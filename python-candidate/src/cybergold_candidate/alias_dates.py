"""V8 Date-string compatibility for retained signed aliases.

Adapted from V8's BSD-licensed dateparser.{h,cc} and dateparser-inl.h.
Copyright 2011 the V8 project authors. See ../../NOTICE-V8.txt.
This preserves an existing parser; it imposes no new timestamp format.
"""
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .aliases import JS_WHITESPACE


MONTHS = {name: index+1 for index, name in enumerate(
    ('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'))}
ZONES = {'ut':0,'utc':0,'z':0,'gmt':0,'cdt':-5,'cst':-6,'edt':-4,'est':-5,
         'mdt':-6,'mst':-7,'pdt':-7,'pst':-8}
END = ('end',None,0)


def tokens(text):
    result=[];i=0
    while i<len(text) and text[i]!='\0':
        char=text[i];start=i;i+=1
        if '0'<=char<='9':
            while i<len(text) and '0'<=text[i]<='9':i+=1
            number=text[start:i].lstrip('0')
            result.append(('number',int(number[:9] or '0'),i-start))
        elif char in ':-+.)':result.append(('symbol',char,1))
        elif char>= 'A' and char not in JS_WHITESPACE:
            while i<len(text) and text[i]>='A' and text[i] not in JS_WHITESPACE:i+=1
            word=text[start:i];lower=''.join(chr(ord(c)+32) if 'A'<=c<='Z' else c for c in word)
            prefix=lower[:3]
            if prefix in MONTHS:kind,value='month',MONTHS[prefix]
            elif lower in ZONES:kind,value='zone',ZONES[lower]
            elif lower in ('am','pm'):kind,value='ampm',0 if lower=='am' else 12
            elif lower=='t':kind,value='separator',0
            else:kind,value='keyword',None
            result.append((kind,value,len(word)))
        elif char in JS_WHITESPACE:result.append(('space',None,1))
        elif char=='(':
            balance=1
            while i<len(text) and text[i]!='\0' and balance:
                if text[i]=='(':balance+=1
                elif text[i]==')':balance-=1
                i+=1
            result.append(('unknown',None,1))
        else:result.append(('unknown',None,1))
    return result+[END]


def milliseconds(token):
    number,length=token[1:]
    return number*10**(3-length) if length<3 else number//10**(min(length,9)-3)


def civil_days(year,month,day):
    year-=month<=2;era=year//400;within=year-era*400
    ordinal=(153*(month+(-3 if month>2 else 9))+2)//5+day-1
    return era*146097+within*365+within//4-within//100+ordinal-719468


def date_milliseconds(text):
    # Apps sign Date.toISOString() strings. Parse that ordinary UTC format
    # directly, without normalizing the signed message or its timestamp bytes.
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', text):
        try:
            delta = datetime.fromisoformat(text) - datetime(1970, 1, 1, tzinfo=timezone.utc)
            return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000
        except ValueError:
            pass  # Retain historical V8 overflow/legacy-client date semantics.
    return legacy_date_milliseconds(text)


def legacy_date_milliseconds(text):
    stream=tokens(text);position=0;days=[];clock=[];month=None;ampm=None
    sign=None;zone_hour=None;zone_minute=None;iso=False
    def peek():return stream[position]
    def next_token():
        nonlocal position
        value=peek()
        if position<len(stream)-1:position+=1
        return value
    def skip(value):
        if peek()[:2]==('symbol',value):next_token();return True
        return False
    def fixed(length,lo,hi):return peek()[0]=='number' and peek()[2]==length and lo<=peek()[1]<=hi
    def expecting(number):return len(clock) in (1,2,3) and 0<=number<=(999 if len(clock)==3 else 59)
    def add(values,number,maximum):
        if len(values)>=maximum:return False
        values.append(number);return True
    def final(number):
        if not add(clock,number,4):return False
        clock.extend([0]*(4-len(clock)));return True
    def parse_iso():
        nonlocal iso,sign,zone_hour,zone_minute
        if peek()[0]=='symbol' and peek()[1] in '+-':
            saved=next_token()
            if not fixed(6,0,999999):return saved
            year=next_token()[1]
            if saved[1]=='-' and year==0:return saved
            days.append(year*(-1 if saved[1]=='-' else 1))
        elif fixed(4,0,9999):days.append(next_token()[1])
        else:return next_token()
        if skip('-'):
            if not fixed(2,1,12):return next_token()
            days.append(next_token()[1])
            if skip('-'):
                if not fixed(2,1,31):return next_token()
                days.append(next_token()[1])
        if peek()[0]!='separator':
            if peek()[0]!='end':return next_token()
        else:
            next_token()
            if not fixed(2,0,24):return None
            hour=next_token()[1];clock.append(hour)
            if not skip(':') or not fixed(2,0,59):return None
            minute=next_token()[1]
            if hour==24 and minute!=0:return None
            clock.append(minute)
            if skip(':'):
                if not fixed(2,0,59):return None
                second=next_token()[1]
                if hour==24 and second!=0:return None
                clock.append(second)
                if skip('.'):
                    if peek()[0]!='number' or hour==24 and peek()[1]!=0:return None
                    clock.append(milliseconds(next_token()))
            if peek()==('zone',0,1):next_token();sign=1;zone_hour=zone_minute=0
            elif peek()[0]=='symbol' and peek()[1] in '+-':
                sign=-1 if next_token()[1]=='-' else 1
                if fixed(4,0,9999):
                    zone_hour,zone_minute=divmod(next_token()[1],100)
                    if zone_hour>23 or zone_minute>59:return None
                else:
                    if not fixed(2,0,23):return None
                    zone_hour=next_token()[1]
                    if not skip(':') or not fixed(2,0,59):return None
                    zone_minute=next_token()[1]
            if peek()[0]!='end':return None
        if zone_hour is None and not clock:sign=1;zone_hour=zone_minute=0
        iso=True;return END
    token=parse_iso()
    if token is None:return math.nan
    has_number=bool(days)
    while token[0]!='end':
        kind,value,length=token
        if kind=='number':
            has_number=True
            if skip(':'):
                if skip(':'):
                    if clock:return math.nan
                    clock.extend([value,0])
                else:
                    if not add(clock,value,4):return math.nan
                    skip('.')
            elif skip('.') and expecting(value):
                clock.append(value)
                if peek()[0]!='number' or not final(milliseconds(next_token())):return math.nan
            elif zone_hour is not None and zone_minute is None and 0<=value<=59:zone_minute=value
            elif expecting(value):
                final(value)
                if peek()[0] not in ('end','space') and peek()!=('zone',0,1) and peek()[:2] not in (('symbol','+'),('symbol','-')):return math.nan
            else:
                if not add(days,value,3):return math.nan
                skip('-')
        elif kind in ('keyword','month','ampm','zone','separator'):
            if kind=='ampm' and clock:ampm=value
            elif kind=='month':month=value;skip('-')
            elif kind=='zone' and has_number:sign=-1 if value<0 else 1;zone_hour=abs(value);zone_minute=0
            elif has_number or peek()[0]=='number':return math.nan
        elif kind=='symbol' and value in '+-' and ((zone_hour==0 and zone_minute==0) or clock):
            sign=-1 if value=='-' else 1;number=digits=0
            if peek()[0]=='number':_,number,digits=next_token()
            has_number=True
            if peek()[:2]==('symbol',':'):zone_hour=number;zone_minute=None
            elif digits in (1,2):zone_hour=number;zone_minute=0
            elif digits in (3,4):zone_hour,zone_minute=divmod(number,100)
            else:return math.nan
        elif kind=='symbol' and value in '+-)' and has_number:return math.nan
        token=next_token()
    if not days:return math.nan
    days.extend([1]*(3-len(days)))
    if month is None:
        if iso or not 1<=days[0]<=31:year,month,day=days
        else:month,day,year=days
    else:
        if not 1<=days[0]<=31:year,day=days[:2]
        else:day,year=days[:2]
    if not iso:
        if 0<=year<=49:year+=2000
        elif 50<=year<=99:year+=1900
    if not 1<=month<=12 or not 1<=day<=31:return math.nan
    clock.extend([0]*(4-len(clock)));hour,minute,second,millisecond=clock
    if ampm is not None:
        if not 0<=hour<=12:return math.nan
        hour=hour%12+ampm
    if not (0<=hour<=23 and 0<=minute<=59 and 0<=second<=59 and 0<=millisecond<=999):
        if hour!=24 or minute or second or millisecond:return math.nan
    stamp=civil_days(year,month,day)*86400000+(hour*3600+minute*60+second)*1000+millisecond
    if sign is not None:
        offset=(zone_hour or 0)*3600+(zone_minute or 0)*60
        if offset>2147483647:return math.nan
        stamp-=sign*offset*1000
    elif time.timezone==0 and not time.daylight:
        pass
    else:
        # Standard IANA timezone data resolves folds using the earlier instant,
        # and gaps using the pre-transition offset, as the retained Date does.
        # Gregorian calendars repeat every 400 years beyond datetime's range;
        # ancient dates use the initial offset, future dates the final rule.
        try:
            zone_name=os.environ.get('TZ','').lstrip(':')
            if zone_name:zone=ZoneInfo(zone_name)
            else:
                with open('/etc/localtime','rb') as stream:zone=ZoneInfo.from_file(stream)
            mapped=year if 1<=year<=9999 else 400+year%400 if year<1 else 2400+year%400
            local=datetime(mapped,month,1)+timedelta(days=day-1,hours=hour,minutes=minute,seconds=second)
            stamp-=int(local.replace(tzinfo=zone,fold=0).utcoffset().total_seconds())*1000
        except (OSError,ZoneInfoNotFoundError,ValueError,OverflowError):
            try:stamp=round(time.mktime((year,month,day,hour,minute,second,0,0,-1))*1000)+millisecond
            except (ValueError,OverflowError):return math.nan
    return stamp if abs(stamp)<=8640000000000000 else math.nan

"""Retained worker authorization, reconcile envelopes and fork transition plan."""
import hmac
import json
import re

from .aliases import JS_WHITESPACE
from .indexer_policy import HASH
from .rpc_http import parse_json

REQUEST_KIND='cybergold-b2b-reconcile-request'
RESPONSE_KIND='cybergold-b2b-reconcile-response'
MODES=['allow-exact-receipt-noop','require-worker-run']


def authorize_worker(header,token):
    def node_bytes(value):
        return value.encode('utf-16-le',errors='surrogatepass').decode('utf-16-le',errors='replace').encode('utf-8')
    if not token or len(node_bytes(token))<32:return 'not-configured'
    if not header or not header.startswith('Bearer '):return 'invalid'
    supplied=node_bytes(header[7:]);expected=node_bytes(token)
    return 'authorized' if len(supplied)==len(expected) and hmac.compare_digest(supplied,expected) else 'invalid'


def unique_object(pairs):
    keys=[key for key,_ in pairs]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate JSON key')
    return dict(pairs)


def parse_reconcile(raw,content_type=None,declared=None):
    if declared is not None and (not re.fullmatch(r'[0-9]+',declared) or int(declared)>4096) or len(raw)>4096:
        raise ValueError('Internal reconcile request is too large')
    if not raw:return {'legacy':True,'mode':'require-worker-run'}
    if not content_type or content_type.split(';',1)[0].strip().lower()!='application/json':
        raise ValueError('Internal reconcile request must use application/json')
    try:
        text=raw.decode('utf-8-sig',errors='strict')
        json.loads(text,object_pairs_hook=unique_object)
        value=parse_json(text)
    except Exception:raise ValueError('Internal reconcile JSON is invalid') from None
    if not isinstance(value,dict) or set(value)!=set(['formatVersion','kind','mode']):
        raise ValueError('Internal reconcile request shape is invalid')
    if (value['kind']!=REQUEST_KIND or type(value['formatVersion']) not in (int,float) or value['formatVersion']!=1
        or value['mode'] not in MODES):raise ValueError('Internal reconcile request identity is invalid')
    return {'legacy':False,'mode':value['mode']}


def reconcile_response(result,legacy):
    status=result['status']
    return {'body':{'status':status} if legacy else {'kind':RESPONSE_KIND,'formatVersion':2,**result},
        'httpStatus':{'reconciled':200,'deferred-cadence':200,'incomplete':202,'busy':409}[status],
        'retryAfter':'1' if status=='busy' else None}


def iso_seconds(seconds):
    # Proleptic Gregorian conversion preserves JS's accepted extended years.
    days,day_seconds=divmod(seconds,86400);z=days+719468;era=z//146097;doe=z-era*146097
    yoe=(doe-doe//1460+doe//36524-doe//146096)//365;year=yoe+era*400
    doy=doe-(365*yoe+yoe//4-yoe//100);mp=(5*doy+2)//153
    day=doy-(153*mp+2)//5+1;month=mp+(3 if mp<10 else -9);year+=month<=2
    year_text=f'{year:04}' if year<=9999 else f'+{year:06}'
    hour,remainder=divmod(day_seconds,3600);minute,second=divmod(remainder,60)
    return f'{year_text}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.000Z'


def history_progress(input):
    start,indexed,head=(input[key] for key in ['startBlock','indexedThroughBlock','networkFinalizedBlock'])
    observed,finalized=(input[key] for key in ['indexedThroughTimestampSeconds','networkFinalizedTimestampSeconds'])
    if (min(start,indexed,head,observed,finalized)<0 or max(observed,finalized)>8640000000000
        or indexed<start or indexed>head or start>head):raise ValueError('Dashboard history progress is invalid')
    total=head-start;completed=indexed-start
    return {'formatVersion':1,'startBlock':str(start),'indexedThroughBlock':str(indexed),
        'indexedThroughDate':iso_seconds(observed),'networkFinalizedBlock':str(head),
        'networkFinalizedDate':iso_seconds(finalized),'percent':100 if total==0 else (completed*10000//total)/100}


def fork_transition(previous,current,deployment_start,current_hash_at_previous):
    for label,anchor in [('previous',previous),('current',current)]:
        if not anchor['generation'].strip(JS_WHITESPACE):raise ValueError(label+' fork generation is missing')
        if anchor['forkBlock']<0:raise ValueError(label+' fork block is negative')
        if not isinstance(anchor['forkBlockHash'],str) or not HASH.fullmatch(anchor['forkBlockHash']):
            raise ValueError(label+' fork block hash is invalid')
    if deployment_start<0:raise ValueError('deployment start block is negative')
    if deployment_start>current['forkBlock']:raise ValueError('deployment start block is above the current fork point')
    old_hash=previous['forkBlockHash'].lower();new_hash=current['forkBlockHash'].lower()
    if previous['generation']==current['generation']:
        if previous['forkBlock']!=current['forkBlock'] or old_hash!=new_hash:
            raise ValueError('fork history changed without a new process generation')
        return {'kind':'unchanged'}
    if (current['forkBlock']>=previous['forkBlock']>=deployment_start
        and isinstance(current_hash_at_previous,str) and HASH.fullmatch(current_hash_at_previous)
        and current_hash_at_previous.lower()==old_hash):
        return {'kind':'reuse-prefix','invalidateFrom':previous['forkBlock']+1,
            'retainedThrough':previous['forkBlock'],'retainedBlockHash':old_hash}
    return {'kind':'full-replay','invalidateFrom':deployment_start,'retainedThrough':None,'retainedBlockHash':None}


def fork_anchor(value):
    if not isinstance(value,dict) or set(value)!=set(['generation','forkBlock','forkBlockHash']):
        raise ValueError('Sandbox fork anchor shape is invalid')
    if (not isinstance(value['generation'],str) or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',value['generation'],re.I)
        or not isinstance(value['forkBlock'],str) or not re.fullmatch(r'(0|[1-9][0-9]*)',value['forkBlock'])
        or not isinstance(value['forkBlockHash'],str) or not HASH.fullmatch(value['forkBlockHash'])):
        raise ValueError('Sandbox fork anchor identity is invalid')
    return {**value,'forkBlock':int(value['forkBlock']),'forkBlockHash':value['forkBlockHash'].lower()}


def parse_fork_request(value):
    if not isinstance(value,dict):raise ValueError('Sandbox fork request shape is invalid')
    if (value.get('kind')!='cybergold-sandbox-fork-generation' or type(value.get('formatVersion')) not in (int,float)
        or value['formatVersion']!=1):raise ValueError('Sandbox fork request identity is invalid')
    action=value.get('action')
    keys=['kind','formatVersion','action','current']+(['previous'] if action=='apply' else [])
    if action not in ('prepare','apply') or set(value)!=set(keys):raise ValueError('Sandbox fork request shape is invalid')
    return {'action':action,**({'previous':fork_anchor(value['previous'])} if action=='apply' else {}),
        'current':fork_anchor(value['current'])}

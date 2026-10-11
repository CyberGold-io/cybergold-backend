"""Actual image date/receipt comparisons; fixtures remain synthetic and local."""
import json
import subprocess
import sys
from pathlib import Path


CODE='''
import json, math, os, sys, time
from cybergold_candidate.alias_dates import date_milliseconds
from cybergold_candidate.reconciliation_receipt import parse_receipt
fixture=json.load(sys.stdin);date_count=0
for profile in fixture['dates']:
    os.environ['TZ']=profile['timezone'];time.tzset()
    for case in profile['values']:
        actual=date_milliseconds(case['text']);expected=case['value']
        assert math.isnan(actual) if expected is None else actual==expected, (profile['timezone'],case,actual)
        date_count+=1
for case in fixture['receipts']['cases']:
    result=error=None
    try:result=parse_receipt(case['raw'])
    except ValueError as failure:error=str(failure)
    assert (result,error)==(case['result'],case['error']),case
print(json.dumps({'result':'pass','nativeDateComparisons':date_count,
    'nativeStoredReceiptComparisons':len(fixture['receipts']['cases']),
    'installedEndpointsOrDatabaseUsed':False}))
'''


if __name__=='__main__':
    fixture={'receipts':json.loads(Path(sys.argv[1]).read_text()),
             'dates':[json.loads(Path(path).read_text()) for path in sys.argv[2:]]}
    result=subprocess.check_output(['docker','run','--rm','--interactive','--entrypoint','python',
        'cybergold-python-candidate:market-parity','-c',CODE],input=json.dumps(fixture),text=True)
    print(result.strip())

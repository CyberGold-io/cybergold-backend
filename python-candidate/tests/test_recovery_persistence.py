import json
from pathlib import Path
import sys

from cybergold_candidate.recovery_persistence import parse_integer,parse_address,transfer,apply_transfer,checkpoint_rows
from test_worker_contract import revive

cases=revive(json.loads(Path(sys.argv[1]).read_text()))
for case in cases:
    value=case['input'];result=None;error=None
    try:
        match case['op']:
            case 'integer':result=parse_integer(value)
            case 'address':result=parse_address(value)
            case 'transfer':result=transfer(value['event'],value['payload'])
            case 'apply':
                balances=dict(value['balances']);apply_transfer(balances,value['value']);result=[list(item) for item in balances.items()]
            case 'checkpoint':result=checkpoint_rows(value)
    except Exception as failure:error=str(failure)
    assert (result,error)==(case['result'],case['error']),(case,result,error)
print(f'PASS: {len(cases)} actual Node/Python recovery transfer replay and checkpoint comparisons')

import asyncio
import json
from pathlib import Path
import sys

from cybergold_candidate.worker_contract import authorize_worker, parse_reconcile, reconcile_response, history_progress, fork_transition, parse_fork_request


def revive(value):
    if isinstance(value,dict):
        if set(value)=={'$bigint'}:return int(value['$bigint'])
        return {key:revive(item) for key,item in value.items()}
    if isinstance(value,list):return [revive(item) for item in value]
    return value


async def run(path):
    cases=revive(json.loads(Path(path).read_text()))
    for case in cases:
        value=case['input'];result=None;error=None
        try:
            match case['op']:
                case 'auth':result=authorize_worker(value['header'],value['token'])
                case 'parse':result=parse_reconcile(value['raw'].encode(),value.get('contentType','application/json'),value.get('declared'))
                case 'response':result=reconcile_response(value['result'],value['legacy'])
                case 'progress':result=history_progress(value)
                case 'fork-plan':result=fork_transition(value['previous'],value['current'],value['deploymentStartBlock'],value['currentHashAtPreviousForkBlock'])
                case 'fork-parse':result=parse_fork_request(value)
        except Exception as failure:error=str(failure)
        assert (result,error)==(case['result'],case['error']),(case,result,error)
    print(f'PASS: {len(cases)} actual Node/Python worker authorization, reconcile contract and fork transition comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

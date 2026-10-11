import asyncio
import json
from pathlib import Path
import sys

from cybergold_candidate.adaptive_logs import execute_ranges
from test_indexer import decode


async def run(path):
    cases=decode(json.loads(Path(path).read_text()))
    for case in cases:
        value=case['input'];calls=[];result=None;error=None
        async def request(attempt):
            calls.append(attempt)
            if attempt['range']['toBlock']-attempt['range']['fromBlock']+1>value['maximumWidth']:
                raise RuntimeError('range-limit')
            return [str(attempt['range']['fromBlock'])]
        async def validate(response,_value):return response
        try:
            result=await execute_ranges(value['baseRange'],request,validate,lambda _error:value['approved'],
                **{key:item for key,item in value.items() if key in ('maxAttempts','maxRanges','maxCardinality')})
        except ValueError as failure:error=str(failure)
        assert (result,error,calls)==(case['result'],case['error'],case['calls']),case
    print(f'PASS: {len(cases)} actual Node adaptive journal request/error/order comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

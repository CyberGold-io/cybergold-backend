import asyncio
import json
from pathlib import Path
import sys

from cybergold_candidate.indexer_policy import (identity_transition,finalized_anchor,deployment_start,
    projection_scan,planning_boundary,anchor_tag,finalized_profile,snapshot_matches)
from cybergold_candidate.raw_journal import normalize_rpc_logs,parse_coverage,replay_coverage,merge_coverage,stored_logs


def decode(value):
    if isinstance(value,dict):
        if set(value)=={'$bigint'}:return int(value['$bigint'])
        return {key:decode(item) for key,item in value.items()}
    if isinstance(value,list):return [decode(item) for item in value]
    return value


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        value=decode(case['input']);result=None;error=None;header_calls=0
        try:
            match case['op']:
                case 'identity':result=identity_transition(value['stored'],value['expected'])
                case 'anchor':
                    # Node's rejected number fixture has typeof number, rather
                    # than bigint. Preserve that typed transport distinction.
                    raw=case['input'].get('number')
                    if raw is not None and not isinstance(raw,dict):
                        raise ValueError('Finalized RPC anchor is incomplete or invalid')
                    result=finalized_anchor(value)
                case 'deployment':result=deployment_start(value['chainId'],value['configuredStartBlock'],value['anchorBlock'])
                case 'scan':result=projection_scan(**value)
                case 'boundary':result=planning_boundary(**value)
                case 'tag':result=anchor_tag(value)
                case 'profile':result=finalized_profile(value)
                case 'snapshot':result=snapshot_matches(**value)
                case 'rpc':
                    async def header(_number):
                        nonlocal header_calls
                        header_calls+=1
                        candidate=dict(value['header'])
                        if not isinstance(case['input']['header']['timestamp'],dict):
                            candidate['timestamp']=float(candidate['timestamp'])
                        return candidate
                    result=await normalize_rpc_logs(value['value'],value['expectedAddress'],value['fromBlock'],value['toBlock'],header)
                case 'coverage':result=parse_coverage(**value)
                case 'replay':result=replay_coverage(**value)
                case 'merge':result=merge_coverage(**value)
                case 'stored':result=stored_logs(**value)
        except ValueError as failure:error=str(failure)
        assert (result,error,header_calls)==(decode(case['result']),case['error'],case['headerCalls']),case
    print(f'PASS: {len(cases)} actual Node indexer identity, finality, raw-log and journal coverage comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

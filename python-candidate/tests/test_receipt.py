import json
from pathlib import Path
import sys

from cybergold_candidate.reconciliation_receipt import RpcCounter,create_receipt,parse_receipt


def main(path):
    fixture=json.loads(Path(path).read_text())
    for case in fixture['cases']:
        result=error=None
        try:result=parse_receipt(case['raw'])
        except ValueError as failure:error=str(failure)
        assert (result,error)==(case['result'],case['error']),case
    input=fixture['input'];input['finalizedAnchor']['blockNumber']=int(input['finalizedAnchor']['blockNumber'])
    for role in ('dashboardProjection','stateSnapshot'):input[role]['blockNumber']=int(input[role]['blockNumber'])
    for role in ('rawJournal','safeCursors'):
        for cursor in input[role]['cursors']:cursor['blockNumber']=int(cursor['blockNumber'])
    for case in fixture['creations']:
        result=error=None
        try:result=create_receipt({**input,'completedAtMs':case['completedAtMs']})
        except ValueError as failure:error=str(failure)
        assert (result,error)==(case['result'],case['error']),case
    counter=RpcCounter();counter.plan('core-address');counter.log_attempt('core-address');counter.gateway_attempt('eth_getLogs')
    counter.log_attempt('core-address',True);counter.gateway_attempt('eth_getLogs');counter.log_failure();counter.gateway_failure()
    for method in ('eth_call','eth_chainId','eth_getBlockByHash','eth_getBlockByNumber','eth_getCode'):counter.gateway_attempt(method)
    before=counter.snapshot()
    try:counter.gateway_attempt('eth_sendRawTransaction')
    except ValueError as failure:assert str(failure)==fixture['counts']['rejected']
    else:raise AssertionError('Existing indexer method policy changed')
    counter.gateway_attempt('eth_call')
    assert before==fixture['counts']['before'] and counter.snapshot()==fixture['counts']['after']
    print(f"PASS: {len(fixture['cases'])} actual Node/Python stored receipt and {len(fixture['creations'])} construction comparisons; RPC counters preserve attempts/failures and prior snapshots")


if __name__=='__main__':main(sys.argv[1])

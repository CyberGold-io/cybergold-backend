import asyncio
import copy
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import sys

from cybergold_candidate.completed_state import CompletedState,IDENTITY


class Rows:
    def __init__(self,values):self.values=values
    async def fetchall(self):return self.values
    async def fetchone(self):return self.values[0] if self.values else None


class FixtureDatabase:
    def __init__(self,fixture):self.fixture=fixture;self.calls=[]
    @asynccontextmanager
    async def connection(self):yield self
    @asynccontextmanager
    async def transaction(self):yield self
    async def execute(self,sql,params):
        value=self.fixture
        if 'INSERT INTO' in sql or 'DELETE FROM' in sql:
            self.calls.append({'operation':'delete' if 'DELETE FROM' in sql else 'put','params':list(params)})
            return Rows([])
        if 'model_count' in sql:return Rows([{'model_count':str(value['modelCount'])}])
        if 'row_count' in sql:
            key='raw' if 'onchain_raw_logs' in sql else 'models' if 'onchain_read_model_snapshots' in sql else 'safe' if len(params)==3 else 'events'
            return Rows([{'row_count':value['counts'][key]}])
        if 'SELECT state_value' in sql:
            address,key=params[1:]
            if value.get('queryErrorKey')==key:raise RuntimeError('synthetic query failure')
            state=value['states'].get(address,{})
            return Rows([{'state_value':state[key]}] if key in state else [])
        addresses=params[1] if isinstance(params[1],list) else [params[1]]
        return Rows([{'contract_address':address,'state_key':key,'state_value':item}
            for address in addresses for key,item in value['states'].get(address,{}).items() if key in params[2]])


async def main(path):
    fixture=json.loads(Path(path).read_text())
    assert IDENTITY==json.loads(Path('src/server/onchain-indexer/snapshot-identity.json').read_text())
    for case in fixture['cases']:
        database=FixtureDatabase(case);runtime=copy.deepcopy(case['runtime']);result=error=None
        try:result=await CompletedState(database,case['config']).receipt(runtime,case['now'])
        except Exception as failure:error=str(failure)
        assert (result,error,runtime)==(case['result'],case['error'],case['runtimeAfter']),{
            'case':case,'actual':(result,error,runtime)}
    for case in fixture['commits']:
        database=FixtureDatabase({});checkpoint=copy.deepcopy(case['checkpoint'])
        checkpoint['coreCursor']['blockNumber']=int(checkpoint['coreCursor']['blockNumber'])
        for cursor in checkpoint['safeCursors']:cursor['blockNumber']=int(cursor['blockNumber'])
        lease=SimpleNamespace(reconciliation_id=case['lease']['reconciliationId'],config_revision=case['lease']['configRevision'])
        await CompletedState(database,fixture['config']).commit(lease,checkpoint,case['receipt'])
        assert database.calls==case['calls'],{'actual':database.calls,'case':case}
    for case in fixture['builds']:
        value={'states':{fixture['config']['coreAddress']:case['states']},'counts':case['counts']}
        database=FixtureDatabase(value);checkpoint=copy.deepcopy(case['checkpoint']);anchor=copy.deepcopy(case['lease']['finalizedAnchor'])
        anchor['blockNumber']=int(anchor['blockNumber']);checkpoint['coreCursor']['blockNumber']=int(checkpoint['coreCursor']['blockNumber'])
        for field in ('safeCursors','rawCursors'):
            for cursor in checkpoint[field]:cursor['blockNumber']=int(cursor['blockNumber'])
        lease=SimpleNamespace(reconciliation_id=case['lease']['reconciliationId'],config_revision=case['lease']['configRevision'],finalized_anchor=anchor)
        result=error=None
        try:result=await CompletedState(database,fixture['config']).build_receipt(lease,checkpoint,fixture['receipt']['rpcRequests'],1790762400098,1790762400123)
        except ValueError as failure:error=str(failure)
        assert (result,error)==(case['result'],case['error']),{'case':case,'actual':(result,error)}
    print(f"PASS: {len(fixture['cases'])} actual retained Node/Python coherent completion reads and "
        f"{len(fixture['commits'])} exact commit/deletion bindings and {len(fixture['builds'])} durable count/construction comparisons; identities unchanged")


if __name__=='__main__':asyncio.run(main(sys.argv[1]))

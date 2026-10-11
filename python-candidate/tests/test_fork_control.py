"""Control-order parity with the retained Node functions; RPC is synthetic."""
import asyncio
from contextlib import asynccontextmanager
import copy
import json
import sys
from cybergold_candidate.fork_control import ForkControl
from test_fork_recovery import Cursor,wire

async def check(cases):
    for case in cases:
        calls=[];runtime={'lastReconciledAtMs':12,'lastReconciliationReceipt':{'retained':True}}
        config=copy.deepcopy(case['config']);input=copy.deepcopy(case['input']);mode=case['mode']
        if config:
            config['chainId']=int(config['chainId']);config['startBlock']=int(config['startBlock'])
        for key in ['previous','current']:input[key]['forkBlock']=int(input[key]['forkBlock'])
        class Database:
            async def ensure_schema(self):
                calls.append('schema')
                if mode=='schema-error':raise RuntimeError('fixture schema failure')
            @asynccontextmanager
            async def advisory_lock(self,key):calls.append('lock:'+key);yield mode!='busy'
            @asynccontextmanager
            async def connection(self):yield self
            @asynccontextmanager
            async def transaction(self):calls.append('transaction');yield self
            async def execute(self,sql,params):
                calls.append('query')
                if mode=='db-error':raise RuntimeError('fixture database failure')
                if sql.strip().startswith('SELECT') and len(params)==3:
                    previous=input['previous']
                    return Cursor([{'state_key':key,'state_value':value} for key,value in zip(
                        ['sandbox_fork_generation','sandbox_fork_block','sandbox_fork_block_hash','sandbox_fork_projection_status'],
                        [previous['generation'],str(previous['forkBlock']),previous['forkBlockHash'],'ready'])])
                if sql.strip().startswith('SELECT'):return Cursor([{'state_key':'last_scanned_block','state_value':'900'}])
                return Cursor([])
        class Client:
            async def chain_id(self):calls.append('chain');return 1 if mode=='rpc-chain' else 31338
            async def block(self,number):
                calls.append('block:'+str(number))
                if mode=='rpc-error':raise RuntimeError('fixture RPC failure')
                current=number==input['current']['forkBlock']
                return {'number':42 if current and mode=='current-number' or not current and mode=='previous-number' else number,
                    'hash':input['previous']['forkBlockHash'] if not current or mode=='current-hash' else input['current']['forkBlockHash']}
            async def close(self):pass
        controller=ForkControl(Database(),config,runtime,lambda _:Client())
        try:result=await controller.status() if case['action']=='status' else await controller.transition(input);actual={'result':wire(result)}
        except Exception as error:actual={'error':str(error)}
        actual.update(calls=calls,runtime=runtime)
        assert actual==case['expected'],(case,actual)
    print(f'PASS: {len(cases)} retained fork control configuration, lock, RPC/header and transaction paths')

if __name__=='__main__':asyncio.run(check(json.load(open(sys.argv[1]))))

import asyncio
import json
from pathlib import Path
import sys

from cybergold_candidate.recovery_reader import RecoveryPortfolioReader

def asset(index):return '0x'+format(index,'040x')


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls={};clock=0;current_hash='0x'+'a'*64;fail_once=True
        def call(name):calls[name]=calls.get(name,0)+1
        class Reader:
            core=asset(1000);chain_id=31338
            async def block(self,requested):
                call('block');return {'number':9007199254740993,'hash':requested or current_hash}
            async def assert_canonical(self,_block):
                call('canonical')
                if case.get('fault')=='canonical':raise ValueError('fixture-canonical-change')
            async def count(self,_block):
                nonlocal fail_once
                call('count')
                if case.get('fault')=='count' or case.get('sequence')=='retry-page' and fail_once:
                    fail_once=False;raise ValueError('fixture-count-error')
                return case['total']
            async def assets(self,_block,offset):
                call('assets');length=min(max(case['total']-offset,0),64)
                values=[asset(offset+i+1) for i in range(length)]
                if case.get('fault')=='duplicate-assets' and len(values)>1:values[1]=values[0]
                return values,999 if case.get('fault')=='next' else min(offset+length,case['total'])
            async def paused(self,_block):call('paused');return False
            async def pools(self,_block,assets):
                call('pools');values=[{'asset':value,'externalShares':'9007199254740993',
                    'custody':{'liveBalanceAvailable':case.get('fault')!='custody'}} for value in assets]
                if case.get('fault')=='pool-count':values.pop()
                if case.get('fault')=='pool-order':values.reverse()
                return values
            async def balances(self,_block,_holder,assets):
                call('balances');values=[-1 if case.get('fault')=='negative-balance' else
                    9007199254740994 if case.get('fault')=='excess-balance' else
                    9007199254740993 if index%2==0 else 0 for index,_ in enumerate(assets)]
                if case.get('fault')=='balance-count':values.pop()
                return values
            async def preview(self,*_args):
                call('preview')
                if case.get('fault')=='preview':raise ValueError('fixture-preview')
                return 2**256-1
            async def fund(self,*_args):
                call('fund')
                if case.get('fault')=='fund':raise ValueError('fixture-fund')
                return {'status':{'configured':False,'available':False,'reason':'not-configured','problem':None,
                    'governance':None,'governancePaused':None},'offers':[]}
        load=RecoveryPortfolioReader(Reader(),lambda:clock)
        async def read(holder=asset(1001),offset=None,block_hash='default'):
            offset=case['offset'] if offset is None else offset
            block_hash=('0x'+'a'*64 if offset else None) if block_hash=='default' else block_hash
            try:return {'result':await load.get(holder,offset,block_hash)}
            except Exception as error:return {'error':str(error)}
        sequence=case.get('sequence')
        results=await asyncio.gather(read(),read()) if sequence=='concurrent' else [await read()]
        if sequence and sequence!='concurrent':
            if sequence=='expired':clock=10000
            if sequence=='same-height-reset':current_hash='0x'+'b'*64
            results.append(await read(asset(1002) if sequence=='different-holder' else asset(1001),
                1 if sequence=='continuation-without-hash' else None,
                None if sequence=='continuation-without-hash' else 'default'))
        assert (results,calls)==(case['results'],case['calls']),(case,results,calls)
        await load.close()
    print(f'PASS: {len(cases)} actual Node/Python recovery snapshot, pagination, cache and optional-failure comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

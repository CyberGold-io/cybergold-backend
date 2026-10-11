import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from aiohttp import web
from web3 import Web3

from cybergold_candidate.recovery_reader import RecoveryPortfolioReader
from cybergold_candidate.recovery_rpc import RecoveryRpc, ABI


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[];private_headers=[]
        async def respond(request):
            body=await request.json();private_headers.append(request.headers.get('authorization'))
            method=body['method'];fault=case['fault']
            if method=='eth_chainId':result='0x1' if fault=='chain' else '0x7a6a'
            elif method.startswith('eth_getBlock'):
                result={'hash':'0x'+'b'*64 if fault=='canonical' and body['params'][0]!='latest' else case['hash'],
                    'number':'0x20000000000001','timestamp':'0x1'}
            else:
                assert method=='eth_call'
                contract='core' if body['params'][0]['to'].lower()==case['core'] else 'governance'
                route=next(route for route in case['routes'] if route['contract']==contract and route['selector']==body['params'][0]['data'][:10])
                decoded_contract=Web3().eth.contract(abi=ABI[contract])
                function,args=decoded_contract.decode_function_input(body['params'][0]['data'])
                def wire(value):
                    if type(value) is int:return str(value)
                    if isinstance(value,(list,tuple)):return [wire(item) for item in value]
                    return value
                calls.append({'contract':contract,'name':function.fn_name,'args':wire(list(args.values())),'target':body['params'][1]})
                if route['response'] is None:
                    return web.json_response({'jsonrpc':'2.0','id':body['id'],'error':{'code':-32000,'message':'fixture-private-rpc'}})
                result=route['response']
            return web.json_response({'jsonrpc':'2.0','id':body['id'],'result':result})
        app=web.Application();app.router.add_post('/',respond)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        settings=SimpleNamespace(RPC_URL=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/',
            RPC_AUTHORIZATION='Bearer fixture-private',NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=case['core'],
            NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None if case['fault']=='not-configured' else case['governance'])
        rpc=RecoveryRpc(settings);load=RecoveryPortfolioReader(rpc)
        try:
            try:outcome={'result':await load.get(case['holder'])}
            except Exception as error:outcome={'error':str(error)}
            assert outcome==case['outcome'],(case['fault'],outcome,case['outcome'])
            normalize=lambda values:sorted(json.dumps(item,sort_keys=True) for item in values)
            assert normalize(calls)==normalize(case['calls']),(case['fault'],calls,case['calls'])
            assert private_headers and all(value=='Bearer fixture-private' for value in private_headers)
        finally:
            await load.close();await rpc.close();await runner.cleanup()
    print(f'PASS: {len(cases)} actual Viem/Web3.py recovery portfolios, ABI calls and canonical hash targets over native loopback HTTP')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

"""Native fixed-hash replay compared with the actual standard Wagmi call shape."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from eth_abi import encode
import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.transaction_revert import TransactionRevert, TransactionRevertRpc

HASH='0x'+'a'*64
DATA=Web3.to_hex(Web3.keccak(text='Error(string)')[:4]+encode(['string'],['Synthetic rejection']))
SETTINGS=SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338')


class Provider(AsyncBaseProvider):
    def __init__(self, transaction=None, result='0x1234', error=None, chain='0x7a6a', blocked=False):
        super().__init__();self.transaction,self.result,self.error,self.chain,self.blocked=transaction,result,error,chain,blocked
        self.calls=[];self.started=asyncio.Event();self.cancelled=False

    async def make_request(self, method, params):
        self.calls.append((method,params))
        if method=='eth_chainId':value=self.chain
        elif method=='eth_getTransactionByHash':value=self.transaction
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:self.cancelled=True;raise
            if self.error:return {'jsonrpc':'2.0','id':1,'error':self.error}
            value=self.result
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':value}

    async def disconnect(self):pass


def service(provider):return TransactionRevert(SETTINGS,TransactionRevertRpc(SETTINGS,AsyncWeb3(provider)))


class RevertTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_native_transaction_fields_match_actual_wagmi_replay(self):
        for row in ROWS:
            provider=Provider(row['transaction']);value=await service(provider).get(HASH)
            self.assertEqual(value['data'],'0x1234')
            call=next((method,params) for method,params in provider.calls if method=='eth_call')
            self.assertEqual(json.loads(json.dumps(call)),[row['call']['method'],row['call']['params']])
            self.assertEqual(value['transactionHash'],HASH)
            self.assertFalse(value['reverted'])

    async def test_native_revert_data_and_empty_return_are_preserved(self):
        for provider,expected in ((Provider(ROWS[0]['transaction'],error={'code':3,'message':'execution reverted private provider text','data':DATA}),{'data':DATA,'reverted':True}),
                                  (Provider(ROWS[0]['transaction'],result='0x'),{'data':None,'reverted':False})):
            value=await service(provider).get(HASH)
            self.assertEqual({key:value[key] for key in ('data','reverted')},expected)

    async def test_absence_outage_wrong_chain_and_unconfigured_are_unavailable(self):
        for reader in (None,service(Provider()),service(Provider(ROWS[0]['transaction'],error={'code':-32000,'message':'https://password@private.invalid'})),service(Provider(chain='0x1'))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(transaction_revert=reader)),base_url='http://fixture') as client:
                response=await client.get('/api/transaction/revert',params={'hash':HASH})
                self.assertEqual(response.status_code,503)
                self.assertNotIn('password',response.text)
                self.assertNotIn('data',response.json())
                self.assertEqual(response.headers['cache-control'],'no-store')

    async def test_http_cannot_select_new_calldata_provider_or_account(self):
        provider=Provider(ROWS[0]['transaction'])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(transaction_revert=service(provider))),base_url='http://fixture') as client:
            response=await client.get('/api/transaction/revert',params={'hash':HASH,'data':'0x6666','provider':'ignored','account':'ignored'})
            self.assertEqual(response.status_code,200)
            self.assertEqual((await client.head('/api/transaction/revert',params={'hash':HASH})).status_code,200)
            self.assertEqual((await client.get('/api/transaction/revert',params={'hash':'invalid'})).status_code,400)
            self.assertIn('operation="/api/transaction/revert"',(await client.get('/metrics')).text)
        self.assertNotIn('ignored',json.dumps(provider.calls))
        self.assertTrue(all(params[0]['data']=='0x1234' for method,params in provider.calls if method=='eth_call'))
        self.assertFalse(any(method.startswith('eth_send') for method,_ in provider.calls))

    async def test_disconnect_cancels_native_replay(self):
        provider=Provider(ROWS[0]['transaction'],blocked=True);task=asyncio.create_task(service(provider).get(HASH))
        await asyncio.wait_for(provider.started.wait(),2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)


if __name__=='__main__':
    import sys
    ROWS=json.loads(Path(sys.argv.pop()).read_text());unittest.main()

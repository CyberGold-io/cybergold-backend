"""Exercise native ENS decoding/forward verification through the fixed APIs."""
import asyncio
from types import SimpleNamespace
import unittest

from eth_abi import decode, encode
from ens.constants import UNIVERSAL_RESOLVER_ADDR
import httpx
from web3 import AsyncWeb3, Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.ens_records import EnsRecords
from cybergold_candidate.protocol_facts import ProtocolFactsRpc
from test_native_balance import ADDRESS, HASH, Provider

NAME='alice.eth'
RESOLVER='0x'+'3'*40
NFT='0x'+'4'*40


class EnsProvider(Provider):
    def __init__(self, name=NAME, holder=ADDRESS, avatar='ipfs://bafy-fixture', token_uri='ipfs://nft-fixture/{id}.json', nft_failure=False, **kwargs):
        super().__init__(**kwargs)
        self.name,self.holder,self.avatar=name,holder,avatar
        self.ens_calls=[]
        self.nft_calls=[]
        self.token_uri,self.nft_failure=token_uri,nft_failure

    async def make_request(self, method, params):
        if method != 'eth_call':return await super().make_request(method, params)
        self.calls.append((method,params))
        if params[0]['to'].lower()==NFT.lower():
            assert params[1]=={'blockHash':HASH,'requireCanonical':True}
            data=bytes.fromhex(params[0]['data'][2:])
            self.nft_calls.append((data[:4],decode(['uint256'],data[4:])[0]))
            if self.nft_failure:return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://password@private.invalid'}}
            return {'jsonrpc':'2.0','id':1,'result':Web3.to_hex(encode(['string'],[self.token_uri]))}
        self.assert_call(params)
        self.started.set()
        if self.blocked:
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:self.cancelled=True;raise
        if self.failure:return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://password@private.invalid'}}
        dns,inner=decode(['bytes','bytes'],bytes.fromhex(params[0]['data'][10:]))
        selector=inner[:4]
        self.ens_calls.append((dns,selector))
        if selector==Web3.keccak(text='name(bytes32)')[:4]:result=encode(['string'],[self.name])
        elif selector==Web3.keccak(text='addr(bytes32)')[:4]:result=encode(['address'],[self.holder])
        elif selector==Web3.keccak(text='text(bytes32,string)')[:4]:
            _,key=decode(['bytes32','string'],inner[4:]);assert key=='avatar'
            result=encode(['string'],[self.avatar])
        else:raise AssertionError(selector.hex())
        return {'jsonrpc':'2.0','id':1,'result':Web3.to_hex(encode(['bytes','address'],[result,RESOLVER]))}

    @staticmethod
    def assert_call(params):
        assert params[0]['to'].lower()==UNIVERSAL_RESOLVER_ADDR.lower()
        assert params[1]=={'blockHash':HASH,'requireCanonical':True}


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CHAIN_ID='31338',NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=ADDRESS,
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return EnsRecords(settings,ProtocolFactsRpc(settings,AsyncWeb3(provider)))


class EnsTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_primary_name_verifies_forward_address_at_same_hash(self):
        provider=EnsProvider();value=await service(provider).get('name',ADDRESS)
        self.assertEqual(value['name'],NAME)
        self.assertEqual(value['holder'],ADDRESS)
        self.assertEqual(value['context']['blockHash'],HASH)
        self.assertEqual(len(provider.ens_calls),2)
        self.assertTrue(provider.ens_calls[0][0].endswith(b'\x04addr\x07reverse\x00'))
        self.assertEqual(provider.ens_calls[1][0],b'\x05alice\x03eth\x00')

    async def test_absent_and_forward_mismatched_names_are_null(self):
        for provider in (EnsProvider(name=''),EnsProvider(holder='0x'+'2'*40)):
            self.assertIsNone((await service(provider).get('name',ADDRESS))['name'])

    async def test_avatar_text_record_is_preserved_and_not_fetched(self):
        for record in ('https://avatar.invalid/a.png','ipfs://bafy-fixture','eip155:1/erc721:0x'+'4'*40+'/2',''):
            provider=EnsProvider(avatar=record)
            value=await service(provider).get('avatar',NAME)
            self.assertEqual(value['avatarRecord'],record or None)
            self.assertEqual(len(provider.ens_calls),1)

    async def test_http_validation_normalization_and_native_head(self):
        provider=EnsProvider();app=create_app(ens_records=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            response=await client.get('/api/account/ens-avatar-record',params={'name':'ALICE.eth','resolver':'ignored'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['name'],NAME)
            self.assertEqual((await client.head('/api/account/ens-name',params={'holder':ADDRESS})).status_code,200)
            for path,params in (('/api/account/ens-name',{'holder':'invalid'}),('/api/account/ens-avatar-record',{}),('/api/account/ens-avatar-record',{'name':'a..eth'})):
                self.assertEqual((await client.get(path,params=params)).status_code,400)
            self.assertIn('operation="/api/account/ens-name"',(await client.get('/metrics')).text)

    async def test_nft_standard_uri_reads_preserve_wide_ids_and_same_canonical_hash(self):
        for namespace,method,token in [('erc721','tokenURI',str(2**200)),('erc1155','uri','0x'+format(2**200,'x'))]:
            provider=EnsProvider(avatar=f'eip155:1/{namespace}:{NFT}/{token}')
            value=await service(provider).get('avatar',NAME)
            self.assertEqual(value['nftTokenUri'],{'status':'success','value':provider.token_uri})
            self.assertEqual(provider.nft_calls,[(Web3.keccak(text=method+'(uint256)')[:4],2**200)])
            self.assertEqual(len(provider.ens_calls),1)
            self.assertEqual(value['context']['blockHash'],HASH)

    async def test_nft_failure_keeps_record_with_redacted_per_read_failure(self):
        record=f'eip155:1/erc721:{NFT}/2'
        value=await service(EnsProvider(avatar=record,nft_failure=True)).get('avatar',NAME)
        self.assertEqual(value['avatarRecord'],record)
        self.assertEqual(value['nftTokenUri'],{'status':'failure','error':'avatar-token-uri-unavailable'})
        self.assertNotIn('password',str(value))
        self.assertEqual((await service(EnsProvider(avatar='eip155:1/erc721:invalid/2')).get('avatar',NAME))['nftTokenUri']['status'],'failure')

    async def test_native_failures_and_reorg_are_redacted_unavailable(self):
        for provider in (EnsProvider(failure=True),EnsProvider(reorg=True),EnsProvider(chain='0x1')):
            app=create_app(ens_records=service(provider))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                response=await client.get('/api/account/ens-name',params={'holder':ADDRESS})
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertNotIn('password',response.text)
                self.assertNotIn('name',response.json())

    async def test_cancellation_stops_native_ens_call(self):
        provider=EnsProvider(blocked=True);task=asyncio.create_task(service(provider).get('name',ADDRESS))
        await asyncio.wait_for(provider.started.wait(),2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)


if __name__=='__main__':unittest.main()

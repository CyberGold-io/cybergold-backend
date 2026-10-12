"""Web3.py ABI calls at the retained EIP-1898 canonical snapshot identity."""
import asyncio
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from eth_utils.abi import collapse_if_tuple
from web3 import AsyncWeb3, Web3

from .recovery_lenses import reconcile, fund_terms, treasury_accounting
from .rpc_transport import rpc_provider

ABI=json.loads(Path(__file__).with_name('recovery-rpc-abi.json').read_text())
ZERO='0x'+'0'*40


class RecoveryApiError(Exception):
    def __init__(self,message,status=503,retry=None):
        super().__init__(message);self.status,self.retry=status,retry


class SnapshotChanged(RecoveryApiError):
    """The existing canonical header check disproved the pinned snapshot."""


def abi_value(value,parameter):
    array=re.fullmatch(r'(.*)\[([0-9]*)\]',parameter['type'])
    if array:return [abi_value(item,{**parameter,'type':array[1]}) for item in value]
    if parameter['type']=='tuple':
        components=parameter['components']
        converted=[abi_value(item,component) for item,component in zip(value,components,strict=True)]
        return dict(zip((component['name'] for component in components),converted,strict=True)) if all(
            component.get('name') for component in components) else converted
    if parameter['type']=='address':return Web3.to_checksum_address(value)
    return value


class RecoveryRpc:
    def __init__(self,settings,w3=None):
        url=settings.RPC_URL;core=settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS;chain=settings.NEXT_PUBLIC_CHAIN_ID
        split=urlsplit(url or '')
        if split.scheme not in ('http','https') or not split.hostname or not core or not chain or not re.fullmatch(r'[1-9][0-9]*',chain):
            raise RecoveryApiError('Recovery RPC, Core address or chain is not configured')
        self.core=Web3.to_checksum_address(core)
        if self.core==ZERO:raise RecoveryApiError('Recovery Core address is not configured')
        self.chain_id=int(chain);self.governance=settings.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS
        self.w3=w3 or AsyncWeb3(rpc_provider(url,settings.RPC_AUTHORIZATION))
        self.contracts={name:self.w3.eth.contract(abi=values) for name,values in ABI.items()}

    async def close(self):await self.w3.provider.disconnect()

    async def call(self,contract,address,name,block,args=()):
        abi=next(item for item in ABI[contract] if item['name']==name)
        data=self.contracts[contract].encode_abi(name,args=[abi_value(value,parameter)
            for value,parameter in zip(args,abi['inputs'],strict=True)])
        # Web3 contract.call resolves hashes to numbers. Keep the accepted
        # hash/requireCanonical form by using its standard provider + ABI codec.
        response=await self.w3.provider.make_request('eth_call',[{'to':address,'data':data},
            {'blockHash':block['hash'],'requireCanonical':True}])
        if 'error' in response:raise ValueError('Recovery contract RPC failed')
        decoded=self.w3.codec.decode([collapse_if_tuple(output) for output in abi['outputs']],bytes.fromhex(response['result'][2:]))
        values=[abi_value(value,output) for value,output in zip(decoded,abi['outputs'],strict=True)]
        return values[0] if len(values)==1 else values

    async def block(self,block_hash):
        chain,value=await asyncio.gather(self.w3.eth.chain_id,self.w3.eth.get_block(block_hash or 'latest'))
        if chain!=self.chain_id:raise ValueError('Recovery RPC chain mismatch')
        if value.get('hash') is None or value.get('number') is None:raise ValueError('Recovery block is unavailable')
        return {'hash':Web3.to_hex(value['hash']),'number':value['number']}

    async def assert_canonical(self,block):
        value=await self.w3.eth.get_block(block['number'])
        if value.get('hash') is None or Web3.to_hex(value['hash']).lower()!=block['hash'].lower():
            raise SnapshotChanged('Recovery snapshot changed; restart discovery',retry=1)

    async def count(self,block):return await self.call('core',self.core,'outstandingRecoveryAssetCount',block)
    async def assets(self,block,offset):return await self.call('core',self.core,'outstandingRecoveryAssets',block,[offset,64])
    async def paused(self,block):return await self.call('core',self.core,'paused',block)

    async def pools(self,block,assets):
        async def read(asset):
            pool,lifecycle,custody=await asyncio.gather(*(self.call('core',self.core,name,block,[asset]) for name in (
                'recoveryPool','reserveLifecycle','reserveCustodyStatus')))
            pool={**pool,'asset':asset,'totalShares':pool['coreAttachedShares']+pool['externalShares']}
            pool={key:str(value) if type(value) is int and key!='shareDecimals' else value for key,value in pool.items()}
            lifecycle={**lifecycle,'asset':asset,'exitEntitlementRaw':str(lifecycle['exitEntitlementRaw'])}
            custody={key:str(value) if type(value) is int and key!='lifecycle' else value for key,value in custody.items()}
            return reconcile(pool,lifecycle,custody)
        return await asyncio.gather(*(read(asset) for asset in assets))

    async def balances(self,block,holder,assets):
        return await self.call('core',self.core,'balanceOfBatch',block,[[holder]*len(assets),[int(asset,16) for asset in assets]]) if assets else []

    async def preview(self,block,asset,shares):return await self.call('core',self.core,'previewRedeemRecoveryShares',block,[asset,shares])

    async def fund(self,block,_holder,entries):
        if not self.governance or self.governance.lower()==ZERO:
            return {'status':{'configured':False,'available':False,'reason':'not-configured','problem':None,
                'governance':None,'governancePaused':None},'offers':[]}
        governance=Web3.to_checksum_address(self.governance)
        trusted,paused,treasury=await asyncio.gather(*(self.call('governance',governance,name,block) for name in (
            'trustedRecoveryFundCore','paused','recoveryFundTreasuryStatus')))
        if trusted.lower()!=self.core.lower():raise ValueError('Fund Core mismatch')
        deficit=treasury_accounting(*treasury)['deficit']
        async def offer(entry):
            try:
                terms=await self.call('governance',governance,'assetRecoveryFund',block,[entry['pool']['asset']])
                current=fund_terms(terms)
                if not current['active']:return None
                if deficit>0:return {'available':False,'generation':str(terms['generation']),
                    'problem':'Fund treasury is below its commitments'}
                shares=int(entry['balanceRaw']);accepted=min(shares,current['remainingCoverageShares'])
                generation,amount=await self.call('governance',governance,'previewAssetRecoveryFundPurchase',block,
                    [entry['pool']['asset'],accepted])
                if generation!=terms['generation']:raise ValueError('Fund preview generation mismatch')
                return {'available':True,'impairedAsset':entry['pool']['asset'],'generation':str(generation),
                    'governancePaused':paused,'holderShares':entry['balanceRaw'],'acceptedShares':str(accepted),
                    'remainingCapacity':str(current['remainingCoverageShares']),'cygldToken':self.core,'cygldAmount':str(amount)}
            except Exception:return {'available':False,'generation':'0','problem':'Fund offer unavailable'}
        return {'status':{'configured':True,'available':True,'reason':None,'problem':None,
            'governance':governance,'governancePaused':paused},'offers':await asyncio.gather(*(offer(entry) for entry in entries))}

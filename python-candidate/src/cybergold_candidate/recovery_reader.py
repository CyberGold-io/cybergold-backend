"""Retained hash-keyed recovery page/balance cache and snapshot composition."""
import asyncio
import time

from cachetools import FIFOCache

SCHEMA='recovery-rpc-native-v1'
PAGE_SIZE=64


class RecoveryPortfolioReader:
    def __init__(self,reader,now=lambda:time.time()*1000):
        self.reader,self.now=reader,now
        # Node Map eviction is insertion order, not access-order LRU.
        self.pages,self.wallets=FIFOCache(maxsize=128),FIFOCache(maxsize=128)
        self.tasks=set()

    async def cached(self,cache,key,read):
        entry=cache.get(key)
        if entry and entry['expires']>self.now():return await asyncio.shield(entry['value'])
        cache.pop(key,None)
        task=asyncio.create_task(read())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        cache[key]={'expires':self.now()+10_000,'value':task}
        try:return await asyncio.shield(task)
        except Exception:
            cache.pop(key,None)
            raise

    async def close(self):
        tasks=list(self.tasks)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.pages.clear();self.wallets.clear()

    async def get(self,holder,offset=0,block_hash=None):
        reader=self.reader
        if offset<0 or offset>0 and not block_hash:
            raise ValueError('Recovery continuation requires its snapshot block hash')
        block=await reader.block(block_hash)
        identity=f'{SCHEMA}:{reader.chain_id}:{reader.core.lower()}:{block["hash"].lower()}'
        await reader.assert_canonical(block)
        async def page_read():
            total,(assets,next_offset),paused=await asyncio.gather(
                reader.count(block),reader.assets(block,offset),reader.paused(block))
            expected=min(max(total-offset,0),PAGE_SIZE)
            if (len(assets)!=expected or next_offset!=(total if offset>=total else offset+expected)
                or len({asset.lower() for asset in assets})!=len(assets)):
                raise ValueError('Recovery registry page is incomplete or inconsistent')
            pools=await reader.pools(block,assets)
            if len(pools)!=len(assets) or any(pool['asset'].lower()!=assets[index].lower() for index,pool in enumerate(pools)):
                raise ValueError('Recovery pool page does not match the registry')
            return {'pools':pools,'total':total,'next':next_offset,'paused':paused}
        page=await self.cached(self.pages,f'{identity}:{offset}',page_read)
        assets=[pool['asset'] for pool in page['pools']]
        async def balances_read():return await reader.balances(block,holder,assets)
        balances=await self.cached(self.wallets,f'{identity}:{holder.lower()}:{offset}',balances_read)
        if len(balances)!=len(page['pools']):raise ValueError('Recovery balance batch is incomplete')
        async def entry(pool,shares):
            payout=None;problem=None
            if not pool['custody']['liveBalanceAvailable']:problem='custody-unavailable'
            else:
                try:payout=str(await reader.preview(block,pool['asset'],shares))
                except Exception:problem='preview-unavailable'
            return {'shareId':str(int(pool['asset'],16)),'balanceRaw':str(shares),'pool':pool,
                'payoutRaw':payout,'payoutProblem':problem,'fundOffer':None}
        reads=[]
        for pool,shares in zip(page['pools'],balances):
            if shares<0 or shares>int(pool['externalShares']):
                raise ValueError('Recovery holder supply is inconsistent')
            if shares:reads.append(entry(pool,shares))
        entries=await asyncio.gather(*reads)
        try:
            optional=await reader.fund(block,holder,entries)
            fund=optional['status']
            for index,item in enumerate(entries):
                item['fundOffer']=optional['offers'][index] if index<len(optional['offers']) else None
        except Exception:
            fund={'configured':True,'available':False,'reason':'unavailable-or-inconsistent',
                'problem':'Governance Fund is unavailable','governance':None,'governancePaused':None}
        await reader.assert_canonical(block)
        return {'enabled':True,'status':'ready','schemaVersion':SCHEMA,'chainId':str(reader.chain_id),
            'collection':reader.core,'snapshotBlock':str(block['number']),'snapshotBlockHash':block['hash'],
            'complete':page['next']==page['total'],
            'nextOffset':None if page['next']==page['total'] else str(page['next']),
            'totalAssets':str(page['total']),'corePaused':page['paused'],'fund':fund,
            'balances':entries,'pools':page['pools']}

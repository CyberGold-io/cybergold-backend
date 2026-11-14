"""Owned advisory warming below stock Anvil; the SDK keeps its ordinary reads."""
import asyncio
import json

import httpx
from web3 import Web3

from .search_observations import current_search_observations
from .quote_flow import stage
from .shared_reads import SharedReads
from .uniswap_v3 import V3_TICK_SPACING, canonical_pool_address, bitmap_slots, bitmap_word_positions
from .uniswap_v4 import bitmap_slots as v4_bitmap_slots, v4_pool_id


class ForkBitmapPrefetch:
    def __init__(self, url, authorization, anchor_reader, *, client=None):
        self.url = url.rstrip('/')+'/prefetch/bitmaps'
        self.authorization = authorization
        self.anchor_reader = anchor_reader
        self.client = client or httpx.AsyncClient(timeout=None, follow_redirects=False)
        self.owns_client = client is None
        self.reads = SharedReads()
        self.tasks = {}

    @staticmethod
    def descriptor(pool, rpc):
        protocol = pool.get('protocol')
        if protocol == 'v3':
            a, b = (pool[name]['address'] for name in ('token0', 'token1'))
            fee = int(pool['feePips'])
            return {'protocol': protocol, 'factory': rpc.factory, 'token0': a, 'token1': b,
                'feePips': fee, 'address': pool.get('address') or canonical_pool_address(rpc.factory, a, b, fee)}
        if protocol == 'v4':
            return {'protocol': protocol, 'poolId': pool['id'],
                    'poolManager': pool.get('poolManager') or rpc.pool_manager}
        return None

    def schedule(self, pool, positions, rpc):
        try:
            descriptor = self.descriptor(pool, rpc)
            if descriptor is None:
                return
            positions = tuple(dict.fromkeys(positions))
            if not positions:
                return
            key = (json.dumps(descriptor, sort_keys=True), positions)
            observations = current_search_observations()
            tasks = observations.bitmap_prefetches if observations is not None else self.tasks
            if key in tasks:
                return
            task = asyncio.create_task(self._fill(descriptor, positions, rpc))
            tasks[key] = task
            if observations is None:
                task.add_done_callback(lambda _task: self.tasks.pop(key, None))
        except (KeyError, TypeError, ValueError, AttributeError):
            return  # An optional descriptor cannot change ordinary quoting.

    def schedule_body(self, body, rpc):
        """Plan topology names pools even when its actual residual amounts are unknown."""
        observations = current_search_observations()
        seen = observations.bitmap_full_pools if observations is not None else set()

        def visit(value):
            if isinstance(value, dict):
                if 'inputCurrency' in value and isinstance(value.get('routes'), list):
                    for route in value['routes']:
                        current = value['inputCurrency'].lower()
                        for step in route['steps']:
                            output = step['currencyOut'].lower()
                            a, b = sorted((current, output))
                            kind, fee = int(step['kind']), int(step['fee'])
                            if kind in (1, 2):
                                protocol = 'v3' if kind == 1 else 'v4'
                                spacing = (V3_TICK_SPACING.get(fee) if kind == 1 else int(step['tickSpacing']))
                                if spacing:
                                    pool = {'protocol': protocol, 'token0': {'address': a},
                                        'token1': {'address': b}, 'feePips': fee, 'tickSpacing': spacing}
                                    if kind == 2:
                                        pool['id'] = v4_pool_id((a,b,fee,spacing,'0x'+'00'*20))
                                    identity = (protocol,a,b,fee,spacing)
                                    if identity not in seen:
                                        seen.add(identity)
                                        self.schedule(pool, bitmap_word_positions(spacing), rpc)
                            current = output
                    return
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        try:
            visit(body)
        except (KeyError, TypeError, ValueError, AttributeError):
            return

    async def _fill(self, descriptor, positions, rpc):
        try:
            observations = current_search_observations()
            anchor = (await observations.read(('fork-bitmap-anchor',), self.anchor_reader)
                      if observations is not None else await self.anchor_reader())
            if not anchor:
                return
            key = (anchor,json.dumps(descriptor,sort_keys=True),positions)
            async def produce(_keys):
                for offset in range(0,len(positions),512):
                    chunk = positions[offset:offset+512]
                    with stage('bitmap.prefetch'):
                        async with rpc.semaphore:
                            response = await self.client.post(self.url,
                                headers={'Authorization':self.authorization},
                                json={'blockHash':anchor,'pool':descriptor,'wordPositions':list(chunk)})
                            response.raise_for_status()
                            report = response.json()
                    if report.get('wordsCached') == len(chunk):
                        with stage('bitmap.native-warm'):
                            await self._warm_native(descriptor,chunk,rpc)
                return [{'filled':True}]
            await self.reads.many([key],produce,retain=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            return  # No optional supplier failure becomes a quote failure.

    @staticmethod
    async def _warm_native(descriptor, positions, rpc):
        account = descriptor.get('address',descriptor.get('poolManager'))
        slots = (bitmap_slots(positions) if descriptor['protocol']=='v3'
                 else v4_bitmap_slots(descriptor['poolId'],positions))
        pending = iter(slots[offset:offset+32] for offset in range(0,len(slots),32))
        async def worker():
            for batch in pending:
                async with rpc.semaphore:
                    # Read current local state normally; base values are never injected
                    # over a Sandbox mutation or a simulation's private overrides.
                    await rpc.w3.provider.make_batch_request([
                        ('eth_getStorageAt',[account,Web3.to_hex(slot),'latest']) for slot in batch])
        tasks = [asyncio.create_task(worker()) for _ in range(min(8,(len(slots)+31)//32))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.tasks.clear()
        await self.reads.close()
        if self.owns_client:
            await self.client.aclose()

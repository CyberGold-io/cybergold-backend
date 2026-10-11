"""Canonical worker reuse, protocol accounting and bounded durable activity."""
import asyncio
from copy import deepcopy
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from web3 import Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.pool_activity import (append_range, baseline, decode_event, get_pool_activity,
    pool_identity, public_activity, rollup, topic, EVENT_LIMIT, RANGE_LIMIT)
from cybergold_candidate.recovery_rpc import RecoveryApiError
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO
from cybergold_candidate.uniswap_routes import v4_pool_id

A, B, C, D = ('0x'+str(index).rjust(40, '0') for index in range(1, 5))
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A)
CODEC = Web3().codec


def block(number, branch=0):
    return {'number': number, 'hash': '0x'+hex(number+branch*100000)[2:].rjust(64, '0')}


def pool(protocol, manager=C):
    tokens = [{'address': address, 'decimals': 18, 'chainId': 1} for address in (A, B)]
    result = {'id': C, 'address': C, 'protocol': protocol, 'feePips': 3000,
              'token0': tokens[0], 'token1': tokens[1]}
    if protocol == 'v3':
        result.update(tickSpacing=10, feePips=500)
    elif protocol == 'v4':
        result.pop('address')
        result.update(id=v4_pool_id((A, B, 100, 1, ZERO)), poolManager=manager,
                      tickSpacing=1, feePips=100, hooks=ZERO)
    return result


def address_topic(address):
    return '0x'+address[2:].rjust(64, '0')


def log(entry, signature, types, values, indexed=(), *, number=101, index=0, transaction=0, branch=0):
    return {'address': entry.get('poolManager', entry.get('address')),
            'topics': [topic(signature), *indexed], 'data': Web3.to_hex(CODEC.encode(types, values)),
            'blockNumber': hex(number), 'blockHash': block(number, branch)['hash'],
            'transactionHash': '0x'+hex(number*100+transaction+branch*100000)[2:].rjust(64, '0'),
            'transactionIndex': hex(transaction), 'logIndex': hex(index)}


def swap(entry, amount0, amount1, **kwargs):
    if entry['protocol'] == 'v2':
        return log(entry, 'Swap(address,uint256,uint256,uint256,uint256,address)', ['uint256']*4,
                   [max(amount0, 0), max(amount1, 0), max(-amount0, 0), max(-amount1, 0)],
                   [address_topic(A), address_topic(B)], **kwargs)
    if entry['protocol'] == 'v3':
        return log(entry, 'Swap(address,address,int256,int256,uint160,uint128,int24)',
                   ['int256', 'int256', 'uint160', 'uint128', 'int24'],
                   [amount0, amount1, 1 << 96, 1000, 0], [address_topic(A), address_topic(B)], **kwargs)
    return log(entry, 'Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)',
               ['int128', 'int128', 'uint160', 'uint128', 'int24', 'uint24'],
               [amount0, amount1, 1 << 96, 1000, 0, 1123], [entry['id'], address_topic(A)], **kwargs)


class Store:
    def __init__(self):
        self.data = {}
        self.scope = ''
        self.fail_activity = False
        self.loads = []

    async def load(self, namespace, *, readonly=False):
        self.loads.append((namespace, readonly))
        return deepcopy(self.data.get(self.scope+namespace, {}))

    async def save(self, namespace, identity, value):
        if namespace == 'activity' and self.fail_activity:
            raise OSError('synthetic DB outage')
        self.data.setdefault(self.scope+namespace, {})[identity] = deepcopy(value)


class Rpc:
    def __init__(self):
        self.w3 = Web3()
        self.pool_manager = C
        self.state_view = D
        self.rows = []
        self.queries, self.checks, self.reads = [], [], []
        self.branch_start = None

    async def block(self, number):
        return block(number, 1 if self.branch_start and number >= self.branch_start else 0)

    async def assert_canonical(self, anchor):
        self.checks.append(deepcopy(anchor))
        if anchor != await self.block(anchor['number']):
            raise RecoveryApiError('Synthetic canonical history changed', retry=1)

    async def logs(self, query):
        self.queries.append(deepcopy(query))
        first, last = int(query['fromBlock'], 16), int(query['toBlock'], 16)
        return deepcopy([row for row in self.rows if row['address'].lower() == query['address'].lower()
                         and first <= int(row['blockNumber'], 16) <= last
                         and (not query.get('topics') or row['topics'][1].lower() == query['topics'][1].lower())])

    async def read_function(self, address, signature, inputs, args, outputs, anchor):
        self.reads.append(signature)
        if signature == 'getReserves()': return 100, 200, 0
        if signature.startswith('getSlot0'): return 1 << 96, 0, 0, 100
        if signature.startswith('getLiquidity'): return (1000,)
        if signature == 'slot0()': return 1 << 96, 0, 0, 0, 0, 0, True
        if signature == 'liquidity()': return (1000,)
        raise AssertionError(signature)

    async def close(self):
        pass


class Activity(unittest.IsolatedAsyncioTestCase):
    async def registry(self, entries, store=None, rpc=None):
        rpc, store = rpc or Rpc(), store or Store()
        registry = PoolRegistry(SETTINGS, rpc, store)
        registry.inventory = {entry['id']: deepcopy(entry) for entry in entries}
        registry.loaded = True
        registry.loaded_at = __import__('time').monotonic()
        for entry in entries:
            await store.save('inventory', entry['id'], entry)
            state = {**entry, 'context': {'chainId': 1, 'blockNumber': '100', 'blockHash': block(100)['hash']},
                     'ticks': [], 'bitmapWords': []}
            state.update(reserve0='100', reserve1='200') if entry['protocol'] == 'v2' else state.update(
                sqrtRatioX96=str(1 << 96), liquidity='1000', tick=0)
            registry.observed[entry['id']] = state
        self.addAsyncCleanup(registry.close)
        return registry, rpc, store

    async def test_protocol_signed_volume_and_wide_liquidity_are_lossless(self):
        large = 2**100+37
        for protocol in ('v2', 'v3', 'v4'):
            entry = pool(protocol)
            row = swap(entry, -large if protocol == 'v4' else large, large//2 if protocol == 'v4' else -large//2)
            event = decode_event(entry, row, CODEC)
            totals = rollup([event])
            self.assertEqual(totals['amount0InRaw'], str(large))
            self.assertEqual(totals['amount1OutRaw'], str(abs(int(event['arguments'].get('amount1', -large//2)))))
            self.assertEqual(totals['swapCount'], 1)
        entry = pool('v4')
        event = decode_event(entry, log(entry, 'ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)',
            ['int24', 'int24', 'int256', 'bytes32'], [-100, 100, -large, bytes(32)],
            [entry['id'], address_topic(A)]), CODEC)
        self.assertEqual(rollup([event])['liquidityRemovedRaw'], str(large))
        self.assertNotIn('amount0', event['arguments'])
        self.assertNotIn('token0BalanceRaw', event)
        zero_burn = decode_event(pool('v3'), log(pool('v3'), 'Burn(address,int24,int24,uint128,uint256,uint256)',
            ['uint128', 'uint256', 'uint256'], [0, 0, 0],
            [address_topic(A), Web3.to_hex(CODEC.encode(['int24'], [-100])), Web3.to_hex(CODEC.encode(['int24'], [100]))]), CODEC)
        self.assertEqual(rollup([zero_burn])['liquidityRemovalCount'], 0)

    async def test_worker_reuses_logs_and_existing_canonical_checks_once(self):
        entry = pool('v4')
        registry, rpc, store = await self.registry([entry])
        a = swap(entry, -300, 200, number=101, index=4, transaction=1)
        b = swap(entry, -100, 60, number=101, index=3, transaction=0)
        rpc.rows = [a, b, a]
        await registry.monitor(block(102))
        self.assertEqual(len(rpc.queries), 1)
        self.assertEqual(rpc.queries[0]['topics'], [None, entry['id']])
        self.assertEqual(rpc.checks, [block(100), block(102)])
        bundle = (await store.load('activity'))[pool_identity(entry)]
        events = bundle['ranges'][0]['events']
        self.assertEqual([event['logIndex'] for event in events], [3, 4])
        self.assertEqual(bundle['ranges'][0]['rollup']['amount0InRaw'], '400')
        self.assertEqual(events[1]['arguments']['fee'], '1123')
        self.assertEqual(events[1]['pool']['feePips'], 100)
        self.assertEqual(events[1]['blockHash'], block(101)['hash'])
        self.assertEqual(registry.observed[entry['id']]['context']['blockNumber'], '102')

    async def test_quote_snapshot_does_not_write_activity(self):
        entry = pool('v2')
        registry, rpc, store = await self.registry([entry])
        rpc.rows = [swap(entry, 10, -5)]
        await registry.snapshot(entry, block(102), publish=False)
        self.assertEqual(await store.load('activity'), {})
        self.assertEqual(registry.activity, {})

    async def test_persistence_failure_does_not_veto_state_and_retries_without_duplicate_scan(self):
        entry = pool('v2')
        registry, rpc, store = await self.registry([entry])
        store.fail_activity = True
        rpc.rows = [swap(entry, 10, -5)]
        await registry.monitor(block(102))
        self.assertEqual(registry.observed[entry['id']]['context']['blockNumber'], '102')
        self.assertEqual(await store.load('activity'), {})
        store.fail_activity = False
        await registry.monitor(block(102))
        self.assertEqual(len(rpc.queries), 1)
        self.assertEqual((await get_pool_activity(store, 1))['events'][0]['arguments']['amount0In'], '10')

    async def test_restart_reorg_removes_orphaned_events_and_rollups(self):
        entry = pool('v4')
        registry, rpc, store = await self.registry([entry])
        rpc.rows = [swap(entry, -100, 50, number=101)]
        await registry.monitor(block(102))
        rpc.rows = [swap(entry, -9000, 4000, number=103)]
        await registry.monitor(block(104))
        await asyncio.gather(*tuple(registry.background))
        restarted = PoolRegistry(SETTINGS, rpc, store)
        self.addAsyncCleanup(restarted.close)
        rpc.branch_start = 103
        rpc.rows = [swap(entry, -200, 100, number=103, branch=1)]
        rpc.queries.clear()
        await restarted.monitor(block(105, 1))
        result = await get_pool_activity(store, 1)
        self.assertEqual([event['arguments']['amount0'] for event in result['events']], ['-200', '-100'])
        self.assertEqual([entry['rollup']['amount0InRaw'] for entry in result['pools'][0]['rollups']], ['100', '200'])
        self.assertEqual(result['pools'][0]['indexedThroughBlockHash'], block(105, 1)['hash'])
        self.assertEqual([(int(query['fromBlock'], 16), int(query['toBlock'], 16)) for query in rpc.queries], [(103, 105)])

    async def test_missing_prefix_is_bounded_and_acquired_suffix_is_not_scanned_twice(self):
        entry = pool('v2')
        registry, rpc, store = await self.registry([entry])
        bundle = baseline(entry, block(95))
        registry.activity[pool_identity(entry)] = bundle
        rpc.rows = [swap(entry, 11, -7, number=97), swap(entry, 20, -10, number=101)]
        await registry.monitor(block(102), max_blocks=4)
        self.assertEqual([(int(q['fromBlock'], 16), int(q['toBlock'], 16)) for q in rpc.queries], [(101, 102), (96, 99)])
        result = await get_pool_activity(store, 1)
        self.assertEqual(result['pools'][0]['indexedThroughBlock'], '99')
        await registry.monitor(block(102), max_blocks=4)
        self.assertEqual([(int(q['fromBlock'], 16), int(q['toBlock'], 16)) for q in rpc.queries][-1], (100, 102))
        self.assertEqual([event['arguments']['amount0In'] for event in (await get_pool_activity(store, 1))['events']], ['20', '11'])

    async def test_retention_and_public_filter_keep_exact_manager_identity(self):
        first, other = pool('v4'), pool('v4', D)
        bundle = append_range(baseline(first, block(100)), block(101),
            [swap(first, -1, 1, index=index) for index in range(EVENT_LIMIT+3)], CODEC)
        self.assertEqual(len(bundle['ranges'][0]['events']), EVENT_LIMIT)
        self.assertEqual(bundle['ranges'][0]['rollup']['swapCount'], EVENT_LIMIT+3)
        for number in range(102, 102+RANGE_LIMIT):
            bundle = append_range(bundle, block(number), [], CODEC)
        self.assertEqual(len(bundle['ranges']), RANGE_LIMIT)
        self.assertEqual(bundle['baseline']['blockNumber'], '101')
        self.assertTrue(bundle['eventsTruncated'])
        store = Store()
        await store.save('activity', pool_identity(first), bundle)
        await store.save('activity', pool_identity(other), append_range(baseline(other, block(100)),
            block(101), [swap(other, -2, 1)], CODEC))
        all_pools = await get_pool_activity(store, 1, {'poolId': first['id']})
        self.assertEqual(len(all_pools['pools']), 2)
        selected = await get_pool_activity(store, 1, {'poolId': first['id'], 'poolManager': D.upper().replace('0X', '0x')})
        self.assertEqual([item['pool']['poolManager'] for item in selected['pools']], [D])
        many = public_activity(1, [append_range(baseline(first, block(100)), block(101),
            [swap(first, -1, 1, index=index) for index in range(110)], CODEC)])
        self.assertEqual(len(many['events']), 100)
        self.assertTrue(many['hasMore'])

    async def test_malformed_known_events_remain_visible_without_fabricated_volume(self):
        entry = pool('v4')
        row = swap(entry, -100, 50)
        row['data'] = '0x01'
        event = decode_event(entry, row, CODEC)
        self.assertIsNone(event['arguments'])
        self.assertEqual(event['data'], '0x01')
        self.assertEqual(rollup([event])['undecodedCount'], 1)
        self.assertEqual(rollup([event])['amount0InRaw'], '0')

    async def test_reorg_before_bounded_baseline_restarts_truthful_coverage(self):
        entry = pool('v4')
        registry, rpc, store = await self.registry([entry])
        registry.activity[pool_identity(entry)] = append_range(baseline(entry, block(100)),
            block(102), [swap(entry, -10, 5)], CODEC)
        registry.activity_loaded = True
        rpc.branch_start = 100
        await registry.monitor(block(103, 1))
        result = await get_pool_activity(store, 1)
        self.assertEqual(result['events'], [])
        self.assertEqual(result['pools'][0]['journalStartBlock'], '104')
        self.assertEqual(result['pools'][0]['indexedThroughBlockHash'], block(103, 1)['hash'])
        self.assertEqual(rpc.queries, [])

    async def test_failed_current_baseline_does_not_publish_activity_checkpoint(self):
        entry = pool('v2')
        registry, rpc, store = await self.registry([entry])
        registry.observed.clear()
        async def failed_read(*_args):
            raise OSError('synthetic state outage')
        rpc.read_function = failed_read
        # The supplied old branch is neither a getter observation nor canonical.
        rpc.branch_start = 100
        await registry.monitor(block(103))
        self.assertEqual(await store.load('activity'), {})

    async def test_api_reads_only_persisted_activity_and_uses_existing_error_envelope(self):
        store = Store()
        entry = pool('v4')
        await store.save('activity', pool_identity(entry), append_range(baseline(entry, block(100)),
            block(102), [swap(entry, -(2**100), 50)], CODEC))
        async def read(filters):
            return await get_pool_activity(store, 1, filters)
        app = create_app(pool_activity=read)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/api/activity/pools', params={'protocol': 'v4', 'poolId': entry['id'], 'poolManager': C})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.json()['events'][0]['arguments']['amount0'], str(-(2**100)))
                self.assertEqual((await client.head('/api/activity/pools')).status_code, 200)
                invalid = await client.get('/api/activity/pools?poolManager=bad')
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(invalid.json()['error'], 'Invalid poolManager filter.')
                self.assertEqual((await client.post('/api/activity/pools')).status_code, 405)
                self.assertTrue(all(readonly for namespace, readonly in store.loads if namespace == 'activity'))
        self.assertEqual(await get_pool_activity(None, 1), {'enabled': False, 'events': [], 'pools': []})
        async def fail(_filters):
            raise OSError('private DB details')
        app = create_app(pool_activity=fail)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/api/activity/pools')
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()['error'], 'Pool activity is temporarily unavailable.')
                self.assertNotIn('private', response.text)

    async def test_sandbox_activity_read_does_not_redirect_registry_persistence(self):
        from cybergold_candidate import runtime
        from cybergold_candidate.environment import load_environment
        from cybergold_candidate.uniswap_state import UniswapStore

        class Database:
            @asynccontextmanager
            async def connection(self):
                yield object()
            async def close(self):
                pass

        reads, writes, registries = [], [], []

        class ScopedStore(UniswapStore):
            async def load(self, namespace, *, readonly=False):
                reads.append((self, self.scope+namespace, readonly))
                return {}
            async def save(self, namespace, identity, value):
                writes.append((self.scope+namespace, identity, deepcopy(value)))

        def registry(*args, **kwargs):
            result = PoolRegistry(*args, **kwargs)
            registries.append(result)
            return result

        async def generation(*_args):
            return {'anchor': {'generation': 'new'}, 'status': 'ready'}

        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '31338',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': A, 'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid',
            'DATABASE_URL': 'postgresql://fixture.invalid/db'})
        async with httpx.AsyncClient() as client:
            with patch.object(runtime, 'UniswapStore', ScopedStore), \
                patch.object(runtime, 'PoolRegistry', registry), \
                patch('cybergold_candidate.fork_recovery.read_generation', generation):
                app = runtime.create_configured_app(settings, Database(), client)
                old = registries[0]
                await old.observe_generation('old')
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
                        self.assertEqual((await api.get('/api/activity/pools')).status_code, 200)
                    self.assertEqual((old.generation, old.store.scope), ('old', 'generation:old:'))
                    self.assertIsNot(reads[-1][0], old.store)
                    self.assertEqual(reads[-1][1:], ('generation:new:activity', True))
                    old.persist('inventory', 'old-pool', {'fromGeneration': old.generation})
                    await asyncio.gather(*tuple(old.background))
                    self.assertEqual(writes, [('generation:old:inventory', 'old-pool', {'fromGeneration': 'old'})])
                await old.close()


if __name__ == '__main__':
    unittest.main()

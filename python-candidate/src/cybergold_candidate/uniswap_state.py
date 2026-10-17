"""Canonical multi-protocol pool observations, inventory and event maintenance.

The registry stores observed state only. SDK candidate post-state is never
published here. Optional persistence or discovery failure does not veto quotes.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import time

from web3 import Web3
from web3.exceptions import BlockNotFound

from .uniswap_v4 import POOL_MANAGER, STATE_VIEW, read_pool_state, read_state_view
from .pool_producer import DEFAULT_FACTORY, PoolRpc
from .shared_reads import SharedReads
from .uniswap_routes import pool_key, v4_pool_id
from .wallet_balances import TOKENS
from .quote_errors import QuoteFailure, rpc_failure
from .recovery_rpc import RecoveryApiError, SnapshotChanged
from .pool_activity import baseline, checkpoint, append_range, pool_identity

ZERO = '0x'+'00'*20
V2_FACTORY = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
PAXG = dict(TOKENS)['paxg']

# Inclusive Mainnet deployment receipts, also inherited by the existing
# Mainnet-backed Sandbox (31338). These are acquisition defaults, not pool
# eligibility rules; configured custom deployments/chains retain genesis.
MAINNET_DEPLOYMENT_BLOCKS = {
    ('v2', V2_FACTORY.lower()): 10_000_835,
    ('v3', DEFAULT_FACTORY.lower()): 12_369_621,
    ('v4', POOL_MANAGER.lower()): 21_688_329,
}


def topic(signature):
    return Web3.to_hex(Web3.keccak(text=signature))


DISCOVERY = {'v2': topic('PairCreated(address,address,address,uint256)'),
             'v3': topic('PoolCreated(address,address,uint24,int24,address)'),
             'v4': topic('Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)')}
EVENTS = {signature.split('(')[0]: topic(signature) for signature in (
    'Sync(uint112,uint112)', 'Swap(address,address,int256,int256,uint160,uint128,int24)',
    'Mint(address,address,int24,int24,uint128,uint256,uint256)',
    'Burn(address,int24,int24,uint128,uint256,uint256)',
    'Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)',
    'ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)',
    'ProtocolFeeUpdated(bytes32,uint24)', 'SetFeeProtocol(uint8,uint8,uint8,uint8)')}
V3_SWAP = topic('Swap(address,address,int256,int256,uint160,uint128,int24)')
V4_SWAP = topic('Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)')


def copy_pool_snapshot(snapshot):
    """Own canonical scalar coverage rows and deep-copy all pool metadata.

    Bitmap/tick producers below and their persisted observations contain only
    scalar row values. Lists and row dictionaries still belong to each caller.
    """
    coverage = ('bitmapWords', 'ticks')
    result = deepcopy({key: value for key, value in snapshot.items() if key not in coverage})
    for key in coverage:
        if key in snapshot:
            result[key] = [dict(row) for row in snapshot[key]]
    return {key: result[key] for key in snapshot}


async def owned_reads(*operations):
    """Drain this acquisition's subscriptions; preserve canonical disproof."""
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
        if disproof is not None:
            raise disproof


class UniswapRpc(PoolRpc):
    def __init__(self, settings, w3=None, *, pool_reads=None):
        super().__init__(settings, w3)
        self.v2_factory = Web3.to_checksum_address(os.environ.get('NEXT_PUBLIC_UNISWAP_V2_FACTORY_ADDRESS') or V2_FACTORY)
        self.pool_manager = Web3.to_checksum_address(os.environ.get('NEXT_PUBLIC_UNISWAP_V4_POOL_MANAGER_ADDRESS') or POOL_MANAGER)
        self.state_view = Web3.to_checksum_address(os.environ.get('NEXT_PUBLIC_UNISWAP_V4_STATE_VIEW_ADDRESS') or STATE_VIEW)
        self.reads = pool_reads if pool_reads is not None else SharedReads()
        self.owns_pool_reads = pool_reads is None
        self.semaphore = asyncio.Semaphore(8)
        self.before_request = None

    async def read_function(self, address, signature, input_types, args, output_types, block):
        data = Web3.keccak(text=signature)[:4]+self.w3.codec.encode(input_types, args)
        key = (self.chain_id, block['hash'].lower(), address.lower(), Web3.to_hex(data).lower())
        def decode(response):
            if 'error' in response:
                raise rpc_failure(response['error'])
            return self.w3.codec.decode(output_types, bytes.fromhex(response['result'][2:]))
        async def produce(_keys):
            async with self.semaphore:
                if self.before_request:
                    await self.before_request()
                response = await self.w3.provider.make_request('eth_call', [
                    {'to': Web3.to_checksum_address(address), 'data': Web3.to_hex(data)},
                    {'blockHash': block['hash'], 'requireCanonical': True}])
            decode(response)  # A failed typed observation is never retained.
            return [response]
        rows, _ = await self.reads.many([key], produce, retain=self.chain_id == 1)
        try:
            return decode(rows[0])
        except Exception:
            # Legacy eligibility treats malformed getter replies as unknown.
            # They must not make a later typed retry reuse the same failure.
            self.reads.completed.pop(key, None)
            raise

    async def logs(self, query):
        async with self.semaphore:
            if self.before_request:
                await self.before_request()
            response = await self.w3.provider.make_request('eth_getLogs', [query])
        if 'error' in response:
            raise rpc_failure(response['error'])
        return response['result']

    async def close(self):
        if self.owns_pool_reads:
            await self.reads.close()
        await super().close()


class UniswapStore:
    """Additional namespaces in the existing DB, lazily recovered on use."""
    def __init__(self, database, chain, core):
        self.database, self.chain, self.core = database, chain, core.lower()
        self.scope = 'generation:unobserved:' if chain == 31338 else ''
        self.ready = False
        self.lock = asyncio.Lock()

    async def prepare(self):
        if self.ready:
            return
        async with self.lock:
            if not self.ready:
                async with self.database.connection() as connection:
                    await connection.execute('''CREATE TABLE IF NOT EXISTS cybergold_uniswap_state (
                        chain_id BIGINT NOT NULL, core_address TEXT NOT NULL, namespace TEXT NOT NULL,
                        identity TEXT NOT NULL, payload JSONB NOT NULL,
                        PRIMARY KEY(chain_id,core_address,namespace,identity))''')
                self.ready = True

    async def save(self, namespace, identity, value):
        namespace = self.scope+namespace
        await self.prepare()
        async with self.database.connection() as connection:
            await connection.execute('''INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(chain_id,core_address,namespace,identity) DO UPDATE SET payload=EXCLUDED.payload''',
                (self.chain, self.core, namespace, identity, json.dumps(value)))

    async def save_protocol_configuration(self, identity, value):
        """Order this advisory snapshot across API/worker writers only.

        Explicit rewind clears remain valid; after a clear a canonical lower
        block can seed recovery. Other registry namespaces keep their writers.
        """
        namespace = self.scope+'helpers-configuration'
        await self.prepare()
        async with self.database.connection() as connection:
            cursor = await connection.execute('''INSERT INTO cybergold_uniswap_state
                VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(chain_id,core_address,namespace,identity) DO UPDATE SET payload=EXCLUDED.payload
                WHERE EXCLUDED.payload='null'::jsonb OR cybergold_uniswap_state.payload='null'::jsonb
                    OR (EXCLUDED.payload->'context'->>'blockNumber')::numeric >=
                       (cybergold_uniswap_state.payload->'context'->>'blockNumber')::numeric
                RETURNING payload''', (self.chain, self.core, namespace, identity, json.dumps(value)))
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute('''SELECT payload FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s''',
                    (self.chain, self.core, namespace, identity))
                row = await cursor.fetchone()
            return row['payload'] if row else None

    async def load(self, namespace, *, readonly=False):
        namespace = self.scope+namespace
        if not readonly:
            await self.prepare()
        async with self.database.connection() as connection:
            async with connection.transaction():
                if readonly:
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                cursor = await connection.execute('''SELECT identity,payload FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s''', (self.chain, self.core, namespace))
                return {row['identity']: row['payload'] for row in await cursor.fetchall()}

    async def catalog(self, protocol, cursor, pools, removed):
        """Pool identities and their canonical scan checkpoint commit together."""
        scope = self.scope
        await self.prepare()
        async with self.database.connection() as connection:
            async with connection.transaction():
                if removed:
                    await connection.execute('''DELETE FROM cybergold_uniswap_state
                        WHERE chain_id=%s AND core_address=%s AND namespace=ANY(%s)
                        AND identity=ANY(%s)''', (self.chain, self.core,
                            [scope+'inventory', scope+'observation'], list(removed)))
                    await connection.execute('''DELETE FROM cybergold_uniswap_state
                        WHERE chain_id=%s AND core_address=%s AND namespace=%s
                        AND payload->'pool'->>'protocol'=%s AND payload->'pool'->>'id'=ANY(%s)''',
                        (self.chain, self.core, scope+'activity', protocol, list(removed)))
                rows = [('inventory', pool['id'], pool) for pool in pools]+[('cursor', protocol, cursor)]
                for namespace, identity, value in rows:
                    await connection.execute('''INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)
                        ON CONFLICT(chain_id,core_address,namespace,identity) DO UPDATE SET payload=EXCLUDED.payload''',
                        (self.chain, self.core, scope+namespace, identity, json.dumps(value)))


class PoolRegistry:
    def __init__(self, settings, rpc=None, store=None, *, pool_reads=None):
        self.settings, self.rpc, self.store = settings, rpc, store
        self.pool_reads = pool_reads
        self.chain = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.core = settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS or ZERO
        self.inventory, self.observed, self.cursors = {}, {}, {}
        self.activity = {}
        self.activity_loaded = False
        self.metadata, self.pending = {}, SharedReads()
        self.lookups = {}
        self.lookup_anchors = {}
        self.lookup_month = None
        self.loaded = False
        self.loaded_at = 0
        self.load_task = None
        self.background = set()
        self.discovery_month = None
        self.generation = None
        # The known deployment's PoolKey is the seed; deriving its ID also keeps
        # a different configured Core from borrowing another pool's state.
        a, b = sorted((self.core.lower(), PAXG.lower()))
        key = (a, b, 100, 1, ZERO)
        pool = {'id': v4_pool_id(key), 'protocol': 'v4', 'token0': self.token(a, 18),
            'token1': self.token(b, 18), 'poolManager': POOL_MANAGER, 'feePips': 100,
            'tickSpacing': 1, 'hooks': ZERO}
        self.inventory[pool['id']] = pool
        self.seed = deepcopy(pool)

    def token(self, address, decimals):
        return {'address': Web3.to_checksum_address(address), 'decimals': decimals, 'chainId': self.chain}

    async def observe_generation(self, generation):
        if generation is None or generation == self.generation:
            return
        self.generation = generation
        if self.store and self.chain == 31338:
            self.store.scope = 'generation:'+str(generation)+':'
        tasks = tuple(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.pending.close()
        self.inventory = {self.seed['id']: deepcopy(self.seed)}
        self.observed.clear()
        self.cursors.clear()
        self.activity.clear()
        self.activity_loaded = False
        self.metadata.clear()
        self.lookups.clear()
        self.lookup_anchors.clear()
        self.discovery_month = self.lookup_month = None
        self.loaded = False

    async def ensure_loaded(self, *, wait=False):
        if (not self.loaded or time.monotonic()-self.loaded_at >= 60) and self.load_task is None:
            task = asyncio.create_task(self._load())
            self.load_task = task
            self.background.add(task)
            def done(task):
                self.background.discard(task)
                if self.load_task is task:
                    self.load_task = None
                if not task.cancelled():
                    task.exception()
            task.add_done_callback(done)
        if wait and self.load_task:
            await asyncio.shield(self.load_task)

    async def _load(self):
        generation = self.generation
        if not self.loaded or time.monotonic()-self.loaded_at >= 60:
            if self.store:
                try:
                    inventory = await self.store.load('inventory')
                    cursors = await self.store.load('cursor')
                    observations = await self.store.load('observation') if self.chain == 1 else {}
                    if generation != self.generation:
                        return
                    for identity, pool in list(self.inventory.items()):
                        if pool.get('discovery') and identity not in inventory:
                            self.inventory.pop(identity, None)
                            self.observed.pop(identity, None)
                    self.inventory.update(inventory)
                    self.cursors.update(cursors)
                    if self.chain == 1:
                        for identity, row in observations.items():
                            old = self.observed.get(identity)
                            if old is None or int(row['context']['blockNumber']) > int(old['context']['blockNumber']):
                                self.observed[identity] = row
                    self.discovery_month = self.cursors.get('catalog', {}).get('month')
                except Exception:
                    pass  # Persistence is optional to exact provider quoting.
            if generation != self.generation:
                return
            self.loaded = True
            self.loaded_at = time.monotonic()

    def get_rpc(self):
        if self.rpc is None:
            self.rpc = UniswapRpc(self.settings, pool_reads=self.pool_reads)
        return self.rpc

    async def token_metadata(self, address, block, *, publish=True):
        if address.lower() not in self.metadata:
            generation = self.generation
            async def produce():
                if address.lower() == ZERO:
                    value = 18  # The native currency has no ERC20 contract.
                else:
                    value, = await self.get_rpc().read_function(address, 'decimals()', [], [], ['uint8'], block)
                return self.token(address, value)
            token = deepcopy(await self.pending.one(
                ('token-metadata', generation, address.lower(), block['hash']), produce))
            if publish and generation == self.generation:
                self.metadata[address.lower()] = token
            return token
        return self.metadata[address.lower()]

    def persist(self, namespace, identity, value):
        if self.store:
            task = asyncio.create_task(self.store.save(namespace, identity, deepcopy(value)))
            self.background.add(task)
            def done(task):
                self.background.discard(task)
                if not task.cancelled():
                    task.exception()  # Ordinary persistence outage, no quote gate.
            task.add_done_callback(done)

    def publish_observation(self, state):
        if self.chain == 1:
            if self.observed.get(state['id']) == state:
                return
            self.observed[state['id']] = deepcopy(state)
        self.persist('observation', state['id'], state)

    async def snapshot(self, pool, block, *, publish=True):
        rpc = self.get_rpc()
        generation = self.generation
        context = {'chainId': self.chain, 'blockNumber': str(block['number']), 'blockHash': block['hash']}
        key = (pool['protocol'], pool['id'], block['hash'])
        async def produce():
            old = self.observed.get(pool['id']) if self.chain == 1 else None
            if old and int(old['context']['blockNumber']) < block['number']:
                try:
                    state = await self.advance(pool, old, block)
                    return state
                except SnapshotChanged:
                    raise
                except Exception:
                    pass  # Ordinary gap/reorg/read failure uses fresh getters.
            state = deepcopy(pool)
            if pool['protocol'] == 'v3':
                if not state.get('address'):
                    address, = await rpc.read_function(rpc.factory, 'getPool(address,address,uint24)',
                        ['address', 'address', 'uint24'], [pool['token0']['address'],
                            pool['token1']['address'], int(pool['feePips'])], ['address'], block)
                    if address.lower() == ZERO:
                        raise QuoteFailure('quote-no-route')
                    state['address'] = address
                if state.get('tickSpacing') is None:
                    state['tickSpacing'], = await rpc.read_function(state['address'],
                        'tickSpacing()', [], [], ['int24'], block)
            async def metadata(token):
                if token.get('decimals') is not None:
                    return {**token, 'chainId': self.chain}
                try:
                    return await self.token_metadata(token['address'], block)
                except SnapshotChanged:
                    raise
                except Exception:
                    # Integer swap arithmetic does not depend on display scale.
                    # Preserve discovery's existing unknown-decimals contract.
                    return {**self.token(token['address'], 18), 'decimalsKnown': False}
            state['token0'], state['token1'] = await owned_reads(
                metadata(state['token0']), metadata(state['token1']))
            if pool['protocol'] == 'v2':
                r0, r1, _ = await rpc.read_function(pool['address'], 'getReserves()', [], [],
                    ['uint112', 'uint112', 'uint32'], block)
                state.update(reserve0=str(r0), reserve1=str(r1))
            elif pool['protocol'] == 'v3':
                slot, liquidity = await owned_reads(
                    rpc.read_function(state['address'], 'slot0()', [], [],
                        ['uint160', 'int24', 'uint16', 'uint16', 'uint16', 'uint8', 'bool'], block),
                    rpc.read_function(state['address'], 'liquidity()', [], [], ['uint128'], block))
                state.update(sqrtRatioX96=str(slot[0]), tick=slot[1], liquidity=str(liquidity[0]),
                             protocolFee=slot[5], lpFee=int(pool['feePips']))
            else:
                state.update(await read_pool_state(rpc.read_function, rpc.state_view, pool['id'], block))
            state.update(context=context, ticks=[], bitmapWords=[])
            return state
        old = self.observed.get(pool['id'])
        if self.chain == 1 and old and old['context']['blockHash'] == block['hash']:
            return deepcopy(old)
        state = deepcopy(await self.pending.one(key, produce))
        # A shared acquisition stays pure. Each caller owns publication after
        # its accepted boundary, without duplicating event advancement/getters.
        if publish and generation == self.generation:
            self.publish_observation(state)
        return state

    async def extend_ticks(self, snapshot, requests, block):
        snapshot, requests = copy_pool_snapshot(snapshot), deepcopy(requests)
        generation = self.generation
        # Share only an identical fill that is still acquiring its coverage.
        # Completed Sandbox observations remain fresh on the next call, even
        # at the same header; each caller owns the returned mutable snapshot.
        key = ('tick-fill', generation, block['hash'],
               json.dumps(snapshot, sort_keys=True), json.dumps(requests, sort_keys=True))
        async def produce():
            return await self._extend_ticks(snapshot, requests, block, generation)
        result = copy_pool_snapshot(await self.pending.one(key, produce))
        return result

    async def _extend_ticks(self, snapshot, requests, block, generation):
        rpc = self.get_rpc()
        pool = snapshot
        current = self.observed.get(pool['id'])
        covered = current if current and current['context']['blockHash'] == block['hash'] else snapshot
        words = {int(row['wordPosition']): row for row in covered.get('bitmapWords', [])}
        ticks = {int(row['index']): row for row in covered.get('ticks', [])}
        spacing = int(pool['tickSpacing'])
        requested_words = {int(word) for request in requests for word in request.get('wordPositions', [])}
        missing_words = sorted(requested_words-words.keys())
        async def read_word(word):
            if pool['protocol'] == 'v4':
                value, = await read_state_view(rpc.read_function, rpc.state_view, 'getTickBitmap', block,
                    [bytes.fromhex(pool['id'][2:]), word])
            else:
                value, = await rpc.read_function(pool['address'], 'tickBitmap(int16)', ['int16'], [word], ['uint256'], block)
            return word, value
        for word, bitmap in await owned_reads(*(read_word(word) for word in missing_words)):
            words[word] = {'wordPosition': word, 'bitmap': str(bitmap)}
        needed = {int(tick) for request in requests for tick in request.get('ticks', [])}
        for word in requested_words:
            bits = int(words[word]['bitmap'])
            if bits:
                needed.update(((word << 8)+bit)*spacing for bit in range(256) if bits & (1 << bit))
        async def read_tick(index):
            if pool['protocol'] == 'v4':
                value = await read_state_view(rpc.read_function, rpc.state_view, 'getTickLiquidity', block,
                    [bytes.fromhex(pool['id'][2:]), index])
            else:
                value = await rpc.read_function(pool['address'], 'ticks(int24)', ['int24'], [index],
                    ['uint128', 'int128', 'uint256', 'uint256', 'int56', 'uint160', 'uint32', 'bool'], block)
            return {'index': index, 'liquidityGross': str(value[0]), 'liquidityNet': str(value[1])}
        for row in await owned_reads(*(read_tick(index) for index in sorted(needed-ticks.keys()))):
            ticks[row['index']] = row
        # Concurrent candidates can have requested different coverage from the
        # same observation. Merge their immutable tick observations at this hash.
        current = self.observed.get(pool['id'])
        if current and current['context']['blockHash'] == block['hash']:
            words.update({int(row['wordPosition']): row for row in current.get('bitmapWords', [])})
            ticks.update({int(row['index']): row for row in current.get('ticks', [])})
        # extend_ticks owns the snapshot; coverage below replaces its old rows.
        # Subscriber, observed-state and persistence copies remain independent.
        result = {**snapshot, 'bitmapWords': list(words.values()), 'ticks': list(ticks.values())}
        if generation == self.generation:
            if self.chain == 1:
                self.observed[pool['id']] = deepcopy(result)
            self.persist('observation', pool['id'], result)
        return result

    async def event_logs(self, pool, first, block):
        rpc = self.get_rpc()
        address = pool.get('poolManager', rpc.pool_manager) if pool['protocol'] == 'v4' else pool['address']
        topics = [None, pool['id']] if pool['protocol'] == 'v4' else []
        async def produce(_keys):
            return [await rpc.logs({'address': address, 'fromBlock': hex(first),
                'toBlock': hex(block['number']), **({'topics': topics} if topics else {})})]
        key = ('pool-events', self.generation, pool['protocol'], address.lower(), pool['id'].lower(), first, block['hash'])
        values, _ = await self.pending.many([key], produce, retain=self.chain == 1)
        return deepcopy(values[0])

    async def advance(self, pool, old, block, *, with_logs=False):
        """Carry covered ticks through the proven canonical event interval."""
        rpc = self.get_rpc()
        if pool['protocol'] == 'v4' and (pool.get('hooks', ZERO).lower() != ZERO or int(pool['feePips']) >= 0x800000):
            raise ValueError('Pool state needs ordinary canonical getters')
        number = int(old['context']['blockNumber'])
        await rpc.assert_canonical({'number': number, 'hash': old['context']['blockHash']})
        rows = await self.event_logs(pool, number+1, block)
        state = deepcopy(old)
        for row in sorted(rows, key=lambda row: (int(row['blockNumber'], 16),
            int(row['transactionIndex'], 16), int(row['logIndex'], 16))):
            self.apply_event(state, row)
        await rpc.assert_canonical(block)
        state['context'] = {'chainId': self.chain, 'blockNumber': str(block['number']), 'blockHash': block['hash']}
        return (state, rows) if with_logs else state

    async def commit_catalog(self, protocol, cursor, pools=(), removed=()):
        if self.store:
            try:
                await self.store.catalog(protocol, cursor, pools, removed)
            except Exception:
                pass  # Optional durable cache, not a quote eligibility gate.
        for identity in removed:
            self.inventory.pop(identity, None)
            self.observed.pop(identity, None)
            for key, bundle in list(self.activity.items()):
                if bundle['pool']['protocol'] == protocol and bundle['pool']['id'] == identity:
                    self.activity.pop(key)
        for pool in pools:
            self.inventory[pool['id']] = pool
        self.cursors[protocol] = deepcopy(cursor)

    async def recover_catalog(self):
        """Rewind orphaned scan ranges, including after a process restart."""
        rpc = self.get_rpc()
        changed = False
        canonical = set()
        orphaned = set()
        async def check(point):
            key = (int(point['blockNumber']), point['blockHash'].lower())
            if key in orphaned:
                return False
            if key not in canonical:
                try:
                    await rpc.assert_canonical({'number': key[0], 'hash': point['blockHash']})
                except (RecoveryApiError, BlockNotFound):
                    orphaned.add(key)
                    return False
                canonical.add(key)
            return True
        for protocol in ('v2', 'v3', 'v4'):
            cursor = self.cursors.get(protocol, {})
            checkpoints = list(cursor.get('checkpoints', []))
            rewind = None
            while checkpoints:
                point = checkpoints[-1]
                if await check(point):
                    break
                rewind = int(checkpoints.pop()['rangeStart'])
            if rewind is not None:
                removed = [identity for identity, pool in self.inventory.items() if pool.get('discovery', {}).get('protocol') == protocol
                    and int(pool['discovery']['blockNumber']) >= rewind]
                await self.commit_catalog(protocol, {'blockNumber': str(rewind), 'checkpoints': checkpoints, 'pending': True}, removed=removed)
                changed = True
            elif cursor and not checkpoints and not cursor.get('checkpoints'):
                # Older un-hashed inventory cursors are hints; replay their
                # creation events to establish recoverable canonical checkpoints.
                await self.commit_catalog(protocol, {'blockNumber': '0', 'checkpoints': [], 'pending': True})
                changed = True
            # On-demand identities have the same recoverable canonical anchor
            # as discovery ranges, without requiring another quote-time probe.
            removed = []
            for identity, pool in list(self.inventory.items()):
                anchor = pool.get('acquisition')
                if pool['protocol'] == protocol and anchor and not await check(anchor):
                    removed.append(identity)
            if removed:
                for identity in removed:
                    pool = self.inventory[identity]
                    for token in (pool['token0'], pool['token1']):
                        self.metadata.pop(token['address'].lower(), None)
                await self.commit_catalog(protocol, self.cursors.get(protocol, {}), removed=removed)
                changed = True
        for key, anchor in list(self.lookup_anchors.items()):
            if key not in self.lookups:
                self.lookup_anchors.pop(key, None)
            elif not await check(anchor):
                self.lookups.pop(key, None)
                self.lookup_anchors.pop(key, None)
                changed = True
        if changed:
            self.discovery_month = None
            self.cursors.pop('catalog', None)
            self.lookups.clear()
            self.lookup_anchors.clear()
        return changed

    async def discover(self, block, *, force=False, max_blocks=50_000):
        await self.ensure_loaded(wait=True)
        await self.recover_catalog()
        if force:
            self.lookups = {key: value for key, value in self.lookups.items() if value is not None}
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if not force and self.discovery_month == month and not any(row.get('pending') for row in self.cursors.values()):
            return
        rpc = self.get_rpc()
        padded = '0x'+self.core[2:].lower().rjust(64, '0')
        completed = True
        for protocol, address in (('v2', rpc.v2_factory), ('v3', rpc.factory), ('v4', rpc.pool_manager)):
            # Producer birth includes every possible pool creation, including
            # currency keys initialized before CYGLD deployment. Keep a saved
            # cursor literal; only a cold known deployment uses this floor.
            cursor = self.cursors.get(protocol, {})
            floor = MAINNET_DEPLOYMENT_BLOCKS.get((protocol, address.lower()), 0) if self.chain in (1, 31338) else 0
            start = int(cursor.get('blockNumber', floor))
            checkpoints = list(cursor.get('checkpoints', []))
            end = min(block['number'], start+max_blocks-1)
            if end < start:
                continue
            for first in range(start, end+1, 10_000):
                last = min(first+9999, end)
                anchor = block if last == block['number'] else await rpc.block(last)
                filters = ([DISCOVERY[protocol], padded], [DISCOVERY[protocol], None, padded]) if protocol != 'v4' else (
                    [DISCOVERY[protocol], None, padded], [DISCOVERY[protocol], None, None, padded])
                rows = await asyncio.gather(*(rpc.logs({'address': address, 'fromBlock': hex(first),
                    'toBlock': hex(last), 'topics': topics}) for topics in filters))
                logs = {row['transactionHash']+row['logIndex']: row for group in rows for row in group}
                pools = []
                for row in sorted(logs.values(), key=lambda row: (int(row['blockNumber'], 16), int(row['logIndex'], 16))):
                    pool = await self.decode_discovery(protocol, row, block)
                    pool['discovery'] = {'protocol': protocol, 'blockNumber': str(int(row['blockNumber'], 16)),
                        'scanBlockNumber': str(last), 'scanBlockHash': anchor['hash']}
                    pools.append(pool)
                await rpc.assert_canonical(anchor)
                checkpoints.append({'rangeStart': str(first), 'blockNumber': str(last), 'blockHash': anchor['hash']})
                await self.commit_catalog(protocol, {'blockNumber': str(last+1), 'checkpoints': checkpoints,
                    'pending': last < block['number']}, pools)
            completed &= end == block['number']
        if completed:
            await rpc.assert_canonical(block)
            self.discovery_month = month
            self.lookups = {key: value for key, value in self.lookups.items() if value is not None}
            self.lookup_month = month
            self.cursors['catalog'] = {'month': month}
            self.persist('cursor', 'catalog', self.cursors['catalog'])

    async def decode_discovery(self, protocol, log, block):
        rpc = self.get_rpc()
        offset = 2 if protocol == 'v4' else 1
        token0, token1 = ('0x'+log['topics'][offset+i][-40:] for i in range(2))
        async def metadata(address):
            try:
                return await self.token_metadata(address, block)
            except Exception:
                # The factory event establishes the pool identity even if this
                # ERC20's optional decimals() is unavailable. Raw integer swaps
                # do not depend on decimals; expose the unknown metadata.
                return {**self.token(address, 18), 'decimalsKnown': False}
        a, b = await asyncio.gather(metadata(token0), metadata(token1))
        data = bytes.fromhex(log['data'][2:])
        if protocol == 'v2':
            address, _ = rpc.w3.codec.decode(['address', 'uint256'], data)
            return {'id': address.lower(), 'protocol': protocol, 'address': address,
                    'token0': a, 'token1': b, 'feePips': 3000}
        if protocol == 'v3':
            spacing, address = rpc.w3.codec.decode(['int24', 'address'], data)
            return {'id': address.lower(), 'protocol': protocol, 'address': address, 'token0': a,
                    'token1': b, 'feePips': int(log['topics'][3], 16), 'tickSpacing': spacing}
        fee, spacing, hooks, _, _ = rpc.w3.codec.decode(['uint24', 'int24', 'address', 'uint160', 'int24'], data)
        return {'id': log['topics'][1].lower(), 'protocol': protocol, 'poolManager': rpc.pool_manager,
                'token0': a, 'token1': b, 'feePips': fee, 'tickSpacing': spacing, 'hooks': hooks}

    async def monitor(self, block, *, max_blocks=20000):
        """Catch up known snapshots; unobserved pools acquire a canonical baseline."""
        await self.ensure_loaded(wait=True)
        rpc = self.get_rpc()
        for pool in list(self.inventory.values()):
            old = self.observed.get(pool['id'])
            acquired = None
            try:
                if old is None:
                    await self.snapshot(pool, block)
                elif int(old['context']['blockNumber']) < block['number']:
                    state, rows = await self.advance(pool, old, block, with_logs=True)
                    acquired = (old['context'], rows)
                    self.observed[pool['id']] = state
                    self.persist('observation', pool['id'], state)
            except Exception:
                # Reorg/gap/unknown baseline: invalidate coverage, then an ordinary
                # canonical resnapshot; do not admit incomplete logs as exact state.
                self.observed.pop(pool['id'], None)
                try:
                    await self.snapshot(pool, block)
                except Exception:
                    pass
            try:
                await self.monitor_activity(pool, block, acquired, max_blocks=max_blocks)
            except Exception:
                # Activity persistence/decoding/catch-up is optional to exact
                # observations and quotes. Its durable cursor retries next run.
                pass

    async def monitor_activity(self, pool, block, acquired=None, *, max_blocks=20000):
        """Use accepted state logs, acquiring only a missing history interval."""
        if not self.activity_loaded:
            # Only the worker loads activity; quote/model registry acquisition
            # never depends on this journal or performs its database reads.
            loaded = await self.store.load('activity') if self.store else {}
            self.activity = {**loaded, **self.activity}
            self.activity_loaded = True
        rpc = self.get_rpc()
        identity = pool_identity(pool)
        bundle = deepcopy(self.activity.get(identity))
        known = {(block['number'], block['hash'].lower())} if acquired else set()
        observed = self.observed.get(pool['id'])
        if observed and observed['context']['blockHash'].lower() == block['hash'].lower() and int(
                observed['context']['blockNumber']) == block['number']:
            # The accepted block-bound getter/state publication already proves
            # this anchor, including the cold-baseline and fallback paths.
            known.add((block['number'], block['hash'].lower()))
        if acquired:
            context, rows = acquired
            known.add((int(context['blockNumber']), context['blockHash'].lower()))
        else:
            context, rows = None, []
        if bundle is None:
            anchor = ({'number': int(context['blockNumber']), 'hash': context['blockHash']} if context else block)
            bundle = baseline(pool, anchor)
        else:
            while True:
                point = checkpoint(bundle)
                anchor = {'number': int(point['blockNumber']), 'hash': point['blockHash']}
                try:
                    if (anchor['number'], anchor['hash'].lower()) not in known:
                        await rpc.assert_canonical(anchor)
                    break
                except (RecoveryApiError, BlockNotFound):
                    if bundle['ranges']:
                        bundle['ranges'].pop()
                    else:
                        # The bounded window's baseline itself was orphaned.
                        # Restart truthful coverage at the observed block.
                        bundle = baseline(pool, block)
                        break
        first = int(checkpoint(bundle)['blockNumber'])+1
        if first <= block['number']:
            last = min(block['number'], first+max_blocks-1)
            end = block if last == block['number'] else await rpc.block(last)
            if context and first >= int(context['blockNumber'])+1:
                selected = rows
            else:
                # A previous DB outage/restart can leave activity behind state.
                # Catch up the missing prefix only; reuse the acquired suffix.
                prefix_last = min(last, int(context['blockNumber'])) if context else last
                prefix_end = ({'number': prefix_last, 'hash': context['blockHash']}
                              if context and prefix_last == int(context['blockNumber']) else
                              end if prefix_last == last else await rpc.block(prefix_last))
                selected = await self.event_logs(pool, first, prefix_end)
                if context and prefix_last < last:
                    selected += rows
            if (end['number'], end['hash'].lower()) not in known:
                await rpc.assert_canonical(end)
            bundle = append_range(bundle, end, selected, rpc.w3.codec)
        elif not bundle['ranges'] and (block['number'], block['hash'].lower()) not in known:
            await rpc.assert_canonical(block)
        self.activity[identity] = bundle
        if self.store:
            await self.store.save('activity', identity, bundle)

    def apply_event(self, state, log):
        codec = self.get_rpc().w3.codec
        signature = log['topics'][0].lower()
        data = bytes.fromhex(log['data'][2:])
        if signature == EVENTS['Sync'].lower():
            a, b = codec.decode(['uint112', 'uint112'], data)
            state.update(reserve0=str(a), reserve1=str(b))
        elif signature == DISCOVERY['v4'].lower():
            fee, _spacing, _hooks, price, tick = codec.decode(['uint24', 'int24', 'address', 'uint160', 'int24'], data)
            state.update(sqrtRatioX96=str(price), tick=tick, liquidity='0')
            if fee < 0x800000:
                state['lpFee'] = fee
        elif signature == topic('Initialize(uint160,int24)').lower():
            price, tick = codec.decode(['uint160', 'int24'], data)
            state.update(sqrtRatioX96=str(price), tick=tick, liquidity='0')
        elif signature in (V3_SWAP.lower(), V4_SWAP.lower()):
            types = ['int128', 'int128', 'uint160', 'uint128', 'int24', 'uint24'] if state['protocol'] == 'v4' else (
                ['int256', 'int256', 'uint160', 'uint128', 'int24'])
            values = codec.decode(types, data)
            state.update(sqrtRatioX96=str(values[2]), liquidity=str(values[3]), tick=values[4])
        elif signature == EVENTS['ProtocolFeeUpdated'].lower():
            state['protocolFee'] = codec.decode(['uint24'], data)[0]
        elif signature == EVENTS['SetFeeProtocol'].lower():
            _old0, _old1, current0, current1 = codec.decode(['uint8', 'uint8', 'uint8', 'uint8'], data)
            state['protocolFee'] = current0 | (current1 << 4)
        elif signature == EVENTS['ModifyLiquidity'].lower() or signature in (EVENTS['Mint'].lower(), EVENTS['Burn'].lower()):
            if state['protocol'] == 'v4':
                lower, upper, delta, _salt = codec.decode(['int24', 'int24', 'int256', 'bytes32'], data)
            else:
                lower, upper = (int.from_bytes(bytes.fromhex(value[2:]), 'big', signed=True)
                    for value in log['topics'][-2:])
                if signature == EVENTS['Mint'].lower():
                    delta = codec.decode(['address', 'uint128', 'uint256', 'uint256'], data)[1]
                else:
                    delta = -codec.decode(['uint128', 'uint256', 'uint256'], data)[0]
            words = {((tick//int(state['tickSpacing'])) >> 8) for tick in (lower, upper)}
            state['ticks'] = [row for row in state.get('ticks', []) if row['index'] not in (lower, upper)]
            state['bitmapWords'] = [row for row in state.get('bitmapWords', []) if row['wordPosition'] not in words]
            if lower <= state['tick'] < upper:
                state['liquidity'] = str(int(state['liquidity'])+delta)

    async def close(self):
        tasks = tuple(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.pending.close()
        if self.rpc:
            await self.rpc.close()

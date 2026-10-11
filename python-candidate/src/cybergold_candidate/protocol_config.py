"""RPC-free App configuration and a narrow canonical adapter observation cache.

The cache chooses defaults, never authorizes caller-selected swaps. Live pause,
roles and transaction-preparation facts keep their existing producers.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import os
import time

from fastapi.responses import JSONResponse
from web3 import Web3

from .app_tokens import configured_tokens
from .helpers_router_facts import ABI
from .protocol_facts import ProtocolFactsRpc
from .quote_errors import QuoteFailure

# Reviewed deployed encodings. Preference is explicit, independent of set order.
SUPPORTED_ADAPTERS = (
    ('0xc2c210979674db1349f812ea116f2f6d131ab839', 'uniswap-multi-protocol-v1'),
    ('0x4edb8190232a47e45d861003672938eb7ee84a15', 'uniswap-v3'),
)
APPROVAL_TOPIC = Web3.to_hex(Web3.keccak(text='AdapterApprovalUpdated(address,bool)'))


def select_adapter(approved):
    available = {address.lower() for address in approved}
    return next(((Web3.to_checksum_address(address), encoding)
                 for address, encoding in SUPPORTED_ADAPTERS if address in available), (None, None))


def configured_address(settings, name):
    value = getattr(settings, name, os.environ.get(name))
    return Web3.to_checksum_address(value) if value and Web3.is_address(value) and int(value, 16) else None


class ProtocolConfiguration:
    def __init__(self, settings, store=None, rpc=None, *, generation_reader=None, now=None):
        self.settings, self.store, self.rpc = settings, store, rpc
        self.chain = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.helpers = configured_address(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS')
        self.generation_reader = generation_reader
        self.now = now or time.time
        self.generation, self.value = None, None
        self.epoch = 0
        self.loading, self.refreshing = None, None
        self.write_lock = asyncio.Lock()
        self.unsaved_epoch = None
        self.tasks = set()
        self.started = False

    def track(self, operation):
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        def done(task):
            self.tasks.discard(task)
            if not task.cancelled():
                task.exception()
        task.add_done_callback(done)
        return task

    async def observe_generation(self, generation):
        if generation != self.generation:
            self.generation = generation
            self.epoch += 1
            self.value = None
            self.unsaved_epoch = None
            if self.store:
                self.store.scope = ('generation:'+str(generation)+':' if generation
                                    else 'generation:unobserved:') if self.chain == 31338 else ''

    async def load(self, *, wait=True):
        if self.loading is None:
            async def recover():
                try:
                    if self.generation_reader:
                        try:
                            generation = await self.generation_reader()
                        except Exception:
                            generation = None
                        await self.observe_generation(generation)
                    epoch = self.epoch
                    unsaved = self.unsaved_epoch is not None
                    if self.store and self.helpers:
                        values = await self.store.load('helpers-configuration')
                        if (epoch == self.epoch and not unsaved and self.unsaved_epoch is None
                                and self.helpers.lower() in values):
                            self.value = values[self.helpers.lower()]
                except Exception:
                    # Optional cache recovery does not block configured roots.
                    pass
            task = self.track(recover())
            self.loading = task
            def done(task):
                if self.loading is task:
                    self.loading = None
            task.add_done_callback(done)
        if wait:
            await asyncio.shield(self.loading)
        return deepcopy(self.value)

    async def persist(self):
        if not self.store or not self.helpers:
            return
        epoch = self.epoch
        value = deepcopy(self.value)
        self.unsaved_epoch = epoch
        try:
            async with self.write_lock:
                if epoch != self.epoch:
                    return
                retained = await self.store.save_protocol_configuration(self.helpers.lower(), value)
                if epoch == self.epoch:
                    self.value = deepcopy(retained)
                    self.unsaved_epoch = None
        except Exception:
            # Failed optional storage cannot undo a newer local observation.
            pass

    async def observe(self, approved, context, *, generation=None, epoch=None):
        if generation != self.generation or (epoch is not None and epoch != self.epoch):
            return
        if self.value and int(context['blockNumber']) < int(self.value['context']['blockNumber']):
            return
        self.epoch += 1
        self.value = {'approved': list(approved), 'context': deepcopy(context),
                      'observedSeconds': self.now()}
        await self.persist()

    async def observe_facts(self, facts, generation=None):
        if self.generation_reader:
            await self.load()
        if generation != self.generation:
            return
        field = facts['configuration']['approvedAdapters']
        if field['status'] == 'success':
            await self.observe(field['value'], facts['context'], generation=self.generation)

    async def capture_facts(self, facts, generation=None):
        # Keep live signing/pause facts independent of optional cache I/O.
        self.track(self.observe_facts(deepcopy(facts), generation))

    async def read_pending(self, rpc, block):
        await self.load()
        if not self.helpers or (self.value and self.now()-self.value['observedSeconds'] < 86_400):
            return None
        epoch, generation = self.epoch, self.generation
        if hasattr(rpc, 'read_function'):
            approved, = await rpc.read_function(self.helpers, 'approvedAdapters()', [], [], ['address[]'], block)
        else:
            approved = await rpc.read('helpers', self.helpers, 'approvedAdapters', block)
        context = {'blockNumber': str(block['number']), 'blockHash': block['hash'],
                   'observedAt': datetime.now(timezone.utc).isoformat()}
        return approved, context, generation, epoch

    async def publish_pending(self, pending):
        if pending:
            approved, context, generation, epoch = pending
            await self.observe(approved, context, generation=generation, epoch=epoch)

    async def refresh(self):
        if not self.helpers or not self.settings.RPC_URL:
            return
        if self.refreshing is None:
            async def update():
                try:
                    await self.load()
                    if not self.helpers or self.value or not self.settings.RPC_URL:
                        return
                    if self.rpc is None:
                        self.rpc = ProtocolFactsRpc(self.settings, abi=ABI)
                    async with asyncio.timeout(15):
                        block = await self.rpc.block()
                        pending = await self.read_pending(self.rpc, block)
                        await self.rpc.assert_canonical(block)
                        await self.publish_pending(pending)
                except Exception:
                    pass
            task = self.track(update())
            self.refreshing = task
            def done(task):
                if self.refreshing is task:
                    self.refreshing = None
            task.add_done_callback(done)
        await asyncio.shield(self.refreshing)

    async def start(self):
        if not self.started and self.helpers and self.settings.RPC_URL:
            self.started = True
            self.track(self.refresh())

    async def invalidate_from(self, block_number):
        if not self.value or int(self.value['context']['blockNumber']) >= block_number:
            self.epoch += 1
            self.value = None
            await self.persist()

    async def apply_journal(self, database):
        await self.load()
        if not self.value or not self.helpers:
            return
        from .helpers_activity import decode_helpers_activity
        epoch, generation = self.epoch, self.generation
        snapshot = deepcopy(self.value)
        context = snapshot['context']
        async with database.connection() as connection:
            cursor = await connection.execute('''SELECT block_number::text,block_hash,tx_hash,log_index,
                block_timestamp_seconds::text,topics,data FROM onchain_raw_logs
                WHERE chain_id=%s AND contract_address=%s AND block_number>%s AND topics->>0=%s
                ORDER BY block_number,log_index''',
                (str(self.chain), self.helpers.lower(), context['blockNumber'], APPROVAL_TOPIC))
            rows = await cursor.fetchall()
        approved = {address.lower(): address for address in snapshot['approved']}
        for row in rows:
            event = decode_helpers_activity(row)
            if event['eventName'] != 'AdapterApprovalUpdated':
                continue
            address = event['arguments']['adapter']
            if event['arguments']['approved']:
                approved[address.lower()] = address
            else:
                approved.pop(address.lower(), None)
            context = {'blockNumber': row['block_number'], 'blockHash': row['block_hash'],
                       'observedAt': datetime.now(timezone.utc).isoformat()}
        if rows:
            await self.observe(list(approved.values()), context, generation=generation, epoch=epoch)

    async def resolve_request(self, request):
        # Explicit and quote-bound addresses retain the existing admission path.
        if request.get('adapter') is not None:
            return request
        value = deepcopy(request)
        retained = value.get('retainedPlan') or {}
        address = retained.get('params', {}).get('adapter')
        if not address:
            addresses = {row['adapter'] for row in retained.get('quotes', []) if row.get('adapter')}
            address = next(iter(addresses)) if len(addresses) == 1 else None
        if not address:
            cached = await self.load(wait=False)
            address, _encoding = select_adapter(cached['approved']) if cached else (None, None)
        if not address:
            raise QuoteFailure('quote-unavailable')
        value['adapter'] = address
        return value

    async def get(self):
        cached = await self.load(wait=False)
        address, encoding = select_adapter(cached['approved']) if cached else (None, None)
        core = configured_address(self.settings, 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS')
        contracts = {'core': core, 'helpers': self.helpers,
            'governance': configured_address(self.settings, 'NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS'),
            'staking': configured_address(self.settings, 'NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS'),
            'safe': configured_address(self.settings, 'NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS'),
            'uniswapAdapter': address}
        observation = ({name: cached['context'][name] for name in ('blockNumber', 'blockHash', 'observedAt')}
                       if cached and address else None)
        return {'chainId': self.chain, 'contracts': contracts, 'tokens': configured_tokens(core, self.chain),
                'sandboxForkGeneration': self.generation,
                'adapter': {'status': 'success' if address else 'unavailable',
                            'encoding': encoding, 'observation': observation}}

    async def close(self):
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.rpc:
            await self.rpc.close()


async def handle_protocol_configuration(service):
    if service is None:
        return JSONResponse({'error': 'Protocol configuration is unavailable.'}, status_code=503,
                            headers={'Cache-Control': 'no-store'})
    return JSONResponse(await service.get(), headers={'Cache-Control': 'no-store'})

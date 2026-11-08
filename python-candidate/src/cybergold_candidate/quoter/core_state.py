"""Event-maintained construction hints; complete plans are priced by Helpers.

Cold fields warm independently. API processes use memory and listen for worker
publications; only the existing journal worker persists updates. Cache/store
failures are ordinary component failures, never a quote admission condition.
"""
import asyncio
from copy import deepcopy
import json

from psycopg import AsyncConnection

from ..core_activity import decode_core_activity, EVENTS as CORE_EVENTS
from ..helpers_activity import decode_helpers_activity, EVENTS as HELPER_EVENTS
from ..protocol_config import configured_address
from ..rpc_block_context import LATEST_BLOCK

CHANNEL = 'cybergold_quote_core_state'
NAMESPACE = 'quote-core-construction'
FIELDS = {
    'assets': ('core', 'basketAssets()', 'address[]'),
    'weights': ('core', 'basketTargetsPpm()', 'uint256[]'),
    'conversions': ('core', 'basketCygldPerUnitFp18()', 'uint256[]'),
    'recoveryAssets': ('core', 'coreAttachedRecoveryAssets()', 'address[]'),
    'issueFee': ('core', 'issuanceFeePpm()', 'uint256'),
    'redeemFee': ('core', 'redemptionFeePpm()', 'uint256'),
    'helperFee': ('helpers', 'helperFeePpm()', 'uint256'),
}
EVENT_FIELDS = {
    'BasketConfigured': {'assets': 'assets', 'weights': 'targetsPpm', 'conversions': 'cygldPerUnitFp18'},
    'IssuanceFeePpmUpdated': {'issueFee': 'newIssuanceFeePpm'},
    'RedemptionFeePpmUpdated': {'redeemFee': 'newRedemptionFeePpm'},
    'HelperFeeUpdated': {'helperFee': 'newHelperFeePpm'},
    'MaxTotalSupplyUpdated': {'maxSupply': 'newMaxTotalSupply'},
}
REFRESH_EVENTS = frozenset(('DiamondCut', 'RecoveryActivated',
    'RecoveryRehabilitated', 'RecoverySharesRedeemed', 'AssetRecoveryFundActivated',
    'Issued', 'Redeemed', 'ReserveLifecycleChanged'))
_RESTART = object()


def normalized(name, value):
    if name in ('weights', 'conversions', 'available', 'recoveryShares', 'recoveryValues'):
        return list(map(int, value))
    if name in ('issueFee', 'redeemFee', 'helperFee', 'supply', 'maxSupply', 'effectiveCap'):
        return int(value)
    return deepcopy(value)


class CoreQuoteState:
    def __init__(self, settings, registry, *, store=None, publisher=False):
        self.settings, self.registry = settings, registry
        self.store = store if store is not None else getattr(registry, 'store', None)
        self.publisher = publisher
        self.core = configured_address(settings, 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS')
        self.helpers = configured_address(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS')
        self.value, self.pending, self.versions, self.waiters = {}, {}, {}, {}
        self.tasks, self.positions = set(), {}
        self.generation = None
        self.epoch = self.revision = 0
        self.started = False
        self.listener = self.connection = self.warming = self.loading = None
        self._published = None
        self._invalidated = False
        self.generation_observer = None
        self._notification_pending = publisher
        self._listened = False

    def track(self, operation):
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return task

    def update(self, fields, *, advance=True):
        fields = {name: normalized(name, value) for name, value in fields.items()}
        if 'assets' in fields and fields['assets'] != self.value.get('assets'):
            if 'assets' in self.value:
                # These vectors belong to the previous basket. A supplied
                # event/model vector is installed atomically below; independent
                # missing fields retain their ordinary lazy acquisition.
                self.invalidate(name for name in ('weights', 'conversions', 'available')
                    if name not in fields)
            else:
                self.value.pop('available', None)
        # Publish the full event/model vector before waking either basis waiter.
        for name, value in fields.items():
            self.value[name] = value
            if advance:
                self.versions[name] = self.versions.get(name, 0) + 1
        for name, value in fields.items():
            future = self.waiters.get(name)
            if future is not None and not future.done():
                future.set_result(deepcopy(value))

    def invalidate(self, names):
        names = tuple(names)
        if any(name in FIELDS for name in names) and self.warming is not None and not self.warming.done():
            self.warming.cancel()
            self.warming = None
        for name in names:
            self.value.pop(name, None)
            self.versions[name] = self.versions.get(name, 0) + 1
            task = self.pending.pop(name, None)
            if task is not None and not task.done():
                task.cancel()
            future = self.waiters.pop(name, None)
            if future is not None and not future.done():
                future.set_result(_RESTART)

    async def field(self, name):
        while name not in self.value:
            if name not in self.pending:
                version, epoch = self.versions.get(name, 0), self.epoch
                future = asyncio.get_running_loop().create_future()
                self.waiters[name] = future
                async def acquire(version=version, epoch=epoch, future=future):
                    try:
                        group, signature, result_type = FIELDS[name]
                        values = await self.registry.get_rpc().read_function(
                            self.core if group == 'core' else self.helpers,
                            signature, [], [], [result_type], LATEST_BLOCK)
                        result = list(values[0]) if result_type.endswith('[]') else int(values[0])
                        if epoch == self.epoch and self.versions.get(name, 0) == version:
                            self.update({name: result})
                    except asyncio.CancelledError:
                        if not future.done():
                            future.cancel()
                        raise
                    except BaseException as error:
                        if not future.done():
                            future.set_exception(error)
                            future.exception()
                task = self.track(acquire())
                self.pending[name] = task
                def finished(done):
                    if self.pending.get(name) is done:
                        self.pending.pop(name, None)
                task.add_done_callback(finished)
            future = self.waiters[name]
            result = await asyncio.shield(future)
            if result is not _RESTART and name in self.value:
                return deepcopy(self.value[name])
        return deepcopy(self.value[name])

    def warm(self):
        if all(name in self.value for name in FIELDS):
            return None
        if self.warming is None or self.warming.done():
            async def acquire():
                await asyncio.gather(*(self.field(name) for name in FIELDS), return_exceptions=True)
            self.warming = self.track(acquire())
        return self.warming

    async def get(self):
        await self.start()
        await asyncio.gather(self.field('assets'), self.field('weights'))
        return deepcopy(self.value)

    async def outputs(self):
        await self.start()
        assets, recovery = await asyncio.gather(self.field('assets'), self.field('recoveryAssets'))
        available = self.value.get('available')
        return [{'kind': 0, 'token': asset, 'id': '0',
                 'amount': str(available[index]) if available is not None and index < len(available) else '1'}
                for index, asset in enumerate(assets)] + [
                    {'kind': 1, 'token': self.core, 'id': str(int(asset, 16)), 'amount': '1'}
                    for asset in recovery]

    def observe_facts(self, facts):
        updates = {}
        for target, source in (('assets', 'assets'), ('weights', 'targetsPpm'), ('conversions', 'cygldPerUnitFp18')):
            field = facts.get('basket', {}).get(source, {})
            if field.get('status') == 'success':
                updates[target] = field['value']
        for target, source in (('issueFee', 'issuancePpm'), ('helperFee', 'helpersPpm')):
            field = facts.get('fees', {}).get(source, {})
            if field.get('status') == 'success':
                updates[target] = field['value']
        for target, source in (('supply', 'totalSupply'), ('maxSupply', 'maxTotalSupply'), ('effectiveCap', 'effectiveCygldSupplyCap')):
            field = facts.get('issuanceCapacity', {}).get(source, {})
            if field.get('status') == 'success':
                updates[target] = field['value']
        self.update(updates)

    def observe_model(self, state):
        updates = {key: state[key] for key in ('assets', 'weights', 'conversions', 'available',
            'issueFee', 'redeemFee', 'helperFee', 'supply', 'maxSupply', 'effectiveCap',
            'recoveryShares', 'recoveryValues') if key in state}
        if 'descriptors' in state:
            updates['recoveryAssets'] = ['0x'+format(int(row['id']), '040x')
                for row in state['descriptors'] if int(row['kind']) == 1]
        self.update(updates)

    async def _recover(self, missing_only):
        if self.store is None or self._invalidated:
            return
        epoch, versions = self.epoch, dict(self.versions)
        try:
            saved = (await self.store.load(NAMESPACE)).get(self.core.lower())
            if not saved or epoch != self.epoch:
                return
            revision = int(saved.get('revision', 0))
            if revision < self.revision:
                return
            incoming = saved.get('fields', {})
            reset = not missing_only and revision > self.revision and saved.get('reset', False)
            if reset:
                self.invalidate(set(self.value) | set(self.pending))
            elif not missing_only and revision > self.revision:
                # Publications contain the worker's full advisory snapshot.
                # Missing keys carry its event invalidations, but cannot erase
                # an independent local observation completed during this load.
                self.invalidate(name for name in self.value if name not in incoming
                    and self.versions.get(name, 0) == versions.get(name, 0))
            updates = {key: value for key, value in incoming.items() if key not in self.value or (
                not missing_only and revision > self.revision and
                self.versions.get(key, 0) == versions.get(key, 0))}
            # Startup storage is an advisory seed. A live getter already in
            # flight can still replace it; later notifications are observations.
            self.update(updates, advance=not missing_only)
            self.positions = deepcopy(saved.get('positions', {}))
            self.revision = revision
            self._published = json.dumps({'fields': incoming, 'positions': self.positions}, sort_keys=True)
        except Exception:
            pass

    async def load(self):
        await self._recover(True)

    async def reload(self):
        await self._recover(False)

    async def publish(self):
        if not self.publisher or self.store is None:
            return
        snapshot = {'fields': deepcopy(self.value), 'positions': deepcopy(self.positions)}
        encoded = json.dumps(snapshot, sort_keys=True)
        changed = encoded != self._published
        if not changed and not self._notification_pending:
            return
        epoch, revision = self.epoch, self.revision + 1
        try:
            if changed:
                await self.store.save(NAMESPACE, self.core.lower(), {**snapshot, 'revision': revision,
                    'reset': self._invalidated})
                if epoch != self.epoch:
                    return
                self.revision, self._published = revision, encoded
                self._invalidated = False
                self._notification_pending = True
            async with self.store.database.connection() as connection:
                await connection.execute('SELECT pg_notify(%s,%s)', (CHANNEL,
                    json.dumps({'chain': self.registry.chain, 'core': self.core.lower(),
                        'scope': self.store.scope, 'generation': self.generation})))
            self._notification_pending = False
        except Exception:
            pass

    def apply_event(self, name, arguments, address=None):
        mapping = EVENT_FIELDS.get(name)
        if mapping:
            self.update({target: arguments[source] for target, source in mapping.items()})
            if name == 'MaxTotalSupplyUpdated':
                # The effective cap also includes the global maximum. Later
                # ordinary facts/models can repopulate this advisory hint;
                # the event does not require a quote-time getter.
                self.invalidate(['effectiveCap'])
        elif name == 'DiamondCut':
            self.invalidate(['helperFee'] if address and address.lower() == self.helpers.lower() else FIELDS)
        elif name in ('RecoveryActivated', 'RecoveryRehabilitated'):
            asset = arguments['asset']
            if 'recoveryAssets' in self.value:
                assets = list(self.value['recoveryAssets'])
                if name == 'RecoveryActivated' and int(arguments['addedCoreAttachedShares']) and asset.lower() not in {a.lower() for a in assets}:
                    assets.append(asset)
                    assets.sort(key=lambda value: int(value, 16))
                if name == 'RecoveryRehabilitated':
                    assets = [a for a in assets if a.lower() != asset.lower()]
                self.update({'recoveryAssets': assets})
            else:
                self.invalidate(['recoveryAssets'])
            self.invalidate(['available', 'effectiveCap'])
        elif name in ('Issued', 'Redeemed', 'ReserveLifecycleChanged', 'RecoverySharesRedeemed', 'AssetRecoveryFundActivated'):
            # Unbound latest amount hints cannot be advanced as a pinned ledger.
            self.invalidate(['available', 'supply', 'effectiveCap'])
            if name == 'Redeemed' and any(int(kind) == 1 for kind in arguments.get('kinds', [])):
                self.invalidate(['recoveryAssets'])
        self.warm()

    async def apply_journal(self, database):
        await self.reload()
        for address, decode, events in ((self.core, decode_core_activity, CORE_EVENTS),
                                        (self.helpers, decode_helpers_activity, HELPER_EVENTS)):
            position = self.positions.get(address.lower(), [-1, -1])
            topics = [topic for topic, event in events.items()
                      if event['name'] in EVENT_FIELDS or event['name'] in REFRESH_EVENTS]
            async with database.connection() as connection:
                cursor = await connection.execute('''SELECT block_number::text,block_hash,tx_hash,log_index,
                    block_timestamp_seconds::text,topics,data FROM onchain_raw_logs
                    WHERE chain_id=%s AND contract_address=%s AND (block_number,log_index)>(%s,%s)
                    AND topics->>0=ANY(%s) ORDER BY block_number,log_index''',
                    (str(self.registry.chain), address.lower(), *position, topics))
                rows = await cursor.fetchall()
            for row in rows:
                event = decode(row)
                if event['eventName'] is not None:
                    self.apply_event(event['eventName'], event['arguments'] or {}, address)
                self.positions[address.lower()] = [int(row['block_number']), row['log_index']]
        warming = self.warm()
        if warming is not None:
            await warming
        await self.publish()

    async def invalidate_from(self, block_number):
        self.epoch += 1
        self.invalidate(set(self.value) | set(self.pending))
        self.positions.clear()
        self._published = None
        self._invalidated = True

    async def listen(self):
        url = getattr(self.settings, 'DATABASE_URL', None)
        if not url or self.store is None or self.publisher:
            return
        try:
            async with await AsyncConnection.connect(url, autocommit=True) as connection:
                self.connection = connection
                await connection.execute('LISTEN '+CHANNEL)
                if self._listened:
                    await self.reload()
                else:
                    await self.load()
                self._listened = True
                async for message in connection.notifies():
                    identity = json.loads(message.payload)
                    if identity.get('chain') == self.registry.chain and identity.get('core') == self.core.lower():
                        if (identity.get('scope') != self.store.scope and self.registry.chain == 31338
                                and identity.get('generation') is not None):
                            await self.observe_generation(identity['generation'], warm=False)
                            if self.generation_observer is not None:
                                try:
                                    await self.generation_observer(identity['generation'])
                                except Exception:
                                    pass
                        if identity.get('scope') == self.store.scope:
                            await self.reload()
                            self.warm()
        except Exception:
            pass
        finally:
            self.connection = None

    async def start(self):
        if not self.started:
            self.started = True
            self.warm()
            self.loading = self.track(self.load())
        if self.listener is None or self.listener.done():
            self.listener = self.track(self.listen())

    async def observe_generation(self, generation, *, warm=True):
        if generation is not None and generation != self.generation:
            self.generation = generation
            self.epoch += 1
            self.invalidate(set(self.value) | set(self.pending))
            self.positions.clear()
            self.revision = 0
            self._published = None
            self._invalidated = False
            if self.store and self.registry.chain == 31338:
                self.store.scope = 'generation:'+str(generation)+':' if generation else 'generation:unobserved:'
            if self.started and warm:
                self.warm()

    async def close(self):
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for future in self.waiters.values():
            if not future.done():
                future.cancel()
        self.pending.clear()
        self.waiters.clear()
        self.listener = self.connection = self.warming = self.loading = None
        self.started = False

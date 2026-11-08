"""Shared completed economic observations in the existing optional SQL store.

A stored quote keeps its original context and semantic plan. It is a historical
display/seed observation; lookup does not reprice or prepare a transaction.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

from ..market_fee import get_market_fee_rate
from ..protocol_config import configured_address
from .path_families import PATH_FAMILIES, quote_path_family
from .ranking import prefer_completed
from .reuse_routes import funded_route_identity


@dataclass(frozen=True)
class EconomicQuoteScope:
    chain: int
    core: str
    namespace: str
    identity: str
    deployment: str = field(default='', compare=False, repr=False)


def normalized_economic_request(request):
    """Preserve ordered basket inputs; exclude transport and execution fields."""
    return {'intent': int(request['intent']),
        'inputs': [{'currency': row['currency'].lower(), 'amount': str(int(row['amount']))}
                   for row in request['inputs']],
        'outputCurrency': request['outputCurrency'].lower()}


def request_identity(request, deployment):
    encoded = json.dumps({'request': normalized_economic_request(request), 'deployment': deployment},
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode()).hexdigest()


class EconomicQuoteStore:
    def __init__(self, settings, registry=None, *, store=None, limit=4096, fee_scope=None):
        self.settings, self.registry = settings, registry
        self.store = store if store is not None else getattr(registry, 'store', None)
        self.limit = max(0, int(limit))
        # A caller may supply already-observed protocol/fee facts. Reading this
        # identity must not trigger RPC, collection or a new eligibility rule.
        self.fee_scope = fee_scope
        self.memory = OrderedDict()
        self.locations = {}
        self.retired = {}
        self.known_rows = {}
        self.books = set()
        self.io, self.background = set(), set()
        self.observation_sequence = 0

    @staticmethod
    def scope_key(scope):
        return scope.chain, scope.core, scope.namespace, scope.deployment

    def track_io(self, task):
        if task in self.io:
            return
        self.io.add(task)
        for record in self.retired.values():
            if not record['deleted'] or record.get('inflight_only'):
                record['owners'].add(task)
        def done(task):
            self.io.discard(task)
            self._release_retired()
        task.add_done_callback(done)

    def _release_retired(self):
        for key, record in list(self.retired.items()):
            if (record['deleted'] or record['point'] not in self.memory) and all(
                    task.done() for task in record['owners']):
                self.retired.pop(key, None)
                if not self.locations.get(key):
                    self.known_rows.pop(key, None)

    def _retire(self, scope, identity, *, replaced=False):
        key = self.scope_key(scope), identity
        record = self.retired.get(key)
        if record is not None and (not record.get('inflight_only') or not replaced):
            return
        point = self.scope_key(scope), scope.identity
        record = {'owners': set(self.io) | (record['owners'] if record else set()),
                  'deleted': self.store is None, 'point': point,
                  'rows': set(self.known_rows.get(key, ()))}
        self.retired[key] = record
        self.memory.setdefault(point, {})
        self._prune()
        if self.store is None:
            self._release_retired()
            return
        async def discard():
            try:
                await self.store.prepare()
                async with self.store.database.connection() as connection:
                    async with connection.transaction():
                        counter = (scope.chain, scope.core, scope.namespace+'-sequence', 'commits')
                        await connection.execute('''INSERT INTO cybergold_uniswap_state
                            VALUES (%s,%s,%s,%s,'{"sequence":0}'::jsonb) ON CONFLICT DO NOTHING''', counter)
                        await connection.execute('''SELECT payload FROM cybergold_uniswap_state
                            WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s
                            FOR UPDATE''', counter)
                        current_identity, current = '', None
                        for point, family in self.locations.get(key, ()):
                            row = self.memory.get(point, {}).get(family)
                            if row is not None:
                                current_identity, current = point[1]+':'+family, row['quote']
                        await connection.execute('''DELETE FROM cybergold_uniswap_state
                            WHERE chain_id=%s AND core_address=%s AND namespace=%s
                            AND (payload->>'candidateIdentity'=%s OR identity=ANY(%s))
                            AND (identity<>%s OR payload->'quote' IS DISTINCT FROM %s::jsonb)''',
                            (scope.chain, scope.core, scope.namespace, identity,
                             list(record['rows'] | self.known_rows.get(key, set())), current_identity, json.dumps(current)))
                record['deleted'] = True
            except Exception:
                pass  # A failed optional delete cannot restore a paid-disproved observation.
            self._release_retired()
        task = asyncio.create_task(discard())
        self.background.add(task)
        self.track_io(task)
        task.add_done_callback(self.background.discard)

    def register_book(self, scope, book):
        self.books.add((self.scope_key(scope), book))

    def unregister_book(self, book):
        self.books = {(scope, value) for scope, value in self.books if value is not book}

    def latest_version(self, scope, identity):
        key = self.scope_key(scope), identity
        values = [book.versions.get(identity, 0) for owner, book in self.books if owner == key[0]]
        values += [self.memory.get(point, {}).get(family, {}).get('version', 0)
                   for point, family in self.locations.get(key, ())]
        values.append(self.retired.get(key, {}).get('version', 0))
        return max(values, default=0)

    def historical_observation(self, scope, value):
        identity = funded_route_identity(value)
        rows = [self.memory[point][family] for point, family in
                self.locations.get((self.scope_key(scope), identity), ())]
        if rows:
            row = max(rows, key=lambda row: row['sequence'] if row['sequence'] is not None else -1)
            return deepcopy(row['quote']), row['sequence']
        if self.history_replaced(scope, identity):
            return None
        return deepcopy(value), None

    def announce(self, request, frame, owner, *, scope):
        identity, replaces = frame['_candidateIdentity'], frame.get('_replacesIdentity')
        value = frame['value']
        same = next((self.memory[point][family] for point, family in
                     self.locations.get((self.scope_key(scope), identity), ())
                     if self.memory[point][family]['current'] and self.memory[point][family]['quote'] == value), None)
        if same is not None and (replaces is None or replaces == identity):
            version = same['version']
        else:
            self.observation_sequence += 1
            version = self.observation_sequence
        targets = {book for key, book in self.books if key == self.scope_key(scope)
                   and (book is owner or identity in book.rows or identity in book.observed
                        or replaces in book.rows or replaces in book.observed)}
        targets.add(owner)
        if replaces is not None and replaces != identity:
            self.forget(replaces, scope=scope)
        if value is None:
            self.forget(identity, scope=scope)
        else:
            request = value.get('request', request)
            self.remember(request, value, scope=self.point_scope(scope, request), version=version)
        # Known-ID rows in every active operation receive the same paid fact.
        # Metadata-only terminal/family enrichment never creates a new version.
        for book in targets:
            if book.on_observation is not None:
                book.on_observation(frame, version)

    def point_scope(self, scope, request):
        return EconomicQuoteScope(scope.chain, scope.core, scope.namespace,
            request_identity(request, json.loads(scope.deployment)), scope.deployment)

    def history_replaced(self, scope, identity):
        key = self.scope_key(scope), identity
        return (key in self.retired or any(owner == key[0] and identity in book.observed
                for owner, book in self.books)
                or any(self.memory.get(point, {}).get(family, {}).get('current')
                       for point, family in self.locations.get(key, ())))

    def discard_history(self, scope, identity, rows):
        key = self.scope_key(scope), identity
        if key in self.retired or not self.locations.get(key) and any(
                owner == key[0] and identity in book.observed for owner, book in self.books):
            self._retire(scope, identity)
            record = self.retired.get(key)
            if record is not None:
                record['rows'].update(rows)

    def forget(self, identity, *, scope, cached=False):
        key = self.scope_key(scope), identity
        locations = self.locations.pop(key, set())
        for point, family in locations:
            rows = self.memory.get(point)
            if rows is not None:
                rows.pop(family, None)
                if not rows:
                    self.memory.pop(point, None)
        if locations or cached or key in self.known_rows or key in self.retired:
            self._retire(scope, identity, replaced=True)

    def remember(self, request, quote, *, scope=None, current=True, sequence=None, row_identity=None, version=None):
        selected = scope or self.capture_scope(request)
        try:
            identity = funded_route_identity(quote)
        except (KeyError, TypeError, ValueError):
            return False  # An incomplete old observation remains available through its ordinary SQL path.
        key = self.scope_key(selected), identity
        def remember_row():
            if row_identity is not None:
                self.known_rows.setdefault(key, set()).add(row_identity)
        if not current:
            if key in self.retired or any(scope == key[0] and identity in book.observed
                                          for scope, book in self.books):
                remember_row()
                self._retire(selected, identity)
                return False
            if any(self.memory.get(point, {}).get(family, {}).get('current')
                   for point, family in self.locations.get(key, ())):
                remember_row()
                return False
            existing = [(point, family, self.memory.get(point, {}).get(family))
                        for point, family in self.locations.get(key, ())]
            if existing:
                if sequence is None or any(row is not None and row['sequence'] is not None
                                            and row['sequence'] >= sequence for _, _, row in existing):
                    remember_row()
                    return False
                for old_point, old_family, _ in existing:
                    self.memory.get(old_point, {}).pop(old_family, None)
                    if not self.memory.get(old_point):
                        self.memory.pop(old_point, None)
                self.locations.pop(key, None)
        else:
            if version is None:
                self.observation_sequence += 1
                version = self.observation_sequence
            if version < self.latest_version(selected, identity):
                return False
            if any(self.memory.get(point, {}).get(family, {}).get('quote') == quote
                   for point, family in self.locations.get(key, ())):
                for point, family in self.locations[key]:
                    self.memory[point][family]['version'] = max(self.memory[point][family].get('version', 0), version)
                return False
            self.forget(identity, scope=selected)
        point = self.scope_key(selected), selected.identity
        rows = self.memory.setdefault(point, {})
        family = quote_path_family(quote)
        previous = rows.get(family)
        if previous is not None:
            if not current and not previous['current'] and previous['identity'] == identity:
                if sequence is None or previous['sequence'] is not None and sequence <= previous['sequence']:
                    return False
            elif not prefer_completed(quote, previous['quote'], scalar=request['intent'] in (0, 1),
                                      basket=request['intent'] >= 2):
                return False
            previous_key = point[0], previous['identity']
            self.locations.get(previous_key, set()).discard((point, family))
            if not self.locations.get(previous_key):
                self.locations.pop(previous_key, None)
                if previous_key not in self.retired:
                    self.known_rows.pop(previous_key, None)
        rows[family] = {'quote': deepcopy(quote), 'identity': identity, 'current': current,
                        'sequence': sequence, 'version': version or 0}
        self.locations.setdefault(key, set()).add((point, family))
        remember_row()
        self.memory.move_to_end(point)
        self._prune()
        if not current:
            for owner, book in tuple(self.books):
                if owner == key[0] and identity in book.rows and identity not in book.observed and book.on_history is not None:
                    book.on_history(quote, sequence)
        return True

    def _prune(self):
        while len(self.memory) > self.limit:
            old_point, old_rows = self.memory.popitem(last=False)
            for old_family, row in old_rows.items():
                old_key = old_point[0], row['identity']
                owners = {task for task in self.io if not task.done()}
                if row['current'] and owners:
                    # The quote payload obeys the ordinary point limit. Only
                    # its paid ordering survives until overlapping SQL work
                    # drains, so an older snapshot cannot restore it.
                    record = self.retired.setdefault(old_key, {'owners': set(),
                        'deleted': True, 'point': old_point, 'rows': set(), 'inflight_only': True})
                    record['owners'].update(owners)
                    record['version'] = max(record.get('version', 0), row.get('version', 0))
                self.locations.get(old_key, set()).discard((old_point, old_family))
                if not self.locations.get(old_key):
                    self.locations.pop(old_key, None)
                    self.known_rows.pop(old_key, None)
        self._release_retired()

    def memory_lookup(self, request, *, scope=None):
        selected = scope or self.capture_scope(request)
        rows = self.memory.get((self.scope_key(selected), selected.identity), {})
        best = None
        for row in rows.values():
            if prefer_completed(row['quote'], best, scalar=request['intent'] in (0, 1),
                                basket=request['intent'] >= 2):
                best = row['quote']
        return deepcopy(best)

    def memory_neighbors(self, request, *, scope=None):
        selected = scope or self.capture_scope(request)
        normalized = normalized_economic_request(request)
        if normalized['intent'] not in (0, 1) or len(normalized['inputs']) != 1:
            return []
        budget = int(normalized['inputs'][0]['amount'])
        intent = {**normalized, 'inputs': [{'currency': normalized['inputs'][0]['currency']}]}
        chosen = {family: {} for family in PATH_FAMILIES}
        for (scope_key, point), rows in self.memory.items():
            if scope_key != self.scope_key(selected):
                continue
            for family, row in rows.items():
                quote = row['quote']
                candidate = normalized_economic_request(quote['request'])
                candidate_intent = {**candidate, 'inputs': [{'currency': candidate['inputs'][0]['currency']}]}
                if candidate_intent != intent:
                    continue
                amount, funded = int(candidate['inputs'][0]['amount']), int(quote['inputs'][0]['amount'])
                output = int(quote['quotedOutput'])
                identity = point+':'+family
                lower = chosen[family].get('lower')
                rank = (output, -funded, -abs(amount-budget))
                if funded <= budget and (lower is None or rank > lower[0]):
                    chosen[family]['lower'] = (rank, identity, quote)
                upper = chosen[family].get('upper')
                rank = (-amount, output, -funded)
                if amount > budget and (upper is None or rank > upper[0]):
                    chosen[family]['upper'] = (rank, identity, quote)
        return [{'family': family, 'side': side, 'identity': row[1], 'quote': deepcopy(row[2])}
                for family in PATH_FAMILIES for side, row in chosen[family].items()]

    async def close(self):
        tasks = tuple(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def neighbors(self, request, *, scope=None):
        selected = scope or self.capture_scope(request)
        memory = self.memory_neighbors(request, scope=selected)
        return memory or await self.load_neighbors(request, scope=selected)

    def capture_scope(self, request):
        normalized = normalized_economic_request(request)
        chain = int(getattr(self.registry, 'chain', self.settings.NEXT_PUBLIC_CHAIN_ID))
        core = (getattr(self.registry, 'core', None)
                or configured_address(self.settings, 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS') or '').lower()
        prefix = getattr(self.store, 'scope', '')
        generation = getattr(self.registry, 'generation', None) if chain == 31338 else None
        deployment = {'chainId': chain, 'core': core,
            'helpers': (configured_address(self.settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS') or '').lower(),
            'adapter': (configured_address(self.settings, 'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS') or '').lower(),
            'generation': generation, 'storageScope': prefix,
            'runtimeConfiguration': getattr(self.settings, 'CYBERGOLD_RUNTIME_CONFIG_ID', None),
            'marketFeePpm': [get_market_fee_rate(chain, row['currency'], normalized['outputCurrency'], 'exact-in')
                             for row in normalized['inputs']],
            'observedFeeScope': self.fee_scope() if self.fee_scope else None}
        identity = request_identity(normalized, deployment)
        return EconomicQuoteScope(chain, core, prefix+'economic-quotes', identity,
                                  json.dumps(deployment, sort_keys=True, separators=(',', ':')))

    async def load_neighbors(self, request, *, scope=None):
        """Return lower/upper completed observations independently per path family.

        Lower means the best observed output funded within the new budget,
        including an exact request or a larger historical maximum. Upper stays
        the nearest strictly larger historical maximum for downscaled replay.
        Only the at-most-four selected complete payloads leave optional SQL.
        """
        if self.store is None:
            return []
        self.track_io(asyncio.current_task())
        try:
            normalized = normalized_economic_request(request)
            if normalized['intent'] not in (0, 1) or len(normalized['inputs']) != 1:
                return []
            selected = scope or self.capture_scope(request)
            deployment = json.loads(selected.deployment)
            budget = int(normalized['inputs'][0]['amount'])
            intent = {**normalized, 'inputs': [{'currency': normalized['inputs'][0]['currency']}]}
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                cursor = await connection.execute('''WITH recent AS (
                    SELECT split_part(identity, ':', 1) AS point
                    FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s
                    GROUP BY point
                    ORDER BY MAX((payload->>'savedSequence')::bigint) DESC, point LIMIT %s
                ) SELECT identity,
                    payload->'quote'->'request' AS request,
                    payload->'quote'->>'quotedOutput' AS quoted_output,
                    payload->'quote'->'inputs'->0->>'amount' AS funded_input,
                    payload->'quote'->'inputs' AS funded_inputs,
                    payload->'quote'->'plan'->'body' AS body,
                    payload->>'candidateIdentity' AS candidate_identity,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM jsonb_array_elements(COALESCE(
                            payload->'quote'->'plan'->'body'->'branches', '[]'::jsonb)) AS branch
                        WHERE branch->>'kind'='0' AND (branch->>'amountIn')::numeric > 0
                    ) THEN 'core' ELSE 'market' END AS path_family,
                    (payload->>'savedSequence')::bigint AS sequence
                    FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s
                    AND split_part(identity, ':', 1) IN (SELECT point FROM recent)
                    ORDER BY (payload->>'savedSequence')::bigint DESC, identity''',
                    (selected.chain, selected.core, selected.namespace, self.limit,
                     selected.chain, selected.core, selected.namespace))
                headers = await cursor.fetchall()
                chosen = {family: {} for family in PATH_FAMILIES}
                points = set()
                candidates = set()
                sequences = {}
                candidate_rows = {}
                for row in headers:
                    try:
                        candidate = normalized_economic_request(row['request'])
                        if len(candidate['inputs']) != 1:
                            continue
                        candidate_intent = {**candidate, 'inputs': [{'currency': candidate['inputs'][0]['currency']}]}
                        if candidate_intent != intent:
                            continue
                        family = row.get('path_family', 'market')
                        identity = request_identity(candidate, deployment)
                        if row['identity'] not in (identity, identity+':'+family):
                            continue
                        candidate_identity = row.get('candidate_identity')
                        if candidate_identity is None and row.get('body') is not None:
                            candidate_identity = funded_route_identity({'inputs': row['funded_inputs'],
                                                                        'plan': {'body': row['body']}})
                        if candidate_identity is not None:
                            key = self.scope_key(selected), candidate_identity
                            candidate_rows.setdefault(candidate_identity, set()).add(row['identity'])
                            if key in self.retired:
                                self.retired[key]['rows'].add(row['identity'])
                            if candidate_identity in candidates:
                                continue
                            candidates.add(candidate_identity)
                            if self.history_replaced(selected, candidate_identity):
                                self.discard_history(selected, candidate_identity, candidate_rows[candidate_identity])
                                continue
                        # Old single-winner and new per-family rows can name
                        # the same logical point. Their producer sequence keeps
                        # the existing most-recent overwrite semantics.
                        point = (identity, family)
                        if point in points:
                            continue
                        points.add(point)
                        sequences[row['identity']] = row.get('sequence')
                        amount = int(candidate['inputs'][0]['amount'])
                        funded = int(row.get('funded_input') or amount)
                        output = int(row['quoted_output'])
                        lower = chosen[family].get('lower')
                        rank = (output, -funded, -abs(amount-budget))
                        if funded <= budget and (lower is None or rank > lower[3]):
                            chosen[family]['lower'] = (amount, row['identity'], output, rank)
                        upper = chosen[family].get('upper')
                        if amount > budget and (upper is None or amount < upper[0]
                                or amount == upper[0] and (output, -funded) > (upper[2], -upper[3])):
                            chosen[family]['upper'] = (amount, row['identity'], output, funded)
                    except (KeyError, TypeError, ValueError, AttributeError):
                        continue
                projected = [(family, side, chosen[family][side][1]) for family in PATH_FAMILIES
                             for side in ('lower', 'upper') if side in chosen[family]]
                identities = list(dict.fromkeys(identity for _, _, identity in projected))
                if not identities:
                    return self.memory_neighbors(request, scope=selected)
                cursor = await connection.execute('''SELECT identity, payload->'quote' AS quote
                    FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s
                    AND namespace=%s AND identity=ANY(%s)''',
                    (selected.chain, selected.core, selected.namespace, identities))
                quotes = {row['identity']: row['quote'] for row in await cursor.fetchall()}
                result = []
                for family, side, identity in projected:
                    if identity in quotes:
                        value = quotes[identity]
                        try:
                            candidate_identity = funded_route_identity(value)
                        except (KeyError, TypeError, ValueError):
                            candidate_identity = None
                        if candidate_identity is not None:
                            key = self.scope_key(selected), candidate_identity
                            if self.history_replaced(selected, candidate_identity):
                                self.discard_history(selected, candidate_identity, candidate_rows.get(candidate_identity, ()))
                                continue
                        self.remember(value['request'], value, scope=self.point_scope(selected, value['request']),
                                      current=False, sequence=sequences.get(identity), row_identity=identity)
                        if candidate_identity is not None and (key in self.locations or key in self.retired):
                            self.known_rows.setdefault(key, set()).update(candidate_rows.get(candidate_identity, ()))
                        canonical = self.historical_observation(selected, value) if candidate_identity is not None else (value, None)
                        if canonical is not None:
                            result.append({'family': family, 'side': side, 'identity': identity,
                                           'quote': deepcopy(canonical[0])})
                return self.memory_neighbors(request, scope=selected) or result
        except Exception:
            return []

    async def lookup(self, request, *, scope=None):
        selected = scope or self.capture_scope(request)
        memory = self.memory_lookup(request, scope=selected)
        return memory if memory is not None else await self.load_lookup(request, scope=selected)

    async def load_lookup(self, request, *, scope=None):
        if self.store is None:
            return None
        self.track_io(asyncio.current_task())
        try:
            selected = scope or self.capture_scope(request)
            scalar = request['intent'] in (0, 1)
            identities = ([selected.identity, *(selected.identity+':'+family for family in PATH_FAMILIES)]
                          if scalar else [selected.identity])
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                cursor = await connection.execute('''SELECT identity,payload FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=ANY(%s)
                    ORDER BY (payload->>'savedSequence')::bigint DESC, identity''',
                    (selected.chain, selected.core, selected.namespace, identities))
                best, families = None, set()
                for row in await cursor.fetchall():
                    value = row['payload']['quote']
                    try:
                        candidate_identity = funded_route_identity(value)
                    except (KeyError, TypeError, ValueError):
                        candidate_identity = None
                    if candidate_identity is not None and self.history_replaced(selected, candidate_identity):
                        self.discard_history(selected, candidate_identity,
                                             [row['identity']] if row.get('identity') is not None else [])
                        continue
                    family = quote_path_family(value)
                    if family in families:
                        continue
                    families.add(family)
                    self.remember(request, value, scope=selected, current=False,
                                  sequence=row['payload'].get('savedSequence'), row_identity=row.get('identity'))
                    canonical = self.historical_observation(selected, value) if candidate_identity is not None else (value, None)
                    if canonical is not None and prefer_completed(canonical[0], best, scalar=scalar, basket=request['intent'] >= 2):
                        best = canonical[0]
                return self.memory_lookup(request, scope=selected) or deepcopy(best)
        except Exception:
            # Optional cache availability never rejects ordinary search.
            return None

    async def save(self, request, quote, *, scope=None):
        selected = scope or self.capture_scope(request)
        self.remember(request, quote, scope=selected)
        return await self.persist(request, quote, scope=selected)

    async def persist(self, request, quote, *, scope=None, version=None):
        if self.store is None:
            return False
        self.track_io(asyncio.current_task())
        try:
            selected = scope or self.capture_scope(request)
            identity = (selected.identity+':'+quote_path_family(quote)
                        if request['intent'] in (0, 1) else selected.identity)
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                async with connection.transaction():
                    # One existing-table row serializes sequence assignment and
                    # pruning for this chain/Core/generation scope. It is not a
                    # search lease: errors simply leave the quote uncached.
                    counter = (selected.chain, selected.core,
                               selected.namespace+'-sequence', 'commits')
                    await connection.execute('''INSERT INTO cybergold_uniswap_state
                        VALUES (%s,%s,%s,%s,'{"sequence":0}'::jsonb) ON CONFLICT DO NOTHING''', counter)
                    cursor = await connection.execute('''UPDATE cybergold_uniswap_state
                        SET payload=jsonb_build_object('sequence', (payload->>'sequence')::bigint+1)
                        WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s
                        RETURNING (payload->>'sequence')::bigint AS sequence''', counter)
                    sequence = (await cursor.fetchone())['sequence']
                    if version is not None and version < self.latest_version(selected, funded_route_identity(quote)):
                        return False
                    family = quote_path_family(quote)
                    row = self.memory.get((self.scope_key(selected), selected.identity), {}).get(family)
                    if row is not None:
                        quote = row['quote']
                    else:
                        try:
                            candidate_identity = funded_route_identity(quote)
                        except (KeyError, TypeError, ValueError):
                            candidate_identity = None
                        retired = self.retired.get((self.scope_key(selected), candidate_identity))
                        if retired is not None and not retired.get('inflight_only'):
                            return False
                    try:
                        candidate_identity = funded_route_identity(quote)
                    except (KeyError, TypeError, ValueError):
                        candidate_identity = None
                    encoded = json.dumps(deepcopy(quote))
                    await connection.execute('''INSERT INTO cybergold_uniswap_state
                        VALUES (%s,%s,%s,%s,jsonb_build_object('quote', %s::jsonb,
                            'savedSequence', %s::bigint, 'savedAt', clock_timestamp(),
                            'candidateIdentity', %s::text))
                        ON CONFLICT(chain_id,core_address,namespace,identity)
                        DO UPDATE SET payload=EXCLUDED.payload''',
                        (selected.chain, selected.core, selected.namespace, identity, encoded, sequence, candidate_identity))
                    await connection.execute('''DELETE FROM cybergold_uniswap_state
                        WHERE chain_id=%s AND core_address=%s AND namespace=%s
                        AND split_part(identity, ':', 1) IN (
                            SELECT split_part(identity, ':', 1) AS point
                            FROM cybergold_uniswap_state
                            WHERE chain_id=%s AND core_address=%s AND namespace=%s
                            GROUP BY point
                            ORDER BY MAX((payload->>'savedSequence')::bigint) DESC, point
                            OFFSET %s)''',
                        (selected.chain, selected.core, selected.namespace,
                         selected.chain, selected.core, selected.namespace, self.limit))
            return True
        except Exception:
            return False

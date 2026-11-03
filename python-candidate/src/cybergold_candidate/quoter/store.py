"""Shared completed economic observations in the existing optional SQL store.

A stored quote keeps its original context and semantic plan. It is a historical
display/seed observation; lookup does not reprice or prepare a transaction.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

from ..market_fee import get_market_fee_rate
from ..protocol_config import configured_address
from .path_families import PATH_FAMILIES, quote_path_family
from .ranking import prefer_completed


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

    async def neighbors(self, request, *, scope=None):
        """Return lower/upper completed observations independently per path family.

        Lower means the best observed output funded within the new budget,
        including an exact request or a larger historical maximum. Upper stays
        the nearest strictly larger historical maximum for downscaled replay.
        Only the at-most-four selected complete payloads leave optional SQL.
        """
        if self.store is None:
            return []
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
                for row in headers:
                    try:
                        candidate = normalized_economic_request(row['request'])
                        if len(candidate['inputs']) != 1:
                            continue
                        candidate_intent = {**candidate, 'inputs': [{'currency': candidate['inputs'][0]['currency']}]}
                        family = row.get('path_family', 'market')
                        identity = request_identity(candidate, deployment)
                        if candidate_intent != intent or row['identity'] not in (identity, identity+':'+family):
                            continue
                        # Old single-winner and new per-family rows can name
                        # the same logical point. Their producer sequence keeps
                        # the existing most-recent overwrite semantics.
                        point = (identity, family)
                        if point in points:
                            continue
                        points.add(point)
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
                    return []
                cursor = await connection.execute('''SELECT identity, payload->'quote' AS quote
                    FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s
                    AND namespace=%s AND identity=ANY(%s)''',
                    (selected.chain, selected.core, selected.namespace, identities))
                quotes = {row['identity']: row['quote'] for row in await cursor.fetchall()}
                result = []
                for family, side, identity in projected:
                    if identity in quotes:
                        result.append({'family': family, 'side': side, 'identity': identity,
                                       'quote': deepcopy(quotes[identity])})
                return result
        except Exception:
            return []

    async def lookup(self, request, *, scope=None):
        if self.store is None:
            return None
        try:
            selected = scope or self.capture_scope(request)
            scalar = request['intent'] in (0, 1)
            identities = ([selected.identity, *(selected.identity+':'+family for family in PATH_FAMILIES)]
                          if scalar else [selected.identity])
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                cursor = await connection.execute('''SELECT payload FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=ANY(%s)
                    ORDER BY (payload->>'savedSequence')::bigint DESC, identity''',
                    (selected.chain, selected.core, selected.namespace, identities))
                best, families = None, set()
                for row in await cursor.fetchall():
                    value = row['payload']['quote']
                    family = quote_path_family(value)
                    if family in families:
                        continue
                    families.add(family)
                    if prefer_completed(value, best, scalar=scalar, basket=request['intent'] >= 2):
                        best = value
                return deepcopy(best)
        except Exception:
            # Optional cache availability never rejects ordinary search.
            return None

    async def save(self, request, quote, *, scope=None):
        if self.store is None:
            return False
        try:
            selected = scope or self.capture_scope(request)
            identity = (selected.identity+':'+quote_path_family(quote)
                        if request['intent'] in (0, 1) else selected.identity)
            encoded = json.dumps(deepcopy(quote))
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
                    await connection.execute('''INSERT INTO cybergold_uniswap_state
                        VALUES (%s,%s,%s,%s,jsonb_build_object('quote', %s::jsonb,
                            'savedSequence', %s::bigint, 'savedAt', clock_timestamp()))
                        ON CONFLICT(chain_id,core_address,namespace,identity)
                        DO UPDATE SET payload=EXCLUDED.payload''',
                        (selected.chain, selected.core, selected.namespace, identity, encoded, sequence))
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

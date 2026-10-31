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
        """Project bounded headers, then retrieve only the selected neighbors.

        The lower candidate is the best observed output fitting the budget;
        a nearer but poor quote must not hide it. The upper remains nearest
        for the existing arithmetic hint and downscaled replay. The captured
        identity preserves deployment/configuration family without a head or
        new freshness rule. Historical outputs only order fresh replay work.
        """
        empty = {'lower': None, 'upper': None}
        if self.store is None:
            return empty
        try:
            normalized = normalized_economic_request(request)
            if normalized['intent'] not in (0, 1) or len(normalized['inputs']) != 1:
                return empty
            selected = scope or self.capture_scope(request)
            deployment = json.loads(selected.deployment)
            budget = int(normalized['inputs'][0]['amount'])
            family = {**normalized, 'inputs': [{'currency': normalized['inputs'][0]['currency']}]}
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                cursor = await connection.execute('''SELECT identity,
                    payload->'quote'->'request' AS request,
                    payload->'quote'->>'quotedOutput' AS quoted_output,
                    (payload->>'savedSequence')::bigint AS sequence
                    FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s
                    ORDER BY (payload->>'savedSequence')::bigint DESC, identity LIMIT %s''',
                    (selected.chain, selected.core, selected.namespace, self.limit))
                headers = await cursor.fetchall()
                chosen = {}
                for row in headers:
                    try:
                        candidate = normalized_economic_request(row['request'])
                        if len(candidate['inputs']) != 1:
                            continue
                        candidate_family = {**candidate, 'inputs': [{'currency': candidate['inputs'][0]['currency']}]}
                        if candidate_family != family or request_identity(candidate, deployment) != row['identity']:
                            continue
                        amount = int(candidate['inputs'][0]['amount'])
                        side = 'lower' if amount < budget else 'upper' if amount > budget else None
                        if side is None:
                            continue
                        previous = chosen.get(side)
                        # Rank scalar outputs with exact integers. Equal lower
                        # outputs preserve the prior nearest-budget tie break;
                        # equal headers retain the last successful save.
                        output = int(row['quoted_output']) if side == 'lower' else 0
                        if previous is None or (
                                (output, amount) > (previous[2], previous[0]) if side == 'lower'
                                else amount < previous[0]):
                            chosen[side] = (amount, row['identity'], output)
                    except (KeyError, TypeError, ValueError, AttributeError):
                        continue
                if not chosen:
                    return empty
                cursor = await connection.execute('''SELECT identity, payload->'quote' AS quote
                    FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s
                    AND namespace=%s AND identity=ANY(%s)''',
                    (selected.chain, selected.core, selected.namespace, [row[1] for row in chosen.values()]))
                quotes = {row['identity']: row['quote'] for row in await cursor.fetchall()}
                return {side: {'identity': chosen[side][1], 'quote': deepcopy(quotes[chosen[side][1]])}
                        if side in chosen and chosen[side][1] in quotes else None for side in empty}
        except Exception:
            return empty

    async def lookup(self, request, *, scope=None):
        if self.store is None:
            return None
        try:
            selected = scope or self.capture_scope(request)
            await self.store.prepare()
            async with self.store.database.connection() as connection:
                cursor = await connection.execute('''SELECT payload FROM cybergold_uniswap_state
                    WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s''',
                    (selected.chain, selected.core, selected.namespace, selected.identity))
                row = await cursor.fetchone()
                return deepcopy(row['payload']['quote']) if row else None
        except Exception:
            # Optional cache availability never rejects ordinary search.
            return None

    async def save(self, request, quote, *, scope=None):
        if self.store is None:
            return False
        try:
            selected = scope or self.capture_scope(request)
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
                        (selected.chain, selected.core, selected.namespace, selected.identity, encoded, sequence))
                    await connection.execute('''DELETE FROM cybergold_uniswap_state
                        WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity IN (
                            SELECT identity FROM cybergold_uniswap_state
                            WHERE chain_id=%s AND core_address=%s AND namespace=%s
                            ORDER BY (payload->>'savedSequence')::bigint DESC, identity
                            OFFSET %s)''',
                        (selected.chain, selected.core, selected.namespace,
                         selected.chain, selected.core, selected.namespace, self.limit))
            return True
        except Exception:
            return False

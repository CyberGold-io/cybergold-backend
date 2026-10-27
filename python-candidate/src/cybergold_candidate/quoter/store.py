"""Shared completed economic observations in the existing optional SQL store.

A stored quote keeps its original context and semantic plan. It is a historical
display/seed observation; lookup does not reprice or prepare a transaction.
"""
from copy import deepcopy
from dataclasses import dataclass
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


def normalized_economic_request(request):
    """Preserve ordered basket inputs; exclude transport and execution fields."""
    return {'intent': int(request['intent']),
        'inputs': [{'currency': row['currency'].lower(), 'amount': str(int(row['amount']))}
                   for row in request['inputs']],
        'outputCurrency': request['outputCurrency'].lower()}


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
        encoded = json.dumps({'request': normalized, 'deployment': deployment},
                             sort_keys=True, separators=(',', ':'))
        identity = hashlib.sha256(encoded.encode()).hexdigest()
        return EconomicQuoteScope(chain, core, prefix+'economic-quotes', identity)

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

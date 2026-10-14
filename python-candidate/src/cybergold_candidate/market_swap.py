"""Market quote coordinator: inventory -> protocol quotes -> fee-neutral plan.

Quoter qualification is deliberately distinct from a real wallet's signed
permit-and-swap simulation. Fees are first-party pricing facts, not signatures.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from typing import Literal
from fractions import Fraction
from types import SimpleNamespace

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter
from web3 import Web3

from .basket_preview import InvalidPreview, handle_basket_preview
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS, floor, ceil
from .market_fee import get_market_fee_rate, gross_buy_target, quoted_fee, routed_sell_budget
from .quote_errors import public_quote_error, QuoteFailure
from .trade_observation import QuoteObservation
from .sdk_worker import SdkWorker, SdkWorkerError, MissingPoolState
from .uniswap_routes import RoutePlan, candidate_branches, supported_route, resize_branches, v3_path, pool_key
from .uniswap_state import ZERO
from .wallet_balances import TOKENS
from .quote_models import PoolBaseline, LegModel
from .quote_cache import IntentSharing
from .rpc_diagnostics import route_count, freeze_quote_work


class MarketQuoteRequest(BaseModel):
    side: Literal['buy', 'sell']
    mode: Literal['exact-in', 'exact-out']
    counterToken: str
    amount: str
    adapter: str | None = None
    recipient: str
    deadline: str
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)
    retainedPlan: dict | None = None


class MarketModelRequest(BaseModel):
    side: Literal['buy', 'sell']
    mode: Literal['exact-in', 'exact-out']
    counterToken: str
    adapter: str | None = None


REQUEST = TypeAdapter(MarketQuoteRequest)
MODEL_REQUEST = TypeAdapter(MarketModelRequest)
ADAPTER_TYPE = '(bool,uint256,uint256,(uint256,(uint8,address,uint24,int24,address,bytes)[])[])'
PROTOCOL = {'v2': 0, 'v3': 1, 'v4': 2}


def encode_adapter(plan):
    branches = []
    for branch in plan['branches']:
        hops = []
        for hop in branch['hops']:
            pool = hop['pool']
            output = pool['token1' if hop['zeroForOne'] else 'token0']['address']
            hops.append((PROTOCOL[pool['protocol']], output, int(pool['feePips']),
                int(pool.get('tickSpacing') or 0), pool.get('hooks') or ZERO, b''))
        branches.append((int(branch['amountIn']) if plan['mode'] == 'exactIn' else 0, hops))
    return Web3.to_hex(Web3().codec.encode([ADAPTER_TYPE], [(
        plan['mode'] == 'exactIn', int(plan['limit']), int(plan['deadline']), branches)]))


def market_family(request, chain, core):
    return json.dumps(['market', request['side'], request['mode'], request['counterToken'].lower(),
        request['adapter'].lower()], separators=(',', ':'))


class DailyRecipientCache:
    """Advisory owner observation. Quotes never acquire/refresh this over RPC."""
    def __init__(self, store=None, helpers=None, now=None):
        self.store, self.helpers = store, helpers
        self.now = now or time.time
        self.value = None
        self.loaded = False
        self.loaded_at = 0
        self.lock = asyncio.Lock()
        self.background = set()
        self.load_task = None
        self.revision = 0

    def track(self, operation):
        task = asyncio.create_task(operation)
        self.background.add(task)
        def done(task):
            self.background.discard(task)
            if not task.cancelled():
                task.exception()
        task.add_done_callback(done)
        return task

    async def load(self, *, wait=False):
        if (not self.loaded or self.now()-self.loaded_at >= 86_400) and self.load_task is None:
            revision = self.revision
            async def recover():
                self.loaded = True
                self.loaded_at = self.now()
                if self.store:
                    try:
                        value = (await self.store.load('recipient')).get(self.helpers.lower())
                        if revision == self.revision:
                            self.value = value
                    except Exception:
                        pass
            task = self.track(recover())
            self.load_task = task
            def done(task):
                if self.load_task is task:
                    self.load_task = None
            task.add_done_callback(done)
        if wait and self.load_task:
            await asyncio.shield(self.load_task)
        return deepcopy(self.value)

    async def observe(self, address):
        self.revision += 1
        self.value = {'address': address, 'observedAt': datetime.now(timezone.utc).isoformat(),
                      'observedSeconds': self.now()}
        if self.store:
            async def save():
                try:
                    await self.store.save('recipient', self.helpers.lower(), deepcopy(self.value))
                except Exception:
                    pass
            self.track(save())

    def reset(self):
        self.revision += 1
        self.value = None
        self.loaded = False
        self.load_task = None
        for task in tuple(self.background):
            task.cancel()

    async def close(self):
        tasks = tuple(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def refresh(self, rpc, block):
        # Called by the ordinary worker run, never from a quote request.
        async with self.lock:
            await self.load(wait=True)
            if self.value and self.now()-self.value.get('observedSeconds', 0) < 86_400:
                return
            try:
                owner, = await rpc.read_function(self.helpers, 'owner()', [], [], ['address'], block)
                await self.observe(owner)
            except Exception:
                pass


class MarketQuotes:
    def __init__(self, settings, registry, sdk=None, *, recipient_cache=None, now=None, request_resolver=None):
        self.settings, self.registry = settings, registry
        self.sdk = sdk or SdkWorker()
        self.recipient_cache = recipient_cache
        self.request_resolver = request_resolver
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.models = OrderedDict()
        self.generation = None
        self.shared = registry.pending.__class__()
        self.quoter_v4 = os_environ('NEXT_PUBLIC_UNISWAP_V4_QUOTER_ADDRESS', '0x52F0E24D1c21C8A0cB1e5a5dD6198556BD9E1203')
        self.semaphore = asyncio.Semaphore(8)
        self.sharing = IntentSharing(SimpleNamespace(settings=settings,
            routes=SimpleNamespace(rpc=registry.get_rpc()), get=self._get), head=self.head)

    async def head(self):
        rpc = self.registry.get_rpc()
        return await self.registry.pending.one(('head', self.registry.chain), lambda: rpc.block(None))

    async def close(self):
        await self.shared.close()
        await self.sharing.close()
        await self.sdk.close()
        if self.recipient_cache:
            await self.recipient_cache.close()

    def packet(self, request):
        family = market_family(request, self.registry.chain, self.registry.core)
        previous = self.models.get(family)
        packet = deepcopy(previous) if previous else {'namespace': 'market', 'family': family, 'routes': [],
            'intent': {name: request[name] for name in ('side', 'mode', 'counterToken', 'adapter')},
            'cygld': self.registry.core}
        token_in, token_out = (request['counterToken'], self.registry.core) if request['side'] == 'buy' else (
            self.registry.core, request['counterToken'])
        packet['feeRatePpm'] = get_market_fee_rate(self.registry.chain, token_in, token_out, request['mode'])
        return packet

    async def observe_generation(self, generation):
        if generation is not None and generation != self.generation:
            self.generation = generation
            self.models.clear()
            await self.registry.observe_generation(generation)
            if self.recipient_cache:
                self.recipient_cache.reset()

    async def get_model(self, request, *, block=None):
        if self.request_resolver:
            request = await self.request_resolver(request)
        generation = self.generation
        request = MarketModelRequest.model_validate(request).model_dump()
        for name in ('counterToken', 'adapter'):
            request[name] = Web3.to_checksum_address(request[name])
        await self.registry.ensure_loaded()
        rpc = self.registry.get_rpc()
        block = block or await self.head()
        packet = self.packet(request)
        token_in, token_out = (request['counterToken'], self.registry.core) if request['side'] == 'buy' else (
            self.registry.core, request['counterToken'])
        routes = []
        for pool in list(self.registry.inventory.values()):
            tokens = {token['address'].lower() for token in (pool['token0'], pool['token1'])}
            if tokens != {token_in.lower(), token_out.lower()}:
                continue
            try:
                state = await self.registry.snapshot(pool, block)
                zero_for_one = token_in.lower() == pool['token0']['address'].lower()
                baseline = self.baseline(state, zero_for_one)
                def fraction(value):
                    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}
                route = {'version': 1, 'executionContext': 'helpers-market',
                    'mode': 'exactIn' if request['mode'] == 'exact-in' else 'exactOut',
                    'tokenIn': token_in, 'tokenOut': token_out,
                    'branches': [{'amountIn': '0', 'hops': [{'pool': deepcopy(pool), 'zeroForOne': zero_for_one}]}],
                    'inputAmount': '0', 'outputAmount': '0', 'limit': '0', 'deadline': '0'}
                old = next((row for row in packet['routes'] if row['route']['branches'][0]['hops'][0]['pool']['id'] == pool['id']), None)
                routes.append({'route': route, 'amountIn': '0', 'amountOut': '0', 'points': old['points'] if old else [],
                    'exchangeRate': fraction(baseline.exchange), 'feeRetention': fraction(baseline.fee_retention),
                    **({'localImpact': fraction(baseline.local_impact)} if baseline.local_impact is not None else {})})
            except Exception:
                pass
        if generation != self.generation:
            return self.packet(request)
        if routes:
            packet['routes'] = routes
            packet['context'] = {'chainId': self.registry.chain, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'observedAt': self.now()}
            self.models[packet['family']] = deepcopy(packet)
        return packet

    def baseline(self, state, zero_for_one):
        if state['protocol'] == 'v2':
            a, b = int(state['reserve0']), int(state['reserve1'])
            source, target = (a, b) if zero_for_one else (b, a)
            return PoolBaseline(Fraction(target, source), Fraction(997, 1000), Fraction(1, source))
        fee = int(state['feePips'])
        if state['protocol'] == 'v4':
            packed = int(state.get('protocolFee', 0))
            protocol = packed & 0xfff if zero_for_one else packed >> 12
            lp = int(state.get('lpFee', fee))
            fee = protocol+lp-protocol*lp//1_000_000
        return PoolBaseline.v3(int(state['sqrtRatioX96']), int(state['liquidity']), fee, zero_for_one)

    async def route_baseline(self, plan, block):
        """Indicative marginal/impact metadata; exact swap arithmetic is SDK-owned."""
        branches = []
        total = sum(int(branch['amountIn']) for branch in plan['branches'])
        for branch in plan['branches']:
            rate, retention, impact = Fraction(1), Fraction(1), Fraction(0)
            for hop in branch['hops']:
                state = await self.registry.snapshot(hop['pool'], block)
                baseline = self.baseline(state, hop['zeroForOne'])
                if baseline.local_impact is None:
                    raise ValueError('Indicative pool impact unavailable')
                impact += baseline.local_impact*baseline.fee_retention*rate*retention
                rate *= baseline.exchange
                retention *= baseline.fee_retention
            weight = Fraction(int(branch['amountIn']), total) if total else Fraction(1, len(plan['branches']))
            branches.append((weight, PoolBaseline(rate, retention, impact/retention)))
        exchange = sum(weight*baseline.exchange for weight, baseline in branches)
        effective_rate = sum(weight*baseline.exchange*baseline.fee_retention for weight, baseline in branches)
        retention = effective_rate/exchange
        effective_impact = sum(weight**2*baseline.exchange*baseline.fee_retention**2*baseline.local_impact
            for weight, baseline in branches)/effective_rate
        return PoolBaseline(exchange, retention, effective_impact/retention)

    def estimate(self, packet, request):
        exact_in = request['mode'] == 'exact-in'
        rate = packet['feeRatePpm']
        values = []
        for row in packet['routes']:
            if 'exchangeRate' not in row:
                continue
            def f(value):
                return Fraction(int(value['numerator']), int(value['denominator']))
            baseline = PoolBaseline(f(row['exchangeRate']), f(row['feeRetention']),
                f(row['localImpact']) if 'localImpact' in row else None)
            amount = int(request['amount'])
            raw = routed_sell_budget(amount, rate)[0] if request['side'] == 'sell' and exact_in else (
                gross_buy_target(amount, rate)[0] if request['side'] == 'buy' and not exact_in else amount)
            predicted = LegModel(baseline=baseline).predict(raw, 'local', inverse=not exact_in)
            if predicted:
                if request['side'] == 'buy' and exact_in:
                    predicted -= quoted_fee(predicted, rate)
                elif request['side'] == 'sell' and not exact_in:
                    predicted += quoted_fee(predicted, rate)
                values.append(predicted)
        return str(max(values) if exact_in else min(values)) if values else None

    async def connector_inventory(self, token_in, token_out, block):
        """Preserve existing direct/via-WETH V3 fee coverage; add V2 connectors."""
        rpc = self.registry.get_rpc()
        weth = dict(TOKENS)['weth']
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if self.registry.lookup_month != month:
            self.registry.lookups = {key: value for key, value in self.registry.lookups.items() if value is not None}
            self.registry.lookup_month = month
        endpoints = {token_in.lower(), token_out.lower()}
        for pool in self.registry.inventory.values():
            if any(token['address'].lower() == self.registry.core.lower() for token in (pool['token0'], pool['token1'])):
                endpoints.update(token['address'].lower() for token in (pool['token0'], pool['token1']))
        # Existing direct/via-WETH paths plus CYGLD-counter connectors; do not
        # construct a complete token-universe cross product on every edit.
        pairs = {tuple(sorted((a, b))) for a in endpoints for b in (
            token_in.lower(), token_out.lower(), weth.lower()) if a != b}
        known = {(pool['protocol'], tuple(sorted((pool['token0']['address'].lower(),
            pool['token1']['address'].lower()))), int(pool['feePips'])): pool
            for pool in self.registry.inventory.values() if pool.get('address')}
        async def v2(pair):
            key = ('v2', pair, 3000)
            if key in known or key in self.registry.lookups:
                return
            try:
                address, = await rpc.read_function(rpc.v2_factory, 'getPair(address,address)',
                    ['address', 'address'], list(pair), ['address'], block)
                if address.lower() == ZERO:
                    self.registry.lookups[key] = None
                    return
                a, b = await asyncio.gather(*(self.registry.token_metadata(token, block) for token in pair))
                pool = {'id': address.lower(), 'protocol': 'v2', 'address': address,
                    'token0': a, 'token1': b, 'feePips': 3000}
                self.registry.inventory[pool['id']] = pool
                self.registry.lookups[key] = pool
                self.registry.persist('inventory', pool['id'], pool)
            except Exception:
                pass
        async def v3(pair, fee):
            key = ('v3', pair, fee)
            if key in known or key in self.registry.lookups:
                return
            address = None
            try:
                address, = await rpc.read_function(rpc.factory, 'getPool(address,address,uint24)',
                    ['address', 'address', 'uint24'], [*pair, fee], ['address'], block)
                if address.lower() == ZERO:
                    self.registry.lookups[key] = None
                    return
                a, b = await asyncio.gather(*(self.registry.token_metadata(token, block) for token in pair))
                spacing, = await rpc.read_function(address, 'tickSpacing()', [], [], ['int24'], block)
                pool = {'id': address.lower(), 'protocol': 'v3', 'address': address,
                    'token0': a, 'token1': b, 'feePips': fee, 'tickSpacing': spacing}
                self.registry.inventory[pool['id']] = pool
                self.registry.lookups[key] = pool
                self.registry.persist('inventory', pool['id'], pool)
            except Exception:
                # A failed optional lookup is unknown, not canonical absence.
                # Retain a path-key candidate for the ordinary V3 Quoter even
                # when local pool/model metadata is unavailable.
                a, b = (self.registry.token(token, 18) for token in pair)
                pool = {'id': 'v3:'+':'.join((*pair, str(fee))), 'protocol': 'v3',
                    'token0': a, 'token1': b, 'feePips': fee,
                    'tickSpacing': {100: 1, 500: 10, 3000: 60, 10000: 200}[fee],
                    **({'address': address} if address else {})}
                self.registry.inventory[pool['id']] = pool
        pending = set()
        try:
            for pair in pairs:
                pending.add(asyncio.create_task(v2(pair)))
                for fee in (100, 500, 3000, 10000):
                    pending.add(asyncio.create_task(v3(pair, fee)))
                if len(pending) >= 32:
                    await asyncio.gather(*pending)
                    pending.clear()
            await asyncio.gather(*pending)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def quote_hop(self, hop, mode, amount, block):
        rpc = self.registry.get_rpc()
        pool = hop['pool']
        if pool['protocol'] == 'v2':
            source, target = (pool['token0']['address'], pool['token1']['address']) if hop['zeroForOne'] else (
                pool['token1']['address'], pool['token0']['address'])
            router = os_environ('NEXT_PUBLIC_UNISWAP_V2_ROUTER_ADDRESS', '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D')
            try:
                method = 'getAmountsOut(uint256,address[])' if mode == 'exactIn' else 'getAmountsIn(uint256,address[])'
                amounts, = await rpc.read_function(router, method, ['uint256', 'address[]'],
                    [amount, [source, target]], ['uint256[]'], block)
                return {'amountIn': str(amounts[0]), 'amountOut': str(amounts[-1]), 'qualification': 'quoter'}
            except Exception:
                snapshot = await self.registry.snapshot(pool, block)
                value = await self.sdk.request({'operation': 'quote', 'mode': mode, 'amount': str(amount),
                    'poolId': pool['id'], 'pools': [snapshot], 'zeroForOne': hop['zeroForOne']})
                value['qualification'] = 'sdk'
                return value
        if pool['protocol'] == 'v3':
            path = v3_path([hop], mode == 'exactOut')
            method = 'quoteExactInput(bytes,uint256)' if mode == 'exactIn' else 'quoteExactOutput(bytes,uint256)'
            value = await rpc.read_function(self.settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS,
                method, ['bytes', 'uint256'], [bytes.fromhex(path[2:]), amount],
                ['uint256', 'uint160[]', 'uint32[]', 'uint256'], block)
            return {'amountIn': str(amount if mode == 'exactIn' else value[0]),
                    'amountOut': str(value[0] if mode == 'exactIn' else amount), 'qualification': 'quoter'}
        params = (pool_key(pool), hop['zeroForOne'], amount, b'')
        method = 'quoteExactInputSingle' if mode == 'exactIn' else 'quoteExactOutputSingle'
        types = '((address,address,uint24,int24,address),bool,uint128,bytes)'
        value = await rpc.read_function(self.quoter_v4, method+'('+types+')', [types], [params],
            ['uint256', 'uint256'], block)
        return {'amountIn': str(amount if mode == 'exactIn' else value[0]),
                'amountOut': str(value[0] if mode == 'exactIn' else amount), 'qualification': 'quoter',
                # The pinned BaseV4Quoter rejects a specified-side partial
                # delta; successful exact-output calls prove this target filled.
                **({'fullyFilled': True} if mode == 'exactOut' else {})}

    def resolve_branches(self, branches, token_in, token_out, mode, amount):
        """Retain route/allocation intent, use server-owned pool identities."""
        try:
            result = deepcopy(branches)
            inventory = {identity.lower(): pool for identity, pool in self.registry.inventory.items()}
            if not result:
                raise InvalidPreview('Retained route has no swap branches.')
            if mode == 'exactOut' and len(result) != 1:
                raise InvalidPreview('Exact-output split branches are not supported.')
            for branch in result:
                current = token_in.lower()
                if not branch['hops']:
                    raise InvalidPreview('Retained route has no swap hops.')
                for hop in branch['hops']:
                    pool = inventory.get(hop['pool']['id'].lower())
                    if pool is None:
                        raise InvalidPreview('Retained pool identity is unavailable.')
                    hop['pool'] = deepcopy(pool)
                    source, target = (pool['token0']['address'], pool['token1']['address']) if hop['zeroForOne'] else (
                        pool['token1']['address'], pool['token0']['address'])
                    if source.lower() != current:
                        raise InvalidPreview('Retained route input currency does not match the preceding hop.')
                    current = target.lower()
                if current != token_out.lower():
                    raise InvalidPreview('Retained route output currency does not match the intent.')
                if not supported_route(branch['hops'], mode):
                    raise InvalidPreview('Mixed exact-output routes are not supported.')
            if mode == 'exactIn':
                if any(int(branch['amountIn']) < 0 for branch in result):
                    raise InvalidPreview('Retained branch input allocation is negative.')
                result = resize_branches(result, amount)
            return result
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            if isinstance(error, InvalidPreview):
                raise
            raise InvalidPreview('Retained route cannot be resolved.') from error

    async def quote_branches(self, branches, mode, amount, block):
        try:
            value = await self.quote_sdk_branches(branches, mode, amount, block)
        except (SdkWorkerError, ValueError, TimeoutError, KeyError):
            return await self.quote_fallback_branches(branches, mode, amount, block)
        if not value.get('settled', True):
            raise InvalidPreview('Unsettled current-operation intermediate currency.')
        if mode == 'exactOut' and not value.get('fullyFilled', True):
            raise InvalidPreview('Exact-output target cannot be filled.')
        value['qualification'] = 'sdk'
        return value

    async def quote_sdk_branches(self, branches, mode, amount, block, *, candidate=None, canonical=None):
        canonical = canonical if canonical is not None else {}
        snapshots = {}
        pools = {}
        for branch in branches:
            for hop in branch['hops']:
                pool = hop['pool']
                pools.setdefault(pool['id'], pool)
        missing = {identity: pool for identity, pool in pools.items() if identity not in canonical}
        reads = {identity: asyncio.create_task(self.registry.snapshot(pool, block))
                 for identity, pool in missing.items()} if len(missing) > 1 else {}
        try:
            # Start only this candidate's required observations. Consume in
            # route order, preserving canonical insertion and read-error priority.
            for identity, pool in pools.items():
                if identity not in canonical:
                    canonical[identity] = await reads[identity] if reads else await self.registry.snapshot(pool, block)
                snapshots[identity] = deepcopy(candidate.get(identity, canonical[identity])
                    if candidate is not None else canonical[identity])
        finally:
            # These subscriptions are owned here; SharedReads preserves other
            # subscribers and cancels a producer only when nobody still needs it.
            for task in reads.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*reads.values(), return_exceptions=True)
        payload = {'operation': 'simulateRoute', 'mode': mode, 'amount': str(amount),
            'pools': list(snapshots.values()), 'route': {'branches': [
                {'amountIn': branch['amountIn'], 'hops': [{'poolId': hop['pool']['id'],
                    'zeroForOne': hop['zeroForOne']} for hop in branch['hops']]} for branch in branches]}}
        try:
            # Acquisition is on-demand and bounded per request. Ordinary Quoters
            # still provide results when a long uncovered tick path is expensive.
            for _ in range(4):
                try:
                    value = await self.sdk.request(payload)
                    if candidate is not None:
                        # Compact postState carries only changing fields. Keep
                        # the canonical coverage in the isolated candidate bank.
                        for post in value['postState']:
                            candidate[post['id']] = {**snapshots[post['id']], **post}
                    return value
                except MissingPoolState as missing:
                    for identity, snapshot in list(snapshots.items()):
                        requests = [row for row in missing.requests if row.get('poolId', row.get('id')) == identity]
                        if requests:
                            observed = await self.registry.extend_ticks(canonical[identity], requests, block)
                            canonical[identity] = observed
                            snapshots[identity] = {**snapshot, 'ticks': observed['ticks'], 'bitmapWords': observed['bitmapWords']}
                    payload['pools'] = list(snapshots.values())
        except (SdkWorkerError, ValueError, TimeoutError):
            pass
        raise SdkWorkerError('SDK route state unavailable')

    def v3_branches(self, path, mode, amount):
        from .quote_history import economic_path
        tokens, fees = economic_path(path, 'exact-in' if mode == 'exactIn' else 'exact-out')
        hops = []
        for source, target, fee in zip(tokens[:-1], tokens[1:], fees, strict=True):
            pool = next((pool for pool in self.registry.inventory.values() if pool['protocol'] == 'v3'
                and pool['feePips'] == fee and {source.lower(), target.lower()} == {
                    pool['token0']['address'].lower(), pool['token1']['address'].lower()}), None)
            if pool is None:
                raise SdkWorkerError('Selected V3 route metadata unavailable')
            hops.append({'pool': deepcopy(pool), 'zeroForOne': source.lower() == pool['token0']['address'].lower()})
        return [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]

    async def compose_core_rows(self, rows, mode, block, *, ordered_assets=None, issue=False):
        """Replay shared selected pools in BasketRouter's actual asset order."""
        prepared = []
        try:
            for index, row in enumerate(rows):
                target, best = row['target'], row['best']
                if not best or target['inputAsset'].lower() == target['outputAsset'].lower():
                    continue
                amount = int(target['amount'])
                branches = best['routePlan']['branches'] if best.get('routePlan') else self.v3_branches(best['path'], mode, amount)
                branches = self.resolve_branches(branches, target['inputAsset'], target['outputAsset'], mode, amount)
                prepared.append((index, branches))
            ids = [hop['pool']['id'] for _, branches in prepared for branch in branches for hop in branch['hops']]
            if len(ids) == len(set(ids)):
                return rows
            order = {asset.lower(): index for index, asset in enumerate(ordered_assets or [])}
            prepared.sort(key=lambda item: order.get(rows[item[0]]['target']['outputAsset' if issue else 'inputAsset'].lower(), item[0]))
            result = deepcopy(rows)
            candidate, canonical = {}, {}
            for index, branches in prepared:
                target = rows[index]['target']
                value = await self.quote_sdk_branches(branches, mode, int(target['amount']), block,
                    candidate=candidate, canonical=canonical)
                if not value.get('settled', True) or (mode == 'exactOut' and not value['fullyFilled']):
                    raise InvalidPreview('Selected Core route cannot settle its required output.')
                best = result[index]['best']
                best['quote'] = value['amountOut' if mode == 'exactIn' else 'amountIn']
                if best.get('routePlan'):
                    best['routePlan'].update(branches=branches, inputAmount=value['amountIn'], outputAmount=value['amountOut'])
            return result
        except (SdkWorkerError, ValueError, TimeoutError, KeyError):
            # An uncovered shared path uses the existing final Helpers preview.
            # Never publish a partially replayed mixture as one exact model.
            return rows

    async def quote_fallback_branches(self, branches, mode, amount, block):
        # Separate protocol calls are valid for pool-disjoint paths. Shared-pool
        # split candidates require the SDK's sequential state, never independent
        # summed quotes masquerading as a composed execution.
        identities = [hop['pool']['id'] for branch in branches for hop in branch['hops']]
        if len(identities) != len(set(identities)):
            raise SdkWorkerError('Composed shared-pool quote needs covered SDK state')
        total_in = total_out = 0
        sources = set()
        for branch in branches:
            current = int(branch['amountIn']) if mode == 'exactIn' else amount
            ordered = branch['hops'] if mode == 'exactIn' else list(reversed(branch['hops']))
            for hop in ordered:
                value = await self.quote_hop(hop, mode, current, block)
                sources.add(value.get('qualification', 'sdk'))
                current = int(value['amountOut' if mode == 'exactIn' else 'amountIn'])
            total_in += int(branch['amountIn']) if mode == 'exactIn' else current
            total_out += current if mode == 'exactIn' else amount
        return {'amountIn': str(total_in), 'amountOut': str(total_out), 'qualification':
            'sdk-and-quoter' if len(sources) > 1 else next(iter(sources), 'sdk')}

    async def reserve_quotes(self, request, block, on_update=None):
        """Core reserve legs share protocol providers, without market fees."""
        await self.registry.ensure_loaded()
        mode = 'exactIn' if request['mode'] == 'exact-in' else 'exactOut'
        for target in request['targets']:
            await self.connector_inventory(target['inputAsset'], target['outputAsset'], block)
        pools = [pool for pool in self.registry.inventory.values() if pool['protocol'] != 'v4' or (
            pool.get('hooks', ZERO).lower() == ZERO and int(pool['feePips']) < 0x800000)]
        results = [{'target': target, 'best': None, 'attempted': 0, 'succeeded': 0, 'failures': [], 'total': 0}
            for target in request['targets']]

        async def evaluate(result, branches):
            target = result['target']
            try:
                async with self.semaphore:
                    value = await self.quote_branches(branches, mode, int(target['amount']), block)
                observed = int(value['amountOut' if mode == 'exactIn' else 'amountIn'])
                plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': mode,
                    'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'], 'branches': deepcopy(branches),
                    'inputAmount': value['amountIn'], 'outputAmount': value['amountOut'], 'limit': '0', 'deadline': '0'}
                row = {'path': '0x', 'quote': str(observed), 'route': 'direct' if len(branches) == 1 and len(branches[0]['hops']) == 1 else 'mixed',
                    'feeInfo': '/'.join(str(hop['pool']['feePips']) for branch in branches for hop in branch['hops']), 'routePlan': plan}
                result['succeeded'] += 1
                best = result['best']
                if observed > 0 and (best is None or (observed > int(best['quote']) if mode == 'exactIn' else observed < int(best['quote']))):
                    result['best'] = row
                route_count('typedCompleted')
            except Exception as error:
                if len(result['failures']) < 128:
                    result['failures'].append({'path': '0x', 'rpcCode': 0, **public_quote_error(error)})
                route_count('typedCompleted')
            finally:
                result['attempted'] += 1

        async def branches_for(target):
            async for branches in candidate_branches(pools, target['inputAsset'], target['outputAsset'], mode, int(target['amount'])):
                # The existing V3 search covers its original homogeneous paths.
                if len(branches) == 1 and all(hop['pool']['protocol'] == 'v3' for hop in branches[0]['hops']):
                    continue
                yield branches

        generators = [(result, branches_for(result['target'])) for result in results]
        pending, active = list(generators), set()
        async def completed():
            nonlocal active
            done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            await asyncio.gather(*done)
            if on_update:
                await on_update(deepcopy(results))
        try:
            # One candidate per leg per turn, with the existing global budget.
            # A slow connector tail must not hide another leg's cheap route.
            while pending:
                for entry in list(pending):
                    result, generator = entry
                    try:
                        branches = await anext(generator)
                    except StopAsyncIteration:
                        pending.remove(entry)
                        continue
                    result['total'] += 1
                    route_count('typedEnumerated')
                    active.add(asyncio.create_task(evaluate(result, branches)))
                    if len(active) >= 8:
                        await completed()
            while active:
                await completed()
        except BaseException as error:
            freeze_quote_work(error)
            raise
        finally:
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            await asyncio.gather(*(generator.aclose() for _, generator in generators))
        return results

    def make_quote(self, request, branches, raw, rate, block, *, retained=None):
        side, mode = request['side'], request['mode']
        exact_in = mode == 'exact-in'
        cygld = self.registry.core
        token_in, token_out = (request['counterToken'], cygld) if side == 'buy' else (cygld, request['counterToken'])
        amount_in, amount_out = int(raw['amountIn']), int(raw['amountOut'])
        request_amount, tolerance = int(request['amount']), request['slippageBps']
        dust = 0
        if side == 'buy':
            if exact_in:
                fee = int(retained['fee']['amount']) if retained else quoted_fee(amount_out, rate)
                net, total, notional = amount_out-fee, request_amount, amount_out
                bound = int(retained['params']['bound']) if retained else floor(net, tolerance)
                limit = bound+fee
                input_maximum, output_minimum = request_amount, bound
            else:
                gross, fee = gross_buy_target(request_amount, rate) if retained is None else (
                    request_amount+int(retained['fee']['amount']), int(retained['fee']['amount']))
                net, total, notional = request_amount, amount_in, gross
                bound = int(retained['params']['bound']) if retained else ceil(total, tolerance)
                limit = gross
                input_maximum, output_minimum = bound, net
        else:
            if exact_in:
                routed, fee, dust = routed_sell_budget(request_amount, rate) if retained is None else (
                    int(retained['params']['routedInput']), int(retained['fee']['amount']),
                    request_amount-int(retained['params']['routedInput'])-int(retained['fee']['amount']))
                net, total, notional = amount_out, request_amount, routed
                bound = int(retained['params']['bound']) if retained else floor(net, tolerance)
                limit = bound
                input_maximum, output_minimum = request_amount, bound
            else:
                fee = int(retained['fee']['amount']) if retained else quoted_fee(amount_in, rate)
                net, total, notional = request_amount, amount_in+fee, amount_in
                bound = int(retained['params']['bound']) if retained else ceil(total, tolerance)
                limit = net
                input_maximum, output_minimum = bound, net
        if retained and exact_in and net < output_minimum:
            raise InvalidPreview('Retained market minimum net output cannot be met.')
        if retained and not exact_in and total > input_maximum:
            raise InvalidPreview('Retained market inclusive input maximum would be exceeded.')
        route = {'version': 1, 'executionContext': 'helpers-market', 'mode': 'exactIn' if exact_in else 'exactOut',
            'tokenIn': token_in, 'tokenOut': token_out, 'branches': deepcopy(branches),
            'inputAmount': str(amount_in), 'outputAmount': str(amount_out), 'limit': str(limit), 'deadline': request['deadline']}
        data = encode_adapter(route)
        params = {'side': 0 if side == 'buy' else 1, 'counterToken': request['counterToken'],
            'amount': request['amount'], 'bound': str(bound), 'routedInput': str(notional) if side == 'sell' and exact_in else '0',
            'feeCygld': str(fee), 'recipient': request['recipient'], 'deadline': request['deadline'],
            'adapter': request['adapter'], 'data': data}
        fee_facts = deepcopy(retained['fee']) if retained else {'asset': cygld, 'ratePpm': rate, 'amount': str(fee),
            'basis': 'quoted', 'notional': str(notional)}
        plan = {'side': side, 'mode': mode, 'amount': request['amount'], 'slippageBps': tolerance,
            'route': route, 'params': params, 'fee': fee_facts}
        quote = {'operation': 'market', 'side': side, 'mode': mode, 'tokenIn': token_in, 'tokenOut': token_out,
            'amountIn': str(amount_in), 'amountOut': str(amount_out), 'totalInput': str(total), 'netOutput': str(net),
            'grossOutput': str(notional if side == 'buy' and not exact_in else amount_out), 'routedAmountIn': str(amount_in), 'fee': fee_facts, 'inputMaximum': str(input_maximum),
            'outputMinimum': str(output_minimum), 'refundDust': str(dust), 'params': params, 'adapterData': data, 'plan': plan,
            'qualification': raw.get('qualification', 'sdk'), 'context': {'chainId': self.registry.chain, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'observedAt': self.now()}}
        if not exact_in:
            quote['outputRefundEstimate'] = str(max(0, amount_out-(notional if side == 'buy' else net)))
        if len(branches) == 1 and amount_in > 0:
            marginal = Fraction(1)
            try:
                for hop in branches[0]['hops']:
                    state = self.registry.observed[hop['pool']['id']]
                    if state['context']['blockHash'] != block['hash']:
                        raise KeyError('No coherent marginal observation')
                    baseline = self.baseline(state, hop['zeroForOne'])
                    marginal *= baseline.exchange*baseline.fee_retention
                impact = max(Fraction(0), 1-Fraction(amount_out, amount_in)/marginal)*1_000_000
                quote['priceImpactPpm'] = str((impact.numerator+impact.denominator-1)//impact.denominator)
            except (KeyError, ValueError, ZeroDivisionError):
                pass
        return quote

    async def qualify_quote(self, request, branches, raw, rate, block, amount, emit, *, retained=None):
        """Economic reference comparison; signed full-call simulation is separate."""
        result = self.make_quote(request, branches, raw, rate, block, retained=retained)
        if raw.get('qualification') != 'sdk':
            return result
        try:
            observed = await self.quote_fallback_branches(branches, raw_mode(request), amount, block)
            if observed['qualification'] in ('quoter', 'sdk-and-quoter'):
                if request['mode'] == 'exact-in' and observed['amountOut'] == raw['amountOut']:
                    observed['amountIn'] = raw['amountIn']
                elif request['mode'] == 'exact-out' and observed['amountIn'] == raw['amountIn'] and int(raw['amountOut']) >= int(observed['amountOut']):
                    # Native V2 backwards quotes expose the target, while SDK
                    # forward replay also exposes integer output overdelivery.
                    observed['amountOut'] = raw['amountOut']
                changed = any(raw[name] != observed[name] for name in ('amountIn', 'amountOut'))
                observed['qualification'] = 'sdk-and-quoter'
                result = self.make_quote(request, branches, observed, rate, block, retained=retained)
                if changed:
                    await emit({'type': 'invalidated'})
        except SdkWorkerError:
            result['executionSimulationRequired'] = True
        except InvalidPreview:
            raise
        except Exception as error:
            if public_quote_error(error)['code'] == 'quote-contract-reverted':
                original_remainder = raw.get('fullyFilled') is False and raw.get('settled') is True and all(
                    row['originalInput'] for row in raw.get('residuals', []))
                if not original_remainder:
                    await emit({'type': 'invalidated'})
                    raise
                result['executionSimulationRequired'] = True
            result['quoteVerificationUnavailable'] = public_quote_error(error)['code']
        return result

    async def get(self, request, on_update=None):
        if self.request_resolver:
            request = await self.request_resolver(request)
        async def ignore(_frame):
            pass
        return await self.sharing.get(request, on_update or ignore)

    async def _get(self, request, on_update=None, *, block=None):
        request = MarketQuoteRequest.model_validate(request).model_dump()
        try:
            for field in ('counterToken', 'adapter', 'recipient'):
                request[field] = Web3.to_checksum_address(request[field])
            Web3().codec.encode(['uint256', 'uint256'], [int(request['amount']), int(request['deadline'])])
        except (ValueError, TypeError, OverflowError) as error:
            raise InvalidPreview('Invalid market quote input.') from error
        async def emit(value):
            if on_update:
                await on_update(value)
        await emit({'type': 'model', 'value': self.packet(request)})
        started = time.perf_counter()
        model_generation = self.generation
        await self.registry.ensure_loaded()
        rpc = self.registry.get_rpc()
        async with asyncio.timeout(45):
            block = block or await rpc.block(None)
            side, exact_in = request['side'], request['mode'] == 'exact-in'
            token_in, token_out = (request['counterToken'], self.registry.core) if side == 'buy' else (
                self.registry.core, request['counterToken'])
            rate = get_market_fee_rate(self.registry.chain, token_in, token_out, request['mode'])
            amount = int(request['amount'])
            quote_amount = routed_sell_budget(amount, rate)[0] if side == 'sell' and exact_in else (
                gross_buy_target(amount, rate)[0] if side == 'buy' and not exact_in else amount)
            mode = 'exactIn' if exact_in else 'exactOut'
            retained = request.get('retainedPlan')
            if retained:
                try:
                    for name in ('side', 'mode', 'amount', 'slippageBps'):
                        if retained.get(name) != request[name]:
                            raise InvalidPreview('Retained market '+name+' changed.')
                    for name in ('counterToken', 'adapter', 'recipient'):
                        if retained['params'][name].lower() != request[name].lower():
                            raise InvalidPreview('Retained market '+name+' changed.')
                    target = int(retained['params']['routedInput']) if side == 'sell' and exact_in else (
                        amount+int(retained['fee']['amount']) if side == 'buy' and not exact_in else amount)
                    branches = self.resolve_branches(retained['route']['branches'], token_in, token_out, mode, target)
                    raw = await self.quote_branches(branches, mode, target, block)
                    result = await self.qualify_quote(request, branches, raw, retained['fee']['ratePpm'], block, target, emit, retained=retained)
                    await rpc.assert_canonical(block)
                    result['metrics'] = {'candidateCalls': 1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
                    await emit({'type': 'qualified', 'value': result})
                    return result
                except InvalidPreview:
                    await emit({'type': 'invalidated'})
            async def baseline_work():
                try:
                    packet = await self.get_model(request, block=block)
                    await emit({'type': 'model', 'value': packet})
                    estimate = self.estimate(packet, request)
                    if estimate is not None:
                        await emit({'type': 'estimate', 'amount': estimate})
                except Exception:
                    pass
            baseline_task = asyncio.create_task(baseline_work())
            try:
                await self.connector_inventory(token_in, token_out, block)
            except BaseException:
                baseline_task.cancel()
                await asyncio.gather(baseline_task, return_exceptions=True)
                raise
            pools = [pool for pool in self.registry.inventory.values() if pool['protocol'] != 'v4' or (
                pool.get('hooks', ZERO).lower() == ZERO and int(pool['feePips']) < 0x800000 and all(
                    token['address'].lower() != ZERO for token in (pool['token0'], pool['token1'])))]
            completed = 0
            best = None
            rpc_error = None
            lock = asyncio.Lock()
            async def evaluate(branches):
                nonlocal best, completed, rpc_error
                try:
                    async with self.semaphore:
                        raw = await self.quote_branches(branches, mode, quote_amount, block)
                        result = self.make_quote(request, branches, raw, rate, block)
                    async with lock:
                        score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                        tie = json.dumps(branches, sort_keys=True)
                        if best is None or (score, tie) > best[0]:
                            # Verify a prospective winner before publishing it;
                            # do not force the App to retain optimistic SDK terms
                            # after native Quoter repricing invalidates them.
                            result = await self.qualify_quote(request, branches, raw, rate, block, quote_amount, emit)
                            score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                            if best is None or (score, tie) > best[0]:
                                best = ((score, tie), result)
                                await emit({'type': 'qualified', 'value': {**result,
                                    'metrics': {'candidateCalls': completed+1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}}})
                except Exception as error:
                    if public_quote_error(error)['code'].startswith('rpc-'):
                        rpc_error = error
                finally:
                    async with lock:
                        completed += 1
                        await emit({'type': 'progress', 'completedCandidates': completed})
            active = set()
            try:
                async for branches in candidate_branches(pools, token_in, token_out, mode, quote_amount):
                    active.add(asyncio.create_task(evaluate(branches)))
                    if len(active) >= 8:
                        done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                        await asyncio.gather(*done)
                await asyncio.gather(*active)
            finally:
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
                if not baseline_task.done():
                    baseline_task.cancel()
                await asyncio.gather(baseline_task, return_exceptions=True)
            if best is None:
                if rpc_error:
                    raise rpc_error
                raise QuoteFailure('quote-no-route')
            await rpc.assert_canonical(block)
            result = best[1]
            result['metrics'] = {'candidateCalls': completed, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
            result['searchCoverage'] = {'scope': 'selected-inventory', 'maxHops': 3,
                'splitPercentages': [25, 50, 75] if exact_in else [],
                'inventoryPools': len(pools), 'catalogMonth': self.registry.discovery_month}
            if self.recipient_cache:
                cached = await self.recipient_cache.load()
                if cached:
                    result['feeBeneficiaryDisplay'] = {name: cached[name] for name in ('address', 'observedAt')}
            family = market_family(request, self.registry.chain, self.registry.core)
            old = self.models.get(family, {'routes': []})
            def signature(route):
                total = sum(int(branch['amountIn']) for branch in route['branches'])
                return [(str(Fraction(int(branch['amountIn']), total)) if total else '1',
                    [(hop['pool']['id'], hop['zeroForOne']) for hop in branch['hops']])
                    for branch in route['branches']]
            same_route = next((row for row in old['routes'] if signature(row['route']) == signature(result['plan']['route'])), None)
            points = same_route['points'] if same_route else []
            points = [row for row in points if row['amountIn'] != result['amountIn']][-31:]+[
                {'amountIn': result['amountIn'], 'amountOut': result['amountOut']}]
            metadata = {name: same_route[name] for name in ('exchangeRate', 'feeRetention', 'localImpact')
                if same_route and name in same_route}
            if model_generation == self.generation:
                self.models[family] = {**self.packet(request), 'context': result['context'], 'routes': [
                    {'route': result['plan']['route'], 'amountIn': result['amountIn'], 'amountOut': result['amountOut'],
                        'points': points, **metadata}]}
            while len(self.models) > 128:
                self.models.popitem(last=False)
            await emit({'type': 'model', 'value': self.packet(request)})
            return result


def raw_mode(request):
    return 'exactIn' if request['mode'] == 'exact-in' else 'exactOut'


def os_environ(name, default):
    import os
    return os.environ.get(name) or default


async def handle_market_quote(request, service, stream=False):
    if not stream:
        return await handle_basket_preview(request, service, REQUEST, 'market-quote',
            'Invalid market quote input.', 'Market quotes are temporarily unavailable.')
    try:
        value = REQUEST.validate_python(await request.json()).model_dump()
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid market quote input.'}, status_code=400,
            headers={'Cache-Control': 'no-store'})
    observation = QuoteObservation(request, value, 'market')
    async def generate():
        queue = asyncio.Queue()
        async def publish(frame):
            await queue.put(observation.event(frame))
        async def run():
            try:
                result = await service.get(value, publish)
                await publish({'type': 'complete', 'value': result})
            except Exception as error:
                await publish(observation.error(error))
            finally:
                await queue.put(None)
        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield json.dumps(event, separators=(',', ':'))+'\n'
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            observation.finish('cancelled')
    return StreamingResponse(generate(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})

"""Market quote coordinator: inventory -> protocol quotes -> fee-neutral plan.

SDK pricing is deliberately distinct from a real wallet's signed
permit-and-swap simulation. Fees are first-party pricing facts, not signatures.
"""
import asyncio
from .route_work_slots import engine_work
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
from .quote_budget import budget_entry, current_budget, SearchStopped
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation
from .uniswap_routes import RoutePlan, market_routes, supported_route, pool_identity, route_identity, resize_branches
from .uniswap_state import ZERO
from .uniswap_v4 import tick_prefetch_scope
from .quote_models import PoolBaseline, LegModel
from .route_quote_engine import RouteQuoteEngine, route_snapshot_scope
from .market_capacity import maximum_filled_input
from .capacity_cache import VerifiedCapacityCache, capacity_key, pool_capacity_facts
from .route_encoding import ADAPTER_TYPE, encode_adapter, encode_route
from .quote_cache import IntentSharing
from .rpc_diagnostics import (quote_work_scope, quote_phase, quote_qualified, start_route_work,
    route_subphase, route_count, route_legs, route_leg_started, route_leg_finished,
    provider_qualification_begin, provider_qualification_scope, provider_qualification_stage,
    provider_qualification_finish, provider_qualification_terms, provider_qualification_selected,
    current_quote_diagnostics)

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

class MarketQuotes(RouteQuoteEngine):
    def __init__(self, settings, registry, sdk=None, *, recipient_cache=None, now=None, request_resolver=None):
        super().__init__(settings, registry, sdk=sdk)
        self.recipient_cache = recipient_cache
        self.request_resolver = request_resolver
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.models = OrderedDict()
        self.fill_capacity = VerifiedCapacityCache()
        self.generation = None
        self.sharing = IntentSharing(SimpleNamespace(settings=settings,
            routes=SimpleNamespace(rpc=registry.get_rpc()), get=self._get), head=self.head)

    async def quote_market_branches(self, branches, mode, amount, block):
        try:
            value = await self.quote_branches(branches, mode, amount, block)
        except InvalidPreview as error:
            if getattr(error, 'sdk_partial_fill', False):
                failure = QuoteFailure('quote-insufficient-liquidity')
                failure.sdk_result = getattr(error, 'sdk_result', None)
                raise failure from error
            raise
        if not value.get('fullyFilled', True):
            failure = QuoteFailure('quote-insufficient-liquidity')
            failure.sdk_result = value
            raise failure
        return value

    async def quote_purchase_budget(self, request, branches, amount, rate, block):
        """Return a smaller fully settled purchase when liquidity limits funding."""
        with route_snapshot_scope() as snapshots:
            try:
                return branches, await self.quote_market_branches(branches, 'exactIn', amount, block)
            except QuoteFailure as error:
                initial = getattr(error, 'sdk_result', None)
                if error.code != 'quote-insufficient-liquidity' or initial is None:
                    raise
            if int(initial['amountOut']) <= quoted_fee(int(initial['amountOut']), rate):
                raise QuoteFailure('quote-insufficient-liquidity')
            total = sum(int(branch['amountIn']) for branch in branches)
            identity = {'adapter': request['adapter'].lower(), 'feeRatePpm': rate,
                'counterToken': request['counterToken'].lower(), 'direction': 'buy',
                'branches': [{'weight': str(Fraction(int(branch['amountIn']), total)),
                    'hops': [(pool_identity(hop['pool']), hop['zeroForOne']) for hop in branch['hops']]}
                    for branch in branches]}
            def key():
                return capacity_key('market-fill', chain=self.registry.chain, block=block, identity=identity,
                    facts={name: pool_capacity_facts(value) for name, value in snapshots.items()})
            cached = self.fill_capacity.get(key()) if snapshots else None
            async def probe(funding):
                allocated = resize_branches(branches, funding)
                try:
                    return await self.quote_market_branches(allocated, 'exactIn', funding, block)
                except QuoteFailure as error:
                    if error.code != 'quote-insufficient-liquidity':
                        raise
                    return None
            funding, raw = await maximum_filled_input(amount, initial, probe,
                cached=int(cached['maximumInput']) if cached else None)
            if not funding or raw is None or int(raw['amountOut']) <= quoted_fee(int(raw['amountOut']), rate):
                raise QuoteFailure('quote-insufficient-liquidity')
            if snapshots:
                self.fill_capacity.remember(key(), {'maximumInput': str(funding)})
            return resize_branches(branches, funding), raw

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
            self.fill_capacity.clear()
            await self.registry.observe_generation(generation)
            if self.recipient_cache:
                self.recipient_cache.reset()

    def resolve_market_branches(self, branches, token_in, token_out, mode, amount):
        result = super().resolve_branches(branches, token_in, token_out, mode, amount)
        sale = token_in.lower() == self.registry.core.lower()
        anchor = pool_identity(self.registry.seed)
        for branch in result:
            hop = branch['hops'][0 if sale else -1]
            if pool_identity(hop['pool']) != anchor:
                raise InvalidPreview('Retained Market route does not use the canonical CYGLD pool.')
        return result

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
        mode = 'exactIn' if request['mode'] == 'exact-in' else 'exactOut'
        async for hops in market_routes(list(self.registry.inventory.values()), token_in, token_out,
                                        self.registry.core, self.registry.seed):
            if not supported_route(hops, mode):
                continue
            try:
                def fraction(value):
                    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}
                route = {'version': 1, 'executionContext': 'helpers-market',
                    'mode': mode,
                    'tokenIn': token_in, 'tokenOut': token_out,
                    'branches': [{'amountIn': '0', 'hops': deepcopy(hops)}],
                    'inputAmount': '0', 'outputAmount': '0', 'limit': '0', 'deadline': '0'}
                baseline = await self.route_baseline(route, block)
                key = route_identity(route['branches'])
                old = next((row for row in packet['routes'] if route_identity([
                    {**branch, 'amountIn': '0'} for branch in row['route']['branches']]) == key), None)
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
                net, total, notional = amount_out-fee, amount_in, amount_out
                bound = int(retained['params']['bound']) if retained else floor(net, tolerance)
                limit = bound+fee
                input_maximum, output_minimum = amount_in, bound
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
            provider_qualification_stage('tolerance', targetAmount=str(request_amount),
                minimumAmountOut=str(output_minimum), observedAmountOut=str(net))
            raise InvalidPreview('Retained market minimum net output cannot be met.')
        if retained and not exact_in and total > input_maximum:
            provider_qualification_stage('tolerance', targetAmount=str(request_amount),
                maximumAmountIn=str(input_maximum), observedAmountIn=str(total))
            raise InvalidPreview('Retained market inclusive input maximum would be exceeded.')
        route = {'version': 1, 'executionContext': 'helpers-market', 'mode': 'exactIn' if exact_in else 'exactOut',
            'tokenIn': token_in, 'tokenOut': token_out, 'branches': deepcopy(branches),
            'inputAmount': str(amount_in), 'outputAmount': str(amount_out), 'limit': str(limit), 'deadline': request['deadline']}
        data = encode_route(route, request['adapter'])
        params = {'side': 0 if side == 'buy' else 1, 'counterToken': request['counterToken'],
            'amount': str(amount_in) if side == 'buy' and exact_in else request['amount'],
            'bound': str(bound), 'routedInput': str(notional) if side == 'sell' and exact_in else '0',
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
        """Apply fee and retained execution bounds to the SDK-priced route.

        The shared engine proves settlement and exact-output fill. A real
        wallet's signed full-call simulation remains a separate operation.
        """
        return self.make_quote(request, branches, raw, rate, block, retained=retained)

    @budget_entry
    async def get(self, request, on_update=None):
        universal = getattr(self, 'universal_quotes', None)
        if universal and universal.adapter and request.get('mode') == 'exact-in' and not request.get('retainedPlan'):
            return await universal.scalar_request(request, on_update)
        budget = current_budget()
        if self.request_resolver:
            request = await budget.prepare(self.request_resolver(request))
        async def ignore(_frame):
            pass
        return await self.sharing.get(request, on_update or ignore)

    @quote_work_scope
    @tick_prefetch_scope()
    async def _get(self, request, on_update=None, *, block=None):
        budget = current_budget()
        request = MarketQuoteRequest.model_validate(request).model_dump()
        try:
            for field in ('counterToken', 'adapter', 'recipient'):
                request[field] = Web3.to_checksum_address(request[field])
            Web3().codec.encode(['uint256', 'uint256'], [int(request['amount']), int(request['deadline'])])
        except (ValueError, TypeError, OverflowError) as error:
            raise InvalidPreview('Invalid market quote input.') from error
        async def emit(value):
            if value.get('type') == 'qualified' and isinstance(value.get('value'), dict):
                diagnostics = current_quote_diagnostics()
                if diagnostics:
                    value = {**value, 'value': {**value['value'], 'quoteDiagnostics': diagnostics}}
            if on_update:
                await on_update(value)
        def terms(result, branches):
            try:
                provider_qualification_terms(quotedInput=result['totalInput'], quotedOutput=result['netOutput'],
                    inputMaximum=result['inputMaximum'], outputMinimum=result['outputMinimum'], branches=branches)
            except Exception:
                pass  # Optional evidence cannot change quote qualification.
        await emit({'type': 'model', 'value': self.packet(request)})
        started = time.perf_counter()
        model_generation = self.generation
        await budget.prepare(self.registry.ensure_loaded()) if budget is not None else await self.registry.ensure_loaded()
        rpc = self.registry.get_rpc()
        async with asyncio.timeout(45):
            block = block or (await budget.prepare(rpc.block(None)) if budget is not None else await rpc.block(None))
            side, exact_in = request['side'], request['mode'] == 'exact-in'
            token_in, token_out = (request['counterToken'], self.registry.core) if side == 'buy' else (
                self.registry.core, request['counterToken'])
            rate = get_market_fee_rate(self.registry.chain, token_in, token_out, request['mode'])
            amount = int(request['amount'])
            quote_amount = routed_sell_budget(amount, rate)[0] if side == 'sell' and exact_in else (
                gross_buy_target(amount, rate)[0] if side == 'buy' and not exact_in else amount)
            mode = 'exactIn' if exact_in else 'exactOut'
            quote_phase('execution-search')
            start_route_work(request['mode'])
            route_subphase('structured-search')
            diagnostic_legs = route_legs([{'inputAsset': token_in, 'outputAsset': token_out,
                                            'amount': str(quote_amount)}])
            diagnostic_leg = diagnostic_legs[0] if diagnostic_legs else None
            diagnostic_best = None
            retained = request.get('retainedPlan')
            if retained:
                async def retained_quote():
                    nonlocal diagnostic_best, quote_amount
                    probe = provider_qualification_begin('retained-validation', provider='market')
                    priced, pricing_started = False, False
                    with provider_qualification_scope(probe):
                        try:
                            for name in ('side', 'mode', 'amount', 'slippageBps'):
                                if retained.get(name) != request[name]:
                                    raise InvalidPreview('Retained market '+name+' changed.')
                            for name in ('counterToken', 'adapter', 'recipient'):
                                if retained['params'][name].lower() != request[name].lower():
                                    raise InvalidPreview('Retained market '+name+' changed.')
                            target = int(retained['params']['routedInput']) if side == 'sell' and exact_in else (
                                amount+int(retained['fee']['amount']) if side == 'buy' and not exact_in else (
                                    int(retained['params']['amount']) if side == 'buy' and exact_in else amount))
                            if side == 'buy' and exact_in:
                                if target > amount:
                                    raise InvalidPreview('Retained market funding exceeds the input budget.')
                                quote_amount = target
                            branches = self.resolve_market_branches(retained['route']['branches'], token_in, token_out, mode, target)
                            provider_qualification_stage('route-pricing')
                            route_count('typedEnumerated')
                            route_leg_started(diagnostic_leg, amount=str(target))
                            pricing_started = True
                            async with engine_work(self.semaphore):
                                try:
                                    raw = await self.quote_market_branches(branches, mode, target, block)
                                except QuoteFailure as error:
                                    if side == 'buy' and exact_in and error.code == 'quote-insufficient-liquidity':
                                        raise InvalidPreview('Retained market funding is no longer fully fillable.') from error
                                    raise
                            route_leg_finished(diagnostic_leg, 'succeeded', best={'routePlan': {'branches': branches}})
                            priced = True
                            diagnostic_best = int(raw['amountOut' if exact_in else 'amountIn'])
                            provider_qualification_stage('qualification')
                            result = await self.qualify_quote(request, branches, raw, retained['fee']['ratePpm'], block, target, emit, retained=retained)
                            terms(result, branches)
                            provider_qualification_stage('canonicality')
                            await rpc.assert_canonical(block)
                            if budget is not None:
                                budget.canonical_done()
                                budget.cleanup_done()
                            provider_qualification_stage('selection')
                            if budget is not None and not budget.qualified():
                                provider_qualification_finish(probe, 'cancelled')
                                raise SearchStopped()
                            result['metrics'] = {'candidateCalls': 1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
                            quote_qualified(True)
                            provider_qualification_selected(probe)
                            provider_qualification_finish(probe, 'qualified')
                            await emit({'type': 'qualified', 'value': result})
                            if diagnostics := current_quote_diagnostics():
                                result['quoteDiagnostics'] = diagnostics
                            return result
                        except asyncio.CancelledError:
                            if pricing_started and not priced:
                                route_leg_finished(diagnostic_leg, 'cancelled')
                            provider_qualification_finish(probe, 'cancelled')
                            raise
                        except Exception as error:
                            if pricing_started and not priced:
                                route_leg_finished(diagnostic_leg, 'failed', code=public_quote_error(error)['code'])
                            provider_qualification_finish(probe, 'rejected', error)
                            raise
                        finally:
                            if pricing_started:
                                route_count('typedCompleted')
                try:
                    return await budget.discovery(retained_quote()) if budget is not None else await retained_quote()
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
            completed = 0
            best = None
            rpc_error, liquidity_error, context_error = None, None, None
            pools = []
            lock = asyncio.Lock()
            async def evaluate(branches):
                nonlocal best, completed, rpc_error, liquidity_error, context_error, diagnostic_best
                probe = provider_qualification_begin('route-pricing', provider='market')
                route_leg_started(diagnostic_leg, amount=str(quote_amount))
                priced = False
                with provider_qualification_scope(probe):
                    try:
                        async with engine_work(self.semaphore):
                            if side == 'buy' and exact_in:
                                branches, raw = await self.quote_purchase_budget(request, branches, quote_amount, rate, block)
                            else:
                                raw = await self.quote_market_branches(branches, mode, quote_amount, block)
                            observed = int(raw['amountOut' if exact_in else 'amountIn'])
                            improves_pricing = diagnostic_best is None or (
                                observed > diagnostic_best if exact_in else observed < diagnostic_best)
                            if improves_pricing:
                                diagnostic_best = observed
                            route_leg_finished(diagnostic_leg, 'succeeded',
                                best={'routePlan': {'branches': branches}} if improves_pricing else None)
                            priced = True
                            provider_qualification_stage('fee-bounds')
                            result = self.make_quote(request, branches, raw, rate, block)
                            terms(result, branches)
                        async with lock:
                            score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                            tie = json.dumps(branches, sort_keys=True)
                            if best is None or (score, tie) > best[0]:
                                # The SDK result supplies the economic terms;
                                # canonical context validation still precedes readiness.
                                provider_qualification_stage('qualification')
                                result = await self.qualify_quote(request, branches, raw, rate, block, quote_amount, emit)
                                terms(result, branches)
                                score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                                if best is None or (score, tie) > best[0]:
                                    if budget is not None:
                                        provider_qualification_stage('canonicality')
                                        await rpc.assert_canonical(block)
                                        provider_qualification_stage('selection')
                                        if not budget.qualified():
                                            provider_qualification_finish(probe, 'cancelled')
                                            return
                                    best = ((score, tie), result)
                                    quote_qualified(True)
                                    provider_qualification_selected(probe)
                                    provider_qualification_finish(probe, 'qualified')
                                    await emit({'type': 'qualified', 'value': {**result,
                                        'metrics': {'candidateCalls': completed+1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}}})
                            provider_qualification_finish(probe, 'not-improved')
                    except asyncio.CancelledError:
                        if not priced:
                            route_leg_finished(diagnostic_leg, 'cancelled')
                        provider_qualification_finish(probe, 'cancelled')
                        raise
                    except SnapshotChanged as error:
                        if not priced:
                            route_leg_finished(diagnostic_leg, 'failed', code=public_quote_error(error)['code'])
                        provider_qualification_finish(probe, 'rejected', error)
                        quote_qualified(False)
                        context_error, best = error, None
                        if budget is not None:
                            budget.invalidated()
                        raise
                    except Exception as error:
                        code = public_quote_error(error)['code']
                        if not priced:
                            route_leg_finished(diagnostic_leg, 'failed', code=code)
                        provider_qualification_finish(probe, 'rejected', error)
                        if code.startswith('rpc-'):
                            rpc_error = error
                        elif code == 'quote-insufficient-liquidity':
                            liquidity_error = error
                    finally:
                        route_count('typedCompleted')
                        async with lock:
                            completed += 1
                            await emit({'type': 'progress', 'completedCandidates': completed})
            async def search():
                nonlocal pools
                async def price(_index, branches):
                    await evaluate(branches)
                await self.search_candidates({**request, 'executionContext': 'helpers-market',
                    'targets': [{'inputAsset': token_in, 'outputAsset': token_out,
                        'amount': str(quote_amount)}]}, block, price)
                pools = list(self.registry.inventory.values())
            baseline_task = asyncio.create_task(baseline_work())
            try:
                try:
                    await budget.discovery(search()) if budget is not None else await search()
                except SearchStopped:
                    if context_error is not None:
                        raise context_error
                    if best is None:
                        raise
                except Exception as error:
                    if isinstance(error, SnapshotChanged) or context_error is not None or best is None:
                        raise
                    # An ordinary unfinished search cannot discard a checked
                    # incumbent. Its terminal canonical validation still follows.
            finally:
                if not baseline_task.done():
                    baseline_task.cancel()
                await asyncio.gather(baseline_task, return_exceptions=True)
                if budget is not None:
                    budget.cleanup_done()
            if context_error is not None:
                raise context_error
            if best is None:
                if rpc_error:
                    raise rpc_error
                if liquidity_error:
                    raise liquidity_error
                raise QuoteFailure('quote-no-route')
            final_validation = provider_qualification_begin('canonicality', provider='market')
            with provider_qualification_scope(final_validation):
                try:
                    await rpc.assert_canonical(block)
                    provider_qualification_finish(final_validation, 'qualified')
                except asyncio.CancelledError:
                    provider_qualification_finish(final_validation, 'cancelled')
                    raise
                except Exception as error:
                    provider_qualification_finish(final_validation, 'rejected', error)
                    if isinstance(error, SnapshotChanged):
                        quote_qualified(False)
                    raise
            if budget is not None:
                budget.canonical_done()
            result = best[1]
            result['metrics'] = {'candidateCalls': completed, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
            result['searchCoverage'] = {'scope': 'selected-inventory', 'maxHops': 3,
                'splitPercentages': [25, 50, 75] if exact_in else [],
                'inventoryPools': len(pools), 'catalogMonth': self.registry.discovery_month,
                'canonicalPoolId': self.registry.seed['id'],
                'canonicalPosition': 'first' if side == 'sell' else 'last',
                'protocolCoverage': 'mixed-exact-input' if exact_in else 'homogeneous-exact-output'}
            if self.recipient_cache:
                try:
                    cached = await budget.discovery(self.recipient_cache.load()) if budget is not None else await self.recipient_cache.load()
                except SearchStopped:
                    cached = None
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
            quote_qualified(True)
            if diagnostics := current_quote_diagnostics():
                result['quoteDiagnostics'] = diagnostics
            return result


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

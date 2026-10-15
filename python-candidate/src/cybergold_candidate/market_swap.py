"""Market quote coordinator: inventory -> protocol quotes -> fee-neutral plan.

SDK pricing is deliberately distinct from a real wallet's signed
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
from .quote_budget import budget_entry, current_budget, SearchStopped
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation
from .uniswap_routes import RoutePlan
from .uniswap_state import ZERO
from .quote_models import PoolBaseline, LegModel
from .route_quote_engine import RouteQuoteEngine
from .route_encoding import ADAPTER_TYPE, encode_adapter, encode_route
from .quote_cache import IntentSharing

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
        self.generation = None
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
        data = encode_route(route, request['adapter'])
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
        """Apply fee and retained execution bounds to the SDK-priced route.

        The shared engine proves settlement and exact-output fill. A real
        wallet's signed full-call simulation remains a separate operation.
        """
        return self.make_quote(request, branches, raw, rate, block, retained=retained)

    @budget_entry
    async def get(self, request, on_update=None):
        budget = current_budget()
        if self.request_resolver:
            request = await budget.prepare(self.request_resolver(request))
        async def ignore(_frame):
            pass
        return await self.sharing.get(request, on_update or ignore)

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
            if on_update:
                await on_update(value)
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
            retained = request.get('retainedPlan')
            if retained:
                async def retained_quote():
                    for name in ('side', 'mode', 'amount', 'slippageBps'):
                        if retained.get(name) != request[name]:
                            raise InvalidPreview('Retained market '+name+' changed.')
                    for name in ('counterToken', 'adapter', 'recipient'):
                        if retained['params'][name].lower() != request[name].lower():
                            raise InvalidPreview('Retained market '+name+' changed.')
                    target = int(retained['params']['routedInput']) if side == 'sell' and exact_in else (
                        amount+int(retained['fee']['amount']) if side == 'buy' and not exact_in else amount)
                    branches = self.resolve_branches(retained['route']['branches'], token_in, token_out, mode, target)
                    async with self.semaphore:
                        raw = await self.quote_branches(branches, mode, target, block)
                    result = await self.qualify_quote(request, branches, raw, retained['fee']['ratePpm'], block, target, emit, retained=retained)
                    await rpc.assert_canonical(block)
                    if budget is not None:
                        budget.canonical_done()
                        budget.cleanup_done()
                    if budget is not None and not budget.qualified():
                        raise SearchStopped()
                    result['metrics'] = {'candidateCalls': 1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
                    await emit({'type': 'qualified', 'value': result})
                    return result
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
            rpc_error, context_error = None, None
            pools = []
            lock = asyncio.Lock()
            async def evaluate(branches):
                nonlocal best, completed, rpc_error, context_error
                try:
                    async with self.semaphore:
                        raw = await self.quote_branches(branches, mode, quote_amount, block)
                        result = self.make_quote(request, branches, raw, rate, block)
                    async with lock:
                        score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                        tie = json.dumps(branches, sort_keys=True)
                        if best is None or (score, tie) > best[0]:
                            # The SDK result supplies the economic terms;
                            # canonical context validation still precedes readiness.
                            result = await self.qualify_quote(request, branches, raw, rate, block, quote_amount, emit)
                            score = int(result['netOutput']) if exact_in else -int(result['totalInput'])
                            if best is None or (score, tie) > best[0]:
                                if budget is not None:
                                    await rpc.assert_canonical(block)
                                    if not budget.qualified():
                                        return
                                best = ((score, tie), result)
                                await emit({'type': 'qualified', 'value': {**result,
                                    'metrics': {'candidateCalls': completed+1, 'totalMs': round((time.perf_counter()-started)*1000, 3)}}})
                except SnapshotChanged as error:
                    context_error, best = error, None
                    if budget is not None:
                        budget.invalidated()
                    raise
                except Exception as error:
                    if public_quote_error(error)['code'].startswith('rpc-'):
                        rpc_error = error
                finally:
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
                raise QuoteFailure('quote-no-route')
            await rpc.assert_canonical(block)
            if budget is not None:
                budget.canonical_done()
            result = best[1]
            result['metrics'] = {'candidateCalls': completed, 'totalMs': round((time.perf_counter()-started)*1000, 3)}
            result['searchCoverage'] = {'scope': 'selected-inventory', 'maxHops': 3,
                'splitPercentages': [25, 50, 75] if exact_in else [],
                'inventoryPools': len(pools), 'catalogMonth': self.registry.discovery_month}
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

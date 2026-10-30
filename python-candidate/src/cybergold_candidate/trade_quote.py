"""Compare complete Core and market executions, preserving each selected plan.

Models are indicative. Only the existing providers qualify economic execution
terms; wallet authorization and signed full-call simulation remain separate.
"""
import asyncio
from copy import deepcopy
import json
import time
from types import SimpleNamespace
from typing import Literal

from fastapi.responses import JSONResponse, StreamingResponse
from eth_abi.exceptions import EncodingError
from pydantic import BaseModel, Field
from web3 import Web3

from .basket_preview import InvalidPreview
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS
from .pool_producer import ZERO
from .protocol_facts import ABI
from .quote_cache import IntentSharing
from .quote_errors import QuoteFailure, public_quote_error
from .rpc_diagnostics import bind_quote_error, quote_failure_context
from .fast_trade_estimates import FastTradeEstimates, model_estimate
from .recovery_rpc import SnapshotChanged
from .route_search import WETH
from .wallet_balances import TOKENS
from .uniswap_routes import uses_typed_adapter
from .shared_reads import discard_pool_observation
from .trade_observation import QuoteObservation
from .quote_budget import budget_entry, current_budget, SearchStopped

PAXG = next(address for name, address in TOKENS if name == 'paxg')


class TradeModelRequest(BaseModel):
    side: Literal['buy', 'sell']
    mode: Literal['exact-in', 'exact-out']
    counterToken: str
    native: bool = False
    amount: str
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)


class RetainedPlan(BaseModel):
    strategy: Literal['core', 'market']
    request: dict
    quote: dict


class TradeQuoteRequest(TradeModelRequest):
    recipient: str
    deadline: str
    retainedPlan: RetainedPlan | None = None


def validate(request, *, model=False):
    try:
        request['counterToken'] = Web3.to_checksum_address(request['counterToken'])
        if request['native']:
            request['counterToken'] = Web3.to_checksum_address(WETH)
        if not model:
            request['recipient'] = Web3.to_checksum_address(request['recipient'])
        Web3().codec.encode(['uint256'] if model else ['uint256', 'uint256'],
            [int(request['amount'])] if model else [int(request['amount']), int(request['deadline'])])
    except (ValueError, TypeError, OverflowError, EncodingError) as error:
        raise InvalidPreview('Invalid trade quote input.') from error
    return request


def split_amount(amount, weights):
    total = sum(weights)
    if not total:
        raise InvalidPreview('Core basket has no positive target weight.')
    allocated = 0
    values = []
    for index, weight in enumerate(weights):
        value = amount-allocated if index == len(weights)-1 else amount*weight//total
        values.append(value)
        allocated += value
    return values


def core_request(request, assets, weights):
    """Retain the App's existing weighted seed, direct leg and integer remainder."""
    counter, amount = request['counterToken'], int(request['amount'])
    buy, exact_in = request['side'] == 'buy', request['mode'] == 'exact-in'
    targets = []
    if (buy and exact_in) or (not buy and not exact_in):
        index = next((i for i, asset in enumerate(assets) if asset.lower() == counter.lower()), None)
        if index is None:
            indices = [i for i, weight in enumerate(weights) if weight > 0] if buy else list(range(len(assets)))
            values = split_amount(amount, [weights[i] for i in indices])
        else:
            total = sum(weights)
            if not total:
                raise InvalidPreview('Core basket has no positive target weight.')
            direct = amount*weights[index]//total
            indices = [i for i, weight in enumerate(weights) if i != index and (weight > 0 or not buy)]
            values = split_amount(amount-direct, [weights[i] for i in indices]) if sum(weights[i] for i in indices) else [0]*len(indices)
            if not buy:
                targets.append({'inputAsset': assets[index], 'outputAsset': counter, 'amount': str(direct)})
        targets.extend({'inputAsset': counter if buy else assets[i],
                        'outputAsset': assets[i] if buy else counter, 'amount': str(value)}
                       for i, value in zip(indices, values, strict=True) if value > 0)
        targets = [row for row in targets if int(row['amount']) > 0]
    result = {'mode': ('issue-' if buy else 'redeem-')+request['mode'],
        'token': ZERO if request['native'] else counter, 'quoteToken': counter,
        'native': request['native'], 'amount': request['amount'], 'adapter': request['adapter'],
        'deadline': request['deadline'], 'slippageBps': request['slippageBps'],
        'orderedAssets': list(assets), 'targets': targets}
    retained = request.get('retainedPlan')
    if retained and retained['strategy'] == 'core':
        old, quote = retained['request'], retained['quote']
        for name in ('mode', 'token', 'quoteToken', 'native', 'amount', 'slippageBps'):
            if old.get(name, DEFAULT_SLIPPAGE_BPS if name == 'slippageBps' else None) != result[name]:
                raise InvalidPreview('Retained Core '+name+' changed.')
        result['retainedPlan'] = {'slippageBps': quote.get('slippageBps', DEFAULT_SLIPPAGE_BPS),
            'executionAmount': quote['executionAmount'], 'maximumInputAmount': quote['maximumInputAmount'],
            'minimumAmountOut': quote['preview'].get('minimumAmountOut', '0'),
            'quotes': deepcopy(quote['quotes']), 'expectedCoreOutputs': deepcopy(quote.get('expectedCoreOutputs', [])),
            **({'expectedInputAmount': quote['expectedInputAmount']} if quote.get('expectedInputAmount') is not None else {})}
    return result


def market_request(request):
    result = {name: request[name] for name in ('side', 'mode', 'counterToken', 'amount', 'recipient', 'deadline', 'slippageBps', 'adapter')}
    retained = request.get('retainedPlan')
    if retained and retained['strategy'] == 'market':
        result['retainedPlan'] = deepcopy(retained['quote']['plan'])
    return result


def economics(strategy, request, quote):
    """Requested-token amounts after fees; caps/minima never masquerade as price."""
    if strategy == 'market':
        return {name: quote[source] for name, source in (
            ('quotedInput', 'totalInput'), ('quotedOutput', 'netOutput'),
            ('inputMaximum', 'inputMaximum'), ('outputMinimum', 'outputMinimum'))}
    buy, exact_in = request['side'] == 'buy', request['mode'] == 'exact-in'
    if buy:
        return {'quotedInput': quote.get('expectedInputAmount', quote['maximumInputAmount']),
            'quotedOutput': quote['executionAmount'], 'inputMaximum': quote['maximumInputAmount'],
            'outputMinimum': quote['executionAmount']}
    return {'quotedInput': quote['executionAmount'],
        'quotedOutput': quote.get('expectedOutputAmount', quote['displayAmount'] if exact_in else quote['preview']['minimumAmountOut']),
        'inputMaximum': quote['executionAmount'], 'outputMinimum': quote['preview']['minimumAmountOut']}


def score(request, value):
    return int(value['quotedOutput']) if request['mode'] == 'exact-in' else -int(value['quotedInput'])


class TradeQuotes:
    def __init__(self, settings, core, market, *, request_resolver=None, basis_reader=None):
        self.settings, self.core, self.market = settings, core, market
        self.request_resolver, self.basis_reader = request_resolver, basis_reader
        self.history = getattr(core, 'history', None)
        self.basis, self.basis_epoch = None, None
        self.fast_estimates = FastTradeEstimates()
        self.sharing = IntentSharing(SimpleNamespace(settings=settings, routes=core.routes, get=self._get),
            rpc_factory=core.routes.rpc_factory, head=market.head)

    async def close(self):
        await self.sharing.close()

    async def resolve(self, request):
        retained = request.get('retainedPlan')
        # A chosen complete plan keeps its concrete adapter through revalidation.
        if retained:
            request['adapter'] = retained['request'].get('adapter')
        return await self.request_resolver(request) if self.request_resolver else request

    def supported_market(self, request):
        # The historical V3 deployment does not decode the market compiler's
        # typed payload. Core keeps its existing legacy encoder in that case.
        # The Market facet funds and settles ERC20s. Native ETH needs a new
        # wrapping/unwrap execution endpoint, so it remains explicitly absent.
        # Eligible ERC20 connectors use canonical Market anchoring in the shared
        # route engine; mixed exact-output is still excluded by its ABI rule.
        return not request['native'] and uses_typed_adapter(request.get('adapter'))

    def cached_basis(self):
        if self.history and self.basis_epoch != self.history.epoch:
            self.basis = None
        if self.basis:
            return self.basis
        model = self.history.protocol_model() if self.history else None
        if model:
            return model['state']['assets'], list(map(int, model['state']['weights']))
        if self.history and self.history.facts:
            row = next(reversed(self.history.facts.values()))['basket']
            return row['assets']['value'], list(map(int, row['targetsPpm']['value']))
        return None

    async def read_basis(self, block):
        if self.basis_reader:
            return await self.basis_reader(block)
        rpc = self.core.routes.rpc
        names = ('basketAssets', 'basketTargetsPpm')
        abi = [row for row in ABI['core'] if row['name'] in names]
        contract = rpc.w3.eth.contract(abi=abi)
        address = Web3.to_checksum_address(self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
        counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
        calls = [(address, contract.encode_abi(name, args=[])) for name in names]
        rows, _ = await rpc.pool_batch(calls, block, counts)
        values = []
        for call, name, row in zip(calls, names, rows, strict=True):
            if 'error' in row:
                from .quote_errors import rpc_failure
                raise rpc_failure(row['error'])
            output = next(entry for entry in abi if entry['name'] == name)['outputs'][0]['type']
            try:
                values.append(rpc.w3.codec.decode([output], bytes.fromhex(row['result'][2:]))[0])
            except Exception:
                discard_pool_observation(rpc, call, block)
                raise
        return list(values[0]), list(map(int, values[1])), counts['issued']

    def estimate_scope(self):
        return (self.settings.NEXT_PUBLIC_CHAIN_ID,
                self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS.lower(),
                self.settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS.lower(),
                self.history.epoch if self.history else None,
                getattr(self.market, 'generation', None))

    def packet(self, request, provider_models=None):
        intent = {name: deepcopy(request[name]) for name in TradeModelRequest.model_fields}
        packet = {'namespace': 'trade', 'intent': intent, 'models': []}
        estimates = []
        basis = self.cached_basis()
        if self.history and basis:
            adapted = core_request({**request, 'deadline': request.get('deadline', '0')}, *basis)
            value = self.history.packet(adapted)
            packet['models'].append({'strategy': 'core', 'value': value})
            amount = model_estimate(value, request)
            if amount is not None:
                estimates.append(('core', amount))
        if self.supported_market(request):
            adapted = market_request({**request, 'recipient': request.get('recipient', ZERO), 'deadline': request.get('deadline', '0')})
            value = (provider_models or {}).get('market') or self.market.packet(adapted)
            packet['models'].append({'strategy': 'market', 'value': value})
            amount = self.market.estimate(value, adapted)
            if amount is not None:
                estimates.append(('market', amount))
        packet.update(self.fast_estimates.packet(request, estimates, scope=self.estimate_scope()))
        return packet

    async def acquire_models(self, request, block):
        models = {}
        async def core_model():
            if not self.history or (request.get('retainedPlan') or {}).get('strategy') == 'market':
                return
            context = {'chainId': int(self.settings.NEXT_PUBLIC_CHAIN_ID), 'blockNumber': str(block['number']),
                       'blockHash': block['hash'], 'observedAt': self.core.now()}
            self.history.ensure_state(self.core.routes.rpc, block, context)
            task = self.history.tasks.get(('state', block['hash'].lower()))
            if task:
                await asyncio.shield(task)
        async def market_model():
            if self.supported_market(request) and (request.get('retainedPlan') or {}).get('strategy') != 'core':
                adapted = market_request({**request, 'recipient': request.get('recipient', ZERO), 'deadline': request.get('deadline', '0')})
                models['market'] = await self.market.get_model(adapted, block=block)
        await asyncio.gather(core_model(), market_model(), return_exceptions=True)
        return self.packet(request, models)

    async def get_model(self, request):
        request = validate(TradeModelRequest.model_validate(request).model_dump(), model=True)
        cached_estimates = getattr(self, 'cached_estimates', None)
        if request['mode'] == 'exact-in' and cached_estimates is not None:
            return await cached_estimates.get_model(request)
        request = await self.resolve(request)
        registry = getattr(self.market, 'registry', None)
        if registry is not None:
            await registry.ensure_loaded(wait=True)
        packet = self.packet(request)
        if packet.get('budgetRange') and packet.get('estimate'):
            return packet
        if all(row['value'].get('routes') or (row['strategy'] == 'core' and row['value'].get('protocol')) for row in packet['models']) and packet['models']:
            return packet
        # Cold model acquisition reuses the providers' lightweight baselines;
        # warm display is RPC-free and exact search never waits for this work.
        if self.core.routes.rpc is None:
            self.core.routes.rpc = self.core.routes.rpc_factory(self.settings)
        block = await self.market.head()
        return await self.acquire_models(request, block)

    @budget_entry
    async def get(self, request, on_update):
        universal = getattr(self, 'universal_quotes', None)
        if universal and universal.adapter and request.get('mode') == 'exact-in' and not request.get('retainedPlan'):
            return await universal.scalar_request(request, on_update)
        budget = current_budget()
        request = await budget.prepare(self.resolve(validate(TradeQuoteRequest.model_validate(request).model_dump())))
        await budget.prepare(on_update({'type': 'model', 'value': self.packet(request)}))
        bridge = universal and universal.adapter and request['side'] == 'sell' and request['mode'] == 'exact-out' and not request.get('retainedPlan')
        async def publish(frame):
            if bridge:
                candidate = frame.get('value', {})
                if frame['type'] in ('qualified', 'provider-qualified') and candidate.get('strategy') == 'core':
                    return
                frame = deepcopy(frame)
                frame.get('value', {}).get('providerCandidates', {}).pop('core', None)
                frame.get('providerCandidates', {}).pop('core', None)
            await on_update(frame)
        result = await self.sharing.get(request, publish)
        if bridge:
            if result['strategy'] == 'core':
                return await universal.core_sale_from_legacy(request, result, on_update)
            result = deepcopy(result)
            result.get('providerCandidates', {}).pop('core', None)
        return result

    async def _get(self, request, on_update, *, block):
        started, target_reads = time.perf_counter(), 0
        budget = current_budget()
        retained = request.get('retainedPlan')
        strategies = [retained['strategy']] if retained else ['core', 'market']
        evaluation = {name: 'running' if name in strategies and (name == 'core' or self.supported_market(request)) else 'unsupported'
                      for name in ('core', 'market')}
        candidates, terminal_candidates, winner, errors, context_error = {}, {}, None, {}, None
        error_quote_diagnostics = {}
        search_outcomes = {name: 'running' if evaluation[name] == 'running' else 'not-run'
                           for name in ('core', 'market')}
        provider_errors = {}
        lock = asyncio.Lock()

        def candidate_value(value):
            return {**deepcopy(value), 'evaluation': deepcopy(evaluation),
                    'metrics': {'totalMs': round((time.perf_counter()-started)*1000, 3), 'targetReads': target_reads}}

        def assessments(pool):
            result = {}
            for name in ('core', 'market'):
                availability = ('not-run' if name not in strategies else
                                'unsupported' if evaluation[name] == 'unsupported' else
                                'unavailable' if context_error is not None else
                                'qualified' if name in pool else
                                'pending' if search_outcomes[name] == 'running' else 'unavailable')
                result[name] = {'availability': availability, 'searchOutcome': search_outcomes[name],
                                **deepcopy(provider_errors.get(name, {}))}
                diagnostic = pool.get(name, {}).get('providerQuote', {}).get('quoteDiagnostics')
                if availability == 'qualified' and isinstance(diagnostic, dict):
                    result[name].setdefault('quoteDiagnostics', deepcopy(diagnostic))
            return result

        def decorate(value, pool=None):
            pool = candidates if pool is None else pool
            return {**candidate_value(value), 'providerAssessments': assessments(pool),
                    'providerCandidates': {name: candidate_value(row) for name, row in pool.items()}}

        async def evidence(frame):
            try:
                await on_update(frame)
            except Exception:
                # Additive observations never change ordinary selection/errors.
                pass

        async def assessment(name, pool=None):
            await evidence({'type': 'provider-assessment', 'strategy': name,
                            'value': assessments(candidates if pool is None else pool)[name]})

        async def select():
            nonlocal winner
            selected = max(candidates.values(), key=lambda row: (score(request, row), row['strategy'] == 'core')) if candidates else None
            if selected is not None and selected != winner:
                winner = deepcopy(selected)
                self.fast_estimates.remember_selected(request, winner, scope=self.estimate_scope())
                await on_update({'type': 'qualified', 'value': decorate(winner)})
                await evidence({'type': 'model', 'value': self.packet(request)})
            elif selected is None:
                winner = None

        async def run(strategy):
            nonlocal target_reads, context_error
            if evaluation[strategy] != 'running':
                return
            try:
                if strategy == 'core':
                    epoch = self.history.epoch if self.history else None
                    operation = self.read_basis(block)
                    assets, weights, reads = await budget.discovery(operation) if budget else await operation
                    target_reads += reads
                    if not self.history or self.history.epoch == epoch:
                        self.basis, self.basis_epoch = (assets, weights), epoch
                    adapted = core_request(request, assets, weights)
                else:
                    adapted = market_request(request)
                def execution_value(quote):
                    counter = ZERO if request['native'] else request['counterToken']
                    return {'strategy': strategy, 'side': request['side'], 'mode': request['mode'],
                        'tokenIn': counter if request['side'] == 'buy' else self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS,
                        'tokenOut': self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS if request['side'] == 'buy' else counter,
                        **economics(strategy, request, quote), 'context': quote['context'],
                        'providerRequest': deepcopy(adapted), 'providerQuote': deepcopy(quote)}
                async def publish(frame):
                    nonlocal context_error
                    if frame['type'] == 'qualified':
                        if context_error is not None:
                            return
                        quote = frame['value']
                        value = execution_value(quote)
                        async with lock:
                            if context_error is not None:
                                return
                            old = candidates.get(strategy)
                            if old is None or score(request, value) >= score(request, old):
                                candidates[strategy] = value
                                await select()
                                if old != value:
                                    await evidence({'type': 'provider-qualified', 'strategy': strategy,
                                                    'value': candidate_value(value)})
                                    await assessment(strategy)
                    elif frame['type'] == 'invalidated':
                        async with lock:
                            if frame.get('reason') == 'snapshot-changed':
                                context_error = SnapshotChanged('Recovery snapshot changed; restart discovery', retry=1)
                                candidates.clear()
                                self.fast_estimates.invalidate(request, scope=self.estimate_scope())
                                if winner:
                                    await on_update({'type': 'invalidated', 'strategy': winner['strategy']})
                                await select()
                                await evidence({'type': 'model', 'value': self.packet(request)})
                            else:
                                candidates.pop(strategy, None)
                                if winner and winner['strategy'] == strategy:
                                    self.fast_estimates.invalidate(request, scope=self.estimate_scope())
                                    await on_update({'type': 'invalidated', 'strategy': strategy})
                                    await select()
                                    await evidence({'type': 'model', 'value': self.packet(request)})
                            if budget:
                                budget.ready = bool(candidates)
                            for name in (('core', 'market') if context_error is not None else (strategy,)):
                                await assessment(name)
                    elif frame['type'] == 'model':
                        await on_update({'type': 'model', 'value': self.packet(request, {strategy: frame['value']})})
                    elif frame['type'] == 'progress':
                        await on_update({'type': 'progress', 'strategy': strategy,
                                         'value': {name: value for name, value in frame.items() if name != 'type'}})
                    # An estimate is never an executable winner. The common
                    # packet ranks its separate indicative family models.
                quote = (await self.core.get(adapted, publish, block=block, quoted_ranking=True) if strategy == 'core'
                         else await self.market._get(adapted, publish, block=block))
                await publish({'type': 'qualified', 'value': quote})
                terminal_candidates[strategy] = execution_value(quote)
                evaluation[strategy] = 'complete'
                search_outcomes[strategy] = 'complete'
                await assessment(strategy)
            except SearchStopped as error:
                evaluation[strategy] = 'unavailable'
                search_outcomes[strategy] = 'timeout'
                errors[strategy] = TimeoutError('Quote selection budget exhausted')
                error_quote_diagnostics[strategy] = quote_failure_context(error)
                provider_errors[strategy] = public_quote_error(errors[strategy])
                await assessment(strategy)
            except asyncio.CancelledError:
                evaluation[strategy] = 'unavailable'
                search_outcomes[strategy] = 'cancelled'
                try:
                    await assessment(strategy)
                finally:
                    raise
            except Exception as error:
                evaluation[strategy] = 'unavailable'
                errors[strategy] = error
                error_quote_diagnostics[strategy] = quote_failure_context(error)
                provider_errors[strategy] = public_quote_error(error)
                code = provider_errors[strategy]['code']
                search_outcomes[strategy] = ('timeout' if code in ('quote-timeout', 'rpc-timeout') else
                                             'complete' if code in ('quote-no-route', 'quote-insufficient-liquidity',
                                                                    'issuance-cap-exceeded') else 'error')
                if isinstance(error, SnapshotChanged):
                    async with lock:
                        context_error = error
                        self.fast_estimates.invalidate(request, scope=self.estimate_scope())
                        if winner:
                            await on_update({'type': 'invalidated', 'strategy': winner['strategy']})
                        candidates.clear()
                        await select()
                        await evidence({'type': 'model', 'value': self.packet(request)})
                await on_update({'type': 'provider-error', 'strategy': strategy, **public_quote_error(error)})
                for name in (('core', 'market') if context_error is not None else (strategy,)):
                    await assessment(name)

        async def models():
            value = await self.acquire_models(request, block)
            await on_update({'type': 'model', 'value': value})
            if value.get('estimate'):
                await on_update({'type': 'estimate', **value['estimate']})
        for strategy in ('core', 'market'):
            await assessment(strategy)
        model_task = asyncio.create_task(models())
        tasks = [asyncio.create_task(run(strategy)) for strategy in strategies]
        try:
            await asyncio.gather(*tasks)
            if context_error is not None:
                bind_quote_error(context_error, next((error_quote_diagnostics[strategy]
                    for strategy, error in errors.items() if error is context_error), None))
                raise context_error
            # Ordinary search errors retain the existing checked-incumbent
            # fallback. A policy cutoff must obtain a provider terminal value,
            # including its final canonical validation and owned-task drain.
            final = terminal_candidates if budget and budget.stop.is_set() else candidates
            for strategy in ('core', 'market'):
                await assessment(strategy, final)
            if final:
                winner = max(final.values(), key=lambda row: (score(request, row), row['strategy'] == 'core'))
                self.fast_estimates.remember_selected(request, winner, scope=self.estimate_scope())
                await evidence({'type': 'model', 'value': self.packet(request)})
                return decorate(winner, final)
            error = next(iter(errors.values()), QuoteFailure('quote-no-route'))
            # A full Core cap does not prevent Market purchases. When that
            # independent provider also fails, expose why it could not fill
            # the request; retain the cap reason in Core's assessment.
            core_error = errors.get('core')
            if (getattr(core_error, 'code', None) == 'issuance-cap-exceeded'
                    and (getattr(core_error, 'constraint', None) or {}).get('availableRaw') == '0'
                    and 'market' in errors):
                error = errors['market']
            bind_quote_error(error, next((error_quote_diagnostics[strategy]
                for strategy, value in errors.items() if value is error), None))
            raise error
        finally:
            for task in [model_task, *tasks]:
                task.cancel()
            await asyncio.gather(model_task, *tasks, return_exceptions=True)


async def handle_trade_quote(request, service, *, model=False):
    try:
        value = (TradeModelRequest if model else TradeQuoteRequest).model_validate(await request.json()).model_dump()
        validate(value, model=model)
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid trade quote input.'}, status_code=400, headers={'Cache-Control': 'no-store'})
    observation = QuoteObservation(request, value)
    if model:
        try:
            result = await service.get_model(value)
            observation.finish('succeeded')
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except Exception as error:
            payload = observation.event(observation.error(error))
            return JSONResponse({key: value for key, value in payload.items() if key != 'type'},
                                status_code=503, headers={'Cache-Control': 'no-store'})
    async def events():
        queue = asyncio.Queue()
        provider_assessments, provider_candidates = {}, {}
        async def publish(frame):
            if frame['type'] == 'provider-assessment':
                provider_assessments[frame['strategy']] = deepcopy(frame['value'])
                if frame['value']['availability'] != 'qualified':
                    provider_candidates.pop(frame['strategy'], None)
            elif frame['type'] == 'provider-qualified':
                provider_candidates[frame['strategy']] = deepcopy(frame['value'])
            await queue.put(observation.event(frame))
        async def produce():
            try:
                await publish({'type': 'complete', 'value': await service.get(value, publish)})
            except Exception as error:
                payload = observation.error(error)
                if provider_assessments:
                    payload.update(providerAssessments=deepcopy(provider_assessments),
                                   providerCandidates=deepcopy(provider_candidates))
                await publish(payload)
            finally:
                await queue.put(None)
        task = asyncio.create_task(produce())
        try:
            while (frame := await queue.get()) is not None:
                yield json.dumps(frame, separators=(',', ':'))+'\n'
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            observation.finish('cancelled')
    return StreamingResponse(events(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

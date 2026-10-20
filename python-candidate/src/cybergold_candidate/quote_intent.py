"""The existing token quote flows, streamed through one canonical context."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from typing import Literal

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter
from web3 import Web3

from .basket_preview import BasketPreviewRpc, InvalidPreview
from .route_search import RouteSearchRpc, RouteTarget
from .token_preview import TokenPreviewRpc
from .quote_revalidation import RetainedPlanChanged, core_bounds, revalidate, selected_route
from .preview_errors import KnownPreviewError
from .quote_errors import QuoteFailure, RpcTimeout, rpc_failure, public_quote_error
from .quote_budget import current_budget, SearchStopped
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS, floor, ceil
from .issuance_capacity import capacity_amounts, read_capacity
from .route_encoding import encode_route
from .route_work_slots import engine_work
from .uniswap_routes import resize_branches, v3_plan
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation
from .rpc_diagnostics import (error_diagnostics, quote_work_scope, quote_background, quote_phase,
                              quote_qualified, route_subphase, finish_route_work, freeze_quote_work,
                              provider_qualification_begin, provider_qualification_current, provider_qualification_scope,
                              provider_qualification_stage, provider_qualification_finish, provider_qualification_terms,
                              provider_qualification_selected, current_quote_diagnostics)


class RetainedQuotePlan(BaseModel):
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)
    executionAmount: str
    maximumInputAmount: str
    minimumAmountOut: str
    expectedInputAmount: str | None = None
    quotes: list[dict]
    expectedCoreOutputs: list[dict]


class QuoteIntentRequest(BaseModel):
    mode: Literal['issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out']
    token: str
    quoteToken: str
    native: bool
    amount: str
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)
    adapter: str | None = None
    deadline: str
    orderedAssets: list[str]
    targets: list[RouteTarget] = Field(default_factory=list)
    retainedPlan: RetainedQuotePlan | None = None


REQUEST = TypeAdapter(QuoteIntentRequest)


def issue_input_bounds(quotes, maximum, direct, slippage_bps=DEFAULT_SLIPPAGE_BPS):
    """Allocate route cushions from unused input, without reducing CYGLD output.

    The deployed executor delivers a fixed net target and refunds unspent input.
    Its per-leg ceilings must fit the caller's existing aggregate input ceiling.
    A tight budget therefore limits the available input-price cushion rather
    than applying a second, unconditional percentage deduction to the output.
    """
    observed = [int(quote['amountIn']) for quote in quotes]
    cushions = [ceil(amount, slippage_bps) - amount for amount in observed]
    available = max(0, maximum - direct - sum(observed))
    allowance = min(available, sum(cushions))
    total = sum(cushions)
    allocated = 0
    cumulative = 0
    bounded = []
    for quote, amount, cushion in zip(quotes, observed, cushions, strict=True):
        cumulative += cushion
        next_allocated = allowance * cumulative // total if total else 0
        bounded.append({**quote, 'amountIn': str(amount + next_allocated - allocated)})
        allocated = next_allocated
    return bounded


def validate(value):
    try:
        for name in ('token', 'quoteToken'):
            Web3.to_checksum_address(value[name])
        for asset in value['orderedAssets']:
            Web3.to_checksum_address(asset)
        Web3().codec.encode(['uint256', 'uint256'], [int(value['amount']), int(value['deadline'])])
        for target in value['targets']:
            Web3.to_checksum_address(target['inputAsset'])
            Web3.to_checksum_address(target['outputAsset'])
            Web3().codec.encode(['uint256'], [int(target['amount'])])
    except Exception as error:
        raise InvalidPreview('Invalid quote input.') from error


def same_order(actual, expected):
    if [asset.lower() for asset in actual] != [asset.lower() for asset in expected]:
        raise InvalidPreview('Basket preview order changed.')


def route_failure(row, *, fallback_code='quote-no-route'):
    for failure in row['failures']:
        if failure.get('code') in ('rpc-rate-limit', 'rpc-timeout', 'rpc-unavailable', 'rpc-access-denied'):
            return QuoteFailure(failure['code'], diagnostics=failure.get('diagnostics'))
    for failure in row['failures']:
        if failure.get('code') == 'quote-timeout':
            return QuoteFailure('quote-timeout', diagnostics=failure.get('diagnostics'))
    failure = next(iter(row['failures']), {})
    return QuoteFailure(fallback_code, diagnostics=failure.get('diagnostics'))


class QuoteIntent:
    def __init__(self, settings, routes, now=None, *, seeds=None, basket_math=None, correction=None, history=None,
                 qualification=True, retain_plans=False, early_issue_probe=False):
        self.settings, self.routes = settings, routes
        self.history = history
        self.seeds, self.basket_math, self.correction = seeds, basket_math, correction
        self.qualification, self.retain_plans = qualification, retain_plans
        self.early_issue_probe = early_issue_probe
        self.retained = OrderedDict()
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def close(self):
        if self.basket_math:
            await self.basket_math.close()
        if self.history:
            await self.history.close()

    @quote_work_scope
    async def get(self, request, on_update, *, block=None, model_epoch=None, quoted_ranking=False):
        budget = current_budget()
        validate(request)
        slippage_bps = request.get('slippageBps', DEFAULT_SLIPPAGE_BPS)
        epoch = self.history.epoch if self.history and model_epoch is None else model_epoch
        if self.history and epoch == self.history.epoch:
            await on_update({'type': 'model', 'value': self.history.packet(request)})
        if self.routes.rpc is None:
            self.routes.rpc = RouteSearchRpc(self.settings)
        rpc = self.routes.rpc
        engine = self.routes.engine
        rpc.route_engine = engine
        basket = BasketPreviewRpc(self.settings, rpc.w3)
        token = TokenPreviewRpc(self.settings, rpc.w3)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(15):
                block = (await budget.prepare(rpc.block(None)) if budget is not None else await rpc.block(None)) if block is None else block
        except RpcTimeout:
            raise
        except TimeoutError:
            raise RpcTimeout('RPC context acquisition timed out') from None
        context = {'chainId': rpc.chain_id, 'blockNumber': str(block['number']),
                   'blockHash': block['hash'], 'observedAt': self.now()}
        if self.history and epoch == self.history.epoch:
            self.history.ensure_known_routes(engine, request, block, context)
            self.history.ensure_state(rpc, block, context)
        metrics = {'rpcReads': 3, 'rpcReadsRequested': 3, 'rpcReadsCoalesced': 0,
                   'rpcReadsReused': 0, 'rpcReadsScope': 'coordinator', 'candidateCalls': 0, 'iterations': 0}
        memo, estimates = {}, set()
        recovery = None
        waves = []
        qualified = None
        pending_qualification, qualifying = None, None
        capacity_state = None
        route_searches = {}
        expected_input_gross = None
        context_error = None

        async def capacity(rows):
            nonlocal capacity_state
            if capacity_state is None:
                capacity_state = asyncio.create_task(read_capacity(rpc, self.settings, block, metrics, shared=quoted_ranking))
            values = await asyncio.shield(capacity_state)
            return capacity_amounts(request, [row['best']['quote'] for row in rows], values)

        def result_value(value):
            return {**value, 'mode': request['mode'], 'slippageBps': slippage_bps, 'context': context,
                    **({'quoteDiagnostics': diagnostics} if (diagnostics := current_quote_diagnostics()) else {}),
                    'metrics': {**metrics, 'totalMs': round((time.perf_counter() - started) * 1000, 3)}}

        def improves(value):
            if qualified is None:
                return True
            if request['mode'] == 'issue-exact-in':
                return int(value['executionAmount']) > int(qualified['executionAmount'])
            if request['mode'] == 'issue-exact-out':
                field = 'expectedInputAmount' if quoted_ranking else 'maximumInputAmount'
                return int(value.get(field, value['maximumInputAmount'])) < int(qualified.get(field, qualified['maximumInputAmount']))
            if request['mode'] == 'redeem-exact-in':
                if quoted_ranking:
                    return int(value['displayAmount']) > int(qualified['displayAmount'])
                return int(value['preview']['minimumAmountOut']) > int(qualified['preview']['minimumAmountOut'])
            return int(value['executionAmount']) < int(qualified['executionAmount'])

        def qualification_terms(value):
            try:
                issue = request['mode'].startswith('issue')
                provider_qualification_terms(executionAmount=value['executionAmount'],
                    quotedInput=value.get('expectedInputAmount', value['maximumInputAmount']) if issue else value['executionAmount'],
                    quotedOutput=value['executionAmount'] if issue else value.get('expectedOutputAmount', value['preview']['minimumAmountOut']),
                    inputMaximum=value['maximumInputAmount'] if issue else value['executionAmount'],
                    outputMinimum=value['executionAmount'] if issue else value['preview']['minimumAmountOut'],
                    branches=[branch for leg in value['quotes'] for branch in leg.get('routePlan', {}).get('branches', [])])
            except Exception:
                pass  # Optional evidence cannot change quote qualification.

        async def invalidate_context(error):
            nonlocal context_error, qualified, pending_qualification
            context_error = error
            if budget is not None:
                budget.invalidated()
            qualified = None
            quote_qualified(False)
            if pending_qualification:
                provider_qualification_finish(pending_qualification[1], 'cancelled')
            pending_qualification = None
            await on_update({'type': 'invalidated', 'context': context, 'reason': 'snapshot-changed'})

        async def qualify():
            nonlocal pending_qualification, qualified, context_error
            while pending_qualification is not None:
                (read, probe), pending_qualification = pending_qualification, None
                try:
                    with provider_qualification_scope(probe):
                        value = await read()
                        if not request['mode'].startswith('issue'):
                            value.setdefault('expectedCoreOutputs', core_bounds(value['preview']['projectedCoreOutputs'], slippage_bps))
                        qualification_terms(value)
                        if not improves(value):
                            provider_qualification_finish(probe, 'not-improved')
                            continue
                        metrics['rpcReads'] += 1
                        metrics['rpcReadsRequested'] += 1
                        provider_qualification_stage('canonicality')
                        async with asyncio.timeout(15):
                            await rpc.assert_canonical(block)
                        provider_qualification_stage('selection')
                        if budget is not None and not budget.qualified():
                            provider_qualification_finish(probe, 'cancelled')
                            continue
                        qualified = value
                        provider_qualification_selected(probe)
                        quote_qualified(True)
                        provider_qualification_finish(probe, 'qualified')
                        await on_update({'type': 'qualified', 'value': result_value(value)})
                except asyncio.CancelledError:
                    provider_qualification_finish(probe, 'cancelled')
                    raise
                except SnapshotChanged as error:
                    # A disproved common snapshot is different from an
                    # unavailable prospective route. It also retires an
                    # earlier tuple and survives a later ordinary tail error.
                    provider_qualification_finish(probe, 'rejected', error)
                    await invalidate_context(error)
                    return
                except Exception as error:
                    # An optional candidate failure does not replace ordinary
                    # complete coverage/validation or discard a checked tuple.
                    provider_qualification_finish(probe, 'rejected', error)

        def schedule_qualification(read):
            nonlocal pending_qualification, qualifying
            if not self.qualification or context_error is not None:
                return
            if pending_qualification:
                provider_qualification_finish(pending_qualification[1], 'superseded')
            probe = provider_qualification_current() or provider_qualification_begin()
            if probe is not None:
                probe.scheduled = True
            pending_qualification = (read, probe)
            if qualifying is None or qualifying.done():
                async def background():
                    with quote_background():
                        await qualify()
                qualifying = asyncio.create_task(background())
                estimates.add(qualifying)
                qualifying.add_done_callback(estimates.discard)

        async def preview(service, value):
            provider_qualification_stage('basket-preview' if service is basket else 'final-preview')
            data = service.encode(value)
            key = (service.helpers, data)
            if key not in memo:
                async def read():
                    metrics['rpcReads'] += 1
                    metrics['rpcReadsRequested'] += 1
                    async with asyncio.timeout(15):
                        return await service.preview(value['mode'], data, block)
                async def cached():
                    if self.basket_math and service is basket:
                        return await self.basket_math.read(rpc.chain_id, block, service.helpers, data, read)
                    return await read()
                memo[key] = asyncio.create_task(cached())
            return await asyncio.shield(memo[key])

        async def estimate(read, display):
            try:
                result = await read()
                value = display(result)
                if int(value) > 0:
                    await on_update({'type': 'estimate', 'amount': str(value), 'context': context})
            except Exception:
                # An early candidate is display-only. The final selected call
                # still returns its ordinary error; failure never means ready.
                pass

        def schedule(read, display):
            async def background():
                with quote_background():
                    await estimate(read, display)
            task = asyncio.create_task(background())
            estimates.add(task)
            task.add_done_callback(estimates.discard)

        def legs(targets, rows, mode, redeem=False, protect=True):
            values = []
            for target, row in zip(targets, rows, strict=True):
                if not row['best']:
                    raise route_failure(row)
                best = row['best']
                observed = int(best['quote'])
                if mode == 'exact-in':
                    limit = floor(observed, slippage_bps) if protect else observed
                    bound = limit
                else:
                    limit = int(target['amount'])
                    bound = ceil(observed, slippage_bps) if protect else observed
                route_plan = {**deepcopy(best['routePlan']), 'limit': str(limit), 'deadline': request['deadline']}
                leg = {'adapter': request['adapter'], 'minimumAmountOut': str(limit),
                    'routePlan': route_plan, 'data': encode_route(route_plan, request['adapter'])}
                if redeem:
                    leg.update(inputAsset=target['inputAsset'], inputAmount=target['amount'])
                else:
                    leg.update(outputAsset=target['outputAsset'], amountIn=target['amount'] if mode == 'exact-in' else str(bound))
                values.append(leg)
            return values

        def canonical_rows(rows, targets, mode):
            """Normalize retained/injected route results at the service boundary."""
            rows = deepcopy(rows)
            for row, target in zip(rows, targets, strict=True):
                best = row.get('best')
                if best is None:
                    continue
                plan = best.get('routePlan')
                if plan is None:
                    plan = v3_plan(best['path'], mode, target['amount'], chain_id=rpc.chain_id)
                    plan.update(inputAmount=str(target['amount'] if mode == 'exact-in' else best['quote']),
                        outputAmount=str(best['quote'] if mode == 'exact-in' else target['amount']))
                plan['executionContext'] = 'helpers-core'
                best['routePlan'] = plan
            return rows

        async def search(targets, mode, stage, early=None, *, logical_phase=None, wait_early=False):
            quote_phase(logical_phase or ('initial-search' if stage == 'initial' else 'execution-search'))
            cache_key = (mode, json.dumps(targets, sort_keys=True))
            if cache_key in route_searches:
                rows = route_searches[cache_key]
                if early:
                    early(rows)
                return rows
            previous = None
            pending_early, preparing = None, None
            async def prepare_early():
                nonlocal pending_early
                while pending_early is not None:
                    rows, pending_early = pending_early, None
                    probe = provider_qualification_begin('composition') if self.qualification else None
                    try:
                        # Prospective replay shares candidate pricing slots
                        # and the producer's existing selection budget.
                        with provider_qualification_scope(probe):
                            async with engine_work(engine.semaphore):
                                rows = await engine.compose_core_rows(rows,
                                    'exactIn' if mode == 'exact-in' else 'exactOut', block,
                                    ordered_assets=request['orderedAssets'], issue=request['mode'].startswith('issue'))
                            early(rows)
                            if probe is not None and not probe.scheduled:
                                provider_qualification_finish(probe, 'not-improved')
                            if wait_early and qualifying is not None:
                                await asyncio.shield(qualifying)
                                if context_error is not None:
                                    raise context_error
                    except asyncio.CancelledError:
                        freeze_quote_work()
                        provider_qualification_finish(probe, 'cancelled')
                        raise
                    except SnapshotChanged as error:
                        provider_qualification_finish(probe, 'rejected', error)
                        if context_error is not error:
                            await invalidate_context(error)
                        if wait_early:
                            raise
                        return
                    except Exception as error:
                        # Final selection retains its ordinary errors. A failed
                        # prospective replay may be superseded by another route.
                        provider_qualification_finish(probe, 'rejected', error)
            async def update(event):
                nonlocal previous, pending_early, preparing
                rows = canonical_rows(event['results'], targets, mode)
                await on_update({'type': 'progress', 'stage': stage,
                    'completed': sum(row['attempted'] for row in rows), 'total': sum(row['total'] for row in rows)})
                identity = json.dumps([row['best'] for row in rows], sort_keys=True)
                if early and all(row['best'] for row in rows) and identity != previous:
                    previous = identity
                    pending_early = deepcopy(rows)
                    if wait_early:
                        # Use the completed candidate's released slots for its
                        # executable check before unrelated coverage refills them.
                        with quote_background():
                            await prepare_early()
                    elif preparing is None or preparing.done():
                        async def background():
                            with quote_background():
                                await prepare_early()
                        preparing = asyncio.create_task(background())
                        estimates.add(preparing)
                        preparing.add_done_callback(estimates.discard)
            search_request = {'mode': mode, 'targets': targets, 'adapter': request['adapter']}
            try:
                result = await self.routes.get(search_request, on_update=update, block=block)
                # Candidate failures are isolated by the common scheduler. A
                # deadline that leaves a required leg unquoted still belongs
                # to this search, before any subsequent preview phase begins.
                for row in result['results']:
                    if row['best'] is None and any(failure.get('code') == 'quote-timeout'
                            for failure in row['failures']):
                        raise route_failure(row)
            except Exception as error:
                freeze_quote_work(error)
                # Freeze the route cause before this search's prospective
                # replay cleanup can replace the request-local RPC context.
                if getattr(error, 'rpc_diagnostics', None) is None:
                    diagnostics = error_diagnostics(error)
                    if diagnostics:
                        error.rpc_diagnostics = diagnostics
                raise
            finally:
                if preparing:
                    preparing.cancel()
                    await asyncio.gather(preparing, return_exceptions=True)
            route_subphase('composition')
            async with engine_work(engine.semaphore):
                result['results'] = await engine.compose_core_rows(canonical_rows(result['results'], targets, mode),
                    'exactIn' if mode == 'exact-in' else 'exactOut', block,
                    ordered_assets=request['orderedAssets'], issue=request['mode'].startswith('issue'))
            finish_route_work()
            for key in ('rpcReads', 'rpcReadsRequested', 'rpcReadsCoalesced', 'rpcReadsReused', 'candidateCalls'):
                metrics[key] += result['metrics'][key]
            waves.append((mode, result['results'], result['context']))
            route_searches[cache_key] = result['results']
            return result['results']

        def issue_request(mode, quotes, amount, net=None):
            value = {'mode': 'issue-' + ('native' if request['native'] else 'token') + '-' + mode,
                     'quotes': quotes}
            if not request['native']:
                value['inputToken'] = request['token']
            if mode == 'exact-in':
                value['inputAmount'] = str(amount)
            else:
                value['maximumNativeIn' if request['native'] else 'maximumInputAmount'] = str(amount)
                value['netCygldOut'] = str(net)
            return value

        def issue_estimate(value):
            same_order(value['orderedCoreAssets'], request['orderedAssets'])
            return value['netCygldOut']

        async def issue():
            amount = int(request['amount'])
            initial = None
            capacity_value = {}
            if request['mode'] == 'issue-exact-in':
                targets = request['targets']
                def early(rows):
                    # Advisory construction uses expected route output. It is
                    # not an execution minimum or a slippage-adjusted payout.
                    value = issue_request('exact-in', legs(targets, rows, 'exact-in', protect=False), amount)
                    schedule(lambda: preview(token, value), issue_estimate)
                    if not self.early_issue_probe:
                        return
                    async def checked():
                        provisional = await preview(token, value)
                        same_order(provisional['orderedCoreAssets'], request['orderedAssets'])
                        net = int(provisional['netCygldOut'])
                        provider_qualification_terms(executionAmount=str(net))
                        selected = []
                        for index, (target, row) in enumerate(zip(targets, rows, strict=True)):
                            # Fresh revalidation resolves the same selected
                            # pools and rebuilds calldata after Core quantities
                            # and exact-output bounds are known.
                            leg = deepcopy(value['quotes'][index])
                            leg['routePlan']['mode'] = 'exactOut'
                            for branch in leg['routePlan']['branches']:
                                branch['amountIn'] = '0'
                            selected.append(leg)
                        result = await revalidate(request, {'executionAmount': str(net), 'maximumInputAmount': str(amount),
                            'quotes': selected, 'slippageBps': slippage_bps}, rpc, block, basket, token, preview, metrics)
                        result.update(initialPreview=provisional, displayAmount=provisional['netCygldOut'])
                        result.update(await capacity(rows))
                        return result
                    schedule_qualification(checked)
                rows = await search(targets, 'exact-in', 'initial', early)
                quote_phase('initial-preview')
                initial = await preview(token, issue_request('exact-in', legs(targets, rows, 'exact-in', protect=False), amount))
                same_order(initial['orderedCoreAssets'], request['orderedAssets'])
                net = int(initial['netCygldOut'])
                quote_phase('capacity')
                capacity_value = await capacity(rows)
            else:
                net = amount
            quote_phase('basket-preview')
            required = await preview(basket, {'mode': 'issue-exact-out', 'netCygldOut': str(net)})
            same_order(required['orderedCoreAssets'], request['orderedAssets'])
            targets = [{'inputAsset': request['quoteToken'], 'outputAsset': asset, 'amount': raw}
                for asset, raw in zip(required['orderedCoreAssets'], required['amountsInExact'], strict=True)
                if int(raw) > 0 and asset.lower() != request['quoteToken'].lower()]
            direct = sum(int(raw) for asset, raw in zip(required['orderedCoreAssets'], required['amountsInExact'], strict=True)
                         if asset.lower() == request['quoteToken'].lower())
            def execution_quotes(rows):
                if initial is None:
                    return legs(targets, rows, 'exact-out')
                return issue_input_bounds(legs(targets, rows, 'exact-out', protect=False), amount, direct, slippage_bps)
            def early(rows):
                quotes = execution_quotes(rows)
                maximum = amount if initial else direct + sum(int(leg['amountIn']) for leg in quotes)
                if initial is None:
                    expected = direct + sum(int(row['best']['quote']) for row in rows)
                    schedule(lambda: asyncio.sleep(0, result=expected), str)
                async def checked():
                    final = await preview(token, issue_request('exact-out', quotes, maximum, net))
                    same_order(final['orderedCoreAssets'], request['orderedAssets'])
                    return {'quotes': quotes, 'preview': final, 'initialPreview': initial, 'basketPreview': required,
                            **capacity_value,
                            'displayAmount': str(int(initial['netCygldOut']) if initial else maximum),
                            'expectedInputAmount': str(direct + sum(int(row['best']['quote']) for row in rows)),
                            'executionAmount': str(net), 'maximumInputAmount': str(maximum)}
                schedule_qualification(checked)
            rows = await search(targets, 'exact-out', 'execution', early)
            quotes = execution_quotes(rows)
            maximum = amount if initial else direct + sum(int(leg['amountIn']) for leg in quotes)
            quote_phase('final-preview')
            final = await preview(token, issue_request('exact-out', quotes, maximum, net))
            same_order(final['orderedCoreAssets'], request['orderedAssets'])
            display = int(initial['netCygldOut']) if initial else maximum
            return {'quotes': quotes, 'preview': final, 'initialPreview': initial,
                    **capacity_value,
                    'basketPreview': required, 'displayAmount': str(display),
                    'expectedInputAmount': str(direct + sum(int(row['best']['quote']) for row in rows)),
                    'executionAmount': str(net), 'maximumInputAmount': str(maximum)}

        async def redemption(gross, early_display=True, *, protect=True, selected=None, fallback_gross=None,
                             remaining_corrections=10):
            quote_phase('basket-preview')
            try:
                required = await preview(basket, {'mode': 'redeem-exact-in', 'grossCygldIn': str(gross)})
            except KnownPreviewError as error:
                if fallback_gross is None or error.code not in ('insufficient-protocol-supply', 'redemption-supply-exceeded'):
                    raise
                gross = fallback_gross
                required = await preview(basket, {'mode': 'redeem-exact-in', 'grossCygldIn': str(gross)})
            targets = [{'inputAsset': row['token'], 'outputAsset': request['quoteToken'], 'amount': row['amount']}
                for row in required['projectedCoreOutputs'] if row['kind'] == 0 and int(row['amount']) > 0
                and row['token'].lower() != request['quoteToken'].lower()]
            def value(rows):
                return {'mode': 'redeem-' + ('native' if request['native'] else 'token') + '-exact-in',
                        'outputToken': request['token'], 'grossCygldIn': str(gross),
                        'quotes': legs(targets, rows, 'exact-in', redeem=True, protect=protect)}
            def expected_output(final, rows, quotes):
                # Helpers aggregates direct Core output and each routed minimum.
                # Restore the quoter's expected outputs for display; the signed
                # aggregate/leg minima remain the same execution protection.
                return int(final['minimumAmountOut']) + sum(int(row['best']['quote']) - int(leg['minimumAmountOut'])
                    for row, leg in zip(rows, quotes, strict=True))
            def early(rows):
                if not protect:
                    return
                selected = value(rows)
                if early_display:
                    schedule(lambda: preview(token, selected), lambda result: expected_output(result, rows, selected['quotes']))
                async def checked():
                    final = await preview(token, selected)
                    result = {'quotes': selected['quotes'], 'preview': final, 'initialPreview': None, 'basketPreview': required,
                            **({'expectedInputAmount': str(expected_input_gross)} if expected_input_gross is not None else {}),
                            'displayAmount': str(expected_output(final, rows, selected['quotes']) if early_display else gross),
                            'expectedOutputAmount': str(expected_output(final, rows, selected['quotes'])),
                            'executionAmount': str(gross), 'maximumInputAmount': '0'}
                    return await refine_redemption(result, remaining_corrections) if not early_display else result
                schedule_qualification(checked)
            if selected is None:
                rows = await search(targets, 'exact-in', 'execution', early,
                                    logical_phase='execution-search' if protect else 'expected-input-search')
            else:
                quote_phase('execution-search' if protect else 'expected-input-search')
                by_asset = {quote['inputAsset'].lower(): quote for quote in selected}
                async def reprice(target):
                    quote = by_asset[target['inputAsset'].lower()]
                    plan, _ = selected_route(quote, 'exactIn', int(target['amount']), rpc)
                    async with engine_work(engine.semaphore):
                        plan['branches'] = engine.resolve_branches(plan['branches'], target['inputAsset'],
                            target['outputAsset'], 'exactIn', int(target['amount']))
                        quoted = await engine.quote_branches(plan['branches'], 'exactIn', int(target['amount']), block)
                    plan.update(inputAmount=quoted['amountIn'], outputAmount=quoted['amountOut'])
                    return {'target': target, 'best': {'quote': quoted['amountOut'], 'routePlan': plan}, 'failures': []}
                composed = None
                planned = None
                if protect:
                    try:
                        planned = []
                        for target in targets:
                            plan, _ = selected_route(by_asset[target['inputAsset'].lower()],
                                'exactIn', int(target['amount']), rpc)
                            planned.append({'target': target, 'best': {'quote': '0', 'routePlan': plan},
                                'failures': []})
                        quote_shared = engine.quote_shared_core_rows
                    except SnapshotChanged:
                        raise
                    except Exception:
                        # The ordinary caller path owns malformed plans and
                        # legacy receivers without the optional shared method.
                        planned = None
                if planned is not None:
                    composed = await quote_shared(planned, 'exactIn', block,
                        ordered_assets=request['orderedAssets'], issue=False)
                    if composed is not None:
                        rows = composed
                if composed is None and protect:
                    # Isolated leg observations can overlap. Consume in Core
                    # order so errors keep their previous precedence; the
                    # shared-pool execution replay below remains sequential.
                    tasks = [asyncio.create_task(reprice(target)) for target in targets]
                    try:
                        rows = [await task for task in tasks]
                    finally:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                        disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
                        if disproof is not None:
                            raise disproof
                elif composed is None:
                    rows = [await reprice(target) for target in targets]
                metrics['candidateCalls'] += len(targets)
                if protect and composed is None:
                    async with engine_work(engine.semaphore):
                        rows = await engine.compose_core_rows(rows, 'exactIn', block,
                            ordered_assets=request['orderedAssets'], issue=False)
            selected = value(rows)
            quote_phase('final-preview')
            final = await preview(token, selected)
            return {'quotes': selected['quotes'], 'preview': final,
                    'initialPreview': None, 'basketPreview': required,
                    'expectedOutputAmount': str(expected_output(final, rows, selected['quotes'])),
                    'displayAmount': str(expected_output(final, rows, selected['quotes']) if early_display else gross), 'executionAmount': str(gross),
                    'maximumInputAmount': '0'}

        async def refine_redemption(result, remaining_corrections=10):
            """Check the existing eleven-point protected inversion on one route."""
            target = int(request['amount'])
            observations = []
            for iteration in range(remaining_corrections + 1):
                gross = int(result['executionAmount'])
                minimum = int(result['preview']['minimumAmountOut'])
                provider_qualification_stage('tolerance', targetAmount=str(target), minimumAmountOut=str(target),
                    maximumAmountOut=str(ceil(target, slippage_bps)), observedAmountOut=str(minimum))
                observations.append((gross, minimum))
                if target <= minimum <= ceil(target, slippage_bps):
                    return result
                if iteration == remaining_corrections or minimum <= 0:
                    break
                next_gross = gross * target // minimum
                next_gross = next_gross if next_gross != gross else gross + (1 if minimum < target else -1)
                if self.correction:
                    next_gross = self.correction(observations, target, next_gross)
                if next_gross <= 0:
                    break
                result = await redemption(next_gross, early_display=False, selected=result['quotes'])
            raise InvalidPreview('Candidate is outside the minimum-output interval.')

        async def recovery_assets():
            metrics['rpcReads'] += 1
            metrics['rpcReadsRequested'] += 1
            abi = [{'type': 'function', 'name': 'coreAttachedRecoveryAssets', 'stateMutability': 'view',
                    'inputs': [], 'outputs': [{'name': '', 'type': 'address[]'}]}]
            contract = rpc.w3.eth.contract(abi=abi)
            async with asyncio.timeout(15):
                response = await rpc.w3.provider.make_request('eth_call', [
                    {'to': Web3.to_checksum_address(self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS),
                     'data': contract.encode_abi('coreAttachedRecoveryAssets')},
                    {'blockHash': block['hash'], 'requireCanonical': True}])
            if 'error' in response:
                raise rpc_failure(response['error'])
            return rpc.w3.codec.decode(['address[]'], bytes.fromhex(response['result'][2:]))[0]

        async def redeem_out():
            nonlocal recovery, expected_input_gross
            # The existing amount-independent metadata read starts alongside
            # the first search and stays pinned to the operation's context.
            targets = request['targets']
            def minimums(rows, assets):
                by_asset = {target['inputAsset'].lower(): row
                            for target, row in zip(targets, rows, strict=True)}
                result = []
                for asset in request['orderedAssets']:
                    row = by_asset.get(asset.lower())
                    if row is not None and not row['best']:
                        if row['failures']:
                            raise route_failure(row, fallback_code='quote-unavailable')
                        raise InvalidPreview('No exact-out route found.')
                    amount = int(row['best']['quote']) if row is not None else 0
                    result.append({'kind': 0, 'token': asset, 'id': '0', 'minimumAmount': str(amount)})
                result.extend({'kind': 1, 'token': self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS,
                               'id': str(int(asset, 16)), 'minimumAmount': '0'} for asset in assets)
                return result
            async def seed(rows):
                assets = await asyncio.shield(recovery)
                return await preview(basket, {'mode': 'redeem-exact-out', 'minimumOutputs': minimums(rows, assets)})
            def padded_seed(initial):
                gross = int(initial['grossCygldIn'])
                routed = any(row['kind'] == 0 and int(row['amount']) > 0
                    and row['token'].lower() != request['quoteToken'].lower()
                    for row in initial['projectedCoreOutputs'])
                if routed and slippage_bps < 10_000:
                    adjusted = (gross * 10_000 + (10_000 - slippage_bps) - 1) // (10_000 - slippage_bps)
                    if adjusted < 2**256:
                        return adjusted
                return gross
            def early(rows):
                schedule(lambda: seed(rows), lambda result: result['grossCygldIn'])
                async def checked():
                    initial = await seed(rows)
                    original = int(initial['grossCygldIn'])
                    selected = []
                    for target, row in zip(targets, rows, strict=True):
                        plan = deepcopy(row['best']['routePlan'])
                        # Exact-output seed terms only locate a route. Actual
                        # forward Core amounts and prices are acquired below.
                        plan.update(mode='exactIn', inputAmount='0', outputAmount='0', limit='0')
                        selected.append({'inputAsset': target['inputAsset'],
                            'minimumAmountOut': '0', 'routePlan': plan})
                    gross = padded_seed(initial)
                    result = await redemption(gross, early_display=False, selected=selected,
                        fallback_gross=original if gross != original else None)
                    result = await refine_redemption(result)
                    result['initialPreview'] = initial
                    return result
                schedule_qualification(checked)
            async def legacy_seed():
                nonlocal recovery
                if recovery is None:
                    recovery = asyncio.create_task(recovery_assets())
                rows = await search(targets, 'exact-out', 'initial', early, wait_early=True)
                quote_phase('initial-preview')
                return await seed(rows)
            gross = self.seeds.suggest(request, context) if self.seeds else None
            hinted, initial, observations = gross is not None, None, []
            if not hinted:
                initial = await legacy_seed()
                gross = int(initial['grossCygldIn'])
            else:
                await on_update({'type': 'estimate', 'amount': str(gross), 'context': context})
            target = int(request['amount'])
            # Padding is only a protected-search hint. Keep the original seed
            # for advisory inversion and the specific first-preview fallback.
            expected_input_seed = gross
            if not hinted:
                gross = padded_seed(initial)
            for iteration in range(11):
                metrics['iterations'] = iteration
                quote_phase('execution-search', iteration=iteration)
                if gross <= 0:
                    raise InvalidPreview('Unable to compute a reliable quote for the entered amount.')
                result = await redemption(gross, early_display=False,
                    fallback_gross=expected_input_seed if iteration == 0 and gross != expected_input_seed else None,
                    remaining_corrections=10-iteration)
                gross = int(result['executionAmount'])
                quoted = int(result['preview']['minimumAmountOut'])
                observations.append((gross, quoted))
                if target <= quoted <= ceil(target, slippage_bps):
                    expected_input_gross = await expected_redemption_input(expected_input_seed)
                    result.update(displayAmount=str(gross), expectedInputAmount=str(expected_input_gross), initialPreview=initial)
                    return result
                if iteration == 10 or quoted <= 0:
                    raise InvalidPreview('Unable to compute a reliable quote for the entered amount.')
                next_gross = gross * target // quoted
                gross = next_gross if next_gross != gross else gross + (1 if quoted < target else -1)
                if self.correction:
                    gross = self.correction(observations, target, gross)
                if hinted and iteration == 0 and getattr(self.seeds, 'fallback', True):
                    # One fallback, within the original eleven evaluations.
                    initial = await legacy_seed()
                    gross, hinted = int(initial['grossCygldIn']), False
                    observations = []
            raise AssertionError('Unreachable correction loop')

        async def expected_redemption_input(gross, selected=None):
            """Invert raw market output separately from protected execution output."""
            target = int(request['amount'])
            observations = []
            for iteration in range(11):
                quote_phase('expected-input-search', iteration=iteration)
                result = await redemption(gross, early_display=False, protect=False, selected=selected)
                quoted = int(result['expectedOutputAmount'])
                observations.append((gross, quoted))
                # Keep the existing inversion's integer interval, independent
                # of the caller's execution tolerance.
                if target <= quoted <= ceil(target):
                    return gross
                if iteration == 10 or quoted <= 0:
                    raise InvalidPreview('Unable to compute a reliable expected quote for the entered amount.')
                next_gross = gross * target // quoted
                gross = next_gross if next_gross != gross else gross + (1 if quoted < target else -1)
                if self.correction:
                    gross = self.correction(observations, target, gross)
            raise AssertionError('Unreachable expected-input correction loop')

        async def discover(operation):
            try:
                return await operation
            except Exception as error:
                # A checked Helpers tuple survives an ordinary optimization
                # failure, as it does in the unified trade coordinator. A
                # disproved snapshot and caller cancellation still retire it.
                if isinstance(error, SnapshotChanged) or context_error is not None or qualified is None:
                    raise
                return deepcopy(qualified)

        async def drain():
            nonlocal pending_qualification, context_error
            if pending_qualification:
                provider_qualification_finish(pending_qualification[1], 'cancelled')
            pending_qualification = None
            tasks = list(estimates) + list(memo.values()) + ([recovery] if recovery else []) + ([capacity_state] if capacity_state else [])
            for task in tasks:
                task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            if context_error is None:
                context_error = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
            if budget is not None:
                budget.cleanup_done()
            if context_error is not None:
                raise context_error

        retained_key = json.dumps({key: value for key, value in request.items() if key not in ('deadline', 'retainedPlan')}, sort_keys=True)
        async def selection():
            incumbent = self.retained.get(retained_key) if self.retain_plans and rpc.chain_id == 1 else None
            result = None
            prior = None
            # Browser limits take precedence over another subscriber's bank entry.
            # These are hints only: current Basket, pool and Helpers reads follow.
            # A browser-selected plan can be freshly checked on every chain.
            # Sandbox still has no shared completed-plan bank: overrides may
            # change its state without changing the header.
            if self.retain_plans and request.get('retainedPlan'):
                plan = request['retainedPlan']
                prior = {**plan, 'preview': {'minimumAmountOut': plan['minimumAmountOut']}}
            elif incumbent and time.monotonic()-incumbent[0] < 600:
                prior = incumbent[1]
            if prior:
                quote_phase('retained-validation')
                retained_validation = provider_qualification_begin('retained-validation')
                try:
                    with provider_qualification_scope(retained_validation):
                        try:
                            result = await revalidate(request, prior, rpc, block, basket, token, preview, metrics)
                            qualification_terms(result)
                            provider_qualification_finish(retained_validation, 'qualified')
                        except asyncio.CancelledError:
                            freeze_quote_work()
                            provider_qualification_finish(retained_validation, 'cancelled')
                            raise
                        except Exception as error:
                            provider_qualification_finish(retained_validation, 'rejected', error)
                            raise
                except RetainedPlanChanged:
                    await on_update({'type': 'invalidated', 'context': context})
                except KnownPreviewError:
                    # A paid Core rejection invalidates this selected plan.
                    # Ordinary transport failures still retain prior display.
                    await on_update({'type': 'invalidated', 'context': context})
                except SnapshotChanged:
                    raise
                except Exception as error:
                    code = public_quote_error(error)['code']
                    if code.startswith('rpc-') or code == 'quote-timeout':
                        # An unavailable selected read cannot disprove this
                        # plan. Report its cause without a broad RPC search.
                        raise
                    # An unusable caller hint can use ordinary complete search.
            if result is not None:
                if request['mode'] == 'issue-exact-in':
                    selected = {leg['outputAsset'].lower(): leg for leg in result['quotes']}
                    observations = []
                    for target in request['targets']:
                        chosen = selected[target['outputAsset'].lower()]
                        plan = chosen['routePlan']
                        branches = resize_branches(plan['branches'], int(target['amount']))
                        async with engine_work(engine.semaphore):
                            value = await engine.quote_branches(branches, 'exactIn', int(target['amount']), block)
                        observations.append(value['amountOut'])
                    metrics['candidateCalls'] += len(observations)
                    rows = [{'best': {'quote': amount}} for amount in observations]
                    result.update(await capacity(rows))
                elif request['mode'] == 'redeem-exact-out':
                    seed = prior.get('expectedInputAmount') or result['executionAmount']
                    result['expectedInputAmount'] = str(await expected_redemption_input(int(seed), result['quotes']))
            elif request['mode'].startswith('issue'):
                result = await discover(issue())
            elif request['mode'] == 'redeem-exact-in':
                result = await discover(redemption(int(request['amount'])))
            else:
                result = await discover(redeem_out())
            return result

        try:
            stopped = False
            try:
                result = await budget.discovery(selection()) if budget is not None else await selection()
            except SearchStopped as error:
                stopped = True
                if qualified is None:
                    freeze_quote_work(error)
                    raise
                result = deepcopy(qualified)
            if budget is not None:
                await drain()
            quote_phase('canonicality')
            final_validation = provider_qualification_begin('canonicality')
            with provider_qualification_scope(final_validation):
                try:
                    qualification_terms(result)
                    async with asyncio.timeout(15):
                        await rpc.assert_canonical(block)
                except asyncio.CancelledError:
                    freeze_quote_work()
                    provider_qualification_finish(final_validation, 'cancelled')
                    raise
                except Exception as error:
                    provider_qualification_finish(final_validation, 'rejected', error)
                    if isinstance(error, SnapshotChanged):
                        quote_qualified(False)
                    raise
            if budget is not None:
                budget.canonical_done()
            if context_error is not None:
                raise context_error
            if budget is not None and not stopped and not budget.qualified():
                if qualified is None:
                    raise SearchStopped()
                result = deepcopy(qualified)
            with provider_qualification_scope(final_validation):
                qualification_terms(result)
                provider_qualification_selected(final_validation)
                provider_qualification_finish(final_validation, 'qualified')
            quote_qualified(True)
            # Final completion supersedes any still-running display-only read.
            result.update(mode=request['mode'], slippageBps=slippage_bps, context=context,
                          metrics={**metrics, 'totalMs': round((time.perf_counter() - started) * 1000, 3)})
            diagnostics = current_quote_diagnostics()
            if diagnostics:
                result['quoteDiagnostics'] = diagnostics
            if not request['mode'].startswith('issue'):
                result.setdefault('expectedCoreOutputs', core_bounds(result['preview']['projectedCoreOutputs'], slippage_bps))
            if self.retain_plans and rpc.chain_id == 1 and not request.get('retainedPlan'):
                # Caller limits are freshly checked, but do not replace another
                # client's shared full-search incumbent with a chosen subplan.
                self.retained[retained_key] = (time.monotonic(), deepcopy(result))
                self.retained.move_to_end(retained_key)
                while len(self.retained) > 256:
                    self.retained.popitem(last=False)
            if self.seeds and not request.get('retainedPlan'):
                self.seeds.observe(request, result)
            if self.history and epoch == self.history.epoch:
                if not request.get('retainedPlan'):
                    self.history.observe(request, result, waves)
                await on_update({'type': 'model', 'value': self.history.packet(request)})
                # Acquire optional components after exact work. Tasks belong to
                # the shared bank, survive subscriber departure, and never hold
                # completion open. No idle polling or calibration swaps.
                if epoch == self.history.epoch:
                    self.history.ensure_state(rpc, block, context)
                    for mode, rows, _ in waves:
                        for row in rows:
                            if row['best']:
                                self.history.ensure_route(engine, row['best']['routePlan'], block, context)
            return result
        except Exception as error:
            freeze_quote_work(error)
            # Auxiliary previews cancelled below must not replace the RPC
            # stage/timing of the primary failure with their cleanup cause.
            if getattr(error, 'rpc_diagnostics', None) is None:
                diagnostics = error_diagnostics(error)
                if diagnostics:
                    error.rpc_diagnostics = diagnostics
            raise
        finally:
            await drain()


def numeric_core_quote(value):
    """Old recipient-less Core API is a numerical read after executor migration."""
    fields = ('mode', 'context', 'slippageBps', 'metrics', 'displayAmount', 'executionAmount',
              'maximumInputAmount', 'expectedInputAmount', 'expectedOutputAmount')
    return {'readOnly': True, **{key: deepcopy(value[key]) for key in fields if key in value},
            'minimumAmountOut': str(value.get('preview', {}).get('minimumAmountOut', '0'))}


async def handle_quote_intent(request, service):
    try:
        value = REQUEST.validate_python(await request.json()).model_dump()
        validate(value)
    except ValueError:
        return JSONResponse({'error': 'Invalid quote input.'}, status_code=400, headers={'Cache-Control': 'no-store'})
    universal = getattr(service, 'universal_quotes', None)
    read_only = universal and universal.adapter and value['mode'] != 'issue-exact-out'
    observation = QuoteObservation(request, value, 'core')

    async def events():
        queue = asyncio.Queue()
        history = getattr(service, 'history', None)
        async def publish(event):
            if read_only and event['type'] in ('qualified', 'complete'):
                event = {**event, 'value': numeric_core_quote(event['value'])}
            epoch = history.epoch if history and event['type'] == 'model' else None
            await queue.put((observation.event(event), epoch))
        async def produce():
            try:
                await publish({'type': 'complete', 'value': await service.get(value, publish)})
            except Exception as error:
                await publish(observation.error(error))
        operation = asyncio.create_task(produce())
        try:
            while True:
                event, epoch = await queue.get()
                if event['type'] == 'model' and history and epoch != history.epoch:
                    continue
                yield json.dumps(event, separators=(',', ':')) + '\n'
                if event['type'] in ('complete', 'error'):
                    break
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            observation.finish('cancelled')
    return StreamingResponse(events(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

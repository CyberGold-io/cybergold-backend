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
from .route_search import RouteSearchRpc, RouteTarget, candidates
from .token_preview import TokenPreviewRpc
from .quote_revalidation import RetainedPlanChanged, core_bounds, revalidate
from .preview_errors import KnownPreviewError
from .quote_errors import QuoteFailure, RpcTimeout, rpc_failure, public_quote_error
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS, floor, ceil
from .issuance_capacity import capacity_amounts, read_capacity
from .market_swap import encode_adapter
from .uniswap_routes import resize_branches, uses_typed_adapter
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation
from .rpc_diagnostics import (error_diagnostics, quote_work_scope, quote_background, quote_phase,
                              quote_qualified, route_subphase, finish_route_work, freeze_quote_work)


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
            candidates(target, 'exact-in' if value['mode'] == 'issue-exact-in' else 'exact-out')
    except Exception as error:
        raise InvalidPreview('Invalid quote input.') from error


def same_order(actual, expected):
    if [asset.lower() for asset in actual] != [asset.lower() for asset in expected]:
        raise InvalidPreview('Basket preview order changed.')


def route_failure(row, *, fallback_code='quote-no-route'):
    for failure in row['failures']:
        if failure.get('code') in ('rpc-rate-limit', 'rpc-timeout', 'rpc-unavailable', 'rpc-access-denied'):
            return QuoteFailure(failure['code'], diagnostics=failure.get('diagnostics'))
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
        validate(request)
        slippage_bps = request.get('slippageBps', DEFAULT_SLIPPAGE_BPS)
        epoch = self.history.epoch if self.history and model_epoch is None else model_epoch
        if self.history and epoch == self.history.epoch:
            await on_update({'type': 'model', 'value': self.history.packet(request)})
        if self.routes.rpc is None:
            self.routes.rpc = RouteSearchRpc(self.settings)
        rpc = self.routes.rpc
        if getattr(self.routes, 'multi_protocol', None):
            rpc.multi_protocol = self.routes.multi_protocol
        multi_provider = getattr(self.routes, 'multi_protocol', None) if uses_typed_adapter(request['adapter']) else None
        basket = BasketPreviewRpc(self.settings, rpc.w3)
        token = TokenPreviewRpc(self.settings, rpc.w3)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(15):
                block = await rpc.block(None) if block is None else block
        except RpcTimeout:
            raise
        except TimeoutError:
            raise RpcTimeout('RPC context acquisition timed out') from None
        context = {'chainId': rpc.chain_id, 'blockNumber': str(block['number']),
                   'blockHash': block['hash'], 'observedAt': self.now()}
        if self.history and epoch == self.history.epoch and multi_provider:
            self.history.ensure_known_typed_pools(multi_provider, request, block, context)
            self.history.ensure_state(rpc, block, context)
        metrics = {'rpcReads': 3, 'rpcReadsRequested': 3, 'rpcReadsCoalesced': 0,
                   'rpcReadsReused': 0, 'candidateCalls': 0, 'iterations': 0}
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

        async def qualify():
            nonlocal pending_qualification, qualified, context_error
            while pending_qualification is not None:
                read, pending_qualification = pending_qualification, None
                try:
                    value = await read()
                    if not request['mode'].startswith('issue'):
                        value.setdefault('expectedCoreOutputs', core_bounds(value['preview']['projectedCoreOutputs'], slippage_bps))
                    if not improves(value):
                        continue
                    metrics['rpcReads'] += 1
                    metrics['rpcReadsRequested'] += 1
                    async with asyncio.timeout(15):
                        await rpc.assert_canonical(block)
                    qualified = value
                    quote_qualified(True)
                    await on_update({'type': 'qualified', 'value': result_value(value)})
                except SnapshotChanged as error:
                    # A disproved common snapshot is different from an
                    # unavailable prospective route. It also retires an
                    # earlier tuple and survives a later ordinary tail error.
                    context_error = error
                    qualified = None
                    quote_qualified(False)
                    pending_qualification = None
                    await on_update({'type': 'invalidated', 'context': context, 'reason': 'snapshot-changed'})
                    return
                except Exception:
                    # An optional candidate failure does not replace ordinary
                    # complete coverage/validation or discard a checked tuple.
                    pass

        def schedule_qualification(read):
            nonlocal pending_qualification, qualifying
            if not self.qualification or context_error is not None:
                return
            pending_qualification = read
            if qualifying is None or qualifying.done():
                async def background():
                    with quote_background():
                        await qualify()
                qualifying = asyncio.create_task(background())
                estimates.add(qualifying)
                qualifying.add_done_callback(estimates.discard)

        async def preview(service, value):
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
                route_plan = None
                if best.get('routePlan'):
                    route_plan = {**deepcopy(best['routePlan']), 'limit': str(limit), 'deadline': request['deadline']}
                    data = encode_adapter(route_plan)
                else:
                    data = '0x' + rpc.w3.codec.encode(['bytes', 'uint256', 'uint256', 'bool'],
                        [bytes.fromhex(best['path'][2:]), limit, int(request['deadline']), mode == 'exact-in']).hex()
                leg = {'adapter': request['adapter'], 'minimumAmountOut': str(limit), 'data': data}
                if route_plan:
                    leg['routePlan'] = route_plan
                if redeem:
                    leg.update(inputAsset=target['inputAsset'], inputAmount=target['amount'])
                else:
                    leg.update(outputAsset=target['outputAsset'], amountIn=target['amount'] if mode == 'exact-in' else str(bound))
                values.append(leg)
            return values

        async def search(targets, mode, stage, early=None, *, logical_phase=None):
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
                    try:
                        # Prospective shared-state replay uses the same budget
                        # as candidate quotes and cannot block search coverage.
                        async with multi_provider.semaphore:
                            rows = await multi_provider.compose_core_rows(rows,
                                'exactIn' if mode == 'exact-in' else 'exactOut', block,
                                ordered_assets=request['orderedAssets'], issue=request['mode'].startswith('issue'))
                        early(rows)
                    except Exception:
                        # Final selection retains its ordinary errors. A failed
                        # prospective replay may be superseded by another route.
                        pass
            async def update(event):
                nonlocal previous, pending_early, preparing
                rows = event['results']
                await on_update({'type': 'progress', 'stage': stage,
                    'completed': sum(row['attempted'] for row in rows), 'total': sum(row['total'] for row in rows)})
                identity = json.dumps([row['best'] for row in rows], sort_keys=True)
                if early and all(row['best'] for row in rows) and identity != previous:
                    previous = identity
                    if multi_provider:
                        pending_early = deepcopy(rows)
                        if preparing is None or preparing.done():
                            async def background():
                                with quote_background():
                                    await prepare_early()
                            preparing = asyncio.create_task(background())
                            estimates.add(preparing)
                            preparing.add_done_callback(estimates.discard)
                    else:
                        early(rows)
            search_request = {'mode': mode, 'targets': targets}
            if getattr(self.routes, 'multi_protocol', None):
                search_request['adapter'] = request['adapter']
            try:
                result = await self.routes.get(search_request, on_update=update, block=block)
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
            if multi_provider:
                route_subphase('composition')
                result['results'] = await multi_provider.compose_core_rows(result['results'],
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
                side_started = False
                def early(rows):
                    nonlocal side_started
                    # Advisory construction uses expected route output. It is
                    # not an execution minimum or a slippage-adjusted payout.
                    value = issue_request('exact-in', legs(targets, rows, 'exact-in', protect=False), amount)
                    schedule(lambda: preview(token, value), issue_estimate)
                    if side_started or not self.early_issue_probe:
                        return
                    side_started = True
                    async def checked():
                        provisional = await preview(token, value)
                        same_order(provisional['orderedCoreAssets'], request['orderedAssets'])
                        net = int(provisional['netCygldOut'])
                        selected = []
                        for index, (target, row) in enumerate(zip(targets, rows, strict=True)):
                            if row['best'].get('routePlan'):
                                # Fresh revalidation resolves the same selected
                                # pools, checks exact-output support and rebuilds
                                # calldata after quantities/bounds are known.
                                leg = deepcopy(value['quotes'][index])
                                leg['routePlan']['mode'] = 'exactOut'
                                for branch in leg['routePlan']['branches']:
                                    branch['amountIn'] = '0'
                                selected.append(leg)
                                continue
                            raw = bytes.fromhex(row['best']['path'][2:])
                            tokens = [raw[:20]] + [raw[offset+3:offset+23] for offset in range(20,len(raw),23)]
                            fees = [raw[offset:offset+3] for offset in range(20,len(raw),23)]
                            reverse = tokens[-1] + b''.join(fee+asset for fee,asset in zip(reversed(fees),reversed(tokens[:-1]),strict=True))
                            selected.append({'adapter': request['adapter'], 'outputAsset': target['outputAsset'],
                                'amountIn': target['amount'], 'minimumAmountOut': '0',
                                'data': '0x'+rpc.w3.codec.encode(['bytes','uint256','uint256','bool'],
                                    [reverse, 0, int(request['deadline']), False]).hex()})
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
                if fallback_gross is None or error.code != 'insufficient-protocol-supply':
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
                    minimum = int(final['minimumAmountOut'])
                    if not early_display and not int(request['amount']) <= minimum <= ceil(int(request['amount']), slippage_bps):
                        # Reuse the ordinary eleven forward evaluations while
                        # unrelated route coverage continues. Each local slope
                        # is a hint: new quantities are repriced, composed and
                        # checked by the full Helpers preview before publishing.
                        target = int(request['amount'])
                        observed_gross, quotes = gross, selected['quotes']
                        observations = [(observed_gross, minimum)]
                        for _ in range(remaining_corrections):
                            if minimum <= 0:
                                break
                            next_gross = observed_gross * target // minimum
                            next_gross = next_gross if next_gross != observed_gross else observed_gross + (1 if minimum < target else -1)
                            if self.correction:
                                next_gross = self.correction(observations, target, next_gross)
                            if next_gross <= 0:
                                break
                            revised = await redemption(next_gross, early_display=False, selected=quotes)
                            observed_gross = int(revised['executionAmount'])
                            minimum = int(revised['preview']['minimumAmountOut'])
                            observations.append((observed_gross, minimum))
                            if target <= minimum <= ceil(target, slippage_bps):
                                return revised
                            quotes = revised['quotes']
                        raise InvalidPreview('Candidate is outside the minimum-output interval.')
                    return {'quotes': selected['quotes'], 'preview': final, 'initialPreview': None, 'basketPreview': required,
                            **({'expectedInputAmount': str(expected_input_gross)} if expected_input_gross is not None else {}),
                            'displayAmount': str(expected_output(final, rows, selected['quotes']) if early_display else gross),
                            'expectedOutputAmount': str(expected_output(final, rows, selected['quotes'])),
                            'executionAmount': str(gross), 'maximumInputAmount': '0'}
                schedule_qualification(checked)
            if selected is None:
                rows = await search(targets, 'exact-in', 'execution', early,
                                    logical_phase='execution-search' if protect else 'expected-input-search')
            else:
                quote_phase('execution-search' if protect else 'expected-input-search')
                by_asset = {quote['inputAsset'].lower(): quote for quote in selected}
                calls, paths = [], []
                typed_rows = {}
                for target in targets:
                    quote = by_asset[target['inputAsset'].lower()]
                    if quote.get('routePlan'):
                        plan = deepcopy(quote['routePlan'])
                        plan['branches'] = resize_branches(plan['branches'], int(target['amount']))
                        if protect:
                            async with multi_provider.semaphore:
                                plan['branches'] = multi_provider.resolve_branches(plan['branches'], target['inputAsset'],
                                    target['outputAsset'], 'exactIn', int(target['amount']))
                                quoted = await multi_provider.quote_branches(plan['branches'], 'exactIn', int(target['amount']), block)
                            plan.update(inputAmount=quoted['amountIn'], outputAmount=quoted['amountOut'])
                        else:
                            quoted = await rpc.multi_protocol.quote_branches(plan['branches'], 'exactIn', int(target['amount']), block)
                        typed_rows[len(paths)] = {'best': {'path': '0x', 'quote': quoted['amountOut'], 'routePlan': plan}, 'failures': []}
                        paths.append(None)
                        continue
                    path, _, _, _ = rpc.w3.codec.decode(['bytes', 'uint256', 'uint256', 'bool'], bytes.fromhex(quote['data'][2:]))
                    paths.append('0x' + path.hex())
                    calls.append(rpc.encode({'mode': 'exact-in', 'path': paths[-1], 'amount': target['amount']}))
                counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
                observed = await rpc.quote_batch_counted('exact-in', calls, block, counts) if calls else []
                for name, counter in (('rpcReads', 'issued'), ('rpcReadsRequested', 'requested'),
                                      ('rpcReadsCoalesced', 'coalesced'), ('rpcReadsReused', 'reused')):
                    metrics[name] += counts[counter]
                metrics['candidateCalls'] += len(calls)
                ordinary = iter([{'best': {'path': path, 'quote': row['amount']}, 'failures': []}
                        if row['status'] == 'success' else {'best': None, 'failures': [row]}
                        for path, row in zip((path for path in paths if path is not None), observed, strict=True)])
                rows = [typed_rows[index] if index in typed_rows else next(ordinary) for index in range(len(paths))]
                if protect and multi_provider:
                    rows = [{**row, 'target': target} for target, row in zip(targets, rows, strict=True)]
                    async with multi_provider.semaphore:
                        rows = await multi_provider.compose_core_rows(rows, 'exactIn', block,
                            ordered_assets=request['orderedAssets'], issue=False)
            selected = value(rows)
            quote_phase('final-preview')
            final = await preview(token, selected)
            return {'quotes': selected['quotes'], 'preview': final,
                    'initialPreview': None, 'basketPreview': required,
                    'expectedOutputAmount': str(expected_output(final, rows, selected['quotes'])),
                    'displayAmount': str(expected_output(final, rows, selected['quotes']) if early_display else gross), 'executionAmount': str(gross),
                    'maximumInputAmount': '0'}

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
            def early(rows):
                schedule(lambda: seed(rows), lambda result: result['grossCygldIn'])
            async def legacy_seed():
                nonlocal recovery
                if recovery is None:
                    recovery = asyncio.create_task(recovery_assets())
                rows = await search(targets, 'exact-out', 'initial', early)
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
            routed = initial and any(row['kind'] == 0 and int(row['amount']) > 0
                and row['token'].lower() != request['quoteToken'].lower() for row in initial['projectedCoreOutputs'])
            if not hinted and routed and slippage_bps < 10_000:
                adjusted = (gross * 10_000 + (10_000 - slippage_bps) - 1) // (10_000 - slippage_bps)
                if adjusted < 2**256:
                    gross = adjusted
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

        try:
            retained_key = json.dumps({key: value for key, value in request.items() if key not in ('deadline', 'retainedPlan')}, sort_keys=True)
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
                try:
                    result = await revalidate(request, prior, rpc, block, basket, token, preview, metrics)
                except RetainedPlanChanged:
                    await on_update({'type': 'invalidated', 'context': context})
                except KnownPreviewError:
                    # A paid Core rejection invalidates this selected plan.
                    # Ordinary transport failures still retain prior display.
                    await on_update({'type': 'invalidated', 'context': context})
                except Exception as error:
                    code = public_quote_error(error)['code']
                    if code.startswith('rpc-') or code == 'quote-timeout':
                        # An unavailable selected read cannot disprove this
                        # plan. Report its cause without a broad RPC search.
                        raise
                    # An unusable caller hint can use ordinary complete search.
            if result is not None:
                if request['mode'] == 'issue-exact-in':
                    reverse = []
                    selected = {leg['outputAsset'].lower(): leg for leg in result['quotes']}
                    calls = []
                    typed_observations = []
                    for target in request['targets']:
                        chosen = selected[target['outputAsset'].lower()]
                        if chosen.get('routePlan'):
                            plan = chosen['routePlan']
                            branches = resize_branches(plan['branches'], int(target['amount']))
                            value = await rpc.multi_protocol.quote_branches(branches, 'exactIn', int(target['amount']), block)
                            typed_observations.append({'status': 'success', 'amount': value['amountOut']})
                            continue
                        path, _, _, _ = rpc.w3.codec.decode(['bytes', 'uint256', 'uint256', 'bool'], bytes.fromhex(selected[target['outputAsset'].lower()]['data'][2:]))
                        assets = [path[:20]] + [path[offset+3:offset+23] for offset in range(20, len(path), 23)]
                        fees = [path[offset:offset+3] for offset in range(20, len(path), 23)]
                        path = assets[-1] + b''.join(fee+asset for fee, asset in zip(reversed(fees), reversed(assets[:-1]), strict=True))
                        reverse.append('0x' + path.hex())
                        calls.append(rpc.encode({'mode': 'exact-in', 'path': reverse[-1], 'amount': target['amount']}))
                    counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
                    observations = await rpc.quote_batch_counted('exact-in', calls, block, counts) if calls else []
                    observations.extend(typed_observations)
                    for name, counter in (('rpcReads', 'issued'), ('rpcReadsRequested', 'requested'),
                                          ('rpcReadsCoalesced', 'coalesced'), ('rpcReadsReused', 'reused')):
                        metrics[name] += counts[counter]
                    metrics['candidateCalls'] += len(calls)
                    rows = [{'best': {'quote': row['amount']}} for row in observations if row['status'] == 'success']
                    if len(rows) != len(observations):
                        failure = next(row for row in observations if row['status'] != 'success')
                        raise QuoteFailure(failure.get('code', 'quote-unavailable'),
                                           diagnostics=failure.get('diagnostics'))
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
            quote_phase('canonicality')
            async with asyncio.timeout(15):
                await rpc.assert_canonical(block)
            if context_error is not None:
                raise context_error
            # Final completion supersedes any still-running display-only read.
            result.update(mode=request['mode'], slippageBps=slippage_bps, context=context,
                          metrics={**metrics, 'totalMs': round((time.perf_counter() - started) * 1000, 3)})
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
                            if row['best'] and row['best'].get('routePlan'):
                                self.history.ensure_typed_pool(self.routes.multi_protocol, row['best']['routePlan'], block, context)
                            elif row['best'] and row['best']['path'] != '0x':
                                self.history.ensure_pool(rpc, row['best']['path'], mode, block, context)
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
            for task in estimates:
                task.cancel()
            tasks = list(estimates) + list(memo.values()) + ([recovery] if recovery else []) + ([capacity_state] if capacity_state else [])
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if context_error is not None:
                raise context_error


async def handle_quote_intent(request, service):
    try:
        value = REQUEST.validate_python(await request.json()).model_dump()
        validate(value)
    except ValueError:
        return JSONResponse({'error': 'Invalid quote input.'}, status_code=400, headers={'Cache-Control': 'no-store'})
    observation = QuoteObservation(request, value, 'core')

    async def events():
        queue = asyncio.Queue()
        history = getattr(service, 'history', None)
        async def publish(event):
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

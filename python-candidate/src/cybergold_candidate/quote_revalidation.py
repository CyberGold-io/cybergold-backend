"""Fresh selected-plan checks preserve the originally accepted execution bounds."""
from copy import deepcopy

from .basket_preview import InvalidPreview
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS, floor, ceil
from .uniswap_routes import resize_branches, v3_plan
from .route_encoding import encode_route


class RetainedPlanChanged(InvalidPreview):
    """Fresh quantities/prices contradict the incumbent's original bounds."""


def core_bounds(outputs, slippage_bps=DEFAULT_SLIPPAGE_BPS):
    return [{'kind': row['kind'], 'token': row['token'], 'id': row['id'],
             'minimumAmount': str(floor(int(row['amount']), slippage_bps))}
            for row in outputs]


def check_core(outputs, bounds):
    actual = {(row['kind'], row['token'].lower(), row['id']): int(row['amount']) for row in outputs}
    expected = {(row['kind'], row['token'].lower(), row['id']): int(row['minimumAmount']) for row in bounds}
    if actual.keys() != expected.keys() or any(actual[key] < bound for key, bound in expected.items()):
        raise RetainedPlanChanged('Retained Core output bounds changed.')


def selected_route(leg, mode, amount, rpc):
    """Normalize an older retained ABI payload once at the request boundary."""
    if leg.get('routePlan'):
        plan = deepcopy(leg['routePlan'])
        limit = int(leg['minimumAmountOut'])
    else:
        path, limit, deadline, exact_in = rpc.w3.codec.decode(
            ['bytes', 'uint256', 'uint256', 'bool'], bytes.fromhex(leg['data'][2:]))
        plan = v3_plan(path, 'exactIn' if exact_in else 'exactOut', amount,
            chain_id=rpc.chain_id, limit=limit, deadline=deadline)
    if plan['mode'] != mode:
        raise RetainedPlanChanged('Retained swap mode changed.')
    plan['executionContext'] = 'helpers-core'
    if mode == 'exactIn':
        plan['branches'] = resize_branches(plan['branches'], amount)
    return plan, limit


async def revalidate(request, previous, rpc, block, basket, token, preview, metrics):
    slippage_bps = request.get('slippageBps', DEFAULT_SLIPPAGE_BPS)
    if previous.get('slippageBps', DEFAULT_SLIPPAGE_BPS) != slippage_bps:
        raise RetainedPlanChanged('Retained execution tolerance does not match the intent.')
    issue = request['mode'].startswith('issue')
    amount = int(previous['executionAmount'])
    if request['mode'] in ('issue-exact-out', 'redeem-exact-in') and amount != int(request['amount']):
        raise RetainedPlanChanged('Retained execution amount does not match the intent.')
    if request['mode'] == 'issue-exact-in' and int(previous['maximumInputAmount']) > int(request['amount']):
        raise RetainedPlanChanged('Retained input ceiling exceeds the intent budget.')
    required = await preview(basket, {'mode': 'issue-exact-out', 'netCygldOut': str(amount)} if issue
        else {'mode': 'redeem-exact-in', 'grossCygldIn': str(amount)})
    if issue:
        if [a.lower() for a in required['orderedCoreAssets']] != [a.lower() for a in request['orderedAssets']]:
            raise RetainedPlanChanged('Basket preview order changed.')
        quantities = [(asset, int(raw)) for asset, raw in zip(required['orderedCoreAssets'], required['amountsInExact'], strict=True)]
    else:
        bounds = previous.get('expectedCoreOutputs') or core_bounds(previous['preview']['projectedCoreOutputs'], slippage_bps)
        check_core(required['projectedCoreOutputs'], bounds)
        quantities = [(row['token'], int(row['amount'])) for row in required['projectedCoreOutputs'] if row['kind'] == 0]
    selected = {row['outputAsset' if issue else 'inputAsset'].lower(): row for row in previous['quotes']}
    targets = [(asset, raw) for asset, raw in quantities if raw > 0 and asset.lower() != request['quoteToken'].lower()]
    if {asset.lower() for asset, _ in targets} != selected.keys():
        raise RetainedPlanChanged('Retained swap asset set changed.')
    plans, values = [], []
    mode = 'exactOut' if issue else 'exactIn'
    provider = rpc.route_engine
    for asset, raw in targets:
        leg = selected[asset.lower()]
        plan, limit = selected_route(leg, mode, raw, rpc)
        try:
            branches = provider.resolve_branches(plan['branches'], request['quoteToken'] if issue else asset,
                asset if issue else request['quoteToken'], plan['mode'], raw)
        except InvalidPreview as error:
            raise RetainedPlanChanged(str(error)) from error
        try:
            metrics['candidateCalls'] += 1
            async with provider.semaphore:
                result = await provider.quote_branches(branches, mode, raw, block)
        except Exception as error:
            from .quote_errors import public_quote_error
            if public_quote_error(error)['code'] == 'quote-contract-reverted':
                raise RetainedPlanChanged('Retained route no longer quotes.') from error
            raise
        observed = result['amountIn' if issue else 'amountOut']
        plan.update(branches=branches, inputAmount=result['amountIn'], outputAmount=result['amountOut'])
        plans.append((leg, asset, raw, limit))
        values.append({'target': {'inputAsset': request['quoteToken'] if issue else asset,
            'outputAsset': asset if issue else request['quoteToken'], 'amount': str(raw)},
            'best': {'quote': observed, 'routePlan': plan}})
    async with provider.semaphore:
        values = await provider.compose_core_rows(values, mode, block,
            ordered_assets=request['orderedAssets'], issue=issue)
    quotes = []
    expected_surplus = 0
    expected_input = 0
    for (leg, asset, raw, limit), value in zip(plans, values, strict=True):
        observed = int(value['best']['quote'])
        if issue:
            if observed > int(leg['amountIn']):
                raise RetainedPlanChanged('Retained swap input bound cannot be met.')
            bound = min(int(leg['amountIn']), ceil(observed, slippage_bps))
            expected_input += observed
            limit = raw
            quote = {**leg, 'amountIn': str(bound), 'minimumAmountOut': str(raw)}
        else:
            if observed < limit:
                raise RetainedPlanChanged('Retained swap output bound cannot be met.')
            quote = {**leg, 'inputAmount': str(raw)}
            expected_surplus += observed - limit
        plan = value['best']['routePlan']
        plan.update(limit=str(limit), deadline=request['deadline'])
        quote.update(routePlan=plan, data=encode_route(plan, request['adapter']))
        quotes.append(quote)
    prefix = ('issue-' if issue else 'redeem-') + ('native' if request['native'] else 'token')
    if issue:
        needed = sum(raw for asset, raw in quantities if asset.lower() == request['quoteToken'].lower())
        expected_input += needed
        needed += sum(int(row['amountIn']) for row in quotes)
        maximum = int(previous['maximumInputAmount']) if request['mode'] == 'issue-exact-in' else needed
        if needed > int(previous['maximumInputAmount']):
            raise RetainedPlanChanged('Retained aggregate input bound cannot be met.')
        value = {'mode': prefix+'-exact-out', 'quotes': quotes, 'netCygldOut': str(amount),
                 'maximumNativeIn' if request['native'] else 'maximumInputAmount': str(maximum)}
        if not request['native']:
            value['inputToken'] = request['token']
    else:
        maximum = 0
        value = {'mode': prefix+'-exact-in', 'outputToken': request['token'], 'grossCygldIn': str(amount), 'quotes': quotes}
    final = await preview(token, value)
    if issue:
        if [a.lower() for a in final['orderedCoreAssets']] != [a.lower() for a in request['orderedAssets']]:
            raise RetainedPlanChanged('Basket preview order changed.')
    else:
        check_core(final['projectedCoreOutputs'], bounds)
        minimum = int(final['minimumAmountOut'])
        if minimum < int(previous['preview']['minimumAmountOut']):
            raise RetainedPlanChanged('Retained aggregate output bound cannot be met.')
        if request['mode'] == 'redeem-exact-out' and not int(request['amount']) <= minimum <= ceil(int(request['amount']), slippage_bps):
            raise RetainedPlanChanged('Retained minimum-output interval changed.')
    result = {'quotes': quotes, 'preview': final, 'initialPreview': None, 'basketPreview': required,
              'displayAmount': str(amount if request['mode'] in ('issue-exact-in', 'redeem-exact-out')
                                   else maximum if issue else int(final['minimumAmountOut']) + expected_surplus),
              'executionAmount': str(amount), 'maximumInputAmount': str(maximum)}
    if issue:
        result['expectedInputAmount'] = str(expected_input)
    else:
        result['expectedCoreOutputs'] = deepcopy(bounds)
    return result

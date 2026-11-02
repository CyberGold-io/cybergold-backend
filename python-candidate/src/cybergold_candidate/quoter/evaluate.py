"""Construct complete execution proposals; Helpers alone measures their result."""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, routed_sell_budget
from ..quote_budget import current_budget
from ..quote_errors import QuoteFailure
from ..routing_encoding import split_runtime, weighted_routes
from .contracts import path_operation, path_nomination
from .reuse_routes import _amounts

CORE_SHARES = (0, 25, 50, 75, 100)


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency, 'routes': []}


def nominate_conversion(self, source, target, amount, block, *, market=False):
    """Encode a supplied topology without pricing its amount or pool state."""
    if not amount or source.lower() == target.lower():
        return identity_template(source), {'inputCurrency': source, 'outputCurrency': target, 'branches': []}
    candidate = next(iter(self.amm.nominations(source, target, amount, block,
                                              market=market, first=True)), None)
    if candidate is None:
        raise QuoteFailure('quote-no-route')
    branches, origins = candidate
    branches = deepcopy(branches)
    physical_source = source
    leading = [row['hops'][0].get('kind') for row in branches]
    if leading and leading[0] in ('wrap', 'unwrap') and all(value == leading[0] for value in leading):
        physical_source = branches[0]['hops'][0]['currencyOut']
        for row in branches:
            row['hops'] = row['hops'][1:]
    template = {'inputCurrency': physical_source, 'outputCurrency': target,
                'routes': weighted_routes(branches)}
    chosen = {'inputCurrency': source, 'outputCurrency': target,
              'branches': [{'hops': row['hops']} for row in branches], 'template': deepcopy(template)}
    if origins:
        chosen['discoveryOrigins'] = sorted(origins)
    return template, chosen


async def replay_conversion(self, chosen, source, target, amount, block, bank, canonical, *, branch=0, stage=0, **_):
    if not amount or source.lower() == target.lower():
        return identity_template(source), amount, []
    if (chosen['inputCurrency'].lower() != source.lower()
            or chosen['outputCurrency'].lower() != target.lower() or not chosen['branches']):
        raise QuoteFailure('quote-no-route')
    routes = chosen['template']['routes']
    output, consumed, retained = 0, 0, []
    for selected, funded in zip(chosen['branches'], split_runtime(amount, routes), strict=True):
        with path_nomination(source, chosen.get('discoveryOrigins', ())):
            used, received = await self.price_path(selected['hops'], funded, block, bank, canonical)
        output += received
        consumed += used
        if used < funded:
            retained.append({'branch': branch, 'stage': stage + (chosen['template']['inputCurrency'].lower() != source.lower()),
                             'currency': chosen['template']['inputCurrency'], 'amount': str(funded-used)})
    if retained:
        retained = [{**retained[0], 'amount': str(sum(int(row['amount']) for row in retained))}]
    chosen['_observation'] = {'inputCurrency': chosen['template']['inputCurrency'],
        'fundedInput': str(amount), 'consumedInput': str(consumed), 'outputCurrency': target, 'output': str(output)}
    return deepcopy(chosen['template']), output, retained


async def core_output_descriptors(self, block):
    """Read cached execution identities; the Helpers call supplies quantities."""
    return deepcopy(await self.core_outputs(block))


async def evaluate_candidate(self, request, share, order, block, assets, weights, *, first=False,
                             observations=None, selected=None, selection=True):
    """Build first proposals from topology; detailed work may explore AMM paths.

    No amount-dependent Core preview belongs here. Acquisition allocations and
    retained output identities make the complete body executable; Core lots,
    fees, residuals and the final economic output come from one Helpers call.
    """
    if selected is not None:
        plan = deepcopy(selected)
    else:
        bank, canonical, recorded = {}, observations if observations is not None else {}, {}
        budget = current_budget()
        intent = request['intent']
        amount = int(request['inputs'][0]['amount'])

        async def convert(source, target, lot, operation, *, market=False, topology=False, optional=False):
            if first or topology:
                try:
                    route, chosen = nominate_conversion(self, source, target, lot, block, market=market)
                except QuoteFailure as error:
                    if not optional or error.code != 'quote-no-route':
                        raise
                    # A currently zero Core residual/output does not require a
                    # route. Leave a semantic identity; execution decides if a
                    # positive lot makes this particular proposal unavailable.
                    return identity_template(source)
            else:
                chosen = {}
                with path_operation(operation, int(operation.split(':')[0]), 0):
                    pending = self.conversion(source, target, lot, block, bank, canonical, first=False,
                                              market=market, capture=chosen)
                    route, _, _ = await budget.discovery(pending) if budget and selection else await pending
                chosen.pop('_observation', None)
            recorded[operation] = deepcopy(chosen)
            return route

        async def continuations(branch):
            result = []
            for index, asset in enumerate(assets):
                # The actual residual is produced inside Helpers. Nominal lots
                # select topology only and cause no SDK/RPC amount quotation.
                route = await convert(asset, self.core, 1, f'{branch}:residual:{index}',
                                      market=True, topology=True, optional=True)
                result.append({'route': route, 'feeCygld': '0'})
            return result

        async def buy_core(lot, branch):
            acquisitions = []
            for index, (asset, funded) in enumerate(zip(assets, _amounts(lot, list(weights)), strict=True)):
                route = await convert(request['inputs'][0]['currency'], asset, funded,
                                      f'{branch}:acquire:{index}')
                acquisitions.append({'amountIn': str(funded), 'route': route})
            return {'basketAssets': list(assets), 'acquisitions': acquisitions,
                    'continuations': await continuations(branch)}

        async def sell_core(branch, *, basket=False):
            outputs = await core_output_descriptors(self, block)
            routes = []
            for index, row in enumerate(outputs):
                if int(row['kind']) != 0:
                    routes.append(identity_template(row['token']))
                    continue
                if not basket:
                    routes.append(await convert(row['token'], request['outputCurrency'],
                        max(1, int(row.get('amount', '1'))), f'{branch}:redeem:{index}',
                        topology=True, optional=True))
            return {'expectedOutputs': outputs, **({'conversions': routes} if not basket else {})}

        if intent in (0, 1):
            core_amount = amount * share // 100
            stages = [('core', core_amount), ('market', amount-core_amount)]
            if order == 'market-first':
                stages.reverse()
            branches = []
            for kind, lot in stages:
                if not lot:
                    continue
                branch = len(branches)
                if kind == 'core':
                    data = await buy_core(lot, branch) if intent == 0 else await sell_core(branch)
                else:
                    source, target = request['inputs'][0]['currency'], request['outputCurrency']
                    rate = get_market_fee_rate(self.engine.registry.chain, source, target, 'exact-in')
                    fee = routed_sell_budget(lot, rate)[1] if intent == 1 else 0
                    data = {'route': await convert(source, target, lot-fee, f'{branch}:market', market=True),
                            'feeCygld': str(fee)}
                branches.append({'kind': 0 if kind == 'core' else 1, 'amountIn': str(lot), 'data': data})
            body = {'branches': branches}
            allocations = [{'kind': row['kind'], 'amountIn': row['amountIn']} for row in branches]
        elif intent == 2:
            body, allocations = {'continuations': await continuations(0)}, []
        else:
            body, allocations = await sell_core(0, basket=True), []
        plan = {'allocations': allocations, 'conversions': recorded, 'body': body}
    return {'request': deepcopy(request), 'plan': plan, 'inputs': deepcopy(request['inputs']),
            'searchCoverage': {'coreSharesPercent': list(CORE_SHARES), 'orders': ['core-first', 'market-first'],
                               'maxCoreInvocations': 1, 'maxAmmHops': 3, 'scope': 'selected-inventory'}}

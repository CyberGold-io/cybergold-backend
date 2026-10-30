"""Ordered whole-plan evaluation; discovery and wire compilation stay outside."""
from copy import deepcopy

from ..basket_preview import InvalidPreview
from ..market_fee import get_market_fee_rate, quoted_fee, routed_sell_budget
from ..quote_budget import current_budget
from ..quote_errors import QuoteFailure
from ..routing_encoding import ROUTING_ENCODING, split_runtime
from .contracts import path_operation
from .reuse_routes import selected_conversion

CORE_SHARES = (0, 25, 50, 75, 100)


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency, 'routes': []}


async def replay_conversion(self, chosen, source, target, amount, block, bank, canonical, *, branch=0, stage=0, **_):
    if not amount or source.lower() == target.lower():
        return identity_template(source), amount, []
    if (chosen['inputCurrency'].lower() != source.lower()
            or chosen['outputCurrency'].lower() != target.lower() or not chosen['branches']):
        raise QuoteFailure('quote-no-route')
    routes = chosen['template']['routes']
    output, consumed, retained = 0, 0, []
    for selected, funded in zip(chosen['branches'], split_runtime(amount, routes), strict=True):
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


async def evaluate_candidate(self, request, share, order, block, assets, weights, *, first=False,
                         observations=None, selected=None, selection=True):
    bank, canonical, retained, branches = {}, observations if observations is not None else {}, [], []
    recorded, conversion_observations = {}, []
    selected_routes = selected['conversions'] if selected is not None else None
    fees = {'coreProtocolFeeCygld': 0, 'coreHelpersFeeCygld': 0, 'marketFeeCygld': 0}
    intent = request['intent']
    amount = int(request['inputs'][0]['amount'])
    if selected is not None:
        total = sum(int(row['amountIn']) for row in selected['allocations'])
        if intent < 2 and total != amount:
            raise InvalidPreview('Selected allocations do not match declared funding.')
        share = sum(int(row['amountIn']) for row in selected['allocations'] if row['kind'] == 0) * 100 // total if total else 100
    core_amount = amount * share // 100
    market_amount = amount - core_amount
    output, recovery, recipient_outputs, cursor = 0, [], [], 0
    has_continuation = False
    budget = current_budget()
    async def convert(source, target, lot, *, operation, **kwargs):
        nonlocal cursor
        kwargs['stage'] = cursor
        if selected_routes is None:
            chosen = {}
            pending = self.conversion(source, target, lot, block, bank, canonical, first=first,
                                      capture=chosen, **kwargs)
        else:
            chosen = deepcopy(selected_conversion(selected, operation, source))
            if chosen is None:
                if lot and source.lower() != target.lower():
                    raise QuoteFailure('quote-no-route')
                chosen = {'inputCurrency': source, 'outputCurrency': target, 'branches': []}
            pending = replay_conversion(self, chosen, source, target, lot, block, bank, canonical, **kwargs)
        with path_operation(operation, kwargs.get('branch', 0), cursor):
            result = await budget.discovery(pending) if budget and selection else await pending
        observation = chosen.pop('_observation', None)
        if observation is not None:
            conversion_observations.append({'operation': operation, **observation})
        recorded[operation] = deepcopy(chosen)
        route = result[0]
        if lot and source.lower() != target.lower():
            cursor += (source.lower() != route['inputCurrency'].lower()) + (
                route['inputCurrency'].lower() != route['outputCurrency'].lower()) + (
                route['outputCurrency'].lower() != target.lower())
        return result
    async def continuation(lots, branch):
        nonlocal output, cursor, has_continuation
        result = []
        for index, (asset, lot) in enumerate(zip(assets, lots, strict=True)):
            cursor += 1  # Core issuance appends each actual/residual basket lot.
            if not lot:
                result.append({'route': identity_template(asset), 'feeCygld': '0'})
                continue
            has_continuation = True
            route, gross, left = await convert(asset, self.core, lot, market=True,
                                               branch=branch, stage=index + len(assets), operation=f'{branch}:residual:{index}')
            fee = quoted_fee(gross, get_market_fee_rate(self.engine.registry.chain, asset, self.core, 'exact-in'))
            output += gross - fee
            fees['marketFeeCygld'] += fee
            retained.extend(left)
            result.append({'route': route, 'feeCygld': str(fee)})
        return result
    async def core_buy(lot, branch):
        nonlocal output
        payment = request['inputs'][0]['currency']
        allocated, acquired, acquisitions = 0, [], []
        positive = [i for i, weight in enumerate(weights) if weight]
        if selected is not None and [a.lower() for a in selected['body']['branches'][branch]['data']['basketAssets']] != [a.lower() for a in assets]:
            raise InvalidPreview('Selected Core basket order changed.')
        for index, asset in enumerate(assets):
            value = (int(selected['body']['branches'][branch]['data']['acquisitions'][index]['amountIn'])
                     if selected is not None else
                     lot - allocated if index == positive[-1] else lot * weights[index] // sum(weights))
            allocated += value
            route, received, left = await convert(payment, asset, value, branch=branch, stage=index, operation=f'{branch}:acquire:{index}')
            acquired.append(received)
            acquisitions.append({'amountIn': str(value), 'route': route})
            retained.extend(left)
        result = await self.core_preview('issue-exact-in', {'maximumAmountsIn': list(map(str, acquired))}, block)
        fees['coreProtocolFeeCygld'] += int(result['fees']['protocolFeeCygld'])
        fees['coreHelpersFeeCygld'] += int(result['fees']['helperFeeCygld'])
        output += int(result['netCygldOut'])
        residual = [a - int(b) for a, b in zip(acquired, result['amountsInExact'], strict=True)]
        tails = await continuation(residual, branch)
        return {'basketAssets': result['orderedCoreAssets'], 'acquisitions': acquisitions, 'continuations': tails}
    async def core_sell(lot, branch, basket=False):
        nonlocal output, recovery, recipient_outputs
        result = await self.core_preview('redeem-exact-in', {'grossCygldIn': str(lot)}, block)
        fees['coreProtocolFeeCygld'] += int(result['fees']['protocolFeeCygld'])
        fees['coreHelpersFeeCygld'] += int(result['fees']['helperFeeCygld'])
        expected, conversions = [], []
        for index, row in enumerate(result['projectedCoreOutputs']):
            expected.append(deepcopy(row))
            if basket:
                recipient_outputs.append(row)
            if row['kind'] != 0:
                if int(row['amount']): recovery.append(row)
                conversions.append(identity_template(row['token']))
                continue
            if basket:
                continue
            route, received, left = await convert(row['token'], request['outputCurrency'], int(row['amount']),
                                                  branch=branch, stage=index, operation=f'{branch}:redeem:{index}')
            output += received
            retained.extend(left)
            conversions.append(route)
        return {'expectedOutputs': expected, 'conversions': conversions}
    async def market(lot, branch):
        nonlocal output
        source = request['inputs'][0]['currency']
        target = request['outputCurrency']
        rate = get_market_fee_rate(self.engine.registry.chain, source, target, 'exact-in')
        _routed, fee, _dust = routed_sell_budget(lot, rate) if intent == 1 else (lot, 0, 0)
        routed = lot - fee if intent == 1 else lot
        route, gross, left = await convert(source, target, routed, market=True, branch=branch, operation=f'{branch}:market')
        if intent == 0:
            fee = quoted_fee(gross, rate)
        output += gross - (fee if intent == 0 else 0)
        fees['marketFeeCygld'] += fee
        retained.extend(left)
        return {'route': route, 'feeCygld': str(fee)}
    if intent in (0, 1):
        stages = ([('core' if row['kind'] == 0 else 'market', int(row['amountIn']))
                   for row in selected['allocations']] if selected is not None else
                  [('core', core_amount), ('market', market_amount)])
        if selected is None and order == 'market-first': stages.reverse()
        for kind, lot in stages:
            if not lot:
                continue
            index = len(branches)
            data = await (core_buy(lot, index) if intent == 0 else core_sell(lot, index)) if kind == 'core' else await market(lot, index)
            branches.append({'kind': 0 if kind == 'core' else 1, 'amountIn': str(lot), 'data': data})
        body = {'branches': branches}
    elif intent == 2:
        acquired = [int(row['amount']) for row in request['inputs']]
        result = await self.core_preview('issue-exact-in', {'maximumAmountsIn': list(map(str, acquired))}, block)
        fees['coreProtocolFeeCygld'] = int(result['fees']['protocolFeeCygld'])
        fees['coreHelpersFeeCygld'] = int(result['fees']['helperFeeCygld'])
        output += int(result['netCygldOut'])
        body = {'continuations': await continuation([a - int(b) for a, b in
            zip(acquired, result['amountsInExact'], strict=True)], 0)}
    else:
        body = await core_sell(amount, 0, basket=True)
    if intent != 3 and not output and not recovery:
        raise InvalidPreview('This scalar trade has no final output or recovery shares.')
    # Reduced funding can make a productive Core branch less than one percent.
    # Integer search-grid percentages must not relabel its actual execution.
    kinds = {row['kind'] for row in branches}
    family = ('mixed' if len(kinds) > 1 else 'market' if kinds == {1} else 'core')
    if intent in (0, 2) and has_continuation:
        family = 'mixed'
    return {'strategy': 'universal', 'routeFamily': family, 'operation': 'executeExactInput',
        'settlementPolicy': 'protocol-retained-input',
        'request': deepcopy(request),
        'plan': {'allocations': [{'kind': row['kind'], 'amountIn': row['amountIn']} for row in branches],
                 'conversions': recorded, 'body': body},
        'inputs': deepcopy(request['inputs']), 'quotedOutput': str(output),
        'conversionObservations': conversion_observations,
        **({'quotedInput': str(amount), 'inputMaximum': str(amount)} if intent != 2 else {}),
        'estimatedRetainedInputCharges': retained, 'fees': {key: str(value) for key, value in fees.items()},
        'estimatedRecipientOutputs': recipient_outputs if intent == 3 else [
            {'kind': 0, 'token': request['outputCurrency'], 'id': '0', 'amount': str(output)}],
        'retentionDisclosure': {'custodian': self.helpers, 'beneficiary': 'helpers-owner-at-settlement'},
        'recoveryShares': recovery, 'deployment': {'helpers': self.helpers, 'adapter': self.adapter,
            'encoding': ROUTING_ENCODING}, 'context': {'chainId': self.engine.registry.chain,
            'blockNumber': str(block['number']), 'blockHash': block['hash'], 'observedAt': self.now()},
        'searchCoverage': {'coreSharesPercent': list(CORE_SHARES), 'orders': ['core-first', 'market-first'],
                           'maxCoreInvocations': 1, 'maxAmmHops': 3, 'scope': 'selected-inventory'}}

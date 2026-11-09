"""Measured Core consumption supplies targets for whole funding alternatives.

Inverse and SDK amounts nominate complete bodies. Only the caller's ordinary
Helpers evaluation measures their economic result. One invocation traverses
its root observation's alternatives; derived quotes do not recurse here.
"""
from copy import deepcopy

from ..recovery_rpc import SnapshotChanged
from .evaluate import replay_conversion
from .funding import funding_proposal
from .inverse import inverse_conversion
from .plan_simulation import project_core_inputs
from .reuse_routes import proposal_identity


def _retaining(asset, core):
    template = {'inputCurrency': asset, 'outputCurrency': core, 'routes': []}
    return {'inputCurrency': asset, 'outputCurrency': core,
            'branches': [], 'template': template}


async def _replay(quoter, chosen, source, target, amount, block, bank, canonical):
    """Advance one private diagnostic bank in the body's execution order."""
    if not amount:
        return 0
    if source.lower() == target.lower():
        return amount
    if not chosen['branches']:
        return 0  # A retained continuation has no AMM operation to advance.
    _, output, _ = await replay_conversion(quoter, deepcopy(chosen), source, target,
                                           amount, block, bank, canonical)
    return output


async def _acquisition_bank(quoter, value, block, canonical):
    """Replay the explicit operations preceding Core's residual conversions."""
    request, plan = value['request'], value['plan']
    bank = {}
    if request['intent'] == 2:
        return bank
    source, core = request['inputs'][0]['currency'], request['outputCurrency']
    for branch, row in enumerate(plan['body']['branches']):
        if row['kind'] == 1:
            if not int(row['amountIn']):
                continue
            await _replay(quoter, plan['conversions'][f'{branch}:market'], source, core,
                          int(row['amountIn']), block, bank, canonical)
        else:
            for index, (asset, acquisition) in enumerate(zip(
                    row['data']['basketAssets'], row['data']['acquisitions'], strict=True)):
                if not int(acquisition['amountIn']) or source.lower() == asset.lower():
                    continue
                await _replay(quoter, plan['conversions'][f'{branch}:acquire:{index}'],
                              source, asset, int(acquisition['amountIn']), block, bank, canonical)
            return bank
    return bank


async def _sized(quoter, value, measured, residuals, block, canonical):
    request, original = value['request'], value['plan']
    source, core = request['inputs'][0]['currency'], request['outputCurrency']
    amounts, conversions, bank = {}, {}, {}
    rows = {(row['branch'], row['index']): row for row in measured}
    if request['intent'] == 2:
        inputs = []
        for index, row in enumerate(measured):
            useful, selected = residuals.get((row['branch'], row['index']), (0, None))
            inputs.append({'currency': row['currency'], 'amount': str(row['consumed'] + useful)})
            conversions[f'0:residual:{index}'] = selected or _retaining(row['currency'], core)
        return funding_proposal(request, original, conversions=conversions, inputs=inputs)
    for branch, row in enumerate(original['body']['branches']):
        if row['kind'] == 1:
            if not int(row['amountIn']):
                continue
            await _replay(quoter, original['conversions'][f'{branch}:market'], source, core,
                          int(row['amountIn']), block, bank, canonical)
            continue
        data = row['data']
        for index, (asset, acquisition) in enumerate(zip(data['basketAssets'], data['acquisitions'], strict=True)):
            observation = rows[(branch, index)]
            useful, continuation = residuals.get((branch, index), (0, None))
            desired = observation['consumed'] + useful
            operation = f'{branch}:acquire:{index}'
            if source.lower() == asset.lower() or not desired:
                amount = desired
                chosen = deepcopy(original['conversions'].get(operation))
            else:
                amount, chosen = await inverse_conversion(quoter, original['conversions'][operation],
                    source, asset, int(acquisition['amountIn']), desired, block, bank, canonical)
            amounts[operation] = amount
            if chosen is not None:
                conversions[operation] = chosen
            conversions[f'{branch}:residual:{index}'] = continuation or _retaining(asset, core)
        for index, asset in enumerate(data['basketAssets']):
            useful, _ = residuals.get((branch, index), (0, None))
            await _replay(quoter, conversions[f'{branch}:residual:{index}'], asset, core,
                          useful, block, bank, canonical)
    return funding_proposal(request, original, amounts=amounts, conversions=conversions)


async def _useful_residuals(quoter, value, measured, block, canonical):
    bank = await _acquisition_bank(quoter, value, block, canonical)
    result, core = {}, value['request']['outputCurrency']
    observed = {row['operation']: row for row in value.get('conversionObservations', ())}
    for row in measured:
        branch, index, asset, residual = row['branch'], row['index'], row['currency'], row['residual']
        if not residual:
            continue
        operation = f'{branch}:residual:{index}'
        chosen = {}
        try:
            await quoter.conversion(asset, core, residual, block, bank, canonical,
                                     market=True, capture=chosen)
            useful = int(chosen['_observation']['consumedInput'])
            chosen.pop('_observation', None)
            chosen.pop('_funding', None)
        except SnapshotChanged:
            raise
        except Exception:
            # An optional SDK failure cannot erase a successfully measured
            # sibling continuation; its existing body remains a nomination.
            old = observed.get(operation)
            if old is None:
                continue
            useful = int(old['consumedInput'])
            chosen = deepcopy(value['plan']['conversions'][operation])
        if useful:
            result[(branch, index)] = useful, chosen
    return result


async def compose_remaining_budget(quoter, value, proposal, measured, block, canonical):
    """Offer both orders of a fixed resized Core body and remaining-budget Market."""
    request, core = value['request'], value['request']['outputCurrency']
    if request['intent'] != 0:
        return
    core_branches = [(index, row) for index, row in enumerate(proposal['plan']['body']['branches'])
                     if row['kind'] == 0]
    if not core_branches:
        return
    old_index, body = core_branches[0]
    source = request['inputs'][0]['currency']
    remaining = int(request['inputs'][0]['amount']) - int(body['amountIn'])
    if remaining <= 0:
        return
    consumed = {row['index']: row['consumed'] for row in measured if row['branch'] == old_index}
    async def compose(core_first):
        bank, market = {}, {}
        if core_first:
            acquired = []
            for index, (asset, acquisition) in enumerate(zip(
                    body['data']['basketAssets'], body['data']['acquisitions'], strict=True)):
                chosen = proposal['plan']['conversions'].get(f'{old_index}:acquire:{index}')
                acquired.append(await _replay(quoter, chosen, source, asset,
                    int(acquisition['amountIn']), block, bank, canonical))
            for index, (asset, lot) in enumerate(zip(body['data']['basketAssets'], acquired, strict=True)):
                await _replay(quoter, proposal['plan']['conversions'][f'{old_index}:residual:{index}'],
                    asset, core, max(0, lot-consumed[index]), block, bank, canonical)
        route, _, _ = await quoter.conversion(source, core, remaining, block, bank, canonical,
                                              market=True, capture=market)
        market.pop('_observation', None)
        market_funding = market.pop('_funding', remaining)
        market_body = {'kind': 1, 'amountIn': str(market_funding), 'data': {'route': route, 'feeCygld': '0'}}
        core_index, market_index = (0, 1) if core_first else (1, 0)
        plan = {'body': {'branches': [deepcopy(body), market_body] if core_first else [market_body, deepcopy(body)]},
                'allocations': [], 'conversions': {}}
        plan['allocations'] = [{key: row[key] for key in ('kind', 'amountIn')}
                               for row in plan['body']['branches']]
        prefix = f'{old_index}:'
        plan['conversions'].update({f'{core_index}:{key[len(prefix):]}': deepcopy(chosen)
            for key, chosen in proposal['plan']['conversions'].items() if key.startswith(prefix)})
        plan['conversions'][f'{market_index}:market'] = market
        return {**funding_proposal(request, plan), 'phase': 'core-market-funding'}
    errors = []
    for core_first in (True, False):
        try:
            yield await compose(core_first)
        except SnapshotChanged:
            raise
        except Exception as error:
            errors.append(error)
    if errors:
        raise errors[0]


async def core_funding_alternatives(quoter, value, block, observations, *, core_only=False):
    """Yield one root's measured Core, useful residual and Market alternatives."""
    request = value['request']
    if request['intent'] not in (0, 2):
        return
    measured = project_core_inputs(value, quoter.engine.registry.chain)
    if not measured:
        return
    canonical = observations if observations is not None else {}
    seen = {proposal_identity({'inputs': value['inputs'], 'plan': value['plan']})}
    errors = []
    async def offer(proposal, phase):
        identity = proposal_identity(proposal)
        if identity in seen:
            return
        seen.add(identity)
        yield {**proposal, 'phase': phase}
        if request['intent'] == 0 and not core_only:
            try:
                async for composed in compose_remaining_budget(quoter, value, proposal, measured, block, canonical):
                    identity = proposal_identity(composed)
                    if identity not in seen:
                        seen.add(identity)
                        yield composed
            except SnapshotChanged:
                raise
            except Exception as error:
                errors.append(error)
    try:
        reduced = await _sized(quoter, value, measured, {}, block, canonical)
    except SnapshotChanged:
        raise
    except Exception as error:
        errors.append(error)
    else:
        # With unchanged funding, replacing an unused zero-lot continuation is
        # no sizing alternative and does not warrant another Helpers call.
        if reduced['inputs'] != value['inputs']:
            async for proposal in offer(reduced, 'core-consumption'):
                yield proposal
    try:
        residuals = await _useful_residuals(quoter, value, measured, block, canonical)
    except SnapshotChanged:
        raise
    except Exception as error:
        errors.append(error)
        residuals = {}
    if residuals:
        try:
            useful = await _sized(quoter, value, measured, residuals, block, canonical)
        except SnapshotChanged:
            raise
        except Exception as error:
            errors.append(error)
        else:
            async for proposal in offer(useful, 'useful-core-residual'):
                yield proposal
    if errors:
        raise errors[0]  # Preserve the ordinary owned optional-work diagnostic.

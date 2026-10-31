"""Immutable neighboring route blueprints and integer funding reconstruction.

These values only nominate exact candidates. They contain no historical pool
state, output/fee promise, transaction guard or executable calldata.
"""
from copy import deepcopy

from ..basket_preview import InvalidPreview
from ..uniswap_routes import PoolRef


def _conversion(value):
    """Keep execution topology, discarding observations and simulated state."""
    template = value.get('template')
    result = {key: value[key] for key in ('inputCurrency', 'outputCurrency')}
    result['branches'] = []
    for branch in value['branches']:
        hops = []
        for hop in branch['hops']:
            if 'pool' in hop:
                hops.append({'pool': PoolRef.model_validate(hop['pool']).model_dump(exclude_none=True),
                             'zeroForOne': hop['zeroForOne']})
            else:
                hops.append({key: hop[key] for key in ('kind', 'currencyOut')})
        result['branches'].append({'hops': hops})
    if template is not None:
        result['template'] = {key: deepcopy(template[key])
                              for key in ('inputCurrency', 'outputCurrency', 'routes')}
        # Execution guards do not belong to a reusable route, even when an
        # older response included them within a route template.
        for route in result['template']['routes']:
            for key in list(route):
                if key not in ('sharePpm', 'steps'):
                    del route[key]
    return result


def extract_blueprint(quote):
    """Extract scalar topology and allocation ratios from a completed quote."""
    request, plan = quote['request'], quote['plan']
    if request['intent'] not in (0, 1) or len(request['inputs']) != 1:
        raise InvalidPreview('Neighbor route reuse requires a scalar exact-input request.')
    result = {'intent': request['intent'], 'inputCurrency': request['inputs'][0]['currency'],
        'funding': int(quote['inputs'][0]['amount']), 'branches': []}
    for index, (allocation, body) in enumerate(zip(plan['allocations'], plan['body']['branches'], strict=True)):
        prefix = f'{index}:'
        branch = {'kind': allocation['kind'], 'weight': int(allocation['amountIn']),
            'conversions': {operation[len(prefix):]: _conversion(chosen)
                for operation, chosen in plan['conversions'].items() if operation.startswith(prefix)}}
        if allocation['kind'] == 0 and request['intent'] == 0:
            data = body['data']
            branch['assets'] = list(data['basketAssets'])
            branch['acquisitionWeights'] = [int(row['amountIn']) for row in data['acquisitions']]
        elif allocation['kind'] == 0:
            # Projected outputs may interleave ERC1155 shares with currencies;
            # asset identity, rather than a historical ordinal, selects a path.
            branch['redeemByAsset'] = {row['token'].lower(): branch['conversions'][f'redeem:{output_index}']
                for output_index, row in enumerate(body['data']['expectedOutputs'])
                if row['kind'] == 0 and f'redeem:{output_index}' in branch['conversions']}
        result['branches'].append(branch)
    return result


def _amounts(total, weights):
    """Floor preceding positive lots; give the last positive lot the remainder."""
    denominator = sum(weights)
    if total < 0 or denominator <= 0 or any(weight < 0 for weight in weights):
        raise InvalidPreview('Neighbor allocation has no positive funding ratio.')
    last = max(index for index, weight in enumerate(weights) if weight)
    result = [total * weight // denominator if weight else 0 for weight in weights]
    result[last] = total - sum(result[:last])
    return result


def resize_blueprint(blueprint, amount, assets):
    """Rebuild the complete selected plan at a new scalar funded amount."""
    lots = _amounts(int(amount), [branch['weight'] for branch in blueprint['branches']])
    plan = {'allocations': [], 'body': {'branches': []}, 'conversions': {}, 'assetConversions': {}}
    for old_branch, lot in zip(blueprint['branches'], lots, strict=True):
        if not lot:
            continue
        index = len(plan['allocations'])
        conversions = deepcopy(old_branch['conversions'])
        data = {}
        if old_branch['kind'] == 0 and blueprint['intent'] == 0:
            previous = old_branch['assets']
            if {asset.lower() for asset in previous} != {asset.lower() for asset in assets}:
                raise InvalidPreview('Neighbor Core basket asset set changed.')
            old_indices = {asset.lower(): position for position, asset in enumerate(previous)}
            positions = [old_indices[asset.lower()] for asset in assets]
            weights = [old_branch['acquisitionWeights'][position] for position in positions]
            acquisitions = _amounts(lot, weights)
            data = {'basketAssets': list(assets),
                'acquisitions': [{'amountIn': str(value)} for value in acquisitions]}
            conversions = {operation: chosen for operation, chosen in conversions.items()
                           if not operation.startswith(('acquire:', 'residual:'))}
            for role in ('acquire', 'residual'):
                for new_position, old_position in enumerate(positions):
                    chosen = old_branch['conversions'].get(f'{role}:{old_position}')
                    if chosen is not None:
                        conversions[f'{role}:{new_position}'] = deepcopy(chosen)
        elif old_branch['kind'] == 0:
            # Rebuilt Core sales always resolve by currency, so an output with
            # no prior route remains optional-unavailable instead of binding
            # accidentally to another asset's historical numeric key.
            conversions = {operation: chosen for operation, chosen in conversions.items()
                           if not operation.startswith('redeem:')}
            plan['assetConversions'][str(index)] = deepcopy(old_branch['redeemByAsset'])
        plan['allocations'].append({'kind': old_branch['kind'], 'amountIn': str(lot)})
        plan['body']['branches'].append({'kind': old_branch['kind'], 'amountIn': str(lot), 'data': data})
        plan['conversions'].update({f'{index}:{operation}': chosen for operation, chosen in conversions.items()})
    return plan


def selected_conversion(selected, operation, source):
    """Read rebuilt sale aliases, otherwise preserve ordinary selected replay."""
    branch, role, *_ = operation.split(':')
    aliases = selected.get('assetConversions', {})
    if role == 'redeem' and branch in aliases:
        return aliases[branch].get(source.lower())
    return selected['conversions'].get(operation)


def neighbor_proposals(quote, budget, assets):
    """Reprice fitting original funding before trying the larger budget.

    Upscaling can become unproductive or consume the selection window. Keep
    the already-fitting plan in contention first, without copying its old
    price or extending that window. Both proposals still use current state.
    """
    blueprint = extract_blueprint(quote)
    amounts = []
    if 0 < blueprint['funding'] < int(budget):
        amounts.append(blueprint['funding'])
    amounts.append(int(budget))
    return [{'plan': resize_blueprint(blueprint, amount, assets),
             'inputs': [{'currency': blueprint['inputCurrency'], 'amount': str(amount)}]}
            for amount in amounts]

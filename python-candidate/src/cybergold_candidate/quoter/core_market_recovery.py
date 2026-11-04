"""Try ready topology alternatives when a Core-produced market lot cannot settle.

A reverted remainder identifies a currency, never its original Core quantity.
Each nomination changes one implicated market leg in the same funded whole
plan. Only a complete Helpers success supplies amounts for ordinary exploration.
"""
from contextlib import aclosing
from copy import deepcopy

from .evaluate import encode_nomination


def implicated_core_market_operations(selected, unsettled):
    currency = unsettled['currency'].lower()
    implicated = []
    for operation, chosen in selected['conversions'].items():
        role = operation.split(':')[1]
        if role not in ('redeem', 'residual'):
            continue
        if chosen['inputCurrency'].lower() == currency or any(
                hop['pool']['token0' if hop['zeroForOne'] else 'token1']['address'].lower() == currency
                for row in chosen['branches'] for hop in row['hops'] if 'pool' in hop):
            implicated.append(operation)
    return implicated


async def core_market_proposals(quoter, request, selected, block, *, unsettled):
    for operation in implicated_core_market_operations(selected, unsettled):
        chosen = selected['conversions'][operation]
        branch, role, index = operation.split(':')
        source, target = chosen['inputCurrency'], chosen['outputCurrency']
        # No Core quantity is inferred here. This is the existing nominal
        # topology cohort, including its ready hosted/local tool alternatives.
        async with aclosing(quoter.amm.async_nominations(
                source, target, 1, block, market=role == 'residual')) as candidates:
            async for candidate in candidates:
                route, replacement = encode_nomination(source, target, candidate)
                plan = deepcopy(selected)
                plan['conversions'][operation] = replacement
                position = int(index)
                if request['intent'] == 2:
                    plan['body']['continuations'][position]['route'] = deepcopy(route)
                else:
                    data = plan['body']['branches'][int(branch)]['data']
                    if role == 'redeem':
                        data['conversions'][position] = deepcopy(route)
                        aliases = plan.get('assetConversions', {}).get(branch)
                        if aliases is not None:
                            aliases[source.lower()] = deepcopy(replacement)
                    else:
                        data['continuations'][position]['route'] = deepcopy(route)
                yield {'inputs': deepcopy(request['inputs']), 'plan': plan}

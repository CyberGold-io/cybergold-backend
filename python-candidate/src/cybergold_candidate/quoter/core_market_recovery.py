"""Try ready topology alternatives when a Core-produced market lot cannot settle.

A reverted remainder identifies a currency, never its original Core quantity.
Each nomination changes one implicated market leg in the same funded whole
plan. Only a complete Helpers success supplies amounts for ordinary exploration.
"""
from contextlib import aclosing
from copy import deepcopy

from .evaluate import encode_nomination
from .reuse_routes import proposal_identity
from ..recovery_rpc import SnapshotChanged


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


async def compose_core_market(quoter, request, selected, block, *, unsettled, attempt):
    """Follow paid whole-plan failures from the changed plan, then try siblings.

    Each iterator nominates only the implicated market leg. A second failing
    leg expands the changed complete body, preserving funding and Core fields.
    The owned stack avoids both a Cartesian product and Python recursion depth;
    a topology is tried once per recovery, while later provider passes remain
    free to expose new alternatives or retry ordinary failures.
    """
    seen = {proposal_identity({'inputs': request['inputs'], 'plan': selected})}
    stack = [core_market_proposals(quoter, request, selected, block, unsettled=unsettled)]
    try:
        while stack:
            try:
                proposal = await anext(stack[-1])
            except StopAsyncIteration:
                await stack.pop().aclose()
                continue
            except SnapshotChanged:
                raise
            except Exception:
                # An ordinary failed child feed does not exhaust its parent
                # alternatives. Cancellation and state disproof still retain
                # their own ordinary propagation contracts.
                await stack.pop().aclose()
                continue
            identity = proposal_identity(proposal)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                value = await attempt(proposal)
            except SnapshotChanged:
                raise
            except Exception as error:
                remainder = getattr(error, 'unsettled_intermediate', None)
                if remainder is not None:
                    stack.append(core_market_proposals(quoter, request, proposal['plan'], block,
                                                       unsettled=deepcopy(remainder)))
            else:
                if value is not None:
                    return value
    finally:
        for iterator in reversed(stack):
            await iterator.aclose()

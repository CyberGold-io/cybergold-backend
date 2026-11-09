"""Optional failed-plan funding nominations using the existing prefix kernel.

Only explicit funded AMM lots are replayed here. Core-produced quantities are
not inferred from old receipts or a revert remainder. Helpers validates every
complete repaired plan independently before it can become a quote.
"""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, quoted_fee, routed_sell_budget
from .amm import PartialPath
from .contracts import HopTrace, capture_paths, path_nomination, path_operation
from .evaluate import replay_conversion
from .prefix import backward_input
from .funding import funding_proposal


def scaled_funding(amount, branch_funded, repaired_branch_funded):
    """A proportional total nomination; retain the template's split weights.

    Integer allocation and shared-pool effects require complete forward replay,
    so this amount is not a fill boundary or a capacity certificate.
    """
    return int(amount) * int(repaired_branch_funded) // int(branch_funded)


def _remainder_hop(selected, unsettled):
    """Identify one linear downstream hop for the paid settlement remainder.

    Ambiguity only disables this diagnostic shortcut. Every path remains
    available to the ordinary forward diagnostic and independent search.
    """
    if unsettled is None:
        return None
    currency, matches = unsettled['currency'].lower(), []
    for operation, chosen in selected['conversions'].items():
        for branch in chosen['branches']:
            physical_index = 0
            for index, hop in enumerate(branch['hops']):
                if 'pool' not in hop:
                    continue
                source = hop['pool']['token0' if hop['zeroForOne'] else 'token1']['address']
                if physical_index > 0 and source.lower() == currency:
                    matches.append((operation, index, len(chosen['branches'])))
                physical_index += 1
    if len(matches) == 1 and matches[0][2] == 1:
        return matches[0][:2]
    return None


async def recover_selected(quoter, request, selected, block, observations, *, unsettled=None):
    """Return changed complete plans after a caller's failed Helpers attempt.

    Traverse known explicit-funded operations in execution order, retaining one
    private bank across split branches, acquisitions and Market operations.
    An unknown Core-produced AMM lot ends this diagnostic prefix; it does not
    exclude the original plan or any other search work.
    """
    plan = deepcopy(selected)
    bank, canonical = {}, observations if observations is not None else {}
    source = request['inputs'][0]['currency']
    remainder_hop = _remainder_hop(plan, unsettled)

    async def conversion(operation, amount, chosen):
        # The existing path producer acquires fresh immutable observations;
        # copying its selected topology needs no additional metadata contract.
        chosen = deepcopy(chosen)
        with capture_paths() as traces, path_operation(operation, int(operation.split(':')[0]), 0):
            try:
                if remainder_hop is not None and remainder_hop[0] == operation:
                    index = remainder_hop[1]
                    route = chosen['branches'][0]['hops']
                    before = deepcopy(bank)
                    with path_nomination(chosen['inputCurrency'], chosen.get('discoveryOrigins', ())):
                        _, output = await quoter.price_path(route[:index], amount, block, bank, canonical)
                    consumed = output - int(unsettled['amount'])
                    if consumed > 0:
                        trace = traces[-1]
                        trace.route = deepcopy(route)
                        trace.hops.append(HopTrace(deepcopy(route[index]), output, consumed, 0, None))
                        target = await backward_input(quoter, trace)
                        return False, (scaled_funding(amount, trace.funded, target)
                                       if target is not None else None)
                    # Latest-state prefix output can differ from the paid
                    # failed call. Fall back without inventing consumed input.
                    bank.clear()
                    bank.update(before)
                await replay_conversion(quoter, chosen, chosen['inputCurrency'], chosen['outputCurrency'],
                                        amount, block, bank, canonical)
            except PartialPath as partial:
                target = await backward_input(quoter, partial.trace)
                return False, (scaled_funding(amount, partial.trace.funded, target)
                               if target is not None else None)
        return True, None

    def proposal(operation, amount):
        return [funding_proposal(request, plan, {operation: amount})]

    for index, branch in enumerate(plan['body']['branches']):
        if branch['kind'] == 1:
            operation = f'{index}:market'
            amount = int(branch['amountIn'])
            if not amount:
                continue
            rate = get_market_fee_rate(quoter.engine.registry.chain, source, request['outputCurrency'], 'exact-in')
            routed = amount - routed_sell_budget(amount, rate)[1] if request['intent'] == 1 else amount
            settled, reduced = await conversion(operation, routed, plan['conversions'][operation])
            if not settled:
                if reduced is not None and 0 < reduced < routed:
                    funded = reduced + quoted_fee(reduced, rate) if request['intent'] == 1 else reduced
                    return proposal(operation, funded)
                return []
        elif request['intent'] == 0:
            data = branch['data']
            for asset_index, acquisition in enumerate(data['acquisitions']):
                operation = f'{index}:acquire:{asset_index}'
                amount = int(acquisition['amountIn'])
                if not amount or source.lower() == data['basketAssets'][asset_index].lower():
                    continue
                settled, reduced = await conversion(operation, amount, plan['conversions'][operation])
                if not settled:
                    if reduced is not None and 0 < reduced < amount:
                        return proposal(operation, reduced)
                    return []
            if any(row['route']['routes'] for row in data['continuations']):
                # Actual residual lots are produced inside Core/Helpers. Do not
                # advance later pools using historical or nominal quantities.
                return []
        else:
            # Core redemption produces its actual currency/share lots at call
            # time; an old expected-output vector supplies identities only.
            return []
    return []

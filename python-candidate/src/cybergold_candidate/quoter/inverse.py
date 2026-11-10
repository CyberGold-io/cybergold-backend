"""Advisory target-output pricing over the existing ordered SDK path kernel."""
from copy import deepcopy

from ..pool_snapshot import copy_pool_bank
from ..route_work_slots import engine_work
from ..routing_encoding import exact_output_routes, split_runtime
from ..uniswap_routes import pool_identity
from .contracts import capture_paths
from .evaluate import replay_conversion
from .reuse_routes import _amounts


async def inverse_hops(quoter, hops, desired):
    """Walk physical pool occurrences backward at their captured private states."""
    target = int(desired)
    if not target:
        return 0
    for row in reversed(hops):
        pool = deepcopy(row.pre_state)
        async with engine_work(quoter.engine.semaphore):
            value = await quoter.engine.sdk.request({'operation': 'quote', 'pools': [pool],
                'poolId': pool['id'], 'mode': 'exactOut', 'amount': str(target),
                'zeroForOne': row.hop['zeroForOne']})
        target = int(value['amountIn'])
    return target


async def inverse_conversion(quoter, chosen, source, target, funded, desired, block, bank, canonical):
    """Nominate new split funding, then advance a private bank by forward replay.

    Helpers reports aggregate conversions. Diagnostic path replay supplies the
    output proportions and each occurrence's pre-swap state. Exact-output SDK
    pricing includes pool fees; ceiling funding preserves each required path
    input after ppm encoding. Only complete Helpers execution validates the
    resulting whole-plan economics.
    """
    selected = deepcopy(chosen)
    if not desired or source.lower() == target.lower():
        return int(desired), selected
    preceding = copy_pool_bank(bank)
    physical = [hop['pool'] for branch in selected['branches']
                for hop in branch['hops'] if 'pool' in hop]
    if (len(selected['branches']) == 1 and physical
            and len(physical) == len(selected['branches'][0]['hops'])
            and len({pool_identity(pool) for pool in physical}) == len(physical)):
        # One simple path needs only its target-output quote. There is no
        # split-output proportion to recover from the original larger input.
        branches = [{**deepcopy(selected['branches'][0]), 'amountIn': str(desired)}]
        async with engine_work(quoter.engine.semaphore):
            quoted = await quoter.engine.quote_sdk_branches(branches, 'exactOut', int(desired), block,
                candidate=copy_pool_bank(preceding), canonical=canonical)
        amount = int(quoted['amountIn'])
        selected['branches'][0]['amountIn'] = str(amount)
        advanced = copy_pool_bank(preceding)
        await replay_conversion(quoter, selected, source, target, amount, block, advanced, canonical)
        selected.pop('_observation', None)
        selected.pop('_funding', None)
        bank.clear()
        bank.update(advanced)
        return amount, selected
    with capture_paths() as traces:
        await replay_conversion(quoter, selected, source, target, int(funded), block,
                                copy_pool_bank(preceding), canonical)
    targets = _amounts(int(desired), [trace.output for trace in traces])
    amounts = [await inverse_hops(quoter, trace.hops, amount)
               for trace, amount in zip(traces, targets, strict=True)]
    branches = [{**deepcopy(branch), 'amountIn': str(amount)}
                for branch, amount in zip(selected['branches'], amounts, strict=True)]
    amount, selected['template']['routes'] = exact_output_routes(branches)
    selected['branches'] = branches
    advanced = copy_pool_bank(preceding)
    await replay_conversion(quoter, selected, source, target, amount, block, advanced, canonical)
    for branch, funded in zip(selected['branches'], split_runtime(amount, selected['template']['routes']), strict=True):
        branch['amountIn'] = str(funded)
    selected.pop('_observation', None)
    bank.clear()
    bank.update(advanced)
    return amount, selected

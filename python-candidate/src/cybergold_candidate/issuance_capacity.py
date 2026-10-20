"""Core's unclipped issuance calculation from the quoted basket at one block."""
import asyncio

from web3 import Web3

from .quote_errors import rpc_failure
from .basket_arithmetic import gross_for_net
from .capacity_cache import core_capacity_facts
from .preview_errors import KnownPreviewError
from .shared_reads import discard_pool_observation

PPM, FP = 1_000_000, 10**18
CORE_READS = [('basketTargetsPpm', 'uint256[]'), ('basketCygldPerUnitFp18', 'uint256[]'),
              ('issuanceFeePpm', 'uint256'), ('totalSupply', 'uint256'),
              ('maxTotalSupply', 'uint256'), ('effectiveCygldSupplyCap', 'uint256')]
READS = CORE_READS + [('helperFeePpm', 'uint256')]
SUPPLY_READS = CORE_READS[3:]
ABI = [{'type': 'function', 'name': name, 'stateMutability': 'view', 'inputs': [],
        'outputs': [{'type': output}]} for name, output in READS]


def capacity_amounts(request, outputs, values):
    weights, conversions, issue_fee, supply, maximum, effective, helper_fee = values
    amounts = {target['outputAsset'].lower(): int(output)
               for target, output in zip(request['targets'], outputs, strict=True)}
    direct = int(request['amount']) - sum(int(target['amount']) for target in request['targets'])
    amounts[request['quoteToken'].lower()] = direct
    gross = min((amounts.get(asset.lower(), 0) * conversion // FP) * PPM // weight
                for asset, conversion, weight in zip(request['orderedAssets'], conversions, weights, strict=True)
                if weight)
    available = core_capacity_facts((supply, maximum, effective), issue_fee, helper_fee)
    def net(value):
        core_net = value - value * issue_fee // PPM
        return core_net - core_net * helper_fee // PPM
    requested_net = net(gross)
    # Fee floors can give the same recipient net for several budget-supported
    # gross amounts. Match the exact-output executor's canonical mint amount.
    requested_gross = gross_for_net(gross_for_net(requested_net, helper_fee), issue_fee) if requested_net else 0
    return {'requestedGrossCygldOut': str(requested_gross), 'requestedNetCygldOut': str(requested_net),
            'remainingGrossCapacity': available['remainingGrossCapacity'],
            'remainingNetCapacity': available['remainingNetCapacity']}


async def _read_values(rpc, settings, block, reads, metrics=None, *, shared=False):
    contract = rpc.w3.eth.contract(abi=ABI)
    core = Web3.to_checksum_address(settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
    calls = [(Web3.to_checksum_address(settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
              if name == 'helperFeePpm' else core, contract.encode_abi(name)) for name, _ in reads]
    if shared:
        counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
        rows, _ = await rpc.pool_batch(calls, block, counts)
        if metrics is not None:
            for name, field in (('rpcReads', 'issued'), ('rpcReadsRequested', 'requested'),
                                ('rpcReadsCoalesced', 'coalesced'), ('rpcReadsReused', 'reused')):
                metrics[name] += counts[field]
    else:
        if metrics is not None:
            metrics['rpcReads'] += len(calls)
            metrics['rpcReadsRequested'] += len(calls)
        if hasattr(rpc, 'call_batch'):
            rows = await rpc.call_batch(calls, block)
        else:
            tasks = [asyncio.create_task(rpc.w3.provider.make_request('eth_call', [
                {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}]))
                for address, data in calls]
            try:
                rows = await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    values = []
    for call, (_, output), row in zip(calls, reads, rows, strict=True):
        if 'error' in row:
            raise rpc_failure(row['error'])
        try:
            values.append(rpc.w3.codec.decode([output], bytes.fromhex(row['result'][2:]))[0])
        except Exception:
            if shared:
                discard_pool_observation(rpc, call, block)
            raise
    return values


async def read_supply_capacity(rpc, settings, block, metrics=None, *, shared=False):
    """The three authoritative supply limits, from the request's pinned block."""
    return tuple(await _read_values(rpc, settings, block, SUPPLY_READS, metrics, shared=shared))


def exhausted_capacity_error(values):
    available = core_capacity_facts(values)
    if available['remainingGrossCapacity'] != '0':
        return None
    return KnownPreviewError('issuance-cap-exceeded',
        'No CYGLD issuance capacity remains. Core cannot issue additional CYGLD.',
        constraint={'kind': 'issuance-cap', 'quantity': 'gross-cygld-mint',
                    'limitKind': available['limitKind'], 'availableRaw': '0',
                    'currentSupplyRaw': available['currentSupplyRaw'], 'limitRaw': available['limitRaw']})


async def read_capacity(rpc, settings, block, metrics, *, shared=False, supply_values=None):
    if supply_values is None:
        return await _read_values(rpc, settings, block, READS, metrics, shared=shared)
    values = await _read_values(rpc, settings, block, READS[:3] + READS[6:], metrics, shared=shared)
    return values[:3] + list(supply_values) + values[3:]

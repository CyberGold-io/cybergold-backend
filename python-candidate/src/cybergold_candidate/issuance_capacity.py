"""Core's unclipped issuance calculation from the quoted basket at one block."""
from web3 import Web3

from .quote_errors import rpc_failure
from .basket_arithmetic import gross_for_net

PPM, FP = 1_000_000, 10**18
CORE_READS = [('basketTargetsPpm', 'uint256[]'), ('basketCygldPerUnitFp18', 'uint256[]'),
              ('issuanceFeePpm', 'uint256'), ('totalSupply', 'uint256'),
              ('maxTotalSupply', 'uint256'), ('effectiveCygldSupplyCap', 'uint256')]
READS = CORE_READS + [('helperFeePpm', 'uint256')]
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
    remaining = max(0, min(maximum, effective) - supply)
    def net(value):
        core_net = value - value * issue_fee // PPM
        return core_net - core_net * helper_fee // PPM
    requested_net = net(gross)
    # Fee floors can give the same recipient net for several budget-supported
    # gross amounts. Match the exact-output executor's canonical mint amount.
    requested_gross = gross_for_net(gross_for_net(requested_net, helper_fee), issue_fee) if requested_net else 0
    return {'requestedGrossCygldOut': str(requested_gross), 'requestedNetCygldOut': str(requested_net),
            'remainingGrossCapacity': str(remaining), 'remainingNetCapacity': str(net(remaining))}


async def read_capacity(rpc, settings, block, metrics):
    contract = rpc.w3.eth.contract(abi=ABI)
    core = Web3.to_checksum_address(settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
    helpers = Web3.to_checksum_address(settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
    calls = [(core if name != 'helperFeePpm' else helpers, contract.encode_abi(name)) for name, _ in READS]
    metrics['rpcReads'] += len(calls)
    metrics['rpcReadsRequested'] += len(calls)
    rows = await rpc.call_batch(calls, block)
    values = []
    for (_, output), row in zip(READS, rows, strict=True):
        if 'error' in row:
            raise rpc_failure(row['error'])
        values.append(rpc.w3.codec.decode([output], bytes.fromhex(row['result'][2:]))[0])
    return values

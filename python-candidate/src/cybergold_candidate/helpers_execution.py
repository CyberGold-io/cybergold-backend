"""Simulate and estimate the Helpers Swap operations used by the Apps."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Literal

from eth_utils.abi import collapse_if_tuple
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .safe_transaction import Address, UInt
from .transaction_nonce import NonceRpc
from .quote_errors import rpc_failure
from .preview_errors import preview_error
from .rpc_diagnostics import error_diagnostics, rpc_call

ABI = json.loads(Path(__file__).with_name('helpers-execution-abi.json').read_text())
# Public identities from the Helpers basket-router errors; no return arguments
# or signature/calldata bytes are retained in diagnostics.
REVERT_NAMES = {Web3.to_hex(Web3.keccak(text=signature))[:10]:
    (signature.split('(')[0], signature.partition('(')[2][:-1].split(',') if not signature.endswith('()') else [])
    for signature in ('ZeroInputAmount()', 'InsufficientInput()', 'InsufficientOutput(uint256,uint256)',
        'PermitExpired(uint256,uint256)', 'PermitAmountTooLow(uint256,uint256)',
        'PermitAllowanceTooLow(uint256,uint256)', 'Permit2AmountTooLow(uint256,uint256)',
        'NativeValueMismatch(uint256,uint256)', 'AdapterNotApproved(address)',
        'CoreInputAboveMaximum(address,uint256,uint256)', 'Error(string)', 'Panic(uint256)')}
Operation = Literal['issueFromBasketExactOutWithMixedPermits', 'issueFromBasketExactOutWithPermit2', 'issueFromNativeExactOut', 'issueFromTokenExactOut', 'issueFromTokenExactOutWithPermit', 'issueFromTokenExactOutWithPermit2', 'swapExactOutput', 'executeExactInput']


class HelpersExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    owner: Address
    operation: Operation
    args: list[Any]
    value: UInt | None = None


def argument(value, parameter):
    """Restore decimal JSON amounts through the shipped ABI's concrete types."""
    array = re.fullmatch(r'(.*)\[([0-9]*)\]', parameter['type'])
    if array:
        return [argument(item, {**parameter, 'type': array[1]}) for item in value]
    if parameter['type'] == 'tuple':
        components = parameter['components']
        return [argument(value[part['name']] if isinstance(value, dict) else value[index], part)
                for index, part in enumerate(components)]
    if parameter['type'].startswith(('uint', 'int')):
        return int(value)
    if parameter['type'] == 'address':
        return Web3.to_checksum_address(value)
    return value


class HelpersExecutionRpc(NonceRpc):
    async def execution_read(self, method, params, stage):
        try:
            # The outer context retains this operation's stage if its backend
            # deadline cancels the transport before an RPC exception exists.
            with rpc_call(method, stage=stage):
                result = await self.w3.provider.make_request(method, params)
        except Exception as error:
            diagnostics = error_diagnostics(error)
            if diagnostics:
                error.rpc_diagnostics = {**diagnostics, 'stage': stage}
            raise
        if 'error' in result:
            upstream = result['error']
            error = preview_error(upstream) or rpc_failure(upstream)
            diagnostics = {**(error_diagnostics(upstream) or {}), 'stage': stage, 'rpcMethod': method}
            data = upstream.get('data')
            if isinstance(data, str) and re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){4,}', data):
                selector = data[:10].lower()
                diagnostics['errorSelector'] = selector
                if selector in REVERT_NAMES:
                    name, types = REVERT_NAMES[selector]
                    try:
                        self.w3.codec.decode(types, bytes.fromhex(data[10:]))
                        diagnostics['errorName'] = name
                    except Exception:
                        pass  # Unknown/malformed arguments retain selector only.
            error.rpc_diagnostics = diagnostics
            raise error
        return result

    async def estimate(self, helpers, payload):
        method = next(row for row in ABI if row['name'] == payload.operation)
        args = [argument(value, parameter) for value, parameter in zip(payload.args, method['inputs'], strict=True)]
        data = self.w3.eth.contract(abi=ABI).encode_abi(payload.operation, args=args)
        transaction = {'from': Web3.to_checksum_address(payload.owner), 'to': Web3.to_checksum_address(helpers), 'data': data}
        if payload.value is not None:
            transaction['value'] = hex(int(payload.value))
        # The existing fee hint first simulates, then estimates latest state.
        # Native reverts and ABI decoding errors retain that ordering.
        result = await self.execution_read('eth_call', [transaction, 'latest'], 'helpers-simulation')
        self.w3.codec.decode([collapse_if_tuple(output) for output in method['outputs']], bytes.fromhex(result['result'][2:]))
        result = await self.execution_read('eth_estimateGas', [transaction], 'helpers-gas-estimation')
        return int(result['result'], 16)


class HelpersExecution:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, payload):
        if self.rpc is None:
            self.rpc = HelpersExecutionRpc(self.settings)
        helpers = getattr(self.settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS', os.environ.get('NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            gas = await self.rpc.estimate(helpers, payload)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'helpers': helpers, 'owner': Web3.to_checksum_address(payload.owner),
                'operation': payload.operation, 'gas': str(gas), 'blockTag': 'latest'}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_helpers_execution(request, service):
    try:
        payload = HelpersExecutionRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A supported Swap execution request is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(payload)) if service else None
    return await handle_protocol_facts(request, bound, 'helpers-execution',
                                       'Swap execution fee simulation is temporarily unavailable.')

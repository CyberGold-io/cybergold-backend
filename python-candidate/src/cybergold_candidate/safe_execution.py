"""Simulate the App's exact Safe execution, without signing or submitting."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .safe_transaction import Address, SafeAddressRequest, UInt
from .transaction_nonce import NonceRpc

Bytes = Annotated[str, StringConstraints(pattern=r'^0x(?:[0-9a-fA-F]{2})*$')]
ABI = [{'type': 'function', 'name': 'execTransaction', 'stateMutability': 'payable',
        'inputs': [{'name': name, 'type': kind} for name, kind in (
            ('to', 'address'), ('value', 'uint256'), ('data', 'bytes'), ('operation', 'uint8'),
            ('safeTxGas', 'uint256'), ('baseGas', 'uint256'), ('gasPrice', 'uint256'),
            ('gasToken', 'address'), ('refundReceiver', 'address'), ('signatures', 'bytes'))],
        'outputs': [{'name': 'success', 'type': 'bool'}]}]


class SafeExecutionRequest(SafeAddressRequest):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    executor: Address
    executorNonce: UInt
    to: Address
    value: UInt
    data: Bytes
    operation: int
    safeTxGas: UInt
    baseGas: UInt
    gasPrice: UInt
    gasToken: Address
    refundReceiver: Address
    signatures: Bytes

    def arguments(self):
        return [Web3.to_checksum_address(self.to), int(self.value), self.data, self.operation,
                int(self.safeTxGas), int(self.baseGas), int(self.gasPrice),
                Web3.to_checksum_address(self.gasToken), Web3.to_checksum_address(self.refundReceiver),
                self.signatures]


class SafeExecutionRpc(NonceRpc):
    async def simulate(self, payload):
        data = self.w3.eth.contract(abi=ABI).encode_abi('execTransaction', args=payload.arguments())
        # Preserve Viem's latest-state simulation, including the executor's
        # pending nonce. The canonical head context does not reserve execution.
        result = await self.w3.provider.make_request('eth_call', [{
            'from': Web3.to_checksum_address(payload.executor),
            'to': Web3.to_checksum_address(payload.address), 'data': data,
            'nonce': hex(int(payload.executorNonce))}, 'latest'])
        if 'error' in result:
            raise ValueError('Safe execution simulation failed')
        return self.w3.codec.decode(['bool'], bytes.fromhex(result['result'][2:]))[0]


class SafeExecution:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, payload):
        if self.rpc is None:
            self.rpc = SafeExecutionRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            success = await self.rpc.simulate(payload)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'address': Web3.to_checksum_address(payload.address),
                'executor': Web3.to_checksum_address(payload.executor), 'executorNonce': payload.executorNonce,
                'success': success, 'blockTag': 'latest'}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_safe_execution(request, service):
    try:
        payload = SafeExecutionRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A valid Safe execution simulation is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(payload)) if service else None
    return await handle_protocol_facts(request, bound, 'safe-execution',
                                       'Safe execution simulation is temporarily unavailable.')

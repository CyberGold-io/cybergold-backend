"""The Apps' two fresh Safe transaction reads; never signs or submits."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc

Address = Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]
UInt = Annotated[str, StringConstraints(pattern=r'^[0-9]+$')]

ABI = [
    {'type': 'function', 'name': 'nonce', 'stateMutability': 'view',
     'inputs': [], 'outputs': [{'name': '', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getTransactionHash', 'stateMutability': 'view',
     'inputs': [{'name': name, 'type': kind} for name, kind in (
         ('to', 'address'), ('value', 'uint256'), ('data', 'bytes'), ('operation', 'uint8'),
         ('safeTxGas', 'uint256'), ('baseGas', 'uint256'), ('gasPrice', 'uint256'),
         ('gasToken', 'address'), ('refundReceiver', 'address'), ('nonce', 'uint256'))],
     'outputs': [{'name': '', 'type': 'bytes32'}]},
]


class SafeAddressRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    address: Address


class SafeHashRequest(SafeAddressRequest):
    to: Address
    value: UInt
    data: Annotated[str, StringConstraints(pattern=r'^0x(?:[0-9a-fA-F]{2})*$')]
    operation: int
    safeTxGas: UInt
    baseGas: UInt
    gasPrice: UInt
    gasToken: Address
    refundReceiver: Address
    nonce: UInt

    def arguments(self):
        # Standard ABI encoding enforces the native uint8/uint256 ranges.
        return [Web3.to_checksum_address(self.to), int(self.value), self.data, self.operation,
                int(self.safeTxGas), int(self.baseGas), int(self.gasPrice),
                Web3.to_checksum_address(self.gasToken), Web3.to_checksum_address(self.refundReceiver),
                int(self.nonce)]


class SafeTransactionRpc(NonceRpc):
    async def read(self, address, name, arguments, block):
        contract = self.w3.eth.contract(abi=ABI)
        data = contract.encode_abi(name, args=arguments)
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': Web3.to_hex(block['hash']), 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Safe transaction read failed')
        output = 'uint256' if name == 'nonce' else 'bytes32'
        return self.w3.codec.decode([output], bytes.fromhex(response['result'][2:]))[0]


class SafeTransaction:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, address, payload=None):
        if self.rpc is None:
            self.rpc = SafeTransactionRpc(self.settings)
        address = Web3.to_checksum_address(address)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            value = await self.rpc.read(address, 'nonce' if payload is None else 'getTransactionHash',
                                        [] if payload is None else payload.arguments(), block)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']),
                'observedAt': self.now()}, 'address': address,
                **({'nonce': str(value)} if payload is None else {'safeTxHash': Web3.to_hex(value)})}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_safe_transaction(request, service, hash_request=False):
    try:
        value = (SafeHashRequest.model_validate(await request.json()) if hash_request else
                 SafeAddressRequest.model_validate(dict(request.query_params)))
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A valid Safe transaction request is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(value.address, value if hash_request else None)) if service else None
    return await handle_protocol_facts(request, bound, 'safe-transaction',
                                       'Safe transaction observations are temporarily unavailable.')

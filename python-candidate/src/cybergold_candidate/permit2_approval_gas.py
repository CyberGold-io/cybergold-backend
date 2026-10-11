"""Estimate the App's exact ERC20 approval of its configured Permit2 spender."""
import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc

Address = Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]
HELPERS_ABI = [{'type': 'function', 'name': 'permit2', 'inputs': [],
                'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view'}]
TOKEN_ABI = [{'type': 'function', 'name': 'approve', 'stateMutability': 'nonpayable',
              'inputs': [{'name': 'spender', 'type': 'address'}, {'name': 'amount', 'type': 'uint256'}],
              'outputs': [{'name': '', 'type': 'bool'}]}]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    owner: Address
    token: Address


class Permit2ApprovalGasRpc(NonceRpc):
    async def estimate(self, helpers, payload, block):
        data = self.w3.eth.contract(abi=HELPERS_ABI).encode_abi('permit2')
        result = await self.w3.provider.make_request('eth_call', [
            {'to': helpers, 'data': data}, {'blockHash': Web3.to_hex(block['hash']), 'requireCanonical': True}])
        if 'error' in result:
            raise ValueError('Configured Permit2 read failed')
        permit2 = Web3.to_checksum_address(self.w3.codec.decode(['address'], bytes.fromhex(result['result'][2:]))[0])
        data = self.w3.eth.contract(abi=TOKEN_ABI).encode_abi('approve', args=[permit2, 2**256-1])
        # Native latest-state gas estimation retains the App's original behavior.
        # It is an observation, never a gas reservation or an executed approval.
        result = await self.w3.provider.make_request('eth_estimateGas', [{
            'from': Web3.to_checksum_address(payload.owner), 'to': Web3.to_checksum_address(payload.token), 'data': data}])
        if 'error' in result:
            raise ValueError('Permit2 approval gas estimation failed')
        return permit2, int(result['result'], 16)


class Permit2ApprovalGas:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, payload):
        if self.rpc is None:
            self.rpc = Permit2ApprovalGasRpc(self.settings)
        helpers = getattr(self.settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS', os.environ.get('NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            permit2, gas = await self.rpc.estimate(helpers, payload, block)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'owner': Web3.to_checksum_address(payload.owner), 'token': Web3.to_checksum_address(payload.token),
                'permit2': permit2, 'gas': str(gas), 'blockTag': 'latest'}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_permit2_approval_gas(request, service):
    try:
        payload = ApprovalRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A valid token and owner are required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(payload)) if service else None
    return await handle_protocol_facts(request, bound, 'permit2-approval-gas',
                                       'Permit2 approval gas estimation is unavailable.')

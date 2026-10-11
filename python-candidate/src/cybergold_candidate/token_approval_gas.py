"""Exact selected-token approval gas observation for configured Helpers."""
import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from web3 import Web3

from .permit2_approval_gas import TOKEN_ABI
from .protocol_facts import handle_protocol_facts
from .safe_transaction import Address, UInt
from .transaction_nonce import NonceRpc
from .quote_errors import rpc_failure


class TokenApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    owner: Address
    token: Address
    amount: UInt


class TokenApprovalRpc(NonceRpc):
    async def estimate(self, helpers, payload):
        data = self.w3.eth.contract(abi=TOKEN_ABI).encode_abi('approve', args=[helpers, int(payload.amount)])
        response = await self.w3.provider.make_request('eth_estimateGas', [{
            'from': Web3.to_checksum_address(payload.owner), 'to': Web3.to_checksum_address(payload.token), 'data': data}])
        if 'error' in response:
            raise rpc_failure(response['error'])
        return int(response['result'], 16)


class TokenApprovalGas:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, payload):
        if self.rpc is None:
            self.rpc = TokenApprovalRpc(self.settings)
        helpers = Web3.to_checksum_address(getattr(self.settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS',
                                                   os.environ.get('NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS')))
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            gas = await self.rpc.estimate(helpers, payload)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'owner': Web3.to_checksum_address(payload.owner), 'token': Web3.to_checksum_address(payload.token),
                'amount': payload.amount, 'spender': helpers, 'gas': str(gas), 'blockTag': 'latest'}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_token_approval_gas(request, service):
    try:
        payload = TokenApprovalRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A valid token, owner and unsigned amount are required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(payload)) if service else None
    return await handle_protocol_facts(request, bound, 'token-approval-gas', 'Token approval gas estimation is unavailable.')

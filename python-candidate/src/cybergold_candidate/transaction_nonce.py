"""Fresh pending account nonce for the App's Governance transaction flows."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import AsyncWeb3, Web3

from .protocol_facts import handle_protocol_facts
from .rpc_transport import rpc_provider


class NonceRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    owner: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class NonceRpc:
    def __init__(self, settings, w3=None):
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))

    async def block(self):
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        return await self.w3.eth.get_block('latest')

    async def pending_nonce(self, owner):
        return await self.w3.eth.get_transaction_count(owner, 'pending')

    async def assert_canonical(self, block):
        current = await self.w3.eth.get_block(block['number'])
        if current['hash'] != block['hash']:
            raise ValueError('Nonce observation head changed')

    async def close(self):
        await self.w3.provider.disconnect()


class TransactionNonce:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, owner):
        if self.rpc is None:
            self.rpc = NonceRpc(self.settings)
        owner = Web3.to_checksum_address(owner)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            # Pending state is a fresh provider observation, not an EIP-1898
            # block-pinned contract read or a server-side nonce reservation.
            nonce = await self.rpc.pending_nonce(owner)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                    'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']),
                    'observedAt': self.now()}, 'owner': owner, 'blockTag': 'pending', 'nonce': str(nonce)}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_transaction_nonce(request, service):
    try:
        owner = NonceRequest.model_validate(dict(request.query_params)).owner
    except ValidationError:
        return JSONResponse({'error': 'A valid owner address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(owner)) if service else None
    return await handle_protocol_facts(request, bound, 'transaction-nonce',
                                       'Pending transaction nonce is temporarily unavailable.')

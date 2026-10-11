"""Fresh receipt facts used by the Apps' Safe execution history."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import AsyncWeb3, Web3
from web3.exceptions import TransactionNotFound

from .protocol_facts import handle_protocol_facts
from .rpc_transport import rpc_provider


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    hash: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{64}$')]


class ReceiptRpc:
    def __init__(self, settings, w3=None):
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))

    async def receipt(self, transaction_hash):
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        try:
            return await self.w3.eth.get_transaction_receipt(transaction_hash)
        except TransactionNotFound:
            # Native null/absence is unknown. Provider/transport failures are
            # ordinary errors, not evidence of pending/replaced/cancelled state.
            return None

    async def close(self):
        await self.w3.provider.disconnect()


class TransactionReceipt:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, transaction_hash):
        if self.rpc is None:
            self.rpc = ReceiptRpc(self.settings)
        async with asyncio.timeout(15):
            value = await self.rpc.receipt(transaction_hash)
            receipt = None if value is None else {
                'transactionHash': Web3.to_hex(value['transactionHash']),
                'blockHash': Web3.to_hex(value['blockHash']), 'blockNumber': str(value['blockNumber']),
                'status': {0: 'reverted', 1: 'success'}[value['status']],
                'logs': [{'address': row['address'], 'data': Web3.to_hex(row['data']),
                          'topics': [Web3.to_hex(topic) for topic in row['topics']]} for row in value['logs']]}
            return {'chainId': self.rpc.chain_id, 'observedAt': self.now(),
                    'transactionHash': transaction_hash, 'receipt': receipt}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_transaction_receipt(request, service):
    try:
        transaction_hash = ReceiptRequest.model_validate(dict(request.query_params)).hash
    except ValidationError:
        return JSONResponse({'error': 'A valid transaction hash is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(transaction_hash)) if service else None
    return await handle_protocol_facts(request, bound, 'transaction-receipt',
                                       'Transaction receipt is temporarily unavailable.')

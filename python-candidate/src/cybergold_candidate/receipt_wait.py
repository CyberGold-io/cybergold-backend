"""Fixed fresh observations consumed by Viem's existing receipt waiter.

Native Ethereum wire values preserve the standard library's formatter and
replacement detection. There is no server queue, inferred cancellation,
wallet submission, caller-selected RPC method, endpoint or ABI.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import AsyncWeb3

from .protocol_facts import handle_protocol_facts
from .rpc_transport import rpc_provider
from .shared_reads import SharedReads


class HashRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    hash: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{64}$')]


class BlockRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    blockNumber: Annotated[str, StringConstraints(pattern=r'^[0-9]+$')]


class ReceiptWaitRpc:
    def __init__(self, settings, w3=None):
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))
        self.head_reads = SharedReads()

    async def observe(self, operation, argument=None):
        if operation == 'head':
            return await self.head_reads.one('latest', self.head)
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        method, params, field = {
            'transaction': ('eth_getTransactionByHash', [argument], 'transaction'),
            'receipt': ('eth_getTransactionReceipt', [argument], 'receipt'),
            'block': ('eth_getBlockByNumber', [argument, True], 'block'),
        }[operation]
        response = await self.w3.provider.make_request(method, params)
        if 'error' in response:
            # Native null is absence; a provider error never becomes null.
            raise ValueError('Transaction observation provider failed')
        value = response['result']
        return field, value

    async def head(self):
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        response = await self.w3.provider.make_request('eth_getBlockByNumber', ['latest', False])
        if 'error' in response:
            raise ValueError('Head observation provider failed')
        value = response['result']
        return {'blockNumber': str(int(value['number'], 16)), 'blockHash': value['hash'],
                'blockTimestamp': str(int(value['timestamp'], 16))}

    async def close(self):
        await self.head_reads.close()
        await self.w3.provider.disconnect()


class ReceiptWait:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, operation, argument=None):
        if self.rpc is None:
            self.rpc = ReceiptWaitRpc(self.settings)
        async with asyncio.timeout(15):
            value = await self.rpc.observe(operation, argument)
            fields = value if operation == 'head' else {value[0]: value[1]}
            return {'chainId': self.rpc.chain_id, 'observedAt': self.now(), **fields}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_receipt_wait(request, service, operation):
    argument = None
    try:
        if operation in ('transaction', 'receipt'):
            argument = HashRequest.model_validate(dict(request.query_params)).hash
        elif operation == 'block':
            argument = hex(int(BlockRequest.model_validate(dict(request.query_params)).blockNumber))
    except ValidationError:
        message = ('A decimal block number is required.' if operation == 'block'
                   else 'A valid transaction hash is required.')
        return JSONResponse({'error': message}, status_code=400, headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(operation, argument)) if service else None
    return await handle_protocol_facts(request, bound, 'receipt-wait-' + operation,
                                       'Transaction confirmation observations are temporarily unavailable.')

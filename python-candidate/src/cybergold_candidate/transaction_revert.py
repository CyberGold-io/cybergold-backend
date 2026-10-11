"""Replay the transaction identified by the App's receipt, never caller calldata."""
import asyncio
from datetime import datetime, timezone
import re
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from pydantic import ValidationError
from web3 import Web3
from web3.exceptions import ContractLogicError

from .protocol_facts import handle_protocol_facts
from .receipt_wait import HashRequest, ReceiptWaitRpc


class TransactionRevertRpc(ReceiptWaitRpc):
    async def replay(self, transaction_hash):
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        transaction = await self.w3.eth.get_transaction(transaction_hash)
        # These are the standard Wagmi receipt-hook replay fields, derived from
        # the chain transaction. The client supplies only its transaction hash.
        keys = ('from', 'to', 'gas', 'nonce', 'value', 'accessList',
                'authorizationList', 'maxFeePerBlobGas')
        call = {key: transaction[key] for key in keys if key in transaction and transaction[key] is not None}
        call['data'] = transaction['input']
        fees = ('maxFeePerGas', 'maxPriorityFeePerGas') if transaction.get('type') == 2 else ('gasPrice',)
        call.update({key: transaction[key] for key in fees if transaction.get(key) is not None})
        try:
            result = await self.w3.eth.call(call, 'latest')
            return {'data': Web3.to_hex(result) if result else None, 'reverted': False}
        except ContractLogicError as error:
            # Expose EVM return bytes only, never private provider text/URLs.
            data = error.data
            return {'data': data if isinstance(data, str) and re.fullmatch(r'0x(?:[a-fA-F0-9]{2})*', data) else None,
                    'reverted': True}


class TransactionRevert:
    def __init__(self, settings, rpc=None, now=None):
        self.settings,self.rpc=settings,rpc
        self.now=now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'))

    async def get(self, transaction_hash):
        if self.rpc is None:self.rpc=TransactionRevertRpc(self.settings)
        async with asyncio.timeout(15):
            payload=await self.rpc.replay(transaction_hash)
            return {'chainId':self.rpc.chain_id,'observedAt':self.now(),'transactionHash':transaction_hash,**payload}

    async def close(self):
        if self.rpc:await self.rpc.close()


async def handle_transaction_revert(request, service):
    try:transaction_hash=HashRequest.model_validate(dict(request.query_params)).hash
    except ValidationError:
        return JSONResponse({'error':'A valid transaction hash is required.'},status_code=400,headers={'Cache-Control':'no-store'})
    bound=SimpleNamespace(get=lambda:service.get(transaction_hash)) if service else None
    return await handle_protocol_facts(request,bound,'transaction-revert','Transaction revert observations are temporarily unavailable.')

"""Configured QuoterV2 exact-input/output reads; App route choice is retained."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter
from web3 import AsyncWeb3, Web3

from .basket_preview import InvalidPreview, handle_basket_preview
from .recovery_rpc import RecoveryRpc
from .rpc_transport import rpc_provider

ABI = json.loads(Path(__file__).with_name('uniswap-quote-abi.json').read_text())
METHODS = {'exact-in': 'quoteExactInput', 'exact-out': 'quoteExactOutput'}


class QuoteRequest(BaseModel):
    mode: Literal['exact-in', 'exact-out']
    path: str
    amount: str


REQUEST = TypeAdapter(QuoteRequest)


class UniswapQuoteRpc(RecoveryRpc):
    def __init__(self, settings, w3=None):
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.quoter = Web3.to_checksum_address(settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))
        self.contract = self.w3.eth.contract(abi=ABI)

    def encode(self, request):
        try:
            return self.contract.encode_abi(METHODS[request['mode']],
                args=[bytes.fromhex(request['path'].removeprefix('0x')), int(request['amount'])])
        except Exception as error:
            raise InvalidPreview('Invalid Uniswap quote input.') from error

    async def quote(self, mode, data, block):
        response = await self.w3.provider.make_request('eth_call', [
            {'to': self.quoter, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Uniswap quote contract read failed')
        outputs = next(row for row in ABI if row['name'] == METHODS[mode])['outputs']
        decoded = self.w3.codec.decode([row['type'] for row in outputs], bytes.fromhex(response['result'][2:]))
        # Existing App consumers use tuple[0]; gas/tick arrays do not select routes.
        return {'amount': str(decoded[0])}


class UniswapQuote:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request):
        if self.rpc is None:
            self.rpc = UniswapQuoteRpc(self.settings)
        data = self.rpc.encode(request)
        async with asyncio.timeout(15):
            block = await self.rpc.block(None)
            result = await self.rpc.quote(request['mode'], data, block)
            await self.rpc.assert_canonical(block)
            return {'mode': request['mode'], 'quoter': self.rpc.quoter, 'result': result,
                    'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                                'blockHash': block['hash'], 'observedAt': self.now()}}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_uniswap_quote(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'uniswap-quote',
        'Invalid Uniswap quote input.', 'Uniswap quotes are temporarily unavailable.')

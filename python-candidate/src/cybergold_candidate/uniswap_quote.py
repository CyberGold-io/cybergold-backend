"""Caller-selected V3 routes use the shared structured quote engine."""
import asyncio
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, TypeAdapter
from web3 import AsyncWeb3, Web3

from .basket_preview import InvalidPreview, handle_basket_preview
from .recovery_rpc import RecoveryRpc
from .rpc_transport import rpc_provider
from .route_work_slots import engine_work
from .uniswap_routes import v3_plan

class QuoteRequest(BaseModel):
    mode: Literal['exact-in', 'exact-out']
    path: str
    amount: str


REQUEST = TypeAdapter(QuoteRequest)


class QuoteContextRpc(RecoveryRpc):
    """Pinned chain/header transport; no onchain price calculator is loaded."""
    def __init__(self, settings, w3=None):
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))



class UniswapQuote:
    def __init__(self, settings, rpc=None, now=None, *, engine=None):
        self.settings, self.rpc = settings, rpc
        self.engine = engine
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request):
        try:
            amount = int(request['amount'])
            # Preserve the shipped ABI's uint256 input domain before RPC.
            Web3().codec.encode(['uint256'], [amount])
            plan = v3_plan(request['path'], request['mode'], amount,
                chain_id=int(self.settings.NEXT_PUBLIC_CHAIN_ID))
        except Exception as error:
            raise InvalidPreview('Invalid Uniswap quote input.') from error
        if self.engine is None:
            raise RuntimeError('Shared route quote engine is not configured.')
        if self.rpc is None:
            self.rpc = QuoteContextRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block(None)
            async with engine_work(self.engine.semaphore):
                value = await self.engine.quote_branches(plan['branches'], plan['mode'], amount, block)
            await self.rpc.assert_canonical(block)
            result = {'amount': str(value['amountOut' if plan['mode'] == 'exactIn' else 'amountIn'])}
            return {'mode': request['mode'], 'qualification': 'sdk', 'result': result,
                    'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                                'blockHash': block['hash'], 'observedAt': self.now()}}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_uniswap_quote(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'uniswap-quote',
        'Invalid Uniswap quote input.', 'Uniswap quotes are temporarily unavailable.')

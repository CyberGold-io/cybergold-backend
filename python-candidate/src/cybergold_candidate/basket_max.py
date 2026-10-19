"""Wallet-bounded proportional basket MAX from one canonical Core snapshot."""
import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel, TypeAdapter

from .basket_arithmetic import PPM, FP, ceil_div, gross_for_net
from .basket_preview import BasketPreviewRpc, InvalidPreview, handle_basket_preview
from .protocol_facts import ProtocolFactsRpc


class BasketMaxRequest(BaseModel):
    driverToken: str
    maximumAmountsIn: list[str]


REQUEST = TypeAdapter(BasketMaxRequest)


def proportional_maximum(budgets, weights, decimals, conversions, issue_fee, capacity, driver):
    """Largest wallet-bounded driver whose unclipped canonical gross fits.

    App proportional budgets use floor(driver * weight * 10**decimals /
    driver_scale). Invert these floors exactly. Core first rounds budget value
    down, then canonicalizes the issuance fee; its first gross above capacity
    therefore supplies the first forbidden driver. Helpers split Core's net
    issuance and do not increase gross supply on this direct-basket path.
    """
    zero = (0, [0] * len(budgets))
    if capacity <= 0:
        return zero
    scales = [weight * 10**precision for weight, precision in zip(weights, decimals, strict=True)]
    driver_scale = scales[driver]
    positive = [i for i, weight in enumerate(weights) if weight]
    wallet_bound = min(ceil_div((budgets[i] + 1) * driver_scale, scales[i]) - 1 for i in positive)
    # gross_for_net is the exact inverse used by the existing Core preview,
    # including fee plateaus; using capacity+1 here would lose that property.
    next_gross = gross_for_net(capacity - capacity * issue_fee // PPM + 1, issue_fee)
    next_budgets = [ceil_div(ceil_div(next_gross * weights[i], PPM) * FP, conversions[i])
                    for i in positive]
    first_forbidden = max(ceil_div(amount * driver_scale, scales[i])
                          for i, amount in zip(positive, next_budgets, strict=True))
    amount = min(wallet_bound, first_forbidden - 1)
    result = [amount * scale // driver_scale for scale in scales]
    supported_gross = min((result[i] * conversions[i] // FP) * PPM // weights[i] for i in positive)
    return (amount, result) if supported_gross > 0 else zero


class BasketMaxRpc(ProtocolFactsRpc):
    def __init__(self, settings, w3=None):
        super().__init__(settings, w3)
        self.basket = BasketPreviewRpc(settings, self.w3)
        self.helpers = self.basket.helpers

    def encode(self, request):
        return self.basket.encode({'mode': 'issue-exact-in', 'maximumAmountsIn': request['maximumAmountsIn']})

    async def state(self, block):
        names = ('basketAssets', 'basketTargetsPpm', 'basketCygldPerUnitFp18', 'issuanceFeePpm',
                 'totalSupply', 'maxTotalSupply', 'effectiveCygldSupplyCap')
        values = await asyncio.gather(*(self.read('core', self.core, name, block) for name in names))
        return dict(zip(('assets', 'weights', 'conversions', 'issueFee', 'supply', 'maxSupply', 'effectiveCap'),
                        values, strict=True))

    async def decimals(self, assets, block):
        return await asyncio.gather(*(self.read('token', asset, 'decimals', block) for asset in assets))

    async def preview(self, amounts, block):
        data = self.basket.encode({'mode': 'issue-exact-in', 'maximumAmountsIn': [str(value) for value in amounts]})
        return await self.basket.preview('issue-exact-in', data, block)


class BasketMax:
    rpc_type = BasketMaxRpc

    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request):
        if self.rpc is None:
            self.rpc = self.rpc_type(self.settings)
        # The retained fixed Helpers ABI establishes uint256 input bounds.
        self.rpc.encode(request)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            state = await self.rpc.state(block)
            assets, weights = state['assets'], state['weights']
            if len(request['maximumAmountsIn']) != len(assets):
                raise InvalidPreview('Basket budgets must follow the configured Core asset vector.')
            driver = next((i for i, asset in enumerate(assets)
                           if asset.lower() == request['driverToken'].lower()), None)
            if driver is None:
                raise InvalidPreview('Basket driver must be a configured Core asset.')
            if not weights[driver]:
                raise InvalidPreview('Basket driver must have positive weight.')
            capacity = max(0, min(state['maxSupply'], state['effectiveCap']) - state['supply'])
            amount, amounts = 0, [0] * len(assets)
            net = '0'
            positive = [i for i, weight in enumerate(weights) if weight]
            budgets = [int(value) for value in request['maximumAmountsIn']]
            if capacity and all(budgets[i] for i in positive):
                precisions = await self.rpc.decimals([assets[i] for i in positive], block)
                decimals = [0] * len(assets)
                for i, precision in zip(positive, precisions, strict=True):
                    decimals[i] = precision
                amount, amounts = proportional_maximum(
                    budgets, weights, decimals,
                    state['conversions'], state['issueFee'], capacity, driver)
                if amount:
                    # All arithmetic inputs and the authoritative validation use
                    # the same existing EIP-1898 hash/requireCanonical contract.
                    result = await self.rpc.preview(amounts, block)
                    net = result['netCygldOut']
                    if int(net) == 0:
                        amount, amounts = 0, [0] * len(assets)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                                'blockHash': block['hash'], 'observedAt': self.now()},
                    'helpers': self.rpc.helpers, 'orderedCoreAssets': assets,
                    'driverToken': assets[driver], 'driverAmount': str(amount),
                    'maximumAmountsIn': [str(value) for value in amounts], 'netCygldOut': net}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_basket_max(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'basket-max',
                                      'Invalid basket MAX input.', 'Basket MAX is temporarily unavailable.')

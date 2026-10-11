"""The Apps' six token/native Helpers previews; no signing or routing policy."""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter
from web3 import Web3

from .basket_preview import BasketPreview, BasketPreviewRpc, InvalidPreview, handle_basket_preview

METHODS = {
    'issue-token-exact-in': 'previewIssueFromTokenExactIn',
    'issue-native-exact-in': 'previewIssueFromNativeExactIn',
    'issue-token-exact-out': 'previewIssueFromTokenExactOut',
    'issue-native-exact-out': 'previewIssueFromNativeExactOut',
    'redeem-token-exact-in': 'previewRedeemToTokenExactIn',
    'redeem-native-exact-in': 'previewRedeemToNativeExactIn',
}


class IssueLeg(BaseModel):
    adapter: str
    amountIn: str
    minimumAmountOut: str
    data: str


class RedemptionLeg(BaseModel):
    adapter: str
    minimumAmountOut: str
    data: str


class IssueTokenExactIn(BaseModel):
    mode: Literal['issue-token-exact-in']
    inputToken: str
    inputAmount: str
    quotes: list[IssueLeg]


class IssueNativeExactIn(BaseModel):
    mode: Literal['issue-native-exact-in']
    inputAmount: str
    quotes: list[IssueLeg]


class IssueTokenExactOut(BaseModel):
    mode: Literal['issue-token-exact-out']
    inputToken: str
    maximumInputAmount: str
    netCygldOut: str
    quotes: list[IssueLeg]


class IssueNativeExactOut(BaseModel):
    mode: Literal['issue-native-exact-out']
    maximumNativeIn: str
    netCygldOut: str
    quotes: list[IssueLeg]


class RedeemTokenExactIn(BaseModel):
    mode: Literal['redeem-token-exact-in']
    outputToken: str
    grossCygldIn: str
    quotes: list[RedemptionLeg]


class RedeemNativeExactIn(BaseModel):
    mode: Literal['redeem-native-exact-in']
    grossCygldIn: str
    quotes: list[RedemptionLeg]


REQUEST = TypeAdapter(Annotated[IssueTokenExactIn | IssueNativeExactIn | IssueTokenExactOut |
    IssueNativeExactOut | RedeemTokenExactIn | RedeemNativeExactIn, Field(discriminator='mode')])


class TokenPreviewRpc(BasketPreviewRpc):
    abi = json.loads(Path(__file__).with_name('token-preview-abi.json').read_text())
    methods = METHODS

    def encode(self, request):
        try:
            mode = request['mode']
            if mode.startswith('issue-'):
                legs = [(Web3.to_checksum_address(row['adapter']), int(row['amountIn']),
                         int(row['minimumAmountOut']), bytes.fromhex(row['data'].removeprefix('0x')))
                        for row in request['quotes']]
            else:
                legs = [(Web3.to_checksum_address(row['adapter']), int(row['minimumAmountOut']),
                         bytes.fromhex(row['data'].removeprefix('0x'))) for row in request['quotes']]
            if mode == 'issue-token-exact-in':
                params = (Web3.to_checksum_address(request['inputToken']), int(request['inputAmount']))
            elif mode == 'issue-native-exact-in':
                params = int(request['inputAmount'])
            elif mode == 'issue-token-exact-out':
                params = (Web3.to_checksum_address(request['inputToken']), int(request['maximumInputAmount']),
                          int(request['netCygldOut']))
            elif mode == 'issue-native-exact-out':
                params = (int(request['maximumNativeIn']), int(request['netCygldOut']))
            elif mode == 'redeem-token-exact-in':
                params = (int(request['grossCygldIn']), Web3.to_checksum_address(request['outputToken']))
            else:
                params = int(request['grossCygldIn'])
            return self.contract.encode_abi(self.methods[mode], args=[params, legs])
        except Exception as error:
            raise InvalidPreview('Invalid token preview input.') from error


class TokenPreview(BasketPreview):
    rpc_type = TokenPreviewRpc


async def handle_token_preview(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'token-preview',
        'Invalid token preview input.', 'Token previews are temporarily unavailable.')

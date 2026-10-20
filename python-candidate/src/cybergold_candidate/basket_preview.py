"""The four Swap basket previews, read from configured Helpers at one block."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Annotated, Literal

from eth_utils.abi import collapse_if_tuple
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from web3 import AsyncWeb3, Web3

from .recovery_rpc import RecoveryRpc, abi_value
from .rpc_transport import rpc_provider
from .preview_errors import preview_error, KnownPreviewError, zero_amount_issue_error
from .issuance_capacity import read_supply_capacity, exhausted_capacity_error
from .quote_errors import rpc_failure, public_quote_error
from .trade_observation import QuoteObservation, failure

ABI = json.loads(Path(__file__).with_name('basket-preview-abi.json').read_text())
METHODS = {
    'issue-exact-in': 'previewIssueFromBasketExactIn',
    'issue-exact-out': 'previewIssueFromBasketExactOut',
    'redeem-exact-in': 'previewRedeemToBasketExactIn',
    'redeem-exact-out': 'previewRedeemToBasketExactOut',
}


class IssueExactIn(BaseModel):
    mode: Literal['issue-exact-in']
    maximumAmountsIn: list[str]


class IssueExactOut(BaseModel):
    mode: Literal['issue-exact-out']
    netCygldOut: str


class RedeemExactIn(BaseModel):
    mode: Literal['redeem-exact-in']
    grossCygldIn: str


class MinimumOutput(BaseModel):
    kind: int
    token: str
    id: str
    minimumAmount: str


class RedeemExactOut(BaseModel):
    mode: Literal['redeem-exact-out']
    minimumOutputs: list[MinimumOutput]


REQUEST = TypeAdapter(Annotated[IssueExactIn | IssueExactOut | RedeemExactIn | RedeemExactOut,
                               Field(discriminator='mode')])


class InvalidPreview(ValueError):
    pass


def wire_value(value, parameter):
    """ABI-shaped JSON: uint256 stays decimal text; token kind stays a number."""
    if parameter['type'].endswith('[]'):
        return [wire_value(item, {**parameter, 'type': parameter['type'][:-2]}) for item in value]
    if parameter['type'] == 'tuple':
        return {part['name']: wire_value(value[part['name']], part) for part in parameter['components']}
    if parameter['type'].startswith('uint') and parameter['type'] != 'uint8':
        return str(value)
    return value


class BasketPreviewRpc(RecoveryRpc):
    abi = ABI
    methods = METHODS

    def __init__(self, settings, w3=None):
        self.settings = settings
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.helpers = Web3.to_checksum_address(settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))
        self.contract = self.w3.eth.contract(abi=self.abi)

    def encode(self, request):
        try:
            mode = request['mode']
            if mode == 'issue-exact-in':
                args = [[int(value) for value in request['maximumAmountsIn']]]
            elif mode == 'issue-exact-out':
                args = [int(request['netCygldOut'])]
            elif mode == 'redeem-exact-in':
                args = [int(request['grossCygldIn'])]
            else:
                args = [[(row['kind'], Web3.to_checksum_address(row['token']),
                          int(row['id']), int(row['minimumAmount'])) for row in request['minimumOutputs']]]
            # The shipped ABI owns uint bounds and tuple/address encoding.
            # No arbitrary ABI, method, provider or target comes from the App.
            return self.contract.encode_abi(self.methods[mode], args=args)
        except Exception as error:
            raise InvalidPreview('Invalid basket preview input.') from error

    async def preview(self, mode, data, block):
        response = await self.w3.provider.make_request('eth_call', [
            {'to': self.helpers, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            _, arguments = self.contract.decode_function_input(data)
            known = preview_error(response['error'], mode=mode, arguments=arguments)
            if known is None and zero_amount_issue_error(response['error'], mode):
                known = exhausted_capacity_error(await read_supply_capacity(self, self.settings, block))
            if known:
                raise known
            raise rpc_failure(response['error'])
        output = next(row for row in self.abi if row['name'] == self.methods[mode])['outputs'][0]
        decoded = self.w3.codec.decode([collapse_if_tuple(output)], bytes.fromhex(response['result'][2:]))[0]
        return wire_value(abi_value(decoded, output), output)


class BasketPreview:
    rpc_type = BasketPreviewRpc

    def __init__(self, settings, rpc=None, now=None, history=None):
        self.settings, self.rpc = settings, rpc
        self.history = history
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request):
        if self.rpc is None:
            self.rpc = self.rpc_type(self.settings)
        data = self.rpc.encode(request)
        # Reuse the existing API RPC operation deadline and cancellation policy.
        async with asyncio.timeout(15):
            block = await self.rpc.block(None)
            result = await self.rpc.preview(request['mode'], data, block)
            await self.rpc.assert_canonical(block)
            response = {'mode': request['mode'], 'helpers': self.rpc.helpers,
                    'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                                'blockHash': block['hash'], 'observedAt': self.now()}, 'result': result}
            if self.history:
                response['basketModel'] = self.history.protocol_model()
            return response

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_basket_preview(request, service, adapter=REQUEST, context='basket-preview',
                                invalid='Invalid basket preview input.',
                                unavailable='Basket previews are temporarily unavailable.'):
    try:
        value = adapter.validate_python(await request.json()).model_dump()
    except (ValueError, ValidationError):
        return JSONResponse({'error': invalid}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    qualified_json = context in ('basket-preview', 'token-preview', 'market-quote')
    observation = QuoteObservation(request, value,
        'market' if context == 'market-quote' else 'core' if context in ('basket-preview', 'token-preview') else None)

    async def result():
        try:
            result = await service.get(value)
            if qualified_json:
                observation.event({'type':'complete', 'value':result})
            else:
                observation.finish('succeeded')
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except InvalidPreview:
            observation.finish('invalid')
            return JSONResponse({'error': invalid}, status_code=400,
                                headers={'Cache-Control': 'no-store'})
        except Exception as error:
            payload = public_quote_error(error)
            payload = failure(request, error, context, payload=payload)
            observation.finish('failed', frame=payload)
            return JSONResponse(payload,
                                status_code=503, headers={'Cache-Control': 'no-store'})

    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass

    operation, caller = asyncio.create_task(result()), asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((operation, caller), return_when=asyncio.FIRST_COMPLETED)
        return await operation if operation in done else Response(status_code=499)
    finally:
        operation.cancel()
        caller.cancel()
        await asyncio.gather(operation, caller, return_exceptions=True)
        observation.finish('cancelled')

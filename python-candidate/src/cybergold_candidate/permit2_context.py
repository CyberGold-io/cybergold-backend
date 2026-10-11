"""The App's fixed Permit2 verification, nonce and allowance observations."""
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter
from web3 import Web3

from .basket_preview import handle_basket_preview
from .protocol_facts import ProtocolFactsRpc
from .supplier_dispatch import dispatch

Address = Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class Verify(BaseModel):
    mode: Literal['verify']


class Nonce(BaseModel):
    mode: Literal['nonce']
    owner: Address


class Allowances(BaseModel):
    mode: Literal['allowances']
    owner: Address
    tokens: list[Address]


REQUEST = TypeAdapter(Annotated[Verify | Nonce | Allowances, Field(discriminator='mode')])
ABI = [
    {'type': 'function', 'name': 'permit2', 'stateMutability': 'view',
     'inputs': [], 'outputs': [{'name': '', 'type': 'address'}]},
    {'type': 'function', 'name': 'nonceBitmap', 'stateMutability': 'view',
     'inputs': [{'name': 'owner', 'type': 'address'}, {'name': 'wordPos', 'type': 'uint256'}],
     'outputs': [{'name': '', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'allowance', 'stateMutability': 'view',
     'inputs': [{'name': 'owner', 'type': 'address'}, {'name': 'spender', 'type': 'address'}],
     'outputs': [{'name': '', 'type': 'uint256'}]},
]


class Permit2Rpc(ProtocolFactsRpc):
    async def permit2_read(self, address, name, args, block):
        data = self.w3.eth.contract(abi=ABI).encode_abi(name, args=args)
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Permit2 context read failed')
        output = 'address' if name == 'permit2' else 'uint256'
        value = self.w3.codec.decode([output], bytes.fromhex(response['result'][2:]))[0]
        return Web3.to_checksum_address(value) if name == 'permit2' else value

    async def code(self, address, block):
        response = await self.w3.provider.make_request('eth_getCode', [
            address, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Permit2 bytecode read failed')
        return response['result']


class Permit2Context:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request):
        if self.rpc is None:
            self.rpc = Permit2Rpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            permit2 = await self.rpc.permit2_read(self.rpc.helpers, 'permit2', [], block)
            mode = request['mode']
            if mode == 'verify':
                result = {'code': await self.rpc.code(permit2, block)}
            else:
                owner = Web3.to_checksum_address(request['owner'])
                if mode == 'nonce':
                    # Same first-free-bit traversal as the existing App, bounded
                    # by the operation deadline rather than an arbitrary word cap.
                    word = 0
                    while True:
                        bitmap = await self.rpc.permit2_read(permit2, 'nonceBitmap', [owner, word], block)
                        free = next((bit for bit in range(256) if not bitmap & (1 << bit)), None)
                        if free is not None:
                            result = {'owner': owner, 'nonce': str((word << 8) | free)}
                            break
                        word += 1
                else:
                    tokens = [Web3.to_checksum_address(token) for token in request['tokens']]
                    unique = list(dict.fromkeys(tokens))
                    async def allowance(token):
                        return await self.rpc.permit2_read(token, 'allowance', [owner, permit2], block)
                    observed = dict(zip(unique, await dispatch(unique, allowance), strict=True))
                    values = [observed[token] for token in tokens]
                    result = {'owner': owner, 'allowances': [{'token': token, 'value': str(value)}
                        for token, value in zip(tokens, values, strict=True)]}
            await self.rpc.assert_canonical(block)
            return {'mode': mode, 'helpers': self.rpc.helpers, 'permit2': permit2, 'result': result,
                    'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                        'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()}}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_permit2_context(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'permit2-context',
                                      'Invalid Permit2 context input.',
                                      'Permit2 observations are temporarily unavailable.')

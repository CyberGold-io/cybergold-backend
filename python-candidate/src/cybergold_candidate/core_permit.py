"""Fresh Core permit signing context for the App; never signs or submits."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import ProtocolFactsRpc, handle_protocol_facts

ABI = [
    {'type': 'function', 'name': 'name', 'stateMutability': 'view',
     'inputs': [], 'outputs': [{'name': '', 'type': 'string'}]},
    {'type': 'function', 'name': 'nonces', 'stateMutability': 'view',
     'inputs': [{'name': 'owner', 'type': 'address'}],
     'outputs': [{'name': '', 'type': 'uint256'}]},
]


class PermitRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    owner: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class CorePermitRpc(ProtocolFactsRpc):
    async def permit_read(self, name, owner, block):
        data = self.w3.eth.contract(abi=ABI).encode_abi(name, args=[owner] if name == 'nonces' else [])
        response = await self.w3.provider.make_request('eth_call', [
            {'to': self.core, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Core permit read failed')
        output = 'uint256' if name == 'nonces' else 'string'
        return self.w3.codec.decode([output], bytes.fromhex(response['result'][2:]))[0]


class CorePermit:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, owner):
        if self.rpc is None:
            self.rpc = CorePermitRpc(self.settings)
        owner = Web3.to_checksum_address(owner)
        # Preserve the existing App's version-1 domain, Helpers spender and
        # current nonce. No cached nonce or server-selected value/deadline.
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            name, nonce = await asyncio.gather(self.rpc.permit_read('name', owner, block),
                                               self.rpc.permit_read('nonces', owner, block))
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                    'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                    'owner': owner, 'spender': self.rpc.helpers, 'nonce': str(nonce),
                    'domain': {'name': name, 'version': '1', 'chainId': self.rpc.chain_id,
                               'verifyingContract': self.rpc.core}}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_core_permit(request, service):
    try:
        owner = PermitRequest.model_validate(dict(request.query_params)).owner
    except ValidationError:
        return JSONResponse({'error': 'A valid owner address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(owner)) if service else None
    return await handle_protocol_facts(request, bound, 'core-permit',
                                       'Core permit context is temporarily unavailable.')

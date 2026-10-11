"""The App's Safe principal observations, without interpreting signing authority."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import ProtocolFactsRpc, handle_protocol_facts

# Same two read signatures as the retained App SAFE_ABI. No generic ABI/method
# input, nonce, simulation or transaction submission belongs to this operation.
ABI = {'safe': [
    {'type': 'function', 'name': 'getOwners', 'inputs': [],
     'outputs': [{'name': '', 'type': 'address[]'}], 'stateMutability': 'view'},
    {'type': 'function', 'name': 'getThreshold', 'inputs': [],
     'outputs': [{'name': '', 'type': 'uint256'}], 'stateMutability': 'view'},
]}


class PrincipalRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    address: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class SafePrincipalRpc(ProtocolFactsRpc):
    def __init__(self, settings, w3=None):
        super().__init__(settings, w3, abi=ABI)

    async def code(self, address, block):
        response = await self.w3.provider.make_request('eth_getCode', [
            address, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Principal bytecode read failed')
        return Web3.to_hex(Web3.to_bytes(hexstr=response['result']))


class GovernanceSafePrincipal:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, address):
        if self.rpc is None:
            self.rpc = SafePrincipalRpc(self.settings)
        address = Web3.to_checksum_address(address)
        async with asyncio.timeout(15):
            block = await self.rpc.block()

            async def read(name):
                try:
                    value = (await self.rpc.code(address, block) if name == 'code' else
                             await self.rpc.read('safe', address, name, block))
                    return {'status': 'success', 'value': str(value) if name == 'getThreshold' else value}
                except Exception:
                    return {'status': 'failure', 'error': 'contract-read-failed'}

            code, owners, threshold = await asyncio.gather(*(read(name) for name in ('code', 'getOwners', 'getThreshold')))
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'address': address, 'code': code, 'owners': owners, 'threshold': threshold}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_safe_principal(request, service):
    try:
        address = PrincipalRequest.model_validate(dict(request.query_params)).address
    except ValidationError:
        return JSONResponse({'error': 'A valid principal address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    # Per-request address binding preserves concurrent principal isolation.
    bound = SimpleNamespace(get=lambda: service.get(address)) if service else None
    return await handle_protocol_facts(request, bound, 'governance-safe-principal',
                                       'Safe principal observations are temporarily unavailable.')

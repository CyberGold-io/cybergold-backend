"""Configured Governance role rosters used by the Apps' three diamond pages."""
import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace
from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc

# Retain the App's named roles and existing first-50 display policy.
SURFACES = {
    'core': ('NEXT_PUBLIC_CORE_DIAMOND_ADDRESS', ('DEFAULT_ADMIN_ROLE', 'UPGRADER_ROLE')),
    'staking': ('NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS', ('DEFAULT_ADMIN_ROLE', 'UPGRADER_ROLE', 'ALLOCATOR_ROLE', 'WITHDRAWER_ROLE')),
    'governance-diamond': ('NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS', ('DEFAULT_ADMIN_ROLE', 'UPGRADER_ROLE', 'PROPOSER_ROLE', 'EXECUTOR_ROLE', 'CANCELLER_ROLE')),
}
ABI = [
    {'type': 'function', 'name': 'getRoleMemberCount', 'stateMutability': 'view',
     'inputs': [{'name': 'role', 'type': 'bytes32'}], 'outputs': [{'name': '', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getRoleMember', 'stateMutability': 'view',
     'inputs': [{'name': 'role', 'type': 'bytes32'}, {'name': 'index', 'type': 'uint256'}],
     'outputs': [{'name': '', 'type': 'address'}]},
]


class RolesRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    surface: Literal['core', 'staking', 'governance-diamond']


def role_hash(name):
    return bytes(32) if name == 'DEFAULT_ADMIN_ROLE' else Web3.keccak(text=name)


class GovernanceRolesRpc(NonceRpc):
    async def read(self, address, name, arguments, block):
        data = self.w3.eth.contract(abi=ABI).encode_abi(name, args=arguments)
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': Web3.to_hex(block['hash']), 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Role roster read failed')
        output = 'uint256' if name == 'getRoleMemberCount' else 'address'
        value = self.w3.codec.decode([output], bytes.fromhex(response['result'][2:]))[0]
        return value if output == 'uint256' else Web3.to_checksum_address(value)


class GovernanceRoles:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, surface):
        if self.rpc is None:
            self.rpc = GovernanceRolesRpc(self.settings)
        setting, names = SURFACES[surface]
        address = getattr(self.settings, setting, os.environ.get(setting))
        async with asyncio.timeout(15):
            block = await self.rpc.block()

            async def roster(name):
                if not address:
                    return {'id': name, 'count': {'status': 'failure', 'error': 'not-configured'}, 'members': []}
                hashed = role_hash(name)
                try:
                    count = await self.rpc.read(address, 'getRoleMemberCount', [hashed], block)
                except Exception:
                    return {'id': name, 'count': {'status': 'failure', 'error': 'contract-read-failed'}, 'members': []}

                async def member(index):
                    try:
                        value = await self.rpc.read(address, 'getRoleMember', [hashed, index], block)
                        return {'status': 'success', 'value': value}
                    except Exception:
                        return {'status': 'failure', 'error': 'contract-read-failed'}

                members = await asyncio.gather(*(member(index) for index in range(min(count, 50))))
                return {'id': name, 'count': {'status': 'success', 'value': str(count)}, 'members': members}

            rows = await asyncio.gather(*(roster(name) for name in names))
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']),
                'observedAt': self.now()}, 'surface': surface, 'address': address or None,
                'memberDisplayLimit': 50, 'roles': rows}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_governance_roles(request, service):
    try:
        surface = RolesRequest.model_validate(dict(request.query_params)).surface
    except ValidationError:
        return JSONResponse({'error': 'A configured Governance surface is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(surface)) if service else None
    return await handle_protocol_facts(request, bound, 'governance-roles',
                                       'Governance role observations are temporarily unavailable.')

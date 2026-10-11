"""Configured diamond pause and emergency-authority observations for the Apps."""
import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .governance_roles import SURFACES
from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc

ABI = [
    {'type': 'function', 'name': name, 'stateMutability': 'view', 'inputs': [],
     'outputs': [{'name': '', 'type': kind}]} for name, kind in (('safeWallet', 'address'), ('paused', 'bool'))
] + [
    {'type': 'function', 'name': name, 'stateMutability': 'view',
     'inputs': [{'name': 'account', 'type': 'address'}], 'outputs': [{'name': '', 'type': 'bool'}]}
    for name in ('canPause', 'canUnpause')
]


class AuthorityRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    surface: Literal['core', 'staking', 'governance-diamond']
    account: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')] | None = None


class GovernanceAuthorityRpc(NonceRpc):
    async def read(self, address, name, arguments, block):
        data = self.w3.eth.contract(abi=ABI).encode_abi(name, args=arguments)
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': Web3.to_hex(block['hash']), 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Governance authority read failed')
        kind = 'address' if name == 'safeWallet' else 'bool'
        value = self.w3.codec.decode([kind], bytes.fromhex(response['result'][2:]))[0]
        return Web3.to_checksum_address(value) if kind == 'address' else value


class GovernanceAuthority:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, surface, account=None):
        if self.rpc is None:
            self.rpc = GovernanceAuthorityRpc(self.settings)
        setting, _ = SURFACES[surface]
        address = getattr(self.settings, setting, os.environ.get(setting))
        account = Web3.to_checksum_address(account) if account else None
        async with asyncio.timeout(15):
            block = await self.rpc.block()

            async def read(name, arguments=()):
                if not address:
                    return {'status': 'failure', 'error': 'not-configured'}
                try:
                    return {'status': 'success', 'value': await self.rpc.read(address, name, list(arguments), block)}
                except Exception:
                    return {'status': 'failure', 'error': 'contract-read-failed'}

            absent = {'status': 'failure', 'error': 'not-configured'}
            safe, paused, can_pause, can_unpause = await asyncio.gather(
                read('safeWallet'), read('paused'),
                read('canPause', [account]) if account else asyncio.sleep(0, result=absent),
                read('canUnpause', [account]) if account else asyncio.sleep(0, result=absent))
            # Use the same block's configured Safe. This is an observation; the
            # App keeps its existing Safe compatibility and wallet checks.
            safe_can_unpause = await read('canUnpause', [safe['value']]) if safe['status'] == 'success' else absent
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'surface': surface, 'address': address or None, 'account': account,
                'safeWallet': safe, 'paused': paused, 'accountCanPause': can_pause,
                'accountCanUnpause': can_unpause, 'safeCanUnpause': safe_can_unpause}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_governance_authority(request, service):
    try:
        value = AuthorityRequest.model_validate(dict(request.query_params))
    except ValidationError:
        return JSONResponse({'error': 'A configured Governance surface and optional account are required.'},
                            status_code=400, headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(value.surface, value.account)) if service else None
    return await handle_protocol_facts(request, bound, 'governance-authority',
                                       'Governance authority observations are temporarily unavailable.')

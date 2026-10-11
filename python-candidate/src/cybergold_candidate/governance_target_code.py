"""Code presence used to describe the Apps' Safe proposal destinations."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from pydantic import ValidationError
from web3 import Web3

from .governance_safe_principal import PrincipalRequest, SafePrincipalRpc
from .protocol_facts import handle_protocol_facts


class GovernanceTargetCode:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, address):
        if self.rpc is None:
            self.rpc = SafePrincipalRpc(self.settings)
        address = Web3.to_checksum_address(address)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            code = await self.rpc.code(address, block)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'address': address, 'hasCode': code != '0x'}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_governance_target_code(request, service):
    try:
        address = PrincipalRequest.model_validate(dict(request.query_params)).address
    except ValidationError:
        return JSONResponse({'error': 'A valid proposal target address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(address)) if service else None
    return await handle_protocol_facts(request, bound, 'governance-target-code',
                                       'Proposal target code is temporarily unavailable.')

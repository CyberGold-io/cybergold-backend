"""Permanent recovery-share precision for the Apps' quote display."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import ProtocolFactsRpc, handle_protocol_facts
from .recovery_rpc import ABI as RECOVERY_ABI

ABI = {'core': [entry for entry in RECOVERY_ABI['core'] if entry['name'] == 'recoveryPool']}


class PrecisionRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    asset: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class RecoverySharePrecision:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, asset):
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings, abi=ABI)
        asset = Web3.to_checksum_address(asset)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            pool = await self.rpc.call('core', self.rpc.core, 'recoveryPool', block, [asset])
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                    'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                    'core': self.rpc.core, 'asset': asset, 'shareDecimals': pool['shareDecimals']}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_recovery_share_precision(request, service):
    try:
        asset = PrecisionRequest.model_validate(dict(request.query_params)).asset
    except ValidationError:
        return JSONResponse({'error': 'A valid asset address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(asset)) if service else None
    return await handle_protocol_facts(request, bound, 'recovery-share-precision',
                                       'Recovery-share precision is temporarily unavailable.')

"""The configured Core recovery-asset list used by redemption flows."""
import asyncio
from datetime import datetime, timezone

from .protocol_facts import ProtocolFactsRpc

ABI = {'core': [{'type': 'function', 'name': 'coreAttachedRecoveryAssets',
    'stateMutability': 'view', 'inputs': [],
    'outputs': [{'name': '', 'type': 'address[]'}]}]}


class CoreRecoveryAssets:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self):
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings, abi=ABI)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            assets = await self.rpc.read('core', self.rpc.core, 'coreAttachedRecoveryAssets', block)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                    'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                    'core': self.rpc.core, 'assets': assets}

    async def close(self):
        if self.rpc:
            await self.rpc.close()

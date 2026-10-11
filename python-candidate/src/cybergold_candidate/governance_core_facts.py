"""The Core governance configuration used by the App, at one canonical block."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from web3 import Web3

from .protocol_facts import ProtocolFactsRpc

ABI = json.loads(Path(__file__).with_name('governance-core-facts-abi.json').read_text())
FIELDS = (('treasury', 'treasury'), ('basketConfigHash', 'basketConfigHash'),
          ('issuanceFeePpm', 'issuanceFeePpm'), ('redemptionFeePpm', 'redemptionFeePpm'),
          ('maxFeePpm', 'MAX_FEE_PPM'), ('maxTotalSupply', 'maxTotalSupply'), ('totalSupply', 'totalSupply'),
          ('safeWallet', 'safeWallet'))


class GovernanceCoreFacts:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self):
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings, abi=ABI)
        # Reuse the current facts operation deadline and canonical transport.
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            async def read(name):
                try:
                    value = await self.rpc.read('core', self.rpc.core, name, block)
                    return {'status': 'success', 'value': Web3.to_hex(value) if name == 'basketConfigHash' else str(value)}
                except Exception:
                    return {'status': 'failure', 'error': 'contract-read-failed'}
            values = await asyncio.gather(*(read(name) for _, name in FIELDS))
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'core': self.rpc.core, 'configuration': dict(zip((key for key, _ in FIELDS), values, strict=True))}

    async def close(self):
        if self.rpc:
            await self.rpc.close()

"""The Apps' existing EIP-1559 fee estimate through configured server RPC."""
import asyncio
from datetime import datetime, timezone

from web3 import Web3

from .protocol_facts import ProtocolFactsRpc


class FeeRpc(ProtocolFactsRpc):
    async def block(self):
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        block = await self.w3.eth.get_block('latest')
        return {'hash': Web3.to_hex(block['hash']), 'number': block['number'],
                'timestamp': block['timestamp'], 'baseFeePerGas': block.get('baseFeePerGas')}

    async def priority_fee(self, base_fee):
        try:
            # Web3.eth.max_priority_fee adds its own fee-history fallback.
            # This transport call keeps the App's qualified supplier policy.
            response = await self.w3.provider.make_request('eth_maxPriorityFeePerGas', [])
            if 'error' in response:
                raise ValueError('Priority fee unavailable')
            return Web3.to_int(hexstr=response['result'])
        except Exception:
            # Retain Viem's existing unsupported-priority-method fallback.
            # The configured Ethereum Mainnet/fork Apps request EIP-1559 fees.
            return max(0, await self.w3.eth.gas_price - base_fee)


class TransactionFees:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self):
        if self.rpc is None:
            self.rpc = FeeRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            base_fee = block['baseFeePerGas']
            if base_fee is None:
                raise ValueError('EIP-1559 fees unavailable')
            priority = await self.rpc.priority_fee(base_fee)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                    'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                    'maxFeePerGas': str(base_fee * 12 // 10 + priority),
                    'maxPriorityFeePerGas': str(priority)}

    async def close(self):
        if self.rpc:
            await self.rpc.close()

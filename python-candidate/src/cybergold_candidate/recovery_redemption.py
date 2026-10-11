"""Simulate the App's exact recovery-share redemption; never signs or submits."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc

ABI = [{'type': 'function', 'name': 'redeemRecoveryShares', 'stateMutability': 'nonpayable',
        'inputs': [{'name': name, 'type': kind} for name, kind in
                   (('asset', 'address'), ('shares', 'uint256'), ('recipient', 'address'), ('minRawOut', 'uint256'))],
        'outputs': [{'name': 'rawOut', 'type': 'uint256'}]}]
Address = Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]
UInt = Annotated[str, StringConstraints(pattern=r'^[0-9]+$')]


class RedemptionRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    holder: Address
    asset: Address
    shares: UInt
    minRawOut: UInt


class RecoveryRedemptionRpc(NonceRpc):
    async def simulate(self, core, payload, block):
        holder, asset = Web3.to_checksum_address(payload.holder), Web3.to_checksum_address(payload.asset)
        data = self.w3.eth.contract(abi=ABI).encode_abi('redeemRecoveryShares',
            args=[asset, int(payload.shares), holder, int(payload.minRawOut)])
        result = await self.w3.provider.make_request('eth_call', [
            {'from': holder, 'to': core, 'data': data}, {'blockHash': Web3.to_hex(block['hash']), 'requireCanonical': True}])
        if 'error' in result:
            raise ValueError('Recovery redemption simulation failed')
        return self.w3.codec.decode(['uint256'], bytes.fromhex(result['result'][2:]))[0]


class RecoveryRedemption:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, payload):
        if self.rpc is None:
            self.rpc = RecoveryRedemptionRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            amount = await self.rpc.simulate(self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS, payload, block)
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': Web3.to_hex(block['hash']), 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'core': self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS, 'holder': Web3.to_checksum_address(payload.holder),
                'asset': Web3.to_checksum_address(payload.asset), 'shares': payload.shares,
                'minRawOut': payload.minRawOut, 'rawOut': str(amount)}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_recovery_redemption(request, service):
    try:
        payload = RedemptionRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        return JSONResponse({'error': 'A valid recovery-share redemption is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(payload)) if service else None
    return await handle_protocol_facts(request, bound, 'recovery-redemption',
                                       'Recovery-share redemption simulation is unavailable.')

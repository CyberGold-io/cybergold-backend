"""The Apps' fixed token/native wallet balances at one canonical block."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import ProtocolFactsRpc, handle_protocol_facts
from .finalized_multicall import ADDRESS as MULTICALL_ADDRESS, ContractClient
from .app_tokens import TOKENS

# Same Backend-owned assets as the App selector catalog. CYGLD uses the
# configured Core; asset identifiers select these fixed bindings, never a
# caller-provided contract or provider.
ABI = [{'type': 'function', 'name': 'balanceOf', 'stateMutability': 'view',
        'inputs': [{'name': 'account', 'type': 'address'}], 'outputs': [{'name': '', 'type': 'uint256'}]}]
NATIVE_MULTICALL_ABI = [{'type': 'function', 'name': 'getEthBalance', 'stateMutability': 'view',
    'inputs': [{'name': 'addr', 'type': 'address'}], 'outputs': [{'name': 'balance', 'type': 'uint256'}]}]


class WalletRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    holder: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class TokenBalanceSelection(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    tokenId: Literal['eth', 'cygld', 'xaut', 'paxg', 'usdt', 'usdc', 'weth']


class WalletBalancesRpc(ProtocolFactsRpc):
    async def display_block(self):
        # Ordinary balances use the configured provider and retain one exact
        # canonical read hash, without transaction-preparation cross-checks.
        block = await self.w3.eth.get_block('latest')
        return {'hash': Web3.to_hex(block['hash']), 'number': block['number'], 'timestamp': block['timestamp']}

    async def request(self, method, params):
        response = await self.w3.provider.make_request(method, params)
        if 'error' in response:
            raise ValueError('Wallet balance Multicall read failed')
        return response['result']

    async def aggregate_balances(self, addresses, holder, block):
        # Reuse the existing aggregate3 codec: one hash-pinned eth_call, with
        # allowFailure=true and independent decoding for every inner call.
        contracts = [{'address': Web3.to_checksum_address(address), 'abi': ABI,
                      'functionName': 'balanceOf', 'args': [holder]} for address in addresses]
        contracts.append({'address': MULTICALL_ADDRESS, 'abi': NATIVE_MULTICALL_ABI,
                          'functionName': 'getEthBalance', 'args': [holder]})
        return await ContractClient(self).multicall({'contracts': contracts, 'blockHash': block['hash']})

    async def balance(self, address, holder, block):
        data = self.w3.eth.contract(abi=ABI).encode_abi('balanceOf', args=[holder])
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Token balance read failed')
        return self.w3.codec.decode(['uint256'], bytes.fromhex(response['result'][2:]))[0]

    async def native_balance(self, holder, block):
        response = await self.w3.provider.make_request('eth_getBalance', [
            holder, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Native balance read failed')
        return int(response['result'], 16)


class WalletBalances:
    def __init__(self, settings, rpc=None, now=None):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, holder, *, ordinary=False):
        if self.rpc is None:
            self.rpc = WalletBalancesRpc(self.settings)
        holder = Web3.to_checksum_address(holder)
        async with asyncio.timeout(15):
            block = await self.rpc.display_block() if ordinary else await self.rpc.block()
            tokens = (('cygld', self.rpc.core), *TOKENS)
            results = await self.rpc.aggregate_balances([address for _, address in tokens], holder, block)
            values = [{'status': 'success', 'value': str(result['result'])} if result['status'] == 'success'
                      else {'status': 'failure', 'error': 'contract-read-failed'} for result in results]
            if not ordinary:
                await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'holder': holder, 'native': values[-1],
                'tokens': [{'id': name, 'address': Web3.to_checksum_address(address), 'balance': value}
                           for (name, address), value in zip(tokens, values[:-1], strict=True)]}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_wallet_balances(request, service):
    try:
        holder = WalletRequest.model_validate(dict(request.query_params)).holder
    except ValidationError:
        return JSONResponse({'error': 'A valid holder address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    # Bind per request: simultaneous wallets never mutate a shared holder.
    ordinary = request.query_params.get('purpose') == 'display'
    bound = SimpleNamespace(get=lambda: service.get(holder, ordinary=ordinary)) if service else None
    return await handle_protocol_facts(request, bound, 'wallet-balances',
                                       'Wallet balances are temporarily unavailable.')


class TokenBalance(WalletBalances):
    """Compatibility read for one of the existing fixed wallet assets."""
    async def get(self, holder, token_id):
        if self.rpc is None:
            self.rpc = WalletBalancesRpc(self.settings)
        holder = Web3.to_checksum_address(holder)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            try:
                if token_id == 'eth':
                    value = await self.rpc.native_balance(holder, block)
                else:
                    address = dict((('cygld', self.rpc.core), *TOKENS))[token_id]
                    value = await self.rpc.balance(Web3.to_checksum_address(address), holder, block)
                balance = {'status': 'success', 'value': str(value)}
            except Exception:
                balance = {'status': 'failure', 'error': 'contract-read-failed'}
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'holder': holder, 'tokenId': token_id, 'balance': balance}


async def handle_token_balance(request, service):
    query = dict(request.query_params)
    try:
        holder = WalletRequest.model_validate(query).holder
    except ValidationError:
        return JSONResponse({'error': 'A valid holder address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    try:
        token_id = TokenBalanceSelection.model_validate(query).tokenId
    except ValidationError:
        return JSONResponse({'error': 'tokenId must be one of eth, cygld, xaut, paxg, usdt, usdc or weth.'},
                            status_code=400, headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(holder, token_id)) if service else None
    return await handle_protocol_facts(request, bound, 'token-balance',
                                       'Wallet token balance is temporarily unavailable.')


class NativeBalance(WalletBalances):
    """RainbowKit/Wagmi's latest native balance, without unrelated token reads."""
    async def get(self, holder, *, ordinary=False):
        if self.rpc is None:
            self.rpc = WalletBalancesRpc(self.settings)
        holder = Web3.to_checksum_address(holder)
        async with asyncio.timeout(15):
            block = await self.rpc.display_block() if ordinary else await self.rpc.block()
            value = await self.rpc.native_balance(holder, block)
            if not ordinary:
                await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'holder': holder, 'balance': str(value)}


async def handle_native_balance(request, service):
    try:
        holder = WalletRequest.model_validate(dict(request.query_params)).holder
    except ValidationError:
        return JSONResponse({'error': 'A valid holder address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    ordinary = request.query_params.get('purpose') == 'display'
    bound = SimpleNamespace(get=lambda: service.get(holder, ordinary=ordinary)) if service else None
    return await handle_protocol_facts(request, bound, 'native-balance',
                                       'Native balance is temporarily unavailable.')

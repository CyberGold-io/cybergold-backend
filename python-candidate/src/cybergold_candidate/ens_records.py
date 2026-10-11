"""The Apps' Ethereum name/avatar records, using standard Web3.py ENS."""
import asyncio
from types import SimpleNamespace

from ens import AsyncENS
from ens.exceptions import InvalidName, ResolverNotFound
from ens.utils import normalize_name
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from .protocol_facts import ProtocolFacts, ProtocolFactsRpc, handle_protocol_facts
from .wallet_balances import WalletRequest


class BlockProvider(AsyncBaseProvider):
    """Pin native ENS contract calls without mutating the shared transport."""
    def __init__(self, provider, block):
        super().__init__()
        self.provider, self.block = provider, block

    async def make_request(self, method, params):
        if method == 'eth_call':
            params = [params[0], {'blockHash': self.block['hash'], 'requireCanonical': True}, *params[2:]]
        return await self.provider.make_request(method, params)

    async def disconnect(self):
        pass  # The owning product RPC closes its shared authenticated transport.


class EnsRecords(ProtocolFacts):
    async def nft_token_uri(self, record, block):
        """Read the two standard NFT avatar URI methods, never fetch metadata.

        Match the Apps' maintained Viem parser: NFT records select the token
        contract/id; all reads still use the configured Ethereum chain.
        Malformed/unsupported NFT records retain their text but cannot render.
        """
        if 'eip155:' not in record.lower():
            return None
        try:
            _, asset, token_id = record.split('/')
            namespace, address = asset.split(':')
            method = {'erc721': 'tokenURI', 'erc1155': 'uri'}[namespace.lower()]
            abi = [{'name': method, 'type': 'function', 'stateMutability': 'view',
                    'inputs': [{'name': 'tokenId', 'type': 'uint256'}],
                    'outputs': [{'name': '', 'type': 'string'}]}]
            data = self.rpc.w3.eth.contract(abi=abi).encode_abi(method, args=[int(token_id, 16 if token_id.startswith('0x') else 10)])
            response = await self.rpc.w3.provider.make_request('eth_call', [
                {'to': Web3.to_checksum_address(address), 'data': data},
                {'blockHash': block['hash'], 'requireCanonical': True}])
            if 'error' in response:
                raise ValueError('NFT avatar URI read failed')
            value = self.rpc.w3.codec.decode(['string'], bytes.fromhex(response['result'][2:]))[0]
            return {'status': 'success', 'value': value}
        except Exception:
            return {'status': 'failure', 'error': 'avatar-token-uri-unavailable'}

    async def get(self, mode, value):
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            ens = AsyncENS.from_web3(AsyncWeb3(BlockProvider(self.rpc.w3.provider, block)))
            # ENS adds a wall-clock stale-chain middleware by default. The Apps
            # use the existing configured-chain/canonical-block contract, and a
            # Sandbox fork can intentionally retain its source timestamp.
            ens.w3.middleware_onion.remove('stalecheck')
            if mode == 'name':
                holder = Web3.to_checksum_address(value)
                record = await ens.name(holder)
                payload = {'holder': holder, 'name': record or None}
            else:
                try:
                    record = await ens.get_text(value, 'avatar')
                except ResolverNotFound:
                    record = None
                payload = {'name': value, 'avatarRecord': record or None}
                if record:
                    token_uri = await self.nft_token_uri(record, block)
                    if token_uri is not None:
                        payload['nftTokenUri'] = token_uri
            await self.rpc.assert_canonical(block)
            return {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()}, **payload}


async def handle_ens(request, service, mode):
    try:
        value = (WalletRequest.model_validate(dict(request.query_params)).holder if mode == 'name'
                 else normalize_name(request.query_params.get('name', '')))
        if mode == 'avatar' and not value:
            raise InvalidName('ENS name required')
    except (ValidationError, InvalidName):
        return JSONResponse({'error': 'A valid holder address is required.' if mode == 'name' else 'A valid ENS name is required.'},
                            status_code=400, headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(mode, value)) if service else None
    return await handle_protocol_facts(request, bound, 'ens-'+mode, 'ENS observations are temporarily unavailable.')

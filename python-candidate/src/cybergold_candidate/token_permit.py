"""Selected ERC20 observations and optional native-permit qualification.

Only concrete token operations use the configured provider. Disposable permit
signatures stay in memory and run inside eth_call; user nonces are never cached.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import os
import time
from typing import Annotated

from eth_account import Account
from eth_account.messages import encode_typed_data, hash_domain
from fastapi.responses import JSONResponse
from hexbytes import HexBytes
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .finalized_multicall import ContractClient
from .protocol_facts import handle_protocol_facts
from .transaction_nonce import NonceRpc
from .quote_errors import QuoteFailure, rpc_failure
from .shared_reads import SharedReads


def function(name, inputs, outputs, mutability='view'):
    return {'type': 'function', 'name': name, 'stateMutability': mutability,
            'inputs': [{'name': label, 'type': kind} for label, kind in inputs],
            'outputs': [{'name': '', 'type': kind} for kind in outputs]}


ABI = [function(name, [], ['string']) for name in ('name', 'symbol', 'version')]
ABI += [function('decimals', [], ['uint8']), function('DOMAIN_SEPARATOR', [], ['bytes32']),
        function('nonces', [('owner', 'address')], ['uint256']),
        function('balanceOf', [('owner', 'address')], ['uint256']),
        function('allowance', [('owner', 'address'), ('spender', 'address')], ['uint256']),
        function('eip712Domain', [], ['bytes1', 'string', 'string', 'uint256', 'address', 'bytes32', 'uint256[]']),
        function('permit', [('owner', 'address'), ('spender', 'address'), ('value', 'uint256'),
                           ('deadline', 'uint256'), ('v', 'uint8'), ('r', 'bytes32'), ('s', 'bytes32')], [], 'nonpayable')]
SEEDS = {
    '0x45804880de22913dafe09f4980848ece6ecbaf78': ('Paxos Gold', '1'),
    '0x68749665ff8d2d112fa859aa293f07a622782f38': ('Tether Gold', '1'),
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': ('USD Coin', '2'),
}
DAI = '0x6b175474e89094c44da98b954eedeac495271d0f'
CAPABILITY_CACHE_SECONDS = 30 * 24 * 60 * 60
PERMIT_TYPES = {'Permit': [{'name': name, 'type': kind} for name, kind in (
    ('owner', 'address'), ('spender', 'address'), ('value', 'uint256'),
    ('nonce', 'uint256'), ('deadline', 'uint256'))]}
Address = Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')]


class MetadataRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    token: Address
    holder: Address | None = None


class TokenPermitRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    token: Address
    owner: Address


class UnreadableToken(ValueError):
    """Contract response was not the concrete ABI requested, without a revert."""


class TokenPermitRpc(NonceRpc):
    def __init__(self, settings, w3=None):
        super().__init__(settings, w3)
        self.helpers = getattr(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS',
                               os.environ.get('NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))

    async def block(self):
        block = await super().block()
        return {'hash': Web3.to_hex(block['hash']), 'number': block['number'], 'timestamp': block['timestamp']}

    async def assert_canonical(self, block):
        # The existing transaction-observation boundary, without a Core address
        # prerequisite for an independent ERC20 read.
        await super().assert_canonical({**block, 'hash': HexBytes(block['hash'])})

    async def request(self, method, params):
        response = await self.w3.provider.make_request(method, params)
        if 'error' in response:
            raise rpc_failure(response['error'])
        return response['result']

    async def token_read(self, token, name, block, args=()):
        entry = next(row for row in ABI if row['name'] == name)
        data = self.w3.eth.contract(abi=ABI).encode_abi(name, args=list(args))
        raw = bytes.fromhex((await self.request('eth_call', [
            {'to': token, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}]))[2:])
        try:
            values = self.w3.codec.decode([part['type'] for part in entry['outputs']], raw)
        except Exception as error:
            # Older ERC20s expose bytes32 metadata under the same selectors.
            if name in ('name', 'symbol') and len(raw) == 32:
                try:
                    return raw.rstrip(b'\0').decode('utf-8')
                except UnicodeError:
                    pass
            raise UnreadableToken('Token response could not be decoded') from error
        return values[0] if len(values) == 1 else values

    async def qualify(self, token, domain, block):
        account = Account.create()
        owner, spender = account.address, Web3.to_checksum_address(self.helpers)
        nonce, allowance = await asyncio.gather(self.token_read(token, 'nonces', block, [owner]),
                                                 self.token_read(token, 'allowance', block, [owner, spender]))
        message = {'owner': owner, 'spender': spender, 'value': 1, 'nonce': nonce,
                   'deadline': block['timestamp'] + 600}
        signature = Account.sign_message(encode_typed_data(domain, PERMIT_TYPES, message), account.key)
        args = [owner, spender, 1, message['deadline'], signature.v,
                signature.r.to_bytes(32, 'big'), signature.s.to_bytes(32, 'big')]
        invalid = [*args[:5], (signature.r ^ 1).to_bytes(32, 'big'), args[6]]
        def call(name, values):
            return {'address': token, 'abi': ABI, 'functionName': name, 'args': values}
        # One discarded execution context can inspect nonce/allowance changes.
        # Invalid first also proves rejection without contaminating valid state.
        rows = await ContractClient(self).multicall({'blockHash': block['hash'], 'contracts': [
            call('permit', invalid), call('nonces', [owner]), call('allowance', [owner, spender]),
            call('permit', args), call('nonces', [owner]), call('allowance', [owner, spender])]})
        if rows[0]['status'] != 'failure':
            return False
        expected = [(1, nonce), (2, allowance), (4, nonce + 1), (5, 1)]
        return rows[3]['status'] == 'success' and all(
            rows[index]['status'] == 'success' and rows[index]['result'] == value for index, value in expected)


def success(value):
    return {'status': 'success', 'value': value}


def field_error(error):
    if isinstance(error, UnreadableToken):
        return 'invalid-contract-response'
    if isinstance(error, QuoteFailure):
        return 'contract-read-failed' if error.code == 'quote-contract-reverted' else error.code
    return 'rpc-unavailable'


def capability(kind='unknown', **parts):
    return {'kind': kind, 'confidence': 'qualified' if kind == 'erc2612' else 'unknown', **parts}


class TokenObservations:
    def __init__(self, settings, rpc=None, now=None, clock=time.monotonic):
        self.settings, self.rpc = settings, rpc
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.clock, self.cache, self.pending = clock, OrderedDict(), SharedReads()

    async def observed(self, token, name, block, args=(), convert=lambda value: value):
        try:
            return success(convert(await self.rpc.token_read(token, name, block, args)))
        except Exception as error:
            return {'status': 'failure', 'error': field_error(error)}

    async def resolve_domain(self, token, separator, metadata, block):
        introspection = await self.observed(token, 'eip712Domain', block)
        if introspection['status'] == 'success':
            fields, name, version, chain, verifying, salt, extensions = introspection['value']
            mask = int.from_bytes(fields, 'big')
            if mask & ~31 or extensions:
                return capability(reason='unsupported-domain-extensions')
            values = (name, version, str(chain) if chain > 2**53 - 1 else chain, Web3.to_checksum_address(verifying), Web3.to_hex(salt))
            domain = {key: value for index, (key, value) in enumerate(zip(
                ('name', 'version', 'chainId', 'verifyingContract', 'salt'), values, strict=True)) if mask & (1 << index)}
            if Web3.to_hex(hash_domain(domain)).lower() == separator.lower():
                return {'domain': domain, 'source': 'erc5267'}
            return capability(reason='domain-separator-mismatch')
        if introspection.get('error') not in ('contract-read-failed', 'invalid-contract-response'):
            return capability('unavailable', reason=introspection['error'])
        seed = SEEDS.get(token.lower())
        if seed and self.rpc.chain_id in (1, 31338):
            domain = {'name': seed[0], 'version': seed[1], 'chainId': self.rpc.chain_id, 'verifyingContract': token}
            if Web3.to_hex(hash_domain(domain)).lower() == separator.lower():
                return {'domain': domain, 'source': 'seed'}
        # Bounded common reconstruction; none of these guesses reach the wallet
        # unless their full domain hash matches the token's observed separator.
        version = await self.observed(token, 'version', block)
        names = [metadata[key]['value'] for key in ('name', 'symbol') if metadata[key]['status'] == 'success']
        versions = list(dict.fromkeys(([version['value']] if version['status'] == 'success' else []) + ['1', '2', '']))
        for name in dict.fromkeys(names):
            for version_name in versions:
                for include_version in (True, False):
                    domain = {'name': name, 'chainId': self.rpc.chain_id, 'verifyingContract': token}
                    if include_version:
                        domain['version'] = version_name
                    if Web3.to_hex(hash_domain(domain)).lower() == separator.lower():
                        return {'domain': domain, 'source': 'reconstruction'}
        return capability(reason='domain-unresolved')

    async def discover(self, token, separator, metadata, block):
        if separator['status'] == 'failure':
            error = separator['error']
            if error not in ('contract-read-failed', 'invalid-contract-response'):
                return capability('unavailable', reason=error)
            nonce = await self.observed(token, 'nonces', block, ['0x' + '1' * 40], str)
            if error == 'contract-read-failed' and nonce.get('error') == 'contract-read-failed':
                return capability('none', confidence='observed', reason='standard-interface-not-observed')
            if nonce.get('error') not in (None, 'contract-read-failed', 'invalid-contract-response'):
                return capability('unavailable', reason=nonce['error'])
            return capability(reason='standard-domain-not-observed')
        resolved = await self.resolve_domain(token, separator['value'], metadata, block)
        if 'domain' not in resolved:
            return resolved
        if token.lower() == DAI:
            return capability('variant', confidence='observed', variant='dai', **resolved)
        if not self.rpc.helpers:
            return capability(reason='helpers-not-configured', **resolved)
        try:
            qualified = await self.rpc.qualify(token, resolved['domain'], block)
        except Exception as error:
            code = field_error(error)
            return capability('unknown' if code in ('contract-read-failed', 'invalid-contract-response') else 'unavailable',
                              reason='qualification-incomplete' if code in ('contract-read-failed', 'invalid-contract-response') else code,
                              **resolved)
        return capability('erc2612' if qualified else 'unknown',
                          reason='standard-state-semantics-qualified' if qualified else 'standard-state-semantics-unconfirmed',
                          observation={'blockNumber': str(block['number']), 'blockHash': block['hash']}, **resolved)

    async def reusable(self, token, separator, block):
        key = (self.rpc.chain_id, token.lower(), separator.get('value'))
        cached = self.cache.get(key)
        cacheable_separator = separator['status'] == 'success' or separator.get('error') in (
            'contract-read-failed', 'invalid-contract-response')
        if cacheable_separator and cached and self.clock() - cached[0] < CAPABILITY_CACHE_SECONDS:
            self.cache.move_to_end(key)
            return deepcopy(cached[1])
        # A changed separator invalidates previous domain observations, without
        # requiring implementation identity or introducing swap admission.
        for old in list(self.cache):
            if old[:2] == key[:2]:
                del self.cache[old]
        async def fetch():
            fields = await asyncio.gather(*(self.observed(token, name, block) for name in ('name', 'symbol', 'decimals')))
            metadata = dict(zip(('name', 'symbol', 'decimals'), fields, strict=True))
            result = {'metadata': metadata, 'authorization': await self.discover(token, separator, metadata, block)}
            await self.rpc.assert_canonical(block)
            if cacheable_separator and result['authorization']['kind'] != 'unavailable' and all(value['status'] == 'success' for value in fields):
                self.cache[key] = (self.clock(), deepcopy(result))
                while len(self.cache) > 512:
                    self.cache.popitem(last=False)
            return result
        return deepcopy(await self.pending.one(key, fetch))

    def context(self, block):
        return {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']), 'blockHash': block['hash'],
                'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()}

    async def metadata(self, token, holder=None, *, balance_only=False):
        if self.rpc is None:
            self.rpc = TokenPermitRpc(self.settings)
        token = Web3.to_checksum_address(token)
        holder = Web3.to_checksum_address(holder) if holder else None
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            if balance_only:
                result = {'metadata': {name: {'status': 'failure', 'error': 'not-requested'}
                                       for name in ('name', 'symbol', 'decimals')},
                          'authorization': capability(reason='not-requested')}
            else:
                separator = await self.observed(token, 'DOMAIN_SEPARATOR', block, convert=Web3.to_hex)
                result = await self.reusable(token, separator, block)
            if holder:
                result.update(holder=holder, balance=await self.observed(token, 'balanceOf', block, [holder], str))
            await self.rpc.assert_canonical(block)
            return {'context': self.context(block), 'token': {'chainId': self.rpc.chain_id, 'address': token}, **result}

    async def permit(self, token, owner):
        if self.rpc is None:
            self.rpc = TokenPermitRpc(self.settings)
        token, owner = Web3.to_checksum_address(token), Web3.to_checksum_address(owner)
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            separator, nonce, allowance = await asyncio.gather(
                self.observed(token, 'DOMAIN_SEPARATOR', block, convert=Web3.to_hex),
                self.observed(token, 'nonces', block, [owner], str),
                self.observed(token, 'allowance', block, [owner, Web3.to_checksum_address(self.rpc.helpers)], str)
                if self.rpc.helpers else asyncio.sleep(0, result={'status': 'failure', 'error': 'not-configured'}))
            reusable = await self.reusable(token, separator, block)
            await self.rpc.assert_canonical(block)
            return {'context': self.context(block), 'token': {'chainId': self.rpc.chain_id, 'address': token},
                    'owner': owner, 'spender': self.rpc.helpers, 'nonce': nonce, 'allowance': allowance,
                    'authorization': reusable['authorization']}

    async def close(self):
        await self.pending.close()
        self.cache.clear()
        if self.rpc:
            await self.rpc.close()


async def handle_token_metadata(request, service):
    try:
        payload = MetadataRequest.model_validate(dict(request.query_params))
    except ValidationError:
        return JSONResponse({'error': 'A valid token address and optional holder address are required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    balance_only = request.query_params.get('purpose') == 'balance'
    bound = SimpleNamespace(get=lambda: service.metadata(payload.token, payload.holder, balance_only=balance_only)) if service else None
    return await handle_protocol_facts(request, bound, 'token-metadata', 'Token metadata is temporarily unavailable.')


async def handle_token_permit(request, service):
    try:
        payload = TokenPermitRequest.model_validate(dict(request.query_params))
    except ValidationError:
        return JSONResponse({'error': 'Valid token and owner addresses are required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.permit(payload.token, payload.owner)) if service else None
    return await handle_protocol_facts(request, bound, 'token-permit', 'Token permit context is temporarily unavailable.')

"""Concrete ABI/domain/permit semantics, owner isolation and HTTP lifecycle."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from eth_account import Account
from eth_account.messages import encode_typed_data, hash_domain
from eth_utils.abi import collapse_if_tuple
import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.finalized_multicall import ADDRESS as MULTICALL
from cybergold_candidate.token_permit import ABI, CAPABILITY_CACHE_SECONDS, DAI, PERMIT_TYPES, SEEDS, TokenObservations, TokenPermitRpc
from cybergold_candidate.token_approval_gas import TokenApprovalGas, TokenApprovalRequest, TokenApprovalRpc

TOKEN, HELPERS, OWNER = ('0x' + digit * 40 for digit in ('3', '4', '5'))
HASH = '0x' + 'a' * 64
BLOCK = {'number': '0x65', 'timestamp': '0x6a000001', 'hash': HASH}
CODEC = Web3().codec
SELECTORS = {bytes(Web3.keccak(text=row['name'] + '(' + ','.join(collapse_if_tuple(p) for p in row['inputs']) + ')')[:4]): row for row in ABI}


class Provider(AsyncBaseProvider):
    def __init__(self, domain=None, *, introspection=True, legacy=False, failures=None, semantics=True, noop=False, extensions=(), reorg=False, blocked=False):
        super().__init__()
        self.domain = domain or {'name': 'Domain different from symbol', 'version': '17', 'chainId': 31338, 'verifyingContract': TOKEN,
                                 'salt': '0x' + 'c' * 64}
        self.introspection, self.legacy, self.failures = introspection, legacy, failures or {}
        self.semantics, self.noop, self.extensions, self.reorg, self.blocked = semantics, noop, extensions, reorg, blocked
        self.calls, self.probes, self.state = [], 0, {}
        self.started, self.cancelled = asyncio.Event(), 0

    def execute(self, data, state):
        raw = bytes.fromhex(data[2:])
        entry = SELECTORS[raw[:4]]
        name = entry['name']
        if name in self.failures:
            return False, b''
        args = CODEC.decode([part['type'] for part in entry['inputs']], raw[4:])
        if name == 'name':
            value = 'Display token'
        elif name == 'symbol':
            value = 'TOK'
        elif name == 'version':
            return False, b''
        elif name == 'decimals':
            value = 6
        elif name == 'DOMAIN_SEPARATOR':
            value = hash_domain(self.domain)
        elif name == 'eip712Domain':
            if not self.introspection:
                return False, b''
            keys = ('name', 'version', 'chainId', 'verifyingContract', 'salt')
            mask = sum(1 << index for index, key in enumerate(keys) if key in self.domain)
            values = [self.domain.get(key, '' if key in ('name', 'version') else 0 if key == 'chainId'
                       else '0x' + '0' * 40 if key == 'verifyingContract' else b'\0' * 32) for key in keys]
            if isinstance(values[-1], str):
                values[-1] = bytes.fromhex(values[-1][2:])
            return True, CODEC.encode([part['type'] for part in entry['outputs']], [mask.to_bytes(1), *values, list(self.extensions)])
        elif name == 'nonces':
            value = state.get(('nonce', args[0]), int(args[0], 16) % 100 + 2**100)
        elif name == 'allowance':
            value = state.get(('allowance', *args), 0)
        elif name == 'balanceOf':
            value = 2**200 + int(args[0], 16)
        elif name == 'permit':
            if self.noop:
                return True, b''
            owner, spender, value, deadline, v, r, s = args
            nonce = state.get(('nonce', owner), int(owner, 16) % 100 + 2**100)
            message = dict(owner=owner, spender=spender, value=value, nonce=nonce, deadline=deadline)
            try:
                signer = Account.recover_message(encode_typed_data(self.domain, PERMIT_TYPES, message),
                                                 vrs=(v, int.from_bytes(r), int.from_bytes(s)))
            except Exception:
                return False, b''
            if signer.lower() != owner.lower():
                return False, b''
            if self.semantics:
                state[('nonce', owner)] = nonce + 1
                state[('allowance', owner, spender)] = value
            return True, b''
        else:
            raise AssertionError(name)
        if self.legacy and name in ('name', 'symbol'):
            return True, value.encode().ljust(32, b'\0')
        return True, CODEC.encode([part['type'] for part in entry['outputs']], [value])

    async def make_request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        if method == 'eth_chainId':
            result = '0x7a6a'
        elif method == 'eth_getBlockByNumber':
            result = {**BLOCK, 'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_estimateGas':
            result = hex(2**100 + 7)
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if params[0]['to'].lower() == MULTICALL.lower():
                self.probes += 1
                raw = bytes.fromhex(params[0]['data'][2:])
                calls = CODEC.decode(['(address,bool,bytes)[]'], raw[4:])[0]
                discarded = deepcopy(self.state)
                rows = [self.execute(Web3.to_hex(data), discarded) for _, _, data in calls]
                result = Web3.to_hex(CODEC.encode(['(bool,bytes)[]'], [rows]))
            else:
                raw = bytes.fromhex(params[0]['data'][2:])
                entry = SELECTORS[raw[:4]]
                failure = self.failures.get(entry['name'])
                if failure == 'rpc':
                    return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'private-provider-password'}}
                if failure == 'empty':
                    result = '0x'
                else:
                    good, data = self.execute(params[0]['data'], deepcopy(self.state))
                    if not good:
                        return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'execution reverted'}}
                    result = Web3.to_hex(data)
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def settings():
    return SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture', NEXT_PUBLIC_CHAIN_ID='31338',
                           NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x' + '9' * 40, NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,
                           NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS)


def service(provider):
    config = settings()
    return TokenObservations(config, TokenPermitRpc(config, AsyncWeb3(provider)))


class TokenPermitTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_token_metadata_requires_no_core_binding(self):
        config = settings()
        del config.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS
        del config.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS
        observer = TokenObservations(config, TokenPermitRpc(config, AsyncWeb3(Provider())))
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'erc2612')

    async def test_imported_erc5267_salt_token_qualifies_actual_valid_and_invalid_signatures(self):
        provider = Provider()
        result = await service(provider).metadata(TOKEN, OWNER)
        auth = result['authorization']
        self.assertEqual((auth['kind'], auth['confidence'], auth['source']), ('erc2612', 'qualified', 'erc5267'))
        self.assertEqual(auth['domain'], provider.domain)
        self.assertEqual(result['metadata']['decimals'], {'status': 'success', 'value': 6})
        self.assertEqual(result['balance']['value'], str(2**200 + int(OWNER, 16)))
        self.assertEqual(provider.probes, 1)
        self.assertEqual(provider.state, {})
        self.assertNotIn('signature', json.dumps(result))
        for method, params in provider.calls:
            if method == 'eth_call':
                self.assertEqual(params[1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_seeded_domains_do_not_require_version_getter(self):
        for token, (name, version) in SEEDS.items():
            token = Web3.to_checksum_address(token)
            domain = {'name': name, 'version': version, 'chainId': 31338, 'verifyingContract': token}
            result = await service(Provider(domain, introspection=False)).metadata(token)
            self.assertEqual(result['authorization']['source'], 'seed')
            self.assertEqual(result['authorization']['kind'], 'erc2612')
            self.assertEqual(result['authorization']['domain'], domain)

    async def test_bounded_common_reconstruction_matches_separator_and_bytes32_metadata(self):
        domain = {'name': 'Display token', 'version': '2', 'chainId': 31338, 'verifyingContract': TOKEN}
        result = await service(Provider(domain, introspection=False, legacy=True)).metadata(TOKEN)
        self.assertEqual(result['metadata']['name']['value'], 'Display token')
        self.assertEqual(result['metadata']['symbol']['value'], 'TOK')
        self.assertEqual(result['authorization']['source'], 'reconstruction')
        self.assertEqual(result['authorization']['domain'], domain)

    async def test_large_introspected_chain_id_preserved_losslessly(self):
        domain = {'name': 'Large chain domain', 'version': '1', 'chainId': 2**200 + 7, 'verifyingContract': TOKEN}
        result = await service(Provider(domain)).metadata(TOKEN)
        self.assertEqual(result['authorization']['domain']['chainId'], str(2**200 + 7))
        self.assertEqual(result['authorization']['kind'], 'erc2612')

    async def test_missing_version_field_preserved(self):
        domain = {'name': 'No version', 'chainId': 31338, 'verifyingContract': TOKEN}
        result = await service(Provider(domain)).metadata(TOKEN)
        self.assertNotIn('version', result['authorization']['domain'])
        self.assertEqual(result['authorization']['kind'], 'erc2612')

    async def test_domain_extensions_and_unresolved_legacy_keep_ordinary_authorization_unknown(self):
        for provider in (Provider(extensions=[99]), Provider(introspection=False)):
            result = await service(provider).metadata(TOKEN)
            self.assertEqual(result['authorization']['kind'], 'unknown')
            self.assertEqual(provider.probes, 0)

    async def test_dai_variant_distinct_from_amount_permit(self):
        domain = {'name': 'Dai Stablecoin', 'version': '1', 'chainId': 31338, 'verifyingContract': DAI}
        provider = Provider(domain)
        result = await service(provider).metadata(DAI)
        self.assertEqual(result['authorization']['kind'], 'variant')
        self.assertEqual(result['authorization']['variant'], 'dai')
        self.assertEqual(provider.probes, 0)

    async def test_reverts_empty_fallback_and_rpc_unavailability_distinct(self):
        for failures, kind in (({'DOMAIN_SEPARATOR': 'revert', 'nonces': 'revert'}, 'none'),
                               ({'DOMAIN_SEPARATOR': 'empty', 'nonces': 'empty'}, 'unknown'),
                               ({'DOMAIN_SEPARATOR': 'rpc'}, 'unavailable')):
            provider = Provider(failures=failures)
            result = await service(provider).metadata(TOKEN)
            self.assertEqual(result['authorization']['kind'], kind)
            self.assertNotIn('password', json.dumps(result))

    async def test_noop_and_incomplete_state_semantics_do_not_claim_standard_permit(self):
        for provider in (Provider(noop=True), Provider(semantics=False)):
            result = await service(provider).metadata(TOKEN)
            self.assertEqual(result['authorization']['kind'], 'unknown')
            self.assertEqual(result['authorization']['reason'], 'standard-state-semantics-unconfirmed')

    async def test_metadata_and_balance_failures_do_not_invent_details_or_zero(self):
        result = await service(Provider(failures={'decimals': 'empty', 'balanceOf': 'rpc'})).metadata(TOKEN, OWNER)
        self.assertEqual(result['metadata']['decimals'], {'status': 'failure', 'error': 'invalid-contract-response'})
        self.assertEqual(result['balance'], {'status': 'failure', 'error': 'rpc-unavailable'})
        self.assertEqual(result['metadata']['name']['status'], 'success')

    async def test_concurrent_owners_and_fresh_nonces_allowances_with_reused_discovery(self):
        provider, other = Provider(), '0x' + '6' * 40
        observer = service(provider)
        first, second = await asyncio.gather(observer.permit(TOKEN, OWNER), observer.permit(TOKEN, other))
        self.assertNotEqual(first['nonce']['value'], second['nonce']['value'])
        self.assertEqual(provider.probes, 1)
        provider.state[('nonce', OWNER.lower())] = 777
        provider.state[('allowance', OWNER.lower(), HELPERS.lower())] = 2**200
        third = await observer.permit(TOKEN, OWNER)
        self.assertEqual(third['nonce']['value'], '777')
        self.assertEqual(third['allowance']['value'], str(2**200))
        self.assertEqual(provider.probes, 1)

    async def test_balance_only_refresh_after_cache_expiry_never_discovers_or_reads_metadata(self):
        provider, clock = Provider(), [0]
        observer = service(provider)
        observer.clock = lambda: clock[0]
        await observer.metadata(TOKEN)
        self.assertEqual(provider.probes, 1)
        clock[0] = CAPABILITY_CACHE_SECONDS + 20
        provider.calls.clear()
        for _ in range(2):
            result = await observer.metadata(TOKEN, OWNER, balance_only=True)
            self.assertEqual(result['balance']['value'], str(2**200 + int(OWNER, 16)))
            self.assertEqual(result['authorization'], {'kind': 'unknown', 'confidence': 'unknown', 'reason': 'not-requested'})
            self.assertTrue(all(field == {'status': 'failure', 'error': 'not-requested'} for field in result['metadata'].values()))
        self.assertEqual(provider.probes, 1)
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(SELECTORS[bytes.fromhex(params[0]['data'][2:10])]['name'] == 'balanceOf' for params in calls))
        # The same expired cache still qualifies when explicitly resolving a token.
        await observer.metadata(TOKEN)
        self.assertEqual(provider.probes, 2)

    async def test_balance_only_rpc_failure_remains_per_field_unavailability(self):
        provider = Provider(failures={'balanceOf': 'rpc'})
        result = await service(provider).metadata(TOKEN, OWNER, balance_only=True)
        self.assertEqual(result['balance'], {'status': 'failure', 'error': 'rpc-unavailable'})
        self.assertEqual(result['authorization']['reason'], 'not-requested')
        self.assertNotIn('password', json.dumps(result))
        self.assertEqual(provider.probes, 0)

    async def test_balance_only_http_transport_and_existing_canonical_failure(self):
        app = create_app(token_observations=service(Provider()))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/tokens/metadata?token='+TOKEN+'&holder='+OWNER+'&purpose=balance')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['authorization']['reason'], 'not-requested')
            self.assertEqual(response.json()['balance']['status'], 'success')
            self.assertEqual(response.headers['cache-control'], 'no-store')
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).metadata(TOKEN, OWNER, balance_only=True)

    async def test_monthly_boundary_requalifies_unconfirmed_permit_with_unchanged_separator(self):
        provider, clock = Provider(semantics=False), [0]
        observer = service(provider)
        observer.clock = lambda: clock[0]
        first = await observer.metadata(TOKEN)
        self.assertEqual(first['authorization']['kind'], 'unknown')
        self.assertEqual(provider.probes, 1)
        provider.semantics = True
        clock[0] = CAPABILITY_CACHE_SECONDS - 1
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'unknown')
        self.assertEqual(provider.probes, 1)
        clock[0] = CAPABILITY_CACHE_SECONDS
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'erc2612')
        self.assertEqual(provider.probes, 2)
        self.assertEqual(len(observer.cache), 1)
        await observer.close()
        self.assertEqual(len(observer.cache), 0)

    async def test_negative_capability_is_cached_monthly_and_reappeared_separator_refreshes_immediately(self):
        provider, clock = Provider(failures={'DOMAIN_SEPARATOR': 'revert', 'nonces': 'revert'}), [0]
        observer = service(provider)
        observer.clock = lambda: clock[0]
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'none')
        self.assertEqual(len(observer.cache), 1)
        def count(name):
            return sum(1 for method, params in provider.calls if method == 'eth_call' and
                params[0]['to'].lower() != MULTICALL.lower() and
                SELECTORS[bytes.fromhex(params[0]['data'][2:10])]['name'] == name)
        clock[0] = CAPABILITY_CACHE_SECONDS - 1
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'none')
        self.assertEqual((count('DOMAIN_SEPARATOR'), count('nonces'), count('name')), (2, 1, 1))
        # The token adds its domain before the original monthly entry expires.
        provider.failures.clear()
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'erc2612')
        self.assertEqual(provider.probes, 1)
        self.assertEqual(len(observer.cache), 1)

    async def test_monthly_expiry_refreshes_missing_and_empty_standard_domain_observations(self):
        for failure, expected in (('revert', 'none'), ('empty', 'unknown')):
            provider, clock = Provider(failures={'DOMAIN_SEPARATOR': failure, 'nonces': failure}), [0]
            observer = service(provider)
            observer.clock = lambda: clock[0]
            first = await observer.metadata(TOKEN)
            self.assertEqual(first['authorization']['kind'], expected)
            provider.calls.clear()
            clock[0] = CAPABILITY_CACHE_SECONDS - 1
            self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], expected)
            names = [SELECTORS[bytes.fromhex(params[0]['data'][2:10])]['name']
                     for method, params in provider.calls if method == 'eth_call']
            self.assertEqual(names, ['DOMAIN_SEPARATOR'])
            self.assertEqual(provider.probes, 0)
            provider.calls.clear()
            clock[0] = CAPABILITY_CACHE_SECONDS
            self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], expected)
            names = [SELECTORS[bytes.fromhex(params[0]['data'][2:10])]['name']
                     for method, params in provider.calls if method == 'eth_call']
            self.assertEqual(set(names), {'DOMAIN_SEPARATOR', 'name', 'symbol', 'decimals', 'nonces'})
            self.assertEqual(provider.probes, 0)

    async def test_monthly_reuse_keeps_owner_nonce_allowance_and_balance_fresh(self):
        provider, clock = Provider(), [0]
        observer = service(provider)
        observer.clock = lambda: clock[0]
        await observer.metadata(TOKEN, OWNER)
        clock[0] = CAPABILITY_CACHE_SECONDS - 1
        provider.state[('nonce', OWNER.lower())] = 777
        provider.state[('allowance', OWNER.lower(), HELPERS.lower())] = 2**200
        fresh = await observer.permit(TOKEN, OWNER)
        self.assertEqual(fresh['nonce']['value'], '777')
        self.assertEqual(fresh['allowance']['value'], str(2**200))
        metadata = await observer.metadata(TOKEN, OWNER)
        self.assertEqual(metadata['balance']['value'], str(2**200 + int(OWNER, 16)))
        self.assertEqual(provider.probes, 1)
        calls = [SELECTORS[bytes.fromhex(params[0]['data'][2:10])]['name'] for method, params in provider.calls
                 if method == 'eth_call' and params[0]['to'].lower() != MULTICALL.lower()]
        self.assertEqual(calls.count('DOMAIN_SEPARATOR'), 3)
        self.assertEqual(calls.count('balanceOf'), 2)

    async def test_metadata_rpc_failure_is_not_retained_for_monthly_reuse(self):
        provider = Provider(failures={'name': 'rpc'})
        observer = service(provider)
        first = await observer.metadata(TOKEN)
        self.assertEqual(first['metadata']['name'], {'status': 'failure', 'error': 'rpc-unavailable'})
        self.assertEqual(len(observer.cache), 0)
        provider.failures.clear()
        second = await observer.metadata(TOKEN)
        self.assertEqual(second['metadata']['name'], {'status': 'success', 'value': 'Display token'})
        self.assertEqual(provider.probes, 2)

    async def test_cached_negative_does_not_mask_rpc_unavailability_or_delay_retry(self):
        provider = Provider(failures={'DOMAIN_SEPARATOR': 'revert', 'nonces': 'revert'})
        observer = service(provider)
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'none')
        provider.failures['DOMAIN_SEPARATOR'] = 'rpc'
        result = await observer.metadata(TOKEN)
        self.assertEqual(result['authorization']['kind'], 'unavailable')
        self.assertNotIn('password', json.dumps(result))
        self.assertEqual(len(observer.cache), 0)
        provider.failures.clear()
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'erc2612')
        self.assertEqual(provider.probes, 1)

    async def test_changed_domain_separator_invalidates_reusable_metadata(self):
        provider, observer = Provider(), None
        observer = service(provider)
        clock = [0]
        observer.clock = lambda: clock[0]
        await observer.metadata(TOKEN)
        clock[0] = CAPABILITY_CACHE_SECONDS // 2
        provider.domain['version'] = '18'
        result = await observer.permit(TOKEN, OWNER)
        self.assertEqual(result['authorization']['domain']['version'], '18')
        self.assertEqual(provider.probes, 2)

    async def test_unavailable_observation_not_cached_as_unsupported(self):
        provider = Provider(failures={'DOMAIN_SEPARATOR': 'rpc'})
        observer = service(provider)
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'unavailable')
        provider.failures.clear()
        self.assertEqual((await observer.metadata(TOKEN))['authorization']['kind'], 'erc2612')

    async def test_reorg_discards_result(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).permit(TOKEN, OWNER)

    async def test_last_caller_cancellation_reaches_rpc(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).permit(TOKEN, OWNER))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled, 3)

    async def test_http_selected_addresses_validation_no_store_and_head(self):
        app = create_app(token_observations=service(Provider()))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = '/api/tokens/metadata?token=' + TOKEN + '&holder=' + OWNER
            response = await client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual((await client.head(path)).content, b'')
            self.assertEqual((await client.get('/api/account/token-permit?token='+TOKEN+'&owner='+OWNER)).status_code, 200)
            self.assertEqual((await client.get('/api/account/token-permit?token=bad&owner='+OWNER)).status_code, 400)
            self.assertEqual((await client.get('/api/tokens/metadata?token='+TOKEN+'&holder=bad')).status_code, 400)

    async def test_exact_helpers_approval_gas_zero_and_wide_amount(self):
        provider = Provider()
        config = settings()
        observer = TokenApprovalGas(config, TokenApprovalRpc(config, AsyncWeb3(provider)))
        for amount in ('0', str(2**200)):
            result = await observer.get(TokenApprovalRequest(owner=OWNER, token=TOKEN, amount=amount))
            self.assertEqual(result['gas'], str(2**100+7))
            self.assertEqual(result['amount'], amount)
            self.assertEqual(result['spender'], HELPERS)
            tx = next(params[0] for method, params in reversed(provider.calls) if method == 'eth_estimateGas')
            args = CODEC.decode(['address', 'uint256'], bytes.fromhex(tx['data'][10:]))
            self.assertEqual(args, (HELPERS.lower(), int(amount)))


if __name__ == '__main__':
    unittest.main()

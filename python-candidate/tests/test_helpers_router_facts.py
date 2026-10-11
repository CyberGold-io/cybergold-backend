"""Canonical Helpers ABI, partial unknowns and operation cancellation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3, Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.helpers_router_facts import ABI, HelpersRouterFacts
from cybergold_candidate.protocol_facts import ProtocolFactsRpc
from test_protocol_facts import HASH, Provider

REFERENCE = json.loads(Path(sys.argv[1]).read_text())


def service(provider, helpers=True):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer synthetic',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'] if helpers else None)
    return HelpersRouterFacts(settings, ProtocolFactsRpc(settings, AsyncWeb3(provider), abi=ABI))


class AdapterProvider(Provider):
    def __init__(self, code='0x6000', code_failure=False, code_blocked=False):
        super().__init__()
        self.code, self.code_failure, self.code_blocked = code, code_failure, code_blocked
        self.code_started, self.code_cancelled = asyncio.Event(), False

    async def make_request(self, method, params):
        if method != 'eth_getCode':
            return await super().make_request(method, params)
        self.calls.append((method, params))
        self.code_started.set()
        if self.code_blocked:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.code_cancelled = True
                raise
        if self.code_failure:
            return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'https://password@private.invalid'}}
        return {'jsonrpc': '2.0', 'id': 1, 'result': self.code}


class SelectorProvider(Provider):
    def __init__(self, installed=True, unavailable=False, overrides=None, blocked=False):
        super().__init__()
        self.installed, self.unavailable = installed, unavailable
        self.overrides, self.selector_blocked = overrides or {}, blocked
        self.selector_started, self.selector_cancelled = asyncio.Event(), False

    async def make_request(self, method, params):
        prefix = Web3.to_hex(Web3.keccak(text='facetAddress(bytes4)')[:4])
        if method != 'eth_call' or not params[0]['data'].startswith(prefix):
            return await super().make_request(method, params)
        self.calls.append((method, params))
        selector = '0x' + params[0]['data'][10:18]
        assert selector in REFERENCE['selectors'].values()
        self.selector_started.set()
        if self.selector_blocked:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.selector_cancelled = True
                raise
        installed = self.overrides.get(selector, self.installed)
        if self.unavailable or installed == 'unavailable':
            return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'private-password'}}
        address = '0x' + ('8' if installed else '0') * 40
        return {'jsonrpc': '2.0', 'id': 1, 'result': Web3.to_hex(Web3().codec.encode(['address'], [address]))}


class HelpersRouterFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_permit_selector_observation_opt_in_installed_absent_and_unavailable(self):
        for provider, expected in ((SelectorProvider(), {'status': 'success', 'value': True}),
                                  (SelectorProvider(installed=False), {'status': 'success', 'value': False}),
                                  (SelectorProvider(unavailable=True), {'status': 'failure', 'error': 'contract-read-failed'})):
            observer = service(provider)
            self.assertNotIn('tokenPermitIssuance', (await observer.get())['configuration'])
            value = await observer.get(token_permit=True)
            self.assertEqual(value['configuration']['tokenPermitIssuance'], expected)
            self.assertNotIn('password', json.dumps(value))
            reads = [params for method, params in provider.calls if method == 'eth_call']
            self.assertEqual(len(reads), 13)
            self.assertEqual(reads[-1][1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_native_permit_selector_http_opt_in(self):
        app = create_app(helpers_router_facts=service(SelectorProvider(installed=False)))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/governance/helpers-facts?tokenPermitIssuance=true')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['configuration']['tokenPermitIssuance'], {'status': 'success', 'value': False})

    async def test_mixed_basket_selectors_are_optional_fresh_and_independent(self):
        exact_in = REFERENCE['selectors']['issueFromBasketExactInWithMixedPermits']
        exact_out = REFERENCE['selectors']['issueFromBasketExactOutWithMixedPermits']
        provider = SelectorProvider(overrides={exact_in: False, exact_out: True})
        observer = service(provider)
        bare = await observer.get()
        self.assertEqual(len(bare['configuration']), 6)
        value = (await observer.get(basket_permit=True))['configuration']
        self.assertNotIn('tokenPermitIssuance', value)
        self.assertEqual(value['basketPermitIssuanceExactIn'], {'status': 'success', 'value': False})
        self.assertEqual(value['basketPermitIssuanceExactOut'], {'status': 'success', 'value': True})
        provider.overrides[exact_in] = True
        provider.overrides[exact_out] = 'unavailable'
        value = (await observer.get(basket_permit=True))['configuration']
        self.assertEqual(value['basketPermitIssuanceExactIn'], {'status': 'success', 'value': True})
        self.assertEqual(value['basketPermitIssuanceExactOut'], {'status': 'failure', 'error': 'contract-read-failed'})
        self.assertEqual(value['helperFeePpm'], {'status': 'success', 'value': '0'})
        self.assertNotIn('password', json.dumps(value))
        reads = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(reads), 22)
        selectors = [params for params in reads if params[0]['data'].startswith('0xcdffacc6')]
        self.assertEqual(['0x' + params[0]['data'][10:18] for params in selectors],
                         [exact_in, exact_out, exact_in, exact_out])
        self.assertTrue(all(params[1] == {'blockHash': HASH, 'requireCanonical': True} for params in selectors))

    async def test_mixed_basket_http_option_and_missing_helpers_preserve_other_facts(self):
        app = create_app(helpers_router_facts=service(SelectorProvider(installed=False)))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            value = await client.get('/api/governance/helpers-facts?basketPermitIssuance=true&tokenPermitIssuance=true')
            self.assertEqual(value.status_code, 200)
            self.assertEqual(value.headers['cache-control'], 'no-store')
            facts = value.json()['configuration']
            for name in ('tokenPermitIssuance', 'basketPermitIssuanceExactIn', 'basketPermitIssuanceExactOut'):
                self.assertEqual(facts[name], {'status': 'success', 'value': False})
            bare = (await client.get('/api/governance/helpers-facts?basketPermitIssuance=false')).json()['configuration']
            self.assertEqual(len(bare), 6)
        provider = SelectorProvider()
        missing = await service(provider, helpers=False).get(token_permit=True, basket_permit=True)
        self.assertTrue(all(field == {'status': 'failure', 'error': 'not-configured'}
                            for field in missing['configuration'].values()))
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_cancellation_reaches_mixed_basket_selector_read(self):
        provider = SelectorProvider(blocked=True)
        task = asyncio.create_task(service(provider).get(basket_permit=True))
        await provider.selector_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.selector_cancelled)

    async def test_adapter_code_presence_empty_code_and_unknown_are_distinct(self):
        adapter = '0x' + '9' * 40
        for provider, expected in ((AdapterProvider(), {'status': 'success', 'value': True}),
                (AdapterProvider(code='0x00'), {'status': 'success', 'value': True}),
                (AdapterProvider(code='0x'), {'status': 'success', 'value': False}),
                (AdapterProvider(code_failure=True), {'status': 'failure', 'error': 'contract-read-failed'}),
                (AdapterProvider(code='invalid'), {'status': 'failure', 'error': 'contract-read-failed'})):
            value = await service(provider).get(adapter)
            self.assertEqual(value['adapter'], {'address': adapter, 'codePresent': expected})
            self.assertEqual(value['configuration']['approvedAdapters']['value'], [adapter, '0x' + '0' * 40])
            self.assertEqual([params for method, params in provider.calls if method == 'eth_getCode'],
                             [[adapter, {'blockHash': HASH, 'requireCanonical': True}]])
            self.assertNotIn('password', json.dumps(value))

    async def test_fresh_adapter_reads_do_not_share_another_address_or_old_presence(self):
        provider = AdapterProvider()
        observer = service(provider)
        self.assertTrue((await observer.get('0x' + '9' * 40))['adapter']['codePresent']['value'])
        provider.code = '0x'
        self.assertFalse((await observer.get('0x' + '8' * 40))['adapter']['codePresent']['value'])
        self.assertEqual([params[0] for method, params in provider.calls if method == 'eth_getCode'],
                         ['0x' + '9' * 40, '0x' + '8' * 40])

    async def test_cancellation_reaches_optional_adapter_code_read(self):
        provider = AdapterProvider(code_blocked=True)
        task = asyncio.create_task(service(provider).get('0x' + '9' * 40))
        await provider.code_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.code_cancelled)

    async def test_optional_adapter_http_preserves_bare_facts_and_address_errors(self):
        provider = AdapterProvider()
        app = create_app(helpers_router_facts=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            self.assertNotIn('adapter', (await client.get('/api/governance/helpers-facts')).json())
            path = '/api/governance/helpers-facts?adapter=' + '0x' + '9' * 40
            value = await client.get(path)
            self.assertEqual(value.status_code, 200)
            self.assertTrue(value.json()['adapter']['codePresent']['value'])
            self.assertEqual(value.headers['cache-control'], 'no-store')
            head = await client.head(path)
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b'')
            self.assertEqual((await client.get('/api/governance/helpers-facts?adapter=bad')).status_code, 400)

    async def test_canonical_app_calldata_and_one_block(self):
        provider = Provider()
        result = await service(provider).get()
        values = result['configuration']
        self.assertEqual(values['helperFeePpm']['value'], '0')
        self.assertIs(values['paused']['value'], False)
        self.assertEqual(values['approvedAdapters']['value'], ['0x'+'9'*40, '0x'+'0'*40])
        self.assertEqual(result['helpers'], REFERENCE['helpers'])
        self.assertEqual(result['context']['blockHash'], HASH)
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(calls), 6)
        for params in calls:
            self.assertEqual(params[0]['to'], REFERENCE['helpers'])
            self.assertIn(params[0]['data'], provider.rows)
            self.assertEqual(params[1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_failed_allowlist_is_unknown_not_empty_and_other_fields_survive(self):
        value = await service(Provider(failures=('approvedAdapters',))).get()
        self.assertEqual(value['configuration']['approvedAdapters'], {'status':'failure','error':'contract-read-failed'})
        self.assertEqual(value['configuration']['helperFeePpm']['value'], '0')
        self.assertIs(value['configuration']['paused']['value'], False)
        self.assertNotIn('password', json.dumps(value))

    async def test_missing_helpers_does_no_contract_calls(self):
        provider = Provider()
        value = await service(provider, helpers=False).get()
        self.assertIsNone(value['helpers'])
        self.assertTrue(all(field == {'status':'failure','error':'not-configured'}
                            for field in value['configuration'].values()))
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_reorg_fails_whole_observation(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get()

    async def test_caller_cancellation_cancels_all_six_reads(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get())
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled, 6)

    async def test_fixed_http_operation_and_redacted_failure(self):
        for provider, expected in ((Provider(), 200), (Provider(reorg=True), 503)):
            app = create_app(helpers_router_facts=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/api/governance/helpers-facts?target=http://untrusted.invalid')
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('password', response.text)
            if expected == 503:
                self.assertIn('correlationId', response.json())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])

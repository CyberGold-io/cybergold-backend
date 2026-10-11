"""Configured diamond authority reads preserve native Viem wire and partial errors."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.governance_authority import GovernanceAuthority, GovernanceAuthorityRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x' + 'a' * 64


class Provider(AsyncBaseProvider):
    def __init__(self, failed=None, reorg=False, blocked=False, chain='0x7a6a'):
        super().__init__()
        self.failed, self.reorg, self.blocked, self.chain = failed, reorg, blocked, chain
        self.calls, self.started, self.cancelled = [], asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId': result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            row = next(row for row in REFERENCE if row['address'].lower() == params[0]['to'].lower())
            read = next(read for read in row['calls'] if read['data'] == params[0]['data'])
            if read['name'] == self.failed:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'https://password@private.invalid'}}
            result = read['encodedResult']
        else: raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self): pass


def service(provider, configured=True):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture', NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE[0]['address'] if configured else None,
        NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS=REFERENCE[1]['address'], NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=REFERENCE[2]['address'])
    return GovernanceAuthority(settings, GovernanceAuthorityRpc(settings, AsyncWeb3(provider)))


class AuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_configured_surfaces_match_viem_wire_at_one_canonical_hash(self):
        provider = Provider(); observer = service(provider)
        for row in REFERENCE:
            result = await observer.get(row['surface'], row['account'])
            self.assertEqual(result['safeWallet']['value'].lower(), row['safe'])
            self.assertEqual(result['paused']['value'], row['calls'][1]['result'])
            self.assertEqual(result['accountCanPause'], {'status': 'success', 'value': True})
            self.assertEqual(result['accountCanUnpause'], {'status': 'success', 'value': False})
            self.assertEqual(result['safeCanUnpause'], {'status': 'success', 'value': True})
            self.assertEqual(result['context']['blockNumber'], '101')
        reads = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(reads), 15)
        for actual, expected in zip(reads, [call for row in REFERENCE for call in row['calls']], strict=True):
            self.assertEqual(actual[0]['data'], expected['data'])
            self.assertEqual(actual[1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_partial_failure_is_neither_false_nor_default_authority(self):
        for name in ('paused', 'safeWallet', 'canPause', 'canUnpause'):
            result = await service(Provider(failed=name)).get('core', REFERENCE[0]['account'])
            field = {'paused': 'paused', 'safeWallet': 'safeWallet', 'canPause': 'accountCanPause', 'canUnpause': 'accountCanUnpause'}[name]
            self.assertEqual(result[field], {'status': 'failure', 'error': 'contract-read-failed'})
            self.assertNotIn('password', json.dumps(result))
            if name == 'safeWallet': self.assertEqual(result['safeCanUnpause']['error'], 'not-configured')

    async def test_optional_account_and_unconfigured_surface_do_not_invent_values(self):
        provider = Provider(); result = await service(provider).get('core')
        self.assertIsNone(result['account'])
        self.assertEqual(result['accountCanPause']['error'], 'not-configured')
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 3)
        provider = Provider(); result = await service(provider, configured=False).get('core')
        self.assertIsNone(result['address'])
        self.assertEqual(result['paused']['error'], 'not-configured')
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_chain_and_reorg_failures_do_not_return_authority(self):
        for provider, message in ((Provider(chain='0x1'), 'chain mismatch'), (Provider(reorg=True), 'head changed')):
            with self.assertRaisesRegex(ValueError, message): await service(provider).get('core')

    async def test_cancellation_stops_native_supplier(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get('core', REFERENCE[0]['account']))
        await provider.started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(provider.cancelled)

    async def test_fixed_http_shape_and_redacted_supplier_outage(self):
        app = create_app(governance_authority=service(Provider()))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for query in ('', '?surface=custom', '?surface=core&account=bad'):
                result = await client.get('/api/governance/authority' + query)
                self.assertEqual(result.status_code, 400)
            result = await client.get('/api/governance/authority?surface=core&provider=http://unused.invalid')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers['cache-control'], 'no-store')
        app = create_app(governance_authority=service(Provider(chain='0x1')))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/api/governance/authority?surface=core')
            self.assertEqual(result.status_code, 503)
            self.assertNotIn('safeWallet', result.json())


if __name__ == '__main__': unittest.main(argv=[sys.argv[0]])

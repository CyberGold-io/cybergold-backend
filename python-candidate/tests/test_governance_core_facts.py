"""Compare the App's canonical ABI bytes and preserve partial reads/cancellation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3

from cybergold_candidate.app import create_app
from cybergold_candidate.governance_core_facts import ABI, GovernanceCoreFacts
from cybergold_candidate.protocol_facts import ProtocolFactsRpc
from test_protocol_facts import HASH, Provider

REFERENCE = json.loads(Path(sys.argv[1]).read_text())


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer synthetic',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return GovernanceCoreFacts(settings, ProtocolFactsRpc(settings, AsyncWeb3(provider), abi=ABI))


class GovernanceCoreFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_app_calldata_lossless_values_and_one_block(self):
        provider = Provider()
        result = await service(provider).get()
        values = result['configuration']
        self.assertEqual(values['maxTotalSupply']['value'], str(2**255))
        self.assertEqual(values['totalSupply']['value'], str(2**200))
        self.assertEqual(values['issuanceFeePpm']['value'], '0')
        self.assertEqual(values['basketConfigHash']['value'], '0x'+'7'*64)
        self.assertEqual(values['safeWallet']['value'].lower(), '0x'+'8'*40)
        self.assertEqual(result['context']['blockHash'], HASH)
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(calls), 8)
        for params in calls:
            self.assertEqual(params[0]['to'], REFERENCE['core'])
            self.assertIn(params[0]['data'], provider.rows)
            self.assertEqual(params[1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_field_failure_is_not_zero_and_does_not_hide_other_reads(self):
        value = await service(Provider(failures=('totalSupply',))).get()
        self.assertEqual(value['configuration']['totalSupply'], {'status':'failure','error':'contract-read-failed'})
        self.assertEqual(value['configuration']['issuanceFeePpm']['value'], '0')
        self.assertNotIn('password', json.dumps(value))

    async def test_unavailable_safe_authority_does_not_become_an_address(self):
        value = await service(Provider(failures=('safeWallet',))).get()
        self.assertEqual(value['configuration']['safeWallet'], {'status':'failure','error':'contract-read-failed'})
        self.assertEqual(value['configuration']['issuanceFeePpm']['value'], '0')

    async def test_reorg_fails_whole_observation(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get()

    async def test_caller_cancellation_cancels_reads(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get())
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled, 8)

    async def test_fixed_http_operation_and_redacted_failure(self):
        for provider, expected in ((Provider(), 200), (Provider(reorg=True), 503)):
            app = create_app(governance_core_facts=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/api/governance/core-facts?target=http://untrusted.invalid')
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('password', response.text)
            if expected == 503:
                self.assertIn('correlationId', response.json())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])

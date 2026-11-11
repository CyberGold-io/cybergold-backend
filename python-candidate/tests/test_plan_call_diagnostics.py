"""Exact repeated failure evidence never reuses or changes failed calls."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from web3 import Web3

from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.quote_errors import RpcTimeout
from cybergold_candidate.quoter.plan_call_diagnostics import PlanCallCensus
from cybergold_candidate.quoter.plan_transport import execute_plan_call, simulation_scope


def params(value='0x1', tag='latest'):
    return [{'to': '0x'+'11'*20, 'data': '0x12345678', 'value': value}, tag,
            {'0x'+'22'*20: {'balance': '0x100'}}]


def failure(data='0xabcdef01'):
    return {'error': {'code': 3, 'message': 'execution reverted: private provider text', 'data': data}}


class Provider:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    async def make_request(self, method, arguments):
        self.calls.append((method, deepcopy(arguments)))
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return deepcopy(result)


async def execute(provider, arguments=None, shared=True):
    return await execute_plan_call(SimpleNamespace(w3=SimpleNamespace(provider=provider)),
        arguments if arguments is not None else params(), semaphore=None, now=lambda: 123,
        shared=shared)


class PlanCallDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_failure_repetitions_are_counted_but_latest_failures_are_not_cached(self):
        records = []
        flow = Flow('/api/economic-quotes/stream', kind='search', sink=records.append)
        source = Provider([failure(), failure(), failure('0xabcdef02'), failure(), failure()])
        with flow_scope(flow):
            async with simulation_scope():
                first, _ = await execute(source)
                # Object-key order must not disguise identical wire parameters.
                reordered = params()
                reordered[0] = dict(reversed(list(reordered[0].items())))
                second, counts = await execute(source, reordered)
                await execute(source)
                await execute(source, params(value='0x2'))
                await execute(source, params(value='0x2'))
            flow.finish('succeeded')
        self.assertEqual(first, second)
        self.assertEqual(counts['issued'], 1)
        self.assertEqual(len(source.calls), 5, 'diagnostic collection must not cache failures')
        census = records[0]['helpersCalls']
        self.assertEqual(census['providerDispatches'], 5)
        self.assertEqual(census['outcomes'], {'quote-contract-reverted': 5})
        self.assertEqual(census['trackedFailurePairs'], 3)
        self.assertEqual(census['trackedRepeatedFailures'], 2)
        self.assertEqual([row['occurrences'] for row in census['repeatedFailureRows']], [2, 2])
        self.assertTrue(all(row['stateTag'] == 'latest' for row in census['repeatedFailureRows']))
        encoded = json.dumps(census)
        self.assertNotIn('private provider text', encoded)
        self.assertNotIn('0xabcdef01', encoded)
        self.assertNotIn('0x12345678', encoded)
        self.assertNotIn('0x'+'22'*20, encoded)

    async def test_success_sharing_and_fresh_preparation_are_unchanged(self):
        source = Provider([{'result': '0x01'}] * 3)
        flow = Flow('/api/economic-quotes/stream', kind='search')
        with flow_scope(flow):
            async with simulation_scope():
                _, first = await execute(source)
                _, second = await execute(source)
                await execute(source, shared=False)
                await execute(source, shared=False)
        self.assertEqual((first['issued'], second['reused']), (1, 1))
        self.assertEqual(len(source.calls), 3)
        self.assertEqual(flow.helpers_calls['outcomes'], {'result-envelope': 3})
        self.assertEqual(flow.helpers_calls['trackedFailurePairs'], 0)

    async def test_provider_state_and_paid_contexts_remain_distinct(self):
        a, b = Provider([failure()] * 8), Provider([failure()] * 2)
        flow = Flow('/api/economic-quotes/stream', kind='search')
        pinned = {'blockHash': '0x'+'33'*32, 'requireCanonical': True}
        with flow_scope(flow):
            async with simulation_scope():
                for _ in range(2):
                    await execute(a)
                    await execute(b)
                    await execute(a, params(tag=pinned))
                    await execute(a, shared=False)
        rows = flow.helpers_calls['repeatedFailureRows']
        self.assertEqual(len(rows), 4)
        self.assertEqual(flow.helpers_calls['trackedRepeatedFailures'], 4)
        self.assertEqual(len({row['providerContextDigest'] for row in rows}), 2)
        self.assertEqual({row['stateTag'] for row in rows}, {'latest', 'hash-pinned'})
        self.assertEqual({row['sharingEnabled'] for row in rows}, {True, False})

    async def test_timeout_and_cancel_are_counted_and_retried_without_retaining_exceptions(self):
        timeout = TimeoutError('private provider timeout')
        source = Provider([timeout, asyncio.CancelledError(), {'result': '0x01'}])
        flow = Flow('/api/economic-quotes/stream', kind='search')
        with flow_scope(flow):
            async with simulation_scope():
                with self.assertRaises(TimeoutError) as caught:
                    await execute(source)
                self.assertIs(caught.exception, timeout)
                with self.assertRaises(asyncio.CancelledError):
                    await execute(source)
                result, _ = await execute(source)
        self.assertEqual(result['result'], '0x01')
        self.assertEqual(len(source.calls), 3)
        self.assertEqual(flow.helpers_calls['outcomes'],
                         {'cancelled': 1, 'quote-timeout': 1, 'result-envelope': 1})
        self.assertEqual(flow.helpers_calls['trackedFailurePairs'], 0)

    async def test_broken_optional_observation_does_not_replace_provider_result(self):
        source = Provider([failure(), {'result': '0x01'}])
        flow = Flow('/api/economic-quotes/stream', kind='search')
        with flow_scope(flow), patch.object(PlanCallCensus, 'response', side_effect=RuntimeError('observer failed')):
            async with simulation_scope():
                first, _ = await execute(source)
                second, _ = await execute(source)
        self.assertIn('error', first)
        self.assertEqual(second['result'], '0x01')
        self.assertEqual(len(source.calls), 2)

    async def test_known_reverts_provider_limits_and_unknown_envelopes_are_separate(self):
        known = failure(Web3.to_hex(Web3.keccak(text='InsufficientReserveBalance()'))[:10])
        limited = {'error': {'code': -32005, 'message': 'private rate limit'}}
        unknown = {'error': {'code': -32603, 'message': 'private internal error'}}
        request = httpx.Request('POST', 'http://unused.invalid')
        http_limit = httpx.HTTPStatusError('private HTTP limit', request=request,
                                         response=httpx.Response(429, request=request))
        source = Provider([known, limited, unknown, {}, RpcTimeout('private timeout'), http_limit])
        flow = Flow('/api/economic-quotes/stream', kind='search')
        with flow_scope(flow):
            async with simulation_scope():
                for _ in range(4):
                    await execute(source, shared=False)
                with self.assertRaises(RpcTimeout):
                    await execute(source, shared=False)
                with self.assertRaises(httpx.HTTPStatusError):
                    await execute(source, shared=False)
        self.assertEqual(flow.helpers_calls['outcomes'], {
            'insufficient-reserve-balance': 1, 'rpc-rate-limit': 2,
            'rpc-unavailable': 1, 'malformed-envelope': 1, 'rpc-timeout': 1})
        self.assertEqual(flow.helpers_calls['trackedFailurePairs'], 3)
        self.assertEqual(flow.helpers_calls['trackedRepeatedFailures'], 0)

    def test_bounded_census_reports_omissions_and_still_counts_known_repetitions(self):
        census = PlanCallCensus(max_entries=2)
        provider = object()
        identities = [census.identity(provider, json.dumps(params(hex(i))), params(hex(i)), True)
                      for i in range(3)]
        for identity in identities:
            census.response(identity, failure())
        census.response(identities[0], failure())
        report = census.snapshot()
        self.assertEqual(report['trackedFailurePairs'], 2)
        self.assertEqual(report['untrackedFailureObservations'], 1)
        self.assertEqual(report['trackedRepeatedFailures'], 1)
        self.assertEqual(report['outcomes'], {'quote-contract-reverted': 4})

    async def test_search_census_does_not_cross_scope(self):
        source = Provider([failure()] * 2)
        flows = [Flow('/api/economic-quotes/stream', kind='search') for _ in range(2)]
        for flow in flows:
            with flow_scope(flow):
                async with simulation_scope():
                    await execute(source)
        self.assertTrue(all(flow.helpers_calls['trackedRepeatedFailures'] == 0 for flow in flows))
        self.assertTrue(all(flow.helpers_calls['providerDispatches'] == 1 for flow in flows))


if __name__ == '__main__':
    unittest.main()

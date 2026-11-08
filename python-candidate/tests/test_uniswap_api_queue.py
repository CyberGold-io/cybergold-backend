"""Shared hosted quota pacing and response diagnostics, without chain RPC."""
import asyncio
from email.utils import formatdate
import json
from types import SimpleNamespace
import unittest

import httpx

from cybergold_candidate.quoter.hosted_routes import (
    HostedRouteError, UniRouteApiProvider, UniswapApiProvider)
from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.route_observations import (
    RouteObservations, project_route_discovery, route_observation_scope)
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue, retry_after_seconds
from cybergold_candidate.trade_observation import economic_evidence
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from test_hosted_routes import A, B, BLOCK, Registry, settings, standard_pool


class Clock:
    def __init__(self):
        self.time, self.sleepers = 0.0, []

    def now(self):
        return self.time

    async def sleep(self, delay):
        future = asyncio.get_running_loop().create_future()
        self.sleepers.append((self.time + delay, future))
        await future

    async def advance(self, value):
        self.time = value
        for deadline, future in self.sleepers:
            if deadline <= value and not future.done():
                future.set_result(None)
        for _ in range(3):
            await asyncio.sleep(0)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_start_spacing_without_burst_after_idle(self):
        clock, starts = Clock(), []
        queue = UniswapApiQueue(8, now=clock.now, sleep=clock.sleep)
        self.addCleanup(queue.close)
        async def request(index):
            await queue.wait()
            starts.append((index, clock.now()))
        tasks = [asyncio.create_task(request(index)) for index in range(8)]
        await asyncio.sleep(0)
        for step in range(1, 8):
            await clock.advance(step / 8)
        await asyncio.gather(*tasks)
        self.assertEqual(starts, [(index, index / 8) for index in range(8)])
        await clock.advance(100.0)
        first, second = asyncio.create_task(request(8)), asyncio.create_task(request(9))
        await asyncio.sleep(0)
        self.assertTrue(first.done())
        self.assertFalse(second.done())
        await clock.advance(100.125)
        await second
        self.assertEqual(starts[-2:], [(8, 100.0), (9, 100.125)])

    async def test_pause_applies_to_existing_waiters_and_cancelled_waiter_uses_no_slot(self):
        clock = Clock()
        queue = UniswapApiQueue(8, now=clock.now, sleep=clock.sleep)
        self.addCleanup(queue.close)
        await queue.wait()
        cancelled, survivor = [asyncio.create_task(queue.wait()) for _ in range(2)]
        await asyncio.sleep(0)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        queue.pause(5)
        await clock.advance(4.0)
        self.assertFalse(survivor.done())
        await clock.advance(5.0)
        await survivor
        self.assertEqual(queue.next_start, 5.125)
        self.assertFalse(queue.pending)

    async def test_close_cancels_sleeping_and_queued_waiters(self):
        queue = UniswapApiQueue()
        await queue.wait()
        tasks = [asyncio.create_task(queue.wait()) for _ in range(2)]
        await asyncio.sleep(0)
        queue.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertFalse(queue.pending)
        self.assertFalse(queue.lock.locked())

    async def test_stalled_waiter_does_not_leave_an_accumulated_start_permit(self):
        clock = Clock()
        queue = UniswapApiQueue(8, now=clock.now, sleep=clock.sleep)
        self.addCleanup(queue.close)
        await queue.wait()
        first, second = [asyncio.create_task(queue.wait()) for _ in range(2)]
        await asyncio.sleep(0)
        # Wake an overdue sleeper after a long event-loop stall. The next
        # request must still wait a full interval from the resumed admission.
        await clock.advance(100)
        self.assertTrue(first.done())
        self.assertFalse(second.done())
        await clock.advance(100.125)
        await second

    def test_retry_after_seconds_date_and_fallback(self):
        self.assertEqual(retry_after_seconds('2'), 2)
        self.assertEqual(retry_after_seconds('0.25'), .25)
        self.assertEqual(retry_after_seconds(formatdate(105, usegmt=True), now=lambda: 100), 5)
        self.assertEqual(retry_after_seconds(formatdate(90, usegmt=True), now=lambda: 100), 0)
        for value in (None, '', 'invalid', 'nan', 'inf'):
            self.assertEqual(retry_after_seconds(value), 1)


class HostedQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.queue = UniswapApiQueue(50)
        self.engine = SimpleNamespace(registry=Registry(), uniswap_api_queue=self.queue)
        self.addCleanup(self.queue.close)

    def provider(self, handler, *, guidestar=False):
        kind = UniswapApiProvider if guidestar else UniRouteApiProvider
        provider = kind(self.engine, settings(), **({'guidestar': True} if guidestar else {}),
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=None))
        self.addAsyncCleanup(provider.close)
        return provider

    async def test_engine_owns_configured_queue_and_cancels_waiters_on_shutdown(self):
        class Sdk:
            async def close(self):
                pass
        engine = RouteQuoteEngine(settings(CYBERGOLD_UNISWAP_API_RPS='8'), Registry(), sdk=Sdk())
        self.assertEqual(engine.uniswap_api_queue.interval, .125)
        engine.uniswap_api_queue.pause(60)
        task = asyncio.create_task(engine.uniswap_api_queue.wait())
        await asyncio.sleep(0)
        await engine.close()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_both_adapters_and_new_search_share_queue_without_serializing_responses(self):
        starts, active, peak = [], 0, 0
        async def handler(request):
            nonlocal active, peak
            starts.append(asyncio.get_running_loop().time())
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.06)
                return httpx.Response(200, json={'quote': {'route': [], 'swapSteps': []}})
            finally:
                active -= 1
        recorder = RouteObservations()
        first, second = self.provider(handler), self.provider(handler, guidestar=True)
        with route_observation_scope(recorder):
            await asyncio.gather(first.discover(A, B, 100, BLOCK), second.discover(A, B, 100, BLOCK))
            # A fresh provider uses the engine's retained budget, not a new queue.
            await first.close()
            fresh = self.provider(handler)
            self.assertIs(fresh.queue, first.queue)
            await fresh.discover(A, B, 100, BLOCK)
        self.assertGreaterEqual(starts[1] - starts[0], .019)
        self.assertEqual(peak, 2)
        self.assertEqual(recorder.api_metrics['httpStatuses'], {'200': 3})
        self.assertEqual(recorder.api_metrics['queueEntries'], 3)
        self.assertEqual(recorder.metrics['requests'], 0)
        self.assertEqual(set(recorder.api_metrics['origins']), {'uniroute-api', 'uniswap-guidestar'})

    async def test_429_ends_failed_query_and_cools_down_independent_adapter(self):
        starts = []
        async def handler(request):
            starts.append(asyncio.get_running_loop().time())
            if len(starts) == 1:
                return httpx.Response(429, headers={'Retry-After': '0.08'}, json={'error': 'private'})
            return httpx.Response(200, json={'quote': {'route': [], 'swapSteps': []}})
        recorder = RouteObservations()
        first, second = self.provider(handler), self.provider(handler, guidestar=True)
        with route_observation_scope(recorder):
            outcomes = await asyncio.gather(first.discover(A, B, 100, BLOCK),
                second.discover(A, B, 100, BLOCK), return_exceptions=True)
        self.assertIsInstance(outcomes[0], HostedRouteError)
        self.assertEqual(str(outcomes[0]), 'Uniswap route provider returned HTTP 429')
        self.assertEqual(outcomes[1], [])
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1] - starts[0], .079)
        observed = recorder.api_metrics
        self.assertEqual(observed['httpStatuses'], {'200': 1, '429': 1})
        self.assertEqual((observed['requests'], observed['errors'], observed['completed'], observed['retries']),
                         (2, 1, 1, 0))
        projected = project_route_discovery({'apiRequests': observed})['apiRequests']
        self.assertEqual(projected['httpStatuses'], observed['httpStatuses'])
        self.assertGreater(projected['summedQueueWaitMs'], 75)
        self.assertNotIn('private', json.dumps(projected))
        stored = economic_evidence({'metrics': {'routeDiscovery': {'apiRequests': observed}}},
            {'operationKind': 'quoter', 'resultSource': 'stored-quote'})
        self.assertEqual(stored['observedQuoteMetrics']['routeDiscovery']['apiRequests']['httpStatuses'],
                         {'200': 1, '429': 1})
        self.assertNotIn('producerMetrics', stored)

    async def test_shared_queue_keeps_concurrent_request_observations_separate(self):
        first = self.provider(lambda request: httpx.Response(200, json={'quote': {'route': []}}))
        second = self.provider(lambda request: httpx.Response(404), guidestar=True)
        recorders = RouteObservations(), RouteObservations()
        async def run(provider, recorder):
            with route_observation_scope(recorder):
                try:
                    await provider.discover(A, B, 100, BLOCK)
                except HostedRouteError:
                    pass
        await asyncio.gather(run(first, recorders[0]), run(second, recorders[1]))
        self.assertEqual(recorders[0].api_metrics['httpStatuses'], {'200': 1})
        self.assertEqual(recorders[1].api_metrics['httpStatuses'], {'404': 1})
        self.assertEqual(set(recorders[0].api_metrics['origins']), {'uniroute-api'})
        self.assertEqual(set(recorders[1].api_metrics['origins']), {'uniswap-guidestar'})

    async def test_429_finishes_without_a_global_clock_and_owner_cancels_next_cooldown(self):
        def handler(request):
            return httpx.Response(429, headers={'Retry-After': '60'})
        provider, recorder = self.provider(handler), RouteObservations()
        with route_observation_scope(recorder):
            with self.assertRaises(HostedRouteError):
                await asyncio.wait_for(provider.discover(A, B, 100, BLOCK), .5)
            # A new query respects the server pause, but remains owned and
            # immediately cancellable rather than restarting the failed one.
            task = asyncio.create_task(provider.discover(A, B, 100, BLOCK))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        observed = recorder.api_metrics
        self.assertEqual((observed['requests'], observed['retries'], observed['queueEntries'],
                          observed['queueCancelled'], observed['cancelled']), (1, 0, 2, 1, 0))
        self.assertFalse(self.queue.pending)

    async def test_natural_bootstrap_completion_keeps_sibling_hints_after_429(self):
        first = self.provider(lambda request: httpx.Response(429, headers={'Retry-After': '0'}), guidestar=True)
        second = self.provider(lambda request: httpx.Response(200, json={'quote': {
            'route': [[standard_pool('v3', A, B, fee=500)]]}}))
        session = RouteBootstrap([first, second], nomination_only=True)
        observed = []
        async def ordinary():
            session.offers(A, B, 100, BLOCK)
            return 'ordinary-result'
        async def reevaluate():
            observed.extend(session.offers(A, B, 100, BLOCK))
        result = await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertEqual(result, 'ordinary-result')
        self.assertTrue(any(row['origins'] == ['uniroute-api'] for row in observed))
        providers = session.metrics['providers']
        self.assertEqual(providers['uniswap-guidestar']['error'], 1)
        self.assertEqual(providers['uniswap-guidestar']['started'], 1)
        self.assertEqual(providers['uniroute-api']['completed'], 1)
        self.assertFalse(self.queue.pending)

    async def test_non_429_errors_are_not_retried_and_have_http_statuses(self):
        for status in (400, 401, 403, 404, 500, 503):
            with self.subTest(status=status):
                provider = self.provider(lambda request: httpx.Response(status, json={'error': 'private'}))
                recorder = RouteObservations()
                with route_observation_scope(recorder):
                    with self.assertRaises(HostedRouteError):
                        await provider.discover(A, B, 100, BLOCK)
                self.assertEqual(recorder.api_metrics['httpStatuses'], {str(status): 1})
                self.assertEqual(recorder.api_metrics['requests'], 1)
                self.assertEqual(recorder.api_metrics['retries'], 0)

    async def test_transport_failure_has_no_invented_http_status(self):
        def handler(request):
            raise httpx.ConnectError('private transport error')
        provider, recorder = self.provider(handler), RouteObservations()
        with route_observation_scope(recorder):
            with self.assertRaises(httpx.ConnectError):
                await provider.discover(A, B, 100, BLOCK)
        self.assertEqual(recorder.api_metrics['httpStatuses'], {})
        self.assertEqual(recorder.api_metrics['errors'], 1)

    async def test_queue_cancellation_records_origin_without_claiming_http_request(self):
        self.queue.pause(60)
        provider = self.provider(lambda request: self.fail('No request should start'))
        recorder = RouteObservations()
        with route_observation_scope(recorder):
            task = asyncio.create_task(provider.discover(A, B, 100, BLOCK))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(recorder.api_metrics['requests'], 0)
        self.assertEqual(recorder.api_metrics['queueCancelled'], 1)
        self.assertEqual(recorder.api_metrics['origins']['uniroute-api']['queueEntries'], 1)

    def test_closed_log_projection_drops_arbitrary_status_labels_and_values(self):
        projected = project_route_discovery({'apiRequests': {'scope': 'hosted-api-http-attempts',
            'httpStatuses': {'200': 2, '429': 1, 'private': 5, '401': 'private', '999': 1},
            'origins': {'uniroute-api': {'httpStatuses': {'404': 3, 'private': 1}}}}})
        self.assertEqual(projected['apiRequests']['httpStatuses'], {'200': 2, '429': 1})
        self.assertEqual(projected['apiRequests']['origins']['uniroute-api']['httpStatuses'], {'404': 3})
        self.assertNotIn('private', json.dumps(projected))


if __name__ == '__main__':
    unittest.main()

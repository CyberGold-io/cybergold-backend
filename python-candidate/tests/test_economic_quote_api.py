"""Two API clients share observations; Refresh is distinct from lookup."""
from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.store import EconomicQuoteStore
from cybergold_candidate.quoter.path_families import quote_path_family
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_universal_quote import Engine, Quotes, request, BLOCK, CORE, PAXG, OTHER, USER


class SharedStore:
    def __init__(self):
        self.rows = {}
        self.family_rows = {}

    def capture_scope(self, value):
        return str(value)

    async def lookup(self, value, *, scope):
        return deepcopy(self.rows.get(scope))

    async def neighbors(self, value, *, scope):
        return [{'family': family, 'side': 'lower', 'identity': str(scope)+':'+family, 'quote': deepcopy(quote)}
                for family, quote in self.family_rows.get(scope, {}).items()]

    async def save(self, value, quote, *, scope):
        self.family_rows.setdefault(scope, {})[quote_path_family(quote)] = deepcopy(quote)
        best = None
        for value in self.family_rows[scope].values():
            if prefer_completed(value, best, scalar=quote['request']['intent'] in (0, 1),
                                basket=quote['request']['intent'] >= 2):
                best = value
        self.rows[scope] = deepcopy(best)
        return True


def service(store):
    quoter = Quotes(Engine())
    quoter.engine.registry.ensure_loaded = AsyncMock()
    return quoter, EconomicQuotes(quoter, store)


async def persisted(service):
    """Tests that inspect SQL await its owner, not the public quote response."""
    await asyncio.gather(*tuple(service.background))


class EconomicQuoteApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_offer_uses_fitting_funding_even_from_a_higher_budget_and_prefers_less_on_tie(self):
        store = SharedStore()
        quoter, quotes = service(store)
        self.addAsyncCleanup(quotes.close)
        small_request = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        smaller = await quoter.quote(small_request)
        maximum = {**small_request, 'inputs': [{**small_request['inputs'][0], 'amount': '50005'}]}
        previous = await quoter.quote(maximum)
        previous['quotedOutput'] = smaller['quotedOutput']
        previous['estimatedRecipientOutputs'] = deepcopy(smaller['estimatedRecipientOutputs'])
        # The historical search tried an even larger maximum and found this
        # smaller-funded complete tuple; its funding still fits the new input.
        smaller['request'] = {**small_request, 'inputs': [{**small_request['inputs'][0], 'amount': '100010'}]}
        before = deepcopy(smaller)
        store.neighbors = AsyncMock(return_value=[{'family': quote_path_family(smaller), 'side': 'lower', 'quote': smaller}])
        quoter.quote = AsyncMock(side_effect=AssertionError('Cache selection must not reprice'))
        offered = await quotes.cached_offer(maximum, previous, store.capture_scope(maximum))
        self.assertEqual(offered['request'], maximum)
        self.assertEqual(offered['quotedOutput'], previous['quotedOutput'])
        self.assertEqual(offered['inputs'], smaller['inputs'])
        self.assertEqual(offered['plan'], smaller['plan'])
        self.assertEqual(offered['fees'], smaller['fees'])
        self.assertEqual(smaller, before)
        quoter.quote.assert_not_called()

    async def test_cached_offer_selects_better_complete_tuple_without_rpc_or_mutation(self):
        store = SharedStore()
        quoter, quotes = service(store)
        small_request = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        small = await quoter.quote(small_request)
        large_request = {**small_request, 'inputs': [{**small_request['inputs'][0], 'amount': '100010'}]}
        poor = await quoter.quote(large_request)
        poor['quotedOutput'] = '1'
        poor['estimatedRecipientOutputs'][0]['amount'] = '1'
        await store.save(large_request, poor, scope=store.capture_scope(large_request))
        store.neighbors = AsyncMock(return_value=[{'family': quote_path_family(small), 'side': 'lower', 'quote': small}])
        retained = deepcopy(store.rows)
        quoter.quote = AsyncMock(side_effect=AssertionError('Stored offer must not search'))
        block = quoter.engine.block
        quoter.engine.block = AsyncMock(side_effect=AssertionError('Stored offer must not read a head'))
        offered = await quotes.cached_offer(large_request, poor, store.capture_scope(large_request))
        for result in [offered]:
            self.assertEqual(result['request'], large_request)
            for field in ('inputs', 'plan', 'context', 'quotedOutput', 'fees', 'conversionObservations'):
                self.assertEqual(result[field], small[field])
            self.assertEqual(result['observation']['source'], 'stored')
        self.assertEqual(store.rows, retained)
        quoter.quote.assert_not_called()
        quoter.engine.block.assert_not_called()
        quoter.engine.block = block
        prepared = await TransactionPreparation(quoter).prepare({
            'quote': offered, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['plan']['inputs'], small['inputs'])
        self.assertEqual(prepared['plan']['minimumOutput'], str(int(small['quotedOutput']) * 99 // 100))

    async def test_ordinary_json_and_stream_optimize_underfunded_cache_at_requested_budget(self):
        for streamed in (False, True):
            with self.subTest(streamed=streamed):
                store = SharedStore()
                quoter, quotes = service(store)
                self.addAsyncCleanup(quotes.close)
                smaller = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
                maximum = {**smaller, 'inputs': [{**smaller['inputs'][0], 'amount': '50005'}]}
                old = await quoter.quote(smaller)
                full = await quoter.quote(maximum)
                old['request'] = deepcopy(maximum)
                await store.save(maximum, old, scope=store.capture_scope(maximum))
                lower = deepcopy(old)
                lower['quotedOutput'] = str(int(old['quotedOutput']) + 1)
                lower['plan']['body']['known_floor_marker'] = True
                store.neighbors = AsyncMock(return_value=[{'family': quote_path_family(lower), 'side': 'lower', 'quote': lower}])
                historical_delivered = asyncio.Event()
                async def optimize(value, callback=None, **options):
                    self.assertEqual(value, maximum)
                    seeded = await options['seed_lookup']()
                    self.assertEqual(seeded['inputs'], old['inputs'])
                    self.assertEqual(seeded['plan'], old['plan'])
                    self.assertEqual((await options['neighbors']())[0]['quote']['plan'], lower['plan'])
                    self.assertIsNone(options.get('seed'))
                    if callback:
                        await historical_delivered.wait()
                        await callback({'type': 'qualified', 'value': deepcopy(full)})
                    return deepcopy(full)
                quoter.quote = AsyncMock(side_effect=optimize)
                progressive = quotes.progressive
                async def observed_progressive(value, publish, **options):
                    async def delivered(frame):
                        await publish(frame)
                        if (frame['type'] == 'qualified' and frame['value']['observation']['source'] == 'stored'
                                and frame['value']['plan'] == lower['plan']):
                            historical_delivered.set()
                    return await progressive(value, delivered, **options)
                quotes.progressive = observed_progressive
                app = create_app(economic_quotes=quotes)
                endpoint = '/api/economic-quotes' + ('/stream' if streamed else '')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                    response = await client.post(endpoint, json=maximum)  # No refresh flag.
                self.assertEqual(response.status_code, 200, response.text)
                if streamed:
                    frames = [json.loads(line) for line in response.text.splitlines()]
                    qualified = [frame['value'] for frame in frames if frame['type'] == 'qualified']
                    stored = [value for value in qualified if value['observation']['source'] == 'stored']
                    self.assertEqual(stored[-1]['plan'], lower['plan'])
                    self.assertEqual([int(value['quotedOutput']) for value in stored],
                                     sorted(int(value['quotedOutput']) for value in stored))
                    self.assertEqual(qualified[-1]['inputs'], maximum['inputs'])
                    result = next(frame['value'] for frame in frames if frame['type'] == 'complete')
                else:
                    result = response.json()
                self.assertEqual(result['inputs'], maximum['inputs'])
                self.assertEqual(result['quotedOutput'], full['quotedOutput'])
                self.assertEqual(result['observation'], {'source': 'search', 'refresh': False})
                quoter.quote.assert_awaited_once()

    async def test_optional_cache_reader_failure_does_not_cancel_fresh_search_but_caller_cancellation_propagates(self):
        store = SharedStore()
        quoter, quotes = service(store)
        self.addAsyncCleanup(quotes.close)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        saved = await quoter.quote(value)
        await store.save(value, saved, scope=store.capture_scope(value))
        for error in (OSError('Optional SQL unavailable'), asyncio.CancelledError()):
            with self.subTest(reader_error=type(error).__name__):
                store.neighbors = AsyncMock(side_effect=error)
                result = await quotes.get(value)
                self.assertEqual(result['quotedOutput'], saved['quotedOutput'])
                self.assertEqual(result['observation']['source'], 'search')
        started, drained = asyncio.Event(), asyncio.Event()
        async def held(*args, **options):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                drained.set()
        quoter.quote = held
        task = asyncio.create_task(quotes.get(value))
        await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(drained.is_set())

    async def test_missing_accepted_residual_is_ordinary_400_with_exact_private_failure_evidence(self):
        quoter, _ = service(SharedStore())
        value = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '1000'},
            {'currency': OTHER, 'amount': '1000'}], 'outputCurrency': CORE}
        historical = await quoter.candidate(value, 100, 'core-first', BLOCK, [PAXG, OTHER], [1, 1])
        del historical['plan']['conversions']['0:residual:0']
        historical['plan']['body']['continuations'][0]['route'] = {
            'inputCurrency': PAXG, 'outputCurrency': PAXG, 'routes': []}
        preview = quoter.preview
        async def changed(mode, payload, block):
            result = await preview(mode, payload, block)
            result['amountsInExact'][0] = '999'
            return result
        quoter.preview = changed
        app = create_app(transaction_preparation=TransactionPreparation(quoter))
        with self.assertLogs('cybergold.candidate', level='ERROR') as captured:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                response = await client.post('/api/tx-preparations', json={
                    'quote': historical, 'sender': USER, 'recipient': USER})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('Refresh the quote', response.json()['error'])
        self.assertNotIn('selectedReplay', response.json())
        rows = [json.loads(row.getMessage()) for row in captured.records]
        failure = next(row for row in rows if row['event'] == 'quote_failure')
        self.assertEqual(failure['exceptionType'], 'InvalidPreview')
        self.assertEqual(failure['selectedReplay'], {'operation': '0:residual:0',
            'inputCurrency': PAXG, 'outputCurrency': CORE, 'amount': '1', 'reason': 'missing-selected-route'})

    async def test_legacy_seed_is_completed_before_first_progressive_qualification(self):
        from cybergold_candidate.quoter.evaluate import identity_template
        store = SharedStore()
        quoter, quotes = service(store)
        value = {'intent': 0, 'inputs': [{'currency': PAXG, 'amount': '1000'}], 'outputCurrency': CORE}
        async def current_snapshot(pool, _block):
            # Reusable cached topology contains PoolRefs, never historical
            # reserves. The fixture reader must resolve current inventory.
            return deepcopy(quoter.engine.registry.inventory[pool['id']])
        quoter.engine.registry.snapshot = current_snapshot
        from cybergold_candidate.uniswap_routes import pool_identity
        sdk = quoter.engine.quote_sdk_branches
        async def current_sdk(*args, **options):
            # Like the real SDK worker, this component oracle starts a private
            # bank from its separately acquired immutable observations.
            for state in options['canonical'].values():
                options['candidate'].setdefault(pool_identity(state), deepcopy(state))
            return await sdk(*args, **options)
        quoter.engine.quote_sdk_branches = current_sdk
        async def preview(mode, payload, block):
            self.assertEqual(mode, 'issue-exact-in')
            return {'netCygldOut': '1000', 'amountsInExact': payload['maximumAmountsIn'],
                    'orderedCoreAssets': [PAXG, OTHER],
                    'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        quoter.preview = preview
        historical = await quoter.candidate(value, 100, 'core-first', BLOCK, [PAXG, OTHER], [1, 1])
        for chosen in historical['plan']['conversions'].values():
            chosen['discoveryOrigins'] = ['fixture-legacy-seed']
        historical['plan']['conversions'] = {key: row for key, row in historical['plan']['conversions'].items()
                                           if ':residual:' not in key}
        for row, asset in zip(historical['plan']['body']['branches'][0]['data']['continuations'], (PAXG, OTHER)):
            row['route'] = identity_template(asset)
        await store.save(value, historical, scope=store.capture_scope(value))
        frames = []
        seed_offered = asyncio.Event()
        candidate = quoter.candidate
        async def hold_ordinary(*args, **kwargs):
            selected = kwargs.get('selected') or {}
            retained = any('fixture-legacy-seed' in chosen.get('discoveryOrigins', [])
                           for chosen in selected.get('conversions', {}).values())
            if not retained:
                await seed_offered.wait()
            return await candidate(*args, **kwargs)
        quoter.candidate = hold_ordinary
        async def publish(frame):
            frames.append(deepcopy(frame))
            if frame['type'] == 'qualified':
                seed_offered.set()
        async with asyncio.timeout(2):
            await quotes.progressive(value, publish, refresh=True)
        qualified = [frame['value'] for frame in frames if frame['type'] == 'qualified']
        self.assertTrue(qualified)
        self.assertEqual(qualified[0]['searchCoverage']['selectedPhase'], 'nearby-lower')
        self.assertIn('0:residual:0', qualified[0]['plan']['conversions'])
        self.assertIn('0:residual:1', qualified[0]['plan']['conversions'])

    async def test_old_cached_quote_has_dormant_topology_before_json_or_stream_selection(self):
        store = SharedStore()
        quoter, quotes = service(store)
        value = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '1000'},
            {'currency': OTHER, 'amount': '1000'}], 'outputCurrency': CORE}
        historical = await quoter.candidate(value, 100, 'core-first', BLOCK, [PAXG, OTHER], [1, 1])
        del historical['plan']['conversions']['0:residual:0']
        historical['plan']['body']['continuations'][0]['route'] = {
            'inputCurrency': PAXG, 'outputCurrency': PAXG, 'routes': []}
        await store.save(value, historical, scope=store.capture_scope(value))
        retained = deepcopy(store.rows)
        quoter.engine.block = AsyncMock(side_effect=AssertionError('No head for stored quote'))
        quoter.quote = AsyncMock(side_effect=AssertionError('No search for stored quote'))
        app = create_app(economic_quotes=quotes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            ordinary = await client.post('/api/economic-quotes', json=value)
            streamed = await client.post('/api/economic-quotes/stream', json=value)
        self.assertEqual(ordinary.status_code, 200, ordinary.text)
        self.assertEqual(streamed.status_code, 200, streamed.text)
        frames = [json.loads(line) for line in streamed.text.splitlines()]
        visible = [frame['value'] for frame in frames if frame['type'] in ('ready', 'qualified', 'complete')]
        self.assertTrue(visible)
        for offered in [ordinary.json(), *visible]:
            self.assertIn('0:residual:0', offered['plan']['conversions'])
            self.assertEqual(offered['plan']['body']['continuations'][0]['route']['outputCurrency'], CORE)
            for field in ('context', 'quotedOutput', 'fees', 'inputs', 'conversionObservations'):
                self.assertEqual(offered[field], historical[field])
        self.assertEqual(store.rows, retained)
        quoter.quote.assert_not_called()
        quoter.engine.block.assert_not_called()

    async def test_existing_fork_generation_observer_runs_before_cache_lookup(self):
        quoter, _ = service(SharedStore())
        registry = quoter.engine.registry
        registry.chain = 31338
        registry.store = SimpleNamespace(scope='generation:unobserved:')
        generation = {'value': 'one'}
        async def observe():
            registry.generation = generation['value']
            registry.store.scope = 'generation:' + generation['value'] + ':'
        class MemoryScopeStore(EconomicQuoteStore):
            rows = {}
            async def lookup(self, value, *, scope):
                return deepcopy(self.rows.get(scope))
            async def save(self, value, quote, *, scope):
                self.rows[scope] = deepcopy(quote)
                return True
        store = MemoryScopeStore(quoter.settings, registry)
        quotes = EconomicQuotes(quoter, store, observe_scope=observe)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        first = await quotes.get(value)
        self.assertEqual((await quotes.get(value))['observation']['source'], 'search')
        before = len(quoter.evaluated)
        generation['value'] = 'two'
        replacement = await quotes.get(value)
        await persisted(quotes)
        self.assertEqual(replacement['observation']['source'], 'search')
        self.assertGreater(len(quoter.evaluated), before)
        self.assertEqual({key.namespace for key in store.rows},
                         {'generation:one:economic-quotes', 'generation:two:economic-quotes'})
        self.assertEqual(first['request'], replacement['request'])

    async def test_second_api_client_reprices_original_saved_routes_without_head_read(self):
        store = SharedStore()
        first, a = service(store)
        second, b = service(store)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        app_a, app_b = create_app(economic_quotes=a), create_app(economic_quotes=b)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app_a), base_url='http://one') as client_a, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app_b), base_url='http://two') as client_b:
            initial = await client_a.post('/api/economic-quotes', json=value)
            self.assertEqual(initial.status_code, 200, initial.text)
            second.engine.block = AsyncMock(side_effect=AssertionError('lookup must not acquire a new head'))
            cached = await client_b.post('/api/economic-quotes', json={**value, 'deadline': 'ignored', 'recipient': 'ignored'})
            self.assertEqual(cached.status_code, 200, cached.text)
        measured, reused = initial.json(), cached.json()
        self.assertEqual(reused['quotedOutput'], measured['quotedOutput'])
        self.assertEqual(reused['inputs'], measured['inputs'])
        self.assertEqual(reused['observation']['source'], 'search')
        second.engine.block.assert_not_called()
        self.assertTrue(first.evaluated)
        self.assertTrue(second.evaluated)

    async def test_refresh_replays_seed_and_failed_refresh_keeps_saved_success(self):
        store = SharedStore()
        quoter, quotes = service(store)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        observed = await quotes.get(value)
        await persisted(quotes)
        recorded = deepcopy(store.rows)
        quote = quoter.quote
        seeds = []
        async def measured(req, **kwargs):
            lookup = kwargs.get('seed_lookup')
            async def observed_lookup():
                seed = await lookup()
                seeds.append(seed)
                return seed
            kwargs['seed_lookup'] = observed_lookup
            return await quote(req, **kwargs)
        quoter.quote = measured
        refreshed = await quotes.get(value, refresh=True)
        self.assertEqual(refreshed['observation'], {'source': 'search', 'refresh': True})
        self.assertEqual(seeds[0]['plan'], observed['plan'])
        await persisted(quotes)
        saved = deepcopy(store.rows)
        quoter.quote = AsyncMock(side_effect=QuoteFailure('quote-no-route'))
        with self.assertRaises(QuoteFailure):
            await quotes.get(value, refresh=True)
        self.assertEqual(store.rows, saved)
        quoter.quote = quote  # The ordinary caller still performs fresh search.
        retained = await quotes.get(value)
        # A successful refresh may improve the original quote. A later failure
        # must retain that latest successful economic tuple.
        for field in ('quotedOutput', 'inputs', 'plan', 'fees', 'routeOrigins'):
            self.assertEqual(retained.get(field), refreshed.get(field))
        self.assertEqual(len(recorded), 1)

    async def test_economic_api_does_not_require_or_emit_execution_terms(self):
        _, quotes = service(SharedStore())
        app = create_app(economic_quotes=quotes)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            response = await client.post('/api/economic-quotes', json=value)
            invalid = await client.post('/api/economic-quotes', json={**value, 'refresh': 'yes'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(invalid.status_code, 400)
        def check(node):
            if isinstance(node, dict):
                self.assertFalse({'deadline', 'recipient', 'outputMinimum', 'minimumOutput', 'minimumAmount', 'calldata'} & node.keys())
                for item in node.values():
                    check(item)
            elif isinstance(node, list):
                for item in node:
                    check(item)
        check(response.json())

    async def test_unusable_saved_routes_leave_ordinary_candidates_available(self):
        quoter, _ = service(SharedStore())
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        previous = await quoter.quote(value)
        unusable = deepcopy(previous)
        unusable['plan']['conversions'] = {}
        result = await quoter.quote(value, seed=unusable)
        self.assertGreater(int(result['quotedOutput']), 0)
        self.assertNotEqual(result['searchCoverage']['selectedPhase'], 'saved-plan')

    async def test_different_sized_seed_is_not_mislabeled_as_requested_funding(self):
        quoter, _ = service(SharedStore())
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        previous = await quoter.quote(value)
        changed = {**value, 'inputs': [{**value['inputs'][0], 'amount': '20002'}]}
        result = await quoter.quote(changed, seed=previous)
        self.assertEqual(sum(int(row['amountIn']) for row in result['plan']['allocations']), 20002)
        self.assertEqual(result['inputs'][0]['amount'], '20002')
        self.assertNotEqual(result['searchCoverage']['selectedPhase'], 'saved-plan')


if __name__ == '__main__':
    unittest.main()

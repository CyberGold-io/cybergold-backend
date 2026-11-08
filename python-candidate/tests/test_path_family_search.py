"""Actual producer replay of both economic path families and their neighbors."""
import asyncio
from copy import deepcopy
import unittest

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.path_families import quote_path_family
from cybergold_candidate.quoter.reuse_routes import neighbor_proposals, proposal_identity
from cybergold_candidate.quoter.reuse_routes import funded_route_identity
from cybergold_candidate.quote_errors import QuoteFailure
from test_universal_quote import Quotes, Engine, CORE, PAXG, OTHER, WETH, BLOCK


def quoter():
    q = Quotes(Engine())
    sdk = q.engine.quote_sdk_branches
    async def acquire(branches, *args, **options):
        current = deepcopy(branches)
        for branch in current:
            for hop in branch['hops']:
                hop['pool'] = deepcopy(q.engine.registry.inventory[hop['pool']['id']])
        return await sdk(current, *args, **options)
    q.engine.quote_sdk_branches = acquire
    q.route_provider_factory = lambda: []
    return q


def request(amount, intent=0):
    return {'intent': intent, 'inputs': [{'currency': WETH if intent == 0 else CORE, 'amount': str(amount)}],
            'outputCurrency': CORE if intent == 0 else WETH}


def hops(q, currencies):
    source, result = currencies[0], []
    for target in currencies[1:]:
        pool = next(row for row in q.engine.registry.inventory.values() if
            {row['token0']['address'].lower(), row['token1']['address'].lower()} == {source.lower(), target.lower()})
        result.append({'pool': deepcopy(pool), 'zeroForOne': source.lower() == pool['token0']['address'].lower()})
        source = target
    return result


class PathFamilySearchTests(unittest.IsolatedAsyncioTestCase):
    async def rows(self, q):
        assets, weights = await q.basis(BLOCK)
        lower_market = await q.candidate(request(10000), 0, 'core-first', BLOCK, assets, weights, first=True)
        original = q.amm.async_nominations
        async def alternate(source, target, amount, block, **options):
            yield [{'amountIn': str(amount), 'hops': hops(q, [WETH, OTHER, PAXG, CORE])}], ['uniroute-local']
        q.amm.async_nominations = alternate
        try:
            upper_market = await q.candidate(request(30000), 0, 'core-first', BLOCK, assets, weights, first=True)
        finally:
            q.amm.async_nominations = original
        lower_core = await q.candidate(request(10000), 100, 'core-first', BLOCK, assets, weights, first=True)
        upper_core = await q.candidate(request(30000), 50, 'market-first', BLOCK, assets, weights, first=True)
        return [{'family': family, 'side': side, 'identity': family+'-'+side, 'quote': quote}
            for family, side, quote in [('market','lower',lower_market),('market','upper',upper_market),
                                        ('core','lower',lower_core),('core','upper',upper_core)]]

    async def test_private_reprice_and_disproof_never_enter_legacy_update_callback(self):
        from unittest.mock import AsyncMock
        q = quoter()
        rows = await self.rows(q)
        original = q.candidate
        async def candidate(funding, *args, **options):
            selected = options.get('selected')
            if selected is None:
                raise QuoteFailure('quote-no-route')
            if funding['inputs'][0]['amount'] == '10000' and selected['allocations'][0]['kind'] == 1:
                raise QuoteFailure('quote-contract-reverted')
            return await original(funding, *args, **options)
        q.candidate = candidate
        q.amm.async_family_offers = AsyncMock(return_value=[])
        frames = []
        async def update(frame): frames.append(deepcopy(frame))
        async def neighbors(): return deepcopy(rows)
        async with asyncio.timeout(3):
            await Quoter.get(q, request(20000), update, neighbors=neighbors)
        self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
        self.assertTrue(all(frame['type'] in ('qualified', 'upper-replay-settled') for frame in frames))
        self.assertTrue(all(not any(key.startswith('_candidate') or key == '_replacesIdentity'
                                   for key in frame) for frame in frames))

    async def test_private_observer_receives_each_paid_original_and_expansion_before_ranking(self):
        from unittest.mock import AsyncMock
        q = quoter()
        rows = await self.rows(q)
        original = q.candidate
        async def candidate(funding, *args, **options):
            if options.get('selected') is None:
                raise QuoteFailure('quote-no-route')
            return await original(funding, *args, **options)
        q.candidate = candidate
        q.amm.async_family_offers = AsyncMock(return_value=[])
        frames = []
        async def observed(frame):
            frames.append(deepcopy(frame))
        async def neighbors():
            return deepcopy(rows)
        async with asyncio.timeout(3):
            value = await Quoter.get(q, request(20000), neighbors=neighbors, on_candidate=observed)
        self.assertEqual(len(frames), 6)
        self.assertTrue(all(frame['type'] == 'candidate-repriced' for frame in frames))
        self.assertCountEqual([frame['value']['inputs'][0]['amount'] for frame in frames],
                              ['20000'] * 4 + ['10000'] * 2)
        self.assertEqual(len({frame['_candidateIdentity'] for frame in frames}), 6)
        self.assertTrue(all(frame['_candidateIdentity'] == funded_route_identity(frame['value'])
                            for frame in frames))
        self.assertEqual(int(value['quotedOutput']), max(int(frame['value']['quotedOutput']) for frame in frames))
        self.assertTrue(any(int(frame['value']['quotedOutput']) < int(value['quotedOutput']) for frame in frames),
                        'paid losing observations must reach the private observer too')
        self.assertEqual(q.engine.semaphore._value, 8)

    async def test_four_topologies_replay_fitting_originals_and_capture_global_losers(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                q = quoter()
                rows = await self.rows(q)
                retained = deepcopy(rows)
                target = request(20000)
                entered, paid, cancelled_calls = asyncio.Event(), {}, []
                original = q.candidate
                async def candidate(funding, *args, **options):
                    if options.get('selected') is None:
                        raise QuoteFailure('quote-no-route')
                    result = await original(funding, *args, **options)
                    key = proposal_identity({'inputs': funding['inputs'], 'plan': options['selected']})
                    paid[key] = {'value': result, 'release': asyncio.Event()}
                    if len(paid) == 6:
                        entered.set()
                    try:
                        await paid[key]['release'].wait()
                    except asyncio.CancelledError:
                        cancelled_calls.append(key)
                        raise
                    return result
                q.candidate = candidate
                # The ordinary family explorer is irrelevant to this cache
                # replay control; these complete cached plans use real pricing.
                from unittest.mock import AsyncMock
                q.amm.async_family_offers = AsyncMock(return_value=[])
                families, visible = {}, []
                published = asyncio.Event()
                async def family(value):
                    families[quote_path_family(value)] = deepcopy(value)
                async def publish(frame):
                    if frame['type'] == 'qualified':
                        visible.append(deepcopy(frame['value']))
                        published.set()
                async def neighbors():
                    return deepcopy(rows)
                async with asyncio.timeout(4):
                    task = asyncio.create_task(Quoter.get(q, target, publish, neighbors=neighbors,
                        seed=rows[0]['quote'], on_family=family))
                    try:
                        await entered.wait()
                        self.assertEqual(len(paid), 6)
                        self.assertCountEqual([row['value']['inputs'][0]['amount'] for row in paid.values()],
                                              ['20000'] * 4 + ['10000'] * 2)
                        ordered = sorted(paid.values(), key=lambda row: int(row['value']['quotedOutput']), reverse=True)
                        winner = ordered[0]
                        winner['release'].set()
                        await published.wait()
                        opposite = next(row for row in ordered[1:] if
                            quote_path_family(row['value']) != quote_path_family(winner['value']))
                        opposite['release'].set()
                        for _ in range(100):
                            if len(families) == 2:
                                break
                            await asyncio.sleep(0)
                        self.assertEqual(set(families), {'market', 'core'})
                        # The newly captured losing family never downgrades
                        # the global executable result already delivered.
                        self.assertEqual(len(visible), 1)
                        self.assertEqual(visible[0]['quotedOutput'], winner['value']['quotedOutput'])
                        if cancelled:
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                            self.assertEqual(len(cancelled_calls), len(paid) - 2)
                        else:
                            for row in ordered:
                                row['release'].set()
                            value = await task
                            self.assertEqual(value['quotedOutput'], winner['value']['quotedOutput'])
                            self.assertEqual(set(families), {'market', 'core'})
                        self.assertEqual(rows, retained)
                        self.assertEqual(q.engine.semaphore._value, 8)
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_flushes_later_equivalent_family_origins(self):
        from unittest.mock import AsyncMock, patch
        from cybergold_candidate.quoter.provenance import merge_origins
        q = quoter()
        target = request(20000)
        assets, weights = await q.basis(BLOCK)
        saved = await q.candidate(target, 0, 'core-first', BLOCK, assets, weights, first=True)
        q.amm.async_family_offers = AsyncMock(return_value=[])
        original = q.candidate
        published, merged, blocked, drained = (asyncio.Event() for _ in range(4))
        async def candidate(funding, share, *args, first=False, **options):
            if options.get('selected') is not None:
                return await original(funding, share, *args, first=first, **options)
            if first and share == 100:
                blocked.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            if not first and share == 0:
                await published.wait()
                value = deepcopy(saved)
                for chosen in value['plan']['conversions'].values():
                    chosen['discoveryOrigins'] = ['uniroute-local']
                return value
            raise QuoteFailure('quote-no-route')
        q.candidate = candidate
        families, visible = [], []
        async def family(value):
            families.append(deepcopy(value))
        async def publish(frame):
            if frame['type'] == 'qualified':
                visible.append(deepcopy(frame['value']))
                published.set()
        def record_merge(incumbent, value):
            merge_origins(incumbent, value)
            if incumbent and incumbent.get('routeOrigins', {}).get('discoveryProviders') == [
                    'cybergold-custom', 'uniroute-local']:
                merged.set()
        async def neighbors():
            return [{'family': 'market', 'side': 'lower', 'identity': 'exact-market', 'quote': deepcopy(saved)}]
        with patch('cybergold_candidate.quoter.search.merge_origins', record_merge):
            async with asyncio.timeout(3):
                task = asyncio.create_task(Quoter.get(q, target, publish, neighbors=neighbors, on_family=family))
                try:
                    await merged.wait()
                    await blocked.wait()
                    self.assertEqual(families[-1]['routeOrigins']['discoveryProviders'], ['cybergold-custom'])
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(drained.is_set())
        self.assertEqual(len(visible), 1)
        self.assertEqual(families[-1]['routeOrigins']['discoveryProviders'], ['cybergold-custom', 'uniroute-local'])
        self.assertEqual(families[-1]['inputs'], saved['inputs'])
        self.assertEqual(families[-1]['fees'], saved['fees'])
        self.assertEqual(families[-1]['context'], families[0]['context'])

    async def test_equivalent_core_sale_routes_deduplicate_ignored_projected_amounts(self):
        q = quoter()
        assets, weights = await q.basis(BLOCK)
        lower = await q.candidate(request(10000, 1), 100, 'core-first', BLOCK, assets, weights, first=True)
        upper = await q.candidate(request(30000, 1), 100, 'core-first', BLOCK, assets, weights, first=True)
        left = neighbor_proposals(lower, 20000, assets)[-1]
        right = neighbor_proposals(upper, 20000, assets)[-1]
        self.assertNotEqual(left['plan']['body']['branches'][0]['data']['expectedOutputs'],
                            right['plan']['body']['branches'][0]['data']['expectedOutputs'])
        self.assertEqual(proposal_identity(left), proposal_identity(right))
        # Core output identity still changes execution and must stay distinct.
        different = deepcopy(right)
        different['plan']['body']['branches'][0]['data']['expectedOutputs'][0]['id'] = '9'
        self.assertNotEqual(proposal_identity(left), proposal_identity(different))
        calls, original = [], q.candidate
        async def candidate(funding, *args, **options):
            if options.get('selected') is None:
                raise QuoteFailure('quote-no-route')
            calls.append({'funding': deepcopy(funding['inputs']), 'plan': deepcopy(options['selected'])})
            return await original(funding, *args, **options)
        q.candidate = candidate
        from unittest.mock import AsyncMock
        q.amm.async_family_offers = AsyncMock(return_value=[])
        async def neighbors():
            return [{'family':'core','side':side,'identity':side,'quote':quote}
                    for side,quote in [('lower',lower),('upper',upper)]]
        async with asyncio.timeout(3):
            value = await Quoter.get(q, request(20000, 1), neighbors=neighbors)
        self.assertEqual(len(calls), 2)
        self.assertCountEqual([row['funding'][0]['amount'] for row in calls], ['10000', '20000'])
        self.assertEqual(value['inputs'], request(20000, 1)['inputs'])
        self.assertEqual(len(value['metrics']['nearbySearch']['sources']), 1)
        self.assertEqual(len(value['metrics']['nearbySearch']['sources'][0]['aliases']), 1)


if __name__ == '__main__':
    unittest.main()

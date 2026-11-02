"""Real AlphaRouter child with a controlled canonical Python pricing boundary."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.alpha_routes import AlphaRoutes, AlphaRouteError
from cybergold_candidate.quoter.bootstrap import ProviderUnavailable
from cybergold_candidate.recovery_rpc import SnapshotChanged


A, B, C = ('0x'+value*40 for value in ('1', '2', '3'))
BLOCK = {'number': 101, 'hash': '0x'+'ab'*32}
ROOT = Path(__file__).resolve().parents[2]


def pool(a=A, b=C, fee=3000, protocol='v3'):
    return {'id': f'{protocol}:{a}:{b}:{fee}', 'protocol': protocol,
            'token0': {'address': a, 'chainId': 1, 'decimals': 18},
            'token1': {'address': b, 'chainId': 1, 'decimals': None},
            'feePips': fee, 'tickSpacing': 60}


class Engine:
    def __init__(self, pools=None, chain=1):
        rows = deepcopy(pools or [pool()])
        for row in rows:
            row['token0']['chainId'] = row['token1']['chainId'] = chain
        self.registry = SimpleNamespace(chain=chain, inventory={row['id']: row for row in rows})
        self.semaphore = asyncio.Semaphore(8)
        self.calls = []

    async def quote_sdk_branches(self, branches, mode, amount, block, *, candidate, canonical):
        self.calls.append((deepcopy(branches), mode, amount, block, candidate, canonical))
        # The explicit oracle makes a two-hop shape better. SDK tests separately
        # prove arithmetic; this checks that actual AlphaRouter uses this oracle.
        output = amount * (3 if len(branches[0]['hops']) > 1 else 2)
        return {'amountIn': str(amount), 'amountOut': str(output), 'fullyFilled': True, 'settled': True}


class AlphaRouteTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, engine):
        return AlphaRoutes(engine, command=['node', str(ROOT/'src/uniswap-sdk/alpha-worker.ts')])

    async def test_real_router_selects_canonical_two_hop_and_retains_seed_identifiers(self):
        engine = Engine([pool(), pool(A, B, 500), pool(B, C)])
        provider = self.provider(engine)
        try:
            candidates = await provider.discover(A, C, 1000000000000000007, BLOCK)
            self.assertGreaterEqual(len(candidates), 2)
            self.assertEqual(len(candidates[-1]), 1)
            self.assertEqual(len(candidates[-1][0]['hops']), 2)
            self.assertGreater(len(engine.calls), 1)
            self.assertTrue(all(call[4] == {} for call in engine.calls))
            self.assertEqual(len({id(call[4]) for call in engine.calls}), len(engine.calls))
            self.assertEqual(len({id(call[5]) for call in engine.calls}), 1)
            self.assertTrue(all(call[3] is BLOCK for call in engine.calls))
            self.assertTrue(all(hop['pool']['id'] in engine.registry.inventory
                                for candidate in candidates for row in candidate for hop in row['hops']))
            child = provider.process
            await provider.discover(C, A, 99999, BLOCK)
            self.assertIs(child, provider.process)
        finally:
            await provider.close()
        self.assertIsNotNone(child.returncode)

    async def test_v2_also_uses_canonical_callback_not_dummy_reserves(self):
        engine = Engine([pool(protocol='v2')])
        provider = self.provider(engine)
        try:
            self.assertTrue(await provider.discover(A, C, 10**30, BLOCK))
            self.assertTrue(engine.calls)
            self.assertEqual(engine.calls[0][0][0]['hops'][0]['pool']['protocol'], 'v2')
        finally:
            await provider.close()

    async def test_ordinary_quote_failure_keeps_alphas_unpriced_topology_available(self):
        engine = Engine()
        async def unavailable(*_args, **_kwargs):
            raise RuntimeError('ordinary missing or unfillable pool')
        engine.quote_sdk_branches = unavailable
        provider = self.provider(engine)
        try:
            hints = await provider.discover(A, C, 1000, BLOCK)
            self.assertTrue(hints)
            self.assertTrue(all('quote' not in branch for hint in hints for branch in hint))
        finally:
            await provider.close()

    async def test_context_disproof_propagates_and_reaps_calculation_child(self):
        engine = Engine()
        async def invalidated(*_args, **_kwargs):
            raise SnapshotChanged('controlled disproof')
        engine.quote_sdk_branches = invalidated
        provider = self.provider(engine)
        with self.assertRaises(SnapshotChanged):
            await provider.discover(A, C, 1000, BLOCK)
        self.assertIsNone(provider.process)
        await provider.close()

    async def test_actual_unsupported_chain_returns_ordinary_provider_error(self):
        provider = self.provider(Engine(chain=31337))
        try:
            with self.assertRaises(AlphaRouteError):
                await provider.discover(A, C, 1000, BLOCK)
            child = provider.process
            self.assertIsNotNone(child)
            self.assertIsNone(child.returncode)
            with self.assertRaises(AlphaRouteError):
                await provider.discover(A, C, 1000, BLOCK)
            self.assertIs(provider.process, child)
            self.assertEqual(provider.sequence, 2)
        finally:
            await provider.close()
        self.assertIsNotNone(child.returncode)

    async def test_mainnet_backed_fork_uses_real_chain_dependencies_and_quote_callbacks(self):
        engine = Engine([pool(), pool(A, B, 500), pool(B, C)], chain=31338)
        provider = self.provider(engine)
        self.addAsyncCleanup(provider.close)
        candidates = await asyncio.wait_for(provider.discover(A, C, 10**18+7, BLOCK), 3)
        self.assertTrue(candidates)
        self.assertGreater(len(engine.calls), 1)
        self.assertTrue(all(call[3] is BLOCK for call in engine.calls))
        self.assertTrue(all(hop['pool'][token]['chainId'] == 31338 for candidate in candidates
            for branch in candidate for hop in branch['hops'] if 'pool' in hop for token in ('token0', 'token1')))
        self.assertTrue(all(hop['pool'][token]['chainId'] == 31338 for call in engine.calls
            for branch in call[0] for hop in branch['hops'] for token in ('token0', 'token1')))

    async def test_terminal_error_after_quote_callback_reuses_child_for_next_request(self):
        script = '''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request['id'] == '1':
        print(json.dumps({'id': '1', 'operation': 'quote', 'quoteId': '1:1',
            'mode': 'exactIn', 'amount': '1000', 'branches': [{'amountIn': '1000',
            'hops': [{'pool': request['pools'][0], 'zeroForOne': True}]}]}), flush=True)
        json.loads(next(sys.stdin))
        print(json.dumps({'id': '1', 'error': 'ordinary calculation failure'}), flush=True)
    else:
        print(json.dumps({'id': request['id'], 'candidates': []}), flush=True)
'''
        engine = Engine()
        provider = AlphaRoutes(engine, command=[sys.executable, '-u', '-c', script])
        try:
            with self.assertRaises(AlphaRouteError):
                await provider.discover(A, C, 1000, BLOCK)
            child = provider.process
            self.assertEqual(len(engine.calls), 1)
            self.assertIsNone(child.returncode)
            self.assertEqual(await provider.discover(A, C, 1000, BLOCK), [])
            self.assertIs(provider.process, child)
        finally:
            await provider.close()
        self.assertIsNotNone(child.returncode)

    async def test_eof_and_invalid_frames_still_retire_child(self):
        frames = [None, 'not-json', json.dumps({'id': 'other', 'error': 'wrong request'}),
                  json.dumps({'id': '1', 'unexpected': True})]
        for frame in frames:
            with self.subTest(frame=frame):
                statement = 'sys.exit(0)' if frame is None else f'print({frame!r}, flush=True)'
                script = f'import sys\nnext(sys.stdin)\n{statement}\n'
                provider = AlphaRoutes(Engine(), command=[sys.executable, '-u', '-c', script])
                with self.assertRaises((AlphaRouteError, json.JSONDecodeError)):
                    await provider.discover(A, C, 1000, BLOCK)
                self.assertIsNone(provider.process)
                await provider.close()

    async def test_transport_failure_still_retires_child(self):
        provider = AlphaRoutes(Engine(), command=[sys.executable, '-u', '-c',
                              'import sys\nfor line in sys.stdin: pass'])
        async def disconnected(*_):
            raise BrokenPipeError()
        provider._write = disconnected
        with self.assertRaises(BrokenPipeError):
            await provider.discover(A, C, 1000, BLOCK)
        self.assertIsNone(provider.process)
        await provider.close()

    async def test_cancellation_during_callback_drains_child(self):
        engine, entered = Engine(), asyncio.Event()
        async def blocked(*_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()
        engine.quote_sdk_branches = blocked
        provider = self.provider(engine)
        task = asyncio.create_task(provider.discover(A, C, 1000, BLOCK))
        await entered.wait()
        child = provider.process
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(child.returncode)
        self.assertIsNone(provider.process)
        await provider.close()

    async def test_close_drains_callback_even_when_hint_subscriber_has_not_resumed(self):
        engine, entered, drained = Engine(), asyncio.Event(), asyncio.Event()
        async def blocked(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        engine.quote_sdk_branches = blocked
        provider = self.provider(engine)
        stream = provider.discover_batches(A, C, 1000, BLOCK)
        try:
            self.assertTrue(await asyncio.wait_for(anext(stream), 3))
            await asyncio.wait_for(entered.wait(), 1)
            child = provider.process
            await asyncio.wait_for(provider.close(), 1)
            self.assertTrue(drained.is_set())
            self.assertIsNotNone(child.returncode)
            self.assertIsNone(provider.process)
            self.assertEqual(engine.semaphore._value, 8)
            self.assertTrue(all(not entry['callbacks'] for entry in provider.requests.values()))
            with self.assertRaises(AlphaRouteError):
                await anext(stream)
        finally:
            await stream.aclose()
            await provider.close()

    async def test_cancellation_while_spawn_handle_is_pending_reaps_exact_child(self):
        provider = self.provider(Engine())
        original = asyncio.create_subprocess_exec
        children, entered, release = [], asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            child = await original(*args, **kwargs)
            children.append(child)
            entered.set()
            await release.wait()
            return child
        with patch('cybergold_candidate.quoter.alpha_routes.asyncio.create_subprocess_exec', delayed):
            task = asyncio.create_task(provider.discover(A, C, 1000, BLOCK))
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        await provider.close()
        with self.assertRaises(ProviderUnavailable):
            await provider.discover(A, C, 1000, BLOCK)


if __name__ == '__main__':
    unittest.main()

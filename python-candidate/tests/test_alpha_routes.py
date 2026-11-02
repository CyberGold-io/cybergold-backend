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
            self.assertEqual(len(candidates), 1)
            self.assertEqual(len(candidates[0]), 1)
            self.assertEqual(len(candidates[0][0]['hops']), 2)
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

    async def test_ordinary_quote_failure_preserves_empty_outcome(self):
        engine = Engine()
        async def unavailable(*_args, **_kwargs):
            raise RuntimeError('ordinary missing or unfillable pool')
        engine.quote_sdk_branches = unavailable
        provider = self.provider(engine)
        try:
            self.assertEqual(await provider.discover(A, C, 1000, BLOCK), [])
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
        provider = self.provider(Engine(chain=31338))
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

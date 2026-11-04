"""Multi-leg recovery through the real producer, SDK and complete plan compiler."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.exact_input_plan import compile_plan, CORE_SELL
from cybergold_candidate.helpers_execution import ABI
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.amm import PartialPath
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.plan_simulation import HelpersPlanSimulation
from cybergold_candidate.quoter.plan_call import executable_body
from cybergold_candidate.quoter.reuse_routes import proposal_identity
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from quoter_fixture import service, synthetic_pool
from test_universal_quote import CORE, PAXG, OTHER, WETH, USER, HELPERS, ADAPTER, settings
from test_quoter_plan_simulation import CODEC, Rpc, Provider, branches, encoded, measured, stage, NOW


REQUEST = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': WETH}
MIDDLE = '0x' + '44' * 20


def constant_product(amount, reserve_in=10**9, reserve_out=10**9):
    return amount * 997 * reserve_out // (reserve_in * 1000 + amount * 997)


def thin_pool(source, target, number, fee=3000):
    pool = synthetic_pool(source, target, number, 'v3', liquidity=10**5)
    spacing = {500: 10, 3000: 60}[fee]
    pool.update(feePips=fee, tickSpacing=spacing)
    words = {word: 0 for word in range((-887272 // spacing) >> 8, ((887272 // spacing) >> 8) + 1)}
    pool['ticks'] = []
    for tick, net in ((-spacing, 10**5), (spacing, -10**5)):
        compressed = tick // spacing
        words[compressed >> 8] |= 1 << (compressed % 256)
        pool['ticks'].append({'index': tick, 'liquidityGross': str(10**5), 'liquidityNet': str(net)})
    pool['bitmapWords'] = [{'wordPosition': word, 'bitmap': str(bits)} for word, bits in words.items()]
    return pool


def route(source, *pools):
    result = []
    for pool in pools:
        forward = source.lower() == pool['token0']['address'].lower()
        result.append({'pool': deepcopy(pool), 'zeroForOne': forward})
        source = pool['token1' if forward else 'token0']['address']
    return result


def fixture(test, *, asymmetric=False, shared=False, all_fail=False, duplicates=False, late=False, hold=False,
            helpers_abi=False):
    assets, pools, menus = [PAXG, OTHER], [], {}
    shared_pool = thin_pool(MIDDLE, WETH, 9930) if shared else None
    shared_good = synthetic_pool(MIDDLE, WETH, 9931, 'v2') if shared else None
    if shared_pool:
        pools.extend((shared_pool, shared_good))
    for index, asset in enumerate(assets):
        bad = thin_pool(asset, WETH, 9900 + index)
        good = synthetic_pool(asset, WETH, 9910 + index, 'v2')
        pools.extend((bad, good))
        variants = [route(asset, bad), route(asset, good)]
        if asymmetric:
            other_bad = thin_pool(asset, WETH, 9920 + index, fee=500)
            pools.append(other_bad)
            variants.insert(2 if index == 0 else 1, route(asset, other_bad))
        if shared:
            first = synthetic_pool(asset, MIDDLE, 9940 + index, 'v2')
            pools.append(first)
            variants[0] = route(asset, first, shared_pool)
            variants[-1] = route(asset, first, shared_good)
        if all_fail:
            variants = variants[:1]
        menus[asset.lower()] = variants
    pools.append(synthetic_pool(PAXG, CORE, 9999, 'v4', liquidity=10**12))
    quoter = service(test, pools)
    control = SimpleNamespace(attempts=[], successes=[], failures=[], queries=[], closed=False,
                              failed=asyncio.Event(), held=asyncio.Event(), cancelled=False)

    async def outputs(_=None):
        return [{'kind': 0, 'token': asset, 'id': '0', 'amount': '1'} for asset in assets]

    async def preview(mode, value, _):
        test.assertEqual(mode, 'redeem-exact-in')
        amount = int(value['grossCygldIn'])
        return {'projectedCoreOutputs': [{'kind': 0, 'token': asset, 'id': '0', 'amount': str(amount // 2)}
                                        for asset in assets],
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}

    async def discover(*_):
        pass

    quoter.core_outputs, quoter.preview = outputs, preview
    quoter.discover, quoter.seed_routes = discover, lambda *_: None
    leaf = quoter.plan_simulator
    if helpers_abi:
        control.wire, control.sdk_calls = [], 0
        original_sdk = quoter.engine.sdk.request
        async def sdk(*args, **options):
            control.sdk_calls += 1
            return await original_sdk(*args, **options)
        quoter.engine.sdk.request = sdk

        def execute(method, params):
            function, decoded = Web3().eth.contract(abi=ABI).decode_function_input(params[0]['data'])
            test.assertEqual((method, function.fn_name, params[1]), ('eth_call', 'executeExactInput', 'latest'))
            compiled = decoded['plan']
            body = branches(decoded)
            test.assertEqual([(row[0], row[1]) for row in body], [(0, 10000)])
            test.assertEqual(compiled['inputs'][0]['amount'], 10000)
            outputs, conversions = CODEC.decode([CORE_SELL], body[0][2])[0]
            wire = {'outputs': deepcopy(outputs), 'sdkCalls': control.sdk_calls}
            control.wire.append(wire)
            for asset, template in zip(assets, conversions, strict=True):
                if any(step[0] == 1 for weighted in template[3] for step in weighted[1]):
                    wire['remainder'] = asset
                    return {'error': {'code': 3, 'message': 'execution reverted', 'data':
                        '0xdb8b21c4' + CODEC.encode(['address', 'uint256'], [asset, 4700]).hex()}}
            wire['success'] = True
            output = constant_product(5000)
            return encoded(measured(output * 2, currency=WETH,
                stages=[stage(index, asset, WETH, 5000, output) for index, asset in enumerate(assets)]))

        # The real simulator decodes both Helpers ABI success bytes and the
        # real UnsettledIntermediate selector; this transport is the only mock.
        provider = Provider(*(execute for _ in range(32)))
        control.rpc, control.provider = Rpc(provider), provider
        quoter.engine.registry.get_rpc = lambda: control.rpc
        leaf = HelpersPlanSimulation(settings(), quoter.engine.registry, helpers=HELPERS, adapter=ADAPTER,
            core=CORE, now=lambda: NOW, semaphore=quoter.engine.semaphore)

    async def simulate(request, selected, **options):
        compile_plan({**request, 'recipient': USER, 'deadline': '1'}, executable_body(selected['body']), 0)
        attempted = deepcopy(selected)
        control.attempts.append(attempted)
        if hold and len(control.attempts) >= 3:
            control.held.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                control.cancelled = True
                raise
        try:
            # The component oracle reports an unconsumed inner-hop currency
            # through its actual SDK trace, before returning an economic tuple.
            # Translate that measured failure like the Helpers revert below.
            with capture_paths():
                value = await leaf(request, selected, **options)
        except PartialPath as partial:
            hop = partial.trace.hops[-1]
            source = hop.hop['pool']['token0' if hop.hop['zeroForOne'] else 'token1']['address']
            remainder = {'currency': source, 'amount': hop.funded - hop.consumed}
            test.assertGreater(remainder['amount'], 0)
            error = QuoteFailure('quote-contract-reverted')
            error.unsettled_intermediate = remainder
            control.failures.append(deepcopy(remainder))
            control.failed.set()
            raise error from partial
        except QuoteFailure as error:
            remainder = getattr(error, 'unsettled_intermediate', None)
            if remainder is not None:
                control.failures.append(deepcopy(remainder))
                control.failed.set()
            raise
        remainder = next((row for row in value['estimatedRetainedInputCharges']
                          if row['currency'].lower() in {PAXG.lower(), OTHER.lower(), MIDDLE.lower()}
                          and int(row['amount']) > 0), None)
        if remainder is not None:
            error = QuoteFailure('quote-contract-reverted')
            error.unsettled_intermediate = {'currency': remainder['currency'], 'amount': int(remainder['amount'])}
            control.failures.append(deepcopy(error.unsettled_intermediate))
            control.failed.set()
            raise error
        control.successes.append(attempted)
        return value

    quoter.plan_simulator = simulate

    class Ready(RouteTool):
        name = 'controlled-core-composition'

        def discover(self, query):
            control.queries.append((query.source.lower(), query.amount))
            variants = menus.get(query.source.lower(), []) if query.target.lower() == WETH.lower() else []
            ready = variants[:1] if late and query.amount == 1 else variants
            if duplicates:
                ready = [path for path in ready for _ in range(2)]

            async def pending():
                await control.failed.wait()
                await asyncio.sleep(0)
                return [[{'amountIn': str(query.amount), 'hops': deepcopy(path)}] for path in variants[1:]]

            return CandidateFeed(available=[[{'amountIn': str(query.amount), 'hops': deepcopy(path)}]
                                            for path in ready],
                                 pending=pending() if late and query.amount == 1 else None)

        async def close(self):
            control.closed = True

    quoter.route_provider_factory = lambda: [Ready()]
    return quoter, control


class CoreMarketCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_child_feed_preserves_parent_alternatives(self):
        from cybergold_candidate.quoter.core_market_recovery import compose_core_market
        closed, attempts = [], []

        def plan(choice):
            return {'allocations': [], 'conversions': {}, 'body': {'choice': choice}}

        async def alternatives(_quoter, request, selected, _block, **_):
            try:
                if selected['body']['choice'] == 0:
                    for choice in (1, 2):
                        yield {'inputs': request['inputs'], 'plan': plan(choice)}
                else:
                    raise OSError('One optional child feed failed.')
            finally:
                closed.append(selected['body']['choice'])

        async def attempt(proposal):
            choice = proposal['plan']['body']['choice']
            attempts.append(choice)
            if choice == 1:
                error = QuoteFailure('quote-contract-reverted')
                error.unsettled_intermediate = {'currency': PAXG, 'amount': 1}
                raise error
            return {'quotedOutput': '10'}

        with patch('cybergold_candidate.quoter.core_market_recovery.core_market_proposals', alternatives):
            value = await compose_core_market(None, REQUEST, plan(0), None,
                unsettled={'currency': OTHER, 'amount': 1}, attempt=attempt)
        self.assertEqual(value['quotedOutput'], '10')
        self.assertEqual(attempts, [1, 2])
        self.assertEqual(closed, [1, 0])

    async def successful(self, **options):
        quoter, control = fixture(self, **options)
        updates = []

        async def publish(frame):
            if frame['type'] == 'qualified':
                updates.append(deepcopy(frame['value']))

        async with asyncio.timeout(10):
            result = await quoter.get(REQUEST, publish, core_only=True)
        self.assertEqual(result['inputs'], REQUEST['inputs'])
        if options.get('shared'):
            prefix = constant_product(5000)
            first = constant_product(prefix)
            second = constant_product(prefix, 10**9 + prefix, 10**9 - first)
            self.assertEqual(result['quotedOutput'], str(first + second))
            self.assertLess(first + second, first * 2, 'the second leg must use the advanced shared pool')
        else:
            self.assertEqual(result['quotedOutput'], str(constant_product(5000) * 2))
        self.assertTrue(control.closed)
        if not options.get('late'):
            self.assertEqual(updates[0]['searchCoverage']['selectedPhase'], 'core-market-bootstrap')
        self.assertEqual({amount for _, amount in control.queries}, {1, 5000})
        first, chosen = control.attempts[0], control.successes[0]
        self.assertEqual(first['allocations'], chosen['allocations'])
        self.assertEqual(first['body']['branches'][0]['data']['expectedOutputs'],
                         chosen['body']['branches'][0]['data']['expectedOutputs'])
        return control

    async def test_ready_alternatives_compose_both_failing_legs(self):
        control = await self.successful()
        self.assertGreaterEqual(len(control.failures), 2)
        self.assertLessEqual(len(control.attempts), 6)

    async def test_asymmetric_nominee_indices_are_not_lost(self):
        await self.successful(asymmetric=True)

    async def test_shared_downstream_remainder_is_followed_from_changed_body(self):
        control = await self.successful(shared=True)
        self.assertTrue(all(row['currency'].lower() == MIDDLE.lower() for row in control.failures))

    async def test_actual_helpers_abi_reverts_both_legs_then_prices_complete_composition(self):
        control = await self.successful(helpers_abi=True)
        self.assertEqual({row['currency'].lower() for row in control.failures},
                         {PAXG.lower(), OTHER.lower()})
        first_success = next(index for index, row in enumerate(control.wire) if row.get('success'))
        self.assertTrue(all(row['sdkCalls'] == 0 for row in control.wire[:first_success + 1]),
                        'known complete paths must reach Helpers without SDK amount preflight')
        self.assertTrue(all(row['outputs'] == control.wire[0]['outputs'] for row in control.wire),
                        'composition changes market legs while preserving encoded Core identities')
        self.assertFalse(control.rpc.heads or control.rpc.verifications)

    async def test_duplicate_alternatives_do_not_expand_the_repair_tree(self):
        control = await self.successful(duplicates=True)
        identities = [proposal_identity({'inputs': REQUEST['inputs'], 'plan': plan})
                      for plan in control.attempts]
        self.assertLessEqual(len(set(identities)), 3)

    async def test_late_provider_revision_can_still_supply_joint_alternatives(self):
        await self.successful(late=True)

    async def test_all_fail_keeps_contract_failure_and_drains_provider(self):
        quoter, control = fixture(self, all_fail=True)
        async with asyncio.timeout(10):
            with self.assertRaises(QuoteFailure) as caught:
                await quoter.get(REQUEST, core_only=True)
        self.assertEqual(caught.exception.code, 'quote-contract-reverted')
        self.assertTrue(control.closed)

    async def test_cancellation_drains_partially_composed_plan(self):
        quoter, control = fixture(self, hold=True)
        task = asyncio.create_task(quoter.get(REQUEST, core_only=True))
        try:
            await asyncio.wait_for(control.held.wait(), 10)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(control.cancelled)
        self.assertTrue(control.closed)


if __name__ == '__main__':
    unittest.main()

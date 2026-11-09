"""Measured Core targets reach SDK inverses and complete Helpers bodies."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate.app_tokens import TOKENS
from cybergold_candidate.exact_input_plan import CORE_BUY, compile_plan
from cybergold_candidate.quoter.core_funding import core_funding_alternatives, compose_remaining_budget
from cybergold_candidate.quoter.evaluate import encode_nomination
from cybergold_candidate.quoter.plan_call import executable_body, compile_call
from cybergold_candidate.quoter.plan_simulation import HelpersPlanSimulation, project_core_inputs
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.routing_encoding import ZERO
from quoter_fixture import service, synthetic_pool
from test_quoter_plan_simulation import CODEC, Provider, Rpc, branches, encoded, measured, stage, NOW
from test_universal_quote import (BLOCK, CORE, PAXG, OTHER, WETH, HELPERS, ADAPTER, USER,
                                 capacity_nominations, settings)


def retained(asset):
    template = {'inputCurrency': asset, 'outputCurrency': CORE, 'routes': []}
    return {'inputCurrency': asset, 'outputCurrency': CORE,
            'branches': [], 'template': template}


def root_value(q, pools, *, native=False, identity=False):
    source = PAXG if identity else ZERO if native else WETH
    physical = WETH if native else source
    acquisitions, conversions, stages = [], {}, []
    for index, asset in enumerate((PAXG, OTHER)):
        if source.lower() == asset.lower():
            template = {'inputCurrency': asset, 'outputCurrency': asset, 'routes': []}
            chosen = {'inputCurrency': asset, 'outputCurrency': asset, 'branches': [], 'template': template}
        else:
            pool = pools[index]
            hops = [{'pool': pool, 'zeroForOne': physical.lower() == pool['token0']['address'].lower()}]
            if native:
                hops.insert(0, {'kind': 'wrap', 'currencyOut': WETH})
                stages.append(stage(len(stages), source, physical, 10000, 10000))
            template, chosen = encode_nomination(source, asset, ([{'amountIn': '10000', 'hops': hops}], []))
            stages.append(stage(len(stages), physical, asset, 10000, 9969))
        acquisitions.append({'amountIn': '10000', 'route': deepcopy(template)})
        conversions[f'0:acquire:{index}'] = chosen
        conversions[f'0:residual:{index}'] = retained(asset)
    for index, asset in enumerate((PAXG, OTHER)):
        acquired = 10000 if source.lower() == asset.lower() else 9969
        stages.append(stage(len(stages), asset, CORE, acquired, 100 if index == 0 else 0,
                            consumed=4000, returned=acquired-4000))
        stages.append(stage(len(stages), asset, CORE, acquired-4000, 0,
                            consumed=0, returned=acquired-4000))
    request = {'intent': 0, 'inputs': [{'currency': source, 'amount': '20000'}], 'outputCurrency': CORE}
    plan = {'allocations': [{'kind': 0, 'amountIn': '20000'}], 'conversions': conversions,
        'body': {'branches': [{'kind': 0, 'amountIn': '20000', 'data': {
            'basketAssets': [PAXG, OTHER], 'acquisitions': acquisitions,
            'continuations': [{'route': deepcopy(conversions[f'0:residual:{index}']['template']),
                               'feeCygld': '0'} for index in range(2)]}}]}}
    provider = Provider()
    rpc = Rpc(provider)
    q.engine.registry.get_rpc = lambda: rpc
    simulator = HelpersPlanSimulation(settings(), q.engine.registry, helpers=HELPERS,
        adapter=ADAPTER, core=CORE, now=lambda: NOW)
    value = simulator.project(request, plan,
        {**encoded(measured(100, stages=stages, fees=(1, 0, 0),
                           retained=[(0, 0, WETH, 123)])), 'observedAt': NOW},
        {'issued': 1, 'coalesced': 0, 'reused': 0}, rpc=rpc,
        tag='latest', block=None, pricing=True, candidate=None)
    return value, simulator, provider


class CoreFundingTests(unittest.IsolatedAsyncioTestCase):
    def service(self, *, identity=False, thin=True):
        source = PAXG if identity else WETH
        pools = [synthetic_pool(WETH, PAXG, 8901, 'v2'),
                 synthetic_pool(source, OTHER, 8902, 'v2'),
                 synthetic_pool(PAXG, CORE, 8903, 'v4', liquidity=10**5 if thin else 10**9)]
        return service(self, pools), pools

    async def first(self, q, value):
        alternatives = core_funding_alternatives(q, value, BLOCK, {})
        try:
            return await anext(alternatives)
        finally:
            await alternatives.aclose()

    async def collect(self, q, value):
        result = []
        try:
            async for proposal in core_funding_alternatives(q, value, BLOCK, {}):
                result.append(proposal)
        except QuoteFailure as error:
            # An unavailable optional Market composition does not erase the
            # independently emitted Core/useful-residual alternatives.
            self.assertEqual(error.code, 'quote-no-route')
        return result

    async def test_core_stages_are_distinct_from_aggregate_retained_charges(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        original = deepcopy(value)
        self.assertEqual(project_core_inputs(value, 1), [
            {'branch': 0, 'index': index, 'currency': asset,
             'acquired': 9969, 'consumed': 4000, 'residual': 5969}
            for index, asset in enumerate((PAXG, OTHER))])
        self.assertEqual(value, original)
        self.assertEqual(set(value), set(original))

    async def test_sdk_core_sizing_preserves_native_and_identity_funding(self):
        for native, identity in ((False, False), (True, False), (False, True)):
            with self.subTest(native=native, identity=identity):
                q, pools = self.service(identity=identity)
                value, _, _ = root_value(q, pools, native=native, identity=identity)
                original = deepcopy(value)
                proposal = await self.first(q, value)
                self.assertEqual(proposal['phase'], 'core-consumption')
                self.assertLess(int(proposal['inputs'][0]['amount']), 20000)
                self.assertEqual(proposal['inputs'][0]['currency'], value['inputs'][0]['currency'])
                data = proposal['plan']['body']['branches'][0]['data']
                self.assertEqual(sum(int(row['amountIn']) for row in data['acquisitions']),
                                 int(proposal['inputs'][0]['amount']))
                for index, asset in enumerate((PAXG, OTHER)):
                    acquisition = data['acquisitions'][index]
                    if identity and index == 0:
                        self.assertEqual(acquisition['amountIn'], '4000')
                        continue
                    chosen = proposal['plan']['conversions'][f'0:acquire:{index}']
                    _, output = await q.price_path(chosen['branches'][0]['hops'],
                        int(acquisition['amountIn']), BLOCK, {}, {})
                    self.assertGreaterEqual(output, 4000)
                    self.assertEqual(acquisition['route']['inputCurrency'].lower(),
                                     (WETH if native else value['inputs'][0]['currency']).lower())
                compiled = compile_plan({**value['request'], 'inputs': proposal['inputs'],
                    'recipient': USER, 'deadline': '0'}, executable_body(proposal['plan']['body']), 99)
                self.assertTrue(compiled['body'].startswith('0x'))
                self.assertEqual(compiled['inputs'], proposal['inputs'])
                self.assertEqual(value, original)

    async def test_complete_helpers_observation_prices_proposal_and_retains_original(self):
        q, pools = self.service()
        value, simulator, provider = root_value(q, pools)
        proposal = await self.first(q, value)
        amounts = [int(row['amountIn']) for row in proposal['plan']['body']['branches'][0]['data']['acquisitions']]
        stages = [stage(0, WETH, PAXG, amounts[0], 4000), stage(1, WETH, OTHER, amounts[1], 4000),
                  stage(2, PAXG, CORE, 4000, 100), stage(3, OTHER, CORE, 4000, 0)]
        provider.responses.append(encoded(measured(100, stages=stages, fees=(1, 0, 0))))
        q.plan_simulator = simulator
        result = await q.candidate({**value['request'], 'inputs': proposal['inputs']},
                                  100, 'core-first', BLOCK, [PAXG, OTHER], [500000, 500000],
                                  selected=proposal['plan'])
        self.assertEqual(result['quotedOutput'], '100')
        self.assertEqual(result['estimatedRetainedInputCharges'], [])
        self.assertEqual(result['inputs'], proposal['inputs'])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][1][1], 'latest')
        self.assertNotIn('inputLimitObserved', result['searchCoverage'])
        self.assertEqual(value['inputs'][0]['amount'], '20000')

    async def test_search_publishes_full_incumbent_then_helpers_validated_core_reduction(self):
        q, pools = self.service()
        root, simulator, provider = root_value(q, pools)
        q.discover = AsyncMock()
        q.route_provider_factory = lambda: []
        calls, responses = [], {}
        async def wire(method, params):
            provider.calls.append((method, deepcopy(params)))
            return deepcopy(responses[params[0]['data']])
        provider.make_request = wire
        async def capped_helpers(request, selected, **options):
            branches = selected['body']['branches']
            if len(branches) != 1 or branches[0]['kind'] != 0:
                raise QuoteFailure('quote-no-route')
            data, stages, acquired, bank = branches[0]['data'], [], [], {}
            for index, asset in enumerate(data['basketAssets']):
                acquisition = data['acquisitions'][index]
                amount = int(acquisition['amountIn'])
                chosen = selected['conversions'][f'0:acquire:{index}']
                _, output = await q.price_path(chosen['branches'][0]['hops'], amount, BLOCK, bank, {})
                stages.append(stage(len(stages), WETH, asset, amount, output))
                acquired.append(output)
            used = min(4000, *acquired)
            net = used * 100 // 4000
            retained_rows = []
            for index, (asset, amount) in enumerate(zip(data['basketAssets'], acquired, strict=True)):
                stages.append(stage(len(stages), asset, CORE, amount, net if index == 0 else 0,
                                    consumed=used, returned=amount-used))
                if amount > used:
                    stages.append(stage(len(stages), asset, CORE, amount-used, 0,
                                        consumed=0, returned=amount-used))
                    retained_rows.append((0, len(stages)-1, asset, amount-used))
            # The independent leaf models a capped Core and unavailable surplus
            # liquidity, then returns bytes through the actual Helpers decoder.
            response = encoded(measured(net, stages=stages, fees=(1, 0, 0), retained=retained_rows))
            compiled = compile_call(request, selected, chain=1, helpers=HELPERS,
                                    core=CORE, contract=simulator.contract)
            responses[compiled.params[0]['data']] = response
            calls.append(int(request['inputs'][0]['amount']))
            return await simulator(request, selected, **options)
        q.plan_simulator = capped_helpers
        events, budget = [], QuoteBudget()
        async def update(event):
            if event['type'] == 'qualified':
                events.append(deepcopy(event['value']))
                if int(event['value']['inputs'][0]['amount']) < 20000:
                    budget.finish_selection('measured-core-reduction')
        with patch('cybergold_candidate.quoter.search.CORE_SHARES', (100,)):
            async with asyncio.timeout(10):
                with budget_context(budget):
                    result = await q.get(root['request'], update, seed=root)
        self.assertEqual(events[0]['inputs'][0]['amount'], '20000')
        self.assertEqual(events[0]['quotedOutput'], '100')
        self.assertTrue(events[0]['estimatedRetainedInputCharges'])
        self.assertEqual(result['quotedOutput'], '100')
        self.assertLess(int(result['inputs'][0]['amount']), 20000)
        self.assertEqual(result['estimatedRetainedInputCharges'], [])
        self.assertNotIn('inputLimitObserved', result['searchCoverage'])
        self.assertIn(20000, calls)
        self.assertIn(int(result['inputs'][0]['amount']), calls)
        self.assertTrue(all(row[0] == 'eth_call' for row in provider.calls))

    async def test_100k_usdt_split_acquisitions_preserve_exact_net_core_output_after_fees(self):
        usdt, xaut = (dict(TOKENS)[name] for name in ('usdt', 'xaut'))
        decimals = {usdt.lower(): 6, xaut.lower(): 6, PAXG.lower(): 18, WETH.lower(): 18}
        reserves = {usdt.lower(): 40_000_000 * 10**6, xaut.lower(): 10_000 * 10**6,
                    PAXG.lower(): 10_000 * 10**18, WETH.lower(): 20_000 * 10**18}
        pools = []
        for number, (source, target) in enumerate(((usdt, PAXG), (usdt, WETH),
                                                   (WETH, PAXG), (usdt, xaut)), 8910):
            pool = synthetic_pool(source, target, number, 'v2')
            for index in (0, 1):
                currency = pool[f'token{index}']['address'].lower()
                pool[f'token{index}']['decimals'] = decimals[currency]
                pool[f'reserve{index}'] = str(reserves[currency])
            pools.append(pool)
        q = service(self, pools)
        assets, targets = [PAXG, xaut], [4661111320113019730, 3107408]
        async def basis(_):
            return assets, [600000, 400000]
        q.basis_reader, q.discover = basis, AsyncMock()
        q.seed_routes = lambda *_: None
        q.route_provider_factory = lambda: []
        def hop(source, pool):
            return {'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
        paths = [[hop(usdt, pools[0])], [hop(usdt, pools[1]), hop(WETH, pools[2])]]
        # Only acquisition topology is available: neither gold surplus nor
        # remaining USDT can buy CYGLD on a market route in this fixture.
        capacity_nominations(q.amm, {
            (usdt.lower(), PAXG.lower()): [(500000, paths[0]), (0, paths[1])],
            (usdt.lower(), xaut.lower()): [(0, [hop(usdt, pools[3])])],
        })
        budget_amount, expected_net = 100_000 * 10**6, 241386318399242216435
        # Independent capped-Core leaf: protocol 0.1%, Helpers 0.2%, both
        # rounded up. This gross cap delivers the exact requested net amount.
        gross_cap = 242112656368347258211
        def fees(gross):
            return tuple((gross * rate + 999999) // 1000000 for rate in (1000, 2000))
        self.assertEqual(gross_cap - sum(fees(gross_cap)), expected_net)
        request = {'intent': 0, 'inputs': [{'currency': usdt, 'amount': str(budget_amount)}],
                   'outputCurrency': CORE}
        acquisitions, conversions = [], {}
        for index, (asset, funded, selected_paths) in enumerate(zip(
                assets, (60_000 * 10**6, 40_000 * 10**6), (paths, [[hop(usdt, pools[3])]]), strict=True)):
            nominated = [{'amountIn': str(funded // len(selected_paths)), 'hops': path}
                         for path in selected_paths]
            template, chosen = encode_nomination(usdt, asset, (nominated, []))
            acquisitions.append({'amountIn': str(funded), 'route': template})
            conversions[f'0:acquire:{index}'] = chosen
            conversions[f'0:residual:{index}'] = retained(asset)
        plan = {'allocations': [{'kind': 0, 'amountIn': str(budget_amount)}], 'conversions': conversions,
                'body': {'branches': [{'kind': 0, 'amountIn': str(budget_amount), 'data': {
                    'basketAssets': assets, 'acquisitions': acquisitions,
                    'continuations': [{'route': deepcopy(conversions[f'0:residual:{index}']['template']),
                                       'feeCygld': '0'} for index in range(2)]}}]}}
        provider, executions, sdk_calls = Provider(), [], []
        rpc = Rpc(provider)
        q.engine.registry.get_rpc = lambda: rpc
        simulator = HelpersPlanSimulation(settings(), q.engine.registry, helpers=HELPERS,
            adapter=ADAPTER, core=CORE, now=lambda: NOW)
        real_sdk = q.engine.sdk.request
        async def observe_sdk(payload, **options):
            sdk_calls.append((payload.get('operation'), payload.get('mode')))
            return await real_sdk(payload, **options)
        q.engine.sdk.request = observe_sdk
        async def execute_helpers(method, params):
            provider.calls.append((method, deepcopy(params)))
            self.assertEqual(method, 'eth_call')
            _, values = simulator.contract.decode_function_input(params[0]['data'])
            body = branches(values)
            if len(body) != 1 or body[0][0] != 0:
                raise QuoteFailure('quote-no-route')
            encoded_assets, lots, continuations = CODEC.decode([CORE_BUY], body[0][2])[0]
            self.assertEqual([asset.lower() for asset in encoded_assets], [asset.lower() for asset in assets])
            self.assertEqual(sum(lot[0] for lot in lots), values['plan']['inputs'][0]['amount'])
            acquired, stages, bank, split_lots = [], [], {}, []
            # Decode the actual Helpers calldata and price its encoded ppm
            # splits and physical hops, rather than using inverse nominations.
            for asset, (funded, template) in zip(encoded_assets, lots, strict=True):
                allocated, output, portions = 0, 0, []
                for index, (share, steps) in enumerate(template[3]):
                    portion = funded - allocated if index == len(template[3])-1 else funded * share // 1000000
                    allocated += portion
                    source, physical = template[0], []
                    for kind, target, fee, _ in steps:
                        self.assertEqual(kind, 0)
                        pool = next(row for row in pools if {
                            row['token0']['address'].lower(), row['token1']['address'].lower()
                        } == {source.lower(), target.lower()})
                        self.assertEqual(fee, pool['feePips'])
                        physical.append(hop(source, pool))
                        source = target
                    used, received = await q.price_path(physical, portion, BLOCK, bank, {})
                    self.assertEqual(used, portion)
                    output += received
                    portions.append(portion)
                acquired.append(output)
                split_lots.append(portions)
                stages.append(stage(len(stages), usdt, asset, funded, output))
            gross = min(gross_cap, *(amount * gross_cap // target
                                     for amount, target in zip(acquired, targets, strict=True)))
            protocol_fee, helper_fee = fees(gross)
            net = gross - protocol_fee - helper_fee
            residuals, retained_rows = [], []
            for index, (asset, amount, target) in enumerate(zip(encoded_assets, acquired, targets, strict=True)):
                consumed = (target * gross + gross_cap - 1) // gross_cap
                residual = amount - consumed
                residuals.append(residual)
                stages.append(stage(len(stages), asset, CORE, amount, net if index == 0 else 0,
                                    consumed=consumed, returned=residual))
                self.assertEqual(continuations[index][0][3], ())
                if residual:
                    stages.append(stage(len(stages), asset, CORE, residual, 0, consumed=0, returned=residual))
                    retained_rows.append((0, len(stages)-1, asset, residual))
            executions.append({'funding': values['plan']['inputs'][0]['amount'], 'acquired': acquired,
                               'gross': gross, 'net': net, 'fees': (protocol_fee, helper_fee),
                               'retained': residuals, 'splitLots': split_lots})
            return encoded(measured(net, stages=stages, fees=(protocol_fee, helper_fee, 0), retained=retained_rows))
        provider.make_request, q.plan_simulator = execute_helpers, simulator
        root = await simulator(request, plan)
        self.assertEqual([row['consumed'] for row in project_core_inputs(root, 1)], targets)
        self.assertEqual(root['quotedOutput'], str(expected_net))
        self.assertEqual(plan['body']['branches'][0]['data']['acquisitions'][0]['route']['routes'][0]['sharePpm'], 500000)
        initial_retained = executions[0]['retained']
        events, budget = [], QuoteBudget()
        async def update(event):
            if event['type'] == 'qualified':
                value = event['value']
                events.append(deepcopy(value))
                if int(value['inputs'][0]['amount']) < budget_amount and int(value['quotedOutput']) == expected_net:
                    budget.finish_selection('equal-net-smaller-usdt-funding')
        with patch('cybergold_candidate.quoter.search.CORE_SHARES', (100,)):
            async with asyncio.timeout(15):
                with budget_context(budget):
                    result = await q.get(request, update, seed=root)
        self.assertEqual(events[0]['inputs'][0]['amount'], str(budget_amount))
        self.assertEqual(result['quotedOutput'], str(expected_net))
        self.assertLess(int(result['inputs'][0]['amount']), budget_amount,
                        [(row['funding'], row['net']) for row in executions])
        selected = next(row for row in executions if row['funding'] == int(result['inputs'][0]['amount'])
                        and row['net'] == expected_net)
        self.assertEqual(selected['gross'], gross_cap)
        self.assertGreater(selected['gross'], selected['net'])
        self.assertEqual(result['fees']['coreProtocolFeeCygld'], str(selected['fees'][0]))
        self.assertEqual(result['fees']['coreHelpersFeeCygld'], str(selected['fees'][1]))
        self.assertTrue(all(fee > 0 for fee in selected['fees']))
        self.assertEqual(result['fees']['marketFeeCygld'], '0')
        self.assertEqual(result['estimatedRecipientOutputs'][0]['amount'], str(expected_net))
        self.assertTrue(all(final < initial for final, initial in zip(selected['retained'], initial_retained, strict=True)))
        self.assertTrue(all(amount >= target for amount, target in zip(selected['acquired'], targets, strict=True)))
        self.assertEqual(len(selected['splitLots'][0]), 2)
        self.assertTrue(any(mode == 'exactOut' for _, mode in sdk_calls))
        self.assertTrue(any(mode == 'exactIn' for _, mode in sdk_calls))
        self.assertNotIn('inputLimitObserved', result['searchCoverage'])
        self.assertEqual(request['inputs'][0]['amount'], str(budget_amount))

    async def test_primary_market_keeps_actual_sdk_downstream_partial_funding(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        reduced = await self.first(q, value)
        rows = project_core_inputs(value, 1)
        proposals = [row async for row in compose_remaining_budget(q, value, reduced, rows, BLOCK, {})]
        self.assertEqual(len(proposals), 2)
        available = 20000 - int(reduced['inputs'][0]['amount'])
        for proposal in proposals:
            branch = next(row for row in proposal['plan']['body']['branches'] if row['kind'] == 1)
            self.assertGreater(int(branch['amountIn']), 0)
            self.assertLess(int(branch['amountIn']), available)
            self.assertEqual(int(proposal['inputs'][0]['amount']),
                             int(reduced['inputs'][0]['amount']) + int(branch['amountIn']))
        market_first = next(row for row in proposals if row['plan']['body']['branches'][0]['kind'] == 1)
        chosen = market_first['plan']['conversions']['0:market']
        self.assertGreater(len(chosen['branches'][0]['hops']), 1)
        _, output = await q.price_path(chosen['branches'][0]['hops'],
            int(market_first['plan']['body']['branches'][0]['amountIn']), BLOCK, {}, {})
        self.assertGreater(output, 0)

    async def test_useful_partial_residual_keeps_untradable_sibling_and_both_market_orders(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        convert = q.conversion
        async def liquidity(source, *args, **kwargs):
            if source.lower() == OTHER.lower():
                raise QuoteFailure('quote-no-route')
            return await convert(source, *args, **kwargs)
        q.conversion = liquidity
        proposals = await self.collect(q, value)
        reduced = next(row for row in proposals if row['phase'] == 'core-consumption')
        useful = next(row for row in proposals if row['phase'] == 'useful-core-residual')
        self.assertGreater(int(useful['inputs'][0]['amount']), int(reduced['inputs'][0]['amount']))
        self.assertLess(int(useful['inputs'][0]['amount']), 20000)
        continuations = useful['plan']['body']['branches'][0]['data']['continuations']
        self.assertTrue(continuations[0]['route']['routes'])
        self.assertEqual(continuations[1]['route']['routes'], [])
        self.assertTrue(all(route['steps'] for route in continuations[0]['route']['routes']))
        compositions = [row for row in proposals if row['phase'] == 'core-market-funding']
        self.assertEqual({tuple(branch['kind'] for branch in row['plan']['body']['branches'])
                          for row in compositions}, {(0, 1), (1, 0)})
        for row in compositions:
            self.assertLessEqual(int(row['inputs'][0]['amount']), 20000)
            self.assertEqual(int(row['inputs'][0]['amount']), sum(int(branch['amountIn'])
                for branch in row['plan']['body']['branches']))
            core_index = next(index for index, branch in enumerate(row['plan']['body']['branches']) if branch['kind'] == 0)
            self.assertIn(f'{core_index}:acquire:0', row['plan']['conversions'])
            self.assertIn(f'{1-core_index}:market', row['plan']['conversions'])

    async def test_direct_basket_uses_measured_vector_without_inverse_or_scalar_sum(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        value['request'] = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '9969'},
            {'currency': OTHER, 'amount': '9969'}], 'outputCurrency': CORE}
        value['inputs'] = deepcopy(value['request']['inputs'])
        value['plan']['body'] = {'continuations': value['plan']['body']['branches'][0]['data']['continuations']}
        value['plan']['allocations'] = []
        value['pricingEvidence']['stages'] = value['pricingEvidence']['stages'][2:]
        with patch('cybergold_candidate.quoter.core_funding.inverse_conversion',
                   side_effect=AssertionError('Basket input is already the asset vector')):
            proposal = await self.first(q, value)
        self.assertEqual(proposal['inputs'], [{'currency': PAXG, 'amount': '4000'},
                                             {'currency': OTHER, 'amount': '4000'}])
        self.assertEqual(proposal['plan']['allocations'], [])

    async def test_missing_core_evidence_and_market_only_do_no_sdk_work(self):
        q = SimpleNamespace(engine=SimpleNamespace(registry=SimpleNamespace(chain=1)), conversion=AsyncMock())
        for value in ({'request': {'intent': 1}}, {'request': {'intent': 0}, 'pricingEvidence': {}},
                {'request': {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '1'}], 'outputCurrency': CORE},
                 'plan': {'body': {'branches': []}}, 'pricingEvidence': {'stages': []}}):
            self.assertEqual([row async for row in core_funding_alternatives(q, value, BLOCK, {})], [])
        q.conversion.assert_not_awaited()

    async def test_fully_consumed_basket_does_not_reprice_unused_continuations(self):
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '100'},
            {'currency': OTHER, 'amount': '100'}], 'outputCurrency': CORE}
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        value.update(request=request, inputs=deepcopy(request['inputs']),
            plan={'allocations': [], 'conversions': {}, 'body': {'continuations': [
                {'route': {'inputCurrency': asset, 'outputCurrency': asset, 'routes': []}, 'feeCygld': '0'}
                for asset in (PAXG, OTHER)]}})
        value['pricingEvidence']['stages'] = [
            {'inputCurrency': asset, 'outputCurrency': CORE, 'fundedInput': '100',
             'consumedInput': '100', 'returnedInput': '0', 'amountOut': '100' if index == 0 else '0'}
            for index, asset in enumerate((PAXG, OTHER))]
        self.assertEqual([row async for row in core_funding_alternatives(q, value, BLOCK, {})], [])

    async def test_failed_inverse_still_allows_independent_useful_residual_proposal(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        from cybergold_candidate.quoter.inverse import inverse_conversion
        called = False
        async def first_fails(*args, **kwargs):
            nonlocal called
            if not called:
                called = True
                raise QuoteFailure('quote-no-route')
            return await inverse_conversion(*args, **kwargs)
        with patch('cybergold_candidate.quoter.core_funding.inverse_conversion', first_fails):
            proposals = await self.collect(q, value)
        self.assertTrue(any(row['phase'] == 'useful-core-residual' for row in proposals))

    async def test_zero_weight_acquisition_needs_no_unused_route_metadata(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        asset = '0x' + '77' * 20
        data = value['plan']['body']['branches'][0]['data']
        data['basketAssets'].append(asset)
        data['acquisitions'].append({'amountIn': '0', 'route': {
            'inputCurrency': WETH, 'outputCurrency': asset, 'routes': []}})
        data['continuations'].append({'route': retained(asset)['template'], 'feeCygld': '0'})
        value['pricingEvidence']['stages'].append({'inputCurrency': asset, 'outputCurrency': CORE,
            'fundedInput': '0', 'consumedInput': '0', 'returnedInput': '0', 'amountOut': '0'})
        proposals = await self.collect(q, value)
        self.assertTrue(any(row['phase'] == 'useful-core-residual' for row in proposals))
        for proposal in proposals:
            core = next(row for row in proposal['plan']['body']['branches'] if row['kind'] == 0)
            self.assertEqual(core['data']['acquisitions'][2]['amountIn'], '0')

    async def test_core_only_keeps_core_and_residual_sizing_without_primary_market(self):
        q, pools = self.service()
        value, _, _ = root_value(q, pools)
        proposals = [row async for row in core_funding_alternatives(q, value, BLOCK, {}, core_only=True)]
        self.assertIn('core-consumption', {row['phase'] for row in proposals})
        self.assertIn('useful-core-residual', {row['phase'] for row in proposals})
        self.assertTrue(all(branch['kind'] == 0 for row in proposals
                            for branch in row['plan']['body']['branches']))


if __name__ == '__main__':
    unittest.main()

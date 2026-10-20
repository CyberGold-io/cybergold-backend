"""Universal exact-input plans: one joint Core call and ordered AMM replay.

Every candidate owns its pool-state bank. Quotes model disclosed treasury
retention; they never subtract retained principal from the user's gross spend.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations

from fastapi.responses import JSONResponse
from web3 import Web3

from .basket_preview import BasketPreviewRpc, InvalidPreview
from .exact_input_plan import UniversalExactInputRequest, compile_plan
from .execution_tolerance import floor
from .market_fee import get_market_fee_rate, quoted_fee, routed_sell_budget
from .protocol_config import configured_address
from .quote_budget import budget_entry, current_budget, SearchStopped, budget_context, QuoteBudget
from .quote_errors import QuoteFailure, public_quote_error, rpc_failure
from .recovery_rpc import SnapshotChanged
from .preview_errors import preview_error
from .routing_encoding import ZERO, ROUTING_ENCODING, weighted_routes, split_runtime
from .route_search import WETH
from .uniswap_routes import pool_identity, opposite, V4_CONNECTOR_KEYS, initial_v3_branches
from .uniswap_v4 import v4_pool_id, POOL_MANAGER
from .wallet_balances import TOKENS
from .uniswap_state import owned_reads
from .route_work_slots import engine_work

PAXG = dict(TOKENS)['paxg']
CORE_SHARES = (0, 25, 50, 75, 100)


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency,
            'minimumOutput': '0', 'routes': []}


def paths(pools, source, target, weth=WETH, max_hops=3):
    """Selected pool graph plus explicit lossless native/WETH transitions."""
    graph = {}
    unique = {}
    for pool in pools:
        identity = pool_identity(pool)
        if identity not in unique or pool.get('address'):
            unique[identity] = pool
    for pool in unique.values():
        if pool.get('hooks', ZERO).lower() != ZERO:
            continue
        for token in (pool['token0'], pool['token1']):
            graph.setdefault(token['address'].lower(), []).append(pool)
    found = []
    def walk(current, route, visited, hops):
        if current == target.lower():
            if route:
                found.append(route)
            return
        if hops < max_hops:
            for pool in sorted(graph.get(current, []), key=lambda row: (row['protocol'], row['id'])):
                following = opposite(pool, current)
                if following not in visited:
                    walk(following, route + [{'pool': pool, 'zeroForOne': current == pool['token0']['address'].lower()}],
                         visited | {following}, hops + 1)
        if current in (ZERO, weth.lower()):
            following = weth.lower() if current == ZERO else ZERO
            if following not in visited:
                walk(following, route + [{'kind': 'wrap' if current == ZERO else 'unwrap',
                    'currencyOut': following}], visited | {following}, hops)
    walk(source.lower(), [], {source.lower()}, 0)
    return sorted(found, key=lambda route: (len(route), repr(route)))


def route_candidates(routes, amount):
    for route in routes:
        yield [{'amountIn': str(amount), 'hops': route}]
    for left, right in combinations(routes, 2):
        for share in (25, 50, 75):
            first = amount * share // 100
            if first and amount - first:
                yield [{'amountIn': str(first), 'hops': left}, {'amountIn': str(amount - first), 'hops': right}]


class UniversalQuotes:
    def __init__(self, settings, engine, *, preview=None, basis_reader=None, now=None):
        self.settings, self.engine = settings, engine
        self.adapter = configured_address(settings, 'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS')
        self.helpers = configured_address(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS')
        self.core = configured_address(settings, 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS')
        self.preview = preview
        self.basis_reader = basis_reader
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def basis(self, block):
        if self.basis_reader:
            return await self.basis_reader(block)
        rpc = self.engine.registry.get_rpc()
        assets, weights = await asyncio.gather(
            rpc.read_function(self.core, 'basketAssets()', [], [], ['address[]'], block),
            rpc.read_function(self.core, 'basketTargetsPpm()', [], [], ['uint256[]'], block))
        return list(assets[0]), list(map(int, weights[0]))

    async def core_preview(self, mode, value, block):
        if self.preview:
            return await self.preview(mode, value, block)
        if mode == 'issue-exact-in':
            rpc = self.engine.registry.get_rpc()
            data = Web3.keccak(text='previewIssueFromBasketExactIn(uint256[])')[:4] + rpc.w3.codec.encode(
                ['uint256[]'], [list(map(int, value['maximumAmountsIn']))])
            response = await rpc.w3.provider.make_request('eth_call', [
                {'from': self.helpers, 'to': self.core, 'data': Web3.to_hex(data)},
                {'blockHash': block['hash'], 'requireCanonical': True}])
            if 'error' in response:
                raise preview_error(response['error'], mode=mode, arguments=value) or rpc_failure(response['error'])
            target, protocol_fee, exact, assets = rpc.w3.codec.decode(
                ['uint256', 'uint256', 'uint256[]', 'address[]'], bytes.fromhex(response['result'][2:]))
            rate, = await rpc.read_function(self.helpers, 'helperFeePpm()', [], [], ['uint256'], block)
            helper_fee = target * rate // 1_000_000
            return {'netCygldOut': str(target - helper_fee),
                'fees': {'protocolFeeCygld': str(protocol_fee), 'helperFeeCygld': str(helper_fee)},
                'amountsInExact': list(map(str, exact)), 'orderedCoreAssets': list(map(Web3.to_checksum_address, assets))}
        rpc = BasketPreviewRpc(self.settings, self.engine.registry.get_rpc().w3)
        payload = {'mode': mode, **value}
        return await rpc.preview(mode, rpc.encode(payload), block)

    def seed_routes(self, request, assets):
        """Execution identities, before optional factory/metadata observations.

        This is the existing direct/via-WETH V3 seed plus native V4 PoolKeys.
        Neither an identity nor a display scale claims liquidity or a quote.
        """
        registry = self.engine.registry
        payment = request['inputs'][0]['currency'] if request['intent'] == 0 else request['outputCurrency']
        if payment.lower() == ZERO:
            payment = WETH
        known = {pool_identity(pool) for pool in registry.inventory.values()}
        for asset in dict.fromkeys([PAXG, *assets]):
            for branches in initial_v3_branches({'inputAsset': payment, 'outputAsset': asset,
                                                 'amount': '1'}, 'exactIn', registry.chain):
                for branch in branches:
                    for hop in branch['hops']:
                        pool = hop['pool']
                        if pool_identity(pool) not in known:
                            registry.inventory[pool['id']] = pool
                            known.add(pool_identity(pool))
        currencies = sorted({ZERO, WETH.lower(), payment.lower(), PAXG.lower(), *(asset.lower() for asset in assets)})
        for a, b in combinations(currencies, 2):
            if ZERO not in (a, b):
                continue
            for fee, spacing in V4_CONNECTOR_KEYS:
                identity = v4_pool_id((a, b, fee, spacing, ZERO))
                registry.inventory.setdefault(identity, {'id': identity, 'protocol': 'v4',
                    **{f'token{index}': deepcopy(getattr(registry, 'metadata', {}).get(currency) or {
                        'address': Web3.to_checksum_address(currency), 'chainId': registry.chain,
                        'decimals': 18 if currency == ZERO else None}) for index, currency in enumerate((a, b))},
                    'feePips': fee, 'tickSpacing': spacing, 'hooks': ZERO, 'poolManager': POOL_MANAGER})

    async def discover(self, request, assets, block):
        registry = self.engine.registry
        await registry.ensure_loaded()
        payment = request['inputs'][0]['currency'] if request['intent'] == 0 else request['outputCurrency']
        if payment.lower() == ZERO:
            payment = WETH
        await owned_reads(*(self.engine.connector_inventory(payment, asset, block)
            for asset in dict.fromkeys([payment, PAXG, *assets]) if asset.lower() != payment.lower()))
        # Native V4 keys have no pair factory. The snapshot producer observes
        # these ordinary hookless candidates, including on a cold inventory.
        currencies = sorted({ZERO, WETH.lower(), payment.lower(), PAXG.lower(),
                             *(asset.lower() for asset in assets)})
        async def metadata(currency):
            if currency == ZERO:
                return registry.token(currency, 18)
            try:
                return await registry.token_metadata(currency, block)
            except SnapshotChanged:
                raise
            except Exception:
                # Match the registry's discovery contract: display scale can
                # be unknown while raw integer pricing remains available.
                return {**registry.token(currency, 18), 'decimalsKnown': False}
        observed = await owned_reads(*(metadata(currency) for currency in currencies))
        tokens = dict(zip(currencies, observed, strict=True))
        for a, b in combinations(currencies, 2):
            if ZERO not in (a, b):
                continue
            for fee, spacing in V4_CONNECTOR_KEYS:
                key = (a, b, fee, spacing, ZERO)
                identity = v4_pool_id(key)
                pool = registry.inventory.setdefault(identity, {'id': identity, 'protocol': 'v4',
                    'token0': deepcopy(tokens[a]), 'token1': deepcopy(tokens[b]), 'feePips': fee,
                    'tickSpacing': spacing, 'hooks': ZERO, 'poolManager': POOL_MANAGER})
                for index, currency in enumerate((a, b)):
                    if pool[f'token{index}'].get('decimals') is None:
                        pool[f'token{index}'] = deepcopy(tokens[currency])

    async def price_path(self, route, amount, block, bank, canonical):
        current, used = amount, amount
        for index, hop in enumerate(route):
            if not current:
                break
            if 'kind' in hop:
                continue
            async with engine_work(self.engine.semaphore):
                value = await self.engine.quote_sdk_branches([{'amountIn': str(current), 'hops': [hop]}],
                    'exactIn', current, block, candidate=bank, canonical=canonical)
            debit, output = int(value['amountIn']), int(value['amountOut'])
            if index == 0:
                used = debit
            elif debit < current:
                raise InvalidPreview('Unsettled current-operation intermediate currency.')
            current = output
        return used, current

    async def conversion(self, source, target, amount, block, bank, canonical, *, market=False,
                         first=False, branch=0, stage=0):
        if not amount or source.lower() == target.lower():
            return identity_template(source), amount, []
        registry = self.engine.registry
        selected = paths(list(registry.inventory.values()), source, target)
        if market:
            anchor = pool_identity(registry.seed)
            selected = [route for route in selected if pool_identity(
                next(hop for hop in (route if source.lower() == self.core.lower() else reversed(route))
                     if 'pool' in hop)['pool']) == anchor]
        if first:
            # Preserve the existing V3 seed's prompt executable candidate before
            # cold, possibly uninitialized V4 connector keys. Refinement still
            # explores every selected protocol/path and split allocation.
            canonical_edge = pool_identity(registry.seed)
            selected.sort(key=lambda route: (sum(hop['pool']['protocol'] == 'v4' and
                pool_identity(hop['pool']) != canonical_edge for hop in route if 'pool' in hop),
                sum(hop['pool']['protocol'] == 'v3' and not hop['pool'].get('address') for hop in route if 'pool' in hop),
                sum(hop['pool']['protocol'] == 'v3' and hop['pool']['feePips'] != 3000 for hop in route if 'pool' in hop), len(route)))
        best, rpc_error = None, None
        for branches in route_candidates(selected, amount):
            # A common leading wrap belongs to Helpers funding, not to the
            # adapter's whole-conversion intermediate set.
            leading = [row['hops'][0].get('kind') for row in branches]
            normalized = deepcopy(branches)
            physical_source = source
            if leading and leading[0] in ('wrap', 'unwrap') and all(value == leading[0] for value in leading):
                physical_source = normalized[0]['hops'][0]['currencyOut']
                for row in normalized:
                    row['hops'] = row['hops'][1:]
            routes = weighted_routes(normalized)
            for row, funded in zip(normalized, split_runtime(amount, routes), strict=True):
                row['amountIn'] = str(funded)
            trial = deepcopy(bank)
            output, retained = 0, []
            try:
                for row in normalized:
                    funded = int(row['amountIn'])
                    used, received = await self.price_path(row['hops'], funded, block, trial, canonical)
                    output += received
                    if used < funded:
                        retained.append({'branch': branch, 'stage': stage + (physical_source.lower() != source.lower()), 'currency': physical_source,
                                         'amount': str(funded - used)})
            except SnapshotChanged:
                raise
            except Exception as error:
                if public_quote_error(error).get('code', '').startswith('rpc-'):
                    rpc_error = error
                continue
            if retained:
                retained = [{**retained[0], 'amount': str(sum(int(row['amount']) for row in retained))}]
            if best is None or output > best[0]:
                template = {'inputCurrency': physical_source, 'outputCurrency': target,
                            'minimumOutput': '0', 'routes': routes}
                best = output, template, retained, trial
                if first:
                    break
            await asyncio.sleep(0)
        if best is None:
            raise rpc_error or QuoteFailure('quote-no-route')
        bank.clear()
        bank.update(best[3])
        return best[1], best[0], best[2]

    async def candidate(self, request, share, order, block, assets, weights, *, first=False, core_sale_bounds=None,
                        observations=None):
        bank, canonical, retained, branches = {}, observations if observations is not None else {}, [], []
        fees = {'coreProtocolFeeCygld': 0, 'coreHelpersFeeCygld': 0, 'marketFeeCygld': 0}
        intent = request['intent']
        amount = int(request['inputs'][0]['amount'])
        core_amount = amount * share // 100
        market_amount = amount - core_amount
        output, recovery, recipient_outputs, cursor = 0, [], [], 0
        has_continuation = False
        budget = current_budget()
        async def convert(source, target, lot, **kwargs):
            nonlocal cursor
            kwargs['stage'] = cursor
            operation = self.conversion(source, target, lot, block, bank, canonical, first=first, **kwargs)
            result = await budget.discovery(operation) if budget else await operation
            route = result[0]
            if lot and source.lower() != target.lower():
                cursor += (source.lower() != route['inputCurrency'].lower()) + (
                    route['inputCurrency'].lower() != route['outputCurrency'].lower()) + (
                    route['outputCurrency'].lower() != target.lower())
            return result
        async def continuation(lots, branch):
            nonlocal output, cursor, has_continuation
            result = []
            for index, (asset, lot) in enumerate(zip(assets, lots, strict=True)):
                cursor += 1  # Core issuance appends each actual/residual basket lot.
                if not lot:
                    result.append({'route': identity_template(asset), 'feeCygld': '0'})
                    continue
                has_continuation = True
                route, gross, left = await convert(asset, self.core, lot, market=True,
                                                   branch=branch, stage=index + len(assets))
                fee = quoted_fee(gross, get_market_fee_rate(self.engine.registry.chain, asset, self.core, 'exact-in'))
                output += gross - fee
                fees['marketFeeCygld'] += fee
                retained.extend(left)
                result.append({'route': route, 'feeCygld': str(fee)})
            return result
        async def core_buy(lot, branch):
            nonlocal output
            payment = request['inputs'][0]['currency']
            allocated, acquired, acquisitions = 0, [], []
            positive = [i for i, weight in enumerate(weights) if weight]
            for index, asset in enumerate(assets):
                value = lot - allocated if index == positive[-1] else lot * weights[index] // sum(weights)
                allocated += value
                route, received, left = await convert(payment, asset, value, branch=branch, stage=index)
                acquired.append(received)
                acquisitions.append({'amountIn': str(value), 'route': route})
                retained.extend(left)
            result = await self.core_preview('issue-exact-in', {'maximumAmountsIn': list(map(str, acquired))}, block)
            fees['coreProtocolFeeCygld'] += int(result['fees']['protocolFeeCygld'])
            fees['coreHelpersFeeCygld'] += int(result['fees']['helperFeeCygld'])
            output += int(result['netCygldOut'])
            residual = [a - int(b) for a, b in zip(acquired, result['amountsInExact'], strict=True)]
            tails = await continuation(residual, branch)
            return {'basketAssets': result['orderedCoreAssets'], 'acquisitions': acquisitions, 'continuations': tails}
        async def core_sell(lot, branch, basket=False):
            nonlocal output, recovery, recipient_outputs
            result = await self.core_preview('redeem-exact-in', {'grossCygldIn': str(lot)}, block)
            fees['coreProtocolFeeCygld'] += int(result['fees']['protocolFeeCygld'])
            fees['coreHelpersFeeCygld'] += int(result['fees']['helperFeeCygld'])
            expected, conversions = [], []
            for index, row in enumerate(result['projectedCoreOutputs']):
                expected.append({key: row[key] for key in ('kind', 'token', 'id')} |
                                {'minimumAmount': str(floor(int(row['amount']), request['slippageBps']))})
                if basket:
                    recipient_outputs.append(row)
                if row['kind'] != 0:
                    if int(row['amount']): recovery.append(row)
                    conversions.append(identity_template(row['token']))
                    continue
                if basket:
                    continue
                route, received, left = await convert(row['token'], request['outputCurrency'], int(row['amount']),
                                                      branch=branch, stage=index)
                output += received
                retained.extend(left)
                conversions.append(route)
            if core_sale_bounds:
                for row, bound in zip(result['projectedCoreOutputs'], core_sale_bounds['expectedOutputs'], strict=True):
                    if any(str(row[key]).lower() != str(bound[key]).lower() for key in ('kind', 'token', 'id')):
                        raise InvalidPreview('Accepted Core output identity changed.')
                    if int(row['amount']) < int(bound['minimumAmount']):
                        raise InvalidPreview('Accepted Core output minimum cannot be met.')
                expected = deepcopy(core_sale_bounds['expectedOutputs'])
            return {'expectedOutputs': expected, 'conversions': conversions}
        async def market(lot, branch):
            nonlocal output
            source = request['inputs'][0]['currency']
            target = request['outputCurrency']
            rate = get_market_fee_rate(self.engine.registry.chain, source, target, 'exact-in')
            _routed, fee, _dust = routed_sell_budget(lot, rate) if intent == 1 else (lot, 0, 0)
            routed = lot - fee if intent == 1 else lot
            route, gross, left = await convert(source, target, routed, market=True, branch=branch)
            if intent == 0:
                fee = quoted_fee(gross, rate)
            output += gross - (fee if intent == 0 else 0)
            fees['marketFeeCygld'] += fee
            retained.extend(left)
            return {'route': route, 'feeCygld': str(fee)}
        if intent in (0, 1):
            stages = [('core', core_amount), ('market', market_amount)]
            if order == 'market-first': stages.reverse()
            for kind, lot in stages:
                if not lot:
                    continue
                index = len(branches)
                data = await (core_buy(lot, index) if intent == 0 else core_sell(lot, index)) if kind == 'core' else await market(lot, index)
                branches.append({'kind': 0 if kind == 'core' else 1, 'amountIn': str(lot), 'data': data})
            body = {'branches': branches}
        elif intent == 2:
            acquired = [int(row['amount']) for row in request['inputs']]
            result = await self.core_preview('issue-exact-in', {'maximumAmountsIn': list(map(str, acquired))}, block)
            fees['coreProtocolFeeCygld'] = int(result['fees']['protocolFeeCygld'])
            fees['coreHelpersFeeCygld'] = int(result['fees']['helperFeeCygld'])
            output += int(result['netCygldOut'])
            body = {'continuations': await continuation([a - int(b) for a, b in
                zip(acquired, result['amountsInExact'], strict=True)], 0)}
        else:
            body = await core_sell(amount, 0, basket=True)
        minimum = floor(output, request['slippageBps'])
        if core_sale_bounds:
            minimum = int(core_sale_bounds['minimumOutput'])
            if output < minimum:
                raise InvalidPreview('Accepted scalar output minimum cannot be met.')
        if intent != 3 and not minimum and not recovery:
            raise InvalidPreview('This scalar trade has no final output or recovery shares.')
        plan = compile_plan(request, body, minimum)
        family = 'core' if share == 100 else 'market' if share == 0 else 'mixed'
        if intent in (0, 2) and has_continuation:
            family = 'mixed'
        return {'strategy': 'universal', 'routeFamily': family, 'operation': 'executeExactInput',
            'settlementPolicy': 'protocol-retained-input', 'plan': plan, 'planDescription': body,
            'inputs': deepcopy(request['inputs']), 'quotedOutput': str(output),
            **({'quotedInput': str(amount), 'inputMaximum': str(amount)} if intent != 2 else {}),
            'outputMinimum': str(minimum),
            'estimatedRetainedInputCharges': retained, 'fees': {key: str(value) for key, value in fees.items()},
            'estimatedRecipientOutputs': recipient_outputs if intent == 3 else [
                {'kind': 0, 'token': request['outputCurrency'], 'id': '0', 'amount': str(output)}],
            'retentionDisclosure': {'custodian': self.helpers, 'beneficiary': 'helpers-owner-at-settlement'},
            'recoveryShares': recovery, 'deployment': {'helpers': self.helpers, 'adapter': self.adapter,
                'encoding': ROUTING_ENCODING}, 'context': {'chainId': self.engine.registry.chain,
                'blockNumber': str(block['number']), 'blockHash': block['hash'], 'observedAt': self.now()},
            'searchCoverage': {'coreSharesPercent': [100] if core_sale_bounds else list(CORE_SHARES), 'orders': ['core-first', 'market-first'],
                               'maxCoreInvocations': 1, 'maxAmmHops': 3, 'scope': 'selected-inventory'}}

    async def scalar_request(self, request, on_update=None):
        buy = request['side'] == 'buy'
        counter = ZERO if request.get('native') else request['counterToken']
        return await self.get({'intent': 0 if buy else 1,
            'inputs': [{'currency': counter if buy else self.core, 'amount': request['amount']}],
            'outputCurrency': self.core if buy else counter, 'recipient': request['recipient'],
            'deadline': request['deadline'], 'slippageBps': request.get('slippageBps', 100)}, on_update)

    async def core_sale_from_legacy(self, request, legacy, on_update=None):
        """A fresh Core-only quote at solved gross Q, with accepted minima frozen."""
        provider = legacy['providerQuote']
        value = {'intent': 1, 'inputs': [{'currency': self.core, 'amount': provider['executionAmount']}],
            'outputCurrency': ZERO if request.get('native') else request['counterToken'],
            'recipient': request['recipient'], 'deadline': request['deadline'],
            'slippageBps': request.get('slippageBps', 100)}
        bounds = {'minimumOutput': legacy['outputMinimum'],
                  'expectedOutputs': deepcopy(provider['expectedCoreOutputs'])}
        # The numeric output-target solver has finished its own selection window.
        # This newly disclosed execution quote owns the ordinary fresh window.
        with budget_context(QuoteBudget()):
            return await self.get(value, on_update, core_sale_bounds=bounds)

    @budget_entry
    async def get(self, request, on_update=None, *, core_sale_bounds=None):
        return await current_budget().produce(self._get(request, on_update, core_sale_bounds=core_sale_bounds))

    async def _get(self, request, on_update=None, *, core_sale_bounds=None):
        request = UniversalExactInputRequest.model_validate(request).model_dump()
        request['recipient'] = Web3.to_checksum_address(request['recipient'])
        request['outputCurrency'] = Web3.to_checksum_address(request['outputCurrency'])
        for row in request['inputs']:
            row['currency'] = Web3.to_checksum_address(row['currency'])
            Web3().codec.encode(['uint256'], [int(row['amount'])])
        if request['intent'] != 2:
            if len(request['inputs']) != 1:
                raise InvalidPreview('This intent requires exactly one input currency.')
            if request['intent'] != 0 and request['inputs'][0]['currency'].lower() != self.core.lower():
                raise InvalidPreview('This intent requires CYGLD as its exact input currency.')
        if request['intent'] in (0, 2) and request['outputCurrency'].lower() != self.core.lower():
            raise InvalidPreview('This intent requires CYGLD as its output currency.')
        Web3().codec.encode(['uint256'], [int(request['deadline'])])
        if not self.adapter:
            raise QuoteFailure('quote-unavailable')
        budget = current_budget()
        registry = self.engine.registry
        rpc = registry.get_rpc()
        block = await budget.prepare(rpc.block(None))
        assets, weights = await budget.prepare(self.basis(block)) if request['intent'] != 3 else ([], [])
        if request['intent'] == 2 and [row['currency'].lower() for row in request['inputs']] != [asset.lower() for asset in assets]:
            raise InvalidPreview('Basket input currencies must follow Core basket order.')
        if request['intent'] != 3:
            self.seed_routes(request, assets)
        best, failures, observations = None, [], {}
        async def evaluate(share, order, first):
            nonlocal best
            try:
                value = await budget.discovery(self.candidate(request, share, order, block, assets, weights, first=first,
                    core_sale_bounds=core_sale_bounds, observations=observations))
                if best is None or int(value['quotedOutput']) > int(best['quotedOutput']):
                    if not budget.qualified():
                        return
                    best = value
                    if on_update: await on_update({'type': 'qualified', 'value': value})
            except SnapshotChanged:
                raise
            except Exception as error:
                failures.append(error)
        grid = [(share, order) for share in CORE_SHARES for order in
                (('core-first', 'market-first') if 0 < share < 100 else ('core-first',))]
        if request['intent'] >= 2 or core_sale_bounds: grid = [(100, 'core-first')]
        async def discovered():
            try:
                if request['intent'] != 3:
                    await budget.discovery(self.discover(request, assets, block))
                await owned_reads(*(evaluate(share, order, False) for share, order in grid))
            except SnapshotChanged:
                raise
            except Exception as error:
                failures.append(error)
        try:
            await owned_reads(owned_reads(*(evaluate(share, order, True) for share, order in grid)), discovered())
        except SearchStopped:
            pass
        budget.cleanup_done()
        await rpc.assert_canonical(block)
        budget.canonical_done()
        if best is None:
            informative = next((error for error in failures if not isinstance(error, InvalidPreview) and
                not (isinstance(error, QuoteFailure) and error.code == 'quote-no-route')), None)
            raise informative or QuoteFailure('quote-no-route')
        return best


async def handle_universal_quote(request, service):
    try:
        value = UniversalExactInputRequest.model_validate(await request.json()).model_dump()
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid universal exact-input request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    try:
        result = await service.get(value)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except InvalidPreview as error:
        return JSONResponse({'error': str(error)}, status_code=400, headers={'Cache-Control': 'no-store'})
    except Exception as error:
        return JSONResponse(public_quote_error(error), status_code=503, headers={'Cache-Control': 'no-store'})

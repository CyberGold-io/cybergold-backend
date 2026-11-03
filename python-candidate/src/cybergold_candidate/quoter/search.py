"""CyberGold Quoter: whole-plan selection and ordered AMM replay.

The existing execution-response adapter is preserved during the economic/API
boundary migration. No alternative pricing engine or scheduler is introduced.

Every candidate owns its pool-state bank. Quotes model disclosed treasury
retention; they never subtract retained principal from the user's gross spend.
"""
import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
from secrets import randbits

from web3 import Web3

from ..basket_preview import BasketPreviewRpc, InvalidPreview
from .types import EconomicRequest
from ..protocol_config import configured_address
from ..quote_budget import budget_entry, current_budget, SearchStopped, budget_context, QuoteBudget
from ..quote_errors import QuoteFailure, public_quote_error, rpc_failure
from ..recovery_rpc import SnapshotChanged
from ..preview_errors import preview_error
from ..routing_encoding import ZERO, ROUTING_ENCODING, weighted_routes, split_runtime
from ..route_search import WETH
from ..route_work_slots import bootstrap_priority
from ..uniswap_routes import pool_identity, V4_CONNECTOR_KEYS, initial_v3_branches
from ..uniswap_v4 import v4_pool_id, POOL_MANAGER
from ..wallet_balances import TOKENS
from ..uniswap_state import owned_reads
from ..rpc_block_context import LATEST_BLOCK, rpc_block_parameter
from .amm import price_path, PartialPath
from .discovery import paths, route_candidates
from .ranking import prefer_completed
from .contracts import SearchSession
from .exploration import explore
from .funding import measured_funding_proposal, cached_core_funding
from .reuse_routes import neighbor_proposals
from .bootstrap import RouteBootstrap, bootstrap_scope, current_bootstrap
from .amm_adapter import CyberGoldAmmAdapter
from .custom_routes import CustomRoutes
from .provenance import attach_origins, merge_origins
from ..route_observations import RouteObservations, current_route_observations, route_observation_scope
from ..search_observations import search_observation_scope, current_search_observations
from .core_state import CoreQuoteState

PAXG = dict(TOKENS)['paxg']
CORE_SHARES = (0, 25, 50, 75, 100)


async def alongside_bootstrap(ordinary, bootstrap, *, incumbent=None):
    """Optional cached work cannot prolong otherwise-completed discovery.

    Both tasks are owned here. Optional lookup failure does not disprove a
    Helpers result. A complete ordinary result need not wait for a slow cache;
    if nothing priced, an offered seed may still be the first useful result.
    """
    tasks = [asyncio.create_task(ordinary), asyncio.create_task(bootstrap)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if tasks[1] in done:
            await asyncio.gather(tasks[1], return_exceptions=True)
        await tasks[0]
        if incumbent is not None and incumbent() is None:
            await tasks[1]
        if tasks[1].done():
            await asyncio.gather(tasks[1], return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency,
            'routes': []}


class Quoter:
    def __init__(self, settings, engine, *, preview=None, basis_reader=None, now=None,
                 exploration_seed=None, route_provider_factory=None, plan_simulator=None,
                 core_state_cache=None):
        self.settings, self.engine = settings, engine
        self.exploration_seed = exploration_seed
        self.route_provider_factory = route_provider_factory
        self.adapter = configured_address(settings, 'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS')
        self.helpers = configured_address(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS')
        self.core = configured_address(settings, 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS')
        self.amm = CyberGoldAmmAdapter(engine, self.core)
        self.preview = preview
        self.basis_reader = basis_reader
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.core_state_cache = core_state_cache or CoreQuoteState(settings, engine.registry)
        from .plan_simulation import HelpersPlanSimulation
        self.plan_simulator = plan_simulator or HelpersPlanSimulation(settings, engine.registry,
            helpers=self.helpers, adapter=self.adapter, core=self.core, now=self.now,
            semaphore=engine.semaphore if plan_simulator is None else None)

    async def basis(self, block):
        if self.basis_reader:
            return await self.basis_reader(block)
        state = await self.core_state(block)
        return list(state['assets']), list(map(int, state['weights']))

    async def core_state(self, block=None):
        return await self.core_state_cache.get()

    async def core_outputs(self, block=None):
        return await self.core_state_cache.outputs()

    async def start(self):
        await self.core_state_cache.start()

    async def close(self):
        await self.core_state_cache.close()

    async def core_preview(self, mode, value, block):
        observations = current_search_observations()
        if observations is not None:
            identity = ('core-preview', self.core.lower(), self.helpers.lower(), mode,
                        json.dumps(value, sort_keys=True), json.dumps(block, sort_keys=True))
            return await observations.read(identity, lambda: self._core_preview(mode, value, block))
        return await self._core_preview(mode, value, block)

    async def _core_preview(self, mode, value, block):
        if self.preview:
            return await self.preview(mode, value, block)
        if mode == 'issue-exact-in':
            rpc = self.engine.registry.get_rpc()
            data = Web3.keccak(text='previewIssueFromBasketExactIn(uint256[])')[:4] + rpc.w3.codec.encode(
                ['uint256[]'], [list(map(int, value['maximumAmountsIn']))])
            response = await rpc.w3.provider.make_request('eth_call', [
                {'from': self.helpers, 'to': self.core, 'data': Web3.to_hex(data)},
                rpc_block_parameter(block)])
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
        bootstrap = current_bootstrap()
        if bootstrap is not None:
            bootstrap.watch_catalog_load()
        payment = request['inputs'][0]['currency'] if request['intent'] == 0 else request['outputCurrency']
        if payment.lower() == ZERO:
            payment = WETH
        await owned_reads(*(self.engine.connector_inventory(payment, asset, block)
            for asset in dict.fromkeys([payment, PAXG, *assets]) if asset.lower() != payment.lower()))
        # Native V4 keys have no pair factory. The snapshot producer observes
        # these ordinary hookless candidates, including on a cold inventory.
        currencies = sorted({ZERO, WETH.lower(), payment.lower(), PAXG.lower(),
                             *(asset.lower() for asset in assets)})
        tokens = {currency: deepcopy(getattr(registry, 'metadata', {}).get(currency) or
            {**registry.token(currency, 18), 'decimalsKnown': currency == ZERO})
            for currency in currencies}
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
        return await price_path(self.engine, route, amount, block, bank, canonical)

    async def conversion(self, source, target, amount, block, bank, canonical, **options):
        return await self.amm.convert(source, target, amount, block, bank, canonical,
                                      price_path=self.price_path, **options)

    async def candidate(self, request, share, order, block, assets, weights, *, first=False,
                        observations=None, selected=None, selection=True):
        from .evaluate import evaluate_candidate
        from .dormant_routes import with_dormant_routes
        if selected is not None:
            return await self.plan_simulator(request, selected)
        value = await evaluate_candidate(self, request, share, order, block, assets, weights,
                                         first=first, observations=observations, selected=selected, selection=selection)
        value = with_dormant_routes(value, getattr(self.engine.registry, 'seed', None))
        # SDK quantities choose promising paths/allocations. Only execution of
        # the complete plan supplies the published economic result.
        return await self.plan_simulator(request, value['plan'], candidate=value)

    async def exploration_block(self):
        """Local SDK metadata only; exploration needs no header acquisition."""
        return deepcopy(LATEST_BLOCK)

    @budget_entry
    async def get(self, request, on_update=None, *, core_only=False, seed=None, neighbors=None,
                  seed_lookup=None):
        observations = RouteObservations()
        with route_observation_scope(observations):
            try:
                result = await self._produce(request, on_update, core_only=core_only,
                                             seed=seed, neighbors=neighbors, seed_lookup=seed_lookup)
            except (Exception, asyncio.CancelledError) as error:
                error.quoter_metrics = {**self.producer_metrics(current_budget()),
                    **getattr(error, 'quoter_metrics', {}),
                    'routeDiscovery': {**observations.discovery, 'physicalRpc': observations.metrics,
                                       'apiRequests': observations.api_metrics}}
                raise
        result.setdefault('metrics', {}).setdefault('routeDiscovery', {}).update(
            physicalRpc=observations.metrics, apiRequests=observations.api_metrics)
        return attach_origins(result)

    async def _produce(self, request, on_update=None, *, core_only=False, seed=None, neighbors=None,
                       seed_lookup=None):
        budget = current_budget()
        # The SQL feed starts alongside head/basis acquisition. Its caller
        # captures the existing scope; this task never owns a second search.
        async def lookup_neighbors():
            try:
                return await neighbors()
            except Exception:
                return {}
        neighbor_task = (asyncio.create_task(lookup_neighbors())
                         if neighbors is not None and not core_only else None)
        async def lookup_seed():
            try:
                return await seed_lookup()
            except Exception:
                return None
        seed_task = asyncio.create_task(lookup_seed()) if seed_lookup is not None else None
        try:
            from .plan_simulation import simulation_scope
            async with simulation_scope(), search_observation_scope():
                result = await budget.produce(self._get(request, on_update, core_only=core_only,
                                                       seed=seed, neighbor_task=neighbor_task,
                                                       seed_task=seed_task))
        except Exception as error:
            # Private diagnostic evidence preserves the public error contract.
            # In particular, exhaustion can still return quote-no-route while
            # its actual stopping reason is recorded as timeout.
            error.quoter_metrics = self.producer_metrics(budget)
            raise
        finally:
            lookups = [task for task in (neighbor_task, seed_task) if task is not None]
            for task in lookups:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*lookups, return_exceptions=True)
        result['metrics'] = {**(result.get('metrics') or {}), **self.producer_metrics(budget)}
        return result

    @staticmethod
    def producer_metrics(budget):
        times = budget.timings()
        search_ms = min((value for value in (times['selectionMs'], times['drainedMs'])
                         if value is not None), default=None)
        values = {**budget.metrics(), 'totalMs': times['terminalMs'],
                  'timeToFirstWholePlanMs': times['firstQualifiedMs'],
                  'searchMs': search_ms, 'selectionReason': times['selectionReason']}
        if search_ms is not None and times['terminalMs'] is not None:
            values['finalizationMs'] = round(times['terminalMs'] - search_ms, 3)
        return values

    def normalise_request(self, request):
        request = EconomicRequest.model_validate(request).model_dump()
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
        if not self.adapter:
            raise QuoteFailure('quote-unavailable')
        return request

    async def direct_basket_funding(self, request, block):
        """Offer proportional/capacity funding from cached construction facts.

        This is only a nomination. It never reads a supply/amount preview before
        trying the ordinary full plan; Helpers measures any resulting body.
        """
        from ..basket_arithmetic import ceil_div
        state = deepcopy(self.core_state_cache.value)
        if request['intent'] == 3:
            supply = state.get('supply')
            if supply is None:
                return None
            amount = min(int(request['inputs'][0]['amount']), int(supply))
            return ([{**request['inputs'][0], 'amount': str(amount)}]
                    if amount and amount < int(request['inputs'][0]['amount']) else None)
        if request['intent'] != 2:
            return None
        units, weights = state.get('conversions'), state.get('weights')
        if not units or not weights:
            return None
        budgets = [int(row['amount']) for row in request['inputs']]
        try:
            gross = min((budget * int(unit) // 10**18) * 1_000_000 // int(weight)
                        for budget, unit, weight in zip(budgets, units, weights, strict=True) if int(weight))
            if all(name in state for name in ('supply', 'maxSupply', 'effectiveCap')):
                gross = min(gross, max(0, min(int(state['maxSupply']), int(state['effectiveCap']))-int(state['supply'])))
            amounts = [ceil_div(ceil_div(gross * int(weight), 1_000_000) * 10**18, int(unit)) if int(weight) else 0
                       for unit, weight in zip(units, weights, strict=True)]
        except (ValueError, ZeroDivisionError):
            return None
        if not any(amounts) or amounts == budgets:
            return None
        return [{**row, 'amount': str(amount)} for row, amount in zip(request['inputs'], amounts, strict=True)]

    async def _get(self, request, on_update=None, *, core_only=False, seed=None, neighbor_task=None,
                   seed_task=None):
        request = self.normalise_request(request)
        budget = current_budget()
        registry = self.engine.registry
        rpc = registry.get_rpc()
        block = await self.exploration_block()
        assets = [row['currency'] for row in request['inputs']] if request['intent'] == 2 else []
        weights = []
        route_bootstrap = None
        direct_funding, default_funding = None, None
        if request['intent'] in (0, 1):
            self.seed_routes(request, [])
        async def prepare_basis():
            nonlocal assets, weights, block, direct_funding, default_funding
            if request['intent'] >= 2:
                return
            if request['intent'] == 1:
                # Redemption templates need output identities, not allocation
                # weights. Start catalog work as soon as the asset list exists.
                if self.basis_reader is not None:
                    assets, _ = await budget.prepare(self.basis(block))
                else:
                    assets = await budget.prepare(self.core_state_cache.field('assets'))
            else:
                assets, weights = await budget.prepare(self.basis(block))
            self.seed_routes(request, assets)
            if route_bootstrap is not None:
                route_bootstrap.refresh_catalog()
        preparation = asyncio.create_task(prepare_basis())
        async def prepared():
            if preparation is not None:
                try:
                    # Many candidate/feed owners await this one preparation.
                    # The producer below retains ownership through cleanup.
                    await asyncio.shield(preparation)
                except SnapshotChanged as error:
                    failures.append(error)
                    return False
                except Exception as error:
                    failures.append(error)
                    return False
            return True
        best, failures, observations = None, [], {}
        session = SearchSession(self.exploration_seed if self.exploration_seed is not None else randbits(64))
        reconstructions = set()
        neighbor_metrics = {'starts': 0, 'completed': 0, 'sources': []}
        async def evaluate(share, order, first, selected=None, funding=None, phase=None, partial=False,
                           failure_sink=None):
            nonlocal best
            errors = failures if failure_sink is None else failure_sink
            try:
                needs_core = request['intent'] == 0 and share != 0
                if selected is None and needs_core and not await prepared():
                    return
                funding = default_funding if funding is None else funding
                funded_request = {**request, 'inputs': deepcopy(funding)} if funding is not None else request
                funded_request, selected = cached_core_funding(
                    funded_request, self.core_state_cache.value, selected)
                try:
                    async def produce_candidate():
                        return await self.candidate(funded_request, share, order, block, assets, weights,
                            first=first, observations=observations, selected=selected)
                    shared = current_search_observations()
                    if selected is None and shared is not None:
                        identity = ('complete-candidate', share, order, first,
                            json.dumps(funded_request, sort_keys=True), route_bootstrap.revision if route_bootstrap else 0)
                        pending = shared.read(identity, produce_candidate)
                    else:
                        pending = produce_candidate()
                    value = await budget.discovery(pending)
                except SnapshotChanged as error:
                    # The SDK only constructs proposals. A failed exploratory
                    # snapshot says nothing about an independent Helpers quote.
                    errors.append(error)
                    return
                if selected is not None:
                    # A legacy seed/neighbor is a newly offered quote here,
                    # unlike TransactionPreparation's already-accepted plan.
                    from .dormant_routes import with_dormant_routes
                    value = with_dormant_routes(value, getattr(registry, 'seed', None))
                value['request'] = deepcopy(request)
                attach_origins(value)
                merge_origins(best, value)
                if prefer_completed(value, best, scalar=request['intent'] in (0, 1), basket=request['intent'] >= 2):
                    if not budget.qualified():
                        return
                    value['searchCoverage']['selectedPhase'] = phase or ('saved-plan' if selected is not None
                        else 'capacity-limited' if funding is not None and funding != request['inputs']
                        else 'first-result' if first else 'detailed')
                    measured = current_route_observations()
                    discovery_metrics = route_bootstrap.metrics if route_bootstrap is not None else {}
                    if measured is not None:
                        discovery_metrics.update(physicalRpc=measured.metrics, apiRequests=measured.api_metrics)
                    value.setdefault('metrics', {})['routeDiscovery'] = discovery_metrics
                    best = value
                    if on_update: await on_update({'type': 'qualified', 'value': value})
                # A lower-funding body is a new proposal. Price it alongside
                # normal search, rather than adding a network tail afterward.
                proposal = measured_funding_proposal(value, registry.chain) if not core_only else None
                if proposal is not None:
                    reduced_request, plan = proposal
                    async def reprice():
                        try:
                            await evaluate(share, order, False, selected=plan,
                                funding=reduced_request['inputs'], phase='measured-funding')
                        except SearchStopped:
                            pass
                        except Exception as error:
                            failures.append(error)
                    task = asyncio.create_task(reprice())
                    reconstructions.add(task)
                    task.add_done_callback(reconstructions.discard)
                return value
            except SnapshotChanged:
                raise
            except PartialPath as error:
                if partial:
                    raise
                errors.append(error)
            except Exception as error:
                if partial and isinstance(error, QuoteFailure) and error.code == 'quote-contract-reverted':
                    # An optional failed whole path can ask the SDK to explore
                    # a different funding/prefix shape; no SDK reprice is
                    # required for a successful Helpers observation.
                    raise
                errors.append(error)
        grid = [(share, order) for share in CORE_SHARES for order in
                (('core-first', 'market-first') if 0 < share < 100 else ('core-first',))]
        if request['intent'] >= 2 or core_only: grid = [(100, 'core-first')]
        async def discovered():
            async def side(chosen_assets):
                try:
                    if request['intent'] != 3:
                        await budget.discovery(self.discover(request, chosen_assets, block))
                        route_bootstrap.refresh_catalog()
                    await owned_reads(*(evaluate(share, order, False) for share, order in grid))
                except SearchStopped:
                    pass
                except Exception as error:
                    failures.append(error)
            async def core_side():
                if await prepared():
                    await side(assets)
            try:
                if request['intent'] in (0, 1) and not core_only:
                    await owned_reads(side([]), core_side())
                else:
                    await core_side()
            except Exception as error:
                failures.append(error)
            finally:
                session.discovery_done.set()
        try:
            async def seeded_body():
                offered = (seed if seed is not None else
                    await budget.discovery(asyncio.shield(seed_task)) if seed_task is not None else None)
                if offered is not None:
                    funding = offered['inputs']
                    maxima = direct_funding if direct_funding is not None else request['inputs']
                    # A saved plan remains an optional candidate under the
                    # requested budget, including for direct diagnostic callers.
                    if len(funding) == len(maxima) and all(
                            row['currency'].lower() == maximum['currency'].lower()
                            and int(row['amount']) <= int(maximum['amount'])
                            for row, maximum in zip(funding, maxima, strict=True)):
                        async def expanded_seed():
                            try:
                                proposal = neighbor_proposals(offered, int(maxima[0]['amount']), assets)[-1]
                            except Exception as error:
                                failures.append(error)
                                return
                            await evaluate(100, 'core-first', False, selected=proposal['plan'],
                                funding=proposal['inputs'], phase='saved-plan-budget')
                        retained = evaluate(100, 'core-first', False, selected=offered['plan'], funding=funding)
                        if request['intent'] in (0, 1) and int(funding[0]['amount']) < int(maxima[0]['amount']):
                            # The exact request key can retain a smaller-funded
                            # winner. Start its full-budget topology replay now,
                            # independently of the already-fitting fallback.
                            await owned_reads(expanded_seed(), retained)
                        else:
                            await retained
            async def seeded():
                try:
                    await seeded_body()
                except SnapshotChanged:
                    raise
                except Exception as error:
                    failures.append(error)
                finally:
                    session.seed_done.set()
            async def limited():
                if request['intent'] not in (2, 3):
                    return
                try:
                    if not await prepared():
                        return
                    funding = await self.direct_basket_funding(request, block)
                    if funding is not None:
                        await evaluate(100, 'core-first', True, funding=funding, phase='capacity-limited')
                except Exception as error:
                    failures.append(error)
            async def nearby():
                if neighbor_task is None or request['intent'] not in (0, 1):
                    return
                selected_neighbors = await budget.discovery(asyncio.shield(neighbor_task))
                async def replay_neighbor(side):
                    source = None
                    settled = True
                    try:
                        row = selected_neighbors.get(side)
                        if not row:
                            return
                        source = {'side': side, 'identity': row.get('identity'), 'attempts': []}
                        basis = row['quote'].get('reuseSample', {}).get('basis')
                        if basis is not None:
                            source['referenceBasis'] = basis
                        neighbor_metrics['sources'].append(source)
                        proposals = neighbor_proposals(row['quote'], int(request['inputs'][0]['amount']), assets)
                        async def replay_proposal(proposal):
                            attempt = {'funding': proposal['inputs'][0]['amount']}
                            source['attempts'].append(attempt)
                            neighbor_metrics['starts'] += 1
                            started = asyncio.get_running_loop().time()
                            try:
                                errors = []
                                with bootstrap_priority():
                                    value = await evaluate(100, 'core-first', False,
                                        selected=proposal['plan'], funding=proposal['inputs'], phase='nearby-'+side,
                                        failure_sink=errors)
                                attempt['completed'] = value is not None
                                neighbor_metrics['completed'] += value is not None
                                if errors:
                                    attempt['failureCode'] = public_quote_error(errors[-1])['code']
                            finally:
                                attempt['elapsedMs'] = round((asyncio.get_running_loop().time()-started)*1000, 3)
                        # The fitting replay must not hold the edited budget
                        # behind a slow call. Both complete plans use ordinary
                        # independent Helpers pricing and the same owner clock.
                        await owned_reads(*(replay_proposal(proposal) for proposal in reversed(proposals)))
                    except asyncio.CancelledError:
                        settled = False
                        raise
                    except Exception as error:
                        # Optional legacy/cache shape failures must not replace
                        # the ordinary terminal quote-no-route/error taxonomy.
                        if source is not None:
                            source['failureCode'] = public_quote_error(error)['code']
                    finally:
                        # The App may retain a validated candidate behind its
                        # displayed upper arithmetic hint. Release that wait on
                        # success, absence or ordinary replay failure.
                        # Only economic streams supply this neighbor work.
                        if settled and side == 'upper' and on_update:
                            await on_update({'type': 'upper-replay-settled'})
                # Each neighbor proceeds independently. Neither awaits the
                # other's acquisition, nor changes E17's exact-seed event.
                await owned_reads(replay_neighbor('upper'), replay_neighbor('lower'))
            async def ordinary_body():
                ordinary = owned_reads(explore(self, request, block, session, evaluate, lambda: best,
                    observations=observations, seeded=seed is not None, core_only=core_only), limited(),
                    owned_reads(*(evaluate(share, order, True) for share, order in grid)), discovered())
                if neighbor_task is None:
                    await ordinary
                else:
                    await alongside_bootstrap(ordinary, nearby(), incumbent=lambda: best)

            async def ordinary_search():
                # Saved plans, Market construction, and Core preparation have
                # separate inputs and start independently.
                await alongside_bootstrap(ordinary_body(), seeded(), incumbent=lambda: best)

            async def provider_arrival():
                # Late AMM nominations receive the same optional family and
                # partial-prefix work as the initial/catalog snapshots. Reuse
                # the existing successful observation bank and selection clock;
                # ordinary whole-plan improvements publish independently.
                await owned_reads(explore(self, request, block, session, evaluate, lambda: best,
                    observations=observations, seeded=seed is not None, core_only=core_only),
                    owned_reads(*(evaluate(share, order, False, phase='provider-arrival')
                                  for share, order in grid)))

            async def provider_quick():
                # Ready nominations can qualify while an older detailed pass
                # still owns slow state reads. These remain complete economic
                # candidates under the same comparator and selection budget.
                await owned_reads(*(evaluate(share, order, True, phase='provider-arrival-quick')
                                    for share, order in grid))

            tools = (self.route_provider_factory() if self.route_provider_factory is not None
                     else [CustomRoutes(registry)])
            route_bootstrap = RouteBootstrap(tools, catalog=registry, nomination_only=True)
            with bootstrap_scope(route_bootstrap):
                await route_bootstrap.run(ordinary_search(), provider_arrival, quick=provider_quick)
                while reconstructions:
                    await asyncio.gather(*tuple(reconstructions), return_exceptions=True)
        except SearchStopped:
            pass
        finally:
            for task in tuple(reconstructions):
                task.cancel()
            await asyncio.gather(*tuple(reconstructions), return_exceptions=True)
            preparation_error = None
            if preparation is not None:
                if not preparation.done():
                    preparation.cancel()
                outcome, = await asyncio.gather(preparation, return_exceptions=True)
                if isinstance(outcome, SnapshotChanged):
                    preparation_error = outcome
                elif isinstance(outcome, Exception):
                    failures.append(outcome)
            measured = current_route_observations()
            if measured is not None and route_bootstrap is not None:
                # The session has drained before exposing its terminal outcome,
                # including no-route, context disproof and caller cancellation.
                measured.discovery = route_bootstrap.metrics
            if preparation_error is not None:
                failures.append(preparation_error)
        budget.cleanup_done()
        if best is not None and not budget.stop.is_set():
            budget.finish_selection('complete')
        if best is not None:
            best['metrics'] = {**(best.get('metrics') or {}), 'optionalSearch': {
                'randomSeed': str(session.random_seed) if seed is not None else None,
                'starts': session.starts, 'pruned': session.pruned, 'repairs': session.repairs}}
            if neighbor_task is not None:
                best['metrics']['nearbySearch'] = neighbor_metrics
            if route_bootstrap is not None:
                best['metrics']['routeDiscovery'] = route_bootstrap.metrics
                best['metrics']['routeDiscovery']['capabilities'] = {'uniroute-local': 'published-route-finder-and-quote-split-components', 'uniroute-api': 'trading-api-observed-engine'}
        if best is None:
            informative = next((error for error in failures if not isinstance(error, InvalidPreview) and
                not (isinstance(error, QuoteFailure) and error.code == 'quote-no-route')), None)
            raise informative or QuoteFailure('quote-no-route')
        return best

    quote = get

    @budget_entry
    async def evaluate_selected(self, request, selected, *, recipient=None, minimum=1, accepted_core=None):
        """Prepare through one fresh latest-state execution of the accepted plan."""
        request = self.normalise_request(request)
        from .types import EconomicPlan
        selected = EconomicPlan.model_validate(selected).model_dump()
        budget = current_budget()
        async def replay():
            value = await budget.prepare(self.plan_simulator(request, selected, pricing=False,
                recipient=recipient, minimum=minimum, accepted_core=accepted_core))
            budget.cleanup_done()
            return attach_origins(value)
        return await budget.produce(replay())

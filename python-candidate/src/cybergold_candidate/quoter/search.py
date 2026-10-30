"""CyberGold Quoter: whole-plan selection and ordered AMM replay.

The existing execution-response adapter is preserved during the economic/API
boundary migration. No alternative pricing engine or scheduler is introduced.

Every candidate owns its pool-state bank. Quotes model disclosed treasury
retention; they never subtract retained principal from the user's gross spend.
"""
import asyncio
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
from ..uniswap_routes import pool_identity, V4_CONNECTOR_KEYS, initial_v3_branches
from ..uniswap_v4 import v4_pool_id, POOL_MANAGER
from ..wallet_balances import TOKENS
from ..uniswap_state import owned_reads
from .amm import price_path, PartialPath
from .discovery import paths, route_candidates
from .ranking import prefer_completed
from .contracts import SearchSession
from .exploration import explore
from .funding import reconstruct

PAXG = dict(TOKENS)['paxg']
CORE_SHARES = (0, 25, 50, 75, 100)


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency,
            'routes': []}


class Quoter:
    def __init__(self, settings, engine, *, preview=None, basis_reader=None, now=None,
                 exploration_seed=None, optional_limit=16):
        self.settings, self.engine = settings, engine
        self.exploration_seed, self.optional_limit = exploration_seed, optional_limit
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
        return await price_path(self.engine, route, amount, block, bank, canonical)

    async def conversion(self, source, target, amount, block, bank, canonical, *, market=False,
                         first=False, branch=0, stage=0, capture=None):
        if not amount or source.lower() == target.lower():
            if capture is not None:
                capture.update(inputCurrency=source, outputCurrency=target, branches=[],
                               _observation={'inputCurrency': source, 'fundedInput': str(amount),
                                             'consumedInput': str(amount), 'outputCurrency': target, 'output': str(amount)})
            return identity_template(source), amount, []
        registry = self.engine.registry
        selected = paths(list(registry.inventory.values()), source, target)
        if market:
            anchor = pool_identity(registry.seed)
            selected = [route for route in selected if pool_identity(
                next(hop for hop in (route if source.lower() == self.core.lower() else reversed(route))
                     if 'pool' in hop)['pool']) == anchor]
        if first:
            # Keep the V3 seed ahead of newly discovered V2 and noncanonical V4
            # paths, including after their addresses become known. A thin V2
            # acquisition must not displace the prompt Core candidate. Refinement
            # still compares every selected protocol/path and split allocation.
            canonical_edge = pool_identity(registry.seed)
            selected.sort(key=lambda route: (sum(hop['pool']['protocol'] != 'v3' and
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
            output, consumed, retained = 0, 0, []
            try:
                for row in normalized:
                    funded = int(row['amountIn'])
                    used, received = await self.price_path(row['hops'], funded, block, trial, canonical)
                    output += received
                    consumed += used
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
                            'routes': routes}
                best = output, template, retained, trial, deepcopy(normalized), consumed
                if first and output > 0:
                    break
            await asyncio.sleep(0)
        if best is None:
            raise rpc_error or QuoteFailure('quote-no-route')
        if capture is not None:
            capture.update(inputCurrency=source, outputCurrency=target, branches=[{'hops': row['hops']} for row in best[4]], template=deepcopy(best[1]),
                           _observation={'inputCurrency': best[1]['inputCurrency'], 'fundedInput': str(amount),
                                         'consumedInput': str(best[5]), 'outputCurrency': target, 'output': str(best[0])})
        bank.clear()
        bank.update(best[3])
        return best[1], best[0], best[2]

    async def candidate(self, request, share, order, block, assets, weights, *, first=False,
                        observations=None, selected=None, selection=True):
        from .evaluate import evaluate_candidate
        return await evaluate_candidate(self, request, share, order, block, assets, weights,
                                        first=first, observations=observations, selected=selected, selection=selection)

    @budget_entry
    async def get(self, request, on_update=None, *, core_only=False, seed=None):
        budget = current_budget()
        try:
            result = await budget.produce(self._get(request, on_update, core_only=core_only, seed=seed))
        except Exception as error:
            # Private diagnostic evidence preserves the public error contract.
            # In particular, exhaustion can still return quote-no-route while
            # its actual stopping reason is recorded as timeout.
            error.quoter_metrics = self.producer_metrics(budget)
            raise
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
        """Construct a smaller direct Core candidate, leaving unused budgets unfunded.

        Core's issuance preview already solves its supply cap and returns the
        canonical basket costs, as used by basket MAX. Redemption funding cannot
        exceed the existing CYGLD supply; Helpers/Core still preview that actual
        funding and apply both fee layers before it becomes a completed quote.
        """
        if request['intent'] == 2:
            result = await self.core_preview('issue-exact-in', {
                'maximumAmountsIn': [row['amount'] for row in request['inputs']]}, block)
            amounts = list(map(int, result['amountsInExact']))
        elif request['intent'] == 3:
            supply, = await self.engine.registry.get_rpc().read_function(
                self.core, 'totalSupply()', [], [], ['uint256'], block)
            return [{'currency': request['inputs'][0]['currency'],
                     'amount': str(min(int(request['inputs'][0]['amount']), int(supply)))}]
        else:
            return None
        if not any(amounts) or amounts == [int(row['amount']) for row in request['inputs']]:
            return None
        return [{'currency': row['currency'], 'amount': str(amount)}
                for row, amount in zip(request['inputs'], amounts, strict=True)]

    async def _get(self, request, on_update=None, *, core_only=False, seed=None):
        request = self.normalise_request(request)
        budget = current_budget()
        registry = self.engine.registry
        rpc = registry.get_rpc()
        block = await budget.prepare(rpc.block(None))
        assets, weights = await budget.prepare(self.basis(block)) if request['intent'] != 3 else ([], [])
        if request['intent'] == 2 and [row['currency'].lower() for row in request['inputs']] != [asset.lower() for asset in assets]:
            raise InvalidPreview('Basket input currencies must follow Core basket order.')
        if request['intent'] != 3:
            self.seed_routes(request, assets)
        direct_funding = (await budget.prepare(self.direct_basket_funding(request, block))
                          if request['intent'] == 3 else None)
        # At zero supply the original request still receives Core's ordinary
        # identified rejection; zero funding must not become a successful quote.
        default_funding = direct_funding if direct_funding and any(int(row['amount']) for row in direct_funding) else None
        best, failures, observations = None, [], {}
        session = SearchSession(self.optional_limit,
            self.exploration_seed if self.exploration_seed is not None else randbits(64))
        async def evaluate(share, order, first, selected=None, funding=None, phase=None, partial=False):
            nonlocal best
            try:
                funding = default_funding if funding is None else funding
                funded_request = {**request, 'inputs': deepcopy(funding)} if funding is not None else request
                value = await budget.discovery(self.candidate(funded_request, share, order, block, assets, weights, first=first,
                    observations=observations, selected=selected))
                value['request'] = deepcopy(request)
                if prefer_completed(value, best, scalar=request['intent'] in (0, 1), basket=request['intent'] >= 2):
                    if not budget.qualified():
                        return
                    value['searchCoverage']['selectedPhase'] = phase or ('saved-plan' if selected is not None
                        else 'capacity-limited' if funding is not None and funding != request['inputs']
                        else 'first-result' if first else 'detailed')
                    best = value
                    if on_update: await on_update({'type': 'qualified', 'value': value})
            except SnapshotChanged:
                raise
            except PartialPath as error:
                if partial:
                    raise
                failures.append(error)
            except Exception as error:
                failures.append(error)
        grid = [(share, order) for share in CORE_SHARES for order in
                (('core-first', 'market-first') if 0 < share < 100 else ('core-first',))]
        if request['intent'] >= 2 or core_only: grid = [(100, 'core-first')]
        async def discovered():
            try:
                if request['intent'] != 3:
                    await budget.discovery(self.discover(request, assets, block))
                session.discovery_done.set()
                await owned_reads(*(evaluate(share, order, False) for share, order in grid))
            except SnapshotChanged:
                raise
            except Exception as error:
                failures.append(error)
            finally:
                session.discovery_done.set()
        try:
            async def seeded_body():
                if seed is not None:
                    funding = seed['inputs']
                    maxima = direct_funding if direct_funding is not None else request['inputs']
                    # A saved plan remains an optional candidate under the
                    # requested budget, including for direct diagnostic callers.
                    if len(funding) == len(maxima) and all(
                            row['currency'].lower() == maximum['currency'].lower()
                            and int(row['amount']) <= int(maximum['amount'])
                            for row, maximum in zip(funding, maxima, strict=True)):
                        await evaluate(100, 'core-first', False, selected=seed['plan'], funding=funding)
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
                if request['intent'] != 2:
                    return
                try:
                    funding = await budget.discovery(self.direct_basket_funding(request, block))
                    if funding is not None:
                        await evaluate(100, 'core-first', True, funding=funding, phase='capacity-limited')
                except SnapshotChanged:
                    raise
                except Exception as error:
                    failures.append(error)
            await owned_reads(explore(self, request, block, session, evaluate, lambda: best,
                observations=observations, seeded=seed is not None, core_only=core_only), seeded(), limited(),
                owned_reads(*(evaluate(share, order, True) for share, order in grid)), discovered())
        except SearchStopped:
            pass
        budget.cleanup_done()
        if best is not None and not budget.stop.is_set():
            budget.finish_selection('complete')
        if best is not None and not core_only:
            try:
                best = await reconstruct(self, best, block, assets, weights, observations)
            except SnapshotChanged:
                raise
            except Exception:
                pass  # Keep the ordinary winner if optional reconstruction fails.
        if best is not None:
            best['metrics'] = {**(best.get('metrics') or {}), 'optionalSearch': {
                'randomSeed': str(session.random_seed) if seed is not None else None,
                'starts': session.starts, 'pruned': session.pruned, 'repairs': session.repairs}}
        await rpc.assert_canonical(block)
        budget.canonical_done()
        if best is None:
            informative = next((error for error in failures if not isinstance(error, InvalidPreview) and
                not (isinstance(error, QuoteFailure) and error.code == 'quote-no-route')), None)
            raise informative or QuoteFailure('quote-no-route')
        return best

    quote = get

    @budget_entry
    async def evaluate_selected(self, request, selected):
        """Replay selected routes at current state without route discovery."""
        request = self.normalise_request(request)
        from .types import EconomicPlan
        selected = EconomicPlan.model_validate(selected).model_dump()
        budget = current_budget()
        async def replay():
            rpc = self.engine.registry.get_rpc()
            block = await budget.prepare(rpc.block(None))
            assets, weights = await budget.prepare(self.basis(block)) if request['intent'] != 3 else ([], [])
            if request['intent'] == 2 and [row['currency'].lower() for row in request['inputs']] != [asset.lower() for asset in assets]:
                raise InvalidPreview('Basket input currencies must follow Core basket order.')
            value = await budget.prepare(self.candidate(request, 100, 'core-first', block, assets, weights,
                                                       selected=selected))
            budget.cleanup_done()
            await rpc.assert_canonical(block)
            budget.canonical_done()
            return value
        return await budget.produce(replay())

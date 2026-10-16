"""Shared route discovery, pricing and ordered execution-state replay.

Core, Market and direct Uniswap consumers share one runtime instance. Protocol
pricing methods are implementation details of a canonical forward route.
"""
import asyncio
from .route_work_slots import engine_work
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import json

from .basket_preview import InvalidPreview
from .quote_errors import public_quote_error
from .quote_models import PoolBaseline
from .recovery_rpc import SnapshotChanged
from .rpc_diagnostics import route_count
from .route_scheduler import schedule_routes, raise_snapshot_disproof
from .sdk_worker import SdkWorker, MissingPoolState
from .uniswap_routes import (candidate_branches, supported_route, resize_branches,
    pool_identity, route_identity, v3_branches, initial_v3_branches, LEGACY_V3_ADAPTERS)
from .uniswap_state import ZERO
from .wallet_balances import TOKENS



class RouteQuoteEngine:
    def __init__(self, settings, registry, sdk=None):
        self.settings, self.registry = settings, registry
        self.sdk = sdk or SdkWorker()
        self.shared = registry.pending.__class__()
        self.semaphore = asyncio.Semaphore(8)

    async def close(self):
        await self.shared.close()
        await self.sdk.close()

    def enrich_branches(self, branches):
        """Attach observed metadata without changing execution identity."""
        registry = getattr(self, 'registry', None)
        known = {pool_identity(pool): pool for pool in getattr(registry, 'inventory', {}).values()}
        result = deepcopy(branches)
        for branch in result:
            for hop in branch['hops']:
                pool = known.get(pool_identity(hop['pool']))
                if pool is not None:
                    hop['pool'] = deepcopy(pool)
                elif hop['pool']['protocol'] == 'v3':
                    # Absent inventory still has one factory execution identity;
                    # optional caller/catalog IDs cannot duplicate SDK state.
                    hop['pool']['id'] = ':'.join(map(str, pool_identity(hop['pool'])))
        return result

    def baseline(self, state, zero_for_one):
        if state['protocol'] == 'v2':
            a, b = int(state['reserve0']), int(state['reserve1'])
            source, target = (a, b) if zero_for_one else (b, a)
            return PoolBaseline(Fraction(target, source), Fraction(997, 1000), Fraction(1, source))
        fee = int(state['feePips'])
        if state['protocol'] == 'v4':
            packed = int(state.get('protocolFee', 0))
            protocol = packed & 0xfff if zero_for_one else packed >> 12
            lp = int(state.get('lpFee', fee))
            fee = protocol+lp-protocol*lp//1_000_000
        return PoolBaseline.v3(int(state['sqrtRatioX96']), int(state['liquidity']), fee, zero_for_one)

    async def route_baseline(self, plan, block):
        """Indicative marginal/impact metadata; exact swap arithmetic is SDK-owned."""
        plan = {**plan, 'branches': RouteQuoteEngine.enrich_branches(self, plan['branches'])}
        branches = []
        total = sum(int(branch['amountIn']) for branch in plan['branches'])
        for branch in plan['branches']:
            rate, retention, impact = Fraction(1), Fraction(1), Fraction(0)
            for hop in branch['hops']:
                state = await self.registry.snapshot(hop['pool'], block)
                baseline = self.baseline(state, hop['zeroForOne'])
                if baseline.local_impact is None:
                    raise ValueError('Indicative pool impact unavailable')
                impact += baseline.local_impact*baseline.fee_retention*rate*retention
                rate *= baseline.exchange
                retention *= baseline.fee_retention
            weight = Fraction(int(branch['amountIn']), total) if total else Fraction(1, len(plan['branches']))
            branches.append((weight, PoolBaseline(rate, retention, impact/retention)))
        exchange = sum(weight*baseline.exchange for weight, baseline in branches)
        effective_rate = sum(weight*baseline.exchange*baseline.fee_retention for weight, baseline in branches)
        retention = effective_rate/exchange
        effective_impact = sum(weight**2*baseline.exchange*baseline.fee_retention**2*baseline.local_impact
            for weight, baseline in branches)/effective_rate
        return PoolBaseline(exchange, retention, effective_impact/retention)

    async def connector_inventory(self, token_in, token_out, block):
        """Preserve existing direct/via-WETH V3 fee coverage; add V2 connectors."""
        rpc = self.registry.get_rpc()
        weth = dict(TOKENS)['weth']
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if self.registry.lookup_month != month:
            self.registry.lookups = {key: value for key, value in self.registry.lookups.items() if value is not None}
            self.registry.lookup_month = month
        endpoints = {token_in.lower(), token_out.lower()}
        for pool in self.registry.inventory.values():
            if any(token['address'].lower() == self.registry.core.lower() for token in (pool['token0'], pool['token1'])):
                endpoints.update(token['address'].lower() for token in (pool['token0'], pool['token1']))
        # Existing direct/via-WETH paths plus CYGLD-counter connectors; do not
        # construct a complete token-universe cross product on every edit.
        pairs = {tuple(sorted((a, b))) for a in endpoints for b in (
            token_in.lower(), token_out.lower(), weth.lower()) if a != b}
        known = {(pool['protocol'], tuple(sorted((pool['token0']['address'].lower(),
            pool['token1']['address'].lower()))), int(pool['feePips'])): pool
            for pool in self.registry.inventory.values() if pool.get('address')}
        async def v2(pair):
            key = ('v2', pair, 3000)
            if key in known or key in self.registry.lookups:
                return
            try:
                address, = await rpc.read_function(rpc.v2_factory, 'getPair(address,address)',
                    ['address', 'address'], list(pair), ['address'], block)
                if address.lower() == ZERO:
                    self.registry.lookups[key] = None
                    return
                a, b = await asyncio.gather(*(self.registry.token_metadata(token, block) for token in pair))
                pool = {'id': address.lower(), 'protocol': 'v2', 'address': address,
                    'token0': a, 'token1': b, 'feePips': 3000}
                self.registry.inventory[pool['id']] = pool
                self.registry.lookups[key] = pool
                self.registry.persist('inventory', pool['id'], pool)
            except SnapshotChanged:
                raise
            except Exception:
                pass
        async def v3(pair, fee):
            key = ('v3', pair, fee)
            if key in known or key in self.registry.lookups:
                return
            address = None
            try:
                address, = await rpc.read_function(rpc.factory, 'getPool(address,address,uint24)',
                    ['address', 'address', 'uint24'], [*pair, fee], ['address'], block)
                if address.lower() == ZERO:
                    self.registry.lookups[key] = None
                    return
                a, b = await asyncio.gather(*(self.registry.token_metadata(token, block) for token in pair))
                spacing, = await rpc.read_function(address, 'tickSpacing()', [], [], ['int24'], block)
                pool = {'id': address.lower(), 'protocol': 'v3', 'address': address,
                    'token0': a, 'token1': b, 'feePips': fee, 'tickSpacing': spacing}
                self.registry.inventory[pool['id']] = pool
                self.registry.lookups[key] = pool
                self.registry.persist('inventory', pool['id'], pool)
            except SnapshotChanged:
                raise
            except Exception:
                # Discovery failure is unknown, not canonical absence. Keep
                # its execution identity for the SDK's on-demand acquisition.
                a, b = (self.registry.token(token, 18) for token in pair)
                pool = {'id': 'v3:'+':'.join((*pair, str(fee))), 'protocol': 'v3',
                    'token0': a, 'token1': b, 'feePips': fee,
                    'tickSpacing': {100: 1, 500: 10, 3000: 60, 10000: 200}[fee],
                    **({'address': address} if address else {})}
                self.registry.inventory[pool['id']] = pool
        pending = set()
        try:
            for pair in pairs:
                pending.add(asyncio.create_task(v2(pair)))
                for fee in (100, 500, 3000, 10000):
                    pending.add(asyncio.create_task(v3(pair, fee)))
                if len(pending) >= 32:
                    await asyncio.gather(*pending)
                    pending.clear()
            await asyncio.gather(*pending)
        finally:
            for task in pending:
                task.cancel()
            outcomes = await asyncio.gather(*pending, return_exceptions=True)
            raise_snapshot_disproof(outcomes)

    def resolve_branches(self, branches, token_in, token_out, mode, amount):
        """Retain route/allocation intent, use server-owned pool identities."""
        try:
            result = deepcopy(branches)
            inventory = {identity.lower(): pool for identity, pool in self.registry.inventory.items()}
            if not result:
                raise InvalidPreview('Retained route has no swap branches.')
            if mode == 'exactOut' and len(result) != 1:
                raise InvalidPreview('Exact-output split branches are not supported.')
            for branch in result:
                current = token_in.lower()
                if not branch['hops']:
                    raise InvalidPreview('Retained route has no swap hops.')
                for hop in branch['hops']:
                    pool = inventory.get(hop['pool']['id'].lower())
                    if pool is None:
                        key = pool_identity(hop['pool'])
                        pool = next((row for row in inventory.values() if pool_identity(row) == key), None)
                    if pool is None:
                        if hop['pool']['protocol'] != 'v3':
                            raise InvalidPreview('Retained pool identity is unavailable.')
                        # Retain the V3 execution identity. The registry acquires
                        # its required SDK state at the operation's pinned block.
                        pool = {name: deepcopy(hop['pool'][name]) for name in
                                ('id', 'protocol', 'token0', 'token1', 'feePips')}
                    hop['pool'] = deepcopy(pool)
                    source, target = (pool['token0']['address'], pool['token1']['address']) if hop['zeroForOne'] else (
                        pool['token1']['address'], pool['token0']['address'])
                    if source.lower() != current:
                        raise InvalidPreview('Retained route input currency does not match the preceding hop.')
                    current = target.lower()
                if current != token_out.lower():
                    raise InvalidPreview('Retained route output currency does not match the intent.')
                if not supported_route(branch['hops'], mode):
                    raise InvalidPreview('Mixed exact-output routes are not supported.')
            if mode == 'exactIn':
                if any(int(branch['amountIn']) < 0 for branch in result):
                    raise InvalidPreview('Retained branch input allocation is negative.')
                result = resize_branches(result, amount)
            return RouteQuoteEngine.enrich_branches(self, result)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            if isinstance(error, InvalidPreview):
                raise
            raise InvalidPreview('Retained route cannot be resolved.') from error

    async def quote_branches(self, branches, mode, amount, block):
        branches = RouteQuoteEngine.enrich_branches(self, branches)
        value = await self.quote_sdk_branches(branches, mode, amount, block)
        if not value.get('settled', True):
            raise InvalidPreview('Unsettled current-operation intermediate currency.')
        if mode == 'exactOut' and not value.get('fullyFilled', True):
            raise InvalidPreview('Exact-output target cannot be filled.')
        value['qualification'] = 'sdk'
        return value

    async def quote_sdk_branches(self, branches, mode, amount, block, *, candidate=None, canonical=None):
        branches = RouteQuoteEngine.enrich_branches(self, branches)
        canonical = canonical if canonical is not None else {}
        snapshots = {}
        pools = {}
        for branch in branches:
            for hop in branch['hops']:
                pool = hop['pool']
                pools.setdefault(pool['id'], pool)
        missing = {identity: pool for identity, pool in pools.items() if identity not in canonical}
        reads = {identity: asyncio.create_task(self.registry.snapshot(pool, block))
                 for identity, pool in missing.items()} if len(missing) > 1 else {}
        try:
            # Start only this candidate's required observations. Consume in
            # route order, preserving canonical insertion and read-error priority.
            for identity, pool in pools.items():
                if identity not in canonical:
                    canonical[identity] = await reads[identity] if reads else await self.registry.snapshot(pool, block)
                snapshots[identity] = deepcopy(candidate.get(identity, canonical[identity])
                    if candidate is not None else canonical[identity])
        finally:
            # These subscriptions are owned here; SharedReads preserves other
            # subscribers and cancels a producer only when nobody still needs it.
            for task in reads.values():
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*reads.values(), return_exceptions=True)
            raise_snapshot_disproof(outcomes)
        payload = {'operation': 'simulateRoute', 'mode': mode, 'amount': str(amount),
            'pools': list(snapshots.values()), 'route': {'branches': [
                {'amountIn': branch['amountIn'], 'hops': [{'poolId': hop['pool']['id'],
                    'zeroForOne': hop['zeroForOne']} for hop in branch['hops']]} for branch in branches]}}
        async def acquire(requests):
            observations = []
            for identity, snapshot in list(snapshots.items()):
                needed = [row for row in requests if row.get('poolId', row.get('id')) == identity]
                if needed:
                    observed = await self.registry.extend_ticks(canonical[identity], needed, block)
                    canonical[identity] = observed
                    snapshots[identity] = {**snapshot, 'ticks': observed['ticks'], 'bitmapWords': observed['bitmapWords']}
                    observations.append({'id': identity, 'ticks': observed['ticks'], 'bitmapWords': observed['bitmapWords']})
            return observations
        # The SDK pauses at its exact missing observation instead of replaying
        # completed swaps. The existing producer budget still owns every fill.
        while True:
            try:
                value = await self.sdk.request(payload, on_state=acquire)
                if candidate is not None:
                    # Compact postState carries only changing fields. Keep
                    # canonical coverage in this isolated candidate bank.
                    for post in value['postState']:
                        candidate[post['id']] = {**snapshots[post['id']], **post}
                return value
            except MissingPoolState as missing:
                # Direct/legacy SDK clients retain their ordinary state request.
                await acquire(missing.requests)
                payload['pools'] = list(snapshots.values())

    def v3_branches(self, path, mode, amount):
        return RouteQuoteEngine.enrich_branches(self,
            v3_branches(path, mode, amount, chain_id=self.registry.chain))

    async def compose_core_rows(self, rows, mode, block, *, ordered_assets=None, issue=False):
        """Replay shared selected pools in BasketRouter's actual asset order."""
        prepared = []
        for index, row in enumerate(rows):
            target, best = row['target'], row['best']
            if not best or target['inputAsset'].lower() == target['outputAsset'].lower():
                continue
            amount = int(target['amount'])
            branches = best['routePlan']['branches'] if best.get('routePlan') else self.v3_branches(best['path'], mode, amount)
            branches = self.resolve_branches(branches, target['inputAsset'], target['outputAsset'], mode, amount)
            prepared.append((index, branches))
        ids = [pool_identity(hop['pool']) for _, branches in prepared for branch in branches for hop in branch['hops']]
        if len(ids) == len(set(ids)):
            return rows
        order = {asset.lower(): index for index, asset in enumerate(ordered_assets or [])}
        prepared.sort(key=lambda item: order.get(rows[item[0]]['target']['outputAsset' if issue else 'inputAsset'].lower(), item[0]))
        result = deepcopy(rows)
        candidate, canonical = {}, {}
        for index, branches in prepared:
            target = rows[index]['target']
            value = await self.quote_sdk_branches(branches, mode, int(target['amount']), block,
                candidate=candidate, canonical=canonical)
            if not value.get('settled', True) or (mode == 'exactOut' and not value['fullyFilled']):
                raise InvalidPreview('Selected Core route cannot settle its required output.')
            best = result[index]['best']
            best['quote'] = value['amountOut' if mode == 'exactIn' else 'amountIn']
            if best.get('routePlan'):
                best['routePlan'].update(branches=branches, inputAmount=value['amountIn'], outputAmount=value['amountOut'])
        return result

    def initial_v3_branches(self, target, mode):
        return initial_v3_branches(target, mode, chain_id=self.registry.chain)

    async def search_candidates(self, request, block, evaluate, *, on_completed=None):
        """One scheduler for every candidate family and required Core leg."""
        mode = 'exactIn' if request['mode'] == 'exact-in' else 'exactOut'
        targets = request['targets']
        if all(target['inputAsset'].lower() == target['outputAsset'].lower() for target in targets):
            return
        scheduled = [{} for _ in targets]
        def inventory():
            return [pool for pool in self.registry.inventory.values() if pool['protocol'] != 'v4' or (
                pool.get('hooks', ZERO).lower() == ZERO and int(pool['feePips']) < 0x800000 and all(
                    token['address'].lower() != ZERO for token in (pool['token0'], pool['token1'])))]
        async def discover():
            try:
                await self.registry.ensure_loaded()
                for target in targets:
                    if target['inputAsset'].lower() == target['outputAsset'].lower():
                        continue
                    await self.connector_inventory(target['inputAsset'], target['outputAsset'], block)
            except SnapshotChanged:
                raise
            except Exception:
                # Discovery supplies optional observations; V3 execution identities
                # acquire SDK state without a database/catalog observation.
                return
        def make_feeds(_expanded):
            pools = inventory()
            async def feed(index, target):
                if target['inputAsset'].lower() == target['outputAsset'].lower():
                    return
                prior = dict(scheduled[index])
                seen = {}
                seed = iter(self.initial_v3_branches(target, mode))
                graph = candidate_branches(pools, target['inputAsset'], target['outputAsset'],
                    mode, int(target['amount']))
                seed_done = graph_done = False
                graph_next = asyncio.create_task(anext(graph))
                turn = 0
                try:
                    while not seed_done or not graph_done:
                        if not seed_done and (turn % 2 == 0 or graph_done or not graph_next.done()):
                            try:
                                branches = next(seed)
                            except StopIteration:
                                seed_done = True
                                turn += 1
                                continue
                        else:
                            try:
                                branches = await graph_next
                                graph_next = asyncio.create_task(anext(graph))
                            except StopAsyncIteration:
                                graph_done = True
                                turn += 1
                                continue
                        turn += 1
                        # The historical compiler only accepts homogeneous V3.
                        # This is the existing ABI dispatch, not new admission.
                        if (request.get('adapter') or '').lower() in LEGACY_V3_ADAPTERS and not (
                            len(branches) == 1 and all(hop['pool']['protocol'] == 'v3'
                                for hop in branches[0]['hops'])):
                            continue
                        key = route_identity(branches)
                        seen[key] = seen.get(key, 0)+1
                        if seen[key] <= prior.get(key, 0):
                            await asyncio.sleep(0)
                            continue
                        # A minimal seed and the same rich graph route are one
                        # candidate; rounded split multiplicities remain intact.
                        if len(branches) == 1 and key in scheduled[index]:
                            continue
                        yield branches
                finally:
                    graph_next.cancel()
                    outcomes = await asyncio.gather(graph_next, return_exceptions=True)
                    await graph.aclose()
                    raise_snapshot_disproof(outcomes)
            return [feed(index, target) for index, target in enumerate(targets)]
        async def admitted(index, branches):
            key = route_identity(branches)
            scheduled[index][key] = scheduled[index].get(key, 0)+1
            route_count('typedEnumerated')
            await evaluate(index, branches)
        await schedule_routes(make_feeds, admitted, discover=discover, on_completed=on_completed)

    async def search_routes(self, request, block, on_update=None):
        mode = 'exactIn' if request['mode'] == 'exact-in' else 'exactOut'
        results = [{'target': target, 'best': None, 'attempted': 0, 'succeeded': 0,
                    'failures': [], 'total': 0} for target in request['targets']]
        for result in results:
            target = result['target']
            if target['inputAsset'].lower() == target['outputAsset'].lower():
                result['best'] = {'path': '0x', 'quote': str(target['amount']),
                    'route': 'identity', 'feeInfo': '0', 'routePlan': {'version': 1,
                        'executionContext': request.get('executionContext', 'helpers-core'),
                        'mode': mode, 'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'],
                        'branches': [], 'inputAmount': str(target['amount']),
                        'outputAmount': str(target['amount']), 'limit': '0', 'deadline': '0'}}
        async def evaluate(index, branches):
            result = results[index]
            target = result['target']
            result['total'] += 1
            try:
                async with engine_work(self.semaphore):
                    value = await self.quote_branches(branches, mode, int(target['amount']), block)
                observed = int(value['amountOut' if mode == 'exactIn' else 'amountIn'])
                plan = {'version': 1, 'executionContext': request.get('executionContext', 'helpers-core'), 'mode': mode,
                    'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'],
                    'branches': deepcopy(branches), 'inputAmount': value['amountIn'],
                    'outputAmount': value['amountOut'], 'limit': '0', 'deadline': '0'}
                row = {'path': '0x', 'quote': str(observed),
                    'route': 'direct' if len(branches) == 1 and len(branches[0]['hops']) == 1 else 'mixed',
                    'feeInfo': '/'.join(str(hop['pool']['feePips']) for branch in branches
                        for hop in branch['hops']), 'routePlan': plan}
                result['succeeded'] += 1
                best = result['best']
                if observed > 0 and (best is None or (observed > int(best['quote'])
                        if mode == 'exactIn' else observed < int(best['quote']))):
                    result['best'] = row
            except SnapshotChanged:
                raise
            except Exception as error:
                if len(result['failures']) < 128:
                    result['failures'].append({'path': '0x', 'rpcCode': 0, **public_quote_error(error)})
            finally:
                result['attempted'] += 1
                route_count('typedCompleted')
        async def completed():
            if on_update:
                await on_update(deepcopy(results))
        await self.search_candidates(request, block, evaluate, on_completed=completed)
        return results

    async def reserve_quotes(self, request, block, on_update=None):
        return await self.search_routes(request, block, on_update)

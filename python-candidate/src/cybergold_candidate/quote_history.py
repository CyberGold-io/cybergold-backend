"""Organic display models and shared background state; never execution quotes."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction as F
import time

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

from .basket_arithmetic import BasketArithmetic, ceil_div, wire
from .protocol_facts import ABI as FACTS_ABI
from .quote_models import LegModel
from .recovery_rpc import ABI as RECOVERY_ABI, abi_value
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS
from .uniswap_routes import route_identity, standalone_v3, uses_typed_adapter, v3_plan
from .shared_reads import discard_pool_observation


def economic_path(path, mode):
    """Compatibility projection; packed input is normalized at this boundary."""
    plan = v3_plan(path, mode, 0)
    hops = plan['branches'][0]['hops']
    return [plan['tokenIn']]+[hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address']
                            for hop in hops], [hop['pool']['feePips'] for hop in hops]


def fraction(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def family(request):
    # Amount/deadline are not model identity; all token/order/native semantics are.
    return (request['mode'], request['token'].lower(), request['quoteToken'].lower(),
            request['native'], request['adapter'].lower(), tuple(a.lower() for a in request['orderedAssets']))


def route_key(plan):
    total = sum(int(branch['amountIn']) for branch in plan['branches'])
    identity = tuple((str(F(int(amount), total)) if total else '1', hops)
                     for amount, hops in route_identity(plan['branches']))
    if len(plan['branches']) == 1:
        hops = plan['branches'][0]['hops']
        tokens = (plan['tokenIn'].lower(),)+tuple(hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address'].lower() for hop in hops)
    else:
        tokens = (plan['tokenIn'].lower(), plan['tokenOut'].lower())
    fees = tuple(hop['pool']['feePips'] for branch in plan['branches'] for hop in branch['hops'])
    return tokens, fees, ('helpers-core', identity)


# Existing callers can migrate independently without retaining another model.
typed_route_key = route_key


class QuoteHistory:
    def __init__(self, settings, limit=256):
        self.settings, self.limit = settings, limit
        self.routes, self.families = OrderedDict(), OrderedDict()
        self.baselines, self.states, self.facts = OrderedDict(), OrderedDict(), OrderedDict()
        self.tasks = {}
        self.retiring_tasks = set()
        self.generation = None
        self.epoch = 0
        self.revision = 0
        self.reads = self.envelopes = 0
        self.predictions = self.retired = 0

    async def observe_generation(self, generation):
        """Retire optional display history at the existing accepted fork reset."""
        if not generation or generation == self.generation:
            return False
        self.generation = generation
        self.epoch += 1
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for bank in (self.routes, self.families, self.baselines, self.states, self.facts):
            bank.clear()
        self.revision += 1
        for task in tasks:
            self.retiring_tasks.add(task)
            task.add_done_callback(self.retiring_tasks.discard)
            task.cancel()
        return True

    def trim(self, bank):
        while len(bank) > self.limit:
            bank.popitem(last=False)

    def facts_observed(self, facts):
        if all(facts['basket'][key]['status'] == 'success' for key in ('assets', 'targetsPpm', 'cygldPerUnitFp18')) and all(
                row['status'] == 'success' for row in facts['fees'].values()):
            key = facts['context']['blockHash'].lower()
            self.facts[key] = deepcopy(facts)
            self.trim(self.facts)

    def launch(self, key, produce):
        if key in self.tasks:
            return
        async def background():
            try:
                async with asyncio.timeout(15):
                    await produce()
            except Exception:
                # Optional model acquisition failure leaves ordinary exact work alone.
                pass
            finally:
                if self.tasks.get(key) is task:
                    self.tasks.pop(key, None)
        task = asyncio.create_task(background())
        self.tasks[key] = task

    async def batch(self, rpc, calls, block, abi):
        contracts = {address: rpc.w3.eth.contract(abi=abi) for address, _, _ in calls}
        encoded = [(address, contracts[address].encode_abi(name, args=args)) for address, name, args in calls]
        if hasattr(rpc, 'pool_batch'):
            counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
            rows, _ = await rpc.pool_batch(encoded, block, counts)
            self.reads += counts['issued']
            self.envelopes += bool(counts['issued'])
        else:
            rows = await rpc.call_batch(encoded, block)
            self.reads += len(calls)
            self.envelopes += bool(calls)
        values = []
        for call, (_, name, _), row in zip(encoded, calls, rows, strict=True):
            if 'error' in row:
                raise ValueError('Optional model state unavailable: ' + name)
            out = next(entry for entry in abi if entry['name'] == name)['outputs'][0]
            try:
                value = rpc.w3.codec.decode([collapse_if_tuple(out)], bytes.fromhex(row['result'][2:]))[0]
                values.append(abi_value(value, out))
            except Exception:
                discard_pool_observation(rpc, call, block)
                raise
        return values

    def ensure_state(self, rpc, block, context):
        key = block['hash'].lower()
        row = self.states.get(key)
        # Model state is a display hint. Reuse it until the head changes or an
        # ordinary validated quote contradicts its arithmetic; no periodic
        # recalibration reads on a stagnant Sandbox header.
        if row:
            return
        epoch = self.epoch
        self.launch(('state', key), lambda: self.acquire_state(rpc, block, context, epoch))

    async def acquire_state(self, rpc, block, context, epoch=None):
        epoch = self.epoch if epoch is None else epoch
        core = Web3.to_checksum_address(self.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
        helpers = Web3.to_checksum_address(self.settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
        names = ('totalSupply', 'maxTotalSupply', 'effectiveCygldSupplyCap', 'redemptionFeePpm')
        abi = [{'name': name, 'type': 'function', 'stateMutability': 'view', 'inputs': [],
                'outputs': [{'type': 'uint256'}]} for name in names]
        abi += [{'name': 'coreAttachedRecoveryAssets', 'type': 'function', 'stateMutability': 'view',
                 'inputs': [], 'outputs': [{'type': 'address[]'}]},
                {'name': 'hasRole', 'type': 'function', 'stateMutability': 'view',
                 'inputs': [{'type': 'bytes32'}, {'type': 'address'}], 'outputs': [{'type': 'bool'}]}]
        abi += [row for row in RECOVERY_ABI['core'] if row['name'] in ('reserveCustodyStatus', 'recoveryPool')]
        fact_names = ('basketAssets', 'basketTargetsPpm', 'basketCygldPerUnitFp18', 'issuanceFeePpm')
        abi += [row for row in FACTS_ABI['core'] if row['name'] in fact_names] + FACTS_ABI['helpers']
        facts = self.facts.get(block['hash'].lower())
        calls = [(core, name, []) for name in names + ('coreAttachedRecoveryAssets',)] + [
            (core, 'hasRole', [Web3.keccak(text='REDEMPTION_FEE_EXEMPT_ROLE'), helpers])]
        if not facts:
            calls += [(core, name, []) for name in fact_names] + [(helpers, 'helperFeePpm', [])]
        values = await self.batch(rpc, calls, block, abi)
        supply, maximum, cap, redeem_fee, recovery, exempt = values[:6]
        assets, weights, conversions, issue_fee, helper_fee = (values[6:] if not facts else [
            facts['basket']['assets']['value'], facts['basket']['targetsPpm']['value'],
            facts['basket']['cygldPerUnitFp18']['value'], facts['fees']['issuancePpm']['value'],
            facts['fees']['helpersPpm']['value']])
        values = await self.batch(rpc, [(core, 'reserveCustodyStatus', [a]) for a in assets] + [
            (core, 'recoveryPool', [a]) for a in recovery], block, abi)
        custody, pools = values[:len(assets)], values[len(assets):]
        await rpc.assert_canonical(block)
        if epoch != self.epoch:
            return
        state = {'assets': assets, 'weights': list(map(int, weights)), 'conversions': list(map(int, conversions)),
                 'issueFee': int(issue_fee), 'helperFee': int(helper_fee), 'redeemFee': 0 if exempt else redeem_fee,
                 'supply': supply, 'maxSupply': maximum, 'effectiveCap': cap,
                 'available': [row['activeAvailableRaw'] for row in custody],
                 'recoveryShares': [p['coreAttachedShares'] for p in pools],
                 'recoveryValues': [ceil_div(p['coreAttachedShares'] * p['referenceValueCygld'], p['referenceShares'])
                                    for p in pools],
                 'descriptors': [{'kind': 0, 'token': a, 'id': '0'} for a in assets] + [
                     {'kind': 1, 'token': core, 'id': str(int(a, 16))} for a in recovery]}
        self.states[block['hash'].lower()] = {'context': {**deepcopy(context), 'observedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')}, 'state': wire(state), '_acquiredAt': time.monotonic()}
        self.states.move_to_end(block['hash'].lower())
        self.trim(self.states)
        self.revision += 1

    def ensure_route(self, provider, plan, block, context):
        plan = deepcopy(plan)
        key = (*route_key(plan), block['hash'].lower())
        if key in self.baselines:
            return
        epoch = self.epoch
        self.launch(('route', key), lambda: self.acquire_route(provider, plan, block, context, epoch))

    async def acquire_route(self, provider, plan, block, context, epoch=None):
        epoch = self.epoch if epoch is None else epoch
        baseline = await provider.route_baseline(plan, block)
        await provider.registry.get_rpc().assert_canonical(block)
        if epoch != self.epoch:
            return
        key = route_key(plan)
        self.baselines[(*key, block['hash'].lower())] = (baseline, deepcopy(context), time.monotonic())
        entry = self.routes.setdefault(key, {'model': LegModel(), 'context': deepcopy(context),
            'observations': [], 'routePlan': deepcopy(plan)})
        if entry['context']['blockHash'] != context['blockHash'] or (
            entry['model'].baseline is not None and entry['model'].baseline != baseline):
            entry['model'] = LegModel()
        entry['model'].baseline = baseline
        entry['context'] = deepcopy(context)
        entry['routePlan'] = deepcopy(plan)
        self.routes.move_to_end(key)
        self.baselines.move_to_end((*key, block['hash'].lower()))
        self.trim(self.routes)
        self.trim(self.baselines)
        self.revision += 1

    def ensure_known_routes(self, provider, request, block, context):
        """Known direct pool metadata can seed Core models without trade points."""
        epoch = self.epoch
        async def discover_known():
            await provider.registry.ensure_loaded(wait=True)
            if epoch != self.epoch:
                return
            issue = request['mode'].startswith('issue')
            for asset in request['orderedAssets']:
                source, target = (request['quoteToken'], asset) if issue else (asset, request['quoteToken'])
                for pool in list(provider.registry.inventory.values()):
                    if {source.lower(), target.lower()} != {
                        pool['token0']['address'].lower(), pool['token1']['address'].lower()}:
                        continue
                    plan = {'version': 1, 'executionContext': 'helpers-core',
                        'mode': 'exactOut' if request['mode'] == 'issue-exact-out' else 'exactIn',
                        'tokenIn': source, 'tokenOut': target,
                        'branches': [{'amountIn': '1', 'hops': [{'pool': deepcopy(pool),
                            'zeroForOne': source.lower() == pool['token0']['address'].lower()}]}],
                        'inputAmount': '0', 'outputAmount': '0', 'limit': '0', 'deadline': '0'}
                    self.ensure_route(provider, plan, block, context)
        self.launch(('known-routes', family(request), block['hash'].lower()), discover_known)

    # Compatibility adapters normalize at entry and delegate to the same engine.
    ensure_typed_pool = ensure_route
    ensure_known_typed_pools = ensure_known_routes

    def ensure_pool(self, rpc, path, mode, block, context):
        plan = v3_plan(path, mode, 0, chain_id=context['chainId'])
        self.ensure_route(getattr(rpc, 'route_engine', rpc), plan, block, context)

    def observe(self, request, result, waves):
        context = result['context']
        source_legs = []
        snapshot = self.states.get(context['blockHash'].lower())
        if snapshot:
            try:
                state = {k: [int(v) for v in value] if k in ('weights', 'conversions', 'available', 'recoveryShares', 'recoveryValues')
                         else int(value) if k in ('issueFee', 'helperFee', 'redeemFee', 'supply', 'maxSupply', 'effectiveCap') else value
                         for k, value in snapshot['state'].items()}
                model = BasketArithmetic(state)
                actual = result['basketPreview']
                prediction = (model.issue(int(result['executionAmount']), includes_helper=True)
                              if request['mode'].startswith('issue') else model.redeem_in(int(result['executionAmount'])))
                expected = {key: actual[key] for key in prediction}
                if wire(prediction) != expected:
                    self.states.pop(context['blockHash'].lower(), None)
            except (ValueError, KeyError, ZeroDivisionError):
                self.states.pop(context['blockHash'].lower(), None)
        for wave in waves:
            mode, rows = wave[:2]
            source_context = wave[2] if len(wave) > 2 else context
            for row in rows:
                best, target = row['best'], row['target']
                if not best:
                    continue
                plan = best.get('routePlan')
                if plan is None:
                    if best.get('path', '0x') == '0x':
                        continue
                    plan = v3_plan(best['path'], mode, target['amount'], chain_id=context['chainId'])
                    plan['inputAmount' if mode == 'exact-out' else 'outputAmount'] = best['quote']
                if not plan['branches']:
                    continue
                key = route_key(plan)
                entry = self.routes.setdefault(key, {'model': LegModel(), 'context': context, 'observations': []})
                entry['routePlan'] = deepcopy(plan)
                self.routes.move_to_end(key)
                baseline = self.baselines.get((*key, context['blockHash'].lower()))
                model = entry['model']
                if entry['context']['blockHash'] != context['blockHash']:
                    # Preserve old observations as history; do not relabel them
                    # as measured under a new marginal rate.
                    model = entry['model'] = LegModel()
                if baseline:
                    if model.baseline and model.baseline != baseline[0]:
                        model = entry['model'] = LegModel()
                    model.baseline = baseline[0]
                amount_in, amount_out = int(target['amount']), int(best['quote'])
                if mode == 'exact-out':
                    amount_in, amount_out = amount_out, amount_in
                before = model.retired
                previous_points = set(model.points)
                model.observe(amount_in, amount_out, 'anchored' if model.baseline else 'larger')
                self.retired += model.retired-before
                removed = previous_points-set(model.points)
                if removed:
                    if context['chainId'] != 1:
                        self.baselines.pop((*key, context['blockHash'].lower()), None)
                    for family_points in self.families.values():
                        for coordinate, point in list(family_points.items()):
                            if any(route == key and (a, b) in removed for route, a, b in point['_legs']):
                                del family_points[coordinate]
                source_legs.append((key, amount_in, amount_out))
                entry['observations'].append({'input': str(amount_in), 'output': str(amount_out), 'context': deepcopy(source_context), 'recordedAt': time.time()})
                entry['observations'][:] = entry['observations'][-64:]
                entry['context'] = deepcopy(context)
                self.trim(self.routes)
        key = family(request)
        entry = self.families.setdefault(key, OrderedDict())
        display = result.get('expectedInputAmount', result['displayAmount']) if request['mode'].endswith('exact-out') else result['displayAmount']
        entry[int(request['amount'])] = {'input': request['amount'], 'display': display,
                                         'context': deepcopy(context), 'recordedAt': time.time(), '_legs': source_legs}
        entry.move_to_end(int(request['amount']))
        while len(entry) > 16:
            entry.popitem(last=False)
        self.families.move_to_end(key)
        self.trim(self.families)
        self.revision += 1

    def packet(self, request):
        pairs = {(request['quoteToken'].lower(), a.lower()) if request['mode'].startswith('issue') else
                 (a.lower(), request['quoteToken'].lower()) for a in request['orderedAssets']}
        selected = {}
        for key, entry in reversed(self.routes.items()):
            if not uses_typed_adapter(request['adapter']) and not standalone_v3(entry['routePlan']):
                continue
            tokens, fees = key[:2]
            pair = (tokens[0], tokens[-1])
            if pair not in pairs or pair in selected:
                continue
            model = entry['model']
            points = sorted(model.points, key=lambda p: abs(p[0]-int(request['amount'])))[:4]
            row = {'tokens': list(tokens), 'fees': list(fees), 'context': deepcopy(entry['context']),
                   'points': [{**{'input': str(a), 'output': str(b)}, **next(
                       ({k: deepcopy(v) for k, v in observation.items() if k in ('context', 'recordedAt')}
                        for observation in reversed(entry['observations']) if observation['input'] == str(a) and observation['output'] == str(b)), {})}
                       for a, b in sorted(points)],
                   'feeRetention': fraction(F(1))}
            retention = F(1)
            for fee in fees:
                retention *= F(1_000_000-fee, 1_000_000)
            row['feeRetention'] = fraction(retention)
            if entry.get('routePlan'):
                row['routePlan'] = deepcopy(entry['routePlan'])
                row['protocols'] = [hop['pool']['protocol'] for branch in entry['routePlan']['branches'] for hop in branch['hops']]
                row['poolIds'] = [hop['pool']['id'] for branch in entry['routePlan']['branches'] for hop in branch['hops']]
            baseline = self.baselines.get((*key, entry['context']['blockHash'].lower()))
            if baseline:
                row['feeRetention'] = fraction(baseline[0].fee_retention)
                row['exchangeRate'] = fraction(baseline[0].exchange)
                row['exchangeContext'] = deepcopy(baseline[1])
                if baseline[0].local_impact is not None:
                    row['localImpact'] = fraction(baseline[0].local_impact)
            selected[pair] = row
        whole = list(self.families.get(family(request), {}).values())
        whole = sorted(whole, key=lambda row: abs(int(row['input'])-int(request['amount'])))[:4]
        return {'revision': self.revision, 'intent': {**{k: deepcopy(request[k]) for k in (
            'mode', 'token', 'quoteToken', 'native', 'adapter', 'orderedAssets', 'targets', 'amount')},
            'slippageBps': request.get('slippageBps', DEFAULT_SLIPPAGE_BPS)},
            'routes': list(selected.values()),
            'whole': [{k: deepcopy(v) for k, v in row.items() if not k.startswith('_')} for row in whole],
            'protocol': self.protocol_model()}

    def protocol_model(self):
        """Already-paid indicative state; never fetch or relabel its context."""
        state = next(reversed(self.states.values()), None) if self.states else None
        return {k: deepcopy(v) for k, v in state.items() if not k.startswith('_')} if state else None

    async def close(self):
        tasks = list({*self.tasks.values(), *self.retiring_tasks})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

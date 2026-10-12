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
from .pool_producer import ABI as POOL_ABI
from .quote_models import LegModel, PoolBaseline
from .recovery_rpc import ABI as RECOVERY_ABI, abi_value
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS
from .uniswap_routes import uses_typed_adapter
from .shared_reads import discard_pool_observation


def economic_path(path, mode):
    raw = bytes.fromhex(path[2:])
    tokens = ['0x' + raw[offset:offset+20].hex() for offset in range(0, len(raw), 23)]
    fees = [int.from_bytes(raw[offset:offset+3]) for offset in range(20, len(raw), 23)]
    if mode == 'exact-out':
        tokens, fees = list(reversed(tokens)), list(reversed(fees))
    return tokens, fees


def fraction(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def family(request):
    # Amount/deadline are not model identity; all token/order/native semantics are.
    return (request['mode'], request['token'].lower(), request['quoteToken'].lower(),
            request['native'], request['adapter'].lower(), tuple(a.lower() for a in request['orderedAssets']))


def typed_route_key(plan):
    total = sum(int(branch['amountIn']) for branch in plan['branches'])
    identity = tuple((str(F(int(branch['amountIn']), total)) if total else '1', tuple(
        (hop['pool']['protocol'], hop['pool']['id'].lower(), hop['zeroForOne']) for hop in branch['hops']))
        for branch in plan['branches'])
    if len(plan['branches']) == 1:
        hops = plan['branches'][0]['hops']
        tokens = (plan['tokenIn'].lower(),)+tuple(hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address'].lower() for hop in hops)
    else:
        tokens = (plan['tokenIn'].lower(), plan['tokenOut'].lower())
    fees = tuple(hop['pool']['feePips'] for branch in plan['branches'] for hop in branch['hops'])
    return tokens, fees, ('helpers-core', identity)


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

    def ensure_pool(self, rpc, path, mode, block, context):
        tokens, fees = economic_path(path, mode)
        key = (tuple(tokens), tuple(fees), block['hash'].lower())
        baseline = self.baselines.get(key)
        if baseline:
            return
        epoch = self.epoch
        self.launch(('pool', key), lambda: self.acquire_pool(rpc, tokens, fees, block, context, key, epoch))

    def ensure_typed_pool(self, provider, plan, block, context):
        route_key = typed_route_key(plan)
        key = (*route_key, block['hash'].lower())
        if key in self.baselines:
            return
        epoch = self.epoch
        async def acquire():
            baseline = await provider.route_baseline(plan, block)
            await provider.registry.get_rpc().assert_canonical(block)
            if epoch != self.epoch:
                return
            self.baselines[key] = (baseline, deepcopy(context), time.monotonic())
            entry = self.routes.setdefault(route_key, {'model': LegModel(), 'context': deepcopy(context),
                'observations': [], 'routePlan': deepcopy(plan)})
            if entry['context']['blockHash'] != context['blockHash'] or (
                entry['model'].baseline is not None and entry['model'].baseline != baseline):
                entry['model'] = LegModel()
            entry['model'].baseline = baseline
            entry['context'] = deepcopy(context)
            entry['routePlan'] = deepcopy(plan)
            self.routes.move_to_end(route_key)
            self.trim(self.routes)
            self.trim(self.baselines)
            self.revision += 1
        self.launch(('typed-pool', key), acquire)

    def ensure_known_typed_pools(self, provider, request, block, context):
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
                    if pool['protocol'] == 'v3' or {source.lower(), target.lower()} != {
                        pool['token0']['address'].lower(), pool['token1']['address'].lower()}:
                        continue
                    plan = {'version': 1, 'executionContext': 'helpers-core',
                        'mode': 'exactOut' if request['mode'] == 'issue-exact-out' else 'exactIn',
                        'tokenIn': source, 'tokenOut': target,
                        'branches': [{'amountIn': '1', 'hops': [{'pool': deepcopy(pool),
                            'zeroForOne': source.lower() == pool['token0']['address'].lower()}]}],
                        'inputAmount': '0', 'outputAmount': '0', 'limit': '0', 'deadline': '0'}
                    self.ensure_typed_pool(provider, plan, block, context)
        self.launch(('known-typed', family(request), block['hash'].lower()), discover_known)

    async def acquire_pool(self, rpc, tokens, fees, block, context, key, epoch=None):
        epoch = self.epoch if epoch is None else epoch
        async def reads(group, address, names, arguments=()):
            calls = [(address, rpc.pools.pool_contracts[group].encode_abi(name, args=list(arguments))) for name in names]
            counts = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
            try:
                rows, _ = await rpc.pool_batch(calls, block, counts)
            finally:
                self.reads += counts['issued']
                self.envelopes += bool(counts['issued'])
            result = []
            for call, name, row in zip(calls, names, rows, strict=True):
                if 'error' in row:
                    raise ValueError('Optional pool state unavailable')
                outputs = next(entry for entry in POOL_ABI[group] if entry.get('name') == name)['outputs']
                try:
                    decoded = rpc.w3.codec.decode([collapse_if_tuple(out) for out in outputs], bytes.fromhex(row['result'][2:]))
                    result.append(decoded[0] if len(decoded) == 1 else decoded)
                except Exception:
                    discard_pool_observation(rpc, call, block)
                    raise
            return result
        async def hop(token_in, token_out, fee):
            ordered = sorted((token_in, token_out))
            address = (await reads('factory', rpc.pools.factory, ('getPool',), (*map(Web3.to_checksum_address, ordered), fee)))[0]
            slot, liquidity = await reads('pool', Web3.to_checksum_address(address), ('slot0', 'liquidity'))
            return PoolBaseline.v3(int(slot[0]), int(liquidity), fee, token_in == ordered[0])
        hops = await asyncio.gather(*(hop(a, b, f) for a, b, f in zip(tokens[:-1], tokens[1:], fees, strict=True)))
        rate, retention, impact = F(1), F(1), F(0)
        for baseline in hops:
            if baseline.local_impact is None:
                raise ValueError('Optional zero-liquidity model')
            impact += baseline.local_impact * baseline.fee_retention * rate * retention
            rate *= baseline.exchange
            retention *= baseline.fee_retention
        await rpc.assert_canonical(block)
        if epoch != self.epoch:
            return
        self.baselines[key] = (PoolBaseline(rate, retention, impact/retention), {**deepcopy(context), 'observedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')}, time.monotonic())
        self.baselines.move_to_end(key)
        self.trim(self.baselines)
        self.revision += 1

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
                if not best or (best['path'] == '0x' and not best.get('routePlan')):
                    continue
                plan = best.get('routePlan')
                if plan:
                    key = typed_route_key(plan)
                else:
                    tokens, fees = economic_path(best['path'], mode)
                    key = (tuple(tokens), tuple(fees))
                entry = self.routes.setdefault(key, {'model': LegModel(), 'context': context, 'observations': []})
                if plan:
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
            if len(key) > 2 and not uses_typed_adapter(request['adapter']):
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

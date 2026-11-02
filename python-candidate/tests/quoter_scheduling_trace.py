"""Actual whole-Quoter scheduling traces over an explicit synthetic chain.

The ordinary factory, graph discovery, optional work, eight pricing permits,
5/15-second producer budget, SDK pricing and whole-plan comparison are intact.
Chain replies/Core preview, selected-plan SDK component pricing and hosted
HTTP responses are explicit fixture data; this does not emulate Helpers execution.
No private environment file, live RPC or real Uniswap account is consumed.
"""
import asyncio
from collections import Counter
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import resource
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch
from weakref import WeakKeyDictionary

import httpx
from aiohttp import web

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quote_budget import QuoteBudget, current_budget
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate import route_observations
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.uniswap_routes import pool_identity
from cybergold_candidate.routing_encoding import ZERO
from benchmark_matrix_fixture import BLOCK, CORE, OTHER, PAXG, WETH, LoopbackState, MatrixCase, MatrixService
from benchmark_parallel_matrix import ROOT, selected_request, selected_topology
from benchmark_parallel_matrix import canonical_cache, difference, source_bindings
from cybergold_candidate.routing_encoding import weighted_routes
from quoter_fixture import synthetic_pool
from test_universal_quote import fixture_plan_simulator


STRATEGIES = ('custom-only', 'all-local', 'hosted-failure', 'parallel')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def asset(address):
    return {WETH.lower(): 'WETH', PAXG.lower(): 'PAXG', OTHER.lower(): 'OTHER',
            CORE.lower(): 'synthetic-CYGLD', ZERO: 'native'}.get(address.lower(), 'other-asset')


def pool_tag(pool):
    return {'identity': digest(pool_identity(pool)), 'protocol': pool['protocol'], 'feePips': pool['feePips']}


def candidate_tag(branches, origins=()):
    return {'candidate': digest([(row['amountIn'], [
        (pool_identity(hop['pool']), hop['zeroForOne']) if 'pool' in hop else
        (hop['kind'], hop['currencyOut']) for hop in row['hops']]) for row in branches]),
        'origins': list(origins), 'pools': [pool_tag(hop['pool']) for row in branches
            for hop in row['hops'] if 'pool' in hop]}


class SchedulingTrace:
    def __init__(self):
        self.started = time.perf_counter()
        self.events = []
        self.tasks, self.candidates, self.rounds = WeakKeyDictionary(), WeakKeyDictionary(), WeakKeyDictionary()
        self.task_sequence = 0
        self.early_finder = asyncio.Event()
        self.round_sequence = 0
        self.round_context = ContextVar('scheduling_trace_round', default=None)
        self.slots = None
        self.phase = 'search'
        self.budget_windows = None

    def emit(self, kind, **fields):
        task = asyncio.current_task()
        if task is not None and task not in self.tasks:
            self.task_sequence += 1
            self.tasks[task] = self.task_sequence
        budget = current_budget()
        if budget is not None and self.budget_windows is None:
            self.budget_windows = {'initialMs':round((budget.initial-budget.started)*1000,3),
                'deadlineMs':round((budget.deadline-budget.started)*1000,3)}
        self.events.append({'event': kind, 'phase': self.phase, 'atMs': round((time.perf_counter()-self.started)*1000, 3),
            'producerMs': round(budget.elapsed(), 3) if budget is not None else None,
            'task': self.tasks.get(task), 'round': self.round_context.get(),
            'origin': route_observations._origin.get(), **fields})

    @contextmanager
    def observe(self, quoter):
        trace = self
        self.slots = quoter.engine.semaphore
        old_publish, old_run = RouteBootstrap._publish_batch, RouteBootstrap.run
        old_completed = getattr(RouteBootstrap, 'publish_completed', None)
        old_nominations, old_candidate = CyberGoldAmmAdapter.nominations, Quoter.candidate
        old_acquire, old_release = PricingSlots.acquire, PricingSlots.release
        old_quote = quoter.engine.quote_sdk_branches
        old_snapshot = quoter.engine.registry.snapshot
        old_qualified, old_stop = QuoteBudget.qualified, QuoteBudget.finish_selection
        old_lock = quoter.engine.sdk.lock

        def published(session, response, entry, attempt):
            count = len(entry['offers'])
            result = old_publish(session, response, entry, attempt)
            offers = entry['offers'][count:]
            trace.emit('source-batch', source=entry['name'], revision=session.revision,
                sourceAsset=asset(entry['query'].source), targetAsset=asset(entry['query'].target),
                amount=str(entry['query'].amount), nominations=[candidate_tag(o['branches'], o['origins']) for o in offers])
            if entry['name'] == 'uniroute-local' and offers:
                trace.early_finder.set()
            return result

        def completed(session, query, route, origins=()):
            previous_revision = session.revision
            result = old_completed(session, query, route, origins)
            if result:
                trace.emit('completed-topology-publication', revision=session.revision,
                    notified=session.revision != previous_revision,
                    sourceAsset=asset(query.source), targetAsset=asset(query.target), amount=str(query.amount),
                    **candidate_tag([{'amountIn':str(query.amount),'hops':route}], origins))
            return result

        async def running(session, ordinary, reevaluate, **kwargs):
            async def observed_arrival(operation, lane):
                task = asyncio.current_task()
                trace.round_sequence += 1
                number = trace.round_sequence
                trace.rounds[task] = number
                token = trace.round_context.set(number)
                trace.emit('arrival-round-start', revision=session.revision, number=number, lane=lane)
                try:
                    return await operation()
                finally:
                    trace.emit('arrival-round-end', revision=session.revision, number=number, lane=lane)
                    trace.rounds.pop(task, None)
                    trace.round_context.reset(token)
            async def arrival():
                return await observed_arrival(reevaluate, 'detailed')
            quick = kwargs.get('quick')
            if quick is not None:
                async def quick_arrival():
                    return await observed_arrival(quick, 'quick')
                kwargs['quick'] = quick_arrival
            return await old_run(session, ordinary, arrival, **kwargs)

        def nominations(adapter, source, target, amount, block, **kwargs):
            iterator = iter(old_nominations(adapter, source, target, amount, block, **kwargs))
            task = asyncio.current_task()
            previous = trace.candidates.get(task)
            try:
                for branches, origins in iterator:
                    tag = candidate_tag(branches, origins)
                    trace.candidates[task] = tag
                    trace.emit('conversion-candidate', sourceAsset=asset(source), targetAsset=asset(target),
                               amount=str(amount), first=kwargs.get('first', False), **tag)
                    yield branches, origins
            finally:
                if previous is None:
                    trace.candidates.pop(task, None)
                else:
                    trace.candidates[task] = previous
                close = getattr(iterator, 'close', None)
                if close is not None:
                    close()

        async def candidate(service, request, share, order, *args, **kwargs):
            trace.emit('whole-plan-start', share=share, order=order, first=kwargs.get('first', False))
            try:
                value = await old_candidate(service, request, share, order, *args, **kwargs)
                trace.emit('whole-plan-priced', share=share, order=order, output=value['quotedOutput'],
                    funding=[{'asset': asset(i['currency']), 'amount': i['amount']} for i in value['inputs']],
                    fees=value['fees'], kinds=[b['kind'] for b in value['plan']['body']['branches']],
                    origins=value.get('routeOrigins', {}).get('discoveryProviders', []))
                return value
            except BaseException as error:
                trace.emit('whole-plan-exit', share=share, order=order, outcome=type(error).__name__)
                raise

        async def acquire(slots):
            if slots is trace.slots:
                trace.emit('engine-permit-wait', free=slots._value,
                    ordinaryQueued=len(slots._ordinary), priorityQueued=len(slots._priority))
            result = await old_acquire(slots)
            if slots is trace.slots:
                trace.emit('engine-permit-acquired', free=slots._value)
            return result

        def release(slots):
            result = old_release(slots)
            if slots is trace.slots:
                trace.emit('engine-permit-released', free=slots._value)
            return result

        async def quote(*args, **kwargs):
            tag = trace.candidates.get(asyncio.current_task(), {})
            branches = args[0]
            trace.emit('canonical-price-start', amount=str(args[2]),
                **candidate_tag(branches, tag.get('origins', [])))
            try:
                value = await old_quote(*args, **kwargs)
                trace.emit('canonical-price-end', amountIn=value['amountIn'], amountOut=value['amountOut'],
                    fullyFilled=value['fullyFilled'], settled=value['settled'],
                    **candidate_tag(branches, tag.get('origins', [])))
                return value
            except BaseException as error:
                trace.emit('canonical-price-exit', outcome=type(error).__name__,
                           **candidate_tag(branches, tag.get('origins', [])))
                raise

        async def snapshot(pool, *args, **kwargs):
            trace.emit('initial-state-wait', free=trace.slots._value, **pool_tag(pool))
            try:
                return await old_snapshot(pool, *args, **kwargs)
            finally:
                trace.emit('initial-state-end', free=trace.slots._value, **pool_tag(pool))

        def qualified(budget):
            result = old_qualified(budget)
            trace.emit('qualification', admitted=result, reason=budget.reason)
            return result

        def stop(budget, reason):
            before = budget.stop.is_set()
            result = old_stop(budget, reason)
            if not before:
                trace.emit('selection-stop', reason=budget.reason)
            return result

        class SdkLock:
            async def acquire(self):
                trace.emit('sdk-queue-wait', locked=old_lock.locked())
                result=await old_lock.acquire()
                trace.emit('sdk-exchange-enter')
                return result
            def release(self):
                trace.emit('sdk-exchange-leave')
                old_lock.release()
            def locked(self):
                return old_lock.locked()
            async def __aenter__(self):
                await self.acquire()
                return self
            async def __aexit__(self, *_):
                self.release()

        with ExitStack() as stack:
            if old_completed is not None:
                stack.enter_context(patch.object(RouteBootstrap, 'publish_completed', completed))
            for target, name, operation in ((RouteBootstrap, '_publish_batch', published),
                (RouteBootstrap, 'run', running), (CyberGoldAmmAdapter, 'nominations', nominations),
                (quoter, 'candidate', candidate.__get__(quoter, Quoter)), (PricingSlots, 'acquire', acquire),
                (PricingSlots, 'release', release), (QuoteBudget, 'qualified', qualified),
                (QuoteBudget, 'finish_selection', stop),
                (quoter.engine.sdk, 'lock', SdkLock()),
                (quoter.engine, 'quote_sdk_branches', quote), (quoter.engine.registry, 'snapshot', snapshot)):
                stack.enter_context(patch.object(target, name, operation))
            yield self


def v3_pool(a, b, number, fee):
    pool = synthetic_pool(a, b, number, 'v3', liquidity=10**10)
    if fee == 100:
        pool['feePips'], pool['tickSpacing'] = 100, 1
        words = {}
        for tick in pool['ticks']:
            compressed = tick['index']
            words[compressed >> 8] = words.get(compressed >> 8, 0) | 1 << (compressed % 256)
        pool['bitmapWords'] = [{'wordPosition': word, 'bitmap': str(value)} for word, value in words.items()]
    return pool


def fixture_case(core_preview):
    pools = [v3_pool(WETH, PAXG, 2101, 3000), v3_pool(WETH, PAXG, 2102, 100),
             synthetic_pool(PAXG, CORE, 2105, 'v4', liquidity=10**12)]
    request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
    return MatrixCase('serving-market-plus-core' if core_preview else 'serving-pure-market',
        'market-plus-core' if core_preview else 'pure-market', tuple(pools), request, core_preview,
        'Synthetic Core/anchor and finite canonical RPC delays; actual serving discovery and all supplier implementations.')


class SchedulingState(LoopbackState):
    def __init__(self, case, trace, *, slow_scalar_ms=6000, slow_catalog_ms=7000):
        super().__init__(case.pools)
        self.trace, self.slow_scalar_ms, self.slow_catalog_ms = trace, slow_scalar_ms, slow_catalog_ms
        self.old = [pool for pool in case.pools if pool['protocol']=='v3' and pool['feePips']==3000]

    async def receive(self, request):
        body = await request.json()
        rows = body if isinstance(body, list) else [body]
        self.envelopes += 1
        self.members += len(rows)
        self.methods.update(row.get('method') for row in rows)
        delay, kind = 0, None
        for row in rows:
            if row.get('method') != 'eth_call':
                continue
            call = row['params'][0]
            target, data = call['to'].lower(), call['data'].lower()
            scalar = any(selector in data for selector in ('3850c7bd','1a686502'))
            if scalar and any(target==pool['address'].lower() or pool['address'][2:].lower() in data for pool in self.old):
                delay, kind = self.slow_scalar_ms, 'old-pool-scalar'
            selector = data[:10]
            if selector == '0x1698ee82':  # getPool(address,address,uint24)
                a,b,fee = self.codec.decode(['address','address','uint24'], bytes.fromhex(data[10:]))
                if PAXG.lower() in (a.lower(),b.lower()) and fee==10000:
                    delay, kind = self.slow_catalog_ms, 'unrelated-catalog-read'
        if delay:
            phase=self.trace.phase
            self.trace.emit('fixture-rpc-delay-start', delayKind=kind, delayMs=delay, phase=phase)
            await asyncio.sleep(delay/1000)
            self.trace.emit('fixture-rpc-delay-end', delayKind=kind, phase=phase)
        return web.json_response([self.reply(row) for row in body] if isinstance(body,list) else self.reply(body))


def hosted_document(pools, source, target, *, guidestar):
    from cybergold_candidate.quoter.discovery import paths
    options = paths(pools, source, target)
    route = options[0] if options else []
    standard, steps = [], []
    for hop in route:
        if 'pool' not in hop:
            continue
        pool = hop['pool']
        a,b = (pool['token0']['address'], pool['token1']['address']) if hop['zeroForOne'] else (
            pool['token1']['address'], pool['token0']['address'])
        standard.append({'type': pool['protocol']+'-pool', 'tokenIn': {'address':a},
            'tokenOut': {'address':b}, 'fee':pool['feePips'], 'tickSpacing':pool['tickSpacing'], 'hooks':pool['hooks']})
        if pool['protocol']=='v3':
            steps.append({'type':'V3_SWAP_EXACT_IN','path':'0x'+a[2:]+format(pool['feePips'],'06x')+b[2:]})
        else:
            steps.append({'type':'V4_SWAP','v4Actions':[{'action':'SWAP_EXACT_IN_SINGLE','poolKey':{
                'currency0':pool['token0']['address'],'currency1':pool['token1']['address'],
                'fee':pool['feePips'],'tickSpacing':pool['tickSpacing'],'hooks':pool['hooks']}}]})
    return {'quote': {'route': [] if guidestar else ([standard] if standard else []),
        **({'swapSteps': steps} if guidestar else {'routeCandidates':[{'fixture':'not parsed'}]})}}


def reference_plan(case, *, core_preview):
    """One independently replayable fast-path plan, never injected into search."""
    better={pool['token0']['address'].lower() if pool['token1']['address'].lower()==WETH.lower()
            else pool['token1']['address'].lower():pool for pool in case.pools
            if pool['protocol']=='v3' and pool['feePips']==100}
    def hop(pool, source):
        return {'pool':deepcopy(pool),'zeroForOne':pool['token0']['address'].lower()==source.lower()}
    amount=int(case.request['inputs'][0]['amount'])
    conversions={}
    def conversion(operation,target,funded,hops):
        template={'inputCurrency':WETH,'outputCurrency':target,
            'routes':weighted_routes([{'amountIn':str(funded),'hops':hops}])}
        conversions[operation]={'inputCurrency':WETH,'outputCurrency':target,
            'branches':[{'hops':deepcopy(hops)}],'template':deepcopy(template)}
        return template
    if not core_preview:
        hops=[hop(better[PAXG.lower()],WETH),hop(case.pools[-1],PAXG)]
        route=conversion('0:market',CORE,amount,hops)
        data={'route':route,'feeCygld':'0'}
        kind=1
    else:
        acquisitions=[]
        for index,target in enumerate((PAXG,)):
            funded=amount
            route=conversion(f'0:acquire:{index}',target,funded,[hop(better[target.lower()],WETH)])
            acquisitions.append({'amountIn':str(funded),'route':route})
        data={'basketAssets':[PAXG],'acquisitions':acquisitions,
            'continuations':[{'route':{'inputCurrency':a,'outputCurrency':a,'routes':[]},'feeCygld':'0'}
                for a in (PAXG,)]}
        kind=0
    return {'allocations':[{'kind':kind,'amountIn':str(amount)}],'conversions':conversions,
            'body':{'branches':[{'kind':kind,'amountIn':str(amount),'data':data}]}}


def bindings():
    result=source_bindings()
    for name in ('quoter_scheduling_trace.py','test_quoter_scheduling_trace.py','benchmark_quoter_scheduling.py'):
        path=ROOT/'python-candidate/tests'/name
        if path.exists():result[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


async def run_fixture(*, node, core_preview=False, slow_scalar_ms=6000, slow_catalog_ms=7000,
                      cache_mode='cold', strategy='parallel'):
    before=bindings()
    session_started=time.perf_counter()
    child_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    case = fixture_case(core_preview)
    trace = SchedulingTrace()
    transport = await SchedulingState(case, trace, slow_scalar_ms=slow_scalar_ms,
        slow_catalog_ms=slow_catalog_ms).start()
    service = MatrixService(case, transport, node, ROOT)
    q, registry = service.quoter, service.registry
    # Keep the actual serving seed/discovery paths. Initial observed state and
    # connectors are not acquired for free before the producer budget starts.
    registry.inventory = {pool['id']: deepcopy(pool) for pool in service.catalog_identities.values()
        if pool['protocol']=='v4' or pool['feePips']==3000}
    q.seed_routes = Quoter.seed_routes.__get__(q, Quoter)
    q.discover = Quoter.discover.__get__(q, Quoter)
    q.candidate = Quoter.candidate.__get__(q, Quoter)
    async def basis(_):
        return [PAXG], [1_000_000]
    q.basis_reader=basis
    async def simulate(request, selected, **kwargs):
        # MatrixService's generic oracle captures its original two-asset basis.
        # This scheduling case owns a one-asset Core: bind every selected replay
        # to the same basis as ordinary search, using an explicit component oracle.
        return await fixture_plan_simulator(q, request, selected, basis_reader=q.basis, **kwargs)
    q.plan_simulator=simulate
    async def preview(mode, value, block):
        if not core_preview or mode!='issue-exact-in':
            raise QuoteFailure('quote-no-route')
        matched = min(map(int,value['maximumAmountsIn']))
        return {'netCygldOut':str(matched*3),'amountsInExact':[str(matched)],
            'orderedCoreAssets':[PAXG],'fees':{'protocolFeeCygld':'0','helperFeeCygld':'0'}}
    q.preview = preview
    settings = SimpleNamespace(**{**vars(service.settings),
        'CYBERGOLD_UNISWAP_API_KEY':None if strategy=='all-local' else 'offline-fixture',
        'CYBERGOLD_UNISWAP_API_SWAPPER':None})
    better = [pool for pool in case.pools if pool['protocol']=='v4' or pool['feePips']==100]
    hosted_receipts=Counter()
    async def hosted(request):
        guidestar=request.headers.get('x-universal-router-swapsteps')=='true'
        hosted_receipts['uniswap-guidestar' if guidestar else 'uniroute-api']+=1
        await trace.early_finder.wait()
        await asyncio.sleep(.2)
        if strategy=='hosted-failure':
            return httpx.Response(503,json={'error':'offline-fixture-service-unavailable'})
        payload=json.loads(request.content)
        return httpx.Response(200,json=hosted_document(better,payload['tokenIn'],payload['tokenOut'],
            guidestar=guidestar))
    suppliers=[]
    def providers():
        tools=route_providers(settings,q.engine)
        for tool in tools:
            raw=getattr(tool,'provider',tool)
            if hasattr(raw,'command'):
                raw.command=[node,str(ROOT/raw.command[1]),*raw.command[2:]]
            if hasattr(raw,'client_factory'):
                raw.client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(hosted),timeout=None)
        suppliers.extend(tools)
        return tools
    # Warm requests have the identical independently executed custom-only
    # primer. Its observations/work stay separate from measured search.
    primer=None
    if cache_mode=='warm':
        trace.phase='primer'
        start=time.perf_counter();server_before=transport.counts()
        try:
            value=await q.get(deepcopy(case.request))
            primer={'status':'completed','output':value['quotedOutput'],'funding':value['inputs'],
                    'metrics':value.get('metrics',{})}
        except Exception as error:
            primer={'status':'failed','failureType':type(error).__name__,
                    'metrics':getattr(error,'quoter_metrics',{})}
        primer.update(wallMs=round((time.perf_counter()-start)*1000,3),
                      serverRpc=difference(transport.counts(),server_before))
    if strategy!='custom-only':q.route_provider_factory=providers
    trace.phase='search';trace.started=time.perf_counter()
    cache_before=canonical_cache(registry)
    server_before=transport.counts()
    result={'case':case.name,'status':'pending','scope':'synthetic-Core-and-chain/hosted-HTTP-fixtures/actual-serving-Quoter',
        'pin':BLOCK,'chainState':'synthetic-immutable-ABI-responses',
        'pricingOracle':'explicit-selected-plan-SDK-component; not Helpers execution',
        'request':{'inputAsset':'WETH','inputRaw':'10000','outputAsset':'synthetic-CYGLD'},'updates':[],
        'strategy':strategy,'cacheMode':cache_mode,'primer':primer,
        'configuration':{'optionalLimit':None,'engineSlots':q.engine.semaphore._value},
        'hostedFixtureMode':{'custom-only':'not-used','all-local':'unconfigured',
            'hosted-failure':'http-503-fixture','parallel':'success-fixture'}[strategy],
        'candidateInstrumentation':'owned-instance-method; whole-plan start/priced/exit spans recorded',
        'canonicalCacheBefore':cache_before,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sourceSha256Before':before,'fixtureSha256':case.digest,
        'fixtureDelaysMs':{'oldScalar':slow_scalar_ms,'unrelatedCatalog':slow_catalog_ms}}
    async def publish(frame):
        if frame['type']!='qualified':return
        quote=frame['value']
        event={'output':quote['quotedOutput'],'funding':[{'asset':asset(i['currency']),'amount':i['amount']} for i in quote['inputs']],
            'origins':quote.get('routeOrigins',{}),'fees':quote['fees'],
            'kinds':[b['kind'] for b in quote['plan']['body']['branches']],
            'selectedPhase':quote.get('searchCoverage',{}).get('selectedPhase')}
        result['updates'].append(event)
        trace.emit('whole-plan-qualified',**event)
    search_started,python_started=time.perf_counter(),time.process_time()
    try:
        with trace.observe(q):
            value=await q.get(deepcopy(case.request),publish)
        result['searchWallMs']=round((time.perf_counter()-search_started)*1000,3)
        result['searchPythonCpuMs']=round((time.process_time()-python_started)*1000,3)
        result.update(status='completed',output=value['quotedOutput'],funding=[{'asset':asset(i['currency']),
            'amount':i['amount']} for i in value['inputs']],metrics=value.get('metrics',{}),
            fees=value['fees'],selectedKinds=[b['kind'] for b in value['plan']['body']['branches']],
            origins=value.get('routeOrigins',{}),selectedTopology=selected_topology(value))
        result['searchServerRpc']=difference(transport.counts(),server_before)
        result['canonicalCacheAfter']=canonical_cache(registry)
        trace.phase='selected-replay';replay_before=transport.counts()
        replay=await q.evaluate_selected(selected_request(case.request,value),value['plan'])
        result['replaySameOutput']=replay['quotedOutput']==value['quotedOutput']
        result['selectedReplayServerRpc']=difference(transport.counts(),replay_before)
        trace.phase='independent-reference';reference_before=transport.counts()
        reference=await q.evaluate_selected(case.request,reference_plan(case,core_preview=core_preview))
        result['independentReference']={'output':reference['quotedOutput'],'funding':[
            {'asset':asset(i['currency']),'amount':i['amount']} for i in reference['inputs']],
            'fees':reference['fees'],'kinds':[b['kind'] for b in reference['plan']['body']['branches']],
            'qualification':'separate-selected-plan-synthetic-SDK-replay-after-search',
            'serverRpc':difference(transport.counts(),reference_before)}
    except Exception as error:
        result.update(status='failed',failureType=type(error).__name__,failurePhase=trace.phase)
        result.setdefault('metrics',getattr(error,'quoter_metrics',{}))
        result.setdefault('searchWallMs',round((time.perf_counter()-search_started)*1000,3))
        result.setdefault('searchPythonCpuMs',round((time.process_time()-python_started)*1000,3))
    finally:
        result.setdefault('searchServerRpc',difference(transport.counts(),server_before))
        await service.close()
        await transport.close()
        result['events']=trace.events
        result['budgetConfiguration']=trace.budget_windows
        result['hostedFixtureReceivedRequests']=dict(hosted_receipts)
        result['serverRpc']=transport.counts()
        result['allSuppliersClosed']=all(getattr(getattr(t,'provider',t),'closed',True) is not False
            and not getattr(getattr(t,'provider',t),'clients',()) for t in suppliers)
        result['sdkChildRetired']=q.engine.sdk.process is None or q.engine.sdk.process.returncode is not None
        result['supplierChildrenRetired']={t.name:(getattr(getattr(t,'provider',t),'process',None) is None
            or getattr(getattr(t,'provider',t),'process').returncode is not None) for t in suppliers
            if hasattr(getattr(t,'provider',t),'process')}
        result['liveHttpClients']=sum(len(getattr(getattr(t,'provider',t),'clients',())) for t in suppliers)
        child_after=resource.getrusage(resource.RUSAGE_CHILDREN)
        result['childCpuIncludingPrimerReplayCleanupMs']=round(1000*(child_after.ru_utime+child_after.ru_stime
            -child_before.ru_utime-child_before.ru_stime),3)
        result['sessionWallIncludingPrimerReplayCleanupMs']=round((time.perf_counter()-session_started)*1000,3)
        physical=result.get('metrics',{}).get('routeDiscovery',{}).get('physicalRpc',{})
        result['rpcReconciliation']={'clientAttemptsMinusServerEnvelopes':physical.get('requests',0)
            -result['searchServerRpc']['httpEnvelopes'],
            'clientMembersMinusServerMembers':physical.get('jsonRpcMembers',0)-result['searchServerRpc']['jsonRpcMembers'],
            'scope':'measured-search; server counts received HTTP bodies before finite response delay'}
        result['sourceSha256After']=bindings()
        result['sourceContentChangedDuringRun']=before!=result['sourceSha256After']
    return result

"""Request-owned route hints alongside ordinary whole-plan discovery.

Suppliers nominate semantic candidates only. Conversions read completed hints
without waiting; arrivals ask the owner to reevaluate its ordinary whole plans.
No supplier quote, private pool bank, selection clock or ranking lives here.
"""
import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from inspect import isawaitable, iscoroutine

from ..quote_budget import SearchStopped, current_budget
from ..recovery_rpc import SnapshotChanged
from ..route_observations import origin_scope
from ..uniswap_routes import pool_identity
from .route_tools import PendingRouteTool, RouteQuery, RouteTool, async_batches, round_robin
from .discovery import route_identity, TopologyCache, topology_scope
from .provenance import origin_names
from .cooperative import CHECKPOINT


_bootstrap = ContextVar('route_discovery_bootstrap', default=None)
_quick_offers = ContextVar('route_discovery_quick_offers', default=None)


def current_bootstrap():
    return _bootstrap.get()


@contextmanager
def bootstrap_scope(session):
    token = _bootstrap.set(session)
    try:
        with topology_scope(session.topology):
            yield session
    finally:
        _bootstrap.reset(token)


class ProviderUnavailable(RuntimeError):
    """A supplier has no configured/runnable discovery capability."""


class RouteBootstrap:
    def __init__(self, providers, *, catalog=None, nomination_only=False):
        self._loop = asyncio.get_running_loop()
        self._budget = current_budget()
        self._started_mono = self._loop.time()
        self._started_ms = self._elapsed_ms()
        self._finished_ms = None
        self._owners = ([PendingRouteTool(discover, name) for name, discover in providers.items()]
                        if isinstance(providers, Mapping) else
                        [provider if isinstance(provider, RouteTool) else PendingRouteTool(provider)
                         for provider in providers])
        self.providers = [(provider.name, provider) for provider in self._owners]
        self._queries, self._attempts, self._tasks = {}, [], set()
        self.topology = TopologyCache()
        self._completed_offers = {}
        self._publication_sequence = 0
        self._close_errors = []
        self._changed = asyncio.Event()
        self._closed, self._close_task = False, None
        self.revision, self.reevaluations = 0, 0
        self.quick_reevaluations = 0
        self._catalog = catalog
        self.catalog_revision = 0
        if catalog is not None:
            self.topology.catalog_changed(catalog.inventory.values())
        # A Helpers-priced consumer treats supplier snapshots as exploratory
        # inputs. Their disproof cannot invalidate independent execution results.
        self.nomination_only = nomination_only
        self._catalog_input = self._catalog_identity()
        self._catalog_load = None
        self._handled_catalog_load = None
        self.watch_catalog_load()

    def _catalog_identity(self):
        # The existing execution pool keys establish graph connectivity.
        # Observed prices, coverage, aliases and optional display metadata do
        # not change that graph or require another optimizer calculation.
        return (frozenset(pool_identity(pool) for pool in self._catalog.inventory.values())
                if self._catalog is not None else None)

    def watch_catalog_load(self):
        """Observe the registry owner's background load without owning its wait."""
        if self._closed or self._catalog is None:
            return
        task = getattr(self._catalog, 'load_task', None)
        if task is self._catalog_load:
            return
        if self._catalog_load is not None:
            self._catalog_load.remove_done_callback(self._catalog_loaded)
        self._catalog_load = task
        if task is not None:
            task.add_done_callback(self._catalog_loaded)

    def _catalog_loaded(self, task):
        if (not self._closed and task is self._catalog_load
                and task is not self._handled_catalog_load):
            self._handled_catalog_load = task
            self.refresh_catalog()

    def refresh_catalog(self):
        """Invalidate changed local graph inputs, retaining existing nominations.

        A pending calculation finishes independently; successive catalog events
        coalesce into one calculation against the latest input. Hosted queries
        have no local-graph dependency and are not repeated by this event.
        """
        if self._closed:
            return False
        if self._budget is not None and self._budget.stop.is_set():
            return False
        self.watch_catalog_load()
        current = self._catalog_identity()
        if current == self._catalog_input:
            return False
        self._catalog_input = current
        self.catalog_revision += 1
        if self._catalog is not None:
            self.topology.catalog_changed(self._catalog.inventory.values())
        for entries in self._queries.values():
            for entry in entries:
                if entry['catalog_dependent']:
                    entry['wanted_catalog'] = current
                    task = entry.get('task')
                    if task is None or (task.done() and not task.cancelled() and task.exception() is None):
                        self._start_entry(entry)
        # Existing lazy/custom queries need to revisit their older graph.
        # Before the first query there is no consumed choice to reevaluate;
        # its initial calculation will already receive this latest catalog.
        if self._queries:
            self.revision += 1
            self._changed.set()
        return True

    def _elapsed_ms(self):
        value = self._budget.elapsed() if self._budget is not None else (
            self._loop.time() - self._started_mono) * 1000
        return round(value, 3)

    @property
    def timings(self):
        """Per-provider wall timings, in the producer's existing clock.

        First-candidate is the earliest nomination. Completed/cancelled are the
        last completed/cancelled attempts; pending counts remain independent.
        Duration spans the first attempt to its latest finish (or now while a
        query is pending), not the sum of overlapping supplier query durations.
        Immediate repeatable feeds have no artificial asynchronous completion;
        feedReadMs/counts separately report their consumed enumeration work.
        Without a producer budget these coordinates start at session creation.
        """
        result = {}
        for name, _ in self.providers:
            attempts = [row for row in self._attempts if row['provider'] == name]
            started = min((row['startedMs'] for row in attempts), default=None)
            completed = max((row['completedMs'] for row in attempts if row['completedMs'] is not None), default=None)
            cancelled = max((row['cancelledMs'] for row in attempts if row['cancelledMs'] is not None), default=None)
            pending = sum(row['status'] == 'pending' for row in attempts)
            available = any(row['status'] == 'available' for row in attempts)
            end = (self._finished_ms if self._finished_ms is not None else self._elapsed_ms()) if pending or available else max(
                (value for value in (completed, cancelled) if value is not None), default=started)
            result[name] = {'started': len(attempts), 'pending': pending, 'startedMs': started,
                'firstCandidateMs': min((row['firstCandidateMs'] for row in attempts
                                         if row['firstCandidateMs'] is not None), default=None),
                'completedMs': completed, 'cancelledMs': cancelled,
                'durationMs': round(end - started, 3) if started is not None else None}
        return result

    @property
    def metrics(self):
        statuses = ('available', 'pending', 'completed', 'empty', 'unavailable', 'error',
                    'cancelled', 'stopped', 'invalidated')
        result = {}
        timings = self.timings
        for name, provider in self.providers:
            attempts = [row for row in self._attempts if row['provider'] == name]
            result[name] = {'started': len(attempts),
                **{status: sum(row['status'] == status for row in attempts) for status in statuses},
                'candidates': sum(row['candidates'] for row in attempts),
                'batches': sum(row['batches'] for row in attempts),
                'feedReads': sum(row['feedReads'] for row in attempts),
                'feedIterations': sum(row['feedIterations'] for row in attempts),
                'feedErrors': sum(row['feedErrors'] for row in attempts),
                'feedReadMs': round(sum(row['feedReadMs'] for row in attempts), 3),
                'engineAttribution': {
                    'engines': {engine: sum(row.get('engineAttribution', {}).get('engine') == engine for row in attempts)
                                for engine in ('uniroute', 'guidestar', 'unverified')},
                    'evidence': {evidence: sum(row.get('engineAttribution', {}).get('evidence') == evidence for row in attempts)
                                 for evidence in ('route-candidates', 'swap-steps', 'not-disclosed', 'ambiguous')}},
                **{key: value for key, value in timings[name].items() if key.endswith('Ms')}}
            try:
                diagnostics = getattr(provider, 'diagnostics', {})
            except Exception:
                diagnostics = {}  # Optional counters never decide quote eligibility.
            if isinstance(diagnostics, dict):
                # Each provider is request-owned. Copy aggregate counters once;
                # overlapping query-attempt snapshots must not be summed.
                result[name].update({key: diagnostics[key] for key in (
                    'workerQueries', 'quoteCallbacks', 'quoteCallbackFailures', 'quoteCallbackMs',
                    'nominationChainId', 'executionChainId')
                    if type(diagnostics.get(key)) in (int, float)})
        finished = self._finished_ms if self._finished_ms is not None else self._elapsed_ms()
        return {'queries': len(self._queries), 'revision': self.revision,
                'reevaluations': self.reevaluations, 'quickReevaluations': self.quick_reevaluations,
                'completedOffers': sum(len(rows) for rows in self._completed_offers.values()),
                'providers': result,
                'closeErrors': len(self._close_errors),
                'clock': 'producer' if self._budget is not None else 'session',
                'startedMs': self._started_ms, 'completedMs': self._finished_ms,
                'elapsedMs': round(finished - self._started_ms, 3)}

    def _raise_failure(self):
        # Preserve the existing priority of a canonical-context disproof over
        # cancellation or an otherwise completed sibling operation.
        failures = []
        for task in self._tasks:
            if task.done():
                if task.cancelled():
                    if not self._closed:
                        failures.append(asyncio.CancelledError())
                elif task.exception() is not None:
                    failures.append(task.exception())
        disproof = next((error for error in failures if isinstance(error, SnapshotChanged)), None)
        if disproof is not None and not self.nomination_only:
            raise disproof
        failures = [error for error in failures if not (self.nomination_only and isinstance(error, SnapshotChanged))]
        if failures:
            raise failures[0]

    def candidates(self, source, target, amount, block, *, path_projection=None):
        """Backward-compatible branch-only view of completed nominations."""
        return [offer['branches'] for offer in self.offers(source, target, amount, block,
                                                          path_projection=path_projection)]

    def offers(self, source, target, amount, block, *, path_projection=None):
        """Start suppliers; fairly consume immediate/completed nominations.

        Origins neither authorize a candidate nor change query sharing/ranking.
        Duplicate nominations retain each supplier for the consumer to combine.
        """
        return round_robin(self.offer_feeds(source, target, amount, block, path_projection=path_projection))

    def publish_completed(self, query, route, origins=()):
        """Share completed path topology, never its simulated price or bank.

        Recording a prefix does not start a tool query. Replaying the same
        shape only merges diagnostic origins, preventing arrival feedback.
        """
        if self._closed or (self._budget is not None and self._budget.stop.is_set()):
            return False
        topology = []
        for hop in route:
            if 'pool' not in hop:
                topology.append({'kind': hop['kind'], 'currencyOut': hop['currencyOut']})
                continue
            pool = {key: deepcopy(hop['pool'][key]) for key in (
                'id', 'protocol', 'address', 'poolManager', 'feePips', 'tickSpacing', 'hooks')
                if key in hop['pool']}
            for token in ('token0', 'token1'):
                pool[token] = {key: deepcopy(hop['pool'][token][key]) for key in (
                    'address', 'chainId', 'decimals') if key in hop['pool'][token]}
            topology.append({'pool': pool, 'zeroForOne': hop['zeroForOne']})
        key = query.source.lower(), query.target.lower(), int(query.amount)
        rows = self._completed_offers.setdefault(key, {})
        identity, names = route_identity(topology), origin_names(origins)
        if identity in rows:
            offer = rows[identity][1]
            offer['origins'].extend(name for name in names if name not in offer['origins'])
            return False
        offer = {'branches': [{'amountIn': str(query.amount), 'hops': topology}], 'origins': names}
        self._publication_sequence += 1
        rows[identity] = self._publication_sequence, offer
        # Future consumers read this ready hint when they first ask. Only a
        # query already consumed by this search has an older choice to revisit.
        if key in self._queries:
            self.revision += 1
            self._changed.set()
        return True

    def offer_feeds(self, source, target, amount, block, *, path_projection=None,
                    cooperative=False, projection_steps=None):
        """Start all pending tools now; return their separate lazy offer feeds."""
        self._raise_failure()
        if self._closed:
            return []
        key = source.lower(), target.lower(), int(amount)
        if key not in self._queries:
            self._queries[key] = []
            query = RouteQuery(*key, block)
            for name, provider in self.providers:
                entry = {'provider': provider, 'name': name, 'query': query, 'offers': [], 'offer_revisions': [],
                         'catalog_dependent': getattr(provider, 'catalog_dependent', False),
                         'wanted_catalog': self._catalog_input, 'task': None}
                self._queries[key].append(entry)
                self._start_entry(entry)
        def copied(rows):
            snapshot = list(rows)
            def steps():
                for row in snapshot:
                    if cooperative:
                        yield CHECKPOINT
                    yield deepcopy(row)
            return steps()
        regular = [round_robin((self._available(entry, path_projection, cooperative=cooperative,
                                             projection_steps=projection_steps), copied(entry['offers'])))
                   for entry in self._queries[key] if entry.get('feed') is not None]
        if key in self._completed_offers:
            regular.insert(0, copied([offer for _, offer in self._completed_offers[key].values()]))
        quick = _quick_offers.get()
        # A quick whole-plan pass tries ready nominations before re-entering
        # lazy custom tails. Every ordinary feed remains available afterward.
        # Publication order belongs to this session, never to supplier metadata.
        prefix = ([iter((deepcopy(offer),)) for offer in quick[1].get(key, ())]
                  if quick is not None and quick[0] is self else [])
        return prefix + regular

    def _ready_offers(self):
        result = {}
        for key in dict.fromkeys((*self._queries, *self._completed_offers)):
            entries = self._queries.get(key, ())
            rows = [(revision, offer) for entry in entries
                    for revision, offer in zip(entry['offer_revisions'], entry['offers'], strict=True)]
            rows.extend(self._completed_offers.get(key, {}).values())
            result[key] = [deepcopy(offer) for _, offer in sorted(rows, key=lambda row: row[0], reverse=True)]
        return result

    async def _quick_pass(self, callback, offers):
        token = _quick_offers.set((self, offers))
        try:
            return await callback()
        finally:
            _quick_offers.reset(token)

    def _start_entry(self, entry):
        attempt = {'provider': entry['name'], 'status': 'pending', 'candidates': 0, 'batches': 0,
            'startedMs': self._elapsed_ms(), 'firstCandidateMs': None,
            'completedMs': None, 'cancelledMs': None,
            'feedReads': 0, 'feedIterations': 0, 'feedReadMs': 0.0, 'feedErrors': 0}
        self._attempts.append(attempt)
        entry['attempt'] = attempt
        entry['started_catalog'] = entry['wanted_catalog']
        try:
            feed = entry['provider'].discover(entry['query'])
            entry['feed'] = feed
            if feed.pending is None and getattr(feed, 'updates', None) is None:
                attempt['status'] = 'available'
            else:
                task = asyncio.create_task(self._discover(feed, entry, attempt))
                entry['task'] = task
                self._tasks.add(task)
                task.add_done_callback(lambda done: self._completed(done, attempt, entry))
        except SnapshotChanged:
            if not self.nomination_only:
                raise
            attempt['status'] = 'invalidated'
            attempt['completedMs'] = self._elapsed_ms()
        except Exception as error:
            attempt['status'] = 'unavailable' if isinstance(error, ProviderUnavailable) else 'error'
            attempt['completedMs'] = self._elapsed_ms()

    def _available(self, entry, path_projection=None, *, cooperative=False, projection_steps=None):
        attempt = entry['attempt']
        attempt['feedIterations'] += 1
        iterator = None
        try:
            iterator = iter(entry['feed'].available_steps(path_projection, projection_steps) if cooperative
                            else entry['feed'].available_projected(path_projection))
            while True:
                started = self._loop.time()
                try:
                    with origin_scope(attempt['provider']):
                        candidate = next(iterator)
                except StopIteration:
                    return
                finally:
                    attempt['feedReadMs'] += (self._loop.time() - started) * 1000
                if candidate is CHECKPOINT:
                    yield CHECKPOINT
                    continue
                attempt['feedReads'] += 1
                attempt['candidates'] += 1
                if attempt['firstCandidateMs'] is None:
                    attempt['firstCandidateMs'] = self._elapsed_ms()
                yield {'branches': deepcopy(candidate), 'origins': [attempt['provider']]}
        except SnapshotChanged:
            if not self.nomination_only:
                raise
            attempt['feedErrors'] += 1
        except Exception:
            attempt['feedErrors'] += 1
        finally:
            close = getattr(iterator, 'close', None)
            if close is not None:
                try:
                    close()
                except SnapshotChanged:
                    if not self.nomination_only:
                        raise
                    attempt['feedErrors'] += 1
                except Exception:
                    attempt['feedErrors'] += 1

    def _publish_batch(self, response, entry, attempt):
        rows = deepcopy(list(response))
        attribution = getattr(response, 'engine_attribution', None)
        if isinstance(attribution, dict):
            attempt['engineAttribution'] = {
                'engine': attribution.get('engine') if attribution.get('engine') in (
                    'uniroute', 'guidestar', 'unverified') else 'unverified',
                'evidence': attribution.get('evidence') if attribution.get('evidence') in (
                    'route-candidates', 'swap-steps', 'not-disclosed', 'ambiguous') else 'not-disclosed'}
        attempt['batches'] += 1
        attempt['candidates'] += len(rows)
        if rows:
            if attempt['firstCandidateMs'] is None:
                attempt['firstCandidateMs'] = self._elapsed_ms()
            self.revision += 1
            self._publication_sequence += 1
            entry['offers'].extend({'branches': row, 'origins': [attempt['provider']]} for row in rows)
            entry['offer_revisions'].extend([self._publication_sequence] * len(rows))
            self._changed.set()

    async def _discover(self, feed, entry, attempt):
        try:
            with origin_scope(attempt['provider']):
                async for response in async_batches(feed):
                    self._publish_batch(response, entry, attempt)
            attempt['status'] = 'completed' if attempt['candidates'] else 'empty'
        except ProviderUnavailable:
            attempt['status'] = 'unavailable'
        except SnapshotChanged:
            attempt['status'] = 'invalidated'
            if not self.nomination_only:
                raise
        except asyncio.CancelledError:
            attempt['status'] = 'cancelled'
            attempt['cancelledMs'] = self._elapsed_ms()
            raise
        except SearchStopped:
            attempt['status'] = 'stopped'
            raise
        except Exception:
            # Supplier text may contain an HTTP URL/key or subprocess stderr.
            # Only its ordinary outcome belongs in the shared quote metrics.
            attempt['status'] = 'error'
        finally:
            if attempt['status'] != 'cancelled':
                attempt['completedMs'] = self._elapsed_ms()

    def _completed(self, task, attempt, entry):
        if task.cancelled():
            attempt['status'] = 'cancelled'
            if attempt['cancelledMs'] is None:
                attempt['cancelledMs'] = self._elapsed_ms()
        else:
            failure = task.exception()  # Retrieve failures even if already draining.
            if (not self._closed and failure is None and entry.get('task') is task
                    and not (self._budget is not None and self._budget.stop.is_set())
                    and entry['catalog_dependent']
                    and entry['wanted_catalog'] != entry['started_catalog']):
                self._start_entry(entry)
        self._changed.set()

    async def run(self, ordinary, reevaluate, *, quick=None):
        """Keep ordinary completion independent and consume late arrivals."""
        ordinary_task = asyncio.create_task(ordinary)
        round_task, changed_task = None, None
        completed_revision, round_revision = 0, 0
        quick_tasks, quick_revision = set(), 0
        budget = current_budget()
        stopped = asyncio.create_task(budget.stop.wait()) if budget is not None else None
        result = None
        try:
            while True:
                # A load can have published while its done callback is still
                # queued behind this continuation. Consume that existing event
                # before deciding the request has no remaining work.
                if (self._catalog_load is not None and self._catalog_load.done()
                        and self._catalog_load is not self._handled_catalog_load):
                    self._catalog_loaded(self._catalog_load)
                self._raise_failure()
                if ordinary_task.done():
                    result = await ordinary_task
                if round_task is not None and round_task.done():
                    await round_task
                    completed_revision = round_revision
                    round_task = None
                for task in tuple(quick_tasks):
                    if task.done():
                        await task
                        quick_tasks.remove(task)
                if stopped is not None and stopped.done():
                    raise SearchStopped()
                if quick is not None and self.revision > quick_revision:
                    quick_revision = self.revision
                    self.quick_reevaluations += 1
                    quick_tasks.add(asyncio.create_task(self._quick_pass(quick, self._ready_offers())))
                if round_task is None and self.revision > completed_revision:
                    round_revision = self.revision
                    self.reevaluations += 1
                    round_task = asyncio.create_task(reevaluate())
                providers_pending = any(not task.done() for task in self._tasks)
                if ordinary_task.done() and round_task is None and not quick_tasks and not providers_pending:
                    self._raise_failure()
                    return result
                self._changed.clear()
                changed_task = asyncio.create_task(self._changed.wait())
                waiters = {changed_task, *quick_tasks}
                if not ordinary_task.done():
                    waiters.add(ordinary_task)
                if round_task is not None:
                    waiters.add(round_task)
                if stopped is not None:
                    waiters.add(stopped)
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                changed_task.cancel()
                await asyncio.gather(changed_task, return_exceptions=True)
                changed_task = None
        finally:
            owned = [task for task in (ordinary_task, round_task, changed_task, stopped) if task is not None]
            owned.extend(quick_tasks)
            for task in owned:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*owned, return_exceptions=True)
            try:
                await self.close()
            except SnapshotChanged as error:
                outcomes.append(error)
            disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
            if disproof is not None and not self.nomination_only:
                raise disproof

    async def _close(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*self._tasks, return_exceptions=True)
        for entries in self._queries.values():
            for entry in entries:
                operation = entry['feed'].pending if entry.get('feed') is not None else None
                if iscoroutine(operation):
                    # A task cancelled before its first turn never awaited the
                    # feed's coroutine. Close that owned pending object too.
                    operation.close()
                updates = getattr(entry['feed'], 'updates', None) if entry.get('feed') is not None else None
                close = getattr(updates, 'aclose', None)
                if close is not None:
                    try:
                        await close()
                    except BaseException as error:
                        outcomes.append(error)
        async def close_provider(provider):
            close = getattr(provider, 'close', None)
            if close is not None:
                value = close()
                if isawaitable(value):
                    await value
        outcomes.extend(await asyncio.gather(*(close_provider(provider) for provider in self._owners),
                                            return_exceptions=True))
        self._close_errors = [error for error in outcomes if isinstance(error, Exception)
                              and (self.nomination_only or not isinstance(error, SnapshotChanged))]
        self._finished_ms = self._elapsed_ms()
        self.topology.clear()
        disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
        if disproof is not None and not self.nomination_only:
            raise disproof

    async def close(self):
        if self._close_task is None:
            self._closed = True
            if self._catalog_load is not None:
                self._catalog_load.remove_done_callback(self._catalog_loaded)
                self._catalog_load = None
            self._close_task = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise

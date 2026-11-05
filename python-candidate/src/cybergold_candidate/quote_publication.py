"""Backend candidate reconciliation and publication of selected whole quotes."""
import asyncio
from copy import deepcopy

from .quoter.reuse_routes import funded_route_identity
from .quoter.quote_book import QuoteBook
from .quote_flow import stage


class CanonicalPublication:
    def __init__(self, quoter, request, publish, *, refresh=False, cache=None):
        self.quoter, self.request, self.publish = quoter, request, publish
        self.refresh, self.cache = refresh, cache
        self.queue = asyncio.Queue()
        registry = getattr(getattr(quoter, 'engine', None), 'registry', None)
        self.book = QuoteBook(request, refresh=refresh, seed=getattr(registry, 'seed', None))
        self.best = None
        self.closed = False
        self.private_observations = False
        self.context = self.disproof = None
        self.book.on_observation = self._accept_observation
        self.book.on_history = self._accept_history
        if cache is not None:
            cache.bind(self.book)

    def _current(self, frame):
        frame = {**frame, '_candidateIdentity': frame.get('_candidateIdentity') or funded_route_identity(frame['value'])}
        if self.cache is not None:
            self.cache.announce(frame)
        else:
            self._accept_observation(frame, max(self.book.versions.values(), default=0) + 1)

    def _accept_observation(self, frame, version):
        with stage('publication.reconcile', kind='cpu'):
            if frame.get('type') == 'candidate-repriced':
                self.private_observations = True
            value, identity = frame['value'], frame['_candidateIdentity']
            replaces = frame.get('_replacesIdentity')
            self.book.versions[identity] = version
            if replaces is not None:
                self.book.versions[replaces] = version
            previous = self.book.winner()
            self.book.observe(value, identity=identity, replaces=replaces)
            if self.cache is not None:
                if replaces is not None:
                    self.cache.forget_pending(replaces)
                if value is None:
                    self.cache.forget_pending(identity)
            if value is not None:
                self.context = deepcopy(value['context'])
            elif previous is not None:
                self.disproof = deepcopy(previous['context'])
            self._remember_families()
            self.queue.put_nowait(('changed', None))

    def _accept_history(self, value, sequence):
        with stage('publication.reconcile', kind='cpu'):
            if self.book.observe(value, current=False, sequence=sequence):
                self.queue.put_nowait(('changed', None))

    def _historical(self, value):
        with stage('publication.reconcile', kind='cpu'):
            try:
                observation = self.cache.historical_observation(value) if self.cache is not None else (value, None)
                if observation is not None:
                    self.book.observe(observation[0], current=False, sequence=observation[1])
            except (KeyError, TypeError, ValueError):
                pass  # An incomplete old cache row cannot interrupt ordinary search.

    def _remember_families(self):
        if self.cache is not None:
            for value, current in self.book.family_values().values():
                if current:
                    self.cache.remember(value, version=self.book.versions.get(funded_route_identity(value)))

    async def observe_family(self, value):
        if funded_route_identity(value) not in self.book.observed:
            await self.enqueue({'type': 'candidate-repriced', 'value': value})

    async def enqueue(self, frame):
        if self.closed:
            return
        if frame['type'] == 'candidate-repriced':
            self._current(frame)
        elif frame['type'] == 'qualified':
            # Legacy/scripted producers retain their ordinary callback. Real
            # Quoter observations enter through the private on_candidate hook.
            previous = self.book.rows.get(funded_route_identity(frame['value']))
            if previous is None or previous[0] != frame['value']:
                self._current(frame)
            self.queue.put_nowait(('changed', None))
        elif frame['type'] == 'upper-replay-settled':
            self.queue.put_nowait(('upper-replay-settled', None))

    async def run(self):
        while True:
            with stage('publication.queue', kind='queue'):
                item = await self.queue.get()
            if item is None:
                break
            kind, value = item
            if self.closed:
                continue
            if kind == 'upper-replay-settled':
                with stage('publication.publish', kind='await'):
                    await self.publish({'type': kind})
                continue
            if kind == 'stored':
                self._historical(value)
            elif kind == 'stored-batch':
                for observation in value:
                    self._historical(observation)
            elif kind == 'candidate':
                self._current({'value': value})
            elif kind == 'terminal':
                if not self.private_observations or funded_route_identity(value) not in self.book.observed:
                    self._current({'value': value})
                else:
                    self.book.finish(value)
                self._remember_families()
            await self.publish_selected()

    async def publish_selected(self):
        with stage('publication.reconcile', kind='cpu'):
            winner = self.book.winner()
            if winner == self.best and not (winner is None and self.disproof is not None):
                return
            previous, self.best = self.best, winner
        if winner is not None:
            with stage('publication.publish', kind='await'):
                await self.publish({'type': 'qualified', 'value': deepcopy(winner)})
        elif previous is not None or self.disproof is not None:
            with stage('publication.publish', kind='await'):
                await self.publish({'type': 'invalidated', 'context': deepcopy(
                    previous['context'] if previous is not None else self.disproof)})
            self.disproof = None

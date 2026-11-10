"""Operation-owned whole candidates; current observations replace their own history."""
from copy import deepcopy

from .path_families import quote_path_family
from .provenance import merge_origins
from .ranking import prefer_completed
from .reuse_estimate import attach_reuse_sample
from .reuse_routes import funded_route_identity
from .dormant_routes import with_dormant_routes
from .pool_directions import conflicting_pool, quote_directions


class QuoteBook:
    def __init__(self, request, *, refresh=False, seed=None):
        self.request, self.refresh = request, refresh
        self.seed = seed
        self.rows, self.observed = {}, set()
        self.versions, self.history_versions = {}, {}
        self.on_observation = self.on_history = None

    def preferred(self, value, previous):
        return prefer_completed(value, previous, scalar=self.request['intent'] in (0, 1),
                                basket=self.request['intent'] >= 2)

    def fits(self, value):
        inputs, maximum = value['inputs'], self.request['inputs']
        return len(inputs) == len(maximum) and all(
            row['currency'].lower() == budget['currency'].lower()
            and int(row['amount']) <= int(budget['amount'])
            for row, budget in zip(inputs, maximum, strict=True))

    def observe(self, value, *, identity=None, replaces=None, current=True, sequence=None):
        identity = identity or funded_route_identity(value)
        if value is not None and conflicting_pool(quote_directions(value)) is not None:
            if not current:
                return False
            value = None
        if not current:
            if identity in self.observed or not self.fits(value):
                return False
            if identity in self.rows:
                previous = self.rows[identity][0]
                old_sequence = self.history_versions.get(identity)
                if sequence is not None and (old_sequence is None or sequence > old_sequence):
                    self.rows[identity] = (deepcopy(value), False)
                    self.history_versions[identity] = sequence
                    return True
                before = deepcopy(previous)
                merge_origins(previous, value)
                return before != previous
        else:
            self.observed.add(identity)
            if replaces is not None:
                self.observed.add(replaces)
                self.rows.pop(replaces, None)
            if value is not None and not self.fits(value):
                self.rows.pop(identity, None)
                return True
        if value is None:
            self.rows.pop(identity, None)
        else:
            self.rows[identity] = (deepcopy(value), current)
            if not current:
                self.history_versions[identity] = sequence
        return True

    def family_values(self):
        selected = {}
        for value, current in self.rows.values():
            family = quote_path_family(value)
            previous = selected.get(family)
            if self.preferred(value, previous[0] if previous else None):
                selected[family] = (value, current)
        return selected

    def winner(self):
        selected, current = None, False
        for value, observed in self.rows.values():
            if self.preferred(value, selected):
                selected, current = value, observed
        if selected is None:
            return None
        value = attach_reuse_sample(with_dormant_routes(selected, self.seed))
        value['request'] = deepcopy(self.request)
        value['observation'] = {'source': 'search' if current else 'stored', 'refresh': self.refresh if current else False}
        return value

    def finish(self, value):
        """The greedy inner return cannot restore an already-repriced old value."""
        identity = funded_route_identity(value)
        if identity not in self.observed:
            self.observe(value, identity=identity)
            return
        previous = self.rows.get(identity)
        if previous is not None:
            merge_origins(previous[0], value)
            if (previous[0]['inputs'] == value['inputs']
                    and previous[0]['quotedOutput'] == value['quotedOutput']
                    and value.get('metrics') is not None):
                previous[0]['metrics'] = deepcopy(value['metrics'])

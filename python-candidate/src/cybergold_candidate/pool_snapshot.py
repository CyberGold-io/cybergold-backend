"""Caller-owned pool copies, separated from observation acquisition and IO."""
from copy import deepcopy

from .quote_flow import stage
from .prepared_values import freeze


def copy_pool_descriptor(pool):
    with stage('topology.clone', kind='cpu'):
        return deepcopy(pool)


def copy_pool_state(state):
    with stage('state.clone', kind='cpu'):
        return deepcopy(state)


def copy_pool_snapshot(snapshot):
    """Own scalar coverage rows and deep-copy all other pool metadata."""
    with stage('state.clone', kind='cpu'):
        coverage = ('bitmapWords', 'ticks')
        result = deepcopy({key: value for key, value in snapshot.items() if key not in coverage})
        for key in coverage:
            if key in snapshot:
                result[key] = [dict(row) for row in snapshot[key]]
        return {key: result[key] for key in snapshot}


def copy_pool_bank(bank):
    return {identity: copy_pool_snapshot(state) for identity, state in bank.items()}


def private_pool_snapshot(snapshot):
    """Private scalar overlay sharing only captured immutable nested values."""
    with stage('state.clone', kind='cpu'):
        return {key: freeze(value) for key, value in snapshot.items()}


def fork_pool_bank(bank):
    return PrivatePoolBank(bank)


class PrivatePoolBank(dict):
    """Internal simulation overlays; ordinary dict arguments remain mutable exports."""
    def __init__(self, values=()):
        super().__init__((key, private_pool_snapshot(value)) for key, value in dict(values).items())

def bank_snapshot(bank, state):
    return private_pool_snapshot(state) if isinstance(bank, PrivatePoolBank) else copy_pool_snapshot(state)


def merge_private_coverage(target, incoming):
    for field, key in (('bitmapWords', 'wordPosition'), ('ticks', 'index')):
        if field not in incoming:
            continue
        current, added = target.get(field), incoming[field]
        if current is added:
            continue
        added = freeze(added)
        if current is None:
            target[field] = added
            continue
        current = freeze(current)
        if current.content_key == added.content_key:
            target[field] = current
            continue
        rows = {int(row[key]): row for row in added}
        rows.update({int(row[key]): row for row in current})
        target[field] = freeze(list(rows.values()))

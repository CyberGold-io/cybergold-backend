"""Caller-owned pool copies, separated from observation acquisition and IO."""
from copy import deepcopy

from .quote_flow import stage


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

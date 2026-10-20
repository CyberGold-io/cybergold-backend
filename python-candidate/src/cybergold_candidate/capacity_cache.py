"""Bounded memoization of capacity facts calculated from verified state.

This bank does not acquire state, extend its age, or store failures. In
particular, a prior Sandbox block hash does not make an observation current:
callers must supply freshly observed values before reusing a calculated fact.
"""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json


class VerifiedCapacityCache:
    def __init__(self, limit=256):
        self.limit, self.completed = limit, OrderedDict()

    def get(self, key):
        if key not in self.completed:
            return None
        self.completed.move_to_end(key)
        return deepcopy(self.completed[key])

    def remember(self, key, value):
        """Publish only a successfully verified capacity or arithmetic result."""
        self.completed[key] = deepcopy(value)
        self.completed.move_to_end(key)
        while len(self.completed) > self.limit:
            self.completed.popitem(last=False)
        return deepcopy(value)

    def clear(self):
        self.completed.clear()


def capacity_key(namespace, *, chain, block, identity, facts):
    """An exact content identity; context must already be verified by its caller."""
    content = json.dumps({'identity': identity, 'facts': facts}, sort_keys=True, separators=(',', ':'))
    return namespace, int(chain), block['hash'].lower(), sha256(content.encode()).hexdigest()


def pool_capacity_facts(snapshot):
    """SDK input state without display timestamps or acquisition bookkeeping."""
    result = deepcopy({key: value for key, value in snapshot.items() if key not in ('context', 'acquisition')})
    if 'bitmapWords' in result:
        result['bitmapWords'].sort(key=lambda row: int(row['wordPosition']))
    if 'ticks' in result:
        result['ticks'].sort(key=lambda row: int(row['index']))
    return result


_core_capacity = VerifiedCapacityCache()


def core_capacity_facts(values, issuance_fee=0, helper_fee=0):
    """Reuse math only after the request has freshly established its inputs."""
    supply, maximum, effective = values
    key = (supply, maximum, effective, issuance_fee, helper_fee)
    result = _core_capacity.get(key)
    if result is None:
        limit = min(maximum, effective)
        gross = max(0, limit-supply)
        core_net = gross-gross*issuance_fee//1_000_000
        result = _core_capacity.remember(key, {
            'currentSupplyRaw': str(supply), 'limitRaw': str(limit),
            'limitKind': 'maximum-total-supply' if maximum <= effective else 'effective-supply-cap',
            'remainingGrossCapacity': str(gross),
            'remainingNetCapacity': str(core_net-core_net*helper_fee//1_000_000)})
    return result

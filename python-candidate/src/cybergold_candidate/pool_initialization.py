"""Request-local initialization facts from canonical pool observations only."""
from .search_observations import current_search_observations
from .uniswap_routes import pool_identity


def _key(registry, pool, block, generation):
    return (id(registry), registry.chain, generation, block['hash'], pool_identity(pool))


def _authority(registry, pool):
    if pool['protocol'] == 'v4':
        return (pool.get('poolManager') or getattr(registry.get_rpc(), 'pool_manager', '')).lower()
    return (pool.get('address') or '').lower()


def record_pool_initialization(registry, state, block, generation, *, requested=None):
    """A successful getter, not a descriptor or private post-state, supplies this fact."""
    observations = current_search_observations()
    if observations is None or state['protocol'] not in ('v3', 'v4'):
        return
    value = state.get('sqrtRatioX96')
    if type(value) not in (int, str):
        return
    try:
        zero = int(value) == 0
    except ValueError:
        return
    facts = observations.pool_initializations.setdefault(_key(registry, state, block, generation), {})
    facts[_authority(registry, state)] = zero
    if state['protocol'] == 'v3' and requested is not None and not requested.get('address'):
        # This producer actually resolved the address-less factory alias.
        facts[''] = zero


def observed_uninitialized(registry, pool, block):
    """Unknown state remains eligible; initialized pools need no active liquidity."""
    observations = current_search_observations()
    if (observations is None or not observations.pool_initializations
            or pool['protocol'] not in ('v3', 'v4')):
        return False
    facts = observations.pool_initializations.get(
        _key(registry, pool, block, getattr(registry, 'generation', None)), {})
    authority = _authority(registry, pool)
    if authority or pool['protocol'] == 'v4':
        return facts.get(authority, False)
    # Only the producer that resolved this factory alias can disprove it.
    # Conflicting explicit-address facts retain the unknown alias as well.
    return facts.get('', False) and all(facts.values())

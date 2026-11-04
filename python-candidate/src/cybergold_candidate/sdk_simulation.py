"""Share exact SDK arithmetic inside one search, including acquired coverage."""
from copy import deepcopy
import json

from .route_work_slots import engine_work, required_state_wait
from .search_observations import current_search_observations


async def simulate_sdk(engine, payload, on_state):
    observations = current_search_observations()
    if observations is None:
        return await engine.sdk.request(payload, on_state=on_state)

    # These are the actual observed/private scalars, coverage, allocation and
    # direction sent to the arithmetic worker, not just an executable path.
    identity = ('exact-sdk-payload', id(engine.sdk),
                json.dumps(payload, sort_keys=True, separators=(',', ':')))
    produced = False

    async def calculate():
        nonlocal produced
        produced = True
        demands = []
        async def acquire(requests):
            demands.append(deepcopy(requests))
            return await on_state(requests)
        # The shared task owns its pricing capacity. It must not inherit a
        # subscriber's permit while that subscriber is parked or cancelled.
        async with engine_work(engine.semaphore):
            value = await engine.sdk.request(payload, on_state=acquire)
        return {'value': value, 'demands': demands}

    async with required_state_wait():
        result = await observations.read(identity, calculate)
        if not produced:
            # V3 postState omits canonical coverage. Replaying the successful
            # demands supplies each caller's isolated snapshot/candidate bank.
            for requests in result['demands']:
                await on_state(requests)
    return result['value']

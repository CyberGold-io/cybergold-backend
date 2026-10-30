"""Owned optional Market work, alongside unchanged ordinary candidate jobs."""
import random

from ..quote_budget import current_budget
from ..recovery_rpc import SnapshotChanged
from ..route_scheduler import schedule_routes
from .amm import PartialPath
from .contracts import capture_paths
from .discovery import families, market_plan, route_identity
from .policy import dominated, output_upper_bound
from .prefix import repair_prefix


async def explore(quoter, request, block, session, evaluate, incumbent, *, observations,
                  seeded=False, core_only=False):
    if core_only or request['intent'] not in (0, 1):
        return
    source, target = request['inputs'][0]['currency'], request['outputCurrency']
    amount = int(request['inputs'][0]['amount'])
    if seeded:
        await session.seed_done.wait()

    def feeds(expanded):
        groups = families(quoter.engine.registry, source, target, quoter.core)
        if seeded:
            rng = random.Random(session.random_seed)
            for _, routes in groups:
                rng.shuffle(routes)
            rng.shuffle(groups)
        async def feed(routes):
            for route in routes:
                if session.starts >= session.limit:
                    break
                identity = route_identity(route)
                if identity not in session.resolved:
                    yield identity, route
        return [feed(routes) for _, routes in groups]

    async def one(_index, item):
        identity, route = item
        if identity in session.resolved:
            return
        session.resolved.add(identity)
        bound = output_upper_bound(quoter.engine.registry, request, route, block, observations=observations)
        if dominated(bound, incumbent()):
            session.pruned += 1
            return
        if not session.claim():
            return
        session.started.add(identity)
        try:
            with capture_paths():
                await evaluate(0, 'core-first', False, selected=market_plan(source, target, route, amount),
                    phase='route-family-exploration' if seeded else 'route-family', partial=True)
        except PartialPath as error:
            # Inline in the parent lease: no nested scheduler permit wait.
            if not session.claim():
                return
            proposal = await repair_prefix(quoter, request, error.trace, block)
            if proposal is not None:
                funding, plan = proposal
                session.repairs += 1
                await evaluate(0, 'core-first', False, selected=plan, funding=funding, phase='backward-prefix')

    async def optional(_index, item):
        try:
            await one(_index, item)
        except SnapshotChanged:
            raise
        except Exception:
            pass  # An optional failed path cannot remove ordinary alternatives.

    try:
        await current_budget().discovery(schedule_routes(feeds, optional,
            discover=session.discovery_done.wait, limit=8))
    except SnapshotChanged:
        raise
    except Exception:
        pass

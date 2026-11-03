"""Owned optional Market work, alongside unchanged ordinary candidate jobs."""
import random

from ..quote_budget import current_budget
from ..quote_errors import QuoteFailure
from ..market_fee import get_market_fee_rate, routed_sell_budget
from ..route_scheduler import schedule_routes
from .amm import PartialPath
from .contracts import capture_paths
from .discovery import market_plan, route_identity
from .prefix import repair_prefix


async def explore(quoter, request, block, session, evaluate, incumbent, *, observations,
                  seeded=False, core_only=False):
    if core_only or request['intent'] not in (0, 1):
        return
    source, target = request['inputs'][0]['currency'], request['outputCurrency']
    amount = int(request['inputs'][0]['amount'])

    async def feeds(expanded):
        groups = await quoter.amm.async_family_offers(source, target, amount, block)
        if seeded:
            rng = random.Random(session.random_seed)
            for _, routes in groups:
                rng.shuffle(routes)
            rng.shuffle(groups)
        async def feed(routes):
            for route, origins in routes:
                identity = route_identity(route)
                if identity not in session.resolved:
                    yield identity, route, origins
        return [feed(routes) for _, routes in groups]

    async def one(_index, item):
        identity, route, origins = item
        if identity in session.resolved or identity in session.pending:
            return
        session.pending.add(identity)
        # SDK-head bounds cannot disprove a latest Helpers-priced quote.
        # Supplier topology remains eligible for execution simulation.
        session.claim()
        session.started.add(identity)
        try:
            with capture_paths():
                try:
                    value = await evaluate(0, 'core-first', False, selected=market_plan(source, target, route, amount, origins=origins),
                        phase='route-family-exploration' if seeded else 'route-family', partial=True)
                    if value is not None:
                        session.resolved.add(identity)
                except QuoteFailure as error:
                    if error.code != 'quote-contract-reverted':
                        raise
                    # Explore why this new path cannot settle, so the existing
                    # backward-prefix producer can construct a different plan.
                    rate = get_market_fee_rate(quoter.engine.registry.chain, source, target, 'exact-in')
                    funding = amount - routed_sell_budget(amount, rate)[1] if request['intent'] == 1 else amount
                    await quoter.price_path(route, funding, block, {}, observations)
        except PartialPath as error:
            # Inline in the parent lease: no nested scheduler permit wait.
            session.claim()
            proposal = await repair_prefix(quoter, request, error.trace, block, origins=origins)
            if proposal is not None:
                funding, plan = proposal
                session.repairs += 1
                await evaluate(0, 'core-first', False, selected=plan, funding=funding, phase='backward-prefix')
        finally:
            session.pending.discard(identity)

    async def optional(_index, item):
        try:
            await one(_index, item)
        except Exception:
            pass  # An optional failed path cannot remove ordinary alternatives.

    try:
        await current_budget().discovery(schedule_routes(feeds, optional,
            discover=session.discovery_done.wait, limit=8))
    except Exception:
        pass

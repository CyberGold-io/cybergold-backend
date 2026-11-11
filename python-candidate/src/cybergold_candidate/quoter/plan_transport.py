"""Whole-plan scheduling, search-local sharing and one actual Helpers RPC.

Compilation and result projection are separate synchronous modules. A sharing
wait is not another physical call and retains the issuing owner's flow clock.
"""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json

from ..quote_flow import current_flow, stage
from ..route_work_slots import engine_work
from ..shared_reads import SharedReads
from .plan_call import preparation_scope
from .plan_call_diagnostics import PlanCallCensus, observe


_reads = ContextVar('completed_plan_simulations', default=None)
_census = ContextVar('plan_call_census', default=None)


@asynccontextmanager
async def simulation_scope():
    reads = SharedReads()
    token = _reads.set(reads)
    flow = current_flow()
    census = PlanCallCensus(reads.max_completed) if flow is not None else None
    census_token = _census.set(census)
    try:
        with preparation_scope():
            yield
    finally:
        try:
            with stage('search.cleanup'):
                await reads.close()
        finally:
            if census is not None:
                flow.helpers_calls = observe(census.snapshot)
            _census.reset(census_token)
            _reads.reset(token)


async def execute_plan_call(rpc, params, *, semaphore, now, shared):
    reads = _reads.get() if shared else None
    census = _census.get()
    wire = json.dumps(params, sort_keys=True) if reads is not None or census is not None else None

    async def send():
        with stage('helpers.rpc'):
            if census is not None:
                census.started += 1
            # Hash only provider dispatches after Helpers sharing, not its hits.
            identity = observe(lambda: census.identity(rpc.w3.provider, wire, params, shared)) if census is not None else None
            try:
                response = await rpc.w3.provider.make_request('eth_call', params)
            except BaseException as error:
                if census is not None:
                    observe(lambda: census.exception(error))
                raise
            if identity is not None:
                observe(lambda: census.response(identity, response))
            return response

    async def execute():
        if semaphore is None:
            response = await send()
        else:
            async with engine_work(semaphore, stage_name='helpers.permit'):
                response = await send()
        return {**response, 'observedAt': now()}

    counts = {'issued': 1, 'coalesced': 0, 'reused': 0}
    if reads is None:
        return await execute(), counts

    async def produce(_keys):
        return [await execute()]

    with stage('helpers.shared'):
        responses, counts = await reads.many([wire], produce, retain=True)
    return responses[0], counts

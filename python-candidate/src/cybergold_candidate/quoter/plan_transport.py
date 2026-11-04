"""Whole-plan scheduling, search-local sharing and one actual Helpers RPC.

Compilation and result projection are separate synchronous modules. A sharing
wait is not another physical call and retains the issuing owner's flow clock.
"""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json

from ..quote_flow import stage
from ..route_work_slots import engine_work
from ..shared_reads import SharedReads


_reads = ContextVar('completed_plan_simulations', default=None)


@asynccontextmanager
async def simulation_scope():
    reads = SharedReads()
    token = _reads.set(reads)
    try:
        yield
    finally:
        with stage('search.cleanup'):
            await reads.close()
        _reads.reset(token)


async def execute_plan_call(rpc, params, *, semaphore, now, shared):
    async def send():
        with stage('helpers.rpc'):
            return await rpc.w3.provider.make_request('eth_call', params)

    async def execute():
        if semaphore is None:
            response = await send()
        else:
            async with engine_work(semaphore, stage_name='helpers.permit'):
                response = await send()
        return {**response, 'observedAt': now()}

    reads = _reads.get() if shared else None
    counts = {'issued': 1, 'coalesced': 0, 'reused': 0}
    if reads is None:
        return await execute(), counts

    async def produce(_keys):
        return [await execute()]

    with stage('helpers.shared'):
        responses, counts = await reads.many([json.dumps(params, sort_keys=True)], produce, retain=True)
    return responses[0], counts

"""JSONL transport stages; SDK request identity and continuation stay with its owner."""
import json
from contextlib import AsyncExitStack, asynccontextmanager

from .quote_flow import stage
from .route_work_slots import required_state_wait
from .sdk_timing import begin_exchange, observe
from contextvars import ContextVar

_exchange_timing = ContextVar('sdk_exchange_timing', default=None)


@asynccontextmanager
async def exchange_lock(lock):
    # Waiting for the serialized worker uses no engine/scheduler capacity.
    # Register lock cleanup before reacquiring leases: cancellation at that
    # boundary must release the lock just as cancellation during an exchange.
    async with AsyncExitStack() as stack:
        async with required_state_wait(engine_priority=True):
            with stage('sdk.queue', kind='queue'):
                entered = await stack.enter_async_context(lock)
        yield entered


def encode(payload):
    with stage('sdk.encode', kind='cpu'):
        return (json.dumps(payload, separators=(',', ':'))+'\n').encode()


async def write(process, payload):
    message = encode(payload)
    with stage('sdk.write'):
        process.stdin.write(message)
        await process.stdin.drain()


async def read(process):
    with stage('sdk.read'):
        line = await process.stdout.readline()
        timing = _exchange_timing.get()
        if timing is not None:
            observe(timing.consumed_line)
    if not line:
        return None
    with stage('sdk.decode', kind='cpu'):
        return json.loads(line)


async def exchange(process, payload):
    timing = observe(lambda: begin_exchange(payload))
    token = _exchange_timing.set(timing)
    try:
        with stage('sdk.exchange'):
            await write(process, {**payload, '_sdkTiming': True} if timing is not None else payload)
            response = await read(process)
        if timing is not None:
            observe(lambda: timing.finish(response))
        return response
    except BaseException as error:
        if timing is not None:
            observe(lambda: timing.finish(error=error))
        raise
    finally:
        _exchange_timing.reset(token)

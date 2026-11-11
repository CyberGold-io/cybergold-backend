"""JSONL transport stages; SDK request identity and continuation stay with its owner."""
import json
from contextlib import AsyncExitStack, asynccontextmanager

from .quote_flow import stage
from .route_work_slots import required_state_wait


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
    if not line:
        return None
    with stage('sdk.decode', kind='cpu'):
        return json.loads(line)


async def exchange(process, payload):
    with stage('sdk.exchange'):
        await write(process, payload)
        return await read(process)

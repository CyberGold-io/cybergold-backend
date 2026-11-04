"""JSONL transport stages; SDK request identity and continuation stay with its owner."""
import json
from contextlib import asynccontextmanager

from .quote_flow import stage


@asynccontextmanager
async def exchange_lock(lock):
    with stage('sdk.queue', kind='queue'):
        await lock.acquire()
    try:
        yield
    finally:
        lock.release()


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

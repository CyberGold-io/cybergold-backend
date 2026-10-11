"""Lazy native DB pool and retained/additive bootstrap; no startup health gate."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = json.loads(Path(__file__).with_name('retained-schema.json').read_text())
POOL_IDENTITIES = json.loads(Path(__file__).with_name('pool-identity-schema.json').read_text())


class Database:
    def __init__(self,url):
        self.url = url
        self.pool = None
        self.schema_task = None

    async def get_pool(self):
        if not self.url:
            raise RuntimeError('DATABASE_URL is required for the on-chain dashboard indexer')
        if self.pool is None:
            self.pool = AsyncConnectionPool(self.url,min_size=0,max_size=8,open=False,kwargs={'row_factory':dict_row})
            # Native pool initialization performs no eager health/query gate.
            await self.pool.open()
        return self.pool

    @asynccontextmanager
    async def connection(self):
        pool = await self.get_pool()
        async with pool.connection() as connection:
            yield connection

    async def initialize_schema(self):
        for statement in (*SCHEMA['statements'], *POOL_IDENTITIES['statements']):
            async with self.connection() as connection:
                await connection.execute(statement)

    async def ensure_schema(self):
        # Preserve the existing shared initialization and one retry after reset.
        for attempt in range(2):
            if self.schema_task is None:
                self.schema_task = asyncio.create_task(self.initialize_schema())
            try:
                await asyncio.shield(self.schema_task)
                return
            except Exception:
                self.schema_task = None
                if self.pool:
                    try:
                        await self.pool.close()
                    except Exception:
                        pass  # Match retained failed-startup reset behavior.
                    self.pool = None
                if attempt == 1:
                    raise

    @asynccontextmanager
    async def advisory_lock(self,key):
        async with self.connection() as connection:
            cursor = await connection.execute('SELECT pg_try_advisory_lock(hashtext(%s),0) AS acquired',(key,))
            acquired = (await cursor.fetchone())['acquired'] is True
            try:
                yield acquired
            finally:
                if acquired:
                    try:
                        await connection.execute('SELECT pg_advisory_unlock(hashtext(%s),0)',(key,))
                    except Exception:
                        # Preserve the action's original error. Closing the native
                        # session releases its lock if the unlock query failed.
                        await connection.close()

    async def close(self):
        if self.schema_task is not None and not self.schema_task.done():
            self.schema_task.cancel()
            await asyncio.gather(self.schema_task,return_exceptions=True)
        if self.pool:
            await self.pool.close()
            self.pool = None

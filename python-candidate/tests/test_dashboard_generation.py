import asyncio
from contextlib import asynccontextmanager

import httpx
from unittest.mock import patch

from cybergold_candidate.environment import load_environment
from cybergold_candidate.runtime import create_configured_app
from cybergold_candidate.quote_history import QuoteHistory

CORE = '0x'+'1'*40
BASE = {'NEXT_PUBLIC_CHAIN_ID': '31338', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE,
        'NEXT_PUBLIC_RPC_URL': 'http://unused.invalid', 'DATABASE_URL': 'postgresql://unused.invalid/db'}
PAYLOAD = {'enabled': True, 'snapshotBlock': '100', 'metrics': {'holderCount': 7}}


class Database:
    def __init__(self, generation):
        self.generation, self.statements = generation, []
        self.snapshot = PAYLOAD
        self.status = 'ready'
    @asynccontextmanager
    async def connection(self):
        yield self
    async def execute(self, sql, params):
        self.statements.append((sql, params))
        return self
    async def fetchone(self):
        return {'payload': self.snapshot} if self.snapshot is not None else None
    async def fetchall(self):
        if self.generation is None:
            return []
        return [{'state_key': key, 'state_value': value} for key, value in (
            ('sandbox_fork_generation', self.generation), ('sandbox_fork_block', '99'),
            ('sandbox_fork_block_hash', '0x'+'2'*64), ('sandbox_fork_projection_status', self.status))]
    async def close(self):
        pass


async def run():
    for chain, generation in (('31338', 'old-fork'), ('31338', 'new-fork'), ('31338', None), ('1', 'unused')):
        database = Database(generation)
        app = create_configured_app(load_environment({**BASE, 'NEXT_PUBLIC_CHAIN_ID': chain}), database)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
                response = await api.get('/api/dashboard/onchain-summary')
                assert response.status_code == 200
                expected = {**PAYLOAD, 'sandboxForkGeneration': generation} if chain == '31338' else PAYLOAD
                assert response.json() == expected
                assert all(sql.lstrip().startswith('SELECT') for sql, _ in database.statements)
                assert len(database.statements) == (2 if chain == '31338' else 1)
    for chain in ('31338', '1'):
        database = Database('old-fork')
        settings = load_environment({**BASE, 'NEXT_PUBLIC_CHAIN_ID': chain})
        history = QuoteHistory(settings)
        history.states['old'] = {'context': {'blockHash': 'old'}, 'state': {'supply': '186'}}
        with patch('cybergold_candidate.runtime.QuoteHistory', return_value=history):
            app = create_configured_app(settings, database)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
                assert (await api.get('/api/dashboard/onchain-summary')).status_code == 200
                assert bool(history.states) == (chain == '1')
                history.states['current'] = {'context': {'blockHash': 'current'}, 'state': {'supply': '8'}}
                assert (await api.get('/api/dashboard/onchain-summary')).status_code == 200
                assert 'current' in history.states
                started, retiring, finish = (asyncio.Event() for _ in range(3))
                async def optional():
                    started.set()
                    try:
                        await finish.wait()
                    except asyncio.CancelledError:
                        retiring.set()
                        await finish.wait()
                history.launch('held-teardown', optional)
                await started.wait()
                database.generation = 'new-fork'
                database.status = 'refreshing'
                database.snapshot = None
                response = await asyncio.wait_for(api.get('/api/dashboard/onchain-summary'), 1)
                assert response.status_code == 500
                assert bool(history.states) == (chain == '1')
                assert history.epoch == (2 if chain == '31338' else 0)
                if chain == '31338':
                    await retiring.wait()
                    assert history.retiring_tasks
                finish.set()
                await history.close()
                history.states['new'] = {'context': {'blockHash': 'new'}, 'state': {'supply': '8'}}
                assert (await api.get('/api/dashboard/onchain-summary')).status_code == 500
                assert 'new' in history.states
                assert len(database.statements) == (8 if chain == '31338' else 4)
    print('PASS: existing durable Sandbox generation is additive/read-only, missing anchor is null, Mainnet response unchanged')
    print('PASS: first/change generation resets API-local model history before an unavailable refreshing snapshot; same generation/Mainnet history stays')


if __name__ == '__main__':
    asyncio.run(run())

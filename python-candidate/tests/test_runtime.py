import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.environment import load_environment
from cybergold_candidate.runtime import safe_history_profile, dashboard_enabled, create_configured_app

BASE = {'NEXT_PUBLIC_CHAIN_ID':'31338','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':'0x'+'1'*40,
        'NEXT_PUBLIC_RPC_URL':'http://fixture.invalid','DATABASE_URL':'postgresql://fixture.invalid/db'}


async def run(path):
    cases=json.loads(Path(path).read_text())
    # Use the same public fixture values as the retained Node process.
    for case in cases:
        settings=load_environment({**BASE,**case['values']})
        try:
            addresses,lookback=safe_history_profile(settings)
            actual={'addresses':addresses,'lookback':lookback}; error=None
        except ValueError as failure:
            actual=None;error=str(failure)
        assert actual==case['safe'] and error==case['error'],case
        assert dashboard_enabled(settings)==case['dashboardEnabled'],case
    class UnusedDatabase:
        closed=False
        def connection(self): raise AssertionError('Disabled read opened a database connection')
        async def close(self): self.closed=True
    database=UnusedDatabase()
    settings=load_environment({**BASE,'DATABASE_URL':None})
    async with httpx.AsyncClient() as client:
        app=create_configured_app(settings,database,client)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                assert (await api.get('/api/activity/core')).json()=={'enabled':False,'events':[]}
                assert (await api.get('/api/activity/safe')).json()=={'enabled':False,'events':[]}
                assert (await api.get('/api/dashboard/onchain-summary')).json()['enabled'] is False
        assert database.closed
    print(f'PASS: {len(cases)} actual Node runtime profile comparisons; configured API startup/shutdown and lazy disabled DB')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

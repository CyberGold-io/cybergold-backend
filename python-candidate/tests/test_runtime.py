import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

from cybergold_candidate.environment import load_environment
from cybergold_candidate.app import create_app
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.sandbox_funding import SandboxFunding
from cybergold_candidate import runtime
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
    for chain in ('31338', '1'):
        database=UnusedDatabase()
        settings=load_environment({**BASE,'DATABASE_URL':None,'NEXT_PUBLIC_CHAIN_ID':chain})
        services={}
        def observe_services(**values):
            services.update(values)
            return create_app(**values)
        async with httpx.AsyncClient() as client:
            # Observe the actual runtime-created services without replacing
            # their constructors or the app/HTTP handlers they are passed to.
            with patch.object(runtime,'create_app',side_effect=observe_services):
                app=create_configured_app(settings,database,client)
            core=services['quote_intent'].service
            assert isinstance(core,QuoteIntent)
            assert core.early_issue_probe is (chain=='31338'),chain
            assert services['trade_quotes'].core is core
            assert services['route_search'] is core.routes
            assert core.retain_plans is True and core.qualification is True
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                    assert (await api.get('/api/activity/core')).json()=={'enabled':False,'events':[]}
                    assert (await api.get('/api/activity/safe')).json()=={'enabled':False,'events':[]}
                    assert (await api.get('/api/dashboard/onchain-summary')).json()['enabled'] is False
            assert database.closed
    # Serving always selects native funding. Legacy service/script settings
    # cannot send a configured API back to the retired funding process.
    database=UnusedDatabase()
    services={}
    settings=load_environment({**BASE,'DATABASE_URL':None,'FORK_FAUCET_ENABLED':'1',
        'FORK_FAUCET_SERVICE_URL':'http://127.0.0.1:9999/fund',
        'FORK_FAUCET_SERVICE_TOKEN':'1'*64,'FORK_FAUCET_SCRIPT_PATH':'/fixture/retired-faucet'})
    def observe_native(**values):
        services.update(values)
        return create_app(**values)
    def no_network(_request):
        raise AssertionError('Missing native configuration attempted a legacy funding request')
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        with patch.object(runtime,'create_app',side_effect=observe_native):
            app=create_configured_app(settings,database,client)
        assert isinstance(services['faucet_service'],SandboxFunding)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.post('/api/faucet',json={'address':'0x'+'a'*40,
                    'requestId':'11111111-1111-4111-8111-111111111111'},
                    headers={'x-real-ip':'192.0.2.1','x-forwarded-for':'192.0.2.1'})
                assert response.status_code==503,response.text
                assert response.json()['code']=='CONFIGURATION_ERROR',response.text
                assert response.headers['cache-control']=='no-store'
        assert database.closed
    print(f'PASS: {len(cases)} actual Node runtime profile comparisons; Sandbox/Mainnet serving quote wiring, configured API startup/shutdown, native faucet selection and lazy disabled DB')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))

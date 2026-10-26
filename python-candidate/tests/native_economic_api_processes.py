"""Literal two-process HTTP/SQL completed-quote reuse on a caller-owned DB.

Pricing uses the deterministic test_universal_quote fixture, not a provider.
Each Uvicorn process owns a real app, service, SQL store and connection pool.
The coordinator owns both loopback sockets/processes and always stops them.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import uuid

import httpx
import uvicorn

from cybergold_candidate.app import create_app
from cybergold_candidate.database import Database
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.store import EconomicQuoteStore
from cybergold_candidate.uniswap_state import UniswapStore
from test_universal_quote import CORE, Engine, Quotes, request


async def serve(role, descriptor):
    database = Database(os.environ['DATABASE_URL'])
    engine = Engine()
    quoter = Quotes(engine)
    registry = engine.registry
    registry.store = UniswapStore(database, registry.chain, registry.core)
    registry.store.scope = os.environ['QUOTER_API_TEST_SCOPE']
    async def loaded():
        pass
    registry.ensure_loaded = loaded
    observed = {'pid': os.getpid(), 'role': role, 'headRequests': 0, 'failRefresh': False}
    block = engine.block
    async def fixture_block(value):
        observed['headRequests'] += 1
        if role == 'lookup':
            raise AssertionError('The lookup process must not acquire a provider head')
        if observed['failRefresh']:
            raise QuoteFailure('quote-no-route')
        return await block(value)
    engine.block = fixture_block
    service = EconomicQuotes(quoter, EconomicQuoteStore(quoter.settings, registry))
    app = create_app(economic_quotes=service, on_shutdown=database.close)

    @app.get('/__fixture__/state')
    async def state():
        return {**observed, 'candidateEvaluations': len(quoter.evaluated)}

    @app.post('/__fixture__/fail-refresh')
    async def fail_refresh():
        observed['failRefresh'] = True
        return {'enabled': True}

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='warning',
                                          access_log=False, lifespan='on'))
    with socket.socket(fileno=descriptor) as listener:
        await server.serve(sockets=[listener])


async def await_fixture(client, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Owned API fixture exited during startup')
        try:
            response = await client.get('/__fixture__/state')
            if response.status_code == 200:
                return response.json()
        except httpx.TransportError:
            pass
        await asyncio.sleep(.1)
    raise TimeoutError('Owned API fixture did not start')


def economic_tuple(value):
    return {key: deepcopy(item) for key, item in value.items() if key != 'observation'}


async def qualify(output):
    namespace = 'native-economic-api:'+uuid.uuid4().hex+':'
    processes, listeners = [], []
    report = None
    database = Database(os.environ['DATABASE_URL'])
    with tempfile.TemporaryDirectory(prefix='cybergold-economic-api-processes-') as directory:
        logs = []
        try:
            endpoints = []
            for role in ('producer', 'lookup'):
                listener = socket.socket()
                listener.bind(('127.0.0.1', 0))
                listener.listen(128)
                listeners.append(listener)
                endpoint = 'http://127.0.0.1:'+str(listener.getsockname()[1])
                log = open(Path(directory)/(role+'.log'), 'w')
                logs.append(log)
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    '--serve', role, '--fd', str(listener.fileno())],
                    env={**os.environ, 'QUOTER_API_TEST_SCOPE': namespace},
                    pass_fds=(listener.fileno(),), stdout=log, stderr=log)
                processes.append(process)
                endpoints.append(endpoint)
                listener.close()

            async with httpx.AsyncClient(base_url=endpoints[0], timeout=20, trust_env=False) as one, \
                    httpx.AsyncClient(base_url=endpoints[1], timeout=20, trust_env=False) as two:
                before_a, before_b = await asyncio.gather(await_fixture(one, processes[0]),
                                                         await_fixture(two, processes[1]))
                assert before_a['pid'] != before_b['pid']
                payload = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
                response = await one.post('/api/economic-quotes', json=payload)
                assert response.status_code == 200
                original = response.json()
                assert original['observation']['source'] == 'search'

                response = await two.post('/api/economic-quotes', json=payload)
                assert response.status_code == 200
                reused = response.json()
                assert reused['observation']['source'] == 'stored'
                assert economic_tuple(original) == economic_tuple(reused)
                after_a, after_b = (await one.get('/__fixture__/state')).json(), (await two.get('/__fixture__/state')).json()
                assert after_a['headRequests'] > 0 and after_a['candidateEvaluations'] > 0
                assert after_b['headRequests'] == 0 and after_b['candidateEvaluations'] == 0

                await one.post('/__fixture__/fail-refresh')
                failure = await one.post('/api/economic-quotes', json={**payload, 'refresh': True})
                assert failure.status_code == 503
                retained_response = await two.post('/api/economic-quotes', json=payload)
                assert retained_response.status_code == 200
                retained = retained_response.json()
                assert economic_tuple(retained) == economic_tuple(original)
                assert retained['observation']['source'] == 'stored'
                after_failure_a = (await one.get('/__fixture__/state')).json()
                after_failure_b = (await two.get('/__fixture__/state')).json()
                assert after_failure_a['headRequests'] > after_a['headRequests']
                assert after_failure_b['headRequests'] == 0 and after_failure_b['candidateEvaluations'] == 0

                async with database.connection() as connection:
                    version = (await (await connection.execute('SHOW server_version')).fetchone())['server_version']
                    rows = await (await connection.execute('''SELECT payload FROM cybergold_uniswap_state
                        WHERE chain_id=%s AND core_address=%s AND namespace=%s''',
                        (1, CORE.lower(), namespace+'economic-quotes'))).fetchall()
                assert len(rows) == 1
                assert rows[0]['payload']['quote'] == economic_tuple(original)
                report = {'result': 'passed', 'scope': 'local two-process HTTP and PostgreSQL correctness control',
                    'pricing': 'deterministic test fixture; no live RPC or owned-fork latency measurement',
                    'postgresVersion': version, 'distinctApiProcesses': True,
                    'api1Pid': after_a['pid'], 'api2Pid': after_b['pid'],
                    'api1InitialHeadReads': after_a['headRequests'],
                    'api2HeadReads': after_failure_b['headRequests'],
                    'api2CandidateEvaluations': after_failure_b['candidateEvaluations'],
                    'twoIndependentHttpClients': True, 'storedLookupAcrossProcesses': True,
                    'originalContext': original['context'], 'quotedOutput': original['quotedOutput'],
                    'planSha256': hashlib.sha256(json.dumps(original['plan'], sort_keys=True).encode()).hexdigest(),
                    'completeEconomicTupleIdentical': True, 'failedRefreshStatus': failure.status_code,
                    'failedRefreshPreservedSqlSuccess': True, 'scopedStoredQuoteCount': len(rows),
                    'liveRpcCalls': 0, 'signatures': 0, 'broadcasts': 0}
        finally:
            for listener in listeners:
                listener.close()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    await asyncio.to_thread(process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
            for log in logs:
                log.close()
            await database.close()
    report['ownedApiProcessesStopped'] = all(process.poll() is not None for process in processes)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', choices=('producer', 'lookup'))
    parser.add_argument('--fd', type=int)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    try:
        asyncio.run(serve(arguments.serve, arguments.fd) if arguments.serve else qualify(arguments.output))
    except Exception as error:
        print(json.dumps({'result': 'failed', 'errorType': type(error).__name__}), flush=True)
        raise SystemExit(1)

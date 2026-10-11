"""Actual Python image/retained PostgreSQL generation read, no deployed inputs."""
import json
import subprocess
import time
import urllib.request
import uuid

IMAGE = 'cybergold-fork-generation-candidate:qualified'
PG = 'docker.io/library/postgres@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'
PREFIX = 'cybergold-generation-fixture-' + uuid.uuid4().hex[:10]
DB, API, NETWORK = (PREFIX+'-'+role for role in ('db', 'api', 'network'))
CORE = '0x'+'1'*40
PAYLOAD = {'enabled': True, 'snapshotBlock': '100', 'metrics': {'holderCount': 7}}


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def sql(statement):
    return docker('exec', DB, 'psql', '-XqAt', '-U', 'fixture', '-d', 'fixture', '-c', statement)


try:
    docker('network', 'create', NETWORK)
    docker('run', '--detach', '--name', DB, '--network', NETWORK, '--env', 'POSTGRES_USER=fixture',
        '--env', 'POSTGRES_PASSWORD=fixture-only', PG)
    for _ in range(150):
        if subprocess.run(['docker', 'exec', DB, 'pg_isready', '-U', 'fixture'], capture_output=True).returncode == 0:
            break
        time.sleep(.1)
    docker('run', '--detach', '--name', API, '--network', NETWORK, '--publish', '127.0.0.1::3000',
        '--env', 'NEXT_PUBLIC_CHAIN_ID=31338', '--env', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+CORE,
        '--env', 'NEXT_PUBLIC_RPC_URL=http://no-rpc:5000', '--env', 'RPC_URL=http://no-rpc:5000',
        '--env', 'SAFE_TX_SERVICE_URL=http://no-safe-service:9542',
        '--env', 'DATABASE_URL=postgresql://fixture:fixture-only@'+DB+':5432/fixture', IMAGE)
    port = docker('port', API, '3000/tcp').rsplit(':', 1)[1]
    base = 'http://127.0.0.1:'+port
    for _ in range(150):
        try:
            with urllib.request.urlopen(base+'/metrics', timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        time.sleep(.1)
    docker('exec', API, 'python', '-c',
        'import asyncio,os; from cybergold_candidate.database import Database; '
        'asyncio.run(Database(os.environ["DATABASE_URL"]).ensure_schema())')
    sql("INSERT INTO onchain_read_model_snapshots(chain_id,contract_address,model_key,block_number,payload) "
        + "VALUES(31338,'"+CORE+"','onchain-dashboard-v1',100,'"+json.dumps(PAYLOAD)+"')")
    for key, value in (('sandbox_fork_generation', 'old-fork'), ('sandbox_fork_block', '99'),
        ('sandbox_fork_block_hash', '0x'+'2'*64), ('sandbox_fork_projection_status', 'ready')):
        sql("INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value) VALUES(31338,'"
            +CORE+"','"+key+"','"+value+"')")
    observations = []
    for generation in ('old-fork', 'new-fork'):
        sql("UPDATE onchain_sync_state SET state_value='"+generation+"' WHERE state_key='sandbox_fork_generation'")
        with urllib.request.urlopen(base+'/api/dashboard/onchain-summary', timeout=10) as response:
            result = json.load(response)
            assert result == {**PAYLOAD, 'sandboxForkGeneration': generation}, result
            observations.append(result)
    assert sql('SELECT COUNT(*) FROM onchain_read_model_snapshots') == '1'
    docker('stop', '--time', '20', API)
    assert int(docker('inspect', API, '--format', '{{.State.ExitCode}}')) == 0
    print(json.dumps({'result': 'pass', 'actualImageResponses': observations,
        'rpcAndSafeServiceNotUsed': True, 'schemaAndSnapshotUnchanged': True, 'shutdownExitCode': 0,
        'testedImageId': docker('image', 'inspect', IMAGE, '--format', '{{.Id}}'),
        'installedInputsUsed': False}, indent=2))
finally:
    for container in (API, DB):
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
    subprocess.run(['docker', 'network', 'rm', NETWORK], capture_output=True)

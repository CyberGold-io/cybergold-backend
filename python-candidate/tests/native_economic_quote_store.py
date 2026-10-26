"""Actual concurrent completed-quote storage on a caller-owned disposable DB.

No RPC, chain mutation, signing or deployed database is used by this control.
"""
import asyncio
from copy import deepcopy
import json
import os

from cybergold_candidate.database import Database
from cybergold_candidate.quoter.store import EconomicQuoteStore
from cybergold_candidate.uniswap_state import UniswapStore
from test_economic_quote_store import fixture


async def run():
    settings, registry, request, quote = fixture()
    first_db, second_db = Database(os.environ['DATABASE_URL']), Database(os.environ['DATABASE_URL'])
    first = UniswapStore(first_db, registry.chain, registry.core)
    second = UniswapStore(second_db, registry.chain, registry.core)
    first.scope = second.scope = registry.store.scope
    registry.store = first
    one = EconomicQuoteStore(settings, registry, limit=3)
    two = EconomicQuoteStore(settings, registry, store=second, limit=3)
    try:
        await first.prepare()
        async with first_db.connection() as a, second_db.connection() as b:
            a_pid = (await (await a.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            b_pid = (await (await b.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            assert a_pid != b_pid
            version = (await (await a.execute('SHOW server_version')).fetchone())['server_version']
        assert await one.save(request, quote)
        observed = await two.lookup(request)
        assert observed == quote
        observed['plan']['operations'][0]['amount'] = 'changed-client-copy'
        assert await one.lookup(request) == quote
        # Separate API writers save complete competing tuples. One complete
        # winner is visible; no output/plan/context field mixing is possible.
        variants = [{**deepcopy(quote), 'quotedOutput': str(index),
            'plan': {'operations': [{'kind': 'market', 'amount': str(index)}]},
            'context': {'blockNumber': str(index), 'blockHash': '0x'+f'{index:064x}'}} for index in range(8)]
        assert all(await asyncio.gather(*(service.save(request, value)
            for index, value in enumerate(variants) for service in ([one] if index % 2 == 0 else [two]))))
        saved = await two.lookup(request)
        assert saved in variants
        # A serial save after concurrent commits is the last successful tuple,
        # independently of its lower original block/amount.
        assert await one.save(request, quote)
        assert await two.lookup(request) == quote
        requests = [{**request, 'inputs': [{'currency': request['inputs'][0]['currency'], 'amount': str(index+1)}]}
                    for index in range(8)]
        assert all(await asyncio.gather(*(service.save(changed, {**quote, 'request': changed})
            for index, changed in enumerate(requests) for service in ([one] if index % 2 == 0 else [two]))))
        scope = one.capture_scope(request)
        async with first_db.connection() as connection:
            cursor = await connection.execute('''SELECT COUNT(*) AS count FROM cybergold_uniswap_state
                WHERE chain_id=%s AND core_address=%s AND namespace=%s''',
                (scope.chain, scope.core, scope.namespace))
            count = (await cursor.fetchone())['count']
        assert count == 3
        assert sum([await two.lookup(changed) is not None for changed in requests]) == 3
        # A slow old-generation save stays in its captured namespace even if
        # the runtime has moved to the accepted replacement generation.
        old_scope = one.capture_scope(request)
        registry.generation = 'two'
        first.scope = second.scope = 'generation:two:'
        assert await one.save(request, quote, scope=old_scope)
        assert await two.lookup(request) is None
        assert await two.save(request, {**quote, 'quotedOutput': '999'})
        assert (await one.lookup(request))['quotedOutput'] == '999'
        assert await one.lookup(request, scope=old_scope) == quote
        print(json.dumps({'postgresVersion': version, 'distinctDatabaseConnections': True,
            'crossProcessEquivalentLookup': True, 'concurrentCompleteTupleWrites': 8,
            'lastCommittedWholeTuple': True, 'concurrentBoundedRecords': count,
            'originalObservationPreserved': True, 'generationIsolation': True, 'rpc': 'none'}))
    finally:
        await asyncio.gather(first_db.close(), second_db.close())


if __name__ == '__main__':
    asyncio.run(run())

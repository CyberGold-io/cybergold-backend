"""Compare scan coordination to compiled retained Node code; no deployed RPC."""
import asyncio
import json
import sys

from cybergold_candidate.reconciliation_receipt import RpcCounter
from cybergold_candidate.safe_collector import EVENTS, reconcile_configured, reconcile_safe


def block_hash(number):
    return '0x' + f'{number:064x}'


def wire(value):
    if isinstance(value, list):
        return [wire(item) for item in value]
    if isinstance(value, dict):
        return {key: str(item) if type(item) is int and key in ('blockNumber', 'timestamp', 'payment', 'block') else wire(item)
            for key, item in value.items()}
    return value


async def check(cases):
    address = '0x' + '5' * 40
    for case in cases:
        mode = case['mode']
        calls, persisted = [], []
        stored_cursor = None
        counter = RpcCounter()
        anchor = None if mode == 'legacy' else {'blockNumber': 103, 'blockHash': block_hash(103)}
        profile = None if mode == 'missing-profile' else 'profile'
        scanned = 103 if mode == 'already' else 105 if mode == 'ahead' else 102 if mode == 'wrong-cursor' else None
        working = {'blockNumber': scanned, 'blockHash': block_hash(999) if mode == 'reorg' else None if scanned is None else block_hash(scanned),
            'profile': 'old' if mode == 'overlap' else 'profile'}
        committed = {**working, 'blockNumber': 103 if mode == 'already' else 102,
            'blockHash': block_hash(103 if mode == 'already' else 102), 'reconciliationId': 'accepted'}
        coverage = {'startBlock': 102, 'cursorBlock': 103} if mode == 'backfill' else {'startBlock': 90, 'cursorBlock': 99} if mode == 'gap' else {'startBlock': 100, 'cursorBlock': 103} if mode == 'covered' else None

        def logs(begin, end, topic=None):
            values = [{'contractAddress': address, 'blockNumber': number,
                'blockHash': block_hash(999) if mode == 'block-hash' else block_hash(number),
                'transactionHash': block_hash(number + 1000), 'logIndex': 0, 'blockTimestampSeconds': number + 1000,
                'topics': [block_hash(999) if mode == 'unknown' else topic or EVENTS[0][1], block_hash(777)],
                'data': '0x11' if mode == 'malformed' else '0x' + f'{2**200:064x}'} for number in range(begin, end + 1)]
            return [values[0]] * 10001 if mode == 'cardinality' else values

        class Projection:
            async def ensure_version(self):
                calls.append('version')
                if mode == 'version-error':
                    raise ValueError('fixture version failure')
            async def cursor(self):
                calls.append('cursor'); return working['blockNumber']
            async def cursor_hash(self):
                calls.append('hash'); return working['blockHash']
            async def profile(self):
                calls.append('profile'); return working['profile']
            async def committed(self):
                calls.append('committed'); return committed
            async def delete_from(self, number):
                calls.append('delete:' + str(number))
            async def persist(self, values):
                calls.append('persist:' + str(len(values))); persisted.extend(values)
            async def put_cursor(self, number, value, p):
                nonlocal stored_cursor
                calls.append('put:' + str(number)); stored_cursor = {'block': number, 'hash': value, 'profile': p}
        projection = Projection()
        projection.address = address

        class Client:
            async def block_number(self):
                calls.append('latest'); return 103
            async def block(self, number):
                calls.append('header:' + str(number))
                return {'number': 42 if mode in ('wrong-header', 'wrong-cursor') else number,
                    'hash': block_hash(999) if mode == 'wrong-anchor' and number == 103 else block_hash(number), 'timestamp': number + 1000}
            async def logs(self, unused_address, value, topic=None):
                begin, end = value['fromBlock'], value['toBlock']
                calls.append(f'legacy:{begin}-{end}:{topic}')
                if mode == 'rpc-error':
                    raise ValueError('fixture RPC failure')
                return [{**log, 'address': address, 'blockNumber': hex(log['blockNumber']), 'logIndex': '0x0'} for log in logs(begin, end, topic)]

        class Journal:
            async def coverage(self):
                calls.append('coverage'); return coverage
            async def ingest(self, first, begin, end, c, source, request, read, split, headers):
                nonlocal coverage
                calls.append(f'ingest:{begin}-{end}'); c.plan(source); c.log_attempt(source)
                if mode == 'rpc-error':
                    c.log_failure(); raise ValueError('fixture RPC failure')
                coverage = {'startBlock': 100, 'cursorBlock': end}
                return logs(begin, end)
            async def prepare_replay(self, enabled, first, end, read):
                calls.append('prepare:' + str(enabled).lower())
                if mode == 'prepare-error':
                    raise ValueError('fixture replay failure')
                return coverage if enabled else None
            async def replay(self, begin, end, unused_coverage):
                calls.append(f'replay:{begin}-{end}'); return logs(begin, end)

        try:
            result = await reconcile_safe(projection, Journal(), {'lookbackBlocks': 3, 'reorgWindow': 2, 'maxBlocksPerRun': 20, 'chunkBlocks': 2},
                counter, Client(), Client(), address_scoped=case['scoped'], raw_replay=case.get('replay', False), anchor=anchor,
                profile=profile, lease_bound=case.get('lease', False), committed_id='other' if mode == 'wrong-committed' else 'accepted',
                maximum_blocks=2 if mode == 'partial' else None)
            actual = {'result': result}
        except Exception as error:
            actual = {'error': str(error)}
        actual.update(calls=calls, persisted=wire(persisted), cursor=wire(stored_cursor), counts=counter.snapshot())
        assert actual == case['expected'], (case['scoped'], mode, next((key for key in actual if actual[key] != case['expected'].get(key)), None), actual)
    visits = []
    async def reconcile(address):
        visits.append(address); return address != 'first'
    assert await reconcile_configured(['first', 'second'], reconcile) is False and visits == ['first', 'second']
    print(f'PASS: {len(cases)} retained Safe collector scan, lease-bound cursor, replay, failure and write-order comparisons; configured Safes do not short circuit')


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))

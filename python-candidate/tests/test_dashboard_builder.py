"""Compare retained bucket mathematics and composed product snapshots."""
import asyncio
import json
import sys
from cybergold_candidate.dashboard_builder import DashboardReads, DEFINITIONS, empty_buckets, apply_rows, materialize


async def check(cases):
    end, hash_value, core = 1790812800123, '0x' + 'a' * 64, '0x' + '1' * 40
    for case in cases:
        mode, calls = case['mode'], []
        if case['domain'] == 'buckets':
            window = empty_buckets(case['range'], end)
            for field in ('mintRaw', 'redeemRaw', 'transferRaw'):
                apply_rows(window, case['rows'], field, end)
            result = materialize(window, int(case['supply']), int(case['decimals']))
            actual = {'result': {**result, 'netIssuanceRaw': str(result['netIssuanceRaw'])}}
        else:
            class Client:
                async def block(self, number=None, *, block_hash=None):
                    calls.append({'block': block_hash or str(number)})
                    return {'hash': '0x' + 'b' * 64 if mode == 'wrong-hash' else hash_value, 'timestamp': end // 1000}
            class State:
                async def core_metrics(self, target):
                    calls.append('metrics')
                    if mode == 'read-error':
                        raise ValueError('fixture read failure')
                    return {'totalSupplyRaw': 1000 * 10**18, 'tokenDecimals': 0 if mode == 'zero-decimals' else 18,
                        'issuanceFeePpm': None if mode == 'missing-fees' else 5000, 'redemptionFeePpm': 8000, 'paused': False}
                async def basket(self, target, *, force_pinned=False, terminal=None):
                    calls.append({'basket': force_pinned})
                    return None if mode == 'no-basket' else {'fixture': 'basket'}
            class Store:
                async def count(self):
                    calls.append('count')
                    return 2**53 if mode == 'holder-wide' else 2**53-1 if mode == 'holder-limit' else -1 if mode == 'negative-holders' else None if mode == 'no-holders' else 7
            class Reads(DashboardReads):
                async def amount_logs(self, name, address, argument, start_ms, end_ms):
                    calls.append(name)
                    if mode == 'empty':
                        return []
                    start = end - 30 * 86400000
                    return [{'block_timestamp_ms': ms, 'tx_hash': 'tx-' + str(index), 'amount_raw': str(index+1)}
                        for index, ms in enumerate([start-1, start, start+1, start+3600000, end-1, end, end+1])]
                async def latest(self, category):
                    names = [definition['name'] for definition in DEFINITIONS['core'] if definition['category'] == category]
                    calls.append(names)
                    return None if mode == 'no-updates' else {'timestampMs': end-1000, 'txHash': names[0]}
            reads = Reads({'coreAddress': core, 'chainId': 31338}, Client(), Store(), state_reads=State())
            try:
                result = await reads.summary(103, {'fixture': 'recovery'}, {'blockNumber': 103},
                    expected_hash=hash_value if mode in ('hash', 'wrong-hash') else None, force_pinned=mode == 'hash')
                actual = {'result': result}
            except Exception as error:
                actual = {'error': str(error)}
        actual['calls'] = calls
        assert actual == case['expected'], (case['domain'], mode, case.get('range'), actual, case['expected'])
    print(f'PASS: {len(cases)} retained dashboard bucket, supply, inclusive-window, precision and composed snapshot comparisons')


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))

"""Compare retained metrics/basket/cache reads and their exact calldata targets."""
import asyncio
import json
import sys
from cybergold_candidate.finalized_multicall import encode_call
from cybergold_candidate.indexer_state_reads import StateReads


async def check(cases):
    core, assets, hash_value = '0x' + '1' * 40, ['0x' + '2' * 40, '0x' + '3' * 40], '0x' + 'a' * 64
    for case in cases:
        mode, calls = case['mode'], []
        pinned = case['pinned']
        class Store:
            async def state_entry(self, key):
                calls.append('cache'); return case['cache']
            async def put_state(self, key, value):
                calls.append('put:' + key + ':' + value)
                if mode == 'write-error':
                    raise ValueError('fixture write failure')
        class Client:
            async def read_contract(self, request):
                name, address = request['functionName'], request['address']
                target = {'blockHash': request['blockHash'], 'requireCanonical': request['requireCanonical']} if pinned else {'blockNumber': str(request['blockNumber'])}
                calls.append({'address': address, 'data': encode_call(request), 'target': target})
                if mode == 'metrics-error' and name == 'issuanceFeePpm' or mode in ('read-error', 'pinned-error', 'terminal') and name == 'cygldRefGramsFp18' or mode == 'token-error' and address != core:
                    raise ValueError('fixture read failure')
                if (mode, name) in [('missing-assets', 'basketAssets'), ('missing-targets', 'basketTargetsPpm'), ('missing-gold', 'basketGoldRefGramsFp18'), ('missing-units', 'basketCygldPerUnitFp18')]:
                    raise ValueError('fixture optional failure')
                return {'totalSupply': 2**220 if mode == 'large' else 1000 * 10**18, 'decimals': 0 if mode == 'decimals-zero' else 18,
                    'issuanceFeePpm': 5000, 'redemptionFeePpm': 8000, 'paused': False, 'cygldRefGramsFp18': 2 * 10**18,
                    'basketAssets': [] if mode == 'empty' else assets, 'basketTargetsPpm': [500000] if mode == 'mismatch' else [500000, 500000],
                    'basketGoldRefGramsFp18': [10**18, 2 * 10**18], 'basketCygldPerUnitFp18': [10**18, 2 * 10**18],
                    'balanceOf': 0 if mode == 'zero-balances' else 100 * 10**18 if address == assets[0] else 50 * 10**18,
                    'symbol': 'ONE' if address == assets[0] else 'TWO'}[name]
        reads = StateReads({'coreAddress': core}, Client(), Store(), now_ms=lambda: 100000000)
        target = {'blockHash': hash_value, 'requireCanonical': True} if pinned else {'blockNumber': 103}
        try:
            if case['domain'] == 'metrics':
                result = await reads.core_metrics(target)
                result = {key: str(value) if type(value) is int else value for key, value in result.items()}
            else:
                method = reads.reference_grams if case['domain'] == 'reference' else reads.basket
                result = await method(target, force_pinned=pinned, terminal=lambda _: mode == 'terminal')
                if case['domain'] == 'reference' and result is not None:
                    result = str(result)
            actual = {'result': result}
        except Exception as error:
            actual = {'error': str(error)}
        actual['calls'] = calls
        assert actual == case['expected'], (case, actual)
    print(f'PASS: {len(cases)} retained Core/token metrics, basket reads and cached/pinned reference-price paths; exact ABI calldata and read targets match')


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))

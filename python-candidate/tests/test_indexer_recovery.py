"""Compare retained coherent recovery/Fund/model reads with exact calldata."""
import asyncio
import json
import sys
from cybergold_candidate.finalized_multicall import encode_call
from cybergold_candidate.indexer_recovery_reads import RecoveryStateReads, portfolio_model


async def check(cases):
    core, governance, reserve, hash_value = '0x' + '1' * 40, '0x' + '9' * 40, '0x' + '4' * 40, '0x' + 'a' * 64
    for case in cases:
        mode, calls = case['mode'], []
        no_pools = mode in ('no-pools', 'empty')
        scale = 2**200 if mode == 'wide' else 1
        terms = {'generation': 7, 'coverageShares': 100 * scale, 'purchasedShares': 20 * scale, 'initialCygldCommitment': 1000 * scale}
        if mode == 'exhausted':
            terms.update(coverageShares=0, purchasedShares=0, initialCygldCommitment=0)
        if mode == 'bad-terms':
            terms['purchasedShares'] = terms['coverageShares']
        commitment = 0 if mode == 'exhausted' or no_pools else 800 * scale * len(case['poolAssets'])
        target = {'blockHash': hash_value, 'requireCanonical': True}
        class Client:
            async def read_contract(self, request):
                calls.append({'address': request['address'], 'data': encode_call(request), 'target': target})
                name = request['functionName']
                if mode in ('read-error', 'terminal') and name == 'trustedRecoveryFundCore':
                    raise ValueError('fixture read failure')
                empty = mode == 'empty-pool'
                pool = {'impaired': not empty, 'coreAttachedShares': 0 if empty else 100, 'externalShares': 0 if empty else 200,
                    'redeemableRaw': 0 if empty else 300, 'cygldPerAssetRawFp18': 10**18, 'cygldSupplyCap': 1000,
                    'referenceShares': 100, 'referenceValueCygld': 100, 'shareDecimals': 18}
                custody = {'lifecycle': 1, 'poolImpaired': not empty, 'redeemablePoolRaw': pool['redeemableRaw'], 'coreAttachedShares': pool['coreAttachedShares'],
                    'externalShares': 99 if mode == 'custody' else pool['externalShares'], 'exitEntitlementRaw': 50, 'liveBalanceAvailable': True,
                    'liveRawCustody': 400, 'activeAvailableRaw': 50, 'poolRawDeficit': 0, 'exitEntitlementDeficitRaw': 0}
                return {'coreAttachedRecoveryAssets': list(reversed(case['poolAssets'])), 'basketAssets': [] if no_pools else [reserve],
                    'reserveLifecycle': {'lifecycle': 3 if mode == 'lifecycle' else 1, 'exitEntitlementRaw': 50}, 'recoveryPool': pool,
                    'reserveCustodyStatus': custody, 'trustedRecoveryFundCore': governance if mode == 'trusted-core' else core, 'paused': mode == 'paused',
                    'recoveryFundTreasuryStatus': [0 if mode == 'deficit' else 10000 * scale, 20000 * scale if mode == 'treasury' else 0,
                        commitment + 1 if mode == 'aggregate' else 0 if mode == 'empty-pool' else commitment],
                    'assetRecoveryFund': terms, 'acquiredRecoveryShares': 201 if mode == 'acquired' else 50,
                    'previewAssetRecoveryFundPurchase': [8 if mode == 'preview-generation' else 7, 799 * scale if mode == 'preview-amount' else 800 * scale]}[name]
        class Reads(RecoveryStateReads):
            async def indexed_assets(self, event, block):
                calls.append('indexed-recovery' if event == 'RecoveryActivated' else 'indexed-reserve')
                return case['poolAssets'] if event == 'RecoveryActivated' else case['reserveAssets']
        reads = Reads({'chainId': 31338, 'coreAddress': core, 'governanceAddress': None if mode == 'no-governance' else governance}, Client(), None)
        try:
            if case['domain'] == 'snapshot':
                result = await reads.snapshot(103, target, lambda _: mode == 'terminal')
                actual = {'result': result, 'model': portfolio_model(31338, 103, core, result)}
            else:
                actual = {'result': await reads.fund(case['pools'], target, lambda _: mode == 'terminal')}
        except Exception as error:
            actual = {'error': str(error)}
        actual['calls'] = calls
        assert actual == case['expected'], (case['domain'], mode, next((key for key in actual if actual[key] != case['expected'].get(key)), None), actual, case['expected'])
    print(f'PASS: {len(cases)} retained recovery snapshot, Fund accounting, unavailable/terminal and portfolio-model comparisons; exact calldata targets match')


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))

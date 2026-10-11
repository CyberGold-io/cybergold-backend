"""Retained recovery snapshot/Fund accounting and schema-5 portfolio model."""
import asyncio
import json
from pathlib import Path

from .recovery_lenses import fund_terms, treasury_accounting, reconcile
from .recovery_persistence import parse_address

ABI = json.loads(Path(__file__).with_name('indexer-recovery-abi.json').read_text())


def ordered_assets(groups):
    values = {asset.lower(): asset for group in groups for asset in group}
    return sorted(values.values(), key=lambda asset: int(asset, 16))


def unavailable(governance, reason, problem):
    return {'configured': governance is not None, 'available': False, 'reason': reason, 'problem': problem,
        'governance': governance.lower() if governance is not None else None,
        'trustedCore': None, 'governancePaused': None, 'treasury': None, 'funds': []}


def portfolio_model(chain, block, collection, recovery):
    base = {'schemaVersion': '5.0', 'chainId': str(chain), 'snapshotBlock': str(block), 'collection': collection.lower()}
    if recovery is None:
        return {**base, 'recovery': None}
    if recovery['collection'].lower() != collection.lower():
        raise ValueError('Recovery portfolio collection differs from the configured Core')
    if len(recovery['pools']) > 256:
        raise ValueError('Recovery pools exceeds the configured cardinality limit of 256')
    fund = recovery['fund']
    current = [{key: row[key] for key in ('impairedAsset', 'generation', 'coverageShares', 'purchasedShares',
        'remainingCoverageShares', 'initialCygldCommitment', 'remainingCygldCommitment')}
        for row in fund['funds'] if row['active'] and row['remainingCoverageShares'] != '0']
    if len(current) > 256:
        raise ValueError('Active Recovery Fund positions exceeds the configured cardinality limit of 256')
    status = {key: fund[key] for key in ('configured', 'available', 'reason', 'problem', 'governance', 'governancePaused')}
    status['treasuryDeficit'] = fund['treasury']['deficit'] if fund['treasury'] is not None else None
    return {**base, 'recovery': {'pools': recovery['pools'], 'fund': {'status': status, 'currentFunds': current}}}


class RecoveryStateReads:
    def __init__(self, config, client, store):
        self.config, self.client, self.store = config, client, store

    async def call(self, contract, name, target, args=None):
        abi = next(entry for entry in ABI[contract] if entry['name'] == name)
        request = {'address': self.config['coreAddress' if contract == 'core' else 'governanceAddress'],
            'abi': [abi], 'functionName': name, **target}
        if args is not None:
            request['args'] = args
        return await self.client.read_contract(request)

    async def indexed_assets(self, name, block):
        rows = await self.store.execute('''SELECT payload FROM onchain_event_logs
            WHERE chain_id=%s AND contract_address=%s AND event_name=%s AND block_number<=%s''',
            (str(self.config['chainId']), self.config['coreAddress'].lower(), name, str(block)))
        values = []
        for row in rows:
            payload = row['payload']
            args = payload.get('args') if isinstance(payload, dict) else None
            asset = parse_address(args.get('asset')) if isinstance(args, dict) else None
            if asset is not None:
                values.append(asset)
        return ordered_assets([values])

    async def fund(self, pools, target, terminal=None):
        governance = self.config.get('governanceAddress')
        if governance is None:
            return unavailable(None, 'not-configured', None)
        try:
            trusted, paused, treasury = await asyncio.gather(*(self.call('governance', name, target) for name in
                ('trustedRecoveryFundCore', 'paused', 'recoveryFundTreasuryStatus')))
            if trusted.lower() != self.config['coreAddress'].lower():
                raise ValueError('Recovery Fund trusted Core does not match the indexed Core')
            balance, exposure, committed = treasury
            derived_treasury = treasury_accounting(balance, exposure, committed)
            async def read(pool):
                asset = pool['asset']
                terms, acquired = await asyncio.gather(self.call('governance', 'assetRecoveryFund', target, [asset]),
                    self.call('governance', 'acquiredRecoveryShares', target, [asset]))
                derived = fund_terms(terms)
                attached, external = int(pool['coreAttachedShares']), int(pool['externalShares'])
                if attached < 0 or external < 0 or acquired < 0 or acquired > external:
                    raise ValueError('Invalid Recovery Fund uncovered-interest inputs')
                uncovered = attached + external - acquired
                unfunded = max(uncovered - derived['remainingCoverageShares'], 0)
                preview = None
                if derived['active'] and derived['remainingCoverageShares'] > 0:
                    generation, amount = await self.call('governance', 'previewAssetRecoveryFundPurchase', target,
                        [asset, derived['remainingCoverageShares']])
                    if generation != terms['generation'] or amount != derived['remainingCygldCommitment']:
                        raise ValueError('Recovery Fund current purchase preview does not reconcile')
                    preview = {'generation': str(generation), 'shares': str(derived['remainingCoverageShares']), 'cygldAmount': str(amount)}
                return {'impairedAsset': asset.lower(), 'generation': str(terms['generation']), 'active': derived['active'],
                    'coverageShares': str(terms['coverageShares']), 'purchasedShares': str(terms['purchasedShares']),
                    'remainingCoverageShares': str(derived['remainingCoverageShares']), 'initialCygldCommitment': str(terms['initialCygldCommitment']),
                    'paidCygld': str(derived['paidCygld']), 'remainingCygldCommitment': str(derived['remainingCygldCommitment']),
                    'governanceBalance': str(acquired), 'uncoveredInterest': str(uncovered), 'currentlyUnfundedInterest': str(unfunded),
                    'acquiredShares': str(acquired), 'purchasePreview': preview}
            funds = await asyncio.gather(*(read(pool) for pool in pools))
            if sum(int(row['remainingCygldCommitment']) for row in funds) != committed:
                raise ValueError('Recovery Fund aggregate commitment does not reconcile')
            return {'configured': True, 'available': True, 'reason': None, 'problem': None, 'governance': governance.lower(),
                'trustedCore': trusted.lower(), 'governancePaused': paused,
                'treasury': {'balance': str(balance), 'allowanceExposure': str(exposure), 'unallowanced': str(derived_treasury['unallowanced']),
                    'aggregateCommitment': str(committed), 'available': str(derived_treasury['available']), 'deficit': str(derived_treasury['deficit'])},
                'funds': funds}
        except Exception as error:
            if terminal is not None and terminal(error):
                raise
            return unavailable(governance, 'unavailable-or-inconsistent', str(error))

    async def snapshot(self, block, target, terminal=None):
        try:
            attached, historical, reserves, basket = await asyncio.gather(self.call('core', 'coreAttachedRecoveryAssets', target),
                self.indexed_assets('RecoveryActivated', block), self.indexed_assets('ReserveLifecycleChanged', block),
                self.call('core', 'basketAssets', target))
            pool_assets = ordered_assets([attached, historical])
            reserve_assets = ordered_assets([reserves, pool_assets, basket])
            if len(pool_assets) > 256 or len(reserve_assets) > 512:
                raise ValueError('Recovery asset cardinality exceeds the App read-model policy')
            async def lifecycle(asset):
                value = await self.call('core', 'reserveLifecycle', target, [asset])
                return {'asset': asset.lower(), 'lifecycle': value['lifecycle'], 'exitEntitlementRaw': str(value['exitEntitlementRaw'])}
            lifecycles = await asyncio.gather(*(lifecycle(asset) for asset in reserve_assets))
            by_asset = {value['asset']: value for value in lifecycles}
            async def pool(asset):
                pool, custody = await asyncio.gather(self.call('core', 'recoveryPool', target, [asset]),
                    self.call('core', 'reserveCustodyStatus', target, [asset]))
                lifecycle = by_asset.get(asset.lower())
                if lifecycle is None:
                    raise ValueError('Recovery pool, lifecycle, and custody views are inconsistent')
                current = {key: str(pool[key]) for key in ('coreAttachedShares', 'externalShares', 'redeemableRaw',
                    'cygldPerAssetRawFp18', 'cygldSupplyCap', 'referenceShares', 'referenceValueCygld')}
                current.update(asset=asset.lower(), impaired=pool['impaired'], totalShares=str(pool['coreAttachedShares'] + pool['externalShares']), shareDecimals=pool['shareDecimals'])
                current_custody = {key: str(custody[key]) for key in ('redeemablePoolRaw', 'coreAttachedShares', 'externalShares',
                    'exitEntitlementRaw', 'liveRawCustody', 'activeAvailableRaw', 'poolRawDeficit', 'exitEntitlementDeficitRaw')}
                current_custody.update(lifecycle=custody['lifecycle'], poolImpaired=custody['poolImpaired'], liveBalanceAvailable=custody['liveBalanceAvailable'])
                return reconcile(current, lifecycle, current_custody)
            rows = await asyncio.gather(*(pool(asset) for asset in pool_assets))
            pools = [row for row in rows if row['impaired'] or row['coreAttachedShares'] != '0' or row['externalShares'] != '0' or row['redeemableRaw'] != '0']
            fund = await self.fund(pools, target, terminal)
            return {'collection': self.config['coreAddress'].lower(), 'pools': pools, 'reserveLifecycles': lifecycles, 'fund': fund}
        except Exception as error:
            if terminal is not None and terminal(error):
                raise
            return None

"""Retained indexer identity and finalized planning rules; no scheduler."""
import json
import re

HASH = re.compile(r'0x[a-fA-F0-9]{64}')
MAX_BIGINT = 9_223_372_036_854_775_807


def identity_transition(stored, expected):
    version = stored['rawJournalVersion']
    if version is not None and version != expected['rawJournalVersion']:
        raise ValueError(f"Raw journal version {version} is incompatible with {expected['rawJournalVersion']}")
    projection = stored['dashboardProjectionVersion']
    if projection is None:
        projection = stored['legacyIndexerVersion']
    governance = stored['dashboardProjectionGovernanceAddress']
    if governance is None:
        governance = stored['legacyGovernanceAddress']
    changed = governance != expected['governanceAddress']
    return {'initializeRawJournalIdentity':version is None,
            'initializeStateSnapshotIdentity':stored['stateSnapshotVersion'] is None,
            'resetProjection':projection != expected['dashboardProjectionVersion'] or changed,
            'resetStateSnapshots':stored['stateSnapshotVersion'] is not None and
                stored['stateSnapshotVersion'] != expected['stateSnapshotVersion'],
            'restartScanFromDeployment':changed}


def finalized_anchor(value):
    number, block_hash = value.get('number'), value.get('hash')
    if (type(number) is not int or not 0 <= number <= MAX_BIGINT or
            not isinstance(block_hash,str) or not HASH.fullmatch(block_hash)):
        raise ValueError('Finalized RPC anchor is incomplete or invalid')
    return {'blockNumber':number,'blockHash':block_hash.lower()}


def deployment_start(chain_id, configured, anchor):
    if configured < 0:
        raise ValueError('Archive-free deployment start block cannot be negative')
    if chain_id == 1 and configured == 0:
        raise ValueError('ONCHAIN_INDEXER_START_BLOCK must be a configured nonzero block on Ethereum mainnet in archive-free mode')
    if configured > anchor:
        raise ValueError('Archive-free deployment start block is above the finalized anchor')
    return configured


def projection_scan(deploymentStartBlock, anchor, cursor, canonicalCursorHash,
                    reorgWindow, forceConfigurationOverlap):
    if reorgWindow <= 0:
        raise ValueError('Finalized projection reorg window must be positive')
    block = cursor['blockNumber']
    if block is None or block < deploymentStartBlock:
        return {'fromBlock':deploymentStartBlock,'reason':'initial'}
    if forceConfigurationOverlap:
        return {'fromBlock':deploymentStartBlock,'reason':'configuration-overlap'}
    def overlap(value):
        return max(deploymentStartBlock,max(0,value-reorgWindow))
    if block > anchor['blockNumber']:
        return {'fromBlock':overlap(anchor['blockNumber']),'reason':'cursor-ahead-overlap'}
    stored_hash = (cursor.get('blockHash') or '').lower()
    canonical_hash = (canonicalCursorHash or '').lower()
    if not stored_hash or not canonical_hash or stored_hash != canonical_hash:
        return {'fromBlock':overlap(block),'reason':'hash-mismatch-overlap'}
    if block == anchor['blockNumber']:
        return {'fromBlock':None,'reason':'already-projected'}
    return {'fromBlock':block+1,'reason':'continue'}


def planning_boundary(leaseBound, working, committed):
    return committed if leaseBound else working


def finalized_profile(value):
    # Insertion order is the retained JSON identity. Never bump projection
    # versions or reset cursors merely because the implementation language moved.
    profile = {'version':1,'addressScopedRawLogs':value['addressScopedRawLogs'],
        'coreDeploymentStartBlock':str(value['coreDeploymentStartBlock']),
        'safeLookbackBlocks':str(value['safeLookbackBlocks']),
        'governanceAddress':value['governanceAddress'].lower() if value['governanceAddress'] is not None else None,
        'safeAddresses':sorted(address.lower() for address in value['safeAddresses']),
        'rawJournalVersion':value['rawJournalVersion'],
        'dashboardProjectionVersion':value['dashboardProjectionVersion'],
        'safeCursorVersion':value['safeCursorVersion']}
    for key in ('coreEventSelectors','governanceEventSelectors','safeEventSelectors'):
        profile[key] = [selector.lower() for selector in value[key]]
    return json.dumps(profile,separators=(',',':'),ensure_ascii=False)


def snapshot_matches(anchor, expectedProfile, snapshotBlockNumber, snapshotBlockHash,
                     snapshotProfile, requiredSnapshotsExist):
    return bool(requiredSnapshotsExist and snapshotBlockNumber == anchor['blockNumber'] and
                snapshotBlockHash is not None and snapshotBlockHash.lower() == anchor['blockHash'].lower() and
                snapshotProfile == expectedProfile)


def anchor_tag(chain_id):
    return 'latest' if chain_id == 31338 else 'finalized'

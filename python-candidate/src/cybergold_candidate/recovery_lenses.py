"""Existing recovery lens consistency and current Fund accounting formulas."""
import re


def canonical_uint(value,label):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]*)',value):
        raise ValueError(label+' must be a canonical unsigned integer')
    return int(value)


def reconcile(pool,lifecycle,custody):
    if lifecycle['asset'].lower()!=pool['asset'].lower():
        raise ValueError('Recovery pool and reserve lifecycle views are inconsistent')
    inconsistent='Recovery pool, lifecycle, and custody views are inconsistent'
    if (type(lifecycle['lifecycle']) is not int or lifecycle['lifecycle']<0 or lifecycle['lifecycle']>=3
        or custody['lifecycle']!=lifecycle['lifecycle'] or custody['poolImpaired']!=pool['impaired']):
        raise ValueError(inconsistent)
    attached=canonical_uint(pool['coreAttachedShares'],'Core-attached recovery shares')
    external=canonical_uint(pool['externalShares'],'External recovery shares')
    liability=canonical_uint(pool['redeemableRaw'],'Recovery-pool liability')
    if canonical_uint(pool['totalShares'],'Total recovery shares')!=attached+external:
        raise ValueError('Recovery pool share totals are inconsistent')
    entitlement=canonical_uint(lifecycle['exitEntitlementRaw'],'Reserve exit entitlement')
    if (canonical_uint(custody['coreAttachedShares'],'Custody Core-attached shares')!=attached
        or canonical_uint(custody['externalShares'],'Custody external shares')!=external
        or canonical_uint(custody['redeemablePoolRaw'],'Custody pool liability')!=liability
        or canonical_uint(custody['exitEntitlementRaw'],'Custody exit entitlement')!=entitlement):
        raise ValueError(inconsistent)
    canonical_uint(pool['cygldPerAssetRawFp18'],'Recovery conversion')
    canonical_uint(pool['cygldSupplyCap'],'Recovery CYGLD supply cap')
    live=canonical_uint(custody['liveRawCustody'],'Live reserve custody')
    if not custody['liveBalanceAvailable'] and live!=0:raise ValueError(inconsistent)
    canonical_uint(custody['activeAvailableRaw'],'Active available custody')
    canonical_uint(custody['poolRawDeficit'],'Recovery-pool deficit')
    canonical_uint(custody['exitEntitlementDeficitRaw'],'Exit-entitlement deficit')
    return {**pool,'lifecycle':dict(lifecycle),'custody':dict(custody)}


def fund_terms(terms):
    generation,coverage,purchased,commitment=(terms[key] for key in (
        'generation','coverageShares','purchasedShares','initialCygldCommitment'))
    if generation<0 or coverage<0 or purchased<0:raise ValueError('Invalid Recovery Fund current terms')
    if coverage==0:
        if purchased!=0 or commitment!=0:raise ValueError('Invalid exhausted Recovery Fund terms')
        return {'active':False,'remainingCoverageShares':0,'paidCygld':0,'remainingCygldCommitment':0}
    if generation==0 or purchased>=coverage or commitment<=0:raise ValueError('Invalid Recovery Fund current terms')
    paid=commitment*purchased//coverage
    return {'active':True,'remainingCoverageShares':coverage-purchased,'paidCygld':paid,
        'remainingCygldCommitment':commitment-paid}


def treasury_accounting(balance,allowance,committed):
    if balance<0 or allowance<0 or allowance>balance or committed<0:
        raise ValueError('Invalid Recovery Fund treasury accounting')
    unallowanced=balance-allowance
    return {'unallowanced':unallowanced,'available':max(0,unallowanced-committed),'deficit':max(0,committed-unallowanced)}

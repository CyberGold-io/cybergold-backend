"""Replay held-out route points with independent pool price/fee/liquidity.

Run through the existing read-only RPC wrapper. No new size-ladder calls.
Older Sandbox points are labeled historical; matching hashes do not prove no
administrative overrides. This is route estimation, not a full CYGLD preview.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from fractions import Fraction as F
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

from cybergold_candidate.pool_producer import PoolRpc
from cybergold_candidate.quote_models import LegModel, PoolBaseline
from web3 import Web3


def fraction(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


async def main(args):
    captured = json.loads(Path(args.ladder).read_text())
    contracts = json.loads(Path(args.contracts).read_text())['publicContracts']
    settings = SimpleNamespace(RPC_URL=os.environ.get('DISTANT_FORKNET_RPC_URL','http://unused.invalid'),RPC_AUTHORIZATION=None,
                               NEXT_PUBLIC_CHAIN_ID='31338')
    rpc = PoolRpc(settings)
    document = {'observedAt':datetime.now(timezone.utc).isoformat(), 'scope':__doc__,
                'calibrationQuoterCallsAdded':0, 'baselineReads':0, 'cases':[]}
    try:
        started = time.perf_counter()
        saved = json.loads(Path(args.baseline_evidence).read_text()) if args.baseline_evidence else None
        block = saved['currentContext'] if saved else await rpc.block(None)
        document['currentContext'] = block
        for leg in captured['legs']:
            token_in, token_out = contracts[captured['inputToken']], contracts[leg['outputToken']]
            fee = int(leg['feeInfo'])
            if saved:
                row = next(row for row in saved['baselines'] if row['leg']==leg['outputToken'])
                def value(name):
                    return F(int(row[name]['numerator']),int(row[name]['denominator']))
                baseline = PoolBaseline(value('marginalExchangeRateRaw'),value('feeRetention'),value('activeLiquidityImpactCoefficient'))
            else:
                pool = await rpc.read('factory',rpc.factory,'getPool',block,
                                      sorted([Web3.to_checksum_address(token_in),Web3.to_checksum_address(token_out)])+[fee])
                slot, liquidity = await asyncio.gather(rpc.read('pool',pool,'slot0',block), rpc.read('pool',pool,'liquidity',block))
                document['baselineReads'] += 3
                baseline = PoolBaseline.v3(int(slot[0]),int(liquidity),fee,token_in.lower()<token_out.lower())
            points = [(int(p['requestedRaw']),int(p['quotedRaw'])) for p in leg['ladder'] if p['status']=='completed']
            # For prediction each exact answer is held out; calibration source
            # is the already-recorded ladder, not a claim of organic hit rates.
            model = LegModel(points,baseline)
            document.setdefault('baselines',[]).append({'leg':leg['outputToken'],
                'marginalExchangeRateRaw':fraction(baseline.exchange),
                'feeRetention':fraction(baseline.fee_retention),
                'activeLiquidityImpactCoefficient':fraction(baseline.local_impact),
                'currentPriceVersusOldSmallPointPercent':float(100*(baseline.exchange*baseline.fee_retention/F(points[0][1],points[0][0])-1))})
            tests = [point for row in leg['heldOut'] for point in (row.get('actual'), row.get('actualExactOut')) if point]
            for point in tests:
                if point.get('status') != 'completed':
                    continue
                amount, exact = int(point['requestedRaw']),int(point['quotedRaw'])
                inverse = point['mode']=='exact-out'
                for method in ('larger','nearest','linear','free','anchored','local'):
                    tick = time.perf_counter_ns()
                    predicted = model.predict(amount,method,inverse)
                    cpu_us = (time.perf_counter_ns()-tick)/1000
                    document['cases'].append({'leg':leg['outputToken'],'mode':point['mode'],
                        'method':method,'amount':str(amount),'exact':str(exact),
                        'predicted':str(predicted) if predicted is not None else None,
                        'errorPercent':float(100*F(predicted-exact,exact)) if predicted is not None else None,
                        'cpuMicroseconds':cpu_us,'historicalPointContext':point['context']})
        if not saved:
            await rpc.assert_canonical(block)
        else:
            document['baselineEvidence'] = args.baseline_evidence
        document['baselineAcquisitionMs'] = round(1000*(time.perf_counter()-started),3)
    finally:
        await rpc.close()
    Path(args.output).write_text(json.dumps(document,indent=2)+'\n')
    print(json.dumps({'cases':len(document['cases']),'baselineReads':document['baselineReads'],
                      'baselineAcquisitionMs':document['baselineAcquisitionMs']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ladder',required=True)
    parser.add_argument('--contracts',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--baseline-evidence',help='Reuse captured baselines for an offline replay with zero RPC')
    asyncio.run(main(parser.parse_args()))

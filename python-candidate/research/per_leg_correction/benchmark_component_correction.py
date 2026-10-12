"""Offline R2: genuine captured integer basket state + controlled pool oracle.

Usage: --output PATH [--traces recorded-mainnet-delayed-correction.json].
Recorded samples are one-step held-out checks, never invented final quotes.
"""
import argparse
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
import time

from cybergold_candidate.basket_arithmetic import BasketArithmetic
from .quote_component_correction import ComponentCorrection
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.quote_models import PoolBaseline


def state():
    return json.loads(Path(__file__).resolve().parents[2].joinpath('tests/fixtures/basket-model.json').read_text())['state']


def oracle(gross, snapshot, regime='smooth'):
    basket = BasketArithmetic(snapshot).redeem_in(gross)
    amounts = [row['amount'] for row in basket['projectedCoreOutputs']]
    rates, impacts = [F(153, 100), F(15*10**11)], [F(1,10**19), F(1,10000)]
    legs = []
    for i, amount in enumerate(amounts):
        f = F(997,1000)
        output = rates[i]*f*amount/(1+impacts[i]*f*amount)
        # A changed tick regime is an intentionally held-out stress case.
        threshold = [52*10**12,35][i]
        if regime == 'tick' and amount > threshold:
            at_tick = rates[i]*f*threshold/(1+impacts[i]*f*threshold)
            output = at_tick + (output-at_tick)*F(98,100)
        quoted = output.numerator//output.denominator
        minimum = quoted*99//100
        legs.append({'inputAsset':snapshot['assets'][i], 'inputAmount':str(amount),
            'minimumAmountOut':str(minimum),'data':str(i)})
    return {'quotes':legs,'preview':{'minimumAmountOut':str(sum(int(l['minimumAmountOut']) for l in legs))}}


def solve(target, variant, regime='smooth'):
    snapshot = state()
    baselines = {'0':PoolBaseline(F(153,100),F(997,1000)),
                 '1':PoolBaseline(F(15*10**11),F(997,1000))}
    component = ComponentCorrection(snapshot,'weth',lambda path:path,baselines,use_upper_rate=variant=='upperRate')
    correction = delayed_local_step if variant == 'shipped' else component
    gross = 2802115027027027 * target // 131700000113139
    points, calls, cpu = [], [], 0
    for iteration in range(11):
        result = oracle(gross,snapshot,regime)
        output = int(result['preview']['minimumAmountOut'])
        points.append((gross,output))
        if variant != 'shipped':component.observe_result(result)
        calls.append({'gross':str(gross),'minimum':str(output)})
        if target <= output <= target*101//100:
            return {'status':'complete','evaluations':len(calls),'gross':str(gross),'minimum':str(output),
                    'calls':calls,'modelCpuMs':cpu,'modelProposals':component.proposals}
        if iteration == 10 or output <= 0:break
        proposed = gross*target//output
        if proposed == gross:proposed += 1 if output < target else -1
        started = time.perf_counter_ns()
        gross = correction(points,target,proposed)
        cpu += (time.perf_counter_ns()-started)/1e6
    return {'status':'failure','evaluations':len(calls),'calls':calls,'modelCpuMs':cpu,'modelProposals':component.proposals}


def held_out(path):
    evidence = json.loads(Path(path).read_text())
    rows = []
    for sample in evidence['samples']:
        correction = ComponentCorrection(state(),sample['asset'],lambda path:path)
        points = []
        baskets = {p['gross']:p for p in sample['previews'] if p['kind']=='redeem-exact-in'}
        for preview in sample['previews']:
            if preview['kind'] != 'redeem-token-exact-in':continue
            basket = baskets[preview['gross']]
            gross = int(preview['gross'])
            expected = BasketArithmetic(state()).redeem_in(gross)
            parity = [int(o['amount']) for o in basket['outputs']] == [o['amount'] for o in expected['projectedCoreOutputs']]
            before = correction.predict(gross)
            actual = int(preview['quotedMinimum'])
            rows.append({'asset':sample['asset'],'index':sample['index'],'gross':str(gross),
                'basketQuantitiesMatchCapturedState':parity,'predictedBeforeTraining':str(before) if before else None,
                'actual':str(actual),'errorPercent':float(100*F(before-actual,actual)) if before else None})
            if parity:
                correction.observe_result({'quotes':[{'inputAsset':item['asset'],'inputAmount':item['amount'],
                    'minimumAmountOut':minimum,'data':str(i)} for i,(item,minimum) in
                    enumerate(zip(basket['outputs'],preview['legMinimums'],strict=True))]})
            points.append((gross,actual))
    return rows


def main(args):
    document = {'scope':'Offline controlled experiment. Captured Sandbox integer Basket state; explicit synthetic pool marginal rates, 0.3% fees and nonlinear size impact. Every proposed gross is checked by the independent controlled forward oracle, eleven-check ceiling and original target..target+1% preserved. Tick stress is intentionally outside the smooth model. Counts are forward evaluations, not deployed RPC totals or wall-time savings. Recorded Mainnet checks use only preceding paid points, with quantity parity reported; exchange/fee decomposition absent in those recorded fallback predictions. No midpoint.',
        'controlled':[], 'heldOutMainnet':held_out(args.traces) if args.traces else []}
    for regime in ('smooth','tick'):
        for target in [10**12,10**13,131700000113139,134000000000000,10**15,5*10**15]:
            low,high=1,state()['supply']
            while low<high:
                middle=(low+high)//2
                if int(oracle(middle,state(),regime)['preview']['minimumAmountOut'])>=target:high=middle
                else:low=middle+1
            first=int(oracle(low,state(),regime)['preview']['minimumAmountOut'])
            document['controlled'].append({'regime':regime,'target':str(target),
                'oracleSmallestUpperGross':str(low),'oracleSmallestUpperOutput':str(first),
                'oracleIntervalRealizable':first<=target*101//100,
                'shipped':solve(target,'shipped',regime),'component':solve(target,'component',regime),
                'upperRate':solve(target,'upperRate',regime)})
    Path(args.output).write_text(json.dumps(document,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in row.items() if k not in ('shipped','component','upperRate')}|
        {v:{k:row[v][k] for k in ('status','evaluations','modelCpuMs')} for v in ('shipped','component','upperRate')}
        for row in document['controlled']],indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--traces')
    main(parser.parse_args())

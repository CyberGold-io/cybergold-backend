"""Counterbalanced fixed/bounds/protected-random/combined actual-SDK searches.

All arms use the same acquired catalog, seed plan, selection clock and optional
allowance. Test-only patches disable the specific optional policies; runtime
configuration and ordinary candidate work are unchanged. No network or sends.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BACKEND / 'python-candidate/src'), str(BACKEND / 'python-candidate/tests')]
from quoter_fixture import historical_service, historical_data, historical_route
from cybergold_candidate.quoter.discovery import market_plan
import cybergold_candidate.quoter.search as search
import cybergold_candidate.quoter.exploration as exploration


async def main(args):
    result = {'scope': __doc__, 'rows': [], 'networkRequests': 0, 'completed': False}
    arms = ['fixed', 'bounds', 'protected-random', 'combined']
    for repetition in range(3):
        for arm in arms[repetition:] + arms[:repetition]:
            cleanups = []
            class Owner:
                def addAsyncCleanup(self, function, *values):
                    cleanups.append((function, values))
            q, case = historical_service(Owner(), exploration_seed=1700 + repetition)
            try:
                row = next(row for row in case['routes'] if row['output'] == '3847595333028986815')
                selected = market_plan(case['request']['inputs'][0]['currency'], q.core,
                    historical_route(q, row), 500000000)
                seed = await q.candidate(case['request'], 0, 'core-first', historical_data()['anchor'],
                    *case['basis'], selected=selected)
                original_explore, original_dominated = search.explore, exploration.dominated
                async def fixed(*values, **options):
                    options['seeded'] = False
                    return await original_explore(*values, **options)
                started = time.monotonic()
                with patch.object(search, 'explore', original_explore if arm in ('protected-random', 'combined') else fixed), \
                        patch.object(exploration, 'dominated', original_dominated if arm in ('bounds', 'combined') else lambda *_: False):
                    value = await q.get(case['request'], seed=seed)
                result['rows'].append({'arm': arm, 'repetition': repetition, 'seed': str(1700+repetition),
                    'output': value['quotedOutput'], 'funding': value['inputs'], 'metrics': value['metrics'],
                    'totalMs': round((time.monotonic()-started)*1000, 3), 'sdkRequests': q.engine.sdk.sequence,
                    'incumbentPreserved': int(value['quotedOutput']) >= int(seed['quotedOutput'])})
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2)+'\n')
                print(json.dumps({'arm': arm, 'repetition': repetition, 'output': value['quotedOutput']}), flush=True)
            finally:
                for function, values in reversed(cleanups):
                    await function(*values)
    result['completed'] = True
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))

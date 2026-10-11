"""Read-only fresh producer comparison through with-authenticated-rpc.sh.

PYTHONPATH=python-candidate/src <authenticated wrapper> -- python-candidate/.venv/bin/python
  python-candidate/tests/benchmark_route_search.py /absolute/output.json
The deployed broker is unchanged: this measures the new backend with today's adapter.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from cybergold_candidate.route_search import RouteSearch, WETH, candidates
from cybergold_candidate.uniswap_quote import UniswapQuote

PAXG = '0x45804880De22913dAFE09f4980848ECE6EcbAf78'
XAUT = '0x68749665FF8D2d112Fa859AA293F07A622782F38'
USDC = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
    NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS='0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
    RPC_URL=os.environ['MAINNET_RPC_URL'], RPC_AUTHORIZATION=None)


async def legacy(search, mode, targets):
    async def quote(target, row):
        try:
            value = await search.get({'mode': mode, 'path': row['path'], 'amount': target['amount']})
            return {'path': row['path'], 'amount': value['result']['amount'], 'blockHash': value['context']['blockHash']}
        except Exception as error:
            return {'path': row['path'], 'failureType': type(error).__name__}
    outputs = []
    for target in targets:
        outputs.append([quote(target, row) for row in candidates(target, mode)])
    rows = await asyncio.gather(*(operation for group in outputs for operation in group))
    return {'candidates': rows, 'successful': sum('amount' in row for row in rows),
            'rpcReads': 3*len(rows)+sum('amount' in row for row in rows)}


async def main():
    output = Path(sys.argv[1])
    document = {'observedAt': datetime.now(timezone.utc).isoformat(),
        'scope': 'Fresh backend producer waves; legacy candidates already parallel, no pool preparation/record overhead included. Existing deployed broker, not the feature broker. Unique amounts; latest blocks can differ across waves. No UI duration or numerical parity claim across blocks.',
        'trials': []}
    old, new = UniswapQuote(SETTINGS), RouteSearch(SETTINGS)
    try:
        for mode in ('exact-in', 'exact-out'):
            for symbol, token in (('WETH', WETH), ('USDC', USDC)):
                for repeat in range(3):
                    for strategy in (('legacy', 'grouped') if repeat % 2 == 0 else ('grouped', 'legacy')):
                        # Fresh calldata, including the corrected six-decimal XAUt output.
                        offset = 1+repeat*2+(strategy == 'grouped')
                        targets = [{'inputAsset': token, 'outputAsset': asset,
                            'amount': str((600_000_000_000_000 if symbol == 'WETH' else 2_000_000)+offset
                                if mode == 'exact-in' else (100_000_000_000_000 if asset == PAXG else 100)+offset)}
                            for asset in (PAXG, XAUT)]
                        started = time.perf_counter()
                        trial = {'mode': mode, 'asset': symbol, 'repeat': repeat+1,
                                 'strategy': strategy, 'targets': targets}
                        try:
                            result = await legacy(old, mode, targets) if strategy == 'legacy' else await new.get({'mode': mode, 'targets': targets})
                            trial.update(status='completed', result=result)
                        except Exception as error:
                            trial.update(status='failure', failureType=type(error).__name__)
                        trial['durationMs'] = round((time.perf_counter()-started)*1000, 3)
                        document['trials'].append(trial)
                        output.write_text(json.dumps(document, indent=2)+'\n')
                        print(json.dumps({key: value for key, value in trial.items() if key not in ('targets','result')}), flush=True)
    finally:
        await old.close()
        await new.close()


if __name__ == '__main__':
    asyncio.run(main())

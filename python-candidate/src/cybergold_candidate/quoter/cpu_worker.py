"""Internal pipe worker: pure graph recipes only, never network or pricing."""
import json
import sys

from .cooperative import finish
from .cpu import batch_routes
from .discovery import _enumerate_path_steps
from ..routing_encoding import ZERO
from ..uniswap_routes import pool_identity


def enumerate_recipes(value):
    pools = value['pools']
    for pool in pools:
        pool['hooks'] = pool.get('hooks') or ZERO
    positions = {pool_identity(pool): index for index, pool in enumerate(pools)}
    routes = finish(_enumerate_path_steps(pools, value['source'], value['target'],
                                         value['weth'], value['maxHops']))
    return [[[positions[pool_identity(hop['pool'])], hop['zeroForOne']]
             if 'pool' in hop else [hop['kind'], hop['currencyOut']]
             for hop in route] for route in routes]


def main():
    print('{"ready":true}', flush=True)
    for line in sys.stdin:
        try:
            for routes in batch_routes(enumerate_recipes(json.loads(line))):
                print(json.dumps({'routes': routes}, separators=(',', ':')), flush=True)
            print('{"done":true}', flush=True)
        except Exception as error:
            print(json.dumps({'error': type(error).__name__+': '+str(error)}), flush=True)


if __name__ == '__main__':
    main()

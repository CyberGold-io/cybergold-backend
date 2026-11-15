"""Internal pipe worker: pure graph recipes only, never network or pricing."""
import json
import base64
import io
import pickle
import sys

from .cooperative import finish, QUANTUM
from .cpu import batch_routes
from .discovery import _enumerate_path_steps
from ..routing_encoding import ZERO
from ..uniswap_routes import pool_identity
from .prepared_nomination import prepare_rows


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
            value = json.loads(line)
            if value.get('operation') == 'prepare':
                # The matching parent is the only writer of this internal pipe.
                rows = pickle.loads(base64.b64decode(value['captured']))
                buffer = io.BytesIO()
                encoder = pickle.Pickler(buffer, protocol=5)
                chunk = []
                for prepared in prepare_rows(rows):
                    chunk.append(prepared)
                    if len(chunk) == QUANTUM:
                        buffer.seek(0)
                        buffer.truncate()
                        encoder.dump(chunk)
                        print(json.dumps({'prepared': base64.b64encode(buffer.getvalue()).decode()}), flush=True)
                        chunk = []
                if chunk:
                    buffer.seek(0)
                    buffer.truncate()
                    encoder.dump(chunk)
                    print(json.dumps({'prepared': base64.b64encode(buffer.getvalue()).decode()}), flush=True)
                print('{"done":true}', flush=True)
                continue
            for routes in batch_routes(enumerate_recipes(value)):
                print(json.dumps({'routes': routes}, separators=(',', ':')), flush=True)
            print('{"done":true}', flush=True)
        except Exception as error:
            print(json.dumps({'error': type(error).__name__+': '+str(error)}), flush=True)


if __name__ == '__main__':
    main()

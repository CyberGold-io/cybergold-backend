"""Internal pipe worker: pure recipes and ABI parameters, never RPC or pricing."""
import json
import base64
import io
import pickle
import sys
import time

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
    contract, contract_abi = None, None
    for line in sys.stdin:
        try:
            value = json.loads(line)
            if value.get('operation') == 'encode-plan':
                from web3 import Web3
                from .plan_call import _compile_params
                arguments, abi = pickle.loads(base64.b64decode(value['captured']))
                started, cpu_started = time.perf_counter(), time.thread_time()
                try:
                    if contract is None or contract_abi != abi:
                        contract = Web3().eth.contract(abi=abi)
                        contract_abi = abi
                    params = _compile_params(*arguments, contract)
                except Exception as error:
                    result = {'encodingError': base64.b64encode(pickle.dumps(error, protocol=5)).decode()}
                else:
                    result = {'encoded': json.dumps(params, separators=(',', ':'))}
                result.update(wallMs=(time.perf_counter()-started)*1000,
                              threadCpuMs=(time.thread_time()-cpu_started)*1000)
                print(json.dumps(result, separators=(',', ':')), flush=True)
                continue
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

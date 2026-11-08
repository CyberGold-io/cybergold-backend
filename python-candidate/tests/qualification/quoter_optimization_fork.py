"""Implemented funding/prefix constructors -> real local router receipts.

The authenticated upstream is used only for historical reads. All deployment,
liquidity, funding and execution transactions target this process' owned Anvil.
No signed wallet material or shared Sandbox/Mainnet writes are used.
"""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from web3 import Web3

BACKEND = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BACKEND / 'python-candidate/src'), str(BACKEND / 'python-candidate/tests')]
import universal_fork as fixture
from quoter_fixture import historical_data
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.amm import PartialPath
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.funding import reconstruct
from cybergold_candidate.quoter.prefix import repair_prefix
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.tx_preparation import compile_execution
from cybergold_candidate.uniswap_state import PoolRegistry

USDT = '0xdAC17F958D2ee523a2206206994597C13D831ec7'
PAXG = '0x45804880De22913dAFE09f4980848ECE6EcbAf78'
V2_FACTORY = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
V3_FACTORY = '0x1F98431c8aD98523631AE4a59f267346ea31F984'
NPM = '0xC36442b4a4522E871399CD717aBDD847Ab11FE88'


def call(w3, sender, target, signature, types, values):
    return fixture.send(w3, sender, to=target, data=Web3.keccak(text=signature)[:4] + w3.codec.encode(types, values))


async def qualify(url, result):
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 60}))
    admin = w3.eth.accounts[0]
    payer = Web3.to_checksum_address(os.urandom(20).hex())
    w3.provider.make_request('anvil_impersonateAccount', [payer])
    w3.provider.make_request('anvil_setBalance', [payer, hex(10**21)])
    helpers, adapter = fixture.deploy_helpers(w3, admin)
    config = json.loads((BACKEND.parent / 'cybergold-protocol/config/deploy-config.json').read_text())
    token_funding = config['fork']['funding']['tokenFunding']
    holder = Web3.to_checksum_address(token_funding['holders'][token_funding['symbols'].index('USDT')])
    w3.provider.make_request('anvil_impersonateAccount', [holder])
    w3.provider.make_request('anvil_setBalance', [holder, hex(10**18)])
    try:
        call(w3, holder, USDT, 'transfer(address,uint256)', ['address', 'uint256'], [payer, 2_000_000_000])
    finally:
        w3.provider.make_request('anvil_stopImpersonatingAccount', [holder])
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=fixture.CORE,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=helpers.address, CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=adapter,
        RPC_URL=url, RPC_AUTHORIZATION=None)
    result['deployment'] = {'helpers': helpers.address, 'adapter': adapter, 'scope': 'fresh local Helpers'}
    snapshot = w3.provider.make_request('evm_snapshot', [])['result']

    async def execute(label, quote):
        compiled = compile_execution(quote, recipient=payer, deadline=w3.eth.get_block('latest').timestamp + 600)
        fixture.approve(w3, payer, quote['inputs'][0]['currency'], helpers.address, int(quote['inputs'][0]['amount']))
        actual = fixture.execute(w3, payer, helpers, compiled, label)
        tx = w3.eth.get_block('latest').transactions[-1]
        receipt = w3.eth.get_transaction_receipt(tx)
        result['cases'].append({'case': label, 'quote': quote, 'receipt': {
            'transactionHash': Web3.to_hex(tx), 'status': receipt.status, 'gasUsed': receipt.gasUsed},
            'actualFees': {key: str(actual[key]) for key in quote['fees']},
            'exactBalanceFeeRetentionVerifier': 'passed'})

    data = historical_data()
    case = data['cases'][0]
    direct = next(row for row in case['routes'] if row['output'] == '1512123003848321271')
    route = [{'pool': deepcopy(case['inventory'][hop['pool']]), 'zeroForOne': hop['zeroForOne']} for hop in direct['hops']]
    direct_plan = market_plan(USDT, fixture.CORE, route, 500000000)
    choices = [('direct-funding', case['request'], direct_plan)] + [
        ('mixed-' + row['order'], row['original']['request'], row['original']['plan']) for row in data['mixed']]
    for label, request, selected in choices:
        w3.provider.make_request('evm_revert', [snapshot])
        snapshot = w3.provider.make_request('evm_snapshot', [])['result']
        registry = PoolRegistry(settings); engine = RouteQuoteEngine(settings, registry); q = Quoter(settings, engine)
        try:
            block = await registry.get_rpc().block(None)
            assets, weights = await q.basis(block)
            original = await q.candidate(request, 100, 'core-first', block, assets, weights, selected=selected)
            reduced = await reconstruct(q, original, block, assets, weights, {})
            assert reduced['quotedOutput'] == original['quotedOutput']
            assert int(reduced['inputs'][0]['amount']) < int(original['inputs'][0]['amount'])
            assert not reduced['estimatedRetainedInputCharges']
            await execute(label, reduced)
        finally:
            await engine.close(); await registry.close()

    # A real V2 prefix followed by newly minted narrow V3 liquidity creates
    # positive intermediate partial consumption on the owned fork. The final
    # token is real CYGLD; only A/B are local synthetic ERC20s.
    token_a = fixture.deploy(w3, admin, 'MockERC20', 'Prefix A', 'PXA', 18)
    token_b = fixture.deploy(w3, admin, 'MockERC20', 'Prefix B', 'PXB', 18)
    for token in (token_a, token_b):
        call(w3, admin, token.address, 'mint(address,uint256)', ['address', 'uint256'], [admin, 10**12])
    call(w3, admin, token_a.address, 'mint(address,uint256)', ['address', 'uint256'], [payer, 10000])
    call(w3, admin, V2_FACTORY, 'createPair(address,address)', ['address', 'address'], [token_a.address, token_b.address])
    raw = w3.eth.call({'to': V2_FACTORY, 'data': Web3.keccak(text='getPair(address,address)')[:4]
        + w3.codec.encode(['address', 'address'], [token_a.address, token_b.address])})
    pair = Web3.to_checksum_address(w3.codec.decode(['address'], raw)[0])
    for token in (token_a, token_b):
        call(w3, admin, token.address, 'transfer(address,uint256)', ['address', 'uint256'], [pair, 10**9])
    call(w3, admin, pair, 'mint(address)', ['address'], [admin])
    call(w3, payer, fixture.CORE, 'transfer(address,uint256)', ['address', 'uint256'], [admin, 10**9])
    lo, hi = sorted([token_b.address, fixture.CORE], key=str.lower)
    call(w3, admin, NPM, 'createAndInitializePoolIfNecessary(address,address,uint24,uint160)',
         ['address', 'address', 'uint24', 'uint160'], [lo, hi, 3000, 2**96])
    for token in [token_b.address, fixture.CORE]:
        fixture.approve(w3, admin, token, NPM, 10**9)
    mint_type = '(address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,address,uint256)'
    call(w3, admin, NPM, 'mint(' + mint_type + ')', [mint_type],
        [(lo, hi, 3000, -60, 60, 3000, 3000, 0, 0, admin, w3.eth.get_block('latest').timestamp + 600)])
    raw = w3.eth.call({'to': V3_FACTORY, 'data': Web3.keccak(text='getPool(address,address,uint24)')[:4]
        + w3.codec.encode(['address', 'address', 'uint24'], [lo, hi, 3000])})
    pool3 = Web3.to_checksum_address(w3.codec.decode(['address'], raw)[0])
    def pool(a, b, address, protocol):
        a, b = sorted([a, b], key=str.lower)
        return {'id': address, 'address': address, 'protocol': protocol, 'feePips': 3000, 'tickSpacing': 60,
                'token0': {'address': a, 'decimals': 18}, 'token1': {'address': b, 'decimals': 18}}
    pools = [pool(token_a.address, token_b.address, pair, 'v2'), pool(token_b.address, fixture.CORE, pool3, 'v3')]
    route = [{'pool': row, 'zeroForOne': source.lower() == row['token0']['address'].lower()}
             for source, row in zip([token_a.address, token_b.address], pools)]
    registry = PoolRegistry(settings); engine = RouteQuoteEngine(settings, registry); q = Quoter(settings, engine)
    try:
        block = await registry.get_rpc().block(None)
        request = {'intent': 0, 'inputs': [{'currency': token_a.address, 'amount': '10000'}], 'outputCurrency': fixture.CORE}
        try:
            with capture_paths():
                await q.candidate(request, 0, 'core-first', block, [], [],
                    selected=market_plan(token_a.address, fixture.CORE, route, 10000))
        except PartialPath as error:
            proposal = await repair_prefix(q, request, error.trace, block)
        else:
            raise AssertionError('Expected positive intermediate partial consumption')
        assert proposal is not None
        funding, selected = proposal
        repaired = await q.candidate({**request, 'inputs': funding}, 0, 'core-first', block, [], [], selected=selected)
        repaired['request'] = request
        assert not repaired['estimatedRetainedInputCharges']
        await execute('backward-prefix-local-v2-v3', repaired)
    finally:
        await engine.close(); await registry.close()
    result['result'] = 'passed'


def main(args):
    result = {'scope': __doc__, 'result': 'running', 'cases': [], 'mainnetWrites': 0,
              'forkBlock': 26299298, 'ownedForkStopped': False}
    process = None
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        url = 'http://127.0.0.1:' + str(port)
        with tempfile.TemporaryDirectory(prefix='cybergold-optimization-fork-') as directory:
            with open(Path(directory) / 'anvil.log', 'w') as log:
                process = subprocess.Popen([str(Path.home() / '.foundry/bin/anvil'),
                    '--fork-url', os.environ['MAINNET_RPC_URL'], '--fork-block-number', '26299298',
                    '--chain-id', '31338', '--host', '127.0.0.1', '--port', str(port), '--silent'], stdout=log, stderr=log)
                local = Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 2}))
                for _ in range(100):
                    try:
                        if local.eth.chain_id == 31338:
                            break
                    except Exception:
                        time.sleep(.1)
                else:
                    raise TimeoutError('Owned fork startup')
                asyncio.run(qualify(url, result))
    except Exception as error:
        result.update(result='failed', errorType=type(error).__name__)
        if isinstance(error, AssertionError):
            result['assertion'] = str(error)[:500]
        import traceback
        result['traceback'] = traceback.format_exc()
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            result['ownedForkStopped'] = process.poll() is not None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('cases', 'traceback')}), flush=True)
    return 0 if result['result'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))

"""Backend quote/compiler -> actual Core + Universal Router, disposable Anvil only.

Run from the Backend root through Ops' with-authenticated-rpc.sh. MAINNET_RPC_URL
is consumed only by Anvil's read-only fork transport. All transactions use this
process' new loopback Anvil and its unlocked disposable accounts, without keys.
This is an explicit integration qualification, not an ordinary unit-test gate.
"""
import asyncio
from collections import defaultdict
import hashlib
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
from eth_utils.abi import event_abi_to_log_topic, collapse_if_tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from cybergold_candidate.helpers_execution import argument
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.universal_quote import UniversalQuotes, ZERO

CORE = '0x601da021cAF3DB5AA63e700D239b5935C370601d'
WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
PERMIT2 = '0x000000000022D473030F116dDEE9F6B43aC78BA3'
ROUTER = '0xab863E752Bf67D8DCDD929EaAe9Be9dc83Fb3BbB'
PIN = 26164733
HELPERS = Path(__file__).resolve().parents[4] / 'cybergold-helpers-universal-exact-in'


def artifact(name):
    return json.loads((HELPERS / 'out' / f'{name}.sol' / f'{name}.json').read_text())


def send(w3, account, **transaction):
    tx = w3.eth.send_transaction({'from': account, 'gas': 16_000_000, **transaction})
    receipt = w3.eth.wait_for_transaction_receipt(tx)
    assert receipt.status == 1, f'Local transaction reverted: {tx.hex()}'
    return receipt


def deploy(w3, account, name, *args):
    value = artifact(name)
    code = value['bytecode']['object'].removeprefix('0x')
    for libraries in value['bytecode'].get('linkReferences', {}).values():
        for library, locations in libraries.items():
            linked = deploy(w3, account, library).address[2:]
            for location in locations:
                begin = location['start'] * 2
                code = code[:begin] + linked + code[begin + location['length'] * 2:]
    factory = w3.eth.contract(abi=value['abi'], bytecode='0x'+code)
    receipt = send(w3, account, data=factory.constructor(*args).data_in_transaction)
    return w3.eth.contract(address=receipt.contractAddress, abi=value['abi'])


def deploy_helpers(w3, admin):
    roles = {'cut': 'DiamondCutOwnerLiveFacet', 'loupe': 'ProtocolDiamondLoupeFacet',
             'ownership': 'OwnershipFacet', 'pause': 'OwnerPausableFacet', 'admin': 'RouterAdminFacet',
             'issuePreview': 'RouterIssuePreviewFacet', 'issue': 'RouterIssueFacet',
             'issueBasket': 'RouterIssueBasketFacet', 'redeem': 'RouterRedeemFacet',
             'redeemBasket': 'RouterRedeemBasketFacet', 'recoveryShareReceiver': 'RecoveryShareReceiverFacet'}
    facets = {}
    for role, name in roles.items():
        constructor = next((row for row in artifact(name)['abi'] if row['type'] == 'constructor'), None)
        facets[role] = deploy(w3, admin, name, *([PERMIT2] if constructor and constructor['inputs'] else [])).address
    init = deploy(w3, admin, 'DiamondLiveInit')
    metadata = json.loads((HELPERS / 'generated/abi/HelpersDiamond.json').read_text())
    grouped = defaultdict(list)
    for row in metadata['selectors']:
        grouped[row['facet']].append(row['selector'])
    cut = [(facets[role], 0, selectors) for role, selectors in grouped.items()]
    config = {'owner': admin, 'requirePristineShell': False, 'expectedSelectorCount': len(metadata['selectors']),
              'coreDiamond': CORE, 'wrappedNative': WETH, 'helperFeePpm': 5000, 'approvedAdapters': [],
              **{f'{role if role != "pause" else "pausable"}Facet': address for role, address in facets.items() if role != 'cut'}}
    init_method = next(row for row in init.abi if row.get('name') == 'init')
    init_data = init.encode_abi('init', args=[argument(config, init_method['inputs'][0])])
    diamond = deploy(w3, admin, 'HelpersDiamond', cut, (admin, init.address, init_data))
    adapter = deploy(w3, admin, 'UniswapRoutingAdapter', diamond.address, ROUTER, PERMIT2, WETH)
    trade = deploy(w3, admin, 'TradeExactInFacet', PERMIT2, adapter.address)
    market = deploy(w3, admin, 'MarketSwapFacet', PERMIT2)
    entries = metadata['abi'] + artifact('ITradeExactInput')['abi'] + artifact('MarketSwapFacet')['abi']
    abi = list({(row['type'], row.get('name'), tuple(collapse_if_tuple(value) for value in row.get('inputs', []))): row for row in entries}.values())
    helpers = w3.eth.contract(address=diamond.address, abi=abi)
    signature = next(key for key in artifact('TradeExactInFacet')['methodIdentifiers'] if key.startswith('executeExactInput('))
    selector = Web3.keccak(text=signature)[:4]
    market_signature = next(key for key in artifact('MarketSwapFacet')['methodIdentifiers'] if key.startswith('swapExactOutput('))
    market_selector = Web3.keccak(text=market_signature)[:4]
    send(w3, admin, to=helpers.address, data=helpers.encode_abi('diamondCut', args=[[
        (trade.address, 0, [selector]), (market.address, 0, [market_selector])], ZERO, b'']))
    send(w3, admin, to=helpers.address, data=helpers.encode_abi('setAdapterApproval', args=[adapter.address, False, True]))
    return helpers, adapter.address


def balances(w3, helpers, currencies):
    values = {}
    abi = [{'type': 'function', 'name': 'balanceOf', 'stateMutability': 'view',
            'inputs': [{'type': 'address', 'name': 'owner'}], 'outputs': [{'type': 'uint256', 'name': ''}]}]
    for currency in currencies:
        values[currency.lower()] = w3.eth.get_balance(helpers) if currency.lower() == ZERO else w3.eth.contract(
            address=Web3.to_checksum_address(currency), abi=abi).functions.balanceOf(helpers).call()
    return values


def approve(w3, payer, token, spender, amount):
    data = Web3.keccak(text='approve(address,uint256)')[:4] + w3.codec.encode(['address', 'uint256'], [spender, amount])
    send(w3, payer, to=Web3.to_checksum_address(token), data=data)


def execute(w3, payer, helpers, quote, label):
    plan = quote['plan']
    permit = {'value': '0', 'deadline': '0', 'v': 0, 'r': '0x'+'00'*32, 's': '0x'+'00'*32}
    funding = {'authorizations': [{'kind': 0, 'permit': permit} for _ in plan['inputs']],
               'permit2': {'permit': {'permitted': [], 'nonce': '0', 'deadline': '0'}, 'signature': '0x'}}
    method = next(row for row in helpers.abi if row.get('name') == 'executeExactInput')
    args = [argument(value, parameter) for value, parameter in zip([plan, funding], method['inputs'], strict=True)]
    currencies = {row['currency'] for row in plan['inputs']} | {plan['outputCurrency']} | {
        row['currency'] for row in quote['estimatedRetainedInputCharges']} | {
        row['token'] for row in quote['estimatedRecipientOutputs'] if row['kind'] == 0}
    before = balances(w3, helpers.address, currencies)
    payer_before = balances(w3, payer, currencies)
    value = sum(int(row['amount']) for row in plan['inputs'] if row['currency'].lower() == ZERO)
    call = helpers.functions.executeExactInput(*args)
    simulated = call.call({'from': payer, 'value': value})
    receipt = send(w3, payer, to=helpers.address, value=value, data=call._encode_transaction_data())
    topic = event_abi_to_log_topic(next(row for row in helpers.abi if row.get('name') == 'ExactInputExecuted'))
    # Decode through the shipped event ABI; underlying Core/pool logs are unrelated.
    decoded = [helpers.events.ExactInputExecuted().process_log(log)['args'] for log in receipt.logs
               if log['address'].lower() == helpers.address.lower() and log['topics'][0] == topic]
    assert len(decoded) == 1, (label, 'aggregate event missing')
    actual = decoded[0]['result']
    actual_output = sum(int(row['amount']) for row in actual['recipientOutputs'] if row['kind'] == 0 and
                        row['token'].lower() == plan['outputCurrency'].lower())
    if plan['intent'] != 3:
        assert actual_output == int(quote['quotedOutput']), (label, 'SDK/Core quote differs', actual_output, quote['quotedOutput'])
        assert actual_output >= int(plan['minimumOutput'])
    else:
        assert list(actual['recipientOutputs']) == [dict(row, id=int(row['id']), amount=int(row['amount']))
                                                  for row in quote['estimatedRecipientOutputs']]
        for row, bound in zip(actual['recipientOutputs'], quote['planDescription']['expectedOutputs'], strict=True):
            assert int(row['amount']) >= int(bound['minimumAmount'])
    actual_retained = [(int(row['branch']), int(row['stage']), row['currency'].lower(), int(row['amount'])) for row in actual['retainedInputs']]
    expected_retained = [(int(row['branch']), int(row['stage']), row['currency'].lower(), int(row['amount'])) for row in quote['estimatedRetainedInputCharges']]
    assert actual_retained == expected_retained, (label, actual_retained, expected_retained)
    for field in ('coreProtocolFeeCygld', 'coreHelpersFeeCygld', 'marketFeeCygld'):
        assert actual[field] == int(quote['fees'][field]), (label, field, actual[field], quote['fees'][field])
    after = balances(w3, helpers.address, currencies)
    payer_after = balances(w3, payer, currencies)
    for currency in before:
        assert after[currency] - before[currency] == sum(row[3] for row in actual_retained if row[2] == currency), (label, 'treasury delta', currency)
        received = sum(int(row['amount']) for row in actual['recipientOutputs'] if row['kind'] == 0 and row['token'].lower() == currency)
        funded = sum(int(row['amount']) for row in plan['inputs'] if row['currency'].lower() == currency)
        gas = receipt.gasUsed * receipt.effectiveGasPrice if currency == ZERO else 0
        assert payer_after[currency] - payer_before[currency] + gas == received - funded, (label,
            'gross funding/output balance', currency, {'before': payer_before[currency], 'after': payer_after[currency],
            'gas': gas, 'gasUsed': receipt.gasUsed, 'effectiveGasPrice': receipt.effectiveGasPrice,
            'received': received, 'funded': funded, 'difference': payer_after[currency]-payer_before[currency]+gas-received+funded})
    assert actual['retainedCustodian'] == helpers.address
    assert actual['feeBeneficiaryAtSettlement'] == helpers.functions.owner().call()
    assert len(simulated[1]) == len(actual['stages'])
    print(json.dumps({'case': label, 'intent': plan['intent'], 'routeFamily': quote['routeFamily'],
                      'quotedOutput': quote['quotedOutput'], 'actualOutput': str(actual_output),
                      'minimumOutput': plan['minimumOutput'], 'retainedInputs': actual_retained,
                      'recipientOutputs': [dict(row, id=str(row['id']), amount=str(row['amount'])) for row in actual['recipientOutputs']],
                      'fees': {field: str(actual[field]) for field in quote['fees']},
                      'stages': len(actual['stages']), 'gasUsed': receipt.gasUsed}), flush=True)
    return actual


async def qualify(url, deployment=None):
    w3 = Web3(Web3.HTTPProvider(url))
    chain_id = w3.eth.chain_id
    entry = w3.eth.get_block('latest')
    context = {'mode': 'standalone-pinned-fork' if deployment is None else 'owned-staged-fork',
               'entryBlockNumber': entry.number, 'entryBlockHash': Web3.to_hex(entry.hash)}
    admin = w3.eth.accounts[0]
    # Well-known Anvil addresses can have real Mainnet EIP7702 code at a fork
    # snapshot. Use a fresh fork-only impersonated payer, with no signing key.
    payer = Web3.to_checksum_address(os.urandom(20).hex())
    w3.provider.make_request('anvil_impersonateAccount', [payer])
    w3.provider.make_request('anvil_setBalance', [payer, hex(10_000 * 10**18)])
    if deployment is None:
        helpers, adapter = deploy_helpers(w3, admin)
    else:
        metadata = json.loads((HELPERS / 'generated/abi/HelpersDiamond.json').read_text())
        entries = metadata['abi'] + artifact('ITradeExactInput')['abi'] + artifact('MarketSwapFacet')['abi']
        abi = list({(row['type'], row.get('name'), tuple(collapse_if_tuple(value) for value in row.get('inputs', []))): row for row in entries}.values())
        helpers = w3.eth.contract(address=Web3.to_checksum_address(deployment['helpers']), abi=abi)
        adapter = Web3.to_checksum_address(next(row['address'] for row in deployment['creations'] if row['id'] == 'routingAdapter'))
    identities = {name: hashlib.sha256(artifact(name)['bytecode']['object'].encode()).hexdigest() for name in (
        'TradeExactInFacet', 'CoreIssueExecution', 'TradeRouteEncoding', 'UniswapRoutingAdapter', 'MarketSwapFacet')}
    selector_count = sum(len(row[1]) for row in helpers.functions.facets().call())
    # A staged-release exercise runs before legacy selector retirement; the
    # standalone fresh deployment already contains the candidate's final45.
    if deployment is None:
        assert selector_count == 45
    print(json.dumps({'stage': 'local-deployment-complete', 'helpers': helpers.address,
                      'selectorCount': selector_count, 'creationTemplateSha256': identities,
                      'executionContext': context,
                      **({'forkBlock': PIN, 'forkBlockHash': Web3.to_hex(w3.eth.get_block(PIN).hash)}
                         if deployment is None else {})}), flush=True)
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=str(chain_id), NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=helpers.address, CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=adapter,
        RPC_URL=url, RPC_AUTHORIZATION=None)
    registry = PoolRegistry(settings)
    engine = RouteQuoteEngine(settings, registry)
    quotes = UniversalQuotes(settings, engine)
    original_price = quotes.price_path
    failed_paths = 0
    async def observed_price(*args, **kwargs):
        nonlocal failed_paths
        try:
            return await original_price(*args, **kwargs)
        except Exception as error:
            if failed_paths < 8:
                print(json.dumps({'stage': 'route-pricing', 'error': type(error).__name__, 'message': str(error),
                                  'protocols': [hop.get('pool', {}).get('protocol', hop.get('kind')) for hop in args[0]]}), flush=True)
                failed_paths += 1
            raise
    quotes.price_path = observed_price
    try:
        rpc = registry.get_rpc()
        block = await rpc.block(None)
        assets, weights = await quotes.basis(block)
        deadline = str(int(w3.eth.get_block('latest').timestamp) + 3600)
        request = {'intent': 0, 'inputs': [{'currency': ZERO, 'amount': str(10**16)}],
                   'outputCurrency': CORE, 'recipient': payer, 'deadline': deadline, 'slippageBps': 100}
        # Exercise the public search/compiler first; also execute a requested 50/50
        # candidate to qualify shared-pool state replay even when another grid point wins.
        try:
            winner = await quotes.get(request)
            print(json.dumps({'case': 'public-search', 'routeFamily': winner['routeFamily'],
                              'quotedOutput': winner['quotedOutput'], 'searchCoverage': winner['searchCoverage']}), flush=True)
        except Exception as error:
            print(json.dumps({'stage': 'cold-public-search', 'error': type(error).__name__, 'message': str(error),
                              'inventoryCount': len(registry.inventory)}), flush=True)
            winner = await quotes.get(request)
        execute(w3, payer, helpers, winner, 'native-buy-public-quote')
        block = await rpc.block(None)
        buy = await quotes.candidate(request, 50, 'core-first', block, assets, weights, first=True)
        acquired = execute(w3, payer, helpers, buy, 'native-buy-mixed-core-first')
        cygld = sum(int(row['amount']) for row in acquired['recipientOutputs'] if row['token'].lower() == CORE.lower())
        sale_amount = cygld // 3
        approve(w3, payer, CORE, helpers.address, sale_amount)
        sale_request = {**request, 'intent': 1, 'inputs': [{'currency': CORE, 'amount': str(sale_amount)}], 'outputCurrency': ZERO}
        sale_public = await quotes.get(sale_request)
        execute(w3, payer, helpers, sale_public, 'native-sale-public-quote')
        approve(w3, payer, CORE, helpers.address, sale_amount)
        block = await rpc.block(None)
        sale = await quotes.candidate(sale_request, 50, 'market-first', block, assets, weights, first=True)
        execute(w3, payer, helpers, sale, 'native-sale-mixed-market-first')
        redeem_amount = cygld // 3
        approve(w3, payer, CORE, helpers.address, redeem_amount)
        basket_request = {**sale_request, 'intent': 3, 'inputs': [{'currency': CORE, 'amount': str(redeem_amount)}]}
        redeem = await quotes.get(basket_request)
        basket = execute(w3, payer, helpers, redeem, 'basket-redeem-public-quote')
        amounts = {row['token'].lower(): int(row['amount']) for row in basket['recipientOutputs'] if row['kind'] == 0}
        for asset in assets:
            approve(w3, payer, asset, helpers.address, amounts.get(asset.lower(), 0))
        issue_request = {**request, 'intent': 2, 'inputs': [{'currency': asset, 'amount': str(amounts.get(asset.lower(), 0))} for asset in assets]}
        issue = await quotes.get(issue_request)
        execute(w3, payer, helpers, issue, 'basket-issue-public-quote')
        print(json.dumps({'qualification': 'passed', 'executionContext': context,
                          **({'forkBlock': PIN} if deployment is None else {}), 'localChainId': chain_id,
                          'helpers': helpers.address, 'adapter': adapter,
                          'sdkRequestCount': engine.sdk.sequence, 'executedCases': 6,
                          'publicQuoteExecutions': 4, 'explicitGridCandidateExecutions': 2}), flush=True)
    finally:
        try:
            await engine.close()
            await registry.close()
        finally:
            w3.provider.make_request('anvil_stopImpersonatingAccount', [payer])


def main():
    if os.environ.get('OWNED_FORK_RPC_URL'):
        deployment = json.loads(Path(os.environ['HELPERS_EXACT_INPUT_DEPLOYMENT']).read_text())
        # SdkWorker's relative command uses the Backend repository root.
        os.chdir(Path(__file__).resolve().parents[3])
        asyncio.run(qualify(os.environ['OWNED_FORK_RPC_URL'], deployment))
        return
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(['anvil', '--fork-url', os.environ['MAINNET_RPC_URL'], '--fork-block-number', str(PIN),
            '--chain-id', '31338', '--port', str(port), '--silent'], stdout=log, stderr=log)
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError('Owned Anvil exited during startup')
                try:
                    if Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 1})).is_connected():
                        break
                except Exception:
                    pass
                time.sleep(.1)
            asyncio.run(qualify(url))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()

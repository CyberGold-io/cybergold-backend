"""Pure preparation of a complete Helpers eth_call; no network or scheduling."""
from copy import deepcopy
from dataclasses import dataclass
from ..exact_input_plan import compile_plan
from ..helpers_execution import ABI, argument
from ..market_fee import get_market_fee_rate, routed_sell_budget
from ..routing_encoding import ZERO
from .simulation_funding import funding_overrides, SIMULATION_SENDER

METHOD = next(row for row in ABI if row.get('name') == 'executeExactInput')
EMPTY_PERMIT = {'value': 0, 'deadline': 0, 'v': 0, 'r': '0x'+'00'*32, 's': '0x'+'00'*32}

def funding_bundle(inputs):
    return {'authorizations': [{'kind': 0, 'permit': EMPTY_PERMIT} for _ in inputs],
            'permit2': {'permit': {'permitted': [], 'nonce': 0, 'deadline': 0}, 'signature': '0x'}}


def executable_body(body, accepted_core=None):
    """Encode existing Core identities and route bounds without a second price."""
    body = deepcopy(body)
    supplied = iter(accepted_core) if accepted_core is not None else None
    def visit(node):
        if isinstance(node, list):
            for row in node:
                visit(row)
        elif isinstance(node, dict):
            if 'expectedOutputs' in node:
                node['expectedOutputs'] = [deepcopy(next(supplied)) if supplied is not None else
                    {**{key: row[key] for key in ('kind', 'token', 'id')}, 'minimumAmount': '0'}
                    for row in node['expectedOutputs']]
            if 'inputCurrency' in node and 'outputCurrency' in node and 'routes' in node:
                node['minimumOutput'] = '0'
            for key, value in node.items():
                if key != 'expectedOutputs':
                    visit(value)
    visit(body)
    return body


def neutralize_buy_fees(request, body, chain):
    """Buy fees are output arithmetic; sell fees determine actual AMM funding."""
    if request['intent'] in (0, 1):
        for branch in body['branches']:
            if branch['kind'] == 1:
                rate = get_market_fee_rate(chain, request['inputs'][0]['currency'],
                                           request['outputCurrency'], 'exact-in')
                branch['data']['feeCygld'] = str(routed_sell_budget(int(branch['amountIn']), rate)[1]
                                               if request['intent'] == 1 else 0)
            elif request['intent'] == 0:
                for row in branch['data']['continuations']:
                    row['feeCygld'] = '0'
    elif request['intent'] == 2:
        for row in body['continuations']:
            row['feeCygld'] = '0'


@dataclass
class PreparedPlanCall:
    plan: dict
    params: list
    block_tag: object


def compile_call(request, selected, *, chain, helpers, core, contract, block=None,
                 pricing=True, minimum=None, accepted_core=None, recipient=None):
    plan = deepcopy(selected)
    if pricing:
        neutralize_buy_fees(request, plan['body'], chain)
    if minimum is None:
        # Core's share-only redemption accepts zero scalar output. The
        # contract itself rejects zero minima when positive ERC20 output
        # exists, and Market branches require a positive scalar minimum.
        share_only = request['intent'] == 1 and all(branch['kind'] == 0 and all(
            int(row['kind']) != 0 or int(row.get('amount', row.get('minimumAmount', '0'))) == 0
            for row in branch['data']['expectedOutputs']) for branch in plan['body']['branches'])
        minimum = 0 if share_only else 1
    body = executable_body(plan['body'], accepted_core)
    compiled = compile_plan({**request, 'recipient': recipient or SIMULATION_SENDER, 'deadline': '0'},
                            body, minimum if request['intent'] != 3 else 0)
    args = [argument(value, parameter) for value, parameter in zip(
        (compiled, funding_bundle(request['inputs'])), METHOD['inputs'], strict=True)]
    transaction = {'from': SIMULATION_SENDER, 'to': helpers,
                   'data': contract.encode_abi('executeExactInput', args=args), 'gasPrice': '0x0'}
    native = sum(int(row['amount']) for row in request['inputs'] if row['currency'].lower() == ZERO)
    if native:
        transaction['value'] = hex(native)
    tag = {'blockHash': block['hash'], 'requireCanonical': True} if block is not None else 'latest'
    params = [transaction, tag, funding_overrides(request['inputs'], helpers, core)]
    return PreparedPlanCall(plan, params, tag)

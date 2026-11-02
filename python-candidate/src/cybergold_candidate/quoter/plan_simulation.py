"""One Helpers execution call prices a complete plan; SDKs only explore it.

Quote funding is ephemeral. Pool, reserve, supply and contract code are never
overridden. Latest observations deliberately make no canonical-block claim;
transaction preparation performs a fresh latest call with accepted bounds.
"""
from copy import deepcopy
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

from ..exact_input_plan import compile_plan
from ..helpers_execution import ABI, argument
from ..market_fee import get_market_fee_rate, quoted_fee, routed_sell_budget
from ..preview_errors import preview_error
from ..quote_errors import rpc_failure
from ..recovery_rpc import abi_value
from ..shared_reads import SharedReads
from ..route_work_slots import engine_work
from ..routing_encoding import ZERO
from .simulation_funding import funding_overrides, SIMULATION_SENDER


METHOD = next(row for row in ABI if row.get('name') == 'executeExactInput')
EMPTY_PERMIT = {'value': 0, 'deadline': 0, 'v': 0, 'r': '0x'+'00'*32, 's': '0x'+'00'*32}
_reads = ContextVar('completed_plan_simulations', default=None)


@asynccontextmanager
async def simulation_scope():
    """Reuse identical completed observations only within this one search."""
    reads = SharedReads()
    token = _reads.set(reads)
    try:
        yield
    finally:
        await reads.close()
        _reads.reset(token)


def funding_bundle(inputs):
    return {'authorizations': [{'kind': 0, 'permit': EMPTY_PERMIT} for _ in inputs],
            'permit2': {'permit': {'permitted': [], 'nonce': 0, 'deadline': 0}, 'signature': '0x'}}


def wire(value):
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(item) for item in value]
    return str(value) if isinstance(value, int) else value


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


class StageProjection:
    """Read Helpers' own ordered conversion stages, including native wrappers."""
    def __init__(self, stages):
        self.stages, self.cursor, self.observations = stages, 0, []

    def take(self):
        row = self.stages[self.cursor]
        self.cursor += 1
        return row

    def conversion(self, source, target, amount, route, operation):
        if not amount or source.lower() == target.lower():
            return amount
        current = amount
        if source.lower() != route['inputCurrency'].lower():
            current = int(self.take()['amountOut'])
        funded, consumed = current, current
        output = current
        if route['inputCurrency'].lower() != route['outputCurrency'].lower():
            stage = self.take()
            funded, consumed, output = map(int, (stage['fundedInput'], stage['consumedInput'], stage['amountOut']))
        self.observations.append({'operation': operation, 'inputCurrency': route['inputCurrency'],
            'fundedInput': str(funded), 'consumedInput': str(consumed),
            'outputCurrency': route['outputCurrency'], 'output': str(output)})
        if output and route['outputCurrency'].lower() != target.lower():
            output = int(self.take()['amountOut'])
        return output


def project_buy_fees(request, body, stages, chain, core):
    """Fee-neutral swaps have identical inputs/state; fees are paid at the end."""
    projection, total, continued = StageProjection(stages), 0, False
    def residuals(assets, continuations, branch):
        nonlocal total, continued
        for index, (asset, row) in enumerate(zip(assets, continuations, strict=True)):
            residual = int(projection.take()['returnedInput'])
            if not residual:
                row['feeCygld'] = '0'
                continue
            gross = projection.conversion(asset, core, residual, row['route'], f'{branch}:residual:{index}')
            fee = quoted_fee(gross, get_market_fee_rate(chain, asset, core, 'exact-in'))
            row['feeCygld'] = str(fee)
            total += fee
            continued = True
    if request['intent'] == 2:
        residuals([row['currency'] for row in request['inputs']], body['continuations'], 0)
    elif request['intent'] == 0:
        for index, branch in enumerate(body['branches']):
            lot, data = int(branch['amountIn']), branch['data']
            if not lot:
                continue
            source = request['inputs'][0]['currency']
            if branch['kind'] == 1:
                gross = projection.conversion(source, core, lot, data['route'], f'{index}:market')
                fee = quoted_fee(gross, get_market_fee_rate(chain, source, core, 'exact-in'))
                data['feeCygld'] = str(fee)
                total += fee
            else:
                for asset_index, (asset, acquisition) in enumerate(zip(data['basketAssets'], data['acquisitions'], strict=True)):
                    projection.conversion(source, asset, int(acquisition['amountIn']), acquisition['route'],
                                          f'{index}:acquire:{asset_index}')
                residuals(data['basketAssets'], data['continuations'], index)
    return total, projection.observations, continued


def project_sell_results(request, body, measured):
    """Replace descriptive Core amounts only with identifiable receipt amounts.

    Conversion stages carry their branch and original funded amount. Recovery
    shares are positive-only and retain output/branch order, but have no branch
    tag. Ambiguous repeated identities remain descriptive rather than acquiring
    an invented per-branch quantity. None of this controls quote eligibility.
    """
    if request['intent'] != 1:
        return [], []
    observations, recorded, identities, shares = [], [], [], []
    known_output, complete = 0, True
    target = request['outputCurrency']

    def record(row, branch, index, amount, source):
        row['amount'] = str(amount)
        recorded.append({'branch': branch, 'index': index,
            **{key: row[key] for key in ('kind', 'token', 'id', 'amount')}, 'source': source})

    for branch_index, branch in enumerate(body['branches']):
        if not int(branch['amountIn']):
            continue
        stages = [row for row in measured['stages'] if int(row['branch']) == branch_index]
        projection = StageProjection(stages)
        data = branch['data']
        if branch['kind'] == 1:
            routed = int(branch['amountIn']) - int(data['feeCygld'])
            known_output += projection.conversion(request['inputs'][0]['currency'], target, routed,
                                                  data['route'], f'{branch_index}:market')
        else:
            outputs = data['expectedOutputs']
            currencies = [row['token'].lower() for row in outputs if int(row['kind']) == 0]
            unique = len(set(currencies)) == len(currencies)
            for index, row in enumerate(outputs):
                if int(row['kind']) != 0:
                    shares.append((branch_index, index, row))
                    continue
                if not unique:
                    # Zero outputs do not append a stage. Repeated currency
                    # descriptors therefore cannot always be assigned a stage.
                    complete = False
                    continue
                source = row['token']
                if source.lower() == target.lower():
                    identities.append((branch_index, index, row))
                    continue
                stage = stages[projection.cursor] if projection.cursor < len(stages) else None
                funded = int(stage['fundedInput']) if stage is not None and stage['inputCurrency'].lower() == source.lower() else 0
                record(row, branch_index, index, funded, 'conversion-funding' if funded else 'no-conversion-stage')
                known_output += projection.conversion(source, target, funded, data['conversions'][index],
                                                       f'{branch_index}:redeem:{index}')
        observations.extend(projection.observations)

    # Identity conversions append no stage. The aggregate receipt proves their
    # amount only when exactly one unknown scalar contribution remains.
    if complete and len(identities) == 1:
        remainder = int(measured['recipientOutputs'][0]['amount']) - known_output
        if remainder >= 0:
            branch, index, row = identities[0]
            record(row, branch, index, remainder, 'scalar-remainder')

    def identity(row):
        return int(row['kind']), row['token'].lower(), int(row['id'])

    groups = {}
    for branch, index, row in shares:
        groups.setdefault(identity(row), []).append((branch, index, row))
    returned = {}
    for row in measured['recoveryShares']:
        returned.setdefault(identity(row), []).append(int(row['amount']))
    for key, rows in groups.items():
        amounts = returned.get(key, [])
        if not amounts:
            amounts = [0] * len(rows)
        elif len(rows) == 1:
            amounts = [sum(amounts)]
        if len(amounts) == len(rows):
            for (branch, index, row), amount in zip(rows, amounts, strict=True):
                record(row, branch, index, amount, 'recovery-shares')
    return observations, recorded


class HelpersPlanSimulation:
    def __init__(self, settings, registry, *, helpers, adapter, core, now, semaphore=None):
        self.settings, self.registry = settings, registry
        self.helpers, self.adapter, self.core, self.now = helpers, adapter, core, now
        self.semaphore = semaphore
        self.contract = Web3().eth.contract(abi=ABI)

    async def __call__(self, request, selected, *, block=None, pricing=True, minimum=None,
                       accepted_core=None, recipient=None, candidate=None):
        plan = deepcopy(selected)
        if pricing:
            neutralize_buy_fees(request, plan['body'], self.registry.chain)
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
        transaction = {'from': SIMULATION_SENDER, 'to': self.helpers,
                       'data': self.contract.encode_abi('executeExactInput', args=args), 'gasPrice': '0x0'}
        native = sum(int(row['amount']) for row in request['inputs'] if row['currency'].lower() == ZERO)
        if native:
            transaction['value'] = hex(native)
        tag = {'blockHash': block['hash'], 'requireCanonical': True} if block is not None else 'latest'
        rpc = self.registry.get_rpc()
        params = [transaction, tag, funding_overrides(request['inputs'], self.helpers, self.core)]
        async def execute():
            if self.semaphore is None:
                response = await rpc.w3.provider.make_request('eth_call', params)
            else:
                async with engine_work(self.semaphore):
                    response = await rpc.w3.provider.make_request('eth_call', params)
            return {**response, 'observedAt': self.now()}
        reads = _reads.get() if block is None and pricing else None
        counts = {'issued': 1, 'coalesced': 0, 'reused': 0}
        if reads is None:
            response = await execute()
        else:
            async def produce(_keys):
                return [await execute()]
            responses, counts = await reads.many([json.dumps(params, sort_keys=True)], produce, retain=True)
            response = responses[0]
        if 'error' in response:
            raise preview_error(response['error']) or rpc_failure(response['error'])
        output = METHOD['outputs'][0]
        decoded = rpc.w3.codec.decode([collapse_if_tuple(output)], bytes.fromhex(response['result'][2:]))[0]
        measured = abi_value(decoded, output)
        # ABI integer fields are normalized at the economic wire boundary below.
        core_amounts = []
        if request['intent'] in (0, 2):
            extra_fee, observations, continued = project_buy_fees(request,
                plan['body'] if pricing else deepcopy(plan['body']), measured['stages'], self.registry.chain, self.core)
            if not pricing:
                extra_fee = 0
        else:
            observations, core_amounts = project_sell_results(request, plan['body'], measured)
            extra_fee, continued = 0, False
        recipients = [{**row, 'kind': int(row['kind']), 'id': str(row['id']), 'amount': str(row['amount'])}
                      for row in measured['recipientOutputs']]
        if request['intent'] == 3:
            # Direct basket output is present in the execution receipt itself;
            # never carry old nomination amounts as a latest basket quote.
            plan['body']['expectedOutputs'] = deepcopy(recipients)
        if extra_fee:
            recipients[0]['amount'] = str(int(recipients[0]['amount']) - extra_fee)
        scalar = int(recipients[0]['amount']) if request['intent'] != 3 else 0
        recovery = [{**row, 'kind': int(row['kind']), 'id': str(row['id']), 'amount': str(row['amount'])}
                    for row in measured['recoveryShares']]
        kinds = {row['kind'] for row in plan['allocations'] if int(row['amountIn'])}
        family = 'mixed' if len(kinds) > 1 or continued else 'market' if kinds == {1} else 'core'
        value = deepcopy(candidate) if candidate is not None else {}
        value.update(strategy='universal', routeFamily=family, operation='executeExactInput',
            settlementPolicy='protocol-retained-input', request=deepcopy(request), plan=plan,
            inputs=deepcopy(request['inputs']), quotedOutput=str(scalar), conversionObservations=observations,
            fees={'coreProtocolFeeCygld': str(measured['coreProtocolFeeCygld']),
                  'coreHelpersFeeCygld': str(measured['coreHelpersFeeCygld']),
                  'marketFeeCygld': str(int(measured['marketFeeCygld']) + extra_fee)},
            estimatedRetainedInputCharges=[{**row, 'branch': int(row['branch']), 'stage': int(row['stage']),
                                           'amount': str(row['amount'])} for row in measured['retainedInputs']],
            estimatedRecipientOutputs=recipients, recoveryShares=recovery,
            deployment={'helpers': self.helpers, 'adapter': self.adapter, 'encoding': 'uniswap-routing-v1'},
            retentionDisclosure={'custodian': self.helpers, 'beneficiary': 'helpers-owner-at-settlement'},
            context={'chainId': self.registry.chain, 'blockNumber': str(block['number']) if block else None,
                     'blockHash': block['hash'] if block else None,
                     'blockTag': tag, 'verification': 'execution-simulation' if not pricing else 'quote-observation',
                     'observedAt': response['observedAt']},
            searchCoverage={**value.get('searchCoverage', {}), 'pricing': 'helpers-execution',
                            'scope': 'selected-inventory', 'maxAmmHops': 3, 'maxCoreInvocations': 1},
            pricingEvidence={'engine': 'helpers-execution', 'rpcCalls': counts['issued'],
                'coalesced': counts['coalesced'], 'reused': counts['reused'], 'funding': 'ephemeral-overrides',
                'feeTreatment': 'policy-output-arithmetic' if pricing and request['intent'] in (0, 2) else 'plan-fees',
                **({'coreOutputAmounts': core_amounts} if core_amounts else {}),
                'rawTradeResult': wire(measured),
                'stages': [{key: str(item) if isinstance(item, int) else item for key, item in row.items()}
                           for row in measured['stages']]})
        if request['intent'] != 2:
            value.update(quotedInput=request['inputs'][0]['amount'], inputMaximum=request['inputs'][0]['amount'])
        return value

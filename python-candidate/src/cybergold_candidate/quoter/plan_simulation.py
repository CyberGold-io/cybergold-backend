"""One Helpers execution call prices a complete plan; SDKs only explore it.

Quote funding is ephemeral. Pool, reserve, supply and contract code are never
overridden. Latest observations deliberately make no canonical-block claim;
transaction preparation performs a fresh latest call with accepted bounds.
"""
from copy import deepcopy

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

from ..helpers_execution import ABI
from ..market_fee import get_market_fee_rate, quoted_fee
from ..preview_errors import KnownPreviewError, preview_error
from ..quote_errors import rpc_failure
from ..recovery_rpc import abi_value
from ..quote_flow import stage
from .plan_call import METHOD, compile_call
from .plan_transport import execute_plan_call
from .pool_directions import conflicting_pool, quote_directions




def wire(value):
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(item) for item in value]
    return str(value) if isinstance(value, int) else value






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


def project_buy_fees(request, body, stages, chain, core, *, core_inputs=None):
    """Fee-neutral swaps have identical inputs/state; fees are paid at the end."""
    projection, total, continued = StageProjection(stages), 0, False
    def residuals(assets, continuations, branch):
        nonlocal total, continued
        for index, (asset, row) in enumerate(zip(assets, continuations, strict=True)):
            measured = projection.take()
            residual = int(measured['returnedInput'])
            if core_inputs is not None:
                core_inputs.append({'branch': branch, 'index': index, 'currency': asset,
                    'acquired': int(measured['fundedInput']),
                    'consumed': int(measured['consumedInput']), 'residual': residual})
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


def project_core_inputs(value, chain):
    """Read Core consumption from the same ordered stages used for buy fees.

    These request-local construction amounts are not additional quote fields.
    Aggregate retained charges can also contain AMM returns, so they cannot
    supply this per-Core, per-asset consumption.
    """
    evidence = value.get('pricingEvidence') or {}
    stages = evidence.get('stages', evidence.get('rawTradeResult', {}).get('stages'))
    if stages is None or value['request']['intent'] not in (0, 2):
        return []
    result = []
    project_buy_fees(value['request'], deepcopy(value['plan']['body']), stages, chain,
                     value['request']['outputCurrency'], core_inputs=result)
    return result


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
        with stage('plan.compile', kind='cpu'):
            call = compile_call(request, selected, chain=self.registry.chain, helpers=self.helpers,
                core=self.core, contract=self.contract, block=block, pricing=pricing,
                minimum=minimum, accepted_core=accepted_core, recipient=recipient)
        rpc = self.registry.get_rpc()
        response, counts = await execute_plan_call(rpc, call.params, semaphore=self.semaphore,
            now=self.now, shared=block is None and pricing)
        with stage('observation.project', kind='cpu'):
            return self.project(request, call.plan, response, counts, rpc=rpc,
                tag=call.block_tag, block=block, pricing=pricing, candidate=candidate)

    def project(self, request, plan, response, counts, *, rpc, tag, block, pricing, candidate):
        if 'error' in response:
            error = preview_error(response['error']) or rpc_failure(response['error'])
            data = response['error'].get('data')
            if isinstance(data, str) and data[:10].lower() == '0xdb8b21c4':
                try:
                    currency, amount = rpc.w3.codec.decode(['address', 'uint256'], bytes.fromhex(data[10:]))
                    # Private search input, not a capacity or output claim.
                    error.unsettled_intermediate = {'currency': currency, 'amount': int(amount)}
                except Exception:
                    pass  # Malformed bytes keep their ordinary contract error.
            raise error
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
        opposed = conflicting_pool(quote_directions(value, self.registry.chain))
        if opposed is not None:
            raise KnownPreviewError('opposed-pool-directions',
                'An exchange pool is used in opposite directions in one trade.',
                constraint={'kind': 'opposed-pool-directions', 'pool': opposed})
        return value

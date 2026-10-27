"""Reprice a selected economic plan, bind accepted guards, then compile it."""
from copy import deepcopy
import time

from .basket_preview import InvalidPreview
from pydantic import BaseModel, Field

from .exact_input_plan import ExactAssetAmount, compile_plan
from .execution_tolerance import DEFAULT_SLIPPAGE_BPS, floor
from .quoter.types import EconomicQuote
from .safe_transaction import Address, UInt


class ExecutionBounds(BaseModel):
    inputs: list[ExactAssetAmount] | None = None
    minimumOutput: UInt | None = None
    expectedCoreOutputs: list[dict] | None = None


class TransactionPreparationRequest(BaseModel):
    quote: EconomicQuote
    sender: Address
    recipient: Address
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)
    acceptedBounds: ExecutionBounds | None = None



def execution_body(value, slippage, accepted_core=None):
    """Add execution guards to an economic body without changing its routes."""
    body = deepcopy(value['plan']['body'])
    supplied = iter(accepted_core) if accepted_core is not None else None

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            if 'expectedOutputs' in node:
                result = []
                for row in node['expectedOutputs']:
                    bound = next(supplied) if supplied is not None else {
                        **{key: row[key] for key in ('kind', 'token', 'id')},
                        'minimumAmount': str(floor(int(row['amount']), slippage))}
                    if any(str(row[key]).lower() != str(bound[key]).lower() for key in ('kind', 'token', 'id')):
                        raise InvalidPreview('Accepted Core output identity changed.')
                    if int(row['amount']) < int(bound['minimumAmount']):
                        raise InvalidPreview('Accepted Core output minimum cannot be met.')
                    result.append(deepcopy(bound))
                node['expectedOutputs'] = result
            if 'inputCurrency' in node and 'outputCurrency' in node and 'routes' in node:
                node['minimumOutput'] = '0'
            for key, item in node.items():
                if key != 'expectedOutputs':
                    visit(item)
    try:
        visit(body)
        if supplied is not None and next(supplied, None) is not None:
            raise InvalidPreview('Accepted Core output identity changed.')
    except StopIteration:
        raise InvalidPreview('Accepted Core output identity changed.') from None
    return body


def core_bounds(value, slippage):
    body = execution_body(value, slippage)
    if value['request']['intent'] == 3:
        return body['expectedOutputs']
    return [row for branch in body.get('branches', []) if branch['kind'] == 0
            for row in branch['data'].get('expectedOutputs', [])]


def compile_execution(value, *, recipient, deadline, slippage=100, minimum=None, accepted_core=None):
    minimum = floor(int(value['quotedOutput']), slippage) if minimum is None else int(minimum)
    if int(value['quotedOutput']) < minimum:
        raise InvalidPreview('Accepted scalar output minimum cannot be met.')
    body = execution_body(value, slippage, accepted_core)
    request = {**value['request'], 'inputs': deepcopy(value['inputs']),
               'recipient': recipient, 'deadline': str(deadline)}
    plan = compile_plan(request, body, minimum)
    result = {key: deepcopy(item) for key, item in value.items() if key not in ('request', 'plan')}
    result.update(plan=plan, planDescription=body, outputMinimum=str(minimum), economicQuote=deepcopy(value))
    return result


class TransactionPreparation:
    def __init__(self, quoter, *, now=None, observe_scope=None):
        self.quoter = quoter
        self.now = now or time.time
        self.observe_scope = observe_scope

    async def prepare(self, payload):
        request = TransactionPreparationRequest.model_validate(payload).model_dump(exclude_none=True)
        if self.observe_scope is not None:
            await self.observe_scope()
        selected = request['quote']
        # Preserve the selected deployment binding. Wallet batches/approvals
        # captured by the caller must never be silently retargeted to another
        # Helpers or routing adapter during preparation.
        if selected['deployment']['helpers'].lower() != self.quoter.helpers.lower():
            raise InvalidPreview('Selected Helpers deployment changed.')
        if selected['deployment']['adapter'].lower() != self.quoter.adapter.lower():
            raise InvalidPreview('Selected routing adapter changed.')
        accepted = request.get('acceptedBounds', {})
        # Bind to the displayed observation before current-state replay. Repricing
        # cannot lower these quantities or enlarge the accepted input vector.
        minimum = accepted.get('minimumOutput', str(floor(int(selected['quotedOutput']), request['slippageBps'])))
        expected = accepted.get('expectedCoreOutputs', core_bounds(selected, request['slippageBps']))
        maxima = accepted.get('inputs', selected['inputs'])
        if len(maxima) != len(selected['inputs']):
            raise InvalidPreview('Accepted input currencies changed.')
        for actual, maximum in zip(selected['inputs'], maxima, strict=True):
            if actual['currency'].lower() != maximum['currency'].lower():
                raise InvalidPreview('Accepted input currencies changed.')
            if int(actual['amount']) > int(maximum['amount']):
                raise InvalidPreview('Accepted input maximum cannot be met.')
        economic_request = {**selected['request'], 'inputs': deepcopy(selected['inputs'])}
        value = await self.quoter.evaluate_selected(economic_request, selected['plan'])
        result = compile_execution(value, recipient=request['recipient'], deadline=int(self.now()) + 600,
                                   slippage=request['slippageBps'], minimum=minimum, accepted_core=expected)
        result['economicQuote'] = value
        result['sender'] = request['sender']
        return result

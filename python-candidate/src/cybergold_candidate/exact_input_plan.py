"""Lossless wire compiler for ITradeExactInput; no wallet authorization policy."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field
from web3 import Web3

from .execution_tolerance import DEFAULT_SLIPPAGE_BPS
from .safe_transaction import Address, UInt

STEP = '(uint8,address,uint24,int24)'
WEIGHTED_ROUTE = f'(uint32,{STEP}[])'
AMM_TEMPLATE = f'(address,address,uint256,{WEIGHTED_ROUTE}[])'
CONTINUATION = f'({AMM_TEMPLATE},uint256)'
ACQUISITION = f'(uint256,{AMM_TEMPLATE})'
CORE_BUY = f'(address[],{ACQUISITION}[],{CONTINUATION}[])'
CORE_OUTPUT = '(uint8,address,uint256,uint256)'
CORE_SELL = f'({CORE_OUTPUT}[],{AMM_TEMPLATE}[])'
MARKET = f'({AMM_TEMPLATE},uint256)'
SCALAR_BODY = '(uint8,uint256,bytes)[]'
PLAN = '(uint8,(address,uint256)[],address,address,uint256,uint256,bytes)'


class ExactAssetAmount(BaseModel):
    currency: Address
    amount: UInt


class UniversalExactInputRequest(BaseModel):
    intent: Literal[0, 1, 2, 3]
    inputs: list[ExactAssetAmount]
    outputCurrency: Address
    recipient: Address
    deadline: UInt
    slippageBps: int = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=10_000, strict=True)


def address(value):
    return Web3.to_checksum_address(value)


def template_tuple(route):
    return (address(route['inputCurrency']), address(route['outputCurrency']), int(route['minimumOutput']), [
        (int(row['sharePpm']), [(int(step['kind']), address(step['currencyOut']), int(step['fee']), int(step['tickSpacing']))
                             for step in row['steps']]) for row in route['routes']])


def continuation_tuple(row):
    return template_tuple(row['route']), int(row['feeCygld'])


def output_tuple(row):
    return int(row['kind']), address(row['token']), int(row['id']), int(row['minimumAmount'])


def encode_body(intent, body):
    codec = Web3().codec
    if intent in (0, 1):
        branches = []
        for branch in body['branches']:
            value = branch['data']
            if branch['kind'] == 1:
                encoded = codec.encode([MARKET], [(template_tuple(value['route']), int(value['feeCygld']))])
            elif intent == 0:
                encoded = codec.encode([CORE_BUY], [(list(map(address, value['basketAssets'])), [
                    (int(row['amountIn']), template_tuple(row['route'])) for row in value['acquisitions']],
                    list(map(continuation_tuple, value['continuations'])))])
            else:
                encoded = codec.encode([CORE_SELL], [(list(map(output_tuple, value['expectedOutputs'])),
                    list(map(template_tuple, value['conversions'])))])
            branches.append((int(branch['kind']), int(branch['amountIn']), encoded))
        return Web3.to_hex(codec.encode([f'({SCALAR_BODY})'], [(branches,)]))
    if intent == 2:
        return Web3.to_hex(codec.encode([f'({CONTINUATION}[])'], [(
            list(map(continuation_tuple, body['continuations'])),)]))
    return Web3.to_hex(codec.encode([f'({CORE_OUTPUT}[])'], [(
        list(map(output_tuple, body['expectedOutputs'])),)]))


def compile_plan(request, body, minimum):
    plan = {name: deepcopy(request[name]) for name in
            ('intent', 'inputs', 'outputCurrency', 'recipient', 'deadline')}
    plan['minimumOutput'] = str(minimum)
    plan['body'] = encode_body(plan['intent'], body)
    # Exercise exactly the uint/address domain that the signed Solidity ABI uses.
    Web3().codec.encode([PLAN], [(plan['intent'], [(address(row['currency']), int(row['amount']))
        for row in plan['inputs']], address(plan['outputCurrency']), address(plan['recipient']),
        int(plan['deadline']), int(plan['minimumOutput']), bytes.fromhex(plan['body'][2:]))])
    return plan

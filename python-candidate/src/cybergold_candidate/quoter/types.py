"""Wallet-free economic request, semantic plan and measured quote types."""
from typing import Literal

from pydantic import BaseModel, Field

from ..exact_input_plan import ExactAssetAmount
from ..safe_transaction import Address, UInt


class EconomicRequest(BaseModel):
    intent: Literal[0, 1, 2, 3]
    inputs: list[ExactAssetAmount] = Field(min_length=1)
    outputCurrency: Address


class PlanAllocation(BaseModel):
    kind: Literal[0, 1]
    amountIn: UInt


class EconomicPlan(BaseModel):
    allocations: list[PlanAllocation]
    # These are selected physical routes, not simulated post-state or calldata.
    conversions: dict[str, dict]
    body: dict


class EconomicQuote(BaseModel):
    request: EconomicRequest
    plan: EconomicPlan
    inputs: list[ExactAssetAmount]
    quotedOutput: UInt
    routeFamily: Literal['core', 'market', 'mixed']
    conversionObservations: list[dict] = Field(default_factory=list)
    estimatedRecipientOutputs: list[dict]
    fees: dict
    estimatedRetainedInputCharges: list[dict]
    recoveryShares: list[dict]
    deployment: dict
    context: dict
    retentionDisclosure: dict
    searchCoverage: dict
    metrics: dict | None = None

    # The public response also retains the familiar economic discriminants.
    strategy: Literal['universal'] = 'universal'
    operation: Literal['executeExactInput'] = 'executeExactInput'
    settlementPolicy: Literal['protocol-retained-input'] = 'protocol-retained-input'
    quotedInput: UInt | None = None
    inputMaximum: UInt | None = None

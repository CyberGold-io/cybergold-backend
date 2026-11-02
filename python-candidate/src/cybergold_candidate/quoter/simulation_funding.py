"""Ephemeral caller funding for Helpers quote simulation; no RPC or wallet state.

Only the synthetic payer's native balance and token balance/Helpers allowance
are changed. Token proxies retain their code, implementations, supply, roles,
pool balances and every other account. Layouts come from the configured tokens'
published source and are qualified with balanceOf/allowance override calls.
"""
from web3 import Web3

from ..app_tokens import TOKENS
from ..routing_encoding import ZERO


SIMULATION_SENDER = Web3.to_checksum_address('0x000000000000000000000000000000000000c0de')
ERC20_STORAGE = int('52c63247e1f47db19d5ce0460030c497f067ca4cebf71ba98eeadabe20bace00', 16)
MAX_UINT256 = (1 << 256) - 1

# Mapping roots, not mapping entries. Proxy tokens hold these at the public
# token address. PAXG V1/V2 preserve roots 1/3; XAUt uses OZ4's storage gaps.
_ROOTS = {dict(TOKENS)[name].lower(): roots for name, roots in (
    ('weth', (3, 4)), ('usdc', (9, 10)), ('usdt', (2, 5)),
    ('paxg', (1, 3)), ('xaut', (51, 52)),
)}


class UnsupportedSimulationFunding(ValueError):
    code = 'unsupported-simulation-funding'

    def __init__(self, currency):
        self.currency = currency
        super().__init__(f'Quote simulation funding is not supported for input currency {currency}.')


def _word(value):
    return '0x' + int(value).to_bytes(32, 'big').hex()


def _mapping(owner, root):
    # Solidity mapping(address => ...) uses two padded 32-byte words.
    return Web3.keccak(bytes.fromhex(owner[2:]).rjust(32, b'\0') + int(root).to_bytes(32, 'big'))


def funding_overrides(inputs, helpers, core):
    """Fund exact positive input lots without changing economic execution state.

    Duplicate currencies share one payer balance and one allowance. Core's
    maximum allowance is not decremented by OZ transferFrom, avoiding a fake
    approval mutation in its separate allowance-exposure accounting. The payer
    is a synthetic EOA; this is quote funding, not real-wallet authorization.
    """
    amounts = {}
    for row in inputs:
        amount = int(row['amount'])
        if amount:
            currency = row['currency'].lower()
            amounts[currency] = amounts.get(currency, 0) + amount
    overrides = {SIMULATION_SENDER: {'balance': hex(amounts.pop(ZERO, 0))}}
    for currency, amount in amounts.items():
        is_core = currency == core.lower()
        roots = (ERC20_STORAGE, ERC20_STORAGE + 1) if is_core else _ROOTS.get(currency)
        if roots is None:
            raise UnsupportedSimulationFunding(Web3.to_checksum_address(currency))
        balance = _mapping(SIMULATION_SENDER, roots[0])
        allowance = _mapping(helpers, int.from_bytes(_mapping(SIMULATION_SENDER, roots[1]), 'big'))
        overrides[Web3.to_checksum_address(currency)] = {'stateDiff': {
            Web3.to_hex(balance): _word(amount),
            Web3.to_hex(allowance): _word(MAX_UINT256 if is_core else amount),
        }}
    return overrides

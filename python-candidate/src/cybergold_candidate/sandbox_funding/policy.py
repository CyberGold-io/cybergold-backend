"""The existing Sandbox faucet allocation, in raw token units."""
from dataclasses import dataclass

CHAIN_ID = 31338
ETH_WEI = 10_000_000_000_000_000_000
COOLDOWN_SECONDS = 900


@dataclass(frozen=True)
class Token:
    symbol: str
    address: str
    amount: int


TOKENS = (
    Token('PAXG', '0x45804880De22913dAFE09f4980848ECE6EcbAf78', 5_000_000_000_000_000_000),
    Token('XAUT', '0x68749665FF8D2d112Fa859AA293F07A622782F38', 5_000_000),
    Token('USDC', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 10_000_000_000),
    Token('USDT', '0xdAC17F958D2ee523a2206206994597C13D831ec7', 10_000_000_000),
)


def allocation(address):
    return {'status': 'ok', 'address': address, 'ethWei': str(ETH_WEI),
            'tokens': [{'symbol': token.symbol, 'amount': str(token.amount)} for token in TOKENS], 'dryRun': False}

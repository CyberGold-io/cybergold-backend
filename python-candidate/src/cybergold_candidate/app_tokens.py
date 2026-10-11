"""The initial App selector catalog, owned by the configured Backend."""
from web3 import Web3

TOKENS = (
    ('xaut', '0x68749665FF8D2d112Fa859AA293F07A622782F38'),
    ('paxg', '0x45804880De22913dAFE09f4980848ECE6EcbAf78'),
    ('usdt', '0xdAC17F958D2ee523a2206206994597C13D831ec7'),
    ('usdc', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'),
    ('weth', '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'),
)
METADATA = {
    'cygld': ('CYGLD', 'CyberGold', 18), 'xaut': ('XAUt', 'Tether Gold', 6),
    'paxg': ('PAXG', 'Paxos Gold', 18), 'usdt': ('USDT', 'Tether USD', 6),
    'usdc': ('USDC', 'USDC', 6), 'eth': ('ETH', 'Ether', 18),
    'weth': ('WETH', 'Wrapped Ether', 18),
}


def configured_tokens(core, chain):
    addresses = {'cygld': core, **dict(TOKENS)}
    rows = []
    for identity in ('cygld', 'xaut', 'paxg', 'usdt', 'usdc', 'eth', 'weth'):
        symbol, name, decimals = METADATA[identity]
        row = {'id': identity, 'symbol': symbol, 'name': name,
               'decimals': decimals, 'chainId': chain,
               'type': 'native' if identity == 'eth' else 'erc20'}
        if identity != 'eth':
            if not addresses[identity]:
                continue
            row['address'] = Web3.to_checksum_address(addresses[identity])
        rows.append(row)
    return rows

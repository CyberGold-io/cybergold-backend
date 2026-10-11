"""Read-only actual-token qualification through the authenticated RPC adapter.

Usage: wrapper --target mainnet -- python native_token_permit.py {RPC_URL} 1 OUTPUT
The same harness accepts an owned local fork RPC and its actual chain ID (1 or
31338); the command-line chain is used for the configured provider observation.
Pass the loopback adapter URL from the wrapper. Keys/signatures
stay in TokenPermitRpc.qualify memory; JSON records observations, never calldata.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from eth_account import Account

from cybergold_candidate.token_permit import TokenObservations
from cybergold_candidate.helpers_router_facts import HelpersRouterFacts
from cybergold_candidate.wallet_balances import TOKENS


async def main():
    url, chain, output = sys.argv[1:]
    config = SimpleNamespace(RPC_URL=url, RPC_AUTHORIZATION=None, NEXT_PUBLIC_CHAIN_ID=chain,
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x' + '8' * 40, NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x30E9aFd21a30b2629bE33508a131aC890368F534')
    observer = TokenObservations(config)
    helpers = HelpersRouterFacts(config)
    # No retained private key; this separate fresh owner is read for context only.
    owner = Account.create().address
    results = []
    try:
        for symbol, token in TOKENS:
            if symbol not in ('paxg', 'xaut', 'usdc', 'usdt'):
                continue
            metadata = await observer.metadata(token, owner)
            context = await observer.permit(token, owner)
            results.append({'symbol': symbol.upper(), 'metadata': metadata, 'permitContext': context})
            assert metadata['authorization']['kind'] == ('none' if symbol == 'usdt' else 'erc2612'), symbol
            if symbol != 'usdt':
                assert context['nonce']['status'] == 'success' and context['nonce']['value'] == '0', symbol
            assert context['allowance'] == {'status': 'success', 'value': '0'}, symbol
        helpers_facts = await helpers.get(token_permit=True, basket_permit=True)
    finally:
        await observer.close()
        await helpers.close()
    result = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'chainId': int(chain),
        'scope': 'Read-only configured-token metadata/context plus invalid/valid ERC2612 signatures and nonce/allowance effects within one discarded Multicall eth_call; no broadcasts, funding, user wallet requests, persisted keys/signatures or calldata.',
        'helpersSpender': config.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS, 'helpersFacts': helpers_facts, 'observations': results}
    Path(output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'chainId': int(chain), 'qualified': [row['symbol'] for row in results if row['metadata']['authorization']['kind']=='erc2612'], 'output': output}))


if __name__ == '__main__':
    asyncio.run(main())

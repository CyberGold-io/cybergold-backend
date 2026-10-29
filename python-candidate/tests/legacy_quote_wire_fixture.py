"""Historical wire comparison fixtures, excluded from the serving runtime.

These adapters retain the pinned Viem/Quoter wire controls and generic shared-read
cancellation comparisons. Product swap pricing exclusively uses the SDK engine.
"""
from collections import OrderedDict
import json
from pathlib import Path
from copy import deepcopy
import time
from web3 import Web3
from cybergold_candidate.uniswap_quote import QuoteContextRpc
from cybergold_candidate.route_search import RouteSearchRpc
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.quote_errors import rpc_failure
from cybergold_candidate.rpc_diagnostics import error_diagnostics
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_state import ZERO

ABI = json.loads(Path(__file__).with_name('legacy-uniswap-quoter-abi.json').read_text())
METHODS = {'exact-in': 'quoteExactInput', 'exact-out': 'quoteExactOutput'}


class ReferenceUniswapQuoteRpc(QuoteContextRpc):
    def __init__(self, settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self.quoter = Web3.to_checksum_address(settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS)
        self.contract = self.w3.eth.contract(abi=ABI)

    def encode(self, request):
        try:
            return self.contract.encode_abi(METHODS[request['mode']],
                args=[bytes.fromhex(request['path'].removeprefix('0x')), int(request['amount'])])
        except Exception as error:
            raise InvalidPreview('Invalid Uniswap quote input.') from error


    async def quote(self, mode, data, block):
        response = await self.w3.provider.make_request('eth_call', [
            {'to': self.quoter, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Uniswap quote contract read failed')
        outputs = next(row for row in ABI if row['name'] == METHODS[mode])['outputs']
        decoded = self.w3.codec.decode([row['type'] for row in outputs], bytes.fromhex(response['result'][2:]))
        # Existing App consumers use tuple[0]; gas/tick arrays do not select routes.
        return {'amount': str(decoded[0])}


class ReferenceRouteSearchRpc(RouteSearchRpc):
    def __init__(self, settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self.quoter = Web3.to_checksum_address(settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS)
        self.contract = self.w3.eth.contract(abi=ABI)

    encode = ReferenceUniswapQuoteRpc.encode

    async def eligible_paths(self, paths, block):
        # Reuse the previous route selector's absent/zero-active-liquidity rule.
        # On Anvil an empty pool can exhaust upstream reads and fail a whole
        # native batch. Observe only the fields needed for that existing rule.
        requirements, by_path = {}, {}
        for path in paths:
            raw = bytes.fromhex(path[2:])
            hops = []
            for offset in range(20, len(raw), 23):
                tokens = sorted(('0x' + raw[offset-20:offset].hex(),
                                 '0x' + raw[offset+3:offset+23].hex()))
                key = (*tokens, int.from_bytes(raw[offset:offset+3]))
                requirements[key] = (self.pools.factory,
                    self.pools.pool_contracts['factory'].encode_abi('getPool',
                        args=[*(Web3.to_checksum_address(token) for token in tokens), key[2]]))
                hops.append(key)
            by_path[path] = hops
        if not requirements:
            return set(paths), {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
        reads = {'requested': len(requirements), 'issued': 0, 'coalesced': 0, 'reused': 0}
        unusable, addresses = set(), {}
        try:
            rows, reads = await self.pool_batch(list(requirements.values()), block, reads)
        except Exception:
            # Failed observations are unknown, as in the previous selector;
            # they do not establish that a route is unusable.
            return set(paths), reads
        for key, row in zip(requirements, rows, strict=True):
            try:
                address = Web3.to_checksum_address(self.w3.codec.decode(
                    ['address'], bytes.fromhex(row['result'][2:]))[0])
                if address == ZERO:
                    unusable.add(key)
                else:
                    addresses.setdefault(address, []).append(key)
            except Exception:
                continue
        if addresses:
            calls = [(address, self.pools.pool_contracts['pool'].encode_abi('liquidity'))
                     for address in addresses]
            more = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
            try:
                rows, more = await self.pool_batch(calls, block, more)
            except Exception:
                rows = []
            reads = {key: reads[key] + more[key] for key in reads}
            for address, row in zip(addresses, rows):
                try:
                    liquidity = self.w3.codec.decode(['uint128'], bytes.fromhex(row['result'][2:]))[0]
                    if liquidity == 0:
                        unusable.update(addresses[address])
                except Exception:
                    continue
        return {path for path, hops in by_path.items() if not any(key in unusable for key in hops)}, reads


    async def quote_batch(self, mode, data, block):
        rows = await self.call_batch([(self.quoter, calldata) for calldata in data], block)
        outputs = next(row for row in ABI if row['name'] == METHODS[mode])['outputs']
        values = []
        for row in rows:
            if 'error' in row:
                diagnostics = error_diagnostics(row['error'])
                values.append({'status': 'failure', 'rpcCode': row['error']['code'],
                               'code': rpc_failure(row['error']).code,
                               **({'diagnostics': diagnostics} if diagnostics else {})})
            else:
                decoded = self.w3.codec.decode([part['type'] for part in outputs],
                    bytes.fromhex(row['result'][2:]))
                values.append({'status': 'success', 'amount': str(decoded[0])})
        return values


    async def quote_batch_counted(self, mode, data, block, counts):
        values = await self.quote_batch(mode, data, block)
        for name in ('requested', 'issued'):
            counts[name] = counts.get(name, 0) + len(data)
        return values


class SharingQuoterRpc(ReferenceRouteSearchRpc):
    """Coalesce identical Quoter calldata; optionally retain successful Mainnet math."""
    def __init__(self, *args, completed=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.quotes = SharedReads()
        self.retain_completed = completed
        self.completed_quotes = OrderedDict()
        self.counts = dict(requested=0, issued=0, coalesced=0, reused=0)

    async def quote_batch(self, mode, data, block):
        return await self.quote_batch_counted(mode, data, block, {})

    async def quote_batch_counted(self, mode, data, block, caller_counts):
        keys = [(self.chain_id, block['hash'].lower(), self.quoter.lower(), mode, value.lower()) for value in data]
        by_key = dict(zip(keys, data, strict=True))
        hits = {}
        if self.retain_completed and self.chain_id == 1:
            for key in keys:
                row = self.completed_quotes.get(key)
                if row and time.monotonic()-row[0] < 10:
                    hits[key] = deepcopy(row[1])
                    self.completed_quotes.move_to_end(key)
                else:
                    self.completed_quotes.pop(key,None)
        async def produce(missing):
            result = await super(SharingQuoterRpc, self).quote_batch(mode, [by_key[key] for key in missing], block)
            if self.retain_completed and self.chain_id == 1:
                for key,value in zip(missing,result,strict=True):
                    if value['status'] == 'success':
                        self.completed_quotes[key] = (time.monotonic(),deepcopy(value))
                        self.completed_quotes.move_to_end(key)
                        while len(self.completed_quotes)>4096:
                            self.completed_quotes.popitem(last=False)
            return result
        missing = [key for key in keys if key not in hits]
        values, counts = await self.quotes.many(missing, produce)
        counts['requested'] += len(keys)-len(missing)
        counts['reused'] += len(keys)-len(missing)
        resolved = dict(zip(missing,values,strict=True))
        for key, value in counts.items():
            self.counts[key] += value
            caller_counts[key] = caller_counts.get(key, 0) + value
        return [hits[key] if key in hits else resolved[key] for key in keys]

    async def close(self):
        await self.quotes.close()
        self.completed_quotes.clear()
        await super().close()


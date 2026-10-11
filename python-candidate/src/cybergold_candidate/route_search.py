"""All existing V3 candidates for a quote wave, at one canonical block."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
import time
from itertools import zip_longest
from typing import Literal

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, TypeAdapter
from web3 import Web3

from .basket_preview import InvalidPreview, handle_basket_preview
from .pool_producer import PoolRpc, ZERO
from .shared_reads import SharedReads
from .uniswap_quote import ABI, METHODS, UniswapQuoteRpc
from .wallet_balances import TOKENS
from .quote_errors import rpc_failure, public_quote_error
from .rpc_diagnostics import rpc_call, error_diagnostics
from .uniswap_routes import uses_typed_adapter

WETH = next(address for name, address in TOKENS if name == 'weth')
DIRECT_FEES = (100, 500, 3000, 10000)
VIA_FEES = (500, 3000, 10000)


class RouteTarget(BaseModel):
    inputAsset: str
    outputAsset: str
    amount: str


class RouteSearchRequest(BaseModel):
    mode: Literal['exact-in', 'exact-out']
    targets: list[RouteTarget]
    adapter: str | None = None


REQUEST = TypeAdapter(RouteSearchRequest)


def candidates(target, mode):
    try:
        token_in = Web3.to_checksum_address(target['inputAsset'])
        token_out = Web3.to_checksum_address(target['outputAsset'])
        amount = int(target['amount'])
        # The same uint256 domain is used by the existing Quoter ABI.
        Web3().codec.encode(['uint256'], [amount])
    except Exception as error:
        raise InvalidPreview('Invalid route search input.') from error
    if token_in == token_out:
        return []
    rows = []

    def add(tokens, fees, route):
        if mode == 'exact-out':
            tokens, fees = list(reversed(tokens)), list(reversed(fees))
        path = '0x' + tokens[0][2:]
        for fee, token in zip(fees, tokens[1:], strict=True):
            path += f'{fee:06x}' + token[2:]
        rows.append({'path': path.lower(), 'route': route,
                     'feeInfo': '/'.join(map(str, reversed(fees) if mode == 'exact-out' else fees)),
                     'totalFee': sum(fees)})

    for fee in DIRECT_FEES:
        add([token_in, token_out], [fee], 'direct')
    if token_in != WETH and token_out != WETH:
        for fee_in in VIA_FEES:
            for fee_out in VIA_FEES:
                add([token_in, WETH, token_out], [fee_in, fee_out], 'viaWeth')
    return sorted(rows, key=lambda row: (row['totalFee'], row['route'] != 'direct', row['feeInfo']))


class RouteSearchRpc(UniswapQuoteRpc):
    def __init__(self, settings, w3=None, client=None, *, pool_reads=None):
        super().__init__(settings, w3)
        self.pools = PoolRpc(settings, self.w3)
        self.url = settings.RPC_URL
        self.rpc_secrets = (settings.RPC_URL, settings.RPC_AUTHORIZATION)
        self.pool_reads = pool_reads if pool_reads is not None else SharedReads()
        self.owns_pool_reads = pool_reads is None
        self.client = client or httpx.AsyncClient(timeout=15, follow_redirects=False,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                     **({'Authorization': settings.RPC_AUTHORIZATION} if settings.RPC_AUTHORIZATION else {})})

    async def call_batch(self, calls, block):
        payload = [{'jsonrpc': '2.0', 'id': index, 'method': 'eth_call', 'params': [
            {'to': address, 'data': calldata},
            {'blockHash': block['hash'], 'requireCanonical': True}]}
            for index, (address, calldata) in enumerate(calls)]
        with rpc_call('eth_call', stage='route-search', secrets=self.rpc_secrets) as call:
            response = await self.client.post(self.url, json=payload)
            response.raise_for_status()
            by_id = {row['id']: {**row, 'error': call.rpc_error(row['error'])} if 'error' in row else row
                     for row in response.json()}
            return [by_id[row['id']] for row in payload]

    async def pool_batch(self, calls, block, counts):
        keys = [(self.chain_id, block['hash'].lower(), address.lower(), data.lower()) for address, data in calls]
        by_key = dict(zip(keys, calls, strict=True))
        async def produce(missing):
            return await self.call_batch([by_key[key] for key in missing], block)
        # Mainnet hash-addressed state is immutable. Sandbox can change state
        # under the same header via administrative overrides, so it retains
        # only overlapping reads, never a completed pool observation.
        return await self.pool_reads.many(keys, produce, retain=self.chain_id == 1, counts=counts)

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

    async def close(self):
        if self.owns_pool_reads:
            await self.pool_reads.close()
        await self.client.aclose()
        await super().close()


def reduce_results(request, plans, outcomes):
    results = []
    for target, rows in zip(request['targets'], plans, strict=True):
        best, attempted, succeeded, failures = None, 0, 0, []
        if target['inputAsset'].lower() == target['outputAsset'].lower():
            best = {'path': '0x', 'quote': target['amount'], 'route': 'direct', 'feeInfo': '0'}
        for row in rows:
            if row['callIndex'] not in outcomes:
                continue
            attempted += 1
            value = outcomes[row['callIndex']]
            if value['status'] == 'failure':
                failures.append({'path': row['path'], 'rpcCode': value['rpcCode'],
                                 **({'code': value['code']} if 'code' in value else {}),
                                 **({'diagnostics': value['diagnostics']} if 'diagnostics' in value else {})})
                continue
            succeeded += 1
            amount = int(value['amount'])
            if amount <= 0:
                continue
            if best is None or (amount > int(best['quote']) if request['mode'] == 'exact-in'
                                else amount < int(best['quote'])):
                best = {key: row[key] for key in ('path', 'route', 'feeInfo')}
                best['quote'] = value['amount']
        results.append({'target': target, 'best': best, 'attempted': attempted,
                        'succeeded': succeeded, 'failures': failures})
    return results


class RouteSearch:
    def __init__(self, settings, rpc=None, now=None, direct_batch_size=2, *, remaining_batch_size=2, group_planner=None, rpc_factory=RouteSearchRpc, multi_protocol=None):
        self.settings, self.rpc = settings, rpc
        self.direct_batch_size = direct_batch_size
        self.remaining_batch_size = remaining_batch_size
        self.group_planner = group_planner
        self.rpc_factory = rpc_factory
        self.multi_protocol = multi_protocol
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, request, on_update=None, *, block=None):
        if self.rpc is None:
            self.rpc = self.rpc_factory(self.settings)
        if self.multi_protocol:
            self.rpc.multi_protocol = self.multi_protocol
        provider = self.multi_protocol if uses_typed_adapter(request.get('adapter')) else None
        started = time.perf_counter()
        plans, calls, call_paths, indices = [], [], [], {}
        for target in request['targets']:
            rows = candidates(target, request['mode'])
            for row in rows:
                key = (row['path'], int(target['amount']))
                if key not in indices:
                    indices[key] = len(calls)
                    calls.append(self.rpc.encode({'mode': request['mode'], 'path': row['path'],
                                                  'amount': target['amount']}))
                    call_paths.append(row['path'])
                row['callIndex'] = indices[key]
            plans.append(rows)
        async with asyncio.timeout(15):
            owns_context = block is None
            block = await self.rpc.block(None) if owns_context else block
            context_done = time.perf_counter()
            eligible, pool_reads = await self.rpc.eligible_paths(list(dict.fromkeys(call_paths)), block)
            selected = [index for index, path in enumerate(call_paths) if path in eligible]
            outcomes = {}
            quote_reads = {'requested': 0, 'issued': 0, 'coalesced': 0, 'reused': 0}
            if on_update is None:
                quoted = await self.rpc.quote_batch_counted(request['mode'], [calls[index] for index in selected], block, quote_reads) if selected else []
                outcomes = dict(zip(selected, quoted, strict=True))
            else:
                async def snapshot():
                    results = reduce_results(request, plans, outcomes)
                    for row, plan in zip(results, plans, strict=True):
                        row['total'] = sum(candidate['callIndex'] in selected for candidate in plan)
                    await on_update({'type': 'progress', 'results': results})

                async def quote_group(group):
                    values = await self.rpc.quote_batch_counted(request['mode'], [calls[index] for index in group], block, quote_reads)
                    return dict(zip(group, values, strict=True))

                # Small concurrent batches preserve complete coverage and avoid
                # serial upstream compatibility fanout dominating one large tail.
                direct_rows = [[row['callIndex'] for row in plan if row['route'] == 'direct'
                                and row['callIndex'] in selected] for plan in plans]
                direct, groups = set(), []
                for wave in zip_longest(*direct_rows):
                    group = list(dict.fromkeys(index for index in wave if index is not None and index not in direct))
                    direct.update(group)
                    groups.extend(group[offset:offset + self.direct_batch_size]
                                  for offset in range(0, len(group), self.direct_batch_size))
                remaining = [index for index in selected if index not in direct]
                if remaining:
                    size = self.remaining_batch_size or len(remaining)
                    groups.extend(remaining[offset:offset+size] for offset in range(0, len(remaining), size))
                if self.group_planner:
                    groups = self.group_planner.groups(request, plans, groups)
                tasks = [asyncio.create_task(quote_group(group)) for group in groups]
                try:
                    await snapshot()
                    for task in asyncio.as_completed(tasks):
                        outcomes.update(await task)
                        await snapshot()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            quotes_done = time.perf_counter()
            results = reduce_results(request, plans, outcomes)
            if provider:
                def combined(extended):
                    rows = reduce_results(request, plans, outcomes)
                    for row, extra, plan in zip(rows, extended, plans, strict=True):
                        row['attempted'] += extra['attempted']
                        row['succeeded'] += extra['succeeded']
                        row['failures'].extend(extra['failures'])
                        row['total'] = sum(candidate['callIndex'] in selected for candidate in plan) + extra.get('total', extra['attempted'])
                        other = extra['best']
                        if other and (row['best'] is None or (int(other['quote']) > int(row['best']['quote'])
                            if request['mode'] == 'exact-in' else int(other['quote']) < int(row['best']['quote']))):
                            row['best'] = other
                    return rows
                async def update_extended(extended):
                    await on_update({'type': 'progress', 'results': combined(extended)})
                extended = await provider.reserve_quotes(request, block, **(
                    {'on_update': update_extended} if on_update else {}))
                results = combined(extended)
                for row in results:
                    row.pop('total', None)
            if owns_context:
                await self.rpc.assert_canonical(block)
            if self.group_planner:
                self.group_planner.observe(request, results)
            finished = time.perf_counter()
            return {'mode': request['mode'], 'quoter': self.rpc.quoter, 'results': results,
                'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                            'blockHash': block['hash'], 'observedAt': self.now()},
                'metrics': {'candidateCalls': len(selected),
                    'rpcReads': quote_reads['issued'] + pool_reads['issued'] + (3 if owns_context else 0),
                    'rpcReadsRequested': quote_reads['requested'] + pool_reads['requested'] + (3 if owns_context else 0),
                    'rpcReadsCoalesced': quote_reads['coalesced'] + pool_reads['coalesced'],
                    'rpcReadsReused': quote_reads['reused'] + pool_reads['reused'],
                    'contextMs': round((context_done - started) * 1000, 3),
                    'quotesMs': round((quotes_done - context_done) * 1000, 3),
                    'canonicalityMs': round((finished - quotes_done) * 1000, 3),
                    'totalMs': round((finished - started) * 1000, 3)}}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_route_search(request, service):
    return await handle_basket_preview(request, service, REQUEST, 'route-search',
        'Invalid route search input.', 'Route search is temporarily unavailable.')


async def handle_route_stream(request, service):
    try:
        value = REQUEST.validate_python(await request.json()).model_dump()
        for target in value['targets']:
            candidates(target, value['mode'])
    except ValueError:
        return JSONResponse({'error': 'Invalid route search input.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})

    async def events():
        queue = asyncio.Queue()

        async def produce():
            try:
                result = await service.get(value, on_update=queue.put)
                await queue.put({'type': 'complete', 'value': result})
            except Exception as error:
                correlation = str(uuid.uuid4())
                payload = public_quote_error(error)
                logging.getLogger('cybergold.candidate').error(json.dumps({
                    'context': 'route-search-stream', 'correlationId': correlation,
                    'errorClassification': payload['code'], 'exceptionType': type(error).__name__,
                    **({'diagnostics': payload['diagnostics']} if 'diagnostics' in payload else {})}))
                await queue.put({'type': 'error', **payload,
                                 'error': 'Route search is temporarily unavailable.', 'correlationId': correlation})

        operation = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, separators=(',', ':')) + '\n'
                if event['type'] in ('complete', 'error'):
                    break
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    return StreamingResponse(events(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

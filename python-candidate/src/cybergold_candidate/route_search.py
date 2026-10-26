"""Canonical-context HTTP/Core facade and shared pinned-state transport."""
import asyncio
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
import time
from typing import Literal

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, TypeAdapter
from web3 import Web3

from .basket_preview import InvalidPreview, handle_basket_preview
from .pool_producer import PoolRpc
from .shared_reads import SharedReads
from .telemetry import getter_reads, rpc_exchange
from .uniswap_quote import QuoteContextRpc
from .wallet_balances import TOKENS
from .quote_errors import QuoteFailure, public_quote_error
from .uniswap_routes import LEGACY_V3_ADAPTERS, initial_v3_branches, standalone_v3, v3_path
from .rpc_diagnostics import (rpc_call, route_work_scope, route_subphase,
                              route_count, freeze_quote_work)

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


def validate_target(target):
    try:
        token_in = Web3.to_checksum_address(target['inputAsset'])
        token_out = Web3.to_checksum_address(target['outputAsset'])
        amount = int(target['amount'])
        # Preserve the route amount's established uint256 domain.
        Web3().codec.encode(['uint256'], [amount])
    except Exception as error:
        raise InvalidPreview('Invalid route search input.') from error
    return token_in, token_out, amount


def candidates(target, mode):
    token_in, token_out, amount = validate_target(target)
    # Compatibility projection for historical wire fixtures/benchmarks. The
    # executable skeletons come from the one canonical candidate producer.
    return [{'path': v3_path(branches[0]['hops'], mode == 'exact-out'),
        'route': 'direct' if len(branches[0]['hops']) == 1 else 'viaWeth',
        'feeInfo': '/'.join(str(hop['pool']['feePips']) for hop in branches[0]['hops']),
        'totalFee': sum(hop['pool']['feePips'] for hop in branches[0]['hops'])}
        for branches in initial_v3_branches({'inputAsset': token_in,
            'outputAsset': token_out, 'amount': str(amount)}, mode)]


def public_rows(rows):
    """Keep packed V3 compatibility at the HTTP boundary only."""
    result = deepcopy(rows)
    for row in result:
        best = row.get('best')
        if best and best.get('routePlan') and standalone_v3(best['routePlan']):
            plan = best['routePlan']
            hops = plan['branches'][0]['hops']
            best['path'] = v3_path(hops, plan['mode'] == 'exactOut')
            if len(hops) == 2 and hops[0]['pool']['token1' if hops[0]['zeroForOne'] else 'token0']['address'].lower() == WETH.lower():
                best['route'] = 'viaWeth'
    return result


class RouteSearchRpc(QuoteContextRpc):
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
        with rpc_exchange(len(payload)), rpc_call('eth_call', stage='route-search', secrets=self.rpc_secrets) as call:
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
        try:
            return await self.pool_reads.many(keys, produce, retain=self.chain_id == 1, counts=counts)
        finally:
            getter_reads(counts)

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
    """HTTP/Core facade for the same engine used by Market and direct quotes."""
    def __init__(self, settings, rpc=None, now=None, *, rpc_factory=RouteSearchRpc,
                 engine=None, multi_protocol=None):
        self.settings, self.rpc = settings, rpc
        self.rpc_factory = rpc_factory
        self.engine = engine if engine is not None else multi_protocol
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    @property
    def multi_protocol(self):
        # Retain the old injection name for callers without retaining a second
        # route representation, quote producer, or scheduling path.
        return self.engine

    @multi_protocol.setter
    def multi_protocol(self, value):
        self.engine = value

    @route_work_scope
    async def get(self, request, on_update=None, *, block=None):
        for target in request['targets']:
            validate_target(target)
        # The unversioned public endpoint historically enumerates V3 paths.
        # Give that existing execution capability to the common planner too.
        request = {**request, 'adapter': request.get('adapter') or next(iter(LEGACY_V3_ADAPTERS))}
        if self.rpc is None:
            self.rpc = self.rpc_factory(self.settings)
        self.rpc.route_engine = self.engine
        started = time.perf_counter()
        async with asyncio.timeout(15):
            owns_context = block is None
            block = await self.rpc.block(None) if owns_context else block
            context_done = time.perf_counter()
            route_subphase('structured-search')
            async def progress(rows):
                if on_update:
                    await on_update({'type': 'progress', 'results': public_rows(rows)})
            results = await self.engine.search_routes(request, block, on_update=progress)
            failures = [failure for row in results for failure in row['failures']]
            if results and not any(row['best'] for row in results) and failures and all(
                    failure.get('code', '').startswith('rpc-') for failure in failures):
                first = failures[0]
                raise QuoteFailure(first['code'], diagnostics=first.get('diagnostics'))
            quotes_done = time.perf_counter()
            if owns_context:
                route_subphase('canonicality')
                await self.rpc.assert_canonical(block)
            finished = time.perf_counter()
            context_reads = 3 if owns_context else 0
            return {'mode': request['mode'], 'qualification': 'sdk', 'results': public_rows(results),
                'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                            'blockHash': block['hash'], 'observedAt': self.now()},
                # Engine state acquisition and SDK IPC are not counted
                # by this facade. Do not present coordinator reads as supplier
                # cost or infer savings from removing the old V3 batch wave.
                'metrics': {'candidateCalls': sum(row['attempted'] for row in results),
                    'rpcReads': context_reads, 'rpcReadsRequested': context_reads,
                    'rpcReadsCoalesced': 0, 'rpcReadsReused': 0, 'rpcReadsScope': 'coordinator',
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
            validate_target(target)
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

"""Web3 provider boundary preserving ordinary Viem and raw-log retry policies."""
import asyncio
import json
import re

import httpx
from web3 import AsyncHTTPProvider
from web3.exceptions import Web3RPCError
from .safe_service import truthy


def rpc_code(error):
    if isinstance(error, Web3RPCError) and isinstance(error.rpc_response, dict):
        value = error.rpc_response.get('error')
        return value.get('code') if isinstance(value, dict) else None
    return getattr(error, 'code', None)


def should_retry(error):
    if isinstance(error, asyncio.CancelledError):
        return False
    code = rpc_code(error)
    if type(code) in (int, float):
        return code in (-1, -32005, -32603, 429)
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code:
        return error.response.status_code in (403, 408, 413, 429, 500, 502, 503, 504)
    return True


def retry_delay(error, count):
    if isinstance(error, httpx.HTTPStatusError):
        header = error.response.headers.get('Retry-After')
        if header is not None and re.search(r'[0-9]', header):
            parsed = re.match(r'\s*([+-]?[0-9]+)', header)
            # Viem skips a NaN/zero delay; negative timers fire immediately.
            return int(parsed[1]) if parsed else 0
    return (1 << count) * 0.15


class IndexerProvider(AsyncHTTPProvider):
    """HTTPX owns HTTP semantics; Web3 owns JSON-RPC encoding and decoding."""
    def __init__(self, url, authorization=None, http_client=None):
        if authorization is not None and (authorization == '' or re.search(r'[\r\n\0]', authorization)):
            raise ValueError('ONCHAIN_INDEXER_RPC_AUTHORIZATION is invalid')
        super().__init__(url, exception_retry_configuration=None, cache_allowed_requests=False)
        self.http = http_client or httpx.AsyncClient(timeout=10, follow_redirects=True)
        self.headers = {'Content-Type': 'application/json', **({'Authorization': authorization} if authorization else {})}

    async def _make_request(self, method, request_data):
        response = await self.http.post(self.endpoint_uri, content=request_data, headers=self.headers)
        try:
            data = response.json() if response.headers.get('Content-Type', '').startswith('application/json') else json.loads(response.text or '{}')
        except (ValueError, TypeError):
            if response.is_success:
                raise
            data = {'error': response.text}
        if not response.is_success:
            error = data.get('error') if isinstance(data, dict) else None
            if not (isinstance(error, dict) and type(error.get('code')) in (int, float) and isinstance(error.get('message'), str)):
                response.raise_for_status()
        return json.dumps(data).encode()

    async def disconnect(self):
        await self.http.aclose()
        await super().disconnect()


class IndexerRpc:
    def __init__(self, url=None, authorization=None, *, provider=None, retry_count=3, sleep=asyncio.sleep, close_provider=True,
                 before_request=None):
        self.provider = provider or IndexerProvider(url, authorization)
        self.retry_count, self.sleep = retry_count, sleep
        self.close_provider = close_provider
        self.before_request = before_request

    async def request(self, method, params):
        for attempt in range(self.retry_count + 1):
            if self.before_request is not None:
                await self.before_request()
            try:
                response = await self.provider.make_request(method, params)
                if response is None:
                    raise ValueError('Indexer RPC response is null')
                if not isinstance(response, dict):
                    return None
                if truthy(response.get('error')):
                    raise Web3RPCError('Indexer RPC request failed', rpc_response=response)
                return response.get('result')
            except Exception as error:
                if attempt >= self.retry_count or not should_retry(error):
                    raise
                delay = retry_delay(error, attempt)
                if delay:
                    await self.sleep(delay)

    async def chain_id(self):
        return int(await self.request('eth_chainId', []), 16)

    async def block_number(self):
        return int(await self.request('eth_blockNumber', []), 16)

    async def block(self, number=None, *, block_hash=None):
        tag = hex(number) if type(number) is int else number
        value = await self.request('eth_getBlockByHash' if block_hash else 'eth_getBlockByNumber', [block_hash or tag, False])
        return {**value, 'number': int(value['number'], 16) if value and value.get('number') is not None else None,
            'hash': value.get('hash') if value else None,
            'timestamp': int(value['timestamp'], 16) if value and value.get('timestamp') is not None else None} if value else {'number': None, 'hash': None, 'timestamp': None}

    async def logs(self, address, value, topic=None):
        params = {'address': address, 'fromBlock': hex(value['fromBlock']), 'toBlock': hex(value['toBlock'])}
        if topic is not None:
            params['topics'] = [topic]
        return await self.request('eth_getLogs', [params])

    async def close(self):
        if self.close_provider:
            await self.provider.disconnect()


def direct_rpc(settings, *, raw_logs=False):
    return IndexerRpc(settings.ONCHAIN_INDEXER_RPC_URL or settings.RPC_URL or settings.NEXT_PUBLIC_RPC_URL,
        settings.ONCHAIN_INDEXER_RPC_AUTHORIZATION, retry_count=0 if raw_logs else 3)


def leased_rpc(lease, counter, before_request=None):
    # The enclosing run owns release; no transport retry/direct fallback.
    return IndexerRpc(provider=lease.provider(counter, before_request), retry_count=0, close_provider=False)

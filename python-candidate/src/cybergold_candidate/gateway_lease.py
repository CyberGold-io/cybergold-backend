"""Retained private indexer lease protocol over HTTPX, isolated worker source.

All predicates below belong to the existing TypeScript client contract. This
adapter introduces no release gate, retry, direct-provider fallback or scheduler.
"""
import asyncio
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import AnyUrl, ValidationError
from web3.exceptions import Web3RPCError
from web3.providers.async_base import AsyncBaseProvider

from .reconciliation_receipt import GatewayMethodRejectedError, safe_count
from .rpc_http import parse_json
from .safe_service import truthy

RPC_PATH = '/rpc/indexer'
ACQUIRE_PATH = '/rpc/indexer/leases'
RELEASE_PATH = '/rpc/indexer/leases/release'
MAX_CONTRACT_BYTES = 4096
TIMEOUT_SECONDS = 35
LEASE_HEADER = 'X-CyberGold-RPC-Lease'
RECONCILIATION_HEADER = 'X-CyberGold-RPC-Reconciliation'


class GatewayLeaseError(ValueError):
    def __init__(self):
        super().__init__('Indexer gateway lease restart required')


class GatewayRangeReductionError(ValueError):
    def __init__(self):
        super().__init__('Indexer gateway log range reduction required')


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def exact(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def safe_integer(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= 2**53-1 and value == int(value)


def health_suppressed(active_id, ambiguous_until_ms, now_ms):
    return active_id is not None and (not safe_integer(ambiguous_until_ms)
        or not safe_integer(now_ms) or now_ms < ambiguous_until_ms)


def enabled(value=None):
    if value is None or value in ('', '0', 'false'):
        return False
    if value in ('1', 'true'):
        return True
    raise ValueError('ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED must be one of 0, 1, false, or true')


def gateway_url(value):
    # Reuse the locked URL parser already used by candidate settings, including
    # host/default-port and dot-segment normalization, before the retained policy.
    try:
        url = AnyUrl(value)
    except (ValueError, ValidationError):
        raise ValueError('ONCHAIN_INDEXER_RPC_URL must be an absolute URL') from None
    parsed = urlsplit(str(url))
    if (url.scheme not in ('http', 'https') or not url.host or url.username or url.password or parsed.query
        or parsed.fragment or parsed.path != RPC_PATH):
        raise ValueError('ONCHAIN_INDEXER_RPC_URL must be an HTTP(S) URL ending exactly in /rpc/indexer')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def endpoint(url, path):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def has_json_type(response):
    return response.headers.get('content-type', '').split(';', 1)[0].strip().lower() == 'application/json'


async def contract_json(response):
    declared = response.headers.get('content-length')
    if declared is not None and (not re.fullmatch(r'[0-9]+', declared) or int(declared) > MAX_CONTRACT_BYTES):
        raise GatewayLeaseError()
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > MAX_CONTRACT_BYTES:
            raise GatewayLeaseError()
    try:
        result = parse_json(data.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise GatewayLeaseError() from None
    if not isinstance(result, dict):
        raise GatewayLeaseError()
    return result


async def contract_request(client, url, authorization, body, lease_headers=None):
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with client.stream('POST', url, headers={
                'Accept': 'application/json', 'Authorization': authorization,
                'Cache-Control': 'no-store', 'Content-Type': 'application/json',
                **(lease_headers or {})}, json=body, follow_redirects=False,
                timeout=TIMEOUT_SECONDS) as response:
                if str(response.url) != url or response.status_code != 200 or not has_json_type(response):
                    raise GatewayLeaseError()
                return await contract_json(response)
    except GatewayLeaseError:
        raise
    except Exception:
        raise GatewayLeaseError() from None


def error_chain(error):
    seen = set()
    for _ in range(16):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        yield error
        error = getattr(error, '__cause__', None)


def range_reduction_required(error):
    return any(isinstance(value, GatewayRangeReductionError) for value in error_chain(error))


def restart_required(error):
    return not range_reduction_required(error) and any(
        isinstance(value, (GatewayLeaseError, httpx.RequestError, TimeoutError))
        or getattr(value, 'name', None) in ('HttpRequestError', 'TimeoutError', 'AbortError')
        for value in error_chain(error))


def accounting_failure(error):
    return any(isinstance(value, GatewayMethodRejectedError) for value in error_chain(error))


class GatewayLease:
    def __init__(self, rpc_url, authorization, client, now, token, reconciliation_id,
                 anchor, expires_seconds, revision):
        issued = now()
        expires = issued + expires_seconds * 1000 if type(expires_seconds) in (int, float) else math.nan
        if (not matches(r'[A-Za-z0-9_-]{43,128}', token)
            or not matches(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', reconciliation_id)
            or not safe_count(expires_seconds) or expires_seconds < 1
            or not safe_integer(issued) or not safe_integer(expires) or expires <= issued
            or not matches(r'[0-9a-f]{64}', revision)):
            raise GatewayLeaseError()
        self.reconciliation_id = reconciliation_id
        self.finalized_anchor = dict(anchor)
        self.config_revision = revision
        self.expires_in_seconds = expires_seconds
        self.expires_at_ms = expires
        self._rpc_url = rpc_url
        self._authorization = authorization
        self._client = client
        self._now = now
        self._token = token
        self._released = False
        self._slots = asyncio.Semaphore(4)
        self._active = 0
        self._waiting = 0
        self._rpc_id = 0

    def _current(self):
        if self._released or self._now() >= self.expires_at_ms:
            raise GatewayLeaseError()

    def _headers(self):
        return {'Authorization': self._authorization, LEASE_HEADER: self._token,
                RECONCILIATION_HEADER: self.reconciliation_id}

    async def request(self, method, params, counter, before_request=None):
        # Rejected methods are outside the attempt/failure accounting, just as
        # recordGatewayRpcAttempt is outside the retained client's try block.
        counter.gateway_attempt(method)
        try:
            try:
                # Viem bounds callback/queue/fetch until response headers. Its
                # fetch slot and timer are released before decoding the body.
                async with asyncio.timeout(TIMEOUT_SECONDS):
                    self._current()
                    if before_request is not None:
                        try:
                            await before_request()
                        except Exception as failure:
                            # Viem wraps callback errors, retaining their cause
                            # for range/accounting classification by the worker.
                            raise GatewayLeaseError() from failure
                    self._current()
                    self._waiting += 1
                    try:
                        await self._slots.acquire()
                    finally:
                        self._waiting -= 1
                    self._active += 1
                    try:
                        self._current()
                        self._rpc_id += 1
                        request = self._client.build_request('POST', self._rpc_url, json={
                            'jsonrpc': '2.0', 'id': self._rpc_id, 'method': method, 'params': params},
                            headers={'Content-Type': 'application/json', **self._headers()},
                            timeout=httpx.Timeout(TIMEOUT_SECONDS, read=None))
                        response = await self._client.send(request, stream=True, follow_redirects=False)
                    finally:
                        self._active -= 1
                        self._slots.release()
            except GatewayLeaseError:
                raise
            except Exception:
                raise GatewayLeaseError() from None
            try:
                if str(response.url) != self._rpc_url:
                    raise GatewayLeaseError()
                if not response.is_success:
                    value = await contract_json(response) if response.status_code == 413 and has_json_type(response) else None
                    if (exact(value, ('formatVersion', 'kind')) and type(value['formatVersion']) in (int, float)
                        and value['formatVersion'] == 1 and value['kind'] == 'cybergold-rpc-indexer-range-reduction-required'):
                        raise GatewayRangeReductionError()
                    raise GatewayLeaseError()
                if not has_json_type(response):
                    raise GatewayLeaseError()
                raw = await response.aread()
            finally:
                await response.aclose()
            try:
                value = parse_json(raw.decode('utf-8-sig', errors='replace'))
            except (ValueError, UnicodeError):
                raise GatewayLeaseError() from None
            if value is None:
                raise TypeError('Indexer gateway RPC response is null')
            if isinstance(value, dict) and truthy(value.get('error')):
                raise Web3RPCError('Indexer gateway RPC request failed', rpc_response=value)
            # Viem returns undefined (represented as None here) if an otherwise
            # valid JSON response has no result; do not add an envelope gate.
            return value.get('result') if isinstance(value, dict) else None
        except BaseException:
            counter.gateway_failure()
            raise

    async def release(self):
        self._current()
        if self._active or self._waiting:
            raise GatewayLeaseError()
        value = await contract_request(self._client, endpoint(self._rpc_url, RELEASE_PATH),
            self._authorization, {'kind': 'cybergold-rpc-indexer-lease-release-request',
            'formatVersion': 1, 'reconciliationId': self.reconciliation_id},
            {LEASE_HEADER: self._token, RECONCILIATION_HEADER: self.reconciliation_id})
        if (not exact(value, ('formatVersion', 'kind', 'reconciliationId', 'released'))
            or type(value['formatVersion']) not in (int, float) or value['formatVersion'] != 1
            or value['kind'] != 'cybergold-rpc-indexer-lease-release'
            or value['reconciliationId'] != self.reconciliation_id or value['released'] is not True):
            raise GatewayLeaseError()
        self._released = True

    def provider(self, counter, before_request=None):
        return GatewayProvider(self, counter, before_request)


class GatewayProvider(AsyncBaseProvider):
    """Web3.py delegates each wire attempt to the same acquired lease."""
    def __init__(self, lease, counter, before_request=None):
        super().__init__(cache_allowed_requests=False)
        self.lease = lease
        self.counter = counter
        self.before_request = before_request

    async def make_request(self, method, params):
        result = await self.lease.request(method, params, self.counter, self.before_request)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def is_connected(self, show_traceback=False):
        try:
            await self.make_request('eth_chainId', [])
            return True
        except Exception:
            if show_traceback:
                raise
            return False


class GatewayClient:
    def __init__(self, rpc_url, token, client, now=None):
        if not matches(r'[A-Za-z0-9_-]{43,128}', token):
            raise ValueError('ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN must be a 43-to-128-character URL-safe token')
        self._rpc_url = rpc_url
        self._authorization = 'Bearer ' + token
        self._client = client
        self._now = now or (lambda: int(time.time() * 1000))

    async def acquire(self, expectation):
        identifier = expectation['reconciliationId']
        revision = expectation['expectedRuntimeRevision']
        expected = expectation['expectedFinalizedAnchor']
        if (not matches(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', identifier)
            or not matches(r'[0-9a-f]{64}', revision) or not safe_count(expected['blockNumber'])
            or not matches(r'0x[0-9a-f]{64}', expected['blockHash'])):
            raise GatewayLeaseError()
        value = await contract_request(self._client, endpoint(self._rpc_url, ACQUIRE_PATH),
            self._authorization, {'kind': 'cybergold-rpc-indexer-lease-acquire-request',
            'formatVersion': 2, 'reconciliationId': identifier, 'expectedRuntimeRevision': revision,
            'expectedFinalizedAnchor': {'number': int(expected['blockNumber']), 'hash': expected['blockHash']}})
        if (not exact(value, ('configRevision', 'expiresInSeconds', 'finalizedAnchor', 'formatVersion',
            'kind', 'leaseToken', 'reconciliationId')) or value['kind'] != 'cybergold-rpc-indexer-lease'
            or type(value['formatVersion']) not in (int, float) or value['formatVersion'] != 1
            or value['reconciliationId'] != identifier or not exact(value['finalizedAnchor'], ('hash', 'number'))):
            raise GatewayLeaseError()
        anchor = value['finalizedAnchor']
        if not safe_count(anchor['number']) or not matches(r'0x[0-9a-fA-F]{64}', anchor['hash']):
            raise GatewayLeaseError()
        if (value['configRevision'] != revision or anchor['number'] != expected['blockNumber']
            or anchor['hash'].lower() != expected['blockHash']):
            raise GatewayLeaseError()
        return GatewayLease(self._rpc_url, self._authorization, self._client, self._now,
            value['leaseToken'], identifier, {'blockNumber': int(anchor['number']), 'blockHash': anchor['hash'].lower()},
            value['expiresInSeconds'], value['configRevision'])


def from_environment(environment, client, now=None):
    if not enabled(environment.get('ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED')):
        if 'ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN' in environment:
            raise ValueError('Disabled indexer gateway configuration must not include a gateway token')
        return None
    url = environment.get('ONCHAIN_INDEXER_RPC_URL')
    token = environment.get('ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN')
    if not url or not token:
        raise ValueError('Enabled indexer gateway requires ONCHAIN_INDEXER_RPC_URL and ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN')
    return GatewayClient(gateway_url(url), token, client, now)


def assert_runtime(enabled, chain_id, archive_free_finalized, address_scoped):
    if enabled and (chain_id != 1 or not archive_free_finalized or not address_scoped):
        raise ValueError('Private indexer gateway requires chain 1 archive-free finalized address-scoped mode')

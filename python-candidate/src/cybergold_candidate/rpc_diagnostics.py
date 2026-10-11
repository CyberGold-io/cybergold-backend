"""Request-local RPC failure context, without URLs, credentials or call data."""
from contextlib import contextmanager
from contextvars import ContextVar
from http import HTTPStatus
import asyncio
import re
from time import perf_counter
from urllib.parse import parse_qsl, unquote, urlsplit

import aiohttp
import httpx
from web3.exceptions import Web3RPCError


_scope = ContextVar('rpc_diagnostic_scope', default=None)
_stages = {'eth_chainId': 'chain-head', 'eth_blockNumber': 'chain-head', 'eth_getBlockByNumber': 'block-read',
           'eth_getBlockByHash': 'block-read', 'eth_call': 'contract-read',
           'eth_estimateGas': 'gas-estimation', 'eth_maxPriorityFeePerGas': 'priority-fee',
           'eth_gasPrice': 'gas-price', 'eth_getTransactionReceipt': 'receipt-read',
           'eth_getTransactionByHash': 'transaction-read', 'eth_getTransactionCount': 'nonce-read',
           'eth_getBalance': 'balance-read', 'eth_getCode': 'code-read', 'eth_getLogs': 'event-read'}


def safe_provider_message(message, secrets=()):
    if not isinstance(message, str):
        return None
    sensitive = set()
    for secret in secrets:
        if not isinstance(secret, str) or not secret:
            continue
        sensitive.add(secret)
        if re.match(r'(?i)^(bearer|basic)\s+', secret):
            sensitive.add(secret.split(None, 1)[1])
        if '://' in secret:
            try:
                parts = urlsplit(secret)
                sensitive.update(filter(None, (parts.username, parts.password)))
                sensitive.update(unquote(value) for value in (parts.username, parts.password) if value)
                sensitive.update(value for _, value in parse_qsl(parts.query) if value)
                sensitive.update(unquote(value) for value in parts.path.split('/') if value
                                 and value.lower() not in ('v1', 'v2', 'v3', 'rpc', 'api', 'jsonrpc'))
            except ValueError:
                pass
    text = message
    for secret in sorted(sensitive, key=len, reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(secret) + r'(?!\w)', '[redacted]', text)
    text = re.sub(r'(?i)\b(?:https?|wss?)://[^\s<>"\']+', '[redacted URL]', text)
    text = re.sub(r'(?i)\b(?:bearer|basic)\s+[^\s,;]+', '[redacted authorization]', text)
    text = re.sub(r"""(?i)\b(?:authorization|api[_-]?key|access[_-]?token|password|secret|token)["']?"""
                  r"""\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)""",
                  '[redacted credential]', text)
    # Free-form provider text can echo whole request objects. Their boundaries
    # are not reliable prose, so retain the explanation before that field and
    # omit the rest rather than exposing a partially parsed payload.
    text = re.sub(r"""(?is)\b(?:params|data|calldata|input|arguments|request(?:[_-]?body)?)["']?"""
                  r'\s*[:=].*', '[redacted request data]', text)
    text = re.sub(r'(?<![\w])[A-Za-z0-9+/_.=-]{24,}(?![\w])', '[redacted token]', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text).strip()
    # A bare opaque identifier is data, not a provider explanation. Short
    # private credential tags must not escape merely because they are below
    # the long-token redaction threshold.
    if re.fullmatch(r'[\w.-]+', text) and re.search(r'[-_.0-9]', text):
        return None
    if not re.sub(r'\[redacted[^\]]*\]', '', text).strip(' \t\n:;,.-'):
        return None
    return text[:512]


class _RequestScope:
    def __init__(self, stage):
        self.stage = stage
        self.cancelled = []


@contextmanager
def rpc_diagnostic_scope(stage=None):
    token = _scope.set(_RequestScope(stage))
    try:
        yield
    finally:
        _scope.reset(token)


class RpcDiagnosticsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        with rpc_diagnostic_scope():
            await self.app(scope, receive, send)


class _RpcError(dict):
    """Private metadata survives Web3 error conversion without changing wire keys."""
    def __init__(self, error, diagnostics):
        super().__init__(error)
        self.rpc_diagnostics = diagnostics


def _provider_error(error, secrets=()):
    result = {'failureType': 'rpc-error'}
    if type(error.get('code')) is int:
        result['upstreamErrorCode'] = error['code']
    message = safe_provider_message(error.get('message'), secrets)
    if message:
        result['providerMessage'] = message
    return result


def error_diagnostics(error):
    value = getattr(error, 'rpc_diagnostics', None)
    if value is not None:
        current = _scope.get()
        # Shared physical reads can have subscribers in different logical
        # operations. Project each caller's stage without mutating the shared
        # exception or its physical RPC timing.
        return {**value, **({'stage': current.stage} if current and current.stage else {})}
    if isinstance(error, Web3RPCError):
        payload = (error.rpc_response or {}).get('error', {})
        return error_diagnostics(payload)
    if isinstance(error, dict):
        # Errors originating outside the instrumented transport have no
        # configured credential context. Retain their numeric code, but do
        # not guess that their arbitrary message is safe to publish.
        return {'failureType': 'rpc-error',
                **({'upstreamErrorCode': error['code']} if type(error.get('code')) is int else {})}
    if isinstance(error, TimeoutError):
        current = _scope.get()
        if current and current.cancelled:
            return dict(max(current.cancelled, key=lambda item: item['elapsedMs']))
    return None


@contextmanager
def rpc_call(method, stage=None, secrets=()):
    call = _RpcCall(method, stage, secrets)
    try:
        yield call
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            current = _scope.get()
            if current:
                current.cancelled.append({**call.context(), 'failureType': 'backend-deadline'})
        elif isinstance(error, Exception) and getattr(error, 'rpc_diagnostics', None) is None:
            error.rpc_diagnostics = call.failure(error)
        raise


class _RpcCall:
    def __init__(self, method, stage, secrets):
        self.method, self.secrets, self.started = method, secrets, perf_counter()
        current = _scope.get()
        if current:
            # A later operation must not inherit an earlier cancelled read's
            # method or timing when its own enclosing deadline expires.
            current.cancelled.clear()
        self.stage = stage or (current.stage if current else None) or _stages.get(method, 'rpc-request')

    def context(self):
        return {'rpcMethod': self.method, 'stage': self.stage,
                'elapsedMs': round((perf_counter() - self.started) * 1000, 3)}

    def rpc_error(self, error):
        return _RpcError(error, {**self.context(), **_provider_error(error, self.secrets)})

    def failure(self, error):
        result = self.context()
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            result['failureType'] = 'provider-timeout'
        elif isinstance(error, (aiohttp.ClientResponseError, httpx.HTTPStatusError)):
            status = error.status if isinstance(error, aiohttp.ClientResponseError) else error.response.status_code
            result.update(failureType='http-error', httpStatus=status)
            try:
                result['providerMessage'] = HTTPStatus(status).phrase
            except ValueError:
                pass
            if isinstance(error, httpx.HTTPStatusError):
                try:
                    payload = error.response.json().get('error')
                    if isinstance(payload, dict):
                        result.update(_provider_error(payload, self.secrets))
                        result['failureType'] = 'http-error'
                except (ValueError, AttributeError):
                    pass
        else:
            result['failureType'] = 'transport-error'
        return result

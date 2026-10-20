"""Safe failure categories; provider URLs, payloads and credentials stay private."""
import asyncio

import aiohttp
import httpx
from web3.exceptions import Web3RPCError

from .preview_errors import KnownPreviewError
from .rpc_diagnostics import error_diagnostics, quote_error_diagnostics


MESSAGES = {
    'rpc-rate-limit': 'RPC request limit reached. Please retry shortly.',
    'rpc-timeout': 'RPC request timed out. Please retry.',
    'rpc-unavailable': 'RPC service is unavailable. Please retry.',
    'rpc-access-denied': 'RPC provider refused access. Please retry later.',
    'quote-timeout': 'Quote calculation timed out. Please retry.',
    'quote-no-route': 'No exchange route is available for this amount.',
    'quote-insufficient-liquidity': 'The Market does not have enough liquidity to fill this amount. Reduce the amount.',
    'quote-contract-reverted': 'The contract rejected the quote for this amount.',
    'quote-unavailable': 'The quote service could not complete this request. Please retry.',
}


class QuoteFailure(ValueError):
    def __init__(self, code, *, diagnostics=None):
        super().__init__(MESSAGES[code])
        self.code = code
        self.rpc_diagnostics = diagnostics


class RpcTimeout(TimeoutError):
    """A timeout at the RPC boundary, rather than the enclosing quote stage."""


def rpc_failure(error):
    if error.get('code') == -32005:
        result = QuoteFailure('rpc-rate-limit')
    elif error.get('code') == 3 or str(error.get('message', '')).lower().startswith('execution reverted'):
        result = QuoteFailure('quote-contract-reverted')
    else:
        result = QuoteFailure('rpc-unavailable')
    result.rpc_diagnostics = error_diagnostics(error)
    return result


def _public_quote_error(error):
    if isinstance(error, (KnownPreviewError, QuoteFailure)):
        return {'code': error.code, 'error': str(error),
                **({'constraint': dict(error.constraint)} if isinstance(error, KnownPreviewError) and error.constraint else {})}
    if isinstance(error, Web3RPCError):
        return _public_quote_error(rpc_failure((error.rpc_response or {}).get('error', {})))
    if isinstance(error, (RpcTimeout, httpx.TimeoutException)):
        code = 'rpc-timeout'
    elif isinstance(error, (aiohttp.ClientResponseError, httpx.HTTPStatusError)):
        status = error.status if isinstance(error, aiohttp.ClientResponseError) else error.response.status_code
        code = 'rpc-rate-limit' if status == 429 else 'rpc-timeout' if status == 504 \
            else 'rpc-access-denied' if status in (401, 403) else 'rpc-unavailable'
    elif isinstance(error, (aiohttp.ClientError, httpx.RequestError)):
        code = 'rpc-unavailable'
    elif isinstance(error, asyncio.TimeoutError):
        code = 'quote-timeout'
    else:
        code = 'quote-unavailable'
    return {'code': code, 'error': MESSAGES[code]}


def public_quote_error(error):
    payload = _public_quote_error(error)
    diagnostics = error_diagnostics(error)
    quote_diagnostics = quote_error_diagnostics(error)
    return {**payload, **({'diagnostics': diagnostics} if diagnostics else {}),
            **({'quoteDiagnostics': quote_diagnostics} if quote_diagnostics else {})}

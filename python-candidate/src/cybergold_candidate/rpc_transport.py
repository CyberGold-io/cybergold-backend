"""Web3.py source adapter; no serving route or autonomous retry scheduler."""
import asyncio
from aiohttp import ClientTimeout
from web3 import AsyncHTTPProvider
from web3._utils.http_session_manager import HTTPSessionManager
import json

from .shared_reads import SharedReads
from .quote_errors import RpcTimeout
from .rpc_diagnostics import rpc_call


class _CancellationSafeSessionManager(HTTPSessionManager):
    """Finish Web3's executor-backed cache lock even if its caller cancels."""
    def __init__(self):
        super().__init__()
        self.pending = set()

    async def async_cache_and_return_session(self, *args, **kwargs):
        # Web3's async_lock awaits a blocking thread acquire. Cancelling that
        # await can leave the acquire running after its release path has exited.
        # Only session/cache work is shielded; the subsequent HTTP request is
        # still awaited directly and retains ordinary cancellation/deadlines.
        task = asyncio.create_task(super().async_cache_and_return_session(*args, **kwargs))
        self.pending.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task):
        self.pending.discard(task)
        if not task.cancelled():
            # An abandoned caller cannot receive a later cache failure. Consume
            # it without logging provider/session details; active awaits raise.
            task.exception()

    async def finish_pending(self):
        await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.pending)),
                             return_exceptions=True)


class SharedHttpProvider(AsyncHTTPProvider):
    """Only overlapping hash-pinned eth_calls share work; heads stay fresh."""
    def __init__(self, *args, **kwargs):
        self.diagnostic_secrets = kwargs.pop('diagnostic_secrets', ())
        super().__init__(*args, **kwargs)
        self._request_session_manager = _CancellationSafeSessionManager()
        self.reads = SharedReads()

    async def make_request(self, method, params):
        async def read(method, params):
            stage = 'chain-head' if method == 'eth_getBlockByNumber' and params and params[0] == 'latest' else None
            with rpc_call(method, stage=stage, secrets=self.diagnostic_secrets) as call:
                try:
                    response = await super(SharedHttpProvider, self).make_request(method, params)
                except TimeoutError:
                    failure = RpcTimeout('RPC request timed out')
                    # The call context sees the converted timeout and records
                    # its method/timing; no provider exception text is exposed.
                    raise failure from None
                if isinstance(response, dict) and isinstance(response.get('error'), dict):
                    return {**response, 'error': call.rpc_error(response['error'])}
                return response
        if method == 'eth_call' and len(params) > 1 and isinstance(params[1], dict) and 'blockHash' in params[1]:
            key = json.dumps([method, params], sort_keys=True)
            # Each subscriber can reach its own deadline while the shared
            # physical call continues for another request.
            with rpc_call(method, secrets=self.diagnostic_secrets):
                return await self.reads.one(key, lambda: read(method, params))
        return await read(method, params)

    async def disconnect(self):
        await self.reads.close()
        # The standard disconnect closes cached sessions. Finish abandoned cache
        # lookups first so none can create a session after that cleanup.
        await self._request_session_manager.finish_pending()
        await super().disconnect()


def rpc_provider(url, authorization=None, timeout_seconds=15):
    return SharedHttpProvider(
        url,
        diagnostic_secrets=(url, authorization),
        request_kwargs={'timeout': ClientTimeout(total=timeout_seconds),
                        'allow_redirects': False,
                        'headers': {'Accept': 'application/json', 'Content-Type': 'application/json',
                                    **({'Authorization': authorization} if authorization else {})}},
        # Keep existing caller/broker deadlines and fallback in charge; defaults
        # must not silently multiply attempts or cache a canonicality check.
        exception_retry_configuration=None,
        cache_allowed_requests=False,
    )

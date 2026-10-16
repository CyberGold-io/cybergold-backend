"""Request-local RPC failure context, without URLs, credentials or call data."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from http import HTTPStatus
import asyncio
import re
from time import perf_counter
import math
from urllib.parse import parse_qsl, unquote, urlsplit
from weakref import WeakKeyDictionary

import aiohttp
import httpx
from web3.exceptions import Web3RPCError


_scope = ContextVar('rpc_diagnostic_scope', default=None)
_quote_scope = ContextVar('quote_work_scope', default=None)
_quote_background = ContextVar('quote_background_work', default=False)
_QUOTE_PHASES = {'context', 'initial-search', 'initial-preview', 'capacity', 'basket-preview',
                 'expected-input-search', 'execution-search', 'final-preview', 'canonicality',
                 'retained-validation'}
_ROUTE_PHASES = {'context', 'eligibility', 'v3-coverage', 'typed-reserve', 'structured-search', 'composition', 'canonicality'}
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


def _milliseconds(started, finished=None):
    return round(((perf_counter() if finished is None else finished) - started) * 1000, 3)


class _QuoteWork:
    """One producer's bounded logical work, independent of physical RPC context."""
    def __init__(self):
        self.owner = asyncio.current_task()
        self.started = perf_counter()
        self.phase, self.qualified, self.iteration = 'context', False, 0
        self.wave, self.frozen = None, None

    def snapshot(self):
        if self.frozen is not None:
            return self.frozen
        result = {'phase': self.phase, 'elapsedMs': _milliseconds(self.started),
                  'qualified': self.qualified, 'inversionIteration': self.iteration}
        if self.wave is not None:
            result['routeWave'] = self.wave.snapshot()
            pending = _pending_sdk(self.wave)
            if pending:
                result['pendingSdk'] = pending
        return result


class _RouteWork:
    def __init__(self, mode):
        self.mode, self.started = mode, perf_counter()
        self.subphase, self.phase_started = 'context', self.started
        self.finished, self.frozen = None, None
        self.counts = dict.fromkeys(('legacyCandidates', 'legacyCompleted', 'typedEnumerated',
                                    'typedCompleted', 'sdkRequests'), 0)
        # SDK waits/exchanges accumulate across candidates and can exceed the
        # wave's wall time. They are never added to the aggregate elapsed time.
        self.sdk_wait, self.sdk_exchange, self.sdk_active = 0, 0, {}
        self.sdk_sessions, self.sdk_sequence = {}, 0

    def snapshot(self):
        if self.frozen is not None:
            return self.frozen
        end = self.finished if self.finished is not None else perf_counter()
        waiting = sum(acquired is None for _, acquired in self.sdk_active.values())
        wait = self.sdk_wait + sum(((end if acquired is None else acquired) - queued) * 1000
                                  for queued, acquired in self.sdk_active.values())
        exchange = self.sdk_exchange + sum((end - acquired) * 1000
                                          for _, acquired in self.sdk_active.values() if acquired is not None)
        return {'mode': self.mode, 'elapsedMs': _milliseconds(self.started, end),
                'subphase': self.subphase, 'subphaseElapsedMs': _milliseconds(self.phase_started, end),
                **self.counts, 'typedPending': self.counts['typedEnumerated'] - self.counts['typedCompleted'],
                'sdkWaiting': waiting, 'sdkLockWaitMs': round(wait, 3), 'sdkExchangeMs': round(exchange, 3)}


def quote_work_scope(method):
    @wraps(method)
    async def observed(*args, **kwargs):
        token = _quote_scope.set(_QuoteWork())
        try:
            return await method(*args, **kwargs)
        except Exception as error:
            freeze_quote_work(error)
            raise
        finally:
            _quote_scope.reset(token)
    return observed


@contextmanager
def quote_background():
    # Prospective replay/qualification must not replace the main phase or
    # claim its candidate/SDK work. The original RPC diagnostic scope remains.
    token = _quote_background.set(True)
    try:
        yield
    finally:
        _quote_background.reset(token)


@contextmanager
def quote_owned_task():
    """Lend primary diagnostics to an awaited, operation-owned child task."""
    current = _quote_scope.get()
    previous = current.owner if current else None
    if current:
        current.owner = asyncio.current_task()
    try:
        yield
    finally:
        if current:
            current.owner = previous


def quote_phase(phase, *, iteration=None):
    current = _quote_scope.get()
    if current and current.owner is asyncio.current_task() and phase in _QUOTE_PHASES:
        if current.phase != phase:
            current.wave = None
        current.phase, current.frozen = phase, None
        if iteration is not None:
            current.iteration = iteration


def quote_qualified(value):
    current = _quote_scope.get()
    if current:
        current.qualified = value
        if not value:
            # A background snapshot invalidation supersedes an ordinary tail
            # error and must describe the now-retired tuple in its own error.
            current.frozen = None


def route_work_scope(method):
    @wraps(method)
    async def observed(self, request, *args, **kwargs):
        current = _quote_scope.get()
        if current and current.owner is asyncio.current_task():
            current.wave, current.frozen = _RouteWork(request['mode']), None
        try:
            return await method(self, request, *args, **kwargs)
        except BaseException as error:
            freeze_quote_work(error)
            raise
        finally:
            finish_route_work()
    return observed


def route_subphase(phase):
    current = _quote_scope.get()
    if current and current.wave and current.owner is asyncio.current_task() and phase in _ROUTE_PHASES:
        current.wave.subphase, current.wave.phase_started = phase, perf_counter()
        current.wave.finished = None


def route_count(name, amount=1):
    current = _quote_scope.get()
    if current and current.wave and not _quote_background.get() and current.wave.frozen is None and name in current.wave.counts:
        current.wave.counts[name] += amount


def finish_route_work():
    current = _quote_scope.get()
    if current and current.wave and current.owner is asyncio.current_task():
        current.wave.finished = perf_counter()


def freeze_quote_work(error=None):
    # Diagnostic collection never changes the original error or recovery.
    try:
        current = _quote_scope.get()
        if current and current.owner is asyncio.current_task():
            if current.frozen is None:
                current.frozen = current.snapshot()
                if current.wave:
                    current.wave.frozen = current.frozen.get('routeWave')
            if error is not None:
                bind_quote_error(error, current.frozen)
    except Exception:
        pass


def _quote_owner():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def bind_quote_error(error, snapshot):
    """Transfer one logical owner's snapshot without changing a shared error."""
    try:
        owner = _quote_owner()
        if owner is None or snapshot is None:
            return
        owners = getattr(error, '_quote_work_by_owner', None)
        if owners is None:
            owners = error._quote_work_by_owner = WeakKeyDictionary()
        owners[owner] = snapshot
    except Exception:
        pass


_SDK_STATES = {'initial-queued', 'resume-queued', 'exchange', 'required-read'}
_SDK_ROWS, _SDK_MEMBERS = 8, 16


def _bounded_integer(value, low=0, high=10**12):
    return type(value) is int and low <= value <= high


def _pool_identity(value):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r'0x(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', value):
        return value.lower()
    matched = re.fullmatch(r'v3:(0x[0-9a-fA-F]{40}):(0x[0-9a-fA-F]{40}):([0-9]{1,7})', value)
    if matched and int(matched[3]) <= 10**6:
        return value.lower()
    return None


def _sdk_members(value, low, high):
    if not isinstance(value, list):
        return [], 0
    members = [item for item in value[:_SDK_MEMBERS] if _bounded_integer(item, low, high)]
    return members, len(value)


def _project_pending_sdk(value):
    """Failure-log fields only; this never projects arbitrary SDK/client data."""
    if not isinstance(value, dict) or not _bounded_integer(value.get('count')):
        return None
    rows = []
    for source in value.get('rows', [])[:_SDK_ROWS] if isinstance(value.get('rows'), list) else ():
        if not isinstance(source, dict) or source.get('state') not in _SDK_STATES:
            continue
        row = {'state': source['state']}
        for name in ('session', 'stateWaits', 'wordsReturned', 'emptyWords', 'wordCount', 'tickCount',
                     'wordsOmitted', 'ticksOmitted'):
            if _bounded_integer(source.get(name)):
                row[name] = source[name]
        if source.get('mode') in ('exactIn', 'exactOut'):
            row['mode'] = source['mode']
        if source.get('protocol') in ('v2', 'v3', 'v4'):
            row['protocol'] = source['protocol']
        identity = _pool_identity(source.get('poolId'))
        if identity:
            row['poolId'] = identity
        address = source.get('poolAddress')
        if isinstance(address, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
            row['poolAddress'] = address.lower()
        for name, low, high in (('wordPositions', -32768, 32767), ('ticks', -887272, 887272)):
            if isinstance(source.get(name), list):
                row[name] = [item for item in source[name][:_SDK_MEMBERS] if _bounded_integer(item, low, high)]
        rows.append(row)
    result = {'count': value['count'], 'rows': rows}
    if _bounded_integer(value.get('omittedRows')):
        result['omittedRows'] = value['omittedRows']
    return result


class _SdkSession:
    """One SDK request/calculation, distinct from its serialized exchanges."""
    def __init__(self, payload):
        current = _quote_scope.get()
        self.wave = current.wave if current and not _quote_background.get() else None
        self.state, self.requests = 'initial-queued', None
        self.waits = self.words = self.empty = 0
        if self.wave is None or self.wave.frozen is not None:
            self.wave = None
            return
        self.pools = {row['id']: {name: row.get(name) for name in ('id', 'address', 'protocol')}
                      for row in payload.get('pools', []) if isinstance(row, dict) and isinstance(row.get('id'), str)}
        self.mode = payload.get('mode')
        if self.wave and self.wave.frozen is None:
            self.wave.sdk_sequence += 1
            self.sequence = self.wave.sdk_sequence
            self.wave.sdk_sessions[self] = self
        else:
            self.wave = None

    def queued(self):
        self.state = 'initial-queued' if self.requests is None else 'resume-queued'

    def acquired(self):
        self.state = 'exchange'

    def missing(self, requests):
        self.state, self.waits = 'required-read', self.waits+1
        rows = []
        if isinstance(requests, list):
            for needed in requests[:_SDK_ROWS]:
                if not isinstance(needed, dict):
                    continue
                pool = self.pools.get(needed.get('poolId'), {})
                words, word_count = _sdk_members(needed.get('wordPositions'), -32768, 32767)
                ticks, tick_count = _sdk_members(needed.get('ticks'), -887272, 887272)
                rows.append((pool, words, word_count, ticks, tick_count))
        self.requests = rows
        self.request_count = len(requests) if isinstance(requests, list) else 0

    def observed(self, coverage):
        # The bridge already computes newly added coverage. Count only the
        # current required observations, never scan or copy the accumulated prefix.
        wanted = {pool.get('id'): set(words) for pool, words, _, _, _ in self.requests or []}
        for pool in coverage:
            needed = wanted.get(pool.get('id'), ())
            for row in pool.get('bitmapWords', []):
                if int(row['wordPosition']) in needed:
                    self.words += 1
                    self.empty += int(row['bitmap']) == 0

    def snapshot(self):
        selected = self.requests if self.requests is not None else [(pool, [], 0, [], 0) for pool in self.pools.values()]
        rows = []
        for pool, words, word_count, ticks, tick_count in selected[:_SDK_ROWS]:
            row = {'session': self.sequence, 'mode': self.mode, 'state': self.state,
                   'protocol': pool.get('protocol'), 'poolId': pool.get('id'),
                   'poolAddress': pool.get('address'), 'wordPositions': list(words), 'ticks': list(ticks),
                   'wordCount': word_count, 'tickCount': tick_count,
                   'stateWaits': self.waits, 'wordsReturned': self.words, 'emptyWords': self.empty}
            if word_count > len(words):
                row['wordsOmitted'] = word_count-len(words)
            if tick_count > len(ticks):
                row['ticksOmitted'] = tick_count-len(ticks)
            rows.append(row)
        count = self.request_count if self.requests is not None else len(self.pools)
        return rows, count

    def freeze(self, error):
        current = _quote_scope.get()
        if self.wave and current and current.wave is self.wave and not _quote_background.get():
            freeze_quote_work(error)

    def close(self):
        if self.wave:
            self.wave.sdk_sessions.pop(self, None)


class _SdkObservation:
    """Diagnostic callbacks cannot replace an operation result or exception."""
    def __init__(self, payload):
        try:
            self.session = _SdkSession(payload)
        except Exception:
            self.session = None

    def call(self, name, *args):
        try:
            if self.session:
                return getattr(self.session, name)(*args)
        except Exception:
            pass


def quote_sdk_session(payload):
    return _SdkObservation(payload)


def _pending_sdk(wave):
    try:
        rows, count = [], 0
        for session in wave.sdk_sessions.values():
            observed, size = session.snapshot()
            count += size
            rows.extend(observed[:max(0, _SDK_ROWS-len(rows))])
        if not wave.sdk_sessions:
            return None
        value = {'count': len(wave.sdk_sessions), 'rows': rows}
        if count > len(rows):
            value['omittedRows'] = count-len(rows)
        return _project_pending_sdk(value)
    except Exception:
        return None


@contextmanager
def quote_sdk_request(session=None):
    current = _quote_scope.get()
    wave = current.wave if current and not _quote_background.get() else None
    key = object()
    if session:
        session.call('queued')
    if wave and wave.frozen is None:
        route_count('sdkRequests')
        wave.sdk_active[key] = (perf_counter(), None)
    def acquired():
        if session:
            session.call('acquired')
        if wave and key in wave.sdk_active:
            queued, _ = wave.sdk_active[key]
            wave.sdk_active[key] = (queued, perf_counter())
    try:
        yield acquired
    except asyncio.CancelledError as error:
        freeze_quote_work(error)
        raise
    finally:
        if wave and key in wave.sdk_active:
            queued, locked = wave.sdk_active.pop(key)
            end = perf_counter()
            wave.sdk_wait += ((end if locked is None else locked) - queued) * 1000
            if locked is not None:
                wave.sdk_exchange += (end - locked) * 1000


def _quote_error_source(error):
    owners, owner = getattr(error, '_quote_work_by_owner', None), _quote_owner()
    source = owners.get(owner) if isinstance(owners, WeakKeyDictionary) and owner is not None else None
    # A shared physical error never supplies another producer's owned snapshot.
    return source if source is not None else getattr(error, 'quote_diagnostics', None)


def quote_failure_context(error):
    """Internal transfer/log projection; pending SDK state stays off the wire."""
    result = quote_error_diagnostics(error)
    try:
        source = _quote_error_source(error)
        pending = _project_pending_sdk(source.get('pendingSdk')) if isinstance(source, dict) else None
        if pending:
            result = {**(result or {}), 'pendingSdk': pending}
    except Exception:
        pass
    return result


def quote_error_diagnostics(error):
    """Closed projection: diagnostic payloads cannot contain request data."""
    try:
        source = _quote_error_source(error)
        if not isinstance(source, dict):
            return None
        result = {}
        for name, allowed in (('phase', _QUOTE_PHASES),):
            if source.get(name) in allowed:
                result[name] = source[name]
        if type(source.get('qualified')) is bool:
            result['qualified'] = source['qualified']
        def numbers(value, names, target):
            for name in names:
                number = value.get(name)
                if type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 1e12:
                    target[name] = number
        numbers(source, ('elapsedMs', 'inversionIteration'), result)
        wave = source.get('routeWave')
        if isinstance(wave, dict):
            projected = {}
            if wave.get('mode') in ('exact-in', 'exact-out'):
                projected['mode'] = wave['mode']
            if wave.get('subphase') in _ROUTE_PHASES:
                projected['subphase'] = wave['subphase']
            numbers(wave, ('elapsedMs', 'subphaseElapsedMs', 'legacyCandidates', 'legacyCompleted',
                          'typedEnumerated', 'typedCompleted', 'typedPending', 'sdkRequests',
                          'sdkWaiting', 'sdkLockWaitMs', 'sdkExchangeMs'), projected)
            if projected:
                result['routeWave'] = projected
        return result or None
    except Exception:
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

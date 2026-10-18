"""Request-local RPC failure context, without URLs, credentials or call data."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from http import HTTPStatus
import asyncio
import json
import logging
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
_provider_qualification = ContextVar('provider_qualification_diagnostic', default=None)
_candidate_work_id = ContextVar('quote_candidate_work_id', default=None)
_QUOTE_PHASES = {'context', 'initial-search', 'initial-preview', 'capacity', 'basket-preview',
                 'expected-input-search', 'execution-search', 'final-preview', 'canonicality',
                 'retained-validation'}
_ROUTE_PHASES = {'context', 'eligibility', 'v3-coverage', 'typed-reserve', 'structured-search', 'composition', 'canonicality'}
_PROVIDER_STAGES = {'composition', 'basket-preview', 'initial-preview', 'execution-search',
                'expected-input-search', 'final-preview', 'tolerance', 'canonicality', 'selection',
                'route-pricing', 'fee-bounds', 'qualification', 'retained-validation'}
_PROVIDER_OUTCOMES = {'running', 'qualified', 'rejected', 'not-improved', 'cancelled', 'superseded'}
_QUOTE_CODES = {'rpc-rate-limit', 'rpc-timeout', 'rpc-unavailable', 'rpc-access-denied',
                'quote-timeout', 'quote-no-route', 'quote-contract-reverted', 'quote-unavailable',
                'insufficient-protocol-supply', 'issuance-cap-exceeded',
                'redemption-supply-exceeded', 'redemption-capacity-exceeded'}
_LEG_ROWS, _LEG_CODES, _LEG_POOLS, _PROVIDER_ROWS = 16, 16, 8, 8
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
        from .quote_budget import current_budget
        self.budget = current_budget()
        self.work_id = _candidate_work_id.get()
        self.qualifications = _ProviderQualifications(self)

    def clock(self):
        return self.budget.elapsed() if self.budget is not None else _milliseconds(self.started)

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
        if self.qualifications.attempts:
            result['providerQualifications'] = self.qualifications.snapshot()
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
        self.legs = []
        self.leg_count = 0

    def snapshot(self):
        if self.frozen is not None:
            return self.frozen
        end = self.finished if self.finished is not None else perf_counter()
        waiting = sum(acquired is None for _, acquired in self.sdk_active.values())
        wait = self.sdk_wait + sum(((end if acquired is None else acquired) - queued) * 1000
                                  for queued, acquired in self.sdk_active.values())
        exchange = self.sdk_exchange + sum((end - acquired) * 1000
                                          for _, acquired in self.sdk_active.values() if acquired is not None)
        result = {'mode': self.mode, 'elapsedMs': _milliseconds(self.started, end),
                'subphase': self.subphase, 'subphaseElapsedMs': _milliseconds(self.phase_started, end),
                **self.counts, 'typedPending': self.counts['typedEnumerated'] - self.counts['typedCompleted'],
                'sdkWaiting': waiting, 'sdkLockWaitMs': round(wait, 3), 'sdkExchangeMs': round(exchange, 3)}
        if self.leg_count:
            result['legs'] = {'count': self.leg_count, 'omittedRows': self.leg_count-len(self.legs),
                              'rows': [leg.snapshot() for leg in self.legs]}
        return result


def quote_work_scope(method):
    @wraps(method)
    async def observed(*args, **kwargs):
        token = _quote_scope.set(_QuoteWork())
        try:
            return await method(*args, **kwargs)
        except BaseException as error:
            freeze_quote_work(error)
            raise
        finally:
            _quote_scope.reset(token)
    return observed


@contextmanager
def quote_candidate_scope(work_id):
    """A shared producer owns observations; subscribers never emit copies."""
    valid = isinstance(work_id, str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', work_id)
    token = _candidate_work_id.set(work_id if valid else None)
    try:
        yield
    finally:
        _candidate_work_id.reset(token)


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
    provider_qualification_stage(phase)
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


def start_route_work(mode):
    """Observe non-facade consumers after their normal request validation."""
    current = _quote_scope.get()
    if current and current.owner is asyncio.current_task() and mode in ('exact-in', 'exact-out'):
        current.wave, current.frozen = _RouteWork(mode), None


def route_subphase(phase):
    provider_qualification_stage(phase)
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


def _uint256(value):
    return (isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,77}', value) is not None
            and int(value) < 2**256)


def _address(value):
    return value.lower() if isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', value) else None


def _one_of(value, allowed):
    return isinstance(value, str) and value in allowed


def _safe_pools(branches):
    """Pool identities only: never retain executable route/request contents."""
    pools, seen, total = [], set(), 0
    for branch in branches if isinstance(branches, list) else ():
        for hop in branch.get('hops', []) if isinstance(branch, dict) and isinstance(branch.get('hops'), list) else ():
            pool = hop.get('pool') if isinstance(hop, dict) else None
            if not isinstance(pool, dict) or not _one_of(pool.get('protocol'), ('v2', 'v3', 'v4')):
                continue
            row = {'protocol': pool['protocol']}
            identity, address = _pool_identity(pool.get('id')), _address(pool.get('address'))
            if identity:
                row['poolId'] = identity
            if address:
                row['poolAddress'] = address
            if not identity and not address:
                continue
            key = tuple(row.items())
            if key in seen:
                continue
            seen.add(key)
            total += 1
            if len(pools) < _LEG_POOLS:
                pools.append(row)
    return pools, max(0, total-len(pools))


def _observation(default=None):
    """Optional evidence cannot replace the producer's ordinary result/error."""
    def decorate(function):
        @wraps(function)
        def observed(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception:
                return default
        return observed
    return decorate


class _RouteLeg:
    def __init__(self, wave, index, target):
        self.wave, self.index = wave, index
        self.target = {name: target[name] for name in ('inputAsset', 'outputAsset', 'amount') if name in target}
        self.started = self.succeeded = self.failed = self.cancelled = 0
        self.best = target.get('inputAsset', '').lower() == target.get('outputAsset', '').lower()
        self.codes, self.pools, self.omitted_pools = {}, [], 0

    def snapshot(self):
        row = {'index': self.index, 'started': self.started, 'succeeded': self.succeeded,
               'failed': self.failed, 'cancelled': self.cancelled,
               'pending': self.started-self.succeeded-self.failed-self.cancelled,
               'bestAvailable': self.best, 'failureCounts': [dict(code=code, count=count)
                   for code, count in list(self.codes.items())[:_LEG_CODES]],
               'omittedFailureCodes': max(0, len(self.codes)-_LEG_CODES),
               'bestPools': [dict(pool) for pool in self.pools], 'omittedPools': self.omitted_pools}
        for name in ('inputAsset', 'outputAsset'):
            if value := _address(self.target.get(name)):
                row[name] = value
        if _uint256(self.target.get('amount')):
            row['amount'] = self.target['amount']
        return row


@_observation(())
def route_legs(targets):
    current = _quote_scope.get()
    wave = current.wave if current and not _quote_background.get() else None
    if wave is None or wave.frozen is not None:
        return []
    wave.leg_count = len(targets)
    wave.legs = [_RouteLeg(wave, index, target) for index, target in enumerate(targets[:_LEG_ROWS])]
    return wave.legs


@_observation()
def route_leg_started(leg, *, amount=None):
    if leg is not None and leg.wave.frozen is None:
        if amount is not None and leg.target.get('amount') != amount:
            # A retained replay and its ordinary fallback can price distinct
            # routed amounts. Keep their counts without claiming one amount.
            leg.target.pop('amount', None)
        leg.started += 1


@_observation()
def route_leg_finished(leg, outcome, *, code=None, best=None):
    if leg is None or leg.wave.frozen is not None:
        return
    if outcome == 'succeeded':
        leg.succeeded += 1
        if best:
            leg.best = True
            leg.pools, leg.omitted_pools = _safe_pools(best['routePlan']['branches'])
    elif outcome == 'failed':
        leg.failed += 1
        code = code if code in _QUOTE_CODES else 'quote-unavailable'
        leg.codes[code] = leg.codes.get(code, 0)+1
    elif outcome == 'cancelled':
        leg.cancelled += 1


class _ProviderQualifications:
    def __init__(self, work):
        self.work = work
        self.attempts, self.rows = 0, []
        self.provider = None
        self.selected = None
        self.counts = dict.fromkeys(('qualified', 'rejected', 'not-improved', 'cancelled', 'superseded'), 0)

    def keep(self, row):
        if row not in self.rows:
            self.rows.append(row)
        if len(self.rows) > _PROVIDER_ROWS:
            old = next((entry for entry in self.rows if entry['outcome'] != 'running'
                        and entry['attempt'] != self.selected), None)
            old = old or next((entry for entry in self.rows if entry['attempt'] != self.selected), self.rows[0])
            self.rows.remove(old)

    def snapshot(self):
        rows = [{**row, **({'elapsedMs': max(0, round(self.work.clock()-row['startedMs'], 3))}
                          if row['outcome'] == 'running' else {})} for row in self.rows]
        return {'provider': self.provider, 'attempts': self.attempts, **{('notImproved' if key == 'not-improved' else key): count
                    for key, count in self.counts.items()},
                'pending': self.attempts-sum(self.counts.values()),
                'omittedRows': self.attempts-len(self.rows), 'rows': rows,
                **({'selectedAttempt': self.selected} if self.selected is not None else {}),
                **_selection_fields(self.work.budget)}


class _ProviderQualification:
    def __init__(self, work, stage):
        self.work = work
        work.qualifications.attempts += 1
        self.row = {'attempt': work.qualifications.attempts, 'stage': stage, 'outcome': 'running',
                    'startedMs': round(work.clock(), 3)}
        work.qualifications.keep(self.row)
        self.scheduled = False
        self.logged_terminal = False
        self.observe('started', self.row)

    @_observation()
    def observe(self, phase, row):
        if self.work.work_id is None:
            return
        candidate = _project_qualification_row(row)
        if candidate is not None:
            from .telemetry import observe
            record = {'event': 'quote_candidate', 'workId': self.work.work_id,
                      'provider': self.work.qualifications.provider, 'phase': phase,
                      'candidate': candidate}
            observe(lambda: logging.getLogger('cybergold.candidate').info(json.dumps(record)))

    def finish(self, outcome, error=None):
        if self.logged_terminal or self.row['outcome'] != 'running' or outcome not in _PROVIDER_OUTCOMES-{'running'}:
            return
        # Snapshot rows/counters are copied at the cutoff. Keep live cleanup
        # state accurate too: a later successful finalization may unfreeze it.
        row = self.row
        row['outcome'] = outcome
        row['completedMs'] = round(self.work.clock(), 3)
        row['elapsedMs'] = max(0, round(row['completedMs']-row['startedMs'], 3))
        self.work.qualifications.counts[outcome] += 1
        if error is not None and outcome == 'rejected':
            # Import lazily: quote_errors itself projects these diagnostics.
            from .quote_errors import public_quote_error
            code = public_quote_error(error)['code']
            if code == 'quote-unavailable':
                from .quote_errors import QuoteFailure
                from .preview_errors import KnownPreviewError
                if isinstance(error.__cause__, (QuoteFailure, KnownPreviewError)):
                    code = public_quote_error(error.__cause__)['code']
            row['code'] = code if code in _QUOTE_CODES else 'quote-unavailable'
        self.logged_terminal = True
        self.observe('completed', row)


@_observation()
def provider_qualification_begin(stage='selection', *, provider='core'):
    current = _quote_scope.get()
    if current is None or current.frozen is not None or stage not in _PROVIDER_STAGES or provider not in ('core', 'market'):
        return None
    if current.qualifications.provider is not None and current.qualifications.provider != provider:
        return None
    current.qualifications.provider = provider
    return _ProviderQualification(current, stage)


@contextmanager
def provider_qualification_scope(probe):
    token = _provider_qualification.set(probe)
    try:
        yield
    finally:
        _provider_qualification.reset(token)


@_observation()
def provider_qualification_stage(stage, **bounds):
    probe = _provider_qualification.get()
    if probe is None or probe.work is not _quote_scope.get() or probe.work.frozen is not None or probe.row['outcome'] != 'running':
        return
    if stage in _PROVIDER_STAGES:
        probe.row['stage'] = stage
    if stage == 'tolerance':
        for name in ('targetAmount', 'minimumAmountOut', 'maximumAmountOut', 'observedAmountOut',
                     'maximumAmountIn', 'observedAmountIn'):
            if _uint256(bounds.get(name)):
                probe.row[name] = bounds[name]


def provider_qualification_current():
    probe = _provider_qualification.get()
    return probe if probe is not None and probe.work is _quote_scope.get() and probe.row['outcome'] == 'running' else None


@_observation()
def provider_qualification_terms(*, branches=None, **amounts):
    probe = provider_qualification_current()
    if probe is None or probe.work.frozen is not None:
        return
    for name in ('executionAmount', 'quotedInput', 'quotedOutput', 'inputMaximum', 'outputMinimum'):
        if _uint256(amounts.get(name)):
            probe.row[name] = amounts[name]
    if branches is not None:
        probe.row['pools'], probe.row['omittedPools'] = _safe_pools(branches)


@_observation()
def provider_qualification_selected(probe):
    if probe is not None and probe.work is _quote_scope.get() and probe.work.frozen is None:
        probe.work.qualifications.selected = probe.row['attempt']
        probe.work.qualifications.keep(probe.row)


def _selection_fields(budget):
    if budget is None:
        return {}
    fields = budget.metrics()
    result = {key: fields[key] for key in ('firstQualifiedMs', 'selectionMs', 'canonicalCompletedMs',
              'cleanupCompletedMs') if key in fields}
    reason = budget.timings().get('selectionReason')
    if reason in ('complete', 'best-initial', 'first-extension', 'timeout'):
        result['selectionReason'] = reason
    return result


@_observation()
def current_quote_diagnostics():
    current = _quote_scope.get()
    return project_quote_diagnostics(current.snapshot()) if current is not None else None


@_observation()
def finalize_quote_diagnostics(value, budget):
    """Complete the existing shared clock after producer finalization."""
    if not isinstance(value, dict):
        return
    diagnostic = value.get('quoteDiagnostics')
    if isinstance(diagnostic, dict) and isinstance(diagnostic.get('providerQualifications'), dict):
        diagnostic['providerQualifications'].update(_selection_fields(budget))
    for name in ('providerQuote',):
        finalize_quote_diagnostics(value.get(name), budget)
    for name in ('providerCandidates', 'providerAssessments'):
        rows = value.get(name)
        if isinstance(rows, dict):
            for provider in ('core', 'market'):
                finalize_quote_diagnostics(rows.get(provider), budget)


@_observation()
def provider_qualification_finish(probe, outcome, error=None):
    if probe is not None:
        probe.finish(outcome, error)


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


def _project_pools(values):
    pools = []
    for pool in values[:_LEG_POOLS] if isinstance(values, list) else ():
        if not isinstance(pool, dict) or not _one_of(pool.get('protocol'), ('v2', 'v3', 'v4')):
            continue
        safe = {'protocol': pool['protocol']}
        if identity := _pool_identity(pool.get('poolId')):
            safe['poolId'] = identity
        if address := _address(pool.get('poolAddress')):
            safe['poolAddress'] = address
        if len(safe) > 1:
            pools.append(safe)
    return pools


def _project_route_legs(value):
    if not isinstance(value, dict) or not _bounded_integer(value.get('count')):
        return None
    result = {'count': value['count'], 'rows': []}
    if _bounded_integer(value.get('omittedRows')):
        result['omittedRows'] = value['omittedRows']
    for source in value.get('rows', [])[:_LEG_ROWS] if isinstance(value.get('rows'), list) else ():
        if not isinstance(source, dict) or not _bounded_integer(source.get('index')):
            continue
        row = {name: source[name] for name in ('index', 'started', 'succeeded', 'failed', 'cancelled',
               'pending', 'omittedFailureCodes', 'omittedPools') if _bounded_integer(source.get(name))}
        if type(source.get('bestAvailable')) is bool:
            row['bestAvailable'] = source['bestAvailable']
        for name in ('inputAsset', 'outputAsset'):
            if address := _address(source.get(name)):
                row[name] = address
        if _uint256(source.get('amount')):
            row['amount'] = source['amount']
        row['failureCounts'] = [{'code': failure['code'], 'count': failure['count']}
            for failure in source.get('failureCounts', [])[:_LEG_CODES]
            if isinstance(failure, dict) and _one_of(failure.get('code'), _QUOTE_CODES)
            and _bounded_integer(failure.get('count'))] if isinstance(source.get('failureCounts'), list) else []
        row['bestPools'] = _project_pools(source.get('bestPools'))
        result['rows'].append(row)
    return result


def _project_provider_qualifications(value):
    if not isinstance(value, dict) or not _bounded_integer(value.get('attempts')) \
            or not _one_of(value.get('provider'), ('core', 'market')):
        return None
    result = {name: value[name] for name in ('attempts', 'qualified', 'rejected', 'notImproved',
              'cancelled', 'superseded', 'pending', 'omittedRows', 'selectedAttempt') if _bounded_integer(value.get(name))}
    for name in ('firstQualifiedMs', 'selectionMs', 'canonicalCompletedMs', 'cleanupCompletedMs'):
        if type(value.get(name)) in (int, float) and math.isfinite(value[name]) and 0 <= value[name] <= 1e12:
            result[name] = value[name]
    if _one_of(value.get('selectionReason'), ('complete', 'best-initial', 'first-extension', 'timeout')):
        result['selectionReason'] = value['selectionReason']
    rows = [_project_qualification_row(source) for source in value.get('rows', [])[:_PROVIDER_ROWS]] \
        if isinstance(value.get('rows'), list) else []
    return {**result, 'provider': value['provider'], 'rows': [row for row in rows if row is not None]}


def _project_qualification_row(source):
    if not isinstance(source, dict) or not _bounded_integer(source.get('attempt')) \
            or not _one_of(source.get('stage'), _PROVIDER_STAGES) or not _one_of(source.get('outcome'), _PROVIDER_OUTCOMES):
        return None
    row = {name: source[name] for name in ('attempt', 'stage', 'outcome')}
    for name in ('startedMs', 'completedMs', 'elapsedMs'):
        if type(source.get(name)) in (int, float) and math.isfinite(source[name]) and 0 <= source[name] <= 1e12:
            row[name] = source[name]
    if _one_of(source.get('code'), _QUOTE_CODES):
        row['code'] = source['code']
    for name in ('targetAmount', 'minimumAmountOut', 'maximumAmountOut', 'observedAmountOut',
                 'maximumAmountIn', 'observedAmountIn', 'executionAmount', 'quotedInput', 'quotedOutput',
                 'inputMaximum', 'outputMinimum'):
        if _uint256(source.get(name)):
            row[name] = source[name]
    if isinstance(source.get('pools'), list):
        row['pools'] = _project_pools(source['pools'])
    if _bounded_integer(source.get('omittedPools')):
        row['omittedPools'] = source['omittedPools']
    return row


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


def project_quote_diagnostics(source):
    """Closed projection: diagnostic payloads cannot contain request data."""
    try:
        if not isinstance(source, dict):
            return None
        result = {}
        for name, allowed in (('phase', _QUOTE_PHASES),):
            if _one_of(source.get(name), allowed):
                result[name] = source[name]
        if type(source.get('qualified')) is bool:
            result['qualified'] = source['qualified']
        def numbers(value, names, target):
            for name in names:
                number = value.get(name)
                if type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 1e12:
                    target[name] = number
        numbers(source, ('elapsedMs', 'inversionIteration'), result)
        qualifications = _project_provider_qualifications(source.get('providerQualifications'))
        if qualifications:
            result['providerQualifications'] = qualifications
        wave = source.get('routeWave')
        if isinstance(wave, dict):
            projected = {}
            if wave.get('mode') in ('exact-in', 'exact-out'):
                projected['mode'] = wave['mode']
            if _one_of(wave.get('subphase'), _ROUTE_PHASES):
                projected['subphase'] = wave['subphase']
            numbers(wave, ('elapsedMs', 'subphaseElapsedMs', 'legacyCandidates', 'legacyCompleted',
                          'typedEnumerated', 'typedCompleted', 'typedPending', 'sdkRequests',
                          'sdkWaiting', 'sdkLockWaitMs', 'sdkExchangeMs'), projected)
            legs = _project_route_legs(wave.get('legs'))
            if legs:
                projected['legs'] = legs
            if projected:
                result['routeWave'] = projected
        return result or None
    except Exception:
        return None


def quote_error_diagnostics(error):
    try:
        return project_quote_diagnostics(_quote_error_source(error))
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

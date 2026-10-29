"""Best-effort subscriber observations; shared producers never inherit caller IDs."""
import json
import logging
import time
import uuid
import math
import re

from .diagnostics import project
from .quote_errors import public_quote_error
from .rpc_diagnostics import quote_failure_context
from .telemetry import observe


_ECONOMIC_KINDS = {'quoter', 'transaction-preparation', 'fast-estimator'}
_ECONOMIC_SOURCES = {'stored-quote', 'search', 'refresh', 'prepared-transaction', 'fast-estimate'}
_ECONOMIC_PHASES = {'lookup', 'current-state-search', 'selected-plan-replay', 'advisory-estimate'}


def economic_evidence(value, evidence):
    """Bounded public economic facts, never plans, calldata or wallet material."""
    result = {}
    for key, allowed in (('operationKind', _ECONOMIC_KINDS), ('resultSource', _ECONOMIC_SOURCES),
                         ('operationPhase', _ECONOMIC_PHASES)):
        if evidence.get(key) in allowed:
            result[key] = evidence[key]
    def raw(number):
        return isinstance(number, str) and re.fullmatch(r'[0-9]{1,78}', number) and int(number) < 2**256
    def assets(rows):
        return [{'currency': row['currency'], 'amount': row['amount']} for row in rows[:32]
            if isinstance(row, dict) and raw(row.get('amount')) and isinstance(row.get('currency'), str)
            and re.fullmatch(r'0x[0-9a-fA-F]{40}', row['currency'])]
    budget = assets(evidence.get('requestInputs', []))
    if budget:
        result['inputBudget'] = budget
    if isinstance(value, dict):
        result.update(project(value.get('context', {})))
        for name in ('quotedInput', 'quotedOutput', 'inputMaximum', 'outputMinimum'):
            if raw(value.get(name)):
                result[name] = value[name]
        funding = assets(value.get('inputs', []))
        if funding:
            result['funding'] = funding
        estimate = value.get('estimate', {})
        if isinstance(estimate, dict) and raw(estimate.get('amount')):
            result['estimatedAmount'] = estimate['amount']
        phase = value.get('searchCoverage', {}).get('selectedPhase')
        if phase in ('saved-plan', 'first-result', 'detailed'):
            result['routePhase'] = phase
        metrics = value.get('metrics') or evidence.get('producerMetrics') or {}
        safe = {}
        for key in ('timeToFirstWholePlanMs', 'searchMs', 'totalMs', 'finalizationMs'):
            number = metrics.get(key)
            if type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 1e12:
                safe[key] = number
        if metrics.get('selectionReason') in ('complete', 'best-initial', 'first-extension', 'timeout'):
            safe['selectionReason'] = metrics['selectionReason']
        if safe:
            result['observedQuoteMetrics' if result.get('resultSource') == 'stored-quote' else 'producerMetrics'] = safe
    rpc = evidence.get('rpc', {})
    projected = {}
    for section, scope, keys in (
        ('getterReads', 'hash-pinned-getter-bank', ('requested', 'issued', 'coalesced', 'reused')),
        ('transport', 'owned-provider-exchanges', ('started', 'completed', 'rpcCallsStarted', 'summedExchangeMs'))):
        source = rpc.get(section, {})
        row = {key: source[key] for key in keys if type(source.get(key)) in (int, float)
               and math.isfinite(source[key]) and 0 <= source[key] <= 1e12}
        if row:
            projected[section] = {'scope': scope, **row}
    if projected:
        result['rpc'] = projected
    return result


def request_references(request):
    state = getattr(request, 'scope', {}).get('state', {})
    return {key: state[key] for key in ('request_id', 'attempt_id') if state.get(key)}


def references(request):
    names = {'request_id': 'requestId', 'attempt_id': 'attemptId'}
    return {names[key]: value for key, value in request_references(request).items()}


def failure(request, error, context, *, strategy=None, work_id=None, payload=None):
    payload = dict(payload or public_quote_error(error))
    result = {**payload, **references(request), 'correlationId': str(uuid.uuid4())}
    if work_id:
        result['workId'] = work_id
    record = {**result, 'event': 'quote_failure', 'context': context,
              'errorClassification': payload.get('code', context+'-unavailable'), 'component': 'api'}
    if error is not None:
        record['exceptionType'] = type(error).__name__
        details = quote_failure_context(error) or {}
        if 'pendingSdk' in details:
            record['pendingSdk'] = details['pendingSdk']
    if strategy:
        record['strategy'] = strategy
    observe(lambda: logging.getLogger('cybergold.candidate').error(json.dumps(record)))
    return result


class QuoteObservation:
    """Measure logical HTTP subscriptions, including losing-provider failures."""
    def __init__(self, request, intent, strategy=None):
        self.request, self.strategy = request, strategy
        self.operation = getattr(request, 'scope', {}).get('path', 'unmatched')
        try:
            self.metrics = request.app.state.metrics
        except (AttributeError, KeyError):
            # Domain/direct-handler comparisons have no HTTP application.
            # Observations remain optional there as well as at serving time.
            self.metrics = None
        self.started = time.perf_counter()
        self.first = None
        self.terminal = False
        self.work_id = None
        mode = intent.get('mode', '')
        self.mode = mode if mode in ('exact-in', 'exact-out', 'issue-exact-in', 'issue-exact-out',
                                     'redeem-exact-in', 'redeem-exact-out') else 'other'
        self.context = project({**intent, 'inputMode': mode.removeprefix('issue-').removeprefix('redeem-'),
                                'direction': 'issue' if mode.startswith('issue-') else
                                             'redeem' if mode.startswith('redeem-') else None})

    def event(self, frame):
        # Copy subscriber metadata onto the transport frame only. Never mutate
        # the producer's replay bank, plan, cache key or shared exception.
        result = {**frame, **references(self.request)}
        self.work_id = frame.get('workId') or self.work_id
        if self.work_id:
            result['workId'] = self.work_id
        kind = frame['type']
        strategy = frame.get('strategy') or (frame.get('value') or {}).get('strategy') or self.strategy or 'none'
        strategy = strategy if strategy in ('core', 'market', 'universal') else 'none'
        if kind == 'provider-error':
            result = {**failure(self.request, None, self.operation,
                               strategy=strategy, work_id=self.work_id,
                               payload={key: frame[key] for key in ('error', 'code', 'constraint', 'diagnostics', 'quoteDiagnostics') if key in frame}),
                      'type': kind, 'strategy': strategy}
            observe(lambda: self.metrics.quote_provider_outcomes.labels(self.operation, strategy, 'failed').inc())
        if kind in ('qualified', 'complete') and not (frame.get('value') or {}).get('readOnly') and self.first is None:
            self.first = time.perf_counter()-self.started
            observe(lambda: self.metrics.quote_first_executable.labels(self.operation, self.mode).observe(self.first))
        if kind in ('qualified', 'invalidated', 'provider-error', 'complete', 'error'):
            observe(lambda: self.metrics.quote_stages.labels(self.operation, strategy, kind).inc())
        if kind in ('complete', 'error'):
            self.finish('succeeded' if kind == 'complete' else 'failed', strategy, result)
        return result

    def error(self, error):
        return {'type': 'error', **failure(self.request, error, self.operation, work_id=self.work_id)}

    def finish(self, outcome, strategy='none', frame=None):
        if self.terminal:
            return
        self.terminal = True
        observe(lambda: self.metrics.quote_outcomes.labels(self.operation, self.mode, outcome).inc())
        if self.strategy in ('core', 'market') and outcome in ('succeeded', 'failed'):
            observe(lambda: self.metrics.quote_provider_outcomes.labels(self.operation, self.strategy, outcome).inc())
        record = {**self.context, **references(self.request), 'event': 'quote_outcome',
                  'operation': self.operation, 'mode': self.mode, 'outcome': outcome, 'strategy': strategy,
                  'durationMs': round((time.perf_counter()-self.started)*1000, 3), 'component': 'api'}
        if self.first is not None:
            record['firstExecutableMs'] = round(self.first*1000, 3)
        if self.work_id:
            record['workId'] = self.work_id
        if frame:
            for key in ('correlationId', 'code'):
                if key in frame:
                    record[key] = frame[key]
            value = frame.get('value', {})
            record.update(project({**value, **value.get('context', {})}))
            if isinstance(frame.get('economicEvidence'), dict):
                def economic():
                    facts = economic_evidence(value, frame['economicEvidence'])
                    record.update(facts)
                    source = facts.get('resultSource')
                    if source:
                        self.metrics.economic_results.labels(self.operation, source, outcome).inc()
                    first = facts.get('producerMetrics', {}).get('timeToFirstWholePlanMs')
                    if source in ('search', 'refresh') and first is not None:
                        self.metrics.quoter_first_plan.labels(self.operation).observe(first/1000)
                observe(economic)
            for provider, status in value.get('evaluation', {}).items():
                if provider in ('core', 'market') and status == 'complete':
                    observe(lambda p=provider: self.metrics.quote_provider_outcomes.labels(self.operation, p, 'succeeded').inc())
        observe(lambda: logging.getLogger('cybergold.candidate').info(json.dumps(record)))

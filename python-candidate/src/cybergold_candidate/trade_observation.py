"""Best-effort subscriber observations; shared producers never inherit caller IDs."""
import json
import logging
import time
import uuid

from .diagnostics import project
from .quote_errors import public_quote_error
from .rpc_diagnostics import quote_failure_context
from .telemetry import observe


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
            for provider, status in value.get('evaluation', {}).items():
                if provider in ('core', 'market') and status == 'complete':
                    observe(lambda p=provider: self.metrics.quote_provider_outcomes.labels(self.operation, p, 'succeeded').inc())
        observe(lambda: logging.getLogger('cybergold.candidate').info(json.dumps(record)))

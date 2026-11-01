"""Request-local physical transport observations, independent of quote policy.

RPC counts sit below shared-read coalescing and count HTTP attempts plus JSON-RPC
members. One Multicall eth_call is one member; its inner calls are not counted.
Shared work is charged to its first issuing owner, not every benefiting caller.
No URL, headers, parameters, response body or exception text is retained here.
"""
import asyncio
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import re
import time


DISCOVERY_PROVIDERS = frozenset(('cybergold-custom', 'uniswap-alpharouter',
    'uniswap-standard-api', 'uniswap-guidestar', 'uniroute', 'uniroute-api', 'uniroute-local'))
TRANSPORT_ORIGINS = DISCOVERY_PROVIDERS | frozenset(('cybergold-quoter', 'other'))
RPC_METHODS = frozenset(('eth_call', 'eth_chainId', 'eth_getBlockByNumber', 'eth_getBlockByHash',
    'eth_getCode', 'eth_getStorageAt', 'eth_getBalance', 'eth_getLogs', 'eth_estimateGas',
    'eth_getTransactionReceipt', 'eth_getTransactionByHash', 'eth_getTransactionCount',
    'eth_gasPrice', 'eth_maxPriorityFeePerGas', 'eth_feeHistory', 'net_version',
    'web3_clientVersion', 'debug_traceTransaction', 'trace_transaction'))

_recorder = ContextVar('route_transport_observations', default=None)
_origin = ContextVar('route_discovery_origin', default='cybergold-quoter')


def current_route_observations():
    return _recorder.get()


@contextmanager
def route_observation_scope(recorder):
    token = _recorder.set(recorder)
    try:
        yield recorder
    finally:
        _recorder.reset(token)


@contextmanager
def origin_scope(name):
    # These labels are diagnostics only. Unknown names share one bounded label;
    # they never decide whether a provider or quote can run.
    token = _origin.set(name if isinstance(name, str) and name in TRANSPORT_ORIGINS else 'other')
    try:
        yield
    finally:
        _origin.reset(token)


def _row():
    return {'requests': 0, 'jsonRpcMembers': 0, 'batchRequests': 0, 'batchMembers': 0,
            'completed': 0, 'errors': 0, 'cancelled': 0, 'summedElapsedMs': 0.0}


def _snapshot(row):
    return {**row, 'inFlight': row['requests'] - row['completed'] - row['errors'] - row['cancelled'],
            'summedElapsedMs': round(row['summedElapsedMs'], 3)}


def _rpc_members(data):
    try:
        value = json.loads(data) if isinstance(data, (bytes, bytearray, str)) else data
    except (ValueError, TypeError, UnicodeDecodeError):
        return [], False
    if isinstance(value, list):
        return value, True
    return ([value] if isinstance(value, dict) else []), False


class RouteObservations:
    def __init__(self):
        self.rpc, self.api = _row(), _row()
        self.rpc_origins, self.api_origins = {}, {}
        self.methods = Counter()
        self.discovery = {}

    @property
    def metrics(self):
        return {'scope': 'physical-http-attempts', **_snapshot(self.rpc),
                'methods': dict(sorted(self.methods.items())),
                'origins': {name: _snapshot(row) for name, row in sorted(self.rpc_origins.items())}}

    @property
    def api_metrics(self):
        # Hosted routing HTTP is not chain RPC and is never added to RPC totals.
        keys = ('requests', 'completed', 'errors', 'cancelled', 'inFlight', 'summedElapsedMs')
        def project(row):
            observed = _snapshot(row)
            return {key: observed[key] for key in keys}
        return {'scope': 'hosted-api-http-attempts', **project(self.api),
                'origins': {name: project(row) for name, row in sorted(self.api_origins.items())}}

    @contextmanager
    def record_http(self, data=None, *, api=False):
        """Surround an actual post attempt after any cached-session acquisition."""
        aggregate, origins = (self.api, self.api_origins) if api else (self.rpc, self.rpc_origins)
        owned = origins.setdefault(_origin.get(), _row())
        rows = aggregate, owned
        for row in rows:
            row['requests'] += 1
        if not api:
            members, batch = _rpc_members(data)
            for row in rows:
                row['jsonRpcMembers'] += len(members)
                row['batchRequests'] += int(batch)
                row['batchMembers'] += len(members) if batch else 0
            for member in members:
                method = member.get('method') if isinstance(member, dict) else None
                self.methods[method if isinstance(method, str) and method in RPC_METHODS else 'other'] += 1
        started, status = time.perf_counter(), 'completed'
        try:
            yield
        except asyncio.CancelledError:
            status = 'cancelled'
            raise
        except BaseException:
            status = 'errors'
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            for row in rows:
                row[status] += 1
                row['summedElapsedMs'] += elapsed


@contextmanager
def physical_rpc_exchange(data):
    recorder = _recorder.get()
    if recorder is None:
        yield
    else:
        with recorder.record_http(data):
            yield


@contextmanager
def api_exchange():
    recorder = _recorder.get()
    if recorder is None:
        yield
    else:
        with recorder.record_http(api=True):
            yield


def _numbers(source, names):
    if not isinstance(source, dict):
        return {}
    return {name: source[name] for name in names if type(source.get(name)) in (int, float)
            and math.isfinite(source[name]) and 0 <= source[name] <= 1e12}


def project_route_origins(source):
    """Closed log projection: known source labels and semantic operation names."""
    if not isinstance(source, dict):
        return {}
    result = {}
    for key, known in (('economicEvaluator', ('cybergold-quoter',)),
                       ('pricing', ('cybergold-sdk', 'canonical-sdk-and-core-previews'))):
        if source.get(key) in known:
            result[key] = source[key]
    def providers(value):
        if not isinstance(value, (list, tuple)):
            return []
        return sorted({name for name in value if isinstance(name, str)
                       and name in DISCOVERY_PROVIDERS | {'unspecified'}})
    names = providers(source.get('discoveryProviders'))
    if names or source.get('discoveryProviders') == []:
        result['discoveryProviders'] = names
    adapter = source.get('adapterConversions')
    if isinstance(adapter, list):
        operations = [operation for operation in adapter if isinstance(operation, str)
            and re.fullmatch(r'[0-9]{1,3}:(?:market|(?:acquire|residual|redeem):[0-9]{1,3})', operation)]
        if operations:
            result['adapterConversions'] = sorted(set(operations))
    conversions = source.get('conversions')
    if isinstance(conversions, dict):
        observed = {}
        for operation, origins in list(conversions.items())[:128]:
            if (isinstance(operation, str) and re.fullmatch(
                    r'[0-9]{1,3}:(?:market|(?:acquire|residual|redeem):[0-9]{1,3})', operation)):
                names = providers(origins)
                if names:
                    observed[operation] = names
        if observed:
            result['conversions'] = observed
    return result


def _project_transport(source, *, api=False):
    if not isinstance(source, dict):
        return {}
    scope = 'hosted-api-http-attempts' if api else 'physical-http-attempts'
    if source.get('scope') != scope:
        return {}
    names = ('requests', 'completed', 'errors', 'cancelled', 'inFlight', 'summedElapsedMs')
    if not api:
        names += ('jsonRpcMembers', 'batchRequests', 'batchMembers')
    result = {'scope': scope, **_numbers(source, names)}
    origins = source.get('origins')
    if isinstance(origins, dict):
        rows = {name: _numbers(row, names) for name, row in origins.items()
                if name in TRANSPORT_ORIGINS}
        if rows:
            result['origins'] = rows
    methods = source.get('methods')
    if not api and isinstance(methods, dict):
        result['methods'] = _numbers(methods, (*RPC_METHODS, 'other'))
    return result


def project_route_discovery(source):
    """Origin and transport facts without request keys or supplier error text."""
    if not isinstance(source, dict):
        return {}
    result = _numbers(source, ('queries', 'revision', 'reevaluations', 'quickReevaluations', 'closeErrors',
                              'startedMs', 'completedMs', 'elapsedMs'))
    if source.get('clock') in ('producer', 'session'):
        result['clock'] = source['clock']
    providers = source.get('providers')
    if isinstance(providers, dict):
        names = ('started', 'available', 'pending', 'completed', 'empty', 'unavailable', 'error', 'cancelled',
                 'stopped', 'invalidated', 'candidates', 'startedMs', 'firstCandidateMs',
                 'completedMs', 'cancelledMs', 'durationMs', 'feedReads', 'feedIterations',
                 'feedErrors', 'feedReadMs', 'batches', 'workerQueries', 'quoteCallbacks',
                 'quoteCallbackFailures', 'quoteCallbackMs')
        rows = {}
        for name, row in providers.items():
            if name not in DISCOVERY_PROVIDERS:
                continue
            observed = _numbers(row, names)
            attribution = row.get('engineAttribution') if isinstance(row, dict) else None
            if isinstance(attribution, dict):
                engines = _numbers(attribution.get('engines'), ('uniroute', 'guidestar', 'unverified'))
                evidence = _numbers(attribution.get('evidence'),
                    ('route-candidates', 'swap-steps', 'not-disclosed', 'ambiguous'))
                if engines or evidence:
                    observed['engineAttribution'] = {'engines': engines, 'evidence': evidence}
            rows[name] = observed
        if rows:
            result['providers'] = rows
    for key, api in (('physicalRpc', False), ('apiRequests', True)):
        projected = _project_transport(source.get(key), api=api)
        if projected:
            result[key] = projected
    return result

"""Bounded evidence of repeated Helpers failures; never a response cache.

Only digests and closed result categories survive the call. Matching wire/error
bytes at ``latest`` do not prove matching chain state or authorize result reuse.
"""
from collections import Counter
from hashlib import sha256
import asyncio
import json

from ..preview_errors import preview_error
from ..quote_errors import public_quote_error, rpc_failure


class PlanCallCensus:
    def __init__(self, max_entries=4096):
        # Same entry budget as the search's completed-read bank; no payloads.
        self.max_entries = max_entries
        self.started = 0
        self.outcomes = Counter()
        self.failures = {}
        self.untracked = 0

    @staticmethod
    def identity(provider, wire, params, shared):
        tag = params[1]
        state = 'hash-pinned' if isinstance(tag, dict) and 'blockHash' in tag else \
            'latest' if tag == 'latest' else 'other'
        return (id(provider), sha256(wire.encode()).hexdigest(), state, shared)

    def response(self, identity, response):
        error = response.get('error')
        if not isinstance(error, dict):
            self.outcomes['result-envelope' if 'result' in response else 'malformed-envelope'] += 1
            return
        known = preview_error(error)
        kind = known.code if known is not None else rpc_failure(error).code
        self.outcomes[kind] += 1
        # Full error envelope equality, including code/data/message, rather
        # than assuming equal categories or selectors prove the same failure.
        error_digest = sha256(json.dumps(error, sort_keys=True).encode()).hexdigest()
        key = (*identity, error_digest)
        if key not in self.failures:
            if len(self.failures) >= self.max_entries:
                self.untracked += 1
                return
            provider, wire_digest, state, shared = identity
            self.failures[key] = {'wireDigest': wire_digest, 'errorDigest': error_digest,
                'providerContextDigest': sha256(str(provider).encode()).hexdigest()[:16],
                'stateTag': state, 'sharingEnabled': shared, 'kind': kind, 'occurrences': 0}
        self.failures[key]['occurrences'] += 1

    def exception(self, error):
        # Exceptions and cancellations are counted but never fingerprinted or
        # retained with their traceback/provider text.
        kind = 'cancelled' if isinstance(error, asyncio.CancelledError) else public_quote_error(error)['code']
        self.outcomes[kind] += 1

    def snapshot(self):
        repeated = [row for row in self.failures.values() if row['occurrences'] > 1]
        return {'providerDispatches': self.started, 'outcomes': dict(sorted(self.outcomes.items())),
            'trackedFailurePairs': len(self.failures),
            'trackedRepeatedFailures': sum(row['occurrences']-1 for row in repeated),
            'untrackedFailureObservations': self.untracked,
            'repeatedFailureRows': [dict(row) for row in sorted(repeated,
                key=lambda row: (-row['occurrences'], row['wireDigest'], row['errorDigest']))[:16]],
            'omittedRepeatedFailureRows': max(0, len(repeated)-16)}


def observe(action):
    """Optional evidence cannot change a result, error, or cancellation."""
    try:
        return action()
    except Exception:
        return None

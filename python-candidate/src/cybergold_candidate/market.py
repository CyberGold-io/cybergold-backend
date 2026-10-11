"""Source-only Python port of the current market provider/resolution contract.

No HTTP service, production scheduler, schema or shared-cache policy is changed.
A future HTTPX adapter supplies fetch_json; fixtures supply it locally today.
"""
import asyncio
import calendar
import math
import re
import json
import logging
import httpx
from collections.abc import Awaitable, Callable
from typing import Any

from .alias_dates import date_milliseconds

GOLD_URL = 'https://data-api.binance.vision/api/v3/ticker/price?symbol=PAXGUSDT'
FX_URL = 'https://api.frankfurter.app/latest?from=USD&to=EUR,CHF,RUB'
FALLBACK_RATES = {'USD': 1, 'EUR': 0.92, 'CHF': 0.89, 'RUB': 91.5}
FetchJson = Callable[[str], Awaitable[tuple[int, Any]]]


class MarketResolution(dict):
    """The existing resolution with a nonsecret, out-of-band diagnostic."""
    def __init__(self, payload, failure_code):
        super().__init__(payload=payload, isFresh=False)
        self.failure_code = failure_code


def exact(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def positive(value: Any, maximum: int) -> bool:
    # Python bool is an int subclass; JavaScript's number contract excludes it.
    return type(value) in (int, float) and 0 < value <= maximum and math.isfinite(value)


def iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z', value, flags=re.ASCII)
    if not match:
        return False
    year, month, day, hour, minute, second, _ = map(int, match.groups())
    # Proleptic Gregorian year 0000 is accepted by Date.toISOString(), although
    # datetime cannot represent it. Match the Node contract rather than narrow it.
    return (1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]
            and hour < 24 and minute < 60 and second < 60)


def parse_gold_provider(value: Any):
    if not exact(value, ('symbol', 'price')) or value['symbol'] != 'PAXGUSDT':
        return None
    price = value['price']
    if isinstance(price, str):
        if not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', price, flags=re.ASCII):
            return None
        price = float(price)
    return price if positive(price, 1_000_000_000) else None


def parse_fx_provider(value: Any):
    if (not exact(value, ('amount', 'base', 'date', 'rates'))
            or type(value['amount']) not in (int, float) or value['amount'] != 1
            or value['base'] != 'USD' or not isinstance(value['date'], str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['date'], flags=re.ASCII)
            or not exact(value['rates'], ('EUR', 'CHF', 'RUB'))):
        return None
    rates = value['rates']
    return rates.copy() if all(positive(rate, 1_000_000) for rate in rates.values()) else None


def parse_gold_payload(value: Any):
    if (exact(value, ('price', 'fetchedAt', 'stale'))
            and positive(value['price'], 1_000_000_000)
            and iso_timestamp(value['fetchedAt']) and type(value['stale']) is bool):
        return value.copy()
    return None


def parse_fx_payload(value: Any):
    if (not exact(value, ('base', 'rates', 'fetchedAt', 'stale')) or value['base'] != 'USD'
            or not exact(value['rates'], ('USD', 'EUR', 'CHF', 'RUB'))
            or type(value['rates']['USD']) not in (int, float) or value['rates']['USD'] != 1
            or not iso_timestamp(value['fetchedAt']) or type(value['stale']) is not bool):
        return None
    return ({**value, 'rates': value['rates'].copy()}
            if all(positive(value['rates'][key], 1_000_000) for key in ('EUR', 'CHF', 'RUB')) else None)


async def resolve_market(feed: str, last_known: dict | None, fetch_json: FetchJson,
                         now: Callable[[], str]) -> dict:
    gold = feed == 'gold'
    status = None
    try:
        status, body = await asyncio.wait_for(fetch_json(GOLD_URL if gold else FX_URL), timeout=10)
        if not 200 <= status < 300:
            raise ValueError('Provider HTTP failure')
        value = parse_gold_provider(body) if gold else parse_fx_provider(body)
        if value is None:
            raise ValueError('Invalid provider payload')
        payload = {'price': value} if gold else {'base': 'USD', 'rates': {'USD': 1, **value}}
        return {'payload': {**payload, 'fetchedAt': now(), 'stale': False}, 'isFresh': True}
    except Exception as error:
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
        failure_code = (f'provider-http-{status}' if status is not None and not 200 <= status < 300
                        else 'provider-timeout' if isinstance(error, (TimeoutError, httpx.TimeoutException))
                        else 'provider-unreachable' if isinstance(error, httpx.RequestError)
                        else 'provider-invalid-response')
        logging.getLogger('cybergold.candidate').warning(json.dumps({
            'event': 'market-supplier-failure', 'feed': feed, 'reason': failure_code}))
        # CancelledError is deliberately not swallowed: cancellation of a Python
        # task is distinct from the existing provider timeout/failure fallback.
        if last_known is not None:
            # A failed refresh preserves the acquisition age of the last success.
            # Gold remains usable for an hour, although acquisition is retried at 30 minutes.
            stale = (last_known['stale'] or
                     date_milliseconds(now()) - date_milliseconds(last_known['fetchedAt']) >= 3_600_000) if gold else True
            payload = {**last_known, 'stale': stale}
        else:
            payload = ({'price': 3320} if gold else {'base': 'USD', 'rates': FALLBACK_RATES.copy()})
            payload.update(fetchedAt=now(), stale=True)
        return MarketResolution(payload, failure_code)


def response_headers(feed: str, fresh: bool, payload=None, now=None):
    ttl = 1800 if feed == 'gold' else 300
    remaining = ttl
    if fresh and payload is not None and now is not None:
        age = (date_milliseconds(now) - date_milliseconds(payload['fetchedAt'])) / 1000
        remaining = max(0, math.floor(ttl - max(0, age)))
    return {'cache-control': f's-maxage={remaining}, stale-while-revalidate={ttl}'
            if fresh and remaining else 'no-store'}

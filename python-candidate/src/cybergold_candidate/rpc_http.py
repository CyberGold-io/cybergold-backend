"""Retained raw JSON-RPC HTTP contract; isolated candidate source only."""
import asyncio
from collections import deque
from .alias_dates import date_milliseconds
from .aliases import JS_WHITESPACE
import json
import logging
import math
import time
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse, Response

from .rpc_policy import MAX_REQUEST_BYTES, validate_payload, valid_response_payload


class RpcReadPacer:
    """The existing single-process public Sandbox budget, not a new limiter."""
    def __init__(self, now=time.time):
        self.now = now
        self.next_start = 0
        self.paused_until = 0
        self.pending = deque()
        self.timer = None

    async def wait(self, calls):
        future = asyncio.get_running_loop().create_future()
        self.pending.append((calls, future))
        try:
            self.drain()
            await future
        finally:
            if future.cancelled():
                self.pending = deque(entry for entry in self.pending if entry[1] is not future)
                self.drain()

    def pause(self, delay_seconds):
        self.paused_until = max(self.paused_until, self.now() + delay_seconds)
        self.drain()

    def drain(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        while self.pending:
            if self.pending[0][1].cancelled():
                self.pending.popleft()
                continue
            delay = max(self.next_start, self.paused_until) - self.now()
            if delay > 0:
                self.timer = asyncio.get_running_loop().call_later(min(delay, 2147483.647), self.drain)
                return
            calls, future = self.pending.popleft()
            self.next_start = self.now() + calls * 4 / 32
            future.set_result(None)

    def close(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        while self.pending:
            self.pending.popleft()[1].cancel()


def retry_delay(value, now=time.time):
    if not value or not value.strip(JS_WHITESPACE):
        return 1.0
    trimmed = value.strip(JS_WHITESPACE)
    try:
        delay = float(trimmed) if trimmed.isascii() and trimmed.isdigit() else (date_milliseconds(value) - now()*1000)/1000
        return max(1.0, delay) if math.isfinite(delay) else 1.0
    except (ValueError, OverflowError, TypeError):
        return 1.0


def count_reads(payload):
    return sum(isinstance(call, dict) and call.get('method') == 'eth_call'
               for call in (payload if isinstance(payload, list) else [payload]))


def error_response(status, code, message, payload=None, headers=None):
    def envelope(call):
        return {'jsonrpc': '2.0', 'id': call.get('id') if isinstance(call, dict) else None,
                'error': {'code': code, 'message': message}}
    body = [envelope(call) for call in payload] if isinstance(payload, list) else envelope(payload)
    return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store', **(headers or {})})


def failure(status, payload):
    return error_response(status, -32603,
                          'RPC upstream request timed out.' if status == 504 else 'RPC upstream is unavailable.', payload)


def parse_json(value):
    def invalid_constant(_value):
        raise ValueError('Non-JSON number')
    # JSON.parse uses IEEE-754 numbers, including rounded large numeric IDs.
    def integer(value):
        number = float(value)
        return int(number) if math.isfinite(number) else number
    return json.loads(value, parse_int=integer,
                      parse_constant=invalid_constant)


class RpcHttp:
    def __init__(self, client, url=None, authorization=None, timeout_seconds=15, metrics=None):
        self.client, self.url, self.authorization = client, url, authorization
        self.timeout_seconds = timeout_seconds
        self.metrics=metrics
        parsed = urlsplit(url or '')
        self.pacer = (RpcReadPacer() if parsed.scheme == 'https' and parsed.hostname == 'rpc.cybergold.io'
                      and parsed.port in (None, 443) else None)

    async def handle(self, request):
        declared = request.headers.get('content-length')
        try:
            too_large = declared is not None and math.isfinite(float(declared)) and float(declared) > MAX_REQUEST_BYTES
        except ValueError:
            too_large = False
        if too_large:
            return error_response(413, -32600, 'JSON-RPC request is too large.')
        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_REQUEST_BYTES:
                    return error_response(413, -32600, 'JSON-RPC request is too large.')
            raw_body = raw.decode('utf-8-sig')
            payload = parse_json(raw_body)
        except Exception:
            return error_response(400, -32700, 'Invalid JSON request body.')
        validation = validate_payload(payload)
        if not validation['ok']:
            return error_response(403 if validation['code'] == -32601 else 400,
                                  validation['code'], validation['message'])
        if not self.url:
            return failure(502, payload)

        async def disconnected():
            while (await request.receive())['type'] != 'http.disconnect':
                pass

        relay = asyncio.create_task(self.relay(raw_body, payload))
        caller = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((relay, caller), return_when=asyncio.FIRST_COMPLETED)
            return relay.result() if relay in done else failure(504, payload)
        finally:
            relay.cancel()
            caller.cancel()
            await asyncio.gather(relay, caller, return_exceptions=True)

    async def relay(self, raw_body, payload):
        parsed_url = urlsplit(self.url)
        if parsed_url.username is not None or parsed_url.password is not None:
            # Retained fetch() cannot send a URL containing credentials.
            return failure(502, payload)
        deadline = time.time() + self.timeout_seconds
        async def send():
            if self.pacer:
                await self.pacer.wait(count_reads(payload))
            started=time.monotonic();outcome='transport_error'
            try:
                response=await self.client.send(self.client.build_request('POST', self.url,
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                             **({'Authorization': self.authorization} if self.authorization else {})},
                    content=raw_body.encode(), timeout=None), stream=True, follow_redirects=False)
                outcome=str(response.status_code)
                return response
            finally:
                if self.metrics:
                    from .telemetry import observe
                    observe(lambda:self.metrics.rpc_attempts.labels(outcome).inc())
                    observe(lambda:self.metrics.rpc_duration.observe(time.monotonic()-started))

        response = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await send()
                if response.status_code == 429 and self.pacer:
                    delay = retry_delay(response.headers.get('retry-after'))
                    self.pacer.pause(delay)
                    if time.time() + delay < deadline:
                        await response.aclose()
                        response = await send()
                if response.status_code == 429:
                    delay = retry_delay(response.headers.get('retry-after'))
                    if self.pacer:
                        self.pacer.pause(delay)
                    return error_response(429, -32005, 'RPC rate limit reached. Please retry shortly.', payload,
                                          {'Retry-After': str(math.ceil(delay))})
                if not 200 <= response.status_code < 300:
                    return failure(502, payload)
                body = (await response.aread()).decode('utf-8-sig', errors='replace')
                try:
                    parsed = parse_json(body)
                except (ValueError, OverflowError):
                    return failure(502, payload)
                if not valid_response_payload(parsed):
                    return failure(502, payload)
                return Response(body, status_code=response.status_code,
                                headers={'Cache-Control': 'no-store', 'Content-Type': 'application/json'})
        except TimeoutError:
            return failure(504, payload)
        except Exception:
            # Never include URLs, credentials or supplier response bodies.
            logging.getLogger('cybergold.candidate').error('RPC upstream connection failed')
            return failure(502, payload)
        finally:
            if response:
                await response.aclose()

    def close(self):
        if self.pacer:
            self.pacer.close()

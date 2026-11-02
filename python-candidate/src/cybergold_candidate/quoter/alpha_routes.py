"""Full AlphaRouter nomination with canonical Python SDK quote callbacks.

The child owns topology selection and percentage/split optimization. It has no
RPC transport or authority over observed prices, economic ranking or execution.
"""
import asyncio
from copy import deepcopy
import json
import time

from ..recovery_rpc import SnapshotChanged
from ..route_work_slots import engine_work
from .bootstrap import ProviderUnavailable


class AlphaRouteError(RuntimeError):
    """An ordinary isolated AlphaRouter supplier/protocol failure."""


class AlphaRoutes:
    name = 'uniswap-alpharouter'
    catalog_dependent = True

    def __init__(self, engine, command=None):
        self.engine = engine
        self.command = command or ['node', 'src/uniswap-sdk/alpha-worker.ts']
        self.process = None
        self.lock = asyncio.Lock()
        self.sequence = 0
        self.closed = False
        self.quote_callbacks = self.quote_callback_failures = 0
        self.quote_callback_ms = 0.0

    @property
    def diagnostics(self):
        return {'workerQueries': self.sequence, 'quoteCallbacks': self.quote_callbacks,
                'quoteCallbackFailures': self.quote_callback_failures,
                'quoteCallbackMs': round(self.quote_callback_ms, 3)}

    async def _stop(self, process=None):
        process = self.process if process is None else process
        if process is self.process:
            self.process = None
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def close(self):
        self.closed = True
        await self._stop()

    async def discover(self, source, target, amount, block):
        candidates = []
        async for batch in self.discover_batches(source, target, amount, block):
            candidates.extend(batch)
        return candidates

    async def discover_batches(self, source, target, amount, block):
        async with self.lock:
            if self.closed:
                raise ProviderUnavailable('AlphaRouter session is closed')
            if self.process is None or self.process.returncode is not None:
                starting = asyncio.create_task(asyncio.create_subprocess_exec(*self.command,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=4*1024*1024))
                try:
                    self.process = await asyncio.shield(starting)
                except asyncio.CancelledError:
                    try:
                        process = await starting
                        await self._stop(process)
                    except BaseException:
                        pass
                    raise
            process = self.process
            self.sequence += 1
            identity = str(self.sequence)
            # These are topology references only. Supplied observations, ticks,
            # amounts and display scale never become a child quote oracle.
            fields = ('id', 'protocol', 'token0', 'token1', 'feePips', 'lpFee',
                      'tickSpacing', 'hooks', 'poolManager', 'address')
            pools = [{key: deepcopy(value) for key, value in pool.items() if key in fields}
                     for pool in list(self.engine.registry.inventory.values())]
            outgoing = {'id': identity, 'chainId': int(self.engine.registry.chain),
                        'blockNumber': int(block['number']), 'source': source,
                        'target': target, 'amount': str(amount), 'pools': pools}
            canonical = {}
            terminal_error = False
            try:
                await self._write(process, outgoing)
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        raise AlphaRouteError('AlphaRouter worker exited')
                    response = json.loads(line)
                    if response.get('id') != identity:
                        raise AlphaRouteError('AlphaRouter response differs from request')
                    if response.get('operation') == 'quote':
                        self.quote_callbacks += 1
                        started = time.perf_counter()
                        try:
                            result = await self._quote(response, block, canonical)
                            self.quote_callback_failures += result.get('quote') is None
                        finally:
                            self.quote_callback_ms += (time.perf_counter() - started) * 1000
                        await self._write(process, {'id': identity, 'operation': 'quoteResult',
                            'quoteId': response['quoteId'], 'result': result})
                    elif response.get('operation') == 'candidates':
                        yield response['candidates']
                    elif 'candidates' in response:
                        yield response['candidates']
                        return
                    elif 'error' in response:
                        # A matched terminal error retires this request in the
                        # worker. Its healthy calculation process is reusable.
                        terminal_error = True
                        raise AlphaRouteError('AlphaRouter candidate discovery unavailable')
                    else:
                        # Do not expose arbitrary child text, URLs or inputs.
                        raise AlphaRouteError('AlphaRouter candidate discovery unavailable')
            except BaseException:
                # Cancellation, disproof and broken framing/transport still
                # retire the child and all calculation work it owns.
                if not terminal_error:
                    await self._stop(process)
                raise

    async def _quote(self, request, block, canonical):
        amount, mode = int(request['amount']), request['mode']
        branches = [{'amountIn': row['amountIn'],
                     'hops': [hop for hop in row['hops'] if 'pool' in hop]}
                    for row in request['branches']]
        try:
            if all(not row['hops'] for row in branches):
                return {'quote': str(amount)}
            async with engine_work(self.engine.semaphore):
                value = await self.engine.quote_sdk_branches(branches, mode, amount, block,
                    candidate={}, canonical=canonical)
            quote = (str(value['amountOut' if mode == 'exactIn' else 'amountIn'])
                     if value['fullyFilled'] and value['settled'] else None)
            return {'quote': quote}
        except SnapshotChanged:
            raise
        except Exception:
            # One failed route/percentage leaves other AlphaRouter candidates
            # and every ordinary custom candidate available. SearchStopped and
            # cancellation are BaseExceptions and retain their owner effects.
            return {'quote': None}

    @staticmethod
    async def _write(process, value):
        process.stdin.write((json.dumps(value, separators=(',', ':'))+'\n').encode())
        await process.stdin.drain()

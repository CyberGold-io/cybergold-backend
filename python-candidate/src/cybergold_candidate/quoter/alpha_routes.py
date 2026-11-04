"""Engine-owned calculation children; requests own their framed calculations.

Each calculation owns its quote callbacks/private candidate banks. One reader
routes replies by request identity, so raw finder hints need not wait for an
older calculation's slow SDK callback. Children have no chain RPC transport.
"""
import asyncio
from copy import deepcopy
from contextvars import copy_context
import json
import time

from ..recovery_rpc import SnapshotChanged
from ..route_work_slots import engine_work
from ..search_observations import current_search_observations
from .bootstrap import ProviderUnavailable
from .cooperative import QUANTUM


class AlphaRouteError(RuntimeError):
    """An ordinary isolated calculation supplier/protocol failure."""


class CalculationSession:
    """One producer's queries and diagnostics on an engine-owned driver."""
    def __init__(self, driver):
        self.driver = driver
        self.name, self.catalog_dependent = driver.name, driver.catalog_dependent
        self.streams = {}
        self.counts = {'workerQueries': 0, 'quoteCallbacks': 0,
                       'quoteCallbackFailures': 0, 'quoteCallbackMs': 0.0}

    @property
    def diagnostics(self):
        return {**self.counts, 'quoteCallbackMs': round(self.counts['quoteCallbackMs'], 3)}

    async def discover(self, source, target, amount, block):
        candidates = []
        async for batch in self.discover_batches(source, target, amount, block):
            candidates.extend(batch)
        return candidates

    async def discover_batches(self, source, target, amount, block):
        stream = self.driver.discover_batches(source, target, amount, block, counts=self.counts)
        self.streams[stream] = asyncio.current_task()
        try:
            async for batch in stream:
                yield batch
        finally:
            await stream.aclose()
            self.streams.pop(stream, None)

    async def close(self):
        # Bootstrap normally drains its feed tasks first. Also own direct
        # subscribers without stopping calculations belonging to another owner.
        tasks = {task for task in self.streams.values() if task is not asyncio.current_task()}
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(stream.aclose() for stream in tuple(self.streams)),
                             return_exceptions=True)
        self.streams.clear()


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
        self.requests = {}
        self.reader = None
        self.reader_process = None
        self.retired = set()

    @property
    def diagnostics(self):
        return {'workerQueries': self.sequence, 'quoteCallbacks': self.quote_callbacks,
                'quoteCallbackFailures': self.quote_callback_failures,
                'quoteCallbackMs': round(self.quote_callback_ms, 3)}

    async def _stop(self, process=None, error=None):
        process = self.process if process is None else process
        if process is self.process:
            self.process = None
            self.retired.clear()
        current = asyncio.current_task()
        reader = self.reader if self.reader_process is process else None
        if reader is not None and reader is not current:
            reader.cancel()
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        if reader is not None and reader is not current:
            await asyncio.gather(reader, return_exceptions=True)
        if reader is not None and self.reader is reader:
            self.reader = None
            self.reader_process = None
        entries = [entry for entry in tuple(self.requests.values()) if entry['process'] is process]
        callbacks = [task for entry in entries for task in tuple(entry['callbacks'])]
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)
        for entry in entries:
            entry['queue'].put_nowait(error or AlphaRouteError('Calculation worker stopped'))

    async def close(self):
        self.closed = True
        await self._stop()

    def session(self):
        return CalculationSession(self)

    async def _start(self):
        # This lock owns only construction and writes, never a calculation.
        if self.closed:
            raise ProviderUnavailable('Calculation session is closed')
        if self.process is None or self.process.returncode is not None:
            starting = asyncio.create_task(asyncio.create_subprocess_exec(*self.command,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4*1024*1024))
            try:
                self.process = await asyncio.shield(starting)
            except asyncio.CancelledError:
                try:
                    await self._stop(await starting)
                except BaseException:
                    pass
                raise
            self.retired.clear()
            self.reader_process = self.process
            self.reader = asyncio.create_task(self._read(self.process))
        return self.process

    async def _read(self, process):
        frames = 0
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise AlphaRouteError('Calculation worker exited')
                frames += 1
                if frames == QUANTUM:
                    frames = 0
                    # A buffered stdout read can complete inline indefinitely.
                    # Let callbacks and unrelated HTTP work consume their turn.
                    await asyncio.sleep(0)
                response = json.loads(line)
                if response.get('id') in self.retired:
                    if response.get('operation') == 'cancelled':
                        self.retired.discard(response['id'])
                    continue  # Late frames from an explicitly cancelled calculation.
                entry = self.requests.get(response.get('id'))
                if entry is None or entry['process'] is not process:
                    raise AlphaRouteError('Calculation response differs from request')
                if response.get('operation') == 'quote':
                    task = asyncio.create_task(self._answer(response, entry),
                                               context=entry['context'].copy())
                    entry['callbacks'].add(task)
                    task.add_done_callback(entry['callbacks'].discard)
                elif response.get('operation') == 'candidates':
                    entry['queue'].put_nowait(response)
                elif 'candidates' in response or 'error' in response:
                    entry['terminal'] = True
                    entry['queue'].put_nowait(response)
                else:
                    raise AlphaRouteError('Calculation response is unavailable')
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._stop(process, error)

    async def _answer(self, response, entry):
        self.quote_callbacks += 1
        counts = entry['counts']
        if counts is not None:
            counts['quoteCallbacks'] += 1
        started = time.perf_counter()
        try:
            result = await self._quote(response, entry['block'], entry['canonical'], (self, response['id']))
            self.quote_callback_failures += result.get('quote') is None
            if counts is not None:
                counts['quoteCallbackFailures'] += result.get('quote') is None
            async with self.lock:
                if not entry['terminal'] and self.requests.get(response['id']) is entry:
                    await self._write(entry['process'], {'id': response['id'], 'operation': 'quoteResult',
                        'quoteId': response['quoteId'], 'result': result})
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            entry['queue'].put_nowait(error)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.quote_callback_ms += elapsed
            if counts is not None:
                counts['quoteCallbackMs'] += elapsed

    async def discover(self, source, target, amount, block):
        candidates = []
        async for batch in self.discover_batches(source, target, amount, block):
            candidates.extend(batch)
        return candidates

    async def discover_batches(self, source, target, amount, block, *, counts=None):
        entry, identity = None, None
        try:
            async with self.lock:
                process = await self._start()
                self.sequence += 1
                if counts is not None:
                    counts['workerQueries'] += 1
                identity = str(self.sequence)
                entry = {'process': process, 'queue': asyncio.Queue(), 'callbacks': set(),
                         'canonical': {}, 'block': block, 'terminal': False,
                         'context': copy_context(), 'counts': counts}
                self.requests[identity] = entry
                fields = ('id', 'protocol', 'token0', 'token1', 'feePips', 'lpFee',
                          'tickSpacing', 'hooks', 'poolManager', 'address')
                pools = [{key: deepcopy(value) for key, value in pool.items() if key in fields}
                         for pool in list(self.engine.registry.inventory.values())]
                await self._write(process, {'id': identity, 'chainId': int(self.engine.registry.chain),
                    'blockNumber': int(block['number']), 'source': source, 'target': target,
                    'amount': str(amount), 'pools': pools})
            while True:
                response = await entry['queue'].get()
                if isinstance(response, BaseException):
                    raise response
                if 'error' in response:
                    raise AlphaRouteError('Calculation candidate discovery unavailable')
                yield response['candidates']
                if response.get('operation') != 'candidates':
                    return
        finally:
            if entry is not None:
                self.requests.pop(identity, None)
                self.retired.add(identity)
                callbacks = tuple(entry['callbacks'])
                for task in callbacks:
                    task.cancel()
                await asyncio.gather(*callbacks, return_exceptions=True)
                if self.process is entry['process']:
                    if entry['terminal'] or self.requests:
                        # Callback writes have drained before this ordered
                        # retirement. Its acknowledgement releases both sides'
                        # query bookkeeping while sibling calculations continue.
                        try:
                            async with self.lock:
                                await self._write(entry['process'], {'id': identity, 'operation': 'cancel'})
                        except Exception as error:
                            # A broken shared transport retires its subscribers;
                            # it does not replace the closing query's own outcome.
                            await self._stop(entry['process'], error)
                    else:
                        await self._stop(entry['process'])

    async def _quote(self, request, block, canonical, scope=None):
        amount, mode = int(request['amount']), request['mode']
        branches = [{'amountIn': row['amountIn'],
                     'hops': [hop for hop in row['hops'] if 'pool' in hop]}
                    for row in request['branches']]
        if all(not row['hops'] for row in branches):
            return {'quote': str(amount)}
        async def calculate():
            async with engine_work(self.engine.semaphore):
                value = await self.engine.quote_sdk_branches(branches, mode, amount, block,
                    candidate={}, canonical=canonical)
            quote = (str(value['amountOut' if mode == 'exactIn' else 'amountIn'])
                     if value['fullyFilled'] and value['settled'] else None)
            return {'quote': quote}
        try:
            shared = current_search_observations()
            if shared is not None and scope is not None:
                # The framed calculation owns one immutable baseline. Preserve
                # every percentage answer while sharing identical rounded work.
                key = ('route-tool-callback', scope, mode, amount,
                       json.dumps(branches, sort_keys=True, separators=(',', ':')))
                return await shared.read(key, calculate)
            return await calculate()
        except SnapshotChanged:
            raise
        except Exception:
            return {'quote': None}

    @staticmethod
    async def _write(process, value):
        process.stdin.write((json.dumps(value, separators=(',', ':'))+'\n').encode())
        await process.stdin.drain()

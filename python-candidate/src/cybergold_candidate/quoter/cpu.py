"""Persistent pure-CPU processes; the API retains policy, RPC and mutable state."""
import asyncio
import base64
from contextlib import aclosing
from contextvars import Context
import io
import json
import logging
import pickle
import sys
import time
from ..quote_flow import stage, worker_stage

from .cooperative import QUANTUM


class _Worker:
    def __init__(self):
        self.process = None

    async def start(self):
        if self.process is None or self.process.returncode is not None:
            try:
                with stage('cpu.startup'):
                    launch = asyncio.create_task(asyncio.create_subprocess_exec(
                        sys.executable, '-m', 'cybergold_candidate.quoter.cpu_worker',
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL))
                    try:
                        self.process = await asyncio.shield(launch)
                    except BaseException:
                        # Creation can finish after cancellation. Recover its
                        # handle before the outer finalizer terminates/reaps it.
                        result, = await asyncio.gather(launch, return_exceptions=True)
                        if not isinstance(result, BaseException):
                            self.process = result
                        raise
                    if not await self.process.stdout.readline():
                        raise RuntimeError('Topology worker exited during startup')
            except BaseException:
                await self.close()
                raise

    async def paths(self, pools, source, target, weth, max_hops):
        try:
            await self.start()
            payload = {'pools': pools, 'source': source, 'target': target,
                       'weth': weth, 'maxHops': max_hops}
            self.process.stdin.write((json.dumps(payload)+'\n').encode())
            await self.process.stdin.drain()
            result = []
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError('Topology worker exited during enumeration')
                packet = json.loads(line)
                if 'error' in packet:
                    raise ValueError(packet['error'])
                result.extend(packet.get('routes', ()))
                if packet.get('done'):
                    return result
                await asyncio.sleep(0)
        except BaseException:
            # This worker has one active job. Reap its computation before
            # the pool can transfer ready replacement capacity into the slot.
            await self.close()
            raise

    async def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
            await process.communicate()

    async def prepare(self, captured):
        """Private parent-generated snapshot; one job owns this pipe/memo."""
        try:
            await self.start()
            packet = {'operation': 'prepare', 'captured': base64.b64encode(captured).decode()}
            self.process.stdin.write((json.dumps(packet)+'\n').encode())
            await self.process.stdin.drain()
            buffer = io.BytesIO()
            decoder = pickle.Unpickler(buffer)
            while True:
                packet = await self.packet()
                if 'error' in packet:
                    raise ValueError(packet['error'])
                if packet.get('done'):
                    return
                buffer.seek(0)
                buffer.truncate()
                buffer.write(base64.b64decode(packet['prepared']))
                buffer.seek(0)
                yield decoder.load()
        except BaseException:
            await self.close()
            raise

    async def packet(self):
        parts = []
        while True:
            try:
                parts.append(await self.process.stdout.readuntil(b'\n'))
                break
            except asyncio.LimitOverrunError as error:
                parts.append(await self.process.stdout.readexactly(error.consumed))
        return json.loads(b''.join(parts))

    async def encode_plan(self, captured):
        try:
            await self.start()
            packet = {'operation': 'encode-plan', 'captured': base64.b64encode(captured).decode()}
            self.process.stdin.write((json.dumps(packet)+'\n').encode())
            await self.process.stdin.drain()
            with stage('plan.worker_read'):
                packet = await self.packet()
            if 'error' in packet:
                raise ValueError(packet['error'])
            failed = 'encodingError' in packet
            worker_stage('plan.worker', packet['wallMs'], packet['threadCpuMs'], failed=failed)
            if failed:
                # Only the matching internal process writes this pipe. Preserve
                # ordinary ABI exception types/arguments instead of recategorizing
                # a malformed plan as a worker transport error.
                error_type, arguments, state = pickle.loads(base64.b64decode(packet['encodingError']))
                error = error_type.__new__(error_type, *arguments)
                error.args = arguments
                error.__dict__.update(state)
                raise error
            return packet['encoded']
        except BaseException:
            await self.close()
            raise


class CpuWorkers:
    """Two independent jobs can run in parallel without the parent's GIL.

    Workers persist across requests. Each session owns its submitted tasks;
    cancellation terminates only the process executing that task, not siblings.
    An explicitly started pool owns one ready standby and background repairs;
    it still admits only the same two jobs. Unstarted script consumers retain
    their ordinary lazy process startup.
    """
    def __init__(self, *, name='cpu'):
        self.workers = [_Worker(), _Worker()]
        self.available = asyncio.Queue()
        for worker in self.workers:
            self.available.put_nowait(worker)
        self.jobs = set()
        self.name = name
        self._maintaining = False
        self._spare = None
        self._spare_task = None
        self._maintenance = set()

    @staticmethod
    def _alive(worker):
        return worker is not None and worker.process is not None and worker.process.returncode is None

    def _launch(self, coroutine):
        # Pool maintenance belongs to the API lifetime, not the query whose
        # cancelled job freed this slot. Do not retain its flow/budget/context.
        task = asyncio.create_task(coroutine, context=Context())
        self._maintenance.add(task)
        def finished(done):
            self._maintenance.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return task

    def _report(self, action, started, error=None):
        try:
            record = {'event': 'cpu_worker_maintenance', 'component': 'api',
                      'pool': self.name, 'action': action,
                      'wallMs': round((time.perf_counter()-started)*1000, 3)}
            if error is not None:
                record['errorType'] = type(error).__name__
            logging.getLogger('cybergold.candidate').info(json.dumps(record))
        except Exception:
            pass

    def _ensure_spare(self):
        if self._maintaining and not self._alive(self._spare) and self._spare_task is None:
            self._spare_task = self._launch(self._warm_spare())
        return self._spare_task

    async def _warm_spare(self):
        started, worker = time.perf_counter(), None
        try:
            previous, self._spare = self._spare, None
            if previous is not None:
                await previous.close()
            worker = _Worker()
            await worker.start()
            if self._maintaining:
                self._spare, worker = worker, None
                self._report('standby-ready', started)
        except Exception as error:
            # Optional spare failure does not reject startup or a query. A
            # subsequent ordinary release can try warming the standby again.
            self._report('standby-failed', started, error)
        finally:
            if worker is not None:
                await worker.close()
            self._spare_task = None

    def _adopt_spare(self, worker):
        if worker.process is None and self._alive(self._spare):
            standby, self._spare = self._spare, None
            worker.process, standby.process = standby.process, None
            self._ensure_spare()
            return True
        return False

    async def _make_ready(self, worker):
        if not self._alive(worker):
            await worker.close()
            if not self._adopt_spare(worker):
                await worker.start()

    def _release(self, worker):
        if self._maintaining and not self._alive(worker):
            if self._adopt_spare(worker):
                self.available.put_nowait(worker)
            else:
                self._launch(self._repair(worker))
        else:
            self.available.put_nowait(worker)
        self._ensure_spare()

    async def _repair(self, worker):
        started = time.perf_counter()
        try:
            await self._make_ready(worker)
            self._report('slot-ready', started)
        except Exception as error:
            await worker.close()
            self._report('slot-failed', started, error)
        finally:
            if not self._maintaining:
                await worker.close()
            self.available.put_nowait(worker)

    async def start(self):
        self._maintaining = True
        tasks = [self._launch(worker.start()) for worker in self.workers]
        self._ensure_spare()
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.close()
            raise

    def paths(self, pools, source, target, weth, max_hops):
        # Capture connectivity before scheduling or queuing. Caller dictionaries
        # can acquire new metadata while this job waits for a process.
        graph = [{key: pool[key] for key in
                  ('id', 'protocol', 'feePips', 'tickSpacing', 'hooks', 'address')
                  if key in pool} | {key: {'address': pool[key]['address']}
                                    for key in ('token0', 'token1')} for pool in pools]
        return self._paths(graph, source, target, weth, max_hops)

    def prepare(self, rows):
        # C-level capture runs before the first await. Later supplier mutation
        # cannot change a queued job. Pickle is internal parent/child framing,
        # never an accepted network payload or a persisted untrusted artifact.
        with stage('discovery.capture', kind='cpu'):
            captured = pickle.dumps(list(rows), protocol=5)
        return self._prepare(captured)

    def capture_plan(self, arguments, abi):
        with stage('plan.capture', kind='cpu'):
            return pickle.dumps((arguments, abi), protocol=5)

    async def encode_plan(self, captured):
        task = asyncio.current_task()
        self.jobs.add(task)
        worker = None
        try:
            with stage('plan.queue', kind='queue'):
                worker = await self.available.get()
            await self._make_ready(worker)
            return await worker.encode_plan(captured)
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self._release(worker)

    async def _prepare(self, captured):
        task = asyncio.current_task()
        self.jobs.add(task)
        worker = None
        try:
            worker = await self.available.get()
            await self._make_ready(worker)
            async with aclosing(worker.prepare(captured)) as chunks:
                async for chunk in chunks:
                    yield chunk
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self._release(worker)

    async def _paths(self, *args):
        task = asyncio.current_task()
        self.jobs.add(task)
        worker = None
        try:
            worker = await self.available.get()
            await self._make_ready(worker)
            return await worker.paths(*args)
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self._release(worker)

    async def close(self):
        self._maintaining = False
        jobs = tuple(self.jobs)
        for task in jobs:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        maintenance = tuple(self._maintenance)
        for task in maintenance:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*maintenance, return_exceptions=True)
        self._spare_task = None
        standby, self._spare = self._spare, None
        outcomes = await asyncio.gather(*(worker.close() for worker in self.workers),
            *([standby.close()] if standby is not None else []), return_exceptions=True)
        error = next((value for value in outcomes if isinstance(value, BaseException)), None)
        if error is not None:
            raise error


def batch_routes(routes):
    """Compact transfers use the existing cooperative item quantum."""
    for index in range(0, len(routes), QUANTUM):
        yield routes[index:index+QUANTUM]

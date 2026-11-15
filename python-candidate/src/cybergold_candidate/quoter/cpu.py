"""Persistent pure-CPU processes; the API retains policy, RPC and mutable state."""
import asyncio
import base64
from contextlib import aclosing
import io
import json
import pickle
import sys
from ..quote_flow import stage, worker_stage

from .cooperative import QUANTUM


class _Worker:
    def __init__(self):
        self.process = None

    async def start(self):
        if self.process is None or self.process.returncode is not None:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'cybergold_candidate.quoter.cpu_worker',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            if not await self.process.stdout.readline():
                raise RuntimeError('Topology worker exited during startup')

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
            # This worker has one active job. Stop that computation before
            # returning it to the pool; a later job starts a fresh process.
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
    """
    def __init__(self):
        self.workers = [_Worker(), _Worker()]
        self.available = asyncio.Queue()
        for worker in self.workers:
            self.available.put_nowait(worker)
        self.jobs = set()

    async def start(self):
        tasks = [asyncio.create_task(worker.start()) for worker in self.workers]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
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
            return await worker.encode_plan(captured)
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self.available.put_nowait(worker)

    async def _prepare(self, captured):
        task = asyncio.current_task()
        self.jobs.add(task)
        worker = None
        try:
            worker = await self.available.get()
            async with aclosing(worker.prepare(captured)) as chunks:
                async for chunk in chunks:
                    yield chunk
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self.available.put_nowait(worker)

    async def _paths(self, *args):
        task = asyncio.current_task()
        self.jobs.add(task)
        worker = None
        try:
            worker = await self.available.get()
            return await worker.paths(*args)
        finally:
            self.jobs.discard(task)
            if worker is not None:
                self.available.put_nowait(worker)

    async def close(self):
        jobs = tuple(self.jobs)
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        await asyncio.gather(*(worker.close() for worker in self.workers))


def batch_routes(routes):
    """Compact transfers use the existing cooperative item quantum."""
    for index in range(0, len(routes), QUANTUM):
        yield routes[index:index+QUANTUM]

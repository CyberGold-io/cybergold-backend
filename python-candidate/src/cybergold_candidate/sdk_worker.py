"""Managed lossless JSONL bridge. Only Python acquires chain observations."""
import asyncio
import json
import os
import shlex
from copy import deepcopy
from .rpc_diagnostics import quote_sdk_request, freeze_quote_work


class SdkWorkerError(RuntimeError):
    pass


class MissingPoolState(SdkWorkerError):
    def __init__(self, requests):
        super().__init__('SDK quote needs additional observed pool state')
        self.requests = requests


class SdkWorker:
    def __init__(self, command=None, timeout=15):
        self.command = command or shlex.split(os.environ.get('CYBERGOLD_UNISWAP_SDK_COMMAND',
            'node src/uniswap-sdk/worker.ts'))
        self.timeout = timeout
        self.process = None
        self.lock = asyncio.Lock()
        self.sequence = 0

    async def request(self, payload, on_state=None):
        payload = deepcopy(payload)
        process = request_id = None
        terminal, coverage = False, None
        try:
            while True:
                # Each start/resume is one serialized exchange. Required chain
                # observations run outside this lock and its diagnostics scope.
                with quote_sdk_request() as acquired:
                    async with self.lock:
                        acquired()
                        if process is not None and (self.process is not process or process.returncode is not None):
                            raise SdkWorkerError('SDK continuation worker exited')
                        if process is None:
                            if self.process is None or self.process.returncode is not None:
                                self.process = await asyncio.create_subprocess_exec(*self.command,
                                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.DEVNULL, limit=4*1024*1024)
                            process = self.process
                            self.sequence += 1
                            request_id = str(self.sequence)
                            outgoing = {**payload, 'id': request_id}
                            if on_state is not None:
                                outgoing['continueState'] = True
                        else:
                            outgoing = {'id': request_id, 'operation': 'resume', 'coverage': coverage}
                        try:
                            async with asyncio.timeout(self.timeout):
                                process.stdin.write((json.dumps(outgoing, separators=(',', ':'))+'\n').encode())
                                await process.stdin.drain()
                                line = await process.stdout.readline()
                                if not line:
                                    raise SdkWorkerError('SDK worker exited')
                                response = json.loads(line)
                                if response.get('id') != request_id:
                                    raise SdkWorkerError('SDK worker response does not match request')
                                if not (response.get('stateRequest') or response.get('missingState') or response.get('error')):
                                    value = response['result']
                        except BaseException as error:
                            if isinstance(error, asyncio.CancelledError):
                                freeze_quote_work(error)
                            if on_state is not None and isinstance(error, (asyncio.CancelledError, TimeoutError)):
                                await self._retire(process, request_id)
                                terminal = True
                            else:
                                await self._stop()
                            raise
                if response.get('stateRequest'):
                    if on_state is None:
                        raise MissingPoolState(response['stateRequest'])
                    observed = await on_state(response['stateRequest'])
                    coverage = []
                    for pool in observed:
                        original = next(row for row in payload['pools'] if row['id'] == pool['id'])
                        words = {int(row['wordPosition']): row for row in original.get('bitmapWords', [])}
                        ticks = {int(row['index']): row for row in original.get('ticks', [])}
                        added_words = [row for row in pool['bitmapWords'] if int(row['wordPosition']) not in words]
                        added_ticks = [row for row in pool['ticks'] if int(row['index']) not in ticks]
                        words.update({int(row['wordPosition']): row for row in added_words})
                        ticks.update({int(row['index']): row for row in added_ticks})
                        original['bitmapWords'], original['ticks'] = list(words.values()), list(ticks.values())
                        coverage.append({'id': pool['id'], 'bitmapWords': added_words, 'ticks': added_ticks})
                    continue
                terminal = True
                if response.get('missingState'):
                    raise MissingPoolState(response['missingState'])
                if response.get('error'):
                    raise SdkWorkerError('SDK quote unavailable')
                return value
        finally:
            if not terminal and process is not None and self.process is process and process.returncode is None:
                # A complete synchronous JSONL write cannot interleave bytes.
                # One-way cancellation must not wait on another client's lock.
                try:
                    process.stdin.write((json.dumps({'id': request_id, 'operation': 'cancel'})+'\n').encode())
                except (BrokenPipeError, ConnectionError, RuntimeError):
                    pass  # Cleanup never replaces the owning operation's error.

    async def _retire(self, process, request_id):
        # Reuse the existing child cleanup allowance, including kill fallback.
        # Retiring this stack must preserve other producers paused in the child.
        deadline = asyncio.get_running_loop().time()+2
        try:
            async with asyncio.timeout_at(deadline):
                process.stdin.write((json.dumps({'id': request_id, 'operation': 'cancel',
                    'acknowledge': True})+'\n').encode())
                await process.stdin.drain()
                while True:
                    response = json.loads(await process.stdout.readline())
                    if response.get('id') != request_id:
                        raise SdkWorkerError('SDK worker response does not match request')
                    # A state/result frame can already be queued when cancelled.
                    if response.get('cancelled') is True:
                        return
        except BaseException:
            try:
                await self._stop(grace=max(0, deadline-asyncio.get_running_loop().time()))
            except BaseException:
                pass  # Keep the original cancellation/deadline error.

    async def _stop(self, grace=2):
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), grace)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def close(self):
        async with self.lock:
            await self._stop()

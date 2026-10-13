"""Managed lossless JSONL bridge. Only Python acquires chain observations."""
import asyncio
import json
import os
import shlex
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

    async def request(self, payload):
        # Serialized exchange bounds worker state and lets cancellation terminate
        # a blocked worker without cancelling a different client's exchange.
        with quote_sdk_request() as acquired:
            async with self.lock:
                acquired()
                if self.process is None or self.process.returncode is not None:
                    self.process = await asyncio.create_subprocess_exec(*self.command,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL, limit=4*1024*1024)
                self.sequence += 1
                request_id = str(self.sequence)
                try:
                    async with asyncio.timeout(self.timeout):
                        self.process.stdin.write((json.dumps({**payload, 'id': request_id}, separators=(',', ':'))+'\n').encode())
                        await self.process.stdin.drain()
                        line = await self.process.stdout.readline()
                        if not line:
                            raise SdkWorkerError('SDK worker exited')
                        response = json.loads(line)
                        if response.get('id') != request_id:
                            raise SdkWorkerError('SDK worker response does not match request')
                        if response.get('missingState'):
                            raise MissingPoolState(response['missingState'])
                        if response.get('error'):
                            raise SdkWorkerError('SDK quote unavailable')
                        return response['result']
                except (asyncio.CancelledError, TimeoutError, BrokenPipeError, ValueError) as error:
                    if isinstance(error, asyncio.CancelledError):
                        freeze_quote_work(error)
                    await self._stop()
                    raise

    async def _stop(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def close(self):
        async with self.lock:
            await self._stop()

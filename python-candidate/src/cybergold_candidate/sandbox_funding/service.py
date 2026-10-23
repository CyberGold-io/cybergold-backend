"""Serialized native funding with the existing generation ledger and cooldown."""
import asyncio
from contextlib import asynccontextmanager
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import time

from web3 import Web3

from .errors import FundingError
from .policy import CHAIN_ID, ETH_WEI, TOKENS, allocation
from .rpc import AnvilRpc
from .state import FundingRequest, FundingState, StateError

ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
UUID4 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


class SandboxFunding:
    adapter_mode = True  # Preserve request-ID and trusted requester-IP HTTP inputs.

    def __init__(self, *, client=None, enabled=False, rpc_url=None, rpc_authorization=None,
                 state_root=None, generation_file=None, rpc=None, now=None):
        self.enabled = enabled
        self.rpc_url, self.rpc_authorization = rpc_url, rpc_authorization
        self.state_root = Path(state_root) if state_root else None
        self.generation_file = Path(generation_file) if generation_file else None
        self.now = now or time.time
        self.rpc = rpc
        self.client = client
        self.transport = None
        self.worker = asyncio.Lock()

    async def close(self):
        if self.transport is not None:
            await self.transport.close()

    def _request(self, address, request_id, requester_ip):
        if not self.enabled:
            raise FundingError('DISABLED')
        if not isinstance(address, str) or not ADDRESS.fullmatch(address) or int(address[2:], 16) == 0:
            raise FundingError('INVALID_ADDRESS')
        if not isinstance(request_id, str) or not UUID4.fullmatch(request_id):
            raise FundingError('INVALID_REQUEST_ID')
        try:
            if not isinstance(requester_ip, str) or '%' in requester_ip:
                raise ValueError('invalid requester IP')
            parsed_ip = ipaddress.ip_address(requester_ip)
        except ValueError:
            raise FundingError('INVALID_REQUESTER_IP') from None
        mapped = getattr(parsed_ip, 'ipv4_mapped', None)
        return FundingRequest(address, address.lower(), request_id, (mapped or parsed_ip).compressed)

    def _generation(self):
        value = self.generation_file.read_text(encoding='ascii').strip()
        if UUID4.fullmatch(value) is None:
            raise StateError('Anvil generation must be a lowercase UUID v4')
        return value

    async def _call(self, method, params):
        if self.rpc is not None:
            return await self.rpc(method, params)
        if self.transport is None:
            self.transport = AnvilRpc(self.client, self.rpc_url, self.rpc_authorization)
        return await self.transport(method, params)

    @asynccontextmanager
    async def _operation(self):
        # Reuse the old service lock to serialize all API processes and the old
        # service during retirement. A waiter never blocks the API event loop.
        self.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.state_root / 'service.lock', os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            while not acquired:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    await asyncio.sleep(.05)
            yield
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    async def fund(self, address, request_id, requester_ip):
        request = self._request(address, request_id, requester_ip)
        if (self.rpc is None and not self.rpc_url) or self.state_root is None or self.generation_file is None:
            raise FundingError('CONFIGURATION_ERROR')
        try:
            async with asyncio.timeout(20), self.worker, self._operation():
                generation = self._generation()
                directory = self.state_root / 'generations' / generation
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                with FundingState(directory / 'faucet.sqlite3', self.now) as state:
                    # Exclusive operation ownership proves no live request owns
                    # a retained reservation, including one from the old service.
                    state.recover_uncertain()
                    return await self._fund(request, generation, state)
        except FundingError:
            raise
        except TimeoutError:
            raise FundingError('TIMEOUT', diagnostics={'stage': 'sandbox-funding', 'failureType': 'backend-deadline'}) from None
        except (OSError, StateError):
            raise FundingError('CONFIGURATION_ERROR', diagnostics={'stage': 'sandbox-funding-state', 'failureType': 'state-error'}) from None

    async def _checkpoint(self):
        block = await self._call('eth_getBlockByNumber', ['latest', False])
        number, block_hash = int(block['number'], 16), block['hash'].lower()
        if number <= 0 or re.fullmatch(r'0x[0-9a-f]{64}', block_hash) is None:
            raise ValueError('Sandbox chain checkpoint is invalid')
        return number, block_hash

    async def _verify(self, generation, checkpoint):
        if self._generation() != generation:
            raise ValueError('Anvil generation changed')
        if int(await self._call('eth_chainId', []), 16) != CHAIN_ID:
            raise ValueError('Sandbox chain ID mismatch')
        if 'anvil' not in (await self._call('web3_clientVersion', [])).lower():
            raise ValueError('Sandbox RPC is not Anvil')
        if checkpoint is not None:
            block = await self._call('eth_getBlockByNumber', [hex(checkpoint[0]), False])
            if block['hash'].lower() != checkpoint[1]:
                raise ValueError('Sandbox chain checkpoint mismatch')
        else:
            info = await self._call('anvil_nodeInfo', [])
            fork_block = info['forkConfig']['forkBlockNumber']
            if (int(fork_block, 0) if isinstance(fork_block, str) else int(fork_block)) <= 0:
                raise ValueError('Anvil fork block is invalid')

    async def _balances(self, address):
        native = int(await self._call('eth_getBalance', [address, 'latest']), 16)
        balances = []
        for token in TOKENS:
            data = '0x70a08231' + address[2:].lower().zfill(64)
            value = await self._call('eth_call', [{'to': token.address, 'data': data}, 'latest'])
            if not isinstance(value, str) or re.fullmatch(r'0x[0-9a-fA-F]{64}', value) is None:
                raise ValueError(f'{token.symbol} balance response is invalid')
            balances.append(int(value, 16))
        return native, balances

    @staticmethod
    def _existing(reservation):
        if reservation.kind == 'conflict':
            raise FundingError('REQUEST_CONFLICT', replace=True)
        if reservation.status == 'completed' and reservation.result is not None:
            return reservation.result
        code = reservation.error_code or 'REQUEST_UNCERTAIN'
        if code == 'REQUEST_ID_CONFLICT':
            code = 'REQUEST_CONFLICT'
        raise FundingError(code, replace=code in ('REQUEST_UNCERTAIN', 'FUNDING_FAILED', 'REQUEST_CONFLICT'))

    async def _fund(self, request, generation, state):
        checkpoint = state.chain_checkpoint()
        try:
            await self._verify(generation, checkpoint)
            if checkpoint is None:
                checkpoint = await self._checkpoint()
                state.set_chain_checkpoint(checkpoint)
        except Exception:
            raise FundingError('CHAIN_UNAVAILABLE', diagnostics={'stage': 'sandbox-funding-chain', 'failureType': 'chain-error'}) from None
        existing = state.lookup(request)
        if existing is not None:
            return self._existing(existing)
        reserved = False
        mutation_started = False
        address = Web3.to_checksum_address(request.address)
        try:
            native, balances = await self._balances(address)
            needs_funding = native < ETH_WEI or any(value < token.amount for token, value in zip(TOKENS, balances, strict=True))
            reservation = state.reserve(request, now=self.now(), needs_top_up=needs_funding)
            if reservation.kind == 'cooldown':
                raise FundingError('RATE_LIMITED', retry=reservation.retry_after_seconds)
            if reservation.kind != 'reserved':
                return self._existing(reservation)
            reserved = True
            if native < ETH_WEI:
                mutation_started = True
                await self._call('anvil_setBalance', [address, hex(ETH_WEI)])
            for token, value in zip(TOKENS, balances, strict=True):
                if value < token.amount:
                    mutation_started = True
                    await self._call('anvil_dealERC20', [address, token.address, hex(token.amount)])
            candidate = await self._checkpoint()
            await self._verify(generation, checkpoint)
            state.set_chain_checkpoint(candidate)
            result = allocation(request.address)
            state.complete(request.request_id, result, did_transfer=mutation_started)
            return result
        except FundingError:
            raise
        except BaseException as exc:
            # A cancelled/failed write can still land in Anvil. Persist its
            # terminal uncertainty before releasing operation ownership.
            try:
                if not reserved:
                    reservation = state.reserve(request, now=self.now(), needs_top_up=False)
                    if reservation.kind != 'reserved':
                        return self._existing(reservation)
                    reserved = True
                if mutation_started:
                    state.uncertain(request.request_id)
                else:
                    state.fail(request.request_id)
            except StateError:
                # A retained reservation is recovered as uncertain next time.
                pass
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            code = 'REQUEST_UNCERTAIN' if mutation_started else 'FUNDING_FAILED'
            raise FundingError(code, replace=True,
                diagnostics={'stage': 'sandbox-funding', 'failureType': 'write-uncertain' if mutation_started else 'read-error'}) from None

"""Configured live protocol facts at one canonical hash; no database work."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from eth_utils.abi import collapse_if_tuple
from fastapi.responses import JSONResponse, Response
from web3 import Web3

from .recovery_rpc import RecoveryRpc, abi_value
from .quote_errors import public_quote_error, RpcTimeout
from .shared_reads import SharedReads, discard_pool_observation
from .trade_observation import failure as observe_failure

ABI = json.loads(Path(__file__).with_name('protocol-facts-abi.json').read_text())


class ProtocolFactsRpc(RecoveryRpc):
    def __init__(self, settings, w3=None, abi=ABI, *, pool_reads=None):
        super().__init__(settings, w3)
        self.pool_reads = pool_reads if pool_reads is not None else SharedReads()
        self.owns_pool_reads = pool_reads is None
        # Existing Ops profiles already carry this optional product address.
        # Invalid/unavailable Helpers fail only their ordinary read; no new
        # startup prerequisite is added to the retained settings contract.
        self.helpers = getattr(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS',
                               os.environ.get('NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))
        self.abi = abi
        self.contracts = {group: self.w3.eth.contract(abi=entries) for group, entries in abi.items()}

    async def block(self, _block_hash=None):
        # Reuse the accepted configured-chain relationship from recovery reads.
        if await self.w3.eth.chain_id != self.chain_id:
            raise ValueError('Configured RPC chain mismatch')
        block = await self.w3.eth.get_block('latest')
        return {'hash': Web3.to_hex(block['hash']), 'number': block['number'], 'timestamp': block['timestamp']}

    async def read(self, group, address, name, block):
        function = next(entry for entry in self.abi[group] if entry['name'] == name)
        data = self.contracts[group].encode_abi(name, args=[])
        key = (self.chain_id, block['hash'].lower(), address.lower(), data.lower())
        async def produce(_keys):
            return [await self.w3.provider.make_request('eth_call', [
                {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])]
        # Borrow the same getter identity as routes and pool observations.
        # Sandbox administrative writes can change values under one header,
        # so only overlapping Sandbox callers share an unfinished read.
        rows, _ = await self.pool_reads.many([key], produce, retain=self.chain_id == 1)
        response = rows[0]
        if 'error' in response:
            raise ValueError('Contract read failed')
        outputs = function['outputs']
        try:
            decoded = self.w3.codec.decode([collapse_if_tuple(output) for output in outputs],
                                          bytes.fromhex(response['result'][2:]))
            return abi_value(decoded[0], outputs[0])
        except Exception:
            discard_pool_observation(self, (address, data), block)
            raise

    async def close(self):
        if self.owns_pool_reads:
            await self.pool_reads.close()
        await super().close()


class ProtocolFacts:
    def __init__(self, settings, rpc=None, now=None, on_observation=None, history=None, *, pool_reads=None):
        self.settings, self.rpc = settings, rpc
        self.on_observation = on_observation
        self.history = history
        self.pool_reads = pool_reads
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self):
        epoch = self.history.epoch if self.history else None
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings, pool_reads=self.pool_reads)
        # Existing API RPC deadline/no-retry policy bounds the complete operation.
        async with asyncio.timeout(15):
            block = await self.rpc.block()
            async def read(group, address, name, convert=lambda value: value):
                if not address:
                    return {'status': 'failure', 'error': 'not-configured'}
                try:
                    return {'status': 'success', 'value': convert(await self.rpc.read(group, address, name, block))}
                except Exception:
                    return {'status': 'failure', 'error': 'contract-read-failed'}
            raw_array = lambda values: [str(value) for value in values]
            core, helpers = self.rpc.core, self.rpc.helpers
            names = ('basketAssets', 'basketTargetsPpm', 'basketGoldRefGramsFp18', 'basketCygldPerUnitFp18',
                     'cygldRefGramsFp18', 'issuanceFeePpm', 'paused')
            conversions = (list, raw_array, raw_array, raw_array, str, str, bool)
            values = await asyncio.gather(*(read('core', core, name, convert)
                                           for name, convert in zip(names, conversions, strict=True)),
                                         read('helpers', helpers, 'helperFeePpm', str),
                                         *(read('core', core, name, str) for name in (
                                             'totalSupply', 'maxTotalSupply', 'effectiveCygldSupplyCap')))
            assets = values[0]['value'] if values[0]['status'] == 'success' else []
            async def metadata(address):
                decimals, name, symbol = await asyncio.gather(read('token', address, 'decimals', int),
                                                             read('token', address, 'name', str),
                                                             read('token', address, 'symbol', str))
                return {'address': address, 'decimals': decimals, 'name': name, 'symbol': symbol}
            rows = await asyncio.gather(*(metadata(address) for address in assets))
            # A reorg cannot turn mixed successful calls into a coherent result.
            await self.rpc.assert_canonical(block)
            result = {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']),
                                'observedAt': self.now()}, 'core': core, 'helpers': helpers,
                    'basket': {'assets': values[0], 'targetsPpm': values[1], 'goldRefGramsFp18': values[2],
                               'cygldPerUnitFp18': values[3], 'metadata': rows},
                    'reference': values[4], 'fees': {'issuancePpm': values[5], 'helpersPpm': values[7]},
                    'pause': values[6],
                    'issuanceCapacity': {'totalSupply': values[8], 'maxTotalSupply': values[9],
                                         'effectiveCygldSupplyCap': values[10]}}
            if self.on_observation and (not self.history or epoch == self.history.epoch):
                self.on_observation(result)
            if self.history:
                result['basketModel'] = self.history.protocol_model()
            return result

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_protocol_facts(request, service, context='protocol-facts', unavailable='Protocol facts are temporarily unavailable.'):
    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass
    async def result():
        try:
            if service is None:
                raise ValueError('Protocol facts not configured')
            return JSONResponse(await service.get(), headers={'Cache-Control': 'no-store'})
        except Exception as error:
            failure = RpcTimeout() if isinstance(error, TimeoutError) and not isinstance(error, RpcTimeout) else error
            payload = public_quote_error(failure)
            if payload['code'] == 'quote-unavailable':
                payload = {'error': unavailable,
                           **({'diagnostics': payload['diagnostics']} if 'diagnostics' in payload else {})}
            return JSONResponse(observe_failure(request, error, context, payload=payload),
                                status_code=503, headers={'Cache-Control': 'no-store'})
    operation, caller = asyncio.create_task(result()), asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((operation, caller), return_when=asyncio.FIRST_COMPLETED)
        return await operation if operation in done else Response(status_code=499)
    finally:
        operation.cancel()
        caller.cancel()
        await asyncio.gather(operation, caller, return_exceptions=True)

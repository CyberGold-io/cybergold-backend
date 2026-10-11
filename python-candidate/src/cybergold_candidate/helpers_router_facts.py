"""The Helpers configuration consumed by Swap and governance at one block."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from fastapi.responses import JSONResponse
from hexbytes import HexBytes
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from web3 import Web3

from .protocol_facts import ProtocolFactsRpc, handle_protocol_facts
from .helpers_execution import ABI as EXECUTION_ABI
from eth_utils.abi import collapse_if_tuple

ABI = json.loads(Path(__file__).with_name('helpers-router-facts-abi.json').read_text())
FIELDS = ('helperFeePpm', 'permit2', 'wrappedNative', 'owner', 'approvedAdapters', 'paused')


class HelpersFactsRequest(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)
    adapter: Annotated[str, StringConstraints(pattern=r'^0x[0-9a-fA-F]{40}$')] | None = None


class HelpersRouterFacts:
    def __init__(self, settings, rpc=None, now=None, owner_observer=None, configuration_observer=None,
                 configuration_scope=None):
        self.settings, self.rpc = settings, rpc
        self.owner_observer = owner_observer
        self.configuration_observer = configuration_observer
        self.configuration_scope = configuration_scope
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, adapter=None, *, token_permit=False, basket_permit=False, market_swap=False):
        configuration_scope = self.configuration_scope() if self.configuration_scope else None
        if self.rpc is None:
            self.rpc = ProtocolFactsRpc(self.settings, abi=ABI)
        async with asyncio.timeout(15):
            block = await self.rpc.block()

            async def read(name):
                if not self.rpc.helpers:
                    return {'status': 'failure', 'error': 'not-configured'}
                try:
                    value = await self.rpc.read('helpers', self.rpc.helpers, name, block)
                    return {'status': 'success', 'value': str(value) if name == 'helperFeePpm' else value}
                except Exception:
                    return {'status': 'failure', 'error': 'contract-read-failed'}

            values = await asyncio.gather(*(read(name) for name in FIELDS))
            adapter_observation = None
            if adapter is not None:
                adapter = Web3.to_checksum_address(adapter)
                try:
                    response = await self.rpc.w3.provider.make_request('eth_getCode', [
                        adapter, {'blockHash': block['hash'], 'requireCanonical': True}])
                    if 'error' in response:
                        raise ValueError('Adapter code read failed')
                    code = {'status': 'success', 'value': bool(HexBytes(response['result']))}
                except Exception:
                    code = {'status': 'failure', 'error': 'contract-read-failed'}
                adapter_observation = {'address': adapter, 'codePresent': code}
            async def installed(name):
                if not self.rpc.helpers:
                    return {'status': 'failure', 'error': 'not-configured'}
                else:
                    try:
                        entry = next(row for row in EXECUTION_ABI if row['name'] == name)
                        signature = entry['name'] + '(' + ','.join(collapse_if_tuple(part) for part in entry['inputs']) + ')'
                        selector = Web3.keccak(text=signature)[:4]
                        data = Web3.keccak(text='facetAddress(bytes4)')[:4] + self.rpc.w3.codec.encode(['bytes4'], [selector])
                        response = await self.rpc.w3.provider.make_request('eth_call', [
                            {'to': self.rpc.helpers, 'data': Web3.to_hex(data)},
                            {'blockHash': block['hash'], 'requireCanonical': True}])
                        if 'error' in response:
                            raise ValueError('Helpers selector read failed')
                        address = self.rpc.w3.codec.decode(['address'], bytes.fromhex(response['result'][2:]))[0]
                        return {'status': 'success', 'value': int(address, 16) != 0}
                    except Exception:
                        return {'status': 'failure', 'error': 'contract-read-failed'}
            permit_issuance = {}
            if token_permit:
                permit_issuance['tokenPermitIssuance'] = await installed('issueFromTokenExactOutWithPermit')
            if basket_permit:
                for mode in ('ExactIn', 'ExactOut'):
                    permit_issuance['basketPermitIssuance' + mode] = await installed('issueFromBasket' + mode + 'WithMixedPermits')
            if market_swap:
                for mode in ('Input', 'Output'):
                    permit_issuance['marketSwapExact' + mode] = await installed('swapExact' + mode)
            await self.rpc.assert_canonical(block)
            owner = values[FIELDS.index('owner')]
            if self.owner_observer and owner['status'] == 'success':
                await self.owner_observer(owner['value'])
            result = {'context': {'chainId': self.rpc.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'blockTimestamp': str(block['timestamp']), 'observedAt': self.now()},
                'helpers': self.rpc.helpers,
                **({'adapter': adapter_observation} if adapter_observation is not None else {}),
                'configuration': {**dict(zip(FIELDS, values, strict=True)),
                    **permit_issuance}}
            if self.configuration_observer:
                try:
                    await self.configuration_observer(result, configuration_scope)
                except Exception:
                    pass
            return result

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_helpers_router_facts(request, service):
    try:
        adapter = HelpersFactsRequest.model_validate(dict(request.query_params)).adapter
    except ValidationError:
        return JSONResponse({'error': 'A valid adapter address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    token_permit = request.query_params.get('tokenPermitIssuance') == 'true'
    basket_permit = request.query_params.get('basketPermitIssuance') == 'true'
    market_swap = request.query_params.get('marketSwap') == 'true'
    bound = SimpleNamespace(get=lambda: service.get(adapter, token_permit=token_permit, basket_permit=basket_permit, market_swap=market_swap)) if (
        service and (adapter is not None or token_permit or basket_permit or market_swap)) else service
    return await handle_protocol_facts(request, bound, 'helpers-router-facts',
                                       'Helpers configuration is temporarily unavailable.')

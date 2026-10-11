"""Retained canonical-anchor batching and budgets; standard Web3 ABI codec."""
import asyncio

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

from .recovery_rpc import abi_value
from .reconciliation_receipt import safe_count

ADDRESS = '0xca11bde05977b3631167028862be2a173976ca11'
LIMITS = {'maxCalls': 1024, 'maxTotalCalldataBytes': 1048576,
    'maxCallsPerBatch': 32, 'maxBatchCalldataBytes': 65536, 'maxProviderRequests': 32}
CODEC = Web3().codec


class MulticallBudgetError(ValueError):
    pass


def plan_batches(sizes, limits=None):
    limits = LIMITS if limits is None else limits
    if len(sizes) > limits['maxCalls'] or any(not safe_count(size) or not 0 < size <= limits['maxBatchCalldataBytes'] for size in sizes) or sum(sizes) > limits['maxTotalCalldataBytes']:
        raise MulticallBudgetError('Finalized Multicall read budget exceeded')
    batches, begin, total = [], 0, 0
    for index, size in enumerate(sizes):
        if index > begin and (index - begin >= limits['maxCallsPerBatch'] or total + size > limits['maxBatchCalldataBytes']):
            batches.append({'from': begin, 'to': index, 'calldataBytes': total})
            begin, total = index, 0
        total += size
    if begin < len(sizes):
        batches.append({'from': begin, 'to': len(sizes), 'calldataBytes': total})
    return batches


def encode_call(request):
    abi = request['abi']
    contract = Web3().eth.contract(abi=abi)
    function = next(item for item in abi if item.get('type') == 'function' and item['name'] == request['functionName'])
    args = [abi_value(value, parameter) for value, parameter in zip(request.get('args', []), function['inputs'], strict=True)]
    return contract.encode_abi(request['functionName'], args=args)


def decoded_value(value, parameter):
    if isinstance(value, bytes):
        return '0x' + value.hex()
    converted = abi_value(value, parameter)
    if isinstance(converted, dict):
        return {component['name']: decoded_value(value[index], component) for index, component in enumerate(parameter['components'])}
    if isinstance(converted, list):
        if parameter['type'].endswith(']'):
            inner = {**parameter, 'type': parameter['type'][:parameter['type'].rfind('[')]}
            return [decoded_value(item, inner) for item in value]
        if parameter['type'] == 'tuple':
            return [decoded_value(item, component) for item, component in zip(value, parameter['components'], strict=True)]
    return converted


def decode_call(request, data):
    function = next(item for item in request['abi'] if item.get('type') == 'function' and item['name'] == request['functionName'])
    values = CODEC.decode([collapse_if_tuple(output) for output in function['outputs']], bytes.fromhex(data[2:]))
    values = [decoded_value(value, output) for value, output in zip(values, function['outputs'], strict=True)]
    return values[0] if len(values) == 1 else values


class ContractClient:
    def __init__(self, rpc):
        self.rpc = rpc

    async def block(self, number=None, *, block_hash=None):
        return await self.rpc.block(number, block_hash=block_hash)

    async def block_number(self):
        return await self.rpc.block_number()

    async def request(self, method, params):
        return await self.rpc.request(method, params)

    async def logs(self, address, value, topic=None):
        return await self.rpc.logs(address, value, topic)

    async def read_contract(self, request):
        target = {'blockHash': request['blockHash'], 'requireCanonical': request.get('requireCanonical', False)} if request.get('blockHash') is not None else hex(request['blockNumber']) if request.get('blockNumber') is not None else request.get('blockTag', 'latest')
        result = await self.rpc.request('eth_call', [{'to': request['address'], 'data': encode_call(request)}, target])
        return decode_call(request, result)

    async def multicall(self, request):
        contracts = request['contracts']
        calls = [(value['address'], True, bytes.fromhex(encode_call(value)[2:])) for value in contracts]
        selector = Web3.keccak(text='aggregate3((address,bool,bytes)[])')[:4]
        data = '0x' + (selector + CODEC.encode(['(address,bool,bytes)[]'], [calls])).hex()
        result = await self.rpc.request('eth_call', [{'to': ADDRESS, 'data': data},
            {'blockHash': request['blockHash'], 'requireCanonical': True}])
        rows = CODEC.decode(['(bool,bytes)[]'], bytes.fromhex(result[2:]))[0]
        values = []
        for index, (success, raw) in enumerate(rows):
            try:
                if not success:
                    raise ValueError('Finalized Multicall contract read failed')
                values.append({'status': 'success', 'result': decode_call(contracts[index], '0x' + raw.hex())})
            except Exception as error:
                values.append({'status': 'failure', 'error': error})
        return values


class FinalizedMulticall:
    def __init__(self, client, block_hash, limits=None):
        self.client, self.block_hash = client, block_hash
        self.limits = LIMITS if limits is None else limits
        self.queue, self.scheduled = [], False
        self.calls = self.calldata = self.provider_requests = 0
        self.flush_tasks = set()

    async def block(self, number=None, *, block_hash=None):
        return await self.client.block(number, block_hash=block_hash)

    async def read_contract(self, request):
        if ((request.get('blockHash') or '').lower() != self.block_hash.lower() or request.get('requireCanonical') is not True
            or 'blockNumber' in request or 'blockTag' in request):
            raise ValueError('Finalized Multicall read is not bound to its exact canonical anchor')
        size = (len(encode_call(request)) - 2) // 2
        self.calls += 1
        self.calldata += size
        plan_batches([1] * (self.calls - 1) + [size], self.limits)
        if self.calldata > self.limits['maxTotalCalldataBytes']:
            raise MulticallBudgetError('Finalized Multicall read budget exceeded')
        future = asyncio.get_running_loop().create_future()
        self.queue.append((request, size, future))
        if not self.scheduled:
            self.scheduled = True
            asyncio.get_running_loop().call_soon(self.schedule_flush)
        return await future

    def schedule_flush(self):
        task = asyncio.create_task(self.flush())
        self.flush_tasks.add(task)
        task.add_done_callback(self.flush_tasks.discard)

    @staticmethod
    def reject(entries, error):
        for _, _, future in entries:
            if not future.done():
                future.set_exception(error)

    async def flush(self):
        self.scheduled = False
        pending, self.queue = self.queue, []
        if not pending:
            return
        try:
            batches = plan_batches([size for _, size, _ in pending], self.limits)
            maximum = self.limits.get('maxProviderRequests', LIMITS['maxProviderRequests'])
            if not safe_count(maximum) or maximum <= 0 or self.provider_requests + len(batches) > maximum:
                raise MulticallBudgetError('Finalized Multicall provider request budget exceeded')
        except Exception as error:
            self.reject(pending, error)
            return
        self.provider_requests += len(batches)
        for batch in batches:
            entries = pending[batch['from']:batch['to']]
            try:
                values = await self.client.multicall({'contracts': [{key: request[key] for key in ('address', 'abi', 'functionName', 'args') if key in request} for request, _, _ in entries],
                    'allowFailure': True, 'blockHash': self.block_hash, 'requireCanonical': True,
                    'multicallAddress': ADDRESS, 'batchSize': LIMITS['maxBatchCalldataBytes']})
                if len(values) != len(entries):
                    raise ValueError('Finalized Multicall returned the wrong result count')
                for value, (_, _, future) in zip(values, entries, strict=True):
                    if not future.done():
                        if value['status'] == 'success':
                            future.set_result(value['result'])
                        else:
                            future.set_exception(value['error'])
            except Exception as error:
                self.reject(entries, error)

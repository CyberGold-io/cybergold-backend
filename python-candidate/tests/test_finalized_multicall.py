"""Compare actual retained batching, budgets and Viem ABI bytes."""
import asyncio
import json
import sys
from cybergold_candidate.finalized_multicall import ContractClient, FinalizedMulticall, encode_call, decode_call, plan_batches


def wire(value):
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [wire(item) for item in value]
    return str(value) if type(value) is int else value


def arguments(value, parameter):
    if parameter['type'].endswith(']'):
        inner = {**parameter, 'type': parameter['type'][:parameter['type'].rfind('[')]}
        return [arguments(item, inner) for item in value]
    if parameter['type'].startswith(('uint', 'int')):
        return int(value)
    return value


async def check(reference):
    limits = {'maxCalls': 100, 'maxTotalCalldataBytes': 10000, 'maxCallsPerBatch': 2, 'maxBatchCalldataBytes': 1000, 'maxProviderRequests': 10}
    for case in reference['plans']:
        try:
            actual = {'result': plan_batches(case['sizes'], limits)}
        except Exception as error:
            actual = {'error': str(error)}
        assert actual == case['expected'], (case, actual)
    hash_value = '0x' + 'a' * 64
    abi = [{'type': 'function', 'name': 'fixture', 'stateMutability': 'view', 'inputs': [{'type': 'uint256', 'name': 'value'}], 'outputs': [{'type': 'uint256'}]}]
    # Use the exact retained ABI shape in provider-call envelopes too.
    abi = reference['cases'][0]['expected']['calls'][0]['contracts'][0]['abi']
    for case in reference['cases']:
        mode, calls, waves = case['mode'], [], []
        class Client:
            async def multicall(self, request):
                calls.append(request)
                if mode == 'provider-failure':
                    raise ValueError('fixture provider failure')
                if mode == 'wrong-count':
                    return []
                return [{'status': 'failure', 'error': ValueError('fixture contract failure')} if mode == 'contract-failure' and r['args'][0] == 2 else
                    {'status': 'success', 'result': r['args'][0] + 2} for r in request['contracts']]
        client = FinalizedMulticall(Client(), hash_value, case['limits'])
        for wave in ([1, 2, 3, 4], [5]):
            requests = [{'address': '0x' + '1' * 40, 'abi': abi, 'functionName': 'fixture', 'args': [value],
                'blockHash': '0x' + 'b' * 64 if mode == 'wrong-anchor' else hash_value, 'requireCanonical': mode != 'not-canonical',
                **({'blockNumber': 1} if mode == 'block-number' else {}), **({'blockTag': 'finalized'} if mode == 'block-tag' else {})} for value in wave]
            settled = await asyncio.gather(*(client.read_contract(request) for request in requests), return_exceptions=True)
            waves.append([{'error': str(value)} if isinstance(value, Exception) else {'result': str(value)} for value in settled])
        expected_calls = case['expected']['calls']
        assert waves == case['expected']['waves'] and wire(calls) == wire(expected_calls), (mode, waves, calls, case['expected'])
    for case in reference['codec']:
        request = case['request']
        function = request['abi'][0]
        request['args'] = [arguments(value, parameter) for value, parameter in zip(request['args'], function['inputs'], strict=True)]
        assert encode_call(request) == case['encoded'], case
        result = decode_call(request, case['returnData'])
        # Viem decodes <=48-bit ints as numbers, uint256 as bigint strings.
        def result_wire(value, parameter):
            if parameter['type'].endswith(']'):
                inner = {**parameter, 'type': parameter['type'][:parameter['type'].rfind('[')]}
                return [result_wire(item, inner) for item in value]
            if parameter['type'] == 'tuple':
                return {part['name']: result_wire(value[part['name']], part) for part in parameter['components']}
            if parameter['type'].startswith(('uint', 'int')) and int(parameter['type'].lstrip('uint') or 256) > 48:
                return str(value)
            return value
        converted = result_wire(result, function['outputs'][0]) if len(function['outputs']) == 1 else [result_wire(v, p) for v, p in zip(result, function['outputs'], strict=True)]
        assert converted == case['result'], (case, converted)
    aggregate = reference['aggregate']
    sent = []
    class Rpc:
        async def request(self, method, params):
            assert method == 'eth_call'; sent.append(params); return aggregate['response']
    for request in aggregate['input']['contracts']:
        request['args'] = [int(value) for value in request['args']]
    results = await ContractClient(Rpc()).multicall(aggregate['input'])
    assert sent == aggregate['calls'], (sent, aggregate['calls'])
    assert [{'status': value['status'], **({'result': str(value['result'])} if value['status'] == 'success' else {})} for value in results] == aggregate['results']
    print(f"PASS: {len(reference['plans'])} retained Multicall plans, {len(reference['cases'])} multi-wave queue/budget/error paths and {len(reference['codec'])} Viem/Web3 ABI byte/result comparisons; aggregate wire bytes, canonical anchor and partial failure match")


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))

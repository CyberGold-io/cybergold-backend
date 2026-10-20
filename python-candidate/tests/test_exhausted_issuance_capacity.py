"""Distinguish Helpers' zero-output revert from exhausted issuance, at one block."""
import asyncio
from types import SimpleNamespace
import unittest

from eth_utils.abi import collapse_if_tuple
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.basket_preview import BasketPreviewRpc
from cybergold_candidate.issuance_capacity import (
    ABI, READS, exhausted_capacity_error, read_capacity, read_supply_capacity,
)
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.token_preview import TokenPreviewRpc

BLOCK = {'hash': '0x' + 'a' * 64, 'number': 101}
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
    NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x' + '1' * 40,
    NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x' + '2' * 40)
ZERO_OUTPUT = Web3.to_hex(Web3.keccak(text='AmountTooSmallAfterFees()'))[:10]


def abi_value(parameter):
    if parameter['type'].endswith('[]'):
        return []
    if parameter['type'] == 'tuple':
        return tuple(abi_value(item) for item in parameter['components'])
    return 1


class Provider(AsyncBaseProvider):
    def __init__(self, *, capacity=(250, 250, 1000), revert=ZERO_OUTPUT):
        super().__init__()
        self.capacity, self.revert, self.calls = capacity, revert, []
        self.w3 = Web3()
        self.reads = {self.w3.eth.contract(abi=ABI).encode_abi(name): (name, output)
                      for name, output in READS}
        self.values = dict(zip((name for name, _ in READS),
            ([500000, 500000], [10**18, 10**18], 100, *capacity, 200), strict=True))

    async def make_request(self, method, params):
        assert method == 'eth_call'
        self.calls.append(params)
        data = params[0]['data']
        if data in self.reads:
            name, output = self.reads[data]
            result = '0x' + self.w3.codec.encode([output], [self.values[name]]).hex()
            return {'jsonrpc': '2.0', 'id': 1, 'result': result}
        if self.revert is not None:
            return {'jsonrpc': '2.0', 'id': 1,
                    'error': {'code': 3, 'data': self.revert, 'message': 'execution reverted'}}
        for rpc_type in (BasketPreviewRpc, TokenPreviewRpc):
            contract = self.w3.eth.contract(abi=rpc_type.abi)
            try:
                function, _ = contract.decode_function_input(data)
            except ValueError:
                continue
            output = next(row for row in rpc_type.abi if row['name'] == function.fn_name)['outputs'][0]
            result = '0x' + self.w3.codec.encode([collapse_if_tuple(output)], [abi_value(output)]).hex()
            return {'jsonrpc': '2.0', 'id': 1, 'result': result}
        raise AssertionError(data)

    async def disconnect(self):
        pass


def preview(provider, request):
    rpc_type = TokenPreviewRpc if any(part in request['mode'] for part in ('-token-', '-native-')) else BasketPreviewRpc
    rpc = rpc_type(SETTINGS, AsyncWeb3(provider))
    return rpc.preview(request['mode'], rpc.encode(request), BLOCK)


ISSUE_REQUESTS = [
    {'mode': 'issue-exact-in', 'maximumAmountsIn': ['100', '100']},
    {'mode': 'issue-exact-out', 'netCygldOut': '100'},
    {'mode': 'issue-token-exact-in', 'inputToken': '0x' + '3' * 40, 'inputAmount': '100', 'quotes': []},
    {'mode': 'issue-native-exact-in', 'inputAmount': '100', 'quotes': []},
    {'mode': 'issue-token-exact-out', 'inputToken': '0x' + '3' * 40,
     'maximumInputAmount': '100', 'netCygldOut': '100', 'quotes': []},
    {'mode': 'issue-native-exact-out', 'maximumNativeIn': '100', 'netCygldOut': '100', 'quotes': []},
]
REDEEM_REQUESTS = [
    {'mode': 'redeem-exact-in', 'grossCygldIn': '100'},
    {'mode': 'redeem-exact-out', 'minimumOutputs': []},
    {'mode': 'redeem-token-exact-in', 'outputToken': '0x' + '3' * 40, 'grossCygldIn': '100', 'quotes': []},
    {'mode': 'redeem-native-exact-in', 'grossCygldIn': '100', 'quotes': []},
]


class ExhaustedIssuanceCapacityTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_limit_reports_only_the_binding_supply_limit(self):
        for values, kind, limit in (((250, 250, 1000), 'maximum-total-supply', 250),
                                   ((250, 1000, 250), 'effective-supply-cap', 250),
                                   ((251, 250, 250), 'maximum-total-supply', 250)):
            error = exhausted_capacity_error(values)
            self.assertIsInstance(error, KnownPreviewError)
            self.assertEqual(public_quote_error(error), {
                'code': 'issuance-cap-exceeded', 'error': str(error), 'constraint': {
                    'kind': 'issuance-cap', 'quantity': 'gross-cygld-mint', 'limitKind': kind,
                    'availableRaw': '0', 'currentSupplyRaw': str(values[0]), 'limitRaw': str(limit)}})
        self.assertIsNone(exhausted_capacity_error((249, 250, 1000)))
        self.assertIsNone(exhausted_capacity_error((0, 2**256-1, 2**256-1)))

    async def test_ambiguous_zero_output_issue_revert_is_cap_error_only_when_capacity_is_zero(self):
        for request in ISSUE_REQUESTS:
            for values in ((250, 250, 1000), (250, 1000, 250), (249, 250, 1000)):
                with self.subTest(mode=request['mode'], capacity=values):
                    provider = Provider(capacity=values)
                    with self.assertRaises(ValueError) as caught:
                        await preview(provider, request)
                    expected = 'issuance-cap-exceeded' if values[0] >= min(values[1:]) else 'quote-contract-reverted'
                    self.assertEqual(public_quote_error(caught.exception)['code'], expected)
                    self.assertEqual(len(provider.calls), 4)
                    self.assertTrue(all(params[1] == {'blockHash': BLOCK['hash'], 'requireCanonical': True}
                                        for params in provider.calls))
                    self.assertEqual([params[0]['to'] for params in provider.calls[1:]],
                                     [SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS] * 3)

    async def test_success_redemption_and_other_reverts_do_not_gain_capacity_reads(self):
        cap_selector = Web3.to_hex(Web3.keccak(text='MaxTotalSupplyExceeded(uint256,uint256,uint256)'))[:10]
        cap_error = cap_selector + Web3().codec.encode(['uint256'] * 3, [250, 1, 250]).hex()
        for request in ISSUE_REQUESTS + REDEEM_REQUESTS:
            for revert in (None, '0x12345678', cap_error):
                with self.subTest(mode=request['mode'], revert=revert):
                    provider = Provider(revert=revert)
                    if revert is None:
                        await preview(provider, request)
                    else:
                        with self.assertRaises(ValueError):
                            await preview(provider, request)
                    self.assertEqual(len(provider.calls), 1)
        for request in REDEEM_REQUESTS:
            provider = Provider()
            with self.assertRaises(ValueError) as caught:
                await preview(provider, request)
            self.assertEqual(public_quote_error(caught.exception)['code'], 'quote-contract-reverted')
            self.assertEqual(len(provider.calls), 1)

    async def test_reusing_early_supply_reads_preserves_capacity_shape_and_seven_reads(self):
        provider = Provider(capacity=(249, 250, 1000))
        rpc = SimpleNamespace(w3=AsyncWeb3(provider))
        metrics = {'rpcReads': 0, 'rpcReadsRequested': 0}
        supply = await read_supply_capacity(rpc, SETTINGS, BLOCK, metrics)
        self.assertEqual(supply, (249, 250, 1000))
        values = await read_capacity(rpc, SETTINGS, BLOCK, metrics, supply_values=supply)
        self.assertEqual(values, [tuple(value) if isinstance(value, list) else value
                                  for value in provider.values.values()])
        self.assertEqual(len(provider.calls), 7)
        self.assertEqual(metrics, {'rpcReads': 7, 'rpcReadsRequested': 7})
        ordinary_provider = Provider(capacity=(249, 250, 1000))
        ordinary_values = await read_capacity(SimpleNamespace(w3=AsyncWeb3(ordinary_provider)), SETTINGS,
            BLOCK, {'rpcReads': 0, 'rpcReadsRequested': 0})
        self.assertEqual(ordinary_values, values)
        self.assertEqual(len(ordinary_provider.calls), 7)

    async def test_shared_reads_preserve_issued_coalesced_and_reused_metrics(self):
        provider = Provider(capacity=(249, 250, 1000))
        async def pool_batch(calls, block, counts):
            counts.update(requested=len(calls), issued=1, coalesced=1, reused=1)
            return [await provider.make_request('eth_call', [{'to': address, 'data': data},
                {'blockHash': block['hash'], 'requireCanonical': True}]) for address, data in calls], None
        metrics = {'rpcReads': 0, 'rpcReadsRequested': 0, 'rpcReadsCoalesced': 0, 'rpcReadsReused': 0}
        values = await read_supply_capacity(SimpleNamespace(w3=AsyncWeb3(provider), pool_batch=pool_batch),
            SETTINGS, BLOCK, metrics, shared=True)
        self.assertEqual(values, (249, 250, 1000))
        self.assertEqual(metrics, {'rpcReads': 1, 'rpcReadsRequested': 3, 'rpcReadsCoalesced': 1, 'rpcReadsReused': 1})

    async def test_direct_read_failure_and_caller_cancellation_drain_all_sibling_reads(self):
        class BlockingProvider(Provider):
            def __init__(self, fail):
                super().__init__()
                self.fail, self.started, self.finished, self.cancelled = fail, 0, 0, 0
                self.all_started = asyncio.Event()

            async def make_request(self, method, params):
                self.started += 1
                if self.started == 3:
                    self.all_started.set()
                try:
                    await self.all_started.wait()
                    name, _ = self.reads[params[0]['data']]
                    if self.fail and name == 'totalSupply':
                        raise RuntimeError('Fixture read failure')
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
                finally:
                    self.finished += 1

        for fail in (True, False):
            provider = BlockingProvider(fail)
            operation = asyncio.create_task(read_supply_capacity(
                SimpleNamespace(w3=AsyncWeb3(provider)), SETTINGS, BLOCK))
            await provider.all_started.wait()
            if not fail:
                operation.cancel()
            with self.assertRaises(RuntimeError if fail else asyncio.CancelledError):
                await operation
            self.assertEqual(provider.finished, 3)
            self.assertEqual(provider.cancelled, 2 if fail else 3)


if __name__ == '__main__':
    unittest.main()

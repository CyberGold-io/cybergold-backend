"""Funding overrides touch only the synthetic payer's exact funding entries."""
from copy import deepcopy
import socket
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.app_tokens import TOKENS
from cybergold_candidate.quoter.simulation_funding import (
    SIMULATION_SENDER, UnsupportedSimulationFunding, funding_overrides,
)
from cybergold_candidate.routing_encoding import ZERO


HELPERS = '0x'+'12'*20
CORE = '0x'+'34'*20
UNKNOWN = '0x'+'56'*20
MAXIMUM = (1 << 256) - 1


def slot(owner, root):
    return Web3.keccak(Web3().codec.encode(['address', 'uint256'], [owner, root]))


class SimulationFundingTests(unittest.TestCase):
    def test_configured_tokens_override_only_exact_payer_balance_and_helpers_allowance(self):
        for name, balance_root, allowance_root in (
                ('weth', 3, 4), ('usdc', 9, 10), ('usdt', 2, 5),
                ('paxg', 1, 3), ('xaut', 51, 52)):
            with self.subTest(token=name):
                currency = dict(TOKENS)[name]
                value = funding_overrides([{'currency': currency, 'amount': '1234567'}], HELPERS, CORE)
                allowance = slot(HELPERS, int.from_bytes(slot(SIMULATION_SENDER, allowance_root), 'big'))
                expected = {Web3.to_hex(slot(SIMULATION_SENDER, balance_root)), Web3.to_hex(allowance)}
                self.assertEqual(set(value), {SIMULATION_SENDER, currency})
                self.assertEqual(value[SIMULATION_SENDER], {'balance': '0x0'})
                self.assertEqual(set(value[currency]), {'stateDiff'})
                self.assertEqual(set(value[currency]['stateDiff']), expected)
                self.assertTrue(all(int(word, 16) == 1234567 and len(word) == 66
                                    for word in value[currency]['stateDiff'].values()))

    def test_native_lots_are_aggregated_without_storage_or_code_override(self):
        value = funding_overrides([{'currency': ZERO, 'amount': '3'},
                                   {'currency': ZERO, 'amount': '7'}], HELPERS, CORE)
        self.assertEqual(value, {SIMULATION_SENDER: {'balance': '0xa'}})

    def test_duplicate_token_currencies_share_exact_aggregate_funding(self):
        weth = dict(TOKENS)['weth']
        inputs = [{'currency': weth.lower(), 'amount': '3'}, {'currency': weth, 'amount': '7'}]
        saved = deepcopy(inputs)
        value = funding_overrides(inputs, HELPERS, CORE)
        self.assertEqual(inputs, saved)
        self.assertEqual(len(value[weth]['stateDiff']), 2)
        self.assertEqual(set(map(lambda word: int(word, 16), value[weth]['stateDiff'].values())), {10})

    def test_dynamic_core_uses_namespaced_storage_and_non_decrementing_allowance(self):
        root = int('52c63247e1f47db19d5ce0460030c497f067ca4cebf71ba98eeadabe20bace00', 16)
        value = funding_overrides([{'currency': CORE, 'amount': '21'}], HELPERS, CORE)
        state = value[Web3.to_checksum_address(CORE)]['stateDiff']
        allowance = slot(HELPERS, int.from_bytes(slot(SIMULATION_SENDER, root + 1), 'big'))
        self.assertEqual(int(state[Web3.to_hex(slot(SIMULATION_SENDER, root))], 16), 21)
        self.assertEqual(int(state[Web3.to_hex(allowance)], 16), MAXIMUM)
        self.assertEqual(len(state), 2)

    def test_mixed_input_vector_changes_only_funded_token_and_payer_entries(self):
        paxg, xaut = dict(TOKENS)['paxg'], dict(TOKENS)['xaut']
        value = funding_overrides([{'currency': paxg, 'amount': '5'}, {'currency': xaut, 'amount': '6'},
                                   {'currency': ZERO, 'amount': '7'}], HELPERS, CORE)
        self.assertEqual(set(value), {paxg, xaut, SIMULATION_SENDER})
        self.assertEqual(value[SIMULATION_SENDER], {'balance': '0x7'})
        self.assertTrue(all(set(fields) == {'stateDiff'} and len(fields['stateDiff']) == 2
                            for token, fields in value.items() if token != SIMULATION_SENDER))

    def test_zero_lots_need_no_token_layout_or_override(self):
        self.assertEqual(funding_overrides([{'currency': UNKNOWN, 'amount': '0'}], HELPERS, CORE),
                         {SIMULATION_SENDER: {'balance': '0x0'}})

    def test_unknown_positive_input_has_specific_ordinary_error(self):
        with self.assertRaisesRegex(UnsupportedSimulationFunding, 'not supported for input currency') as caught:
            funding_overrides([{'currency': UNKNOWN, 'amount': '1'}], HELPERS, CORE)
        self.assertEqual(caught.exception.code, 'unsupported-simulation-funding')
        self.assertEqual(caught.exception.currency, Web3.to_checksum_address(UNKNOWN))

    def test_computation_has_no_network_or_account_reads(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('Unexpected network access')):
            value = funding_overrides([{'currency': dict(TOKENS)['weth'], 'amount': '1'}], HELPERS, CORE)
        self.assertEqual(len(value), 2)


if __name__ == '__main__':
    unittest.main()

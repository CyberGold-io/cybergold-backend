"""Display ranges reuse Backend economics without acquiring execution authority."""
import unittest

from cybergold_candidate.fast_trade_estimates import FastTradeEstimates


REQUEST = {'side': 'buy', 'mode': 'exact-in', 'counterToken': '0x'+'1'*40,
           'native': False, 'amount': '100', 'slippageBps': 100, 'adapter': '0x'+'2'*40}
SCOPE = ('31338', 'core', 'helpers', 1, 'fork-a')


class FastTradeEstimateTests(unittest.TestCase):
    def test_smaller_and_larger_buy_budget_reuse_complete_core_or_market_spending_and_output(self):
        for strategy in ('core', 'market'):
            with self.subTest(strategy=strategy):
                estimates = FastTradeEstimates()
                estimates.remember_selected(REQUEST,
                    {'strategy': strategy, 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31',
                     'providerQuote': {'requestedGrossCygldOut': '400', 'remainingGrossCapacity': '125'}},
                    scope=SCOPE)
                # Competing approximate curves cannot replace the known tuple
                # in its established funding range, regardless of provider.
                for amount in ('50', '200', str(2**256-1)):
                    with self.subTest(amount=amount):
                        value = estimates.packet({**REQUEST, 'amount': amount}, [('core', '9999')], scope=SCOPE)
                        self.assertEqual(value, {
                            'estimate': {'strategy': strategy, 'amount': '125'},
                            'budgetRange': {'minimumBudget': '31',
                                            'quotedInput': '30', 'quotedOutput': '125'}})

    def test_purchase_requires_enough_funding_but_has_no_original_budget_ceiling(self):
        estimates = FastTradeEstimates()
        estimates.remember_selected(REQUEST,
            {'strategy': 'market', 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31'},
            scope=SCOPE)
        for amount in (31, 100, 101, 200):
            self.assertEqual(estimates.packet({**REQUEST, 'amount': str(amount)}, [], scope=SCOPE)
                             ['estimate']['amount'], '125')
        for amount in (0, 30):
            value = estimates.packet({**REQUEST, 'amount': str(amount)}, [('core', '7')], scope=SCOPE)
            self.assertEqual(value['estimate'], {'strategy': 'core', 'amount': '7'})
            self.assertEqual(value['budgetRange']['quotedInput'], '30')

    def test_partial_sale_keeps_its_original_upper_budget_bound(self):
        estimates = FastTradeEstimates()
        sale = {**REQUEST, 'side': 'sell'}
        estimates.remember_selected(sale,
            {'strategy': 'market', 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31'},
            scope=SCOPE)
        for amount in ('31', '50', '100'):
            value = estimates.packet({**sale, 'amount': amount}, [], scope=SCOPE)
            self.assertEqual(value['estimate']['amount'], '125')
            self.assertEqual(value['budgetRange']['maximumBudget'], '100')
        for amount in ('30', '101', '200'):
            value = estimates.packet({**sale, 'amount': amount}, [('core', '7')], scope=SCOPE)
            self.assertEqual(value['estimate'], {'strategy': 'core', 'amount': '7'})

    def test_family_and_existing_fork_configuration_boundaries_do_not_reuse_other_facts(self):
        estimates = FastTradeEstimates()
        estimates.remember_selected(REQUEST,
            {'strategy': 'market', 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31'},
            scope=SCOPE)
        for changes in ({'counterToken': '0x'+'3'*40}, {'native': True}, {'side': 'sell'},
                        {'mode': 'exact-out'}, {'slippageBps': 99}, {'adapter': '0x'+'4'*40}):
            self.assertNotIn('budgetRange', estimates.packet({**REQUEST, **changes}, [], scope=SCOPE))
        self.assertNotIn('budgetRange', estimates.packet(REQUEST, [], scope=(*SCOPE[:-1], 'fork-b')))
        self.assertNotIn('budgetRange', estimates.packet(REQUEST, [], scope=SCOPE))

    def test_fresh_full_spend_or_selected_invalidation_retires_previous_range(self):
        estimates = FastTradeEstimates()
        partial = {'strategy': 'core', 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31',
                   'providerQuote': {'requestedGrossCygldOut': '400', 'remainingGrossCapacity': '125'}}
        estimates.remember_selected(REQUEST, partial, scope=SCOPE)
        estimates.remember_selected(REQUEST,
            {'strategy': 'market', 'quotedInput': '100', 'quotedOutput': '500', 'inputMaximum': '100'},
            scope=SCOPE)
        self.assertNotIn('budgetRange', estimates.packet(REQUEST, [], scope=SCOPE))
        estimates.remember_selected(REQUEST, partial, scope=SCOPE)
        estimates.invalidate(REQUEST, scope=SCOPE)
        self.assertNotIn('budgetRange', estimates.packet(REQUEST, [], scope=SCOPE))

    def test_uncapped_core_under_spending_uses_ordinary_curve_instead_of_a_false_plateau(self):
        for capacity in ({}, {'requestedGrossCygldOut': '100', 'remainingGrossCapacity': str(10**30)}):
            with self.subTest(capacity=capacity):
                estimates = FastTradeEstimates()
                estimates.remember_selected(REQUEST,
                    {'strategy': 'core', 'quotedInput': '50', 'quotedOutput': '100', 'inputMaximum': '52',
                     'providerQuote': capacity}, scope=SCOPE)
                self.assertEqual(estimates.packet({**REQUEST, 'amount': '200'}, [('core', '200')], scope=SCOPE),
                                 {'estimate': {'strategy': 'core', 'amount': '200'}})

    def test_core_at_exact_capacity_also_has_an_unbounded_purchase_display_range(self):
        estimates = FastTradeEstimates()
        estimates.remember_selected(REQUEST,
            {'strategy': 'core', 'quotedInput': '30', 'quotedOutput': '125', 'inputMaximum': '31',
             'providerQuote': {'requestedGrossCygldOut': '125', 'remainingGrossCapacity': '125'}}, scope=SCOPE)
        value = estimates.packet({**REQUEST, 'amount': '200'}, [], scope=SCOPE)
        self.assertEqual(value['estimate'], {'strategy': 'core', 'amount': '125'})
        self.assertNotIn('maximumBudget', value['budgetRange'])

    def test_full_spend_sale_has_no_smaller_budget_plateau_and_fallback_preserves_backend_ranking(self):
        estimates = FastTradeEstimates()
        sale = {**REQUEST, 'side': 'sell', 'amount': '500'}
        estimates.remember_selected(sale,
            {'strategy': 'market', 'quotedInput': '500', 'quotedOutput': '161', 'inputMaximum': '500'},
            scope=SCOPE)
        packet = estimates.packet({**sale, 'amount': '250'}, [('core', '80'), ('market', '79')], scope=SCOPE)
        self.assertEqual(packet, {'estimate': {'strategy': 'core', 'amount': '80'}})
        self.assertEqual(estimates.packet({**sale, 'mode': 'exact-out'},
                         [('market', '80'), ('core', '80')], scope=SCOPE)['estimate']['strategy'], 'core')
        self.assertEqual(estimates.packet({**sale, 'mode': 'exact-out'},
                         [('market', '79'), ('core', '80')], scope=SCOPE)['estimate']['strategy'], 'market')


if __name__ == '__main__':
    unittest.main()

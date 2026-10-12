"""Upper-model candidate boundaries; no candidate bypasses exact validation."""
from copy import deepcopy
import unittest

from .benchmark_component_correction import state, solve, oracle
from .quote_component_correction import ComponentCorrection
from cybergold_candidate.quote_correction import delayed_local_step


class ComponentCorrectionTest(unittest.TestCase):
    def test_original_first_three_checks_are_unchanged(self):
        component=ComponentCorrection(state(),'weth',lambda path:path)
        for points in ([],[(10,20)],[(10,20),(11,22)]):
            self.assertEqual(component(points,25,12),12)

    def test_no_observed_upper_uses_existing_local_step(self):
        component=ComponentCorrection(state(),'weth',lambda path:path)
        points=[(10,20),(11,21),(12,22)]
        self.assertEqual(component(points,30,15),delayed_local_step(points,30,15))
        self.assertEqual(component.fallbacks,1)

    def test_missing_leg_cannot_be_treated_as_zero(self):
        component=ComponentCorrection(state(),'weth',lambda path:path)
        value=oracle(2802115027027027,state())
        value['quotes']=value['quotes'][:1]
        component.observe_result(value)
        self.assertIsNone(component.predict(2802115027027027))

    def test_basket_supply_limit_uses_ordinary_error_fallback(self):
        component=ComponentCorrection(state(),'weth',lambda path:path)
        self.assertIsNone(component.predict(state()['supply']*2))

    def test_controlled_results_always_remain_in_accepted_interval(self):
        for regime in ('smooth','tick'):
            for target in (10**12,131700000113139,5*10**15):
                for variant in ('component','upperRate'):
                    value=solve(target,variant,regime)
                    self.assertLessEqual(value['evaluations'],11)
                    if value['status']=='complete':
                        self.assertGreaterEqual(int(value['minimum']),target)
                        self.assertLessEqual(int(value['minimum']),target*101//100)

    def test_direct_token_and_recovery_do_not_require_swap_model(self):
        snapshot=deepcopy(state())
        snapshot['descriptors'][1]['kind']=1
        component=ComponentCorrection(snapshot,snapshot['assets'][0],lambda path:path)
        gross=2802115027027027
        expected=component.basket.redeem_in(gross)['projectedCoreOutputs'][0]['amount']
        self.assertEqual(component.predict(gross),expected)

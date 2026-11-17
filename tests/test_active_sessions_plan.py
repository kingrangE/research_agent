import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('plan', Path(__file__).resolve().parents[1] / 'scripts/plan_active_sessions.py')
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class LoadPlanTests(unittest.TestCase):
    def test_exact_denominator(self):
        result = plan.expectation(10000, 1800)
        self.assertEqual(result['expected_requests'], 9090000)
        self.assertEqual(result['expected_rps'], 5050)
        self.assertEqual(result['expected_endpoint_requests']['quotes'], 1800000)
        self.assertEqual(plan.expectation(100, 600)['expected_requests'], 30300)
        self.assertEqual(plan.expectation(1000, 600)['expected_requests'], 303000)
        self.assertEqual(plan.expectation(5000, 600)['expected_requests'], 1515000)

    def test_invalid_plan_rejected(self):
        for users, seconds in [(0,30),(101,30),(10100,30),(100,29)]:
            with self.assertRaises(ValueError):
                plan.expectation(users, seconds)


if __name__ == '__main__':
    unittest.main()

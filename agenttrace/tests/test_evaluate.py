"""Tests for agenttrace.evaluate: the volume-alarm baseline and the robustness intervals."""
import unittest

from agenttrace import evaluate

H = 3600.0


class EvaluateTests(unittest.TestCase):
    def test_rate_alarm_fires_on_the_surge_and_reports_harm_still_to_come(self):
        quiet = [h * H + 60 for h in range(24)]                        # one action an hour for a day
        surge = [24 * H + i for i in range(200)]                       # then 200 in one hour
        harm = [24 * H + i for i in range(100)] + [30 * H + i for i in range(100)]
        a = evaluate.rate_alarm(quiet + surge, harm)
        self.assertEqual(a["count"], 200)
        self.assertEqual(a["harm_share_after"], 0.5)                   # known at the end of the surge hour

    def test_no_alarm_without_history(self):
        self.assertIsNone(evaluate.rate_alarm([0, 10, 20], [5]))

    def test_robustness_interval_contains_the_point_estimate(self):
        harm = [h * H for h in range(100)]
        sig = [{"signal": "first: x", "time": "t", "harm_share_after": 0.5, "t": 49.5 * H}]
        r = evaluate.robustness(sig, harm, sigma_h=1.0, draws=300)[0]
        lo, hi = r["interval_95"]
        self.assertLessEqual(lo, 0.5)
        self.assertGreaterEqual(hi, 0.5)
        self.assertLess(hi - lo, 0.1)

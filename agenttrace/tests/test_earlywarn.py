import json
import os
import re
import shutil
import tempfile
import unittest

from agenttrace import earlywarn, groundtruth, live, validation

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "app", "views")


def run(mode, setting, lead_harm=None, hours=36, agents=10, signs=(), rules=None, alarms=None):
    """A hand-made run record, the shape earlywarn.extract returns."""
    return {"mode": mode, "setting": setting, "dated": True, "hours": hours, "agents": agents, "first_true_harm_h": 18.0,
            "first_true_message_h": 12.0, "signs": [{"id": i, "name": i, "family": "joint", "kind": "message", "h": h} for i, h in signs],
            "rules": rules or {}, "alarms": alarms or {}}


class TestStats(unittest.TestCase):
    def test_poisson_interval_known_values(self):
        lo, hi = earlywarn.poisson_ci(0, 1.0)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 3.689, places=2)
        lo, hi = earlywarn.poisson_ci(10, 1.0)
        self.assertAlmostEqual(lo, 4.795, places=2)
        self.assertAlmostEqual(hi, 18.39, places=1)

    def test_interval_scales_with_exposure(self):
        lo, hi = earlywarn.poisson_ci(5, 10.0)
        lo1, hi1 = earlywarn.poisson_ci(5, 1.0)
        self.assertAlmostEqual(hi * 10, hi1, places=6)
        self.assertAlmostEqual(lo * 10, lo1, places=6)


class TestFrozen(unittest.TestCase):
    def test_file_is_dated_and_complete(self):
        fz = earlywarn.load_frozen()
        self.assertEqual(fz["frozen_on"], "2026-11-13")
        self.assertIn("knew how the Swarm Traces incident unfolded", fz["note"])
        self.assertEqual(len(fz["code"]["git_head"]), 40)
        self.assertTrue(fz["code"]["sha256"]["agenttrace/insight.py"])
        self.assertEqual([r["id"] for r in fz["rules"]], [r["id"] for r in live.DEFAULT_RULES])
        for r, d in zip(fz["rules"], live.DEFAULT_RULES):
            self.assertEqual(r["conditions"], d["conditions"])      # the thresholds are the live defaults
        ids = {x["id"] for x in fz["signs"]}
        for need in ("message", "two_way", "group3", "group20", "program2", "program3", "rate_all", "rate_harm",
                     "coordination: two identities use one place", "first: hf_dataset_write", "first: probe_request"):
            self.assertIn(need, ids)
        self.assertEqual(fz["volume_baseline"]["k_sigma"], 3.0)

    def test_every_sign_a_swarm_produces_is_frozen(self):
        d = tempfile.mkdtemp()
        try:
            os.environ["SWARM_TRACER_NO_CACHE"] = "1"
            r = earlywarn._swarm_run(d, {"agents": 14, "realworld": 0.6}, "t", "t", 21)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        ids = {x["id"] for x in earlywarn.load_frozen()["signs"]}
        self.assertTrue(r["signs"])
        for g in r["signs"]:
            self.assertIn(g["id"], ids)
        self.assertIsNotNone(r["first_true_harm_h"])
        self.assertIn("watch-harm", r["rules"])
        self.assertEqual(set(r["alarms"]), {f["id"] for f in earlywarn.FAMILIES})

    def test_drift_is_reported_not_fatal(self):
        st = earlywarn.frozen_status()
        self.assertIsInstance(st["drift"], list)
        self.assertIn("frozen", st)


class TestTables(unittest.TestCase):
    def runs(self):
        c = lambda i, **k: run("coordinated", "base", alarms={"watch": {"1": 17.0, "2": 18.5, "3": None},
                                                               "coord": {str(n): 10.0 + n for n in range(1, 6)},
                                                               "volume": {"2": 15.0, "3": 20.0, "4": None, "5": None},
                                                               "place": {"1": 8.0}, "message": {"1": 12.0},
                                                               "group": {"3": 13.0, "5": 14.0, "10": 15.0, "20": 16.0}},
                               signs=[("message", 12.0)], rules={"watch-harm": 17.0, "alert-coord2": 12.0, "baseline-volume": 20.0})
        b = lambda fire: run("benign", "benign", signs=[("message", 5.0)] if fire else [], rules={"watch-harm": 3.0 if fire else None},
                             alarms={"watch": {"1": 3.0 if fire else None, "2": None, "3": None}, "coord": {str(n): None for n in range(1, 6)},
                                     "volume": {str(k): None for k in range(2, 6)}, "place": {"1": None}, "message": {"1": 5.0 if fire else None},
                                     "group": {str(k): None for k in (3, 5, 10, 20)}})
        return [c(i) for i in range(4)] + [b(True), b(False), b(False), b(False)]

    def test_forward_table_leads_and_ticks(self):
        f = earlywarn.forward_table(self.runs())
        msg = next(x for x in f["signs"] if x["id"] == "message")
        self.assertEqual(msg["coordinated"]["harm"]["fired"], 4)
        self.assertEqual(msg["coordinated"]["harm"]["median_lead_h"], 6.0)       # 18 - 12
        self.assertEqual(msg["coordinated"]["message"]["median_lead_h"], 0.0)
        self.assertEqual(msg["benign"]["fired"], 1)
        watch = next(x for x in f["rules"] if x["id"] == "watch-harm")
        self.assertEqual(watch["coordinated"]["harm"]["median_lead_h"], 1.0)
        self.assertEqual(watch["benign"], {"n": 4, "fired": 1})

    def test_false_alarm_rate_and_exposure(self):
        a = earlywarn.false_alarms(self.runs())
        self.assertEqual(a["benign_runs"], 4)
        self.assertEqual(a["trace_hours"], 144.0)
        self.assertEqual(a["agent_hours"], 1440)
        w = next(r for r in a["rows"] if r["id"] == "watch-harm")
        self.assertEqual(w["alarms"], 1)
        self.assertAlmostEqual(w["per_24h"], 1 / 6.0, places=3)                 # 1 alarm in 6 days
        self.assertLess(w["ci_low"], w["per_24h"])
        self.assertGreater(w["ci_high"], w["per_24h"])
        z = next(r for r in a["rows"] if r["id"] == "alert-coord2")
        self.assertEqual(z["alarms"], 0)
        self.assertEqual(z["ci_low"], 0.0)
        self.assertIsNotNone(z["zero_bound"])
        self.assertIn("No real benign", a["caveat"])

    def test_cost_curve_points_defaults_and_budgets(self):
        c = earlywarn.cost_curve(self.runs())
        fam = {f["id"]: f for f in c["families"]}
        self.assertEqual(set(fam), {f["id"] for f in earlywarn.FAMILIES})
        self.assertEqual([p["value"] for p in fam["coord"]["points"]], [1, 2, 3, 4, 5])
        self.assertEqual([p["value"] for p in fam["volume"]["points"]], [2, 3, 4, 5])
        self.assertEqual([p["value"] for p in fam["watch"]["points"] if p["default"]], [1])
        self.assertEqual([p["value"] for p in fam["coord"]["points"] if p["default"]], [2])
        self.assertEqual([p["value"] for p in fam["volume"]["points"] if p["default"]], [3])
        w1 = fam["watch"]["points"][0]
        self.assertEqual(w1["false_alarms"], 1)
        self.assertEqual(w1["median_lead_h"], 1.0)
        self.assertEqual(w1["fired"], 4)
        v4 = fam["volume"]["points"][2]
        self.assertEqual((v4["fired"], v4["median_lead_h"]), (0, None))
        self.assertTrue(all(isinstance(f["advice"], str) and f["advice"] for f in c["families"]))
        zero = c["budgets"][0]
        self.assertEqual(zero["budget_per_24h"], 0.0)
        self.assertEqual(zero["best"]["family"], "place")                        # the quiet family with the most lead

    def test_advice_names_negative_lead_as_after(self):
        f = {"id": "x", "name": "X", "param": "k"}
        pts = [{"value": 1, "false_alarms": 0, "per_24h": 0.0, "zero_bound": 0.07, "median_lead_h": -3.0, "fired": 5, "coordinated": 5, "detect": 1.0}]
        self.assertIn("3.0 h after the first true harm", earlywarn._advice(f, pts))


class TestRun(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["SWARM_TRACER_NO_CACHE"] = "1"
        os.environ["SWARM_TRACER_EARLYWARN_DIR"] = self.dir

    def tearDown(self):
        os.environ.pop("SWARM_TRACER_EARLYWARN_DIR", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_forward_runs_and_is_served(self):
        sm = earlywarn.run_forward(self.dir, seeds=(21,), settings=["small", "benign"], wiki=False, samples=False, log=lambda *_: None)
        self.assertEqual(sm["forward"]["coordinated_runs"], 1)
        self.assertEqual(sm["forward"]["benign_runs"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "forward.json")))
        got = earlywarn._summary({}, {})
        self.assertTrue(got["ran"])
        self.assertNotIn("runs", got)

    def test_summary_before_any_run_says_so(self):
        got = earlywarn._summary({}, {})
        self.assertFalse(got["ran"])
        self.assertIn("earlywarn forward", got["command"])

    def test_quick_run_never_overwrites_the_full_one(self):
        with open(os.path.join(self.dir, "forward.json"), "w") as f:
            json.dump({"seeds": [21, 22], "marker": "full"}, f)
        earlywarn.run_forward(self.dir, seeds=(21,), settings=["small"], wiki=False, samples=False, log=lambda *_: None, fname="forward_quick.json")
        self.assertEqual(earlywarn.latest(self.dir)["marker"], "full")

    def test_your_own_trace_gives_the_same_table(self):
        p = os.path.join(os.path.dirname(HERE), "samples", "benign_swarm", "benign_swarm.jsonl")
        out = os.path.join(self.dir, "mine")
        res = earlywarn.run_trace(p, "code_traces.json", out)
        self.assertTrue(res["declared_benign"])
        self.assertGreater(res["agent_hours"], 0)
        self.assertEqual({r["id"] for r in res["if_benign"]["rows"] if r["kind"] == "rule"}, {"watch-harm", "alert-coord2", "baseline-volume"})
        self.assertTrue(os.path.exists(os.path.join(out, "earlywarn.json")))
        self.assertIn("you decide", res["note"])

    def test_release_endpoint_needs_a_dataset(self):
        with self.assertRaises(LookupError):
            earlywarn._release({}, {})

    def test_release_endpoint_on_a_loaded_session(self):
        from agenttrace.session import Session
        s = Session()
        s.load(os.path.join(os.path.dirname(HERE), "samples", "demo_swarm", "demo_swarm.jsonl"), "code_traces.json", {}, "demo")
        r = earlywarn._release({"session": s}, {})
        self.assertTrue(r["no_truth"])
        self.assertEqual({x["id"] for x in r["rules"]}, {"watch-harm", "alert-coord2", "baseline-volume"})
        self.assertEqual([p["value"] for p in next(f for f in r["families"] if f["id"] == "coord")["points"]], [1, 2, 3, 4, 5])

    def test_run_endpoint_needs_an_explicit_request(self):
        with self.assertRaises(ValueError):
            earlywarn._run_post({}, {}, b"{}")
        with self.assertRaises(ValueError):
            earlywarn._run_post({}, {}, b"not json")

    def test_cli_freeze_check(self):
        self.assertEqual(earlywarn.main(["freeze", "--check"]), 0)


class TestUi(unittest.TestCase):
    def test_sections_registered_and_nothing_hard_coded(self):
        with open(os.path.join(APP, "fx_earlywarn.js"), encoding="utf-8") as f:
            js = f.read()
        for sid, title in (("earlywarn", "Frozen signs"), ("ew_forward", "Forward test"), ("ew_false", "False alarms"),
                           ("ew_cost", "Cost curve"), ("ew_online", "Online mode")):
            self.assertIn(f'id: "{sid}", title: "{title}"', js)
        self.assertNotRegex(js, r"189,?579|\bonclick=|\bonchange=")
        with open(os.path.join(os.path.dirname(APP), "index.html"), encoding="utf-8") as f:
            self.assertIn("fx_earlywarn.js", f.read())

    def test_every_family_has_a_colour(self):
        with open(os.path.join(APP, "fx_earlywarn.js"), encoding="utf-8") as f:
            js = f.read()
        for fam in earlywarn.FAMILIES:
            self.assertRegex(js, r"\b%s: \"#[0-9a-f]{6}\"" % fam["id"])


if __name__ == "__main__":
    unittest.main()

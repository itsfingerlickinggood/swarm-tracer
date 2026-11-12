"""Forensics, coordination without messages: synchrony, adoption, split work, and the benign baseline."""
import os
import tempfile
import unittest

from agenttrace import fx_coord as fx
from agenttrace import groundtruth
from agenttrace.session import Session


def _sim(mode, agents=14, seed=2):
    d = tempfile.mkdtemp(prefix="fxk_test_")
    groundtruth.make(d, agents=agents, seed=seed, mode=mode)
    s = Session()
    s.load(os.path.join(d, "trace.jsonl"), "code_traces.json")
    return s


class PieceTests(unittest.TestCase):
    def test_co_events_are_one_to_one(self):
        xs = [(0.0, "a1"), (7200.0, "a2"), (7300.0, "a3")]
        ys = [(1800.0, "b1"), (7250.0, "b2"), (90000.0, "b3")]
        ev = []
        self.assertEqual(fx._co(xs, ys, ev, "x"), 2)
        self.assertEqual([e[2][1] for e in ev], ["a1", "a2"])

    def test_bursts_need_a_quiet_hour(self):
        rows = [(0, "scan", "r1"), (600, "scan", "r2"), (4000, "scan", "r3"), (8000, "scan", "r4"), (8100, "other", "r5"), (8200, None, "r6")]
        b = fx._bursts(rows)
        self.assertEqual([r for _, r in b["scan"]], ["r1", "r4"])
        self.assertNotIn("other", b)

    def test_poisson_tail(self):
        self.assertAlmostEqual(fx._poisson_sf(0, 2.0), 1.0)
        self.assertAlmostEqual(fx._poisson_sf(1, 1.0), 1 - 2.718281828 ** -1, places=6)
        self.assertLess(fx._poisson_sf(6, 0.4), 1e-4)

    def test_synchrony_finds_planted_pair_and_not_the_rest(self):
        import random
        rng = random.Random(5)
        acts = {}
        shared = [h * 15 * 3600.0 + rng.uniform(0, 7200) for h in range(14)]
        acts["A"] = sorted((t, "scan", f"a{i}") for i, t in enumerate(shared))
        acts["B"] = sorted((t + rng.uniform(60, 1200), "scan", f"b{i}") for i, t in enumerate(shared))
        for k in range(12):
            acts[f"N{k}"] = sorted((rng.uniform(0, 210 * 3600.0), "scan", f"n{k}_{i}") for i in range(10))
        out, meta, _ = fx._synchrony(acts)
        self.assertTrue(out[("A", "B")]["link"])
        self.assertGreaterEqual(out[("A", "B")]["co_events"], 12)
        self.assertEqual([k for k, v in out.items() if v["link"]], [("A", "B")])
        self.assertGreater(meta["pairs_tested"], 50)


class SimulatedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benign = _sim("benign")
        cls.coord = _sim("coordinated")

    def test_no_session(self):
        with self.assertRaises(LookupError):
            fx.GET["silent"]({"session": None}, {})

    def test_shape(self):
        r = fx.GET["silent"]({"session": self.coord}, {})
        sm = r["summary"]
        for k in ("links", "behaviour_only", "with_message", "same_agent", "new", "tested", "thresholds", "simulated"):
            self.assertIn(k, sm)
        self.assertEqual(sm["links"], sm["behaviour_only"] + sm["with_message"])
        self.assertEqual(len(r["links"]), min(150, sm["links"]))
        for c in r["cascades"]:
            self.assertGreaterEqual(c["in_cascade"], 3)
            self.assertIn("p", c)

    def test_baselines_are_quiet(self):
        # neither simulated swarm plans timing, adoption order or a split of work
        for s in (self.benign, self.coord):
            sm = fx.summary(s)
            self.assertLessEqual(sm["links"] - sm["same_agent"], 1)
            self.assertEqual(sm["cascades"], 0)

    def test_pair(self):
        s = self.coord
        names = sorted(fx.build(s)["acts"])
        d = fx.GET["silent_pair"]({"session": s}, {"a": names[0], "b": names[1]})
        self.assertEqual(set(d["rows"]), {names[0], names[1]})
        self.assertTrue(d["rows"][names[0]]["hours"])
        with self.assertRaises(ValueError):
            fx.GET["silent_pair"]({"session": s}, {"a": names[0]})
        with self.assertRaises(LookupError):
            fx.GET["silent_pair"]({"session": s}, {"a": names[0], "b": "nobody"})


if __name__ == "__main__":
    unittest.main()

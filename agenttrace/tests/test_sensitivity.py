"""Gap sensitivity, the insiders' findings, what to collect next."""
import json
import os
import tempfile
import unittest

from agenttrace import extensions, groundtruth, identity, sensitivity as sx
from agenttrace.session import Session


class SensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._save = identity.SAVE_DECISIONS
        identity.SAVE_DECISIONS = False
        d = tempfile.mkdtemp()
        t = groundtruth.make(d, agents=24, seed=2)
        cls.s = Session()
        cls.s.load(os.path.join(d, "trace.jsonl"), t["pack"], {}, "sens-test.jsonl")
        cls.r = sx.compute(cls.s)

    @classmethod
    def tearDownClass(cls):
        identity.SAVE_DECISIONS = cls._save

    def test_registered(self):
        get, _ = extensions.routes()
        for k in ("sensitivity", "sensitivity_gap", "insiders", "collect_next"):
            self.assertIn(k, get)

    def test_every_gap_present_and_ranges_bracket_as_counted(self):
        self.assertTrue(self.r["available"])
        keys = [g["key"] for g in self.r["gaps"]]
        self.assertEqual(sorted(keys), sorted(k for k, _, _ in sx.GAPS))
        for g in self.r["gaps"]:
            for k, x in g["ranges"].items():
                if x["lo"] is not None:
                    self.assertLessEqual(x["lo"], x["hi"])
        for g in self.r["gaps"]:
            if g["key"] in ("merged", "reasoning"):
                continue
            m = g["ranges"].get("messages")
            if m and m["base"] is not None:
                self.assertLessEqual(m["lo"], m["base"])
                self.assertGreaterEqual(m["hi"], m["base"])

    def test_cached_and_single_gap(self):
        self.assertIs(sx.compute(self.s), self.r)
        self.assertEqual(sx.sensitivity_gap(self.s, "time")["gap"]["key"], "time")
        with self.assertRaises(LookupError):
            sx.sensitivity_gap(self.s, "nope")

    def test_reasoning_is_not_computable(self):
        g = next(x for x in self.r["gaps"] if x["key"] == "reasoning")
        self.assertFalse(g["computable"])

    def test_success_never_adds_messages(self):
        g = next(x for x in self.r["gaps"] if x["key"] == "success")
        base = g["scenarios"][0]["values"]["messages"]
        self.assertTrue(all(x["values"]["messages"] <= base for x in g["scenarios"]))

    def test_the_order_of_the_deliveries_does_not_change_any_scenario(self):
        import random
        s = self.s
        dels = list(s.flow["_deliveries"])
        harm = sorted(s.rec["_times"][r] for r in s.harmful if r in s.rec["_times"])
        want = sx._named_deliveries(sx._View(s, dels, harm), {}, "asis")[0]
        self.assertGreater(len(want), 10)
        rng = random.Random(3)
        for _ in range(5):
            mixed = dels[:]
            rng.shuffle(mixed)
            got = sx._named_deliveries(sx._View(s, mixed, harm), {}, "asis")[0]
            self.assertEqual([(x[0], x[1]["write_id"], x[1]["read_id"]) for x in got], [(x[0], x[1]["write_id"], x[1]["read_id"]) for x in want])
        # the failed-reads scenario drops messages by a seeded draw over that list: the same set of messages gives
        # the same means, whatever order the deliveries arrived in
        a = [x["values"] for x in sx._gap_success(s, sx._values(s, s.rec["_times"], dels=dels))[0]]
        mixed = dels[:]
        rng.shuffle(mixed)
        b = [x["values"] for x in sx._gap_success(s, sx._values(s, s.rec["_times"], dels=mixed))[0]]
        self.assertEqual(a, b)
        self.assertEqual(len(a), len(sx.SUCCESS_P))

    def test_mean_is_exact_and_order_free(self):
        xs = [0.1] * 10 + [1e16, -1e16, 3.3]
        self.assertEqual(sx._mean(xs, 6), sx._mean(list(reversed(xs)), 6))
        self.assertEqual(sx._mean(xs, 6), round(4.3 / 13, 6))
        self.assertIsNone(sx._mean([]))

    def test_insiders_not_applicable_here(self):
        self.assertFalse(sx.insiders(self.s)["available"])

    def test_insider_file_is_well_formed(self):
        with open(sx.INSIDERS) as fh:
            spec = json.load(fh)
        ids = [f["id"] for f in spec["findings"]]
        self.assertEqual(len(ids), len(set(ids)))
        for f in spec["findings"]:
            self.assertTrue(f["source"] and f["finding"] and f["check"]["kind"])
            if f["check"]["kind"] == "static":
                self.assertIn(f["check"]["status"], ("recovered", "partly", "invisible"))

    def test_collect_next_orders_and_sizes(self):
        c = sx.collect_next(self.s)
        self.assertEqual([x["priority"] for x in c["items"]], list(range(1, len(c["items"]) + 1)))
        self.assertEqual(c["items"][-1]["id"], "reasoning")


if __name__ == "__main__":
    unittest.main()

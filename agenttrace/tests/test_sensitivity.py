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

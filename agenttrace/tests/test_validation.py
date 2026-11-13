import json
import os
import shutil
import tempfile
import unittest

from agenttrace import groundtruth, validation


class TestBenignMake(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_benign_truth_has_no_messages_or_harm(self):
        t = groundtruth.make(self.dir, agents=20, seed=1, mode="benign", two_token_share=0.3)
        self.assertEqual(t["mode"], "benign")
        self.assertEqual(t["messages"], [])
        self.assertEqual(t["harm"], [])
        self.assertTrue(all(r.startswith("B") for r in t["records"]))
        # no agent ever reads a place another agent wrote
        writer = {}
        for r, x in t["records"].items():
            if x["do"] == "own_write":
                writer[x["place"]] = x["agent"]
        for r, x in t["records"].items():
            if x["do"] == "own_read":
                self.assertEqual(writer.get(x["place"], x["agent"]), x["agent"])
        with open(os.path.join(self.dir, "trace.jsonl")) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual(len(rows), len(t["records"]))

    def test_no_notes_when_share_is_zero(self):
        t = groundtruth.make(self.dir, agents=20, seed=3, mention_share=0.0)
        self.assertFalse(any(x["do"] == "mention" for x in t["records"].values()))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            groundtruth.make(self.dir, agents=20, mode="chaos")


class TestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.sm = validation.run_suite(cls.dir, seeds=(1,), quick=True, settings=["base", "field_times", "benign"],
                                      log=lambda *_: None, keep_swarms=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_files_written(self):
        for f in ("summary.json", "summary.md"):
            self.assertTrue(os.path.isfile(os.path.join(self.dir, f)))
        with open(os.path.join(self.dir, "summary.md")) as f:
            md = f.read()
        self.assertIn("Benign baseline", md)
        self.assertIn("Identity merge proposals", md)

    def test_measures_and_ranges(self):
        sm = self.sm
        self.assertEqual(sm["coordinated_runs"], 2)
        self.assertEqual(sm["benign_runs"], 1)
        base = next(x for x in sm["settings"] if x["name"] == "base")
        r = base["measures"]["msg_recall"]
        self.assertTrue(0 < r["median"] <= 1 and r["min"] <= r["median"] <= r["max"])
        self.assertIsNotNone(base["measures"]["dating_coverage"])
        field = next(x for x in sm["settings"] if x["name"] == "field_times")
        self.assertIsNone(field["measures"]["dating_error_h"])   # nothing estimated when every record has a time
        for b in ("high", "medium", "low", "direct_rule"):
            self.assertIn(b, sm["identity_pooled"])

    def test_message_precision_per_grade(self):
        mg = self.sm["message_grades"]
        for part in ("all", "realworld"):
            for g in ("direct", "inferred", "weak"):
                x = mg[part][g]
                self.assertLessEqual(x["correct"], x["found"])
                if x["found"]:
                    self.assertTrue(0 <= x["precision_ci"][0] <= x["precision"] <= x["precision_ci"][1] <= 1)
        run = next(r for r in self.sm["runs"] if r["setting"] == "base")
        found = sum(x["found"] for x in run["counts"]["by_grade"].values())
        self.assertEqual(found, run["counts"]["messages_found"])
        self.assertEqual(sum(mg["all"][g]["found"] for g in ("direct", "inferred", "weak")),
                         sum(r["counts"]["messages_found"] for r in self.sm["runs"] if r["mode"] != "benign"))
        with open(os.path.join(self.dir, "summary.md")) as f:
            self.assertIn("Message precision by confidence grade", f.read())

    def test_benign_reports_what_fires(self):
        b = self.sm["benign"]
        self.assertEqual(b["runs"], 1)
        run = next(r for r in self.sm["runs"] if r["mode"] == "benign")
        self.assertEqual(run["true_messages"], 0)
        self.assertEqual(run["benign"]["messages_between_agents"], 0)
        self.assertEqual({x["id"] for x in run["benign"]["rules"]}, {"watch-harm", "alert-coord2", "baseline-volume"})
        rules = [x for x in b["fires"] if x["what"] == "rule"]
        self.assertEqual(len(rules), 3)
        for x in b["fires"]:
            self.assertLessEqual(x["runs"], x["of"])

    def test_endpoint_reads_latest(self):
        old = os.environ.get("SWARM_TRACER_VALIDATION_DIR")
        os.environ["SWARM_TRACER_VALIDATION_DIR"] = self.dir
        try:
            os.utime(os.path.join(self.dir, "summary.json"))   # newest of the candidate locations
            res = validation.GET["validation_summary"]({}, {})
            self.assertTrue(res["available"])
            self.assertNotIn("runs", res)
            self.assertEqual(res["benign_runs"], 1)
        finally:
            if old is None:
                os.environ.pop("SWARM_TRACER_VALIDATION_DIR", None)
            else:
                os.environ["SWARM_TRACER_VALIDATION_DIR"] = old

    def test_registered(self):
        from agenttrace import extensions
        get, post = extensions.routes()
        self.assertIn("validation_summary", get)
        self.assertIn("validation_run", post)


class TestBenignSample(unittest.TestCase):
    def test_sample_has_truth(self):
        d = os.path.join(os.path.dirname(validation.__file__), "samples", "benign_swarm")
        p = groundtruth.truth_path_for(d)
        self.assertIsNotNone(p)
        t = groundtruth.load_truth(p)
        self.assertEqual(t["mode"], "benign")
        self.assertEqual(t["messages"], [])


if __name__ == "__main__":
    unittest.main()

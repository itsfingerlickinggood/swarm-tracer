"""Case file, in-app labels, time ranges and the ground-truth test mode."""
import json
import os
import shutil
import tempfile
import unittest

from agenttrace import casework, groundtruth, labels
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self._old = os.environ.get("SWARM_TRACER_HOME")
        os.environ["SWARM_TRACER_HOME"] = self.home

    def tearDown(self):
        if self._old is None:
            os.environ.pop("SWARM_TRACER_HOME", None)
        else:
            os.environ["SWARM_TRACER_HOME"] = self._old
        shutil.rmtree(self.home, ignore_errors=True)


class TestGroundTruth(_Home):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.truth = groundtruth.make(cls.dir, agents=24, seed=2)
        cls.s = Session()
        cls.s.load(os.path.join(cls.dir, "trace.jsonl"), cls.truth["pack"], {}, "gt-test.jsonl")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_make_writes_trace_and_truth(self):
        self.assertTrue(os.path.exists(os.path.join(self.dir, "trace.jsonl.truth")))
        self.assertEqual(len(self.truth["agents"]), 24)
        self.assertTrue(self.truth["messages"])
        for w, r, p in self.truth["messages"][:20]:
            self.assertLessEqual(self.truth["records"][w]["t"], self.truth["records"][r]["t"])
            self.assertNotEqual(self.truth["records"][w]["agent"], self.truth["records"][r]["agent"])
        # deterministic for a seed
        d2 = tempfile.mkdtemp()
        try:
            t2 = groundtruth.make(d2, agents=24, seed=2)
            self.assertEqual(t2["messages"], self.truth["messages"])
        finally:
            shutil.rmtree(d2, ignore_errors=True)

    def test_score(self):
        sc = groundtruth.score(self.s, self.truth)
        m = sc["messages"]
        self.assertEqual(m["true"], len(self.truth["messages"]))
        self.assertGreater(m["correct"], 0)
        self.assertTrue(0 < m["precision"] <= 1 and 0 < m["recall"] <= 1)
        # every false positive and miss is explained, and the explanations add up
        self.assertEqual(sum(x["n"] for x in m["false_positives"]), m["found"] - m["correct"])
        self.assertEqual(sum(x["n"] for x in m["missed"]), m["true"] - m["correct"])
        self.assertIn("pairs", sc)
        self.assertGreater(sc["dating"]["estimated"], 0)
        self.assertTrue(sc["early_signs"]["signs"])
        self.assertIn("message", {r["key"] for r in sc["early_signs"]["signs"]})
        self.assertEqual(sc["identity"]["agents"], 24)
        self.assertIn("Messages", groundtruth.report_text(sc))

    def test_cli_score(self):
        res = groundtruth.load_and_score(self.dir)
        self.assertEqual(res["true_messages"], len(self.truth["messages"]))

    def test_field_mode(self):
        d = tempfile.mkdtemp()
        try:
            t = groundtruth.make(d, agents=8, seed=5, time_mode="field", name="x.jsonl")
            sc = groundtruth.load_and_score(d)
            self.assertEqual(sc["dating"]["estimated"], 0)
            self.assertEqual(sc["true_messages"], len(t["messages"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_endpoint_finds_truth_next_to_the_trace(self):
        st = {"session": self.s}
        self.s._cw_source = os.path.join(self.dir, "trace.jsonl")
        self.s._cw_gt = None
        r = casework.get_groundtruth_score(st, {})
        self.assertTrue(r["available"])
        self.assertEqual(r["truth_file"], "trace.jsonl.truth")

    def test_truth_upload_must_match(self):
        sess = Session()
        d = tempfile.mkdtemp()
        try:
            sess.load(write_trace(d), "generic.json")
            with self.assertRaises(ValueError):
                casework.post_groundtruth_truth({"session": sess}, {}, json.dumps(self.truth).encode())
            r = casework.get_groundtruth_score({"session": sess}, {})
            self.assertFalse(r["available"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_time_range(self):
        est = [e.id for e in self.s.events if not e.time and e.id in self.s.rec["_times"] and e.kind == "payload"]
        self.assertTrue(est)
        r = casework.time_range(self.s, est[len(est) // 2])
        self.assertEqual(r["source"], "estimated")
        self.assertLessEqual(r["low"], r["time"])
        self.assertLessEqual(r["time"], r["high"])
        self.assertRegex(r["text"], r"^estimated \d\d:\d\d \(likely .+–.+\)$")
        with self.assertRaises(LookupError):
            casework.time_range(self.s, "nope")


class TestCaseFile(_Home):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_trace(cls.dir), "generic.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_unloaded(self):
        with self.assertRaises(LookupError):
            casework.get_case({"session": Session()}, {})

    def test_roundtrip_and_validation(self):
        st = {"session": self.s}
        self.assertEqual(casework.get_case(st, {})["case"]["items"], [])
        actor = self.s.actor["M0001"][0]
        body = {"title": "My case", "notes": "first look", "items": [
            {"kind": "record", "key": "M0005", "note": "the post"},
            {"kind": "record", "key": "M0005", "note": "duplicate"},
            {"kind": "actor", "key": actor},
            {"kind": "conversation", "key": "agent-0|agent-1"}]}
        r = casework.post_case(st, {}, json.dumps(body).encode())
        self.assertEqual(len(r["case"]["items"]), 3)
        self.assertTrue(os.path.exists(casework.case_path(self.s)))
        self.assertTrue(r["path"].startswith(self.home))
        again = casework.get_case(st, {})["case"]
        self.assertEqual(again["title"], "My case")
        self.assertEqual(again["items"][0]["note"], "the post")
        with self.assertRaises(ValueError):
            casework.post_case(st, {}, json.dumps({"items": [{"kind": "nope", "key": "x"}]}).encode())
        with self.assertRaises(ValueError):
            casework.post_case(st, {}, b"not json")

    def test_export(self):
        st = {"session": self.s}
        place = self.s.op_list[0][0] if self.s.op_list else None
        items = [{"kind": "record", "key": "M0005", "note": "look <here>"}, {"kind": "record", "key": "GONE"}]
        if place:
            items.append({"kind": "place", "key": place})
        casework.post_case(st, {}, json.dumps({"notes": "Notes & thoughts", "items": items}).encode())
        h = casework.get_case_export(st, {"format": "html", "base": "http://127.0.0.1:8010/"})
        self.assertTrue(h["filename"].endswith(".html"))
        html = h["html"]
        self.assertIn("<style>", html)
        self.assertIn("M0005", html)
        self.assertIn("look &lt;here&gt;", html)
        self.assertIn("Notes &amp; thoughts", html)
        self.assertIn("Warning signs", html)
        self.assertIn("Not in this dataset", html)
        self.assertIn("#tab=", html)
        j = casework.get_case_export(st, {"format": "json"})["dossier"]
        self.assertEqual(j["items"][0]["facts"]["kind"], "record")
        self.assertTrue(j["key_numbers"])
        with self.assertRaises(ValueError):
            casework.get_case_export(st, {"format": "pdf"})

    def test_time_range_field(self):
        r = casework.time_range(self.s, "M0003")
        self.assertEqual(r["source"], "time field")

    def test_labels(self):
        st = {"session": self.s}
        r = casework.post_label(st, {}, json.dumps({"id": "M0005", "tag": "sends_data", "label": "1"}).encode())
        self.assertEqual(r["total"], 1)
        casework.post_label(st, {}, json.dumps({"id": "M0010", "tag": "sends_data", "label": "0"}).encode())
        casework.post_label(st, {}, json.dumps({"id": "M0015", "tag": "sends_data", "label": "?"}).encode())
        casework.post_label(st, {}, json.dumps({"id": "M0005>M0007", "tag": "message", "label": "1"}).encode())
        # changing a label replaces it
        casework.post_label(st, {}, json.dumps({"id": "M0010", "tag": "sends_data", "label": "1"}).encode())
        p = casework.get_precision(st, {})
        self.assertEqual(p["labels"], 4)
        row = next(x for x in p["rows"] if x["tag"] == "sends_data")
        self.assertEqual((row["tp"], row["fp"], row["unclear"]), (2, 0, 1))
        self.assertLess(row["ci_low"], 1.0)
        # the file is the CSV labels.precision reads
        self.assertIn("sends_data", labels.precision(casework.labels_path(self.s))["tags"])
        got = casework.get_labels(st, {"id": "M0005"})
        self.assertEqual({(x["tag"], x["label"]) for x in got["labels"]}, {("sends_data", "1"), ("message", "1")})
        # clearing removes the row
        casework.post_label(st, {}, json.dumps({"id": "M0015", "tag": "sends_data", "label": ""}).encode())
        self.assertEqual(casework.get_precision(st, {})["labels"], 3)
        with self.assertRaises(ValueError):
            casework.post_label(st, {}, json.dumps({"id": "M0005", "tag": "x", "label": "yes"}).encode())
        with self.assertRaises(LookupError):
            casework.post_label(st, {}, json.dumps({"id": "NOPE", "tag": "x", "label": "1"}).encode())

    def test_routes_registered(self):
        from agenttrace import extensions
        get, post = extensions.routes()
        for k in ("case", "case_export", "time_range", "labels", "precision", "groundtruth_score"):
            self.assertIn(k, get)
        for k in ("case", "label", "groundtruth_truth"):
            self.assertIn(k, post)


class TestDemoSample(unittest.TestCase):
    def test_demo_swarm_has_truth(self):
        d = os.path.join(os.path.dirname(casework.__file__), "samples", "demo_swarm")
        p = groundtruth.truth_path_for(d)
        self.assertIsNotNone(p)
        t = groundtruth.load_truth(p)
        self.assertTrue(os.path.exists(os.path.join(d, t["trace"])))


if __name__ == "__main__":
    unittest.main()

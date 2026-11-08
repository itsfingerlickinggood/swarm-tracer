"""Tests for agenttrace on small synthetic data.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -v
"""
import csv
import json
import os
import tempfile
import unittest

from agenttrace import analysis, labels, model, packs, report

PACK = {
    "name": "test",
    "behaviors": [
        {"name": "post", "stage": "exfiltration", "pattern": "POST"},
        {"name": "generic", "stage": "execution", "pattern": "innerHTML", "context": True},
        {"name": "shell", "stage": "execution", "pattern": "uname -a"},
    ],
    "shared_names": [{"family": "board", "pattern": "zz[A-Z_]+"}],
    "handles": ["C5", "OTS92"],
    "handle_families": {"C5": "C5", "OTS92": "OTS92"},
}


def write_pack(d):
    p = os.path.join(d, "pack.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(PACK, f)
    return packs.load_pack(p)


def write_csv(d, rows, header):
    p = os.path.join(d, "in.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    return p


ROWS = [
    {"msg_id": "a1", "body": "C5 POST zzBOARD_X", "sender": "C5", "reply_to": "", "sent_at": "2026-11-01T10:00:00Z"},
    {"msg_id": "a2", "body": "reply: stored zzBOARD_X", "sender": "", "reply_to": "a1", "sent_at": ""},
    {"msg_id": "b1", "body": "OTS92 read zzBOARD_X", "sender": "OTS92", "reply_to": "", "sent_at": "2026-11-01T10:05:00Z"},
    {"msg_id": "c1", "body": "uname -a and innerHTML", "sender": "C5", "reply_to": "", "sent_at": ""},
    {"msg_id": "d1", "body": "the word C50 is not a handle", "sender": "", "reply_to": "", "sent_at": ""},
]


class ModelTests(unittest.TestCase):
    def test_alias_columns_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_csv(d, ROWS, list(ROWS[0].keys()))
            ev = model.load(path)
            self.assertEqual(ev[0].id, "a1")
            self.assertEqual(ev[0].actor, "C5")
            self.assertEqual(ev[1].parent, "a1")
            self.assertIsNotNone(ev[0].time)
            self.assertIsNone(ev[1].time)

    def test_explicit_map_overrides_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_csv(d, ROWS, list(ROWS[0].keys()))
            ev = model.load(path, {"text": "sender"})
            self.assertEqual(ev[0].text, "C5")

    def test_missing_id_and_text_are_filled_in(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_csv(d, [{"x": "1", "y": "2"}], ["x", "y"])
            ev = model.load(path)
            self.assertEqual(ev[0].id, "in:1")              # file stem and line
            self.assertIn('"x": "1"', ev[0].text)           # the record's fields become its text
            self.assertTrue(ev[0].text_from_fields)

    def test_jsonl_nested_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": "j1", "meta": {"agent": "C5"}, "content": "POST"}) + "\n")
                f.write(json.dumps({"id": "j2", "meta": {"agent": "C5"}, "content": "ok"}) + "\n")
            ev = model.load(p, {"actor": "meta.agent"})
            self.assertEqual(ev[0].actor, "C5")
            self.assertEqual(ev[1].text, "ok")

    def test_unix_seconds_time(self):
        self.assertIsNotNone(model.parse_time(1783815200))
        self.assertIsNone(model.parse_time("not a time"))


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.pack = write_pack(cls.d)
        path = write_csv(cls.d, ROWS, list(ROWS[0].keys()))
        cls.events = model.load(path)
        cls.res = analysis.analyze(cls.events, cls.pack)

    def test_evidence_and_context_are_separate(self):
        self.assertIn("post", self.res["_evidence"]["a1"])
        self.assertNotIn("generic", self.res["_evidence"]["c1"])
        self.assertIn("generic", self.res["_context"]["c1"])
        self.assertIn("shell", self.res["_evidence"]["c1"])

    def test_handle_needs_clean_boundary(self):
        self.assertEqual(self.res["_attr"]["d1"], None)  # "C50" must not attribute to C5

    def test_thread_root_follows_parent(self):
        self.assertEqual(self.res["_root"]["a2"], "a1")

    def test_child_inherits_actor_from_thread(self):
        self.assertEqual(self.res["_attr"]["a2"], "C5")

    def test_shared_name_gives_edge_between_actors(self):
        pairs = {(a, b) for a, b, _, _ in self.res["actor_edges"]}
        self.assertIn(("C5", "OTS92"), pairs)

    def test_reply_edges_only_between_different_actors(self):
        self.assertEqual(self.res["reply_edges"], [])  # a2 inherits C5 from a1

    def test_gaps_are_counted(self):
        self.assertGreaterEqual(self.res["gaps"]["no_time"], 1)
        self.assertEqual(self.res["gaps"]["no_parent"], 4)

    def test_report_renders_and_escapes(self):
        html_text = report.render(self.res, "test", "<script>x</script>")
        self.assertNotIn("<script>x</script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)


class LabelTests(unittest.TestCase):
    def test_precision_and_controls(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "labels.csv")
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["id", "tag", "preview", "label"])
                w.writerow(["a", "post", "", "1"])
                w.writerow(["b", "post", "", "1"])
                w.writerow(["c", "post", "", "0"])
                w.writerow(["d", "post", "", ""])
                w.writerow(["e", "control", "", "1"])
                w.writerow(["f", "control", "", "0"])
            out = labels.precision(p)
            t = out["tags"]["post"]
            self.assertEqual((t["tp"], t["fp"], t["unclear"]), (2, 1, 1))
            self.assertAlmostEqual(t["precision"], 2 / 3)
            self.assertEqual(out["controls"]["missed"], 1)
            self.assertAlmostEqual(out["controls"]["miss_rate"], 0.5)

    def test_wilson_interval_bounds(self):
        lo, hi = labels.wilson(5, 10)
        self.assertTrue(0 < lo < 0.5 < hi < 1)


if __name__ == "__main__":
    unittest.main()

"""Comparing two swarms, the library of past incidents, the disk cache, and the AI report mode."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from agenttrace import ai, cache, compare
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


def write_trace_b(d):
    """A second, different swarm: four actors, every one writing to and reading a shared board."""
    import csv
    rows = []
    for i in range(40):
        body = (f"posting notes to https://board.example.org/room method: 'POST'" if i % 2 == 0
                else "reading https://board.example.org/room for news")
        rows.append({"id": f"B{i:04d}", "sender": f"bot-{i % 4}", "reply_to": "", "sent_at": f"2026-10-01T{8 + i // 20:02d}:{(i * 3) % 60:02d}:00Z",
                     "body": body})
    p = os.path.join(d, "other.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


class CompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, {"SWARM_TRACER_NO_CACHE": "1"})
        cls.env.start()
        cls.d = tempfile.mkdtemp()
        cls.a_path, cls.b_path = write_trace(cls.d), write_trace_b(cls.d)
        cls.a = Session()
        cls.a.load(cls.a_path, "generic.json", {"text": "body"})
        cls.state = {"session": cls.a}

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_measures_shape(self):
        m = compare.measures(self.a)
        self.assertEqual(m["records"], 30)
        self.assertEqual(m["dated_share"], 1.0)
        self.assertEqual(m["named_actors"], 3)
        for k in ("messages_named", "messages_named_exact", "messages_named_merged", "pairs", "largest_group", "wait_median_h",
                  "wait_p90_h", "two_way_share", "programs_shared", "adoption_median_h", "first_sign", "volume_alarm", "curve", "gaps",
                  "places_by_type"):
            self.assertIn(k, m)
        self.assertEqual(m["messages_named"], m["messages_named_exact"] + m["messages_named_merged"])
        self.assertIn("joint", m["first_sign"])
        for h, v in m["curve"]:
            self.assertTrue(0 <= v <= 1)
        json.dumps(m)

    def test_compare_two_traces(self):
        r = compare.api_compare(self.state, {})
        self.assertIsNone(r["b"])
        out = compare.api_load(self.state, {}, json.dumps({"path": self.b_path, "pack": "generic.json"}).encode())
        self.assertTrue(out["loaded"])
        r = compare.api_compare(self.state, {})
        self.assertEqual(r["a"]["records"], 30)
        self.assertEqual(r["b"]["records"], 40)
        self.assertGreaterEqual(r["b"]["named_actors"], 2)
        self.assertTrue(r["differences"])
        self.assertTrue(all(isinstance(d["text"], str) and d["text"] for d in r["differences"]))
        self.assertTrue(compare.api_state(self.state, {})["loaded"])
        compare.api_clear(self.state, {}, b"")
        self.assertIsNone(compare.api_compare(self.state, {})["b"])

    def test_bad_path(self):
        with self.assertRaises(ValueError):
            compare.api_load(self.state, {}, json.dumps({"path": os.path.join(self.d, "missing.csv")}).encode())

    def test_needs_main_dataset(self):
        with self.assertRaises(LookupError):
            compare.api_compare({"session": Session()}, {})

    def test_differences_words(self):
        a = compare.measures(self.a)
        b = dict(a, name="big", records=a["records"] * 10, two_way_share=(a["two_way_share"] or 0) + 0.5)
        texts = " ".join(d["text"] for d in compare.differences(a, b))
        self.assertIn("10.0x the records", texts)
        self.assertIn("both ways", texts)

    def test_library(self):
        lib = compare.library()
        ids = {e["id"] for e in lib["entries"]}
        self.assertTrue({"swarm_traces", "collusion_wiki", "demo_swarm"} <= ids)
        for e in lib["entries"]:
            for k in ("title", "description", "source_url", "paths", "pack", "available"):
                self.assertIn(k, e)
        st = next(e for e in lib["entries"] if e["id"] == "swarm_traces")
        self.assertTrue(st["context_available"])
        with self.assertRaises(ValueError):
            compare.library_entry("nope")

    def test_library_paths_resolve(self):
        p = os.path.join(self.d, "lib.json")
        with open(p, "w") as f:
            json.dump({"entries": [{"id": "x", "title": "X", "paths": ["/no/such/file", self.b_path], "pack": "generic.json"}]}, f)
        e = compare.library(p)["entries"][0]
        self.assertEqual(e["available"], os.path.abspath(self.b_path))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.d, "cache")
        self.env = mock.patch.dict(os.environ, {"SWARM_TRACER_CACHE_DIR": self.cache_dir, "SWARM_TRACER_CACHE_MIN": "0",
                                                "SWARM_TRACER_NO_CACHE": ""})
        self.env.start()
        self.path = write_trace(self.d)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.d, ignore_errors=True)

    def load(self, name=None):
        s = Session()
        s.load(self.path, "generic.json", {"text": "body"}, name)
        return s

    def test_round_trip(self):
        a = self.load()
        self.assertFalse(cache.LAST["hit"])
        self.assertEqual(len([f for f in os.listdir(self.cache_dir) if f.endswith(".pickle")]), 1)
        b = self.load()
        self.assertTrue(cache.LAST["hit"])
        self.assertTrue(b.loaded)
        self.assertEqual(json.dumps(a.summary(), sort_keys=True, default=str), json.dumps(b.summary(), sort_keys=True, default=str))
        self.assertEqual(a.trace("M0007")["id"], b.trace("M0007")["id"])
        c = self.load(name="renamed.csv")
        self.assertTrue(cache.LAST["hit"])
        self.assertEqual(c.summary()["name"], "renamed.csv")

    def test_invalidates_on_change(self):
        self.load()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("M0030,agent-0,M0029,2026-11-01T10:30:00Z,status ok\n")
        s = self.load()
        self.assertFalse(cache.LAST["hit"])
        self.assertEqual(s.summary()["records"], 31)

    def test_corrupt_cache_falls_back(self):
        self.load()
        f = os.path.join(self.cache_dir, cache.LAST["key"] + ".pickle")
        with open(f, "wb") as fh:
            fh.write(b"not a pickle")
        s = self.load()
        self.assertFalse(cache.LAST["hit"])
        self.assertEqual(s.summary()["records"], 30)

    def test_opt_out(self):
        with mock.patch.dict(os.environ, {"SWARM_TRACER_NO_CACHE": "1"}):
            self.load()
        self.assertFalse(os.path.isdir(self.cache_dir) and os.listdir(self.cache_dir))


class AIReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"SWARM_TRACER_NO_CACHE": "1"}):
            cls.s = Session()
            cls.s.load(write_trace(cls.d), "generic.json", {"text": "body"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_report_prompt(self):
        msgs, _ = ai.build_messages(self.s, [{"role": "user", "content": "Draft the incident report."}], mode="report")
        self.assertIn("Incident report format", msgs[0]["content"])
        self.assertIn('"recommendations"', msgs[0]["content"])
        self.assertIn("GAP FACTS", msgs[1]["content"])
        chat, _ = ai.build_messages(self.s, [{"role": "user", "content": "hi"}], mode="chat")
        self.assertNotIn("Incident report format", chat[0]["content"])

    def test_report_parse_and_verify(self):
        text = json.dumps({"title": "T", "summary": "S", "timeline": [{"time": "2026-11-01 10:07", "label": "first message", "ids": ["M0007", "Z99999"]}],
                           "sections": [{"heading": "What happened", "paragraphs": ["`M0000` then `Q12345` and `agent-1`"], "ids": ["M0000"]}],
                           "unknowns": "no read logs", "recommendations": ["log reads"]})
        o = ai.verify(ai.parse_answer(text), self.s)
        self.assertEqual(o["timeline"][0]["_missing"], ["Z99999"])
        self.assertEqual(o["timeline"][0]["_data_time"], "2026-11-01 10:07")
        self.assertEqual(o["sections"][0]["_inline"]["M0000"][0], "record")
        self.assertEqual(o["sections"][0]["_inline"]["agent-1"][0], "actor")
        self.assertIn("Q12345", o["_checks"]["ids_missing"])
        self.assertEqual(o["unknowns"], ["no read logs"])

    def test_empty_key_allowed_for_localhost(self):
        self.assertTrue(ai.is_local("http://localhost:11434/v1"))
        self.assertTrue(ai.is_local("http://127.0.0.1:4000/v1"))
        self.assertFalse(ai.is_local("https://api.openai.com/v1"))
        with self.assertRaises(ValueError):
            ai.call("https://api.openai.com/v1", "", "m", [{"role": "user", "content": "x"}])
        seen = {}

        def fake_post(url, payload, api_key, session_id, timeout):
            seen.update(url=url, key=api_key, max_tokens=payload["max_tokens"])
            return {"choices": [{"message": {"content": "OK"}}]}
        with mock.patch.object(ai, "_post", fake_post):
            content, _ = ai.call("http://localhost:11434/v1", "", "llama3.1", [{"role": "user", "content": "x"}])
            self.assertEqual(content, "OK")
            self.assertEqual(seen["url"], "http://localhost:11434/v1/chat/completions")
            self.assertEqual(seen["key"], "")
            self.assertEqual(seen["max_tokens"], 4096)
            ai.call("http://localhost:11434/v1", "", "llama3.1", [{"role": "system", "content": ai.system_prompt("report")}])
            self.assertEqual(seen["max_tokens"], 8192)


if __name__ == "__main__":
    unittest.main()

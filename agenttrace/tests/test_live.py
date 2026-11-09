import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from agenttrace import live
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


def rows(n0, n1):
    """Chat-like records as in write_trace: three agents posting to and reading two boards."""
    out = []
    for i in range(n0, n1):
        body = "status ok" if i % 5 else f"posting notes to https://notes.example.com/board{i % 2} method: 'POST'"
        if i == 7:
            body = "reading https://notes.example.com/board0 for the plan"
        out.append({"id": f"M{i:04d}", "sender": f"agent-{i % 3}", "reply_to": f"M{i - 1:04d}" if i else "",
                    "sent_at": f"2026-11-01T10:{i:02d}:00Z", "body": body})
    return out


def append(path, recs):
    with open(path, "a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["SWARM_TRACER_RULES"] = os.path.join(self.d, "rules.json")
        self.state = {"session": Session(), "busy": False, "error": None, "lock": threading.Lock()}
        live.LIVE.update({"events": [], "seq": 0})

    def tearDown(self):
        live.live_stop(self.state, {})
        os.environ.pop("SWARM_TRACER_RULES", None)
        shutil.rmtree(self.d, ignore_errors=True)

    def _watch(self, path):
        # set up live mode without the thread, then step it by hand
        live.LIVE.update({"path": path, "pack": "generic.json", "mapping": {"text": "body"}, "interval": 1,
                          "watching": True, "session": None, "sig": None, "pending": None, "loads": 0,
                          "error": None, "note": None, "inc": None, "incremental": None, "reanalyze_s": None,
                          "reanalyze_auto": True, "pending_records": 0, "records_read": 0, "read_offset": 0,
                          "last_analysis": 0.0, "analysis_s": None, "facts": None, "rules_now": None,
                          "rules_fp": None})

    def test_picks_up_appended_lines(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 5))
        self._watch(p)
        self.assertTrue(live.check(self.state))
        self.assertTrue(self.state["session"].loaded)
        self.assertEqual(len(self.state["session"].events), 5)
        st = live.live_status(self.state, {})
        self.assertEqual(st["records"], 5)
        self.assertTrue(st["dataset_is_live"])
        first = {e["type"] for e in st["events"]}
        self.assertIn("load", first)
        seq = st["seq"]
        # nothing changed: no reload
        self.assertFalse(live.check(self.state))
        # a half-written line is not read until it is finished
        with open(p, "a") as f:
            f.write('{"id": "M0005", "sen')
        self.assertFalse(live.check(self.state))
        with open(p, "rb+") as f:   # finish it properly
            f.seek(0, 2)
            f.truncate(f.tell() - len('{"id": "M0005", "sen'))
        append(p, rows(5, 30))
        self.assertTrue(live.check(self.state))
        self.assertEqual(len(self.state["session"].events), 30)
        st = live.live_status(self.state, {"since": seq})
        types = [e["type"] for e in st["events"]]
        self.assertIn("records", types)
        rec = next(e for e in st["events"] if e["type"] == "records")
        self.assertEqual(rec["count"], 25)
        self.assertIn("messages", types)
        signs = [e for e in st["events"] if e["type"] == "sign"]
        self.assertTrue(any(e["kind"] == "message" for e in signs))       # first message between agents, M0007
        self.assertTrue(all(not e.get("initial") for e in signs))
        alerts = [e for e in st["events"] if e["type"] == "alert"]
        self.assertTrue(any(e["rule"] == "alert-coord2" and e["record"] for e in alerts))
        # each sign is reported once
        self.assertFalse(live.check(self.state))

    def test_thread_start_and_stop(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 10))
        st = live.live_start(self.state, {}, json.dumps({"path": p, "pack": "generic.json", "interval_s": 0.2,
                                                         "map": {"text": "body"}}).encode())
        self.assertTrue(st["watching"])
        for _ in range(100):
            if live.LIVE["loads"]:
                break
            threading.Event().wait(0.1)
        self.assertEqual(live.live_status(self.state, {})["records"], 10)
        st = live.live_stop(self.state, {}, b"")
        self.assertFalse(st["watching"])

    def test_bad_start(self):
        with self.assertRaises(ValueError):
            live.live_start(self.state, {}, b"{}")
        with self.assertRaises(ValueError):
            live.live_start(self.state, {}, json.dumps({"path": "/no/such/dir/x.jsonl"}).encode())


class IncrementalLiveTests(LiveTests):
    """Live mode reads a growing JSON-lines file incrementally (only the new bytes)."""
    test_picks_up_appended_lines = test_thread_start_and_stop = test_bad_start = None

    def fresh(self, p):
        s = Session()
        s._analyze(p, "generic.json", {"text": "body"})
        return s

    def test_partial_lines_are_read_once_complete(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 5))
        self._watch(p)
        self.assertTrue(live.check(self.state))
        st = live.live_status(self.state, {})
        self.assertTrue(st["incremental"])
        self.assertEqual(st["records_read"], 5)
        self.assertEqual(st["read_offset"], os.path.getsize(p))
        # three complete lines and the start of a fourth
        append(p, rows(5, 8))
        half = json.dumps(rows(8, 9)[0])
        with open(p, "a") as f:
            f.write(half[:15])
        self.assertTrue(live.check(self.state))
        self.assertEqual(len(self.state["session"].events), 8)
        self.assertEqual(live.LIVE["read_offset"], os.path.getsize(p) - 15)   # the partial line is not consumed
        with open(p, "a") as f:
            f.write(half[15:] + "\n")
        append(p, rows(9, 12))
        self.assertTrue(live.check(self.state))
        s = self.state["session"]
        self.assertEqual([e.id for e in s.events], [f"M{i:04d}" for i in range(12)])
        # the same as analyzing the whole file afresh
        ref = self.fresh(p)
        self.assertEqual([(e.id, e.text, e.actor, e.parent) for e in s.events],
                         [(e.id, e.text, e.actor, e.parent) for e in ref.events])
        self.assertEqual(s.summary()["records"], ref.summary()["records"])
        self.assertEqual(len(s.flow["_deliveries"]), len(ref.flow["_deliveries"]))
        self.assertFalse(live.check(self.state))      # nothing new

    def test_unreadable_lines_reported_like_a_full_read(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 4))
        with open(p, "a") as f:
            f.write("not json\n\n")
        append(p, rows(4, 6))
        self._watch(p)
        self.assertTrue(live.check(self.state))
        got = self.state["session"].read_report["files"][0]
        ref = self.fresh(p).read_report["files"][0]
        self.assertEqual(got["unreadable_lines"], 1)
        self.assertEqual(got["unreadable_line_numbers"], ref["unreadable_line_numbers"])
        self.assertEqual(got["rows"], ref["rows"])

    def test_truncation_and_rotation_reload_from_start(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 10))
        self._watch(p)
        self.assertTrue(live.check(self.state))
        seq = live.LIVE["seq"]
        # truncated and rewritten with fewer, different records
        other = [dict(r, id="N" + r["id"][1:]) for r in rows(0, 3)]
        with open(p, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in other))
        self.assertTrue(live.check(self.state))
        self.assertEqual([e.id for e in self.state["session"].events], ["N0000", "N0001", "N0002"])
        evs = live.live_status(self.state, {"since": seq})["events"]
        self.assertTrue(any(e["type"] == "reset" and "truncated" in e["text"] for e in evs))
        # rotated: a new file moved into place, longer than the old one
        seq = live.LIVE["seq"]
        new = os.path.join(self.d, "new.jsonl")
        append(new, [dict(r, id="R" + r["id"][1:]) for r in rows(0, 6)])
        os.replace(new, p)
        self.assertTrue(live.check(self.state))
        self.assertEqual(len(self.state["session"].events), 6)
        self.assertTrue(self.state["session"].events[0].id.startswith("R"))
        evs = live.live_status(self.state, {"since": seq})["events"]
        self.assertTrue(any(e["type"] == "reset" for e in evs))

    def test_full_analysis_is_throttled(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 5))
        self._watch(p)
        self.assertTrue(live.check(self.state))
        live.LIVE.update({"reanalyze_auto": False, "reanalyze_s": 3600})
        append(p, rows(5, 9))
        self.assertFalse(live.check(self.state))        # read, but not analyzed yet
        st = live.live_status(self.state, {})
        self.assertEqual(st["records_read"], 9)
        self.assertEqual(st["pending_records"], 4)
        self.assertEqual(st["records"], 5)
        self.assertIn("at most every 3600 s", st["note"])
        self.assertEqual(len(self.state["session"].events), 5)
        live.LIVE["reanalyze_s"] = 0
        self.assertTrue(live.check(self.state))         # the file did not change, but rows were waiting
        st = live.live_status(self.state, {})
        self.assertEqual((st["records"], st["pending_records"]), (9, 0))
        self.assertIsNone(st["note"])

    def test_reanalyze_s_validated(self):
        p = os.path.join(self.d, "feed.jsonl")
        append(p, rows(0, 3))
        with self.assertRaises(ValueError):
            live.live_start(self.state, {}, json.dumps({"path": p, "reanalyze_s": "soon"}).encode())
        st = live.live_start(self.state, {}, json.dumps({"path": p, "pack": "generic.json", "interval_s": 60,
                                                         "reanalyze_s": 30, "map": {"text": "body"}}).encode())
        self.assertTrue(st["watching"])
        self.assertEqual(live.LIVE["reanalyze_s"], 30)
        self.assertFalse(live.LIVE["reanalyze_auto"])

    def test_not_utf8_falls_back_to_full_reloads(self):
        p = os.path.join(self.d, "feed.jsonl")
        with open(p, "wb") as f:
            f.write(json.dumps(rows(0, 1)[0]).encode() + b"\n")
            f.write(b'{"id": "M0001", "sender": "agent-1", "sent_at": "2026-11-01T10:01:00Z", "body": "caf\xe9"}\n')
        self._watch(p)
        self.assertTrue(live.check(self.state))
        self.assertFalse(live.LIVE["incremental"])
        self.assertEqual(len(self.state["session"].events), 2)
        append(p, rows(2, 4))
        self.assertTrue(live.check(self.state))
        self.assertEqual(len(self.state["session"].events), 4)


class RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_trace(cls.d), "generic.json", {"text": "body"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def setUp(self):
        os.environ["SWARM_TRACER_RULES"] = os.path.join(self.d, "rules.json")
        if os.path.exists(os.environ["SWARM_TRACER_RULES"]):
            os.remove(os.environ["SWARM_TRACER_RULES"])
        self.state = {"session": self.s}

    def tearDown(self):
        os.environ.pop("SWARM_TRACER_RULES", None)

    def test_defaults_evaluate(self):
        r = live.rules_get(self.state, {})
        self.assertFalse(r["saved"])
        self.assertEqual([x["id"] for x in r["rules"]], ["watch-harm", "alert-coord2", "baseline-volume"])
        ev = {x["id"]: x for x in live.rules_eval(self.state, {})["rules"]}
        self.assertEqual(ev["watch-harm"]["record"], "M0000")
        self.assertEqual(ev["alert-coord2"]["record"], "M0010")
        self.assertEqual(ev["alert-coord2"]["harm_share_after"], 0.5)
        self.assertFalse(ev["alert-coord2"]["hindsight"])        # generic pack: the defaults were not written on it

    def test_save_load_evaluate_custom(self):
        rules = live.rules_get(self.state, {})["rules"] + [
            {"name": "Two messages agent-0 to agent-1", "severity": "alert",
             "conditions": [{"type": "messages_between", "a": "agent-0", "b": "agent-1", "n": 1}]},
            {"name": "Busy harm", "severity": "watch", "conditions": [{"type": "harm_rate", "per_hour": 3}]},
            {"name": "Group", "severity": "info", "match": "any",
             "conditions": [{"type": "group_size", "size": 2, "actor": "agent-1"}, {"type": "coordination_kinds", "n": 9}]},
            {"name": "Never", "conditions": [{"type": "coordination_kinds", "n": 9}]},
        ]
        out = live.rules_post(self.state, {}, json.dumps({"rules": rules}).encode())
        self.assertTrue(out["saved"])
        with open(os.environ["SWARM_TRACER_RULES"]) as f:
            self.assertEqual(len(json.load(f)["rules"]), 7)
        ev = {x["name"]: x for x in live.rules_eval(self.state, {})["rules"]}
        self.assertEqual(ev["Two messages agent-0 to agent-1"]["record"], "M0007")
        self.assertTrue(ev["Two messages agent-0 to agent-1"]["hindsight"])     # written with this dataset loaded
        self.assertTrue(ev["Busy harm"]["fired"])
        self.assertTrue(ev["Group"]["fired"])
        self.assertFalse(ev["Never"]["fired"])
        self.assertFalse(ev["Watch: first single-actor harmful sign"]["hindsight"])   # unchanged default
        # reset restores the defaults
        self.assertFalse(live.rules_post(self.state, {}, b'{"reset": true}')["saved"])

    def test_bad_rules_rejected(self):
        for bad in ([{"name": "", "conditions": [{"type": "sign"}]}],
                    [{"name": "x", "conditions": []}],
                    [{"name": "x", "conditions": [{"type": "nope"}]}],
                    [{"name": "x", "severity": "loud", "conditions": [{"type": "sign"}]}],
                    [{"name": "x", "conditions": [{"type": "harm_rate", "per_hour": "many"}]}]):
            with self.assertRaises(ValueError):
                live.rules_post(self.state, {}, json.dumps({"rules": bad}).encode())


class ReplayFeedTests(unittest.TestCase):
    def test_replays_in_time_order(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "src.jsonl")
            recs = rows(0, 12)
            append(src, list(reversed(recs)))
            dst = os.path.join(d, "out", "feed.jsonl")
            subprocess.run([sys.executable, "-m", "agenttrace.tools.replay_feed", src, dst, "--rate", "1000",
                            "--fast", "--quiet"], check=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            with open(dst) as f:
                ids = [json.loads(x)["id"] for x in f]
            self.assertEqual(ids, [r["id"] for r in recs])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

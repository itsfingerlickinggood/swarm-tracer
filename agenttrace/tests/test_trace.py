"""Tests for the Trace tab's server side (agenttrace/trace.py) on the bundled demo swarm."""
import json
import unittest

from agenttrace import cli, extensions, trace
from agenttrace.session import Session

STEP_KEYS = {"t", "time", "estimated", "kind", "actor", "agent", "record", "place", "text", "evidence"}


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session()
        cls.s.load(cli.demo_input(), "auto")
        cls.state = {"session": cls.s}
        cls.starts = trace.starts(cls.s)["starts"]

    def check_chain(self, r):
        json.dumps(r)
        self.assertTrue(r["found"])
        self.assertLessEqual(len(r["steps"]), trace.MAX_STEPS)
        ts = [st["t"] for st in r["steps"] if st["t"] is not None]
        self.assertEqual(ts, sorted(ts))
        lanes = {l["actor"] for l in r["lanes"]}
        for st in r["steps"]:
            self.assertTrue(STEP_KEYS <= set(st))
            self.assertIn(st["record"], self.s.by_id)
            self.assertIn(st["actor"], lanes)
            self.assertLessEqual(len(st["text"]), 200)
            self.assertEqual(st["harmful"], st["record"] in self.s.harmful)
            if st["harmful"]:
                self.assertEqual(st["kind"], "harm")
        for e in r["edges"]:
            self.assertTrue(0 <= e["from"] < len(r["steps"]) and 0 <= e["to"] < len(r["steps"]))
            self.assertNotEqual(e["from"], e["to"])
        self.assertEqual(r["truncated"], r["steps_total"] > len(r["steps"]))

    def test_routes_registered(self):
        get, _ = extensions.routes()
        for name in ("trace_start", "trace_path", "trace_harm"):
            self.assertIn(name, get)
        self.assertRaises(LookupError, get["trace_path"], {"session": None}, {"q": "x"})
        self.assertRaises(ValueError, get["trace_path"], self.state, {"q": "  "})
        self.assertRaises(ValueError, get["trace_harm"], self.state, {})
        self.assertRaises(LookupError, get["trace_harm"], self.state, {"rec": "no-such-record"})

    def test_starts_come_from_the_data(self):
        keys = [x["key"] for x in self.starts]
        self.assertIn("first_message", keys)
        self.assertIn("widest_program", keys)
        self.assertIn("broadcast_place", keys)
        harms = [x for x in self.starts if x["key"] == "first_harm"]
        self.assertTrue(harms)
        self.assertEqual(len({x["kind"] for x in harms}), len(harms))
        for x in harms:
            self.assertIn(x["harm"], self.s.harmful)
            self.assertIn(x["kind"], self.s.pack.harm)
        for x in self.starts:      # every starting point resolves to something
            if x.get("q"):
                self.assertTrue(trace.trace_path(self.s, x["q"])["found"], x)

    def test_path_for_a_record(self):
        d = next(x for x in self.starts if x["key"] == "first_message")
        r = trace.trace_path(self.s, d["q"])
        self.check_chain(r)
        self.assertEqual(r["resolved"], {"type": "record", "key": d["q"]})
        focus = [st for st in r["steps"] if st["focus"]]
        self.assertEqual([st["record"] for st in focus], [d["q"]])
        # the first message: its write is linked to a read by another actor
        msgs = [e for e in r["edges"] if e["kind"] == "message"]
        self.assertTrue(msgs)
        a, b = r["steps"][msgs[0]["from"]], r["steps"][msgs[0]["to"]]
        self.assertEqual(a["record"], d["q"])
        self.assertNotEqual(a["actor"], b["actor"])
        self.assertEqual(msgs[0]["place"], d["place"])
        self.assertGreaterEqual(r["summary"]["handovers"], 1)
        self.assertGreaterEqual(r["summary"]["holders"], 2)

    def test_path_for_a_program_record(self):
        d = next(x for x in self.starts if x["key"] == "widest_program")
        r = trace.trace_path(self.s, d["q"])
        self.check_chain(r)
        reuse = [e for e in r["edges"] if e["kind"] == "reuse"]
        self.assertTrue(reuse)
        self.assertTrue(all(r["steps"][e["from"]]["record"] == d["q"] for e in reuse))

    def test_path_for_a_token(self):
        tok = max((a for a in self.s.by_actor if a.startswith("[CREDENTIAL")), key=lambda a: len(self.s.by_actor[a]))
        r = trace.trace_path(self.s, tok)
        self.check_chain(r)
        self.assertEqual(r["resolved"], {"type": "token", "key": tok})
        self.assertGreater(r["as_identity"], 0)
        self.assertTrue(any(st["kind"] in ("use", "harm") and st["actor"] == tok for st in r["steps"]))
        m = r["summary"]
        self.assertEqual(m["first_seen"]["record"], r["steps"][0]["record"])
        self.assertLessEqual(m["agents"], m["holders"])
        if m["first_harm"]:
            self.assertIn(m["first_harm"]["record"], self.s.harmful)
            self.assertGreaterEqual(m["first_to_harm_h"], 0)
        # the app's short form finds the same token
        short = "cred " + tok.split()[1].rstrip("]")
        self.assertEqual(trace.trace_path(self.s, short)["resolved"]["key"], tok)

    def test_path_for_a_place(self):
        d = next(x for x in self.starts if x["key"] == "broadcast_place")
        r = trace.trace_path(self.s, d["q"])
        self.check_chain(r)
        self.assertEqual(r["resolved"]["type"], "place")
        self.assertTrue(any(e["kind"] == "message" for e in r["edges"]))
        self.assertTrue(all(st["place"] == d["q"] for st in r["steps"] if st["kind"] in ("write", "read")))

    def test_path_for_an_unknown_string(self):
        r = trace.trace_path(self.s, "zz-no-record-holds-this-zz")
        json.dumps(r)
        self.assertFalse(r["found"])
        self.assertEqual(r["steps"], [])
        self.assertEqual(r["resolved"]["type"], "string")
        self.assertEqual(set(r["suggestions"]), {"records", "actors", "places"})

    def test_harm_provenance(self):
        d = next(x for x in self.starts if x["key"] == "first_harm")
        r = trace.trace_harm(self.s, d["harm"])
        json.dumps(r)
        self.assertTrue(r["harmful"])
        ids = [n["id"] for n in r["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        types = {n["type"] for n in r["nodes"]}
        self.assertTrue({"harm", "actor"} <= types)
        self.assertTrue(types <= {"harm", "credential", "program", "place", "actor", "message", "origin"})
        by = {n["id"]: n for n in r["nodes"]}
        self.assertEqual(by["harm"]["record"], d["harm"])
        self.assertEqual(by["actor"]["actor"], self.s.actor[d["harm"]][0])
        for e in r["edges"]:      # a DAG that only ever points toward the harm
            self.assertLess(by[e["from"]]["layer"], by[e["to"]]["layer"])
            self.assertTrue(e["label"])
        self.assertIn(("actor", "harm"), {(e["from"], e["to"]) for e in r["edges"]})
        for tok in self.s.rec["_ids"].get(d["harm"], {}):
            self.assertIn("cred:" + tok, by)
        for n in r["nodes"]:
            if n["type"] == "origin":
                self.assertIn(n["record"], self.s.by_id)
        self.assertTrue(r["story"])
        self.assertLessEqual(len(r["text"]), 200)

    def test_harm_provenance_with_messages(self):
        # a harmful record whose actor had read another actor's write before it
        rid = next((r for r in sorted(self.s.harmful) if self.s.del_in.get(r)), None)
        if rid is None:
            self.skipTest("no harmful record reads a message in the demo")
        r = trace.trace_harm(self.s, rid)
        msgs = [n for n in r["nodes"] if n["type"] == "message"]
        self.assertTrue(msgs)
        self.assertTrue(any(n["direct"] for n in msgs))
        self.assertGreaterEqual(r["messages_before"], len(msgs))


if __name__ == "__main__":
    unittest.main()

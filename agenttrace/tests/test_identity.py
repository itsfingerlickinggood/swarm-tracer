"""Identity merging and roles on a small constructed trace.

tok-A and tok-B take turns inside one thread (one stops, the other starts minutes later), as one agent
switching keys would; tok-C works in its own thread at the same time as both, and runs one program
that A also runs.
"""
import csv
import datetime as dt
import json
import os
import shutil
import tempfile
import unittest

from agenttrace import identity
from agenttrace.session import Session

PROGRAM = ("import requests; r = requests.get('https://data.example.org/catalog/index'); "
           "rows = r.json()['items']; out = [x['name'] for x in rows if x.get('public')]; print(len(out), out[:5])")


def write_identity_trace(d):
    t0 = dt.datetime(2026, 11, 1, 10, 0)
    rows = []

    def add(actor, minute, parent, body):
        rid = f"R{len(rows):04d}"
        rows.append({"id": rid, "sender": actor, "reply_to": parent or "",
                     "sent_at": (t0 + dt.timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:00Z"), "body": body})
        return rid

    # A and B share one thread and hand over: A 10:00-10:15, B 10:20-10:35, A 11:00-11:15, B 11:20-11:35
    last = None
    for start, who in ((0, "tok-A"), (20, "tok-B"), (60, "tok-A"), (80, "tok-B")):
        for k in range(4):
            last = add(who, start + 5 * k, last, f"step {start + k} of the shared job by {who}")
    # C works in its own thread the whole time, in parallel with both
    lastc = None
    for m in range(0, 100, 5):
        lastc = add("tok-C", m, lastc, f"independent work item {m}")
    # one program run by A and C
    add("tok-A", 61, None, PROGRAM)
    add("tok-C", 62, None, PROGRAM)
    rows.sort(key=lambda r: r["sent_at"])
    p = os.path.join(d, "ids.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.home = tempfile.mkdtemp()
        cls.saved = (identity.DECISIONS_DIR, identity.SAVE_DECISIONS)
        identity.DECISIONS_DIR, identity.SAVE_DECISIONS = cls.home, True
        cls.s = Session()
        cls.s.load(write_identity_trace(cls.d), "generic.json", {"text": "body"})
        cls.state = {"session": cls.s}

    @classmethod
    def tearDownClass(cls):
        identity.DECISIONS_DIR, identity.SAVE_DECISIONS = cls.saved
        shutil.rmtree(cls.d, ignore_errors=True)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.s._id_decisions = {}

    def pair(self, r, a, b):
        return next((x for x in r["proposals"] if {x["a"], x["b"]} == {a, b}), None)

    def test_thread_and_handoffs_propose_a_b(self):
        r = identity.identity(self.s)
        p = self.pair(r, "tok-A", "tok-B")
        self.assertIsNotNone(p)
        keys = {e["key"] for e in p["evidence"]}
        self.assertIn("same_thread", keys)
        self.assertIn("handoff", keys)
        self.assertEqual(p["against"], [])
        self.assertIn(p["confidence"], ("medium", "high"))
        self.assertEqual(p["score"], sum(e["points"] for e in p["evidence"]))
        # every evidence item names its records, or says what it counted
        th = next(e for e in p["evidence"] if e["key"] == "same_thread")
        self.assertTrue(th["records"])

    def test_parallel_actor_counts_against(self):
        base = identity._base(self.s)
        pa = base["pairs"].get(("tok-A", "tok-C"))
        self.assertIsNotNone(pa)                       # the shared program makes them a candidate
        sc = identity._score(self.s, base, "tok-A", "tok-C", pa)
        self.assertIn("same_programs", {e["key"] for e in sc["evidence"]})
        self.assertIn("parallel", {e["key"] for e in sc["against"]})
        self.assertNotIn("handoff", {e["key"] for e in sc["evidence"]})
        self.assertLess(sc["score"], identity.LOW)     # so it is not proposed
        self.assertIsNone(self.pair(identity.identity(self.s), "tok-A", "tok-C"))

    def test_estimate_and_decisions(self):
        r = identity.identity(self.s)
        e = r["estimate"]
        self.assertEqual(e["named_actors"], 3)
        conf = self.pair(r, "tok-A", "tok-B")["confidence"]
        self.assertEqual(e["estimated_agents"], 2 if conf == "high" else 3)
        self.assertEqual(e["low"], 2)
        self.assertEqual(e["high"], 3)
        out = identity._post_decide(self.state, {}, json.dumps({"a": "tok-B", "b": "tok-A", "decision": "accept"}).encode())
        self.assertEqual(out["decision"], "accept")
        self.assertEqual(out["estimate"]["estimated_agents"], 2)
        self.assertEqual(out["estimate"]["high"], 2)
        self.assertTrue(os.path.exists(out["saved_to"]))
        with open(out["saved_to"]) as f:
            self.assertEqual(json.load(f), [{"a": "tok-A", "b": "tok-B", "decision": "accept"}])
        r = identity.identity(self.s)
        self.assertEqual(r["groups"][0]["actors"].__len__(), 2)
        identity.decide(self.s, "tok-A", "tok-B", "reject")
        r = identity.identity(self.s)
        self.assertEqual(r["estimate"]["estimated_agents"], 3)
        self.assertEqual(r["estimate"]["low"], 3)
        self.assertEqual(r["groups"], [])
        identity.decide(self.s, "tok-A", "tok-B", "clear")
        self.assertEqual(identity.identity(self.s)["estimate"]["rejected"], 0)

    def test_bad_decisions(self):
        with self.assertRaises(ValueError):
            identity.decide(self.s, "tok-A", "nobody", "accept")
        with self.assertRaises(ValueError):
            identity.decide(self.s, "tok-A", "tok-B", "maybe")
        with self.assertRaises(ValueError):
            identity._post_decide(self.state, {}, b"not json")
        with self.assertRaises(LookupError):
            identity._get_identity({"session": Session()}, {})

    def test_actor_view_and_roles(self):
        r = identity._get_identity(self.state, {"actor": "tok-A"})
        self.assertTrue(any("tok-B" in (x["a"], x["b"]) for x in r["proposals"]))
        self.assertIsNotNone(r["role"])
        ro = identity._get_roles(self.state, {})
        self.assertEqual(ro["named_actors"], 3)
        self.assertEqual(sum(ro["counts"].values()), 3)
        for x in ro["rows"]:
            self.assertIn(x["role"], {"coordinator", "relay", "recruiter", "worker", "participant", "lone"})
            self.assertTrue(x["why"])

    def test_helpers(self):
        self.assertEqual(identity._stem("Helper57"), "helper")
        self.assertIsNone(identity._stem("Helper"))
        self.assertIsNone(identity._stem("ab1"))
        s = identity._sessions([0, 600, 5000])
        self.assertEqual(len(s), 2)
        self.assertEqual(identity._overlap([(0, 100)], [(50, 200)]), 50)
        self.assertEqual(len(identity._handoffs([(0, 100)], [(200, 300)])), 1)
        self.assertEqual(identity._handoffs([(0, 100)], [(100 + 3600, 4000)]), [])

    def test_routes_registered(self):
        from agenttrace import extensions
        get, post = extensions.routes()
        self.assertIn("identity", get)
        self.assertIn("roles", get)
        self.assertIn("identity_decide", post)


if __name__ == "__main__":
    unittest.main()

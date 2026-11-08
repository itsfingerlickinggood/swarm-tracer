"""Tests for the "Follow the evidence" forensics (agenttrace/fx_lineage.py) on small written traces."""
import csv
import os
import tempfile
import unittest

from agenttrace import extensions, fx_lineage as fx
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace

ROWS = [
    # id, sender, minute, body
    ("C00", "agent-0", 0, "posting orders to https://cmd.example.com/orders method: 'POST' with the plan for today"),
    ("C01", "agent-1", 5, "reading https://cmd.example.com/orders for the orders of the day"),
    ("C02", "agent-1", 20, "running subprocess on the host to follow the orders"),
    ("C03", "agent-2", 10, "reading https://cmd.example.com/orders now and then"),
    ("C04", "agent-2", 30, "found a key [CREDENTIAL 7] in the notes, keeping it carried along"),
    ("C05", "agent-3", 60, "calling with Authorization Bearer [CREDENTIAL 7] for the first time"),
    ("C06", "agent-3", 90, "Bearer [CREDENTIAL 7] uploading to https://drop.example.com/box1 method: 'POST'"),
    ("C07", "agent-0", 120, "reading https://drop.example.com/box1 to collect what was left"),
    ("C08", "agent-1", 130, "leaving a note at https://drop.example.com/box2 method: 'POST'"),
    ("C09", "agent-0", 140, "status ok"),
]


def write_c2_trace(d):
    p = os.path.join(d, "c2.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "sender", "sent_at", "body"])
        w.writeheader()
        for rid, who, m, body in ROWS:
            w.writerow({"id": rid, "sender": who, "sent_at": f"2026-11-01T{10 + m // 60:02d}:{m % 60:02d}:00Z", "body": body})
    return p


class FxLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_c2_trace(cls.d), "generic.json", {"text": "body"})
        cls.small = Session()
        cls.small.load(write_trace(cls.d), "generic.json", {"text": "body"})

    # ---------------------------------------------------------------- trace anything
    def test_trace_substring_on_shared_test_trace(self):
        t = fx.trace(self.small, "NOTES.example.com")       # case-insensitive
        self.assertEqual(t["total"], 7)                    # every fifth post and the read in M0007
        self.assertEqual(t["first"]["id"], "M0000")
        self.assertEqual([a["actor"] for a in t["actors"]], ["agent-0", "agent-2", "agent-1"])
        self.assertEqual([(h["from"], h["to"]) for h in t["hops"]], [("agent-0", "agent-2"), ("agent-2", "agent-1")])
        self.assertTrue(all(r["places"] for r in t["rows"]))
        self.assertEqual(sum(n for _, n in t["series"]), 7)

    def test_trace_token_identity_and_cred_shorthand(self):
        t = fx.trace(self.s, "cred 7")
        self.assertEqual(t["total"], 3)
        self.assertEqual(t["as_identity"], 2)
        self.assertEqual(t["first"]["id"], "C04")
        self.assertFalse(t["first"]["identity"])
        self.assertEqual([h["to"] for h in t["hops"]], ["agent-3"])
        self.assertEqual(t["hops"][0]["from_record"], "C04")

    def test_trace_regex_and_errors(self):
        self.assertEqual(fx.trace(self.s, "/box[12]/")["total"], 3)
        with self.assertRaises(ValueError):
            fx.trace(self.s, "/[unclosed/")
        with self.assertRaises(ValueError):
            fx.trace(self.s, "  ")
        self.assertEqual(fx.trace(self.s, "nothing like this")["total"], 0)

    def test_trace_limit_keeps_true_total(self):
        t = fx.trace(self.small, "status", limit=5)
        self.assertEqual(len(t["rows"]), 5)
        self.assertGreater(t["total"], 5)

    # ---------------------------------------------------------------- credentials
    def test_credential_lifecycle(self):
        c = fx.credentials(self.s)
        row = next(r for r in c["tokens"] if r["token"] == "[CREDENTIAL 7]")
        self.assertEqual(row["uses"], 2)
        self.assertEqual(row["first_use_record"], "C05")
        self.assertEqual(row["last_use_record"], "C06")
        self.assertEqual(row["seen_record"], "C04")
        self.assertTrue(row["seen_before_use"])
        self.assertEqual([x["actor"] for x in row["carried_by"]], ["agent-2"])
        self.assertEqual(row["users"][0]["actor"], "agent-3")
        self.assertEqual(row["places_total"], 1)
        self.assertIn("url", row["place_types"])
        self.assertGreater(row["quiet_h"], 0)
        self.assertGreaterEqual(c["seen_before_use"], 1)

    # ---------------------------------------------------------------- command and control
    def test_c2_place_and_what_changed(self):
        lst = fx.c2_list(self.s)
        chans = [r["channel"] for r in lst["places"]]
        self.assertIn("url:cmd.example.com/orders", chans)
        p = fx.c2_place(self.s, "url:cmd.example.com/orders")
        self.assertEqual(p["writes_total"], 1)
        card = p["cards"][0]
        self.assertEqual(card["record"], "C00")
        readers = {r["actor"]: r for r in card["readers"]}
        self.assertEqual(set(readers), {"agent-1", "agent-2"})
        r1 = readers["agent-1"]
        self.assertAlmostEqual(r1["wait_h"], 5 / 60, places=2)
        self.assertIn("runs_shell", [x["intent"] for x in r1["new_intents"]])
        self.assertIn("C02", r1["records_after"])
        self.assertEqual(r1["before"], 0)
        with self.assertRaises(LookupError):
            fx.c2_place(self.s, "url:no.such/place")

    def test_c2_empty_on_trace_without_shared_reads(self):
        self.assertEqual(fx.c2_list(self.small)["total"], 0)

    # ---------------------------------------------------------------- dead drops
    def test_dead_drops(self):
        d = fx.drops(self.s)
        by = {r["channel"]: r for r in d["rows"]}
        box1, box2, orders = by["url:drop.example.com/box1"], by["url:drop.example.com/box2"], by["url:cmd.example.com/orders"]
        self.assertEqual(box1["writer"], "agent-3")
        self.assertEqual(box1["status"], "one")
        self.assertEqual(box1["readers"][0]["actor"], "agent-0")
        self.assertAlmostEqual(box1["readers"][0]["wait_h"], 0.5, places=2)
        self.assertEqual(box2["status"], "never")
        self.assertEqual(orders["status"], "many")
        self.assertEqual(sum(b["n"] for b in d["hist"]), d["pickups"])
        out = fx.drops_csv(self.s)
        lines = out["csv"].strip().splitlines()
        self.assertTrue(lines[0].startswith("place,place_type,writer"))
        self.assertEqual(len(lines) - 1, out["rows"])
        self.assertEqual(out["rows"], 4)     # box1: 1 pickup, orders: 2, box2: never picked up

    # ---------------------------------------------------------------- search
    def test_boolean_parser(self):
        f, terms = fx.parse_query('"the plan" AND (orders OR notes) -subprocess')
        self.assertEqual(terms, ["the plan", "orders", "notes"])
        self.assertTrue(f("posting orders with the plan"))
        self.assertFalse(f("the plan orders subprocess"))
        self.assertFalse(f("orders only"))
        f, _ = fx.parse_query("NOT a")
        self.assertTrue(f("bcd"))
        with self.assertRaises(ValueError):
            fx.parse_query("a OR")
        with self.assertRaises(ValueError):
            fx.parse_query("a)")

    def test_search(self):
        self.assertEqual(fx.search(self.s, "orders AND reading")["total"], 2)
        self.assertEqual(fx.search(self.s, "subprocess OR carried")["total"], 2)
        self.assertEqual(fx.search(self.s, "cred 7")["total"], 3)
        self.assertEqual(fx.search(self.s, "/box[12]/")["total"], 3)
        self.assertEqual(fx.search(self.s, "box1", actor="agent-0")["total"], 1)
        r = fx.search(self.s, "example.com NOT box2", limit=2)
        self.assertEqual(r["total"], 5)
        self.assertEqual(len(r["rows"]), 2)
        self.assertIn("snip", r["rows"][0])
        self.assertEqual(fx.search(self.s, "", hour="2026-11-01 10")["total"], 5)

    def test_like(self):
        r = fx.like(self.s, "C01")
        ids = [x["id"] for x in r["rows"]]
        self.assertIn("C03", ids)
        self.assertIn("url:cmd.example.com/orders", r["rows"][0]["places"])
        self.assertNotIn("C01", ids)
        with self.assertRaises(LookupError):
            fx.like(self.s, "nope")

    # ---------------------------------------------------------------- routes
    def test_routes(self):
        get, _ = extensions.routes()
        for name in ("fx_trace", "fx_credentials", "fx_c2", "fx_c2_place", "fx_drops", "fx_drops_csv", "fx_search", "fx_like"):
            self.assertIn(name, get)
        st = {"session": self.s}
        self.assertEqual(get["fx_trace"](st, {"q": "box1"})["total"], 2)
        self.assertEqual(get["fx_drops"](st, {"limit": "1"})["total"], 3)
        self.assertEqual(len(get["fx_drops"](st, {"limit": "1"})["rows"]), 1)
        with self.assertRaises(LookupError):
            get["fx_c2"]({"session": Session()}, {})
        with self.assertRaises(ValueError):
            get["fx_search"](st, {"q": "x", "limit": "many"})


if __name__ == "__main__":
    unittest.main()

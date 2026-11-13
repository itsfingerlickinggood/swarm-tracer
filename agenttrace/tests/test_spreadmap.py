"""Spread map, evidence graph and stage tie-in, on a small simulated swarm (groundtruth.make)."""
import os
import tempfile
import unittest
from unittest import mock

from agenttrace import groundtruth, spreadmap as sp
from agenttrace.session import Session

CACHES = ("_spreadmap", "_spreadmap_ev", "_spreadmap_graph", "_spreadmap_stages")


def _sim(mode="coordinated", agents=30, seed=1):
    d = tempfile.mkdtemp(prefix="spreadmap_test_")
    groundtruth.make(d, agents=agents, seed=seed, mode=mode)
    s = Session()
    s.load(os.path.join(d, "trace.jsonl"), "code_traces.json")
    return s


def _clear(s):
    for k in CACHES:
        if hasattr(s, k):
            delattr(s, k)


class SpreadMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _sim()
        cls.st = {"session": cls.s}

    def test_no_session(self):
        for name, fn in sp.GET.items():
            with self.assertRaises(LookupError):
                fn({"session": None}, {"q": "x", "a": "a", "b": "b"})

    def test_shape_and_rank(self):
        r = sp.GET["spreadmap"](self.st, {})
        self.assertEqual(r["summary"]["items"], len(sp.build(self.s)["items"]))
        xs = r["items"]
        self.assertTrue(xs)
        keys = [(-x["agents"], -x["runs"]) for x in xs]
        self.assertEqual(keys, sorted(keys), "ranked by agents first, then runs")
        for x in xs:
            self.assertIn(x["kind"], sp.KINDS)
            self.assertIn(x["type"], tuple(sp.TYPES) + ("single",))
            self.assertGreaterEqual(x["agents"] + x["runs"], 2)
            self.assertTrue(x["origin"]["time"])
            if x["t25"] is not None:
                self.assertLessEqual(x["t25"], x["t50"])
                self.assertLessEqual(x["t50"], x["t90"])
                self.assertGreaterEqual(x["t25"], 0)
        for st in r["strips"]:
            hs = [p["hours"] for p in st["strip"]["points"]]
            self.assertEqual(hs, sorted(hs))
            self.assertEqual(hs[0], 0)
        self.assertIs(sp.build(self.s), sp.build(self.s))       # cached on the session

    def test_item_cascade(self):
        top = sp.GET["spreadmap"](self.st, {})["items"][0]
        it = sp.GET["spreadmap_item"](self.st, {"q": top["item"]})
        self.assertEqual(it["item"], top["item"])
        self.assertEqual(it["holders"][0]["type"], "origin")
        self.assertEqual(it["holders"][0]["unit"], top["origin"]["unit"])
        self.assertEqual(sum(1 for h in it["holders"] if h["named"]), top["agents"])
        with self.assertRaises(LookupError):
            sp.GET["spreadmap_item"](self.st, {"q": "definitely-not-an-item-zzz"})
        with self.assertRaises(ValueError):
            sp.GET["spreadmap_item"](self.st, {"q": " "})

    def test_agents_never_exceed_actors(self):
        for x in sp.build(self.s)["items"].values():
            if x["kind"] in ("file", "place", "string", "credential"):
                self.assertLessEqual(x["agents"], x["actors"])

    def test_reach_by_agent_vs_by_token(self):
        """Two tokens of one estimated agent are two actors but one agent."""
        s = _sim()
        base = sp.build(s)
        two = next(x for x in base["items"].values() if x["actors"] >= 2 and x["agents"] >= 2 and x["kind"] != "credential")
        named = [h["actor"] for h in two["holders"] if h["named"]][:2]
        a, b = named
        real = sp._amap(s)

        def merged(_s):
            m = dict(real)
            m[a] = m[b] = a
            return m
        _clear(s)
        with mock.patch.object(sp, "_amap", merged):
            got = sp.build(s)["items"][two["item"]]
        self.assertEqual(got["actors"], two["actors"])
        self.assertEqual(got["agents"], two["agents"] - 1)
        _clear(s)

    def test_hours_non_negative_and_ordered(self):
        for x in list(sp.build(self.s)["items"].values())[:200]:
            hs = [h["hours"] for h in x["holders"] if h["hours"] is not None]
            self.assertEqual(hs, sorted(hs))
            self.assertEqual(x["span_h"], hs[-1])


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _sim()
        cls.st = {"session": cls.s}

    def test_counts_add_up(self):
        r = sp.GET["evidence"](self.st, {})
        sm = r["summary"]
        self.assertEqual(sm["pairs"], len(r["pairs"]))
        self.assertEqual(sm["beyond_messages"], sum(1 for p in r["pairs"] if not p["message"]))
        self.assertEqual(sm["beyond_messages"], sm["pairs"] - sm["message"])
        self.assertLessEqual(sm["content_beyond"] + sm["behaviour_beyond"], sm["beyond_messages"] * 2)
        for p in r["pairs"]:
            self.assertNotEqual(p["a"], p["b"])
            self.assertLess(p["a"], p["b"])
            self.assertEqual(p["style"], p["kinds"][0])
        self.assertGreater(sm["message"], 0)

    def test_pair_detail(self):
        r = sp.GET["evidence"](self.st, {})
        p = next(x for x in r["pairs"] if x["message"])
        d = sp.GET["evidence_pair"](self.st, {"a": p["b"], "b": p["a"]})
        self.assertEqual(d["messages_total"], p["message"])
        self.assertTrue(all(m["write_id"] and m["read_id"] for m in d["messages"]))
        with self.assertRaises(LookupError):
            sp.GET["evidence_pair"](self.st, {"a": "nobody1", "b": "nobody2"})
        with self.assertRaises(ValueError):
            sp.GET["evidence_pair"](self.st, {"a": "x"})


class StageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _sim()
        cls.st = {"session": cls.s}

    def test_stage_rows(self):
        r = sp.GET["spread_stages"](self.st, {})
        self.assertTrue(r["stages"])
        for g in r["stages"]:
            self.assertIn("stage", g)
            if not g["agents"]:
                continue
            self.assertTrue(g["first"]["unit"])
            for row in g["crossed"] + g["preceded"]:
                self.assertGreaterEqual(row["lag_h"], sp.MARGIN_H)
                self.assertNotEqual(row["user"], row["origin_unit"])
                self.assertGreaterEqual(row["hold_to_use_h"], 0)
            self.assertLessEqual(len(g["crossed"]), 10)


if __name__ == "__main__":
    unittest.main()

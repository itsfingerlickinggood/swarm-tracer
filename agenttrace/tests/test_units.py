"""Units: the token -> estimated agent map and the recount by agent (GET /api/x/units_map, units_summary)."""
import os
import shutil
import tempfile
import unittest

from agenttrace import extensions, fx_whatif, identity, insight, units
from agenttrace.session import Session

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "demo_swarm")


class TestUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls._old = os.environ.get("SWARM_TRACER_HOME")
        os.environ["SWARM_TRACER_HOME"] = cls.home
        cls._save = identity.SAVE_DECISIONS
        identity.SAVE_DECISIONS = False
        cls.s = Session()
        cls.s.load(DEMO, "auto", {}, "units-test-demo")
        cls.state = {"session": cls.s}

    @classmethod
    def tearDownClass(cls):
        identity.SAVE_DECISIONS = cls._save
        if cls._old is None:
            os.environ.pop("SWARM_TRACER_HOME", None)
        else:
            os.environ["SWARM_TRACER_HOME"] = cls._old
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.s._id_decisions = {}
        self.s._fx_dec = {"messages": {}, "signs": {}}
        self.s._fx_wi = None

    def _named_messages(self):
        return [d for d in self.s.flow["_deliveries"] if insight.is_named(d["from"]) and insight.is_named(d["to"])]

    def test_routes_registered(self):
        get, _ = extensions.routes()
        self.assertIn("units_map", get)
        self.assertIn("units_summary", get)
        with self.assertRaises(LookupError):
            get["units_map"]({"session": None}, {})
        with self.assertRaises(ValueError):
            get["units_summary"](self.state, {"unit": "swarm"})

    def test_map_matches_the_whatif_estimate(self):
        m = units.GET["units_map"](self.state, {})
        w = fx_whatif.whatif(self.s, "estimate")
        self.assertEqual(m["rule"], "estimate")
        self.assertEqual(m["tokens"], w["as_counted"]["named_actors"])
        self.assertEqual(m["agents"], w["after"]["agents"])
        self.assertEqual(m["messages"], {"token": w["as_counted"]["messages"], "agent": w["after"]["messages"],
                                         "inside_one_agent": w["after"]["inside_one_agent"],
                                         "rejected": w["after"]["rejected_messages"]})
        self.assertEqual(m["merged_agents"], w["groups_total"])
        self.assertEqual(m["no_merges"], not m["agent_list"])
        self.assertEqual(m["tokens"] - m["merges"], m["agents"])
        if m["no_merges"]:
            self.assertEqual(m["note"], "no tokens are merged in this trace")
            self.assertEqual(m["of"], {})
        for g in m["agent_list"]:
            self.assertEqual(g["id"], g["tokens"][0])
            self.assertTrue(all(m["of"][t] == g["id"] for t in g["tokens"]))
            self.assertIn(f"{len(g['tokens'])} tokens", g["label"])

    def test_token_unit_equals_the_existing_counts(self):
        t = units.GET["units_summary"](self.state, {"unit": "token"})
        f = self.s.summary()["flow"]
        self.assertEqual(t["unit"], "token")
        self.assertEqual(t["messages"], f["deliveries_between_named_actors"])
        self.assertEqual(t["pairs"], f["named_actor_pairs"])
        self.assertEqual(t["messages"], len(self._named_messages()))
        self.assertEqual(t["inside_one_agent"], 0)
        self.assertEqual(t["units"], t["tokens"])
        self.assertEqual(sum(p["messages"] for p in t["top_pairs"]) if t["pairs_listed"] == t["pairs"] else t["messages"], t["messages"])
        for p in t["top_pairs"]:      # by token, each pair is its own single token pair
            self.assertEqual(p["token_pairs"], [{"from": p["from"], "to": p["to"], "messages": p["messages"]}])
        sim = insight.simulate(self.s)
        self.assertEqual([(g["key"], g["as_counted"]["time"], g["as_counted"]["harm_share_after"]) for g in t["signs"]],
                         [(g["key"], g["time"], g["harm_share_after"]) for g in sim["signals"]])
        self.assertTrue(all(g["value"] == g["as_counted"] for g in t["signs"]))

    def test_agent_unit_with_no_merges_is_the_token_count(self):
        a = units.units_summary(self.s, "agent")
        t = units.units_summary(self.s, "token")
        if not a["no_merges"]:
            self.skipTest("the demo swarm has merges")
        for k in ("messages", "pairs", "inside_one_agent", "units", "top_pairs", "first_message"):
            self.assertEqual(a[k], t[k], k)
        self.assertEqual(a["note"], "no tokens are merged in this trace")

    def test_an_accepted_merge_moves_messages_inside_one_agent(self):
        named = self._named_messages()
        self.assertTrue(named, "the demo swarm has messages between named actors")
        a, b = named[0]["from"], named[0]["to"]
        between = sum(1 for d in named if {d["from"], d["to"]} == {a, b})
        before = units.units_summary(self.s, "agent")
        self.s._id_decisions = {tuple(sorted((a, b))): "accept"}
        m = units.units_map(self.s)
        after = units.units_summary(self.s, "agent")
        self.assertFalse(m["no_merges"])
        self.assertEqual(m["of"][a], m["of"][b])
        g = next(x for x in m["agent_list"] if a in x["tokens"])
        self.assertIn(b, g["tokens"])
        self.assertEqual(g["name"], "Agent " + units._letters(m["agent_list"].index(g)))
        self.assertIsNotNone(g["confidence"])
        self.assertEqual(after["agents"], before["agents"] - 1)
        self.assertEqual(after["inside_one_agent"] - before["inside_one_agent"], between)
        self.assertEqual(after["messages"], before["messages"] - between)
        self.assertEqual(after["messages"] + after["inside_one_agent"], after["as_counted"]["messages"])
        # the pair breakdown agrees with the recount it sits beside
        self.assertEqual(sum(x["messages"] for x in after["inside"]), after["inside_one_agent"])
        ins = next(x for x in after["inside"] if x["agent"] == g["id"])
        self.assertEqual(sum(p["messages"] for p in ins["token_pairs"]), ins["messages"])
        if after["pairs_listed"] == after["pairs"]:
            self.assertEqual(sum(p["messages"] for p in after["top_pairs"]), after["messages"])
        tot = {x["id"]: x for x in after["totals"]}
        self.assertEqual(tot[g["id"]]["tokens"], len(g["tokens"]))
        self.assertGreaterEqual(tot[g["id"]]["inside"], between)
        # the token unit ignores the merge
        tok = units.units_summary(self.s, "token")
        self.assertEqual(tok["messages"], before["as_counted"]["messages"])
        self.assertEqual(tok["inside_one_agent"], 0)
        # every sign carries both readings; the agent one is the What-if recount
        w = fx_whatif.whatif(self.s, "estimate")
        for row, src in zip(after["signs"], w["signs"]):
            self.assertEqual(row["as_counted"]["time"], src["time"])
            self.assertEqual(row["by_agent"] and row["by_agent"]["time"], src["after"] and src["after"]["time"])
            self.assertEqual(row["value"], row["by_agent"])

    def test_letters(self):
        self.assertEqual([units._letters(i) for i in (0, 1, 25, 26, 27)], ["A", "B", "Z", "AA", "AB"])


if __name__ == "__main__":
    unittest.main()

"""Tests for the QA tools: the consistency oracle's helpers and the smoke test's dataset setup.

The browser and server parts run in `python3 -m agenttrace.tools.check`; these tests stay offline and fast.
"""
import io
import os
import shutil
import tempfile
import unittest

from agenttrace.tools import oracle, smoke

COLS = ["from", "to", "channel", "write_id", "read_id", "write_t", "read_t", "latency_h", "how", "merged"]


def msg(a, b, t, merged=0, ch="board:x"):
    return [a, b, ch, "W", "R", t - 60 if t is not None else None, t, 0.1, "read in code", merged]


class OracleHelperTests(unittest.TestCase):
    def test_is_named(self):
        self.assertTrue(oracle.is_named("[CREDENTIAL 5]"))
        self.assertFalse(oracle.is_named("run:abc"))
        self.assertFalse(oracle.is_named(""))
        self.assertFalse(oracle.is_named(None))

    def test_prepare_drops_undated_and_sorts(self):
        raw = {"columns": COLS, "rows": [msg("a", "b", 300), msg("b", "a", None), msg("a", "c", 100, merged=1)]}
        m = oracle.prepare_messages(raw)
        self.assertEqual([x["read_t"] for x in m], [100, 300])
        self.assertTrue(m[0]["merged"])

    def test_message_stats_relations(self):
        raw = {"columns": COLS, "rows": [
            msg("a", "b", 1), msg("a", "b", 2), msg("b", "a", 3, merged=1),
            msg("a", "a", 4),                       # a self-pair: counted by the network, not by Compare
            msg("run:1", "a", 5, merged=1),         # anonymous: not named
        ]}
        st = oracle.message_stats(oracle.prepare_messages(raw))
        self.assertEqual(st["all"], 5)
        self.assertEqual(st["named"], 4)
        self.assertEqual(st["named_merged"], 1)
        self.assertEqual(st["named_exact"], 3)
        self.assertEqual(st["named"], st["named_exact"] + st["named_merged"])
        self.assertEqual(st["merged_all"], 2)
        self.assertEqual(st["named_pairs"], 3)
        self.assertEqual(st["named_pairs_no_self"], 2)
        self.assertEqual(st["named_nodes"], {"a", "b"})

    def test_hour_to_epoch(self):
        self.assertEqual(oracle.hour_to_epoch("1970-01-01 01"), 3600)
        self.assertEqual(oracle.hour_to_epoch("1970-01-01 01:30"), 5400)
        self.assertEqual(oracle.hour_to_epoch("at or before 1970-01-02"), 86400)
        self.assertIsNone(oracle.hour_to_epoch("soon"))
        self.assertIsNone(oracle.hour_to_epoch(None))

    def test_signals_in_range_keeps_the_end_of_the_last_hour(self):
        hours = ["1970-01-01 01", "1970-01-01 03"]
        sigs = [{"t": 3599}, {"t": 3600}, {"t": 4 * 3600}, {"t": 4 * 3600 + 1}, {"t": None}]
        self.assertEqual([g["t"] for g in oracle.signals_in_range(sigs, hours)], [3600, 4 * 3600])
        self.assertEqual(oracle.signals_in_range(sigs, []), [])

    def test_first_by_family(self):
        sigs = [{"family": "single", "name": "a"}, {"family": "joint", "name": "b"}, {"family": "single", "name": "c"}]
        fb = oracle.first_by_family(sigs)
        self.assertEqual(fb["single"]["name"], "a")
        self.assertEqual(fb["joint"]["name"], "b")

    def test_checks_equal_and_relation(self):
        out = io.StringIO()
        c = oracle.Checks(out)
        self.assertTrue(c.equal("same", x=1, y=1))
        self.assertFalse(c.equal("differ", x=1, y=2))
        self.assertFalse(c.equal("missing", x=1, y=None))
        self.assertTrue(c.relation("rel", 3 == 2 + 1, "3 = 2 + 1"))
        self.assertEqual([r["check"] for r in c.failed], ["differ", "missing"])
        self.assertIn("FAIL  differ: x=1, y=2", out.getvalue())

    def test_run_checks_on_consistent_data(self):
        """A tiny consistent dataset passes every check; breaking one count fails exactly that check."""
        rows = [msg("a", "b", 3600), msg("b", "a", 3700, merged=1)]
        sim = {"messages": [1], "harmful": [1], "harm_total": 1,
               "signals": [{"key": "replay:first: x", "family": "single", "name": "x", "time": "1970-01-01 01:00", "t": 3600,
                            "harm_share_after": 1.0}]}
        summary = {"name": "t", "records": 4, "timed": 2, "actions": {"named_actors": 2, "named_actors_dated": 2},
                   "actor_kinds": {"token": 2}, "harm_events_timed": 1, "replay": [{"signal": "first: x"}],
                   "activity_by_hour": {"1970-01-01 01": {"x": 2}},
                   "flow": {"deliveries": 2, "deliveries_between_named_actors": 2, "named_actor_pairs": 2,
                            "coarse_channel_deliveries": 1, "channels": 1, "channel_types": {"board": {"channels": 1}}}}
        compare_a = {"named_actors": 2, "messages_named": 2, "messages_named_exact": 1, "messages_named_merged": 1,
                     "pairs": 2, "dated_share": 0.5, "signals": 1, "harm_total": 1, "places": 1,
                     "first_sign": {"single": {"name": "x", "time": "1970-01-01 01:00"}}}
        d = {"summary": summary, "messages": {"columns": COLS, "rows": rows}, "sim": sim,
             "gaps": {"rows": [{"key": "identity", "count": 2}, {"key": "merged", "count": 1, "of": 2}, {"key": "time", "count": 2}]},
             "lanes": {"actors": [{"actor": "a", "kind": "token"}, {"actor": "b", "kind": "token"},
                                  {"actor": "(anonymous runs)", "kind": "runs"}]},
             "pairs": {"total": 2, "rows": [{"messages": 1}, {"messages": 1}]}, "events": {"total": 4, "timed": 2},
             "identity": {"estimate": {"named_actors": 2}}, "roles": {"named_actors": 2, "messages_between_named": 2},
             "compare": {"a": compare_a}}
        c = oracle.run_checks(d, out=None)
        self.assertEqual(c.failed, [], c.failed)
        d["gaps"]["rows"][0]["count"] = 3
        c = oracle.run_checks(d, out=None)
        self.assertEqual(len(c.failed), 1)
        self.assertIn("named actors", c.failed[0]["check"])

    def test_run_checks_reports_a_failed_endpoint(self):
        d = {"summary": {"flow": {}, "actions": {"named_actors": 0}}, "messages": RuntimeError("HTTP 500")}
        for k in ("sim", "gaps", "lanes", "pairs", "events", "identity", "roles", "compare"):
            d[k] = RuntimeError("down")
        c = oracle.run_checks(d, out=None)
        self.assertTrue(c.failed)
        self.assertTrue(all("could not run" in r["detail"] for r in c.failed))


class SmokeSetupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_make_odd_writes_every_case(self):
        cases = dict(smoke.make_odd(self.d))
        self.assertEqual(set(cases), {"text-only folder", "one-line file", "empty file", "header-only CSV",
                                      "JSONL with a broken line", "non-UTF-8 CSV"})
        self.assertEqual(os.path.getsize(cases["empty file"]), 0)
        with open(cases["non-UTF-8 CSV"], "rb") as f:
            self.assertRaises(UnicodeDecodeError, f.read().decode, "utf-8")
        self.assertTrue(os.path.isdir(cases["text-only folder"]))

    def test_dataset_specs(self):
        specs = smoke.dataset_specs(["demo", "samples", "mine=" + self.d + "::generic.json"], self.d)
        labels = [s[0] for s in specs]
        self.assertIn("demo swarm", labels)
        self.assertTrue(sum(1 for x in labels if x.startswith("sample ")) >= 8)
        self.assertIn(("mine", self.d, "generic.json"), specs)

    def test_errorish_warn_boxes(self):
        self.assertTrue(smoke.ERRORISH.search("x is not defined"))
        self.assertTrue(smoke.ERRORISH.search("HTTP 500"))
        self.assertFalse(smoke.ERRORISH.search("Correlation, not causation."))


if __name__ == "__main__":
    unittest.main()

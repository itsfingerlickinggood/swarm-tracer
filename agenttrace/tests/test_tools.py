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


class CoverageLinesTests(unittest.TestCase):
    """tools/coverage_lines.py: a module called like a standard-library one, run in a thread, is still counted
    (agenttrace/server.py read 0% before: http/server.py was ignored by name, and its handlers run in threads)."""

    def test_thread_and_same_named_module_are_counted(self):
        import importlib.util
        import sys
        import threading
        import http.server  # noqa: F401  the standard-library module whose bare name is also "server"
        from agenttrace.tools import coverage_lines as C
        d = os.path.realpath(tempfile.mkdtemp(prefix="st-cov-test-"))
        src = ("def in_main(x):\n    y = x + 1\n    return y\n\n\n"
               "def in_thread(out):\n    out.append(1)\n    out.append(2)\n\n\n"
               "def never():\n    return 'not run'\n")
        path = os.path.join(d, "server.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        saved = (C.PKG, C.run_tests, sys.gettrace())

        def fake_tests(_dir):
            spec = importlib.util.spec_from_file_location("st_cov_probe_server", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.in_main(1)
            got = []
            t = threading.Thread(target=mod.in_thread, args=(got,))
            t.start()
            t.join()
            return got
        try:
            C.PKG, C.run_tests = d, fake_tests
            res, out = C.with_trace("unused")
        finally:
            C.PKG, C.run_tests = saved[0], saved[1]
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(res, [1, 2])
        self.assertIs(sys.gettrace(), saved[2])          # the tracer that was there before is back
        lines, covered = out[path]
        # 3 def lines + 2 in in_main + 2 in in_thread are run; the body of never() is not
        self.assertEqual((lines, covered), (8, 7))


class RoutesPendingTests(unittest.TestCase):
    """tools/routes.py: a route that is still computing answers a placeholder; the tool must hash the answer, not
    the placeholder (the unexplained fx_evolution_cluster difference on the wiki logs was this, not hash order)."""

    def test_a_pending_reply_is_asked_again(self):
        from agenttrace.tools import routes
        replies = [(200, {"pending": True, "message": "wait"}, 0.1), (200, {"pending": True}, 0.1), (200, {"clusters": [1, 2]}, 0.1)]
        asked = []

        def get(base, path, timeout=0):
            asked.append(path)
            return replies[min(len(asked), len(replies)) - 1]
        self.assertEqual(routes.settled("http://x", "/api/x/fx_evolution_cluster?id=0", wait=5, pause=0, get=get), (200, {"clusters": [1, 2]}))
        self.assertEqual(len(asked), 3)

    def test_it_gives_up_after_the_wait_and_other_replies_pass_through(self):
        from agenttrace.tools import routes
        always = lambda base, path, timeout=0: (200, {"pending": True}, 0.0)
        self.assertEqual(routes.settled("http://x", "/p", wait=0, pause=0, get=always), (200, {"pending": True}))
        for data in ({"pending": False, "rows": []}, {"pending": "yes"}, [1], "text", {"pending_records": 3}):
            self.assertEqual(routes.settled("http://x", "/p", wait=5, pause=0, get=lambda b, p, timeout=0, d=data: (200, d, 0.0)), (200, data))


if __name__ == "__main__":
    unittest.main()

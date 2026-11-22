"""Light tests for the interaction test and the demo-video builder: the parts that need no browser.

The browser run itself is `python3 -m agenttrace.tools.interact --quick` (also a stage of tools.check --full).
"""
import io
import os
import tempfile
import unittest

from agenttrace.tools import demo_video, interact


class SamplePlan(unittest.TestCase):
    ITEMS = ([{"kind": "button", "sig": "button|button.a", "n": i} for i in range(5)]
             + [{"kind": "button", "sig": "button|button.b", "n": 0}]
             + [{"kind": "row", "sig": "row|tr.click", "n": i} for i in range(40)]
             + [{"kind": "file-input", "sig": "file-input|input:file", "n": 0}, {"kind": "disabled", "sig": "disabled|button", "n": 0}])

    def test_one_of_each_signature(self):
        plan = interact.sample_plan(self.ITEMS, per_sig=1)
        self.assertEqual([(p["sig"], p["n"]) for p in plan], [("button|button.a", 0), ("button|button.b", 0), ("row|tr.click", 0)])

    def test_first_last_middle(self):
        plan = interact.sample_plan(self.ITEMS, per_sig=3)
        self.assertEqual([p["n"] for p in plan if p["kind"] == "row"], [0, 39, 20])
        self.assertEqual([p["n"] for p in plan if p["sig"] == "button|button.a"], [0, 4, 2])

    def test_limits(self):
        plan = interact.sample_plan(self.ITEMS, per_sig=3, per_kind=2, max_sigs=1)
        self.assertEqual(len([p for p in plan if p["kind"] == "button"]), 2)
        self.assertEqual({p["sig"] for p in plan if p["kind"] == "button"}, {"button|button.a"})

    def test_never_files_or_disabled(self):
        self.assertFalse([p for p in interact.sample_plan(self.ITEMS, per_sig=9) if p["kind"] in ("file-input", "disabled")])


class KeyboardPass(unittest.TestCase):
    """The keyboard-access pass itself needs Chrome (python3 -m agenttrace.tools.interact --keyboard); here only what
    can be checked without one: what it looks for, and that the app still has the handlers it presses on."""

    def test_targets_cover_chips_rows_and_terms(self):
        whats = [w for _n, _s, w in interact.KB_TARGETS]
        self.assertEqual(sorted(whats), ["actor", "agent", "place", "record", "row", "term"])
        sel = {w: s for _n, s, w in interact.KB_TARGETS}
        self.assertIn("tr.click", sel["row"])
        self.assertIn("data-id", sel["record"])
        self.assertIn("events", interact.KB_TABS)

    def test_the_pass_uses_real_keys_only(self):
        import inspect
        src = inspect.getsource(interact.Runner.keyboard_access_checks) + inspect.getsource(interact.Runner.kb_tab_to)
        self.assertNotIn("click_sel", src)
        self.assertNotIn(".click()", src)
        self.assertNotIn("dispatchMouseEvent", src)
        for key in ('self.key("Tab")', '"Enter"', '"Space"', '"Escape"', '"ArrowDown"', "shift=True"):
            self.assertIn(key, src, key)
        self.assertEqual(interact.KEYS["Space"], 32)

    def test_app_has_the_keyboard_handlers_the_pass_relies_on(self):
        with open(os.path.join(interact.PKG, "app", "core.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('const KEY_TARGETS = "tr.click,.ent,', js)                          # chips and rows get a tab stop
        self.assertIn('(e.key !== "Enter" && e.key !== " ")', js)                         # Enter and Space press them
        self.assertIn('e.key === "Escape" || e.key === "Tab") close();', js)              # the search results close when focus moves on
        self.assertIn("glossaryOpener", js)                                               # the glossary gives the focus back
        with open(os.path.join(interact.PKG, "app", "app.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn(":focus-visible{outline:2px solid", css)

    @unittest.skipUnless(os.environ.get("SWARM_TRACER_BROWSER_TESTS") and interact.find_chrome(), "set SWARM_TRACER_BROWSER_TESTS=1 (needs Chrome) to run the keyboard pass here")
    def test_keyboard_pass_in_chrome(self):
        srv = interact.Server(interact.free_port(), os.path.join(interact.PKG, "samples", "demo_swarm"))
        try:
            self.assertTrue(srv.wait(300), srv.output(300))
            ds = interact.run_dataset("demo swarm", srv.base, keyboard_only=True)
        finally:
            srv.stop()
        bad = [c for c in ds["checks"] if not c["ok"]]
        self.assertEqual(bad, [])
        self.assertGreaterEqual(len(ds["checks"]), 30)


class Report(unittest.TestCase):
    def test_diff(self):
        self.assertEqual(interact.diff_snap({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "c": 4}), ["b", "c"])

    def test_table_and_failures(self):
        ds = {"dataset": "demo", "base": "http://x", "mode": "quick", "seconds": 1.0, "checks": [{"name": "back", "ok": False, "note": "lost"}, {"name": "esc", "ok": True, "note": ""}],
              "pages": [{"page": "overview", "found": {"button": 4, "row": 9}, "exercised": {"button": 2, "row": 1}, "passed": {"button": 2},
                         "failed": [{"kind": "row", "sig": "row|tr.click", "note": "dead: no effect", "label": "x"}], "skipped": []}]}
        buf = io.StringIO()
        self.assertEqual(interact.print_report([ds], out=buf), 2)
        text = buf.getvalue()
        self.assertIn("overview", text)
        self.assertIn("button:2/4", text)
        self.assertIn("FAIL check: back", text)
        self.assertIn("INTERACT 2 failures", text)
        self.assertEqual(interact.totals(ds)["row"], {"found": 9, "exercised": 1, "passed": 0, "failed": 1, "skipped": 0})

    def test_writes_stay_in_the_page(self):
        # the page-side script must answer every non-GET itself and decline confirm()/prompt()
        self.assertIn("m !== 'GET' && m !== 'HEAD'", interact.INIT_JS)
        self.assertIn(interact.BLOCK_NOTE, interact.INIT_JS)
        self.assertIn("window.confirm = () => { ix.dialogs++; return false; }", interact.INIT_JS)


SCRIPT = """# Demo

Video: `docs/assets/demo.mp4` (about 4 min 14 s, 1440x900).

## 1. The problem

Screens: `#tab=overview`

The release gives us the logs: 189,579 records from that incident.

## 2. Who talked to whom

Screens: `#tab=network&scroll=470`, `#tab=timeline`

Each write counts once per reader. That leaves 19 messages in all, six of them between named tokens, in five sender-receiver pairs. A first count said 166.
"""
NUMBERS = {"records": 189579, "name": "x", "messages": 24, "named": 6, "pairs": 5, "tokens": 8, "inside": 3, "agent_messages": 3}


class DemoScript(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "demo-script.md")
        with open(self.path, "w") as f:
            f.write(SCRIPT)

    def test_parse(self):
        secs = demo_video.parse_script(self.path)
        self.assertEqual([s["n"] for s in secs], [1, 2])
        self.assertEqual(secs[1]["screens"], ["#tab=network&scroll=470", "#tab=timeline"])
        self.assertTrue(secs[1]["text"].startswith("Each write counts once"))
        self.assertNotIn("Screens", secs[1]["text"])

    def test_stale_numbers_are_caught(self):
        probs = demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS)
        self.assertTrue(any("19 messages" in p for p in probs), probs)
        self.assertTrue(any("inside one estimated agent" in p for p in probs), probs)

    def test_update_then_clean(self):
        self.assertTrue(demo_video.update_script(self.path, NUMBERS))
        with open(self.path) as f:
            text = f.read()
        self.assertIn("That leaves 24 messages in all, six of them between eight named tokens, in five sender-receiver pairs. "
                      "Three of those six are between tokens that Swarm Tracer estimates belong to one agent. A first count said 166.", text)
        self.assertEqual(demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS), [])
        # one message more, late in the day: the same command rewrites it again
        self.assertTrue(demo_video.update_script(self.path, dict(NUMBERS, messages=25, named=7, tokens=9, pairs=6)))
        self.assertEqual(demo_video.check_numbers(demo_video.parse_script(self.path), dict(NUMBERS, messages=25, named=7, tokens=9, pairs=6)), [])
        self.assertFalse(demo_video.update_script(self.path, dict(NUMBERS, messages=25, named=7, tokens=9, pairs=6)))

    def test_no_merges_drops_the_agent_sentence(self):
        s = demo_video.claim_sentence(dict(NUMBERS, inside=0))
        self.assertNotIn("one agent", s)

    def _deliveries_script(self, n):
        with open(self.path, "w") as f:
            f.write(SCRIPT.replace("That leaves 19 messages in all, six of them between named tokens",
                                   f"That leaves {n} deliveries in all, six of them between eight named tokens")
                    + " Three of those six are between tokens that Swarm Tracer estimates belong to one agent.\n")

    def test_deliveries_wording_is_understood(self):
        # since v2.3.0 the script says "deliveries", not "messages": the same count is checked
        self._deliveries_script(24)
        self.assertEqual(demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS), [])

    def test_deliveries_wording_is_still_checked(self):
        self._deliveries_script(19)
        probs = demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS)
        self.assertEqual(probs, ["script says 19 deliveries in all; the app has 24"])
        # another noun is not accepted as the count sentence
        with open(self.path, "w") as f:
            f.write(SCRIPT.replace("19 messages in all", "24 contacts in all"))
        probs = demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS)
        self.assertTrue(any("no sentence" in p for p in probs), probs)

    def test_update_keeps_the_scripts_word(self):
        self._deliveries_script(19)
        self.assertTrue(demo_video.update_script(self.path, NUMBERS))
        with open(self.path) as f:
            text = f.read()
        self.assertIn("That leaves 24 deliveries in all, six of them between eight named tokens, in five sender-receiver pairs. "
                      "Three of those six are between tokens", text)
        self.assertNotIn("messages in all", text)
        self.assertEqual(demo_video.check_numbers(demo_video.parse_script(self.path), NUMBERS), [])
        self.assertIn("1 delivery in all", demo_video.claim_sentence(dict(NUMBERS, messages=1), "deliveries"))


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

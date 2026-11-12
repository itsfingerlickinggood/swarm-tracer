"""Forensics, content tracing: grades per message, hand-overs with no shared place, one string's holders."""
import os
import tempfile
import unittest

from agenttrace import fx_content as fx
from agenttrace import groundtruth
from agenttrace.session import Session


def _sim(mode, agents=14, seed=2):
    d = tempfile.mkdtemp(prefix="fxc_test_")
    groundtruth.make(d, agents=agents, seed=seed, mode=mode)
    s = Session()
    s.load(os.path.join(d, "trace.jsonl"), "code_traces.json")
    return s


class ItemTests(unittest.TestCase):
    def test_shapes(self):
        got = fx.items_of("fetch('results/ddenv.txt'); x = 'HELLO_MAY64_'; document.body.innerText = r.status; "
                          "t = '[CREDENTIAL 9]'; b = '[ENCODED BLOB 12]'; open('guard62943.so'); parse_matrix(1)")
        self.assertIn("results/ddenv.txt", got)
        self.assertIn("HELLO_MAY64_", got)
        self.assertIn("[ENCODED BLOB 12]", got)
        self.assertIn("guard62943.so", got)
        self.assertIn("parse_matrix", got)
        self.assertNotIn("[CREDENTIAL 9]", got)            # identity tokens are another analysis
        self.assertNotIn("document.body.innerText", got)   # a property chain is not content
        self.assertNotIn("r.status", got)
        self.assertTrue(fx.specific("guard62943.so"))
        self.assertFalse(fx.specific("parse_matrix"))


class SimulatedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benign = _sim("benign")
        cls.coord = _sim("coordinated")

    def test_no_session(self):
        with self.assertRaises(LookupError):
            fx.GET["content"]({"session": None}, {})

    def test_shape(self):
        r = fx.GET["content"]({"session": self.coord}, {})
        sm = r["summary"]
        self.assertEqual(sm["messages"], len(self.coord.flow["_deliveries"]))
        self.assertEqual(sum(sm["grades"].values()), sm["messages"])
        self.assertEqual(len(r["messages"]), sm["messages"])
        for m in r["messages"]:
            self.assertIn(m["grade"], ("used", "fetched only", "unclear"))
            self.assertTrue(m["why"])
            for u in m["used"]:
                self.assertLessEqual(len(u["write_snip"]), fx.QUOTE + 2)
                self.assertGreaterEqual(u["after_h"], 0)
        self.assertIn("benign", sm["simulated"])
        self.assertIs(fx.build(self.coord), fx.build(self.coord))      # cached on the session

    def test_benign_baseline_is_quiet(self):
        sm = fx.summary(self.benign)
        self.assertEqual(sm["grades"]["used"], 0)
        self.assertEqual(sm["handovers"]["strong"], 0)

    def test_readers_that_only_fetch_are_not_users(self):
        # the simulated readers fetch a message and do nothing with it
        sm = fx.summary(self.coord)
        self.assertEqual(sm["grades"]["used"], 0)
        self.assertEqual(sm["handovers"]["strong"], 0)

    def test_item_chain(self):
        s = self.coord
        d = s.flow["_deliveries"][0]
        item = next(iter(sorted(fx.items_of(s.by_id[d["write_id"]].text), key=len, reverse=True)))
        r = fx.GET["content_item"]({"session": s}, {"q": item})
        self.assertGreaterEqual(r["records"], 1)
        self.assertTrue(r["holders"])
        self.assertIn(d["write_id"], [c["id"] for c in r["chain"]])
        with self.assertRaises(ValueError):
            fx.GET["content_item"]({"session": s}, {"q": "ab"})


if __name__ == "__main__":
    unittest.main()

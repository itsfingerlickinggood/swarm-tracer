"""Known-answer tests for agenttrace.messages (channel deliveries and content spread).

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import tempfile
import unittest

from agenttrace import analysis, messages, reconstruct
from agenttrace.tests.test_reconstruct import PACK, ev, load_pack

CHANNEL_PACK = dict(PACK, channels=[{"name": "repo", "pattern": r"repo/(R\w+)", "write": r"WRITE"}],
                    shared_identities=["[TOKEN 0]"])
BASE = 1783600000


def build(events):
    d = tempfile.mkdtemp()
    pack = load_pack(d, dict(CHANNEL_PACK, time=dict(PACK["time"], min_points=20)))
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    return messages.message_flow(events, pack, rec, res)


def story():
    ev_ = [ev(i, f"at {BASE + i * 600} auth=[TOKEN 0] idle") for i in range(40)]
    ev_[5] = ev(5, f"at {BASE + 5 * 600} auth=[TOKEN 1] repo/RA WRITE")
    ev_[8] = ev(8, f"at {BASE + 8 * 600} auth=[TOKEN 2] repo/RA read")       # delivery 1 -> 2
    ev_[9] = ev(9, f"at {BASE + 9 * 600} auth=[TOKEN 1] repo/RA read")       # same actor: not a delivery
    ev_[3] = ev(3, f"at {BASE + 3 * 600} auth=[TOKEN 3] repo/RB read")       # read before any write
    ev_[12] = ev(12, f"at {BASE + 12 * 600} auth=[TOKEN 4] repo/RB WRITE")
    ev_[15] = ev(15, f"at {BASE + 15 * 600} auth=[TOKEN 0] repo/RB read")    # shared key: anonymous run
    prog = "import os; send(data); loop(); x = 1; y = 2; z = 3; done"
    ev_[20] = ev(20, f"auth=[TOKEN 5] {prog} at {BASE + 20 * 600}")
    ev_[30] = ev(30, f"auth=[TOKEN 6] {prog} at {BASE + 30 * 600}")
    return ev_


class MessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = build(story())
        cls.dels = cls.flow["_deliveries"]

    def test_delivery_between_different_actors(self):
        pairs = {(d["from"], d["to"], d["channel"]) for d in self.dels}
        self.assertIn(("[TOKEN 1]", "[TOKEN 2]", "repo:RA"), pairs)

    def test_no_delivery_to_the_writer_itself(self):
        self.assertFalse(any(d["from"] == d["to"] for d in self.dels))

    def test_read_before_write_is_not_a_delivery(self):
        self.assertFalse(any(d["to"] == "[TOKEN 3]" for d in self.dels))

    def test_shared_identity_becomes_a_run(self):
        d = [x for x in self.dels if x["channel"] == "repo:RB"]
        self.assertEqual(len(d), 1)
        self.assertTrue(d[0]["to"].startswith("run:"))

    def test_latency(self):
        d = [x for x in self.dels if x["to"] == "[TOKEN 2]"][0]
        self.assertAlmostEqual(d["latency_h"], 0.5, places=1)

    def test_first_named_delivery(self):
        self.assertEqual(self.flow["first_named_delivery"]["read_id"], "E0008")

    def test_content_spread_source_and_adopter(self):
        # the identical read lines of E0008 and E0009 also form a family; pick the program's
        s = [x for x in self.flow["content_spread"] if x["source_record"] == "E0020"][0]
        self.assertEqual(s["source"], "[TOKEN 5]")
        self.assertEqual(s["adopters"][0]["actor"], "[TOKEN 6]")
        self.assertAlmostEqual(s["adopters"][0]["hours_after_source"], 10 * 600 / 3600, places=1)

    def test_channel_performance(self):
        ra = [c for c in self.flow["top_channels"] if c["channel"] == "repo:RA"][0]
        self.assertEqual((ra["writes"], ra["reads"], ra["deliveries"]), (1, 2, 1))


if __name__ == "__main__":
    unittest.main()


class RetryTests(unittest.TestCase):
    def test_same_program_rerun_is_not_a_delivery(self):
        prog = "fetch(repo/RX) with a long enough body to count as a program: a b c d e f g h"
        evs = [ev(i, f"at {BASE + i * 600} auth=[TOKEN 0] idle") for i in range(40)]
        evs[5] = ev(5, f"at {BASE + 5 * 600} auth=[TOKEN 1] {prog} WRITE")
        evs[6] = ev(6, f"at {BASE + 6 * 600} auth=[TOKEN 2] {prog} WRITE")   # same program, other token
        evs[7] = ev(7, f"at {BASE + 7 * 600} auth=[TOKEN 3] {prog}")         # same text minus WRITE: a read
        flow = build(evs)
        pairs = {(d["from"], d["to"]) for d in flow["_deliveries"]}
        self.assertIn(("[TOKEN 2]", "[TOKEN 3]"), pairs)          # different program text: counted
        self.assertNotIn(("[TOKEN 1]", "[TOKEN 2]"), pairs)       # both writes: never a delivery

    def test_mention_judged_by_its_own_context(self):
        filler = " ".join(["pad"] * 80)
        evs = [ev(i, f"at {BASE + i * 600} auth=[TOKEN 0] idle") for i in range(40)]
        evs[5] = ev(5, f"at {BASE + 5 * 600} auth=[TOKEN 1] repo/RA WRITE")
        evs[9] = ev(9, f"at {BASE + 9 * 600} auth=[TOKEN 2] repo/RA {filler} {filler} {filler} then WRITE repo/RZ")
        flow = build(evs)
        self.assertIn(("[TOKEN 1]", "[TOKEN 2]", "repo:RA"),
                      {(d["from"], d["to"], d["channel"]) for d in flow["_deliveries"]})


class RepeatReadTests(unittest.TestCase):
    def test_reading_the_same_write_again_is_one_message(self):
        evs = [ev(i, f"at {BASE + i * 600} auth=[TOKEN 0] idle") for i in range(40)]
        evs[5] = ev(5, f"at {BASE + 5 * 600} auth=[TOKEN 1] repo/RA WRITE")
        evs[8] = ev(8, f"at {BASE + 8 * 600} auth=[TOKEN 2] repo/RA poll")
        evs[11] = ev(11, f"at {BASE + 11 * 600} auth=[TOKEN 2] repo/RA poll again")   # same write, same reader
        evs[14] = ev(14, f"at {BASE + 14 * 600} auth=[TOKEN 1] repo/RA WRITE v2")
        evs[17] = ev(17, f"at {BASE + 17 * 600} auth=[TOKEN 2] repo/RA poll")         # a new write: a new message
        flow = build(evs)
        got = [(d["write_id"], d["read_id"]) for d in flow["_deliveries"] if d["to"] == "[TOKEN 2]"]
        self.assertEqual(got, [("E0005", "E0008"), ("E0014", "E0017")])
        self.assertEqual(flow["repeat_reads"], 1)


class TruncatedRetryTests(unittest.TestCase):
    def test_cut_short_copy_of_the_same_program_is_not_a_delivery(self):
        body = " ".join(f"step{k}" for k in range(70))
        evs = [ev(i, f"at {BASE + i * 600} auth=[TOKEN 0] idle") for i in range(40)]
        evs[5] = ev(5, f"{body} repo/RQ WRITE auth=[TOKEN 1] at {BASE + 5 * 600}")
        evs[6] = ev(6, f"{body} repo/RQ auth=[TOKEN 2] at {BASE + 6 * 600}")      # same start, cut short
        flow = build(evs)
        self.assertNotIn(("[TOKEN 1]", "[TOKEN 2]"), {(d["from"], d["to"]) for d in flow["_deliveries"]})
        self.assertEqual(flow["reads_dropped_as_same_program"], 1)

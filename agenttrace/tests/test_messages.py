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


class VerbRuleTests(unittest.TestCase):
    """judge_span / judge_how on the shapes found in the audit of the real release."""
    WRX = __import__("re").compile(r"/commit/|x-ndjson|method:\s*['\"](POST|PUT)|[(,]\s*method\s*=\s*['\"]POST|Request\([^)]{0,120}data\s*=", __import__("re").I)
    RRX = __import__("re").compile(r"method:\s*['\"](GET|HEAD)|/resolve/", __import__("re").I)
    P = "https://huggingface.co/datasets/[X 1]"

    def how(self, text):
        i = text.index("huggingface.co/datasets/[X 1]")
        return messages.judge_how(text, i, i + len("huggingface.co/datasets/[X 1]"), self.WRX, self.RRX)

    def test_helper_call_verb_is_read_from_its_own_call(self):
        text = f"src='{self.P}';_,d=Q('GET',src,h={{}});r,_=Q('POST',B+R+'/blobs/uploads/',b'',H)"
        self.assertEqual(self.how(text)[0], "read")
        text = f"src='{self.P}';_,d=Q('POST',src,h={{}})"
        self.assertEqual(self.how(text)[0], "write")

    def test_a_name_given_another_value_stops_the_search(self):
        text = f"u='{self.P}';r=fetch(u,{{headers:{{}}}});u=l+'x';fetch(Q(u),{{method:'PUT'}})"
        self.assertEqual(self.how(text)[0], "read")

    def test_cut_off_call_and_hidden_lfs_operation_are_not_counted(self):
        self.assertEqual(self.how(f"x=await fetch('{self.P}',{{method")[0], "mention")
        self.assertEqual(self.how(f"x=fetch('{self.P}/info/lfs/objects/batch',{{method:'POST',body:B}})")[0], "mention")
        up = f"B={{operation:'upload'}};fetch('{self.P}/info/lfs/objects/batch',{{method:'POST',body:B}})"
        self.assertEqual(self.how(up)[:1] + self.how(up)[3:], ("write", "inferred"))

    def test_how_the_verb_was_found(self):
        self.assertEqual(self.how(f"fetch('{self.P}',{{method:'POST'}})")[3], "call")
        self.assertEqual(self.how(f"u='{self.P}';fetch(u,{{method:'POST'}})")[3], "inferred")
        self.assertEqual(self.how(f"see {self.P} for the data, then more text follows here to pad it out")[3], "default")

    def test_repository_held_in_a_variable_names_only_an_owner(self):
        text = f"fetch('{self.P}/'+repo+'/commit/main',{{method:'POST'}})"
        self.assertEqual(self.how(text)[0], "mention")


class GradeTests(unittest.TestCase):
    def ops(self, wt=1000, rt=1100):
        w = ("p:A", "write", "[T 1]", "token", wt, 1, "W")
        r = ("p:A", "read", "[T 2]", "token", rt, 2, "R")
        return [w, r]

    def run_grade(self, how, coarse=None, estimated=None, rt=1100):
        dels = messages.deliveries(self.ops(rt=rt), None, None, how, coarse, estimated)[0]
        self.assertEqual(len(dels), 1)
        return dels[0]["grade"]

    def test_direct_inferred_weak(self):
        self.assertEqual(self.run_grade({("W", "p:A"): "call", ("R", "p:A"): "call"}), "direct")
        self.assertEqual(self.run_grade({("W", "p:A"): "inferred", ("R", "p:A"): "call"}), "inferred")
        self.assertEqual(self.run_grade({("W", "p:A"): "call", ("R", "p:A"): "default"}), "weak")
        calls = {("W", "p:A"): "call", ("R", "p:A"): "call"}
        self.assertEqual(self.run_grade(calls, coarse=lambda ch: True), "weak")
        # a time estimated while the records are more than an hour apart
        self.assertEqual(self.run_grade(calls, estimated=lambda rid: rid == "R", rt=1000 + 2 * 3600), "weak")
        self.assertEqual(self.run_grade(calls, estimated=lambda rid: rid == "R", rt=1000 + 600), "direct")

    def test_no_grade_without_how(self):
        dels = messages.deliveries(self.ops())[0]
        self.assertNotIn("grade", dels[0])

    def test_flow_and_message_list_carry_the_grade(self):
        flow = build(story())
        self.assertTrue(all(d["grade"] in messages.GRADES for d in flow["_deliveries"]))
        self.assertEqual(sum(flow["deliveries_by_grade"].values()), len(flow["_deliveries"]))

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


# ------------------------------------------------------------------ rule integrity (docs/counting-rule.md)

REAL_PACK = None


def real_pack():
    """The code-traces pack as shipped: the verb vocabulary the release is counted with."""
    global REAL_PACK
    if REAL_PACK is None:
        import os
        from agenttrace import packs
        REAL_PACK = packs.load_pack(os.path.join(os.path.dirname(os.path.abspath(packs.__file__)), "packs", "code_traces.json"))
    return REAL_PACK


def judge_all(text):
    """[(place, op, how)] for every mention in the text, with the shipped pack."""
    out = []
    for name, rx, wrx, rrx in messages.compile_channels(real_pack()):
        for m in rx.finditer(text):
            if m.group(1):
                op, _lo, _hi, how = messages.judge_how(text, m.start(), m.end(), wrx, rrx)
                out.append((m.group(1), op, how))
    return out


class SpecRuleTests(unittest.TestCase):
    """One test per statement of docs/counting-rule.md that the audit or the crosscheck showed can go wrong."""
    A = "https://huggingface.co/datasets/own/a"
    B = "https://huggingface.co/api/datasets/own/b"

    def one(self, text):
        got = judge_all(text)
        self.assertEqual(len(got), 1, text)
        return got[0][1:]

    def test_R6_an_operation_in_the_next_call_does_not_make_a_read_a_write(self):
        # found by the crosscheck: a GET of A followed by a commit to B whose body says operation:'upload'
        text = (f"const r = await fetch('{self.A}/resolve/main/x.json', {{headers: {{}}}});\n"
                f"await fetch('{self.B}/commit/main', {{method: 'POST', body: JSON.stringify({{operation: 'upload', path: 'p'}})}});")
        self.assertEqual(judge_all(text), [("own/a", "read", "call"), ("own/b", "write", "inferred")])
        text = (f"const r = await fetch('{self.A}/resolve/main/x.json');await fetch('https://collector.example/c', "
                f"{{method: 'POST', body: JSON.stringify({{operation: 'upload', path: 'p'}})}});")
        self.assertEqual(self.one(text), ("read", "call"))

    def test_R6_lfs_batch_is_judged_by_its_operation(self):
        self.assertEqual(self.one(f"B={{operation:'upload'}};fetch('{self.A}/info/lfs/objects/batch',{{method:'POST',body:B}})"), ("write", "inferred"))
        xhr = f"x=new XMLHttpRequest;x.open('POST','{self.A}/info/lfs/objects/batch',0);x.send(JSON.stringify({{operation:'download'}}))"
        self.assertEqual(self.one(xhr), ("read", "inferred"))
        # the batch path swallowed by redaction: the operation in the call's own body still decides
        hidden = f"fetch('{self.A}',{{method:'POST',headers:{{'Content-Type':'application/vnd.git-lfs+json'}},body:`{{\"operation\":\"download\"}}`}})"
        self.assertEqual(self.one(hidden), ("read", "inferred"))
        self.assertEqual(self.one(f"x=fetch('{self.A}/info/lfs/objects/batch',{{method:'POST',body:B}})")[0], "mention")

    def test_R8_direct_calls(self):
        self.assertEqual(self.one(f"fetch('{self.B}/commit/main',{{method:'POST',body:b}})"), ("write", "call"))
        self.assertEqual(self.one(f"x=new XMLHttpRequest;x.open('GET','{self.A}/resolve/main/f',false);x.send()"), ("read", "call"))
        self.assertEqual(self.one(f"await fetch('{self.A}', {{headers: {{'Authorization': 'x'}}}})"), ("read", "default"))
        # the verb of the next request call does not count (R4, R16)
        text = f"fetch('{self.A}/x').then(r=>r.text()).then(t=>fetch('https://c.example/x',{{method:'POST',body:t}}))"
        self.assertEqual(self.one(text)[0], "read")

    def test_R9_never_passed_is_not_counted(self):
        self.assertEqual(self.one(f"u='{self.A}';console.log(1)")[0], "mention")
        self.assertEqual(self.one(f"u='{self.A}';r=fetch(u,{{headers:{{}}}})"), ("read", "inferred"))
        self.assertEqual(self.one(f"u='{self.B}/commit/main';r=fetch(u,{{method:'POST'}})"), ("write", "inferred"))
        self.assertEqual(self.one(f"u='{self.A}';s=f\"x.open('POST','{{u}}',0)\"")[0], "write")       # interpolated

    def test_R10_helper_arguments(self):
        self.assertEqual(self.one(f"src='{self.A}';d=Q(src,data=b)")[0], "write")
        self.assertEqual(self.one(f"src='{self.A}';d=Q(src,h)")[0], "read")
        self.assertEqual(self.one(f"u='{self.A}';q=urllib.request.Request(u,d,{{'Authorization':'x'}});r=urllib.request.urlopen(q)")[0], "write")
        self.assertEqual(self.one(f"u='{self.A}';q=urllib.request.Request(u,headers={{'Authorization':'x'}});r=urllib.request.urlopen(q)")[0], "read")
        self.assertEqual(self.one(f"u='{self.A}';q=urllib.request.Request(u,None,{{'Authorization':'x'}})")[0], "read")

    def test_R11_a_verb_beside_a_literal_in_a_helper_call(self):
        self.assertEqual(self.one(f"req('{self.A}', tok, 'POST', data)"), ("write", "inferred"))
        self.assertEqual(self.one(f"Q('POST','{self.A}','{{}}',W)"), ("write", "inferred"))
        self.assertEqual(self.one(f"Q('PUT', B+'{self.A}', body)"), ("write", "inferred"))
        self.assertEqual(self.one(f"Q('GET','{self.A}',W)")[0], "read")
        # a POST in an earlier call is not beside this literal
        self.assertEqual(self.one(f"Q('POST',other,b);R('{self.A}')")[0], "read")
        self.assertEqual(self.one(f"r=urllib.request.Request('{self.A}', d, H)")[0], "write")
        self.assertEqual(self.one(f"r=urllib.request.Request('{self.A}', headers=H)")[0], "read")

    def test_R12_request_written_as_data(self):
        self.assertEqual(self.one('{"u": "%s", "m": "POST", "b": "x"}' % self.A), ("write", "inferred"))
        self.assertEqual(self.one('{"u": "%s", "m": "GET"}' % self.A), ("read", "inferred"))
        self.assertEqual(self.one('{"url": "%s", "body": "x"}' % self.A), ("write", "inferred"))
        self.assertEqual(self.one('{"u": "%s"}\n' % self.A + "x" * 60)[1], "default")

    def test_R13_cut_off_call_and_bare_url(self):
        self.assertEqual(self.one(f"x=await fetch('{self.A}',{{method")[0], "mention")
        self.assertEqual(self.one(f"x=await fetch('{self.A}")[0], "mention")
        self.assertEqual(self.one(self.A)[0], "mention")
        # a redaction marker with a space in it is still part of the URL (found by the crosscheck)
        self.assertEqual(self.one("https://huggingface.co/datasets/[HF REPO 741]")[0], "mention")
        self.assertEqual(self.one("https://[SERVICE HOST 1]/https://huggingface.co/datasets/[HF REPO 741]?x=[REDACTED:query:1]")[0], "mention")
        self.assertEqual(self.one(f"see {self.A} for the data, then more text follows here to pad it out"), ("read", "default"))

    def test_R15_options_in_a_variable(self):
        self.assertEqual(self.one(f"o={{method:'POST',body:z}};u='{self.B}/x';fetch(u,o)")[0], "write")
        self.assertEqual(self.one(f"o={{headers:h}};u='{self.A}';fetch(u,o)")[0], "read")
        far = "o={headers:h};" + "pad=1;" * 60 + f"z={{method:'POST'}};u='{self.A}';fetch(u,o)"
        self.assertEqual(self.one(far)[0], "read")                       # another object's verb, 300+ characters on

    def test_R16_a_call_ends_at_its_parenthesis(self):
        self.assertEqual(self.one(f"u='{self.A}';r=fetch(u);o={{method:'POST'}}")[0], "read")
        self.assertEqual(self.one(f"u='{self.A}';r=fetch(u,{{method:'POST'}});")[0], "write")
        self.assertEqual(self.one(f"u='{self.A}';r=fetch(enc(u),{{method:'POST'}});")[0], "write")     # a nested parenthesis is not the end

    def test_R17_hidden_holder_and_a_later_write_through_a_name(self):
        # the one audited false link: a script that writes a script (the assignment is swallowed by redaction)
        script = ("b='\\n'.join(json.dumps(x) for x in [ENCODED BLOB] HOST 1]/https://huggingface.co/api/datasets/own/a';T='[C 1]';"
                  "s=f\"x=new XMLHttpRequest;x.open('POST','{u}',0);x.setRequestHeader('authorization','Bearer {T}');x.send({b!r})\";open('f','w').write(s)")
        self.assertEqual(self.one(script)[0], "mention")
        # no later write through a name: still a read by default
        reader = "[ENCODED BLOB]/https://huggingface.co/datasets/own/a'\nr=urllib.request.urlopen(urllib.request.Request(u,headers=H))"
        self.assertEqual(self.one(reader), ("read", "default"))
        # a later write to a literal URL is another place's call
        other = "[ENCODED BLOB]/https://huggingface.co/datasets/own/a';fetch('https://collector.example/c',{method:'POST',body:b})"
        self.assertEqual(self.one(other), ("read", "default"))
        # a visible assignment is R9's business, not R17's
        self.assertEqual(self.one(f"u='{self.A}';r=fetch(u,{{headers:{{}}}});fetch(v,{{method:'POST'}})")[0], "read")
        # the quoted value of a key in a config file is not held by a name: R17 leaves it to R14
        # (a dataset card pasted before a program that POSTs through a name; seven such records on the release)
        card = ("x.send(d);document.body.innerText=x.status\n---\nconfigs:\n- config_name: ref\n  data_files:\n  - split: train\n"
                "    path: \"reference://x.csv::https://huggingface.co/datasets/own/a\"\n---\n"
                "import urllib.request\nr=urllib.request.urlopen(urllib.request.Request(u,data=b))")
        self.assertEqual(self.one(card), ("read", "default"))
        flat = card.replace("  - split: train\n    path:", "  data_files:")
        self.assertEqual(self.one(flat), ("read", "default"))
        # the same string as a statement of its own is still R17's
        self.assertEqual(self.one(card.replace("    path: \"reference", "[ENCODED BLOB]reference"))[0], "mention")

    def test_R17_on_the_whole_pipeline(self):
        import datetime as dt
        from agenttrace.model import Event
        mk = lambda rid, text, t: Event(id=rid, text=text, kind="payload", time=dt.datetime.fromtimestamp(BASE + t, dt.timezone.utc))
        evs = [mk("W", f"x=new XMLHttpRequest;x.open('POST','{self.B}',0);x.setRequestHeader('authorization','Bearer [CREDENTIAL 5]');x.send(d)", 0),
               mk("G", "v=1;b=json.dumps(x) for x in [ENCODED BLOB] HOST 1]/https://huggingface.co/api/datasets/own/b';T='[CREDENTIAL 7]';"
                       "s=f\"x=new XMLHttpRequest;x.open('POST','{u}',0);x.setRequestHeader('authorization','Bearer {T}')\";open('f','w').write(s)", 60),
               mk("R", f"r=await fetch('{self.B}', {{headers: {{'Authorization': 'Bearer [CREDENTIAL 9]'}}}})", 120)]
        res = analysis.analyze(evs, real_pack())
        rec = reconstruct.reconstruct(evs, real_pack(), res)
        flow = messages.message_flow(evs, real_pack(), rec, res)
        self.assertEqual([(d["write_id"], d["read_id"]) for d in flow["_deliveries"]], [("W", "R")])


def flow_of(events, **pack_overrides):
    d = tempfile.mkdtemp()
    pack = load_pack(d, dict(CHANNEL_PACK, time=dict(PACK["time"], min_points=20), **pack_overrides))
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    return messages.message_flow(events, pack, rec, res), messages.channel_ops(events, pack, rec, res)


def at(i):
    return f"at {BASE + i * 600}"


def filler(n=40):
    return [ev(i, f"{at(i)} auth=[TOKEN 0] idle") for i in range(n)]


class CountTests(unittest.TestCase):
    """The numbers the report quotes, on a story with known answers (R23 to R30)."""

    @classmethod
    def setUpClass(cls):
        evs = filler()
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE")
        evs[4] = ev(4, f"{at(4)} auth=[TOKEN 2] repo/RA read")          # 1 -> 2
        evs[6] = ev(6, f"{at(6)} auth=[TOKEN 3] repo/RA read")          # 1 -> 3
        evs[8] = ev(8, f"{at(8)} auth=[TOKEN 2] repo/RA WRITE")
        evs[10] = ev(10, f"{at(10)} auth=[TOKEN 1] repo/RA read")       # 2 -> 1 (the latest write, R26)
        evs[12] = ev(12, f"{at(12)} auth=[TOKEN 3] repo/RA read")       # 2 -> 3
        evs[14] = ev(14, f"{at(14)} auth=[TOKEN 0] repo/RA read")       # 2 -> an anonymous run
        evs[16] = ev(16, f"{at(16)} auth=[TOKEN 4] repo/RB WRITE")      # never read
        evs[18] = ev(18, f"{at(18)} auth=[TOKEN 5] repo/RC read")       # read, never written
        cls.flow, cls.ops = flow_of(evs)
        cls.dels = cls.flow["_deliveries"]

    def test_R30_counts(self):
        f = self.flow
        self.assertEqual(f["deliveries"], 5)
        self.assertEqual(f["deliveries_between_named_actors"], 4)
        self.assertEqual(f["named_actor_pairs"], 4)
        self.assertEqual(f["actor_pairs"], 5)
        self.assertEqual(f["deliveries_order_unknown"], 0)
        self.assertEqual(f["repeat_reads"], 0)
        self.assertEqual(f["direct_messages"], 0)
        self.assertEqual(f["overwrites"], 0)
        self.assertEqual(sorted((d["write_id"], d["read_id"]) for d in self.dels),
                         [("E0002", "E0004"), ("E0002", "E0006"), ("E0008", "E0010"), ("E0008", "E0012"), ("E0008", "E0014")])

    def test_R26_latest_earlier_write(self):
        by_read = {d["read_id"]: d["write_id"] for d in self.dels}
        self.assertEqual(by_read["E0012"], "E0008")
        self.assertEqual(by_read["E0006"], "E0002")

    def test_first_named_delivery_and_pairs(self):
        f = self.flow
        self.assertEqual((f["first_named_delivery"]["write_id"], f["first_named_delivery"]["read_id"]), ("E0002", "E0004"))
        self.assertEqual(f["first_named_delivery_any_channel"]["read_id"], "E0004")
        self.assertEqual({(p["from"], p["to"]): p["deliveries"] for p in f["top_pairs"]},
                         {("[TOKEN 1]", "[TOKEN 2]"): 1, ("[TOKEN 1]", "[TOKEN 3]"): 1, ("[TOKEN 2]", "[TOKEN 1]"): 1, ("[TOKEN 2]", "[TOKEN 3]"): 1})
        self.assertTrue(all(not p["from"].startswith("run:") and not p["to"].startswith("run:") for p in f["top_pairs"]))

    def test_channel_table(self):
        ch = {c["channel"]: c for c in self.flow["_channels"]}
        ra, rb, rc = ch["repo:RA"], ch["repo:RB"], ch["repo:RC"]
        self.assertEqual((ra["writes"], ra["reads"], ra["writers"], ra["readers"], ra["deliveries"]), (2, 5, 2, 4, 5))
        self.assertEqual((ra["never_read"], ra["read_without_write_seen"]), (False, False))
        self.assertEqual((rb["writes"], rb["reads"], rb["never_read"], rb["deliveries"]), (1, 0, True, 0))
        self.assertEqual((rc["writes"], rc["reads"], rc["read_without_write_seen"], rc["never_read"]), (0, 1, True, False))
        self.assertEqual(self.flow["channel_types"]["repo"]["deliveries"], 5)
        self.assertEqual(self.flow["channel_types"]["repo"]["never_read"], 1)
        self.assertEqual(ra["median_latency_h"], round(4 * 600 / 3600, 2))

    def test_operations(self):
        self.assertEqual(self.flow["operations"], 9)
        self.assertEqual(self.flow["records_on_channels"], 9)
        self.assertEqual(sorted(o[1] for o in self.ops), ["read"] * 6 + ["write"] * 3)
        kinds = {o[2]: o[3] for o in self.ops}
        self.assertEqual(kinds["[TOKEN 1]"], "token")
        self.assertTrue(any(a.startswith("run:") and k == "run" for a, k in kinds.items()))

    def test_latency_is_read_minus_write(self):
        d = [x for x in self.dels if x["read_id"] == "E0014"][0]
        self.assertEqual(d["latency_h"], 1.0)
        self.assertAlmostEqual(d["read_time"] - d["write_time"], 6 * 600, delta=1)
        self.assertEqual(self.flow["latency_hours"]["median"], round(4 * 600 / 3600, 2))

    def test_coarse_place_is_weak_and_not_the_first_named_delivery(self):
        evs = filler()
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE")
        evs[4] = ev(4, f"{at(4)} auth=[TOKEN 2] repo/RA read")
        evs[6] = ev(6, f"{at(6)} auth=[TOKEN 1] repo/RB WRITE")
        evs[8] = ev(8, f"{at(8)} auth=[TOKEN 2] repo/RB read")
        flow, _ops = flow_of(evs, coarse_channels=["^repo:RA$"])
        self.assertEqual(flow["coarse_channel_deliveries"], 1)
        self.assertEqual(flow["first_named_delivery"]["read_id"], "E0008")
        self.assertEqual(flow["first_named_delivery_any_channel"]["read_id"], "E0004")
        self.assertEqual({d["channel"]: d["grade"] for d in flow["_deliveries"]}["repo:RA"], "weak")


class TimeRuleTests(unittest.TestCase):
    """R23 to R25 on bare operations."""

    def op(self, place, op, actor, t, rid, i=0):
        return (place, op, actor, "token", t, i, rid)

    def test_R24_equal_times_count_and_a_later_write_does_not(self):
        w, r = self.op("p", "write", "A", 100, "W"), self.op("p", "read", "B", 100, "R", 1)
        self.assertEqual(len(messages.deliveries([w, r])[0]), 1)                       # write time <= read time
        late = self.op("p", "write", "A", 101, "W")
        self.assertEqual(messages.deliveries([late, r])[0], [])

    def test_R23_same_actor_or_same_record_is_not_a_delivery(self):
        w = self.op("p", "write", "A", 100, "W")
        self.assertEqual(messages.deliveries([w, self.op("p", "read", "A", 200, "R", 1)])[0], [])
        post = self.op("p", "post", "A", 100, "X")
        self.assertEqual(messages.deliveries([post])[0], [])                           # a post does not read itself
        two = [self.op("p", "post", "A", 100, "X"), self.op("p", "post", "B", 100, "Y", 1)]
        self.assertEqual(sorted((d["write_id"], d["read_id"]) for d in messages.deliveries(two)[0]), [("X", "Y"), ("Y", "X")])

    def test_R22_another_place_is_not_read(self):
        w, r = self.op("p", "write", "A", 100, "W"), self.op("q", "read", "B", 200, "R", 1)
        self.assertEqual(messages.deliveries([w, r])[0], [])

    def test_R25_undated(self):
        w = self.op("p", "write", "A", None, "W")
        r = self.op("p", "read", "B", 200, "R", 1)
        self.assertEqual(messages.deliveries([w, r])[0], [])                           # an undated write is never linked
        out = messages.deliveries([self.op("p", "write", "A", 100, "W"), self.op("p", "read", "B", None, "R", 1),
                                   self.op("p", "read", "A", None, "R2", 2)])
        self.assertEqual((out[0], out[2]), ([], 1))                                    # order unknown: only the other actor's read

    def test_R26_R28_reads_are_taken_in_time_order(self):
        ops = [self.op("p", "read", "B", 300, "R2", 0), self.op("p", "read", "B", 200, "R1", 1), self.op("p", "write", "A", 100, "W", 2)]
        out = messages.deliveries(ops)
        self.assertEqual([(d["write_id"], d["read_id"]) for d in out[0]], [("W", "R1")])
        self.assertEqual(out[5], 1)
        self.assertEqual(out[0][0]["latency_h"], round(100 / 3600, 2))
        self.assertEqual(out[0][0]["how"], "read in code")

    def test_perf_row(self):
        ops = [self.op("p", "write", "A", 100, "W"), self.op("p", "read", "B", 3700, "R", 1), self.op("p", "read", "C", 7300, "R2", 2)]
        perf = messages.deliveries(ops)[1][0]
        self.assertEqual((perf["writes"], perf["reads"], perf["writers"], perf["readers"], perf["actors"], perf["deliveries"]), (1, 2, 1, 2, 3, 2))
        self.assertEqual((perf["first_write"], perf["first_read"]), (messages.iso(100), messages.iso(3700)))
        self.assertEqual(perf["median_latency_h"], 2.0)
        self.assertEqual((perf["never_read"], perf["read_without_write_seen"], perf["overwrites"]), (False, False, 0))


class FullBodyPostTests(unittest.TestCase):
    """R18, R29: posts on a structural place; a post that keeps none of the lines the earlier one added is an overwrite."""

    def page(self, i, actor, text, t, kind="action"):
        e = ev(i, text, kind=kind, actor=actor, time=f"2026-07-09T10:{t:02d}:00Z")
        e.channel = "wiki~Page"
        return e

    def flow(self, evs, **over):
        return flow_of(evs, full_body_posts=True, identity_patterns=[], channels=[], **over)[0]

    def test_kept_lines_are_a_delivery_and_dropped_lines_an_overwrite(self):
        a = self.page(1, "ann", "intro line one\nann adds this line", 1)
        b = self.page(2, "bob", "intro line one\nann adds this line\nbob adds another", 2)
        c = self.page(3, "cat", "cat replaces everything here", 3)
        flow = self.flow([a, b, c])
        got = {(d["write_id"], d["read_id"]): d for d in flow["_deliveries"]}
        self.assertEqual(sorted(got), [("E0001", "E0002")])
        self.assertEqual(got[("E0001", "E0002")]["how"], "kept 2 of 2 lines it added")
        self.assertEqual(got[("E0001", "E0002")]["lines"], ["intro line one", "ann adds this line"])
        self.assertEqual(got[("E0001", "E0002")]["grade"], "direct")
        self.assertEqual(got[("E0001", "E0002")]["channel"], "place:wiki~Page")
        over = flow["_overwrites"]
        self.assertEqual([(d["write_id"], d["read_id"]) for d in over], [("E0002", "E0003")])
        self.assertEqual(over[0]["how"], "dropped all 1 lines it added")           # only bob's own line counts as added
        self.assertEqual(over[0]["lines"], ["bob adds another"])
        self.assertEqual((flow["overwrites"], flow["deliveries"]), (1, 1))
        self.assertEqual(flow["top_overwrite_pairs"], [{"from": "bob", "to": "cat", "overwrites": 1}])
        self.assertEqual(flow["deliveries_by_how"], {"kept earlier content": 1})
        page = flow["_channels"][0]
        self.assertEqual((page["deliveries"], page["overwrites"], page["writes"], page["reads"]), (1, 1, 3, 3))

    def test_a_post_that_added_nothing_is_still_read(self):
        a = self.page(1, "ann", "short", 1)                                         # no line of 8+ characters
        b = self.page(2, "bob", "bob writes a long line", 2)
        flow = self.flow([a, b])
        self.assertEqual(flow["_deliveries"][0]["how"], "edited after it (it added no lines to compare)")
        self.assertEqual(flow["overwrites"], 0)

    def test_without_full_body_posts_a_later_post_is_a_delivery(self):
        a = self.page(1, "ann", "ann adds this line", 1)
        c = self.page(2, "cat", "cat replaces everything here", 2)
        flow = flow_of([a, c], identity_patterns=[], channels=[])[0]
        self.assertEqual([(d["write_id"], d["read_id"], d["how"]) for d in flow["_deliveries"]], [("E0001", "E0002", "posted after it")])

    def test_R18_write_only_kinds_and_structural_off(self):
        a = self.page(1, "ann", "ann adds this line", 1)
        d = self.page(2, "mod", "deleted the page here", 2, kind="delete")
        b = self.page(3, "bob", "bob starts the page again", 3)
        flow = self.flow([a, d, b], write_only_kinds=["delete"], action_kinds=["action", "delete"])
        pairs = sorted((x["write_id"], x["read_id"]) for x in flow["_deliveries"] + flow["_overwrites"])
        self.assertEqual(pairs, [("E0002", "E0003")])                               # the delete wrote, it did not read ann
        self.assertEqual(self.flow([a, b], structural_channels=False)["operations"], 0)

    def test_R19_naming_another_place_reads_it(self):
        a = self.page(1, "ann", "ann adds this line", 1)
        b = ev(2, "see PageTwoLong and Page for details", actor="bob", time="2026-07-09T10:05:00Z")
        b.channel = "wiki~Other"
        c = ev(3, "content of the second page", actor="cat", time="2026-07-09T10:03:00Z")
        c.channel = "wiki~PageTwoLong"
        flow, ops = flow_of([a, b, c], full_body_posts=True, identity_patterns=[], channels=[], mention_channels=True)
        self.assertEqual(sorted((d["write_id"], d["read_id"], d["how"]) for d in flow["_deliveries"]),
                         [("E0003", "E0002", "named the place")])                    # 'Page' is under six characters: not a name
        self.assertEqual(flow["_deliveries"][0]["grade"], "inferred")
        self.assertIn(("place:wiki~PageTwoLong", "read", "bob"), {(o[0], o[1], o[2]) for o in ops})
        self.assertNotIn(("place:wiki~Other", "read", "bob"), {(o[0], o[1], o[2]) for o in ops})
        off = flow_of([a, b, c], full_body_posts=True, identity_patterns=[], channels=[])[0]
        self.assertEqual(off["deliveries"], 0)


class DirectMessageTests(unittest.TestCase):
    """R20: a record addressed to another actor."""

    def msg(self, i, actor, to, t, parent=None, text="hello there"):
        e = ev(i, text, actor=actor, time=f"2026-07-09T10:{t:02d}:00Z", parent=parent)
        e.to = to
        e.channel = "room"
        return e

    def flow(self, evs):
        return flow_of(evs, identity_patterns=[], channels=[], structural_channels=False)[0]

    def test_reply_by_the_recipient_is_the_read(self):
        a = self.msg(1, "ann", "bob", 1)
        x = self.msg(2, "cat", None, 2)
        b = self.msg(3, "bob", None, 3)
        flow = self.flow([a, x, b])
        self.assertEqual(flow["direct_messages"], 1)
        d = flow["_deliveries"][0]
        self.assertEqual((d["channel"], d["from"], d["to"], d["write_id"], d["read_id"], d["how"], d["grade"]),
                         ("inbox:bob", "ann", "bob", "E0001", "E0003", messages.DIRECT_HOW, "direct"))
        self.assertEqual(d["latency_h"], round(120 / 3600, 2))
        self.assertEqual((flow["deliveries"], flow["deliveries_between_named_actors"], flow["named_actor_pairs"]), (1, 1, 1))
        self.assertEqual(flow["channel_types"]["inbox"]["deliveries"], 1)

    def test_a_child_reply_wins_over_a_later_record(self):
        a = self.msg(1, "ann", "bob", 1)
        late = self.msg(2, "bob", None, 5)
        child = self.msg(3, "bob", None, 9, parent="E0001")
        self.assertEqual(self.flow([a, late, child])["_deliveries"][0]["read_id"], "E0003")

    def test_no_reply_and_self_addressed(self):
        a = self.msg(1, "ann", "bob", 1)
        me = self.msg(2, "ann", "ann", 2)
        flow = self.flow([a, me])
        self.assertEqual([(d["write_id"], d["read_id"], d["latency_h"]) for d in flow["_deliveries"]], [("E0001", "E0001", 0.0)])

    def test_a_reply_earlier_in_time_is_not_the_read(self):
        a = self.msg(1, "ann", "bob", 5)
        early = self.msg(2, "bob", None, 1)
        flow = self.flow([a, early])
        self.assertEqual(flow["_deliveries"][0]["read_id"], "E0001")

    def test_undated_direct_messages_are_counted_apart(self):
        a = ev(1, "hello there", actor="ann")
        a.to, a.channel = "bob", "room"
        flow = self.flow([a] + [self.msg(2, "cat", None, 2)])
        self.assertEqual((flow["direct_messages"], flow["direct_messages_undated"], flow["deliveries"]), (0, 1, 0))


class ActorRuleTests(unittest.TestCase):
    """R21, R21a: who an operation belongs to."""

    def test_order_of_actor_sources(self):
        evs = filler(30)
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE", actor="[TOKEN 1]")
        evs[3] = ev(3, f"{at(3)} auth=[TOKEN 0] repo/RA read")                       # shared key only: an anonymous run
        evs[4] = ev(4, f"{at(4)} repo/RA read", parent="E0002")                      # no token: its thread's token
        evs[5] = ev(5, f"{at(5)} auth=[TOKEN 2] auth=[TOKEN 3] repo/RA read")        # two tokens: the first
        _flow, ops = flow_of(evs)
        who = {o[6]: (o[2], o[3]) for o in ops}
        self.assertEqual(who["E0002"], ("[TOKEN 1]", "named"))
        self.assertEqual(who["E0003"][1], "run")
        self.assertTrue(who["E0003"][0].startswith("run:"))
        self.assertEqual(who["E0004"], ("[TOKEN 1]", "token_via_thread"))
        self.assertEqual(who["E0005"], ("[TOKEN 2]", "token"))

    def test_R21a_the_token_in_the_judged_call_is_the_actor(self):
        pad = " ".join(["pad"] * 120)
        evs = filler(30)
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE")
        evs[5] = ev(5, f"{at(5)} auth=[TOKEN 2] {pad} {pad} repo/RA read auth=[TOKEN 3]")
        flow, ops = flow_of(evs)
        self.assertEqual({o[6]: o[2] for o in ops}["E0005"], "[TOKEN 3]")
        self.assertEqual([(d["from"], d["to"]) for d in flow["_deliveries"]], [("[TOKEN 1]", "[TOKEN 3]")])

    def test_R2_only_action_records_operate(self):
        evs = filler(30)
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE")
        evs[5] = ev(5, f"{at(5)} auth=[TOKEN 2] repo/RA read", kind="reply")
        flow, ops = flow_of(evs)
        self.assertEqual((flow["deliveries"], [o[6] for o in ops]), (0, ["E0002"]))

    def test_R3_R5_comment_and_one_operation_per_record(self):
        evs = filler(30)
        evs[2] = ev(2, f"{at(2)} auth=[TOKEN 1] repo/RA WRITE")
        evs[4] = ev(4, f"{at(4)} auth=[TOKEN 2] step\n// repo/RA is where the plan is")
        evs[6] = ev(6, f"{at(6)} auth=[TOKEN 3] repo/RA read " + " ".join(["pad"] * 150) + " repo/RA WRITE")
        flow, ops = flow_of(evs)
        self.assertEqual(sorted((o[6], o[1]) for o in ops), [("E0002", "write"), ("E0006", "write")])
        self.assertEqual(flow["deliveries"], 0)


if __name__ == "__main__":
    unittest.main()

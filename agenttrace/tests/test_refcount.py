"""Tests for agenttrace.refcount, the second implementation of the counting rule (docs/counting-rule.md).

Each case cites the statement it checks. The reference must not use messages.py, and on clean generated
swarms and the built-in samples the two implementations must give the same deliveries.

Run from the project root:
    python3 -m unittest agenttrace.tests.test_refcount -v
"""
import io
import os
import random
import re
import unittest

from agenttrace import messages, refcount
from agenttrace.tests import test_properties as T

P = "https://huggingface.co/datasets/[X 1]"
BOARD = "https://pkg.example.net/artifactory/api/github-remote/zzBOARD_1"


def judge(text):
    """[(op, how)] for every place mention in the text, with the code-traces pack."""
    out = []
    for _name, rx, wrx, rrx in refcount._channels(T.pack()):
        j = refcount.Judge(text, wrx, rrx)
        for m in rx.finditer(text):
            if m.group(1):
                out.append(j.judge(m.start(), m.end())[:2])
    return out


class JudgeTests(unittest.TestCase):
    def one(self, text):
        got = judge(text)
        self.assertEqual(len(got), 1, text)
        return got[0]

    def test_R8_a_mention_inside_a_request_call(self):
        self.assertEqual(self.one(f"fetch('{P}/commit/main',{{method:'POST',body:b}})"), ("write", "call"))
        self.assertEqual(self.one(f"const m = await fetch('{P}/resolve/main/msg_1.json')"), ("read", "call"))
        self.assertEqual(self.one(f"x=new XMLHttpRequest;x.open('POST','{P}/commit/main',0);x.send(b)"), ("write", "call"))
        self.assertEqual(self.one(f"x=new XMLHttpRequest;x.open('GET','{P}/resolve/main/f',false);x.send()"), ("read", "call"))
        self.assertEqual(self.one(f"requests.post('{P}/commit/main', headers=h, data=d)"), ("write", "call"))
        self.assertEqual(self.one(f"requests.get('{P}/resolve/main/x', headers=h)"), ("read", "call"))
        self.assertEqual(self.one(f"r=U.urlopen(U.Request('{P}/commit/main',data=d,headers=H))"), ("write", "call"))
        self.assertEqual(self.one(f"await fetch('{BOARD}/', {{method: 'MKCOL', headers: {{}}}})"), ("write", "call"))

    def test_R8_a_request_with_no_verb_is_a_read_by_default(self):
        self.assertEqual(self.one(f"await fetch('{BOARD}/msg_3', {{headers: {{'Authorization': 'x'}}}})"), ("read", "default"))

    def test_R4_the_next_call_does_not_decide(self):
        text = f"fetch('{P}/resolve/main/a.json').then(r=>r.text()).then(t=>fetch('https://c.example/x',{{method:'POST',body:t}}))"
        self.assertEqual(self.one(text), ("read", "call"))
        text = f"const r = await fetch('{P}', {{headers: {{}}}});await fetch('https://c.example/x', {{method: 'POST', body: JSON.stringify({{operation: 'upload'}})}});"
        self.assertEqual(self.one(text)[0], "read")

    def test_R6_lfs_batch(self):
        self.assertEqual(self.one(f"x=fetch('{P}/info/lfs/objects/batch',{{method:'POST',body:B}})")[0], None)
        self.assertEqual(self.one(f"B={{operation:'upload'}};fetch('{P}/info/lfs/objects/batch',{{method:'POST',body:B}})"), ("write", "inferred"))
        self.assertEqual(self.one(f"B=JSON.stringify({{operation:'download'}});fetch('{P}/info/lfs/objects/batch',{{method:'POST',body:B}})"), ("read", "inferred"))
        xhr = f"x=new XMLHttpRequest;x.open('POST','{P}',0);x.send('{{\"operation\":\"download\"}}')"
        self.assertEqual(self.one(xhr), ("read", "inferred"))

    def test_R7_repository_in_a_variable(self):
        self.assertEqual(self.one(f"fetch('{P}/'+repo+'/commit/main',{{method:'POST'}})")[0], None)

    def test_R9_a_name_is_judged_by_the_calls_it_is_passed_to(self):
        self.assertEqual(self.one(f"u='{P}/commit/main';r=fetch(u,{{method:'POST'}})"), ("write", "inferred"))
        self.assertEqual(self.one(f"u='{P}';r=fetch(u,{{headers:{{}}}});u=l+'x';fetch(Q(u),{{method:'PUT'}})"), ("read", "inferred"))
        self.assertEqual(self.one(f"u='{P}';print(1)")[0], None)
        self.assertEqual(self.one(f"u=f'{P}';s=f\"x=new XMLHttpRequest;x.open('POST','{{u}}',0)\""), ("write", "inferred"))
        wrapped = '{"submitted_code":"import urllib.request;u=\\\'%s\\\';print(len(urllib.request.urlopen(u).read()))"}' % P
        self.assertEqual(self.one(wrapped), ("read", "inferred"))

    def test_R10_R11_helper_calls(self):
        self.assertEqual(self.one(f"src='{P}';_,d=Q('GET',src,h={{}});r,_=Q('POST',B+R+'/blobs/uploads/',b'',H)")[0], "read")
        self.assertEqual(self.one(f"src='{P}';_,d=Q('POST',src,h={{}})")[0], "write")
        self.assertEqual(self.one(f"req('{P}', tok, 'POST', data)")[0], "write")
        self.assertEqual(self.one(f"Q('POST','{P}','{{}}',W)")[0], "write")

    def test_R12_a_request_written_as_data(self):
        self.assertEqual(self.one('{"u": "%s", "m": "POST", "b": "x"}' % P)[0], "write")
        self.assertEqual(self.one('{"u": "%s", "m": "GET"}' % P)[0], "read")
        self.assertEqual(self.one('{"u": "%s", "b": "x"}' % P)[0], "write")

    def test_R13_cut_off_and_bare_url(self):
        self.assertEqual(self.one(f"x=await fetch('{P}',{{method")[0], None)
        self.assertEqual(self.one(P)[0], None)

    def test_R14_no_verb_is_a_read_by_default(self):
        self.assertEqual(self.one(f"see {P} for the data, then more text follows here to pad it out"), ("read", "default"))

    def test_R15_options_in_a_variable(self):
        self.assertEqual(self.one(f"o={{method:'POST',body:z}};u='{P}/commit/main';fetch(u,o)")[0], "write")

    def test_R17_hidden_holder(self):
        script = f"for x in [BLOB] HOST 1]/{P[8:]}';T='[C 1]';s=f\"x=new XMLHttpRequest;x.open('POST','{{u}}',0);x.send(b)\";open('f','w').write(s)"
        self.assertEqual(self.one(script)[0], None)
        reader = f"[BLOB]{P[8:]}'\nr=urllib.request.urlopen(urllib.request.Request(u,headers=H))"
        self.assertEqual(self.one(reader), ("read", "default"))
        # the quoted value of a config key is not a held name
        card = f"x.send(d)\n---\nconfigs:\n- config_name: ref\n  data_files: \"reference://x::{P}\"\n---\nr=urllib.request.urlopen(urllib.request.Request(u,data=b))"
        self.assertEqual(self.one(card), ("read", "default"))
        self.assertEqual(self.one(card.replace('  data_files: "', "[BLOB]"))[0], None)

    def test_shell_command_lines(self):
        self.assertEqual(self.one(f"curl -s -X PUT -H 'a: b' {BOARD}/msg_1 -d @f")[0], "write")
        self.assertEqual(self.one(f"curl -s {BOARD}/msg_1")[0], "read")
        self.assertEqual(self.one(f"curl -sSL {BOARD}/msg_1|gzip -d|python3")[0], "read")

    def test_redaction_markers_with_spaces_do_not_break_the_string(self):
        text = f"fetch('https://[SERVICE HOST 1]/{P}',{{method:'POST',headers:{{}}}})"
        self.assertEqual(self.one(text), ("write", "call"))

    def test_R3_comments(self):
        for text, pos_of, want in [
            ("// see repo X", "X", True), ("x = 1 // see X", "X", True), ("# note X", "X", True),
            ("  * X in a block", "X", True), ("fetch('https://h/X')", "X", False), ("a = '#X'", "X", False),
            ("x = 1; /* done */ fetch('X')", "X", False), ("code;\n/* open X", "X", True), ("-- X", "X", True),
            ("/* done */ fetch('X')", "X", True),      # R3 as written: a line that starts with /* is a comment line
        ]:
            self.assertEqual(refcount.commented(text, text.index(pos_of)), want, text)


class LinkTests(unittest.TestCase):
    def ops(self, rows):
        return [refcount.Op(p, op, a, t, rid, i) for i, (p, op, a, t, rid) in enumerate(rows)]

    def keys(self, out):
        return [(d["write_id"], d["read_id"]) for d in out["deliveries"]]

    def test_R22_to_R26(self):
        out = refcount.link(self.ops([("p", "write", "A", 10, "W1"), ("p", "write", "C", 20, "W2"), ("p", "read", "B", 30, "R1"),
                                      ("p", "read", "C", 31, "R2"), ("q", "read", "B", 32, "R3"), ("p", "read", "B", 5, "R0")]))
        self.assertEqual(self.keys(out), [("W2", "R1"), ("W1", "R2")])

    def test_R25_undated(self):
        out = refcount.link(self.ops([("p", "write", "A", 10, "W"), ("p", "read", "B", None, "R"), ("p", "write", "A", None, "W2"),
                                      ("p", "read", "B", 1, "R0")]))
        self.assertEqual((self.keys(out), out["order_unknown"]), ([], 1))

    def test_R27_same_program(self):
        ops = self.ops([("p", "write", "A", 10, "W"), ("p", "read", "B", 20, "R")])
        self.assertEqual(self.keys(refcount.link(ops, program={"W": ("x",), "R": ("x",)})), [])
        self.assertEqual(refcount.link(ops, program={"W": ("x",), "R": ("x",)})["same_program"], 1)
        self.assertEqual(self.keys(refcount.link(ops, program={"W": ("x",), "R": ("y",)})), [("W", "R")])
        self.assertEqual(self.keys(refcount.link(ops, program={"W": None, "R": None})), [("W", "R")])

    def test_R28_repeat_reads(self):
        out = refcount.link(self.ops([("p", "write", "A", 10, "W"), ("p", "read", "B", 20, "R1"), ("p", "read", "B", 30, "R2"),
                                      ("p", "write", "A", 40, "W2"), ("p", "read", "B", 50, "R3")]))
        self.assertEqual((self.keys(out), out["repeat_reads"]), ([("W", "R1"), ("W2", "R3")], 1))

    def test_R29_overwrite(self):
        texts = {"A1": "first line of A\nsecond line of A", "B1": "something else entirely", "B2": "first line of A\nplus more from B"}
        ops = self.ops([("p", "post", "A", 10, "A1"), ("p", "post", "B", 20, "B1")])
        out = refcount.link(ops, texts=texts, full_body=True)
        self.assertEqual((self.keys(out), len(out["overwrites"])), ([], 1))
        ops = self.ops([("p", "post", "A", 10, "A1"), ("p", "post", "B", 20, "B2")])
        out = refcount.link(ops, texts=texts, full_body=True)
        self.assertEqual((self.keys(out), len(out["overwrites"])), ([("A1", "B2")], 0))

    def test_R31_to_R33_grades(self):
        def grade(hw, hr, coarse=None, est=None, gap=100):
            ops = [refcount.Op("p:A", "write", "A", 1000, "W", 0, hw), refcount.Op("p:A", "read", "B", 1000 + gap, "R", 1, hr)]
            return refcount.link(ops, coarse=coarse, estimated=est)["deliveries"][0]["grade"]
        self.assertEqual(grade("call", "call"), "direct")
        self.assertEqual(grade("inferred", "call"), "inferred")
        self.assertEqual(grade("call", "default"), "weak")
        self.assertEqual(grade("call", "call", coarse=[re.compile("^p:")]), "weak")
        self.assertEqual(grade("call", "call", est=lambda rid: rid == "R", gap=7200), "weak")
        self.assertEqual(grade("call", "call", est=lambda rid: rid == "R", gap=600), "direct")

    def test_properties_P2_P4_P6_on_random_operations(self):
        rng = random.Random(53)
        for case in range(200):
            raw = T.gen_ops(rng, ties=case % 2 == 0)
            ops = [refcount.Op(o[0], o[1], o[2], o[4], o[6], o[5]) for o in raw]
            by_id = {o.rid: o for o in ops}
            out = refcount.link(ops)
            for d in out["deliveries"]:
                w, r = by_id[d["write_id"]], by_id[d["read_id"]]
                self.assertTrue(w.place == r.place and w.actor != r.actor and w.rid != r.rid and w.time <= r.time, f"case {case}")
            again = ops + [refcount.Op(o.place, "read", o.actor, o.time + 0.5, o.rid + "+", len(ops) + i)
                           for i, o in enumerate(ops) if o.op == "read" and o.time is not None]
            self.assertEqual(len(refcount.link(again)["deliveries"]), len(out["deliveries"]), f"case {case}")
            self.assertEqual(refcount.link([o for o in ops if o.op == "read"])["deliveries"], [], f"case {case}")
            # and the main implementation links the same pairs from the same operations
            self.assertEqual(sorted((d["write_id"], d["read_id"]) for d in messages.deliveries(raw)[0]),
                             sorted((d["write_id"], d["read_id"]) for d in out["deliveries"]), f"case {case}")


class AgreementTests(unittest.TestCase):
    """On clean data the two implementations must agree exactly; real data is tools/crosscheck.py's job."""

    def test_reference_does_not_use_messages(self):
        with io.open(refcount.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIsNone(re.search(r"^\s*(?:from\s+\.?\s*messages\b|from\s+\.\s+import\s+[^\n]*\bmessages\b|import\s+[^\n]*\bmessages\b)", src, re.M))
        self.assertNotIn("judge_span", src)
        self.assertNotIn("channel_ops", src)

    def test_generated_swarms(self):
        rng = random.Random(23)
        total = 0
        for case in range(60):
            events = [e for *_x, e in T.gen_swarm(rng)]
            flow, rec, res = T.flow_of(events)
            a = sorted((d["channel"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in flow["_deliveries"])
            out = refcount.count(events, T.pack(), rec, res)
            b = sorted((d["place"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in out["deliveries"])
            self.assertEqual(a, b, f"case {case}")
            self.assertEqual((flow["deliveries_order_unknown"], flow["repeat_reads"], flow["reads_dropped_as_same_program"]),
                             (out["order_unknown"], out["repeat_reads"], out["same_program"]), f"case {case}")
            total += len(a)
        self.assertGreater(total, 300)

    def test_built_in_samples(self):
        from agenttrace.tools import crosscheck
        seen = 0
        for label, path, pack_file in crosscheck.dataset_specs(["demo", "benign", "samples"]):
            if not os.path.exists(path):
                continue
            r = crosscheck.compare(crosscheck.analyze(path, pack_file))
            self.assertEqual((r["only_A"], r["only_B"]), (0, 0), label)
            self.assertEqual(r["A"]["deliveries"], r["B"]["deliveries"], label)
            self.assertEqual(r["grade_agreement"]["same"], r["grade_agreement"]["of"], label)
            seen += r["both"]
        self.assertGreater(seen, 200)

    def test_crosscheck_reports_a_disagreement_and_the_exit_code(self):
        from agenttrace.tools import crosscheck
        s = crosscheck.analyze(os.path.join(crosscheck.PKG, "samples", "benign_swarm"), None)
        d = s.flow["_deliveries"][0]
        fake = dict(d, write_id="NOPE")
        s.flow = dict(s.flow, _deliveries=[fake])
        r = crosscheck.compare(s)
        self.assertEqual((r["both"], r["only_A"], r["only_B"]), (0, 1, 1))
        self.assertEqual(r["disagreement"], 1.0)
        self.assertEqual(r["deliveries_only_A"][0]["write_id"], "NOPE")
        buf = io.StringIO()
        ok = crosscheck.run(["benign"], threshold=0.10, stream=buf)
        self.assertTrue(ok["passed"])
        self.assertIn("worst disagreement 0.0%", buf.getvalue())
        self.assertEqual(crosscheck.run(["nope=/does/not/exist"], stream=io.StringIO())["skipped"][0]["why"], "not on disk")


if __name__ == "__main__":
    unittest.main()

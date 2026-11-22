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

    def test_R6a_paths_info_is_a_read(self):
        self.assertEqual(self.one(f"fetch('{P}/paths-info/main',{{method:'POST',body:b}})"), ("read", "inferred"))

    def test_R6b_an_upload_batch_counts_only_if_the_object_goes_up(self):
        batch = f"fetch('{P}/info/lfs/objects/batch',{{method:'POST',body:JSON.stringify({{operation:'upload',objects:[{{oid:'[SRC 7]'}}]}})}})"

        class Facts:
            def __init__(self, ok):
                self.ok = ok

            def goes_up(self, oids, pos):
                self.seen = oids
                return self.ok
        for ok, want in ((True, "write"), (False, None)):
            for _name, rx, wrx, rrx in refcount._channels(T.pack()):
                j = refcount.Judge(batch, wrx, rrx)
                j.ctx, j.pos = Facts(ok), 3
                m = next(m for m in rx.finditer(batch) if m.group(1))
                self.assertEqual(j.judge(m.start(), m.end())[0], want)
                break

    def test_R6b_facts_from_a_trace(self):
        ev = [type("E", (), {"id": f"R{i}", "text": t})() for i, t in enumerate([
            "operation:'download',objects:[{oid:'[SRC 1]'}]",          # 0: object asked for
            "operation:'upload',objects:[{oid:'[SRC 1]'}]",            # 1: a probe of a file that existed
            "operation:'upload',objects:[{oid:'[SRC 2]'}]",            # 2: new object
            "operation:'upload',objects:[{oid:'[SRC 3]'}]",            # 3: never sent
            "commit lfsFile [SRC 1] and [SRC 2]"])]                    # 4: sends 1 and 2
        f = refcount.LfsFacts(ev)
        self.assertEqual([f.goes_up(("[SRC %d]" % n,), n) for n in (1, 2, 3)], [False, True, False])
        self.assertFalse(f.goes_up((), 2))

    def test_R13_a_record_that_ends_inside_the_verb(self):
        self.assertEqual(self.one(f"fetch('{P}/commit/main',{{method:'POS")[0], None)
        self.assertEqual(self.one(f"{P}/commit/main',{{method:'POS")[0], None)

    def test_a_quote_lost_to_redaction_does_not_hide_the_call(self):
        text = f"x={{summary:'sealed [ENCODED BLOB] r=await fetch('https://[SERVICE HOST 1]/{P}/commit/main',{{method:'POST',body:b}})"
        self.assertEqual(self.one(text)[0], "write")
        text = f"let u='{P}',r=await fetch(u,{{headers:h}}),q=await fetch('https://c.example/x',{{method:'POST',body:JSON.stringify({{u:r.url}})}})"
        self.assertEqual(self.one(text)[0], "read")

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

    def test_R23a_a_read_that_lists_the_writers_token(self):
        ops = [refcount.Op("p", "write", "[CREDENTIAL 5]", 10, "W", 0, kind="token"), refcount.Op("p", "read", "B", 20, "R", 1)]
        self.assertEqual(self.keys(refcount.link(ops, texts={"W": "w", "R": "for t in ['[CREDENTIAL 5]','[CREDENTIAL 6]']"})), [])
        self.assertEqual(self.keys(refcount.link(ops, texts={"W": "w", "R": "for t in ['[CREDENTIAL 55]']"})), [("W", "R")])
        named = [refcount.Op("p", "write", "[CREDENTIAL 5]", 10, "W", 0, kind="named"), ops[1]]
        self.assertEqual(self.keys(refcount.link(named, texts={"W": "w", "R": "[CREDENTIAL 5]"})), [("W", "R")])

    def test_R38_the_written_content_test(self):
        ev = [type("E", (), {"id": i, "text": t})() for i, t in [
            ("W", "put report_final_v2.json to place"), ("R", "got report_final_v2.json from it"),
            ("W2", "put other_rarely.json"), ("R2", "read something_else_entirely.txt")]]
        ev += [type("E", (), {"id": f"X{i}", "text": "common_name.json " * 2})() for i in range(8)]
        ds = [{"place": "p", "write_id": "W", "read_id": "R", "grade": "weak"}, {"place": "p", "write_id": "W2", "read_id": "R2", "grade": "weak"},
              {"place": "inbox:b", "write_id": "W", "read_id": "R", "grade": "direct"}]
        self.assertEqual(refcount.content_test(ds, ev), 2)
        self.assertEqual([d["uses_content"] for d in ds], [True, False, True])
        self.assertEqual(ds[0]["shared_terms"], ["report_final_v2.json"])

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


def split_in_verbs(events, rng):
    """The same swarm with some records cut inside a verb into two consecutive records (R13a's shape)."""
    out, cuts = [], 0
    for e in events:
        m = re.search(r"(?:method\s*[:=]\s*|\.open\s*\(\s*)['\"](POST|PUT|PATCH|DELETE|GET|HEAD)['\"]", e.text)
        if m and rng.random() < 0.6:
            k = m.start(1) + rng.randint(1, len(m.group(1)) - 1)
            out.append(T.Event(id=e.id, text=e.text[:k], kind=e.kind, time=e.time))
            out.append(T.Event(id=e.id + "b", text=e.text[k:], kind=e.kind, time=e.time))
            cuts += 1
        else:
            out.append(e)
    return out, cuts


class JoinTests(unittest.TestCase):
    """R13a: a record cut inside a verb that the next record completes is read as one record."""

    def test_R13a_where_a_text_ends_inside_a_verb(self):
        for text, want in [("fetch(u,{method:'POS", ("POS", "'")), ('x.open ( "pu', ("PU", '"')), ("r(u, method = 'D", ("D", "'")),
                           ("fetch(u,{method:'POST", None), ("fetch(u,{method:'POSTS", None), ("fetch(u,{mode:'POS", None),
                           ("fetch(u,{xmethod:'POS", None), ("say('POS", None), ("fetch(u,{method:'XY", None), ("fetch(u,{method:'", None),
                           ("fetch(u,{method:POS", None), ("", None)]:
            self.assertEqual(refcount._ends_in_verb(text), want, text)

    def test_R13a_what_completes_it(self):
        self.assertTrue(refcount._begins_with_rest("T',headers:{}", "POS", "'"))
        self.assertTrue(refcount._begins_with_rest("t',headers:{}", "POS", "'"))
        self.assertTrue(refcount._begins_with_rest("ATCH'", "P", "'"))
        self.assertFalse(refcount._begins_with_rest('T",headers:{}', "POS", "'"))
        self.assertFalse(refcount._begins_with_rest("x=1;T'", "POS", "'"))
        self.assertFalse(refcount._begins_with_rest("TS'", "POS", "'"))

    def test_R13a_joined_record_keeps_the_first_id_and_takes_the_tokens_of_both(self):
        ev = lambda i, t, **kw: T.Event(id=i, text=t, kind=kw.pop("kind", "payload"), **kw)
        a = ev("a", "ps://huggingface.co/api/datasets/[HF REPO 5]/commit/main',{method:'POS")
        b = ev("b", "T',headers:{Authorization:'Bearer [CREDENTIAL 170]','Cont")
        c = ev("c", "fetch('https://huggingface.co/datasets/[HF REPO 5]/resolve/main/x',{headers:{Authorization:'Bearer [CREDENTIAL 169]'}})")
        rec = {"_ids": {"a": [], "b": ["[CREDENTIAL 170]"], "c": ["[CREDENTIAL 169]"]}, "_times": {"b": 100, "c": 300}}
        res = {"_root": {"a": "a", "b": "b", "c": "c"}}
        records, rec_j, joined = refcount.join([a, b, c], T.pack(), rec)
        self.assertEqual((joined, [r.id for r in records], records[0].text), ({"a": ["b"]}, ["a", "c"], a.text + b.text))
        self.assertEqual((rec_j["_ids"]["a"], rec_j["_times"]["a"], rec["_ids"]["a"]), (["[CREDENTIAL 170]"], 100, []))
        out = refcount.count([a, b, c], T.pack(), rec, res)
        self.assertEqual([(d["write_id"], d["read_id"], d["from"], d["to"]) for d in out["deliveries"]],
                         [("a", "c", "[CREDENTIAL 170]", "[CREDENTIAL 169]")])
        self.assertEqual(sorted((o.rid, o.op) for o in out["_ops"]), [("a", "write"), ("c", "read")])
        # the same three records with something else in between: nothing is joined, the cut call is not counted (R13)
        out = refcount.count([a, c, b], T.pack(), rec, res)
        self.assertEqual((out["joined"], out["deliveries"]), ({}, []))
        # fields that keep two records apart (R13a c)
        for other in (ev("b", b.text, kind="reply"), ev("b", b.text, parent="zz"), ev("b", b.text, actor="B"), ev("b", b.text, channel="c9"),
                      ev("b", b.text, to="someone")):
            self.assertEqual(refcount.join([a, other, c], T.pack(), rec)[2], {}, other)
        self.assertEqual(refcount.join([a, ev("b", b.text, parent="a"), c], T.pack(), rec)[2], {"a": ["b"]})

    def test_R13a_cutting_records_inside_a_verb_changes_no_delivery_in_either_implementation(self):
        rng = random.Random(41)
        total = cut_total = 0
        for case in range(40):
            events = [e for *_x, e in T.gen_swarm(rng)]
            flow, rec, res = T.flow_of(events)
            want = sorted((d["channel"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in flow["_deliveries"])
            pieces, cuts = split_in_verbs(events, rng)
            flow2, rec2, res2 = T.flow_of(pieces)
            a = sorted((d["channel"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in flow2["_deliveries"])
            out = refcount.count(pieces, T.pack(), rec2, res2)
            b = sorted((d["place"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in out["deliveries"])
            self.assertEqual(a, want, f"case {case}: messages.py")
            self.assertEqual(b, want, f"case {case}: refcount.py")
            self.assertEqual(len(flow2["joined_fragments"]), cuts, f"case {case}")
            self.assertEqual({k: v for k, v in out["joined"].items()}, {j["record"]: j["continued_in"] for j in flow2["joined_fragments"]})
            total += len(want)
            cut_total += cuts
        self.assertGreater(total, 150)
        self.assertGreater(cut_total, 100)


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

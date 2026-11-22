"""Rule changes of v2.2.0 (docs/audit-v2.1.md plan B1 to B7): each false link the audit found, as a small case with
asserted values, plus the counts on the Swarm Traces release when the file is in this checkout.

    python3 -m unittest agenttrace.tests.test_audit_rules -v
"""
import json
import os
import unittest

from agenttrace import messages as M
from agenttrace.tests.test_mutants import E, flow_of, world

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE = os.path.join(REPO, "redacted_columns.csv")
with open(os.path.join(REPO, "agenttrace", "packs", "code_traces.json"), encoding="utf-8") as f:
    RAW = json.load(f)

HF = "https://huggingface.co/datasets/[HF REPO 5]"
UP = ("T='[CREDENTIAL 170]';U='https://h/https://huggingface.co/datasets/[HF REPO 5]/info/lfs/objects/batch';"
      "B={operation:'upload',objects:[{oid:'[REDACTED:source_identifier:000791]',size:9}]};fetch(U,{method:'POST',body:JSON.stringify(B)})")
DOWN = ("B={operation:'download',objects:[{oid:'[REDACTED:source_identifier:000791]',size:9}]};"
        "fetch('https://h/https://huggingface.co/datasets/[HF REPO 5]/info/lfs/objects/batch',{method:'POST',body:JSON.stringify(B)})")
COMMIT = "fetch('https://huggingface.co/api/datasets/[HF REPO 5]/commit/main',{method:'POST',body:'lfsFile oid:\"[REDACTED:source_identifier:000791]\"'})"
READ = "fetch('https://huggingface.co/datasets/[HF REPO 5]/resolve/main/train.jsonl',{headers:{}})"


def flow(texts, tokens, times):
    """texts: {id: text}; tokens: {id: token}; times: {id: seconds}. Every record is an action by its token."""
    evs = [E(i, t) for i, t in texts.items()]
    ids = {i: ([tokens[i]] if i in tokens else []) for i in texts}
    return flow_of(evs, dict(RAW, action_kinds=["action"]), times, ids=ids)


def judge(text, place="[HF REPO 5]"):
    wrx, rrx = M.compile_channels(world([E("x")], raw=RAW)[2])[0][2:]
    s = text.index(place)
    return M.judge_op(text, s, s + len(place), wrx, rrx)


class B1LfsProbe(unittest.TestCase):
    def test_upload_after_download_of_the_same_object_is_no_write(self):
        f = flow({"d": DOWN, "u": UP, "r": READ}, {"d": "[CREDENTIAL 170]", "u": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"},
                 {"d": 100, "u": 200, "r": 300})
        self.assertEqual(f["deliveries"], 0)

    def test_upload_counts_when_a_later_request_sends_the_object(self):
        f = flow({"u": UP, "c": COMMIT, "r": READ}, {"u": "[CREDENTIAL 170]", "c": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"},
                 {"u": 100, "c": 200, "r": 300})
        self.assertEqual(f["deliveries"], 1)

    def test_upload_never_sent_is_no_write(self):
        f = flow({"u": UP, "r": READ}, {"u": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"u": 100, "r": 300})
        self.assertEqual(f["deliveries"], 0)


class B2ReaderListsWritersToken(unittest.TestCase):
    def test_a_read_that_lists_the_writers_token_is_not_a_delivery(self):
        sweep = "for(t of ['[CREDENTIAL 170]','[CREDENTIAL 169]']){" + READ + "}"
        f = flow({"w": COMMIT, "r": sweep}, {"w": "[CREDENTIAL 170]"}, {"w": 100, "r": 300})
        self.assertEqual(f["deliveries"], 0)
        f = flow({"w": COMMIT, "r": READ}, {"w": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"w": 100, "r": 300})
        self.assertEqual(f["deliveries"], 1)


class B3CutInsideTheVerb(unittest.TestCase):
    def test_record_ending_inside_the_verb_is_not_counted(self):
        base = "ps://huggingface.co/api/datasets/[HF REPO 5]/commit/main',{method:'"
        for tail in ("POS", "P", ""):
            text = "fetch('" + base[3:] + tail
            wrx, rrx = M.compile_channels(world([E("x")], raw=RAW)[2])[0][2:]
            s = text.index("[HF REPO 5]")
            self.assertEqual(M.judge_op(text, s, s + 11, wrx, rrx), "mention", tail)
        full = "fetch('https://huggingface.co/api/datasets/[HF REPO 5]/commit/main',{method:'POST'"
        self.assertEqual(judge(full), "write")


class B3JoinedFragments(unittest.TestCase):
    """R13a: a record cut inside a verb that the next record completes is read as one record."""
    CUT = "ps://huggingface.co/api/datasets/[HF REPO 5]/commit/main',{method:'POS"
    REST = "T',headers:{Authorization:'Bearer [CREDENTIAL 170]','Cont"

    def test_the_release_pair_is_one_write_by_the_token_in_the_continuation(self):
        f = flow({"a": self.CUT, "b": self.REST, "r": READ}, {"b": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"a": 100, "b": 100, "r": 300})
        self.assertEqual(f["joined_fragments"], [{"record": "a", "continued_in": ["b"]}])
        self.assertEqual([(d["write_id"], d["read_id"], d["from"], d["to"]) for d in f["_deliveries"]],
                         [("a", "r", "[CREDENTIAL 170]", "[CREDENTIAL 169]")])
        self.assertEqual((f["operations"], f["records_on_channels"]), (2, 2))      # the continuation has no operation of its own

    def test_not_completed_by_the_next_record_stays_cut(self):
        for nxt in ("x=1;T',headers:{}", "T\",headers:{}", "ST',headers:{}", "", "t = 5"):
            f = flow({"a": self.CUT, "b": nxt, "r": READ}, {"b": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"a": 100, "b": 100, "r": 300})
            self.assertEqual((f["joined_fragments"], f["deliveries"]), ([], 0), nxt)

    def test_only_a_cut_inside_a_verb_is_joined(self):
        # cut inside the address, after a complete verb, or after six letters: no evidence that the next record continues it
        for a, b in (("fetch('https://huggingface.co/api/datasets/[HF REPO", " 5]/commit/main',{method:'POST'})"),
                     (self.CUT + "T", "',headers:{}"), (self.CUT[:-3] + "POSTER", "T',headers:{}"),
                     (self.CUT[:-10] + "{mode:'POS", "T',headers:{}")):
            view, parts = M.join_fragments([E("a", a), E("b", b)], world([E("x")], raw=dict(RAW, action_kinds=["action"]))[2])
            self.assertEqual((parts, [i for i, _e in view]), ({}, [0, 1]), a[-12:])

    def test_fields_that_keep_two_records_apart(self):
        pack = world([E("x")], raw=dict(RAW, action_kinds=["action"]))[2]
        ok = lambda a, b: bool(M.join_fragments([a, b], pack)[1])
        self.assertTrue(ok(E("a", self.CUT), E("b", self.REST)))
        self.assertTrue(ok(E("a", self.CUT), E("b", self.REST, parent="a")))
        self.assertTrue(ok(E("a", self.CUT, parent="p"), E("b", self.REST, parent="p")))
        self.assertFalse(ok(E("a", self.CUT), E("b", self.REST, parent="other")))
        self.assertFalse(ok(E("a", self.CUT), E("b", self.REST, kind="reply")))
        self.assertFalse(ok(E("a", self.CUT, kind="reply"), E("b", self.REST, kind="reply")))      # not action records (R2)
        self.assertFalse(ok(E("a", self.CUT, actor="A"), E("b", self.REST, actor="B")))
        self.assertFalse(ok(E("a", self.CUT, channel="c1"), E("b", self.REST, channel="c2")))
        self.assertFalse(ok(E("a", self.CUT, to="B"), E("b", self.REST, to="B")))                  # a direct message is never joined

    def test_open_call_three_fragments_and_what_the_view_keeps(self):
        evs = [E("a", "x=new XMLHttpRequest;x.open('PU"), E("b", "T','https://huggingface.co/api/datasets/[HF REPO 5]',false);fetch(u,{method : \"ge"),
               E("c", "t\"});y=1"), E("d", READ)]
        pack = world([E("x")], raw=dict(RAW, action_kinds=["action"]))[2]
        view, parts = M.join_fragments(evs, pack)
        self.assertEqual(parts, {"a": ["b", "c"]})
        self.assertEqual([(i, e.id) for i, e in view], [(0, "a"), (3, "d")])
        self.assertEqual(view[0][1].text, evs[0].text + evs[1].text + evs[2].text)
        self.assertEqual(evs[0].text, "x=new XMLHttpRequest;x.open('PU")                            # the input is not changed
        ops = M.channel_ops(evs, *[world(evs, raw=dict(RAW, action_kinds=["action"]), ids={"a": [], "b": ["[CREDENTIAL 7]"], "c": [], "d": []},
                                         times={"b": 50, "d": 90})[k] for k in (2, 0, 1)])
        # one write under the first id, by the token of a later fragment, at the first time any fragment has
        self.assertEqual([(o[1], o[2], o[4], o[5], o[6]) for o in ops if o[6] == "a"], [("write", "[CREDENTIAL 7]", 50, 0, "a")])
        self.assertEqual([o[6] for o in ops if o[6] in ("b", "c")], [])

    def test_the_joined_text_is_what_the_other_statements_read(self):
        # R23a: the reader lists the token that only the continuation holds, so it may be the writer itself
        reader = "for(t of ['[CREDENTIAL 170]','[CREDENTIAL 169]'])" + READ
        f = flow({"a": self.CUT, "b": self.REST, "r": reader}, {"b": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"a": 100, "b": 100, "r": 300})
        self.assertEqual(f["deliveries"], 0)
        # R38: a rare term that only the continuation holds, quoted by the reader
        rest = "T',body:'report_final_v2.json'})"
        f = flow({"a": self.CUT, "b": rest, "r": READ + ";n='report_final_v2.json'"}, {"a": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"},
                 {"a": 100, "b": 100, "r": 300})
        self.assertEqual((f["deliveries"], f["deliveries_reader_uses_content"], f["_deliveries"][0]["shared_terms"]), (1, 1, ["report_final_v2.json"]))


class B4Places(unittest.TestCase):
    def test_unnumbered_places_are_coarse(self):
        import re
        rx = [re.compile(p) for p in RAW["coarse_channels"]]
        coarse = lambda ch: any(r.search(ch) for r in rx)
        for ch in ("hf_dataset:[HF REPO]", "hf_dataset:[REDACTED:username:000033]", "hf_dataset:[REDACTED:username:...]", "hf_dataset:[USER 41]"):
            self.assertTrue(coarse(ch), ch)
        self.assertFalse(coarse("hf_dataset:[HF REPO 5]"))

    def test_board_places_are_keyed_by_full_path(self):
        mk = "fetch('https://p/artifactory/github-remote-cache/zzBOARD/CHILD_A',{method:'MKCOL'})"
        get = "fetch('https://p/artifactory/github-remote-cache/zzBOARD/GETCHILD_'+i,{mode:'no-cors'})"
        f = flow({"w": mk, "r": get}, {"w": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"w": 100, "r": 200})
        self.assertEqual(f["deliveries"], 0)
        self.assertEqual(sorted(c["channel"] for c in f["_channels"]), ["board:zzBOARD/CHILD_A", "board:zzBOARD/GETCHILD_"])
        get2 = get.replace("GETCHILD_'+i", "CHILD_A'")
        f = flow({"w": mk, "r": get2}, {"w": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"w": 100, "r": 200})
        self.assertEqual(f["deliveries"], 1)


class B5Verbs(unittest.TestCase):
    def test_paths_info_post_is_a_read(self):
        text = "fetch('https://huggingface.co/api/datasets/[HF REPO 5]/paths-info/main',{method:'POST',body:'{}'})"
        self.assertEqual(judge(text), "read")

    def test_presigned_form_upload_is_a_write(self):
        text = ("f=new FormData;f.append('policy','x');f.append('signature','y');"
                "f.append('file',new Blob(['https://huggingface.co/datasets/[HF REPO 5]']))")
        self.assertEqual(judge(text), "write")


class B7WrittenContent(unittest.TestCase):
    def test_reader_that_quotes_what_was_written(self):
        w = COMMIT.replace("lfsFile", "path:'quarterly_findings_summary.md'")
        r = READ + ";document.body.innerText='quarterly_findings_summary.md'"
        f = flow({"w": w, "r": r, "o": "x=1"}, {"w": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"w": 100, "r": 200, "o": 5})
        self.assertEqual((f["deliveries_write_then_read"], f["deliveries_reader_uses_content"]), (1, 1))
        self.assertEqual(f["_deliveries"][0]["shared_terms"], ["quarterly_findings_summary.md"])

    def test_reader_that_quotes_nothing_is_counted_apart(self):
        f = flow({"w": COMMIT, "r": READ}, {"w": "[CREDENTIAL 170]", "r": "[CREDENTIAL 169]"}, {"w": 100, "r": 200})
        self.assertEqual((f["deliveries_write_then_read"], f["deliveries_reader_uses_content"], f["deliveries_content_checked"]), (1, 0, 1))
        self.assertFalse(f["_deliveries"][0]["uses_content"])


class B6SweepPairs(unittest.TestCase):
    def test_pairs_need_sweep_programs_and_messages_and_nothing_against(self):
        from agenttrace import identity
        ev = lambda *k: [{"key": x} for x in k]
        base = {"scored": [{"a": "B", "b": "A", "evidence": ev("key_sweep", "same_programs", "messages"), "against": []},
                           {"a": "C", "b": "D", "evidence": ev("key_sweep", "same_programs", "messages"), "against": [{"key": "parallel"}]},
                           {"a": "E", "b": "F", "evidence": ev("key_sweep", "same_programs"), "against": []}]}
        self.assertEqual(identity.sweep_self_pairs(base), {("A", "B")})


@unittest.skipUnless(os.path.isfile(RELEASE), "the Swarm Traces release (redacted_columns.csv) is not in this checkout")
class ReleaseCounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agenttrace.session import Session
        cls.s = Session()
        cls.s.load(RELEASE, "code_traces.json", {}, "release")
        cls.f = cls.s.flow

    def test_counts(self):
        f = self.f
        # 9 before fragments were joined (R13a); R0022674 + R0022675 is a commit that two anonymous runs read later
        self.assertEqual((f["deliveries_write_then_read"], f["deliveries_between_named_actors"]), (11, 4))
        self.assertEqual((f["deliveries_exact_place"], f["deliveries_reader_uses_content"], f["deliveries_content_checked"]), (8, 0, 11))
        self.assertEqual(f["joined_fragments"], [{"record": "R0022674", "continued_in": ["R0022675"]}])

    def test_audit_false_links_are_gone(self):
        got = {(d["write_id"], d["read_id"]) for d in self.f["_deliveries"]}
        for pair in [("R0005366", "R0005421"), ("R0005417", "R0005665"), ("R0006727", "R0006743"), ("R0005366", "R0006792"),
                     ("R0045942", "R0046036")]:
            self.assertNotIn(pair, got)
        for pair in [("R0006584", "R0006786"), ("R0044824", "R0045143"), ("R0044999", "R0045751")]:
            self.assertIn(pair, got)

    def test_the_joined_commit_is_counted_again(self):
        # dropped in v2.2.0 as a call cut inside its verb; with the continuation joined (R13a) it is a POST to
        # .../commit/main under the continuation's token. The audit label for both links is still "unclear".
        got = {(d["write_id"], d["read_id"]): d for d in self.f["_deliveries"]}
        for pair in [("R0022674", "R0032250"), ("R0022674", "R0032842")]:
            self.assertIn(pair, got)
            self.assertEqual((got[pair]["from"], got[pair]["channel"]), ("[CREDENTIAL 169]", "hf_dataset:[HF REPO 280]"))
        self.assertFalse(any("R0022675" in k for k in got))
        with open(os.path.join(REPO, "agenttrace", "claims", "audited_links.json"), encoding="utf-8") as fh:
            labels = {(r["write_id"], r["read_id"]): r["label"] for r in json.load(fh)["links"]}
        self.assertEqual({labels[p] for p in [("R0022674", "R0032250"), ("R0022674", "R0032842")]}, {"unclear"})

    def test_1721_1722_are_one_agent(self):
        from agenttrace import units
        m = units.units_map(self.s)
        self.assertEqual(m["messages"], {"token": 4, "agent": 2, "inside_one_agent": 2, "rejected": 0})
        self.assertEqual(m["of"]["[CREDENTIAL 1721]"], m["of"]["[CREDENTIAL 1722]"])


if __name__ == "__main__":
    unittest.main()

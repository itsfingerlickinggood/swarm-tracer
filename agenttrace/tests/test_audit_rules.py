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
        self.assertEqual((f["deliveries_write_then_read"], f["deliveries_between_named_actors"]), (9, 4))
        self.assertEqual((f["deliveries_exact_place"], f["deliveries_reader_uses_content"], f["deliveries_content_checked"]), (6, 0, 9))

    def test_audit_false_links_are_gone(self):
        got = {(d["write_id"], d["read_id"]) for d in self.f["_deliveries"]}
        for pair in [("R0005366", "R0005421"), ("R0005417", "R0005665"), ("R0006727", "R0006743"), ("R0005366", "R0006792"),
                     ("R0045942", "R0046036"), ("R0022674", "R0032250")]:
            self.assertNotIn(pair, got)
        for pair in [("R0006584", "R0006786"), ("R0044824", "R0045143"), ("R0044999", "R0045751")]:
            self.assertIn(pair, got)

    def test_1721_1722_are_one_agent(self):
        from agenttrace import units
        m = units.units_map(self.s)
        self.assertEqual(m["messages"], {"token": 4, "agent": 2, "inside_one_agent": 2, "rejected": 0})
        self.assertEqual(m["of"]["[CREDENTIAL 1721]"], m["of"]["[CREDENTIAL 1722]"])


if __name__ == "__main__":
    unittest.main()

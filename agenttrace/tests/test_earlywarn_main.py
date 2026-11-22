"""v2.3.0: the simple alarms as the main early warning, the shared-control signs as context, the pre-registration,
the benign sets, and the streaming form. Every test asserts a value."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from agenttrace import baselines, earlywarn, online
from agenttrace.session import Session

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(PKG)
APP = os.path.join(PKG, "app", "views")
DEMO = os.path.join(PKG, "samples", "demo_swarm", "demo_swarm.jsonl")
BENIGN = os.path.join(PKG, "samples", "benign_swarm", "benign_swarm.jsonl")
PLACE = earlywarn.PLACE_SIGN
os.environ.setdefault("SWARM_TRACER_NO_CACHE", "1")


def demo():
    s = Session()
    s.load(DEMO, "code_traces.json", {}, "demo")
    return s


def run(mode, setting, new_host=None, volume6=None, share=None, place_share=None, place_h=None, hours=48, harm=18.0, alert=None):
    """A hand-made run record, the shape earlywarn.extract returns."""
    base = {k: None for k, _ in baselines.BASELINES}
    base.update(new_host_12h=new_host, volume_6h=volume6)
    r = {"mode": mode, "setting": setting, "dated": True, "hours": hours, "agents": 10, "first_true_harm_h": harm,
         "first_true_message_h": 12.0, "rules": {"alert-coord2": alert}, "alarms": {"baseline": base},
         "signs": [{"id": PLACE, "name": "Two identities share one place", "family": "joint", "kind": "place", "h": place_h}] if place_h is not None else []}
    if mode != "benign":
        r["true_share"] = {"alarm": {"new_host_12h": share, "volume_6h": None}, "sign": {PLACE: place_share} if place_share is not None else {},
                           "rule": {}}
    return r


def runs():
    c = [run("coordinated", "a", 17.0, None, 0.9, 0.5, 16.0), run("coordinated", "a", 17.0, 19.0, 0.8, 0.85, 15.0),
         run("coordinated", "b", 20.0, None, 0.4, 0.3, 19.0), run("coordinated", "b", None, None, None, 0.2, 21.0)]
    b = [run("benign", "x", 30.0), run("benign", "x"), run("benign", "y"), run("benign", "y", alert=5.0), run("benign", "y")]
    return c + b


class TestMainAlarmDefinitions(unittest.TestCase):
    def test_the_four_main_alarms_and_their_frozen_parameters(self):
        self.assertEqual(baselines.MAIN_IDS, ("new_host_12h", "first_intent", "distinct_actors", "volume_6h"))
        self.assertEqual(baselines.VARIANT_IDS, ("volume_12h", "new_host_24h"))
        prm = {a["id"]: a["params"] for a in baselines.frozen_params()["main"]}
        self.assertEqual(prm["new_host_12h"], {"after_h": 12})
        self.assertEqual(prm["first_intent"], {"intent": "search_for_secrets"})
        self.assertEqual(prm["distinct_actors"], {"k_sigma": 3.0, "min_history_h": 12, "min_sd": 1.0})
        self.assertEqual(prm["volume_6h"], {"k_sigma": 3.0, "min_history_h": 6, "min_sd": 1.0})
        self.assertEqual(baselines.ROLE["volume_12h"], "variant")
        self.assertEqual(baselines.ROLE["new_host_12h"], "main")

    def test_the_parameter_hash_moves_when_a_parameter_does(self):
        before = baselines.params_sha256()
        self.assertRegex(before, r"^[0-9a-f]{64}$")
        self.assertEqual(before, baselines.params_sha256())
        changed = [dict(a, params=dict(a["params"], after_h=6)) if a["id"] == "new_host_12h" else a for a in baselines.MAIN_ALARMS]
        with mock.patch.object(baselines, "MAIN_ALARMS", changed):
            self.assertNotEqual(baselines.params_sha256(), before)

    def test_post_hoc_and_context_are_said_in_words(self):
        self.assertTrue(baselines.POST_HOC.startswith("Post-hoc on one incident"))
        self.assertIn("not a test", baselines.POST_HOC)
        self.assertTrue(baselines.CONTEXT_NOTE.startswith("Not an early warning"))
        self.assertEqual(baselines.CONTEXT_LABEL, "Context: who shares control")

    def test_which_signs_are_context(self):
        self.assertTrue(baselines.is_context({"family": "joint", "kind": "message"}))
        self.assertTrue(baselines.is_context({"family": "joint", "kind": "place"}))
        self.assertFalse(baselines.is_context({"family": "single", "kind": "harm"}))
        self.assertFalse(baselines.is_context({"family": "baseline", "kind": "baseline"}))


class TestOnTheDemoSwarm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = demo()
        cls.ew = baselines.early_warning(cls.s)

    def test_main_alarms_times_records_and_harm_shares(self):
        a = {x["id"]: x for x in self.ew["alarms"]}
        self.assertEqual(list(a), list(baselines.MAIN_IDS))
        self.assertEqual({k: v["fired"] for k, v in a.items()},
                         {"new_host_12h": True, "first_intent": False, "distinct_actors": True, "volume_6h": False})
        self.assertEqual((a["new_host_12h"]["h"], a["new_host_12h"]["record"], a["new_host_12h"]["harm_share_after"]), (15.79, "R1000237", 0.906))
        self.assertEqual((a["distinct_actors"]["h"], a["distinct_actors"]["record"], a["distinct_actors"]["harm_share_after"]), (16.0, None, 0.906))
        self.assertEqual(a["distinct_actors"]["time"], "2026-07-03 16:00")
        self.assertIn("22 distinct named actors", a["distinct_actors"]["why"])
        self.assertEqual(self.ew["first"], "new_host_12h")
        self.assertEqual([x["role"] for x in self.ew["alarms"]], ["main"] * 4)
        self.assertEqual([(x["id"], x["role"], x["fired"]) for x in self.ew["variants"]],
                         [("volume_12h", "variant", False), ("new_host_24h", "variant", False)])
        self.assertEqual(self.ew["harm_records"], 414)
        self.assertTrue(self.ew["has_intent"])

    def test_details_and_alarms_agree(self):
        d = baselines.details(self.s)
        self.assertEqual(baselines.alarms(self.s), {k: v["t"] for k, v in d.items()})
        self.assertEqual(set(d), {k for k, _ in baselines.BASELINES})
        self.assertEqual(d["volume_6h"], {"t": None, "record": None, "why": None})

    def test_context_is_the_shared_control_signs_and_says_so(self):
        ctx = self.ew["context"]
        self.assertGreaterEqual(len(ctx), 5)
        self.assertTrue(all(c["role"] == "context" for c in ctx))
        first = ctx[0]                                   # the shared-control signs come first
        self.assertEqual((first["kind"], first["shared_control"], first["h"], first["harm_share_after"]), ("place", True, 9.97, 0.995))
        self.assertEqual(first["after_alarms"], [])     # on this simulated swarm it fired before every main alarm: shown, not hidden
        self.assertFalse(any(c["kind"] == "harm" for c in ctx))
        self.assertEqual(self.ew["context_note"], baselines.CONTEXT_NOTE)

    def test_compare_marks_every_row_with_its_role(self):
        rows = baselines.compare(self.s)["rows"]
        role = {r["id"]: r["role"] for r in rows}
        self.assertEqual({i: role[i] for i in baselines.MAIN_IDS}, {i: "main" for i in baselines.MAIN_IDS})
        self.assertEqual(role["volume_12h"], "variant")
        self.assertEqual(role["message"], "context")
        self.assertEqual(role["replay:first: hf_dataset_write"], "other")

    def test_endpoint_with_and_without_a_dataset(self):
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, {"SWARM_TRACER_EARLYWARN_DIR": tmp}):
                none = earlywarn._main_get({}, {})
                got = earlywarn._main_get({"session": self.s}, {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIsNone(none["loaded"])
        self.assertEqual(none["main_ids"], list(baselines.MAIN_IDS))
        self.assertEqual(none["evidence"]["ran"], False)
        self.assertEqual(none["evidence"]["prereg_now"]["written"], False)
        self.assertEqual(got["loaded"]["first"], "new_host_12h")
        self.assertEqual(got["alarms_sha256"], baselines.params_sha256())
        self.assertEqual(got["context_label"], "Context: who shares control")

    def test_cli_prints_the_main_alarms_first(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(earlywarn.main(["alarms", DEMO, "--pack", "code_traces.json"]), 0)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].endswith("main early-warning alarms"))
        self.assertEqual([l.split()[0] for l in lines[1:5]], ["MAIN"] * 4)
        self.assertIn("90.6% of timed harm still to come", lines[1])
        self.assertIn("did not fire", lines[2])
        i = lines.index("Context: who shares control (not an early warning)")
        self.assertGreater(i, 6)
        self.assertTrue(lines[i + 1].strip().startswith("context"))
        self.assertTrue(lines[-1].startswith("Post-hoc on one incident"))


class TestTables(unittest.TestCase):
    def test_per_swarm_counts_intervals_lead_and_harm_share(self):
        rows = {r["id"]: r for r in earlywarn.main_table(runs())}
        self.assertEqual(list(rows), ["new_host_12h", "first_intent", "distinct_actors", "volume_6h", "any_main", "volume_12h", "new_host_24h"])
        self.assertEqual([rows[i]["role"] for i in rows], ["main"] * 4 + ["any"] + ["variant"] * 2)
        c = rows["new_host_12h"]["coordinated"]
        self.assertEqual((c["fired"]["k"], c["fired"]["n"]), (3, 4))
        self.assertEqual((c["before_harm"]["k"], c["before_harm"]["n"], c["before_harm"]["ci"]), (2, 4, [0.15, 0.85]))   # 17 < 18 twice
        self.assertEqual(c["median_lead_h"], 1.0)                 # leads 1, 1, -2
        self.assertEqual((c["min_lead_h"], c["max_lead_h"]), (-2.0, 1.0))
        self.assertEqual(c["harm_share_median"], 0.6)             # 0.9, 0.8, 0.4, and 0 for the swarm where it never fired
        self.assertEqual((c["beats"]["k"], c["beats"]["n"], c["beats"]["ties"]), (2, 4, 0))   # 0.9>0.5, 0.8<0.85, 0.4>0.3, 0<0.2
        self.assertEqual(c["fired"]["by_setting"], {"a": [2, 2], "b": [1, 2]})
        b = rows["new_host_12h"]["benign"]
        self.assertEqual((b["fired"]["k"], b["fired"]["n"], b["fired"]["ci"]), (1, 5, [0.036, 0.624]))
        self.assertEqual(b["per_24h"], 0.1)                       # 1 alarm in 5 swarms of 48 h = 10 days
        self.assertEqual(b["trace_days"], 10.0)
        self.assertEqual(rows["first_intent"]["coordinated"]["fired"]["k"], 0)
        self.assertIsNone(rows["first_intent"]["coordinated"]["median_lead_h"])

    def test_any_of_the_four_is_the_first_to_fire(self):
        rs = [run("coordinated", "a", 17.0, 15.0, 0.5, 0.1, 16.0), run("benign", "x", None, 3.0), run("benign", "x", 9.0, None), run("benign", "x")]
        rs[0]["true_share"]["alarm"]["volume_6h"] = 0.7
        row = next(r for r in earlywarn.main_table(rs) if r["id"] == "any_main")
        self.assertEqual(row["coordinated"]["median_lead_h"], 3.0)          # 18 - min(17, 15)
        self.assertEqual(row["coordinated"]["harm_share_median"], 0.7)      # the earlier alarm has the larger share
        self.assertEqual((row["benign"]["fired"]["k"], row["benign"]["fired"]["n"]), (2, 3))   # the union of the alarms' false alarms

    def test_resampling_whole_settings(self):
        self.assertIsNone(earlywarn._boot_share([(1, 2)]))                 # one setting cannot be resampled
        self.assertEqual(earlywarn._boot_share([(2, 2), (3, 3), (5, 5)]), [1.0, 1.0])
        lo, hi = earlywarn._boot_share([(0, 10), (10, 10)])
        self.assertEqual((lo, hi), (0.0, 1.0))                             # two opposite settings: the interval is the whole range
        blk = earlywarn._share_block([{"setting": "a", "x": 1}, {"setting": "a", "x": 0}, {"setting": "b", "x": 1}], lambda r: r["x"])
        self.assertEqual((blk["k"], blk["n"], blk["share"], blk["settings"]), (2, 3, 0.667, 2))
        self.assertEqual(blk["ci"], earlywarn.wilson(2, 3))

    def test_context_table_lists_shared_control_signs_even_when_silent(self):
        rs = [run("coordinated", "a", 17.0, None, 0.9), run("benign", "x")]
        ctx = {r["id"]: r for r in earlywarn.context_table(rs)}
        self.assertEqual(list(ctx)[:2], [earlywarn.CARRIED_SIGN, PLACE])
        self.assertEqual(ctx[PLACE]["coordinated"]["fired"]["k"], 0)
        self.assertTrue(ctx[PLACE]["shared_control"])
        self.assertEqual(ctx["alert-coord2"]["role"], "context")
        ctx2 = {r["id"]: r for r in earlywarn.context_table(runs())}
        self.assertEqual(ctx2[PLACE]["coordinated"]["fired"]["k"], 4)
        self.assertEqual(ctx2[PLACE]["coordinated"]["before_harm"]["k"], 2)     # hours 16 and 15 against a first harm at 18
        self.assertEqual(ctx2[PLACE]["coordinated"]["harm_share_median"], 0.4)  # 0.5, 0.85, 0.3, 0.2
        self.assertEqual(ctx2["alert-coord2"]["benign"]["fired"]["k"], 1)

    def test_hypotheses_are_decided_by_the_per_swarm_interval(self):
        blk = lambda k, n: {"k": k, "n": n, "ci": earlywarn.wilson(k, n), "ci_settings": None}
        row = lambda bh, beats, ben: {"id": "new_host_12h", "role": "main", "coordinated": {"before_harm": blk(*bh), "beats": blk(*beats) if beats else None},
                                      "benign": {"fired": blk(*ben)}}
        h = {x["hypothesis"]: x for x in earlywarn.hypotheses([row((20, 20), (3, 4), (0, 30))])}
        self.assertTrue(h["H1"]["holds"])            # 20/20: lower end 0.839
        self.assertFalse(h["H2"]["holds"])           # 3/4: lower end 0.301, not above 0.5
        self.assertTrue(h["H3"]["holds"])            # 0/30: upper end 0.114
        h = {x["hypothesis"]: x for x in earlywarn.hypotheses([row((11, 20), None, (0, 6))])}
        self.assertFalse(h["H1"]["holds"])           # 11/20 is a majority but the interval reaches below a half
        self.assertIsNone(h["H2"]["holds"])          # nothing to compare: not measurable, not a pass
        self.assertFalse(h["H3"]["holds"])           # 0/6: too few swarms to bound the rate below 20%
        self.assertEqual([x["id"] for x in earlywarn.HYPOTHESES], ["H1", "H2", "H3"])
        self.assertEqual(earlywarn.hypotheses([{"id": "volume_12h", "role": "variant"}]), [])     # variants are not tested

    def test_false_alarm_rows_lead_with_the_main_alarms(self):
        a = earlywarn.false_alarms(runs())
        self.assertEqual([r["id"] for r in a["rows"][:4]], list(baselines.MAIN_IDS))
        self.assertEqual([r["role"] for r in a["rows"][:6]], ["main"] * 4 + ["variant"] * 2)
        nh = a["rows"][0]
        self.assertEqual((nh["alarms"], nh["swarms"], nh["per_24h"], nh["swarm_share_ci"]), (1, 5, 0.1, [0.036, 0.624]))
        self.assertEqual(next(r for r in a["rows"] if r["id"] == "alert-coord2")["role"], "context")

    def test_benign_set_rows(self):
        rs = runs() + [dict(run("benign", "z"), dated=False)]
        bs = earlywarn.benign_set("label", "simulated", rs)
        self.assertEqual((bs["swarms"], bs["undated"], bs["trace_hours"], bs["classes"]), (5, 1, 240.0, ["x", "y"]))
        got = {r["id"]: (r["fired"]["k"], r["fired"]["n"], r["role"]) for r in bs["rows"]}
        self.assertEqual(got["new_host_12h"], (1, 5, "main"))
        self.assertEqual(got["any_main"], (1, 5, "any"))
        self.assertEqual(got["alert-coord2"], (1, 5, "context"))
        self.assertEqual(got[PLACE], (0, 5, "context"))

    def test_summary_carries_main_context_and_the_caveat(self):
        sm = earlywarn.summarize(runs())
        self.assertEqual([r["id"] for r in sm["main"]][:4], list(baselines.MAIN_IDS))
        self.assertEqual(sm["post_hoc"], baselines.POST_HOC)
        self.assertEqual(len(sm["hypotheses"]), 15)              # three hypotheses for four alarms and for any of the four
        self.assertEqual({f["id"] for f in sm["cost"]["families"]} >= set(earlywarn.MAIN_FAMILIES), True)


class TestPreregistration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_file_freezes_alarms_seeds_and_hypotheses_and_is_written_once(self):
        rec = earlywarn.prereg_v23(self.dir)
        with open(os.path.join(self.dir, "prereg_v23.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["alarms_sha256"], baselines.params_sha256())
        self.assertEqual(saved["alarms"], baselines.frozen_params())
        self.assertEqual(saved["original_generator"]["seeds"], list(range(41, 51)))
        self.assertEqual(saved["independent_generator"]["seeds"], list(range(511, 521)))
        self.assertEqual(len(saved["original_generator"]["settings"]), 12)
        self.assertEqual([h["id"] for h in saved["hypotheses"]], ["H1", "H2", "H3"])
        self.assertEqual(saved["post_hoc"], baselines.POST_HOC)
        self.assertEqual(set(saved["code_sha256"]), set(earlywarn.V23_CODE_FILES))
        self.assertEqual(rec["written_utc"], saved["written_utc"])
        self.assertNotIn("rewritten_with_results_present", saved)
        with self.assertRaises(FileExistsError):
            earlywarn.prereg_v23(self.dir)
        again = earlywarn.prereg_v23(self.dir, force=True)
        self.assertEqual(again["rewritten_with_results_present"], ["prereg_v23.json"])

    def test_status_notices_a_changed_parameter(self):
        earlywarn.prereg_v23(self.dir)
        st = earlywarn.prereg_status(self.dir)
        self.assertEqual((st["written"], st["alarms_match"], st["code_changed"]), (True, True, []))
        self.assertEqual(st["seeds"], {"original": list(range(41, 51)), "independent": list(range(511, 521))})
        changed = [dict(a, params={"after_h": 6}) if a["id"] == "new_host_12h" else a for a in baselines.MAIN_ALARMS]
        with mock.patch.object(baselines, "MAIN_ALARMS", changed):
            self.assertFalse(earlywarn.prereg_status(self.dir)["alarms_match"])

    def test_forward_refuses_without_a_preregistration(self):
        with self.assertRaises(FileNotFoundError):
            earlywarn.run_v23(self.dir, log=lambda *_: None)
        self.assertEqual(earlywarn.main(["forward23", "--out", self.dir]), 1)
        self.assertEqual(os.listdir(self.dir), [])
        self.assertEqual(earlywarn.evidence(self.dir)["ran"], False)

    def test_a_small_run_on_seen_seeds_writes_every_file(self):
        # seeds 21 and 501 were run in earlier versions: this exercises the code without touching a pre-registered seed
        earlywarn.prereg_v23(self.dir)
        sm = earlywarn.run_v23(self.dir, log=lambda *_: None, seeds=(21,), indep_seeds=(501,),
                               only=("small", "benign", "coord", "benign_plain"))
        self.assertEqual(sm["as_preregistered"], False)           # other seeds and a subset: it must not pass for the real run
        o, i = sm["generators"]["original"], sm["generators"]["independent"]
        self.assertEqual((o["seeds"], o["coordinated_runs"], o["benign_runs"]), ([21], 1, 1))
        self.assertEqual((i["seeds"], i["coordinated_runs"], i["benign_runs"]), ([501], 1, 1))
        self.assertEqual([r["id"] for r in o["main"]][:5], list(baselines.MAIN_IDS) + ["any_main"])
        nh = o["main"][0]["coordinated"]
        self.assertEqual((nh["fired"]["k"], nh["fired"]["n"]), (1, 1))
        self.assertEqual(nh["before_harm"]["k"], 0)               # on the original simulator the new-host alarm comes after the first harm
        self.assertLess(nh["median_lead_h"], 0)
        self.assertEqual(len(o["hypotheses"]), 15)
        self.assertEqual(sm["prereg"]["alarms_match"], True)
        for f in ("forward_v23.json", "forward_v23_independent.json", "summary_v23.json"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, f)), f)
        with open(os.path.join(self.dir, "forward_v23.json"), encoding="utf-8") as f:
            self.assertEqual({r["seed"] for r in json.load(f)["runs"]}, {21})
        ev = earlywarn.evidence(self.dir)
        self.assertEqual((ev["ran"], ev["prereg_now"]["written"]), (True, True))
        self.assertEqual([b["swarms"] for b in ev["benign_sets"][:2]], [1, 1])
        self.assertEqual(ev["benign_sets"][-1]["set"], "Bundled benign sample (agenttrace/samples/benign_swarm)")
        with self.assertRaises(FileExistsError):                  # results are there: the pre-registration cannot be quietly rewritten
            earlywarn.prereg_v23(self.dir)


class TestSavedForwardTest(unittest.TestCase):
    """The files in reports/earlywarn, when they are there: the order and the seeds are what the text says."""
    DIR = os.path.join(ROOT, "reports", "earlywarn")

    def _load(self, name):
        p = os.path.join(self.DIR, name)
        if not os.path.exists(p):
            self.skipTest(name + " is not on this machine")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_preregistration_came_first_and_matches(self):
        pr, sm = self._load("prereg_v23.json"), self._load("summary_v23.json")
        self.assertEqual(pr["alarms_sha256"], baselines.params_sha256())
        self.assertNotIn("rewritten_with_results_present", pr)
        self.assertEqual(sm["prereg_written_utc"], pr["written_utc"])
        self.assertEqual(sm["as_preregistered"], True)
        self.assertEqual(sm["prereg"]["code_changed"], [])
        for kind, seeds in (("original", list(range(41, 51))), ("independent", list(range(511, 521)))):
            g = sm["generators"][kind]
            self.assertEqual(g["seeds"], seeds)
            self.assertLess(pr["written_utc"], g["swarms_generated_from_utc"])      # ISO times in UTC sort as text
        self.assertEqual((sm["generators"]["original"]["coordinated_runs"], sm["generators"]["original"]["benign_runs"]), (90, 30))
        self.assertEqual((sm["generators"]["independent"]["coordinated_runs"], sm["generators"]["independent"]["benign_runs"]), (20, 50))

    def test_saved_runs_use_only_the_preregistered_seeds(self):
        fw = self._load("forward_v23.json")
        self.assertEqual(sorted({r["seed"] for r in fw["runs"]}), list(range(41, 51)))
        self.assertEqual(len(fw["runs"]), 120)
        ind = self._load("forward_v23_independent.json")
        self.assertEqual(sorted({r["seed"] for r in ind["runs"]}), list(range(511, 521)))
        self.assertEqual(len(ind["runs"]), 70)


class TestExternalBenign(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "setA", "data"))
        shutil.copy(BENIGN, os.path.join(self.root, "setA", "one.jsonl"))
        with open(os.path.join(self.root, "setA", "chat.json"), "w", encoding="utf-8") as f:     # no times anywhere
            json.dump({"history": [{"content": "look at https://www.google.com/search?q=x", "role": "user", "name": "A"},
                                   {"content": "done", "role": "assistant", "name": "B"}]}, f)
        for name in ("README.md", "manifest.json", "COUNTS.json"):
            with open(os.path.join(self.root, "setA", name), "w", encoding="utf-8") as f:
                f.write("{}")
        with open(os.path.join(self.root, "setA", "data", "part.parquet"), "wb") as f:
            f.write(b"PAR1")
        os.makedirs(os.path.join(self.root, "salt-agent-collusion"))
        shutil.copy(BENIGN, os.path.join(self.root, "salt-agent-collusion", "x.jsonl"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _tree(self):
        return sorted((os.path.join(d, f), os.path.getsize(os.path.join(d, f)), os.path.getmtime(os.path.join(d, f)))
                      for d, _, fs in os.walk(self.root) for f in fs)

    def test_counts_dated_and_undated_apart_and_changes_nothing(self):
        before = self._tree()
        res = earlywarn.external_benign(self.root, log=lambda *_: None)
        self.assertEqual(self._tree(), before)                    # read-only
        self.assertEqual([d["dataset"] for d in res["datasets"]], ["setA"])
        self.assertEqual(res["excluded"][0]["dataset"], "salt-agent-collusion")     # a collusion experiment is not a benign set
        d = res["datasets"][0]
        self.assertEqual((d["files"], d["loaded"], d["dated"], d["unreadable_format"], d["failed"]), (3, 2, 1, 1, 0))
        self.assertIsNone(d["benign_as_published"])               # a folder nobody described is marked so
        bs = d["benign_set"]
        self.assertEqual((bs["swarms"], bs["undated"]), (1, 1))  # the undated trace is not counted as "no alarm"
        self.assertEqual({r["id"]: r["fired"]["n"] for r in bs["rows"]}["new_host_12h"], 1)
        self.assertEqual((d["pattern_check"]["k"], d["pattern_check"]["n"]), (1, 2))   # the web-search line matches the secrets-search pattern
        self.assertEqual(res["pattern"], r"google\.com/search|github\.com/search|pastebin")

    def test_a_missing_folder_is_said_not_measured(self):
        res = earlywarn.external_benign(os.path.join(self.root, "nope"), log=lambda *_: None)
        self.assertEqual((res["present"], res["datasets"]), (False, []))


class TestStreaming(unittest.TestCase):
    def test_hour_alarm_is_the_streaming_form_of_the_series_alarm(self):
        counts = {**{h: 5 for h in range(15)}, 15: 99}
        self.assertEqual(baselines.series_alarm(counts, 100), (100 + 15 + 1) * 3600.0)
        a = online.HourAlarm(3.0, 12, 1.0)
        hit = None
        for h in range(17):                       # the record in hour 16 closes hour 15
            for _ in range(counts.get(h, 1)):
                hit = hit or a.add((100 + h) * 3600.0 + 1)
        self.assertEqual(hit[0], (100 + 15 + 1) * 3600.0)
        self.assertEqual(hit[1], 99)
        b = online.HourAlarm(3.0, 12, 1.0)       # not enough history: 8 hours, then a spike
        for h in range(10):
            for _ in range(99 if h == 8 else 5):
                self.assertIsNone(b.add(h * 3600.0 + 1))
        self.assertIsNone(b.close())

    def test_hour_alarm_counts_distinct_keys(self):
        a = online.HourAlarm(3.0, 2, 1.0)
        for h in range(3):
            a.add(h * 3600.0, "x")
            a.add(h * 3600.0 + 5, "x")           # the same actor twice is one actor
        for k in "abcdefgh":
            a.add(3 * 3600.0 + 1, k)
        hit = a.close()
        self.assertEqual((hit[0], hit[1]), (4 * 3600.0, 8))

    def test_monitor_emits_the_main_alarms_with_their_role(self):
        s = demo()
        res = online.replay_session(s)
        ev = {e["key"]: e for e in res["events"]}
        self.assertEqual(ev["alarm:new_host_12h"]["role"], "main")
        self.assertEqual(ev["alarm:new_host_12h"]["record"], "R1000237")      # the same record the replay names
        self.assertEqual(ev["alarm:new_host_12h"]["family"], "alarm")
        self.assertEqual(ev["alarm:distinct_actors"]["time"], "2026-07-03 16:00")
        self.assertEqual(ev["message"]["role"], "context")
        self.assertEqual(ev["replay:first: hf_dataset_write"]["role"], "other")
        self.assertNotIn("alarm:first_intent", ev)                             # the simulator never writes that action
        m = res["compare"]["main"]
        self.assertEqual((m["alarms"], m["replay"], m["both"], m["matched"]), (4, 2, 2, 2))
        self.assertEqual(online.role_of("alarm:volume_6h", "alarm", "alarm"), "main")
        self.assertEqual(online.role_of("alarm:volume_12h", "alarm", "alarm"), "variant")
        self.assertEqual(online.role_of("two_way", "joint", "two_way"), "context")
        self.assertIn("hosts", res["memory"])
        self.assertEqual(res["memory"]["hosts"]["entries"], 0)                 # dropped once the alarm has fired


class TestUi(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(APP, name), encoding="utf-8") as f:
            return f.read()

    def test_main_alarms_section_comes_first(self):
        js = self._read("fx_earlywarn.js")
        ids = [m for m in __import__("re").findall(r'\{ id: "(\w+)", title: "', js)]
        self.assertEqual(ids, ["ew_main", "earlywarn", "ew_forward", "ew_false", "ew_cost", "ew_online"])
        self.assertIn('id: "ew_main", title: "Main alarms"', js)
        self.assertIn('"/api/x/earlywarn_main"', js)
        self.assertIn("not an early warning", js)
        self.assertNotRegex(js, r"\bonclick=|\bonchange=|93\.4|91\.3|86\.9")     # no inline handlers, no hard-coded results

    def test_early_flag_tab_leads_with_the_alarms_and_labels_the_context(self):
        js = self._read("early.js")
        self.assertIn('cached("/api/x/earlywarn_main")', js)
        self.assertIn("The main early warning is four simple alarms.", js)
        self.assertIn("Post-hoc on one incident.", js)
        self.assertGreaterEqual(js.count("not an early warning"), 4)
        self.assertNotIn("before ordinary volume monitoring fires", js)          # the withdrawn lead sentence is gone
        self.assertNotIn("Tracer: alert", js)
        self.assertNotRegex(js, r"\bonclick=|\bonchange=|93\.4|91\.3|86\.9")
        self.assertIn('tabindex="0" role="button"', js)                           # the alarm list can be reached and used by keyboard
        css = self._read("early.css")
        self.assertIn(".efsig:focus-visible", css)


if __name__ == "__main__":
    unittest.main()

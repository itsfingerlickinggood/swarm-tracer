"""The v2.2.0 evaluation: independent generator, comment-only place mentions, baselines, resampling, fixed grading,
and the attribution split by thread. Tests assert values, not only shapes."""
import json
import os
import tempfile
import types
import unittest

from agenttrace import (attribution, baselines, earlywarn, groundtruth, identity, indepeval, indepgen, packs,
                        reconstruct, sensitivity, validation)
from agenttrace.session import Session

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _ev(text):
    return types.SimpleNamespace(id="R1", text=text)


class PlaceMentions(unittest.TestCase):
    pack = packs.load_pack(os.path.join(os.path.dirname(HERE), "packs", "code_traces.json"))

    def test_comment_only_mention_is_not_a_use(self):
        name = "zzALPHA_BOARD"
        self.assertEqual(reconstruct.places_of(_ev(f"// the crew keeps notes in {name}; not fetching it\nconsole.log(1)"), self.pack), set())
        self.assertEqual(reconstruct.places_of(_ev(f"x = 1  # see {name}\n"), self.pack), set())

    def test_real_use_still_counts(self):
        name = "zzALPHA_BOARD"
        self.assertEqual(reconstruct.places_of(_ev(f"fetch('https://h.example/{name}')"), self.pack), {name})
        # a name in a comment AND in code: counted once, from the code
        self.assertEqual(reconstruct.places_of(_ev(f"// {name}\nfetch('https://h.example/{name}')"), self.pack), {name})

    def test_notes_no_longer_fire_the_shared_place_sign(self):
        """The generator writes place-naming notes at random times; the sign used to fire on them (v2.1.0 +5.8 h)."""
        identity.SAVE_DECISIONS = False
        with tempfile.TemporaryDirectory() as d:
            truth = groundtruth.make(d, agents=40, seed=31, mention_share=0.25)
            s = validation._load(d, truth)
            sp = [x for x in s.rec["shared_places"] if not x["same_record"]]
            self.assertTrue(sp)
            first = min(sp, key=lambda x: x["second"])
            self.assertNotEqual(truth["records"][first["second_id"]]["do"], "mention")
            self.assertNotEqual(truth["records"][first["first_id"]]["do"], "mention")


class IndependentGenerator(unittest.TestCase):
    def test_deterministic_values(self):
        with tempfile.TemporaryDirectory() as d:
            t = indepgen.make(d, "coord", 1, agents=30, hours=48, **indepgen.CELLS["chrono_epoch60"][1])
            self.assertEqual((len(t["records"]), len(t["messages"]), len(t["harm"])), (792, 194, 43))
            t2 = indepgen.make(d, "coord", 1, agents=30, hours=48, **indepgen.CELLS["chrono_epoch60"][1])
            self.assertEqual(t["messages"], t2["messages"])

    def test_vocabulary_is_not_the_packs(self):
        pack = packs.load_pack(os.path.join(os.path.dirname(HERE), "packs", "code_traces.json"))
        with tempfile.TemporaryDirectory() as d:
            indepgen.make(d, "coord", 2, agents=30)
            with open(os.path.join(d, "trace.jsonl"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("zz", text)
            self.assertEqual({m.group(0) for _, rx in pack.shared_names for m in rx.finditer(text)}, set())

    def test_benign_classes(self):
        self.assertEqual(len(indepgen.BENIGN), 5)
        with tempfile.TemporaryDirectory() as d:
            plain = indepgen.make(d, "benign_plain", 1, agents=20)
            self.assertEqual((len(plain["messages"]), len(plain["harm"])), (0, 0))
            ci = indepgen.make(d, "benign_ci", 1, agents=20)
            self.assertGreater(len(ci["messages"]), 100)
            self.assertEqual(ci["harm"], [])
            self.assertIn("bot", ci["agents"])

    def test_scorer_reads_it_and_gets_the_audit_numbers(self):
        identity.SAVE_DECISIONS = False
        with tempfile.TemporaryDirectory() as d:
            t = indepgen.make(d, "coord", 1, agents=30, hours=48, **indepgen.CELLS["chrono_epoch60"][1])
            s = validation._load(d, t)
            sc = groundtruth.score(s, t)
        self.assertEqual(sc["true_messages"], 194)
        self.assertGreater(sc["messages"]["precision"], 0.60)
        self.assertLess(sc["messages"]["precision"], 0.80)
        self.assertGreater(sc["messages"]["recall"], 0.45)
        self.assertLess(sc["messages"]["recall"], 0.70)

    def test_grouped_by_agent_file_is_undated(self):
        with tempfile.TemporaryDirectory() as d:
            t = indepgen.make(d, "coord", 1, agents=30, hours=48, **indepgen.CELLS["grouped_epoch60"][1])
            s = validation._load(d, t)
            self.assertEqual(len(s.flow["_deliveries"]), 0)
            self.assertEqual(earlywarn.extract(s, t, {})["dated"], False)


class Baselines(unittest.TestCase):
    def test_hosts(self):
        self.assertEqual(baselines.hosts_of("curl -s http://169.254.169.254/latest/meta-data/ -H 'X: https://A.Example.org:8443/p?x=1'"),
                         {"169.254.169.254", "a.example.org"})

    def test_new_host_after_12h(self):
        evs = [types.SimpleNamespace(id=f"R{i}", text=t) for i, t in enumerate(
            ["fetch('https://a.example/x')", "fetch('https://a.example/y')", "fetch('https://b.example/x')", "fetch('https://a.example/z')", "fetch('https://c.example/')"])]
        times = {"R0": 0.0, "R1": 3600.0, "R2": 5 * 3600.0, "R3": 13 * 3600.0, "R4": 14 * 3600.0}
        intents = {e.id: "x" for e in evs}
        # b.example is new at 5 h (inside the history window); the first new host at or after 12 h is c.example at 14 h
        self.assertEqual(baselines.new_host_alarm(evs, times, intents, 12), 14 * 3600.0)
        self.assertIsNone(baselines.new_host_alarm(evs, times, intents, 15))

    def test_series_alarm(self):
        counts = {h: 5 for h in range(20)}
        self.assertIsNone(baselines.series_alarm(counts, 0))
        counts[15] = 40
        self.assertEqual(baselines.series_alarm(counts, 100), (100 + 15 + 1) * 3600.0)
        self.assertIsNone(baselines.series_alarm({**{h: 5 for h in range(8)}, 8: 99}, 0, 3.0, 12))     # not enough history

    def test_on_an_independent_swarm(self):
        identity.SAVE_DECISIONS = False
        with tempfile.TemporaryDirectory() as d:
            t = indepgen.make(d, "coord", 1, agents=30, hours=48, **indepgen.CELLS["chrono_epoch60"][1])
            s = validation._load(d, t)
            run = earlywarn.extract(s, t, {"setting": "coord", "mode": "coordinated"})
            cmp = baselines.compare(s)
        b = run["alarms"]["baseline"]
        self.assertAlmostEqual(b["new_host_12h"], 12.5, delta=0.1)
        self.assertAlmostEqual(b["volume_12h"], 20.0, delta=0.5)
        self.assertIsNone(b["new_host_24h"])
        kinds = {r["kind"] for r in cmp["rows"]}
        self.assertEqual(kinds & {"baseline", "shared-control sign", "single-agent sign"}, {"baseline", "shared-control sign", "single-agent sign"})
        for r in cmp["rows"]:
            if r["kind"] == "shared-control sign" and r["harm_share_after"] is not None:
                better = [x["id"] for x in cmp["rows"] if x["kind"] == "baseline" and (x["harm_share_after"] or -1) > r["harm_share_after"]]
                self.assertEqual(r["loses_to"], better)


class Resampling(unittest.TestCase):
    def test_wilson(self):
        self.assertEqual(earlywarn.wilson(0, 30), [0.0, 0.114])
        self.assertEqual(earlywarn.wilson(12, 30), [0.246, 0.577])
        self.assertIsNone(earlywarn.wilson(0, 0))

    def test_settings_interval_is_wider_when_settings_differ(self):
        by = {"a": [1.0] * 10, "b": [9.0] * 10, "c": [5.0] * 10}
        r = validation.resample_ci(by)
        self.assertEqual(r["median"], 5.0)
        self.assertEqual(r["settings_n"], 3)
        sw = r["swarms"][1] - r["swarms"][0]
        st = r["settings"][1] - r["settings"][0]
        self.assertGreater(st, sw)
        self.assertEqual(r["settings"][0], 1.0)
        self.assertEqual(r["settings"][1], 9.0)

    def test_one_setting_has_no_settings_interval(self):
        self.assertIsNone(validation.resample_ci({"a": [1.0, 2.0, 3.0]})["settings"])

    def test_forward_lead_interval_reports_settings(self):
        runs = []
        for st, lead in (("a", -1.0), ("b", -3.0), ("c", 2.0)):
            for _ in range(4):
                runs.append({"setting": st, "mode": "coordinated", "dated": True, "first_true_harm_h": 10.0, "first_true_message_h": 9.0,
                             "alarms": {}, "rules": {}, "signs": [{"id": "s", "name": "s", "family": "joint", "kind": "place", "h": 10.0 - lead}]})
        fw = earlywarn.forward_table(runs)
        c = fw["signs"][0]["coordinated"]["harm"]
        self.assertEqual((c["median_lead_h"], c["fired"], c["settings_firing"]), (-1.0, 12, 3))
        self.assertEqual(c["share_lead_positive"], 0.333)
        self.assertLessEqual(c["median_ci_settings"][0], -1.0)
        self.assertGreaterEqual(c["median_ci_settings"][1], -1.0)

    def test_indepeval_pooling(self):
        rows = [{"found": 10, "correct": 7}, {"found": 30, "correct": 21}]
        p = indepeval._pool(rows, "found", "correct")
        self.assertEqual((p["found"], p["correct"], p["share"]), (40, 28, 0.7))
        self.assertEqual(p["ci"], groundtruth._wilson(28, 40))


class FrozenAndSaved(unittest.TestCase):
    def test_frozen_file_names_the_forward_plan(self):
        fz = earlywarn.load_frozen()
        self.assertEqual(fz["frozen_on"], "2026-11-16")
        ft = fz["forward_test"]
        self.assertEqual(ft["seeds"], list(range(31, 41)))
        self.assertEqual(ft["independent_generator"]["seeds"], list(range(501, 511)))
        self.assertIn("agenttrace/indepgen.py", fz["code"]["sha256"])
        self.assertEqual({b["id"] for b in fz["baselines"]}, {k for k, _ in baselines.BASELINES})

    def _saved(self, name):
        p = os.path.join(ROOT, "reports", "earlywarn", name)
        if not os.path.isfile(p):
            self.skipTest(name + " not generated")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_saved_forward_runs_were_made_after_the_preregistration(self):
        pr = self._saved("prereg.json")
        for name in ("forward.json", "forward_independent.json"):
            d = self._saved(name)
            self.assertGreater(d["generated"], pr["written_utc"])
            self.assertIs(d["frozen_file_matches_prereg"], True)
        self.assertEqual(self._saved("forward.json")["seeds"], list(range(31, 41)))
        self.assertEqual(self._saved("forward_independent.json")["seeds"], list(range(501, 511)))

    def test_saved_shared_place_sign_does_not_lead(self):
        """With comment-only mentions ignored the sign fires after the first true harm, not 5.8 h before it."""
        d = self._saved("forward.json")
        row = next(r for r in d["forward"]["signs"] if r["id"] == "coordination: two identities use one place")
        c = row["coordinated"]["harm"]
        self.assertLessEqual(c["median_lead_h"], 0.0)
        self.assertLess(c["share_lead_positive"], 0.25)
        self.assertEqual(row["benign"]["fired"], 0)
        ind = self._saved("forward_independent.json")
        self.assertFalse(any(r["id"] == "coordination: two identities use one place" and r["coordinated"]["harm"]["fired"]
                             for r in ind["forward"]["signs"]))

    def test_saved_alert_is_not_a_malice_detector(self):
        ind = self._saved("forward_independent.json")
        alert = next(r for r in ind["forward"]["rules"] if r["id"] == "alert-coord2")
        self.assertGreaterEqual(alert["benign"]["fired"] / alert["benign"]["n"], 0.5)


class AttributionSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        identity.SAVE_DECISIONS = False
        cls.tmp = tempfile.mkdtemp()
        t = groundtruth.make(cls.tmp, agents=30, seed=3)
        cls.s = Session()
        cls.s.load(os.path.join(cls.tmp, "trace.jsonl"), t["pack"], {}, "split-test.jsonl")

    def test_pools_are_disjoint_and_cover_all_roots(self):
        b = attribution._base(self.s)
        roots = {b["root"][r] for r in b["acts"] if self.s.actor[r][1] in ("named", "token", "token_via_thread")}
        tr = attribution._hide_half(self.s, 1, share=1.0, pool=attribution.TRAIN_POOL)
        te = attribution._hide_half(self.s, 1, share=1.0, pool=attribution.TEST_POOL)
        self.assertFalse(tr & te)
        self.assertEqual(tr | te, roots)
        self.assertEqual(attribution._pool_of("R0001"), attribution._pool_of("R0001"))
        self.assertTrue(tr and te)

    def test_no_scored_thread_was_a_training_row(self):
        for seed in (1, 2, 3, 4):
            hide = attribution._hide_half(self.s, seed, pool=attribution.TEST_POOL)
            self.assertTrue(all(attribution._pool_of(r) == attribution.TEST_POOL for r in hide))
        for seed in attribution.TRAIN_SEEDS:
            hide = attribution._hide_half(self.s, seed, pool=attribution.TRAIN_POOL)
            self.assertTrue(all(attribution._pool_of(r) == attribution.TRAIN_POOL for r in hide))
        h = attribution.holdout(self.s, seeds=(1, 2), big=0)
        self.assertEqual(h["split"]["pool"], attribution.TEST_POOL)

    def test_real_run_coverage_is_reported_apart(self):
        a = attribution.attribution(self.s)
        rr = a["real_runs"]
        self.assertEqual(rr["runs"], a["runs"])
        self.assertEqual(rr["linked"], sum(rr["by_band"].values()))
        self.assertEqual(rr["share"], round(rr["linked"] / rr["runs"], 4) if rr["runs"] else None)
        self.assertIn("hidden named threads", a["holdout"]["split"]["coverage_is"].lower())


class InsiderGrading(unittest.TestCase):
    def test_tolerance_is_fixed_in_advance(self):
        g = sensitivity._grading()
        self.assertEqual(g["tolerance_h"], 1.0)
        self.assertEqual(g["fixed_on"], "2026-11-16")
        self.assertEqual(set(g["independent_checks"]), {"milestone", "per_day", "span_start", "span_end"})
        # whatever the tool's own dating error, the tolerance does not move
        fake = types.SimpleNamespace(rec={"time_test": {"blocks": [{"timed": True, "fit_error_hours_p90": 9.0}]}})
        self.assertEqual(sensitivity._tolerance_h(fake), 1.0)
        self.assertEqual(sensitivity._fit_error_h(fake), 9.0)

    def test_every_finding_check_is_classified(self):
        with open(sensitivity.INSIDERS, encoding="utf-8") as f:
            spec = json.load(f)
        g = spec["grading"]
        kinds = {x["check"]["kind"] for x in spec["findings"]}
        self.assertEqual(kinds, set(g["independent_checks"]) | set(g["circular_checks"]))
        self.assertEqual(len(spec["findings"]), 41)

    def test_saved_grading_on_the_release(self):
        p = os.path.join(ROOT, "reports", "evaluation", "insiders_graded.json")
        if not os.path.isfile(p):
            self.skipTest("not generated")
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["tolerance_h"], 1.0)
        self.assertTrue(r["tolerance_fixed_in_advance"])
        self.assertEqual(r["split"]["independent_time_checks"]["total"] + r["split"]["circular_checks"]["total"], r["total"])
        for f_ in r["findings"]:
            d = f_["evidence"]["numbers"].get("difference_h")
            if f_["id"] in ("credential_first_use", "hdf5_file_read") and d is not None:
                self.assertEqual(f_["status"] == "recovered", abs(d) <= 1.0)


if __name__ == "__main__":
    unittest.main()

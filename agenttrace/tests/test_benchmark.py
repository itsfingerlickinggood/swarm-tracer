import os
import shutil
import tempfile
import unittest

from agenttrace import benchmark, groundtruth, validation

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE = os.path.join(REPO, "redacted_columns.csv")


class TestAuditFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = benchmark.load_audit()

    def test_structure(self):
        self.assertEqual(benchmark.check_audit(self.audit), [])
        self.assertEqual(self.audit["made"], "2026-11-13")
        self.assertIn("not independently double-labelled", self.audit["labelled_by"])

    def test_covers_v110_and_later_links(self):
        links = self.audit["links"]
        self.assertEqual(sum(1 for r in links if r["reported_v110"]), 166)
        self.assertTrue(any(r["reported_now"] and not r["reported_v110"] for r in links))
        self.assertEqual(sum(self.audit["counts"].values()), len(links))

    def test_every_link_has_an_endpoint_kind(self):
        kinds = {r["endpoint_kind"] for r in self.audit["links"]}
        self.assertEqual(kinds, {"named_named", "involves_run"})
        for r in self.audit["links"]:
            run = r["from"].startswith("run:") or r["to"].startswith("run:")
            self.assertEqual(r["endpoint_kind"], "involves_run" if run else "named_named")
        by = self.audit["counts_by_endpoint_kind"]
        self.assertEqual(sum(sum(v.values()) for v in by.values()), len(self.audit["links"]))
        self.assertGreater(len(self.audit["links"]), 182)

    def test_text_is_short(self):
        for r in self.audit["links"]:
            self.assertLessEqual(len(r["write_snippet"]), 160)
            self.assertLessEqual(len(r["read_snippet"]), 160)

    def test_score_on_the_file_itself(self):
        links = self.audit["links"]
        # reporting exactly the true links: precision and recall 1, no regressions
        true = [(r["write_id"], r["read_id"]) for r in links if r["label"] == "true_message"]
        res = benchmark.score(true, self.audit)
        self.assertEqual(res["precision"]["value"], 1.0)
        self.assertEqual(res["recall"]["value"], 1.0)
        self.assertEqual(res["disagreements"], [])
        # reporting what v1.1.0 reported: its 166 links, with the false ones listed
        old = [(r["write_id"], r["read_id"]) for r in links if r["reported_v110"]]
        res = benchmark.score(old, self.audit)
        self.assertEqual(res["reported_now"], 166)
        self.assertEqual(res["then_vs_now"]["v110"]["reported"], 166)
        self.assertEqual(res["precision"]["k"], sum(1 for r in links if r["reported_v110"] and r["label"] == "true_message"))
        self.assertEqual(res["precision"]["n"], 166 - sum(1 for r in links if r["reported_v110"] and r["label"] == "unclear"))
        lo, hi = res["precision"]["ci"]
        self.assertTrue(0 <= lo <= res["precision"]["value"] <= hi <= 1)
        self.assertEqual(len(res["regressions"]["false_links_reported"]), res["precision"]["n"] - res["precision"]["k"])
        self.assertEqual(sum(c["v110"] for c in res["confusion"]), 166)

    def test_groups_and_grades(self):
        links = self.audit["links"]
        pairs = [{"write_id": r["write_id"], "read_id": r["read_id"], "from": r["from"], "to": r["to"],
                  "grade": "weak" if i % 2 else "inferred"} for i, r in enumerate(links) if r["label"] == "true_message"]
        res = benchmark.score(pairs, self.audit)
        g = res["groups"]
        self.assertEqual(g["all"]["reported"], len(pairs))
        self.assertEqual(g["named_named"]["reported"] + g["involves_run"]["reported"], len(pairs))
        self.assertEqual(g["all"]["precision"]["value"], 1.0)
        self.assertEqual(sum(res["by_grade"][k]["reported"] for k in benchmark.GRADES), len(pairs))
        self.assertEqual(res["by_grade"]["direct"]["precision"]["value"], None)
        self.assertEqual(g["pool"]["named_named"]["links"] + g["pool"]["involves_run"]["links"], len(links))
        # a false link in the named group lowers only that group
        bad = next(r for r in links if r["label"] == "false_write" and r["endpoint_kind"] == "named_named")
        res = benchmark.score(pairs + [{"write_id": bad["write_id"], "read_id": bad["read_id"], "from": bad["from"], "to": bad["to"]}], self.audit)
        self.assertLess(res["groups"]["named_named"]["precision"]["value"], 1.0)

    def test_unknown_links_are_set_apart(self):
        res = benchmark.score([("RX", "RY")], self.audit)
        self.assertEqual(res["reported_now_not_audited"], 1)
        self.assertIsNone(res["precision"]["value"])
        self.assertEqual(res["recall"]["k"], 0)
        self.assertEqual(len(res["regressions"]["true_links_missed"]), res["true_links_in_pool"])

    def test_registered_and_other_data(self):
        from agenttrace import extensions
        get, _ = extensions.routes()
        self.assertIn("benchmark", get)
        d = tempfile.mkdtemp()
        try:
            groundtruth.make(d, agents=8, seed=1)
            from agenttrace.session import Session
            os.environ["SWARM_TRACER_NO_CACHE"] = "1"
            s = Session()
            s.load(os.path.join(d, "trace.jsonl"), "code_traces.json", {}, "sim")
            out = get["benchmark"]({"session": s}, {})
            self.assertFalse(out["applies"])
            self.assertIn("why", out)
        finally:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
            shutil.rmtree(d, ignore_errors=True)
        with self.assertRaises(LookupError):
            get["benchmark"]({"session": None}, {})


@unittest.skipUnless(os.path.isfile(RELEASE), "the Swarm Traces release (redacted_columns.csv) is not in this checkout")
class TestRealBenchmark(unittest.TestCase):
    def test_run(self):
        old = os.environ.get("SWARM_TRACER_NO_CACHE")
        os.environ.pop("SWARM_TRACER_NO_CACHE", None)     # the disk cache makes a second run quick
        try:
            res = benchmark.run(RELEASE)
        finally:
            if old is not None:
                os.environ["SWARM_TRACER_NO_CACHE"] = old
        self.assertEqual(res["audited_links"], len(benchmark.load_audit()["links"]))
        self.assertEqual(res["reported_now"], res["reported_now_audited"] + res["reported_now_not_audited"])
        self.assertEqual(res["then_vs_now"]["v110"]["reported"], 166)
        self.assertIn("Precision now", benchmark.report_text(res))
        # every delivery the code reports on the release has been read by hand
        self.assertEqual(res["reported_now_not_audited"], 0)
        self.assertEqual(res["groups"]["all"]["reported"], res["reported_now"])
        self.assertGreaterEqual(res["precision"]["value"], 0.8)
        self.assertEqual(res["regressions"]["true_links_missed"], [])
        self.assertIn("independent", res)
        self.assertGreater(res["independent"]["decided"]["agreement"]["value"], 0.85)
        self.assertIn("Precision by grade", benchmark.report_text(res))


class TestIndependentMethod(unittest.TestCase):
    PLACE = "[REDACTED:destination:000001]"

    def op(self, text):
        return benchmark.independent_ops(text, self.PLACE)[0]

    def test_verbs_found_by_different_routes(self):
        p = self.PLACE
        self.assertEqual(self.op(f"fetch('https://huggingface.co/api/datasets/{p}',{{method:'POST',body:b}})"), "write")
        self.assertEqual(self.op(f"fetch('https://huggingface.co/datasets/{p}',{{headers:{{A:'x'}}}})"), "read")
        self.assertEqual(self.op(f"x.open('PUT','https://huggingface.co/datasets/{p}',false)"), "write")
        self.assertEqual(self.op(f"u='https://huggingface.co/datasets/{p}';fetch(u,{{method:'POST'}})"), "write")
        self.assertEqual(self.op(f"u='https://huggingface.co/datasets/{p}';fetch(u,{{headers:{{}}}})"), "read")
        self.assertEqual(self.op(f"r=u.urlopen(u.Request('https://huggingface.co/datasets/{p}',data=d))"), "write")
        self.assertEqual(self.op(f"r=u.urlopen(u.Request('https://huggingface.co/datasets/{p}'))"), "read")
        self.assertEqual(self.op(f"o={{method:'POST'}};fetch('https://huggingface.co/datasets/{p}',o)"), "write")

    def test_a_get_then_a_post_elsewhere_is_a_read(self):
        text = (f"(async()=>{{let u='https://huggingface.co/datasets/{self.PLACE}',r=await fetch(u,{{headers:{{}}}}),"
                "q=await fetch('https://elsewhere.example/x',{method:'POST',body:'b'})})()")
        self.assertEqual(self.op(text), "read")

    def test_lfs_operation_decides_and_a_hidden_one_is_unknown(self):
        p = self.PLACE
        up = f"U='https://h/https://huggingface.co/datasets/{p}/info/lfs/objects/batch';B={{operation:'upload'}};fetch(U,{{method:'POST',body:B}})"
        dl = up.replace("upload", "download")
        self.assertEqual(self.op(up), "write")
        self.assertEqual(self.op(dl), "read")
        self.assertIsNone(self.op(up.replace("B={operation:'upload'}", "B={}")))

    def test_cut_off_call_is_unknown(self):
        self.assertIsNone(self.op(f"x=await fetch('https://huggingface.co/api/datasets/{self.PLACE}',{{method"))

    def test_kappa(self):
        self.assertEqual(benchmark.kappa([True, False, True, False], [True, False, True, False]), 1.0)
        self.assertEqual(benchmark.kappa([True, True, False, False], [True, False, True, False]), 0.0)
        self.assertIsNone(benchmark.kappa([], []))
        self.assertIsNone(benchmark.kappa([True, True], [True, True]))

    def test_agreement_on_a_fake_session(self):
        p = self.PLACE
        class E:
            def __init__(self, t):
                self.text = t
        s = type("S", (), {})()
        s.by_id = {"W": E(f"fetch('https://huggingface.co/api/datasets/{p}',{{method:'POST',body:b}})"),
                   "R": E(f"fetch('https://huggingface.co/datasets/{p}')"),
                   "R2": E(f"fetch('https://huggingface.co/api/datasets/{p}',{{method:'POST',body:b}})")}
        audit = {"links": [
            {"write_id": "W", "read_id": "R", "channel_now": "hf_dataset:" + p, "label": "true_message", "reason": "r"},
            {"write_id": "W", "read_id": "R2", "channel_now": "hf_dataset:" + p, "label": "read_not_a_read", "reason": "r"},
            {"write_id": "W", "read_id": "R2", "channel_now": "hf_dataset:" + p, "label": "unclear", "reason": "r"}]}
        out = benchmark.independent_agreement(s, audit)
        self.assertEqual(out["decided"]["n"], 2)
        self.assertEqual(out["decided"]["agreement"]["value"], 1.0)
        self.assertEqual(out["decided"]["matrix"], {"true_yes": 1, "true_no": 0, "false_yes": 0, "false_no": 1})
        self.assertEqual(out["unclear_links"], 1)
        self.assertEqual(out["disagreements"], [])


class TestRealWorldSimulator(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_old_settings_unchanged_by_default(self):
        a = groundtruth.make(os.path.join(self.dir, "a"), agents=12, seed=4)
        b = groundtruth.make(os.path.join(self.dir, "b"), agents=12, seed=4, realworld=0.0)
        self.assertEqual(a["messages"], b["messages"])
        self.assertNotIn("realworld", a["params"])
        with open(os.path.join(self.dir, "a", "trace.jsonl")) as f, open(os.path.join(self.dir, "b", "trace.jsonl")) as g:
            self.assertEqual(f.read(), g.read())

    def test_realworld_shapes_and_exact_truth(self):
        t = groundtruth.make(self.dir, agents=30, seed=2, realworld=0.7)
        shapes = {x.get("shape") for x in t["records"].values()} - {None}
        self.assertTrue(set(groundtruth.RW_READS) <= shapes and set(groundtruth.RW_WRITES) <= shapes, shapes)
        import json
        with open(os.path.join(self.dir, "trace.jsonl")) as f:
            text = {r["id"]: r["text"] for r in map(json.loads, f)}
        recs = t["records"]
        self.assertTrue(any("operation:'download'" in text[r] for r, x in recs.items() if x.get("shape") == "lfs_download"))
        self.assertTrue(any("urlopen(" in text[r] for r, x in recs.items() if x.get("shape") == "py_read"))
        self.assertTrue(any("relay.example.net/https://huggingface.co" in v for v in text.values()))
        self.assertTrue(any("] REPO " in p for p in t["places"]))
        for w, r, place in t["messages"]:
            # every true message: a record that really wrote the place, read by a different agent, later
            self.assertTrue(recs[w].get("wrote"))
            self.assertIn(place, (recs[w].get("place"), recs[w].get("wrote_place")))
            self.assertNotEqual(recs[w]["agent"], recs[r]["agent"])
            self.assertLessEqual(recs[w]["t"], recs[r]["t"])
            if not recs[r].get("hidden"):
                self.assertIn(place.split(":", 1)[1], text[r])
        # an exfiltrating read writes its copy to a different dataset, never to the one it read
        for r, x in recs.items():
            if x.get("shape") == "exfil_dataset":
                self.assertNotEqual(x["place"], x["wrote_place"])

    def test_benign_realworld_has_no_messages(self):
        t = groundtruth.make(self.dir, agents=20, seed=1, mode="benign", realworld=0.7)
        self.assertEqual(t["messages"], [])
        self.assertEqual(t["harm"], [])
        self.assertTrue(any(x.get("shape") for x in t["records"].values()))

    def test_settings_and_link_scoring(self):
        names = [x[0] for x in validation.SETTINGS]
        self.assertIn("realworld", names)
        self.assertIn("benign_realworld", names)
        truth = {"messages": [["a", "b", "p"], ["c", "d", "p"]],
                 "records": {k: {"agent": k.upper() if k != "b" else "B"} for k in "abcd"}}
        sc = validation.score_links([("a", "b"), ("a", "d")], truth)
        self.assertEqual((sc["found"], sc["correct"], sc["true"]), (2, 1, 2))
        self.assertEqual(sc["precision"], 0.5)
        self.assertEqual(sc["between_agents"], 2)


if __name__ == "__main__":
    unittest.main()

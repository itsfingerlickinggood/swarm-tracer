"""What-if mode, reference comparison, chain of custody, SOC exports and the case file's custody and summary."""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest

from agenttrace import casework, extensions, fx_whatif as fx, groundtruth, identity
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls._old = os.environ.get("SWARM_TRACER_HOME")
        os.environ["SWARM_TRACER_HOME"] = cls.home
        cls._save = identity.SAVE_DECISIONS
        identity.SAVE_DECISIONS = False
        cls.dir = tempfile.mkdtemp()
        cls.truth = groundtruth.make(cls.dir, agents=24, seed=2)
        cls.path = os.path.join(cls.dir, "trace.jsonl")
        cls.s = Session()
        cls.s.load(cls.path, cls.truth["pack"], {}, "fx-whatif-test.jsonl")

    @classmethod
    def tearDownClass(cls):
        identity.SAVE_DECISIONS = cls._save
        if cls._old is None:
            os.environ.pop("SWARM_TRACER_HOME", None)
        else:
            os.environ["SWARM_TRACER_HOME"] = cls._old
        shutil.rmtree(cls.dir, ignore_errors=True)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.s._id_decisions = {}
        self.s._fx_dec = {"messages": {}, "signs": {}}
        self.s._fx_wi = None


class TestWhatIf(_Base):
    def test_no_decisions_accepted_rule_matches(self):
        w = fx.whatif(self.s, "accepted")
        a, b = w["as_counted"], w["after"]
        for k in ("agents", "messages", "pairs", "largest_group"):
            self.assertEqual(a[k], b[k], k)
        self.assertEqual(a["agents"], a["named_actors"])
        self.assertTrue(all(g["status"] == "unchanged" for g in w["signs"]))
        # "as counted" agrees with the flow's own count of messages between named actors (no self-messages here)
        named = [d for d in self.s.flow["_deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")
                 and d["from"] != d["to"]]
        self.assertEqual(a["messages"], len(named))

    def test_accepted_merge_turns_messages_into_self_talk(self):
        d = next(d for d in self.s.flow["_deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")
                 and d["from"] != d["to"])
        a, b = sorted((d["from"], d["to"]))
        between = sum(1 for x in self.s.flow["_deliveries"] if {x["from"], x["to"]} == {a, b})
        self.s._id_decisions = {(a, b): "accept"}
        w = fx.whatif(self.s, "accepted")
        self.assertEqual(w["after"]["agents"], w["as_counted"]["agents"] - 1)
        self.assertEqual(w["after"]["inside_one_agent"], between)
        self.assertEqual(w["after"]["messages"], w["as_counted"]["messages"] - between)
        self.assertEqual(w["groups_total"], 1)
        self.assertEqual(sorted(w["groups"][0]["actors"]), [a, b])

    def test_estimate_rule_merges_high_pairs_unless_rejected(self):
        w = fx.whatif(self.s, "estimate")
        est = identity.identity(self.s)["estimate"]["estimated_agents"]
        self.assertEqual(w["after"]["agents"], est)
        # merging can only remove messages and delay or drop joint signs
        self.assertLessEqual(w["after"]["messages"], w["as_counted"]["messages"])
        for g in w["signs"]:
            if g["family"] == "joint" and g["after"]:
                self.assertGreaterEqual(g["after"]["time"], g["time"][:16])

    def test_reject_messages_and_signs(self):
        d = self.s.flow["_deliveries"][0]
        mid = d["write_id"] + ">" + d["read_id"]
        r = fx.decide(self.s, {"kind": "message", "ids": [mid], "action": "reject", "by": "tester"})
        self.assertEqual(r["messages"], 1)
        self.assertTrue(os.path.exists(fx.decisions_path(self.s)))
        w = fx.whatif(self.s, "accepted")
        named = not d["from"].startswith("run:") and not d["to"].startswith("run:")
        self.assertEqual(w["after"]["rejected_messages"], len(fx._delivery_index(self.s)[mid]) if named else 0)
        self.assertTrue(any(m["id"] == mid and m["rejected"] for m in fx.record_messages(self.s, d["read_id"])))
        # reject the first joint sign: the first joint sign after is another one
        first = next(g for g in w["signs"] if g["family"] == "joint")
        fx.decide(self.s, {"kind": "sign", "ids": [first["key"]], "action": "reject"})
        w2 = fx.whatif(self.s, "accepted")
        self.assertEqual(next(g for g in w2["signs"] if g["key"] == first["key"])["status"], "rejected")
        self.assertNotEqual((w2["first_joint"]["after"] or {}).get("key"), first["key"])
        lst = fx.decisions_listing(self.s)
        self.assertEqual(lst["messages"][0]["by"], "tester")
        self.assertEqual(lst["signs"][0]["key"], first["key"])
        fx.decide(self.s, {"kind": "message", "ids": [mid], "action": "restore"})
        fx.decide(self.s, {"clear": True})
        self.assertEqual(fx.whatif(self.s, "accepted")["decisions"]["signs_rejected"], 0)

    def test_bad_decisions(self):
        with self.assertRaises(LookupError):
            fx.decide(self.s, {"kind": "message", "ids": ["nope>nada"], "action": "reject"})
        with self.assertRaises(LookupError):
            fx.decide(self.s, {"kind": "sign", "ids": ["no-such-sign"], "action": "reject"})
        with self.assertRaises(ValueError):
            fx.decide(self.s, {"kind": "other", "ids": ["x"]})
        with self.assertRaises(ValueError):
            fx.whatif(self.s, "everything")


class TestCustodyAndExports(_Base):
    def test_custody_hashes(self):
        c = fx.custody(self.s)
        with open(self.path, "rb") as f:
            want = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(c["files"][0]["sha256"], want)
        self.assertEqual(c["files"][0]["role"], "read")
        ids = hashlib.sha256("".join(rid + "\n" for rid in sorted(e.id for e in self.s.events)).encode()).hexdigest()
        self.assertEqual(c["record_ids_sha256"], ids)
        self.assertEqual(c["pack"]["file"], self.truth["pack"])
        self.assertTrue(c["pack"]["sha256"])
        self.assertTrue(c["tool"]["version"])
        self.assertTrue(c["loaded_at"])
        self.assertEqual(len(c["fingerprint"]), 64)
        self.assertEqual(fx.custody(self.s)["fingerprint"], c["fingerprint"])   # stable

    def test_timeline_csv(self):
        r = fx.export(self.s, "timeline_csv")
        lines = r["content"].splitlines()
        self.assertTrue(lines[0].startswith("# Dataset"))
        body = [x for x in lines if not x.startswith("#")]
        rows = list(csv.DictReader(io.StringIO("\n".join(body))))
        self.assertEqual(len(rows), len(self.s.rec["_times"]))
        self.assertEqual(r["count"], len(rows))
        self.assertEqual(rows, sorted(rows, key=lambda x: x["time"]))
        self.assertIn(rows[0]["harmful"], ("yes", "no"))

    def test_timesketch_csv(self):
        r = fx.export(self.s, "timesketch_csv")
        rows = list(csv.DictReader(io.StringIO(r["content"])))
        self.assertEqual(rows[0]["data_type"], "swarmtracer:custody")
        for x in rows[:20]:
            self.assertTrue(x["message"])
            self.assertRegex(x["datetime"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
            self.assertTrue(x["timestamp_desc"])

    def test_formula_cells_neutralised(self):
        self.assertEqual(fx._cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(fx._cell("ok"), "ok")

    def test_stix_bundle(self):
        r = fx.export(self.s, "stix")
        b = json.loads(r["content"])
        self.assertEqual(b["type"], "bundle")
        ids = [o["id"] for o in b["objects"]]
        self.assertEqual(len(ids), len(set(ids)))
        idre = re.compile(r"^[a-z0-9-]+--[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        types = {o["type"] for o in b["objects"]}
        self.assertTrue({"identity", "indicator", "attack-pattern", "sighting", "note", "grouping"} <= types)
        known = set(ids)
        for o in b["objects"]:
            self.assertRegex(o["id"], idre)
            self.assertEqual(o["spec_version"], "2.1")
            self.assertTrue(o["id"].startswith(o["type"] + "--"))
            for k in ("created_by_ref", "sighting_of_ref"):
                if k in o:
                    self.assertIn(o[k], known)
            for k in ("where_sighted_refs", "object_refs", "observed_data_refs"):
                for ref in o.get(k, []):
                    self.assertIn(ref, known)
            if o["type"] == "indicator":
                self.assertEqual(o["pattern_type"], "stix")
                self.assertRegex(o["pattern"], r"^\[[a-z0-9-]+:[a-z_]+ = '.*'\]$")
            if o["type"] == "attack-pattern":
                self.assertTrue(o["kill_chain_phases"][0]["phase_name"])
        # deterministic ids
        b2 = json.loads(fx.export(self.s, "stix")["content"])
        self.assertEqual(ids, [o["id"] for o in b2["objects"]])
        self.assertEqual(b["id"], b2["id"])

    def test_detections(self):
        r = fx.export(self.s, "detections")
        d = json.loads(r["content"])
        self.assertTrue(d["detections"])
        self.assertIn("custody", d)
        self.assertTrue(all(x["logic"] for x in d["detections"]))
        with self.assertRaises(ValueError):
            fx.export(self.s, "pdf")

    def test_case_export_has_summary_custody_and_truth_and_escapes(self):
        st = {"session": self.s}
        casework.post_case(st, {}, json.dumps({"title": "T", "notes": "n", "investigator": "<b>Eve</b>",
                                               "items": [{"kind": "record", "key": self.s.events[3].id, "note": "<script>x</script>",
                                                          "by": "<i>Eve</i>"}]}).encode())
        h = casework.get_case_export(st, {"format": "html", "base": "javascript:alert(1)//"})["html"]
        self.assertIn("Summary", h)
        self.assertIn("Chain of custody", h)
        self.assertIn(fx.custody(self.s)["record_ids_sha256"], h)
        self.assertIn("Ground-truth score", h)
        self.assertIn("&lt;b&gt;Eve&lt;/b&gt;", h)
        self.assertIn("&lt;i&gt;Eve&lt;/i&gt;", h)
        self.assertNotIn("<script>x", h)
        self.assertNotIn("javascript:", h)
        j = casework.get_case_export(st, {"format": "json"})["dossier"]
        self.assertEqual(j["investigator"], "<b>Eve</b>")
        self.assertIn("fingerprint", j["custody"])
        self.assertTrue(j["ground_truth"]["available"])


class TestReference(_Base):
    def test_deviations(self):
        other = tempfile.mkdtemp()
        try:
            t2 = groundtruth.make(other, agents=12, seed=5)
            ref = Session()
            ref.load(os.path.join(other, "trace.jsonl"), t2["pack"], {}, "ref.jsonl")
            rows = fx.deviations(fx.ref_measures(self.s), fx.ref_measures(ref))
            self.assertEqual({r["key"] for r in rows}, {m[0] for m in fx.REF_MEASURES})
            for r in rows:
                self.assertTrue(r["text"])
                if r["ratio"] is not None:
                    self.assertEqual(r["flag"], r["ratio"] >= 2 or r["ratio"] <= 0.5)
            same = fx.deviations(fx.ref_measures(self.s), fx.ref_measures(self.s))
            self.assertFalse(any(r["flag"] for r in same))
            # the reference route: set it directly and read the deviations
            fx.REF.update(session=ref, source={"kind": "path", "name": "ref.jsonl"}, busy=False, error=None)
            out = fx.reference_state({"session": self.s})
            self.assertEqual(len(out["rows"]), len(fx.REF_MEASURES))
            self.assertFalse(out["same_dataset"])
        finally:
            fx.REF.update(session=None, source=None)
            shutil.rmtree(other, ignore_errors=True)

    def test_deviation_wording(self):
        rows = {r["key"]: r for r in fx.deviations({"messages_per_actor": 6.0, "two_way_share": 0.5, "joint_signs": 3},
                                                   {"messages_per_actor": 1.0, "two_way_share": 0.1, "joint_signs": 0})}
        self.assertTrue(rows["messages_per_actor"]["flag"])
        self.assertIn("6.0x", rows["messages_per_actor"]["text"])
        self.assertTrue(rows["two_way_share"]["flag"])
        self.assertIn("+40 points", rows["two_way_share"]["text"])
        self.assertIn("reference has none", rows["joint_signs"]["text"])
        self.assertIn("Cannot compare", rows["wait_median_h"]["text"])


class TestSmallTraceAndRoutes(unittest.TestCase):
    def test_small_trace_and_routes(self):
        d = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        old = os.environ.get("SWARM_TRACER_HOME")
        os.environ["SWARM_TRACER_HOME"] = home
        try:
            s = Session()
            s.load(write_trace(d), "generic.json", {"text": "body"})
            st = {"session": s}
            get, post = extensions.routes()
            for k in ("fx_whatif", "fx_whatif_decisions", "fx_whatif_record", "fx_reference", "fx_custody", "fx_export"):
                self.assertIn(k, get)
            for k in ("fx_whatif_decide", "fx_reference_load", "fx_reference_clear"):
                self.assertIn(k, post)
            w = get["fx_whatif"](st, {})
            self.assertIn("as_counted", w)
            for f in fx.EXPORTS:
                self.assertTrue(get["fx_export"](st, {"format": f})["content"])
            self.assertTrue(get["fx_custody"](st, {})["files"][0]["sha256"])
            with self.assertRaises(LookupError):
                get["fx_whatif"]({"session": Session()}, {})
            with self.assertRaises(ValueError):
                post["fx_reference_load"](st, {}, json.dumps({"path": os.path.join(d, "missing")}).encode())
        finally:
            if old is None:
                os.environ.pop("SWARM_TRACER_HOME", None)
            else:
                os.environ["SWARM_TRACER_HOME"] = old
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

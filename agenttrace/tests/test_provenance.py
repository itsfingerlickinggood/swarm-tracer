"""Tests for the provenance manifest tool (agenttrace/tools/provenance.py) and the reproducible-build helper.

Offline and fast: nothing here loads a dataset. The values themselves are checked by
`python3 -m agenttrace.tools.provenance verify`, not by these tests.
"""
import json
import os
import re
import shutil
import tempfile
import unittest

from agenttrace.tools import provenance as P
from agenttrace.tools import repro


class FormatTests(unittest.TestCase):
    def test_int_allows_thousands_commas(self):
        rx = P.render("<v> records", 189579, "int")
        self.assertTrue(re.search(rx, "the release (189,579 records)"))
        self.assertTrue(re.search(rx, "189579 records"))
        self.assertFalse(re.search(rx, "189,580 records"))

    def test_percent_rounds_half_up(self):
        for share, shown in ((0.895, "90"), (0.5869, "59"), (0.083, "8"), (0.832, "83"), (0.502, "50"), (0.9474, "95"), (1.0, "100")):
            self.assertTrue(re.fullmatch(P.FORMATS["pct"][0](share), shown), (share, shown))
        self.assertTrue(re.fullmatch(P.FORMATS["pct1"][0](0.0762), "7.6"))

    def test_decimals(self):
        self.assertTrue(re.fullmatch(P.FORMATS["f1"][0](5.18), "5.2"))
        self.assertTrue(re.fullmatch(P.FORMATS["f0"][0](20.48), "20"))
        self.assertTrue(re.fullmatch(P.FORMATS["f2"][0](2.2), "2.20"))

    def test_words(self):
        self.assertEqual(P.number_word(7), "seven")
        self.assertEqual(P.number_word(59), "fifty-nine")
        self.assertEqual(P.number_word(60), "sixty")
        self.assertTrue(re.search(P.render("<v> moments", 7, "word"), "Seven moments it dates"))
        self.assertTrue(re.search(P.render("<v> percent", 0.5869, "pct_word"), "Fifty-nine percent of payloads"))

    def test_times(self):
        t = "2026-07-10 11:51"
        self.assertEqual(P.FORMATS["hm_on_md"][0](t), "11:51 on July 10")
        self.assertEqual(P.FORMATS["md_at_hm"][0](t), "July 10 at 11:51")
        self.assertEqual(P.FORMATS["d_mon_hm"][0](t), "10 Jul 11:51")
        self.assertEqual(P.FORMATS["mon_d_hm"][0](t), "Jul 10 11:51")
        self.assertEqual(P.FORMATS["hm"][0](t), "11:51")

    def test_default_format(self):
        self.assertEqual(P.default_format(24), "int")
        self.assertEqual(P.default_format(0.5), "f2")
        self.assertEqual(P.default_format("R0005366"), "str")


class NormalizeTests(unittest.TestCase):
    def test_html_tags_entities_and_gaps(self):
        t = P.normalize("<style>p{x:1}</style><p>finds <b>24</b> messages, 66%&ndash;<b>79%</b>&ndash;88% (<span class=id>R1</span>).</p><script>var a=99</script>", True)
        self.assertEqual(t, "finds 24 messages, 66%–79%–88% (R1).")

    def test_markdown_emphasis_and_links(self):
        t = P.normalize("the release shows **24 messages, 6 of them** ([docs](docs/validation.md#x)) and `code`", False)
        self.assertEqual(t, "the release shows 24 messages, 6 of them ([docs]) and code")


class PlaceTests(unittest.TestCase):
    TEXT = "It finds 24 messages, 6 of them between 8 named tokens. The first came at 11:51 on July 10 (90% to come)."

    def test_ok(self):
        status, printed, span = P.check_place(self.TEXT, r"It finds <v> messages", 24, "int")
        self.assertEqual((status, printed), ("ok", "24"))
        self.assertEqual(self.TEXT[span[0]:span[1]], "24")

    def test_disagrees_reports_what_is_printed(self):
        status, printed, _ = P.check_place(self.TEXT, r"It finds <v> messages", 23, "int")
        self.assertEqual((status, printed), ("disagrees", "24"))
        status, printed, _ = P.check_place(self.TEXT, r"came at <v> \(", "2026-07-12 07:47", "hm_on_md")
        self.assertEqual((status, printed), ("disagrees", "11:51 on July 10"))

    def test_anchor_and_file_missing(self):
        self.assertEqual(P.check_place(self.TEXT, r"It reports <v> messages", 24, "int")[0], "anchor_missing")
        self.assertEqual(P.check_place(None, r"It finds <v> messages", 24, "int")[0], "file_missing")


class ScanTests(unittest.TestCase):
    def test_numbers_near_key_words(self):
        text = "In 2026 the tool found 24 messages and 8 named tokens in R0005366; 90% to come, 3 of them. See page 12."
        nums = [n for _, _, n, _ in P.scan_numbers(text)]
        self.assertEqual(nums, ["24", "8", "90%"])

    def test_covered_spans_are_left_out(self):
        text = "It finds 24 messages, 6 of them between 8 named tokens."
        _, _, span = P.check_place(text, r"It finds <v> messages", 24, "int")
        rel = P.PUBLISHED[0]
        un = P.unregistered({rel: [span]}, {rel: text})
        self.assertEqual([u["number"] for u in un], ["8"])
        self.assertEqual(len(P.unregistered({}, {rel: text})), 2)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.claims = P.registry()

    def test_ids_unique_and_sources_known(self):
        ids = [c.id for c in self.claims]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.claims:
            self.assertIn(c.source, P.DATASETS, c.id)
            self.assertTrue(c.statement and c.how, c.id)

    def test_every_place_is_well_formed(self):
        dummy = {"int": 5, "pct": 0.5, "pct1": 0.5, "f0": 1.0, "f1": 1.0, "f2": 1.0, "f3": 1.0, "word": 5, "pct_word": 0.5, "str": "x",
                 "iso": "2026-07-10 11:51", "hm": "2026-07-10 11:51", "hm_on_md": "2026-07-10 11:51", "md_at_hm": "2026-07-10 11:51",
                 "d_mon_hm": "2026-07-10 11:51", "mon_d_hm": "2026-07-10 11:51"}
        self.assertEqual(set(dummy), set(P.FORMATS))
        for c in self.claims:
            for rel, template, fmt in c.places:
                self.assertIn(rel, P.PUBLISHED, c.id)
                self.assertEqual(template.count("<v>"), 1, f"{c.id}: {template}")
                fmt = fmt or c.fmt or "int"
                self.assertIn(fmt, P.FORMATS, c.id)
                re.compile(P.render(template, dummy[fmt], fmt))
                re.compile(P.loose(template, fmt))

    def test_headline_numbers_are_registered(self):
        ids = {c.id for c in self.claims}
        for k in ("release.records", "release.deliveries", "release.named_deliveries", "release.named_pairs", "release.named_message_tokens",
                  "release.named_tokens", "release.agents", "release.agent_messages", "release.first_message_time", "release.first_message_harm_share",
                  "release.agent_first_message_time", "release.agent_first_message_share", "audit.links", "audit.true_links",
                  "release.attributed_share", "release.board_folders", "release.board_folders_written", "release.board_folders_read",
                  "release.board_folders_both", "release.insider_findings", "release.insider_recovered", "release.insider_partly",
                  "release.insider_invisible"):
            self.assertIn(k, ids)

    def test_every_computed_part_belongs_to_a_dataset(self):
        parts = [p for ps in P.PARTS.values() for p in ps]
        self.assertEqual(sorted(parts), sorted(P.PART_FUNCS))
        self.assertEqual(set(P.PARTS), set(P.DATASETS))


class LightPartTests(unittest.TestCase):
    """The parts that need no dataset compute from tracked files."""

    def test_audit_counts_add_up(self):
        m = P.part_audit()
        self.assertEqual(m["audit.links"], m["audit.true_links"] + m["audit.read_then_post"] + m["audit.read_is_write"] +
                         m["audit.downloads"] + m["audit.different_repo"] + m["audit.unclear"])
        self.assertGreater(m["audit.first_count"], 0)

    def test_samples(self):
        m = P.part_samples()
        self.assertGreater(m["samples.demo_records"], 100)
        self.assertGreater(m["samples.benign_records"], 100)


class DiffTests(unittest.TestCase):
    def test_walk_diff(self):
        saved = {"a": 1, "b": {"c": [1, 2], "d": 0.5}, "rows": [{"k": 1}, {"k": 2}], "extra": "ignored"}
        now = {"a": 1, "b": {"c": [1, 3], "d": 0.5}, "rows": [{"k": 1}, {"k": 5}]}
        self.assertEqual(P._walk_diff(saved, now), [("b.c[1]", 2, 3), ("rows[1].k", 2, 5)])
        self.assertEqual(P._walk_diff(saved, {"a": 1}), [])

    def test_block_diff(self):
        d = tempfile.mkdtemp(prefix="st-prov-")
        try:
            os.makedirs(os.path.join(d, "docs"))
            with open(os.path.join(d, "out.md"), "w") as f:
                f.write("Generated 2026-01-02 by x\n\n| a | 1 |\n| b | 2 |\n")
            with open(os.path.join(d, "docs", "page.md"), "w") as f:
                f.write("# T\n\n## Results\n\nGenerated 2026-01-01 by x\n\n| a | 1 |\n| b | 2 |\n\n## Next\n\ntext\n")
            c = P.Claim("x.block", "s", "h")
            c.block = ("docs/page.md", "## Results", "## Next", "out.md")
            self.assertEqual(P.block_diff(c, d), ("ok", []))
            with open(os.path.join(d, "out.md"), "a") as f:
                f.write("| c | 3 |\n")
            status, diff = P.block_diff(c, d)
            self.assertEqual((status, diff), ("disagrees", ["+| c | 3 |"]))
            c.block = ("docs/page.md", "## Missing", "## Next", "out.md")
            self.assertEqual(P.block_diff(c, d)[0], "anchor_missing")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class VerifyTests(unittest.TestCase):
    """verify against a small manifest and a temporary tree (texts and claims files only; nothing is recomputed)."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="st-prov-")
        os.makedirs(os.path.join(self.d, "agenttrace", "claims"))
        self.doc = os.path.join(self.d, "README.md")
        with open(self.doc, "w") as f:
            f.write("The release shows **24 messages**, 6 of them between named tokens.\n")
        for name in P.CLAIM_FILES_REQUIRED:
            with open(os.path.join(self.d, "agenttrace", "claims", name), "w") as f:
                f.write("{}")
        with open(os.path.join(self.d, "agenttrace", "messages.py"), "w") as f:
            f.write("# rule\n")
        cdir = os.path.join(self.d, "agenttrace", "claims")
        tpl, tpl2 = r"shows <v> messages", r"messages, <v> of them"
        self.manifest = {
            "claim_files": {n: P.sha256_file(os.path.join(cdir, n)) for n in P.CLAIM_FILES_REQUIRED},
            "rule_files": {"agenttrace/messages.py": P.sha256_file(os.path.join(self.d, "agenttrace", "messages.py"))},
            "datasets": {},
            "claims": [
                {"id": "t.messages", "kind": "number", "value": 24, "dataset": "t", "computed_by": "x", "statement": "s",
                 "places": [{"file": "README.md", "anchor": tpl, "format": "int", "status": "ok", "must_match": P.render(tpl, 24, "int"), "printed": "24"},
                            {"file": "docs/absent.md", "anchor": tpl, "format": "int", "status": "ok", "must_match": P.render(tpl, 24, "int"), "printed": "24"}]},
                {"id": "t.named", "kind": "number", "value": 5, "dataset": "t", "computed_by": "x", "statement": "s",
                 "places": [{"file": "README.md", "anchor": tpl2, "format": "int", "status": "disagrees", "must_match": P.render(tpl2, 5, "int"), "printed": "6"}]},
            ],
        }

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_verify(self):
        return P.verify_manifest(self.manifest, root=self.d, log=lambda *_: None)

    def test_clean_tree_has_no_drift_and_keeps_the_known_disagreement(self):
        res = self.run_verify()
        self.assertEqual(res["drift"], [])
        self.assertEqual([(x["what"], x["expected"], x["found"]) for x in res["disagreements"]], [("t.named", "5", "6")])
        self.assertIn("docs/absent.md is not on this machine: 1 place(s) that print a number there were not checked", res["skipped"])
        self.assertTrue(any("not re-derived" in s for s in res["skipped"]))

    def test_changed_text_is_drift(self):
        with open(self.doc, "w") as f:
            f.write("The release shows **23 messages**, 6 of them between named tokens.\n")
        res = self.run_verify()
        self.assertEqual([(x["kind"], x["what"], x["expected"], x["found"]) for x in res["drift"]], [("printed number", "t.messages", "24", "23")])

    def test_reworded_text_is_drift(self):
        with open(self.doc, "w") as f:
            f.write("There are 24 messages, 6 of them between named tokens.\n")
        res = self.run_verify()
        self.assertEqual([(x["kind"], x["what"]) for x in res["drift"]], [("anchor not found", "t.messages")])

    def test_known_disagreement_that_changes_is_drift(self):
        with open(self.doc, "w") as f:
            f.write("The release shows **24 messages**, 7 of them between named tokens.\n")
        res = self.run_verify()
        self.assertEqual([(x["what"], x["found"]) for x in res["drift"]], [("t.named", "7")])
        self.assertEqual(res["disagreements"], [])

    def test_fixed_text_clears_the_disagreement(self):
        with open(self.doc, "w") as f:
            f.write("The release shows **24 messages**, 5 of them between named tokens.\n")
        res = self.run_verify()
        self.assertEqual((res["drift"], res["disagreements"]), ([], []))

    def test_changed_claims_file_is_drift(self):
        with open(os.path.join(self.d, "agenttrace", "claims", "audited_links.json"), "w") as f:
            f.write('{"links": []}')
        res = self.run_verify()
        self.assertEqual([(x["kind"], x["what"]) for x in res["drift"]], [("claims file", "audited_links.json")])

    def test_missing_required_claims_file_record_is_drift(self):
        del self.manifest["claim_files"]["frozen_signs.json"]
        res = self.run_verify()
        self.assertIn(("claims file", "frozen_signs.json"), [(x["kind"], x["what"]) for x in res["drift"]])

    def test_changed_rule_file_is_drift_when_values_cannot_be_rederived(self):
        with open(os.path.join(self.d, "agenttrace", "messages.py"), "a") as f:
            f.write("# changed\n")
        res = self.run_verify()
        self.assertEqual([(x["kind"], x["what"]) for x in res["drift"]], [("rule file", "agenttrace/messages.py")])

    def test_print_verify_exit_state(self):
        import io
        res = self.run_verify()
        buf = io.StringIO()
        self.assertTrue(P.print_verify(res, self.manifest, 0.1, out=buf))
        self.assertIn("VERIFY FAILED: 0 drift, 1 known disagreement", buf.getvalue())
        self.assertFalse(P.print_verify(res, self.manifest, 0.1, out=io.StringIO(), allow_known=True))


class ManifestFileTests(unittest.TestCase):
    """The committed manifest, when there is one, has the shape verify relies on."""

    def test_manifest_shape(self):
        if not os.path.exists(P.MANIFEST):
            self.skipTest("no manifest built yet")
        m = P.load_manifest()
        self.assertEqual(m["manifest_version"], P.MANIFEST_VERSION)
        for f in P.CLAIM_FILES_REQUIRED:
            self.assertRegex(m["claim_files"][f], r"^[0-9a-f]{64}$")
        self.assertNotIn("provenance.json", m["claim_files"])
        ids = {c.id for c in P.registry()}
        self.assertEqual({e["id"] for e in m["claims"]}, ids, "the manifest and the registry list different numbers: run `provenance build`")
        for e in m["claims"]:
            for p in e["places"]:
                self.assertIn(p["status"], ("ok", "disagrees", "anchor_missing", "file_missing", "not_computed", "source_missing"))
        for ds, d in m["datasets"].items():
            for f, rec in d["inputs"].items():
                self.assertRegex(rec["sha256"], r"^[0-9a-f]{64}$")
                self.assertFalse(os.path.isabs(f))
        text = json.dumps(m)
        self.assertNotIn(os.path.expanduser("~"), text, "the manifest must not hold a path on this machine")


class ReproHelperTests(unittest.TestCase):
    def test_compare_hashes(self):
        self.assertEqual(repro.compare_hashes({"a": "1", "b": "2"}, {"a": "1", "b": "2"}), [])
        self.assertEqual(repro.compare_hashes({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "4"}), ["b", "c"])

    def test_parse_check(self):
        out = ("... unit tests\nPASS  unit tests (16 s): Ran 3 tests — OK\n... smoke (API only)\nFAIL  smoke (API only) (6 s): 1/2 cells pass\n"
               "      demo [x] y: bad\n\nPASS  unit tests\nFAIL  smoke (API only)\nCHECK FAILED: 1/2 stages (2026-11-14 20:37 UTC)\n")
        self.assertEqual(repro.parse_check(out), [("unit tests", True), ("smoke (API only)", False)])
        self.assertEqual(repro.parse_check("no summary here"), [])

    def test_clean_env_is_isolated(self):
        env = repro.clean_env("/tmp/x", seed="5")
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual((env["SWARM_TRACER_HOME"], env["PYTHONHASHSEED"], env["SWARM_TRACER_NO_CACHE"]), ("/tmp/x", "5", "1"))


if __name__ == "__main__":
    unittest.main()

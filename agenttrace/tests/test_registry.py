"""Tests for the dataset registry and the page built from it.

Run from the project root:
    python3 -m unittest agenttrace.tests.test_registry -v
"""
import copy
import os
import re
import unittest

from agenttrace.tools import registry

ROOT = registry.ROOT


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = registry.load()
        cls.by_id = {e["id"]: e for e in cls.reg["entries"]}

    def test_registry_is_valid(self):
        self.assertEqual(registry.validate(self.reg), [])

    def test_the_three_named_sources_are_present(self):
        for eid in ("swarm_traces", "collusion_wiki", "ai_village"):
            self.assertIn(eid, self.by_id)
        self.assertEqual(self.by_id["swarm_traces"]["status"], "analysed")
        self.assertEqual(self.by_id["collusion_wiki"]["status"], "analysed")
        self.assertGreaterEqual(sum(1 for e in self.reg["entries"] if e["status"] == "candidate"), 5)

    def test_no_licence_never_reads_as_open(self):
        for e in self.reg["entries"]:
            if e["terms"]["licence"] == registry.NO_LICENCE:
                self.assertEqual(e["terms"]["badge"], "ask first", e["id"])
                self.assertIn(e["publish"], ("aggregates", "nothing"), e["id"])

    def test_analysed_counts_match_the_saved_evaluation(self):
        import json
        for eid, folder in (("swarm_traces", "evaluation"), ("collusion_wiki", "evaluation-wiki")):
            p = os.path.join(ROOT, "reports", folder, "summary.json")
            if not os.path.exists(p):
                self.skipTest("reports/ not on this machine")
            with open(p, encoding="utf-8") as f:
                s = json.load(f)
            loc = self.by_id[eid]["local"]
            self.assertEqual(loc["records"], s["records"], eid)
            self.assertEqual(loc["actors"], s["identities_total"], eid)
            self.assertEqual(loc["timed_records"], s["timed"], eid)
            self.assertEqual(loc["messages"], s["flow"]["deliveries"], eid + ": message count changed; update datasets.json")

    def test_gallery_blocks_stay_inside_the_terms(self):
        """What the investigations may show of a record is in the registry, and may not go past the reuse terms."""
        with_gallery = {eid: e["gallery"] for eid, e in self.by_id.items() if e.get("gallery")}
        self.assertEqual(with_gallery["swarm_traces"]["records"], "viewer", "no stated licence: no record text")
        self.assertIn("{id}", with_gallery["swarm_traces"]["record_url"])
        self.assertEqual(with_gallery["moltbook_observatory"]["records"], "none", "numbers only: no post, no agent name")
        for eid, g in with_gallery.items():
            if g["records"] == "excerpts":
                self.assertEqual((self.by_id[eid]["terms"]["excerpts"], self.by_id[eid]["publish"]), ("yes", "excerpts"), eid)
                self.assertIn("reports/external/", g["report"], eid)

        def broken(eid, change):
            reg = copy.deepcopy(self.reg)
            change(next(e for e in reg["entries"] if e["id"] == eid))
            return [x for x in registry.validate(reg) if "gallery" in x]
        self.assertTrue(broken("swarm_traces", lambda e: e["gallery"].update(records="excerpts")))     # excerpts with no licence
        self.assertTrue(broken("swarm_traces", lambda e: e["gallery"].pop("record_url")))              # a viewer rule with no viewer
        self.assertTrue(broken("who_and_when", lambda e: e["gallery"].update(attribution="")))         # excerpts with no credit line
        self.assertTrue(broken("who_and_when", lambda e: e["gallery"].update(report="reports/other.json")))
        self.assertTrue(broken("mast_data", lambda e: e["gallery"].update(records="everything")))
        self.assertTrue(broken("ai_village", lambda e: e.update(gallery=dict(self.by_id["mast_data"]["gallery"]))))   # a candidate

    def test_validator_catches_mistakes(self):
        def broken(change):
            reg = copy.deepcopy(self.reg)
            change(reg["entries"][0])
            return registry.validate(reg)
        self.assertTrue(broken(lambda e: e["terms"].update(badge="open")))            # open without a licence
        self.assertTrue(broken(lambda e: e.update(publish="excerpts")))               # publishing beyond the terms
        self.assertTrue(broken(lambda e: e["terms"].update(quote="word " * 15)))      # quote too long
        self.assertTrue(broken(lambda e: e.update(can=e["can"][:2])))                 # too few lines
        self.assertTrue(broken(lambda e: e.update(local=None)))                       # analysed without counts
        self.assertTrue(broken(lambda e: e.update(source_url="http://example.org")))  # not https
        self.assertTrue(broken(lambda e: e["fields"].update(timestamps="maybe")))
        reg = copy.deepcopy(self.reg)
        reg["entries"].append(copy.deepcopy(reg["entries"][0]))
        self.assertTrue(any("duplicate" in x for x in registry.validate(reg)))

    def test_page_has_a_card_per_dataset_and_no_scripts(self):
        page = registry.render(self.reg)
        for e in self.reg["entries"]:
            self.assertIn(f'<article class="ds" id="{e["id"]}">', page)
            self.assertIn(registry.esc(e["citation"]), page)
            for line in e["can"] + e["cannot"]:
                self.assertIn(registry.esc(line), page)
        low = page.lower()
        self.assertNotIn("<script", low)
        self.assertNotIn("<style", low)
        self.assertNotIn("style=", low)
        self.assertIsNone(re.search(r"\son\w+=", low))
        self.assertNotIn("javascript:", low)
        self.assertIn('href="datasets.css"', page)

    def test_page_escapes_registry_text(self):
        reg = copy.deepcopy(self.reg)
        reg["entries"][0]["title"] = "<script>alert(1)</script>"
        reg["entries"][0]["links"][0]["url"] = "https://example.org/'onmouseover='x"
        page = registry.render(reg)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("'onmouseover='x", page)

    @unittest.skipUnless(os.path.isdir(os.path.join(ROOT, "docs")), "needs the source checkout (docs/ is not in an installed copy)")
    def test_built_page_and_notes_are_current(self):
        with open(registry.PAGE, encoding="utf-8") as f:
            self.assertEqual(f.read(), registry.render(self.reg), "run python3 -m agenttrace.tools.registry")
        self.assertTrue(os.path.exists(os.path.join(ROOT, "docs", "datasets.css")))
        with open(os.path.join(ROOT, "docs", "dataset-licensing.md"), encoding="utf-8") as f:
            notes = f.read()
        for eid in self.by_id:
            self.assertIn(f"`{eid}`", notes, f"{eid} missing from docs/dataset-licensing.md")


if __name__ == "__main__":
    unittest.main()

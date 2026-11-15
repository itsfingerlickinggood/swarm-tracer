"""Tests for the second-labeller kit (agenttrace/tools/labelkit.py): the agreement maths on known cases, the blind
sheet (no label or reason of the first reader), and the scoring of answers. No dataset is needed."""
import csv
import json
import os
import shutil
import tempfile
import unittest

from agenttrace import benchmark
from agenttrace.tools import labelkit as L


def table(tt, tf, ft, ff):
    """Two raters' yes/no lists from a 2x2 table: tt both yes, tf first yes second no, ft first no second yes, ff both no."""
    a = ["y"] * (tt + tf) + ["n"] * (ft + ff)
    b = ["y"] * tt + ["n"] * tf + ["y"] * ft + ["n"] * ff
    return a, b


class KappaTests(unittest.TestCase):
    def test_perfect_agreement(self):
        a = ["true", "false", "false", "undecidable", "true"]
        self.assertAlmostEqual(L.cohen_kappa(a, list(a)), 1.0)
        self.assertEqual(L.raw_agreement(a, list(a)), 1.0)

    def test_textbook_two_by_two(self):
        # 20 both yes, 5 yes/no, 10 no/yes, 15 both no: po = 0.70, pe = 0.5*0.6 + 0.5*0.4 = 0.50, kappa = 0.40
        a, b = table(20, 5, 10, 15)
        self.assertAlmostEqual(L.raw_agreement(a, b), 0.70)
        self.assertAlmostEqual(L.cohen_kappa(a, b), 0.40)

    def test_second_known_case(self):
        # 45 both yes, 15 yes/no, 25 no/yes, 15 both no: po = 0.60, pe = 0.6*0.7 + 0.4*0.3 = 0.54, kappa = 0.06/0.46
        a, b = table(45, 15, 25, 15)
        self.assertAlmostEqual(L.cohen_kappa(a, b), 0.06 / 0.46)

    def test_chance_level_is_zero(self):
        a, b = table(25, 25, 25, 25)
        self.assertAlmostEqual(L.cohen_kappa(a, b), 0.0)

    def test_total_disagreement_is_minus_one(self):
        a, b = table(0, 10, 10, 0)
        self.assertAlmostEqual(L.cohen_kappa(a, b), -1.0)

    def test_three_categories(self):
        # po = 7/10; both raters use A, B, C with shares 0.4, 0.3, 0.3: pe = 0.34; kappa = 0.36/0.66
        a = ["A"] * 4 + ["B"] * 3 + ["C"] * 3
        b = ["A", "A", "A", "B", "B", "B", "C", "C", "C", "A"]
        self.assertAlmostEqual(L.raw_agreement(a, b), 0.7)
        self.assertAlmostEqual(L.cohen_kappa(a, b), 0.36 / 0.66)

    def test_high_agreement_low_kappa_when_one_answer_dominates(self):
        # 94 both no, 3 + 3 split, 0 both yes: 94% raw agreement, kappa below zero
        a, b = table(0, 3, 3, 94)
        self.assertAlmostEqual(L.raw_agreement(a, b), 0.94)
        self.assertLess(L.cohen_kappa(a, b), 0)

    def test_undefined_cases(self):
        self.assertIsNone(L.cohen_kappa([], []))
        self.assertIsNone(L.cohen_kappa(["n"] * 5, ["n"] * 5))
        self.assertIsNone(L.raw_agreement([], []))
        with self.assertRaises(ValueError):
            L.cohen_kappa(["y"], ["y", "n"])

    def test_matches_the_benchmark_implementation_on_booleans(self):
        a, b = table(13, 5, 2, 211)
        self.assertAlmostEqual(L.cohen_kappa(a, b), benchmark.kappa([x == "y" for x in a], [x == "y" for x in b]), places=4)


class BootstrapTests(unittest.TestCase):
    def test_range_holds_the_estimate_and_is_repeatable(self):
        a, b = table(20, 5, 10, 15)
        lo, hi, used = L.bootstrap_kappa(a, b, draws=500, seed=3)
        self.assertLessEqual(lo, 0.40)
        self.assertGreaterEqual(hi, 0.40)
        self.assertLess(lo, hi)
        self.assertEqual(used, 500)
        self.assertEqual(L.bootstrap_kappa(a, b, draws=500, seed=3), (lo, hi, used))
        self.assertTrue(-1 <= lo <= 1 and -1 <= hi <= 1)

    def test_more_items_give_a_narrower_range(self):
        a, b = table(20, 5, 10, 15)
        lo1, hi1, _ = L.bootstrap_kappa(a, b, draws=400, seed=1)
        lo2, hi2, _ = L.bootstrap_kappa(a * 10, b * 10, draws=400, seed=1)
        self.assertLess(hi2 - lo2, hi1 - lo1)

    def test_perfect_agreement(self):
        a, b = table(10, 0, 0, 10)
        lo, hi, _ = L.bootstrap_kappa(a, b, draws=200)
        self.assertEqual((lo, hi), (1.0, 1.0))

    def test_undefined(self):
        self.assertIsNone(L.bootstrap_kappa(["n"] * 5, ["n"] * 5))
        self.assertIsNone(L.bootstrap_kappa(["n"], ["n"]))


def audit_of(n=6):
    labels = ["true_message", "false_write", "read_not_a_read", "unclear", "false_write", "true_message", "different_repo", "false_write"]
    links = []
    for i in range(n):
        links.append({"write_id": f"W{i}", "read_id": f"R{i}", "from": "a", "to": "b", "channel_v110": f"hf_dataset:OLD{i}",
                      "channel_now": f"hf_dataset:[HF REPO {i}]", "reported_v110": True, "reported_now": i % 2 == 0, "label": labels[i % len(labels)],
                      "reason": f"FIRST-READER-REASON-{i} because of the verb", "also": [], "write_snippet": f"fetch('x/[HF REPO {i}]/commit'",
                      "read_snippet": f"fetch('x/[HF REPO {i}]/resolve'", "latency_h": 1.5, "endpoint_kind": "named_named"})
    return {"made": "2026-11-13", "labels": {}, "links": links}


def texts_of(audit):
    out = {}
    for r in audit["links"]:
        key = L.place_key(r["channel_now"])
        out[r["write_id"]] = "A" * 900 + f" fetch('https://h/{key}/commit',{{method:'POST'}}) " + "B" * 900
        out[r["read_id"]] = f"fetch('https://h/{key}/resolve/main/f') </script><script>alert(1)</script> tail"
    return out


class SheetTests(unittest.TestCase):
    def test_first_reader_answer(self):
        self.assertEqual(L.first_reader_answer("true_message"), "true")
        self.assertEqual(L.first_reader_answer("unclear"), "undecidable")
        for k in ("false_write", "false_write_lfs_or_urlopen", "different_repo", "comment_only", "read_not_a_read"):
            self.assertEqual(L.first_reader_answer(k), "false")

    def test_shuffle_is_fixed_and_complete(self):
        links = audit_of(8)["links"]
        a, b = L.shuffled(links, 5), L.shuffled(list(reversed(links)), 5)
        self.assertEqual([(i, r["write_id"]) for i, r in a], [(i, r["write_id"]) for i, r in b])
        self.assertEqual(sorted(r["write_id"] for _, r in a), sorted(r["write_id"] for r in links))
        self.assertEqual([i for i, _ in a], [f"L{k:03d}" for k in range(1, 9)])
        self.assertNotEqual([r["write_id"] for _, r in a], sorted(r["write_id"] for r in links))
        self.assertNotEqual([r["write_id"] for _, r in a], [r["write_id"] for _, r in L.shuffled(links, 6)])

    def test_excerpt_marks_the_place(self):
        text = "x" * 2000 + "PLACE" + "y" * 2000
        ex = L.excerpt(text, "PLACE", window=100)
        self.assertEqual(ex["text"][ex["mark"][0]:ex["mark"][1]], "PLACE")
        self.assertEqual((len(ex["text"]), ex["start"], ex["cut_before"], ex["cut_after"]), (205, 1900, True, True))

    def test_excerpt_falls_back_to_the_hint_then_the_start(self):
        text = "a" * 1000 + "near the call" + "b" * 1000
        ex = L.excerpt(text, "NOT THERE", hint="near the call", window=50)
        self.assertIsNone(ex["mark"])
        self.assertIn("near the call", ex["text"])
        ex = L.excerpt(text, "NOT THERE", hint="nor this", window=50)
        self.assertEqual((ex["start"], len(ex["text"]), ex["cut_after"]), (0, 100, True))
        self.assertEqual(L.excerpt("", "X")["text"], "")

    def test_sheet_is_blind(self):
        audit = audit_of(8)
        items = L.build_items(audit, texts_of(audit), seed=1)
        self.assertEqual(len(items), 8)
        self.assertEqual(L.leaks(items, audit), [])
        page = L.render_page({"seed": 1, "links": 8, "audit_sha256": "0" * 64, "note": ""}, items)
        blob = page + json.dumps(items)
        for r in audit["links"]:
            self.assertNotIn(r["reason"], blob)
        for word in ("read_not_a_read", "false_write", "true_message", "different_repo", "reported_v110", "reported_now", "OLD0"):
            self.assertNotIn(word, blob)
        for it in items:
            self.assertEqual(set(it) & set(L.HIDDEN_FIELDS), set())

    def test_leak_check_catches_a_planted_reason(self):
        audit = audit_of(3)
        items = L.build_items(audit, texts_of(audit), seed=1)
        items[0]["label"] = "true_message"
        items[1]["place"] = audit["links"][0]["reason"]
        bad = L.leaks(items, audit)
        self.assertTrue(any("field label" in b for b in bad))
        self.assertTrue(any("reason of W0->R0" in b for b in bad))

    def test_record_text_cannot_break_out_of_the_page(self):
        audit = audit_of(2)
        items = L.build_items(audit, texts_of(audit), seed=1)
        page = L.render_page({"seed": 1, "links": 2, "audit_sha256": "0" * 64, "note": ""}, items)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertEqual(page.count("</script>"), 2)           # the data block and the page's own script
        start = page.index('<script id="kit" type="application/json">') + len('<script id="kit" type="application/json">')
        data = json.loads(page[start:page.index("</script>", start)])
        self.assertEqual(len(data["items"]), 2)
        self.assertIn("</script><script>alert(1)</script>", data["items"][0]["read"]["text"] + data["items"][1]["read"]["text"])
        self.assertNotIn("innerHTML", page)

    def test_missing_record_is_marked(self):
        audit = audit_of(1)
        items = L.build_items(audit, {"W0": "some text [HF REPO 0]"}, seed=1)
        self.assertTrue(items[0]["read"]["missing"])
        self.assertFalse(items[0]["write"].get("missing", False))

    def test_real_audit_file_builds_a_blind_sheet(self):
        audit = L.load_audit()
        texts = {}
        for r in audit["links"]:
            texts.setdefault(r["write_id"], r["write_snippet"])
            texts.setdefault(r["read_id"], r["read_snippet"])
        items = L.build_items(audit, texts)
        self.assertEqual(len(items), len(audit["links"]))
        self.assertEqual(L.leaks(items, audit), [])
        self.assertEqual(len({it["item"] for it in items}), len(items))


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.audit = audit_of(8)        # first reader: true, false, false, undecidable, false, true, false, false
        self.first = [L.first_reader_answer(r["label"]) for r in self.audit["links"]]

    def answers(self, vals):
        return {(f"W{i}", f"R{i}"): v for i, v in enumerate(vals)}

    def test_full_agreement(self):
        res = L.score(self.audit, self.answers(self.first), draws=200)
        self.assertEqual((res["answered"], res["unanswered"], res["disagreements"]), (8, 0, []))
        self.assertEqual(res["three_way"]["raw_agreement"], 1.0)
        self.assertEqual(res["three_way"]["kappa"], 1.0)
        self.assertEqual(res["decided_by_both"]["n"], 7)

    def test_disagreements_unanswered_and_bad_answers(self):
        vals = list(self.first)
        vals[1] = "true"            # first reader: false
        vals[3] = "false"           # first reader: undecidable
        vals[6] = None              # not answered
        vals[7] = "maybe"           # not one of the three
        ans = self.answers(vals)
        ans[("W99", "R99")] = "true"
        res = L.score(self.audit, ans, notes={("W1", "R1"): "the POST goes to this place"}, draws=200)
        self.assertEqual((res["answered"], res["unanswered"]), (6, 2))
        self.assertEqual(res["unknown_links"], [["W99", "R99"]])
        self.assertEqual(res["invalid_answers"], [["W7", "R7", "maybe"]])
        self.assertEqual(res["three_way"]["agree"], 4)
        self.assertAlmostEqual(res["three_way"]["raw_agreement"], round(4 / 6, 4))
        d = {(x["write_id"], x["first_reader"], x["second_labeller"]) for x in res["disagreements"]}
        self.assertEqual(d, {("W1", "false", "true"), ("W3", "undecidable", "false")})
        w1 = next(x for x in res["disagreements"] if x["write_id"] == "W1")
        self.assertEqual(w1["second_labeller_note"], "the POST goes to this place")
        self.assertIn("FIRST-READER-REASON-1", w1["first_reader_reason"])
        self.assertEqual(res["three_way"]["confusion"]["false"]["true"], 1)
        self.assertEqual(res["undecidable"], {"first_reader": 1, "second_labeller": 0, "both": 0})
        self.assertEqual(res["decided_by_both"]["n"], 5)
        self.assertEqual(res["decided_by_both"]["agree"], 4)
        text = L.report_text(res, "second")
        self.assertIn("6 of 8 links answered, 2 unanswered", text)
        self.assertIn("2 disagreement(s):", text)

    def test_kappa_matches_the_formula(self):
        vals = ["true", "true", "false", "undecidable", "false", "false", "false", "false"]
        res = L.score(self.audit, self.answers(vals), draws=100)
        self.assertAlmostEqual(res["three_way"]["kappa"], round(L.cohen_kappa(self.first, vals), 4))
        lo, hi = res["three_way"]["kappa_95"]
        self.assertLessEqual(lo, hi)

    def test_reads_json_and_csv_answers(self):
        d = tempfile.mkdtemp(prefix="st-labelkit-")
        try:
            pj, pc = os.path.join(d, "a.json"), os.path.join(d, "a.csv")
            with open(pj, "w") as f:
                json.dump({"kit": {"seed": 1}, "labeller": "B", "answers": [{"item": "L001", "write_id": "W0", "read_id": "R0", "answer": "True", "note": "n"},
                                                                          {"item": "L002", "write_id": "W1", "read_id": "R1", "answer": None, "note": ""}]}, f)
            who, ans, notes, kit = L.read_answers(pj)
            self.assertEqual((who, ans, notes[("W0", "R0")], kit), ("B", {("W0", "R0"): "true", ("W1", "R1"): None}, "n", {"seed": 1}))
            items = L.build_items(self.audit, texts_of(self.audit), seed=1)
            L.write_csv(pc, items)
            with open(pc, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 8)
            self.assertEqual({r["answer"] for r in rows}, {""})
            self.assertNotIn("label", rows[0])
            rows[0]["answer"] = "FALSE"
            with open(pc, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            who, ans, notes, kit = L.read_answers(pc)
            self.assertEqual(sum(1 for v in ans.values() if v), 1)
            self.assertEqual(ans[(rows[0]["write_id"], rows[0]["read_id"])], "false")
            self.assertEqual(L.score(self.audit, ans)["answered"], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_nothing_is_invented_for_missing_answers(self):
        res = L.score(self.audit, {})
        self.assertEqual((res["answered"], res["unanswered"], res["three_way"]["kappa"], res["disagreements"]), (0, 8, None, []))


if __name__ == "__main__":
    unittest.main()

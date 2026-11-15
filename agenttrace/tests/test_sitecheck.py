"""Tests for the site checks: the scanners are run on planted fakes in a temporary docs folder.

The fake secrets are put together at run time, so this file holds nothing a secret scanner would stop.
"""
import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from agenttrace.tools import build_investigations as B
from agenttrace.tools import sitecheck as S

A40 = "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0hL3nR6uX9a"
FAKES = {
    "hf-token": "hf_" + A40[:34],
    "openai-style-key": "sk-" + "proj-" + A40[:32],
    "aws-access-key": "AKIA" + "IOSFODNN7EXAMPLQ",
    "github-token": "ghp_" + A40[:36],
    "slack-token": "xoxb-" + "123456789012-" + A40[:20],
    "google-api-key": "AIza" + A40[:35],
    "jwt": "eyJ" + A40[:20] + ".eyJ" + A40[:30] + "." + A40[:25],
    "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "bearer-token": "Authorization: Bearer " + A40[:30],
    "basic-credentials": "Authorization: Basic " + "dXNlcjpwYXNzd29yZDEyMzQ1Ng==",
    "secret-assignment": '"password": "' + A40[:20] + '"',
    "url-with-password": "https://deploy:" + "s3cretpw@" + "git.example.com/x.git",
    "ip-address": "connect to 34.117.59.81 now",
    "ipv6-address": "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
    "internal-hostname": "curl http://artifactory.build.corp/x and db01.prod.internal",
    "local-path": "/Users/" + "someone/project/data.csv",
    "email": "write to jane.roe@" + "corp-mail.io today",
    "unredacted-hf-repo": "https://huggingface.co/datasets/" + "realowner/real-repo/resolve/main/x",
}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class SecretScannerTests(unittest.TestCase):
    def test_each_planted_fake_is_found(self):
        for rule, text in FAKES.items():
            found = {f.rule for f in S.scan_text("before " + text + " after", "x.md")}
            self.assertIn(rule, found, f"{rule} not found in {text!r}")

    def test_release_placeholders_are_not_findings(self):
        text = ("fetch('https://[SERVICE HOST 1]/https://huggingface.co/datasets/[HF REPO 30]/resolve/main/a',"
                "{headers:{Authorization:'Bearer [CREDENTIAL 169]','X-API-Key':\"[CREDENTIAL 1]\"}}) "
                "https://huggingface.co/api/datasets/[REDACTED:destination:001593] [PROXY 4 URL 11] cred 169 run:R0005427")
        self.assertEqual([str(f) for f in S.scan_text(text, "x.json")], [])

    def test_ordinary_docs_text_is_not_a_finding(self):
        text = ("Open http://127.0.0.1:8010 or http://localhost:8010. Version 2.0.0, Chrome/120.0.0.0, v1.2.3.4. "
                "pipx install git+https://github.com/itsfingerlickinggood/swarm-tracer@v2.0.0 "
                "placeholder=\"oc_sk_... or sk-...\" Authorization: Bearer <token> S.internal = x.local; a.svc(); "
                "mail user@example.com, 0.0.0.0, 192.0.2.7, sha256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
        self.assertEqual([str(f) for f in S.scan_text(text, "x.md")], [])

    def test_folder_scan_finds_fakes_in_any_text_file_and_decodes_entities(self):
        d = tempfile.mkdtemp()
        try:
            write(os.path.join(d, "a.md"), "token " + FAKES["hf-token"])
            write(os.path.join(d, "sub", "b.json"), json.dumps({"k": FAKES["github-token"]}))
            write(os.path.join(d, "c.html"), "<p>jane.roe&#64;corp-mail.io</p>")
            write(os.path.join(d, "demo", "data", "x-0.json"), json.dumps({"p": FAKES["local-path"]}))
            with open(os.path.join(d, "pic.png"), "wb") as f:
                f.write(b"\x89PNG" + FAKES["hf-token"].encode())
            found, skipped = S.scan_redaction(d)
            got = {(f.rule, f.path.replace(os.sep, "/")) for f in found}
            self.assertIn(("hf-token", "a.md"), got)
            self.assertIn(("github-token", "sub/b.json"), got)
            self.assertIn(("email", "c.html"), got)
            self.assertIn(("local-path", "demo/data/x-0.json"), got)
            self.assertEqual(skipped, ["pic.png"])
        finally:
            shutil.rmtree(d)

    def test_allowlist_needs_a_reason_and_matches_by_rule_text_and_path(self):
        f = S.Finding("redaction", "email", "datasets.html", "a@b.org")
        self.assertTrue(S.allowed(f, [{"rule": "email", "match": "a@b.org", "path": "dataset*", "reason": "published"}]))
        self.assertTrue(S.allowed(f, [{"rule": "email", "match": "/@b\\.org$/", "reason": "published"}]))
        self.assertFalse(S.allowed(f, [{"rule": "email", "match": "a@b.org", "path": "demo/*", "reason": "x"}]))
        self.assertFalse(S.allowed(f, [{"rule": "ip-address", "match": "a@b.org", "reason": "x"}]))
        self.assertFalse(S.allowed(f, [{"rule": "email", "match": "other@b.org", "reason": "x"}]))
        d = tempfile.mkdtemp()
        try:
            write(os.path.join(d, "allow.json"), json.dumps([{"rule": "email", "match": "a@b.org"}]))
            with self.assertRaises(SystemExit):
                S.load_allow(os.path.join(d, "allow.json"))
        finally:
            shutil.rmtree(d)


def fake_site(d, snippets=False):
    """A docs folder with one investigation, built by the real builder from a hand-made bundle."""
    story = {"slug": "one", "title": "One", "dek": "A story with {n} messages.", "order": 1,
             "body": [{"h": "Start"}, {"p": "First [[c1|there are {n} messages, the first on {rec:R0000002.time}]] then."},
                      {"p": "Also [[c2|{rec:R0000002.actor} read what {rec:R0000001.actor} wrote]] " + "word " * 300}],
             "claims": {"c1": {"evidence": "Count {n}.", "figures": ["n"], "records": ["R0000002"]},
                        "c2": {"evidence": "The pair.", "records": [{"id": "R0000001", "note": "write"}, "R0000002"]}}}
    rec = lambda rid, actor, t: {"id": rid, "kind": "payload", "time": t, "time_estimated": True, "time_source": "estimated", "actor": actor,
                                 "actor_kind": "token", "agent": None, "intent": "hf_read", "text_length": 120,
                                 "judged": [{"op": "read", "place": "hf_dataset:[HF REPO 1]", "place_label": "Hugging Face dataset HF REPO 1", "in_text": True}],
                                 "messages": [], "viewer": B.CITATION["viewer"].format(id=rid)}
    bundle = {"schema": 1, "story": "one", "snippets": "on" if snippets else "off", "citation": dict(B.CITATION, text=B.CITATION_TEXT),
              "produced_by": {"tool": "Swarm Tracer", "version": "9.9.9", "pack": "p", "agent_rule": "estimate", "agent_rule_note": "", "dataset": "d.jsonl", "records": 3},
              "figures": {"n": {"value": 24, "text": "24", "as": "int", "from": "/api/state", "path": "summary.flow.deliveries", "label": "messages"}},
              "records": {"R0000001": rec("R0000001", "[CREDENTIAL 170]", "2026-07-10 11:18"), "R0000002": rec("R0000002", "[CREDENTIAL 169]", "2026-07-10 11:51")},
              "findings": {}}
    if snippets:
        bundle["records"]["R0000001"]["snippet"] = DATA[0]["text"][:100]
    inv = os.path.join(d, "investigations")
    write(os.path.join(inv, "stories", "one.json"), json.dumps(story))
    write(os.path.join(inv, "data", "one.json"), json.dumps(bundle, indent=1) + "\n")
    for name in ("story.css", "story.js"):
        write(os.path.join(inv, name), "/* x */")
    for name in ("validation.md", "limitations.md", "datasets.html", "getting-started.md"):
        write(os.path.join(d, name), "x")
    write(os.path.join(d, "index.html"), '<a href="investigations/">i</a><a href="demo/">d</a><img src="assets/a.png">')
    write(os.path.join(d, "assets", "a.png"), "")
    write(os.path.join(d, "demo", "index.html"), "<p>demo</p>")
    B.build(None, False, inv, False, True, log=lambda *a: None)
    return inv, story, bundle


DATA = [
    {"id": "R0000001", "kind": "payload", "time_utc": None, "text": "fetch('https://huggingface.co/api/datasets/[HF REPO 1]/commit/main',{method:'POST',headers:{Authorization:'Bearer [CREDENTIAL 170]'},body:'{\"key\":\"header\",\"value\":{\"summary\":\"upload notes for the others\"}}'})"},
    {"id": "R0000002", "kind": "payload", "time_utc": None, "text": "u='https://huggingface.co/datasets/[HF REPO 1]/resolve/main/train.jsonl';fetch(u,{headers:{Authorization:'Bearer [CREDENTIAL 169]'}})"},
    {"id": "R0000003", "kind": "response", "time_utc": "2026-07-10T12:00:00Z", "text": "200 ok"},
]


def write_dataset(d):
    p = os.path.join(d, "release.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in DATA:
            f.write(json.dumps(r) + "\n")
    return p


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="st-sitecheck-")
        self.docs = os.path.join(self.d, "docs")
        self.inv, self.story, self.bundle = fake_site(self.docs)
        self.data = write_dataset(self.d)

    def tearDown(self):
        shutil.rmtree(self.d)

    def rules(self, **kw):
        res = S.run(self.docs, allow_path=None, **kw)
        return sorted({f.rule for f in res["findings"]}), res

    def save(self, story=None, bundle=None, rebuild=True):
        if story is not None:
            write(os.path.join(self.inv, "stories", "one.json"), json.dumps(story))
        if bundle is not None:
            write(os.path.join(self.inv, "data", "one.json"), json.dumps(bundle, indent=1) + "\n")
        if rebuild:
            B.build(None, False, self.inv, False, True, log=lambda *a: None)

    def test_clean_site_passes_with_and_without_the_dataset(self):
        rules, res = self.rules()
        self.assertEqual(rules, [], [str(f) for f in res["findings"]])
        self.assertTrue(any("no --dataset" in n for n in res["notes"]))
        rules, res = self.rules(dataset=self.data)
        self.assertEqual(rules, [], [str(f) for f in res["findings"]])

    def test_claim_ref_that_is_not_in_the_bundle(self):
        b = copy.deepcopy(self.bundle)
        del b["records"]["R0000001"]
        self.save(bundle=b, rebuild=False)
        rules, res = self.rules()
        self.assertIn("evidence-ref-unresolved", rules)
        self.assertTrue(any("R0000001" in f.text for f in res["findings"]))

    def test_claim_without_evidence_and_uncited_record(self):
        s = copy.deepcopy(self.story)
        s["claims"]["c2"] = {"evidence": "nothing"}
        s["body"][2]["p"] = "Also [[c2|someone read it]] " + "word " * 300
        self.save(story=s)
        rules, _ = self.rules()
        self.assertIn("claim-without-evidence", rules)
        self.assertIn("uncited-record-in-bundle", rules)

    def test_record_missing_from_or_differing_from_the_dataset(self):
        b = copy.deepcopy(self.bundle)
        b["records"]["R0000001"]["actor"] = "[CREDENTIAL 999]"
        b["records"]["R0000002"]["kind"] = "response"
        s = copy.deepcopy(self.story)
        s["claims"]["c2"]["records"].append("R0000009")
        b["records"]["R0000009"] = dict(b["records"]["R0000001"], id="R0000009")
        self.save(story=s, bundle=b)
        rules, res = self.rules(dataset=self.data)
        self.assertIn("record-not-in-dataset", rules)
        detail = " | ".join(f"{f.text}: {f.detail}" for f in res["findings"] if f.rule == "record-differs")
        self.assertIn("R0000001: token [CREDENTIAL 999]", detail)
        self.assertIn("R0000002: kind", detail)

    def test_time_must_match_a_time_the_release_gives(self):
        b = copy.deepcopy(self.bundle)
        s = copy.deepcopy(self.story)
        s["claims"]["c2"]["records"].append("R0000003")
        b["records"]["R0000003"] = dict(b["records"]["R0000001"], id="R0000003", kind="response", actor_kind="run", actor="run:R0000003",
                                        time="2026-07-10 13:00", time_estimated=False, time_source="field")
        self.save(story=s, bundle=b)
        _, res = self.rules(dataset=self.data)
        self.assertTrue(any(f.rule == "record-differs" and f.text == "R0000003" and "time" in f.detail for f in res["findings"]))
        b["records"]["R0000003"]["time"] = "2026-07-10 12:00"
        self.save(bundle=b)
        rules, res = self.rules(dataset=self.data)
        self.assertEqual(rules, [], [str(f) for f in res["findings"]])

    def test_number_on_the_page_that_differs_from_the_bundle(self):
        p = os.path.join(self.inv, "one", "index.html")
        with open(p, encoding="utf-8") as f:
            page = f.read()
        write(p, page.replace('data-v="n">24<', 'data-v="n">19<'))
        rules, res = self.rules()
        self.assertIn("number-differs", rules)
        self.assertIn("page-stale", rules)
        self.assertTrue(any("19" in f.detail and "24" in f.detail for f in res["findings"] if f.rule == "number-differs"))

    def test_bundle_changed_after_the_page_was_built(self):
        b = copy.deepcopy(self.bundle)
        b["figures"]["n"].update(value=6, text="6")
        self.save(bundle=b, rebuild=False)
        rules, _ = self.rules()
        self.assertIn("number-differs", rules)

    def test_number_typed_into_the_story(self):
        s = copy.deepcopy(self.story)
        s["body"][1]["p"] += " In all 189,579 records were read."
        self.save(story=s)
        rules, res = self.rules()
        self.assertEqual(rules, ["number-not-from-bundle"], [str(f) for f in res["findings"]])
        self.assertEqual([f.text for f in res["findings"]], ["189,579"])

    def test_story_length(self):
        s = copy.deepcopy(self.story)
        s["body"][2]["p"] = "Also [[c2|{rec:R0000002.actor} read what {rec:R0000001.actor} wrote]]."
        self.save(story=s)
        rules, _ = self.rules()
        self.assertIn("story-length", rules)

    def test_broken_links(self):
        write(os.path.join(self.docs, "page.html"), '<a href="missing.html">x</a><a href="validation.html">ok: rendered from .md</a>'
              '<img src="assets/none.png"><a href="#nowhere">x</a><a id="here" href="#here">ok</a><a href="https://example.org/x">ext</a>'
              '<script src="demo/none.js"></script><a href="investigations/one/">ok</a>')
        write(os.path.join(self.docs, "notes.md"), "[ok](validation.md) [bad](nope.md) ![img](assets/a.png) [ext](https://example.org)\n```\n[code](not-a-link.md)\n```\n")
        _, res = self.rules()
        got = sorted((f.rule, f.path, f.text) for f in res["findings"])
        self.assertEqual(got, [("broken-anchor", "page.html", "#nowhere"), ("broken-link", "notes.md", "nope.md"),
                               ("broken-link", "page.html", "assets/none.png"), ("broken-link", "page.html", "demo/none.js"),
                               ("broken-link", "page.html", "missing.html")])

    def test_demo_manifest_must_be_complete(self):
        demo = os.path.join(self.docs, "demo")
        write(os.path.join(demo, "static.json"), json.dumps({"paths": {"/api/state": 1, "/api/event": 2}}))
        write(os.path.join(demo, "data", "state-0.json"), "{}")
        write(os.path.join(demo, "data", "event-0.json"), "{}")
        write(os.path.join(demo, "data", "records-index.json"), "{}")
        _, res = self.rules()
        got = [(f.rule, f.text.replace(os.sep, "/")) for f in res["findings"]]
        self.assertIn(("demo-pack-missing", "demo/data/event-1.json"), got)
        self.assertIn("demo-not-static", [r for r, _ in got])

    def test_snippets_on_fails_unless_allowed(self):
        shutil.rmtree(self.docs)
        self.inv, self.story, self.bundle = fake_site(self.docs, snippets=True)
        rules, _ = self.rules(dataset=self.data)
        self.assertIn("snippets-on", rules)
        self.assertIn("record-text-field", rules)
        self.assertIn("record-text", rules)
        res = S.run(self.docs, dataset=self.data, allow_path=None, allow_snippets=True)
        self.assertEqual([str(f) for f in res["findings"]], [])

    def test_record_text_pasted_into_any_page_is_found(self):
        quote = DATA[0]["text"][20:110]
        write(os.path.join(self.docs, "deep.md"), "As the payload says: `" + quote + "` and so on.")
        write(os.path.join(self.docs, "page.html"), "<p>" + DATA[1]["text"].replace("'", "&#x27;") + "</p>")
        write(os.path.join(self.docs, "demo", "data", "event-0.json"), json.dumps({"text": DATA[0]["text"]}))
        _, res = self.rules(dataset=self.data)
        hits = {f.path: f for f in res["findings"] if f.rule == "record-text"}
        self.assertEqual(sorted(hits), ["deep.md", "page.html"], "the simulated demo folder is not searched")
        self.assertIn("R0000001", hits["deep.md"].detail)
        self.assertIn("R0000002", hits["page.html"].detail)
        self.assertGreaterEqual(len(hits["deep.md"].text), S.SHINGLE)

    def test_short_quotes_and_page_markup_are_not_record_text(self):
        write(os.path.join(self.docs, "ok.md"), "The code calls `https://huggingface.co/api/datasets/` with a bearer token.")
        _, res = self.rules(dataset=self.data)
        self.assertEqual([str(f) for f in res["findings"]], [])

    def test_allowlist_waives_and_reports_unused_entries(self):
        write(os.path.join(self.docs, "contact.md"), "mail " + FAKES["email"].split()[2])
        allow = os.path.join(self.d, "allow.json")
        write(allow, json.dumps([{"rule": "email", "match": "jane.roe@corp-mail.io", "reason": "published contact"},
                                 {"rule": "ip-address", "match": "10.9.8.7", "reason": "never used"}]))
        res = S.run(self.docs, allow_path=allow)
        self.assertEqual(res["findings"], [])
        self.assertEqual(len(res["waived"]), 1)
        self.assertTrue(any("matched nothing" in n for n in res["notes"]))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(S.main(["--docs", self.docs, "--allow", allow]), 0)
            self.assertEqual(S.main(["--docs", self.docs, "--allow", os.path.join(self.d, "none.json")]), 1)
        self.assertIn("redaction: 1 findings", out.getvalue())


@unittest.skipUnless(os.path.isdir(os.path.join(S.DOCS, "investigations")), "needs the source checkout (docs/ is not in an installed copy)")
class CommittedSiteTests(unittest.TestCase):
    """The site in this repository, checked offline (no dataset, no server)."""

    def test_committed_bundles_publish_no_record_text(self):
        self.assertEqual([str(f) for f in S.check_no_snippets(S.DOCS)], [])

    def test_committed_investigations_resolve_and_match(self):
        fs = S.check_evidence(S.DOCS) + S.check_numbers(S.DOCS)
        self.assertEqual([str(f) for f in fs], [])
        _, _, stories, bundles = S.load_investigations(S.DOCS)
        self.assertEqual(len(stories), 3)
        for s in stories:
            self.assertLessEqual(len(bundles[s["slug"]]["records"]), B.MAX_RECORDS)

    def test_allowlist_entries_all_have_reasons(self):
        self.assertTrue(all(a.get("reason") and a.get("rule") for a in S.load_allow(S.ALLOW)))


if __name__ == "__main__":
    unittest.main()

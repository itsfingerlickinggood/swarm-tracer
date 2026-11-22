"""Tests for the site checks: the scanners are run on planted fakes in a temporary docs folder.

The fake secrets are put together at run time, so this file holds nothing a secret scanner would stop.
"""
import contextlib
import copy
import html
import io
import json
import os
import re
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
             "figures": {"n": {"from": "/api/state", "path": "summary.flow.deliveries", "as": "int", "label": "messages"}},
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
        b["records"]["R0000009"] = dict(b["records"]["R0000001"], id="R0000009", viewer=B.CITATION["viewer"].format(id="R0000009"))
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
                                        time="2026-07-10 13:00", time_estimated=False, time_source="field",
                                        viewer=B.CITATION["viewer"].format(id="R0000003"))
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


REPORT = {"tool_version": "9.9.8", "measured_on": "2026-11-22", "totals": {"runs": 184, "share": 0.25}, "words": [{"match": "secret"}]}


def external_story(slug, dataset, order, records=True):
    """A story of a measured dataset: its numbers are read from reports/external/<name>/results.json."""
    cit = B.citation_of(dataset)
    claims = {"c1": {"evidence": "The runs.", "figures": ["runs", "share"]}}
    body = [{"h": "Start"}, {"p": "There are [[c1|{runs} runs, {share} of them flagged]]. " + "word " * 300}]
    if records:
        claims["c2"] = {"evidence": "One message.", "records": [{"id": "hc1:3", "note": "an instruction"}]}
        body.append({"p": "And [[c2|one agent wrote to another]]."})
    return {"slug": slug, "title": slug.title(), "dek": "A story with {runs} runs.", "order": order, "dataset": dataset,
            "kicker": cit["name"], "source": {"attribution": cit["attribution"]},
            "figures": {"runs": {"from": cit["report"], "path": "totals.runs", "as": "int", "label": "runs"},
                        "share": {"from": cit["report"], "path": "totals.share", "as": "pct", "label": "flagged"}},
            "body": body, "claims": claims}


def external_bundle(story, snippet="Please search for the schools near the exchange and list their names."):
    cit = B.citation_of(story["dataset"])
    api = B.Api(None, ROOT_OF[0])
    b = {"schema": 1, "story": story["slug"], "dataset": cit["dataset"], "snippets": "off", "citation": cit,
         "produced_by": dict({"tool": "Swarm Tracer", "version": "9.9.9", "pack": "generic agent traces"}, **B.report_stamp(cit, api)),
         "figures": B.resolve_figures(story, api), "records": {}, "findings": {}}
    if B.cited_records(story):
        b["snippets"] = "on"
        b["records"]["hc1:3"] = {"id": "hc1:3", "kind": "instruction", "time": None, "time_estimated": False, "time_source": None,
                                 "actor": "Orchestrator", "actor_kind": "named", "agent": None, "intent": "other", "text_length": 131,
                                 "judged": [{"op": "write", "place": "inbox:WebSurfer", "place_label": "inbox WebSurfer", "in_text": False}],
                                 "messages": [], "snippet": snippet}
    return b


ROOT_OF = [None]        # the temporary folder that holds docs/ and reports/ for the test that is running


class OtherDatasetTests(unittest.TestCase):
    """Stories of datasets other than Swarm Traces: an openly licensed one (excerpts with the credit line), and one
    that is published as numbers only. The citation and the rule come from the real registry."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="st-sitecheck-")
        ROOT_OF[0] = self.d
        self.docs = os.path.join(self.d, "docs")
        self.inv, self.swarm, _ = fake_site(self.docs)
        for name in ("who_and_when", "moltbook"):
            write(os.path.join(self.d, "reports", "external", name, "results.json"), json.dumps(REPORT))
        self.open = external_story("two", "who_and_when", 2)
        self.numbers = external_story("three", "moltbook_observatory", 3, records=False)
        for st in (self.open, self.numbers):
            self.save(st, external_bundle(st), rebuild=False)
        self.build()

    def tearDown(self):
        shutil.rmtree(self.d)

    def save(self, story, bundle=None, rebuild=True):
        write(os.path.join(self.inv, "stories", story["slug"] + ".json"), json.dumps(story))
        if bundle is not None:
            write(os.path.join(self.inv, "data", story["slug"] + ".json"), json.dumps(bundle, indent=1) + "\n")
        if rebuild:
            self.build()

    def build(self, **kw):
        kw.setdefault("from_bundles", True)
        return B.build(None, None, self.inv, log=lambda *a: None, root=self.d, **kw)

    def bundle(self, slug):
        with open(os.path.join(self.inv, "data", slug + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def page(self, slug=None):
        with open(os.path.join(self.inv, slug, "index.html") if slug else os.path.join(self.inv, "index.html"), encoding="utf-8") as f:
            return f.read()

    def rules(self):
        res = S.run(self.docs, allow_path=None)
        return sorted({f.rule for f in res["findings"]}), res

    def test_three_datasets_build_and_pass(self):
        rules, res = self.rules()
        self.assertEqual(rules, [], [str(f) for f in res["findings"]])

    def test_gallery_is_grouped_by_dataset_with_the_registry_citation_licence_and_credit(self):
        index = self.page()
        self.assertEqual(re.findall(r'<section class="group" id="ds-[a-z_]+" data-dataset="([a-z_]+)"', index),
                         ["swarm_traces", "who_and_when", "moltbook_observatory"])
        seen = html.unescape(index)
        for did in ("swarm_traces", "who_and_when", "moltbook_observatory"):
            cit = B.citation_of(did)
            for k in ("title", "attribution", "licence"):
                self.assertIn(cit[k], seen, f"{did}: {k}")
            self.assertIn(cit["text"].rstrip("."), seen, did)
            self.assertIn(f'href="../datasets.html#{did}"', index)
        for slug in ("one", "two", "three"):
            self.assertEqual(index.count(f'<a href="{slug}/">'), 1)
            page = html.unescape(self.page(slug))
            cit = B.citation_of(B.dataset_of(next(s for s in B.load_stories(self.inv) if s["slug"] == slug)))
            self.assertIn(cit["attribution"], page)
            self.assertIn("Licence: " + cit["licence"], page)

    def test_record_links_and_text_follow_each_dataset(self):
        swarm, open_, numbers = self.page("one"), self.page("two"), self.page("three")
        self.assertIn('href="https://swarmtraces.org/viewer/#/row/R0000001"', swarm)        # the publisher's viewer, no text
        self.assertNotIn("<blockquote", swarm)
        self.assertIn("Please search for the schools", open_)                                # an excerpt, with its credit
        quote = re.search(r"<blockquote.*?</blockquote>", open_, flags=re.S).group(0)
        self.assertIn(B.citation_of("who_and_when")["attribution"], html.unescape(quote))
        self.assertNotIn("swarmtraces.org/viewer", open_)
        self.assertNotIn("<blockquote", numbers)                                             # numbers only
        self.assertNotIn("data-rid", numbers)
        self.assertIn("Numbers only", numbers)

    def test_number_that_the_saved_result_no_longer_holds(self):
        write(os.path.join(self.d, "reports", "external", "who_and_when", "results.json"),
              json.dumps(dict(REPORT, totals={"runs": 190, "share": 0.25})))
        rules, res = self.rules()
        self.assertEqual(rules, ["figure-differs-from-report"], [str(f) for f in res["findings"]])
        f = res["findings"][0]
        self.assertEqual((f.path, f.text), ("investigations/data/two.json", "runs"))
        self.assertIn("184", f.detail)
        self.assertIn("190", f.detail)
        with self.assertRaises(SystemExit) as e:                       # a pages-only build will not print the stale number
            self.build()
        self.assertIn("runs is '184' in the bundle, '190' in the saved result", str(e.exception))
        self.build(from_bundles=False, keep=("swarm_traces", "who_and_when"))     # the build reads the saved result again
        self.assertEqual(self.bundle("two")["figures"]["runs"]["value"], 190)
        self.assertIn('data-v="runs">190<', self.page("two"))
        self.assertEqual(self.bundle("two")["records"]["hc1:3"]["snippet"][:13], "Please search", "kept: the dataset was not read")
        rules, res = self.rules()
        self.assertEqual(rules, [], [str(f) for f in res["findings"]])

    def test_saved_result_that_is_missing_or_lacks_the_figure(self):
        os.remove(os.path.join(self.d, "reports", "external", "moltbook", "results.json"))
        _, res = self.rules()
        got = {(f.rule, f.path, f.text) for f in res["findings"]}
        self.assertEqual(got, {("figure-differs-from-report", "investigations/data/three.json", k) for k in ("runs", "share")})
        with self.assertRaises(SystemExit):
            self.build(from_bundles=False, keep=("swarm_traces", "who_and_when"))
        write(os.path.join(self.d, "reports", "external", "moltbook", "results.json"), json.dumps({"totals": {"runs": 184}}))
        with self.assertRaises(SystemExit) as e:
            self.build(from_bundles=False, keep=("swarm_traces", "who_and_when"))
        self.assertIn("figure share", str(e.exception))

    def test_story_may_read_only_its_own_datasets_saved_result(self):
        s = copy.deepcopy(self.numbers)
        s["figures"]["runs"]["from"] = "reports/external/who_and_when/results.json"
        self.save(s, rebuild=False)
        rules, res = self.rules()
        self.assertIn("story-breaks-dataset-rule", rules)
        self.assertTrue(any("reads reports/external/moltbook/results.json and nothing else" in f.text for f in res["findings"]))
        with self.assertRaises(SystemExit):
            self.build(from_bundles=False, keep=("swarm_traces", "who_and_when"))

    def test_numbers_only_dataset_takes_no_record_and_no_text(self):
        s = copy.deepcopy(self.numbers)
        s["claims"]["c1"]["records"] = ["hc1:3"]
        b = self.bundle("three")
        b["records"] = external_bundle(self.open)["records"]
        b["snippets"] = "on"
        self.save(s, b)
        rules, res = self.rules()
        for rule in ("record-in-numbers-only", "snippets-on", "story-breaks-dataset-rule", "record-text-on-page", "record-text-field"):
            self.assertIn(rule, rules, [str(f) for f in res["findings"]])
        with self.assertRaises(SystemExit) as e:                       # and the builder refuses to make such a bundle
            B.build_bundle(s, B.Api(None, self.d))
        self.assertIn("numbers only", str(e.exception))
        # a figure that is text is one word: a sentence of a post cannot come in as a "figure"
        s = copy.deepcopy(self.numbers)
        s["figures"]["word"] = {"from": "reports/external/moltbook/results.json", "path": "words.0.match", "as": "text", "label": "a word"}
        s["claims"]["c1"]["figures"].append("word")
        self.assertEqual(B.build_bundle(s, B.Api(None, self.d))["figures"]["word"]["text"], "secret")
        write(os.path.join(self.d, "reports", "external", "moltbook", "results.json"),
              json.dumps(dict(REPORT, words=[{"match": "a whole sentence that an agent posted"}])))
        with self.assertRaises(SystemExit) as e:
            B.build_bundle(s, B.Api(None, self.d))
        self.assertIn("would print text", str(e.exception))
        b = self.bundle("three")
        b["figures"]["word"] = B.figure_entry(s["figures"]["word"], "a whole sentence that an agent posted")
        self.save(s, b)
        self.assertIn("text-in-numbers-only", self.rules()[0])

    def test_excerpt_needs_the_credit_line_and_the_registry_citation(self):
        cit = B.citation_of("who_and_when")
        p = os.path.join(self.inv, "two", "index.html")
        page = self.page("two")
        quote = re.search(r"<blockquote.*?</blockquote>", page, flags=re.S).group(0)
        write(p, page.replace(quote, quote.replace(html.escape(cit["attribution"]), "from a dataset")))
        rules, _ = self.rules()
        self.assertIn("excerpt-without-credit", rules)
        self.assertIn("page-stale", rules)
        self.build()
        b = self.bundle("two")
        b["citation"]["attribution"] = "Ours."
        self.save(self.open, b, rebuild=False)
        self.assertIn("citation-differs", self.rules()[0])
        s = copy.deepcopy(self.open)                                  # a story cannot carry a credit line of its own
        s["source"]["attribution"] = "Ours."
        self.save(s, self.bundle("two"), rebuild=False)
        rules, res = self.rules()
        self.assertIn("story-breaks-dataset-rule", rules)
        with self.assertRaises(SystemExit) as e:
            self.build(from_bundles=False, keep=("swarm_traces", "who_and_when"))
        self.assertIn("credit line differs from the registry's", str(e.exception))

    def test_excerpt_is_bounded_and_scanned_like_any_page(self):
        b = external_bundle(self.open, snippet="x" * (B.SNIPPET_MAX + 1))
        self.save(self.open, b)
        self.assertIn("snippet-too-long", self.rules()[0])
        b = external_bundle(self.open, snippet="export KEY=" + FAKES["hf-token"])
        self.save(self.open, b)
        self.assertIn("hf-token", self.rules()[0])

    def test_record_of_a_viewer_dataset_links_to_the_viewer(self):
        with open(os.path.join(self.inv, "data", "one.json"), encoding="utf-8") as f:
            b = json.load(f)
        b["records"]["R0000001"]["viewer"] = "https://example.org/viewer/R0000001"
        self.save(self.swarm, b)
        rules, res = self.rules()
        self.assertEqual(rules, ["viewer-link"], [str(f) for f in res["findings"]])
        b = self.bundle("two")                                        # and a dataset with no viewer has no such link
        b["records"]["hc1:3"]["viewer"] = "https://swarmtraces.org/viewer/#/row/hc1:3"
        self.save(self.open, b)
        self.assertIn("viewer-link", self.rules()[0])

    def test_dataset_must_be_in_the_registry_and_match_the_story(self):
        s = dict(self.open, dataset="no_such_dataset")
        self.save(s, rebuild=False)
        self.assertIn("dataset-differs", self.rules()[0])
        with self.assertRaises(SystemExit) as e:
            self.build()
        self.assertIn("no \"gallery\" block", str(e.exception))


@unittest.skipUnless(os.path.isdir(os.path.join(S.DOCS, "investigations")), "needs the source checkout (docs/ is not in an installed copy)")
class CommittedSiteTests(unittest.TestCase):
    """The site in this repository, checked offline (no dataset, no server): every story, whatever their number."""

    @classmethod
    def setUpClass(cls):
        _, cls.inv, cls.stories, cls.bundles = S.load_investigations(S.DOCS)

    def page(self, slug=None):
        with open(os.path.join(self.inv, slug, "index.html") if slug else os.path.join(self.inv, "index.html"), encoding="utf-8") as f:
            return f.read()

    def test_every_story_has_a_bundle_a_page_and_a_place_in_the_gallery(self):
        self.assertGreaterEqual(len(self.stories), 7)
        index = self.page()
        for s in self.stories:
            with self.subTest(story=s["slug"]):
                self.assertIn(s["slug"], self.bundles, "no bundle")
                self.assertTrue(os.path.isfile(os.path.join(self.inv, s["slug"], "index.html")), "no page")
                self.assertEqual(index.count(f'<a href="{s["slug"]}/">'), 1)
                self.assertLessEqual(len(self.bundles[s["slug"]]["records"]), B.MAX_RECORDS)
        slugs = {s["slug"] for s in self.stories}
        extra = {f[:-5] for f in os.listdir(os.path.join(self.inv, "data")) if f.endswith(".json")} - slugs
        self.assertEqual(extra, set(), "a bundle with no story")

    def test_committed_investigations_resolve_and_match(self):
        fs = S.check_evidence(S.DOCS) + S.check_links(S.DOCS) + S.check_numbers(S.DOCS)
        self.assertEqual([str(f) for f in fs], [])

    def test_committed_bundles_keep_to_their_dataset_rules(self):
        self.assertEqual([str(f) for f in S.check_record_rules(S.DOCS)], [])
        seen = set()
        for s in self.stories:
            b = self.bundles[s["slug"]]
            cit = B.citation_of(B.dataset_of(s, b))
            seen.add(cit["dataset"])
            page = self.page(s["slug"])
            with self.subTest(story=s["slug"], rule=cit["records"]):
                self.assertEqual(b["citation"], cit, "the citation is the registry's")
                self.assertIn(cit["attribution"], html.unescape(page))
                if cit["records"] == "viewer":            # no stated licence: no record text, a link to the publisher's viewer
                    self.assertEqual(b["snippets"], "off")
                    self.assertNotIn("<blockquote", page)
                    for rid, r in b["records"].items():
                        self.assertNotIn("snippet", r)
                        self.assertIn(f'href="{html.escape(cit["viewer"].format(id=rid))}"', page)
                elif cit["records"] == "excerpts":        # an open licence: short excerpts, each with the credit line
                    quotes = re.findall(r"<blockquote.*?</blockquote>", page, flags=re.S)
                    self.assertEqual(len(quotes), sum(1 for r in b["records"].values() if "snippet" in r))
                    for q in quotes:
                        self.assertIn(cit["attribution"], html.unescape(q))
                    self.assertTrue(all(len(r.get("snippet", "")) <= B.SNIPPET_MAX and "viewer" not in r for r in b["records"].values()))
                else:                                     # numbers only: no record, so no text and no agent name
                    self.assertEqual((b["records"], b["snippets"]), ({}, "off"))
                    self.assertNotIn("<blockquote", page)
                    self.assertNotIn("data-rid", page)
                    self.assertEqual(B.cited_records(s), [])
        self.assertLessEqual({"swarm_traces", "who_and_when", "mast_data", "salt_agent_collusion", "moltbook_observatory"}, seen)
        self.assertEqual(B.citation_of("swarm_traces")["records"], "viewer")
        self.assertEqual(B.citation_of("moltbook_observatory")["records"], "none")

    def test_committed_numbers_are_the_saved_results(self):
        """A story of a measured dataset reads reports/external/<name>/results.json and prints what it holds now."""
        checked = 0
        for s in self.stories:
            cit = B.citation_of(B.dataset_of(s))
            if not cit.get("report"):
                continue
            if not os.path.isfile(os.path.join(B.ROOT, *cit["report"].split("/"))):
                self.skipTest(cit["report"] + " is not in this copy")
            res = B.read_report(cit["report"])
            b = self.bundles[s["slug"]]
            for key, spec in s["figures"].items():
                with self.subTest(story=s["slug"], figure=key):
                    self.assertEqual(spec["from"], cit["report"])
                    self.assertEqual(b["figures"][key]["value"], B.figure_value(spec, res))
                    self.assertIn(f'data-v="{key}">{html.escape(B.fmt_value(B.figure_value(spec, res), spec["as"]))}<', self.page(s["slug"]))
                    checked += 1
            self.assertEqual(B.report_mismatches(s, b), [])
        self.assertGreater(checked, 50)

    def test_gallery_groups_the_stories_by_dataset(self):
        index = self.page()
        groups = re.findall(r'<section class="group" id="ds-[a-z_]+" data-dataset="([a-z_]+)"', index)
        want = []
        for s in self.stories:
            d = B.dataset_of(s, self.bundles[s["slug"]])
            if d not in want:
                want.append(d)
        self.assertEqual(groups, want)
        for did in groups:
            cit = B.citation_of(did)
            for k in ("title", "licence", "attribution"):
                self.assertIn(cit[k], html.unescape(index), f"{did}: {k}")

    def test_allowlist_entries_all_have_reasons(self):
        self.assertTrue(all(a.get("reason") and a.get("rule") for a in S.load_allow(S.ALLOW)))


if __name__ == "__main__":
    unittest.main()

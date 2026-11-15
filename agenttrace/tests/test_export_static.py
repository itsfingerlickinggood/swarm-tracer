"""Tests for the static export (the hosted demo) and the investigations builder.

The export itself runs in a child process, because it loads a dataset into the server's global state and
points the per-user state folder at a temporary one. The browser parts (crawl, --verify) are not run here.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from agenttrace.tools import build_investigations as B
from agenttrace.tools import export_static as X

ROOT = X.ROOT
NODE = shutil.which("node")

# runs static.js outside a browser: a fetch that reads the export folder and the few page objects it touches
NODE_HARNESS = r"""
const fs = require("fs"), path = require("path");
const dir = process.argv[2], queries = JSON.parse(process.argv[3]);
const el = () => ({ classList: { add() {} }, setAttribute() {}, appendChild() {}, insertBefore() {}, after() {}, querySelector: () => null, dataset: {}, style: {} });
globalThis.window = globalThis; globalThis.addEventListener = () => {};
globalThis.document = { documentElement: el(), body: el(), addEventListener() {}, getElementById: () => null, querySelector: () => null, createElement: el };
globalThis.fetch = async (f) => { const p = path.join(dir, f); if (!fs.existsSync(p)) return { ok: false, status: 404 }; return { ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) }; };
require(path.join(dir, "static.js"));
(async () => {
  const out = [];
  for (const q of queries) {
    try { out.push({ ok: await window.ST_STATIC.api(q.path, q.opts) }); } catch (e) { out.push({ error: e.message }); }
  }
  out.push({ keys: queries.map((q) => { const p = window.ST_STATIC.parse(q.path); const k = window.ST_STATIC.canon(p.path, p.q); return [k, window.ST_STATIC.fnv(k)]; }) });
  console.log(JSON.stringify(out));
})();
"""


class DedupeTests(unittest.TestCase):
    def test_rows_and_shared_values_round_trip(self):
        rows = {"R1": {"id": "R1", "kind": "payload", "preview": "p" * 60}, "R2": {"id": "R2", "kind": "tool", "preview": "q"}}
        big = {"actor": "a", "hourly": [["2026-07-03 01", 2]] * 9}
        items = {"k1": dict(rows["R1"], text="t", children=[dict(rows["R2"], score=1.5), {"id": "R2", "kind": "other"}], explain=big),
                 "k2": dict(rows["R2"], explain=big, label="x" * 80, again=["x" * 80, {"id": "R9"}])}
        enc = {k: X.ref_rows(v, rows) for k, v in items.items()}
        self.assertEqual(enc["k1"]["children"][0], {"$r": "R2", "score": 1.5})
        self.assertEqual(enc["k1"]["children"][1], {"id": "R2", "kind": "other"}, "a row with another value is left alone")
        self.assertNotIn("preview", enc["k1"])
        old = X.SHARE_FILE_MIN
        try:
            X.SHARE_FILE_MIN = 0
            packed, table = X.share(enc)
            X.SHARE_FILE_MIN = 10 ** 9
            self.assertEqual(X.share(enc), (enc, None), "too little saved: no shared file")
        finally:
            X.SHARE_FILE_MIN = old
        self.assertEqual(packed["k1"]["explain"], packed["k2"]["explain"])
        self.assertIn("$s", packed["k1"]["explain"])
        for k in items:
            self.assertEqual(X.decode(packed[k], rows, table), items[k])
        with self.assertRaises(SystemExit):
            X.ref_rows({"a": [{"$r": "R1"}]}, rows)


class KeyTests(unittest.TestCase):
    def test_canonical_key_sorts_and_drops_empty(self):
        path, q = X.parse("/api/list?name=channels&q=&offset=0&limit=200")
        self.assertEqual(path, "/api/list")
        self.assertEqual(X.canon(path, q), "/api/list?limit=200&name=channels&offset=0")
        self.assertEqual(X.canon(*X.parse("/api/state")), "/api/state?")

    def test_key_decodes_and_keeps_first_value(self):
        path, q = X.parse("/api/actor?a=%5BCREDENTIAL+5%5D&a=other")
        self.assertEqual(q, {"a": "[CREDENTIAL 5]"})
        self.assertEqual(X.canon(path, q), "/api/actor?a=[CREDENTIAL 5]")

    def test_fnv_vectors(self):
        self.assertEqual(X.fnv(""), 0x811C9DC5)
        self.assertEqual(X.fnv("a"), 0xE40C292C)
        self.assertEqual(X.fnv("foobar"), 0xBF9CF968)

    def test_slug(self):
        self.assertEqual(X.slug("/api/x/units_map"), "x_units_map")
        self.assertEqual(X.slug("/api/event"), "event")

    def test_request_url_round_trips(self):
        q = {"a": "run:R1", "b": "[CREDENTIAL 5]"}
        self.assertEqual(X.parse(X.request_url("/api/conversation", q)), ("/api/conversation", q))


class ExpandTests(unittest.TestCase):
    def test_sample_requests_are_repeated_for_everything(self):
        seen = ["/api/state", "/api/event?id=R1", "/api/event?lite=1&id=R1", "/api/actor?a=tok", "/api/place?ch=p1",
                "/api/conversation?a=tok&b=tok2", "/api/events?limit=100", "/api/x/fx_like?id=R1&k=5"]
        samples = {"rec": ["R1"], "actor": ["tok"], "place": ["p1"], "pair": [("tok", "tok2")]}
        pop = {"rec": ["R1", "R2", "R3"], "actor": ["tok", "tok2"], "place": ["p1", "p2"], "pair": [("tok", "tok2"), ("tok2", "tok")]}
        keys = {X.canon(p, q) for p, q in X.expand(seen, samples, pop)}
        for want in ("/api/state?", "/api/event?id=R3", "/api/event?id=R2&lite=1", "/api/actor?a=tok2", "/api/place?ch=p2",
                     "/api/conversation?a=tok2&b=tok", "/api/x/fx_like?id=R3&k=5"):
            self.assertIn(want, keys)
        self.assertFalse([k for k in keys if k.startswith("/api/events")], "queries the page answers itself are not saved")
        self.assertNotIn("/api/conversation?a=tok2&b=tok2", keys, "a pair request is repeated per pair, not per actor")


class StaticIndexTests(unittest.TestCase):
    def test_app_page_is_switched_to_static(self):
        with open(os.path.join(X.APP_DIR, "index.html"), encoding="utf-8") as f:
            page = X.static_index(f.read(), "demo")
        self.assertIn('<meta name="st-static" content="demo">', page)
        self.assertLess(page.index('src="static.js"'), page.index('src="core.js"'))
        self.assertNotIn('src="/', page)
        self.assertNotIn('href="/', page)
        self.assertEqual(X.static_index(page, "demo"), page)

    def test_core_js_has_the_switch_and_no_other_fetch(self):
        with open(os.path.join(X.APP_DIR, "core.js"), encoding="utf-8") as f:
            core = f.read()
        self.assertIn("if (STATIC) return STATIC.api(path, opts);", core)
        self.assertIn("const STATIC = window.ST_STATIC || null;", core)
        for root, _, files in os.walk(X.APP_DIR):
            for name in files:
                if name.endswith(".js"):
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        n = f.read().count("fetch(")
                    self.assertEqual(n, 1 if name == "core.js" else 0, f"{name}: every request must go through api()")

    def test_server_never_serves_static_mode(self):
        with open(os.path.join(X.APP_DIR, "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotIn("st-static", page)
        self.assertNotIn("static.js", page)


class ScrubTests(unittest.TestCase):
    def test_machine_folders_are_removed(self):
        home = os.path.expanduser("~")
        text = json.dumps({"a": os.path.join(ROOT, "redacted.csv"), "b": os.path.join(home, ".swarm-tracer", "x.json")})
        out = X.scrub(text)
        self.assertNotIn(home, out)
        self.assertEqual(json.loads(out), {"a": "redacted.csv", "b": "~/.swarm-tracer/x.json"})


class DatasetRegistryTests(unittest.TestCase):
    def test_only_the_demo_is_listed(self):
        self.assertEqual(sorted(X.DATASETS), ["demo"])
        self.assertTrue(os.path.isdir(X.DATASETS["demo"]["path"]))
        self.assertTrue(X.DATASETS["demo"]["licence"])

    def test_unknown_dataset_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            X.export("swarm-traces", tempfile.mkdtemp())
        self.assertIn("unknown dataset", str(e.exception))

    def test_will_not_overwrite_a_folder_that_is_not_an_export(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "keep.txt"), "w") as f:
            f.write("x")
        with self.assertRaises(SystemExit):
            X.write_export(d, {}, {}, {"dataset": "demo"})
        self.assertTrue(os.path.isfile(os.path.join(d, "keep.txt")))


@unittest.skipUnless(os.path.isdir(os.path.join(ROOT, "docs")), "needs the source checkout (docs/ is not in an installed copy)")
class ExportRunTests(unittest.TestCase):
    """One export without Chrome, drill-down for four records, read back the way static.js reads it."""

    @classmethod
    def setUpClass(cls):
        cls.out = os.path.join(tempfile.mkdtemp(prefix="st-export-test-"), "demo")
        r = subprocess.run([sys.executable, "-m", "agenttrace.tools.export_static", "--out", cls.out, "--no-browser", "--max-records", "4"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        cls.log = r.stdout + r.stderr
        if r.returncode != 0:
            raise AssertionError("export failed: " + cls.log[-2000:])
        with open(os.path.join(cls.out, "static.json"), encoding="utf-8") as f:
            cls.man = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(os.path.dirname(cls.out), ignore_errors=True)

    def lookup(self, url):
        return X.read_saved(self.out, url)

    def test_manifest(self):
        m = self.man
        self.assertTrue(m["static"])
        self.assertEqual(m["dataset"], "demo")
        self.assertEqual(m["drilldown"]["records"], 4)
        self.assertGreater(m["records"], 1000)
        for path, n in m["paths"].items():
            for i in range(n):
                self.assertTrue(os.path.isfile(os.path.join(self.out, "data", f"{X.slug(path)}-{i}.json")), path)

    def test_saved_responses_are_found_by_key(self):
        st = self.lookup("/api/state")
        self.assertTrue(st["loaded"])
        self.assertEqual(st["summary"]["records"], self.man["records"])
        with open(os.path.join(self.out, "data", "records-index.json"), encoding="utf-8") as f:
            ix = json.load(f)
        self.assertEqual(len(ix["events"]), self.man["records"])
        self.assertEqual(len(ix["find"]), len(ix["events"]))
        rid = ix["events"][0]["id"]
        self.assertEqual(self.lookup("/api/event?id=" + rid)["id"], rid)
        a = ix["actors"][0]["actor"]
        self.assertIsNotNone(self.lookup(X.request_url("/api/actor", {"a": a})))

    def test_app_is_copied_and_switched(self):
        for f in ("index.html", "core.js", "app.css", "static.js", "static.css", "views/overview.js"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, f)), f)
        with open(os.path.join(self.out, "index.html"), encoding="utf-8") as f:
            self.assertIn('name="st-static"', f.read())

    def test_nothing_from_this_machine_is_in_it(self):
        home = os.path.expanduser("~")
        for root, _, files in os.walk(self.out):
            for name in files:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                    text = f.read()
                self.assertNotIn(home, text, name)
                self.assertNotIn("st-export-home-", text, name)
        self.assertEqual(self.lookup("/api/x/case")["case"]["items"], [], "a case file saved on this machine must not be exported")

    def test_no_file_jekyll_would_drop(self):
        for root, dirs, files in os.walk(self.out):
            for name in dirs + files:
                self.assertFalse(name.startswith(("_", ".", "#")) or name.endswith("~"), name)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_static_js_answers_like_the_server(self):
        from agenttrace import insight
        from agenttrace.session import Session
        s = Session()
        s.load(X.DATASETS["demo"]["path"], X.DATASETS["demo"]["pack"], {}, "demo_swarm")
        rid, last = s.events[0].id, s.events[-1].id
        actor = next(a for a in s.by_actor if not a.startswith("run:"))
        cases = [
            ("/api/events?limit=50", lambda: s.search("", "", "", "", "", False, 0, 50, "")),
            ("/api/events?q=board&limit=20&offset=5", lambda: s.search("board", "", "", "", "", False, 5, 20, "")),
            ("/api/events?kind=payload&channels=1&limit=10", lambda: s.search("", "payload", "", "", "", True, 0, 10, "")),
            ("/api/events?actor=" + actor.replace(" ", "+") + "&limit=30", lambda: s.search("", "", actor, "", "", False, 0, 30, "")),
            ("/api/events?hour=2026-07-03+01..2026-07-03+05&limit=500", lambda: s.search("", "", "", "", "", False, 0, 500, "2026-07-03 01..2026-07-03 05")),
            ("/api/pairs?limit=50", lambda: s.pairs("", True, 0, 50)),
            ("/api/pairs?q=cred&all=1&limit=500", lambda: s.pairs("cred", False, 0, 500)),
            ("/api/list?name=channels&q=&offset=0&limit=200", lambda: s.listing("channels", "", 0, 200)),
            ("/api/list?name=identities&q=cred+1&offset=1&limit=7", lambda: s.listing("identities", "cred 1", 1, 7)),
            ("/api/search?q=cred", lambda: insight.omni(s, "cred")),
            ("/api/search?q=" + rid[:6], lambda: insight.omni(s, rid[:6])),
            ("/api/search?q=", lambda: insight.omni(s, "")),
            ("/api/event?id=" + rid, lambda: s.trace(rid)),
            ("/api/event?lite=1&id=" + rid, lambda: s.trace(rid, text_limit=600)),
        ]
        extra = [{"path": "/api/event?id=" + last}, {"path": "/api/x/case", "opts": {"method": "POST", "body": "{}"}},
                 {"path": "/api/list?name=nope"}]
        harness = os.path.join(os.path.dirname(self.out), "harness.js")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(NODE_HARNESS)
        r = subprocess.run([NODE, harness, self.out, json.dumps([{"path": p} for p, _ in cases] + extra)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        got = json.loads(r.stdout)
        for (path, want), g in zip(cases, got):
            self.assertIn("ok", g, f"{path}: {g}")
            self.assertEqual(g["ok"], json.loads(json.dumps(want(), default=str)), path)
        not_saved, post, no_list, keys = got[len(cases):]
        self.assertIn("not saved in the hosted demo", not_saved["error"])
        self.assertEqual(post["error"], X.STATIC_MESSAGE)
        self.assertIn("no list named", no_list["error"])
        for (path, _), (key, h) in zip(cases, keys["keys"]):
            self.assertEqual(key, X.canon(*X.parse(path)), path)
            self.assertEqual(h, X.fnv(key), path)


class StoryBuilderTests(unittest.TestCase):
    def test_dig(self):
        d = {"signs": [{"key": "a.b: c", "after": {"time": "2026-07-12 07:47"}}, {"key": "x"}], "list": [1, 2, 3], "n": {"m": 4}}
        self.assertEqual(B.dig(d, "signs[key=a.b: c].after.time"), "2026-07-12 07:47")
        self.assertEqual(B.dig(d, "list.#"), 3)
        self.assertEqual(B.dig(d, "list.1"), 2)
        self.assertEqual(B.dig(d, "n.m"), 4)
        with self.assertRaises(KeyError):
            B.dig(d, "signs[key=zzz].after")

    def test_formats(self):
        self.assertEqual(B.fmt_value(189579, "int"), "189,579")
        self.assertEqual(B.fmt_value(0.895, "pct"), "90%")
        self.assertEqual(B.fmt_value(0.083, "pct"), "8%")
        self.assertEqual(B.fmt_value("2026-07-12 07:47", "time"), "Jul 12 07:47")
        self.assertEqual(B.fmt_value(5.76, "h1"), "5.8")
        self.assertEqual(B.short("[CREDENTIAL 169]"), "cred 169")
        self.assertEqual(B.short("run:R0005427"), "run R0005427")
        self.assertEqual(B.place_label("hf_dataset:[HF REPO 646]"), "Hugging Face dataset HF REPO 646")

    def test_snippet_is_bounded_and_hosts_are_masked(self):
        t = {"text": "x" * 50 + " fetch('https://cache.corp-registry.example.org/a/b/zzBOARD') and https://huggingface.co/datasets/x " + "y" * 400,
             "why": [{"type": "place", "s": 60, "e": 90}]}
        s = B.snippet_of(t)
        self.assertLessEqual(len(s), B.SNIPPET_MAX)
        self.assertIn("[HOST]", s)
        self.assertNotIn("corp-registry", s)
        self.assertIn("huggingface.co", s)

    def _fake(self):
        story = {"slug": "s", "title": "T", "dek": "D {n}", "order": 1,
                 "body": [{"h": "H"}, {"p": "Before [[c1|claim {n} at {rec:R1.time} by {rec:R1.actor}]] after."}],
                 "claims": {"c1": {"evidence": "E {n}", "records": [{"id": "R1", "note": "the write"}], "figures": ["n"]}}}
        bundle = {"schema": 1, "story": "s", "snippets": "off", "citation": dict(B.CITATION, text=B.CITATION_TEXT),
                  "produced_by": {"tool": "Swarm Tracer", "version": "9.9.9", "pack": "p", "agent_rule": "estimate", "dataset": "d.csv", "records": 10},
                  "figures": {"n": {"value": 24, "text": "24", "as": "int", "from": "/api/state", "path": "summary.flow.deliveries", "label": "messages"}},
                  "records": {"R1": {"id": "R1", "kind": "payload", "time": "2026-07-10 11:51", "time_estimated": True, "time_source": "estimated",
                                     "actor": "[CREDENTIAL 169]", "actor_kind": "token", "agent": None, "intent": "hf_read", "text_length": 427,
                                     "judged": [{"op": "read", "place": "hf_dataset:[HF REPO 1]", "place_label": "Hugging Face dataset HF REPO 1", "in_text": True}],
                                     "messages": [], "viewer": B.CITATION["viewer"].format(id="R1")}},
                  "findings": {}}
        return story, bundle

    def test_page_reads_well_without_snippets(self):
        story, bundle = self._fake()
        page = B.render_story(story, bundle, [story])
        self.assertIn('data-v="n">24</span>', page)
        self.assertIn('data-v="rec:R1.time">Jul 10 11:51</span>', page)
        self.assertIn(">cred 169</span>", page)
        self.assertIn('href="https://swarmtraces.org/viewer/#/row/R1"', page)
        self.assertIn("Text not reproduced here", page)
        self.assertNotIn("<blockquote", page)
        self.assertIn("estimated", page)
        self.assertIn(B.CITATION["title"], page)
        self.assertIn("Swarm Tracer 9.9.9", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("onclick", page)
        self.assertIn('<script src="../story.js"></script>', page)

    def test_page_with_snippets_shows_the_excerpt(self):
        story, bundle = self._fake()
        bundle["snippets"] = "on"
        bundle["records"]["R1"]["snippet"] = "fetch(u,{headers:{Authorization:'Bearer [CREDENTIAL 169]'}})"
        page = B.render_story(story, bundle, [story])
        self.assertIn("<blockquote", page)
        self.assertIn("Bearer [CREDENTIAL 169]", page)
        self.assertNotIn("Text not reproduced here", page)

    def test_unknown_placeholder_or_claim_fails(self):
        story, bundle = self._fake()
        story["body"][1]["p"] = "[[c1|x {missing}]]"
        with self.assertRaises(SystemExit):
            B.render_story(story, bundle, [story])
        story, bundle = self._fake()
        story["body"][1]["p"] = "[[c9|x]]"
        with self.assertRaises(SystemExit):
            B.render_story(story, bundle, [story])

    @unittest.skipUnless(os.path.isdir(os.path.join(ROOT, "docs")), "needs the source checkout (docs/ is not in an installed copy)")
    def test_committed_stories_hold_no_numbers(self):
        for s in B.load_stories():
            for b in s["body"]:
                text = B.plain(b.get("p") or b.get("note") or b.get("h") or "")
                self.assertNotRegex(B.PLACEHOLDER.sub("", text), r"\d", f"{s['slug']}: numbers come from the dataset, not the story file")


if __name__ == "__main__":
    unittest.main()

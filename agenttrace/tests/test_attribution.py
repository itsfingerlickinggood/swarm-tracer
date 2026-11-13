"""Attribution of anonymous runs: evidence rules, holdout scoring and endpoint shapes."""
import json
import os
import tempfile
import unittest
from collections import Counter

from agenttrace import attribution, groundtruth
from agenttrace.session import Session


def _row(rid, text):
    return json.dumps({"id": rid, "kind": "payload", "parent": None, "text": text})


def _auth(n):
    return f"headers: {{'Authorization': 'Bearer [CREDENTIAL {n}]'}}"


def _styled_trace(path):
    """Two named actors with their own rare material, anonymous copies of it, and a pair of
    anonymous runs that share material with nobody named."""
    rows, n = [], [0]

    def add(text):
        n[0] += 1
        rows.append(_row(f"R{n[0]:04d}", text))
        return f"R{n[0]:04d}"
    out = {}
    # actor 7: three threads, each with its own pair of rare strings, plus a common helper
    a7 = [("zebraQueueAlpha", "[SERVICE 9 URL 41]"), ("quokkaLedgerBeta", "[SERVICE 9 URL 42]"), ("ibexRouterGamma", "[SERVICE 9 URL 43]")]
    for i, (name, url) in enumerate(a7):
        for _ in range(2):
            add(f"const {name} = await fetch('{url}', {{{_auth(7)}}}); console.log('{name}-done', {i});")
    # actor 8: its own material
    for name, url in [("heronCacheDelta", "[SERVICE 4 URL 11]"), ("lemurSchemaEpsilon", "[SERVICE 4 URL 12]")]:
        for _ in range(2):
            add(f"var {name} = new XMLHttpRequest(); {name}.open('GET', \"{url}\"); /* {_auth(8)} */ {name}.send();")
    # anonymous: uses all three of actor 7's rare names -> high
    out["high"] = add("const zebraQueueAlpha = 1, quokkaLedgerBeta = 2, ibexRouterGamma = 3; "
                      "await fetch('[SERVICE 9 URL 41]'); await fetch('[SERVICE 9 URL 42]'); await fetch('[SERVICE 9 URL 43]');")
    # anonymous: two of them -> medium
    out["medium"] = add("const zebraQueueAlpha = 1, quokkaLedgerBeta = 2; console.log(zebraQueueAlpha + quokkaLedgerBeta);")
    # anonymous: one rare name seen in two of actor 8's threads -> low
    out["low"] = add("var heronCacheDelta = 5; console.log('value', heronCacheDelta);")
    # anonymous: nothing rare in common with anyone
    out["none"] = add("console.log('hello world', 12345);")
    # anonymous pair sharing four rare features of their own
    for _ in range(2):
        out.setdefault("pair", []).append(add(
            "const walrusTensorZeta = '[PROXY 3 URL 77]', ospreyLexerEta = '[PROXY 3 URL 78]'; console.log(walrusTensorZeta, ospreyLexerEta);"))
    # filler so nothing above is rare only because the file is tiny
    for i in range(70):
        add(f"const filler = await fetch('https://example.org/'); var request = new XMLHttpRequest(); request.open('GET', 'x'); "
            f"request.send(); console.log('filler number', 'value', {i}); // headers Authorization Bearer")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return out


class AttributionRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "trace.jsonl")
        cls.ids = _styled_trace(path)
        cls.s = Session()
        cls.s.load(path, "code_traces.json", {}, "styled")
        cls.out = attribution.attribution(cls.s)
        cls.state = {"session": cls.s}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def link(self, key):
        return attribution.run_detail(self.s, "run:" + self.ids[key])

    def test_bands(self):
        hi, me, lo, no = self.link("high"), self.link("medium"), self.link("low"), self.link("none")
        self.assertEqual((hi["band"], hi["actor"]), ("high", "[CREDENTIAL 7]"))
        self.assertEqual((me["band"], me["actor"]), ("medium", "[CREDENTIAL 7]"))
        self.assertEqual((lo["band"], lo["actor"]), ("low", "[CREDENTIAL 8]"))
        self.assertIsNone(no["band"])
        self.assertTrue(any(e["direct"] and e["token"] == "zebraQueueAlpha" for e in hi["evidence"]))
        for e in hi["evidence"]:
            for snip in (e.get("here"), (e.get("there") or {}).get("snippet")):
                self.assertLessEqual(len(snip or ""), attribution.QUOTE + 2)

    def test_high_needs_direct_items(self):
        res = self.s._attr_res
        for u, ln in res["links"].items():
            if ln["band"] == "high":
                self.assertGreaterEqual(ln["direct"], attribution.HIGH_GROUPS)
                self.assertIsNone(ln["conflict"])

    def test_cluster_of_anonymous_runs(self):
        a, b = self.ids["pair"]
        d = attribution.run_detail(self.s, "run:" + a)
        self.assertIsNone(d["actor"])
        self.assertEqual(d["cluster"]["runs"], 2)
        self.assertEqual(d["cluster"]["mates"][0]["id"], "run:" + b)
        cl = [c for c in self.out["clusters"] if "run:" + a in c["members"]]
        self.assertEqual(len(cl), 1)
        self.assertIsNone(cl[0]["actor"])

    def test_summary_shape_and_counts(self):
        o = self.out
        for k in ("runs", "actions", "actions_total", "named_actions", "bands", "clusters", "bubbles", "evidence_kinds",
                  "actors", "holdout", "method", "caveat", "examples", "known_share_before"):
            self.assertIn(k, o)
        self.assertEqual(sum(o["bands"][b]["runs"] for b in ("high", "medium", "low", "unattributed")), o["runs"])
        self.assertEqual(o["actions"] + o["named_actions"], o["actions_total"])
        self.assertEqual(o["bands"]["high"]["runs"], 1)
        self.assertGreaterEqual(o["bands"]["unattributed"]["runs"], 71)
        json.dumps(o)

    def test_endpoints(self):
        get = attribution.GET
        self.assertIs(get["attribution"](self.state, {}), self.out)          # cached on the session
        d = get["attribution_run"](self.state, {"id": "run:" + self.ids["high"]})
        self.assertEqual(d["band"], "high")
        json.dumps(d)
        with self.assertRaises(LookupError):
            get["attribution"]({"session": None}, {})
        with self.assertRaises(ValueError):
            get["attribution_run"](self.state, {})
        with self.assertRaises(LookupError):
            get["attribution_run"](self.state, {"id": "run:nope"})

    def test_own_token_is_never_evidence(self):
        hide = attribution._hide_half(self.s, 1, share=1.0)
        res = attribution._attribute(self.s, hide)
        for u in hide:
            self.assertFalse(any(k[0] == "credential" for k in res["unit_feats"][u]))


class SecondPassAndFamilies(unittest.TestCase):
    """Place evidence, the learned weights and cut-offs, template families and resolve()."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "trace.jsonl")
        cls.ids = _styled_trace(path)
        cls.s = Session()
        cls.s.load(path, "code_traces.json", {}, "styled2")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_place_evidence_names_the_only_named_actor(self):
        s = self.s
        named = "R0001"                      # a record of actor 7
        anon = self.ids["none"]              # no first-pass link
        s._attr_pt = {"unit_ch": {s.res["_root"][named]: {"place:board:zzA"}, s.res["_root"][anon]: {"place:board:zzA"}},
                      "ch_n": {"place:board:zzA": 2}}
        try:
            res = attribution._attribute(s)
            ev = attribution._evidence(s, res, frozenset(), None)
            u = s.res["_root"][anon]
            self.assertIn(u, ev)
            top, rival = attribution._top(ev[u])
            self.assertEqual(top, s.actor[named][0])
            self.assertEqual(ev[u][top]["place"], 1)
            self.assertEqual(rival, 0.0)
            # a place that too many runs touch is not specific
            s._attr_pt["ch_n"]["place:board:zzA"] = attribution.PLACE_MAX + 1
            self.assertNotIn(u, attribution._evidence(s, res, frozenset(), None))
        finally:
            del s._attr_pt

    def test_fit_and_cutoffs(self):
        rows = []
        for i in range(200):
            good = i % 4 != 0
            c = Counter(place=1 if good else 0, pre=2 if good else 0, combo=1)
            rows.append((attribution._vec(c, 0.0), 1 if (good or i % 20 == 0) else 0))
        w = attribution._fit(rows)
        hi = attribution._prob(w, attribution._vec(Counter(place=1, pre=2, combo=1), 0.0))
        lo = attribution._prob(w, attribution._vec(Counter(combo=1), 0.0))
        self.assertGreater(hi, lo)
        cuts = attribution._cutoffs([(attribution._prob(w, x), ok) for x, ok in rows], {"high": 0.9, "medium": 0.8, "low": 0.5})
        self.assertIsNotNone(cuts["high"])
        # too few rows: no model, no extra links
        self.assertEqual(attribution._extra_links(self.s, {"links": {}, "unit_recs": {}}, frozenset(), None,
                                                  {"weights": None, "cuts": {}}), {})

    def test_template_families_do_not_chain(self):
        # 30 copies of one masked program, each with its own number, plus a block that shares rare constants
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            rows = [_row(f"F{i:03d}", f"stage {i} of the relay: upload block [ENCODED BLOB {i}] to the cache now please") for i in range(30)]
            for i in range(6):
                rows.append(_row(f"G{i:03d}", "run the nightly relay job: send block [SERVICE 5 URL 1] and [SERVICE 5 URL 2] "
                                              f"and [SERVICE 5 URL 3] to the cache, attempt {i}"))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(rows) + "\n")
            s = Session()
            s.load(path, "code_traces.json", {}, "fam")
            res = attribution._attribute(s)
            tf = attribution.template_families(s, res)
        self.assertGreaterEqual(tf["families"], 1)
        top = tf["top"][0]
        self.assertEqual(top["records"], 30)           # the numbered blob does not split the family
        self.assertEqual(top["clusters"], 0)           # nothing rare is shared, nothing is chained
        self.assertLessEqual(len(top["snippet"]), attribution.QUOTE + 2)
        json.dumps(tf)

    def test_resolve_labels_every_action(self):
        out = attribution.resolve(self.s)
        self.assertEqual(set(out), set(attribution._base(self.s)["acts"]))
        self.assertEqual(out["R0001"]["band"], "named")
        anon = out[self.ids["high"]]
        self.assertEqual((anon["band"], anon["via"]), ("high", "run link"))
        self.assertIsNone(out[self.ids["none"]]["actor"])
        self.assertIs(attribution.resolve(self.s), out)

    def test_summary_before_after(self):
        o = attribution.attribution(self.s)
        self.assertEqual(sum(o["bands_before"].values()), o["runs"])
        for b in ("high", "medium", "low"):
            self.assertGreaterEqual(o["bands"][b]["runs"], o["bands_before"][b])
        self.assertIn("template_families", o)
        self.assertIn("bands_first_pass", o["holdout"])
        json.dumps(o)


class AttributionOnSimulatedSwarm(unittest.TestCase):
    """Simulated agents all run the same generated code: a negative control. The method must link few
    hidden runs and must not call any of them high (measured: 0 high links in 1,027 hidden runs)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        groundtruth.make(cls.tmp.name, agents=20, seed=1)
        cls.score = attribution.score_swarms(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_negative_control(self):
        sc = self.score
        self.assertTrue(sc["available"])
        self.assertGreater(sc["hidden_runs"], 30)
        self.assertEqual(sc["bands"]["high"]["links"], 0)
        self.assertLessEqual(sc["coverage"], 0.10)
        for b in ("high", "medium", "low"):
            self.assertEqual(set(sc["bands"][b]), {"links", "correct", "precision", "precision_ci"})
        json.dumps(sc)

    def test_score_endpoint(self):
        out = attribution.GET["attribution_score"]({"session": None}, {"path": self.tmp.name})
        self.assertEqual(out["bands"], self.score["bands"])
        missing = attribution.score_swarms(os.path.join(self.tmp.name, "nowhere"))
        self.assertFalse(missing["available"])


class HoldoutRecoversStyledAgents(unittest.TestCase):
    """A swarm whose agents do have personal material: hidden threads are recovered, and high is right."""

    def test_holdout_precision(self):
        import random
        rng = random.Random(4)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trace.jsonl")
            rows, truth, n = [], {}, 0
            for a in range(12):
                words = [f"ag{a}w{j}{rng.randint(1000, 9999)}helper" for j in range(6)]
                for _ in range(14):
                    n += 1
                    pick = rng.sample(words, 4)
                    rows.append(_row(f"R{n:04d}", f"const {pick[0]} = '{pick[1]}'; function {pick[2]}() {{ return '{pick[3]}'; }} "
                                                   f"fetch('https://example.org/x', {{{_auth(10 + a)}}});"))
                    truth[f"R{n:04d}"] = a
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(rows) + "\n")
            s = Session()
            s.load(path, "code_traces.json", {}, "styled12")
            h = attribution.holdout(s, seeds=(1, 2), big=0)
        self.assertGreater(h["bands"]["high"]["links"], 20)
        self.assertGreaterEqual(h["bands"]["high"]["precision"], 0.95)
        self.assertGreater(h["coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()

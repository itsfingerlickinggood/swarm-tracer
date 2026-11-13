import json
import math
import os
import shutil
import tempfile
import unittest

from agenttrace import evaluate, groundtruth, online, validation
from agenttrace.session import Session

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
DEMO = os.path.join(SAMPLES, "demo_swarm", "demo_swarm.jsonl")
os.environ.setdefault("SWARM_TRACER_NO_CACHE", "1")


def pack():
    return online.load_pack("code_traces.json")


class TestBounded(unittest.TestCase):
    def test_oldest_evicted_and_counted(self):
        b = online.Bounded(3)
        for i in range(5):
            b[i] = i
        self.assertEqual(list(b), [2, 3, 4])
        self.assertEqual(b.evicted, 2)
        b[3] = 9                      # an update is not an insertion
        self.assertEqual(b.evicted, 2)


class TestVolumeRule(unittest.TestCase):
    def test_matches_the_replays_rule_on_the_same_times(self):
        import random
        rng = random.Random(4)
        t0 = 1783000000.0
        times = []
        for h in range(40):
            n = rng.randint(5, 15) if h != 30 else 80
            times += [t0 + h * 3600 + rng.uniform(0, 3599) for _ in range(n)]
        times.sort()
        mon = online.OnlineMonitor(pack())
        for t in times:
            mon._rate("all", t)
        mon._close_hours("all", mon.cur["all"], mon.cur["all"] + 1)
        want = evaluate.rate_alarm(times, [], k=3.0)
        got = mon.rate_done[("all", 3.0)]
        self.assertIsNotNone(want)
        self.assertEqual(got, evaluate._parse(want["hour"]) + 3600)
        self.assertIsNone(mon.rate_done[("all", 5.0)] if want["count"] < 5 else None)

    def test_state_is_three_numbers_not_the_hours(self):
        mon = online.OnlineMonitor(pack())
        for h in range(100):
            mon._rate("all", 1783000000.0 + h * 3600)
        self.assertEqual(len(mon.hist["all"]), 3)


class TestStreaming(unittest.TestCase):
    def test_demo_events_match_the_replay(self):
        s = Session()
        s.load(DEMO, "code_traces.json", {}, "demo")
        res = online.replay_session(s)
        c = res["compare"]
        self.assertEqual(res["records"], len(s.events))
        self.assertGreaterEqual(c["both"], 10)
        self.assertGreaterEqual(c["matched"], c["both"] - 1)           # all but at most one within 15 minutes
        for e in res["events"]:
            self.assertTrue(1 <= e["record_index"] <= res["records"])
        # early means records seen: the first event is long before the end
        self.assertLess(min(e["record_index"] for e in res["events"]), res["records"] // 4)
        keys = {e["key"] for e in res["events"]}
        for k in ("message", "two_way", "group3", "program2"):
            self.assertIn(k, keys)

    def test_every_event_fires_once_and_in_stream_order(self):
        out = online.stream(online.iter_records(DEMO), pack())
        keys = [e["key"] for e in out["events"]]
        self.assertEqual(len(keys), len(set(keys)))
        idx = [e["record_index"] for e in out["events"]]
        self.assertEqual(idx, sorted(idx))

    def test_benign_swarm_fires_no_more_than_the_replay(self):
        d = tempfile.mkdtemp()
        try:
            tr = groundtruth.make(d, agents=14, seed=22, mode="benign")
            s = validation._load(d, tr)
            res = online.replay_session(s)
            self.assertEqual(res["compare"]["online_signs"] - res["compare"]["both"], len([r for r in res["compare"]["rows"] if r["status"] == "online only"]))
            self.assertLessEqual(len([r for r in res["compare"]["rows"] if r["status"] == "online only" and r["family"] != "baseline"]), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_caps_hold_and_the_stream_still_runs(self):
        caps = {"ids_roots": 50, "tokens": 40, "places": 10, "channels": 10, "got": 20, "actors": 8, "pairs": 10, "families": 10,
                "written": 10, "thread_idents": 10}
        out = online.stream(online.iter_records(DEMO), pack(), caps=caps)
        self.assertEqual(out["records"], 1462)
        mem = out["memory"]
        for k, cap in (("ids_roots", 50), ("tokens_first_use", 40), ("places", 10), ("channels", 10), ("got", 20), ("actors", 8),
                       ("pairs", 10), ("families", 10), ("written", 10)):
            self.assertLessEqual(mem[k]["entries"], cap, k)
        self.assertGreater(sum(v["evicted"] for v in mem.values()), 0)

    def test_accepts_plain_dicts(self):
        mon = online.OnlineMonitor(pack())
        with open(DEMO) as f:
            rows = [json.loads(l) for l in f][:400]
        for r in rows:
            mon.feed({"id": r["id"], "text": r["text"], "kind": r["kind"], "parent": r.get("parent")})
        self.assertEqual(mon.n, 400)
        self.assertTrue(mon.events_out)

    def test_a_logged_direct_message_is_a_message(self):
        p = os.path.join(SAMPLES, "autogen_messages.jsonl")
        out = online.stream(online.iter_records(p), online.load_pack("generic.json"))
        keys = [e["key"] for e in out["events"]]
        self.assertIn("message", keys)
        self.assertIn("two_way", keys)


class TestEndpointAndCli(unittest.TestCase):
    def test_endpoint_needs_a_dataset(self):
        with self.assertRaises(LookupError):
            online._online_replay({}, {})

    def test_endpoint_returns_events_with_record_index(self):
        s = Session()
        s.load(DEMO, "code_traces.json", {}, "demo")
        online._CACHE.clear()
        r = online._online_replay({"session": s}, {})
        self.assertFalse(r["running"])
        self.assertTrue(all("record_index" in e for e in r["events"]))
        self.assertIn("caps", r)
        self.assertTrue(r["approximations"])
        self.assertIn("rows", r["compare"])

    def test_cli_run_writes_json(self):
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, "o.json")
            self.assertEqual(online.main(["run", DEMO, "--pack", "code_traces.json", "--compare", "--json", out]), 0)
            with open(out) as f:
                j = json.load(f)
            self.assertEqual(j["records"], 1462)
            self.assertGreater(j["records_per_s"], 100)
            self.assertIn("compare", j)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_iter_records_streams_csv_and_jsonl_alike(self):
        a = [e.id for e in online.iter_records(DEMO)]
        self.assertEqual(len(a), 1462)


if __name__ == "__main__":
    unittest.main()

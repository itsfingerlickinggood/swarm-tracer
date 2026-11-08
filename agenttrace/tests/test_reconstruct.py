"""Known-answer tests for agenttrace.reconstruct on synthetic traces.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import json
import os
import random
import tempfile
import unittest

from agenttrace import analysis, packs, reconstruct
from agenttrace.model import Event, parse_time

BASE = 1783600000  # 2026-07-09 roughly

PACK = {
    "name": "test",
    "action_kinds": ["action"],
    "behaviors": [{"name": "upload", "stage": "exfiltration", "pattern": "UPLOAD"}],
    "identity_patterns": [{"role": "auth", "pattern": r"auth=(\[TOKEN \d+\])"}],
    "variable_identity": {"assign": r"\b([A-Z])=(\[TOKEN \d+\])", "use": r"auth=\{var\}|auth=\b{var}\b"},
    "info_patterns": [{"family": "token", "pattern": r"\[TOKEN \d+\]"}],
    "shared_names": [{"family": "board", "pattern": r"zzBOARD_[A-Z]+"}],
    "intents": [{"name": "write_board", "pattern": "zzBOARD"}, {"name": "upload", "pattern": "UPLOAD"}],
    "harm": ["upload"],
    "time": {"embedded_epoch": True, "window": ["2026-07-01", "2026-07-25"], "min_points": 20, "min_spearman": 0.8},
}


def load_pack(d, overrides=None):
    p = os.path.join(d, "pack.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(dict(PACK, **(overrides or {})), f)
    return packs.load_pack(p)


def ev(i, text, kind="action", parent=None, actor=None, time=None):
    return Event(id=f"E{i:04d}", text=text, kind=kind, parent=parent, actor=actor, time=parse_time(time))


def story():
    """A timed block of actions with known spread, carry and shared-place events."""
    events = []
    for i in range(60):
        t = BASE + i * 600
        text = f"step at {t} auth=[TOKEN 1]"
        if i == 10:
            text = f"at {t} auth=[TOKEN 1] stores [TOKEN 9] for later"      # carries token 9
        if i == 20:
            text = f"at {t} auth=[TOKEN 9] zzBOARD_X"                     # first use of token 9, on a board
        if i == 25:
            text = f"at {t} auth=[TOKEN 1] zzBOARD_X"                     # second identity on the same board
        if i == 40:
            text = f"at {t} auth=[TOKEN 9] UPLOAD"                        # harm
        if i == 50:
            text = f"at {t} A=[TOKEN 7]; auth=A UPLOAD"                   # identity through a variable
        events.append(ev(i, text))
    return events


class TimeTests(unittest.TestCase):
    def test_ordered_block_is_timed_and_shuffled_block_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            pack = load_pack(d)
            good = [ev(i, f"t {BASE + i * 60}") for i in range(40)]
            rng = random.Random(3)
            shuffled = [BASE + i * 60 for i in range(40)]
            rng.shuffle(shuffled)
            bad = [ev(100 + i, f"t {v}", kind="data") for i, v in enumerate(shuffled)]
            times, test = reconstruct.infer_times(good + bad, pack)
            self.assertIn("E0000", times)
            self.assertNotIn("E0100", times)
            blocks = {b["kind"]: b for b in test["blocks"]}
            self.assertTrue(blocks["action"]["timed"])
            self.assertFalse(blocks["data"]["timed"])
            self.assertLess(blocks["action"]["fit_error_hours_median"], 0.1)

    def test_time_field_wins_and_children_inherit(self):
        with tempfile.TemporaryDirectory() as d:
            pack = load_pack(d, {"time": {}})
            a = ev(1, "x", time="2026-07-10T00:00:00Z")
            b = ev(2, "y", kind="data", parent="E0001")
            times, test = reconstruct.infer_times([a, b], pack)
            self.assertEqual(times["E0002"], times["E0001"])
            self.assertEqual(test["source"]["inherited_from_parent"], 1)

    def test_tail_error_limit_rejects_a_block(self):
        with tempfile.TemporaryDirectory() as d:
            pack = load_pack(d, {"time": dict(PACK["time"], max_p90_error_hours=0.0001)})
            events = [ev(i, f"t {BASE + i * 60 + (5000 if i % 5 == 0 else 0)}") for i in range(40)]
            times, test = reconstruct.infer_times(events, pack)
            self.assertFalse(test["blocks"][0]["timed"])


class ReconstructTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.pack = load_pack(cls.d, {"time": dict(PACK["time"], min_points=20)})
        cls.events = story()
        res = analysis.analyze(cls.events, cls.pack)
        cls.rec = reconstruct.reconstruct(cls.events, cls.pack, res)

    def test_identities_found(self):
        ids = {p["identity"] for p in self.rec["identities"]}
        self.assertTrue({"[TOKEN 1]", "[TOKEN 9]"} <= ids)

    def test_identity_through_variable(self):
        self.assertEqual(self.rec["_ids"]["E0050"].get("[TOKEN 7]"), "via_variable")

    def test_stable_token_check(self):
        self.assertGreaterEqual(self.rec["identity_test"]["tokens_used_5_plus"], 1)

    def test_seen_then_used(self):
        items = {r["item"]: r for r in self.rec["seen_then_used"]}
        self.assertIn("[TOKEN 9]", items)
        self.assertEqual(items["[TOKEN 9]"]["first_seen_id"], "E0010")
        self.assertAlmostEqual(items["[TOKEN 9]"]["lead_hours"], 10 * 600 / 3600, places=0)

    def test_carried_edge(self):
        pairs = {(e["from"], e["to"]) for e in self.rec["carried_edges"]}
        self.assertIn(("[TOKEN 1]", "[TOKEN 9]"), pairs)

    def test_shared_place_in_separate_records(self):
        p = {x["place"]: x for x in self.rec["shared_places"]}["zzBOARD_X"]
        self.assertFalse(p["same_record"])
        self.assertEqual(p["identities"], ["[TOKEN 9]", "[TOKEN 1]"])

    def test_replay_shares(self):
        r = {x["signal"]: x for x in self.rec["replay"]}
        self.assertEqual(self.rec["harm_events_timed"], 2)               # E0040 and E0050
        self.assertEqual(r["coordination: two identities use one place"]["harm_share_after"], 1.0)
        self.assertEqual(r["first: upload"]["harm_share_after"], 0.5)     # E0050 comes after E0040

    def test_non_action_records_are_not_identities(self):
        e = ev(900, "auth=[TOKEN 5]", kind="data")
        self.assertEqual(reconstruct.identities_of(e, self.pack), {})


if __name__ == "__main__":
    unittest.main()

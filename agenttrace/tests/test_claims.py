"""Known-answer tests for agenttrace.claims.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import json
import os
import tempfile
import unittest

from agenttrace import analysis, claims, packs, reconstruct
from agenttrace.tests.test_reconstruct import PACK, ev, load_pack

CLAIMS = {"name": "test report", "claims": [
    {"id": "board_use", "section": "Boards", "says": "agents used a board", "patterns": ["zzBOARD_X"],
     "cited": ["E0020", "E0999"]},
    {"id": "absent", "section": "Never happened", "says": "x", "patterns": ["NOT_IN_DATA"], "cited": []},
]}


class ClaimsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        cls.pack = load_pack(d, {"time": dict(PACK["time"], min_points=20)})
        base = 1783600000
        cls.events = [ev(i, f"at {base + i * 600} auth=[TOKEN 1]") for i in range(40)]
        cls.events[20] = ev(20, f"at {base + 20 * 600} auth=[TOKEN 9] zzBOARD_X")
        cls.events[25] = ev(25, f"at {base + 25 * 600} auth=[TOKEN 1] zzBOARD_X")
        p = os.path.join(d, "claims.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(CLAIMS, f)
        cfg = claims.load_claims(p)
        res = analysis.analyze(cls.events, cls.pack)
        rec = reconstruct.reconstruct(cls.events, cls.pack, res)
        cls.out = {r["id"]: r for r in claims.evaluate(cls.events, cls.pack, res, rec, cfg)}

    def test_claim_records_and_order_of_identities(self):
        r = self.out["board_use"]
        self.assertEqual(r["records"], 2)
        self.assertEqual([s["identity"] for s in r["spread"]], ["[TOKEN 9]", "[TOKEN 1]"])

    def test_two_identities_in_separate_records(self):
        self.assertEqual(self.out["board_use"]["two_identities_separately"]["record"], "E0025")

    def test_cited_records(self):
        r = self.out["board_use"]
        self.assertEqual((r["cited_found"], r["cited_matched"], r["cited_timed"]), (1, 1, 1))

    def test_place_spread(self):
        ps = self.out["board_use"]["place_spread"][0]
        self.assertEqual((ps["place"], ps["records"], ps["first_record"]), ("zzBOARD_X", 2, "E0020"))

    def test_absent_claim(self):
        self.assertEqual(self.out["absent"]["records"], 0)
        self.assertIsNone(self.out["absent"]["first_time"])


if __name__ == "__main__":
    unittest.main()

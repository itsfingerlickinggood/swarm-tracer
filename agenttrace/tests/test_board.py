"""The board reconstruction: folder-name types, funnel arithmetic, unnamed writers, endpoint shapes."""
import json
import os
import tempfile
import unittest

from agenttrace import board
from agenttrace.session import Session

BASE = "https://pkg.example.org/artifactory/github-remote-cache/"


def _put(name):
    return f"await fetch('{BASE}{name}/', {{method: 'PUT', body: 'x'}});"


def _get(name):
    return f"await fetch('{BASE}{name}/').then(r => r.text());"


class Types(unittest.TestCase):
    def test_decoding(self):
        cases = {"zzFILE_ARVO1538X_CFG_V1": "file", "zzF_C4V4GZP0": "file", "zzINBOX_ABC123": "mailbox",
                 "zzMAILBOX_X": "mailbox", "zzRESULT_ARC2_NAT": "result", "zzBEACON_X_1": "beacon",
                 "zzCMDC608OCT32": "command", "zzBROWSER_MKCOL_TEST1": "probe", "zzCALLBACK_ROOT1": "stage",
                 "zzMODAL14232P2": "modal", "zzDATA_X_V1": "payload", "zzQQQ9": "other",
                 "board:zzFILE_A_V1": "file"}
        for name, want in cases.items():
            self.assertEqual(board.folder_type(name), want, name)

    def test_stem_groups_versions(self):
        self.assertEqual(board.stem("zzFILE_A_V1"), board.stem("zzFILE_A_V2"))


class Reconstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [
            ("R0001", _put("zzFILE_ALPHA_V1")),            # unnamed writer
            ("R0002", _get("zzFILE_ALPHA_V1")),            # later read by another run: a delivery
            ("R0003", _put("zzRESULT_BETA")),              # written, never read
            ("R0004", _get("zzINBOX_GAMMA")),              # read, no writer seen
            ("R0005", _put("zzFILE_ALPHA_V2")),
            ("R0006", "console.log('nothing about the board here')"),
        ]
        fd, cls.path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rid, text in rows:
                f.write(json.dumps({"id": rid, "kind": "payload", "parent": None, "text": text}) + "\n")
        cls.s = Session()
        cls.s.load(cls.path, "code_traces.json", {}, "board")
        # a tiny trace has too few timestamps to be dated: give the records an order, as a dated trace would
        when = {rid: 1783603749 + 600 * i for i, (rid, _t) in enumerate(rows)}
        cls.s.op_list = [o[:4] + (when[o[6]],) + o[5:] for o in cls.s.op_list]
        cls.b = board.board(cls.s)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_funnel_arithmetic(self):
        f = self.b["funnel"]
        self.assertEqual(f["folders"], 4)
        self.assertEqual((f["written"], f["read"], f["both"]), (3, 2, 1))
        self.assertEqual(f["written_only"], f["written"] - f["both"])
        self.assertEqual(f["read_only"], f["read"] - f["both"])
        self.assertEqual(f["written"] + f["read_only"], f["folders"])
        self.assertEqual((f["writes"], f["reads"]), (3, 2))
        self.assertLessEqual(f["linked"], f["both"])

    def test_unnamed_writers_link(self):
        self.assertEqual(self.b["funnel"]["deliveries"], 1)
        self.assertEqual(self.b["flow"]["deliveries"], 1)
        row = next(r for r in self.b["flow"]["rows"] if r["t"] == "file" and r["l"] != "none" and r["r"] != "none")
        self.assertEqual((row["l"], row["r"], row["n"]), ("anonymous", "anonymous", 1))

    def test_types_and_flow_units(self):
        counts = {t["type"]: t["folders"] for t in self.b["types"]}
        self.assertEqual(counts, {"file": 2, "result": 1, "mailbox": 1})
        self.assertEqual(self.b["other"]["folders"], 0)
        fl = self.b["flow"]
        self.assertEqual(fl["deliveries"] + fl["unread_writes"], self.b["funnel"]["writes"])
        self.assertEqual(sum(r["n"] for r in fl["rows"]), fl["deliveries"] + fl["unread_writes"] + fl["reads_no_writer"])

    def test_timeline_and_summary_shape(self):
        for k in ("hours", "series", "first_appearances", "top_folders", "caveats", "claims", "visible", "seconds"):
            self.assertIn(k, self.b)
        for t, s in self.b["series"].items():
            self.assertEqual(len(s["w"]), len(self.b["hours"]))
        self.assertIs(board.board(self.s), self.b)         # cached on the session

    def test_folder_endpoint(self):
        d = board.folder(self.s, "zzFILE_ALPHA_V1")
        self.assertEqual((d["writes"], d["reads"], d["deliveries_total"]), (1, 1, 1))
        self.assertEqual([o["op"] for o in d["ops"]], ["write", "read"])
        self.assertIn("zzFILE_ALPHA_V2", d["revisions"])
        self.assertTrue(all(len(o["snippet"]) <= 160 for o in d["ops"]))
        with self.assertRaises(LookupError):
            board.folder(self.s, "zzNOPE")

    def test_routes(self):
        st = {"session": self.s}
        self.assertEqual(board.GET["board"](st, {})["funnel"]["folders"], 4)
        self.assertEqual(board.GET["board_folder"](st, {"name": "zzRESULT_BETA"})["type"], "result")
        with self.assertRaises(ValueError):
            board.GET["board_folder"](st, {})


if __name__ == "__main__":
    unittest.main()

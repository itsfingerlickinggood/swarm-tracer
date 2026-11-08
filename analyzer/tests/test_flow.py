"""Unit tests for analyzer/flow.py on small synthetic data.

Run from the project root:
    python3 -m unittest discover -s analyzer/tests -v
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW = os.path.join(HERE, "..", "flow.py")

CONFIG = {
    "name": "test",
    "handles": ["C5", "OTS92", "LIBR11"],
    "handle_families": {"C5": "C5", "OTS92": "OTS92", "LIBR11": "LIBR11"},
    "artifact_patterns": [{"family": "mailbox_board", "pattern": "zz(?:MODAL|FILE)_[A-Za-z0-9_]{0,40}"}],
    "artifact_to_family": {"mailbox_board": None},
    "write_markers": "write|PUT|POST",
    "read_markers": "read|GET|poll",
    "anchors": [],
}

ROWS = [
    # Thread 1: family C5 writes the board.
    {"id": "T1", "text": "C5 writes zzMODAL_BOARD_1 with PUT", "parent_id": ""},
    # Thread 1 child: no handle, inherits the thread's handle.
    {"id": "T1a", "text": "response: stored zzMODAL_BOARD_1", "parent_id": "T1"},
    # Thread 2: family OTS92 reads the same board.
    {"id": "T2", "text": "OTS92 read zzMODAL_BOARD_1 with GET", "parent_id": ""},
    # Thread 3: no shared artifact, one handle only.
    {"id": "T3", "text": "LIBR11 status ok", "parent_id": ""},
    # Thread 4: artifact with no handle at all; unattributed.
    {"id": "T4", "text": "generic note about zzFILE_SOLO_9", "parent_id": ""},
    # Thread 5: the same unattributed artifact in another thread.
    {"id": "T5", "text": "another note about zzFILE_SOLO_9", "parent_id": ""},
]


def run_flow(rows, config, extra=None):
    d = tempfile.mkdtemp()
    csv_path = os.path.join(d, "in.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "text", "parent_id"])
        w.writeheader()
        w.writerows(rows)
    cfg_path = os.path.join(d, "cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    out = os.path.join(d, "out")
    cmd = [sys.executable, "-I", FLOW, csv_path, "--config", cfg_path, "--out", out] + (extra or [])
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_flow(ROWS, CONFIG)
        cls.summary = read_json(os.path.join(cls.out, "flow_summary.json"))
        cls.early = read_json(os.path.join(cls.out, "early_flag.json"))

    def test_handle_edge_between_families(self):
        edges = read_csv(os.path.join(self.out, "edges.csv"))
        pairs = {(e["from_family"], e["to_family"]) for e in edges}
        self.assertIn(("C5", "OTS92"), pairs)

    def test_write_then_read_is_strong(self):
        edges = {(e["from_family"], e["to_family"]): e for e in read_csv(os.path.join(self.out, "edges.csv"))}
        self.assertEqual(edges[("C5", "OTS92")]["strong_write_then_read"], "1")

    def test_thread_inherits_handle(self):
        att = {r["id"]: r for r in read_csv(os.path.join(self.out, "attribution.csv"))}
        self.assertEqual(att["T1a"]["family"], "C5")
        self.assertEqual(att["T1a"]["how"], "thread")

    def test_unattributed_when_no_handle(self):
        att = {r["id"]: r for r in read_csv(os.path.join(self.out, "attribution.csv"))}
        self.assertEqual(att["T4"]["how"], "unattributed")

    def test_no_edge_from_single_family(self):
        edges = read_csv(os.path.join(self.out, "edges.csv"))
        self.assertFalse(any(e["from_family"] == "LIBR11" or e["to_family"] == "LIBR11" for e in edges))

    def test_thread_reuse_detected(self):
        reuse = self.early["rule_thread_reuse"]
        self.assertEqual(reuse["artifacts_reused_across_threads"], 2)  # zzMODAL_BOARD_1 and zzFILE_SOLO_9
        self.assertEqual(reuse["first_reuse_across_threads"]["artifact"], "zzMODAL_BOARD_1")

    def test_family_flag_fires_on_shared_name(self):
        self.assertIsNotNone(self.early["first_shared_artifact"])
        self.assertEqual(self.early["first_shared_artifact"]["id"], "T2")

    def test_report_written(self):
        with open(os.path.join(self.out, "flow_report.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Directed edges between families: 1", text)

    def test_anchor_counts_reported_for_both_rules(self):
        cfg = dict(CONFIG, anchors=["T1", "T2", "T5"])
        out = run_flow(ROWS, cfg)
        early = read_json(os.path.join(out, "early_flag.json"))
        self.assertEqual(early["anchors_checked"], 3)
        # Anchors T1 (row 0), T2 (row 2), T5 (row 5). First family flag is at T2 (row 2).
        self.assertEqual(early["anchors_after_family_flag"], 2)   # T2 and T5
        # First thread reuse is also at T2 (second thread for zzMODAL_BOARD_1).
        self.assertEqual(early["anchors_after_thread_flag"], 2)   # T2 and T5


if __name__ == "__main__":
    unittest.main()

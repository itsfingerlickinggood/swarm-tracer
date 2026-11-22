"""Crosscheck: count deliveries twice, with messages.py and with the separately written refcount.py.

    python3 -m agenttrace.tools.crosscheck                         # big, wiki, demo, benign, samples
    python3 -m agenttrace.tools.crosscheck --datasets demo samples # only these
    python3 -m agenttrace.tools.crosscheck --datasets my=/path/to/file.jsonl::code_traces.json
    python3 -m agenttrace.tools.crosscheck --out reports/integrity/crosscheck.json --threshold 0.10

For each dataset it prints and writes: deliveries found by both, only by messages.py (A), only by refcount.py
(B), each with its place and record ids; the same for full-body overwrites and for single operations (place,
record, write/read). On the Swarm Traces release every delivery also carries the hand-audit label from
agenttrace/claims/audited_links.json as a third opinion (the labels, not benchmark.py's own second method).
The written-content test (R38) is compared too: how many deliveries pass in each implementation, on how many
shared deliveries the verdict is the same, and how many pass by the reader's later output (R38b). It is reported
and does not enter the disagreement figure, which is about deliveries.

Disagreement for a dataset is (only A + only B) / (both + only A + only B) over deliveries; 0 when both find
none. The exit code is 1 when any dataset is above --threshold (default 0.10), else 0.

Nothing is cached and no server is started. Datasets that are not on disk are skipped and listed.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "agenttrace")
THRESHOLD = 0.10
DATA_EXT = (".json", ".jsonl", ".csv", ".tsv", ".txt", ".log")


def dataset_specs(names):
    """(label, path, pack) for big, wiki, demo, benign, samples, or [label=]path[::pack]. Same names as tools/smoke.py."""
    out = []
    for n in names:
        if n == "big":
            out.append(("Swarm Traces (redacted_columns.csv)", os.path.join(ROOT, "redacted_columns.csv"), "code_traces.json"))
        elif n == "wiki":
            out.append(("collusion.wiki logs", os.path.join(ROOT, "full-wiki-logs"), None))
        elif n == "demo":
            out.append(("demo swarm", os.path.join(PKG, "samples", "demo_swarm"), None))
        elif n == "benign":
            out.append(("benign swarm", os.path.join(PKG, "samples", "benign_swarm"), None))
        elif n == "samples":
            sd = os.path.join(PKG, "samples")
            for f in sorted(os.listdir(sd)):
                if os.path.splitext(f)[1] in DATA_EXT:
                    out.append(("sample " + f, os.path.join(sd, f), None))
        else:
            label, _, rest = n.rpartition("=")
            path, _, pack = rest.partition("::")
            out.append((label or os.path.basename(path.rstrip("/")), os.path.abspath(path), pack or None))
    return out


def analyze(path, pack_file):
    """Load and analyze like the app does, without the disk cache. Returns (events, pack, rec, res, flow, pack name)."""
    from agenttrace.session import Session
    s = Session()
    s.path = path
    s._analyze(path, pack_file, {}, os.path.basename(path))
    return s


def _audit_labels():
    try:
        with open(os.path.join(PKG, "claims", "audited_links.json"), encoding="utf-8") as f:
            audit = json.load(f)
        return {(r["write_id"], r["read_id"]): r["label"] for r in audit["links"]}, (audit.get("dataset") or {}).get("records")
    except (OSError, ValueError, KeyError):
        return {}, None


def compare(s, labels=None):
    """Both counts on a loaded session, and where they differ."""
    from agenttrace import messages, refcount
    t0 = time.time()
    ref = refcount.count(s.events, s.pack, s.rec, s.res)
    ref_s = time.time() - t0
    main_d = {(d["channel"], d["write_id"], d["read_id"]): d for d in s.flow["_deliveries"]}
    ref_d = {(d["place"], d["write_id"], d["read_id"]): d for d in ref["deliveries"]}
    labels = labels or {}

    def row(k, a, b):
        d = a or b
        out = {"place": k[0], "write_id": k[1], "read_id": k[2], "from": d["from"], "to": d["to"],
               "grade_A": a.get("grade") if a else None, "grade_B": b.get("grade") if b else None}
        if labels:
            out["audit_label"] = labels.get((k[1], k[2]), "not audited")
        return out
    both = sorted(set(main_d) & set(ref_d))
    only_a = sorted(set(main_d) - set(ref_d))
    only_b = sorted(set(ref_d) - set(main_d))
    union = len(both) + len(only_a) + len(only_b)
    main_o = {(d["channel"], d["write_id"], d["read_id"]) for d in s.flow.get("_overwrites", [])}
    ref_o = {(d["place"], d["write_id"], d["read_id"]) for d in ref["overwrites"]}
    ops_a = {(o[0], o[6], o[1]) for o in messages.channel_ops(s.events, s.pack, s.rec, s.res) if not o[0].startswith("inbox:")}
    ops_b = {(o.place, o.rid, o.op) for o in ref["_ops"]}
    named = lambda rows: sum(1 for d in rows if not d["from"].startswith("run:") and not d["to"].startswith("run:"))
    grade_same = sum(1 for k in both if main_d[k].get("grade") == ref_d[k].get("grade"))
    # the written-content test (R38): how many deliveries pass in each implementation, and by which statement
    later = lambda d: d.get("content_how") == "in the reader's later output"
    passes = lambda k, d: k[0].startswith("inbox:") or bool(d.get("uses_content"))     # a logged direct message passes as it stands
    used_differs = sorted(k for k in both if passes(k, main_d[k]) != passes(k, ref_d[k]))
    content = {"A_pass": s.flow["deliveries_reader_uses_content"], "B_pass": ref["deliveries_reader_uses_content"],
               "same_verdict": len(both) - len(used_differs), "of": len(both),
               "later_output_R38b": {"A": sum(1 for d in main_d.values() if later(d)), "B": sum(1 for d in ref_d.values() if later(d)),
                                     "both": sum(1 for k in both if later(main_d[k]) and later(ref_d[k]))},
               "verdict_differs": [{"place": k[0], "write_id": k[1], "read_id": k[2], "A": main_d[k].get("content_how"),
                                    "B": ref_d[k].get("content_how")} for k in used_differs[:200]]}
    return {
        "records": len(s.events), "pack": s.pack.name,
        "A": {"deliveries": len(main_d), "named": named(main_d.values()), "overwrites": len(main_o), "operations": len(ops_a),
              "order_unknown": s.flow["deliveries_order_unknown"], "repeat_reads": s.flow["repeat_reads"],
              "same_program": s.flow["reads_dropped_as_same_program"]},
        "B": {"deliveries": len(ref_d), "named": named(ref_d.values()), "overwrites": len(ref_o), "operations": len(ops_b),
              "order_unknown": ref["order_unknown"], "repeat_reads": ref["repeat_reads"], "same_program": ref["same_program"],
              "seconds": round(ref_s, 2)},
        "both": len(both), "only_A": len(only_a), "only_B": len(only_b),
        "disagreement": round((len(only_a) + len(only_b)) / union, 4) if union else 0.0,
        "grade_agreement": {"same": grade_same, "of": len(both)},
        "content_test": content,
        "overwrites": {"both": len(main_o & ref_o), "only_A": len(main_o - ref_o), "only_B": len(ref_o - main_o)},
        "operations": {"both": len(ops_a & ops_b), "only_A": len(ops_a - ops_b), "only_B": len(ops_b - ops_a)},
        "deliveries_both": [row(k, main_d[k], ref_d[k]) for k in both],
        "deliveries_only_A": [row(k, main_d[k], None) for k in only_a],
        "deliveries_only_B": [row(k, None, ref_d[k]) for k in only_b],
        "operations_only_A": [list(x) for x in sorted(ops_a - ops_b)[:400]],
        "operations_only_B": [list(x) for x in sorted(ops_b - ops_a)[:400]],
    }


def run(names, threshold=THRESHOLD, out=None, stream=sys.stdout, list_cap=40):
    labels, audit_records = _audit_labels()
    results, skipped = [], []
    for label, path, pack in dataset_specs(names):
        if not os.path.exists(path):
            skipped.append({"dataset": label, "path": path, "why": "not on disk"})
            print(f"-- {label}: skipped (not on disk)", file=stream)
            continue
        t0 = time.time()
        try:
            s = analyze(path, pack)
        except Exception as e:                     # a sample the loader refuses is reported, not fatal
            skipped.append({"dataset": label, "path": path, "why": f"{type(e).__name__}: {e}"})
            print(f"-- {label}: skipped ({type(e).__name__}: {e})", file=stream)
            continue
        use_labels = labels if audit_records and len(s.events) == audit_records else None
        r = compare(s, use_labels)
        r["dataset"], r["path"], r["seconds"] = label, os.path.relpath(path, ROOT), round(time.time() - t0, 1)
        r["over_threshold"] = r["disagreement"] > threshold
        results.append(r)
        print(f"-- {label} ({r['records']:,} records, pack {r['pack']})", file=stream)
        print(f"   deliveries: A {r['A']['deliveries']}, B {r['B']['deliveries']}; both {r['both']}, only A {r['only_A']}, "
              f"only B {r['only_B']}; disagreement {100 * r['disagreement']:.1f}%{'  ABOVE THRESHOLD' if r['over_threshold'] else ''}", file=stream)
        print(f"   named: A {r['A']['named']}, B {r['B']['named']}; grades equal on {r['grade_agreement']['same']} of {r['grade_agreement']['of']} shared", file=stream)
        c = r["content_test"]
        print(f"   reader uses what was written (R38): A {c['A_pass']}, B {c['B_pass']}; same verdict on {c['same_verdict']} of {c['of']} shared; "
              f"by the reader's later output (R38b): A {c['later_output_R38b']['A']}, B {c['later_output_R38b']['B']}, both {c['later_output_R38b']['both']}", file=stream)
        o, p = r["overwrites"], r["operations"]
        print(f"   overwrites: both {o['both']}, only A {o['only_A']}, only B {o['only_B']}; "
              f"operations: both {p['both']}, only A {p['only_A']}, only B {p['only_B']}", file=stream)
        for side in ("only_A", "only_B"):
            rows = r["deliveries_" + side]
            for d in rows[:list_cap]:
                extra = f"  [audit: {d['audit_label']}]" if "audit_label" in d else ""
                print(f"   {side.replace('_', ' ')}: {d['write_id']} -> {d['read_id']}  {d['place']}{extra}", file=stream)
            if len(rows) > list_cap:
                print(f"   ... {len(rows) - list_cap} more {side.replace('_', ' ')} in the JSON", file=stream)
    worst = max((r["disagreement"] for r in results), default=0.0)
    summary = {"about": "deliveries counted by agenttrace/messages.py (A) and by agenttrace/refcount.py (B); see docs/counting-rule.md",
               "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "threshold": threshold,
               "worst_disagreement": worst, "passed": worst <= threshold, "skipped": skipped, "datasets": results}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print(f"wrote {out}", file=stream)
    print(f"worst disagreement {100 * worst:.1f}% (threshold {100 * threshold:.0f}%): {'ok' if worst <= threshold else 'FAILED'}", file=stream)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count deliveries with messages.py and with refcount.py and list where they differ.")
    ap.add_argument("--datasets", nargs="*", default=["big", "wiki", "demo", "benign", "samples"],
                    help="big, wiki, demo, benign, samples, or [label=]path[::pack]")
    ap.add_argument("--threshold", type=float, default=THRESHOLD, help="largest tolerated disagreement per dataset (default 0.10)")
    ap.add_argument("--out", help="write the full result as JSON here")
    a = ap.parse_args(argv)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    return 0 if run(a.datasets, a.threshold, a.out)["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Benchmark: the hand-audited message links of the Swarm Traces release.

    python3 -m agenttrace.benchmark run redacted_columns.csv [--out DIR] [--pack code_traces.json]

agenttrace/claims/audited_links.json holds every link between two named tokens that v1.1.0 reported on
the release (166) and every link the code reported at audit time that v1.1.0 did not, each read by hand
and labelled: a true message, or one of the ways a link can be false (the "write" only read the place
and posted elsewhere; it was an LFS download or a Python urlopen; write and read are on different
repositories; the "read" is itself a write), or unclear.

run loads the data with the current code, takes its links between named tokens and scores them against
those labels: precision and recall against the true_message labels (unclear left out and counted), with
Wilson 95% intervals, the count per label for each version, and the regressions: true links now missed,
false links now reported, and links the current code reports that nobody has audited yet.

Recall here is against the true links in the audited pool, not against every true message in the data:
only links some version of the tool reported were ever read. One labeller, tool-assisted.

GET /api/x/benchmark returns the same for the loaded session when it is the Swarm Traces release (same
record count, audited records present); otherwise {"applies": false}.
"""
import argparse
import json
import os
import sys
import threading

from .labels import wilson

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_PATH = os.path.join(HERE, "claims", "audited_links.json")
TRUE, UNCLEAR, UNAUDITED = "true_message", "unclear", "not_audited"
LABEL_ORDER = ["true_message", "false_write", "false_write_lfs_or_urlopen", "different_repo", "comment_only",
               "read_not_a_read", "unclear"]
SHORT = {"true_message": "true message", "false_write": "read, then posted elsewhere",
         "false_write_lfs_or_urlopen": "LFS download, urlopen or query POST", "different_repo": "different repositories",
         "comment_only": "named in a comment", "read_not_a_read": "the read is a write", "unclear": "unclear",
         "not_audited": "not audited yet"}
REQUIRED = ("write_id", "read_id", "from", "to", "label", "reason", "reported_v110", "reported_now",
            "write_snippet", "read_snippet")
_LOCK = threading.Lock()


def load_audit(path=None):
    with open(path or AUDIT_PATH, encoding="utf-8") as f:
        return json.load(f)


def check_audit(audit):
    """Problems with the audited file's structure (an empty list when it is sound)."""
    bad = []
    for k in ("about", "made", "how", "labelled_by", "labels", "counts", "links", "dataset"):
        if k not in audit:
            bad.append(f"missing header field {k}")
    seen = set()
    counts = {}
    for i, r in enumerate(audit.get("links", [])):
        for k in REQUIRED:
            if k not in r:
                bad.append(f"link {i}: missing {k}")
        key = (r.get("write_id"), r.get("read_id"))
        if key in seen:
            bad.append(f"link {i}: duplicate {key}")
        seen.add(key)
        if r.get("label") not in audit.get("labels", {}):
            bad.append(f"link {i}: unknown label {r.get('label')}")
        if not (r.get("reported_v110") or r.get("reported_now")):
            bad.append(f"link {i}: reported by no version")
        for k in ("write_snippet", "read_snippet"):
            if len(r.get(k) or "") > 120:
                bad.append(f"link {i}: {k} longer than 120 characters")
        if len(r.get("reason") or "") > 220 or not r.get("reason"):
            bad.append(f"link {i}: reason missing or too long")
        counts[r.get("label")] = counts.get(r.get("label"), 0) + 1
    for k, n in audit.get("counts", {}).items():
        if counts.get(k, 0) != n:
            bad.append(f"header count for {k} is {n}, the links have {counts.get(k, 0)}")
    return bad


def _ci(k, n):
    if not n:
        return None
    lo, hi = wilson(k, n)
    return [round(lo, 4), round(hi, 4)]


def _rate(k, n):
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "ci": _ci(k, n)}


def _public(r):
    return {k: r.get(k) for k in ("write_id", "read_id", "from", "to", "channel_v110", "channel_now", "label", "reason",
                                  "also", "write_snippet", "read_snippet", "latency_h", "reported_v110", "reported_now")}


def score(found, audit):
    """found: the links between named tokens the code under test reports, as dicts with write_id, read_id
    (and from, to, channel when known) or as (write_id, read_id) pairs."""
    links = audit["links"]
    by_key = {(r["write_id"], r["read_id"]): r for r in links}
    fd = {}
    for d in found:
        if isinstance(d, dict):
            fd[(d["write_id"], d["read_id"])] = d
        else:
            fd[tuple(d)] = {"write_id": d[0], "read_id": d[1]}
    labels = [k for k in LABEL_ORDER if k in audit.get("labels", {})] + [k for k in audit.get("labels", {}) if k not in LABEL_ORDER]
    audited = [by_key[k] for k in fd if k in by_key]
    unaudited = [fd[k] for k in fd if k not in by_key]
    tp = sum(1 for r in audited if r["label"] == TRUE)
    unclear_found = sum(1 for r in audited if r["label"] == UNCLEAR)
    judged = len(audited) - unclear_found
    true_all = [r for r in links if r["label"] == TRUE]
    v110 = [r for r in links if r.get("reported_v110")]
    v110_tp = sum(1 for r in v110 if r["label"] == TRUE)
    v110_judged = sum(1 for r in v110 if r["label"] != UNCLEAR)

    def per_label(rows):
        return {k: sum(1 for r in rows if r["label"] == k) for k in labels}
    confusion = []
    for k in labels:
        rows = [r for r in links if r["label"] == k]
        confusion.append({"label": k, "name": SHORT.get(k, k.replace("_", " ")), "what": audit["labels"].get(k, ""),
                          "audited": len(rows), "v110": sum(1 for r in rows if r.get("reported_v110")),
                          "now": sum(1 for r in rows if (r["write_id"], r["read_id"]) in fd),
                          "dropped_now": sum(1 for r in rows if (r["write_id"], r["read_id"]) not in fd)})
    missed = [_public(r) for r in true_all if (r["write_id"], r["read_id"]) not in fd]
    false_now = [_public(r) for r in audited if r["label"] not in (TRUE, UNCLEAR)]
    unclear_rows = [_public(r) for r in audited if r["label"] == UNCLEAR]
    return {
        "audit": {k: audit.get(k) for k in ("about", "made", "how", "labelled_by", "limits", "dataset")},
        "audited_links": len(links),
        "labels": [{"label": k, "name": SHORT.get(k, k), "what": audit["labels"][k]} for k in labels],
        "reported_now": len(fd), "reported_now_audited": len(audited), "reported_now_unclear": unclear_found,
        "reported_now_not_audited": len(unaudited),
        "precision": _rate(tp, judged),
        "recall": _rate(tp, len(true_all)),
        "true_links_in_pool": len(true_all),
        "confusion": confusion,
        "then_vs_now": {
            "v110": {"reported": len(v110), "by_label": per_label(v110), "precision": _rate(v110_tp, v110_judged),
                     "recall": _rate(v110_tp, len(true_all))},
            "now": {"reported": len(fd), "by_label": {**per_label(audited), UNAUDITED: len(unaudited)},
                    "precision": _rate(tp, judged), "recall": _rate(tp, len(true_all))},
            "kept": sum(1 for r in v110 if (r["write_id"], r["read_id"]) in fd),
            "dropped": sum(1 for r in v110 if (r["write_id"], r["read_id"]) not in fd),
            "new": sum(1 for k in fd if k not in by_key or not by_key[k].get("reported_v110")),
        },
        "regressions": {"true_links_missed": missed, "false_links_reported": false_now,
                        "unclear_links_reported": unclear_rows,
                        "not_audited_links_reported": [{k: d.get(k) for k in ("write_id", "read_id", "from", "to", "channel")}
                                                       for d in unaudited]},
        # where the current code and the reading disagree: it reports a link read as false, or drops one read as true
        "disagreements": false_now + missed,
    }


def named_links(s):
    return [d for d in s.flow["_deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")]


def applies(s, audit):
    """Is the loaded session the audited release? Same record count, and the audited records are there."""
    want = (audit.get("dataset") or {}).get("records")
    ids = {r["write_id"] for r in audit["links"]} | {r["read_id"] for r in audit["links"]}
    have = sum(1 for i in ids if i in s.by_id)
    if want and len(s.events) != want:
        return False, f"the audit is of the Swarm Traces release ({want:,} records); this dataset has {len(s.events):,}"
    if have < 0.95 * len(ids):
        return False, "the audited records are not in this dataset"
    return True, ""


def simulator_check():
    """The saved comparison of v1.1.0's rules with the current code on the simulated swarms, or None."""
    try:
        from . import validation
        return validation.old_rules_summary()
    except Exception:       # pragma: no cover
        return None


def run(data, pack="code_traces.json", audit_path=None):
    from .session import Session
    audit = load_audit(audit_path)
    s = Session()
    s.load(data, pack, {}, os.path.basename(data))
    ok, why = applies(s, audit)
    if not ok:
        raise SystemExit("this benchmark does not apply: " + why)
    res = score(named_links(s), audit)
    res["dataset"] = {"name": s.name, "records": len(s.events)}
    return res


def _pct(x):
    if not x or x["value"] is None:
        return "–"
    return f"{100 * x['value']:.0f}% ({x['k']}/{x['n']}; 95% {100 * x['ci'][0]:.0f}–{100 * x['ci'][1]:.0f}%)"


def report_text(res):
    tv = res["then_vs_now"]
    L = [f"Audited links: {res['audited_links']} (labelled {res['audit']['made']}; {res['audit']['labelled_by']})",
         f"Links between named tokens reported now: {res['reported_now']} "
         f"({res['reported_now_audited']} audited, {res['reported_now_unclear']} unclear, {res['reported_now_not_audited']} not audited yet)",
         f"Precision now: {_pct(res['precision'])}    at v1.1.0: {_pct(tv['v110']['precision'])}",
         f"Recall now (of the {res['true_links_in_pool']} true links in the audited pool): {_pct(res['recall'])}"
         f"    at v1.1.0: {_pct(tv['v110']['recall'])}", "",
         f"{'label':<38}{'audited':>8}{'v1.1.0':>8}{'now':>6}"]
    for c in res["confusion"]:
        L.append(f"{c['name']:<38}{c['audited']:>8}{c['v110']:>8}{c['now']:>6}")
    rg = res["regressions"]
    L += ["", f"True links now missed: {len(rg['true_links_missed'])}"]
    L += [f"  {r['write_id']} -> {r['read_id']}  {r['reason']}" for r in rg["true_links_missed"]]
    L.append(f"False links now reported: {len(rg['false_links_reported'])}")
    L += [f"  {r['write_id']} -> {r['read_id']}  [{r['label']}] {r['reason']}" for r in rg["false_links_reported"]]
    if rg["not_audited_links_reported"]:
        L.append(f"Reported now but never audited: {len(rg['not_audited_links_reported'])}")
        L += [f"  {r['write_id']} -> {r['read_id']}  {r.get('channel') or ''}" for r in rg["not_audited_links_reported"]]
    return "\n".join(L)


# ------------------------------------------------------------------ route

def get_benchmark(state, q):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    sim = simulator_check()
    try:
        audit = load_audit()
    except (OSError, ValueError) as e:
        return {"applies": False, "why": f"the audited file could not be read: {e}", "simulator": sim}
    ok, why = applies(s, audit)
    if not ok:
        return {"applies": False, "why": why, "simulator": sim,
                "audit": {k: audit.get(k) for k in ("made", "labelled_by", "counts", "dataset")}}
    with _LOCK:
        res = getattr(s, "_benchmark", None)
        if res is None:
            res = score(named_links(s), audit)
            res["dataset"] = {"name": s.name, "records": len(s.events)}
            s._benchmark = res
    return {"applies": True, **res, "simulator": sim}


GET = {"benchmark": get_benchmark}
POST = {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.benchmark", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score the current code's links on the release against the audited labels")
    r.add_argument("data", help="the Swarm Traces release file (redacted_columns.csv)")
    r.add_argument("--pack", default="code_traces.json")
    r.add_argument("--out", default=None, help="folder for benchmark.json and benchmark.txt")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.data, a.pack)
    txt = report_text(res)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "benchmark.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
        with open(os.path.join(a.out, "benchmark.txt"), "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

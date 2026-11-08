#!/usr/bin/env python3
"""Reconstruct who talked to whom through shared artifacts, and test early flagging.

Usage (from the project root):
    python3 -I analyzer/flow.py redacted_columns.csv --config analyzer/flow_rules/swarm_traces.json --out reports/flow

Method, in brief:
1. Attribution. Each record is assigned to a handle family (a controller or campaign
   name) if its own text names one; otherwise to its thread's most common handle.
   Records with neither stay unattributed. The release has no sender field, so this
   is the only attribution available.
2. Artifacts. A shared artifact is a name the swarm uses to pass information: a
   mailbox board, a command file, a controller name. Patterns come from the config.
3. Edges. When an artifact appears under two different handle families, we add a
   directed edge from the family that first mentions it to the family that mentions
   it next. Direction is "first mention", not a verified send. A write marker in the
   first record and a read marker in the later one make the edge stronger.
4. Spread. For each artifact: first and last record, families that touched it, and
   how many records it reached.
5. Early flag. Replay the records in file order (timestamps are missing; see gaps)
   and find the first record at which an artifact is shared between two families.
   Compare it with the report's cited records (anchors) when the config lists them.

Outputs in --out: artifacts.csv, edges.csv, attribution.csv, early_flag.json,
flow_summary.json, flow_report.md (includes what an investigator would still miss).
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    arts = []
    for a in cfg["artifact_patterns"]:
        arts.append((a["family"], re.compile(a["pattern"])))
    handle_rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, cfg["handles"]), key=len, reverse=True)) + r")(?![A-Za-z0-9])")
    write_rx = re.compile(cfg.get("write_markers", "(?!)"), re.I)
    read_rx = re.compile(cfg.get("read_markers", "(?!)"), re.I)
    return cfg, arts, handle_rx, write_rx, read_rx


def family_of(handle, cfg):
    """Map a handle to its family using the config's prefix table (longest prefix wins)."""
    for prefix, fam in cfg.get("handle_families", {}).items():
        if handle.startswith(prefix):
            return fam
    return handle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id-col", default="id")
    ap.add_argument("--text-col", default="text")
    ap.add_argument("--parent-col", default="parent_id")
    ap.add_argument("--families", default=None,
                    help="records.csv from analyzer/analyze.py; used to check thread-reuse cases")
    a = ap.parse_args()
    cfg, arts, handle_rx, write_rx, read_rx = load_config(a.config)
    os.makedirs(a.out, exist_ok=True)

    recs = []
    with open(a.csv, encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            recs.append({"idx": i, "id": row[a.id_col], "text": row[a.text_col] or "",
                         "parent": row.get(a.parent_col) or ""})
    by_id = {r["id"]: r for r in recs}

    # thread roots and thread handles
    root = {}
    for r in recs:
        cur, seen = r["id"], set()
        while True:
            p = by_id.get(cur, {}).get("parent")
            if not p or p not in by_id or p in seen:
                break
            seen.add(cur)
            cur = p
        root[r["id"]] = cur

    own_handles = {}
    for r in recs:
        hs = [family_of(h, cfg) for h in set(handle_rx.findall(r["text"]))]
        own_handles[r["id"]] = sorted(set(hs))
    thread_votes = defaultdict(Counter)
    for r in recs:
        for h in own_handles[r["id"]]:
            thread_votes[root[r["id"]]][h] += 1
    thread_handle = {t: c.most_common(1)[0][0] for t, c in thread_votes.items()}

    # Artifact-based attribution: a record that names a controller's own command file
    # or board belongs to that controller, even when it names no handle.
    a2f = cfg.get("artifact_to_family", {})

    def family_from_artifact(name, fam_name):
        if a2f.get(fam_name):
            return a2f[fam_name]
        m = handle_rx.search(name)
        return family_of(m.group(1), cfg) if m else None

    art_family_of = defaultdict(list)
    for fam_name, rx in arts:
        for r in recs:
            for m in rx.finditer(r["text"]):
                f = family_from_artifact(m.group(0), fam_name)
                if f:
                    art_family_of[r["id"]].append(f)

    attr = {}   # id -> (family or None, how)
    for r in recs:
        if own_handles[r["id"]]:
            attr[r["id"]] = (own_handles[r["id"]][0], "own_text")
        elif art_family_of.get(r["id"]):
            attr[r["id"]] = (Counter(art_family_of[r["id"]]).most_common(1)[0][0], "artifact_name")
        elif root[r["id"]] in thread_handle:
            attr[r["id"]] = (thread_handle[root[r["id"]]], "thread")
        else:
            attr[r["id"]] = (None, "unattributed")
    how = Counter(v[1] for v in attr.values())

    # artifacts: name -> list of (idx, id, family, write?, read?)
    art_hits = defaultdict(list)
    for r in recs:
        seen_here = set()
        for fam_name, rx in arts:
            for m in rx.finditer(r["text"]):
                nm = m.group(0)
                if nm in seen_here:
                    continue
                seen_here.add(nm)
                art_hits[nm].append({
                    "idx": r["idx"], "id": r["id"], "family": attr[r["id"]][0],
                    "artifact_family": fam_name,
                    "write": bool(write_rx.search(r["text"])),
                    "read": bool(read_rx.search(r["text"])),
                })

    # artifact table and edges
    art_rows, edges = [], Counter()
    edge_evidence = defaultdict(list)
    first_shared = None
    for nm, hits in art_hits.items():
        fams = [h["family"] for h in hits if h["family"]]
        distinct = sorted(set(fams))
        art_rows.append([nm, hits[0]["artifact_family"], len(hits), hits[0]["id"], hits[-1]["id"],
                         len(distinct), "|".join(distinct)])
        ordered = [h for h in hits if h["family"]]
        for x in range(len(ordered)):
            for y in range(x + 1, len(ordered)):
                s, d = ordered[x], ordered[y]
                if s["family"] != d["family"]:
                    key = (s["family"], d["family"])
                    edges[key] += 1
                    if len(edge_evidence[key]) < 8:
                        edge_evidence[key].append(f"{nm}: {s['id']} -> {d['id']}")
                    strong = s["write"] and d["read"]
                    if strong:
                        edges[("strong",) + key] += 1
                    if first_shared is None or d["idx"] < first_shared[0]:
                        first_shared = (d["idx"], d["id"], nm, s["family"], d["family"])

    art_rows.sort(key=lambda r: -r[2])
    edge_rows = []
    for key, n in edges.most_common():
        if key[0] == "strong":
            continue
        strong = edges.get(("strong",) + key, 0)
        edge_rows.append([key[0], key[1], n, strong, " ; ".join(edge_evidence.get(key, [])[:4])])

    # early flag: replay in file order
    shared_so_far = set()
    fam_seen_for = defaultdict(set)
    first_flag = None
    flags_at = []
    hit_index = defaultdict(list)
    for nm, hits in art_hits.items():
        for h in hits:
            hit_index[h["idx"]].append((nm, h["family"]))
    for r in recs:
        for nm, fam in hit_index.get(r["idx"], []):
            if fam:
                fam_seen_for[nm].add(fam)
            if len(fam_seen_for[nm]) >= 2 and nm not in shared_so_far:
                shared_so_far.add(nm)
                flags_at.append({"id": r["id"], "idx": r["idx"], "artifact": nm,
                                 "families": sorted(fam_seen_for[nm])})
                if first_flag is None:
                    first_flag = flags_at[-1]
    # Second rule: an artifact reappearing in a different thread (a different run or
    # conversation). This says information moved, even when the family is unknown.
    thr_seen = defaultdict(set)
    thread_flag = None
    thread_flags = []
    for r in recs:
        for nm, fam in hit_index.get(r["idx"], []):
            thr_seen[nm].add(root[r["id"]])
            if len(thr_seen[nm]) == 2 and nm not in {f["artifact"] for f in thread_flags}:
                thread_flags.append({"id": r["id"], "idx": r["idx"], "artifact": nm})
                if thread_flag is None:
                    thread_flag = thread_flags[-1]
    artifacts_multi_thread = sum(1 for v in thr_seen.values() if len(v) >= 2)

    # Check thread-reuse cases: if every record carrying the artifact belongs to one
    # analyzer family, the reuse is most likely one template copied across runs.
    fam_of_rec = {}
    if a.families:
        with open(a.families, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                fam_of_rec[row["id"]] = row.get("family", "")
    reuse_rows = []
    template_like = 0
    for nm, hits in art_hits.items():
        threads = {root[h["id"]] for h in hits}
        if len(threads) < 2:
            continue
        fams = {fam_of_rec.get(h["id"], "") for h in hits}
        fams.discard("")
        likely_copy = bool(fams) and len(fams) == 1
        template_like += likely_copy
        reuse_rows.append([nm, len(threads), len(hits), len(fams), "template_copy" if likely_copy else "mixed_or_unknown"])
    reuse_rows.sort(key=lambda r: -r[1])
    with open(os.path.join(a.out, "thread_reuse_check.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artifact", "threads", "records", "analyzer_families", "verdict"])
        w.writerows(reuse_rows)

    n = len(recs)
    anchors = [x for x in cfg.get("anchors", []) if x in by_id]
    anchor_idx = {x: by_id[x]["idx"] for x in anchors}
    before_anchor = {}
    for x, ix in anchor_idx.items():
        before_anchor[x] = {
            "idx": ix,
            "family_rule_at_or_before": first_flag is not None and first_flag["idx"] <= ix,
            "thread_rule_at_or_before": thread_flag is not None and thread_flag["idx"] <= ix,
        }
    anchors_after_thread = sum(1 for x in anchors if thread_flag and anchor_idx[x] >= thread_flag["idx"])
    early = {
        "order": "file order (timestamps are missing)",
        "first_shared_artifact": first_flag,
        "shared_artifacts_total": len(shared_so_far),
        "rule_thread_reuse": {
            "first_reuse_across_threads": thread_flag,
            "artifacts_reused_across_threads": artifacts_multi_thread,
            "fraction_of_stream": round(thread_flag["idx"] / n, 4) if thread_flag else None,
            "checked_against_families": bool(a.families),
            "likely_template_copies": template_like,
            "mixed_or_unknown": len(reuse_rows) - template_like,
        },
        "fraction_of_stream_at_first_flag": round(first_flag["idx"] / n, 4) if first_flag else None,
        "anchors_checked": len(anchors),
        "anchors_after_family_flag": sum(1 for x in anchors if first_flag and anchor_idx[x] >= first_flag["idx"]),
        "anchors_after_thread_flag": anchors_after_thread,
        "anchor_detail": before_anchor,
    }
    with open(os.path.join(a.out, "early_flag.json"), "w", encoding="utf-8") as f:
        json.dump(early, f, indent=2)

    with open(os.path.join(a.out, "artifacts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artifact", "family", "records", "first_id", "last_id", "families_touching", "families"])
        w.writerows(art_rows)
    with open(os.path.join(a.out, "edges.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from_family", "to_family", "shared_artifact_mentions", "strong_write_then_read", "evidence"])
        w.writerows(edge_rows)
    with open(os.path.join(a.out, "attribution.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "family", "how"])
        for r in recs:
            w.writerow([r["id"], attr[r["id"]][0] or "", attr[r["id"]][1]])

    fam_counts = Counter(v[0] for v in attr.values() if v[0])
    summary = {
        "records": n,
        "attribution": dict(how),
        "families_seen": len(fam_counts),
        "families": dict(fam_counts.most_common()),
        "artifacts": len(art_hits),
        "artifacts_in_2plus_records": sum(1 for h in art_hits.values() if len(h) >= 2),
        "artifacts_across_2plus_families": sum(1 for r in art_rows if r[5] >= 2),
        "edges": len(edge_rows),
        "strong_edges": sum(1 for r in edge_rows if r[3] > 0),
        "early_flag": early,
    }
    with open(os.path.join(a.out, "flow_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    unattr = how.get("unattributed", 0)
    lines = [
        "# Flow reconstruction: summary", "",
        f"Records: {n:,}. Attribution: " + ", ".join(f"{k} {v:,}" for k, v in how.items()) + ".", "",
        "## Families and edges",
        f"- Families seen: {len(fam_counts)} ({', '.join(f'{k} {v}' for k, v in fam_counts.most_common(8))}).",
        f"- Artifacts: {len(art_hits):,}. In two or more records: {summary['artifacts_in_2plus_records']:,}. Across two or more families: {summary['artifacts_across_2plus_families']:,}.",
        f"- Directed edges between families: {len(edge_rows)}. With a write then read: {summary['strong_edges']}.",
        f"- Artifacts reused across different threads: {early['rule_thread_reuse']['artifacts_reused_across_threads']:,}. "
        + (f"Of these, {template_like:,} have all their records in one known analyzer family, and "
           f"{len(reuse_rows) - template_like:,} have mixed or unknown families. Most records have no family, so the "
           f"split mostly shows missing attribution, not copying. Read thread reuse as shared-resource access: several runs "
           f"touch the same name, which fits a board or mailbox, but it does not show who sent what." if a.families
           else "Not checked against families (pass --families)."), "",
        "## Early flag (file order)",
        (f"First artifact shared between two families: {first_flag['id']} ({first_flag['artifact']}; "
         f"{' and '.join(first_flag['families'])}). That is {early['fraction_of_stream_at_first_flag']:.2%} into the file."
         if first_flag else "No artifact was shared between two families."), "",
        f"Anchors checked: {len(anchors)}. At or after the family-rule flag: {early['anchors_after_family_flag']}. "
        f"At or after the thread-reuse flag: {early['anchors_after_thread_flag']}.",
        "Anchors are the records the report cites, so they are chosen with hindsight; read this as a consistency check.", "",
        "## What an investigator would still miss",
        f"- Sender and receiver are not in the data. Every edge is inferred from a shared name and a first mention, not an observed message.",
        f"- {unattr:,} records ({unattr / n:.1%}) cannot be attributed to any family, even through their thread.",
        "- Direction is first mention. A name that was read before it was written, or was written by a redacted party, reverses or hides an edge.",
        "- No timestamps: the early-flag test is in file order, which may not match when things happened.",
        "- Artifact names are a curated list. An artifact outside the list is invisible, and names reused by unrelated code (for example generic words) add false edges.",
        "- Family boundaries come from the handle prefix table in the config, which is hand-built.",
        "",
    ]
    with open(os.path.join(a.out, "flow_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(json.dumps({k: summary[k] for k in ("records", "attribution", "families_seen", "artifacts",
                                             "artifacts_across_2plus_families", "edges", "strong_edges")}, indent=2))
    print("first shared artifact:", first_flag)


if __name__ == "__main__":
    main()

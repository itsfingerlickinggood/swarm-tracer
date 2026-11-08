#!/usr/bin/env python3
"""Forensics on Swarm Traces: who talked to whom, how information spread,
and whether simple coordination rules would have flagged the swarm early.

Usage:
    python3 -I forensics/swarm_forensics.py redacted.jsonl forensics/out

Inputs: the redacted Swarm Traces JSONL (one record per line with fields
id, cite, kind, parent_id, time_utc, tags, text).

Outputs (in the output dir):
    entities.csv      one row per campaign/controller handle
    edges.csv         weighted directed edges (co_mention, parent_flow, board_flow)
    timeline.csv      first/last appearance per entity, in record order and in dates
    flags.json        replay results for each coordination rule
    anchors.csv       the record IDs the report cites, and whether the rules fire near them
    report.md         summary, including what an investigator would still miss
"""
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# Entity handles. Built from the names that recur in controllers, boards and
# commands in the report. Longest alternatives first so C5DF220 is not read as C5.
# ---------------------------------------------------------------------------
ENTITY_NAMES = [
    "C6E6E", "C5DF", "C23RO", "C64I", "C608", "C5L14", "C5GH", "C4E1", "C4R1",
    "OTS92", "G23619", "G236C3", "G236", "LIBR11", "Future9180",
    "SC4E1", "SC4", "H20E1", "A22B", "PX32", "U58E1", "U58",
    "MARB051", "BE90", "flb4", "hb58428env", "K64AUTO", "K64", "M47E1", "C5", "C6",
]
ENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, ENTITY_NAMES), key=len, reverse=True)) + r")"
)

# Coordination markers: specific to the controller/mailbox machinery described in the report.
# Deliberately narrow: generic words like "lock" or "poll" fire on ordinary exploit code.
COORD_RE = re.compile(
    r"BEACON|_DONE|OTS92CMD|OTS92DONE|OTS92OUT|g23619cmd|g236_tokens|claim_|"
    r"neutrali[sz]|seen\.add|MKCOL|board\(|tailscale|exit-node|elect one|"
    r"signed command|controller launch|shared-infra|prune",
    re.I,
)
# Credential / reconnaissance markers: what the agents were after.
RECON_RE = re.compile(
    r"secret|serviceaccount|kube|IMDS|LOOT|token|aws_|AWS4|cluster-admin|rule_score|configmap",
    re.I,
)
# Redaction placeholders, which hide real identifiers from the investigator.
REDACT_RE = re.compile(r"\[(REDACTED|SERVICE|CREDENTIAL|USER|HF REPO|INFRA CONFIG|ENV VALUE|WEBHOOK)[^\]]*\]")
# Epoch seconds embedded in names, for example C6E6E_STAGE1P_1783815200. Limited to 2026-era values.
EPOCH_RE = re.compile(r"(?<!\d)(17[6-9]\d{7})(?!\d)")  # 10-digit unix seconds, 2026-era
BOARD_RE = re.compile(r"zz(?:HF|D64|FILE|MODAL|WAF|BEACON|OTS|G236|C6|C5|C4|LIB|SC4|H20)[A-Za-z0-9_]{0,80}")

# Record IDs the report cites as evidence. Used as anchors for the early-flag check.
REPORT_ANCHORS = [
    "R0000028", "R0001544", "R0044685", "R0046300", "R0045500", "R0045113", "R0017775",
    "R0020319", "R0037871", "R0013615", "R0066842", "R0066845", "R0005947", "R0052281",
    "R0052703", "R0035596", "R0035736", "R0002547", "R0003300", "R0003589", "R0029223",
    "R0028613", "R0028572", "R0079934", "R0034468", "R0030740", "R0035032", "R0189544",
    "R0189571", "R0035183", "R0050295", "R0050923", "R0050939", "R0051428", "R0042479",
    "R0051248", "R0036650", "R0029048", "R0189549", "R0189550", "R0035082", "R0043481",
    "R0030994", "R0071628", "R0071839", "R0046388", "R0027899", "R0033275", "R0033135",
    "R0072837", "R0072838", "R0004717", "R0052703",
]


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            o["_idx"] = len(rows)  # position in the file, which is the replay order
            rows.append(o)
    return rows


def entities_in(text):
    return {canon(m) for m in ENT_RE.findall(text or "")}


def canon(name):
    # Group the sub-handles into one family, so C5DF220 and C5 count as one actor.
    for prefix, family in [("C6E6E", "C6E6E"), ("C5DF", "C5"), ("C23RO", "C23RO"),
                           ("C64I", "C64"), ("C608", "C6"), ("C5L14", "C5"), ("C5GH", "C5"),
                           ("C4E1", "C4"), ("C4R1", "C4"), ("G236C3", "G236"), ("G23619", "G236"),
                           ("G236", "G236"), ("U58E1", "U58"), ("SC4E1", "SC4"), ("M47E1", "M47"),
                           ("K64AUTO", "K64"), ("hb58428env", "hb58428env"), ("flb4", "flb4"),
                           ("Future9180", "Future9180"), ("LIBR11", "LIBR11"),
                           ("H20E1", "H20E1"), ("A22B", "A22B"), ("PX32", "PX32"),
                           ("MARB051", "MARB051"), ("BE90", "BE90"), ("OTS92", "OTS92"),
                           ("SC4", "SC4"), ("U58", "U58"), ("C5", "C5"), ("C6", "C6"), ("K64", "K64")]:
        if name.startswith(prefix):
            return family
    return name


def epoch_dates(text):
    out = []
    for m in EPOCH_RE.findall(text or ""):
        try:
            out.append(dt.datetime.fromtimestamp(int(m), dt.timezone.utc))
        except (OverflowError, OSError, ValueError):
            pass
    return out


def build(rows):
    by_id = {r["id"]: r for r in rows}
    ent_first = {}
    ent_last = {}
    ent_count = Counter()
    ent_dates = defaultdict(list)
    co = Counter()
    parent_flow = Counter()
    board_writers = defaultdict(set)  # board -> entities that mention it with a write marker
    board_readers = defaultdict(set)
    board_first = {}
    rec_ents = {}

    for r in rows:
        text = r.get("text", "")
        ents = entities_in(text)
        rec_ents[r["id"]] = ents
        for e in ents:
            ent_first.setdefault(e, r["_idx"])
            ent_last[e] = r["_idx"]
            ent_count[e] += 1
            for d in epoch_dates(text):
                ent_dates[e].append(d)
        for a in ents:
            for b in ents:
                if a < b:
                    co[(a, b)] += 1
        pid = r.get("parent_id")
        if pid and pid in rec_ents:
            for a in rec_ents[pid]:
                for b in ents:
                    if a != b:
                        parent_flow[(a, b)] += 1
        for b in set(BOARD_RE.findall(text)):
            if COORD_RE.search(text):
                for e in ents:
                    board_writers[b].add(e)
                board_first.setdefault(b, r["_idx"])
            else:
                for e in ents:
                    board_readers[b].add(e)
    board_flow = Counter()
    for b, ws in board_writers.items():
        for w in ws:
            for rd in board_readers.get(b, ()):
                if w != rd:
                    board_flow[(w, rd)] += 1
    return {
        "by_id": by_id, "ent_first": ent_first, "ent_last": ent_last, "ent_count": ent_count,
        "ent_dates": ent_dates, "co": co, "parent_flow": parent_flow, "board_flow": board_flow,
        "board_writers": board_writers, "board_first": board_first, "rec_ents": rec_ents,
    }


def replay(rows, g):
    """Replay the stream in file order. Record each rule's first firing and its context."""
    # Windowed rule: a handle family seen in >=2 distinct families within 200 records
    # of each other, with at least one coordination marker in the window.
    window = 200
    recent = []  # (idx, families)
    windowed_hits = []
    for r in rows:
        fams = g["rec_ents"].get(r["id"], set())
        if fams:
            recent.append((r["_idx"], fams))
        recent = [(i, f) for i, f in recent if r["_idx"] - i <= window]
        seen = set().union(*[f for _, f in recent]) if recent else set()
        if len(seen) >= 2 and COORD_RE.search(r.get("text", "")):
            windowed_hits.append(r["_idx"])

    rules = {
        "R1_coord_marker_with_handle": lambda t, ents: bool(COORD_RE.search(t)) and len(ents) >= 1,
        "R2_coord_marker_2plus_handles": lambda t, ents: bool(COORD_RE.search(t)) and len(ents) >= 2,
        "R3_board_marker_with_handle": lambda t, ents: bool(BOARD_RE.search(t)) and len(ents) >= 1,
        "R4_recon_plus_coord": lambda t, ents: bool(COORD_RE.search(t)) and bool(RECON_RE.search(t)),
    }
    results = {}
    total = len(rows)
    for name, fn in list(rules.items()) + [("R5_windowed_2_families_coord", None)]:
        if fn is None:
            hits = windowed_hits
        else:
            hits = []
            for r in rows:
                ents = g["rec_ents"].get(r["id"], set())
                if fn(r.get("text", ""), ents):
                    hits.append(r["_idx"])
        results[name] = {
            "fires": len(hits),
            "first_idx": hits[0] if hits else None,
            "first_id": rows[hits[0]]["id"] if hits else None,
            "first_fraction_of_stream": round(hits[0] / total, 4) if hits else None,
            "hits_in_first_10pct": sum(1 for h in hits if h < total * 0.10),
        }
    return results


def anchor_check(rows, g, flags_idx):
    by_id = g["by_id"]
    idx_of = {r["id"]: r["_idx"] for r in rows}
    out = []
    for a in REPORT_ANCHORS:
        if a not in idx_of:
            out.append({"anchor": a, "present": False})
            continue
        i = idx_of[a]
        r = by_id[a]
        ents = sorted(g["rec_ents"].get(a, set()))
        prior = [f for f in flags_idx if f <= i]
        out.append({
            "anchor": a,
            "present": True,
            "kind": r.get("kind"),
            "has_parent": bool(r.get("parent_id")),
            "entities": ";".join(ents),
            "has_redaction": bool(REDACT_RE.search(r.get("text", ""))),
            "coord_marker": bool(COORD_RE.search(r.get("text", ""))),
            "rule_fired_at_or_before": bool(prior),
            "distance_to_nearest_prior_flag": (i - max(prior)) if prior else None,
        })
    return out


def investigator_gaps(rows, g):
    n = len(rows)
    no_time = sum(1 for r in rows if not r.get("time_utc"))
    no_parent = sum(1 for r in rows if not r.get("parent_id"))
    redacted = sum(1 for r in rows if REDACT_RE.search(r.get("text", "")))
    no_entity = sum(1 for r in rows if not g["rec_ents"].get(r["id"]))
    single = [e for e, c in g["ent_count"].items() if c == 1]
    board_only_redacted = 0
    for r in rows:
        if BOARD_RE.search(r.get("text", "")) and REDACT_RE.search(r.get("text", "")):
            board_only_redacted += 1
    return {
        "records": n,
        "records_without_time_utc": no_time,
        "records_without_parent": no_parent,
        "records_with_redaction_placeholders": redacted,
        "records_mentioning_no_tracked_entity": no_entity,
        "entities_seen_once": len(single),
        "records_with_board_and_redaction": board_only_redacted,
        "records_with_epoch_in_name": sum(1 for r in rows if EPOCH_RE.search(r.get("text", ""))),
    }


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main(argv):
    src = argv[1] if len(argv) > 1 else "redacted.jsonl"
    out = argv[2] if len(argv) > 2 else "forensics/out"
    os.makedirs(out, exist_ok=True)
    rows = load(src)
    g = build(rows)

    ents = sorted(g["ent_count"], key=lambda e: g["ent_first"][e])
    ent_rows = []
    timeline_rows = []
    for e in ents:
        ds = sorted(g["ent_dates"].get(e, []))
        ent_rows.append([e, g["ent_count"][e], rows[g["ent_first"][e]]["id"], rows[g["ent_last"][e]]["id"]])
        timeline_rows.append([
            e, g["ent_first"][e], rows[g["ent_first"][e]]["id"], rows[g["ent_last"][e]]["id"],
            ds[0].date().isoformat() if ds else "", ds[-1].date().isoformat() if ds else "",
        ])
    write_csv(os.path.join(out, "entities.csv"), ["entity", "mentions", "first_id", "last_id"], ent_rows)
    write_csv(os.path.join(out, "timeline.csv"),
              ["entity", "first_idx", "first_id", "last_id", "first_date", "last_date"], timeline_rows)

    edge_rows = []
    for (a, b), c in g["co"].most_common():
        edge_rows.append(["co_mention", a, b, c])
    for (a, b), c in g["parent_flow"].most_common():
        edge_rows.append(["parent_flow", a, b, c])
    for (a, b), c in g["board_flow"].most_common():
        edge_rows.append(["board_flow", a, b, c])
    write_csv(os.path.join(out, "edges.csv"), ["kind", "src", "dst", "weight"], edge_rows)

    flags = replay(rows, g)
    flag_idx = sorted({r["_idx"] for r in rows if COORD_RE.search(r.get("text", ""))})
    anchors = anchor_check(rows, g, flag_idx)
    write_csv(os.path.join(out, "anchors.csv"),
              ["anchor", "present", "kind", "has_parent", "entities", "has_redaction",
               "coord_marker", "rule_fired_at_or_before", "distance_to_nearest_prior_flag"],
              [[a.get(k, "") for k in ["anchor", "present", "kind", "has_parent", "entities",
                                        "has_redaction", "coord_marker", "rule_fired_at_or_before",
                                        "distance_to_nearest_prior_flag"]] for a in anchors])
    with open(os.path.join(out, "flags.json"), "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2)

    gaps = investigator_gaps(rows, g)
    present = [a for a in anchors if a.get("present")]
    flagged_anchor = sum(1 for a in present if a["coord_marker"])
    summary = {
        "records": len(rows),
        "tracked_entities": len(ents),
        "co_mention_edges": len(g["co"]),
        "parent_flow_edges": len(g["parent_flow"]),
        "board_flow_edges": len(g["board_flow"]),
        "anchors_present": len(present),
        "anchors_with_coord_marker": flagged_anchor,
        "rules": flags,
        "investigator_gaps": gaps,
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    lines = ["# Swarm Traces forensics: summary", "",
             f"Records: {len(rows)}. Tracked entities: {len(ents)}. Edges: co-mention {len(g['co'])}, "
             f"parent flow {len(g['parent_flow'])}, board flow {len(g['board_flow'])}.", "",
             "## Early-flag replay (file order)", "",
             "| Rule | Fires | First record | First fraction of stream | Hits in first 10% |",
             "|---|---|---|---|---|"]
    for name, res in flags.items():
        lines.append(f"| {name} | {res['fires']} | {res['first_id']} | {res['first_fraction_of_stream']} | {res['hits_in_first_10pct']} |")
    lines += ["", "## Report anchors", "",
              f"{len(present)} of {len(REPORT_ANCHORS)} cited records are in the release. "
              f"{flagged_anchor} of them contain a coordination marker."
              " Anchors were chosen by investigators who already knew the story, so this is a consistency check, not an independent detection test.",
              "", "## What an investigator would still miss", "",
              f"- {gaps['records_without_time_utc']} of {gaps['records']} records have no timestamp, so every date here comes from epoch values in names ({gaps['records_with_epoch_in_name']} records) or from the report.",
              f"- {gaps['records_without_parent']} records have no parent link, so their origin is unknown.",
              f"- {gaps['records_with_redaction_placeholders']} records contain redaction placeholders, which hide endpoints and identities.",
              f"- {gaps['records_mentioning_no_tracked_entity']} records mention no tracked handle, so the tool cannot attribute them.",
              f"- {gaps['entities_seen_once']} handles appear only once and cannot be linked to others.",
              f"- {gaps['records_with_board_and_redaction']} records tie a board name to a redacted field, so the board flow they imply is uncertain.",
              "- Agent identity: the release has no sender or receiver field. Edges are inferred from co-mention, parent links and shared board names, not observed messages.",
              ""]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv)

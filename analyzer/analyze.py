#!/usr/bin/env python3
"""Analyze a CSV of agent records: tags, stages, handles, threads, families, gaps.

Works on any CSV with an id column and a text column. Other columns are optional.

Usage (from the project root):
    python3 -I analyzer/analyze.py data.csv --out reports/mydata
    python3 -I analyzer/analyze.py data.csv --out reports/mydata \
        --id-col record --text-col body --kind-col type --parent-col reply_to --time-col created
    python3 -I analyzer/analyze.py data.csv --out reports/mydata --rules analyzer/rules/mine.json

Outputs in --out:
    report.html       one page to read: profile, stages, behaviors, handles, threads, families, gaps
    summary.json      every number in the report, machine-readable
    records.csv       one row per record: tags, stages, handles, thread root, family
    behaviors.csv, stages.csv, handles.csv, families.csv, threads.csv, pairs.csv

Stdlib only. Behavior and handle rules come from a JSON rules file (see analyzer/rules/).
Tags describe what the text would do. They are pattern matches, not verified behavior.
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

SIM_BITS_MAX = 6        # families: at most this many differing bits of 64
SHINGLE = 4             # tokens per shingle
MIN_TOKENS = 20         # shorter texts group only when normalized text is identical
TOKEN = re.compile(r"<[a-z][a-z_]*>|\w+|[^\w\s]")


# ----------------------------------------------------------------- loading

def load_rules(path):
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    compiled = []
    for b in rules["behaviors"]:
        flags = re.I if "i" in b.get("flags", "") else 0
        try:
            rx = re.compile(b["pattern"], flags)
        except re.error as e:
            raise SystemExit(f"bad pattern for behavior {b['name']}: {e}")
        compiled.append({**b, "rx": rx})
    handle_rx = None
    if rules.get("handles"):
        alt = "|".join(sorted(map(re.escape, rules["handles"]), key=len, reverse=True))
        handle_rx = re.compile(r"(?<![A-Za-z0-9])(" + alt + r")(?![A-Za-z0-9])")
    ph = re.compile(rules.get("placeholder_pattern", r"(?!)"))
    return compiled, handle_rx, ph, rules


def read_records(path, cols):
    """Return list of dicts with normalized keys: id, text, kind, parent, time."""
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        present = set(reader.fieldnames or [])
        for need in ("id", "text"):
            if cols[need] not in present:
                raise SystemExit(f"column '{cols[need]}' not found; columns are: {sorted(present)}")
        for row in reader:
            out.append({
                "id": row[cols["id"]],
                "text": row.get(cols["text"]) or "",
                "kind": (row.get(cols["kind"]) or "record") if cols["kind"] in present else "record",
                "parent": (row.get(cols["parent"]) or "") if cols["parent"] in present else "",
                "time": (row.get(cols["time"]) or "") if cols["time"] in present else "",
            })
    return out, sorted(present)


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    if re.fullmatch(r"\d{10}", s):
        return dt.datetime.fromtimestamp(int(s), dt.timezone.utc)
    return None


# ----------------------------------------------------------------- analysis

def roots_of(records):
    by_id = {r["id"]: r for r in records}
    root = {}
    for r in records:
        cur, seen = r["id"], set()
        while True:
            p = by_id.get(cur, {}).get("parent")
            if not p or p not in by_id or p in seen:
                break
            seen.add(cur)
            cur = p
        root[r["id"]] = cur
    return root


def normalize(text, ph):
    t = ph.sub(lambda m: "<" + re.sub(r"[^a-z]+", "_", m.group(0)[1:-1].split(":")[0].lower()).strip("_") + ">", text)
    t = re.sub(r"\b[0-9a-fA-F]{8,}\b", " <h> ", t)
    t = re.sub(r"\b\d+\b", " <n> ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def simhash(text):
    words = TOKEN.findall(text)
    if len(words) < SHINGLE:
        shingles = {" ".join(words)}
    else:
        shingles = {" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}
    v = [0] * 64
    for s in shingles:
        h = int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big")
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    return sum(1 << b for b in range(64) if v[b] > 0)


def families(records, ph):
    """Group records: identical normalized text, then near-duplicates by SimHash bands."""
    norm = [normalize(r["text"], ph) for r in records]
    exact = {}
    rep = []
    for i, t in enumerate(norm):
        k = hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()
        exact.setdefault(k, i)
        rep.append(exact[k])
    reps = sorted(set(rep))
    long_reps = [i for i in reps if len(TOKEN.findall(norm[i])) >= MIN_TOKENS]
    sig = {i: simhash(norm[i]) for i in long_reps}
    bands = [defaultdict(list) for _ in range(4)]
    for i in long_reps:
        for b in range(4):
            bands[b][(sig[i] >> (16 * b)) & 0xFFFF].append(i)
    parent = list(range(len(records)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for b in range(4):
        for bucket in bands[b].values():
            if 2 <= len(bucket) <= 5000:
                for x in range(len(bucket)):
                    for y in range(x + 1, len(bucket)):
                        i, j = bucket[x], bucket[y]
                        if bin(sig[i] ^ sig[j]).count("1") <= SIM_BITS_MAX:
                            ri, rj = find(i), find(j)
                            if ri != rj:
                                parent[max(ri, rj)] = min(ri, rj)
    fam_root = [find(rep[i]) for i in range(len(records))]
    members = defaultdict(list)
    for i, r in enumerate(fam_root):
        members[r].append(i)
    ranked = sorted(members.items(), key=lambda kv: -len(kv[1]))
    fid = {root: f"F{k + 1:05d}" for k, (root, _) in enumerate(ranked)}
    return [fid[r] for r in fam_root], ranked, norm


# ----------------------------------------------------------------- report

def bar(pct):
    return f'<div class="bar" style="width:{max(0.5, min(100, pct)):.1f}%"></div>'


def esc(x):
    return html.escape(str(x))


def write_report(path, title, S, behaviors_rows, stage_rows, handle_rows, pair_rows, thread_rows, family_rows):
    def table(headers, rows):
        head = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    prof = S["profile"]
    gaps = S["gaps"]
    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
body{{font:14px -apple-system,system-ui,sans-serif;margin:24px;color:#222;max-width:1200px}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}}
th,td{{text-align:left;padding:4px 6px;border-bottom:1px solid #eee;vertical-align:top}}
th{{background:#f0f3f6}} td.num{{text-align:right;white-space:nowrap}}
.bar{{height:9px;background:#3b6ea5;border-radius:3px;min-width:2px}}
.mono{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;word-break:break-word}}
.note{{color:#666;font-size:12px}} .kpi span{{display:inline-block;margin-right:22px}}
.kpi b{{font-size:18px}}
</style></head><body>
<h1>{esc(title)}</h1>
<p class="note">Generated by analyzer/analyze.py. Tags are pattern matches on the text, not verified behavior. Rules: {esc(S['rules_name'])}.</p>
<div class="kpi"><span>records <b>{prof['records']:,}</b></span><span>with any tag <b>{S['records_with_any_tag']:,}</b> ({S['records_with_any_tag_pct']}%)</span><span>families <b>{S['families']:,}</b></span><span>threads <b>{S['threads']:,}</b></span></div>
<h2>Profile</h2>
<p>Columns: {esc(', '.join(prof['columns']))}</p>
<p>Kinds: {esc(', '.join(f'{k} {v:,}' for k, v in prof['kinds'].items()))}</p>
<p>Timestamps: {esc(prof['time_note'])}</p>
<h2>Stages (what the behaviors suggest, grouped)</h2>
{table(['stage', 'records', '%', ''], [[esc(s), f'{n:,}', f'{p}', bar(p)] for s, n, p in stage_rows])}
<h2>Behaviors</h2>
{table(['behavior', 'stage', 'records', '%', 'by kind', 'what the pattern matches', ''],
       [[esc(b), esc(st), f'{n:,}', f'{p}', esc(k), esc(d), bar(p)] for b, st, n, p, k, d in behaviors_rows])}
<h2>Behavior pairs that co-occur most</h2>
{table(['behavior A', 'behavior B', 'records together'], [[esc(a), esc(b), f'{n:,}'] for a, b, n in pair_rows])}
<h2>Handles named in the text</h2>
{table(['handle', 'records'], [[esc(h), f'{n:,}'] for h, n in handle_rows]) if handle_rows else '<p class="note">No handles configured or none found.</p>'}
<h2>Threads (records linked by parent)</h2>
<p>{S['threads']:,} threads. {S['threads_singleton']:,} are single records. {S['records_with_parent']:,} records have a parent.</p>
{table(['thread root', 'records in thread', 'example kinds'], [[esc(a), f'{n:,}', esc(k)] for a, n, k in thread_rows])}
<h2>Families (near-duplicate texts)</h2>
<p>{S['families']:,} families. {S['families_10plus']:,} have 10 or more records and cover {S['records_in_families_10plus']:,} records. The grouping uses normalized text (ids, numbers and hex are masked), so previews show the shared shape.</p>
{table(['family', 'records', 'kinds', 'preview of normalized text'], [[esc(f), f'{n:,}', esc(k), f'<span class="mono">{esc(p)}</span>'] for f, n, k, p in family_rows])}
<h2>Gaps: what this data cannot tell you</h2>
<ul>
<li>{gaps['no_time']:,} of {prof['records']:,} records have no usable timestamp.</li>
<li>{gaps['no_parent']:,} records have no parent, so their origin is unknown.</li>
<li>{gaps['has_placeholder']:,} records contain redaction placeholders, which hide endpoints or identities.</li>
<li>{gaps['no_handle']:,} records name no configured handle, so they cannot be attributed to a campaign.</li>
<li>{gaps['no_tag']:,} records match no behavior rule. A rule set can only find what its patterns describe.</li>
</ul>
</body></html>"""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rules", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules", "default.json"))
    ap.add_argument("--id-col", default="id")
    ap.add_argument("--text-col", default="text")
    ap.add_argument("--kind-col", default="kind")
    ap.add_argument("--parent-col", default="parent_id")
    ap.add_argument("--time-col", default="time_utc")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()

    cols = {"id": a.id_col, "text": a.text_col, "kind": a.kind_col, "parent": a.parent_col, "time": a.time_col}
    behaviors, handle_rx, ph, rules = load_rules(a.rules)
    records, columns = read_records(a.csv, cols)
    os.makedirs(a.out, exist_ok=True)
    n = len(records)
    if n == 0:
        raise SystemExit("no records")

    # profile
    kinds = Counter(r["kind"] for r in records)
    times = [parse_time(r["time"]) for r in records]
    usable = [t for t in times if t]
    time_note = (f"{len(usable):,} records parse as timestamps, from {min(usable).isoformat()} to {max(usable).isoformat()}"
                 if usable else "no usable timestamps (the time column is missing, empty, or unparseable)")

    # per-record tags, handles, placeholders
    rec_tags, rec_stages, rec_handles, rec_ph = [], [], [], []
    CONTEXT = {b["name"] for b in behaviors if b.get("context")}
    beh_count = Counter()
    beh_by_kind = defaultdict(Counter)
    stage_recs = defaultdict(set)
    handle_count = Counter()
    pair_count = Counter()
    for i, r in enumerate(records):
        tags = [b["name"] for b in behaviors if b["rx"].search(r["text"])]
        evidence = [t for t in tags if t not in CONTEXT]   # context tags never count as evidence
        stages = sorted({b["stage"] for b in behaviors if b["name"] in evidence})
        hs = sorted(set(handle_rx.findall(r["text"]))) if handle_rx else []
        phs = len(set(ph.findall(r["text"])))
        rec_tags.append(evidence)
        rec_stages.append(stages)
        rec_handles.append(hs)
        rec_ph.append(phs)
        for t in tags:
            beh_count[t] += 1
            beh_by_kind[t][r["kind"]] += 1
        for t in evidence:
            pass
        for s in stages:
            stage_recs[s].add(i)
        for h in hs:
            handle_count[h] += 1
        for x in range(len(tags)):
            for y in range(x + 1, len(tags)):
                pair_count[(tags[x], tags[y])] += 1

    # threads
    root = roots_of(records)
    thread_size = Counter(root.values())
    thread_kinds = defaultdict(Counter)
    for r in records:
        thread_kinds[root[r["id"]]][r["kind"]] += 1

    # families
    fam_ids, ranked, norm = families(records, ph)

    # summaries
    behaviors_rows = []
    for b in behaviors:
        c = beh_count.get(b["name"], 0)
        kinds_txt = ", ".join(f"{k} {v:,}" for k, v in beh_by_kind[b["name"]].most_common())
        behaviors_rows.append((b["name"], b["stage"], c, round(100 * c / n, 2), kinds_txt, b.get("description", "")))
    behaviors_rows.sort(key=lambda x: -x[2])
    stage_rows = sorted(((s, len(v), round(100 * len(v) / n, 2)) for s, v in stage_recs.items()), key=lambda x: -x[1])
    handle_rows = handle_count.most_common()
    pair_rows = [(a_, b_, c) for (a_, b_), c in pair_count.most_common(15)]
    thread_rows = []
    for rt, sz in thread_size.most_common(20):
        thread_rows.append((rt, sz, ", ".join(f"{k} {v}" for k, v in thread_kinds[rt].most_common())))
    fam_rows = []
    fam_sizes = [len(m) for _, m in ranked]
    for root_i, mem in ranked[:25]:
        kc = Counter(records[i]["kind"] for i in mem)
        fam_rows.append((fam_ids[mem[0]], len(mem), ", ".join(f"{k} {v}" for k, v in kc.most_common()), norm[root_i][:180]))

    with_tag = sum(1 for t in rec_tags if t)
    gaps = {
        "no_time": sum(1 for t in times if not t),
        "no_parent": sum(1 for r in records if not r["parent"]),
        "has_placeholder": sum(1 for p in rec_ph if p),
        "no_handle": sum(1 for h in rec_handles if not h) if handle_rx else n,
        "no_tag": n - with_tag,
    }
    S = {
        "rules_name": rules.get("name", os.path.basename(a.rules)),
        "profile": {"records": n, "columns": columns, "kinds": dict(kinds.most_common()), "time_note": time_note},
        "records_with_any_tag": with_tag,
        "records_with_any_tag_pct": round(100 * with_tag / n, 2),
        "records_with_parent": sum(1 for r in records if r["parent"]),
        "threads": len(thread_size),
        "threads_singleton": sum(1 for v in thread_size.values() if v == 1),
        "families": len(ranked),
        "families_singleton": sum(1 for s in fam_sizes if s == 1),
        "families_10plus": sum(1 for s in fam_sizes if s >= 10),
        "records_in_families_10plus": sum(s for s in fam_sizes if s >= 10),
        "behaviors": {b: c for b, _, c, *_ in behaviors_rows},
        "stages": {s: c for s, c, _ in stage_rows},
        "handles": dict(handle_rows),
        "gaps": gaps,
    }

    # files
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(S, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out, "records.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "kind", "parent", "thread_root", "behavior_tags", "stages", "handles", "placeholders", "family", "time"])
        for i, r in enumerate(records):
            w.writerow([r["id"], r["kind"], r["parent"], root[r["id"]], "|".join(rec_tags[i]),
                        "|".join(rec_stages[i]), "|".join(rec_handles[i]), rec_ph[i], fam_ids[i], r["time"]])

    def simple_csv(name, header, rows):
        with open(os.path.join(a.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    simple_csv("behaviors.csv", ["behavior", "stage", "records", "pct", "by_kind", "description"],
               [[b, s, c, p, k, d] for b, s, c, p, k, d in behaviors_rows])
    simple_csv("stages.csv", ["stage", "records", "pct"], stage_rows)
    simple_csv("handles.csv", ["handle", "records"], handle_rows)
    simple_csv("pairs.csv", ["behavior_a", "behavior_b", "records"], pair_rows)
    simple_csv("threads.csv", ["thread_root", "records", "kinds"], thread_rows)
    simple_csv("families.csv", ["family", "records", "kinds", "preview"], fam_rows)

    title = a.title or f"Analysis: {os.path.basename(a.csv)}"
    write_report(os.path.join(a.out, "report.html"), title, S, behaviors_rows, stage_rows, handle_rows,
                 pair_rows, thread_rows, fam_rows)
    print(f"records {n:,}; tagged {with_tag:,} ({S['records_with_any_tag_pct']}%); "
          f"families {len(ranked):,}; threads {len(thread_size):,}")
    print(f"report: {os.path.join(a.out, 'report.html')}")


if __name__ == "__main__":
    main()

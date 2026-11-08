#!/usr/bin/env python3
"""Build a one-page HTML demo from the outputs of analyzer/flow.py.

Usage (from the project root, after running flow.py):
    python3 -I analyzer/flow_html.py redacted_columns.csv reports/flow

Writes reports/flow/flow_demo.html. Stdlib only.
"""
import csv
import html
import json
import os
import re
import sys

csv.field_size_limit(sys.maxsize)


def esc(x):
    return html.escape(str(x))


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def excerpt(text, n=220):
    return esc(re.sub(r"\s+", " ", text)[:n]) + ("…" if len(text) > n else "")


def main(argv):
    src, out = argv[1], argv[2]
    summary = json.load(open(os.path.join(out, "flow_summary.json"), encoding="utf-8"))
    early = json.load(open(os.path.join(out, "early_flag.json"), encoding="utf-8"))
    artifacts = read_csv(os.path.join(out, "artifacts.csv"))
    edges = read_csv(os.path.join(out, "edges.csv"))
    reuse = read_csv(os.path.join(out, "thread_reuse_check.csv"))
    attribution = read_csv(os.path.join(out, "attribution.csv"))

    # Text of the records behind the first flags, so the page shows the evidence itself.
    wanted = set()
    ff = early["rule_thread_reuse"]["first_reuse_across_threads"]
    if ff:
        wanted.add(ff["id"])
    fam = early["first_shared_artifact"]
    if fam:
        wanted.add(fam["id"])
    texts = {}
    with open(src, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["id"] in wanted:
                texts[row["id"]] = row["text"]

    att_counts = {}
    for r in attribution:
        att_counts[r["how"]] = att_counts.get(r["how"], 0) + 1
    total = summary["records"]

    def kpi(label, value):
        return f'<div class="kpi"><b>{esc(value)}</b><span>{esc(label)}</span></div>'

    rule_t = early["rule_thread_reuse"]
    edge_html = (
        "<p><b>No edges between controller families.</b> No artifact name in this release is shared by two families, "
        "so the who-talked-to-whom graph is empty. This is the main result, not a bug.</p>"
        if not edges else
        "<table><thead><tr><th>from</th><th>to</th><th>mentions</th><th>write then read</th><th>evidence</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(e['from_family'])}</td><td>{esc(e['to_family'])}</td><td>{esc(e['shared_artifact_mentions'])}</td>"
                  f"<td>{esc(e['strong_write_then_read'])}</td><td class='mono'>{esc(e['evidence'])}</td></tr>" for e in edges)
        + "</tbody></table>"
    )

    art_rows = "".join(
        f"<tr><td class='mono'>{esc(a['artifact'])}</td><td>{esc(a['family'])}</td><td>{esc(a['records'])}</td>"
        f"<td>{esc(a['first_id'])}</td><td>{esc(a['last_id'])}</td><td>{esc(a['families_touching'])}</td></tr>"
        for a in artifacts[:25])

    reuse_sorted = sorted(reuse, key=lambda r: -int(r["threads"]))[:25]
    reuse_rows = "".join(
        f"<tr><td class='mono'>{esc(r['artifact'])}</td><td>{esc(r['threads'])}</td><td>{esc(r['records'])}</td>"
        f"<td>{esc(r['analyzer_families'])}</td><td>{esc(r['verdict'])}</td></tr>" for r in reuse_sorted)

    def flag_block(title, f):
        if not f:
            return f"<p><b>{esc(title)}:</b> none.</p>"
        return (f"<p><b>{esc(title)}:</b> {esc(f['id'])} (artifact <span class='mono'>{esc(f['artifact'])}</span>)</p>"
                f"<pre>{excerpt(texts.get(f['id'], '(text not found)'), 400)}</pre>")

    gaps = [
        f"{total:,} records. No timestamps, so the timeline is file order, not real time.",
        f"{att_counts.get('unattributed', 0):,} records ({att_counts.get('unattributed', 0) / total:.1%}) cannot be tied to any controller family.",
        "The release has no sender or receiver fields. Any edge would be inferred from a shared name.",
        "Artifact names come from a hand-built list. Names outside it are invisible.",
        "Thread reuse shows shared-resource access, not who sent what. Copies of one template would look the same.",
        "The report's cited records are chosen with hindsight, so the anchor counts are a consistency check only.",
    ]

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Flow reconstruction: demo</title>
<style>
body{{font:14px -apple-system,system-ui,sans-serif;margin:24px auto;max-width:1180px;color:#222;padding:0 16px}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin-top:30px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.lede{{color:#555;margin-top:0}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.kpi{{background:#f0f4f8;border-radius:8px;padding:10px 14px;min-width:150px}}
.kpi b{{display:block;font-size:20px}} .kpi span{{font-size:12px;color:#555}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}}
th,td{{text-align:left;padding:4px 6px;border-bottom:1px solid #eee;vertical-align:top}} th{{background:#f0f3f6}}
.mono{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;word-break:break-word}}
pre{{background:#fafafa;border:1px solid #e3e3e3;padding:8px;white-space:pre-wrap;word-break:break-word;font-size:12px}}
.callout{{background:#fff8e6;border-left:4px solid #e0a800;padding:10px 14px;margin:14px 0}}
</style></head><body>
<h1>Flow reconstruction: demo</h1>
<p class="lede">Who shared what, from the Swarm Traces release. Generated by analyzer/flow.py. Read the callouts before the numbers.</p>
<div class="kpis">
{kpi('records', f'{total:,}')}
{kpi('attributed to a family', f"{total - att_counts.get('unattributed', 0):,}")}
{kpi('artifacts (names)', f"{summary['artifacts']:,}")}
{kpi('artifacts across 2+ families', summary['artifacts_across_2plus_families'])}
{kpi('edges between families', summary['edges'])}
{kpi('artifacts reused across threads', f"{rule_t['artifacts_reused_across_threads']:,}")}
</div>
<div class="callout"><b>Bottom line.</b> The data does not show who talked to whom. Every shared name belongs to one family,
so the graph has no edges. The only pattern is shared-resource access across runs, which starts at
{esc(rule_t['first_reuse_across_threads']['id'] if rule_t['first_reuse_across_threads'] else 'n/a')}, and it may be copies of one template rather than coordination.</div>

<h2>1. Who can be attributed</h2>
<p>Attribution order: a handle in the record's own text, then a controller file name in the text, then the thread's handle.</p>
<table><thead><tr><th>how</th><th>records</th><th>share</th></tr></thead><tbody>
{''.join(f"<tr><td>{esc(k)}</td><td>{v:,}</td><td>{v / total:.2%}</td></tr>" for k, v in sorted(att_counts.items(), key=lambda kv: -kv[1]))}
</tbody></table>

<h2>2. Edges between families</h2>
{edge_html}

<h2>3. Most-used artifact names (top 25 by records)</h2>
<table><thead><tr><th>artifact</th><th>family</th><th>records</th><th>first</th><th>last</th><th>families touching</th></tr></thead>
<tbody>{art_rows}</tbody></table>

<h2>4. Early flag</h2>
<p>Replay in file order. Timestamps are missing, so this is order, not time.</p>
{flag_block('First artifact shared by two families', early['first_shared_artifact'])}
{flag_block('First artifact reused across two threads', rule_t['first_reuse_across_threads'])}
<p>Cited records (anchors) checked: {early['anchors_checked']}. At or after the family flag: {early['anchors_after_family_flag']}.
At or after the thread-reuse flag: {early['anchors_after_thread_flag']}. Anchors are chosen with hindsight, so this is a consistency check.</p>

<h2>5. Thread reuse, with a check</h2>
<p>{rule_t['artifacts_reused_across_threads']:,} artifacts appear in two or more threads. {rule_t['likely_template_copies']} have all their records in one known family.
{rule_t['mixed_or_unknown']} have mixed or unknown families. Most records have no family, so this split mostly shows missing attribution.</p>
<table><thead><tr><th>artifact</th><th>threads</th><th>records</th><th>known families</th><th>verdict</th></tr></thead>
<tbody>{reuse_rows}</tbody></table>

<h2>6. What an investigator would still miss</h2>
<ul>{''.join(f'<li>{esc(g)}</li>' for g in gaps)}</ul>
</body></html>"""
    with open(os.path.join(out, "flow_demo.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote", os.path.join(out, "flow_demo.html"))


if __name__ == "__main__":
    main(sys.argv)

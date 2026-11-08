#!/usr/bin/env python3
"""Build one page that answers the question, with confidence and measured precision.

Usage (from the project root, after analyze.py, flow.py and the label file exist):
    python3 -I analyzer/answer.py --out reports/answer

Inputs: reports/swarm-traces/summary.json, reports/flow/flow_summary.json,
        reports/flow/early_flag.json, reports/swarm-traces/labels.json
Output: reports/answer/index.html
"""
import argparse
import html
import json
import os
from collections import defaultdict


def esc(x):
    return html.escape(str(x))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/answer")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    tags = json.load(open("reports/swarm-traces/summary.json", encoding="utf-8"))
    flow = json.load(open("reports/flow/flow_summary.json", encoding="utf-8"))
    early = json.load(open("reports/flow/early_flag.json", encoding="utf-8"))
    labels = json.load(open("reports/swarm-traces/labels.json", encoding="utf-8"))

    agg = defaultdict(lambda: {"n": 0, "tp": 0, "fp": 0, "unclear": 0})
    controls = {"n": 0, "missed": 0, "clean": 0, "unclear": 0}
    for r in labels:
        if r["rule"] == "none":
            controls["n"] += 1
            if r["label"] == 1:
                controls["missed"] += 1
            elif r["label"] == 0:
                controls["clean"] += 1
            else:
                controls["unclear"] += 1
            continue
        g = agg[r["rule"]]
        g["n"] += 1
        if r["label"] == 1:
            g["tp"] += 1
        elif r["label"] == 0:
            g["fp"] += 1
        else:
            g["unclear"] += 1

    def prec_row(rule):
        g = agg.get(rule, {"n": 0, "tp": 0, "fp": 0, "unclear": 0})
        j = g["tp"] + g["fp"]
        lo, hi = wilson(g["tp"], j)
        return g, j, lo, hi

    rule_note = {
        "repo_commit": "Tightened after labeling (the old pattern matched README reads). Not re-measured.",
        "captcha_or_waf": "Tightened after labeling. Not re-measured.",
    }
    prec_rows = []
    for rule in sorted(agg):
        g, j, lo, hi = prec_row(rule)
        prec = f"{100 * g['tp'] / j:.0f}%" if j else "n/a"
        ci = f"{100 * lo:.0f}–{100 * hi:.0f}%" if j else "n/a"
        prec_rows.append(
            f"<tr><td class='mono'>{esc(rule)}</td><td>{g['n']}</td><td>{j}</td><td>{prec}</td><td>{ci}</td>"
            f"<td>{esc(rule_note.get(rule, ''))}</td></tr>")

    ctrl_missed_pct = 100 * controls["missed"] / max(1, controls["missed"] + controls["clean"])

    claims = [
        ("Agents sent data by HTTP POST, often with an API key or bearer token.",
         f"http_post: {esc(prec_row('http_post')[1])} judged, precision {100*agg['http_post']['tp']/max(1,prec_row('http_post')[1]):.0f}%; "
         f"api_key_or_bearer precision {100*agg['api_key_or_bearer']['tp']/max(1,prec_row('api_key_or_bearer')[1]):.0f}%.",
         "High", "Sample size is 10 per rule, so the interval is wide, but the pattern is visible in most samples."),
        ("Agents ran identity and system-recon commands on target machines.",
         f"runs_shell precision {100*agg['runs_shell']['tp']/max(1,prec_row('runs_shell')[1]):.0f}% of {prec_row('runs_shell')[1]} judged; "
         f"identity_recon {100*agg['identity_recon']['tp']/max(1,prec_row('identity_recon')[1]):.0f}% of {prec_row('identity_recon')[1]}.",
         "High", "Commands are visible in the code. Whether they ran, and their output, is not in the release."),
        ("Agents used named mailbox boards on a package registry.",
         f"mailbox_or_board_marker precision {100*agg['mailbox_or_board_marker']['tp']/max(1,prec_row('mailbox_or_board_marker')[1]):.0f}% of {prec_row('mailbox_or_board_marker')[1]} judged.",
         "Medium", "Only 4 judged cases. The board names are visible, but who wrote to them is not."),
        ("Controllers used signed command files to receive instructions.",
         f"signed_command_channel precision {100*agg['signed_command_channel']['tp']/max(1,prec_row('signed_command_channel')[1]):.0f}% of {prec_row('signed_command_channel')[1]} judged.",
         "Medium", "Small sample. Command files are named, but there is no record of a command being sent and acted on."),
        ("Two controller families shared a name, so one could have passed information to another.",
         f"{flow['edges']} edges between families; {flow['artifacts_across_2plus_families']} artifact names shared by 2+ families.",
         "High that the names do not show it", "This is a null result from name matching. A link that uses no shared name would not be seen."),
        ("Information moved across separate runs through shared names.",
         f"{early['rule_thread_reuse']['artifacts_reused_across_threads']} names appear in 2+ threads; "
         f"{early['rule_thread_reuse']['mixed_or_unknown']} have mixed or unknown families.",
         "Low", "Most reuse may be one request repeated, or copied code. Not shown to be coordination."),
        ("The coordination could have been flagged early.",
         "No timestamps; the flag runs in file order only.",
         "Not testable", "The release cannot answer this without dates. Anchor results are a consistency check, since the anchors were chosen with hindsight."),
    ]
    claim_rows = "".join(
        f"<tr><td>{esc(c)}</td><td>{ev}</td><td><b>{esc(conf)}</b></td><td>{esc(gap)}</td></tr>"
        for c, ev, conf, gap in claims)

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>What the swarm release shows</title>
<style>
body{{font:14px -apple-system,system-ui,sans-serif;margin:24px auto;max-width:1100px;color:#222;padding:0 16px}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}} th{{background:#f0f3f6}}
.mono{{font-family:ui-monospace,Menlo,monospace;font-size:12px}}
.answer{{background:#eef4fb;border-left:4px solid #3b6ea5;padding:12px 16px;font-size:15px;margin:14px 0}}
.note{{color:#666;font-size:12.5px}}
</style></head><body>
<h1>What the swarm release shows</h1>
<p class="note">{tags['profile']['records']:,} records from the redacted Swarm Traces release. Every claim below names its evidence, its measured precision, and what is still missing.</p>

<div class="answer"><b>Answer.</b> The release shows what the agents tried to do: post data with API keys, run identity and system commands, use registry boards and signed command files. It does not show who talked to whom. No name is shared between two controller families, so the family graph has no edges, and the timing of any coordination cannot be tested.</div>

<h2>Claims, with evidence and confidence</h2>
<table><thead><tr><th>Claim</th><th>Evidence (measured on the labeled sample)</th><th>Confidence</th><th>What is still missing</th></tr></thead>
<tbody>{claim_rows}</tbody></table>

<h2>Measured precision of each rule</h2>
<p class="note">Each rule was checked by reading a random sample of the records it tags. "Judged" excludes records that could not be read from the 230-character preview. Intervals are 95% Wilson intervals, which are wide at these sample sizes. One labeler (the analyst) did all the labels, so this is not an inter-rater measure.</p>
<table><thead><tr><th>Rule</th><th>Sampled</th><th>Judged</th><th>Precision</th><th>95% interval</th><th>Note</th></tr></thead>
<tbody>{''.join(prec_rows)}</tbody></table>

<h2>Recall: behavior the rules miss</h2>
<p>Of {controls['n']} records that the rules tag with nothing, {controls['missed']} visibly contain behavior the rules do not tag ({ctrl_missed_pct:.0f}% of judged controls), and {controls['clean']} do not. Most of the missed behavior is code that loads a second script through a link-shortener chain. That pattern appears in {tags['behaviors'].get('remote_script_or_shortener', 0):,} records and is kept as context rather than evidence, because it is a delivery method, not an action.</p>

<h2>What the tags are, and are not</h2>
<ul>
<li>Tags count only evidence rules. Generic browser code (page writes, plain network calls, base64) is marked as context and does not count.</li>
<li>A tag means the text matches a pattern that usually indicates the behavior. It does not mean the code ran or succeeded.</li>
<li>{tags['records_with_any_tag']:,} records ({tags['records_with_any_tag_pct']}%) carry at least one evidence tag.</li>
</ul>

<h2>What an investigator would still miss</h2>
<ul>
<li>Who sent each message: the release has no sender or receiver fields.</li>
<li>When anything happened: timestamps are empty, except a few unix numbers in names that fall on two days.</li>
<li>Whether a command ran, and its output: most command cards have no response in the release.</li>
<li>Coordination that uses no shared name, which the name-matching graph cannot see.</li>
<li>Anything outside the hand-built name and handle lists.</li>
</ul>
</body></html>"""
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote", os.path.join(a.out, "index.html"))


if __name__ == "__main__":
    main()

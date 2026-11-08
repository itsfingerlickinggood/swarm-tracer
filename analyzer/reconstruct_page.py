#!/usr/bin/env python3
"""Build a simple page from reports/reconstruct/summary.json.

Usage (from the project root, after reconstruct.py):
    python3 -I analyzer/reconstruct_page.py reports/reconstruct
"""
import html
import json
import os
import sys

INTENT_LABEL = {
    "submit_to_eval_api": "Submit to the evaluation API", "hf_read": "Read from Hugging Face",
    "hf_dataset_write": "Write to Hugging Face datasets", "docker_registry": "Use the Docker registry",
    "kubernetes_api": "Call the Kubernetes API", "registry_board": "Use a mailbox board on the package registry",
    "cloud_metadata": "Query cloud metadata", "search_for_secrets": "Search the web for secrets",
    "shortener_chain": "Load code through link shorteners", "other": "Other",
}
COLORS = {
    "submit_to_eval_api": "#9aa5b1", "hf_read": "#7fb3e6", "hf_dataset_write": "#2f6fb3", "docker_registry": "#e3a43b",
    "kubernetes_api": "#c0392b", "registry_board": "#8e44ad", "cloud_metadata": "#d35400", "search_for_secrets": "#16a085",
    "shortener_chain": "#cfd6dd", "other": "#e8ecf0",
}
SIGNAL_LABEL = {
    "first_registry_board_write": "First write to a mailbox board",
    "first_use_of_acquired_credential": "First use of a token that appeared earlier in another record",
    "first_secret_search": "First web search for tokens",
    "first_hf_dataset_write": "First write to a Hugging Face dataset",
    "first_kubernetes_request": "First Kubernetes API request",
    "first_board_shared_by_two_principals": "First board used by two tokens in separate records",
    "first_principal_handling_another_credential": "First token seen carrying another token before its use",
}


def esc(x):
    return html.escape("" if x is None else str(x))


def table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def timeline_svg(by_hour):
    hours = sorted(by_hour)
    if not hours:
        return ""
    order = ["hf_dataset_write", "hf_read", "kubernetes_api", "docker_registry", "registry_board", "cloud_metadata",
             "search_for_secrets", "submit_to_eval_api", "shortener_chain", "other"]
    totals = [sum(by_hour[h].values()) for h in hours]
    mx = max(totals)
    W, H, left, bottom = 860, 240, 40, 40
    bw = (W - left - 10) / len(hours)
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img"><title>Requests per estimated hour, by intent</title>']
    for k, h in enumerate(hours):
        y = H - bottom
        for intent in order:
            v = by_hour[h].get(intent, 0)
            if not v:
                continue
            hh = (H - bottom - 10) * v / mx
            y -= hh
            parts.append(f'<rect x="{left + k * bw:.1f}" y="{y:.1f}" width="{max(1, bw - 1):.1f}" height="{hh:.1f}" fill="{COLORS[intent]}">'
                         f'<title>{esc(h)}:00 {esc(INTENT_LABEL[intent])}: {v}</title></rect>')
        if k % 12 == 0:
            parts.append(f'<text x="{left + k * bw:.1f}" y="{H - bottom + 16}" font-size="11" fill="#555">{esc(h[5:].replace("T", " ").replace(" ", " "))}h</text>')
    parts.append(f'<text x="0" y="14" font-size="11" fill="#555">{mx}/h</text></svg>')
    legend = "".join(f'<span style="display:inline-block;margin:2px 12px 2px 0;font-size:13px"><span style="display:inline-block;width:10px;height:10px;background:{COLORS[i]};margin-right:5px"></span>{esc(INTENT_LABEL[i])}</span>' for i in order)
    return "".join(parts) + f"<div>{legend}</div>"


def main(argv):
    d = argv[1] if len(argv) > 1 else "reports/reconstruct"
    s = json.load(open(os.path.join(d, "summary.json"), encoding="utf-8"))
    tt, pt = s["time_test"], s["placeholder_test"]

    principals = [[esc(p["credential"]), f"{p['auth_uses']:,}", esc(p["first"]), esc(p["last"]),
                   esc(", ".join(INTENT_LABEL.get(k, k) for k in p["intents"]))] for p in s["top_principals"][:12]]
    acquired = [[esc(a["credential"]), esc(a["first_seen"]), esc(a["first_seen_id"]), esc(a["first_seen_kind"]),
                 esc(a["first_auth"]), f"{a['auth_uses']:,}", esc(a["lead_hours"])] for a in s["acquired_then_used"]]
    boards = [[esc(b["board"]), esc(" and ".join(b["principals"])), esc(b["first"]), esc(b["second"]),
               "one record (one actor holding two tokens)" if b["same_record"] else "separate records"] for b in s["shared_boards"]]
    handled = [[esc(e["from"]), esc(e["to"]), f"{e['payloads']}", esc(", ".join(e["evidence"]))] for e in s["handled_edges"][:15]]
    sig_rows = []
    for k, v in sorted(((k, v) for k, v in s["signals"].items() if v), key=lambda kv: kv[1]["time"]):
        sig_rows.append([esc(SIGNAL_LABEL.get(k, k)), esc(v["time"]), f"{100 * v['harmful_share_after']:.0f}%",
                         f"{100 * v['acquired_share_after']:.0f}%", esc(v["id"])])

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Who talked to whom, and how information spread</title>
<style>
body{{font:15px/1.55 -apple-system,system-ui,sans-serif;color:#222;margin:0}}
main{{max-width:920px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:17px;margin:34px 0 8px}}
.answer{{background:#eef4fb;border-left:4px solid #2f6fb3;padding:12px 16px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}}
td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}} th{{color:#555}}
.muted{{color:#666;font-size:13.5px}} code{{font-size:13px}}
ul li{{margin:4px 0}}
</style></head><body><main>
<h1>Who talked to whom, and how information spread</h1>
<p class="muted">Swarm Traces release, {s['records']:,} records ({s['payloads']:,} payloads). Built by analyzer/reconstruct.py.</p>

<div class="answer"><b>Answer.</b> The agents can be told apart by the tokens they authenticated with. {s['principals']} tokens were used to authenticate. Harvested tokens spread: some first appear inside another record and are then used to authenticate, hours later, hundreds of times. Two tokens used the same mailbox board in separate records on July 11 at 21:33, the first sign of coordination through a shared place. At that point, {100 * (s['signals']['first_board_shared_by_two_principals'] or {{}}).get('harmful_share_after', 0):.0f}% of the harmful requests were still to come.</div>

<h2>Two facts that make this possible</h2>
<ul>
<li><b>Redacted values are stable.</b> Each hidden value keeps one placeholder everywhere. Of {pt['credentials_seen_5_plus_times_as_auth']} tokens used to authenticate five or more times, {pt['with_one_role_90pct']} keep one role (for example <code>[CREDENTIAL 1]</code> is the <code>X-API-Key</code> in nearly every use). So a placeholder can stand for one token, one service or one repository across records.</li>
<li><b>Payload order is time order, for the first block.</b> In the first block of payloads ({tt['blocks'][0]['first_id']} to {tt['blocks'][0]['last_id']}, {tt['blocks'][0]['payloads']:,} payloads), timestamps written inside {tt['points']:,} of them rise with file order (rank correlation {tt['spearman_payload_order_vs_embedded_time']}). Fitting that relation gives each of those payloads an estimated time, with a median error of {tt['fit_error_hours_median']} hours (90% within {tt['fit_error_hours_p90']} hours). One outside check: the report dates the MARB051 comment to July 9, 20:54; the estimate for that record is about half an hour later. The other payload blocks ({sum(b['payloads'] for b in tt['blocks'][1:]):,} payloads) have too few timestamps, or timestamps that do not follow order, so they get no time and are left out of every timed result below.</li>
</ul>

<h2>What the agents were doing, hour by hour</h2>
<p class="muted">Requests per estimated hour, by what each request does. Estimated span: {esc(tt['estimated_span'][0])} to {esc(tt['estimated_span'][1])} UTC.</p>
{timeline_svg(s['intent_by_hour'])}

<h2>Who: the tokens that authenticated the most</h2>
<p class="muted">A token is not an agent: one agent can hold several tokens, and token 1 is a shared evaluation key used by every agent.</p>
{table(['token', 'uses as auth', 'first', 'last', 'mostly used to'], principals)}

<h2>How information spread: tokens seen before they were used</h2>
<p class="muted">A token that appears in another record (a recovered file or a response) before its first use to authenticate. Lead is the gap in hours. Very short leads may be the same program's own text, not a hand-off.</p>
{table(['token', 'first seen', 'in record', 'record kind', 'first used', 'uses', 'lead (h)'], acquired)}

<h2>Who talked to whom</h2>
<h3>Tokens that carried other tokens</h3>
<p class="muted">A request authenticated with one token carries another token as data, before that second token is first used. The first token's holder had the second token first.</p>
{table(['carrier token', 'carried token', 'payloads', 'evidence'], handled) if handled else '<p>None found.</p>'}
<h3>Mailbox boards used by two tokens</h3>
{table(['board', 'tokens', 'first use', 'second use', 'how'], boards) if boards else '<p>None found.</p>'}

<h2>Could it have been flagged early?</h2>
<p class="muted">Each signal's first estimated time, and how much of the later activity came after it, among timed payloads only. Harmful requests are Hugging Face dataset writes, Kubernetes calls, cloud metadata queries, Docker registry use and mailbox boards ({s['harmful_requests_total']:,} in all). Token uses counts uses of tokens that were seen before their first use ({s['acquired_token_uses_total']:,} in all).</p>
{table(['signal', 'first time (est.)', 'harmful requests still to come', 'token uses still to come', 'record'], sig_rows)}
<p class="muted">The single-agent signals (a board write, a token search) fire on July 9 and 10, before almost all of the harm. The coordination signals (two tokens on one board, one token carrying another) fire on July 11, with 40 to 60% still to come. A monitor watching only for coordination would have fired about two days after one watching for these single actions.</p>

<h2>What an investigator would still miss</h2>
<ul>
<li><b>Agents, not tokens.</b> The agent ID is redacted to one value for everyone, so the tool sees tokens. One agent with many tokens looks like many principals, and many agents sharing token 1 look like one.</li>
<li><b>Exact times.</b> Times are estimated from file order and are only as good as the fit. Payloads before the first timestamp or after the last are clamped to the ends of the range. Responses and recovered files only get a time through a parent payload.</li>
<li><b>Messages without a shared token or board.</b> Coordination through a channel that leaves no shared placeholder is invisible here.</li>
<li><b>What a token could do.</b> The redaction hides which account or scope each token belongs to.</li>
<li><b>Whether a request worked.</b> Most requests have no recorded response.</li>
<li><b>Intent labels.</b> They come from patterns on each request's target and are not hand-checked yet.</li>
</ul>
</main></body></html>"""
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote", os.path.join(d, "index.html"))


if __name__ == "__main__":
    main(sys.argv)

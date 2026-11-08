"""One HTML page for any analyzed trace set.

Order of the page: what each claim rests on (time and identity checks), what the agents
did over time, who they were, how information spread, who talked to whom, whether it could
have been flagged early, then tags with measured precision, and what the data cannot show.
The page states measurements. Conclusions are the reader's.
"""
import html

PALETTE = ["#2f6fb3", "#7fb3e6", "#c0392b", "#e3a43b", "#8e44ad", "#d35400", "#16a085", "#9aa5b1",
           "#cfd6dd", "#5d6d7e", "#27ae60", "#f1c40f"]


def esc(x):
    return html.escape("" if x is None else str(x))


def table(headers, rows):
    if not rows:
        return '<p class="muted">None found.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def share(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def hourly_chart(by_hour, intents):
    hours = sorted(by_hour)
    if not hours:
        return '<p class="muted">No timed records, so no timeline.</p>'
    order = [k for k in intents if k != "other"] + (["other"] if "other" in intents else [])
    color = {k: PALETTE[i % len(PALETTE)] for i, k in enumerate(order)}
    mx = max(sum(by_hour[h].values()) for h in hours)
    W, H, L, B = 880, 230, 46, 36
    bw = (W - L - 10) / len(hours)
    step = max(1, len(hours) // 12)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img"><title>Records per hour by intent</title>']
    for k, h in enumerate(hours):
        y = H - B
        for intent in order:
            v = by_hour[h].get(intent, 0)
            if v:
                hh = (H - B - 10) * v / mx
                y -= hh
                out.append(f'<rect x="{L + k * bw:.1f}" y="{y:.1f}" width="{max(1, bw - 1):.1f}" height="{hh:.1f}" '
                           f'fill="{color[intent]}"><title>{esc(h)}h {esc(intent)}: {v}</title></rect>')
        if k % step == 0:
            out.append(f'<text x="{L + k * bw:.1f}" y="{H - B + 15}" font-size="11" fill="#555">{esc(h[5:])}h</text>')
    out.append(f'<text x="0" y="14" font-size="11" fill="#555">{mx}/h</text></svg>')
    legend = "".join(f'<span class="lg"><i style="background:{color[k]}"></i>{esc(k)}</span>' for k in order)
    return "".join(out) + f"<div>{legend}</div>"


def render(res, pack_name, title, prec=None, rec=None):
    n = res["records"]
    g = res["gaps"]
    rec = rec or {}
    tt = rec.get("time_test", {})
    it = rec.get("identity_test", {})
    prec_tags = (prec or {}).get("tags", {})

    # ---- checks
    timed = n - tt.get("untimed", n)
    blocks = tt.get("blocks", [])
    block_rows = [[esc(b["kind"]), esc(b["first_id"]), esc(b["last_id"]), f"{b['records']:,}", f"{b['timestamp_points']:,}",
                   esc(b["spearman"]), "yes" if b["timed"] else "no",
                   esc(b.get("fit_error_hours_median", "")), esc(b.get("clamped_to_range_end", ""))] for b in blocks]
    src = tt.get("source", {})
    time_line = (f"{timed:,} of {n:,} records have a time ({', '.join(f'{k.replace(chr(95), chr(32))} {v:,}' for k, v in src.items())}). "
                 + (f"Span {esc(tt['span'][0])} to {esc(tt['span'][1])} UTC." if tt.get("span") else ""))
    id_line = (f"{it.get('with_one_role_90pct', 0)} of {it.get('tokens_used_5_plus', 0)} identity tokens used five or more times "
               f"keep one role in at least 90% of uses." if it.get("tokens_used_5_plus") else
               "No identity tokens repeat often enough to test stability.")

    # ---- tables
    ident_rows = [[esc(p["identity"]), f"{p['uses']:,}", esc(p["first"]), esc(p["last"]),
                   esc(", ".join(p["roles"])), esc(", ".join(p["intents"]))] for p in rec.get("identities", [])[:15]]
    spread_rows = [[esc(r["item"]), esc(r["first_seen"]), esc(r["first_seen_id"]), esc(r["first_seen_kind"]),
                    esc(r["first_used"]), f"{r['uses']:,}", esc(r["lead_hours"])] for r in rec.get("seen_then_used", [])[:40]]
    carried_rows = [[esc(e["from"]), esc(e["to"]), f"{e['records']}", esc(", ".join(e["evidence"]))]
                    for e in rec.get("carried_edges", [])[:20]]
    place_rows = [[esc(p["place"]), esc(" and ".join(p["identities"][:4])), esc(p["first"]), esc(p["second"]),
                   "one record" if p["same_record"] else "separate records"] for p in rec.get("shared_places", [])[:20]]
    reply_rows = [[esc(a), esc(b), f"{c:,}"] for a, b, c in res["reply_edges"]]
    replay_rows = [[esc(r["signal"]), esc(r["time"]), share(r["harm_share_after"]), share(r["spread_share_after"]),
                    esc(r["hours_before_last"]), esc(r["ref"])] for r in rec.get("replay", [])]

    def prec_cell(tag):
        p = prec_tags.get(tag)
        if not p or p["precision"] is None:
            return "not measured"
        return f"{100 * p['precision']:.0f}% ({100 * p['ci_low']:.0f}–{100 * p['ci_high']:.0f}%, n={p['judged']})"

    ev_rows = [[esc(t), f"{c:,}", pct(c, n), prec_cell(t)] for t, c in res["evidence_tags"].items()]
    ctx_rows = [[esc(t), f"{c:,}", pct(c, n)] for t, c in res["context_tags"].items()]
    ctrl = (prec or {}).get("controls")
    recall_line = (f"Of {ctrl['n']} records with no evidence tag, {ctrl['missed']} visibly contain behavior the tags miss "
                   f"({100 * ctrl['miss_rate']:.0f}% of judged controls)." if ctrl and ctrl.get("miss_rate") is not None
                   else "Recall not measured. Run the sample step and fill in control labels to measure it.")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
html{{color-scheme:light}} body{{font:15px/1.55 -apple-system,system-ui,sans-serif;color:#222;background:#fff;margin:0}}
main{{max-width:960px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:34px 0 6px}} h3{{font-size:15px;margin:18px 0 4px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0}}
td,th{{text-align:left;padding:5px 7px;border-bottom:1px solid #eee;vertical-align:top}} th{{color:#555}}
.muted{{color:#666;font-size:13.5px}} .lg{{display:inline-block;margin:2px 12px 2px 0;font-size:12.5px}}
.lg i{{display:inline-block;width:10px;height:10px;margin-right:5px}}
.kpi{{display:inline-block;margin:6px 22px 6px 0;font-size:13px;color:#555}} .kpi b{{display:block;font-size:19px;color:#222}}
</style></head><body><main>
<h1>{esc(title)}</h1>
<p class="muted">Pack: {esc(pack_name)}. Every number below is a measurement; tags are pattern matches.</p>
<div>
<span class="kpi"><b>{n:,}</b>records</span>
<span class="kpi"><b>{pct(timed, n)}</b>with a time</span>
<span class="kpi"><b>{rec.get('identities_total', 0):,}</b>identities</span>
<span class="kpi"><b>{len(rec.get('seen_then_used', [])):,}</b>items seen, then used</span>
<span class="kpi"><b>{rec.get('carried_edges_total', 0):,}</b>carried-token links</span>
<span class="kpi"><b>{sum(1 for p in rec.get('shared_places', []) if not p['same_record']):,}</b>places shared by two identities</span>
</div>

<h2>1. What the results rest on</h2>
<h3>Time</h3>
<p>{time_line}</p>
<p class="muted">Records without a time field are timed from unix seconds in their text only if the pack allows it and the block's timestamps are dense and rise with file order. Blocks with timestamps:</p>
{table(['kind', 'first', 'last', 'records', 'timestamps', 'rank corr.', 'timed', 'median error (h)', 'clamped'], block_rows)}
<h3>Identity</h3>
<p>{id_line} A token stands for one holder only if it is stable; check this before reading the identity results.</p>

<h2>2. What the agents did over time</h2>
{hourly_chart(rec.get('activity_by_hour', {}), list(rec.get('intents', {}).keys()))}

<h2>3. Who: identities by activity</h2>
<p class="muted">An identity is the actor field, or a token the pack names (for example an auth credential). One agent can hold several tokens; one shared token can stand for many agents.</p>
{table(['identity', 'uses', 'first', 'last', 'roles', 'mostly'], ident_rows)}

<h2>4. How information spread</h2>
<p class="muted">Items first seen as data in one record and later used as an identity. Very short leads may be one program's own text, not a hand-off.</p>
{table(['item', 'first seen', 'record', 'kind', 'first used', 'uses', 'lead (h)'], spread_rows)}

<h2>5. Who talked to whom</h2>
<h3>One identity carried another's token before it was used</h3>
{table(['carrier', 'carried', 'records', 'evidence'], carried_rows)}
<h3>Two identities used the same place</h3>
{table(['place', 'identities', 'first', 'second', 'how'], place_rows)}
<h3>Replies between identities</h3>
{table(['from', 'to', 'replies'], reply_rows)}

<h2>6. Could it have been flagged early?</h2>
<p class="muted">Each signal's first time, and the share of later timed harmful activity ({rec.get('harm_events_timed', 0):,} records) and later uses of seen-then-used items ({rec.get('spread_uses_timed', 0):,}) that came after it.</p>
{table(['signal', 'first time', 'harm still to come', 'spread still to come', 'hours before last record', 'record'], replay_rows)}

<h2>7. Tags and their accuracy</h2>
{table(['evidence tag', 'records', '% of records', 'precision (95% interval, judged n)'], ev_rows)}
<p class="muted">Context tags (shown, not counted as evidence):</p>
{table(['context tag', 'records', '% of records'], ctx_rows)}
<p>{esc(recall_line)}</p>

<h2>8. What this data does not show</h2>
<ul>
<li>{n - timed:,} records have no time, so they are left out of the timeline and the early-flag replay.</li>
<li>{g['no_actor']:,} records have no actor field and no identity token, so they cannot be attributed.</li>
<li>{g['no_parent']:,} records have no parent link.</li>
<li>Links that leave no shared token, place, or reply are invisible.</li>
<li>Whether an action succeeded is only known where the data records a result.</li>
</ul>
</main></body></html>"""

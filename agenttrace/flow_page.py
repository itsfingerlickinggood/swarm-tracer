"""HTML page for message flow: who talked to whom through which channels, and how content spread."""
import html
import math
from collections import Counter


def esc(x):
    return html.escape("" if x is None else str(x))


def short(a):
    return a.replace("[CREDENTIAL ", "cred ").replace("]", "") if a else a


def table(headers, rows):
    if not rows:
        return '<p class="muted">None found.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def network_svg(pairs, max_nodes=16):
    deg = Counter()
    for p in pairs:
        deg[p["from"]] += p["deliveries"]
        deg[p["to"]] += p["deliveries"]
    nodes = [n for n, _ in deg.most_common(max_nodes)]
    if len(nodes) < 2:
        return '<p class="muted">Too few named actors to draw.</p>'
    W, H, R = 880, 520, 200
    cx, cy = W / 2, H / 2
    pos = {n: (cx + R * math.cos(2 * math.pi * i / len(nodes) - math.pi / 2),
               cy + R * math.sin(2 * math.pi * i / len(nodes) - math.pi / 2)) for i, n in enumerate(nodes)}
    mx = max(p["deliveries"] for p in pairs)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img"><title>Who delivered messages to whom</title>',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
           '<path d="M0,0 L10,5 L0,10 z" fill="#2f6fb3"/></marker></defs>']
    for p in pairs:
        a, b = p["from"], p["to"]
        if a not in pos or b not in pos:
            continue
        (x1, y1), (x2, y2) = pos[a], pos[b]
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 1
        x1, y1 = x1 + dx / d * 16, y1 + dy / d * 16
        x2, y2 = x2 - dx / d * 18, y2 - dy / d * 18
        # bend so that a->b and b->a do not overlap
        mxp, myp = (x1 + x2) / 2 - dy / d * 18, (y1 + y2) / 2 + dx / d * 18
        w = 0.8 + 5 * math.log1p(p["deliveries"]) / math.log1p(mx)
        out.append(f'<path d="M{x1:.1f},{y1:.1f} Q{mxp:.1f},{myp:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="#2f6fb3" '
                   f'stroke-opacity="0.55" stroke-width="{w:.2f}" marker-end="url(#ah)"><title>{esc(short(a))} to {esc(short(b))}: '
                   f'{p["deliveries"]} deliveries over {p["channels"]} channels, first {esc(p["first"])}</title></path>')
    for n in nodes:
        x, y = pos[n]
        r = 6 + 10 * math.sqrt(deg[n] / deg[nodes[0]])
        lx = x + (r + 6) * (1 if x >= cx else -1)
        anchor = "start" if x >= cx else "end"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#e3a43b" stroke="#fff"><title>{esc(n)}: {deg[n]} deliveries</title></circle>')
        out.append(f'<text x="{lx:.1f}" y="{y + 4:.1f}" font-size="12" text-anchor="{anchor}" fill="#333">{esc(short(n))}</text>')
    out.append("</svg>")
    return "".join(out)


def render(flow, rec, title):
    ct = flow["channel_types"]
    ak = flow["actors_on_channels"]
    lat = flow["latency_hours"]
    fnd = flow["first_named_delivery"]
    coord = [r for r in rec.get("replay", []) if r["signal"].startswith("coordination")]

    type_rows = [[esc(t), f"{v['channels']:,}", f"{v['writes']:,}", f"{v['reads']:,}", f"{v['deliveries']:,}",
                  f"{v['never_read']:,}"] for t, v in sorted(ct.items(), key=lambda kv: -kv[1]["deliveries"])]
    pair_rows = [[f"<code>{esc(short(p['from']))}</code>", f"<code>{esc(short(p['to']))}</code>", f"{p['deliveries']}",
                  f"{p['channels']}", esc(p["first"])] for p in flow["top_pairs"][:20]]
    ch_rows = [[f"<code>{esc(c['channel'])}</code>", c["writes"], c["reads"], c["writers"], c["readers"], c["deliveries"],
                esc(c["median_latency_h"]), esc(c["first_write"])] for c in flow["top_channels"][:20]]
    spread_rows = []
    for s in flow["content_spread"][:20]:
        ad = ", ".join(f"{esc(short(a['actor']))} (+{a['hours_after_source']} h)" for a in s["adopters"][:5])
        if len(s["adopters"]) > 5:
            ad += f", and {len(s['adopters']) - 5} more"
        spread_rows.append([f"<code>{esc(s['family'])}</code>", s["copies"], f"<code>{esc(short(s['source']))}</code>",
                            esc(s["source_time"]), f"<code>{esc(s['source_record'])}</code>", ad])

    fany = flow.get("first_named_delivery_any_channel")
    coarse_note = (f" An earlier possible delivery, {esc(short(fany['from']))} to {esc(short(fany['to']))} at {esc(fany['read_time'])}, "
                   f"is on <code>{esc(fany['channel'])}</code>, a channel the redaction reduced to its owner, so it may join two different places."
                   if fany and fnd and fany["read_id"] != fnd["read_id"] else "")
    first_line = (f"The first message between two named actors on a specific channel: <code>{esc(short(fnd['from']))}</code> writes to "
                  f"<code>{esc(fnd['channel'])}</code> in <code>{esc(fnd['write_id'])}</code> at {esc(fnd['write_time'])}, and "
                  f"<code>{esc(short(fnd['to']))}</code> reads it in <code>{esc(fnd['read_id'])}</code> at {esc(fnd['read_time'])}."
                  if fnd else "No delivery between two named actors was found.")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(title)}: message flow</title>
<style>
html{{color-scheme:light}}
body{{font:15px/1.6 -apple-system,system-ui,sans-serif;color:#222;background:#fff;margin:0}}
main{{max-width:980px;margin:0 auto;padding:28px 20px 70px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:34px 0 8px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}} td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}} th{{color:#555}}
.muted{{color:#666;font-size:13.5px}} code{{font-size:13px;background:#f3f5f7;padding:0 3px;border-radius:3px}}
.box{{background:#eef4fb;border-left:4px solid #2f6fb3;padding:12px 16px;margin:14px 0}}
.kpi{{display:inline-block;margin:6px 24px 6px 0;font-size:13px;color:#555}} .kpi b{{display:block;font-size:20px;color:#222}}
</style></head><body><main>
<h1>{esc(title)}: who talked to whom</h1>
<p class="muted">Built by <code>agenttrace flow</code>. A channel is a place agents write to and read from. A delivery is a read of a channel after a write by a different actor.</p>
<div>
<span class="kpi"><b>{flow['records_on_channels']:,}</b>records that touch a channel</span>
<span class="kpi"><b>{flow['channels']:,}</b>channels</span>
<span class="kpi"><b>{flow['deliveries']:,}</b>dated deliveries</span>
<span class="kpi"><b>{flow['deliveries_between_named_actors']:,}</b>between named actors</span>
<span class="kpi"><b>{flow['named_actor_pairs']:,}</b>named sender-receiver pairs</span>
<span class="kpi"><b>{esc(lat['median'])} h</b>median time to be read</span>
</div>

<div class="box">{first_line} {f"At that point {100 * flow['harm_share_after_first_named_delivery']:.0f}% of the timed harmful activity was still to come." if flow.get('harm_share_after_first_named_delivery') is not None else ""}{coarse_note}
{f"The earlier coordination signals, from shared tokens and places, first fire at {esc(coord[0]['time'])}, so watching channels is the earlier signal." if coord else ""}</div>

<h2>1. Who delivered messages to whom</h2>
<p class="muted">Named actors only (identity tokens and handles). Arrow width grows with the number of deliveries. Hover for counts.</p>
{network_svg(flow['top_pairs'])}
{table(['sender', 'receiver', 'deliveries', 'channels', 'first delivery'], pair_rows)}

<h2>2. The channels and how they performed</h2>
{table(['channel type', 'channels', 'writes', 'reads', 'deliveries', 'written, never read by another actor'], type_rows)}
<p class="muted">Busiest channels. Latency is the median time from the write to the read that picked it up.</p>
{table(['channel', 'writes', 'reads', 'writers', 'readers', 'deliveries', 'median latency (h)', 'first write'], ch_rows)}

<h2>3. How content spread between actors</h2>
<p class="muted">The same program, with ids masked, sent under several named actors. The first is the source; the rest adopted it, this many hours later. {flow['content_families_moving']:,} programs moved between two or more named actors.</p>
{table(['program', 'copies', 'source', 'source time', 'source record', 'adopted by'], spread_rows)}

<h2>4. What this does not show</h2>
<ul>
<li><b>Most senders are anonymous.</b> Of the actors on channels, {ak.get('token', 0):,} are identity tokens, {ak.get('handle', 0):,} are named handles, and {ak.get('run', 0):,} are single runs with no name. A run is one submitted program and its replies, not an agent.</li>
<li><b>A token is not an agent.</b> One agent can hold several tokens, so a delivery between two tokens may be one agent talking to itself. The same program under several tokens may be one agent trying tokens in turn.</li>
<li><b>Retries are not messages.</b> {flow.get('reads_dropped_as_same_program', 0):,} reads were dropped because the only earlier write was the same program, rerun under another actor.</li>
<li><b>Order needs dates.</b> {flow['deliveries_order_unknown']:,} reads follow a write by another actor on the same channel but cannot be ordered because one side has no time.</li>
<li><b>A read is an attempt.</b> The release rarely shows whether the read succeeded or what it returned.</li>
<li><b>Channel names are redacted pseudonyms.</b> Some redactions keep only the owner's name, so several repositories of one owner can merge into one channel. {flow.get('coarse_channel_deliveries', 0):,} deliveries are on such channels; the headline first delivery leaves them out.</li>
<li><b>Channels outside the pack are invisible.</b> Messages passed through a place the pack does not list, or with no shared place at all, are not counted.</li>
</ul>
</main></body></html>"""

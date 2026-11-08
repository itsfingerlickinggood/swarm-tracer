"""HTML page that sets each report claim beside what the traces show."""
import html


def esc(x):
    return html.escape("" if x is None else str(x))


def render(results, cfg, rec, title):
    n = len(results)
    found = sum(1 for r in results if r["records"])
    cited_total = sum(len(r["cited"]) for r in results)
    cited_found = sum(r["cited_found"] for r in results)
    cited_matched = sum(r["cited_matched"] for r in results)
    cited_timed = sum(r["cited_timed"] for r in results)
    coord = [r for r in results if r["two_identities_separately"]]
    coord_sig = next((x for x in rec.get("replay", []) if x["signal"].startswith("coordination")), None)

    rows = []
    for r in results:
        c2 = r["two_identities_separately"]
        rows.append("<tr>"
                    f"<td><a href='#{esc(r['id'])}'>{esc(r['section'])}</a><div class='muted'>{esc(r['id'])}</div></td>"
                    f"<td class='n'>{r['records']:,}</td>"
                    f"<td>{esc(r['first_time'] or 'no time')}</td>"
                    f"<td class='n'>{r['identities']}</td>"
                    f"<td>{esc(c2['time'] if c2 else 'no')}</td>"
                    f"<td>{r['cited_found']}/{len(r['cited'])} found, {r['cited_matched']} matched, {r['cited_timed']} dated</td>"
                    "</tr>")

    details = []
    for r in results:
        spread = "".join(f"<li><code>{esc(s['identity'])}</code>{' (shared by many agents)' if s.get('shared') else ''} "
                         f"first at {esc(s['first_time'] or 'unknown time')} (<code>{esc(s['record'])}</code>)</li>"
                         for s in r["spread"][:8])
        items = "".join(f"<li><code>{esc(i['item'])}</code> in {i['records']} records, first in <code>{esc(i['first_record'])}</code></li>"
                        for i in r["recurring_items"])
        places = "".join(f"<li><code>{esc(p['place'])}</code>: {p['records']} records in {p['threads']} threads, "
                         f"first in <code>{esc(p['first_record'])}</code>"
                         + (f", dated {esc(p['first'])} to {esc(p['last'])}" if p['first'] else ", not dated") + "</li>"
                         for p in r["place_spread"])
        cited = "".join(f"<li><code>{esc(x['id'])}</code>: "
                        + ("not in the data" if not x["in_data"] else
                           f"{esc(x['kind'])}, {'matches' if x['matches_patterns'] else 'does not match'} the patterns, "
                           f"{'time ' + esc(x['time']) if x['time'] else 'no time'}")
                        + "</li>" for x in r["cited"])
        kinds = ", ".join(f"{esc(k)} {v:,}" for k, v in r["by_kind"].items())
        details.append(f"""
<section id="{esc(r['id'])}">
<h3>{esc(r['section'])}</h3>
<p><b>Report says:</b> {esc(r['says'])}</p>
<p><b>In the traces:</b> {r['records']:,} records ({kinds or 'none'}), in {r['threads']:,} threads.
{f"Dated from {esc(r['first_time'])} (<code>{esc(r['first_record'])}</code>) to {esc(r['last_time'])}, {r['timed_records']:,} records dated." if r['first_time'] else "None of these records can be dated."}</p>
<p><b>Who took part, in order of first appearance:</b> {r['identities']} identities.</p>
{f'<ul>{spread}</ul>' if spread else '<p class="muted">No identity token appears in these records.</p>'}
{f"<p><b>Two identities, separate records:</b> yes, from {esc(r['two_identities_separately']['time'] or 'unknown time')} (<code>{esc(r['two_identities_separately']['identity'])}</code> in <code>{esc(r['two_identities_separately']['record'])}</code>).</p>" if r['two_identities_separately'] else ''}
{f'<p><b>Information that recurs across these records:</b></p><ul>{items}</ul>' if items else ''}
{f'<p><b>Shared places these records use, and how far each spread:</b></p><ul>{places}</ul>' if places else ''}
<p><b>Records the report cites:</b></p>
{f'<ul>{cited}</ul>' if cited else '<p class="muted">The report cites none.</p>'}
</section>""")

    missing = [r for r in results if not r["records"]]
    undated = [r for r in results if r["records"] and not r["first_time"]]
    no_ident = [r for r in results if r["records"] and not r["identities"]]

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
html{{color-scheme:light}}
body{{font:15px/1.6 -apple-system,system-ui,sans-serif;color:#222;background:#fff;margin:0}}
main{{max-width:980px;margin:0 auto;padding:28px 20px 70px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:34px 0 8px}} h3{{font-size:16px;margin:28px 0 6px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}} td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}}
th{{color:#555}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.muted{{color:#666;font-size:13px}} code{{font-size:13px;background:#f3f5f7;padding:0 3px;border-radius:3px}}
.box{{background:#eef4fb;border-left:4px solid #2f6fb3;padding:12px 16px;margin:14px 0}}
section{{border-top:1px solid #eee}}
</style></head><body><main>
<h1>{esc(title)}</h1>
<p class="muted">Claims from <a href="{esc(cfg.get('source', ''))}">{esc(cfg['name'])}</a>, checked against the traces with <code>agenttrace claims</code>.</p>

<div class="box">
<b>Summary.</b> {found} of {n} report claims show up in the traces. The report cites {cited_total} records: {cited_found} are in the data, {cited_matched} match the claim's patterns, and {cited_timed} can be dated.
{len(coord)} claims involve two or more identities in separate records, which is the signature of coordination this tool can see.
{f"The earliest coordination signal in the whole release is at {esc(coord_sig['time'])}." if coord_sig else ""}
</div>

<h2>Claims at a glance</h2>
<table><thead><tr><th>report section</th><th>records</th><th>first dated</th><th>identities</th><th>two identities, separately</th><th>cited records</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>

<h2>What an investigator would still miss</h2>
<ul>
<li>Claims the traces do not show at all: {', '.join(esc(r['section']) for r in missing) or 'none'}.</li>
<li>Claims shown only in records that cannot be dated: {', '.join(esc(r['section']) for r in undated) or 'none'}. Their place in the timeline, and whether they could have been flagged early, is unknown.</li>
<li>Claims whose records carry no identity token: {', '.join(esc(r['section']) for r in no_ident) or 'none'}. For these, who did it cannot be told from the traces.</li>
<li>An identity here is a token, not an agent: one agent can hold many tokens, and a shared key stands for many agents. Keys the pack marks as shared are left out of every coordination count.</li>
<li>Patterns find text, not success. A matching record shows an attempt, not that it worked.</li>
</ul>

<h2>Each claim</h2>
{''.join(details)}
</main></body></html>"""

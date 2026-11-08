// Overview: the incident in one screen. Context from the public reports (when a context file matches
// the dataset), the whole incident on one chart, short answers to the challenge's questions, and what
// the swarm is made of. Every number is counted from the records or quoted with its source.
"use strict";
(() => {
  async function overview(el, s) {
    el.innerHTML = '<div id="ovw"><p class="muted">Loading…</p></div>';
    const [ctxR, sim, lanes, gapsR] = await Promise.all([
      cached("/api/context").catch(() => ({})), cached("/api/sim").catch(() => null),
      cached("/api/lanes").catch(() => null), cached("/api/gaps").catch(() => ({ rows: [] }))]);
    const ctx = ctxR.context, ms = ctxR.milestones;
    const f = s.flow, T = s.list_totals || {};
    const named = Object.entries(s.actor_kinds || {}).filter(([k]) => k !== "run").reduce((a, [, v]) => a + v, 0);
    const sigs = sim?.signals || [];
    const firstOf = (fam) => sigs.find((g) => g.family === fam);
    const j = firstOf("joint"), sg = firstOf("single"), bl = firstOf("baseline");
    const host = $("ovw");
    host.innerHTML = `
    ${ctx ? brief(ctx) : `<div class="card ovnoctx"><h2>${esc(s.name)}</h2><p class="muted small">No incident report is linked to this dataset, so this page shows only what the records say. To add context, put a file like <code>agenttrace/claims/incident_context.json</code> with a <code>match</code> rule for this dataset.</p></div>`}
    ${card("The incident at a glance", '<div id="glance"></div><div id="glancekey" class="legend"></div>',
      { sub: `Timed actions per hour, coloured by what the code does${ctx ? "; the investigators' phases above; " : "; "}warning signs as dots (blue: actors together, dark: a single actor, grey: volume baseline)${ms?.milestones?.length ? "; below, each time the reports give against the tool's estimate" : ""}. Click an hour to list its events.` })}
    <h3 class="ovh">Answers to the challenge</h3>
    <div class="grid2 answers">
      ${answer("Who talked to whom", "network", f.named_actor_pairs ? `<b>${fmt(f.named_actor_pairs)}</b> named sender-receiver pairs exchanged <b>${fmt(f.deliveries_between_named_actors)}</b> messages, read a median <b>${hoursWord(f.latency_hours.median)}</b> after they were written.` : "No message between two named actors was found.",
        (f.top_pairs || []).length ? hbars(f.top_pairs.slice(0, 5).map((p) => ({ label: `${ent.actor(p.from)} → ${ent.actor(p.to)}`, value: p.deliveries, color: ACCENT }))) : "",
        f.first_named_delivery ? `First: ${ent.actor(f.first_named_delivery.from)} wrote ${ent.rec(f.first_named_delivery.write_id)}, ${ent.actor(f.first_named_delivery.to)} read it in ${ent.rec(f.first_named_delivery.read_id)} (${esc(f.first_named_delivery.read_time)})` : "")}
      ${answer("How information spread", "spread", spreadLine(s, T),
        (s.content_spread || []).length ? hbars(s.content_spread.slice(0, 5).map((x) => ({ label: `${ent.actor(x.source)} <span class="muted small">${esc(x.what?.intent_what ? x.what.intent_what.split(" (")[0] : "")}</span>`, value: x.actors, color: C.program }))) + '<p class="small muted">actors reached by each program</p>' : "",
        s.seen_then_used?.length ? `${fmt(T.seen_then_used ?? s.seen_then_used.length)} tokens were seen as data before their first use; ${fmt(T.carried_edges ?? 0)} times one identity carried another's token.` : "")}
      ${answer("Could it have been flagged early?", "early", j ? `The first sign of actors working together, <b>${esc(j.name.toLowerCase())}</b>, fired on ${esc(when(toTime(j.time)))} with <b>${pct(j.harm_share_after)}</b> of the harmful activity still to come.` : "No sign of actors working together fired.",
        famBars(sigs), bl ? `A volume alarm would have fired on ${esc(when(toTime(bl.time)))} with ${pct(bl.harm_share_after)} still to come.` : "")}
      ${answer("What an investigator would still miss", "gaps", "The biggest blind spots, measured:",
        hbars((gapsR.rows || []).filter((g) => g.share != null).sort((a, b) => b.share - a.share).slice(0, 4).map((g) => ({ label: esc(g.gap), value: Math.round(g.share * 1000) / 10, color: HARM, title: g.hides }))) , "Share of records, messages or places affected (%).")}
    </div>
    <h3 class="ovh">The swarm by the numbers</h3>
    <div class="kpis">
      ${kpi("records", fmt(s.records), Object.entries(s.kinds).map(([k, v]) => `${fmt(v)} ${esc(k)}`).join(" · "))}
      ${kpi("dated", pct(s.timed / s.records), `${fmt(s.timed)} records`)}
      ${kpi("named actors", fmt(named), `${fmt(s.actor_kinds?.run || 0)} anonymous runs`)}
      ${kpi("places", fmt(f.channels), `${fmt(f.records_on_channels)} records touch one`)}
      ${kpi("messages", fmt(f.deliveries), `${fmt(f.deliveries_between_named_actors)} between named actors`)}
      ${kpi("programs shared", fmt(T.content_spread ?? f.content_families_moving), "run by 2+ actors")}
      ${kpi("warning signs", fmt(sigs.length), `${sigs.filter((g) => g.family === "joint").length} of actors together`)}
      ${kpi("harmful actions", fmt(sim?.harm_total ?? s.harm_events_timed), "timed")}
    </div>
    <div class="grid2">
      ${card("What the swarm is made of", anatomy(s), { sub: "Each bar is one whole, split by kind. Hover a segment for its count." })}
      ${card("What the agents did", hbars(Object.entries(s.intents).map(([k, v]) => ({ label: `${esc(human(k))}${isHarm(k) ? ' <span class="harmtag">harm</span>' : ""}`, value: v, color: intentColor(k), title: intentName(k), attrs: `data-click data-intent="${esc(k)}"` })), { total: Object.values(s.intents).reduce((a, b) => a + b, 0) }), { sub: "Actions by what the code does (pattern match). Click one to list its events." })}
    </div>
    ${card("Most active actors", '<div id="ovactors"></div>', { sub: "Named actors by timed actions, with their activity across the whole incident. Hover for a card, click to inspect." })}
    ${ctx ? reported(ctx, ms) : ""}
    <details class="card ovmethod"><summary><h3>How the data was read</h3></summary>${method(s)}</details>`;

    host.querySelectorAll(".hb[data-intent]").forEach((b) => b.addEventListener("click", () => goEvents({ intent: b.dataset.intent })));
    host.querySelectorAll("[data-gotab]").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.gotab)));
    const g = $("glance");
    const draw = () => glance(g, s, sim, ctx, ms);
    draw(); onResize(g, draw);
    if (lanes) leaders($("ovactors"), lanes);
  }

  function spreadLine(s, T) {
    const w = s.content_spread?.[0];
    if (!w) return "No program was run by more than one named actor.";
    const last = Math.max(...w.adopters.map((a) => a.hours_after_source));
    return `<b>${fmt(T.content_spread ?? s.content_spread.length)}</b> programs were run by more than one named actor. The widest, first run by ${ent.actor(w.source)} (${ent.rec(w.source_record)}), reached <b>${fmt(w.actors - 1)}</b> more actors within <b>${hoursWord(last)}</b>.`;
  }
  function famBars(sigs) {
    const rows = ["single", "joint", "baseline"].map((fam) => {
      const xs = sigs.filter((g) => g.family === fam && g.harm_share_after != null);
      if (!xs.length) return null;
      const first = xs[0];
      return { label: `${FAMILY[fam].label} <span class="muted small">${esc(when(toTime(first.time)))}</span>`, value: Math.round(first.harm_share_after * 100), color: FAMILY[fam].color, title: first.name };
    }).filter(Boolean);
    return rows.length ? hbars(rows, { max: 100, unit: "%" }) + '<p class="small muted">harm still to come when each kind of sign first fired</p>' : "";
  }
  function answer(title, tab, line, viz, foot) {
    return `<section class="card answer"><header><h3>${esc(title)}</h3><button type="button" class="link" data-gotab="${tab}">Open →</button></header><p class="aline">${line}</p>${viz || ""}${foot ? `<p class="small muted afoot">${foot}</p>` : ""}</section>`;
  }

  // ---------------------------------------------------------------- incident brief from the reports
  function brief(ctx) {
    const nums = (ctx.numbers || []).slice(0, 8);
    return `<section class="card brief">
      <div class="bkicker">Incident brief <span class="muted">from public reports, not from the records</span></div>
      <h2>${esc(ctx.title)}</h2>
      <div class="bnums">${nums.map((n) => `<div title="${esc(n.source || "")}"><b>${esc(n.value)}</b><span>${esc(n.label)}</span></div>`).join("")}</div>
      <p class="bsum">${esc(ctx.summary)}</p>
      ${ctx.swarm ? `<details class="bmore"><summary>The swarm: what it was, its agents, their task, how they coordinated</summary><div class="bswarm">${[["The swarm", ctx.swarm.what], ["Agents", ctx.swarm.agents], ["Their task", ctx.swarm.task], ["How they coordinated", ctx.swarm.setup]].filter(([, v]) => v).map(([k, v]) => `<div><span>${esc(k)}</span>${esc(v)}</div>`).join("")}</div></details>` : ""}
      <p class="small muted bsrc">Sources: ${(ctx.sources || []).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(String(x.name).split(" - ")[0].split(",")[0])}</a>`).join(" · ")}</p>
    </section>`;
  }
  function reported(ctx, ms) {
    const list = (items, f) => `<ul class="rlist">${(items || []).map(f).join("")}</ul>`;
    const mrows = ms?.milestones || [];
    const mx = Math.max(1, ...mrows.map((m) => Math.abs(m.difference_h || 0)));
    return `<h3 class="ovh">What the investigators reported, and what the data shows</h3>
    ${mrows.length ? card("Report times against the tool's estimates", `<div class="dumb">${mrows.map((m) => `<div class="drow"><div class="dlab">${esc(m.event)}<span class="muted small"> ${esc(m.source)}</span></div><div class="dbar"><i class="mid"></i>${m.difference_h != null ? `<i class="v" style="left:${50 + 50 * Math.max(-1, Math.min(1, m.difference_h / Math.max(3, mx)))}%"></i>` : ""}</div><div class="dval">${m.difference_h == null ? "–" : (m.difference_h > 0 ? "+" : "") + m.difference_h + " h"}</div></div>`).join("")}<div class="drow axis"><div></div><div class="dbar"><span style="left:0">${-Math.max(3, mx).toFixed(0)} h (tool earlier)</span><span style="left:50%">0</span><span style="right:0">+${Math.max(3, mx).toFixed(0)} h</span></div><div></div></div></div>`,
      { sub: `Each row: a moment the reports date, and how far the tool's estimate from the records lands from it. ${mrows.filter((m) => m.difference_h != null && Math.abs(m.difference_h) <= 3).length} of ${mrows.length} fall within 3 hours.` }) : ""}
    <div class="grid2">
      ${card("Actors the reports name", list(ctx.actors, (a) => `<li><b>${esc(a.name)}</b> ${esc(a.what)} <span class="src">${esc(a.source)}</span></li>`))}
      ${card("Channels the reports describe", list(ctx.channels, (a) => `<li><b>${esc(a.name)}</b> ${esc(a.what)} <span class="src">${esc(a.source)}</span></li>`))}
      ${card("Harms", list(ctx.harms, (a) => `<li><b>${esc(a.name)}</b> ${esc(a.what)} <span class="src">${esc(a.source)}</span></li>`))}
      ${card("Detection and response", list(ctx.detection, (a) => `<li>${a.time ? `<b>${esc(a.time)}</b> ` : ""}${esc(a.what)} <span class="src">${esc(a.source)}</span></li>`))}
    </div>
    ${ctx.dataset ? card("About this dataset, per its authors", `<p>${esc(ctx.dataset.what)}</p><p class="small"><b>Records:</b> ${esc(ctx.dataset.records)}<br><b>Redaction:</b> ${esc(ctx.dataset.redaction)}</p>`, { sub: esc(ctx.dataset.source || "") }) : ""}
    ${(ctx.open_questions || []).length ? card("Questions the reports leave open", list(ctx.open_questions, (q) => `<li>${esc(q)}</li>`)) : ""}`;
  }

  // ---------------------------------------------------------------- the whole incident on one chart
  function glance(host, s, sim, ctx, ms) {
    const hours = Object.keys(s.activity_by_hour).sort();
    if (!hours.length) { host.innerHTML = '<p class="muted">No timed records, so no chart.</p>'; return; }
    const tot = Object.fromEntries(hours.map((h) => [h, Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0)]));
    const intents = Object.entries(s.intents).sort((a, b) => (a[0] === "other") - (b[0] === "other") || b[1] - a[1]).map(([k]) => k);
    const W = Math.max(380, host.clientWidth || 700);
    const phases = (ctx?.phases || []).map((p) => ({ ...p, t: toTime(p.start) })).filter((p) => p.t != null).sort((a, b) => a.t - b.t);
    const t0 = toTime(hours[0]), t1 = toTime(hours.at(-1)) + 3600e3;
    const x0 = 46, x1 = W - 10;
    const X = (t) => x0 + (Math.max(t0, Math.min(t1, t)) - t0) / (t1 - t0) * (x1 - x0);
    const rowRep = phases.length ? 22 : 0, rowSig = 20, chartH = 150, rowMs = ms?.milestones?.length ? 26 : 0;
    const yRep = 4, ySig = yRep + rowRep + 4, yT = ySig + rowSig + 4, yB = yT + chartH, yMs = yB + 8, H = yMs + rowMs + 22;
    const mx = Math.max(...Object.values(tot)), Y = (v) => yB - v / mx * chartH;
    const bw = Math.max(1, (x1 - x0) / ((t1 - t0) / 3600e3) - 0.6);
    let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="The incident at a glance">`;
    // report phases: one segment from each phase's start to the next
    if (phases.length) {
      svg += `<text x="${x0 - 6}" y="${yRep + 13}" text-anchor="end" font-size="10" fill="${QUIET}">reports</text>`;
      const shades = ["#e8eef6", "#dde7f3", "#d2e0ef", "#c7d8ec", "#bcd1e8", "#b1c9e4", "#a6c2e1", "#9bbadd", "#90b3d9"];
      phases.forEach((p, i) => {
        const a = p.t, b = phases[i + 1]?.t ?? (toTime(p.end) || t1);
        if (b < t0 || a > t1) return;
        const xa = X(a), xb = X(Math.min(b, t1));
        if (xb - xa < 1) return;
        svg += `<g><rect x="${xa}" y="${yRep}" width="${Math.max(2, xb - xa - 1)}" height="18" rx="3" fill="${shades[i % shades.length]}" stroke="#fff"/><title>${esc(p.name)} (from ${esc(p.start)}): ${esc(p.what)} (${esc(p.source)})</title>${xb - xa > 60 ? `<text x="${xa + 5}" y="${yRep + 12.5}" font-size="10" fill="#28466b">${esc(fitName(p.name, xb - xa - 10, "10px sans-serif"))}</text>` : ""}</g>`;
      });
    }
    // grid and bars
    const step = mx > 2000 ? 1000 : mx > 500 ? 250 : mx > 100 ? 50 : mx > 20 ? 10 : 2;
    for (let v = 0; v <= mx; v += step) svg += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${x0 - 6}" y="${Y(v) + 3.5}" text-anchor="end" font-size="10" fill="${QUIET}">${fmt(v)}</text>`;
    hours.forEach((h) => {
      let y = yB; const x = X(toTime(h));
      intents.forEach((it) => { const v = s.activity_by_hour[h][it] || 0; if (!v) return; const hh = v / mx * chartH; y -= hh;
        svg += `<rect data-hour="${esc(h)}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(2)}" height="${hh.toFixed(2)}" fill="${intentColor(it)}"><title>${esc(when(toTime(h)))} · ${esc(human(it))}: ${fmt(v)} (hour total ${fmt(tot[h])})</title></rect>`; });
    });
    // the data's own moments
    let lastLx = -99, lrow = 0;
    (s.phases || []).filter((p) => ["surge", "peak", "stop"].includes(p.key)).forEach((p) => {
      const x = X(toTime(p.time));
      lrow = x - lastLx < 34 ? lrow + 1 : 0; lastLx = x;
      svg += `<line x1="${x}" x2="${x}" y1="${yT}" y2="${yB}" stroke="${INK}" stroke-dasharray="3 3" stroke-opacity=".45"/><text x="${x + 3}" y="${yT + 10 + lrow * 11}" font-size="10" fill="${INK}" fill-opacity=".75">${esc({ surge: "surge", peak: "peak", stop: "drop" }[p.key])}<title>${esc(p.name)} ${esc(p.time)}${p.why ? ": " + esc(p.why) : ""}</title></text>`;
    });
    svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    // signals
    svg += `<text x="${x0 - 6}" y="${ySig + 12}" text-anchor="end" font-size="10" fill="${QUIET}">signs</text>`;
    let lastX = -99, lane = 0;
    (sim?.signals || []).forEach((g) => {
      const x = X(g.t * 1000); lane = x - lastX < 9 ? (lane + 1) % 2 : 0; lastX = x;
      svg += `<circle cx="${x}" cy="${ySig + 6 + lane * 8}" r="4.2" fill="${FAMILY[g.family]?.color || SINGLE}" stroke="#fff" stroke-width="1"${g.ref && /^[A-Za-z]\d{3,}$/.test(g.ref) ? ` data-id="${esc(g.ref)}"` : ""}><title>${esc(g.name)}, ${esc(g.time)}: ${pct(g.harm_share_after)} of the harm still to come. ${esc(g.why)}</title></circle>`;
    });
    // report times against the tool's estimates
    if (rowMs) {
      svg += `<text x="${x0 - 6}" y="${yMs + 14}" text-anchor="end" font-size="10" fill="${QUIET}">check</text>`;
      ms.milestones.forEach((m, i) => {
        const a = toTime(m.source_time), b = toTime(m.ours);
        if (a == null) return;
        const y = yMs + 6 + (i % 3) * 7;
        if (b != null) svg += `<line x1="${X(a)}" x2="${X(b)}" y1="${y}" y2="${y}" stroke="${ACCENT}" stroke-width="2"/><circle cx="${X(b)}" cy="${y}" r="3" fill="${ACCENT}"/>`;
        svg += `<path d="M${X(a)},${y - 4}L${X(a) + 4},${y}L${X(a)},${y + 4}L${X(a) - 4},${y}Z" fill="#fff" stroke="${INK}" stroke-width="1.2"><title>${esc(m.event)} — report ${esc(m.source_time)} (${esc(m.source)}), tool ${esc(m.ours || "–")}: ${m.difference_h == null ? "" : (m.difference_h > 0 ? "+" : "") + m.difference_h + " h"}</title></path>`;
      });
    }
    timeTicks(t0, t1, Math.max(3, Math.floor(W / 110))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 4}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${H - 6}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    host.innerHTML = svg + "</svg>";
    host.querySelectorAll("rect[data-hour]").forEach((r) => r.addEventListener("click", () => goEvents({ hour: r.dataset.hour })));
    $("glancekey").innerHTML = intents.filter((k) => s.intents[k]).map((k) => `<span><i style="background:${intentColor(k)}"></i>${esc(human(k))}</span>`).join("") +
      (rowMs ? `<span><svg width="10" height="10"><path d="M5,1L9,5L5,9L1,5Z" fill="#fff" stroke="${INK}"/></svg> report time</span><span><i style="background:${ACCENT};border-radius:50%"></i>tool estimate</span>` : "");
  }

  // ---------------------------------------------------------------- composition
  function anatomy(s) {
    const f = s.flow;
    const kc = ["#2f6fb3", "#6aa5dc", "#bcd3ec", "#9aa5b1", "#cfd6dd"];
    const recs = Object.entries(s.kinds).map(([k, v], i) => ({ label: k, value: v, color: kc[i % kc.length] }));
    const ak = s.actor_kinds || {};
    const actorWord = { token: "tokens", token_via_thread: "tokens via thread", handle: "self-chosen names", named: "actor field", run: "anonymous runs" };
    const actors = Object.entries(ak).sort((a, b) => (a[0] === "run") - (b[0] === "run") || b[1] - a[1]).map(([k, v], i) => ({ label: actorWord[k] || k, value: v, color: k === "run" ? "#cfd6dd" : ["#b7791f", "#e3a43b", "#f3c97a", "#f9e2b5"][i % 4] }));
    const pc = ["#6b46c1", "#9a7be0", "#c4b1ef", "#e0d6f7"];
    const places = Object.entries(f.channel_types || {}).sort((a, b) => b[1].channels - a[1].channels).map(([k, v], i) => ({ label: placeType(k), value: v.channels, color: pc[i % pc.length] }));
    const hc = { "read in code": "#2e7d32", "named the place": "#c58a00", "posted after it": "#e3a43b", "kept earlier content": "#2f6fb3" };
    const how = Object.entries(f.deliveries_by_how || {}).map(([k, v]) => ({ label: k, value: v, color: hc[k] || "#9aa5b1" }));
    const row = (title, parts, note) => `<div class="anat"><div class="anh"><b>${esc(title)}</b>${note ? `<span class="muted small">${note}</span>` : ""}</div>${stackbar(parts, { h: 14 })}</div>`;
    return row("Records by kind", recs, fmt(s.records)) + row("Actors by kind", actors, "named actors and anonymous runs") +
      (places.length ? row("Places by type", places, fmt(f.channels)) : "") + (how.length ? row("Messages by what they rest on", how, fmt(f.deliveries)) : "");
  }

  function leaders(host, lanes) {
    const rows = lanes.actors.filter((a) => a.kind !== "runs").sort((a, b) => b.total - a.total).slice(0, 12);
    if (!rows.length) { host.innerHTML = '<p class="muted">No named actors with timed actions.</p>'; return; }
    const t0 = toTime(lanes.start), t1 = t0 + lanes.hours * 3600e3;
    const series = (a) => a.bins.map((b) => [new Date(t0 + b[0] * 3600e3).toISOString().slice(0, 13).replace("T", " "), b.slice(1).reduce((x, y) => x + y, 0)]);
    const max = Math.max(...rows.map((a) => a.total));
    host.innerHTML = `<table class="leaders"><thead><tr><th>actor</th><th>activity over the incident</th><th class="n">actions</th><th class="n">harmful</th><th class="n">sent</th><th class="n">received</th><th>first seen</th></tr></thead><tbody>${rows.map((a) => `<tr>
      <td>${ent.actor(a.actor)}</td><td>${spark(series(a), { w: 190, h: 22, t0, t1, color: C.actor })}</td>
      <td class="n"><span class="minibar"><i style="width:${(100 * a.total / max).toFixed(1)}%"></i></span>${fmt(a.total)}</td>
      <td class="n">${a.harmful ? `${fmt(a.harmful)} <span class="muted small">${pct(a.harmful / a.total)}</span>` : "–"}</td>
      <td class="n">${fmt(a.sent)}</td><td class="n">${fmt(a.received)}</td><td class="small">${esc(a.first)}</td></tr>`).join("")}</tbody></table>`;
  }

  function method(s) {
    return `
    <p>Pack: <b>${esc(s.pack)}</b>${s.pack_choice ? ` <span class="muted">(picked automatically: ${esc(s.pack_choice.why)})</span>` : ""}.</p>
    ${(s.shared_identities || []).length ? `<p>Shared keys, never counted as actors: ${s.shared_identities.map((t) => ent.actor(t)).join(" ")}${(s.auto_shared || []).length ? ` <span class="muted">(found automatically: ${s.auto_shared.map((a) => `${esc(short(a.identity))} is used in ${pct(a.share_of_runs)} of the runs that carry a token`).join("; ")})</span>` : ""}.</p>` : ""}
    <h4>Files</h4>
    ${table(["file", "rows", "events", "fields found"], (s.read_report?.files || []).map((f) => [esc(f.file), fmt(f.rows), fmt(f.events),
      Object.entries(f.fields).map(([k, v]) => `${esc(k)}: <code>${esc(v.join(" → "))}</code>`).join("<br>")]))}
    <h4>Time</h4>
    <p class="small">${fmt(s.timed)} of ${fmt(s.records)} records have a time (${Object.entries(s.time_test.source || {}).map(([k, v]) => `${esc(human(k))} ${fmt(v)}`).join(", ") || "none"}). ${s.time_test.span ? `Span ${esc(s.time_test.span[0])} to ${esc(s.time_test.span[1])} UTC.` : ""} Where records have no time field, unix timestamps written in the code are fitted to file order within each block of one kind; a block is dated only if the fit passes a rank-correlation and error check.</p>
    ${table(["kind", "first", "last", "records", "timestamps", "rank corr.", "dated", "median err (h)"],
      (s.time_test.blocks || []).map((b) => [esc(b.kind), ent.rec(b.first_id), ent.rec(b.last_id), fmt(b.records), fmt(b.timestamp_points), esc(b.spearman), b.timed ? "yes" : `no${b.rejected ? " (" + esc(b.rejected) + ")" : ""}`, esc(b.fit_error_hours_median ?? "")]))}
    <h4>Identity</h4>
    <p class="small">${s.identity_test.tokens_used_5_plus ? `${s.identity_test.with_one_role_90pct} of ${s.identity_test.tokens_used_5_plus} identity tokens used 5+ times keep one role in at least 90% of uses.` : "No identity tokens repeat enough to test."}</p>
    <h4>Evidence tags</h4>${hbars(Object.entries(s.evidence_tags).slice(0, 15).map(([k, v]) => ({ label: esc(human(k)), value: v, title: tagName(k), color: "#5d6d7e" })), { total: s.records })}`;
  }

  VIEWS.overview = overview;
})();

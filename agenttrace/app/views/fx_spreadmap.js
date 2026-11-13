// Forensics › "Spread map", "One graph, three kinds of evidence", "Stage the incident": how information
// moved between estimated agents, which evidence says so, and what an agent already held before each
// attack stage. Every number comes from /api/x/spreadmap, /evidence and /spread_stages (cached server side).
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const HR = 3600e3;
  const TYPE = {
    message: { label: "message-carried", color: "#6b46c1" },
    content: { label: "content-only hand-over", color: "#0f766e" },
    behaviour: { label: "behaviour-only / independent adoption", color: "#d9822b" },
    unknown: { label: "unknown (no recorded carrier)", color: "#9aa5b1" },
    single: { label: "one holder", color: "#cdd3da" },
    origin: { label: "origin", color: "#1b2430" },
  };
  const KIND = { credential: "credential", file: "file or path", place: "place", host: "host", program: "program family", technique: "technique tag", string: "other string" };
  const KIND_COLOR = { credential: "#c2410c", file: "#2f6fb3", place: "#6b46c1", host: "#0f766e", program: "#b8579a", technique: "#d9822b", string: "#9aa5b1" };
  const ST = { kinds: new Set(["credential", "file", "place", "host", "program", "technique"]), item: null, vis: new Set(["message", "content", "behaviour"]), pair: null };
  const badge = (t, c = "") => `<span class="fxsb ${c}">${esc(t)}</span>`;
  const dot = (c) => `<i class="fxsd" style="background:${c}"></i>`;
  const typeTag = (t) => `<span class="fxst" style="--c:${(TYPE[t] || TYPE.unknown).color}"><i></i>${esc((TYPE[t] || TYPE.unknown).label)}</span>`;
  const kindTag = (k) => `<span class="fxsk" style="--c:${KIND_COLOR[k] || "#9aa5b1"}">${esc(KIND[k] || k)}</span>`;
  const cut = (t, n = 160) => { t = String(t ?? "").replace(/\s+/g, " "); return t.length > n ? t.slice(0, n - 1) + "…" : t; };
  const unitChip = (u) => (String(u).startsWith("run:") ? ent.actor(u) : ent.agent(u));
  const hrs = (h) => (h == null ? "–" : hoursWord(h));
  const goTrace = (q) => { location.hash = "tab=trace&q=" + encodeURIComponent(q); goTab("trace"); };
  const itemBtn = (x) => `<button type="button" class="fxsitem" data-item="${esc(x.item)}" title="${esc(x.item)}">${esc(cut(x.label, 40))}</button>`;
  const hex = (h) => esc(h);

  // ================================================================ 1. spread map
  function strips(host, r) {
    host.innerHTML = r.strips.length ? `<div class="fxsgrid">${r.strips.map((x, i) => strip(x, i)).join("")}</div>` : '<p class="muted">No item reached two agents with dated records in the chosen kinds.</p>';
  }
  function strip(x, i) {
    const pts = x.strip.points, W = 250, H = 66, L = 8, R = 10, T = 8, B = 20;
    const hmax = Math.max(1, x.span_h, ...pts.map((p) => p.hours));
    const px = (h) => L + (W - L - R) * (h / hmax), n = pts.length;
    const py = (j) => (n < 2 ? (T + H - B) / 2 : T + (H - T - B) * (j / (n - 1)));
    const line = pts.map((p, j) => `${px(p.hours).toFixed(1)},${py(j).toFixed(1)}`).join(" ");
    const ticks = [0, 0.5, 1].map((f) => `<text x="${(L + (W - L - R) * f).toFixed(1)}" y="${H - 5}" font-size="8.5" fill="#66717d" text-anchor="${f === 0 ? "start" : f === 1 ? "end" : "middle"}">${esc(hrs(f * hmax))}</text>`).join("");
    const marks = [["t25", 0.25], ["t50", 0.5], ["t90", 0.9]].filter(([k]) => x[k] != null).map(([k]) => `<line x1="${px(x[k]).toFixed(1)}" x2="${px(x[k]).toFixed(1)}" y1="${T - 2}" y2="${H - B + 2}" stroke="#c9d1d9" stroke-dasharray="2 2"/>`).join("");
    return `<div class="fxsstrip" data-item="${esc(x.item)}" tabindex="0" role="button" title="Open the full cascade of ${esc(x.label)}">
      <div class="fxshd">${kindTag(x.kind)} <b>${esc(cut(x.label, 34))}</b></div>
      <div class="fxsmeta small muted">${plural(x.agents, "agent")}${x.runs ? ` + ${plural(x.runs, "run")}` : ""} · 50% by ${esc(hrs(x.t50))}</div>
      <svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Cascade of ${esc(x.label)}: ${n} agents over ${esc(hrs(hmax))}">
        ${marks}<line x1="${L}" x2="${W - R}" y1="${H - B + 3}" y2="${H - B + 3}" stroke="#a3acb6"/>
        <polyline points="${line}" fill="none" stroke="#b6bfc9" stroke-width="1.2"/>
        ${pts.map((p, j) => `<circle cx="${px(p.hours).toFixed(1)}" cy="${py(j).toFixed(1)}" r="${j === 0 ? 4.4 : 3.2}" fill="${(TYPE[j === 0 ? "origin" : p.type] || TYPE.unknown).color}" stroke="#fff" stroke-width=".8"><title>${esc(short(p.unit))}: ${esc(hrs(p.hours))} after the origin (${esc(j === 0 ? "origin" : TYPE[p.type]?.label || p.type)})</title></circle>`).join("")}
        ${ticks}
      </svg>
      ${x.strip.points_total > pts.length ? `<div class="small muted">first ${pts.length} of ${x.strip.points_total} agents shown</div>` : ""}</div>`;
  }

  function scatter(host, r) {
    const xs = r.scatter;
    if (!xs.length) { host.innerHTML = '<p class="muted">Nothing to plot.</p>'; return; }
    const W = Math.max(520, Math.min(900, host.clientWidth || 800)), H = 330, L = 46, Rr = 14, T = 12, B = 38;
    const lx = (h) => Math.log10(1 + h), xmax = Math.max(...xs.map((p) => lx(p.t50)), 0.5), ymax = Math.max(...xs.map((p) => p.agents));
    const px = (h) => L + (W - L - Rr) * (lx(h) / xmax), py = (a) => H - B - (H - B - T) * ((a - 1.5) / (ymax - 1));
    const xt = [0, 1, 6, 24, 72].filter((h) => lx(h) <= xmax * 1.02), yt = [2, 5, 10, 20, 40].filter((a) => a <= ymax);
    let s = `<svg class="fxssvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Reach against speed for every item that reached two or more agents">`;
    xt.forEach((h) => { s += `<line x1="${px(h)}" x2="${px(h)}" y1="${T}" y2="${H - B}" stroke="#eef0f3"/><text x="${px(h)}" y="${H - B + 14}" font-size="10.5" fill="#66717d" text-anchor="middle">${esc(h === 0 ? "0" : hrs(h))}</text>`; });
    yt.forEach((a) => { s += `<line x1="${L}" x2="${W - Rr}" y1="${py(a)}" y2="${py(a)}" stroke="#eef0f3"/><text x="${L - 6}" y="${py(a) + 3.5}" font-size="10.5" fill="#66717d" text-anchor="end">${a}</text>`; });
    s += `<text x="${(L + W - Rr) / 2}" y="${H - 6}" font-size="11" fill="#3d4a58" text-anchor="middle">hours from the origin until half of the agents held it (log scale)</text><text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" font-size="11" fill="#3d4a58" text-anchor="middle">estimated agents that held it</text>`;
    // draw the common types first so the rarer ones stay on top
    const order = ["unknown", "behaviour", "content", "message"];
    xs.slice().sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type)).forEach((p) => {
      const jx = ((p.item.length * 7) % 9 - 4) * 0.25, jy = ((p.item.length * 13) % 9 - 4) * 0.18;
      s += `<circle class="fxspt" cx="${(px(p.t50) + jx).toFixed(1)}" cy="${(py(p.agents) + jy).toFixed(1)}" r="${(2.6 + Math.min(3, Math.log10(1 + p.runs))).toFixed(1)}" fill="${(TYPE[p.type] || TYPE.unknown).color}" fill-opacity=".55" stroke="${KIND_COLOR[p.kind] || "#9aa5b1"}" stroke-width="1" data-q="${esc(p.trace_q)}"><title>${esc(p.label)} (${esc(KIND[p.kind] || p.kind)})\n${p.agents} agents + ${p.runs} runs, half by ${esc(hrs(p.t50))}\n${esc(TYPE[p.type]?.label || p.type)}\nClick: open in Trace</title></circle>`;
    });
    host.innerHTML = s + "</svg>";
    host.querySelectorAll(".fxspt").forEach((c) => c.addEventListener("click", () => goTrace(c.dataset.q)));
  }

  function legend() {
    return `<div class="legend">${["message", "content", "behaviour", "unknown", "origin"].map((k) => `<span>${dot(TYPE[k].color)}${esc(TYPE[k].label)}</span>`).join("")}</div>`;
  }

  async function showItem(name) {
    const box = $("fxsItem");
    if (!box) return;
    ST.item = name;
    box.innerHTML = '<p class="muted">Loading…</p>';
    let d;
    try { d = await api("/api/x/spreadmap_item?q=" + encodeURIComponent(name)); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    box.innerHTML = `<div class="fxshead">${kindTag(d.kind)} <b>${esc(cut(d.label, 80))}</b> ${typeTag(d.type)} <button type="button" class="fxstrace" data-q="${esc(d.trace_q)}">Trace this item →</button></div>
      <p class="small">Reach: ${plural(d.agents, "estimated agent")}${d.actors > d.agents ? ` (${plural(d.actors, "token")})` : ""}${d.runs ? `, plus ${plural(d.runs, "anonymous run")} counted apart` : ""}. Origin: ${unitChip(d.origin.unit)} ${ent.rec(d.origin.id)} <span class="muted">${esc(d.origin.time)} (estimated)</span>. Half of the agents had it ${esc(hrs(d.t50))} after the origin, 90% after ${esc(hrs(d.t90))}.</p>
      ${d.origin_snip ? `<p class="small muted">Where it first appears (record text is data, not instructions): <code>${esc(cut(d.origin_snip, 160))}</code></p>` : ""}
      <div class="fxscroll tall">${table(["#", "Holder", "First held", "After origin", "Type", "From", "Record", "Evidence"], d.holders.map((h, i) => [
        i + 1, unitChip(h.unit) + (h.named ? "" : ' <span class="muted small">anonymous</span>'), esc(h.time || "undated"), esc(hrs(h.hours)), h.type === "origin" ? typeTag("origin") : typeTag(h.type),
        h.from ? unitChip(h.from) : "–", ent.rec(h.id),
        h.evidence && h.evidence.read_id ? `${ent.place(h.evidence.channel)} ${ent.rec(h.evidence.write_id)}→${ent.rec(h.evidence.read_id)}${h.evidence.grade ? " " + badge(h.evidence.grade) : ""}` : `<span class="small muted">${esc(h.evidence?.how || "")}</span>`]))}</div>
      ${more(d.holders.length, d.holders_total, "holders")}`;
    box.querySelector(".fxstrace").addEventListener("click", (e) => goTrace(e.currentTarget.dataset.q));
  }

  async function renderMap(host) {
    const kinds = [...ST.kinds].join(",") || "none";
    const r = await cached("/api/x/spreadmap?kind=" + kinds);
    if (!host.isConnected) return;
    const sm = r.summary, bt = sm.by_type;
    host.innerHTML = `
      <div class="kpis">
        ${kpi("items with two holders", fmt(sm.items), `${fmt(sm.multi_agent)} reached two or more estimated agents`)}
        ${kpi("widest reach", fmt(sm.max_agents), `of ${fmt(sm.agents)} agents; items held by over ${Math.round(sm.max_share * 100)}% of them (${fmt(sm.agent_cap)}+) are left out as common`)}
        ${kpi("median time to half the agents", hrs(sm.median_t50_h), "over items that reached 2+ agents; times are estimated")}
        ${kpi("median time to 90%", hrs(sm.median_t90_h), "same items")}
        ${kpi("spread type, items with 2+ agents", `${fmt(bt.message || 0)} / ${fmt(bt.content || 0)} / ${fmt(bt.behaviour || 0)} / ${fmt(bt.unknown || 0)}`, "message / content / behaviour / unknown")}
      </div>
      <div class="fxschips" id="fxsKinds"><span class="small muted">Kinds of item:</span> ${Object.keys(KIND).map((k) => `<label class="fxschip"><input type="checkbox" data-kind="${k}" ${ST.kinds.has(k) ? "checked" : ""}> ${kindTag(k)} <span class="muted small">${fmt(sm.by_kind[k] || 0)}</span></label>`).join("")}</div>
      ${card(`The ${r.strips.length} widest cascades`, `<div id="fxsStrips"></div>${legend()}`,
        { sub: `One small plot per item: each dot is an estimated agent's first hold, left to right in hours since the origin (each plot has its own scale; dashed lines mark 25, 50 and 90% of the agents), lines join the holders in order. Colour is how that agent most plausibly got it. Click a plot for the full cascade.` })}
      ${card("Reach against speed", `<div id="fxsScatter"></div>${legend()}`,
        { sub: `${fmt(r.scatter.length)} items that reached two or more agents. Up = more agents; left = faster. Dot size grows with the number of anonymous runs that also held it; the outline is the kind of item. Click a dot to open it in Trace.` })}
      ${card("Every item, widest first", `<div class="fxscroll tall" id="fxsTable"></div>${more(r.items.length, r.items_total, "items")}`, { sub: "Ranked by estimated agents, then anonymous runs, then speed. Click a row for the full cascade." })}
      ${card("One item's cascade", `<div id="fxsItem"><p class="muted">Click a plot, a row or an item name.</p></div>`)}
      ${card("How to read this, and what it cannot say", `<ul class="fxscav">
        <li><b>Holding is not receiving.</b> A first hold is the first record of the agent that has the string, uses the token, or (techniques, hosts, program families) first does it after its first hour. Two agents can hold the same string because both read it from the same outside source; that shows as “unknown”, not as a spread.</li>
        <li><b>Spread types are a best explanation, not a finding.</b> Message-carried: a delivery from an earlier holder to the later one, after the earlier one held the item and before the later one did. Content-only hand-over: the item moved with no shared place (Content tracing), or the credential was in somebody's data before it was used. Behaviour-only: the two agents are behaviour-linked (Coordination without messages), or a technique, host or program family appears with no visible carrier, which cannot be told from independent adoption. Unknown: none of these. An item's type is the commonest type among its later agents.</li>
        <li><b>Times are mostly estimated</b> (median error about 15 minutes, 90th percentile about 2 hours), so a lead of under an hour is not an order. Items that start in every agent's first moments (a shared prompt, a common library) look like instant spread.</li>
        <li><b>Agents are estimates.</b> Tokens merged on direct evidence count once; the reach by token is shown beside the reach by agent where they differ. Anonymous runs cannot be merged into agents, so they are counted apart and left out of the speed figures.</li>
        <li><b>Left out:</b> ${fmt(sm.common_dropped)} item(s) held by over ${Math.round(sm.max_share * 100)}% of the agents; public names with no digit, path or placeholder (library calls), MIME types and plain routes (commit/main); anything in over ${fmt(sm.thresholds.hold_cap)} holders while scanning. Some public API paths and redaction placeholders still get through.</li>
        <li>Scanned ${fmt(sm.scanned.strings)} distinctive-shaped strings, ${fmt(sm.scanned.credentials)} credentials and ${fmt(sm.scanned.techniques)} techniques, hosts and program families in ${sm.seconds} s.</li></ul>`)}`;
    strips($("fxsStrips"), r);
    onResize(host, () => scatter($("fxsScatter"), r));
    scatter($("fxsScatter"), r);
    $("fxsTable").innerHTML = table(["#", "Item", "Kind", "Agents", "Runs", "Origin", "Half by", "90% by", "Spread type"], r.items.map((x) => [
      x.rank, itemBtn(x), kindTag(x.kind), x.agents, x.runs, `${unitChip(x.origin.unit)} <span class="small muted">${esc(x.origin.time)}</span>`, esc(hrs(x.t50)), esc(hrs(x.t90)), typeTag(x.type)]), true);
    bindRows($("fxsTable"), (i) => showItem(r.items[i].item));
    host.addEventListener("click", (e) => {
      const b = e.target.closest(".fxsitem, .fxsstrip");
      if (b && b.dataset.item) { showItem(b.dataset.item); $("fxsItem").scrollIntoView({ block: "center", behavior: "smooth" }); }
    });
    host.addEventListener("keydown", (e) => { const b = e.target.closest(".fxsstrip"); if (b && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); showItem(b.dataset.item); } });
    $("fxsKinds").addEventListener("change", (e) => {
      const k = e.target.dataset.kind;
      if (!k) return;
      e.target.checked ? ST.kinds.add(k) : ST.kinds.delete(k);
      renderMap(host);
    });
    const first = r.items.find((x) => x.agents >= 2) || r.items[0];
    if (first) showItem(ST.item && r.items.some((x) => x.item === ST.item) ? ST.item : first.item);
  }

  // ================================================================ 2. one graph, three kinds of evidence
  const EK = {
    message: { label: "message", color: "#6b46c1", dash: "", w: 2.2 },
    content: { label: "content hand-over", color: "#0f766e", dash: "7 4", w: 2.2 },
    behaviour: { label: "behaviour link", color: "#d9822b", dash: "1.5 4", w: 2.6 },
  };
  const pk = (p) => p.a + "\u0001" + p.b;
  const kinds3 = (p) => p.kinds.map((k) => `<span class="fxsek" style="--c:${EK[k].color}">${esc(EK[k].label)}${p[k] > 1 ? ` ×${p[k]}` : ""}</span>`).join(" ");

  function hull(pts) {
    if (pts.length < 3) return pts;
    const p = pts.slice().sort((a, b) => a.x - b.x || a.y - b.y), cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = [];
    for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (const q of p.slice().reverse()) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }

  function layout(nodes, pairs, W, H) {
    const idx = new Map(nodes.map((n, i) => [n.unit, i]));
    nodes.forEach((n, i) => { const a = (2 * Math.PI * i) / nodes.length; n.x = W / 2 + Math.cos(a) * W * 0.3; n.y = H / 2 + Math.sin(a) * H * 0.34; });
    const pull = pairs.map((p) => [idx.get(p.a), idx.get(p.b), p.kinds.length]);
    for (let it = 0; it < 240; it++) {
      const k = 0.9 * (1 - it / 240) + 0.05;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = Math.min(40, 5200 / d2);
        dx /= d; dy /= d; a.x += dx * f * k; a.y += dy * f * k; b.x -= dx * f * k; b.y -= dy * f * k;
      }
      pull.forEach(([i, j, w]) => { const a = nodes[i], b = nodes[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = ((d - 100) / d) * 0.05 * w * k; a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f; });
      nodes.forEach((n) => { n.x += (W / 2 - n.x) * 0.012; n.y += (H / 2 - n.y) * 0.02; n.x = Math.max(70, Math.min(W - 70, n.x)); n.y = Math.max(26, Math.min(H - 30, n.y)); });
    }
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const fit = Math.min((W - 180) / Math.max(1, x1 - x0), (H - 80) / Math.max(1, y1 - y0), 3.2);
    nodes.forEach((n) => { n.x = W / 2 + (n.x - (x0 + x1) / 2) * fit; n.y = H / 2 + 6 + (n.y - (y0 + y1) / 2) * fit; });
  }

  function drawGraph(host, r) {
    if (!r.nodes.length) { host.innerHTML = '<p class="muted">No pair of agents has any of the three kinds of evidence.</p>'; return; }
    const nodes = r.nodes.map((n) => ({ ...n })), W = Math.max(560, host.clientWidth || 800), H = Math.max(360, Math.min(600, 160 + nodes.length * 14));
    layout(nodes, r.pairs, W, H);
    const at = new Map(nodes.map((n) => [n.unit, n]));
    let s = `<svg class="fxssvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Evidence between estimated agents">`;
    nodes.forEach((n) => { if (n.tokens.length > 1) s += `<circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${(15 + n.tokens.length * 2).toFixed(1)}" fill="#2f6fb3" fill-opacity=".13" stroke="#2f6fb3" stroke-opacity=".35"><title>One estimated agent holding ${n.tokens.length} tokens</title></circle>`; });
    r.pairs.forEach((p) => {
      const a = at.get(p.a), b = at.get(p.b), shown = p.kinds.filter((k) => ST.vis.has(k));
      if (!shown.length) return;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, nx = -dy / d, ny = dx / d;
      s += `<g class="fxsedge${ST.pair === pk(p) ? " on" : ""}" data-pair="${esc(pk(p))}"><line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="transparent" stroke-width="13"/>`;
      shown.forEach((k, i) => {
        const o = (i - (shown.length - 1) / 2) * 3.4, e = EK[k];
        s += `<line x1="${(a.x + nx * o).toFixed(1)}" y1="${(a.y + ny * o).toFixed(1)}" x2="${(b.x + nx * o).toFixed(1)}" y2="${(b.y + ny * o).toFixed(1)}" stroke="${e.color}" stroke-width="${e.w}" ${e.dash ? `stroke-dasharray="${e.dash}"` : ""} stroke-linecap="round"/>`;
      });
      s += `<title>${esc(short(p.a))} and ${esc(short(p.b))}: ${p.kinds.map((k) => EK[k].label + (p[k] > 1 ? " ×" + p[k] : "")).join(", ")}\nClick for the evidence</title></g>`;
    });
    nodes.forEach((n) => {
      const rr = 5 + Math.min(7, Math.log10(1 + n.records) * 2.2);
      s += `<g data-agent="${esc(n.unit)}"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${rr.toFixed(1)}" fill="#fdf3e1" stroke="#b7791f" stroke-width="1.6"/><text x="${n.x.toFixed(1)}" y="${(n.y - rr - 4).toFixed(1)}" text-anchor="middle" font-size="10.5" fill="#5c3b08" paint-order="stroke" stroke="#fff" stroke-width="3">${esc(short(n.unit))}</text><title>${esc(short(n.unit))}: ${fmt(n.records)} records, ${n.degree} linked agent(s)${n.tokens.length > 1 ? `\n${n.tokens.length} tokens in one estimated agent` : ""}</title></g>`;
    });
    host.innerHTML = s + "</svg>";
    host.querySelectorAll(".fxsedge").forEach((g) => g.addEventListener("click", () => { const p = r.pairs.find((x) => pk(x) === g.dataset.pair); if (p) showPair(p); }));
  }

  async function showPair(p) {
    ST.pair = pk(p);
    const box = $("fxsPair");
    box.innerHTML = '<p class="muted">Loading…</p>';
    let d;
    try { d = await api("/api/x/evidence_pair?a=" + encodeURIComponent(p.a) + "&b=" + encodeURIComponent(p.b)); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    const msg = d.messages.length ? `<h4>${plural(d.messages_total, "message")}</h4>${table(["From", "To", "Place", "Wrote", "Read", "Wait", "Grade"], d.messages.map((m) => [ent.actor(m.from), ent.actor(m.to), ent.place(m.channel), ent.rec(m.write_id), ent.rec(m.read_id), `<span class="fxsnw">${esc(gapWord(m.latency_h, true))}</span>`, m.grade ? badge(m.grade) : '<span class="muted small">no grade</span>']))}` : "";
    const cont = d.content.length ? `<h4>Content that moved with no shared place</h4>${d.content.map((c) => `<p class="small">${ent.actor(c.from)} then ${ent.actor(c.to)}</p>${table(["String", "First", "Then", "Gap", "First record text", "Later record text"], c.items.map((it) => [`<code class="fxswrap">${esc(cut(it.item, 40))}</code>`, ent.rec(it.first_id), ent.rec(it.then_id), `<span class="fxsnw">${esc(gapWord(it.gap_h, true))}</span>`, `<span class="small muted">${esc(cut(it.first_snip))}</span>`, `<span class="small muted">${esc(cut(it.then_snip))}</span>`]))}`).join("")}` : "";
    const b = d.behaviour, adopt = b && b.adoption ? `<p class="small">Adopted the same technique within hours: ${b.adoption.co_adoptions} times (z ${b.adoption.z}, adjusted p ${b.adoption.p_adj}).</p>${table(["Technique", "First", "Record", "Then", "Record", "Gap"], b.adoption.techniques.map((t) => [esc(t.technique), ent.actor(t.first), ent.rec(t.first_id), ent.actor(t.then), ent.rec(t.then_id), `<span class="fxsnw">${esc(gapWord(t.gap_h, true))}</span>`]))}` : "";
    const beh = b ? `<h4>Behaviour link: ${esc(b.kinds.join(" + "))} (z ${b.z})</h4>${b.synchrony ? `<p class="small">Bursts of the same intent started within an hour of each other: ${esc(JSON.stringify(b.synchrony))}.</p>` : ""}${adopt}<p class="small muted">The full evidence is in Coordination without messages.</p>` : "";
    box.innerHTML = `<div class="fxshead">${unitChip(d.a)} ↔ ${unitChip(d.b)} ${kinds3(d)}</div>${msg}${cont}${beh}`;
  }

  async function renderGraph(host) {
    const r = await cached("/api/x/evidence");
    if (!host.isConnected) return;
    const sm = r.summary;
    host.innerHTML = `
      <div class="fxsbig"><b>${fmt(sm.beyond_messages)}</b> of ${fmt(sm.pairs)} linked agent pairs${sm.share_missed != null ? ` (${pct(sm.share_missed)})` : ""} have no message between them. ${sm.message ? `A message-only analysis sees ${fmt(sm.message)}; the other two kinds of evidence add ${fmt(sm.beyond_messages)} more` : "No pair has a message; the other two kinds add all of them"}: ${fmt(sm.content_beyond)} through content that moved with no shared place, ${fmt(sm.behaviour_beyond)} through behaviour${sm.all_three ? `; ${fmt(sm.all_three)} pair(s) have all three kinds` : ""}.</div>
      <div class="kpis">
        ${kpi("agent pairs, any evidence", fmt(sm.pairs), `${fmt(sm.agents)} estimated agents`)}
        ${kpi("by message", fmt(sm.message), `${fmt(sm.message_deliveries_with_runs)} further deliveries involve an anonymous run and are not drawn`)}
        ${kpi("by content hand-over", fmt(sm.content), `${fmt(sm.content_beyond)} with no message; strong pairs only, ${fmt(sm.content_pairs_weak_left_out)} weak candidates left out`)}
        ${kpi("by behaviour link", fmt(sm.behaviour), `${fmt(sm.behaviour_beyond)} with no message; passed the chance tests`)}
      </div>
      ${card("Agents and the evidence between them", `
        <div class="fxsbar" id="fxsTog">${Object.keys(EK).map((k) => `<label class="fxschip"><input type="checkbox" data-ev="${k}" ${ST.vis.has(k) ? "checked" : ""}> <svg width="34" height="10"><line x1="2" y1="5" x2="32" y2="5" stroke="${EK[k].color}" stroke-width="${EK[k].w}" ${EK[k].dash ? `stroke-dasharray="${EK[k].dash}"` : ""} stroke-linecap="round"/></svg> ${esc(EK[k].label)} <span class="muted small">${fmt(sm[k])}</span></label>`).join("")}</div>
        <div id="fxsGraph"></div>
        <div class="legend"><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${EK.message.color}" stroke-width="2.2"/></svg>solid: message</span><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${EK.content.color}" stroke-width="2.2" stroke-dasharray="7 4"/></svg>dashed: content-only hand-over</span><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${EK.behaviour.color}" stroke-width="2.6" stroke-dasharray="1.5 4" stroke-linecap="round"/></svg>dotted: behaviour link</span><span><i style="background:#2f6fb3;opacity:.3;border-radius:5px"></i>halo: one estimated agent with several tokens</span></div>`,
        { sub: "Only agents with at least one link are drawn. A pair with several kinds of evidence shows one line per kind, side by side. Click a line, or a row below, for the evidence." })}
      ${card("The evidence for one pair", `<div id="fxsPair"><p class="muted">Click a line or a row.</p></div>`)}
      ${card("Agent pairs and the evidence kinds present", `<div class="fxscroll tall" id="fxsPairs"></div>${more(r.pairs.length, r.pairs_total, "pairs")}`, { sub: "More kinds first, then the number of messages. A number is how many messages, strong hand-over pairs, or behaviour tests passed (synchrony, adoption, split work)." })}
      ${card("What each kind can and cannot show", `<ul class="fxscav">
        <li><b>Message:</b> a place one agent wrote and another read afterwards (Channels). Placing the read after the write is the only evidence, and a message shows content was available, not that it was used. ${sm.has_grade ? `Delivery grades: ${Object.entries(sm.grades).map(([k, v]) => `${esc(k)} ${fmt(v)}`).join(", ")}.` : "No delivery grade is attached to the messages in this dataset, so none is shown."}</li>
        <li><b>Content hand-over:</b> a distinctive string first held by one agent and later by another who never held it, with no shared place and no same-program rerun. Strong pairs only; a string two agents read from the same outside source looks the same.</li>
        <li><b>Behaviour link:</b> acting in step (synchrony), adopting the same techniques within hours, or splitting work, each against a chance model with a family-wise correction. It says the two behaved as if linked, not how information travelled.</li>
        <li>Pairs between two tokens of one estimated agent, and anything involving an anonymous run, are not drawn (${fmt(sm.same_agent_deliveries)} delivery(ies) are inside one agent).</li></ul>`)}`;
    const draw = () => drawGraph($("fxsGraph"), r);
    draw();
    onResize(host, draw);
    $("fxsTog").addEventListener("change", (e) => { const k = e.target.dataset.ev; if (!k) return; e.target.checked ? ST.vis.add(k) : ST.vis.delete(k); draw(); });
    $("fxsPairs").innerHTML = table(["Agent", "Agent", "Evidence", "Messages", "Hand-overs", "Behaviour"], r.pairs.map((p) => [unitChip(p.a), unitChip(p.b), kinds3(p), p.message, p.content, p.behaviour]), true);
    bindRows($("fxsPairs"), (i) => { showPair(r.pairs[i]); $("fxsPair").scrollIntoView({ block: "center", behavior: "smooth" }); });
    if (r.pairs[0]) showPair(r.pairs.find((p) => p.kinds.length > 1) || r.pairs[0]);
  }

  // ================================================================ 3. stage the incident
  function timeline(host, r) {
    const rows = r.stages.filter((g) => g.first && g.crossed.length);
    if (!rows.length) { host.innerHTML = '<p class="muted">No stage has a dated first user that held an item from another agent first.</p>'; return; }
    const per = 4, lane = (g) => 22 + Math.min(per, g.crossed.length) * 12;
    const pick = (g) => g.crossed.slice().sort((a, b) => a.lag_h - b.lag_h).slice(0, per);
    const all = rows.flatMap((g) => pick(g)), t0 = Math.min(...all.map((x) => toTime(x.origin_time))), t1 = Math.max(...all.map((x) => toTime(x.use_time)), ...rows.map((g) => toTime(g.first.time)));
    const W = Math.max(640, host.clientWidth || 900), L = 150, Rr = 20, T = 22, px = (t) => L + (W - L - Rr) * ((t - t0) / Math.max(1, t1 - t0));
    const H = T + rows.reduce((a, g) => a + lane(g), 0) + 10;
    let s = `<svg class="fxssvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Stage timeline: items that reached the first agent of each stage">`;
    timeTicks(t0, t1, 9).forEach(({ t, label }) => { s += `<line x1="${px(t)}" x2="${px(t)}" y1="${T - 6}" y2="${H - 4}" stroke="#eef0f3"/><text x="${px(t)}" y="12" font-size="10.5" fill="#66717d" text-anchor="middle">${esc(label)}</text>`; });
    let y = T;
    rows.forEach((g, gi) => {
      const h = lane(g), fx = px(toTime(g.first.time));
      s += `<rect x="0" y="${y}" width="${W}" height="${h}" fill="${gi % 2 ? "#fafbfc" : "#fff"}"/><text x="6" y="${y + 15}" font-size="11.5" font-weight="600" fill="#1b2430">${esc(human(g.stage))}</text><text x="6" y="${y + 28}" font-size="10" fill="#66717d">${esc(short(g.first.unit))} first, ${esc(when(toTime(g.first.time)))}</text>`;
      pick(g).forEach((x, i) => {
        const x0 = px(toTime(x.origin_time)), x1 = px(toTime(x.use_time)), yy = y + 14 + i * 12, col = KIND_COLOR[x.kind] || "#9aa5b1";
        s += `<g class="fxsbarg"><line x1="${x0.toFixed(1)}" x2="${x1.toFixed(1)}" y1="${yy}" y2="${yy}" stroke="${col}" stroke-width="4" stroke-linecap="round" stroke-opacity=".75"/><circle cx="${x0.toFixed(1)}" cy="${yy}" r="3.4" fill="#fff" stroke="${col}" stroke-width="1.6"/><path d="M${(x1 - 4.5).toFixed(1)},${yy}l4.5,-4.5l4.5,4.5l-4.5,4.5z" fill="${col}"/><text x="${(x1 > W * 0.6 ? x0 - 8 : x1 + 9).toFixed(1)}" text-anchor="${x1 > W * 0.6 ? "end" : "start"}" y="${yy + 3.5}" font-size="10" fill="#3d4a58" paint-order="stroke" stroke="#fff" stroke-width="3">${esc(cut(x.label, 26))} · ${esc(hrs(x.lag_h))}</text><title>${esc(x.label)} (${esc(KIND[x.kind])})\norigin ${esc(short(x.origin_unit))}, ${esc(x.origin_time)}\nfirst used at this stage by ${esc(short(x.user))}, ${esc(x.use_time)}\n${esc(hrs(x.lag_h))} from the origin (estimated)</title></g>`;
      });
      s += `<line x1="${fx.toFixed(1)}" x2="${fx.toFixed(1)}" y1="${y + 2}" y2="${y + h - 2}" stroke="#c2410c" stroke-width="1.5"/>`;
      y += h;
    });
    host.innerHTML = s + "</svg>";
  }

  async function renderStages(host) {
    const r = await cached("/api/x/spread_stages");
    if (!host.isConnected) return;
    const gs = r.stages.filter((g) => g.agents);
    const crossedAll = gs.reduce((a, g) => a + g.crossed_total, 0);
    const nw = (t) => `<span class="fxsnw">${t}</span>`;
    const rowsT = gs.flatMap((g) => g.crossed.slice(0, 4).map((x) => [nw(`<b>${esc(human(g.stage))}</b><br><span class="small muted">first: ${esc(short(g.first.unit))}, ${esc(g.first.time)}</span>`),
      `<div>${itemBtn(x)}</div>${kindTag(x.kind)}`, nw(`${unitChip(x.origin_unit)}<br>→ ${unitChip(x.user)}${x.user === g.first.unit ? ' <span class="fxsb">stage\'s first</span>' : ""}`),
      nw(`<b>${esc(hrs(x.lag_h))}</b>`), nw(esc(hrs(x.arrival_h))), nw(esc(hrs(x.hold_to_use_h))), nw(x.in_record ? "in the record" : "earlier record"), typeTag(x.type)]));
    host.innerHTML = `
      <div class="kpis">
        ${kpi("stages with a dated first agent", fmt(gs.length), `${fmt(r.actors_total)} agents climbed at least one stage (${fmt(r.actors_listed)} listed by the ladder)`)}
        ${kpi("items that crossed to a stage's first user", fmt(gs.reduce((a, g) => a + g.preceded_total, 0)), "the stage's first agent held it before, from another agent, 1 h or more after its origin")}
        ${kpi("items first used at a stage after crossing", fmt(crossedAll), "summed over stages: any agent, shortest origin-to-use first")}
      </div>
      ${card("Stage timeline: how long information took to reach the first user", `<div id="fxsTL"></div><div class="legend">${["credential", "file", "place", "host", "program", "technique", "string"].map((k) => `<span>${dot(KIND_COLOR[k])}${esc(KIND[k])}</span>`).join("")}<span><svg width="20" height="10"><circle cx="5" cy="5" r="3.4" fill="#fff" stroke="#66717d" stroke-width="1.6"/></svg>origin</span><span><svg width="12" height="10"><path d="M1,5l4.5,-4.5l4.5,4.5l-4.5,4.5z" fill="#66717d"/></svg>first use at the stage</span><span><svg width="12" height="10"><line x1="6" x2="6" y1="0" y2="10" stroke="#c2410c" stroke-width="1.5"/></svg>first agent to reach the stage</span></div>`,
        { sub: "One lane per stage in the ladder's own order. A bar runs from an item's origin to the first use at the stage by an agent that already held it; up to four items per lane, shortest first. Times are estimated and an item that arrived within an hour of its origin is left out (the order cannot be told)." })}
      ${card("Which item came before each stage, and who used it first", `<div class="fxscroll tall" id="fxsStTable"></div>`,
        { sub: "Per stage, the best items of each kind (credential, program family, host, file, technique, place): where the item started, which agent used it first at the stage, how long it took to get there, and how long that agent had held it. “In the record” means the item's text is in the stage's own record." })}
      ${card("One item", `<div id="fxsItem"><p class="muted">Click an item name above.</p></div>`)}
      ${card("How far to trust this", `<ul class="fxscav">
        <li><b>Precedence is not causation.</b> That an agent held an item before it reached a stage does not show the item led it there; most agents hold many items and climb many stages. The table lists what the swarm shared, in the order it was seen.</li>
        <li><b>Times are estimated</b> (median error about 15 minutes, 90th percentile about 2 hours). Lags under an hour are not reported as an order; long lags are accurate to hours, not minutes.</li>
        <li><b>The ladder is a guess for some intents.</b> A stage comes from the pack, a behaviour of the same name or the intent's name (Behaviour tab); an agent's stage time is its first dated action there, and only the first ${fmt(r.actors_listed)} climbers the ladder lists are used.</li>
        <li><b>Origin is the first record we hold, not the first in the world.</b> An item that appears first in a shared prompt or outside source may only seem to cross the swarm; anonymous runs are counted in an item's reach but never as stage users.</li>
        <li>Items counted: those held by at least two agents, in the kinds the map keeps. ${fmt(r.summary.multi_agent)} items reached two or more agents.</li></ul>`)}`;
    timeline($("fxsTL"), r);
    onResize(host, () => timeline($("fxsTL"), r));
    $("fxsStTable").innerHTML = table(["Stage", "Item", "Origin → first use here", "Origin to use", "Origin to arrival", "Held before use", "Item seen", "Spread type"], rowsT);
    host.addEventListener("click", async (e) => {
      const b = e.target.closest(".fxsitem");
      if (!b) return;
      const box = $("fxsItem");
      box.innerHTML = '<p class="muted">Loading…</p>';
      try {
        const d = await api("/api/x/spreadmap_item?q=" + encodeURIComponent(b.dataset.item));
        box.innerHTML = `<div class="fxshead">${kindTag(d.kind)} <b>${esc(cut(d.label, 80))}</b> ${typeTag(d.type)} <button type="button" class="fxstrace" data-q="${esc(d.trace_q)}">Trace this item →</button></div><p class="small">${plural(d.agents, "agent")}${d.runs ? ` and ${plural(d.runs, "run")}` : ""}; origin ${unitChip(d.origin.unit)} ${ent.rec(d.origin.id)} ${esc(d.origin.time)}; half of the agents by ${esc(hrs(d.t50))}. The full cascade is in the Spread map.</p>`;
        box.querySelector(".fxstrace").addEventListener("click", (ev) => goTrace(ev.currentTarget.dataset.q));
      } catch (err) { box.innerHTML = `<p class="warn">${esc(err.message)}</p>`; }
    });
  }

  window.FX_SECTIONS.push(
    { id: "spreadmap", title: "Spread map", group: "Follow the evidence",
      blurb: "How did information spread across the swarm? For each credential, file, place, host, program family or technique that more than one agent held: where it started, how many estimated agents had it, how fast it spread, and what the best explanation of each hand-over is (a message, content with no shared place, behaviour, or nothing recorded).", render: renderMap },
    { id: "evidence", title: "Three kinds of evidence", group: "Follow the evidence",
      blurb: "Messages, content hand-overs and behaviour links in one graph over estimated agents. The headline number is how many linked pairs a message-only analysis would miss.", render: renderGraph },
    { id: "incident", title: "Stage the incident", group: "Follow the evidence",
      blurb: "Ties what spread to how the incident climbed: for each attack stage, which items an agent already held when it first reached it, who used them first, and how long they had taken to get there from their origin.", render: renderStages });
})();

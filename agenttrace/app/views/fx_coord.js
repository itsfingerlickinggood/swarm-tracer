// Forensics › "Coordination without messages": behaviour links between named actors (synchrony,
// technique adoption, complementary work), each against a chance model. Builds on Lead–lag.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const BEH = "#0f766e", MSG = "#6b46c1", HR = 3600e3;
  const ST = { pair: null };
  const KIND = { synchrony: "synchrony", adoption: "adoption", complementary: "split work" };
  const badge = (t, cls = "") => `<span class="fxkb ${cls}">${esc(t)}</span>`;
  const techName = (k) => { const i = k.indexOf(":"), kind = k.slice(0, i), v = k.slice(i + 1); return kind === "program" ? `program family ${v.slice(0, 7)}` : kind === "intent" ? `intent ${human(v)}` : kind === "tag" ? `tag ${human(v)}` : `host ${v}`; };
  const pkey = (p) => p.a + "\u0001" + p.b;
  const pnum = (x) => (x == null ? "–" : x < 0.001 ? x.toExponential(0) : String(+x.toFixed(3)));

  // ---------------------------------------------------------------- network graph
  function hull(pts) {
    if (pts.length < 3) return pts;
    const p = pts.slice().sort((a, b) => a.x - b.x || a.y - b.y), cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = [];
    for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (const q of p.slice().reverse()) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }
  function graph(host, r) {
    if (!host) return;
    const nodes = r.nodes.map((n) => ({ ...n }));
    if (!nodes.length) { host.innerHTML = '<p class="muted">No behaviour link passed the tests, so there is no graph to draw.</p>'; return; }
    const W = Math.max(560, host.clientWidth || 800), H = Math.max(340, Math.min(560, 150 + nodes.length * 14));
    const idx = new Map(nodes.map((n, i) => [n.actor, i]));
    const groups = [...new Set(nodes.map((n) => n.agent || n.actor))];
    // start on a circle with estimated agents side by side, then a small fixed force layout
    nodes.sort((a, b) => groups.indexOf(a.agent || a.actor) - groups.indexOf(b.agent || b.actor));
    nodes.forEach((n, i) => { idx.set(n.actor, i); const a = (2 * Math.PI * i) / nodes.length; n.x = W / 2 + Math.cos(a) * W * 0.3; n.y = H / 2 + Math.sin(a) * H * 0.34; });
    const links = r.links.filter((p) => idx.has(p.a) && idx.has(p.b));
    const pull = links.map((p) => [idx.get(p.a), idx.get(p.b), 1]);
    nodes.forEach((a, i) => nodes.forEach((b, j) => { if (i < j && a.agent && a.agent === b.agent) pull.push([i, j, 2]); }));
    for (let it = 0; it < 260; it++) {
      const k = 0.9 * (1 - it / 260) + 0.05;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = Math.min(40, 5200 / d2);
        dx /= d; dy /= d; a.x += dx * f * k; a.y += dy * f * k; b.x -= dx * f * k; b.y -= dy * f * k;
      }
      pull.forEach(([i, j, w]) => { const a = nodes[i], b = nodes[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, want = w === 2 ? 46 : 96, f = ((d - want) / d) * 0.06 * w * k; a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f; });
      nodes.forEach((n) => { n.x += (W / 2 - n.x) * 0.012; n.y += (H / 2 - n.y) * 0.02; n.x = Math.max(70, Math.min(W - 70, n.x)); n.y = Math.max(26, Math.min(H - 30, n.y)); });
    }
    // stretch the finished layout to the box, so a small graph is not a knot in the middle
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const fit = Math.min((W - 180) / Math.max(1, x1 - x0), (H - 80) / Math.max(1, y1 - y0), 3.2);
    nodes.forEach((n) => { n.x = W / 2 + (n.x - (x0 + x1) / 2) * fit; n.y = H / 2 + 6 + (n.y - (y0 + y1) / 2) * fit; });
    let s = `<svg class="fxksvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Behaviour links between actors">`;
    // hulls: tokens of one estimated agent
    groups.forEach((g, gi) => {
      const ms = nodes.filter((n) => n.agent && n.agent === g);
      if (ms.length < 2) return;
      const col = PALETTE.intent[gi % PALETTE.intent.length], h = hull(ms);
      s += `<path d="M${h.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join("L")}Z" fill="${col}" fill-opacity=".14" stroke="${col}" stroke-opacity=".14" stroke-width="34" stroke-linejoin="round" stroke-linecap="round"><title>One estimated agent: ${esc(short(g))}</title></path>`;
    });
    // message-only edges between the nodes shown (thin, purple, for comparison)
    const linked = new Set(links.map(pkey));
    r.message_edges.forEach((m) => { if (idx.has(m.a) && idx.has(m.b) && !linked.has(m.a + "\u0001" + m.b)) { const a = nodes[idx.get(m.a)], b = nodes[idx.get(m.b)]; s += `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${MSG}" stroke-width="1" stroke-opacity=".55"><title>Message only (no behaviour link): ${esc(short(m.a))} and ${esc(short(m.b))}, ${m.n} message(s)</title></line>`; } });
    links.forEach((p) => {
      const a = nodes[idx.get(p.a)], b = nodes[idx.get(p.b)], w = Math.max(1.6, Math.min(5, p.z / 2.4));
      s += `<g class="fxkedge${ST.pair === pkey(p) ? " on" : ""}" data-pair="${esc(pkey(p))}"><line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="transparent" stroke-width="12"/><line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${BEH}" stroke-width="${w.toFixed(1)}" ${p.has_message ? "" : 'stroke-dasharray="6 4"'} stroke-linecap="round"/><title>${esc(short(p.a))} and ${esc(short(p.b))}: ${p.kinds.map((k) => KIND[k]).join(" + ")}, z ${p.z}\n${p.has_message ? `also ${p.messages} message(s) between them` : "no message between them"}${p.same_agent ? "\none estimated agent" : ""}\nClick for the evidence</title></g>`;
    });
    nodes.forEach((n) => {
      const rr = 5 + Math.min(7, Math.log10(1 + n.actions) * 2.2);
      s += `<g data-actor="${esc(n.actor)}" style="cursor:pointer"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${rr.toFixed(1)}" fill="#fdf3e1" stroke="#b7791f" stroke-width="1.6"/><text x="${n.x.toFixed(1)}" y="${(n.y - rr - 4).toFixed(1)}" text-anchor="middle" font-size="10.5" fill="#5c3b08" paint-order="stroke" stroke="#fff" stroke-width="3">${esc(short(n.actor))}</text><title>${esc(short(n.actor))}: ${fmt(n.actions)} dated actions${n.agent ? `\nestimated agent ${short(n.agent)}` : ""}</title></g>`;
    });
    host.innerHTML = s + "</svg>";
    host.querySelectorAll(".fxkedge").forEach((g) => g.addEventListener("click", () => { const p = r.links.find((x) => pkey(x) === g.dataset.pair); if (p) showPair(p, r); }));
  }

  // ---------------------------------------------------------------- adoption cascades
  function cascades(host, r) {
    if (!host) return;
    const cs = r.cascades;
    if (!cs.length) { host.innerHTML = '<p class="muted">No technique was first used by three actors within the window.</p>'; return; }
    const span = r.summary.thresholds.cascade_h;
    const W = Math.max(560, host.clientWidth || 800), padL = 230, padR = 250, rowH = 30, top = 22;
    const X = (h) => padL + (h / span) * (W - padL - padR);
    const H = top + cs.length * rowH + 8;
    const groups = [...new Set(cs.flatMap((c) => c.steps.map((x) => x.agent || x.actor)))];
    let s = `<svg class="fxksvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Technique adoption cascades">`;
    for (let h = 0; h <= span; h += span > 8 ? 2 : 1) s += `<line x1="${X(h)}" x2="${X(h)}" y1="${top - 4}" y2="${H - 6}" stroke="${GRID}"/><text x="${X(h)}" y="${top - 9}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${h === 0 ? "first use" : "+" + h + " h"}</text>`;
    cs.forEach((c, i) => {
      const y = top + i * rowH + rowH / 2, t0 = toTime(c.steps[0].time);
      if (c.strong) s += `<rect x="0" y="${y - rowH / 2 + 1}" width="${W}" height="${rowH - 2}" fill="${BEH}" opacity=".07"/>`;
      s += `<text x="${padL - 10}" y="${y + 4}" text-anchor="end" font-size="11.5" fill="${INK}" ${c.strong ? 'font-weight="600"' : ""}>${esc(fitName(techName(c.technique), padL - 20, "11.5px sans-serif"))}<title>${esc(c.technique)}\nfirst used ${esc(c.start)}</title></text>`;
      const pts = c.steps.map((x) => ({ x: X(Math.min(span, (toTime(x.time) - t0) / HR)), st: x }));
      s += `<polyline points="${pts.map((p, j) => `${p.x.toFixed(1)},${y + (j % 2 ? 4 : -4)}`).join(" ")}" fill="none" stroke="#1b2430" stroke-opacity=".35" stroke-width="1"/>`;
      pts.forEach((p, j) => { const gi = groups.indexOf(p.st.agent || p.st.actor); s += `<circle cx="${p.x.toFixed(1)}" cy="${y + (j % 2 ? 4 : -4)}" r="4.6" fill="${PALETTE.intent[gi % PALETTE.intent.length]}" stroke="#fff" stroke-width="1" data-id="${esc(p.st.id)}" style="cursor:pointer"><title>${j + 1}. ${esc(short(p.st.actor))} · ${esc(p.st.time)} · ${esc(p.st.id)}${p.st.agent ? `\nestimated agent ${short(p.st.agent)}` : ""}</title></circle>`; });
      s += `<text x="${W - padR + 10}" y="${y + 4}" font-size="11" fill="${QUIET}">${c.in_cascade} of ${c.adopters} adopters · chance ${c.expected} · p ${pnum(c.p)}</text>`;
    });
    host.innerHTML = s + "</svg>";
  }

  // ---------------------------------------------------------------- one pair: synchrony strip and evidence
  function stripChart(host, d) {
    if (!host) return;
    const W = Math.max(560, host.clientWidth || 800), padL = 150, padR = 16, rowH = 44, top = 8;
    const t0 = toTime(d.start) - HR, t1 = toTime(d.end) + 2 * HR;
    const X = (t) => padL + ((t - t0) / Math.max(HR, t1 - t0)) * (W - padL - padR);
    const bw = Math.max(1.2, (W - padL - padR) / Math.max(1, (t1 - t0) / HR));
    const H = top + 2 * rowH + 44;
    const names = [d.a, d.b], yOf = (i) => top + i * (rowH + 16);
    let s = `<svg class="fxksvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Activity of the two actors with co-bursts marked">`;
    const co = (d.synchrony && d.synchrony.events) || [];
    co.forEach((e) => { const x = X(toTime(e.time)); s += `<rect x="${(x - 3).toFixed(1)}" y="${top}" width="${Math.max(6, bw * 1).toFixed(1)}" height="${2 * rowH + 16}" fill="${BEH}" opacity=".16"><title>Co-burst ${esc(e.time)}: both started ${esc(human(e.intent))} within ${e.gap_min} min\n${esc(e.a_id)} and ${esc(e.b_id)}</title></rect>`; });
    names.forEach((a, i) => {
      const y = yOf(i), base = y + rowH - 2, row = d.rows[a];
      const mx = Math.max(1, ...row.hours.map((h) => h[1]));
      s += `<text x="${padL - 8}" y="${y + rowH / 2 + 4}" text-anchor="end" font-size="11.5" fill="#7a4d0c" data-actor="${esc(a)}" style="cursor:pointer">${esc(fitName(short(a), padL - 16, "11.5px sans-serif"))}</text><line x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}" stroke="${AXIS}"/>`;
      row.hours.forEach(([h, n]) => { const hh = (Math.log1p(n) / Math.log1p(mx)) * (rowH - 12); s += `<rect x="${X(toTime(h)).toFixed(1)}" y="${(base - hh).toFixed(1)}" width="${bw.toFixed(2)}" height="${hh.toFixed(1)}" fill="#cfd6de"><title>${esc(h)}: ${n} action(s)</title></rect>`; });
      row.bursts.forEach(([t, it, rid]) => { const x = X(toTime(t)); s += `<path d="M${x.toFixed(1)},${y + 1}v8" stroke="${intentColor(it)}" stroke-width="2" data-id="${esc(rid)}" style="cursor:pointer"><title>${esc(t)}: starts ${esc(human(it))} (${esc(rid)})</title></path>`; });
    });
    timeTicks(t0, t1, 8).forEach((tk) => { const x = X(tk.t); s += `<line x1="${x}" x2="${x}" y1="${H - 26}" y2="${H - 22}" stroke="${AXIS}"/><text x="${x}" y="${H - 9}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(tk.label)}</text>`; });
    host.innerHTML = s + "</svg>";
  }
  async function showPair(p, r) {
    const box = $("fxkPair");
    if (!box) return;
    ST.pair = pkey(p);
    document.querySelectorAll(".fxkedge").forEach((g) => g.classList.toggle("on", g.dataset.pair === ST.pair));
    document.querySelectorAll("#fxkTable tr.click").forEach((tr) => tr.classList.toggle("on", r.links[+tr.dataset.i] && pkey(r.links[+tr.dataset.i]) === ST.pair));
    box.innerHTML = '<p class="muted">Loading the pair…</p>';
    let d;
    try { d = await cached(`/api/x/silent_pair?a=${encodeURIComponent(p.a)}&b=${encodeURIComponent(p.b)}`); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (ST.pair !== pkey(p) || !box.isConnected) return;
    const sy = d.synchrony, ad = d.adoption, ll = d.leadlag;
    box.innerHTML = `
      <p>${ent.actor(d.a)} and ${ent.actor(d.b)} ${d.kinds.length ? d.kinds.map((k) => badge(KIND[k], "beh")).join("") : badge("no link passed")}${d.has_message ? badge(`also ${plural(d.messages, "message")}`, "msg") : badge("no message between them")}${d.same_agent ? badge("one estimated agent", "same") : ""}</p>
      <div id="fxkStrip"></div>
      <div class="legend"><span><i style="background:#cfd6de"></i>actions per hour (log scale, per actor)</span><span><svg width="10" height="12"><path d="M5,1v9" stroke="#2f6fb3" stroke-width="2"/></svg>start of a burst, coloured by intent</span><span><i style="background:${BEH};opacity:.3"></i>co-burst: both start the same intent within ${r.summary.thresholds.window_h} h</span></div>
      <div class="fxkcols">
        <div><h4>Synchrony</h4>${sy ? `<p class="small">${fmt(sy.co_events)} co-bursts at ${fmt(sy.slots)} different times, where chance gives ${sy.expected} ± ${sy.sd}: z ${sy.z}, permutation p ${pnum(sy.p)}, after correction for every pair tested p ${pnum(sy.p_adj)}. ${sy.link ? "<b>Passes.</b>" : "Does not pass."}</p><p class="small muted">${Object.entries(sy.intents).map(([k, n]) => `${esc(human(k))} ×${n}`).join(" · ")}</p>` : `<p class="small muted">Fewer than ${r.summary.thresholds.min_co} co-bursts: not tested.</p>`}</div>
        <div><h4>Technique adoption</h4>${ad ? `<p class="small">${fmt(ad.co_adoptions)} techniques first used within ${r.summary.thresholds.pair_h} h of each other, where chance gives ${ad.expected}: z ${ad.z}, corrected p ${pnum(ad.p_adj)}. ${ad.link ? "<b>Passes.</b>" : "Does not pass."} ${esc(short(d.a))} was first ${fmt(ad.a_first)}×, ${esc(short(d.b))} ${fmt(ad.b_first)}×, ${fmt(ad.ties)} too close to order.</p>
          <div class="fxkscroll">${table(["Technique", "First", "Then", "Gap"], ad.techniques.map((t) => [esc(techName(t.technique)), `${esc(short(t.first))} ${ent.rec(t.first_id)} <span class="muted small">${esc(t.first_time)}</span>`, `${esc(short(t.then))} ${ent.rec(t.then_id)}`, esc(gapWord(t.gap_h, true))]))}</div>` : `<p class="small muted">Fewer than ${r.summary.thresholds.min_co_adopt} co-adoptions: not tested.</p>`}</div>
      </div>
      ${d.complementary.length ? `<h4>Split work</h4>${d.complementary.map((c) => `<p class="small">${esc(c.param)} on <code>${esc(c.target)}</code>: ${esc(short(d.a))} took ${fmt(c.n_a)} values (${esc(c.values_a.slice(0, 12).join(", "))}${c.n_a > 12 ? "…" : ""}), ${esc(short(d.b))} ${fmt(c.n_b)} (${esc(c.values_b.slice(0, 12).join(", "))}${c.n_b > 12 ? "…" : ""}); none in common on a grid of ${fmt(c.grid)} (step ${fmt(c.step)}), chance p ${pnum(c.p)}. ${ent.rec(c.first_a)} ${ent.rec(c.first_b)}</p>`).join("")}` : ""}
      <p class="small muted">${ll ? `Lead–lag (hourly activity): r ${ll.r} at ${ll.lag_hours} h${ll.flag ? `, ${esc(short(ll.leader))} leads` : ", no leader flagged"}.` : "Not among the actors compared in Lead–lag."}</p>`;
    const dr = () => stripChart($("fxkStrip"), d); dr(); onResize($("fxkStrip"), dr);
  }

  async function render(host) {
    const r = await cached("/api/x/silent");
    if (!host.isConnected) return;
    const sm = r.summary, th = sm.thresholds, sim = sm.simulated, t = sm.tested;
    const simText = sim ? `On simulated swarms with known truth (${sim.agents} agents, seeds ${sim.seeds.join(", ")}), where no agent plans its timing, copies a technique or splits work, these tests raised <b>${fmt(sim.benign.false)}</b> false links on the benign swarm and <b>${fmt(sim.coordinated.false)}</b> on the message-coordinated swarm, out of ${fmt(sim.benign.possible_pairs)} possible pairs each, and ${fmt(sim.benign.cascades + sim.coordinated.cascades)} strong cascades. Before the correction for the number of pairs tested they raised ${fmt(sim.before_correction.benign_false)} and ${fmt(sim.before_correction.coordinated_false)}. The simulator contains no behaviour-only coordination, so this measures false alarms; how many real links are missed is not measured.` : "";
    host.innerHTML = `
      <div class="kpis">
        ${kpi("behaviour links", fmt(sm.links), `between ${fmt(sm.actors_linked)} of ${fmt(sm.actors)} named actors with dated actions`)}
        ${kpi("with no message", fmt(sm.behaviour_only), "invisible to the message rule")}
        ${kpi("new", fmt(sm.new), "no message and not one estimated agent")}
        ${kpi("inside one estimated agent", fmt(sm.same_agent), "two tokens, one controller: expected to move together")}
        ${kpi("also have a message", fmt(sm.with_message), "behaviour and message agree")}
        ${kpi("false links on simulated swarms", sim ? fmt(sim.benign.false + sim.coordinated.false) : "–", sim ? `of ${fmt(2 * sim.benign.possible_pairs)} pairs` : "")}
      </div>
      <p class="note small">${simText}</p>
      ${card("Behaviour links", `<div id="fxkGraph"></div>
        <div class="legend"><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${BEH}" stroke-width="3" stroke-dasharray="6 4"/></svg>behaviour link only (no message)</span><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${BEH}" stroke-width="3"/></svg>behaviour link that also has a message</span><span><svg width="30" height="10"><line x1="1" y1="5" x2="29" y2="5" stroke="${MSG}" stroke-width="1"/></svg>message only</span><span><i style="background:#2f6fb3;opacity:.3;border-radius:5px"></i>halo: tokens of one estimated agent</span><span>thicker = higher z</span></div>`,
        { sub: "Only actors with at least one behaviour link are drawn. Click an edge for its evidence, a node for the actor." })}
      ${card("Links and their statistics", `<div id="fxkTable" class="fxkscroll tall"></div>${more(r.links.length, r.links_total, "links")}
        <p class="small muted">Tested: synchrony on ${fmt(t.synchrony.pairs_tested)} pairs of ${fmt(t.synchrony.actors)} actors with ${th.min_co}+ bursts (${fmt(t.synchrony.candidates)} had ${th.min_co}+ co-bursts); adoption on ${fmt(t.adoption.pairs_tested)} pairs over ${fmt(t.adoption.techniques)} techniques (of ${fmt(t.adoption.techniques_seen)} seen; kept when ${th.min_adopters} to ${fmt(t.adoption.max_adopters)} actors adopted them); split work on ${fmt(t.complementary.pairs_tested)} pairs over ${fmt(t.complementary.resources)} numbered resources.</p>`,
        { sub: `New links first. z = how far the count is above chance, in standard deviations; p is after multiplying by every pair tested (kept at ${th.fwer} or below). Click a row for the pair.` })}
      ${card("One pair", `<div id="fxkPair"><p class="muted">Click a link in the graph or the table.</p></div>`, { sub: "Two activity rows with the starts of bursts; shaded columns are co-bursts." })}
      ${card(`Technique adoption cascades: ${plural(sm.cascades, "strong cascade")} of ${fmt(sm.cascade_candidates)} candidates`, `<div id="fxkCasc"></div>
        <p class="small muted">Rows: techniques (an intent, an evidence tag, a host or a program family) first used by 3+ actors within ${th.cascade_h} h of the first use, each actor already active for an hour. A dot per actor's first use, coloured by estimated agent, joined in order. “chance” = how many would fall in the window if each adopter picked a random moment of its own active time; a row is strong (shaded) when p ≤ ${th.p_cascade} and two or more estimated agents take part. The ${fmt(r.cascades.length)} with the lowest p are shown${sm.cascades ? "" : "; none is strong, so read them as candidates only"}.</p>`,
        { sub: "Who picked a new technique up, in what order, in the hours after its first use." })}
      ${card("Close, but not counted", r.near_misses.length ? table(["Pair", "Synchrony", "Adoption", "Message", ""], r.near_misses.map((p) => [`${ent.actor(p.a)} ${ent.actor(p.b)}`, p.synchrony ? `${p.synchrony.co_events} vs ${p.synchrony.expected} · z ${p.synchrony.z} · p ${pnum(p.synchrony.p_adj)}` : "–", p.adoption ? `${p.adoption.co_adoptions} vs ${p.adoption.expected} · z ${p.adoption.z} · p ${pnum(p.adoption.p_adj)}` : "–", p.has_message ? "yes" : "no", p.same_agent ? badge("one agent", "same") : ""])) : '<p class="muted">None.</p>',
        { sub: "The pairs nearest the thresholds. Shown so the cut is visible, not as findings." })}
      ${card("How far to trust this", `<ul class="fxkcav">
          <li><b>A behaviour link is a pattern, not a channel.</b> Two actors can move together because one controller runs both, because they follow the same instructions, or because the same outside event prompted both. Nothing here shows that one informed the other.</li>
          <li><b>Synchrony:</b> a burst is an action of an intent after ${th.window_h} h without it; a co-burst is two actors starting the same intent within ${th.window_h} h. Chance is ${fmt(th.null_draws)} redraws of one actor's burst times from all other actors' burst times, so a swarm-wide surge does not count. A link needs ${th.min_co}+ co-bursts at ${th.min_slots}+ different times, z ≥ ${th.z_sync}, and a corrected p ≤ ${th.fwer}.</li>
          <li><b>Adoption:</b> chance assumes adopters are random actors in proportion to how many techniques each adopted. A link needs ${th.min_co_adopt}+ techniques first used within ${th.pair_h} h of each other (two or more that are not program families), z ≥ ${th.z_adopt}, corrected p ≤ ${th.fwer}. What an actor does in its first hour is how it started, not adoption.</li>
          <li><b>Split work:</b> the same numbered parameter on the same target, ${th.min_values}+ values each, none shared, densely covering one grid; p ≤ ${th.p_compl} that random picks would not collide. Ranges built in a loop rather than written out are not seen.</li>
          <li><b>Times are mostly estimated</b> (median error about 15 min, 90% within about 2 h), so every window is at least an hour and the order of two first uses counts only when they are an hour apart.</li>
          <li>Hourly correlation of the most active actors is in <button type="button" class="link" id="fxkLL">Lead–lag</button>; its result for a pair is shown with the pair.</li>
        </ul>`)}`;
    const rows = r.links.map((p) => [
      `${ent.actor(p.a)} ${ent.actor(p.b)}`, p.kinds.map((k) => badge(KIND[k], "beh")).join(""),
      p.synchrony ? `${p.synchrony.co_events} vs ${p.synchrony.expected}` : "–", p.synchrony ? String(p.synchrony.z) : "–",
      p.adoption ? `${p.adoption.co_adoptions} vs ${p.adoption.expected}` : "–", p.adoption ? String(p.adoption.z) : "–", p.adoption ? pnum(p.adoption.p_adj) : "–",
      p.adoption ? `<span class="small muted">${esc(p.adoption.examples.slice(0, 2).map(techName).join(", "))}</span>` : "",
      p.has_message ? badge(`${p.messages} msg`, "msg") : badge("none"), p.same_agent ? badge("one agent", "same") : (!p.has_message ? badge("new", "new") : "")]);
    $("fxkTable").innerHTML = table(["Pair", "Link", "Co-bursts vs chance", "z", "Co-adoptions vs chance", "z", "p (corrected)", "For example", "Message", ""], rows, true);
    bindRows($("fxkTable"), (i) => { showPair(r.links[i], r); $("fxkPair").scrollIntoView({ block: "center", behavior: "smooth" }); });
    const dg = () => graph($("fxkGraph"), r); dg(); onResize($("fxkGraph"), dg);
    const dc = () => cascades($("fxkCasc"), r); dc(); onResize($("fxkCasc"), dc);
    $("fxkLL").addEventListener("click", () => { location.hash = "tab=forensics&fx=leadlag"; FX_WANT = "leadlag"; goTab("forensics"); });
    const first = r.links.find((p) => p.synchrony) || r.links[0];
    if (first) showPair(first, r);
  }

  window.FX_SECTIONS.push({ id: "silent", title: "Coordination without messages", group: "How agents behaved",
    blurb: `A ${term("message")} needs a shared place. Actors can also be tied by what they do and when: starting the same kind of work together again and again, picking up a new technique one after another, or splitting one job between them. Each tie is tested against chance and shown with its statistics.`, render });
})();

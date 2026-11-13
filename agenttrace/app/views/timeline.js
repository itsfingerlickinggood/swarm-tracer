// Timeline: when everything happened, who was active, and who talked to whom over time.
// 1. an overview strip (activity by intent, the data's turning points, warning signs, the reports' phases) that zooms
// 2. swimlanes: one row per actor, hourly cells, and every message drawn from the writer's row to the reader's
// 3. a chronology of every key moment, and 4. every hour as a row
(() => {
  "use strict";
  const HR = 3600e3;
  const RUNS = "(anonymous runs)";
  const dl = typeof deepLink === "function" ? deepLink() : {};   // #tab=timeline&order=messages&rows=messages
  const st = { z: null, sort: dl.order || "messages", show: dl.rows || "messages", lines: "named", off: new Set(), group: false, one: null, groups: null };
  let seq = 0;
  const hourKey = (t) => new Date(t).toISOString().slice(0, 13).replace("T", " ");
  const WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MOMENT = { first: "first action", surge: "surge begins", peak: "busiest hour", stop: "falls below 15% of peak", last: "last action" };
  const named = (a) => a && !String(a).startsWith("run:");
  const nmOf = (a) => (byAgent() && S.units && named(a) ? agentName(a) : short(a));
  // counting by estimated agent, one lane per agent: its tokens' hourly cells are merged, and a message between two of its
  // tokens stays in its lane as a tick. Tokens no merge touches keep their own lane. (Token mode: lanes as the server draws them.)
  function agentLanes(lanes) {
    const by = new Map(), out = [];
    lanes.actors.forEach((a) => {
      if (a.kind === "runs") { out.push(a); return; }
      const g = agentOf(a.actor);
      let L = by.get(g);
      if (!L) { L = { actor: g, kind: a.kind, tokens: 0, total: 0, first: a.first, last: a.last, first_record: a.first_record, sent: 0, received: 0, inside: 0, _b: new Map(), _h: new Map() }; by.set(g, L); out.push(L); }
      L.tokens++; L.total += a.total;
      if (toTime(a.first) < toTime(L.first)) { L.first = a.first; L.first_record = a.first_record; }
      if (toTime(a.last) > toTime(L.last)) L.last = a.last;
      a.bins.forEach((b) => { const x = L._b.get(b[0]); if (!x) L._b.set(b[0], b.slice()); else for (let k = 1; k < b.length; k++) x[k] += b[k]; });
      a.harm_bins.forEach(([hi, n]) => L._h.set(hi, (L._h.get(hi) || 0) + n));
    });
    out.forEach((L) => { if (L._b) { L.bins = [...L._b.values()].sort((p, q) => p[0] - q[0]); L.harm_bins = [...L._h.entries()]; delete L._b; delete L._h; } });
    return { ...lanes, actors: out };
  }
  // a turning point is an hour, not a moment: "13:00–14:00"
  const hourRange = (t) => `${clock(t)}–${clock(t + HR)}`;
  const MERGED_TIP = "This place may be several places the redaction merged into one owner name, so the write and the read may not be one message.";
  const niceStep = (x) => { const p = Math.pow(10, Math.floor(Math.log10(Math.max(1, x)))); return [1, 2, 2.5, 5, 10].map((k) => k * p).find((k) => k >= x) || 10 * p; };
  // a signal's reference as a chip: an actor if it names one, else a record
  const refChip = (g) => !g.ref ? "" : (g.actors || []).includes(g.ref) || String(g.ref).startsWith("[") ? ent.actor(g.ref) : ent.rec(g.ref);
  const refAttr = (g) => !g.ref ? "" : (g.actors || []).includes(g.ref) || String(g.ref).startsWith("[") ? `data-actor="${esc(g.ref)}"` : `data-id="${esc(g.ref)}"`;

  VIEWS.timeline = async function timeline(el, s) {
    const my = ++seq;
    const hours = Object.keys(s.activity_by_hour || {}).sort();
    el.innerHTML = `<h2>What happened, hour by hour</h2>`;
    if (!hours.length) {
      el.innerHTML += `<div class="empty">No record in this trace has a time, and no time could be estimated, so there is no timeline. The other tabs still work: who talked to whom and how content spread are counted without times, but their order is unknown.</div>`;
      return;
    }
    el.innerHTML += `<p class="lead" id="tlLead">Loading…</p>
      ${card("Activity and turning points", `<div id="tlOver" class="tl-strip"></div><div id="tlKey"></div>`,
        { sub: `${term("dated", "Dated")} ${term("action", "actions")} per hour (estimated times, UTC), coloured by what the code does. Most times are estimated from timestamps the agents wrote into their code; inside a fitted block records spread evenly over its time range, so long flat stretches are an artefact of the fit, not steady activity. Above the bars: the turning points in the data, each ${term("sign", "warning sign")} when it first fired, and the phases the investigators' reports describe. <b>Drag across the bars to zoom the lanes below</b>; click a bar to list that hour's events; double-click to reset.` })}
      ${card("Who was active when, and who talked to whom", `<div id="tlCtl" class="tl-ctl"></div><div id="tlZoom" class="tl-zoom"></div><div class="tl-lanewrap"><div id="tlAxis" class="tl-axis"></div><div id="tlScroll" class="tl-scroll"><div id="tlLanes"></div></div></div><div id="tlLaneKey" class="small muted tl-lanekey"></div>`,
        { sub: `One row per ${S.units && byAgent() ? `${term("agent", "estimated agent")} ${estMark()}; its tokens' cells are merged, a blue bracket and “N tok” mark an agent of several tokens, and a message between two of its own tokens is a tick in its row` : term("named", "named actor")}; the number after the name is its dated actions. Each cell is one hour (estimated times, UTC): its colour is what the actor mostly did, darker means more actions, and a red underline marks ${term("harm", "harmful actions")}. Each line is a ${term("message", "message")}: it starts where the sender wrote to a ${term("place", "place")} and ends where another actor read it; a dashed line is on a place the redaction may have ${term("merged", "merged")}. Hover a row to pick out its messages; hover a line to see the record; click a cell to list those events.` })}
      ${card("Chronology", `<div id="tlFilt" class="tl-filt"></div><div id="tlChron" class="chrono"></div>`,
        { sub: "Every key moment in time order (UTC): turning points in the data (each an hour of activity), warning signs, the first message between each pair of named actors, and what the incident reports say happened, with how far the tool's own estimate is from the report. ⚠ marks a first message on a place the redaction may have merged." })}
      ${card("Every hour", `<div id="tlHours" class="tl-hours"></div>`, { sub: "Every hour from the first dated action to the last (estimated times, UTC). Click an hour to list its events." })}`;
    let lanes, msgs, sim, ctx;
    try {
      [lanes, msgs, sim, ctx] = await Promise.all([cached("/api/lanes"), cached("/api/messages"), cached("/api/sim"), cached("/api/context").catch(() => ({}))]);
    } catch (e) { $("tlLead").textContent = e.message; return; }
    if (my !== seq || S.tab !== "timeline") return;

    const T0 = toTime(hours[0]), T1 = toTime(hours.at(-1)) + HR;
    if (st.z && (st.z[0] < T0 || st.z[1] > T1)) st.z = null;
    const AGM = byAgent() && !!S.units;
    const tokLanes = lanes;
    if (AGM) lanes = agentLanes(lanes);
    const M0 = msgs.rows.map((r) => ({ from: r[0], to: r[1], channel: r[2], write_id: r[3], read_id: r[4], wt: r[5] * 1000, rt: r[6] * 1000, lat: r[7], how: r[8], merged: !!r[9] }));
    // by agent a message is drawn between agents; one between two tokens of an agent is kept apart (an in-lane tick)
    const M = M0.map((m) => (AGM ? { ...m, tf: m.from, tt: m.to, from: named(m.from) ? agentOf(m.from) : m.from, to: named(m.to) ? agentOf(m.to) : m.to } : m));
    const insideMsgs = AGM ? M.filter((m) => named(m.from) && named(m.to) && m.from === m.to) : [];
    const namedMsgs = M.filter((m) => named(m.from) && named(m.to) && !(AGM && m.from === m.to));
    if (AGM) {
      const byL = new Map(lanes.actors.map((a) => [a.actor, a]));
      lanes.actors.forEach((a) => { a.sent = 0; a.received = 0; });
      namedMsgs.forEach((m) => { const f = byL.get(m.from), g = byL.get(m.to); if (f) f.sent++; if (g) g.received++; });
      insideMsgs.forEach((m) => { const f = byL.get(m.from); if (f) f.inside++; });
    }
    const rep = (ctx?.context?.phases || []).map((p, i, all) => {
      const a = toTime(p.start), nxt = all.slice(i + 1).map((q) => toTime(q.start)).find((t) => t != null && t > a);
      return { ...p, a, b: toTime(p.end) ?? nxt ?? a + 6 * HR, hasEnd: !!p.end };
    }).filter((p) => p.a != null);
    const D = { s, hours, lanes, tokLanes, M, namedMsgs, insideMsgs, AGM, sim, ctx, rep, T0, T1 };

    // the lead: the whole story in one sentence
    const tot = Object.fromEntries(hours.map((h) => [h, Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0)]));
    const actions = Object.values(tot).reduce((a, b) => a + b, 0);
    const peak = hours.reduce((a, h) => (tot[h] > (tot[a] || 0) ? h : a), hours[0]);
    const nNamed = lanes.actors.filter((a) => a.kind !== "runs").length;
    const nTokDated = tokLanes.actors.filter((a) => a.kind !== "runs").length;
    const allNamed = AGM ? S.units.agents : s.actions?.named_actors;
    const runLane = lanes.actors.find((a) => a.kind === "runs");
    const days = (T1 - T0) / (24 * HR);
    $("tlLead").innerHTML = `${fmt(actions)} ${term("dated", "dated")} ${term("action", "actions")} over ${days >= 2 ? days.toFixed(1) + " days" : hoursWord(days * 24)}, ${esc(when(T0))} to ${esc(when(T1))} UTC (estimated times). ` +
      `${AGM ? `${allNamed ? `${fmt(nNamed)} of the ${fmt(allNamed)}` : fmt(nNamed)} ${term("agent", "estimated agents")} ${estMark()}${hasMerges() && nTokDated !== nNamed ? ` (${fmt(nTokDated)} tokens)` : ""}` : `${allNamed ? `${fmt(nNamed)} of the ${fmt(allNamed)}` : fmt(nNamed)} ${term("named", "named actors")}`} have dated actions${runLane ? `, and ${fmt(runLane.total)} dated actions come from ${term("run", "anonymous runs")}` : ""}. The busiest hour was ${esc(when(toTime(peak)))}–${esc(clock(toTime(peak) + HR))} with ${fmt(tot[peak])} actions.` +
      (namedMsgs.length ? (() => {
        const ex = namedMsgs.filter((m) => !m.merged), mg = namedMsgs.length - ex.length;
        const first = Math.min(...namedMsgs.map((m) => m.rt)), firstExact = ex.length ? Math.min(...ex.map((m) => m.rt)) : null;
        return ` ${plural(namedMsgs.length, "message")} passed between ${AGM ? `estimated agents ${estMark()}` : "named actors"}${AGM && insideMsgs.length ? ` (${fmt(insideMsgs.length)} more inside one agent, drawn as ticks)` : ""}${mg ? ` (${fmt(mg)} of them on places the redaction may have ${term("merged", "merged")})` : ""}. ` +
          (firstExact != null ? `The first on an exact place was read at ${esc(when(firstExact))}: the warning sign “first message between ${AGM ? "estimated agents" : "named actors"}”.` : "") +
          (firstExact != null && first < firstExact ? ` One read earlier, at ${esc(when(first))}, is on a merged place, so it may not be one message.` : "");
      })() : "");

    drawOverview(D);
    // the Agents tab's estimated agents (merge groups); optional, the lanes work without them
    D.groups = [];
    try { const idn = await cached("/api/x/identity"); D.groups = (idn.groups || []).filter((g) => (g.actors || []).length > 1); } catch { D.groups = []; }
    if (my !== seq || S.tab !== "timeline") return;
    controls(D);
    drawLanes(D);
    chronology(D);
    hourTable(D);
    onResize($("tlOver"), () => drawOverview(D));
    onResize($("tlScroll"), () => drawLanes(D));
  };

  // ------------------------------------------------------------------ 1. overview strip
  function drawOverview(D) {
    const host = $("tlOver");
    if (!host) return;
    const { s, hours, sim, rep, T0, T1 } = D;
    const W = Math.max(420, host.clientWidth || 700), L = 58, R = 14;
    const X = (t) => L + (t - T0) / (T1 - T0) * (W - L - R);
    const tAt = (x) => T0 + (x - L) / (W - L - R) * (T1 - T0);
    const intents = Object.keys(s.intents).filter((k) => k !== "other").concat(s.intents.other ? ["other"] : []);
    const tot = Object.fromEntries(hours.map((h) => [h, Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0)]));
    const mx = Math.max(1, ...Object.values(tot));

    // rows from the top: report phases (two staggered rows), warning signs, the data's moments, then the bars
    const repIn = rep.filter((p) => p.b > T0 && p.a < T1);
    let y = 6;
    const yRep = y; if (repIn.length) y += 2 * 15 + 6;
    const ySig = y + 8; y += 3 * 11 + 6;
    const yMom = y + 10; y += 2 * 13 + 6;
    const yT = y, yB = y + 150, H = yB + 26;
    let svg = `<svg class="chart tl-over" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Timed actions per hour with turning points and warning signs">`;

    if (repIn.length) {
      svg += `<text x="4" y="${yRep + 11}" font-size="10.5" fill="${C.place}" font-weight="600">Reports</text>`;
      repIn.forEach((p, i) => {
        const a = Math.max(T0, p.a), b = Math.min(T1, p.b), x0 = X(a), x1 = Math.max(x0 + 3, X(b)), ry = yRep + (i % 2) * 15;
        const cut = p.a < T0 ? "← " : "";
        const label = fitName(cut + p.name, x1 - x0 - 6, "10.5px -apple-system, system-ui, sans-serif");
        svg += `<g class="tl-rep"><title>${esc(p.name)} · ${esc(p.start || "")}${p.end ? " to " + esc(p.end) : ""}\n${esc(p.what || "")}\n(${esc(p.source || "")})</title>
          <rect x="${x0}" y="${ry}" width="${x1 - x0}" height="13" rx="3" fill="${i % 2 ? "#e9e1f8" : "#f3eefb"}" stroke="#c9b8ee"/>
          ${label.length > 2 ? `<text x="${x0 + 4}" y="${ry + 10}" font-size="10.5" fill="#4c2f94">${esc(label)}</text>` : ""}</g>`;
      });
    }
    // warning signs: one dot each, staggered when they would touch
    const sigs = (sim.signals || []).map((g) => ({ ...g, ms: toTime(g.t) })).filter((g) => g.ms != null && g.ms >= T0 && g.ms <= T1).sort((a, b) => a.ms - b.ms);
    svg += `<text x="4" y="${ySig + 14}" font-size="10.5" fill="${QUIET}" font-weight="600">Signs</text>`;
    const laneX = [-99, -99, -99];
    sigs.forEach((g) => {
      const x = X(g.ms);
      let ln = laneX.findIndex((lx) => x - lx >= 12); if (ln < 0) ln = laneX.indexOf(Math.min(...laneX));
      laneX[ln] = x;
      const cy = ySig + ln * 11 + 4, c = FAMILY[g.family]?.color || SINGLE;
      svg += `<line x1="${x}" x2="${x}" y1="${cy}" y2="${yB}" stroke="${c}" stroke-opacity=".18"/>`;
      svg += `<circle class="node" ${refAttr(g)} cx="${x}" cy="${cy}" r="4.5" fill="${g.family === "baseline" ? "#fff" : c}" stroke="${c}" stroke-width="${g.family === "baseline" ? 1.6 : 1}"><title>${esc(g.name)} · ${esc(g.time)} UTC\n${esc(g.why || "")}${g.harm_share_after != null ? `\n${pct(g.harm_share_after)} of harmful actions still to come` : ""}</title></circle>`;
    });
    // the data's own moments
    svg += `<text x="4" y="${yMom + 9}" font-size="10.5" fill="${QUIET}" font-weight="600">Data</text>`;
    const placed = [];
    (s.phases || []).forEach((p) => {
      const t = toTime(p.time); if (t == null || t < T0 || t > T1) return;
      const x = X(t), label = MOMENT[p.key] || p.name, w = textWidth(label, "10.5px -apple-system, system-ui, sans-serif");
      let lx = Math.min(Math.max(L, x - w / 2), W - R - w);
      let row = 0; while (placed.some((q) => q.row === row && lx < q.x1 + 6 && lx + w > q.x0 - 6) && row < 1) row++;
      placed.push({ x0: lx, x1: lx + w, row });
      const yy = yMom + row * 13;
      svg += `<g><title>${esc(p.name)} · the hour ${esc(when(t))}–${esc(clock(t + HR))} UTC${p.why ? " · " + esc(p.why) : ""}</title><text x="${lx}" y="${yy + 9}" font-size="10.5" fill="#3d4a58">${esc(label)}</text>
        <line x1="${x}" x2="${x}" y1="${yy + 12}" y2="${yB}" stroke="#7d8790" stroke-dasharray="2 3" stroke-opacity=".7"/></g>`;
    });
    // bars
    const step = niceStep(mx / 4);
    for (let v = 0; v <= mx; v += step) { const yy = yB - v / mx * (yB - yT); svg += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="${GRID}"/><text x="${L - 6}" y="${yy + 4}" text-anchor="end" font-size="10.5" fill="${QUIET}">${fmt(v)}</text>`; }
    hours.forEach((h) => {
      const t = toTime(h), x = X(t), bw = Math.max(1, X(t + HR) - x - 0.6);
      let yy = yB;
      intents.forEach((it) => { const v = s.activity_by_hour[h][it] || 0; if (!v) return; const hh = v / mx * (yB - yT); yy -= hh; svg += `<rect x="${x.toFixed(1)}" y="${yy.toFixed(1)}" width="${bw.toFixed(2)}" height="${hh.toFixed(2)}" fill="${intentColor(it)}"/>`; });
    });
    svg += `<line x1="${L}" x2="${W - R}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    timeTicks(T0, T1, Math.max(3, Math.floor((W - L - R) / 80))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 4}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${yB + 17}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    // the zoomed window, and the brush zone on top of the bars
    if (st.z) {
      const a = X(st.z[0]), b = X(st.z[1]);
      svg += `<rect x="${L}" y="${yT}" width="${Math.max(0, a - L)}" height="${yB - yT}" fill="#fff" fill-opacity=".7"/><rect x="${b}" y="${yT}" width="${Math.max(0, W - R - b)}" height="${yB - yT}" fill="#fff" fill-opacity=".7"/>
        <rect x="${a}" y="${yT}" width="${b - a}" height="${yB - yT}" fill="none" stroke="${ACCENT}" stroke-width="1.2"/>`;
    }
    svg += `<rect class="tl-sel" x="0" y="${yT}" width="0" height="${yB - yT}" fill="${ACCENT}" fill-opacity=".12" stroke="${ACCENT}"/>`;
    svg += `<rect class="tl-zone" x="${L}" y="${yT}" width="${W - L - R}" height="${yB - yT}" fill="transparent"/></svg>`;
    host.innerHTML = svg + '<div class="tl-tip" hidden></div>';

    // legend
    const dated = {};
    hours.forEach((h) => Object.entries(s.activity_by_hour[h]).forEach(([k, v]) => { dated[k] = (dated[k] || 0) + v; }));
    $("tlKey").innerHTML = `<div class="legend">${intents.filter((k) => dated[k]).map((k) => `<span title="${esc(intentName(k))}: ${fmt(dated[k])} dated of ${fmt(s.intents[k])} in all"><i style="background:${intentColor(k)}"></i>${esc(human(k))}${isHarm(k) ? ' <em class="tl-harm">harmful</em>' : ""} <b>${fmt(dated[k])}</b></span>`).join("")}</div>
      <div class="small muted tl-keynote">Counts are dated actions, as drawn; hover one for its total including undated actions.</div>
      <div class="legend tl-famkey">${["joint", "single", "baseline"].filter((f) => sigs.some((g) => g.family === f)).map((f) => `<span><i style="border-radius:50%;background:${f === "baseline" ? "#fff" : FAMILY[f].color};border:1.5px solid ${FAMILY[f].color}"></i>warning sign: ${esc(FAMILY[f].label)}</span>`).join("")}${repIn.length ? `<span><i style="background:#f3eefb;border:1px solid #c9b8ee"></i>phase in the incident reports</span>` : ""}</div>`;

    // brush, click and hover
    const svgEl = host.querySelector("svg"), zone = svgEl.querySelector(".tl-zone"), sel = svgEl.querySelector(".tl-sel"), tip = host.querySelector(".tl-tip");
    const px = (e) => e.clientX - svgEl.getBoundingClientRect().left;
    let drag = null;
    zone.addEventListener("pointerdown", (e) => { drag = { x0: px(e), x1: px(e) }; zone.setPointerCapture(e.pointerId); tip.hidden = true; });
    zone.addEventListener("pointermove", (e) => {
      const x = Math.max(L, Math.min(W - R, px(e)));
      if (drag) { drag.x1 = x; sel.setAttribute("x", Math.min(drag.x0, x)); sel.setAttribute("width", Math.abs(x - drag.x0)); return; }
      const h = hourKey(Math.floor(tAt(x) / HR) * HR), row = s.activity_by_hour[h];
      if (!row) { tip.hidden = true; return; }
      const parts = Object.entries(row).sort((a, b) => b[1] - a[1]);
      tip.innerHTML = `<b>${esc(when(toTime(h)))}</b> · ${fmt(tot[h])} actions${parts.slice(0, 5).map(([k, v]) => `<div><i style="background:${intentColor(k)}"></i>${esc(human(k))} <b>${fmt(v)}</b></div>`).join("")}<div class="muted">click to list · drag to zoom</div>`;
      tip.hidden = false;
      tip.style.left = Math.min(x + 12, W - 190) + "px"; tip.style.top = (yT + 4) + "px";
    });
    zone.addEventListener("pointerleave", () => { if (!drag) tip.hidden = true; });
    zone.addEventListener("pointerup", (e) => {
      if (!drag) return;
      const d = drag; drag = null; sel.setAttribute("width", 0);
      if (Math.abs(d.x1 - d.x0) < 4) {
        const h = hourKey(Math.floor(tAt(d.x0) / HR) * HR);
        if (s.activity_by_hour[h]) goEvents({ hour: h });
        return;
      }
      const a = Math.floor(tAt(Math.min(d.x0, d.x1)) / HR) * HR, b = Math.ceil(tAt(Math.max(d.x0, d.x1)) / HR) * HR;
      setZoom(D, [Math.max(T0, a), Math.min(T1, Math.max(b, a + 2 * HR))]);
      const wrap = document.querySelector(".tl-lanewrap");
      if (wrap) requestAnimationFrame(() => wrap.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    });
    zone.addEventListener("dblclick", () => setZoom(D, null));
  }

  function setZoom(D, z) {
    st.z = z && (z[0] > D.T0 || z[1] < D.T1) ? z : null;
    drawOverview(D);
    drawLanes(D);
  }

  // ------------------------------------------------------------------ 2. swimlanes
  function controls(D) {
    const hasRuns = D.lanes.actors.some((a) => a.kind === "runs");
    $("tlCtl").innerHTML = `
      <label>Order <select id="tlSort"><option value="first">first seen</option><option value="activity">most active</option><option value="messages">most messages</option></select></label>
      <label>Rows <select id="tlShow"><option value="all">every ${D.AGM ? "agent" : "actor"}</option><option value="messages">${D.AGM ? "agents" : "actors"} in messages</option><option value="window">active in the zoomed window</option></select></label>
      <label>Message lines <select id="tlLines"><option value="named">between ${D.AGM ? "estimated agents" : "named actors"}</option>${hasRuns ? '<option value="all">all, anonymous runs on the bottom row</option>' : ""}<option value="none">none</option></select></label>
      ${D.namedMsgs.length ? '<button type="button" id="tlFit">Zoom to the messages</button>' : ""}
      ${D.groups.length && !D.AGM ? `<label title="The Agents tab's estimated agents: identities its evidence suggests one agent holds"><input type="checkbox" id="tlGroup"${st.group ? " checked" : ""}> group by estimated agent (${plural(D.groups.length, "group")})</label>` : ""}
      <label>One lane <input id="tlOne" list="tlOneList" placeholder="${D.AGM ? "an agent" : "an actor"}" value="${esc(st.one || "")}" style="width:150px"></label><datalist id="tlOneList">${D.lanes.actors.filter((a) => a.kind !== "runs").sort((a, b) => b.total - a.total).slice(0, 500).map((a) => `<option value="${esc(a.actor)}">${esc(D.AGM ? agentName(a.actor) : short(a.actor))}${D.AGM && a.tokens > 1 ? ` · ${fmt(a.tokens)} tokens` : ""} · ${fmt(a.total)} actions</option>`).join("")}</datalist>
      ${st.one ? '<button type="button" id="tlOneClear">All lanes</button>' : ""}`;
    $("tlSort").value = st.sort; $("tlShow").value = st.show; $("tlLines").value = hasRuns || st.lines !== "all" ? st.lines : "named";
    $("tlSort").addEventListener("change", (e) => { st.sort = e.target.value; drawLanes(D); });
    $("tlShow").addEventListener("change", (e) => { st.show = e.target.value; drawLanes(D); });
    $("tlLines").addEventListener("change", (e) => { st.lines = e.target.value; drawLanes(D); });
    if ($("tlGroup")) $("tlGroup").addEventListener("change", (e) => { st.group = e.target.checked; drawLanes(D); });
    $("tlOne").addEventListener("change", (e) => setOne(D, e.target.value.trim()));
    if ($("tlOneClear")) $("tlOneClear").addEventListener("click", () => setOne(D, null));
    if ($("tlFit")) $("tlFit").addEventListener("click", () => {
      const ts = D.namedMsgs.flatMap((m) => [m.wt, m.rt]);
      setZoom(D, [Math.max(D.T0, Math.floor(Math.min(...ts) / HR) * HR - HR), Math.min(D.T1, Math.ceil(Math.max(...ts) / HR) * HR + HR)]);
    });
  }

  // zoom to one lane: that actor, the actors it exchanged messages with, and its own active span
  function setOne(D, v) {
    const a = v ? D.lanes.actors.find((x) => x.kind !== "runs" && (x.actor === v || short(x.actor) === v || (D.AGM && agentName(x.actor) === v))) : null;
    st.one = a ? a.actor : null;
    if (a) {
      const t0 = Math.floor(toTime(a.first) / HR) * HR, t1 = Math.ceil(toTime(a.last) / HR) * HR + HR;
      st.z = t0 > D.T0 || t1 < D.T1 ? [Math.max(D.T0, t0 - HR), Math.min(D.T1, Math.max(t1 + HR, t0 + 3 * HR))] : null;
    } else st.z = null;
    controls(D);
    drawOverview(D);
    drawLanes(D);
  }

  function drawLanes(D) {
    const host = $("tlLanes"), scroll = $("tlScroll");
    if (!host) return;
    const { lanes, M, T0, T1, s } = D;
    const [z0, z1] = st.z || [T0, T1];
    const W = Math.max(420, scroll.clientWidth || 700), LW = Math.round(Math.min(178, Math.max(124, W * 0.21))), R = 10, LH = 13;
    const X = (t) => LW + (t - z0) / (z1 - z0) * (W - LW - R);
    const start = lanes.start_t * 1000;
    let rows = lanes.actors.filter((a) => a.kind !== "runs");
    const runs = lanes.actors.find((a) => a.kind === "runs");
    if (st.show === "messages") rows = rows.filter((a) => a.sent || a.received);
    if (st.show === "window") rows = rows.filter((a) => a.bins.some(([hi]) => { const t = start + hi * HR; return t + HR > z0 && t < z1; }));
    if (st.sort === "activity") rows.sort((a, b) => b.total - a.total);
    else if (st.sort === "messages") rows.sort((a, b) => (b.sent + b.received) - (a.sent + a.received) || b.total - a.total);
    else rows.sort((a, b) => (a.first < b.first ? -1 : a.first > b.first ? 1 : 0));
    if (st.one) {
      const me = lanes.actors.find((a) => a.actor === st.one);
      const partners = new Set();
      M.forEach((m) => { if (m.from === st.one && named(m.to)) partners.add(m.to); if (m.to === st.one && named(m.from)) partners.add(m.from); });
      rows = me ? [me, ...lanes.actors.filter((a) => a.kind !== "runs" && a.actor !== st.one && partners.has(a.actor)).sort((a, b) => (b.sent + b.received) - (a.sent + a.received))] : rows;
    } else if (runs && (st.show === "all" || st.lines === "all")) rows.push(runs);
    // group lanes by the Agents tab's estimated agents: members of one group sit together under a header
    const gOf = new Map();
    if (st.group && !st.one && !D.AGM) (D.groups || []).forEach((g, i) => g.actors.forEach((a) => gOf.set(a, i)));
    if (gOf.size) {
      const out = [], done = new Set();
      rows.forEach((r) => {
        if (done.has(r.actor)) return;
        const gi = gOf.get(r.actor);
        if (gi == null) { out.push(r); done.add(r.actor); return; }
        const members = rows.filter((x) => gOf.get(x.actor) === gi);
        out.push({ header: true, actor: "\u0000g" + gi, label: `estimated agent ${gi + 1}: ${plural(members.length, "identity", "identities")} shown of ${fmt(D.groups[gi].actors.length)}` });
        members.forEach((x) => { out.push({ ...x, inGroup: gi }); done.add(x.actor); });
      });
      rows = out;
    }

    const H = rows.length * LH + 4;
    const yOf = new Map(rows.filter((r) => !r.header).map((r) => [r.actor, 2 + rows.indexOf(r) * LH + LH / 2]));
    let mxCell = 1;
    lanes.actors.forEach((a) => a.bins.forEach((b) => { let n = 0; for (let k = 1; k < b.length; k++) n += b[k]; if (n > mxCell) mxCell = n; }));
    const nameFont = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    let svg = `<svg class="tl-lanes" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><clipPath id="tlClip"><rect x="${LW}" y="0" width="${W - LW - R}" height="${H}"/></clipPath>
      <marker id="tlArrow" viewBox="0 0 10 10" refX="8" refY="5" markerUnits="userSpaceOnUse" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,1L10,5L0,9z" fill="${ACCENT}"/></marker></defs>`;
    // the data's moments as faint lines behind everything
    (s.phases || []).forEach((p) => { const t = toTime(p.time); if (t != null && t >= z0 && t <= z1) svg += `<line x1="${X(t)}" x2="${X(t)}" y1="0" y2="${H}" stroke="#7d8790" stroke-dasharray="2 4" stroke-opacity=".45"/>`; });
    rows.forEach((r, i) => {
      const y = 2 + i * LH, isRuns = r.kind === "runs";
      if (r.header) {
        svg += `<g class="lane tl-ghead"><rect x="0" y="${y}" width="${W}" height="${LH}" fill="#eef3fa"/><text x="4" y="${y + LH - 3}" font-size="10" font-weight="600" fill="${ACCENT}">${esc(r.label)}</text></g>`;
        return;
      }
      const mine = st.one === r.actor;
      const multi = D.AGM && !isRuns && r.tokens > 1;
      const right = `${multi ? `${fmt(r.tokens)} tok · ` : ""}${fmt(r.total)}`;
      const shown = isRuns ? RUNS : D.AGM ? agentName(r.actor) : short(r.actor);
      const label = fitName(shown, LW - 16 - textWidth(right, "10px -apple-system, system-ui, sans-serif"), nameFont);
      const who = multi ? `data-agent="${esc(r.actor)}"` : `data-actor="${esc(r.actor)}"`;
      const harm = new Map(r.harm_bins.map(([hi, n]) => [hi, n]));
      svg += `<g class="lane" data-lane="${esc(r.actor)}">${mine ? `<rect x="0" y="${y}" width="${W}" height="${LH}" fill="#fff4e0"/>` : i % 2 ? "" : `<rect x="0" y="${y}" width="${W}" height="${LH}" fill="#f7f9fb"/>`}
        ${r.inGroup != null ? `<rect x="0" y="${y}" width="2.5" height="${LH}" fill="${ACCENT}"/>` : ""}${multi ? `<rect class="tl-halo" x="0.5" y="${y + 0.5}" width="${W - 1}" height="${LH - 1}" fill="none" stroke="${ACCENT}" stroke-opacity=".35" rx="2"/><path d="M5,${y + 1.5} H1.5 V${y + LH - 1.5} H5" fill="none" stroke="${ACCENT}" stroke-width="1.6"/>` : ""}
        <text class="lname" ${isRuns ? "" : `${who} data-one="${esc(r.actor)}"`} x="${multi ? 9 : 6}" y="${y + LH - 3}" font-size="11" fill="${isRuns ? QUIET : "#7a4d0c"}"${mine ? ' font-weight="700"' : ""}><title>${esc(isRuns ? RUNS : multi ? `${agentLabel(r.actor)} (estimated: tokens merged on direct evidence)` : r.actor)}${isRuns ? "" : multi ? " · click for its tokens, double-click to zoom to this lane" : " · click for its profile, double-click to zoom to this lane"}</title>${esc(label)}</text>
        <text x="${LW - 6}" y="${y + LH - 3}" font-size="10" fill="${QUIET}" text-anchor="end"><title>${multi ? `${fmt(r.tokens)} tokens merged into this agent; ${fmt(r.total)} dated actions` : `${fmt(r.total)} dated actions`}</title>${multi ? `<tspan fill="${ACCENT}">${fmt(r.tokens)} tok</tspan> · ` : ""}${fmt(r.total)}</text><g clip-path="url(#tlClip)">`;
      r.bins.forEach((b) => {
        const t = start + b[0] * HR;
        if (t + HR <= z0 || t >= z1) return;
        let n = 0, best = 1;
        for (let k = 1; k < b.length; k++) { n += b[k]; if (b[k] > b[best]) best = k; }
        const it = lanes.intents[best - 1], x = X(t), w = Math.max(1, X(t + HR) - x - 0.5);
        const parts = lanes.intents.map((k, j) => [k, b[j + 1]]).filter((p) => p[1]).sort((p, q) => q[1] - p[1]);
        const op = (0.28 + 0.72 * Math.log1p(n) / Math.log1p(mxCell)).toFixed(2);
        const hn = harm.get(b[0]);
        svg += `<rect class="cell" data-h="${hourKey(t)}" x="${x.toFixed(1)}" y="${y + 1.5}" width="${w.toFixed(2)}" height="${LH - 3}" fill="${intentColor(it)}" fill-opacity="${op}"><title>${esc(isRuns ? RUNS : shown)} · ${esc(when(t))} · ${plural(n, "action")}\n${parts.slice(0, 4).map(([k, v]) => `${human(k)} ${fmt(v)}`).join(", ")}${hn ? `\n${fmt(hn)} harmful` : ""}\nclick to list these events</title></rect>`;
        if (hn) svg += `<rect x="${x.toFixed(1)}" y="${y + LH - 2.6}" width="${w.toFixed(2)}" height="1.8" fill="${HARM}"/>`;
      });
      svg += `</g></g>`;
    });
    // message lines from the writer's row at write time to the reader's row at read time
    const laneOf = (a) => (named(a) ? a : RUNS);
    const lines = st.lines === "none" ? [] : M.filter((m) => (st.lines === "all" || (named(m.from) && named(m.to))) && yOf.has(laneOf(m.from)) && yOf.has(laneOf(m.to)) && m.rt >= z0 && m.wt <= z1 && (!st.one || m.from === st.one || m.to === st.one));
    svg += `<g clip-path="url(#tlClip)">`;
    lines.forEach((m) => {
      const x1 = X(m.wt), x2 = X(m.rt), y1 = yOf.get(laneOf(m.from)), y2 = yOf.get(laneOf(m.to));
      const dx = Math.max(8, Math.min(60, Math.abs(x2 - x1) / 2));
      svg += `<path class="msg${m.merged ? " merged" : ""}" data-a="${esc(laneOf(m.from))}" data-b="${esc(laneOf(m.to))}" data-id="${esc(m.read_id)}" d="M${x1.toFixed(1)},${y1} C${(x1 + dx).toFixed(1)},${y1} ${(x2 - dx).toFixed(1)},${y2} ${x2.toFixed(1)},${y2}" marker-end="url(#tlArrow)"><title>${esc(nmOf(m.from))} → ${esc(nmOf(m.to))}${D.AGM && m.tf ? ` (tokens ${esc(short(m.tf))} → ${esc(short(m.tt))})` : ""} via ${esc(placeLabel(m.channel))}\nwritten ${esc(when(m.wt))} in ${esc(m.write_id)}, read ${esc(when(m.rt))} in ${esc(m.read_id)} (${esc(hoursWord(m.lat))} later)\n${esc(m.how || "")}${m.merged ? "\n⚠ " + esc(MERGED_TIP) : ""}</title></path>
        <circle class="msgend" data-a="${esc(laneOf(m.from))}" data-b="${esc(laneOf(m.to))}" cx="${x1.toFixed(1)}" cy="${y1}" r="1.8" fill="${ACCENT}"/>`;
    });
    // a message between two tokens of one agent: a tick in the agent's own row, at the read time
    const ticks = !D.AGM || st.lines === "none" ? [] : D.insideMsgs.filter((m) => yOf.has(m.from) && m.rt >= z0 && m.rt <= z1 && (!st.one || m.from === st.one));
    ticks.forEach((m) => {
      const x = X(m.rt), y = yOf.get(m.from);
      svg += `<line class="msg tick" data-a="${esc(m.from)}" data-b="${esc(m.to)}" data-id="${esc(m.read_id)}" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${y - LH / 2 + 1.5}" y2="${y + LH / 2 - 1.5}" stroke-width="2.2" stroke-opacity=".85"><title>${esc(short(m.tf))} → ${esc(short(m.tt))}: two tokens of ${esc(agentName(m.from))}, inside one agent\nwritten ${esc(when(m.wt))} in ${esc(m.write_id)}, read ${esc(when(m.rt))} in ${esc(m.read_id)}</title></line>`;
    });
    svg += `</g></svg>`;
    host.innerHTML = svg;

    // the time axis above the scrolling lanes
    let ax = `<svg width="${W}" height="24" viewBox="0 0 ${W} 24"><text x="6" y="16" font-size="10" fill="${QUIET}">${D.AGM ? "estimated agent" : "actor"}</text><text x="${LW - 6}" y="16" font-size="10" fill="${QUIET}" text-anchor="end"><title>Dated actions by each actor, over the whole span</title>actions</text>`;
    timeTicks(z0, z1, Math.max(3, Math.floor((W - LW - R) / 80))).forEach((k) => { ax += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="18" y2="24" stroke="${AXIS}"/><text x="${X(k.t)}" y="14" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    $("tlAxis").innerHTML = ax + "</svg>";
    const nRows = rows.filter((r) => !r.header).length;
    $("tlZoom").innerHTML = (st.one ? `One lane: ${D.AGM ? ent.agent(st.one) : ent.actor(st.one)} (highlighted) and the ${plural(nRows - 1, D.AGM ? "agent" : "actor")} it exchanged messages with; only its messages are drawn. <button type="button" class="link" id="tlOneClear2">All lanes</button> ` : "") +
      (gOf.size ? `Grouped by the Agents tab's estimated agents (a blue edge marks a member); ungrouped actors in between. ` : "") +
      (D.AGM && D.tokLanes.actors.length !== lanes.actors.length ? `Over the whole trace ${fmt(D.tokLanes.actors.filter((a) => a.kind !== "runs").length)} tokens make ${fmt(lanes.actors.filter((a) => a.kind !== "runs").length)} agent rows ${estMark()}; a row of several tokens has a blue bracket. ` : "") +
      `${plural(nRows, "row")}${rows.some((r) => r.kind === "runs") ? " (the last is every anonymous run together)" : ""}; the number after each name is its dated actions. ` +
      (st.z ? `Zoomed to <b>${esc(when(z0))}</b> – <b>${esc(when(z1))}</b> (${hoursWord((z1 - z0) / HR)}). <button type="button" class="link" id="tlReset">Show everything</button>` : `Showing the whole span. Drag across the chart above to zoom.`);
    if ($("tlReset")) $("tlReset").addEventListener("click", () => setZoom(D, null));
    if ($("tlOneClear2")) $("tlOneClear2").addEventListener("click", () => setOne(D, null));
    const shown = new Set();
    rows.filter((r) => !r.header).forEach((r) => r.bins.forEach((b) => { let best = 1; for (let k = 1; k < b.length; k++) if (b[k] > b[best]) best = k; shown.add(lanes.intents[best - 1]); }));
    const nMerged = lines.filter((m) => m.merged).length;
    $("tlLaneKey").innerHTML = `<div class="legend">${lanes.intents.filter((k) => shown.has(k)).map((k) => `<span title="${esc(intentName(k))}"><i style="background:${intentColor(k)}"></i>${esc(human(k))}</span>`).join("")}
        <span><i style="background:linear-gradient(90deg,${ACCENT}44,${ACCENT})"></i>darker: more actions that hour</span>
        <span><i class="tl-key-harm"></i>harmful actions that hour</span>
        <span><i class="tl-key-line"></i>message, writer → reader</span>${ticks.length ? `<span><i class="tl-key-tick"></i>message inside one agent (${fmt(ticks.length)})</span>` : ""}${rows.some((r) => r.tokens > 1) ? `<span><i class="tl-key-halo"></i>agent of several tokens</span>` : ""}${nMerged ? `<span><i class="tl-key-line dashed"></i>on a possibly merged place</span>` : ""}</div>
      ${plural(lines.length, "message line")} drawn${ticks.length ? ` and ${plural(ticks.length, "in-row tick")}` : ""}${nMerged ? ` (${fmt(nMerged)} dashed)` : ""}${st.lines === "named" && M.length > D.namedMsgs.length + D.insideMsgs.length ? ` · ${fmt(M.length - D.namedMsgs.length - D.insideMsgs.length)} more involve anonymous runs: choose “all” to draw them on the bottom row` : ""}.`;
    // a large SVG swapped inside a scrolling box can stay unpainted until scrolled: keep the scroll in range and nudge a repaint
    if (scroll.scrollTop > Math.max(0, H - scroll.clientHeight)) scroll.scrollTop = 0;
    requestAnimationFrame(() => { scroll.scrollTop += 1; scroll.scrollTop -= 1; });

    // hover a row: its messages stand out
    const el = host.querySelector("svg");
    let cur = null;
    const light = (lane, one) => {
      if (lane === cur && !one) return;
      cur = lane;
      el.classList.toggle("dim", !!lane || !!one);
      el.querySelectorAll(".msg,.msgend").forEach((p) => p.classList.toggle("hi", one ? p === one : !!lane && (p.dataset.a === lane || p.dataset.b === lane)));
      el.querySelectorAll(".lane").forEach((g) => g.classList.toggle("lo", !!lane && g.dataset.lane !== lane && !(one && (g.dataset.lane === one.dataset.a || g.dataset.lane === one.dataset.b))));
    };
    el.addEventListener("mouseover", (e) => {
      const m = e.target.closest(".msg");
      if (m) { cur = null; light(null, m); return; }
      const g = e.target.closest(".lane");
      light(g ? g.dataset.lane : null);
    });
    el.addEventListener("mouseleave", () => light(null));
    el.addEventListener("dblclick", (e) => { const t = e.target.closest("[data-one]"); if (t) setOne(D, t.dataset.one); });
    el.addEventListener("click", (e) => {
      const c = e.target.closest("rect.cell");
      if (!c) return;
      const lane = c.closest(".lane").dataset.lane;
      if (!lane) return;
      goEvents({ actor: lane === RUNS ? "" : lane, hour: c.dataset.h });
    });
  }

  // ------------------------------------------------------------------ 3. chronology
  const TYPES = [
    { key: "moment", label: "Turning points in the data (hours)", icon: "◆", color: "#5d6d7e" },
    { key: "joint", label: "Warning signs: actors together", icon: "●", color: ACCENT },
    { key: "single", label: "Warning signs: one actor", icon: "●", color: SINGLE },
    { key: "baseline", label: "Volume alarms (baseline)", icon: "○", color: BASE },
    { key: "contact", label: "First message between two actors", icon: "→", color: C.actor },
    { key: "report", label: "Phases in the reports", icon: "■", color: C.place },
    { key: "milestone", label: "Report times vs the tool's estimate", icon: "⚑", color: "#8a5a00" },
  ];
  function chronology(D) {
    const { s, sim, namedMsgs, ctx, rep, T0, T1 } = D;
    const out = [];
    (s.phases || []).forEach((p) => { const t = toTime(p.time); out.push({ t, type: "moment", title: `${p.name} (the hour ${hourRange(t)})`, body: esc(p.why || "") }); });
    (sim.signals || []).forEach((g) => out.push({ t: toTime(g.t), type: g.family in FAMILY ? g.family : "single", title: g.name,
      body: `${esc(g.why || "")}${g.harm_share_after != null ? ` <span class="tl-share">${meter(g.harm_share_after, HARM, 54)} ${pct(g.harm_share_after)} of harm still to come</span>` : ""}`,
      chips: [refChip(g), g.record && g.record !== g.ref ? ent.rec(g.record) : "", ...(g.actors || []).filter((a) => a !== g.ref && named(a)).map((a) => unitChip(a))].filter(Boolean).join(" ") }));
    const seen = new Set();
    const sorted = namedMsgs.slice().sort((a, b) => a.rt - b.rt);
    const firstExact = sorted.find((m) => !m.merged);
    sorted.forEach((m) => {
      const k = m.from + "\u0000" + m.to;
      const isSign = m === firstExact;
      // the first message on an exact place is the warning sign: list it even when the pair met earlier on a merged place
      const earlier = seen.has(k);
      if (earlier && !isSign) return; seen.add(k);
      const back = seen.has(m.to + "\u0000" + m.from);
      out.push({ t: m.rt, type: "contact", title: `${m.merged ? `<span class="tl-warn" title="${esc(MERGED_TIP)}">⚠</span> ` : ""}${esc(nmOf(m.from))} → ${esc(nmOf(m.to))}${back ? ' <span class="badge" title="each of the two has now read the other">now both ways</span>' : ""}${isSign ? ' <span class="badge sign">first on an exact place: the warning sign</span>' : ""}`, html: true,
        body: `${earlier ? "first message on an exact place" : "first message"} from ${esc(nmOf(m.from))} to ${esc(nmOf(m.to))}: written ${esc(when(m.wt))}, read ${m.lat != null && m.lat < 1 / 60 ? "under a minute" : esc(hoursWord(m.lat))} later · ${esc(m.how || "")}${m.merged ? ` · <span class="tl-warnt">on a place the redaction may have merged, so the write and the read may not be one message</span>` : ""}`,
        chips: `${unitChip(m.from)} ${ent.place(m.channel)} ${unitChip(m.to)} ${ent.rec(m.write_id)} ${ent.rec(m.read_id)}` });
    });
    rep.forEach((p) => out.push({ t: p.a, type: "report", title: p.name, body: `${esc(p.what || "")} <span class="muted">(${esc(p.source || "")})</span>`, out: p.a < T0 || p.a > T1, until: p.hasEnd ? p.b : null }));
    (ctx?.milestones?.milestones || []).forEach((m) => {
      const d = m.difference_h;
      out.push({ t: toTime(m.source_time), type: "milestone", title: m.event,
        body: `Report: <b>${esc(m.source_time)}</b> <span class="muted">(${esc(m.source)})</span> · tool's estimate: <b>${esc(m.ours || "not found")}</b>${d != null ? ` <span class="tl-diff ${Math.abs(d) <= 1 ? "ok" : Math.abs(d) <= 3 ? "mid" : "far"}">${d > 0 ? "+" : ""}${d} h</span>` : ""} <span class="muted">· matched on ${esc(m.match || "")}</span>` });
    });
    const items = out.filter((x) => x.t != null).sort((a, b) => a.t - b.t);
    const counts = Object.fromEntries(TYPES.map((t) => [t.key, items.filter((x) => x.type === t.key).length]));
    const draw = () => {
      $("tlFilt").innerHTML = TYPES.filter((t) => counts[t.key]).map((t) => `<button type="button" class="tl-chipbtn${st.off.has(t.key) ? "" : " on"}" data-k="${t.key}"><i style="color:${t.color}">${t.icon}</i>${esc(t.label)} <b>${fmt(counts[t.key])}</b></button>`).join("");
      let day = null, html = "";
      items.filter((x) => !st.off.has(x.type)).forEach((x) => {
        const d = new Date(x.t), dk = d.toISOString().slice(0, 10);
        if (dk !== day) { day = dk; html += `<div class="cday">${WEEK[d.getUTCDay()]} ${esc(dayWord(x.t))}</div>`; }
        const ty = TYPES.find((t) => t.key === x.type);
        html += `<div class="cev ${x.type}${x.out ? " outside" : ""}"><div class="ct">${esc(clock(x.t))}</div><div class="ci" style="color:${ty.color}">${ty.icon}</div>
          <div class="cb"><div class="ctitle">${x.html ? x.title : esc(x.title)}${x.until ? ` <span class="muted small">until ${esc(when(x.until))}</span>` : ""}${x.out ? ' <span class="badge">outside the data\'s time span</span>' : ""}</div>
          ${x.body ? `<div class="cbody">${x.body}</div>` : ""}${x.chips ? `<div class="chips">${x.chips}</div>` : ""}</div></div>`;
      });
      $("tlChron").innerHTML = html || '<p class="muted">Nothing selected.</p>';
      $("tlFilt").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.k; st.off.has(k) ? st.off.delete(k) : st.off.add(k); draw(); }));
    };
    draw();
  }

  // ------------------------------------------------------------------ 4. every hour
  function hourTable(D) {
    const { s, sim } = D;
    if (!sim.hours || !sim.actions) { $("tlHours").innerHTML = '<p class="muted">No hours.</p>'; return; }
    const t0 = sim.start_t * 1000, mxA = Math.max(1, ...sim.actions);
    // by agent: how many estimated agents had a dated action in each hour, and how many were new
    let act = sim.active_actors, neu = sim.new_actors;
    if (D.AGM && D.lanes.start_t != null) {
      const off = Math.round((D.lanes.start_t - sim.start_t) / 3600);
      act = new Array(sim.hours).fill(0); neu = new Array(sim.hours).fill(0);
      D.lanes.actors.filter((a) => a.kind !== "runs").forEach((a) => {
        let first = true;
        a.bins.forEach((b) => { const i = b[0] + off; if (i < 0 || i >= sim.hours) return; act[i]++; if (first) { neu[i]++; first = false; } });
      });
    }
    let rows = "";
    for (let i = 0; i < sim.hours; i++) {
      const t = t0 + i * HR, h = hourKey(t), by = s.activity_by_hour[h] || {};
      const main = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
      rows += `<tr class="click${sim.actions[i] ? "" : " quiet"}" data-h="${h}"><td>${esc(when(t))}</td><td class="n">${fmt(sim.actions[i])}</td><td>${meter(sim.actions[i] / mxA, main ? intentColor(main[0]) : "#cdd3da", 90)}</td>
        <td class="n">${sim.harmful[i] ? fmt(sim.harmful[i]) : ""}</td><td class="n">${act[i] || ""}</td><td class="n">${neu[i] || ""}</td><td class="n">${sim.messages[i] || ""}</td>
        <td>${main ? ent.intent(main[0]) : ""}</td><td class="n">${sim.harm_remaining[i] != null ? pct(sim.harm_remaining[i]) : ""}</td></tr>`;
    }
    $("tlHours").innerHTML = `<table><thead><tr><th>hour (UTC, estimated)</th><th class="n">actions</th><th></th><th class="n">harmful</th><th class="n">${D.AGM ? `estimated agents active ${estMark()}` : "named actors active"}</th><th class="n">new</th><th class="n">messages</th><th>mostly</th><th class="n">harm still to come</th></tr></thead><tbody>${rows}</tbody></table>`;
    $("tlHours").querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest(".ent")) goEvents({ hour: tr.dataset.h }); }));
  }
})();

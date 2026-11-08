// Timeline: when everything happened, who was active, and who talked to whom over time.
// 1. an overview strip (activity by intent, the data's turning points, warning signs, the reports' phases) that zooms
// 2. swimlanes: one row per actor, hourly cells, and every message drawn from the writer's row to the reader's
// 3. a chronology of every key moment, and 4. every hour as a row
(() => {
  "use strict";
  const HR = 3600e3;
  const RUNS = "(anonymous runs)";
  const dl = typeof deepLink === "function" ? deepLink() : {};   // #tab=timeline&order=messages&rows=messages
  const st = { z: null, sort: dl.order || "first", show: dl.rows || "all", lines: "named", off: new Set() };
  let seq = 0;
  const hourKey = (t) => new Date(t).toISOString().slice(0, 13).replace("T", " ");
  const WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MOMENT = { first: "first action", surge: "surge begins", peak: "busiest hour", stop: "falls below 15% of peak", last: "last action" };
  const named = (a) => a && !String(a).startsWith("run:");
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
        { sub: "Timed actions per hour, coloured by what the code does. Above the bars: the moments the data itself shows, each warning sign when it first fired, and the phases the investigators' reports describe. <b>Drag across the bars to zoom the lanes below</b>; click a bar to list that hour's events; double-click to reset." })}
      ${card("Who was active when, and who talked to whom", `<div id="tlCtl" class="tl-ctl"></div><div id="tlZoom" class="tl-zoom"></div><div class="tl-lanewrap"><div id="tlAxis" class="tl-axis"></div><div id="tlScroll" class="tl-scroll"><div id="tlLanes"></div></div></div><div id="tlLaneKey" class="small muted tl-lanekey"></div>`,
        { sub: "One row per actor. Each cell is one hour: its colour is what the actor mostly did, darker means more actions, and a red underline marks harmful actions. Each line is a message: it starts where the sender wrote to a place and ends where another actor read it. Hover a row to pick out its messages; hover a line to see the record; click a cell to list those events." })}
      ${card("Chronology", `<div id="tlFilt" class="tl-filt"></div><div id="tlChron" class="chrono"></div>`,
        { sub: "Every key moment in time order: turning points in the data, warning signs, the first message between each pair of named actors, and what the incident reports say happened, with how far the tool's own estimate is from the report." })}
      ${card("Every hour", `<div id="tlHours" class="tl-hours"></div>`, { sub: "Click an hour to list its events." })}`;
    let lanes, msgs, sim, ctx;
    try {
      [lanes, msgs, sim, ctx] = await Promise.all([cached("/api/lanes"), cached("/api/messages"), cached("/api/sim"), cached("/api/context").catch(() => ({}))]);
    } catch (e) { $("tlLead").textContent = e.message; return; }
    if (my !== seq || S.tab !== "timeline") return;

    const T0 = toTime(hours[0]), T1 = toTime(hours.at(-1)) + HR;
    if (st.z && (st.z[0] < T0 || st.z[1] > T1)) st.z = null;
    const M = msgs.rows.map((r) => ({ from: r[0], to: r[1], channel: r[2], write_id: r[3], read_id: r[4], wt: r[5] * 1000, rt: r[6] * 1000, lat: r[7], how: r[8], merged: !!r[9] }));
    const namedMsgs = M.filter((m) => named(m.from) && named(m.to));
    const rep = (ctx?.context?.phases || []).map((p, i, all) => {
      const a = toTime(p.start), nxt = all.slice(i + 1).map((q) => toTime(q.start)).find((t) => t != null && t > a);
      return { ...p, a, b: toTime(p.end) ?? nxt ?? a + 6 * HR, hasEnd: !!p.end };
    }).filter((p) => p.a != null);
    const D = { s, hours, lanes, M, namedMsgs, sim, ctx, rep, T0, T1 };

    // the lead: the whole story in one sentence
    const tot = Object.fromEntries(hours.map((h) => [h, Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0)]));
    const actions = Object.values(tot).reduce((a, b) => a + b, 0);
    const peak = hours.reduce((a, h) => (tot[h] > (tot[a] || 0) ? h : a), hours[0]);
    const nNamed = lanes.actors.filter((a) => a.kind !== "runs").length;
    const days = (T1 - T0) / (24 * HR);
    $("tlLead").innerHTML = `${fmt(actions)} timed actions by ${plural(nNamed, "named actor")}${lanes.actors.some((a) => a.kind === "runs") ? " and many anonymous runs" : ""} over ${days >= 2 ? days.toFixed(1) + " days" : hoursWord(days * 24)}, ${esc(when(T0))} to ${esc(when(T1))} UTC. The busiest hour was ${esc(when(toTime(peak)))} with ${fmt(tot[peak])} actions.` +
      (namedMsgs.length ? (() => {
        const first = Math.min(...namedMsgs.map((m) => m.rt)), ex = namedMsgs.filter((m) => !m.merged);
        const firstExact = ex.length ? Math.min(...ex.map((m) => m.rt)) : null;
        return ` ${plural(namedMsgs.length, "message")} passed between named actors, the first read at ${esc(when(firstExact ?? first))}` +
          (firstExact != null && firstExact !== first ? ` (one read earlier, at ${esc(when(first))}, is on a place the redaction may have merged).` : ".");
      })() : "");

    drawOverview(D);
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
      svg += `<g><title>${esc(p.name)} · ${esc(p.time)}${p.why ? " · " + esc(p.why) : ""}</title><text x="${lx}" y="${yy + 9}" font-size="10.5" fill="#3d4a58">${esc(label)}</text>
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
    $("tlKey").innerHTML = `<div class="legend">${intents.map((k) => `<span title="${esc(intentName(k))}"><i style="background:${intentColor(k)}"></i>${esc(human(k))}${isHarm(k) ? ' <em class="tl-harm">harmful</em>' : ""} <b>${fmt(s.intents[k])}</b></span>`).join("")}</div>
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
      <label>Rows <select id="tlShow"><option value="all">every actor</option><option value="messages">actors in messages</option><option value="window">active in the zoomed window</option></select></label>
      <label>Message lines <select id="tlLines"><option value="named">between named actors</option>${hasRuns ? '<option value="all">all, anonymous runs on the bottom row</option>' : ""}<option value="none">none</option></select></label>
      ${D.namedMsgs.length ? '<button type="button" id="tlFit">Zoom to the messages</button>' : ""}`;
    $("tlSort").value = st.sort; $("tlShow").value = st.show; $("tlLines").value = hasRuns || st.lines !== "all" ? st.lines : "named";
    $("tlSort").addEventListener("change", (e) => { st.sort = e.target.value; drawLanes(D); });
    $("tlShow").addEventListener("change", (e) => { st.show = e.target.value; drawLanes(D); });
    $("tlLines").addEventListener("change", (e) => { st.lines = e.target.value; drawLanes(D); });
    if ($("tlFit")) $("tlFit").addEventListener("click", () => {
      const ts = D.namedMsgs.flatMap((m) => [m.wt, m.rt]);
      setZoom(D, [Math.max(D.T0, Math.floor(Math.min(...ts) / HR) * HR - HR), Math.min(D.T1, Math.ceil(Math.max(...ts) / HR) * HR + HR)]);
    });
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
    if (runs && (st.show === "all" || st.lines === "all")) rows.push(runs);

    const H = rows.length * LH + 4;
    const yOf = new Map(rows.map((r, i) => [r.actor, 2 + i * LH + LH / 2]));
    let mxCell = 1;
    lanes.actors.forEach((a) => a.bins.forEach((b) => { let n = 0; for (let k = 1; k < b.length; k++) n += b[k]; if (n > mxCell) mxCell = n; }));
    const nameFont = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    let svg = `<svg class="tl-lanes" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><clipPath id="tlClip"><rect x="${LW}" y="0" width="${W - LW - R}" height="${H}"/></clipPath>
      <marker id="tlArrow" viewBox="0 0 10 10" refX="8" refY="5" markerUnits="userSpaceOnUse" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,1L10,5L0,9z" fill="${ACCENT}"/></marker></defs>`;
    // the data's moments as faint lines behind everything
    (s.phases || []).forEach((p) => { const t = toTime(p.time); if (t != null && t >= z0 && t <= z1) svg += `<line x1="${X(t)}" x2="${X(t)}" y1="0" y2="${H}" stroke="#7d8790" stroke-dasharray="2 4" stroke-opacity=".45"/>`; });
    rows.forEach((r, i) => {
      const y = 2 + i * LH, isRuns = r.kind === "runs";
      const label = fitName(isRuns ? RUNS : short(r.actor), LW - 16 - textWidth(fmt(r.total), "10px -apple-system, system-ui, sans-serif"), nameFont);
      const harm = new Map(r.harm_bins.map(([hi, n]) => [hi, n]));
      svg += `<g class="lane" data-lane="${esc(r.actor)}">${i % 2 ? "" : `<rect x="0" y="${y}" width="${W}" height="${LH}" fill="#f7f9fb"/>`}
        <text class="lname" ${isRuns ? "" : `data-actor="${esc(r.actor)}"`} x="6" y="${y + LH - 3}" font-size="11" fill="${isRuns ? QUIET : "#7a4d0c"}">${esc(label)}</text>
        <text x="${LW - 6}" y="${y + LH - 3}" font-size="10" fill="${QUIET}" text-anchor="end">${fmt(r.total)}</text><g clip-path="url(#tlClip)">`;
      r.bins.forEach((b) => {
        const t = start + b[0] * HR;
        if (t + HR <= z0 || t >= z1) return;
        let n = 0, best = 1;
        for (let k = 1; k < b.length; k++) { n += b[k]; if (b[k] > b[best]) best = k; }
        const it = lanes.intents[best - 1], x = X(t), w = Math.max(1, X(t + HR) - x - 0.5);
        const parts = lanes.intents.map((k, j) => [k, b[j + 1]]).filter((p) => p[1]).sort((p, q) => q[1] - p[1]);
        const op = (0.28 + 0.72 * Math.log1p(n) / Math.log1p(mxCell)).toFixed(2);
        const hn = harm.get(b[0]);
        svg += `<rect class="cell" data-h="${hourKey(t)}" x="${x.toFixed(1)}" y="${y + 1.5}" width="${w.toFixed(2)}" height="${LH - 3}" fill="${intentColor(it)}" fill-opacity="${op}"><title>${esc(isRuns ? RUNS : short(r.actor))} · ${esc(when(t))} · ${plural(n, "action")}\n${parts.slice(0, 4).map(([k, v]) => `${human(k)} ${fmt(v)}`).join(", ")}${hn ? `\n${fmt(hn)} harmful` : ""}\nclick to list these events</title></rect>`;
        if (hn) svg += `<rect x="${x.toFixed(1)}" y="${y + LH - 2.6}" width="${w.toFixed(2)}" height="1.8" fill="${HARM}"/>`;
      });
      svg += `</g></g>`;
    });
    // message lines from the writer's row at write time to the reader's row at read time
    const laneOf = (a) => (named(a) ? a : RUNS);
    const lines = st.lines === "none" ? [] : M.filter((m) => (st.lines === "all" || (named(m.from) && named(m.to))) && yOf.has(laneOf(m.from)) && yOf.has(laneOf(m.to)) && m.rt >= z0 && m.wt <= z1);
    svg += `<g clip-path="url(#tlClip)">`;
    lines.forEach((m) => {
      const x1 = X(m.wt), x2 = X(m.rt), y1 = yOf.get(laneOf(m.from)), y2 = yOf.get(laneOf(m.to));
      const dx = Math.max(8, Math.min(60, Math.abs(x2 - x1) / 2));
      svg += `<path class="msg" data-a="${esc(laneOf(m.from))}" data-b="${esc(laneOf(m.to))}" data-id="${esc(m.read_id)}" d="M${x1.toFixed(1)},${y1} C${(x1 + dx).toFixed(1)},${y1} ${(x2 - dx).toFixed(1)},${y2} ${x2.toFixed(1)},${y2}" marker-end="url(#tlArrow)"><title>${esc(short(m.from))} → ${esc(short(m.to))} via ${esc(m.channel)}\nwritten ${esc(when(m.wt))} in ${esc(m.write_id)}, read ${esc(when(m.rt))} in ${esc(m.read_id)} (${esc(hoursWord(m.lat))} later)\n${esc(m.how || "")}</title></path>
        <circle class="msgend" data-a="${esc(laneOf(m.from))}" data-b="${esc(laneOf(m.to))}" cx="${x1.toFixed(1)}" cy="${y1}" r="1.8" fill="${ACCENT}"/>`;
    });
    svg += `</g></svg>`;
    host.innerHTML = svg;

    // the time axis above the scrolling lanes
    let ax = `<svg width="${W}" height="24" viewBox="0 0 ${W} 24"><text x="6" y="16" font-size="10.5" fill="${QUIET}">${plural(rows.length, "row")}</text>`;
    timeTicks(z0, z1, Math.max(3, Math.floor((W - LW - R) / 80))).forEach((k) => { ax += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="18" y2="24" stroke="${AXIS}"/><text x="${X(k.t)}" y="14" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    $("tlAxis").innerHTML = ax + "</svg>";
    $("tlZoom").innerHTML = st.z ? `Zoomed to <b>${esc(when(z0))}</b> – <b>${esc(when(z1))}</b> (${hoursWord((z1 - z0) / HR)}). <button type="button" class="link" id="tlReset">Show everything</button>` : `Showing the whole span. Drag across the chart above to zoom.`;
    if ($("tlReset")) $("tlReset").addEventListener("click", () => setZoom(D, null));
    $("tlLaneKey").innerHTML = `${plural(lines.length, "message line")} drawn${st.lines === "named" && M.length > lines.length ? ` (${fmt(M.length - D.namedMsgs.length)} more involve anonymous runs: choose “all” to draw them on the bottom row)` : ""}.`;

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
    el.addEventListener("click", (e) => {
      const c = e.target.closest("rect.cell");
      if (!c) return;
      const lane = c.closest(".lane").dataset.lane;
      goEvents({ actor: lane === RUNS ? "" : lane, hour: c.dataset.h });
    });
  }

  // ------------------------------------------------------------------ 3. chronology
  const TYPES = [
    { key: "moment", label: "Turning points in the data", icon: "◆", color: "#5d6d7e" },
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
    (s.phases || []).forEach((p) => out.push({ t: toTime(p.time), type: "moment", title: p.name, body: esc(p.why || "") }));
    (sim.signals || []).forEach((g) => out.push({ t: toTime(g.t), type: g.family in FAMILY ? g.family : "single", title: g.name,
      body: `${esc(g.why || "")}${g.harm_share_after != null ? ` <span class="tl-share">${meter(g.harm_share_after, HARM, 54)} ${pct(g.harm_share_after)} of harm still to come</span>` : ""}`,
      chips: [refChip(g), ...(g.actors || []).filter((a) => a !== g.ref && named(a)).map((a) => ent.actor(a))].filter(Boolean).join(" ") }));
    const seen = new Set();
    namedMsgs.slice().sort((a, b) => a.rt - b.rt).forEach((m) => {
      const k = m.from + "\u0000" + m.to;
      if (seen.has(k)) return; seen.add(k);
      const back = seen.has(m.to + "\u0000" + m.from);
      out.push({ t: m.rt, type: "contact", title: `${esc(short(m.from))} → ${esc(short(m.to))}${back ? ' <span class="badge">now both ways</span>' : ""}`, html: true,
        body: `first message: written ${esc(when(m.wt))}, read ${esc(hoursWord(m.lat))} later · ${esc(m.how || "")}`,
        chips: `${ent.actor(m.from)} ${ent.place(m.channel)} ${ent.actor(m.to)} ${ent.rec(m.write_id)} ${ent.rec(m.read_id)}` });
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
    let rows = "";
    for (let i = 0; i < sim.hours; i++) {
      const t = t0 + i * HR, h = hourKey(t), by = s.activity_by_hour[h] || {};
      const main = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
      rows += `<tr class="click${sim.actions[i] ? "" : " quiet"}" data-h="${h}"><td>${esc(when(t))}</td><td class="n">${fmt(sim.actions[i])}</td><td>${meter(sim.actions[i] / mxA, main ? intentColor(main[0]) : "#cdd3da", 90)}</td>
        <td class="n">${sim.harmful[i] ? fmt(sim.harmful[i]) : ""}</td><td class="n">${sim.active_actors[i] || ""}</td><td class="n">${sim.new_actors[i] || ""}</td><td class="n">${sim.messages[i] || ""}</td>
        <td>${main ? ent.intent(main[0]) : ""}</td><td class="n">${sim.harm_remaining[i] != null ? pct(sim.harm_remaining[i]) : ""}</td></tr>`;
    }
    $("tlHours").innerHTML = `<table><thead><tr><th>hour (UTC)</th><th class="n">actions</th><th></th><th class="n">harmful</th><th class="n">named actors active</th><th class="n">new</th><th class="n">messages</th><th>mostly</th><th class="n">harm still to come</th></tr></thead><tbody>${rows}</tbody></table>`;
    $("tlHours").querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest(".ent")) goEvents({ hour: tr.dataset.h }); }));
  }
})();

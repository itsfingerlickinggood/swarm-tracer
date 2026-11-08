// Spread: how programs and tokens moved between actors.
// A program is the same code (ids, numbers and hashes masked) run by several named actors; the first
// run is its source. Tokens move too: seen inside a record as data, then used as an identity.
"use strict";
(() => {
  const ST = { sel: null, q: "", sort: "reach", matrixAll: false };
  let RUN = 0;
  const H = 3600e3;
  const tOf = (s) => toTime(s);
  const lastAfter = (x) => Math.max(0, ...x.adopters.map((a) => a.hours_after_source ?? 0));
  const firstAfter = (x) => Math.min(...x.adopters.map((a) => a.hours_after_source ?? Infinity));

  // one line that says what a program does, from the pack's own words
  const lowFirst = (s) => String(s || "").replace(/^([A-Z])(?![A-Z])/, (c) => c.toLowerCase());
  function whatLine(w) {
    if (!w) return "No description";
    const tags = (w.tags || []).map((t) => lowFirst(t.what));
    const head = w.intent && w.intent !== "other" ? w.intent_what : (tags.length ? tags.shift().replace(/^./, (c) => c.toUpperCase()) : "No known pattern");
    return head + (tags.length ? "; " + tags.slice(0, 2).join("; ") : "");
  }
  const callLine = (w) => (w?.calls || []).slice(0, 2).join("  ·  ");

  async function view(el, s) {
    const my = ++RUN;
    el.innerHTML = `<h2>How information spread</h2><div id="spLead" class="muted">Loading every program run by several actors…</div>`;
    const [{ rows }, stu, car] = await Promise.all([
      cached("/api/spread"),
      cached("/api/list?name=seen_then_used&limit=1000"),
      cached("/api/list?name=carried_edges&limit=1000"),
    ]);
    if (my !== RUN || !el.isConnected || S.tab !== "spread") return;
    const progs = rows.map((x, i) => ({ ...x, i, reach: x.actors - 1, last: lastAfter(x), first: firstAfter(x), t: tOf(x.source_time) }));
    const actors = new Set();
    progs.forEach((x) => { actors.add(x.source); x.adopters.forEach((a) => actors.add(a.actor)); });
    const adoptions = progs.reduce((a, x) => a + x.adopters.length, 0);
    const firsts = progs.map((x) => x.first).filter(Number.isFinite).sort((a, b) => a - b);
    const allAfter = progs.flatMap((x) => x.adopters.map((a) => a.hours_after_source)).filter((h) => h != null).sort((a, b) => a - b);
    const med = (xs) => (xs.length ? xs[Math.floor(xs.length / 2)] : null);
    const widest = progs.slice().sort((a, b) => b.actors - a.actors || b.copies - a.copies)[0];
    const quick = progs.filter((x) => x.adopters.length >= 2 && x.last <= 1).length;
    if (ST.sel == null || !progs[ST.sel] || ST.selFamily !== progs[ST.sel]?.family) { ST.sel = widest ? widest.i : 0; ST.selFamily = widest?.family; }

    const stuRows = stu.rows || [], carRows = car.rows || [];
    el.innerHTML = `
    <h2>How information spread</h2>
    ${progs.length ? `<p class="lead">${plural(progs.length, "program")} ${progs.length === 1 ? "was" : "were"} run by more than one named actor, reaching ${plural(actors.size, "actor")} in ${plural(adoptions, "adoption")}. The widest, first run by ${ent.actor(widest.source)} (<i>${esc(lowFirst(whatLine(widest.what)))}</i>), reached ${plural(widest.reach, "more actor")} within ${hoursWord(widest.last)}.${quick ? ` ${plural(quick, "program")} reached two or more other actors within an hour of the first run.` : ""} Half of all later runs came within ${hoursWord(med(allAfter))} of the first.</p>`
      : `<p class="lead">No program was run by more than one named actor, so no code is seen moving between actors.</p>`}
    <p class="muted small">A program here is the same code, with ids, numbers and hashes masked, run under several named actors. The data shows the same program appearing later under another actor; it does not show who passed it to whom, so lines below join each later run to the first.</p>
    <div class="kpis">
      ${kpi("programs reused", fmt(progs.length), "run by 2+ named actors")}
      ${kpi("actors involved", fmt(actors.size), "ran a shared program")}
      ${kpi("adoptions", fmt(adoptions), "a program reaching a new actor")}
      ${kpi("median time to adopt", hoursWord(med(allAfter)), `first adopter: median ${hoursWord(med(firsts))}`)}
      ${kpi("tokens seen, then used", fmt(stuRows.length), `${plural(carRows.length, "carried token")}`)}
    </div>
    ${progs.length ? card("Program explorer", `
      <div class="spbar"><input id="spQ" placeholder="Filter by what it does, a host or an actor" value="${esc(ST.q)}">
        <label class="small muted">sort <select id="spSort">${[["reach", "widest reach"], ["early", "earliest first run"], ["fast", "fastest spread"], ["copies", "most copies"]].map(([v, l]) => `<option value="${v}"${ST.sort === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
        <span id="spCount" class="small muted"></span></div>
      <div id="spList" class="splist"></div>
      <div id="spDetail" class="spdetail"></div>`, { sub: "Every program run by several actors. Pick one to see who ran it, in what order, and what the code does." }) : ""}
    ${progs.length ? card("Adoption over time", `<div id="spCurve"></div><div class="grid2 spbusy"><div><h4>Whose programs were reused most</h4><div id="spSources"></div></div><div><h4>Who reused others' programs most</h4><div id="spAdopters"></div></div></div>`,
      { sub: "Bars: programs reaching a new actor in each hour. Teal line: all adoptions so far. Amber line: distinct actors who have run someone else's program." }) : ""}
    ${progs.length ? card("Who ran which program", `<div class="small spmctl"><label><input type="checkbox" id="spAllProgs"${ST.matrixAll ? " checked" : ""}> all ${fmt(progs.length)} programs</label> <span class="muted">(otherwise the ${fmt(progs.filter((x) => x.actors >= 3).length)} run by 3 or more actors)</span></div><div id="spMatrix" class="spmatrix"></div>`,
      { sub: "Rows are actors, columns are programs, ordered so actors that ran the same programs sit together. Dark square: the actor ran it first. Light square: it ran it later. Hover a square for the record." }) : ""}
    ${card("Tokens that moved", `<div id="spTokens"></div>
      <h4 style="margin-top:12px">One identity carrying another's token</h4><div id="spCarried"></div>
      <details class="spdet"><summary>Table of all ${fmt(stuRows.length)} tokens seen, then used</summary><div id="stuList"></div></details>`,
      { sub: "A token that appears inside a record as data (hollow dot) before any record uses it to authenticate (solid dot): one way a credential moves between agents. The line is the lead time." })}`;

    if (progs.length) {
      const list = $("spList");
      const drawList = () => {
        const q = ST.q.toLowerCase().replace(/\bcred (\d+)/g, "[credential $1]");
        let xs = progs.filter((x) => !q || (whatLine(x.what) + " " + callLine(x.what) + " " + x.source + " " + x.adopters.map((a) => a.actor).join(" ") + " " + x.source_record).toLowerCase().includes(q));
        const sorters = { reach: (a, b) => b.actors - a.actors || b.copies - a.copies, early: (a, b) => a.t - b.t, fast: (a, b) => (b.adopters.length >= 2) - (a.adopters.length >= 2) || a.last - b.last, copies: (a, b) => b.copies - a.copies };
        xs = xs.sort(sorters[ST.sort]);
        const maxA = Math.max(...progs.map((x) => x.actors));
        $("spCount").textContent = `${fmt(xs.length)} of ${fmt(progs.length)}`;
        list.innerHTML = xs.length ? xs.map((x) => `<div class="sprow${x.i === ST.sel ? " on" : ""}" data-i="${x.i}">
            <span class="spdot" style="background:${intentColor(x.what?.intent)}"></span>
            <div class="spmain"><div class="spwhat" title="${esc(whatLine(x.what))}">${esc(whatLine(x.what))}</div>
              <div class="spsub">${callLine(x.what) ? `<code>${esc(callLine(x.what))}</code> · ` : ""}first ${esc(short(x.source))} · ${esc(x.source_time || "")} · ${plural(x.copies, "copy", "copies")}</div></div>
            <div class="spreach"><span class="meter" style="width:64px"><i style="width:${(100 * x.actors / maxA).toFixed(1)}%;background:${C.program}"></i></span> <b>${x.actors}</b></div>
            <div class="spafter">${hoursWord(x.last)}</div></div>`).join("") : '<p class="muted small" style="padding:8px">No program matches.</p>';
        list.querySelectorAll(".sprow").forEach((r) => r.addEventListener("click", () => { ST.sel = +r.dataset.i; ST.selFamily = progs[ST.sel].family; list.querySelectorAll(".sprow").forEach((x) => x.classList.toggle("on", x === r)); drawDetail(progs[ST.sel]); }));
      };
      let qt = null;
      $("spQ").addEventListener("input", (e) => { clearTimeout(qt); qt = setTimeout(() => { ST.q = e.target.value.trim(); drawList(); }, 150); });
      $("spSort").addEventListener("change", (e) => { ST.sort = e.target.value; drawList(); });
      drawList();
      const on = list.querySelector(".sprow.on"); if (on) list.scrollTop = Math.max(0, on.offsetTop - list.offsetTop - 40);
      drawDetail(progs[ST.sel]);
      const curve = () => drawCurve($("spCurve"), progs);
      curve(); onResize($("spCurve"), curve);
      drawBusy(progs);
      const mat = () => drawMatrix($("spMatrix"), progs.filter((x) => ST.matrixAll || x.actors >= 3));
      mat(); onResize($("spMatrix"), mat);
      $("spAllProgs").addEventListener("change", (e) => { ST.matrixAll = e.target.checked; mat(); });
    }
    const tok = () => drawTokens($("spTokens"), stuRows);
    tok(); onResize($("spTokens"), tok);
    drawCarried($("spCarried"), carRows);
    listView($("stuList"), "seen_then_used", ["item", "first seen", "record", "kind", "first used", "uses", "lead"],
      (x) => [ent.actor(x.item), esc(x.first_seen), ent.rec(x.first_seen_id), esc(x.first_seen_kind), esc(x.first_used), fmt(x.uses), hoursWord(x.lead_hours)],
      stuRows, stuRows.length);
  }

  // ------------------------------------------------------------------ one program: cascade, code, adopters
  async function drawDetail(x) {
    const host = $("spDetail");
    if (!host || !x) return;
    const w = x.what || {};
    host.innerHTML = `
      <div class="sphead">
        <div><div class="spwhat big">${ent.intent(w.intent)} ${esc(whatLine(w))}</div>
          ${(w.tags || []).length ? `<div class="chips">${w.tags.map((t) => `<span class="chip" title="${esc(t.what)}">${esc(human(t.tag))}</span>`).join("")}</div>` : ""}
          ${(w.calls || []).length ? `<div class="small muted">calls ${w.calls.map((c) => `<code>${esc(c)}</code>`).join(" ")}</div>` : ""}</div>
        <button type="button" class="primary small" id="spAsk">Ask the AI about this program</button>
      </div>
      <div class="comp">${[["actors", x.actors], ["copies", x.copies], ["dated copies", x.dated_copies], ["first adopter after", null, hoursWord(x.first)], ["last adopter after", null, hoursWord(x.last)]].map(([k, v, txt]) => `<div><b>${txt ?? fmt(v)}</b><span>${k}</span></div>`).join("")}</div>
      <div id="spCascade"></div>
      <div class="grid2 spsrc">
        <div><h4>The first run ${ent.rec(x.source_record)}</h4><div id="spSrc" class="muted small">Loading the record…</div></div>
        <div><h4>Who ran it, in order</h4>${table(["#", "actor", "record", "time", "after"], [[0, ent.actor(x.source), ent.rec(x.source_record), esc(x.source_time || "–"), '<span class="muted">first</span>'], ...x.adopters.map((a, k) => [k + 1, ent.actor(a.actor), ent.rec(a.record), esc(a.time || "–"), hoursWord(a.hours_after_source)])])}</div>
      </div>`;
    $("spAsk").addEventListener("click", () => askAbout(x.source_record, `Explain how the program first run in ${x.source_record} by ${x.source} spread to ${x.adopters.length} other actors (${x.adopters.map((a) => a.record).slice(0, 8).join(", ")}): what the code does, who ran it in what order, and what that suggests about how information moved. Cite record ids.`));
    const cas = () => drawCascade($("spCascade"), x);
    cas(); onResize($("spCascade"), cas);
    try {
      const t = await cached("/api/event?id=" + encodeURIComponent(x.source_record));
      const src = $("spSrc");
      if (!src || ST.selFamily !== x.family) return;
      const ex = t.explain || {};
      src.className = "";
      src.innerHTML = `<ul class="spwhatlist">${(ex.what || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
        ${(ex.roles || []).length ? `<div class="roles">${ex.roles.map((r) => `<span class="role ${r.role}" title="${esc(r.detail)}">${esc(r.label)}</span>`).join("")}</div>` : ""}
        <pre class="spcode">${esc(t.text.slice(0, 1600))}${t.text.length > 1600 ? "\n…" : ""}</pre>
        <p class="muted small">Text written by the agents, shown as data (${fmt(t.text_length)} chars).</p>`;
    } catch (e) { const src = $("spSrc"); if (src) src.textContent = e.message; }
  }

  function drawCascade(host, x) {
    if (!host) return;
    const rows = [{ actor: x.source, record: x.source_record, time: x.source_time, h: 0, src: true }, ...x.adopters.map((a) => ({ ...a, h: a.hours_after_source }))];
    const W = Math.max(360, host.clientWidth || 700), RH = 24, top = 26, L = 128, R = 64;
    const Hh = top + rows.length * RH + 26;
    const ts = rows.map((r) => tOf(r.time)).filter((t) => t != null);
    if (!ts.length) { host.innerHTML = '<p class="muted small">No dated runs, so no cascade.</p>'; return; }
    let t0 = Math.min(...ts), t1 = Math.max(...ts);
    if (t1 - t0 < H) { t1 = t0 + H; }
    const pad = (t1 - t0) * 0.04; t0 -= pad; t1 += pad;
    const X = (t) => L + (t - t0) / (t1 - t0) * (W - L - R);
    const Y = (i) => top + i * RH + RH / 2;
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Who ran the program, in order">`;
    timeTicks(t0, t1, Math.max(3, Math.floor((W - L - R) / 95))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${top - 6}" y2="${Hh - 22}" stroke="${GRID}"/><text x="${X(k.t)}" y="${Hh - 8}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    svg += `<text x="${L}" y="12" font-size="10.5" fill="${QUIET}">first run</text><text x="${W - 4}" y="12" font-size="10.5" fill="${QUIET}" text-anchor="end">after</text>`;
    const sx = X(tOf(x.source_time)), sy = Y(0);
    rows.forEach((r, i) => {
      const y = Y(i), t = tOf(r.time);
      if (i % 2 === 0) svg += `<rect x="0" y="${y - RH / 2}" width="${W}" height="${RH}" fill="#f8fafc"/>`;
      svg += `<text x="6" y="${y + 4}" font-size="11.5" fill="${r.src ? INK : "#3d4a58"}" font-weight="${r.src ? 650 : 400}" data-actor="${esc(r.actor)}" class="node">${esc(fitName(short(r.actor), L - 14, "11.5px -apple-system, system-ui, sans-serif"))}</text>`;
      if (t == null) { svg += `<text x="${L}" y="${y + 4}" font-size="10.5" fill="${QUIET}">no time</text>`; return; }
      const xx = X(t);
      if (!r.src) {
        const d = xx - sx > 8 ? `M${sx},${sy + 6} L${sx},${y - 6} Q${sx},${y} ${sx + 6},${y} L${xx},${y}` : `M${sx},${sy + 6} L${xx},${y}`;
        svg += `<path d="${d}" fill="none" stroke="${C.program}" stroke-opacity=".45" stroke-width="1.4"/>`;
        svg += `<text x="${W - 4}" y="${y + 4}" font-size="11" fill="${QUIET}" text-anchor="end">+${esc(hoursWord(r.h))}</text>`;
      }
      svg += `<circle class="node" data-id="${esc(r.record)}" cx="${xx}" cy="${y}" r="${r.src ? 6.5 : 5}" fill="${r.src ? INK : C.program}" stroke="#fff" stroke-width="1.5"/>`;
    });
    host.innerHTML = svg + "</svg>";
  }

  // ------------------------------------------------------------------ adoption over time
  function drawCurve(host, progs) {
    if (!host) return;
    const ev = [];
    progs.forEach((x) => x.adopters.forEach((a) => { const t = tOf(a.time); if (t != null) ev.push({ t, actor: a.actor }); }));
    const starts = progs.map((x) => x.t).filter((t) => t != null);
    if (!ev.length) { host.innerHTML = '<p class="muted small">No dated adoptions.</p>'; return; }
    ev.sort((a, b) => a.t - b.t);
    const W = Math.max(360, host.clientWidth || 700), Hh = 210, x0 = 44, x1 = W - 44, yT = 14, yB = Hh - 28;
    const t0 = Math.floor(Math.min(...starts, ev[0].t) / H) * H, t1 = Math.ceil((ev.at(-1).t + 1) / H) * H;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0);
    const perH = new Map(); ev.forEach((e) => { const k = Math.floor(e.t / H) * H; perH.set(k, (perH.get(k) || 0) + 1); });
    const mxH = Math.max(...perH.values());
    const cum = [], reached = [], seen = new Set();
    ev.forEach((e, i) => { seen.add(e.actor); cum.push([e.t, i + 1]); reached.push([e.t, seen.size]); });
    const total = ev.length, Yc = (v) => yB - v / total * (yB - yT), Yb = (v) => yB - v / mxH * (yB - yT) * 0.45;
    const nAct = seen.size, Ya = (v) => yB - v / nAct * (yB - yT);
    const bw = Math.max(1, (x1 - x0) / ((t1 - t0) / H) - 1);
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Adoptions of shared programs over time">`;
    [0, 0.5, 1].forEach((f) => { svg += `<line x1="${x0}" x2="${x1}" y1="${Yc(total * f)}" y2="${Yc(total * f)}" stroke="${GRID}"/><text x="${x0 - 6}" y="${Yc(total * f) + 4}" text-anchor="end" font-size="10.5" fill="${C.program}">${fmt(Math.round(total * f))}</text><text x="${x1 + 6}" y="${Ya(nAct * f) + 4}" font-size="10.5" fill="${C.actor}">${fmt(Math.round(nAct * f))}</text>`; });
    perH.forEach((v, k) => { svg += `<rect x="${X(k)}" y="${Yb(v)}" width="${bw}" height="${yB - Yb(v)}" fill="${C.program}" opacity=".22"><title>${esc(when(k))}: ${plural(v, "adoption")}</title></rect>`; });
    const step = (pts, Yf) => pts.map(([t, v], i) => `${i ? `L${X(t).toFixed(1)},${Yf(pts[i - 1][1]).toFixed(1)} ` : `M${X(t).toFixed(1)},${yB} `}L${X(t).toFixed(1)},${Yf(v).toFixed(1)}`).join(" ") + ` L${x1},${Yf(pts.at(-1)[1]).toFixed(1)}`;
    svg += `<path d="${step(reached, Ya)}" fill="none" stroke="${C.actor}" stroke-width="1.8"/>`;
    svg += `<path d="${step(cum, Yc)}" fill="none" stroke="${C.program}" stroke-width="2.2"/>`;
    svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    timeTicks(t0, t1, Math.max(3, Math.floor((x1 - x0) / 90))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 4}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${yB + 17}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    // half-way mark: when half of all adoptions had happened
    const half = cum[Math.floor(total / 2)];
    if (half) svg += `<line x1="${X(half[0])}" x2="${X(half[0])}" y1="${yT}" y2="${yB}" stroke="${C.program}" stroke-dasharray="3 3" stroke-opacity=".6"/><text x="${X(half[0]) - 5}" y="${yT + 10}" text-anchor="end" font-size="10.5" fill="${C.program}">half of all adoptions by ${esc(when(half[0]))}</text>`;
    host.innerHTML = svg + `</svg><div class="legend"><span><i style="background:${C.program}"></i>adoptions so far <b>${fmt(total)}</b></span><span><i style="background:${C.actor}"></i>actors who ran another's program <b>${fmt(nAct)}</b></span><span><i style="background:${C.program};opacity:.3"></i>adoptions per hour</span></div>`;
  }

  function drawBusy(progs) {
    const src = new Map(), ad = new Map();
    progs.forEach((x) => { src.set(x.source, (src.get(x.source) || 0) + x.adopters.length); x.adopters.forEach((a) => ad.set(a.actor, (ad.get(a.actor) || 0) + 1)); });
    const top = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    $("spSources").innerHTML = hbars(top(src).map(([a, n]) => ({ label: ent.actor(a), value: n, color: INK, title: `${n} later runs by other actors of programs ${short(a)} ran first` })));
    $("spAdopters").innerHTML = hbars(top(ad).map(([a, n]) => ({ label: ent.actor(a), value: n, color: C.program, title: `${short(a)} ran ${n} programs another actor ran first` })));
  }

  // ------------------------------------------------------------------ actor x program matrix
  function drawMatrix(host, progs) {
    if (!host) return;
    if (!progs.length) { host.innerHTML = '<p class="muted small">No program was run by three or more actors. Tick "all programs" to see the rest.</p>'; return; }
    const cells = new Map();   // actor -> Map(progIndex -> {src, record, time})
    progs.forEach((x, j) => {
      const put = (a, v) => { if (!cells.has(a)) cells.set(a, new Map()); if (!cells.get(a).has(j)) cells.get(a).set(j, v); };
      put(x.source, { src: true, record: x.source_record, time: x.source_time });
      x.adopters.forEach((a) => put(a.actor, { src: false, record: a.record, time: a.time }));
    });
    let rows = [...cells.keys()], cols = progs.map((_, j) => j);
    // barycentre ordering: rows by the mean position of their columns, columns by the mean of their rows
    let rpos = new Map(rows.map((r, i) => [r, i])), cpos = new Map(cols.map((c, i) => [c, i]));
    const colRows = new Map(cols.map((j) => [j, rows.filter((r) => cells.get(r).has(j))]));
    rows.sort((a, b) => cells.get(b).size - cells.get(a).size); rpos = new Map(rows.map((r, i) => [r, i]));
    for (let it = 0; it < 12; it++) {
      const cm = (j) => { const rs = colRows.get(j); return rs.reduce((s, r) => s + rpos.get(r), 0) / rs.length; };
      cols.sort((a, b) => cm(a) - cm(b)); cpos = new Map(cols.map((c, i) => [c, i]));
      const rm = (r) => { const js = [...cells.get(r).keys()]; return js.reduce((s, j) => s + cpos.get(j), 0) / js.length; };
      rows.sort((a, b) => rm(a) - rm(b)); rpos = new Map(rows.map((r, i) => [r, i]));
    }
    const W = Math.max(360, host.clientWidth || 700), L = 108, top = 8;
    const cs = Math.max(6, Math.min(16, Math.floor((W - L - 8) / cols.length))), rh = Math.max(15, cs);
    const Wd = L + cols.length * cs + 8, Hh = top + rows.length * rh + 22;
    let svg = `<svg class="chart" width="${Wd}" height="${Hh}" viewBox="0 0 ${Wd} ${Hh}" role="img" aria-label="Which actor ran which shared program">`;
    rows.forEach((r, i) => {
      const y = top + i * rh;
      if (i % 2 === 0) svg += `<rect x="${L}" y="${y}" width="${cols.length * cs}" height="${rh}" fill="#f6f8fa"/>`;
      svg += `<text class="node" data-actor="${esc(r)}" x="${L - 6}" y="${y + rh / 2 + 3.5}" text-anchor="end" font-size="11" fill="#3d4a58">${esc(fitName(short(r), L - 10, "11px -apple-system, system-ui, sans-serif"))}</text>`;
    });
    cols.forEach((j, ci) => {
      const x = L + ci * cs, p = progs[j];
      rows.forEach((r, ri) => {
        const c = cells.get(r).get(j);
        if (!c) return;
        svg += `<rect class="node" data-id="${esc(c.record)}" x="${x + 1}" y="${top + ri * rh + 2}" width="${cs - 2}" height="${rh - 4}" rx="2" fill="${c.src ? INK : C.program}" fill-opacity="${c.src ? 0.9 : 0.55}"><title>${esc(short(r))} ${c.src ? "ran it first" : "ran it later"} (${esc(c.record)}, ${esc(c.time || "no time")}) · ${esc(whatLine(p.what))}</title></rect>`;
      });
    });
    svg += `<text x="${L}" y="${Hh - 6}" font-size="10.5" fill="${QUIET}">${plural(cols.length, "program")} × ${plural(rows.length, "actor")}</text>`;
    host.innerHTML = svg + "</svg>";
  }

  // ------------------------------------------------------------------ tokens
  function drawTokens(host, rows) {
    if (!host) return;
    if (!rows.length) { host.innerHTML = '<p class="muted small">No token was seen as data before its first use as an identity.</p>'; return; }
    const xs = rows.map((r) => ({ ...r, a: tOf(r.first_seen), b: tOf(r.first_used) })).filter((r) => r.a != null && r.b != null).sort((p, q) => p.b - q.b);
    const W = Math.max(360, host.clientWidth || 700), RH = 17, top = 8, L = 104, R = 120;
    const Hh = top + xs.length * RH + 26;
    const t0 = Math.floor(Math.min(...xs.map((r) => r.a)) / H) * H, t1 = Math.ceil((Math.max(...xs.map((r) => r.b)) + 1) / H) * H;
    const X = (t) => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Tokens seen as data, then used as identities">`;
    timeTicks(t0, t1, Math.max(3, Math.floor((W - L - R) / 95))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${top}" y2="${Hh - 22}" stroke="${GRID}"/><text x="${X(k.t)}" y="${Hh - 8}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    xs.forEach((r, i) => {
      const y = top + i * RH + RH / 2, xa = X(r.a), xb = X(r.b);
      svg += `<text class="node" data-actor="${esc(r.item)}" x="${L - 8}" y="${y + 3.5}" text-anchor="end" font-size="11" fill="#3d4a58">${esc(fitName(short(r.item), L - 12, "11px -apple-system, system-ui, sans-serif"))}</text>`;
      svg += `<line x1="${xa}" x2="${xb}" y1="${y}" y2="${y}" stroke="${C.place}" stroke-opacity=".5" stroke-width="2"/>`;
      svg += `<circle class="node" data-id="${esc(r.first_seen_id)}" cx="${xa}" cy="${y}" r="4" fill="#fff" stroke="${C.place}" stroke-width="1.6"><title>${esc(short(r.item))} first seen as data in ${esc(r.first_seen_id)} (${esc(r.first_seen_kind)}), ${esc(r.first_seen)}</title></circle>`;
      svg += `<circle class="node" data-actor="${esc(r.item)}" cx="${xb}" cy="${y}" r="4.2" fill="${C.place}"><title>${esc(short(r.item))} first used as an identity ${esc(r.first_used)}; ${fmt(r.uses)} uses</title></circle>`;
      svg += `<text x="${W - R + 8}" y="${y + 3.5}" font-size="10.5" fill="${QUIET}">${esc(hoursWord(r.lead_hours))} · ${plural(r.uses, "use")}</text>`;
    });
    host.innerHTML = svg + `</svg><div class="legend"><span><i style="background:#fff;border:1.5px solid ${C.place};border-radius:50%"></i>first seen as data (hover for the record)</span><span><i style="background:${C.place};border-radius:50%"></i>first used as an identity</span></div>`;
  }

  function drawCarried(host, rows) {
    if (!host) return;
    if (!rows.length) { host.innerHTML = '<p class="muted small">No record authenticates as one identity while holding another identity\'s token before that token\'s first use.</p>'; return; }
    host.innerHTML = `<p class="muted small">A record that authenticates as one identity and also holds another identity's token, before that token's own first use.</p>
      <div class="spflows">${rows.map((c) => `<div class="spflow">${ent.actor(c.from)}<span class="sparrow"><span>carries</span></span>${ent.actor(c.to)}<span class="muted small">${plural(c.records, "record")}: ${(c.evidence || []).map(ent.rec).join(" ")}</span></div>`).join("")}</div>`;
  }

  VIEWS.spread = view;
})();

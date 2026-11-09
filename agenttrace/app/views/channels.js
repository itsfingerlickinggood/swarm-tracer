// Channels: every place one actor can leave something for another, and how messages moved through them.
// 1. one tile per kind of place, 2. a map of every place, 3. the busiest places hour by hour,
// 4. how long messages waited and how places were shared, 5. the full table.
(() => {
  "use strict";
  const HR = 3600e3;
  const TYPE_COLORS = ["#6b46c1", "#2f6fb3", "#0f766e", "#b7791f", "#c2410c", "#5d6d7e", "#b8579a", "#2e9d5b"];
  const CAT = [
    { key: "msg", label: "carried a message", color: "#6b46c1" },
    { key: "quiet", label: "written and read, no message between actors", color: "#cfc3ec" },
    { key: "never", label: "written, never read by another actor", color: "#f0a57a" },
    { key: "readonly", label: "only read (no write seen)", color: "#d9dee4" },
  ];
  const st = { rank: "ops", top: 40, noMerged: false };
  let seq = 0;
  const catOf = (p) => (p.messages ? "msg" : p.never ? "never" : !p.writes ? "readonly" : "quiet");
  const hourKey = (t) => new Date(t).toISOString().slice(0, 13).replace("T", " ");
  const median = (xs) => { if (!xs.length) return null; const a = xs.slice().sort((p, q) => p - q); return a[Math.floor(a.length / 2)]; };
  // a small share is never shown as 0%
  const share = (x) => (!x ? "0%" : x < 0.001 ? "<0.1%" : x < 0.01 ? (100 * x).toFixed(1) + "%" : pct(x));
  // cut a label at its end, keeping its start (the kind and the first part of the name)
  const endCut = (str, max, font) => { str = String(str); if (textWidth(str, font) <= max) return str; let lo = 1, hi = str.length; while (lo < hi) { const k = Math.ceil((lo + hi) / 2); if (textWidth(str.slice(0, k) + "…", font) <= max) lo = k; else hi = k - 1; } return str.slice(0, lo) + "…"; };
  // the redaction placeholders that appear in place names, in plain words
  const PLACEHOLDERS = [
    [/\[REDACTED:destination:/, "“destination N”: a redacted repository an upload or commit went to"],
    [/\[REDACTED:repo_locator:/, "“repo_locator N”: a redacted repository named in a read or write URL"],
    [/\[HF REPO \d+\]/, "“HF REPO N”: a redacted Hugging Face repository"],
    [/\[REDACTED:username:/, `“username N”: only the owner was kept, so it is the owner's whole namespace and may ${"merge"} several repositories`],
    [/\[REDACTED:query_value:/, "“URL value N”: a dataset named in a URL parameter rather than in the path"],
  ];

  VIEWS.channels = async function channels(el, s) {
    const my = ++seq;
    el.innerHTML = `<h2>Places and how messages moved through them</h2>
      <p class="small muted ch-what">A ${term("place", "place")} (a channel) is anywhere one actor can leave something for another: a repository, a board folder, a webhook, a command file. Each mention of a place in code is judged a ${term("write", "write or a read")}, and a ${term("message", "message")} is a read after a different actor's write.</p>
      <p class="lead" id="chLead">Loading every place…</p><p class="small muted" id="chNames"></p><p class="small ch-opt" id="chOpt"></p>
      <div id="chTiles" class="grid3"></div>
      ${card("Every place", `<div id="chMapKey" class="legend"></div><div id="chMap" class="ch-map"></div>`,
        { sub: "Each tile is one place, grouped by kind. Its size grows with the reads and writes on it (square root, so small places stay visible). Kinds with very few places sit in a thin strip along the bottom. Its colour says what happened there. Hover a tile for its card; click it to inspect every write and read." })}
      ${card("The busiest places, hour by hour", `<div id="chHeatCtl" class="ch-ctl"></div><div id="chHeat"></div>`,
        { sub: "One row per place, hours in UTC (estimated times). In each hour the top half shows writes and the bottom half reads; darker means more. A dark dot marks an hour in which another actor read a message there. Hover a name for the whole name; click a cell to list those events." })}
      <div class="grid2">
        ${card("How long a message waited", `<div id="chLat"></div>`, { sub: `The ${term("latency", "wait")} from a write to the read of it by a different actor, for every message.` })}
        ${card("How places were shared", `<div id="chScatter"></div>`, { sub: "Every place by how many actors wrote to it and how many read it. Both axes use log(1 + count), so 0 fits on the scale. A bigger circle holds more places; the colours are the same as on the map." })}
      </div>
      ${card("Every place", `<div id="chanList"></div>`, { sub: "Busiest first. Click a row to inspect the place; filter to search all of them." })}`;
    let map, msgs;
    try { [map, msgs] = await Promise.all([cached("/api/places_map"), cached("/api/messages")]); }
    catch (e) { $("chLead").textContent = e.message; return; }
    if (my !== seq || S.tab !== "channels") return;

    // places the redaction may have merged: the places of any message flagged as on a merged place
    const mergedSet = new Set(msgs.rows.filter((r) => r[9]).map((r) => r[2]));
    const optHost = $("chOpt");
    if (mergedSet.size) {
      const nm = msgs.rows.filter((r) => r[9]).length;
      optHost.innerHTML = `<label><input type="checkbox" id="chNoMerged"${st.noMerged ? " checked" : ""}> Leave out places the redaction may have merged</label> <span class="muted">${plural(mergedSet.size, "place")} carrying ${plural(nm, "message")} may each join several real places (${term("merged", "merged place")}); leaving them out keeps only places known exactly.</span>`;
      $("chNoMerged").addEventListener("change", (e) => { st.noMerged = e.target.checked; VIEWS.channels(el, s); });
    } else st.noMerged = false;
    const keepP = (ch) => !(st.noMerged && mergedSet.has(ch));
    const P = map.rows.filter((r) => keepP(r[0])).map((r) => ({ ch: r[0], type: String(r[0]).split(":")[0], writes: r[1], reads: r[2], writers: r[3], readers: r[4], messages: r[5], overwrites: r[6], never: !!r[7], first: r[8] }));
    if (!P.length) {
      $("chLead").textContent = "No places found. The pack describes no place (a repository, folder, page or thread), or no record names one, so messages between actors cannot be traced here.";
      ["chTiles"].forEach((id) => ($(id).innerHTML = ""));
      return;
    }
    const M = msgs.rows.filter((r) => !(st.noMerged && r[9])).map((r) => ({ from: r[0], to: r[1], channel: r[2], write_id: r[3], read_id: r[4], wt: r[5] * 1000, rt: r[6] * 1000, lat: r[7], how: r[8], merged: !!r[9] }));
    const types = [...new Set(P.map((p) => p.type))].sort((a, b) => P.filter((p) => p.type === b).length - P.filter((p) => p.type === a).length);
    const tcolor = Object.fromEntries(types.map((t, i) => [t, TYPE_COLORS[i % TYPE_COLORS.length]]));
    const D = { s, P, M, types, tcolor };

    const nMsg = P.filter((p) => p.messages).length, nNever = P.filter((p) => p.never).length, nRead = P.filter((p) => !p.writes).length;
    const byType = types.map((t) => [t, P.filter((p) => p.type === t).length]);
    const found = PLACEHOLDERS.filter(([rx]) => P.some((p) => rx.test(p.ch)));
    $("chNames").innerHTML = found.length ? `Place names are redaction placeholders: ${found.map(([, t]) => esc(t)).join("; ")}. Merged places are flagged (${term("merged", "what merged means")}).` : "";
    $("chLead").innerHTML = `${plural(P.length, "place")} where one actor could leave something for another: ${byType.map(([t, n]) => `${fmt(n)} ${esc(placeType(t, n))}`).join(", ")}. ` +
      `${fmt(nMsg)} of them carried at least one of the ${plural(M.length, "message")}; ${fmt(nNever)} were written and never read by another actor; ${fmt(nRead)} were only read.` +
      (st.noMerged ? ` <span class="muted">Leaving out ${plural(mergedSet.size, "merged place")} and their messages.</span>` : "");

    tiles(D);
    drawMap(D);
    heatControls(D);
    drawHeat(D);
    drawLatency(D);
    drawScatter(D);
    if (st.noMerged) $("chanList").insertAdjacentHTML("beforebegin", '<p class="small muted">This full list still includes merged places (it is read page by page from the server).</p>');
    listView($("chanList"), "channels", ["place", "writes", "reads", "writers", "readers", "messages", "overwrites", "median wait", "first write"],
      (c) => [ent.place(c.channel), fmt(c.writes), fmt(c.reads), fmt(c.writers), fmt(c.readers), fmt(c.deliveries), fmt(c.overwrites || 0), c.median_latency_h != null ? hoursWord(c.median_latency_h) : "–", esc(c.first_write || "–")],
      s.top_channels.slice(0, 15), s.list_totals?.channels, (c) => inspectPlace(c.channel));
    onResize($("chMap"), () => drawMap(D));
    onResize($("chHeat"), () => drawHeat(D));
  };

  // ------------------------------------------------------------------ a place's life, in the Inspector
  // created (first dated write or read), busiest hour, last read; from the place's own operations
  function lifecycle(p) {
    if (!p || !p.ops) return "";
    const timed = p.ops.filter((o) => o.time);
    if (!timed.length && !(p.hourly || []).length) return "";
    const first = timed[0];
    const hourly = (p.hourly || []).map(([h, c]) => ({ h, w: (c.write || 0) + (c.post || 0), r: (c.read || 0) + (c.post || 0) }));
    const busiest = hourly.slice().sort((a, b) => (b.w + b.r) - (a.w + a.r) || (a.h < b.h ? -1 : 1))[0];
    const complete = p.ops.length >= (p.ops_total || 0);
    const reads = timed.filter((o) => o.op === "read" || o.op === "post");
    const lastReadOp = complete && reads.length ? reads[reads.length - 1] : null;
    const lastReadHour = hourly.filter((x) => x.r).map((x) => x.h).sort().pop();
    const lastAny = hourly.map((x) => x.h).sort().pop();
    const t0 = first ? toTime(first.time) : toTime(hourly[0]?.h), t1 = lastAny ? toTime(lastAny) + HR : null;
    let strip = "";
    if (t0 != null && t1 != null && hourly.length > 1) {
      const W = 300, H = 26, mx = Math.max(1, ...hourly.map((x) => x.w + x.r));
      const X = (t) => 2 + (t - t0) / Math.max(HR, t1 - t0) * (W - 4);
      strip = `<svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" height="${H}" class="ch-life" role="img" aria-label="Writes and reads on this place over its life">${hourly.map((x) => { const t = toTime(x.h); if (t == null) return ""; const x0 = X(t), w = Math.max(1, X(t + HR) - x0), hw = (x.w / mx) * 11, hr = (x.r / mx) * 11; return `<rect x="${x0.toFixed(1)}" y="${13 - hw}" width="${w.toFixed(1)}" height="${hw}" fill="#c2410c" opacity=".75"/><rect x="${x0.toFixed(1)}" y="13" width="${w.toFixed(1)}" height="${hr}" fill="#2f6fb3" opacity=".75"/>`; }).join("")}<line x1="0" x2="${W}" y1="13" y2="13" stroke="#dde2e8"/></svg>`;
    }
    const cell = (lab, main, sub) => `<div><div class="muted small">${lab}</div><b>${main}</b>${sub ? `<div class="small">${sub}</div>` : ""}</div>`;
    return `<div class="dsec ch-lifesec"><h4>Life of this place</h4><div class="ch-lifegrid">
      ${cell(first && first.op !== "read" ? "created (first write)" : "first seen", first ? esc(when(toTime(first.time))) : "time unknown", first ? `${esc(first.op)} by ${ent.actor(first.actor)} in ${ent.rec(first.record)}` : "")}
      ${cell("busiest hour", busiest ? esc(when(toTime(busiest.h))) : "–", busiest ? `${plural(busiest.w, "write")}, ${plural(busiest.r, "read")}` : "")}
      ${cell("last read", lastReadOp ? esc(when(toTime(lastReadOp.time))) : lastReadHour ? `in the hour ${esc(when(toTime(lastReadHour)))}` : "never read", lastReadOp ? `by ${ent.actor(lastReadOp.actor)} in ${ent.rec(lastReadOp.record)}` : "")}
    </div>${strip}${strip ? '<div class="small muted">Writes above the line, reads below, hour by hour from creation to the last operation (dated operations only).</div>' : ""}</div>`;
  }
  window.INSPECTOR_EXTRAS = window.INSPECTOR_EXTRAS || [];
  window.INSPECTOR_EXTRAS.push((kind, key, data) => (kind === "place" ? lifecycle(data) : ""));

  // ------------------------------------------------------------------ 1. one tile per kind of place
  function tiles(D) {
    const { P, M, types, tcolor, s } = D;
    const ct = s.flow.channel_types || {};
    const kindShare = (t) => M.length ? M.filter((m) => String(m.channel).split(":")[0] === t).length / M.length : 0;
    const fine = types.some((t) => { const x = kindShare(t); return x > 0 && x < 0.01; });   // a sibling below 1%: one decimal everywhere
    const shareOf = (x) => fine && x >= 0.01 ? (100 * x).toFixed(1) + "%" : share(x);
    $("chTiles").innerHTML = types.map((t) => {
      const ps = P.filter((p) => p.type === t), ms = M.filter((m) => String(m.channel).split(":")[0] === t);
      const tot = ct[t] || {};
      const writes = tot.writes ?? ps.reduce((a, p) => a + p.writes, 0), reads = tot.reads ?? ps.reduce((a, p) => a + p.reads, 0);
      const med = median(ms.map((m) => m.lat));
      const cats = CAT.map((c) => ({ label: c.label, value: ps.filter((p) => catOf(p) === c.key).length, color: c.color }));
      const top = ps.slice().sort((a, b) => b.messages - a.messages || (b.writes + b.reads) - (a.writes + a.reads))[0];
      return `<section class="card ch-tile" style="--tc:${tcolor[t]}">
        <header><h3>${esc(placeType(t))}</h3><span class="muted small">${esc(t)}</span></header>
        <div class="ch-big"><b>${fmt(ps.length)}</b> ${esc(placeType(t, ps.length))}</div>
        ${stackbar(cats, { legend: false, h: 9 })}
        <dl class="ch-dl">
          <div><dt>writes</dt><dd>${fmt(writes)}</dd></div><div><dt>reads</dt><dd>${fmt(reads)}</dd></div>
          <div><dt>messages</dt><dd>${fmt(ms.length)}<span> ${M.length ? shareOf(ms.length / M.length) : ""}</span></dd></div>
          <div><dt>never read</dt><dd>${fmt(ps.filter((p) => p.never).length)}</dd></div>
          <div><dt>median wait</dt><dd>${med != null ? hoursWord(med) : "–"}</dd></div>
          <div><dt>in messages</dt><dd>${fmt(new Set(ms.flatMap((m) => [m.from, m.to])).size)}<span> actors</span></dd></div>
        </dl>
        ${!ms.length && reads ? `<p class="small ch-why">No message here: ${writes ? "no read came after a write by a different actor" : "no write to these places was seen"}.</p>` : ""}
        ${top ? `<div class="small muted ch-top"><span>Busiest</span>${ent.place(top.ch)}</div>` : ""}
      </section>`;
    }).join("") + `<div class="legend ch-catkey">${CAT.map((c) => `<span><i style="background:${c.color}"></i>${esc(c.label)}</span>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------ 2. map of every place (squarified treemap)
  function squarify(items, x, y, w, h) {
    const total = items.reduce((a, i) => a + i.v, 0);
    if (!total || w <= 0 || h <= 0) return;
    const scale = (w * h) / total;
    let i0 = 0, rx = x, ry = y, rw = w, rh = h;
    const area = (i) => items[i].v * scale;
    while (i0 < items.length) {
      const side = Math.min(rw, rh);
      let sum = 0, mx = 0, mn = Infinity, best = Infinity, i = i0;
      while (i < items.length) {
        const a = area(i), s2 = sum + a, mx2 = Math.max(mx, a), mn2 = Math.min(mn, a);
        const worst = Math.max((side * side * mx2) / (s2 * s2), (s2 * s2) / (side * side * mn2));
        if (i > i0 && worst > best) break;
        sum = s2; mx = mx2; mn = mn2; best = worst; i++;
      }
      const thick = sum / side;
      let off = 0;
      for (let k = i0; k < i; k++) {
        const len = area(k) / thick;
        if (rw >= rh) Object.assign(items[k], { x: rx, y: ry + off, w: thick, h: len });
        else Object.assign(items[k], { x: rx + off, y: ry, w: len, h: thick });
        off += len;
      }
      if (rw >= rh) { rx += thick; rw -= thick; } else { ry += thick; rh -= thick; }
      i0 = i;
    }
  }
  function drawMap(D) {
    const host = $("chMap");
    if (!host) return;
    const { P, types, tcolor } = D;
    const W = Math.max(380, host.clientWidth || 700), H = Math.round(Math.min(520, Math.max(320, W * 0.58)));
    const maxM = Math.max(1, ...P.map((p) => p.messages));
    const msgColor = (m) => { const k = Math.log1p(m) / Math.log1p(maxM); const a = [207, 195, 236], b = [62, 33, 128]; return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * (0.35 + 0.65 * k))).join(",")})`; };
    const fill = (p) => (p.messages ? msgColor(p.messages) : CAT.find((c) => c.key === catOf(p)).color);
    const groups = types.map((t) => {
      const items = P.filter((p) => p.type === t).map((p) => ({ p, v: Math.sqrt(Math.max(1, p.writes + p.reads)) })).sort((a, b) => b.v - a.v);
      return { t, items, v: items.reduce((a, i) => a + i.v, 0) };
    });
    // kinds with a tiny share go in a thin strip along the bottom, so they stay visible without taking the map
    const sumV = groups.reduce((a, g) => a + g.v, 0);
    const minor = groups.filter((g) => g.v < sumV * 0.03 && groups.length > 1), major = groups.filter((g) => !minor.includes(g));
    const stripH = minor.length ? 40 : 0;
    major.sort((a, b) => b.v - a.v);
    squarify(major, 0, 0, W, H - stripH - (stripH ? 3 : 0));
    minor.sort((a, b) => b.v - a.v).forEach((g, i) => { const w = W / minor.length; Object.assign(g, { x: i * w, y: H - stripH, w, h: stripH, strip: true }); });
    groups.sort((a, b) => (a.strip ? 1 : 0) - (b.strip ? 1 : 0));
    let svg = `<svg class="ch-tree" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Map of every place">`;
    groups.forEach((g) => {
      const head = g.strip ? 15 : g.h > 40 && g.w > 60 ? 16 : 0;
      squarify(g.items, g.x + 1, g.y + 1 + head, g.w - 2, g.h - 2 - head);
      svg += `<rect x="${g.x}" y="${g.y}" width="${g.w}" height="${g.h}" fill="#fff"/>`;
      if (head) svg += `<rect x="${g.x + 1}" y="${g.y + 1}" width="${g.w - 2}" height="${head - 1}" fill="${tcolor[g.t]}" fill-opacity=".1"/><text x="${g.x + 6}" y="${g.y + 12}" font-size="11" font-weight="700" fill="${tcolor[g.t]}">${esc(fitName(`${placeType(g.t)} · ${fmt(g.items.length)}`, g.w - 12, "700 11px -apple-system, system-ui, sans-serif"))}</text>`;
      let cells = "";
      g.items.forEach((it) => {
        const p = it.p; if (!(it.w > 0 && it.h > 0)) return;
        const big = it.w > 3 && it.h > 3;
        cells += `<rect data-place="${esc(p.ch)}" x="${it.x.toFixed(1)}" y="${it.y.toFixed(1)}" width="${Math.max(0.6, it.w - (big ? 0.8 : 0)).toFixed(1)}" height="${Math.max(0.6, it.h - (big ? 0.8 : 0)).toFixed(1)}" fill="${fill(p)}"/>`;
        if (it.w > 70 && it.h > 15) cells += `<text x="${(it.x + 4).toFixed(1)}" y="${(it.y + 11.5).toFixed(1)}" font-size="10" fill="${p.messages > maxM / 5 ? "#fff" : "#2b2350"}" pointer-events="none">${esc(fitName(placeLabel(p.ch).split(" · ").slice(1).join(" · ") || p.ch, it.w - 8, "10px -apple-system, system-ui, sans-serif"))}</text>`;
      });
      svg += `<g class="ch-cells">${cells}</g><rect x="${g.x + 0.5}" y="${g.y + 0.5}" width="${g.w - 1}" height="${g.h - 1}" fill="none" stroke="${tcolor[g.t]}" stroke-opacity=".5"/>`;
    });
    host.innerHTML = svg + "</svg>";
    $("chMapKey").innerHTML = `<span><i style="background:linear-gradient(90deg,${msgColor(1)},${msgColor(maxM)})"></i>${esc(CAT[0].label)}: 1 to ${fmt(maxM)} messages</span>` +
      CAT.slice(1).map((c) => `<span><i style="background:${c.color}"></i>${esc(c.label)}</span>`).join("") +
      (minor.length ? `<span class="muted">bottom strip: ${minor.map((g) => `${fmt(g.items.length)} ${esc(placeType(g.t, g.items.length))}`).join(", ")}</span>` : "");
  }

  // ------------------------------------------------------------------ 3. busiest places, hour by hour
  function heatControls(D) {
    $("chHeatCtl").innerHTML = `<label>Rank by <select id="chRank"><option value="ops">most reads and writes</option><option value="messages">most messages</option><option value="writers">most writers</option></select></label>
      <label>Show <select id="chTop"><option>20</option><option>40</option><option>80</option></select> places</label>`;
    $("chRank").value = st.rank; $("chTop").value = String(st.top);
    $("chRank").addEventListener("change", (e) => { st.rank = e.target.value; drawHeat(D); });
    $("chTop").addEventListener("change", (e) => { st.top = +e.target.value; drawHeat(D); });
  }
  async function drawHeat(D) {
    const host = $("chHeat");
    if (!host) return;
    const sp = span();
    if (!sp) { host.innerHTML = '<p class="muted">No times, so no hour-by-hour view.</p>'; return; }
    const key = { ops: (p) => p.writes + p.reads, messages: (p) => p.messages * 1e6 + p.writes + p.reads, writers: (p) => p.writers * 1e6 + p.messages }[st.rank];
    const top = D.P.slice().sort((a, b) => key(b) - key(a)).slice(0, st.top);
    host.innerHTML = `<p class="muted small">Loading ${fmt(top.length)} places…</p>`;
    const my = (drawHeat.seq = (drawHeat.seq || 0) + 1);
    let details;
    try { details = await Promise.all(top.map((p) => cached("/api/place?ch=" + encodeURIComponent(p.ch)))); }
    catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (my !== drawHeat.seq || !host.isConnected) return;
    const [T0, T1] = sp, nH = Math.round((T1 - T0) / HR);
    const W = Math.max(380, host.clientWidth || 700), LW = Math.round(Math.min(210, Math.max(130, W * 0.26))), R = 46, RH = 14;
    const cw = (W - LW - R) / nH;
    const rowsData = details.map((d) => {
      const by = new Map(d.hourly.map(([h, c]) => [h, c]));
      return { d, by };
    });
    const read = new Map();
    D.M.forEach((m) => { const k = m.channel + "\u0000" + hourKey(Math.floor(m.rt / HR) * HR); read.set(k, (read.get(k) || 0) + 1); });
    let mw = 1, mr = 1;
    rowsData.forEach(({ by }) => by.forEach((c) => { mw = Math.max(mw, (c.write || 0) + (c.post || 0)); mr = Math.max(mr, (c.read || 0) + (c.post || 0)); }));
    const shade = (n, mx, rgb) => (n ? `rgba(${rgb},${(0.18 + 0.82 * Math.log1p(n) / Math.log1p(mx)).toFixed(2)})` : null);
    const H = 22 + rowsData.length * RH + 6;
    const kinds = new Set(rowsData.map(({ d }) => String(d.channel).split(":")[0])), mixed = kinds.size > 1;
    let svg = `<svg class="ch-heat" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Busiest places hour by hour">`;
    svg += `<defs><clipPath id="chNameClip"><rect x="0" y="0" width="${LW - 6}" height="${H}"/></clipPath></defs>`;
    timeTicks(T0, T1, Math.max(5, Math.floor((W - LW - R) / 60))).forEach((k) => { const x = LW + (k.t - T0) / HR * cw; svg += `<line x1="${x}" x2="${x}" y1="16" y2="${H - 4}" stroke="${GRID}"/><text x="${x}" y="11" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    svg += `<text x="${W - R + 6}" y="11" font-size="10" fill="${QUIET}"><title>messages through each place</title>msgs</text>`;
    rowsData.forEach(({ d, by }, i) => {
      const y = 20 + i * RH;
      if (i % 2 === 0) svg += `<rect x="0" y="${y}" width="${W}" height="${RH}" fill="#f8f9fb"/>`;
      // the name says which place it is; the kind is only spelled out when the rows mix kinds
      const nm = placeLabel(d.channel).split(" · ").slice(1).join(" · ") || d.channel;
      const lbl = mixed ? `${String(d.channel).split(":")[0].replace(/_/g, " ").replace("hf dataset", "dataset")} · ${nm}` : nm;
      svg += `<text data-place="${esc(d.channel)}" x="4" y="${y + RH - 3.5}" font-size="10.5" fill="#4c2f94" class="ch-rowname" clip-path="url(#chNameClip)"><title>${esc(placeLabel(d.channel))}\n${esc(d.channel)}</title>${esc(endCut(lbl, LW - 12, "10.5px ui-monospace, SFMono-Regular, Menlo, monospace"))}</text>`;
      by.forEach((c, h) => {
        const t = toTime(h); if (t == null) return;
        const x = LW + (t - T0) / HR * cw, w = Math.max(1, cw - 0.4);
        const wn = (c.write || 0) + (c.post || 0), rn = (c.read || 0) + (c.post || 0);
        const fw = shade(wn, mw, "194,65,12"), fr = shade(rn, mr, "47,111,179");
        const tip = `${placeLabel(d.channel)} · ${when(t)}\n${fmt(wn)} write${wn === 1 ? "" : "s"}, ${fmt(rn)} read${rn === 1 ? "" : "s"}`;
        svg += `<g class="ch-hc" data-h="${esc(h)}" data-ch="${esc(d.channel)}"><title>${esc(tip)}${read.get(d.channel + "\u0000" + h) ? `\n${read.get(d.channel + "\u0000" + h)} message(s) read` : ""}</title><rect x="${x.toFixed(1)}" y="${y + 1}" width="${w.toFixed(2)}" height="${(RH - 2) / 2}" fill="${fw || "#eef0f3"}"/><rect x="${x.toFixed(1)}" y="${y + 1 + (RH - 2) / 2}" width="${w.toFixed(2)}" height="${(RH - 2) / 2}" fill="${fr || "#eef0f3"}"/></g>`;
        if (read.get(d.channel + "\u0000" + h)) svg += `<circle cx="${(x + w / 2).toFixed(1)}" cy="${y + RH / 2}" r="${Math.min(2.6, Math.max(1.4, w / 2.2)).toFixed(1)}" fill="${INK}" pointer-events="none"/>`;
      });
      svg += `<text x="${W - R + 6}" y="${y + RH - 3.5}" font-size="10.5" fill="${QUIET}">${fmt(d.messages_total)}</text>`;
    });
    host.innerHTML = svg + `</svg><div class="legend">${mixed ? "" : `<span class="muted">all ${esc(placeType([...kinds][0], 2))}</span>`}<span><i style="background:rgba(194,65,12,.8)"></i>writes (top half)</span><span><i style="background:rgba(47,111,179,.8)"></i>reads (bottom half)</span><span><i style="background:${INK};border-radius:50%"></i>a message was read that hour</span></div>`;
    host.querySelector("svg").addEventListener("click", (e) => {
      const g = e.target.closest(".ch-hc"); if (!g) return;
      const ch = g.dataset.ch;
      goEvents({ q: ch.split(":").slice(1).join(":") || ch, hour: g.dataset.h });
    });
  }

  // ------------------------------------------------------------------ 4a. latency histogram
  function drawLatency(D) {
    const host = $("chLat");
    const lat = D.M.map((m) => m.lat).filter((x) => x != null);
    if (!lat.length) { host.innerHTML = '<p class="muted">No dated messages.</p>'; return; }
    const edges = [0, 5 / 60, 0.25, 1, 3, 6, 12, 24, 48, Infinity];
    const labels = ["<5m", "5–15m", "15–60m", "1–3h", "3–6h", "6–12h", "12–24h", "1–2d", "2d+"];
    const long = ["under 5 minutes", "5 to 15 minutes", "15 to 60 minutes", "1 to 3 hours", "3 to 6 hours", "6 to 12 hours", "12 to 24 hours", "1 to 2 days", "2 days or more"];
    const named = (a) => !String(a).startsWith("run:");
    const bins = labels.map(() => ({ n: 0, run: 0 }));
    D.M.forEach((m) => { if (m.lat == null) return; const i = edges.findIndex((e, k) => m.lat >= e && m.lat < edges[k + 1]); if (i < 0) return; if (named(m.from) && named(m.to)) bins[i].n++; else bins[i].run++; });
    const W = 430, H = 206, L = 44, Rr = 6, T = 10, B = 150;
    const mx = Math.max(1, ...bins.map((b) => b.n + b.run)), bw = (W - L - Rr) / bins.length;
    let svg = `<svg class="chart" width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="Message waiting times">`;
    [0, 0.5, 1].forEach((f) => { const v = Math.round(mx * f), y = B - (v / mx) * (B - T); svg += `<line x1="${L}" x2="${W - Rr}" y1="${y}" y2="${y}" stroke="${GRID}"/><text x="${L - 5}" y="${y + 3.5}" text-anchor="end" font-size="10" fill="${QUIET}">${fmt(v)}</text>`; });
    bins.forEach((b, i) => {
      const x = L + i * bw + 3, w = bw - 6, h1 = (b.n / mx) * (B - T), h2 = (b.run / mx) * (B - T);
      svg += `<g><title>${long[i]}: ${fmt(b.n)} between named actors, ${fmt(b.run)} involving an anonymous run</title><rect x="${x}" y="${B - h1}" width="${w}" height="${h1}" fill="${ACCENT}"/><rect x="${x}" y="${B - h1 - h2}" width="${w}" height="${h2}" fill="#b9cbe0"/></g>`;
      svg += `<text x="${x + w / 2}" y="${B + 13}" text-anchor="middle" font-size="9.5" fill="${QUIET}">${labels[i]}</text>`;
      if (b.n + b.run) svg += `<text x="${x + w / 2}" y="${B - h1 - h2 - 3}" text-anchor="middle" font-size="9.5" fill="${INK}">${fmt(b.n + b.run)}</text>`;
    });
    svg += `<line x1="${L}" x2="${W - Rr}" y1="${B}" y2="${B}" stroke="${AXIS}"/>`;
    svg += `<text x="${(L + W - Rr) / 2}" y="${H - 4}" text-anchor="middle" font-size="10.5" fill="${QUIET}">wait from the write to the read</text><text x="11" y="${(T + B) / 2}" font-size="10.5" fill="${QUIET}" transform="rotate(-90 11 ${(T + B) / 2})" text-anchor="middle">messages</text></svg>`;
    const sorted = lat.slice().sort((a, b) => a - b);
    const longW = D.M.filter((m) => m.lat != null && m.lat >= 48), longMerged = longW.filter((m) => m.merged).length;
    const longRuns = longW.filter((m) => !named(m.from) || !named(m.to)).length;
    const longNote = longW.length ? ` ${fmt(longW.length)} waited 2 days or more` +
      (longRuns ? `; ${fmt(longRuns)} of those involve an anonymous run, which may be a later run reading an old place rather than a reply` : "") +
      (longMerged ? `; ${fmt(longMerged)} are on places the redaction may have ${term("merged", "merged")}, where the write and the read may be on two different places` : "") + "." : "";
    host.innerHTML = svg + `<div class="legend"><span><i style="background:${ACCENT}"></i>between named actors</span><span><i style="background:#b9cbe0"></i>involving an anonymous run</span></div>
      <p class="small">Half of all ${fmt(sorted.length)} messages were read within <b>${hoursWord(sorted[Math.floor(sorted.length / 2)])}</b>; 90% within <b>${hoursWord(sorted[Math.floor(sorted.length * 0.9)])}</b>.${longNote}</p>`;
  }

  // ------------------------------------------------------------------ 4b. writers vs readers, binned
  function drawScatter(D) {
    const host = $("chScatter");
    const bins = new Map();
    D.P.forEach((p) => {
      const k = p.writers + "," + p.readers;
      const b = bins.get(k) || { w: p.writers, r: p.readers, n: 0, msg: 0, msgs: 0, one: p.ch };
      b.n++; if (p.messages) { b.msg++; b.msgs += p.messages; }
      bins.set(k, b);
    });
    const all = [...bins.values()];
    const mxW = Math.max(1, ...all.map((b) => b.w)), mxR = Math.max(1, ...all.map((b) => b.r));
    const W = 360, H = 230, L = 40, Rr = 18, T = 18, B = 190, PAD = 14;   // padding keeps circles off the axis labels
    const X = (v) => L + PAD + Math.log1p(v) / Math.log1p(mxW) * (W - L - Rr - PAD), Y = (v) => B - PAD - Math.log1p(v) / Math.log1p(mxR) * (B - T - PAD);
    const ticks = (mx) => [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].filter((v) => v <= mx);
    let svg = `<svg class="chart" width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="Places by number of writers and readers">`;
    ticks(mxW).forEach((v) => { svg += `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${B}" stroke="${GRID}"/><text x="${X(v)}" y="${B + 12}" text-anchor="middle" font-size="9.5" fill="${QUIET}">${v}</text>`; });
    svg += `<line x1="${L}" x2="${W - Rr}" y1="${B}" y2="${B}" stroke="${AXIS}"/><line x1="${L}" x2="${L}" y1="${T}" y2="${B}" stroke="${AXIS}"/>`;
    ticks(mxR).forEach((v) => { svg += `<line x1="${L}" x2="${W - Rr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${L - 5}" y="${Y(v) + 3.5}" text-anchor="end" font-size="9.5" fill="${QUIET}">${v}</text>`; });
    svg += `<text x="${(L + W) / 2}" y="${H - 4}" text-anchor="middle" font-size="10.5" fill="${QUIET}">writers</text><text x="10" y="${(T + B) / 2}" font-size="10.5" fill="${QUIET}" transform="rotate(-90 10 ${(T + B) / 2})" text-anchor="middle">readers</text>`;
    all.sort((a, b) => b.n - a.n).forEach((b) => {
      const r = Math.min(16, 2.2 + 1.6 * Math.sqrt(b.n));
      const share = b.msg / b.n;   // eslint-disable-line no-shadow
      const cat = b.msg ? CAT[0] : b.r === 0 ? CAT[2] : b.w === 0 ? CAT[3] : CAT[1];
      const fillC = b.msg ? `rgba(107,70,193,${(0.35 + 0.6 * share).toFixed(2)})` : cat.color;
      svg += `<circle ${b.n === 1 ? `data-place="${esc(b.one)}"` : ""} cx="${X(b.w).toFixed(1)}" cy="${Y(b.r).toFixed(1)}" r="${r.toFixed(1)}" fill="${fillC}" stroke="#fff" stroke-width=".8"><title>${plural(b.n, "place")} with ${plural(b.w, "writer")} and ${plural(b.r, "reader")}${b.msg ? `; ${fmt(b.msg)} carried ${plural(b.msgs, "message")}` : "; none carried a message"}</title></circle>`;
    });
    const rOf = (n) => Math.min(16, 2.2 + 1.6 * Math.sqrt(n));
    const sizes = [1, 10, 100, 1000].filter((n) => n <= Math.max(...all.map((b) => b.n)));
    let kx = 2, kparts = "";
    sizes.forEach((n) => { const r = rOf(n); kx += r + 1; kparts += `<circle cx="${kx}" cy="18" r="${r}" fill="none" stroke="#9aa5b1"/><text x="${kx + r + 3}" y="22" font-size="9.5" fill="${QUIET}">${fmt(n)}</text>`; kx += r + 3 + textWidth(fmt(n), "9.5px sans-serif") + 12; });
    const key = `<svg width="${Math.ceil(kx)}" height="36" class="ch-sizekey">${kparts}</svg>`;
    host.innerHTML = svg + `</svg><div class="legend">${CAT.map((c) => `<span><i style="background:${c.color};border-radius:50%"></i>${esc(c.label)}</span>`).join("")}</div><div class="small muted ch-sizekeyrow">circle size: places in it ${key}</div>`;
  }
})();

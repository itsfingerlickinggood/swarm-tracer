// Events: every record, filterable, with the filtered set drawn over time and broken down by kind,
// intent and actor. Click a row to inspect it (what it is, its role in the swarm, its components).
"use strict";
(() => {
  const PAGE = 100;
  function events(el, s) {
    const k = Object.keys(s.kinds), it = Object.keys(s.intents), tg = Object.keys(s.evidence_tags);
    const sel = (id, opts, v, name = (o) => o) => `<select id="${id}"><option value="">any</option>${opts.map((o) => `<option value="${esc(o)}"${o === v ? " selected" : ""}>${esc(name(o))}</option>`).join("")}</select>`;
    el.innerHTML = `
    <div class="evhead"><h2>Every event</h2><span id="evtotal" class="muted"></span></div>
    <div class="filters evfilters">
      <input id="fq" placeholder="Search ids and text" value="${esc(S.ev.q)}">
      <label>kind ${sel("fk", k, S.ev.kind)}</label>
      <label>does ${sel("fi", it, S.ev.intent, human)}</label>
      <label>tag ${sel("ft", tg, S.ev.tag, human)}</label>
      <label class="chk"><input type="checkbox" id="fc"${S.ev.channels ? " checked" : ""}> touches a place</label>
      <span id="evchips"></span>
    </div>
    <div class="evsaved small" id="evsaved"></div>
    <div class="evtop">
      ${card("When", '<div id="evhist"></div>', { sub: `Matching records per hour, stacked by what they do (UTC; most times are ${term("dated", "estimated")}). Hover an hour for its breakdown; click it to keep only that hour, or drag across hours to keep a range.` })}
      ${card("What they are", '<div id="evfacets"></div>', { sub: "Click a part to filter." })}
    </div>
    <div id="evlist" class="muted">Loading…</div>`;
    const reload = () => { S.ev.offset = 0; loadEvents(); };
    let tmr; $("fq").addEventListener("input", (e) => { clearTimeout(tmr); tmr = setTimeout(() => { S.ev.q = e.target.value; reload(); }, 300); });
    $("fk").addEventListener("change", (e) => { S.ev.kind = e.target.value; reload(); });
    $("fi").addEventListener("change", (e) => { S.ev.intent = e.target.value; reload(); });
    $("ft").addEventListener("change", (e) => { S.ev.tag = e.target.value; reload(); });
    $("fc").addEventListener("change", (e) => { S.ev.channels = e.target.checked; reload(); });
    savedBar();
    loadEvents();
  }

  // ---------------------------------------------------------------- saved filters (this browser only)
  const SAVE_KEY = "swarmtracer.events.saved";
  const FKEYS = ["q", "kind", "intent", "tag", "actor", "hour", "channels"];
  const loadSaved = () => { try { const v = JSON.parse(localStorage.getItem(SAVE_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } };
  const storeSaved = (v) => { try { localStorage.setItem(SAVE_KEY, JSON.stringify(v.slice(0, 50))); } catch { /* storage full or off */ } };
  const current = () => Object.fromEntries(FKEYS.map((k) => [k, S.ev[k] || (k === "channels" ? false : "")]));
  const describe = (f) => [f.q && `"${f.q}"`, f.kind && `kind ${f.kind}`, f.intent && human(f.intent), f.tag && human(f.tag), f.actor && short(f.actor), f.hour && `hour ${f.hour}`, f.channels && "touches a place"].filter(Boolean).join(", ") || "no filter";
  function savedBar() {
    const box = $("evsaved"); if (!box) return;
    const list = loadSaved();
    box.innerHTML = `<label>Saved filters <select id="evSavedSel"><option value="">${list.length ? "choose…" : "none yet"}</option>${list.map((x, i) => `<option value="${i}" title="${esc(describe(x.f))}">${esc(x.name)}</option>`).join("")}</select></label>
      <button type="button" class="link" id="evSavedDel"${list.length ? "" : " hidden"}>delete</button>
      <input id="evSaveName" placeholder="name for the current filters" style="width:190px"> <button type="button" id="evSave">Save</button>
      <span class="sep"></span><button type="button" id="evCsv" title="Download every matching record (up to 5,000) as a CSV file">Export CSV</button> <span id="evCsvMsg" class="muted"></span>`;
    $("evSavedSel").addEventListener("change", (e) => {
      const x = list[+e.target.value]; if (!x) return;
      const v = e.target.value;
      goEvents(x.f);
      const vi = $("evSavedSel"); if (vi) vi.value = v;
    });
    $("evSavedDel").addEventListener("click", () => { const i = +$("evSavedSel").value; if ($("evSavedSel").value === "") return; list.splice(i, 1); storeSaved(list); savedBar(); });
    $("evSave").addEventListener("click", () => {
      const name = $("evSaveName").value.trim() || describe(current());
      const rest = list.filter((x) => x.name !== name);
      rest.unshift({ name, f: current(), dataset: S.summary?.name || "" });
      storeSaved(rest); savedBar();
    });
    $("evCsv").addEventListener("click", exportCsv);
  }

  // ---------------------------------------------------------------- the filtered set as CSV
  async function exportCsv() {
    const msg = $("evCsvMsg"), btn = $("evCsv");
    btn.disabled = true; msg.textContent = "Collecting…";
    try {
      const rows = []; let total = 0;
      for (let off = 0; off < 5000; off += 500) {
        const p = new URLSearchParams({ q: S.ev.q || "", hour: S.ev.hour || "", kind: S.ev.kind, intent: S.ev.intent, tag: S.ev.tag, actor: S.ev.actor, channels: S.ev.channels ? "1" : "", offset: off, limit: 500 });
        const r = await api("/api/events?" + p);
        total = r.total; rows.push(...r.rows);
        if (off + 500 >= r.total) break;
      }
      const q = (v) => { const t = String(v ?? ""); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
      const head = ["id", "time_utc", "actor", "actor_kind", "kind", "intent", "tags", "messages_in", "messages_out", "places_touched", "preview"];
      const lines = [head.join(",")].concat(rows.map((x) => [x.id, x.time, x.actor, x.actor_kind, x.kind, x.intent, (x.tags || []).join(" "), x.in, x.out, x.ops, x.preview].map(q).join(",")));
      const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `events-${(S.summary?.name || "trace").replace(/[^\w.-]+/g, "_")}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      msg.textContent = rows.length < total ? `${fmt(rows.length)} of ${fmt(total)} rows exported (the first 5,000).` : `${fmt(rows.length)} rows exported.`;
    } catch (e) { msg.textContent = e.message; }
    finally { btn.disabled = false; }
  }

  // ---------------------------------------------------------------- "first time this actor did X"
  // candidates come from the swimlanes (the first hour each actor did each thing); the exact first
  // record in that hour is then looked up, so a mark is exact, by time
  async function firstMarks(rows) {
    let L;
    try { L = await cached("/api/lanes"); } catch { return; }
    if (!L || !L.start_t || !$("evlist")) return;
    const byActor = new Map(L.actors.map((a) => [a.actor, a]));
    const firstHour = new Map();
    const fh = (a, k) => {
      const key = a.actor + "\u0000" + k;
      if (!firstHour.has(key)) { const b = a.bins.find((x) => x[1 + k] > 0); firstHour.set(key, b ? b[0] : null); }
      return firstHour.get(key);
    };
    const want = new Map();
    rows.forEach((x) => {
      const a = byActor.get(x.actor), k = L.intents.indexOf(x.intent);
      if (!a || k < 0 || !x.time) return;
      const h = Math.floor((toTime(x.time) / 1000 - L.start_t) / 3600);
      if (h === fh(a, k)) want.set(x.actor + "\u0000" + x.intent, { actor: x.actor, intent: x.intent, hour: x.time.slice(0, 13) });
    });
    const firsts = new Set();
    await Promise.all([...want.values()].slice(0, 25).map(async (w) => {
      const r = await api(`/api/events?${new URLSearchParams({ actor: w.actor, intent: w.intent, hour: w.hour, limit: 500 })}`);
      let best = null;
      r.rows.forEach((x) => { if (x.time && (!best || x.time < best.time)) best = x; });
      if (best) firsts.add(best.id);
    }));
    document.querySelectorAll("#evlist .evrow").forEach((row) => {
      const x = rows[+row.dataset.i];
      if (!x || !firsts.has(x.id) || row.querySelector(".evfirst")) return;
      row.querySelector(".c2").insertAdjacentHTML("afterbegin", `<span class="evfirst" title="The first time ${esc(short(x.actor))} did this (${esc(human(x.intent))}), by time">first ${esc(human(x.intent))}</span>`);
    });
  }

  function chips() {
    const box = $("evchips"); if (!box) return;
    const c = [];
    if (S.ev.actor) c.push(["actor", `actor ${ent.actor(S.ev.actor)}`]);
    if (S.ev.hour) {
      const [a, b] = S.ev.hour.split("..");
      c.push(["hour", b ? `${esc(when(toTime(a)))} to ${esc(when(toTime(b) + 3600e3))}` : `hour ${esc(when(toTime(a)))}`]);
    }
    box.innerHTML = c.map(([k, h]) => `<span class="fchip">${h}<button class="link" data-clear="${k}" title="Remove">×</button></span>`).join("");
    box.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => { S.ev[b.dataset.clear] = ""; S.ev.offset = 0; loadEvents(); }));
  }

  async function loadEvents() {
    const host = $("evlist"); if (!host) return;
    chips();
    const p = new URLSearchParams({ q: S.ev.q || "", hour: S.ev.hour || "", kind: S.ev.kind, intent: S.ev.intent, tag: S.ev.tag, actor: S.ev.actor, channels: S.ev.channels ? "1" : "", offset: S.ev.offset, limit: PAGE });
    try {
      const r = await api("/api/events?" + p);
      if (!$("evlist")) return;
      $("evtotal").textContent = `${fmt(r.total)} matching · ${fmt(r.timed)} with a time`;
      hist($("evhist"), r.hist, r.hist_by);
      facets($("evfacets"), r.facets, r.total);
      const rows = r.rows;
      host.className = "";
      host.innerHTML = rows.length ? `<div class="evrows">${rows.map((x, i) => `<div class="evrow" data-i="${i}">
          <div class="c1"><span class="tm" title="${esc(x.time ? x.time + " UTC" : "no time")}">${esc(x.time ? when(toTime(x.time)) : "no time")}</span>${ent.rec(x.id)}<span class="badge">${esc(x.kind)}</span></div>
          <div class="c2">${ent.actor(x.actor)} ${ent.intent(x.intent)} ${x.tags.slice(0, 3).map((t) => `<span class="chip" title="${esc(tagName(t))}">${esc(human(t))}</span>`).join("")}${x.tags.length > 3 ? `<span class="muted small">+${x.tags.length - 3}</span>` : ""}
            <span class="io">${x.in ? `<span class="in" title="messages in: read what another actor wrote">↘ ${x.in}</span>` : ""}${x.out ? `<span class="out" title="messages out: another actor read what this wrote">↗ ${x.out}</span>` : ""}${x.ops ? `<span class="ops" title="places touched">◧ ${x.ops}</span>` : ""}</span></div>
          <div class="c3 mono">${esc(x.preview.slice(0, 160))}</div></div>`).join("")}</div>` : '<p class="muted">No event matches these filters.</p>';
      host.insertAdjacentHTML("beforeend", `<p class="pager"><button id="pv"${r.offset === 0 ? " disabled" : ""}>Previous</button> <button id="nx"${r.offset + PAGE >= r.total ? " disabled" : ""}>Next</button> <span class="muted small">${fmt(r.total ? r.offset + 1 : 0)}–${fmt(Math.min(r.total, r.offset + PAGE))} of ${fmt(r.total)}</span></p>`);
      host.querySelectorAll(".evrow").forEach((row) => row.addEventListener("click", (e) => { if (e.target.closest(".ent")) return; selectEvent(rows[+row.dataset.i].id); host.querySelectorAll(".evrow.on").forEach((x) => x.classList.remove("on")); row.classList.add("on"); }));
      $("pv").onclick = () => { S.ev.offset = Math.max(0, S.ev.offset - PAGE); loadEvents(); };
      $("nx").onclick = () => { S.ev.offset += PAGE; loadEvents(); };
      firstMarks(rows).catch(() => {});
    } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
  }

  // what a slice of the chart is: an intent for actions, a record kind otherwise
  const KIND_SHADES = ["#9aa5b1", "#c3cad2", "#7d8a97", "#dde2e8"];
  const sliceName = (k) => k.startsWith("kind:") ? `${k.slice(5)} (not an action)` : human(k);
  function sliceColor(k, kindOrder) {
    if (!k.startsWith("kind:")) return intentColor(k);
    return KIND_SHADES[Math.max(0, kindOrder.indexOf(k)) % KIND_SHADES.length];
  }
  const HOUR = 3600e3;
  const hourKey = (t) => new Date(t).toISOString().slice(0, 13).replace("T", " ");
  function hist(host, h, byHour) {
    if (!host) return;
    const sp = span();
    if (!h.length || !sp) { host.innerHTML = '<p class="muted small">None of the matching records has a time, so they cannot be placed on this chart.</p>'; return; }
    const by = new Map((byHour || []).map(([k, c]) => [k, c]));
    const totals = {};
    by.forEach((c) => Object.entries(c).forEach(([k, v]) => { totals[k] = (totals[k] || 0) + v; }));
    const keys = Object.keys(totals).sort((a, b) => (a.startsWith("kind:") - b.startsWith("kind:")) || (a === "other") - (b === "other") || totals[b] - totals[a]);
    const kindOrder = keys.filter((k) => k.startsWith("kind:"));
    const W = Math.max(300, host.clientWidth || 520), H = 210, x0 = 44, x1 = W - 8, yT = 28, yB = H - 34;
    const [t0, t1] = sp;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0);
    const mx = Math.max(...h.map((x) => x[1]));
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000].find((s) => mx / s <= 4) || Math.ceil(mx / 4);
    const top = Math.ceil(mx / step) * step, Y = (v) => yB - v / top * (yB - yT);
    const bw = Math.max(1, (x1 - x0) / ((t1 - t0) / HOUR) - 0.6);
    const sel = S.ev.hour || "";
    const [selA, selB] = sel.includes("..") ? sel.split("..") : [sel, sel];
    const peak = h.reduce((a, x) => (x[1] > a[1] ? x : a), h[0]);
    let svg = `<svg class="chart evh" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Matching records per hour">`;
    for (let v = 0; v <= top; v += step) svg += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${x0 - 6}" y="${Y(v) + 3.5}" text-anchor="end" font-size="10" fill="${QUIET}">${fmt(v)}</text>`;
    svg += `<text x="10" y="${(yT + yB) / 2}" font-size="10" fill="${QUIET}" transform="rotate(-90 10 ${(yT + yB) / 2})" text-anchor="middle">records per hour</text>`;
    // the incident's own turning points
    let lastEnd = -1e9, row = 0;
    (S.summary?.phases || []).filter((p) => ["surge", "peak", "stop"].includes(p.key)).forEach((p) => {
      const x = X(toTime(p.time)), label = { surge: "surge begins", peak: "busiest hour", stop: "falls below 15%" }[p.key];
      row = x < lastEnd + 4 ? row + 1 : 0;           // a label that would touch the last one goes on the next line
      lastEnd = x + 3 + textWidth(label, "9.5px -apple-system, system-ui, sans-serif");
      svg += `<line x1="${x}" x2="${x}" y1="${yT - 4 + row * 11}" y2="${yB}" stroke="${INK}" stroke-opacity=".35" stroke-dasharray="3 3"/><text x="${x + 3}" y="${yT - 6 + row * 11}" font-size="9.5" fill="${QUIET}">${esc({ surge: "surge begins", peak: "busiest hour", stop: "falls below 15%" }[p.key])}<title>${esc(p.name)} ${esc(p.time)}${p.why ? ": " + esc(p.why) : ""}</title></text>`;
    });
    h.forEach(([k, v]) => {
      const t = toTime(k), x = X(t), on = sel && k >= selA && k <= selB;
      const c = by.get(k) || { all: v };
      let y = yB;
      keys.filter((key) => c[key]).forEach((key) => {
        const hh = c[key] / top * (yB - yT); y -= hh;
        svg += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(2)}" height="${Math.max(0.5, hh).toFixed(2)}" fill="${sliceColor(key, kindOrder)}" opacity="${sel && !on ? 0.28 : 1}" pointer-events="none"/>`;
      });
      if (on) svg += `<rect x="${(x - 0.5).toFixed(1)}" y="${yT}" width="${(bw + 1).toFixed(2)}" height="${yB - yT}" fill="${ACCENT}" fill-opacity=".07" pointer-events="none"/>`;
      const parts = keys.filter((key) => c[key]).map((key) => `${sliceName(key)}: ${fmt(c[key])}`).join("\n");
      svg += `<rect class="hhit" data-h="${esc(k)}" x="${x.toFixed(1)}" y="${yT}" width="${Math.max(bw, 2).toFixed(2)}" height="${yB - yT}" fill="transparent"><title>${esc(when(t))}–${esc(clock(t + HOUR))} UTC: ${fmt(v)} records\n${esc(parts)}\nClick to keep only this hour; drag to keep a range.</title></rect>`;
    });
    svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    timeTicks(t0, t1, Math.max(3, Math.floor((x1 - x0) / 80))).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 4}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${yB + 16}" text-anchor="middle" font-size="10" fill="${QUIET}">${esc(k.label)}</text>`; });
    svg += `<rect class="evbrush" x="0" y="${yT}" width="0" height="${yB - yT}" fill="${ACCENT}" fill-opacity=".14" stroke="${ACCENT}" stroke-opacity=".5" visibility="hidden" pointer-events="none"/>`;
    const shown = keys.slice(0, 14);
    const rest = keys.slice(14).reduce((a, k) => a + totals[k], 0);
    host.innerHTML = svg + "</svg>" +
      `<div class="legend evleg">${shown.map((k) => `<span${k.startsWith("kind:") ? "" : ` class="lk" data-li="${esc(k)}" title="Keep only: ${esc(intentName(k))}"`}><i style="background:${sliceColor(k, kindOrder)}"></i>${esc(sliceName(k))} <b>${fmt(totals[k])}</b></span>`).join("")}${rest ? `<span class="muted">+ ${fmt(rest)} more</span>` : ""}</div>` +
      `<p class="small muted evhnote">Counts in the key are the matching records that have a time. Peak: ${esc(when(toTime(peak[0])))} UTC, ${fmt(peak[1])} records.${sel ? ` Showing ${sel.includes("..") ? `${esc(when(toTime(selA)))} to ${esc(when(toTime(selB) + HOUR))}` : `the hour from ${esc(when(toTime(selA)))}`}. <button type="button" class="link" id="evhclear">show every hour</button>` : ""}</p>`;
    host.querySelectorAll("[data-li]").forEach((el) => el.addEventListener("click", () => { S.ev.intent = el.dataset.li; $("fi").value = el.dataset.li; S.ev.offset = 0; loadEvents(); }));
    if ($("evhclear")) $("evhclear").addEventListener("click", () => { S.ev.hour = ""; S.ev.offset = 0; loadEvents(); });
    // click an hour to keep it; drag across hours to keep a range
    const el = host.querySelector("svg"), brush = el.querySelector(".evbrush");
    const toX = (ev) => { const r = el.getBoundingClientRect(); return (ev.clientX - r.left) * W / r.width; };
    const tAt = (x) => t0 + (Math.max(x0, Math.min(x1, x)) - x0) / (x1 - x0) * (t1 - t0);
    let start = null;
    // pointer events with capture: the release is seen even if the pointer leaves the chart
    el.addEventListener("pointerdown", (ev) => { start = toX(ev); ev.preventDefault(); try { el.setPointerCapture(ev.pointerId); } catch (e) { /* not capturable */ } });
    el.addEventListener("pointerup", (ev) => finish(ev));
    el.addEventListener("pointercancel", () => { start = null; brush.setAttribute("visibility", "hidden"); });
    el.addEventListener("pointermove", (ev) => {
      if (start == null) return;
      const a = Math.min(start, toX(ev)), b = Math.max(start, toX(ev));
      brush.setAttribute("x", a); brush.setAttribute("width", b - a); brush.setAttribute("visibility", b - a > 4 ? "visible" : "hidden");
    });
    function finish(ev) {
      if (start == null) return;
      const end = toX(ev), a = Math.min(start, end), b = Math.max(start, end);
      start = null; brush.setAttribute("visibility", "hidden");
      if (b - a > 4) {
        const ha = hourKey(Math.floor(tAt(a) / HOUR) * HOUR), hb = hourKey(Math.floor(tAt(b) / HOUR) * HOUR);
        S.ev.hour = ha === hb ? ha : `${ha}..${hb}`;
      } else {
        const hk = hourKey(Math.floor(tAt(a) / HOUR) * HOUR);
        S.ev.hour = S.ev.hour === hk ? "" : hk;
      }
      S.ev.offset = 0; loadEvents();
    }
  }

  function facets(host, f, total) {
    if (!host) return;
    const kc = ["#2f6fb3", "#6aa5dc", "#bcd3ec", "#9aa5b1"];
    const kinds = Object.entries(f.kind).map(([k, v], i) => ({ label: k, value: v, color: kc[i % kc.length] }));
    const withIntent = Object.values(f.intent).reduce((a, b) => a + b, 0);
    host.innerHTML = `<div class="small muted">${term("record", "kind of record")} <span class="faint">(click one to keep only that kind)</span></div>${stackbar(kinds, { h: 10 })}
      <div class="chips">${kinds.map((k) => `<button type="button" class="link small" data-fk="${esc(k.label)}">${esc(k.label)}${S.ev.kind === k.label ? " ✓" : ""}</button>`).join("")}</div>
      ${Object.keys(f.intent).length ? `<div class="small muted" style="margin-top:8px">what the code does (${term("intent")}; only ${term("action", "actions")} have one: ${fmt(withIntent)} of the ${fmt(total)})</div>${hbars(Object.entries(f.intent).map(([k, v]) => ({ label: `${esc(human(k))}${isHarm(k) ? ' <span class="harmtag">harm</span>' : ""}`, value: v, color: intentColor(k), attrs: `data-click data-fi="${esc(k)}"` })), { total: withIntent })}` : ""}
      <div class="small muted" style="margin-top:8px">busiest ${term("actor", "actors")} <span class="faint">("run R…" is an ${term("run", "anonymous run")}: a thread with no token or name, credited to its first record)</span></div><div class="chips">${f.actor.slice(0, 8).map(([a, n]) => `<span class="fa">${ent.actor(a, ` <span class="muted">${fmt(n)}</span>`)}<button type="button" class="link small" data-fa="${esc(a)}" title="Keep only this actor's events">filter</button></span>`).join("")}</div>`;
    host.querySelectorAll("[data-fk]").forEach((b) => b.addEventListener("click", () => { S.ev.kind = S.ev.kind === b.dataset.fk ? "" : b.dataset.fk; $("fk").value = S.ev.kind; S.ev.offset = 0; loadEvents(); }));
    host.querySelectorAll("[data-fi]").forEach((b) => b.addEventListener("click", () => { S.ev.intent = b.dataset.fi; $("fi").value = b.dataset.fi; S.ev.offset = 0; loadEvents(); }));
    host.querySelectorAll("[data-fa]").forEach((b) => b.addEventListener("click", () => { S.ev.actor = b.dataset.fa; S.ev.offset = 0; loadEvents(); }));
  }

  VIEWS.events = events;
})();

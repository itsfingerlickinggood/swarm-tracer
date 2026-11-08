// Swarm Tracer app. Talks to the local agenttrace server (python3 -m agenttrace serve).
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString());
const pct = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
const short = (a) => String(a ?? "").replace(/\[CREDENTIAL (\d+)\]/g, "cred $1").replace(/^run:/, "run ");
const PALETTE = ["#2f6fb3", "#e3a43b", "#c0392b", "#16a085", "#8e44ad", "#d35400", "#7fb3e6", "#27ae60", "#9aa5b1", "#5d6d7e", "#f1c40f", "#cfd6dd"];

const S = { summary: null, tab: "overview", selected: null, chat: [], ev: { q: "", kind: "", intent: "", tag: "", actor: "", channels: false, offset: 0 } };

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data;
  try { data = await r.json(); } catch { throw new Error(`HTTP ${r.status}`); }
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// ------------------------------------------------------------------ start
async function init() {
  const p = await api("/api/packs");
  $("pack").innerHTML = p.packs.map((x) => `<option value="${esc(x.file)}" title="${esc(x.description)}"${x.file === "generic.json" ? " selected" : ""}>${esc(x.name)}</option>`).join("");
  const saved = JSON.parse(sessionStorage.getItem("st-ai") || "{}");
  $("baseUrl").value = saved.baseUrl || p.ai_defaults.baseUrl;
  $("model").value = saved.model || p.ai_defaults.model;
  if (saved.apiKey) { $("apiKey").value = saved.apiKey; $("remember").checked = true; }
  status("Loading the analysis…");
  const st = await api("/api/state");
  status("");
  if (st.loaded) setSummary(st.summary);
  else if (st.busy) status("An analysis is running on the server…");
}

function status(t, bad) { $("status").textContent = t || ""; $("status").style.color = bad ? "#ff9b8f" : "#ffd88a"; }

$("upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const files = [...$("folder").files, ...$("file").files].filter((f) => /\.(csv|tsv|jsonl|json|txt)$/i.test(f.name));
  if (!files.length) { status("Choose a file or a folder first.", true); return; }
  const map = {};
  document.querySelectorAll(".mapgrid input").forEach((i) => { if (i.value.trim()) map[i.dataset.role] = i.value.trim(); });
  $("analyze").disabled = true;
  const t0 = performance.now();
  try {
    let r;
    if (files.length === 1) {
      const f = files[0];
      status(`Uploading and analyzing ${f.name} (${(f.size / 1e6).toFixed(1)} MB). Large files take a minute…`);
      r = await api("/api/upload?" + new URLSearchParams({ filename: f.name, pack: $("pack").value, map: JSON.stringify(map) }), { method: "POST", body: f });
    } else {
      // a dataset in several linked files: stage each, then analyze them together
      const batch = Math.random().toString(36).slice(2, 12);
      for (const [i, f] of files.entries()) {
        status(`Uploading ${i + 1} of ${files.length}: ${f.name} (${(f.size / 1e6).toFixed(1)} MB)…`);
        await api("/api/stage?" + new URLSearchParams({ batch, filename: f.name }), { method: "POST", body: f });
      }
      status(`Analyzing ${files.length} files together…`);
      const folder = files[0].webkitRelativePath ? files[0].webkitRelativePath.split("/")[0] : `${files.length} files`;
      r = await api("/api/analyze?" + new URLSearchParams({ batch, pack: $("pack").value, map: JSON.stringify(map), name: folder }), { method: "POST" });
    }
    setSummary(r.summary);
    status(`Analyzed in ${((performance.now() - t0) / 1000).toFixed(0)} s.`);
  } catch (e) { status(e.message, true); }
  finally { $("analyze").disabled = false; }
});

function setSummary(s) {
  S.summary = s;
  $("dsname").textContent = `${s.name} · ${fmt(s.records)} records · pack: ${s.pack}`;
  S.ev = { q: "", kind: "", intent: "", tag: "", actor: "", hour: "", channels: false, offset: 0 };
  render();
}

// ------------------------------------------------------------------ tabs
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  S.tab = b.dataset.tab;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  render();
});

function goEvents(filters) {
  Object.assign(S.ev, { q: "", kind: "", intent: "", tag: "", actor: "", hour: "", channels: false }, filters, { offset: 0 });
  S.tab = "events";
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === "events"));
  render();
}

function render() {
  const el = $("left");
  if (!S.summary) return;
  const f = { overview, network, timeline, channels, spread, early, events, gaps }[S.tab];
  el.innerHTML = "";
  f(el, S.summary);
  el.scrollTop = 0;
}

// ------------------------------------------------------------------ helpers
const kpi = (label, v) => `<div class="kpi"><b>${v}</b><span>${esc(label)}</span></div>`;
function bars(entries, total) {
  const max = Math.max(1, ...entries.map((e) => e[1]));
  return entries.map(([k, v]) => `<div class="bar"><div class="l" title="${esc(k)}">${esc(k)}</div><div class="t"><i style="width:${(100 * v / max).toFixed(2)}%"></i></div><div class="v">${fmt(v)}${total ? ` · ${(100 * v / total).toFixed(1)}%` : ""}</div></div>`).join("");
}
function table(headers, rows, onclick) {
  if (!rows.length) return '<p class="muted">None found.</p>';
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r, i) => `<tr${onclick ? ` class="click" data-i="${i}"` : ""}>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function bindRows(el, onclick) { el.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => onclick(+tr.dataset.i))); }
const idlink = (id) => (id ? `<span class="idlink" data-id="${esc(id)}">${esc(id)}</span>` : "–");
document.addEventListener("click", (e) => {
  const a = e.target.closest(".idlink,[data-ev]");
  if (a) selectEvent(a.dataset.id || a.dataset.ev);
});
const toTime = (s) => (s ? Date.parse(s.replace(" ", "T") + ":00Z") : null);

// ------------------------------------------------------------------ overview
function overview(el, s) {
  const f = s.flow;
  const fnd = f.first_named_delivery;
  el.innerHTML = `
  <div class="kpis">
    ${kpi("records", fmt(s.records))}${kpi("with a time", pct(s.timed / s.records))}${kpi("identities", fmt(s.identities_total))}
    ${kpi("channels", fmt(f.channels))}${kpi("dated messages", fmt(f.deliveries))}${kpi("messages between named actors", fmt(f.deliveries_between_named_actors))}
  </div>
  <div class="note"><b>Answer in brief.</b> ${fnd ? `The first message between two named actors: ${esc(short(fnd.from))} wrote <code>${esc(fnd.channel)}</code> (${idlink(fnd.write_id)}, ${esc(fnd.write_time)}); ${esc(short(fnd.to))} read it (${idlink(fnd.read_id)}, ${esc(fnd.read_time)}). ${f.harm_share_after_first_named_delivery != null ? `At that point ${pct(f.harm_share_after_first_named_delivery)} of the timed harmful activity was still to come.` : ""}` : "No message between two named actors was found."}
  ${f.named_actor_pairs} named sender-receiver pairs exchanged ${fmt(f.deliveries_between_named_actors)} messages; the median message was read ${f.latency_hours.median ?? "–"} h after it was written.</div>
  ${f.deliveries_by_how ? `<p class="muted small">What each message rests on: ${Object.entries(f.deliveries_by_how).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(k)} ${fmt(v)}`).join(" · ")}. Each write counts once per reader${f.repeat_reads ? `; ${fmt(f.repeat_reads)} later reads of a write the reader already had are not counted again` : ""}.${f.overwrites ? ` Also not counted: ${fmt(f.overwrites)} edits that replaced another actor's edit without keeping any line it added, so they show no sign the editor saw it.` : ""}</p>` : ""}
  <h2>How the files were read</h2>
  ${table(["file", "rows", "events", "fields found"], (s.read_report?.files || []).map((f) => [esc(f.file), fmt(f.rows), fmt(f.events),
    Object.entries(f.fields).map(([k, v]) => `${esc(k)}: <code>${esc(v.join(" → "))}</code>`).join("<br>") + (f.text_from_fields ? `<br><span class="muted small">${fmt(f.text_from_fields)} rows had no text field; their fields are used as text</span>` : "")]))}
  ${(s.read_report?.skipped_files || []).length ? `<p class="muted small">Not loaded as events (reference tables, no time or parent): ${s.read_report.skipped_files.map((f) => esc(f.file)).join(", ")}.</p>` : ""}
  ${s.read_report?.dropped_pointer_records ? `<p class="muted small">${fmt(s.read_report.dropped_pointer_records)} records only pointed at another loaded record and were dropped as duplicates.</p>` : ""}
  <h2>What the results rest on</h2>
  <p>Time: ${fmt(s.timed)} of ${fmt(s.records)} records have a time (${Object.entries(s.time_test.source || {}).map(([k, v]) => `${esc(k.replace(/_/g, " "))} ${fmt(v)}`).join(", ") || "none"}). ${s.time_test.span ? `Span ${esc(s.time_test.span[0])} to ${esc(s.time_test.span[1])} UTC.` : ""}</p>
  ${table(["kind", "first", "last", "records", "timestamps", "rank corr.", "timed", "median err (h)"],
    (s.time_test.blocks || []).map((b) => [esc(b.kind), idlink(b.first_id), idlink(b.last_id), fmt(b.records), fmt(b.timestamp_points), esc(b.spearman), b.timed ? "yes" : `no${b.rejected ? " (" + esc(b.rejected) + ")" : ""}`, esc(b.fit_error_hours_median ?? "")]))}
  <p>Identity: ${s.identity_test.tokens_used_5_plus ? `${s.identity_test.with_one_role_90pct} of ${s.identity_test.tokens_used_5_plus} identity tokens used 5+ times keep one role in at least 90% of uses.` : "no identity tokens repeat enough to test."}</p>
  <h2>Identities by activity</h2>
  ${table(["identity", "uses", "first", "last", "mostly"], s.identities.slice(0, 15).map((i) => [`<code>${esc(short(i.identity))}</code>`, fmt(i.uses), esc(i.first), esc(i.last), esc(Object.keys(i.intents).join(", "))]), true)}
  <h2>What the records do</h2>
  ${bars(Object.entries(s.intents), Object.values(s.intents).reduce((a, b) => a + b, 0))}
  <h2>Evidence tags</h2>
  ${bars(Object.entries(s.evidence_tags).slice(0, 15), s.records)}
  <p class="muted small">Context tags (not evidence): ${Object.keys(s.context_tags).map(esc).join(", ") || "none"}.</p>`;
  bindRows(el, (i) => goEvents({ actor: s.identities[i].identity }));
}

// ------------------------------------------------------------------ network (layered layout)
function network(el, s) {
  const pairs = s.flow.top_pairs;
  const sizes = [...new Set([15, 30, 60].map((n) => Math.min(n, pairs.length)))];
  const chosen = Math.min(30, pairs.length);
  el.innerHTML = `<h2>Who talked to whom</h2>
  <p class="muted small">Named actors only. An arrow runs from the actor who wrote to a place to a different actor who later read it; thicker means more messages. Actors that only send are on the left, actors that only receive are on the right, and actors that do both are in the middle. Each shaded band is one group of connected actors. The number in a box is that actor's messages in the pairs shown. Hover a box to pick out its messages; click it to list its events.</p>
  <p class="small">Show the <select id="netN">${sizes.map((n) => `<option value="${n}"${n === chosen ? " selected" : ""}>${n}</option>`).join("")}</select> busiest sender-receiver pairs (of ${fmt(s.flow.named_actor_pairs)}).</p>
  <div id="net"></div>
  <h3>Messages between named actors</h3>
  ${table(["sender", "receiver", "messages", "channels", "first"], pairs.map((p) => [`<code>${esc(short(p.from))}</code>`, `<code>${esc(short(p.to))}</code>`, fmt(p.deliveries), fmt(p.channels), esc(p.first)]), true)}
  <h3>Other links</h3>
  <p class="muted small">One identity carrying another's token before its use, two identities on one place, and replies.</p>
  ${table(["type", "a", "b", "detail"], [
    ...s.carried_edges.slice(0, 10).map((e) => ["carried token", `<code>${esc(short(e.from))}</code>`, `<code>${esc(short(e.to))}</code>`, (e.evidence || []).map(idlink).join(", ")]),
    ...s.shared_places.filter((p) => !p.same_record).slice(0, 10).map((p) => ["shared place", `<code>${esc(short(p.identities[0]))}</code>`, `<code>${esc(short(p.identities[1]))}</code>`, `<code>${esc(p.place)}</code> ${esc(p.first)} / ${esc(p.second)}: ${idlink(p.first_id)}, ${idlink(p.second_id)}`]),
    ...s.reply_edges.slice(0, 10).map((r) => ["replies", `<code>${esc(short(r[0]))}</code>`, `<code>${esc(short(r[1]))}</code>`, fmt(r[2])]),
  ])}`;
  bindRows(el, (i) => goEvents({ actor: pairs[i].from }));
  const host = $("net"), pick = $("netN");
  const draw = () => drawNetwork(host, pairs.slice(0, +pick.value));
  pick.addEventListener("change", draw);
  draw();
  // redraw when the pane is resized, so the boxes always fit the width without scaling the text
  if (window.ResizeObserver) {
    let w = host.clientWidth, t = null;
    new ResizeObserver(() => { if (Math.abs(host.clientWidth - w) > 24) { w = host.clientWidth; clearTimeout(t); t = setTimeout(draw, 120); } }).observe(host);
  }
}

const textWidth = (() => {
  const ctx = document.createElement("canvas").getContext("2d");
  return (s, font) => { ctx.font = font; return ctx.measureText(s).width; };
})();
// shorten a name to fit, keeping its start and its distinguishing end ("AgentSECDou…6937")
function fitName(s, max, font) {
  if (textWidth(s, font) <= max) return s;
  let lo = 2, hi = s.length;
  while (lo < hi) {
    const k = Math.ceil((lo + hi) / 2), head = Math.ceil(k * 0.6), tail = k - head;
    if (textWidth(s.slice(0, head) + "…" + (tail ? s.slice(-tail) : ""), font) <= max) lo = k; else hi = k - 1;
  }
  const head = Math.ceil(lo * 0.6), tail = lo - head;
  return s.slice(0, head) + "…" + (tail ? s.slice(-tail) : "");
}

function drawNetwork(host, pairs) {
  if (!pairs.length) { host.innerHTML = '<p class="muted">No messages between named actors to draw.</p>'; return; }
  const out = {}, inn = {}, tot = {}, nb = {};
  pairs.forEach((p) => {
    out[p.from] = (out[p.from] || 0) + p.deliveries; inn[p.to] = (inn[p.to] || 0) + p.deliveries;
    tot[p.from] = (tot[p.from] || 0) + p.deliveries; tot[p.to] = (tot[p.to] || 0) + p.deliveries;
    (nb[p.from] ||= []).push(p.to); (nb[p.to] ||= []).push(p.from);
  });
  const names = Object.keys(tot);
  const colOf = (n) => (out[n] && inn[n] ? 1 : out[n] ? 0 : 2);   // 0 only sends, 1 both, 2 only receives

  // groups: actors connected by any message in the pairs shown
  const root = Object.fromEntries(names.map((n) => [n, n]));
  const find = (x) => (root[x] === x ? x : (root[x] = find(root[x])));
  pairs.forEach((p) => { const a = find(p.from), b = find(p.to); if (a !== b) root[a] = b; });
  const byRoot = {};
  names.forEach((n) => (byRoot[find(n)] ||= []).push(n));
  const groups = Object.values(byRoot).map((ns) => ({ ns, msgs: ns.reduce((s, n) => s + (out[n] || 0), 0) }))
    .sort((a, b) => b.msgs - a.msgs);

  // inside each group: three columns, ordered so arrows cross as little as possible
  const row = {};   // name -> row within its group (fractional when a column is shorter, so it sits centered)
  groups.forEach((g) => {
    const cols = [[], [], []];
    g.ns.sort((a, b) => tot[b] - tot[a]).forEach((n) => cols[colOf(n)].push(n));
    g.rows = Math.max(...cols.map((c) => c.length));
    const place = () => cols.forEach((c) => c.forEach((n, i) => (row[n] = i + (g.rows - c.length) / 2)));
    place();
    for (let it = 0; it < 8; it++) {
      [2, 1, 0, 1].forEach((ci) => {
        const mean = (n) => nb[n].reduce((s, m) => s + row[m], 0) / nb[n].length;
        cols[ci].sort((a, b) => mean(a) - mean(b) || tot[b] - tot[a]);
        place();
      });
    }
    g.cols = cols;
  });

  // geometry in real pixels: the drawing is as wide as the pane, so text is never scaled down
  const W = Math.max(320, host.clientWidth || 700);
  const ROW = 26, BOX = 19, TOP = 24, BAND_PAD = 7;
  const nameFont = '12px -apple-system, system-ui, "Segoe UI", sans-serif', numFont = '11px -apple-system, system-ui, sans-serif';
  const present = [0, 1, 2].filter((c) => groups.some((g) => g.cols[c].length));
  const gap = Math.max(46, Math.min(120, W * 0.12));
  // each column as wide as its longest name needs; if they do not all fit, trim the widest first
  const need = {};
  present.forEach((c) => (need[c] = Math.min(260, Math.max(...names.filter((n) => colOf(n) === c)
    .map((n) => textWidth(short(n), nameFont) + textWidth(fmt(tot[n]), numFont) + 26)))));
  const room = W - 8 - gap * (present.length - 1);
  const used = (cap) => present.reduce((s, c) => s + Math.min(need[c], cap), 0);
  let lo = 70, hi = 260;
  for (let it = 0; it < 30; it++) { const mid = (lo + hi) / 2; if (used(mid) <= room) lo = mid; else hi = mid; }
  const colW = Object.fromEntries(present.map((c) => [c, Math.min(need[c], lo)]));
  const total = present.reduce((s, c) => s + colW[c], 0) + gap * (present.length - 1);
  const colX = {};
  present.reduce((x, c) => { colX[c] = x; return x + colW[c] + gap; }, Math.max(4, (W - total) / 2));
  const boxOf = (n) => colW[colOf(n)];
  const pos = {};
  let y = TOP;
  groups.forEach((g) => {
    g.y0 = y; y += BAND_PAD;
    g.ns.forEach((n) => (pos[n] = { x: colX[colOf(n)], y: y + row[n] * ROW + ROW / 2 }));
    y += g.rows * ROW + BAND_PAD; g.y1 = y; y += 4;
  });
  const H = y + 4;
  const mx = Math.max(...pairs.map((p) => p.deliveries));
  const width = (n) => (1.2 + 4.3 * Math.log1p(n) / Math.log1p(mx)).toFixed(2);
  const heads = ["only sends", "sends and receives", "only receives"];

  let svg = `<svg class="net" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="messages between named actors">
  <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto"><path d="M0,1L10,5L0,9z" fill="#2f6fb3"/></marker></defs>`;
  groups.forEach((g, i) => { svg += `<rect x="0" y="${g.y0}" width="${W}" height="${g.y1 - g.y0}" rx="6" fill="${i % 2 ? "#ffffff" : "#f6f8fb"}"/>`; });
  present.forEach((c) => { svg += `<text x="${colX[c] + colW[c] / 2}" y="14" text-anchor="middle" font-size="11" fill="#66717d">${heads[c]}</text>`; });

  // arrows first, boxes on top
  pairs.forEach((p) => {
    const a = pos[p.from], b = pos[p.to];
    let d;
    if (colOf(p.from) === 1 && colOf(p.to) === 1) {
      // both in the middle column: a loop beside the column, downward on the right, upward on the left
      const down = b.y > a.y, bend = Math.min(gap * 0.7, 16 + 7 * Math.abs(b.y - a.y) / ROW), w = colW[1];
      d = down ? `M${a.x + w},${a.y} C${a.x + w + bend},${a.y} ${b.x + w + bend},${b.y} ${b.x + w + 2},${b.y}`
               : `M${a.x},${a.y} C${a.x - bend},${a.y} ${b.x - bend},${b.y} ${b.x - 2},${b.y}`;
    } else {
      const x1 = a.x + boxOf(p.from), x2 = b.x - 2, h = (x2 - x1) / 2;
      d = `M${x1},${a.y} C${x1 + h},${a.y} ${x2 - h},${b.y} ${x2},${b.y}`;
    }
    svg += `<path class="edge" data-a="${esc(p.from)}" data-b="${esc(p.to)}" d="${d}" fill="none" stroke="#2f6fb3" stroke-width="${width(p.deliveries)}" marker-end="url(#ah)"><title>${esc(short(p.from))} → ${esc(short(p.to))}: ${fmt(p.deliveries)} message${p.deliveries === 1 ? "" : "s"} over ${fmt(p.channels)} place${p.channels === 1 ? "" : "s"}, first ${esc(p.first)}</title></path>`;
  });
  const fill = ["#fdf0da", "#e7effa", "#eef1f4"], stroke = ["#e3a43b", "#2f6fb3", "#9aa5b1"];
  names.forEach((n) => {
    const c = colOf(n), { x, y: cy } = pos[n], num = fmt(tot[n]), bw = colW[c];
    const label = fitName(short(n), bw - 24 - textWidth(num, numFont), nameFont);
    svg += `<g class="node" data-actor="${esc(n)}"><title>${esc(n)}: sent ${fmt(out[n] || 0)}, received ${fmt(inn[n] || 0)} in the pairs shown</title>
      <rect x="${x}" y="${cy - BOX / 2}" width="${bw}" height="${BOX}" rx="${BOX / 2}" fill="${fill[c]}" stroke="${stroke[c]}"/>
      <text x="${x + 9}" y="${cy + 4}" font-size="12" fill="#1d2329">${esc(label)}</text>
      <text x="${x + bw - 9}" y="${cy + 4}" font-size="11" fill="#66717d" text-anchor="end">${num}</text></g>`;
  });
  host.innerHTML = svg + "</svg>";

  // hover: keep the chosen actor (or arrow) and what it touches, fade the rest
  const el = host.querySelector("svg");
  const light = (keepEdge) => {
    el.classList.add("dim");
    const keep = new Set();
    el.querySelectorAll(".edge").forEach((e) => {
      const on = keepEdge(e);
      e.classList.toggle("hi", on);
      if (on) { keep.add(e.dataset.a); keep.add(e.dataset.b); }
    });
    el.querySelectorAll(".node").forEach((g) => g.classList.toggle("hi", keep.has(g.dataset.actor)));
  };
  const clear = () => { el.classList.remove("dim"); el.querySelectorAll(".hi").forEach((x) => x.classList.remove("hi")); };
  el.querySelectorAll(".node").forEach((g) => {
    const n = g.dataset.actor;
    g.addEventListener("click", () => goEvents({ actor: n }));
    g.addEventListener("mouseenter", () => light((e) => e.dataset.a === n || e.dataset.b === n));
    g.addEventListener("mouseleave", clear);
  });
  el.querySelectorAll(".edge").forEach((edge) => {
    edge.addEventListener("mouseenter", () => light((e) => e === edge));
    edge.addEventListener("mouseleave", clear);
  });
}

// ------------------------------------------------------------------ timeline
function timeline(el, s) {
  const hours = Object.keys(s.activity_by_hour).sort();
  el.innerHTML = `<h2>What the agents did, hour by hour</h2><p class="muted small">Timed records only. Vertical lines mark when each early-flag signal first fired. Click a bar to list that hour's events.</p><div id="tl"></div>`;
  if (!hours.length) { $("tl").innerHTML = '<p class="muted">No timed records, so no timeline.</p>'; return; }
  const intents = Object.keys(s.intents);
  const color = Object.fromEntries(intents.map((k, i) => [k, PALETTE[i % PALETTE.length]]));
  const W = 780, H = 300, L = 44, B = 40;
  const tot = hours.map((h) => Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0));
  const mx = Math.max(...tot), bw = (W - L - 10) / hours.length;
  const t0 = toTime(hours[0] + ":00"), t1 = toTime(hours[hours.length - 1] + ":00") + 3600e3;
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="records per hour by intent">`;
  hours.forEach((h, k) => {
    let y = H - B;
    intents.forEach((it) => { const v = s.activity_by_hour[h][it] || 0; if (!v) return; const hh = (H - B - 14) * v / mx; y -= hh;
      svg += `<rect data-hour="${esc(h)}" x="${L + k * bw}" y="${y}" width="${Math.max(1, bw - 1)}" height="${hh}" fill="${color[it]}"><title>${esc(h)}h · ${esc(it)}: ${v}</title></rect>`; });
    if (k % Math.max(1, Math.round(hours.length / 10)) === 0) svg += `<text x="${L + k * bw}" y="${H - B + 14}" font-size="10" fill="#555">${esc(h.slice(5))}h</text>`;
  });
  s.replay.forEach((r, i) => {
    const T = toTime(r.time.replace("at or before ", "")); if (T == null) return;
    const x = L + (T - t0) / (t1 - t0) * (W - L - 10);
    svg += `<line x1="${x}" x2="${x}" y1="12" y2="${H - B}" stroke="#c0392b" stroke-dasharray="3 3"><title>${esc(r.signal)} · ${esc(r.time)}</title></line><text x="${x + 2}" y="${12 + (i % 6) * 11}" font-size="9.5" fill="#c0392b">${i + 1}</text>`;
  });
  svg += `<text x="2" y="14" font-size="10" fill="#555">${mx}/h</text></svg>`;
  $("tl").innerHTML = svg + `<div class="legend">${intents.map((k) => `<span><i style="background:${color[k]}"></i>${esc(k)}</span>`).join("")}</div>` +
    `<h3>Signals marked on the chart</h3>` + table(["#", "signal", "first time", "harm still to come"], s.replay.map((r, i) => [i + 1, esc(r.signal), esc(r.time), pct(r.harm_share_after)]));
  $("tl").querySelectorAll("rect[data-hour]").forEach((r) => r.addEventListener("click", () => goEvents({ hour: r.dataset.hour })));
}

// ------------------------------------------------------------------ channels
function channels(el, s) {
  const ct = Object.entries(s.flow.channel_types).sort((a, b) => b[1].deliveries - a[1].deliveries);
  el.innerHTML = `<h2>Channels and how messages performed</h2>
  <p class="muted small">A channel is a place agents write to and read from. Deliveries are reads after a write by another actor. Latency is write-to-read time.</p>
  ${table(["type", "channels", "writes", "reads", "messages", "written, never read by another actor"], ct.map(([t, v]) => [esc(t), fmt(v.channels), fmt(v.writes), fmt(v.reads), fmt(v.deliveries), fmt(v.never_read)]))}
  <h3>Messages per channel type</h3>${bars(ct.map(([t, v]) => [t, v.deliveries]))}
  <h3>Busiest channels</h3><p class="muted small">Click a channel to list the events that name it.</p>
  ${table(["channel", "writes", "reads", "writers", "readers", "messages", "median latency (h)", "first write"], s.top_channels.map((c) => [`<code>${esc(c.channel)}</code>`, fmt(c.writes), fmt(c.reads), fmt(c.writers), fmt(c.readers), fmt(c.deliveries), esc(c.median_latency_h), esc(c.first_write)]), true)}`;
  bindRows(el, (i) => goEvents({ q: s.top_channels[i].channel.split(":").slice(1).join(":") }));
}

// ------------------------------------------------------------------ spread
function spread(el, s) {
  const items = s.content_spread.slice(0, 14);
  el.innerHTML = `<h2>How information spread</h2>
  <p class="muted small">Each lane is one program (the same code, ids masked) used under several named actors. The orange dot is the first use (source); blue dots are later adopters. Click a dot to trace that record.</p>
  <div id="lanes"></div>
  <h3>Items seen as data, then used as an identity</h3>
  ${table(["item", "first seen", "record", "kind", "first used", "uses", "lead (h)"], s.seen_then_used.map((x) => [`<code>${esc(short(x.item))}</code>`, esc(x.first_seen), idlink(x.first_seen_id), esc(x.first_seen_kind), esc(x.first_used), fmt(x.uses), esc(x.lead_hours)]))}`;
  if (!items.length) { $("lanes").innerHTML = '<p class="muted">No program moved between two named actors.</p>'; return; }
  const pts = items.flatMap((x) => [toTime(x.source_time), ...x.adopters.map((a) => toTime(a.time))]).filter((t) => t != null);
  const t0 = Math.min(...pts), t1 = Math.max(...pts) || t0 + 1;
  const W = 780, row = 30, L = 120, R = 150, H = items.length * row + 40;
  const X = (t) => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="program spread lanes">`;
  items.forEach((x, i) => {
    const y = 20 + i * row;
    svg += `<text x="4" y="${y + 4}" font-size="11" fill="#333">${esc(x.family)} (${x.actors})</text><line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#eef0f3"/>`;
    x.adopters.forEach((a) => { const xx = X(toTime(a.time)); svg += `<line x1="${X(toTime(x.source_time))}" x2="${xx}" y1="${y}" y2="${y}" stroke="#7fb3e6"/><circle data-ev="${esc(a.record)}" class="node" cx="${xx}" cy="${y}" r="5" fill="#2f6fb3"><title>${esc(short(a.actor))} adopted it ${a.hours_after_source} h later (${esc(a.record)})</title></circle>`; });
    svg += `<circle data-ev="${esc(x.source_record)}" class="node" cx="${X(toTime(x.source_time))}" cy="${y}" r="6.5" fill="#e3a43b"><title>source ${esc(short(x.source))} at ${esc(x.source_time)} (${esc(x.source_record)})</title></circle>`;
    const lastH = Math.max(0, ...x.adopters.map((a) => a.hours_after_source));
    svg += `<text x="${W - R + 10}" y="${y + 4}" font-size="11" fill="#555">${x.adopters.length} adopters, last +${lastH < 1 ? Math.round(lastH * 60) + " min" : lastH.toFixed(1) + " h"}</text>`;
  });
  svg += `<text x="${L}" y="${H - 6}" font-size="10" fill="#555">${new Date(t0).toISOString().slice(5, 16).replace("T", " ")}</text><text x="${W - R}" y="${H - 6}" font-size="10" text-anchor="end" fill="#555">${new Date(t1).toISOString().slice(5, 16).replace("T", " ")}</text></svg>`;
  $("lanes").innerHTML = svg;
}

// ------------------------------------------------------------------ early flag
function early(el, s) {
  const rem = s.harm_remaining_by_hour;
  el.innerHTML = `<h2>Could it have been flagged early?</h2>
  <p class="muted small">The line is the share of timed harmful activity still to come at each hour. Each marker is when a signal first fired. The higher a marker sits on the line, the earlier the warning.</p><div id="ef"></div>
  ${table(["signal", "first time", "harm still to come", "spread still to come", "record"], s.replay.map((r) => [esc(r.signal), esc(r.time), pct(r.harm_share_after), pct(r.spread_share_after), /^[A-Za-z]\d{3,}$/.test(String(r.ref)) ? idlink(r.ref) : `<code>${esc(short(r.ref))}</code>`]))}
  ${s.flow.first_named_delivery ? `<div class="note">First message between named actors: ${esc(s.flow.first_named_delivery.read_time)}, with ${pct(s.flow.harm_share_after_first_named_delivery)} of the harm still to come (${idlink(s.flow.first_named_delivery.read_id)}).</div>` : ""}`;
  if (!rem.length) { $("ef").innerHTML = '<p class="muted">No timed harmful activity.</p>'; return; }
  const W = 780, H = 260, L = 40, B = 30;
  const t0 = toTime(rem[0][0] + ":00"), t1 = toTime(rem[rem.length - 1][0] + ":00") + 3600e3;
  const X = (t) => L + (t - t0) / (t1 - t0) * (W - L - 10), Y = (v) => 10 + (1 - v) * (H - B - 10);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="harm still to come over time">`;
  svg += `<polyline fill="none" stroke="#2f6fb3" stroke-width="2" points="${rem.map(([h, v]) => `${X(toTime(h + ":00"))},${Y(v)}`).join(" ")}"/>`;
  [0, 0.5, 1].forEach((v) => { svg += `<text x="2" y="${Y(v) + 4}" font-size="10" fill="#555">${v * 100}%</text><line x1="${L}" x2="${W - 10}" y1="${Y(v)}" y2="${Y(v)}" stroke="#eef0f3"/>`; });
  const sigs = [...s.replay];
  if (s.flow.first_named_delivery) sigs.push({ signal: "first message between named actors", time: s.flow.first_named_delivery.read_time, harm_share_after: s.flow.harm_share_after_first_named_delivery });
  sigs.forEach((r, i) => { const T = toTime(String(r.time).replace("at or before ", "")); if (T == null || r.harm_share_after == null) return;
    const col = r.signal.startsWith("coordination") || r.signal.startsWith("first message") ? "#c0392b" : "#e3a43b";
    svg += `<circle cx="${X(T)}" cy="${Y(r.harm_share_after)}" r="5" fill="${col}"><title>${esc(r.signal)} · ${esc(r.time)} · ${pct(r.harm_share_after)} still to come</title></circle>`; });
  svg += `<text x="${L}" y="${H - 8}" font-size="10" fill="#555">${esc(rem[0][0])}h</text><text x="${W - 10}" y="${H - 8}" font-size="10" text-anchor="end" fill="#555">${esc(rem[rem.length - 1][0])}h</text></svg>`;
  $("ef").innerHTML = svg + `<div class="legend"><span><i style="background:#e3a43b"></i>single-actor signal</span><span><i style="background:#c0392b"></i>coordination signal</span></div>`;
}

// ------------------------------------------------------------------ events
async function events(el, s) {
  const k = Object.keys(s.kinds), it = Object.keys(s.intents), tg = Object.keys(s.evidence_tags);
  const sel = (id, opts, v) => `<select id="${id}"><option value="">any</option>${opts.map((o) => `<option${o === v ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  el.innerHTML = `<h2>Every event</h2><div class="filters">
    <input id="fq" placeholder="search id or text" value="${esc(S.ev.q)}">
    <label>kind ${sel("fk", k, S.ev.kind)}</label><label>intent ${sel("fi", it, S.ev.intent)}</label><label>tag ${sel("ft", tg, S.ev.tag)}</label>
    <label><input type="checkbox" id="fc"${S.ev.channels ? " checked" : ""}> on a channel</label>
    ${S.ev.actor ? `<span class="chip">actor ${esc(short(S.ev.actor))} <button class="link" id="fa">×</button></span>` : ""}
    ${S.ev.hour ? `<span class="chip">hour ${esc(S.ev.hour)} <button class="link" id="fh">×</button></span>` : ""}
  </div><div id="evlist" class="muted">Loading…</div>`;
  const reload = () => { S.ev.offset = 0; loadEvents(); };
  let tmr; $("fq").addEventListener("input", (e) => { clearTimeout(tmr); tmr = setTimeout(() => { S.ev.q = e.target.value; reload(); }, 300); });
  $("fk").addEventListener("change", (e) => { S.ev.kind = e.target.value; reload(); });
  $("fi").addEventListener("change", (e) => { S.ev.intent = e.target.value; reload(); });
  $("ft").addEventListener("change", (e) => { S.ev.tag = e.target.value; reload(); });
  $("fc").addEventListener("change", (e) => { S.ev.channels = e.target.checked; reload(); });
  if ($("fa")) $("fa").addEventListener("click", () => { S.ev.actor = ""; render(); });
  if ($("fh")) $("fh").addEventListener("click", () => { S.ev.hour = ""; render(); });
  loadEvents();
}

async function loadEvents() {
  const host = $("evlist"); if (!host) return;
  const p = new URLSearchParams({ q: S.ev.q || "", hour: S.ev.hour || "", kind: S.ev.kind, intent: S.ev.intent, tag: S.ev.tag, actor: S.ev.actor, channels: S.ev.channels ? "1" : "", offset: S.ev.offset, limit: 100 });
  try {
    const r = await api("/api/events?" + p);
    const rows = r.rows;
    host.className = "";
    host.innerHTML = `<p class="muted small">${fmt(r.total)} events. Click one to trace it.</p>` +
      table(["id", "kind", "time", "actor", "intent", "tags", "msgs in/out", "text"], rows.map((x) => [esc(x.id), esc(x.kind), esc(x.time || "–"), `<code>${esc(short(x.actor))}</code>`, esc(x.intent || ""), x.tags.slice(0, 3).map((t) => `<span class="chip">${esc(t)}</span>`).join(""), `${x.in}/${x.out}`, `<span class="mono">${esc(x.preview.slice(0, 110))}</span>`]), true) +
      `<p><button id="pv"${r.offset === 0 ? " disabled" : ""}>Previous</button> <button id="nx"${r.offset + 100 >= r.total ? " disabled" : ""}>Next</button> <span class="muted small">${fmt(r.offset + 1)}–${fmt(Math.min(r.total, r.offset + 100))}</span></p>`;
    bindRows(host, (i) => selectEvent(rows[i].id));
    $("pv").onclick = () => { S.ev.offset = Math.max(0, S.ev.offset - 100); loadEvents(); };
    $("nx").onclick = () => { S.ev.offset += 100; loadEvents(); };
  } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
}

// ------------------------------------------------------------------ gaps
function gaps(el, s) {
  const f = s.flow, g = s.gaps, ak = f.actors_on_channels || {};
  el.innerHTML = `<h2>What an investigator would still miss</h2><ul>
  <li><b>Time.</b> ${fmt(s.records - s.timed)} of ${fmt(s.records)} records have no time, so they are not on the timeline or in the early-flag replay.</li>
  <li><b>Who.</b> ${fmt(g.no_actor)} records have no actor field or identity token. On channels, ${fmt(ak.token || 0)} actors are tokens, ${fmt(ak.handle || 0)} are named handles, and ${fmt(ak.run || 0)} are anonymous single runs.</li>
  ${s.pack_actor_note ? `<li><b>Names.</b> ${esc(s.pack_actor_note)}</li>` : ""}
  <li><b>Token is not agent.</b> One agent can hold several tokens; a shared key stands for many agents. A message between two tokens may be one agent talking to itself.</li>
  <li><b>Order.</b> ${fmt(f.deliveries_order_unknown)} reads follow another actor's write on the same channel but cannot be ordered because one side has no time.</li>
  <li><b>Merged places.</b> ${fmt(f.coarse_channel_deliveries || 0)} messages are on channels the redaction reduced to an owner, which may join two different places.</li>
  ${f.overwrites ? `<li><b>Overwrites.</b> ${fmt(f.overwrites)} edits replaced another actor's edit without keeping any line it added. A whole-page edit can be sent without reading the page first, so these may be agents unaware of each other, not a disagreement. They are left out of the message counts.</li>` : ""}
  <li><b>Reading is inferred.</b> ${fmt((f.deliveries_by_how || {})["named the place"] || 0)} messages rest only on a record naming the place. Naming a page or posting after someone shows the place was known, not that the earlier content was read.</li>
  <li><b>Success.</b> A read or write in the code is an attempt; the data rarely records whether it worked.</li>
  <li><b>Unlisted channels.</b> Messages through places the pack does not describe, or with no shared place, are invisible.</li>
  <li><b>Patterns.</b> Tags and intents are pattern matches on text, not verified behavior.</li>
  <li><b>Links.</b> ${fmt(g.no_parent)} records have no parent link.</li></ul>`;
}

// ------------------------------------------------------------------ event trace (right top)
async function selectEvent(id) {
  if (!id) return;
  S.selected = id;
  $("traceid").textContent = id;
  const host = $("trace");
  host.innerHTML = '<div class="empty">Tracing…</div>';
  try {
    const t = await api("/api/event?id=" + encodeURIComponent(id));
    host.innerHTML = traceHTML(t);
    host.scrollTop = 0;
    host.scrollLeft = 0;
  } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
}

function traceHTML(t) {
  const W = 560, H = 230, cx = W / 2, cy = H / 2;
  let svg = `<svg class="tracegraph" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="trace of ${esc(t.id)}"><defs><marker id="ta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0L10,5L0,10z" fill="#7a8794"/></marker></defs>`;
  const cut = (x, n = 21) => (String(x).length > n ? "…" + String(x).slice(-(n - 1)) : String(x));
  const node = (x, y, label, sub, id, fill) => { label = cut(label); sub = cut(sub, 26); return `<g class="node" data-ev="${esc(id || "")}"><title>${esc(id || label)}</title><rect x="${x - 62}" y="${y - 17}" width="124" height="34" rx="6" fill="${fill}" stroke="#c9d1da"/><text x="${x}" y="${y - 2}" text-anchor="middle" font-size="11" font-weight="600" fill="#1d2329">${esc(label)}</text><text x="${x}" y="${y + 11}" text-anchor="middle" font-size="9.5" fill="#5b6672">${esc(sub)}</text></g>`; };
  const arrow = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#7a8794" marker-end="url(#ta)"/>`;
  const par = t.parent_chain.slice(0, 1)[0];
  if (par) svg += node(80, cy, par.id, `parent · ${par.kind}`, par.id, "#f3f6fa") + arrow(142, cy, cx - 64, cy);
  t.children.slice(0, 3).forEach((c, i) => { const y = cy + (i - (Math.min(3, t.children.length) - 1) / 2) * 42; svg += arrow(cx + 64, cy, W - 142, y) + node(W - 80, y, c.id, `child · ${c.kind}`, c.id, "#f3f6fa"); });
  t.messages_in.slice(0, 3).forEach((m, i) => { const x = cx + (i - (Math.min(3, t.messages_in.length) - 1) / 2) * 130; svg += node(x, 26, short(m.from), `wrote ${m.write_time || ""}`, m.write_id, "#fff4dd") + arrow(x, 44, cx, cy - 19); });
  t.messages_out.slice(0, 3).forEach((m, i) => { const x = cx + (i - (Math.min(3, t.messages_out.length) - 1) / 2) * 130; svg += arrow(cx, cy + 19, x, H - 44) + node(x, H - 26, short(m.to), `read ${m.read_time || ""}`, m.read_id, "#e8f4ea"); });
  svg += node(cx, cy, t.id, `${t.kind} · ${short(t.actor)}`, t.id, "#dbe9f8") + "</svg>";
  const more = [];
  if (t.parent_chain.length > 1) more.push(`${t.parent_chain.length} ancestors`);
  if (t.children_total > 3) more.push(`${t.children_total} children`);
  if (t.messages_in.length > 3) more.push(`${t.messages_in.length} messages in`);
  if (t.messages_out.length > 3) more.push(`${t.messages_out.length} messages out`);
  return `
  <div><b>${esc(t.id)}</b> · ${esc(t.kind)} · ${esc(t.time || "no time")}${t.time_source ? ` (${esc(t.time_source)})` : ""} · actor <code>${esc(short(t.actor))}</code> <span class="muted small">(${esc(t.actor_kind)})</span></div>
  <div>${t.intent ? `<span class="chip">${esc(t.intent)}</span>` : ""}${t.tags.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}${t.context_tags.map((x) => `<span class="chip ctx">${esc(x)}</span>`).join("")}</div>
  ${svg}
  ${more.length ? `<p class="muted small">Graph shows up to 3 of each; ${esc(more.join(", "))}.</p>` : ""}
  <h3>Identities</h3><p>${Object.entries(t.identities).map(([k, v]) => `<code>${esc(short(k))}</code> <span class="muted small">${esc(v)}</span>`).join(", ") || '<span class="muted">none in this record</span>'}</p>
  <h3>Thread</h3><p>Root ${idlink(t.thread_root)} · parent ${idlink(t.parent)} · ancestors ${t.parent_chain.map((p) => idlink(p.id)).join(" ← ") || "none"}${t.children_total ? ` · children: ${t.children.slice(0, 12).map((c) => idlink(c.id)).join(", ")}${t.children_total > 12 ? " …" : ""}` : ""}</p>
  <h3>Channels touched</h3>${table(["channel", "op"], t.channel_ops.map((o) => [`<code>${esc(o.channel)}</code>`, esc(o.op)]))}
  <h3>Messages in</h3>${table(["from", "channel", "written in", "at", "evidence"], t.messages_in.map((m) => [`<code>${esc(short(m.from))}</code>`, `<code>${esc(m.channel)}</code>`, idlink(m.write_id), esc(m.write_time), esc(m.how || "")]))}
  <h3>Messages out</h3>${table(["to", "channel", "read in", "at", "evidence"], t.messages_out.map((m) => [`<code>${esc(short(m.to))}</code>`, `<code>${esc(m.channel)}</code>`, idlink(m.read_id), esc(m.read_time), esc(m.how || "")]))}
  ${(t.overwrote || []).length || (t.overwritten_by || []).length ? `<h3>Overwrites <span class="muted small">(not counted as messages)</span></h3>${table(["", "actor", "record", "channel", "what happened"], [
    ...(t.overwrote || []).map((o) => ["replaced", `<code>${esc(short(o.actor))}</code>`, idlink(o.record), `<code>${esc(o.channel)}</code>`, esc(o.how)]),
    ...(t.overwritten_by || []).map((o) => ["replaced by", `<code>${esc(short(o.actor))}</code>`, idlink(o.record), `<code>${esc(o.channel)}</code>`, esc(o.how)])])}` : ""}
  <h3>Same program elsewhere (${fmt(t.same_program_total)})</h3>${table(["id", "actor", "time"], t.same_program.slice(0, 12).map((c) => [idlink(c.id), `<code>${esc(short(c.actor))}</code>`, esc(c.time || "–")]))}
  <h3>Text <span class="muted small">(${fmt(t.text_length)} chars${t.text_truncated ? ", truncated" : ""}; data written by the agents)</span></h3><pre>${esc(t.text)}</pre>`;
}

// ------------------------------------------------------------------ AI investigator (right bottom)
$("aiset").addEventListener("click", () => { const h = $("aisettings").hidden; $("aisettings").hidden = !h; $("aiset").setAttribute("aria-expanded", String(h)); });
function saveAI() {
  if ($("remember").checked) sessionStorage.setItem("st-ai", JSON.stringify({ baseUrl: $("baseUrl").value, model: $("model").value, apiKey: $("apiKey").value }));
  else sessionStorage.setItem("st-ai", JSON.stringify({ baseUrl: $("baseUrl").value, model: $("model").value }));
}
["baseUrl", "model", "apiKey", "remember"].forEach((id) => $(id).addEventListener("change", saveAI));
$("listModels").addEventListener("click", async () => {
  try { const r = await api("/api/ai/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ baseUrl: $("baseUrl").value, apiKey: $("apiKey").value }) });
    $("modellist").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join(""); addMsg("assistant", `Models available: ${r.models.join(", ")}`); }
  catch (e) { addMsg("error", "Could not list models: " + e.message); }
});
$("quick").addEventListener("click", (e) => { const b = e.target.closest("button[data-q]"); if (b) ask(b.dataset.q); });
$("ask").addEventListener("submit", (e) => { e.preventDefault(); const q = $("q").value.trim(); if (q) { $("q").value = ""; ask(q); } });
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("ask").requestSubmit(); });

function md(text) {
  let h = esc(text);
  h = h.replace(/```([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
  // record ids are cited in backticks: make every space-free code span clickable
  h = h.replace(/`([^`\s]{2,160})`/g, '<code class="idlink" data-id="$1">$1</code>');
  h = h.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  h = h.replace(/^#{1,4} (.*)$/gm, "<b>$1</b>");
  h = h.replace(/(^|\n)[-*] (.*)/g, "$1• $2");
  h = h.replace(/(^|[\s(,])([A-Z]\d{4,})\b/g, '$1<span class="idlink" data-id="$2">$2</span>');
  return h.replace(/\n/g, "<br>");
}
function addMsg(role, text, meta) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.innerHTML = (role === "user" ? esc(text).replace(/\n/g, "<br>") : md(text)) + (meta ? `<div class="meta">${esc(meta)}</div>` : "");
  $("chat").appendChild(d);
  $("chat").scrollTop = $("chat").scrollHeight;
  return d;
}

async function ask(q) {
  if (!S.summary) { addMsg("error", "Load a dataset first."); return; }
  if (!$("apiKey").value) { $("aisettings").hidden = false; addMsg("error", "Enter an API key in Settings first."); return; }
  S.chat.push({ role: "user", content: q });
  addMsg("user", q);
  const wait = addMsg("assistant", "Investigating…");
  $("send").disabled = true;
  try {
    const r = await api("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      messages: S.chat, apiKey: $("apiKey").value, baseUrl: $("baseUrl").value, model: $("model").value,
      selectedId: $("useSel").checked ? S.selected : null }) });
    wait.remove();
    S.chat.push({ role: "assistant", content: r.content });
    addMsg("assistant", r.content, `${$("model").value}${r.context_ids?.length ? " · evidence sent: " + r.context_ids.join(", ") : ""}${r.usage?.total_tokens ? " · " + r.usage.total_tokens + " tokens" : ""}`);
  } catch (e) { wait.remove(); S.chat.pop(); addMsg("error", e.message); }
  finally { $("send").disabled = false; }
}

init().catch((e) => status(e.message, true));

// Swarm Tracer core: state, API, formatting, design tokens, chart helpers, entity chips,
// hover cards, the inspector (right top), tabs and the top bar. Views live in views/*.js and
// register themselves in VIEWS; the AI investigator lives in ai.js.
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString());
const pct = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
const short = (a) => String(a ?? "").replace(/\[CREDENTIAL (\d+)\]/g, "cred $1").replace(/^run:/, "run ");
const plural = (n, w, ws) => `${fmt(n)} ${n === 1 ? w : (ws || w + "s")}`;
const human = (s) => String(s ?? "").replace(/_/g, " ");
const VIEWS = {};
const S = { summary: null, tab: "overview", selected: null, chat: [], cache: new Map(),
  ev: { q: "", kind: "", intent: "", tag: "", actor: "", hour: "", channels: false, offset: 0 } };

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data;
  try { data = await r.json(); } catch { throw new Error(`HTTP ${r.status}`); }
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
// GET once per dataset; views share the result
function cached(path) {
  if (!S.cache.has(path)) S.cache.set(path, api(path).catch((e) => { S.cache.delete(path); throw e; }));
  return S.cache.get(path);
}

// ------------------------------------------------------------------ design tokens
const INK = "#1b2430", QUIET = "#66717d", GRID = "#e8ebef", AXIS = "#a3acb6", CURVE = "#b9bfb7";
const ACCENT = "#2f6fb3", SINGLE = "#4b5157", HARM = "#c2410c", BASE = "#8a94a0";
const C = {
  ink: INK, quiet: QUIET, grid: GRID, axis: AXIS,
  joint: ACCENT, single: SINGLE, harm: HARM, baseline: BASE,
  actor: "#b7791f", actorBg: "#fdf3e1", place: "#6b46c1", placeBg: "#f1ebfb",
  record: ACCENT, recordBg: "#e8f0fa", program: "#0f766e", programBg: "#e0f2f1", message: ACCENT,
};
// one colour per intent, the same in every view
const INTENT_PALETTE = ["#2f6fb3", "#e3a43b", "#c2410c", "#0f766e", "#7c4dbd", "#d35400", "#6aa5dc", "#2e9d5b", "#b8579a", "#5d6d7e", "#c9a227"];
function intentColor(name) {
  if (!name || name === "other") return "#cdd3da";
  const order = Object.keys(S.summary?.intents || {}).filter((k) => k !== "other");
  const i = order.indexOf(name);
  return INTENT_PALETTE[(i < 0 ? order.length : i) % INTENT_PALETTE.length];
}
const intentName = (k) => (S.summary?.intent_names?.[k]) || human(k);
const tagName = (k) => (S.summary?.tag_names?.[k]) || human(k);
const isHarm = (k) => (S.summary?.harm_names || []).includes(k);

// ------------------------------------------------------------------ time
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const toTime = (s) => {
  if (s == null || s === "") return null;
  if (typeof s === "number") return s > 1e12 ? s : s * 1000;
  const x = String(s).replace("at or before ", "").replace(" UTC", "").trim();
  const iso = x.length === 13 ? x + ":00" : x.length === 10 ? x + " 00:00" : x;
  const t = Date.parse(iso.replace(" ", "T") + (iso.length <= 16 ? ":00Z" : "Z"));
  return Number.isNaN(t) ? null : t;
};
const sigTime = toTime;
const dayWord = (t) => { const d = new Date(t); return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`; };
const clock = (t) => new Date(t).toISOString().slice(11, 16);
const when = (t) => (t == null ? "–" : `${dayWord(t)} ${clock(t)}`);
const hoursWord = (h) => (h == null ? "–" : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${(+h).toFixed(1)} h` : `${(h / 24).toFixed(1)} days`);
// ticks at whole days, quarter days or hours, whichever gives 3 to 10 ticks across the span
function timeTicks(t0, t1, maxTicks = 10) {
  const H = 3600e3, span = t1 - t0;
  const D = 24 * H, steps = [15 * 60e3, H, 3 * H, 6 * H, 12 * H, D, 2 * D, 4 * D, 7 * D, 14 * D, 30 * D];
  const step = steps.find((s) => span / s <= maxTicks) || 30 * D;
  const out = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step)
    out.push({ t, label: step >= 24 * H || (new Date(t).getUTCHours() === 0 && step > H) ? dayWord(t) : `${dayWord(t)} ${clock(t)}`, day: new Date(t).getUTCHours() === 0 });
  return out;
}
// the dataset's time span, for charts that line up with each other
function span() {
  const sp = S.summary?.time_test?.span;
  return sp ? [toTime(sp[0]), toTime(sp[1]) + 3600e3] : null;
}

// ------------------------------------------------------------------ text measuring
const textWidth = (() => {
  const ctx = document.createElement("canvas").getContext("2d");
  return (s, font = "12px -apple-system, system-ui, sans-serif") => { ctx.font = font; return ctx.measureText(s).width; };
})();
// shorten a name to fit, keeping its start and its distinguishing end ("AgentSECDou…6937")
function fitName(s, max, font) {
  s = String(s);
  if (textWidth(s, font) <= max) return s;
  let lo = 2, hi = s.length;
  while (lo < hi) {
    const k = Math.ceil((lo + hi) / 2), head = Math.ceil(k * 0.6), tail = k - head;
    if (textWidth(s.slice(0, head) + "…" + (tail ? s.slice(-tail) : ""), font) <= max) lo = k; else hi = k - 1;
  }
  const head = Math.ceil(lo * 0.6), tail = lo - head;
  return s.slice(0, head) + "…" + (tail ? s.slice(-tail) : "");
}

// ------------------------------------------------------------------ entity chips
// Every actor, place and record anywhere in the app is one of these: hover for a card, click to inspect.
const xtra = (x) => (typeof x === "string" ? x : "");   // .map(ent.rec) passes an index here; ignore it
const ent = {
  actor: (a, extra = "") => a ? `<span class="ent actor${String(a).startsWith("run:") ? " run" : ""}" data-actor="${esc(a)}"><i></i>${esc(short(a))}${xtra(extra)}</span>` : "–",
  place: (ch, extra = "") => ch ? `<span class="ent place" data-place="${esc(ch)}" title="${esc(ch)}"><i></i>${esc(placeLabel(ch))}${xtra(extra)}</span>` : "–",
  rec: (id, extra = "") => id ? `<span class="ent rec" data-id="${esc(id)}">${esc(id)}${xtra(extra)}</span>` : "–",
  intent: (k) => k ? `<span class="pill" style="--c:${intentColor(k)}" title="${esc(intentName(k))}"><i></i>${esc(human(k))}</span>` : "",
};
const idlink = (id) => ent.rec(id);
function placeLabel(ch) {
  const [type, ...rest] = String(ch).split(":");
  const name = rest.join(":").replace(/\]\s*\[/g, "] + [")
    .replace(/\[REDACTED:query_value:0*(\d+)\]/g, "URL value $1")
    .replace(/\[REDACTED:([a-z_]+):0*(\d+)\]/g, (m, k, n) => `${k.replace(/_/g, " ")} ${n}`)
    .replace(/\[([A-Z][A-Z ]+?) (\d+)\]/g, "$1 $2").replace(/\[([A-Z][A-Z ]+)\]/g, "$1");
  return `${type.replace(/_/g, " ")} · ${name}`;
}
const PLACE_TYPES = { hf_dataset: ["Hugging Face dataset", "Hugging Face datasets"], board: ["board folder (registry mailbox)", "board folders (registry mailbox)"],
  webhook: ["webhook", "webhooks"], command_file: ["command file", "command files"], page: ["wiki page", "wiki pages"], thread: ["thread", "threads"], talk: ["talk page", "talk pages"] };
const placeType = (t, n = 1) => (PLACE_TYPES[t] ? PLACE_TYPES[t][n === 1 ? 0 : 1] : human(t) + (n === 1 ? "" : "s"));

// ------------------------------------------------------------------ small charts (HTML or SVG strings)
// sparkline of [[isoHour, n], ...] across [t0, t1]; mark = time to highlight
function spark(series, { w = 160, h = 28, t0, t1, color = ACCENT, mark = null, fill = true, max = null } = {}) {
  const sp = span();
  t0 = t0 ?? sp?.[0]; t1 = t1 ?? sp?.[1];
  if (!series?.length || t0 == null) return `<svg class="spark" width="${w}" height="${h}"></svg>`;
  const pts = series.map(([k, v]) => [toTime(k), v]).filter((p) => p[0] != null).sort((a, b) => a[0] - b[0]);
  const mx = max || Math.max(1, ...pts.map((p) => p[1]));
  const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (w - 2) + 1, Y = (v) => h - 2 - (v / mx) * (h - 4);
  const bw = Math.max(1, (w - 2) / Math.max(1, (t1 - t0) / 3600e3));
  let s = `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><line x1="0" x2="${w}" y1="${h - 1.5}" y2="${h - 1.5}" stroke="${GRID}"/>`;
  pts.forEach(([t, v]) => { s += `<rect x="${X(t).toFixed(1)}" y="${Y(v).toFixed(1)}" width="${bw.toFixed(2)}" height="${(h - 2 - Y(v)).toFixed(1)}" fill="${color}" opacity="${fill ? 0.85 : 1}"/>`; });
  if (mark != null) s += `<line x1="${X(mark)}" x2="${X(mark)}" y1="0" y2="${h}" stroke="${HARM}" stroke-width="1.5"/>`;
  return s + "</svg>";
}
// a list of horizontal bars; items [{label(html), value, color?, title?, attrs?}]
function hbars(items, { max = null, total = null, unit = "" } = {}) {
  const mx = max || Math.max(1, ...items.map((i) => i.value));
  return `<div class="hbars">${items.map((i) => `<div class="hb"${i.attrs ? " " + i.attrs : ""}${i.title ? ` title="${esc(i.title)}"` : ""}><div class="hl">${i.label}</div><div class="ht"><i style="width:${(100 * i.value / mx).toFixed(2)}%;background:${i.color || ACCENT}"></i></div><div class="hv">${fmt(i.value)}${unit}${total ? `<span> ${(100 * i.value / total).toFixed(i.value / total < 0.01 ? 1 : 0)}%</span>` : ""}</div></div>`).join("")}</div>`;
}
// one stacked bar with a legend; parts [{label, value, color}]
function stackbar(parts, { legend = true, h = 12 } = {}) {
  const tot = parts.reduce((a, p) => a + p.value, 0) || 1;
  return `<div class="stack" style="height:${h}px">${parts.filter((p) => p.value).map((p) => `<i style="width:${(100 * p.value / tot).toFixed(3)}%;background:${p.color}" title="${esc(p.label)}: ${fmt(p.value)} (${(100 * p.value / tot).toFixed(1)}%)"></i>`).join("")}</div>` +
    (legend ? `<div class="legend">${parts.filter((p) => p.value).map((p) => `<span><i style="background:${p.color}"></i>${esc(p.label)} <b>${fmt(p.value)}</b></span>`).join("")}</div>` : "");
}
// share meter 0..1
const meter = (x, color = ACCENT, w = 90) => `<span class="meter" style="width:${w}px"><i style="width:${Math.max(0, Math.min(1, x ?? 0)) * 100}%;background:${color}"></i></span>`;
// a label may carry a glossary term (term()), so it is escaped only when it is plain text
const kpi = (label, v, sub = "", extra = "") => `<div class="kpi"><b>${v}</b><span>${String(label).includes("<") ? label : esc(label)}</span>${sub ? `<em>${sub}</em>` : ""}${extra}</div>`;
const card = (title, body, { sub = "", cls = "", right = "" } = {}) => `<section class="card ${cls}"><header><h3>${title}</h3>${right}</header>${sub ? `<p class="sub">${sub}</p>` : ""}${body}</section>`;

// ------------------------------------------------------------------ tables and full lists
function table(headers, rows, onclick) {
  if (!rows.length) return '<p class="muted">None found.</p>';
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r, i) => `<tr${onclick ? ` class="click" data-i="${i}"` : ""}>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function bindRows(el, onclick) { el.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", (e) => { if (e.target.closest(".ent,button,a")) return; onclick(+tr.dataset.i); })); }
// a table that starts with the rows the summary carries and can page through the whole list on the server
function listView(host, name, headers, rowFn, rows, total, onRow) {
  if (!host) return;
  const st = { rows: rows.slice(), total: total ?? rows.length, q: "", full: false };
  const load = async (append) => {
    const r = await api(`/api/list?name=${encodeURIComponent(name)}&q=${encodeURIComponent(st.q)}&offset=${append ? st.rows.length : 0}&limit=200`);
    st.rows = append ? st.rows.concat(r.rows) : r.rows; st.total = r.total; st.full = true; draw();
  };
  const draw = () => {
    const filter = st.total > 12 || st.q ? `<p class="small listbar"><input class="lq" placeholder="Filter all ${fmt(st.total)} rows" value="${esc(st.q)}"> <span class="muted">${st.rows.length < st.total ? `showing ${fmt(st.rows.length)} of ${fmt(st.total)}` : plural(st.total, "row")}</span></p>` : "";
    host.innerHTML = filter + table(headers, st.rows.map(rowFn), !!onRow) + (st.rows.length < st.total ? `<button type="button" class="lmore">Show ${st.full ? "200 more" : `all ${fmt(st.total)}`}</button>` : "");
    if (onRow) bindRows(host, (i) => onRow(st.rows[i]));
    const more = host.querySelector(".lmore"); if (more) more.addEventListener("click", () => load(st.full));
    const q = host.querySelector(".lq");
    if (q) { let t = null; q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { st.q = q.value.trim(); load(false).then(() => { const n = host.querySelector(".lq"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }); }, 250); }); }
  };
  draw();
  return { reload: () => load(false) };
}
// redraw a chart when its box changes width
function onResize(host, draw) {
  if (!window.ResizeObserver || !host) return;
  let w = host.clientWidth, t = null;
  new ResizeObserver(() => { if (host.isConnected && Math.abs(host.clientWidth - w) > 24) { w = host.clientWidth; clearTimeout(t); t = setTimeout(draw, 120); } }).observe(host);
}

// ------------------------------------------------------------------ label placement (for charts with many labelled dots)
// Search the whole plot for each label's spot: no overlap with other labels, as little of the line
// and the dots covered as possible, and the shortest leader back to its dot.
function placeLabels(items, box, avoidPts, maxLeader = 260) {
  const G = 5, nx = Math.ceil((box.x1 - box.x0) / G) + 1, ny = Math.ceil((box.y1 - box.y0) / G) + 1;
  const grid = new Uint8Array(nx * ny);
  avoidPts.forEach((p) => {
    const r = p.r || 3;
    for (let j = Math.floor((p.y - r - box.y0) / G); j <= Math.floor((p.y + r - box.y0) / G); j++)
      for (let i = Math.floor((p.x - r - box.x0) / G); i <= Math.floor((p.x + r - box.x0) / G); i++)
        if (i >= 0 && j >= 0 && i < nx && j < ny) grid[j * nx + i] = 1;
  });
  const P = new Int32Array((nx + 1) * (ny + 1));
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    P[(j + 1) * (nx + 1) + i + 1] = grid[j * nx + i] + P[j * (nx + 1) + i + 1] + P[(j + 1) * (nx + 1) + i] - P[j * (nx + 1) + i];
  const covered = (b) => {
    const i0 = Math.max(0, Math.floor((b.x - box.x0) / G)), i1 = Math.min(nx, Math.ceil((b.x + b.w - box.x0) / G));
    const j0 = Math.max(0, Math.floor((b.y - box.y0) / G)), j1 = Math.min(ny, Math.ceil((b.y + b.h - box.y0) / G));
    return P[j1 * (nx + 1) + i1] - P[j0 * (nx + 1) + i1] - P[j1 * (nx + 1) + i0] + P[j0 * (nx + 1) + i0];
  };
  const hits = (a, b, m = 4) => a.x < b.x + b.w + m && b.x < a.x + a.w + m && a.y < b.y + b.h + m && b.y < a.y + a.h + m;
  const crosses = (ax, ay, bx, by, r) => {
    let t0 = 0, t1 = 1; const dx = bx - ax, dy = by - ay;
    for (const [p, q] of [[-dx, ax - r.x], [dx, r.x + r.w - ax], [-dy, ay - r.y], [dy, r.y + r.h - ay]]) {
      if (p === 0) { if (q < 0) return false; continue; }
      const t = q / p; if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
    }
    return true;
  };
  const placed = [];
  const anchors = items.map((it) => ({ x: it.x, y: it.y, it }));
  for (const it of items) {
    let best = null;
    for (let y = box.y0; y + it.h <= box.y1; y += 6) for (let x = box.x0; x + it.w <= box.x1; x += 6) {
      const b = { x, y, w: it.w, h: it.h };
      if (placed.some((p) => hits(b, p))) continue;
      const lx = Math.max(b.x, Math.min(it.x, b.x + b.w)), ly = Math.max(b.y, Math.min(it.y, b.y + b.h));
      const d = Math.hypot(lx - it.x, ly - it.y);
      if (d > maxLeader) continue;
      const near = anchors.filter((a) => a.it !== it && a.x > b.x - 16 && a.x < b.x + b.w + 16 && a.y > b.y - 16 && a.y < b.y + b.h + 16).length;
      const cross = placed.filter((p) => crosses(it.x, it.y, lx, ly, p)).length;
      const cost = covered(b) * 60 + d * 1.2 + (d > 12 ? 10 : 0) + near * 90 + cross * 160;
      if (!best || cost < best.cost) best = { b, cost };
    }
    if (best) { it.label = best.b; placed.push(best.b); }
  }
}

// ------------------------------------------------------------------ signals
const SIGNAL_NAMES = {
  registry_board: "Registry mailbox first used", docker_registry: "Docker registry first used",
  hf_dataset_write: "First Hugging Face dataset write", kubernetes_api: "Kubernetes API first called",
  cloud_metadata: "Cloud metadata first requested", probe_request: "First probe request",
  hides_page: "First page hidden", proxy_link: "First proxy link", recreated_after_delete: "Page recreated after a delete",
  runs_shell: "First shell command", handles_secrets: "First secret handled", sends_data: "First data sent out", deletes: "First delete",
};
function signalInfo(r) {
  if (r.family) return { name: r.name, joint: r.family === "joint", baseline: r.family === "baseline" };
  const sig = String(r.signal);
  if (sig.startsWith("first message")) return { name: "First message between named actors", joint: true };
  if (sig.startsWith("coordination: one identity carries")) return { name: "One identity carries another's token", joint: true };
  if (sig.startsWith("coordination: two identities")) return { name: `Two identities share ${String(r.ref).length < 24 ? "place " + r.ref : "one place"}`, joint: true };
  if (sig.startsWith("coordination")) return { name: sig.replace(/^coordination:\s*/, "").replace(/^./, (c) => c.toUpperCase()), joint: true };
  if (sig.startsWith("spread")) return { name: "Token seen as data, then used", joint: false };
  const key = sig.replace(/^first:\s*/, "");
  return { name: SIGNAL_NAMES[key] || ("First " + key.replace(/_/g, " ")), joint: false };
}
const FAMILY = { joint: { label: "actors together", color: ACCENT }, single: { label: "single actor", color: SINGLE }, baseline: { label: "volume baseline", color: BASE } };

// ------------------------------------------------------------------ glossary: every term the app uses, in plain words
const GLOSSARY = {
  record: ["Record", "One row of the trace: here a payload (code an agent ran), a response (what came back), or a recovered text."],
  dated: ["Dated record", "A record with a time: its own time field, or a time estimated from unix timestamps the agents wrote into their code (fitted per block of same-kind records, and kept only if the fit passes a rank-correlation and error check)."],
  action: ["Action", "A record an agent ran (here, a payload). Only actions can have an actor, an intent or count as harmful."],
  actor: ["Actor", "Who did a record: an identity token it authenticates with, a name it writes, or, failing both, its own run. A token is not an agent: one agent can hold several tokens."],
  named: ["Named actor", "Any actor that is not an anonymous run: an identity token (shown as cred N), a token taken from the record's thread, or a self-chosen name."],
  token: ["Identity token", "A credential a record uses to authenticate. The release redacts it to a stable placeholder such as [CREDENTIAL 169], shown here as cred 169: the same placeholder is the same hidden token everywhere."],
  token_via_thread: ["Token via thread", "A record with no token of its own whose thread (parent chain) uses one: it is credited to that token."],
  handle: ["Self-chosen name", "A name an agent wrote into its code (for example OTS92), from the pack's list of names."],
  run: ["Anonymous run", "A record with no token and no name. It is identified only by the first record of its thread (run R…), so two runs may be one agent."],
  shared_key: ["Shared key", "A token that many agents use, such as the evaluation key every agent submits with. It says nothing about who acted, so it is never counted as an actor."],
  place: ["Place", "Anywhere one actor can leave something for another: a Hugging Face dataset, a folder on the registry used as a board, a webhook, a command file, a wiki page."],
  write: ["Write / read", "Each mention of a place in code is judged a write if write code (an upload, a commit, a POST, a folder creation) sits within 160 characters before or 260 after it; otherwise it is a read."],
  message: ["Message", "A read of a place after a different actor wrote to it, linked to the latest such write. Each write counts once per reader, and a reader running the same program as the writer is one sender retrying, not a message."],
  merged: ["Merged place", "A place the redaction reduced to its owner's name, so it may join several repositories: a write and a read there may be on two different places."],
  overwrite: ["Overwrite", "Where every post replaces a whole page, an edit that keeps none of the lines the earlier editor added. The editor may never have seen it, so it is not counted as a message."],
  latency: ["Wait", "Time from a write to the read that picked it up."],
  program: ["Program", "The same code with ids, numbers and hashes masked. A shared program is run by two or more named actors: the first is its source, the rest adopted it."],
  seen_used: ["Seen, then used", "A token that appears inside a record as data before any record uses it to authenticate: one way a credential passes between agents."],
  carried: ["Carried token", "A record that authenticates as one identity and holds another identity's token, before that token's own first use."],
  intent: ["Intent", "What an action's code tries to do: the first of the pack's intent patterns that matches it. A pattern match, not proof that it worked."],
  tag: ["Tag", "A behavior pattern found in the code (for example a POST, a bearer token, a shell command). Context tags are shown but never counted as evidence."],
  harm: ["Harmful action", "An action whose intent or tag is in the pack's harm list. The list says which kinds of action the investigator treats as harm; the others (for example reading public pages) still happened but are not counted as harm."],
  harm_left: ["Harm still to come", "Of all dated harmful actions, the share that came after a given moment. 90% means a warning then would have come before 90% of the harm."],
  sign: ["Warning sign", "The first time a signal fires. Single actor: one agent doing something harmful. Actors together: a link between agents (a message, a shared program, a carried token, a shared name, a linked group). Volume baseline: ordinary monitoring of action counts."],
  volume: ["Volume alarm", "The baseline: fires at the end of the first hour whose action count is above the mean plus three standard deviations of every earlier hour (after 12 hours of history)."],
  stretch: ["Stretch of the incident", "Where a moment falls, from the data's own shape: build-up (before the main surge), surge, height (from the busiest hour until activity falls below 15% of it), wind-down."],
  pack: ["Pack", "A small JSON file that adapts the tool to a dataset: which records are actions and which patterns mark identities, places, intents and harm."],
  group: ["Linked group", "Actors joined by a chain of messages, in either direction."],
  broker: ["Broker", "An actor on many of the shortest message routes between other actors: removing it splits groups apart."],
};
const term = (key, label) => GLOSSARY[key] ? `<span class="term" data-term="${key}">${label ?? esc(GLOSSARY[key][0])}</span>` : (label ?? key);
function glossaryText(key) {
  const g = GLOSSARY[key];
  if (!g) return "";
  let d = g[1];
  if (key === "harm" && (S.summary?.harm_names || []).length) d += " In this pack: " + S.summary.harm_names.map(human).join(", ") + ".";
  const ak = S.summary?.actions?.kinds || S.summary?.actor_kinds;
  if (key === "named" && ak) d += ` In this dataset, ${fmt(S.summary.actions?.named_actors)} named actors ran actions: ${[[ak.token, "identity tokens"], [ak.token_via_thread, "tokens via thread"], [ak.handle, "self-chosen names"], [ak.named, "actor fields"]].filter(([n]) => n).map(([n, w]) => `${fmt(n)} ${w}`).join(", ")}.`;
  return d;
}
function glossaryCard(key) { const g = GLOSSARY[key]; return g ? `<div class="hc"><div class="hch"><b>${esc(g[0])}</b></div><div class="hcwhat">${esc(glossaryText(key))}</div><div class="hcfoot">Click for the glossary</div></div>` : ""; }
function openGlossary(q = "") {
  let el = $("glossary");
  if (!el) { el = document.createElement("div"); el.id = "glossary"; el.className = "glossary"; document.body.appendChild(el); }
  const draw = (q) => {
    const rows = Object.entries(GLOSSARY).filter(([, [n, d]]) => !q || (n + " " + d).toLowerCase().includes(q.toLowerCase()));
    el.querySelector(".glist").innerHTML = rows.map(([k, [n]]) => `<div class="gitem" id="g-${k}"><b>${esc(n)}</b><p>${esc(glossaryText(k))}</p></div>`).join("") || '<p class="muted">No term matches.</p>';
  };
  el.innerHTML = `<div class="ghead"><h3>What the words mean</h3><input placeholder="Find a term" value="${esc(q)}"><button type="button" class="link">Close</button></div><div class="glist"></div>`;
  el.hidden = false;
  el.querySelector("button").addEventListener("click", () => { el.hidden = true; });
  el.querySelector("input").addEventListener("input", (e) => draw(e.target.value));
  draw(q);
}

// ------------------------------------------------------------------ hover cards
const HC = { el: null, timer: null, hide: null, key: null };
function hcEl() {
  if (!HC.el) {
    HC.el = document.createElement("div"); HC.el.className = "hovercard"; HC.el.hidden = true; document.body.appendChild(HC.el);
    HC.el.addEventListener("mouseenter", () => clearTimeout(HC.hide));
    HC.el.addEventListener("mouseleave", () => hideCard());
  }
  return HC.el;
}
function hideCard() { clearTimeout(HC.timer); HC.hide = setTimeout(() => { if (HC.el) HC.el.hidden = true; HC.key = null; }, 140); }
function placeCard(x, y) {
  const el = hcEl(), r = el.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  let left = x + 14, top = y + 14;
  if (left + r.width > W - 8) left = Math.max(8, x - r.width - 14);
  if (top + r.height > H - 8) top = Math.max(8, H - r.height - 8);
  el.style.left = left + "px"; el.style.top = top + "px";
}
async function showCard(target, x, y) {
  if (target.dataset.term) {
    HC.key = "t:" + target.dataset.term;
    const el = hcEl(); el.innerHTML = glossaryCard(target.dataset.term); el.hidden = false; placeCard(x, y);
    return;
  }
  const a = target.dataset.actor, ch = target.dataset.place, id = target.dataset.id || target.dataset.ev;
  const key = a ? "a:" + a : ch ? "p:" + ch : id ? "r:" + id : null;
  if (!key || HC.key === key) return;
  HC.key = key;
  const el = hcEl();
  el.innerHTML = '<div class="hcload">…</div>'; el.hidden = false; placeCard(x, y);
  try {
    let html;
    if (a) html = actorCard(await cached("/api/actor?a=" + encodeURIComponent(a)));
    else if (ch) html = placeCard_(await cached("/api/place?ch=" + encodeURIComponent(ch)));
    else html = recordCard(await cached("/api/event?lite=1&id=" + encodeURIComponent(id)));
    if (HC.key !== key) return;
    el.innerHTML = html; placeCard(x, y);
  } catch (e) { if (HC.key === key) el.innerHTML = `<div class="hcload">${esc(e.message)}</div>`; }
}
function actorCard(p) {
  const kindWord = { token: "identity token", handle: "self-chosen name", run: "anonymous run", token_via_thread: "token (from its thread)", named: "actor field" }[p.kind] || p.kind;
  const top = p.intents.slice(0, 4);
  return `<div class="hc actor"><div class="hch"><span class="ent actor"><i></i>${esc(short(p.actor))}</span><span class="muted">${esc(kindWord)}${p.shared ? " · shared key" : ""}</span></div>
    ${spark(p.hourly, { w: 260, h: 34, color: C.actor })}
    <div class="hcrow muted small"><span>${when(toTime(p.first))}</span><span>${when(toTime(p.last))}</span></div>
    <div class="hcstats"><span><b>${fmt(p.actions)}</b> actions (${fmt(p.timed_actions)} dated)</span><span><b>${fmt(p.harmful)}</b> harmful</span><span><b>${fmt(p.places_total)}</b> places</span></div>
    <div class="hcstats"><span>messages: <b>${fmt(p.sent)}</b> sent, <b>${fmt(p.received)}</b> received, <b>${fmt(p.partners)}</b> partners</span><span class="muted">with named actors only: ${fmt(p.sent_named)} / ${fmt(p.received_named)} / ${fmt(p.partners_named)}</span></div>
    ${top.length ? stackbar(top.map((i) => ({ label: human(i.intent), value: i.n, color: intentColor(i.intent) })), { h: 8 }) : ""}
    ${p.signals.length ? `<div class="hcsig">${p.signals.slice(0, 3).map((g) => `<span class="sigdot" style="background:${FAMILY[g.family]?.color}"></span>${esc(g.name)} <span class="muted">${esc(g.time)}</span>`).join("<br>")}</div>` : ""}
    <div class="hcfoot">Click to inspect</div></div>`;
}
function placeCard_(p) {
  const r = p.row || {};
  const series = p.hourly.map(([h, c]) => [h, Object.values(c).reduce((a, b) => a + b, 0)]);
  return `<div class="hc place"><div class="hch"><span class="ent place"><i></i>${esc(placeLabel(p.channel))}</span></div>
    <div class="muted small">${esc(placeType(p.type))}${p.merged ? " · may merge several places (redaction kept only the owner)" : ""}</div>
    ${spark(series, { w: 260, h: 30, color: C.place })}
    <div class="hcstats"><span><b>${fmt(r.writes)}</b> writes</span><span><b>${fmt(r.reads)}</b> reads</span><span><b>${fmt(p.writers.length)}</b> writers</span><span><b>${fmt(p.readers.length)}</b> readers</span><span><b>${fmt(p.messages_total)}</b> messages</span>${p.overwrites ? `<span><b>${fmt(p.overwrites)}</b> overwrites</span>` : ""}</div>
    ${r.never_read ? '<div class="small" style="color:#9a3412">Written, never read by another actor</div>' : ""}
    <div class="hcfoot">Click to inspect</div></div>`;
}
function recordCard(t) {
  const x = t.explain || {};
  return `<div class="hc rec"><div class="hch"><span class="ent rec">${esc(t.id)}</span><span class="muted">${esc(t.kind)} · ${esc(t.time || "no time")}</span></div>
    <div class="hcrow">${ent.actor(t.actor)} ${ent.intent(t.intent)}</div>
    <div class="hcwhat">${(x.what || []).slice(0, 2).map(esc).join(" ")}</div>
    ${(x.roles || []).length ? `<div class="roles">${x.roles.slice(0, 4).map((r) => `<span class="role ${r.role}">${esc(r.label)}</span>`).join("")}</div>` : ""}
    <div class="hcstats"><span><b>${fmt(t.messages_in.length)}</b> messages in</span><span><b>${fmt(t.messages_out.length)}</b> out</span><span><b>${fmt(t.channel_ops.length)}</b> place${t.channel_ops.length === 1 ? "" : "s"}</span><span><b>${fmt(t.same_program_total)}</b> other cop${t.same_program_total === 1 ? "y" : "ies"} of its program</span></div>
    ${x.harm_share_after != null ? `<div class="small">${meter(x.harm_share_after, HARM, 70)} <b>${pct(x.harm_share_after)}</b> of the dated harm came after it</div>` : ""}
    <div class="hcfoot">Click to inspect</div></div>`;
}
document.addEventListener("mouseover", (e) => {
  const t = e.target.closest("[data-term],[data-actor],[data-place],[data-id],[data-ev]");
  if (!t || t.closest(".hovercard") || t.dataset.nocard != null) return;
  clearTimeout(HC.hide); clearTimeout(HC.timer);
  HC.timer = setTimeout(() => showCard(t, e.clientX, e.clientY), 260);
});
// a card never outlives the pointer: close it on any press, scroll or key
const dropCard = () => { clearTimeout(HC.timer); if (HC.el) HC.el.hidden = true; HC.key = null; };
document.addEventListener("mousedown", (e) => { if (!e.target.closest(".hovercard")) dropCard(); });
document.addEventListener("scroll", dropCard, true);
document.addEventListener("keydown", (e) => { if (e.target.matches?.("input,textarea")) dropCard(); });
document.addEventListener("mouseout", (e) => {
  const t = e.target.closest("[data-term],[data-actor],[data-place],[data-id],[data-ev]");
  if (t && !t.contains(e.relatedTarget)) hideCard();
});
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-term]");
  if (g) { openGlossary(GLOSSARY[g.dataset.term]?.[0] || ""); return; }
  const t = e.target.closest("[data-actor],[data-place],[data-id],[data-ev]");
  if (!t || t.dataset.noclick != null) return;
  if (HC.el) HC.el.hidden = true; HC.key = null;
  if (t.dataset.actor) inspectActor(t.dataset.actor);
  else if (t.dataset.place) inspectPlace(t.dataset.place);
  else selectEvent(t.dataset.id || t.dataset.ev);
});

// ------------------------------------------------------------------ the inspector (right top): a record, an actor or a place
const INS = { stack: [] };
// features add sections to the Inspector: window.INSPECTOR_EXTRAS.push((kind, key, data) => html), and
// window.INSPECTOR_BIND.push((host, kind, key) => {...}) to wire them after render
window.INSPECTOR_EXTRAS = window.INSPECTOR_EXTRAS || [];
window.INSPECTOR_BIND = window.INSPECTOR_BIND || [];
const extras = (kind, key, data) => window.INSPECTOR_EXTRAS.map((f) => { try { return f(kind, key, data) || ""; } catch (e) { console.error(e); return ""; } }).join("");
const bindExtras = (host, kind, key) => window.INSPECTOR_BIND.forEach((f) => { try { f(host, kind, key); } catch (e) { console.error(e); } });
function inspect(kind, key, render) {
  const cur = INS.stack.at(-1);
  if (!cur || cur.kind !== kind || cur.key !== key) INS.stack.push({ kind, key });
  if (INS.stack.length > 30) INS.stack.shift();
  $("traceid").innerHTML = `${INS.stack.length > 1 ? '<button class="link" id="insBack" title="Back">← back</button> ' : ""}<span class="kindtag ${kind}">${kind}</span> ${esc(kind === "actor" ? short(key) : kind === "place" ? placeLabel(key) : key)}`;
  if ($("insBack")) $("insBack").addEventListener("click", () => { INS.stack.pop(); const p = INS.stack.pop(); if (p) ({ record: selectEvent, actor: inspectActor, place: inspectPlace })[p.kind](p.key); });
  const host = $("trace");
  host.innerHTML = '<div class="empty">Loading…</div>';
  render(host).then(() => { host.scrollTop = 0; }).catch((e) => { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; });
}
function selectEvent(id) {
  if (!id) return;
  S.selected = id;
  inspect("record", id, async (host) => { const t = await api("/api/event?id=" + encodeURIComponent(id)); host.innerHTML = recordDossier(t) + extras("record", id, t); bindExtras(host, "record", id); });
}
function inspectActor(a) {
  inspect("actor", a, async (host) => { const p = await cached("/api/actor?a=" + encodeURIComponent(a)); host.innerHTML = actorDossier(p) + extras("actor", a, p); bindDossier(host); bindExtras(host, "actor", a); });
}
function inspectPlace(ch) {
  inspect("place", ch, async (host) => { const p = await cached("/api/place?ch=" + encodeURIComponent(ch)); host.innerHTML = placeDossier(p) + extras("place", ch, p); bindDossier(host); bindExtras(host, "place", ch); });
}
function bindDossier(host) {
  host.querySelectorAll("[data-goevents]").forEach((b) => b.addEventListener("click", () => goEvents(JSON.parse(b.dataset.goevents))));
}

// small node-link picture: what came in, the record, what went out, its parent and children
function recordGraph(t) {
  const W = 560, H = 210, cx = W / 2, cy = H / 2;
  let svg = `<svg class="tracegraph" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="trace of ${esc(t.id)}"><defs><marker id="ta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0L10,5L0,10z" fill="#7a8794"/></marker></defs>`;
  const cut = (x, n = 20) => (String(x).length > n ? "…" + String(x).slice(-(n - 1)) : String(x));
  const node = (x, y, label, sub, attrs, fill, stroke = "#c9d1da") => `<g class="node" ${attrs}><rect x="${x - 62}" y="${y - 17}" width="124" height="34" rx="7" fill="${fill}" stroke="${stroke}"/><text x="${x}" y="${y - 2}" text-anchor="middle" font-size="11" font-weight="600" fill="${INK}">${esc(cut(label))}</text><text x="${x}" y="${y + 11}" text-anchor="middle" font-size="9.5" fill="#5b6672">${esc(cut(sub, 26))}</text></g>`;
  const arrow = (x1, y1, x2, y2, c = "#7a8794") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" marker-end="url(#ta)"/>`;
  const par = t.parent_chain[0];
  if (par) svg += node(80, cy, par.id, `parent · ${par.kind}`, `data-id="${esc(par.id)}"`, "#f3f6fa") + arrow(142, cy, cx - 64, cy);
  t.children.slice(0, 3).forEach((c, i) => { const y = cy + (i - (Math.min(3, t.children.length) - 1) / 2) * 42; svg += arrow(cx + 64, cy, W - 142, y) + node(W - 80, y, c.id, `child · ${c.kind}`, `data-id="${esc(c.id)}"`, "#f3f6fa"); });
  t.messages_in.slice(0, 3).forEach((m, i) => { const x = cx + (i - (Math.min(3, t.messages_in.length) - 1) / 2) * 132; svg += node(x, 24, short(m.from), `wrote ${m.write_time || ""}`, `data-id="${esc(m.write_id)}"`, C.actorBg, "#e7c48a") + arrow(x, 42, cx, cy - 19, C.actor); });
  t.messages_out.slice(0, 3).forEach((m, i) => { const x = cx + (i - (Math.min(3, t.messages_out.length) - 1) / 2) * 132; svg += arrow(cx, cy + 19, x, H - 42, ACCENT) + node(x, H - 24, short(m.to), `read ${m.read_time || ""}`, `data-id="${esc(m.read_id)}"`, "#e8f0fa", "#9fbfe3"); });
  svg += node(cx, cy, t.id, `${t.kind} · ${short(t.actor)}`, `data-id="${esc(t.id)}" data-noclick`, "#dbe9f8", ACCENT) + "</svg>";
  return svg;
}
const ROLE_ICON = { sender: "↗", receiver: "↘", signal: "⚑", source: "◆", adopter: "◇", carrier: "⇄", seen: "◉", overwrite: "✎", harm: "!" };
// plain text from the server with record ids, credentials and place keys turned into chips
function richText(text) {
  return esc(text)
    .replace(/(hf_dataset|board|webhook|command_file|place):((?:\[[^\]\s]+(?: [^\]]+)?\]|[\w.\-~@#/])+)/g, (m) => ent.place(m.replace(/&amp;/g, "&")))
    .replace(/\[CREDENTIAL (\d+)\]/g, (m) => ent.actor(m))
    .replace(/(^|[\s(,;])(R\d{6,8})\b/g, (m, pre, id) => pre + ent.rec(id));
}
const KIND_WORD = { payload: "payload: code an agent ran", response: "response: what came back to an agent", recovered_text: "recovered text: text recovered from the agents' files" };
const ACTOR_KIND = { token: ["identity token", "token"], token_via_thread: ["token taken from its thread", "token_via_thread"], handle: ["self-chosen name", "handle"], run: ["anonymous run", "run"], named: ["actor field", "actor"] };
const actorKind = (k) => ACTOR_KIND[k] ? term(ACTOR_KIND[k][1], esc(ACTOR_KIND[k][0])) : esc(k);
function msgLine(m, dir) {
  const who = dir === "in" ? m.from : m.to;
  return `<div class="mline">${dir === "in" ? `${ent.actor(who)} wrote ${ent.place(m.channel)} in ${ent.rec(m.write_id)} <span class="muted">${esc(m.write_time || "")}</span>; this record read it`
    : `this record wrote ${ent.place(m.channel)}; ${ent.actor(who)} read it in ${ent.rec(m.read_id)} <span class="muted">${esc(m.read_time || "")}</span>`}${m.latency_h != null ? ` <span class="muted">(${hoursWord(m.latency_h)} later)</span>` : ""} <span class="how">${esc(m.how || "")}</span></div>`;
}
const more = (shown, total, what) => total > shown ? `<p class="small muted">Showing ${fmt(shown)} of ${fmt(total)} ${what}.</p>` : "";
function recordDossier(t) {
  const x = t.explain || {}, a = x.actor || {}, comp = x.components || {}, pr = x.program;
  const pos = a.position && a.timed ? `record ${fmt(a.position)} of ${fmt(a.timed)} dated records by this actor` : "";
  return `
  <div class="dhead"><div><span class="ent rec big" data-noclick data-id="${esc(t.id)}">${esc(t.id)}</span> <span class="badge" title="${esc(KIND_WORD[t.kind] || t.kind)}">${esc(t.kind)}</span> ${ent.intent(t.intent)}</div>
    <div class="muted small">${esc(t.time ? t.time + " UTC" : "no time")}${t.time_source ? ` (${t.time_source === "estimated" ? term("dated", "estimated") : esc(t.time_source)})` : ""} · by ${ent.actor(t.actor)} <span class="muted">(${actorKind(t.actor_kind)})</span></div></div>
  ${x.copy_of ? `<div class="note small">Not an ${term("action")} itself: ${esc(KIND_WORD[t.kind] || t.kind)}. It repeats or answers ${ent.rec(x.copy_of.record)} (${esc(x.copy_of.why)}), so its identities and places are counted there, not twice.</div>` : ""}
  <div class="dsec what"><h4>What it is</h4><ul>${(x.what || []).map((w) => `<li>${richText(w)}</li>`).join("")}</ul>
    ${t.tags.length || t.context_tags.length ? `<div class="chips"><span class="small muted">${term("tag", "tags")}:</span>${t.tags.map((g) => `<span class="chip" title="${esc(tagName(g))}">${esc(human(g))}</span>`).join("")}${t.context_tags.map((g) => `<span class="chip ctx" title="context only, not evidence: ${esc(tagName(g))}">${esc(human(g))}</span>`).join("")}</div>` : ""}</div>
  <div class="dsec"><h4>Its role in the swarm</h4>
    ${(x.roles || []).length ? `<div class="rolelist">${x.roles.map((r) => `<div class="rolecard ${r.role}"><span class="ri">${ROLE_ICON[r.role] || "•"}</span><div><b>${esc(r.label)}</b><div class="small muted">${richText(r.detail)}</div></div></div>`).join("")}</div>` : '<p class="small muted">No link to another actor found: it sends and receives no message, starts or reuses no shared program, and fires no warning sign.</p>'}
    <div class="dgrid">
      <div><div class="dl">${term("harm_left")}</div>${x.harm_share_after != null ? `${meter(x.harm_share_after, HARM, 110)} <b>${pct(x.harm_share_after)}</b><div class="small muted">of all dated harmful actions came after this record's time</div>` : `<span class="muted small">${x.is_action === false ? "not an action, so not placed" : "no time, so no position"}</span>`}</div>
      <div><div class="dl">${term("stretch")}</div>${x.phase ? `<b>${esc(x.phase.name)}</b><div class="small muted">${esc(x.phase.what)}</div>` : '<span class="muted small">–</span>'}${x.report_phase ? `<div class="small">The reports call this stretch: ${esc(x.report_phase.name)} <span class="muted">(${esc(x.report_phase.source)})</span></div>` : ""}</div>
    </div></div>
  <div class="dsec"><h4>Its actor ${ent.actor(t.actor)}</h4>
    ${spark(a.hourly, { w: 320, h: 34, color: C.actor, mark: toTime(t.time) })}
    ${sparkAxis(320)}
    <div class="small muted">${fmt(a.records)} records${pos ? " · this is " + pos : ""}. Bars: its dated records per hour; ${t.time ? "red line: this record." : "this record has no time."}</div></div>
  <div class="dsec"><h4>What it connects to</h4>
    <div class="comp">${[["identities", comp.identities], ["places written", comp.places_written], ["places read", comp.places_read], ["messages in", comp.messages_in], ["messages out", comp.messages_out], ["records before it in its thread", comp.ancestors], ["records after it (children)", comp.children], ["evidence tags", comp.tags], ["context tags", comp.context_tags]].map(([k, v]) => `<div class="${v ? "" : "zero"}"><b>${fmt(v || 0)}</b><span>${k}</span></div>`).join("")}</div>
    ${recordGraph(t)}
    <p class="small muted">Above: messages in (writers, amber); left: its parent; right: its children; below: who read what it wrote (blue). Up to 3 of each.</p></div>
  ${t.messages_in.length ? `<div class="dsec"><h4>${term("message", "Messages in")} (${fmt(t.messages_in.length)})</h4>${t.messages_in.slice(0, 20).map((m) => msgLine(m, "in")).join("")}${more(Math.min(20, t.messages_in.length), t.messages_in.length, "messages")}</div>` : ""}
  ${t.messages_out.length ? `<div class="dsec"><h4>${term("message", "Messages out")} (${fmt(t.messages_out.length)})</h4>${t.messages_out.slice(0, 20).map((m) => msgLine(m, "out")).join("")}${more(Math.min(20, t.messages_out.length), t.messages_out.length, "messages")}</div>` : ""}
  ${(t.overwrote || []).length || (t.overwritten_by || []).length ? `<div class="dsec"><h4>${term("overwrite", "Overwrites")} <span class="muted small">(not counted as messages)</span></h4>${[
    ...(t.overwrote || []).map((o) => `<div class="mline">replaced ${ent.actor(o.actor)}'s edit ${ent.rec(o.record)} on ${ent.place(o.channel)} <span class="how">${esc(o.how)}</span></div>`),
    ...(t.overwritten_by || []).map((o) => `<div class="mline">replaced by ${ent.actor(o.actor)} in ${ent.rec(o.record)} on ${ent.place(o.channel)} <span class="how">${esc(o.how)}</span></div>`)].join("")}</div>` : ""}
  ${pr && pr.copies <= 1 ? `<div class="dsec"><h4>The same ${term("program")} elsewhere</h4><p class="small muted">No other action runs exactly this code (ids, numbers and hashes masked).</p></div>` : ""}
  ${pr && pr.copies > 1 ? `<div class="dsec"><h4>The same ${term("program")} elsewhere</h4>
    <div class="small">${plural(pr.copies, "copy", "copies")} including this one (${esc(pr.rule)}), run by ${plural(pr.actors, "actor")}, ${fmt(pr.named_actors)} of them named. ${pr.is_first ? "<b>This is its first run.</b>" : pr.first_record ? `First run by ${ent.actor(pr.first_actor)} in ${ent.rec(pr.first_record)}${pr.first_time ? ` at ${esc(pr.first_time)}` : ""}.` : ""}</div>
    ${pr.hourly.length ? spark(pr.hourly, { w: 320, h: 30, color: C.program, mark: toTime(t.time) }) + sparkAxis(320) : ""}
    <div class="chips">${pr.top_actors.map((p) => ent.actor(p.actor, ` <span class="muted">${fmt(p.n)}</span>`)).join(" ")}</div></div>` : ""}
  <div class="dsec"><h4>${term("token", "Identities")}</h4><p>${Object.entries(t.identities).map(([k, v]) => `${ent.actor(k)} <span class="muted small">used as ${esc(v.replace(/_/g, " "))}</span>`).join(" ") || '<span class="muted">none in this record</span>'}</p></div>
  <div class="dsec"><h4>${term("place", "Places touched")}</h4>${t.channel_ops.length ? `<div class="chips">${t.channel_ops.map((o) => ent.place(o.channel, ` <span class="op ${o.op}">${esc(o.op)}</span>`)).join(" ")}</div>` : '<p class="muted small">none</p>'}</div>
  <div class="dsec"><h4>Thread</h4><p class="small">First record of its thread ${ent.rec(t.thread_root)} · parent ${ent.rec(t.parent)}${t.parent_chain.length > 1 ? ` · earlier in the thread ${t.parent_chain.slice(0, 8).map((p) => ent.rec(p.id)).join(" ← ")}` : ""}${t.children_total ? ` · children ${t.children.slice(0, 10).map((c) => ent.rec(c.id)).join(" ")}${t.children_total > 10 ? ` and ${fmt(t.children_total - 10)} more` : ""}` : ""}</p></div>
  ${t.same_program.length ? `<div class="dsec"><h4>Records whose code starts the same way (${fmt(t.same_program_total)})</h4><p class="small muted">The first 60 words of code match (ids masked): the rule that treats a rerun of one program as one sender, not a message.</p>${table(["id", "actor", "time"], t.same_program.slice(0, 10).map((c) => [ent.rec(c.id), ent.actor(c.actor), esc(c.time || "–")]))}${more(Math.min(10, t.same_program.length), t.same_program_total, "records")}</div>` : ""}
  ${whySection(t)}
  <div class="dsec"><h4>Text <span class="muted small">(${fmt(t.text_length)} chars${t.text_truncated ? ", truncated" : ""}; written by the agents, shown as data)</span></h4>
    ${(t.why || []).length ? `<div class="wlegend">${WHY_ORDER.filter((k) => t.why.some((w) => w.type === k)).map((k) => `<span class="w-${k}">${esc(WHY_NAME[k])}</span>`).join("")}<span class="muted small">hover a mark to see what it set</span></div>` : ""}
    <pre class="whytext">${highlight(t.text, t.why || [])}</pre></div>
  <div class="dsec"><button type="button" class="primary" onclick="askAbout('${esc(t.id)}')">Ask the AI to explain this record</button></div>`;
}
// start and end dates under a sparkline that spans the whole dataset
function sparkAxis(w) {
  const sp = span();
  return sp ? `<div class="saxis" style="width:${w}px"><span>${esc(dayWord(sp[0]))}</span><span>${esc(dayWord(sp[1] - 1))}</span></div>` : "";
}
// why the tool reads a record the way it does: the stretches of its text that set each reading
const WHY_ORDER = ["intent", "tag", "identity", "info", "place", "write_cue", "handle", "name", "context"];
const WHY_NAME = { intent: "sets the intent", tag: "evidence tag", identity: "identity token", info: "token seen as data", place: "place named", write_cue: "write code", handle: "self-chosen name", name: "reusable name", context: "context tag" };
function highlight(text, spans) {
  if (!spans.length) return esc(text);
  const cuts = new Set([0, text.length]);
  spans.forEach((w) => { cuts.add(w.s); cuts.add(w.e); });
  const pts = [...cuts].filter((x) => x >= 0 && x <= text.length).sort((a, b) => a - b);
  let out = "";
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], seg = text.slice(a, b);
    const on = spans.filter((w) => w.s <= a && w.e >= b);
    if (!on.length) { out += esc(seg); continue; }
    const top = WHY_ORDER.find((k) => on.some((w) => w.type === k));
    const cls = [...new Set(on.map((w) => "w-" + w.type))].join(" ");
    out += `<mark class="${cls} top-${top}" title="${esc(on.map((w) => w.label).join("\n"))}">${esc(seg)}</mark>`;
  }
  return out;
}
function whySection(t) {
  const w = t.why || [];
  if (!w.length) return "";
  const by = {};
  w.forEach((x) => { const k = x.type + "\u0000" + x.key; (by[k] ||= { ...x, n: 0, snip: t.text.slice(x.s, Math.min(x.e, x.s + 70)) }).n += 1; });
  const rows = Object.values(by).sort((a, b) => WHY_ORDER.indexOf(a.type) - WHY_ORDER.indexOf(b.type));
  return `<div class="dsec"><h4>Why the tool reads it this way</h4><div class="whylist">${rows.map((x) => `<div class="whyrow"><span class="wk w-${x.type}">${esc(WHY_NAME[x.type])}</span><div><div>${esc(x.label)}</div><code class="wsnip">${esc(x.snip)}${x.e - x.s > 70 ? "…" : ""}</code>${x.n > 1 ? ` <span class="muted small">×${x.n}</span>` : ""}</div></div>`).join("")}</div>
    <p class="small muted">Every reading is a pattern match on the text, from the pack. It shows what the code would do, not whether it worked.</p></div>`;
}

const progWhat = (w) => !w ? "" : [w.intent_what, ...(w.tags || []).map((t) => t.what)].filter(Boolean).join("; ");
function actorDossier(p) {
  const kindWord = { token: "identity token", handle: "self-chosen name", run: "anonymous run", token_via_thread: "token (from its thread)", named: "actor field" }[p.kind] || p.kind;
  const ev = esc(JSON.stringify({ actor: p.actor }));
  return `
  <div class="dhead"><div><span class="ent actor big" data-noclick data-actor="${esc(p.actor)}"><i></i>${esc(short(p.actor))}</span> <span class="badge">${esc(kindWord)}</span>${p.shared ? ' <span class="badge warnb">shared key: stands for many agents</span>' : ""}</div>
    <div class="muted small">${actorKind(p.kind)} · active ${esc(p.first || "no time")} to ${esc(p.last || "")} UTC</div></div>
  <div class="dsec">${spark(p.hourly, { w: 420, h: 46, color: C.actor })}${sparkAxis(420)}<div class="small muted">Its dated records per hour.</div>
    <div class="comp">${[["actions", p.actions], ["dated actions", p.timed_actions], ["harmful actions", p.harmful], ["records incl. responses", p.records], ["messages sent", p.sent], ["messages received", p.received], ["partners", p.partners], ["places", p.places_total], ["programs started", p.programs_started_total], ["programs reused", p.programs_adopted_total]].map(([k, v]) => `<div class="${v ? "" : "zero"}"><b>${fmt(v || 0)}</b><span>${k}</span></div>`).join("")}</div>
    <p class="small muted">Messages count every partner, anonymous runs included; with named actors only: ${fmt(p.sent_named)} sent, ${fmt(p.received_named)} received, ${fmt(p.partners_named)} partners (the numbers on Who talked to whom). Records include the responses and texts credited to this actor through its threads.</p>
    <button type="button" data-goevents="${ev}">List all ${fmt(p.records)} events</button></div>
  <div class="dsec"><h4>What its ${term("action", "actions")} do <span class="muted small">(${term("intent", "intent")}; share of its ${fmt(p.actions)} actions)</span></h4>${hbars(p.intents.map((i) => ({ label: `${esc(human(i.intent))}${isHarm(i.intent) ? ' <span class="harmtag">harm</span>' : ""}`, value: i.n, color: intentColor(i.intent), title: i.what })), { total: p.actions || p.records })}
    ${p.tags.length ? `<div class="small muted" style="margin-top:6px">Patterns found in its code (${term("tag", "tags")}; one action can have several)</div><div class="chips">${p.tags.map((g) => `<span class="chip" title="${esc(g.what)}">${esc(human(g.tag))} <b>${fmt(g.n)}</b></span>`).join("")}</div>` : ""}</div>
  ${p.signals.length ? `<div class="dsec"><h4>${term("sign", "Warning signs")} it fired</h4>${p.signals.map((g) => `<div class="sigrow"><span class="sigdot" style="background:${FAMILY[g.family]?.color}"></span><b>${esc(g.name)}</b> <span class="muted small">${esc(g.time)} UTC · ${pct(g.harm_share_after)} of the harm still to come</span>${g.record ? " " + ent.rec(g.record) : ""}<div class="small muted">${richText(g.why)}</div></div>`).join("")}</div>` : ""}
  <div class="dsec two"><div><h4>Sends ${term("message", "messages")} to</h4>${p.sends_to.length ? hbars(p.sends_to.map((x) => ({ label: ent.actor(x.actor), value: x.n, color: ACCENT }))) + more(p.sends_to.reduce((a, x) => a + x.n, 0), p.sent, "messages (the busiest partners)") : '<p class="muted small">nobody</p>'}</div>
    <div><h4>Hears from</h4>${p.hears_from.length ? hbars(p.hears_from.map((x) => ({ label: ent.actor(x.actor), value: x.n, color: C.actor }))) + more(p.hears_from.reduce((a, x) => a + x.n, 0), p.received, "messages (the busiest partners)") : '<p class="muted small">nobody</p>'}</div></div>
  <div class="dsec"><h4>${term("place", "Places")} it used (${fmt(p.places_total)})</h4>${p.places.length ? `<div class="plist">${p.places.map((r) => `<div>${ent.place(r.channel)} <span class="muted small">${[["write", r.write], ["read", r.read], ["post", r.post]].filter(([, n]) => n).map(([k, n]) => `${fmt(n)} ${k}${n === 1 ? "" : "s"}`).join(", ")}</span></div>`).join("")}</div>` + more(p.places.length, p.places_total, "places, busiest first") : '<p class="muted small">none</p>'}</div>
  ${p.programs_started.length ? `<div class="dsec"><h4>${term("program", "Programs")} it ran first that others reused</h4>${table(["first run", "actors who ran it", "what it does"], p.programs_started.map((x) => [ent.rec(x.record), fmt(x.actors), esc(progWhat(x.what))]))}${more(p.programs_started.length, p.programs_started_total, "programs")}</div>` : ""}
  ${p.programs_adopted.length ? `<div class="dsec"><h4>${term("program", "Programs")} it reused from others</h4>${table(["its first run", "first run by", "after", "what it does"], p.programs_adopted.map((x) => [ent.rec(x.record), ent.actor(x.source), hoursWord(x.hours_after_source), esc(progWhat(x.what))]))}${more(p.programs_adopted.length, p.programs_adopted_total, "programs")}</div>` : ""}
  ${p.carried.length ? `<div class="dsec"><h4>${term("carried", "Carried tokens")}</h4>${table(["carrier", "token", "records", "evidence"], p.carried.map((c) => [ent.actor(c.from), ent.actor(c.to), fmt(c.records), c.evidence.map(ent.rec).join(" ")]))}</div>` : ""}
  ${p.seen_then_used.length ? `<div class="dsec"><h4>${term("seen_used", "Seen as data before its first use")}</h4>${table(["first seen", "record", "first used", "lead"], p.seen_then_used.map((x) => [esc(x.first_seen), ent.rec(x.first_seen_id), esc(x.first_used), hoursWord(x.lead_hours)]))}</div>` : ""}
  <div class="dsec"><p class="small">First record ${ent.rec(p.first_record)} · last ${ent.rec(p.last_record)}</p><button type="button" class="primary" onclick="askAbout(null, ${esc(JSON.stringify("Profile the actor " + p.actor + ": what it did, who it exchanged messages with, which programs it shared, and which warning signs it fired."))})">Ask the AI about this actor</button></div>`;
}
function placeDossier(p) {
  const r = p.row || {};
  const series = p.hourly.map(([h, c]) => [h, Object.values(c).reduce((a, b) => a + b, 0)]);
  const wseries = p.hourly.map(([h, c]) => [h, (c.write || 0) + (c.post || 0)]);
  return `
  <div class="dhead"><div><span class="ent place big" data-noclick data-place="${esc(p.channel)}"><i></i>${esc(placeLabel(p.channel))}</span> <span class="badge">${esc(placeType(p.type))}</span>${p.merged ? ' <span class="badge warnb">may merge several places</span>' : ""}</div>
    <div class="muted small"><code>${esc(p.channel)}</code></div></div>
  <div class="dsec">${spark(series, { w: 420, h: 40, color: C.place })}${spark(wseries, { w: 420, h: 18, color: HARM })}${sparkAxis(420)}
    <div class="small muted">Purple: every ${term("write", "read and write")} per hour; orange: writes only.</div>
    <div class="comp">${[["writes", r.writes], ["reads", r.reads], ["writers", p.writers.length], ["readers", p.readers.length], ["messages", p.messages_total], ["overwrites", p.overwrites]].map(([k, v]) => `<div class="${v ? "" : "zero"}"><b>${fmt(v || 0)}</b><span>${k}</span></div>`).join("")}</div>
    ${r.never_read ? '<p class="warn small">Written, but never read by another actor: a message nobody picked up, or a read the patterns could not see.</p>' : ""}</div>
  <div class="dsec two"><div><h4>Writers</h4>${p.writers.length ? hbars(p.writers.slice(0, 12).map((x) => ({ label: ent.actor(x.actor), value: x.n, color: HARM }))) : '<p class="muted small">none</p>'}</div>
    <div><h4>Readers</h4>${p.readers.length ? hbars(p.readers.slice(0, 12).map((x) => ({ label: ent.actor(x.actor), value: x.n, color: ACCENT }))) : '<p class="muted small">none</p>'}</div></div>
  <div class="dsec"><h4>${term("message", "Messages")} through it (${fmt(p.messages_total)})</h4>${p.messages.length ? p.messages.slice(0, 60).map((m) => `<div class="mline">${ent.actor(m.from)} wrote in ${ent.rec(m.write_id)} <span class="muted">${esc(m.write_time || "")}</span> → ${ent.actor(m.to)} read in ${ent.rec(m.read_id)} <span class="muted">${esc(m.read_time || "")} (${hoursWord(m.latency_h)} later)</span> <span class="how">${esc(m.how || "")}</span></div>`).join("") + more(Math.min(60, p.messages.length), p.messages_total, "messages") : `<p class="muted small">none${(p.row?.reads || 0) ? ": no write by a different actor came before its reads" : ""}</p>`}</div>
  <div class="dsec"><h4>Every operation (${fmt(p.ops_total)})</h4>${table(["time", "op", "actor", "record"], p.ops.slice(0, 200).map((o) => [esc(o.time || "–"), `<span class="op ${o.op}">${esc(o.op)}</span>`, ent.actor(o.actor), ent.rec(o.record)]))}${p.ops_total > 200 ? `<p class="small muted">First 200 of ${fmt(p.ops_total)}.</p>` : ""}</div>`;
}

// ------------------------------------------------------------------ tabs
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) goTab(b.dataset.tab);
});
S.scroll = {};
function goTab(tab) {
  if (S.tab && $("left")) S.scroll[S.tab] = $("left").scrollTop;
  S.tab = tab;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === tab));
  render();
}
function goEvents(filters) {
  Object.assign(S.ev, { q: "", kind: "", intent: "", tag: "", actor: "", hour: "", channels: false }, filters, { offset: 0 });
  goTab("events");
}
function render() {
  const el = $("left");
  if (!S.summary) return;
  const f = VIEWS[S.tab];
  el.innerHTML = "";
  el.scrollTop = 0;
  if (!f) { el.innerHTML = `<p class="warn">No view named ${esc(S.tab)}.</p>`; return; }
  const back = S.scroll?.[S.tab];
  Promise.resolve(f(el, S.summary)).then(() => { if (back) setTimeout(() => { if ($("left").scrollHeight > back) $("left").scrollTop = back; }, 400); })
    .catch((e) => { el.insertAdjacentHTML("beforeend", `<p class="warn">${esc(e.message)}</p>`); console.error(e); });
}
function tabCounts(s) {
  const f = s.flow, T = s.list_totals || {};
  const counts = { network: f.named_actor_pairs, channels: f.channels, spread: T.content_spread, events: s.records };   // early: set from the replay below
  const what = { network: "sender-receiver pairs between named actors", channels: "places", spread: "programs run by two or more named actors", early: "warning signs", events: "records" };
  document.querySelectorAll("#tabs button").forEach((b) => {
    const n = counts[b.dataset.tab];
    let c = b.querySelector(".cnt");
    if (n == null) { if (c) c.remove(); return; }
    if (!c) { c = document.createElement("span"); c.className = "cnt"; b.appendChild(c); }
    c.textContent = n >= 10000 ? Math.round(n / 1000) + "k" : fmt(n);
    c.title = `${fmt(n)} ${what[b.dataset.tab] || ""}`;
  });
  // the early-flag count is every warning sign the replay tracks, which the summary does not carry
  cached("/api/sim").then((sim) => {
    const b = document.querySelector('#tabs button[data-tab="early"]');
    if (!b) return;
    let c = b.querySelector(".cnt");
    if (!c) { c = document.createElement("span"); c.className = "cnt"; b.appendChild(c); }
    c.textContent = fmt(sim.signals.length); c.title = `${fmt(sim.signals.length)} warning signs`;
  }).catch(() => {});
}

// ------------------------------------------------------------------ top bar
function status(t, bad) { const el = $("status"); el.textContent = t || ""; el.className = "status" + (bad ? " bad" : t ? " busy" : ""); }
function setSummary(s) {
  S.summary = s;
  S.conv = null;
  S.cache = new Map();
  INS.stack = [];
  S.ev = { q: "", kind: "", intent: "", tag: "", actor: "", hour: "", channels: false, offset: 0 };
  const sp = s.time_test?.span;
  $("dsname").innerHTML = `<b title="${esc(s.name)}">${esc(s.name)}</b><span title="${esc(`${fmt(s.records)} records · pack: ${s.pack}${s.pack_choice ? " (picked automatically: " + s.pack_choice.why + ")" : ""}`)}">${fmt(s.records)} records · ${esc(s.pack)}${s.pack_choice ? " (auto)" : ""}</span>`;
  $("ribbon").innerHTML = [
    sp ? [term("dated", "span"), (() => { const a = toTime(sp[0]), b = toTime(sp[1]); const da = dayWord(a), db = dayWord(b); return da.split(" ")[0] === db.split(" ")[0] ? `${da}–${db.split(" ")[1]}` : `${da}–${db}`; })()] : null,
    [term("dated", "dated"), pct(s.timed / s.records)],
    [term("named", "named actors"), fmt(s.actions?.named_actors ?? Object.entries(s.actor_kinds || {}).filter(([k]) => k !== "run").reduce((a, [, v]) => a + v, 0))],
    [term("place", "places"), fmt(s.flow.channels)],
    [term("message", "messages"), fmt(s.flow.deliveries)],
  ].filter(Boolean).map(([k, v]) => `<span><b>${v}</b>${k}</span>`).join("");
  $("loadpanel").hidden = true;
  tabCounts(s);
  render();
}

// one search box for records, actors and places
(() => {
  const box = $("omni"), out = $("omniout");
  let t = null, seq = 0;
  const close = () => { out.hidden = true; };
  box.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = box.value.trim(), my = ++seq;
      if (!q || !S.summary) { close(); return; }
      try {
        const r = await api("/api/search?q=" + encodeURIComponent(q));
        if (my !== seq) return;
        const sec = (title, items) => items.length ? `<div class="oh">${title}</div>${items.join("")}` : "";
        out.innerHTML = sec("Actors", r.actors.map((a) => `<div class="oi" data-actor="${esc(a.actor)}" data-nocard><span class="ent actor${a.kind === "run" ? " run" : ""}"><i></i>${esc(short(a.actor))}</span><span class="muted">${esc({ token: "token", token_via_thread: "token via thread", handle: "self-chosen name", run: "anonymous run", named: "actor field" }[a.kind] || a.kind)} · ${fmt(a.records)} records</span></div>`)) +
          sec("Places", r.places.map((p) => `<div class="oi" data-place="${esc(p.channel)}" data-nocard><span class="ent place wrap"><i></i>${esc(placeLabel(p.channel))}</span><span class="muted">${p.messages ? plural(p.messages, "message") : plural(p.ops, "operation")}</span></div>`)) +
          sec("Records", r.records.map((x) => `<div class="oi" data-id="${esc(x.id)}" data-nocard><span class="ent rec">${esc(x.id)}</span><span class="muted">${esc(x.kind)} · ${esc(short(x.actor))} · ${esc(x.time || "no time")}</span></div>`)) +
          `<div class="oi" data-search="${esc(q)}"><span>Search all record text for “${esc(q)}”</span></div>`;
        out.hidden = false;
        out.querySelector("[data-search]").addEventListener("click", () => { close(); goEvents({ q }); });
      } catch (e) { out.innerHTML = `<div class="oh">${esc(e.message)}</div>`; out.hidden = false; }
    }, 180);
  });
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") { const first = out.querySelector(".oi"); if (first) first.click(); } if (e.key === "Escape") close(); });
  out.addEventListener("click", () => setTimeout(close, 0));
  document.addEventListener("click", (e) => { if (!e.target.closest(".omni")) close(); });
})();

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  ["loadpanel", "glossary", "omniout"].forEach((id) => { if ($(id)) $(id).hidden = true; });
  if (HC.el) HC.el.hidden = true;
});
$("glossbtn").addEventListener("click", () => { const g = $("glossary"); if (g && !g.hidden) g.hidden = true; else openGlossary(); });
$("loadbtn").addEventListener("click", () => { $("loadpanel").hidden = !$("loadpanel").hidden; });
document.addEventListener("click", (e) => {
  if (!e.target.closest("#loadpanel,#loadbtn") && $("loadpanel")) $("loadpanel").hidden = true;
  if (!e.target.closest("#glossary,#glossbtn,[data-term]") && $("glossary")) $("glossary").hidden = true;
});
const DATA_FILE = /\.(csv|tsv|jsonl|json|txt|log)$/i;
$("upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const chosen = [...$("folder").files, ...$("file").files];
  // a folder can hold anything: send only trace files, and say what was left out
  const files = chosen.filter((f) => DATA_FILE.test(f.name) && !f.name.startsWith("."));
  const left = chosen.filter((f) => !files.includes(f) && !f.name.startsWith("."));
  const leftNote = left.length ? ` Left out ${plural(left.length, "file")} that are not traces (${left.slice(0, 4).map((f) => f.name).join(", ")}${left.length > 4 ? ", …" : ""}).` : "";
  if (!files.length) {
    status(chosen.length ? `No trace files here: use .jsonl, .json, .csv, .tsv, or a plain-text log (.txt, .log).${leftNote}` : "Choose a file or a folder first.", true);
    return;
  }
  const map = {};
  document.querySelectorAll(".mapgrid input").forEach((i) => { if (i.value.trim()) map[i.dataset.role] = i.value.trim(); });
  $("analyze").disabled = true;
  const t0 = performance.now();
  let current = "";
  try {
    let r;
    if (files.length === 1) {
      const f = files[0];
      current = f.name;
      status(`Uploading and analyzing ${f.name} (${(f.size / 1e6).toFixed(1)} MB). Large files take a minute…`);
      r = await api("/api/upload?" + new URLSearchParams({ filename: f.name, pack: $("pack").value, map: JSON.stringify(map) }), { method: "POST", body: f });
    } else {
      const batch = Math.random().toString(36).slice(2, 12);
      const skipped = [];
      for (const [i, f] of files.entries()) {
        current = f.name;
        status(`Uploading ${i + 1} of ${files.length}: ${f.name} (${(f.size / 1e6).toFixed(1)} MB)…`);
        const res = await api("/api/stage?" + new URLSearchParams({ batch, filename: f.name }), { method: "POST", body: f });
        if (res.skipped) skipped.push(res.skipped);
      }
      current = "";
      status(`Analyzing ${files.length - skipped.length} files together…`);
      const folder = files[0].webkitRelativePath ? files[0].webkitRelativePath.split("/")[0] : `${files.length} files`;
      r = await api("/api/analyze?" + new URLSearchParams({ batch, pack: $("pack").value, map: JSON.stringify(map), name: folder }), { method: "POST" });
    }
    setSummary(r.summary);
    const sk = r.summary.read_report?.skipped_files || [];
    status(`Analyzed in ${((performance.now() - t0) / 1000).toFixed(0)} s.${leftNote}${sk.length ? ` Set aside ${plural(sk.length, "reference table")} (rows with no time and no parent): see the overview.` : ""}`);
    setTimeout(() => status(""), 12000);
  } catch (e) {
    const net = /fetch|network|reset/i.test(e.message);
    status(`${current ? `Could not upload ${current}: ` : ""}${net ? "the connection to the app dropped. Is the app still running (python3 -m agenttrace serve)?" : e.message}`, true);
  }
  finally { $("analyze").disabled = false; }
});

// deep links: #tab=early&hour=2026-07-11T06&rec=R0006786&actor=...&place=...&scroll=600&ai=wide
// open a view, a record, an actor or a place straight from the address (also used to capture figures)
function deepLink() {
  return Object.fromEntries(new URLSearchParams(location.hash.replace(/^#/, "")).entries());
}
function openDeepLink() {
  const d = deepLink();
  if (d.ai === "wide") document.body.classList.add("aiwide");
  if (d.a && d.b) { S.conv = { a: d.a, b: d.b }; if (!d.tab) d.tab = "network"; }   // a conversation link
  if (d.tab && VIEWS[d.tab]) goTab(d.tab);
  if (d.rec) selectEvent(d.rec);
  else if (d.actor) inspectActor(d.actor);
  else if (d.place) inspectPlace(d.place);
  if (d.scroll) setTimeout(() => { $("left").scrollTop = +d.scroll; }, 2500);
}

async function init() {
  const p = await api("/api/packs");
  $("pack").innerHTML = p.packs.map((x) => `<option value="${esc(x.file)}" title="${esc(x.description)}"${x.file === "auto" ? " selected" : ""}>${esc(x.name)}</option>`).join("");
  if (window.initAI) initAI(p.ai_defaults);
  status("Loading the analysis…");
  const st = await api("/api/state");
  status("");
  if (st.loaded) { setSummary(st.summary); openDeepLink(); }
  else if (st.busy) status("An analysis is running on the server…");
  else $("loadpanel").hidden = false;
}
window.addEventListener("load", () => init().catch((e) => status(e.message, true)));

// simple labelled bars (kept for views that list counts)
function bars(entries, total) {
  return hbars(entries.map(([k, v]) => ({ label: esc(human(k)), value: v, color: intentColor(k) })), { total });
}

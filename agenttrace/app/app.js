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
  $("pack").innerHTML = p.packs.map((x) => `<option value="${esc(x.file)}" title="${esc(x.description)}"${x.file === "auto" ? " selected" : ""}>${esc(x.name)}</option>`).join("");
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
  S.conv = null;
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
// a table that starts with the rows the summary carries and can page through the whole list on the server
function listView(host, name, headers, rowFn, rows, total, onRow) {
  if (!host) return;
  const st = { rows: rows.slice(), total: total ?? rows.length, q: "", full: false };
  const load = async (append) => {
    const r = await api(`/api/list?name=${encodeURIComponent(name)}&q=${encodeURIComponent(st.q)}&offset=${append ? st.rows.length : 0}&limit=200`);
    st.rows = append ? st.rows.concat(r.rows) : r.rows; st.total = r.total; st.full = true; draw();
  };
  const draw = () => {
    const filter = st.total > 12 || st.q ? `<p class="small listbar"><input class="lq" placeholder="Filter all ${fmt(st.total)} rows" value="${esc(st.q)}"> <span class="muted">${st.rows.length < st.total ? `showing ${fmt(st.rows.length)} of ${fmt(st.total)}` : `${fmt(st.total)} row${st.total === 1 ? "" : "s"}`}</span></p>` : "";
    host.innerHTML = filter + table(headers, st.rows.map(rowFn), !!onRow) + (st.rows.length < st.total ? `<button type="button" class="lmore">Show ${st.full ? "200 more" : `all ${fmt(st.total)}`}</button>` : "");
    if (onRow) bindRows(host, (i) => onRow(st.rows[i]));
    const more = host.querySelector(".lmore"); if (more) more.addEventListener("click", () => load(st.full));
    const q = host.querySelector(".lq");
    if (q) { let t = null; q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { st.q = q.value.trim(); load(false).then(() => { const n = host.querySelector(".lq"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }); }, 250); }); }
  };
  draw();
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
  <p>Pack: <b>${esc(s.pack)}</b>${s.pack_choice ? ` <span class="muted">(picked automatically: ${esc(s.pack_choice.why)}; pick another pack above to override)</span>` : ""}.</p>
  ${(s.shared_identities || []).length ? `<p>Shared keys, never counted as actors: ${s.shared_identities.map((t) => `<code>${esc(short(t))}</code>`).join(", ")}${(s.auto_shared || []).length ? ` <span class="muted">(found automatically: ${s.auto_shared.map((a) => `${esc(short(a.identity))} is used in ${pct(a.share_of_runs)} of the runs that carry a token`).join("; ")})</span>` : ""}.</p>` : ""}
  <p>Time: ${fmt(s.timed)} of ${fmt(s.records)} records have a time (${Object.entries(s.time_test.source || {}).map(([k, v]) => `${esc(k.replace(/_/g, " "))} ${fmt(v)}`).join(", ") || "none"}). ${s.time_test.span ? `Span ${esc(s.time_test.span[0])} to ${esc(s.time_test.span[1])} UTC.` : ""}</p>
  ${table(["kind", "first", "last", "records", "timestamps", "rank corr.", "timed", "median err (h)"],
    (s.time_test.blocks || []).map((b) => [esc(b.kind), idlink(b.first_id), idlink(b.last_id), fmt(b.records), fmt(b.timestamp_points), esc(b.spearman), b.timed ? "yes" : `no${b.rejected ? " (" + esc(b.rejected) + ")" : ""}`, esc(b.fit_error_hours_median ?? "")]))}
  <p>Identity: ${s.identity_test.tokens_used_5_plus ? `${s.identity_test.with_one_role_90pct} of ${s.identity_test.tokens_used_5_plus} identity tokens used 5+ times keep one role in at least 90% of uses.` : "no identity tokens repeat enough to test."}</p>
  <h2>Identities by activity</h2>
  <p class="muted small">Every identity the tool found, busiest first. Click one to list its events.</p>
  <div id="idlist"></div>
  <h2>What the records do</h2>
  ${bars(Object.entries(s.intents), Object.values(s.intents).reduce((a, b) => a + b, 0))}
  <h2>Evidence tags</h2>
  ${bars(Object.entries(s.evidence_tags).slice(0, 15), s.records)}
  <p class="muted small">Context tags (not evidence): ${Object.keys(s.context_tags).map(esc).join(", ") || "none"}.</p>`;
  listView($("idlist"), "identities", ["identity", "uses", "first", "last", "roles", "mostly"],
    (i) => [`<code>${esc(short(i.identity))}</code>`, fmt(i.uses), esc(i.first || "–"), esc(i.last || "–"), esc(Object.keys(i.roles || {}).join(", ")), esc(Object.keys(i.intents || {}).slice(0, 3).join(", "))],
    s.identities.slice(0, 15), s.list_totals?.identities ?? s.identities_total, (i) => goEvents({ actor: i.identity }));
}

// ------------------------------------------------------------------ network (layered layout)
function network(el, s) {
  const pairs = s.flow.top_pairs;
  const sizes = [...new Set([15, 30, 60].map((n) => Math.min(n, pairs.length)))];
  const chosen = Math.min(30, pairs.length);
  el.innerHTML = `<h2>Who talked to whom</h2>
  <p class="muted small">Named actors only. An arrow runs from the actor who wrote to a place to a different actor who later read it; thicker means more messages. Actors that only send are on the left, actors that only receive are on the right, and actors that do both are in the middle. Each shaded band is one group of connected actors. The number in a box is that actor's messages in the pairs shown. Hover a box to pick out its messages; click it to list its events. <b>Click an arrow to open the whole conversation</b> between the two actors, with every record id.</p>
  <p class="small">Show the <select id="netN">${sizes.map((n) => `<option value="${n}"${n === chosen ? " selected" : ""}>${n}</option>`).join("")}</select> busiest sender-receiver pairs (of ${fmt(s.flow.named_actor_pairs)}).</p>
  <div id="net"></div>
  <div id="conv"></div>
  <h3>All sender-receiver pairs</h3>
  <p class="small"><input id="pairQ" placeholder="Find an actor, e.g. cred 169" style="width:220px"> <label class="muted"><input type="checkbox" id="pairAll"> include anonymous runs</label> <span id="pairCount" class="muted"></span></p>
  <p class="muted small">Click a pair to open its conversation. "Back" is how many messages went the other way.</p>
  <div id="pairs"></div>
  <h3>One identity carrying another's token</h3>
  <p class="muted small">A record that authenticates as one identity and also holds another identity's token, before that token's own first use.</p>
  <div id="carriedList"></div>
  <h3>Two identities using one place</h3>
  <p class="muted small">A named place (a controller, a command channel, a board) used by two identities. "Separately" means in different records.</p>
  <div id="sharedList"></div>
  <h3>Replies between actors</h3>
  <div id="replyList"></div>`;
  const T = s.list_totals || {};
  listView($("carriedList"), "carried_edges", ["carrier", "token carried", "records", "evidence"],
    (e) => [`<code>${esc(short(e.from))}</code>`, `<code>${esc(short(e.to))}</code>`, fmt(e.records), (e.evidence || []).map(idlink).join(", ")], s.carried_edges.slice(0, 10), T.carried_edges);
  listView($("sharedList"), "shared_places", ["place", "identities", "first use", "second use", "separately"],
    (p) => [`<code>${esc(p.place)}</code>`, p.identities.map((x) => `<code>${esc(short(x))}</code>`).join(" "), `${esc(p.first)} ${idlink(p.first_id)}`, `${esc(p.second)} ${idlink(p.second_id)}`, p.same_record ? "no, same record" : "yes"], s.shared_places.slice(0, 10), T.shared_places);
  listView($("replyList"), "reply_edges", ["from", "to", "replies"],
    (r) => [`<code>${esc(short(r.from))}</code>`, `<code>${esc(short(r.to))}</code>`, fmt(r.replies)], s.reply_edges.slice(0, 10).map((r) => ({ from: r[0], to: r[1], replies: r[2] })), T.reply_edges);
  pairList();
  let qt = null;
  $("pairQ").addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(() => pairList(), 200); });
  $("pairAll").addEventListener("change", () => pairList());
  if (S.conv) openConversation(S.conv.a, S.conv.b, false);
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

// every pair, searchable, a page at a time
async function pairList(offset = 0) {
  const box = $("pairs");
  if (!box) return;
  const q = $("pairQ").value.trim(), all = $("pairAll").checked;
  const r = await api(`/api/pairs?q=${encodeURIComponent(q)}${all ? "&all=1" : ""}&offset=${offset}&limit=50`);
  if ($("pairQ").value.trim() !== q) return;   // a newer search is on its way
  $("pairCount").textContent = `${fmt(r.total)} pair${r.total === 1 ? "" : "s"}`;
  const rows = r.rows.map((p) => `<tr class="click" data-a="${esc(p.from)}" data-b="${esc(p.to)}"><td><code>${esc(short(p.from))}</code></td><td><code>${esc(short(p.to))}</code></td><td class="n">${fmt(p.messages)}</td><td class="n">${fmt(p.back)}</td><td class="n">${fmt(p.channels)}</td><td>${esc(p.first)}</td><td>${esc(p.last)}</td></tr>`).join("");
  const head = "<tr><th>sender</th><th>receiver</th><th>messages</th><th>back</th><th>places</th><th>first</th><th>last</th></tr>";
  if (offset === 0) box.innerHTML = r.total ? `<table><thead>${head}</thead><tbody>${rows}</tbody></table><p id="pairMore"></p>` : '<p class="muted">None found.</p>';
  else box.querySelector("tbody").insertAdjacentHTML("beforeend", rows);
  box.querySelectorAll("tr.click:not([data-bound])").forEach((tr) => { tr.dataset.bound = 1; tr.addEventListener("click", () => openConversation(tr.dataset.a, tr.dataset.b)); });
  const shown = offset + r.rows.length, more = $("pairMore");
  if (more) more.innerHTML = shown < r.total ? `<button id="pairMoreBtn">Show ${fmt(Math.min(50, r.total - shown))} more (${fmt(shown)} of ${fmt(r.total)} shown)</button>` : "";
  if ($("pairMoreBtn")) $("pairMoreBtn").addEventListener("click", () => pairList(shown));
}

// the whole conversation between two actors: every message both ways, in time order, with record ids
async function openConversation(a, b, scroll = true) {
  const box = $("conv");
  if (!box) return;
  S.conv = { a, b };
  box.innerHTML = '<p class="muted">Loading the conversation…</p>';
  const c = await api(`/api/conversation?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const PAGE = 200;
  const item = (it) => {
    const side = it.kind === "overwrite" ? "over" : it.from === a ? "left" : "right";
    const lines = it.lines.length ? `<ul class="lines">${it.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : "";
    return `<div class="msg ${side}">
      <div class="mhead"><b>${esc(short(it.from))} → ${esc(short(it.to))}</b>${it.kind === "overwrite" ? ' <span class="tag">overwrite, not a message</span>' : ""}${it.merged_place ? ' <span class="tag" title="The redaction kept only the owner of this place, so it may join several places: the write and the read may not be the same message.">place may be merged by redaction</span>' : ""} · <code>${esc(it.channel)}</code> · <span class="muted">${esc(it.how || "")}</span></div>
      <div class="mrow"><span class="lab">wrote</span> ${idlink(it.write_id)} <span class="muted">${esc(it.write_time || "time unknown")}</span></div>
      <div class="snip">${esc(it.write_text)}</div>
      <div class="mrow"><span class="lab">${it.kind === "overwrite" ? "replaced in" : "read in"}</span> ${idlink(it.read_id)} <span class="muted">${esc(it.read_time || "time unknown")}${it.latency_h != null ? ` · ${esc(it.latency_h)} h later` : ""}</span></div>
      <div class="snip">${esc(it.read_text)}</div>
      ${lines ? `<div class="mrow"><span class="lab">${it.kind === "overwrite" ? "lines dropped" : "lines kept"}</span></div>${lines}` : ""}
    </div>`;
  };
  box.innerHTML = `<div class="conv">
    <div class="convhead">
      <div><b>${esc(short(a))} ↔ ${esc(short(b))}</b><br><span class="muted small">${fmt(c.a_to_b)} message${c.a_to_b === 1 ? "" : "s"} from ${esc(short(a))} (left), ${fmt(c.b_to_a)} from ${esc(short(b))} (right)${c.overwrites ? `, ${fmt(c.overwrites)} overwrite${c.overwrites === 1 ? "" : "s"} (centre)` : ""}${c.on_merged_places ? `; ${fmt(c.on_merged_places)} on places the redaction may have merged` : ""} · ${fmt(c.places.length)} place${c.places.length === 1 ? "" : "s"} · ${esc(c.first || "")} to ${esc(c.last || "")}</span></div>
      <div class="convbtns"><button id="convAsk">Ask the AI about this</button> <button id="convCopy">Copy ${fmt(c.record_ids.length)} record ids</button> <button id="convClose">Close</button></div>
    </div>
    <details class="convids"><summary>All ${fmt(c.record_ids.length)} record ids, in order</summary><div>${c.record_ids.map(idlink).join(" ")}</div></details>
    <details class="convids"><summary>${fmt(c.places.length)} place${c.places.length === 1 ? "" : "s"}</summary><div>${c.places.map((p) => `<code>${esc(p)}</code>`).join(" ")}</div></details>
    <div class="thread" id="thread">${c.items.slice(0, PAGE).map(item).join("")}</div>
    ${c.items.length > PAGE ? `<button id="convMore">Show all ${fmt(c.items.length)}</button>` : ""}
    ${c.truncated ? `<p class="muted small">Showing the first ${fmt(c.items.length)} of ${fmt(c.total)}.</p>` : ""}
  </div>`;
  if ($("convMore")) $("convMore").addEventListener("click", () => { $("thread").innerHTML = c.items.map(item).join(""); $("convMore").remove(); });
  $("convClose").addEventListener("click", () => { S.conv = null; box.innerHTML = ""; });
  $("convCopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(c.record_ids.join("\n")); $("convCopy").textContent = "Copied"; }
    catch { $("convCopy").textContent = "Copy failed"; }
  });
  $("convAsk").addEventListener("click", () => {
    $("q").value = `Explain the conversation between ${a} and ${b}: what passed between them, in what order, through which places, and what it suggests. Cite record ids.`;
    $("q").focus();
  });
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
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
    const tip = `${esc(short(p.from))} → ${esc(short(p.to))}: ${fmt(p.deliveries)} message${p.deliveries === 1 ? "" : "s"} over ${fmt(p.channels)} place${p.channels === 1 ? "" : "s"}, first ${esc(p.first)}. Click to open the conversation.`;
    svg += `<path class="edge" data-a="${esc(p.from)}" data-b="${esc(p.to)}" d="${d}" fill="none" stroke="#2f6fb3" stroke-width="${width(p.deliveries)}" marker-end="url(#ah)"/>`;
    // a wider invisible copy, so a thin arrow is easy to hover and click
    svg += `<path class="edgehit" data-a="${esc(p.from)}" data-b="${esc(p.to)}" d="${d}" fill="none" stroke="transparent" stroke-width="12"><title>${tip}</title></path>`;
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
  el.querySelectorAll(".edgehit").forEach((hit) => {
    const { a, b } = hit.dataset;
    hit.addEventListener("mouseenter", () => light((e) => e.dataset.a === a && e.dataset.b === b));
    hit.addEventListener("mouseleave", clear);
    hit.addEventListener("click", () => openConversation(a, b));
  });
}

// ------------------------------------------------------------------ timeline
function timeline(el, s) {
  const hours = Object.keys(s.activity_by_hour).sort();
  const tot = Object.fromEntries(hours.map((h) => [h, Object.values(s.activity_by_hour[h]).reduce((a, b) => a + b, 0)]));
  const peak = hours.reduce((a, h) => (tot[h] > (tot[a] || 0) ? h : a), hours[0]);
  el.innerHTML = `<h2>What the agents did, hour by hour</h2>
  ${peak ? `<p class="lead">The busiest hour was ${esc(dayWord(toTime(peak + ":00")))} ${esc(peak.slice(11))}:00 UTC, with ${fmt(tot[peak])} timed actions.</p>` : ""}
  <p class="muted small">Timed actions only, stacked by what the code does. The numbered marks along the top show when each warning sign first fired (blue: actors working together; grey: a single actor). Click a bar to list that hour's events.</p>
  <div id="tl"></div><div id="tlkey"></div>`;
  if (!hours.length) { $("tl").innerHTML = '<p class="muted">No timed records, so no timeline.</p>'; return; }
  const draw = () => drawTimeline($("tl"), s, hours, tot);
  draw();
  if (window.ResizeObserver) { let w = $("tl").clientWidth; new ResizeObserver(() => { if ($("tl") && Math.abs($("tl").clientWidth - w) > 24) { w = $("tl").clientWidth; draw(); } }).observe($("tl")); }
}

function drawTimeline(host, s, hours, tot) {
  const intents = Object.entries(s.intents).sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const color = Object.fromEntries(intents.map((k, i) => [k, k === "other" ? "#c9cfd6" : PALETTE[i % PALETTE.length]]));
  const W = Math.max(380, host.clientWidth || 700), H = 300, x0 = 52, x1 = W - 12, yT = 40, yB = H - 30;
  const t0 = toTime(hours[0] + ":00"), t1 = toTime(hours.at(-1) + ":00") + 3600e3;
  const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0), bw = Math.max(1, (x1 - x0) / ((t1 - t0) / 3600e3) - 1);
  const mx = Math.max(...Object.values(tot)), Y = (v) => yB - v / mx * (yB - yT);
  const step = mx > 2000 ? 1000 : mx > 500 ? 250 : mx > 100 ? 50 : mx > 20 ? 10 : 2;
  let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Timed actions per hour, by what the code does">`;
  for (let v = 0; v <= mx; v += step) svg += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="${QUIET}">${fmt(v)}</text>`;
  hours.forEach((h) => {
    let y = yB; const x = X(toTime(h + ":00"));
    intents.forEach((it) => { const v = s.activity_by_hour[h][it] || 0; if (!v) return; const hh = v / mx * (yB - yT); y -= hh;
      svg += `<rect data-hour="${esc(h)}" x="${x}" y="${y}" width="${bw}" height="${hh}" fill="${color[it]}"><title>${esc(dayWord(toTime(h + ":00")))} ${esc(h.slice(11))}:00 · ${esc(it.replace(/_/g, " "))}: ${fmt(v)} (hour total ${fmt(tot[h])})</title></rect>`; });
  });
  svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
  timeTicks(t0, t1).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 5}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${yB + 19}" text-anchor="middle" font-size="11" fill="${QUIET}">${esc(k.label)}</text>`; });
  // warning signs: numbered marks on a strip above the bars, staggered when close
  const sigs = s.replay.map((r) => ({ ...r, ...signalInfo(r), t: sigTime(r.time) })).filter((r) => r.t != null && r.t >= t0 && r.t <= t1).sort((a, b) => a.t - b.t);
  let lastX = -99, lane = 0;
  sigs.forEach((r, i) => {
    const x = X(r.t); lane = x - lastX < 18 ? (lane + 1) % 2 : 0; lastX = x;
    const cy = 14 + lane * 15, c = r.joint ? ACCENT : SINGLE;
    svg += `<line x1="${x}" x2="${x}" y1="${cy + 7}" y2="${yB}" stroke="${c}" stroke-opacity=".35" stroke-dasharray="2 3"/><circle cx="${x}" cy="${cy}" r="7" fill="${c}"/><text x="${x}" y="${cy + 3.5}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#fff">${i + 1}<title>${esc(r.name)} · ${esc(r.time)}</title></text>`;
  });
  host.innerHTML = svg + "</svg>";
  host.querySelectorAll("rect[data-hour]").forEach((r) => r.addEventListener("click", () => goEvents({ hour: r.dataset.hour })));
  $("tlkey").innerHTML = `<div class="legend">${intents.map((k) => `<span><i style="background:${color[k]}"></i>${esc(k.replace(/_/g, " "))} <span class="muted">${fmt(s.intents[k])}</span></span>`).join("")}</div>` +
    `<h3>Warning signs on the chart</h3>` + table(["#", "sign", "kind", "first fired (UTC)", "harm still to come"], sigs.map((r, i) => [i + 1, esc(r.name), r.joint ? "actors together" : "single actor", esc(r.time), pct(r.harm_share_after)]));
}

// ------------------------------------------------------------------ channels
function channels(el, s) {
  const ct = Object.entries(s.flow.channel_types).sort((a, b) => b[1].deliveries - a[1].deliveries);
  const top = ct[0];
  el.innerHTML = `<h2>Places and how messages moved through them</h2>
  ${top ? `<p class="lead">${fmt(top[1].deliveries)} of ${fmt(s.flow.deliveries)} messages went through <b>${esc(top[0].replace(/_/g, " "))}</b> places.</p>` : ""}
  <p class="muted small">A place is anywhere one actor can leave something for another: a repository, a mailbox folder, a page, a thread. A message is a read of a place after a different actor wrote to it. Latency is the time from write to read.</p>
  ${table(["type", "places", "writes", "reads", "messages", "written, never read by another actor"], ct.map(([t, v]) => [esc(t), fmt(v.channels), fmt(v.writes), fmt(v.reads), fmt(v.deliveries), fmt(v.never_read)]))}
  <h3>Messages per place type</h3>${bars(ct.map(([t, v]) => [t, v.deliveries]))}
  <h3>Every place</h3><p class="muted small">Busiest first. Click a place to list the events that name it.</p>
  <div id="chanList"></div>`;
  listView($("chanList"), "channels", ["place", "writes", "reads", "writers", "readers", "messages", "overwrites", "median latency (h)", "first write"],
    (c) => [`<code>${esc(c.channel)}</code>`, fmt(c.writes), fmt(c.reads), fmt(c.writers), fmt(c.readers), fmt(c.deliveries), fmt(c.overwrites || 0), esc(c.median_latency_h ?? "–"), esc(c.first_write || "–")],
    s.top_channels.slice(0, 15), s.list_totals?.channels, (c) => goEvents({ q: c.channel.split(":").slice(1).join(":") }));
}

// ------------------------------------------------------------------ spread
function spread(el, s) {
  const all = s.content_spread, total = s.list_totals?.content_spread ?? all.length;
  const widest = all[0];
  el.innerHTML = `<h2>How information spread</h2>
  ${widest ? `<p class="lead">${fmt(total)} programs were run by more than one named actor. The widest, first run by ${esc(short(widest.source))}, reached ${fmt(widest.actors - 1)} more within ${hoursWord(Math.max(...widest.adopters.map((a) => a.hours_after_source)))}.</p>` : ""}
  <p class="muted small">Each lane is one program (the same code, with ids, numbers and hashes masked) run by several named actors. The dark dot is its first run; blue dots are later runs by other actors, in time order. Click a dot to trace that record.</p>
  <p class="small">Show <select id="laneN"><option>10</option><option selected>20</option><option>40</option></select> programs</p>
  <div id="lanes"></div>
  <h3>Every program run by several actors</h3><div id="spreadList"></div>
  <h3>Items first seen as data, then used as an identity</h3>
  <p class="muted small">A token that appears inside a record as data before any record uses it to authenticate: one way a credential moves between agents.</p>
  <div id="stuList"></div>`;
  const T = s.list_totals || {};
  listView($("spreadList"), "content_spread", ["first run by", "record", "time", "actors", "copies", "last adopter", "after"],
    (x) => { const last = x.adopters.at(-1) || {}; return [`<code>${esc(short(x.source))}</code>`, idlink(x.source_record), esc(x.source_time || "–"), fmt(x.actors), fmt(x.copies), `<code>${esc(short(last.actor || ""))}</code> ${idlink(last.record)}`, esc(last.hours_after_source != null ? hoursWord(last.hours_after_source) : "–")]; },
    all.slice(0, 10), total);
  listView($("stuList"), "seen_then_used", ["item", "first seen", "record", "kind", "first used", "uses", "lead"],
    (x) => [`<code>${esc(short(x.item))}</code>`, esc(x.first_seen), idlink(x.first_seen_id), esc(x.first_seen_kind), esc(x.first_used), fmt(x.uses), hoursWord(x.lead_hours)],
    s.seen_then_used.slice(0, 10), T.seen_then_used);
  if (!all.length) { $("lanes").innerHTML = '<p class="muted">No program moved between two named actors.</p>'; return; }
  const draw = () => drawLanes($("lanes"), all.slice(0, +$("laneN").value));
  $("laneN").addEventListener("change", draw);
  draw();
}
const hoursWord = (h) => (h == null ? "–" : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${(+h).toFixed(1)} h` : `${(h / 24).toFixed(1)} days`);

function drawLanes(host, items) {
  const W = Math.max(380, host.clientWidth || 700), row = 28, L = 150, R = 118, y0 = 30, H = y0 + items.length * row + 30;
  const pts = items.flatMap((x) => [toTime(x.source_time), ...x.adopters.map((a) => toTime(a.time))]).filter((t) => t != null);
  const t0 = Math.min(...pts), t1 = Math.max(...pts) + 1;
  const X = (t) => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
  const nameFont = '12px -apple-system, system-ui, sans-serif';
  let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="How programs spread between actors over time">`;
  timeTicks(t0, t1).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${y0 - 10}" y2="${H - 26}" stroke="${GRID}"/><text x="${X(k.t)}" y="${H - 10}" text-anchor="middle" font-size="11" fill="${QUIET}">${esc(k.label)}</text>`; });
  items.forEach((x, i) => {
    const y = y0 + i * row, sx = X(toTime(x.source_time));
    const label = fitName(`${short(x.source)}'s program`, L - 14, nameFont);
    svg += `<text x="4" y="${y + 4}" font-size="12" fill="${INK}"><title>${esc(x.source)}: ${x.copies} copies, ${x.actors} actors</title>${esc(label)}</text>`;
    const xs = x.adopters.map((a) => X(toTime(a.time)));
    svg += `<line x1="${sx}" x2="${Math.max(sx, ...xs)}" y1="${y}" y2="${y}" stroke="#bcd3ec" stroke-width="2"/>`;
    x.adopters.forEach((a, k) => { svg += `<circle data-ev="${esc(a.record)}" class="node" cx="${xs[k]}" cy="${y}" r="4.5" fill="${ACCENT}" stroke="#fff" stroke-width="1"><title>${esc(short(a.actor))} ran it ${hoursWord(a.hours_after_source)} after the first run (${esc(a.record)}, ${esc(a.time)})</title></circle>`; });
    svg += `<circle data-ev="${esc(x.source_record)}" class="node" cx="${sx}" cy="${y}" r="5.5" fill="${INK}" stroke="#fff" stroke-width="1.5"><title>first run by ${esc(short(x.source))} at ${esc(x.source_time)} (${esc(x.source_record)})</title></circle>`;
    const lastH = Math.max(0, ...x.adopters.map((a) => a.hours_after_source));
    svg += `<text x="${W - R + 10}" y="${y + 4}" font-size="11.5" fill="${QUIET}">${x.actors} actors, ${hoursWord(lastH)}</text>`;
  });
  svg += `<text x="${W - R + 10}" y="${y0 - 14}" font-size="11" fill="${QUIET}">reach, time</text></svg>`;
  host.innerHTML = svg;
}

// ------------------------------------------------------------------ chart helpers
const INK = "#1d2329", QUIET = "#66717d", GRID = "#e6e9ee", AXIS = "#9aa5b1", CURVE = "#b9bfb7", ACCENT = "#2f6fb3", SINGLE = "#4b5157";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const sigTime = (t) => toTime(String(t || "").replace("at or before ", ""));
const dayWord = (t) => { const d = new Date(t); return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`; };
const clock = (t) => new Date(t).toISOString().slice(11, 16);
// ticks at whole days, quarter days or hours, whichever gives 3 to 10 ticks across the span
function timeTicks(t0, t1) {
  const H = 3600e3, span = t1 - t0;
  const step = span > 3 * 24 * H ? 24 * H : span > 18 * H ? 6 * H : span > 4 * H ? H : 15 * 60e3;
  const out = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push({ t, label: step >= 24 * H || new Date(t).getUTCHours() === 0 && step > H ? dayWord(t) : `${dayWord(t)} ${clock(t)}` });
  return out;
}
// plain names for replay signals; packs name their own harms, the rest fall back to their words
const SIGNAL_NAMES = {
  registry_board: "Registry mailbox first used", docker_registry: "Docker registry first used",
  hf_dataset_write: "First Hugging Face dataset write", kubernetes_api: "Kubernetes API first called",
  cloud_metadata: "Cloud metadata first requested", probe_request: "First probe request",
  hides_page: "First page hidden", proxy_link: "First proxy link", recreated_after_delete: "Page recreated after a delete",
  runs_shell: "First shell command", handles_secrets: "First secret handled", sends_data: "First data sent out", deletes: "First delete",
};
function signalInfo(r) {
  const sig = String(r.signal);
  if (sig.startsWith("first message")) return { name: "First message between named actors", joint: true };
  if (sig.startsWith("coordination: one identity carries")) return { name: "One identity carries another's token", joint: true };
  if (sig.startsWith("coordination: two identities")) return { name: `Two identities share ${String(r.ref).length < 24 ? "place " + r.ref : "one place"}`, joint: true };
  if (sig.startsWith("coordination")) return { name: sig.replace(/^coordination:\s*/, "").replace(/^./, (c) => c.toUpperCase()), joint: true };
  if (sig.startsWith("spread")) return { name: "Token seen as data, then used", joint: false };
  const key = sig.replace(/^first:\s*/, "");
  return { name: SIGNAL_NAMES[key] || ("First " + key.replace(/_/g, " ")), joint: false };
}
// place two-line labels next to their dots without covering other labels, dots or the line
// Search the whole plot for each label's spot: no overlap with other labels, as little of the line
// and the dots covered as possible, and the shortest leader back to its dot. Works for any curve shape.
function placeLabels(items, box, avoidPts, maxLeader = 260) {
  const C = 5, nx = Math.ceil((box.x1 - box.x0) / C) + 1, ny = Math.ceil((box.y1 - box.y0) / C) + 1;
  const grid = new Uint8Array(nx * ny);
  avoidPts.forEach((p) => {
    const r = p.r || 3;
    for (let j = Math.floor((p.y - r - box.y0) / C); j <= Math.floor((p.y + r - box.y0) / C); j++)
      for (let i = Math.floor((p.x - r - box.x0) / C); i <= Math.floor((p.x + r - box.x0) / C); i++)
        if (i >= 0 && j >= 0 && i < nx && j < ny) grid[j * nx + i] = 1;
  });
  const P = new Int32Array((nx + 1) * (ny + 1));   // 2-D prefix sums: covered cells in any box in O(1)
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    P[(j + 1) * (nx + 1) + i + 1] = grid[j * nx + i] + P[j * (nx + 1) + i + 1] + P[(j + 1) * (nx + 1) + i] - P[j * (nx + 1) + i];
  const covered = (b) => {
    const i0 = Math.max(0, Math.floor((b.x - box.x0) / C)), i1 = Math.min(nx, Math.ceil((b.x + b.w - box.x0) / C));
    const j0 = Math.max(0, Math.floor((b.y - box.y0) / C)), j1 = Math.min(ny, Math.ceil((b.y + b.h - box.y0) / C));
    return P[j1 * (nx + 1) + i1] - P[j0 * (nx + 1) + i1] - P[j1 * (nx + 1) + i0] + P[j0 * (nx + 1) + i0];
  };
  const hits = (a, b, m = 4) => a.x < b.x + b.w + m && b.x < a.x + a.w + m && a.y < b.y + b.h + m && b.y < a.y + a.h + m;
  const crosses = (ax, ay, bx, by, r) => {   // does the segment a-b pass through rectangle r?
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
      // a label beside someone else's dot reads as that dot's label
      const near = anchors.filter((a) => a.it !== it && a.x > b.x - 16 && a.x < b.x + b.w + 16 && a.y > b.y - 16 && a.y < b.y + b.h + 16).length;
      const cross = placed.filter((p) => crosses(it.x, it.y, lx, ly, p)).length;
      const cost = covered(b) * 60 + d * 1.2 + (d > 12 ? 10 : 0) + near * 90 + cross * 160;
      if (!best || cost < best.cost) best = { b, cost };
    }
    if (best) { it.label = best.b; placed.push(best.b); }
  }
}

// ------------------------------------------------------------------ early flag
function early(el, s) {
  const rem = s.harm_remaining_by_hour;
  const fnd = s.flow.first_named_delivery;
  const sigs = s.replay.map((r) => ({ ...r }));
  if (fnd) sigs.push({ signal: "first message between named actors", time: fnd.read_time, ref: fnd.read_id, harm_share_after: s.flow.harm_share_after_first_named_delivery });
  sigs.forEach((r) => Object.assign(r, signalInfo(r), { t: sigTime(r.time) }));
  sigs.sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
  const joint = sigs.filter((r) => r.joint && r.harm_share_after != null), single = sigs.filter((r) => !r.joint && r.harm_share_after != null);
  const lo = (xs) => xs.length ? Math.min(...xs.map((r) => r.harm_share_after)) : null, hi = (xs) => xs.length ? Math.max(...xs.map((r) => r.harm_share_after)) : null;
  const finding = joint.length && single.length
    ? `Single-actor signs fired with ${pct(lo(single))} to ${pct(hi(single))} of the harm still to come; signs of actors working together with ${pct(lo(joint))} to ${pct(hi(joint))}.`
    : "Each dot is when a signal first fired; the higher it sits, the earlier the warning.";
  el.innerHTML = `<h2>Could it have been flagged early?</h2>
  <p class="lead">${esc(finding)}</p>
  <p class="muted small">The grey line is the share of timed harmful activity still to come, hour by hour (${fmt(s.harm_events_timed)} timed harmful actions). Each dot marks when a warning sign first fired: <b style="color:${ACCENT}">blue</b> for signs of two actors working together, <b style="color:${SINGLE}">dark grey</b> for single-actor signs. Click a dot to trace its record.</p>
  <div id="ef"></div>
  <h3>Every signal</h3>
  ${table(["signal", "kind", "first fired (UTC)", "harm still to come", "spread still to come", "record"], sigs.map((r) => [esc(r.name), r.joint ? "actors together" : "single actor", esc(r.time), pct(r.harm_share_after), pct(r.spread_share_after), /^[A-Za-z]\d{3,}$/.test(String(r.ref)) || /[~@]/.test(String(r.ref)) ? idlink(r.ref) : `<code>${esc(short(r.ref))}</code>`]))}`;
  if (!rem.length) { $("ef").innerHTML = '<p class="muted">No timed harmful activity, so no replay.</p>'; return; }
  drawEarly($("ef"), rem, sigs);
  if (window.ResizeObserver) { let w = $("ef").clientWidth; new ResizeObserver(() => { if ($("ef") && Math.abs($("ef").clientWidth - w) > 24) { w = $("ef").clientWidth; drawEarly($("ef"), rem, sigs); } }).observe($("ef")); }
}

function drawEarly(host, rem, sigs) {
  const W = Math.max(360, host.clientWidth || 700), H = Math.round(Math.min(480, Math.max(360, W * 0.62)));
  const x0 = 52, x1 = W - 16, yT = 18, yB = H - 34;
  const t0 = toTime(rem[0][0] + ":00") - 1800e3, t1 = toTime(rem[rem.length - 1][0] + ":00") + 3600e3;
  const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0), Y = (v) => yB - v * (yB - yT);
  const pts = rem.map(([h, v]) => ({ x: X(toTime(h + ":00")), y: Y(v), h, v }));
  // dense samples along the line so labels steer clear of it
  const avoid = [];
  pts.forEach((p, i) => { const q = pts[i + 1]; if (!q) return avoid.push(p); for (let k = 0; k < 6; k++) avoid.push({ x: p.x + (q.x - p.x) * k / 6, y: p.y + (q.y - p.y) * k / 6 }); });
  const nameFont = '600 12.5px -apple-system, system-ui, "Segoe UI", sans-serif', detFont = '11.5px -apple-system, system-ui, sans-serif';
  const shown = sigs.filter((r) => r.t != null && r.harm_share_after != null);
  // dots on the same spot share one label
  const groups = [];
  shown.forEach((r) => { r.x = X(r.t); r.y = Y(r.harm_share_after); const g = groups.find((g) => Math.hypot(g.x - r.x, g.y - r.y) < 12 && g.joint === r.joint); if (g) g.more.push(r); else groups.push({ ...r, more: [] }); });
  groups.forEach((g) => {
    g.line1 = g.name + (g.more.length ? ` (+${g.more.length} more)` : "");
    g.line2 = `${dayWord(g.t)} ${clock(g.t)} · ${pct(g.harm_share_after)} still to come`;
    g.w = Math.max(textWidth(g.line1, nameFont), textWidth(g.line2, detFont)) + 6; g.h = 32;
  });
  const order = [...groups].sort((a, b) => (b.joint - a.joint) || (a.t - b.t));
  placeLabels(order, { x0: x0 + 4, x1: x1, y0: yT, y1: yB - 4 }, [...avoid.map((p) => ({ ...p, r: 3 })), ...groups.map((g) => ({ x: g.x, y: g.y, r: 9 }))]);
  let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Share of harmful activity still to come, with the first time each warning sign fired">`;
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => { svg += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="${QUIET}">${v * 100}%</text>`; });
  svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
  timeTicks(t0, t1).forEach((k) => { svg += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${yB}" y2="${yB + 5}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${yB + 19}" text-anchor="middle" font-size="11" fill="${QUIET}">${esc(k.label)}</text>`; });
  svg += `<path d="${pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join("")}" fill="none" stroke="${CURVE}" stroke-width="2.5"/>`;
  pts.forEach((p) => { svg += `<circle cx="${p.x}" cy="${p.y}" r="5" fill="transparent"><title>${esc(p.h)}:00 UTC: ${pct(p.v)} of timed harmful activity still to come</title></circle>`; });
  groups.forEach((g) => {
    const c = g.joint ? ACCENT : SINGLE, L = g.label;
    if (L) {
      const lx = Math.max(L.x, Math.min(g.x, L.x + L.w)), ly = Math.max(L.y, Math.min(g.y, L.y + L.h));
      if (Math.hypot(lx - g.x, ly - g.y) > 10) svg += `<line x1="${g.x}" y1="${g.y}" x2="${lx}" y2="${ly}" stroke="${g.joint ? ACCENT : SINGLE}" stroke-opacity=".45" stroke-width="1.2"/>`;
      svg += `<g class="lbl"><rect x="${L.x - 2}" y="${L.y - 1}" width="${L.w + 2}" height="${L.h}" rx="3" fill="#fff" fill-opacity=".85"/><text x="${L.x}" y="${L.y + 13}" font-size="12.5" font-weight="600" fill="${g.joint ? INK : "#3a4148"}">${esc(g.line1)}</text><text x="${L.x}" y="${L.y + 28}" font-size="11.5" fill="${QUIET}">${esc(g.line2)}</text></g>`;
    }
    [g, ...g.more].forEach((r) => {
      const link = /^[A-Za-z]\d{3,}$/.test(String(r.ref)) || /[~@]/.test(String(r.ref));
      svg += `<circle class="${link ? "node" : ""}" ${link ? `data-ev="${esc(r.ref)}"` : ""} cx="${r.x}" cy="${r.y}" r="5.5" fill="${c}" stroke="#fff" stroke-width="1.5"><title>${esc(r.name)}, ${esc(r.time)} UTC (${esc(short(r.ref))}): ${pct(r.harm_share_after)} of timed harmful activity still to come</title></circle>`;
    });
  });
  host.innerHTML = svg + "</svg>" + (groups.some((g) => !g.label) ? `<p class="muted small">Not labelled for lack of room (hover the dot): ${groups.filter((g) => !g.label).map((g) => `${esc(g.line1)}, ${esc(g.line2)}`).join("; ")}.</p>` : "");
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
  <li><b>Links.</b> ${fmt(g.no_parent)} records have no parent link.</li></ul>
  ${f.overwrites ? `<h3>Every overwrite</h3><p class="muted small">Edits that replaced another actor's edit without keeping any line it added. Not counted as messages. Click a row to trace the edit that did the replacing.</p><div id="overList"></div>` : ""}`;
  if (f.overwrites) listView($("overList"), "overwrites", ["replaced", "by", "place", "earlier edit", "replacing edit", "what happened"],
    (o) => [`<code>${esc(short(o.from))}</code>`, `<code>${esc(short(o.to))}</code>`, `<code>${esc(o.channel)}</code>`, `${idlink(o.write_id)} <span class="muted small">${esc(o.write_time || "")}</span>`, `${idlink(o.read_id)} <span class="muted small">${esc(o.read_time || "")}</span>`, esc(o.how)],
    [], s.list_totals?.overwrites, (o) => selectEvent(o.read_id));
  if (f.overwrites) $("overList").querySelector(".lmore")?.click();
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
// one session id per conversation: OpenCode Go needs it (x-opencode-session); other providers ignore it
const newSessionId = () => "ses_" + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : String(Date.now()) + Math.random().toString(16).slice(2));
S.aiSession = newSessionId();
$("newChat").addEventListener("click", () => { S.chat = []; S.aiSession = newSessionId(); $("chat").innerHTML = ""; $("aistatus").textContent = "Started a new chat."; });
$("checkAI").addEventListener("click", async () => {
  const st = $("aistatus");
  if (!$("apiKey").value) { st.textContent = "Enter an API key first."; st.className = "small bad"; return; }
  st.textContent = "Checking…"; st.className = "small muted";
  try {
    const r = await api("/api/ai/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      baseUrl: $("baseUrl").value, apiKey: $("apiKey").value, model: $("model").value, sessionId: S.aiSession }) });
    st.textContent = `Connected: ${$("model").value} replied "${r.reply}".`; st.className = "small ok";
  } catch (e) { st.textContent = e.message; st.className = "small bad"; }
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
      selectedId: $("useSel").checked ? S.selected : null, conversation: S.conv || null, sessionId: S.aiSession }) });
    wait.remove();
    S.chat.push({ role: "assistant", content: r.content });
    addMsg("assistant", r.content, `${$("model").value}${r.context_ids?.length ? " · evidence sent: " + r.context_ids.join(", ") : ""}${S.conv ? ` · conversation sent: ${short(S.conv.a)} ↔ ${short(S.conv.b)}` : ""}${r.usage?.total_tokens ? " · " + r.usage.total_tokens + " tokens" : ""}`);
  } catch (e) { wait.remove(); S.chat.pop(); addMsg("error", e.message); }
  finally { $("send").disabled = false; }
}

init().catch((e) => status(e.message, true));

// Case file: pin records, actors, places and conversations with notes (kept on the server per
// dataset, mirrored in this browser), copy links, export a dossier; label tags, intents and
// messages right / wrong / can't tell with live precision; time ranges for estimated times; and
// the ground-truth score when the dataset is a simulated swarm with a truth file.
(() => {
"use strict";
const KINDS = ["record", "actor", "place", "conversation"];
const KIND_TITLE = { record: "Records", actor: "Actors", place: "Places", conversation: "Conversations" };
const CW = { name: null, case: null, loading: null, saveT: null, prec: null, gt: null };
const lsKey = () => "swarm-tracer-case:" + (S.summary?.name || "");

GLOSSARY.case_file = ["Case file", "Your own list of pinned records, actors, places and conversations, each with a note. It is kept on this machine (~/.swarm-tracer/cases) per dataset and exports as a printable dossier."];
GLOSSARY.label_precision = ["Precision from your labels", "Of the records a pattern fired on that you judged, the share you marked right. The range is a 95% Wilson interval: with few labels it is wide, so label more before trusting it."];
GLOSSARY.time_range = ["Estimated time range", "A record with no time field is dated from where it sits among records whose text carries a timestamp. Nine in ten of those timestamps fall within the fit error of the line, so the record's true time is likely inside ± that error."];
GLOSSARY.ground_truth = ["Ground truth", "A simulated swarm written by agenttrace.groundtruth, where every message (which record wrote it, which record read it) is known. Comparing what the tool finds with it gives precision and recall."];

// ------------------------------------------------------------------ the case: load, save, mirror
function blank() { return { dataset: S.summary?.name, title: `Case file: ${S.summary?.name || ""}`, notes: "", items: [] }; }
async function ensure() {
  if (!S.summary) return null;
  if (CW.name === S.summary.name && CW.case) return CW.case;
  if (CW.loading && CW.name === S.summary.name) return CW.loading;
  CW.name = S.summary.name;
  CW.loading = (async () => {
    let c = null;
    try { c = (await api("/api/x/case")).case; } catch (e) { console.warn("case file: server copy unavailable", e); }
    let local = null;
    try { local = JSON.parse(localStorage.getItem(lsKey()) || "null"); } catch { local = null; }
    // the server copy wins; the browser copy fills in when the server has none (or is unreachable)
    if ((!c || !c.items?.length) && local?.items?.length) { c = local; save(); }
    CW.case = c || local || blank();
    CW.loading = null;
    count();
    return CW.case;
  })();
  return CW.loading;
}
function mirror() { try { localStorage.setItem(lsKey(), JSON.stringify(CW.case)); } catch { /* storage full or blocked */ } }
function save(now) {
  mirror(); count();
  clearTimeout(CW.saveT);
  const go = () => api("/api/x/case", { method: "POST", body: JSON.stringify(CW.case) })
    .then((r) => { CW.case.updated = r.case.updated; mirror(); })
    .catch((e) => status("Case file kept in this browser only: " + e.message, true));
  if (now) return go();
  CW.saveT = setTimeout(go, 500);
}
function count() {
  const el = $("casecount");
  if (el) { const n = CW.case?.items?.length || 0; el.textContent = n ? String(n) : ""; el.className = n ? "cw-count" : ""; }
}
const find = (kind, key) => CW.case?.items.find((x) => x.kind === kind && x.key === key);
function pin(kind, key, note) {
  if (!CW.case) return;
  const have = find(kind, key);
  if (have) { if (note != null) have.note = note; }
  else CW.case.items.push({ kind, key, note: note || "", added: new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC", tab: S.tab });
  save(true); drawerRefresh();
}
function unpin(kind, key) {
  if (!CW.case) return;
  CW.case.items = CW.case.items.filter((x) => !(x.kind === kind && x.key === key));
  save(true); drawerRefresh();
}

// re-read the case whenever a dataset is loaded
if (typeof window.setSummary === "function" && !window.setSummary._cw) {
  const orig = window.setSummary;
  window.setSummary = function (s) { const r = orig.apply(this, arguments); CW.case = null; CW.prec = null; CW.gt = null; ensure().then(drawerRefresh); return r; };
  window.setSummary._cw = true;
}

// ------------------------------------------------------------------ links
const P = { record: "rec", actor: "actor", place: "place" };
function linkFor(kind, key, tab) {
  const base = location.origin + location.pathname;
  if (kind === "conversation") { const [a, b] = key.split("|"); return `${base}#tab=network&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`; }
  return `${base}#tab=${encodeURIComponent(tab || S.tab || "overview")}&${P[kind]}=${encodeURIComponent(key)}`;
}
function viewLink() {
  const cur = INS.stack.at(-1);
  if (cur && P[cur.kind]) return linkFor(cur.kind, cur.key, S.tab);
  if (S.tab === "network" && S.conv) return linkFor("conversation", `${S.conv.a}|${S.conv.b}`);
  return `${location.origin}${location.pathname}#tab=${encodeURIComponent(S.tab || "overview")}`;
}
async function copy(text, btn) {
  const old = btn?.textContent;
  try { await navigator.clipboard.writeText(text); if (btn) btn.textContent = "Copied"; }
  catch { window.prompt("Copy this link:", text); }
  if (btn) setTimeout(() => { btn.textContent = old; }, 1400);
}
function openItem(kind, key) {
  if (kind === "record") selectEvent(key);
  else if (kind === "actor") inspectActor(key);
  else if (kind === "place") inspectPlace(key);
  else { const [a, b] = key.split("|"); S.conv = { a, b }; goTab("network"); }
}
const chip = (kind, key) => kind === "record" ? ent.rec(key) : kind === "actor" ? ent.actor(key) : kind === "place" ? ent.place(key)
  : (() => { const [a, b] = key.split("|"); return `${ent.actor(a)} ⇄ ${ent.actor(b)}`; })();

// ------------------------------------------------------------------ Inspector: pin, note, link (every kind)
window.INSPECTOR_EXTRAS.push((kind, key, data) => {
  if (!P[kind]) return "";
  CW.data = { kind, key, data };
  return `<div class="dsec cw-sec" data-cw-kind="${esc(kind)}" data-cw-key="${esc(key)}">
    <h4>${term("case_file", "Case file")} <span class="cw-state small muted"></span></h4>
    <textarea class="cw-note" rows="2" placeholder="Your note on this ${esc(kind)} (optional)"></textarea>
    <div class="cw-btns"><button type="button" class="primary cw-pin">Pin to case file</button> <button type="button" class="cw-link">Copy link to this view</button> <button type="button" class="link cw-open">Open the case file</button></div>
  </div>
  ${kind === "record" ? `<div class="dsec cw-label" data-cw-rec="${esc(key)}"></div>` : ""}`;
});
window.INSPECTOR_BIND.push((host, kind, key) => {
  const sec = host.querySelector(".cw-sec");
  if (!sec) return;
  const note = sec.querySelector(".cw-note"), btn = sec.querySelector(".cw-pin"), st = sec.querySelector(".cw-state");
  const draw = () => {
    const it = find(kind, key);
    sec.classList.toggle("pinned", !!it);
    st.innerHTML = it ? '<span class="cw-pinned">● pinned</span>' : "";
    btn.textContent = it ? "Unpin" : "Pin to case file";
    btn.classList.toggle("primary", !it);
    if (it && document.activeElement !== note) note.value = it.note || "";
  };
  ensure().then(draw);
  btn.addEventListener("click", () => { if (find(kind, key)) { unpin(kind, key); note.value = ""; } else pin(kind, key, note.value); draw(); });
  note.addEventListener("input", () => { const it = find(kind, key); if (it) { it.note = note.value; save(); drawerRefresh(true); } });
  sec.querySelector(".cw-link").addEventListener("click", (e) => copy(linkFor(kind, key, S.tab), e.target));
  sec.querySelector(".cw-open").addEventListener("click", () => openDrawer());
  if (kind === "record") { bindLabels(host, key); bindRange(host, key); }
});

// ------------------------------------------------------------------ Inspector: time range for estimated times
async function bindRange(host, rid) {
  let r;
  try { r = await api("/api/x/time_range?id=" + encodeURIComponent(rid)); } catch { return; }
  if (r.source !== "estimated" || !r.low) return;
  const line = host.querySelector(".dhead .muted.small");
  if (line && !line.querySelector(".cw-range")) {
    line.insertAdjacentHTML("beforeend", ` · <span class="cw-range" title="${esc(r.why || "")}">${term("time_range", "likely " + esc(r.likely || r.text))}</span>`);
  }
  const sec = host.querySelector(".cw-sec");
  if (sec && !host.querySelector(".cw-rangesec")) {
    sec.insertAdjacentHTML("beforebegin", `<div class="dsec cw-rangesec"><h4>${term("time_range", "How sure its time is")}</h4>
      ${rangeBar(r)}<p class="small muted">${esc(r.why || "")}${r.from ? ` Its own time comes from ${esc(r.from)}, the record it answers.` : ""}</p></div>`);
  }
}
function rangeBar(r) {
  const W = 320, lo = toTime(r.low), hi = toTime(r.high), t = toTime(r.time);
  if (lo == null || hi == null || t == null || hi <= lo) return `<p><b>${esc(r.text)}</b></p>`;
  const X = (v) => 10 + ((v - lo) / (hi - lo)) * (W - 20);
  return `<p><b>${esc(r.text)}</b> <span class="muted small">(±${esc(r.p90_hours)} h)</span></p>
    <svg viewBox="0 0 ${W} 26" width="${W}" height="26" class="cw-rbar" aria-label="time range"><line x1="10" x2="${W - 10}" y1="12" y2="12" stroke="${C.place}" stroke-width="5" stroke-linecap="round" opacity=".25"/>
    <line x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="4" y2="20" stroke="${HARM}" stroke-width="2"/>
    <text x="10" y="25" font-size="9" fill="${C.quiet}">${esc(r.low.slice(5))}</text><text x="${W - 10}" y="25" font-size="9" text-anchor="end" fill="${C.quiet}">${esc(r.high.slice(5))}</text></svg>`;
}

// ------------------------------------------------------------------ Inspector: labels on a record
const LBL = [["1", "right"], ["0", "wrong"], ["?", "can't tell"]];
async function bindLabels(host, rid) {
  const box = host.querySelector(`.cw-label[data-cw-rec="${CSS.escape(rid)}"]`);
  if (!box) return;
  let t, have;
  const known = CW.data && CW.data.kind === "record" && CW.data.key === rid ? CW.data.data : null;
  try { [t, have] = await Promise.all([known || api("/api/event?id=" + encodeURIComponent(rid) + "&lite=1"), api("/api/x/labels?id=" + encodeURIComponent(rid))]); }
  catch (e) { box.innerHTML = ""; return; }
  const got = {};
  have.labels.forEach((l) => { got[l.tag + "\u0000" + l.id] = l.label; });
  const rows = [];
  (t.tags || []).forEach((g) => rows.push({ id: rid, tag: g, what: `tag <b>${esc(human(g))}</b>`, title: tagName(g) }));
  if (t.intent && t.intent !== "other") rows.push({ id: rid, tag: "intent:" + t.intent, what: `intent ${ent.intent(t.intent)}` });
  (t.messages_in || []).slice(0, 8).forEach((m) => rows.push({ id: `${m.write_id}>${rid}`, tag: "message", what: `message in from ${ent.actor(m.from)} via ${ent.place(m.channel)} (${ent.rec(m.write_id)})` }));
  (t.messages_out || []).slice(0, 8).forEach((m) => rows.push({ id: `${rid}>${m.read_id}`, tag: "message", what: `message out to ${ent.actor(m.to)} via ${ent.place(m.channel)} (${ent.rec(m.read_id)})` }));
  if (!rows.length) { box.remove(); return; }
  box.innerHTML = `<h4>Label it <span class="muted small">(is each reading right? saved to your labels file; ${term("label_precision", "precision")} updates live)</span></h4>
    <div class="cw-lrows">${rows.map((r, i) => `<div class="cw-lrow" data-i="${i}"><div class="cw-lwhat"${r.title ? ` title="${esc(r.title)}"` : ""}>${r.what}</div><div class="cw-lbtns">${LBL.map(([v, w]) => `<button type="button" data-v="${v}" class="${got[r.tag + "\u0000" + r.id] === v ? "on v" + (v === "?" ? "q" : v) : ""}">${w}</button>`).join("")}</div></div>`).join("")}</div>
    <p class="small muted cw-lnote">${fmt(have.total)} labels on this dataset so far. <button type="button" class="link cw-open">See precision</button></p>`;
  box.querySelector(".cw-open").addEventListener("click", () => openDrawer("labels"));
  box.querySelectorAll(".cw-lrow").forEach((row) => row.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    const r = rows[+row.dataset.i];
    const v = b.classList.contains("on") ? "" : b.dataset.v;
    try {
      const res = await api("/api/x/label", { method: "POST", body: JSON.stringify({ id: r.id, tag: r.tag, label: v }) });
      row.querySelectorAll("button").forEach((x) => { x.className = x.dataset.v === v ? "on v" + (v === "?" ? "q" : v) : ""; });
      CW.prec = res.precision;
      const n = box.querySelector(".cw-lnote");
      if (n) n.firstChild.textContent = `${fmt(res.total)} labels on this dataset so far. `;
      drawerRefresh(true);
    } catch (err) { status(err.message, true); }
  }));
}

// ------------------------------------------------------------------ conversations: a pin button in the conversation panel
new MutationObserver(() => {
  const btns = document.querySelector("#conv .convbtns");
  if (!btns || btns.querySelector(".cw-cpin") || !S.conv) return;
  const key = `${S.conv.a}|${S.conv.b}`;
  btns.insertAdjacentHTML("afterbegin", `<button type="button" class="cw-cpin">${find("conversation", key) ? "Pinned ●" : "Pin to case file"}</button> `);
  const b = btns.querySelector(".cw-cpin");
  ensure().then(() => { b.textContent = find("conversation", key) ? "Pinned ●" : "Pin to case file"; });
  b.addEventListener("click", async () => {
    await ensure();
    if (find("conversation", key)) unpin("conversation", key); else pin("conversation", key, "");
    b.textContent = find("conversation", key) ? "Pinned ●" : "Pin to case file";
  });
}).observe(document.body, { childList: true, subtree: true });

// ------------------------------------------------------------------ the drawer
function drawerEl() {
  let el = $("cwdrawer");
  if (!el) { el = document.createElement("aside"); el.id = "cwdrawer"; el.className = "cw-drawer"; el.hidden = true; document.body.appendChild(el); }
  return el;
}
async function openDrawer(focus) {
  const el = drawerEl();
  if (!S.summary) { el.hidden = false; el.innerHTML = `<div class="cw-head"><h3>Case file</h3><button type="button" class="link cw-close">Close</button></div><p class="muted cw-pad">Load a dataset first.</p>`; el.querySelector(".cw-close").onclick = () => { el.hidden = true; }; return; }
  el.hidden = false;
  await ensure();
  drawRender();
  loadSide();
  if (focus === "labels") setTimeout(() => el.querySelector("#cwLabels")?.scrollIntoView({ block: "start" }), 50);
}
function drawerRefresh(soft) {
  const el = $("cwdrawer");
  if (!el || el.hidden) return;
  if (soft) { drawSide(); return; }
  drawRender();
}
function drawRender() {
  const el = drawerEl(), c = CW.case;
  if (!c) return;
  const groups = KINDS.map((k) => [k, c.items.filter((x) => x.kind === k)]).filter(([, l]) => l.length);
  el.innerHTML = `<div class="cw-head"><input class="cw-title" value="${esc(c.title || "")}" aria-label="Case title"><button type="button" class="link cw-close">Close</button></div>
    <div class="cw-body">
      <p class="small muted">${term("case_file", "Case file")} for <b>${esc(S.summary.name)}</b> · ${plural(c.items.length, "pinned item")}${c.updated ? ` · saved ${esc(c.updated)}` : ""}</p>
      <label class="cw-lab">Your notes<textarea class="cw-notes" rows="4" placeholder="What you think happened, open questions, next steps…">${esc(c.notes || "")}</textarea></label>
      <div class="cw-btns"><button type="button" class="cw-vlink">Copy link to this view</button> <button type="button" class="primary cw-exh">Export case file (HTML)</button> <button type="button" class="cw-exj">(JSON)</button></div>
      ${groups.length ? groups.map(([k, l]) => `<h4 class="cw-gh">${KIND_TITLE[k]} <span class="muted">${fmt(l.length)}</span></h4>${l.map((it) => itemRow(it)).join("")}`).join("")
        : '<p class="muted cw-empty">Nothing pinned yet. Open any record, actor or place in the Inspector and press <b>Pin to case file</b>; a conversation has its own pin button.</p>'}
      <div id="cwLabels"></div>
      <div id="cwTruth"></div>
    </div>`;
  el.querySelector(".cw-close").addEventListener("click", () => { el.hidden = true; });
  el.querySelector(".cw-title").addEventListener("input", (e) => { c.title = e.target.value; save(); });
  el.querySelector(".cw-notes").addEventListener("input", (e) => { c.notes = e.target.value; save(); });
  el.querySelector(".cw-vlink").addEventListener("click", (e) => copy(viewLink(), e.target));
  el.querySelector(".cw-exh").addEventListener("click", (e) => exportCase("html", e.target));
  el.querySelector(".cw-exj").addEventListener("click", (e) => exportCase("json", e.target));
  el.querySelectorAll(".cw-item").forEach((row) => {
    const it = c.items[+row.dataset.i];
    row.querySelector(".cw-inote").addEventListener("input", (e) => { it.note = e.target.value; save(); });
    row.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (!b) return;
      const act = b.dataset.act, i = c.items.indexOf(it);
      // move within its own kind's group
      const same = c.items.map((x, j) => [x, j]).filter(([x]) => x.kind === it.kind).map(([, j]) => j), at = same.indexOf(i);
      if (act === "up" && at > 0) { [c.items[i], c.items[same[at - 1]]] = [c.items[same[at - 1]], c.items[i]]; save(true); drawRender(); }
      else if (act === "down" && at < same.length - 1) { [c.items[i], c.items[same[at + 1]]] = [c.items[same[at + 1]], c.items[i]]; save(true); drawRender(); }
      else if (act === "rm") unpin(it.kind, it.key);
      else if (act === "link") copy(linkFor(it.kind, it.key, it.tab), b);
      else if (act === "open") openItem(it.kind, it.key);
    });
  });
  drawSide();
}
function itemRow(it) {
  const i = CW.case.items.indexOf(it);
  return `<div class="cw-item" data-i="${i}"><div class="cw-irow"><span class="cw-chip">${chip(it.kind, it.key)}</span>
    <span class="cw-ibtns"><button type="button" class="link" data-act="open">open</button><button type="button" class="link" data-act="link">copy link</button><button type="button" data-act="up" title="Move up">↑</button><button type="button" data-act="down" title="Move down">↓</button><button type="button" data-act="rm" title="Remove from the case file">✕</button></span></div>
    <textarea class="cw-inote" rows="2" placeholder="Note">${esc(it.note || "")}</textarea><div class="small faint">pinned ${esc(it.added || "")}</div></div>`;
}
async function exportCase(format, btn) {
  const old = btn.textContent;
  btn.textContent = "Exporting…"; btn.disabled = true;
  try {
    clearTimeout(CW.saveT); await save(true);
    const r = await api(`/api/x/case_export?format=${format}&base=${encodeURIComponent(location.origin + location.pathname)}`);
    const blob = format === "html" ? new Blob([r.html], { type: "text/html" }) : new Blob([JSON.stringify(r.dossier, null, 1)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = r.filename; document.body.appendChild(a); a.click(); a.remove();
    if (format === "html") window.open(url, "_blank");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    status(`Saved ${r.filename}${format === "html" ? "; it also opened in a new tab, ready to print to PDF" : ""}.`);
    setTimeout(() => status(""), 6000);
  } catch (e) { status("Export failed: " + e.message, true); }
  finally { btn.textContent = old; btn.disabled = false; }
}

// ------------------------------------------------------------------ drawer: your labels, ground truth
async function loadSide() {
  try { CW.prec = await api("/api/x/precision"); } catch { CW.prec = null; }
  try { CW.gt = await api("/api/x/groundtruth_score"); } catch (e) { CW.gt = { available: false, why: e.message }; }
  drawSide();
}
const pr = (x) => x == null ? "–" : pct(x);
function drawSide() {
  const L = $("cwLabels"), T = $("cwTruth");
  if (L) {
    const p = CW.prec;
    L.innerHTML = card("Your labels", !p || !p.labels ? '<p class="small muted">No labels yet. In the Inspector, a record shows its tags, intent and messages with right / wrong / can\'t tell buttons.</p>'
      : `<div class="cw-kpis">${kpiBox(p.labels, "labels")}${kpiBox(p.judged, "judged right or wrong")}${kpiBox(p.rows.length, "patterns")}</div>
        <table class="cw-ptab"><thead><tr><th>pattern</th><th>right</th><th>wrong</th><th>?</th><th>${term("label_precision", "precision")}</th></tr></thead><tbody>${p.rows.map((r) => `<tr><td>${esc(human(r.tag))}</td><td>${fmt(r.tp)}</td><td>${fmt(r.fp)}</td><td>${fmt(r.unclear)}</td><td>${r.precision == null ? "–" : ciBar(r)}</td></tr>`).join("")}</tbody></table>
        <p class="small muted">Saved to <code>${esc(p.path)}</code>, the same CSV <code>python3 -m agenttrace precision</code> reads. Ranges are 95% Wilson intervals.</p>`,
      { sub: "Your judgments of the tool's readings, and the precision they imply" });
  }
  if (T) {
    const g = CW.gt;
    if (!g) { T.innerHTML = ""; return; }
    T.innerHTML = card(term("ground_truth", "Ground truth"), g.available ? truthBody(g)
      : `<p class="small muted">${esc(g.why || "No truth file for this dataset.")}</p><label class="small cw-tfile">Score against a truth file <input type="file" accept=".truth,.json"></label>`,
      { sub: g.available ? `Scored against ${esc(g.truth_file)}` : "For a simulated swarm with known messages" });
    const inp = T.querySelector(".cw-tfile input");
    if (inp) inp.addEventListener("change", async () => {
      const f = inp.files[0];
      if (!f) return;
      try { CW.gt = await api("/api/x/groundtruth_truth?filename=" + encodeURIComponent(f.name), { method: "POST", body: f }); drawSide(); }
      catch (e) { status(e.message, true); }
    });
  }
}
const kpiBox = (v, k) => `<div><b>${fmt(v)}</b><span>${esc(k)}</span></div>`;
function ciBar(r) {
  const W = 90;
  return `<span class="cw-ci"><svg width="${W}" height="10" viewBox="0 0 ${W} 10"><rect x="0" y="4" width="${W}" height="2" fill="${GRID}"/><rect x="${(r.ci_low * W).toFixed(1)}" y="2" width="${Math.max(1, (r.ci_high - r.ci_low) * W).toFixed(1)}" height="6" rx="2" fill="${ACCENT}" opacity=".35"/><circle cx="${(r.precision * W).toFixed(1)}" cy="5" r="3" fill="${ACCENT}"/></svg> <b>${pct(r.precision)}</b> <span class="muted">${pct(r.ci_low)}–${pct(r.ci_high)}</span></span>`;
}
function truthBody(g) {
  const m = g.messages, p = g.pairs, d = g.dating, e = g.early_signs, i = g.identity;
  const prRow = (name, x) => `<tr><td>${name}</td><td>${pr(x.precision)} <span class="muted">${fmt(x.correct)}/${fmt(x.found)}</span></td><td>${pr(x.recall)} <span class="muted">${fmt(x.correct)}/${fmt(x.true)}</span></td></tr>`;
  return `<table class="cw-ptab"><thead><tr><th></th><th>precision</th><th>recall</th></tr></thead><tbody>
      ${prRow("messages (write → read record)", m)}${prRow("pairs of agents", p)}${i.merges ? prRow("identity merges", i.merges) : ""}</tbody></table>
    ${m.false_positives.length ? `<p class="small"><b>Messages the tool found that did not happen</b></p><ul class="cw-why">${m.false_positives.map((x) => `<li>${fmt(x.n)} · ${esc(x.why)} ${x.examples.slice(0, 2).map((ex) => ent.rec(ex[1])).join(" ")}</li>`).join("")}</ul>` : ""}
    ${m.missed.length ? `<p class="small"><b>Messages it missed</b></p><ul class="cw-why">${m.missed.map((x) => `<li>${fmt(x.n)} · ${esc(x.why)} ${x.examples.slice(0, 2).map((ex) => ent.rec(ex[1])).join(" ")}</li>`).join("")}</ul>` : ""}
    <p class="small"><b>Dating:</b> ${d.estimated ? `${fmt(d.estimated)} estimated times; median error ${esc(d.median_error_hours)} h, 90th percentile ${esc(d.p90_error_hours)} h; ${pct(d.inside_stated_range)} fall inside the range the app states.` : "no estimated times in this dataset."}</p>
    <p class="small"><b>Early signs:</b> ${fmt(e.found)} of ${fmt(e.true)} found; ${fmt(e.on_time)} within an hour of the true time.</p>
    ${table(["sign", "true", "tool", "off by"], e.signs.map((r) => [esc(r.name), esc((r.true_time || "").slice(5, 16).replace("T", " ")), esc(r.tool_time ? r.tool_time.slice(5, 16).replace("T", " ") : "not found"), r.error_hours == null ? "–" : `<span class="${r.on_time ? "" : "cw-off"}">${r.error_hours > 0 ? "+" : ""}${esc(r.error_hours)} h</span>`]))}
    <p class="small"><b>Identity:</b> ${fmt(i.agents)} agents, ${fmt(i.agents_with_two_tokens)} holding two tokens; the tool counts ${fmt(i.tool_actors)} actors. ${esc(i.note || "")}</p>`;
}

// ------------------------------------------------------------------ top-bar button
const btn = $("casebtn");
if (btn) btn.addEventListener("click", () => { const el = $("cwdrawer"); if (el && !el.hidden) el.hidden = true; else openDrawer(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("cwdrawer") && !e.target.matches?.("input,textarea")) $("cwdrawer").hidden = true; });
window.addEventListener("load", () => setTimeout(() => { if (S.summary) ensure(); }, 600));
window.CASEFILE = { ensure, pin, unpin, openDrawer, linkFor, viewLink };
})();

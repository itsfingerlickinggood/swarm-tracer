// Forensics, "What is missing": how far each gap could move the headline answers (range bars), the insiders'
// published findings set against what the records show, and what to log next time. Server side:
// agenttrace/sensitivity.py (GET /api/x/sensitivity, sensitivity_gap, insiders, collect_next).
(() => {
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
const G = "What is missing";
const STATUS = { recovered: { c: "#1f7a4d", word: "recovered", tip: "the tool shows it, within its dating error" },
                 partly: { c: "#d9a030", word: "partly", tip: "some of it shows, or it shows at another size" },
                 invisible: { c: "#6b7480", word: "invisible", tip: "the records cannot show it" } };
const HEADS = ["first_message", "first_message_share", "messages", "pairs", "alarm_lead_h"];
const KIND = { first_message: "time", first_message_share: "share", messages: "count", pairs: "count", alarm_lead_h: "hours" };
const SIGN_SHARE = /^share:/;

const tword = (v) => v == null ? "–" : when(toTime(v));
const val = (v, kind) => v == null ? "–" : kind === "time" ? tword(v) : kind === "share" ? pct(v) : kind === "hours" ? `${(+v).toFixed(1)} h` : fmt(Math.round(v * 10) / 10);
function rangeText(r, kind) {
  if (!r || r.lo == null) return "no value";
  const a = val(r.lo, kind), b = val(r.hi, kind);
  return a === b ? a : `${a} to ${b}`;
}
// one range on the axis shared by every gap: the grey track is everything any gap allows, the blue part this gap's range, the tick the as-counted value
function bar(r, axis, kind) {
  if (!r || r.lo == null) return '<span class="sx-bar sx-none"></span>';
  let a = axis.lo, b = axis.hi;
  if (kind === "share") { a = 0; b = 1; }
  if (kind === "count" && a > 0) a = 0;
  const span = (b - a) || 1, pos = (v) => Math.max(0, Math.min(100, ((v - a) / span) * 100));
  const l = pos(r.lo), w = Math.max(1.5, pos(r.hi) - l);
  return `<span class="sx-bar"><i class="sx-ext" style="left:${l.toFixed(2)}%;width:${w.toFixed(2)}%"></i>${r.base != null ? `<b class="sx-base" style="left:${pos(r.base).toFixed(2)}%" title="as counted: ${esc(val(r.base, kind))}"></b>` : ""}</span>`;
}
const same = (r) => r && r.lo != null && r.lo === r.hi;

function headRows(heads, ranges, overall, defs) {
  const lab = Object.fromEntries(defs.map((d) => [d.key, d.label]));
  return heads.map((k) => {
    const kind = KIND[k] || "share", r = ranges[k], ov = overall[k] || {};
    const moved = r && r.lo != null && !same(r);
    return `<div class="sx-row${moved ? "" : " sx-still"}"><div class="sx-l">${esc(lab[k] || k)}</div>${bar(r, { lo: ov.lo, hi: ov.hi }, kind)}<div class="sx-t"><b>${esc(rangeText(r, kind))}</b>${r && r.base != null && moved ? `<span class="muted small"> · as counted ${esc(val(r.base, kind))}</span>` : same(r) ? '<span class="muted small"> · does not move</span>' : ""}${r && r.missing ? `<span class="muted small"> · no value in ${r.missing} of ${r.of} cases</span>` : ""}</div></div>`;
  }).join("");
}

function scenarioTable(g) {
  const rows = g.scenarios.map((x) => {
    const v = x.values;
    return `<tr><td>${esc(x.label)}${x.note ? `<div class="small muted">${esc(x.note)}</div>` : ""}</td><td>${v.first_message != null ? esc(tword(v.first_message)) : "–"}</td><td class="num">${pct(v.first_message_share)}</td><td class="num">${v.messages != null ? fmt(Math.round(v.messages * 10) / 10) : "–"}</td><td class="num">${v.pairs != null ? fmt(Math.round(v.pairs * 10) / 10) : "–"}</td><td class="num">${v.alarm_lead_h != null ? (+v.alarm_lead_h).toFixed(1) + " h" : "–"}</td></tr>`;
  }).join("");
  return `<div class="sx-scroll"><table class="sx-tab"><thead><tr><th>Case</th><th>First message</th><th class="num">Harm still to come</th><th class="num">Messages</th><th class="num">Pairs</th><th class="num">Lead over volume alarm</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function gapCard(g, sens, gapRows) {
  const open = g.computable;
  const rowsTag = g.rows.map((k) => { const r = gapRows.find((x) => x.key === k); return r ? `<span class="qtag" style="--c:#5b6672">${esc(r.gap)}${r.count != null ? ` · ${fmt(r.count)} ${esc(r.unit)}` : ""}</span>` : ""; }).join(" ");
  const signs = sens.headlines.filter((h) => SIGN_SHARE.test(h.key));
  const body = !open ? `<p class="small">${esc(g.note)}</p>` : `
    ${headRows(HEADS, g.ranges, sens.overall, sens.headlines)}
    <details class="sx-det"><summary>Harm still to come at each warning sign</summary>${headRows(signs.map((x) => x.key), g.ranges, sens.overall, sens.headlines)}</details>
    <details class="sx-det"><summary>The ${g.scenarios.length} cases behind these ranges</summary>${scenarioTable(g)}</details>
    <p class="small muted sx-note">${esc(g.note)}</p>`;
  return `<section class="card sx-gap" data-sxgap="${esc(g.key)}"><header><h3>${esc(g.title)}</h3>${rowsTag}</header>${body}</section>`;
}

async function renderSens(host) {
  host.innerHTML = '<p class="muted">Recounting every headline under each assumption… (the first time takes a few seconds)</p>';
  const [sens, gp] = await Promise.all([api("/api/x/sensitivity"), cached("/api/gaps").catch(() => ({ rows: [] }))]);
  if (!sens.available) { host.innerHTML = `<p class="muted">${esc(sens.reason || "Not available for this dataset.")}</p>`; return; }
  const ov = sens.overall;
  host.innerHTML = `
    <p class="small muted">Each bar is the range one gap leaves open for one headline answer, on a common scale: grey is everything any gap allows, blue is this gap's range, the tick is the value as counted. Two gaps are parametric (missing channel, read success): their ranges follow stated assumptions, not measurements. Computed from the loaded records in ${esc(String(sens.elapsed_s))} s; counts move if the counting rules change.</p>
    ${card("All gaps together", headRows(HEADS, ov, ov, sens.headlines), { sub: "The widest range any single gap allows for each answer." })}
    ${sens.gaps.map((g) => gapCard(g, sens, gp.rows || [])).join("")}`;
  const want = window.FX_SENS_FOCUS;
  if (want) { window.FX_SENS_FOCUS = null; const el = host.querySelector(`[data-sxgap="${want}"]`); if (el) { el.classList.add("sx-focus"); el.scrollIntoView({ block: "start" }); } }
}

// ------------------------------------------------------------------ the insiders
const INS = { status: "", group: "", open: null };
async function renderInsiders(host) {
  host.innerHTML = '<p class="muted">Checking each published finding against the records… (the first time takes about ten seconds)</p>';
  const d = await api("/api/x/insiders");
  if (!d.available) { host.innerHTML = `<p class="muted">${esc(d.reason || "Not available for this dataset.")}</p>`; return; }
  drawInsiders(host, d);
}
function drawInsiders(host, d) {
  const c = d.counts, tot = d.total;
  const list = d.findings.filter((f) => (!INS.status || f.status === INS.status) && (!INS.group || f.group === INS.group));
  const groups = Object.keys(d.by_group);
  host.innerHTML = `
    <p class="small muted">${esc(d.about)}</p>
    <div class="in-sum" role="img" aria-label="${c.recovered} recovered, ${c.partly} partly, ${c.invisible} invisible">${["recovered", "partly", "invisible"].map((k) => c[k] ? `<span style="flex:${c[k]};background:${STATUS[k].c}" title="${STATUS[k].word}: ${c[k]}">${c[k]}</span>` : "").join("")}</div>
    <div class="in-key">${["recovered", "partly", "invisible"].map((k) => `<button type="button" data-st="${k}" class="${INS.status === k ? "on" : ""}" title="${esc(STATUS[k].tip)}"><i style="background:${STATUS[k].c}"></i>${c[k]} ${STATUS[k].word}</button>`).join("")}
      <span class="muted small">of ${tot} findings · times count as recovered within the dating error of ${d.tolerance_h} h</span></div>
    <div class="in-key">${groups.map((g) => `<button type="button" data-gr="${esc(g)}" class="${INS.group === g ? "on" : ""}">${esc(g)} <span class="muted">${["recovered", "partly", "invisible"].map((k) => d.by_group[g][k]).join(" / ")}</span></button>`).join("")}${INS.status || INS.group ? '<button type="button" class="link" data-clear="1">show all</button>' : ""}</div>
    <div class="in-grid" role="list">${d.findings.map((f) => `<button type="button" role="listitem" class="in-tile${list.includes(f) ? "" : " dim"}${INS.open === f.id ? " on" : ""}" data-f="${esc(f.id)}" style="--c:${STATUS[f.status].c}" title="${esc(STATUS[f.status].word + ": " + f.finding)}"></button>`).join("")}</div>
    <div class="in-list">${list.map((f) => `<div class="in-row${INS.open === f.id ? " open" : ""}" data-row="${esc(f.id)}"><button type="button" class="in-head" data-f="${esc(f.id)}" aria-expanded="${INS.open === f.id}"><i style="background:${STATUS[f.status].c}"></i><span class="in-st" style="color:${STATUS[f.status].c}">${STATUS[f.status].word}</span><span class="in-fi">${esc(f.finding)}</span><span class="muted small in-src">${esc(f.source)}</span></button>${INS.open === f.id ? detail(f) : ""}</div>`).join("") || '<p class="muted">No finding matches.</p>'}</div>`;
  host.querySelectorAll("[data-st]").forEach((b) => b.addEventListener("click", () => { INS.status = INS.status === b.dataset.st ? "" : b.dataset.st; drawInsiders(host, d); }));
  host.querySelectorAll("[data-gr]").forEach((b) => b.addEventListener("click", () => { INS.group = INS.group === b.dataset.gr ? "" : b.dataset.gr; drawInsiders(host, d); }));
  host.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => { INS.status = INS.group = ""; drawInsiders(host, d); }));
  host.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { INS.open = INS.open === b.dataset.f ? null : b.dataset.f; drawInsiders(host, d); const r = host.querySelector(`[data-row="${INS.open}"]`); if (r) r.scrollIntoView({ block: "nearest" }); }));
  host.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
    const [tab, q] = [b.dataset.go, b.dataset.q];
    if (tab === "events" && q) goEvents({ q }); else goTab(tab);
  }));
}
function detail(f) {
  const e = f.evidence || {}, n = e.numbers || {};
  const nums = Object.entries(n).filter(([, v]) => v != null && !Array.isArray(v) && typeof v !== "object").map(([k, v]) => `<span class="muted small">${esc(k.replace(/_/g, " "))}</span> <b>${esc(typeof v === "number" ? fmt(v) : String(v))}</b>`).join(" · ");
  const v = f.view || {};
  return `<div class="in-detail"><p>${esc(f.why)}</p>
    ${e.records && e.records.length ? `<p class="small">Records: ${e.records.map((r) => ent.rec(r)).join(" ")}${e.n && e.n > e.records.length ? ` <span class="muted">(${fmt(e.n)} in all)</span>` : ""}</p>` : ""}
    ${nums ? `<p class="small">${nums}</p>` : ""}
    ${v.tab ? `<p class="small"><button type="button" class="primary" data-go="${esc(v.tab)}"${v.q ? ` data-q="${esc(v.q)}"` : ""}>Open ${esc(v.label || v.tab)}</button></p>` : ""}</div>`;
}

// ------------------------------------------------------------------ what to collect next time
async function renderCollect(host) {
  host.innerHTML = '<p class="muted">Sizing each missing field…</p>';
  const d = await api("/api/x/collect_next");
  if (!d.available) { host.innerHTML = `<p class="muted">${esc(d.reason || "Not available for this dataset.")}</p>`; return; }
  host.innerHTML = `<p class="small muted">${esc(d.basis)} The same list, with the figures as of the day it was written, is in <code>docs/collect-next-time.md</code>.</p>
    <ol class="cn-list">${d.items.map((x) => `<li class="card cn"><header><h3><span class="cn-n">${x.priority}</span> ${esc(x.field)}</h3>${x.parametric ? '<span class="qtag" style="--c:#8a5a00">parametric</span>' : ""}</header>
      <p><b>Closes:</b> ${esc(x.closes)}</p>
      ${x.effect ? `<div class="cn-eff"><div><span class="muted small">First message today</span><b>${esc(x.effect.first_message)}</b></div><div><span class="muted small">Harm still to come then</span><b>${esc(x.effect.first_message_share)}</b></div><div><span class="muted small">Messages</span><b>${esc(x.effect.messages)}</b></div><div><span class="muted small">Pairs</span><b>${esc(x.effect.pairs)}</b></div></div>` : ""}
      <p class="small">${esc(x.sentence || "")}</p>
      <p class="small"><b>Cost for a lab:</b> ${esc(x.cost)}</p></li>`).join("")}</ol>`;
}

window.FX_SECTIONS.push(
  { id: "sensitivity", title: "Gap sensitivity", group: G, blurb: "For each blind spot, the headline answers recounted under a best and a worst case, as ranges.", render: renderSens },
  { id: "insiders", title: "Compare with the insiders", group: G, blurb: "What the incident's insiders published, set against what the records show: recovered, partly, or invisible.", render: renderInsiders },
  { id: "collect", title: "What to collect next time", group: G, blurb: "The log fields and practices that would close each gap, in priority order, with the size of the effect.", render: renderCollect },
);
})();

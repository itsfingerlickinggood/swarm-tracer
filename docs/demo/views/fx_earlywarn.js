// Forensics, "Early warning": could the coordination have been flagged early? Since v2.3.0 the main answer is four
// simple alarms (new host, secrets search, distinct actors, volume); the signs of shared control are context ("who
// shares control"), shown with their measured numbers and labelled as not an early warning. Then the frozen signs,
// the v2.2.0 forward test, false-alarm rates, a cost curve, and a streaming monitor.
// Server side: agenttrace/earlywarn.py and agenttrace/baselines.py (tables), agenttrace/online.py (streaming).
// Every number comes from the API.
(() => {
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
const G = "Early warning";
const FAM_COLOR = { newhost: "#0f766e", secrets: "#b8579a", actors: "#1d4f91", volume6: "#a16207",
  watch: "#c2410c", coord: "#2f6fb3", volume: "#d9822b", place: "#2e9d5b", message: "#7c4dbd", group: "#5d6d7e" };
const MAIN_COLOR = "#0f766e", CONTEXT_COLOR = "#8a94a0";
const MAIN_PATH = "/api/x/earlywarn_main";
const share = (b) => !b || !b.n ? "–" : `${b.k}/${b.n}`;
const ci = (c) => !c ? "" : `${Math.round(c[0] * 100)}–${Math.round(c[1] * 100)}%`;
const shareCi = (b) => !b || !b.n ? '<span class="muted">–</span>' : `<span class="nowrap">${b.k}/${b.n}</span> <span class="muted small nowrap">${ci(b.ci)}</span>`;
const p1 = (x) => x == null ? "–" : `${(x * 100).toFixed(1)}%`;
const range = (c, f) => !c ? "" : ` <span class="muted small nowrap">${f(c[0])} to ${f(c[1])}</span>`;
const roleTag = (r) => r === "main" ? '<span class="ew-role ew-main">main alarm</span>' : r === "any" ? '<span class="ew-role ew-main">any of four</span>' : r === "variant" ? '<span class="ew-role">variant</span>' : r === "context" ? '<span class="ew-role ew-ctx">context</span>' : "";
const num = (x, d = 1) => x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
const hrs = (x) => x == null ? "–" : `${num(x)} h`;
const rate = (x) => x == null ? "–" : x >= 10 ? x.toFixed(0) : x >= 1 ? x.toFixed(1) : x.toFixed(2);
const tick = (ok) => ok ? '<span class="ew-yes" title="fired">✓</span>' : '<span class="ew-no" title="did not fire">✗</span>';
const SUMMARY_PATH = "/api/x/earlywarn_summary";

async function summary(host) {
  const d = await api(SUMMARY_PATH);
  if (!d.ran) {
    host.innerHTML = `<p class="warn">The forward test has not been run on this machine yet.</p>
      <p class="small">It takes about a minute: <code>${esc(d.command)}</code></p>
      <p><button type="button" id="ewrun">${d.running ? "Running…" : "Run it now (one seed per setting)"}</button></p>`;
    const b = host.querySelector("#ewrun");
    if (b && !d.running) b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Running…";
      await api("/api/x/earlywarn_run", { method: "POST", body: JSON.stringify({ run: true, quick: true }) });
      const poll = async () => { const s = await api(SUMMARY_PATH); if (s.ran && !s.running) { S.cache.clear(); renderAgain(host); } else setTimeout(poll, 3000); };
      poll();
    });
    return null;
  }
  return d;
}
let LAST_RENDER = null;
function renderAgain(host) { if (LAST_RENDER) LAST_RENDER(host); }

const wide = (host) => Math.max(290, Math.floor(host.clientWidth || 400) - 40);   // pixels a chart may use inside a card
const tbl = (html, min = 440) => `<div class="ew-scroll"><table class="ew-tab" style="min-width:${min}px">${html}</table></div>`;
const caveat = (t) => `<p class="small muted ew-cav">${t}</p>`;

// ------------------------------------------------------------------ 0. the main alarms, then the context
const recChip = (id) => id ? (typeof ent !== "undefined" && ent.rec ? ent.rec(id) : `<code>${esc(id)}</code>`) : "";
function preregLine(pn) {
  if (!pn || !pn.written) return `<p class="small warn">No pre-registration file on this machine. Write it before any forward swarm exists: <code>python3 -m agenttrace.earlywarn prereg23</code>, then <code>python3 -m agenttrace.earlywarn forward23</code>.</p>`;
  return `<p class="small">Pre-registration <code>reports/earlywarn/prereg_v23.json</code> written ${esc(pn.written_utc)} (file SHA-256 <code>${esc(pn.file_sha256.slice(0, 12))}</code>, alarm parameters <code>${esc(pn.alarms_sha256.slice(0, 12))}</code>).
    ${pn.alarms_match ? "The alarm parameters in the code still hash to that value." : '<span class="warn">The alarm parameters in the code no longer match it.</span>'}
    ${pn.code_changed.length ? `<span class="warn">Code changed since it was written: ${pn.code_changed.map((x) => `<code>${esc(x)}</code>`).join(", ")}.</span>` : "No code file has changed since."}
    ${pn.rewritten_with_results_present ? '<span class="warn">It was rewritten while results were already present.</span>' : ""}
    It was not committed to git by the tool, so the order rests on the file times unless you commit it.</p>`;
}
function forwardCard(kind, g) {
  const keep = (r) => r.shared_control || r.id === "alert-coord2";
  const rows = g.main.concat(g.context.filter(keep));
  const body = rows.map((x) => {
    const c = x.coordinated, b = x.benign;
    return `<tr${x.role === "context" ? ' class="ew-ctxrow"' : ""}><td>${esc(x.name)} ${roleTag(x.role)}</td><td class="num">${share(c.fired)}</td><td class="num">${shareCi(c.before_harm)}</td>
      <td class="num">${hrs(c.median_lead_h)}${range(c.median_ci_settings, (v) => num(v))}</td><td class="num">${p1(c.harm_share_median)}${range(c.harm_share_ci_settings, (v) => `${Math.round(v * 100)}%`)}</td>
      <td class="num">${x.role === "context" ? '<span class="muted">–</span>' : shareCi(c.beats)}</td><td class="num">${shareCi(b.fired)}</td></tr>`; }).join("");
  const verdict = (h) => h.holds == null ? "not measurable" : h.holds ? "holds" : "fails";
  const short = Object.fromEntries(g.main.map((x) => [x.id, x.short]));
  const hyp = ["H1", "H2", "H3"].map((id) => { const hs = g.hypotheses.filter((h) => h.hypothesis === id);
    return `<li><b>${id}</b>: ${hs.map((h) => `${esc(short[h.alarm] || h.alarm)} <span class="${h.holds ? "ew-yes" : "ew-no"}">${verdict(h)}</span> <span class="muted small">(${h.k == null ? "–" : `${h.k}/${h.n}`})</span>`).join(" · ")}</li>`; }).join("");
  return card(`Forward test, ${kind} generator: ${fmt(g.coordinated_runs)} coordinated and ${fmt(g.benign_runs)} benign swarms`, tbl(`<thead><tr><th>Alarm or sign</th><th class="num">Fired</th><th class="num">Before the first harm</th><th class="num">Median lead</th><th class="num">True harm still to come</th><th class="num">More harm to come than the shared-place sign</th><th class="num">Fired, benign</th></tr></thead><tbody>${body}</tbody>`, 720)
    + `<ul class="ew-adv ew-hyp">${hyp}</ul>`,
    { sub: `Seeds ${esc(g.seeds[0])} to ${esc(g.seeds[g.seeds.length - 1])}, generated ${esc(g.generated)}, after the pre-registration. k/n is per swarm with its 95% binomial interval; the ranges beside the lead and the harm share resample whole settings. A lead with a minus sign is after the first true harm. A sign that never fires counts as 0% of harm still to come.` });
}
function benignCard(E) {
  const ids = ["new_host_12h", "first_intent", "distinct_actors", "volume_6h", "any_main", "alert-coord2"];
  const heads = ["New host", "Secrets search", "Distinct actors", "Volume, 6 h", "Any of the four", "Old Alert rule (context)"];
  const cell = (set, id) => { const r = set.rows.find((x) => x.id === id); return r ? shareCi(r.fired) : "–"; };
  const sim = E.benign_sets.map((s) => `<tr${s.set.startsWith("  ") ? ' class="ew-sub2"' : ""}><td>${esc(s.set.trim())}<div class="small muted">${esc(s.kind)}${s.undated ? `; ${fmt(s.undated)} more had no times` : ""}</div></td><td class="num">${fmt(s.swarms)}</td>${ids.map((id) => `<td class="num">${cell(s, id)}</td>`).join("")}</tr>`).join("");
  const ext = E.external && E.external.present ? E.external.datasets.map((d) => `<tr class="ew-real"><td>${esc(d.dataset)} <span class="ew-role">real traces</span><div class="small muted">${esc(d.what || "")}. Read-only; ${fmt(d.loaded)} of ${fmt(d.files)} files loaded${d.unreadable_format ? `, ${fmt(d.unreadable_format)} in a format with no reader` : ""}${d.too_large ? `, ${fmt(d.too_large)} too large` : ""}${d.failed ? `, ${fmt(d.failed)} failed` : ""}</div></td><td class="num">${fmt(d.dated)}<div class="small muted">with times, of ${fmt(d.loaded)}</div></td>
      ${d.dated ? ids.map((id) => `<td class="num">${id === "first_intent" ? `<span class="muted small">pattern in</span> ${shareCi(d.pattern_check)}` : cell(d.benign_set, id)}</td>`).join("")
        : `<td colspan="6" class="small"><span class="warn">Not measurable: no trace has times, so no time-based alarm can fire.</span> The pattern behind the secrets-search alarm matches a record in ${shareCi(d.pattern_check)} traces.</td>`}</tr>`).join("") : "";
  const excl = E.external && (E.external.excluded || []).length ? ` Left out: ${E.external.excluded.map((x) => `${esc(x.dataset)} (${esc(x.why)})`).join("; ")}.` : "";
  return card("Benign false alarms, on every benign set there is", tbl(`<thead><tr><th>Benign set</th><th class="num">Swarms</th>${heads.map((h) => `<th class="num">${esc(h)}</th>`).join("")}</tr></thead><tbody>${sim}${ext}</tbody>`, 760)
    + `<p class="small muted">${E.external && E.external.present ? esc(E.external.note) + excl : "Real traces under <code>datasets-ext/</code> have not been measured on this machine (<code>python3 -m agenttrace.earlywarn external</code>), so every row is simulated."} The simulators never write a secrets-search action, so its 0s there are not evidence. A real trace is counted once however long it is; the real traces with times run for days, so \"fired at least once\" is easier to reach there than in a 36 to 48 hour simulated swarm.</p>`,
    { sub: "Swarms in which each alarm fired at least once, of the swarms in the set, with the per-swarm 95% binomial interval. A benign swarm that fires an alarm is a false alarm. \"Any of the four\" is what an operator who runs all four would hear." });
}
async function renderMain(host) {
  const d = await api(MAIN_PATH);
  LAST_RENDER = renderMain;
  const L = d.loaded, E = d.evidence;
  const when2 = (x) => x.fired === false || x.time == null ? '<span class="muted">did not fire</span>' : `<span class="nowrap">${esc(x.time)} UTC</span> <span class="muted small nowrap">hour ${esc(x.h)}</span>`;
  const harm = (x) => x.harm_share_after == null ? '<span class="muted">–</span>' : `${meter(x.harm_share_after, x.role === "context" ? CONTEXT_COLOR : MAIN_COLOR, 60)} ${p1(x.harm_share_after)}`;
  let loaded = '<p class="small muted">No dataset is loaded, so there is nothing to run the alarms on.</p>';
  if (L && !L.dated) loaded = '<p class="warn">No record in this dataset has a time. All four alarms need time (12 hours of history, or counts per hour), so none can fire here. That is not the same as no alarm.</p>';
  else if (L) {
    const firstMain = L.alarms.filter((x) => x.fired).sort((a, b) => a.t - b.t)[0];
    const before = firstMain ? L.context.filter((x) => x.t < firstMain.t) : L.context;
    loaded = tbl(`<thead><tr><th>Alarm</th><th>Fired</th><th>Harm still to come</th><th>Record</th><th>Why</th></tr></thead><tbody>${L.alarms.concat(L.variants).map((x) =>
      `<tr><td>${esc(x.name)} ${roleTag(x.role)}<div class="small muted">${esc(x.what)}</div></td><td>${when2(x)}</td><td class="nowrap">${harm(x)}</td><td>${recChip(x.record)}</td><td class="small">${esc(x.why || "")}</td></tr>`).join("")}</tbody>`, 620)
      + `<p class="small">${firstMain ? `The first main alarm here is <b>${esc(firstMain.name.toLowerCase())}</b>, with ${p1(firstMain.harm_share_after)} of the ${fmt(L.harm_records)} timed harmful actions still to come.` : "No main alarm fired on this dataset."}
        ${before.length ? `<span class="warn">On this dataset ${plural(before.length, "sign")} of shared control fired ${firstMain ? "before it" : "although no alarm did"} (${esc(before.slice(0, 3).map((x) => x.name).join("; "))}${before.length > 3 ? "; …" : ""}).</span> On the real release it was the other way round; both are shown so you can see which holds here.` : L.context.length ? "Every sign of shared control fired after it." : ""}
        ${L.has_intent ? "" : "This pack has no search_for_secrets intent, so the secrets-search alarm cannot fire here."}</p>`;
  }
  const ctx = L && L.dated ? (L.context.length ? tbl(`<thead><tr><th>Sign of shared control</th><th>First fired</th><th>Harm still to come</th><th>Record</th><th>Main alarms that fired before it</th></tr></thead><tbody>${L.context.map((x) =>
      `<tr><td>${esc(x.name)}${x.shared_control ? ' <span class="ew-role ew-ctx">shared control</span>' : ""}</td><td>${when2(x)}</td><td class="nowrap">${harm({ ...x, role: "context" })}</td><td>${recChip(x.record)}</td><td class="small">${x.after_alarms.length ? esc(x.after_alarms.map((i) => (L.alarms.find((a) => a.id === i) || {}).short || i).join(", ")) : '<span class="muted">none</span>'}</td></tr>`).join("")}</tbody>`, 560) : '<p class="small muted">No sign of shared control fired on this dataset.</p>') : "";
  const rel = E.release;
  const relCard = rel ? card("The real release: the one incident the alarms were chosen on", tbl(`<thead><tr><th>Alarm or sign</th><th class="num">Hours after the first timed action</th><th>Share of timed harm still to come</th></tr></thead><tbody>${rel.alarms.concat(rel.variants, rel.context).map((x) =>
      `<tr${x.role === "context" ? ' class="ew-ctxrow"' : ""}><td>${esc(x.name)} ${roleTag(x.role)}</td><td class="num">${x.h == null ? "–" : esc(x.h)}</td><td class="nowrap">${harm(x)}</td></tr>`).join("")}</tbody>`, 440),
      { sub: `${fmt(rel.records)} records, ${fmt(rel.harm_records)} timed harmful actions. ${esc(rel.note)}` }) : "";
  host.innerHTML = `
    <div class="ew-hero ew-posthoc"><div class="ew-date"><span class="small muted">Read this first</span><b>Post-hoc</b></div><div class="ew-note">${esc(d.post_hoc)}</div></div>
    <p class="ew-lead">The main early warning is four simple alarms: the first new host after 12 hours, the first secrets-search action, more distinct actors in an hour than before, and more actions in an hour than before. None of them looks at who shares what. The signs that do are below as context.${E.ran ? ` In the pre-registered forward test on simulated swarms the hypothesis that an alarm fires before the first true harm ${Object.values(E.generators).some((g) => g.hypotheses.some((h) => h.hypothesis === "H1" && h.holds)) ? "held for some alarms" : "failed for every alarm on both generators"}: read the tables before relying on them as a warning.` : ""}</p>
    ${card(L ? `The main alarms on ${esc(L.dataset)}` : "The main alarms on the loaded dataset", loaded)}
    ${E.ran ? benignCard(E) : ""}
    ${E.ran ? Object.entries(E.generators).map(([k, g]) => forwardCard(k === "original" ? "original" : "independent", g)).join("") : card("Forward test", '<p class="warn">The pre-registered forward test has not been run on this machine.</p>')}
    ${card("The pre-registration", preregLine(E.prereg_now) + (E.ran ? `<ul class="ew-adv">${E.hypothesis_text.map((h) => `<li class="small"><b>${esc(h.id)} (${esc(h.name)})</b>: ${esc(h.statement)} <span class="muted">${esc(h.expected)}</span></li>`).join("")}</ul>` : ""))}
    ${relCard}
    ${card(`${esc(d.context_label)} <span class="ew-role ew-ctx">not an early warning</span>`, `<p class="small">${esc(d.context_note)}</p>${ctx}`)}
    ${E.ran ? caveat(E.caveats.map(esc).join(" ")) : ""}`;
}

// ------------------------------------------------------------------ 1. frozen signs
async function renderFrozen(host) {
  const [f, m] = await Promise.all([api("/api/x/earlywarn_frozen"), api(MAIN_PATH)]);
  const fz = f.frozen;
  const groups = [["single", "One actor"], ["joint", "Context: actors together (who shares control; not an early warning)"], ["baseline", "The 12 h volume alarm (a variant of the main volume alarm)"]];
  host.innerHTML = `
    ${card("The main alarms, as frozen for v2.3.0", tbl(`<thead><tr><th>Alarm</th><th>What it is</th><th>Parameters</th></tr></thead><tbody>${m.alarms.main.map((x) => [x, "main"]).concat(m.alarms.variants.map((x) => [x, "variant"])).map(([x, r]) =>
      `<tr><td>${esc(x.name)} ${roleTag(r)}</td><td class="small">${esc(x.what)}</td><td class="small nowrap">${esc(Object.entries(x.params).map(([k, v]) => `${k} = ${v}`).join(", "))}</td></tr>`).join("")}</tbody>`, 460)
      + preregLine(m.evidence.prereg_now), { sub: esc(m.post_hoc) })}
    <div class="ew-hero"><div class="ew-date"><span class="small muted">Frozen on</span><b>${esc(fz.frozen_on)}</b></div>
      <div class="ew-note">${esc(fz.note)}</div></div>
    ${card("The default alert rules of v2.2.0 (context)", tbl(`<thead><tr><th>Rule</th><th>Severity</th><th>Fires when</th></tr></thead><tbody>${fz.rules.map((r) =>
      `<tr><td>${esc(r.name)}</td><td><span class="ew-sev ew-${esc(r.severity)}">${esc(r.severity)}</span></td><td>${esc(r.description)}</td></tr>`).join("")}</tbody>`, 380))}
    ${groups.map(([g, title]) => { const rows = fz.signs.filter((x) => x.family === g); return rows.length ? card(title, tbl(`<thead><tr><th>Sign</th><th>What it is</th><th>Threshold</th></tr></thead><tbody>${rows.map((x) =>
      `<tr><td>${esc(x.name)}${x.pack ? `<div class="small muted">pack ${esc(x.pack)}</div>` : ""}</td><td class="small">${esc(x.definition)}</td><td class="small nowrap">${esc(x.threshold)}</td></tr>`).join("")}</tbody>`, 460)) : ""; }).join("")}
    ${card("Code version", `<p class="small">git <code>${esc((fz.code.git_head || "").slice(0, 10))}</code>${f.same_head ? " (still the current commit)" : `; the repository is now at <code>${esc((f.head_now || "").slice(0, 10))}</code>`}.
      ${f.drift.length ? `<span class="warn">Sign code has changed since the freeze: ${f.drift.map((x) => `<code>${esc(x)}</code>`).join(", ")}.</span>` : "The sign code is byte-for-byte what it was when frozen."}</p>
      <p class="small muted">File hashes are in <code>agenttrace/claims/frozen_signs.json</code>. Check any time: <code>python3 -m agenttrace.earlywarn freeze --check</code>.</p>`)}`;
}

// ------------------------------------------------------------------ 2. forward test
async function renderForward(host) {
  const d = await summary(host); if (!d) return;
  LAST_RENDER = renderForward;
  const F = d.forward;
  const nC = F.coordinated_runs, nB = F.benign_runs;
  const cell = (n, ok) => `${tick(ok)} <span class="small">${n}</span>`;
  const row = (x) => {
    const h = x.coordinated.harm, m = x.coordinated.message;
    return `<tr><td>${esc(x.name)}</td><td class="nowrap">${cell(`${h.fired}/${h.n}`, h.fired > 0)}</td><td class="num">${hrs(h.median_lead_h)}</td><td class="num">${hrs(m.median_lead_h)}</td><td class="nowrap">${x.benign.fired ? cell(`${x.benign.fired}/${x.benign.n}`, true) : `<span class="muted small">0/${x.benign.n}</span>`}</td></tr>`;
  };
  const head = `<thead><tr><th></th><th>Fired, coordinated</th><th class="num">Lead before first harm</th><th class="num">Lead before first message</th><th>Fired, benign</th></tr></thead>`;
  const fam = (g, t) => { const rows = F.signs.filter((x) => x.family === g); return rows.length ? `<tr class="ew-grp"><td colspan="5">${t}</td></tr>${rows.map(row).join("")}` : ""; };
  const wiki = d.wiki || {};
  host.innerHTML = `
    <p class="ew-lead">${fmt(nC)} coordinated and ${fmt(nB)} benign simulated swarms (seeds ${esc(d.seeds[0])} to ${esc(d.seeds[d.seeds.length - 1])}, every validation setting), run through the simple alarms and the signs exactly as frozen. A lead is hours <i>before</i> the first true harm or the first true message in the simulation's own truth; a minus sign means the sign fired after it.</p>
    ${card("The simple alarms, the default rules and every sign", tbl(`${head}<tbody>
      ${(F.baselines || []).length ? `<tr class="ew-grp"><td colspan="5">Simple alarms (the main early warning since v2.3.0, and their variants)</td></tr>${F.baselines.map(row).join("")}` : ""}
      <tr class="ew-grp"><td colspan="5">Default alert rules of v2.2.0</td></tr>${F.rules.map(row).join("")}
      ${fam("single", "Signs: one actor")}${fam("joint", "Context: actors together (not an early warning)")}${fam("baseline", "The 12 h volume alarm")}</tbody>`, 400),
      { sub: "✓ = fired in at least one swarm of that kind. A sign that fires on benign swarms is a false alarm there. This is the v2.2.0 run; the pre-registered run of the main alarms on fresh seeds is under Main alarms." })}
    ${card("Sample traces that have timestamps", tbl(`<thead><tr><th>Sample</th><th>Span</th><th class="c">Watch</th><th class="c">Alert</th><th>Signs that fired</th></tr></thead><tbody>${d.samples.map((s) =>
      `<tr><td>${esc(s.name)}${s.error ? ` <span class="warn small">${esc(s.error)}</span>` : ""}</td><td class="num small">${s.hours != null ? `${s.hours} h` : "–"}</td><td class="c">${tick(s.rules["watch-harm"] != null)}</td><td class="c">${tick(s.rules["alert-coord2"] != null)}</td><td class="small">${esc(s.signs.map((g) => g.name).join(", ") || "none")}</td></tr>`).join("")}</tbody>`, 460),
      { sub: "Made-up traces of a few records in other frameworks' formats, with hand-written handoffs. They have no harm and no truth, so only whether a sign fired can be said, not how early. A handoff is a message, so these fire the coordination signs by design." })}
    ${card("The wiki swarm", wiki.available ? `<p class="small">${esc(wiki.note)}</p>${tbl(`<thead><tr><th>Sign</th><th class="num">Hours after the first record</th></tr></thead><tbody>${wiki.signs.map((g) => `<tr><td>${esc(g.name)}</td><td class="num">${g.h == null ? "–" : g.h.toFixed(1)}</td></tr>`).join("")}</tbody>`, 300)}
      <p class="small muted">The pipeline's own first harmful record is at hour ${wiki.first_flagged_harm_h == null ? "–" : wiki.first_flagged_harm_h.toFixed(1)}.</p>` : `<p class="small muted">${esc(wiki.note || "not run")}</p>`)}
    ${caveat(d.caveats.map(esc).join(" "))}`;
}

// ------------------------------------------------------------------ 3. false alarms
async function renderFalse(host) {
  const d = await summary(host); if (!d) return;
  LAST_RENDER = renderFalse;
  const A = d.false_alarms;
  const isMain = (r) => r.role === "main" || (r.role == null && ["new_host_12h", "first_intent", "distinct_actors", "volume_6h"].includes(r.id));
  const rows = A.rows.filter((r) => r.kind === "rule" || r.alarms > 0 || isMain(r)).sort((a, b) => isMain(b) - isMain(a));
  const max = Math.max(0.1, ...rows.map((r) => r.ci_high || r.per_24h || 0)) * 1.1;
  const W = wide(host), L = 14, R = 40, rowH = 38, H = rows.length * rowH + 40;
  const X = (v) => L + (W - L - R) * Math.min(1, v / max);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const svg = `<svg width="${W}" height="${H}" class="ew-svg" role="img" aria-label="False alarms per 24 hours of trace time, with 95% intervals">
    ${ticks.map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="4" y2="${H - 30}" stroke="${GRID}"/><text x="${X(t)}" y="${H - 16}" text-anchor="middle" class="ew-ax">${rate(t)}</text>`).join("")}
    ${rows.map((r, i) => { const y = 6 + i * rowH, c = isMain(r) ? MAIN_COLOR : r.kind === "rule" ? ACCENT : "#8a94a0";
      return `<text x="${L}" y="${y + 11}" class="ew-lab ${isMain(r) || r.kind === "rule" ? "ew-b" : ""}">${esc(r.name.length > Math.floor(W / 6.3) ? r.name.slice(0, Math.floor(W / 6.3) - 1) + "…" : r.name)}</text>
        <rect x="${L}" y="${y + 17}" width="${Math.max(1, X(r.per_24h || 0) - L)}" height="11" fill="${c}" opacity=".75" rx="2"/>
        ${r.ci_high != null ? `<line x1="${X(r.ci_low)}" x2="${X(r.ci_high)}" y1="${y + 22.5}" y2="${y + 22.5}" stroke="${INK}" stroke-width="1.4"/><line x1="${X(r.ci_low)}" x2="${X(r.ci_low)}" y1="${y + 18}" y2="${y + 27}" stroke="${INK}"/><line x1="${X(r.ci_high)}" x2="${X(r.ci_high)}" y1="${y + 18}" y2="${y + 27}" stroke="${INK}"/>` : ""}
        <text x="${X(r.ci_high || r.per_24h || 0) + 5}" y="${y + 27}" class="ew-ax">${rate(r.per_24h)}</text>
        <title>${esc(r.name)}: ${r.alarms} alarms, ${rate(r.per_24h)} per 24 h (95% ${rate(r.ci_low)} to ${rate(r.ci_high)})</title>`; }).join("")}
    <text x="${L}" y="${H - 2}" class="ew-axt">false alarms per 24 h of trace time; line = 95% interval</text></svg>`;
  host.innerHTML = `
    <div class="ew-stats"><div><b>${fmt(A.benign_runs)}</b><span>benign swarms</span></div><div><b>${fmt(A.trace_hours)}</b><span>trace hours</span></div><div><b>${fmt(A.agent_hours)}</b><span>agent-hours observed</span></div></div>
    <p class="ew-lead">Alarms per 24 hours of trace time on swarms that never coordinate, with an exact Poisson 95% interval. Green bars are the four main alarms, blue bars the default alert rules of v2.2.0, grey bars individual signs and alarm variants. This is the v2.2.0 run; every benign set, per swarm, is under Main alarms.</p>
    ${card("False alarms per day", svg + tbl(`<thead><tr><th>Rule or sign</th><th class="num">Alarms</th><th class="num">Per 24 h</th><th class="num">95%</th></tr></thead><tbody>${rows.map((r) =>
      `<tr><td>${esc(r.name)}${isMain(r) ? " " + roleTag("main") : ""}</td><td class="num">${r.alarms}</td><td class="num">${rate(r.per_24h)}</td><td class="num">${r.alarms ? `${rate(r.ci_low)} to ${rate(r.ci_high)}` : `0 to ${rate(r.ci_high)}`}</td></tr>`).join("")}</tbody>`, 380))}
    ${card("What this is not", `<p class="small">${esc(A.caveat)}</p>
      <p class="small"><b>Your own benign trace.</b> <code>python3 -m agenttrace.earlywarn run YOUR_TRACE.jsonl --pack auto --out DIR</code> prints this table for it (alarms per 24 h of its own trace time, agent-hours, interval). It is a false-alarm rate only if you know the trace is benign. See <code>docs/early-warning.md</code>.</p>`)}`;
}

// ------------------------------------------------------------------ 4. cost curve
function ocChart(C, W) {
  const fams = C.families;
  const pts = fams.flatMap((f) => f.points.map((p) => ({ ...p, fam: f.id, famName: f.name })));
  const H = 340, L = 40, R = 14, T = 12, B = 52;
  const ys = pts.map((p) => p.median_lead_h).filter((v) => v != null);
  let lo = Math.min(-2, ...ys), hi = Math.max(2, ...ys);
  const padY = (hi - lo) * 0.08; lo -= padY; hi += padY;
  const zeroW = 44;                      // a column for "none seen" at the left of the log axis
  const xmin = 0.03, xmax = Math.max(2, ...pts.map((p) => p.per_24h || 0)) * 1.3;
  const plotL = L + zeroW + 14;
  const X = (v) => v ? plotL + (W - R - plotL) * (Math.log10(v) - Math.log10(xmin)) / (Math.log10(xmax) - Math.log10(xmin)) : L + zeroW / 2;
  const Y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const xt = [0.05, 0.1, 0.2, 0.5, 1, 2, 5].filter((v) => v <= xmax);
  const yt = []; const step = (hi - lo) > 40 ? 10 : (hi - lo) > 20 ? 5 : 2; for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) yt.push(v);
  let s = `<svg width="${W}" height="${H}" class="ew-svg ew-oc" role="img" aria-label="Operating characteristic: lead time against false alarms per day, one line per rule family">`;
  s += yt.map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v === 0 ? AXIS : GRID}" ${v === 0 ? 'stroke-width="1.4"' : ""}/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" class="ew-ax">${v}</text>`).join("");
  s += xt.map((v) => `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${H - B}" stroke="${GRID}"/><text x="${X(v)}" y="${H - B + 15}" text-anchor="middle" class="ew-ax">${v}</text>`).join("");
  s += `<line x1="${L + zeroW + 2}" x2="${L + zeroW + 2}" y1="${T}" y2="${H - B}" stroke="${AXIS}" stroke-dasharray="3 3"/><text x="${L + zeroW / 2}" y="${H - B + 15}" text-anchor="middle" class="ew-ax">none seen</text>`;
  s += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ew-axt">false alarms per 24 h, benign trace (log scale)</text>`;
  s += `<text transform="translate(11 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle" class="ew-axt">median lead before first harm (h)</text>`;
  s += `<text x="${plotL + 2}" y="${T + 9}" class="ew-ax">↑ earlier than the first harm</text><text x="${plotL + 2}" y="${H - B - 4}" class="ew-ax">↓ later</text>`;
  // lines, then points with labels
  for (const f of fams) {
    const p = f.points.filter((p) => p.median_lead_h != null && p.per_24h != null).sort((a, b) => (a.per_24h - b.per_24h) || (a.value - b.value));
    const col = FAM_COLOR[f.id] || "#555";
    if (p.length > 1) s += `<polyline fill="none" stroke="${col}" stroke-width="1.8" opacity=".8" points="${p.map((q) => `${X(q.per_24h).toFixed(1)},${Y(q.median_lead_h).toFixed(1)}`).join(" ")}"/>`;
    p.forEach((q, i) => {
      const cx = X(q.per_24h), cy = Y(q.median_lead_h), dy = (i % 2 ? 14 : -8);
      s += `<g><circle cx="${cx}" cy="${cy}" r="${q.default ? 6.5 : 4.5}" fill="${col}" ${q.default ? `stroke="${INK}" stroke-width="2"` : 'stroke="#fff" stroke-width="1"'}/><text x="${cx + 7}" y="${cy + dy}" class="ew-pl" fill="${col}">${esc(q.label)}</text>
        <title>${esc(f.name)} ${esc(f.param)} ${esc(q.label)}${q.default ? " (default)" : ""}: ${rate(q.per_24h)} false alarms per 24 h; median lead ${hrs(q.median_lead_h)}; caught ${q.fired} of ${q.coordinated}</title></g>`;
    });
  }
  s += "</svg>";
  const legend = `<div class="ew-leg">${fams.map((f) => `<span><i style="background:${FAM_COLOR[f.id] || "#555"}"></i>${esc(f.name)}</span>`).join("")}<span><i class="ew-ring"></i>current default</span></div>`;
  return legend + s;
}
async function renderCost(host) {
  const d = await summary(host); if (!d) return;
  LAST_RENDER = renderCost;
  const C = d.cost;
  const bud = C.budgets.map((b) => `<tr><td class="num">${b.budget_per_24h === 0 ? "none seen" : `up to ${b.budget_per_24h}`}</td><td>${b.best ? `${esc(b.name)}, ${esc(b.label)}` : '<span class="muted">nothing qualifies</span>'}</td><td class="num">${b.best ? hrs(b.median_lead_h) : "–"}</td><td class="num">${b.best ? rate(b.per_24h) : "–"}</td><td class="num">${b.best ? pct(b.detect) : "–"}</td></tr>`).join("");
  host.innerHTML = `
    <p class="ew-lead">Each line is one rule family with its threshold swept; each dot is one threshold, labelled with it. Left is quieter, up is earlier. Lead is the median over ${fmt(C.coordinated_runs)} coordinated swarms that the rule caught; false alarms are per 24 h of ${fmt(C.benign_runs)} benign swarms (${esc(C.benign_days)} days of trace).</p>
    ${card("Lead time against false alarms", ocChart(C, wide(host)), { sub: "Outlined dots are the frozen defaults. Dots at the left edge never fired on a benign swarm; their true rate is only bounded above (see the table)." })}
    ${card("What to pick", `<ul class="ew-adv">${C.families.map((f) => `<li>${esc(f.advice)}</li>`).join("")}</ul>`)}
    ${card("The best rule for each false-alarm budget", tbl(`<thead><tr><th class="num">Budget per 24 h</th><th>Best rule</th><th class="num">Median lead</th><th class="num">False alarms per 24 h</th><th class="num">Caught</th></tr></thead><tbody>${bud}</tbody>`, 440), { sub: "Among settings that caught at least half of the coordinated swarms." })}
    ${card("Every point", tbl(`<thead><tr><th>Family</th><th>Setting</th><th class="num">False alarms per 24 h</th><th class="num">95% interval</th><th class="num">Caught</th><th class="num">Median lead</th></tr></thead><tbody>${C.families.map((f) => f.points.map((p) =>
      `<tr><td>${esc(f.name)}</td><td>${esc(f.param ? f.param + " = " : "")}${esc(p.label)}${p.default ? ' <span class="ew-def">default</span>' : ""}</td><td class="num">${rate(p.per_24h)}</td><td class="num">${p.false_alarms ? `${rate(p.ci_low)} to ${rate(p.ci_high)}` : `0 to ${rate(p.ci_high)}`}</td><td class="num">${p.fired}/${p.coordinated}</td><td class="num">${hrs(p.median_lead_h)}</td></tr>`).join("")).join("")}</tbody>`, 500))}
    <div id="ewrel"></div>
    ${caveat(d.caveats.map(esc).join(" "))}`;
  try {
    const r = await api("/api/x/earlywarn_release");
    const f = (x) => x == null ? '<span class="muted">did not fire</span>' : `hour ${x.toFixed(1)}`;
    $("ewrel").innerHTML = card("On the loaded dataset: where each default fires (no truth)", `<p class="small warn">A real release has no ground truth, so there is no lead time here, only where each rule fires on the replay. Hours are counted from the first timed action of ${esc(r.dataset)}.</p>
      ${tbl(`<thead><tr><th>Rule family</th><th>Settings, hours after the start</th></tr></thead><tbody>${r.families.map((fm) => `<tr><td>${esc(fm.name)}</td><td class="small">${fm.points.map((p) => `<span class="${p.default ? "ew-def2" : ""}">${esc(String(p.value))}${fm.id === "volume" ? "σ" : ""}: ${f(p.h)}</span>`).join(" · ")}</td></tr>`).join("")}</tbody>`, 420)}`);
  } catch (e) { $("ewrel").innerHTML = ""; }
}

// ------------------------------------------------------------------ 5. online mode
async function renderOnline(host) {
  host.innerHTML = '<p class="muted">Streaming the records through the monitor…</p>';
  let d = await api("/api/x/online_replay");
  let tries = 0;
  while (d.running && tries++ < 200) {
    host.innerHTML = `<p class="muted">Streaming ${fmt(d.records)} records through the monitor…</p>`;
    await new Promise((r) => setTimeout(r, 2500));
    if (!host.isConnected) return;
    d = await api("/api/x/online_replay");
  }
  if (d.running) { host.innerHTML = '<p class="warn">Still running; open this section again in a minute.</p>'; return; }
  const byRole = (a, b) => (b.role === "main") - (a.role === "main");
  const rows = d.compare.rows.filter((r) => r.online_index != null || r.replay_index != null).sort(byRole);
  const N = d.records;
  const mainEv = (d.events || []).filter((e) => e.role === "main").sort((a, b) => a.record_index - b.record_index);
  const cm = d.compare.main || { alarms: 4, online: mainEv.length, both: 0, matched: 0 };
  const W = wide(host), L = 6, R = 12, rowH = 34, T = 10, H = T + rows.length * rowH + 34;
  const X = (n) => L + (W - L - R) * Math.log10(Math.max(1, n)) / Math.log10(Math.max(10, N));
  const tk = []; for (let v = 1; v <= N; v *= 10) tk.push(v);
  const svg = `<svg width="${W}" height="${H}" class="ew-svg" role="img" aria-label="Each sign's moment of firing on a records-seen axis, online against replay">
    ${tk.map((v) => `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${H - 28}" stroke="${GRID}"/><text x="${X(v)}" y="${H - 15}" text-anchor="middle" class="ew-ax">${fmt(v)}</text>`).join("")}
    <text x="${L}" y="${H - 2}" class="ew-axt">records seen (log scale)</text>
    ${rows.map((r, i) => { const y = T + i * rowH + 24, col = r.role === "main" ? MAIN_COLOR : r.family === "joint" ? C.joint : r.family === "single" ? C.single : C.baseline;
      return `<text x="${L}" y="${y - 12}" class="ew-lab ${r.role === "main" ? "ew-b" : ""}">${esc(r.name.length > Math.floor(W / 6.3) ? r.name.slice(0, Math.floor(W / 6.3) - 1) + "…" : r.name)}</text>
        ${r.online_index != null && r.replay_index != null ? `<line x1="${X(r.online_index)}" x2="${X(r.replay_index)}" y1="${y}" y2="${y}" stroke="${AXIS}"/>` : ""}
        ${r.replay_index != null ? `<circle cx="${X(r.replay_index)}" cy="${y}" r="5" fill="#fff" stroke="${col}" stroke-width="1.6"><title>replay: record ${fmt(r.replay_index)}, ${esc(r.replay_time || "")}</title></circle>` : ""}
        ${r.online_index != null ? `<circle cx="${X(r.online_index)}" cy="${y}" r="4" fill="${col}"><title>online: after ${fmt(r.online_index)} records, ${esc(r.online_time || "")}</title></circle>` : ""}`; }).join("")}</svg>`;
  const c = d.compare;
  host.innerHTML = `
    <div class="ew-stats"><div><b>${fmt(d.records)}</b><span>records streamed</span></div><div><b>${fmt(d.records_per_s)}</b><span>records per second</span></div><div><b>${esc(cm.online)} of ${esc(cm.alarms)}</b><span>main alarms fired online</span></div><div><b>${esc(cm.matched)} of ${esc(cm.both)}</b><span>main alarms fired by both that match the replay within ${esc(c.tolerance_h)} h</span></div><div><b>${esc(c.matched)} of ${esc(c.both)}</b><span>of all shared signs match</span></div></div>
    <p class="ew-lead">The monitor reads the records one at a time, in order. Its main output is the four simple alarms; the signs of shared control follow as context (who shares control, not an early warning). Each is said the moment the records so far make it fire.</p>
    ${card("The main alarms, as the stream fired them", mainEv.length ? tbl(`<thead><tr><th>Alarm</th><th class="num">Records seen</th><th>Online time</th><th>Why</th></tr></thead><tbody>${mainEv.map((e) =>
      `<tr><td>${esc(e.name)} ${roleTag("main")}</td><td class="num">${fmt(e.record_index)}</td><td class="small nowrap">${esc(e.time)}</td><td class="small">${esc(e.why)}</td></tr>`).join("")}</tbody>`, 480) : '<p class="small muted">No main alarm fired on this stream.</p>',
      { sub: "Chosen after seeing one real incident (post-hoc). The hourly alarms are known at the end of their hour." })}
    <p class="ew-lead"> Filled dots: the record count at which it fired online. Hollow dots: the record the replay's sign points at, which the replay could only pick knowing the whole dataset.</p>
    ${card("Signs as they fire, by records seen", svg)}
    ${card("Online against the replay", tbl(`<thead><tr><th>Alarm or sign</th><th class="num">Records seen</th><th>Online time</th><th>Replay time</th><th class="num">Difference</th></tr></thead><tbody>${c.rows.slice().sort(byRole).map((r) =>
      `<tr class="${r.status !== "both" ? "ew-flag" : r.match ? "" : "ew-flag"}"><td>${esc(r.name)} ${roleTag(r.role)}</td><td class="num">${r.online_index != null ? fmt(r.online_index) : "–"}</td><td class="small nowrap">${esc(r.online_time || "–")}</td><td class="small nowrap">${esc(r.replay_time || "–")}</td><td class="num">${r.status === "both" ? hrs(r.diff_h) : `<span class="muted">${esc(r.status)}</span>`}</td></tr>`).join("")}</tbody>`, 520),
      { sub: `Times are the data's own (estimated from timestamps in the code), to the minute. Highlighted rows differ by more than ${esc(c.tolerance_h)} h or are in one side only.` })}
    ${card("Where it approximates, and the memory bounds", `<ul class="ew-adv">${d.approximations.map((a) => `<li class="small">${esc(a)}</li>`).join("")}</ul>
      <p class="small">Evictions: ${Object.entries(d.memory).filter(([k, v]) => v.evicted).map(([k, v]) => `${esc(k)} ${fmt(v.evicted)}`).join(", ") || "none, no cap was reached on this dataset"}. Caps: ${Object.entries(d.caps).map(([k, v]) => `${esc(k)} ${fmt(v)}`).join(", ")}.</p>`)}`;
}

const SECS = [
  { id: "ew_main", title: "Main alarms", blurb: "The four simple alarms (new host, secrets search, distinct actors, volume) on this dataset, their benign false alarms and the pre-registered forward test; then who shares control, as context.", render: renderMain },
  { id: "earlywarn", title: "Frozen signs", blurb: "The main alarms with their frozen parameters, and every sign and default rule as they stood on one date, so later tests cannot move the goalposts.", render: renderFrozen },
  { id: "ew_forward", title: "Forward test", blurb: "The v2.2.0 run: the simple alarms and the frozen signs on data they were not written on, with the lead before the first true harm and the first true message.", render: renderForward },
  { id: "ew_false", title: "False alarms", blurb: "How often each alarm, sign and rule fires per day on swarms that never coordinate, with how much was observed.", render: renderFalse },
  { id: "ew_cost", title: "Cost curve", blurb: "Lead time against false alarms for every alarm and rule family and threshold: what an operator buys at each alarm budget.", render: renderCost },
  { id: "ew_online", title: "Online mode", blurb: "A streaming monitor with bounded memory: the four main alarms first, then the signs of shared control as context, checked against the replay.", render: renderOnline },
];
for (const x of SECS) window.FX_SECTIONS.push({ ...x, group: G });
})();

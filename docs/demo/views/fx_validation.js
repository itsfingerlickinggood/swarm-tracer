// fx_validation: "How accurate is the tool?" — the saved validation summary (agenttrace.validation),
// drawn as range bars (min–max over seeds, a dot at the median) per simulated-swarm setting.
(() => {
  "use strict";
  GLOSSARY.validation_range = ["Range over seeds", "Each simulated setting is generated with several random seeds. The bar runs from the lowest to the highest value over those seeds; the dot is the median."];
  GLOSSARY.benign_swarm = ["Benign swarm", "A simulated swarm whose agents work in parallel on their own tasks and never coordinate: no agent reads what another wrote and no token is carried. Anything the tool flags there is a false positive."];
  GLOSSARY.direct_evidence = ["Direct evidence (identity)", "Evidence that ties two tokens to one stream of work: both used in one record, both inside one small thread, or one carrying the other's token before its first use. Shared places, shared programs and handoffs are not direct: coordinating agents share those too."];

  const fmtV = (v, unit) => v == null ? "–" : unit === "share" ? Math.round(100 * v) + "%" : unit === "hours" ? (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1)) + " h" : fmt(v);
  const rangeText = (r, unit) => !r ? "–" : r.min === r.max ? fmtV(r.median, unit) : `${fmtV(r.min, unit)} – <b>${fmtV(r.median, unit)}</b> – ${fmtV(r.max, unit)}`;
  const rangeKpi = (r, unit) => !r ? "–" : r.min === r.max ? fmtV(r.median, unit) : `<span class="nowrap">min ${fmtV(r.min, unit)} · median <b>${fmtV(r.median, unit)}</b> · max ${fmtV(r.max, unit)}</span>`;

  // one measure: a row per setting, a bar from min to max and a dot at the median
  function rangeChart(m, rows) {
    const vals = rows.flatMap((r) => r.r ? [r.r.min, r.r.max] : []);
    if (!vals.length) return `<p class="muted">No setting produced this measure.</p>`;
    let lo = 0, hi = 1;
    if (m.unit !== "share") { lo = Math.min(0, ...vals); hi = Math.max(0, ...vals); if (hi === lo) hi = lo + 1; }
    const X = (v) => (100 * (v - lo) / (hi - lo)).toFixed(2);
    const zero = m.unit !== "share" && lo < 0 ? `<i class="vz" style="left:${X(0)}%"></i>` : "";
    const good = m.better === "up" ? "higher is better" : m.better === "down" ? "lower is better" : "";
    return `<div class="vrc">${rows.map((r) => {
      const t = r.r ? `${r.label}: ${r.r.min === r.r.max ? fmtV(r.r.median, m.unit) : `min ${fmtV(r.r.min, m.unit)}, median ${fmtV(r.r.median, m.unit)}, max ${fmtV(r.r.max, m.unit)}`} over ${r.r.n} seed${r.r.n === 1 ? "" : "s"}` : `${r.label}: not measured`;
      return `<div class="vr${r.all ? " all" : ""}" title="${esc(t)}"><span class="vl">${esc(r.label)}</span><span class="vt">${zero}${r.r ? `<i class="vb" style="left:${X(r.r.min)}%;width:${Math.max(0.6, X(r.r.max) - X(r.r.min))}%"></i><i class="vd" style="left:${X(r.r.median)}%"></i>` : ""}</span><span class="vv">${rangeText(r.r, m.unit)}</span></div>`;
    }).join("")}<div class="vax"><span></span><span class="vaxin"><span>${fmtV(lo, m.unit)}</span><em>${good}</em><span>${fmtV(hi, m.unit)}</span></span><span></span></div></div>`;
  }

  function groupCard(sm, g) {
    const M = Object.fromEntries(sm.measures.map((m) => [m.key, m]));
    const ident = g.name === "Identity merging";
    const sets = sm.settings.filter((x) => ident || x.mode !== "benign");
    const blocks = g.keys.map((k) => {
      const m = M[k];
      const rows = sets.map((x) => ({ label: x.label, r: x.measures[k] }));
      rows.push({ label: "all coordinated swarms", r: sm.overall[k], all: true });
      return `<div class="vm"><h4>${esc(m.label)}</h4>${rangeChart(m, rows)}</div>`;
    }).join("");
    return card(esc(g.name), `<div class="vgrid">${blocks}</div>`);
  }

  function identityCard(sm) {
    const ip = sm.identity_pooled;
    const rows = ["high", "medium", "low", "direct_rule"].map((b) => {
      const x = ip[b] || {};
      const ci = x.precision_ci;
      const ev = Object.entries(x.wrong_pairs_evidence || {}).slice(0, 4).map(([k, v]) => `${esc(human(k))} ${fmt(v)}`).join(", ");
      const col = x.precision == null ? BASE : x.precision >= 0.8 ? "#0f766e" : x.precision >= 0.5 ? "#b7791f" : HARM;
      return [b === "direct_rule" ? term("direct_evidence", "direct-evidence rule (what-if)") : esc(b), fmt(x.proposed), fmt(x.correct),
        `${meter(x.precision, col)} <b>${pct(x.precision)}</b>${ci ? ` <span class="muted">(${pct(ci[0])}–${pct(ci[1])})</span>` : ""}`, ev || "–"];
    });
    const hi = ip.high || {};
    const verdict = hi.precision == null ? "No pair was proposed as high." :
      hi.precision >= 0.8 ? `“High” is right ${pct(hi.precision)} of the time on these swarms (target 80%).` :
      `“High” is right only ${pct(hi.precision)} of the time here (${fmt(hi.correct)} of ${fmt(hi.proposed)}), below the 80% target: treat high merges as leads, not facts.`;
    return card("Identity merges by confidence band, all runs pooled",
      `<p class="${hi.precision != null && hi.precision < 0.8 ? "warn" : "muted"}">${verdict}</p>` +
      table(["band", "pairs proposed", "really one agent", "precision (95% range)", "evidence on the wrong pairs"], rows),
      { sub: `Each pair the Agents tab proposes is checked against the simulation, which knows which tokens one agent holds. The direct-evidence row is a what-if: the same proposals, kept only when they rest on a shared record, a small shared thread or a carried token. In these simulations an agent's threads never mix agents, so that row is optimistic.` });
  }

  function benignCard(sm) {
    const b = sm.benign;
    if (!b || !b.runs) return card("Benign baseline", `<p class="muted">This summary has no benign swarms.</p>`);
    const items = b.fires.map((x) => ({
      label: `${x.what === "rule" ? `<b>rule</b> ` : ""}${esc(x.name)}`,
      value: x.runs, color: x.what === "rule" ? HARM : (x.kind === "harm" ? HARM : x.family === "baseline" ? BASE : ACCENT),
      title: `${x.name}: fired on ${x.runs} of ${x.of} benign swarms${x.hours_from_start ? `, median ${x.hours_from_start.median} h after the start` : ""}${x.example ? ` — e.g. ${x.example}` : ""}`,
    }));
    const by = Object.entries(b.by_setting || {}).map(([k, v]) => {
      const lab = (sm.settings.find((s) => s.name === k) || {}).label || k;
      const rf = Object.entries(v.rules_fired || {});
      return `<li><b>${esc(lab)}</b> (${plural(v.runs, "swarm")}): ${rf.length ? rf.map(([id, n]) => `${esc(id)} ${n}×`).join(", ") : "no default rule fired"}</li>`;
    }).join("");
    return card(`What fires on ${term("benign_swarm", "benign swarms")}`,
      `<div class="kpis">${kpi("benign swarms", fmt(b.runs))}${kpi("messages between different agents", rangeKpi(b.messages_between_agents, "count"))}${kpi("messages between two tokens of one agent", rangeKpi(b.messages_one_agent_two_tokens, "count"))}${kpi("records the pack calls harmful", rangeKpi(b.harm_records_flagged, "count"))}</div>` +
      hbars(items, { max: Math.max(1, ...b.fires.map((x) => x.of)), unit: ` of ${b.runs}` }) + `<ul class="vlist">${by}</ul>`,
      { sub: `Every sign and default alert rule that fired on a swarm with no coordination at all is a false positive. Bars count the benign swarms (of ${b.runs}) where each one fired.` });
  }

  let which = "";
  function signsCard(sm) {
    if (!sm.signs || !sm.signs.length) return "";
    const rows = sm.signs.map((y) => [esc(y.name), `${fmt(y.found)} of ${fmt(y.runs)}`,
      `${meter(y.runs ? y.on_time / y.runs : null, y.on_time / Math.max(1, y.runs) >= 0.8 ? "#0f766e" : y.on_time / Math.max(1, y.runs) >= 0.5 ? "#b7791f" : HARM)} ${fmt(y.on_time)} of ${fmt(y.runs)}`,
      rangeText(y.error_hours, "hours")]);
    return card("Each early sign on the coordinated swarms", table(["sign", "found", "within 1 hour of the truth", "tool time minus true time (min – median – max)"], rows),
      { sub: "A negative error means the tool names the sign before it truly happened: something that only looks like it (a note naming a board, a wrongly matched message) came first." });
  }

  async function render(host) {
    let sm;
    try { sm = await api("/api/x/validation_summary" + (which ? "?which=" + which : "")); } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    const runBtn = `<button type="button" id="vrun"${sm.running ? " disabled" : ""}>${sm.running ? "Running…" : "Run a quick check (1 seed, 20 agents)"}</button>`;
    if (!sm.available) {
      host.innerHTML = card("No validation results yet", `<p>${esc(sm.why || "")} Run the full suite from a terminal:</p><pre>${esc(sm.command || "")}</pre><p>or ${runBtn} here (about ten seconds).</p>${sm.error ? `<p class="warn">${esc(sm.error)}</p>` : ""}`);
      bind(host);
      return;
    }
    const groups = sm.groups.map((g) => groupCard(sm, g)).join("");
    host.innerHTML =
      `<div class="kpis">${kpi("coordinated swarms", fmt(sm.coordinated_runs))}${kpi("benign swarms", fmt(sm.benign_runs))}${kpi("seeds per setting", fmt((sm.seeds || []).length), (sm.seeds || []).join(", "))}${kpi("generated", esc((sm.generated || "").replace("T", " ").replace("Z", " UTC")), sm.quick ? "quick run: 20 agents at most" : "")}</div>` +
      `<p class="muted">Simulated swarms with known truth (${term("validation_range", "ranges over seeds")}), loaded with the tool exactly as the app loads a file. The simulations are ours: real swarms differ, so read these as how the tool behaves on swarms shaped like these, not as its accuracy on yours. From <code>${esc(sm.command || "")}</code>. ${runBtn}${sm.has_full && sm.has_quick ? ` <a href="#" id="vwhich">${sm.quick ? "Show the full suite" : "Show the last quick check"}</a>` : ""}</p>` +
      (sm.error ? `<p class="warn">${esc(sm.error)}</p>` : "") +
      identityCard(sm) + benignCard(sm) + signsCard(sm) + groups;
    bind(host);
  }

  function bind(host) {
    const w = host.querySelector("#vwhich");
    if (w) w.addEventListener("click", (e) => { e.preventDefault(); which = which === "quick" ? "" : "quick"; render(host); });
    const b = host.querySelector("#vrun");
    if (!b) return;
    b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Running…";
      try { await api("/api/x/validation_run", { method: "POST", body: "{}" }); } catch (e) { b.textContent = e.message; return; }
      const poll = async () => {
        const s = await api("/api/x/validation_summary?which=quick").catch(() => null);
        if (s && !s.running) { which = "quick"; render(host); return; }
        setTimeout(poll, 1500);
      };
      setTimeout(poll, 1500);
    });
  }

  window.FX_SECTIONS = window.FX_SECTIONS || [];
  window.FX_SECTIONS.push({
    id: "validation", title: "How accurate is the tool?", group: "Test and export",
    blurb: "Message links, sign timing, dating and identity merges scored against simulated swarms whose truth is known, plus what fires on benign swarms that never coordinate.",
    render,
  });
})();

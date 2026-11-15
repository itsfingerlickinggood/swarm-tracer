// fx_benchmark: "Audited links (real data)" — the tool's message links on the Swarm Traces release scored
// against links read and labelled by hand (agenttrace/benchmark.py, agenttrace/claims/audited_links.json),
// and v1.1.0's rules next to the current code on the harder simulated swarms.
(() => {
  "use strict";
  GLOSSARY.audited_link = ["Audited link", "A message link the tool reported on the Swarm Traces release (between two named tokens, or with an anonymous run: on one side), checked by reading the write record and the read record: is the write a commit, upload, POST or PUT to that same place, is the read a fetch of it, is it the same repository."];
  GLOSSARY.wilson_range = ["95% range", "A Wilson interval: the range of true rates that would plausibly give this count. With few links it is wide; 0 of 18 still allows a true precision up to about 18%."];
  GLOSSARY.audit_pool = ["Audited pool", "Only links that some version of the tool reported were read. Recall here means: of the links in that pool found to be true, how many the current code still reports. True messages no version ever reported are not in it."];

  const COL = { true_message: "#0f766e", false_write: "#c2410c", false_write_lfs_or_urlopen: "#d9822b", different_repo: "#7c5cbf",
    comment_only: "#8a94a0", read_not_a_read: "#b7791f", unclear: "#b8c0c8", not_audited: "#5b6672" };
  const p0 = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
  const rateText = (r) => !r || r.value == null ? "–" : `${p0(r.value)}`;
  const rateSub = (r) => !r || r.value == null ? "nothing to score" : `${fmt(r.k)} of ${fmt(r.n)} · ${term("wilson_range", "95% range")} ${p0(r.ci[0])}–${p0(r.ci[1])}`;
  // a 0–100% track with the interval as a band and the value as a dot
  const ciBar = (r, color = ACCENT) => !r || r.value == null ? "" :
    `<span class="bmci" title="${esc(`${p0(r.value)} (${r.k} of ${r.n}); 95% range ${p0(r.ci[0])}–${p0(r.ci[1])}`)}"><i class="band" style="left:${100 * r.ci[0]}%;width:${Math.max(1, 100 * (r.ci[1] - r.ci[0]))}%;background:${color}"></i><i class="dot" style="left:${100 * r.value}%;background:${color}"></i></span>`;
  const tile = (label, r, color, sub2 = "") => `<div class="kpi bmk"><b style="color:${color}">${rateText(r)}</b><span>${label}</span><em>${rateSub(r)}</em>${ciBar(r, color)}${sub2 ? `<em>${sub2}</em>` : ""}</div>`;
  const snippet = (s) => `<code class="bmsnip">${esc(s || "")}</code>`;

  const simRate = (x) => !x || !x.found ? null : { value: x.precision, k: x.correct, n: x.found, ci: x.precision_ci };
  const GRADE_NAME = { direct: "direct", inferred: "inferred", weak: "weak" };
  const GRADE_WHAT = { direct: "the write verb and the read verb both sit in the very call that names the place", inferred: "a verb was found, but through a variable, a helper, an LFS operation or nearby text", weak: "a default: no verb found, a merged place, or an estimated time more than an hour from the other side" };
  const GRADE_COL = { direct: "#0f766e", inferred: "#3b82a0", weak: "#b7791f" };

  function groupsCard(d) {
    const g = d.groups, rows = [["named_named", "between two named tokens"], ["involves_run", "an anonymous run: on one side"], ["all", "all deliveries"]];
    const body = rows.map(([k, name]) => { const x = g[k], r = x.precision;
      return `<div class="bmg"><span class="bmgl">${esc(name)} <span class="muted">· ${fmt(x.reported)} reported${x.unclear ? `, ${fmt(x.unclear)} unclear left out` : ""}${x.not_audited ? `, ${fmt(x.not_audited)} not audited` : ""}</span></span><span class="bmgv">${ciBar(r, k === "all" ? ACCENT : "#0f766e")} <b>${p0(r.value)}</b> <em class="muted">${r.value == null ? "nothing to score" : `${fmt(r.k)} of ${fmt(r.n)} · ${p0(r.ci[0])}–${p0(r.ci[1])}`}</em></span></div>`; }).join("");
    return card("Precision for each kind of message", body,
      { sub: `Every delivery the code reports on this release was read by hand, not only those between named tokens: ${fmt(g.all.reported)} in all. The audit holds ${fmt(g.pool.named_named.links)} links between named tokens and ${fmt(g.pool.involves_run.links)} with an anonymous run: endpoint.` });
  }

  function gradeCard(d) {
    const sg = ((d.simulator_grades || {}).realworld) || null, simAll = ((d.simulator_grades || {}).all) || null;
    const rows = Object.keys(GRADE_NAME).map((k) => ({ k, a: d.by_grade[k].precision, s: simRate(sg && sg[k]), x: d.by_grade[k] }));
    const ranges = rows.flatMap((r) => [r.a, r.s]).filter((r) => r && r.value != null);
    const sep = (list) => list.some((a) => list.some((b) => a !== b && a.ci[0] > b.ci[1]));
    const sepAudit = sep(rows.map((r) => r.a).filter((r) => r && r.value != null)), sepSim = sep(rows.map((r) => r.s).filter((r) => r && r.value != null));
    const body = rows.map((r) => `<div class="bmsim"><h4><span class="bmdot" style="background:${GRADE_COL[r.k]}"></span>${esc(GRADE_NAME[r.k])} <span class="muted">${esc(GRADE_WHAT[r.k])}</span></h4>` +
      `<div class="bmsr"><span>audit</span><span>${ciBar(r.a, GRADE_COL[r.k])} <b>${p0(r.a.value)}</b> <em class="muted">${r.a.value == null ? "none reported" : `${fmt(r.a.k)} of ${fmt(r.a.n)} · ${p0(r.a.ci[0])}–${p0(r.a.ci[1])}`}</em></span><span class="muted">${fmt(r.x.reported)} reported</span></div>` +
      `<div class="bmsr"><span>simulated</span><span>${r.s ? ciBar(r.s, GRADE_COL[r.k]) : ""} <b>${r.s ? p0(r.s.value) : "–"}</b> <em class="muted">${r.s ? `${fmt(r.s.k)} of ${fmt(r.s.n)} · ${p0(r.s.ci[0])}–${p0(r.s.ci[1])}` : "no simulated run saved"}</em></span><span class="muted">real-world-style swarms</span></div></div>`).join("");
    const verdict = (sepAudit || sepSim) ? "At least two grades have ranges that do not overlap, so the grade carries some information." : "The ranges overlap on both the audit and the simulated swarms: the grade does not tell a reader which messages to believe more. It records how the verb was found, nothing more.";
    return card("Does the confidence grade tell you anything?", `<p class="muted">${esc(verdict)}</p>${body}`,
      { sub: "Each message carries one grade (the last column of the message list). Precision per grade on the audited links, and on the simulated swarms where the truth is exact. Unclear links are left out." });
  }

  function agreeCard(d) {
    const ind = d.independent;
    if (!ind) return "";
    const m = ind.decided.matrix, n = ind.decided.n, a = ind.decided.agreement;
    const cell = (v, bad) => `<td class="bmcell${bad ? " bad" : ""}" style="background:rgba(${bad ? "194,65,12" : "15,118,110"},${Math.min(0.8, 0.08 + 0.72 * v / Math.max(1, n)).toFixed(2)})"><b>${fmt(v)}</b></td>`;
    const mat = `<table class="bmmx"><thead><tr><th></th><th>independent method: message</th><th>independent method: not a message</th></tr></thead><tbody>` +
      `<tr><th>read as a true message</th>${cell(m.true_yes, false)}${cell(m.true_no, true)}</tr>` +
      `<tr><th>read as not a message</th>${cell(m.false_yes, true)}${cell(m.false_no, false)}</tr></tbody></table>`;
    const dis = ind.disagreements.length ? `<ul class="bmlist">${ind.disagreements.slice(0, 8).map((r) => `<li>${ent.rec(r.write_id)} → ${ent.rec(r.read_id)} <span class="muted">(${esc(r.label.replace(/_/g, " "))})</span>: ${esc(r.independent)}</li>`).join("")}</ul>` : "";
    return card("Independent method agreement", `<p><b>${p0(a.value)}</b> raw agreement (${fmt(a.k)} of ${fmt(a.n)}, ${p0(a.ci[0])}–${p0(a.ci[1])}), kappa <b>${ind.decided.kappa == null ? "–" : ind.decided.kappa.toFixed(2)}</b>. ${fmt(ind.unclear_links)} unclear links are left out${ind.unclear_called_message ? `; the second method calls ${fmt(ind.unclear_called_message)} of them messages` : ""}.</p>${mat}${dis}`,
      { sub: `A second method, not a second person: ${esc(ind.method)} It was fixed twice after its first disagreements were read, so its agreement is a little flattering. ${fmt(ind.disagreements.length)} disagreement${ind.disagreements.length === 1 ? "" : "s"}.` });
  }

  function trustCard(d) {
    const g = d.groups, nn = g.named_named.precision, rn = g.involves_run.precision;
    const part = (r) => r.value == null ? "none" : `${fmt(r.k)} of ${fmt(r.n)}`;
    return card("What a reader may trust", `<p>On this release the tool now reports ${fmt(g.all.reported)} messages. The reading found ${part(nn)} of those between named tokens to be real and ${part(rn)} of those involving an anonymous run; ${fmt(g.all.unclear)} could not be decided. ` +
      `Treat each as a lead that was checked once, not as proof: the labelling is one person's reading, the rules were changed while looking at these same links (so the rates are optimistic), and many true links share one writer. ` +
      `The grade does not change that. Nothing here says how many true messages the tool misses outside the audited pool.</p>`);
  }

  function labelCard(d) {
    const rows = d.confusion.filter((c) => c.audited || c.label === "true_message");
    const total = d.audited_links;
    const bars = hbars(rows.map((c) => ({ label: `<span class="bmdot" style="background:${COL[c.label] || BASE}"></span>${esc(c.name)}`, value: c.audited, color: COL[c.label] || BASE, title: c.what })), { total });
    const falses = rows.filter((c) => c.label !== "true_message" && c.label !== "unclear").reduce((a, c) => a + c.audited, 0);
    const tr = (rows.find((c) => c.label === "true_message") || {}).audited || 0;
    return card(`What the ${fmt(total)} ${term("audited_link", "audited links")} turned out to be`,
      `<p class="${tr / Math.max(1, total) < 0.5 ? "warn" : "muted"}"><b>${fmt(tr)}</b> of ${fmt(total)} is a true message; <b>${fmt(falses)}</b> are false in one of the ways below; ${fmt(total - tr - falses)} could not be decided.</p>` +
      stackbar(rows.map((c) => ({ label: c.name, value: c.audited, color: COL[c.label] || BASE })), { legend: false, h: 16 }) + bars +
      `<ul class="bmlist">${rows.map((c) => `<li><b>${esc(c.name)}</b>: ${esc(c.what)}</li>`).join("")}</ul>`,
      { sub: `${esc(d.audit.how || "")}` });
  }

  function thenNowCard(d) {
    const tv = d.then_vs_now, labs = d.confusion.map((c) => c.label).concat(tv.now.by_label.not_audited ? ["not_audited"] : []);
    const name = (k) => k === "not_audited" ? "not audited yet" : (d.confusion.find((c) => c.label === k) || {}).name || k;
    const mx = Math.max(tv.v110.reported, tv.now.reported, 1);
    const row = (title, v) => `<div class="bmtn"><span class="bmtl"><b>${esc(title)}</b> ${fmt(v.reported)} links</span><span class="bmtt"><span class="bmts" style="width:${(100 * v.reported / mx).toFixed(2)}%">${labs.filter((k) => v.by_label[k]).map((k) => `<i style="width:${(100 * v.by_label[k] / Math.max(1, v.reported)).toFixed(3)}%;background:${COL[k] || BASE}" title="${esc(`${name(k)}: ${v.by_label[k]}`)}"></i>`).join("")}</span></span><span class="bmtv">precision ${rateText(v.precision)} <span class="muted">(${v.precision.k}/${v.precision.n})</span></span></div>`;
    const tbl = table(["what the reading found", "audited", "reported at v1.1.0", "reported now"],
      d.confusion.filter((c) => c.audited).map((c) => [`<span class="bmdot" style="background:${COL[c.label] || BASE}"></span>${esc(c.name)}`, fmt(c.audited), fmt(c.v110), c.label === "true_message" || !c.now ? fmt(c.now) : `<b class="bmbad">${fmt(c.now)}</b>`]));
    return card("Then and now", `${row("v1.1.0", tv.v110)}${row("now (between named tokens)", tv.now)}<div class="legend">${labs.filter((k) => tv.v110.by_label[k] || tv.now.by_label[k]).map((k) => `<span><i style="background:${COL[k] || BASE}"></i>${esc(name(k))}</span>`).join("")}</div>${tbl}`,
      { sub: `v1.1.0 reported ${fmt(tv.v110.reported)} messages between named tokens; the current code reports ${fmt(tv.now.reported)}: ${fmt(tv.kept)} of the old ones kept, ${fmt(tv.dropped)} dropped, ${fmt(tv.new)} new. Bars share one scale; colours are what the reading found.` });
  }

  function disagreeCard(d) {
    const rows = d.disagreements || [];
    if (!rows.length) return card("Where the current code and the reading disagree", `<p class="muted">Nowhere: every audited link the code reports was read as true, and no true link is dropped.</p>`);
    const body = rows.map((r) => {
      const kept = r.reported_now;
      return `<div class="bmrow"><div class="bmhead"><span class="bmtag" style="background:${COL[r.label] || BASE}">${esc((d.confusion.find((c) => c.label === r.label) || {}).name || r.label)}</span> <span class="bmverdict">${kept ? "the code reports it; the reading says it is not a message" : "the code drops it; the reading says it is a message"}</span></div>` +
        `<div class="bmpair">${ent.actor(r.from)} wrote in ${ent.rec(r.write_id)} → ${ent.actor(r.to)} read in ${ent.rec(r.read_id)}${r.latency_h != null ? ` <span class="muted">${esc(String(r.latency_h))} h apart</span>` : ""}</div>` +
        `<div class="bmwhy">${esc(r.reason)}</div><div class="bmsn"><span>write</span>${snippet(r.write_snippet)}<span>read</span>${snippet(r.read_snippet)}</div></div>`;
    }).join("");
    const n1 = rows.filter((r) => r.reported_now).length;
    return card(`Where the current code and the reading disagree (${fmt(rows.length)})`, body,
      { sub: `${fmt(n1)} link${n1 === 1 ? "" : "s"} the code reports that the reading calls false, ${fmt(rows.length - n1)} it drops that the reading calls true. These are the rows to check first: click a record to read it. Snippets are the first mention of the place in each record.` });
  }

  function simCard(sim) {
    if (!sim || !(sim.settings || []).length) return card("Old rules against the current code on simulated swarms", `<p class="muted">No comparison saved. Run <code>python3 -m agenttrace.validation old-rules --worktree DIR</code> with a checkout of v1.1.0.</p>`);
    const ov = esc(sim.old_version || "old");
    const rows = sim.settings.map((x) => {
      if (x.mode === "benign") {
        const mx = Math.max(1, x.old.between_agents, x.now.between_agents);
        const bar = (v, c) => `<span><span class="bmcnt"><i style="width:${(100 * v / mx).toFixed(2)}%;background:${c}"></i></span> <b>${fmt(v)}</b></span>`;
        return `<div class="bmsim"><h4>${esc(x.label)} <span class="muted">(${fmt(x.runs)} swarms, no true message)</span></h4><div class="bmsr"><span>${ov}</span>${bar(x.old.between_agents, HARM)}<span class="muted">false links between different agents</span></div><div class="bmsr"><span>now</span>${bar(x.now.between_agents, ACCENT)}<span class="muted">false links between different agents</span></div></div>`;
      }
      const R = (v, k, n) => ({ value: v[k], k: v.correct, n: v[n], ci: v[k + "_ci"] });
      const line = (who, v, c) => `<div class="bmsr"><span>${who}</span><span class="bmtwo"><span>precision ${ciBar(R(v, "precision", "found"), c)} <b>${p0(v.precision)}</b> <em class="muted">${p0(v.precision_ci[0])}–${p0(v.precision_ci[1])}</em></span><span>recall ${ciBar(R(v, "recall", "true"), c)} <b>${p0(v.recall)}</b> <em class="muted">${p0(v.recall_ci[0])}–${p0(v.recall_ci[1])}</em></span></span></div>`;
      return `<div class="bmsim"><h4>${esc(x.label)} <span class="muted">(${fmt(x.runs)} swarms, ${fmt(x.now.true)} true messages)</span></h4>${line(ov, x.old, HARM)}${line("now", x.now, ACCENT)}</div>`;
    }).join("");
    return card("Old rules against the current code on simulated swarms", rows,
      { sub: `The earlier simulated swarms could not tell ${ov} from the current code: both score the same on the default setting. The real-world settings add the payload shapes found in this audit, with the truth still exact. Pooled over seeds; ranges are 95%.` });
  }

  async function render(host) {
    let d;
    try { d = await api("/api/x/benchmark"); } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (!d.applies) {
      const c = (d.audit || {}).counts;
      host.innerHTML = card("This audit is of another dataset", `<p>${esc(d.why || "The loaded dataset is not the Swarm Traces release.")}</p>` +
        (c ? `<p class="muted">The audited file holds ${fmt(Object.values(c).reduce((a, b) => a + b, 0))} links from that release, ${fmt(c.true_message || 0)} of them read as true messages (labelled ${esc(d.audit.made || "")}; ${esc(d.audit.labelled_by || "")}). Load the release to score the current code against it.</p>` : "")) + simCard(d.simulator);
      return;
    }
    const tv = d.then_vs_now, pr = d.precision, bad = pr.value != null && pr.value < 0.5, g = d.groups;
    host.innerHTML =
      `<div class="kpis">${tile("precision, all deliveries", pr, bad ? HARM : "#0f766e", d.reported_now_unclear ? `${fmt(d.reported_now_unclear)} unclear left out` : "")}` +
      `${tile("between two named tokens", g.named_named.precision, "#0f766e")}` +
      `${tile("an anonymous run: on one side", g.involves_run.precision, "#0f766e")}` +
      `${kpi("messages on the release", `${fmt(d.reported_now)}`, `v1.1.0 reported ${fmt(tv.v110.reported)} between named tokens`)}` +
      `${kpi("links audited by hand", fmt(d.audited_links), `labelled ${esc(d.audit.made || "")}`)}</div>` +
      `<p class="${bad ? "warn" : "muted"}">${bad ? `Of the ${fmt(pr.n)} links the current code reports here that could be decided, the reading found ${fmt(pr.k)} to be a message. Treat message links on this dataset as leads to open and read, not as findings.` : `The reading agrees with ${fmt(pr.k)} of the ${fmt(pr.n)} links the current code reports that could be decided.`} ` +
      `Recall within the ${term("audit_pool", "audited pool")}: ${rateText(d.recall)} (${fmt(d.recall.k)} of ${fmt(d.true_links_in_pool)} true links). ` +
      `Limits: ${esc((d.audit.limits || []).join("; "))}. Labelled by: ${esc(d.audit.labelled_by || "")}.${d.reported_now_not_audited ? ` <b>${fmt(d.reported_now_not_audited)} link${d.reported_now_not_audited === 1 ? "" : "s"} reported now ${d.reported_now_not_audited === 1 ? "is" : "are"} not in the audit yet</b> and ${d.reported_now_not_audited === 1 ? "is" : "are"} left out of the rates.` : ""}</p>` +
      trustCard(d) + groupsCard(d) + gradeCard(d) + agreeCard(d) + labelCard(d) + thenNowCard(d) + disagreeCard(d) + simCard(d.simulator);
  }

  window.FX_SECTIONS = window.FX_SECTIONS || [];
  window.FX_SECTIONS.push({
    id: "benchmark", title: "Audited links (real data)", group: "Test and export",
    blurb: "Every message the tool reports on the Swarm Traces release, scored against links read and labelled by hand: precision with ranges for each kind of endpoint and each confidence grade, a second method's agreement, what each false link was, v1.1.0 against now, and the rows where the code and the reading disagree.",
    render,
  });
})();

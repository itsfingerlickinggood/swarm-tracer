// fx_benchmark: "Audited links (real data)" — the tool's message links on the Swarm Traces release scored
// against links read and labelled by hand (agenttrace/benchmark.py, agenttrace/claims/audited_links.json),
// and v1.1.0's rules next to the current code on the harder simulated swarms.
(() => {
  "use strict";
  GLOSSARY.audited_link = ["Audited link", "A message link the tool reported between two named tokens on the Swarm Traces release, checked by reading the write record and the read record: is the write a commit, upload, POST or PUT to that same place, is the read a fetch of it, is it the same repository."];
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
    return card("Then and now", `${row("v1.1.0", tv.v110)}${row("now", tv.now)}<div class="legend">${labs.filter((k) => tv.v110.by_label[k] || tv.now.by_label[k]).map((k) => `<span><i style="background:${COL[k] || BASE}"></i>${esc(name(k))}</span>`).join("")}</div>${tbl}`,
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
    const tv = d.then_vs_now, pr = d.precision, bad = pr.value != null && pr.value < 0.5;
    host.innerHTML =
      `<div class="kpis">${tile("precision now: reported links read as true", pr, bad ? HARM : "#0f766e", d.reported_now_unclear ? `${fmt(d.reported_now_unclear)} unclear left out` : "")}` +
      `${tile(`recall now, within the ${term("audit_pool", "audited pool")}`, d.recall, d.recall.value ? "#0f766e" : HARM, `${fmt(d.true_links_in_pool)} true link${d.true_links_in_pool === 1 ? "" : "s"} in the pool`)}` +
      `${kpi("links between named tokens", `${fmt(tv.v110.reported)} → ${fmt(tv.now.reported)}`, "v1.1.0 → now")}` +
      `${kpi("links audited by hand", fmt(d.audited_links), `labelled ${esc(d.audit.made || "")}`)}</div>` +
      `<p class="${bad ? "warn" : "muted"}">${bad ? `Of the ${fmt(pr.n)} links the current code reports here that could be decided, the reading found ${fmt(pr.k)} to be a message. Treat message links on this dataset as leads to open and read, not as findings.` : `The reading agrees with ${fmt(pr.k)} of the ${fmt(pr.n)} links the current code reports.`} ` +
      `Limits: ${esc((d.audit.limits || []).join("; "))}. Labelled by: ${esc(d.audit.labelled_by || "")}.${d.reported_now_not_audited ? ` <b>${fmt(d.reported_now_not_audited)} link${d.reported_now_not_audited === 1 ? "" : "s"} reported now ${d.reported_now_not_audited === 1 ? "is" : "are"} not in the audit yet</b> and ${d.reported_now_not_audited === 1 ? "is" : "are"} left out of the rates.` : ""}</p>` +
      labelCard(d) + thenNowCard(d) + disagreeCard(d) + simCard(d.simulator);
  }

  window.FX_SECTIONS = window.FX_SECTIONS || [];
  window.FX_SECTIONS.push({
    id: "benchmark", title: "Audited links (real data)", group: "Test and export",
    blurb: "The tool's message links on the Swarm Traces release, scored against links read and labelled by hand: precision and recall with ranges, what each false link was, v1.1.0 against now, and the rows where the code and the reading disagree.",
    render,
  });
})();

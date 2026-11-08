// What's missing: the blind spots, measured. Each gap is drawn with how much of the data it affects,
// which question it limits, what it could hide and what would close it. The AI investigator can audit
// them against the incident reports; its answer comes back as gap cards with checked record ids.
"use strict";
(() => {
  const Q = { "who talked to whom": { c: ACCENT, tab: "network" }, "how information spread": { c: "#0f766e", tab: "spread" }, "early flag": { c: "#c2410c", tab: "early" }, all: { c: "#5b6672", tab: null } };
  async function gaps(el, s) {
    el.innerHTML = '<p class="muted">Loading…</p>';
    const { rows } = await cached("/api/gaps");
    const measured = rows.filter((r) => r.share != null).sort((a, b) => b.share - a.share);
    const counted = rows.filter((r) => r.share == null && r.count != null);
    const open = rows.filter((r) => r.count == null);
    const f = s.flow;
    el.innerHTML = `
    <h2>What an investigator would still miss</h2>
    <p class="lead">The tool reconstructs only what the records show. ${measured.length ? `The largest measured gap: <b>${esc(measured[0].gap.toLowerCase())}</b>, ${pct(measured[0].share)} of ${esc(measured[0].unit)}.` : ""} Each gap below says which of the three questions it limits.</p>
    <div class="qkey">${Object.entries(Q).map(([k, v]) => `<span><i style="background:${v.c}"></i>${esc(k)}</span>`).join("")}</div>
    ${card("Measured blind spots", `<div class="gaprows">${measured.map(row).join("")}</div>`, { sub: "Bar: share of the records, messages or places affected." })}
    ${counted.length || open.length ? `<div class="grid2">${[...counted, ...open].map(cardFor).join("")}</div>` : ""}
    ${card("AI gap audit", `<div id="gapai">${S.gapAudit || `<p class="small muted">The investigator reads these measured gaps, the analysis brief${s.pack ? "" : ""} and the incident reports (when linked), then ranks the blind spots for the three questions, with what each could hide and how to close it. Needs an API key in the investigator's Settings.</p>`}</div>`,
      { right: `<button type="button" class="primary" id="gapRun">${S.gapAudit ? "Run again" : "Run the AI gap audit"}</button>` })}
    ${f.overwrites ? card("Every overwrite", '<div id="overList"></div>', { sub: "Edits that replaced another actor's edit without keeping any line it added. Not counted as messages. Click a row to inspect the replacing edit." }) : ""}`;
    el.querySelectorAll("[data-gotab]").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.gotab)));
    $("gapRun").addEventListener("click", runAudit);
    if (f.overwrites) {
      const lv = listView($("overList"), "overwrites", ["replaced", "by", "place", "earlier edit", "replacing edit", "what happened"],
        (o) => [ent.actor(o.from), ent.actor(o.to), ent.place(o.channel), `${ent.rec(o.write_id)} <span class="muted small">${esc(o.write_time || "")}</span>`, `${ent.rec(o.read_id)} <span class="muted small">${esc(o.read_time || "")}</span>`, esc(o.how)],
        [], s.list_totals?.overwrites, (o) => selectEvent(o.read_id));
      lv.reload();
    }
  }
  const qtag = (q) => { const v = Q[q] || Q.all; return `<span class="qtag" style="--c:${v.c}"${v.tab ? ` data-gotab="${v.tab}"` : ""}>${esc(q)}</span>`; };
  function row(r) {
    const c = (Q[r.question] || Q.all).c;
    return `<div class="gaprow"><div class="gl"><b>${esc(r.gap)}</b>${qtag(r.question)}</div>
      <div class="gb"><span class="gbar"><i style="width:${(r.share * 100).toFixed(2)}%;background:${c}"></i></span><b>${pct(r.share)}</b><span class="muted small">${fmt(r.count)} of ${fmt(r.of)} ${esc(r.unit)}</span></div>
      <div class="gt"><span>Hides</span>${esc(r.hides)}</div><div class="gt"><span>To close it</span>${esc(r.close)}</div></div>`;
  }
  function cardFor(r) {
    return `<section class="card gapcard2"><header><h3>${esc(r.gap)}</h3>${qtag(r.question)}</header>
      ${r.count != null ? `<div class="gbig">${fmt(r.count)} <span class="muted small">${esc(r.unit)}</span></div>` : '<div class="gbig muted small">not measurable from these records</div>'}
      <div class="gt"><span>Hides</span>${esc(r.hides)}</div><div class="gt"><span>To close it</span>${esc(r.close)}</div></section>`;
  }
  async function runAudit() {
    const box = $("gapai"), btn = $("gapRun");
    btn.disabled = true;
    box.innerHTML = '<div class="aiwait"><i></i><i></i><i></i> Auditing the gaps against the data and the reports…</div>';
    try {
      const r = await window.askAI("Audit what an investigator would still miss with this data, for the three questions: who talked to whom, how information spread, and whether the coordination could have been flagged early.", { mode: "gaps" });
      const html = r.structured ? window.renderAIStructured(r.structured) : `<pre>${esc(r.content)}</pre>`;
      S.gapAudit = html + `<p class="small muted">${esc($("model").value)}${r.usage?.total_tokens ? " · " + fmt(r.usage.total_tokens) + " tokens" : ""}</p>`;
      box.innerHTML = S.gapAudit;
      btn.textContent = "Run again";
    } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
    finally { btn.disabled = false; }
  }
  VIEWS.gaps = gaps;
})();

// What's missing: the blind spots, measured. Each gap is drawn with how much of the data it affects,
// which question it limits, what it could hide and what would close it. The AI investigator can audit
// them against the incident reports; its answer comes back as gap cards with checked record ids.
"use strict";
(() => {
  const Q = { "who talked to whom": { c: ACCENT, tab: "network" }, "how information spread": { c: C.program, tab: "spread" }, "early flag": { c: PALETTE.sign.baseline, tab: "early" }, all: { c: "#5b6672", tab: null } };
  async function gaps(el, s) {
    el.innerHTML = '<p class="muted">Loading…</p>';
    const { rows } = await cached("/api/gaps");
    if (S.tab !== "gaps") return;
    const measured = rows.filter((r) => r.share != null && r.count > 0).sort((a, b) => b.share - a.share);
    const none = rows.filter((r) => r.share != null && !r.count);
    const counted = rows.filter((r) => r.share == null && r.count != null);
    const open = rows.filter((r) => r.count == null);
    const f = s.flow;
    el.innerHTML = `
    <h2>What an investigator would still miss</h2>
    <p class="lead">The tool reconstructs only what the records show. ${measured.length ? `The largest measured gap: <b>${esc(measured[0].gap.toLowerCase())}</b>, ${pct(measured[0].share)} of ${esc(measured[0].unit)}.` : ""} Each gap below says which of the challenge's three questions it limits: who talked to whom, how information spread, and whether the coordination could have been flagged early.</p>
    <p class="small muted">Words used here: ${term("action")}, ${term("named", "named actor")}, ${term("run", "anonymous run")}, ${term("merged", "merged place")}, ${term("pack")}. A parent link ties a record to the record that started it (its thread).</p>
    <div class="qkey">${Object.entries(Q).map(([k, v]) => `<span><i style="background:${v.c}"></i>${esc(k)}</span>`).join("")}</div>
    ${card("Measured blind spots", `<div class="gaprows">${measured.map(row).join("")}</div>${none.length ? `<p class="small muted">Measured and found empty in this dataset: ${none.map((r) => esc(r.gap.toLowerCase())).join("; ")}.</p>` : ""}`, { sub: "Bar: share of the records, actions, messages or places affected (the unit is given on each row). Under each, the range its gap leaves open for the headline answers.", right: '<button type="button" class="link small" data-sxgo="">Gap sensitivity: how far each gap moves the answers →</button>' })}
    ${counted.length || open.length ? `<div class="grid2">${[...counted, ...open].map(cardFor).join("")}</div>` : ""}
    ${card("AI gap audit", `<div id="gapai">${S.gapAudit || `<p class="small muted">The investigator reads these measured gaps, the analysis brief${s.pack ? "" : ""} and the incident reports (when linked), then ranks the blind spots for the three questions, with what each could hide and how to close it. Needs an API key in the investigator's Settings.</p>`}</div>`,
      { right: `<button type="button" class="primary" id="gapRun">${S.gapAudit ? "Run again" : "Run the AI gap audit"}</button>` })}
    ${f.overwrites ? card("Every overwrite", '<div id="overList"></div>', { sub: "Edits that replaced another actor's edit without keeping any line it added. Not counted as messages. Click a row to inspect the replacing edit." }) : ""}`;
    el.querySelectorAll("[data-gotab]").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.gotab)));
    el.querySelectorAll("[data-gapex]").forEach((b) => b.addEventListener("click", (e) => { if (e.target.closest(".ent,[data-gotab],a")) return; toggleExamples(b.closest("[data-gap]"), rows.find((r) => r.key === b.closest("[data-gap]").dataset.gap)); }));
    $("gapRun").addEventListener("click", runAudit);
    el.querySelectorAll("[data-sxgo]").forEach((b) => b.addEventListener("click", () => openSens(b.dataset.sxgo)));
    fillRanges(el, rows);
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
    const ex = EX[r.key];
    return `<div class="gaprow" data-gap="${esc(r.key)}"><div class="gl"><b>${esc(r.gap)}</b>${qtag(r.question)}</div>
      <div class="gb"${ex ? ` data-gapex="1" style="cursor:pointer" title="Click to see examples"` : ""}><span class="gbar"><i style="width:${(r.share * 100).toFixed(2)}%;background:${c}"></i></span><b>${pct(r.share)}</b><span class="muted small">${fmt(r.count)} of ${fmt(r.of)} ${esc(r.unit)}</span>${ex ? ` <button type="button" class="link small">see examples ▾</button>` : ""}</div>
      <div class="gt"><span>Hides</span>${esc(r.hides)}</div><div class="gt"><span>To close it</span>${esc(r.close)}</div><div class="grng" data-rng="${esc(r.key)}"></div><div class="gapex" hidden></div></div>`;
  }
  function cardFor(r) {
    const ex = EX[r.key] && r.count;
    return `<section class="card gapcard2" data-gap="${esc(r.key)}"><header><h3>${esc(r.gap)}</h3>${qtag(r.question)}${ex ? ` <button type="button" class="link small" data-gapex="1">see examples ▾</button>` : ""}</header>
      ${r.count != null ? `<div class="gbig">${fmt(r.count)} <span class="muted small">${esc(r.unit)}</span></div>` : '<div class="gbig muted small">not measurable from these records</div>'}
      <div class="gt"><span>Hides</span>${esc(r.hides)}</div><div class="gt"><span>To close it</span>${esc(r.close)}</div><div class="grng" data-rng="${esc(r.key)}"></div><div class="gapex" hidden></div></section>`;
  }
  // ---------------------------------------------------------------- the range each gap leaves open (agenttrace/sensitivity.py)
  function openSens(key) {
    window.FX_SENS_FOCUS = key || null;
    location.hash = "tab=forensics&fx=sensitivity";
    FX_WANT = "sensitivity";
    goTab("forensics");
  }
  const rv = (v, kind) => v == null ? "–" : kind === "time" ? when(toTime(v)) : kind === "share" ? pct(v) : fmt(Math.round(v));
  const rt = (r, kind) => { if (!r || r.lo == null) return null; const a = rv(r.lo, kind), b = rv(r.hi, kind); return a === b ? `${a} (does not move)` : `${a} to ${b}`; };
  async function fillRanges(el, rows) {
    let sens;
    try { sens = await cached("/api/x/sensitivity"); } catch { return; }
    if (S.tab !== "gaps") return;
    el.querySelectorAll("[data-rng]").forEach((box) => {
      const g = (sens.gaps || []).find((x) => (x.rows || []).includes(box.dataset.rng));
      if (!sens.available || !g) return;
      if (!g.computable) { box.innerHTML = `<span class="grl">Range</span><span class="muted">cannot be sized from these records</span> <button type="button" class="link small" data-sxgo="${esc(g.key)}">why</button>`; }
      else {
        const parts = [["first message", rt(g.ranges.first_message, "time")], ["harm still to come then", rt(g.ranges.first_message_share, "share")], ["messages", rt(g.ranges.messages, "count")], ["pairs", rt(g.ranges.pairs, "count")]].filter((p) => p[1]);
        box.innerHTML = `<span class="grl">Range${g.key === "channel" || g.key === "success" ? " (parametric)" : ""}</span>${parts.map((p) => `<span class="grp"><span class="muted">${esc(p[0])}</span> <b>${esc(p[1])}</b></span>`).join("")} <button type="button" class="link small" data-sxgo="${esc(g.key)}">details</button>`;
      }
      box.querySelectorAll("[data-sxgo]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openSens(b.dataset.sxgo); }));
    });
  }
  // ---------------------------------------------------------------- examples behind each gap, from existing endpoints
  const isRun = (a) => String(a || "").startsWith("run:");
  // the events endpoint pages at most 500 rows: read the first four pages
  const sample = async () => { const ps = await Promise.all([0, 500, 1000, 1500].map((o) => cached(`/api/events?offset=${o}&limit=500`))); return { rows: ps.flatMap((p) => p.rows) }; };
  const msgRows = async (keep) => { const m = await cached("/api/messages"); return m.rows.filter(keep); };
  const recChips = (ids) => ids.map((id) => ent.rec(id)).join(" ");
  // each returns {html, scope}; scope says how the examples were found
  const EX = {
    time: async () => { const r = await sample(); const xs = r.rows.filter((x) => !x.time); return { html: recChips(xs.slice(0, 16).map((x) => x.id)), n: xs.length, scope: `among the first ${fmt(r.rows.length)} records in file order` }; },
    actor: async () => { const r = await sample(); const xs = r.rows.filter((x) => isRun(x.actor) && x.intent); return { html: xs.slice(0, 16).map((x) => `${ent.rec(x.id)} <span class="muted small">${esc(short(x.actor))}</span>`).join(" · "), n: xs.length, scope: `actions with an intent among the first ${fmt(r.rows.length)} records in file order` }; },
    weak: async () => { const xs = await msgRows((r) => r[8] === "named the place" || r[8] === "posted after it"); return { html: msgList(xs), n: xs.length, scope: "every such message, earliest first" }; },
    merged: async () => { const xs = await msgRows((r) => r[9]); return { html: msgList(xs), n: xs.length, scope: "every such message, earliest first" }; },
    never_read: async () => { const m = await cached("/api/places_map"); const xs = m.rows.filter((r) => r[7]).sort((a, b) => b[1] - a[1]); return { html: xs.slice(0, 16).map((r) => `${ent.place(r[0])} <span class="muted small">${plural(r[1], "write")}</span>`).join(" · "), n: xs.length, scope: "most-written first" }; },
    identity: async () => ({ html: `<button type="button" class="link" data-gotab="agents">Open the Agents tab</button> to see which tokens and names may be one agent.`, n: null, scope: "" }),
    overwrites: async () => ({ html: "Every overwrite is listed in the card at the bottom of this page.", n: null, scope: "" }),
  };
  function msgList(xs) {
    return `<table class="small"><tbody>${xs.slice(0, 16).map((r) => `<tr><td>${ent.actor(r[0])} → ${ent.actor(r[1])}</td><td>${ent.place(r[2])}</td><td>${ent.rec(r[3])} → ${ent.rec(r[4])}</td><td class="muted">${esc(r[8] || "")}</td></tr>`).join("")}</tbody></table>`;
  }
  async function toggleExamples(host, r) {
    const box = host && host.querySelector(".gapex");
    if (!box || !r || !EX[r.key]) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = '<p class="small muted">Finding examples…</p>';
    try {
      const x = await EX[r.key]();
      box.innerHTML = x.n === 0 ? `<p class="small muted">None found ${esc(x.scope)}.</p>`
        : `<div class="small">${x.n != null ? `<span class="muted">Examples (${fmt(Math.min(x.n, 16))} of ${fmt(x.n)} ${esc(x.scope)}):</span> ` : ""}${x.html}</div>`;
      box.querySelectorAll("[data-gotab]").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.gotab)));
    } catch (e) { box.innerHTML = `<p class="small warn">${esc(e.message)}</p>`; }
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

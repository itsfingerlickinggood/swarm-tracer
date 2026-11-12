// Forensics › "Was it used? Content tracing": grades each message by whether what was written
// reappears in what the reader did next, and lists content that moved with no shared place.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const GRADE = { used: { label: "used", color: "#0f766e" }, "fetched only": { label: "fetched only", color: "#e3a43b" }, unclear: { label: "unclear", color: "#c3cad3" } };
  const ST = { item: null };
  const AGENT_COLORS = PALETTE.intent;
  const mark = (snip, item) => esc(snip).split(esc(item)).join(`<mark class="fxcm">${esc(item)}</mark>`);
  const gradeParts = (g) => Object.keys(GRADE).map((k) => ({ label: GRADE[k].label, value: g[k] || 0, color: GRADE[k].color }));
  const badge = (t, cls = "") => `<span class="fxcb ${cls}">${esc(t)}</span>`;
  const itemBtn = (it) => `<button type="button" class="fxcitem" data-item="${esc(it)}" title="Show who held this string, and when">${esc(it.length > 44 ? it.slice(0, 43) + "…" : it)}</button>`;

  function strip(m) {
    const u = m.used[0];
    const est = true;
    const step = (glyph, cls, label, who, rec, t) => `<div class="fxcstep ${cls}"><span class="fxcg">${glyph}</span><div><b>${label}</b> ${who}<br>${ent.rec(rec)} <span class="muted small">${esc(t || "time unknown")}</span></div></div>`;
    const gap = (h) => `<div class="fxcgap"><span>${esc(laterWord(h, est) || "–")}</span></div>`;
    return `<div class="fxcuse">
      <div class="fxcsteps">
        ${step("▲", "w", "write", ent.actor(m.from), m.write_id, m.write_time)}${gap(m.wait_h)}
        ${step("▼", "r", "read", ent.actor(m.to), m.read_id, m.read_time)}${gap(u.after_h)}
        ${step("●", "u", "use", ent.actor(m.to), u.use_id, u.use_time)}
      </div>
      <div class="fxcsn"><span class="muted small">in the write</span><code>${mark(u.write_snip, u.item)}</code></div>
      <div class="fxcsn"><span class="muted small">in the reader's later record</span><code>${mark(u.use_snip, u.item)}</code></div>
      <div class="small muted">Place ${ent.place(m.channel)} · reused string ${itemBtn(u.item)} held by ${plural(u.rarity.actors, "actor")} in ${plural(u.rarity.records, "record")}${m.used_total > 1 ? ` · ${fmt(m.used_total - 1)} more reused string${m.used_total > 2 ? "s" : ""}: ${m.used.slice(1).map((x) => itemBtn(x.item)).join(" ")}` : ""}${m.same_agent ? " · " + badge("one estimated agent", "same") : ""}${u.uncertain ? " · " + badge("use within 15 min of the read: order uncertain", "warn") : ""}</div>
    </div>`;
  }

  function timeline(host, r) {
    if (!host) return;
    const hs = r.holders.filter((h) => h.times.length);
    if (!hs.length) { host.innerHTML = `<p class="muted">${fmt(r.records)} record(s) hold this string, none of them dated.</p>`; return; }
    // lanes grouped by estimated agent: groups in order of their first holder
    const keyOf = (h) => h.agent || h.actor;
    const groups = [];
    hs.forEach((h) => { let g = groups.find((x) => x.key === keyOf(h)); if (!g) groups.push(g = { key: keyOf(h), agent: h.agent, rows: [] }); g.rows.push(h); });
    const rows = groups.flatMap((g) => g.rows.map((h) => ({ h, g })));
    const W = Math.max(560, host.clientWidth || 800), padL = 170, padR = 20, rowH = 22, top = 8;
    let t0 = Infinity, t1 = -Infinity;
    hs.forEach((h) => h.times.forEach((x) => { const t = toTime(x[0]); if (t < t0) t0 = t; if (t > t1) t1 = t; }));
    if (t1 - t0 < 3600e3) { t0 -= 1800e3; t1 += 1800e3; }
    const X = (t) => padL + ((t - t0) / (t1 - t0)) * (W - padL - padR);
    const H = top + rows.length * rowH + 30;
    let s = `<svg class="fxcsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Holders of the string over time">`;
    let y = top, firstPt = null;
    groups.forEach((g, gi) => {
      const col = g.agent ? AGENT_COLORS[gi % AGENT_COLORS.length] : "#8b96a2";
      if (g.agent && g.rows.length > 1) s += `<rect x="2" y="${y}" width="${W - 4}" height="${g.rows.length * rowH}" fill="${col}" opacity=".07" rx="4"/><rect x="2" y="${y}" width="3" height="${g.rows.length * rowH}" fill="${col}"><title>One estimated agent: ${esc(short(g.agent))}</title></rect>`;
      g.rows.forEach((h) => {
        const cy = y + rowH / 2;
        s += `<line x1="${padL}" x2="${W - padR}" y1="${cy}" y2="${cy}" stroke="${GRID}"/>`;
        s += `<text x="${padL - 8}" y="${cy + 4}" text-anchor="end" font-size="11.5" fill="${h.kind === "run" ? "#5b6672" : "#7a4d0c"}" data-actor="${esc(h.actor)}" style="cursor:pointer">${esc(fitName(short(h.actor), padL - 20, "11.5px sans-serif"))}<title>${esc(short(h.actor))}: ${fmt(h.records)} record(s)${h.undated ? `, ${fmt(h.undated)} undated` : ""}</title></text>`;
        h.times.forEach((x, i) => {
          const cx = X(toTime(x[0]));
          if (i === 0 && (!firstPt || toTime(x[0]) < firstPt.t)) firstPt = { t: toTime(x[0]), x: cx, y: cy };
          s += `<circle cx="${cx.toFixed(1)}" cy="${cy}" r="${i === 0 ? 5 : 3.2}" fill="${i === 0 ? col : "#fff"}" stroke="${col}" stroke-width="1.4" data-id="${esc(x[1])}" style="cursor:pointer"><title>${esc(short(h.actor))} · ${esc(x[0])} · ${esc(x[1])} (${esc(x[2])})${i === 0 ? "\nfirst dated record with the string" : ""}</title></circle>`;
        });
        y += rowH;
      });
    });
    // arrows from the first holder to each later holder's first record
    if (firstPt) rows.forEach(({ h }) => { const t = toTime(h.times[0][0]); if (t > firstPt.t) { const yy = top + rows.findIndex((q) => q.h === h) * rowH + rowH / 2; s += `<path d="M${firstPt.x.toFixed(1)},${firstPt.y}C${firstPt.x.toFixed(1)},${yy} ${X(t).toFixed(1)},${firstPt.y} ${(X(t) - 6).toFixed(1)},${yy}" fill="none" stroke="#1b2430" stroke-opacity=".28" stroke-dasharray="3 3"/>`; } });
    timeTicks(t0, t1, 8).forEach((tk) => { const t = tk.t ?? tk, x = X(t); s += `<line x1="${x}" x2="${x}" y1="${H - 26}" y2="${H - 22}" stroke="${AXIS}"/><text x="${x}" y="${H - 9}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(tk.label ?? when(t))}</text>`; });
    host.innerHTML = s + "</svg>";
  }

  async function showItem(item) {
    const box = $("fxcItem");
    if (!box) return;
    ST.item = item;
    const inp = $("fxcQ"); if (inp) inp.value = item;
    box.innerHTML = '<p class="muted">Searching every record…</p>';
    let r;
    try { r = await cached("/api/x/content_item?q=" + encodeURIComponent(item)); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (ST.item !== item || !box.isConnected) return;
    if (!r.records) { box.innerHTML = `<p class="muted">No record holds “${esc(item)}”.</p>`; return; }
    const d = r.distinctive;
    box.innerHTML = `<p class="small"><b>${esc(r.item)}</b>: in ${plural(r.records, "record")}, held by ${plural(r.holders_total, "actor")} (${fmt(r.named_holders)} named). ${d ? "Counts as distinctive." : "Too common, or outside the named actors' records: not counted as distinctive."}
      ${r.first ? `First seen ${esc(r.first.time || "at an unknown time")} under ${ent.actor(r.first.actor)} in ${ent.rec(r.first.id)}.` : ""}</p>
      ${r.first ? `<div class="fxcsn"><code>${mark(r.first.snip, r.item)}</code></div>` : ""}
      <div id="fxcTl"></div>
      <div class="legend"><span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="#2f6fb3"/></svg>an actor's first dated record with the string</span><span><svg width="12" height="12"><circle cx="6" cy="6" r="3.2" fill="#fff" stroke="#2f6fb3" stroke-width="1.4"/></svg>later record</span><span><i style="background:#2f6fb3;opacity:.3"></i>shaded band: tokens of one estimated agent</span><span>dashed line: from the first holder to each later holder</span></div>
      ${r.holders_total > r.holders.length ? `<p class="small muted">Showing the first ${fmt(r.holders.length)} of ${fmt(r.holders_total)} holders.</p>` : ""}`;
    const d2 = () => timeline($("fxcTl"), r); d2(); onResize($("fxcTl"), d2);
  }

  function handover(p, i, maxScore) {
    return `<div class="fxcho${p.strong ? " strong" : ""}">
      <div class="fxchh"><span class="fxcrank">${i + 1}</span>${ent.actor(p.from)} <span class="muted">→</span> ${ent.actor(p.to)}
        ${p.strong ? badge("strong", "strong") : badge("weak")}${p.same_agent ? badge("one estimated agent", "same") : ""}${p.has_message ? badge("also has a message", "msg") : badge("no message")}
        <span class="muted small">${plural(p.n_items, "shared string")}, ${fmt(p.exclusive_items)} exclusive and specific</span>
        <span class="fxcscore" title="Sum of the strings' rarity (1 ÷ actors holding each)"><i style="width:${(100 * p.score / maxScore).toFixed(1)}%"></i></span></div>
      <div class="fxcits">${p.items.slice(0, 5).map((x) => `<div class="fxcit" title="${esc(x.first_snip)}">
          ${itemBtn(x.item)}<span class="fxcrar" title="Rarity: held by ${x.holders} actor(s) in ${x.records} record(s)"><i style="width:${Math.round(100 * x.rarity * 2)}%"></i></span>
          <span class="small muted">${x.holders} holder${x.holders === 1 ? "" : "s"} · ${ent.rec(x.first_id)} → ${ent.rec(x.then_id)} · ${esc(gapWord(x.gap_h, true))}${x.order_uncertain ? " (order uncertain)" : ""}${x.run_earlier ? " · seen earlier in an anonymous run" : ""}${x.specific ? "" : " · dictionary-like name"}</span></div>`).join("")}
        ${p.n_items > 5 ? `<div class="small muted">and ${fmt(p.n_items - 5)} more</div>` : ""}</div></div>`;
  }

  async function render(host) {
    const r = await cached("/api/x/content");
    if (!host.isConnected) return;
    const sm = r.summary, g = sm.grades, th = sm.thresholds, sim = sm.simulated, ho = sm.handovers;
    const used = r.messages.filter((m) => m.grade === "used");
    const maxScore = Math.max(1, ...r.handovers.map((p) => p.score));
    const weak = r.messages.filter((m) => m.weak && m.weak.length).length;
    host.innerHTML = `
      <div class="kpis">
        ${kpi("messages graded", fmt(sm.messages), `${fmt(sm.named.messages)} between named actors`)}
        ${kpi("used", fmt(g.used), "written content reappears in the reader's later records")}
        ${kpi("fetched only", fmt(g["fetched only"]), "traceable content, reader went on, nothing reappeared")}
        ${kpi("unclear", fmt(g.unclear), "nothing to trace, or no later record")}
        ${kpi("hand-overs with no place", fmt(ho.strong), `strong pairs of ${fmt(ho.pairs)} candidates; ${fmt(ho.strong_new)} with no message and not one estimated agent`)}
      </div>
      ${card("Messages by grade", `
        <div class="fxcbars">
          <div><span class="small">All ${fmt(sm.messages)} messages</span>${stackbar(gradeParts(g), { h: 16 })}</div>
          <div><span class="small">${fmt(sm.named.messages)} between named actors (tokens)</span>${stackbar(gradeParts(sm.named.grades), { h: 16 })}</div>
          <div><span class="small">… of those, ${fmt(sm.named.messages - sm.named.same_agent)} between different estimated agents</span>${stackbar(gradeParts(sm.named.grades_across_agents), { h: 16 })}</div>
          <div><span class="small">… and ${fmt(sm.named.same_agent)} inside one estimated agent (two tokens, one controller)</span>${stackbar(gradeParts(sm.named.grades_same_agent), { h: 16 })}</div>
        </div>
        <p class="small muted">Also: in ${fmt(sm.targeted)} message(s) the read itself names a string of the write (the reader knew it before fetching, so it is not counted as use); in ${fmt(sm.delivered)} the string came back in the response to the read; in ${fmt(weak)} only one dictionary-like name reappeared (not enough).</p>`,
        { sub: `A ${term("message")} shows the content was available to the reader. “Used” needs more: a distinctive string of the write record that the reader never held before the read and holds after it.` })}
      ${card(`Used: ${plural(used.length, "message")}`, used.length ? used.map(strip).join("") : `<p class="muted">No message here has a distinctive string of the write reappearing in the reader's later records. That does not show the content was ignored: most written content in this trace is redacted or encoded, so there is little to follow.</p>`,
        { sub: "▲ the write, ▼ the read, ● the reader's first later record holding the string. Gaps are from estimated times." })}
      ${card("Every message and its grade", `<div id="fxcAll"></div>`, { sub: "Click a row to open the read record." })}
      ${card(`Content that moved with no shared place: ${plural(ho.strong, "strong pair")}`, `
        <p class="small">A distinctive string first seen under one named actor and later under another who never held it before, where the two records are not the same program and the later record does not touch a place the first actor wrote. These are candidate links the message rule misses. ${fmt(ho.strong_new)} strong pairs have no message and are not one estimated agent; ${fmt(ho.strong_same_agent)} are inside one estimated agent; ${fmt(ho.strong_with_message)} also have a message.</p>
        <div id="fxcHo" class="fxchos">${r.handovers.length ? r.handovers.map((p, i) => handover(p, i, maxScore)).join("") : '<p class="muted">None found.</p>'}</div>
        ${more(r.handovers.length, r.handovers_total, "pairs")}
        <p class="small muted">Left out: ${fmt(ho.skipped.same_program)} same-program reruns, ${fmt(ho.skipped.place_name)} strings that are part of a place name, ${fmt(ho.skipped.via_place)} where the later record touches a place the first actor wrote, ${fmt(ho.skipped.undated)} that cannot be ordered.</p>`,
        { sub: `Ranked: strong pairs first, then by rarity. Bar = rarity of each string (1 ÷ actors holding it). Strong = ${th.strong_items}+ strings held by these two actors only, each specific (a digit, a path, a file name or a numbered placeholder), first uses more than ${th.order_margin_h} h apart.` })}
      ${card("Who held a string, and when", `
        <form id="fxcF" class="fxcform"><input id="fxcQ" type="text" maxlength="200" placeholder="a file name, marker or other string (4+ characters)" aria-label="String to trace"><button type="submit">Trace</button></form>
        <div id="fxcItem"><p class="muted">Click any string above, or type one.</p></div>`,
        { sub: "One lane per actor that holds the string, in order of first appearance; tokens of one estimated agent are grouped." })}
      ${card("How far to trust this", `
        <ul class="fxccav">
          <li><b>A reused string is evidence, not proof.</b> Two actors can hold the same rare string because both read it from the same outside source, or because it is a public name (a library call, a system path) that is merely rare in this trace.</li>
          <li><b>Absence is weak.</b> “Fetched only” means nothing traceable reappeared. Content can be used without any string surviving (it was redacted, encoded, or acted on rather than copied).</li>
          <li><b>Times are mostly estimated.</b> Undated records of the reader count as “before the read”, and hand-overs closer than ${th.order_margin_h} h are marked order-uncertain and never make a strong pair.</li>
          <li><b>What counts as distinctive:</b> an identifier-like string found in at most ${th.max_records} records, held by at most ${th.max_named} named actors and ${th.max_actors} actors in all. Identity tokens are left out (carried tokens are counted elsewhere). Each record is read up to ${fmt(th.text_cap)} characters. ${fmt(sm.items.distinctive)} distinctive strings of ${fmt(sm.items.candidates)} candidates.</li>
          ${sim ? `<li><b>False positives, measured on simulated swarms</b> (${sim.agents} agents, seeds ${sim.seeds.join(", ")}): the benign swarm, where nobody coordinates, gave <b>${fmt(sim.benign.used)}</b> “used” grades and <b>${fmt(sim.benign.handover_strong)}</b> strong hand-over pairs out of ${fmt(sim.benign.possible_pairs)} possible pairs (and ${fmt(sim.benign.handover_pairs)} weak single-name candidates, which is why weak pairs should not be read as links). The coordinated swarm, whose readers fetch messages and do nothing with them, gave ${fmt(sim.coordinated.used)} “used” of ${fmt(sim.coordinated.messages)} messages and ${fmt(sim.coordinated.handover_strong)} strong pairs. The simulator has no agent that reuses fetched content, so these numbers measure false alarms, not how much real use is found.</li>` : ""}
        </ul>`)}`;
    $("fxcAll").innerHTML = `<div class="fxcscroll">${table(["Grade", "From", "To", "Place", "Wait", "Traceable strings", "Why"], r.messages.map((m) => [
      `<span class="fxcgr" style="--c:${GRADE[m.grade].color}"><i></i>${esc(m.grade)}</span>`, ent.actor(m.from), ent.actor(m.to) + (m.same_agent ? " " + badge("one agent", "same") : ""), ent.place(m.channel),
      `<span class="fxcnw">${esc(gapWord(m.wait_h, true))}</span>`, fmt(m.traceable), `<span class="small muted fxcwhy">${esc(m.why)}</span>`]), true)}</div>`;
    bindRows($("fxcAll"), (i) => selectEvent(r.messages[i].read_id));
    host.addEventListener("click", (e) => { const b = e.target.closest(".fxcitem"); if (b) { showItem(b.dataset.item); $("fxcItem").scrollIntoView({ block: "center", behavior: "smooth" }); } });
    $("fxcF").addEventListener("submit", (e) => { e.preventDefault(); const q = $("fxcQ").value.trim(); if (q) showItem(q); });
    const firstItem = (used[0] && used[0].used[0].item) || (r.handovers[0] && r.handovers[0].items[0] && r.handovers[0].items[0].item);
    if (firstItem) showItem(firstItem);
  }

  window.FX_SECTIONS.push({ id: "content", title: "Was it used? Content tracing", group: "Follow the evidence",
    blurb: `A ${term("message")} shows that content was available to a reader, not that the reader used it. This follows distinctive strings (file names, markers, repository names) from what was written into what the reader did next, and finds content that moved between actors with no shared place at all.`, render });
})();

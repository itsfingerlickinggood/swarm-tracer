"use strict";
// Trace: the front door. One search box, starting points counted from the data, one chain for
// anything (a swimlane of who held it when), and the provenance of a harmful action (a layered graph).
// Deep links: #tab=trace&q=<text> and #tab=trace&harm=<record id>.
(function () {
  const TRC = { q: "", harm: "", run: 0 };
  const enc = encodeURIComponent;
  const PROGRAM = "#0f766e", PLACEC = PALETTE.place.msg, NEXTC = "#9aa5b1";
  const KIND = {
    seen: { word: "data sighting", color: PALETTE.sign.single },
    use: { word: "identity use", color: PALETTE.sign.joint },
    write: { word: "write to a place", color: PLACEC },
    read: { word: "read of a place", color: PLACEC },
    run: { word: "program first run", color: PROGRAM },
    reuse: { word: "program reused", color: PROGRAM },
    next: { word: "what it did next", color: NEXTC },
    harm: { word: "harmful action", color: HARM },
  };
  const EDGE = {
    message: { word: "written, then read by another actor", color: PLACEC, dash: "" },
    seen_used: { word: "seen as data, then used as identity", color: PALETTE.sign.joint, dash: "" },
    reuse: { word: "program reused", color: PROGRAM, dash: "" },
    next_holder: { word: "next actor to hold it (order only)", color: "#8793a0", dash: "4 3" },
    next: { word: "in the following hour", color: "#c3cad2", dash: "" },
    harm: { word: "went on to harm", color: HARM, dash: "2 3" },
  };
  // the mark of one step, centred on (x, y)
  function glyph(kind, x, y, r = 6) {
    const c = (KIND[kind] || KIND.next).color;
    if (kind === "seen") return `<path d="M${x},${y - r - 1}L${x + r + 1},${y}L${x},${y + r + 1}L${x - r - 1},${y}z" fill="#fff" stroke="${c}" stroke-width="1.8"/>`;
    if (kind === "use") return `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}"/>`;
    if (kind === "write") return `<path d="M${x},${y - r - 1}L${x + r + 1},${y + r - 1}L${x - r - 1},${y + r - 1}z" fill="${c}"/>`;
    if (kind === "read") return `<path d="M${x},${y + r + 1}L${x + r + 1},${y - r + 1}L${x - r - 1},${y - r + 1}z" fill="${c}"/>`;
    if (kind === "harm") return `<rect x="${x - r}" y="${y - r}" width="${2 * r}" height="${2 * r}" rx="1" fill="${c}"/>`;
    if (kind === "run") return `<path d="M${x},${y - r - 1}L${x + r + 1},${y}L${x},${y + r + 1}L${x - r - 1},${y}z" fill="${c}"/>`;
    if (kind === "reuse") return `<path d="M${x},${y - r - 1}L${x + r + 1},${y}L${x},${y + r + 1}L${x - r - 1},${y}z" fill="#fff" stroke="${c}" stroke-width="1.8"/>`;
    return `<circle cx="${x}" cy="${y}" r="${r - 2.5}" fill="#fff" stroke="${c}" stroke-width="1.5"/>`;
  }
  const icon = (kind) => `<svg class="trc-ic" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">${glyph(kind, 8, 8, 5)}</svg>`;
  const tms = (st) => (st.t == null ? null : st.t * 1000);
  const whenE = (t, est) => (t == null ? "no time" : (est ? "~" : "") + when(t));
  const cut = (x, n = 200) => { x = String(x ?? ""); return x.length > n ? x.slice(0, n - 1) + "…" : x; };

  // ---------------------------------------------------------------- tooltip (plain text only)
  let tip = null;
  function tipEl() {
    if (!tip) { tip = document.createElement("div"); tip.className = "trc-tip"; tip.hidden = true; document.body.appendChild(tip); }
    return tip;
  }
  function bindTips(host) {
    host.addEventListener("mousemove", (e) => {
      const t = e.target.closest("[data-tip]");
      const el = tipEl();
      if (!t) { el.hidden = true; return; }
      const [head, ...rest] = t.dataset.tip.split("\n");
      el.textContent = "";
      const b = document.createElement("b"); b.textContent = head; el.appendChild(b);
      rest.forEach((line) => { const d = document.createElement("div"); d.textContent = line; el.appendChild(d); });
      el.hidden = false;
      const r = el.getBoundingClientRect();
      el.style.left = Math.max(6, Math.min(innerWidth - r.width - 8, e.clientX + 14)) + "px";
      el.style.top = (e.clientY + 18 + r.height > innerHeight ? e.clientY - r.height - 10 : e.clientY + 18) + "px";
    });
    host.addEventListener("mouseleave", () => { tipEl().hidden = true; });
    host.addEventListener("mousedown", () => { tipEl().hidden = true; });
  }

  // ---------------------------------------------------------------- time axis with compressed idle stretches
  function timeScale(ts, x0, x1) {
    const BREAK = 46;
    ts = [...new Set(ts)].sort((a, b) => a - b);
    if (!ts.length) return { X: () => (x0 + x1) / 2, breaks: [], segs: [] };
    if (ts.length === 1) return { X: () => (x0 + x1) / 2, breaks: [], segs: [], single: ts[0] };
    const gaps = ts.slice(1).map((t, i) => t - ts[i]);
    const sorted = gaps.slice().sort((a, b) => a - b), med = sorted[Math.floor((sorted.length - 1) / 2)];
    const sp = ts.at(-1) - ts[0];
    const long = gaps.map((g) => ts.length >= 4 && g > Math.max(3600e3, 0.2 * sp) && g > 4 * med);
    const real = gaps.reduce((a, g, i) => a + (long[i] ? 0 : g), 0);
    const avail = (x1 - x0) - long.filter(Boolean).length * BREAK;
    const pos = [x0];
    gaps.forEach((g, i) => pos.push(pos[i] + (long[i] ? BREAK : real ? (g / real) * avail : avail / gaps.length)));
    const X = (t) => {
      if (t <= ts[0]) return pos[0];
      if (t >= ts.at(-1)) return pos.at(-1);
      let lo = 0, hi = ts.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m; }
      return pos[lo] + ((t - ts[lo]) / (ts[hi] - ts[lo])) * (pos[hi] - pos[lo]);
    };
    const breaks = [], segs = [];
    let a = 0;
    gaps.forEach((g, i) => { if (long[i]) { breaks.push({ xa: pos[i], xb: pos[i + 1], gap: g }); segs.push([ts[a], ts[i]]); a = i + 1; } });
    segs.push([ts[a], ts.at(-1)]);
    return { X, breaks, segs };
  }

  // ---------------------------------------------------------------- the chain as a swimlane
  function swimlane(host, d) {
    const W = Math.max(640, host.clientWidth || 900), LH = 30, TOP = 34, LEFT = 168, RIGHT = 26;
    const lanes = d.lanes, laneY = {};
    lanes.forEach((l, i) => { laneY[l.actor] = TOP + i * LH + LH / 2; });
    const undated = d.steps.filter((s) => s.t == null);
    const x1 = W - RIGHT - (undated.length ? 70 : 0);
    const sc = timeScale(d.steps.filter((s) => s.t != null).map(tms), LEFT + 18, x1);
    const H = TOP + lanes.length * LH + 14;
    // positions; steps that would sit on top of each other in one lane are nudged right
    const P = d.steps.map((s) => ({ x: s.t == null ? W - RIGHT - 30 : sc.X(tms(s)), y: laneY[s.actor] }));
    lanes.forEach((l) => {
      let last = -1e9;
      d.steps.forEach((s, i) => { if (s.actor !== l.actor) return; if (P[i].x < last + 14) P[i].x = last + 14; last = P[i].x; });
    });
    let g = `<svg class="trc-lanes" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><title>Who held it, when: one lane per actor</title><defs>${Object.entries(EDGE).map(([k, e]) => `<marker id="trc-a-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,1L10,5L0,9z" fill="${e.color}"/></marker>`).join("")}</defs>`;
    // lanes and their labels; a bracket joins the lanes of one estimated agent
    lanes.forEach((l, i) => {
      const y = TOP + i * LH;
      g += `<rect x="${LEFT}" y="${y + 2}" width="${W - LEFT - 6}" height="${LH - 4}" rx="4" fill="${i % 2 ? "#f7f9fb" : "#fbfcfd"}"/>`;
      g += `<g class="trc-lane" data-actor="${esc(l.actor)}"><circle cx="${LEFT - 138}" cy="${y + LH / 2}" r="3.5" fill="${String(l.actor).startsWith("run:") ? "#aab3bc" : C.actor}"/><text x="${LEFT - 130}" y="${y + LH / 2 + 4}" font-size="12" fill="${INK}">${esc(fitName(short(l.actor), 118))}</text></g>`;
    });
    let i0 = 0;
    while (i0 < lanes.length) {
      let i1 = i0;
      while (i1 + 1 < lanes.length && lanes[i1 + 1].agent === lanes[i0].agent) i1++;
      if (i1 > i0) {
        const ya = TOP + i0 * LH + 5, yb = TOP + (i1 + 1) * LH - 5, ym = (ya + yb) / 2;
        g += `<g data-tip="${esc(`One estimated agent\n${i1 - i0 + 1} of these actors are joined by the Agents tab's evidence (counted as ${short(lanes[i0].agent)})`)}"><path d="M20,${ya}H14V${yb}H20" fill="none" stroke="${C.actor}" stroke-width="1.6"/><text transform="translate(9,${ym}) rotate(-90)" text-anchor="middle" font-size="9.5" fill="#7a4d0c">1 agent</text></g>`;
      }
      i0 = i1 + 1;
    }
    // axis: ticks inside each stretch of real scale, a zigzag over each compressed stretch
    const labels = [];
    sc.segs.forEach(([ta, tb]) => {
      const w = sc.X(tb) - sc.X(ta);
      labels.push({ x: sc.X(ta), text: when(ta), major: true });
      if (w > 150) timeTicks(ta, tb, Math.max(2, Math.floor(w / 95))).forEach((k) => labels.push({ x: sc.X(k.t), text: k.label }));
    });
    if (sc.single != null) labels.push({ x: sc.X(sc.single), text: when(sc.single), major: true });
    let lastX = -1e9;
    labels.sort((a, b) => a.x - b.x || (b.major ? 1 : 0) - (a.major ? 1 : 0)).forEach((l) => {
      if (l.x - lastX < 76) return;
      lastX = l.x;
      g += `<line x1="${l.x.toFixed(1)}" x2="${l.x.toFixed(1)}" y1="${TOP - 4}" y2="${H - 8}" stroke="${GRID}"/><text x="${l.x.toFixed(1)}" y="${TOP - 10}" font-size="10.5" fill="${QUIET}" text-anchor="${l.x > W - 60 ? "end" : "middle"}">${esc(l.text)}</text>`;
    });
    sc.breaks.forEach((b) => {
      const xm = (b.xa + b.xb) / 2;
      g += `<g data-tip="${esc(`Idle stretch, compressed\nNothing in this chain for ${hoursWord(b.gap / 3600e3)}; the axis skips it`)}"><rect x="${b.xa + 8}" y="${TOP - 2}" width="${b.xb - b.xa - 16}" height="${H - TOP - 6}" fill="#fff" opacity=".82"/><path d="M${xm - 6},${TOP + 3}l5,-9M${xm + 1},${TOP + 3}l5,-9" fill="none" stroke="${QUIET}" stroke-width="1.4"/><line x1="${xm}" x2="${xm}" y1="${TOP + 2}" y2="${H - 10}" stroke="${AXIS}" stroke-dasharray="1 4"/><text x="${xm}" y="${H - 1}" font-size="9.5" fill="${QUIET}" text-anchor="middle">${esc(hoursWord(b.gap / 3600e3))} idle</text></g>`;
    });
    if (undated.length) g += `<line x1="${x1 + 22}" x2="${x1 + 22}" y1="${TOP - 4}" y2="${H - 8}" stroke="${AXIS}" stroke-dasharray="2 3"/><text x="${W - RIGHT - 30}" y="${TOP - 10}" font-size="10.5" fill="${QUIET}" text-anchor="middle">no time</text>`;
    // arrows: quiet ones first, hand-overs on top
    const order = { next: 0, harm: 1, next_holder: 2, reuse: 3, seen_used: 4, message: 5 };
    d.edges.slice().sort((a, b) => (order[a.kind] ?? 0) - (order[b.kind] ?? 0)).forEach((e) => {
      const a = P[e.from], b = P[e.to], st = EDGE[e.kind] || EDGE.next;
      if (!a || !b) return;
      const same = Math.abs(a.y - b.y) < 1;
      const dx = b.x - a.x, sgn = dx >= 0 ? 1 : -1;
      const ax = a.x + (same ? 8 * sgn : 0), bx = b.x - (same ? 9 * sgn : 0);
      const ay = a.y + (same ? 0 : (b.y > a.y ? 8 : -8)), by = b.y + (same ? 0 : (b.y > a.y ? -10 : 10));
      const path = same ? `M${ax.toFixed(1)},${ay}L${bx.toFixed(1)},${by}`
        : `M${ax.toFixed(1)},${ay}C${ax.toFixed(1)},${(ay + by) / 2} ${bx.toFixed(1)},${(ay + by) / 2} ${bx.toFixed(1)},${by}`;
      if (same && Math.abs(bx - ax) < 4) return;
      const from = d.steps[e.from], to = d.steps[e.to];
      const tipText = `${st.word}\n${short(from.actor)} ${from.record} → ${short(to.actor)} ${to.record}${e.place ? "\nvia " + placeLabel(e.place) : ""}${e.gap_h != null ? "\n" + gapWord(e.gap_h, e.estimated) + " apart" : ""}`;
      g += `<g class="trc-e k-${e.kind}" data-from="${e.from}" data-to="${e.to}" data-tip="${esc(tipText)}"><path d="${path}" fill="none" stroke="transparent" stroke-width="9"/><path class="ln" d="${path}" fill="none" stroke="${st.color}" stroke-width="${e.kind === "next" ? 1.2 : 1.7}"${st.dash ? ` stroke-dasharray="${st.dash}"` : ""} marker-end="url(#trc-a-${e.kind})"/></g>`;
    });
    // the steps
    d.steps.forEach((s, i) => {
      const p = P[i], k = KIND[s.kind] || KIND.next;
      const tipText = `${k.word} · ${whenE(tms(s), s.estimated)}\n${short(s.actor)} · ${s.record}${s.place ? "\n" + placeLabel(s.place) : ""}\n${cut(short(s.evidence), 180)}`;
      g += `<g class="trc-n${s.focus ? " focus" : ""}" data-i="${i}" data-id="${esc(s.record)}" data-nocard data-tip="${esc(tipText)}"><circle cx="${p.x.toFixed(1)}" cy="${p.y}" r="12" fill="transparent"/>${s.focus ? `<circle cx="${p.x.toFixed(1)}" cy="${p.y}" r="11" fill="none" stroke="${INK}" stroke-width="1.2" stroke-dasharray="2 2"/>` : ""}${glyph(s.kind, +p.x.toFixed(1), p.y)}</g>`;
    });
    host.innerHTML = g + "</svg>";
  }
  function laneLegend(d) {
    const kinds = [...new Set(d.steps.map((s) => s.kind))], ek = [...new Set(d.edges.map((e) => e.kind))];
    return `<div class="trc-legend">${Object.keys(KIND).filter((k) => kinds.includes(k)).map((k) => `<span>${icon(k)}${esc(KIND[k].word)}</span>`).join("")}${Object.keys(EDGE).filter((k) => ek.includes(k)).map((k) => `<span><svg width="26" height="10" aria-hidden="true"><line x1="1" x2="20" y1="5" y2="5" stroke="${EDGE[k].color}" stroke-width="1.7"${EDGE[k].dash ? ` stroke-dasharray="${EDGE[k].dash}"` : ""}/><path d="M19,1.5L25,5L19,8.5z" fill="${EDGE[k].color}"/></svg>${esc(EDGE[k].word)}</span>`).join("")}<span class="muted">dashed ring: where the chain starts · hover a mark, click it to inspect the record</span></div>`;
  }

  // ---------------------------------------------------------------- the story: one sentence per step
  function stepSentence(s) {
    const a = ent.actor(s.actor), r = ent.rec(s.record), p = s.place ? ent.place(s.place) : "";
    switch (s.kind) {
      case "seen": return `${a} held it as data in ${r}`;
      case "use": return `${a} used it as an identity in ${r}`;
      case "write": return `${a} wrote ${p || "a place"} in ${r}`;
      case "read": return `${a} read ${p || "a place"} in ${r}`;
      case "run": return `${a} ran the program first, in ${r}`;
      case "reuse": return `${a} reused the program in ${r}`;
      case "harm": return `${a} did a harmful action${s.intent ? " " + ent.intent(s.intent) : ""} in ${r}${p ? " on " + p : ""}`;
      default: return `${a} went on to ${s.intent ? ent.intent(s.intent) : "act"} in ${r}`;
    }
  }
  function storyList(d, limit) {
    const rows = d.steps.slice(0, limit).map((s, i) => `<li data-i="${i}" class="k-${esc(s.kind)}">${icon(s.kind)}<span class="trc-when" title="${s.estimated ? "time estimated from timestamps in the code" : "time from the record"}">${esc(whenE(tms(s), s.estimated))}</span><div class="trc-what">${stepSentence(s)}${s.harmful ? ` <button type="button" class="link trc-go" data-harm="${esc(s.record)}" title="Where did this harmful action come from?">where from?</button>` : ""}<div class="small muted">${richText(cut(s.evidence, 260))}</div>${s.text ? `<code class="trc-text" title="start of the record's text (data written by the agents under study)">${esc(cut(s.text, 200))}</code>` : ""}</div></li>`).join("");
    return `<ol class="trc-story">${rows}</ol>${d.steps.length > limit ? `<button type="button" class="trc-more">Show all ${fmt(d.steps.length)} steps</button>` : ""}`;
  }

  // ---------------------------------------------------------------- the chain view
  const TYPE_WORD = { record: "record", token: "identity token", actor: "actor", place: "place", string: "text" };
  function chainHead(d) {
    const r = d.resolved, key = r.key;
    const chip = r.type === "record" ? ent.rec(key) : r.type === "token" || r.type === "actor" ? ent.actor(key) : r.type === "place" ? ent.place(key) : `<code class="trc-q">${esc(cut(key, 80))}</code>`;
    const count = d.records != null ? ` <span class="muted small">in ${plural(d.records, "record")}${d.as_identity ? `, ${fmt(d.as_identity)} as an identity` : ""}</span>` : "";
    return `<div class="trc-head"><span class="badge">${esc(TYPE_WORD[r.type] || r.type)}</span> ${chip}${count}${d.harm_link ? ` <button type="button" class="trc-go primary" data-harm="${esc(d.harm_link)}">Where did this harm come from? →</button>` : ""}</div>`;
  }
  function summaryStrip(d) {
    const m = d.summary, f = m.first_seen, h = m.first_harm;
    const hk = Object.entries(m.handover_kinds || {}).map(([k, n]) => `${fmt(n)} ${({ message: "write → read", seen_used: "data → identity", reuse: "program reuse", next_holder: "next holder" })[k] || human(k)}`).join(", ");
    return `<div class="kpis trc-strip">
      ${kpi("first seen", f ? esc(whenE(f.t ?? toTime(f.time), f.estimated)) : "–", f ? `${ent.rec(f.record)} ${ent.actor(f.actor)}` : "")}
      ${kpi(term("actor", "holders"), fmt(m.holders), `→ ${m.agents < m.holders ? "~" : ""}${fmt(m.agents)} ${term("agent", m.agents === 1 ? "estimated agent" : "estimated agents")}${m.agents < m.holders ? ": some holders are one agent" : ""}`)}
      ${kpi(term("place", "places"), fmt(m.places), m.place_list.slice(0, 2).map((p) => ent.place(p)).join(" "))}
      ${kpi("hand-overs", fmt(m.handovers), esc(hk))}
      ${kpi(term("harm", "harmful actions reached"), `<span style="color:${m.harm_reached ? HARM : "inherit"}">${fmt(m.harm_reached)}</span>`, h ? `first: ${ent.rec(h.record)} ${esc(human(h.kind))}` : "none by its holders afterwards")}
      ${kpi("first sight → first harm", h && m.first_to_harm_h != null ? esc(m.first_to_harm_h === 0 ? "at once" : gapWord(m.first_to_harm_h, m.gap_estimated)) : "–", h ? esc(whenE(toTime(h.time), h.estimated)) : "")}
    </div>`;
  }
  function drawChain(out, d) {
    if (!d.found) {
      const sg = d.suggestions || {};
      const any = (sg.records || []).length + (sg.actors || []).length + (sg.places || []).length;
      out.innerHTML = `<div class="trc-none"><h3>Nothing matches “${esc(cut(d.q, 80))}”</h3><p class="muted">No record id, token, place or record text holds it. Matching is case-insensitive and looks inside words: check the spelling or try a shorter piece.</p>
        ${any ? `<p>Close matches: ${[...(sg.records || []).map((x) => [x, x]), ...(sg.actors || []).map((x) => [x, short(x)]), ...(sg.places || []).map((x) => [x, placeLabel(x)])].map(([q, label]) => `<button type="button" class="trc-go chipbtn" data-q="${esc(q)}">${esc(label)}</button>`).join(" ")}</p>` : '<p class="muted small">Or pick one of the starting points above.</p>'}</div>`;
      return;
    }
    let limit = 40;
    const caps = [];
    if (d.truncated) caps.push(`${fmt(d.steps_total)} steps found; the ${fmt(d.steps.length)} most telling are shown${d.lanes_total > d.lanes.length ? ` (${fmt(d.lanes.length)} of ${fmt(d.lanes_total)} actors)` : ""}.`);
    (d.notes || []).forEach((n) => caps.push(n));
    out.innerHTML = `${chainHead(d)}${summaryStrip(d)}
      ${card("Who held it, when", `<div class="trc-scroll"><div id="trclanes"></div></div>${laneLegend(d)}`, { sub: `One lane per ${term("actor", "actor")}, time across (UTC). Arrows are hand-overs: a ${term("write", "write")} another actor read, a token ${term("seen_used", "seen as data and then used")}, a ${term("program", "program")} reused. ${d.steps.some((s) => s.estimated) ? `“~” marks times ${term("dated", "estimated")} from timestamps in the code.` : ""}` })}
      ${caps.length ? `<p class="note small">${caps.map(esc).join(" ")}</p>` : ""}
      ${card("The story, step by step", '<div id="trcstory"></div>', { sub: "In time order. Each line is one record; the grey line under it says why it is in the chain." })}`;
    const host = out.querySelector("#trclanes"), story = out.querySelector("#trcstory");
    const draw = () => swimlane(host, d);
    draw(); onResize(host.parentElement, draw); bindTips(host);
    const drawStory = () => {
      story.innerHTML = storyList(d, limit);
      const more = story.querySelector(".trc-more");
      if (more) more.addEventListener("click", () => { limit = d.steps.length; drawStory(); });
    };
    drawStory();
    // a story line lights its mark, and a mark lights its arrows
    const light = (i, on) => {
      host.querySelectorAll(`.trc-n[data-i="${i}"]`).forEach((n) => n.classList.toggle("hot", on));
      host.querySelectorAll(`.trc-e[data-from="${i}"],.trc-e[data-to="${i}"]`).forEach((n) => n.classList.toggle("hot", on));
      host.classList.toggle("dim", on);
      story.querySelectorAll(`li[data-i="${i}"]`).forEach((n) => n.classList.toggle("hot", on));
    };
    story.addEventListener("mouseover", (e) => { const li = e.target.closest("li[data-i]"); if (li) light(li.dataset.i, true); });
    story.addEventListener("mouseout", (e) => { const li = e.target.closest("li[data-i]"); if (li && !li.contains(e.relatedTarget)) light(li.dataset.i, false); });
    host.addEventListener("mouseover", (e) => { const n = e.target.closest(".trc-n"); if (n) light(n.dataset.i, true); });
    host.addEventListener("mouseout", (e) => { const n = e.target.closest(".trc-n"); if (n && !n.contains(e.relatedTarget)) light(n.dataset.i, false); });
  }

  // ---------------------------------------------------------------- backward from harm: a layered graph
  const NODE = {
    origin: { word: "where it began", color: "#5d6d7e", bg: "#f3f5f7" },
    credential: { word: "credential", color: C.actor, bg: C.actorBg },
    program: { word: "program", color: PROGRAM, bg: C.programBg },
    place: { word: "place", color: C.place, bg: C.placeBg },
    message: { word: "message", color: ACCENT, bg: C.recordBg },
    actor: { word: "actor", color: C.actor, bg: C.actorBg },
    harm: { word: "harmful action", color: HARM, bg: "#fdeee6" },
  };
  const LAYERS = ["Where each began", "What it used", "Who", "The action"];
  function nodeAttrs(n) {
    if (n.type === "credential" || n.type === "actor") return `data-actor="${esc(n.actor)}"`;
    if (n.type === "place") return `data-place="${esc(n.place)}"`;
    return n.record ? `data-id="${esc(n.record)}"` : "";
  }
  function nodeLabel(n) {
    if (n.type === "credential" || n.type === "actor") return short(n.label);
    if (n.type === "place") return placeLabel(n.label);
    return short(n.label);
  }
  function nodeSub(n) {
    if (n.type === "actor") return n.merged ? `one agent with ${short(n.agent)}` : n.detail;
    if (n.type === "credential") return n.shared ? "shared key" : n.as_data ? "carried as data" : n.users_before ? `${plural(n.users_before, "earlier user")}` : "its only user so far";
    if (n.type === "place") return n.detail;
    if (n.type === "program") return `${plural(n.actors, "actor")} ran it`;
    return `${n.record || ""}${n.time ? " · " + whenE(toTime(n.time), n.estimated) : ""}`;
  }
  function harmDag(host, d) {
    const W = Math.max(720, host.clientWidth || 900), NW = Math.min(210, (W - 60) / 4 - 46), NH = 42, VG = 14, TOP = 30;
    const cols = [0, 1, 2, 3].map((l) => d.nodes.filter((n) => n.layer === l));
    const idx = Object.fromEntries(d.nodes.map((n) => [n.id, n]));
    // layer 1 keeps the server's order (credentials, program, places, messages); origins follow their targets
    const rank = Object.fromEntries(cols[1].map((n, i) => [n.id, i]));
    const tgt = (n) => { const e = d.edges.find((x) => x.from === n.id); return e ? (rank[e.to] ?? (e.to === "actor" ? -1 : 99)) : 99; };
    cols[0].sort((a, b) => tgt(a) - tgt(b));
    const rows = Math.max(1, ...cols.map((c) => c.length));
    const H = TOP + rows * (NH + VG) + 10;
    const colX = (l) => 14 + l * ((W - 28 - NW) / 3);
    cols.forEach((c, l) => c.forEach((n, i) => { n._x = colX(l); n._y = TOP + (H - TOP - 10 - c.length * (NH + VG) + VG) / 2 + i * (NH + VG); }));
    let g = `<svg class="trc-dag" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><title>Where this action came from: origins, what it used, the actor, the action</title><defs><marker id="trc-da" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,1L10,5L0,9z" fill="#7a8794"/></marker></defs>`;
    LAYERS.forEach((t, l) => { if (cols[l].length) g += `<text x="${colX(l)}" y="14" font-size="10.5" fill="${QUIET}" style="text-transform:uppercase;letter-spacing:.5px">${esc(t)}</text>`; });
    const font = "10px -apple-system, system-ui, sans-serif";
    let labels = "";
    d.edges.forEach((e, k) => {
      const a = idx[e.from], b = idx[e.to];
      if (!a || !b) return;
      const xa = a._x + NW, ya = a._y + NH / 2, xb = b._x - 2, yb = b._y + NH / 2, xm = (xa + xb) / 2;
      const c = NODE[a.type]?.color || "#7a8794";
      g += `<path class="trc-de" data-a="${esc(a.id)}" data-b="${esc(b.id)}" d="M${xa},${ya}C${xm},${ya} ${xm},${yb} ${xb},${yb}" fill="none" stroke="${c}" stroke-opacity=".55" stroke-width="1.6" marker-end="url(#trc-da)"/>`;
      // label near the source end, where edges have not yet merged
      const far = b.layer - a.layer > 1;
      const lx = far ? xa + 34 : xm, ly = far ? ya + (yb > ya ? 11 : -11) : (ya + yb) / 2;
      const w = textWidth(e.label, font) + 8;
      labels += `<g class="trc-dl"><rect x="${(lx - w / 2).toFixed(1)}" y="${(ly - 7).toFixed(1)}" width="${w.toFixed(1)}" height="14" rx="3" fill="#fff" opacity=".92"/><text x="${lx.toFixed(1)}" y="${(ly + 3.5).toFixed(1)}" font-size="10" text-anchor="middle" fill="#4b5866">${esc(e.label)}</text></g>`;
    });
    g += labels;
    d.nodes.forEach((n) => {
      const st = NODE[n.type] || NODE.origin;
      const tipText = `${st.word}: ${nodeLabel(n)}\n${n.record ? n.record + (n.time ? " · " + whenE(toTime(n.time), n.estimated) : "") + "\n" : ""}${cut(short(n.detail), 220)}`;
      g += `<g class="trc-dn t-${n.type}" data-node="${esc(n.id)}" ${nodeAttrs(n)} data-nocard data-tip="${esc(tipText)}"><rect x="${n._x}" y="${n._y}" width="${NW}" height="${NH}" rx="7" fill="${st.bg}" stroke="${st.color}" stroke-width="${n.type === "harm" ? 2 : 1}"/><rect x="${n._x}" y="${n._y}" width="5" height="${NH}" rx="2" fill="${st.color}"/>
        <text x="${n._x + 13}" y="${n._y + 17}" font-size="12" font-weight="600" fill="${INK}">${esc(fitName(nodeLabel(n), NW - 20, "600 12px -apple-system, system-ui, sans-serif"))}</text>
        <text x="${n._x + 13}" y="${n._y + 32}" font-size="10.5" fill="#5b6672">${esc(fitName(nodeSub(n), NW - 20, "10.5px -apple-system, system-ui, sans-serif"))}</text></g>`;
    });
    host.innerHTML = g + "</svg>";
  }
  function drawHarm(out, d) {
    const creds = d.nodes.filter((n) => n.type === "credential"), prog = d.nodes.find((n) => n.type === "program");
    const places = d.nodes.filter((n) => n.type === "place");
    out.innerHTML = `<div class="trc-head"><span class="badge${d.harmful ? " harmb" : ""}">${d.harmful ? "harmful action" : "record (not counted as harmful)"}</span> ${ent.rec(d.rec)} ${d.kind ? ent.intent(d.intent || d.kind) : ""} <span class="muted small">${esc(whenE(d.t != null ? d.t * 1000 : null, d.estimated))} · by</span> ${ent.actor(d.actor)}${d.agent && d.agent !== d.actor ? ` <span class="muted small">one ${term("agent", "estimated agent")} with</span> ${ent.actor(d.agent)}` : ""} <button type="button" class="trc-go" data-q="${esc(d.rec)}">Trace forward from this record →</button></div>
      ${d.text ? `<code class="trc-text block" title="start of the record's text (data written by the agents under study)">${esc(cut(d.text, 200))}</code>` : ""}
      <div class="kpis trc-strip">
        ${kpi(term("token", "credentials used"), fmt(creds.filter((c) => !c.as_data).length), creds.slice(0, 3).map((c) => ent.actor(c.actor)).join(" "))}
        ${kpi("earlier users of them", fmt(creds.reduce((a, c) => a + (c.shared ? 0 : c.users_before || 0), 0)), creds.some((c) => c.shared) ? "shared keys left out" : "other actors, before this record")}
        ${kpi(term("program", "program copies"), prog ? fmt(prog.copies) : "1", prog ? `${plural(prog.actors, "actor")} ran it` : "only this record runs this code")}
        ${kpi(term("place", "places touched"), fmt(d.places_total), places.slice(0, 2).map((p) => ent.place(p.place)).join(" "))}
        ${kpi(term("message", "messages that reached the actor before"), fmt(d.messages_before), d.messages_before ? "the latest are drawn" : "none: no other actor's write was read first")}
      </div>
      ${card("Where it came from", '<div class="trc-scroll"><div id="trcdag"></div></div><div class="trc-legend">' + Object.entries(NODE).filter(([k]) => d.nodes.some((n) => n.type === k)).map(([k, v]) => `<span><i class="sw" style="background:${v.bg};border-color:${v.color}"></i>${esc(v.word)}</span>`).join("") + '<span class="muted">read left to right · hover a box, click it to inspect</span></div>', { sub: `Backward from the action: the ${term("token", "credentials")} it used and where each first appeared, its ${term("program", "program")} and who ran it first, the ${term("place", "places")} it touches and who wrote them first, and the ${term("message", "messages")} that reached its actor before it.` })}
      ${card("The story, backward", `<ol class="trc-story back">${d.story.map((x) => `<li>${x.time ? `<span class="trc-when">${esc(whenE(toTime(x.time), x.estimated))}</span>` : '<span class="trc-when"></span>'}<div class="trc-what">${richText(x.text)} ${x.actor ? ent.actor(x.actor) : ""} ${x.place ? (x.actor || x.record ? "" : "") + ent.place(x.place) : ""} ${x.record ? `<span class="muted">in</span> ${ent.rec(x.record)}` : ""}</div></li>`).join("")}</ol>`, { sub: "One sentence per link in the picture above." })}`;
    const host = out.querySelector("#trcdag");
    const draw = () => harmDag(host, d);
    draw(); onResize(host.parentElement, draw); bindTips(host);
    host.addEventListener("mouseover", (e) => {
      const n = e.target.closest(".trc-dn"); if (!n) return;
      host.classList.add("dim");
      host.querySelectorAll(".trc-de").forEach((p) => p.classList.toggle("hot", p.dataset.a === n.dataset.node || p.dataset.b === n.dataset.node));
      n.classList.add("hot");
    });
    host.addEventListener("mouseout", (e) => {
      const n = e.target.closest(".trc-dn"); if (!n || n.contains(e.relatedTarget)) return;
      host.classList.remove("dim"); n.classList.remove("hot");
      host.querySelectorAll(".trc-de.hot").forEach((p) => p.classList.remove("hot"));
    });
  }

  // ---------------------------------------------------------------- the front door
  const START_ICON = { first_message: "read", widest_program: "run", found_credential: "seen", first_harm: "harm", broadcast_place: "write" };
  function startCards(st, compact) {
    if (!st.starts.length) return '<p class="muted small">No starting point could be counted from this dataset: it has no messages, shared programs, credentials or harmful actions. Type any text from a record above.</p>';
    return `<div class="trc-starts${compact ? " compact" : ""}">${st.starts.map((x) => `<button type="button" class="trc-start trc-go k-${esc(x.key)}" ${x.harm ? `data-harm="${esc(x.harm)}"` : `data-q="${esc(x.q)}"`} title="${esc(short(x.detail || ""))}">${icon(START_ICON[x.key] || "use")}<span class="tl">${esc(x.label)}</span><span class="td">${esc(cut(short(x.detail || ""), 110))}</span>${x.time ? `<span class="tt">${esc(whenE(toTime(x.time), x.estimated))}${x.record ? " · " + esc(x.record) : ""}</span>` : ""}</button>`).join("")}</div>`;
  }
  function setHash(q, harm) {
    const h = "#tab=trace" + (harm ? "&harm=" + enc(harm) : q ? "&q=" + enc(q) : "");
    try { history.replaceState(null, "", h); } catch { /* file: or sandboxed */ }
  }

  VIEWS.trace = async function (el, s) {
    const d = deepLink();
    if (d.tab === "trace" && (d.q || d.harm)) { TRC.q = d.harm ? "" : d.q; TRC.harm = d.harm || ""; }
    el.innerHTML = `<div class="trc">
      <div class="trc-door"><h2>Trace anything through the swarm</h2>
        <form id="trcform" class="trc-form" role="search"><input id="trcq" type="search" placeholder="Trace a token, file name, URL, place or record id" aria-label="Trace a token, file name, URL, place or record id" autocomplete="off" spellcheck="false" value="${esc(TRC.harm || TRC.q)}"><button class="primary" type="submit">Trace</button><button type="button" id="trclink" title="Copy a link to this trace">Copy link</button></form>
        <p class="small muted">One chain for whatever you type: where it first appeared, every hand-over between ${term("actor", "actors")}, what its holders did next, and the ${term("harm", "harmful actions")} it ended in. A record id of a harmful action can also be traced backward to where it came from.</p>
        <div id="trcstart"><p class="muted small">Counting starting points…</p></div></div>
      <div id="trcout"></div></div>`;
    const out = el.querySelector("#trcout"), input = el.querySelector("#trcq"), startHost = el.querySelector("#trcstart");
    let starts = null;
    const drawStarts = () => { if (starts) startHost.innerHTML = `<div class="trc-starthead small muted">${TRC.q || TRC.harm ? "Other starting points" : "Or start from what the data itself points at"}</div>${startCards(starts, !!(TRC.q || TRC.harm))}`; };
    const go = async () => {
      const run = ++TRC.run;
      setHash(TRC.q, TRC.harm);
      input.value = TRC.harm || TRC.q;
      drawStarts();
      if (!TRC.q && !TRC.harm) { out.innerHTML = ""; return; }
      out.innerHTML = '<p class="muted">Tracing…</p>';
      try {
        if (TRC.harm) {
          const r = await cached("/api/x/trace_harm?rec=" + enc(TRC.harm));
          if (run === TRC.run && S.tab === "trace") drawHarm(out, r);
        } else {
          const r = await cached("/api/x/trace_path?q=" + enc(TRC.q));
          if (run === TRC.run && S.tab === "trace") drawChain(out, r);
        }
      } catch (e) {
        if (run === TRC.run) out.innerHTML = `<div class="trc-none"><h3>Could not trace “${esc(cut(TRC.harm || TRC.q, 80))}”</h3><p class="muted">${esc(e.message)}</p></div>`;
      }
    };
    el.querySelector("#trcform").addEventListener("submit", (e) => { e.preventDefault(); TRC.q = input.value.trim(); TRC.harm = ""; go(); });
    el.querySelector("#trclink").addEventListener("click", (e) => {
      const url = location.origin + location.pathname + "#tab=trace" + (TRC.harm ? "&harm=" + enc(TRC.harm) : TRC.q ? "&q=" + enc(TRC.q) : "");
      const b = e.currentTarget;
      (navigator.clipboard?.writeText(url) || Promise.reject()).then(() => { b.textContent = "Copied"; }, () => { b.textContent = "Link is in the address bar"; }).finally(() => setTimeout(() => { b.textContent = "Copy link"; }, 1800));
    });
    // every "trace this" button in the view: starting points, suggestions, "where from?"
    el.addEventListener("click", (e) => {
      const b = e.target.closest(".trc-go");
      if (!b) return;
      e.preventDefault();
      if (b.dataset.harm) { TRC.harm = b.dataset.harm; TRC.q = ""; } else { TRC.q = b.dataset.q || ""; TRC.harm = ""; }
      go().then(() => { const top = el.querySelector("#trcout"); if (top && $("left")) $("left").scrollTop = Math.max(0, top.offsetTop - 80); });
    });
    go();
    try { starts = await cached("/api/x/trace_start"); drawStarts(); }
    catch (e) { startHost.innerHTML = `<p class="warn small">${esc(e.message)}</p>`; }
    if (!TRC.q && !TRC.harm) input.focus();
  };
})();

// Forensics, "Follow the evidence": trace anything, credential lifecycle, command-and-control,
// dead-drop ledger, better search. Server side: agenttrace/fx_lineage.py (/api/x/fx_*).
// Also adds two Inspector extras on records: "Records like this" and "Trace a string".
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const G = "Follow the evidence";
  Object.assign(GLOSSARY, {
    fx_trace: ["Trace", "Every record whose text contains a string (case-insensitive; a regular expression if written /like this/), in time order, with who held it and where. A string carried in a record is not proof that the actor read or used it."],
    fx_hop: ["Hop", "The first time an actor's record carries the string, linked to the latest earlier dated record by a different actor that carried it. It shows the order the string reached actors in, not a proven hand-over; a hop is marked as a message when the earlier actor had sent the later one a message before then."],
    fx_as_identity: ["Used as identity", "The string is (part of) a token the record authenticates with, not just text in it."],
    fx_lifecycle: ["Credential lifecycle", "For one identity token: first seen as data in a record (an info pattern from the pack, in a record that does not authenticate with it), first use, last use, and the time since (quiet)."],
    fx_quiet: ["Quiet since", "Hours from the token's last dated use to the last dated record in the dataset."],
    fx_exposure: ["Exposure", "Which kinds of place the records that authenticate with a token touched (read, write or post)."],
    fx_c2: ["Command place", "A place agents can leave instructions in for others: command files and board folders from the pack, plus any place two or more actors read."],
    fx_pickup: ["Pickup", "The first read of a place by another actor after a write: the app's message. The wait is the time from that write to the read."],
    fx_after: ["What changed after", "For each reader that picked a write up: its dated actions in the hour before the read and in the hour after it (the read itself not counted), and the intents and places it used for the first time in that hour. Timing, not proof that the write caused it."],
    fx_drop: ["Dead drop", "A place written by exactly one actor. Its pickups are the reads by other actors after a write, each counted once per reader at its first pickup."],
    fx_bool: ["Boolean search", "Words and \"quoted phrases\", combined with AND (or a space), OR, NOT (or a leading -), and parentheses. Matching is case-insensitive and inside words. /pattern/ is a regular expression."],
    fx_like: ["Records like this", "Other records ranked by what they share with this one: the same program (masked text, 3 points), the same start of code (2), and each shared place or token (rarer ones weigh more). Places and tokens on more than 5,000 records, and shared keys, are left out."],
  });

  const H = 3600e3;
  const enc = encodeURIComponent;
  const hl = (snip, terms) => {
    let s = esc(snip || "");
    (terms || []).filter((t) => t && t.length > 0).sort((a, b) => b.length - a.length).forEach((t) => {
      const rx = new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      s = s.replace(rx, (m) => `<mark>${m}</mark>`);
    });
    return s;
  };
  // take a q/fx deep link once, then drop it from the address so the side menu keeps working
  function takeLink(id) {
    const d = typeof deepLink === "function" ? deepLink() : {};
    if (d.fx !== id || d.q == null) return null;
    const p = new URLSearchParams(location.hash.replace(/^#/, ""));
    p.delete("fx"); p.delete("q");
    history.replaceState(null, "", location.pathname + location.search + (p.toString() ? "#" + p.toString() : ""));
    return d.q;
  }
  function linkFor(id, q) {
    return `${location.origin}${location.pathname}#tab=forensics&fx=${enc(id)}&q=${enc(q)}`;
  }
  // open one of these sections with a query, from anywhere in the app (the Inspector, other views)
  function openFx(id, q) {
    if (id === "trace") TR.q = q; else { SR.q = q; SR.offset = 0; }
    if (S.tab !== "forensics") goTab("forensics");
    const b = document.querySelector(`.fxnav button[data-fx="${id}"]`);
    if (b) b.click();
    else { location.hash = `tab=forensics&fx=${enc(id)}&q=${enc(q)}`; goTab("forensics"); }
  }
  window.fxTrace = (q) => openFx("trace", q);
  function copyLink(btn, url) {
    (navigator.clipboard?.writeText(url) || Promise.reject()).then(() => { btn.textContent = "Link copied"; }, () => { prompt("Copy this link", url); });
    setTimeout(() => { btn.textContent = "Copy link"; }, 1800);
  }
  const timeAxis = (t0, t1, X, y, x0, x1) => {
    let s = `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="${AXIS}"/>`;
    timeTicks(t0, t1, Math.max(3, Math.floor((x1 - x0) / 110))).forEach((k) => {
      s += `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${y}" y2="${y + 4}" stroke="${AXIS}"/><text x="${X(k.t)}" y="${y + 15}" font-size="10" fill="${QUIET}" text-anchor="middle">${esc(k.label)}</text>`;
    });
    return s;
  };

  // ================================================================ 1. trace anything
  const TR = { q: "", data: null, shown: 100 };
  async function renderTrace(host, s) {
    const linked = takeLink("trace");
    if (linked != null) TR.q = linked;
    const ex = examples(s);
    host.innerHTML = `
      <form class="fxq" id="trform"><input id="trq" placeholder="A token, URL, host, path or line of code; /regex/ for a pattern" value="${esc(TR.q)}" autocomplete="off">
        <button class="primary" type="submit">Trace</button> <button type="button" id="trlink">Copy link</button></form>
      <p class="small muted">${term("fx_trace", "Traces")} any string through every record. Try: ${ex.map((x) => `<button type="button" class="link trex" data-q="${esc(x)}">${esc(short(x))}</button>`).join(" · ") || "a word from a record"}. ${(s.identities || []).some((i) => /^\[CREDENTIAL \d+\]$/.test(i.identity)) ? "“cred 169” finds [CREDENTIAL 169]." : ""}</p>
      <div id="trout"></div>`;
    const go = (q) => { TR.q = q.trim(); $("trq").value = TR.q; run(); };
    $("trform").addEventListener("submit", (e) => { e.preventDefault(); go($("trq").value); });
    host.querySelectorAll(".trex").forEach((b) => b.addEventListener("click", () => go(b.dataset.q)));
    $("trlink").addEventListener("click", (e) => copyLink(e.target, linkFor("trace", $("trq").value.trim())));
    if (TR.q) run();
  }
  function examples(s) {
    const out = [];
    const tok = (s.seen_then_used || [])[0]?.item || (s.identities || []).find((i) => !(s.shared_identities || []).includes(i.identity))?.identity;
    if (tok) out.push(tok);
    const ch = (s.top_channels || [])[0]?.channel;
    if (ch) out.push(ch.split(":").slice(1).join(":"));
    return out.filter((x) => x && x.length < 80);
  }
  async function run() {
    const out = $("trout");
    if (!out) return;
    out.innerHTML = '<p class="muted">Tracing…</p>';
    let d;
    try { d = await cached("/api/x/fx_trace?q=" + enc(TR.q)); } catch (e) { out.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (!$("trout") || TR.q !== d.q) return;
    TR.data = d; TR.shown = 100;
    if (TR.named == null || TR.lastQ !== d.q) TR.named = d.named_actors >= 2;
    TR.lastQ = d.q;
    const hopsOf = () => (TR.named ? d.hops_named : d.hops), hopsTotal = () => (TR.named ? d.hops_named_total : d.hops_total);
    if (!d.total) { out.innerHTML = `<p class="note">No record contains “${esc(d.q)}”. Matching is case-insensitive and inside words; check the spelling, or try a shorter piece.</p>`; return; }
    const f = d.first;
    out.innerHTML = `
      <div class="kpis">
        ${kpi(term("record", "records"), fmt(d.total), `${fmt(d.dated)} dated`)}
        ${kpi(term("actor", "actors"), fmt(d.actors_total), `${fmt(d.named_actors)} named`)}
        ${kpi(term("fx_as_identity", "used as identity"), fmt(d.as_identity), "records")}
        ${kpi(term("place", "places"), fmt(d.places_total), "touched by these records")}
        ${kpi(term("fx_hop", "hops"), fmt(d.hops_total), `actor to actor; ${fmt(d.hops_named_total)} between named actors`)}
      </div>
      ${card("First appearance", `<div class="fxfirst">${ent.rec(f.id)} <span class="muted small">${esc(f.time ? f.time + " UTC" : "no time")} · ${esc(f.kind || "")}</span> by ${ent.actor(f.actor)} ${f.identity ? '<span class="badge">used as identity</span>' : '<span class="badge">as data</span>'} ${ent.intent(f.intent)}</div><pre class="fxsnip">${hl(f.snip, [d.regex ? "" : d.searched_for])}</pre>`,
        { sub: d.dated ? "The earliest dated record that contains the string." : "No matching record has a time; this is the first in file order." })}
      ${card("Lineage", '<div id="trchart" class="fxchart"></div>', { right: d.named_actors ? `<label class="small"><input type="checkbox" id="trnamed"${TR.named ? " checked" : ""}> ${term("named", "named actors")} only</label>` : "", sub: `Time across, actors down in the order they first held the string (first 40). Each dot is a record: filled where the string is ${term("fx_as_identity", "used as an identity")}, hollow where it is data. Lines are ${term("fx_hop", "hops")}: blue when the earlier actor had sent the later one a ${term("message")} first, grey otherwise. Click a dot to inspect the record.` })}
      ${card("When it appears", `${spark(d.series, { w: Math.min(900, (out.clientWidth || 700) - 30), h: 46, color: ACCENT })}${sparkAxisW(Math.min(900, (out.clientWidth || 700) - 30))}<p class="small muted">Matching records per hour across the whole dataset (${fmt(d.dated)} of ${fmt(d.total)} have a time).</p>`)}
      <div class="grid2">
        ${card("Actors in order of first contact", '<div id="tract"></div>', { sub: `${fmt(d.actors_total)} actors${d.actors_total > d.actors.length ? `, first ${fmt(d.actors.length)} listed` : ""}.` })}
        ${card("Places", d.places.length ? hbars(d.places.slice(0, 15).map((p) => ({ label: ent.place(p.channel), value: p.records, color: C.place, title: Object.entries(p.ops).map(([k, v]) => `${v} ${k}`).join(", ") }))) : '<p class="muted small">None of these records touches a place.</p>', { sub: `Places touched by the matching records, by records (${fmt(d.places_total)} in all).` })}
      </div>
      ${card(term("fx_hop", "Hops"), '<div id="trhops"></div>', { sub: '<span id="trhopsub"></span>' })}
      ${card("Every record", '<div id="trrows"></div>', { sub: `${fmt(d.total)} records in time order${d.total > d.shown ? `; the first ${fmt(d.shown)} are listed` : ""}. Click a record to open it in the Inspector, where you can pin it to the case file.` })}`;
    const ch = $("trchart"), draw = () => lineage(ch, d, TR.named, hopsOf());
    draw(); onResize(ch, draw);
    const acts = $("tract");
    const drawActs = (n) => {
      acts.innerHTML = table(["", "actor", "first contact", "records", "as identity"], d.actors.slice(0, n).map((a, i) => [String(i + 1), ent.actor(a.actor), `${esc(a.first || "no time")} ${ent.rec(a.first_record)}`, fmt(a.records), fmt(a.as_identity)])) +
        (d.actors.length > n ? `<button type="button" class="lmore">Show ${fmt(Math.min(d.actors.length, n + 50) - n)} more</button>` : "");
      acts.querySelector(".lmore")?.addEventListener("click", () => drawActs(n + 50));
    };
    drawActs(15);
    const hops = $("trhops");
    const drawHops = (n) => {
      const hs = hopsOf();
      $("trhopsub").textContent = `${fmt(hopsTotal())} hops${TR.named ? " between named actors" : ""}${hopsTotal() > hs.length ? `, first ${fmt(hs.length)} listed` : ""}: actor A held it, then actor B, with the two records and the gap.`;
      hops.innerHTML = hs.length ? table(["from", "record", "to", "record", "gap", "message"], hs.slice(0, n).map((h) => [ent.actor(h.from), `${ent.rec(h.from_record)} <span class="muted small">${esc(h.from_time)}</span>`, ent.actor(h.to), `${ent.rec(h.to_record)} <span class="muted small">${esc(h.to_time)}</span>`, hoursWord(h.gap_h), h.message ? `${ent.place(h.message.channel)} ${ent.rec(h.message.write_id)}→${ent.rec(h.message.read_id)}` : '<span class="muted small">none before</span>'])) +
        (hs.length > n ? `<button type="button" class="lmore">Show ${fmt(Math.min(hs.length, n + 50) - n)} more</button>` : "") : `<p class="muted small">Only one ${TR.named ? "named " : ""}actor holds it, or no matching record has a time.</p>`;
      hops.querySelector(".lmore")?.addEventListener("click", () => drawHops(n + 50));
    };
    drawHops(15);
    $("trnamed")?.addEventListener("change", (e) => { TR.named = e.target.checked; draw(); drawHops(15); });
    const rows = $("trrows");
    const drawRows = () => {
      const terms = d.regex ? [] : [d.searched_for];
      rows.innerHTML = table(["time", "record", "actor", "", "places", "text"], d.rows.slice(0, TR.shown).map((r) => [esc(r.time || "–"), ent.rec(r.id), ent.actor(r.actor), r.identity ? '<span class="badge" title="used as identity">id</span>' : "", r.places.slice(0, 3).map((p) => ent.place(p[0], ` <span class="op ${esc(p[1])}">${esc(p[1])}</span>`)).join(" ") + (r.places_total > 3 ? ` <span class="muted small">+${r.places_total - 3}</span>` : ""), `<span class="fxsn">${hl(r.snip, terms)}</span>`])) +
        (d.rows.length > TR.shown ? `<button type="button" class="lmore">Show ${fmt(Math.min(200, d.rows.length - TR.shown))} more of ${fmt(d.rows.length)}</button>` : "") +
        (d.total > d.rows.length ? `<p class="small muted">The list stops at ${fmt(d.rows.length)} of ${fmt(d.total)} records; the counts above cover all of them.</p>` : "");
      rows.querySelector(".lmore")?.addEventListener("click", () => { TR.shown += 200; drawRows(); });
    };
    drawRows();
  }
  function sparkAxisW(w) {
    const sp = span();
    return sp ? `<div class="saxis" style="width:${w}px"><span>${esc(dayWord(sp[0]))}</span><span>${esc(dayWord(sp[1] - 1))}</span></div>` : "";
  }
  function lineage(host, d, named, hops) {
    const keep = (a) => !named || !String(a).startsWith("run:");
    const rowsT = d.rows.filter((r) => r.time && keep(r.actor));
    if (!rowsT.length) { host.innerHTML = '<p class="muted small">No matching record has a time, so there is nothing to place on a time axis.</p>'; return; }
    const actors = d.actors.filter((a) => a.first && keep(a.actor)).slice(0, 40);
    const yi = new Map(actors.map((a, i) => [a.actor, i]));
    const W = Math.max(420, host.clientWidth || 700), x0 = 120, x1 = W - 14, rh = 16, top = 8;
    const Hh = top + actors.length * rh + 30;
    const ts = rowsT.map((r) => toTime(r.time));
    let t0 = Math.min(...ts), t1 = Math.max(...ts);
    if (t1 - t0 < H) { t0 -= H / 2; t1 += H / 2; }
    const pad = (t1 - t0) * 0.02; t0 -= pad; t1 += pad;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0), Y = (i) => top + i * rh + rh / 2;
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Lineage of the traced string">`;
    actors.forEach((a, i) => {
      svg += `<line x1="${x0}" x2="${x1}" y1="${Y(i)}" y2="${Y(i)}" stroke="${GRID}"/>`;
      svg += `<text x="${x0 - 6}" y="${Y(i) + 4}" font-size="11" text-anchor="end" fill="${String(a.actor).startsWith("run:") ? QUIET : INK}" data-actor="${esc(a.actor)}" style="cursor:pointer">${esc(fitName(short(a.actor), x0 - 12, "11px -apple-system, system-ui, sans-serif"))}</text>`;
    });
    hops.forEach((h) => {
      const a = yi.get(h.from), b = yi.get(h.to);
      if (a == null || b == null) return;
      const xa = X(toTime(h.from_time)), xb = X(toTime(h.to_time)), ya = Y(a), yb = Y(b), mx = (xa + xb) / 2;
      svg += `<path d="M${xa},${ya} C${mx},${ya} ${mx},${yb} ${xb},${yb}" fill="none" stroke="${h.message ? ACCENT : "#aab3bd"}" stroke-width="${h.message ? 1.6 : 1}"${h.message ? "" : ' stroke-dasharray="3 3"'} opacity=".8"><title>${esc(short(h.from))} → ${esc(short(h.to))}, ${esc(hoursWord(h.gap_h))}${h.message ? " (a message came first)" : ""}</title></path>`;
    });
    rowsT.forEach((r) => {
      const i = yi.get(r.actor);
      if (i == null) return;
      const x = X(toTime(r.time));
      svg += `<circle cx="${x.toFixed(1)}" cy="${Y(i)}" r="3.6" fill="${r.identity ? ACCENT : "#fff"}" stroke="${r.identity ? ACCENT : C.actor}" stroke-width="1.4" data-id="${esc(r.id)}" style="cursor:pointer"><title>${esc(r.id)} · ${esc(r.time)}</title></circle>`;
    });
    svg += timeAxis(t0, t1, X, top + actors.length * rh + 4, x0, x1) + "</svg>";
    host.innerHTML = svg + ((named ? d.named_actors : d.actors_total) > actors.length ? `<p class="small muted">${fmt(actors.length)} of ${fmt(named ? d.named_actors : d.actors_total)} ${named ? "named " : ""}actors shown (those with a dated record, earliest first)${d.rows.length < d.total ? `; dots for the first ${fmt(d.rows.length)} records` : ""}.</p>` : "");
  }

  // ================================================================ 2. credential lifecycle
  const CR = { sort: "first_use", dir: 1, q: "", shown: 60 };
  async function renderCred(host, s) {
    const d = await cached("/api/x/fx_credentials");
    if (!d.total) { host.innerHTML = `<p class="note">No record authenticates with an ${term("token")}: the pack finds none in this dataset, so there is no credential lifecycle to draw.</p>`; return; }
    host.innerHTML = `
      <div class="kpis">
        ${kpi(term("token", "identity tokens"), fmt(d.total), `${fmt(d.shared.length)} ${term("shared_key", "shared keys")}`)}
        ${kpi(term("seen_used", "seen before use"), fmt(d.seen_before_use), "first seen as data, then used")}
        ${kpi(term("carried", "carried edges"), fmt(d.carried_edges), "carrier → token, before its first use")}
        ${kpi(term("place", "place types"), fmt(d.place_types.length), d.place_types.map(human).join(", ") || "none")}
      </div>
      ${d.info_patterns ? "" : '<p class="note small">The pack has no info patterns, so tokens are never found as data: “first seen” and “carried by” stay empty.</p>'}
      ${card(term("fx_lifecycle", "Credential lifecycle"), '<div class="listbar small"><input id="crq" placeholder="Filter tokens, users or places" value="' + esc(CR.q) + '"> <span id="crn" class="muted"></span></div><div id="crtab"></div>',
        { sub: `One row per token. The bar spans the dataset: <span class="fxkey seen"></span> first seen as data, <span class="fxkey used"></span> first to last use, <span class="fxkey quiet"></span> ${term("fx_quiet", "quiet")} until the end. Click a column to sort.` })}
      ${card(term("fx_exposure", "Exposure map"), '<div id="crmat"></div>', { sub: "Tokens (the 40 with the most places) by the type of place their records touched; the cell is the number of places. Click a token to inspect it." })}`;
    const draw = () => credTable($("crtab"), d);
    let t = null;
    $("crq").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { CR.q = e.target.value.trim().toLowerCase(); CR.shown = 60; draw(); }, 200); });
    draw();
    exposure($("crmat"), d);
  }
  const CR_COLS = [["token", "token"], ["life", "lifecycle", null], ["seen", "first seen as data"], ["first_use", "first use"], ["last_use", "last use"], ["uses", "uses"], ["users_total", "users"], ["places_total", "places opened"], ["carried_by_total", "carried by"], ["quiet_h", "quiet"]];
  function credTable(host, d) {
    const sp = span();
    const q = CR.q.replace(/\bcred (\d+)/g, "[credential $1]");
    let rows = d.tokens.filter((r) => !q || [r.token, short(r.token), ...r.users.map((u) => u.actor + " " + short(u.actor)), ...r.places.map((p) => p.channel)].join(" ").toLowerCase().includes(q));
    const k = CR.sort;
    rows = rows.slice().sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * CR.dir;
    });
    $("crn").textContent = `${fmt(rows.length)} of ${fmt(d.total)} tokens`;
    const bar = (r) => {
      if (!sp) return "";
      const w = 150, h = 14, X = (t) => Math.max(0, Math.min(w, (t - sp[0]) / (sp[1] - sp[0]) * w));
      const fu = toTime(r.first_use), lu = toTime(r.last_use), se = toTime(r.seen);
      let svg = `<svg width="${w}" height="${h}" class="fxlife"><line x1="0" x2="${w}" y1="${h / 2}" y2="${h / 2}" stroke="${GRID}"/>`;
      if (lu != null) svg += `<line x1="${X(lu)}" x2="${w}" y1="${h / 2}" y2="${h / 2}" stroke="#cfd5dc" stroke-width="2" stroke-dasharray="2 2"/>`;
      if (fu != null) svg += `<rect x="${X(fu)}" y="${h / 2 - 3}" width="${Math.max(2, X(lu) - X(fu))}" height="6" rx="2" fill="${r.shared ? BASE : ACCENT}"/><circle cx="${X(fu)}" cy="${h / 2}" r="3" fill="${r.shared ? BASE : ACCENT}"/>${X(lu) - X(fu) > 4 ? `<circle cx="${X(lu)}" cy="${h / 2}" r="3" fill="${r.shared ? BASE : ACCENT}"/>` : ""}`;
      if (se != null) svg += `<path d="M${X(se)},${h / 2 - 5} l4,5 l-4,5 l-4,-5z" fill="${C.actor}"><title>first seen as data ${esc(r.seen)}</title></path>`;
      return svg + `<title>${esc(`${r.seen ? "seen " + r.seen + " · " : ""}used ${r.first_use || "–"} to ${r.last_use || "–"}`)}</title></svg>`;
    };
    const head = `<tr>${CR_COLS.map(([key, label, sortable]) => `<th${sortable === null ? "" : ` data-sort="${key}" class="fxsort${CR.sort === key ? " on" : ""}"`}>${esc(label)}${CR.sort === key ? (CR.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>`;
    const body = rows.slice(0, CR.shown).map((r) => `<tr>
      <td>${ent.actor(r.token)}${r.shared ? ' <span class="badge warnb" title="a key many agents use">shared</span>' : ""}</td>
      <td>${bar(r)}</td>
      <td>${r.seen_record ? `${esc(r.seen || "no time")} ${ent.rec(r.seen_record)}${r.seen_actor && r.seen_actor !== r.token ? ` <span class="muted small">by</span> ${ent.actor(r.seen_actor)}` : ""}${r.seen_before_use ? ' <span class="badge">before use</span>' : ""}` : '<span class="muted small">never as data</span>'}</td>
      <td>${esc(r.first_use || "no time")} ${ent.rec(r.first_use_record)}</td>
      <td>${esc(r.last_use || "no time")} ${ent.rec(r.last_use_record)}</td>
      <td class="n">${fmt(r.uses)}</td>
      <td>${r.users.slice(0, 3).map((u) => ent.actor(u.actor, ` <span class="muted">${fmt(u.n)}</span>`)).join(" ")}${r.users_total > 3 ? ` <span class="muted small">+${fmt(r.users_total - 3)}</span>` : ""}</td>
      <td>${r.places_total ? `<b>${fmt(r.places_total)}</b> ${r.places.slice(0, 2).map((p) => ent.place(p.channel)).join(" ")}` : '<span class="muted small">none</span>'}</td>
      <td>${r.carried_by.slice(0, 3).map((c) => ent.actor(c.actor, ` <span class="muted">${fmt(c.records)}</span>`)).join(" ")}${r.carried_by_total > 3 ? ` <span class="muted small">+${fmt(r.carried_by_total - 3)}</span>` : ""}${r.carried_by.length ? ` <span class="muted small">e.g.</span> ${ent.rec(r.carried_by[0].evidence[0])}` : ""}</td>
      <td class="n">${hoursWord(r.quiet_h)}</td></tr>`).join("");
    host.innerHTML = rows.length ? `<div class="fxscroll"><table class="fxcred"><thead>${head}</thead><tbody>${body}</tbody></table></div>${rows.length > CR.shown ? `<button type="button" class="lmore">Show ${fmt(Math.min(100, rows.length - CR.shown))} more of ${fmt(rows.length)}</button>` : ""}` : '<p class="muted">No token matches.</p>';
    host.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (CR.sort === key) CR.dir = -CR.dir; else { CR.sort = key; CR.dir = ["uses", "users_total", "places_total", "carried_by_total", "quiet_h"].includes(key) ? -1 : 1; }
      credTable(host, d);
    }));
    host.querySelector(".lmore")?.addEventListener("click", () => { CR.shown += 100; credTable(host, d); });
  }
  function exposure(host, d) {
    const types = d.place_types;
    const rows = d.tokens.filter((r) => r.places_total).sort((a, b) => b.places_total - a.places_total).slice(0, 40);
    if (!rows.length || !types.length) { host.innerHTML = '<p class="muted small">No token\'s records touch a place.</p>'; return; }
    const mx = Math.max(1, ...rows.flatMap((r) => types.map((t) => r.place_types[t] || 0)));
    host.innerHTML = `<div class="fxscroll"><table class="fxmat"><thead><tr><th>token</th>${types.map((t) => `<th>${esc(placeType(t, 2))}</th>`).join("")}<th>all places</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${ent.actor(r.token)}${r.shared ? ' <span class="badge warnb">shared</span>' : ""}</td>${types.map((t) => { const v = r.place_types[t] || 0; return `<td class="fxcell" style="background:${v ? `rgba(107,70,193,${(0.12 + 0.75 * Math.sqrt(v / mx)).toFixed(2)})` : "transparent"};color:${v / mx > 0.45 ? "#fff" : INK}">${v ? fmt(v) : ""}</td>`; }).join("")}<td class="n">${fmt(r.places_total)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  // ================================================================ 3. command-and-control
  const C2 = { ch: null, all: false };
  async function renderC2(host, s) {
    const d = await cached("/api/x/fx_c2");
    if (!d.total) { host.innerHTML = `<p class="note">No ${term("fx_c2", "command place")}: the pack names no command files or boards here, and no place has two or more readers.</p>`; return; }
    host.innerHTML = `
      <p class="small muted">${fmt(d.total)} ${term("fx_c2", "command places")}${Object.keys(d.types).length > 1 ? `: ${Object.entries(d.types).map(([t, n]) => `${fmt(n)} ${esc(placeType(t, n))}`).join(", ")}` : ""}${d.command_places ? `, of which ${fmt(d.command_places)} are command files or boards` : " (no command files or boards here, so these are the places two or more actors read)"}. Pick one to see its writes, its reads and ${term("fx_after", "what changed after")} each write.</p>
      <div class="fxc2"><div class="fxc2list card"><div class="listbar small"><input id="c2q" placeholder="Filter places"> ${d.command_places && d.command_places < d.total ? `<label class="small"><input type="checkbox" id="c2all"${C2.all ? " checked" : ""}> also places with 2+ readers</label>` : ""}</div><div id="c2rows"></div></div>
      <div id="c2det" class="fxc2det"></div></div>`;
    let q = "";
    const rowsFor = () => d.places.filter((r) => (C2.all || !d.command_places || r.command) && (!q || (r.channel + " " + placeLabel(r.channel)).toLowerCase().includes(q)));
    const list = () => {
      const rows = rowsFor().slice(0, 300);
      $("c2rows").innerHTML = rows.length ? `<div class="fxplist">${rows.map((r) => `<button type="button" class="fxpl${r.channel === C2.ch ? " on" : ""}" data-ch="${esc(r.channel)}"><span class="fxpn">${esc(placeLabel(r.channel))}</span><span class="muted small">${fmt(r.writes)} w · ${fmt(r.reads)} r · ${fmt(r.readers)} readers · ${fmt(r.messages)} msg</span></button>`).join("")}</div>${rowsFor().length > 300 ? `<p class="small muted">First 300 of ${fmt(rowsFor().length)}; filter to find others.</p>` : ""}` : '<p class="muted small">None.</p>';
      $("c2rows").querySelectorAll(".fxpl").forEach((b) => b.addEventListener("click", () => { C2.ch = b.dataset.ch; list(); detail(); }));
    };
    $("c2q").addEventListener("input", (e) => { q = e.target.value.trim().toLowerCase(); list(); });
    $("c2all")?.addEventListener("change", (e) => { C2.all = e.target.checked; list(); });
    if (!C2.ch || !d.places.some((r) => r.channel === C2.ch)) C2.ch = (rowsFor()[0] || d.places[0]).channel;
    list(); detail();
  }
  async function detail() {
    const host = $("c2det");
    if (!host) return;
    const ch = C2.ch;
    host.innerHTML = '<p class="muted">Loading…</p>';
    let p;
    try { p = await cached("/api/x/fx_c2_place?ch=" + enc(ch)); } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (C2.ch !== ch || !$("c2det")) return;
    const sm = p.summary;
    host.innerHTML = `
      ${card(`${ent.place(p.channel)}`, `<div id="c2tl" class="fxchart"></div>`, { sub: `${esc(placeType(p.type))} · ${plural(p.writes_total, "write")} by ${plural(p.writers.length, "writer")}, read by ${plural(p.readers.length, "actor")}. Lanes per actor (first 25): <span class="fxkey w"></span> write or post, <span class="fxkey r"></span> read. Click a mark to inspect the record.` })}
      ${card(term("fx_after", "What changed after each write"), `<p class="small">${p.cards_total ? `${plural(p.cards_total, "write")} ${p.cards_total === 1 ? "was" : "were"} picked up (${plural(sm.pickups, "pickup")} by other actors${p.cards_total > p.cards.length ? `; the first ${fmt(p.cards.length)} writes shown` : ""}). In the hour after the read, <b>${fmt(sm.with_new_intent)}</b> readers did something new (a first intent), <b>${fmt(sm.with_new_place)}</b> went to another place for the first time, <b>${fmt(sm.more_after)}</b> acted more than in the hour before and <b>${fmt(sm.fewer_after)}</b> less.` : "No write here was picked up by another actor."} ${p.writes_without_pickup ? `${plural(p.writes_without_pickup, "write")} had no pickup.` : ""}</p><div class="fxcards">${p.cards.map(writeCard).join("")}</div>`,
        { sub: "Before / after: the reader's dated actions in the hour before it read the write and in the hour from the read. Timing only: a reader may have changed for another reason." })}`;
    const tl = $("c2tl"), draw = () => placeTimeline(tl, p);
    draw(); onResize(tl, draw);
  }
  function writeCard(c) {
    return `<div class="fxwc"><div class="fxwch">${ent.actor(c.writer)} <span class="op ${esc(c.op)}">${esc(c.op)}</span> ${ent.rec(c.record)} <span class="muted small">${esc(c.time || "no time")}</span></div>
      ${c.readers.map((r) => {
        const mx = Math.max(1, r.before || 0, r.after || 0);
        return `<div class="fxrd"><div>${ent.actor(r.actor)} read it in ${ent.rec(r.read_record)} <span class="muted small">${esc(r.read_time || "")}${r.wait_h != null ? `, ${hoursWord(r.wait_h)} after the write` : ""}</span></div>
        ${r.before != null ? `<div class="fxba"><span class="small muted">hour before</span><span class="fxbab"><i style="width:${(100 * r.before / mx).toFixed(0)}%"></i></span><b>${fmt(r.before)}</b><span class="small muted">hour after</span><span class="fxbab after"><i style="width:${(100 * r.after / mx).toFixed(0)}%"></i></span><b>${fmt(r.after)}</b><span class="small muted">actions</span></div>
        ${r.new_intents.length ? `<div class="small">first time: ${r.new_intents.map((x) => `${ent.intent(x.intent)} ${ent.rec(x.record)}`).join(" ")}</div>` : ""}
        ${r.new_places_total ? `<div class="small">new places: ${r.new_places.map((x) => ent.place(x.channel)).join(" ")}${r.new_places_total > r.new_places.length ? ` <span class="muted">+${fmt(r.new_places_total - r.new_places.length)}</span>` : ""}</div>` : ""}
        ${r.records_after.length ? `<div class="small muted">records after: ${r.records_after.map((x) => ent.rec(x)).join(" ")}</div>` : ""}` : '<div class="small muted">The read has no time, so no before and after.</div>'}</div>`;
      }).join("")}</div>`;
  }
  function placeTimeline(host, p) {
    const ops = p.timeline.filter((o) => o.time);
    if (!ops.length) { host.innerHTML = '<p class="muted small">No operation here has a time.</p>'; return; }
    const order = [];
    ops.forEach((o) => { if (!order.includes(o.actor)) order.push(o.actor); });
    const actors = order.slice(0, 25), yi = new Map(actors.map((a, i) => [a, i]));
    const W = Math.max(380, host.clientWidth || 600), x0 = 110, x1 = W - 12, rh = 16, top = 6, Hh = top + actors.length * rh + 28;
    const ts = ops.map((o) => toTime(o.time));
    let t0 = Math.min(...ts), t1 = Math.max(...ts);
    if (t1 - t0 < H) { t0 -= H / 2; t1 += H / 2; }
    const pad = (t1 - t0) * 0.02; t0 -= pad; t1 += pad;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0), Y = (i) => top + i * rh + rh / 2;
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}">`;
    actors.forEach((a, i) => { svg += `<line x1="${x0}" x2="${x1}" y1="${Y(i)}" y2="${Y(i)}" stroke="${GRID}"/><text x="${x0 - 6}" y="${Y(i) + 4}" font-size="11" text-anchor="end" fill="${INK}" data-actor="${esc(a)}" style="cursor:pointer">${esc(fitName(short(a), x0 - 12, "11px -apple-system, system-ui, sans-serif"))}</text>`; });
    p.cards.forEach((c) => c.readers.forEach((r) => {
      const a = yi.get(c.writer), b = yi.get(r.actor);
      if (a == null || b == null || !c.time || !r.read_time) return;
      svg += `<line x1="${X(toTime(c.time))}" y1="${Y(a)}" x2="${X(toTime(r.read_time))}" y2="${Y(b)}" stroke="${ACCENT}" stroke-width="1" opacity=".45"/>`;
    }));
    ops.forEach((o) => {
      const i = yi.get(o.actor);
      if (i == null) return;
      const x = X(toTime(o.time)).toFixed(1), y = Y(i);
      svg += o.op === "read" ? `<circle cx="${x}" cy="${y}" r="3.4" fill="${ACCENT}" data-id="${esc(o.record)}" style="cursor:pointer"><title>${esc(o.record)} read · ${esc(o.time)}</title></circle>`
        : `<rect x="${x - 3.6}" y="${y - 3.6}" width="7.2" height="7.2" fill="${HARM}" data-id="${esc(o.record)}" style="cursor:pointer"><title>${esc(o.record)} ${esc(o.op)} · ${esc(o.time)}</title></rect>`;
    });
    svg += timeAxis(t0, t1, X, top + actors.length * rh + 4, x0, x1) + "</svg>";
    host.innerHTML = svg + (order.length > actors.length ? `<p class="small muted">${fmt(actors.length)} of ${fmt(order.length)} actors shown, earliest first.</p>` : "") + (p.ops_total > p.timeline.length ? `<p class="small muted">First ${fmt(p.timeline.length)} of ${fmt(p.ops_total)} operations.</p>` : "");
  }

  // ================================================================ 4. dead-drop ledger
  const DR = { status: "", q: "", shown: 80 };
  async function renderDrops(host, s) {
    const d = await cached("/api/x/fx_drops");
    if (!d.total) { host.innerHTML = `<p class="note">No place is written by exactly one actor${d.multi_writer_places ? ` (${plural(d.multi_writer_places, "place")} with several writers are not ${term("fx_drop", "dead drops")})` : ""}.</p>`; return; }
    host.innerHTML = `
      <div class="kpis">
        ${kpi(term("fx_drop", "dead drops"), fmt(d.total), `places written by one actor; ${fmt(d.multi_writer_places)} with several writers left out`)}
        ${kpi("never picked up", fmt(d.never), pct(d.never / d.total))}
        ${kpi("picked up by one", fmt(d.one), "other actor")}
        ${kpi("picked up by many", fmt(d.many), "2 or more other actors")}
        ${kpi(term("fx_pickup", "median wait"), hoursWord(d.median_wait_h), `over ${plural(d.pickups, "pickup")}`)}
      </div>
      <div class="grid2">
        ${card(term("latency", "Wait before pickup"), '<div id="drhist"></div>', { sub: `Each reader's first ${term("fx_pickup", "pickup")} of each drop, by the time from the write it picked up (${plural(d.pickups, "pickup")} with a time).` })}
        ${card("Export", `<p class="small">One CSV line per pickup (and one per drop never picked up): place, writer, first write, reader, read time, the records, and the wait in hours.</p><button type="button" class="primary" id="drcsv">Download dead_drops.csv</button> <span id="drcsvn" class="small muted"></span>`)}
      </div>
      ${card("Ledger", `<div class="listbar small"><input id="drq" placeholder="Filter places, writers or readers" value="${esc(DR.q)}"> ${[["", "all"], ["many", "picked up by many"], ["one", "by one"], ["never", "never picked up"]].map(([k, l]) => `<button type="button" class="fxst${DR.status === k ? " on" : ""}" data-st="${k}">${esc(l)}</button>`).join(" ")} <span id="drn" class="muted"></span></div><div id="drtab"></div>`,
        { sub: "Places written by one actor, most picked up first. Readers show their wait after the write they picked up." })}`;
    hist($("drhist"), d.hist);
    const draw = () => dropTable($("drtab"), d);
    let t = null;
    $("drq").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { DR.q = e.target.value.trim().toLowerCase(); DR.shown = 80; draw(); }, 200); });
    host.querySelectorAll(".fxst").forEach((b) => b.addEventListener("click", () => { DR.status = b.dataset.st; host.querySelectorAll(".fxst").forEach((x) => x.classList.toggle("on", x === b)); DR.shown = 80; draw(); }));
    $("drcsv").addEventListener("click", async () => {
      const r = await api("/api/x/fx_drops_csv");
      const url = URL.createObjectURL(new Blob([r.csv], { type: "text/csv" }));
      const a = document.createElement("a"); a.href = url; a.download = r.filename || "dead_drops.csv"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      $("drcsvn").textContent = `${fmt(r.rows)} lines`;
    });
    draw();
  }
  function hist(host, bins) {
    const W = Math.max(300, Math.min(560, host.clientWidth || 420)), Hh = 140, x0 = 30, x1 = W - 6, y1 = Hh - 34, y0 = 8;
    const mx = Math.max(1, ...bins.map((b) => b.n)), bw = (x1 - x0) / bins.length;
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}"><line x1="${x0}" x2="${x1}" y1="${y1}" y2="${y1}" stroke="${AXIS}"/>`;
    bins.forEach((b, i) => {
      const h = (b.n / mx) * (y1 - y0), x = x0 + i * bw;
      svg += `<rect x="${x + 2}" y="${y1 - h}" width="${bw - 4}" height="${h}" fill="${ACCENT}" rx="2"><title>${esc(b.bin)}: ${fmt(b.n)}</title></rect>`;
      if (b.n) svg += `<text x="${x + bw / 2}" y="${y1 - h - 3}" font-size="10" text-anchor="middle" fill="${INK}">${fmt(b.n)}</text>`;
      svg += `<text x="${x + bw / 2}" y="${y1 + 12 + (i % 2) * 11}" font-size="9.5" text-anchor="middle" fill="${QUIET}">${esc(b.bin)}</text>`;
    });
    host.innerHTML = svg + "</svg>";
  }
  function dropTable(host, d) {
    const rows = d.rows.filter((r) => (!DR.status || r.status === DR.status) && (!DR.q || [r.channel, placeLabel(r.channel), r.writer, short(r.writer), ...r.readers.map((x) => x.actor + " " + short(x.actor))].join(" ").toLowerCase().includes(DR.q)));
    $("drn").textContent = `${fmt(rows.length)} of ${fmt(d.total)}${d.rows.length < d.total ? ` (the first ${fmt(d.rows.length)} are loaded)` : ""}`;
    host.innerHTML = table(["place", "writer", "writes", "first write", "pickups", "first wait", "median wait", "picked up by"], rows.slice(0, DR.shown).map((r) => [
      ent.place(r.channel), ent.actor(r.writer), fmt(r.writes), `${esc(r.first_write || "no time")} ${ent.rec(r.first_write_record)}`,
      r.pickups ? `<b>${fmt(r.pickups)}</b>` : '<span class="badge warnb">never</span>', hoursWord(r.first_wait_h), hoursWord(r.median_wait_h),
      r.readers.slice(0, 4).map((x) => `${ent.actor(x.actor)} <span class="muted small">${hoursWord(x.wait_h)}</span> ${ent.rec(x.read_record)}`).join("<br>") + (r.pickups > 4 ? `<br><span class="muted small">and ${fmt(r.pickups - 4)} more</span>` : "")])) +
      (rows.length > DR.shown ? `<button type="button" class="lmore">Show ${fmt(Math.min(100, rows.length - DR.shown))} more of ${fmt(rows.length)}</button>` : "");
    host.querySelector(".lmore")?.addEventListener("click", () => { DR.shown += 100; dropTable(host, d); });
  }

  // ================================================================ 5. better search
  const SR = { q: "", kind: "", intent: "", actor: "", hour: "", offset: 0, like: "" };
  const SAVED = "swarm-tracer.fx_saved_searches";
  const loadSaved = () => { try { return JSON.parse(localStorage.getItem(SAVED) || "[]"); } catch { return []; } };
  const storeSaved = (x) => { try { localStorage.setItem(SAVED, JSON.stringify(x.slice(0, 40))); } catch { /* blocked */ } };
  async function renderSearch(host, s) {
    const linked = takeLink("search");
    if (linked != null) { SR.q = linked; SR.offset = 0; }
    const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;
    host.innerHTML = `
      <form id="srform" class="fxq fxsearch">
        <input id="srq" placeholder='e.g. "x-api-key" AND (board OR dataset) NOT test   or   /169\\.254\\.\\d+/' value="${esc(SR.q)}" autocomplete="off">
        <button class="primary" type="submit">Search</button>
        <div class="fxfilters small">
          <select id="srkind">${opt("", "any kind", SR.kind)}${Object.keys(s.kinds || {}).map((k) => opt(k, k, SR.kind)).join("")}</select>
          <select id="srintent">${opt("", "any intent", SR.intent)}${Object.keys(s.intents || {}).map((k) => opt(k, human(k), SR.intent)).join("")}</select>
          <input id="sractor" placeholder="actor (exact, e.g. [CREDENTIAL 169])" value="${esc(SR.actor)}">
          <input id="srhour" placeholder="hour: 2026-07-11 04 or a..b" value="${esc(SR.hour)}">
          <button type="button" id="srsave">Save this search</button> <button type="button" id="srlink">Copy link</button>
        </div></form>
      <p class="small muted">${term("fx_bool", "Boolean search")} over record text: words, "quoted phrases", AND, OR, NOT (or -word), parentheses; /pattern/ for a regular expression (add c after the last slash to match case).</p>
      <div id="srsaved" class="chips"></div>
      <div id="srout"></div>
      ${card(term("fx_like", "Records like this"), `<form id="lkform" class="fxq"><input id="lkid" placeholder="a record id" value="${esc(SR.like)}"><button type="submit">Find similar</button></form><div id="lkout"></div>`, { sub: "The same program, the same start of code, the same places, the same tokens. Also in the Inspector for any record." })}`;
    const read = () => { SR.q = $("srq").value.trim(); SR.kind = $("srkind").value; SR.intent = $("srintent").value; SR.actor = $("sractor").value.trim().replace(/^cred (\d+)$/i, "[CREDENTIAL $1]"); SR.hour = $("srhour").value.trim(); };
    $("srform").addEventListener("submit", (e) => { e.preventDefault(); read(); SR.offset = 0; doSearch(); });
    ["srkind", "srintent"].forEach((id) => $(id).addEventListener("change", () => { read(); SR.offset = 0; doSearch(); }));
    $("srsave").addEventListener("click", () => {
      read();
      if (!SR.q && !SR.kind && !SR.intent && !SR.actor && !SR.hour) return;
      const name = prompt("Name this search", SR.q || "filters");
      if (name == null) return;
      const list = loadSaved().filter((x) => x.name !== name);
      list.unshift({ name, q: SR.q, kind: SR.kind, intent: SR.intent, actor: SR.actor, hour: SR.hour });
      storeSaved(list); savedChips();
    });
    $("srlink").addEventListener("click", (e) => copyLink(e.target, linkFor("search", $("srq").value.trim())));
    $("lkform").addEventListener("submit", (e) => { e.preventDefault(); SR.like = $("lkid").value.trim(); likeInto($("lkout"), SR.like, true); });
    savedChips();
    if (SR.q || SR.kind || SR.intent || SR.actor || SR.hour) doSearch();
    if (SR.like) likeInto($("lkout"), SR.like, true);
  }
  function savedChips() {
    const host = $("srsaved");
    if (!host) return;
    const list = loadSaved();
    host.innerHTML = list.length ? `<span class="small muted">Saved (this browser):</span> ${list.map((x, i) => `<span class="chip fxsaved" data-i="${i}" title="${esc([x.q, x.kind, x.intent, x.actor, x.hour].filter(Boolean).join(" · "))}">${esc(x.name)} <button type="button" class="link fxrm" data-i="${i}" title="Remove" aria-label="Remove this saved search">×</button></span>`).join("")}` : "";
    host.querySelectorAll(".fxsaved").forEach((c) => c.addEventListener("click", (e) => {
      const list2 = loadSaved();
      if (e.target.closest(".fxrm")) { list2.splice(+c.dataset.i, 1); storeSaved(list2); savedChips(); return; }
      Object.assign(SR, { q: "", kind: "", intent: "", actor: "", hour: "" }, list2[+c.dataset.i], { offset: 0 });
      renderSearch($("fxsec"), S.summary);
    }));
  }
  async function doSearch() {
    const out = $("srout");
    if (!out) return;
    out.innerHTML = '<p class="muted">Searching…</p>';
    const qs = new URLSearchParams({ q: SR.q, kind: SR.kind, intent: SR.intent, actor: SR.actor, hour: SR.hour, offset: SR.offset, limit: 100 });
    let d;
    try { d = await cached("/api/x/fx_search?" + qs); } catch (e) { out.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (!$("srout")) return;
    const w = Math.min(900, (out.clientWidth || 700) - 30);
    out.innerHTML = card(`${fmt(d.total)} matching records`, `
      ${d.timed ? spark(d.hist, { w, h: 40, color: ACCENT }) + sparkAxisW(w) + `<p class="small muted">Matches per hour (${fmt(d.timed)} with a time).</p>` : ""}
      ${d.total ? `<div class="fxfacets small">${Object.entries(d.facets.kind).map(([k, n]) => `<span class="chip">${esc(k)} <b>${fmt(n)}</b></span>`).join("")} ${Object.entries(d.facets.intent).slice(0, 8).map(([k, n]) => `${ent.intent(k)} <b>${fmt(n)}</b>`).join(" ")}</div>
      <div class="fxfacets small">${d.facets.actor.slice(0, 8).map(([a, n]) => ent.actor(a, ` <span class="muted">${fmt(n)}</span>`)).join(" ")}</div>` : ""}
      ${table(["time", "record", "actor", "kind", "intent", "text", ""], d.rows.map((r) => [esc(r.time || "–"), ent.rec(r.id), ent.actor(r.actor), esc(r.kind), ent.intent(r.intent), `<span class="fxsn">${hl(r.snip, d.terms)}</span>`, `<button type="button" class="link fxlk" data-id="${esc(r.id)}" title="Records like this">like this</button>`]))}
      <div class="fxpage small">${d.offset > 0 ? '<button type="button" id="srprev">← previous 100</button>' : ""} <span class="muted">${d.total ? `${fmt(d.offset + 1)}–${fmt(d.offset + d.rows.length)} of ${fmt(d.total)}` : ""}</span> ${d.offset + d.rows.length < d.total ? '<button type="button" id="srnext">next 100 →</button>' : ""}</div>`,
      { sub: d.regex ? "Regular expression over the record text." : d.terms.length ? `Terms highlighted: ${d.terms.map((t) => `<code>${esc(t)}</code>`).join(" ")}` : "Filters only." });
    $("srprev")?.addEventListener("click", () => { SR.offset = Math.max(0, SR.offset - 100); doSearch(); });
    $("srnext")?.addEventListener("click", () => { SR.offset += 100; doSearch(); });
    out.querySelectorAll(".fxlk").forEach((b) => b.addEventListener("click", () => { SR.like = b.dataset.id; $("lkid").value = SR.like; likeInto($("lkout"), SR.like, true); $("lkout").scrollIntoView({ behavior: "smooth", block: "center" }); }));
  }
  async function likeInto(host, id, wide) {
    if (!host || !id) return;
    host.innerHTML = '<p class="muted small">Looking…</p>';
    let d;
    try { d = await cached("/api/x/fx_like?id=" + enc(id)); } catch (e) { host.innerHTML = `<p class="warn small">${esc(e.message)}</p>`; return; }
    const why = (r) => `${r.why.map((w) => `<span class="chip">${esc(w)}</span>`).join("")}${r.places.map((p) => ent.place(p)).join(" ")}${r.tokens.map((t) => ent.actor(t)).join(" ")}`;
    host.innerHTML = d.rows.length ? (wide
      ? table(["record", "time", "actor", "intent", "shares", "score"], d.rows.map((r) => [ent.rec(r.id), esc(r.time || "–"), ent.actor(r.actor), ent.intent(r.intent), why(r), r.score.toFixed(1)]))
      : `<div class="fxlike">${d.rows.map((r) => `<div class="mline">${ent.rec(r.id)} ${ent.actor(r.actor)} <span class="muted small">${esc(r.time || "no time")}</span><div class="small">${why(r)}</div></div>`).join("")}</div>`) +
      `<p class="small muted">${plural(d.candidates, "record")} share something with ${esc(d.id)}; top ${fmt(d.rows.length)} shown. Same program: ${fmt(d.same_program)}; same start of code: ${fmt(d.same_start)}.${d.skipped.length ? ` Left out as too common: ${d.skipped.map((x) => `${esc(x.what)} ${esc(x.what === "place" ? placeLabel(x.key) : short(x.key))} (${fmt(x.records)} records)`).join(", ")}.` : ""}</p>`
      : `<p class="muted small">No other record shares a program, a place or a token with ${esc(d.id)}${d.skipped.length ? ` (left out as too common: ${d.skipped.map((x) => esc(x.what === "place" ? placeLabel(x.key) : short(x.key))).join(", ")})` : ""}.</p>`;
  }

  // ================================================================ Inspector extras on records
  const URL_RX = /https?:\/\/(?:\[[^\]\s]{1,60}(?: [^\]\s]{1,30})?\]|[^\s'"`<>()\[\]\\])+/g;
  window.INSPECTOR_EXTRAS.push((kind, key, data) => {
    if (kind !== "record" || !data) return "";
    const toks = Object.keys(data.identities || {}).filter((t) => t.length <= 80);
    const urls = [...new Set((String(data.text || "").match(URL_RX) || []).map((u) => u.replace(/[.,;:]+$/, "")).filter((u) => u.length > 12 && u.length <= 200))].slice(0, 6);
    const items = [...toks.map((t) => [t, short(t)]), ...urls.map((u) => [u, u.length > 60 ? u.slice(0, 58) + "…" : u])];
    return `<div class="dsec fxins"><h4>${term("fx_trace", "Trace a string")} from this record</h4>
      <div class="chips">${items.map(([v, l]) => `<button type="button" class="chip fxtr" data-q="${esc(v)}" title="Trace ${esc(v)} through every record">${esc(l)}</button>`).join("")}
      <button type="button" class="fxtrsel" title="Select some of the record's text below, then press this">Trace the selected text</button></div>
      <p class="small muted">${items.length ? "Its tokens and URLs, or any text you select in the record below." : "Select any text in the record below to trace it."}</p></div>
      <div class="dsec fxins"><h4>${term("fx_like", "Records like this")}</h4><div class="fxlikebox"><p class="muted small">Looking…</p></div></div>`;
  });
  window.INSPECTOR_BIND.push((host, kind, key) => {
    if (kind !== "record") return;
    host.querySelectorAll(".fxtr").forEach((b) => b.addEventListener("click", () => fxTrace(b.dataset.q)));
    const sel = host.querySelector(".fxtrsel");
    let lastSel = "";
    const grab = () => { const t = String(window.getSelection?.() || "").trim(); if (t) lastSel = t; };
    host.addEventListener("mouseup", grab); host.addEventListener("keyup", grab);
    sel?.addEventListener("mousedown", grab);
    sel?.addEventListener("click", () => {
      const t = (String(window.getSelection?.() || "").trim() || lastSel).slice(0, 300);
      if (!t) { sel.textContent = "Select some text first"; setTimeout(() => { sel.textContent = "Trace the selected text"; }, 1600); return; }
      fxTrace(t);
    });
    const box = host.querySelector(".fxlikebox");
    if (box) likeInto(box, key, false);
  });

  window.FX_SECTIONS.push(
    { id: "trace", title: "Trace anything", group: G, blurb: "Type any string (a token, a URL, a host, a line of code) and see every record that carried it, who held it in which order, and where it went.", render: renderTrace },
    { id: "credentials", title: "Credential lifecycle", group: G, blurb: "Every identity token: first seen as data, first and last use, who used it, which places it opened, who carried it, and how long it has been quiet.", render: renderCred },
    { id: "c2", title: "Command and control", group: G, blurb: "Command files, boards and places several actors read: who wrote, who polled, and what the readers did in the hour after they picked a write up.", render: renderC2 },
    { id: "drops", title: "Dead-drop ledger", group: G, blurb: "Places written by one actor: who picked them up and how long each drop waited, the ones nobody read and the ones many did. Exportable.", render: renderDrops },
    { id: "search", title: "Search", group: G, blurb: "Boolean and regular-expression search over record text with the event filters, saved searches, and records like a given one.", render: renderSearch },
  );
})();

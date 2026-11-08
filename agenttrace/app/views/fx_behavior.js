// Forensics, "How agents behaved": program evolution, stage ladder, lead–lag, anomaly timeline and a
// chronology built from the data alone. Server side: agenttrace/fx_behavior.py (/api/x/fx_*).
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const G = "How agents behaved";
  const HR = 3600e3;
  const PAL = ["#2f6fb3", "#e3a43b", "#0f766e", "#7c4dbd", "#d35400", "#6aa5dc", "#2e9d5b", "#b8579a", "#5d6d7e", "#c9a227", "#8c564b", "#1f9bb4"];

  Object.assign(GLOSSARY, {
    version: ["Program version", "One distinct text of a program once ids, numbers and hashes are masked. Versions whose 4-token pieces overlap by 80% or more (estimated Jaccard similarity) are one cluster: the same program, edited."],
    jaccard: ["Similarity", "The share of 4-token pieces two masked texts have in common (Jaccard similarity), estimated from 128 MinHash bins. 1 means the same pieces; 0.8 is the bar for two versions to be one program."],
    stage: ["Stage", "A step of an attack (reconnaissance, credential access, execution, exfiltration, cover-up…). Each evidence tag has a stage in the pack; intents get one from the pack's intent_stages or, failing that, from their name. An action can be at several stages at once."],
    leadlag: ["Lead–lag", "How two actors' hourly activity lines up when one is shifted by up to 6 hours. If B's rises and falls best match A's from a few hours earlier, A 'leads' B. A timing pattern only: it does not show that A caused or told B anything."],
    anomaly: ["Pattern break", "An hour in which an actor did something unlike its own past: a burst (at least 3× its median busy hour and 10+ actions), its first time at a new place or with a new intent, its first harmful action or its first message."],
    story: ["Chronology", "Sentences generated from counted facts only (no AI), each with the record ids behind it, in time order and grouped by the stretches of the incident."],
  });

  // ------------------------------------------------------------------ shared
  // fetch an endpoint that may answer {pending: true} while the server computes in the background
  async function get(path, host, live) {
    for (let i = 0; i < 120; i++) {
      const r = await api(path);
      if (!r.pending) return r;
      if (host) host.innerHTML = `<p class="muted">${esc(r.message || "Computing…")} <span class="fxbspin"></span></p>`;
      await new Promise((ok) => setTimeout(ok, 1500));
      if (live && !live()) return null;
    }
    throw new Error("the server is still computing; open this section again in a moment");
  }
  const still = (host) => () => host.isConnected;
  const lowFirst = (s) => String(s || "").replace(/^([A-Z])(?![A-Z])/, (c) => c.toLowerCase());
  function whatLine(w) {
    if (!w) return "no description";
    const tags = (w.tags || []).map((t) => lowFirst(t.what));
    const head = w.intent && w.intent !== "other" ? w.intent_what : (tags.length ? tags.shift() : "no known pattern");
    return String(head).replace(/\.$/, "") + (tags.length ? "; " + tags.slice(0, 2).join("; ") : "");
  }
  const stageName = (g) => human(g).replace(/^./, (c) => c.toUpperCase());
  const tOf = (x) => toTime(x);
  const hourOf = (t) => new Date(t).toISOString().slice(0, 13).replace("T", " ");
  function axis(t0, t1, X, y, x0, x1) {
    let s = `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="${AXIS}"/>`;
    timeTicks(t0, t1, Math.max(3, Math.floor((x1 - x0) / 110))).forEach((k) => {
      const x = X(k.t);
      s += `<line x1="${x}" x2="${x}" y1="${y}" y2="${y + 4}" stroke="${AXIS}"/><text x="${x}" y="${y + 15}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`;
    });
    return s;
  }
  const svgName = (a, max, attrs = "") => `<text ${attrs} data-actor="${esc(a)}" class="fxbname" font-size="11.5" fill="#7a4d0c">${esc(fitName(short(a), max, "11.5px -apple-system, system-ui, sans-serif"))}<title>${esc(short(a))}</title></text>`;

  // ================================================================== 1. program evolution
  const EV = { id: null, sel: null, all: false };
  async function evolution(host) {
    const r = await get("/api/x/fx_evolution", host, still(host));
    if (!r || !host.isConnected) return;
    const m = r.method;
    if (!r.clusters.length) {
      host.innerHTML = `<p class="muted">No program has near-duplicate versions: among ${plural(r.versions_total, "distinct masked text")} of ${plural(r.actions, "action")}, no two overlap by ${pct(m.jaccard)} or more. Only actions of at least ${m.min_tokens} tokens are compared.</p>`;
      return;
    }
    if (EV.id == null || !r.clusters.some((c) => c.id === EV.id)) { EV.id = r.clusters[0].id; EV.sel = null; }
    const adoptedC = r.clusters.filter((c) => c.later_versions_adopted).length;
    host.innerHTML = `
      <p class="lead">${plural(r.clusters_total, "program")} ${r.clusters_total === 1 ? "exists" : "exist"} in more than one version: each is a cluster of near-identical ${term("version", "versions")} (${term("jaccard", "similarity")} ≥ ${m.jaccard}). The largest are listed first; ${fmt(adoptedC)} of the first ${fmt(r.clusters.length)} have a later version that another actor went on to run.</p>
      <p class="muted small">Compared: ${plural(r.versions_total, "distinct masked text")} from ${plural(r.actions, "action")} (texts under ${m.min_tokens} tokens are left out; each text is compared on its first ${fmt(m.max_tokens)} tokens). Candidate pairs come from MinHash bands (${m.bands}×${m.rows} of ${m.bins} bins), so a pair below the bar in every band is never compared; in a very common band each text is compared with the ${m.bucket_cap} before it. Each version is linked to its most similar earlier version (the first ${fmt(m.max_parent_scan)} versions of a cluster).</p>
      <div class="card fxbclist"><header><h3>Programs with versions</h3><span class="muted small">largest first · ${fmt(r.clusters.length)} of ${fmt(r.clusters_total)} listed</span></header><div id="fxbCl"></div></div>
      <div id="fxbTree"></div>`;
    $("fxbCl").innerHTML = r.clusters.map((c) => `<button type="button" class="fxbcl${c.id === EV.id ? " on" : ""}" data-c="${c.id}">
      <b>${plural(c.versions_total, "version")}</b> · ${plural(c.actors, "actor")} · ${plural(c.records, "run")}
      <span>${esc(whatLine(c.what))}</span>${c.later_versions_adopted ? `<em>${fmt(c.later_versions_adopted)} later ${c.later_versions_adopted === 1 ? "version" : "versions"} adopted</em>` : ""}</button>`).join("");
    $("fxbCl").querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => { EV.id = +b.dataset.c; EV.sel = null; EV.all = false; evolution(host); }));
    await cluster(EV.id);
  }

  async function cluster(id) {
    const box = $("fxbTree");
    if (!box) return;
    const c = await get(`/api/x/fx_evolution_cluster?id=${id}`, box, () => box.isConnected);
    if (!c || !box.isConnected) return;
    const vs = c.versions, shown = EV.all ? vs : vs.slice(0, 60);
    const intro = new Set(vs.map((v) => v.introduced_by));
    const calls = (c.what?.calls || []).slice(0, 3);
    box.innerHTML = card("Version tree", `<div id="fxbTreeSvg" class="fxbscroll"></div>
      <div class="legend"><span><i style="background:${C.program};border-radius:50%"></i>a later actor ran this version too</span><span><i style="background:#fff;border:1.5px solid ${C.program};border-radius:50%"></i>run only by the actor who introduced it</span><span><i style="background:#fff;border:2px solid ${HARM};border-radius:50%"></i>introduced by an actor other than its parent's</span></div>
      ${vs.length > shown.length ? `<button type="button" id="fxbAll" class="link">Show all ${fmt(vs.length)} versions</button>` : ""}${c.truncated ? `<p class="small muted">The cluster has ${fmt(c.versions_total)} versions; the earliest ${fmt(vs.length)} are listed.</p>` : ""}
      <div id="fxbDiff"></div>`,
      { sub: `What it does: <b>${esc(whatLine(c.what))}</b>${calls.length ? ` · calls ${calls.map((h) => `<code>${esc(h)}</code>`).join(", ")}` : ""}. ${plural(c.versions_total, "version")} by ${plural(intro.size, "introducing actor")}, ${plural(c.records, "run")} in all. Time runs left to right; each line joins a version to the earlier version it is most similar to (versions join a cluster through a chain of ≥ 0.8 matches, so a version's closest earlier one can be a little below 0.8). Click a version to see what changed.` })
      + card("Versions", `<div id="fxbVt"></div>`, { sub: "In order of first appearance. Adopted by: named actors other than its introducer who later ran this exact version." });
    const allBtn = $("fxbAll"); if (allBtn) allBtn.addEventListener("click", () => { EV.all = true; cluster(id); });
    const draw = () => tree($("fxbTreeSvg"), shown, id);
    draw(); onResize($("fxbTreeSvg"), draw);
    $("fxbVt").innerHTML = table(["#", "first run", "introduced by", "record", "runs", "adopted by", "parent", "similarity"], vs.map((v) => [
      `v${v.n}`, esc(v.time || "undated"), ent.actor(v.introduced_by), ent.rec(v.first_record), fmt(v.records),
      v.adopted_by.length ? v.adopted_by.slice(0, 6).map((a) => ent.actor(a)).join(" ") + (v.adopted_by.length > 6 ? ` +${v.adopted_by.length - 6}` : "") : '<span class="muted">–</span>',
      v.parent == null ? '<span class="muted">first</span>' : `v${v.parent}`, v.similarity == null ? "" : v.similarity.toFixed(2)]), (i) => pick(id, vs[i].n));
    bindRows($("fxbVt"), (i) => pick(id, vs[i].n));
    pick(id, EV.sel ?? (vs.find((v) => v.parent != null && v.changed_by_other) || vs[1] || vs[0]).n);
  }

  function tree(host, vs, cid) {
    if (!host) return;
    const W = Math.max(520, host.clientWidth || 700), padL = 34, padR = 150, rowH = 22, top = 10;
    const dated = vs.filter((v) => v.time).map((v) => tOf(v.time));
    const hasUndated = vs.some((v) => !v.time);
    let t0 = dated.length ? Math.min(...dated) : 0, t1 = dated.length ? Math.max(...dated) : 1;
    if (t1 - t0 < HR) { t0 -= HR / 2; t1 += HR / 2; }
    const xEnd = W - padR - (hasUndated ? 60 : 0);
    const X = (v) => (v.time ? padL + ((tOf(v.time) - t0) / (t1 - t0)) * (xEnd - padL) : W - padR - 20);
    // rows: depth-first from each root, children by time, so a branch stays together
    const kids = new Map(); vs.forEach((v) => { if (v.parent != null) { if (!kids.has(v.parent)) kids.set(v.parent, []); kids.get(v.parent).push(v); } });
    const byN = new Map(vs.map((v) => [v.n, v])), row = new Map();
    const walk = (v) => { if (row.has(v.n)) return; row.set(v.n, row.size); (kids.get(v.n) || []).forEach(walk); };
    vs.forEach((v) => { if (v.parent == null || !byN.has(v.parent)) walk(v); });
    vs.forEach(walk);
    const Y = (v) => top + row.get(v.n) * rowH + rowH / 2;
    const H = top + vs.length * rowH + 30;
    let s = `<svg class="fxbsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Version tree">`;
    vs.forEach((v) => { if (row.get(v.n) % 2 === 0) s += `<rect x="0" y="${Y(v) - rowH / 2}" width="${W}" height="${rowH}" fill="#fafbfc"/>`; });
    if (hasUndated) s += `<text x="${W - padR - 20}" y="${H - 8}" text-anchor="middle" font-size="10.5" fill="${QUIET}">undated</text>`;
    vs.forEach((v) => {
      const p = byN.get(v.parent); if (!p) return;
      const x0 = X(p), y0 = Y(p), x1 = X(v), y1 = Y(v), mx = Math.max(x0 + 8, (x0 + x1) / 2);
      s += `<path d="M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1}" fill="none" stroke="#9fb3c8" stroke-width="1.2"/>`;
    });
    vs.forEach((v) => {
      const x = X(v), y = Y(v), on = v.n === EV.sel;
      const fill = v.adopted_by.length ? C.program : "#fff";
      s += `<g class="fxbnode" data-v="${v.n}" style="cursor:pointer"><circle cx="${x}" cy="${y}" r="${on ? 7.5 : 6}" fill="${fill}" stroke="${v.changed_by_other ? HARM : C.program}" stroke-width="${v.changed_by_other || on ? 2.2 : 1.5}"/>${on ? `<circle cx="${x}" cy="${y}" r="10.5" fill="none" stroke="${ACCENT}" stroke-width="1.2"/>` : ""}<title>v${v.n} · ${esc(v.time || "undated")} · introduced by ${esc(short(v.introduced_by))} in ${esc(v.first_record)} · ${plural(v.records, "run")}${v.adopted_by.length ? ` · adopted by ${v.adopted_by.length}` : ""}${v.similarity != null ? ` · similarity to v${v.parent} ${v.similarity}` : ""}</title></g>`;
      s += `<text x="${x - 10}" y="${y + 3.5}" text-anchor="end" font-size="9.5" fill="${QUIET}" pointer-events="none">v${v.n}</text>`;
      s += svgName(v.introduced_by, padR - 30, `x="${x + 11}" y="${y + 4}"`);
      if (v.adopted_by.length) s += `<text x="${x + 13 + Math.min(padR - 30, textWidth(short(v.introduced_by), "11.5px -apple-system, system-ui, sans-serif"))}" y="${y + 4}" font-size="10.5" fill="${C.program}">+${v.adopted_by.length}</text>`;
    });
    if (dated.length) s += axis(t0, t1, (t) => padL + ((t - t0) / (t1 - t0)) * (xEnd - padL), H - 26, padL, xEnd);
    host.innerHTML = s + "</svg>";
    host.querySelectorAll(".fxbnode").forEach((g) => g.addEventListener("click", () => pick(cid, +g.dataset.v)));
  }

  async function pick(cid, n) {
    EV.sel = n;
    document.querySelectorAll("#fxbTreeSvg .fxbnode").forEach((g) => {
      const on = +g.dataset.v === n, c = g.querySelector("circle");
      c.setAttribute("r", on ? 7.5 : 6);
      g.querySelectorAll("circle+circle").forEach((x) => x.remove());
      if (on) g.insertAdjacentHTML("beforeend", `<circle cx="${c.getAttribute("cx")}" cy="${c.getAttribute("cy")}" r="10.5" fill="none" stroke="${ACCENT}" stroke-width="1.2"/>`);
    });
    const box = $("fxbDiff"); if (!box) return;
    box.innerHTML = '<p class="muted small">Loading the diff…</p>';
    const d = await get(`/api/x/fx_evolution_diff?id=${cid}&version=${n}`, box, () => box.isConnected).catch((e) => ({ error: e.message }));
    if (!d || !box.isConnected || EV.sel !== n) return;
    if (d.error) { box.innerHTML = `<p class="warn">${esc(d.error)}</p>`; return; }
    if (d.parent == null) { box.innerHTML = `<div class="fxbdiffh"><b>v${n}</b> is the first version of this program (${ent.rec(d.record || "")}); there is nothing earlier to compare it with.</div>`; return; }
    box.innerHTML = `<div class="fxbdiffh"><b>v${n}</b> (${ent.rec(d.record)}) against its parent <b>v${d.parent}</b> (${ent.rec(d.parent_record)}): ${term("jaccard", "similarity")} ${d.similarity}, <span class="fxbadd">+${fmt(d.added)}</span> / <span class="fxbdel">−${fmt(d.removed)}</span> lines. Ids, numbers and hashes are masked, so only real changes show.</div>
      ${d.diff.length ? `<pre class="fxbdiff">${d.diff.map((l) => `<span class="${l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : l.startsWith("@@") ? "h" : ""}">${esc(l) || " "}</span>`).join("")}</pre>` : '<p class="muted small">The two texts are the same line by line (they differ only in what the masking hides or in spacing).</p>'}
      ${d.truncated ? `<p class="small muted">Showing ${fmt(d.diff.length)} of ${fmt(d.diff_total)} diff lines.</p>` : ""}`;
  }

  // ================================================================== 2. stage ladder
  async function ladder(host) {
    const r = await get("/api/x/fx_stages", host);
    if (!host.isConnected) return;
    if (!r.stages.length) {
      host.innerHTML = `<p class="muted">No action matched a stage: the pack's evidence tags carry stages${r.intent_stages.length ? "" : " and none of its intents has one"}, and none of them fired on an action.</p>${mapping(r)}`;
      return;
    }
    const top = r.actors.slice(0, 12);
    const firstS = r.stages.filter((x) => x.first_time).sort((a, b) => tOf(a.first_time) - tOf(b.first_time))[0];
    const three = r.actors.filter((a) => a.stages >= 3).length;
    host.innerHTML = `
      <p class="lead">The swarm's actions touched ${fmt(r.stages.length)} ${term("stage", r.stages.length === 1 ? "stage" : "stages")}${firstS ? `, starting with <b>${esc(human(firstS.stage))}</b> on ${esc(when(tOf(firstS.first_time)))}` : ""}. ${plural(r.actors_total, "named actor")} reached at least one stage; ${fmt(three)} reached three or more.</p>
      <div class="kpis">
        ${kpi(term("stage", "stages reached"), fmt(r.stages.length), "by any action")}
        ${kpi("named actors on the ladder", fmt(r.actors_total), `${fmt(three)} at 3+ stages`)}
        ${kpi("most stages, one actor", fmt(r.actors[0]?.stages ?? 0), r.actors[0] ? short(r.actors[0].actor) : "")}
      </div>
      ${r.dated ? card("Kill chain over time", `<div id="fxbLad"></div><div id="fxbLadKey" class="legend"></div>`, { sub: `Stages as rows (the usual order of an attack, top to bottom); time left to right. The black diamond is the swarm's first action at each stage (by any actor, anonymous runs included). Thin lines: the ${fmt(top.length)} named actors who reached the most stages, each joining its first arrival at every stage it reached. Hover for details, click a mark to open its record.` }) : '<p class="warn">No action at any stage has a time, so only the counts are shown.</p>'}
      ${card("Each stage", `<div id="fxbLadT"></div>`, { sub: "First: the first dated action at the stage. Named actors: how many distinct named actors had at least one action there. Via: what put actions at the stage (an evidence tag or an intent)." })}
      ${card("Each actor's climb", `<div id="fxbClimb"></div>`, { sub: `The named actors who reached the most stages, with the first record at each. ${r.actors_total > r.actors.length ? `First ${fmt(r.actors.length)} of ${fmt(r.actors_total)}.` : ""}` })}
      ${mapping(r)}`;
    if (r.dated) { const d = () => ladderChart($("fxbLad"), r, top); d(); onResize($("fxbLad"), d); }
    $("fxbLadT").innerHTML = table(["stage", "first", "first named actor", "named actors", "actions", "via"], r.stages.map((x) => [
      `<b class="fxbnw">${esc(stageName(x.stage))}</b>`, `<span class="fxbnw">${esc(x.first_time ? when(tOf(x.first_time)) : "undated")}</span><br>${ent.actor(x.first_actor)} ${ent.rec(x.first_record)}`,
      x.first_named_actor && x.first_named_actor !== x.first_actor ? `${ent.actor(x.first_named_actor)} ${ent.rec(x.first_named_record)}` : '<span class="muted">same</span>',
      fmt(x.actors), fmt(x.records) + (x.undated ? `<span class="muted small"> (${fmt(x.undated)} undated)</span>` : ""),
      `<span class="small">${x.via.map((v) => esc(v.what.replace(/^tag:/, "tag ").replace(/^intent:/, "intent ").replace(/_/g, " ")) + ` <span class="muted">${fmt(v.n)}</span>`).join(", ")}</span>`]));
    const cols = r.stages.map((x) => x.stage);
    $("fxbClimb").innerHTML = `<div class="fxbscroll">${table(["actor", "stages", ...cols.map(stageName)], r.actors.slice(0, 40).map((a) => {
      const at = new Map(a.steps.map((s, i) => [s.stage, { ...s, i }]));
      return [ent.actor(a.actor), fmt(a.stages), ...cols.map((g) => at.has(g) ? `<span class="fxbstep" data-id="${esc(at.get(g).record)}" title="${esc(at.get(g).time)} · ${esc(at.get(g).record)}">${at.get(g).i + 1}</span>` : "")];
    }))}</div><p class="small muted">Numbers: the order in which the actor first reached each stage. Click one to open the record.</p>`;
  }
  function mapping(r) {
    const guessed = r.intent_stages.filter((x) => x.how !== "pack");
    return `<details class="card"><summary><h3>How actions are mapped to stages</h3></summary>
      <p class="small">Evidence tags carry their stage in the pack: ${r.tag_stages.map((x) => `<span class="chip">${esc(human(x.tag))} → ${esc(human(x.stage))}</span>`).join(" ") || "none"}.</p>
      <p class="small">Intents: ${r.intent_stages.length ? r.intent_stages.map((x) => `<span class="chip">${esc(human(x.intent))} → ${esc(human(x.stage))}</span> <span class="muted">(${esc(x.how)})</span>`).join(" ") : "none has a stage"}. ${guessed.length ? "Add an <code>intent_stages</code> object to the pack to set these yourself." : ""} Intents not listed have no stage.</p></details>`;
  }
  function ladderChart(host, r, top) {
    if (!host) return;
    const rows = r.stages, W = Math.max(520, host.clientWidth || 700), padL = 150, padR = 24, rowH = 34, top0 = 12;
    const H = top0 + rows.length * rowH + 30;
    const pts = [];
    rows.forEach((x) => { if (x.first_time) pts.push(tOf(x.first_time)); });
    top.forEach((a) => a.steps.forEach((s) => pts.push(tOf(s.time))));
    let t0 = Math.min(...pts), t1 = Math.max(...pts);
    if (t1 - t0 < HR) { t0 -= HR; t1 += HR; }
    const X = (t) => padL + ((t - t0) / (t1 - t0)) * (W - padL - padR);
    const idx = new Map(rows.map((x, i) => [x.stage, i]));
    const Y = (g) => top0 + idx.get(g) * rowH + rowH / 2;
    let s = `<svg class="fxbsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Stage ladder">`;
    rows.forEach((x, i) => {
      s += `<line x1="${padL}" x2="${W - padR}" y1="${Y(x.stage)}" y2="${Y(x.stage)}" stroke="${GRID}"/>`;
      s += `<text x="${padL - 10}" y="${Y(x.stage) + 4}" text-anchor="end" font-size="12" fill="${INK}">${esc(fitName(stageName(x.stage), padL - 18, "12px -apple-system, system-ui, sans-serif"))}</text><text x="${padL - 10}" y="${Y(x.stage) + 15}" text-anchor="end" font-size="9.5" fill="${QUIET}">${fmt(x.actors)} actors</text>`;
    });
    top.forEach((a, k) => {
      const c = PAL[k % PAL.length];
      const p = a.steps.map((st) => [X(tOf(st.time)), Y(st.stage), st]);
      if (p.length > 1) s += `<path d="${p.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("")}" fill="none" stroke="${c}" stroke-width="1.3" stroke-opacity=".75"/>`;
      p.forEach(([x, y, st]) => { s += `<circle cx="${x}" cy="${y}" r="3.2" fill="${c}" data-id="${esc(st.record)}" style="cursor:pointer"><title>${esc(short(a.actor))} first at ${esc(human(st.stage))}: ${esc(st.time)} (${esc(st.record)})</title></circle>`; });
    });
    rows.forEach((x) => {
      if (!x.first_time) return;
      const cx = X(tOf(x.first_time)), cy = Y(x.stage);
      s += `<path d="M${cx},${cy - 7}L${cx + 7},${cy}L${cx},${cy + 7}L${cx - 7},${cy}Z" fill="${INK}" stroke="#fff" stroke-width="1.5" data-id="${esc(x.first_record)}" style="cursor:pointer"><title>The swarm first at ${esc(human(x.stage))}: ${esc(x.first_time)}, ${esc(short(x.first_actor))} in ${esc(x.first_record)}</title></path>`;
    });
    s += axis(t0, t1, X, H - 24, padL, W - padR);
    host.innerHTML = s + "</svg>";
    $("fxbLadKey").innerHTML = `<span><i style="background:${INK};transform:rotate(45deg)"></i>swarm's first arrival</span>` + top.map((a, k) => `<span><i style="background:${PAL[k % PAL.length]};border-radius:50%"></i>${ent.actor(a.actor)} <b>${a.stages}</b></span>`).join("");
  }

  // ================================================================== 3. lead–lag
  async function leadlag(host) {
    const r = await get("/api/x/fx_leadlag", host);
    if (!host.isConnected) return;
    const flagged = r.pairs.filter((p) => p.flag);
    host.innerHTML = `
      <p class="warn"><b>Correlation, not causation.</b> A "leader" here only moved first: its busy and quiet hours line up with the other actor's a few hours later. Both may answer a third cause (a shared schedule, the same instructions, the same time estimate); the data does not show that one told the other anything. Messages and shared programs, elsewhere in the app, are the direct evidence.</p>
      <p class="lead">${r.pairs.length ? `Of ${plural(r.pairs_considered, "pair")} among the ${fmt(r.actors_considered)} most active named actors, ${plural(r.pairs.length, "pair")} ${r.pairs.length === 1 ? "was" : "were"} active in the same hour at least ${r.min_overlap} times and could be tested; in ${plural(flagged.length, "pair")} one actor's activity reliably came 1–${r.lags - 1} hours before the other's.` : `No pair of the ${fmt(r.actors_considered)} most active named actors was active in the same hour ${r.min_overlap} or more times, so no timing pattern can be tested.`}</p>
      <p class="muted small">Method: per actor, dated actions per hour (as log(1 + n), then the change from the hour before, so a shared trend does not count). For each pair, the correlation of A's series with B's shifted by −${r.lags}…+${r.lags} hours, over the hours both were active plus ${r.lags} on each side. A pair is flagged when the best shift is not zero and not at the edge of the range, its correlation is at least 0.3 and above 2/√hours (what noise alone reaches about one time in twenty), and at least 0.1 above the same-hour correlation. ${fmt(r.named_with_dated_actions)} named actors had dated actions; only the top ${fmt(r.actors_considered)} by dated actions are paired.</p>
      ${r.pairs.length ? `<div>
        ${card("Who moves first", flagged.length ? `<div id="fxbLL"></div>` : '<p class="muted">No pair passed the bar.</p>', { sub: "Leader → follower, by correlation. The small chart is the correlation at each shift (−6 … +6 h, the follower's hours after the leader's to the right); the dark bar is the best shift." })}
        ${card("Leaders and followers", rolesHtml(r), { sub: "How often each actor came first or second in a flagged pair. Leader: leads at least twice as often as it follows." })}
      </div>
      ${card("Timing map", `<div id="fxbHeat" class="fxbscroll"></div>`, { sub: "Row actor against column actor, for the actors in tested pairs. Blue: the row actor moves first (darker: stronger correlation); orange: the column actor does; grey dot: tested, no lead; blank: not tested. Hover a cell for the numbers." })}
      <details class="card"><summary><h3>Every tested pair (${fmt(r.pairs.length)})</h3></summary><div id="fxbLLAll"></div></details>` : ""}`;
    if (flagged.length) $("fxbLL").innerHTML = table(["leader → follower", "by", "correlation", "same hour", "hours together", "shifts"], flagged.slice(0, 40).map((p) => [
      `<span class="fxbnw">${ent.actor(p.leader)} → ${ent.actor(p.follower)}</span>`, `<span class="fxbnw">${p.lag_hours} h</span>`, p.r.toFixed(2), p.r0 == null ? "–" : p.r0.toFixed(2), `${fmt(p.overlap_hours)} <span class="muted small">of ${fmt(p.window_hours)}</span>`, curve(p)]));
    if (r.pairs.length) {
      heat($("fxbHeat"), r);
      $("fxbLLAll").innerHTML = table(["A", "B", "best shift", "correlation", "same hour", "noise level", "hours together", "flag"], r.pairs.map((p) => [
        ent.actor(p.a), ent.actor(p.b), p.best_lag === 0 ? "0" : p.best_lag > 0 ? `B ${p.best_lag} h after A` : `A ${-p.best_lag} h after B`, p.r.toFixed(2), p.r0 == null ? "–" : p.r0.toFixed(2), p.noise.toFixed(2), fmt(p.overlap_hours), p.flag ? "leads" : ""]));
    }
  }
  // the follower-oriented correlation curve: shifts where the follower comes later are on the right
  function curve(p) {
    const c = p.leader === p.a ? p.curve : p.curve.slice().reverse();
    const w = 6, h = 26, mid = h / 2, best = 6 + p.lag_hours;
    return `<svg width="${c.length * w}" height="${h}" class="fxbcurve"><line x1="0" x2="${c.length * w}" y1="${mid}" y2="${mid}" stroke="${GRID}"/>${c.map((v, i) => `<rect x="${i * w + 0.5}" width="${w - 1}" y="${v >= 0 ? mid - v * mid : mid}" height="${Math.abs(v) * mid}" fill="${i === best ? ACCENT : "#bccbdc"}"><title>${i - 6 >= 0 ? "+" : ""}${i - 6} h: ${v.toFixed(2)}</title></rect>`).join("")}<line x1="${6 * w + w / 2}" x2="${6 * w + w / 2}" y1="0" y2="${h}" stroke="${AXIS}" stroke-dasharray="2 2"/></svg>`;
  }
  function rolesHtml(r) {
    if (!r.roles.length) return '<p class="muted">No actor led or followed in a flagged pair.</p>';
    const mx = Math.max(...r.roles.map((x) => Math.max(x.leads, x.follows)), 1);
    return `<div class="fxbroles">${r.roles.slice(0, 24).map((x) => `<div>${ent.actor(x.actor)}<span class="fxbbar"><i class="l" style="width:${(50 * x.leads / mx).toFixed(1)}%"></i><i class="f" style="width:${(50 * x.follows / mx).toFixed(1)}%"></i></span><span class="small">${x.leads} lead${x.leads === 1 ? "" : "s"} · ${x.follows} follow${x.follows === 1 ? "" : "s"} <b class="fxbrole ${x.role}">${x.role}</b></span></div>`).join("")}</div>
      <div class="legend"><span><i style="background:${ACCENT}"></i>leads</span><span><i style="background:#e3a43b"></i>follows</span></div>`;
  }
  function heat(host, r) {
    if (!host) return;
    const inPairs = new Set(); r.pairs.forEach((p) => { inPairs.add(p.a); inPairs.add(p.b); });
    const score = new Map(); r.pairs.forEach((p) => { if (p.flag) { score.set(p.a, (score.get(p.a) || 0) + 1); score.set(p.b, (score.get(p.b) || 0) + 1); } });
    const actors = [...inPairs].sort((a, b) => (score.get(b) || 0) - (score.get(a) || 0)).slice(0, 24);
    const cell = 18, padL = 130, padT = 110, n = actors.length;
    const W = padL + n * cell + 10, H = padT + n * cell + 10;
    const at = new Map(actors.map((a, i) => [a, i]));
    let s = `<svg class="fxbsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Lead–lag timing map">`;
    actors.forEach((a, i) => {
      s += svgName(a, padL - 12, `x="${padL - 6}" y="${padT + i * cell + cell / 2 + 4}" text-anchor="end"`);
      s += `<g transform="translate(${padL + i * cell + cell / 2 + 4},${padT - 6}) rotate(-55)">${svgName(a, padT - 10, `x="0" y="0"`)}</g>`;
    });
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) s += `<rect x="${padL + j * cell}" y="${padT + i * cell}" width="${cell - 1}" height="${cell - 1}" fill="${i === j ? "#eef0f3" : "#fafbfc"}"/>`;
    r.pairs.forEach((p) => {
      if (!at.has(p.a) || !at.has(p.b)) return;
      [[p.a, p.b], [p.b, p.a]].forEach(([row, col]) => {
        const x = padL + at.get(col) * cell, y = padT + at.get(row) * cell;
        const tip = `${short(row)} vs ${short(col)}: ${p.flag ? `${short(p.leader)} leads by ${p.lag_hours} h, r = ${p.r.toFixed(2)}` : `no lead (best shift ${p.best_lag} h, r = ${p.r.toFixed(2)})`}; ${p.overlap_hours} hours together`;
        if (!p.flag) { s += `<circle cx="${x + cell / 2 - 0.5}" cy="${y + cell / 2 - 0.5}" r="2.2" fill="#c3cad2"><title>${esc(tip)}</title></circle>`; return; }
        const lead = p.leader === row;
        const op = Math.max(0.25, Math.min(1, (p.r - 0.2) / 0.6));
        s += `<rect x="${x}" y="${y}" width="${cell - 1}" height="${cell - 1}" fill="${lead ? ACCENT : "#e3a43b"}" opacity="${op.toFixed(2)}"><title>${esc(tip)}</title></rect><text x="${x + cell / 2 - 0.5}" y="${y + cell / 2 + 3}" text-anchor="middle" font-size="9" fill="#fff" pointer-events="none">${p.lag_hours}</text>`;
      });
    });
    host.innerHTML = s + "</svg>";
  }

  // ================================================================== 4. anomaly timeline
  const KINDS = {
    burst: { label: "burst", color: INK, shape: "tri" },
    place: { label: "first time at a new place", color: C.place, shape: "sq" },
    intent: { label: "first time with a new intent", color: ACCENT, shape: "dot" },
    harm: { label: "first harmful action", color: HARM, shape: "dia" },
    message: { label: "first message", color: "#0f766e", shape: "ring" },
  };
  const AN = { only: "" };
  function shape(k, x, y, r = 4.5) {
    const c = KINDS[k].color;
    switch (KINDS[k].shape) {
      case "tri": return `<path d="M${x},${y - r - 1}L${x + r + 1},${y + r}L${x - r - 1},${y + r}Z" fill="${c}"/>`;
      case "sq": return `<rect x="${x - r + 0.5}" y="${y - r + 0.5}" width="${2 * r - 1}" height="${2 * r - 1}" fill="${c}"/>`;
      case "dia": return `<path d="M${x},${y - r - 1.5}L${x + r + 1.5},${y}L${x},${y + r + 1.5}L${x - r - 1.5},${y}Z" fill="${c}"/>`;
      case "ring": return `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${c}" stroke-width="2"/>`;
      default: return `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}"/>`;
    }
  }
  function markText(m) {
    return m.kinds.map((k) => k.kind === "burst" ? `burst: ${fmt(k.n)} actions (${k.times_median}× its median busy hour)`
      : k.kind === "place" ? `${plural(k.n, "new place")}: ${k.places.map(placeLabel).join(", ")}${k.n > k.places.length ? "…" : ""}`
      : k.kind === "intent" ? `new intent: ${k.intents.map(human).join(", ")}`
      : k.kind === "harm" ? `first harmful action${k.intent ? ` (${human(k.intent)})` : ""} in ${k.record}`
      : `first message ${k.role === "sent" ? "to" : "from"} ${short(k.other)} in ${k.record}`).join("\n");
  }
  async function anomalies(host) {
    const r = await get("/api/x/fx_anomalies", host);
    if (!host.isConnected) return;
    if (!r.actors.length) { host.innerHTML = '<p class="muted">No named actor has a dated action, so there is no pattern to break.</p>'; return; }
    const cnt = r.counts || {};
    host.innerHTML = `
      <p class="lead">For the ${fmt(r.actors.length)} named actors with the most dated actions${r.actors_total > r.actors.length ? ` (of ${fmt(r.actors_total)})` : ""}, the hours in which each one ${term("anomaly", "broke its own pattern")}. Read down a column to see several agents change at once; read along a row to see when one agent changed.</p>
      <div class="kpis">${Object.entries(KINDS).map(([k, v]) => kpi(v.label, fmt(cnt[k] || 0), k === "burst" ? "≥3× its median busy hour and ≥10 actions" : k === "place" || k === "intent" ? "after the actor's first active hour" : "one per actor at most")).join("")}</div>
      ${card("Pattern breaks per actor", `<div class="fxbfilter small">${["", ...Object.keys(KINDS)].map((k) => `<button type="button" data-k="${k}" class="${AN.only === k ? "on" : ""}">${k ? esc(KINDS[k].label) : "all marks"}</button>`).join(" ")}</div><div id="fxbAn"></div>
        <div class="legend">${Object.entries(KINDS).map(([k, v]) => `<span><svg width="12" height="12">${shape(k, 6, 6, 4)}</svg>${esc(v.label)}</span>`).join("")}<span><i style="background:#cfd6de"></i>actions per hour (scaled per actor)</span></div>`,
        { sub: `One strip per actor, ordered by first activity. New places and intents in an actor's first active hour are its starting point and not marked. Click a mark to list that actor's events in that hour; click a name to inspect the actor.` })}`;
    host.querySelectorAll(".fxbfilter [data-k]").forEach((b) => b.addEventListener("click", () => { AN.only = b.dataset.k; anomalies(host); }));
    const d = () => strips($("fxbAn"), r); d(); onResize($("fxbAn"), d);
  }
  function strips(host, r) {
    if (!host) return;
    const rows = r.actors.slice().sort((a, b) => tOf(a.first) - tOf(b.first));
    const W = Math.max(560, host.clientWidth || 800), padL = 140, padR = 16, rowH = 24, top = 6;
    const t0 = tOf(r.start), t1 = tOf(r.end) + HR;
    const X = (t) => padL + ((t - t0) / Math.max(HR, t1 - t0)) * (W - padL - padR);
    const bw = Math.max(1, (W - padL - padR) / Math.max(1, (t1 - t0) / HR));
    const H = top + rows.length * rowH + 28;
    let s = `<svg class="fxbsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Pattern breaks per actor">`;
    rows.forEach((a, i) => {
      const y = top + i * rowH, base = y + rowH - 4;
      if (i % 2 === 0) s += `<rect x="0" y="${y}" width="${W}" height="${rowH}" fill="#fafbfc"/>`;
      s += svgName(a.actor, padL - 14, `x="${padL - 8}" y="${y + rowH / 2 + 4}" text-anchor="end"`);
      const mx = Math.max(1, ...a.hourly.map((h) => h[1]));
      a.hourly.forEach(([h, n]) => { const x = X(tOf(h)), hh = (n / mx) * (rowH - 8); s += `<rect x="${x.toFixed(1)}" y="${(base - hh).toFixed(1)}" width="${bw.toFixed(2)}" height="${hh.toFixed(1)}" fill="#cfd6de"/>`; });
      a.marks.forEach((m) => {
        const ks = m.kinds.filter((k) => !AN.only || k.kind === AN.only);
        if (!ks.length) return;
        const x = X(tOf(m.hour)) + bw / 2;
        const order = ["harm", "message", "burst", "intent", "place"];
        const k = order.find((o) => ks.some((q) => q.kind === o));
        s += `<g class="fxbmark" data-actor-hour="${esc(m.hour)}" data-a="${esc(a.actor)}" style="cursor:pointer">${shape(k, x, y + rowH / 2, k === "place" ? 3.2 : 4.5)}<title>${esc(short(a.actor))} · ${esc(m.hour)}:00 UTC\n${esc(markText({ kinds: ks }))}\nClick to list the events</title></g>`;
      });
    });
    s += axis(t0, t1, X, H - 22, padL, W - padR);
    host.innerHTML = s + "</svg>";
    host.querySelectorAll(".fxbmark").forEach((g) => g.addEventListener("click", () => goEvents({ actor: g.dataset.a, hour: g.dataset.actorHour })));
  }

  // ================================================================== 5. chronology (no AI)
  const partHtml = (p) => typeof p === "string" ? esc(p) : !p ? "" : p.actor ? ent.actor(p.actor) : p.rec ? ent.rec(p.rec) : p.place ? ent.place(p.place) : p.intent ? ent.intent(p.intent) : "";
  const KIND_DOT = { harm: HARM, message: ACCENT, group: ACCENT, token: ACCENT, carried: ACCENT, program: C.program, stage: INK, peak: BASE, surge: BASE, drop: BASE, burst: INK, first: BASE, last: BASE };
  const sentence = (x) => `<li><span class="fxbt">${esc(x.time ? when(tOf(x.time)) : "")}</span><i style="background:${KIND_DOT[x.kind] || BASE}"></i><span>${x.parts.map(partHtml).join("")}</span></li>`;
  async function story(host) {
    const r = await get("/api/x/fx_story", host);
    if (!host.isConnected) return;
    host.innerHTML = `
      <div class="fxbbar2"><button type="button" id="fxbMd" class="primary">Download Markdown</button> <button type="button" id="fxbCopy">Copy Markdown</button> <span class="muted small">${plural(r.sentences, "sentence")}, each from counted facts with the records behind it. Also at <code>/api/x/fx_story</code> (add <code>?format=md</code> for Markdown).</span></div>
      <div class="card fxbstory">
        <p>${r.opening.map(esc).join(" ")}</p>
        ${r.paragraphs.length ? r.paragraphs.map((p) => `<h4>${esc(p.name)}${p.what ? ` <span class="muted">${esc(p.what)}${p.since ? `, from ${esc(when(tOf(p.since)))}` : ""}</span>` : ""}</h4><ul>${p.sentences.map(sentence).join("")}</ul>`).join("") : '<p class="muted">No dated moment to tell: the trace has no dated actions, harmful actions, messages or stage firsts.</p>'}
      </div>
      ${r.actors.length ? `<h3 class="ovh">The most active actors</h3>${r.actors.map((a) => `<details class="card fxbstory"><summary><h3>${ent.actor(a.actor)} <span class="muted small">${plural(a.actions, "action")}</span></h3></summary><ul>${a.sentences.map(sentence).join("")}</ul></details>`).join("")}` : ""}`;
    $("fxbMd").addEventListener("click", () => {
      const blob = new Blob([r.markdown], { type: "text/markdown" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
      a.download = `chronology-${String(r.name || "dataset").replace(/[^\w.-]+/g, "_")}.md`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
    $("fxbCopy").addEventListener("click", async (e) => {
      try { await navigator.clipboard.writeText(r.markdown); e.target.textContent = "Copied"; } catch { e.target.textContent = "Copy failed"; }
      setTimeout(() => { if (e.target.isConnected) e.target.textContent = "Copy Markdown"; }, 1500);
    });
  }

  window.FX_SECTIONS.push(
    { id: "evolution", title: "Program evolution", group: G, blurb: `Near-identical programs grouped into one, with every version in time order: who changed the code, what changed, and whether others ran the new version. Answers “who improved the attack, and did others adopt it?”`, render: evolution },
    { id: "stages", title: "Stage ladder", group: G, blurb: `Each action placed on the steps of an attack (${term("stage", "stages")}), the swarm's first arrival at each, and how the most active actors climbed: the forensic “kill chain”.`, render: ladder },
    { id: "leadlag", title: "Lead–lag", group: G, blurb: `Who moves first: ${term("leadlag", "hourly activity of two actors compared with a shift")}, to find leaders and followers without relying on messages. A timing pattern, not proof of influence.`, render: leadlag },
    { id: "anomalies", title: "Anomaly timeline", group: G, blurb: `One strip per actor marking the hours that ${term("anomaly", "break its own pattern")}: when did this agent change?`, render: anomalies },
    { id: "story", title: "What happened", group: G, blurb: `A ${term("story", "chronology")} written from the data alone, no AI: the incident's stretches and each top actor, sentence by sentence with record ids. Exportable as Markdown.`, render: story },
  );
})();

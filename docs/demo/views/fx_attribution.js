// Forensics, "Who are the anonymous runs?": anonymous runs linked to named actors and to each other by
// shared rare material, with measured precision per confidence band. Server: agenttrace/attribution.py.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const BAND = { named: "#5d6d7e", high: "#0f766e", medium: "#4f9bd9", low: "#e3a43b", unattributed: "#dfe3e8" };
  const BAND_WORD = { named: "named in the trace", high: "high", medium: "medium", low: "low", unattributed: "unattributed" };
  const PAL = ["#2f6fb3", "#7c4dbd", "#d35400", "#2e9d5b", "#b8579a", "#1f9bb4", "#8c564b", "#c9a227", "#6aa5dc", "#5d6d7e"];
  const GREY = "#c3cad2";
  Object.assign(GLOSSARY, {
    anon_run: ["Anonymous run", "A thread whose actions carry no identity token. The app can only call it by its first record: run:<record id>."],
    direct_item: ["Direct item", "A rare feature (a redacted value, string constant, identifier or self-chosen name) that exactly one named actor uses and that at most 50 runs carry in all. Features found in exactly the same threads of that actor count as one item, because a copied program shares dozens of strings at once."],
    attr_band: ["Confidence band", "High: three or more independent direct items and none pointing at another actor. Medium: two. Low: one direct item seen in two or more of the actor's threads, items pointing at two actors, or membership of a cluster whose linked runs agree. One rare feature seen once, or circumstantial evidence alone, makes no link."],
    holdout: ["Holdout test", "The identity token of a random half of the named threads is hidden; those threads are then attributed exactly like anonymous runs, and each link is checked against the hidden token."],
    second_pass: ["Second pass: place and time", "Runs the first pass left unlinked are checked for two more kinds of evidence: a place (a dataset or folder) that only one named actor touches, and named records within ten minutes that share the run's program opening, host and code style or exact program. Weights are learned by logistic regression on halves hidden with other seeds than the test halves; each band's cut-off is the point where those halves are at least as precise as the first pass was in that band."],
    tmpl_family: ["Template family", "Actions whose text is identical once ids, numbers and hex are masked. It says the same program ran many times, not that one agent ran it: many agents can run one program. Families are split into sub-clusters only by shared rare constants, with no chaining."],
    attr_cluster: ["Cluster", "Anonymous runs joined by strong links only: two runs that share at least four rare exact features, each carried by at most four anonymous runs. Joined transitively."],
  });
  const p1 = (x) => x == null ? "–" : (100 * x).toFixed(x >= 0.995 || x < 0.1 ? 1 : 0) + "%";
  const mark = (snip, tok) => {
    let h = esc(snip || "");
    const t = esc(tok || "");
    if (t && t.length >= 3) h = h.split(t).join(`<mark>${t}</mark>`);
    return h;
  };

  // one stacked horizontal bar: parts = [{key, n}]
  function stack(parts, total, label) {
    const segs = parts.filter((p) => p.n > 0).map((p) => {
      const w = 100 * p.n / total;
      return `<i class="fxa-seg" style="width:${w.toFixed(3)}%;background:${BAND[p.key]}" title="${esc(BAND_WORD[p.key])}: ${fmt(p.n)} (${p1(p.n / total)})">${w > 6 ? `<b>${p1(p.n / total)}</b>` : ""}</i>`;
    }).join("");
    return `<div class="fxa-row"><span class="fxa-lab">${label}</span><span class="fxa-bar">${segs}</span></div>`;
  }
  const legend = (keys) => `<div class="legend">${keys.map((k) => `<span><i style="background:${BAND[k]}"></i>${esc(BAND_WORD[k])}</span>`).join("")}</div>`;

  function beforeAfter(r) {
    const bb = r.bands_before, sp = r.second_pass_links;
    const att = (b) => b.high + b.medium + b.low;
    const nowRuns = r.bands.high.runs + r.bands.medium.runs + r.bands.low.runs;
    const rows = ["high", "medium", "low"].map((k) => [bandBadge(k), fmt(bb[k]), `<b>${fmt(r.bands[k].runs)}</b>`, sp[k] ? `+${fmt(sp[k])}` : "0", `${p1(bb[k] / r.runs)} → ${p1(r.bands[k].runs / r.runs)}`]);
    rows.push(["<b>linked</b>", fmt(att(bb)), `<b>${fmt(nowRuns)}</b>`, `+${fmt(nowRuns - att(bb))}`, `${p1(att(bb) / r.runs)} → <b>${p1(nowRuns / r.runs)}</b>`]);
    rows.push(["unattributed", fmt(bb.unattributed), fmt(r.bands.unattributed.runs), fmt(r.bands.unattributed.runs - bb.unattributed), `${p1(bb.unattributed / r.runs)} → ${p1(r.bands.unattributed.runs / r.runs)}`]);
    return `<h4 class="fxa-h">Anonymous runs by band, before and after the ${term("second_pass", "second pass")}</h4>${table(["band", "before", "after", "added", "share of runs"], rows)}`;
  }

  function coverage(r) {
    const b = r.bands, ks = ["high", "medium", "low", "unattributed"];
    const att = b.high.runs + b.medium.runs + b.low.runs;
    const after = (r.named_actions + b.high.actions + b.medium.actions + b.low.actions) / r.actions_total;
    const solid = (r.named_actions + b.high.actions + b.medium.actions) / r.actions_total;
    return card("How much can be attributed",
      `<div class="fxa-big"><div><b>${p1(r.known_share_before)}</b><span>of actions have a known actor today</span></div><div class="fxa-arrow">→</div>
        <div><b>${p1(solid)}</b><span>with high and medium links</span></div><div class="fxa-arrow">→</div>
        <div><b>${p1(after)}</b><span>counting low links too</span></div></div>
      <h4 class="fxa-h">Anonymous runs</h4>
      ${stack(ks.map((k) => ({ key: k, n: b[k].runs })), r.runs, `${fmt(r.runs)} runs`)}
      ${stack(ks.map((k) => ({ key: k, n: b[k].actions })), r.actions, `${fmt(r.actions)} actions`)}
      ${beforeAfter(r)}
      <h4 class="fxa-h">All actions, before and after</h4>
      ${stack([{ key: "named", n: r.named_actions }, { key: "unattributed", n: r.actions_total - r.named_actions }], r.actions_total, "before")}
      ${stack([{ key: "named", n: r.named_actions }, ...ks.map((k) => ({ key: k, n: b[k].actions }))], r.actions_total, "after")}
      ${legend(["named", "high", "medium", "low", "unattributed"])}`,
      { sub: `${fmt(att)} of ${fmt(r.runs)} ${term("anon_run", "anonymous runs")} (${p1(att / r.runs)}) are linked to one of ${fmt(r.actors_total)} named actors; <b>${fmt(b.unattributed.runs)} (${p1(b.unattributed.runs / r.runs)}) stay unattributed</b>. Not linked on purpose: ${fmt(r.single_coincidence_runs)} runs with a single rare feature seen once, ${fmt(r.circumstantial_only_runs)} with circumstantial evidence only.` });
  }

  function bubbles(r) {
    const cl = r.bubbles;
    if (!cl.length) return card("Clusters of anonymous runs", `<p class="muted">No two anonymous runs share enough rare material to be joined.</p>`);
    const actors = [...new Set(cl.map((c) => c.actor).filter(Boolean))];
    const col = (a) => a ? PAL[actors.indexOf(a) % PAL.length] : GREY;
    const W = 1040, pad = 5, R = (n) => 5 + 7 * Math.sqrt(n);
    let x = pad, y = pad, rowH = 0, s = "";
    cl.forEach((c) => {
      const rad = R(c.runs);
      if (x + 2 * rad > W - pad) { x = pad; y += rowH + pad; rowH = 0; }
      rowH = Math.max(rowH, 2 * rad);
      const cy = y + rad;
      s += `<g class="fxa-bub" data-run="${esc(c.member)}" data-c="${c.id}"><circle cx="${(x + rad).toFixed(1)}" cy="${cy.toFixed(1)}" r="${rad.toFixed(1)}" fill="${col(c.actor)}" fill-opacity="${c.actor ? 0.85 : 0.75}" stroke="#fff"/>${rad > 13 ? `<text x="${(x + rad).toFixed(1)}" y="${(cy + 4).toFixed(1)}" text-anchor="middle" font-size="11" fill="${c.actor ? "#fff" : "#39424d"}">${c.runs}</text>` : ""}<title>Cluster ${c.id}: ${c.runs} runs${c.actor ? `, linked to ${short(c.actor)} (${c.linked_runs} of its runs carry direct evidence)` : ", anonymous only"}${c.first ? ` · ${c.first} – ${c.last}` : ""}</title></g>`;
      x += 2 * rad + pad;
    });
    const H = y + rowH + pad;
    return card(`${term("attr_cluster", "Clusters")} of anonymous runs`,
      `<svg class="fxa-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Clusters of anonymous runs, sized by runs">${s}</svg>
       <div class="legend">${actors.slice(0, 10).map((a) => `<span><i style="background:${col(a)};border-radius:50%"></i>${esc(short(a))}</span>`).join("")}<span><i style="background:${GREY};border-radius:50%"></i>anonymous only: a probable agent with no name</span></div>`,
      { sub: `${fmt(r.clusters_total)} clusters hold ${fmt(r.clustered_runs)} runs; ${fmt(r.clusters_named)} are linked to a named actor${r.bubbles.length < r.clusters_total ? `; the ${fmt(r.bubbles.length)} largest are drawn` : ""}. Area grows with the number of runs. Hover for details, click to open one of its runs.` });
  }

  function kindsCard(r) {
    const items = r.evidence_kinds.map((k) => ({ label: esc(k.label) + (k.direct_runs ? "" : k.second_pass ? ` <span class="muted">(second pass)</span>` : ` <span class="muted">(never direct)</span>`), value: k.runs, color: k.direct_runs ? BAND.high : k.second_pass ? BAND.medium : "#9aa5b1",
      title: `${k.label}: in the evidence of ${k.runs} linked runs; a direct item for ${k.direct_runs}` }));
    return card("What the links rest on", hbars(items, { unit: " runs" }),
      { sub: `Linked runs whose evidence includes each kind (a run can have several). Green kinds can be ${term("direct_item", "direct items")}; grey ones only add points. ${fmt(r.credential_carriers)} anonymous runs carry a named actor's credential placeholder outside an auth header: that is not used as a direct item, because held-out threads that carried another actor's key were almost never that actor.` });
  }

  function actorsCard(r) {
    const mx = Math.max(1, ...r.actors.map((a) => a.runs));
    const rows = r.actors.slice(0, 14).map((a) => [ent.actor(a.actor),
      `<span class="fxa-mini" style="width:${Math.max(4, 110 * a.runs / mx)}px">${["high", "medium", "low"].map((k) => a[k] ? `<i style="flex:${a[k]};background:${BAND[k]}" title="${k}: ${a[k]}"></i>` : "").join("")}</span>`,
      fmt(a.high), fmt(a.medium), fmt(a.low), `<b>${fmt(a.runs)}</b>`]);
    return card("Runs attributed to each named actor", table(["named actor", "", "high", "medium", "low", "runs"], rows),
      { sub: `${fmt(r.actors_total)} of ${fmt(r.named_actors)} named actors gain runs${r.actors_total > rows.length ? `; the ${rows.length} with most are listed` : ""}. A named actor is a token: one agent can hold several.` });
  }

  function clustersCard(r) {
    const rows = r.clusters.slice(0, 12).map((c) => [`<span class="nowrap">#${c.id}</span>`, `<b>${fmt(c.runs)}</b>`, c.actor ? ent.actor(c.actor) + ` <span class="muted small">${c.linked_runs} of ${c.runs} runs</span>` : '<span class="muted">anonymous only</span>',
      esc(c.style || ""), (c.evidence || []).slice(0, 3).map((e) => `<code class="fxa-tok" title="${esc(e.label)}: in ${e.runs} runs">${esc(e.token.slice(0, 34))}</code>`).join(" ") || '<span class="muted">features shared pair by pair</span>',
      c.first ? esc(c.first) : '<span class="muted">undated</span>', (c.members || []).slice(0, 3).map((m) => ent.rec(m.slice(4))).join(" ") + (c.runs > 3 ? ` <span class="muted">+${c.runs - 3}</span>` : "")]);
    return card("The 12 largest clusters", `<div id="fxaCl">${table(["", "runs", "linked to", "style", "shared rare material", "first seen", "runs (records)"], rows, () => {})}</div>`,
      { sub: "Click a row to see why one of its runs belongs there." });
  }

  const bandBadge = (b) => b ? `<span class="fxa-badge" style="background:${BAND[b]};color:${b === "low" ? "#3b2a05" : "#fff"}">${esc(b)}</span>` : `<span class="fxa-badge" style="background:${BAND.unattributed};color:#39424d">unattributed</span>`;

  async function detail(id, scroll = true) {
    const box = $("fxaDetail");
    if (!box) return;
    box.innerHTML = `<p class="muted">Loading ${esc(short(id))}…</p>`;
    let d;
    try { d = await api("/api/x/attribution_run?id=" + encodeURIComponent(id)); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (!box.isConnected) return;
    const ev = d.evidence.map((e) => `<div class="fxa-ev${e.direct ? " direct" : ""}">
        <div class="fxa-evh"><span class="fxa-pts">${e.direct ? "direct" : "circumstantial"}${e.points ? ` · ${e.points} pt` : ""}</span> <b>${esc(e.label)}</b> <code class="fxa-tok">${esc(e.token)}</code>
          <span class="muted small">${e.runs_with_it != null ? `carried by ${plural(e.runs_with_it, "run")} in all, ${plural(e.named_actors, "named actor")}` : ""}</span></div>
        ${e.here ? `<div class="fxa-pair"><div><span class="muted small">this run ${ent.rec(d.records[0])}</span><pre>${mark(e.here, e.token)}</pre></div>${e.there ? `<div><span class="muted small">${esc(short(d.actor))} in ${ent.rec(e.there.id)}</span><pre>${mark(e.there.snippet, e.token)}</pre></div>` : ""}</div>` : ""}
      </div>`).join("");
    const cl = d.cluster;
    const mates = cl ? cl.mates.map((m) => `<div class="fxa-ev"><div class="fxa-evh">${ent.rec(m.record)} <span class="muted small">shares ${plural(m.shared, "rare feature")}</span> ${m.tokens.map((t) => `<code class="fxa-tok">${esc(t.slice(0, 40))}</code>`).join(" ")}</div>
        <div class="fxa-pair"><div><span class="muted small">this run</span><pre>${mark(m.here || d.snippet, m.tokens[0])}</pre></div><div><span class="muted small">${ent.rec(m.record)}</span><pre>${mark(m.snippet, m.tokens[0])}</pre></div></div></div>`).join("") : "";
    box.innerHTML = card(`Evidence for ${ent.actor(d.id)}`,
      `<div class="fxa-dh">${bandBadge(d.band)} ${d.actor ? `probably ${ent.actor(d.actor)}` : "no named actor"}${d.conflict ? ` <span class="warn small">direct items also point at ${ent.actor(d.conflict)}</span>` : ""}
         <span class="muted small">${d.time ? esc(d.time) + " · " : ""}${plural(d.actions, "action")} · ${esc(d.style.language)}, ${esc(d.style.network)}, ${esc(d.style.quotes)} quotes · record ${ent.rec(d.records[0])}</span></div>
       ${ev || (d.actor ? "" : `<p class="muted">Nothing rare ties this run to a named actor.</p>`)}
       ${cl ? `<h4 class="fxa-h">Cluster #${cl.id}: ${plural(cl.runs, "run")}${cl.actor ? `, linked to ${ent.actor(cl.actor)}` : ", anonymous only"}</h4>${mates}` : ""}`,
      { sub: "Shared strings are highlighted. Quotes are cut to 160 characters; open a record chip for the whole text. A probable link, not an identity." });
    if (scroll) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function secondPass(r) {
    const h = r.holdout || {}, m = r.model || {}, sp = r.second_pass_links;
    const n = sp.high + sp.medium + sp.low;
    if (!m.weights) return card("Second pass: place and time", `<p class="muted">Too few hidden threads carried place or time evidence to learn weights on this dataset, so no extra links were made.</p>`);
    const kinds = (h.second_pass_kinds || []).map((k) => [k.kinds.split("+").map((x) => esc(x === "own" ? "program owner" : x === "pre" ? "same opening in time" : x === "combo" ? "host+style in time" : x === "fam" ? "same program in time" : x)).join(" + "), fmt(k.links), `${meter(k.precision, k.precision >= 0.9 ? "#0f766e" : k.precision >= 0.7 ? "#b7791f" : HARM)} <b>${p1(k.precision)}</b>`]);
    const w = Object.entries(m.weights).filter(([k]) => k !== "bias").map(([k, v]) => `<span class="fxa-w" title="learned weight (log-odds)">${esc(k)} <b>${v > 0 ? "+" : ""}${v}</b></span>`).join("");
    return card("Second pass: place and time evidence",
      `<p class="small">${fmt(n)} more anonymous runs are linked (${fmt(sp.high)} high, ${fmt(sp.medium)} medium, ${fmt(sp.low)} low). Each needs a place only one named actor touches, or named records within ${Math.round(m.window_s / 60)} minutes that share its program opening, host and code style or exact program, or a program opening that almost only one actor's records carry.</p>
       <h4 class="fxa-h">Measured on held-out threads: which combinations of evidence were right</h4>
       ${table(["evidence on the run", "links", "right"], kinds)}
       <h4 class="fxa-h">Weights learned on ${fmt(m.training_rows)} hidden threads (halves ${(m.training_seeds || []).join(", ")}), tested on other halves</h4>
       <div class="fxa-ws">${w}</div>
       <p class="muted small">Band cut-offs on the predicted probability: high ≥ ${m.cutoffs.high ?? "–"}, medium ≥ ${m.cutoffs.medium ?? "–"}, low ≥ ${m.cutoffs.low ?? "–"}. Each band had to be at least as precise on the training halves as the first pass was there (targets ${["high", "medium", "low"].map((k) => p1((m.targets || {})[k])).join(" / ")}). A "place" alone is the weakest evidence: runs that touch a place a single named actor touches can belong to anyone who later found it.</p>`,
      { sub: `Runs the first pass leaves unlinked get a second look. Only a ${term("second_pass", "second pass")} link whose probability clears a band's cut-off is added; the rest stay unattributed.` });
  }

  function familiesCard(r) {
    const tf = r.template_families;
    if (!tf || !tf.families) return "";
    const rows = tf.top.slice(0, 10).map((f) => [fmt(f.records), fmt(f.runs), `<code class="fxa-tok" title="${esc(f.snippet)}">${esc(f.snippet.replace(/\s+/g, " ").slice(0, 56))}</code>`,
      f.actors_total ? f.actors.slice(0, 2).map((a) => ent.actor(a.actor)).join(" ") + (f.actors_total > 2 ? ` <span class="muted small">+${f.actors_total - 2}</span>` : "") : '<span class="muted">no named actor</span>',
      f.first ? esc(f.first.slice(5)) + " – " + esc((f.last || "").slice(5)) : '<span class="muted">undated</span>', f.clusters ? fmt(f.clusters) : "0", ent.rec(f.example)]);
    return card(`${term("tmpl_family", "Template families")}`,
      `<div class="fxa-big"><div><b>${fmt(tf.families)}</b><span>families of ${tf.min_size}+ actions with one masked program</span></div><div><b>${p1(tf.share_of_runs)}</b><span>of anonymous runs sit in one (${fmt(tf.runs_in_families)})</span></div><div><b>${fmt(tf.subclusters)}</b><span>sub-clusters from shared rare constants (${fmt(tf.runs_in_subclusters)} runs)</span></div></div>
       ${table(["actions", "anon.", "program (masked)", "named actors who run it", "seen", "sub-clusters", "example"], rows)}`,
      { sub: `A template family is a program, not an agent. Splitting by rare constants is not chained: a run joins a sub-cluster only when it shares ${tf.shared_min}+ constants (each carried by at most ${tf.rare_constant_max} family members) with that sub-cluster's first run. Most large families are one fixed program with only a placeholder number varying, so they split into almost nothing; they stay unattributed rather than being credited to whoever ran the program first.` });
  }

  function precRows(bands, name) {
    return ["high", "medium", "low"].map((b) => {
      const x = (bands || {})[b] || {};
      const ci = x.precision_ci;
      const col = x.precision == null ? BASE : x.precision >= 0.9 ? "#0f766e" : x.precision >= 0.7 ? "#b7791f" : HARM;
      return [name, bandBadge(b), fmt(x.links), fmt(x.correct), x.links ? `${meter(x.precision, col)} <b>${p1(x.precision)}</b>${ci ? ` <span class="muted">(${p1(ci[0])}–${p1(ci[1])})</span>` : ""}` : '<span class="muted">no link made</span>'];
    });
  }

  function trust(h, sim) {
    const b = h.bands || {}, w = h.bands_without_largest || {};
    const s = (k) => b[k] && b[k].precision != null ? p1(b[k].precision) : "–";
    const sw = (k) => w[k] && w[k].precision != null ? p1(w[k].precision) : "–";
    let simLine = "";
    if (sim && sim.available) {
      const sl = ["high", "medium", "low"].reduce((n, k) => n + sim.bands[k].links, 0), sc = ["high", "medium", "low"].reduce((n, k) => n + sim.bands[k].correct, 0);
      simLine = `<li><b>Simulated swarms are a negative control.</b> Their agents all run the same generated code, so no run has personal material. Of ${fmt(sim.hidden_runs)} hidden runs in ${fmt(sim.swarms_scored)} swarms the method linked ${fmt(sl)} (${p1(sim.coverage)}), ${fmt(sim.bands.high.links)} of them high, and ${fmt(sc)} of those ${fmt(sl)} were right: when agents share one vocabulary, the few links it makes are coincidences. On such data, trust none of the bands.</li>`;
    }
    return `<ul class="fxa-trust">
      <li><b>High</b> was right ${s("high")} of the time on held-out threads of this dataset (${sw("high")} leaving out the ${h.largest_left_out} largest actors): treat as a strong lead.</li>
      <li><b>Medium</b> was right ${s("medium")} (${sw("medium")} without the largest actors): usually right, check the evidence.</li>
      <li><b>Low</b> was right ${s("low")} (${sw("low")} without the largest actors): a lead only; about one in four is wrong for smaller actors.</li>
      ${simLine}
      <li>The ${term("holdout", "holdout")} flatters the method: hidden threads come from actors who do carry tokens, and ${p1(h.coverage)} of them were linked, against ${"{COV}"} of the truly anonymous runs, which are mostly short fragments. Precision on the anonymous runs themselves cannot be measured.</li></ul>`;
  }

  function validation(r, sim) {
    const h = r.holdout || {};
    if (h.error || !h.bands) return card("How far to trust each band", `<p class="warn">${esc(h.error || "The holdout test did not run.")}</p>`);
    const b = r.bands, cov = p1((b.high.runs + b.medium.runs + b.low.runs) / r.runs);
    let rows = precRows(h.bands_first_pass, "before: first pass only, hidden token is the truth");
    rows = rows.concat(precRows(h.bands, "after: first and second pass, hidden token is the truth"));
    rows = rows.concat(precRows(h.bands_second_pass, "second pass alone (the added links)"));
    rows = rows.concat(precRows(h.bands_without_largest, `this dataset, without the ${h.largest_left_out} largest actors`));
    if (h.bands_merged) rows = rows.concat(precRows(h.bands_merged, "after, scored per estimated agent (tokens the Agents tab merges count as one)"));
    if (sim && sim.this_dataset_agent_pooled) {
      const ap = sim.this_dataset_agent_pooled;
      rows = rows.concat(precRows(ap.bands, "tested, not adopted: tokens of an agent pooled first, scored per agent"));
      rows = rows.concat(precRows(ap.bands_single_token_agents, "same, only hidden threads of agents with a single token"));
    }
    if (sim && sim.available) rows = rows.concat(precRows(sim.bands, `simulated swarms (${sim.swarms_scored} of ${sim.swarms_found}), truth file`));
    return card("How far to trust each band (measured)", trust(h, sim).replace("{COV}", cov) +
      table(["test", "band", "links made", "right", "precision (95% range)"], rows) +
      `<p class="muted small">Holdout: ${fmt(h.hidden_runs)} hidden threads over ${h.seeds.length} random halves. Clusters: of ${fmt(h.cluster_pairs)} pairs of hidden threads put in one cluster, ${p1(h.cluster_pair_precision)} were the same token${h.cluster_pair_precision_merged != null ? ` (${p1(h.cluster_pair_precision_merged)} counting merged tokens as one)` : ""}.${sim && !sim.available ? " " + esc(sim.why || "") : ""}</p>`,
      { sub: `Each ${term("attr_band", "band")} is scored by hiding known identities and trying to recover them.` });
  }

  async function render(host) {
    const r = await api("/api/x/attribution");
    if (!host.isConnected) return;
    if (!r.runs) { host.innerHTML = `<p class="muted">Every action in this dataset carries an identity: there are no anonymous runs to attribute.</p>`; return; }
    const b = r.bands;
    const ex = ["high", "medium", "low"].flatMap((k) => (r.examples[k] || []).slice(0, 3).map((x) => `<button type="button" class="fxa-ex" data-run="${esc(x.id)}">${bandBadge(k)} ${esc(short(x.id))} → ${esc(short(x.actor))}</button>`)).join("");
    host.innerHTML = `<p class="fxa-caveat"><b>Probable links, not identities.</b> ${esc(r.caveat.replace(/^These are probable links[^.]*\.\s*/, ""))}</p>
      <div class="kpis">${kpi("anonymous runs", fmt(r.runs))}${kpi("linked: high", fmt(b.high.runs))}${kpi("linked: medium", fmt(b.medium.runs))}${kpi("linked: low", fmt(b.low.runs))}${kpi("unattributed", fmt(b.unattributed.runs), p1(b.unattributed.runs / r.runs) + " of runs")}${kpi("clusters", fmt(r.clusters_total), fmt(r.clustered_runs) + " runs")}</div>
      ${coverage(r)}${secondPass(r)}${familiesCard(r)}${bubbles(r)}<div class="fxa-two">${kindsCard(r)}${actorsCard(r)}</div>${clustersCard(r)}
      <div class="card"><header><h3>Open a run</h3><span class="muted small">examples from each band</span></header><div class="fxa-exs">${ex}</div></div>
      <div id="fxaDetail"></div><div id="fxaVal"><p class="muted">Scoring on simulated swarms…</p></div>
      <p class="muted small">Method: features are exact redacted values, string constants, identifiers and self-chosen names; one counts when at most ${r.method.max_actors} named actors use it and at most ${r.method.common} runs carry it, and is direct when one named actor uses it and at most ${r.method.rare} runs carry it. ${fmt(r.method.messaged_features_ignored)} features that travelled in a message are ignored. The first ${fmt(r.method.text_cap)} characters of each record are read. Computed in ${r.seconds} s. Estimated agents: ${fmt(r.agent_layer.merged_tokens)} of ${fmt(r.agent_layer.tokens)} tokens merge into ${fmt(r.agent_layer.merged_agents)} agents; links name a token, and the Agents tab folds tokens into agents.</p>`;
    host.querySelectorAll("[data-run]").forEach((el) => el.addEventListener("click", () => detail(el.dataset.run)));
    const clBox = $("fxaCl");
    if (clBox) bindRows(clBox, (i) => detail(r.clusters[i].members[0]));
    const first = (r.examples.high || [])[0] || (r.examples.medium || [])[0] || (r.examples.low || [])[0];
    if (first) detail(first.id, false);
    let sim = null;
    try { sim = await api("/api/x/attribution_score"); } catch (e) { sim = { available: false, why: e.message }; }
    if ($("fxaVal")) $("fxaVal").innerHTML = validation(r, sim);
  }

  window.FX_SECTIONS.push({
    id: "attribution", title: "Who are the anonymous runs?", group: "How agents behaved",
    blurb: "Most actions carry no identity token. This section links anonymous runs to named actors, and to each other, by the rare material they share, and says how often such links were right when tested.",
    render,
  });
})();

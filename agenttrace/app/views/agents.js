// Agents: a token is not an agent. Named actors that are probably one agent (merge proposals scored
// from counted evidence, with the evidence against), the agent groups they form, an estimate of how many
// agents there were, and each named actor's role in the message graph. Decisions go to the server.
(() => {
  "use strict";

  GLOSSARY.estimated_agent = ["Estimated agent", "A group of named actors that are probably one agent: actors joined by a high-confidence or accepted merge proposal (never a rejected one). The low end of the range also joins medium proposals; the high end joins only accepted ones. Anonymous runs and shared keys are not counted."];
  GLOSSARY.merge_proposal = ["Merge proposal", "Two named actors that may be one agent holding two tokens or names. Each piece of evidence is counted in the records and adds points by a fixed rule (one record using both, one carrying the other's token, the same self-chosen names or places, handoffs in time, the same programs, messages between them); evidence against subtracts. 6+ points is high confidence, 4-5 medium, 2-3 low."];
  GLOSSARY.role = ["Role", "What a named actor does in the message graph, by a fixed rule: coordinator (sends to many actors, early), relay (on many shortest message routes, hears and sends), recruiter (first to message many actors), worker (receives at least as much as it sends and runs many actions), participant (other messaging), lone actor (no messages with named actors)."];

  const ROLE_COLOR = { coordinator: "#2f6fb3", relay: "#7c4dbd", recruiter: "#0f766e", worker: "#d39b2a", participant: "#8a94a0", lone: "#c5ccd3" };
  const ROLE_WORD = { coordinator: "coordinator", relay: "relay / broker", recruiter: "recruiter", worker: "worker", participant: "participant", lone: "lone actor" };
  const CONF_COLOR = { high: "#0f766e", medium: "#d39b2a", low: "#a3acb6" };
  const roleBadge = (r) => r ? `<span class="agrole" style="--c:${ROLE_COLOR[r] || "#999"}">${esc(ROLE_WORD[r] || r)}</span>` : "";
  const confBadge = (c) => c ? `<span class="agconf ${c}">${esc(c)}</span>` : '<span class="agconf none">no rule</span>';
  const ST = { conf: "", q: "", undecided: false, shown: 10, role: "", roleShown: 60 };

  function reportsCount(ctx) {
    return (ctx?.numbers || []).filter((x) => /agent/i.test(x.label) && !/name/i.test(x.label)).slice(0, 2);
  }

  async function agents(el, s) {
    el.innerHTML = '<div id="agw"><p class="muted">Counting the evidence…</p></div>';
    const [idr, roles, ctxR] = await Promise.all([api("/api/x/identity"), cached("/api/x/roles"), cached("/api/context").catch(() => ({}))]);
    const host = $("agw");
    if (!host || S.tab !== "agents") return;
    host.innerHTML = `
      <div id="agunit"></div>
      <div id="agest"></div>
      ${card(`${term("merge_proposal", "Merge proposals")}`, '<div id="agbar"></div><div id="agprops"></div>',
        { sub: `Pairs of named actors that may be one agent, highest score first. Every point comes from evidence counted in the records (the record chips open them); evidence against is subtracted. Accept or reject a pair to change the estimate; decisions stay for this dataset.`, right: '<button class="link" id="agrules">How the score is counted</button>' })}
      <div id="agrulebox" hidden></div>
      <div class="grid2">
        ${card("Agent groups", '<div id="aggroups"></div>', { sub: `Named actors joined by high-confidence or accepted proposals: each group counts as one ${term("estimated_agent", "estimated agent")}.` })}
        ${card("Numbered names", '<div id="agnames"></div>', { sub: "Self-chosen names that differ only by trailing digits (Helper12, Helper57): one agent may make a new name per run. Large families are more likely a shared template." })}
      </div>
      ${card("Why not merged?", '<div id="agwhy"></div>', { sub: "Pick two named actors you expect to be one agent: the score they got, what pushed it down, which kinds of evidence were not found for them, and how far they are from a merge." })}
      ${card(`${term("role", "Roles")}`, '<div id="agrolesum"></div><div id="agroles"></div>', { sub: `Each named actor's role in the messages between named actors (${fmt(roles.messages_between_named)} messages), with the numbers behind it. Click a role to filter.`, right: '<button class="link" id="agrolerules">Rules</button>' })}
      <div id="agrolerulebox" hidden></div>`;
    let cur = idr;
    const draw = (r) => { cur = r; estimate(r, ctxR.context, s); proposals(r); groups(r); names(r); };
    draw(idr);
    unitBanner();
    whyNot(idr, roles);
    rules(idr, roles);
    roleView(roles);
    host.querySelector("#agrules").addEventListener("click", () => { const b = $("agrulebox"); b.hidden = !b.hidden; });
    host.querySelector("#agrolerules").addEventListener("click", () => { const b = $("agrolerulebox"); b.hidden = !b.hidden; });
    host.addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-dec]");
      if (!b) return;
      b.disabled = true;
      try {
        const r = await api("/api/x/identity_decide", { method: "POST", body: JSON.stringify({ a: b.dataset.a, b: b.dataset.b, decision: b.dataset.dec }) });
        const before = cur.estimate, after = r.estimate;
        draw(await api("/api/x/identity"));
        await reloadUnits();      // the decision changes which tokens are one agent: the top bar and every tab recount
        unitBanner();
        const wi = await api("/api/x/fx_whatif?rule=accepted").catch(() => null);
        status(`${{ accept: "Accepted as one agent", reject: "Rejected: two agents", clear: "Decision undone" }[b.dataset.dec] || "Saved"} · recount: ${fmt(before?.estimated_agents)} → ${fmt(after?.estimated_agents)} estimated agents${wi ? `, ${fmt(wi.as_counted.messages)} → ${fmt(wi.after.messages)} messages with only accepted merges` : ""}. Decisions are saved on this server for this dataset and seen by everyone using it.`);
        setTimeout(() => status(""), 8000);
      } catch (err) { status(err.message, true); b.disabled = false; }
    });
  }

  // what the app is counting by, what that changes, and the switch
  function unitBanner() {
    const host = $("agunit"), u = S.units;
    if (!host) return;
    if (!u) { host.innerHTML = ""; return; }
    const m = u.messages, sw = (unit, label) => `<button type="button" class="link" data-setunit="${unit}">${label}</button>`;
    const changes = u.no_merges ? `${esc(UNIT_NONE)}: no merge proposal is high-confidence or accepted, so both ways of counting give the same numbers (${fmt(u.tokens)} named actors, ${plural(m.token, "message")}). Accept a proposal below to merge two tokens.`
      : `${plural(u.merges, "merge")} join ${fmt(u.merged_tokens)} tokens into ${plural(u.merged_agents, "agent")} (${u.agent_list.slice(0, 6).map((g) => ent.agent(g.id)).join(" ")}${u.agent_list.length > 6 ? " …" : ""}), so ${fmt(u.tokens)} tokens count as <b>${fmt(u.agents)}</b> estimated agents. Of ${plural(m.token, "message")} between tokens, <b>${fmt(m.inside_one_agent)}</b> pass inside one agent and <b>${fmt(m.agent)}</b> between two agents${m.rejected ? ` (${fmt(m.rejected)} rejected in What-if)` : ""}; warning signs that only join tokens of one agent move later or do not fire.`;
    host.innerHTML = byAgent()
      ? `<div class="unitnote agunit"><b>The app is counting by estimated agents</b> ${estMark()} in every tab. ${changes} Accepting or rejecting a proposal below changes these counts everywhere. ${sw("token", "Count by tokens instead")}</div>`
      : `<div class="unitnote token agunit"><b>The app is counting by tokens</b>: each token or name is treated as its own actor. ${u.no_merges ? changes : `Counting by estimated agents would use: ${changes}`} ${sw("agent", "Count by estimated agents")}</div>`;
  }

  function estimate(r, ctx, s) {
    const e = r.estimate, rep = reportsCount(ctx);
    const range = e.low === e.high ? "" : ` (range ${fmt(e.low)}–${fmt(e.high)})`;
    $("agest").innerHTML = `<section class="card agest">
      <div class="aghead"><div class="agbig"><b>${fmt(e.named_actors)}</b> ${term("named", "named actors")} <span class="agarrow">→</span> about <b>${fmt(e.estimated_agents)}</b> ${term("estimated_agent", "estimated agents")}<span class="muted">${range}</span></div>
      <p class="sub">A ${term("token", "token")} or name is not an agent: one agent can hold several, and a ${term("shared_key", "shared key")} stands for many. The estimate joins actors with high-confidence or accepted ${term("merge_proposal", "merge proposals")}; the low end also joins medium ones, the high end only accepted ones. It counts named actors that ran at least one action${e.unattributed_actions ? `; ${fmt(e.unattributed_actions)} actions by ${term("run", "anonymous runs")} cannot be assigned to any agent and are not in it` : ""}${e.shared_keys ? `; ${plural(e.shared_keys, "shared key")} stand${e.shared_keys === 1 ? "s" : ""} for an unknown number of agents` : ""}.</p></div>
      <div class="kpis">
        ${kpi(term("named", "named actors"), fmt(e.named_actors), identityLine(S.summary, e) || "tokens and names that ran actions")}
        ${kpi(term("estimated_agent", "estimated agents"), fmt(e.estimated_agents), e.low === e.high ? "no medium or accepted pairs change it" : `${fmt(e.low)} to ${fmt(e.high)}`)}
        ${rep.map((x) => kpi(esc(x.label), esc(x.value), `the reports (${esc(x.source)})`)).join("")}
        ${kpi(term("merge_proposal", "proposals"), fmt(e.proposals), ["high", "medium", "low"].map((c) => `${fmt(e.by_confidence[c] || 0)} ${c}`).join(" · ") + " undecided")}
        ${kpi("decisions", fmt(e.accepted + e.rejected), `${fmt(e.accepted)} accepted · ${fmt(e.rejected)} rejected · saved on this server, seen by everyone using it`)}
      </div>
      ${rep.length && e.named_actors ? `<p class="small muted">The reports count agents from the operators' own logs; this dataset sees ${fmt(e.named_actors)} named actors. A gap between the two is what the records cannot tell apart: anonymous runs, shared keys, and agents that never authenticated.</p>` : ""}
    </section>`;
  }

  function evidenceRow(x, against) {
    const pts = x.points > 0 ? `+${x.points}` : String(x.points);
    return `<li class="${against ? "ag-against" : ""}"><span class="agpts">${pts}</span> ${esc(x.text)}${x.records?.length ? ` <span class="agrecs">${x.records.map((id) => ent.rec(id)).join(" ")}</span>` : ""}</li>`;
  }

  function proposalCard(x, maxScore) {
    const dec = x.decision;
    const btn = (d, label, cls = "") => `<button type="button" class="${cls}" data-dec="${d}" data-a="${esc(x.a)}" data-b="${esc(x.b)}">${label}</button>`;
    return `<div class="agprop ${dec ? "dec-" + dec : ""}">
      <div class="agph">
        <div class="agpair">${ent.actor(x.a)} <span class="muted">+</span> ${ent.actor(x.b)}</div>
        <div class="agscore">${confBadge(x.confidence)} <span class="agsbar"><i style="width:${Math.max(0, Math.min(1, x.score / maxScore)) * 100}%;background:${CONF_COLOR[x.confidence] || "#ccc"}"></i></span> <b>${fmt(x.score)}</b> <span class="muted small">points</span></div>
        <div class="agbtns">${dec ? `<span class="agdecided ${dec}">${dec === "accept" ? "accepted: one agent" : "rejected: two agents"}</span> ${btn("clear", "Undo", "link")}` : `${btn("accept", "Accept", "primary")} ${btn("reject", "Reject")}`}</div>
      </div>
      ${x.evidence.length ? `<ul class="agev">${x.evidence.map((v) => evidenceRow(v, false)).join("")}</ul>` : '<p class="small muted">No rule fired for this pair; it is here because of your decision.</p>'}
      ${x.against.length ? `<div class="agagh">Evidence against</div><ul class="agev">${x.against.map((v) => evidenceRow(v, true)).join("")}</ul>` : '<div class="small faint">No evidence against was found (no parallel activity, no conflicting self-chosen names).</div>'}
    </div>`;
  }

  function proposals(r) {
    const all = r.proposals;
    const bar = $("agbar");
    const counts = { "": all.length };
    for (const x of all) counts[x.confidence || "none"] = (counts[x.confidence || "none"] || 0) + 1;
    bar.innerHTML = `<div class="agfilters">${["", "high", "medium", "low"].map((c) => `<button type="button" class="${ST.conf === c ? "on" : ""}" data-conf="${c}">${c || "all"} <span class="muted">${fmt(counts[c] || 0)}</span></button>`).join("")}
      <input id="agq" placeholder="Filter by actor" value="${esc(ST.q)}"> <label class="small"><input type="checkbox" id="agund" ${ST.undecided ? "checked" : ""}> undecided only</label>
      ${r.proposals_total > all.length ? `<span class="small muted">top ${fmt(all.length)} of ${fmt(r.proposals_total)} by score</span>` : ""}</div>`;
    bar.querySelectorAll("[data-conf]").forEach((b) => b.addEventListener("click", () => { ST.conf = b.dataset.conf; ST.shown = 10; proposals(r); }));
    const q = bar.querySelector("#agq");
    let t = null;
    q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { ST.q = q.value.trim(); ST.shown = 10; drawList(); }, 200); });
    bar.querySelector("#agund").addEventListener("change", (e) => { ST.undecided = e.target.checked; ST.shown = 10; drawList(); });
    const drawList = () => {
      const ql = ST.q.toLowerCase();
      const rows = all.filter((x) => (!ST.conf || x.confidence === ST.conf) && (!ST.undecided || !x.decision)
        && (!ql || [x.a, x.b, short(x.a), short(x.b)].some((v) => v.toLowerCase().includes(ql))));
      const max = Math.max(8, ...all.map((x) => x.score));
      const box = $("agprops");
      if (!all.length) { box.innerHTML = '<p class="muted">No pair of named actors has enough counted evidence (2+ points) to propose. Each named actor counts as its own agent.</p>'; return; }
      box.innerHTML = (rows.length ? rows.slice(0, ST.shown).map((x) => proposalCard(x, max)).join("") : '<p class="muted">No proposal matches.</p>')
        + (rows.length > ST.shown ? `<button type="button" class="lmore" id="agmore">Show ${fmt(Math.min(25, rows.length - ST.shown))} more of ${fmt(rows.length - ST.shown)}</button>` : "");
      const m = box.querySelector("#agmore");
      if (m) m.addEventListener("click", () => { ST.shown += 25; drawList(); });
    };
    drawList();
  }

  function groups(r) {
    const box = $("aggroups");
    if (!r.groups.length) { box.innerHTML = '<p class="muted small">No group yet: no high-confidence or accepted proposal. Every named actor counts as its own agent.</p>'; return; }
    box.innerHTML = `<div class="aggrp">${r.groups.slice(0, 40).map((g, i) => `<div class="agg">${i < 12 ? groupGraph(g) : ""}<div class="small"><b>Agent ${i + 1}</b> <span class="muted">${plural(g.actors.length, "named actor")} · ${plural(g.records, "record")} · ${plural(g.links.length, "link")}${g.links.some((l) => l.decision === "accept") ? " · includes accepted" : ""}</span></div><div class="agchips">${g.actors.slice(0, 30).map((a) => ent.actor(a)).join(" ")}${g.actors.length > 30 ? ` <span class="muted small">+${g.actors.length - 30}</span>` : ""}</div></div>`).join("")}</div>${more(Math.min(40, r.groups.length), r.groups_total, "groups")}`;
  }

  // one merge group as a small graph: each line is a link that joins the group (high or accepted),
  // thicker for more points; dashed when the investigator accepted it without a high score
  function groupGraph(g) {
    const n = g.actors.length;
    if (n < 2 || n > 40) return "";
    const W = 260, Hh = n <= 3 ? 90 : n <= 8 ? 150 : 200, cx = W / 2, cy = Hh / 2, rad = Math.min(cx, cy) - 26;
    const pos = new Map(g.actors.map((a, k) => { const ang = -Math.PI / 2 + (2 * Math.PI * k) / n; return [a, [cx + rad * Math.cos(ang) * (n === 2 ? 1.6 : 1.25), cy + rad * Math.sin(ang)]]; }));
    const deg = new Map(); g.links.forEach((l) => { deg.set(l.a, (deg.get(l.a) || 0) + 1); deg.set(l.b, (deg.get(l.b) || 0) + 1); });
    let svg = `<svg class="aggraph" width="100%" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Links that join this group">`;
    g.links.forEach((l) => {
      const [x1, y1] = pos.get(l.a) || [0, 0], [x2, y2] = pos.get(l.b) || [0, 0];
      const acc = l.decision === "accept";
      svg += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${acc ? "#2f6fb3" : CONF_COLOR[l.confidence] || "#9aa5b1"}" stroke-width="${(0.8 + Math.min(8, l.score || 0) * 0.35).toFixed(2)}" stroke-opacity=".75"${acc && l.confidence !== "high" ? ' stroke-dasharray="4 3"' : ""}><title>${esc(short(l.a))} + ${esc(short(l.b))}: ${fmt(l.score)} points${l.confidence ? `, ${l.confidence}` : ""}${acc ? ", accepted" : ""}</title></line>`;
    });
    g.actors.forEach((a) => {
      const [x, y] = pos.get(a), r = 4 + Math.min(5, deg.get(a) || 0);
      svg += `<circle class="node" data-actor="${esc(a)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${C.actorBg}" stroke="${C.actor}" stroke-width="1.4"/>`;
      if (n <= 12) svg += `<text x="${x.toFixed(1)}" y="${(y + (y < cy ? -r - 3 : r + 11)).toFixed(1)}" text-anchor="middle" font-size="9.5" fill="#3d4a58" paint-order="stroke" stroke="#fff" stroke-width="3" pointer-events="none">${esc(fitName(short(a), 80, "9.5px -apple-system, system-ui, sans-serif"))}</text>`;
    });
    return svg + "</svg>";
  }

  // ---------------------------------------------------------------- why not merged
  function whyNot(r, roles) {
    const box = $("agwhy");
    if (!box) return;
    const names = [...new Set((roles.rows || []).map((x) => x.actor).concat(r.proposals.flatMap((x) => [x.a, x.b])))].sort((a, b) => short(a).localeCompare(short(b)));
    if (names.length < 2) { box.innerHTML = '<p class="muted small">Fewer than two named actors.</p>'; return; }
    box.innerHTML = `<div class="agwhyctl"><input id="agwa" list="agwlist" placeholder="first actor" value="${esc(ST.wa || "")}"> + <input id="agwb" list="agwlist" placeholder="second actor" value="${esc(ST.wb || "")}"> <button type="button" id="agwgo">Explain</button></div>
      <datalist id="agwlist">${names.slice(0, 3000).map((a) => `<option value="${esc(a)}">${esc(short(a))}</option>`).join("")}</datalist><div id="agwout"></div>`;
    const resolve = (v) => names.find((a) => a === v) || names.find((a) => short(a) === v) || null;
    $("agwgo").addEventListener("click", async () => {
      const a = resolve($("agwa").value.trim()), b = resolve($("agwb").value.trim()), out = $("agwout");
      ST.wa = $("agwa").value.trim(); ST.wb = $("agwb").value.trim();
      if (!a || !b) { out.innerHTML = '<p class="small warn">Pick two named actors from the list.</p>'; return; }
      if (a === b) { out.innerHTML = '<p class="small warn">Pick two different actors.</p>'; return; }
      out.innerHTML = '<p class="small muted">Counting…</p>';
      try { out.innerHTML = await explainPair(r, a, b); } catch (e) { out.innerHTML = `<p class="small warn">${esc(e.message)}</p>`; }
    });
  }
  async function explainPair(r, a, b) {
    const th = r.thresholds;
    const find = (list) => (list || []).find((x) => (x.a === a && x.b === b) || (x.a === b && x.b === a));
    let x = find(r.proposals), ra = null, rb = null;
    if (!x) { ra = await api(`/api/x/identity?actor=${encodeURIComponent(a)}`); x = find(ra.proposals); }
    if (!x) { rb = await api(`/api/x/identity?actor=${encodeURIComponent(b)}`); x = find(rb.proposals); }
    const grpA = r.groups.findIndex((g) => g.actors.includes(a)), grpB = r.groups.findIndex((g) => g.actors.includes(b));
    const same = grpA >= 0 && grpA === grpB;
    const head = `<div class="agpair">${ent.actor(a)} <span class="muted">+</span> ${ent.actor(b)}</div>`;
    let verdict;
    if (same) verdict = `<p><b>They are already counted as one agent</b> (Agent ${grpA + 1})${x && !(x.decision === "accept" || x.confidence === "high") ? ", joined through other members of the group rather than directly" : ""}.</p>`;
    else if (x && x.decision === "reject") verdict = `<p><b>Not merged because the pair was rejected</b> by an investigator's decision (score ${fmt(x.score)}).</p>`;
    else if (x) verdict = `<p><b>Not merged: ${fmt(x.score)} points, ${x.confidence} confidence.</b> A merge needs ${th.high}+ points (high) or an accepted decision; ${th.high - x.score > 0 ? `${plural(th.high - x.score, "more point")} would make it high.` : ""} Medium pairs only count in the low end of the estimate's range.</p>`;
    else {
      const totals = [ra?.proposals_total, rb?.proposals_total].filter((v) => v != null);
      verdict = `<p><b>Not merged: under ${th.low} points.</b> No rule found enough evidence that one agent held both, so the pair is not even proposed.${totals.some((v) => v > 20) ? " (Each actor's list is cut at its top 20 pairs, so a weak score just below that cut is not shown.)" : ""}</p>`;
    }
    const got = new Set((x?.evidence || []).map((v) => v.key));
    const missing = r.rules.filter((rule) => rule.points.trim().startsWith("+") && !got.has(rule.key));
    const ev = x ? `${x.evidence.length ? `<div class="agagh">Evidence for</div><ul class="agev">${x.evidence.map((v) => evidenceRow(v, false)).join("")}</ul>` : ""}
      ${x.against.length ? `<div class="agagh">Evidence against (subtracted)</div><ul class="agev">${x.against.map((v) => evidenceRow(v, true)).join("")}</ul>` : '<div class="small faint">No evidence against.</div>'}` : "";
    const miss = missing.length ? `<div class="agagh">Not found for this pair</div><ul class="agev agmiss">${missing.map((m) => `<li><span class="agpts">${esc(m.points.split(" ")[0])}</span> ${esc(m.what)}</li>`).join("")}</ul>` : "";
    return `<div class="agprop">${head}${verdict}${ev}${miss}${!same && !(x && x.decision === "reject") ? `<div class="agbtns">If you know they are one agent: <button type="button" class="primary" data-dec="accept" data-a="${esc(a)}" data-b="${esc(b)}">Accept as one agent</button></div>` : ""}</div>`;
  }

  function names(r) {
    const box = $("agnames");
    const f = r.name_families || [];
    if (!f.length) { box.innerHTML = '<p class="muted small">No two named actors have names that differ only by trailing digits.</p>'; return; }
    box.innerHTML = hbars(f.slice(0, 15).map((x) => ({ label: `<code>${esc(x.stem)}…</code>`, value: x.names, color: "#d39b2a", title: x.actors.map(short).join(", ") })))
      + `<p class="small muted">${plural(Math.min(15, f.length), "stem")}, largest first; named actors per stem (hover for names). For example: ${f[0].actors.slice(0, 3).map((a) => ent.actor(a)).join(" ")}</p>`;
  }

  function rules(r, roles) {
    $("agrulebox").innerHTML = card("How a merge proposal is scored", table(["evidence", "points", "what is counted"], r.rules.map((x) => [esc(human(x.key)), esc(x.points), esc(x.what)]))
      + `<p class="small muted">Points add up. ${r.thresholds.high}+ is high confidence, ${r.thresholds.medium}-${r.thresholds.high - 1} medium, ${r.thresholds.low}-${r.thresholds.medium - 1} low; under ${r.thresholds.low} is not proposed. One agent holding two keys and one agent stealing another's key leave the same trace in a record: the score counts what is there, the investigator decides.</p>`, { sub: "A fixed, additive rule; it was not tuned on any dataset." });
    const th = roles.thresholds || {};
    $("agrolerulebox").innerHTML = card("How a role is assigned", table(["role", "rule"], roles.rules.map((x) => [roleBadge(x.role), esc(x.rule)]))
      + `<p class="small muted">The first rule that fits wins. In this dataset: top-5% out-partners ≥ ${fmt(th.out_partners)}, top-5% broker share ≥ ${(100 * (th.broker_share || 0)).toFixed(2)}%, top-5% first contacts ≥ ${fmt(th.first_contacts)}, median actions of messaging actors ${fmt(th.worker_actions)}.${roles.broker_sampled ? " Broker share is estimated from 300 evenly spaced starting actors." : ""}</p>`, {});
  }

  async function roleView(roles) {
    const sum = $("agrolesum");
    const order = ["coordinator", "relay", "recruiter", "worker", "participant", "lone"];
    const total = Object.values(roles.counts).reduce((a, b) => a + b, 0);
    sum.innerHTML = stackbar(order.filter((k) => roles.counts[k]).map((k) => ({ label: ROLE_WORD[k], value: roles.counts[k], color: ROLE_COLOR[k] })), { legend: false })
      + `<div class="agrolebtns">${["", ...order].filter((k) => !k || roles.counts[k]).map((k) => `<button type="button" class="${ST.role === k ? "on" : ""}" data-role="${k}">${k ? roleBadge(k) : "all"} <b>${fmt(k ? roles.counts[k] : total)}</b></button>`).join("")}</div>`;
    sum.querySelectorAll("[data-role]").forEach((b) => b.addEventListener("click", () => { ST.role = b.dataset.role; ST.roleShown = 60; roleView(roles); }));
    const box = $("agroles");
    box.innerHTML = '<p class="muted small">Loading…</p>';
    const r = await cached(`/api/x/roles?limit=5000${ST.role ? "&role=" + ST.role : ""}`);
    const rows = r.rows;
    const drawT = () => {
      box.innerHTML = `<div class="tscroll">${table(["actor", "role", "sent", "received", "sends to", "hears from", "first contacts", "broker share", "actions", "why"],
        rows.slice(0, ST.roleShown).map((x) => [ent.actor(x.actor), roleBadge(x.role), fmt(x.sent), fmt(x.received), fmt(x.out_partners), fmt(x.in_partners), fmt(x.first_contacts),
          x.broker_share ? `${(100 * x.broker_share).toFixed(x.broker_share < 0.01 ? 2 : 1)}%${x.broker_rank ? ` <span class="muted">#${x.broker_rank}</span>` : ""}` : "–", fmt(x.actions), `<span class="small muted">${esc(x.why)}</span>`]))}</div>`
        + (rows.length > ST.roleShown ? `<button type="button" class="lmore" id="agrmore">Show ${fmt(Math.min(200, rows.length - ST.roleShown))} more of ${fmt(rows.length - ST.roleShown)}</button>` : "")
        + `<p class="small muted">Sends to / hears from: distinct named actors. First contacts: actors this one was the first ever to message. Broker share: shortest message routes between two others that pass through it.</p>`;
      const m = box.querySelector("#agrmore");
      if (m) m.addEventListener("click", () => { ST.roleShown += 200; drawT(); });
    };
    drawT();
  }

  VIEWS.agents = agents;

  // ------------------------------------------------------------------ Inspector: "probably the same agent as …"
  window.INSPECTOR_EXTRAS.push((kind, key) => kind === "actor" && !String(key).startsWith("run:") ? `<div class="dsec agins" data-agins="${esc(key)}"><h4>Same agent? and ${term("role", "role")}</h4><p class="small muted">Counting…</p></div>` : "");
  window.INSPECTOR_BIND.push((host, kind, key) => {
    if (kind !== "actor" || String(key).startsWith("run:")) return;
    const box = host.querySelector(".agins");
    if (!box) return;
    api("/api/x/identity?actor=" + encodeURIComponent(key)).then((r) => {
      const ro = r.role;
      const other = (x) => (x.a === key ? x.b : x.a);
      const strong = r.proposals.filter((x) => x.decision === "accept" || (x.decision !== "reject" && (x.confidence === "high" || x.confidence === "medium")));
      const weak = r.proposals.filter((x) => !x.decision && x.confidence === "low").length;
      const line = (x) => `<div class="agirow">${ent.actor(other(x))} ${x.decision === "accept" ? '<span class="agdecided accept">accepted</span>' : confBadge(x.confidence)} <span class="muted small">${fmt(x.score)} points: ${esc(x.evidence.map((v) => human(v.key)).join(", ") || "decision only")}${x.against.length ? `; against: ${esc(x.against.map((v) => human(v.key)).join(", "))}` : ""}</span></div>`;
      box.innerHTML = `<h4>Same agent? and ${term("role", "role")}</h4>
        ${ro ? `<p class="small">${roleBadge(ro.role)} <span class="muted">${esc(ro.why)}</span></p>` : '<p class="small muted">No role: it ran no action.</p>'}
        ${strong.length ? `<p class="small">Probably the same agent as:</p>${strong.slice(0, 6).map(line).join("")}${more(Math.min(6, strong.length), strong.length, "proposals")}` : `<p class="small muted">No high or medium ${term("merge_proposal", "merge proposal")} names this actor: no strong counted evidence that it shares an agent with another named actor.</p>`}
        ${weak ? `<p class="small muted">${plural(weak, "weaker (low-confidence) proposal")} also name${weak === 1 ? "s" : ""} it.</p>` : ""}
        ${r.group ? `<p class="small muted">In a group of ${plural(r.group.actors.length, "named actor")} counted as one ${term("estimated_agent", "estimated agent")}.</p>` : ""}
        <button type="button" class="link" data-gotab-agents>Open the Agents tab</button>`;
      const b = box.querySelector("[data-gotab-agents]");
      if (b) b.addEventListener("click", () => { ST.q = key; ST.conf = ""; goTab("agents"); });
    }).catch((e) => { box.innerHTML = `<p class="small muted">${esc(e.message)}</p>`; });
  });
})();

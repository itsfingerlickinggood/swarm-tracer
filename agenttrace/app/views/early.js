// Early flag: replay the incident hour by hour and watch each warning sign fire.
// Everything comes from /api/sim (hourly state and every signal) and /api/messages (who read whom);
// the alert rule is computed here so it can be changed in the page.
"use strict";
(() => {
  const ST = { i: null, playing: false, speed: 380, N: 2, timer: null, data: null };
  let RUN = 0;
  const HR = 3600;
  const KIND = { harm: "harmful action", token: "token moved", carried: "carried token", place: "shared place", message: "message",
    group: "linked group", two_way: "two-way exchange", program: "shared program", baseline: "volume" };
  const LEVEL = [{ name: "quiet", color: "#e6eaee" }, { name: "watch", color: "#f2c46d" }, { name: "alert", color: HARM }];
  const isRec = (r) => r && (/^[A-Za-z]\d{3,}$/.test(String(r)) || /[~@]/.test(String(r)));
  // sign texts come from the server with raw names; show them the way the rest of the app does
  const placeRx = () => { const ks = Object.keys(S.summary?.flow?.channel_types || {}); return ks.length ? new RegExp(`\\b(?:${ks.map((k) => k.replace(/[^\w]/g, "")).join("|")}):(?:\\[[^\\]]+\\]|[\\w.\\-~@/])+`, "g") : null; };
  const plain = (x) => {
    let t = String(x ?? "");
    const rx = placeRx();
    if (rx) t = t.replace(rx, (m) => placeLabel(m));
    return t.replace(/\[CREDENTIAL (\d+)\]/g, "cred $1").replace(/(\d+(?:\.\d+)?) h later/g, (m, h) => `${hoursWord(+h)} later`);
  };
  const recOf = (g) => g.record || (isRec(g.ref) ? g.ref : null);
  const TOKEN_NOTE = "Filed as a single-actor sign: the token moved between identities, but the data does not show who passed it.";
  const hourRange = (t) => `${when(t)}–${clock(t + HR * 1000)}`;
  const PHASE_WHY = { first: "the first dated action", stop: "after the busiest hour, the first hour with under 15% of its actions", last: "the last dated action" };
  const refChip = (g) => (recOf(g) ? ent.rec(recOf(g)) : g.ref ? `<code>${esc(short(g.ref))}</code>` : "");

  function stop() { clearInterval(ST.timer); ST.timer = null; ST.playing = false; const b = $("efPlay"); if (b) b.innerHTML = "▶ Play"; }

  // the tracer's rule: watch on the first single-actor harmful sign, alert once N kinds of coordination have shown
  function rule(sigs, N) {
    const watch = sigs.find((g) => g.family === "single" && g.kind === "harm") || null;
    const kinds = []; let alert = null;
    for (const g of sigs) {
      if (g.family !== "joint") continue;
      if (!kinds.includes(g.kind)) kinds.push(g.kind);
      if (!alert && kinds.length >= N) alert = { ...g, kinds: kinds.slice() };
    }
    const baseline = sigs.find((g) => g.family === "baseline") || null;
    return { watch, alert, baseline, N };
  }
  const levelAt = (r, t) => (r.alert && t >= r.alert.t ? 2 : r.watch && t >= r.watch.t ? 1 : 0);
  const lead = (a, b) => (a && b ? (b.t - a.t) / HR : null);

  async function view(el, s) {
    const my = ++RUN;
    stop();
    el.innerHTML = `<h2>Could it have been flagged early?</h2><p class="muted">Loading the replay…</p>`;
    const [sim, msgs] = await Promise.all([cached("/api/sim"), cached("/api/messages")]);
    if (my !== RUN || !el.isConnected || S.tab !== "early") return;
    if (!sim.hours) {
      el.innerHTML = `<h2>Could it have been flagged early?</h2><p class="lead">No record has a time, so the incident cannot be replayed hour by hour.</p><p class="muted small">Add a time field (or a pack that estimates times from the text) and analyze again.</p>`;
      return;
    }
    const n = sim.hours;
    const sigs = sim.signals.map((g, k) => ({ ...g, num: k + 1 }));
    const cum = (xs) => { let a = 0; return xs.map((v) => (a += v || 0)); };
    const D = {
      sim, sigs, n, hasHarm: !!sim.harm_total,
      cumActions: cum(sim.actions), cumHarm: cum(sim.harmful), cumActors: cum(sim.new_actors), 
      // named messages on exact places, the same set the warning signs count; places the redaction may
      // have merged are counted apart, since their write and read may be on two different places
      named: msgs.rows.filter((r) => !String(r[0]).startsWith("run:") && !String(r[1]).startsWith("run:") && !r[9]),
      mergedNamed: msgs.rows.filter((r) => !String(r[0]).startsWith("run:") && !String(r[1]).startsWith("run:") && r[9]).map((r) => r[6]).sort((a, b) => a - b),
      anonMsgs: msgs.rows.filter((r) => String(r[0]).startsWith("run:") || String(r[1]).startsWith("run:")).map((r) => r[6]).sort((a, b) => a - b),
      mergedAll: msgs.rows.filter((r) => r[9]).length,
      allPairs: new Set(msgs.rows.filter((r) => !String(r[0]).startsWith("run:") && !String(r[1]).startsWith("run:")).map((r) => r[0] + "\u0000" + r[1])).size,
    };
    D.layout = netLayout(D.named);
    {   // named messages, pairs and the largest group linked by messages, hour by hour
      const hr = (t) => Math.min(n - 1, Math.max(0, Math.floor((t - sim.start_t) / HR)));
      const inc = new Array(n).fill(0), pairs = new Array(n).fill(0), group = new Array(n).fill(0);
      const seen = new Set(), parent = new Map(), size = new Map();
      const find = (x) => { if (!parent.has(x)) { parent.set(x, x); size.set(x, 1); } while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
      let big = 0;
      D.named.slice().sort((a, b) => a[6] - b[6]).forEach((r) => {
        const k = hr(r[6]); inc[k] += 1; seen.add(r[0] + "\u0000" + r[1]);
        let a = find(r[0]), b = find(r[1]);
        if (a !== b) { if (size.get(a) > size.get(b)) [a, b] = [b, a]; parent.set(a, b); size.set(b, size.get(a) + size.get(b)); }
        big = Math.max(big, size.get(find(r[1]))); pairs[k] = seen.size; group[k] = big;
      });
      for (let k = 1; k < n; k++) { pairs[k] = Math.max(pairs[k], pairs[k - 1]); group[k] = Math.max(group[k], group[k - 1]); }
      D.cumMsgs = cum(inc); D.pairs = pairs; D.group = group;
    }
    ST.data = D;
    const dh = (deepLink().hour || "").replace("T", " ");
    if (ST.i == null && dh) { const k = Math.floor((toTime(dh) / 1000 - sim.start_t) / HR); if (k >= 0 && k < n) ST.i = k; }
    if (ST.i == null || ST.i >= n) ST.i = n - 1;

    const harmList = (s.harm_names || []).map((k) => human(k)).join(", ");
    el.innerHTML = `
    <h2>Could it have been flagged early?</h2>
    <p class="small muted efdef">${term("harm", "Harmful actions")}: actions of the kinds in the pack's harm list${harmList ? ` (${esc(harmList)})` : ""}. ${term("harm_left", "Harm still to come")}: the share of the ${fmt(sim.harm_total)} dated harmful actions that came after a moment, so a higher share means an earlier warning. Times are UTC and, for most records, ${term("dated", "estimated")} from timestamps in the agents' code; each replay step is one hour (for example 13:00–14:00).</p>
    <div id="efLead"></div>
    ${card("Replay the incident", `
      <div class="efctl">
        <button type="button" id="efPlay" class="primary">▶ Play</button>
        <button type="button" id="efNext" title="Jump to the next warning sign">Next sign ⏭</button>
        <select id="efSpeed" title="Playback speed">${[[150, "fast"], [380, "normal"], [900, "slow"]].map(([v, l]) => `<option value="${v}"${ST.speed === v ? " selected" : ""}>${l}</option>`).join("")}</select>
        <input type="range" id="efSlider" min="0" max="${n - 1}" step="1" value="${ST.i}" aria-label="replay time, one step per hour">
        <span id="efNow" class="efnow"></span>
      </div>
      <div id="efChart"></div>
      <div id="efCounters" class="kpis efkpis"></div>
      <div class="grid2">
        <div><h4>Warning signs</h4><div id="efBoard" class="efboard"></div></div>
        <div><h4>Who had read whom by now</h4><div id="efNet"></div><div id="efNetCap" class="small muted"></div></div>
      </div>
      <p id="efReconcile" class="small muted efrec"></p>
      <h4 style="margin-top:12px">What the tracer would have said <span class="muted small">(newest first)</span></h4>
      <div id="efFeed" class="effeed"></div>`,
      { sub: `Step through the ${plural(n, "hour")} of dated activity, or click the chart to jump to an hour. The line is the share of all ${fmt(sim.harm_total)} dated harmful actions still to come (left scale); it is drawn solid up to the moment shown. Grey bars are actions per hour, orange the harmful ones (their own scale, tallest bar marked). Numbered dots are ${term("sign", "warning signs")}, filled once they have fired. The band under the chart is the tracer's alert level.` })}
    ${card("The tracer's alert rule", `<div id="efRule"></div>`,
      { sub: "A deliberately simple rule. It was not tuned on this data or tested on any other swarm, so treat its timing as an illustration of what a coordination-aware monitor could see, not as a measured detector." })}
    ${card("The whole incident at a glance", `<div id="efWhole"></div>`,
      { sub: "Every signal on one chart: the higher a dot, the more harm was still to come when it fired. Blue: actors working together. Dark grey: a single actor. Light grey: ordinary volume monitoring, for comparison. Each dot sits at its true height; dots that fired close together are spread sideways. The numbers match the table below." })}
    ${card("Every signal", `<div id="efTable"></div>`)}`;

    $("efPlay").addEventListener("click", () => {
      if (ST.playing) { stop(); return; }
      if (ST.i >= n - 1) ST.i = 0;
      ST.playing = true; $("efPlay").innerHTML = "❚❚ Pause";
      update();
      ST.timer = setInterval(() => {
        if (!$("efChart")) { stop(); return; }
        if (ST.i >= n - 1) { stop(); return; }
        ST.i += 1; update();
      }, ST.speed);
    });
    $("efSpeed").addEventListener("change", (e) => { ST.speed = +e.target.value; if (ST.playing) { stop(); $("efPlay").click(); } });
    $("efSlider").addEventListener("input", (e) => { ST.i = +e.target.value; update(); });
    $("efNext").addEventListener("click", () => {
      const now = sim.start_t + (ST.i + 1) * HR;
      const nx = sigs.find((g) => g.t >= now);
      ST.i = nx ? Math.min(n - 1, Math.floor((nx.t - sim.start_t) / HR)) : n - 1;
      update();
    });
    drawRule(); drawLead();
    update();
    const whole = () => drawWhole($("efWhole"), D);
    whole(); onResize($("efWhole"), whole);
    onResize($("efChart"), () => update());
    $("efChart").addEventListener("click", (e) => {
      if (e.target.closest(".node")) return;
      const svg = $("efChart").querySelector("svg"); if (!svg) return;
      const b = svg.getBoundingClientRect(), W = b.width, f = chartFrame(W, 290);
      const x = e.clientX - b.left; if (x < f.x0 || x > f.x1) return;
      stop(); ST.i = Math.min(n - 1, Math.max(0, Math.floor((x - f.x0) / (f.x1 - f.x0) * n))); update();
    });
    drawTable($("efTable"), sigs);
  }

  // ------------------------------------------------------------------ lead and verdict
  function drawLead() {
    const D = ST.data, host = $("efLead");
    if (!host) return;
    const r = rule(D.sigs, ST.N);
    const firstJoint = D.sigs.find((g) => g.family === "joint");
    const tile = (cls, title, g, sub) => `<div class="eftile ${cls}"><div class="eft">${title}</div>${g ? `<b>${esc(when(g.t * 1000))}</b><div class="small">${esc(g.name)}</div>
      ${g.harm_share_after != null ? `<div class="efm">${meter(g.harm_share_after, cls === "alert" ? HARM : cls === "watch" ? "#d39b2c" : BASE, 120)} <b>${pct(g.harm_share_after)}</b> <span class="muted small">harm still to come</span></div>` : ""}` : `<b>never</b><div class="small muted">${sub}</div>`}</div>`;
    const ahead = lead(r.alert, r.baseline);
    host.innerHTML = `
      <p class="lead">${firstJoint ? `The first sign of actors working together, <b>${esc(firstJoint.name.toLowerCase())}</b>, fired ${esc(when(firstJoint.t * 1000))} with ${pct(firstJoint.harm_share_after)} of the timed harm still to come.` : "No sign of actors working together fired."}
      ${r.alert ? ` With the rule below (alert once ${plural(ST.N, "kind")} of coordination ${ST.N === 1 ? "has" : "have"} shown), the tracer raises an alert at <b>${esc(when(r.alert.t * 1000))}</b> with <b>${pct(r.alert.harm_share_after)}</b> still to come${r.baseline ? (ahead > 0 ? `, ${hoursWord(ahead)} before ordinary volume monitoring fires (${pct(r.baseline.harm_share_after)} still to come)` : ahead < 0 ? `, ${hoursWord(-ahead)} after ordinary volume monitoring (${pct(r.baseline.harm_share_after)})` : ", the same hour as volume monitoring") : ""}.` : ` With the rule below the tracer never reaches an alert: fewer than ${ST.N} kinds of coordination showed.`}</p>
      <div class="eftiles">
        ${tile("watch", "Watch: first single-actor harm sign", r.watch, "no harmful action of a known kind")}
        ${tile("alert", `Alert: ${plural(ST.N, "kind")} of coordination`, r.alert, `fewer than ${ST.N} kinds of coordination showed`)}
        ${tile("base", "Volume alarm (baseline)", r.baseline, "no hour stood out from the ones before it")}
      </div>`;
  }

  function drawRule() {
    const D = ST.data, host = $("efRule");
    if (!host) return;
    const rows = [1, 2, 3].map((N) => { const r = rule(D.sigs, N); return { N, r, ahead: lead(r.alert, r.baseline) }; });
    const kindsSeen = [];
    D.sigs.filter((g) => g.family === "joint").forEach((g) => { if (!kindsSeen.find((k) => k.kind === g.kind)) kindsSeen.push(g); });
    host.innerHTML = `
      <div class="efrule">
        <div><b>Watch</b> when the first single-actor harmful sign fires (the first action of a harmful kind).</div>
        <div><b>Alert</b> when signs of at least <span class="efN" role="group" aria-label="number of kinds of coordination needed for an alert">${[1, 2, 3].map((N) => `<button type="button" data-n="${N}" class="${N === ST.N ? "on" : ""}" aria-pressed="${N === ST.N}" aria-label="alert after ${N} kind${N === 1 ? "" : "s"} of coordination">${N}</button>`).join("")}</span> different kinds of coordination have fired: a message between named actors, a program reused by another actor, actors linked into a group, a two-way exchange, a carried token, or a shared place.</div>
      </div>
      <h4 style="margin-top:10px">Kinds of coordination, in the order they first showed</h4>
      ${kindsSeen.length ? `<div class="efkinds">${kindsSeen.map((g, k) => `<div class="efkind"><span class="efk">${k + 1}</span><div><b>${esc(KIND[g.kind] || g.kind)}</b><div class="small muted">${esc(when(g.t * 1000))} · ${pct(g.harm_share_after)} still to come</div></div></div>`).join('<span class="efarr">→</span>')}</div>` : '<p class="muted small">None showed.</p>'}
      <h4 style="margin-top:10px">How the setting changes the alert</h4>
      ${table(["alert after", "alert at", "on the sign", "harm still to come", "compared with the volume alarm"], rows.map(({ N, r, ahead }) => [
        `<b>${plural(N, "kind")}</b>${N === ST.N ? ' <span class="badge">current setting</span>' : ""}`,
        r.alert ? esc(when(r.alert.t * 1000)) : "never",
        r.alert ? esc(r.alert.name) : "–",
        r.alert ? `${meter(r.alert.harm_share_after, HARM, 70)} ${pct(r.alert.harm_share_after)}` : "–",
        r.alert && r.baseline ? (ahead >= 0 ? `${hoursWord(ahead)} earlier` : `${hoursWord(-ahead)} later`) : "–"]))}
      ${sameShare(rows)}`;
    host.querySelectorAll(".efN button").forEach((b) => b.addEventListener("click", () => { ST.N = +b.dataset.n; drawRule(); drawLead(); update(); }));
  }

  // settings that give the same harm share are worth saying out loud
  function sameShare(rows) {
    const groups = new Map();
    rows.filter((x) => x.r.alert).forEach((x) => { const k = pct(x.r.alert.harm_share_after); (groups.get(k) || groups.set(k, []).get(k)).push(x.N); });
    const same = [...groups.entries()].filter(([, Ns]) => Ns.length > 1);
    if (!same.length) return "";
    return `<p class="small muted">${same.map(([k, Ns]) => `${Ns.join(" or ")} kinds give the same ${k} of the harm still to come`).join("; ")}: requiring more kinds of coordination ${rows.some((x) => x.r.alert && !same.some(([, Ns]) => Ns.includes(x.N))) ? "costs little here, and only the strictest setting fires later" : "does not delay the alert here"}.</p>`;
  }

  // ------------------------------------------------------------------ the replay at hour ST.i
  function update() {
    const D = ST.data;
    if (!D || !$("efChart")) return;
    const { sim, sigs, n } = D, i = ST.i, now = sim.start_t + (i + 1) * HR;
    $("efSlider").value = i;
    const r = rule(sigs, ST.N), lvl = levelAt(r, now);
    $("efNow").innerHTML = `<b>${esc(when((now - HR) * 1000))}</b>–${esc(clock(now * 1000))} UTC <span class="eflvl l${lvl}">${LEVEL[lvl].name}</span>`;
    drawChart($("efChart"), D, i, r);
    const fired = sigs.filter((g) => g.t < now);
    const harmLeft = D.hasHarm ? sim.harm_remaining[i] : null;
    const anon = D.anonMsgs.filter((t) => t < now).length, merged = D.mergedNamed.filter((t) => t < now).length;
    $("efCounters").innerHTML = [
      ["actions so far", fmt(D.cumActions[i]), `${pct(D.cumActions[i] / Math.max(1, sim.actions_total))} of all timed actions`],
      ["harmful so far", fmt(D.cumHarm[i]), D.hasHarm ? `${pct(D.cumHarm[i] / sim.harm_total)} of ${fmt(sim.harm_total)}` : "none defined"],
      ["harm still to come", harmLeft != null ? pct(harmLeft) : "–", "after this hour"],
      ["actors seen", fmt(D.cumActors[i]), `${fmt(sim.active_actors[i])} active this hour`],
      ["named messages", fmt(D.cumMsgs[i]), `on exact places; +${fmt(merged)} on merged places, +${fmt(anon)} with anonymous runs`],
      ["sender-receiver pairs", fmt(D.pairs[i]), "between named actors"],
      ["largest linked group", fmt(D.group[i]), "actors joined by messages"],
      ["signs fired", `${fired.length}/${sigs.length}`, `${fired.filter((g) => g.family === "joint").length} of them about actors working together`],
    ].map(([l, v, sub]) => kpi(l, v, esc(sub))).join("");
    const rec = $("efReconcile");
    if (rec) {
      const all = D.named.length + D.mergedNamed.length;
      rec.innerHTML = `The replay counts messages between named actors on exact places, the same set the warning signs use: by the end ${fmt(D.named.length)} of ${fmt(all)} messages and ${fmt(D.pairs[n - 1])} of ${fmt(D.allPairs)} sender-receiver pairs (Who talked to whom counts all ${fmt(all)} and ${fmt(D.allPairs)}). The other ${fmt(D.mergedNamed.length)} are on ${term("merged", "places the redaction may have merged")}; What's missing counts ${fmt(D.mergedAll)} such messages because it includes those with anonymous runs. Grey dots in the network are actors that have not yet exchanged a message.`;
    }
    // signal board
    $("efBoard").innerHTML = sigs.map((g) => {
      const on = g.t < now, c = FAMILY[g.family]?.color || SINGLE;
      return `<div class="efsig${on ? " on" : ""}" data-t="${g.t}"><span class="efnum" style="${on ? `background:${c};color:#fff` : `border-color:${c};color:${c}`}">${g.num}</span>
        <div class="efsm"><div class="efsn">${esc(g.name)}</div><div class="small muted">${esc(when(g.t * 1000))} · ${esc(KIND[g.kind] || g.kind)}${g.harm_share_after != null ? ` · ${pct(g.harm_share_after)} still to come` : ""}</div></div></div>`;
    }).join("") || '<p class="muted small">No warning sign fired.</p>';
    $("efBoard").querySelectorAll(".efsig").forEach((d) => d.addEventListener("click", () => { stop(); ST.i = Math.min(n - 1, Math.max(0, Math.floor((+d.dataset.t - sim.start_t) / HR))); update(); }));
    const onb = $("efBoard").querySelectorAll(".efsig.on");
    if (ST.playing && onb.length) { const last = onb[onb.length - 1]; const b = $("efBoard"); if (last.offsetTop > b.scrollTop + b.clientHeight - 30) b.scrollTop = last.offsetTop - b.clientHeight + 40; }
    drawNet($("efNet"), D, now);
    drawFeed($("efFeed"), D, now, r);
  }

  // dots that would overlap are moved sideways, never up or down: the height is the value
  function spreadX(pts, gap, xmin, xmax) {
    const placed = [];
    pts.forEach((p) => {
      let x = p.x;
      for (let k = 1; k < 24 && placed.some((q) => Math.abs(q.x - x) < gap && Math.abs(q.y - p.y) < gap); k++) {
        x = p.x + Math.ceil(k / 2) * gap * (k % 2 ? 1 : -1);
        if (x < xmin || x > xmax) x = p.x - Math.ceil(k / 2) * gap * (k % 2 ? 1 : -1);
      }
      p.dx = x; placed.push({ x, y: p.y });
    });
    return pts;
  }

  function chartFrame(W, Hh) { return { x0: 44, x1: W - 14, yT: 22, yB: Hh - 52, band: Hh - 46, bandH: 10, axis: Hh - 30 }; }

  function drawChart(host, D, i, r) {
    const { sim, sigs, n } = D;
    const W = Math.max(360, host.clientWidth || 700), Hh = 290, f = chartFrame(W, Hh);
    const t0 = sim.start_t, t1 = sim.start_t + n * HR, now = sim.start_t + (i + 1) * HR;
    const X = (t) => f.x0 + (t - t0) / (t1 - t0) * (f.x1 - f.x0), Y = (v) => f.yB - v * (f.yB - f.yT);
    const mxA = Math.max(1, ...sim.actions), Yb = (v) => f.yB - v / mxA * (f.yB - f.yT) * (D.hasHarm ? 0.3 : 0.9);
    const bw = Math.max(1, (f.x1 - f.x0) / n - 0.6);
    let svg = `<svg class="chart efclick" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Replay of harm still to come with warning signs">`;
    if (D.hasHarm) [0, 0.25, 0.5, 0.75, 1].forEach((v) => { svg += `<line x1="${f.x0}" x2="${f.x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${f.x0 - 7}" y="${Y(v) + 4}" text-anchor="end" font-size="10.5" fill="${QUIET}">${v * 100}%</text>`; });
    // activity per hour
    sim.actions.forEach((a, k) => {
      if (!a) return;
      const x = X(t0 + k * HR), past = k <= i, h = sim.harmful[k] || 0;
      svg += `<g opacity="${past ? 1 : 0.35}"><rect x="${x}" y="${Yb(a)}" width="${bw}" height="${f.yB - Yb(a)}" fill="#cfd6de"><title>${esc(when((t0 + k * HR) * 1000))}: ${fmt(a)} actions, ${fmt(h)} harmful</title></rect>${h ? `<rect x="${x}" y="${Yb(h)}" width="${bw}" height="${f.yB - Yb(h)}" fill="#f0a578" pointer-events="none"/>` : ""}</g>`;
    });
    svg += `<line x1="${f.x1 - 6}" x2="${f.x1}" y1="${Yb(mxA)}" y2="${Yb(mxA)}" stroke="${QUIET}"/><text x="${f.x1 - 9}" y="${Yb(mxA) + 3.5}" text-anchor="end" font-size="9.5" fill="${QUIET}" paint-order="stroke" stroke="#fff" stroke-width="3">bars: tallest ${fmt(mxA)} actions/hour</text>`;
    // harm still to come: solid up to now, faint after
    if (D.hasHarm) {
      const pts = [[t0, 1], ...sim.harm_remaining.map((v, k) => [t0 + (k + 1) * HR, v])];
      const path = (ps) => ps.map(([t, v], k) => `${k ? "L" : "M"}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join("");
      svg += `<path d="${path(pts)}" fill="none" stroke="${CURVE}" stroke-width="2" stroke-dasharray="4 3" opacity=".7"/>`;
      svg += `<path d="${path(pts.slice(0, i + 2))}" fill="none" stroke="#39434e" stroke-width="2.6"/>`;
    }
    // alert band
    for (let k = 0; k < n; k++) {
      const lv = levelAt(r, t0 + (k + 1) * HR);
      svg += `<rect x="${X(t0 + k * HR)}" y="${f.band}" width="${(f.x1 - f.x0) / n + 0.4}" height="${f.bandH}" fill="${LEVEL[lv].color}" opacity="${k <= i ? 1 : 0.3}"/>`;
    }
    svg += `<text x="${f.x0 - 7}" y="${f.band + 8.5}" text-anchor="end" font-size="9.5" fill="${QUIET}">alert</text>`;
    svg += `<line x1="${f.x0}" x2="${f.x1}" y1="${f.yB}" y2="${f.yB}" stroke="${AXIS}"/>`;
    timeTicks(t0 * 1000, t1 * 1000, Math.max(3, Math.floor((f.x1 - f.x0) / 90))).forEach((k) => { const x = X(k.t / 1000); svg += `<line x1="${x}" x2="${x}" y1="${f.band + f.bandH}" y2="${f.axis - 6}" stroke="${AXIS}"/><text x="${x}" y="${f.axis + 8}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${esc(k.label)}</text>`; });
    // now line
    const xn = X(now);
    svg += `<line x1="${xn}" x2="${xn}" y1="${f.yT - 14}" y2="${f.band + f.bandH}" stroke="${ACCENT}" stroke-width="1.4" stroke-dasharray="3 2"/>`;
    const lbl = when(now * 1000), lw = textWidth(lbl, "600 11px -apple-system, system-ui, sans-serif") + 10;
    const lx = Math.min(f.x1 - lw, Math.max(f.x0, xn - lw / 2));
    svg += `<rect x="${lx}" y="${f.yT - 22}" width="${lw}" height="15" rx="4" fill="${ACCENT}"/><text x="${lx + lw / 2}" y="${f.yT - 11}" text-anchor="middle" font-size="11" font-weight="600" fill="#fff">${esc(lbl)}</text>`;
    // signal dots, numbered, at their true height; dots that share a spot are spread sideways
    const pts = sigs.filter((g) => g.t >= t0 && g.t <= t1 + HR).map((g) => ({ g, x: X(Math.min(g.t, t1)), y: D.hasHarm && g.harm_share_after != null ? Y(g.harm_share_after) : f.yT + 8 }));
    spreadX(pts, 15, f.x0 + 4, f.x1 - 4).forEach(({ g, x, y, dx }) => {
      const on = g.t < now, c = FAMILY[g.family]?.color || SINGLE;
      if (Math.abs(dx - x) > 1) svg += `<line x1="${x}" x2="${dx}" y1="${y}" y2="${y}" stroke="${c}" stroke-opacity=".35"/>`;
      svg += `<g class="node"${recOf(g) ? ` data-id="${esc(recOf(g))}"` : ""}><circle cx="${dx}" cy="${y}" r="7.5" fill="${on ? c : "#fff"}" stroke="${c}" stroke-width="1.5" opacity="${on ? 1 : 0.6}"/><text x="${dx}" y="${y + 3.3}" text-anchor="middle" font-size="9" font-weight="700" fill="${on ? "#fff" : c}" pointer-events="none">${g.num}</text><title>${g.num}. ${esc(g.name)} · ${esc(g.time)} UTC${g.harm_share_after != null ? ` · ${pct(g.harm_share_after)} of harm still to come` : ""}</title></g>`;
    });
    host.innerHTML = svg + "</svg>" + `<div class="legend"><span><i style="background:${ACCENT};border-radius:50%"></i>actors together</span><span><i style="background:${SINGLE};border-radius:50%"></i>single actor</span><span><i style="background:${BASE};border-radius:50%"></i>volume baseline</span><span><i style="background:#cfd6de"></i>actions per hour</span><span><i style="background:#f0a578"></i>harmful actions</span><span><i style="background:${LEVEL[1].color}"></i>watch</span><span><i style="background:${HARM}"></i>alert</span></div>`;
  }

  // ------------------------------------------------------------------ network snapshot
  function netLayout(named) {
    const deg = new Map(), pairs = new Map();
    named.forEach((r) => { deg.set(r[0], (deg.get(r[0]) || 0) + 1); deg.set(r[1], (deg.get(r[1]) || 0) + 1); const k = r[0] < r[1] ? r[0] + "\u0000" + r[1] : r[1] + "\u0000" + r[0]; pairs.set(k, (pairs.get(k) || 0) + 1); });
    const nodes = [...deg.keys()];
    const idx = new Map(nodes.map((a, k) => [a, k]));
    const edges = [...pairs.keys()].map((k) => k.split("\u0000").map((a) => idx.get(a)));
    const N = nodes.length, W = 1, Hh = 0.72, kk = Math.sqrt(W * Hh / Math.max(1, N)) * 0.9;
    const P = nodes.map((_, k) => ({ x: 0.5 + 0.35 * Math.cos(2 * Math.PI * k / Math.max(1, N)), y: Hh / 2 + 0.25 * Math.sin(2 * Math.PI * k / Math.max(1, N)) }));
    for (let it = 0; it < 320; it++) {
      const d = P.map(() => ({ x: 0, y: 0 }));
      for (let a = 0; a < N; a++) for (let b = a + 1; b < N; b++) {
        let dx = P[a].x - P[b].x, dy = P[a].y - P[b].y; const dist = Math.max(0.005, Math.hypot(dx, dy)), fr = kk * kk / dist;
        dx /= dist; dy /= dist; d[a].x += dx * fr; d[a].y += dy * fr; d[b].x -= dx * fr; d[b].y -= dy * fr;
      }
      edges.forEach(([a, b]) => {
        let dx = P[a].x - P[b].x, dy = P[a].y - P[b].y; const dist = Math.max(0.005, Math.hypot(dx, dy)), fa = dist * dist / kk;
        dx /= dist; dy /= dist; d[a].x -= dx * fa; d[a].y -= dy * fa; d[b].x += dx * fa; d[b].y += dy * fa;
      });
      const temp = 0.06 * (1 - it / 320) + 0.002;
      P.forEach((p, k) => {
        d[k].x -= (p.x - 0.5) * 0.9 * kk; d[k].y -= (p.y - Hh / 2) * 0.9 * kk;
        const m = Math.hypot(d[k].x, d[k].y) || 1;
        p.x += d[k].x / m * Math.min(m, temp); p.y += d[k].y / m * Math.min(m, temp);
      });
    }
    const xs = P.map((p) => p.x), ys = P.map((p) => p.y);
    const [ax, bx, ay, by] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    return new Map(nodes.map((a, k) => [a, { x: (P[k].x - ax) / Math.max(1e-6, bx - ax), y: (P[k].y - ay) / Math.max(1e-6, by - ay) }]));
  }

  function drawNet(host, D, now) {
    if (!host) return;
    if (!D.named.length) { host.innerHTML = '<p class="muted small">No message between two named actors.</p>'; $("efNetCap").textContent = ""; return; }
    const W = Math.max(260, host.clientWidth || 300), Hh = Math.round(Math.min(300, Math.max(200, W * 0.62))), m = 16;
    const P = (a) => { const p = D.layout.get(a); return [m + p.x * (W - 2 * m), m + p.y * (Hh - 2 * m)]; };
    const seen = D.named.filter((r) => r[6] < now);
    const edges = new Map(), cnt = new Map(), recent = now - 6 * HR, fresh = new Set();
    seen.forEach((r) => {
      const k = r[0] + "\u0000" + r[1]; const e = edges.get(k) || { a: r[0], b: r[1], n: 0, last: 0 };
      e.n += 1; e.last = Math.max(e.last, r[6]); edges.set(k, e);
      cnt.set(r[0], (cnt.get(r[0]) || 0) + 1); cnt.set(r[1], (cnt.get(r[1]) || 0) + 1);
      if (r[6] >= now - HR) { fresh.add(r[0]); fresh.add(r[1]); }
    });
    let svg = `<svg class="chart efnet" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Messages between named actors read by now"><defs><marker id="efah" viewBox="0 0 10 10" refX="10" refY="5" markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1L10,5L0,9z" fill="${ACCENT}"/></marker></defs>`;
    // all actors that will ever talk, as faint placeholders
    D.layout.forEach((_, a) => { if (!cnt.has(a)) { const [x, y] = P(a); svg += `<circle cx="${x}" cy="${y}" r="2.2" fill="#d6dce3"/>`; } });
    edges.forEach((e) => {
      const [x1, y1] = P(e.a), [x2, y2] = P(e.b), dd = Math.hypot(x2 - x1, y2 - y1) || 1;
      const rb = 3 + Math.sqrt(cnt.get(e.b)) * 1.2 + 2;
      const ex = x2 - (x2 - x1) / dd * rb, ey = y2 - (y2 - y1) / dd * rb, hot = e.last >= recent;
      svg += `<line x1="${x1}" y1="${y1}" x2="${ex}" y2="${ey}" stroke="${hot ? ACCENT : "#9fb6cf"}" stroke-opacity="${hot ? 0.9 : 0.55}" stroke-width="${Math.min(4, 0.9 + Math.log2(1 + e.n))}" marker-end="url(#efah)"><title>${esc(short(e.a))} → ${esc(short(e.b))}: ${plural(e.n, "message")} by now</title></line>`;
    });
    const top = [...cnt.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7).map(([a]) => a);
    cnt.forEach((c, a) => {
      const [x, y] = P(a), r = 3 + Math.sqrt(c) * 1.2;
      svg += `<circle class="node" data-actor="${esc(a)}" cx="${x}" cy="${y}" r="${r}" fill="${C.actorBg}" stroke="${fresh.has(a) ? HARM : C.actor}" stroke-width="${fresh.has(a) ? 2.2 : 1.3}"/>`;
    });
    const boxes = [];
    top.forEach((a) => {
      const [x, y] = P(a), r = 3 + Math.sqrt(cnt.get(a)) * 1.2, label = short(a), w = textWidth(label, "10px -apple-system, system-ui, sans-serif");
      const anchor = x > W - 60 ? "end" : x < 60 ? "start" : "middle";
      const bx = anchor === "end" ? x - w : anchor === "start" ? x : x - w / 2, by = y - r - 13;
      if (boxes.some((b) => bx < b[0] + b[2] + 3 && b[0] < bx + w + 3 && by < b[1] + 12 && b[1] < by + 12)) return;
      boxes.push([bx, by, w]);
      svg += `<text x="${x}" y="${y - r - 3}" text-anchor="${anchor}" font-size="10" fill="#3d4a58" pointer-events="none" paint-order="stroke" stroke="#fff" stroke-width="3">${esc(label)}</text>`;
    });
    host.innerHTML = svg + "</svg>";
    $("efNetCap").innerHTML = `${plural(cnt.size, "named actor")}, ${plural(seen.length, "message")} in ${plural(edges.size, "pair")} by now (exact places). Grey dots: actors not yet in a message. Blue arrows: read in the last 6 hours. Red ring: active in the last hour.`;
  }

  // ------------------------------------------------------------------ explanation feed
  function drawFeed(host, D, now, r) {
    if (!host) return;
    const items = [];
    D.sigs.filter((g) => g.t < now).forEach((g) => items.push({ t: g.t, html: `<span class="efnum sm" style="background:${FAMILY[g.family]?.color};color:#fff">${g.num}</span><div><b>${esc(g.name)}</b> <span class="muted small">${esc(FAMILY[g.family]?.label || "")}</span><div class="small">${esc(plain(g.why))}.${g.harm_share_after != null ? ` <b>${pct(g.harm_share_after)}</b> of the harm was still to come.` : ""}${g.kind === "token" ? ` <span class="muted">${esc(TOKEN_NOTE)}</span>` : ""}</div><div class="chips">${(g.actors || []).filter((a) => a && !/ carried /.test(a)).slice(0, 4).map((a) => ent.actor(a)).join(" ")} ${refChip(g)}</div></div>` }));
    (D.sim.phases || []).forEach((p) => { const t = toTime(p.time) / 1000; if (t < now) items.push({ t, range: true, html: `<span class="efnum sm ph">◷</span><div><b>${esc(p.name)}</b> <span class="muted small">(in the hour ${esc(hourRange(t * 1000))})</span><div class="small muted">${esc(p.why || PHASE_WHY[p.key] || "")}</div></div>` }); });
    if (r.watch && r.watch.t < now) items.push({ t: r.watch.t + 0.1, html: `<span class="efnum sm lv1">!</span><div><b>Tracer: watch</b><div class="small">A harmful action of a known kind appeared (${esc(r.watch.name.toLowerCase())}). One actor acting alone; keep watching for actors working together.</div></div>` });
    if (r.alert && r.alert.t < now) items.push({ t: r.alert.t + 0.2, html: `<span class="efnum sm lv2">!!</span><div><b>Tracer: alert</b><div class="small">${plural(r.alert.kinds.length, "kind")} of coordination now seen: ${esc(r.alert.kinds.map((k) => KIND[k] || k).join(", "))}. ${pct(r.alert.harm_share_after)} of the timed harm was still to come.</div></div>` });
    items.sort((a, b) => b.t - a.t);
    host.innerHTML = items.length ? items.map((x) => `<div class="effi"><span class="eftime">${esc(when(x.t * 1000))}</span>${x.html}</div>`).join("") : '<p class="muted small">Nothing yet. Press play.</p>';
  }

  // ------------------------------------------------------------------ the whole incident
  function drawWhole(host, D) {
    if (!host) return;
    const { sim, sigs, n } = D;
    if (!D.hasHarm) { host.innerHTML = '<p class="muted small">No harmful actions are defined or timed in this trace, so "harm still to come" cannot be drawn.</p>'; return; }
    const W = Math.max(360, host.clientWidth || 700), Hh = Math.round(Math.min(400, Math.max(300, W * 0.5)));
    const x0 = 46, x1 = W - 16, yT = 18, yB = Hh - 34;
    const t0 = sim.start_t - 1800, t1 = sim.start_t + n * HR;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0), Y = (v) => yB - v * (yB - yT);
    const pts = [[sim.start_t, 1], ...sim.harm_remaining.map((v, k) => [sim.start_t + (k + 1) * HR, v])].map(([t, v]) => ({ x: X(t), y: Y(v), t, v }));
    const dots = spreadX(sigs.filter((g) => g.harm_share_after != null).map((g) => ({ g, x: X(g.t), y: Y(g.harm_share_after) })), 18, x0 + 8, x1 - 8);
    let svg = `<svg class="chart" width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Share of harmful activity still to come, with the first time each warning sign fired">`;
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => { svg += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="${QUIET}">${v * 100}%</text>`; });
    svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    timeTicks(t0 * 1000, t1 * 1000, Math.max(3, Math.floor((x1 - x0) / 90))).forEach((k) => { const x = X(k.t / 1000); svg += `<line x1="${x}" x2="${x}" y1="${yB}" y2="${yB + 5}" stroke="${AXIS}"/><text x="${x}" y="${yB + 19}" text-anchor="middle" font-size="11" fill="${QUIET}">${esc(k.label)}</text>`; });
    svg += `<path d="${pts.map((p, k) => `${k ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join("")}" fill="none" stroke="${CURVE}" stroke-width="2.5"/>`;
    dots.forEach(({ g, x, y, dx }) => {
      const c = FAMILY[g.family]?.color || SINGLE;
      if (Math.abs(dx - x) > 1) svg += `<line x1="${x}" x2="${dx}" y1="${y}" y2="${y}" stroke="${c}" stroke-opacity=".4"/><circle cx="${x}" cy="${y}" r="2" fill="${c}"/>`;
      svg += `<g class="node"${recOf(g) ? ` data-id="${esc(recOf(g))}"` : ""}><circle cx="${dx}" cy="${y}" r="8.5" fill="${c}" stroke="#fff" stroke-width="1.5"/><text x="${dx}" y="${y + 3.4}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#fff" pointer-events="none">${g.num}</text><title>${g.num}. ${esc(g.name)}, ${esc(g.time)} UTC: ${pct(g.harm_share_after)} of the harm still to come</title></g>`;
    });
    host.innerHTML = svg + "</svg>" + `<div class="legend"><span><i style="background:${ACCENT};border-radius:50%"></i>actors together</span><span><i style="background:${SINGLE};border-radius:50%"></i>single actor</span><span><i style="background:${BASE};border-radius:50%"></i>volume baseline</span><span><i style="background:${CURVE}"></i>share of timed harmful actions still to come (${fmt(sim.harm_total)} in all)</span></div>`;
  }

  function drawTable(host, sigs) {
    if (!host) return;
    host.innerHTML = table(["#", "signal", "first fired", "harm still to come", "record", "why it counts"], sigs.map((g) => [
      `<span class="efnum sm" style="background:${FAMILY[g.family]?.color};color:#fff">${g.num}</span>`,
      `<b>${esc(g.name)}</b><div class="small muted">${esc(FAMILY[g.family]?.label || g.family)} · ${esc(KIND[g.kind] || g.kind)}</div>${(g.actors || []).length ? `<div class="chips">${g.actors.filter((a) => a && !/ carried /.test(a)).slice(0, 3).map((a) => ent.actor(a)).join(" ")}</div>` : ""}`,
      `<span class="nowrap">${esc(when(g.t * 1000))}</span>`,
      g.harm_share_after != null ? `<span class="nowrap">${meter(g.harm_share_after, FAMILY[g.family]?.color, 46)} ${pct(g.harm_share_after)}</span>` : "–",
      refChip(g), `<span class="small">${esc(plain(g.why))}${g.kind === "token" ? `. <span class="muted">${esc(TOKEN_NOTE)}</span>` : ""}</span>`]));
  }

  VIEWS.early = view;
})();

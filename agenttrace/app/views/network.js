// Who talked to whom: findings, the full graph of every message, a time scrubber, the matrix of
// every sender-receiver pair, a table of every actor, and the conversation behind any pair.
(() => {
"use strict";
const isNamed = (a) => !String(a).startsWith("run:");
const isoHour = (sec) => new Date(sec * 1000).toISOString().slice(0, 13).replace("T", " ");
const ROLES = [
  { label: "only sends", fill: "#e3a43b" },
  { label: "sends and receives", fill: ACCENT },
  { label: "only receives", fill: "#8f9aa6" },
];
const RUN_FILL = "#ffffff", RUN_STROKE = "#9aa5b1", RUN_EDGE = "#aab3bc";   // anonymous runs: hollow, so they never read as "only receives"
const NW = { mode: "named", T: null, playing: false, raf: 0, noMerged: false, mergedByPair: new Map() };   // kept across redraws and tab switches
const MERGED_TIP = "On a place the redaction may have merged: it kept only the owner's name, so the write and the read may be on two different repositories.";
const CAP_LABELS = 70, CAP_MATRIX = 60;

// ------------------------------------------------------------------ data
function prepare(raw) {
  const ix = Object.fromEntries(raw.columns.map((c, i) => [c, i]));
  const msgs = raw.rows.map((r) => ({ from: r[ix.from], to: r[ix.to], ch: r[ix.channel], w: r[ix.write_id], r: r[ix.read_id],
    wt: r[ix.write_t], rt: r[ix.read_t], lat: r[ix.latency_h], how: r[ix.how] || "unknown", merged: !!r[ix.merged] }))
    .filter((m) => m.rt != null).sort((a, b) => a.rt - b.rt);
  return { msgs, named: msgs.filter((m) => isNamed(m.from) && isNamed(m.to)) };
}

function buildGraph(msgs) {
  const nodes = new Map(), edges = new Map();
  const node = (id) => {
    let n = nodes.get(id);
    if (!n) { n = { id, named: isNamed(id), sent: 0, recv: 0, out: new Set(), inn: new Set(), first: Infinity, last: -Infinity, hours: new Map() }; nodes.set(id, n); }
    return n;
  };
  for (const m of msgs) {
    const a = node(m.from), b = node(m.to);
    a.sent++; b.recv++; a.out.add(m.to); b.inn.add(m.from);
    for (const x of [a, b]) {
      x.first = Math.min(x.first, m.rt); x.last = Math.max(x.last, m.rt);
      const h = isoHour(m.rt); x.hours.set(h, (x.hours.get(h) || 0) + 1);
    }
    const k = m.from + "\u0001" + m.to;
    let e = edges.get(k);
    if (!e) { e = { a: m.from, b: m.to, n: 0, merged: 0, times: [], first: m.rt, ch: new Set(), key: k }; edges.set(k, e); }
    e.n++; e.times.push(m.rt); e.ch.add(m.ch); if (m.merged) e.merged++;
  }
  for (const n of nodes.values()) {
    n.total = n.sent + n.recv;
    n.partners = new Set([...n.out, ...n.inn]).size;
    n.role = n.sent && n.recv ? 1 : n.sent ? 0 : 2;
  }
  // groups: actors connected by any message, biggest first
  const root = new Map();
  const find = (x) => { while (root.get(x) !== x) { root.set(x, root.get(root.get(x))); x = root.get(x); } return x; };
  for (const id of nodes.keys()) root.set(id, id);
  for (const e of edges.values()) { const ra = find(e.a), rb = find(e.b); if (ra !== rb) root.set(ra, rb); }
  const byRoot = new Map();
  for (const id of nodes.keys()) { const r = find(id); if (!byRoot.has(r)) byRoot.set(r, []); byRoot.get(r).push(id); }
  const msgsOf = (ids) => ids.reduce((s, id) => s + nodes.get(id).sent, 0);
  const groups = [...byRoot.values()].map((ids) => ids.sort((x, y) => nodes.get(y).total - nodes.get(x).total || (x < y ? -1 : 1)))
    .sort((x, y) => y.length - x.length || msgsOf(y) - msgsOf(x));
  groups.forEach((ids, gi) => ids.forEach((id) => (nodes.get(id).group = gi + 1)));
  return { nodes, edges, groups };
}

// how often an actor sits on the shortest route between two others (Brandes, undirected)
function betweenness(G) {
  const ids = [...G.nodes.keys()], n = ids.length, idx = new Map(ids.map((id, i) => [id, i]));
  const adj = ids.map(() => new Set());
  for (const e of G.edges.values()) { const a = idx.get(e.a), b = idx.get(e.b); if (a !== b) { adj[a].add(b); adj[b].add(a); } }
  const A = adj.map((s) => [...s]);
  const cb = new Float64Array(n), sigma = new Float64Array(n), dist = new Int32Array(n), delta = new Float64Array(n);
  let sources = [...Array(n).keys()], scale = 1;
  if (n > 1500) { const rnd = rng(7); sources = sources.map((i) => [rnd(), i]).sort((p, q) => p[0] - q[0]).slice(0, 400).map((p) => p[1]); scale = n / 400; }
  for (const s of sources) {
    const stack = [], pred = new Map();
    sigma.fill(0); dist.fill(-1); sigma[s] = 1; dist[s] = 0;
    const q = [s];
    for (let h = 0; h < q.length; h++) {
      const v = q[h]; stack.push(v);
      for (const w of A[v]) {
        if (dist[w] < 0) { dist[w] = dist[v] + 1; q.push(w); }
        if (dist[w] === dist[v] + 1) { sigma[w] += sigma[v]; if (!pred.has(w)) pred.set(w, []); pred.get(w).push(v); }
      }
    }
    delta.fill(0);
    while (stack.length) {
      const w = stack.pop();
      for (const v of pred.get(w) || []) delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w]);
      if (w !== s) cb[w] += delta[w];
    }
  }
  const pairs = ((n - 1) * (n - 2)) / 2;
  ids.forEach((id, i) => { const x = G.nodes.get(id); x.btw = (cb[i] * scale) / 2; x.btwShare = pairs > 0 ? x.btw / pairs : 0; });
  [...G.nodes.values()].sort((a, b) => b.btw - a.btw || b.total - a.total).forEach((x, i) => (x.btwRank = x.btw > 0 ? i + 1 : null));
  return { estimated: n > 1500 };
}

// how many pieces an actor's group falls into without it
function splitWithout(G, id) {
  const g = G.groups[G.nodes.get(id).group - 1].filter((x) => x !== id);
  const set = new Set(g), seen = new Set();
  const adj = new Map(g.map((x) => [x, []]));
  for (const e of G.edges.values()) if (set.has(e.a) && set.has(e.b)) { adj.get(e.a).push(e.b); adj.get(e.b).push(e.a); }
  let parts = 0;
  for (const x of g) {
    if (seen.has(x)) continue;
    parts++;
    const st = [x]; seen.add(x);
    while (st.length) { const v = st.pop(); for (const w of adj.get(v)) if (!seen.has(w)) { seen.add(w); st.push(w); } }
  }
  return parts;
}

function rng(seed) {
  return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ------------------------------------------------------------------ findings
function findings(G, all, named) {
  const N = [...G.nodes.values()];
  if (!N.length) return "";
  const cards = [];
  const chip = (id) => ent.actor(id);
  const more = (ids, k) => ids.slice(0, k).map(chip).join(" ") + (ids.length > k ? ` <span class="muted small">+${fmt(ids.length - k)} more</span>` : "");
  const hub = [...N].sort((a, b) => b.partners - a.partners || b.total - a.total)[0];
  cards.push({ big: fmt(hub.partners), unit: "partners", title: "Biggest hub",
    text: `${chip(hub.id)} exchanged messages with ${plural(hub.partners, "other named actor")}: sent ${fmt(hub.sent)} to them and received ${fmt(hub.recv)} from them.` });
  const br = [...N].sort((a, b) => b.btw - a.btw)[0];
  if (br && br.btw > 0) {
    const parts = splitWithout(G, br.id);
    cards.push({ big: pct(br.btwShare), unit: "of routes", title: "Top " + term("broker", "broker"),
      text: `${chip(br.id)} sits on the shortest chain of messages between ${pct(br.btwShare)} of the other pairs of named actors (direction ignored).${parts > 1 ? ` Without it, its ${term("group", "group")} falls into ${fmt(parts)} pieces.` : ` Its ${term("group", "group")} stays connected without it.`}` });
  }
  const g0 = G.groups[0];
  cards.push({ big: fmt(g0.length), unit: `of ${fmt(N.length)} actors in messages`, title: "Largest " + term("group", "group"),
    text: `${G.groups.length === 1 ? `Every one of the ${fmt(N.length)} actors that exchanged messages is linked to every other through a chain of messages (in either direction).` : `The biggest of ${fmt(G.groups.length)} separate groups of actors linked by messages.`} Busiest members: ${more(g0, 4)}` });
  const two = [];
  for (const e of G.edges.values()) { const back = G.edges.get(e.b + "\u0001" + e.a); if (back && e.a < e.b) two.push([e, back]); }
  two.sort((p, q) => (q[0].n + q[1].n) - (p[0].n + p[1].n));
  cards.push({ big: fmt(two.length), unit: "pairs both ways", title: "Two-way pairs",
    text: two.length ? `Pairs of actors where each side read the other at least once. They account for ${fmt(two.length * 2)} of the ${fmt(G.edges.size)} one-way sender→receiver pairs. Busiest: ${chip(two[0][0].a)} ⇄ ${chip(two[0][0].b)}, ${fmt(two[0][0].n)} and ${fmt(two[0][1].n)} messages.` : "No pair read each other: every exchange runs one way." });
  // places the redaction may have merged can join two different places, so prefer a relay on an exact place
  const exact = named.filter((m) => !m.merged);
  const fast = [...(exact.length ? exact : named)].sort((a, b) => a.lat - b.lat || a.rt - b.rt)[0];
  if (fast) cards.push({ big: hoursWord(fast.lat) === "0 min" ? "<1 min" : hoursWord(fast.lat), unit: "from write to read", title: "Fastest relay" + (exact.length ? " (exact place)" : ""),
    text: `${chip(fast.to)} read what ${chip(fast.from)} wrote to ${ent.place(fast.ch)} ${fast.lat < 1 / 60 ? "within a minute" : hoursWord(fast.lat) + " later"} (${ent.rec(fast.w)} → ${ent.rec(fast.r)}).` });
  const how = {};
  all.forEach((m) => { const k = m.how.startsWith("kept ") ? "kept earlier content" : m.how; how[k] = (how[k] || 0) + 1; });
  const code = how["read in code"] || 0;
  const HOWC = { "read in code": ACCENT, "named the place": "#e3a43b", "posted after it": "#b8579a", "kept earlier content": "#0f766e" };
  cards.push({ big: pct(all.length ? code / all.length : 0), unit: "read in code", title: "Evidence behind each message",
    text: (code === all.length ? `All ${fmt(all.length)} messages rest on a read in the reader's code: it names the place without write code nearby (see ${term("write", "write / read")}).` : `${fmt(code)} of ${fmt(all.length)} messages rest on a read in the reader's code; the rest on weaker signs (the place is only named, or posted to after the write).`) +
      stackbar(Object.entries(how).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v, color: HOWC[k] || BASE })), { h: 7 }) });
  return `<div class="nw-finds">${cards.map((c) => `<div class="nw-find"><div class="nw-ft">${c.title.includes("<") ? c.title : esc(c.title)}</div><div class="nw-fb"><b>${c.big}</b><span>${esc(c.unit)}</span></div><div class="nw-fx">${c.text}</div></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ force layout, computed once per size and frozen
// Groups of four or more actors are laid out by a force model; small groups that only talk among
// themselves (often pairs of anonymous runs) are lined up in a strip below, so they do not shrink the rest.
function layout(G, W, H, radius, gap = 3) {
  const big = G.groups.filter((g) => g.length >= 4);
  const major = big.length ? big : G.groups;
  const minor = big.length ? G.groups.filter((g) => g.length < 4) : [];
  const out = new Map();
  // the strip of small groups
  let stripH = 0;
  if (minor.length) {
    const pad = 14, rowH = 16, gap = 9;
    let x = pad, rows = 1;
    const spots = [];
    for (const g of minor) {
      const w = (g.length - 1) * 9;
      if (x + w > W - pad) { x = pad; rows++; }
      g.forEach((id, i) => spots.push([id, x + i * 9, rows - 1]));
      x += w + gap + 6;
    }
    stripH = rows * rowH + 26;
    spots.forEach(([id, sx, row]) => out.set(id, { x: sx + 3, y: H + 22 + row * rowH, r: radius(G.nodes.get(id)) }));
  }
  const ids = major.flat().sort();
  const n = ids.length, idx = new Map(ids.map((id, i) => [id, i]));
  const L = 1000, rnd = rng(42);
  const x = new Float64Array(n), y = new Float64Array(n), dx = new Float64Array(n), dy = new Float64Array(n);
  // each group starts in its own patch, so separate groups do not tangle
  const gk = Math.ceil(Math.sqrt(major.length));
  const gi = new Map(); major.forEach((g, i) => g.forEach((id) => gi.set(id, i)));
  ids.forEach((id, i) => {
    const g = gi.get(id), gx = g % gk, gy = Math.floor(g / gk);
    const huge = major[g].length > n * 0.3;
    x[i] = huge ? L / 2 + (rnd() - 0.5) * L * 0.6 : ((gx + 0.5) / gk) * L + (rnd() - 0.5) * (L / gk) * 0.5;
    y[i] = huge ? L / 2 + (rnd() - 0.5) * L * 0.6 : ((gy + 0.5) / gk) * L + (rnd() - 0.5) * (L / gk) * 0.5;
  });
  const E = [...G.edges.values()].filter((e) => idx.has(e.a) && idx.has(e.b)).map((e) => [idx.get(e.a), idx.get(e.b), 1 + 0.25 * Math.log(e.n)]);
  const k = (L / Math.sqrt(Math.max(1, n))) * 0.75, k2 = k * k, grav = (0.9 * k) / L;
  const iters = n > 1200 ? 120 : n > 400 ? 200 : 320;
  const useGrid = n > 500, cell = 2.5 * k;
  for (let it = 0; it < iters && n > 1; it++) {
    dx.fill(0); dy.fill(0);
    const rep = (i, j) => {
      let ux = x[i] - x[j], uy = y[i] - y[j], d2 = ux * ux + uy * uy;
      if (d2 < 0.01) { ux = rnd() - 0.5; uy = rnd() - 0.5; d2 = 0.5; }
      const f = k2 / d2; dx[i] += ux * f; dy[i] += uy * f; dx[j] -= ux * f; dy[j] -= uy * f;
    };
    if (!useGrid) {
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) rep(i, j);
    } else {
      const grid = new Map();
      for (let i = 0; i < n; i++) { const key = Math.floor(x[i] / cell) + "," + Math.floor(y[i] / cell); if (!grid.has(key)) grid.set(key, []); grid.get(key).push(i); }
      for (let i = 0; i < n; i++) {
        const cx = Math.floor(x[i] / cell), cy = Math.floor(y[i] / cell);
        for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (const j of grid.get(cx + a + "," + (cy + b)) || []) if (j > i) rep(i, j);
      }
    }
    for (const [a, b, w] of E) {
      if (a === b) continue;
      const ux = x[a] - x[b], uy = y[a] - y[b], d = Math.sqrt(ux * ux + uy * uy) || 0.01;
      const f = (d / k) * w; dx[a] -= ux * f; dy[a] -= uy * f; dx[b] += ux * f; dy[b] += uy * f;
    }
    const temp = (L / 9) * (1 - it / iters) + 1;
    for (let i = 0; i < n; i++) {
      dx[i] -= ((x[i] - L / 2) * grav * k) / 10; dy[i] -= ((y[i] - L / 2) * grav * k) / 10;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1, m = Math.min(d, temp);
      x[i] += (dx[i] / d) * m; y[i] += (dy[i] / d) * m;
    }
  }
  // fit the box, then push apart circles that still overlap
  const pad = 34;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) { x0 = Math.min(x0, x[i]); x1 = Math.max(x1, x[i]); y0 = Math.min(y0, y[i]); y1 = Math.max(y1, y[i]); }
  const sx = (W - 2 * pad) / Math.max(1, x1 - x0), sy = (H - 2 * pad) / Math.max(1, y1 - y0);
  const s = Math.min(sx, sy), sxx = Math.min(sx, s * 1.5), syy = Math.min(sy, s * 1.5);
  const ox = (W - (x1 - x0) * sxx) / 2, oy = (H - (y1 - y0) * syy) / 2;
  const px = new Float64Array(n), py = new Float64Array(n), r = ids.map((id) => radius(G.nodes.get(id)));
  for (let i = 0; i < n; i++) { px[i] = ox + (x[i] - x0) * sxx; py[i] = oy + (y[i] - y0) * syy; }
  if (n <= 900) {
    for (let it = 0; it < 80; it++) {
      let moved = false;
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        const ux = px[i] - px[j], uy = py[i] - py[j], d = Math.sqrt(ux * ux + uy * uy) || 0.01;
        const need = r[i] + r[j] + (G.nodes.get(ids[i]).named && G.nodes.get(ids[j]).named ? gap : 3);
        if (d < need) { const m = (need - d) / 2, vx = ux / d, vy = uy / d; px[i] += vx * m; py[i] += vy * m; px[j] -= vx * m; py[j] -= vy * m; moved = true; }
      }
      if (!moved) break;
    }
  }
  ids.forEach((id, i) => out.set(id, { x: Math.max(r[i] + 2, Math.min(W - r[i] - 2, px[i])), y: Math.max(r[i] + 2, Math.min(H - r[i] - 2, py[i])), r: r[i] }));
  return { pos: out, H: H + stripH, strip: minor.length ? { y: H, groups: minor.length, actors: minor.reduce((a, g) => a + g.length, 0) } : null };
}

// labels beside their dots, never on top of each other or of another dot
function labelSpots(items, pos, W, H, blocked = [], mustLabel = 12) {
  const placed = blocked.slice(), font = "11px -apple-system, system-ui, sans-serif";
  const dots = [...pos.values()];
  const overLabel = (b) => placed.some((p) => b.x < p.x + p.w + 2 && p.x < b.x + b.w + 2 && b.y < p.y + p.h + 1 && p.y < b.y + b.h + 1);
  const overDot = (b) => dots.some((d) => d.x + d.r > b.x && d.x - d.r < b.x + b.w && d.y + d.r > b.y && d.y - d.r < b.y + b.h);
  const spots = (p, w, h, g) => [[p.x + g, p.y - h / 2], [p.x - g - w, p.y - h / 2], [p.x - w / 2, p.y - g - h], [p.x - w / 2, p.y + g],
    [p.x + g * 0.7, p.y - g * 0.7 - h], [p.x - g * 0.7 - w, p.y - g * 0.7 - h], [p.x + g * 0.7, p.y + g * 0.7], [p.x - g * 0.7 - w, p.y + g * 0.7]];
  items.forEach((it, rank) => {
    const p = pos.get(it.id); if (!p) return;
    const w = textWidth(it.text, font) + 2, h = 12, g = p.r + 3;
    const inside = (b) => b.x >= 1 && b.y >= 1 && b.x + w <= W - 1 && b.y + h <= H - 1;
    // first a free spot beside the dot; for the busiest actors, then spots further out, then over other dots
    // (the label's white halo keeps it readable), so the biggest dots are never left unnamed
    const tries = [[spots(p, w, h, g), true]];
    if (rank < mustLabel) tries.push([spots(p, w, h, g + 8).concat(spots(p, w, h, g + 18)), true], [spots(p, w, h, g).concat(spots(p, w, h, g + 8)), false]);
    for (const [cands, avoidDots] of tries) {
      const c = cands.map(([x, y]) => ({ x, y, w, h })).find((b) => inside(b) && !overLabel(b) && !(avoidDots && overDot(b)));
      if (c) { placed.push(c); it.at = c; return; }
    }
  });
}

function hull(points) {
  const p = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cross(lo.at(-2), lo.at(-1), q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.reverse()) { while (up.length >= 2 && cross(up.at(-2), up.at(-1), q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

// ------------------------------------------------------------------ the graph
function drawGraph(host, G, mode) {
  if (!G.nodes.size) { host.innerHTML = '<p class="muted nw-empty">No messages to draw.</p>'; return null; }
  const W = Math.max(340, host.clientWidth || 720);
  const nNamed = [...G.nodes.values()].filter((x) => x.named).length;
  const H0 = Math.round(mode === "all" ? Math.min(900, Math.max(500, W * 0.85)) : Math.min(720, Math.max(440, W * 0.8 + nNamed * 1.5)));
  const maxT = Math.max(...[...G.nodes.values()].filter((x) => x.named).map((x) => x.total), 1);
  const radius = (x) => (x.named ? 4 + 10 * Math.sqrt(x.total / maxT) : 2.6);
  const lay = layout(G, W, H0, radius, mode === "named" && nNamed <= 200 ? 16 : 3), pos = lay.pos, H = lay.H;
  const maxE = Math.max(...[...G.edges.values()].map((e) => e.n), 1);
  const ew = (n) => (0.9 + 3.4 * Math.log1p(n) / Math.log1p(maxE)).toFixed(2);
  const many = G.edges.size > 1500;
  let svg = `<svg class="nw-graph" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Every message between actors">
  <defs>${[["n", ACCENT], ["r", RUN_EDGE], ["h", "#1e4f86"]].map(([k, c]) => `<marker id="nwah${k}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1L10,5L0,9z" fill="${c}"/></marker>`).join("")}</defs>`;
  // a soft shape behind each group of named actors, when there is more than one group
  const namedGroups = G.groups.map((ids) => ids.filter(isNamed)).filter((ids) => ids.length >= 3);
  if (mode === "named" && namedGroups.length > 1) {
    namedGroups.forEach((ids, gi) => {
      const pts = hull(ids.map((id) => [pos.get(id).x, pos.get(id).y]));
      svg += `<path d="M${pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join("L")}Z" fill="${gi % 2 ? "#f3eefb" : "#eef4fb"}" stroke="${gi % 2 ? "#f3eefb" : "#eef4fb"}" stroke-width="34" stroke-linejoin="round" opacity=".9"/>`;
      const top = pts.reduce((a, b) => (b[1] < a[1] ? b : a), pts[0]);
      svg += `<text x="${top[0]}" y="${Math.max(11, top[1] - 20)}" text-anchor="middle" font-size="10.5" fill="${QUIET}">group ${gi + 1} · ${fmt(ids.length)} actors</text>`;
    });
  }
  // lines: a gentle curve, so the two directions of a pair do not sit on top of each other
  const edgeSvg = [];
  for (const e of G.edges.values()) {
    const a = pos.get(e.a), b = pos.get(e.b);
    if (!a || !b || e.a === e.b) continue;
    const ux = b.x - a.x, uy = b.y - a.y, len = Math.hypot(ux, uy) || 1;
    const off = Math.min(20, len * 0.12), mx = (a.x + b.x) / 2 - (uy / len) * off, my = (a.y + b.y) / 2 + (ux / len) * off;
    const ex = b.x - mx, ey = b.y - my, el = Math.hypot(ex, ey) || 1, sx0 = mx - a.x, sy0 = my - a.y, sl = Math.hypot(sx0, sy0) || 1;
    const x1 = a.x + (sx0 / sl) * (a.r + 1), y1 = a.y + (sy0 / sl) * (a.r + 1), x2 = b.x - (ex / el) * (b.r + 2.5), y2 = b.y - (ey / el) * (b.r + 2.5);
    const d = `M${x1.toFixed(1)},${y1.toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
    const nm = isNamed(e.a) && isNamed(e.b);
    const tip = `${short(e.a)} → ${short(e.b)}: ${plural(e.n, "message")} over ${plural(e.ch.size, "place")}, first ${when(e.first * 1000)}.` +
      (e.merged ? ` ⚠ ${e.merged === e.n ? "All" : fmt(e.merged) + " of them"} on places the redaction may have merged (dashed line).` : "") + " Click for the whole conversation.";
    const tiny = len < 26;   // dots side by side in the strip: a plain link, no arrowhead
    edgeSvg.push(`<path class="edge${nm ? "" : " run"}" data-k="${esc(e.key)}" data-a="${esc(e.a)}" data-b="${esc(e.b)}" d="${tiny ? `M${a.x.toFixed(1)},${a.y.toFixed(1)} L${b.x.toFixed(1)},${b.y.toFixed(1)}` : d}" fill="none" stroke="${nm ? ACCENT : RUN_EDGE}" stroke-width="${tiny ? 1.4 : ew(e.n)}"${e.merged && e.merged === e.n ? ' stroke-dasharray="4 3"' : ""}${tiny ? "" : ` marker-end="url(#nwah${nm ? "n" : "r"})"`}><title>${esc(tip)}</title></path>`);
    if (!many) edgeSvg.push(`<path class="edgehit" data-k="${esc(e.key)}" data-a="${esc(e.a)}" data-b="${esc(e.b)}" d="${d}" fill="none" stroke="transparent" stroke-width="10"><title>${esc(tip)}</title></path>`);
  }
  if (lay.strip) svg += `<line x1="10" x2="${W - 10}" y1="${lay.strip.y + 4}" y2="${lay.strip.y + 4}" stroke="${GRID}"/><text x="10" y="${lay.strip.y + 16}" font-size="10.5" fill="${QUIET}">${plural(lay.strip.groups, "small group")} (${plural(lay.strip.actors, "actor")}) that only talk among themselves</text>`;
  svg += edgeSvg.join("");
  // dots: size is messages, colour is role; anonymous runs are small grey dots
  const nodeSvg = [];
  for (const x of [...G.nodes.values()].sort((p, q) => p.total - q.total)) {
    const p = pos.get(x.id);
    const fill = x.named ? ROLES[x.role].fill : RUN_FILL;
    nodeSvg.push(`<g class="node${x.named ? "" : " run"}" data-actor="${esc(x.id)}" data-nid="${esc(x.id)}"><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${p.r.toFixed(1)}" fill="${fill}" stroke="${x.named ? "#fff" : RUN_STROKE}" stroke-width="${x.named ? 1.5 : 1}"/></g>`);
  }
  svg += nodeSvg.join("");
  // names of the named actors (busiest first when there are too many to name)
  const toLabel = [...G.nodes.values()].filter((x) => x.named).sort((p, q) => q.total - p.total).slice(0, CAP_LABELS).map((x) => ({ id: x.id, text: short(x.id) }));
  labelSpots(toLabel, pos, W, H, lay.strip ? [{ x: 0, y: lay.strip.y, w: W, h: 20 }] : []);
  svg += toLabel.filter((l) => l.at).map((l) => `<text class="nwlab" data-nid="${esc(l.id)}" data-actor="${esc(l.id)}" x="${(l.at.x + 1).toFixed(1)}" y="${(l.at.y + 9.5).toFixed(1)}" font-size="11">${esc(l.text)}</text>`).join("");
  host.innerHTML = svg + "</svg>";
  const el = host.querySelector("svg");
  // hover: keep the chosen actor (or line) and what it touches, fade the rest
  const light = (keep) => {
    el.classList.add("dim");
    const on = new Set();
    el.querySelectorAll(".edge").forEach((p) => { const k = keep(p); p.classList.toggle("hi", k); if (k) { on.add(p.dataset.a); on.add(p.dataset.b); } });
    el.querySelectorAll("[data-nid]").forEach((g) => g.classList.toggle("hi", on.has(g.dataset.nid)));
  };
  const clear = () => { el.classList.remove("dim"); el.querySelectorAll(".hi").forEach((x) => x.classList.remove("hi")); };
  el.querySelectorAll("g.node, text.nwlab").forEach((g) => {
    const id = g.dataset.nid;
    g.addEventListener("mouseenter", () => light((p) => p.dataset.a === id || p.dataset.b === id));
    g.addEventListener("mouseleave", clear);
  });
  el.querySelectorAll(many ? ".edge" : ".edgehit").forEach((hit) => {
    const k = hit.dataset.k;
    hit.addEventListener("mouseenter", () => light((p) => p.dataset.k === k));
    hit.addEventListener("mouseleave", clear);
    hit.addEventListener("click", () => openConversation(hit.dataset.a, hit.dataset.b));
  });
  return { el, G };
}

// show the graph as it stood at time T (seconds): lines and dots appear as messages are read
function applyTime(view, T) {
  if (!view) return;
  const { el, G } = view;
  const active = new Set();
  const maxE = Math.max(...[...G.edges.values()].map((e) => e.n), 1);
  el.querySelectorAll(".edge,.edgehit").forEach((p) => {
    const e = G.edges.get(p.dataset.k);
    let n = 0;
    if (e) for (const t of e.times) { if (t <= T) n++; else break; }
    p.classList.toggle("off", n === 0);
    if (n && p.classList.contains("edge")) { if (p.hasAttribute("marker-end")) p.setAttribute("stroke-width", (0.9 + 3.4 * Math.log1p(n) / Math.log1p(maxE)).toFixed(2)); active.add(e.a); active.add(e.b); }
  });
  el.querySelectorAll("[data-nid]").forEach((g) => g.classList.toggle("off", !active.has(g.dataset.nid)));
}

function scrubStats(msgs, T) {
  let n = 0;
  const pairs = new Set(), root = new Map();
  const find = (x) => { if (!root.has(x)) root.set(x, x); while (root.get(x) !== x) { root.set(x, root.get(root.get(x))); x = root.get(x); } return x; };
  const size = new Map(); let big = 0;
  for (const m of msgs) {
    if (m.rt > T) break;
    n++; pairs.add(m.from + "\u0001" + m.to);
    const a = find(m.from), b = find(m.to);
    if (!size.has(a)) size.set(a, 1);
    if (!size.has(b)) size.set(b, 1);
    if (a !== b) { root.set(a, b); size.set(b, size.get(a) + size.get(b)); }
    big = Math.max(big, size.get(find(b)));
  }
  return { n, pairs: pairs.size, actors: root.size, big };
}

function histogram(msgs, t0, t1) {
  const B = 120, c = new Array(B).fill(0);
  msgs.forEach((m) => { c[Math.min(B - 1, Math.floor(((m.rt - t0) / Math.max(1, t1 - t0)) * B))]++; });
  const mx = Math.max(1, ...c);
  return `<svg class="nw-hist" viewBox="0 0 ${B} 24" preserveAspectRatio="none">${c.map((v, i) => v ? `<rect x="${i + 0.1}" y="${24 - (v / mx) * 23}" width="0.8" height="${(v / mx) * 23}" fill="${ACCENT}" opacity=".55"/>` : "").join("")}</svg>`;
}

// ------------------------------------------------------------------ the matrix of every sender and receiver
function drawMatrix(host, G) {
  const all = [...G.nodes.values()].filter((x) => x.named);
  if (!all.length) { host.innerHTML = '<p class="muted">No messages between named actors.</p>'; return; }
  const order = (a, b) => a.group - b.group || b.total - a.total || (a.id < b.id ? -1 : 1);
  const senders = all.filter((x) => x.sent).sort(order), receivers = all.filter((x) => x.recv).sort(order);
  const rows = senders.slice(0, CAP_MATRIX), cols = receivers.slice(0, CAP_MATRIX);
  const R = rows.length, N = cols.length, W = Math.max(360, host.clientWidth || 720);
  const font = "11px -apple-system, system-ui, sans-serif";
  const rn = rows.map((x) => short(x.id)), cn = cols.map((x) => short(x.id));
  const labW = Math.min(150, Math.max(...rn.map((t) => textWidth(t, font))) + 14);
  const totW = 56;
  const cs = Math.max(9, Math.min(22, Math.floor((W - labW - totW - 10) / N)));
  const cf = Math.min(11, cs + 0.5), cfont = `${cf}px -apple-system, system-ui, sans-serif`;
  const topH = Math.round(Math.min(130, Math.max(...cn.map((t) => textWidth(t, cfont)))) + 12);
  const recvNums = cs >= 11;
  const gx = labW, gy = topH, Wd = gx + cs * N + totW, Hd = gy + cs * R + 34 + (recvNums ? 14 : 0);
  let mx = 1;
  const cell = (a, b) => G.edges.get(a + "\u0001" + b);
  rows.forEach((r) => cols.forEach((c) => { const e = cell(r.id, c.id); if (e) mx = Math.max(mx, e.n); }));
  const shade = (n) => { const t = Math.log1p(n) / Math.log1p(mx); const lerp = (a, b) => Math.round(a + (b - a) * t); return `rgb(${lerp(206, 23)},${lerp(223, 70)},${lerp(242, 128)})`; };
  let svg = `<svg class="nw-matrix" width="${Wd}" height="${Hd}" viewBox="0 0 ${Wd} ${Hd}" role="img" aria-label="Messages from each sender (rows) to each receiver (columns)">`;
  svg += `<rect x="${gx}" y="${gy}" width="${cs * N}" height="${cs * R}" fill="#fafbfc" stroke="${GRID}"/>`;
  for (let i = 1; i < R; i++) svg += `<line x1="${gx}" x2="${gx + cs * N}" y1="${gy + i * cs}" y2="${gy + i * cs}" stroke="${rows[i].group !== rows[i - 1].group ? "#9aa5b1" : "#f0f2f5"}"${rows[i].group !== rows[i - 1].group ? ' stroke-dasharray="3 2"' : ""}/>`;
  for (let j = 1; j < N; j++) svg += `<line y1="${gy}" y2="${gy + cs * R}" x1="${gx + j * cs}" x2="${gx + j * cs}" stroke="${cols[j].group !== cols[j - 1].group ? "#9aa5b1" : "#f0f2f5"}"${cols[j].group !== cols[j - 1].group ? ' stroke-dasharray="3 2"' : ""}/>`;
  svg += `<rect class="nw-xh-r" x="0" y="0" width="${gx + cs * N + totW}" height="${cs}" fill="#2f6fb3" opacity="0" pointer-events="none"/><rect class="nw-xh-c" x="0" y="0" width="${cs}" height="${gy + cs * R + 30}" fill="#2f6fb3" opacity="0" pointer-events="none"/>`;
  const showNum = cs >= 15;
  const maxSent = Math.max(...rows.map((x) => x.sent), 1), maxRecv = Math.max(...cols.map((x) => x.recv), 1);
  cols.forEach((c, j) => {
    svg += `<text class="nw-cl" data-j="${j}" data-actor="${esc(c.id)}" transform="translate(${gx + j * cs + cs / 2 + cf * 0.35},${gy - 5}) rotate(-90)" font-size="${cf}">${esc(fitName(cn[j], 128, cfont))}</text>`;
    const rh = (c.recv / maxRecv) * 22;
    svg += `<rect x="${gx + j * cs + cs * 0.2}" y="${gy + cs * R + 4}" width="${cs * 0.6}" height="${Math.max(1, rh)}" fill="${ACCENT}" opacity=".7"><title>${esc(short(c.id))} received ${fmt(c.recv)}</title></rect>`;
    if (recvNums) svg += `<text x="${gx + j * cs + cs / 2}" y="${gy + cs * R + 4 + Math.max(1, rh) + 10}" text-anchor="middle" font-size="9" fill="${QUIET}" pointer-events="none">${c.recv}</text>`;
  });
  rows.forEach((r, i) => {
    svg += `<text class="nw-rl" data-i="${i}" data-actor="${esc(r.id)}" x="${gx - 6}" y="${gy + i * cs + cs / 2 + 4}" text-anchor="end" font-size="11">${esc(fitName(rn[i], labW - 14, font))}</text>`;
    cols.forEach((c, j) => {
      if (r.id === c.id) { svg += `<rect x="${gx + j * cs + 0.5}" y="${gy + i * cs + 0.5}" width="${cs - 1}" height="${cs - 1}" fill="#e6e9ee"><title>${esc(short(r.id))} (itself)</title></rect>`; return; }
      const e = cell(r.id, c.id);
      if (!e) return;
      svg += `<rect class="nw-cell" data-i="${i}" data-j="${j}" data-a="${esc(r.id)}" data-b="${esc(c.id)}" x="${gx + j * cs + 0.5}" y="${gy + i * cs + 0.5}" width="${cs - 1}" height="${cs - 1}" rx="1.5" fill="${shade(e.n)}"><title>${esc(short(r.id))} → ${esc(short(c.id))}: ${plural(e.n, "message")} over ${plural(e.ch.size, "place")}. Click for the conversation.</title></rect>`;
      if (showNum) svg += `<text x="${gx + j * cs + cs / 2}" y="${gy + i * cs + cs / 2 + 3.5}" text-anchor="middle" font-size="9.5" fill="${Math.log1p(e.n) / Math.log1p(mx) > 0.45 ? "#fff" : INK}" pointer-events="none">${e.n}</text>`;
    });
    const sw = (r.sent / maxSent) * (totW - 26);
    svg += `<rect x="${gx + cs * N + 6}" y="${gy + i * cs + cs * 0.2}" width="${Math.max(1, sw)}" height="${cs * 0.6}" fill="#e3a43b"/><text x="${gx + cs * N + 9 + sw}" y="${gy + i * cs + cs / 2 + 3.5}" font-size="9.5" fill="${QUIET}">${r.sent}</text>`;
  });
  svg += `<text x="${gx + cs * N + 6}" y="${gy - 6}" font-size="10" fill="${QUIET}">sent</text><text x="${gx - 6}" y="${gy + cs * R + 18}" text-anchor="end" font-size="10" fill="${QUIET}">received</text>`;
  const cut = [senders.length > R ? `${fmt(R)} of ${fmt(senders.length)} senders` : "", receivers.length > N ? `${fmt(N)} of ${fmt(receivers.length)} receivers` : ""].filter(Boolean);
  // colour scale: the same log shading as the cells
  const steps = [...new Set([1, Math.round(Math.sqrt(mx)), mx])].filter((v) => v >= 1);
  const key = `<div class="nw-mkey"><span class="muted small">messages per cell</span>${steps.map((v) => `<span><i style="background:${shade(v)}"></i>${fmt(v)}</span>`).join("")}<span><i style="background:#e6e9ee"></i>itself</span></div>`;
  host.innerHTML = key + svg + "</svg>" + `<p class="small muted">${plural(R, "actor")} sent and ${plural(N, "actor")} received; ${fmt(all.length - senders.length)} only received${cut.length ? `. Showing the most active: ${cut.join(", ")}; every actor is in the table below` : ""}.</p>`;
  const el = host.querySelector("svg"), xr = el.querySelector(".nw-xh-r"), xc = el.querySelector(".nw-xh-c");
  el.querySelectorAll(".nw-cell").forEach((c) => {
    c.addEventListener("mouseenter", () => {
      const i = +c.dataset.i, j = +c.dataset.j;
      xr.setAttribute("y", gy + i * cs); xr.setAttribute("opacity", ".07");
      xc.setAttribute("x", gx + j * cs); xc.setAttribute("opacity", ".07");
      el.querySelectorAll(".nw-rl,.nw-cl").forEach((t) => t.classList.toggle("hl", t.dataset.i == i || t.dataset.j == j));
    });
    c.addEventListener("mouseleave", () => { xr.setAttribute("opacity", "0"); xc.setAttribute("opacity", "0"); el.querySelectorAll(".hl").forEach((t) => t.classList.remove("hl")); });
    c.addEventListener("click", () => openConversation(c.dataset.a, c.dataset.b));
  });
}

// ------------------------------------------------------------------ every actor, sortable
function actorTable(host, G) {
  const rows = [...G.nodes.values()].filter((x) => x.named);
  if (!rows.length) { host.innerHTML = '<p class="muted">None found.</p>'; return; }
  const cols = [
    ["actor", (x) => short(x.id), (x) => ent.actor(x.id)],
    ["sent (to named)", (x) => x.sent, (x) => fmt(x.sent), 1],
    ["received (from named)", (x) => x.recv, (x) => fmt(x.recv), 1],
    ["named partners", (x) => x.partners, (x) => fmt(x.partners), 1],
    ["broker rank", (x) => x.btwRank ?? 1e9, (x) => (x.btwRank ? `#${x.btwRank}` : "–"), 1],
    ["group", (x) => x.group, (x) => fmt(x.group), 1],
    ["first message", (x) => x.first, (x) => esc(when(x.first * 1000))],
    ["last message", (x) => x.last, (x) => esc(when(x.last * 1000))],
    ["messages over time", null, (x) => spark([...x.hours.entries()], { w: 120, h: 20, color: ACCENT })],
  ];
  const st = { key: 1, dir: -1, all: false };
  const draw = () => {
    const f = cols[st.key][1];
    const sorted = rows.slice().sort((a, b) => { const p = f(a), q = f(b); return (p < q ? -1 : p > q ? 1 : 0) * st.dir || b.total - a.total; });
    const show = st.all ? sorted : sorted.slice(0, 40);
    host.innerHTML = `<div class="nw-atwrap"><table class="nw-at"><thead><tr>${cols.map((c, i) => `<th${c[1] ? ` class="sort${i === st.key ? " on" : ""}" data-k="${i}"` : ""}${c[3] ? ' style="text-align:right"' : ""}>${esc(c[0])}${i === st.key ? (st.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead><tbody>${show.map((x) => `<tr>${cols.map((c) => `<td${c[3] ? ' class="n"' : ""}>${c[2](x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` +
      (sorted.length > show.length ? `<button type="button" class="lmore">Show all ${fmt(sorted.length)} actors</button>` : "");
    host.querySelectorAll("th.sort").forEach((th) => th.addEventListener("click", () => { const k = +th.dataset.k; if (k === st.key) st.dir = -st.dir; else { st.key = k; st.dir = k === 0 || k === 4 || k === 5 || k === 6 ? 1 : -1; } draw(); }));
    const more = host.querySelector(".lmore"); if (more) more.addEventListener("click", () => { st.all = true; draw(); });
  };
  draw();
}

// ------------------------------------------------------------------ the view
async function network(el, s) {
  const T = s.list_totals || {};
  const hasReplies = (T.reply_edges ?? (s.reply_edges || []).length) > 0;
  el.innerHTML = `<h2>Who talked to whom</h2><p class="lead muted" id="nwLead">Reading every message…</p>
  <p class="small nw-opt" id="nwOpt"></p>
  <div id="nwFinds"></div>
  <section class="card nw-gcard"><header><h3>Every message, as a graph</h3><div class="nw-mode" id="nwMode"></div></header>
    <p class="sub" id="nwSub"></p>
    <div id="nwGraph" class="nw-ghost"></div>
    <div class="nw-legend" id="nwLegend"></div>
    <div class="nw-scrub" id="nwScrub"></div>
  </section>
  <div id="conv"></div>
  <section class="card"><header><h3>Every sender and receiver</h3></header>
    <p class="sub" id="nwMatSub"></p>
    <div id="nwMatrix" class="nw-mwrap"></div></section>
  <section class="card"><header><h3>Every actor in a message</h3></header>
    <p class="sub">Only messages between named actors count here, as in the graph's "Named actors" view. Click a column to sort. Broker rank orders actors by how often they sit on the shortest chain of messages between two others. Hover or click an actor for its full profile, which also counts messages with anonymous runs.</p>
    <div id="nwActors"></div></section>
  <section class="card"><header><h3>All sender-receiver pairs</h3></header>
    <p class="small"><input id="pairQ" placeholder="Find an actor, e.g. cred 169" style="width:220px"> <label class="muted"><input type="checkbox" id="pairAll"> also show pairs with an anonymous run</label> <span id="pairCount" class="muted"></span></p>
    <p class="sub">Click a pair to open its conversation. "Back" is how many messages went the other way. ⚠ marks pairs with messages on places the redaction may have merged.</p>
    <div id="pairs"></div></section>
  <section class="card"><header><h3>One identity carrying another's token</h3></header>
    <p class="sub">A record that authenticates as one identity and also holds another identity's token, before that token's own first use (see ${term("carried", "carried token")}).</p><div id="carriedList"></div></section>
  <section class="card"><header><h3>Two identities using one name</h3></header>
    <p class="sub">A name the pack lists as one that runs can reuse (a controller, a command channel, a board name), written by two identities. "In different records" is yes when each identity used it in a record of its own; no when both appear in the same record.</p><div id="sharedList"></div></section>
  ${hasReplies ? `<section class="card"><header><h3>Replies between actors</h3></header><p class="sub">A reply is a record whose parent record was written by a different actor.</p><div id="replyList"></div></section>` : ""}`;
  listView($("carriedList"), "carried_edges", ["carrier", "token carried", "records", "evidence"],
    (e) => [ent.actor(e.from), ent.actor(e.to), fmt(e.records), (e.evidence || []).map((id) => ent.rec(id)).join(" ")], (s.carried_edges || []).slice(0, 10), T.carried_edges);
  listView($("sharedList"), "shared_places", ["name", "identities", "first use", "second use", "in different records"],
    (p) => [`<code class="nw-name" title="a reusable name both identities wrote">${esc(p.place)}</code>`, p.identities.map((x) => ent.actor(x)).join(" "), `<span class="nowrap">${esc(when(toTime(p.first)))}</span> ${ent.rec(p.first_id)}`, `<span class="nowrap">${esc(when(toTime(p.second)))}</span> ${ent.rec(p.second_id)}`, p.same_record ? "no, both in one record" : "yes"], (s.shared_places || []).slice(0, 10), T.shared_places);
  if (hasReplies) listView($("replyList"), "reply_edges", ["from", "to", "replies"],
    (r) => [ent.actor(r.from), ent.actor(r.to), fmt(r.replies)], (s.reply_edges || []).slice(0, 10).map((r) => ({ from: r[0], to: r[1], replies: r[2] })), T.reply_edges);
  let qt = null;
  $("pairQ").addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(() => pairList(), 200); });
  $("pairAll").addEventListener("change", () => pairList());

  const raw = await cached("/api/messages");
  if (S.tab !== "network" || !$("nwGraph")) return;
  const base = prepare(raw);
  NW.mergedByPair = new Map();
  base.msgs.forEach((m) => { if (m.merged) { const k = m.from + "\u0001" + m.to; NW.mergedByPair.set(k, (NW.mergedByPair.get(k) || 0) + 1); } });
  pairList();
  if (!base.msgs.length) {
    $("nwLead").innerHTML = "No messages found: no place was written by one actor and later read by a different one. The lists below still show tokens carried between identities and names two identities shared.";
    ["nwFinds", "nwMatrix", "nwActors"].forEach((id) => ($(id).innerHTML = '<p class="muted">Nothing to show.</p>'));
    $("nwGraph").innerHTML = '<p class="muted nw-empty">No messages to draw.</p>';
    return;
  }
  const mergedAll = base.msgs.filter((m) => m.merged).length, mergedNamed = base.named.filter((m) => m.merged).length;
  $("nwOpt").innerHTML = mergedAll ? `<label><input type="checkbox" id="nwNoMerged"${NW.noMerged ? " checked" : ""}> Leave out places the redaction may have merged</label> <span class="muted">⚠ ${plural(mergedNamed, "message")} between named actors (${fmt(mergedAll)} in all) sit on a ${term("merged", "merged place")}, where the write and the read may be on two different repositories.</span>` : "";
  if ($("nwNoMerged")) $("nwNoMerged").addEventListener("change", (e) => { NW.noMerged = e.target.checked; NW.T = null; rebuild(); });

  const t0 = base.msgs[0].rt, t1 = base.msgs.at(-1).rt;
  let view = null, D = null;
  const compute = () => {
    const keep = (m) => !(NW.noMerged && m.merged);
    const msgs = base.msgs.filter(keep), named = base.named.filter(keep);
    const Gn = buildGraph(named), Ga = buildGraph(msgs);
    betweenness(Gn);
    D = { msgs, named, Gn, Ga, runs: [...Ga.nodes.values()].filter((x) => !x.named).length, withRuns: msgs.length - named.length };
    if (!Gn.nodes.size && NW.mode === "named") NW.mode = "all";
  };
  const sources = () => (NW.mode === "named" ? D.named : D.msgs);
  const graphOf = () => (NW.mode === "named" ? D.Gn : D.Ga);
  const lead = () => {
    const tot = s.actions?.named_actors ?? Object.entries(s.actor_kinds || {}).filter(([k]) => k !== "run").reduce((x, [, v]) => x + v, 0);
    const left = NW.noMerged ? ` Leaving out ${plural(mergedAll, "message")} on merged places.` : (mergedNamed ? ` ⚠ ${fmt(mergedNamed)} of the ${fmt(D.named.length)} sit on places the redaction may have merged.` : "");
    $("nwLead").innerHTML = `${fmt(D.Gn.nodes.size)} of the ${fmt(tot)} ${term("named", "named actors")} exchanged ${plural(D.named.length, term("message", "message"))} in ${plural(D.Gn.edges.size, "sender-receiver pair")}` +
      (D.withRuns ? `; ${plural(D.withRuns, "more message")} involve ${plural(D.runs, term("run", "anonymous run"))}.` : ".") + left +
      ` An ${term("actor", "actor")} is an identity token or a self-chosen name seen in the code, not an agent: one agent may hold several tokens, so a message can be one agent talking to itself.`;
    $("nwLead").classList.remove("muted");
  };
  const drawMode = () => {
    const { Gn, Ga } = D;
    $("nwMode").innerHTML = [["named", `Named actors <span>${fmt(Gn.nodes.size)}</span>`], ["all", `Everyone <span>${fmt(Ga.nodes.size)}</span>`]]
      .map(([k, label]) => `<button type="button" data-m="${k}" class="${NW.mode === k ? "on" : ""}"${k === "named" && !Gn.nodes.size ? " disabled" : ""}>${label}</button>`).join("");
    $("nwMode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { NW.mode = b.dataset.m; drawMode(); redraw(); }));
    const G = graphOf();
    $("nwSub").innerHTML = NW.mode === "named"
      ? `All ${plural(G.edges.size, "sender-receiver pair")} between ${plural(G.nodes.size, "named actor")}. Each arrow runs from the writer to the reader; thicker means more messages, dashed means every message on it sits on a merged place. Dot size is an actor's messages. Hover a dot to pick out its messages, click it for its profile; click an arrow for the whole conversation, with every record id.`
      : `Everything: ${plural(G.edges.size, "pair")} among ${plural(G.nodes.size, "actor")}, including ${plural(D.runs, "anonymous run")} as small hollow dots. Small groups that only talk among themselves are lined up at the bottom.`;
    const roles = new Set([...G.nodes.values()].filter((x) => x.named).map((x) => x.role));
    const anyMerged = [...G.edges.values()].some((e) => e.merged && e.merged === e.n);
    $("nwLegend").innerHTML = ROLES.map((r, i) => (roles.has(i) ? `<span><i style="background:${r.fill}"></i>${r.label}</span>` : "")).join("") +
      (NW.mode === "all" && D.runs ? `<span><i style="background:${RUN_FILL};border:1.2px solid ${RUN_STROKE}"></i>anonymous run</span>` : "") +
      (anyMerged ? `<span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="${ACCENT}" stroke-width="2" stroke-dasharray="4 3"/></svg>only on merged places</span>` : "") +
      `<span class="muted">line thickness and dot size: messages</span>`;
  };
  const redraw = () => {
    const host = $("nwGraph"); if (!host) return;
    host.classList.remove("nw-ghost");
    view = drawGraph(host, graphOf(), NW.mode);
    setT(NW.T ?? t1, true);
  };
  // the time scrubber
  const scrub = $("nwScrub");
  scrub.innerHTML = `<button type="button" id="nwPlay" class="nw-play" title="Play the messages in time order">▶</button>
    <div class="nw-track"><div id="nwHist"></div><input type="range" id="nwT" min="0" max="1000" value="1000" aria-label="Show messages up to this time"></div>
    <div class="nw-now"><b id="nwWhen"></b><span id="nwStats"></span></div>`;
  const slider = $("nwT");
  function setT(T, fromRedraw) {
    NW.T = T >= t1 ? null : T;
    const t = Math.min(T, t1);
    if (!fromRedraw) slider.value = Math.round(((t - t0) / Math.max(1, t1 - t0)) * 1000);
    else slider.value = Math.round(((t - t0) / Math.max(1, t1 - t0)) * 1000);
    applyTime(view, t);
    const st = scrubStats(sources(), t);
    $("nwWhen").textContent = T >= t1 ? `All, to ${when(t1 * 1000)}` : when(t * 1000);
    $("nwStats").textContent = `${plural(st.n, "message")} · ${plural(st.pairs, "pair")} · ${plural(st.actors, NW.mode === "named" ? "named actor" : "actor")} · largest group ${fmt(st.big)}`;
  }
  slider.addEventListener("input", () => { stop(); setT(t0 + (slider.value / 1000) * (t1 - t0)); });
  const stop = () => { NW.playing = false; cancelAnimationFrame(NW.raf); const b = $("nwPlay"); if (b) b.textContent = "▶"; };
  $("nwPlay").addEventListener("click", () => {
    if (NW.playing) { stop(); return; }
    NW.playing = true; $("nwPlay").textContent = "❚❚";
    let cur = +slider.value >= 1000 ? 0 : +slider.value;
    let last = performance.now();
    const step = (now) => {
      if (!NW.playing || !$("nwT")) return;
      cur = Math.min(1000, cur + ((now - last) / 14000) * 1000); last = now;
      slider.value = cur; setT(t0 + (cur / 1000) * (t1 - t0), false);
      if (cur >= 1000) { stop(); return; }
      NW.raf = requestAnimationFrame(step);
    };
    NW.raf = requestAnimationFrame(step);
  });
  const matrix = () => {
    $("nwMatSub").innerHTML = `One row per named actor that sent, one column per named actor that received; darker means more messages. Bars at the right count what each actor sent, bars below what it received${D.Gn.groups.length > 1 ? "; dashed lines split separate groups" : ""}. Hover a cell to follow its row and column; click it for the conversation.`;
    drawMatrix($("nwMatrix"), D.Gn);
  };
  function rebuild() {
    stop();
    compute();
    lead();
    $("nwFinds").innerHTML = D.Gn.nodes.size ? findings(D.Gn, D.msgs, D.named) : "";
    $("nwHist").innerHTML = histogram(D.msgs, t0, t1);
    drawMode();
    redraw();
    matrix();
    actorTable($("nwActors"), D.Gn);
  }
  rebuild();
  onResize($("nwGraph"), redraw);
  onResize($("nwMatrix"), matrix);
  if (S.conv) openConversation(S.conv.a, S.conv.b, false);
}

// every pair, searchable, a page at a time
async function pairList(offset = 0) {
  const box = $("pairs");
  if (!box) return;
  const q = $("pairQ").value.trim(), all = $("pairAll").checked;
  const r = await api(`/api/pairs?q=${encodeURIComponent(q)}${all ? "&all=1" : ""}&offset=${offset}&limit=50`);
  if (!$("pairQ") || $("pairQ").value.trim() !== q) return;
  $("pairCount").textContent = `${plural(r.total, "pair")}${all ? ", anonymous runs included" : " between named actors"}${q ? " matching" : ""}`;
  const badge = (p) => { const n = NW.mergedByPair.get(p.from + "\u0001" + p.to); return n ? ` <span class="nw-warn" title="${esc(`${fmt(n)} of these ${fmt(p.messages)} messages are on places the redaction may have merged. ${MERGED_TIP}`)}">⚠ ${fmt(n)}</span>` : ""; };
  const rows = r.rows.map((p) => `<tr class="click" data-a="${esc(p.from)}" data-b="${esc(p.to)}"><td>${ent.actor(p.from)}</td><td>${ent.actor(p.to)}</td><td class="n">${fmt(p.messages)}${badge(p)}</td><td class="n">${fmt(p.back)}</td><td class="n">${fmt(p.channels)}</td><td class="nowrap">${esc(when(toTime(p.first)))}</td><td class="nowrap">${esc(when(toTime(p.last)))}</td></tr>`).join("");
  const head = '<tr><th>sender</th><th>receiver</th><th style="text-align:right">messages</th><th style="text-align:right">back</th><th style="text-align:right">places</th><th>first read</th><th>last read</th></tr>';
  if (offset === 0) box.innerHTML = r.total ? `<div class="nw-atwrap"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div><p id="pairMore"></p>` : '<p class="muted">None found.</p>';
  else box.querySelector("tbody").insertAdjacentHTML("beforeend", rows);
  box.querySelectorAll("tr.click:not([data-bound])").forEach((tr) => { tr.dataset.bound = 1; tr.addEventListener("click", (e) => { if (e.target.closest(".ent")) return; openConversation(tr.dataset.a, tr.dataset.b); }); });
  const shown = offset + r.rows.length, more = $("pairMore");
  if (more) more.innerHTML = shown < r.total ? `<button id="pairMoreBtn">Show ${fmt(Math.min(50, r.total - shown))} more (${fmt(shown)} of ${fmt(r.total)} shown)</button>` : "";
  if ($("pairMoreBtn")) $("pairMoreBtn").addEventListener("click", () => pairList(shown));
}

// the whole conversation between two actors: every message both ways, in time order, with record ids
async function openConversation(a, b, scroll = true) {
  const box = $("conv");
  if (!box) return;
  S.conv = { a, b };
  box.innerHTML = '<p class="muted">Loading the conversation…</p>';
  const c = await api(`/api/conversation?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  if (!$("conv") || S.conv?.a !== a || S.conv?.b !== b) return;
  const PAGE = 200;
  const item = (it) => {
    const side = it.kind === "overwrite" ? "over" : it.from === a ? "left" : "right";
    const lines = it.lines.length ? `<ul class="lines">${it.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : "";
    return `<div class="msg ${side}">
      <div class="mhead">${ent.actor(it.from)} → ${ent.actor(it.to)}${it.kind === "overwrite" ? ' <span class="tag">overwrite, not a message</span>' : ""}${it.merged_place ? ` <span class="tag nw-warn" title="${esc(MERGED_TIP)}">⚠ place may be merged by redaction</span>` : ""} · ${ent.place(it.channel)} · <span class="muted">${esc(it.how || "")}</span></div>
      <div class="mrow"><span class="lab">wrote</span> ${ent.rec(it.write_id)} <span class="muted">${esc(it.write_time || "time unknown")}</span></div>
      <div class="snip">${esc(it.write_text)}</div>
      <div class="mrow"><span class="lab">${it.kind === "overwrite" ? "replaced in" : "read in"}</span> ${ent.rec(it.read_id)} <span class="muted">${esc(it.read_time || "time unknown")}${it.latency_h != null ? ` · ${it.latency_h < 1 / 60 ? "under a minute later" : esc(hoursWord(it.latency_h)) + " later"}` : ""}</span></div>
      <div class="snip">${esc(it.read_text)}</div>
      ${lines ? `<div class="mrow"><span class="lab">${it.kind === "overwrite" ? "lines dropped" : "lines kept"}</span></div>${lines}` : ""}
    </div>`;
  };
  // a strip of the conversation over time: one tick per message, by direction
  const ts = c.items.map((it) => ({ t: toTime(it.read_time), dir: it.kind === "overwrite" ? 0 : it.from === a ? 1 : -1 })).filter((x) => x.t != null);
  let strip = "";
  if (ts.length) {
    const W = 600, t0 = ts[0].t, t1 = Math.max(ts.at(-1).t, t0 + 3600e3);
    const X = (t) => 8 + ((t - t0) / (t1 - t0)) * (W - 16);
    strip = `<svg class="nw-cstrip" viewBox="0 0 ${W} 46" preserveAspectRatio="none" width="100%" height="46"><line x1="8" x2="${W - 8}" y1="23" y2="23" stroke="${GRID}"/>${ts.map((x) => `<line x1="${X(x.t).toFixed(1)}" x2="${X(x.t).toFixed(1)}" y1="${x.dir > 0 ? 6 : x.dir < 0 ? 23 : 15}" y2="${x.dir > 0 ? 23 : x.dir < 0 ? 40 : 31}" stroke="${x.dir > 0 ? "#e3a43b" : x.dir < 0 ? ACCENT : BASE}" stroke-width="2"/>`).join("")}</svg>
      <div class="nw-cax small muted"><span>${esc(when(t0))}</span><span>above: ${esc(short(a))} → ${esc(short(b))} · below: ${esc(short(b))} → ${esc(short(a))}</span><span>${esc(when(ts.at(-1).t))}</span></div>`;
  }
  box.innerHTML = `<div class="conv">
    <div class="convhead">
      <div>${ent.actor(a)} ⇄ ${ent.actor(b)}<br><span class="muted small">${plural(c.a_to_b, "message")} from ${esc(short(a))} (left), ${fmt(c.b_to_a)} from ${esc(short(b))} (right)${c.overwrites ? `, ${plural(c.overwrites, "overwrite")} (centre)` : ""}${c.on_merged_places ? `; ${fmt(c.on_merged_places)} on places the redaction may have merged` : ""} · ${plural(c.places.length, "place")} · ${esc(c.first || "")} to ${esc(c.last || "")}</span></div>
      <div class="convbtns"><button id="convAsk">Ask the AI about this</button> <button id="convCopy">Copy ${fmt(c.record_ids.length)} record ids</button> <button id="convClose">Close</button></div>
    </div>
    ${strip}
    <details class="convids"><summary>All ${fmt(c.record_ids.length)} record ids, in order</summary><div>${c.record_ids.map((id) => ent.rec(id)).join(" ")}</div></details>
    <details class="convids"><summary>${plural(c.places.length, "place")}</summary><div>${c.places.map((p) => ent.place(p)).join(" ")}</div></details>
    <div class="thread" id="thread">${c.items.slice(0, PAGE).map(item).join("")}</div>
    ${c.items.length > PAGE ? `<button id="convMore">Show all ${fmt(c.items.length)}</button>` : ""}
    ${c.truncated ? `<p class="muted small">Showing the first ${fmt(c.items.length)} of ${fmt(c.total)}.</p>` : ""}
  </div>`;
  if ($("convMore")) $("convMore").addEventListener("click", () => { $("thread").innerHTML = c.items.map(item).join(""); $("convMore").remove(); });
  $("convClose").addEventListener("click", () => { S.conv = null; box.innerHTML = ""; });
  $("convCopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(c.record_ids.join("\n")); $("convCopy").textContent = "Copied"; }
    catch { $("convCopy").textContent = "Copy failed"; }
  });
  $("convAsk").addEventListener("click", () => {
    const q = `Explain the conversation between ${a} and ${b}: what passed between them, in what order, through which places, and what it suggests. Cite record ids.`;
    if (window.askAbout) askAbout(null, q); else { $("q").value = q; $("q").focus(); }
  });
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

VIEWS.network = network;
})();

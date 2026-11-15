// Swarm Tracer hosted demo: the app with no server behind it.
// agenttrace/tools/export_static.py copies this file next to index.html as static.js and loads it before
// core.js. core.js's api() hands every request to ST_STATIC.api(), which answers from the JSON files the
// export saved (data/*.json, listed in static.json). Requests that change something (POST) and queries
// that were not saved get one plain message instead of an error from a server that is not there.
"use strict";
(() => {
  const UNAVAILABLE = "Not available in the hosted demo. Install Swarm Tracer to use it.";
  const NOT_SAVED = "This query was not saved in the hosted demo. Install Swarm Tracer to run it on your own machine.";
  const files = new Map();
  const getJSON = (f) => {
    if (!files.has(f)) files.set(f, fetch(f).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }));
    return files.get(f);
  };
  const manifest = () => getJSON("static.json");
  const index = () => getJSON("data/records-index.json");

  // ---------------------------------------------------------------- request -> saved file
  // the same three functions as export_static.py: canonical key, FNV-1a over UTF-8, file name
  function parse(path) {
    const u = new URL(path, "http://x/"), q = {};
    for (const [k, v] of u.searchParams) if (v !== "" && !(k in q)) q[k] = v;
    return { path: u.pathname, q };
  }
  const canon = (path, q) => path + "?" + Object.keys(q).sort().map((k) => k + "=" + q[k]).join("&");
  function fnv(s) {
    let h = 0x811c9dc5;
    for (const b of new TextEncoder().encode(s)) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
    return h;
  }
  const slug = (path) => path.replace(/^\/api\//, "").replace(/[^A-Za-z0-9]+/g, "_");
  async function saved(path, q) {
    const man = await manifest(), n = man.paths[path];
    if (!n) return undefined;
    const key = canon(path, q);
    const pack = await getJSON(`data/${slug(path)}-${fnv(key) % n}.json`);
    if (!Object.prototype.hasOwnProperty.call(pack, key)) return undefined;
    // the export takes repeats out of what it saves (export_static.py ref_rows, share): put them back
    const rows = (man.refs || []).includes(path) ? await rowsById() : null;
    const shared = (man.shared || []).includes(path) ? await getJSON(`data/${slug(path)}-shared.json`) : null;
    return decode(pack[key], rows, shared);
  }
  let byId = null;
  const rowsById = async () => byId || (byId = new Map((await index()).events.map((r) => [r.id, r])));
  // a fresh copy of a saved value: {"$s": n} is item n of the path's shared file, {"$r": id, ...} is record
  // id's row plus the other fields
  function decode(x, rows, shared) {
    if (Array.isArray(x)) return x.map((y) => decode(y, rows, shared));
    if (!x || typeof x !== "object") return x;
    if ("$s" in x) return decode(shared[x.$s], rows, shared);
    const out = "$r" in x ? { ...rows.get(x.$r) } : {};
    for (const k in x) if (k !== "$r") out[k] = decode(x[k], rows, shared);
    return out;
  }
  const clone = (x) => JSON.parse(JSON.stringify(x));

  // ---------------------------------------------------------------- queries answered in the browser
  // Free-text and filter queries cannot all be saved, so these four mirror the server's code over an
  // index of every record (Session.search, Session.pairs, Session.listing, insight.omni, units._events_get).
  const cnt = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  const mostCommon = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]);     // stable: ties keep first-seen order
  const int = (v, d, hi) => { const n = v == null ? d : Math.max(0, parseInt(v, 10) || 0); return hi == null ? n : Math.min(hi, n); };
  function matcher(ix, q, actor) {
    const ql = (q.q || "").toLowerCase().trim(), hour = q.hour || "";
    return (r, i) => {
      if (q.kind && r.kind !== q.kind) return false;
      if (q.intent && r.intent !== q.intent) return false;
      if (q.tag && !r.tags.includes(q.tag)) return false;
      if (actor && r.actor !== actor) return false;
      if (q.channels === "1" && !r.ops) return false;
      if (hour) {
        if (!r.time) return false;
        const h = r.time.slice(0, 13);
        if (hour.includes("..")) { const k = hour.indexOf(".."), lo = hour.slice(0, k), hi = hour.slice(k + 2); if (!(lo <= h && h <= hi)) return false; }
        else if (!h.startsWith(hour)) return false;
      }
      return !ql || ix.find[i].includes(ql);
    };
  }
  function search(ix, q, actor, offset, limit) {
    const ok = matcher(ix, q, actor), rows = [];
    const kinds = new Map(), intents = new Map(), actors = new Map(), hours = new Map(), by = new Map();
    let total = 0;
    ix.events.forEach((r, i) => {
      if (!ok(r, i)) return;
      if (offset <= total && total < offset + limit) rows.push(r);
      total += 1;
      cnt(kinds, r.kind);
      if (r.intent) cnt(intents, r.intent);
      cnt(actors, r.actor);
      if (r.time) {
        const h = r.time.slice(0, 13);
        cnt(hours, h);
        if (!by.has(h)) by.set(h, new Map());
        cnt(by.get(h), r.intent || "kind:" + (r.kind || "record"));
      }
    });
    const hs = [...hours.keys()].sort();
    return { total, offset, rows,
      facets: { kind: Object.fromEntries(mostCommon(kinds)), intent: Object.fromEntries(mostCommon(intents)), actor: mostCommon(actors).slice(0, 12) },
      hist: hs.map((h) => [h, hours.get(h)]), timed: hs.reduce((a, h) => a + hours.get(h), 0),
      hist_by: hs.map((h) => [h, Object.fromEntries(by.get(h))]) };
  }
  const sumDicts = (ds) => { const o = {}; ds.forEach((d) => Object.entries(d).forEach(([k, v]) => { o[k] = (o[k] || 0) + v; })); return o; };
  function unitsEvents(ix, q) {
    const who = q.actor || "", off = int(q.offset, 0), lim = int(q.limit, 100, 500), amap = ix.agent_of;
    const g = who ? (amap[who] || who) : null;
    let toks = who ? Object.keys(amap).filter((t) => amap[t] === g) : [];
    if (who && !toks.length) toks = [who];
    let res;
    if (toks.length > 1) {
      const rs = toks.map((t) => search(ix, q, t, 0, off + lim));
      const order = new Map(ix.events.map((r, i) => [r.id, i]));
      const rows = rs.flatMap((x) => x.rows).sort((a, b) => order.get(a.id) - order.get(b.id)).slice(off, off + lim);
      const hist = sumDicts(rs.map((x) => Object.fromEntries(x.hist))), hby = {};
      rs.forEach((x) => x.hist_by.forEach(([h, c]) => { hby[h] = sumDicts([hby[h] || {}, c]); }));
      const total = rs.reduce((a, x) => a + x.total, 0), hs = Object.keys(hist).sort();
      res = { total, offset: off, rows,
        facets: { kind: sumDicts(rs.map((x) => x.facets.kind)), intent: sumDicts(rs.map((x) => x.facets.intent)), actor: [[who, total]] },
        hist: hs.map((h) => [h, hist[h]]), timed: hs.reduce((a, h) => a + hist[h], 0), hist_by: Object.keys(hby).sort().map((h) => [h, hby[h]]) };
    } else {
      res = search(ix, q, toks[0] || "", off, lim);
      if (!who) {
        const ok = matcher(ix, q, ""), c = new Map();
        ix.events.forEach((r, i) => { if (ok(r, i)) cnt(c, amap[r.actor] || r.actor); });
        res.facets.actor = [...c.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)).slice(0, 12);
      }
    }
    res.agent_tokens = toks.length;
    return res;
  }
  function pairs(ix, q) {
    const terms = (q.q || "").toLowerCase().split(/\s+/).filter(Boolean), namedOnly = q.all !== "1";
    const off = int(q.offset, 0), lim = int(q.limit, 50, 500);
    const hits = ix.pairs.filter((r, i) => (r.named || !namedOnly) && terms.every((t) => ix.pair_keys[i].includes(t)));
    return { total: hits.length, offset: off, rows: hits.slice(off, off + lim) };
  }
  function listing(ix, q) {
    const name = q.name || "";
    if (!Object.prototype.hasOwnProperty.call(ix.lists, name)) throw new Error(`no list named ${name}`);
    let rows = ix.lists[name];
    if (q.q) {
      const ql = q.q.toLowerCase(), find = ix.list_find[name];
      rows = rows.filter((r, i) => find[i].includes(ql) || find[i].split("[credential ").join("cred ").includes(ql));
    }
    const off = int(q.offset, 0), lim = int(q.limit, 100, 1000);
    return { name, total: rows.length, offset: off, rows: rows.slice(off, off + lim) };
  }
  function omni(ix, q, limit = 8) {
    const raw = (q.q || "").trim();
    if (!raw) return { records: [], actors: [], places: [] };
    const ql = raw.toLowerCase(), alt = ql.replace(/\bcred (\d+)/g, "[credential $1]");
    const byId = new Map(ix.events.map((r) => [r.id, r])), recs = [];
    if (byId.has(raw)) recs.push(raw);
    for (const r of ix.events) { if (recs.length >= limit) break; if (r.id !== raw && r.id.toLowerCase().startsWith(ql)) recs.push(r.id); }
    const word = new RegExp("\\b" + ql.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b");
    const rank = (a) => {
      const al = a.toLowerCase(), sh = al.replace(/\[credential (\d+)\]/g, "cred $1");
      if (ql === al || ql === sh || alt === al) return 0;
      if (al.startsWith(ql) || sh.startsWith(ql) || word.test(sh)) return 1;
      return al.includes(ql) || al.includes(alt) || sh.includes(ql) ? 2 : null;
    };
    const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
    const actors = ix.actors.map((a) => [rank(a.actor), -a.records, a]).filter((x) => x[0] != null)
      .sort((x, y) => x[0] - y[0] || x[1] - y[1] || cmp(x[2].actor, y[2].actor)).slice(0, limit).map((x) => x[2]);
    const places = ix.places.filter((p) => p.channel.toLowerCase().includes(ql) || p.channel.toLowerCase().includes(alt))
      .sort((a, b) => b.messages - a.messages || b.ops - a.ops).slice(0, limit);
    return { records: recs.slice(0, limit).map((id) => byId.get(id)), actors, places };
  }
  const LOCAL = { "/api/events": (ix, q) => search(ix, q, q.actor || "", int(q.offset, 0), int(q.limit, 100, 500)),
    "/api/x/units_events": unitsEvents, "/api/pairs": pairs, "/api/list": listing, "/api/search": omni };

  // ---------------------------------------------------------------- the api() the app calls
  async function api(path, opts) {
    if (opts && opts.method && String(opts.method).toUpperCase() !== "GET") throw new Error(UNAVAILABLE);
    const { path: p, q } = parse(path);
    let data;
    if (LOCAL[p]) data = LOCAL[p](await index(), q);
    else {
      data = await saved(p, q);
      // a record's short form is saved only where it differs from the full one
      if (data === undefined && p === "/api/event" && q.lite) { const { lite, ...rest } = q; data = await saved(p, rest); }
      // exports are written by the server on request (case file, SOC bundles, CSV)
      if (data === undefined) throw new Error(/_(export|csv)$/.test(p) ? UNAVAILABLE : NOT_SAVED);
    }
    if (data && data.$error) throw new Error(data.$error);
    return clone(data);
  }
  window.ST_STATIC = { api, parse, canon, fnv, UNAVAILABLE, NOT_SAVED };

  // ---------------------------------------------------------------- what the page says instead of failing
  // (the elements stay in the page, hidden by static.css, because core.js and the views bind to them)
  document.documentElement.classList.add("st-static");
  const INSTALL = "pipx install git+https://github.com/itsfingerlickinggood/swarm-tracer";
  const WHY = {
    load: ["Load your own trace", "The hosted demo shows one dataset: the simulated demo swarm that ships with Swarm Tracer. To analyze your own trace, install the tool. Your files stay on your machine."],
    live: ["Live mode", "Following a growing trace needs the local server, so it is not available in the hosted demo. Install Swarm Tracer to use it."],
    saved: ["Not in the hosted demo", "The hosted demo holds the answers the app needs for every tab, record, actor and place of the demo swarm. This drill-down was not saved with them. Install Swarm Tracer to open it."],
    need: ["Needs the installed tool", "This needs the local server, so it is not available in the hosted demo. Install Swarm Tracer to use it."],
    ai: ["AI investigator", "The AI investigator sends requests through the local server, so it is not available in the hosted demo. Install Swarm Tracer to use it."],
  };
  const noteHTML = (k) => `<h3>${WHY[k][0]}</h3><p>${WHY[k][1]}</p><p><code>${INSTALL}</code></p><p><code>swarm-tracer demo</code> opens this same demo locally, with everything switched on.</p>`;
  function notice(k, from) {
    let el = document.getElementById("stnotice");
    if (!el) {
      el = document.createElement("div"); el.id = "stnotice"; el.className = "stnotice"; el.setAttribute("role", "dialog");
      el.setAttribute("aria-modal", "false"); el.tabIndex = -1; document.body.appendChild(el);
    }
    el.setAttribute("aria-label", WHY[k][0]);
    el.innerHTML = noteHTML(k) + '<button type="button" class="primary" data-stclose>Close</button>';
    el.hidden = false; el.dataset.from = from && from.id ? from.id : "";
    el.querySelector("[data-stclose]").focus();
  }
  function closeNotice() {
    const el = document.getElementById("stnotice");
    if (!el || el.hidden) return;
    el.hidden = true;
    const back = el.dataset.from && document.getElementById(el.dataset.from);
    if (back) back.focus();
  }
  // capture phase: these run before the app's own handlers, which would call the missing server
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-stclose]")) { closeNotice(); return; }
    const hit = (sel) => e.target.closest(sel);
    const k = hit("#loadbtn") ? "load" : hit("#livebtn") ? "live" : hit("[data-ask-rec],[data-ask-q],#aiset,#aiwide") ? "ai" : null;
    if (!k) { if (!hit("#stnotice")) closeNotice(); return; }
    e.preventDefault(); e.stopImmediatePropagation();
    notice(k, hit("button"));
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNotice(); });
  // a view that does not catch a failed request would log an error: say what happened instead
  window.addEventListener("unhandledrejection", (e) => {
    const m = e.reason && e.reason.message;
    if (m !== NOT_SAVED && m !== UNAVAILABLE) return;
    e.preventDefault();
    notice(m === NOT_SAVED ? "saved" : "need", null);
  });

  const ai = document.querySelector(".pane.rbot");
  if (ai) {
    const n = document.createElement("div"); n.className = "stai";
    n.innerHTML = `<p><b>Not available in the hosted demo.</b> ${WHY.ai[1].replace(/^The AI investigator sends/, "It sends").replace(" Install Swarm Tracer to use it.", "")} Install to use it: <code>${INSTALL}</code></p>`;
    ai.appendChild(n);
    const line = document.getElementById("aiStateLine");
    if (line) { const s = document.createElement("span"); s.className = "muted"; s.textContent = "install to use"; line.after(s); }
  }
  const top = document.querySelector("header.top");
  if (top) {
    const b = document.createElement("a"); b.className = "stbadge"; b.href = "../"; b.title = "Read-only: the simulated demo swarm. Back to the Swarm Tracer site.";
    b.textContent = "Hosted demo · read-only";
    const anchor = document.getElementById("dsname");
    top.insertBefore(b, anchor ? anchor.nextSibling : null);
  }
})();

// Compare: the loaded swarm next to a second dataset (a path on this machine or an entry from the
// library of past incidents). The same measures, counted by the same code for both, as paired bars,
// plain sentences on what differs, and the two early-flag curves on one chart.
(() => {
  "use strict";
  const COL_A = ACCENT, COL_B = "#8a5cc2";
  GLOSSARY.two_way = ["Two-way pair", "Two named actors where each sent at least one message to the other. The share is out of every pair of named actors with a message in either direction."];
  GLOSSARY.adoption = ["Adoption speed", "For each program run by several named actors, the hours from its first run to the first run by another actor; the median over programs."];
  GLOSSARY.library = ["Library", "Known datasets and incidents (agenttrace/claims/library.json), with where to get each. Entries found on this machine can be loaded next to the current dataset."];

  const n = (x) => (x == null ? "–" : fmt(x));
  const pc = (x) => (x == null ? "–" : x > 0.99 && x < 1 ? (100 * x).toFixed(1) + "%" : pct(x));
  const hw = (x) => (x == null ? "–" : hoursWord(x));
  const swatch = (c) => `<i class="cmpsw" style="background:${c}"></i>`;

  async function view(el, s) {
    el.innerHTML = '<div id="cmpv"><p class="muted">Loading…</p></div>';
    const [cmp, lib, packs] = await Promise.all([
      api("/api/x/compare"), api("/api/x/library").catch(() => ({ entries: [] })), cached("/api/packs").catch(() => ({ packs: [] }))]);
    const host = $("cmpv");
    if (!host || S.tab !== "compare") return;
    draw(host, cmp, lib, packs.packs || []);
  }

  function loader(lib, packs, cmp) {
    const entries = lib.entries || [];
    const rows = entries.map((e) => `<div class="cmplib">
        <div class="cmplibt"><b>${esc(e.title)}</b> <span class="muted small">${esc(e.kind || "")}${e.pack ? " · pack " + esc(e.pack) : ""}</span></div>
        <div class="small">${esc(e.description || "")}</div>
        <div class="small muted">${e.available ? `On this machine: <code>${esc(e.available)}</code>` : `Not on this machine. ${esc(e.get_it || "")} ${e.source_url ? `<a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_url)}</a>` : ""}`}${e.context_available ? " · incident context included" : ""}</div>
        ${e.available ? `<button type="button" class="primary small" data-lib="${esc(e.id)}">Load to compare</button>` : ""}
      </div>`).join("");
    const opts = packs.map((p) => `<option value="${esc(p.file)}">${esc(p.name)}</option>`).join("");
    return card(`Load a second dataset`, `
      <div class="cmplibs">${rows || '<p class="muted small">The library is empty.</p>'}</div>
      <form id="cmpform" class="cmpform">
        <label>Path on this machine <input id="cmppath" placeholder="/path/to/trace.jsonl, a .csv, or a folder of trace files" autocomplete="off"></label>
        <label>Pack <select id="cmppack">${opts}</select></label>
        <button type="submit" class="primary">Load and compare</button>
      </form>
      <p id="cmpstatus" class="small ${cmp.error ? "bad" : "muted"}">${cmp.busy ? "A dataset is loading…" : cmp.error ? esc(cmp.error) : "Large datasets take up to a minute the first time; a second load comes from the disk cache."}</p>`,
      { sub: `Pick one from the ${term("library")} of past incidents, or give the path of any trace file or folder on this machine. It is analyzed here, next to the current dataset, and never uploaded anywhere.` });
  }

  // one measure as two bars on a shared scale
  function pair(label, a, b, { fmtv = n, max = null, note = "" } = {}) {
    const va = a == null ? null : +a, vb = b == null ? null : +b;
    const mx = max ?? Math.max(1e-9, va || 0, vb || 0);
    const bar = (v, c) => `<div class="cmpbar"><div class="ht"><i style="width:${v == null ? 0 : Math.max(v > 0 ? 0.8 : 0, (100 * v) / mx).toFixed(2)}%;background:${c}"></i></div><span>${fmtv(v)}</span></div>`;
    return `<div class="cmprow"><div class="cmpl">${label}${note ? `<span class="muted small">${note}</span>` : ""}</div><div class="cmpbars">${bar(va, COL_A)}${bar(vb, COL_B)}</div></div>`;
  }
  const group = (title, rows, sub = "") => card(title, `<div class="cmprows">${rows.join("")}</div>`, { sub });

  function signRows(a, b) {
    const out = [];
    for (const fam of ["joint", "single", "baseline"]) {
      const ga = a.first_sign[fam], gb = b.first_sign[fam];
      if (!ga && !gb) continue;
      const nm = (g) => g ? `${esc(g.name)} <span class="muted">· ${hw(g.hours_in)} in</span>` : '<span class="muted">none</span>';
      out.push(pair(`First sign: ${esc(FAMILY[fam]?.label || fam)}`, ga?.harm_share_after, gb?.harm_share_after,
        { fmtv: pc, max: 1, note: `<span>${swatch(COL_A)}${nm(ga)}</span><span>${swatch(COL_B)}${nm(gb)}</span>` }));
    }
    return out;
  }

  // rel: each swarm stretched over its own length (0-100%), so a short swarm next to a long one stays readable
  function curves(a, b, rel) {
    const W = 760, H = 250, L = 46, R = 14, T = 12, B = 34;
    const len = (m) => Math.max(1, m.curve.length ? m.curve[m.curve.length - 1][0] : m.hours || 1);
    const xmax = rel ? 1 : Math.max(1, ...[a, b].map(len));
    const sx = (m, h) => (rel ? h / len(m) : h);
    const X = (x) => L + (x / xmax) * (W - L - R), Y = (v) => T + (1 - v) * (H - T - B);
    let svg = `<svg class="cmpcurve" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Harm still to come against hours since the first dated action, for both datasets">`;
    for (const v of [0, 0.25, 0.5, 0.75, 1]) svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="10" fill="${QUIET}">${v * 100}%</text>`;
    if (rel) {
      for (let k = 0; k <= 10; k += 2) svg += `<line x1="${X(k / 10)}" x2="${X(k / 10)}" y1="${H - B}" y2="${H - B + 4}" stroke="${AXIS}"/><text x="${X(k / 10)}" y="${H - B + 16}" text-anchor="middle" font-size="10" fill="${QUIET}">${k * 10}%</text>`;
    } else {
      const step = xmax <= 24 ? 4 : xmax <= 72 ? 12 : xmax <= 24 * 10 ? 24 : 24 * Math.ceil(xmax / 24 / 10);
      for (let h = 0; h <= xmax; h += step) svg += `<line x1="${X(h)}" x2="${X(h)}" y1="${H - B}" y2="${H - B + 4}" stroke="${AXIS}"/><text x="${X(h)}" y="${H - B + 16}" text-anchor="middle" font-size="10" fill="${QUIET}">${h < 48 || h % 24 ? h + " h" : h / 24 + " d"}</text>`;
    }
    svg += `<text x="${(L + W - R) / 2}" y="${H - 3}" text-anchor="middle" font-size="10.5" fill="${QUIET}">${rel ? "share of each dataset's dated span, from its first to its last dated action" : "hours since each dataset's first dated action"}</text>`;
    [[a, COL_A], [b, COL_B]].forEach(([m, c]) => {
      if (!m.curve.length) return;
      let d = "";
      m.curve.forEach(([h, v], i) => { d += (i ? `H${X(sx(m, h)).toFixed(1)}V${Y(v).toFixed(1)}` : `M${X(sx(m, h)).toFixed(1)},${Y(v).toFixed(1)}`); });
      svg += `<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`;
      for (const fam of ["joint", "single", "baseline"]) {
        const g = fam === "baseline" ? m.volume_alarm : m.first_sign[fam];
        if (!g || g.hours_in == null || g.harm_share_after == null) continue;
        const gx = X(Math.min(sx(m, g.hours_in), xmax));
        const shape = fam === "joint" ? `<circle cx="${gx}" cy="${Y(g.harm_share_after)}" r="5" fill="${c}" stroke="#fff" stroke-width="1.5"/>`
          : fam === "single" ? `<rect x="${gx - 4}" y="${Y(g.harm_share_after) - 4}" width="8" height="8" fill="#fff" stroke="${c}" stroke-width="2"/>`
            : `<path d="M${gx},${Y(g.harm_share_after) - 6}l5,9h-10z" fill="#fff" stroke="${c}" stroke-width="2"/>`;
        svg += `<g>${shape}<title>${esc(m.name)}: ${esc(g.name)}, ${hw(g.hours_in)} after the first action, ${pc(g.harm_share_after)} of the harm still to come</title></g>`;
      }
    });
    return svg + `<line x1="${L}" x2="${L}" y1="${T}" y2="${H - B}" stroke="${AXIS}"/></svg>`;
  }

  function draw(host, cmp, lib, packs) {
    const a = cmp.a, b = cmp.b;
    const head = `<div class="cmphead">
        <div class="cmpside">${swatch(COL_A)}<b>${esc(a.name)}</b><span class="muted small">loaded now · ${esc(a.pack)} · ${n(a.records)} records</span></div>
        <div class="cmpvs">vs</div>
        <div class="cmpside">${swatch(COL_B)}${b ? `<b>${esc(b.name)}</b><span class="muted small">${esc(b.pack)} · ${n(b.records)} records${cmp.b_source?.seconds != null ? ` · loaded in ${cmp.b_source.seconds} s` : ""}</span> <button type="button" class="link small" id="cmpclear">Compare with another</button>` : '<span class="muted">choose a second dataset below</span>'}</div>
      </div>`;
    if (!b) {
      host.innerHTML = head + loader(lib, packs, cmp);
      bindLoader(host);
      return;
    }
    const diffs = cmp.differences || [];
    // two swarms of very different lengths: stretch each over its own span by default
    const la = a.curve.at(-1)?.[0] || a.hours || 1, lb = b.curve.at(-1)?.[0] || b.hours || 1;
    const rel = Math.max(la, lb) / Math.max(1, Math.min(la, lb)) > 5;
    const types = [...new Set([...Object.keys(a.places_by_type), ...Object.keys(b.places_by_type)])]
      .sort((x, y) => ((b.places_by_type[y]?.places || 0) + (a.places_by_type[y]?.places || 0)) - ((b.places_by_type[x]?.places || 0) + (a.places_by_type[x]?.places || 0)));
    const gb = Object.fromEntries(b.gaps.map((g) => [g.key, g]));
    const gaps = a.gaps.filter((g) => gb[g.key]).map((g) => pair(esc(g.gap), g.share, gb[g.key].share, { fmtv: pc, max: 1 }));
    const legend = `<span class="legend cmplegend"><span>${swatch(COL_A)}${esc(a.name)}</span><span>${swatch(COL_B)}${esc(b.name)}</span></span>`;
    host.innerHTML = head + card("What differs", diffs.length ? `<ul class="cmpdiff">${diffs.map((d) => `<li>${esc(d.text)}</li>`).join("")}</ul>` : '<p class="muted">No measure differs by much: within 1.5x on counts and 10 points on shares.</p>',
      { sub: "The largest differences first. Counts are compared as ratios, shares as percentage points; every number is counted by the same code for both datasets." })
      + `<div class="grid2">`
      + group("Size", [
        pair(term("record", "Records"), a.records, b.records),
        pair(term("dated", "Dated share"), a.dated_share, b.dated_share, { fmtv: pc, max: 1 }),
        pair(term("named", "Named actors"), a.named_actors, b.named_actors),
        pair(term("action", "Actions"), a.actions, b.actions),
        pair(term("run", "Actions by anonymous runs"), a.unattributed_share, b.unattributed_share, { fmtv: pc, max: 1 }),
        pair(term("place", "Places"), a.places, b.places),
        pair(term("harm", "Harmful actions (dated)"), a.harm_total, b.harm_total)], legend)
      + group("Who talked to whom", [
        pair(term("message", "Messages between named actors"), a.messages_named, b.messages_named),
        pair(term("merged", "… on places that may be merged"), a.messages_named_merged, b.messages_named_merged),
        pair("Sender-receiver pairs", a.pairs, b.pairs),
        pair(term("two_way", "Pairs that wrote both ways"), a.two_way_share, b.two_way_share, { fmtv: pc, max: 1 }),
        pair(term("group", "Largest linked group"), a.largest_group, b.largest_group),
        pair(term("latency", "Median wait"), a.wait_median_h, b.wait_median_h, { fmtv: hw }),
        pair(term("latency", "90th percentile wait"), a.wait_p90_h, b.wait_p90_h, { fmtv: hw })], legend)
      + `</div><div class="grid2">`
      + group("How information spread", [
        pair(term("program", "Programs shared"), a.programs_shared, b.programs_shared),
        pair(term("adoption", "Median time to first reuse"), a.adoption_median_h, b.adoption_median_h, { fmtv: hw }),
        ...types.map((t) => pair(esc(placeType(t, 2)), a.places_by_type[t]?.places ?? 0, b.places_by_type[t]?.places ?? 0,
          { note: `messages: ${n(a.places_by_type[t]?.messages ?? 0)} / ${n(b.places_by_type[t]?.messages ?? 0)}` }))],
        `Places by type below the line: places in each dataset, with the messages through them.`)
      + group("Could it be flagged early", [
        ...signRows(a, b),
        pair(term("volume", "Volume alarm"), a.volume_alarm?.harm_share_after, b.volume_alarm?.harm_share_after,
          { fmtv: pc, max: 1, note: `<span>${swatch(COL_A)}${a.volume_alarm ? hw(a.volume_alarm.hours_in) + " in" : "never fires"}</span><span>${swatch(COL_B)}${b.volume_alarm ? hw(b.volume_alarm.hours_in) + " in" : "never fires"}</span>` }),
        pair(term("sign", "Warning signs that fired"), a.signals, b.signals)],
        `Bars: ${term("harm_left")} when the first sign of each kind fired; higher is earlier.`)
      + `</div>`
      + card("The two early-flag curves", `<div id="cmpcurvebox">${curves(a, b, rel)}</div>` + legend + `<p class="small muted">Shapes: ● first sign of actors together, ■ first single-actor sign, ▲ volume alarm. Hover a shape for its time.</p>`,
        { sub: `${term("harm_left")} against time since each dataset's own first dated action, so swarms of different dates share one axis. A curve that stays high for longer leaves more time to act; a sign high on its curve fired early.`,
          right: `<span class="cmptoggle small"><button type="button" data-rel="0" class="${rel ? "" : "on"}">Hours</button><button type="button" data-rel="1" class="${rel ? "on" : ""}">Share of span</button></span>` })
      + (gaps.length ? group("What an investigator would still miss", gaps, "Share of records, actions, messages or places affected by each measured blind spot; lower is better.") : "");
    host.querySelectorAll("[data-rel]").forEach((btn) => btn.addEventListener("click", () => {
      $("cmpcurvebox").innerHTML = curves(a, b, btn.dataset.rel === "1");
      host.querySelectorAll("[data-rel]").forEach((x) => x.classList.toggle("on", x === btn));
    }));
    host.querySelector("#cmpclear")?.addEventListener("click", async () => {
      await api("/api/x/compare_clear", { method: "POST", body: "{}" }).catch(() => {});
      render();
    });
  }

  function bindLoader(host) {
    const st = host.querySelector("#cmpstatus");
    const go = async (payload, label) => {
      host.querySelectorAll("button").forEach((x) => (x.disabled = true));
      st.className = "small muted";
      st.textContent = `Analyzing ${label}… large datasets take up to a minute the first time.`;
      const t0 = Date.now();
      const tick = setInterval(() => { st.textContent = `Analyzing ${label}… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      try {
        await api("/api/x/compare_load", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        clearInterval(tick);
        if (S.tab === "compare") render();
      } catch (e) {
        clearInterval(tick);
        st.className = "small bad"; st.textContent = e.message;
        host.querySelectorAll("button").forEach((x) => (x.disabled = false));
      }
    };
    host.querySelectorAll("[data-lib]").forEach((btn) => btn.addEventListener("click", () => go({ library: btn.dataset.lib }, btn.closest(".cmplib").querySelector("b").textContent)));
    host.querySelector("#cmpform").addEventListener("submit", (e) => {
      e.preventDefault();
      const path = host.querySelector("#cmppath").value.trim();
      if (!path) { st.className = "small bad"; st.textContent = "Enter the path of a trace file or folder."; return; }
      go({ path, pack: host.querySelector("#cmppack").value }, path);
    });
  }

  VIEWS.compare = view;
})();

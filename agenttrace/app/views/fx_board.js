// Forensics, "The message board, rebuilt": the Artifactory board folders the payloads touched, decoded into a
// message-type vocabulary, linked write to read, and drawn as a funnel, a timeline and a flow. Server: agenttrace/board.py.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const TYPE_COL = { file: "#2f6fb3", probe: "#d35400", beacon: "#c9a227", payload: "#7c4dbd", modal: "#1f9bb4", result: "#2e9d5b",
    channel: "#b8579a", stage: "#8c564b", mailbox: "#6aa5dc", command: "#c2410c", other: "#aab3bd" };
  const CLS = { token: "#5d6d7e", probable: "#0f766e", anonymous: "#c3cad2", none: "#e8ebef" };
  const CLS_WORD = { token: "named", probable: "probable agent", anonymous: "anonymous", none: "not seen" };
  const ST = { mode: "all", folder: null };
  Object.assign(GLOSSARY, {
    board_folder: ["Board folder", "A directory the agents created in the shared package cache (github-remote-cache/zz...). The release shows the requests that touched it, not what it held."],
    board_type: ["Message type", "A class read off the folder's name (FILE_, RESULT_, INBOX_, BEACON...). The rules are listed under the vocabulary table; the name is all the release gives."],
    board_side: ["Named, probable or anonymous", "Named: an identity token (or a handle) is in the record. Probable: an anonymous run linked to a named agent by shared rare material, with a confidence band. Anonymous: nothing links the record to anyone."],
  });
  const p1 = (x) => x == null ? "–" : (100 * x).toFixed(x < 0.1 && x > 0 ? 1 : 0) + "%";
  const col = (t) => TYPE_COL[t] || "#aab3bd";
  const opBadge = (o) => `<span class="op ${esc(o)}">${esc(o)}</span>`;
  const sideChip = (cl, actor, band) => `<span class="fxb-side" style="--c:${CLS[cl] || CLS.anonymous}">${esc(CLS_WORD[cl] || cl)}${band && band !== "named" ? " · " + esc(band) : ""}</span> ${actor && cl !== "anonymous" ? ent.actor(actor) : actor ? ent.actor(actor) : ""}`;
  const dayLabel = (h) => { const d = new Date(h.replace(" ", "T") + ":00Z"); return d.toUTCString().slice(5, 11); };

  function mini(m, keys = ["token", "probable", "anonymous"]) {
    const tot = keys.reduce((a, k) => a + (m[k] || 0), 0);
    if (!tot) return '<span class="muted">–</span>';
    return `<span class="fxb-mini" title="${keys.map((k) => `${CLS_WORD[k]}: ${m[k] || 0}`).join(", ")}">${keys.map((k) => m[k] ? `<i style="flex:${m[k]};background:${CLS[k]}"></i>` : "").join("")}</span> <b>${fmt(tot)}</b>`;
  }

  // ---------------------------------------------------------------- funnel
  function funnel(r) {
    const f = r.funnel, W = 460, L = 128, bw = 250, rows = [
      ["folders named", f.folders, "#9aa5b1"], ["write seen", f.written, "#2f6fb3"], ["read seen", f.read, "#2e9d5b"],
      ["both seen", f.both, "#c9a227"], ["linked delivery", f.linked, "#c2410c"]];
    const bars = rows.map((x, i) => {
      const w = Math.max(2, bw * x[1] / f.folders), y = 4 + i * 30;
      return `<g><text x="${L - 8}" y="${y + 16}" text-anchor="end" font-size="13" fill="#39424d">${esc(x[0])}</text>
        <rect x="${L}" y="${y}" width="${bw}" height="22" rx="4" fill="#f2f4f6"/><rect x="${L}" y="${y}" width="${w.toFixed(1)}" height="22" rx="4" fill="${x[2]}"><title>${esc(x[0])}: ${x[1]}</title></rect>
        <text x="${L + bw + 6}" y="${y + 16}" font-size="13" font-weight="650" fill="#1f2933">${fmt(x[1])}</text></g>`;
    }).join("");
    const parts = [["written only", f.written_only, "#2f6fb3"], ["both", f.both, "#c9a227"], ["read only", f.read_only, "#2e9d5b"], ["neither", f.folders - f.written - f.read_only, "#e8ebef"]];
    const seg = parts.filter((p) => p[1] > 0).map((p) => `<i style="width:${(100 * p[1] / f.folders).toFixed(3)}%;background:${p[2]};min-width:2px" title="${p[0]}: ${p[1]}">${p[1] / f.folders > 0.15 ? `<b>${fmt(p[1])}</b>` : ""}</i>`).join("");
    return card("What the release lets us see", `<svg class="fxb-svg" viewBox="0 0 ${W} 158" role="img" aria-label="Funnel of board folders">${bars}</svg>
      <h4 class="fxb-h">Every folder in exactly one bucket</h4><div class="fxb-part">${seg}</div>
      <div class="legend">${parts.map((p) => `<span><i style="background:${p[2]}"></i>${p[0]} ${fmt(p[1])}</span>`).join("")}</div>`,
      { sub: `${fmt(f.folders)} ${term("board_folder", "folders")}, ${fmt(f.writes)} writes and ${fmt(f.reads)} reads seen. Most folders show one side only: the payloads of the writers, or of the readers, are not both in the release.` });
  }

  // ---------------------------------------------------------------- vocabulary
  function vocab(r) {
    const items = r.types.map((t) => `<div class="fxb-vt"><div class="fxb-vh"><span class="fxb-sw" style="background:${col(t.type)}"></span><b>${esc(t.label)}</b> <span class="muted small">${esc(t.meaning)}</span></div>
      <div class="fxb-vg"><span><b>${fmt(t.folders)}</b> folders</span><span>write ${fmt(t.written)} · read ${fmt(t.read)} · both ${fmt(t.both)}</span><span class="muted">${esc((t.first || "–").slice(5))} to ${esc((t.last || "–").slice(5))}</span></div>
      <div class="fxb-vg"><span>writes ${mini(t.writers)}</span><span>reads ${mini(t.readers)}</span></div>
      <div class="fxb-ex">${t.examples.slice(0, 2).map((e) => `<code class="fxb-code">${esc(e)}</code>`).join("")}</div></div>`).join("");
    const rules = r.rules.map((x) => `<tr><td><span class="fxb-sw" style="background:${col(x.type)}"></span>${esc(x.label)}</td><td><code>${esc(x.pattern)}</code></td></tr>`).join("");
    return card(`The ${term("board_type", "message types")} the names spell out`,
      `<div class="fxb-vocab">${items}</div>
       <div class="legend">${["token", "probable", "anonymous"].map((k) => `<span><i style="background:${CLS[k]}"></i>${CLS_WORD[k]}</span>`).join("")}</div>
       <details class="fxb-rules"><summary>Naming rules (first match on the name after "zz", upper-cased)</summary><div class="tablewrap"><table><tbody>${rules}</tbody></table></div>
       <p class="muted small">Folders with a version suffix (_V1, _V2...): ${fmt(r.naming.versioned)}; ${fmt(r.naming.stems_with_revisions)} series have several versions${r.naming.max_version ? `, up to V${r.naming.max_version}` : ""}.</p></details>`,
      { sub: `${fmt(r.other.folders)} folders (${p1(r.other.share)}) match no rule and stay in <b>Other</b>${r.other.names.length ? ": " + r.other.names.slice(0, 6).map((n) => `<code class="fxb-code">${esc(n)}</code>`).join(" ") + (r.other.folders > 6 ? " …" : "") : ""}. Writers and readers count operations, not people. File folders show reads only: whoever wrote the chunks is not in the release.` });
  }

  // ---------------------------------------------------------------- stacked timeline
  function timeline(host, r) {
    const hours = r.hours, nh = hours.length;
    if (!nh) { host.innerHTML = card("Protocol timeline", '<p class="muted">No dated board operations.</p>'); return; }
    const types = r.type_order;           // largest first at the bottom
    const val = (t, i) => { const s = r.series[t]; return ST.mode === "writes" ? s.w[i] : ST.mode === "reads" ? s.r[i] : s.w[i] + s.r[i]; };
    const tot = hours.map((_, i) => types.reduce((a, t) => a + (r.series[t] ? val(t, i) : 0), 0));
    const mx = Math.max(1, ...tot), W = 460, X0 = 30, PW = 424, H = 150, Y0 = 8, PH = 118, bw = PW / nh;
    let s = [0, 0.5, 1].map((f) => `<line x1="${X0}" x2="${X0 + PW}" y1="${Y0 + PH - f * PH}" y2="${Y0 + PH - f * PH}" stroke="#e5e8ec"/><text x="${X0 - 5}" y="${Y0 + PH - f * PH + 4}" text-anchor="end" font-size="11" fill="#5b6672">${fmt(Math.round(mx * f))}</text>`).join("");
    hours.forEach((h, i) => {
      let y = Y0 + PH;
      types.forEach((t) => {
        if (!r.series[t]) return;
        const v = val(t, i); if (!v) return;
        const hh = PH * v / mx; y -= hh;
        s += `<rect x="${(X0 + i * bw).toFixed(2)}" y="${y.toFixed(2)}" width="${Math.max(1, bw - 0.6).toFixed(2)}" height="${hh.toFixed(2)}" fill="${col(t)}"><title>${esc(h)} UTC · ${esc(r.labels[t])}: ${v}</title></rect>`;
      });
      if (h.endsWith("00:00")) s += `<line x1="${X0 + i * bw}" x2="${X0 + i * bw}" y1="${Y0}" y2="${Y0 + PH + 5}" stroke="#aab3bd" stroke-dasharray="2 3"/><text x="${X0 + i * bw + 3}" y="${Y0 + PH + 16}" font-size="11" fill="#5b6672">${esc(dayLabel(h))}</text>`;
    });
    const hx = (iso) => { const i = hours.indexOf(iso.slice(0, 13) + ":00"); return X0 + (i < 0 ? 0 : i) * bw + bw / 2; };
    const marks = r.first_appearances.map((f) => `<circle cx="${hx(f.time)}" cy="${H - 6}" r="3.5" fill="${col(f.type)}"><title>${esc(f.label)} first seen ${esc(f.time)} UTC (${esc(f.folder)})</title></circle>`).join("");
    const firsts = r.first_appearances.map((f) => `<div class="fxb-fa"><span class="fxb-sw" style="background:${col(f.type)}"></span><b>${esc(f.label)}</b> <span class="muted">${esc(f.time.slice(5))}</span> ${ent.rec(f.record)}</div>`).join("");
    const btn = (m, l) => `<button type="button" class="fxb-mode${ST.mode === m ? " on" : ""}" data-mode="${m}">${l}</button>`;
    host.innerHTML = card("The protocol timeline: operations per hour by type",
      `<div class="fxb-modes">${btn("all", "all")}${btn("writes", "writes")}${btn("reads", "reads")}</div><div class="legend" style="margin:4px 0 4px">${r.type_order.map((t) => `<span><i style="background:${col(t)}"></i>${esc(r.labels[t])}</span>`).join("")}</div>
       <svg class="fxb-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Board operations per hour, stacked by message type">${s}${marks}</svg><h4 class="fxb-h">First appearance of each type (UTC)</h4><div class="fxb-fas">${firsts}</div>`,
      { sub: `Hours in UTC. Dots mark the first appearance of each type, in time order. ${r.undated_ops ? fmt(r.undated_ops) + " undated operations are not drawn." : ""}` });
    host.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { ST.mode = b.dataset.mode; timeline(host, r); }));
  }

  // ---------------------------------------------------------------- bipartite flow
  function sankey(r) {
    const rows = r.flow.rows;
    if (!rows.length) return card("Who writes what, who reads it", '<p class="muted">No flows.</p>');
    const LC = ["token", "probable", "anonymous", "none"], types = r.type_order.filter((t) => rows.some((x) => x.t === t));
    const sum = (f) => rows.filter(f).reduce((a, x) => a + x.n, 0);
    const W = 520, H = 400, NW = 12, XL = 118, XM = 200, XR = 400, GAP = 6, MINH = 14, MW = 108;
    function layout(keys, valOf) {
      const vals = keys.map(valOf).map((v) => v), tot = vals.reduce((a, b) => a + b, 0);
      const live = vals.filter((v) => v > 0).length;
      let k = (H - GAP * (live - 1)) / tot;
      for (let it = 0; it < 4; it++) { const small = vals.filter((v) => v > 0 && v * k < MINH); const rest = tot - small.reduce((a, b) => a + b, 0); k = (H - GAP * (live - 1) - MINH * small.length) / rest; }
      let y = 0; const pos = {};
      keys.forEach((key, i) => { if (!vals[i]) return; const h = Math.max(MINH, vals[i] * k); pos[key] = { y, h, k: h / vals[i], off: 0, n: vals[i] }; y += h + GAP; });
      return pos;
    }
    const L = layout(LC, (c) => sum((x) => x.l === c)), M = layout(types, (t) => sum((x) => x.t === t)), R = layout(LC, (c) => sum((x) => x.r === c));
    const lcls = (c) => c === "none" ? "writer unseen" : (c === "probable" ? "probable" : CLS_WORD[c]), rcls = (c) => c === "none" ? "no reader seen" : (c === "probable" ? "probable" : CLS_WORD[c]);
    let links = "";
    const place = (node, n) => { const y = node.y + node.off; node.off += n * node.k; return [y, y + n * node.k]; };
    const path = (x0, y0a, y0b, x1, y1a, y1b) => { const mx = (x0 + x1) / 2; return `M${x0} ${y0a} C${mx} ${y0a} ${mx} ${y1a} ${x1} ${y1a} L${x1} ${y1b} C${mx} ${y1b} ${mx} ${y0b} ${x0} ${y0b} Z`; };
    // left -> type, ordered by type then class so ribbons do not cross inside a node
    const lt = {}, tr = {};
    rows.forEach((x) => { lt[x.l + "|" + x.t] = (lt[x.l + "|" + x.t] || 0) + x.n; tr[x.t + "|" + x.r] = (tr[x.t + "|" + x.r] || 0) + x.n; });
    LC.forEach((l) => types.forEach((t) => { const n = lt[l + "|" + t]; if (!n) return; const a = place(L[l], n), b = place(M[t], n);
      links += `<path d="${path(XL + NW, a[0], a[1], XM, b[0], b[1])}" fill="${col(t)}" fill-opacity=".42"><title>${esc(lcls(l))} → ${esc(r.labels[t])}: ${fmt(n)}</title></path>`; }));
    types.forEach((t) => LC.forEach((c) => { const n = tr[t + "|" + c]; if (!n) return; const a = place(M[t], n), b = place(R[c], n);
      links += `<path d="${path(XM + MW, a[0], a[1], XR, b[0], b[1])}" fill="${col(t)}" fill-opacity=".42"><title>${esc(r.labels[t])} → ${esc(rcls(c))}: ${fmt(n)}</title></path>`; }));
    let nodes = "";
    LC.forEach((c) => { const p = L[c]; if (!p) return; nodes += `<rect x="${XL}" y="${p.y}" width="${NW}" height="${p.h}" fill="${CLS[c]}"/><text x="${XL - 8}" y="${p.y + p.h / 2 + 4}" text-anchor="end" font-size="12.5" fill="#39424d">${esc(lcls(c))} <tspan font-weight="650">${fmt(p.n)}</tspan></text>`; });
    LC.forEach((c) => { const p = R[c]; if (!p) return; nodes += `<rect x="${XR}" y="${p.y}" width="${NW}" height="${p.h}" fill="${CLS[c]}"/><text x="${XR + NW + 8}" y="${p.y + p.h / 2 + 4}" font-size="12.5" fill="#39424d">${esc(rcls(c))} <tspan font-weight="650">${fmt(p.n)}</tspan></text>`; });
    types.forEach((t) => { const p = M[t]; nodes += `<rect x="${XM}" y="${p.y}" width="${MW}" height="${p.h}" rx="3" fill="${col(t)}"/><text x="${XM + 7}" y="${p.y + p.h / 2 + 4}" font-size="11.5" fill="#fff" font-weight="600">${esc(r.labels[t].replace("Stage / callback","Stage").replace("Payload / data","Payload").replace("Command / lock","Command").replace("Modal sandbox","Modal").replace("File sharing","File"))} <tspan font-weight="400">${fmt(p.n)}</tspan></text>`; });
    const f = r.flow;
    return card("Who writes what, and who reads it",
      `<svg class="fxb-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Writers, message types and readers">${links}${nodes}</svg>`,
      { sub: `Each unit is one ${term("board_side", "delivery")} (a read after a write of the same folder by another actor: ${fmt(f.deliveries)}), a write with no read seen (${fmt(f.unread_writes)}), or a read with no earlier write seen (${fmt(f.reads_no_writer)}). Left of the types: the writer; right: the reader. ${f.repeat_reads || f.undated_reads ? `Not drawn: ${fmt(f.repeat_reads)} repeat reads, ${fmt(f.undated_reads)} undated reads. ` : ""}${f.same_agent_links ? `${fmt(f.same_agent_links)} deliveries resolve to one agent on both sides. ` : ""}Hover a ribbon for its count.` });
  }

  // ---------------------------------------------------------------- busiest folders + detail
  function busiest(r) {
    const rows = r.top_folders.slice(0, 15).map((t, i) => `<div class="fxb-bf" data-i="${i}"><div>${ent.place(t.channel)}</div>
      <div class="fxb-vg"><span><span class="fxb-sw" style="background:${col(t.type)}"></span>${esc(r.labels[t.type])}</span><span>${fmt(t.writes)} writes</span><span>${fmt(t.reads)} reads</span><span>${fmt(t.deliveries)} linked</span><span class="muted">${esc((t.first || "–").slice(5))}</span></div></div>`).join("");
    return card("The busiest folders", `<div id="fxbTop">${rows}</div>`,
      { sub: "Click a row to open the folder's operations in time order. Chips open the place or a record." });
  }

  async function detail(name) {
    const box = $("fxbDetail");
    if (!box) return;
    box.innerHTML = `<p class="muted">Loading ${esc(name)}…</p>`;
    let d;
    try { d = await api("/api/x/board_folder?name=" + encodeURIComponent(name)); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    if (!box.isConnected) return;
    const ops = d.ops.slice(0, 80).map((o) => [esc(o.time ? o.time.slice(5) : "–"), opBadge(o.op), sideChip(o.class, o.actor, o.band), ent.rec(o.record), `<code class="fxb-snip">${esc(o.snippet)}</code>`]);
    const dl = d.deliveries.slice(0, 20).map((x) => `<div class="mline"><span class="fxb-side" style="--c:${CLS[x.from_class]}">${esc(CLS_WORD[x.from_class])}</span> ${ent.actor(x.from)} wrote in ${ent.rec(x.write_id)} <span class="muted">${esc(x.write_time || "")}</span> → <span class="fxb-side" style="--c:${CLS[x.to_class]}">${esc(CLS_WORD[x.to_class])}</span> ${ent.actor(x.to)} read in ${ent.rec(x.read_id)} <span class="muted">${esc(x.read_time || "")} (${esc(String(x.latency_h))} h later)</span></div>`).join("");
    box.innerHTML = card(`Folder ${esc(d.folder)}`,
      `<div class="fxb-dh"><span class="fxb-sw" style="background:${col(d.type)}"></span><b>${esc(d.label)}</b> <span class="muted small">${esc(d.meaning)} · ${plural(d.writes, "write")} · ${plural(d.reads, "read")}</span></div>
       ${d.revisions.length ? `<p class="small muted">Other versions: ${d.revisions.map((n) => `<code class="fxb-code">${esc(n)}</code>`).join(" ")}</p>` : ""}
       <h4 class="fxb-h">Linked deliveries (${fmt(d.deliveries_total)})</h4>${dl || '<p class="muted small">No read follows a write by another actor in the release.</p>'}
       <h4 class="fxb-h">Operations in time order${d.ops_total > 80 ? ` (first 80 of ${fmt(d.ops_total)})` : ""}</h4>${`<div class="fxb-ops">${ops.map((o) => `<div class="fxb-op">${o.join(" ")}</div>`).join("")}</div>`}`,
      { sub: "Record text is data: shown only as short quotes. Open a record chip for the whole record." });
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---------------------------------------------------------------- what can be inferred
  function infer(r) {
    const v = r.visible, c = r.claims, f = r.funnel;
    const q = c.quotes.map((x) => `<blockquote class="fxb-q">${esc(x.text)} <span class="muted small">${esc(x.source || "")}</span></blockquote>`).join("");
    return card("What this implies, and what it does not",
      `<div class="kpis">${kpi("folders named", fmt(v.named_folders))}${kpi("with write and read seen", fmt(v.complete_exchange_folders), p1(v.complete_share_of_visible) + " of folders")}${kpi("file folders", fmt(v.file_folders), v.claim_files ? "vs ≥ " + fmt(v.claim_files) + " files claimed" : "")}</div>
       ${q ? `<h4 class="fxb-h">What the reports say (quoted from the claims file)</h4>${q}` : ""}
       <ul class="fxb-inf">
        <li>In ${fmt(v.named_folders)} folders, a write was seen in ${fmt(f.written)}, a read in ${fmt(f.read)}, and both in <b>${fmt(f.both)}</b>. At least that many folders show a complete exchange in the release: a <b>floor on the visible share</b>, in folders.</li>
        ${v.claim_entries ? `<li>The claim counts <b>entries</b> (≥ ${fmt(v.claim_entries)}) and files (≥ ${fmt(v.claim_files)}), not folders, so ${fmt(v.named_folders)} named folders cannot be divided by it to give a share of the board. The nearest like-for-like figure is the ${fmt(v.file_folders)} folders named like files against ≥ ${fmt(v.claim_files)} files: at most about ${p1(v.file_folders_vs_claim_files)} if each file were one folder, which it need not be.</li>` : ""}
        ${v.claim_share_pct ? `<li>The ${v.claim_share_pct}% figure says the main namespace carries nearly all Artifactory messaging, so the board is the right thing to reconstruct. It does not say how much of the board the release samples: the other direction (what the payloads leave out) is not covered by it.</li>` : ""}
        <li>Every folder with only one side seen is missing the other side's payload. That says the release lacks those payloads, not that the message went unread or unwritten.</li></ul>`,
      { sub: "Honest limits first: the count is a lower bound on what is visible, never an estimate of the whole board.", cls: "fxb-infer" });
  }

  async function render(host) {
    const r = await api("/api/x/board");
    if (!host.isConnected) return;
    const f = r.funnel;
    host.innerHTML = `<p class="fxb-caveat"><b>The board's contents are not in the release.</b> ${esc(r.caveats[0])} ${esc(r.caveats[3])}</p>
      <div class="kpis">${kpi("folders", fmt(f.folders))}${kpi("writes seen", fmt(f.writes))}${kpi("reads seen", fmt(f.reads))}${kpi("both seen", fmt(f.both), "folders")}${kpi("linked deliveries", fmt(f.deliveries))}${kpi("message types", fmt(r.types.length - (r.types.some((t) => t.type === "other") ? 1 : 0)), p1(r.other.share) + " other")}</div>
      ${funnel(r)}<div id="fxbTl"></div>${vocab(r)}${sankey(r)}${busiest(r)}<div id="fxbDetail"></div>${infer(r)}
      <div class="card fxb-cav"><header><h3>Caveats</h3></header><ul>${r.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>
      <p class="muted small">Computed in ${r.seconds} s${r.attribution ? "" : "; attribution was not available, so every unnamed side is anonymous"}.</p>`;
    timeline($("fxbTl"), r);
    document.querySelectorAll("#fxbTop .fxb-bf").forEach((el) => el.addEventListener("click", (e) => { if (!e.target.closest(".ent")) detail(r.top_folders[+el.dataset.i].folder); }));
    if (r.top_folders[0]) detail(r.top_folders[0].folder);
  }

  window.FX_SECTIONS.push({
    id: "board", title: "The message board, rebuilt", group: "How agents behaved",
    blurb: "The release holds the requests that touched the Artifactory board, not its contents. This section decodes the folder names into message types, links writes to reads, and says how much of the board that lets us see.",
    render,
  });
})();

// Forensics, "Test and export": what-if mode (your decisions applied to the counts and signs), a reference
// swarm as the yardstick, the chain of custody, and exports for a SOC (timeline CSV, Timesketch CSV, STIX 2.1,
// alert rules as detections). Server side: agenttrace/fx_whatif.py.
(() => {
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
const G = "Test and export";

GLOSSARY.whatif = ["What-if mode", "Your decisions applied to the counts: identity merges from the Agents tab (tokens you judged to be one agent), messages you rejected and signs you rejected. Every number is recounted from the same records by the same rules, so the difference comes only from your decisions."];
GLOSSARY.agent_estimate = ["Estimated agents", "Named actors after merging the tokens that are probably one agent. The Agents tab's estimate merges every high-confidence pair you did not reject, plus every pair you accepted."];
GLOSSARY.self_talk = ["Inside one agent", "A message whose writer and reader turn out to be the same agent once tokens are merged. It is not communication between agents, so it drops out of the counts."];
GLOSSARY.reference = ["Reference swarm", "A second dataset used as the yardstick, ideally a benign swarm. Each measure of the swarm under investigation is set against it as a ratio (for counts and rates) or a difference in points (for shares)."];
GLOSSARY.custody = ["Chain of custody", "What produced this analysis, so anyone can check it: the SHA-256 of every input file, a SHA-256 of all record ids, the pack and its hash, the tool's version and build, and when it was loaded. The same block goes into every export."];
GLOSSARY.stix = ["STIX 2.1", "The OASIS standard JSON format for sharing threat intelligence. The bundle holds the actors as pseudonymous identities, the places as indicators, and each warning sign as a sighting of an attack pattern labelled with its stage."];
GLOSSARY.timesketch = ["Timesketch", "Google's open-source timeline tool. Its CSV import needs message, datetime (ISO 8601) and timestamp_desc columns; extra columns become searchable fields."];

const sgn = (d) => d == null ? "" : d > 0 ? `+${fmt(d)}` : d < 0 ? `−${fmt(-d)}` : "±0";
const hl = (x) => x == null ? "–" : pct(x);

// ------------------------------------------------------------------ downloads
function download(name, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime || "application/octet-stream" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
const sizeWord = (b) => b == null ? "" : b < 1024 ? `${b} bytes` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB`;

// ------------------------------------------------------------------ what-if
const WI = { rule: "estimate" };
async function renderWhatif(host) {
  host.innerHTML = '<p class="muted">Recounting…</p>';
  const w = await api(`/api/x/fx_whatif?rule=${WI.rule}`);
  drawWhatif(host, w);
}
function deltaRow(label, a, b, { fmtv = fmt, note = "" } = {}) {
  const d = a != null && b != null && typeof a === "number" ? b - a : null;
  return `<tr><td>${label}${note ? `<div class="small muted">${note}</div>` : ""}</td><td class="num">${fmtv(a)}</td><td class="num"><b>${fmtv(b)}</b></td><td class="num ${d ? "wi-d" : "muted"}">${d == null ? "" : sgn(d)}</td></tr>`;
}
function firstMsg(m) {
  if (!m) return '<span class="muted">none</span>';
  return `${esc(when(toTime(m.time)))} · ${ent.actor(m.from)} → ${ent.actor(m.to)} ${ent.rec(m.read_id)} <span class="muted small">${hl(m.harm_share_after)} of harm still to come</span>`;
}
function drawWhatif(host, w) {
  const a = w.as_counted, b = w.after, d = w.decisions;
  const fa = w.first_joint.as_counted, fb = w.first_joint.after;
  const statusWord = { unchanged: "same", later: "later", earlier: "earlier", gone: "no longer fires", rejected: "rejected by you" };
  const anyDecision = d.merges_accepted + d.merges_rejected + d.messages_rejected + d.signs_rejected > 0;
  host.innerHTML = `
    <div class="wi-bar">
      <span class="small muted">Merges to apply:</span>
      <button type="button" data-rule="estimate" class="${WI.rule === "estimate" ? "on" : ""}" title="High-confidence pairs you did not reject, plus pairs you accepted">${term("agent_estimate", "the Agents tab's estimate")}</button>
      <button type="button" data-rule="accepted" class="${WI.rule === "accepted" ? "on" : ""}" title="Only the pairs you accepted in the Agents tab">only merges you accepted</button>
      <span class="small muted wi-dec">Your decisions: ${plural(d.merges_accepted, "merge")} accepted, ${fmt(d.merges_rejected)} rejected in the <button type="button" class="link" data-go="agents">Agents tab</button> · ${plural(d.messages_rejected, "message")} and ${plural(d.signs_rejected, "sign")} rejected here</span>
    </div>
    ${!anyDecision && WI.rule === "accepted" ? '<p class="warn small">You have made no decision yet, so both columns match. Accept or reject merges in the Agents tab, reject a message from a record in the Inspector, or reject a sign below.</p>' : ""}
    <div class="grid2">
      ${card("As counted, and after your decisions", `<table class="wi-tab"><thead><tr><th></th><th class="num">as counted</th><th class="num">after</th><th class="num">change</th></tr></thead><tbody>
        ${deltaRow(term("agent_estimate", "Named actors → estimated agents"), a.agents, b.agents, { note: `${fmt(a.named_actors)} named actors; ${plural(w.groups_total, "merge group")}` })}
        ${deltaRow("Messages between different agents", a.messages, b.messages)}
        ${deltaRow("Sender-receiver pairs", a.pairs, b.pairs)}
        ${deltaRow("Largest group linked by messages", a.largest_group, b.largest_group)}
        ${deltaRow(term("self_talk", "Messages inside one agent (dropped)"), a.inside_one_agent, b.inside_one_agent)}
        ${deltaRow("Messages you rejected (dropped)", a.rejected_messages, b.rejected_messages)}
      </tbody></table>
      <p class="small"><b>First message between different agents</b><br>as counted: ${firstMsg(a.first_message)}<br>after: ${firstMsg(b.first_message)}</p>`,
        { sub: "Messages between named actors, counted the same way in both columns. Merging tokens turns their messages to each other into talk inside one agent; rejected messages are left out." })}
      ${card("The first sign of actors working together", `
        <div class="wi-first"><div><span class="small muted">as counted</span>${fa ? `<b>${esc(fa.name)}</b><span>${esc(when(toTime(fa.time)))} · ${ent.rec(fa.record)}</span><span class="wi-big">${hl(fa.harm_share_after)}</span><span class="small muted">of harm still to come</span>` : '<b class="muted">none</b>'}</div>
        <div><span class="small muted">after your decisions</span>${fb ? `<b>${esc(fb.name)}</b><span>${esc(when(toTime(fb.time)))} · ${ent.rec(fb.record)}</span><span class="wi-big">${hl(fb.harm_share_after)}</span><span class="small muted">of harm still to come</span>` : '<b class="muted">none fires</b>'}</div></div>
        ${w.groups.length ? `<p class="small"><b>Merge groups applied</b> (${fmt(w.groups_total)}; the first actor is the one the group is counted as)</p><div class="wi-groups">${w.groups.slice(0, 20).map((g) => `<div>${g.actors.slice(0, 8).map((x) => ent.actor(x)).join(" ")}${g.actors.length > 8 ? ` <span class="muted small">+${g.actors.length - 8}</span>` : ""}</div>`).join("")}</div>` : '<p class="small muted">No tokens are merged under this choice.</p>'}`,
        { sub: `${term("harm_left")}: the share of dated harmful actions after the sign; higher is earlier.` })}
    </div>
    ${card("Warning signs, as counted and after", `<table class="wi-tab wi-signs"><thead><tr><th>sign</th><th>as counted <span class="muted">· harm left</span></th><th>after <span class="muted">· harm left</span></th><th></th></tr></thead><tbody>${
      w.signs.map((g) => `<tr><td><span class="wi-fam" style="background:${FAMILY[g.family]?.color || BASE}"></span>${esc(g.name)}${g.record ? `<div>${ent.rec(g.record)}</div>` : ""}</td>
        <td><span class="wi-nw">${esc(when(toTime(g.time)))}</span> · <b>${hl(g.harm_share_after)}</b></td>
        <td>${g.after ? `<span class="wi-nw">${esc(when(toTime(g.after.time)))}</span> · <b>${hl(g.after.harm_share_after)}</b>${g.after.record && g.after.record !== g.record ? `<div>${ent.rec(g.after.record)}</div>` : ""}` : '<span class="muted">–</span>'}
          <div><span class="wi-st wi-${g.status}" title="${esc(g.after?.why || g.note || "")}">${esc(statusWord[g.status] || g.status)}</span></div></td>
        <td><button type="button" class="link" data-sign="${esc(g.key)}" data-act="${g.status === "rejected" ? "restore" : "reject"}">${g.status === "rejected" ? "restore" : "reject"}</button></td></tr>`).join("")}</tbody></table>`,
      { sub: "Signs of actors working together are recounted with tokens merged into agents and your rejected messages left out; single-actor and volume signs do not depend on merges. Reject a sign you judge wrong to see the first sign that remains." })}
    <div id="wiDecs"></div>`;
  host.querySelectorAll("[data-rule]").forEach((x) => x.addEventListener("click", () => { WI.rule = x.dataset.rule; renderWhatif(host); }));
  host.querySelectorAll("[data-go]").forEach((x) => x.addEventListener("click", () => goTab(x.dataset.go)));
  host.querySelectorAll("[data-sign]").forEach((x) => x.addEventListener("click", async () => {
    try { const r = await api(`/api/x/fx_whatif_decide?rule=${WI.rule}`, { method: "POST", body: JSON.stringify({ kind: "sign", ids: [x.dataset.sign], action: x.dataset.act, by: investigator() }) }); drawWhatif(host, r.whatif); }
    catch (e) { status(e.message, true); }
  }));
  drawDecisions($("wiDecs"), host);
}
function investigator() {
  try { return localStorage.getItem("swarm-tracer-investigator") || ""; } catch { return ""; }
}
async function drawDecisions(box, host) {
  if (!box) return;
  let d;
  try { d = await api("/api/x/fx_whatif_decisions"); } catch (e) { box.innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
  const rows = d.messages.map((m) => [m.missing ? `<span class="muted">${esc(m.id)} (not in this dataset)</span>` : `${ent.actor(m.from)} → ${ent.actor(m.to)} via ${ent.place(m.channel)}`,
    m.missing ? "" : `${ent.rec(m.write_id)} → ${ent.rec(m.read_id)}`, esc((m.added || "").replace("T", " ").replace("Z", " UTC")), esc(m.by || ""),
    `<button type="button" class="link" data-msg="${esc(m.id)}">restore</button>`]);
  box.innerHTML = card("Messages you rejected", `${rows.length ? table(["message", "written → read", "rejected", "by", ""], rows) : '<p class="small muted">None yet. Open a record in the Inspector: a record that writes or reads messages has a <b>What-if</b> section with a reject button.</p>'}
    <form class="wi-add"><input placeholder="or type write_id>read_id" aria-label="Message to reject, as write record id > read record id"> <button type="submit">Reject message</button>
    ${d.messages.length || d.signs.length ? ' <button type="button" class="wi-clear">Clear all what-if decisions</button>' : ""}</form>
    <p class="small muted">Saved to <code>${esc(d.file)}</code>. Identity merges stay in the Agents tab's own file.</p>`,
    { sub: "Each is left out of every count above; restore one to count it again." });
  box.querySelectorAll("[data-msg]").forEach((x) => x.addEventListener("click", async () => {
    try { const r = await api(`/api/x/fx_whatif_decide?rule=${WI.rule}`, { method: "POST", body: JSON.stringify({ kind: "message", ids: [x.dataset.msg], action: "restore" }) }); drawWhatif(host, r.whatif); }
    catch (e) { status(e.message, true); }
  }));
  box.querySelector(".wi-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = e.target.querySelector("input").value.trim().replace(/\s*>\s*/, ">");
    if (!v) return;
    try { const r = await api(`/api/x/fx_whatif_decide?rule=${WI.rule}`, { method: "POST", body: JSON.stringify({ kind: "message", ids: [v], action: "reject", by: investigator() }) }); drawWhatif(host, r.whatif); }
    catch (err) { status(err.message, true); }
  });
  const clr = box.querySelector(".wi-clear");
  if (clr) clr.addEventListener("click", async () => {
    if (!confirm("Forget every message and sign you rejected here? (Identity merges in the Agents tab stay.)")) return;
    await api("/api/x/fx_whatif_decide", { method: "POST", body: JSON.stringify({ clear: true }) });
    renderWhatif(host);
  });
}

// Inspector: reject the messages a record is part of
window.INSPECTOR_EXTRAS.push((kind, key, data) => {
  if (kind !== "record" || !data) return "";
  const n = (data.messages_in || []).length + (data.messages_out || []).length;
  if (!n) return "";
  return `<div class="dsec wi-ins" data-wi-rec="${esc(key)}"><h4>${term("whatif", "What-if")}</h4><p class="small wi-ins-body muted">Checking…</p></div>`;
});
window.INSPECTOR_BIND.push(async (host, kind, key) => {
  const box = host.querySelector(".wi-ins");
  if (!box || kind !== "record") return;
  const body = box.querySelector(".wi-ins-body");
  let r;
  try { r = await api("/api/x/fx_whatif_record?id=" + encodeURIComponent(key)); } catch (e) { body.textContent = e.message; return; }
  const draw = () => {
    const all = r.messages, rej = all.filter((m) => m.rejected).length;
    body.className = "small wi-ins-body";
    body.innerHTML = `This record is part of ${plural(all.length, "message")}${rej ? `; you rejected ${fmt(rej)}` : ""}.
      <button type="button" class="wi-rej">${rej === all.length ? "Restore them" : "Reject the messages this record is part of"}</button>
      <button type="button" class="link wi-see">See the effect</button>`;
    body.querySelector(".wi-rej").addEventListener("click", async () => {
      const act = rej === all.length ? "restore" : "reject";
      try {
        if (window.DECISIONS) await window.DECISIONS.decide("message", all.map((m) => m.id), act === "reject");   // updates every Accept/Reject control
        else await api("/api/x/fx_whatif_decide", { method: "POST", body: JSON.stringify({ kind: "message", ids: all.map((m) => m.id), action: act, by: investigator() }) });
        all.forEach((m) => { m.rejected = act === "reject"; });
        draw();
        status(`${act === "reject" ? "Rejected" : "Restored"} ${plural(all.length, "message")}; the What-if section recounts with it.`);
        setTimeout(() => status(""), 4000);
      } catch (e) { status(e.message, true); }
    });
    body.querySelector(".wi-see").addEventListener("click", () => { location.hash = "tab=forensics&fx=whatif"; goTab("forensics"); });
  };
  draw();
  // a single message accepted or rejected on its own line above changes this summary too
  const sync = (e) => {
    if (!box.isConnected) { document.removeEventListener("st-decision", sync); return; }
    if (e.detail.kind !== "message") return;
    let hit = false;
    r.messages.forEach((m) => { if (e.detail.ids.includes(m.id)) { m.rejected = e.detail.reject; hit = true; } });
    if (hit) draw();
  };
  document.addEventListener("st-decision", sync);
});

// ------------------------------------------------------------------ reference swarm
async function renderReference(host) {
  const r = await api("/api/x/fx_reference");
  if (!r.source && !r.busy && !r.error && r.default_available && !renderReference.tried) {
    renderReference.tried = true;
    try { await api("/api/x/fx_reference_load", { method: "POST", body: JSON.stringify({ default: true }) }); return renderReference(host); }
    catch (e) { console.warn("default reference", e); }
  }
  drawReference(host, r);
  if (r.busy) setTimeout(() => { if (host.isConnected) renderReference(host); }, 1500);
}
function drawReference(host, r) {
  const opts = [];
  if (r.default_available) opts.push(`<option value="default">Benign swarm sample (bundled)</option>`);
  if (r.compare_loaded) opts.push(`<option value="compare">The Compare tab's second dataset: ${esc(r.compare_name || "")}</option>`);
  (r.library || []).filter((e) => e.available).forEach((e) => opts.push(`<option value="lib:${esc(e.id)}">${esc(e.title)}</option>`));
  opts.push(`<option value="path">A path on this machine…</option>`);
  const flagged = (r.rows || []).filter((x) => x.flag);
  const src = r.source;
  host.innerHTML = `
    ${card("The yardstick", `<form class="wi-ref"><select aria-label="Reference dataset">${opts.join("")}</select>
        <input class="wi-path" placeholder="/path/to/benign/trace.jsonl or folder" hidden aria-label="Path of the reference dataset"> <button type="submit" class="primary">Use as reference</button>
        ${src ? '<button type="button" class="wi-rclear">Forget the reference</button>' : ""}</form>
      <p class="small ${r.error ? "bad" : "muted"}">${r.busy ? "Loading the reference… (a large dataset takes up to a minute the first time)" : r.error ? esc(r.error)
        : src ? `Reference: <b>${esc(src.name)}</b> (${esc(src.kind)}${src.path ? `, <code>${esc(src.path)}</code>` : ""}), loaded ${esc((src.loaded || "").replace("T", " ").replace("Z", " UTC"))}.`
        : r.default_available ? "No reference loaded." : "No reference loaded. The benign swarm sample (agenttrace/samples/benign_swarm) is not installed; pick a library entry or a path."}</p>`,
      { sub: `A ${term("reference", "reference swarm")} is measured by the same code as the swarm under investigation (the Compare tab's measures), and each measure here is set against it.` })}
    ${r.rows ? (r.same_dataset ? '<p class="warn">The reference is the same dataset as the one under investigation, so nothing can deviate.</p>' : "") + card(`How ${esc(r.here.name)} deviates from ${esc(r.reference.name)}`,
      `<div class="wi-refhead small muted">This swarm: ${fmt(r.here.records)} records, ${fmt(r.here.named_actors)} named actors, ${hoursWord(r.here.hours)} of activity · reference: ${fmt(r.reference.records)} records, ${fmt(r.reference.named_actors)} named actors, ${hoursWord(r.reference.hours)}</div>
      ${flagged.length ? `<ul class="wi-sent">${flagged.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ul>` : '<p class="small">No measure deviates by 2x or more (or 15 points for shares).</p>'}
      <table class="wi-tab"><thead><tr><th>measure</th><th class="num">this swarm</th><th class="num">reference</th><th class="num">deviation</th></tr></thead><tbody>
      ${r.rows.map((x) => `<tr class="${x.flag ? "wi-flag" : ""}" title="${esc(x.text)}"><td>${esc(x.label)}</td><td class="num">${esc(x.here_text)}</td><td class="num">${esc(x.reference_text)}</td><td class="num">${x.ratio != null ? `${x.ratio >= 1 ? x.ratio.toFixed(1) : x.ratio.toFixed(2)}x` : x.difference != null ? `${x.difference >= 0 ? "+" : "−"}${Math.abs(Math.round(100 * x.difference))} pts` : "–"}${x.flag ? " ⚑" : ""}</td></tr>`).join("")}
      </tbody></table>`,
      { sub: `${plural(r.flagged, "measure")} flagged (⚑): a ratio of 2x or more either way, or 15+ points for a share. Ratios use rates per named actor or per hour, so swarms of different size compare.` }) : ""}`;
  const f = host.querySelector(".wi-ref"), sel = f.querySelector("select"), path = f.querySelector(".wi-path");
  if (src) { const v = src.kind === "library" ? "lib:" + src.id : src.kind === "default" ? "default" : src.kind === "compare" ? "compare" : "path"; if ([...sel.options].some((o) => o.value === v)) sel.value = v; if (v === "path") path.value = src.path || ""; }
  path.hidden = sel.value !== "path";
  sel.addEventListener("change", () => { path.hidden = sel.value !== "path"; });
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = sel.value;
    const body = v === "default" ? { default: true } : v === "compare" ? { use_compare: true } : v.startsWith("lib:") ? { library: v.slice(4) } : { path: path.value.trim() };
    try { await api("/api/x/fx_reference_load", { method: "POST", body: JSON.stringify(body) }); renderReference(host); }
    catch (err) { status(err.message, true); }
  });
  const c = host.querySelector(".wi-rclear");
  if (c) c.addEventListener("click", async () => { await api("/api/x/fx_reference_clear", { method: "POST", body: "{}" }); renderReference.tried = true; renderReference(host); });
}

// ------------------------------------------------------------------ chain of custody
function custodyTable(c) {
  const t = c.tool || {}, p = c.pack || {};
  const rows = [["dataset", `${esc(c.dataset)} <span class="muted">(${fmt(c.records)} records)</span>`],
    [`record ids <span class="muted small">SHA-256 of the sorted ids</span>`, `<code class="wi-hash">${esc(c.record_ids_sha256)}</code>`],
    ...(c.files || []).map((f) => [`input file <b>${esc(f.file)}</b>`, f.sha256 ? `<code class="wi-hash">${esc(f.sha256)}</code><div class="small muted">${fmt(f.bytes)} bytes · modified ${esc((f.modified || "").replace("T", " ").replace("Z", " UTC"))} · ${esc(f.role)}${f.matches_listed === true ? ' · <span class="ok">matches the checksum shipped with the data</span>' : f.matches_listed === false ? ' · <b class="bad">does not match the checksum shipped with the data</b>' : ""}</div>` : `<span class="small bad">${esc(f.error || "not hashed")}</span>`]),
    ["pack", `${esc(p.name)}${p.file ? ` · ${esc(p.file)}` : ""}${p.chosen_automatically ? ' <span class="muted small">(chosen automatically)</span>' : ""}${p.sha256 ? `<br><code class="wi-hash">${esc(p.sha256)}</code>` : ""}`],
    ["tool", `${esc(t.name)} ${esc(t.version || "")}${t.git ? ` · build <code>${esc(t.git)}</code>` : ""}${t.code_fingerprint ? ` · code <code>${esc(t.code_fingerprint)}</code>` : ""}`],
    ["loaded", `${esc((c.loaded_at || "not recorded").replace("T", " ").replace("Z", " UTC"))}${c.load_seconds != null ? ` <span class="muted small">in ${esc(c.load_seconds)} s${c.from_cache ? ", from the disk cache" : ""}</span>` : ""}`],
    ["analysis fingerprint", `<code class="wi-hash">${esc(c.fingerprint)}</code>`]];
  return `<table class="wi-tab wi-cust"><tbody>${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</tbody></table>`;
}
async function renderCustody(host) {
  const c = await api("/api/x/fx_custody");
  let cs = null;
  try { cs = window.CASEFILE ? await window.CASEFILE.ensure() : (await api("/api/x/case")).case; } catch { cs = null; }
  const items = (cs?.items || []).slice().sort((a, b) => String(a.added || "").localeCompare(String(b.added || "")));
  host.innerHTML = card(term("custody", "Chain of custody"), custodyTable(c) +
      `<p class="small muted">Check an input file with <code>shasum -a 256 &lt;file&gt;</code>. The fingerprint changes when any input, the pack, the set of record ids or the build changes. This block is written into the case file export and every export in the Exports section.</p>`,
      { sub: "What produced the numbers you are looking at" })
    + card("Who pinned what, and when", items.length ? table(["when", "by", "kind", "item", "note"], items.map((it) => [esc(it.added || "–"), esc(it.by || cs.investigator || "–"), esc(it.kind),
        it.kind === "record" ? ent.rec(it.key) : it.kind === "actor" ? ent.actor(it.key) : it.kind === "place" ? ent.place(it.key) : esc(it.key.replace("|", " ⇄ ")),
        `<span class="small">${esc((it.note || "").slice(0, 120))}${(it.note || "").length > 120 ? "…" : ""}</span>`]))
      : '<p class="small muted">Nothing pinned yet.</p>',
      { sub: `From the case file${cs?.investigator ? `, investigator <b>${esc(cs.investigator)}</b>` : ""}; set your name in the case file drawer so each pin records who made it.`, right: '<button type="button" class="link wi-opencase">Open the case file</button>' });
  const b = host.querySelector(".wi-opencase");
  if (b) b.addEventListener("click", () => window.CASEFILE?.openDrawer());
}

// ------------------------------------------------------------------ exports
const EXPORTS = [
  ["timeline_csv", "Timeline CSV", "Every dated record in time order: time, how it was dated, id, actor, kind, intent, tags, places, harmful. The chain of custody heads the file as # comment lines."],
  ["timesketch_csv", term("timesketch", "Timesketch CSV"), "message, datetime (ISO 8601), timestamp_desc and the same fields, ready for Timesketch's CSV import; the first row records the chain of custody."],
  ["stix", term("stix", "STIX 2.1 bundle"), "Actors as pseudonymous identities, places as indicators (URLs, hosts, named places; the 2,000 busiest), each warning sign as a sighting of an attack pattern with its stage as the kill-chain phase; a note carries the chain of custody. Ids are deterministic (UUIDv5), so re-exporting the same data gives the same ids."],
  ["detections", "Alert rules as detections", "The alert rules (Live mode's rules editor) as JSON detections: each rule's logic, its conditions, and when it fires on this dataset, with the chain of custody."],
];
async function renderExports(host) {
  host.innerHTML = card("Exports for a SOC", `<div class="wi-exps">${EXPORTS.map(([k, name, what]) => `<div class="wi-exp"><div><b>${name}</b><p class="small muted">${what}</p></div><div><button type="button" class="primary" data-exp="${k}">Download</button><div class="small muted wi-expst"></div></div></div>`).join("")}
    <div class="wi-exp"><div><b>Case file</b><p class="small muted">The dossier of everything pinned, with a printable summary page, the ground-truth score when there is one, and the chain of custody.</p></div><div><button type="button" class="primary" data-case="html">HTML</button> <button type="button" data-case="json">JSON</button><div class="small muted wi-expst"></div></div></div></div>`,
    { sub: "Built from the loaded dataset on this machine; nothing is sent anywhere. Text cells that a spreadsheet would run as a formula start with a quote." });
  host.querySelectorAll("[data-exp]").forEach((b) => b.addEventListener("click", async () => {
    const st = b.parentElement.querySelector(".wi-expst"), old = b.textContent;
    b.disabled = true; b.textContent = "Building…";
    try {
      const r = await api("/api/x/fx_export?format=" + b.dataset.exp);
      download(r.filename, r.content, r.mime);
      st.textContent = `Saved ${r.filename}: ${fmt(r.count)} ${b.dataset.exp === "stix" ? "objects" : b.dataset.exp === "detections" ? "rules" : "records"}, ${sizeWord(r.bytes)}.`;
      if (b.dataset.exp === "stix" && r.count && typeof r.count === "object") st.textContent = `Saved ${r.filename}: ${Object.entries(r.count).map(([k, v]) => `${fmt(v)} ${k}`).join(", ")}; ${sizeWord(r.bytes)}.`;
    } catch (e) { st.textContent = e.message; st.className = "small bad wi-expst"; }
    finally { b.disabled = false; b.textContent = old; }
  }));
  host.querySelectorAll("[data-case]").forEach((b) => b.addEventListener("click", async () => {
    const st = b.parentElement.querySelector(".wi-expst"), fmtc = b.dataset.case;
    b.disabled = true;
    try {
      const r = await api(`/api/x/case_export?format=${fmtc}&base=${encodeURIComponent(location.origin + location.pathname)}`);
      if (fmtc === "html") download(r.filename, r.html, "text/html"); else download(r.filename, JSON.stringify(r.dossier, null, 1), "application/json");
      st.textContent = `Saved ${r.filename}.`;
    } catch (e) { st.textContent = e.message; }
    finally { b.disabled = false; }
  }));
}

window.FX_SECTIONS.push(
  { id: "whatif", title: "What-if", group: G, blurb: "Apply your decisions (merged tokens, rejected messages and signs) and see every count and sign recounted, side by side with the counts as the tool made them.", render: renderWhatif },
  { id: "reference", title: "Against a reference", group: G, blurb: "Set the swarm against a reference swarm, a benign one by default, and see which measures deviate and by how much.", render: renderReference },
  { id: "custody", title: "Chain of custody", group: G, blurb: "Hashes of every input file and of the record ids, the build and pack that produced the analysis, and who pinned what and when.", render: renderCustody },
  { id: "exports", title: "Exports", group: G, blurb: "Timeline CSV, Timesketch CSV, a STIX 2.1 bundle and the alert rules as detections, each with the chain of custody.", render: renderExports },
);
})();

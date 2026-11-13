// "Start here": a short guided first pass through whatever dataset is loaded. Each step is one sentence
// built from the dataset's own numbers (summary, replay, identity estimate, gaps) and a button that opens
// the matching deep link. Opens on its own until the investigator closes it (remembered in localStorage);
// the "Start here" button in the top bar always brings it back.
(() => {
"use strict";
const KEY = "swarm-tracer-guide-dismissed";
const G = { steps: null, i: -1, mini: false, forKey: "" };
const isDismissed = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };
const dismiss = () => { try { localStorage.setItem(KEY, "1"); } catch { /* private mode */ } };
const link = (o) => new URLSearchParams(o).toString();
const soft = (p) => p.catch(() => null);

async function buildSteps(s) {
  const f = s.flow || {}, steps = [];
  const named = s.actions?.named_actors ?? Object.entries(s.actor_kinds || {}).filter(([k]) => k !== "run").reduce((a, [, v]) => a + v, 0);
  const [sim, idn, gaps, dec, wi] = await Promise.all([soft(cached("/api/sim")), soft(cached("/api/x/identity")), soft(cached("/api/gaps")), soft(api("/api/x/fx_whatif_decisions")), whatifEstimate()]);
  steps.push({ title: "What is loaded", btn: "Open the overview", link: link({ tab: "overview" }),
    text: `${s.name} holds ${plural(s.records, "record")}, ${pct(s.records ? s.timed / s.records : null)} of them dated, from ${plural(named, "named actor")} using ${plural(f.channels || 0, "place")}.` });
  const msgs = f.deliveries_between_named_actors ?? f.deliveries ?? 0, tp = (f.top_pairs || [])[0];
  steps.push({ title: "Who talked to whom", btn: tp ? "Open their conversation" : "Open Who talked to whom",
    link: tp ? link({ tab: "network", a: tp.from, b: tp.to }) : link({ tab: "network" }),
    text: msgs ? `${plural(msgs, "message")} passed between named actors, over ${plural(f.named_actor_pairs || 0, "sender-receiver pair")}${tp ? `; the busiest is ${short(tp.from)} → ${short(tp.to)} with ${plural(tp.deliveries, "message")}` : ""}.`
      : "No message between named actors was found: no actor read a place after a different actor wrote to it." });
  const fd = f.first_named_delivery;
  if (fd) steps.push({ title: "The first message", btn: "Open it in the Inspector", link: link({ tab: "network", rec: fd.read_id }),
    text: `${short(fd.from)} wrote ${placeLabel(fd.channel)} in ${fd.write_id} and ${short(fd.to)} read it in ${fd.read_id}${fd.read_time ? ` at ${fd.read_time} UTC` : ""}${f.harm_share_after_first_named_delivery != null ? `; ${bothSharesText(f.harm_share_after_first_named_delivery, wi?.after?.first_message?.harm_share_after)} of the dated harm came after it` : ""}.` });
  if (sim) {
    const sigs = sim.signals || [], joint = sigs.filter((g) => g.family === "joint").sort((a, b) => a.t - b.t)[0];
    steps.push({ title: "Could it have been flagged early?", btn: "Replay the early flag", link: link({ tab: "early" }),
      text: `The replay tracks ${plural(sigs.length, "warning sign")}. ${joint ? `The first sign of actors working together (${joint.name.toLowerCase()}) fired ${when(joint.t * 1000)} UTC${joint.harm_share_after != null ? `, with ${bothSharesText(joint.harm_share_after, whatifSign(wi, joint.key)?.after?.harm_share_after)} of the harm still to come` : ""}.` : "None of them is about actors working together."}` });
  }
  const est = idn?.estimate;
  steps.push({ title: "A token is not an agent", btn: "Review identities in Agents", link: link({ tab: "agents" }),
    text: `Each named actor is an identity token or a name, and one agent can hold several. ${est ? `The ${plural(est.named_actors, "named actor")} here come to an estimated ${plural(est.estimated_agents, "agent")}, with ${plural(est.proposals || 0, "possible merge")} for you to accept or reject.` : `This dataset has ${plural(named, "named actor")}; the Agents tab estimates how many agents they are.`}` });
  const rows = (gaps?.rows || []).filter((r) => r.share != null && r.count > 0).sort((a, b) => b.share - a.share);
  steps.push({ title: "What's missing", btn: "See the blind spots", link: link({ tab: "gaps" }),
    text: rows.length ? `The tool sees only what the records show. The largest measured blind spot is ${rows[0].gap.toLowerCase()}: ${pct(rows[0].share)} of ${rows[0].unit}${rows.length > 1 ? `, one of ${plural(rows.length, "measured gap")}` : ""}.`
      : "The tool sees only what the records show; this page lists what it could not measure." });
  const nd = dec ? dec.messages.length + dec.signs.length + dec.merges.length : null;
  steps.push({ title: "Record your judgement", btn: "See the recount", link: link({ tab: "forensics", fx: "whatif" }),
    text: `Reject a message or a warning sign you judge wrong, wherever it is shown, and the What-if section recounts everything without it${nd != null ? ` (${nd ? plural(nd, "decision") + " so far" : "no decision yet"})` : ""}.` });
  return steps;
}

function panel() {
  let el = $("guide");
  if (!el) {
    el = document.createElement("section");
    el.id = "guide"; el.className = "guide"; el.hidden = true;
    el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Start here: a guided first pass");
    document.body.appendChild(el);
    el.addEventListener("click", onClick);
  }
  return el;
}
function draw() {
  const el = panel(), st = G.steps || [], n = st.length;
  if (!n) { el.innerHTML = `<div class="gdhead"><h3>Start here</h3><button type="button" class="link" data-gd="close" aria-label="Close the guide">Close</button></div><p class="muted small gdload">${S.summary ? "Reading the dataset…" : "Load a trace first."}</p>`; return; }
  if (G.mini && G.i >= 0) {
    const x = st[G.i];
    el.className = "guide mini";
    el.innerHTML = `<div class="gdmini"><span class="gdn">${G.i + 1}/${n}</span><b>${esc(x.title)}</b>
      <button type="button" data-gd="prev" ${G.i ? "" : "disabled"} aria-label="Previous step">←</button><button type="button" class="primary" data-gd="next" ${G.i < n - 1 ? "" : "disabled"}>Next step</button>
      <button type="button" class="link" data-gd="all">All steps</button><button type="button" class="link" data-gd="close" aria-label="Close the guide">×</button></div>
      <p class="small gdtext">${esc(x.text)}</p>`;
    return;
  }
  el.className = "guide";
  el.innerHTML = `<div class="gdhead"><h3>Start here</h3><span class="muted small">${n} steps through ${esc(S.summary?.name || "this dataset")}</span><button type="button" class="link" data-gd="close" aria-label="Close the guide">Close</button></div>
    <ol class="gdsteps">${st.map((x, k) => `<li class="${k === G.i ? "on" : ""}"><span class="gdn">${k + 1}</span><div><b>${esc(x.title)}</b><p class="small">${esc(x.text)}</p>
      <button type="button" data-gd="go" data-k="${k}">${esc(x.btn)}</button></div></li>`).join("")}</ol>
    <p class="small muted gdfoot">Closing hides this for good on this browser; the Start here button in the top bar brings it back.</p>`;
}
function go(k) {
  const x = G.steps?.[k];
  if (!x) return;
  G.i = k; G.mini = true;
  location.hash = x.link;
  openDeepLink();
  draw();
}
function onClick(e) {
  const b = e.target.closest("[data-gd]");
  if (!b) return;
  const a = b.dataset.gd;
  if (a === "close") close();
  else if (a === "go") go(+b.dataset.k);
  else if (a === "next") go(G.i + 1);
  else if (a === "prev") go(G.i - 1);
  else if (a === "all") { G.mini = false; draw(); }
}
function close() {
  dismiss();
  const el = $("guide"), had = el?.contains(document.activeElement);
  if (el) el.hidden = true;
  $("guidebtn")?.setAttribute("aria-expanded", "false");
  if (had) $("guidebtn")?.focus();
}
async function open(focus = true) {
  const el = panel();
  el.hidden = false;
  $("guidebtn")?.setAttribute("aria-expanded", "true");
  const key = datasetKey(S.summary);
  if (S.summary && G.forKey !== key) {
    G.steps = null; G.i = -1; G.mini = false; draw();
    try { G.steps = await buildSteps(S.summary); G.forKey = key; } catch (e) { console.error(e); G.steps = []; }
  }
  draw();
  if (focus) el.querySelector("button[data-gd='go'],button[data-gd='next']")?.focus();
}

$("guidebtn")?.addEventListener("click", () => { const el = $("guide"); if (el && !el.hidden) close(); else open(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("guide") && !$("guide").hidden && !e.target.closest?.("#omni")) close(); });
// first visit: open once the dataset is in, unless a deep link asked for a specific view
window.addEventListener("load", () => {
  // the Trace tab is the front door now: the guide no longer opens over it. On a first visit the
  // button is highlighted instead.
  if (!isDismissed()) { const b = document.getElementById("guidebtn"); if (b) b.classList.add("fresh"); }
  return;
  const t = setInterval(() => { if (S.summary) { clearInterval(t); open(false); } }, 300);
  setTimeout(() => clearInterval(t), 60000);
});
window.GUIDE = { open, close };
})();

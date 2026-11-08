// Live mode and alert rules: a drawer opened from the top bar's Live button.
// Follows a growing trace on this machine (agenttrace/live.py), shows each new warning sign and
// alert as it fires, refreshes every tab when the dataset grows, and edits the saved alert rules.
(() => {
  "use strict";
  GLOSSARY.live = ["Live mode", "The app watches a trace file or folder on this machine and analyzes it again each time it grows, so warning signs and alerts show up as the records arrive."];
  GLOSSARY.alert_rule = ["Alert rule", "A saved rule over the warning signs: a name, a severity, and conditions (kinds of sign, harmful actions per hour, messages between named actors, group size). It fires at the moment all its conditions hold."];

  const L = { st: null, seq: 0, timer: null, loads: -1, unseen: 0, title: document.title, rules: null, evalr: null,
    editing: null, feed: [], refresh: true, kinds: [] };
  const SEV = { alert: { color: HARM, bg: "var(--harm-bg)", label: "alert" }, watch: { color: "#b7791f", bg: "#fdf3e1", label: "watch" },
    info: { color: QUIET, bg: "#f1f3f5", label: "info" } };
  const COND = {
    sign: "a warning sign fires",
    coordination_kinds: "kinds of coordination ≥ N",
    harm_rate: "harmful actions in one hour ≥ N",
    messages_between: "messages between actors ≥ N",
    group_size: "a message-linked group ≥ N actors",
  };
  const KINDS = ["harm", "token", "carried", "place", "message", "two_way", "group", "program", "baseline"];
  const KIND_WORD = { harm: "first harmful action of a kind", token: "token seen as data, then used", carried: "one identity carries another's token",
    place: "two identities share a place", message: "first message between named actors", two_way: "first two-way exchange",
    group: "actors linked into a group", program: "program reused by another actor", baseline: "volume alarm" };

  // ------------------------------------------------------------------ drawer shell
  const dr = document.createElement("aside");
  dr.id = "lvDrawer"; dr.className = "lvdrawer"; dr.hidden = true;
  dr.setAttribute("aria-label", "Live mode and alert rules");
  dr.innerHTML = `
    <header class="lvhead"><b>Live mode &amp; alert rules</b><button type="button" class="link" id="lvClose" aria-label="Close">Close ✕</button></header>
    <div class="lvbody">
      <section class="lvsec">
        <h4>Follow a growing trace</h4>
        <p class="small muted">The app watches a file or folder on this machine and analyzes it again whenever it grows. The loaded dataset is replaced each time a new load succeeds, so every tab follows along.</p>
        <label class="lvf">Path of a trace file or folder <input id="lvPath" placeholder="/tmp/feed.jsonl" spellcheck="false" autocomplete="off"></label>
        <div class="lvrow">
          <label class="lvf">Pack <select id="lvPack"></select></label>
          <label class="lvf lvnum">Check every <span><input id="lvInt" type="number" min="0.5" step="0.5" value="2"> s</span></label>
        </div>
        <div class="lvrow"><button type="button" class="primary" id="lvStart">Start</button><button type="button" id="lvStop" disabled>Stop</button>
          <label class="chk small"><input type="checkbox" id="lvRefresh" checked> refresh all tabs on each load</label></div>
        <div id="lvStatus" class="lvstatus small muted">Not watching.</div>
        <details class="lvhint"><summary class="small">No growing trace? Replay one</summary>
          <p class="small muted">Replay an existing trace into a new file, in time order, at a chosen speed (records per second), then start live mode on the new file:</p>
          <pre class="lvcode">python3 -m agenttrace.tools.replay_feed redacted.jsonl /tmp/feed.jsonl --rate 2000</pre>
          <p class="small muted">Add <code>--start 5000</code> to write a first batch at once, <code>--fast</code> to sort by the time field only (no analysis first), <code>--no-sort</code> to keep the file order.</p>
        </details>
      </section>
      <section class="lvsec">
        <h4>What changed, newest first <span id="lvCount" class="muted"></span><button type="button" class="link" id="lvClear">clear</button></h4>
        <label class="chk small"><input type="checkbox" id="lvAll"> also show new records, actors and messages</label>
        <div id="lvFeed" class="lvfeed"><p class="small muted">New records, actors, messages, warning signs and alerts appear here while live mode runs.</p></div>
      </section>
      <section class="lvsec">
        <h4>${term("alert_rule", "Alert rules")}</h4>
        <div id="lvRuleNote" class="small muted"></div>
        <div id="lvRules"></div>
        <div class="lvrow lvtools">
          <button type="button" id="lvAdd">Add a rule</button>
          <button type="button" id="lvExport">Export</button>
          <label class="lvimport"><span>Import…</span><input type="file" id="lvImport" accept=".json,application/json"></label>
          <button type="button" class="link" id="lvReset">restore the defaults</button>
        </div>
        <div id="lvEdit"></div>
      </section>
    </div>`;
  document.body.appendChild(dr);
  const toastHost = document.createElement("div");
  toastHost.className = "lvtoasts"; toastHost.setAttribute("role", "status"); toastHost.setAttribute("aria-live", "polite");
  document.body.appendChild(toastHost);

  const open = () => {
    dr.hidden = false;
    const ps = $("pack");
    if (ps && !$("lvPack").options.length) $("lvPack").innerHTML = ps.innerHTML;
    L.unseen = 0; badge();
    poll(); loadRules();
  };
  const close = () => { dr.hidden = true; };
  $("livebtn").addEventListener("click", () => (dr.hidden ? open() : close()));
  $("lvClose").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !dr.hidden && !e.target.closest?.("#lvEdit")) close(); });

  // ------------------------------------------------------------------ live mode
  function badge() {
    document.title = L.unseen ? `(${L.unseen}) ${L.title}` : L.title;
    const b = $("livebtn");
    b.classList.toggle("lvon", !!L.st?.watching);
    b.innerHTML = `${L.st?.watching ? '<i class="lvdot"></i>' : ""}Live${L.unseen ? ` <span class="lvbadge">${L.unseen}</span>` : ""}`;
  }
  function toast(ev) {
    const s = SEV[ev.severity] || SEV.info;
    const t = document.createElement("div");
    t.className = "lvtoast"; t.style.borderLeftColor = s.color;
    t.innerHTML = `<b style="color:${s.color}">${esc(s.label)}</b> ${esc(ev.text)}<div class="small muted">${ev.record ? ent.rec(ev.record) + " " : ""}${(ev.actors || []).slice(0, 3).map((a) => ent.actor(a)).join(" ")}${ev.harm_share_after != null ? ` · ${pct(ev.harm_share_after)} of the harmful actions loaded so far are later` : ""}</div>`;
    t.addEventListener("click", (e) => { if (!e.target.closest(".ent")) { open(); t.remove(); } });
    toastHost.prepend(t);
    while (toastHost.children.length > 4) toastHost.lastChild.remove();
    setTimeout(() => t.remove(), 9000);
  }

  async function poll() {
    let st;
    try { st = await api(`/api/x/live_status?since=${L.seq}`); }
    catch (e) { $("lvStatus").textContent = e.message; return; }
    const fresh = st.events.filter((e) => e.seq > L.seq);
    const quiet = !L.primed;      // the first poll after a page load: show the log, but do not toast old alerts
    L.primed = true;
    L.seq = Math.max(L.seq, st.seq);
    L.st = st;
    if (fresh.length) {
      L.feed = fresh.slice().reverse().concat(L.feed).slice(0, 600);
      for (const ev of fresh) {
        if (ev.type === "alert" && !ev.initial && !quiet) {
          toast(ev);
          if (dr.hidden || document.hidden) L.unseen++;
        }
      }
      drawFeed();
    }
    // the dataset grew: refresh every tab (and the rules' timing)
    if (L.loads >= 0 && st.loads > L.loads && st.dataset_is_live) {
      if (L.refresh) {
        try { const s = await api("/api/state"); if (s.loaded) { L.actors = null; setSummary(s.summary); } } catch (e) { /* the next load tries again */ }
      }
      if (!dr.hidden) loadRules();
    }
    L.loads = st.loads;
    drawStatus();
    badge();
    clearTimeout(L.timer);
    if (st.watching) L.timer = setTimeout(poll, Math.max(1000, Math.min(4000, (st.interval_s || 2) * 600)));
  }

  function drawStatus() {
    const st = L.st;
    if (!st) return;
    $("lvStart").disabled = false;
    $("lvStop").disabled = !st.watching;
    if (st.path && !$("lvPath").value) $("lvPath").value = st.path;
    if (st.watching) $("lvInt").value = st.interval_s;
    const bits = [];
    if (st.watching) bits.push(`<b class="lvlive"><i class="lvdot"></i>watching</b> <code>${esc(st.path)}</code> every ${st.interval_s} s${st.pack_name ? ` · pack: ${esc(st.pack_name)}` : ""}`);
    else bits.push(st.path ? `Stopped. Last watched <code>${esc(st.path)}</code>.` : "Not watching.");
    if (st.loading) bits.push("analyzing the new records…");
    if (st.last_load) bits.push(`${plural(st.loads, "load")}, the last at ${esc(st.last_load.slice(11, 19))} UTC (${st.load_s} s): ${plural(st.records, "record")}, ${plural(st.actors, "named actor")}, ${plural(st.messages, "message")}, ${plural(st.signs, "warning sign")}`);
    if (st.note) bits.push(esc(st.note));
    if (st.watching && st.last_load && !st.dataset_is_live) bits.push("another dataset is loaded in the app now");
    $("lvStatus").innerHTML = bits.join(" · ") + (st.error ? `<div class="lverr">${esc(st.error)}</div>` : "");
  }

  function feedRow(ev) {
    const s = SEV[ev.severity] || null;
    const icon = { sign: "⚑", alert: "!", pack: "◆", records: "+", actors: "◉", messages: "↔", load: "▤", started: "▶", stopped: "■", error: "×" }[ev.type] || "·";
    const chips = [ev.record ? ent.rec(ev.record) : "", ...(Array.isArray(ev.records) ? ev.records.slice(0, 6).map((r) => ent.rec(r)) : []),
      ...(ev.actors || []).slice(0, 6).map((a) => ent.actor(a))].filter(Boolean).join(" ");
    const more = Array.isArray(ev.records) && ev.count > ev.records.length ? ` <span class="small muted">+${fmt(ev.count - Math.min(6, ev.records.length))} more</span>` : "";
    return `<div class="lvev lv-${esc(ev.type)}${ev.initial ? " lvinit" : ""}" style="${s ? `--sev:${s.color};--sevbg:${s.bg}` : ""}">
      <span class="lvicon" aria-hidden="true">${icon}</span>
      <div class="lvevb">
        <div>${s && (ev.type === "alert" || ev.type === "sign") ? `<span class="lvsev">${esc(ev.type === "alert" ? s.label : FAMILY[ev.family]?.label || "sign")}</span> ` : ""}<b>${esc(ev.text)}</b>${ev.initial ? ' <span class="small muted">(already in the first load)</span>' : ""}</div>
        ${ev.why ? `<div class="small muted">${esc(ev.why)}</div>` : ""}
        ${chips ? `<div class="lvchips">${chips}${more}</div>` : ""}
        <div class="small faint">seen ${esc(ev.at.slice(11, 19))} UTC${ev.time ? ` · in the data at ${esc(when(toTime(ev.time)))}` : ""}${ev.harm_share_after != null ? ` · ${pct(ev.harm_share_after)} of the dated harmful actions loaded so far are later` : ""}</div>
      </div></div>`;
  }
  function drawFeed() {
    const n = L.feed.filter((e) => e.type === "alert").length, g = L.feed.filter((e) => e.type === "sign").length;
    $("lvCount").textContent = L.feed.length ? `(${plural(g, "sign")}, ${plural(n, "alert")})` : "";
    const rows = L.all ? L.feed : L.feed.filter((e) => !["records", "actors", "messages"].includes(e.type));
    $("lvFeed").innerHTML = rows.length ? rows.map(feedRow).join("") : `<p class="small muted">Nothing yet.</p>`;
  }
  $("lvClear").addEventListener("click", () => { L.feed = []; drawFeed(); });
  $("lvAll").addEventListener("change", (e) => { L.all = e.target.checked; drawFeed(); });
  $("lvRefresh").addEventListener("change", (e) => { L.refresh = e.target.checked; });

  $("lvStart").addEventListener("click", async () => {
    const path = $("lvPath").value.trim();
    if (!path) { $("lvStatus").innerHTML = `<div class="lverr">Give the path of a trace file or folder on this machine.</div>`; return; }
    $("lvStart").disabled = true;
    try {
      await api("/api/x/live_start", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, pack: $("lvPack").value || "auto", interval_s: +$("lvInt").value || 2 }) });
      L.loads = 0;
      poll();
    } catch (e) { $("lvStatus").innerHTML = `<div class="lverr">${esc(e.message)}</div>`; $("lvStart").disabled = false; }
  });
  $("lvStop").addEventListener("click", async () => {
    try { await api("/api/x/live_stop", { method: "POST", body: "{}" }); } catch (e) { /* shown by poll */ }
    poll();
  });

  // ------------------------------------------------------------------ rules
  async function loadRules() {
    try {
      L.rules = await api("/api/x/rules");
      L.evalr = S.summary ? await api("/api/x/rules_eval").catch(() => null) : null;
      if (L.evalr?.kinds) L.kinds = L.evalr.kinds;
    } catch (e) { $("lvRules").innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
    drawRules();
  }

  function drawRules() {
    const R = L.rules, E = L.evalr;
    const by = new Map((E?.rules || []).map((r) => [r.id, r]));
    $("lvRuleNote").innerHTML = `${R.saved ? `Saved at <code>${esc(R.path)}</code>.` : "The default rules (nothing saved yet); saving writes them to <code>" + esc(R.path) + "</code>."}
      ${E ? ` Timing on <b>${esc(E.dataset)}</b>: ${plural(E.signals, "warning sign")}, ${fmt(E.harm_total)} dated harmful actions.${E.note ? " " + esc(E.note) : ""}` : " Load a dataset to see when each rule fires."}`;
    $("lvRules").innerHTML = R.rules.map((r, i) => {
      const e = by.get(r.id), s = SEV[r.severity] || SEV.info;
      const fired = e ? (e.fired ? `fires at <b>${esc(when(toTime(e.time)))}</b> ${e.record ? "on " + ent.rec(e.record) : ""} ${(e.actors || []).slice(0, 2).map((a) => ent.actor(a)).join(" ")}
          ${e.harm_share_after != null ? `<div class="lvharm">${meter(e.harm_share_after, s.color, 90)} <b>${pct(e.harm_share_after)}</b> <span class="muted">of the harm still to come</span>${e.hours_before_baseline != null && r.id !== "baseline-volume" ? ` · ${e.hours_before_baseline >= 0 ? hoursWord(e.hours_before_baseline) + " before" : hoursWord(-e.hours_before_baseline) + " after"} the volume alarm` : ""}</div>` : ""}
          <div class="small muted">${esc(e.why || "")}</div>` : `<span class="muted">does not fire on this data</span>`) : "";
      return `<div class="lvrule${r.enabled ? "" : " off"}" style="--sev:${s.color};--sevbg:${s.bg}">
        <div class="lvrh"><span class="lvsev">${esc(s.label)}</span><b>${esc(r.name)}</b>${r.enabled ? "" : ' <span class="small muted">(off)</span>'}
          <span class="lvract"><button type="button" class="link" data-edit="${i}">edit</button><button type="button" class="link" data-del="${i}">delete</button></span></div>
        <div class="small muted">${r.match === "any" ? "any of" : "all of"}: ${r.conditions.map(condWord).map(esc).join("; ")}</div>
        ${e ? `<div class="lvfire">${fired}</div>` : ""}
        ${e?.hindsight ? `<div class="lvhind small">${esc(e.hindsight_note)}</div>` : ""}
      </div>`;
    }).join("") || `<p class="small muted">No rules. Add one, or restore the defaults.</p>`;
    $("lvRules").querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => edit(+b.dataset.edit)));
    $("lvRules").querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
      const r = R.rules[+b.dataset.del];
      if (!confirm(`Delete the rule "${r.name}"?`)) return;
      await save(R.rules.filter((_, j) => j !== +b.dataset.del));
    }));
  }

  function condWord(c) {
    if (c.type === "sign") return `a sign ${c.families.length ? "of " + c.families.map((f) => FAMILY[f]?.label || f).join(" or ") : ""}${c.kinds.length ? ` (${c.kinds.map((k) => KIND_WORD[k] || human(k)).join(" or ")})` : ""}`.replace("a sign ", "a sign ").trim();
    if (c.type === "coordination_kinds") return `${c.n}+ kinds of coordination`;
    if (c.type === "harm_rate") return `${c.per_hour}+ harmful actions within an hour`;
    if (c.type === "messages_between") return `${c.n}+ messages ${c.a && c.b ? `between ${short(c.a)} and ${short(c.b)}` : c.a || c.b ? `involving ${short(c.a || c.b)}` : "between named actors"}`;
    if (c.type === "group_size") return `a message-linked group of ${c.size}+ actors${c.actor ? ` including ${short(c.actor)}` : ""}`;
    return c.type;
  }

  async function save(rules) {
    try {
      L.rules = await api("/api/x/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rules }) });
      L.editing = null; $("lvEdit").innerHTML = "";
      L.evalr = S.summary ? await api("/api/x/rules_eval").catch(() => null) : null;
      drawRules();
      return true;
    } catch (e) { const m = $("lvEditMsg"); if (m) m.textContent = e.message; else status(e.message, true); return false; }
  }

  // ------------------------------------------------------------------ rule editor
  const blank = () => ({ name: "", severity: "alert", enabled: true, match: "all", conditions: [{ type: "coordination_kinds", n: 2 }] });
  function edit(i) {
    L.editing = { i, r: JSON.parse(JSON.stringify(i == null ? blank() : L.rules.rules[i])) };
    drawEdit();
    $("lvEdit").scrollIntoView({ block: "nearest" });
  }
  $("lvAdd").addEventListener("click", () => edit(null));

  function condFields(c, k) {
    const num = (key, label, min = 1) => `<label>${label} <input type="number" min="${min}" step="1" data-k="${k}" data-f="${key}" value="${esc(c[key] ?? "")}"></label>`;
    const txt = (key, label, ph) => `<label>${label} <input data-k="${k}" data-f="${key}" value="${esc(c[key] ?? "")}" placeholder="${esc(ph)}" list="lvActors" spellcheck="false"></label>`;
    if (c.type === "sign") {
      const fams = c.families || [], kinds = c.kinds || [];
      const known = [...new Set([...KINDS, ...L.kinds])];
      return `<div class="lvchecks"><span class="small muted">families (none = any):</span>${["single", "joint", "baseline"].map((f) => `<label class="chk"><input type="checkbox" data-k="${k}" data-fam="${f}" ${fams.includes(f) ? "checked" : ""}> ${esc(FAMILY[f]?.label || f)}</label>`).join("")}</div>
        <div class="lvchecks"><span class="small muted">kinds (none = any):</span>${known.map((x) => `<label class="chk" title="${esc(KIND_WORD[x] || x)}"><input type="checkbox" data-k="${k}" data-kind="${esc(x)}" ${kinds.includes(x) ? "checked" : ""}> ${esc(human(x))}</label>`).join("")}</div>`;
    }
    if (c.type === "coordination_kinds") return num("n", "N kinds");
    if (c.type === "harm_rate") return num("per_hour", "N per hour");
    if (c.type === "messages_between") return txt("a", "actor", "any named actor") + txt("b", "and actor", "any") + num("n", "N messages");
    if (c.type === "group_size") return num("size", "N actors", 2) + txt("actor", "including", "any actor");
    return "";
  }

  function drawEdit() {
    const ed = L.editing;
    if (!ed) { $("lvEdit").innerHTML = ""; return; }
    const r = ed.r;
    const actors = L.actors || [];
    if (!L.actors && S.summary) cached("/api/pairs?limit=500").then((p) => {
      L.actors = [...new Set(p.rows.flatMap((x) => [x.from, x.to]))].sort();
      const dl = $("lvActors"); if (dl) dl.innerHTML = L.actors.slice(0, 300).map((a) => `<option value="${esc(a)}">`).join("");
    }).catch(() => {});
    $("lvEdit").innerHTML = `<form class="lvform" id="lvForm" autocomplete="off">
      <h5>${ed.i == null ? "New rule" : "Edit rule"}</h5>
      <label>Name <input id="lvRName" value="${esc(r.name)}" required placeholder="e.g. Alert: three kinds of coordination"></label>
      <div class="lvrow">
        <label>Severity <select id="lvRSev">${["alert", "watch", "info"].map((s) => `<option${s === r.severity ? " selected" : ""}>${s}</option>`).join("")}</select></label>
        <label>Fires when <select id="lvRMatch"><option value="all"${r.match !== "any" ? " selected" : ""}>all conditions hold</option><option value="any"${r.match === "any" ? " selected" : ""}>any condition holds</option></select></label>
        <label class="chk"><input type="checkbox" id="lvREn" ${r.enabled ? "checked" : ""}> on</label>
      </div>
      ${r.conditions.map((c, k) => `<div class="lvcond">
        <div class="lvrow"><select data-k="${k}" data-type="1">${Object.entries(COND).map(([t, w]) => `<option value="${t}"${t === c.type ? " selected" : ""}>${esc(w)}</option>`).join("")}</select>
        ${r.conditions.length > 1 ? `<button type="button" class="link" data-rm="${k}">remove</button>` : ""}</div>
        <div class="lvrow lvcf">${condFields(c, k)}</div></div>`).join("")}
      <datalist id="lvActors">${actors.slice(0, 300).map((a) => `<option value="${esc(a)}">`).join("")}</datalist>
      <div class="lvrow"><button type="button" id="lvAddCond">Add a condition</button></div>
      <div class="lvrow"><button type="submit" class="primary">Save rule</button><button type="button" id="lvCancel">Cancel</button><span id="lvEditMsg" class="lverr small"></span></div>
      <p class="small muted">Saving records that this dataset was loaded when the rule was written: its timing here will be marked as hindsight.</p>
    </form>`;
    const f = $("lvForm");
    const sync = () => {
      r.name = $("lvRName").value; r.severity = $("lvRSev").value; r.match = $("lvRMatch").value; r.enabled = $("lvREn").checked;
      f.querySelectorAll("[data-f]").forEach((x) => { const c = r.conditions[+x.dataset.k]; c[x.dataset.f] = x.type === "number" ? (x.value === "" ? "" : +x.value) : x.value.trim(); });
      r.conditions.forEach((c, k) => {
        if (c.type !== "sign") return;
        c.families = [...f.querySelectorAll(`[data-k="${k}"][data-fam]:checked`)].map((x) => x.dataset.fam);
        c.kinds = [...f.querySelectorAll(`[data-k="${k}"][data-kind]:checked`)].map((x) => x.dataset.kind);
      });
    };
    f.querySelectorAll("[data-type]").forEach((s) => s.addEventListener("change", () => {
      sync();
      const k = +s.dataset.k;
      r.conditions[k] = { type: s.value, ...{ sign: { families: [], kinds: [] }, coordination_kinds: { n: 2 }, harm_rate: { per_hour: 10 },
        messages_between: { a: "", b: "", n: 1 }, group_size: { size: 3, actor: "" } }[s.value] };
      drawEdit();
    }));
    f.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => { sync(); r.conditions.splice(+b.dataset.rm, 1); drawEdit(); }));
    $("lvAddCond").addEventListener("click", () => { sync(); r.conditions.push({ type: "sign", families: ["joint"], kinds: [] }); drawEdit(); });
    $("lvCancel").addEventListener("click", () => { L.editing = null; drawEdit(); });
    f.addEventListener("submit", async (e) => {
      e.preventDefault(); sync();
      const rules = L.rules.rules.slice();
      if (ed.i == null) rules.push(r); else rules[ed.i] = r;
      await save(rules);
    });
  }

  // ------------------------------------------------------------------ export, import, reset
  $("lvExport").addEventListener("click", async () => {
    const R = await api("/api/x/rules");
    const blob = new Blob([JSON.stringify({ version: 1, rules: R.rules }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "swarm-tracer-rules.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
  $("lvImport").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const rules = Array.isArray(data) ? data : data.rules;
      if (!Array.isArray(rules)) throw new Error("the file has no list of rules");
      if (!confirm(`Replace the ${plural(L.rules.rules.length, "rule")} now saved with the ${plural(rules.length, "rule")} in ${file.name}?`)) return;
      if (await save(rules)) status(`Imported ${plural(rules.length, "rule")} from ${file.name}.`);
    } catch (err) { status(`Could not import ${file.name}: ${err.message}`, true); }
  });
  $("lvReset").addEventListener("click", async () => {
    if (!confirm("Replace the saved rules with the defaults?")) return;
    L.rules = await api("/api/x/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reset: true }) });
    L.evalr = S.summary ? await api("/api/x/rules_eval").catch(() => null) : null;
    drawRules();
  });

  document.addEventListener("visibilitychange", () => { if (!document.hidden && !dr.hidden) { L.unseen = 0; badge(); } });
  // pick up a live session that is already running (e.g. after a page reload)
  window.addEventListener("load", () => setTimeout(poll, 300));
})();

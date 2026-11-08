// Readers: the detected trace format in the overview's read report, logged direct messages
// (inbox places), and the pack builder (Load data -> "Build a pack from a sample…").
(() => {
  "use strict";

  GLOSSARY.direct = ["Direct message (logged)", "A message the trace itself addresses from one actor to another: a recipient field, a handoff span, a delegation to a coworker. The strongest evidence of who talked to whom, because nothing is inferred. It is drawn on the recipient's inbox place."];
  GLOSSARY.format = ["Trace format", "The shape the file was recognised as (for example OpenTelemetry spans, LangSmith runs, AutoGen messages, an MCP tool-call log). A recognised format is read with that framework's own fields for actor, time, parent, tool and recipient; anything else is read by field name."];
  if (typeof PLACE_TYPES === "object") PLACE_TYPES.inbox = ["inbox (direct messages)", "inboxes (direct messages)"];

  // ---------------------------------------------------------------- the overview's read report names the format
  const baseOverview = VIEWS.overview;
  if (baseOverview) {
    VIEWS.overview = async (el, s) => {
      const r = await baseOverview(el, s);
      try { addFormat(el, s); } catch (e) { /* the overview still stands */ }
      return r;
    };
  }
  function addFormat(el, s) {
    const rr = s.read_report || {};
    if (!rr.format || el.querySelector(".rdformat")) return;
    const h = [...el.querySelectorAll(".ovmethod h4")].find((x) => x.textContent.trim() === "Files");
    if (!h) return;
    const files = rr.files || [];
    const per = files.length > 1 ? ` <span class="muted">(${files.map((f) => `${esc(f.file)}: ${esc(f.format || "")}`).join("; ")})</span>` : "";
    const f = s.flow || {};
    const dm = f.direct_messages ? ` ${plural(f.direct_messages, "logged direct message")} ${f.direct_messages === 1 ? "was" : "were"} read from it as ${term("direct", "direct messages")}${f.direct_messages_undated ? `, ${fmt(f.direct_messages_undated)} more had no time and are not counted` : ""}.` : "";
    h.insertAdjacentHTML("beforebegin", `<p class="rdformat small">${term("format", "Format")} detected: <b>${esc(rr.format)}</b>${per}.${dm}</p>`);
  }

  // ---------------------------------------------------------------- pack builder
  const btn = $("packbuild");
  if (!btn) return;
  let modal = null, sug = null;

  function open() {
    if (!modal) {
      document.body.insertAdjacentHTML("beforeend", `
      <div id="pbwrap" class="pbwrap" hidden>
        <div class="pbmodal" role="dialog" aria-modal="true" aria-labelledby="pbtitle">
          <header class="pbhead"><h3 id="pbtitle">Build a pack from a sample</h3><button type="button" class="link" id="pbclose" aria-label="Close">Close</button></header>
          <div class="pbscroll">
            <p class="muted small">Pick a small sample of your trace (a few hundred to a few thousand records). Its format is detected, and a pack is proposed from what the records contain: repeated identity tokens, places several actors use, frequent tools and endpoints, and which kinds of record are actions. Tick what fits, name it, and save. Nothing leaves this machine.</p>
            <label class="pbfile">Sample file <input type="file" id="pbfile" accept=".csv,.jsonl,.json,.tsv,.txt,.log"></label>
            <div id="pbbody"></div>
          </div>
          <footer class="pbfoot" id="pbfoot" hidden>
            <label>Name <input id="pbname" maxlength="60"></label>
            <label class="grow">Description <input id="pbdesc" maxlength="300"></label>
            <button type="button" id="pbsave" class="primary">Save pack</button>
            <span id="pbstatus" class="small muted"></span>
          </footer>
        </div>
      </div>`);
      modal = $("pbwrap");
      $("pbclose").addEventListener("click", close);
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal && !modal.hidden) close(); });
      $("pbfile").addEventListener("change", pick);
      $("pbsave").addEventListener("click", save);
    }
    modal.hidden = false;
    $("pbfile").focus();
  }
  function close() { if (modal) modal.hidden = true; }

  btn.addEventListener("click", (e) => { e.preventDefault(); open(); });

  async function pick() {
    const f = $("pbfile").files[0];
    if (!f) return;
    const body = $("pbbody");
    $("pbfoot").hidden = true;
    body.innerHTML = `<p class="muted">Reading ${esc(f.name)}…</p>`;
    try {
      let blob = f;
      // a big line-based file: the first few MB are a sample (cut at a line end)
      if (f.size > 8e6 && /\.(jsonl|csv|tsv|txt|log)$/i.test(f.name)) {
        const buf = new Uint8Array(await f.slice(0, 8e6).arrayBuffer());
        let end = buf.lastIndexOf(10);
        blob = new Blob([buf.slice(0, end > 0 ? end + 1 : buf.length)]);
      }
      sug = await api("/api/x/pack_suggest?" + new URLSearchParams({ filename: f.name }), { method: "POST", body: blob });
      render(sug, f.size !== blob.size);
    } catch (e) {
      body.innerHTML = `<p class="bad">Could not build a pack from this file: ${esc(e.message)}</p>`;
    }
  }

  const exs = (list) => (list || []).length ? `<ul class="pbex">${list.map((x) => `<li><code>${esc(x.id)}</code> ${esc(x.text)}</li>`).join("")}</ul>` : "";
  const chk = (group, i, on) => `<input type="checkbox" data-g="${group}" data-i="${i}"${on ? " checked" : ""}>`;

  function section(title, sub, rows, empty) {
    return `<section class="pbsec"><h4>${title}</h4><p class="muted small">${sub}</p>${rows.length ? `<div class="pblist">${rows.join("")}</div>` : `<p class="small faint">${empty}</p>`}</section>`;
  }

  function render(s, cut) {
    const st = s.stats;
    const roles = ["id", "text", "kind", "parent", "actor", "time", "tool", "channel", "to"];
    const label = { to: "recipient", channel: "thread / place" };
    const cols = roles.map((r) => `<tr><td>${esc(label[r] || r)}</td><td>${(s.columns[r] || []).length ? `<code>${esc(s.columns[r].join("; "))}</code>` : '<span class="faint">not found</span>'}</td></tr>`).join("");
    const share = (n) => `${fmt(n)} <span class="muted">(${pct(st.records ? n / st.records : 0)})</span>`;
    const ident = s.identity.map((x, i) => `<label class="pbrow">${chk("identity", i, true)}<div><b>${esc(x.label)}</b> <code>${esc(x.entry.pattern)}</code>
      <div class="small muted">${plural(x.records, "record")} by ${plural(x.actors, "actor")}; ${plural(x.repeated_tokens, "token")} used more than once (${x.top_tokens.map(([t, c]) => `<code>${esc(t)}</code> ×${fmt(c)}`).join(", ")})</div>${exs(x.examples)}</div></label>`);
    const places = s.places.map((x, i) => `<label class="pbrow">${chk("places", i, x.suggested)}<div><b>${esc(x.label)}</b> <span class="muted small">${esc(x.type)}</span>
      <div class="small muted">${plural(x.records, "record")}, ${plural(x.actors, "actor")}: ${fmt(x.writers)} writing, ${fmt(x.readers)} only reading</div>${exs(x.examples)}</div></label>`);
    const src = { tool: "tool", endpoint: "HTTP endpoint", verb: "leading verb" };
    const intents = s.intents.map((x, i) => `<label class="pbrow">${chk("intents", i, x.suggested)}<div><b>${esc(x.label)}</b> <span class="muted small">${esc(src[x.source] || x.source)} · ${plural(x.records, "record")}</span>${exs(x.examples.slice(0, 2))}</div></label>`);
    const kinds = s.kinds.map((x, i) => `<label class="pbrow">${chk("kinds", i, x.suggested)}<div><b>${esc(x.kind)}</b> <span class="muted small">${plural(x.records, "record")}, ${fmt(x.with_tool)} with a tool, ${fmt(x.with_actor)} with an actor</span>${exs(x.examples.slice(0, 1))}</div></label>`);
    $("pbbody").innerHTML = `
      <section class="pbsec"><h4>How the sample was read</h4>
        <p class="small">${term("format", "Format")}: <b>${esc(s.format)}</b>. ${plural(st.records, "record")}${cut ? " (the first part of the file)" : ""}: ${share(st.with_actor)} with an actor (${plural(st.actors, "distinct actor")}), ${share(st.with_time)} with a time, ${share(st.with_parent)} with a parent, ${share(st.with_tool)} with a tool, ${share(st.addressed)} addressed to another actor.</p>
        <table class="pbcols"><tbody>${cols}</tbody></table>
        <p class="muted small">Columns are found automatically when the trace is analyzed; set them by hand under Columns in the Load data panel if one is wrong.</p></section>
      ${section("Identity tokens", "Repeated credential-like or placeholder tokens. When a record has no actor field, the token it uses names its actor.", ident, "No token repeats in this sample.")}
      ${section("Places", "Web addresses and file or folder names that several records name. Writing to a place and later reading it is how agents pass information without a direct message.", places, "No place is named by two records or more.")}
      ${section("Intents", "What a record is trying to do, from its tool, an HTTP endpoint or its first word. The first ticked pattern that matches a record names its intent; anything else is \"other\".", intents, "No tool, endpoint or verb repeats.")}
      ${section("Action kinds", "Records of these kinds are actions an agent took; the rest (results, system prompts) are places where information is seen. Leave all ticked to treat every record as an action.", kinds, "No kinds.")}`;
    $("pbname").value = s.name;
    $("pbdesc").value = s.description;
    $("pbstatus").textContent = "";
    $("pbfoot").hidden = false;
  }

  function picked(group) {
    return [...modal.querySelectorAll(`input[data-g="${group}"]`)].filter((c) => c.checked).map((c) => +c.dataset.i);
  }

  function buildPack() {
    const s = sug;
    const uniq = (entries) => {
      const seen = new Map();
      return entries.map((e) => {
        const n = seen.get(e.name) || 0;
        seen.set(e.name, n + 1);
        return n ? { ...e, name: `${e.name}_${n + 1}` } : e;
      });
    };
    const pack = { ...JSON.parse(JSON.stringify(s.base)), name: $("pbname").value.trim(), description: $("pbdesc").value.trim() };
    pack.identity_patterns = picked("identity").map((i) => s.identity[i].entry);
    pack.channels = uniq(picked("places").map((i) => s.places[i].entry));
    pack.intents = uniq([...picked("intents").map((i) => s.intents[i].entry), { name: "other", pattern: "." }]);
    const kinds = picked("kinds");
    if (kinds.length && kinds.length < s.kinds.length) pack.action_kinds = kinds.map((i) => s.kinds[i].kind);
    pack.built_from = { file: s.file, format: s.format, records: s.stats.records };
    return pack;
  }

  async function save() {
    const st = $("pbstatus");
    const pack = buildPack();
    if (!pack.name) { st.textContent = "Give the pack a name."; st.className = "small bad"; return; }
    const post = (over) => api("/api/x/pack_save" + (over ? "?overwrite=1" : ""), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(pack) });
    st.className = "small muted";
    st.textContent = "Saving…";
    let r;
    try {
      r = await post(false);
    } catch (e) {
      if (/already exists/.test(e.message) && confirm(`${e.message}. Replace it?`)) {
        try { r = await post(true); } catch (e2) { st.textContent = e2.message; st.className = "small bad"; return; }
      } else { st.textContent = e.message; st.className = "small bad"; return; }
    }
    await refreshPacks(r.file);
    st.className = "small ok";
    st.textContent = `Saved as ${r.file}. It is selected in the Pack list; analyze a trace to use it.`;
    setTimeout(() => { close(); $("loadpanel").hidden = false; }, 1200);
  }

  async function refreshPacks(selected) {
    const p = await api("/api/packs");
    $("pack").innerHTML = p.packs.map((x) => `<option value="${esc(x.file)}" title="${esc(x.description)}"${x.file === selected ? " selected" : ""}>${esc(x.name)}</option>`).join("");
  }
})();

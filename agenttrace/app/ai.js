// AI investigator (right bottom). The model answers in a fixed JSON shape (agenttrace/ai_answer_format.md);
// each block is drawn as a card or chart from the analysis, and every record id, actor and place it names
// has already been checked against the data on the server. Plain text answers still render.
"use strict";
(() => {
  const CONF = { high: { w: 1, c: "#2e7d32", label: "high confidence" }, medium: { w: 0.62, c: "#c58a00", label: "medium confidence" }, low: { w: 0.3, c: "#b42318", label: "low confidence" } };
  const confBadge = (c) => { const k = CONF[String(c || "").toLowerCase()]; return k ? `<span class="conf" style="--c:${k.c}"><i style="width:${k.w * 100}%"></i></span><span class="conflabel" style="color:${k.c}">${k.label}</span>` : ""; };
  const idChips = (it) => {
    const miss = new Set(it._missing || []);
    return (it.ids || []).map((x) => miss.has(x) ? `<span class="ent rec missing" title="Not found in this dataset">${esc(x)}</span>` : ent.rec(x)).join(" ");
  };
  const nameChip = (name, kind) => kind === "record" ? ent.rec(name) : kind === "actor" ? ent.actor(name) : kind === "place" ? ent.place(name) : `<span class="ent missing" title="Not found in this dataset">${esc(name)}</span>`;
  const actorChip = (it) => it.actor ? (it._actor_missing ? `<span class="ent missing" title="No actor with this name in the data">${esc(it.actor)}</span>` : ent.actor(it.actor)) : "";

  // ---------------------------------------------------------------- one renderer per block type
  const R = {
    stats(b) {
      return `<div class="aistats">${(b.items || []).map((it) => `<div class="aistat"><b>${esc(it.value)}</b><span>${esc(it.label)}</span>${(it.ids || []).length ? `<div class="ids">${idChips(it)}</div>` : ""}</div>`).join("")}</div>`;
    },
    timeline(b) {
      const items = (b.items || []).map((it) => ({ ...it, t: toTime(it._data_time || it.time) })).sort((a, c) => (a.t ?? Infinity) - (c.t ?? Infinity));
      const sp = span();
      let strip = "";
      if (sp && items.some((i) => i.t != null)) {
        const W = 100;
        let lastP = -99, lift = 0;
        strip = `<div class="tlstrip" title="Where these moments fall in the whole incident">${items.filter((i) => i.t != null).map((i, k) => { const p = Math.max(0, Math.min(W, (i.t - sp[0]) / (sp[1] - sp[0]) * W)); lift = p - lastP < 4 ? lift + 1 : 0; lastP = p; return `<i style="left:${p}%;bottom:${-7 + lift * 13}px" title="${esc(i.label)}">${k + 1}</i>`; }).join("")}<span>${esc(dayWord(sp[0]))}</span><span>${esc(dayWord(sp[1] - 1))}</span></div>`;
      }
      return strip + `<ol class="aitl">${items.map((it, k) => {
        const off = it._data_time && it.time && it._data_time.slice(0, 16) !== String(it.time).slice(0, 16);
        return `<li><span class="n">${k + 1}</span><div class="tm">${esc(it.t != null ? when(it.t) : it.time || "time unknown")}${off ? `<span class="small warnc" title="The model said ${esc(it.time)}; the data says ${esc(it._data_time)}"> (data: ${esc(it._data_time)})</span>` : ""}</div><div class="lb">${esc(it.label)} ${actorChip(it)} ${idChips(it)}</div></li>`;
      }).join("")}</ol>`;
    },
    flow(b) {
      const edges = (b.edges || []).filter((e) => e && e.from && e.to);
      if (!edges.length) return "";
      // layers top to bottom: each node one row below anything that points to it, so it fits a narrow pane
      const nodes = new Map();
      const add = (n, k) => { if (!nodes.has(n)) nodes.set(n, { n, kind: k, row: 0, outs: [] }); return nodes.get(n); };
      edges.forEach((e) => { const a = add(e.from, e._from_kind), c = add(e.to, e._to_kind); if (a !== c) a.outs.push(c); });
      for (let it = 0; it < nodes.size; it++) nodes.forEach((v) => v.outs.forEach((o) => { if (o.row <= v.row) o.row = Math.min(v.row + 1, 10); }));
      const rows = [];
      nodes.forEach((v) => (rows[v.row] ||= []).push(v));
      const avail = Math.max(240, Math.min(560, ($("chat")?.clientWidth || 400) - 48));
      const perRow = Math.max(...rows.map((r) => r?.length || 0));
      const GX = 10, NH = 24, GY = 30;
      const NW = Math.min(170, Math.floor((avail - GX * (perRow - 1)) / perRow));
      const W = avail, H = rows.length * (NH + GY) - GY + 8;
      rows.forEach((r, ri) => { const w = r.length * NW + (r.length - 1) * GX; (r || []).forEach((v, k) => { v.x = (W - w) / 2 + k * (NW + GX); v.y = 4 + ri * (NH + GY); }); });
      const fill = { actor: [C.actorBg, C.actor], place: [C.placeBg, C.place], record: [C.recordBg, ACCENT] };
      let svg = `<svg class="aiflow" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"><defs><marker id="afa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,1L10,5L0,9z" fill="#7a8794"/></marker></defs>`;
      edges.forEach((e) => {
        const a = nodes.get(e.from), c = nodes.get(e.to);
        if (a === c) return;
        const x1 = a.x + NW / 2, y1 = a.y + NH, x2 = c.x + NW / 2, y2 = c.y - 2;
        const d = c.row > a.row ? `M${x1},${y1} C${x1},${y1 + GY / 2} ${x2},${y2 - GY / 2} ${x2},${y2}` : `M${a.x + NW},${a.y + NH / 2} C${W - 4},${a.y + NH / 2} ${W - 4},${c.y + NH / 2} ${c.x + NW + 2},${c.y + NH / 2}`;
        svg += `<path d="${d}" fill="none" stroke="#9aa5b1" stroke-width="1.4" marker-end="url(#afa)"${(e.ids || [])[0] && !(e._missing || []).includes(e.ids[0]) ? ` data-id="${esc(e.ids[0])}" class="node"` : ""}><title>${esc(e.label || "")}</title></path>`;
        if (e.label && c.row > a.row) svg += `<text x="${(x1 + x2) / 2 + 6}" y="${(y1 + y2) / 2 + 3}" font-size="9.5" fill="${QUIET}">${esc(fitName(e.label, NW, "9.5px sans-serif"))}</text>`;
      });
      nodes.forEach((v) => {
        const [bg, st] = fill[v.kind] || ["#fdecea", "#b42318"];
        const attr = v.kind === "actor" ? `data-actor="${esc(v.n)}"` : v.kind === "place" ? `data-place="${esc(v.n)}"` : v.kind === "record" ? `data-id="${esc(v.n)}"` : "";
        const label = v.kind === "actor" ? short(v.n) : v.kind === "place" ? placeLabel(v.n) : v.n;
        svg += `<g class="node" ${attr}><rect x="${v.x}" y="${v.y}" width="${NW}" height="${NH}" rx="6" fill="${bg}" stroke="${st}"${v.kind ? "" : ' stroke-dasharray="3 2"'}/><text x="${v.x + NW / 2}" y="${v.y + NH / 2 + 4}" text-anchor="middle" font-size="11" fill="${INK}">${esc(fitName(label, NW - 10, "11px sans-serif"))}</text><title>${esc(v.n)}${v.kind ? "" : " (not found in the data)"}</title></g>`;
      });
      const labels = edges.filter((e) => e.label || (e.ids || []).length).map((e) => `<li>${nameChip(e.from, e._from_kind)} → ${nameChip(e.to, e._to_kind)} <span class="muted">${esc(e.label || "")}</span> ${idChips(e)}</li>`).join("");
      return `<div class="aiflowbox">${svg}</svg></div>${labels ? `<ul class="aiedges">${labels}</ul>` : ""}`;
    },
    actors(b) {
      const items = (b.items || []).slice(0, 8);
      const id = "aa" + Math.random().toString(36).slice(2, 8);
      setTimeout(() => items.forEach(async (it, k) => {
        const host = document.getElementById(id + k);
        if (!host || it._actor_missing || !it.actor) return;
        try {
          const p = await cached("/api/actor?a=" + encodeURIComponent(it.actor));
          host.innerHTML = `${spark(p.hourly, { w: 200, h: 26, color: C.actor })}<div class="hcstats"><span><b>${fmt(p.records)}</b> records</span><span><b>${fmt(p.sent)}</b> sent</span><span><b>${fmt(p.received)}</b> received</span><span><b>${fmt(p.partners)}</b> partners</span><span><b>${fmt(p.harmful)}</b> harmful</span></div>${p.intents.length ? stackbar(p.intents.slice(0, 4).map((i) => ({ label: human(i.intent), value: i.n, color: intentColor(i.intent) })), { legend: false, h: 6 }) : ""}`;
        } catch { host.innerHTML = ""; }
      }), 0);
      return `<div class="aiactors">${items.map((it, k) => `<div class="aiactor">${actorChip(it)}<div class="small">${esc(it.role || "")}</div><div id="${id}${k}" class="aiactorlive">${it._actor_missing ? '<span class="small warnc">not found in the data</span>' : '<span class="small muted">…</span>'}</div></div>`).join("")}</div>`;
    },
    evidence(b) {
      return `<div class="aicards">${(b.items || []).map((it) => `<div class="aicard ev"><div>${esc(it.claim)}</div><div class="ids">${idChips(it)}</div>${it.confidence ? `<div class="cf">${confBadge(it.confidence)}</div>` : ""}</div>`).join("")}</div>`;
    },
    inference(b) {
      return `<div class="aicards">${(b.items || []).map((it) => `<div class="aicard inf"><div><b>${esc(it.claim)}</b></div>${it.confidence ? `<div class="cf">${confBadge(it.confidence)}</div>` : ""}${it.alternative ? `<div class="alt"><span>Alternative</span>${esc(it.alternative)}</div>` : ""}${it.check ? `<div class="alt"><span>How to tell</span>${esc(it.check)}</div>` : ""}${(it.ids || []).length ? `<div class="ids">${idChips(it)}</div>` : ""}</div>`).join("")}</div>`;
    },
    bars(b) {
      const items = (b.items || []).filter((i) => Number.isFinite(+i.value));
      return items.length ? hbars(items.map((i) => ({ label: esc(i.label), value: +i.value, color: ACCENT })), { unit: b.unit ? " " + b.unit : "" }) : "";
    },
    table(b) {
      return table((b.columns || []).map(String), (b.rows || []).slice(0, 30).map((r) => (Array.isArray(r) ? r : [r]).map((c) => linkify(String(c ?? "")))));
    },
    unknowns(b) {
      return `<ul class="aiunk">${(b.items || []).map((x) => `<li>${esc(typeof x === "string" ? x : x.text || x.claim || JSON.stringify(x))}</li>`).join("")}</ul>`;
    },
    next(b) {
      return `<div class="ainext">${(b.items || []).map((it, k) => `<button type="button" data-next='${esc(JSON.stringify({ view: it.view, query: it.query, id: it._id_ok === false ? null : it.id, actor: it._actor_missing ? null : it.actor }))}'>${esc(it.label || "Open")} →</button>`).join("")}</div>`;
    },
  };
  const TITLES = { stats: "Key numbers", timeline: "In time order", flow: "What moved where", actors: "Who was involved", evidence: "Evidence", inference: "What it likely means", unknowns: "What the data cannot show", next: "Next step", bars: "", table: "" };
  const ICON = { stats: "▦", timeline: "⟶", flow: "⇄", actors: "◉", evidence: "✓", inference: "≈", unknowns: "?", next: "→", bars: "▤", table: "▤", gaps: "◌" };

  // record ids and exact names in free text become chips
  function linkify(s) {
    return esc(s).replace(/\b([A-Z]\d{4,})\b/g, (m) => `<span class="ent rec" data-id="${m}">${m}</span>`)
      .replace(/\[CREDENTIAL (\d+)\]/g, (m) => `<span class="ent actor" data-actor="${m}"><i></i>cred ${m.slice(12, -1)}</span>`);
  }

  function renderStructured(o) {
    const blocks = (o.blocks || []).filter((b) => b && R[b.type]);
    const ck = o._checks || {};
    let h = `<div class="aihead"><div class="aians">${linkify(o.answer || "")}</div>${o.confidence ? `<div class="cf">${confBadge(o.confidence)}</div>` : ""}</div>`;
    if (o.gaps) h += renderGaps(o.gaps);
    blocks.forEach((b) => {
      const body = R[b.type](b);
      if (!body) return;
      h += `<section class="aiblock ${b.type}"><h5><span class="ic">${ICON[b.type] || "•"}</span>${esc(b.title || TITLES[b.type] || "")}</h5>${body}</section>`;
    });
    const bad = (ck.ids_missing || []).length + (ck.names_missing || []).length;
    h += `<div class="aicheck ${bad ? "bad" : "ok"}">${bad ? `Checked against the data: ${fmt(ck.ids_found)} record id${ck.ids_found === 1 ? "" : "s"} found; <b>not found</b>: ${[...(ck.ids_missing || []), ...(ck.names_missing || [])].slice(0, 8).map(esc).join(", ")}${bad > 8 ? " …" : ""}. Treat claims that rest on them as unsupported.` : `Checked against the data: all ${fmt(ck.ids_found)} record ids and every name found.`}</div>`;
    return h;
  }
  const SEV = { high: "#b42318", medium: "#c58a00", low: "#5b6672" };
  function renderGaps(gaps) {
    return `<div class="gapcards">${gaps.map((g) => `<div class="gapcard" style="--c:${SEV[String(g.severity).toLowerCase()] || "#5b6672"}">
      <div class="gh"><span class="sev">${esc(g.severity || "")}</span><b>${esc(g.gap)}</b>${g.question ? `<span class="q">${esc(g.question)}</span>` : ""}</div>
      ${g.share != null && Number.isFinite(+g.share) ? `<div class="gm">${meter(+g.share, SEV[String(g.severity).toLowerCase()] || ACCENT, 140)} <b>${pct(+g.share)}</b> <span class="muted small">${esc(g.affected || "")}</span></div>` : g.affected ? `<div class="small muted">${esc(g.affected)}</div>` : ""}
      <div class="gx"><span>Hides</span>${esc(g.hides || "")}</div>
      <div class="gx"><span>To close it</span>${esc(g.close || "")}</div>
      ${(g.example_ids || []).length ? `<div class="ids">${idChips({ ids: g.example_ids, _missing: g._missing })}</div>` : ""}</div>`).join("")}</div>`;
  }
  window.renderAIStructured = renderStructured;
  window.renderAIGaps = renderGaps;

  function md(text) {
    let h = esc(text);
    h = h.replace(/```([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
    h = h.replace(/`([^`\s]{2,160})`/g, '<span class="ent rec" data-id="$1">$1</span>');
    h = h.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    h = h.replace(/^#{1,4} (.*)$/gm, "<b>$1</b>");
    h = h.replace(/(^|\n)[-*] (.*)/g, "$1• $2");
    h = h.replace(/(^|[\s(,])([A-Z]\d{4,})\b/g, '$1<span class="ent rec" data-id="$2">$2</span>');
    return h.replace(/\n/g, "<br>");
  }

  // ---------------------------------------------------------------- chat
  function addMsg(role, html, meta) {
    const empty = $("chat").querySelector(".aiempty"); if (empty) empty.remove();
    const d = document.createElement("div");
    d.className = "amsg " + role;
    d.innerHTML = html + (meta ? `<div class="meta">${meta}</div>` : "");
    $("chat").appendChild(d);
    d.querySelectorAll("[data-next]").forEach((b) => b.addEventListener("click", () => {
      const n = JSON.parse(b.dataset.next);
      if (n.id) selectEvent(n.id);
      if (n.actor) inspectActor(n.actor);
      if (n.view === "events" || (n.query && !n.view)) goEvents({ q: n.query || "" });
      else if (n.view && VIEWS[n.view]) goTab(n.view);
    }));
    d.querySelectorAll(".rawtoggle").forEach((b) => b.addEventListener("click", () => { const p = b.nextElementSibling; p.hidden = !p.hidden; }));
    if (role === "user") $("chat").scrollTop = $("chat").scrollHeight;
    else d.scrollIntoView({ block: "start", behavior: "smooth" });
    return d;
  }
  const settings = () => ({ apiKey: $("apiKey").value, baseUrl: $("baseUrl").value, model: $("model").value });
  function keyState() {
    const line = $("aiStateLine");
    line.className = $("apiKey").value ? "ok" : "";
    line.innerHTML = `<span class="dot"></span>${$("apiKey").value ? esc($("model").value) : "no key yet"}`;
  }
  async function askAI(q, { mode = "chat", host = null } = {}) {
    if (!S.summary) throw new Error("Load a dataset first.");
    if (!$("apiKey").value) { $("aisettings").hidden = false; throw new Error("Enter an API key in Settings first (it is the only thing the investigator needs)."); }
    const history = mode === "chat" ? S.chat.concat([{ role: "user", content: q }]) : [{ role: "user", content: q }];
    const cur = INS.stack.at(-1);
    const sel = $("useSel").checked && cur ? cur : null;
    const r = await api("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      messages: history, ...settings(), mode, selectedId: sel?.kind === "record" ? sel.key : null, selected: sel, conversation: S.conv || null, sessionId: S.aiSession }) });
    return r;
  }
  async function ask(q, fromBox = false) {
    if (!$("apiKey").value) {
      // keep the question where it was typed; say what is missing next to the box
      if (fromBox) $("q").value = q;
      $("aisettings").hidden = false; $("aiset").setAttribute("aria-expanded", "true");
      $("aistatus").textContent = "Add an API key here first: it is the only thing the investigator needs. Your question is kept.";
      $("aistatus").className = "small bad";
      $("apiKey").focus();
      return;
    }
    if (!S.summary) { addMsg("error", "Load a dataset first."); return; }
    S.chat.push({ role: "user", content: q });
    addMsg("user", esc(q).replace(/\n/g, "<br>"));
    const wait = addMsg("assistant", '<div class="aiwait"><i></i><i></i><i></i> Investigating: reading the brief and the records…</div>');
    $("send").disabled = true;
    try {
      const r = await askAI(q);
      wait.remove();
      S.chat.push({ role: "assistant", content: r.content });
      const meta = `${esc($("model").value)}${r.context_ids?.length ? " · records sent: " + r.context_ids.map((x) => ent.rec(x)).join(" ") : ""}${S.conv ? ` · conversation sent: ${esc(short(S.conv.a))} ↔ ${esc(short(S.conv.b))}` : ""}${r.usage?.total_tokens ? " · " + fmt(r.usage.total_tokens) + " tokens" : ""}`;
      const body = r.structured ? renderStructured(r.structured) + `<button type="button" class="link rawtoggle small">raw answer</button><pre hidden>${esc(r.content)}</pre>` : md(r.content);
      addMsg("assistant", body, meta);
    } catch (e) { wait.remove(); S.chat.pop(); addMsg("error", esc(e.message)); }
    finally { $("send").disabled = false; }
  }
  window.askAI = askAI;
  // the question for whatever the Inspector shows: a record, an actor or a place
  function selectedQuestion() {
    const cur = INS.stack.at(-1);
    if (!cur) return "Explain the most important finding in this swarm, with the records behind it.";
    if (cur.kind === "actor") return `Profile the actor ${cur.key}: what it did, who it exchanged messages with, which programs it shared, which warning signs it fired, and what the data cannot show about it.`;
    if (cur.kind === "place") return `Explain the place ${cur.key}: who wrote to it, who read it, which messages passed through it and in what order, and whether the redaction may have merged it.`;
    return `Explain the record ${cur.key} step by step: what the code does, who ran it, what it touched, what it received or passed on, and how it connects to the rest of the swarm.`;
  }
  window.askAbout = (id, q) => {
    if (id) { S.selected = id; $("useSel").checked = true; }
    ask(q || selectedQuestion());
  };

  // ---------------------------------------------------------------- settings
  $("aiwide").addEventListener("click", () => { document.body.classList.toggle("aiwide"); $("aiwide").textContent = document.body.classList.contains("aiwide") ? "Restore" : "Expand"; });
  $("aiset").addEventListener("click", () => { const h = $("aisettings").hidden; $("aisettings").hidden = !h; $("aiset").setAttribute("aria-expanded", String(h)); });
  $("closeSet").addEventListener("click", () => { $("aisettings").hidden = true; $("aiset").setAttribute("aria-expanded", "false"); });
  function saveAI() {
    const keep = $("remember").checked;
    sessionStorage.setItem("st-ai", JSON.stringify({ baseUrl: $("baseUrl").value, model: $("model").value, ...(keep ? { apiKey: $("apiKey").value } : {}) }));
    keyState();
  }
  ["baseUrl", "model", "apiKey", "remember"].forEach((id) => $(id).addEventListener("change", saveAI));
  $("apiKey").addEventListener("input", keyState);
  $("listModels").addEventListener("click", async () => {
    const st = $("aistatus");
    try { const r = await api("/api/ai/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ baseUrl: $("baseUrl").value, apiKey: $("apiKey").value }) });
      $("modellist").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join(""); st.textContent = `${r.models.length} models: ${r.models.join(", ")}`; st.className = "small ok"; }
    catch (e) { st.textContent = "Could not list models: " + e.message; st.className = "small bad"; }
  });
  const newSessionId = () => "ses_" + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : String(Date.now()) + Math.random().toString(16).slice(2));
  S.aiSession = newSessionId();
  $("newChat").addEventListener("click", () => { S.chat = []; S.aiSession = newSessionId(); $("chat").innerHTML = '<div class="aiempty">New chat.</div>'; $("aistatus").textContent = "Started a new chat."; });
  $("checkAI").addEventListener("click", async () => {
    const st = $("aistatus");
    if (!$("apiKey").value) { st.textContent = "Enter an API key first."; st.className = "small bad"; return; }
    st.textContent = "Checking…"; st.className = "small muted";
    try {
      const r = await api("/api/ai/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...settings(), sessionId: S.aiSession }) });
      st.textContent = `Connected: ${$("model").value} replied "${r.reply}".`; st.className = "small ok"; $("aiStateLine").className = "ok";
    } catch (e) { st.textContent = e.message; st.className = "small bad"; $("aiStateLine").className = "bad"; }
  });
  $("quick").addEventListener("click", (e) => { const b = e.target.closest("button[data-q]"); if (b) ask(b.dataset.q === "@selected" ? selectedQuestion() : b.dataset.q); });
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); const q = $("q").value.trim(); if (q) { $("q").value = ""; ask(q, true); } });
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("ask").requestSubmit(); });

  window.initAI = (d) => {
    const saved = JSON.parse(sessionStorage.getItem("st-ai") || "{}");
    $("baseUrl").value = saved.baseUrl || d.baseUrl;
    $("model").value = saved.model || d.model;
    if (saved.apiKey) { $("apiKey").value = saved.apiKey; $("remember").checked = true; }
    keyState();
  };
})();

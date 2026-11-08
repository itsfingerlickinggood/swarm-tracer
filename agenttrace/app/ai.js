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
      // _check: the server recounted this number from the data (only counts it can recount exactly)
      const chk = (it) => !it._check ? "" : it._check.ok
        ? `<span class="small" style="color:#2e7d32" title="Recounted from the data: ${esc(it._check.what)}">✓ recounted</span>`
        : `<span class="small" style="color:#b42318;display:block" title="${esc(it._check.what)}">✗ the data says ${esc(fmt(it._check.data))}</span>`;
      return `<div class="aistats">${(b.items || []).map((it) => `<div class="aistat"${it._check && !it._check.ok ? ' style="outline:1px solid #f1b8b2"' : ""}><b>${esc(it.value)}</b><span>${esc(it.label)}</span> ${chk(it)}${(it.ids || []).length ? `<div class="ids">${idChips(it)}</div>` : ""}</div>`).join("")}</div>`;
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
    h += numbersLine(ck) + factsList(o._facts, ck);
    return h;
  }
  // the "verify numbers" pass: counts in stats blocks the server could recount
  function numbersLine(ck) {
    if (!ck.numbers_checked) return "";
    const w = ck.numbers_mismatch || [];
    return `<div class="aicheck ${w.length ? "bad" : "ok"}">${w.length
      ? `Numbers recounted: ${fmt(ck.numbers_checked)}; <b>${fmt(w.length)} differ from the data</b>: ${w.slice(0, 5).map((m) => `${esc(m.label)} said ${esc(m.said)}, the data has ${esc(fmt(m.data))}`).join("; ")}.`
      : `Numbers recounted: all ${fmt(ck.numbers_checked)} count${ck.numbers_checked === 1 ? "" : "s"} the tool can recount match the data.`}</div>`;
  }
  // what the model fetched with the read-only tools before answering
  const TOOLNAME = { actor_profile: "Actor profile", place_detail: "Place", conversation: "Conversation", search_records: "Search", record_trace: "Record", trace_string: "Trace a string" };
  function factsList(facts, ck) {
    const notes = [ck.repaired ? "the first reply was not in the answer format and was re-asked once" : "",
      ck.tools && ck.tools !== "offered" ? "tools " + ck.tools + ", so it answered from the brief alone" : ""].filter(Boolean);
    const note = notes.length ? `<div class="small muted" style="margin-top:4px">Note: ${esc(notes.join("; "))}.</div>` : "";
    if (!facts || !facts.length) return ck.tools === "offered" ? `<div class="small muted" style="margin-top:4px">The investigator fetched no extra facts: it answered from the brief.</div>${note}` : note;
    const chip = (f) => {
      const a = f.args || {};
      if (f.tool === "actor_profile" && f.ok) return ent.actor(a.actor);
      if (f.tool === "place_detail" && f.ok) return ent.place(a.place);
      if (f.tool === "record_trace" && f.ok) return ent.rec(a.id);
      if (f.tool === "conversation" && f.ok) return ent.actor(a.a) + " ↔ " + ent.actor(a.b);
      return "";
    };
    return `<details class="aifacts" style="margin-top:6px;font-size:12px"><summary style="cursor:pointer">Facts the investigator fetched (${fmt(facts.length)}, in ${fmt(ck.tool_rounds || 1)} round${(ck.tool_rounds || 1) === 1 ? "" : "s"})</summary>
      <ol style="margin:4px 0 0 18px;padding:0">${facts.map((f) => `<li style="margin:2px 0"><b>${esc(TOOLNAME[f.tool] || f.tool)}</b> ${chip(f)} <span class="${f.ok ? "muted" : "warnc"}">${esc(f.summary || "")}</span></li>`).join("")}</ol></details>${note}`;
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
  // a model served on this machine (Ollama, LM Studio, a local proxy) needs no key
  const isLocal = (u) => { try { const h = new URL(u).hostname.replace(/^\[|\]$/g, ""); return ["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(h) || h.endsWith(".localhost"); } catch { return false; } };
  const keyOk = () => !!$("apiKey").value || isLocal($("baseUrl").value);
  window.aiKeyOk = keyOk;
  function keyState() {
    const line = $("aiStateLine");
    line.className = keyOk() ? "ok" : "";
    line.innerHTML = `<span class="dot"></span>${keyOk() ? esc($("model").value) + ($("apiKey").value ? "" : " (local, no key)") : "no key yet"}`;
    $("apiKey").placeholder = isLocal($("baseUrl").value) ? "not needed for a local model" : "oc_sk_... or sk-...";
  }
  async function askAI(q, { mode = "chat", host = null } = {}) {
    if (!S.summary) throw new Error("Load a dataset first.");
    if (!keyOk()) { $("aisettings").hidden = false; throw new Error("Enter an API key in Settings first (it is the only thing the investigator needs; a local model needs none)."); }
    const history = mode === "chat" ? S.chat.concat([{ role: "user", content: q }]) : [{ role: "user", content: q }];
    const cur = INS.stack.at(-1);
    const sel = $("useSel").checked && cur ? cur : null;
    const r = await api("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      messages: history, ...settings(), mode, selectedId: sel?.kind === "record" ? sel.key : null, selected: sel, conversation: S.conv || null, sessionId: S.aiSession }) });
    return r;
  }
  async function ask(q, fromBox = false) {
    if (!keyOk()) {
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
    const wait = addMsg("assistant", '<div class="aiwait"><i></i><i></i><i></i> Investigating: reading the brief, fetching facts it needs…</div>');
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
  $("baseUrl").addEventListener("input", keyState);
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
    if (!keyOk()) { st.textContent = "Enter an API key first (a model on localhost needs none)."; st.className = "small bad"; return; }
    st.textContent = "Checking…"; st.className = "small muted";
    try {
      const r = await api("/api/ai/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...settings(), sessionId: S.aiSession }) });
      st.textContent = `Connected: ${$("model").value} replied "${r.reply}".`; st.className = "small ok"; $("aiStateLine").className = "ok";
    } catch (e) { st.textContent = e.message; st.className = "small bad"; $("aiStateLine").className = "bad"; }
  });
  $("quick").addEventListener("click", (e) => { const b = e.target.closest("button[data-q]"); if (b) ask(b.dataset.q === "@selected" ? selectedQuestion() : b.dataset.q); });
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); const q = $("q").value.trim(); if (q) { $("q").value = ""; ask(q, true); } });
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("ask").requestSubmit(); });

  // ---------------------------------------------------------------- provider presets
  const PRESETS = [
    { id: "opencode", label: "OpenCode Go (default)", baseUrl: "https://opencode.ai/inference/go/openai/v1", model: "deepseek-v4.1-flash", note: "Key from the OpenCode console; DeepSeek models need the Global region turned on." },
    { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-5-mini", note: "Key from platform.openai.com. Press List models to pick another model." },
    { id: "anthropic", label: "Anthropic (OpenAI-compatible endpoint)", baseUrl: "https://api.anthropic.com/v1", model: "claude-sonnet-4-5", note: "Anthropic's OpenAI-format endpoint with an Anthropic API key." },
    { id: "proxy", label: "Claude or other models via a local proxy (LiteLLM)", baseUrl: "http://localhost:4000/v1", model: "claude-sonnet-4-5", note: "Any proxy that speaks the OpenAI format; on localhost the key is optional." },
    { id: "ollama", label: "Ollama on this machine", baseUrl: "http://localhost:11434/v1", model: "llama3.1", note: "Runs locally: nothing leaves this machine and no key is needed. Start it with `ollama run llama3.1`." },
    { id: "custom", label: "Custom", baseUrl: "", model: "", note: "Any OpenAI-compatible service: set its base URL, model and key." },
  ];
  (() => {
    const lab = document.createElement("label");
    lab.innerHTML = `Provider <select id="aipreset">${PRESETS.map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join("")}</select><span id="aipresetnote" class="small muted"></span>`;
    $("aisettings").insertBefore(lab, $("aisettings").firstElementChild);
    $("aipreset").addEventListener("change", () => {
      const p = PRESETS.find((x) => x.id === $("aipreset").value);
      if (p && p.id !== "custom") { $("baseUrl").value = p.baseUrl; $("model").value = p.model; }
      $("aipresetnote").textContent = p?.note || "";
      saveAI();
    });
    $("baseUrl").addEventListener("input", syncPreset);
  })();
  function syncPreset() {
    const p = PRESETS.find((x) => x.baseUrl && x.baseUrl === $("baseUrl").value.trim()) || PRESETS.find((x) => x.id === "custom");
    if ($("aipreset")) { $("aipreset").value = p.id; $("aipresetnote").textContent = p.note; }
  }

  // ---------------------------------------------------------------- incident report
  // the model drafts it as JSON (agenttrace/ai_report_format.md); every record id in it was checked on the server
  const inlineChips = (text, inline) => esc(text).replace(/`([^`\s]{2,160})`/g, (m, tok) => {
    const k = (inline || {})[tok] || [null, tok];
    if (k[0] === "record") return ent.rec(k[1]);
    if (k[0] === "actor") return ent.actor(k[1]);
    if (k[0] === "place") return ent.place(k[1]);
    return `<code${/^[A-Z]\d{4,}$/.test(tok) ? ' class="missing" title="Not found in this dataset"' : ""}>${tok}</code>`;
  }).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  function renderReport(o) {
    const ck = o._checks || {};
    const bad = (ck.ids_missing || []).length + (ck.names_missing || []).length;
    const tl = (o.timeline || []).map((it) => ({ ...it, t: toTime(it._data_time || it.time) })).sort((a, b) => (a.t ?? Infinity) - (b.t ?? Infinity));
    return `<article class="aireport">
      <h2>${esc(o.title || "Incident report")}</h2>
      <p class="small muted">Draft by ${esc($("model").value)} from the analysis of ${esc(S.summary?.name || "this dataset")}, ${esc(new Date().toISOString().slice(0, 10))}. Check it before you share it.</p>
      ${o.summary ? `<section><h3>Summary</h3><p>${inlineChips(o.summary)}</p></section>` : ""}
      ${tl.length ? `<section><h3>Timeline</h3><ol class="airtl">${tl.map((it) => {
        const off = it._data_time && it.time && it._data_time.slice(0, 16) !== String(it.time).slice(0, 16);
        return `<li><span class="tm">${esc(it.t != null ? when(it.t) : it.time || "time unknown")}${off ? ` <span class="warnc small" title="The model said ${esc(it.time)}; the data says ${esc(it._data_time)}">(data: ${esc(it._data_time)})</span>` : ""}</span><span>${esc(it.label || "")} ${idChips(it)}</span></li>`;
      }).join("")}</ol></section>` : ""}
      ${(o.sections || []).map((sec) => `<section><h3>${esc(sec.heading || "")}</h3>${(sec.paragraphs || []).map((p) => `<p>${inlineChips(p, sec._inline)}</p>`).join("")}${(sec.ids || []).length ? `<div class="ids small">Records: ${idChips(sec)}</div>` : ""}</section>`).join("")}
      ${(o.unknowns || []).length ? `<section><h3>What the data cannot show</h3><ul>${o.unknowns.map((x) => `<li>${inlineChips(typeof x === "string" ? x : JSON.stringify(x))}</li>`).join("")}</ul></section>` : ""}
      ${(o.recommendations || []).length ? `<section><h3>Recommendations</h3><ol>${o.recommendations.map((x) => `<li>${inlineChips(typeof x === "string" ? x : JSON.stringify(x))}</li>`).join("")}</ol></section>` : ""}
      <div class="aicheck ${bad ? "bad" : "ok"}">${bad ? `Checked against the data: ${fmt(ck.ids_found)} record ids found; <b>not found</b>: ${[...(ck.ids_missing || []), ...(ck.names_missing || [])].slice(0, 8).map(esc).join(", ")}. Remove or fix what rests on them.` : `Checked against the data: all ${fmt(ck.ids_found)} record ids found.`}</div>
      <div class="aibtns"><button type="button" class="primary" data-mdreport>Download as Markdown</button></div>
    </article>`;
  }
  function reportMarkdown(o) {
    const L = [`# ${o.title || "Incident report"}`, "", `_Draft by ${$("model").value} from Swarm Tracer's analysis of ${S.summary?.name || "the dataset"}, ${new Date().toISOString().slice(0, 10)}. Record ids are as in the dataset; ids marked (not found) were not in the data._`, ""];
    const ids = (it) => (it.ids || []).map((x) => (it._missing || []).includes(x) ? `\`${x}\` (not found)` : `\`${x}\``).join(", ");
    if (o.summary) L.push("## Summary", "", o.summary, "");
    if ((o.timeline || []).length) {
      L.push("## Timeline", "", "| Time (UTC) | What happened | Records |", "|---|---|---|");
      o.timeline.forEach((it) => L.push(`| ${it._data_time || it.time || "unknown"} | ${String(it.label || "").replace(/\|/g, "\\|")} | ${ids(it)} |`));
      L.push("");
    }
    (o.sections || []).forEach((sec) => { L.push(`## ${sec.heading || ""}`, ""); (sec.paragraphs || []).forEach((p) => L.push(p, "")); if ((sec.ids || []).length) L.push(`Records: ${ids(sec)}`, ""); });
    if ((o.unknowns || []).length) { L.push("## What the data cannot show", ""); o.unknowns.forEach((x) => L.push(`- ${typeof x === "string" ? x : JSON.stringify(x)}`)); L.push(""); }
    if ((o.recommendations || []).length) { L.push("## Recommendations", ""); o.recommendations.forEach((x, i) => L.push(`${i + 1}. ${typeof x === "string" ? x : JSON.stringify(x)}`)); L.push(""); }
    const ck = o._checks || {};
    L.push("---", "", `Checked against the data: ${ck.ids_found ?? 0} record ids found` + ((ck.ids_missing || []).length ? `; not found: ${ck.ids_missing.join(", ")}.` : "."));
    return L.join("\n");
  }
  async function draftReport() {
    if (!keyOk()) { $("aisettings").hidden = false; $("aiset").setAttribute("aria-expanded", "true"); $("aistatus").textContent = "Add an API key here first (a model on localhost needs none)."; $("aistatus").className = "small bad"; return; }
    if (!S.summary) { addMsg("error", "Load a dataset first."); return; }
    addMsg("user", "Draft the incident report.");
    const wait = addMsg("assistant", '<div class="aiwait"><i></i><i></i><i></i> Drafting the incident report from the brief, the warning signs and the measured gaps… this takes a minute or two.</div>');
    const btn = $("draftReport"); btn.disabled = true;
    try {
      const r = await askAI("Draft the incident report for this swarm in the report format.", { mode: "report" });
      wait.remove();
      const o = r.structured;
      if (!o || !(o.sections || o.timeline)) { addMsg("assistant", md(r.content), "The model did not return the report format; its answer is shown as text."); return; }
      const meta = `${esc($("model").value)}${r.usage?.total_tokens ? " · " + fmt(r.usage.total_tokens) + " tokens" : ""}`;
      const d = addMsg("assistant", renderReport(o) + `<button type="button" class="link rawtoggle small">raw answer</button><pre hidden>${esc(r.content)}</pre>`, meta);
      d.querySelector("[data-mdreport]").addEventListener("click", () => {
        const blob = new Blob([reportMarkdown(o)], { type: "text/markdown" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = String(o.title || "incident-report").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) + ".md";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      });
    } catch (e) { wait.remove(); addMsg("error", esc(e.message)); }
    finally { btn.disabled = false; }
  }
  window.renderAIReport = renderReport;
  window.aiReportMarkdown = reportMarkdown;
  (() => {
    const b = document.createElement("button");
    b.type = "button"; b.id = "draftReport"; b.textContent = "Draft incident report";
    b.title = "The model writes a full incident report (summary, timeline, sections, unknowns, recommendations) that you can download as Markdown";
    b.addEventListener("click", draftReport);
    $("quick").appendChild(b);
    const st = document.createElement("style");
    st.textContent = `.aireport{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;line-height:1.5;font-size:13px}
.aireport h2{margin:0 0 2px;font-size:16px}.aireport h3{margin:12px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#3d4a58}
.aireport p{margin:0 0 7px}.aireport ul,.aireport ol{margin:0 0 6px;padding-left:20px}
.aireport .airtl{list-style:none;padding:0;display:flex;flex-direction:column;gap:4px}.aireport .airtl li{display:grid;grid-template-columns:110px 1fr;gap:8px}
.aireport .airtl .tm{color:var(--muted);font-variant-numeric:tabular-nums}.aireport code.missing{color:#b42318;text-decoration:line-through}
.aireport .aibtns{margin-top:10px}`;
    document.head.appendChild(st);
  })();

  window.initAI = (d) => {
    const saved = JSON.parse(sessionStorage.getItem("st-ai") || "{}");
    $("baseUrl").value = saved.baseUrl || d.baseUrl;
    $("model").value = saved.model || d.model;
    if (saved.apiKey) { $("apiKey").value = saved.apiKey; $("remember").checked = true; }
    syncPreset();
    keyState();
  };
})();

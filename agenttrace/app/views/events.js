// Events: every record, filterable, with the filtered set drawn over time and broken down by kind,
// intent and actor. Click a row to inspect it (what it is, its role in the swarm, its components).
"use strict";
(() => {
  const PAGE = 100;
  function events(el, s) {
    const k = Object.keys(s.kinds), it = Object.keys(s.intents), tg = Object.keys(s.evidence_tags);
    const sel = (id, opts, v, name = (o) => o) => `<select id="${id}"><option value="">any</option>${opts.map((o) => `<option value="${esc(o)}"${o === v ? " selected" : ""}>${esc(name(o))}</option>`).join("")}</select>`;
    el.innerHTML = `
    <div class="evhead"><h2>Every event</h2><span id="evtotal" class="muted"></span></div>
    <div class="filters evfilters">
      <input id="fq" placeholder="Search ids and text" value="${esc(S.ev.q)}">
      <label>kind ${sel("fk", k, S.ev.kind)}</label>
      <label>does ${sel("fi", it, S.ev.intent, human)}</label>
      <label>tag ${sel("ft", tg, S.ev.tag, human)}</label>
      <label class="chk"><input type="checkbox" id="fc"${S.ev.channels ? " checked" : ""}> touches a place</label>
      <span id="evchips"></span>
    </div>
    <div class="grid2 evtop">
      ${card("When", '<div id="evhist"></div>', { sub: "Matching records per hour (UTC; most times are estimated). Click a bar to keep only that hour." })}
      ${card("What they are", '<div id="evfacets"></div>', { sub: "Click a part to filter." })}
    </div>
    <div id="evlist" class="muted">Loading…</div>`;
    const reload = () => { S.ev.offset = 0; loadEvents(); };
    let tmr; $("fq").addEventListener("input", (e) => { clearTimeout(tmr); tmr = setTimeout(() => { S.ev.q = e.target.value; reload(); }, 300); });
    $("fk").addEventListener("change", (e) => { S.ev.kind = e.target.value; reload(); });
    $("fi").addEventListener("change", (e) => { S.ev.intent = e.target.value; reload(); });
    $("ft").addEventListener("change", (e) => { S.ev.tag = e.target.value; reload(); });
    $("fc").addEventListener("change", (e) => { S.ev.channels = e.target.checked; reload(); });
    loadEvents();
  }

  function chips() {
    const box = $("evchips"); if (!box) return;
    const c = [];
    if (S.ev.actor) c.push(["actor", `actor ${ent.actor(S.ev.actor)}`]);
    if (S.ev.hour) c.push(["hour", `hour ${esc(when(toTime(S.ev.hour)))}`]);
    box.innerHTML = c.map(([k, h]) => `<span class="fchip">${h}<button class="link" data-clear="${k}" title="Remove">×</button></span>`).join("");
    box.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => { S.ev[b.dataset.clear] = ""; S.ev.offset = 0; loadEvents(); }));
  }

  async function loadEvents() {
    const host = $("evlist"); if (!host) return;
    chips();
    const p = new URLSearchParams({ q: S.ev.q || "", hour: S.ev.hour || "", kind: S.ev.kind, intent: S.ev.intent, tag: S.ev.tag, actor: S.ev.actor, channels: S.ev.channels ? "1" : "", offset: S.ev.offset, limit: PAGE });
    try {
      const r = await api("/api/events?" + p);
      if (!$("evlist")) return;
      $("evtotal").textContent = `${fmt(r.total)} matching · ${fmt(r.timed)} with a time`;
      hist($("evhist"), r.hist);
      facets($("evfacets"), r.facets, r.total);
      const rows = r.rows;
      host.className = "";
      host.innerHTML = rows.length ? `<div class="evrows">${rows.map((x, i) => `<div class="evrow" data-i="${i}">
          <div class="c1"><span class="tm" title="${esc(x.time ? x.time + " UTC" : "no time")}">${esc(x.time ? when(toTime(x.time)) : "no time")}</span>${ent.rec(x.id)}<span class="badge">${esc(x.kind)}</span></div>
          <div class="c2">${ent.actor(x.actor)} ${ent.intent(x.intent)} ${x.tags.slice(0, 3).map((t) => `<span class="chip" title="${esc(tagName(t))}">${esc(human(t))}</span>`).join("")}${x.tags.length > 3 ? `<span class="muted small">+${x.tags.length - 3}</span>` : ""}
            <span class="io">${x.in ? `<span class="in" title="messages in: read what another actor wrote">↘ ${x.in}</span>` : ""}${x.out ? `<span class="out" title="messages out: another actor read what this wrote">↗ ${x.out}</span>` : ""}${x.ops ? `<span class="ops" title="places touched">◧ ${x.ops}</span>` : ""}</span></div>
          <div class="c3 mono">${esc(x.preview.slice(0, 160))}</div></div>`).join("")}</div>` : '<p class="muted">No event matches these filters.</p>';
      host.insertAdjacentHTML("beforeend", `<p class="pager"><button id="pv"${r.offset === 0 ? " disabled" : ""}>Previous</button> <button id="nx"${r.offset + PAGE >= r.total ? " disabled" : ""}>Next</button> <span class="muted small">${fmt(r.total ? r.offset + 1 : 0)}–${fmt(Math.min(r.total, r.offset + PAGE))} of ${fmt(r.total)}</span></p>`);
      host.querySelectorAll(".evrow").forEach((row) => row.addEventListener("click", (e) => { if (e.target.closest(".ent")) return; selectEvent(rows[+row.dataset.i].id); host.querySelectorAll(".evrow.on").forEach((x) => x.classList.remove("on")); row.classList.add("on"); }));
      $("pv").onclick = () => { S.ev.offset = Math.max(0, S.ev.offset - PAGE); loadEvents(); };
      $("nx").onclick = () => { S.ev.offset += PAGE; loadEvents(); };
    } catch (e) { host.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
  }

  function hist(host, h) {
    if (!host) return;
    const sp = span();
    if (!h.length || !sp) { host.innerHTML = '<p class="muted small">None of the matching events has a time.</p>'; return; }
    const W = Math.max(260, host.clientWidth || 340), H = 110, x0 = 34, x1 = W - 6, yT = 6, yB = H - 20;
    const [t0, t1] = sp;
    const X = (t) => x0 + (t - t0) / (t1 - t0) * (x1 - x0);
    const mx = Math.max(...h.map((x) => x[1])), Y = (v) => yB - v / mx * (yB - yT);
    const bw = Math.max(1, (x1 - x0) / ((t1 - t0) / 3600e3) - 0.5);
    let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
    [0, mx].forEach((v) => { svg += `<text x="${x0 - 5}" y="${Y(v) + 3.5}" text-anchor="end" font-size="10" fill="${QUIET}">${fmt(v)}</text>`; });
    h.forEach(([k, v]) => { const t = toTime(k); svg += `<rect data-h="${esc(k)}" x="${X(t).toFixed(1)}" y="${Y(v).toFixed(1)}" width="${bw.toFixed(2)}" height="${(yB - Y(v)).toFixed(1)}" fill="${S.ev.hour === k ? HARM : ACCENT}" class="hbar"><title>${esc(when(t))}: ${fmt(v)}</title></rect>`; });
    svg += `<line x1="${x0}" x2="${x1}" y1="${yB}" y2="${yB}" stroke="${AXIS}"/>`;
    timeTicks(t0, t1, Math.max(2, Math.floor(W / 90))).forEach((k) => { svg += `<text x="${X(k.t)}" y="${H - 5}" text-anchor="middle" font-size="10" fill="${QUIET}">${esc(k.label)}</text>`; });
    host.innerHTML = svg + "</svg>";
    host.querySelectorAll("rect[data-h]").forEach((r) => r.addEventListener("click", () => { S.ev.hour = S.ev.hour === r.dataset.h ? "" : r.dataset.h; S.ev.offset = 0; loadEvents(); }));
  }

  function facets(host, f, total) {
    if (!host) return;
    const kc = ["#2f6fb3", "#6aa5dc", "#bcd3ec", "#9aa5b1"];
    const kinds = Object.entries(f.kind).map(([k, v], i) => ({ label: k, value: v, color: kc[i % kc.length] }));
    const withIntent = Object.values(f.intent).reduce((a, b) => a + b, 0);
    host.innerHTML = `<div class="small muted">${term("record", "kind of record")} <span class="faint">(click one to keep only that kind)</span></div>${stackbar(kinds, { h: 10 })}
      <div class="chips">${kinds.map((k) => `<button type="button" class="link small" data-fk="${esc(k.label)}">${esc(k.label)}${S.ev.kind === k.label ? " ✓" : ""}</button>`).join("")}</div>
      ${Object.keys(f.intent).length ? `<div class="small muted" style="margin-top:8px">what the code does (${term("intent")}; only ${term("action", "actions")} have one: ${fmt(withIntent)} of the ${fmt(total)})</div>${hbars(Object.entries(f.intent).map(([k, v]) => ({ label: `${esc(human(k))}${isHarm(k) ? ' <span class="harmtag">harm</span>' : ""}`, value: v, color: intentColor(k), attrs: `data-click data-fi="${esc(k)}"` })), { total: withIntent })}` : ""}
      <div class="small muted" style="margin-top:8px">busiest ${term("actor", "actors")} <span class="faint">("run R…" is an ${term("run", "anonymous run")}: a thread with no token or name, credited to its first record)</span></div><div class="chips">${f.actor.slice(0, 8).map(([a, n]) => `<span class="fa">${ent.actor(a, ` <span class="muted">${fmt(n)}</span>`)}<button type="button" class="link small" data-fa="${esc(a)}" title="Keep only this actor's events">filter</button></span>`).join("")}</div>`;
    host.querySelectorAll("[data-fk]").forEach((b) => b.addEventListener("click", () => { S.ev.kind = S.ev.kind === b.dataset.fk ? "" : b.dataset.fk; $("fk").value = S.ev.kind; S.ev.offset = 0; loadEvents(); }));
    host.querySelectorAll("[data-fi]").forEach((b) => b.addEventListener("click", () => { S.ev.intent = b.dataset.fi; $("fi").value = b.dataset.fi; S.ev.offset = 0; loadEvents(); }));
    host.querySelectorAll("[data-fa]").forEach((b) => b.addEventListener("click", () => { S.ev.actor = b.dataset.fa; S.ev.offset = 0; loadEvents(); }));
  }

  VIEWS.events = events;
})();

// Forensics tab: a shell of sections. Feature files register sections with
//   window.FX_SECTIONS.push({ id, title, group, blurb, render: async (host, summary) => {} })
// and the tab draws a side menu grouped by `group`. Deep link: #tab=forensics&fx=<id>.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const ORDER = ["Follow the evidence", "How agents behaved", "Test and export"];
  let current = null;
  async function forensics(el, s) {
    const secs = window.FX_SECTIONS;
    if (!secs.length) { el.innerHTML = '<p class="muted">No forensic sections are installed.</p>'; return; }
    // a link's fx= picks the first section shown; after that the menu decides
    const want = (typeof FX_WANT !== "undefined" && FX_WANT) || current || (typeof deepLink === "function" && deepLink().fx) || secs[0].id;
    if (typeof FX_WANT !== "undefined") FX_WANT = null;
    current = secs.some((x) => x.id === want) ? want : secs[0].id;
    const groups = [...new Set([...ORDER.filter((g) => secs.some((x) => x.group === g)), ...secs.map((x) => x.group || "More")])];
    el.innerHTML = `<div class="fxwrap"><nav class="fxnav">${groups.map((g) => `<div class="fxg">${esc(g)}</div>${secs.filter((x) => (x.group || "More") === g).map((x) => `<button type="button" data-fx="${esc(x.id)}" class="${x.id === current ? "on" : ""}" title="${esc(x.blurb || "")}">${esc(x.title)}</button>`).join("")}`).join("")}</nav><div class="fxbody" id="fxbody"></div></div>`;
    el.querySelectorAll("[data-fx]").forEach((b) => b.addEventListener("click", () => { current = b.dataset.fx; forensics(el, s); }));
    const sec = secs.find((x) => x.id === current), host = $("fxbody");
    host.innerHTML = `<h2>${esc(sec.title)}</h2>${sec.blurb ? `<p class="lead">${sec.blurb}</p>` : ""}<div id="fxsec"><p class="muted">Loading…</p></div>`;
    try { await sec.render($("fxsec"), s); } catch (e) { $("fxsec").innerHTML = `<p class="warn">${esc(e.message)}</p>`; console.error(e); }
  }
  VIEWS.forensics = forensics;
})();

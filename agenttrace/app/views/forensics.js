// Forensics tab: a shell of sections. Feature files register sections with
//   window.FX_SECTIONS.push({ id, title, group, blurb, render: async (host, summary) => {} })
// and the tab draws a side menu grouped by `group`. Deep link: #tab=forensics&fx=<id>.
"use strict";
window.FX_SECTIONS = window.FX_SECTIONS || [];
(() => {
  const ORDER = ["Follow the evidence", "How agents behaved", "Test and export"];
  let current = null, navWatch = null;
  async function forensics(el, s) {
    const secs = window.FX_SECTIONS;
    if (!secs.length) { el.innerHTML = '<p class="muted">No forensic sections are installed.</p>'; return; }
    // a link's fx= picks the first section shown; after that the menu decides
    const want = (typeof FX_WANT !== "undefined" && FX_WANT) || current || (typeof deepLink === "function" && deepLink().fx) || secs[0].id;
    if (typeof FX_WANT !== "undefined") FX_WANT = null;
    current = secs.some((x) => x.id === want) ? want : secs[0].id;
    const navTop = el.querySelector(".fxnav")?.scrollTop || 0;      // the menu keeps its own scroll position over a redraw
    const groups = [...new Set([...ORDER.filter((g) => secs.some((x) => x.group === g)), ...secs.map((x) => x.group || "More")])];
    el.innerHTML = `<div class="fxwrap"><nav class="fxnav">${groups.map((g) => `<div class="fxg">${esc(g)}</div>${secs.filter((x) => (x.group || "More") === g).map((x) => `<button type="button" data-fx="${esc(x.id)}" class="${x.id === current ? "on" : ""}" title="${esc(x.blurb || "")}">${esc(x.title)}</button>`).join("")}`).join("")}</nav><div class="fxbody" id="fxbody"></div></div>`;
    el.querySelectorAll("[data-fx]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.fx !== current) { try { history.pushState(null, "", "#tab=forensics&fx=" + encodeURIComponent(b.dataset.fx)); } catch { /* file: or sandboxed */ } }
      current = b.dataset.fx; forensics(el, s);
    }));
    // the menu is taller than a laptop window: it sticks to the top of the pane, so it scrolls by itself, or its lower entries
    // could only be reached by scrolling to the very end of a long section
    const nav = el.querySelector(".fxnav"), pane = $("left");
    const fitNav = () => { if (nav.isConnected && pane && getComputedStyle(nav).position === "sticky") nav.style.maxHeight = Math.max(160, pane.clientHeight - 28) + "px"; else if (nav.isConnected) nav.style.maxHeight = ""; };
    fitNav();
    nav.scrollTop = navTop;
    nav.querySelector("button.on")?.scrollIntoView({ block: "nearest" });
    if (pane && window.ResizeObserver) { navWatch?.disconnect(); navWatch = new ResizeObserver(fitNav); navWatch.observe(pane); }
    // the address names the section shown, so a reload or a copied link opens it again (a q= for another section goes)
    try {
      const p = new URLSearchParams(location.hash.replace(/^#/, ""));
      if (p.get("tab") === "forensics" && p.get("fx") !== current) { p.set("fx", current); p.delete("q"); history.replaceState(null, "", "#" + p.toString()); }
    } catch { /* file: or sandboxed */ }
    const sec = secs.find((x) => x.id === current), host = $("fxbody");
    host.innerHTML = `<h2>${esc(sec.title)}</h2>${sec.blurb ? `<p class="lead">${sec.blurb}</p>` : ""}<div id="fxsec"><p class="muted">Loading…</p></div>`;
    try { await sec.render($("fxsec"), s); } catch (e) { $("fxsec").innerHTML = `<p class="warn">${esc(e.message)}</p>`; console.error(e); }
  }
  VIEWS.forensics = forensics;
})();

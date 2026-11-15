// Swarm Tracer investigations: a marked claim opens its evidence beside the text (below it on a phone).
// Without this file the page still works: every claim is a link to its evidence, listed after the story.
"use strict";
(() => {
  const panel = document.getElementById("evidence");
  if (!panel) return;
  document.documentElement.classList.add("js");
  const claims = [...document.querySelectorAll("a.claim")];
  const sections = new Map([...panel.querySelectorAll(".ev")].map((s) => [s.dataset.claim, s]));
  const empty = document.getElementById("evempty"), close = document.getElementById("evclose"), count = document.getElementById("evcount");
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  let current = null;

  function show(id, { focus = false, quiet = false } = {}) {
    if (!sections.has(id)) return;
    current = id;
    sections.forEach((s, k) => s.classList.toggle("on", k === id));
    claims.forEach((a) => { const on = a.dataset.claim === id; a.classList.toggle("on", on); a.setAttribute("aria-expanded", on ? "true" : "false"); });
    empty.hidden = true; close.hidden = false;
    panel.classList.add("open"); document.body.classList.add("sheet");
    const n = [...sections.keys()].indexOf(id) + 1;
    count.textContent = `claim ${n} of ${sections.size}`;
    panel.scrollTop = 0;
    if (!quiet) history.replaceState(null, "", "#" + id);
    if (focus) sections.get(id).querySelector("h3").focus({ preventScroll: !narrow() });
  }
  function hide({ focus = true } = {}) {
    const was = current;
    current = null;
    sections.forEach((s) => s.classList.remove("on"));
    claims.forEach((a) => { a.classList.remove("on"); a.setAttribute("aria-expanded", "false"); });
    empty.hidden = false; close.hidden = true; count.textContent = "";
    panel.classList.remove("open"); document.body.classList.remove("sheet");
    history.replaceState(null, "", location.pathname + location.search);
    if (focus && was) { const a = claims.find((c) => c.dataset.claim === was); if (a) a.focus(); }
  }
  claims.forEach((a) => {
    a.setAttribute("role", "button");
    a.setAttribute("aria-expanded", "false");
    a.addEventListener("click", (e) => {
      e.preventDefault();
      // a keyboard press (detail 0) moves focus to the evidence; a pointer click leaves the reader in the text
      if (current === a.dataset.claim) { hide({ focus: false }); return; }
      show(a.dataset.claim, { focus: e.detail === 0 && !narrow() });
      if (narrow()) a.scrollIntoView({ block: "start" });      // keep the claim in view above the sheet
    });
    a.addEventListener("keydown", (e) => { if (e.key === " ") { e.preventDefault(); a.click(); } });
  });
  close.addEventListener("click", () => hide());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && current) hide(); });
  // a link to a claim (#c3, or #ev-c3 from a page read without scripts) opens it
  const fromHash = () => { const id = location.hash.replace(/^#(ev-)?/, ""); if (sections.has(id)) { show(id, { quiet: true }); const a = claims.find((c) => c.dataset.claim === id); if (a) a.scrollIntoView({ block: narrow() ? "start" : "center" }); return true; } return false; };
  window.addEventListener("hashchange", fromHash);
  if (!fromHash()) { if (narrow()) { empty.hidden = false; } else show(claims[0].dataset.claim, { quiet: true }); }
})();

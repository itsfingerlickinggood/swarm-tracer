// Units: the "Count by" switch in the top bar. The app counts estimated agents by default (tokens merged on
// direct evidence, as the Agents tab and What-if "estimate" do) and can count tokens instead. The state
// (S.unit), the mapping (S.units) and the helpers (agentOf, agentLabel, ent.agent, unitSign…) live in core.js;
// this file only draws the switch and keeps it in step with them.
"use strict";
(() => {
  const OPTS = [["agent", "Estimated agents"], ["token", "Tokens"]];
  function host() {
    let el = document.getElementById("unitsw");
    if (el) return el;
    const top = document.querySelector("header.top"), after = document.getElementById("ribbon");
    if (!top || !after) return null;
    el = document.createElement("div");
    el.id = "unitsw"; el.className = "unitsw";
    el.setAttribute("role", "group"); el.setAttribute("aria-label", "Count by estimated agents or by tokens");
    after.insertAdjacentElement("afterend", el);
    return el;
  }
  function draw() {
    const el = host();
    if (!el) return;
    const u = S.units, none = u && u.no_merges;
    const tip = !u ? UNIT_TIP : none ? `${UNIT_NONE}: both counts are the same` : `${UNIT_TIP}. ${fmt(u.tokens)} tokens → ${fmt(u.agents)} estimated agents (${fmt(u.merges)} merges)`;
    el.title = tip;
    el.innerHTML = `<span class="uswl">Count by</span><span class="uswb">${OPTS.map(([k, label]) => `<button type="button" data-setunit="${k}" class="${S.unit === k ? "on" : ""}" aria-pressed="${S.unit === k}">${label}</button>`).join("")}</span>${none ? `<span class="uswn">${esc(UNIT_NONE)}</span>` : ""}`;
  }
  // core.js fires "unitchange" when the unit is switched and when a dataset's mapping arrives
  document.addEventListener("unitchange", draw);
  draw();
})();

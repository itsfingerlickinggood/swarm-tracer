// Investigator decisions wherever a message or a warning sign is shown: Accept (counted, the default) or
// Reject (left out of the What-if recount). Posts to the What-if endpoint (agenttrace/fx_whatif.py:
// POST /api/x/fx_whatif_decide {kind: "message"|"sign", ids, action: "reject"|"restore"}); "Accept" is
// "restore". Message ids are "write_id>read_id"; sign ids are the replay's sign keys.
// Use: decCtl("message", id) or decCtl("sign", key) in any HTML; clicks are handled here by delegation.
(() => {
"use strict";
const D = { key: "", rejected: { message: new Set(), sign: new Set() }, loading: null, last: null };
const SHARED = "Decisions are saved on this server for this dataset and seen by everyone using it.";
const NOUN = { message: "message", sign: "warning sign" };

function ensure() {
  const k = datasetKey(S.summary);
  if (D.key !== k || !D.loading) {
    D.key = k;
    D.loading = api("/api/x/fx_whatif_decisions").then((d) => {
      D.rejected.message = new Set(d.messages.map((m) => m.id));
      D.rejected.sign = new Set(d.signs.map((g) => g.key));
      refresh(document);
    }).catch((e) => { D.loading = null; console.warn("decisions", e); });
  }
  return D.loading;
}
const isRejected = (kind, id) => D.rejected[kind]?.has(id);
function inner(kind, id) {
  const rej = isRejected(kind, id);
  return `<span class="decst">${rej ? "rejected by you" : "counted"}${D.last && D.last.id === id && D.last.kind === kind ? ` · recount: ${D.last.text}` : ""}</span>` +
    `<button type="button" data-dec-act="accept" aria-pressed="${!rej}" aria-label="Accept this ${NOUN[kind]}" title="Count this ${NOUN[kind]} (the default)">Accept</button>` +
    `<button type="button" data-dec-act="reject" aria-pressed="${!!rej}" aria-label="Reject this ${NOUN[kind]}" title="Leave this ${NOUN[kind]} out of the What-if recount">Reject</button>`;
}
function decCtl(kind, id) {
  if (!id || !S.summary) return "";
  ensure();
  return `<span class="dec${isRejected(kind, id) ? " rej" : ""}" role="group" aria-label="Your decision on this ${NOUN[kind]}" data-dec-kind="${kind}" data-dec-id="${esc(id)}">${inner(kind, id)}</span>`;
}
function refresh(root) {
  root.querySelectorAll?.(".dec[data-dec-id]").forEach((el) => {
    const { decKind: kind, decId: id } = el.dataset;
    const rej = isRejected(kind, id);
    if (el.classList.contains("rej") === !!rej && el.querySelector(".decst") && !(D.last && D.last.id === id && D.last.kind === kind)) return;
    const had = el.contains(document.activeElement) ? document.activeElement.dataset.decAct : null;
    el.classList.toggle("rej", !!rej);
    el.innerHTML = inner(kind, id);
    if (had) el.querySelector(`[data-dec-act="${had}"]`)?.focus();
  });
}
function investigator() { try { return localStorage.getItem("swarm-tracer-investigator") || ""; } catch { return ""; } }
// the recount the server returns with each decision: "107 → 106 messages" or, for a sign, which first sign remains
function consequence(w, kind, reject) {
  if (!w) return "";
  const a = w.as_counted || {}, b = w.after || {};
  if (kind === "message") return `${fmt(a.messages)} → ${fmt(b.messages)} messages`;
  const fj = w.first_joint?.after;
  return fj ? `first joint sign now ${fj.name} (${pct(fj.harm_share_after)} of harm still to come)` : `${plural(w.decisions?.signs_rejected || 0, "sign")} rejected`;
}
async function decide(kind, ids, reject) {
  const r = await api("/api/x/fx_whatif_decide", { method: "POST", body: JSON.stringify({ kind, ids, action: reject ? "reject" : "restore", by: investigator() }) });
  ids.forEach((i) => (reject ? D.rejected[kind].add(i) : D.rejected[kind].delete(i)));
  D.last = { kind, id: ids.length === 1 ? ids[0] : null, text: consequence(r.whatif, kind, reject) };
  refresh(document);
  document.dispatchEvent(new CustomEvent("st-decision", { detail: { kind, ids, reject, whatif: r.whatif } }));
  return r;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-dec-act]");
  if (!b) return;
  const box = b.closest(".dec");
  if (!box) return;
  e.stopPropagation();
  const reject = b.dataset.decAct === "reject", { decKind: kind, decId: id } = box.dataset;
  if (!!isRejected(kind, id) === reject) return;
  box.classList.add("busy");
  try {
    const r = await decide(kind, [id], reject);
    status(`${reject ? "Rejected" : "Accepted"} the ${NOUN[kind]} · recount: ${consequence(r.whatif, kind, reject)}. ${SHARED}`);
    setTimeout(() => status(""), 7000);
  } catch (err) { status(err.message, true); }
  finally { box.classList.remove("busy"); }
}, true);
window.decCtl = decCtl;
// after a reset or a decision made elsewhere (Forensics › What-if): fetch the decisions again
function reload() { D.loading = null; D.last = null; return ensure(); }
window.DECISIONS = { decide, isRejected, ensure, refresh, reload, SHARED, consequence };
})();

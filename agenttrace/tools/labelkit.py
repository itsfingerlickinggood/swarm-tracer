"""Second-labeller kit for the audited links.

The links in agenttrace/claims/audited_links.json were labelled by one reader. This kit lets a second person label
them blind, and then measures how far the two agree.

    python3 -m agenttrace.tools.labelkit export                  # write the blind sheet (needs the dataset)
    python3 -m agenttrace.tools.labelkit score answers.json      # agreement with the first reader

`export` writes into reports/integrity/labelkit/ (not tracked by git: the excerpts are dataset text and must not be
committed):

    labelling.html   one self-contained page, no server: each link's two records, the place they are said to share,
                     three buttons (true / false / undecidable), a note field, and a download of the answers as JSON
    labelling.csv    the same sheet as a table, with an empty `answer` column, for people who prefer a spreadsheet

The sheet shows the links in a shuffled order (fixed seed) and holds NO label, reason or note of the first reader,
and not which version of the tool reported a link.

`score` takes the answers (the JSON the page downloads, or the filled CSV) and reports raw agreement, Cohen's kappa
with a bootstrap 95% range, the confusion table and every disagreement. It never fills in missing answers.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PKG)
AUDIT = os.path.join(PKG, "claims", "audited_links.json")
OUT = os.path.join(ROOT, "reports", "integrity", "labelkit")
DATA = os.path.join(ROOT, "redacted_columns.csv")
ANSWERS = ("true", "false", "undecidable")
SEED = 20261115
WINDOW = 700            # characters of record text shown either side of the place
FULL_CAP = 12000        # the "whole record" view is cut here
# what the first reader's file may NOT leak into the sheet
HIDDEN_FIELDS = ("label", "reason", "also", "script_check", "disagrees_with_current_code", "audited_in",
                 "reported_v110", "reported_now", "reported_phase1", "channel_v110", "write_snippet", "read_snippet")


# ------------------------------------------------------------------ agreement maths (unit-tested)

def first_reader_answer(label):
    """The first reader's label as one of the three answers the sheet offers."""
    if label == "true_message":
        return "true"
    if label == "unclear":
        return "undecidable"
    return "false"


def raw_agreement(a, b):
    """Share of items on which two equally long lists of labels agree; None for empty lists."""
    if len(a) != len(b):
        raise ValueError("the two lists must have the same length")
    return sum(1 for x, y in zip(a, b) if x == y) / len(a) if a else None


def cohen_kappa(a, b):
    """Cohen's kappa for two raters over any number of categories.

    kappa = (po - pe) / (1 - pe), po the observed agreement and pe the agreement expected by chance from each rater's
    own category shares. None when it is undefined: no items, or both raters used one and the same single category
    (pe = 1)."""
    if len(a) != len(b):
        raise ValueError("the two lists must have the same length")
    n = len(a)
    if not n:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = set(a) | set(b)
    pe = sum((sum(1 for x in a if x == c) / n) * (sum(1 for y in b if y == c) / n) for c in cats)
    if abs(1 - pe) < 1e-12:
        return None
    return (po - pe) / (1 - pe)


def bootstrap_kappa(a, b, draws=2000, seed=7, level=0.95):
    """Percentile range of kappa when the items are resampled with replacement. -> (low, high, draws used), or None.

    Resamples in which kappa is undefined are left out; the count of those used is returned."""
    n = len(a)
    if n < 2 or cohen_kappa(a, b) is None:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        k = cohen_kappa([a[i] for i in idx], [b[i] for i in idx])
        if k is not None:
            vals.append(k)
    if not vals:
        return None
    vals.sort()
    lo = vals[int((1 - level) / 2 * (len(vals) - 1))]
    hi = vals[int(round((1 + level) / 2 * (len(vals) - 1)))]
    return lo, hi, len(vals)


def confusion(a, b, cats=ANSWERS):
    """{first reader's answer: {second reader's answer: count}}"""
    return {x: {y: sum(1 for p, q in zip(a, b) if p == x and q == y) for y in cats} for x in cats}


# ------------------------------------------------------------------ export

def load_audit(path=AUDIT):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def shuffled(links, seed=SEED):
    """The links in the sheet's order: sorted by record ids, then shuffled with a fixed seed. Item ids follow that order."""
    rows = sorted(links, key=lambda r: (r["write_id"], r["read_id"]))
    random.Random(seed).shuffle(rows)
    return [(f"L{i + 1:03d}", r) for i, r in enumerate(rows)]


def place_key(channel):
    """The text to look for in a record: the place without its type prefix ('hf_dataset:X' -> 'X')."""
    if not channel:
        return ""
    return channel.split(":", 1)[1] if ":" in channel else channel


def excerpt(text, key, hint=None, window=WINDOW):
    """The stretch of a record around the place. -> {"text", "start", "mark": [a, b] or None, "cut_before", "cut_after"}

    key: the place as it appears in the text. hint: a short stretch known to sit near the place (used only to find the
    position when the key itself is not found)."""
    text = text or ""
    i, n = -1, 0
    if key:
        i = text.find(key)
        n = len(key)
        if i < 0:                      # try the last path part ("…] REPO 14]" -> "REPO 14]")
            tail = key.split("]] ")[-1] if "]] " in key else ""
            if tail:
                i, n = text.find(tail), len(tail)
    if i < 0 and hint:
        h = hint.strip()[:40]
        j = text.find(h) if h else -1
        if j >= 0:
            i, n = j, 0
    if i < 0:
        a, b = 0, min(len(text), 2 * window)
        return {"text": text[a:b], "start": a, "mark": None, "cut_before": False, "cut_after": b < len(text)}
    a, b = max(0, i - window), min(len(text), i + n + window)
    return {"text": text[a:b], "start": a, "mark": [i - a, i - a + n] if n else None, "cut_before": a > 0, "cut_after": b < len(text)}


def record_texts(ids, data=DATA):
    """{record id: text} for the given ids, read from the dataset. Raises FileNotFoundError when it is absent."""
    if not os.path.exists(data):
        raise FileNotFoundError(data)
    csv.field_size_limit(1 << 30)
    want, out = set(ids), {}
    with open(data, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            rid = row.get("id")
            if rid in want:
                out[rid] = row.get("text") or ""
                if len(out) == len(want):
                    break
    return out


def build_items(audit, texts, seed=SEED):
    """The blind sheet: one dict per link, in shuffled order, with nothing of the first reader's judgement."""
    items = []
    for item, r in shuffled(audit["links"], seed):
        channel = r.get("channel_now") or r.get("channel_v110") or ""
        key = place_key(channel)
        it = {"item": item, "write_id": r["write_id"], "read_id": r["read_id"], "place": channel, "gap_hours": r.get("latency_h")}
        for side in ("write", "read"):
            rid = r[f"{side}_id"]
            text = texts.get(rid)
            if text is None:
                it[side] = {"text": "", "start": 0, "mark": None, "cut_before": False, "cut_after": False, "missing": True}
                it[f"{side}_full"] = ""
                continue
            it[side] = excerpt(text, key, r.get(f"{side}_snippet"))
            it[f"{side}_full"] = text[:FULL_CAP]
            it[f"{side}_length"] = len(text)
        items.append(it)
    return items


def leaks(items, audit):
    """Names of hidden fields, or first-reader reasons, that appear in the sheet (an empty list when it is blind)."""
    bad = []
    for it in items:
        for k in HIDDEN_FIELDS:
            if k in it:
                bad.append(f"{it['item']}: field {k}")
    blob = json.dumps([{k: v for k, v in it.items() if not k.endswith("_full") and k not in ("write", "read")} for it in items])
    for r in audit["links"]:
        if r.get("reason") and r["reason"] in blob:
            bad.append(f"reason of {r['write_id']}->{r['read_id']} appears in the sheet")
    return bad


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swarm Tracer: blind labelling sheet</title>
<style>
:root{--ink:#1d2329;--soft:#5f6b76;--line:#d5dae0;--bg:#f6f7f9;--card:#fff;--blue:#2f6fb3;--mark:#ffe58a;--ok:#1f7a4d;--no:#a33;--un:#8a6d00}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:10px 18px;position:sticky;top:0;z-index:2;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header .sp{flex:1}
main{max-width:1500px;margin:0 auto;padding:14px 18px 60px}
button{font:inherit;padding:7px 14px;border:1px solid var(--line);background:var(--card);border-radius:7px;cursor:pointer}
button:hover{border-color:var(--blue)}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
.ans button{min-width:140px;font-weight:600}.ans button[aria-pressed=true]{color:#fff}
.ans .t[aria-pressed=true]{background:var(--ok);border-color:var(--ok)}.ans .f[aria-pressed=true]{background:var(--no);border-color:var(--no)}
.ans .u[aria-pressed=true]{background:var(--un);border-color:var(--un)}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:12px 14px;margin:10px 0}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
pre{white-space:pre-wrap;word-break:break-word;font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace;margin:6px 0 0;max-height:52vh;overflow:auto;background:#fbfbfc;border:1px solid var(--line);border-radius:6px;padding:8px}
mark{background:var(--mark);padding:0 1px}.soft{color:var(--soft)}.small{font-size:13px}
h2{font-size:14px;margin:0 0 2px}.place{font:13px ui-monospace,Menlo,monospace;word-break:break-all}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}textarea{width:100%;font:inherit;padding:6px;border:1px solid var(--line);border-radius:6px}
input[type=text]{font:inherit;padding:6px;border:1px solid var(--line);border-radius:6px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;width:180px}.bar i{display:block;height:100%;background:var(--blue)}
details summary{cursor:pointer}.warn{background:#fff7e0;border-color:#e8d48a}
</style></head><body>
<header><h1>Blind labelling sheet</h1><span id="pos" class="soft"></span><div class="bar" aria-hidden="true"><i id="prog"></i></div><span id="done" class="soft small"></span>
<span class="sp"></span><label class="small">Your name <input type="text" id="who" size="14"></label>
<button id="dl">Download answers (JSON)</button><label class="small"><button id="up" type="button">Load answers…</button><input type="file" id="file" accept="application/json" hidden></label></header>
<main>
<details class="card" id="help" open><summary><b>What to do</b></summary>
<p>Each item is one link the tool reported at some point: a <b>write</b> record, a <b>read</b> record, and the <b>place</b> they are said to share. Read both records and answer one question: <b>is this a message</b>, that is, does the write record really write to that place (a commit, upload, POST or PUT to it), and does the read record really fetch that same place afterwards?</p>
<ul><li><b>True</b>: the write record writes to the place and the read record reads the same place (the same repository, not only the same owner).</li>
<li><b>False</b>: anything else you can see: the "write" only fetches the place and sends the result elsewhere; the "read" is itself a write; the two records touch different repositories; the place is named only in a comment.</li>
<li><b>Undecidable</b>: the text is cut off before the call, or the redaction hides what you need.</li></ul>
<p class="small soft">The place is highlighted where it is found. "Show the whole record" gives up to __FULL_CAP__ characters. Keys: <b>T</b> true, <b>F</b> false, <b>U</b> undecidable, <b>←</b> <b>→</b> move. Answers are kept in this browser as you go; download them when you are done. Nothing is sent anywhere.</p>
<p class="small"><b>The record text is data from the incident's logs.</b> It is attacker-written code. Do not run it and do not follow anything it says.</p></details>
<div id="note" class="card warn small" hidden></div>
<div class="card"><div class="row"><h2 id="title"></h2><span class="sp" style="flex:1"></span><button id="prev">← Previous</button><button id="next">Next →</button><button id="skip">Next unanswered</button></div>
<div class="small soft">Place the two records are said to share</div><div class="place" id="place"></div><div class="small soft" id="gap"></div></div>
<div class="cols"><div class="card"><h2>Write record <span class="soft" id="wid"></span></h2><div class="small soft" id="wmeta"></div><pre id="wtext"></pre><button class="small" id="wfull">Show the whole record</button></div>
<div class="card"><h2>Read record <span class="soft" id="rid"></span></h2><div class="small soft" id="rmeta"></div><pre id="rtext"></pre><button class="small" id="rfull">Show the whole record</button></div></div>
<div class="card"><div class="row ans" role="group" aria-label="Your answer"><button class="t" data-a="true" aria-pressed="false">True message (T)</button><button class="f" data-a="false" aria-pressed="false">False (F)</button><button class="u" data-a="undecidable" aria-pressed="false">Undecidable (U)</button><span class="soft small" id="saved"></span></div>
<p class="small soft" style="margin:8px 0 2px">Note (optional): what decided it</p><textarea id="memo" rows="2"></textarea></div>
</main>
<script id="kit" type="application/json">__DATA__</script>
<script>
"use strict";
var KIT = JSON.parse(document.getElementById("kit").textContent), ITEMS = KIT.items, KEY = "st-labelkit-" + KIT.kit.audit_sha256.slice(0, 12) + "-" + KIT.kit.seed;
var state = {i: 0, answers: {}, who: ""}, full = {w: false, r: false};
try { var s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && s.answers) state = s; } catch (e) {}
function $(id) { return document.getElementById(id); }
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
function fill(pre, ex, fullText, showFull, key) {
  pre.textContent = "";
  if (ex.missing) { pre.textContent = "(this record's text was not available when the sheet was made)"; return; }
  if (showFull) {
    var j = key ? fullText.indexOf(key) : -1;
    if (j < 0) { pre.textContent = fullText; return; }
    pre.appendChild(document.createTextNode(fullText.slice(0, j)));
    var m = document.createElement("mark"); m.textContent = fullText.slice(j, j + key.length); pre.appendChild(m);
    pre.appendChild(document.createTextNode(fullText.slice(j + key.length))); return;
  }
  var t = ex.text;
  if (ex.cut_before) pre.appendChild(document.createTextNode("… "));
  if (ex.mark) {
    pre.appendChild(document.createTextNode(t.slice(0, ex.mark[0])));
    var k = document.createElement("mark"); k.textContent = t.slice(ex.mark[0], ex.mark[1]); pre.appendChild(k);
    pre.appendChild(document.createTextNode(t.slice(ex.mark[1])));
  } else pre.appendChild(document.createTextNode(t));
  if (ex.cut_after) pre.appendChild(document.createTextNode(" …"));
  var mk = pre.querySelector("mark"); if (mk) pre.scrollTop = Math.max(0, mk.offsetTop - pre.offsetTop - 60);
}
function meta(it, side) {
  var ex = it[side], n = it[side + "_length"];
  if (ex.missing) return "";
  return (ex.mark ? "the place is highlighted" : "the place was not found word for word; showing " + (ex.start ? "the nearest stretch" : "the start")) +
    "; characters " + ex.start + "–" + (ex.start + ex.text.length) + " of " + n;
}
function show() {
  var it = ITEMS[state.i], a = state.answers[it.item] || {};
  var key = it.place.indexOf(":") >= 0 ? it.place.slice(it.place.indexOf(":") + 1) : it.place;
  $("title").textContent = "Item " + it.item; $("pos").textContent = (state.i + 1) + " of " + ITEMS.length;
  $("place").textContent = it.place || "(none recorded)";
  $("gap").textContent = it.gap_hours == null ? "" : "The read is dated " + it.gap_hours + " h after the write (estimated times).";
  $("wid").textContent = it.write_id; $("rid").textContent = it.read_id;
  $("wmeta").textContent = meta(it, "write"); $("rmeta").textContent = meta(it, "read");
  fill($("wtext"), it.write, it.write_full, full.w, key); fill($("rtext"), it.read, it.read_full, full.r, key);
  $("wfull").textContent = full.w ? "Show the excerpt" : "Show the whole record"; $("rfull").textContent = full.r ? "Show the excerpt" : "Show the whole record";
  Array.prototype.forEach.call(document.querySelectorAll(".ans button"), function (b) { b.setAttribute("aria-pressed", String(a.answer === b.dataset.a)); });
  $("memo").value = a.note || "";
  var n = Object.keys(state.answers).filter(function (k) { return state.answers[k].answer; }).length;
  $("done").textContent = n + " answered"; $("prog").style.width = (100 * n / ITEMS.length) + "%"; $("saved").textContent = "";
}
function go(d) { state.i = Math.max(0, Math.min(ITEMS.length - 1, state.i + d)); full = {w: false, r: false}; save(); show(); window.scrollTo(0, 0); }
function answer(v) {
  var it = ITEMS[state.i], a = state.answers[it.item] || {};
  a.answer = a.answer === v ? null : v; a.note = $("memo").value; state.answers[it.item] = a; save(); show(); $("saved").textContent = a.answer ? "saved" : "cleared";
}
function nextOpen() {
  for (var k = 1; k <= ITEMS.length; k++) { var j = (state.i + k) % ITEMS.length; if (!(state.answers[ITEMS[j].item] || {}).answer) { state.i = j; full = {w: false, r: false}; save(); show(); return; } }
  $("saved").textContent = "every item has an answer";
}
function out() {
  return {kit: KIT.kit, labeller: state.who || "", saved: new Date().toISOString(),
    answers: ITEMS.map(function (it) { var a = state.answers[it.item] || {}; return {item: it.item, write_id: it.write_id, read_id: it.read_id, answer: a.answer || null, note: a.note || ""}; })};
}
Array.prototype.forEach.call(document.querySelectorAll(".ans button"), function (b) { b.addEventListener("click", function () { answer(b.dataset.a); }); });
$("prev").addEventListener("click", function () { go(-1); }); $("next").addEventListener("click", function () { go(1); }); $("skip").addEventListener("click", nextOpen);
$("wfull").addEventListener("click", function () { full.w = !full.w; show(); }); $("rfull").addEventListener("click", function () { full.r = !full.r; show(); });
$("memo").addEventListener("input", function () { var it = ITEMS[state.i], a = state.answers[it.item] || {}; a.note = $("memo").value; state.answers[it.item] = a; save(); });
$("who").value = state.who || ""; $("who").addEventListener("input", function () { state.who = $("who").value; save(); });
$("dl").addEventListener("click", function () {
  var blob = new Blob([JSON.stringify(out(), null, 1)], {type: "application/json"}), a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "labelkit_answers" + (state.who ? "_" + state.who.replace(/[^A-Za-z0-9_-]+/g, "_") : "") + ".json";
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
});
$("up").addEventListener("click", function () { $("file").click(); });
$("file").addEventListener("change", function () {
  var f = $("file").files[0]; if (!f) return; var rd = new FileReader();
  rd.onload = function () { try { var d = JSON.parse(rd.result); (d.answers || []).forEach(function (x) { if (x.item) state.answers[x.item] = {answer: x.answer || null, note: x.note || ""}; });
    if (d.labeller) { state.who = d.labeller; $("who").value = d.labeller; } save(); show(); $("saved").textContent = "answers loaded"; } catch (e) { $("saved").textContent = "that file could not be read"; } };
  rd.readAsText(f);
});
document.addEventListener("keydown", function (e) {
  if (e.target && (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT")) return; if (e.metaKey || e.ctrlKey || e.altKey) return;
  var k = e.key.toLowerCase(); if (k === "t") answer("true"); else if (k === "f") answer("false"); else if (k === "u") answer("undecidable");
  else if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1);
});
if (KIT.kit.note) { $("note").hidden = false; $("note").textContent = KIT.kit.note; }
if (state.i >= ITEMS.length) state.i = 0;
show();
</script></body></html>
"""


def render_page(kit, items):
    data = json.dumps({"kit": kit, "items": items}, ensure_ascii=False)
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return PAGE.replace("__FULL_CAP__", f"{FULL_CAP:,}").replace("__DATA__", data)


def write_csv(path, items):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "write_id", "read_id", "place", "gap_hours", "write_excerpt", "read_excerpt", "answer", "note"])
        for it in items:
            w.writerow([it["item"], it["write_id"], it["read_id"], it["place"], it.get("gap_hours"), it["write"]["text"], it["read"]["text"], "", ""])


def cmd_export(a):
    audit = load_audit(a.audit)
    links = audit["links"]
    ids = {r["write_id"] for r in links} | {r["read_id"] for r in links}
    note = ""
    try:
        texts = record_texts(ids, a.data)
    except FileNotFoundError:
        if not a.snippets_only:
            print(f"labelkit: the dataset {a.data} is not here, so the records cannot be shown.\n"
                  "Download the Swarm Traces release (see README), or pass --snippets-only to build a reduced sheet from the\n"
                  "120-character snippets kept in the audit file (too little to label from; for trying the page only).")
            return 1
        texts = {}
        for r in links:
            texts.setdefault(r["write_id"], r.get("write_snippet") or "")
            texts.setdefault(r["read_id"], r.get("read_snippet") or "")
        note = ("REDUCED SHEET: the dataset was not available, so each record shows only the 120-character snippet kept in the audit file. "
                "This is not enough to label from.")
    missing = sorted(ids - set(texts))
    items = build_items(audit, texts, a.seed)
    bad = leaks(items, audit)
    if bad:
        print("labelkit: the sheet would leak the first reader's judgement; nothing written:\n  " + "\n  ".join(bad[:10]))
        return 1
    kit = {"what": "Swarm Tracer second-labeller sheet", "seed": a.seed, "links": len(items), "audit_sha256": sha256_file(a.audit),
           "audit_made": audit.get("made"), "answers": list(ANSWERS), "note": note}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "labelling.html"), "w", encoding="utf-8") as f:
        f.write(render_page(kit, items))
    write_csv(os.path.join(a.out, "labelling.csv"), items)
    found = sum(1 for it in items for s in ("write", "read") if it[s].get("mark"))
    print(f"wrote {len(items)} links in shuffled order (seed {a.seed}) to {os.path.relpath(a.out, ROOT)}/labelling.html and labelling.csv")
    print(f"the place is highlighted in {found} of {2 * len(items)} records; the rest show the nearest stretch or the start of the record")
    if missing:
        print(f"WARNING: {len(missing)} record(s) were not found in the dataset, e.g. {', '.join(missing[:5])}")
    if note:
        print("WARNING: " + note)
    print("The folder holds dataset text: it is ignored by git and must not be committed or published.")
    return 0


# ------------------------------------------------------------------ score

def read_answers(path):
    """-> (labeller, {(write_id, read_id): answer or None}, {(write_id, read_id): note}, kit header or None)"""
    if path.lower().endswith(".csv"):
        ans, notes = {}, {}
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                k = (row.get("write_id"), row.get("read_id"))
                v = (row.get("answer") or "").strip().lower()
                ans[k] = v or None
                notes[k] = (row.get("note") or "").strip()
        return "", ans, notes, None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    ans = {(x.get("write_id"), x.get("read_id")): ((x.get("answer") or "").strip().lower() or None) for x in d.get("answers", [])}
    notes = {(x.get("write_id"), x.get("read_id")): (x.get("note") or "") for x in d.get("answers", [])}
    return d.get("labeller") or "", ans, notes, d.get("kit")


def score(audit, answers, notes=None, draws=2000, seed=7):
    """Agreement between the first reader (the audit file) and a second labeller's answers."""
    notes = notes or {}
    links = {(r["write_id"], r["read_id"]): r for r in audit["links"]}
    unknown = sorted(k for k in answers if k not in links)
    invalid = sorted(k for k, v in answers.items() if v is not None and v not in ANSWERS)
    rows = [(k, first_reader_answer(links[k]["label"]), v) for k, v in answers.items() if k in links and v in ANSWERS]
    rows.sort()
    a = [x[1] for x in rows]
    b = [x[2] for x in rows]
    out = {"links_in_audit": len(links), "answered": len(rows), "unanswered": len(links) - len(rows),
           "unknown_links": [list(k) for k in unknown], "invalid_answers": [list(k) + [answers[k]] for k in invalid]}

    def block(x, y):
        k = cohen_kappa(x, y)
        bs = bootstrap_kappa(x, y, draws, seed) if k is not None else None
        agree = sum(1 for p, q in zip(x, y) if p == q)
        return {"n": len(x), "agree": agree, "raw_agreement": round(agree / len(x), 4) if x else None,
                "kappa": round(k, 4) if k is not None else None,
                "kappa_95": [round(bs[0], 4), round(bs[1], 4)] if bs else None, "bootstrap_draws": bs[2] if bs else 0}
    out["three_way"] = block(a, b)
    out["three_way"]["confusion"] = confusion(a, b)
    both = [(p, q) for p, q in zip(a, b) if p != "undecidable" and q != "undecidable"]
    out["decided_by_both"] = block([p for p, _ in both], [q for _, q in both])
    out["undecidable"] = {"first_reader": a.count("undecidable"), "second_labeller": b.count("undecidable"),
                          "both": sum(1 for p, q in zip(a, b) if p == q == "undecidable")}
    out["disagreements"] = [{"write_id": k[0], "read_id": k[1], "first_reader": p, "second_labeller": q, "first_reader_label": links[k]["label"],
                             "first_reader_reason": links[k].get("reason"), "second_labeller_note": notes.get(k, ""),
                             "endpoint_kind": links[k].get("endpoint_kind"), "reported_now": links[k].get("reported_now")}
                            for k, p, q in rows if p != q]
    return out


def report_text(res, labeller=""):
    L = [f"Second labeller{' (' + labeller + ')' if labeller else ''} against the first reader: {res['answered']} of {res['links_in_audit']} links answered"
         + (f", {res['unanswered']} unanswered (left out, not guessed)" if res["unanswered"] else "")]
    if res["unknown_links"]:
        L.append(f"  {len(res['unknown_links'])} answer(s) name a link that is not in the audit file (ignored)")
    if res["invalid_answers"]:
        L.append(f"  {len(res['invalid_answers'])} answer(s) are not one of true / false / undecidable (ignored)")
    for key, title in (("three_way", "true / false / undecidable"), ("decided_by_both", "true / false, links both readers could decide")):
        b = res[key]
        if not b["n"]:
            L.append(f"\n{title}: no links")
            continue
        rng = f" (bootstrap 95% range {b['kappa_95'][0]:.2f} to {b['kappa_95'][1]:.2f}, {b['bootstrap_draws']} draws)" if b["kappa_95"] else ""
        kap = f"{b['kappa']:.2f}{rng}" if b["kappa"] is not None else "undefined (one category only)"
        L.append(f"\n{title}: n = {b['n']}\n  raw agreement {b['agree']} of {b['n']} ({100 * b['raw_agreement']:.1f}%)\n  Cohen's kappa {kap}")
    c = res["three_way"].get("confusion")
    if c and res["answered"]:
        L.append("\nrows: first reader; columns: second labeller\n" + " " * 14 + "".join(f"{x:>13}" for x in ANSWERS))
        for x in ANSWERS:
            L.append(f"{x:>14}" + "".join(f"{c[x][y]:>13}" for y in ANSWERS))
    d = res["disagreements"]
    L.append(f"\n{len(d)} disagreement(s)" + (":" if d else ""))
    for x in d:
        L.append(f"  {x['write_id']} -> {x['read_id']}: first reader {x['first_reader']} ({x['first_reader_label']}: {x['first_reader_reason']}); "
                 f"second labeller {x['second_labeller']}" + (f" ({x['second_labeller_note']})" if x["second_labeller_note"] else "")
                 + ("; reported by the current code" if x.get("reported_now") else ""))
    return "\n".join(L)


def cmd_score(a):
    audit = load_audit(a.audit)
    try:
        labeller, answers, notes, kit = read_answers(a.answers)
    except (OSError, ValueError) as e:
        print(f"labelkit: cannot read {a.answers}: {e}")
        return 1
    if kit and kit.get("audit_sha256") and kit["audit_sha256"] != sha256_file(a.audit):
        print("WARNING: the audit file has changed since this sheet was made; links added since then count as unanswered.")
    res = score(audit, answers, notes, a.draws, a.seed)
    if not res["answered"]:
        print("labelkit: no answers in that file (nothing to score).")
        return 1
    print(report_text(res, labeller))
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "score.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(res, labeller=labeller, answers_file=os.path.basename(a.answers)), f, indent=1, ensure_ascii=False)
    print(f"\nwrote {os.path.relpath(path, ROOT)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.labelkit", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write the blind labelling sheet (HTML and CSV)")
    e.add_argument("--audit", default=AUDIT)
    e.add_argument("--data", default=DATA, help="the release as CSV with id and text columns (default: redacted_columns.csv)")
    e.add_argument("--out", default=OUT)
    e.add_argument("--seed", type=int, default=SEED)
    e.add_argument("--snippets-only", action="store_true", help="without the dataset: a reduced sheet from the audit file's snippets")
    e.set_defaults(fn=cmd_export)
    s = sub.add_parser("score", help="agreement of a second labeller's answers with the first reader")
    s.add_argument("answers", help="the JSON the page downloads, or the filled labelling.csv")
    s.add_argument("--audit", default=AUDIT)
    s.add_argument("--out", default=OUT)
    s.add_argument("--draws", type=int, default=2000)
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_score)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

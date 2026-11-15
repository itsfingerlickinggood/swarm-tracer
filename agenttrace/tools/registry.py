"""Dataset registry: validate agenttrace/claims/datasets.json and build docs/datasets.html from it.

    python3 -m agenttrace.tools.registry                 # validate, then write docs/datasets.html
    python3 -m agenttrace.tools.registry --check         # validate; fail if docs/datasets.html is out of date
    python3 -m agenttrace.tools.registry --shots DIR     # also screenshot the page at 390 to 1680 px and
                                                         # report anything wider than the window (needs Chrome)

The registry records, for each dataset, where it comes from, its reuse terms, which reader handles it and what the
tool can and cannot conclude on it. The page is static: no scripts, one stylesheet (docs/datasets.css).
"""
import argparse
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(ROOT, "agenttrace", "claims", "datasets.json")
PAGE = os.path.join(ROOT, "docs", "datasets.html")

BADGES = ("open", "excerpts only", "ask first", "unknown")
STATUSES = ("analysed", "loadable", "candidate")
PUBLISH = ("raw", "excerpts", "aggregates", "nothing")
ALLOWED = ("yes", "no", "unclear")
FIELD_KEYS = ("actor_ids", "timestamps", "message_bodies", "tool_calls", "recipients")
FIELD_VALUES = ("yes", "no", "partial", "unclear")
REQUIRED = ("id", "title", "status", "kind", "publisher", "source_url", "contains", "size", "format", "fields",
            "reader", "terms", "publish", "publish_note", "citation", "contact", "confidence", "can", "cannot", "links")
NO_LICENCE = "no stated licence — ask the authors"
QUOTE_WORDS = 14          # quotes stay under 15 words
WIDTHS = (390, 768, 1024, 1280, 1680)

FIELD_LABELS = {"actor_ids": "actor ids", "timestamps": "timestamps", "message_bodies": "message text",
                "tool_calls": "tool calls", "recipients": "recipients"}
PUBLISH_LABELS = {"raw": "Raw records, excerpts and numbers", "excerpts": "Short excerpts and numbers",
                  "aggregates": "Numbers and charts only", "nothing": "Nothing until permission"}


def load(path=REGISTRY):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_url(u, local_ok=False):
    if isinstance(u, str) and u.startswith("https://"):
        return True
    return bool(local_ok and isinstance(u, str) and u.endswith(".html") and "/" not in u and ":" not in u)


def validate(reg):
    """Every problem found, as a list of strings; empty when the registry is sound."""
    errs = []
    entries = reg.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["registry has no entries"]
    if not reg.get("checked_on"):
        errs.append("registry: checked_on is missing")
    seen = set()
    for e in entries:
        eid = e.get("id") or "?"
        def bad(msg):
            errs.append(f"{eid}: {msg}")
        for k in REQUIRED:
            if e.get(k) in (None, "", [], {}):
                bad(f"'{k}' is missing or empty")
        if eid in seen:
            bad("duplicate id")
        seen.add(eid)
        if e.get("status") not in STATUSES:
            bad(f"status must be one of {STATUSES}")
        if e.get("publish") not in PUBLISH:
            bad(f"publish must be one of {PUBLISH}")
        for k in ("source_url", "data_url"):
            if e.get(k) and not _is_url(e[k]):
                bad(f"{k} must be an https URL")
        t = e.get("terms") or {}
        if t.get("badge") not in BADGES:
            bad(f"terms.badge must be one of {BADGES}")
        for k in ("raw", "excerpts", "aggregates"):
            if t.get(k) not in ALLOWED:
                bad(f"terms.{k} must be one of {ALLOWED}")
        if not t.get("licence"):
            bad("terms.licence is missing")
        if t.get("quote"):
            if len(t["quote"].split()) > QUOTE_WORDS:
                bad(f"terms.quote is longer than {QUOTE_WORDS} words")
            if not _is_url(t.get("quote_url")):
                bad("terms.quote needs an https quote_url")
        # the badge must not promise more than the terms say
        if t.get("badge") == "open" and (t.get("licence", "").startswith("no stated") or t.get("excerpts") != "yes"):
            bad("badge 'open' needs a stated licence and excerpts allowed")
        if t.get("licence") == NO_LICENCE and t.get("badge") not in ("ask first", "unknown"):
            bad("no stated licence must carry the badge 'ask first' or 'unknown'")
        if t.get("licence", "").startswith("no stated") and t.get("licence") != NO_LICENCE:
            bad(f"write a missing licence exactly as: {NO_LICENCE}")
        # what the site publishes must stay inside the terms
        if e.get("publish") == "raw" and t.get("raw") != "yes":
            bad("publish is 'raw' but terms.raw is not 'yes'")
        if e.get("publish") in ("raw", "excerpts") and t.get("excerpts") != "yes":
            bad("publish allows excerpts but terms.excerpts is not 'yes'")
        f = e.get("fields") or {}
        for k in FIELD_KEYS:
            if f.get(k) not in FIELD_VALUES:
                bad(f"fields.{k} must be one of {FIELD_VALUES}")
        r = e.get("reader") or {}
        if not r.get("name") or not isinstance(r.get("tested"), bool):
            bad("reader needs a name and tested true/false")
        loc = e.get("local")
        if e.get("status") in ("analysed", "loadable"):
            if not isinstance(loc, dict) or not isinstance(loc.get("records"), int) or not isinstance(loc.get("actors"), int):
                bad("an analysed or loadable dataset needs local.records and local.actors (integers)")
            elif not loc.get("loaded_via"):
                bad("local.loaded_via must say how the counts were obtained")
            if not r.get("tested"):
                bad("an analysed or loadable dataset must have reader.tested true")
        elif loc:
            bad("a candidate must not have local counts")
        elif r.get("tested"):
            bad("a candidate cannot have reader.tested true")
        for k in ("can", "cannot"):
            v = e.get(k) or []
            if not (3 <= len(v) <= 5):
                bad(f"'{k}' needs 3 to 5 lines (has {len(v)})")
            for line in v:
                if len(line) > 140:
                    bad(f"'{k}' line too long ({len(line)} chars): {line[:40]}…")
        for ln in e.get("links") or []:
            if not ln.get("label") or not _is_url(ln.get("url"), local_ok=True):
                bad(f"bad link: {ln}")
    return errs


# ------------------------------------------------------------------ the page

def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def _n(v):
    return f"{v:,}" if isinstance(v, int) else esc(v)


def _slug(s):
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def _card(e):
    t, r, loc = e["terms"], e["reader"], e.get("local")
    badge = t["badge"]
    facts = [("Publisher", esc(e["publisher"])),
             ("Released", esc(e.get("released") or "not stated")),
             ("Size", esc(e["size"])),
             ("Format", esc(e["format"])),
             ("Reader", esc(r["name"]) + (f" · pack <code>{esc(r['pack'])}</code>" if str(r.get("pack") or "").endswith(".json") else f" · pack: {esc(r['pack'])}" if r.get("pack") else "")
              + ("" if r["tested"] else " · <em>not tested</em>"))]
    if loc:
        facts.append(("Loaded here", f"{_n(loc['records'])} records, {_n(loc['actors'])} actors"
                      + (f", {_n(loc['messages'])} messages" if loc.get("messages") is not None else "")
                      + (f". {esc(loc['actors_note'])}." if loc.get("actors_note") else "")))
    else:
        facts.append(("Loaded here", "No. We do not hold this data."))
    chips = "".join(f"<li class='f-{esc(e['fields'][k])}'><b>{esc(FIELD_LABELS[k])}</b> {esc(e['fields'][k])}</li>" for k in FIELD_KEYS)
    quote = ""
    if t.get("quote"):
        quote = (f"<p class='quote'>The source says: <q>{esc(t['quote'])}</q> "
                 f"<a href='{esc(t['quote_url'])}'>source</a></p>")
    notes = "".join(f"<li>{esc(x)}</li>" for x in t.get("notes") or [])
    allowed = "".join(f"<li class='a-{esc(t[k])}'><b>{lab}</b> {esc(t[k])}</li>"
                      for k, lab in (("raw", "raw records"), ("excerpts", "short excerpts"), ("aggregates", "numbers")))
    links = " · ".join(f"<a href='{esc(ln['url'])}'>{esc(ln['label'])}</a>" for ln in e["links"])
    adapter = ""
    if e.get("adapter"):
        a = e["adapter"]
        adapter = ("<details><summary>What loading it would take</summary>"
                   f"<p>{esc(a['summary'])}</p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in a.get("mapping") or []) + "</ul>"
                   + ("<p class='small'>Open questions:</p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in a["open_questions"]) + "</ul>"
                      if a.get("open_questions") else "") + "</details>")
    return f"""<article class="ds" id="{esc(e['id'])}">
  <header>
    <div class="pills"><span class="pill s-{esc(e['status'])}">{esc(e['status'])}</span><span class="pill t-{_slug(badge)}">terms: {esc(badge)}</span><span class="kind">{esc(e['kind'])}</span></div>
    <h3>{esc(e['title'])}</h3>
    <p class="what">{esc(e['contains'])}</p>
  </header>
  <dl class="facts">{''.join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in facts)}</dl>
  <ul class="chips" aria-label="What each record carries">{chips}</ul>
  <div class="cc">
    <div class="can"><h4>The tool can</h4><ul>{''.join(f'<li>{esc(x)}</li>' for x in e['can'])}</ul></div>
    <div class="cannot"><h4>The tool cannot</h4><ul>{''.join(f'<li>{esc(x)}</li>' for x in e['cannot'])}</ul></div>
  </div>
  <div class="terms">
    <h4>Reuse terms</h4>
    <p><b>{esc(t['licence'])}</b></p>
    {quote}
    <ul class="chips allowed" aria-label="What may be republished">{allowed}</ul>
    <ul class="notes">{notes}</ul>
    <p class="publish"><b>On this site:</b> {esc(PUBLISH_LABELS[e['publish']])}. {esc(e['publish_note'])}</p>
    <p class="small"><b>Cite as:</b> {esc(e['citation'])}</p>
    <p class="small"><b>Contact:</b> {esc(e['contact'])} · <b>How sure we are:</b> {esc(e['confidence'])}</p>
  </div>
  {adapter}
  <p class="links">{links}</p>
</article>"""


BRAND = ('<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><g fill="none" stroke="#7fb3e6" stroke-width="1.3">'
         '<path d="M5 7L13 4L21 8L19 17L11 21L5 15Z" opacity=".55"/><path d="M13 4L11 21M5 7L19 17M21 8L5 15" opacity=".35"/></g>'
         '<g fill="#fff"><circle cx="5" cy="7" r="2"/><circle cx="13" cy="4" r="2"/><circle cx="21" cy="8" r="2"/>'
         '<circle cx="19" cy="17" r="2"/><circle cx="11" cy="21" r="2"/><circle cx="5" cy="15" r="2"/></g>'
         '<circle cx="13" cy="12.5" r="2.6" fill="#e3a43b"/></svg>')


def render(reg):
    entries = reg["entries"]
    groups = [(s, [e for e in entries if e["status"] == s]) for s in STATUSES]
    counts = {b: sum(1 for e in entries if e["terms"]["badge"] == b) for b in BADGES}
    toc = "".join(f"<li><a href='#{esc(e['id'])}'>{esc(e['title'])}</a> <span class='pill t-{_slug(e['terms']['badge'])}'>{esc(e['terms']['badge'])}</span></li>"
                  for e in entries)
    legend = "".join(f"<li><span class='pill t-{_slug(b)}'>{esc(b)}</span> {esc(reg['badges'][b])} <span class='muted'>({counts[b]})</span></li>" for b in BADGES)
    heads = {"analysed": "Analysed", "loadable": "Loadable", "candidate": "Candidates"}
    sections = []
    for i, (s, es) in enumerate(groups):
        if not es:
            continue
        cls = " class='alt'" if i % 2 == 0 else ""
        sections.append(f"<section{cls}><div class='wrap'><h2>{heads[s]}</h2>"
                        f"<p class='lead'>{esc(reg['statuses'][s])}</p>" + "\n".join(_card(e) for e in es) + "</div></section>")
    skipped = "".join(f"<li><a href='{esc(x['url'])}'>{esc(x['name'])}</a>. {esc(x['why'])}</li>" for x in reg.get("not_listed") or [])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Datasets: Swarm Tracer</title>
<meta name="description" content="Datasets of multi-agent incidents that Swarm Tracer has analysed or could load, with each one's reuse terms and what the tool can and cannot conclude on it.">
<link rel="stylesheet" href="datasets.css">
</head>
<body>
<!-- Built by python3 -m agenttrace.tools.registry from agenttrace/claims/datasets.json. Edit the registry, not this file. -->
<header class="hero">
  <div class="wrap">
    <nav>
      <a class="brand" href="./">{BRAND}Swarm Tracer</a>
      <a href="getting-started.html">Get started</a>
      <a href="formats.html">Formats</a>
      <a href="validation.html">Accuracy</a>
      <a href="dataset-licensing.html">Licensing notes</a>
      <a href="https://github.com/itsfingerlickinggood/swarm-tracer">GitHub</a>
    </nav>
    <h1>Datasets</h1>
    <p class="sub">Logs of real and simulated agent swarms. For each one: where it comes from, what its publisher lets others do with it, and what Swarm Tracer can and cannot conclude from it.</p>
    <p class="sub small">{len(entries)} datasets. Terms were read on {esc(reg['checked_on'])}. We host none of this data. This page is our reading of public pages, not legal advice.</p>
  </div>
</header>
<section>
  <div class="wrap two">
    <div><h2>Terms at a glance</h2><ul class="legend">{legend}</ul></div>
    <div><h2>On this page</h2><ul class="toc">{toc}</ul></div>
  </div>
</section>
{''.join(sections)}
<section>
  <div class="wrap">
    <h2>Looked at, not listed</h2>
    <ul class="notes">{skipped}</ul>
    <p class="note">Know a dataset that belongs here, or see a mistake in how we read your terms? Open an issue on <a href="https://github.com/itsfingerlickinggood/swarm-tracer/issues">GitHub</a>.</p>
  </div>
</section>
<footer>
  <div class="wrap">Swarm Tracer. Open source on <a href="https://github.com/itsfingerlickinggood/swarm-tracer">GitHub</a>. No dataset is redistributed here; every card links to its publisher. See the <a href="dataset-licensing.html">licensing notes</a>.</div>
</footer>
</body>
</html>
"""


def screenshot(page, out_dir, widths=WIDTHS):
    """Screenshot the page at each width; return [(width, overflow_px, path)]."""
    import base64
    from .smoke import Browser
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for w in widths:
        br = Browser(width=w, height=900)
        try:
            br.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": w < 600})
            br.navigate("file://" + os.path.abspath(page))
            br.settle(quiet=0.4, timeout=20)
            over = br.eval("""(() => { let worst = document.documentElement.scrollWidth - window.innerWidth, who = '';
              for (const c of document.querySelectorAll('body *')) { const r = c.getBoundingClientRect();
                if (r.width && r.right > window.innerWidth + 1 && r.right - window.innerWidth > worst) { worst = Math.round(r.right - window.innerWidth); who = c.tagName + '.' + c.className; } }
              return JSON.stringify([worst, who, document.documentElement.scrollHeight]); })()""")
            worst, who, height = json.loads(over)
            br.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": min(height, 12000), "deviceScaleFactor": 1, "mobile": w < 600})
            shot = br.call("Page.captureScreenshot", {"format": "png"})
            path = os.path.join(out_dir, f"datasets_{w}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            out.append((w, worst, who, path))
        finally:
            br.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate the dataset registry and build docs/datasets.html.")
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--out", default=PAGE)
    ap.add_argument("--check", action="store_true", help="validate and fail if the page is out of date; write nothing")
    ap.add_argument("--shots", help="folder for screenshots at 390 to 1680 px (needs Chrome)")
    a = ap.parse_args(argv)
    reg = load(a.registry)
    errs = validate(reg)
    for e in errs:
        print("registry:", e, file=sys.stderr)
    if errs:
        return 1
    page = render(reg)
    if a.check:
        old = open(a.out, encoding="utf-8").read() if os.path.exists(a.out) else None
        if old != page:
            print(f"registry: {a.out} is out of date; run python3 -m agenttrace.tools.registry", file=sys.stderr)
            return 1
        print(f"registry: {len(reg['entries'])} entries valid; page up to date")
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"registry: {len(reg['entries'])} entries valid; wrote {a.out}")
    if a.shots:
        bad = 0
        for w, worst, who, path in screenshot(a.out, a.shots):
            print(f"  {w:>5}px  overflow {worst:>4}px {who}  {path}")
            bad += worst > 1
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

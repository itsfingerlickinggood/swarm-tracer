"""Build the investigations gallery (docs/investigations/) from the stories and the dataset.

    python3 -m agenttrace.tools.build_investigations --api http://localhost:8010          # a running Swarm Tracer
    python3 -m agenttrace.tools.build_investigations --input redacted_columns.csv --pack code_traces.json
    python3 -m agenttrace.tools.build_investigations --api URL --check                     # rebuild and compare
    python3 -m agenttrace.tools.build_investigations --from-bundles                        # pages only, no dataset

A story (docs/investigations/stories/<slug>.json) is written by hand: paragraphs, claims, and for each claim the
records, figures and insider findings that back it. It holds no number: every number in the text is a
placeholder ({deliveries}, {rec:R0005421.time}) that this script fills from the dataset through the app's API.

For each story the script writes
  docs/investigations/data/<slug>.json    the evidence bundle: the figures (value, where it came from) and ONLY
                                          the cited records' fields
  docs/investigations/<slug>/index.html   the page: the story, each claim a link that opens its evidence
and docs/investigations/index.html, the gallery.

--snippets off (the default) publishes ids and metadata only: record id, kind, time and whether it is estimated,
token and estimated agent, what the tool judged (write or read of which place, the message and its grade), and
a link to the publisher's viewer for the text. --snippets on adds at most 160 characters of each record's text.
The Swarm Traces release states no licence, so the committed bundles are built with snippets off.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.parse

from . import smoke

ROOT = smoke.ROOT
OUT = os.path.join(ROOT, "docs", "investigations")
SNIPPET_MAX = 160
MAX_RECORDS = 40
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CITATION = {
    "authors": "Forman, Kharlov, Tom et al.",
    "title": "Revealing the details of how OpenAI agents hacked Hugging Face",
    "site": "swarmtraces.org", "url": "https://swarmtraces.org/", "date": "25 Sep 2026",
    "viewer": "https://swarmtraces.org/viewer/#/row/{id}",
}
CITATION_TEXT = (f'{CITATION["authors"]}, "{CITATION["title"]}", {CITATION["site"]}, {CITATION["date"]}')
REPO = "https://github.com/itsfingerlickinggood/swarm-tracer"
PLACE_TYPES = {"hf_dataset": "Hugging Face dataset", "board": "board folder", "webhook": "webhook",
               "command_file": "command file", "page": "wiki page"}
GRADES = {"direct": "the write and the read are both in the call that names the place",
          "inferred": "the write or read was found through a variable, a helper or nearby text",
          "weak": "no verb found, a merged place, or an estimated time that is too coarse"}
RECORD_FIELDS = ("id", "kind", "time", "time_estimated", "time_source", "actor", "actor_kind", "agent", "intent",
                 "text_length", "judged", "messages", "viewer")


# ---------------------------------------------------------------------- small formatters (the app's own wording)

def short(a):
    """cred 169 for [CREDENTIAL 169], run R0005427 for run:R0005427 (core.js short())."""
    return re.sub(r"^run:", "run ", re.sub(r"\[CREDENTIAL (\d+)\]", r"cred \1", str(a or "")))


def place_label(ch):
    """core.js placeLabel(): 'hf dataset · HF REPO 646'."""
    typ, _, name = str(ch).partition(":")
    name = re.sub(r"\]\s*\[", "] + [", name)
    name = re.sub(r"\[REDACTED:query_value:0*(\d+)\]", r"URL value \1", name)
    name = re.sub(r"\[REDACTED:([a-z_]+):0*(\d+)\]", lambda m: f"{m.group(1).replace('_', ' ')} {m.group(2)}", name)
    name = re.sub(r"\[([A-Z][A-Z ]+?) (\d+)\]", r"\1 \2", name)
    name = re.sub(r"\[([A-Z][A-Z ]+)\]", r"\1", name)
    return f"{PLACE_TYPES.get(typ, typ.replace('_', ' '))} {name}"


def fmt_time(s):
    """'2026-07-10 11:51' -> 'Jul 10 11:51'."""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)", str(s or ""))
    return f"{MONTHS[int(m.group(2)) - 1]} {int(m.group(3))} {m.group(4)}:{m.group(5)}" if m else str(s or "–")


def fmt_value(v, how):
    if v is None:
        return "–"
    if how == "int":
        return f"{int(v):,}"
    if how == "pct":
        return f"{int(float(v) * 100 + 0.5)}%"
    if how == "time":
        return fmt_time(v)
    if how == "day":
        return fmt_time(v).rsplit(" ", 1)[0]
    if how == "h1":
        return f"{abs(float(v)):.1f}"
    if how == "token":
        return short(v)
    if how == "place":
        return place_label(v)
    return str(v)


# ---------------------------------------------------------------------- reading values out of API replies

def split_path(path):
    """'signs[key=a.b: c].after.time' -> ['signs', ('key', 'a.b: c'), 'after', 'time']."""
    out, i, buf = [], 0, ""
    while i < len(path):
        c = path[i]
        if c == "[":
            j = path.index("]", i)
            if buf:
                out.append(buf)
                buf = ""
            k, _, v = path[i + 1:j].partition("=")
            out.append((k, v))
            i = j + 1
            continue
        if c == ".":
            if buf:
                out.append(buf)
                buf = ""
        else:
            buf += c
        i += 1
    if buf:
        out.append(buf)
    return out


def dig(obj, path):
    """Follow a path through dicts and lists; [k=v] picks the first list item whose k is v; '#' is a list's length."""
    for seg in split_path(path):
        if isinstance(seg, tuple):
            k, v = seg
            hits = [x for x in obj if isinstance(x, dict) and str(x.get(k)) == v]
            if not hits:
                raise KeyError(f"no item with {k}={v}")
            obj = hits[0]
        elif seg == "#":
            obj = len(obj)
        elif isinstance(obj, list):
            obj = obj[int(seg)]
        else:
            obj = obj[seg]
    return obj


class Api:
    """GET against a running Swarm Tracer, each path once."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            code, data, _ = smoke.http(self.base, path, timeout=600)
            if code != 200 or not isinstance(data, (dict, list)):
                raise SystemExit(f"GET {path} on {self.base} failed: {code} {str(data)[:200]}")
            self.cache[path] = data
        return self.cache[path]


# ---------------------------------------------------------------------- the bundle

def resolve_figures(story, api):
    out = {}
    for key, spec in story.get("figures", {}).items():
        src = api.get(spec["from"])
        try:
            v = dig(src, spec["path"])
            if spec.get("over"):
                v = v / dig(src, spec["over"])
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as e:
            raise SystemExit(f"{story['slug']}: figure {key}: {spec['from']} has no {spec['path']} ({e})")
        out[key] = {"value": v, "text": fmt_value(v, spec.get("as", "text")), "as": spec.get("as", "text"), "from": spec["from"],
                    "path": spec["path"] + (" / " + spec["over"] if spec.get("over") else ""), "label": spec.get("label", "")}
    return out


def cited_records(story):
    ids = []
    for c in story["claims"].values():
        for r in c.get("records", []):
            rid = r["id"] if isinstance(r, dict) else r
            if rid not in ids:
                ids.append(rid)
    return ids


def mask_hosts(text):
    """Host names in a snippet are masked, except the public service the incident is about."""
    keep = ("huggingface.co",)
    return re.sub(r"\b(?:[a-z0-9-]+\.)+(?:org|com|net|io|dev|internal|local|cloud|ai)\b",
                  lambda m: m.group(0) if m.group(0).lower() in keep else "[HOST]", text, flags=re.I)


def snippet_of(trace):
    """At most SNIPPET_MAX characters of the record's text, around the first place it names."""
    text = trace.get("text") or ""
    spans = [w for w in trace.get("why") or [] if w.get("type") == "place"]
    start = max(0, spans[0]["s"] - 30) if spans else 0
    raw = mask_hosts(" ".join(text[start:start + 400].split()))
    cut = raw[:SNIPPET_MAX - 2]
    return ("…" if start else "") + cut[:SNIPPET_MAX - 2].rstrip() + ("…" if start + len(cut) < len(text) else "")


def record_entry(rid, api, snippets):
    t = api.get("/api/event?lite=1&id=" + urllib.parse.quote(rid))
    units = api.get("/api/x/units_map")
    msgs = api.get("/api/messages")
    col = {c: i for i, c in enumerate(msgs["columns"])}
    agent = None
    g = (units.get("of") or {}).get(t.get("actor"))
    if g:
        info = next((x for x in units.get("agent_list", []) if x["id"] == g), None)
        if info:
            agent = {"id": info["id"], "name": info["name"], "tokens": len(info["tokens"]), "confidence": info.get("confidence")}
    judged = []
    labels = {w.get("key"): w.get("op") for w in t.get("why") or [] if w.get("type") == "place"}
    for op in t.get("channel_ops") or []:
        judged.append({"op": op["op"], "place": op["channel"], "place_label": place_label(op["channel"]),
                       "in_text": op["channel"] in labels})
    messages = []
    for row in msgs["rows"]:
        if rid not in (row[col["write_id"]], row[col["read_id"]]):
            continue
        messages.append({"role": "write" if row[col["write_id"]] == rid else "read",
                         "from": row[col["from"]], "to": row[col["to"]], "place": row[col["channel"]],
                         "place_label": place_label(row[col["channel"]]),
                         "write_id": row[col["write_id"]], "read_id": row[col["read_id"]],
                         "wait_h": row[col["latency_h"]], "grade": row[col["grade"]] if "grade" in col else None,
                         "estimated": bool(row[col["estimated"]]) if "estimated" in col else None,
                         "merged_place": bool(row[col["merged"]]) if "merged" in col else None})
    rec = {"id": t["id"], "kind": t.get("kind"), "time": t.get("time"), "time_estimated": t.get("time_source") == "estimated",
           "time_source": t.get("time_source"), "actor": t.get("actor"), "actor_kind": t.get("actor_kind"), "agent": agent,
           "intent": t.get("intent"), "text_length": t.get("text_length"), "judged": judged, "messages": messages,
           "viewer": CITATION["viewer"].format(id=t["id"])}
    if snippets:
        rec["snippet"] = snippet_of(t)
    return rec


def build_bundle(story, api, snippets, version):
    ids = cited_records(story)
    if len(ids) > MAX_RECORDS:
        raise SystemExit(f"{story['slug']}: cites {len(ids)} records; the limit is {MAX_RECORDS}")
    state = api.get("/api/state")["summary"]
    units = api.get("/api/x/units_map")
    findings = {}
    want = [f for c in story["claims"].values() for f in c.get("findings", [])]
    if want:
        allf = {f["id"]: f for f in api.get("/api/x/insiders")["findings"]}
        for fid in want:
            if fid not in allf:
                raise SystemExit(f"{story['slug']}: no insider finding {fid}")
            f = allf[fid]
            findings[fid] = {"id": fid, "group": f["group"], "source": f["source"], "finding": f["finding"],
                             "status": f["status"], "why": f["why"]}
    return {
        "schema": 1, "story": story["slug"], "snippets": "on" if snippets else "off",
        "citation": dict(CITATION, text=CITATION_TEXT),
        "produced_by": {"tool": "Swarm Tracer", "version": version, "pack": state.get("pack"),
                        "agent_rule": units.get("rule"), "agent_rule_note": units.get("note"),
                        "dataset": state.get("name"), "records": state.get("records")},
        "figures": resolve_figures(story, api),
        "records": {rid: record_entry(rid, api, snippets) for rid in ids},
        "findings": findings,
    }


# ---------------------------------------------------------------------- the page

E = html.escape
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+|rec:R\d+\.[a-z_]+)\}")
LOGO = ('<svg width="24" height="24" viewBox="0 0 26 26" aria-hidden="true"><g fill="none" stroke="#7fb3e6" stroke-width="1.3">'
        '<path d="M5 7L13 4L21 8L19 17L11 21L5 15Z" opacity=".55"/><path d="M13 4L11 21M5 7L19 17M21 8L5 15" opacity=".35"/></g>'
        '<g fill="#fff"><circle cx="5" cy="7" r="2"/><circle cx="13" cy="4" r="2"/><circle cx="21" cy="8" r="2"/>'
        '<circle cx="19" cy="17" r="2"/><circle cx="11" cy="21" r="2"/><circle cx="5" cy="15" r="2"/></g>'
        '<circle cx="13" cy="12.5" r="2.6" fill="#e3a43b"/></svg>')


def value_text(key, bundle):
    """The text a placeholder stands for: a figure, or one field of a cited record."""
    if key.startswith("rec:"):
        rid, field = key[4:].split(".", 1)
        r = bundle["records"].get(rid)
        if r is None:
            raise SystemExit(f"{bundle['story']}: {{{key}}} names a record the story does not cite")
        if field == "time":
            return fmt_time(r["time"])
        if field == "actor":
            return short(r["actor"])
        if field == "id":
            return r["id"]
        raise SystemExit(f"{bundle['story']}: {{{key}}}: only .time, .actor and .id can be quoted")
    if key not in bundle["figures"]:
        raise SystemExit(f"{bundle['story']}: {{{key}}} is not a figure of this story")
    return bundle["figures"][key]["text"]


def fill(text, bundle):
    """Escape the text and swap each {placeholder} for its value in a <span data-v> the site check can read."""
    out, pos = "", 0
    for m in PLACEHOLDER.finditer(text):
        out += E(text[pos:m.start()]) + f'<span class="v" data-v="{E(m.group(1))}">{E(value_text(m.group(1), bundle))}</span>'
        pos = m.end()
    return out + E(text[pos:])


def render_inline(text, story, bundle, order):
    """Paragraph text: [[c1|words]] becomes the link that opens claim c1's evidence."""
    out, pos = "", 0
    for m in re.finditer(r"\[\[([a-z0-9]+)\|(.+?)\]\]", text):
        cid = m.group(1)
        if cid not in story["claims"]:
            raise SystemExit(f"{story['slug']}: the text links claim {cid}, which is not defined")
        if cid not in order:
            order.append(cid)
        n = order.index(cid) + 1
        out += fill(text[pos:m.start()], bundle)
        out += (f'<a class="claim" href="#ev-{cid}" data-claim="{cid}" aria-controls="ev-{cid}"><span class="sr">Evidence {n}: </span>{fill(m.group(2), bundle)}'
                f'<sup aria-hidden="true">{n}</sup></a>')
        pos = m.end()
    return out + fill(text[pos:], bundle)


def record_card(rid, note, bundle):
    r = bundle["records"][rid]
    who = E(short(r["actor"]))
    kind = {"token": "identity token", "run": "anonymous run: no token, no name", "handle": "self-chosen name",
            "token_via_thread": "token, from its thread"}.get(r.get("actor_kind"), r.get("actor_kind") or "")
    agent = ""
    if r.get("agent"):
        a = r["agent"]
        agent = f' · counted as <b>{E(a["name"])}</b> <span class="badge">estimated</span> ({a["tokens"]} tokens, {E(str(a.get("confidence") or ""))} confidence)'
    rows = [("Time", f'{E(fmt_time(r["time"]))} UTC' + (' <span class="badge est" title="Dated from unix timestamps the agents wrote into their code, not from a time field">estimated</span>'
                                                         if r["time_estimated"] else "") if r.get("time") else "no time"),
            ("Who", f'<b>{who}</b> <span class="quiet">({E(kind)})</span>{agent}')]
    judged = []
    # the places its messages go through first; a record that touches many places lists three
    inmsg = {m["place"] for m in r["messages"]}
    ops = sorted(r["judged"], key=lambda j: j["place"] not in inmsg)
    for j in ops[:3]:
        judged.append(f'<li><span class="op {E(j["op"])}">{E(j["op"])}</span> of {E(j["place_label"])}</li>')
    if len(ops) > 3:
        judged.append(f'<li class="quiet">and {len(ops) - 3} more places in the same record</li>')
    # the messages whose other end the story also cites first; a write read by many lists three
    other_of = lambda m: m["read_id"] if m["role"] == "write" else m["write_id"]
    msgs = sorted(r["messages"], key=lambda m: other_of(m) not in bundle["records"])
    for m in msgs[:3]:
        other = other_of(m)
        way = f'to {E(short(m["to"]))}, who read it in' if m["role"] == "write" else f'from {E(short(m["from"]))}, who wrote it in'
        grade = f' Grade <b class="grade {E(str(m["grade"]))}" title="{E(GRADES.get(m["grade"], ""))}">{E(str(m["grade"]))}</b>.' if m.get("grade") else ""
        wait = f' Wait {m["wait_h"]} h{" (estimated times)" if m.get("estimated") else ""}.' if m.get("wait_h") is not None else ""
        merged = " The place may merge several repositories." if m.get("merged_place") else ""
        judged.append(f'<li><span class="op msg">message</span> {way} <code>{E(other)}</code>.{wait}{grade}{merged}</li>')
    if len(msgs) > 3:
        judged.append(f'<li class="quiet">and {len(msgs) - 3} more messages through this record</li>')
    if not judged:
        judged.append('<li class="quiet">The tool found no write or read of a shared place in this record.</li>')
    rows.append(("Tool's judgement", f'<ul class="judged">{"".join(judged)}</ul>'))
    if r.get("intent") and r["intent"] != "other":
        rows.append(("Intent pattern", E(r["intent"].replace("_", " "))))
    body = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    if "snippet" in r:
        text = f'<blockquote class="snip"><code>{E(r["snippet"])}</code><footer>Excerpt of {int(r["text_length"]):,} characters, from the redacted release</footer></blockquote>'
    else:
        text = (f'<p class="nosnip">Text not reproduced here ({int(r["text_length"] or 0):,} characters). '
                f'<a href="{E(r["viewer"])}" rel="noopener">Read record {E(rid)} in the publisher\'s viewer</a>.</p>')
    return (f'<article class="rec" data-rid="{E(rid)}"><header><code class="rid">{E(rid)}</code><span class="kind">{E(r.get("kind") or "record")}</span></header>'
            + (f'<p class="role">{fill(note, bundle)}</p>' if note else "") + f'<dl>{body}</dl>{text}</article>')


def figure_item(key, bundle):
    f = bundle["figures"][key]
    cls = "v long" if len(f["text"]) > 24 else "v"
    return (f'<li><b class="{cls}" data-v="{E(key)}">{E(f["text"])}</b> <span>{E(f.get("label") or key.replace("_", " "))}</span>'
            f'<small>GET {E(f["from"])} → <code>{E(f["path"])}</code></small></li>')


def finding_card(fid, bundle):
    f = bundle["findings"][fid]
    return (f'<article class="finding"><header><span class="kind">insider finding</span><span class="status {E(f["status"])}">{E(f["status"])} in the release</span></header>'
            f'<p class="said">{E(f["finding"])} <span class="quiet">({E(f["source"])})</span></p><p>{E(f["why"])}</p></article>')


def evidence_section(cid, n, story, bundle):
    c = story["claims"][cid]
    parts = [f'<h3 id="evh-{cid}" tabindex="-1"><span class="num">{n}</span> {fill(c["evidence"], bundle)}</h3>']
    if c.get("figures"):
        parts.append(f'<ul class="figs">{"".join(figure_item(k, bundle) for k in c["figures"])}</ul>')
    for fid in c.get("findings", []):
        parts.append(finding_card(fid, bundle))
    for r in c.get("records", []):
        rid, note = (r["id"], r.get("note", "")) if isinstance(r, dict) else (r, "")
        parts.append(record_card(rid, note, bundle))
    for d in c.get("docs", []):
        parts.append(f'<p class="doc">More: <a href="{E(d["href"])}">{E(d["label"])}</a></p>')
    if c.get("caveat"):
        parts.append(f'<p class="caveat">{fill(c["caveat"], bundle)}</p>')
    return f'<section class="ev" id="ev-{cid}" data-claim="{cid}" aria-labelledby="evh-{cid}">{"".join(parts)}</section>'


def site_header(up, here):
    nav = [("Home", up, ""), ("Demo", up + "demo/", "demo"), ("Investigations", up + "investigations/", "inv"),
           ("Datasets", up + "datasets.html", ""), ("GitHub", REPO, "")]
    cur = ' aria-current="page"'
    links = "".join(f'<a href="{E(h)}"{cur if k == here else ""}>{E(t)}</a>' for t, h, k in nav)
    return (f'<a class="skip" href="#main">Skip to the content</a><header class="site"><div class="bar">'
            f'<a class="brand" href="{E(up)}">{LOGO}<span>Swarm Tracer</span></a><nav aria-label="Site">{links}</nav></div></header>')


def produced_line(bundle):
    p = bundle["produced_by"]
    return (f'Numbers: Swarm Tracer {E(str(p["version"]))}, pack "{E(str(p["pack"]))}", agents counted by the '
            f'"{E(str(p["agent_rule"]))}" rule (tokens merged on direct evidence), on {E(str(p["dataset"]))} '
            f'({int(p["records"]):,} records). Times marked estimated are dated from timestamps in the agents\' code.')


def page_head(title, desc, css):
    return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{E(title)}</title>\n'
            f'<meta name="description" content="{E(desc)}">\n<link rel="stylesheet" href="{css}">\n</head>\n')


def plain(text):
    """Story text with the markup taken out (for descriptions and word counts)."""
    return re.sub(r"\[\[[a-z0-9]+\|(.+?)\]\]", r"\1", text)


def story_words(story, bundle):
    txt = " ".join(plain(b.get("p") or b.get("note") or b.get("h") or "") for b in story["body"])
    txt = PLACEHOLDER.sub(lambda m: value_text(m.group(1), bundle), txt)
    return len(txt.split())


def render_story(story, bundle, stories):
    order, blocks = [], []
    for b in story["body"]:
        if "h" in b:
            blocks.append(f'<h2>{fill(b["h"], bundle)}</h2>')
        elif "note" in b:
            blocks.append(f'<p class="aside">{render_inline(b["note"], story, bundle, order)}</p>')
        else:
            blocks.append(f'<p>{render_inline(b["p"], story, bundle, order)}</p>')
    unused = [c for c in story["claims"] if c not in order]
    if unused:
        raise SystemExit(f"{story['slug']}: claims never linked from the text: {', '.join(unused)}")
    i = [s["slug"] for s in stories].index(story["slug"])
    prev, nxt = stories[i - 1] if i else None, stories[i + 1] if i + 1 < len(stories) else None
    nav = ('<nav class="pager" aria-label="Investigations">'
           + (f'<a rel="prev" href="../{E(prev["slug"])}/"><span>Previous</span>{E(prev["title"])}</a>' if prev else "<span></span>")
           + (f'<a rel="next" href="../{E(nxt["slug"])}/"><span>Next</span>{E(nxt["title"])}</a>' if nxt else "<span></span>") + "</nav>")
    nrec = len(bundle["records"])
    mode = ("Short excerpts of the records are shown." if bundle["snippets"] == "on"
            else "Record text is not reproduced: each record links to the publisher's viewer.")
    ev = "".join(evidence_section(cid, n + 1, story, bundle) for n, cid in enumerate(order))
    return (page_head(f'{story["title"]} · Swarm Tracer investigations', fill_plain(story["dek"], bundle), "../story.css")
            + f'<body class="story" data-story="{E(story["slug"])}" data-snippets="{bundle["snippets"]}">\n{site_header("../../", "inv")}\n'
            f'<main id="main" class="layout">\n<article class="text">\n'
            f'<p class="kicker"><a href="../">Investigations</a> · {i + 1} of {len(stories)} · Swarm Traces incident, July 2026</p>\n'
            f'<h1>{E(story["title"])}</h1>\n<p class="dek">{fill(story["dek"], bundle)}</p>\n'
            f'<p class="meta">{len(order)} claims · {nrec} records cited · {story_words(story, bundle)} words. '
            f'<span class="hint">Select a marked claim to see the evidence behind it.</span></p>\n'
            + "\n".join(blocks) +
            f'\n<footer class="source">\n<h2>Source and method</h2>\n'
            f'<p><b>Data.</b> {E(CITATION["authors"])}, "<a href="{CITATION["url"]}" rel="noopener">{E(CITATION["title"])}</a>", '
            f'{E(CITATION["site"])}, {E(CITATION["date"])}. {mode} The release states no licence; see <a href="../../datasets.html">Datasets</a>.</p>\n'
            f'<p class="produced">{produced_line(bundle)}</p>\n'
            f'<p><a href="../data/{E(story["slug"])}.json">Evidence bundle (JSON)</a> · <a href="../stories/{E(story["slug"])}.json">Story source (JSON)</a> · '
            f'<a href="../../validation.html">How accurate is the tool?</a> · <a href="../../limitations.html">Limits</a></p>\n{nav}\n</footer>\n</article>\n'
            f'<aside id="evidence" class="evidence" aria-label="Evidence">\n<div class="evbar"><b>Evidence</b><span id="evcount" class="quiet"></span>'
            f'<button type="button" id="evclose" hidden>Close</button></div>\n'
            f'<p class="evempty" id="evempty" hidden>Select a marked claim in the text. Its records, numbers and what the tool judged open here.</p>\n'
            f'<div id="evlist" class="evlist">{ev}</div>\n</aside>\n</main>\n<script src="../story.js"></script>\n</body>\n</html>\n')


def fill_plain(text, bundle):
    return PLACEHOLDER.sub(lambda m: value_text(m.group(1), bundle), plain(text))


def render_index(stories, bundles):
    cards = []
    for n, s in enumerate(stories, 1):
        b = bundles[s["slug"]]
        cards.append(f'<li class="case"><a href="{E(s["slug"])}/"><span class="n" aria-hidden="true">{n}</span>'
                     f'<h2>{E(s["title"])}</h2><p>{fill(s["dek"], b)}</p>'
                     f'<span class="foot">{len(s["claims"])} claims · {len(b["records"])} records cited<b>Read the investigation →</b></span></a></li>')
    b0 = bundles[stories[0]["slug"]]
    mode = ("Each page shows short excerpts of the cited records." if b0["snippets"] == "on" else
            "The pages publish record ids, times, tokens and what the tool judged. They do not reproduce record text: each record links to the publisher's own viewer.")
    return (page_head("Investigations · Swarm Tracer", "Written investigations of the Swarm Traces incident. Every claim opens the records behind it.", "story.css")
            + f'<body class="gallery">\n{site_header("../", "inv")}\n<main id="main" class="wrap">\n'
            f'<p class="kicker">Investigations</p>\n<h1>What the records show, claim by claim</h1>\n'
            f'<p class="dek">Three short investigations of the Swarm Traces incident, written with Swarm Tracer. Every claim is a link. '
            f'It opens the records behind it: the record id, the time and whether it is estimated, the token and agent, and what the tool judged.</p>\n'
            f'<ol class="cases">{"".join(cards)}</ol>\n'
            f'<section class="about">\n<h2>How these are made</h2>\n'
            f'<p>Each story is a small JSON file with no numbers in it. A build script fills every number and record from the dataset, '
            f'and writes an evidence bundle that holds only the cited records. A check fails the site if a claim has no record, '
            f'if a number on a page differs from the bundle, or if anything that looks like a secret is published.</p>\n'
            f'<p>{mode}</p>\n'
            f'<p><b>Data.</b> {E(CITATION["authors"])}, "<a href="{CITATION["url"]}" rel="noopener">{E(CITATION["title"])}</a>", {E(CITATION["site"])}, {E(CITATION["date"])}. '
            f'The release states no licence; see <a href="../datasets.html">Datasets</a> for what we publish and why.</p>\n'
            f'<p class="produced">{produced_line(b0)}</p>\n'
            f'<p><a class="btn" href="../demo/">Try the tool on a simulated swarm</a> <a class="btn ghost" href="../getting-started.html">Install it and run your own</a></p>\n'
            f'</section>\n</main>\n</body>\n</html>\n')


# ---------------------------------------------------------------------- build

def load_stories(out=OUT):
    d = os.path.join(out, "stories")
    stories = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                s = json.load(fh)
            if s["slug"] + ".json" != f:
                raise SystemExit(f"{f}: its slug is {s['slug']!r}; the file name must match")
            stories.append(s)
    return sorted(stories, key=lambda s: s.get("order", 99))


def outputs(stories, bundles):
    """{relative path: text} of everything this script writes."""
    files = {"index.html": render_index(stories, bundles)}
    for s in stories:
        files[f"data/{s['slug']}.json"] = json.dumps(bundles[s["slug"]], ensure_ascii=False, indent=1) + "\n"
        files[f"{s['slug']}/index.html"] = render_story(s, bundles[s["slug"]], stories)
    return files


def build(api=None, snippets=False, out=OUT, check=False, from_bundles=False, log=print):
    from .export_static import tool_version
    stories = load_stories(out)
    bundles = {}
    for s in stories:
        if from_bundles:
            with open(os.path.join(out, "data", s["slug"] + ".json"), encoding="utf-8") as f:
                bundles[s["slug"]] = json.load(f)
        else:
            bundles[s["slug"]] = build_bundle(s, api, snippets, tool_version())
    files = outputs(stories, bundles)
    changed = []
    for rel, text in files.items():
        p = os.path.join(out, rel)
        old = None
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                old = f.read()
        if old != text:
            changed.append(rel)
            if not check:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
    for s in stories:
        b = bundles[s["slug"]]
        log(f"  {s['slug']}: {len(s['claims'])} claims, {len(b['records'])} records, {len(b['figures'])} figures, "
            f"{story_words(s, b)} words, snippets {b['snippets']}")
    log(("would change: " if check else "wrote: ") + (", ".join(changed) or "nothing (up to date)"))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", help="a running Swarm Tracer with the dataset loaded (e.g. http://localhost:8010)")
    ap.add_argument("--input", help="or: the dataset to load in this process")
    ap.add_argument("--pack", default="auto")
    ap.add_argument("--snippets", choices=("on", "off"), default="off", help="off (default): ids and metadata only")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if a rebuild would change a file")
    ap.add_argument("--from-bundles", action="store_true", help="render the pages from the bundles on disk (no dataset)")
    a = ap.parse_args(argv)
    httpd = None
    try:
        if a.from_bundles:
            api = None
        elif a.api:
            api = Api(a.api)
        elif a.input:
            from .export_static import start_server
            httpd, base, _ = start_server(a.input, a.pack, os.path.basename(a.input))
            api = Api(base)
        else:
            ap.error("give --api URL, --input FILE or --from-bundles")
        changed = build(api, a.snippets == "on", a.out, a.check, a.from_bundles)
    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
    return 1 if (a.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())

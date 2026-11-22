"""Build the investigations gallery (docs/investigations/) from the stories, the datasets and the saved measurements.

    python3 -m agenttrace.tools.build_investigations                       # every story, from what is on this machine
    python3 -m agenttrace.tools.build_investigations --check               # write nothing; exit 1 if a file would change
    python3 -m agenttrace.tools.build_investigations --from-bundles        # pages only: no dataset is read
    python3 -m agenttrace.tools.build_investigations --keep swarm_traces   # leave that dataset's bundles as they are
    python3 -m agenttrace.tools.build_investigations --api http://localhost:8010   # Swarm Traces from a running tool

A story (docs/investigations/stories/<slug>.json) is written by hand: paragraphs, claims, and for each claim the
records, figures and insider findings that back it. It holds no number: every number in the text is a
placeholder ({deliveries}, {rec:R0005421.time}) that this script fills. A story names its dataset by the id it has
in the registry (agenttrace/claims/datasets.json); a story with no "dataset" is a Swarm Traces story.

Where a number may come from, by dataset:
  a dataset the tool is run on (Swarm Traces)      "from": "/api/state"   the app's API with the release loaded
  a dataset measured into reports/external/<name>  "from": "reports/external/<name>/results.json"   the saved result
A story of the second kind may read its own dataset's saved result and nothing else, so it cannot print a number
that file does not hold. The build stops when a figure is not there, when a bundle that is kept holds a value the
saved result no longer has, or when a digit is typed into the text.

What is published about a record, by dataset (the "gallery" block of the registry entry):
  "viewer"    no record text: ids and metadata, each record a link to the publisher's own viewer (Swarm Traces,
              whose release states no licence)
  "excerpts"  at most 160 characters of each cited record, each with the dataset's attribution line (open licences)
  "none"      numbers only: a story may cite no record, so no text and no agent name is published (Moltbook)
The citation, the licence and the attribution line on every page are the registry's.

For each story the script writes
  docs/investigations/data/<slug>.json    the evidence bundle: the figures (value, where it came from) and ONLY
                                          the cited records' fields
  docs/investigations/<slug>/index.html   the page: the story, each claim a link that opens its evidence
and docs/investigations/index.html, the gallery, grouped by dataset.

What is read. Report figures are read from the saved results on every run. Records, and figures from the API, need
the dataset: the Swarm Traces release is loaded in this process (--input, or the file the registry names when it is
in the repository folder; --api uses a running tool instead); the rows another story cites are loaded in a
`python3 -I` child by the loader its measurement module gives (agenttrace/failure_eval.py STORY_DATA,
agenttrace/external_eval.py STORIES). A dataset that is not on this machine keeps the records of the bundle on
disk, and the run says so.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

from . import smoke

ROOT = smoke.ROOT
OUT = os.path.join(ROOT, "docs", "investigations")
REGISTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claims", "datasets.json")
DEFAULT_DATASET = "swarm_traces"
SNIPPET_MAX = 160
MAX_RECORDS = 40
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# what a page may show of a record, and how the gallery says so
POLICIES = {"viewer": "record ids and metadata, each linked to the publisher's viewer; no record text",
            "excerpts": "short excerpts of the cited records, each with the credit line",
            "none": "numbers only: no record, no text and no agent name"}
REPO = "https://github.com/itsfingerlickinggood/swarm-tracer"
PLACE_TYPES = {"hf_dataset": "Hugging Face dataset", "board": "board folder", "webhook": "webhook",
               "command_file": "command file", "page": "wiki page"}
GRADES = {"direct": "the write and the read are both in the call that names the place",
          "inferred": "the write or read was found through a variable, a helper or nearby text",
          "weak": "no verb found, a merged place, or an estimated time that is too coarse"}
RECORD_FIELDS = ("id", "kind", "time", "time_estimated", "time_source", "actor", "actor_kind", "agent", "intent",
                 "text_length", "judged", "messages", "viewer")


# ---------------------------------------------------------------------- the registry: citation, licence, credit

_REGISTRY = {}


def gallery_datasets(path=None):
    """{dataset id: citation} for every registry entry that has a "gallery" block. A citation holds what a page
    prints about its source (name, title, citation text, link, licence, attribution line) and the rule for records."""
    path = path or REGISTRY
    if path not in _REGISTRY:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
        out = {}
        for e in reg.get("entries", []):
            g = e.get("gallery")
            if not g:
                continue
            out[e["id"]] = {"dataset": e["id"], "name": g["name"], "title": e["title"], "kind": e.get("kind", ""),
                            "text": e["citation"], "url": g["url"], "licence": e["terms"]["licence"],
                            "attribution": g["attribution"], "records": g["records"], "viewer": g.get("record_url"),
                            "report": g.get("report"), "input": (e.get("local") or {}).get("path"),
                            "pack": (e.get("reader") or {}).get("pack")}
        _REGISTRY[path] = out
    return _REGISTRY[path]


def citation_of(dataset, path=None):
    ds = gallery_datasets(path)
    if dataset not in ds:
        raise SystemExit(f"dataset {dataset!r} has no \"gallery\" block in {os.path.relpath(path or REGISTRY, ROOT)}: "
                         f"the gallery takes its citation, licence and record rule from there")
    return dict(ds[dataset])


def dataset_of(story, bundle=None):
    return (bundle or {}).get("dataset") or story.get("dataset") or DEFAULT_DATASET


# the Swarm Traces citation, for callers that build a bundle by hand
CITATION = citation_of(DEFAULT_DATASET)
CITATION_TEXT = CITATION["text"]


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


class NoDataset(Exception):
    """A value was asked of a dataset that is not loaded."""


def read_report(path, root=ROOT):
    """A saved result under reports/ (a figure's "from"), as parsed JSON."""
    parts = path.split("/")
    if parts[0] != "reports" or ".." in parts or not path.endswith(".json"):
        raise SystemExit(f"{path}: a saved result is a .json file under reports/")
    full = os.path.join(root, *parts)
    if not os.path.isfile(full):
        raise SystemExit(f"{path} is not there: run the measurement that writes it first")
    with open(full, encoding="utf-8") as f:
        return json.load(f)


class Api:
    """Where figures and records are read: GET against a running Swarm Tracer (each path once), and the saved
    results under reports/. With no base there is no dataset behind it, and only saved results can be read."""

    def __init__(self, base=None, root=ROOT):
        self.base = base.rstrip("/") if base else None
        self.root = root
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            if path.startswith("reports/"):
                self.cache[path] = read_report(path, self.root)
            elif not self.base:
                raise NoDataset(path)
            else:
                code, data, _ = smoke.http(self.base, path, timeout=600)
                if code != 200 or not isinstance(data, (dict, list)):
                    raise SystemExit(f"GET {path} on {self.base} failed: {code} {str(data)[:200]}")
                self.cache[path] = data
        return self.cache[path]


# ---------------------------------------------------------------------- the bundle

def is_report(spec):
    return str(spec.get("from", "")).startswith("reports/")


def figure_value(spec, src):
    v = dig(src, spec["path"])
    if spec.get("over"):
        v = v / dig(src, spec["over"])
    return v


def figure_entry(spec, v):
    how = spec.get("as", "text")
    return {"value": v, "text": fmt_value(v, how), "as": how, "from": spec["from"],
            "path": spec["path"] + (" / " + spec["over"] if spec.get("over") else ""), "label": spec.get("label", "")}


def resolve_figures(story, api, only=None):
    out = {}
    for key, spec in story.get("figures", {}).items():
        if only is not None and not only(spec):
            continue
        src = api.get(spec["from"])
        try:
            v = figure_value(spec, src)
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as e:
            raise SystemExit(f"{story['slug']}: figure {key}: {spec['from']} has no {spec['path']} ({e})")
        out[key] = figure_entry(spec, v)
    return out


def cited_records(story):
    ids = []
    for c in story["claims"].values():
        for r in c.get("records", []):
            rid = r["id"] if isinstance(r, dict) else r
            if rid not in ids:
                ids.append(rid)
    return ids


def story_texts(story):
    """The story's own prose: the dek, the headings, the paragraphs and the notes."""
    return [story.get("dek", "")] + [b.get("p") or b.get("note") or b.get("h") or "" for b in story["body"]]


def story_problems(story, cit):
    """Where a story breaks its dataset's rules: [(kind, what is wrong)]. kind is "records" (it shows what the
    dataset's terms do not allow), "credit", "figure-source" or "number"."""
    slug, name, out = story["slug"], cit["name"], []
    if cit["records"] not in POLICIES:
        out.append(("records", f"the registry gives {name} the record rule {cit['records']!r}; it must be one of {', '.join(POLICIES)}"))
    ids = cited_records(story)
    if len(ids) > MAX_RECORDS:
        out.append(("records", f"cites {len(ids)} records; the limit is {MAX_RECORDS}"))
    keys = set(PLACEHOLDER.findall(" ".join(story_texts(story) + [json.dumps(story["claims"])])))
    if cit["records"] == "none" and (ids or any(k.startswith("rec:") for k in keys)):
        out.append(("records", f"{name} is published as numbers only; a story on it may cite no record"))
    src = story.get("source") or {}
    if src.get("attribution") and src["attribution"] != cit["attribution"]:
        out.append(("credit", f"its credit line differs from the registry's (gallery.attribution of {cit['dataset']} in "
                              f"agenttrace/claims/datasets.json). The pages print the registry's; make the two the same"))
    if src.get("snippets") == "on" and cit["records"] != "excerpts":
        out.append(("records", f"asks for excerpts, which the registry does not allow for {name}"))
    for key, spec in story.get("figures", {}).items():
        frm = str(spec.get("from", ""))
        if cit.get("report"):
            if frm != cit["report"]:
                out.append(("figure-source", f"figure {key} reads {frm}; a {name} story reads {cit['report']} and nothing else"))
        elif not frm.startswith("/api/"):
            out.append(("figure-source", f"figure {key} reads {frm}; a {name} story reads the tool's API (/api/...)"))
    for t in story_texts(story):
        m = re.search(r"\S*\d\S*", PLACEHOLDER.sub("", plain(t)))
        if m:
            out.append(("number", f"the text holds the number {m.group(0)!r}; a number is a placeholder filled from the data"))
    return out


def check_story(story, cit):
    """Stop the build when a story breaks its dataset's rules."""
    for _, what in story_problems(story, cit):
        raise SystemExit(f"{story['slug']}: {what}")


WORD_MAX = 32


def text_figures_too_long(cit, figures):
    """Keys of the figures that would print more than one word of a dataset that is published as numbers only."""
    if cit["records"] != "none":
        return []
    return sorted(k for k, f in figures.items() if f.get("as") == "text" and (len(str(f["text"])) > WORD_MAX or len(str(f["text"]).split()) != 1))


def check_values(story, cit, figures):
    bad = text_figures_too_long(cit, figures)
    if bad:
        raise SystemExit(f"{story['slug']}: figure {bad[0]} would print text of {cit['name']}, which is published as numbers only "
                         f"(a text figure there is one word of at most {WORD_MAX} characters)")
    return figures


def needs_dataset(story):
    """True when the story shows records, insider findings or API figures, which only the loaded dataset gives."""
    return bool(cited_records(story) or any(c.get("findings") for c in story["claims"].values())
                or any(not is_report(spec) for spec in story.get("figures", {}).values()))


def mask_hosts(text):
    """Host names in a snippet are masked, except the public service the incident is about."""
    keep = ("huggingface.co",)
    return re.sub(r"\b(?:[a-z0-9-]+\.)+(?:org|com|net|io|dev|internal|local|cloud|ai)\b",
                  lambda m: m.group(0) if m.group(0).lower() in keep else "[HOST]", text, flags=re.I)


def snippet_of(trace, mask=True):
    """At most SNIPPET_MAX characters of the record's text, around the first place it names, line breaks joined.
    mask=False keeps host names: an openly licensed excerpt is cut short and not changed otherwise."""
    text = trace.get("text") or ""
    spans = [w for w in trace.get("why") or [] if w.get("type") == "place"]
    start = max(0, spans[0]["s"] - 30) if spans else 0
    raw = " ".join(text[start:start + 400].split())
    if mask:
        raw = mask_hosts(raw)
    cut = raw[:SNIPPET_MAX - 2]
    return ("…" if start else "") + cut[:SNIPPET_MAX - 2].rstrip() + ("…" if start + len(cut) < len(text) else "")


def record_entry(rid, api, snippets, cit=None):
    cit = cit or CITATION
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
           "intent": t.get("intent"), "text_length": t.get("text_length"), "judged": judged, "messages": messages}
    if cit.get("viewer"):
        rec["viewer"] = cit["viewer"].format(id=t["id"])
    if snippets:
        rec["snippet"] = snippet_of(t, mask=cit["records"] != "excerpts")
    return rec


def report_stamp(cit, api):
    """Which saved result a story's numbers were read from, and what made it."""
    res = api.get(cit["report"])
    return {"report": cit["report"], "report_tool_version": res.get("tool_version"),
            "report_date": str(res.get("generated") or res.get("measured_on") or "")[:10]}


def build_bundle(story, api, snippets=None, version=None):
    """The evidence bundle of one story. snippets: None follows the registry's rule for the story's dataset (on for
    "excerpts", off otherwise); True or False overrides it where records may be shown at all."""
    cit = citation_of(dataset_of(story))
    check_story(story, cit)
    if snippets is None:
        snippets = cit["records"] == "excerpts" and (story.get("source") or {}).get("snippets", "on") != "off"
    if version is None:
        from .export_static import tool_version
        version = tool_version()
    ids = cited_records(story)
    want = [f for c in story["claims"].values() for f in c.get("findings", [])]
    produced = {"tool": "Swarm Tracer", "version": version}
    records, findings = {}, {}
    if api.base:
        state = api.get("/api/state")["summary"]
        units = api.get("/api/x/units_map")
        produced.update({"pack": state.get("pack"), "agent_rule": units.get("rule"), "agent_rule_note": units.get("note"),
                         "dataset": state.get("name"), "records": state.get("records")})
        if want:
            allf = {f["id"]: f for f in api.get("/api/x/insiders")["findings"]}
            for fid in want:
                if fid not in allf:
                    raise SystemExit(f"{story['slug']}: no insider finding {fid}")
                f = allf[fid]
                findings[fid] = {"id": fid, "group": f["group"], "source": f["source"], "finding": f["finding"],
                                 "status": f["status"], "why": f["why"]}
        records = {rid: record_entry(rid, api, snippets, cit) for rid in ids}
    elif ids or want:
        raise NoDataset(story["slug"])
    if cit.get("report"):
        produced.update(report_stamp(cit, api))
    return {
        "schema": 1, "story": story["slug"], "dataset": cit["dataset"], "snippets": "on" if snippets and records else "off",
        "citation": cit, "produced_by": produced,
        "figures": check_values(story, cit, resolve_figures(story, api)),
        "records": records,
        "findings": findings,
    }


def refresh_bundle(story, old, root=ROOT, reread=True):
    """A bundle on disk brought up to date without its dataset.
    reread=False (pages only): nothing of it changes but the citation, which is always the registry's.
    reread=True (the dataset is kept, or is not on this machine): the story's rules are checked and the report
    figures are read again from the saved result; the records, findings and API figures are kept as they are, so
    the story may not ask for one the bundle does not hold."""
    slug = story["slug"]
    cit = citation_of(dataset_of(story))
    b = dict(old, dataset=cit["dataset"], citation=cit)
    if not reread:
        return b
    check_story(story, cit)
    need = f"{slug}: the bundle on disk has no {{}}; this story needs its dataset to be rebuilt"
    ids = cited_records(story)
    for rid in ids:
        if rid not in old.get("records", {}):
            raise SystemExit(need.format("record " + rid))
    b["records"] = {rid: old["records"][rid] for rid in ids}
    want = [f for c in story["claims"].values() for f in c.get("findings", [])]
    for fid in want:
        if fid not in old.get("findings", {}):
            raise SystemExit(need.format("finding " + fid))
    b["findings"] = {fid: old["findings"][fid] for fid in want}
    api = Api(None, root)
    figures = {}
    for key, spec in story.get("figures", {}).items():
        if is_report(spec):
            figures.update(resolve_figures(story, api, only=lambda s, spec=spec: s is spec))
            continue
        f = old.get("figures", {}).get(key)
        path = spec["path"] + (" / " + spec["over"] if spec.get("over") else "")
        if f is None or f.get("from") != spec["from"] or f.get("path") != path:
            raise SystemExit(need.format(f"figure {key} from {spec['from']} {path}"))
        figures[key] = figure_entry(spec, f["value"])
    b["figures"] = check_values(story, cit, figures)
    b["produced_by"] = dict(old.get("produced_by") or {})
    if cit.get("report"):
        b["produced_by"].update(report_stamp(cit, api))
    if not b["records"]:
        b["snippets"] = "off"
    return b


def report_mismatches(story, bundle, root=ROOT):
    """Every report figure of the bundle that is not what the saved result holds now: [(key, in bundle, saved)]."""
    out = []
    for key, spec in story.get("figures", {}).items():
        if not is_report(spec):
            continue
        have = (bundle.get("figures") or {}).get(key) or {}
        try:
            v = figure_value(spec, read_report(spec["from"], root))
            want = figure_entry(spec, v)
        except SystemExit as e:
            out.append((key, have.get("text"), str(e)))
            continue
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as e:
            out.append((key, have.get("text"), f"{spec['from']} has no {spec['path']} ({e})"))
            continue
        if have.get("value") != want["value"] or have.get("text") != want["text"] or have.get("from") != want["from"] or have.get("path") != want["path"]:
            out.append((key, have.get("text"), want["text"]))
    return out


# ---------------------------------------------------------------------- loading a story's records in a child

CHILD = ("import sys; sys.path.insert(0, sys.argv[1]); from agenttrace.tools import build_investigations as B; "
         "sys.exit(B.child_main(sys.argv[2:]))")


def story_rows(slug):
    """The records the story's dataset reader gives for the runs the story cites, from the measurement modules."""
    from .. import external_eval, failure_eval
    for table in (failure_eval.STORY_DATA, external_eval.STORIES):
        if slug in table:
            return table[slug][1]()
    raise SystemExit(f"{slug}: no loader gives this story's records (see STORY_DATA in agenttrace/failure_eval.py "
                     f"and STORIES in agenttrace/external_eval.py)")


def child_main(argv):
    """Run in a `python3 -I` child, which is the only process that opens the downloaded files: load the rows the
    story cites, serve them read-only, and print the story's bundle as the last line of output."""
    story_path, root, snip = argv
    import shutil
    from .export_static import start_server, tool_version
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)
    cit = citation_of(dataset_of(story))
    try:
        rows = story_rows(story["slug"])
    except OSError as e:
        print(json.dumps({"missing": f"{type(e).__name__}: {e}"}))
        return 0
    tmp = tempfile.mkdtemp(prefix="story-rows-")
    try:
        data = os.path.join(tmp, "rows.jsonl")
        with open(data, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        httpd, base, _ = start_server(data, "auto", cit["name"])
        try:
            bundle = build_bundle(story, Api(base, root), {"on": True, "off": False}.get(snip), tool_version())
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)          # the copy of the rows is not part of the result
    print("\n" + json.dumps({"bundle": bundle}))
    return 0


def child_bundle(story_path, root=ROOT, snippets=None):
    """The story's bundle, built from its dataset in a child; None (and why) when the dataset is not on this machine."""
    snip = {True: "on", False: "off"}.get(snippets, "auto")
    env = dict(os.environ, SWARM_TRACER_NO_CACHE="1")
    r = subprocess.run([sys.executable, "-I", "-W", "ignore", "-c", CHILD, ROOT, os.path.abspath(story_path), os.path.abspath(root), snip],
                       capture_output=True, text=True, timeout=3600, cwd=tempfile.gettempdir(), env=env)
    if r.returncode:
        raise SystemExit((r.stderr.strip().splitlines() or [f"the child that loads {story_path} failed"])[-1])
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out.get("bundle"), out.get("missing")


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
    cit = bundle["citation"]
    size = f'{int(r["text_length"] or 0):,} characters'
    if "snippet" in r and cit.get("records") == "excerpts":
        text = (f'<blockquote class="snip"><code>{E(r["snippet"])}</code><footer>Excerpt of a record of {size}, line breaks joined. '
                f'<span class="credit">{E(cit["attribution"])}</span></footer></blockquote>')
    elif "snippet" in r:
        text = f'<blockquote class="snip"><code>{E(r["snippet"])}</code><footer>Excerpt of {size}, from the redacted release</footer></blockquote>'
    elif r.get("viewer"):
        text = (f'<p class="nosnip">Text not reproduced here ({size}). '
                f'<a href="{E(r["viewer"])}" rel="noopener">Read record {E(rid)} in the publisher\'s viewer</a>.</p>')
    else:
        text = f'<p class="nosnip">Text not reproduced here ({size}).</p>'
    return (f'<article class="rec" data-rid="{E(rid)}"><header><code class="rid">{E(rid)}</code><span class="kind">{E(r.get("kind") or "record")}</span></header>'
            + (f'<p class="role">{fill(note, bundle)}</p>' if note else "") + f'<dl>{body}</dl>{text}</article>')


def figure_item(key, bundle):
    f = bundle["figures"][key]
    cls = "v long" if len(f["text"]) > 24 else "v"
    return (f'<li><b class="{cls}" data-v="{E(key)}">{E(f["text"])}</b> <span>{E(f.get("label") or key.replace("_", " "))}</span>'
            f'<small>{"" if str(f["from"]).startswith("reports/") else "GET "}{E(f["from"])} → <code>{E(f["path"])}</code></small></li>')


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
    if p.get("report"):
        made = f', measured with Swarm Tracer {E(str(p["report_tool_version"]))}' if p.get("report_tool_version") else ""
        when = f' on {E(str(p["report_date"]))}' if p.get("report_date") else ""
        line = (f'Numbers: read from <a href="{REPO}/blob/main/{E(p["report"])}" rel="noopener">{E(p["report"])}</a>{made}{when}, '
                f'and filled in by Swarm Tracer {E(str(p["version"]))}.')
        if bundle.get("records"):
            line += f' The cited records are shown as the tool loads them (pack "{E(str(p.get("pack")))}").'
        return line
    return (f'Numbers: Swarm Tracer {E(str(p["version"]))}, pack "{E(str(p["pack"]))}", agents counted by the '
            f'"{E(str(p["agent_rule"]))}" rule (tokens merged on direct evidence), on {E(str(p["dataset"]))} '
            f'({int(p["records"]):,} records). Times marked estimated are dated from timestamps in the agents\' code.')


def record_rule(bundle):
    """One sentence on what the page shows of the records, by the dataset's rule and what the bundle holds."""
    rule = bundle["citation"].get("records")
    if bundle.get("snippets") == "on":
        return "Short excerpts of the cited records are shown" + (", each with the credit line below." if rule == "excerpts" else ".")
    if rule == "none":
        return "Numbers only: no record, no text and no agent name is published."
    if rule == "viewer":
        return "Record text is not reproduced: each record links to the publisher's viewer."
    return "No record text is reproduced."


def source_block(cit, up, mode=""):
    """The citation, the licence and the attribution line of a dataset, all from the registry."""
    text = cit["text"].rstrip(".")
    return (f'<p><b>Data.</b> <a href="{E(cit["url"])}" rel="noopener">{E(cit["name"])}</a>. {E(text)}. '
            f'Licence: {E(cit["licence"])}. {E(mode) + " " if mode else ""}'
            f'<a href="{E(up)}datasets.html#{E(cit["dataset"])}">The terms, and what this site may publish</a>.</p>\n'
            f'<p class="credit">{E(cit["attribution"])}</p>')


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
    cit = bundle["citation"]
    kicker = story.get("kicker") or cit["title"]
    ev = "".join(evidence_section(cid, n + 1, story, bundle) for n, cid in enumerate(order))
    return (page_head(f'{story["title"]} · Swarm Tracer investigations', fill_plain(story["dek"], bundle), "../story.css")
            + f'<body class="story" data-story="{E(story["slug"])}" data-dataset="{E(cit["dataset"])}" data-snippets="{bundle["snippets"]}">\n{site_header("../../", "inv")}\n'
            f'<main id="main" class="layout">\n<article class="text">\n'
            f'<p class="kicker"><a href="../">Investigations</a> · {i + 1} of {len(stories)} · {E(kicker)}</p>\n'
            f'<h1>{E(story["title"])}</h1>\n<p class="dek">{fill(story["dek"], bundle)}</p>\n'
            f'<p class="meta">{len(order)} claims · {nrec} records cited · {story_words(story, bundle)} words. '
            f'<span class="hint">Select a marked claim to see the evidence behind it.</span></p>\n'
            + "\n".join(blocks) +
            f'\n<footer class="source">\n<h2>Source and method</h2>\n'
            f'{source_block(cit, "../../", record_rule(bundle))}\n'
            f'<p class="produced">{produced_line(bundle)}</p>\n'
            f'<p><a href="../data/{E(story["slug"])}.json">Evidence bundle (JSON)</a> · <a href="../stories/{E(story["slug"])}.json">Story source (JSON)</a> · '
            f'<a href="../../validation.html">How accurate is the tool?</a> · <a href="../../limitations.html">Limits</a></p>\n{nav}\n</footer>\n</article>\n'
            f'<aside id="evidence" class="evidence" aria-label="Evidence">\n<div class="evbar"><b>Evidence</b><span id="evcount" class="quiet"></span>'
            f'<button type="button" id="evclose" hidden>Close</button></div>\n'
            f'<p class="evempty" id="evempty" hidden>Select a marked claim in the text. Its records, numbers and what the tool judged open here.</p>\n'
            f'<div id="evlist" class="evlist">{ev}</div>\n</aside>\n</main>\n<script src="../story.js"></script>\n</body>\n</html>\n')


def fill_plain(text, bundle):
    return PLACEHOLDER.sub(lambda m: value_text(m.group(1), bundle), plain(text))


NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"]


def number_word(n):
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def story_groups(stories, bundles):
    """The stories by dataset, in story order: [(citation, [(number in the gallery, story)])]."""
    groups = []
    for n, s in enumerate(stories, 1):
        cit = bundles[s["slug"]]["citation"]
        g = next((g for g in groups if g[0]["dataset"] == cit["dataset"]), None)
        if g is None:
            g = (cit, [])
            groups.append(g)
        g[1].append((n, s))
    return groups


def render_index(stories, bundles):
    sections = []
    groups = story_groups(stories, bundles)
    for cit, members in groups:
        cards = []
        for n, s in members:
            b = bundles[s["slug"]]
            cards.append(f'<li class="case"><a href="{E(s["slug"])}/"><span class="n" aria-hidden="true">{n}</span>'
                         f'<h3>{E(s["title"])}</h3><p>{fill(s["dek"], b)}</p>'
                         f'<span class="foot">{len(s["claims"])} claims · {len(b["records"])} records cited<b>Read the investigation →</b></span></a></li>')
        did = E(cit["dataset"])
        b0 = bundles[members[0][1]["slug"]]
        sections.append(
            f'<section class="group" id="ds-{did}" data-dataset="{did}" aria-labelledby="dsh-{did}">\n'
            f'<header><p class="kind">{E(cit["kind"])} · {E(POLICIES.get(cit["records"], ""))}</p>\n<h2 id="dsh-{did}">{E(cit["title"])}</h2>\n'
            f'{source_block(cit, "../")}</header>\n'
            f'<ol class="cases" start="{members[0][0]}">{"".join(cards)}</ol>\n'
            f'<p class="produced">{produced_line(b0)}</p>\n</section>')
    count = f'{number_word(len(stories))} short investigation{"" if len(stories) == 1 else "s"}'
    over = f' of {number_word(len(groups)).lower()} datasets' if len(groups) > 1 else f' of {E(groups[0][0]["name"])}' if groups else ""
    return (page_head("Investigations · Swarm Tracer", "Written investigations of multi-agent datasets. Every claim opens the records and numbers behind it.", "story.css")
            + f'<body class="gallery">\n{site_header("../", "inv")}\n<main id="main" class="wrap">\n'
            f'<p class="kicker">Investigations</p>\n<h1>What the records show, claim by claim</h1>\n'
            f'<p class="dek">{count}{over}, written with Swarm Tracer and grouped by dataset. Every claim is a link. '
            f'It opens what is behind it: the numbers and where each was read, and the cited records with what the tool judged.</p>\n'
            + "\n".join(sections) +
            f'\n<section class="about">\n<h2>How these are made</h2>\n'
            f'<p>Each story is a small JSON file with no numbers in it. A build script fills every number, either from the dataset '
            f'through the tool or from a saved measurement in the repository, and writes an evidence bundle that holds only the cited records. '
            f'A check fails the site if a claim has no evidence, if a number on a page differs from the bundle or from the saved measurement, '
            f'or if anything that looks like a secret is published.</p>\n'
            f'<p>What a page shows of a record depends on the terms of its dataset. Where no licence is stated, the page gives record ids, '
            f'times and what the tool judged, and links each record to the publisher\'s own viewer. Where the licence is open, it shows short '
            f'excerpts, each with the credit line. For a social network of agents it shows numbers only. '
            f'The citation, the licence and the credit line of each dataset come from the <a href="../datasets.html">dataset registry</a>.</p>\n'
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


def read_bundle(out, slug):
    p = os.path.join(out, "data", slug + ".json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class Release:
    """A dataset the tool is run on whole (Swarm Traces): a running tool (--api), or the file loaded in this
    process the first time a story asks for it (--input, or the file the registry names)."""

    def __init__(self, api=None, path=None, pack="auto", root=ROOT):
        self.api, self.path, self.pack, self.root, self.httpd = api, path, pack, root, None

    def get(self, cit):
        if self.api is None:
            path = self.path or (os.path.join(ROOT, cit["input"]) if cit.get("input") else None)
            if not path or not os.path.isfile(path):
                return None
            from .export_static import start_server
            pack = self.pack if self.pack != "auto" or not str(cit.get("pack") or "").endswith(".json") else cit["pack"]
            self.httpd, base, _ = start_server(path, pack, os.path.basename(path))
            self.api = Api(base, self.root)
        return self.api

    def close(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def build(api=None, snippets=None, out=OUT, check=False, from_bundles=False, log=print, root=ROOT, keep=(), release=None):
    """Build every story under out/stories. api: an Api on the Swarm Traces release (or give release, a Release).
    from_bundles: read no dataset and change no bundle value, only render; it stops if a bundle holds a report
    figure the saved result does not. keep: dataset ids whose records are kept as the bundles on disk have them."""
    from .export_static import tool_version
    stories = load_stories(out)
    release = release or Release(api, root=root)
    bundles, how = {}, {}
    try:
        for s in stories:
            slug = s["slug"]
            cit = citation_of(dataset_of(s))
            old = read_bundle(out, slug)
            fresh, why = None, ""
            if from_bundles or cit["dataset"] in keep:
                why = "pages only" if from_bundles else "kept (--keep)"
            elif not needs_dataset(s):
                fresh, why = build_bundle(s, Api(None, root), snippets, tool_version()), "numbers from the saved result"
            elif cit.get("report"):
                fresh, missing = child_bundle(os.path.join(out, "stories", slug + ".json"), root, snippets)
                why = "records from the dataset" if fresh else f"dataset not on this machine, records kept ({missing})"
            else:
                a = release.get(cit)
                if a is not None:
                    fresh, why = build_bundle(s, a, snippets, tool_version()), "from the dataset"
                else:
                    why = f"{cit['input'] or cit['name']} is not on this machine, bundle kept"
            if fresh is None:
                if old is None:
                    raise SystemExit(f"{slug}: there is no bundle to keep (docs/investigations/data/{slug}.json) and its dataset was not read")
                fresh = refresh_bundle(s, old, root, reread=not from_bundles)
            wrong = report_mismatches(s, fresh, root)
            if wrong:
                raise SystemExit(f"{slug}: the bundle holds numbers the saved result does not: "
                                 + "; ".join(f"{k} is {have!r} in the bundle, {want!r} in the saved result" for k, have, want in wrong[:6])
                                 + ". Run this build without --from-bundles to read them again.")
            first = ("schema", "story", "dataset", "snippets", "citation", "produced_by", "figures", "records", "findings")
            bundles[slug] = dict([(k, fresh[k]) for k in first if k in fresh] + [(k, v) for k, v in fresh.items() if k not in first])
            how[slug] = why
    finally:
        release.close()
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
        log(f"  {s['slug']} [{b['dataset']}]: {len(s['claims'])} claims, {len(b['records'])} records, {len(b['figures'])} figures, "
            f"{story_words(s, b)} words, snippets {b['snippets']}; {how[s['slug']]}")
    log(("would change: " if check else "wrote: ") + (", ".join(changed) or "nothing (up to date)"))
    return changed


def build_one(slug, out=None, log=print, root=ROOT):
    """Build one story of a measured dataset into a temporary folder, from its dataset: a check that it builds,
    used by the measurement modules. Returns (folder, bundle, page)."""
    import shutil
    src = os.path.join(OUT, "stories", slug + ".json")
    with open(src, encoding="utf-8") as f:
        story = json.load(f)
    tmp = out or tempfile.mkdtemp(prefix="story-check-")
    os.makedirs(os.path.join(tmp, "stories"), exist_ok=True)
    shutil.copy(src, os.path.join(tmp, "stories", slug + ".json"))
    if needs_dataset(story):
        bundle, missing = child_bundle(src, root)
        if bundle is None:
            raise SystemExit(f"{slug}: its dataset is not on this machine ({missing})")
    else:
        bundle = build_bundle(story, Api(None, root))
    page = render_story(story, bundle, [story])
    os.makedirs(os.path.join(tmp, slug), exist_ok=True)
    with open(os.path.join(tmp, slug, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(tmp, "bundle.json"), "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=1, ensure_ascii=False)
    log(f"{slug}: {len(story['claims'])} claims, {len(bundle['records'])} records, {len(bundle['figures'])} figures, "
        f"{story_words(story, bundle)} words -> {tmp}")
    return tmp, bundle, page


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", help="a running Swarm Tracer with the Swarm Traces release loaded (e.g. http://localhost:8010)")
    ap.add_argument("--input", help="or: the Swarm Traces release to load in this process (default: the file the registry names, when it is here)")
    ap.add_argument("--pack", default="auto", help="the pack for --input (default: the one the registry names)")
    ap.add_argument("--snippets", choices=("on", "off"), help="override the registry's rule (default: excerpts only where the registry allows them)")
    ap.add_argument("--keep", default="", help="dataset ids, comma-separated, whose bundles keep their records (saved results are still read again)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if a rebuild would change a file")
    ap.add_argument("--from-bundles", action="store_true", help="render the pages from the bundles on disk (no dataset); stop if a bundle and a saved result differ")
    a = ap.parse_args(argv)
    keep = tuple(k for k in a.keep.split(",") if k)
    for k in keep:
        citation_of(k)
    release = Release(Api(a.api) if a.api else None, a.input, a.pack)
    changed = build(None, {"on": True, "off": False}.get(a.snippets), a.out, a.check, a.from_bundles, keep=keep, release=release)
    return 1 if (a.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())

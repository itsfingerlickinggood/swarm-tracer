"""Case file (pins, notes, export), labeling inside the app, and the ground-truth test mode.

Routes (served at /api/x/<name>, see extensions.py):
    GET  case                    the investigator's case file for the loaded dataset
    POST case                    save it (body: the case JSON: title, notes, items [{kind, key, note}])
    GET  case_export?format=html|json&base=   the dossier: every pinned item with its facts, the key numbers and
                                 the warning signs. html comes back as {"filename", "html"} (self-contained page,
                                 inline CSS, printable to PDF); json as {"filename", "dossier"}
    GET  time_range?id=          an estimated time with the range its dating block's fit error allows
    GET  labels?id=              the labels already given to one record (its tags, intent and messages)
    POST label                   {id, tag, label: "1"|"0"|"?"|"", preview}: save one label
    GET  precision               live precision per pattern from those labels, with Wilson intervals
    GET  groundtruth_score       precision and recall against a truth file (agenttrace.groundtruth), when one
                                 matches the loaded dataset
    POST groundtruth_truth       body: a truth file to score the loaded dataset against

Case files live in ~/.swarm-tracer/cases/<dataset>.json and labels in ~/.swarm-tracer/labels-<dataset>.csv
(set SWARM_TRACER_HOME to keep them elsewhere).
"""
import datetime as dt
import html
import json
import os
import re
import threading

from . import groundtruth, insight, labels, reconstruct

KINDS = ("record", "actor", "place", "conversation")
KIND_TITLE = {"record": "Records", "actor": "Actors", "place": "Places", "conversation": "Conversations"}
UTC = dt.timezone.utc


# ------------------------------------------------------------------ storage

def home():
    return os.environ.get("SWARM_TRACER_HOME") or os.path.join(os.path.expanduser("~"), ".swarm-tracer")


def _slug(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "dataset")).strip("._")[:120] or "dataset"


def case_path(s):
    return os.path.join(home(), "cases", _slug(s.name) + ".json")


def labels_path(s):
    return os.path.join(home(), f"labels-{_slug(s.name)}.csv")


def _now():
    return dt.datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("No dataset loaded. Upload a file first.")
    return s


_LOCK = threading.Lock()


def _write_json(path, obj):
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)


def empty_case(s):
    return {"dataset": s.name, "title": f"Case file: {s.name}", "notes": "", "items": [], "created": _now(), "updated": None}


def load_case(s):
    try:
        with open(case_path(s), encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict) and isinstance(c.get("items"), list):
            return c
    except (OSError, ValueError):
        pass
    return empty_case(s)


def clean_case(s, body):
    if not isinstance(body, dict):
        raise ValueError("the case file must be a JSON object")
    old = load_case(s)
    items, seen = [], set()
    for it in body.get("items") or []:
        if not isinstance(it, dict):
            raise ValueError("each pinned item must be an object with kind and key")
        kind, key = it.get("kind"), it.get("key")
        if kind not in KINDS or not isinstance(key, str) or not key or len(key) > 2000:
            raise ValueError(f"a pinned item needs a kind ({', '.join(KINDS)}) and a key")
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        note = it.get("note") or ""
        if not isinstance(note, str) or len(note) > 50000:
            raise ValueError("a note must be text (at most 50,000 characters)")
        items.append({"kind": kind, "key": key, "note": note, "added": it.get("added") or _now(),
                      **({"tab": it["tab"]} if isinstance(it.get("tab"), str) else {})})
    notes = body.get("notes") or ""
    if not isinstance(notes, str) or len(notes) > 200000:
        raise ValueError("the case notes must be text")
    title = str(body.get("title") or old.get("title") or f"Case file: {s.name}")[:300]
    return {"dataset": s.name, "title": title, "notes": notes, "items": items,
            "created": old.get("created") or _now(), "updated": _now()}


def get_case(state, q):
    s = _session(state)
    return {"case": load_case(s), "path": case_path(s)}


def post_case(state, q, body):
    s = _session(state)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("the case file is not valid JSON")
    if isinstance(data, dict) and isinstance(data.get("case"), dict):
        data = data["case"]
    c = clean_case(s, data)
    _write_json(case_path(s), c)
    return {"case": c, "path": case_path(s)}


# ------------------------------------------------------------------ time ranges for estimated times

def _blocks(s):
    if getattr(s, "_cw_blocks", None) is None:
        out = []
        for b in s.rec["time_test"].get("blocks", []):
            if b.get("timed") and b.get("first_id") in s.order and b.get("last_id") in s.order:
                out.append((s.order[b["first_id"]], s.order[b["last_id"]], b))
        s._cw_blocks = out
    return s._cw_blocks


def _hm(t, ref):
    """HH:MM, with the date when it is not ref's date."""
    d = dt.datetime.fromtimestamp(t, UTC)
    r = dt.datetime.fromtimestamp(ref, UTC)
    return d.strftime("%H:%M") if d.date() == r.date() else f"{d.strftime('%b')} {d.day} {d.strftime('%H:%M')}"


def time_range(s, rid):
    """How sure the record's time is: from its time field, or estimated with the fit error of its dating block."""
    e = s.by_id.get(rid)
    if e is None:
        raise LookupError(f"no record {rid}")
    t = s.rec["_times"].get(rid)
    if t is None:
        return {"id": rid, "source": None, "text": "no time"}
    if e.time:
        return {"id": rid, "source": "time field", "time": reconstruct.iso(t), "text": f"{reconstruct.iso(t)} UTC (from its time field)"}
    cur, hops, seen = rid, 0, set()
    block = None
    while cur and cur in s.by_id and cur not in seen:
        seen.add(cur)
        ce = s.by_id[cur]
        if ce.time:
            return {"id": rid, "source": "inherited", "time": reconstruct.iso(t), "from": cur,
                    "text": f"{reconstruct.iso(t)} UTC (taken from {cur}, which has a time field)"}
        i = s.order[cur]
        block = next((b for a, z, b in _blocks(s) if a <= i <= z), None)
        if block:
            break
        cur, hops = ce.parent, hops + 1
    if not block or block.get("fit_error_hours_p90") is None:
        return {"id": rid, "source": "estimated", "time": reconstruct.iso(t), "text": f"estimated {reconstruct.iso(t)} UTC"}
    p90 = float(block["fit_error_hours_p90"])
    lo, hi = t - p90 * 3600, t + p90 * 3600
    txt = f"estimated {_hm(t, t)} ({'likely ' + _hm(lo, t) + '–' + _hm(hi, t) if p90 > 0 else 'exact fit'})"
    return {"id": rid, "source": "estimated", "time": reconstruct.iso(t), "low": reconstruct.iso(lo), "high": reconstruct.iso(hi),
            "p90_hours": p90, "median_hours": block.get("fit_error_hours_median"), "from": cur if cur != rid else None,
            "block": {"kind": block.get("kind"), "records": block.get("records"), "timestamp_points": block.get("timestamp_points"),
                      "spearman": block.get("spearman")},
            "likely": f"{_hm(lo, t)}–{_hm(hi, t)}", "text": txt,
            "why": (f"Its time is read from where it sits among {block.get('records', 0):,} {block.get('kind') or ''} records "
                    f"dated by {block.get('timestamp_points', 0):,} timestamps found in their text. Nine in ten of those "
                    f"timestamps sit within {p90:g} h of the fitted line, so the range is ±{p90:g} h.")}


def get_time_range(state, q):
    return time_range(_session(state), q.get("id", ""))


# ------------------------------------------------------------------ facts for each pinned item

def _excerpt(text, why, n=6, pad=50):
    spans = sorted(why or [], key=lambda w: w["s"])
    out, last_end = [], -1
    for w in spans:
        if w["s"] < last_end:
            continue
        a, b = max(0, w["s"] - pad), min(len(text), w["e"] + pad)
        out.append({"type": w.get("type"), "label": w.get("label"), "before": text[a:w["s"]], "mark": text[w["s"]:w["e"]][:200],
                    "after": text[w["e"]:b]})
        last_end = w["e"]
        if len(out) >= n:
            break
    return out


def record_facts(s, rid):
    t = s.trace(rid, text_limit=6000)
    if not t:
        return {"kind": "record", "key": rid, "missing": True}
    x = t.get("explain") or {}
    return {"kind": "record", "key": rid, "record_kind": t["kind"], "time": t["time"], "time_range": time_range(s, rid),
            "actor": t["actor"], "actor_kind": t["actor_kind"], "intent": t["intent"], "tags": t["tags"],
            "what": x.get("what") or [], "roles": [{"label": r.get("label"), "detail": r.get("detail")} for r in x.get("roles") or []],
            "harm_share_after": x.get("harm_share_after"),
            "why": _excerpt(t["text"], t.get("why")), "text_start": " ".join(t["text"].split())[:400],
            "messages_in": t["messages_in"][:15], "messages_in_total": len(t["messages_in"]),
            "messages_out": t["messages_out"][:15], "messages_out_total": len(t["messages_out"]),
            "places": t["channel_ops"][:20]}


def actor_facts(s, a):
    try:
        p = insight.actor_profile(s, a)
    except LookupError:
        return {"kind": "actor", "key": a, "missing": True}
    keys = ["kind", "records", "actions", "timed_actions", "harmful", "sent", "received", "partners", "places_total",
            "programs_started_total", "programs_adopted_total", "first", "last", "shared"]
    return {"kind": "actor", "key": a, **{k: p.get(k) for k in keys},
            "intents": p["intents"][:6], "sends_to": p["sends_to"][:8], "hears_from": p["hears_from"][:8],
            "places": [{"channel": r["channel"], "total": r["total"]} for r in p["places"][:8]],
            "signals": [{"name": g["name"], "time": g["time"], "harm_share_after": g["harm_share_after"], "why": g["why"],
                         "record": g.get("record")} for g in p["signals"][:10]]}


def place_facts(s, ch):
    try:
        p = insight.place_detail(s, ch, limit=40)
    except LookupError:
        return {"kind": "place", "key": ch, "missing": True}
    r = p.get("row") or {}
    return {"kind": "place", "key": ch, "type": p["type"], "merged": p["merged"], "writes": r.get("writes"), "reads": r.get("reads"),
            "writers": p["writers"][:10], "writers_total": len(p["writers"]),
            "readers": p["readers"][:10], "readers_total": len(p["readers"]),
            "messages": p["messages"][:20], "messages_total": p["messages_total"], "overwrites": p["overwrites"]}


def conversation_facts(s, key):
    a, _, b = key.partition("|")
    c = s.conversation(a, b, limit=20)
    return {"kind": "conversation", "key": key, "a": a, "b": b, "total": c["total"], "a_to_b": c["a_to_b"], "b_to_a": c["b_to_a"],
            "places": c["places"][:10], "first": c["first"], "last": c["last"],
            "items": [{k: it[k] for k in ("from", "to", "channel", "write_id", "read_id", "write_time", "read_time", "how")}
                      for it in c["items"][:20]]}


FACTS = {"record": record_facts, "actor": actor_facts, "place": place_facts, "conversation": conversation_facts}


def key_numbers(s):
    sm = s.summary()
    f = sm["flow"]
    acts = sm.get("actions") or {}
    return [
        ["records", sm["records"]],
        ["dated records", sm["timed"]],
        ["span", " to ".join(sm["time_test"].get("span") or []) or None],
        ["named actors", acts.get("named_actors")],
        ["places", f.get("channels")],
        ["messages", f.get("deliveries")],
        ["sender-receiver pairs between named actors", f.get("named_actor_pairs")],
        ["harmful actions dated", sm.get("harm_events_timed")],
    ]


def warning_signs(s):
    return [{"name": g["name"], "time": g["time"], "family": g["family"], "harm_share_after": g["harm_share_after"],
             "why": g["why"], "record": g.get("record")} for g in insight.simulate(s)["signals"]]


def link(base, kind, key, tab=None):
    if kind == "conversation":
        a, _, b = key.partition("|")
        from urllib.parse import quote
        return f"{base}#tab=network&a={quote(a, safe='')}&b={quote(b, safe='')}"
    from urllib.parse import quote
    p = {"record": "rec", "actor": "actor", "place": "place"}[kind]
    return f"{base}#tab={quote(tab or 'overview')}&{p}={quote(key, safe='')}"


def dossier(s, base=""):
    c = load_case(s)
    items = []
    for it in c["items"]:
        try:
            facts = FACTS[it["kind"]](s, it["key"])
        except Exception as e:      # one broken pin never stops the export
            facts = {"kind": it["kind"], "key": it["key"], "missing": True, "error": str(e)}
        items.append({**it, "link": link(base, it["kind"], it["key"], it.get("tab")) if base else None, "facts": facts})
    prec = None
    lp = labels_path(s)
    if os.path.exists(lp):
        prec = precision_table(s)
    return {"title": c.get("title"), "dataset": s.name, "pack": s.pack.name, "date": _now(), "notes": c.get("notes", ""),
            "items": items, "key_numbers": key_numbers(s), "warning_signs": warning_signs(s), "precision": prec}


def get_case_export(state, q):
    s = _session(state)
    fmt = q.get("format", "html")
    d = dossier(s, q.get("base", ""))
    stem = "case-" + _slug(s.name)
    if fmt == "json":
        return {"filename": stem + ".json", "dossier": d}
    if fmt != "html":
        raise ValueError("format must be html or json")
    return {"filename": stem + ".html", "html": render_html(d)}


# ------------------------------------------------------------------ the HTML dossier

CSS = """
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:#1b2430;margin:0;background:#f5f7f9}
main{max-width:860px;margin:0 auto;padding:32px 36px;background:#fff}
h1{font-size:24px;margin:0 0 4px}h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#66717d;border-bottom:1px solid #e8ebef;padding-bottom:4px;margin:28px 0 10px}
h3{font-size:15px;margin:0 0 4px}.muted{color:#66717d}.small{font-size:12px}
.meta{color:#66717d;font-size:13px}.notes{white-space:pre-wrap;background:#fbf8ef;border-left:3px solid #e3a43b;padding:10px 14px;border-radius:4px}
.item{border:1px solid #e3e7ec;border-radius:8px;padding:12px 16px;margin:0 0 14px;page-break-inside:avoid}
.kind{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:1px 6px;border-radius:4px;margin-right:6px;background:#eef2f6;color:#4b5157}
.k-record{background:#dbe9f8;color:#24578c}.k-actor{background:#fdf3e1;color:#8a5a12}.k-place{background:#f1ebfb;color:#553399}.k-conversation{background:#e6f4ea;color:#2c6a3d}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}td,th{text-align:left;padding:3px 8px 3px 0;border-bottom:1px solid #eef0f3;vertical-align:top}th{color:#66717d;font-weight:600;font-size:12px}
.num{font-variant-numeric:tabular-nums;text-align:right}
.excerpt{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#f6f8fa;border-radius:4px;padding:6px 8px;margin:4px 0;white-space:pre-wrap;word-break:break-word}
mark{background:#fde68a;padding:0 1px}.note{white-space:pre-wrap;border-left:3px solid #2f6fb3;padding:4px 10px;margin:8px 0;background:#f3f7fc}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.kpi{border:1px solid #e8ebef;border-radius:6px;padding:8px}.kpi b{display:block;font-size:18px}.kpi span{font-size:11px;color:#66717d}
.warn{color:#c2410c}a{color:#2f6fb3}
@media print{body{background:#fff}main{padding:0;max-width:none}a{color:inherit;text-decoration:none}.item{border-color:#ccc}}
"""


def _e(x):
    return html.escape("" if x is None else str(x))


def _n(x):
    return "–" if x is None else (f"{x:,}" if isinstance(x, int) else _e(x))


def _pct(x):
    return "–" if x is None else f"{round(100 * x)}%"


def _short(a):
    return re.sub(r"\[CREDENTIAL (\d+)\]", r"cred \1", str(a or ""))


def _table(head, rows):
    if not rows:
        return '<p class="muted small">none</p>'
    return "<table><tr>" + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr>" + \
        "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def _render_record(f):
    tr = f.get("time_range") or {}
    out = [f'<p class="meta">{_e(f.get("record_kind"))} by <b>{_e(_short(f.get("actor")))}</b> ({_e(f.get("actor_kind"))}) · '
           f'{_e(tr.get("text") or (f.get("time") or "no time"))}{" · intent " + _e(f["intent"]) if f.get("intent") else ""}</p>']
    if tr.get("why"):
        out.append(f'<p class="small muted">{_e(tr["why"])}</p>')
    if f.get("what"):
        out.append("<h3>What it is</h3><ul>" + "".join(f"<li>{_e(w)}</li>" for w in f["what"]) + "</ul>")
    if f.get("tags"):
        out.append(f'<p class="small">Evidence tags: {_e(", ".join(f["tags"]))}</p>')
    out.append("<h3>Its role in the swarm</h3>" + ("<ul>" + "".join(f"<li><b>{_e(r['label'])}</b>: {_e(r['detail'])}</li>" for r in f["roles"]) + "</ul>"
                                                if f.get("roles") else '<p class="muted small">No link to another actor found.</p>'))
    if f.get("harm_share_after") is not None:
        out.append(f'<p class="small">{_pct(f["harm_share_after"])} of all dated harmful actions came after this record.</p>')
    if f.get("why"):
        out.append("<h3>Why it was highlighted</h3>" + "".join(
            f'<div class="excerpt"><span class="muted">{_e(w["label"])}:</span>\n…{_e(w["before"])}<mark>{_e(w["mark"])}</mark>{_e(w["after"])}…</div>'
            for w in f["why"]))
    elif f.get("text_start"):
        out.append(f'<h3>Text (start)</h3><div class="excerpt">{_e(f["text_start"])}</div>')
    rows = [[_e(_short(m["from"])), f'<span class="mono">{_e(m["channel"])}</span>', _e(m["write_id"]), _e(m.get("write_time") or "–")]
            for m in f.get("messages_in", [])]
    if rows:
        out.append(f"<h3>Messages in ({_n(f['messages_in_total'])})</h3>" + _table(["from", "place", "written in", "at"], rows))
    rows = [[_e(_short(m["to"])), f'<span class="mono">{_e(m["channel"])}</span>', _e(m["read_id"]), _e(m.get("read_time") or "–")]
            for m in f.get("messages_out", [])]
    if rows:
        out.append(f"<h3>Messages out ({_n(f['messages_out_total'])})</h3>" + _table(["to", "place", "read in", "at"], rows))
    return "".join(out)


def _render_actor(f):
    nums = [["actions", f.get("actions")], ["dated actions", f.get("timed_actions")], ["harmful actions", f.get("harmful")],
            ["records", f.get("records")], ["messages sent", f.get("sent")], ["messages received", f.get("received")],
            ["partners", f.get("partners")], ["places", f.get("places_total")], ["programs started", f.get("programs_started_total")],
            ["programs reused", f.get("programs_adopted_total")]]
    out = [f'<p class="meta">{_e(f.get("kind"))} · active {_e(f.get("first") or "no time")} to {_e(f.get("last") or "")} UTC'
           f'{" · <span class=warn>shared key: stands for many agents</span>" if f.get("shared") else ""}</p>',
           '<div class="kpis">' + "".join(f'<div class="kpi"><b>{_n(v)}</b><span>{_e(k)}</span></div>' for k, v in nums) + "</div>"]
    if f.get("intents"):
        out.append('<p class="small">What its actions do: ' + _e("; ".join(f"{i['what']} ({i['n']:,})" for i in f["intents"])) + "</p>")
    out.append('<table><tr><th>sends messages to</th><th>hears from</th></tr><tr><td>' +
               ("<br>".join(f"{_e(_short(x['actor']))} <span class=muted>{x['n']:,}</span>" for x in f.get("sends_to", [])) or "nobody") +
               "</td><td>" + ("<br>".join(f"{_e(_short(x['actor']))} <span class=muted>{x['n']:,}</span>" for x in f.get("hears_from", [])) or "nobody") +
               "</td></tr></table>")
    if f.get("signals"):
        out.append("<h3>Warning signs it fired</h3>" + _table(["sign", "time (UTC)", "harm still to come", "why"],
                   [[_e(g["name"]), _e(g["time"]), _pct(g["harm_share_after"]), _e(g["why"])] for g in f["signals"]]))
    return "".join(out)


def _render_place(f):
    out = [f'<p class="meta">{_e(f.get("type"))} · {_n(f.get("writes"))} writes, {_n(f.get("reads"))} reads, '
           f'{_n(f.get("messages_total"))} messages, {_n(f.get("overwrites"))} overwrites'
           f'{" · <span class=warn>may merge several places</span>" if f.get("merged") else ""}</p>',
           '<table><tr><th>writers (' + _n(f.get("writers_total")) + ')</th><th>readers (' + _n(f.get("readers_total")) + ')</th></tr><tr><td>' +
           ("<br>".join(f"{_e(_short(x['actor']))} <span class=muted>{x['n']:,}</span>" for x in f.get("writers", [])) or "none") + "</td><td>" +
           ("<br>".join(f"{_e(_short(x['actor']))} <span class=muted>{x['n']:,}</span>" for x in f.get("readers", [])) or "none") + "</td></tr></table>"]
    if f.get("messages"):
        out.append(f"<h3>Messages through it ({_n(f['messages_total'])})</h3>" + _table(
            ["from", "written in", "to", "read in", "read at"],
            [[_e(_short(m["from"])), _e(m["write_id"]), _e(_short(m["to"])), _e(m["read_id"]), _e(m.get("read_time") or "–")] for m in f["messages"]]))
    return "".join(out)


def _render_conversation(f):
    out = [f'<p class="meta">{_n(f.get("total"))} items · {_n(f.get("a_to_b"))} messages {_e(_short(f["a"]))} → {_e(_short(f["b"]))}, '
           f'{_n(f.get("b_to_a"))} back · {_e(f.get("first") or "")} to {_e(f.get("last") or "")}</p>']
    if f.get("items"):
        out.append(_table(["from", "to", "place", "written in", "read in", "read at"],
                          [[_e(_short(i["from"])), _e(_short(i["to"])), f'<span class="mono">{_e(i["channel"])}</span>', _e(i["write_id"]),
                            _e(i["read_id"]), _e(i.get("read_time") or "–")] for i in f["items"]]))
    return "".join(out)


RENDER = {"record": _render_record, "actor": _render_actor, "place": _render_place, "conversation": _render_conversation}


def _label(kind, key):
    if kind == "conversation":
        a, _, b = key.partition("|")
        return f"{_short(a)} ↔ {_short(b)}"
    return _short(key) if kind == "actor" else key


def render_html(d):
    parts = [f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>{_e(d['title'])}</title><style>{CSS}</style></head><body><main>",
             f"<h1>{_e(d['title'])}</h1>",
             f"<p class='meta'>Dataset <b>{_e(d['dataset'])}</b> · pack {_e(d['pack'])} · exported {_e(d['date'])} from Swarm Tracer</p>"]
    if d.get("notes", "").strip():
        parts.append(f"<h2>The investigator's notes</h2><div class='notes'>{_e(d['notes'])}</div>")
    parts.append("<h2>Key numbers of the dataset</h2><div class='kpis'>" +
                 "".join(f"<div class='kpi'><b>{_n(v)}</b><span>{_e(k)}</span></div>" for k, v in d["key_numbers"]) + "</div>")
    items = d["items"]
    parts.append(f"<h2>Pinned items ({len(items)})</h2>")
    if not items:
        parts.append("<p class='muted'>Nothing pinned yet.</p>")
    for kind in KINDS:
        group = [it for it in items if it["kind"] == kind]
        if not group:
            continue
        parts.append(f"<p class='small muted' style='margin:14px 0 6px'>{KIND_TITLE[kind]} ({len(group)})</p>")
        for it in group:
            f = it["facts"]
            head = f"<h3><span class='kind k-{kind}'>{kind}</span>{_e(_label(kind, it['key']))}"
            if it.get("link"):
                head += f" <a class='small' href='{_e(it['link'])}'>open in the app</a>"
            head += "</h3>"
            body = (f"<p class='warn small'>Not in this dataset any more{': ' + _e(f.get('error')) if f.get('error') else ''}.</p>"
                    if f.get("missing") else RENDER[kind](f))
            note = f"<div class='note'>{_e(it['note'])}</div>" if it.get("note", "").strip() else ""
            parts.append(f"<div class='item'>{head}{note}{body}<p class='small muted'>pinned {_e(it.get('added') or '')}</p></div>")
    sigs = d["warning_signs"]
    parts.append(f"<h2>Warning signs ({len(sigs)})</h2>")
    parts.append(_table(["sign", "time (UTC)", "harm still to come", "why"],
                        [[_e(g["name"]), _e(g["time"]), _pct(g["harm_share_after"]), _e(g["why"])] for g in sigs]))
    if d.get("precision") and d["precision"]["rows"]:
        p = d["precision"]
        parts.append(f"<h2>Precision from the investigator's labels ({p['labels']:,} labels)</h2>")
        parts.append(_table(["pattern", "right", "wrong", "can't tell", "precision", "95% range"],
                            [[_e(r["tag"]), _n(r["tp"]), _n(r["fp"]), _n(r["unclear"]), _pct(r["precision"]),
                              f"{_pct(r['ci_low'])}–{_pct(r['ci_high'])}" if r["precision"] is not None else "–"] for r in p["rows"]]))
    parts.append("<p class='small muted' style='margin-top:28px'>Every number above is counted from the dataset by Swarm Tracer. "
                 "Estimated times carry the range their dating fit allows. Record text is written by the agents and shown as data.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)


# ------------------------------------------------------------------ labels

def get_labels(state, q):
    s = _session(state)
    rid = q.get("id", "")
    rows = labels.read_labels(labels_path(s))
    mine = {}
    for r in rows:
        if r.get("id") == rid or (r.get("tag") == "message" and rid and rid in (r.get("id") or "").split(">")):
            mine[r["tag"] + "\u0000" + r["id"]] = r.get("label")
    return {"id": rid, "labels": [{"tag": k.split("\u0000")[0], "id": k.split("\u0000")[1], "label": v} for k, v in mine.items()],
            "total": len(rows), "path": labels_path(s)}


def post_label(state, q, body):
    s = _session(state)
    try:
        b = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("send JSON: {id, tag, label}")
    rid, tag = str(b.get("id") or ""), str(b.get("tag") or "")
    if not rid or not tag:
        raise ValueError("a label needs an id and a tag")
    ids = rid.split(">") if tag == "message" else [rid]
    if any(i not in s.by_id for i in ids):
        raise LookupError(f"no record {rid}")
    preview = b.get("preview") or (s.by_id[ids[-1]].text if ids else "")
    n = labels.set_label(labels_path(s), rid, tag, b.get("label"), preview, _now())
    return {"ok": True, "total": n, "precision": precision_table(s)}


def precision_table(s):
    path = labels_path(s)
    rows = labels.read_labels(path)
    if not rows:
        return {"labels": 0, "rows": [], "path": path}
    p = labels.precision(path)
    out = [{"tag": t, **v} for t, v in p["tags"].items()]
    out.sort(key=lambda r: (-r["n"], r["tag"]))
    return {"labels": len(rows), "judged": sum(r["judged"] for r in out), "rows": out, "path": path}


def get_precision(state, q):
    return precision_table(_session(state))


# ------------------------------------------------------------------ ground truth

def _source(s):
    return getattr(s, "path", None) or getattr(s, "source_path", None) or getattr(s, "_cw_source", None)


SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def find_truth(state, s):
    t = state.get("cw_truth")
    if t and t.get("dataset") == s.name:
        return t["truth"], t["where"]
    cands = []
    p = groundtruth.truth_path_for(_source(s))
    if p:
        cands.append(p)
    if os.path.isdir(SAMPLES):
        for d in sorted(os.listdir(SAMPLES)):
            q = groundtruth.truth_path_for(os.path.join(SAMPLES, d))
            if q and q not in cands:
                cands.append(q)
    for p in cands:
        try:
            tr = groundtruth.load_truth(p)
        except (OSError, ValueError):
            continue
        if groundtruth.matches(tr, s):
            return tr, p
    return None, None


def get_groundtruth_score(state, q):
    s = _session(state)
    cache = getattr(s, "_cw_gt", None)
    if cache is not None and cache[0] == id(state.get("cw_truth")):
        return cache[1]
    truth, where = find_truth(state, s)
    if truth is None:
        out = {"available": False, "why": "No ground-truth file matches this dataset. Make one with "
               "python3 -m agenttrace.groundtruth make out/, load out/trace.jsonl, or send its truth file here."}
    else:
        out = {"available": True, "truth_file": os.path.basename(where), **groundtruth.score(s, truth)}
    s._cw_gt = (id(state.get("cw_truth")), out)
    return out


def post_groundtruth_truth(state, q, body):
    s = _session(state)
    try:
        truth = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("the truth file is not valid JSON")
    if not isinstance(truth, dict) or "messages" not in truth or "records" not in truth:
        raise ValueError("not a ground-truth file (needs records and messages)")
    if not groundtruth.matches(truth, s):
        raise ValueError("this truth file describes other records than the loaded dataset")
    state["cw_truth"] = {"dataset": s.name, "truth": truth, "where": q.get("filename") or "uploaded truth file"}
    return get_groundtruth_score(state, q)


# remember where each dataset was loaded from, so a truth file next to it can be found
def _remember_source():
    try:
        from .session import Session
    except Exception:
        return
    if getattr(Session.load, "_cw_wrapped", False):
        return
    orig = Session.load

    def load(self, path, *a, **k):
        self._cw_source = path
        return orig(self, path, *a, **k)
    load._cw_wrapped = True
    Session.load = load


_remember_source()

GET = {"case": get_case, "case_export": get_case_export, "time_range": get_time_range, "labels": get_labels,
       "precision": get_precision, "groundtruth_score": get_groundtruth_score}
POST = {"case": post_case, "label": post_label, "groundtruth_truth": post_groundtruth_truth}

"""The message board, rebuilt: what the release lets us see of the Artifactory board.

The payloads name board folders (github-remote-cache/zz...), a write when the request creates or puts
one (MKCOL, PUT), a read when it fetches one. The folder's contents are not in the release, only that
it was touched. This module takes the pack's "board" channel operations (messages.channel_ops, judged
by messages.judge_span) and rebuilds, from the folder names and the order of operations:

1. Links. A read is linked to the latest earlier write of the same folder by another actor
   (messages.deliveries). The writer need not be named: each side is classed with
   attribution.resolve as "token" (named in the trace, or a handle named in the text),
   "probable" (an anonymous run linked to a named agent; the band is kept) or "anonymous".
2. A message-type vocabulary decoded from the folder names. Types are derived by looking at the real
   names (names are upper-case after "zz"; digits are partly masked by redaction), first rule that
   matches the name after "zz" wins:
     file      FILE_ prefix, F_ prefix, or FILE / CHUNK / PART<n> inside the name: file sharing
               (typically zzFILE_<target>_<what>_V<n>, a versioned file or one chunk of it)
     mailbox   MAILBOX / INBOX / MAIL: a personal mailbox
     command   CMD / LOCK / HOLD / VETO / STOP / OWNER / CTRL: control and coordination
     result    RESULT / ANSWER / DONE / MODOUT / RESP / OUTPUT / REPORT: an outcome
     beacon    BEACON / PING / MARK / HELLO / HB / ALIVE / STARTED: a liveness or progress mark
     probe     TEST / PROBE / DIAG / BROWSE / MKCOL / CORS / CHECK: a trial that the board works
     stage     STAGE / CALLBACK / FROMMODAL: a hand-over step of an exploit chain
     modal     MODAL, or MODT<n> / MODC / MODU / MODSCRIPT / MOU: traffic about the Modal sandbox
     channel   C2 / CHAN / C_ prefix, or REPO / BDIR / PASTE / SYNC / OPS: an agent's own named channel
     payload   DATA_ prefix, or PAYLOAD / PAY / DATA / DONOR / CFG / PUSH / NEXUS / SRC / TMP / URI /
               COMMIT / STORE / ASSET / WATCH / UPLOAD / CODE: a blob handed over
     other     everything else (kept visible: the share is reported and the names listed)
   A name can also carry a version (_V<n>): folders with the same stem and several versions are
   counted as revisions of one thing.
3. The share of the board the release shows: folders with a write seen, with a read seen, with both,
   and with a linked delivery. This is a floor on what the payloads show, never an estimate of the
   total: OpenAI's own counts (read from claims/incident_context.json at runtime) are in other units.
4. The protocol timeline: first appearance of each type, and operations per type per hour.
"""
import json
import os
import re
import time
from collections import Counter, defaultdict

from .messages import deliveries
from .reconstruct import iso

CHANNEL = "board"
PREFIX = CHANNEL + ":"
SNIP = 160

# (type, label, regex on the upper-cased name after "zz", what it means)
RULES = [
    ("file", "File sharing", r"^(?:FILE|F)_|FILE|CHUNK|PART\d", "a file or one chunk of it"),
    ("mailbox", "Mailbox", r"MAILBOX|INBOX|^MAIL", "a personal mailbox"),
    ("command", "Command / lock", r"CMD|LOCK|HOLD|VETO|STOP|OWNER|CTRL", "control and coordination"),
    ("result", "Result", r"RESULT|ANSWER|^DONE|MODOUT|RESP|OUTPUT|REPORT", "an outcome handed back"),
    ("beacon", "Beacon", r"BEACON|PING|MARK|HELLO|^HB|ALIVE|STARTED", "a liveness or progress mark"),
    ("probe", "Probe", r"TEST|PROBE|DIAG|BROWSE|MKCOL|CORS|CHECK", "a trial that the board accepts writes"),
    ("stage", "Stage / callback", r"STAGE|CALLBACK|^FROMMODAL", "a hand-over step of an exploit chain"),
    ("modal", "Modal sandbox", r"MODAL|^MOD[TCU]\d|^MODSCRIPT|^MOU\d", "traffic about the Modal sandbox"),
    ("channel", "Own channel", r"^(?:C2|CHAN|C)_|^C\d*CHAN|REPO|BDIR|PASTE|SYNC|OPS", "an agent's own named channel"),
    ("payload", "Payload / data", r"^DATA_|PAYLOAD|PAY|DATA|DONOR|CFG|PUSH|NEXUS|SRC|TMP|URI|COMMIT|STORE|ASSET|WATCH|UPLOAD|^CODE_",
     "a blob or configuration handed over"),
]
RULE_RX = [(t, re.compile(p)) for t, _l, p, _w in RULES]
LABEL = {t: l for t, l, _p, _w in RULES}
LABEL["other"] = "Other"
MEANING = {t: w for t, _l, _p, w in RULES}
MEANING["other"] = "names no rule recognises"
ORDER = [t for t, *_ in RULES] + ["other"]
CLASSES = ("token", "probable", "anonymous")
VERSION = re.compile(r"_V(\d+)(?=[^0-9]|$)", re.I)


def folder_type(name):
    """Message type of a board folder name (with or without the board: prefix)."""
    b = (name[len(PREFIX):] if name.startswith(PREFIX) else name)
    b = (b[2:] if b[:2].lower() == "zz" else b).upper()
    for t, rx in RULE_RX:
        if rx.search(b):
            return t
    return "other"


def stem(name):
    """Name without its version and trailing digits: the thing a revision series is about."""
    b = name[len(PREFIX):] if name.startswith(PREFIX) else name
    return re.sub(r"[_\d]+$", "", VERSION.sub("", b))


def _resolve(s):
    try:
        from . import attribution
        return attribution.resolve(s) or {}
    except Exception:       # attribution is optional here: without it every unnamed side is anonymous
        return {}


def side(op, res):
    """(class, actor, band) of one operation: token (named), probable (linked run) or anonymous."""
    _ch, _op, actor, kind, _t, _i, rid = op
    if kind in ("token", "handle") and actor:
        return "token", actor, "named"
    r = res.get(rid) or {}
    if r.get("actor") and r.get("band") in ("high", "medium", "low"):
        return "probable", r["actor"], r["band"]
    if r.get("actor") and r.get("band") == "named":
        return "token", r["actor"], "named"
    return "anonymous", actor, None


def _hour(t):
    return None if t is None else int(t // 3600) * 3600


def _claims():
    """What OpenAI/METR say about the board's size, quoted from the claims file at run time."""
    out = {"quotes": [], "entries": None, "files": None, "share_pct": None, "source": None}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims", "incident_context.json")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return out
    seen = set()

    def walk(x):
        if isinstance(x, dict):
            w = x.get("what")
            if isinstance(w, str) and re.search(r"95% of the Artifactory|5,855", w) and w not in seen:
                seen.add(w)
                out["quotes"].append({"name": x.get("name"), "text": w, "source": x.get("source")})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc)
    for q in out["quotes"]:
        m = re.search(r"at least ([\d,]+) files across ([\d,]+) entries", q["text"])
        if m:
            out["files"], out["entries"] = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
        m = re.search(r"at least (\d+)% of the Artifactory messaging", q["text"])
        if m:
            out["share_pct"] = int(m.group(1))
    return out


def _snippet(s, rid, folder):
    rec = s.by_id.get(rid)
    text = getattr(rec, "text", "") or ""
    i = text.find(folder)
    if i < 0:
        i = text.lower().find(folder.lower())
    if i < 0:
        i = 0
    lo = max(0, i - 60)
    sn = " ".join(text[lo:lo + SNIP + 20].split())
    return sn[:SNIP]


def _state(s):
    """Everything per-folder, computed once per session: ops with sides, links, types."""
    c = getattr(s, "_board_state", None)
    if c is not None:
        return c
    res = _resolve(s)
    ops = [o for o in s.op_list if o[0].startswith(PREFIX)]
    by = defaultdict(list)
    for o in ops:
        by[o[0]].append(o)
    links = deliveries(ops)[0]
    by_folder_links = defaultdict(list)
    for d in links:
        by_folder_links[d["channel"]].append(d)
    sides = {}
    for o in ops:
        sides[(o[0], o[1], o[6], o[5])] = side(o, res)
    c = {"res": res, "ops": ops, "by": by, "links": links, "flinks": by_folder_links, "sides": sides}
    s._board_state = c
    return c


def _sd(st, o):
    return st["sides"][(o[0], o[1], o[6], o[5])]


def _top(counter, k=3):
    return [{"actor": a, "n": n} for a, n in counter.most_common(k) if a]


def board(s):
    c = getattr(s, "_board_summary", None)
    if c is not None:
        return c
    t0 = time.time()
    st = _state(s)
    by, ops, links = st["by"], st["ops"], st["links"]
    names = sorted(by)
    ftype = {n: folder_type(n) for n in names}
    for_type = defaultdict(list)
    for n in names:
        for_type[ftype[n]].append(n)

    # funnel
    written = {n for n in names if any(o[1] == "write" for o in by[n])}
    read = {n for n in names if any(o[1] == "read" for o in by[n])}
    both = written & read
    linked = {d["channel"] for d in links}
    funnel = {"folders": len(names), "written": len(written), "read": len(read), "both": len(both), "linked": len(linked),
              "written_only": len(written - read), "read_only": len(read - written),
              "writes": sum(1 for o in ops if o[1] == "write"), "reads": sum(1 for o in ops if o[1] == "read"),
              "deliveries": len(links)}

    # per type
    types = []
    hours = sorted({_hour(o[4]) for o in ops if o[4] is not None})
    hidx = {h: i for i, h in enumerate(range(hours[0], hours[-1] + 3600, 3600))} if hours else {}
    nh = len(hidx)
    series = {t: {"w": [0] * nh, "r": [0] * nh} for t in ORDER}
    undated = Counter()
    for o in ops:
        t = ftype[o[0]]
        if o[4] is None:
            undated[t] += 1
            continue
        series[t]["w" if o[1] == "write" else "r"][hidx[_hour(o[4])]] += 1
    first_appear = []
    for t in ORDER:
        fl = for_type.get(t, [])
        if not fl:
            continue
        wc, rc = Counter(), Counter()
        wa, ra = Counter(), Counter()
        times, first = [], None
        for n in fl:
            for o in by[n]:
                cl, actor, band = _sd(st, o)
                (wc if o[1] == "write" else rc)[cl] += 1
                if cl != "anonymous":
                    (wa if o[1] == "write" else ra)[actor] += 1
                if o[4] is not None:
                    times.append(o[4])
                    if first is None or o[4] < first[0]:
                        first = (o[4], n, o[6], cl)
        wf = sum(1 for n in fl if n in written)
        rf = sum(1 for n in fl if n in read)
        bf = sum(1 for n in fl if n in both)
        row = {"type": t, "label": LABEL[t], "meaning": MEANING[t], "folders": len(fl),
               "written": wf, "read": rf, "both": bf,
               "writes": sum(wc.values()), "reads": sum(rc.values()),
               "writers": {k: wc.get(k, 0) for k in CLASSES}, "readers": {k: rc.get(k, 0) for k in CLASSES},
               "top_writers": _top(wa), "top_readers": _top(ra),
               "first": iso(min(times)) if times else None, "last": iso(max(times)) if times else None,
               "undated_ops": undated.get(t, 0),
               "examples": [n[len(PREFIX):] for n in sorted(fl, key=lambda n: -len(by[n]))[:3]]}
        types.append(row)
        if first:
            first_appear.append({"type": t, "label": LABEL[t], "time": iso(first[0]), "t": first[0], "folder": first[1][len(PREFIX):],
                                 "record": first[2], "class": first[3]})
    first_appear.sort(key=lambda x: x["t"])
    for f in first_appear:
        del f["t"]
    types.sort(key=lambda r: -r["folders"])

    # flow units: a delivery, a write nobody is seen to read, a read with no earlier write seen
    flow = Counter()
    linked_w, linked_r = set(), set()
    same_agent = 0
    ops_key = {(o[6], o[0], o[1]): o for o in ops}
    for d in links:
        wo, ro = ops_key.get((d["write_id"], d["channel"], "write")), ops_key.get((d["read_id"], d["channel"], "read"))
        if not wo or not ro:
            continue
        wc_, wa_, _ = _sd(st, wo)
        rc_, ra_, _ = _sd(st, ro)
        flow[(wc_, ftype[d["channel"]], rc_)] += 1
        linked_w.add((wo[0], wo[6]))
        linked_r.add((ro[0], ro[6], ro[5]))
        if wc_ != "anonymous" and rc_ != "anonymous" and wa_ == ra_:
            same_agent += 1
    unread = repeat_reads = undated_reads = 0
    for n in names:
        ws = [o for o in by[n] if o[1] == "write"]
        for o in ws:
            if (o[0], o[6]) not in linked_w:
                flow[(_sd(st, o)[0], ftype[n], "none")] += 1
                unread += 1
        for o in by[n]:
            if o[1] != "read" or (o[0], o[6], o[5]) in linked_r:
                continue
            if o[4] is None:
                undated_reads += 1
            elif any(w[4] is not None and w[4] <= o[4] and w[2] != o[2] and w[6] != o[6] for w in ws):
                repeat_reads += 1
            else:
                flow[("none", ftype[n], _sd(st, o)[0])] += 1
    flow_rows = [{"l": a, "t": t, "r": b, "n": n} for (a, t, b), n in sorted(flow.items(), key=lambda kv: -kv[1])]

    # busiest folders
    top = []
    for n in sorted(names, key=lambda n: (-len(by[n]), n))[:25]:
        lst = by[n]
        wcl = Counter(_sd(st, o)[0] for o in lst if o[1] == "write")
        rcl = Counter(_sd(st, o)[0] for o in lst if o[1] == "read")
        ts = [o[4] for o in lst if o[4] is not None]
        fw = next((o[6] for o in sorted(lst, key=lambda o: (o[4] is None, o[4] or 0)) if o[1] == "write"), None)
        fr = next((o[6] for o in sorted(lst, key=lambda o: (o[4] is None, o[4] or 0)) if o[1] == "read"), None)
        top.append({"folder": n[len(PREFIX):], "channel": n, "type": ftype[n], "writes": sum(wcl.values()), "reads": sum(rcl.values()),
                    "writers": dict(wcl), "readers": dict(rcl), "deliveries": len(st["flinks"].get(n, [])),
                    "first": iso(min(ts)) if ts else None, "last": iso(max(ts)) if ts else None, "first_write": fw, "first_read": fr})

    other = for_type.get("other", [])
    stems = defaultdict(set)
    for n in names:
        m = VERSION.search(n)
        if m:
            stems[stem(n)].add(int(m.group(1)))
    claims = _claims()
    both_n = len(both)
    cl = claims
    visible = {
        "named_folders": len(names), "complete_exchange_folders": both_n,
        "complete_share_of_visible": round(both_n / len(names), 4) if names else None,
        "file_folders": len(for_type.get("file", [])),
        "claim_files": cl["files"], "claim_entries": cl["entries"], "claim_share_pct": cl["share_pct"],
        "file_folders_vs_claim_files": round(len(for_type.get("file", [])) / cl["files"], 4) if cl["files"] else None,
        "folders_vs_claim_entries": round(len(names) / cl["entries"], 6) if cl["entries"] else None,
    }
    caveats = [
        "The release holds payloads that touched board folders, not the board's contents. A folder is seen as written or read only when a payload shows the request; a write seen with no read seen does not mean nobody read it.",
        "A link is a read after a write of the same folder by another actor: it shows the reader could have seen the folder, not that it read the content. Folders hold many entries; a name is not a message.",
        "The share above is a floor on what the release shows, counted in folders. It cannot be scaled to the total: OpenAI counts entries and files, not folders, and its 95% figure is a share of Artifactory messaging in the main namespace, which says nothing about how much of that the release samples.",
        "Writers and readers are mostly anonymous runs (one record each). A probable agent is a link by shared rare material with a stated confidence band, not an identity.",
        "Types are read off the folder names by the rules in agenttrace/board.py. A name can fit several; the first rule wins. Redaction masks some digits, so names that look alike may differ.",
    ]
    out = {
        "seconds": None, "funnel": funnel, "types": types, "type_order": [t["type"] for t in types],
        "labels": {t: LABEL[t] for t in ORDER}, "rules": [{"type": t, "label": l, "pattern": p, "meaning": w} for t, l, p, w in RULES],
        "other": {"folders": len(other), "share": round(len(other) / len(names), 4) if names else 0, "names": [n[len(PREFIX):] for n in other[:40]]},
        "hours": [iso(h) for h in sorted(hidx)], "series": {t: v for t, v in series.items() if for_type.get(t)},
        "undated_ops": sum(undated.values()),
        "flow": {"rows": flow_rows, "unread_writes": unread, "reads_no_writer": sum(r["n"] for r in flow_rows if r["l"] == "none"),
                 "repeat_reads": repeat_reads, "undated_reads": undated_reads, "same_agent_links": same_agent, "deliveries": len(links)},
        "top_folders": top, "first_appearances": first_appear,
        "naming": {"versioned": sum(1 for n in names if VERSION.search(n)), "stems_with_revisions": sum(1 for v in stems.values() if len(v) > 1),
                   "max_version": max((max(v) for v in stems.values()), default=None)},
        "visible": visible, "claims": cl, "caveats": caveats,
        "sides": dict(Counter(_sd(st, o)[0] for o in ops)),
        "attribution": bool(st["res"]),
    }
    out["seconds"] = round(time.time() - t0, 1)
    s._board_summary = out
    return out


def folder(s, name):
    st = _state(s)
    key = name if name.startswith(PREFIX) else PREFIX + name
    if key not in st["by"]:
        low = key.lower()
        key = next((k for k in st["by"] if k.lower() == low), None)
    if key is None:
        raise LookupError("no such board folder: " + name[:80])
    ops = sorted(st["by"][key], key=lambda o: (o[4] is None, o[4] or 0, o[5]))
    short = key[len(PREFIX):]
    rows = []
    for o in ops:
        cl, actor, band = _sd(st, o)
        rows.append({"time": iso(o[4]), "op": o[1], "record": o[6], "actor": actor, "class": cl, "band": band,
                     "snippet": _snippet(s, o[6], short)})
    dl = [{"from": d["from"], "to": d["to"], "write_id": d["write_id"], "read_id": d["read_id"], "write_time": iso(d["write_time"]),
           "read_time": iso(d["read_time"]), "latency_h": d["latency_h"], "how": d["how"],
           "from_class": _cls(st, d["write_id"], key, "write"), "to_class": _cls(st, d["read_id"], key, "read")}
          for d in st["flinks"].get(key, [])]
    sibs = sorted(n[len(PREFIX):] for n in st["by"] if n != key and stem(n) == stem(key) and VERSION.search(n))[:20]
    t = folder_type(key)
    return {"folder": short, "channel": key, "type": t, "label": LABEL[t], "meaning": MEANING[t],
            "writes": sum(1 for r in rows if r["op"] == "write"), "reads": sum(1 for r in rows if r["op"] == "read"),
            "ops": rows[:300], "ops_total": len(rows), "deliveries": dl[:100], "deliveries_total": len(dl), "revisions": sibs}


def _cls(st, rid, key, op):
    for o in st["by"][key]:
        if o[6] == rid and o[1] == op:
            return _sd(st, o)[0]
    return "anonymous"


def _need(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _get_board(state, q):
    return board(_need(state))


def _get_folder(state, q):
    n = (q.get("name") or "").strip()
    if not n:
        raise ValueError("name is required (a folder such as zzFILE_X_V1)")
    return folder(_need(state), n)


GET = {"board": _get_board, "board_folder": _get_folder}
POST = {}

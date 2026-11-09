"""Live mode (follow a growing trace) and saved alert rules.

Live mode
    POST /api/x/live_start {path, pack, interval_s, map, reanalyze_s}   watch a file or folder on this machine
    GET  /api/x/live_status?since=SEQ                       watching?, last load, records, events after SEQ
    POST /api/x/live_stop
A background thread checks the path's size and modification time.

A single JSON-lines file is read incrementally: each check reads only the bytes after the last
offset, up to the last complete line (a half-written record waits for its newline), parses the new
lines and appends them to the rows read so far. A file that shrank, was replaced (another inode) or
whose first bytes changed was truncated or rotated: it is read again from the start. A file that
stops being valid UTF-8 or turns out to be one JSON array falls back to full reloads.
The analysis itself (pack, threads, identities, messages, signs) looks at the whole trace, so it is
recomputed over all rows, but without reading or parsing the file again, and at most once every
reanalyze_s seconds (default "auto": on every change while an analysis takes under half a second,
else at most every four times the last analysis took, at least the watch interval, at most 5 min;
the live status says how many new records are waiting for it and when it runs next). The facts and rule results of the previous
analysis are kept, so each analysis evaluates the rules once instead of twice.
Folders and other formats are analyzed again in a fresh Session on every change (a single file is
first copied up to its last complete line). Either way the app's dataset is swapped only when the
analysis succeeds.
Each load is compared with the previous one and the differences go to an event log: new records,
new named actors, new messages, every warning sign that is new, and every alert rule that fired
for the first time.

Alert rules
    GET  /api/x/rules            the saved rules (or the defaults)
    POST /api/x/rules            {rules: [...]} saves them; {reset: true} restores the defaults
    GET  /api/x/rules_eval       when each rule first fires on the loaded dataset
Rules are stored as JSON at ~/.swarm-tracer/rules.json (SWARM_TRACER_RULES overrides the path).
A rule is a name, a severity and conditions over the warning signs that insight.simulate finds;
it fires at the moment all its conditions hold (or the first one, with match "any").
"""
import bisect
import json
import os
import re
import shutil
import tempfile
import threading
import time
import traceback
from collections import Counter

from . import insight, model, packs, reconstruct
from .session import PACK_DIR, Session

iso = reconstruct.iso
HOUR = 3600.0

# ------------------------------------------------------------------ rules

SEVERITIES = ("info", "watch", "alert")
COND_TYPES = {
    "sign": "a warning sign of the chosen families and kinds has fired",
    "coordination_kinds": "at least N different kinds of coordination sign have fired",
    "harm_rate": "at least N harmful actions within one hour",
    "messages_between": "at least N messages between the named actors (either direction)",
    "group_size": "a group of at least N actors linked by messages (optionally containing a named actor)",
}
# the default rules reproduce the early-flag tab's rule; they were written while looking at the
# datasets these packs were made for, so on those datasets their timing is hindsight, not a test
HINDSIGHT_PACK_FILES = ("code_traces.json", "wiki_swarm.json")

DEFAULT_RULES = [
    {"id": "watch-harm", "name": "Watch: first single-actor harmful sign", "severity": "watch", "enabled": True,
     "match": "all", "conditions": [{"type": "sign", "families": ["single"], "kinds": ["harm"]}], "default": True},
    {"id": "alert-coord2", "name": "Alert: 2 kinds of coordination", "severity": "alert", "enabled": True,
     "match": "all", "conditions": [{"type": "coordination_kinds", "n": 2}], "default": True},
    {"id": "baseline-volume", "name": "Volume baseline: ordinary volume alarm", "severity": "info", "enabled": True,
     "match": "all", "conditions": [{"type": "sign", "families": ["baseline"], "kinds": []}], "default": True},
]


def rules_path():
    return os.environ.get("SWARM_TRACER_RULES") or os.path.join(os.path.expanduser("~"), ".swarm-tracer", "rules.json")


def _num(v, name, lo=0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if x < lo:
        raise ValueError(f"{name} must be at least {lo}")
    return int(x) if x == int(x) else x


def _strs(v):
    if v is None or v == "":
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        raise ValueError("expected a list of names")
    return [str(x).strip() for x in v if str(x).strip()]


def clean_rule(r, i=0):
    """Validate one rule and return it in canonical form (raises ValueError)."""
    if not isinstance(r, dict):
        raise ValueError("each rule must be an object")
    name = str(r.get("name") or "").strip()
    if not name:
        raise ValueError(f"rule {i + 1} has no name")
    sev = r.get("severity") or "alert"
    if sev not in SEVERITIES:
        raise ValueError(f"rule '{name}': severity must be one of {', '.join(SEVERITIES)}")
    conds = r.get("conditions") or []
    if not isinstance(conds, list) or not conds:
        raise ValueError(f"rule '{name}' needs at least one condition")
    out = []
    for c in conds:
        if not isinstance(c, dict) or c.get("type") not in COND_TYPES:
            raise ValueError(f"rule '{name}': condition type must be one of {', '.join(COND_TYPES)}")
        t = c["type"]
        if t == "sign":
            out.append({"type": t, "families": _strs(c.get("families")), "kinds": _strs(c.get("kinds"))})
        elif t == "coordination_kinds":
            out.append({"type": t, "n": _num(c.get("n", 2), "number of kinds", 1)})
        elif t == "harm_rate":
            out.append({"type": t, "per_hour": _num(c.get("per_hour", 10), "harmful actions per hour", 1)})
        elif t == "messages_between":
            out.append({"type": t, "a": str(c.get("a") or "").strip(), "b": str(c.get("b") or "").strip(),
                        "n": _num(c.get("n", 1), "number of messages", 1)})
        elif t == "group_size":
            out.append({"type": t, "size": _num(c.get("size", 3), "group size", 2), "actor": str(c.get("actor") or "").strip()})
    rid = re.sub(r"[^a-z0-9-]+", "-", str(r.get("id") or name).lower()).strip("-")[:60] or f"rule-{i + 1}"
    rule = {"id": rid, "name": name[:120], "severity": sev, "enabled": r.get("enabled", True) is not False,
            "match": "any" if r.get("match") == "any" else "all", "conditions": out}
    if r.get("default"):
        rule["default"] = True
    if r.get("written_on"):
        rule["written_on"] = _strs(r.get("written_on"))[:20]
    return rule


def clean_rules(rules):
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    out, ids = [], set()
    for i, r in enumerate(rules):
        c = clean_rule(r, i)
        base, k = c["id"], 2
        while c["id"] in ids:
            c["id"] = f"{base}-{k}"
            k += 1
        ids.add(c["id"])
        out.append(c)
    return out


def load_rules():
    p = rules_path()
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return clean_rules(data.get("rules", data) if isinstance(data, dict) else data), True
        except (OSError, ValueError):
            pass
    return json.loads(json.dumps(DEFAULT_RULES)), False


def save_rules(rules, dataset=None):
    rules = clean_rules(rules)
    old = {r["id"]: r for r in load_rules()[0]}
    for r in rules:
        # remember which dataset was loaded when a rule was written or changed: its timing there is hindsight
        if dataset and (r["id"] not in old or _core(old[r["id"]]) != _core(r)):
            r["written_on"] = sorted(set(r.get("written_on", [])) | {dataset})
            r.pop("default", None)
    p = rules_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rules": rules}, f, indent=2)
    os.replace(tmp, p)
    return rules


def _core(r):
    return json.dumps({k: r.get(k) for k in ("name", "severity", "match", "conditions", "enabled")}, sort_keys=True)


def _named_deliveries(s):
    """Messages between named actors on exact places, in time order (as the replay counts them)."""
    cached = getattr(s, "_live_named", None)
    if cached is None:
        coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
        cached = sorted((d for d in s.flow["_deliveries"]
                         if insight.is_named(d["from"]) and insight.is_named(d["to"]) and d.get("read_time") is not None
                         and not any(r.search(d["channel"]) for r in coarse)), key=lambda d: d["read_time"])
        s._live_named = cached
    return cached


def _hit(t, record, actors, why):
    return {"t": t, "record": record, "actors": [a for a in actors if a], "why": why}


def eval_condition(s, c, sigs):
    t = c["type"]
    if t == "sign":
        fams, kinds = set(c["families"]), set(c["kinds"])
        for g in sigs:
            if (not fams or g["family"] in fams) and (not kinds or g["kind"] in kinds):
                return _hit(g["t"], g.get("record"), g.get("actors", []), f"{g['name']}: {g['why']}")
        return None
    if t == "coordination_kinds":
        kinds = []
        for g in sigs:
            if g["family"] != "joint":
                continue
            if g["kind"] not in kinds:
                kinds.append(g["kind"])
            if len(kinds) >= c["n"]:
                return _hit(g["t"], g.get("record"), g.get("actors", []),
                            f"{len(kinds)} kinds of coordination had shown ({', '.join(kinds)}); the last: {g['name']}")
        return None
    if t == "harm_rate":
        times = s.rec["_times"]
        harm = sorted((times[r], r) for r in s.harmful if r in times)
        n = int(c["per_hour"])
        for i in range(n - 1, len(harm)):
            if harm[i][0] - harm[i - n + 1][0] < HOUR:
                rid = harm[i][1]
                return _hit(harm[i][0], rid, [s.actor[rid][0]], f"{n} harmful actions within one hour, the last in {rid}")
        return None
    if t == "messages_between":
        a, b, n, k = c["a"], c["b"], int(c["n"]), 0
        for d in _named_deliveries(s):
            ends = {d["from"], d["to"]}
            if (not a or a in ends) and (not b or b in ends) and (not (a and b) or ends == {a, b} or a == b):
                k += 1
                if k >= n:
                    who = f"between {a} and {b}" if a and b else f"involving {a or b}" if a or b else "between named actors"
                    return _hit(d["read_time"], d["read_id"], [d["from"], d["to"]],
                                f"message {k} {who}: {d['to']} read what {d['from']} wrote to {d['channel']}")
        return None
    if t == "group_size":
        parent, size = {}, Counter()

        def find(x):
            parent.setdefault(x, x)
            size[x] = size[x] or 1
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        want, actor = int(c["size"]), c["actor"]
        for d in _named_deliveries(s):
            ra, rb = find(d["from"]), find(d["to"])
            if ra != rb:
                parent[ra] = rb
                size[rb] += size[ra]
            r = find(d["to"])
            if size[r] >= want and (not actor or (actor in parent and find(actor) == r)):
                return _hit(d["read_time"], d["read_id"], [d["from"], d["to"]],
                            f"the message from {d['from']} to {d['to']} linked {size[r]} actors into one group"
                            + (f" with {actor}" if actor else ""))
        return None
    return None


def describe_condition(c):
    t = c["type"]
    if t == "sign":
        f = "/".join(c["families"]) or "any family"
        k = "/".join(c["kinds"]) or "any kind"
        return f"a sign of {f}, {k}"
    if t == "coordination_kinds":
        return f"{c['n']}+ kinds of coordination"
    if t == "harm_rate":
        return f"{c['per_hour']}+ harmful actions in an hour"
    if t == "messages_between":
        who = f"{c['a']} and {c['b']}" if c["a"] and c["b"] else (c["a"] or c["b"] or "any named actors")
        return f"{c['n']}+ messages between {who}" if c["a"] and c["b"] else f"{c['n']}+ messages involving {who}"
    if t == "group_size":
        return f"a message-linked group of {c['size']}+ actors" + (f" including {c['actor']}" if c["actor"] else "")
    return t


def _hindsight_packs():
    names = set()
    for f in HINDSIGHT_PACK_FILES:
        try:
            names.add(packs.load_pack(os.path.join(PACK_DIR, f)).name)
        except (SystemExit, OSError, ValueError):
            pass
    return names


def evaluate_rules(s, rules=None):
    rules = rules if rules is not None else load_rules()[0]
    sim = insight.simulate(s)
    sigs = sim["signals"]
    baseline = next((g for g in sigs if g["family"] == "baseline"), None)
    hind_pack = s.pack.name in _hindsight_packs()
    out = []
    for r in rules:
        hits = [eval_condition(s, c, sigs) for c in r["conditions"]]
        conds = [{"what": describe_condition(c), "fired": bool(h), "time": iso(h["t"]) if h else None,
                  "record": h["record"] if h else None} for c, h in zip(r["conditions"], hits)]
        got = [h for h in hits if h]
        fire = None
        if r["match"] == "any" and got:
            fire = min(got, key=lambda h: h["t"])
        elif r["match"] == "all" and got and len(got) == len(hits):
            fire = max(got, key=lambda h: h["t"])
        written = set(r.get("written_on", []))
        hindsight = (bool(r.get("default")) and hind_pack) or (s.name in written)
        row = {"id": r["id"], "name": r["name"], "severity": r["severity"], "enabled": r["enabled"],
               "match": r["match"], "conditions": conds, "fired": bool(fire)}
        if fire:
            row.update({"time": iso(fire["t"]), "t": fire["t"], "record": fire["record"], "actors": fire["actors"],
                        "why": fire["why"], "harm_share_after": insight.harm_share_after(s, fire["t"]),
                        "hours_before_baseline": round((baseline["t"] - fire["t"]) / HOUR, 1) if baseline else None})
        row["hindsight"] = hindsight
        if hindsight:
            row["hindsight_note"] = ("This default rule was written by the tool's authors after studying the incident this "
                                     "pack was built for, so its timing here is hindsight, not a test."
                                     if r.get("default") else
                                     "This rule was written or changed while this dataset was loaded, so its timing here is hindsight, not a test.")
        out.append(row)
    return {"dataset": s.name, "pack": s.pack.name, "harm_total": sim["harm_total"], "signals": len(sigs),
            "dated": bool(sim["start"]), "rules": out,
            "note": None if sim["start"] else "No record in this dataset has a time, so no rule can fire at a moment."}


# ------------------------------------------------------------------ live mode

LIVE_LOCK = threading.Lock()          # one load at a time
LIVE = {"thread": None, "stop": None, "path": None, "pack": "auto", "mapping": {}, "interval": 2.0, "watching": False,
        "started": None, "last_check": None, "last_load": None, "load_s": None, "loading": False, "loads": 0,
        "records": 0, "actors": 0, "messages": 0, "signs": 0, "error": None, "note": None,
        "events": [], "seq": 0, "session": None, "sig": None, "pending": None, "guard": None,
        # incremental reading (single JSON-lines files)
        "inc": None, "incremental": None, "reanalyze_s": None, "reanalyze_auto": True, "pending_records": 0,
        "records_read": 0, "read_offset": 0, "last_analysis": 0.0, "analysis_s": None,
        "facts": None, "rules_now": None, "rules_fp": None}
MAX_EVENTS = 2000


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(type_, text, **kw):
    LIVE["seq"] += 1
    ev = {"seq": LIVE["seq"], "at": _now(), "type": type_, "text": text}
    ev.update({k: v for k, v in kw.items() if v not in (None, [], "")})
    LIVE["events"].append(ev)
    del LIVE["events"][:-MAX_EVENTS]
    return ev


def _signature(path):
    if os.path.isdir(path):
        from .model import DATA_EXTS
        out = []
        for f in sorted(os.listdir(path)):
            if os.path.splitext(f)[1].lower() in DATA_EXTS and not f.startswith("."):
                st = os.stat(os.path.join(path, f))
                out.append((f, st.st_size, st.st_mtime))
        return tuple(out)
    st = os.stat(path)
    return (st.st_size, st.st_mtime)


def _snapshot(path, workdir):
    """Copy a single file up to its last complete line, keeping its name (record ids depend on it)."""
    dst = os.path.join(workdir, os.path.basename(path))
    with open(path, "rb") as src, open(dst + ".part", "wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)
    with open(dst + ".part", "rb+") as f:
        f.seek(0, 2)
        size = f.tell()
        back = min(size, 1 << 20)
        f.seek(size - back)
        tail = f.read(back)
        cut = tail.rfind(b"\n")
        if cut >= 0 and cut != back - 1:
            f.truncate(size - back + cut + 1)
    os.replace(dst + ".part", dst)
    return dst


def _facts(s):
    named = {a for a, ak in s.actor.values() if ak != "run"}
    sigs = insight.simulate(s)["signals"]
    return {"ids": set(s.by_id), "actors": named, "messages": len(s.flow["_deliveries"]),
            "pairs": {(d["from"], d["to"]) for d in s.flow["_deliveries"]},
            "signs": {g["key"]: g for g in sigs}}


def _diff(prev, new, s, rules_now, rules_before):
    """Log what changed between two loads (prev None: the first load)."""
    first = prev is None
    if first:
        _log("load", f"Loaded {len(new['ids']):,} records, {len(new['actors']):,} named actors, "
                     f"{new['messages']:,} messages, {len(new['signs']):,} warning signs already present.",
             count=len(new["ids"]))
    else:
        added = [r for r in s.by_id if r not in prev["ids"]]
        if added:
            _log("records", f"{len(added):,} new record{'s' if len(added) != 1 else ''} ({len(new['ids']):,} in all)",
                 records=added[:12], count=len(added))
        na = sorted(new["actors"] - prev["actors"])
        if na:
            _log("actors", f"{len(na)} new named actor{'s' if len(na) != 1 else ''}", actors=na[:12], count=len(na))
        dm = new["messages"] - prev["messages"]
        if dm > 0:
            np_ = sorted(p for p in new["pairs"] - prev["pairs"] if insight.is_named(p[0]) and insight.is_named(p[1]))
            _log("messages", f"{dm:,} new message{'s' if dm != 1 else ''}"
                 + (f", {len(np_)} new pair{'s' if len(np_) != 1 else ''} of named actors" if np_ else ""),
                 actors=sorted({a for p in np_[:6] for a in p}), count=dm)
    for key, g in sorted(new["signs"].items(), key=lambda kv: kv[1]["t"]):
        if first or key not in prev["signs"]:
            _log("sign", g["name"], severity={"joint": "watch", "single": "info", "baseline": "info"}.get(g["family"], "info"),
                 family=g["family"], kind=g["kind"], time=g["time"], record=g.get("record"), actors=g.get("actors"),
                 why=g["why"], harm_share_after=g.get("harm_share_after"), initial=first or None)
    before = {r["id"] for r in rules_before if r["fired"]}
    for r in rules_now:
        if r["fired"] and r["enabled"] and (first or r["id"] not in before):
            _log("alert", r["name"], severity=r["severity"], rule=r["id"], time=r["time"], record=r["record"],
                 actors=r["actors"], why=r["why"], harm_share_after=r.get("harm_share_after"), initial=first or None)


def _load_once(state, rows=None):
    """Analyze the trace again and swap it in. rows: every row of the single file read so far
    (incremental mode), so the file is neither copied nor parsed again."""
    path = LIVE["path"]
    with LIVE_LOCK:
        if not state["lock"].acquire(blocking=False):   # an upload is being analyzed: try again next tick
            return False
        LIVE["loading"] = True
        work = tempfile.mkdtemp(prefix="swarmtracer-live-")
        t0 = time.time()
        try:
            name = os.path.basename(path.rstrip(os.sep)) or path
            sess = Session()
            if rows is not None:
                sess.path = path
                # shallow copies: a framework reader may rewrite the rows it is given
                sess._analyze(path, LIVE["pack"], LIVE["mapping"], name, rows=[dict(r) for r in rows])
            else:
                src = path if os.path.isdir(path) else _snapshot(path, work)
                sess.load(src, LIVE["pack"], LIVE["mapping"], name)
            sess.summary()                                  # warm, so the app's refresh is quick
            if LIVE["pack"] in ("auto", "", None) and sess.pack_choice:
                LIVE["pack"] = sess.pack_choice["pack"]     # keep the pack fixed as the trace grows
                _log("pack", f"Pack chosen from the first {len(sess.events):,} records: {sess.pack.name} "
                             f"({sess.pack_choice['why']}). It stays fixed while live mode runs; pick a pack before "
                             "starting to use another.")
            rules = load_rules()[0]
            fp = json.dumps(rules, sort_keys=True)
            now = evaluate_rules(sess, rules)["rules"]
            prev_s = LIVE["session"]
            prev, before = None, []
            if prev_s is not None:
                # the previous analysis's facts and rule results are kept, not recomputed
                prev = LIVE["facts"] if LIVE.get("facts") is not None else _facts(prev_s)
                before = LIVE["rules_now"] if LIVE.get("rules_fp") == fp and LIVE.get("rules_now") is not None \
                    else evaluate_rules(prev_s, rules)["rules"]
            f = _facts(sess)
            _diff(prev, f, sess, now, before)
            state["session"] = sess
            state["error"] = None
            LIVE["session"] = sess
            took = round(time.time() - t0, 2)
            LIVE.update({"records": sess.summary()["records"], "actors": len(f["actors"]), "messages": f["messages"],
                         "signs": len(f["signs"]), "loads": LIVE["loads"] + 1, "last_load": _now(),
                         "load_s": took, "analysis_s": took, "error": None, "note": None,
                         "facts": f, "rules_now": now, "rules_fp": fp})
        except ValueError as e:
            if "no records" in str(e):
                LIVE["note"] = "waiting for the first records"
            else:
                LIVE["error"] = str(e)
                _log("error", f"Could not analyze the trace: {e}", severity="alert")
        except SystemExit as e:
            LIVE["error"] = str(e)
            _log("error", f"Could not analyze the trace: {e}", severity="alert")
        except Exception as e:      # keep watching; say what went wrong
            traceback.print_exc()
            LIVE["error"] = str(e)
            _log("error", f"Could not analyze the trace: {e}", severity="alert")
        finally:
            LIVE["loading"] = False
            LIVE["last_analysis"] = time.time()
            state["lock"].release()
            shutil.rmtree(work, ignore_errors=True)
        return True


# ------------------------------------------------------------------ incremental reading

INC_EXTS = (".jsonl",)
HEAD_BYTES = 4096
_LINE_SPLIT = re.compile(r"\r\n|\r|\n")


class _Fallback(Exception):
    """This file cannot be read incrementally exactly as model.load would read it."""


def _new_inc(path):
    return {"path": path, "offset": 0, "file_id": None, "head": b"", "rows": [], "line_no": 0,
            "unreadable": 0, "unreadable_lines": [], "pending": 0, "disabled": None}


def _read_new(inc, path):
    """Read the complete lines added since inc["offset"] and append their rows.
    Returns (new rows, reset reason or None)."""
    st = os.stat(path)
    fid = (st.st_dev, st.st_ino)
    reset = None
    if inc["offset"]:
        if inc["file_id"] != fid:
            reset = "replaced by another file"
        elif st.st_size < inc["offset"]:
            reset = "truncated"
        else:
            with open(path, "rb") as f:
                if f.read(len(inc["head"])) != inc["head"]:
                    reset = "rewritten from the start"
    if reset:
        fresh = _new_inc(path)
        inc.clear()
        inc.update(fresh)
    inc["file_id"] = fid
    with open(path, "rb") as f:
        f.seek(inc["offset"])
        data = f.read(max(0, st.st_size - inc["offset"]))
        if len(inc["head"]) < HEAD_BYTES:
            f.seek(0)
            head_end = inc["offset"] + (data.rfind(b"\n") + 1)
            inc_head = f.read(min(HEAD_BYTES, head_end))
        else:
            inc_head = inc["head"]
    cut = data.rfind(b"\n")
    if cut < 0:
        return 0, reset
    chunk = data[:cut + 1]
    first = inc["offset"] == 0
    try:
        text = chunk.decode("utf-8-sig" if first else "utf-8")
    except UnicodeDecodeError:
        raise _Fallback("the file is not valid UTF-8")
    if first and text.lstrip().startswith("["):
        raise _Fallback("the file is one JSON array, not JSON lines")
    lines = _LINE_SPLIT.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    added = 0
    for line in lines:
        inc["line_no"] += 1
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            inc["rows"].append(obj)
            added += 1
        else:
            inc["unreadable"] += 1
            if len(inc["unreadable_lines"]) < 20:
                inc["unreadable_lines"].append(inc["line_no"])
    inc["offset"] += len(chunk)
    inc["head"] = inc_head
    inc["pending"] += added
    return added, reset


def _throttle_s():
    """Seconds between two full analyses in incremental mode."""
    if not LIVE.get("reanalyze_auto") and LIVE.get("reanalyze_s") is not None:
        return LIVE["reanalyze_s"]
    took = LIVE.get("analysis_s") or 0
    # a quick analysis runs on every change; a slow one at most every 4x its own duration (<= 5 min)
    return 0.0 if took < 0.5 else round(min(300.0, max(LIVE["interval"], 4 * took)), 2)


def _check_incremental(state, path, sig):
    inc = LIVE["inc"]
    if inc is None or inc["path"] != path:
        inc = LIVE["inc"] = _new_inc(path)
    if sig != LIVE["sig"]:
        try:
            added, reset = _read_new(inc, path)
        except _Fallback as e:
            inc["disabled"] = str(e)
            LIVE["incremental"] = False
            _log("note", f"Reading the whole file on each change from now on: {e}.")
            return None          # the caller does a full reload
        except OSError:
            return False
        LIVE["sig"] = sig
        if reset:
            _log("reset", f"The file was {reset}: reading it again from the start.", severity="watch")
            inc["pending"] = max(inc["pending"], 1)      # analyze even if it is empty now
        LIVE.update({"records_read": len(inc["rows"]), "read_offset": inc["offset"], "incremental": True})
    if not inc["pending"]:
        return False
    wait = _throttle_s()
    LIVE["reanalyze_s"] = wait
    LIVE["pending_records"] = inc["pending"]
    since = time.time() - (LIVE.get("last_analysis") or 0)
    if LIVE["session"] is not None and since < wait:
        LIVE["note"] = (f"{inc['pending']:,} new record{'s' if inc['pending'] != 1 else ''} read; the full re-analysis "
                        f"runs at most every {wait:g} s (the last took {LIVE.get('analysis_s') or 0:g} s), "
                        f"next in {max(0.0, wait - since):.0f} s")
        return False
    if inc["unreadable"]:
        model.READ_NOTES[path] = {"unreadable_lines": inc["unreadable"],
                                  "unreadable_line_numbers": list(inc["unreadable_lines"])}
    else:
        model.READ_NOTES.pop(path, None)
    if not inc["rows"]:
        inc["pending"] = 0
        LIVE["pending_records"] = 0
        LIVE["note"] = "waiting for the first records"
        return False
    if not _load_once(state, rows=inc["rows"]):
        return False
    inc["pending"] = 0
    LIVE["pending_records"] = 0
    return True


def check(state):
    """One watch step: load again when the path changed. Returns True when a load ran."""
    path = LIVE["path"]
    # the app loaded another dataset: after live's first load, anything but live's own session; before
    # it, anything but the session that was showing when live mode started
    mine = LIVE["session"] if LIVE["session"] is not None else LIVE.get("session_at_start")
    if state["session"] is not mine and getattr(state["session"], "loaded", False):
        _log("stopped", "Live mode stopped: another dataset was loaded in the app.")
        LIVE["stop"] and LIVE["stop"].set()
        LIVE["watching"] = False
        return False
    LIVE["last_check"] = _now()
    if not os.path.lexists(path):
        LIVE["note"] = "the path does not exist yet; waiting for it"
        return False
    if LIVE.get("guard"):
        # checked again on every tick: the file may have appeared since, or been replaced by a link or a pipe
        try:
            LIVE["guard"](path)
        except ValueError as e:
            if LIVE["error"] != str(e):
                LIVE["error"] = str(e)
                _log("error", f"Not reading the trace: {e}", severity="alert")
            return False
    try:
        sig = _signature(path)
    except OSError:
        LIVE["note"] = "the path does not exist yet; waiting for it"
        return False
    if os.path.isfile(path) and os.path.splitext(path)[1].lower() in INC_EXTS \
            and not (LIVE["inc"] and LIVE["inc"]["path"] == path and LIVE["inc"]["disabled"]):
        done = _check_incremental(state, path, sig)
        if done is not None:
            return done
        LIVE["sig"] = None
    if sig == LIVE["sig"]:
        return False
    # a single file whose last line is still being written: wait one tick for it to settle
    if not os.path.isdir(path) and sig[0] > 0 and LIVE["pending"] != sig:
        with open(path, "rb") as f:
            f.seek(sig[0] - 1)
            if f.read(1) != b"\n":
                LIVE["pending"] = sig
                return False
    LIVE["pending"] = None
    if not _load_once(state):
        return False
    LIVE["sig"] = sig          # even after an error: try again only when the file changes
    return True


def _run(state, stop):
    while not stop.is_set():
        try:
            check(state)
        except Exception:
            traceback.print_exc()
        stop.wait(LIVE["interval"])


def live_start(state, q, body):
    try:
        b = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("send JSON: {\"path\": ..., \"pack\": ..., \"interval_s\": ...}")
    if not isinstance(b, dict):
        raise ValueError("send a JSON object: {\"path\": ..., \"pack\": ...}")
    if not b.get("path") or not isinstance(b.get("path"), str):
        raise ValueError("give the path of a trace file or folder on this machine")
    guard, pack_guard = state.get("path_guard"), state.get("pack_guard")
    if guard:   # the server's policy: allowed folders only, regular files, no links out (server.check_data_path)
        path = guard(b["path"], allow_missing=True)
    else:
        path = os.path.abspath(os.path.expanduser(b["path"].strip()))
        if not os.path.exists(path) and not os.path.isdir(os.path.dirname(path)):
            raise ValueError(f"no such file or folder: {path}")
    pack = pack_guard(b.get("pack")) if pack_guard else (b.get("pack") or "auto")
    try:
        interval = float(b.get("interval_s") or 2)
    except (TypeError, ValueError):
        raise ValueError("interval_s must be a number of seconds")
    if not 0.2 <= interval <= 3600:
        raise ValueError("interval_s must be between 0.2 and 3600 seconds")
    mapping = b.get("map") or {}
    if not isinstance(mapping, dict):
        raise ValueError("map must be an object: {\"role\": \"column\"}")
    reanalyze = b.get("reanalyze_s")
    if reanalyze not in (None, "", "auto"):
        try:
            reanalyze = float(reanalyze)
        except (TypeError, ValueError):
            raise ValueError("reanalyze_s must be a number of seconds (or \"auto\")")
        if not 0 <= reanalyze <= 3600:
            raise ValueError("reanalyze_s must be between 0 and 3600 seconds")
    else:
        reanalyze = None
    if state.get("busy"):   # an upload is being analyzed: live mode would replace it the moment it finished
        raise LookupError("An upload is being analyzed. Start live mode once it has finished.")
    live_stop(state, {}, b"", quiet=True)
    stop = threading.Event()
    LIVE.update({"path": path, "pack": pack, "mapping": {str(k): str(v) for k, v in mapping.items() if v}, "guard": guard,
                 "interval": interval, "watching": True, "started": _now(), "stop": stop, "session": None,
                 "session_at_start": state.get("session"),
                 "sig": None, "pending": None, "error": None, "note": None, "loads": 0, "records": 0,
                 "actors": 0, "messages": 0, "signs": 0, "last_load": None, "load_s": None,
                 "inc": None, "incremental": None, "reanalyze_s": reanalyze, "reanalyze_auto": reanalyze is None,
                 "pending_records": 0, "records_read": 0, "read_offset": 0, "last_analysis": 0.0, "analysis_s": None,
                 "facts": None, "rules_now": None, "rules_fp": None})
    _log("started", f"Watching {path} every {interval:g} s.")
    th = threading.Thread(target=_run, args=(state, stop), name="swarmtracer-live", daemon=True)
    LIVE["thread"] = th
    th.start()
    return live_status(state, {})


def live_stop(state, q, body=b"", quiet=False):
    stop = LIVE.get("stop")
    if stop is not None and not stop.is_set():
        stop.set()
        if not quiet:
            _log("stopped", "Live mode stopped.")
    LIVE["watching"] = False
    LIVE["inc"] = None          # the rows read so far: the analyzed session keeps what it needs
    return live_status(state, {})


def live_status(state, q):
    try:
        since = int(q.get("since") or 0)
    except ValueError:
        since = 0
    evs = [e for e in LIVE["events"] if e["seq"] > since][-300:]
    s = state["session"]
    return {"watching": LIVE["watching"], "path": LIVE["path"], "pack": LIVE["pack"],
            "pack_name": LIVE["session"].pack.name if LIVE["session"] is not None else None, "interval_s": LIVE["interval"],
            "started": LIVE["started"], "last_check": LIVE["last_check"], "last_load": LIVE["last_load"],
            "load_s": LIVE["load_s"], "loading": LIVE["loading"], "loads": LIVE["loads"], "records": LIVE["records"],
            "actors": LIVE["actors"], "messages": LIVE["messages"], "signs": LIVE["signs"],
            "error": LIVE["error"], "note": LIVE["note"], "seq": LIVE["seq"], "events": evs,
            "dataset_is_live": bool(LIVE["session"] is not None and s is LIVE["session"]),
            # incremental reading: whether it is on, rows read so far, and new rows waiting for the
            # (throttled) full re-analysis
            "incremental": LIVE["incremental"], "records_read": LIVE["records_read"],
            "read_offset": LIVE["read_offset"], "pending_records": LIVE["pending_records"],
            "reanalyze_s": LIVE["reanalyze_s"] if LIVE["incremental"] else None,
            "analysis_s": LIVE["analysis_s"],
            "hint": "python3 -m agenttrace.tools.replay_feed TRACE.jsonl /tmp/feed.jsonl --rate 2000"}


# ------------------------------------------------------------------ rule routes

def rules_get(state, q):
    rules, saved = load_rules()
    return {"rules": rules, "saved": saved, "path": rules_path(), "severities": list(SEVERITIES),
            "condition_types": COND_TYPES, "families": list(insight_families()), "defaults": DEFAULT_RULES}


def insight_families():
    return ("single", "joint", "baseline")


def rules_post(state, q, body):
    try:
        b = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("send JSON: {\"rules\": [...]} or {\"reset\": true}")
    if isinstance(b, dict) and b.get("reset"):
        p = rules_path()
        if os.path.isfile(p):
            os.remove(p)
        return rules_get(state, q)
    rules = b if isinstance(b, list) else b.get("rules") if isinstance(b, dict) else None
    if rules is None:
        raise ValueError("send {rules: [...]}")
    s = state["session"]
    save_rules(rules, s.name if s.loaded else None)
    return rules_get(state, q)


def rules_eval(state, q):
    s = state["session"]
    if not s.loaded:
        raise LookupError("No dataset loaded. Upload a file first.")
    out = evaluate_rules(s)
    for r in out["rules"]:
        r.pop("t", None)
    out["kinds"] = sorted({g["kind"] for g in insight.simulate(s)["signals"]})
    return out


GET = {"live_status": live_status, "rules": rules_get, "rules_eval": rules_eval}
POST = {"live_start": live_start, "live_stop": live_stop, "rules": rules_post}

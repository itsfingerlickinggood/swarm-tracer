"""Comparing two swarms side by side, and the library of past incidents.

    POST /api/x/compare_load   {path, pack} or {library: id}: analyze a second dataset on this machine
    GET  /api/x/compare_state  whether a second dataset is loaded or loading
    POST /api/x/compare_clear  forget the second dataset
    GET  /api/x/compare        the same measures for both datasets, and plain sentences on what differs
    GET  /api/x/library        known datasets and incidents, with whether each is on this machine

Every measure is counted the same way for both datasets by the same code, so differences come
from the data (and the pack each was read with, which the reply names).
"""
import json
import os
import re
import statistics
import threading
import time

from . import insight

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY_PATH = os.path.join(HERE, "claims", "library.json")
LOCK = threading.Lock()
HOUR = 3600.0


# ------------------------------------------------------------------ library

def _roots():
    """Folders a library path hint may be relative to: the package, the project root, the current
    folder, and SWARM_TRACER_DATA if set."""
    out = [HERE, os.path.dirname(HERE), os.getcwd()]
    if os.environ.get("SWARM_TRACER_DATA"):
        out.insert(0, os.environ["SWARM_TRACER_DATA"])
    seen = []
    for r in out:
        r = os.path.abspath(r)
        if r not in seen:
            seen.append(r)
    return seen


def resolve(hint):
    """The first existing path for a hint ('~/x', '/abs/x' or 'relative/x'), or None."""
    if not hint:
        return None
    h = os.path.expanduser(hint)
    cands = [h] if os.path.isabs(h) else [os.path.join(r, h) for r in _roots()]
    for c in cands:
        if os.path.exists(c) and (os.path.isfile(c) or (os.path.isdir(c) and os.listdir(c))):
            return os.path.abspath(c)
    return None


def library(path=None):
    """Entries from claims/library.json, each with `available` (the first path hint that exists here)."""
    with open(path or LIBRARY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for e in data.get("entries", []):
        hints = e.get("paths") or ([e["path"]] if e.get("path") else [])
        found = next((p for p in (resolve(h) for h in hints) if p), None)
        ctx = e.get("context_file")
        out.append({**e, "paths": hints, "available": found,
                    "context_available": bool(ctx and resolve(ctx))})
    return {"about": data.get("about"), "entries": out}


def library_entry(entry_id):
    for e in library()["entries"]:
        if e.get("id") == entry_id:
            return e
    raise ValueError(f"no library entry {entry_id!r}")


# ------------------------------------------------------------------ measures

def _median(xs):
    return round(statistics.median(xs), 2) if xs else None


def _iso_hours(s, t):
    sim = insight.simulate(s)
    if t is None or sim.get("start_t") is None:
        return None
    return round((t - sim["start_t"]) / HOUR, 2)


def measures(s):
    """The comparable numbers of one loaded dataset. Cached on the session."""
    cached = getattr(s, "_compare_measures", None)
    if cached is not None:
        return cached
    summ = s.summary()
    f = summ.get("flow", {})
    acts = summ.get("actions") or {}
    sim = insight.simulate(s)
    n = summ.get("records") or 0

    # messages between named actors, split by whether the place is exact or one the redaction may have merged
    coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
    named = [d for d in s.flow["_deliveries"] if insight.is_named(d["from"]) and insight.is_named(d["to"])]
    merged = sum(1 for d in named if any(r.search(d["channel"]) for r in coarse))
    lat = f.get("latency_hours") or {}

    # sender-receiver pairs and how many of them went both ways
    directed = {(r["from"], r["to"]) for r in s.pair_rows if r["named"] and r["from"] != r["to"]}
    unordered = {tuple(sorted(p)) for p in directed}
    two_way = sum(1 for a, b in unordered if (a, b) in directed and (b, a) in directed)

    # programs reused by other actors, and how fast the first reuse came
    spread = s.flow.get("_content_spread", [])
    first_adopt = [min(a["hours_after_source"] for a in x["adopters"] if a.get("hours_after_source") is not None)
                   for x in spread if any(a.get("hours_after_source") is not None for a in x["adopters"])]

    # warning signs: the first of each family, with how much harm was still to come
    sigs = sim.get("signals", [])
    first_sign = {}
    for g in sigs:
        if g["family"] not in first_sign:
            first_sign[g["family"]] = {"name": g["name"], "time": g["time"], "ref": g.get("ref"), "record": g.get("record"),
                                       "harm_share_after": g["harm_share_after"], "hours_in": _iso_hours(s, g["t"])}
    alarm = next((g for g in sigs if g["key"] == "rate_all"), None) or next((g for g in sigs if g["key"] == "rate_harm"), None)

    # the early-flag curve: harm still to come against hours since the first dated action
    curve = []
    if sim.get("start_t") is not None and sim.get("harm_total"):
        curve.append([0, insight.harm_share_after(s, sim["start_t"])])
        rem = sim.get("harm_remaining", [])
        for i, v in enumerate(rem):   # a step curve: keep only the hours where the value changes
            if v != curve[-1][1] or i == len(rem) - 1:
                if curve[-1][0] != i:
                    curve.append([i, curve[-1][1]])
                curve.append([i + 1, v])
        if len(curve) > 1200:
            step = len(curve) // 600 + 1
            curve = curve[::step] + [curve[-1]]

    gaps = [{"key": g["key"], "gap": g["gap"], "share": g["share"], "count": g["count"], "of": g["of"], "unit": g["unit"]}
            for g in insight.gap_facts(s) if g.get("share") is not None]
    types = {k: {"places": v.get("channels", 0), "messages": v.get("deliveries", 0)}
             for k, v in (f.get("channel_types") or {}).items()}
    out = {
        "name": summ.get("name"), "pack": summ.get("pack"),
        "records": n,
        "dated": summ.get("timed", 0), "dated_share": round(summ.get("timed", 0) / n, 4) if n else None,
        "span": (summ.get("time_test") or {}).get("span"),
        "hours": sim.get("hours", 0),
        "named_actors": acts.get("named_actors", 0),
        "actions": acts.get("total", 0),
        "unattributed_share": round(acts.get("unattributed", 0) / acts["total"], 4) if acts.get("total") else None,
        "places": f.get("channels", 0), "places_by_type": types,
        "messages": f.get("deliveries", 0),
        "messages_named": len(named), "messages_named_exact": len(named) - merged, "messages_named_merged": merged,
        "pairs": len(directed), "pairs_unordered": len(unordered), "two_way_pairs": two_way,
        "two_way_share": round(two_way / len(unordered), 4) if unordered else None,
        "largest_group": max(sim.get("largest_group") or [0]),
        "wait_median_h": lat.get("median"), "wait_p90_h": lat.get("p90"),
        "programs_shared": len(spread),
        "adoption_median_h": _median(first_adopt),
        "harm_total": sim.get("harm_total", 0),
        "signals": len(sigs),
        "first_sign": first_sign,
        "volume_alarm": ({"name": alarm["name"], "time": alarm["time"], "harm_share_after": alarm["harm_share_after"],
                          "hours_in": _iso_hours(s, alarm["t"])} if alarm else None),
        "curve": curve,
        "gaps": gaps,
    }
    s._compare_measures = out
    return out


# ------------------------------------------------------------------ what differs, in words

def _ratio(a, b):
    if not a or not b:
        return None
    return max(a, b) / min(a, b)


def _n(x):
    return f"{x:,}" if isinstance(x, int) else (f"{x:,.1f}" if isinstance(x, float) else str(x))


def _pct(x):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if 0.99 < x < 1 or 0 < x < 0.01 else f"{round(100 * x)}%"


def _hours(h):
    if h is None:
        return "–"
    return f"{round(h * 60)} min" if h < 1 else (f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} days")


def differences(a, b):
    """Plain sentences on the largest differences, most telling first. a and b are measures()."""
    A, B = a["name"] or "the first dataset", b["name"] or "the second dataset"
    out = []

    def add(key, text, weight):
        out.append({"key": key, "text": text, "weight": round(weight, 2)})

    def bigger(key, label, fmt=_n, min_ratio=1.5):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            return
        if (va == 0) != (vb == 0):
            has, val = (A, va) if va else (B, vb)
            other = B if va else A
            add(key, f"{has} has {fmt(val)} {label}; {other} has none.", 3)
            return
        r = _ratio(va, vb)
        if r and r >= min_ratio:
            hi, lo = (A, B) if va > vb else (B, A)
            add(key, f"{hi} has {r:.1f}x the {label} of {lo} ({fmt(max(va, vb))} against {fmt(min(va, vb))}).", min(r, 10) / 2)

    def share(key, label, min_diff=0.1):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            return
        d = abs(va - vb)
        if d >= min_diff:
            hi, lo = (A, B) if va > vb else (B, A)
            add(key, f"{label}: {_pct(max(va, vb))} in {hi} against {_pct(min(va, vb))} in {lo}.", d * 6)

    bigger("records", "records")
    bigger("named_actors", "named actors")
    bigger("messages_named", "messages between named actors")
    bigger("largest_group", "largest group of actors linked by messages", min_ratio=1.3)
    bigger("programs_shared", "programs run by more than one actor")
    share("dated_share", "Records with a time", 0.15)
    share("two_way_share", "Named pairs that wrote both ways")
    share("unattributed_share", "Actions with no named actor", 0.15)
    for key, label in (("wait_median_h", "median wait between a message being written and read"),
                       ("adoption_median_h", "median time until another actor reused a program")):
        va, vb = a.get(key), b.get(key)
        r = _ratio(va, vb)
        if r and r >= 2:
            slow, fast = (A, B) if va > vb else (B, A)
            add(key, f"The {label} is {r:.1f}x longer in {slow} ({_hours(max(va, vb))} against {_hours(min(va, vb))} in {fast}).", min(r, 10) / 2)
    # messages per named actor: how chatty the swarm is, independent of its size
    if a["named_actors"] and b["named_actors"]:
        ma, mb = a["messages_named"] / a["named_actors"], b["messages_named"] / b["named_actors"]
        r = _ratio(ma, mb)
        if r and r >= 2:
            hi, lo = (A, B) if ma > mb else (B, A)
            add("messages_per_actor", f"Per named actor, {hi} exchanged {r:.1f}x as many messages as {lo} "
                                      f"({max(ma, mb):.1f} against {min(ma, mb):.1f}).", min(r, 10) / 2)
    # early flag: the first sign of actors working together
    ja, jb = a["first_sign"].get("joint"), b["first_sign"].get("joint")
    if ja and jb and ja["harm_share_after"] is not None and jb["harm_share_after"] is not None:
        d = ja["harm_share_after"] - jb["harm_share_after"]
        if abs(d) >= 0.1:
            early, late = (A, B) if d > 0 else (B, A)
            add("first_joint", f"The first sign of actors working together came earlier, relative to the harm, in {early}: "
                               f"{_pct(max(ja['harm_share_after'], jb['harm_share_after']))} of the harmful activity was still to come, "
                               f"against {_pct(min(ja['harm_share_after'], jb['harm_share_after']))} in {late}.", abs(d) * 8)
    elif bool(ja) != bool(jb):
        has = A if ja else B
        add("first_joint", f"Only {has} shows a sign of actors working together (a message, a shared program or a shared place).", 3)
    # does a volume alarm come before or after the first joint sign?
    for m, name in ((a, A), (b, B)):
        j, v = m["first_sign"].get("joint"), m["volume_alarm"]
        if j and v and j["hours_in"] is not None and v["hours_in"] is not None and abs(v["hours_in"] - j["hours_in"]) >= 1:
            lead = v["hours_in"] - j["hours_in"]
            add("alarm_" + name, f"In {name}, a plain volume alarm fires {_hours(abs(lead))} "
                                 f"{'after' if lead > 0 else 'before'} the first sign of actors working together.", 1.2)
    # place types one swarm used and the other did not
    ta, tb = set(a["places_by_type"]), set(b["places_by_type"])
    if ta - tb:
        add("types_a", f"Only {A} has places of type {', '.join(sorted(ta - tb))}.", 1)
    if tb - ta:
        add("types_b", f"Only {B} has places of type {', '.join(sorted(tb - ta))}.", 1)
    # blind spots
    ga = {g["key"]: g for g in a["gaps"]}
    for g in b["gaps"]:
        x = ga.get(g["key"])
        if x and abs(x["share"] - g["share"]) >= 0.2:
            worse, better = (A, B) if x["share"] > g["share"] else (B, A)
            add("gap_" + g["key"], f"Blind spot, {g['gap'].lower()}: {_pct(max(x['share'], g['share']))} in {worse} "
                                   f"against {_pct(min(x['share'], g['share']))} in {better}.", abs(x["share"] - g["share"]) * 4)
    if a.get("pack") != b.get("pack"):
        add("pack", f"The two were read with different packs ({a.get('pack')} and {b.get('pack')}), so places, intents and "
                    "harm are defined differently; compare shapes and shares more than raw counts.", 0.5)
    out.sort(key=lambda x: -x["weight"])
    return out


# ------------------------------------------------------------------ routes

def _main(state):
    s = state["session"]
    if not s.loaded:
        raise LookupError("No dataset loaded. Load one first; the comparison puts a second dataset next to it.")
    return s


def api_compare(state, q):
    s = _main(state)
    a = measures(s)
    b_s = state.get("compare")
    if not b_s or not getattr(b_s, "loaded", False):
        return {"a": a, "b": None, "differences": [], "busy": bool(state.get("compare_busy")),
                "error": state.get("compare_error")}
    b = measures(b_s)
    return {"a": a, "b": b, "differences": differences(a, b), "busy": False, "error": None,
            "b_source": state.get("compare_source")}


def api_state(state, q):
    b = state.get("compare")
    return {"loaded": bool(b and getattr(b, "loaded", False)), "name": getattr(b, "name", None) if b else None,
            "busy": bool(state.get("compare_busy")), "error": state.get("compare_error"),
            "source": state.get("compare_source")}


def load_compare(state, path, pack="auto", name=None, mapping=None):
    """Analyze a second dataset into state['compare']. One load at a time."""
    from .session import Session
    if not LOCK.acquire(blocking=False):
        raise LookupError("A comparison dataset is already loading.")
    try:
        state["compare_busy"], state["compare_error"] = True, None
        t0 = time.time()
        sess = Session()
        try:
            sess.load(path, pack or "auto", mapping or {}, name or os.path.basename(path.rstrip(os.sep)))
        except SystemExit as e:   # pack and format errors arrive as SystemExit with a message
            raise ValueError(str(e))
        state["compare"] = sess
        state["compare_source"] = {"path": path, "pack": pack or "auto", "seconds": round(time.time() - t0, 1)}
        return sess
    except Exception as e:
        state["compare_error"] = str(e)
        raise
    finally:
        state["compare_busy"] = False
        LOCK.release()


def api_load(state, q, body):
    try:
        req = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("send JSON: {\"path\": ..., \"pack\": ...} or {\"library\": id}")
    if not isinstance(req, dict):
        raise ValueError("send a JSON object: {\"path\": ..., \"pack\": ...} or {\"library\": id}")
    guard, pack_guard = state.get("path_guard"), state.get("pack_guard")
    pack, name = req.get("pack") or "auto", req.get("name")
    if name is not None:
        name = str(name)[:200]
    if req.get("library"):
        e = library_entry(str(req["library"]))
        if not e["available"]:
            raise ValueError(f"{e['title']} is not on this machine. Get it from {e.get('source_url') or 'its source'} "
                             f"and put it at one of: {', '.join(e['paths'])}.")
        path, pack, name = e["available"], req.get("pack") or e.get("pack") or "auto", name or e["title"]
        if guard:   # the shipped library names its own paths: still a regular file or folder, no device
            path = guard(path, trusted=True)
    else:
        raw = req.get("path")
        if not raw or not isinstance(raw, str):
            raise ValueError("give the path of a trace file or folder on this machine")
        if guard:   # the server's policy: allowed folders only, regular files, no links out (server.check_data_path)
            path = guard(raw)
        else:
            path = os.path.abspath(os.path.expanduser(raw.strip()))
            if not os.path.exists(path):
                raise ValueError(f"No file or folder at {raw!r} on this machine.")
    if pack_guard:
        pack = pack_guard(pack)
    mapping = req.get("map") or {}
    if not isinstance(mapping, dict):
        raise ValueError("map must be an object: {\"role\": \"column\"}")
    sess = load_compare(state, path, pack, name, mapping)
    out = measures(sess)
    return {"loaded": True, "name": sess.name, "records": out["records"], "pack": out["pack"],
            "seconds": state["compare_source"]["seconds"]}


def api_clear(state, q, body):
    state["compare"] = None
    state["compare_source"] = state["compare_error"] = None
    return {"loaded": False}


def api_library(state, q):
    try:
        return library()
    except (OSError, ValueError) as e:
        return {"about": None, "entries": [], "error": f"the library file could not be read: {e}"}


GET = {"compare": api_compare, "compare_state": api_state, "library": api_library}
POST = {"compare_load": api_load, "compare_clear": api_clear}

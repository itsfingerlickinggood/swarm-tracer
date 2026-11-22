"""The simple alarms: the main early-warning feature since v2.3.0 (they were "baselines" in v2.2.0).

The audit of v2.1.0 found that on the real release four plain alarms beat every shared-control sign on "share of
harm still to come" (a volume alarm, the first new host after 12 h, the first search-for-secrets action, a
distinct-actor alarm). v2.3.0 therefore leads with them and shows the shared-control signs as context ("who shares
control"), labelled as not an early warning. This module computes both for any loaded session:

    new_host_12h      the first action, at least 12 h into the trace, that contacts a host not seen before
    first_intent      the first action of a named intent (the release's 'search_for_secrets'), when the pack has it
    distinct_actors   the first hour whose count of distinct named actors is above mean + 3 sd of the earlier hours
                      (at least 12 h of history; sd never below 1)
    volume_6h         the first hour whose action count is above mean + 3 sd of the earlier hours (6 h of history)
  variants, reported beside them:
    volume_12h        the same with 12 h of history (the baseline published in v2.2.0)
    new_host_24h      the new-host alarm after 24 h of history

Honesty: the thresholds are the ones the auditors used, but the four were PICKED as the main alarms after seeing that
they did best on one incident (the Swarm Traces release). That is post-hoc on one incident (POST_HOC below); the
forward test of v2.3.0 (reports/earlywarn/prereg_v23.json, written before its swarms existed) and the benign
false-alarm rates are the only evidence that was not chosen with the answer in view.

    python3 -m agenttrace.baselines [--trace redacted_columns.csv --pack code_traces.json --out reports/baselines.json]
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

from . import evaluate, insight, reconstruct

HOUR = 3600.0
HOST = re.compile(r"https?://(?:[^/\s'\"\\@]*@)?([A-Za-z0-9_.\-\[\]]+?)(?::\d+)?(?=[/\s'\"?#\\)]|$)", re.I)
BASELINES = [
    ("new_host_12h", "First new host after 12 h"),
    ("new_host_24h", "First new host after 24 h"),
    ("distinct_actors", "Distinct-actor alarm (3 sd, 12 h history)"),
    ("volume_12h", "Volume alarm (3 sd, 12 h history)"),
    ("volume_6h", "Volume alarm (3 sd, 6 h history)"),
    ("first_intent", "First search_for_secrets action"),
]
NAME = dict(BASELINES)
INTENT = "search_for_secrets"

# The main early-warning alarms of v2.3.0, in the order the app shows them, with every parameter. This dict is what
# reports/earlywarn/prereg_v23.json freezes (its SHA-256 is params_sha256()); change a value and the hash changes.
MAIN_ALARMS = [
    {"id": "new_host_12h", "short": "New host", "name": NAME["new_host_12h"],
     "params": {"after_h": 12},
     "what": "The first action, at least 12 hours after the first action, that contacts a host no earlier action named."},
    {"id": "first_intent", "short": "Secrets search", "name": NAME["first_intent"],
     "params": {"intent": INTENT},
     "what": "The first action the pack labels search_for_secrets. A pack without that intent never fires it."},
    {"id": "distinct_actors", "short": "Distinct actors", "name": NAME["distinct_actors"],
     "params": {"k_sigma": 3.0, "min_history_h": 12, "min_sd": 1.0},
     "what": "The first hour with more distinct named actors than the mean plus 3 standard deviations of every earlier hour "
             "(at least 12 earlier hours). Known at the end of that hour."},
    {"id": "volume_6h", "short": "Volume", "name": NAME["volume_6h"],
     "params": {"k_sigma": 3.0, "min_history_h": 6, "min_sd": 1.0},
     "what": "The first hour with more actions than the mean plus 3 standard deviations of every earlier hour "
             "(at least 6 earlier hours). Known at the end of that hour."},
]
VARIANTS = [
    {"id": "volume_12h", "short": "Volume, 12 h history", "name": NAME["volume_12h"],
     "params": {"k_sigma": 3.0, "min_history_h": 12, "min_sd": 1.0},
     "what": "The volume alarm with 12 hours of history: the baseline published in v2.2.0."},
    {"id": "new_host_24h", "short": "New host, 24 h", "name": NAME["new_host_24h"],
     "params": {"after_h": 24}, "what": "The new-host alarm after 24 hours of history."},
]
MAIN_IDS = tuple(a["id"] for a in MAIN_ALARMS)
VARIANT_IDS = tuple(a["id"] for a in VARIANTS)
SHORT = {a["id"]: a["short"] for a in MAIN_ALARMS + VARIANTS}
ROLE = {**{i: "main" for i in MAIN_IDS}, **{i: "variant" for i in VARIANT_IDS}}
POST_HOC = ("Post-hoc on one incident: these four alarms were picked as the main early warning after seeing that they "
            "fired with more harm still to come than the shared-control signs on the Swarm Traces release. Their "
            "thresholds were not tuned, but the choice of alarms (and of the 6 h volume history over the 12 h one) was "
            "made with that answer in view, so their figures on that release are not a test.")
CONTEXT_LABEL = "Context: who shares control"
CONTEXT_NOTE = ("Not an early warning. These signs say which identities share a place, a token, a program or a message, "
                "which is what an investigator needs after an alarm. On the real release they fired later than every "
                "simple alarm, and on simulated swarms the shared-place sign fires after the first harm.")
# the two signs the audit called shared-control signs, first; then the other signs of actors together
SHARED_CONTROL_KINDS = ("place", "carried")
CONTEXT_KINDS = ("place", "carried", "message", "two_way", "group", "program")


def frozen_params():
    """The main alarms and the variants with every parameter, as frozen by the v2.3.0 pre-registration."""
    return {"main": [{"id": a["id"], "name": a["name"], "params": a["params"], "what": a["what"]} for a in MAIN_ALARMS],
            "variants": [{"id": a["id"], "name": a["name"], "params": a["params"], "what": a["what"]} for a in VARIANTS],
            "context_kinds": list(CONTEXT_KINDS), "host_pattern": HOST.pattern,
            "counted": "actions with an intent and a time; an actor is named when its kind is not 'run'"}


def params_sha256():
    return hashlib.sha256(json.dumps(frozen_params(), sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def hosts_of(text):
    return {m.group(1).lower() for m in HOST.finditer(text)}


def new_host_hit(events, times, intents, after_h):
    """(time, record id, host) of the first action at least after_h hours after the first action that names a host
    never seen before; None when there is none."""
    acts = sorted(((times[e.id], e) for e in events if e.id in times and intents.get(e.id)), key=lambda x: (x[0], x[1].id))
    if not acts:
        return None
    start = acts[0][0]
    seen = set()
    for t, e in acts:
        hs = hosts_of(e.text)
        if t - start >= after_h * HOUR and hs - seen:
            return t, e.id, sorted(hs - seen)[0]
        seen |= hs
    return None


def new_host_alarm(events, times, intents, after_h):
    """Time of the first action at least after_h hours after the first action that names a host never seen before."""
    hit = new_host_hit(events, times, intents, after_h)
    return hit[0] if hit else None


def series_alarm(counts, start, k=3.0, min_history=12):
    """Alarm time (end of the first hour above mean + k sd of all earlier hours; empty hours count as 0)."""
    if not counts:
        return None
    last = max(counts)
    hist = []
    for h in range(last + 1):
        c = counts.get(h, 0)
        if len(hist) >= min_history:
            mu = sum(hist) / len(hist)
            sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / len(hist))
            if c > mu + k * max(sd, 1.0):
                return (start + h + 1) * HOUR
        hist.append(c)
    return None


def details(s):
    """{alarm id: {"t": alarm time (epoch seconds) or None, "record": the record it fired on (None for an hourly
    alarm, which is known at the end of an hour), "why": one plain sentence}} for a loaded session."""
    times, intents = s.rec["_times"], s.rec["_intents"]
    acts = [(times[e.id], e.id) for e in s.events if e.id in times and intents.get(e.id)]
    out = {k: {"t": None, "record": None, "why": None} for k, _ in BASELINES}
    if not acts:
        return out
    for key, after in (("new_host_12h", 12), ("new_host_24h", 24)):
        hit = new_host_hit(s.events, times, intents, after)
        if hit:
            out[key] = {"t": hit[0], "record": hit[1],
                        "why": f"{hit[1]} contacts {hit[2]}, a host no action had named in the first {(hit[0] - min(a[0] for a in acts)) / HOUR:.1f} h"}
    start = math.floor(min(t for t, _ in acts) / HOUR)
    actors = defaultdict(set)
    for t, rid in acts:
        a, kind = s.actor[rid]
        if kind != "run":
            actors[math.floor(t / HOUR) - start].add(a)
    counts = {h: len(v) for h, v in actors.items()}
    t = series_alarm(counts, start, 3.0, 12)
    if t is not None:
        h = int(round(t / HOUR)) - 1 - start
        out["distinct_actors"] = {"t": t, "record": None,
                                  "why": f"{counts.get(h, 0)} distinct named actors in the hour from {reconstruct.iso((start + h) * HOUR)}, "
                                         "above the mean plus 3 standard deviations of every earlier hour; known at the end of that hour"}
    pts = [t for t, _ in acts]
    for key, mh in (("volume_12h", 12), ("volume_6h", 6)):
        b = evaluate.rate_alarm(pts, s.harm_sorted, k=3.0, min_history=mh)
        if b:
            out[key] = {"t": evaluate._parse(b["hour"]) + HOUR, "record": None,
                        "why": f"{b['count']:,} actions in the hour from {b['hour']}, above the alarm line of {b['threshold']:,.0f} "
                               f"(mean plus 3 standard deviations of every earlier hour, {mh} h of history); known at the end of that hour"}
    firsts = sorted((times[e.id], e.id) for e in s.events if e.id in times and intents.get(e.id) == INTENT)
    if firsts:
        out["first_intent"] = {"t": firsts[0][0], "record": firsts[0][1], "why": f"{firsts[0][1]} is the first action labelled {INTENT}"}
    return out


def alarms(s):
    """{alarm id: alarm time (epoch seconds) or None} for a loaded session."""
    return {k: v["t"] for k, v in details(s).items()}


def is_context(g):
    """True for a replay sign that says who shares control (actors together), which v2.3.0 shows as context."""
    return g.get("family") == "joint" or g.get("kind") in CONTEXT_KINDS


def early_warning(s):
    """The early-warning answer for one loaded session: the four main alarms (and the two variants) with when each
    fired, the record, and the share of timed harm still to come; then the shared-control signs as context."""
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    out = {"dataset": s.name, "pack": s.pack.name, "dated": t0 is not None, "start": sim.get("start"), "hours": sim.get("hours"),
           "harm_records": len(s.harm_sorted), "has_intent": INTENT in _intents_of(s.pack),
           "alarms": [], "variants": [], "context": [], "post_hoc": POST_HOC,
           "context_label": CONTEXT_LABEL, "context_note": CONTEXT_NOTE, "params_sha256": params_sha256()}
    if t0 is None:
        return out
    det = details(s)

    def row(a, role):
        d = det[a["id"]]
        t = d["t"]
        return {"id": a["id"], "key": "alarm:" + a["id"], "name": a["name"], "short": a["short"], "role": role, "what": a["what"],
                "params": a["params"], "fired": t is not None, "t": t, "time": reconstruct.iso(t) if t is not None else None,
                "h": None if t is None else round((t - t0) / HOUR, 2), "record": d["record"], "why": d["why"],
                "harm_share_after": insight.harm_share_after(s, t) if t is not None else None}
    out["alarms"] = [row(a, "main") for a in MAIN_ALARMS]
    out["variants"] = [row(a, "variant") for a in VARIANTS]
    fired = [r for r in out["alarms"] if r["fired"]]
    out["first"] = min(fired, key=lambda r: (r["t"], r["id"]))["id"] if fired else None
    for g in sim["signals"]:
        if not is_context(g):
            continue
        out["context"].append({"key": g["key"], "name": g["name"], "kind": g["kind"], "role": "context",
                               "shared_control": g["kind"] in SHARED_CONTROL_KINDS, "t": g["t"], "time": g["time"],
                               "h": round((g["t"] - t0) / HOUR, 2), "record": g.get("record"), "why": g.get("why"),
                               "harm_share_after": g["harm_share_after"],
                               "after_alarms": [r["id"] for r in fired if r["t"] < g["t"]]})
    out["context"].sort(key=lambda r: (not r["shared_control"], r["t"], r["key"]))
    return out


def _intents_of(pack):
    raw = getattr(pack, "raw", None) or {}
    names = set()
    for it in raw.get("intents", []) or []:
        if isinstance(it, dict) and it.get("name"):
            names.add(it["name"])
        elif isinstance(it, (list, tuple)) and it:
            names.add(str(it[0]))
        elif isinstance(it, str):
            names.add(it)
    return names


def compare(s):
    """Every simple alarm and every sign of one loaded session with its share of harm still to come, best first.
    role: main (the four main alarms), variant, context (who shares control: not an early warning), or other."""
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    if t0 is None:
        return {"dated": False, "rows": []}
    harm = s.harm_sorted
    rows = []
    for k, t in alarms(s).items():
        rows.append({"id": k, "name": NAME[k], "kind": "baseline", "role": ROLE[k], "h": None if t is None else round((t - t0) / HOUR, 2),
                     "harm_share_after": insight.harm_share_after(s, t) if t is not None else None})
    for g in sim["signals"]:
        if g["kind"] == "harm" and g["family"] == "single":
            kind = "single-agent sign"
        elif g["kind"] in ("place", "carried", "token") or g["key"] in ("message", "program2", "program3") or g["key"].startswith("group"):
            kind = "shared-control sign"
        else:
            kind = "single-agent sign" if g["kind"] == "harm" else "other sign"
        rows.append({"id": g["key"], "name": g["name"], "kind": kind, "role": "context" if is_context(g) else "other",
                     "h": round((g["t"] - t0) / HOUR, 2), "harm_share_after": g["harm_share_after"]})
    rows.sort(key=lambda r: (r["harm_share_after"] is None, -(r["harm_share_after"] or 0), r["id"]))
    base = [r for r in rows if r["kind"] == "baseline" and r["harm_share_after"] is not None]
    best_base = max((r["harm_share_after"] for r in base), default=None)
    for r in rows:
        if r["kind"] != "baseline" and r["harm_share_after"] is not None:
            r["loses_to"] = [b["id"] for b in base if b["harm_share_after"] > r["harm_share_after"]]
    return {"dated": True, "harm_records": len(harm), "best_baseline": best_base, "rows": rows,
            "main_alarms": list(MAIN_IDS), "post_hoc": POST_HOC, "context_note": CONTEXT_NOTE}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.baselines", description=__doc__.split("\n")[0])
    ap.add_argument("--trace", default="redacted_columns.csv")
    ap.add_argument("--pack", default="code_traces.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from .session import Session
    s = Session()
    s.load(a.trace, a.pack, {}, os.path.basename(a.trace))
    res = compare(s)
    res["trace"] = a.trace
    res["note"] = ("Share of harm still to come = share of the timed harmful records after the alarm. The harm list is the pack's "
                   "(64% of it is dataset commits), so this measures growth as much as warning; see docs/audit-v2.1.md 1.5.")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    label = {"main": "MAIN ALARM", "variant": "alarm variant", "context": "context (not a warning)", "other": "other sign"}
    for r in res["rows"]:
        sh = r["harm_share_after"]
        print(f"{label[r['role']]:<24} {r['name'][:56]:<56} {r['h'] if r['h'] is not None else '-':>8} h  {'-' if sh is None else f'{100 * sh:.1f}%':>6}")
    if res.get("post_hoc"):
        print("\n" + res["post_hoc"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

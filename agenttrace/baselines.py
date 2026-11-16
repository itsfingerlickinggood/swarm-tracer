"""Simple baselines the coordination signs are scored against.

The audit of v2.1.0 found that on the real release four plain alarms beat every shared-control sign on "share of
harm still to come" (first new host after 12 h, a distinct-actor alarm, a volume alarm, the first search-for-secrets
action). This module computes them for any loaded session so the signs are always shown beside them, on the
release and on simulated swarms:

    new_host_12h      the first action, at least 12 h into the trace, that contacts a host not seen before
    new_host_24h      the same after 24 h of history
    distinct_actors   the first hour whose count of distinct named actors is above mean + 3 sd of the earlier hours
                      (at least 12 h of history; sd never below 1)
    volume_12h        the first hour whose action count is above mean + 3 sd of the earlier hours (12 h of history)
    volume_6h         the same with 6 h of history (the published baseline is the 12 h one)
    first_intent      the first action of a named intent (the release's 'search_for_secrets'), when the pack has it

Nothing here is tuned: the thresholds are the ones the auditors used, fixed before this module was run.

    python3 -m agenttrace.baselines [--trace redacted_columns.csv --pack code_traces.json --out reports/baselines.json]
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

from . import evaluate, insight

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


def hosts_of(text):
    return {m.group(1).lower() for m in HOST.finditer(text)}


def new_host_alarm(events, times, intents, after_h):
    """Time of the first action at least after_h hours after the first action that names a host never seen before."""
    acts = sorted(((times[e.id], e) for e in events if e.id in times and intents.get(e.id)), key=lambda x: (x[0], x[1].id))
    if not acts:
        return None
    start = acts[0][0]
    seen = set()
    for t, e in acts:
        hs = hosts_of(e.text)
        if t - start >= after_h * HOUR and hs - seen:
            return t
        seen |= hs
    return None


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


def alarms(s):
    """{baseline id: alarm time (epoch seconds) or None} for a loaded session."""
    times, intents = s.rec["_times"], s.rec["_intents"]
    acts = [(times[e.id], e.id) for e in s.events if e.id in times and intents.get(e.id)]
    out = {k: None for k, _ in BASELINES}
    if not acts:
        return out
    out["new_host_12h"] = new_host_alarm(s.events, times, intents, 12)
    out["new_host_24h"] = new_host_alarm(s.events, times, intents, 24)
    start = math.floor(min(t for t, _ in acts) / HOUR)
    actors = defaultdict(set)
    for t, rid in acts:
        a, kind = s.actor[rid]
        if kind != "run":
            actors[math.floor(t / HOUR) - start].add(a)
    out["distinct_actors"] = series_alarm({h: len(v) for h, v in actors.items()}, start, 3.0, 12)
    pts = [t for t, _ in acts]
    for key, mh in (("volume_12h", 12), ("volume_6h", 6)):
        b = evaluate.rate_alarm(pts, s.harm_sorted, k=3.0, min_history=mh)
        out[key] = evaluate._parse(b["hour"]) + HOUR if b else None
    firsts = [times[e.id] for e in s.events if e.id in times and intents.get(e.id) == INTENT]
    out["first_intent"] = min(firsts) if firsts else None
    return out


def compare(s):
    """Every baseline and every sign of one loaded session with its share of harm still to come, best first."""
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    if t0 is None:
        return {"dated": False, "rows": []}
    harm = s.harm_sorted
    rows = []
    for k, t in alarms(s).items():
        rows.append({"id": k, "name": NAME[k], "kind": "baseline", "h": None if t is None else round((t - t0) / HOUR, 2),
                     "harm_share_after": insight.harm_share_after(s, t) if t is not None else None})
    for g in sim["signals"]:
        if g["kind"] == "harm" and g["family"] == "single":
            kind = "single-agent sign"
        elif g["kind"] in ("place", "carried", "token") or g["key"] in ("message", "program2", "program3") or g["key"].startswith("group"):
            kind = "shared-control sign"
        else:
            kind = "single-agent sign" if g["kind"] == "harm" else "other sign"
        rows.append({"id": g["key"], "name": g["name"], "kind": kind, "h": round((g["t"] - t0) / HOUR, 2),
                     "harm_share_after": g["harm_share_after"]})
    rows.sort(key=lambda r: (r["harm_share_after"] is None, -(r["harm_share_after"] or 0), r["id"]))
    base = [r for r in rows if r["kind"] == "baseline" and r["harm_share_after"] is not None]
    best_base = max((r["harm_share_after"] for r in base), default=None)
    for r in rows:
        if r["kind"] != "baseline" and r["harm_share_after"] is not None:
            r["loses_to"] = [b["id"] for b in base if b["harm_share_after"] > r["harm_share_after"]]
    return {"dated": True, "harm_records": len(harm), "best_baseline": best_base, "rows": rows}


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
    for r in res["rows"]:
        sh = r["harm_share_after"]
        print(f"{r['kind']:<20} {r['name'][:56]:<56} {r['h'] if r['h'] is not None else '-':>8} h  {'-' if sh is None else f'{100 * sh:.1f}%':>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

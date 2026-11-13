"""Frozen signs, forward test, false-alarm rates, cost curve.

Can the coordination have been flagged early? Four honest answers, each from data:

1. Frozen signs. claims/frozen_signs.json lists every warning sign and the default alert rules as they were on
   2026-11-13, with the code version. They were written knowing how the Swarm Traces incident unfolded, so on that
   incident their timing is hindsight.
2. Forward test. The frozen signs are run on data they were not written on (new simulated swarms with seeds 21 to
   30 in every validation setting, the sample traces that have timestamps, the wiki swarm if its data is here), and
   we report per sign whether it fired and how many hours before the first true harm and the first true message.
3. False alarms. Alarms per 24 h of trace time on benign swarms (no coordination), with the agent-hours observed
   and an exact Poisson interval.
4. Cost curve. For each rule family, sweep the threshold and set the median lead time on coordinated swarms
   against the false alarms per day on benign swarms.

    python3 -m agenttrace.earlywarn freeze                      # rewrite claims/frozen_signs.json
    python3 -m agenttrace.earlywarn forward --out reports/earlywarn [--seeds 21 22 ...]
    python3 -m agenttrace.earlywarn run TRACE --pack PACK --out DIR   # the same tables for your own trace
    GET  /api/x/earlywarn_summary     the latest forward-test summary (or {"ran": false})
    GET  /api/x/earlywarn_frozen      the frozen file and whether the code has drifted since
    GET  /api/x/earlywarn_release     where each default rule fires on the loaded dataset (no truth)
    POST /api/x/earlywarn_run         {run: true, quick: true}: a one-seed forward test, in the background

The simulations are ours. Real benign multi-agent traffic with model-written code was not available.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict

from . import evaluate, groundtruth, insight, live, validation

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FROZEN = os.path.join(HERE, "claims", "frozen_signs.json")
FROZEN_DATE = "2026-11-13"
FORWARD_SEEDS = tuple(range(21, 31))
HOUR = 3600.0
CODE_FILES = ["agenttrace/insight.py", "agenttrace/live.py", "agenttrace/evaluate.py", "agenttrace/reconstruct.py",
              "agenttrace/messages.py", "agenttrace/packs/code_traces.json", "agenttrace/packs/wiki_swarm.json"]
DEFAULT_RULE_IDS = ("watch-harm", "alert-coord2", "baseline-volume")

# the rule families of the cost curve: a threshold swept over values; `default` is the frozen default (None: no default)
FAMILIES = [
    {"id": "watch", "name": "Watch rule", "param": "kinds of harmful action seen", "values": [1, 2, 3], "default": 1,
     "what": "the watch rule fires when k different kinds of harmful action have been seen"},
    {"id": "coord", "name": "N kinds of coordination", "param": "N", "values": [1, 2, 3, 4, 5], "default": 2,
     "what": "fires when N different kinds of coordination sign (shared place, carried token, message, group, two-way exchange, shared program) have shown"},
    {"id": "volume", "name": "Volume alarm", "param": "sigma", "values": [2, 3, 4, 5], "default": 3,
     "what": "fires on the first hour whose action count is more than k standard deviations above every earlier hour"},
    {"id": "place", "name": "Shared place", "param": "", "values": [1], "default": None,
     "what": "fires when two different identities name the same shared place in different records (one sign on its own)"},
    {"id": "message", "name": "First message", "param": "", "values": [1], "default": None,
     "what": "fires on the first message between two named actors"},
    {"id": "group", "name": "Group of k", "param": "k actors", "values": [3, 5, 10, 20], "default": None,
     "what": "fires when k or more actors are linked into one group by messages"},
]
FAMILY = {f["id"]: f for f in FAMILIES}


def default_out():
    env = os.environ.get("SWARM_TRACER_EARLYWARN_DIR")
    if env:
        return env
    if os.path.isdir(os.path.join(REPO, "reports")) or os.path.isdir(os.path.join(REPO, ".git")):
        return os.path.join(REPO, "reports", "earlywarn")
    return os.path.join(os.path.expanduser("~"), ".swarm-tracer", "earlywarn")


# ------------------------------------------------------------------ statistics

def _pois_cdf(k, lam):
    """P(X <= k) for X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0
    term = math.exp(-lam)
    total = term
    for i in range(1, k + 1):
        term *= lam / i
        total += term
    return min(1.0, total)


def poisson_ci(k, exposure, alpha=0.05):
    """Exact (Garwood) interval for a Poisson rate: k events seen in `exposure` units. Returns (lo, hi) per unit."""
    if exposure <= 0:
        return None, None
    lo = 0.0
    if k > 0:
        a, b = 0.0, k + 1.0
        for _ in range(80):          # smallest lam with P(X >= k | lam) = alpha / 2
            m = (a + b) / 2
            if 1 - _pois_cdf(k - 1, m) < alpha / 2:
                a = m
            else:
                b = m
        lo = (a + b) / 2
    a, b = float(k), k + 10 + 10 * math.sqrt(k + 1)
    for _ in range(80):              # largest lam with P(X <= k | lam) = alpha / 2
        m = (a + b) / 2
        if _pois_cdf(k, m) > alpha / 2:
            a = m
        else:
            b = m
    return lo / exposure, ((a + b) / 2) / exposure


def _median(xs):
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _r(x, n=2):
    return None if x is None else round(x, n)


# ------------------------------------------------------------------ extraction: one loaded swarm -> a compact run

def default_rules():
    return live.clean_rules(json.loads(json.dumps(live.DEFAULT_RULES)))


def extract(s, truth=None, meta=None):
    """Everything the tables need from one loaded session, times in hours from the first timed action.
    truth (a groundtruth dict) adds the first true harm and the first true message."""
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    run = dict(meta or {})
    run.update({"name": s.name, "records": len(s.events), "dated": t0 is not None, "hours": sim["hours"], "signs": [],
                "rules": {}, "alarms": {}, "first_true_harm_h": None, "first_true_message_h": None, "agents": None})
    if t0 is None:
        return run
    h = lambda t: None if t is None else round((t - t0) / HOUR, 3)
    sigs = sim["signals"]
    run["signs"] = [{"id": g["key"].replace("replay:", "", 1), "kind": g["kind"], "family": g["family"],
                     "name": "Two identities share one place" if g["kind"] == "place" else g["name"], "h": h(g["t"])} for g in sigs]
    for r in live.evaluate_rules(s, default_rules())["rules"]:
        run["rules"][r["id"]] = h(r["t"]) if r["fired"] else None
    al = {}
    harm_signs = [g for g in sigs if g["kind"] == "harm"]
    al["watch"] = {str(k): h(harm_signs[k - 1]["t"]) if len(harm_signs) >= k else None for k in FAMILY["watch"]["values"]}
    al["coord"] = {}
    for n in FAMILY["coord"]["values"]:
        hit = live.eval_condition(s, {"type": "coordination_kinds", "n": n}, sigs)
        al["coord"][str(n)] = h(hit["t"]) if hit else None
    times, intents = s.rec["_times"], s.rec["_intents"]
    pts = [times[e.id] for e in s.events if e.id in times and intents.get(e.id)]
    harm = s.harm_sorted
    al["volume"] = {}
    for k in FAMILY["volume"]["values"]:
        b = evaluate.rate_alarm(pts, harm, k=float(k))
        al["volume"][str(k)] = h(evaluate._parse(b["hour"]) + HOUR) if b else None
    pl = next((g for g in sigs if g["key"] == "replay:coordination: two identities use one place"), None)
    al["place"] = {"1": h(pl["t"]) if pl else None}
    msg = next((g for g in sigs if g["key"] == "message"), None)
    al["message"] = {"1": h(msg["t"]) if msg else None}
    al["group"] = {}
    for k in FAMILY["group"]["values"]:
        g = next((g for g in sigs if g["key"] == f"group{k}"), None)
        al["group"][str(k)] = h(g["t"]) if g else None
    run["alarms"] = al
    if truth:
        recs = truth["records"]
        fh = [recs[r]["t"] for r in truth.get("harm", []) if r in recs]
        fm = [recs[r]["t"] for _, r, *_ in truth.get("messages", []) if r in recs]
        run["first_true_harm_h"] = h(min(fh)) if fh else None
        run["first_true_message_h"] = h(min(fm)) if fm else None
        run["agents"] = len(truth.get("agents", {})) or (truth.get("params") or {}).get("agents")
    return run


# ------------------------------------------------------------------ the forward test

def _swarm_run(folder, params, setting, label, seed):
    truth = groundtruth.make(folder, seed=seed, **params)
    s = validation._load(folder, truth)
    mode = truth.get("mode", "coordinated")
    return extract(s, truth, {"setting": setting, "label": label, "seed": seed, "mode": mode,
                              "agents": (truth.get("params") or {}).get("agents")})


def _fire_summary(rows, key):
    """rows: list of runs; key(run) -> hour or None."""
    return [key(r) for r in rows]


def _lead_stats(runs, getter, truth_key):
    fired = [(getter(r), r[truth_key]) for r in runs if getter(r) is not None]
    leads = [t - g for g, t in fired if t is not None]
    return {"n": len(runs), "fired": len(fired),
            "median_lead_h": _r(_median(leads)), "min_lead_h": _r(min(leads)) if leads else None,
            "max_lead_h": _r(max(leads)) if leads else None, "leads_n": len(leads)}


def sign_ids(runs):
    seen = {}
    for r in runs:
        for g in r["signs"]:
            seen.setdefault(g["id"], g)
    return seen


def forward_table(runs):
    """Per sign and per default rule: fired or not, and lead time before the first true harm and message."""
    coord = [r for r in runs if r["mode"] != "benign" and r["dated"]]
    benign = [r for r in runs if r["mode"] == "benign" and r["dated"]]
    sign_get = lambda sid: (lambda r: next((g["h"] for g in r["signs"] if g["id"] == sid), None))
    rows = []
    meta = sign_ids(runs)
    for sid, g in sorted(meta.items(), key=lambda kv: (kv[1]["family"] != "single", kv[1]["family"] != "joint", kv[0])):
        get = sign_get(sid)
        rows.append({"id": sid, "name": g["name"], "family": g["family"], "kind": g["kind"],
                     "coordinated": {**{"harm": _lead_stats(coord, get, "first_true_harm_h")},
                                     "message": _lead_stats(coord, get, "first_true_message_h")},
                     "benign": {"n": len(benign), "fired": sum(1 for r in benign if get(r) is not None)}})
    rules = []
    for rid in DEFAULT_RULE_IDS:
        get = lambda r, rid=rid: r["rules"].get(rid)
        name = next((x["name"] for x in live.DEFAULT_RULES if x["id"] == rid), rid)
        rules.append({"id": rid, "name": name,
                      "coordinated": {"harm": _lead_stats(coord, get, "first_true_harm_h"),
                                      "message": _lead_stats(coord, get, "first_true_message_h")},
                      "benign": {"n": len(benign), "fired": sum(1 for r in benign if get(r) is not None)}})
    by_setting = []
    for name, label, _ in validation.SETTINGS:
        rs = [r for r in runs if r.get("setting") == name and r["dated"]]
        if not rs:
            continue
        by_setting.append({"setting": name, "label": label, "mode": rs[0]["mode"], "runs": len(rs),
                           "rules": {rid: sum(1 for r in rs if r["rules"].get(rid) is not None) for rid in DEFAULT_RULE_IDS}})
    return {"signs": rows, "rules": rules, "by_setting": by_setting, "coordinated_runs": len(coord), "benign_runs": len(benign)}


# ------------------------------------------------------------------ false alarms

def false_alarms(runs):
    """Alarms per 24 h of trace time on benign runs, for every sign and rule that fired at least once, and for each
    default rule even if it never did. A sign or rule is counted once per run (its first fire): a rule that could
    fire again after being acknowledged would add to these, so they are lower bounds for it."""
    benign = [r for r in runs if r["mode"] == "benign" and r["dated"]]
    hours = sum(r["hours"] for r in benign)
    agent_hours = sum(r["hours"] * (r.get("agents") or 0) for r in benign)
    days = hours / 24.0

    def row(kind, ident, name, count):
        lo, hi = poisson_ci(count, days) if days else (None, None)
        return {"kind": kind, "id": ident, "name": name, "alarms": count, "per_24h": _r(count / days, 3) if days else None,
                "ci_low": _r(lo, 3), "ci_high": _r(hi, 3), "zero_bound": _r(3.0 / days, 3) if days and count == 0 else None}
    rows = []
    for rid in DEFAULT_RULE_IDS:
        name = next((x["name"] for x in live.DEFAULT_RULES if x["id"] == rid), rid)
        rows.append(row("rule", rid, name, sum(1 for r in benign if r["rules"].get(rid) is not None)))
    meta = sign_ids(runs)
    for sid, g in meta.items():
        c = sum(1 for r in benign if any(x["id"] == sid for x in r["signs"]))
        if c:
            rows.append(row("sign", sid, g["name"], c))
    for sid, g in meta.items():     # signs that fired on coordinated runs and never on benign ones
        if not any(r["id"] == sid for r in rows) and sid not in ("rate_harm",):
            rows.append(row("sign", sid, g["name"], 0))
    rows.sort(key=lambda r: (r["kind"] != "rule", -r["alarms"], r["id"]))
    return {"benign_runs": len(benign), "trace_hours": round(hours, 1), "trace_days": _r(days, 2),
            "agent_hours": round(agent_hours), "rows": rows,
            "caveat": "Simulated benign swarms only. No real benign multi-agent traffic with model-written code was available "
                      "(a real framework run needs a model key). Each sign or rule is counted once per swarm."}


# ------------------------------------------------------------------ cost curve

def cost_curve(runs):
    coord = [r for r in runs if r["mode"] != "benign" and r["dated"]]
    benign = [r for r in runs if r["mode"] == "benign" and r["dated"]]
    days = sum(r["hours"] for r in benign) / 24.0
    fams = []
    for f in FAMILIES:
        pts = []
        for v in f["values"]:
            key = str(v)
            fa = sum(1 for r in benign if r["alarms"].get(f["id"], {}).get(key) is not None)
            leads = [r["first_true_harm_h"] - r["alarms"][f["id"]][key] for r in coord
                     if r["alarms"].get(f["id"], {}).get(key) is not None and r["first_true_harm_h"] is not None]
            fired = sum(1 for r in coord if r["alarms"].get(f["id"], {}).get(key) is not None)
            lo, hi = poisson_ci(fa, days) if days else (None, None)
            pts.append({"value": v, "label": (f"{v}" + ("σ" if f["id"] == "volume" else "")), "default": v == f["default"],
                        "false_alarms": fa, "per_24h": _r(fa / days, 3) if days else None, "ci_low": _r(lo, 3), "ci_high": _r(hi, 3),
                        "zero_bound": _r(3.0 / days, 3) if days and fa == 0 else None,
                        "median_lead_h": _r(_median(leads)), "fired": fired, "coordinated": len(coord),
                        "detect": _r(fired / len(coord), 3) if coord else None})
        fams.append({"id": f["id"], "name": f["name"], "param": f["param"], "what": f["what"], "default": f["default"],
                     "points": pts, "advice": _advice(f, pts)})
    return {"families": fams, "benign_days": _r(days, 2), "coordinated_runs": len(coord), "benign_runs": len(benign),
            "budgets": _budgets(fams)}


def _lead_words(x):
    return f"{abs(x):.1f} h {'before' if x >= 0 else 'after'} the first true harm"


def _advice(f, pts):
    """One plain sentence per family from its own points: the quietest setting that still catches 80%, and the earliest."""
    ok = [p for p in pts if p["detect"] is not None and p["detect"] >= 0.8 and p["median_lead_h"] is not None]
    name = f["name"]
    pname = f"{f['param']} = " if f["param"] else ""
    if not ok:
        return f"{name}: no setting caught at least 80% of the coordinated swarms, so it should not be relied on alone."
    quiet = [p for p in ok if p["false_alarms"] == 0]
    early = max(ok, key=lambda p: p["median_lead_h"])
    fa = lambda p: "no false alarm in any benign swarm" if p["false_alarms"] == 0 else f"about {p['per_24h']} false alarms per day"
    if len(ok) == 1:
        p = ok[0]
        return (f"{name}: it fires a median {_lead_words(p['median_lead_h'])} (caught {p['fired']} of {p['coordinated']}), with {fa(p)}"
                + (f" (a rate below about {p['zero_bound']} per day)." if p["false_alarms"] == 0 else "."))
    if quiet:
        q = max(quiet, key=lambda p: p["median_lead_h"])
        if q is early:
            return f"{name}: pick {pname}{q['value']}, the earliest setting and one that raised no false alarm: a median {_lead_words(q['median_lead_h'])}."
        return (f"{name}: for no false alarms pick {pname}{q['value']} (a median {_lead_words(q['median_lead_h'])}); "
                f"{pname}{early['value']} is earlier ({_lead_words(early['median_lead_h'])}) but raised {fa(early)}.")
    p = min(ok, key=lambda p: (p["per_24h"], -p["median_lead_h"]))
    return (f"{name}: every setting raised false alarms; the quietest ({pname}{p['value']}) gave about {p['per_24h']} per day "
            f"for a median {_lead_words(p['median_lead_h'])}.")


def _budgets(fams):
    out = []
    for budget in (0.0, 0.1, 0.5, 1.0, 5.0):
        best = None
        for f in fams:
            for p in f["points"]:
                if p["per_24h"] is None or p["median_lead_h"] is None or (p["detect"] or 0) < 0.5:
                    continue
                if p["per_24h"] <= budget and (best is None or p["median_lead_h"] > best["median_lead_h"]):
                    best = {"family": f["id"], "name": f["name"], "value": p["value"], "label": p["label"],
                            "median_lead_h": p["median_lead_h"], "per_24h": p["per_24h"], "detect": p["detect"]}
        out.append({"budget_per_24h": budget, "best": best})
    return out


# ------------------------------------------------------------------ frozen signs

def _git(*args):
    try:
        return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def code_hashes():
    out = {}
    for f in CODE_FILES:
        p = os.path.join(REPO, f)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                out[f] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _harm_kinds():
    from . import packs
    out = {}
    for f in ("code_traces.json", "wiki_swarm.json"):
        p = packs.load_pack(os.path.join(HERE, "packs", f))
        out[f] = sorted(p.harm)
    return out


def build_frozen():
    kinds = _harm_kinds()
    signs = []
    for pack, harm in kinds.items():
        for k in harm:
            name, fam = insight.signal_name("first: " + k)
            signs.append({"id": "first: " + k, "name": name, "family": fam, "kind": "harm", "pack": pack,
                          "definition": f"The first record that does what the pack calls '{k}', a harmful action of one actor. Known when that record is seen.",
                          "threshold": "first occurrence", "source": "agenttrace/reconstruct.py replay; agenttrace/insight.py simulate"})
    signs += [
        {"id": "spread: first use of an item seen earlier", "name": "Token seen as data, then used", "family": "single", "kind": "token",
         "definition": "A token appears inside a record as data before any record uses it to authenticate; known when it is first used.",
         "threshold": "first occurrence", "source": "agenttrace/reconstruct.py seen_then_used"},
        {"id": "coordination: two identities use one place", "name": "Two identities share one place", "family": "joint", "kind": "place",
         "definition": "Two different identities name the same shared place (board, dataset) in different records.",
         "threshold": "2 identities, 2 records", "source": "agenttrace/reconstruct.py shared_places"},
        {"id": "coordination: one identity carries another's token", "name": "One identity carries another's token", "family": "joint", "kind": "carried",
         "definition": "A record that authenticates as one identity holds another identity's token before that token's own first use.",
         "threshold": "first occurrence", "source": "agenttrace/reconstruct.py carried edges"},
        {"id": "message", "name": "First message between named actors", "family": "joint", "kind": "message",
         "definition": "An actor reads, from an exact (not coarse) place, what a different named actor wrote there earlier.",
         "threshold": "first occurrence", "source": "agenttrace/messages.py deliveries; insight.simulate"},
        {"id": "group3", "name": "A group of 3+ actors linked by messages", "family": "joint", "kind": "group", "threshold": "k = 3",
         "definition": "Messages join actors into one connected group of at least k.", "source": "agenttrace/insight.py simulate"},
        {"id": "group5", "name": "A group of 5+ actors linked by messages", "family": "joint", "kind": "group", "threshold": "k = 5",
         "definition": "Messages join actors into one connected group of at least k.", "source": "agenttrace/insight.py simulate"},
        {"id": "group10", "name": "A group of 10+ actors linked by messages", "family": "joint", "kind": "group", "threshold": "k = 10",
         "definition": "Messages join actors into one connected group of at least k.", "source": "agenttrace/insight.py simulate"},
        {"id": "group20", "name": "A group of 20+ actors linked by messages", "family": "joint", "kind": "group", "threshold": "k = 20",
         "definition": "Messages join actors into one connected group of at least k.", "source": "agenttrace/insight.py simulate"},
        {"id": "two_way", "name": "First two-way exchange", "family": "joint", "kind": "two_way", "threshold": "first occurrence",
         "definition": "Two named actors have each now sent a message to the other.", "source": "agenttrace/insight.py simulate"},
        {"id": "program2", "name": "First program reused by another actor", "family": "joint", "kind": "program", "threshold": "2 actors",
         "definition": "The same program (text with ids, numbers and hashes masked) is run by a second named actor; routine programs (no shared place, nothing harmful) are ignored.",
         "source": "agenttrace/messages.py content_spread"},
        {"id": "program3", "name": "First program run by three actors", "family": "joint", "kind": "program", "threshold": "3 actors",
         "definition": "A third named actor runs a program already run by two; routine programs are ignored.", "source": "agenttrace/messages.py content_spread"},
        {"id": "rate_all", "name": "Volume alarm on all actions", "family": "baseline", "kind": "baseline",
         "definition": "The first hour whose count of actions exceeds the mean plus 3 standard deviations of every earlier hour (at least 12 earlier hours; standard deviation at least 1). Known at the end of that hour.",
         "threshold": "3 standard deviations; 12 hours of history", "source": "agenttrace/evaluate.py rate_alarm"},
        {"id": "rate_harm", "name": "Volume alarm on harmful actions", "family": "baseline", "kind": "baseline",
         "definition": "The same rule applied to the count of harmful actions per hour.", "threshold": "3 standard deviations; 12 hours of history",
         "source": "agenttrace/evaluate.py rate_alarm"},
    ]
    rules = [{"id": r["id"], "name": r["name"], "severity": r["severity"], "match": r["match"], "conditions": r["conditions"],
              "description": " and ".join(live.describe_condition(c) for c in r["conditions"])} for r in live.DEFAULT_RULES]
    head = _git("rev-parse", "HEAD")
    dirty = [l[3:] for l in _git("status", "--porcelain", "--", "agenttrace").splitlines() if l[3:].startswith("agenttrace/") and l[3:].endswith((".py", ".json"))]
    return {
        "frozen_on": FROZEN_DATE,
        "note": ("Written on 2026-11-13 by the people who built the tool, who by then knew how the Swarm Traces incident unfolded: "
                 "which actions were harmful, in what order, and when. On that incident (and on the wiki swarm, whose pack was written on it) "
                 "the timing of these signs is hindsight, not a test. The forward test uses data they were not written on."),
        "code": {"git_head": head, "uncommitted_code_files_at_freeze": dirty, "sha256": code_hashes(),
                 "how_to_check": "python3 -m agenttrace.earlywarn freeze --check"},
        "signs": signs, "rules": rules,
        "volume_baseline": {"k_sigma": 3.0, "min_history_hours": 12, "min_sd": 1.0},
        "forward_test": {"seeds": list(FORWARD_SEEDS), "settings": [n for n, _, _ in validation.SETTINGS],
                         "rule": "seeds 21-30 were not run before this file was written"},
    }


def freeze(path=FROZEN):
    data = build_frozen()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return data


def load_frozen():
    with open(FROZEN, encoding="utf-8") as f:
        return json.load(f)


def frozen_status():
    """The frozen file and whether the sign code has changed since (hash drift is reported, not an error)."""
    fz = load_frozen()
    now = code_hashes()
    drift = sorted(f for f, h in fz["code"]["sha256"].items() if now.get(f) != h)
    return {"frozen": fz, "drift": drift, "head_now": _git("rev-parse", "HEAD"),
            "same_head": _git("rev-parse", "HEAD") == fz["code"].get("git_head")}


# ------------------------------------------------------------------ data the signs were not written on

def sample_traces():
    """Sample traces under agenttrace/samples that load and have timestamps: (name, path)."""
    root = os.path.join(HERE, "samples")
    out = []
    for f in sorted(os.listdir(root)):
        p = os.path.join(root, f)
        if os.path.isfile(p) and f.endswith((".json", ".jsonl")):
            out.append((f, p))
    return out


def run_samples(log=print):
    from .session import Session
    out = []
    for name, p in sample_traces():
        s = Session()
        try:
            s.load(p, "auto", {}, name)
            r = extract(s, None, {"setting": "sample", "label": name, "mode": "unlabelled", "format": (s.read_report or {}).get("format")})
        except Exception as e:      # a sample that does not load is reported, not hidden
            r = {"name": name, "error": str(e)[:200], "dated": False, "signs": [], "rules": {}, "alarms": {}, "mode": "unlabelled", "hours": 0}
        out.append(r)
        log(f"  sample {name}: {len(r['signs'])} signs, dated={r['dated']}")
    return out


def run_wiki(log=print):
    root = os.path.join(REPO, "full-wiki-logs")
    if not os.path.exists(os.path.join(root, "revisions.jsonl")) or os.path.getsize(os.path.join(root, "revisions.jsonl")) < 1000:
        return {"available": False, "note": "full-wiki-logs/ is empty or missing on this machine."}
    from .session import Session
    s = Session()
    s.load(root, "wiki_swarm.json", {}, "wiki swarm")
    r = extract(s, None, {"setting": "wiki", "label": "wiki swarm", "mode": "real, no independent truth"})
    harm = s.harm_sorted
    t0 = insight.simulate(s).get("start_t")
    first_harm = round((harm[0] - t0) / HOUR, 3) if harm and t0 is not None else None
    r["first_flagged_harm_h"] = first_harm
    r["available"] = True
    r["hindsight"] = True
    r["note"] = ("The wiki pack was written on this incident, so this is not a forward test; 'first harm' is the pipeline's own "
                 "label (the first record the pack marks harmful), not an independent truth.")
    log(f"  wiki swarm: {len(r['signs'])} signs")
    return r


def run_forward(out=None, seeds=FORWARD_SEEDS, settings=None, log=print, wiki=True, samples=True, fname="forward.json"):
    out = out or default_out()
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    from . import identity as idm
    save_dec = idm.SAVE_DECISIONS
    idm.SAVE_DECISIONS = False
    started = time.time()
    tmp = tempfile.mkdtemp(prefix="st_forward_")
    runs = []
    try:
        for name, label, params in validation.SETTINGS:
            if settings and name not in settings:
                continue
            for seed in seeds:
                folder = os.path.join(tmp, f"{name}-s{seed}")
                runs.append(_swarm_run(folder, dict(params), name, label, seed))
                shutil.rmtree(folder, ignore_errors=True)
            log(f"  {name}: {len(seeds)} swarms")
        sample_runs = run_samples(log) if samples else []
        wiki_run = run_wiki(log) if wiki else {"available": False, "note": "not run"}
    finally:
        idm.SAVE_DECISIONS = save_dec
        shutil.rmtree(tmp, ignore_errors=True)
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    summary = summarize(runs, sample_runs, wiki_run)
    summary.update({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seeds": list(seeds),
                    "seconds": round(time.time() - started, 1),
                    "command": "python3 -m agenttrace.earlywarn forward --out " + out + " --seeds " + " ".join(map(str, seeds))})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
        json.dump({**summary, "runs": runs}, f, indent=1)
    return summary


def summarize(runs, sample_runs=None, wiki_run=None):
    fz = None
    try:
        fz = frozen_status()
    except (OSError, ValueError):
        pass
    return {"forward": forward_table(runs), "false_alarms": false_alarms(runs), "cost": cost_curve(runs),
            "samples": [_sample_row(r) for r in (sample_runs or [])], "wiki": wiki_run or {"available": False},
            "frozen_drift": fz["drift"] if fz else None,
            "caveats": ["The swarms are simulated by this tool's own generator: real swarms differ.",
                        "No real benign multi-agent traffic with model-written code was available; a real framework run needs a model key.",
                        "Leads are hours before the first true harm (or true message) in the simulation's own truth file."]}


def _sample_row(r):
    return {"name": r.get("label") or r.get("name"), "format": r.get("format"), "dated": r.get("dated"), "records": r.get("records"),
            "hours": r.get("hours"), "error": r.get("error"),
            "signs": [{"id": g["id"], "name": g["name"], "h": g["h"]} for g in r.get("signs", [])],
            "rules": r.get("rules", {})}


def latest(out=None):
    out = out or default_out()
    # the full run (python3 -m agenttrace.earlywarn forward) wins; the in-app quick run never overwrites it
    p = next((q for q in (os.path.join(out, "forward.json"), os.path.join(out, "forward_quick.json")) if os.path.exists(q)), None)
    if p is None:
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d.pop("runs", None)
    return d


# ------------------------------------------------------------------ your own trace

def run_trace(path, pack="auto", out=None, log=print):
    """The same tables for one trace of your own. If it is benign, the 'false alarms' table is your false-alarm rate;
    if it has no truth file, leads are not computed (no truth), only when each sign and rule fired."""
    from .session import Session
    s = Session()
    s.load(path, pack, {}, os.path.basename(path))
    truth = None
    tp = groundtruth.truth_path_for(path) if hasattr(groundtruth, "truth_path_for") else None
    if tp and os.path.exists(tp):
        truth = groundtruth.load_truth(tp)
    r = extract(s, truth, {"setting": "mine", "label": os.path.basename(path), "mode": (truth or {}).get("mode", "unlabelled")})
    n_agents = len({a for a, k in s.actor.values() if k != "run"})
    r["agents"] = r["agents"] or n_agents
    res = {"run": r, "rules_fired": {k: v for k, v in r["rules"].items()},
           "agent_hours": round((r["hours"] or 0) * (r["agents"] or 0))}
    benign = r["mode"] == "benign"
    asbenign = dict(r, mode="benign")
    res["if_benign"] = false_alarms([asbenign])
    res["note"] = ("These rows are false alarms only if the trace really is benign: you decide that, the tool cannot. "
                   "One trace gives wide intervals; the exposure above says how much was observed.")
    res["declared_benign"] = benign
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "earlywarn.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return res


# ------------------------------------------------------------------ app endpoints

_RUN = {"thread": None, "status": "idle", "error": None}


def _summary(state, q):
    d = latest()
    if d is None:
        return {"ran": False, "running": _RUN["status"] == "running", "command": "python3 -m agenttrace.earlywarn forward"}
    d["ran"] = True
    d["running"] = _RUN["status"] == "running"
    return d


def _frozen(state, q):
    return frozen_status()


def _release(state, q):
    """On the loaded dataset (no truth): when each default rule and each sign fires. For orientation only."""
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset loaded")
    r = extract(s, None, {"setting": "loaded", "label": s.name, "mode": "no truth"})
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    ev = live.evaluate_rules(s)
    fams = []
    for f in FAMILIES:
        pts = []
        for v in f["values"]:
            h = r["alarms"].get(f["id"], {}).get(str(v))
            pts.append({"value": v, "h": h, "default": v == f["default"]})
        fams.append({"id": f["id"], "name": f["name"], "points": pts})
    return {"dataset": s.name, "pack": s.pack.name, "dated": r["dated"], "start": sim.get("start"), "hours": r["hours"],
            "rules": [{"id": x["id"], "name": x["name"], "fired": x["fired"], "time": x.get("time"),
                       "h": r["rules"].get(x["id"])} for x in ev["rules"]],
            "families": fams, "no_truth": True,
            "note": "No truth on a real release: this shows where each rule fires on the replay, not how early it was."}


def _run_post(state, q, body):
    if _RUN["status"] == "running":
        return {"running": True}
    try:
        req = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("body must be JSON")
    if not isinstance(req, dict) or not req.get("run"):
        raise ValueError('send {"run": true} (and "quick": false for the full ten seeds) to start a run')
    quick = bool(req.get("quick", True))

    def work():
        _RUN.update(status="running", error=None)
        try:
            run_forward(seeds=(FORWARD_SEEDS[0],) if quick else FORWARD_SEEDS, wiki=False, log=lambda *_: None, fname="forward_quick.json")
            _RUN["status"] = "done"
        except Exception as e:
            _RUN.update(status="error", error=str(e)[:200])
    t = threading.Thread(target=work, daemon=True)
    _RUN["thread"] = t
    t.start()
    return {"running": True, "quick": quick}


GET = {"earlywarn_summary": _summary, "earlywarn_frozen": _frozen, "earlywarn_release": _release}
POST = {"earlywarn_run": _run_post}


# ------------------------------------------------------------------ command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.earlywarn", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze", help="write claims/frozen_signs.json (or --check for drift)")
    f.add_argument("--check", action="store_true")
    w = sub.add_parser("forward", help="forward test, false alarms and cost curve on new simulated swarms")
    w.add_argument("--out", default=None)
    w.add_argument("--seeds", type=int, nargs="*", default=list(FORWARD_SEEDS))
    w.add_argument("--no-wiki", action="store_true")
    r = sub.add_parser("run", help="the same tables for your own trace")
    r.add_argument("trace")
    r.add_argument("--pack", default="auto")
    r.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "freeze":
        if a.check:
            st = frozen_status()
            print("code unchanged since the freeze" if not st["drift"] else "changed since the freeze: " + ", ".join(st["drift"]))
            return 0
        d = freeze()
        print(f"wrote {FROZEN}: {len(d['signs'])} signs, {len(d['rules'])} rules, git {d['code']['git_head'][:10]}")
    elif a.cmd == "forward":
        sm = summarize_and_print(run_forward(a.out, tuple(a.seeds), wiki=not a.no_wiki))
    elif a.cmd == "run":
        res = run_trace(a.trace, a.pack, a.out)
        print(json.dumps({"rules_fired": res["rules_fired"], "agent_hours": res["agent_hours"],
                          "signs": [(g["id"], g["h"]) for g in res["run"]["signs"]]}, indent=1))
        fa = res["if_benign"]
        print(f"\nIf this trace is benign: {fa['trace_hours']} trace hours, {fa['agent_hours']} agent-hours observed")
        for x in fa["rows"]:
            print(f"  {x['kind']:<5} {x['name'][:52]:<52} alarms {x['alarms']}  per 24 h {x['per_24h']}  95% {x['ci_low']}..{x['ci_high']}")
        print("\n" + res["note"])
    return 0


def summarize_and_print(sm):
    fa = sm["false_alarms"]
    print(f"forward test: {sm['forward']['coordinated_runs']} coordinated, {sm['forward']['benign_runs']} benign swarms; "
          f"{fa['trace_hours']} benign trace hours, {fa['agent_hours']} agent-hours")
    for x in sm["forward"]["rules"]:
        c = x["coordinated"]["harm"]
        print(f"  {x['name']}: coordinated {c['fired']}/{c['n']}, median lead {c['median_lead_h']} h; benign {x['benign']['fired']}/{x['benign']['n']}")
    return sm


if __name__ == "__main__":
    sys.exit(main())

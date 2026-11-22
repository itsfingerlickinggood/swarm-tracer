"""Early warning: the simple alarms first, the shared-control signs as context.

Since v2.3.0 the main early-warning feature is four simple alarms (agenttrace/baselines.py: first new host after
12 h, first search-for-secrets action, a distinct-actor alarm, a volume alarm with 6 h of history). The signs of
shared control (a shared place, a carried token, messages, groups, shared programs) are kept as context, "who shares
control", and are labelled as not an early warning: on the real release they fired later than every simple alarm.

What is and is not evidence:
1. The four alarms were picked after seeing the one real incident (post-hoc on one incident; baselines.POST_HOC).
2. Their benign false-alarm rate is measured on every benign set there is (simulated benign swarms, the independent
   generator's look-alike classes, the bundled benign sample, and real traces under datasets-ext/ when present).
3. reports/earlywarn/prereg_v23.json freezes the alarms, their parameters (with a SHA-256), the seeds and three
   hypotheses BEFORE any swarm with those seeds is generated; `forward23` then runs the test and saves the results.
4. Shares are given with per-swarm binomial (Wilson) intervals and with intervals that resample whole settings.

    python3 -m agenttrace.earlywarn alarms TRACE --pack PACK    # the main alarms, then the context, for a trace
    python3 -m agenttrace.earlywarn prereg23                    # write reports/earlywarn/prereg_v23.json (once)
    python3 -m agenttrace.earlywarn forward23                   # the pre-registered forward test, both generators
    python3 -m agenttrace.earlywarn external                    # benign false alarms on real traces in datasets-ext/
    python3 -m agenttrace.earlywarn release                     # the real release: alarms and context, harm still to come
    python3 -m agenttrace.earlywarn freeze                      # rewrite claims/frozen_signs.json (the v2.2.0 signs)
    python3 -m agenttrace.earlywarn forward --out reports/earlywarn [--seeds 31 32 ...]   # the v2.2.0 forward test
    python3 -m agenttrace.earlywarn run TRACE --pack PACK --out DIR   # the same tables for your own trace
    GET  /api/x/earlywarn_main        the main alarms and the context on the loaded dataset, with the saved evidence
    GET  /api/x/earlywarn_summary     the latest forward-test summary (or {"ran": false})
    GET  /api/x/earlywarn_frozen      the frozen file and whether the code has drifted since
    GET  /api/x/earlywarn_release     where each default rule fires on the loaded dataset (no truth)
    POST /api/x/earlywarn_run         {run: true, quick: true}: a one-seed forward test, in the background

The simulations are ours. Real benign traces, where present, have no timestamps, so the time-based alarms cannot be
scored on them; that is reported as not measurable, never as zero false alarms.
"""
import argparse
import bisect
import datetime as dt
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict

from . import baselines, evaluate, groundtruth, indepgen, insight, live, validation

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FROZEN = os.path.join(HERE, "claims", "frozen_signs.json")
FROZEN_DATE = "2026-11-16"
FORWARD_SEEDS = tuple(range(31, 41))        # v2.2.0: fresh seeds (21-30 were the v2.1.0 forward run and have been seen)
INDEP_SEEDS = tuple(range(501, 511))        # the independent generator: no seed of it has been run before the freeze
INDEP_CELL = "chrono_epoch60"
HOUR = 3600.0
CODE_FILES = ["agenttrace/insight.py", "agenttrace/live.py", "agenttrace/evaluate.py", "agenttrace/reconstruct.py",
              "agenttrace/messages.py", "agenttrace/packs/code_traces.json", "agenttrace/packs/wiki_swarm.json",
              "agenttrace/baselines.py", "agenttrace/groundtruth.py", "agenttrace/indepgen.py", "agenttrace/earlywarn.py"]
DEFAULT_RULE_IDS = ("watch-harm", "alert-coord2", "baseline-volume")

# v2.3.0: the pre-registered forward test of the simple alarms. No swarm with these seeds existed in any earlier run
# (the original generator has been run with seeds 21-40, the independent one with 501-510).
V23_SEEDS = tuple(range(41, 51))
V23_INDEP_SEEDS = tuple(range(511, 521))
V23_PREREG = "prereg_v23.json"
V23_FILES = {"forward": "forward_v23.json", "independent": "forward_v23_independent.json", "summary": "summary_v23.json",
             "external": "benign_external_v23.json", "release": "release_v23.json"}
V23_CODE_FILES = ["agenttrace/baselines.py", "agenttrace/earlywarn.py", "agenttrace/evaluate.py", "agenttrace/insight.py",
                  "agenttrace/reconstruct.py", "agenttrace/messages.py", "agenttrace/live.py", "agenttrace/session.py",
                  "agenttrace/model.py", "agenttrace/groundtruth.py", "agenttrace/indepgen.py", "agenttrace/validation.py",
                  "agenttrace/packs/code_traces.json"]
PLACE_SIGN = "coordination: two identities use one place"
CARRIED_SIGN = "coordination: one identity carries another's token"
ANY_MAIN = "any_main"
EXTERNAL_ROOT = os.path.join(REPO, "datasets-ext")
EXTERNAL_MAX_BYTES = 30 * 1024 * 1024
# what each known folder under datasets-ext/ is, by its publisher's own description. benign False: left out of the
# benign measurement. A folder not listed here is measured and marked as labelled by nobody.
EXTERNAL_SETS = {
    "who_and_when": {"benign": True, "what": "agent teams solving tasks, with task failures and no attack (Who&When)"},
    "mast_data": {"benign": True, "what": "multi-agent systems solving tasks, with failure annotations and no attack (MAST)"},
    "moltbook-observatory": {"benign": True, "what": "public posts and comments of AI agents on a social site, one trace per community: "
                                                     "ordinary traffic, not an attack, and labelled benign by nobody"},
    "salt-agent-collusion": {"benign": False, "what": "a collusion experiment (its agents may collude), so it is not a benign set"},
}

# the rule families of the cost curve: a threshold swept over values; `default` is the frozen default (None: no default)
FAMILIES = [
    {"id": "newhost", "name": "New host (main alarm)", "param": "hours of history", "values": [12, 24], "default": 12,
     "what": "fires on the first action, after that many hours, that contacts a host not seen before"},
    {"id": "secrets", "name": "Secrets search (main alarm)", "param": "", "values": [1], "default": 1,
     "what": "fires on the first action the pack labels search_for_secrets"},
    {"id": "actors", "name": "Distinct actors (main alarm)", "param": "sigma", "values": [3], "default": 3,
     "what": "fires on the first hour with more distinct named actors than the mean plus 3 standard deviations of every earlier hour (12 h of history)"},
    {"id": "volume6", "name": "Volume, 6 h history (main alarm)", "param": "sigma", "values": [3], "default": 3,
     "what": "fires on the first hour whose action count is more than 3 standard deviations above every earlier hour (6 h of history)"},
    {"id": "watch", "name": "Watch rule", "param": "kinds of harmful action seen", "values": [1, 2, 3], "default": 1,
     "what": "the watch rule fires when k different kinds of harmful action have been seen"},
    {"id": "coord", "name": "N kinds of coordination", "param": "N", "values": [1, 2, 3, 4, 5], "default": 2,
     "what": "fires when N different kinds of coordination sign (shared place, carried token, message, group, two-way exchange, shared program) have shown"},
    {"id": "volume", "name": "Volume alarm, 12 h history", "param": "sigma", "values": [2, 3, 4, 5], "default": 3,
     "what": "fires on the first hour whose action count is more than k standard deviations above every earlier hour"},
    {"id": "place", "name": "Shared place", "param": "", "values": [1], "default": None,
     "what": "context, not an early warning: fires when two different identities name the same shared place in different records (one sign on its own)"},
    {"id": "message", "name": "First message", "param": "", "values": [1], "default": None,
     "what": "fires on the first message between two named actors"},
    {"id": "group", "name": "Group of k", "param": "k actors", "values": [3, 5, 10, 20], "default": None,
     "what": "fires when k or more actors are linked into one group by messages"},
]
FAMILY = {f["id"]: f for f in FAMILIES}
MAIN_FAMILIES = ("newhost", "secrets", "actors", "volume6")


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


def wilson(k, n, z=1.96):
    """Wilson 95% interval for k of n swarms (each swarm counted once: a Bernoulli outcome, not a Poisson count)."""
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, mid - half), 3), round(min(1.0, mid + half), 3)]


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
    rule_t = {}
    for r in live.evaluate_rules(s, default_rules())["rules"]:
        run["rules"][r["id"]] = h(r["t"]) if r["fired"] else None
        rule_t[r["id"]] = r["t"] if r["fired"] else None
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
    base_t = baselines.alarms(s)
    al["baseline"] = {k: h(t) for k, t in base_t.items()}
    al["newhost"] = {"12": al["baseline"]["new_host_12h"], "24": al["baseline"]["new_host_24h"]}
    al["secrets"] = {"1": al["baseline"]["first_intent"]}
    al["actors"] = {"3": al["baseline"]["distinct_actors"]}
    al["volume6"] = {"3": al["baseline"]["volume_6h"]}
    run["alarms"] = al
    if truth:
        recs = truth["records"]
        fh = sorted(recs[r]["t"] for r in truth.get("harm", []) if r in recs)
        fm = [recs[r]["t"] for _, r, *_ in truth.get("messages", []) if r in recs]
        # the release's measure, on the generator's truth: the share of true harmful records after the alarm
        share = lambda t: None if t is None or not fh else round((len(fh) - bisect.bisect_right(fh, t)) / len(fh), 4)
        run["true_harm_n"] = len(fh)
        run["true_share"] = {"alarm": {k: share(t) for k, t in base_t.items()},
                             "sign": {g["key"].replace("replay:", "", 1): share(g["t"]) for g in sigs},
                             "rule": {k: share(t) for k, t in rule_t.items()}}
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


def _boot_median(groups, draws=1000, seed=11):
    """95% percentile interval of the median of pooled values, resampling whole groups (settings) with replacement.
    groups: list of lists of values. Settings that share seeds are not independent swarms, so the setting is the unit."""
    groups = [g for g in groups if g]
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(draws):
        pool = [x for _ in groups for x in groups[rng.randrange(len(groups))]]
        meds.append(_median(pool))
    meds.sort()
    return [_r(meds[int(0.025 * draws)]), _r(meds[min(draws - 1, int(0.975 * draws))])]


def _lead_stats(runs, getter, truth_key):
    fired = [(getter(r), r[truth_key], r.get("setting")) for r in runs if getter(r) is not None]
    leads = [t - g for g, t, _ in fired if t is not None]
    by = defaultdict(list)
    for g, t, st in fired:
        if t is not None:
            by[st].append(t - g)
    rng = random.Random(5)
    swarm_ci = None
    if len(leads) >= 2:
        meds = sorted(_median([leads[rng.randrange(len(leads))] for _ in leads]) for _ in range(1000))
        swarm_ci = [_r(meds[25]), _r(meds[974])]
    return {"n": len(runs), "fired": len(fired),
            "median_lead_h": _r(_median(leads)), "min_lead_h": _r(min(leads)) if leads else None,
            "max_lead_h": _r(max(leads)) if leads else None, "leads_n": len(leads),
            "share_lead_positive": _r(sum(1 for x in leads if x > 0) / len(leads), 3) if leads else None,
            "median_ci_swarms": swarm_ci, "median_ci_settings": _boot_median(list(by.values())),
            "settings_firing": len(by)}


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
    base_rows = []
    for key, name in baselines.BASELINES:
        get = lambda r, key=key: (r["alarms"].get("baseline") or {}).get(key)
        base_rows.append({"id": key, "name": name,
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
    return {"signs": rows, "rules": rules, "baselines": base_rows, "by_setting": by_setting, "coordinated_runs": len(coord), "benign_runs": len(benign)}


# ------------------------------------------------------------------ the main alarms and the context, per swarm

def _boot_share(groups, draws=1000, seed=13):
    """95% percentile interval of a pooled share, resampling whole settings with replacement. groups: [(k, n), ...].
    Swarms of one setting share its parameters and settings share seeds, so the setting is the unit."""
    groups = [g for g in groups if g[1]]
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        k = n = 0
        for _ in groups:
            a, b = groups[rng.randrange(len(groups))]
            k += a
            n += b
        vals.append(k / n)
    vals.sort()
    return [round(vals[int(0.025 * draws)], 3), round(vals[min(draws - 1, int(0.975 * draws))], 3)]


def _share_block(rows, hit):
    """k of n swarms for which hit(run) is true: the count, the per-swarm binomial (Wilson) interval, and the interval
    that resamples whole settings."""
    by = defaultdict(lambda: [0, 0])
    k = 0
    for r in rows:
        ok = bool(hit(r))
        k += ok
        by[r.get("setting")][0] += ok
        by[r.get("setting")][1] += 1
    n = len(rows)
    return {"k": k, "n": n, "share": _r(k / n, 3) if n else None, "ci": wilson(k, n),
            "ci_settings": _boot_share([tuple(v) for v in by.values()]), "settings": len(by),
            "by_setting": {str(st): v for st, v in sorted(by.items(), key=lambda kv: str(kv[0]))}}


def _main_getter(aid):
    if aid == ANY_MAIN:
        def get(r):
            v = [(r["alarms"].get("baseline") or {}).get(i) for i in baselines.MAIN_IDS]
            v = [x for x in v if x is not None]
            return min(v) if v else None
        return get
    return lambda r: (r["alarms"].get("baseline") or {}).get(aid)


def _main_share(aid):
    """Share of true harm still to come when the alarm fires; 0 when it never fires; None when the run has no truth."""
    def get(r):
        ts = (r.get("true_share") or {}).get("alarm")
        if ts is None:
            return None
        ids = baselines.MAIN_IDS if aid == ANY_MAIN else (aid,)
        v = [ts.get(i) for i in ids if ts.get(i) is not None]
        return max(v) if v else 0.0
    return get


def _sign_share(sid, kind="sign"):
    def get(r):
        ts = (r.get("true_share") or {}).get(kind)
        if ts is None:
            return None
        v = ts.get(sid)
        return 0.0 if v is None else v
    return get


def alarm_stats(runs, getter, share=None, versus=None):
    """One alarm (or sign) over a set of runs. Coordinated swarms: fired, fired before the first true harm (each k of
    n with a Wilson interval and a settings-resampled interval), the median lead with both intervals, and the median
    share of true harm still to come (never fired counts as 0). `versus` is the share getter of the sign it is
    compared with: the count of swarms where this alarm has strictly more harm still to come. Benign swarms: fired k
    of n with both intervals, and alarms per 24 h of trace with the exact Poisson interval."""
    coord = [r for r in runs if r["mode"] != "benign" and r["dated"]]
    benign = [r for r in runs if r["mode"] == "benign" and r["dated"]]
    lead = _lead_stats(coord, getter, "first_true_harm_h")
    c = {"n": len(coord), "fired": _share_block(coord, lambda r: getter(r) is not None),
         "before_harm": _share_block(coord, lambda r: getter(r) is not None and r.get("first_true_harm_h") is not None
                                     and getter(r) < r["first_true_harm_h"]),
         "median_lead_h": lead["median_lead_h"], "median_ci_swarms": lead["median_ci_swarms"],
         "median_ci_settings": lead["median_ci_settings"], "min_lead_h": lead["min_lead_h"], "max_lead_h": lead["max_lead_h"],
         "harm_share_median": None, "harm_share_ci_settings": None, "beats": None}
    if share is not None:
        vals = [(share(r), r.get("setting")) for r in coord]
        vals = [(v, st) for v, st in vals if v is not None]
        if vals:
            by = defaultdict(list)
            for v, st in vals:
                by[st].append(v)
            c["harm_share_median"] = _r(_median([v for v, _ in vals]), 3)
            c["harm_share_ci_settings"] = _boot_median(list(by.values()), seed=17)
            c["harm_share_n"] = len(vals)
        if versus is not None:
            pairs = [r for r in coord if share(r) is not None and versus(r) is not None]
            if pairs:
                c["beats"] = _share_block(pairs, lambda r: share(r) > versus(r))
                c["beats"]["ties"] = sum(1 for r in pairs if share(r) == versus(r))
    days = sum(r["hours"] for r in benign) / 24.0
    fa = _share_block(benign, lambda r: getter(r) is not None)
    lo, hi = poisson_ci(fa["k"], days) if days else (None, None)
    b = {"n": len(benign), "fired": fa, "trace_days": _r(days, 2), "per_24h": _r(fa["k"] / days, 3) if days else None,
         "ci_low": _r(lo, 3), "ci_high": _r(hi, 3)}
    return {"coordinated": c, "benign": b}


def main_table(runs):
    """The four main alarms, 'any of the four' (what an operator who runs all four hears first), and the two variants."""
    place = _sign_share(PLACE_SIGN)
    rows = []
    spec = [(a["id"], a["name"], a["short"], "main") for a in baselines.MAIN_ALARMS]
    spec.append((ANY_MAIN, "Any of the four main alarms (the first to fire)", "Any of the four", "any"))
    spec += [(a["id"], a["name"], a["short"], "variant") for a in baselines.VARIANTS]
    for aid, name, short, role in spec:
        rows.append({"id": aid, "name": name, "short": short, "role": role,
                     **alarm_stats(runs, _main_getter(aid), _main_share(aid), place)})
    return rows


def context_table(runs):
    """The signs of shared control and the old Alert rule, by the same measures: context, not an early warning."""
    meta = dict(sign_ids(runs))
    # the two shared-control signs are always listed, also where they never fired
    meta.setdefault(PLACE_SIGN, {"name": "Two identities share one place", "kind": "place", "family": "joint"})
    meta.setdefault(CARRIED_SIGN, {"name": "One identity carries another's token", "kind": "carried", "family": "joint"})
    rows = []
    order = lambda kv: (kv[1]["kind"] not in baselines.SHARED_CONTROL_KINDS, kv[0])
    for sid, g in sorted(((k, v) for k, v in meta.items() if baselines.is_context(v)), key=order):
        get = lambda r, sid=sid: next((x["h"] for x in r["signs"] if x["id"] == sid), None)
        rows.append({"id": sid, "name": g["name"], "kind": g["kind"], "role": "context",
                     "shared_control": g["kind"] in baselines.SHARED_CONTROL_KINDS,
                     **alarm_stats(runs, get, _sign_share(sid))})
    name = next((x["name"] for x in live.DEFAULT_RULES if x["id"] == "alert-coord2"), "alert-coord2")
    rows.append({"id": "alert-coord2", "name": name, "kind": "rule", "role": "context", "shared_control": False,
                 **alarm_stats(runs, lambda r: r["rules"].get("alert-coord2"), _sign_share("alert-coord2", "rule"))})
    return rows


HYPOTHESES = [
    {"id": "H1", "name": "lead",
     "statement": "The alarm fires before the first true harm in more than half of the coordinated swarms "
                  "(lower end of the per-swarm 95% binomial interval above 0.5).",
     "expected": "Expected to fail: on seeds 31-40 and 501-510 every simple alarm fired at or after the first true harm."},
    {"id": "H2", "name": "order",
     "statement": "The alarm fires with strictly more true harm still to come than the shared-place sign (a sign or alarm "
                  "that never fires counts as 0) in more than half of the coordinated swarms (lower end of the interval above 0.5). "
                  "This is the order seen post-hoc on the real release.",
     "expected": "Expected to fail on the original simulator: on four swarms of seeds 21-22 (seen before, checked while this "
                 "code was written) the shared-place sign had more true harm still to come every time. On the independent "
                 "generator the shared-place sign fired in 0 of 20 swarms before, so there the alarms should win by default."},
    {"id": "H3", "name": "false alarms",
     "statement": "The alarm fires in fewer than 20% of the benign swarms (upper end of the per-swarm 95% binomial interval below 0.2).",
     "expected": "Expected to hold for the new-host alarm (0/30 and 2/50 before) and to fail for the 6 h volume alarm on the independent generator (19/50 before)."},
]


def hypotheses(main_rows):
    """Each pre-registered hypothesis for each main alarm and for 'any of the four': the count, the interval, the verdict."""
    out = []
    for row in main_rows:
        if row["role"] not in ("main", "any"):
            continue
        c, b = row["coordinated"], row["benign"]
        tests = [("H1", c["before_harm"], lambda blk: blk["ci"] is not None and blk["ci"][0] > 0.5),
                 ("H2", c["beats"], lambda blk: blk["ci"] is not None and blk["ci"][0] > 0.5),
                 ("H3", b["fired"], lambda blk: blk["ci"] is not None and blk["ci"][1] < 0.2)]
        for hid, blk, ok in tests:
            if blk is None or not blk["n"]:
                out.append({"hypothesis": hid, "alarm": row["id"], "k": None, "n": 0, "ci": None, "holds": None})
            else:
                out.append({"hypothesis": hid, "alarm": row["id"], "k": blk["k"], "n": blk["n"], "ci": blk["ci"],
                            "ci_settings": blk["ci_settings"], "holds": bool(ok(blk))})
    return out


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
                "ci_low": _r(lo, 3), "ci_high": _r(hi, 3), "zero_bound": _r(3.0 / days, 3) if days and count == 0 else None,
                "swarms": len(benign), "swarm_share": _r(count / len(benign), 3) if benign else None,
                "swarm_share_ci": wilson(count, len(benign))}
    rows = []
    for rid in DEFAULT_RULE_IDS:
        name = next((x["name"] for x in live.DEFAULT_RULES if x["id"] == rid), rid)
        rows.append(row("rule", rid, name, sum(1 for r in benign if r["rules"].get(rid) is not None)))
    for key, bname in baselines.BASELINES:
        rows.append(row("baseline", key, bname, sum(1 for r in benign if (r["alarms"].get("baseline") or {}).get(key) is not None)))
    meta = sign_ids(runs)
    for sid, g in meta.items():
        c = sum(1 for r in benign if any(x["id"] == sid for x in r["signs"]))
        if c:
            rows.append(row("sign", sid, g["name"], c))
    for sid, g in meta.items():     # signs that fired on coordinated runs and never on benign ones
        if not any(r["id"] == sid for r in rows) and sid not in ("rate_harm",):
            rows.append(row("sign", sid, g["name"], 0))
    for r in rows:
        r["role"] = (baselines.ROLE.get(r["id"], "other") if r["kind"] == "baseline" else
                     "context" if r["id"] == "alert-coord2" or (r["kind"] == "sign" and baselines.is_context(meta.get(r["id"], {}))) else "other")
    # the main alarms first, then their variants, then the rules, then everything else
    rank = {"main": 0, "variant": 1}
    rows.sort(key=lambda r: (rank.get(r["role"], 2 if r["kind"] == "rule" else 3),
                             baselines.MAIN_IDS.index(r["id"]) if r["id"] in baselines.MAIN_IDS else 0, -r["alarms"], r["id"]))
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
        "note": ("Rewritten on 2026-11-16 (v2.2.0; the 2026-11-13 version was committed and then rewritten, and its forward results were never committed). "
                 "Written by the people who built the tool, who by then knew how the Swarm Traces incident unfolded: "
                 "which actions were harmful, in what order, and when. On that incident (and on the wiki swarm, whose pack was written on it) "
                 "the timing of these signs is hindsight, not a test. The forward test uses data they were not written on."),
        "code": {"git_head": head, "uncommitted_code_files_at_freeze": dirty, "sha256": code_hashes(),
                 "how_to_check": "python3 -m agenttrace.earlywarn freeze --check"},
        "signs": signs, "rules": rules,
        "volume_baseline": {"k_sigma": 3.0, "min_history_hours": 12, "min_sd": 1.0},
        "baselines": [{"id": k, "name": n} for k, n in baselines.BASELINES],
        "forward_test": {
            "seeds": list(FORWARD_SEEDS), "settings": [n for n, _, _ in validation.SETTINGS],
            "independent_generator": {"module": "agenttrace/indepgen.py", "seeds": list(INDEP_SEEDS), "cell": INDEP_CELL,
                                      "scenarios": list(indepgen.SCENARIOS), "agents": 30, "hours": 48},
            "grading": "a sign's lead is the hours between the sign and the first true harm (or first true message) in the generator's truth file",
            "rule": ("v2.2.0 freeze. This file and reports/earlywarn/prereg.json (sha256 of this file, of every code file and of both "
                     "generators, written by `earlywarn prereg` before any forward swarm is generated) are written first; the "
                     "forward run then records the hashes it ran with and says whether they differ. Nothing is committed by the tool: "
                     "tag or commit both files before the run to make the order verifiable from history."),
            "seeds_not_run_before_freeze": "old generator 31-40 and independent generator 501-510; 21-30 were the v2.1.0 forward run"},
        "changes_since_v2_1_0": ["the shared-place sign ignores a place named only inside a code comment (reconstruct.places_of)",
                                 "the signs are scored beside simple baselines (agenttrace/baselines.py)",
                                 "an independent generator (agenttrace/indepgen.py) is run beside the old one"],
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
    summary.update(_provenance_block())
    summary.update({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seeds": list(seeds),
                    "generator": "agenttrace.groundtruth (the original simulator)",
                    "seconds": round(time.time() - started, 1),
                    "command": "python3 -m agenttrace.earlywarn forward --out " + out + " --seeds " + " ".join(map(str, seeds))})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
        json.dump({**summary, "runs": runs}, f, indent=1)
    return summary


def _provenance_block():
    """What the run was made with, and whether it differs from the frozen file and the pre-registration."""
    out = {"code_at_run": code_hashes(), "git_head_at_run": _git("rev-parse", "HEAD")}
    try:
        st = frozen_status()
        out["code_changed_since_freeze"] = st["drift"]
        out["frozen_on"] = st["frozen"].get("frozen_on")
    except (OSError, ValueError):
        out["code_changed_since_freeze"] = None
    try:
        with open(os.path.join(default_out(), "prereg.json"), encoding="utf-8") as f:
            pr = json.load(f)
        with open(FROZEN, "rb") as f:
            out["frozen_file_matches_prereg"] = hashlib.sha256(f.read()).hexdigest() == pr.get("frozen_signs_sha256")
        out["prereg_written"] = pr.get("written_utc")
    except (OSError, ValueError):
        out["frozen_file_matches_prereg"] = None
    return out


def prereg(out=None):
    """Write <out>/prereg.json: sha256 of the frozen file, of every code file and of both generators, the seeds, and the
    time, BEFORE any forward swarm is generated. The tool cannot commit for you; commit this file and the frozen file
    first, then run `forward` and `independent`, and the order is on the record."""
    out = out or default_out()
    os.makedirs(out, exist_ok=True)
    with open(FROZEN, "rb") as f:
        fz = hashlib.sha256(f.read()).hexdigest()
    rec = {"written_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "frozen_signs_sha256": fz, "git_head": _git("rev-parse", "HEAD"), "code_sha256": code_hashes(),
           "forward_seeds_original_generator": list(FORWARD_SEEDS), "forward_seeds_independent_generator": list(INDEP_SEEDS),
           "independent_cell": INDEP_CELL, "scenarios": list(indepgen.SCENARIOS),
           "rule": "no forward swarm exists when this file is written; run `forward` and `independent` afterwards"}
    with open(os.path.join(out, "prereg.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    return rec


def run_independent(out=None, seeds=INDEP_SEEDS, scenarios=None, log=print, fname="forward_independent.json"):
    """The forward test again on swarms from agenttrace.indepgen (different naming, code styles, clocks, notes, and
    benign look-alike classes). Same signs, same rules, same baselines; nothing tuned on them."""
    out = out or default_out()
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    from . import identity as idm
    save_dec = idm.SAVE_DECISIONS
    idm.SAVE_DECISIONS = False
    started = time.time()
    tmp = tempfile.mkdtemp(prefix="st_indep_")
    runs = []
    try:
        for sc, (mode, label) in indepgen.SCENARIOS.items():
            if scenarios and sc not in scenarios:
                continue
            for seed in seeds:
                folder = os.path.join(tmp, f"{sc}-s{seed}")
                truth = indepgen.make(folder, sc, seed, agents=30, hours=48, **indepgen.CELLS[INDEP_CELL][1])
                s = validation._load(folder, truth)
                runs.append(extract(s, truth, {"setting": sc, "label": label, "seed": seed, "mode": mode,
                                               "agents": truth["params"]["agents"]}))
                shutil.rmtree(folder, ignore_errors=True)
            log(f"  {sc}: {len(seeds)} swarms")
    finally:
        idm.SAVE_DECISIONS = save_dec
        shutil.rmtree(tmp, ignore_errors=True)
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    summary = summarize(runs, [], {"available": False, "note": "not run"})
    coord = [r for r in runs if r["mode"] != "benign" and r["dated"]]
    summary["by_scenario"] = {}
    for sc, (mode, label) in indepgen.SCENARIOS.items():
        rs = [r for r in runs if r.get("setting") == sc]
        if rs:
            summary["by_scenario"][sc] = {
                "label": label, "mode": mode, "swarms": len(rs), "dated": sum(1 for r in rs if r["dated"]),
                "fired": {rid: sum(1 for r in rs if r["rules"].get(rid) is not None) for rid in DEFAULT_RULE_IDS},
                "signs_fired": {k: sum(1 for r in rs if any(g["id"] == k for g in r["signs"]))
                                for k in sorted({g["id"] for r in rs for g in r["signs"]})},
                "baselines_fired": {k: sum(1 for r in rs if (r["alarms"].get("baseline") or {}).get(k) is not None)
                                    for k, _ in baselines.BASELINES}}
    summary.update(_provenance_block())
    summary.update({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seeds": list(seeds),
                    "generator": "agenttrace.indepgen", "cell": INDEP_CELL, "coordinated_runs": len(coord),
                    "seconds": round(time.time() - started, 1),
                    "command": "python3 -m agenttrace.earlywarn independent --out " + out})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
        json.dump({**summary, "runs": runs}, f, indent=1)
    return summary


# ------------------------------------------------------------------ v2.3.0: pre-registration, forward test, benign sets

def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def v23_code_hashes():
    return {f: _sha_file(os.path.join(REPO, f)) for f in V23_CODE_FILES if os.path.exists(os.path.join(REPO, f))}


def prereg_v23(out=None, force=False):
    """Write <out>/prereg_v23.json BEFORE any swarm with the v2.3.0 seeds exists: the main alarms with every parameter
    and the SHA-256 of that block, the hypotheses and how each is decided, the seeds and generator settings, and the
    SHA-256 of every code file. It refuses to run when the file or any forward result is already there (force
    rewrites and records that it did). The tool cannot commit for you: commit this file before `forward23`."""
    out = out or default_out()
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, V23_PREREG)
    existing = [f for f in [V23_PREREG, V23_FILES["forward"], V23_FILES["independent"], V23_FILES["summary"]]
                if os.path.exists(os.path.join(out, f))]
    if existing and not force:
        raise FileExistsError("already there: " + ", ".join(existing) + ". The pre-registration is written once, before the forward "
                              "swarms; --force rewrites it and records that results existed.")
    rec = {
        "version": "2.3.0", "written_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": "Pre-registration of the forward test of the simple alarms as the main early-warning feature.",
        "post_hoc": baselines.POST_HOC,
        "alarms": baselines.frozen_params(), "alarms_sha256": baselines.params_sha256(),
        "alarms_sha256_how": "sha256 of json.dumps(alarms, sort_keys=True, ensure_ascii=True) as UTF-8",
        "context_signs": {"shared_place": PLACE_SIGN, "carried_token": CARRIED_SIGN,
                          "note": "scored by the same measures, as context; not candidates for the main alarm"},
        "measures": {
            "fired": "the alarm fires at least once in the swarm",
            "before_harm": "the alarm fires strictly before the first true harmful record in the generator's truth file",
            "lead_h": "hours from the alarm to the first true harm (minus = after); median over swarms where it fired",
            "harm_share": "share of the true harmful records later than the alarm; 0 when the alarm never fires",
            "beats_place": "harm_share of the alarm strictly greater than harm_share of the shared-place sign",
            "benign_fired": "the alarm fires at least once in a benign swarm (a false alarm)"},
        "intervals": {"per_swarm": "Wilson 95% binomial interval on k of n swarms",
                      "settings": "95% percentile interval over 1000 resamples of whole settings (scenario classes for the independent generator)",
                      "per_24h": "exact (Garwood) Poisson 95% interval on alarms per 24 h of benign trace, each alarm counted once per swarm"},
        "hypotheses": HYPOTHESES,
        "decision": "Each hypothesis is decided separately for each of the four alarms and for 'any of the four', on each "
                    "generator, by the per-swarm interval. No alarm, parameter or threshold is changed after the run; a "
                    "failed hypothesis is reported as failed.",
        "original_generator": {"module": "agenttrace/groundtruth.py", "seeds": list(V23_SEEDS),
                               "settings": [{"name": n, "label": l, "params": prm} for n, l, prm in validation.SETTINGS]},
        "independent_generator": {"module": "agenttrace/indepgen.py", "seeds": list(V23_INDEP_SEEDS), "cell": INDEP_CELL,
                                  "cell_options": indepgen.CELLS[INDEP_CELL][1], "agents": 30, "hours": 48,
                                  "scenarios": {k: v[0] for k, v in indepgen.SCENARIOS.items()}},
        "seeds_never_run": "original generator: 21-30 (v2.1.0) and 31-40 (v2.2.0) have been run; 41-50 have not. "
                           "Independent generator: 501-510 have been run; 511-520 have not.",
        "code_sha256": v23_code_hashes(), "git_head": _git("rev-parse", "HEAD"),
        "uncommitted_code_files": [l[3:] for l in _git("status", "--porcelain", "--", "agenttrace").splitlines()
                                   if l[3:].endswith((".py", ".json"))],
        "limits": ["Written by the same people who chose the alarms, minutes before the run, in an uncommitted working tree: "
                   "the order rests on this file's own time stamp and hashes unless it is committed before the results.",
                   "Both generators are ours. The simulators never write a search_for_secrets action, so that alarm cannot "
                   "fire on them: its rows are not evidence of anything.",
                   "Lead before the first true harm and share of harm still to come are different measures; the real "
                   "release has only the second."],
        "rule": "no swarm with these seeds exists when this file is written; run `python3 -m agenttrace.earlywarn forward23` afterwards",
    }
    if existing:
        rec["rewritten_with_results_present"] = existing
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    return rec


def load_prereg_v23(out=None):
    path = os.path.join(out or default_out(), V23_PREREG)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    rec["file_sha256"] = _sha_file(path)
    return rec


def prereg_status(out=None):
    """The pre-registration, whether the alarm parameters still hash to what it froze, and which code files changed."""
    pr = load_prereg_v23(out)
    if pr is None:
        return {"written": False, "command": "python3 -m agenttrace.earlywarn prereg23"}
    now = v23_code_hashes()
    return {"written": True, "written_utc": pr["written_utc"], "file_sha256": pr["file_sha256"],
            "alarms_sha256": pr["alarms_sha256"], "alarms_match": pr["alarms_sha256"] == baselines.params_sha256(),
            "code_changed": sorted(f for f, h in pr["code_sha256"].items() if now.get(f) != h),
            "seeds": {"original": pr["original_generator"]["seeds"], "independent": pr["independent_generator"]["seeds"]},
            "git_head": pr.get("git_head"), "rewritten_with_results_present": pr.get("rewritten_with_results_present")}


def _generate(kind, seeds, log, only=None):
    """Runs (the shape extract returns) for one generator and a tuple of seeds, in a temporary folder.
    only: setting or scenario names to keep (tests use it; the pre-registered run keeps all)."""
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    from . import identity as idm
    save_dec = idm.SAVE_DECISIONS
    idm.SAVE_DECISIONS = False
    tmp = tempfile.mkdtemp(prefix="st_v23_")
    runs = []
    try:
        if kind == "original":
            for name, label, params in validation.SETTINGS:
                if only and name not in only:
                    continue
                for seed in seeds:
                    folder = os.path.join(tmp, f"{name}-s{seed}")
                    runs.append(_swarm_run(folder, dict(params), name, label, seed))
                    shutil.rmtree(folder, ignore_errors=True)
                log(f"  {name}: {len(seeds)} swarms")
        else:
            for sc, (mode, label) in indepgen.SCENARIOS.items():
                if only and sc not in only:
                    continue
                for seed in seeds:
                    folder = os.path.join(tmp, f"{sc}-s{seed}")
                    truth = indepgen.make(folder, sc, seed, agents=30, hours=48, **indepgen.CELLS[INDEP_CELL][1])
                    sess = validation._load(folder, truth)
                    runs.append(extract(sess, truth, {"setting": sc, "label": label, "seed": seed, "mode": mode,
                                                      "agents": truth["params"]["agents"]}))
                    shutil.rmtree(folder, ignore_errors=True)
                log(f"  {sc}: {len(seeds)} swarms")
    finally:
        idm.SAVE_DECISIONS = save_dec
        shutil.rmtree(tmp, ignore_errors=True)
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    return runs


def benign_set(label, kind, runs, note=None):
    """One benign set: for each main alarm, 'any of the four' and each variant, fired k of n with both intervals and
    alarms per 24 h; by class (setting) as well. Also the old Alert rule and the shared-place sign, for comparison."""
    benign = [r for r in runs if r["mode"] == "benign" and r["dated"]]
    undated = sum(1 for r in runs if r["mode"] == "benign" and not r["dated"])
    rows = []
    spec = [(a["id"], a["short"], "main") for a in baselines.MAIN_ALARMS] + [(ANY_MAIN, "Any of the four", "any")]
    spec += [(a["id"], a["short"], "variant") for a in baselines.VARIANTS]
    for aid, short, role in spec:
        b = alarm_stats(benign, _main_getter(aid))["benign"]
        rows.append({"id": aid, "short": short, "role": role, **b})
    ctx = [("alert-coord2", "Alert rule (2 kinds of coordination)", lambda r: r["rules"].get("alert-coord2")),
           (PLACE_SIGN, "Shared-place sign", lambda r: next((x["h"] for x in r["signs"] if x["id"] == PLACE_SIGN), None))]
    for cid, short, get in ctx:
        rows.append({"id": cid, "short": short, "role": "context", **alarm_stats(benign, get)["benign"]})
    return {"set": label, "kind": kind, "swarms": len(benign), "undated": undated,
            "trace_hours": round(sum(r["hours"] for r in benign), 1),
            "classes": sorted({str(r.get("setting")) for r in benign}), "rows": rows, "note": note}


def _saved_runs(out, fname):
    path = os.path.join(out, fname)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("runs")


def run_bundled_benign():
    """The bundled benign sample (agenttrace/samples/benign_swarm): one hand-checked simulated trace."""
    from .session import Session
    path = os.path.join(HERE, "samples", "benign_swarm", "benign_swarm.jsonl")
    if not os.path.exists(path):
        return []
    sess = Session()
    sess.load(path, "code_traces.json", {}, "benign_swarm")
    r = extract(sess, None, {"setting": "bundled_sample", "label": "bundled benign sample", "mode": "benign"})
    r["agents"] = len({a for a, k in sess.actor.values() if k != "run"})
    return [r]


def _external_files(root):
    """Data files under root, one level of dataset folders: (dataset, relative path, size). Read-only."""
    out = []
    if not os.path.isdir(root):
        return out
    skip = ("readme", "license", "schema", "manifest", "experiments", "source_", "counts", "communities.json")   # not traces
    for ds in sorted(os.listdir(root)):
        base = os.path.join(root, ds)
        if not os.path.isdir(base) or EXTERNAL_SETS.get(ds, {}).get("benign") is False:
            continue
        for dirpath, dirnames, files in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d != "tables")       # index tables, not traces
            for f in sorted(files):
                if f.lower().startswith(skip) or f.startswith("."):
                    continue
                full = os.path.join(dirpath, f)
                out.append((ds, os.path.relpath(full, base), os.path.getsize(full)))
    return out


def external_benign(root=None, out=None, log=print, limit=None):
    """Benign false alarms on real traces under datasets-ext/ (read-only; nothing there is written or changed).
    Each loadable file is one trace, loaded as the app loads it (pack chosen automatically). A time-based alarm can
    be scored only on a trace with times; an undated trace is counted as not measurable, never as 'no alarm'. The
    secrets-search alarm is also checked without times: does any record match the pattern behind the pack's
    search_for_secrets intent."""
    root = root or EXTERNAL_ROOT
    from . import packs
    from .session import Session
    rx = dict(packs.load_pack(os.path.join(HERE, "packs", "code_traces.json")).intents).get(baselines.INTENT)
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    sets = {}
    started = time.time()
    try:
        for ds, rel, size in _external_files(root):
            d = sets.setdefault(ds, {"dataset": ds, "files": 0, "loaded": 0, "dated": 0, "records": 0, "failed": 0, "unreadable_format": 0,
                                     "too_large": 0, "runs": [], "pattern_traces": 0, "pattern_records": 0, "formats": {}, "packs": {}})
            d["files"] += 1
            ext = os.path.splitext(rel)[1].lower()
            if ext not in (".json", ".jsonl", ".csv", ".tsv"):
                d["unreadable_format"] += 1          # parquet and the like: no standard-library reader
                continue
            if size > EXTERNAL_MAX_BYTES:
                d["too_large"] += 1
                continue
            if limit and d["loaded"] + d["failed"] >= limit:
                continue
            sess = Session()
            try:
                sess.load(os.path.join(root, ds, rel), "auto", {}, f"{ds}/{rel}")
                r = extract(sess, None, {"setting": ds, "label": rel, "mode": "benign"})
            except Exception as e:      # a file that does not load is counted, not hidden
                d["failed"] += 1
                d.setdefault("errors", []).append(f"{rel}: {type(e).__name__}"[:120])
                continue
            r["agents"] = len({a for a, k in sess.actor.values() if k != "run"})
            d["loaded"] += 1
            d["dated"] += bool(r["dated"])
            d["records"] += len(sess.events)
            fmt = (sess.read_report or {}).get("format") or "?"
            d["formats"][fmt] = d["formats"].get(fmt, 0) + 1
            d["packs"][sess.pack.name] = d["packs"].get(sess.pack.name, 0) + 1
            hits = sum(1 for e in sess.events if rx is not None and rx.search(e.text))
            d["pattern_records"] += hits
            d["pattern_traces"] += bool(hits)
            d["runs"].append({k: r[k] for k in ("setting", "label", "mode", "dated", "hours", "agents", "alarms", "rules", "signs", "records")})
    finally:
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    rows = []
    for ds, d in sets.items():
        runs = d.pop("runs")
        errors = d.pop("errors", [])
        label = EXTERNAL_SETS.get(ds, {"benign": None, "what": "not described here; labelled by nobody"})
        bs = benign_set(ds, "real traces: " + label["what"], runs)
        d.update({"what": label["what"], "benign_as_published": label["benign"], "errors": errors[:5], "timed_alarms_measurable": d["dated"],
                  "pattern_check": {"what": "traces with at least one record matching the pattern behind search_for_secrets, "
                                            "with or without times", **_share_block([{"setting": ds, "hit": i < d["pattern_traces"]} for i in range(d["loaded"])],
                                                                                      lambda r: r["hit"])},
                  "benign_set": bs})
        log(f"  {ds}: {d['loaded']} of {d['files']} files loaded, {d['dated']} with times, "
            f"search pattern in {d['pattern_traces']} traces")
        rows.append(d)
    res = {"root": os.path.relpath(root, REPO) if root.startswith(REPO) else root, "present": os.path.isdir(root),
           "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - started, 1),
           "max_file_bytes": EXTERNAL_MAX_BYTES, "datasets": rows,
           "excluded": [{"dataset": ds, "why": v["what"]} for ds, v in sorted(EXTERNAL_SETS.items())
                        if v["benign"] is False and os.path.isdir(os.path.join(root, ds))],
           "pattern": rx.pattern if rx is not None else None,
           "note": "Real multi-agent traces that happen to be on this machine, read and never changed. They are benign only in the "
                   "sense their publishers give (no attack); nobody here labelled them. Undated traces cannot fire a time-based "
                   "alarm, so they say nothing about its false-alarm rate. Each was loaded with the pack the app picks for it, "
                   "which has no search_for_secrets intent, so that alarm is checked by its pattern instead."}
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, V23_FILES["external"]), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return res


def release_v23(trace="redacted_columns.csv", pack="code_traces.json", out=None):
    """The real release: the main alarms and the context by share of timed harm still to come. Post-hoc: this is the
    incident the alarms were chosen on."""
    from .session import Session
    sess = Session()
    sess.load(trace, pack, {}, os.path.basename(trace))
    ew = baselines.early_warning(sess)
    strip = lambda r: {k: v for k, v in r.items() if k not in ("why", "record", "t")}     # no record text or ids in a published file
    res = {"trace": os.path.basename(trace), "pack": pack, "records": len(sess.events), "harm_records": ew["harm_records"],
           "hours": ew["hours"], "alarms": [strip(r) for r in ew["alarms"]], "variants": [strip(r) for r in ew["variants"]],
           "context": [strip(r) for r in ew["context"]], "post_hoc": baselines.POST_HOC,
           "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "note": "Share of harm still to come = share of the timed harmful records after the alarm. One incident, the one the "
                   "alarms were picked on. The harm list is the pack's (64% of it dataset commits); see docs/audit-v2.1.md 1.5."}
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, V23_FILES["release"]), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return res


def run_v23(out=None, log=print, seeds=None, indep_seeds=None, only=None):
    """The pre-registered forward test: both generators with the pre-registered seeds, scored for the main alarms and
    the context, each hypothesis decided, and the benign false-alarm table over every benign set available. Refuses to
    run without the pre-registration; records whether the alarms or the code changed since it was written."""
    out = out or default_out()
    pr = load_prereg_v23(out)
    if pr is None:
        raise FileNotFoundError("no " + V23_PREREG + " in " + out + ": write it first with `python3 -m agenttrace.earlywarn prereg23`")
    status = prereg_status(out)
    seeds = tuple(seeds or pr["original_generator"]["seeds"])
    indep_seeds = tuple(indep_seeds or pr["independent_generator"]["seeds"])
    started = time.time()
    stamp = lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gens = {}
    for kind, sd, fname, gen in (("original", seeds, V23_FILES["forward"], "agenttrace.groundtruth (the original simulator)"),
                                 ("independent", indep_seeds, V23_FILES["independent"], "agenttrace.indepgen (written independently)")):
        log(f"{kind} generator, seeds {sd[0]} to {sd[-1]}")
        t_gen = stamp()
        runs = _generate(kind, sd, log, only)
        main_rows = main_table(runs)
        block = {"generator": gen, "seeds": list(sd), "swarms_generated_from_utc": t_gen, "generated": stamp(),
                 "coordinated_runs": sum(1 for r in runs if r["mode"] != "benign" and r["dated"]),
                 "benign_runs": sum(1 for r in runs if r["mode"] == "benign" and r["dated"]),
                 "undated_runs": sum(1 for r in runs if not r["dated"]),
                 "main": main_rows, "context": context_table(runs), "hypotheses": hypotheses(main_rows)}
        with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
            json.dump({**block, "prereg": status, "runs": runs}, f, indent=1)
        gens[kind] = {**block, "_runs": runs}
    sets = [benign_set("Original simulator, seeds %d to %d (pre-registered)" % (seeds[0], seeds[-1]), "simulated", gens["original"]["_runs"]),
            benign_set("Independent generator look-alike classes, seeds %d to %d (pre-registered)" % (indep_seeds[0], indep_seeds[-1]),
                       "simulated", gens["independent"]["_runs"])]
    for sc in indepgen.BENIGN:
        rs = [r for r in gens["independent"]["_runs"] if r.get("setting") == sc]
        if rs:
            sets.append(benign_set("  class: " + indepgen.SCENARIOS[sc][1], "simulated, one look-alike class", rs))
    for fname, label in (("forward.json", "Original simulator, seeds 31 to 40 (the v2.2.0 run)"),
                         ("forward_independent.json", "Independent generator look-alike classes, seeds 501 to 510 (the v2.2.0 run)")):
        old = _saved_runs(out, fname)
        if old:
            sets.append(benign_set(label, "simulated, run before the alarms were made the main feature", old))
    sets.append(benign_set("Bundled benign sample (agenttrace/samples/benign_swarm)", "simulated, one trace", run_bundled_benign()))
    ext_path = os.path.join(out, V23_FILES["external"])
    external = None
    if os.path.exists(ext_path):
        with open(ext_path, encoding="utf-8") as f:
            external = json.load(f)
    rel_path = os.path.join(out, V23_FILES["release"])
    release = None
    if os.path.exists(rel_path):
        with open(rel_path, encoding="utf-8") as f:
            release = json.load(f)
    for g in gens.values():
        g.pop("_runs")
    summary = {"version": "2.3.0", "generated": stamp(), "seconds": round(time.time() - started, 1),
               "as_preregistered": (list(seeds) == pr["original_generator"]["seeds"] and list(indep_seeds) == pr["independent_generator"]["seeds"]
                                    and not only and status["alarms_match"] and not status["code_changed"]),
               "prereg": status, "prereg_written_utc": pr["written_utc"], "prereg_file_sha256": pr["file_sha256"],
               "alarms_sha256_at_run": baselines.params_sha256(), "code_at_run": v23_code_hashes(),
               "git_head_at_run": _git("rev-parse", "HEAD"),
               "post_hoc": baselines.POST_HOC, "context_note": baselines.CONTEXT_NOTE, "hypothesis_text": HYPOTHESES,
               "generators": gens, "benign_sets": sets, "external": external, "release": release,
               "command": "python3 -m agenttrace.earlywarn forward23",
               "caveats": ["Both generators are this project's own; real swarms differ.",
                           "The simulators never write a search_for_secrets action, so that alarm cannot fire on them.",
                           "The four alarms were chosen on one real incident; this forward test is on simulated swarms only."]}
    with open(os.path.join(out, V23_FILES["summary"]), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary


def evidence(out=None):
    """What has been measured about the main alarms, from the saved v2.3.0 files: the summary if the forward test was
    run, else the pre-registration status alone."""
    out = out or default_out()
    path = os.path.join(out, V23_FILES["summary"])
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["ran"] = True
        d["prereg_now"] = prereg_status(out)
        for key in ("external", "release"):       # written by their own commands, possibly after the forward test
            fp = os.path.join(out, V23_FILES[key])
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as f:
                    d[key] = json.load(f)
        d.pop("code_at_run", None)
        return d
    return {"ran": False, "prereg_now": prereg_status(out), "command": "python3 -m agenttrace.earlywarn prereg23 && python3 -m agenttrace.earlywarn forward23"}


def summarize(runs, sample_runs=None, wiki_run=None):
    fz = None
    try:
        fz = frozen_status()
    except (OSError, ValueError):
        pass
    main_rows = main_table(runs)
    return {"main": main_rows, "context": context_table(runs), "hypotheses": hypotheses(main_rows),
            "post_hoc": baselines.POST_HOC, "context_note": baselines.CONTEXT_NOTE,
            "forward": forward_table(runs), "false_alarms": false_alarms(runs), "cost": cost_curve(runs),
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
    res = {"main": baselines.early_warning(s), "run": r, "rules_fired": {k: v for k, v in r["rules"].items()},
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


def _main_get(state, q):
    """The main early-warning answer: the four simple alarms on the loaded dataset (when one is loaded), the signs of
    shared control as context, and the saved evidence (pre-registration, forward test, benign false alarms)."""
    s = state.get("session")
    loaded = None
    if s is not None and getattr(s, "loaded", False):
        key = (s.name, len(s.events))
        cached = getattr(s, "_earlywarn_main", None)
        if cached is None or cached[0] != key:
            cached = (key, baselines.early_warning(s))
            s._earlywarn_main = cached
        loaded = cached[1]
    return {"loaded": loaded, "alarms": baselines.frozen_params(), "alarms_sha256": baselines.params_sha256(),
            "main_ids": list(baselines.MAIN_IDS), "post_hoc": baselines.POST_HOC,
            "context_label": baselines.CONTEXT_LABEL, "context_note": baselines.CONTEXT_NOTE, "evidence": evidence()}


GET = {"earlywarn_main": _main_get, "earlywarn_summary": _summary, "earlywarn_frozen": _frozen, "earlywarn_release": _release}
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
    sub.add_parser("prereg", help="write reports/earlywarn/prereg.json (hashes and seeds) before any forward swarm exists").add_argument("--out", default=None)
    iv = sub.add_parser("independent", help="forward test on the independent generator's swarms")
    iv.add_argument("--out", default=None)
    iv.add_argument("--seeds", type=int, nargs="*", default=list(INDEP_SEEDS))
    r = sub.add_parser("run", help="the same tables for your own trace")
    r.add_argument("trace")
    r.add_argument("--pack", default="auto")
    r.add_argument("--out", default=None)
    al = sub.add_parser("alarms", help="the main alarms (new host, secrets search, distinct actors, volume) for a trace, then the context")
    al.add_argument("trace")
    al.add_argument("--pack", default="auto")
    al.add_argument("--json", default=None, help="also write the result to this file")
    p23 = sub.add_parser("prereg23", help="write reports/earlywarn/prereg_v23.json before any v2.3.0 forward swarm exists")
    p23.add_argument("--out", default=None)
    p23.add_argument("--force", action="store_true", help="rewrite it even though it or the results exist (recorded in the file)")
    sub.add_parser("forward23", help="the pre-registered forward test of the main alarms, both generators").add_argument("--out", default=None)
    ex = sub.add_parser("external", help="benign false alarms on real traces under datasets-ext/ (read-only)")
    ex.add_argument("--root", default=None)
    ex.add_argument("--out", default=None)
    rl = sub.add_parser("release", help="the real release: main alarms and context by share of harm still to come")
    rl.add_argument("--trace", default="redacted_columns.csv")
    rl.add_argument("--pack", default="code_traces.json")
    rl.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "alarms":
        from .session import Session
        sess = Session()
        sess.load(a.trace, a.pack, {}, os.path.basename(a.trace))
        ew = baselines.early_warning(sess)
        print_alarms(ew)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump(ew, f, indent=1)
        return 0
    if a.cmd == "prereg23":
        try:
            rec = prereg_v23(a.out, a.force)
        except FileExistsError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"wrote {V23_PREREG} at {rec['written_utc']}: alarms {rec['alarms_sha256'][:12]}, git {rec['git_head'][:10]}; "
              f"seeds {rec['original_generator']['seeds'][0]}-{rec['original_generator']['seeds'][-1]} and "
              f"{rec['independent_generator']['seeds'][0]}-{rec['independent_generator']['seeds'][-1]}")
        return 0
    if a.cmd == "forward23":
        try:
            print_v23(run_v23(a.out))
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0
    if a.cmd == "external":
        res = external_benign(a.root, a.out or default_out())
        if not res["present"]:
            print("no datasets-ext/ folder here: nothing to measure")
        return 0
    if a.cmd == "release":
        res = release_v23(a.trace, a.pack, a.out or default_out())
        for x in res["alarms"] + res["variants"] + res["context"]:
            sh = x["harm_share_after"]
            print(f"  {x['role']:<8} {x['name'][:52]:<52} {'-' if x['h'] is None else x['h']:>7} h  {'-' if sh is None else f'{100 * sh:.1f}%':>6}")
        print("\n" + res["post_hoc"])
        return 0
    if a.cmd == "freeze":
        if a.check:
            st = frozen_status()
            print("code unchanged since the freeze" if not st["drift"] else "changed since the freeze: " + ", ".join(st["drift"]))
            return 0
        d = freeze()
        print(f"wrote {FROZEN}: {len(d['signs'])} signs, {len(d['rules'])} rules, git {d['code']['git_head'][:10]}")
    elif a.cmd == "prereg":
        rec = prereg(a.out)
        print(f"wrote prereg.json at {rec['written_utc']}: frozen file {rec['frozen_signs_sha256'][:12]}, git {rec['git_head'][:10]}")
    elif a.cmd == "independent":
        summarize_and_print(run_independent(a.out, tuple(a.seeds)))
    elif a.cmd == "forward":
        sm = summarize_and_print(run_forward(a.out, tuple(a.seeds), wiki=not a.no_wiki))
    elif a.cmd == "run":
        res = run_trace(a.trace, a.pack, a.out)
        print_alarms(res["main"])
        print()
        print(json.dumps({"rules_fired": res["rules_fired"], "agent_hours": res["agent_hours"],
                          "signs": [(g["id"], g["h"]) for g in res["run"]["signs"]]}, indent=1))
        fa = res["if_benign"]
        print(f"\nIf this trace is benign: {fa['trace_hours']} trace hours, {fa['agent_hours']} agent-hours observed")
        for x in fa["rows"]:
            print(f"  {x['kind']:<5} {x['name'][:52]:<52} alarms {x['alarms']}  per 24 h {x['per_24h']}  95% {x['ci_low']}..{x['ci_high']}")
        print("\n" + res["note"])
    return 0


def _ci(ci):
    return "-" if not ci else f"{100 * ci[0]:.0f}-{100 * ci[1]:.0f}%"


def print_alarms(ew):
    """The main alarms for one trace, then the context, as plain lines."""
    print(f"{ew['dataset']}: main early-warning alarms" + ("" if ew["dated"] else " (no record has a time, so no alarm can fire)"))
    for x in ew["alarms"] + ew["variants"]:
        sh = x["harm_share_after"]
        when = "did not fire" if not x["fired"] else f"{x['time']} UTC, hour {x['h']}"
        print(f"  {'MAIN' if x['role'] == 'main' else 'variant':<8} {x['name'][:44]:<44} {when:<36}"
              + ("" if sh is None else f" {100 * sh:.1f}% of timed harm still to come"))
    if not ew["has_intent"]:
        print("  (this pack has no search_for_secrets intent, so that alarm cannot fire here)")
    print(f"{ew['context_label']} (not an early warning)")
    for x in ew["context"]:
        sh = x["harm_share_after"]
        print(f"  context  {x['name'][:44]:<44} {x['time'] + ' UTC, hour ' + str(x['h']):<36}" + ("" if sh is None else f" {100 * sh:.1f}%"))
    if not ew["context"]:
        print("  none fired")
    print(ew["post_hoc"])


def print_v23(sm):
    for kind, g in sm["generators"].items():
        print(f"\n{kind} generator ({g['generator']}), seeds {g['seeds'][0]} to {g['seeds'][-1]}: "
              f"{g['coordinated_runs']} coordinated, {g['benign_runs']} benign swarms")
        print(f"  {'alarm':<44} {'fired':>8} {'before harm':>12} {'95%':>9} {'lead h':>7} {'harm left':>9} {'beats place':>12} {'benign':>8} {'95%':>8}")
        for x in g["main"] + [r for r in g["context"] if r["id"] in (PLACE_SIGN, CARRIED_SIGN, "alert-coord2")]:
            c, b = x["coordinated"], x["benign"]
            bt = c.get("beats")
            print(f"  {x['name'][:44]:<44} {c['fired']['k']:>4}/{c['fired']['n']:<3} {c['before_harm']['k']:>8}/{c['before_harm']['n']:<3} "
                  f"{_ci(c['before_harm']['ci']):>9} {'-' if c['median_lead_h'] is None else c['median_lead_h']:>7} "
                  f"{'-' if c['harm_share_median'] is None else round(100 * c['harm_share_median'], 1):>9} "
                  f"{'-' if not bt else str(bt['k']) + '/' + str(bt['n']):>12} {b['fired']['k']:>4}/{b['fired']['n']:<3} {_ci(b['fired']['ci']):>8}")
        for h in g["hypotheses"]:
            print(f"  {h['hypothesis']} {h['alarm']:<16} {h['k']}/{h['n']} {_ci(h['ci'])}: {'HOLDS' if h['holds'] else 'fails' if h['holds'] is not None else 'not measurable'}")
    st = sm["prereg"]
    print(f"\npre-registration written {st['written_utc']}; alarms unchanged: {st['alarms_match']}; code changed since: {st['code_changed'] or 'none'}")
    return sm


def summarize_and_print(sm):
    fa = sm["false_alarms"]
    print(f"forward test: {sm['forward']['coordinated_runs']} coordinated, {sm['forward']['benign_runs']} benign swarms; "
          f"{fa['trace_hours']} benign trace hours, {fa['agent_hours']} agent-hours")
    print("  main alarms (simple; post-hoc on one incident):")
    for x in sm.get("main", []):
        c, b = x["coordinated"], x["benign"]
        print(f"    {x['name']}: coordinated {c['fired']['k']}/{c['fired']['n']}, before the first harm {c['before_harm']['k']}/{c['before_harm']['n']}, "
              f"median lead {c['median_lead_h']} h; benign {b['fired']['k']}/{b['fired']['n']}")
    print("  context rules and the 12 h volume baseline (not an early warning):")
    for x in sm["forward"]["rules"]:
        c = x["coordinated"]["harm"]
        print(f"  {x['name']}: coordinated {c['fired']}/{c['n']}, median lead {c['median_lead_h']} h; benign {x['benign']['fired']}/{x['benign']['n']}")
    return sm


if __name__ == "__main__":
    sys.exit(main())

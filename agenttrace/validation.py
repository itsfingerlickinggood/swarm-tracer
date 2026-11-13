"""How accurate is the tool? A suite of simulated swarms with known truth, scored as ranges.

    python3 -m agenttrace.validation run --out reports/validation [--seeds 1 2 3 4 5] [--quick]

Generates every SETTING below with each seed (agenttrace.groundtruth make), loads each swarm with
the tool exactly as the app does (Session.load with the code_traces pack), and scores:

- messages: precision/recall of the (write record, read record) links and of the agent pairs;
- early signs: how many of the true signs the tool finds, and its timing error in hours;
- dating: error of the estimated times and the share inside the tool's stated range (coverage);
- identity: precision of agenttrace.identity's merge proposals per confidence band (high, medium,
  low) and recall; plus a counterfactual "direct evidence" rule measured on the same proposals;
- benign swarms (no coordination at all): which warning signs fire, which default alert rules fire
  (agenttrace.live.evaluate_rules with the default rules), how many messages between different
  agents the tool reports, and the identity proposals there. Everything that fires there is a
  false positive.

Writes <out>/summary.json (every run and the ranges), <out>/summary.md (tables with min–median–max)
and the generated swarms under <out>/swarms/. GET /api/x/validation_summary serves the latest
summary.json; POST /api/x/validation_run runs a quick suite (one seed) from the app.

The simulations are ours: real swarms differ (see docs/validation.md for the limits).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict

from . import groundtruth

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# name, label, parameters for groundtruth.make (agents, two_token_share, hidden_share, mention_share, time_mode, mode)
SETTINGS = [
    ("base", "40 agents, defaults", {"agents": 40}),
    ("small", "20 agents", {"agents": 20}),
    ("large", "80 agents", {"agents": 80}),
    ("two_tokens", "40 agents, 35% hold two tokens", {"agents": 40, "two_token_share": 0.35}),
    ("hidden_reads", "40 agents, 25% of reads hidden", {"agents": 40, "hidden_share": 0.25}),
    ("naming_notes", "40 agents, many place-naming notes", {"agents": 40, "mention_share": 0.25}),
    ("quiet", "40 agents, no hidden reads, no notes", {"agents": 40, "hidden_share": 0.0, "mention_share": 0.0}),
    ("field_times", "40 agents, a time field on every record", {"agents": 40, "time_mode": "field"}),
    # the payload shapes found when the real release's links were audited (agenttrace.benchmark): read-then-exfiltrate,
    # LFS downloads, Python urlopen, URLs kept in variables, several places in a record, proxies, redacted paths
    ("realworld", "40 agents, real-world payload patterns", {"agents": 40, "realworld": 0.6}),
    ("benign", "benign: 40 agents, half save results", {"agents": 40, "mode": "benign"}),
    ("benign_readonly", "benign: 40 agents, read-only", {"agents": 40, "mode": "benign", "own_writes": 0.0}),
    ("benign_realworld", "benign: 40 agents, real-world payload patterns", {"agents": 40, "mode": "benign", "realworld": 0.6}),
]
REALWORLD = ("realworld", "benign_realworld")
QUICK_AGENTS = 20

# measures: key, label, unit ("share" 0..1 or "hours" or "count"), which way is better
MEASURES = [
    ("msg_precision", "Message links: precision", "share", "up"),
    ("msg_recall", "Message links: recall", "share", "up"),
    ("pair_precision", "Agent pairs: precision", "share", "up"),
    ("pair_recall", "Agent pairs: recall", "share", "up"),
    ("sign_recall", "Early signs found", "share", "up"),
    ("sign_on_time", "Signs within 1 h of the truth", "share", "up"),
    ("sign_error_h", "Sign timing error, median (h)", "hours", "down"),
    ("dating_error_h", "Dating error, median (h)", "hours", "down"),
    ("dating_p90_h", "Dating error, 90th percentile (h)", "hours", "down"),
    ("dating_coverage", "Estimated times inside the stated range", "share", "up"),
    ("id_high_precision", "Identity merges, high: precision", "share", "up"),
    ("id_medium_precision", "Identity merges, medium: precision", "share", "up"),
    ("id_low_precision", "Identity merges, low: precision", "share", "up"),
    ("id_high_proposed", "Identity merges proposed as high", "count", "none"),
    ("id_recall_high", "Identity: true pairs found at high", "share", "up"),
    ("id_recall_any", "Identity: true pairs found at any band", "share", "up"),
    ("id_direct_precision", "Identity, direct-evidence rule: precision", "share", "up"),
    ("id_direct_recall", "Identity, direct-evidence rule: recall", "share", "up"),
    ("agents_error", "Estimated agents minus true agents", "count", "none"),
    ("alert_after_first_message_h", "Alert (2 kinds of coordination): hours after the first true message", "hours", "none"),
    ("alert_lead_h", "Alert (2 kinds of coordination): hours before the first true harm", "hours", "none"),
    ("watch_lead_h", "Watch (first harmful sign): hours before the first true harm", "hours", "none"),
]
GROUPS = [
    ("Messages", ["msg_precision", "msg_recall", "pair_precision", "pair_recall"]),
    ("Timing and dating", ["sign_recall", "sign_on_time", "sign_error_h", "dating_error_h", "dating_p90_h", "dating_coverage"]),
    ("Identity merging", ["id_high_precision", "id_medium_precision", "id_low_precision", "id_high_proposed",
                          "id_recall_high", "id_recall_any", "id_direct_precision", "id_direct_recall", "agents_error"]),
    ("Default alert rules", ["alert_after_first_message_h", "alert_lead_h", "watch_lead_h"]),
]
MEASURE = {k: {"key": k, "label": l, "unit": u, "better": b} for k, l, u, b in MEASURES}
DIRECT = ("same_record", "same_thread", "carried")    # evidence that ties two tokens to one stream of work


def default_out():
    """reports/validation in a source checkout, else ~/.swarm-tracer/validation."""
    env = os.environ.get("SWARM_TRACER_VALIDATION_DIR")
    if env:
        return env
    if os.path.isdir(os.path.join(REPO, "reports")) or os.path.isdir(os.path.join(REPO, ".git")):
        return os.path.join(REPO, "reports", "validation")
    return os.path.join(os.path.expanduser("~"), ".swarm-tracer", "validation")


# ------------------------------------------------------------------ one swarm

def _load(folder, truth):
    from .session import Session
    s = Session()
    src = os.path.join(folder, truth.get("trace") or "trace.jsonl")
    s.load(src, truth.get("pack") or "code_traces.json", {}, os.path.basename(folder))
    return s


def _direct_rule(s, truth):
    """Counterfactual identity rule: propose only pairs with direct evidence (same record, small shared
    thread, carried token), whatever their score. Measured on the same proposals agenttrace.identity makes."""
    from . import identity as idm
    true_all = {tuple(sorted((a, b))) for ts in truth["agents"].values() for a in ts for b in ts if a < b}
    saved = getattr(s, "_id_decisions", None)
    s._id_decisions = {}
    try:
        props = idm.identity(s, limit=10 ** 6)["proposals"]
    finally:
        if saved is not None:
            s._id_decisions = saved
    pairs = {tuple(sorted((x["a"], x["b"]))) for x in props
             if x.get("confidence") and any(e["key"] in DIRECT for e in x["evidence"])}
    ok = len(pairs & true_all)
    return {"proposed": len(pairs), "correct": ok,
            "precision": round(ok / len(pairs), 4) if pairs else None,
            "recall": round(ok / len(true_all), 4) if true_all else None}


def _benign_facts(s, truth):
    from . import insight, live
    sim = insight.simulate(s)
    t0 = sim.get("start_t")
    signs = [{"key": g["key"], "name": g["name"], "family": g["family"], "kind": g["kind"], "time": g["time"],
              "hours_from_start": round((g["t"] - t0) / 3600, 2) if t0 is not None else None,
              "actors": g["actors"][:3], "record": g.get("record"), "why": g["why"]} for g in sim["signals"]]
    ev = live.evaluate_rules(s, live.clean_rules(json.loads(json.dumps(live.DEFAULT_RULES))))
    rules = [{"id": r["id"], "name": r["name"], "severity": r["severity"], "fired": r["fired"], "time": r.get("time"),
              "hours_from_start": round((r["t"] - t0) / 3600, 2) if (r["fired"] and t0 is not None) else None,
              "why": r.get("why"), "record": r.get("record")} for r in ev["rules"]]
    agent_of = {r: x["agent"] for r, x in truth["records"].items()}
    dl = s.flow["_deliveries"]
    cross = [d for d in dl if agent_of.get(d["write_id"]) and agent_of.get(d["read_id"])
             and agent_of[d["write_id"]] != agent_of[d["read_id"]]]
    selfm = [d for d in dl if agent_of.get(d["write_id"]) and agent_of.get(d["write_id"]) == agent_of.get(d["read_id"])]
    return {"signs": signs, "rules": rules,
            "messages_between_agents": len(cross), "messages_one_agent_two_tokens": len(selfm),
            "agent_pairs_reported": len({(agent_of[d["write_id"]], agent_of[d["read_id"]]) for d in cross}),
            "harm_records_flagged": len(s.harm_sorted)}


def _first_true_harm(truth):
    ts = [truth["records"][r]["t"] for r in truth.get("harm", []) if r in truth["records"]]
    return min(ts) if ts else None


def run_one(folder, truth):
    """Load one generated swarm and score it. Returns a flat row of measures plus details."""
    t0 = time.time()
    s = _load(folder, truth)
    load_s = time.time() - t0
    sc = groundtruth.score(s, truth)
    m, p, d, e, i = sc["messages"], sc["pairs"], sc["dating"], sc["early_signs"], sc["identity"]
    bands = i.get("bands") or {}
    cum = i.get("cumulative") or {}
    direct = _direct_rule(s, truth)
    benign = truth.get("mode") == "benign"
    row = {
        "msg_precision": m["precision"], "msg_recall": m["recall"],
        "pair_precision": p["precision"], "pair_recall": p["recall"],
        "sign_recall": e["recall"], "sign_on_time": e["on_time_share"], "sign_error_h": e["median_abs_error_hours"],
        "dating_error_h": d["median_error_hours"], "dating_p90_h": d["p90_error_hours"],
        "dating_coverage": d["inside_stated_range"],
        "id_high_precision": (bands.get("high") or {}).get("precision"),
        "id_medium_precision": (bands.get("medium") or {}).get("precision"),
        "id_low_precision": (bands.get("low") or {}).get("precision"),
        "id_high_proposed": (bands.get("high") or {}).get("proposed"),
        "id_recall_high": (cum.get("high") or {}).get("recall"),
        "id_recall_any": (cum.get("any") or {}).get("recall"),
        "id_direct_precision": direct["precision"], "id_direct_recall": direct["recall"],
        "agents_error": (i["estimated_agents"] - i["true_agents_seen"]) if i.get("estimated_agents") is not None else None,
    }
    out = {"records": sc["records"], "true_messages": sc["true_messages"], "load_seconds": round(load_s, 2),
           "measures": row,
           "counts": {"messages_found": m["found"], "messages_correct": m["correct"],
                      "by_grade": m.get("by_grade"),
                      "false_positive_reasons": m["false_positives"], "missed_reasons": m["missed"],
                      "dating_estimated": d["estimated"],
                      "signs": [{k: x.get(k) for k in ("key", "name", "error_hours", "on_time")} for x in e["signs"]],
                      "signs_not_in_truth": e["not_in_truth"],
                      "identity_bands": bands, "identity_direct_rule": direct,
                      "true_identity_pairs": i.get("true_pairs"), "estimated_agents": i.get("estimated_agents"),
                      "true_agents_seen": i.get("true_agents_seen")}}
    if benign:
        out["benign"] = _benign_facts(s, truth)
        row.update({"alert_after_first_message_h": None, "alert_lead_h": None, "watch_lead_h": None})
    else:
        from . import live
        ev = live.evaluate_rules(s, live.clean_rules(json.loads(json.dumps(live.DEFAULT_RULES))))
        fh = _first_true_harm(truth)
        fm = min((truth["records"][r]["t"] for _, r, _ in truth["messages"] if r in truth["records"]), default=None)
        out["rules"] = [{"id": r["id"], "fired": r["fired"], "time": r.get("time"), "why": r.get("why"),
                         "hours_before_first_true_harm": round((fh - r["t"]) / 3600, 2) if (r["fired"] and fh) else None}
                        for r in ev["rules"]]
        fired = {r["id"]: r["t"] for r in ev["rules"] if r["fired"]}
        row["alert_after_first_message_h"] = round((fired["alert-coord2"] - fm) / 3600, 2) if ("alert-coord2" in fired and fm) else None
        row["alert_lead_h"] = round((fh - fired["alert-coord2"]) / 3600, 2) if ("alert-coord2" in fired and fh) else None
        row["watch_lead_h"] = round((fh - fired["watch-harm"]) / 3600, 2) if ("watch-harm" in fired and fh) else None
    return out


# ------------------------------------------------------------------ the suite

def _rng(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    med = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return {"min": round(v[0], 4), "median": round(med, 4), "max": round(v[-1], 4), "n": len(v)}


def run_suite(out, seeds=(1, 2, 3), quick=False, settings=None, log=print, keep_swarms=True):
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"    # generated swarms are small; keep the user's cache clean
    from . import identity as idm
    save_dec = idm.SAVE_DECISIONS
    idm.SAVE_DECISIONS = False
    started = time.time()
    chosen = [x for x in SETTINGS if not settings or x[0] in settings]
    runs = []
    swarm_root = os.path.join(out, "swarms")
    try:
        for name, label, params in chosen:
            for seed in seeds:
                p = dict(params)
                if quick:
                    p["agents"] = min(p.get("agents", 40), QUICK_AGENTS)
                folder = os.path.join(swarm_root, f"{name}-s{seed}")
                if os.path.isdir(folder):
                    shutil.rmtree(folder)
                truth = groundtruth.make(folder, seed=seed, **p)
                r = run_one(folder, truth)
                r.update({"setting": name, "label": label, "seed": seed, "params": truth["params"],
                          "mode": truth.get("mode", "coordinated")})
                runs.append(r)
                mm = r["measures"]
                log(f"{name:<16} seed {seed}: {r['records']:>5} records  messages P {_p(mm['msg_precision'])} R {_p(mm['msg_recall'])}"
                    f"  identity high P {_p(mm['id_high_precision'])} ({mm['id_high_proposed']})"
                    + (f"  benign: {len(r['benign']['signs'])} signs, {sum(x['fired'] for x in r['benign']['rules'])} rules fire"
                       if "benign" in r else ""))
                if not keep_swarms:
                    shutil.rmtree(folder, ignore_errors=True)
    finally:
        idm.SAVE_DECISIONS = save_dec
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    summary = summarize(runs)
    summary.update({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "seeds": list(seeds), "quick": bool(quick), "seconds": round(time.time() - started, 1),
                    "command": "python3 -m agenttrace.validation run --out " + out + " --seeds " + " ".join(map(str, seeds))
                    + (" --quick" if quick else "")})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({**summary, "runs": runs}, f, indent=1)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(markdown(summary))
    return {**summary, "runs": runs}


def _p(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def summarize(runs):
    by_setting = defaultdict(list)
    for r in runs:
        by_setting[r["setting"]].append(r)
    settings = []
    for name, label, params in SETTINGS:
        rs = by_setting.get(name)
        if not rs:
            continue
        settings.append({"name": name, "label": label, "mode": rs[0]["mode"], "runs": len(rs),
                         "records": _rng([r["records"] for r in rs]),
                         "true_messages": _rng([r["true_messages"] for r in rs]),
                         "measures": {k: _rng([r["measures"][k] for r in rs]) for k in MEASURE}})
    coord = [r for r in runs if r["mode"] != "benign"]
    benign = [r for r in runs if r["mode"] == "benign"]
    overall = {k: _rng([r["measures"][k] for r in coord]) for k in MEASURE}
    # pooled identity precision per band (all coordinated and benign runs together)
    pooled = {}
    for b in groundtruth.BANDS:
        n = sum((r["counts"]["identity_bands"].get(b) or {}).get("proposed", 0) for r in runs)
        k = sum((r["counts"]["identity_bands"].get(b) or {}).get("correct", 0) for r in runs)
        wrong = Counter()
        for r in runs:
            wrong.update((r["counts"]["identity_bands"].get(b) or {}).get("wrong_pairs_evidence", {}))
        pooled[b] = {"proposed": n, "correct": k, "precision": round(k / n, 4) if n else None,
                     "precision_ci": groundtruth._wilson(k, n), "wrong_pairs_evidence": dict(wrong.most_common(8))}
    dn = sum(r["counts"]["identity_direct_rule"]["proposed"] for r in runs)
    dk = sum(r["counts"]["identity_direct_rule"]["correct"] for r in runs)
    tp = sum(r["counts"]["true_identity_pairs"] or 0 for r in runs)
    pooled["direct_rule"] = {"proposed": dn, "correct": dk, "precision": round(dk / dn, 4) if dn else None,
                             "precision_ci": groundtruth._wilson(dk, dn), "recall": round(dk / tp, 4) if tp else None,
                             "true_pairs": tp}
    # message precision per confidence grade, pooled over the coordinated runs (all, and the real-world-style settings)
    def grades(rs):
        out = {}
        for g in ("direct", "inferred", "weak"):
            n = sum(((r["counts"].get("by_grade") or {}).get(g) or {}).get("found", 0) for r in rs)
            k = sum(((r["counts"].get("by_grade") or {}).get(g) or {}).get("correct", 0) for r in rs)
            out[g] = {"found": n, "correct": k, "precision": round(k / n, 4) if n else None,
                      "precision_ci": groundtruth._wilson(k, n) if n else None}
        return out
    message_grades = {"all": grades(coord), "realworld": grades([r for r in coord if (r.get("params") or {}).get("realworld")])}
    # benign: how often each sign and each default rule fires
    fires = {}
    for r in benign:
        for g in r["benign"]["signs"]:
            x = fires.setdefault(("sign", g["key"]), {"what": "sign", "key": g["key"], "name": g["name"], "family": g["family"],
                                                      "kind": g["kind"], "runs": 0, "hours": [], "example": g["why"]})
            x["runs"] += 1
            if g["hours_from_start"] is not None:
                x["hours"].append(g["hours_from_start"])
        for rule in r["benign"]["rules"]:
            x = fires.setdefault(("rule", rule["id"]), {"what": "rule", "key": rule["id"], "name": rule["name"],
                                                        "severity": rule["severity"], "runs": 0, "hours": [], "example": None})
            if rule["fired"]:
                x["runs"] += 1
                x["example"] = x["example"] or rule["why"]
                if rule.get("hours_from_start") is not None:
                    x["hours"].append(rule["hours_from_start"])
    bl = []
    for x in fires.values():
        x["hours_from_start"] = _rng(x.pop("hours"))
        x["of"] = len(benign)
        bl.append(x)
    bl.sort(key=lambda x: (x["what"] != "rule", -x["runs"], x["key"]))
    benign_sum = {"runs": len(benign), "fires": bl,
                  "messages_between_agents": _rng([r["benign"]["messages_between_agents"] for r in benign]),
                  "messages_one_agent_two_tokens": _rng([r["benign"]["messages_one_agent_two_tokens"] for r in benign]),
                  "agent_pairs_reported": _rng([r["benign"]["agent_pairs_reported"] for r in benign]),
                  "harm_records_flagged": _rng([r["benign"]["harm_records_flagged"] for r in benign]),
                  "identity_high_proposed": _rng([r["measures"]["id_high_proposed"] for r in benign]),
                  "by_setting": {}}
    for name in sorted({r["setting"] for r in benign}):
        rs = [r for r in benign if r["setting"] == name]
        benign_sum["by_setting"][name] = {
            "runs": len(rs),
            "rules_fired": dict(Counter(x["id"] for r in rs for x in r["benign"]["rules"] if x["fired"])),
            "signs": dict(Counter(g["key"] for r in rs for g in r["benign"]["signs"]))}
    per_sign = {}
    for r in coord:
        for x in r["counts"]["signs"]:
            y = per_sign.setdefault(x["key"], {"key": x["key"], "name": x["name"], "runs": 0, "found": 0, "on_time": 0, "errors": []})
            y["runs"] += 1
            if x["error_hours"] is not None:
                y["found"] += 1
                y["errors"].append(x["error_hours"])
                y["on_time"] += bool(x["on_time"])
    signs = []
    for y in per_sign.values():
        y["error_hours"] = _rng(y.pop("errors"))
        signs.append(y)
    signs.sort(key=lambda y: (-y["on_time"] / max(1, y["runs"]), y["key"]))
    alerts = []
    for r in coord:
        for x in r.get("rules", []):
            if x["fired"] and x["hours_before_first_true_harm"] is not None:
                alerts.append((x["id"], x["hours_before_first_true_harm"]))
    alert_lead = {k: _rng([h for i, h in alerts if i == k]) for k in sorted({i for i, _ in alerts})}
    return {"about": "Swarm Tracer validation on simulated swarms (agenttrace.validation). Ranges are min, median, "
                     "max over seeds; the simulations are ours and real swarms differ.",
            "measures": [MEASURE[k] for k, _, _, _ in MEASURES], "groups": [{"name": g, "keys": ks} for g, ks in GROUPS],
            "settings": settings, "overall": overall, "identity_pooled": pooled, "message_grades": message_grades, "benign": benign_sum, "signs": signs,
            "alert_hours_before_first_true_harm": alert_lead,
            "coordinated_runs": len(coord), "benign_runs": len(benign)}


def _cell(x, unit):
    if not x:
        return "–"
    f = (lambda v: f"{100 * v:.0f}%") if unit == "share" else (lambda v: f"{v:.2f}") if unit == "hours" else (lambda v: f"{v:g}")
    if x["min"] == x["max"]:
        return f(x["median"])
    return f"{f(x['min'])}–**{f(x['median'])}**–{f(x['max'])}"


def markdown(sm):
    L = [f"Generated {sm.get('generated', '')} by `{sm.get('command', 'python3 -m agenttrace.validation run')}`. "
         f"{sm['coordinated_runs']} coordinated and {sm['benign_runs']} benign simulated swarms. "
         "Cells are min–**median**–max over seeds; one value means all seeds agree.", ""]
    coord = [x for x in sm["settings"] if x["mode"] != "benign"]
    for g in sm["groups"]:
        keys = g["keys"]
        L.append(f"### {g['name']}")
        L.append("")
        L.append("| setting | " + " | ".join(MEASURE[k]["label"] for k in keys) + " |")
        L.append("|---|" + "---|" * len(keys))
        rows = coord + ([x for x in sm["settings"] if x["mode"] == "benign"] if g["name"] == "Identity merging" else [])
        for x in rows:
            L.append(f"| {x['label']} | " + " | ".join(_cell(x["measures"][k], MEASURE[k]["unit"]) for k in keys) + " |")
        L.append("| **all coordinated** | " + " | ".join(_cell(sm["overall"][k], MEASURE[k]["unit"]) for k in keys) + " |")
        L.append("")
    if sm.get("signs"):
        L.append("### Each early sign on the coordinated swarms")
        L.append("")
        L.append("| sign | found | within 1 h of the truth | tool minus true time, h (min–median–max) |")
        L.append("|---|---|---|---|")
        for y in sm["signs"]:
            L.append(f"| {y['name']} | {y['found']} of {y['runs']} | {y['on_time']} of {y['runs']} | {_cell(y['error_hours'], 'hours')} |")
        L.append("")
    ip = sm["identity_pooled"]
    L.append("### Identity merge proposals, all runs pooled")
    L.append("")
    L.append("| band | proposed | right | precision (95% range) | evidence on the wrong pairs |")
    L.append("|---|---|---|---|---|")
    for b in groundtruth.BANDS + ("direct_rule",):
        x = ip[b]
        ci = x.get("precision_ci")
        ev = ", ".join(f"{k} {v}" for k, v in (x.get("wrong_pairs_evidence") or {}).items())
        L.append(f"| {b.replace('_', ' ')} | {x['proposed']} | {x['correct']} | {_p(x['precision'])}"
                 f"{f' ({_p(ci[0])}–{_p(ci[1])})' if ci else ''} | {ev or '–'} |")
    L.append("")
    mg = sm.get("message_grades")
    if mg:
        L.append("### Message precision by confidence grade, coordinated swarms pooled")
        L.append("")
        L.append("Each message the tool reports carries a grade: direct (the verbs of both sides sit in the very call that names "
                 "the place), inferred (found through a variable, helper or LFS operation) or weak (a default, a merged place, "
                 "or an estimated time more than an hour from the other side). Precision is against the simulator's true messages.")
        L.append("")
        L.append("| grade | all coordinated: reported | right | precision (95% range) | real-world-style settings: reported | right | precision (95% range) |")
        L.append("|---|---|---|---|---|---|---|")
        for g in ("direct", "inferred", "weak"):
            cells = []
            for key in ("all", "realworld"):
                x = mg[key][g]
                ci = x.get("precision_ci")
                cells += [str(x["found"]), str(x["correct"]),
                          (_p(x["precision"]) + (f" ({_p(ci[0])}–{_p(ci[1])})" if ci else "")) if x["found"] else "–"]
            L.append(f"| {g} | " + " | ".join(cells) + " |")
        L.append("")
    b = sm["benign"]
    if b["runs"]:
        L.append(f"### Benign baseline ({b['runs']} swarms with no coordination)")
        L.append("")
        L.append(f"Messages between different agents reported: {_cell(b['messages_between_agents'], 'count')}; "
                 f"between two tokens of one agent: {_cell(b['messages_one_agent_two_tokens'], 'count')}; "
                 f"records flagged harmful by the pack: {_cell(b['harm_records_flagged'], 'count')}; "
                 f"identity pairs proposed as high: {_cell(b['identity_high_proposed'], 'count')}.")
        L.append("")
        L.append("| fires | what | runs | hours from the start |")
        L.append("|---|---|---|---|")
        for x in b["fires"]:
            what = ("default rule (" + x.get("severity", "") + ")") if x["what"] == "rule" else f"sign ({x['family']}, {x['kind']})"
            L.append(f"| {x['name']} | {what} | {x['runs']} of {x['of']} | {_cell(x['hours_from_start'], 'hours')} |")
        L.append("")
    if sm.get("alert_hours_before_first_true_harm"):
        L.append("### Default rules on the coordinated swarms: hours before the first true harmful action")
        L.append("")
        L.append("| rule | hours before (min–median–max) |")
        L.append("|---|---|")
        for k, x in sm["alert_hours_before_first_true_harm"].items():
            L.append(f"| {k} | {_cell(x, 'hours')} |")
        L.append("")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ an older version's rules on the same swarms

_DUMP = ("import json,os,sys;os.environ['SWARM_TRACER_NO_CACHE']='1';from agenttrace.session import Session;"
         "s=Session();s.load(sys.argv[1],'code_traces.json',{},'x');"
         "print(json.dumps([[d['write_id'],d['read_id']] for d in s.flow['_deliveries']]))")


def _links_by(code_root, trace):
    """The (write, read) links another checkout of the tool reports on a trace file (run in its own process)."""
    import subprocess
    import tempfile
    env = dict(os.environ, PYTHONPATH=code_root, SWARM_TRACER_NO_CACHE="1", SWARM_TRACER_HOME=tempfile.mkdtemp(prefix="st_old_"))
    out = subprocess.run([sys.executable, "-c", _DUMP, os.path.abspath(trace)], cwd=code_root, env=env, capture_output=True, text=True, timeout=900)
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[-400:])
    return [tuple(x) for x in json.loads(out.stdout.strip().splitlines()[-1])]


def score_links(links, truth):
    """Links against a truth file: precision/recall on a coordinated swarm; on a benign one, how many links
    join two different agents (every one is false)."""
    true = {(w, r) for w, r, _ in truth["messages"]}
    found = set(links)
    ok = len(found & true)
    agent_of = {r: x["agent"] for r, x in truth["records"].items()}
    cross = sum(1 for w, r in found if agent_of.get(w) and agent_of.get(r) and agent_of[w] != agent_of[r])
    return {"found": len(found), "correct": ok, "true": len(true), "between_agents": cross,
            "precision": round(ok / len(found), 4) if found else None, "recall": round(ok / len(true), 4) if true else None}


def compare_old_rules(worktree, out, label="v1.1.0", settings=("base", "realworld", "benign_realworld"), log=print):
    """Run an older checkout's message rules on swarms the suite already generated under <out>/swarms, next to
    the current code's, and save <out>/old_rules.json. Shows whether a setting can tell the two apart."""
    from .session import Session
    swarm_root = os.path.join(out, "swarms")
    labels = {n: l for n, l, _ in SETTINGS}
    rows = []
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    try:
        for name in settings:
            seeds = []
            for folder in sorted(f for f in os.listdir(swarm_root) if f.rsplit("-s", 1)[0] == name):
                tp = groundtruth.truth_path_for(os.path.join(swarm_root, folder))
                truth = groundtruth.load_truth(tp)
                trace = tp[:-len(groundtruth.TRUTH_EXT)]
                s = Session()
                s.load(trace, "code_traces.json", {}, folder)
                now = score_links([(d["write_id"], d["read_id"]) for d in s.flow["_deliveries"]], truth)
                old = score_links(_links_by(worktree, trace), truth)
                seeds.append({"seed": int(folder.rsplit("-s", 1)[1]), "old": old, "now": now})
                log(f"{folder:<22} old P {_p(old['precision'])} R {_p(old['recall'])} ({old['found']} links, {old['between_agents']} between agents)"
                    f"   now P {_p(now['precision'])} R {_p(now['recall'])} ({now['found']} links, {now['between_agents']} between agents)")
            if not seeds:
                continue

            def pool(k):
                f, c, t = (sum(x[k][j] for x in seeds) for j in ("found", "correct", "true"))
                return {"found": f, "correct": c, "true": t, "between_agents": sum(x[k]["between_agents"] for x in seeds),
                        "precision": round(c / f, 4) if f else None, "precision_ci": groundtruth._wilson(c, f),
                        "recall": round(c / t, 4) if t else None, "recall_ci": groundtruth._wilson(c, t)}
            rows.append({"name": name, "label": labels.get(name, name), "mode": "benign" if name.startswith("benign") else "coordinated",
                         "runs": len(seeds), "old": pool("old"), "now": pool("now"), "seeds": seeds})
    finally:
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    doc = {"about": "Message links reported by an older version's rules and by the current code on the same simulated swarms "
                    "(agenttrace.validation old-rules). Pooled over seeds; intervals are Wilson 95%.",
           "old_version": label, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "settings": rows}
    with open(os.path.join(out, "old_rules.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return doc


def old_rules_summary():
    """The saved old-versus-current comparison, or None."""
    for p in _summary_paths():
        q = os.path.join(os.path.dirname(p), "old_rules.json")
        if os.path.isfile(q):
            with open(q, encoding="utf-8") as f:
                return json.load(f)
    return None


# ------------------------------------------------------------------ routes

def _summary_paths(quick=False):
    seen, out = set(), []
    for d in (os.environ.get("SWARM_TRACER_VALIDATION_DIR"), os.path.join(REPO, "reports", "validation"),
              os.path.join(os.path.expanduser("~"), ".swarm-tracer", "validation")):
        if d and d not in seen:
            seen.add(d)
            out.append(os.path.join(d, "quick", "summary.json") if quick else os.path.join(d, "summary.json"))
    return out


def latest_summary(with_runs=False, which=None):
    """The newest full summary (or, with which="quick" or when there is no full one, the newest quick run
    started from the app, which is saved apart so it never replaces the full suite)."""
    full = [p for p in _summary_paths() if os.path.isfile(p)]
    quick = [p for p in _summary_paths(quick=True) if os.path.isfile(p)]
    found = quick if (which == "quick" and quick) else (full or quick)
    if not found:
        return None
    p = max(found, key=os.path.getmtime)
    with open(p, encoding="utf-8") as f:
        sm = json.load(f)
    if not with_runs:
        sm.pop("runs", None)
    sm.update({"file": p, "has_full": bool(full), "has_quick": bool(quick)})
    return sm


RUN = {"running": False, "error": None, "lock": threading.Lock()}


def get_summary(state, q):
    sm = latest_summary(with_runs=q.get("runs") in ("1", "true"), which=q.get("which"))
    if sm is None:
        return {"available": False, "running": RUN["running"], "error": RUN["error"],
                "why": "No validation summary saved yet.",
                "command": "python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3"}
    return {"available": True, "running": RUN["running"], "error": RUN["error"], **sm}


def post_run(state, q, body=b""):
    """Run a quick suite (one seed, 20 agents) in the background into <out>/quick; poll
    validation_summary?which=quick."""
    with RUN["lock"]:
        if RUN["running"]:
            return {"started": False, "running": True}
        RUN["running"], RUN["error"] = True, None

    def go():
        try:
            run_suite(os.path.join(default_out(), "quick"), seeds=(1,), quick=True, log=lambda *_: None, keep_swarms=False)
        except Exception as e:      # pragma: no cover
            RUN["error"] = str(e)
        finally:
            RUN["running"] = False
    threading.Thread(target=go, daemon=True).start()
    return {"started": True, "running": True}


GET = {"validation_summary": get_summary}
POST = {"validation_run": post_run}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.validation", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="generate the suite, load and score every swarm, write summary.json and summary.md")
    r.add_argument("--out", default=None, help="output folder (default reports/validation)")
    r.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    r.add_argument("--quick", action="store_true", help=f"at most {QUICK_AGENTS} agents per swarm")
    r.add_argument("--settings", nargs="+", default=None, choices=[x[0] for x in SETTINGS])
    r.add_argument("--drop-swarms", action="store_true", help="delete the generated swarms after scoring")
    o = sub.add_parser("old-rules", help="run an older checkout's message rules on the generated swarms, next to the current code's")
    o.add_argument("--worktree", required=True, help="a checkout of the older version (for example: git worktree add DIR v1.1.0)")
    o.add_argument("--label", default="v1.1.0")
    o.add_argument("--out", default=None, help="the suite's output folder (default reports/validation)")
    o.add_argument("--settings", nargs="+", default=["base", "realworld", "benign_realworld"], choices=[x[0] for x in SETTINGS])
    a = ap.parse_args(argv)
    out = a.out or default_out()
    if a.cmd == "old-rules":
        doc = compare_old_rules(a.worktree, out, a.label, a.settings)
        print(f"wrote {os.path.join(out, 'old_rules.json')}")
        return 0 if doc["settings"] else 1
    sm = run_suite(out, seeds=a.seeds, quick=a.quick, settings=a.settings, keep_swarms=not a.drop_swarms)
    print()
    print(markdown(sm))
    print(f"wrote {os.path.join(out, 'summary.json')} and summary.md ({sm['seconds']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

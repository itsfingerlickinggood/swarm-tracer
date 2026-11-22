"""The tool measured on two public datasets of failed multi-agent runs, against the datasets' own labels.

    python3 -I agenttrace/failure_eval.py who_and_when     # datasets-ext/who_and_when  -> reports/external/who_and_when/
    python3 -I agenttrace/failure_eval.py mast_data        # datasets-ext/mast_data     -> reports/external/mast_data/
    python3 -I agenttrace/failure_eval.py story SLUG       # check that an investigation story builds (a temp folder)

(-I keeps Python from importing anything that sits beside the data. `python3 -m agenttrace.failure_eval` is the same.)

Who&When (Zhang et al., MIT): 184 failed runs, each with a human label of the agent and the step that caused the
failure. MAST-Data (Cemri, Pan, Yang et al., CC BY 4.0): 1,642 runs of seven frameworks with 14 failure-mode labels
made by an LLM judge. Neither is an attack and neither is a swarm: each run is one small cooperative team on one task.
So three things can be measured, and only these:

1. Who talked to whom. Some logs name the recipient of a message (Magentic-One's "Orchestrator (-> WebSurfer)",
   ChatDev's "A<->B", AppWorld's "Message to X Agent", HyperAgent's "A->B"). Kept: does the tool list each one as a
   direct message? Withheld: the recipients are removed, and the tool's own deliveries are scored against them.
2. Who failed, and when (Who&When only). The tool has no failure-attribution feature. We read its flags as blame by
   two rules fixed before any score was computed (the record of its first warning sign; its first harmful record) and
   set them beside chance and two plain baselines.
3. False alarms. Every run is benign in the tool's sense (no attack, nothing hidden), so each firing of the default
   rules, the frozen signs and the baseline alarms (agenttrace/earlywarn.py and baselines.py, run as they are) is a
   false alarm. Counted once per run, with Wilson intervals.

Clocks. Who&When and four MAST frameworks print no times, and the tool's replay needs times. "As logged" loads them
undated. "Step clock" gives each record a time from its position (60 s a step), so order-based signs can run; hourly
baselines cannot fire on it and rates per 24 h mean nothing on it. ChatDev, MetaGPT and OpenManus print real times.
"""
import datetime as dt
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):          # run by path under python3 -I: the repository is not on the path yet
    sys.path.insert(0, ROOT)
    __package__ = "agenttrace"
    import agenttrace  # noqa: F401

from . import earlywarn, insight, readers_failure as RF          # noqa: E402
from .messages import DIRECT_HOW                                  # noqa: E402
from .session import Session                                      # noqa: E402

DATA = os.path.join(ROOT, "datasets-ext")
OUT = os.path.join(ROOT, "reports", "external")
RULES = ("watch-harm", "alert-coord2", "baseline-volume")
TOOL_FILES = ("agenttrace/earlywarn.py", "agenttrace/baselines.py", "agenttrace/messages.py", "agenttrace/insight.py",
              "agenttrace/reconstruct.py", "agenttrace/live.py", "agenttrace/packs/generic.json", "agenttrace/packs/chat.json")

SOURCES = {
    "who_and_when": {
        "title": "Who&When", "dir": "who_and_when", "revision_file": "SOURCE_COMMIT.txt",
        "source": "https://github.com/ag2ai/Agents_Failure_Attribution",
        "licence": "MIT (LICENSE in the repository: Copyright (c) 2025 Ming Yin)",
        "attribution": "Zhang et al., \"Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM "
                       "Multi-Agent Systems\", ICML 2025, arXiv:2505.00212; data: github.com/ag2ai/Agents_Failure_Attribution (MIT)",
        "labels": "human annotators: the agent and the step that caused the failure, with a reason",
    },
    "mast_data": {
        "title": "MAST-Data (MAD)", "dir": "mast_data", "revision_file": "SOURCE_REVISION.txt",
        "source": "https://huggingface.co/datasets/mcemri/MAST-Data",
        "licence": "CC BY 4.0 (licence tag on the dataset card)",
        "attribution": "Cemri, Pan, Yang et al., \"Why Do Multi-Agent LLM Systems Fail?\", NeurIPS 2025, arXiv:2503.13657; "
                       "data: huggingface.co/datasets/mcemri/MAST-Data (CC BY 4.0). Records are shown as parsed by our reader "
                       "and cut to short excerpts.",
        "labels": "an LLM judge (the dataset card: \"not by human labelling\"): 14 failure modes per run, 0 / 1",
    },
}
# the dataset paper's own result, for scale; not re-measured here
PUBLISHED = {"agent": 0.535, "step": 0.142,
             "source": "abstract of arXiv:2505.00212: the best method there, an LLM reading the whole log"}


# ------------------------------------------------------------------ small helpers

def wilson(k, n):
    return earlywarn.wilson(k, n)


def rate(k, n):
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def step_of(rid):
    return int(str(rid).rsplit(":", 1)[1].split("~")[0])


def analyse(rows, name, pack="auto"):
    """One run loaded as its own trace, through the same path as a file (model.load with the rows already read)."""
    s = Session()
    s._analyze(name + ".jsonl", pack, rows=[dict(r) for r in rows])
    return s


def tool_state():
    """Short hashes of the code the numbers depend on, so a later reader can tell whether the tool has changed."""
    out = {}
    for rel in TOOL_FILES:
        try:
            with open(os.path.join(ROOT, rel), "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()[:16]
        except OSError:
            out[rel] = None
    return out


def revision_of(name):
    try:
        with open(os.path.join(DATA, SOURCES[name]["dir"], SOURCES[name]["revision_file"]), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# ------------------------------------------------------------------ one run

def measure(rows, name, pack="auto"):
    """What the tool reports on one run: its deliveries, its signs and rules, its first flags."""
    s = analyse(rows, name, pack)
    flow = s.flow
    named = lambda a: not str(a).startswith("run:")
    dels = [d for d in flow["_deliveries"] if named(d["from"]) and named(d["to"])]
    ew = earlywarn.extract(s, None, {"mode": "benign", "label": name})
    ew["agents"] = len({a for a, k in s.actor.values() if k != "run"})
    sim = insight.simulate(s)
    order = s.order
    signs = sorted((g for g in sim["signals"] if g.get("record") in s.by_id), key=lambda g: (g["t"], order[g["record"]], g["key"]))
    times = s.rec["_times"]
    harm_t = set(s.rec.get("_harm_times", []))
    harm = sorted((rid for rid, t in times.items() if t in harm_t), key=lambda r: order[r]) if harm_t else []
    who = lambda rid: s.actor[rid][0] if rid in s.actor else None
    return {
        "pack": (s.pack_choice or {}).get("pack") or pack, "records": len(s.events), "actors": ew["agents"],
        "dated": bool(ew["dated"]), "hours": ew["hours"],
        "direct": [(d["write_id"], d["from"], d["to"]) for d in dels if d["how"] == DIRECT_HOW],
        "direct_undated": flow.get("direct_messages_undated", 0),
        "inferred": [(d["write_id"], d["from"], d["to"]) for d in dels if d["how"] != DIRECT_HOW],
        "how": dict(Counter(d["how"] for d in dels if d["how"] != DIRECT_HOW)),
        "rules": {k: ew["rules"].get(k) is not None for k in RULES},
        "signs": sorted({g["id"] for g in ew["signs"]}),
        "baselines": sorted(k for k, v in (ew["alarms"].get("baseline") or {}).items() if v is not None),
        "first_sign": (signs[0]["record"], who(signs[0]["record"]), signs[0]["key"]) if signs else None,
        "first_harm": (harm[0], who(harm[0])) if harm else None,
        "ew": ew,
    }


# ------------------------------------------------------------------ 1. who talked to whom

def link_counts(logged, deliveries):
    """logged: [(record id, sender, recipient)] from the log. deliveries: [(write id, from, to)] from the tool.
    found: logged messages for which the tool has a delivery of that very record to the logged recipient.
    readers named / right: of the tool's deliveries that start at an addressed record, how many go to its addressee."""
    want = {(i, r) for i, _, r in logged}
    got = {(w, t) for w, _, t in deliveries}
    addressed = {i for i, _, _ in logged}
    from_addressed = {x for x in got if x[0] in addressed}
    pw, pg = {(s, r) for _, s, r in logged}, {(f, t) for _, f, t in deliveries}
    return {"logged": len(want), "found": len(want & got), "readers_named": len(from_addressed),
            "readers_right": len(from_addressed & want), "pairs_logged": len(pw), "pairs_tool": len(pg),
            "pairs_both": len(pw & pg), "pairs_either_way": sum(1 for p in pg if p in pw or (p[1], p[0]) in pw)}


def link_table(per_run):
    """Pooled over runs. Messages inside one run are not independent, so the interval is narrower than it should be;
    the per-run figures say how the runs spread."""
    tot = Counter()
    for c in per_run:
        tot.update(c)
    rec = sorted(c["found"] / c["logged"] for c in per_run if c["logged"])
    return {"runs": len(per_run), "runs_with_logged_recipients": len(rec),
            "message_recall": rate(tot["found"], tot["logged"]),
            "reader_precision": rate(tot["readers_right"], tot["readers_named"]),
            "pair_recall": rate(tot["pairs_both"], tot["pairs_logged"]),
            "pair_precision_vs_logged": rate(tot["pairs_both"], tot["pairs_tool"]),
            "pair_precision_either_direction": rate(tot["pairs_either_way"], tot["pairs_tool"]),
            "per_run_message_recall": {"min": round(rec[0], 3), "median": round(rec[len(rec) // 2], 3), "max": round(rec[-1], 3),
                                       "runs_at_zero": sum(1 for x in rec if x == 0)} if rec else None}


# ------------------------------------------------------------------ 2. who failed, and when

def attribution_row(run, m):
    """The dataset's label beside each way of naming a culprit. A rule with no flag in a run names nobody: a miss."""
    rows, t = run["rows"], run["truth"]
    actors = [r["actor"] for r in rows if r["actor"]]
    busiest = Counter(actors).most_common(1)[0][0] if actors else None     # ties: the one seen first
    preds = {
        "tool_first_sign": (m["first_sign"][1], step_of(m["first_sign"][0])) if m["first_sign"] else None,
        "tool_first_harm": (m["first_harm"][1], step_of(m["first_harm"][0])) if m["first_harm"] else None,
        "baseline_busiest_agent": (busiest, None),
        "baseline_first_step": (rows[0]["actor"], 0) if rows else None,
        "baseline_last_step": (rows[-1]["actor"], len(rows) - 1) if rows else None,
    }
    out = {"run": run["run"], "subset": run["subset"], "steps": len(rows), "agents": len(set(actors)),
           "mistake_agent": t["mistake_agent"], "mistake_step": t["mistake_step"], "preds": {}}
    for k, p in preds.items():
        out["preds"][k] = None if p is None else {"agent": p[0], "step": p[1], "agent_right": p[0] == t["mistake_agent"],
                                                  "step_right": p[1] is not None and p[1] == t["mistake_step"]}
    return out


def attribution_table(rows):
    n = len(rows)
    out = {"runs": n, "methods": {}}
    for k in ("tool_first_sign", "tool_first_harm", "baseline_busiest_agent", "baseline_first_step", "baseline_last_step"):
        named = [r["preds"][k] for r in rows if r["preds"][k]]
        m = {"names_someone": rate(len(named), n), "agent": rate(sum(1 for p in named if p["agent_right"]), n)}
        if k != "baseline_busiest_agent":
            m["step"] = rate(sum(1 for p in named if p["step_right"]), n)
        out["methods"][k] = m
    out["chance"] = {"agent": round(sum(1 / r["agents"] for r in rows if r["agents"]) / n, 4) if n else None,
                     "step": round(sum(1 / r["steps"] for r in rows if r["steps"]) / n, 4) if n else None,
                     "what": "the mean over runs of 1 / agents in the run and 1 / steps in the run"}
    return out


# ------------------------------------------------------------------ 3. false alarms

def alarm_table(ms, real_clock):
    """earlywarn.false_alarms on the runs, every run declared benign. Per-24-h rates are kept only on real clocks."""
    runs = [m["ew"] for m in ms]
    fa = earlywarn.false_alarms(runs)
    rows = []
    for r in fa["rows"]:
        row = {"kind": r["kind"], "id": r["id"], "name": r["name"], "runs_fired": r["alarms"], "runs": r["swarms"],
               "share": r["swarm_share"], "ci95": r["swarm_share_ci"]}
        if real_clock:
            row.update({"per_24h": r["per_24h"], "per_24h_ci95": [r["ci_low"], r["ci_high"]]})
        rows.append(row)
    return {"runs": len(runs), "runs_dated": fa["benign_runs"], "runs_undated": len(runs) - fa["benign_runs"],
            "trace_hours": fa["trace_hours"] if real_clock else None, "clock": "logged times" if real_clock else "step clock",
            "packs": dict(Counter(m["pack"] for m in ms)), "rows": rows}


def any_alarm(ms):
    k = sum(1 for m in ms if any(m["rules"].values()))
    return rate(k, len(ms))


# ------------------------------------------------------------------ a dataset, group by group

def evaluate_group(runs, addressed, real_clock, attribution=False, log=print, label=""):
    """runs: [{run, rows, ...}] of one layout. Returns (aggregate, per-run rows)."""
    runs = [r for r in runs if r["rows"]]
    out = {"runs": len(runs), "records": sum(len(r["rows"]) for r in runs),
           "actors_named_in_runs": len({x["actor"] for r in runs for x in r["rows"] if x["actor"]}),
           "records_with_time": sum(1 for r in runs for x in r["rows"] if x["time"]),
           "logged_messages_with_recipient": sum(len(RF.logged_messages(r["rows"])) for r in runs),
           "clock": "logged times" if real_clock else "step clock"}
    per_run = []
    kept, blind, plain, generic, attr = [], [], [], [], []
    as_logged = {"runs_dated": 0, "direct_messages_listed": 0, "direct_messages_undated": 0, "deliveries": 0, "runs_any_rule": 0}
    for n, r in enumerate(runs):
        name, rows = r["run"], r["rows"]
        logged = RF.logged_messages(rows)
        if not real_clock:                      # as logged: no times at all
            m0 = measure(rows, name)
            as_logged["runs_dated"] += m0["dated"]
            as_logged["direct_messages_listed"] += len(m0["direct"])
            as_logged["direct_messages_undated"] += m0["direct_undated"]
            as_logged["deliveries"] += len(m0["direct"]) + len(m0["inferred"])
            as_logged["runs_any_rule"] += any(m0["rules"].values())
        timed = rows if real_clock else RF.clocked(rows)
        m = measure(timed, name)
        plain.append(m)
        g = m if m["pack"] == "generic.json" else measure(timed, name, "generic.json")
        generic.append(g)
        row = {"run": name, "records": m["records"], "actors": m["actors"], "pack": m["pack"], "rules": m["rules"],
               "rules_generic_pack": g["rules"], "signs": m["signs"], "baselines": m["baselines"],
               "logged_recipients": len(logged), "deliveries": len(m["direct"]) + len(m["inferred"])}
        if logged:
            kept.append(link_counts(logged, m["direct"]))
            b = measure(RF.withheld(timed), name)
            c = link_counts(logged, b["inferred"])
            blind.append(c)
            row["blind"] = c
        if attribution:
            a = attribution_row(r, m)
            attr.append(a)
            row["attribution"] = {k: a[k] for k in ("mistake_agent", "mistake_step", "preds")}
        for extra in ("subset", "mas", "llm", "benchmark", "labels"):
            if extra in r:
                row[extra] = r[extra]
        per_run.append(row)
        if (n + 1) % 200 == 0:
            log(f"  {label}: {n + 1} of {len(runs)} runs")
    if not real_clock:
        out["as_logged"] = dict(as_logged, runs=len(runs),
                                note="no record has a time, so the replay, the signs and the rules cannot run")
    out["who_talked_to_whom"] = {"recipients_kept": link_table(kept), "recipients_withheld": link_table(blind),
                                 "how_inferred": dict(sum((Counter(m["how"]) for m in plain), Counter()))} if addressed and kept else None
    out["false_alarms"] = {"auto_pack": alarm_table(plain, real_clock), "generic_pack": alarm_table(generic, real_clock),
                           "any_default_rule": {"auto_pack": any_alarm(plain), "generic_pack": any_alarm(generic)}}
    if attribution:
        out["attribution"] = attribution_table(attr)
    return out, per_run


def labels_vs_alarms(per_run):
    """MAST-Data: do the default rules fire more on runs the judge marked as failed? (They are not built to.)"""
    failed = [r for r in per_run if any(v == 1 for v in r["labels"].values())]
    clean = [r for r in per_run if all(v == 0 for v in r["labels"].values())]
    out = {"runs_with_a_failure_mode": len(failed), "runs_with_none": len(clean),
           "runs_without_full_labels": len(per_run) - len(failed) - len(clean), "rules": {}}
    for k in RULES:
        out["rules"][k] = {"fired_on_failed": rate(sum(1 for r in failed if r["rules"][k]), len(failed)),
                           "fired_on_clean": rate(sum(1 for r in clean if r["rules"][k]), len(clean))}
    # the frameworks differ in how often they fail and in how often the Watch rule fires, so the pooled gap can be
    # the mix of frameworks and nothing else: the same comparison inside each one
    out["watch_by_layout"] = {}
    for mas in sorted({r["mas"] for r in per_run}):
        f, c = [r for r in failed if r["mas"] == mas], [r for r in clean if r["mas"] == mas]
        out["watch_by_layout"][mas] = {"fired_on_failed": rate(sum(1 for r in f if r["rules"]["watch-harm"]), len(f)),
                                       "fired_on_clean": rate(sum(1 for r in c if r["rules"]["watch-harm"]), len(c))}
    return out


def header(name):
    src = SOURCES[name]
    return {"dataset": name, "title": src["title"], "source": src["source"], "licence": src["licence"],
            "attribution": src["attribution"], "labels_made_by": src["labels"], "revision": revision_of(name),
            "measured_on": dt.date.today().isoformat(), "tool_version": _version(), "tool_files": tool_state(),
            "step_clock": f"{RF.STEP_SECONDS} s a step from {RF.STEP_BASE.date().isoformat()} (undated runs only)",
            "unit": "one run = one trace; every share is runs out of runs, with a Wilson 95% interval"}


def _version():
    try:
        from .tools.export_static import tool_version
        return tool_version()
    except Exception:
        return None


def eval_who_and_when(root=None, log=print):
    root = root or os.path.join(DATA, "who_and_when")
    runs = RF.load_who_and_when(root)
    res = header("who_and_when")
    res["label_check"] = {"runs": len(runs),
                          "label_step_is_by_label_agent": sum(1 for r in runs if r["truth"]["step_actor"] == r["truth"]["mistake_agent"]),
                          "note": "in the other runs the labelled step was spoken by a different agent than the labelled one; "
                                  "the two labels are scored separately, as the dataset gives them"}
    res["groups"], per_run = {}, []
    for sub in ("Algorithm-Generated", "Hand-Crafted"):
        part = [r for r in runs if r["subset"] == sub]
        if not part:
            continue
        g, rows = evaluate_group(part, addressed=(sub == "Hand-Crafted"), real_clock=False, attribution=True, log=log, label=sub)
        res["groups"][sub] = g
        per_run += rows
        log(f"  {sub}: {g['runs']} runs, {g['records']} records")
    res["totals"] = {"runs": len(per_run), "records": sum(r["records"] for r in per_run),
                     "records_with_time": sum(g["records_with_time"] for g in res["groups"].values()),
                     "logged_messages_with_recipient": sum(r["logged_recipients"] for r in per_run)}
    allattr = [dict(r["attribution"], steps=r["records"], agents=r["actors"]) for r in per_run]
    res["attribution_all"] = attribution_table(allattr)
    res["attribution_all"]["published_for_scale"] = PUBLISHED
    res["false_alarms_all"] = {
        "auto_pack": rate(sum(1 for r in per_run if any(r["rules"].values())), len(per_run)),
        "generic_pack": rate(sum(1 for r in per_run if any(r["rules_generic_pack"].values())), len(per_run)),
        "by_rule_auto_pack": {k: rate(sum(1 for r in per_run if r["rules"][k]), len(per_run)) for k in RULES},
        "by_rule_generic_pack": {k: rate(sum(1 for r in per_run if r["rules_generic_pack"][k]), len(per_run)) for k in RULES}}
    return res, per_run


def eval_mast(path=None, log=print, limit=None):
    path = path or os.path.join(DATA, "mast_data", "MAD_full_dataset.json")
    runs = RF.load_mast(path, limit)
    res = header("mast_data")
    res["parsing"] = {"runs_in_file": len(runs), "runs_parsed": sum(1 for r in runs if r["rows"]),
                      "runs_with_no_record": [r["run"] for r in runs if not r["rows"]],
                      "log_blocks_left_out": sum(r["skipped"] for r in runs),
                      "note": "left out: HTTP and usage lines (ChatDev), token counters (OpenManus), loop markers and a "
                              "second copy of each reply (AppWorld), start-up lines (HyperAgent)"}
    res["groups"], per_run = {}, []
    for mas in sorted({r["mas"] for r in runs}):
        part = [r for r in runs if r["mas"] == mas]
        g, rows = evaluate_group(part, addressed=mas in RF.MAST_ADDRESSED, real_clock=mas in RF.MAST_TIMED, log=log, label=mas)
        g["runs_in_file"] = len(part)
        res["groups"][mas] = g
        per_run += rows
        log(f"  {mas}: {g['runs']} runs, {g['records']} records")
    res["totals"] = {"runs": len(per_run), "records": sum(r["records"] for r in per_run),
                     "records_with_time": sum(g["records_with_time"] for g in res["groups"].values()),
                     "logged_messages_with_recipient": sum(r["logged_recipients"] for r in per_run)}
    res["false_alarms_all"] = {
        "auto_pack": rate(sum(1 for r in per_run if any(r["rules"].values())), len(per_run)),
        "generic_pack": rate(sum(1 for r in per_run if any(r["rules_generic_pack"].values())), len(per_run)),
        "by_rule_auto_pack": {k: rate(sum(1 for r in per_run if r["rules"][k]), len(per_run)) for k in RULES},
        "by_rule_generic_pack": {k: rate(sum(1 for r in per_run if r["rules_generic_pack"][k]), len(per_run)) for k in RULES}}
    pooled = Counter()
    for g in res["groups"].values():
        w = g.get("who_talked_to_whom")
        if w:
            for side in ("recipients_kept", "recipients_withheld"):
                for k in ("message_recall", "reader_precision", "pair_recall"):
                    pooled[(side, k, "k")] += w[side][k]["k"]
                    pooled[(side, k, "n")] += w[side][k]["n"]
    res["who_talked_to_whom_all"] = {side: {k: rate(pooled[(side, k, "k")], pooled[(side, k, "n")])
                                            for k in ("message_recall", "reader_precision", "pair_recall")}
                                     for side in ("recipients_kept", "recipients_withheld")}
    res["labels_vs_alarms"] = labels_vs_alarms(per_run)
    for r in per_run:
        r["failure_modes"] = sorted(k for k, v in r.pop("labels").items() if v == 1)
    return res, per_run


# ------------------------------------------------------------------ the written summary

def pct(r):
    if not r or r.get("share") is None:
        return "not measurable (n = 0)"
    lo, hi = r["ci95"]
    return f"{r['k']} of {r['n']} ({r['share'] * 100:.1f}%, 95% interval {lo * 100:.1f} to {hi * 100:.1f}%)"


def summary_md(res):
    name = res["dataset"]
    L = [f"# {res['title']}: the tool measured against someone else's labels", "",
         f"Source: <{res['source']}> at revision `{res['revision']}`. Licence: {res['licence']}.",
         f"Labels made by: {res['labels_made_by']}.",
         f"Measured on {res['measured_on']} with Swarm Tracer {res['tool_version']}; `earlywarn.py` and `baselines.py` run as they were that day "
         f"(hashes in `results.json`). Rebuild: `python3 -I agenttrace/failure_eval.py {name}`.", "",
         f"Loaded: **{res['totals']['runs']:,} runs, {res['totals']['records']:,} records**. "
         f"{res['totals']['logged_messages_with_recipient']:,} records name their recipient in the log.", "",
         "Every run is one small cooperative team on one task: not an attack and not a swarm. A share is runs out of runs.", ""]
    if name == "mast_data":
        p = res["parsing"]
        L += [f"Parsed {p['runs_parsed']:,} of {p['runs_in_file']:,} runs ({len(p['runs_with_no_record'])} have no framework header in their text). "
              f"{p['log_blocks_left_out']:,} log blocks that are not agent turns were left out.", ""]
    L += ["## Who talked to whom", "",
          "A pair is (sender, recipient) inside one run. A message is one record and its recipient.", "",
          "| Layout | Runs | Logged messages with a recipient | Recipients kept: listed as a direct message | Withheld: logged pairs the tool finds | Withheld: the tool's pairs that are logged | ...logged in either direction | Withheld: logged messages the tool finds |",
          "|---|---|---|---|---|---|---|---|"]
    for g, v in res["groups"].items():
        w = v.get("who_talked_to_whom")
        if not w:
            L.append(f"| {g} | {v['runs']} | 0 (the log names no recipient) | – | – | – | – | – |")
            continue
        k, b = w["recipients_kept"], w["recipients_withheld"]
        L.append(f"| {g} | {v['runs']} | {v['logged_messages_with_recipient']:,} | {pct(k['message_recall'])} | {pct(b['pair_recall'])} | "
                 f"{pct(b['pair_precision_vs_logged'])} | {pct(b['pair_precision_either_direction'])} | {pct(b['message_recall'])} |")
    L += ["", "Kept is a check of the reader and the direct-message path, not an accuracy. Withheld is the measurement: the tool sees "
          "only who spoke, in what order, and the text, and links a speaker to whoever posted before in the same conversation. "
          "The logs address only some messages (an instruction, not the answer to it), so a pair of the tool's that is not logged is not "
          "shown to be wrong; the either-direction column counts a pair whose reverse is logged. Each write counts once per reader, so "
          "the tool finds the pair far more often than the single message. Pairs and messages inside a run are not independent, so "
          "these intervals are too narrow.", ""]
    und = {g: v["as_logged"] for g, v in res["groups"].items() if v.get("as_logged")}
    if und:
        runs = sum(a["runs"] for a in und.values())
        L += ["## As logged, without times", "",
              f"{', '.join(und)}: no record has a time. Loaded as logged, {sum(a['runs_dated'] for a in und.values())} of {runs:,} runs are dated, "
              f"the tool holds {sum(a['direct_messages_undated'] for a in und.values()):,} logged messages as undated and puts "
              f"{sum(a['direct_messages_listed'] for a in und.values()):,} of them in the who-talked-to-whom graph, and no sign or rule can fire "
              f"({sum(a['runs_any_rule'] for a in und.values())} runs). Everything else on these layouts uses the step clock.", ""]
    if "attribution_all" in res:
        a = res["attribution_all"]
        L += ["## Who failed, and when", "",
              "The tool has no failure-attribution feature. Two rules, fixed before scoring, read its flags as blame.", "",
              "| Method | Names someone | Agent right | Step right |", "|---|---|---|---|"]
        names = {"tool_first_sign": "Tool: record of its first warning sign", "tool_first_harm": "Tool: its first harmful record",
                 "baseline_busiest_agent": "Baseline: the agent with most records", "baseline_first_step": "Baseline: step 0",
                 "baseline_last_step": "Baseline: the last step"}
        for k, m in a["methods"].items():
            L.append(f"| {names[k]} | {pct(m['names_someone'])} | {pct(m['agent'])} | {pct(m['step']) if 'step' in m else '–'} |")
        L += ["", f"Chance: agent {a['chance']['agent'] * 100:.1f}%, step {a['chance']['step'] * 100:.1f}% ({a['chance']['what']}). "
              f"For scale, the dataset's paper reports {PUBLISHED['agent'] * 100:.1f}% and {PUBLISHED['step'] * 100:.1f}% for its best method "
              f"({PUBLISHED['source']}); we did not re-measure that.", ""]
        for g, v in res["groups"].items():
            t = v["attribution"]["methods"]
            L.append(f"- {g} ({v['runs']} runs): first sign, agent {pct(t['tool_first_sign']['agent'])}, step {pct(t['tool_first_sign']['step'])}; "
                     f"first harmful record, agent {pct(t['tool_first_harm']['agent'])}, step {pct(t['tool_first_harm']['step'])}.")
        L.append("")
    f = res["false_alarms_all"]
    L += ["## False alarms on benign runs", "",
          f"A default rule fired in {pct(f['auto_pack'])} of runs with the pack the tool picks by itself, and in {pct(f['generic_pack'])} with the general pack.", "",
          "| Layout | Clock | Pack picked | Watch (first harmful sign) | Alert (2 kinds of coordination) | Volume baseline |", "|---|---|---|---|---|---|"]
    for g, v in res["groups"].items():
        t = v["false_alarms"]["auto_pack"]
        by = {r["id"]: r for r in t["rows"]}
        cell = lambda k: f"{by[k]['runs_fired']} of {by[k]['runs']} ({(by[k]['share'] or 0) * 100:.1f}%, {by[k]['ci95'][0] * 100:.1f} to {by[k]['ci95'][1] * 100:.1f}%)" if by[k]["runs"] else "–"
        L.append(f"| {g} | {t['clock']} | {', '.join(f'{k} ({n})' for k, n in sorted(t['packs'].items()))} | {cell('watch-harm')} | {cell('alert-coord2')} | {cell('baseline-volume')} |")
    L += ["", "The Alert rule fires on almost any team that talks: it detects information flow, not malice. The hourly baselines need 6 to "
          "12 hours of history and these runs are shorter, so their zeros say nothing. On the step clock a rate per 24 h has no meaning and none is given.", ""]
    if "labels_vs_alarms" in res:
        v = res["labels_vs_alarms"]
        L += ["## Do the rules track task failure?", "",
              f"{v['runs_with_a_failure_mode']:,} runs carry at least one failure mode, {v['runs_with_none']:,} carry none "
              f"({v['runs_without_full_labels']} lack some labels).", ""]
        for k, r in v["rules"].items():
            L.append(f"- `{k}`: fired on {pct(r['fired_on_failed'])} of failed runs and {pct(r['fired_on_clean'])} of clean runs.")
        L += ["", "The pooled gap on the Watch rule is mostly the mix of frameworks: the layouts differ both in how often they fail and in how "
              "often the rule fires. Inside one layout (failed against clean):", ""]
        short = lambda r: f"{r['k']} of {r['n']}" + (f" ({r['share'] * 100:.0f}%)" if r["n"] else "")
        for mas, r in v["watch_by_layout"].items():
            L.append(f"- {mas}: {short(r['fired_on_failed'])} against {short(r['fired_on_clean'])}")
        L += ["", "Most layouts have few clean runs, so these inside-layout gaps are not established either way. The rules were written for "
              "attacks; nothing here says they should separate failed runs from clean ones.", ""]
    L += ["## What this does not show", "",
          "- Accuracy on a swarm, on an attack, or on contact through shared places. These are turn-taking teams; the tool's deliveries here rest on "
          "who posted after whom in one conversation.",
          "- Anything about timing on the step clock, which is order only.",
          "- That the labels are right. " + ("The 14 labels come from an LLM judge." if name == "mast_data" else
                                           "In a few runs the labelled step was not spoken by the labelled agent (see `results.json`)."), "",
          f"Credit: {res['attribution']}", ""]
    return "\n".join(L)


def write(name, res, per_run, out=None):
    d = out or os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(d, "runs.json"), "w", encoding="utf-8") as f:
        json.dump(per_run, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    with open(os.path.join(d, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_md(res))
    return d


def saved(name, out=None):
    """The saved results of a dataset, or None when it has not been measured here."""
    p = os.path.join(out or os.path.join(OUT, name), "results.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ the rows the gallery stories cite

# slug -> (dataset, the rows a local read-only server loads so that the gallery's builder can show the cited records)
STORY_DATA = {"who-failed-and-when": ("who_and_when", lambda: [x for r in RF.load_who_and_when(os.path.join(DATA, "who_and_when"))
                                                              if r["subset"] == "Hand-Crafted" for x in r["rows"]]),
              "seven-frameworks-no-attack": ("mast_data", lambda: [x for r in RF.load_mast(os.path.join(DATA, "mast_data", "MAD_full_dataset.json"))
                                                                    if r["mas"] in ("AppWorld", "HyperAgent") for x in r["rows"]])}


def build_story(slug, out=None, log=print):
    """Build one of the two stories into a temp folder, as a check that it builds. The gallery's builder does the
    work (agenttrace/tools/build_investigations.py, which also builds the published pages): figures from
    reports/external/<name>/results.json, records from the rows above with short excerpts (both licences allow
    them, with the registry's credit line)."""
    from .tools import build_investigations as B
    if slug not in STORY_DATA:
        raise SystemExit(f"{slug}: not one of {', '.join(sorted(STORY_DATA))}")
    return B.build_one(slug, out, log)


# ------------------------------------------------------------------ checks the tests run in a `python3 -I` child

def reader_counts(name):
    """What the reader alone gives on the downloaded files: no part of the analysis is involved."""
    if name == "who_and_when":
        from . import model
        root = os.path.join(DATA, "who_and_when")
        runs = RF.load_who_and_when(root)
        raw = model.load(os.path.join(root, "Hand-Crafted", "1.json"))
        return {"runs": len(runs), "records": sum(len(r["rows"]) for r in runs),
                "addressed": sum(len(RF.logged_messages(r["rows"])) for r in runs),
                "actors": len({x["actor"] for r in runs for x in r["rows"] if x["actor"]}),
                "timed": sum(1 for r in runs for x in r["rows"] if x["time"]),
                "label_step_is_by_label_agent": sum(1 for r in runs if r["truth"]["step_actor"] == r["truth"]["mistake_agent"]),
                "by_subset": {sub: [sum(1 for r in runs if r["subset"] == sub), sum(len(r["rows"]) for r in runs if r["subset"] == sub)]
                              for sub in ("Algorithm-Generated", "Hand-Crafted")},
                "hc1_label": [runs_by["truth"]["mistake_agent"], runs_by["truth"]["mistake_step"]]
                if (runs_by := next((r for r in runs if r["run"] == "hc1"), None)) else None,
                "raw_file": {"format": model.LAST_REPORT.get("format"), "records": len(raw),
                             "actors": sorted({e.actor for e in raw if e.actor}), "addressed": sum(1 for e in raw if e.to)}}
    from . import model
    runs = RF.load_mast(os.path.join(DATA, "mast_data", "MAD_full_dataset.json"))
    by = defaultdict(list)
    for r in runs:
        by[r["mas"]].append(r)
    small = model.load(os.path.join(DATA, "mast_data", "MAD_human_labelled_dataset.json"))   # the 19-run file, through the loader
    return {"human_file": {"format": model.LAST_REPORT.get("format"), "records": len(small),
                           "runs": len({e.channel for e in small}), "addressed": sum(1 for e in small if e.to)},
            "runs_in_file": len(runs), "runs": sum(1 for r in runs if r["rows"]), "records": sum(len(r["rows"]) for r in runs),
            "addressed": sum(len(RF.logged_messages(r["rows"])) for r in runs),
            "timed": sum(1 for r in runs for x in r["rows"] if x["time"]),
            "actors": len({x["actor"] for r in runs for x in r["rows"] if x["actor"]}),
            "left_out": sum(r["skipped"] for r in runs),
            "failed": sum(1 for r in runs if r["rows"] and any(v == 1 for v in r["labels"].values())),
            "by_layout": {m: [sum(1 for r in p if r["rows"]), sum(len(r["rows"]) for r in p),
                              sum(len(RF.logged_messages(r["rows"])) for r in p)] for m, p in sorted(by.items())}}


def recheck(name):
    """The saved results' main numbers, computed again now (all of Who&When; two small layouts of MAST-Data)."""
    quiet = lambda *a, **k: None
    if name == "who_and_when":
        res, _ = eval_who_and_when(log=quiet)
        return {"tool_files": res["tool_files"], "groups": res["groups"], "attribution_all": {k: v for k, v in res["attribution_all"].items() if k != "published_for_scale"},
                "false_alarms_all": res["false_alarms_all"]}
    runs = RF.load_mast(os.path.join(DATA, "mast_data", "MAD_full_dataset.json"))
    out = {"tool_files": tool_state(), "groups": {}}
    for mas in ("AppWorld", "HyperAgent"):
        out["groups"][mas] = evaluate_group([r for r in runs if r["mas"] == mas], addressed=True, real_clock=False, log=quiet)[0]
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("who_and_when", "mast_data", "story", "counts", "recheck"):
        print(__doc__)
        return 2
    os.environ.setdefault("SWARM_TRACER_NO_CACHE", "1")
    if argv[0] == "story":
        build_story(argv[1], argv[2] if len(argv) > 2 else None)
        return 0
    if argv[0] in ("counts", "recheck"):
        json.dump((reader_counts if argv[0] == "counts" else recheck)(argv[1]), sys.stdout)
        return 0
    name = argv[0]
    root = os.path.join(DATA, SOURCES[name]["dir"])
    if not os.path.isdir(root):
        print(f"{root} is not here: download the dataset first (docs/dataset-licensing.md)", file=sys.stderr)
        return 1
    res, per_run = eval_who_and_when() if name == "who_and_when" else eval_mast()
    d = write(name, res, per_run)
    print(f"wrote {d}/results.json, runs.json, summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

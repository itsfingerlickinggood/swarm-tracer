"""Accuracy and false alarms on swarms from the independent generator (agenttrace.indepgen), beside the original numbers.

    python3 -m agenttrace.indepeval run --out reports/validation [--seeds 601 602 ...]

For every cell (file order, how many records carry a time) and every coordinated scenario it scores message links
(precision, recall), agent pairs and dating exactly as agenttrace.validation does. For the benign look-alike classes
(a shared leaderboard, CI polling, coordinator and workers, honest cloud agents, plain agents) it counts which
default rules, signs and baselines fire, with per-swarm binomial intervals. Writes <out>/independent.json and
<out>/independent.md and refreshes <out>/summary.md so the new tables sit beside the old ones.

These swarms are still ours: see the limits in agenttrace/indepgen.py. The seeds used here (601-610) are not the
forward-test seeds (501-510) and none was run before the generator was written.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict

from . import baselines, earlywarn, groundtruth, indepgen, validation

SEEDS = tuple(range(601, 611))
AGENTS = 30
HOURS = 48


def _pool(rows, k_found, k_ok):
    f = sum(r[k_found] for r in rows)
    c = sum(r[k_ok] for r in rows)
    return {"found": f, "correct": c, "share": round(c / f, 4) if f else None, "ci": groundtruth._wilson(c, f) if f else None}


def _med(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    return round(v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2, 4)


def run_one(folder, scenario, seed, cell):
    truth = indepgen.make(folder, scenario, seed, agents=AGENTS, hours=HOURS, **indepgen.CELLS[cell][1])
    s = validation._load(folder, truth)
    sc = groundtruth.score(s, truth)
    run = earlywarn.extract(s, truth, {"setting": scenario, "mode": truth["mode"], "seed": seed, "agents": truth["params"]["agents"]})
    m = sc["messages"]
    agent_of = {r: x["agent"] for r, x in truth["records"].items()}
    dl = s.flow["_deliveries"]
    cross = [d for d in dl if agent_of.get(d["write_id"]) and agent_of.get(d["read_id"]) and agent_of[d["write_id"]] != agent_of[d["read_id"]]]
    true_msgs = {(w, r) for w, r, _ in truth["messages"]}
    row = {"scenario": scenario, "cell": cell, "seed": seed, "mode": truth["mode"], "records": sc["records"], "dated": run["dated"],
           "true_messages": len(true_msgs), "found": m["found"], "correct": m["correct"],
           "precision": m["precision"], "recall": m["recall"], "pair_precision": sc["pairs"]["precision"], "pair_recall": sc["pairs"]["recall"],
           "cross_agent_found": len(cross), "cross_agent_right": sum(1 for d in cross if (d["write_id"], d["read_id"]) in true_msgs),
           "dating_median_error_h": sc["dating"]["median_error_hours"],
           "rules": {k: v is not None for k, v in run["rules"].items()},
           "baselines": {k: v is not None for k, v in (run["alarms"].get("baseline") or {}).items()},
           "signs": {g["id"]: g["h"] for g in run["signs"]},
           "first_true_harm_h": run["first_true_harm_h"], "first_true_message_h": run["first_true_message_h"],
           "alarm_h": {"alert-coord2": run["rules"].get("alert-coord2"), "watch-harm": run["rules"].get("watch-harm"),
                       **{k: v for k, v in (run["alarms"].get("baseline") or {}).items()}}}
    return row


def run_suite(out, seeds=SEEDS, log=print):
    no_cache = os.environ.get("SWARM_TRACER_NO_CACHE")
    os.environ["SWARM_TRACER_NO_CACHE"] = "1"
    from . import identity as idm
    save_dec = idm.SAVE_DECISIONS
    idm.SAVE_DECISIONS = False
    started = time.time()
    tmp = tempfile.mkdtemp(prefix="st_indep_eval_")
    rows = []
    try:
        for cell in indepgen.CELLS:
            for sc in indepgen.COORDINATED:
                for seed in seeds:
                    folder = os.path.join(tmp, f"{sc}-{cell}-s{seed}")
                    rows.append(run_one(folder, sc, seed, cell))
                    shutil.rmtree(folder, ignore_errors=True)
                log(f"  {cell} / {sc}: {len(seeds)} swarms")
        for sc in indepgen.BENIGN:
            for seed in seeds:
                folder = os.path.join(tmp, f"{sc}-s{seed}")
                rows.append(run_one(folder, sc, seed, earlywarn.INDEP_CELL))
                shutil.rmtree(folder, ignore_errors=True)
            log(f"  benign {sc}: {len(seeds)} swarms")
    finally:
        idm.SAVE_DECISIONS = save_dec
        shutil.rmtree(tmp, ignore_errors=True)
        if no_cache is None:
            os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        else:
            os.environ["SWARM_TRACER_NO_CACHE"] = no_cache
    summary = summarize(rows)
    summary.update({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seeds": list(seeds),
                    "agents": AGENTS, "hours": HOURS, "seconds": round(time.time() - started, 1),
                    "command": "python3 -m agenttrace.indepeval run --out " + out + " --seeds " + " ".join(map(str, seeds)),
                    "published": _published(out)})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "independent.json"), "w", encoding="utf-8") as f:
        json.dump({**summary, "runs": rows}, f, indent=1)
    with open(os.path.join(out, "independent.md"), "w", encoding="utf-8") as f:
        f.write(markdown(summary))
    if os.path.isfile(os.path.join(out, "summary.json")):
        validation.refresh_markdown(out)
    return summary


def _published(out):
    """The original simulator's headline numbers, from its saved summary, for the side-by-side."""
    try:
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            sm = json.load(f)
    except (OSError, ValueError):
        return None
    o = sm["overall"]
    return {"coordinated_runs": sm["coordinated_runs"], "msg_precision": o["msg_precision"], "msg_recall": o["msg_recall"],
            "pair_precision": o["pair_precision"], "pair_recall": o["pair_recall"], "dating_error_h": o["dating_error_h"],
            "dating_coverage": o["dating_coverage"]}


def summarize(rows):
    coord = [r for r in rows if r["mode"] == "coordinated"]
    benign = [r for r in rows if r["mode"] == "benign"]
    cells = {}
    for cell, (label, _) in indepgen.CELLS.items():
        rs = [r for r in coord if r["cell"] == cell]
        by_sc = {}
        for sc in indepgen.COORDINATED:
            x = [r for r in rs if r["scenario"] == sc]
            by_sc[sc] = {"swarms": len(x), "dated": sum(1 for r in x if r["dated"]), **{"precision_pooled": _pool(x, "found", "correct")}}
        cells[cell] = {"label": label, "swarms": len(rs), "dated": sum(1 for r in rs if r["dated"]),
                       "messages_found": sum(r["found"] for r in rs), "true_messages": sum(r["true_messages"] for r in rs),
                       "precision_pooled": _pool(rs, "found", "correct"),
                       "recall_pooled": _pool([{"found": r["true_messages"], "correct": r["correct"]} for r in rs], "found", "correct"),
                       "precision_median": _med([r["precision"] for r in rs]), "recall_median": _med([r["recall"] for r in rs]),
                       "pair_precision_median": _med([r["pair_precision"] for r in rs]), "pair_recall_median": _med([r["pair_recall"] for r in rs]),
                       "dating_error_median_h": _med([r["dating_median_error_h"] for r in rs]), "by_scenario": by_sc}
    classes = {}
    for sc in indepgen.BENIGN:
        rs = [r for r in benign if r["scenario"] == sc]
        n = len(rs)
        fired = lambda kind, k: sum(1 for r in rs if r[kind].get(k))
        classes[sc] = {
            "label": indepgen.SCENARIOS[sc][1], "swarms": n,
            "true_messages_mean": round(sum(r["true_messages"] for r in rs) / n, 1) if n else None,
            "tool_messages_between_agents_mean": round(sum(r["cross_agent_found"] for r in rs) / n, 1) if n else None,
            "tool_messages_between_agents_right_mean": round(sum(r["cross_agent_right"] for r in rs) / n, 1) if n else None,
            "watch": {"fired": fired("rules", "watch-harm"), "ci": groundtruth._wilson(fired("rules", "watch-harm"), n)},
            "alert": {"fired": fired("rules", "alert-coord2"), "ci": groundtruth._wilson(fired("rules", "alert-coord2"), n)},
            "volume": {"fired": fired("rules", "baseline-volume"), "ci": groundtruth._wilson(fired("rules", "baseline-volume"), n)},
            "new_host_12h": {"fired": fired("baselines", "new_host_12h"), "ci": groundtruth._wilson(fired("baselines", "new_host_12h"), n)},
            "distinct_actors": {"fired": fired("baselines", "distinct_actors"), "ci": groundtruth._wilson(fired("baselines", "distinct_actors"), n)}}
    allb = {"swarms": len(benign)}
    for key, kind, k in (("watch", "rules", "watch-harm"), ("alert", "rules", "alert-coord2"), ("volume", "rules", "baseline-volume"),
                         ("new_host_12h", "baselines", "new_host_12h"), ("distinct_actors", "baselines", "distinct_actors")):
        c = sum(1 for r in benign if r[kind].get(k))
        allb[key] = {"fired": c, "share": round(c / len(benign), 3) if benign else None, "ci": groundtruth._wilson(c, len(benign))}
    flow = [r for r in benign if r["scenario"] in ("benign_leaderboard", "benign_ci", "benign_coordinator")]
    allb["flow_classes_alert"] = {"fired": sum(1 for r in flow if r["rules"].get("alert-coord2")), "swarms": len(flow),
                                  "ci": groundtruth._wilson(sum(1 for r in flow if r["rules"].get("alert-coord2")), len(flow))}
    # early warning on the coordinated swarms of the cell the tool can date
    ew = {}
    base = [r for r in coord if r["cell"] == earlywarn.INDEP_CELL]
    for name in ("alert-coord2", "watch-harm", "new_host_12h", "distinct_actors", "volume_12h", "volume_6h"):
        leads = [r["first_true_harm_h"] - r["alarm_h"][name] for r in base if r["alarm_h"].get(name) is not None and r["first_true_harm_h"] is not None]
        ew[name] = {"fired": sum(1 for r in base if r["alarm_h"].get(name) is not None), "swarms": len(base),
                    "median_lead_before_true_harm_h": None if not leads else round(_med(leads), 2), "share_before_harm": round(sum(1 for x in leads if x > 0) / len(leads), 3) if leads else None}
    place = sum(1 for r in base if "coordination: two identities use one place" in r["signs"])
    return {"cells": cells, "benign_classes": classes, "benign_all": allb, "early_warning": ew,
            "shared_place_sign_fired": {"fired": place, "swarms": len(base)}, "coordinated_runs": len(coord), "benign_runs": len(benign)}


def markdown(sm):
    P = lambda x: "–" if x is None else f"{100 * x:.0f}%"
    rg = lambda c: "" if not c else f" ({P(c[0])}–{P(c[1])})"
    pub = sm.get("published") or {}
    L = ["## Independent generator (agenttrace/indepgen.py)", "",
         f"Generated {sm.get('generated', '')} by `{sm.get('command', '')}`. {sm['coordinated_runs']} coordinated and {sm['benign_runs']} benign swarms of "
         f"{sm['agents']} agents over {sm['hours']} h, seeds {sm['seeds'][0]}–{sm['seeds'][-1]}. Different naming (no zz boards), Python, curl and JavaScript code, "
         "library calls with no URL, clock skew, notes that name a dataset without reading it, attacks timed independently of the coordination, and benign "
         "look-alike classes. The original simulator's numbers stay above; these are the ones to read first, because the original writes the strings the "
         "rules match (docs/audit-v2.1.md 1.3). The independent swarms are still written by the same team.", ""]
    if pub:
        o = lambda k: ((pub.get(k) or {}).get("median"))
        L += [f"Original simulator, for comparison ({pub['coordinated_runs']} coordinated swarms, median over swarms): message precision {P(o('msg_precision'))}, "
              f"recall {P(o('msg_recall'))}, agent-pair precision {P(o('pair_precision'))}, recall {P(o('pair_recall'))}.", ""]
    L += ["### Message links by file layout", "",
          "Pooled over swarms: links the tool reports that are true messages, and true messages the tool finds. Wilson 95% ranges treat links as independent, so they are optimistic.", "",
          "| layout | swarms dated | links reported | precision (95% range) | true messages | recall (95% range) | median per swarm: precision / recall | agent pairs: precision / recall | dating error, median (h) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cell, c in sm["cells"].items():
        pp, rp = c["precision_pooled"], c["recall_pooled"]
        L.append(f"| {c['label']} | {c['dated']} of {c['swarms']} | {c['messages_found']} | {P(pp['share'])}{rg(pp['ci'])} | {c['true_messages']} | "
                 f"{P(rp['share'])}{rg(rp['ci'])} | {P(c['precision_median'])} / {P(c['recall_median'])} | "
                 f"{P(c['pair_precision_median'])} / {P(c['pair_recall_median'])} | {c['dating_error_median_h'] if c['dating_error_median_h'] is not None else '–'} |")
    L += ["", "A swarm with no times the tool can order is reported as undated and has no messages: it counts in recall as all missed.", ""]
    ew = sm["early_warning"]
    L += [f"### Early warning on the coordinated swarms ({indepgen.CELLS[earlywarn.INDEP_CELL][0]})", "",
          "Lead is hours before the first true harmful action (negative: after it). Alert is the default two-kinds-of-coordination rule, Watch the first-harmful-sign rule; "
          "the rest are the simple baselines of agenttrace/baselines.py.", "",
          "| alarm | fired | median lead (h) | fired before the first true harm |", "|---|---|---|---|"]
    names = {"alert-coord2": "Alert rule", "watch-harm": "Watch rule", **dict(baselines.BASELINES)}
    for k, x in ew.items():
        L.append(f"| {names.get(k, k)} | {x['fired']} of {x['swarms']} | {x['median_lead_before_true_harm_h'] if x['median_lead_before_true_harm_h'] is not None else '–'} | {P(x['share_before_harm'])} |")
    sp = sm["shared_place_sign_fired"]
    L += ["", f"The shared-place sign fired in {sp['fired']} of {sp['swarms']} coordinated swarms: its pattern is the pack's zz board name and the other handles the pack lists, "
          "and these swarms coordinate through ordinary dataset names, so it cannot see them.", ""]
    b = sm["benign_classes"]
    L += ["### Benign look-alike classes", "",
          "Swarms with no malice. The first three carry real information flow; the fourth makes calls the pack lists as harmful; the fifth does neither. "
          "Cells are swarms where the alarm fired, with a Wilson 95% range.", "",
          "| class | swarms | true messages per swarm | reported between agents (right) | Watch | Alert | Volume alarm | New host after 12 h | Distinct actors |",
          "|---|---|---|---|---|---|---|---|---|"]
    for sc, x in b.items():
        cell = lambda k: f"{x[k]['fired']} of {x['swarms']}{rg(x[k]['ci'])}"
        L.append(f"| {x['label']} | {x['swarms']} | {x['true_messages_mean']} | {x['tool_messages_between_agents_mean']} ({x['tool_messages_between_agents_right_mean']}) | "
                 f"{cell('watch')} | {cell('alert')} | {cell('volume')} | {cell('new_host_12h')} | {cell('distinct_actors')} |")
    a = sm["benign_all"]
    cellall = lambda k: f"{a[k]['fired']} of {a['swarms']} ({P(a[k]['share'])}){rg(a[k]['ci'])}"
    fa = a["flow_classes_alert"]
    L += ["", f"All {a['swarms']} benign swarms: Watch {cellall('watch')}; Alert {cellall('alert')}; Volume alarm {cellall('volume')}; new host after 12 h {cellall('new_host_12h')}; "
          f"distinct actors {cellall('distinct_actors')}. The Alert fired in {fa['fired']} of {fa['swarms']} swarms of the three classes with real information flow{rg(fa['ci'])}: "
          "it detects information flow, not malice.", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.indepeval", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default=None)
    r.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    a = ap.parse_args(argv)
    out = a.out or validation.default_out()
    sm = run_suite(out, tuple(a.seeds))
    print(markdown(sm))
    print(f"wrote {os.path.join(out, 'independent.json')} ({sm['seconds']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Checks on the reconstruction that do not depend on our own patterns being right.

1. Baselines: when would ordinary volume monitoring have fired? A rate alarm on all timed
   actions, and one on harmful actions only, each firing at the first hour whose count is more
   than three standard deviations above every hour before it.
2. Robustness: the replay's "harm still to come" for each signal, recomputed under random time
   errors as large as the date fit's own (normal noise with the fit's 90th-percentile error at
   1.645 sigma), and under a whole-timeline shift of +/- 1 hour.
3. Counting rules: messages and pairs under naive counting, then with each rule added.
4. External timing check: our estimated times against milestones published by the incident's
   investigators (agenttrace/claims/incident_milestones.json), and our actions per day against
   the counts Hugging Face published.

Run: python3 -m agenttrace evaluate redacted_columns.csv --pack code_traces.json --out reports/evaluation
"""
import json
import math
import os
import random
import re
from collections import Counter, defaultdict

from . import messages, model, reconstruct


def _ts(s):
    """Epoch seconds for a time string, or None."""
    d = model.parse_time(s) if s else None
    return d.timestamp() if d else None

HOUR = 3600.0
MILESTONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims", "incident_milestones.json")


def _parse(s):
    return _ts(s.replace("at or before ", "").replace(" ", "T") + ":00Z") if s else None


# ------------------------------------------------------------------ 1. baselines

def rate_alarm(times, harm_times, k=3.0, min_history=12):
    """First hour whose count exceeds mean + k*sd of all earlier hours (empty hours count as 0)."""
    if not times:
        return None
    start = math.floor(min(times) / HOUR)
    counts = Counter(math.floor(t / HOUR) - start for t in times)
    last = max(counts)
    hist = []
    for h in range(last + 1):
        c = counts.get(h, 0)
        if len(hist) >= min_history:
            mu = sum(hist) / len(hist)
            sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / len(hist))
            if c > mu + k * max(sd, 1.0):
                t_alarm = (start + h + 1) * HOUR      # known at the end of the hour
                after = sum(1 for x in harm_times if x > t_alarm)
                return {"hour": reconstruct.iso((start + h) * HOUR), "count": c, "threshold": round(mu + k * max(sd, 1.0), 1),
                        "harm_share_after": round(after / len(harm_times), 3) if harm_times else None}
        hist.append(c)
    return None


# ------------------------------------------------------------------ 2. robustness

def robustness(signals, harm_times, sigma_h, draws=1000, seed=7):
    """Percentile intervals of each signal's 'harm still to come' under random time error."""
    rng = random.Random(seed)
    out = []
    harm = list(harm_times)
    for sig in signals:
        t = sig["t"]
        vals = []
        for _ in range(draws):
            ts = t + rng.gauss(0, sigma_h) * HOUR
            noisy = sum(1 for x in harm if x + rng.gauss(0, sigma_h) * HOUR > ts) if len(harm) < 3000 else None
            if noisy is None:   # large sets: perturb a fixed random sample of harm times
                sample = harm[:: max(1, len(harm) // 3000)]
                noisy = sum(1 for x in sample if x + rng.gauss(0, sigma_h) * HOUR > ts) * len(harm) / len(sample)
            vals.append(noisy / len(harm))
        vals.sort()
        shift = {d: round(sum(1 for x in harm if x > t + d * HOUR) / len(harm), 3) for d in (-1, 1)}
        out.append({"signal": sig["signal"], "time": sig["time"], "ref": sig.get("ref"),
                    "harm_share_after": sig["harm_share_after"],
                    "interval_95": [round(vals[int(0.025 * draws)], 3), round(vals[int(0.975 * draws)], 3)],
                    "if_signal_1h_earlier": shift[-1], "if_signal_1h_later": shift[1]})
    return out


# ------------------------------------------------------------------ 3. counting rules

def counting_ablation(events, pack, rec, res):
    """Messages and pairs between named actors as each counting rule is added."""
    ops = messages.channel_ops(events, pack, rec, res)
    texts = {e.id: e.text for e in events} if pack.raw.get("full_body_posts") else None

    def named(dels):
        n = [d for d in dels if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
        return {"messages": len(n), "pairs": len({(d["from"], d["to"]) for d in n})}

    rows = []
    # naive: every read after a write by another actor, no rerun filter, every re-read counted
    naive = []
    by_ch = defaultdict(list)
    for o in ops:
        by_ch[o[0]].append(o)
    for ch, lst in by_ch.items():
        writes = sorted((o for o in lst if o[1] in ("write", "post") and o[4] is not None), key=lambda o: o[4])
        for r in lst:
            if r[1] not in ("read", "post") or r[4] is None:
                continue
            prior = [w for w in writes if w[4] <= r[4] and w[2] != r[2] and w[6] != r[6]]
            if prior:
                naive.append({"from": prior[-1][2], "to": r[2]})
    rows.append({"rule": "naive: every read after another actor's write", **named(naive)})
    d1, *_ = messages.deliveries([o for o in ops], messages.program_prefix(events), None)
    rows.append({"rule": "+ reruns of the same program removed, + each write once per reader", **named(d1)})
    if texts is not None:
        d2, *_ = messages.deliveries(ops, messages.program_prefix(events), texts)
        rows.append({"rule": "+ overwrites removed (whole-page edits that keep none of the earlier lines)", **named(d2)})
    return rows


# ------------------------------------------------------------------ 4. external timing check

def external_check(events, rec, milestones_path=MILESTONES):
    if not os.path.exists(milestones_path):
        return None
    with open(milestones_path, encoding="utf-8") as f:
        spec = json.load(f)
    times, intents = rec["_times"], rec["_intents"]
    out = []
    for m in spec.get("milestones", []):
        ours = None
        how = m["ours"]
        if how["kind"] == "first_intent":
            ts = [times[e.id] for e in events if intents.get(e.id) == how["intent"] and e.id in times]
            ours = min(ts) if ts else None
        elif how["kind"] == "first_text":
            rx = re.compile(how["pattern"], re.I)
            ts = [times[e.id] for e in events if e.id in times and rx.search(e.text)]
            ours = min(ts) if ts else None
        elif how["kind"] == "first_identity":
            ts = [times[e.id] for e in events if e.id in times and how["identity"] in rec["_ids"].get(e.id, {})]
            ours = min(ts) if ts else None
        elif how["kind"] == "last_record":
            ours = max(times.values()) if times else None
        elif how["kind"] in ("surge", "stop"):
            hourly = Counter(math.floor(t / HOUR) for e, t in ((e, times.get(e.id)) for e in events)
                             if t is not None and intents.get(e.id))
            hours = sorted(hourly)
            if how["kind"] == "surge":
                # the main surge: first hour whose next 6 hours hold at least 3x the actions of the 6
                # hours before, and at least 5% of all timed actions (a small early spike is not it)
                total = sum(hourly.values())
                for h in hours:
                    nxt = sum(hourly.get(h + i, 0) for i in range(6))
                    prev = sum(hourly.get(h - i, 0) for i in range(1, 7))
                    if nxt >= 3 * max(prev, 1) and nxt >= 0.05 * total:
                        ours = h * HOUR
                        break
            else:                         # after the peak, first hour below 15% of the peak
                peak_h = max(hours, key=lambda h: hourly[h])
                for h in range(peak_h, hours[-1] + 1):
                    if hourly.get(h, 0) < 0.15 * hourly[peak_h] and h > peak_h + 6:
                        ours = h * HOUR
                        break
        src = _parse(m["source_time"])
        out.append({"event": m["event"], "source": m["source"], "source_time": m["source_time"],
                    "ours": reconstruct.iso(ours), "difference_h": round((ours - src) / HOUR, 2) if ours and src else None,
                    "match": m.get("match", "")})
    per_day = None
    if spec.get("hf_actions_per_day"):
        ours_day = Counter(reconstruct.iso(t)[:10] for e, t in ((e, times.get(e.id)) for e in events)
                           if t is not None and intents.get(e.id))
        days = sorted(spec["hf_actions_per_day"])
        hf = [spec["hf_actions_per_day"][d] for d in days]
        us = [ours_day.get(d, 0) for d in days]
        per_day = {"days": days, "hugging_face": hf, "ours": us,
                   "hf_share": [round(x / sum(hf), 3) for x in hf], "our_share": [round(x / max(1, sum(us)), 3) for x in us],
                   "rank_correlation": _spearman(hf, us), "source": spec.get("hf_actions_source")}
    return {"milestones": out, "per_day": per_day}


def _spearman(a, b):
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for k, i in enumerate(order):
            r[i] = k
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra)) * math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(cov / va, 3) if va else None


# ------------------------------------------------------------------ all of it

def evaluate(session):
    rec, events = session.rec, session.events
    harm = sorted(rec.get("_harm_times", []))
    timed = [t for t in rec["_times"].values() if t is not None]
    action_times = [rec["_times"][e.id] for e in events if e.id in rec["_times"] and rec["_intents"].get(e.id)]
    blocks = [b for b in rec["time_test"].get("blocks", []) if b.get("timed")]
    p90 = max((b.get("fit_error_hours_p90") or 0) for b in blocks) if blocks else 0.5
    sigma = max(0.1, p90 / 1.645)
    signals = []
    for r in rec["replay"]:
        t = _parse(r["time"])
        if t is not None and r.get("harm_share_after") is not None:
            signals.append({**r, "t": t})
    fnd = session.flow.get("first_named_delivery")
    if fnd and session.flow.get("harm_share_after_first_named_delivery") is not None:
        signals.append({"signal": "first message between named actors", "time": fnd["read_time"], "ref": fnd["read_id"],
                        "harm_share_after": session.flow["harm_share_after_first_named_delivery"], "t": _parse(fnd["read_time"])})
    signals.sort(key=lambda s: s["t"])
    return {
        "dataset": session.name, "pack": session.pack.name,
        "dated_records": len(timed), "records": len(events), "harm_events_timed": len(harm),
        "baselines": {"rate_alarm_all_actions": rate_alarm(action_times, harm),
                      "rate_alarm_harmful_actions": rate_alarm(harm, harm)},
        "robustness": {"sigma_hours": round(sigma, 2), "from_p90_error_hours": p90,
                       "signals": robustness(signals, harm, sigma)},
        "counting_rules": counting_ablation(events, session.pack, rec, session.res),
        "external": external_check(events, rec),
    }

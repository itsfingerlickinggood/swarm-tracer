"""Gap sensitivity, comparison with the insiders' findings, what to collect next time.

Routes (served at /api/x/<name>, see extensions.py):
    GET sensitivity            every gap re-run at a best and a worst case: the range of each headline answer
    GET sensitivity_gap?key=   one gap (time, identity, merged, channel, success, reasoning) with its scenarios
    GET insiders               the insiders' published findings, each marked recovered / partly / invisible
    GET collect_next           what to log next time, in priority order, with the size of the effect

Method. The tool's headline answers are recounted from the same records under changed assumptions, with the
same counting code (agenttrace.messages.deliveries, agenttrace.fx_whatif for joint warning signs,
agenttrace.evaluate.rate_alarm for the volume alarm). Nothing here changes the analysis itself.

  time      dating errors (a fresh random shift per estimated time, spread taken from the fit errors, several
            draws), and records with no time placed at the earliest or the latest time their neighbours allow.
  identity  tokens as they are, then agents formed by joining high-confidence pairs, high and medium pairs,
            and every proposed pair (agenttrace.identity).
  merged    places the redaction may have merged counted as messages, as counted, or dropped.
  channel   PARAMETRIC. Messages sent through places the release does not show. A share v of the traffic is
            visible; the rest is scaled from the visible messages. v comes from the incident's published
            numbers when this release matches them, else it is a stated assumption.
  success   PARAMETRIC. A share p (0, 25, 50%) of reads is taken to have failed, drawn at random with a fixed seed.
  reasoning not testable: the records hold no model reasoning.

Each headline is reported as a range over the scenarios of one gap. Warning signs that rest on place, token or
program times (not on message times) keep their as-counted time in the time scenarios; each range says so.
"""
import datetime as dt
import json
import math
import os
import random
import re
import time as _time
from bisect import bisect_left
from collections import Counter, defaultdict

from . import evaluate, fx_whatif, identity, insight, messages, reconstruct

HERE = os.path.dirname(os.path.abspath(__file__))
INSIDERS = os.path.join(HERE, "claims", "insider_findings.json")
CONTEXT = os.path.join(HERE, "claims", "incident_context.json")
HOUR = 3600.0
DRAWS = 10                    # time-noise draws
SUCCESS_DRAWS = 40
SUCCESS_P = (0.0, 0.25, 0.5)
SEED = 7
# the incident's published numbers used for the missing-channel scenario (claims/incident_context.json)
BOARD_NAMESPACE_SHARE = 0.95    # OpenAI estimate: the main namespace holds at least 95% of Artifactory messaging (METR p.25)
BOARD_MESSAGES = 63000          # about 63,000 board messages (METR p.5, p.22-23, p.30-31)
ASSUMED_VISIBLE = (0.9, 0.5)    # stated assumptions when the release does not match the incident

# which rows of the What's missing tab each gap here answers
GAP_ROWS = {"time": ["time", "order"], "identity": ["identity", "actor", "shared"], "merged": ["merged"],
            "channel": ["unlisted", "never_read"], "success": ["success", "weak"], "reasoning": ["patterns"]}

GAPS = [
    ("time", "Records with no time (and dating error)", "time"),
    ("identity", "Tokens are not agents", "identity"),
    ("merged", "Places the redaction may have merged", "merged"),
    ("channel", "Messages through places outside the release", "channel"),
    ("success", "Whether a read worked", "success"),
    ("reasoning", "No reasoning in the records", "reasoning"),
]


# ------------------------------------------------------------------ a session seen with other deliveries

class _Pack:
    def __init__(self, pack, coarse):
        self._p = pack
        self.raw = {**pack.raw, "coarse_channels": coarse}

    def __getattr__(self, k):
        return getattr(self._p, k)


class _View:
    """The session with other deliveries and harm times, so the existing counting code can be reused."""

    def __init__(self, s, dels, harm, coarse=None):
        self._s = s
        self.flow = {**s.flow, "_deliveries": dels}
        self.harm_sorted = harm
        self.pack = _Pack(s.pack, s.pack.raw.get("coarse_channels", []) if coarse is None else coarse)

    def __getattr__(self, k):
        return getattr(self._s, k)


def _iso(t):
    return reconstruct.iso(t) if t is not None else None


# ------------------------------------------------------------------ inputs prepared once

def _prep(s):
    p = getattr(s, "_sens_prep", None)
    if p is not None:
        return p
    ev = s.res["_evidence"]
    harm_names = sorted(s.pack.harm)
    first_of = {name: [e.id for e in s.events if reconstruct.is_action(e, s.pack)
                       and (s.rec["_intents"].get(e.id) == name or name in ev[e.id])] for name in harm_names}
    acts = [e.id for e in s.events if s.rec["_intents"].get(e.id)]
    sigma_kind = {}
    blocks = [b for b in s.rec["time_test"].get("blocks", []) if b.get("timed") and b.get("fit_error_hours_p90") is not None]
    for b in blocks:
        sigma_kind[b["kind"]] = max(sigma_kind.get(b["kind"], 0.0), b["fit_error_hours_p90"] / 1.645)
    glob = max(sigma_kind.values()) if sigma_kind else 0.0
    # records with no time: the nearest dated record of the same kind before and after in file order
    times = s.rec["_times"]
    by_kind = defaultdict(list)
    for i, e in enumerate(s.events):
        if e.id in times:
            by_kind[e.kind].append((i, times[e.id]))
    keys = {k: [x[0] for x in v] for k, v in by_kind.items()}
    lo_all = min(times.values()) if times else None
    hi_all = max(times.values()) if times else None
    bounds = {}
    for i, e in enumerate(s.events):
        if e.id in times:
            continue
        v, kx = by_kind.get(e.kind), keys.get(e.kind)
        a = b = None
        if v:
            j = bisect_left(kx, i)
            a = v[j - 1][1] if j > 0 else None
            b = v[j][1] if j < len(v) else None
        c = [x for x in (a, b) if x is not None]
        if len(c) == 2:
            bounds[e.id] = (min(c), max(c))
        elif c:      # one neighbour only: from it to the end of the dated range on that side
            bounds[e.id] = (lo_all, c[0]) if a is None else (c[0], hi_all)
        else:
            bounds[e.id] = (lo_all, hi_all)
    s._sens_prep = p = {"first_of": first_of, "acts": acts, "sigma_kind": sigma_kind, "sigma_global": glob, "bounds": bounds,
                        "ops": [o for o in s.op_list if not o[0].startswith(messages.DIRECT_PREFIX + ":")],
                        "direct": [d for d in s.flow["_deliveries"] if d["channel"].startswith(messages.DIRECT_PREFIX + ":")],
                        "lo": lo_all, "hi": hi_all}
    return p


def _times_for(s, mode, rng=None):
    base = s.rec["_times"]
    p = _prep(s)
    if mode == "base":
        return base
    t = dict(base)
    if mode in ("earliest", "latest"):
        k = 0 if mode == "earliest" else 1
        for rid, b in p["bounds"].items():
            if b[k] is not None:
                t[rid] = b[k]
        return t
    # noise: only times estimated from text or inherited carry error; a recorded time does not
    sk, g = p["sigma_kind"], p["sigma_global"]
    for e in s.events:
        if e.time or e.id not in base:
            continue
        sig = sk.get(e.kind, g)
        if sig:
            t[e.id] = base[e.id] + rng.gauss(0, sig) * HOUR
    return t


# ------------------------------------------------------------------ headline answers for one scenario

def _named_deliveries(view, amap, coarse_mode):
    """(read_time, delivery, agent_from, agent_to, is_coarse) for messages between different named agents."""
    rx = [re.compile(x) for x in view.pack.raw.get("coarse_channels", [])]
    ag = lambda a: amap.get(a, a)
    out, self_talk = [], 0
    for d in view.flow["_deliveries"]:
        if not (insight.is_named(d["from"]) and insight.is_named(d["to"])):
            continue
        coarse = any(r.search(d["channel"]) for r in rx)
        if coarse and coarse_mode == "exclude":
            continue
        a, b = ag(d["from"]), ag(d["to"])
        if a == b:
            self_talk += 1
            continue
        out.append((d["read_time"], d, a, b, coarse and coarse_mode == "asis"))
    out.sort(key=lambda x: x[0])
    return out, self_talk


def _signs_from(s, view, p, times, ag, exact, harm_t, base_signals, harm_first=True):
    """key -> time of each warning sign the replay lists, under this scenario."""
    joint = fx_whatif.joint_after(view, ag, exact)
    out = {}
    for g in base_signals:
        k, slot = g["key"], fx_whatif._sign_slot(g)
        if slot is not None:
            x = joint.get(slot)
            out[k] = x[0] if x else None
        elif g["kind"] == "harm" and harm_first:
            name = k.split("first: ", 1)[-1]
            ts = [times[r] for r in p["first_of"].get(name, []) if r in times]
            out[k] = min(ts) if ts else None
        elif g["key"] in ("rate_all", "rate_harm"):
            pts = [times[r] for r in p["acts"] if r in times] if k == "rate_all" else harm_t
            b = evaluate.rate_alarm(pts, harm_t)
            out[k] = (evaluate._parse(b["hour"]) + HOUR) if b else None
        else:
            out[k] = g["t"]
    return out


def _share(harm_t, t):
    if not harm_t or t is None:
        return None
    import bisect
    return round((len(harm_t) - bisect.bisect_right(harm_t, t)) / len(harm_t), 3)


def _values(s, times, amap=None, coarse_mode="asis", ops_times=True, dels=None):
    """The headline answers for one scenario."""
    p = _prep(s)
    amap = amap or {}
    harm_t = sorted(times[r] for r in s.harmful if r in times)
    if dels is None:
        ops = [(o[0], o[1], o[2], o[3], times.get(o[6]), o[5], o[6]) for o in p["ops"]] if times is not s.rec["_times"] else p["ops"]
        dels, *_ = messages.deliveries(ops, s.prefix, None)
        dels = dels + [d for d in p["direct"] if d.get("write_time") is not None]
    view = _View(s, dels, harm_t, coarse=([] if coarse_mode == "include" else None))
    named, self_talk = _named_deliveries(view, amap, coarse_mode)
    exact = [(t, d, a, b) for t, d, a, b, c in named if not c]
    base_signals = insight.simulate(s)["signals"]
    ag = lambda a: amap.get(a, a)
    sg = _signs_from(s, view, p, times, ag, exact, harm_t, base_signals)
    return _pack_values(named, self_talk, exact, sg, harm_t, base_signals)


def _pack_values(named, self_talk, exact, sg, harm_t, base_signals):
    first = exact[0] if exact else None
    v = {"messages": len(named), "pairs": len({(a, b) for _, _, a, b, _ in named}), "inside_one_agent": self_talk,
         "first_message": first[0] if first else None,
         "first_message_share": _share(harm_t, first[0]) if first else None,
         "first_message_id": first[1]["read_id"] if first else None}
    for g in base_signals:
        t = sg.get(g["key"])
        v["time:" + g["key"]] = t
        v["share:" + g["key"]] = _share(harm_t, t)
    alarm = sg.get("rate_all")
    v["volume_alarm"] = alarm
    v["alarm_lead_h"] = round((alarm - first[0]) / HOUR, 1) if (alarm is not None and first) else None
    joint = [sg[g["key"]] for g in base_signals if g["family"] == "joint" and sg.get(g["key"]) is not None]
    v["first_joint"] = min(joint) if joint else None
    v["joint_lead_h"] = round((alarm - v["first_joint"]) / HOUR, 1) if (alarm is not None and joint) else None
    v["_named"] = named
    return v


# ------------------------------------------------------------------ the gaps

def _scn(sid, label, case, values, note=""):
    return {"id": sid, "label": label, "case": case, "values": {k: v for k, v in values.items() if not k.startswith("_")}, "note": note}


def _gap_time(s):
    p = _prep(s)
    out = []
    base = _values(s, s.rec["_times"])
    out.append(_scn("base", "As counted", "base", base))
    if not s.rec["_times"]:
        return out, "No record in this trace has a time, so nothing can be dated or perturbed."
    rng = random.Random(SEED)
    for i in range(DRAWS):
        out.append(_scn(f"noise{i + 1}", f"Dating error, draw {i + 1}", "draw", _values(s, _times_for(s, "noise", rng))))
    undated = len(p["bounds"])
    for mode, lab in (("earliest", "Records with no time placed at the earliest time their neighbours allow"),
                      ("latest", "Records with no time placed at the latest time their neighbours allow")):
        out.append(_scn(mode, lab, mode, _values(s, _times_for(s, mode)), f"{undated:,} records placed"))
    sig = ", ".join(f"{k} {v:.1f} h" for k, v in sorted(p["sigma_kind"].items())) or "none (times are recorded, not estimated)"
    return out, f"Spread of the dating error per kind of record, from the fit errors (90th percentile / 1.645): {sig}. {undated:,} records have no time."


def _identity_maps(s):
    base = identity._base(s)
    named = base["named"]
    scored = [x for x in base["scored"]]
    maps = {}
    levels = (("tokens", "Tokens as they are (no merging)", ()), ("high", "Agents from high-confidence pairs", ("high",)),
              ("medium", "Agents from high and medium pairs", ("high", "medium")),
              ("all", "Agents from every proposed pair", ("high", "medium", "low")))
    for key, lab, conf in levels:
        edges = [(x["a"], x["b"]) for x in scored if x["confidence"] in conf]
        comps = identity._components(named, edges)
        amap = {}
        for g in comps:
            g = sorted(g, key=lambda a: (-len(s.by_actor.get(a, [])), a))
            for a in g:
                amap[a] = g[0]
        maps[key] = (lab, amap, len({v for v in amap.values()}) if amap else len(named))
    return maps


def _gap_identity(s):
    maps = _identity_maps(s)
    out = []
    times = s.rec["_times"]
    for key, (lab, amap, agents) in maps.items():
        v = _values(s, times, amap=amap)
        v["agents"] = agents
        out.append(_scn(key, lab, "base" if key == "tokens" else key, v, f"{agents:,} agents from {len(identity._base(s)['named']):,} named actors"))
    return out, "Merges are proposals from agenttrace.identity (counted evidence per pair), not facts."


def _gap_merged(s):
    times = s.rec["_times"]
    out = []
    rx = s.pack.raw.get("coarse_channels", [])
    if not rx:
        return [_scn("base", "As counted", "base", _values(s, times))], "This pack lists no place the redaction may have merged, so nothing changes."
    for mode, lab, case in (("exclude", "Drop messages on possibly merged places", "exclude"),
                            ("asis", "As counted (counted as messages, not used for the first message or the signs)", "base"),
                            ("include", "Treat them as real messages", "include")):
        out.append(_scn(mode, lab, case, _values(s, times, coarse_mode=mode)))
    return out, "A merged place may stand for several real places, so a write and a read there may not be one message."


def _visible_shares(s):
    """[(v, label, source)] for the missing-channel scenario."""
    ctx = None
    try:
        with open(CONTEXT, encoding="utf-8") as f:
            ctx = json.load(f)
    except OSError:
        pass
    try:
        from . import board
        fn = getattr(board, "visible_share", None)
        r = fn(s) if callable(fn) else None
        if r:
            return [(1.0, "Nothing missing", "no assumption")] + [(float(x[0]), x[1], x[2]) for x in r], "agenttrace.board"
    except Exception:
        pass
    matches = bool(ctx) and _matches_incident(s, ctx)
    if matches:
        chans = [c for c in s.flow.get("_channels", []) if c["channel"].startswith("board:")]
        folders = len(chans)
        v_folder = min(1.0, folders / BOARD_MESSAGES) if folders else None
        rows = [(1.0, "Nothing missing", "no assumption"),
                (BOARD_NAMESPACE_SHARE, "The release sees the whole main board: 95% of the traffic", "OpenAI estimate that the main namespace holds at least 95% of Artifactory messaging (METR p.25)")]
        if v_folder:
            rows.append((v_folder, f"The release sees only its {folders:,} board folders of about {BOARD_MESSAGES:,} board messages", "METR p.5, p.22-23, p.30-31"))
        return rows, "published numbers for this incident"
    return [(1.0, "Nothing missing", "no assumption")] + [(v, f"Assume the release sees {round(v * 100)}% of the traffic", "stated assumption") for v in ASSUMED_VISIBLE], "assumed"


def _matches_incident(s, ctx):
    return insight.context(s).get("context") is not None


def _gap_channel(s, base):
    shares, src = _visible_shares(s)
    named = base["_named"]
    exact_t = [t for t, d, a, b, c in named if not c]
    allt = sorted(d["read_time"] for d in s.flow["_deliveries"])
    pool = exact_t if len(exact_t) >= 3 else allt
    k = min(len(pool), 10)
    gap = (pool[k - 1] - pool[0]) / (k - 1) if k >= 2 else None
    lo = _prep(s)["lo"]
    out = []
    for v, lab, why in shares:
        vals = {k2: x for k2, x in base.items() if not k2.startswith("_")}
        M = base["messages"]
        vals["messages"] = round(M / v) if v else None
        P = base["pairs"]
        vals["pairs_low"], vals["pairs"] = P, min(round(P + (vals["messages"] - M)), max(P, len(identity._base(s)["named"]) * (len(identity._base(s)["named"]) - 1))) if v else P
        if v < 1 and gap is not None and base["first_message"] is not None:
            t1 = base["first_message"] - (1 / v - 1) * gap
            t1 = max(t1, lo) if lo is not None else t1
            vals["first_message"] = t1
            hs = sorted(s.harm_sorted)
            vals["first_message_share"] = _share(hs, t1)
            vals["time:message"], vals["share:message"] = t1, vals["first_message_share"]
            if vals.get("volume_alarm") is not None:
                vals["alarm_lead_h"] = round((vals["volume_alarm"] - t1) / HOUR, 1)
            fj = [x for x in (vals.get("first_joint"), t1) if x is not None]
            if fj:
                vals["first_joint"] = min(fj)
                if vals.get("volume_alarm") is not None:
                    vals["joint_lead_h"] = round((vals["volume_alarm"] - vals["first_joint"]) / HOUR, 1)
        out.append(_scn(f"v{round(v * 1000)}", lab, "base" if v == 1.0 else "assumed", vals, why))
    note = (f"Parametric, not measured. A share v of the traffic is visible; messages are scaled by 1/v; pairs run from the observed pairs "
            f"(every unseen message repeats one) to one new pair per unseen message. The first message moves earlier by (1/v - 1) times the "
            f"early spacing of visible messages ({round(gap / HOUR, 1) if gap else 'unknown'} h), not before the first dated record. "
            f"Other signs are left as counted, so this is a floor on the shift. Source of v: {src}.")
    return out, note


def _gap_success(s, base):
    named = base["_named"]
    p = _prep(s)
    out = []
    harm_t = sorted(s.rec["_times"][r] for r in s.harmful if r in s.rec["_times"])
    base_signals = insight.simulate(s)["signals"]
    msg_sig = [g for g in base_signals if g["key"] == "message" or g["key"] == "two_way" or g["key"].startswith("group")]
    for pf in SUCCESS_P:
        if pf == 0:
            out.append(_scn("p0", "Every read worked (as counted)", "base", {k: v for k, v in base.items() if not k.startswith("_")}))
            continue
        rng = random.Random(SEED + int(pf * 100))
        draws = []
        for _ in range(SUCCESS_DRAWS):
            kept = [x for x in named if rng.random() >= pf]
            exact = [(t, d, a, b) for t, d, a, b, c in kept if not c]
            draws.append((len(kept), len({(a, b) for _, _, a, b, _ in kept}), exact))
        mid = sorted(draws, key=lambda x: (x[2][0][0] if x[2] else float("inf")))[len(draws) // 2]
        # median draw by first message time; counts as the mean over draws
        vals = {k: v for k, v in base.items() if not k.startswith("_")}
        vals["messages"] = round(sum(d[0] for d in draws) / len(draws), 1)
        vals["pairs"] = round(sum(d[1] for d in draws) / len(draws), 1)
        firsts = sorted(d[2][0][0] for d in draws if d[2])
        vals["first_message"] = firsts[len(firsts) // 2] if firsts else None
        vals["first_message_share"] = _share(harm_t, vals["first_message"])
        vals["first_message_lo_hi"] = [firsts[0], firsts[-1]] if firsts else None
        exact = mid[2]
        gt, two = fx_whatif._group_and_two_way(exact)
        sg = {"message": exact[0][0] if exact else None, "two_way": two[0] if two else None}
        for k in fx_whatif.GROUP_STEPS:
            sg[f"group{k}"] = gt[k][0] if k in gt else None
        for k, t in sg.items():
            vals["time:" + k] = t
            vals["share:" + k] = _share(harm_t, t)
        alarm = vals.get("volume_alarm")
        vals["alarm_lead_h"] = round((alarm - vals["first_message"]) / HOUR, 1) if (alarm is not None and vals["first_message"] is not None) else None
        out.append(_scn(f"p{round(pf * 100)}", f"{round(pf * 100)}% of reads failed", "assumed", vals,
                        f"median of {SUCCESS_DRAWS} random draws for the first message; message and pair counts are means"))
    return out, ("Parametric, not measured: the records rarely show whether a read returned anything. A share p of the reads that "
                 "became messages is dropped at random (fixed seed). Signs that rest on places, tokens or programs are left as counted.")


# ------------------------------------------------------------------ ranges

def _headline_defs(s):
    d = [("first_message", "First message between named agents", "time"),
         ("first_message_share", "Harm still to come at the first message", "share"),
         ("messages", "Messages between named agents", "count"),
         ("pairs", "Pairs of named agents who talked", "count"),
         ("alarm_lead_h", "Hours the first message comes before the volume alarm", "hours"),
         ("joint_lead_h", "Hours the earliest joint sign comes before the volume alarm", "hours")]
    for g in insight.simulate(s)["signals"]:
        d.append(("share:" + g["key"], f"Harm still to come at: {g['name']}", "share"))
    return d


def _range(scns, key, kind):
    xs = [(x["values"].get(key), x) for x in scns if x["values"].get(key) is not None]
    base = next((x["values"].get(key) for x in scns if x["case"] == "base"), None)
    if not xs:
        return {"lo": None, "hi": None, "base": base, "n": 0}
    lo = min(xs, key=lambda p: p[0])
    hi = max(xs, key=lambda p: p[0])
    return {"lo": lo[0], "hi": hi[0], "base": base, "lo_label": lo[1]["label"], "hi_label": hi[1]["label"], "n": len(xs),
            "of": len(scns), "missing": len(scns) - len(xs)}


def _finish(s, key, title, scns, note, defs, computable=True):
    ranges = {k: _range(scns, k, kind) for k, _, kind in defs}
    for k, r in ranges.items():
        if kind_of(defs, k) == "time":
            for e in ("lo", "hi", "base"):
                r[e + "_iso"] = _iso(r[e])
    return {"key": key, "title": title, "rows": GAP_ROWS.get(key, []), "computable": computable, "note": note,
            "scenarios": scns, "ranges": ranges}


def kind_of(defs, k):
    return next((x[2] for x in defs if x[0] == k), None)


def _compact(scns):
    """Scenario values safe for JSON, with times also as text."""
    for x in scns:
        v = x["values"]
        for k in list(v):
            if k.startswith("time:") or k in ("first_message", "volume_alarm", "first_joint"):
                v[k + "_iso"] = _iso(v[k])
    return scns


def compute(s):
    """All gaps, once per session."""
    c = getattr(s, "_sens", None)
    if c is not None:
        return c
    t0 = _time.time()
    if not s.rec["_times"] and not s.flow["_deliveries"]:
        s._sens = {"available": False, "reason": "This trace has no dated records and no messages, so there is nothing to recount.",
                   "gaps": [], "headlines": [], "elapsed_s": 0}
        return s._sens
    p = _prep(s)
    defs = _headline_defs(s)
    base = _values(s, s.rec["_times"])
    out = []
    plan = [("time", lambda: _gap_time(s)), ("identity", lambda: _gap_identity(s)), ("merged", lambda: _gap_merged(s)),
            ("channel", lambda: _gap_channel(s, base)), ("success", lambda: _gap_success(s, base))]
    titles = {k: t for k, t, _ in GAPS}
    for key, fn in plan:
        try:
            scns, note = fn()
            scns = _compact(scns)
            out.append(_finish(s, key, titles[key], scns, note, defs))
        except Exception as e:   # a section the data cannot support says so
            out.append({"key": key, "title": titles[key], "rows": GAP_ROWS.get(key, []), "computable": False,
                        "note": f"Could not be computed on this trace ({type(e).__name__}: {e}).", "scenarios": [], "ranges": {}})
    out.append({"key": "reasoning", "title": titles["reasoning"], "rows": GAP_ROWS["reasoning"], "computable": False, "scenarios": [], "ranges": {},
                "note": "Not testable: the records hold code and responses, not the model's reasoning, so no range can be computed. "
                        "The incident reports describe what agents intended; the records only show what they ran."})
    # all gaps at once
    allscn = [x for g in out for x in g["scenarios"]]
    overall = {k: _range(allscn, k, kind) for k, _, kind in defs}
    for k, r in overall.items():
        if kind_of(defs, k) == "time":
            for e in ("lo", "hi", "base"):
                r[e + "_iso"] = _iso(r[e])
    res = {"available": True, "dataset": s.name,
           "headlines": [{"key": k, "label": l, "kind": kd} for k, l, kd in defs],
           "baseline": {k: v for k, v in _compact([_scn("base", "", "base", base)])[0]["values"].items()},
           "gaps": out, "overall": overall, "sigma_hours": p["sigma_global"],
           "records": len(s.events), "dated": len(s.rec["_times"]),
           "counts_note": "Counts are recomputed from the loaded records; they move if the counting rules change.",
           "elapsed_s": round(_time.time() - t0, 1)}
    s._sens = res
    return res


# ------------------------------------------------------------------ sections that need other parts

def sensitivity_gap(s, key):
    r = compute(s)
    g = next((x for x in r.get("gaps", []) if x["key"] == key), None)
    if g is None:
        raise LookupError(f"no gap {key!r}; choose one of " + ", ".join(k for k, _, _ in GAPS))
    return {"gap": g, "headlines": r["headlines"], "baseline": r["baseline"]}


# ------------------------------------------------------------------ the insiders' findings

def _tolerance_h(s):
    b = [x.get("fit_error_hours_p90") or 0 for x in s.rec["time_test"].get("blocks", []) if x.get("timed")]
    return max(1.0, max(b) if b else 1.0)


def _span(s):
    ts = s.rec["_times"]
    return (min(ts.values()), max(ts.values())) if ts else (None, None)


def _first_record(s, how):
    """(time, record id) of the first record matching a milestone's rule, or None."""
    times, intents = s.rec["_times"], s.rec["_intents"]
    best = None

    def see(e):
        nonlocal best
        t = times.get(e.id)
        if t is not None and (best is None or t < best[0]):
            best = (t, e.id)
    k = how["kind"]
    if k == "first_intent":
        for e in s.events:
            if intents.get(e.id) == how["intent"]:
                see(e)
    elif k == "first_text":
        rx = re.compile(how["pattern"], re.I)
        for e in s.events:
            if e.id in times and rx.search(e.text):
                see(e)
    elif k == "first_identity":
        for e in s.events:
            if how["identity"] in s.rec["_ids"].get(e.id, {}):
                see(e)
    return best


def _utc(text):
    return dt.datetime.strptime(text[:16], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp()


def _fmt_h(h):
    a = abs(h)
    return f"{a:.1f} h" if a < 48 else f"{a / 24:.1f} days"


def _live_numbers(s):
    sm = s.summary()
    act = sm.get("actions") or {}
    chans = s.flow.get("_channels", [])
    board = [c for c in chans if c["channel"].startswith("board:")]
    ops = sum(c["writes"] + c["reads"] for c in chans)
    bops = sum(c["writes"] + c["reads"] for c in board)
    bmsg = sum(1 for d in s.flow["_deliveries"] if d["channel"].startswith("board:") and insight.is_named(d["from"]) and insight.is_named(d["to"]))
    return {"_board_share": (bops / ops) if ops else 0.0, "named_actors": f"{act.get('named_actors', 0):,}", "anon_runs": f"{act.get('runs', 0):,}",
            "board_folders": f"{len(board):,}", "board_messages": f"{bmsg:,}",
            "board_ops_share": f"{round(100 * bops / ops)}%" if ops else "0%"}


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def insiders(s):
    c = getattr(s, "_insiders", None)
    if c is not None:
        return c
    ctx = insight.context(s)
    if ctx.get("context") is None:
        s._insiders = {"available": False, "reason": "These findings are about the July 2026 Hugging Face incident, and this dataset does not match "
                       "it (the match is by dataset name or identity, and a minimum size), so there is nothing to compare."}
        return s._insiders
    with open(INSIDERS, encoding="utf-8") as f:
        spec = json.load(f)
    from . import claims as claims_mod
    with open(os.path.join(HERE, "claims", "swarm_traces_report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    cl = {x["id"]: x for x in claims_mod.evaluate(s.events, s.pack, s.res, s.rec, claims_mod.load_claims(os.path.join(HERE, "claims", "swarm_traces_report.json")))}
    ext = (ctx.get("milestones") or {})
    mstone = {m["event"]: m for m in ext.get("milestones", [])}
    with open(os.path.join(HERE, "claims", "incident_milestones.json"), encoding="utf-8") as f:
        mspec = {m["event"]: m for m in json.load(f)["milestones"]}
    tol = _tolerance_h(s)
    lo, hi = _span(s)
    live = _live_numbers(s)
    out = []
    for f_ in spec["findings"]:
        ck = f_["check"]
        k = ck["kind"]
        status, ev, why = "invisible", {"records": [], "n": None, "numbers": {}}, ""
        link = dict(f_.get("view") or {})
        if k == "milestone":
            m = mstone.get(ck["event"])
            diff = m["difference_h"] if m else None
            how = mspec[ck["event"]]["ours"]
            fr = _first_record(s, how) if how["kind"] in ("first_intent", "first_text", "first_identity") else None
            if diff is None:
                status, why = "invisible", "No record shows it: the tool found nothing to match this moment."
            else:
                status = "recovered" if abs(diff) <= tol else "partly"
                why = (f"The tool puts it at {m['ours']} UTC, {_fmt_h(diff)} {'later' if diff > 0 else 'earlier'} than the report ({m['source_time']} UTC). "
                       f"Within the dating error of {tol:.1f} h." if abs(diff) <= tol else
                       f"The tool puts it at {m['ours']} UTC, {_fmt_h(diff)} {'later' if diff > 0 else 'earlier'} than the report, more than the dating error of {tol:.1f} h.")
                why += " Rule used: " + m["match"] + "."
            ev = {"records": [fr[1]] if fr else [], "n": None, "numbers": {"ours": m["ours"] if m else None, "report": m["source_time"] if m else None, "difference_h": diff}}
        elif k == "per_day":
            pd = ext.get("per_day")
            if pd and pd.get("rank_correlation") is not None:
                rho = pd["rank_correlation"]
                status = "recovered" if rho >= 0.9 else ("partly" if rho >= 0.5 else "invisible")
                why = (f"The tool's actions per day rank the days in the same order as the Hugging Face log with rank correlation {rho}. "
                       "The release is a sample of the actions Hugging Face recovered, so the sizes differ: the tool counts "
                       + ", ".join(f"{d[5:]} {n:,}" for d, n in zip(pd["days"], pd["ours"])) + ".")
                ev = {"records": [], "n": None, "numbers": {"rank_correlation": rho, "ours": pd["ours"], "report": pd["hugging_face"]}}
            else:
                why = "No dated actions to compare by day."
        elif k in ("span_start", "span_end"):
            src = _utc(ck["time"])
            if lo is None:
                why = "No dated records."
            elif k == "span_start":
                d_h = (lo - src) / HOUR
                if d_h > tol:
                    status = "invisible"
                    why = f"The earliest dated record is at {_iso(lo)} UTC, {_fmt_h(d_h)} after this moment ({ck['time']} UTC). Whatever happened before it is outside what the release dates."
                else:
                    status = "recovered"
                    why = f"The release's dated records reach back to {_iso(lo)} UTC, to this moment ({ck['time']} UTC) within the dating error of {tol:.1f} h."
                ev = {"records": [], "n": None, "numbers": {"ours": _iso(lo), "report": ck["time"], "difference_h": round(d_h, 2)}}
            else:
                d_h = (hi - src) / HOUR
                if d_h < -tol:
                    status = "invisible"
                    why = f"The latest dated record is at {_iso(hi)} UTC, {_fmt_h(d_h)} before this moment ({ck['time']} UTC): the release does not reach it."
                elif d_h <= tol:
                    status = "recovered"
                    why = f"The latest dated record is at {_iso(hi)} UTC, within the dating error of {tol:.1f} h of this moment ({ck['time']} UTC)."
                else:
                    status = "recovered" if d_h <= 24 else "partly"
                    why = f"The latest dated record is at {_iso(hi)} UTC, {_fmt_h(d_h)} after this moment ({ck['time']} UTC): activity continues after the moment the report names."
                ev = {"records": [], "n": None, "numbers": {"ours": _iso(hi), "report": ck["time"], "difference_h": round(d_h, 2)}}
        elif k == "text_count":
            rx = re.compile("|".join(f"(?:{p})" for p in ck["patterns"]), re.I if "i" in ck.get("flags", "") else 0)
            hits = [e.id for e in s.events if rx.search(e.text)]
            n = len(hits)
            exp = ck.get("expect")
            if not n:
                status = "invisible"
                why = "No record in the release matches."
            elif exp and 0.75 <= n / exp <= 1.34:
                status = "recovered"
            else:
                status = "partly"
            if n:
                why = (f_.get("why_static") or "{n} records match.").format_map(_Safe(n=f"{n:,}", **live))
            ev = {"records": hits[:8], "n": n, "numbers": {"records": n, "report": exp}}
        elif k == "claim":
            r = cl.get(ck["claim"])
            cited, found, matched = (len(r["cited"]), r["cited_found"], r["cited_matched"]) if r else (0, 0, 0)
            n = r["records"] if r else 0
            if not n:
                status, why = "invisible", "No record in the release matches what the report describes."
            elif cited and matched == cited:
                status, why = "recovered", f"{n:,} records show it, and all {cited} records the report cites are in the release and match."
            elif cited:
                status, why = "partly", f"{n:,} records show it, but only {matched} of the {cited} records the report cites match (in the release: {found})."
            else:
                status, why = "partly", f"{n:,} records match the report's description; the report cites no record, so they cannot be checked against a citation. Whether the activity ran or succeeded is not in the records."
            ev = {"records": ([x["id"] for x in r["cited"] if x["matches_patterns"]][:8] or ([r["first_record"]] if r and r["first_record"] else [])) if r else [],
                  "n": n, "numbers": {"records": n, "cited": cited, "cited_matched": matched, "first_time": r["first_time"] if r else None}}
        elif k == "board_share":
            share = live["_board_share"]
            status = "partly" if share >= 0.5 else "invisible"
            why = (f_.get("why_static") or "").format_map(_Safe(**live))
            if status == "partly":
                why += " The board dominates the messaging that does show, which fits the report, but the release is not a measure of the board."
            ev = {"records": [], "n": None, "numbers": {"board_ops_share": round(share, 3)}}
        else:    # static
            status = f_.get("status", "invisible")
            why = (f_.get("why_static") or "").format_map(_Safe(**live))
        if ev["records"] and ev["n"] is not None and ev["n"] > len(ev["records"]) and k == "text_count":
            link["q"] = "|".join(ck["patterns"])[:80]
        out.append({"id": f_["id"], "group": f_["group"], "source": f_["source"], "finding": f_["finding"], "status": status,
                    "evidence": ev, "why": why, "view": link})
    cnt = Counter(x["status"] for x in out)
    res = {"available": True, "dataset": s.name, "findings": out, "tolerance_h": round(tol, 1),
           "counts": {k: cnt.get(k, 0) for k in ("recovered", "partly", "invisible")}, "total": len(out),
           "by_group": {g: {k: sum(1 for x in out if x["group"] == g and x["status"] == k) for k in ("recovered", "partly", "invisible")}
                        for g in dict.fromkeys(x["group"] for x in out)},
           "about": spec["about"], "status_rule": spec["status_rule"]}
    s._insiders = res
    return res


# ------------------------------------------------------------------ what to collect next time

COLLECT = [
    {"id": "actor", "gap": "identity", "field": "An actor id on every record (which agent run wrote it)",
     "closes": "Tokens are not agents: the same agent under several tokens, and runs with no name at all.",
     "cost": "Cheap for a lab that runs the agents: the harness already knows which run it is executing. One extra field per log line.",
     "what_it_removes": "the identity range: messages and pairs would be counted between agents, not tokens"},
    {"id": "time", "gap": "time", "field": "A timestamp on every record (server clock, UTC, to the second)",
     "closes": "Records with no time, and times that had to be estimated from text.",
     "cost": "Very cheap: the logging library writes it. The only care needed is one trusted clock.",
     "what_it_removes": "dating error and undated records: the ordering of every message and sign becomes exact"},
    {"id": "bodies", "gap": "success", "field": "Full request bodies and responses (status code, size, first bytes)",
     "closes": "Whether a read or write worked: now a read is an attempt, and a message may never have arrived.",
     "cost": "Storage and privacy: responses can hold secrets, so keep them in a restricted store and hash or redact before sharing. Typically several times the size of the request log.",
     "what_it_removes": "the failed-read assumption: each message is confirmed or dropped"},
    {"id": "board", "gap": "channel", "field": "The contents and the write and read log of every shared place (here, the board)",
     "closes": "Messages through places outside the release, and which reads reached which writes.",
     "cost": "Needs the operator of the shared service (here the package cache) to keep its access log. Cheap if kept from the start; impossible after the service is wiped or rebuilt.",
     "what_it_removes": "the unseen-traffic range: the visible share becomes known"},
    {"id": "places", "gap": "merged", "field": "Unredacted place names kept by the data owner (or a keyed hash per place)",
     "closes": "Places the redaction merged into one, so a write and a read may not be the same place.",
     "cost": "Nearly free: a keyed hash of each place name keeps the privacy and the identity of the place. The key stays with the data owner.",
     "what_it_removes": "the merged-place range: each message is on a real place"},
    {"id": "task", "gap": "identity", "field": "An agent-to-task mapping (which task or goal each run was given)",
     "closes": "Why agents moved together, and whether agents that look coordinated were given the same task.",
     "cost": "Cheap: it is in the lab's own scheduler. Sharing it reveals what the evaluation was, so the lab must decide that separately.",
     "what_it_removes": "nothing in the counts above; it explains them. A group sharing a task is less surprising than a group that was not"},
    {"id": "reasoning", "gap": "reasoning", "field": "The model's reasoning and tool-call transcript for each run",
     "closes": "Intent: what the agent meant to do, whether it chose to go on, and whether it knew a warning.",
     "cost": "The largest by far: transcripts are long, can hold the lab's own private material, and some labs will not release them. Release a sample, or release them to an independent reviewer under agreement.",
     "what_it_removes": "cannot be sized from the records; see the section above"},
]


def _width(r):
    """How much a range matters: 0..3, from harm share points, message count and first-message hours."""
    if not r:
        return 0.0
    out = 0.0
    sh = r.get("first_message_share")
    if sh and sh["lo"] is not None:
        out += min(1.0, sh["hi"] - sh["lo"])
    m = r.get("messages")
    if m and m["lo"] is not None:
        out += min(1.0, (m["hi"] - m["lo"]) / max(m["hi"], 1))
    f = r.get("first_message")
    if f and f["lo"] is not None:
        out += min(1.0, (f["hi"] - f["lo"]) / HOUR / 24)
    return out


def _span_text(x, kind):
    if x is None or x["lo"] is None:
        return "no value"
    f = {"time": lambda v: _iso(v), "share": lambda v: f"{round(v * 100)}%", "count": lambda v: f"{v:,.0f}", "hours": lambda v: f"{v:.1f} h"}[kind]
    return f(x["lo"]) if f(x["lo"]) == f(x["hi"]) else f"{f(x['lo'])} to {f(x['hi'])}"


def collect_next(s):
    sens = compute(s)
    if not sens.get("available"):
        return {"available": False, "reason": sens.get("reason")}
    g = {x["key"]: x for x in sens["gaps"]}
    rows = []
    for c in COLLECT:
        gap = g.get(c["gap"], {})
        r = gap.get("ranges", {}) if gap.get("computable") else {}
        score = _width(r) if r else None
        effect = None
        if r:
            b = r.get("first_message", {}).get("base")
            effect = {"first_message": _span_text(r.get("first_message"), "time"), "first_message_share": _span_text(r.get("first_message_share"), "share"),
                      "messages": _span_text(r.get("messages"), "count"), "pairs": _span_text(r.get("pairs"), "count"),
                      "as_counted": {"first_message": _iso(b), "messages": r.get("messages", {}).get("base"), "pairs": r.get("pairs", {}).get("base"),
                                     "first_message_share": r.get("first_message_share", {}).get("base")}}
        parametric = c["gap"] in ("channel", "success")
        sentence = None
        if effect:
            sentence = (f"With this in the log, the first message between named agents, today anywhere from {effect['first_message']} "
                        f"(harm still to come {effect['first_message_share']}), would be one time; messages today {effect['messages']} would be one count; "
                        f"pairs today {effect['pairs']} would be one count.")
            if parametric:
                sentence += " The range is parametric: it follows the assumption stated in the sensitivity section."
        elif c["gap"] == "reasoning":
            sentence = "Cannot be sized from these records."
        elif gap:
            sentence = gap.get("note")
        rows.append({**c, "effect": effect, "sentence": sentence, "parametric": parametric, "score": round(score, 2) if score is not None else None,
                     "computable": bool(r), "note": gap.get("note")})
    # the two practices that share a gap (actor id and agent-task mapping): only the first carries the range
    rows[5]["effect"], rows[5]["sentence"] = None, "Explains the counts; it does not change them. See the actor id for the size."
    rows[5]["score"] = 0.0
    rows.sort(key=lambda x: (-(x["score"] if x["score"] is not None else -1), x["id"]))
    for i, x in enumerate(rows):
        x["priority"] = i + 1
    return {"available": True, "dataset": s.name, "items": rows, "elapsed_s": sens["elapsed_s"],
            "basis": "Sizes come from the sensitivity ranges of this dataset, computed on load: the range shown is what the missing field leaves open. "
                     "Priority follows how wide that range is for the first message, its harm share and the message count; practices that cannot be sized go last."}


# ------------------------------------------------------------------ routes

def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("No dataset loaded. Upload a file first.")
    return s


def _get_sensitivity(state, q):
    return compute(_session(state))


def _get_gap(state, q):
    return sensitivity_gap(_session(state), q.get("key", ""))


def _get_insiders(state, q):
    return insiders(_session(state))


def _get_collect(state, q):
    return collect_next(_session(state))


GET = {"sensitivity": _get_sensitivity, "sensitivity_gap": _get_gap, "insiders": _get_insiders, "collect_next": _get_collect}
POST = {}

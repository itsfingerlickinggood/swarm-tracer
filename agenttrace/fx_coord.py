"""Coordination without messages: behaviour-based links between named actors.

A message needs a shared place. Two actors can also be linked by what they do and when, with no place
between them. Three conservative tests, each against a chance model, on dated actions of named actors:

  synchrony      a burst is an actor's action of some intent with none of the same intent in the hour
                 before. A co-event is a burst of a and one of b, same intent, starting within WINDOW
                 of each other (each burst used once). Null: a's bursts are redrawn NULL_DRAWS times from
                 the burst times of every OTHER actor (so a swarm-wide surge is expected, not
                 surprising) with a jitter of one window; b stays fixed. A link needs MIN_CO co-events
                 at MIN_SLOTS different times, z >= Z_SYNC, no null draw reaching the observed count, and a
                 Poisson tail at the null mean that stays under FWER after multiplying by the pairs tested.
  adoption       a technique is an intent, an evidence tag, a host or a program family; an actor adopts
                 it at its first dated use, if it had already been active for an hour (what an actor does
                 as it starts is not adoption). Techniques adopted by MIN_ADOPTERS..MAX_SHARE of the actors
                 are kept. A pair co-adopts a technique when both first uses are within PAIR_H hours.
                 Null: adopters are random actors in proportion to how many techniques each adopted,
                 times as observed; the expected count is summed over techniques (Poisson). A link needs
                 MIN_CO_ADOPT co-adoptions, z >= Z_ADOPT and p x pairs tested <= FWER. Order (who was first) is counted
                 only when the gap is at least an hour. A cascade is 3+ first uses within CASCADE_H hours
                 of a technique's first use, strong when a random
                 moment of each adopter's own active time gives that many in under P_CASCADE of draws.
  complementary  the same numeric parameter on the same target (offset=, page=, ...): two actors with 3+
                 values each, no value in common, on one grid whose cells they cover densely, at
                 overlapping times. Null: both pick cells at random; p = chance of no overlap.

Times are mostly estimated (median error about 15 minutes, p90 about 2 hours), so every window is at
least an hour. Each link says whether the pair also has a message and whether both tokens belong to
one estimated agent (fx_whatif). fx_behavior's lead-lag result is attached to a pair when it has one.
Everything is cached on the session (s._fx_coord).
"""
import bisect
import math
import random
import re
import time as _time
from collections import Counter, defaultdict
from functools import reduce

from . import reconstruct

iso = reconstruct.iso
HOUR = 3600.0

WINDOW = HOUR            # two bursts within this are a co-event
BURST_GAP = HOUR         # a burst starts after this long without the same intent
MIN_CO = 4               # co-events a synchrony link needs
MIN_SLOTS = 3            # ... at this many different times (2-hour slots)
Z_SYNC = 3.5
FWER = 0.05              # chance of even one false link per test family, after multiplying p by the pairs tested
NULL_DRAWS = 400
MAX_SYNC_CANDIDATES = 400

MIN_ADOPTERS = 3
MAX_SHARE = 0.25         # a technique used by more of the actors than this is common, not new
PAIR_H = 6.0
CASCADE_H = 12.0
MIN_CO_ADOPT = 4
Z_ADOPT = 4.0
CASCADE_DRAWS = 1000
P_CASCADE = 0.005
ORDER_H = 1.0            # a first use this much earlier counts as "before"

MIN_VALUES = 3           # complementary work: values per actor
MAX_GRID = 400
P_COMPL = 0.01
TEXT_CAP = 20000

_HOST = re.compile(r"(?:https?:)?//([A-Za-z0-9][A-Za-z0-9.\-]{2,60}\.[a-z]{2,8})\b|\[((?:SERVICE HOST|PROXY|SERVICE) \d+)[^\]]*\]")
_PARAM = re.compile(r"\b([A-Za-z_]{3,20})[\"']?\s*[=:]\s*[\"']?(\d{1,9})\b")
_TARGET = re.compile(r"\[(?:HF REPO|REDACTED:destination)[^\]]*\]|[a-z0-9][a-z0-9.\-]+\.[a-z]{2,6}/[\w.\-/]{1,60}")
_PARAM_SKIP = frozenset("length limit timeout status width height version port size max_attempts attempts retries retry "
                        "indent maxlen count top num per_page page_size chunk depth level code time ttl seed".split())


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _agent_of(s):
    try:
        from . import fx_whatif
        groups = fx_whatif.whatif(s, "estimate")["groups"]
    except Exception:
        groups = []
    amap = {}
    for g in groups:
        for a in g.get("actors", []):
            amap[a] = g.get("agent")
    return amap


def _pkey(a, b):
    return (a, b) if a < b else (b, a)


def _poisson_sf(k, lam):
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, 1.0 - cdf)


# ------------------------------------------------------------------ the actions of named actors

def _actions(s):
    """Dated actions of named actors: actor -> [(time, intent, record)] in time order."""
    times, intents = s.rec["_times"], s.rec["_intents"]
    acts = defaultdict(list)
    for e in s.events:
        a, ak = s.actor[e.id]
        if ak == "run" or not reconstruct.is_action(e, s.pack):
            continue
        t = times.get(e.id)
        if t is not None:
            acts[a].append((t, intents.get(e.id), e.id))
    for a in acts:
        acts[a].sort()
    return acts


# ------------------------------------------------------------------ 1. synchrony

def _bursts(rows):
    """[(time, intent, record)] -> burst starts per intent (generic intents left out)."""
    last, out = {}, defaultdict(list)
    for t, it, rid in rows:
        if not it or it == "other":
            continue
        if it not in last or t - last[it] >= BURST_GAP:
            out[it].append((t, rid))
        last[it] = t
    return out


def _co(xs, ys, events=None, intent=None):
    """Co-events between two sorted burst lists [(t, id)]: one-to-one, within WINDOW."""
    i = j = n = 0
    while i < len(xs) and j < len(ys):
        d = xs[i][0] - ys[j][0]
        if abs(d) <= WINDOW:
            n += 1
            if events is not None:
                events.append((min(xs[i][0], ys[j][0]), intent, xs[i], ys[j]))
            i += 1
            j += 1
        elif d < 0:
            i += 1
        else:
            j += 1
    return n


def _synchrony(acts):
    bursts = {a: _bursts(rows) for a, rows in acts.items()}
    bursts = {a: b for a, b in bursts.items() if sum(len(v) for v in b.values()) >= MIN_CO}
    names = sorted(bursts)
    pool_all = sorted((t, a) for a in names for v in bursts[a].values() for t, _ in v)
    cands = []
    tested = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ba, bb = bursts[a], bursts[b]
            shared = [it for it in ba if it in bb]
            if not shared:
                continue
            tested += 1
            obs = sum(_co(ba[it], bb[it]) for it in shared)
            if obs >= MIN_CO:
                cands.append((obs, a, b, shared))
    cands.sort(key=lambda x: (-x[0], x[1], x[2]))
    capped = len(cands) > MAX_SYNC_CANDIDATES
    out = {}
    rng = random.Random(20261113)
    for obs, a, b, shared in cands[:MAX_SYNC_CANDIDATES]:
        ba, bb = bursts[a], bursts[b]
        events = []
        for it in shared:
            _co(ba[it], bb[it], events, it)
        slots = len({int(e[0] // (2 * HOUR)) for e in events})
        if slots < MIN_SLOTS:
            continue
        pool = [t for t, x in pool_all if x != a and x != b]
        if len(pool) < 20:
            pool = [t for t, x in pool_all]
        counts = []
        for _ in range(NULL_DRAWS):
            n = 0
            for it in shared:
                xs = sorted((rng.choice(pool) + rng.uniform(-WINDOW, WINDOW), None) for _ in ba[it])
                n += _co(xs, bb[it])
            counts.append(n)
        mean = sum(counts) / len(counts)
        sd = math.sqrt(sum((c - mean) ** 2 for c in counts) / len(counts))
        z = (obs - mean) / max(sd, 0.5)
        p = (1 + sum(1 for c in counts if c >= obs)) / (1 + len(counts))
        events.sort()
        out[(a, b)] = {"co_events": obs, "slots": slots, "expected": round(mean, 2), "sd": round(sd, 2), "z": round(z, 2),
                       "p": round(p, 4), "bursts_a": sum(len(v) for v in ba.values()), "bursts_b": sum(len(v) for v in bb.values()),
                       "intents": dict(Counter(e[1] for e in events)),
                       "events": [{"time": iso(e[0]), "intent": e[1], "a_id": e[2][1], "b_id": e[3][1],
                                   "gap_min": round(abs(e[2][0] - e[3][0]) / 60.0)} for e in events[:40]],
                       "p_tail": _poisson_sf(obs, max(mean, 0.05))}
    for v in out.values():
        # family-wise: the Poisson tail at the null mean, times every pair tested, must stay under FWER
        v["p_adj"] = float(f"{min(1.0, v['p_tail'] * max(1, tested)):.2g}")
        v["p_tail"] = float(f"{v['p_tail']:.2g}")
        v["link"] = v["z"] >= Z_SYNC and v["p"] <= round(1.0 / (1 + NULL_DRAWS), 4) and v["p_adj"] <= FWER
    return out, {"pairs_tested": tested, "candidates": len(cands), "capped": capped, "actors": len(names)}, bursts


# ------------------------------------------------------------------ 2. technique adoption

def _techniques(s, acts):
    """technique -> {actor: (first time, record)}"""
    first = defaultdict(dict)
    ev = s.res.get("_evidence") if isinstance(s.res, dict) else None
    prefix = getattr(s, "prefix", {})
    for a, rows in acts.items():
        start = rows[0][0]
        seen = set()
        for t, it, rid in rows:          # time order: the first hit is the first use
            keys = []
            if it and it != "other":
                keys.append("intent:" + it)
            if isinstance(ev, dict):
                for tag in ev.get(rid, ()) or ():
                    if isinstance(tag, str):
                        keys.append("tag:" + tag)
            p = prefix.get(rid)
            if p:
                keys.append("program:" + p)
            text = s.by_id[rid].text[:TEXT_CAP]
            for m in _HOST.finditer(text):
                keys.append("host:" + (m.group(1).lower() if m.group(1) else m.group(2)))
            for k in keys:
                if k not in seen:
                    seen.add(k)
                    # what an actor does in its first hour is how it started, not something it picked up
                    if t - start >= ORDER_H * HOUR:
                        first[k][a] = (t, rid)
    return first


def _adoption(s, acts, amap):
    first = _techniques(s, acts)
    n_act = len(acts)
    cap = max(MIN_ADOPTERS, int(MAX_SHARE * n_act))
    techs = {k: v for k, v in first.items() if MIN_ADOPTERS <= len(v) <= cap}
    weight = Counter()
    for v in techs.values():
        for a in v:
            weight[a] += 1
    W = float(sum(weight.values())) or 1.0
    obs = defaultdict(list)
    rng = random.Random(20261113)
    cascades = []
    for k, v in techs.items():
        order = sorted((t, a, rid) for a, (t, rid) in v.items())
        m = len(order)
        close = []
        for i in range(m):
            for j in range(i + 1, m):
                if order[j][0] - order[i][0] > PAIR_H * HOUR:
                    break
                close.append((order[i], order[j]))
        if close:
            frac = len(close) / (m * (m - 1) / 2.0)
            inc = {a: min(1.0, m * weight[a] / W) for _, a, _ in order}
            for (ta, a, ra), (tb, b, rb) in close:
                obs[_pkey(a, b)].append((k, a, ta, ra, b, tb, rb))
            # expected co-adoptions of every candidate pair under random adopters: added below per pair
            techs[k] = (order, frac)
        else:
            techs[k] = (order, 0.0)
        t0 = order[0][0]
        early = [x for x in order if x[0] - t0 <= CASCADE_H * HOUR]
        if len(early) >= 3:
            agents = {amap.get(a, a) for _, a, _ in early}
            # chance: every adopter picks the technique up at a random moment of its own active time
            spans = [(acts[a][0][0] + ORDER_H * HOUR, max(acts[a][-1][0], acts[a][0][0] + ORDER_H * HOUR)) for _, a, _ in order]
            ge = tot = 0
            for _ in range(CASCADE_DRAWS):
                ts = [rng.uniform(lo, hi) for lo, hi in spans]
                lim = min(ts) + CASCADE_H * HOUR
                n = sum(1 for x in ts if x <= lim)
                tot += n
                ge += n >= len(early)
            pc = (1 + ge) / (1 + CASCADE_DRAWS)
            cascades.append({"technique": k, "adopters": m, "in_cascade": len(early), "agents": len(agents),
                             "expected": round(tot / CASCADE_DRAWS, 2), "p": round(pc, 4),
                             "strong": pc <= P_CASCADE and len(agents) >= 2,
                             "span_h": round((early[-1][0] - t0) / HOUR, 2), "start": iso(t0),
                             "steps": [{"actor": a, "time": iso(t), "id": rid, "agent": amap.get(a)} for t, a, rid in early[:25]]})
    sizes = [(len(o), f) for o, f in techs.values() if f > 0]
    out = {}
    for (a, b), hits in obs.items():
        if len(hits) < MIN_CO_ADOPT:
            continue
        l = 0.0
        for m, f in sizes:
            l += min(1.0, m * weight[a] / W) * min(1.0, m * weight[b] / W) * f
        n = len(hits)
        z = (n - l) / math.sqrt(max(l, 0.25))
        p = _poisson_sf(n, l)
        a_first = sum(1 for h in hits if (h[1] == a and h[5] - h[2] >= ORDER_H * HOUR) or (h[4] == a and h[2] - h[5] >= ORDER_H * HOUR))
        b_first = sum(1 for h in hits if (h[1] == b and h[5] - h[2] >= ORDER_H * HOUR) or (h[4] == b and h[2] - h[5] >= ORDER_H * HOUR))
        hits.sort(key=lambda h: h[2])
        kinds = Counter(h[0].split(":", 1)[0] for h in hits)
        out[(a, b)] = {"co_adoptions": n, "expected": round(l, 2), "z": round(z, 2), "p": float(f"{p:.2g}"),
                       "a_first": a_first, "b_first": b_first, "ties": n - a_first - b_first, "kinds": dict(kinds),
                       "techniques": [{"technique": h[0], "first": h[1], "first_time": iso(h[2]), "first_id": h[3],
                                       "then": h[4], "then_time": iso(h[5]), "then_id": h[6],
                                       "gap_h": round((h[5] - h[2]) / HOUR, 2)} for h in hits[:30]],
                       # program families alone are the tool's "shared program" finding, so a link needs
                       # at least two kinds of technique or two non-program techniques
                       "p_tail": p, "non_program": n - kinds.get("program", 0)}
    for v in out.values():
        v["p_adj"] = float(f"{min(1.0, v.pop('p_tail') * max(1, len(obs))):.2g}")
        v["link"] = v["z"] >= Z_ADOPT and v["p_adj"] <= FWER and v.pop("non_program") >= 2
    cascades.sort(key=lambda c: (-c["strong"], c["p"], -c["in_cascade"], c["span_h"], c["technique"]))
    return out, cascades, {"techniques": len(techs), "techniques_seen": len(first), "max_adopters": cap,
                           "pairs_tested": len(obs)}


# ------------------------------------------------------------------ 3. complementary work

def _complementary(s, acts):
    use = defaultdict(lambda: defaultdict(dict))     # (target, param) -> actor -> value -> (time, record)
    for a, rows in acts.items():
        for t, it, rid in rows:
            text = s.by_id[rid].text[:TEXT_CAP]
            if "=" not in text and ":" not in text:
                continue
            targets = [(m.start(), m.group(0)) for m in _TARGET.finditer(text)]
            if not targets:
                continue
            pos = [p for p, _ in targets]
            for m in _PARAM.finditer(text):
                name = m.group(1).lower()
                if name in _PARAM_SKIP:
                    continue
                i = bisect.bisect_right(pos, m.start()) - 1
                if i < 0 or m.start() - pos[i] > 400:
                    continue
                tgt = re.sub(r"\d+", "#", targets[i][1]) if targets[i][1][0] != "[" else targets[i][1]
                use[(tgt, name)][a].setdefault(int(m.group(2)), (t, rid))
    out = defaultdict(list)
    tested = 0
    for (tgt, name), by in use.items():
        big = sorted(a for a, v in by.items() if len(v) >= MIN_VALUES)
        for i, a in enumerate(big):
            for b in big[i + 1:]:
                va, vb = by[a], by[b]
                tested += 1
                if set(va) & set(vb):
                    continue
                allv = sorted(set(va) | set(vb))
                step = reduce(math.gcd, [y - x for x, y in zip(allv, allv[1:])])
                if step <= 0:
                    continue
                grid = (allv[-1] - allv[0]) // step + 1
                if grid > MAX_GRID or grid > 4 * len(allv):
                    continue
                ta = [x[0] for x in va.values()]
                tb = [x[0] for x in vb.values()]
                if min(ta) - max(tb) > 24 * HOUR or min(tb) - max(ta) > 24 * HOUR:
                    continue
                na, nb = len(va), len(vb)
                # both pick cells at random on the grid: the chance that none coincide
                p = math.comb(grid - na, nb) / math.comb(grid, nb) if grid - na >= nb else 0.0
                lab = "".join("a" if v in va else "b" for v in allv)
                switches = sum(1 for x, y in zip(lab, lab[1:]) if x != y)
                out[(a, b)].append({"target": tgt, "param": name, "step": step, "grid": grid, "values_a": sorted(va)[:40],
                                    "values_b": sorted(vb)[:40], "n_a": na, "n_b": nb, "p": float(f"{p:.2g}"),
                                    "coverage": round(len(allv) / grid, 2), "switches": switches,
                                    "interleaved": switches > 1, "first_a": min(va.values())[1], "first_b": min(vb.values())[1],
                                    "link": p <= P_COMPL})
    return out, {"pairs_tested": tested, "resources": len(use)}


# ------------------------------------------------------------------ all together

def build(s):
    c = getattr(s, "_fx_coord", None)
    if c is not None:
        return c
    t0 = _time.time()
    acts = _actions(s)
    amap = _agent_of(s)
    sync, sync_meta, bursts = _synchrony(acts)
    adopt, cascades, adopt_meta = _adoption(s, acts, amap)
    compl, compl_meta = _complementary(s, acts)
    msg_pairs = Counter(_pkey(d["from"], d["to"]) for d in s.flow["_deliveries"])
    lead = {}
    try:
        from . import fx_behavior
        for p in fx_behavior.leadlag(s)["pairs"]:
            lead[_pkey(p["a"], p["b"])] = {"flag": p["flag"], "leader": p["leader"], "lag_hours": p["lag_hours"], "r": p["r"]}
    except Exception:
        pass
    pairs = {}
    for k in set(sync) | set(adopt) | set(compl):
        a, b = k
        sy, ad, co = sync.get(k), adopt.get(k), [x for x in compl.get(k, [])]
        kinds = []
        if sy and sy["link"]:
            kinds.append("synchrony")
        if ad and ad["link"]:
            kinds.append("adoption")
        if any(x["link"] for x in co):
            kinds.append("complementary")
        zs = [sy["z"] if sy and sy["link"] else 0, ad["z"] if ad and ad["link"] else 0]
        pairs[k] = {"a": a, "b": b, "kinds": kinds, "link": bool(kinds), "z": max(zs), "synchrony": sy, "adoption": ad,
                    "complementary": co, "messages": msg_pairs.get(k, 0), "has_message": k in msg_pairs,
                    "same_agent": a in amap and amap.get(a) == amap.get(b),
                    "agent_a": amap.get(a), "agent_b": amap.get(b), "leadlag": lead.get(k)}
    c = {"pairs": pairs, "cascades": cascades, "acts": acts, "bursts": bursts, "amap": amap,
         "meta": {"synchrony": sync_meta, "adoption": adopt_meta, "complementary": compl_meta, "actors": len(acts)},
         "seconds": round(_time.time() - t0, 2)}
    s._fx_coord = c
    return c


# Measured with simulate_check() on simulated swarms (groundtruth.make, 40 agents, seeds 1-3). Neither
# swarm plans any timing, adoption order or split of work, so a link between two different agents is a
# false positive in both; a link between two tokens of one agent is the same controller, counted apart.
SIMULATED = {"agents": 40, "seeds": [1, 2, 3], "measured": "2026-11-13",
             "benign": {"links": 0, "one_true_agent": 0, "false": 0, "false_synchrony": 0, "false_adoption": 0,
                        "false_complementary": 0, "possible_pairs": 2983, "cascades": 0},
             "coordinated": {"links": 0, "one_true_agent": 0, "false": 0, "false_synchrony": 0, "false_adoption": 0,
                             "false_complementary": 0, "false_with_true_message": 0, "possible_pairs": 2983, "cascades": 0},
             # before the family-wise correction and the "already active for an hour" rule (z and the
             # permutation p only), the same swarms gave 7 false links on benign and 10 on coordinated
             "before_correction": {"benign_false": 7, "coordinated_false": 10}}


def _slim(p):
    out = {k: v for k, v in p.items() if k not in ("synchrony", "adoption", "complementary")}
    sy, ad = p["synchrony"], p["adoption"]
    out["synchrony"] = {k: v for k, v in sy.items() if k != "events"} if sy else None
    out["adoption"] = dict({k: v for k, v in ad.items() if k != "techniques"},
                           examples=[t["technique"] for t in ad["techniques"][:4]]) if ad else None
    out["complementary"] = [{k: v for k, v in x.items() if not k.startswith("values_")} for x in p["complementary"] if x["link"]][:3]
    return out


def summary(s):
    c = build(s)
    links = [p for p in c["pairs"].values() if p["link"]]
    return {"links": len(links),
            "by_kind": dict(Counter(k for p in links for k in p["kinds"])),
            "with_message": sum(1 for p in links if p["has_message"]),
            "behaviour_only": sum(1 for p in links if not p["has_message"]),
            "same_agent": sum(1 for p in links if p["same_agent"]),
            "across_agents": sum(1 for p in links if not p["same_agent"]),
            "new": sum(1 for p in links if not p["same_agent"] and not p["has_message"]),
            "actors": c["meta"]["actors"], "actors_linked": len({x for p in links for x in (p["a"], p["b"])}),
            "cascades": sum(1 for x in c["cascades"] if x["strong"]), "cascade_candidates": len(c["cascades"]),
            "tested": c["meta"],
            "thresholds": {"window_h": WINDOW / HOUR, "min_co": MIN_CO, "min_slots": MIN_SLOTS, "z_sync": Z_SYNC,
                           "null_draws": NULL_DRAWS, "min_adopters": MIN_ADOPTERS, "max_share": MAX_SHARE, "pair_h": PAIR_H,
                           "cascade_h": CASCADE_H, "min_co_adopt": MIN_CO_ADOPT, "z_adopt": Z_ADOPT, "fwer": FWER, "p_cascade": P_CASCADE, "order_h": ORDER_H,
                           "min_values": MIN_VALUES, "p_compl": P_COMPL},
            "simulated": SIMULATED, "seconds": c["seconds"]}


def r_silent(state, q):
    s = _session(state)
    c = build(s)
    links = sorted((p for p in c["pairs"].values() if p["link"]),
                   key=lambda p: (p["same_agent"], p["has_message"], -len(p["kinds"]), -p["z"], p["a"], p["b"]))
    near = sorted((p for p in c["pairs"].values() if not p["link"]),
                  key=lambda p: -max(p["synchrony"]["z"] if p["synchrony"] else 0, p["adoption"]["z"] if p["adoption"] else 0))
    counts = {a: len(rows) for a, rows in c["acts"].items()}
    nodes = sorted({x for p in links for x in (p["a"], p["b"])})
    # message pairs between the linked actors, so the graph can show both kinds of edge
    msg = Counter(_pkey(d["from"], d["to"]) for d in s.flow["_deliveries"])
    return {"summary": summary(s), "links": [_slim(p) for p in links[:150]], "links_total": len(links),
            "near_misses": [_slim(p) for p in near[:12]],
            "nodes": [{"actor": a, "agent": c["amap"].get(a), "actions": counts.get(a, 0)} for a in nodes],
            "message_edges": [{"a": a, "b": b, "n": n} for (a, b), n in msg.items() if a in counts and b in counts and a != b],
            "cascades": c["cascades"][:14], "cascades_total": len(c["cascades"])}


def pair(s, a, b):
    c = build(s)
    if a not in c["acts"] or b not in c["acts"]:
        raise LookupError("both actors must be named actors with dated actions")
    if a == b:
        raise ValueError("give two different actors")
    k = _pkey(a, b)
    p = c["pairs"].get(k) or {"a": k[0], "b": k[1], "kinds": [], "link": False, "z": 0, "synchrony": None, "adoption": None,
                              "complementary": [], "messages": 0, "has_message": False,
                              "same_agent": k[0] in c["amap"] and c["amap"].get(k[0]) == c["amap"].get(k[1]), "leadlag": None}
    rows = {}
    t_lo, t_hi = None, None
    for x in k:
        acts = c["acts"][x]
        hours = Counter()
        for t, it, rid in acts:
            hours[int(t // HOUR)] += 1
        t_lo = acts[0][0] if t_lo is None else min(t_lo, acts[0][0])
        t_hi = acts[-1][0] if t_hi is None else max(t_hi, acts[-1][0])
        bl = sorted((t, it, rid) for it, v in c["bursts"].get(x, {}).items() for t, rid in v)
        rows[x] = {"actions": len(acts), "hours": [[iso(h * HOUR), n] for h, n in sorted(hours.items())][:2000],
                   "bursts": [[iso(t), it, rid] for t, it, rid in bl[:600]]}
    return dict(p, rows=rows, start=iso(t_lo), end=iso(t_hi))


def r_silent_pair(state, q):
    a, b = q.get("a"), q.get("b")
    if not a or not b:
        raise ValueError("give a and b")
    return pair(_session(state), a, b)


GET = {"silent": r_silent, "silent_pair": r_silent_pair}
POST = {}


# ------------------------------------------------------------------ measurement on simulated swarms

def simulate_check(agents=40, seeds=(1, 2, 3), folder=None):
    """Links on simulated swarms with known truth: python3 -m agenttrace.fx_coord"""
    import os
    import tempfile
    from . import groundtruth
    from .session import Session
    out = {"agents": agents, "seeds": list(seeds)}
    for mode in ("benign", "coordinated"):
        tot = {"links": 0, "one_true_agent": 0, "false": 0, "false_synchrony": 0, "false_adoption": 0,
               "false_complementary": 0, "false_with_true_message": 0, "possible_pairs": 0, "cascades": 0}
        for seed in seeds:
            d = tempfile.mkdtemp(prefix="fxk_", dir=folder)
            truth = groundtruth.make(d, agents=agents, seed=seed, mode=mode)
            s = Session()
            s.load(os.path.join(d, "trace.jsonl"), "code_traces.json")
            c = build(s)
            owner = {tok: ag for ag, toks in truth["agents"].items() for tok in toks}
            recs = truth["records"]
            talk = {frozenset((recs[w]["agent"], recs[r]["agent"])) for w, r, _ in truth.get("messages", [])}
            tot["possible_pairs"] += len(c["acts"]) * (len(c["acts"]) - 1) // 2
            tot["cascades"] += sum(1 for x in c["cascades"] if x["strong"])
            for p in c["pairs"].values():
                if not p["link"]:
                    continue
                tot["links"] += 1
                oa, ob = owner.get(p["a"], p["a"]), owner.get(p["b"], p["b"])
                if oa == ob:
                    tot["one_true_agent"] += 1
                    continue
                tot["false"] += 1
                for kind in p["kinds"]:
                    tot["false_" + kind] += 1
                if frozenset((oa, ob)) in talk:
                    tot["false_with_true_message"] += 1
        out[mode] = tot
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(simulate_check(), indent=1))

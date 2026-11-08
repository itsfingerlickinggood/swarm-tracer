"""Identity merging (tokens and names that are probably one agent) and agent roles.

A token is not an agent: one agent can hold several tokens or self-chosen names, and a shared
key stands for many agents. This module proposes pairs of named actors that are probably one
agent, from evidence that is counted in the data, never guessed, and classifies each named
actor's role in the message graph.

Scoring rule (additive; every item lists the record ids behind it):

  for one agent                                                          points
  (a) both identities used inside one record (records with 2-3 tokens)   +3, +1 more if 3+ records
      only inside records that use 4+ tokens at once (a key sweep?)      +1
      both inside one small thread (2-3 named actors), never one record  +2, +1 more if 3+ threads
  (b) one carries the other's token before its first use                 +3
  (c) same self-chosen place (exact name)                                +2
      same place family or self-chosen name family written in the code   +1
      numbered names with the same stem (Helper12, Helper57)             +2 if the stem has 2-5 names,
                                                                         +1 if 6-40
  (d) handoffs: one stops and the other starts within 15 minutes,
      without overlapping, 2+ times                                       +2 (1 time: +1)
  (e) the same programs (identical masked code) run by both, among
      programs run by at most 12 named actors                             +2 if 2+ programs or one run
                                                                         by only 2-3 actors, else +1
  (f) messages between the two (one may be talking to itself), counted
      only when they share no record or thread (there it is implied)     +1

  against                                                                points
      active at the same time (parallel sessions overlap 30%+ of the
      shorter one's active time) and never inside one record              -2
      both write self-chosen names in their code, none in common          -1

Confidence: high at 6+, medium at 4-5, low at 2-3. Pairs under 2 are not proposed. High and medium
also need direct evidence: the same record, a small shared thread, or a carried token. Without it a
pair stays low, because shared places, handoffs, shared programs and names also happen between
different agents that coordinate (see docs/validation.md).
Agent groups join every pair that is high or accepted (and never a rejected pair). The estimate
range: low end also joins medium pairs; high end joins only accepted pairs.
"""
import json
import os
import re
from collections import Counter, defaultdict

from . import reconstruct
from .reconstruct import iso

SESSION_GAP = 30 * 60      # a break longer than this ends an activity session
HANDOFF_MAX = 15 * 60      # one stops, the other starts within this
OVERLAP_AGAINST = 0.30     # share of the shorter active time both were active at once
SMALL_THREAD = 3           # threads with at most this many named actors count as shared use
PROGRAM_MAX_ACTORS = 12    # programs run by more named actors are templates, not identity evidence
NAME_FAMILY_MAX = 40       # numbered-name stems with more names than this are not paired
SWEEP_TOKENS = 4           # a record that uses this many tokens at once may be trying collected keys
MAX_PROPOSALS = 400
HIGH, MEDIUM, LOW = 6, 4, 2

DECISIONS_DIR = os.environ.get("SWARM_TRACER_HOME") or os.path.join(os.path.expanduser("~"), ".swarm-tracer")
SAVE_DECISIONS = True

RULES = [
    {"key": "same_record", "points": "+3 (+1 if 3+ records)", "what": "Both identities used inside one record."},
    {"key": "key_sweep", "points": "+1", "what": f"Both only inside records that use {SWEEP_TOKENS}+ tokens at once (maybe trying collected keys)."},
    {"key": "same_thread", "points": "+2 (+1 if 3+ threads)", "what": f"Both inside one thread with at most {SMALL_THREAD} named actors."},
    {"key": "carried", "points": "+3", "what": "One holds the other's token before that token's first use."},
    {"key": "same_place", "points": "+2", "what": "Both use the same self-chosen place name."},
    {"key": "same_family", "points": "+1", "what": "Both use names from the same self-chosen name or place family."},
    {"key": "numbered_names", "points": "+2 / +1", "what": "Names differ only by trailing digits (stem with 2-5 names: +2; 6-40: +1)."},
    {"key": "handoff", "points": "+2 (1 handoff: +1)", "what": "One stops and the other starts within 15 minutes, without overlap."},
    {"key": "same_programs", "points": "+2 / +1", "what": f"Run the same programs (identical masked code), among programs run by at most {PROGRAM_MAX_ACTORS} named actors."},
    {"key": "messages", "points": "+1", "what": "Messages pass between the two (one may be talking to itself); only when they share no record or thread."},
    {"key": "parallel", "points": "-2", "what": "Active at the same time (overlap 30%+ of the shorter active time), never inside one record."},
    {"key": "different_names", "points": "-1", "what": "Both write self-chosen names in their code, none in common."},
]


# ------------------------------------------------------------------ helpers

DIRECT = {"same_record", "same_thread", "carried"}


def _int(q, key, default):
    try:
        return max(0, int(q.get(key, default)))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a whole number")


def _need(state):
    s = state["session"]
    if not getattr(s, "loaded", False):
        raise LookupError("no dataset loaded")
    return s


def _named_actors(s):
    """Named actors that ran at least one action (the scope of the app's actor counts)."""
    out = set()
    for e in s.events:
        a, ak = s.actor[e.id]
        if ak != "run" and reconstruct.is_action(e, s.pack):
            out.add(a)
    return out


def _stem(name):
    """'Helper57' -> 'helper'; None when the name does not end in digits or the stem is too short."""
    k = re.sub(r"[\d_\-. ]+$", "", name)
    if k == name or len(k) < 3 or not re.search(r"\d$", name):
        return None
    return k.lower()


def _sessions(ts):
    out = []
    for t in sorted(ts):
        if out and t - out[-1][1] <= SESSION_GAP:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [(a, b + 60) for a, b in out]   # one record counts as a minute of activity


def _overlap(sa, sb):
    i = j = 0
    tot = 0.0
    while i < len(sa) and j < len(sb):
        lo, hi = max(sa[i][0], sb[j][0]), min(sa[i][1], sb[j][1])
        if hi > lo:
            tot += hi - lo
        if sa[i][1] < sb[j][1]:
            i += 1
        else:
            j += 1
    return tot


def _handoffs(sa, sb):
    """Adjacent sessions of the two, in time order, where one ends and the other starts soon after."""
    seq = sorted([(a, b, 0) for a, b in sa] + [(a, b, 1) for a, b in sb])
    out = []
    for p, n in zip(seq, seq[1:]):
        if p[2] != n[2] and 0 <= n[0] - p[1] <= HANDOFF_MAX:
            out.append((p[1], n[0], p[2]))
    return out


class _Pair:
    __slots__ = ("same_record", "sweep_records", "threads", "carried", "places", "families", "programs")

    def __init__(self):
        self.same_record, self.sweep_records, self.threads = [], [], []
        self.carried, self.places, self.families, self.programs = [], [], [], []


# ------------------------------------------------------------------ the base computation (cached per session)

def _base(s):
    cached = getattr(s, "_identity_base", None)
    if cached is not None:
        return cached
    named = _named_actors(s)
    times = s.rec["_times"]
    shared = set(s.pack.raw.get("shared_identities", []))
    pairs = defaultdict(_Pair)

    def P(a, b):
        return pairs[(a, b) if a < b else (b, a)]

    # (a) one record, one thread
    for rid, toks in s.rec["_ids"].items():
        tk = sorted(t for t in toks if t in named and t not in shared)
        if len(tk) < 2:
            continue
        for i in range(len(tk)):
            for j in range(i + 1, len(tk)):
                p = P(tk[i], tk[j])
                (p.sweep_records if len(tk) >= SWEEP_TOKENS else p.same_record).append(rid)
    root = s.res["_root"]
    by_thread = defaultdict(set)
    for e in s.events:
        a, ak = s.actor[e.id]
        if ak != "run" and a in named:
            by_thread[root[e.id]].add(a)
    for r, acts in by_thread.items():
        if 2 <= len(acts) <= SMALL_THREAD:
            acts = sorted(acts)
            for i in range(len(acts)):
                for j in range(i + 1, len(acts)):
                    P(acts[i], acts[j]).threads.append(r)

    # (b) carried tokens
    for c in s.rec.get("carried_edges", []):
        if c["from"] in named and c["to"] in named:
            P(c["from"], c["to"]).carried.append(c)

    # (c) self-chosen places and names written in the code
    place_fam = {}
    for fam, rx in s.pack.shared_names:
        place_fam[fam] = rx
    actor_places = defaultdict(lambda: defaultdict(list))     # actor -> place -> record ids
    actor_names = defaultdict(lambda: defaultdict(list))      # actor -> family -> record ids
    if s.pack.shared_names or s.pack.handles_rx:
        from .packs import family_of
        for a in named:
            for rid in s.by_actor.get(a, []):
                e = s.by_id[rid]
                if not reconstruct.is_action(e, s.pack):
                    continue
                for fam, rx in s.pack.shared_names:
                    for m in rx.finditer(e.text):
                        lst = actor_places[a][m.group(0)]
                        if len(lst) < 3:
                            lst.append(rid)
                        lst2 = actor_names[a]["place family " + fam]
                        if len(lst2) < 3:
                            lst2.append(rid)
                if s.pack.handles_rx:
                    for m in s.pack.handles_rx.finditer(e.text):
                        lst = actor_names[a][family_of(m.group(1), s.pack)]
                        if len(lst) < 3:
                            lst.append(rid)
    place_users = defaultdict(list)
    for a, d in actor_places.items():
        for pl in d:
            place_users[pl].append(a)
    for pl, users in place_users.items():
        if 2 <= len(users) <= PROGRAM_MAX_ACTORS:
            users.sort()
            for i in range(len(users)):
                for j in range(i + 1, len(users)):
                    P(users[i], users[j]).places.append(pl)
    fam_users = defaultdict(list)
    for a, d in actor_names.items():
        for f in d:
            fam_users[f].append(a)
    for f, users in fam_users.items():
        if 2 <= len(users) <= PROGRAM_MAX_ACTORS:
            users.sort()
            for i in range(len(users)):
                for j in range(i + 1, len(users)):
                    P(users[i], users[j]).families.append(f)
    stems = defaultdict(list)
    for a in named:
        k = _stem(a)
        if k:
            stems[k].append(a)
    stems = {k: sorted(v) for k, v in stems.items() if len(v) >= 2}
    for k, v in stems.items():
        if len(v) <= NAME_FAMILY_MAX:
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    P(v[i], v[j])   # make sure the pair is scored

    # (e) programs (identical masked code) run by several named actors
    prog_actors = {}
    for x in s.flow.get("_content_spread", s.flow.get("content_spread", [])):
        users = {x["source"]: x["source_record"]}
        for ad in x["adopters"]:
            users.setdefault(ad["actor"], ad["record"])
        users = {a: r for a, r in users.items() if a in named}
        if 2 <= len(users) <= PROGRAM_MAX_ACTORS:
            prog_actors[x["family"]] = users
            us = sorted(users)
            for i in range(len(us)):
                for j in range(i + 1, len(us)):
                    P(us[i], us[j]).programs.append(x["family"])

    # activity sessions
    sess = {}
    for a in named:
        ts = [times[r] for r in s.by_actor.get(a, []) if r in times]
        sess[a] = _sessions(ts)

    base = {"named": named, "pairs": pairs, "stems": stems, "sess": sess, "prog_actors": prog_actors,
            "actor_places": actor_places, "actor_names": actor_names, "place_users": place_users,
            "fam_users": fam_users}
    base["scored"] = [_score(s, base, a, b, p) for (a, b), p in pairs.items()]
    base["scored"] = [x for x in base["scored"] if x["score"] >= LOW]
    base["scored"].sort(key=lambda x: (-x["score"], -len(x["evidence"]), x["a"], x["b"]))
    s._identity_base = base
    return base


def _score(s, base, a, b, p):
    ev, against = [], []

    def add(lst, key, points, text, records=(), **extra):
        lst.append({"key": key, "points": points, "text": text, "records": list(records)[:6], **extra})

    # (a)
    if p.same_record:
        pts = 3 + (1 if len(p.same_record) >= 3 else 0)
        add(ev, "same_record", pts, f"Both used inside {len(p.same_record)} record{'s' if len(p.same_record) != 1 else ''}"
            f" (each record uses 2-3 tokens).", p.same_record)
    elif p.sweep_records:
        add(ev, "key_sweep", 1, f"Both used only inside {len(p.sweep_records)} record{'s' if len(p.sweep_records) != 1 else ''}"
            f" that use {SWEEP_TOKENS}+ tokens at once: maybe one agent trying keys it collected, not its own.", p.sweep_records)
    if p.threads and not p.same_record:
        pts = 2 + (1 if len(p.threads) >= 3 else 0)
        add(ev, "same_thread", pts, f"Both inside {len(p.threads)} small thread{'s' if len(p.threads) != 1 else ''}"
            f" (at most {SMALL_THREAD} named actors each).", p.threads)
    # (b)
    if p.carried:
        c = p.carried[0]
        recs = [r for c in p.carried for r in c["evidence"]]
        add(ev, "carried", 3, " and ".join(f"{c['from']} held {c['to']}'s token in {c['records']} record{'s' if c['records'] != 1 else ''}"
                                           for c in p.carried) + " before that token's first use.", recs)
    # (c)
    if p.places:
        pl = sorted(p.places, key=lambda x: len(base["place_users"][x]))
        recs = []
        for x in pl[:3]:
            recs += base["actor_places"][a][x][:1] + base["actor_places"][b][x][:1]
        add(ev, "same_place", 2, f"Both use the self-chosen place name{'s' if len(pl) != 1 else ''} "
            + ", ".join(pl[:4]) + (f" and {len(pl) - 4} more" if len(pl) > 4 else "")
            + f" (used by {min(len(base['place_users'][x]) for x in pl)} named actors).", recs, places=pl[:8])
    elif p.families:
        f = sorted(p.families, key=lambda x: len(base["fam_users"][x]))
        recs = base["actor_names"][a][f[0]][:2] + base["actor_names"][b][f[0]][:2]
        add(ev, "same_family", 1, "Both write names from the same family: " + ", ".join(f[:4])
            + f" (written by {len(base['fam_users'][f[0]])} named actors).", recs)
    sa, sb = _stem(a), _stem(b)
    if sa and sa == sb:
        n = len(base["stems"][sa])
        pts = 2 if n <= 5 else 1
        add(ev, "numbered_names", pts, f"Names differ only by trailing digits: {n} named actors share the stem '{sa}'.",
            [s.by_actor[a][0], s.by_actor[b][0]], stem=sa, stem_size=n)
    # (d)
    A, B = base["sess"].get(a, []), base["sess"].get(b, [])
    ov = _overlap(A, B) if A and B else 0.0
    act = min(sum(y - x for x, y in A), sum(y - x for x, y in B)) if A and B else 0
    share = ov / act if act else 0.0
    hand = _handoffs(A, B) if A and B else []
    if hand and share < 0.10:
        pts = 2 if len(hand) >= 2 else 1
        h = hand[0]
        add(ev, "handoff", pts, f"{len(hand)} handoff{'s' if len(hand) != 1 else ''}: one stops and the other starts within "
            f"{HANDOFF_MAX // 60} minutes (first at {iso(h[1])}); they are active at the same time for {round(share * 100)}% of the shorter one's active time.",
            [], handoffs=len(hand), overlap_share=round(share, 3))
    # (e)
    if p.programs:
        sizes = sorted(len(base["prog_actors"][f]) for f in p.programs)
        pts = 2 if (len(p.programs) >= 2 or sizes[0] <= 3) else 1
        recs = []
        for f in sorted(p.programs, key=lambda f: len(base["prog_actors"][f]))[:3]:
            recs += [base["prog_actors"][f][a], base["prog_actors"][f][b]]
        add(ev, "same_programs", pts, f"Both run {len(p.programs)} program{'s' if len(p.programs) != 1 else ''} "
            f"(identical masked code) that only {sizes[0]}{'-' + str(sizes[-1]) if sizes[-1] != sizes[0] else ''} named actors run.",
            recs, programs=len(p.programs))
    # (f)
    ab, ba = s.by_pair.get((a, b), []), s.by_pair.get((b, a), [])
    if (ab or ba) and not (p.same_record or p.threads):   # inside one thread a message is implied, not new evidence
        recs = [d["write_id"] for d in (ab + ba)[:2]] + [d["read_id"] for d in (ab + ba)[:2]]
        add(ev, "messages", 1, f"{len(ab)} message{'s' if len(ab) != 1 else ''} from {a} to {b}, {len(ba)} back"
            " (one may be talking to itself).", recs)
    # against
    if share >= OVERLAP_AGAINST and not p.same_record and ov >= 600:
        add(against, "parallel", -2, f"Active at the same time: their sessions overlap for {round(share * 100)}% of the shorter one's "
            f"active time ({round(ov / 3600, 1)} h), and no record uses both.", [], overlap_share=round(share, 3))
    na = {k for k in base["actor_names"].get(a, {}) if not k.startswith("place family ")}
    nb = {k for k in base["actor_names"].get(b, {}) if not k.startswith("place family ")}
    if na and nb and not (na & nb):
        add(against, "different_names", -1, f"They write different self-chosen names: {', '.join(sorted(na)[:3])} vs {', '.join(sorted(nb)[:3])}.",
            base["actor_names"][a][sorted(na)[0]][:1] + base["actor_names"][b][sorted(nb)[0]][:1])
    score = sum(x["points"] for x in ev) + sum(x["points"] for x in against)
    conf = "high" if score >= HIGH else "medium" if score >= MEDIUM else "low" if score >= LOW else None
    # Measured on simulated swarms with known agents (agenttrace.validation): pairs resting only on
    # coordination evidence (a shared place, handoffs, shared programs, names) were the same agent about
    # 4% of the time, while pairs with direct evidence were right in every case. So without direct
    # evidence a pair is never more than "low".
    if conf in ("high", "medium") and not any(x["key"] in DIRECT for x in ev):
        conf = "low"
    return {"a": a, "b": b, "score": score, "confidence": conf, "evidence": ev, "against": against,
            "kinds": len(ev)}


# ------------------------------------------------------------------ decisions

def _decision_path(s):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", s.name or "dataset")[:80]
    return os.path.join(DECISIONS_DIR, f"decisions-{name}.json")


def _decisions(s):
    d = getattr(s, "_id_decisions", None)
    if d is None:
        d = {}
        try:
            with open(_decision_path(s), encoding="utf-8") as f:
                for x in json.load(f):
                    d[tuple(sorted((x["a"], x["b"])))] = x["decision"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        s._id_decisions = d
    return d


def _save(s):
    if not SAVE_DECISIONS:
        return None
    try:
        os.makedirs(DECISIONS_DIR, exist_ok=True)
        path = _decision_path(s)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"a": a, "b": b, "decision": v} for (a, b), v in sorted(s._id_decisions.items())], f, indent=1)
        return path
    except OSError:
        return None


# ------------------------------------------------------------------ groups and the estimate

def _components(nodes, edges):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = defaultdict(list)
    for n in nodes:
        comp[find(n)].append(n)
    return list(comp.values())


def identity(s, actor=None, limit=MAX_PROPOSALS):
    base = _base(s)
    dec = _decisions(s)
    named = base["named"]
    props = []
    for x in base["scored"]:
        d = dec.get((x["a"], x["b"]) if x["a"] < x["b"] else (x["b"], x["a"]))
        props.append({**x, "decision": d})
    scored_keys = {(x["a"], x["b"]) for x in props}
    # accepted pairs the rules did not propose still count
    for (a, b), d in dec.items():
        if (a, b) not in scored_keys and a in named and b in named:
            props.append({"a": a, "b": b, "score": 0, "confidence": None, "evidence": [], "against": [], "kinds": 0, "decision": d})

    def merged(levels):
        return [(x["a"], x["b"]) for x in props
                if x["decision"] == "accept" or (x["decision"] != "reject" and x["confidence"] in levels)]

    mid = _components(named, merged({"high"}))
    lo = _components(named, merged({"high", "medium"}))
    hi = _components(named, merged(set()))
    pair_of = {}
    for x in props:
        pair_of.setdefault(x["a"], []).append(x)
        pair_of.setdefault(x["b"], []).append(x)
    groups = []
    for g in mid:
        if len(g) < 2:
            continue
        g = sorted(g, key=lambda a: (-len(s.by_actor.get(a, [])), a))
        gs = set(g)
        links = [x for x in props if x["a"] in gs and x["b"] in gs and
                 (x["decision"] == "accept" or (x["decision"] != "reject" and x["confidence"] == "high"))]
        groups.append({"actors": g, "records": sum(len(s.by_actor.get(a, [])) for a in g),
                       "links": [{"a": x["a"], "b": x["b"], "score": x["score"], "confidence": x["confidence"],
                                  "decision": x["decision"]} for x in links]})
    groups.sort(key=lambda g: (-len(g["actors"]), -g["records"]))
    conf = Counter(x["confidence"] for x in props if x["decision"] is None and x["confidence"])
    shared = s.pack.raw.get("shared_identities", [])
    est = {"named_actors": len(named), "estimated_agents": len(mid), "low": len(lo), "high": len(hi),
           "shared_keys": len(shared), "unattributed_actions": s.summary()["actions"]["unattributed"],
           "proposals": len(props), "by_confidence": dict(conf),
           "accepted": sum(1 for v in dec.values() if v == "accept"),
           "rejected": sum(1 for v in dec.values() if v == "reject")}
    name_families = sorted(({"stem": k, "names": len(v), "actors": v[:12]} for k, v in base["stems"].items()),
                           key=lambda r: -r["names"])[:30]
    if actor:
        mine = [x for x in props if actor in (x["a"], x["b"])]
        mine.sort(key=lambda x: (x["decision"] != "accept", x["decision"] == "reject", -x["score"]))
        grp = next((g for g in groups if actor in g["actors"]), None)
        return {"actor": actor, "proposals": mine[:20], "proposals_total": len(mine), "group": grp,
                "role": roles(s)["by_actor"].get(actor)}
    return {"estimate": est, "proposals": props[:limit], "proposals_total": len(props), "groups": groups[:100],
            "groups_total": len(groups), "name_families": name_families, "rules": RULES,
            "thresholds": {"high": HIGH, "medium": MEDIUM, "low": LOW},
            "decisions_file": _decision_path(s) if SAVE_DECISIONS else None}


def decide(s, a, b, decision):
    if decision not in ("accept", "reject", "clear", None, ""):
        raise ValueError("decision must be accept, reject or clear")
    named = _base(s)["named"]
    for x in (a, b):
        if x not in named:
            raise ValueError(f"no named actor {x}")
    if a == b:
        raise ValueError("a and b must differ")
    key = (a, b) if a < b else (b, a)
    dec = _decisions(s)
    if decision in ("clear", None, ""):
        dec.pop(key, None)
    else:
        dec[key] = decision
    path = _save(s)
    return {"ok": True, "a": key[0], "b": key[1], "decision": dec.get(key), "saved_to": path,
            "estimate": identity(s)["estimate"]}


# ------------------------------------------------------------------ roles

def _betweenness(nodes, adj, max_sources=300):
    """Brandes on the undirected graph; sampled (evenly spaced sources) when it is large."""
    ids = sorted(nodes)
    idx = {n: i for i, n in enumerate(ids)}
    A = [[idx[w] for w in adj[n]] for n in ids]
    n = len(ids)
    cb = [0.0] * n
    sources = list(range(n))
    scale = 1.0
    if n > max_sources:
        step = n / max_sources
        sources = [int(i * step) for i in range(max_sources)]
        scale = n / max_sources
    for src in sources:
        sigma = {src: 1.0}
        dist = {src: 0}
        pred = defaultdict(list)
        order = []
        q = [src]
        h = 0
        while h < len(q):
            v = q[h]
            h += 1
            order.append(v)
            for w in A[v]:
                if w not in dist:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] = sigma.get(w, 0.0) + sigma[v]
                    pred[w].append(v)
        delta = defaultdict(float)
        for w in reversed(order):
            for v in pred[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != src:
                cb[w] += delta[w]
    pairs = (n - 1) * (n - 2) / 2 if n > 2 else 1
    return {ids[i]: (cb[i] * scale / 2) / pairs for i in range(n)}, n > max_sources


def _pctl(vals, q):
    v = sorted(vals)
    if not v:
        return 0
    return v[min(len(v) - 1, int(q * len(v)))]


ROLE_RULES = [
    {"role": "coordinator", "rule": "Sends to many named actors (out-partners in the top 5% and at least 5), sends at least as much as it receives, and most of its sending is in the first half of the dated span."},
    {"role": "relay", "rule": "Sits on many shortest message routes (broker share in the top 5%, above 0) and both hears from and sends to 2+ named actors."},
    {"role": "recruiter", "rule": "First named actor ever to message many others (first contacts in the top 5% and at least 3)."},
    {"role": "worker", "rule": "Receives at least as many messages as it sends and runs at least the median number of actions of actors with messages."},
    {"role": "participant", "rule": "Sends or receives messages but fits none of the patterns above."},
    {"role": "lone", "rule": "No messages with any named actor."},
]


def roles(s):
    cached = getattr(s, "_roles", None)
    if cached is not None:
        return cached
    named = _named_actors(s)
    dels = [d for d in s.flow["_deliveries"] if d["from"] in named and d["to"] in named and d["from"] != d["to"]]
    sent, recv = Counter(), Counter()
    outp, inp = defaultdict(set), defaultdict(set)
    send_times = defaultdict(list)
    adj = defaultdict(set)
    for d in dels:
        sent[d["from"]] += 1
        recv[d["to"]] += 1
        outp[d["from"]].add(d["to"])
        inp[d["to"]].add(d["from"])
        if d.get("write_time") is not None:
            send_times[d["from"]].append(d["write_time"])
        adj[d["from"]].add(d["to"])
        adj[d["to"]].add(d["from"])
    first_contact = Counter()
    seen = set()
    for d in sorted(dels, key=lambda d: (d["read_time"] if d["read_time"] is not None else float("inf"))):
        if d["to"] not in seen:
            seen.add(d["to"])
            first_contact[d["from"]] += 1
    btw, sampled = _betweenness(set(adj), adj) if adj else ({}, False)
    times = s.rec["_times"]
    all_t = list(times.values())
    t0, t1 = (min(all_t), max(all_t)) if all_t else (None, None)
    mid_t = (t0 + t1) / 2 if all_t else None
    actions = Counter()
    for e in s.events:
        a, ak = s.actor[e.id]
        if a in named and reconstruct.is_action(e, s.pack):
            actions[a] += 1
    msg_actors = [a for a in named if sent[a] or recv[a]]
    th = {"out_partners": max(5, _pctl([len(outp[a]) for a in msg_actors], 0.95)),
          "broker_share": _pctl([btw.get(a, 0) for a in msg_actors], 0.95),
          "first_contacts": max(3, _pctl([first_contact[a] for a in msg_actors], 0.95)),
          "worker_actions": _pctl([actions[a] for a in msg_actors], 0.5)}
    rank = {a: i + 1 for i, a in enumerate(sorted((a for a in btw if btw[a] > 0), key=lambda a: -btw[a]))}
    rows = {}
    for a in named:
        st = send_times.get(a, [])
        early = (sum(1 for t in st if t <= mid_t) / len(st)) if (st and mid_t is not None) else None
        r = {"actor": a, "sent": sent[a], "received": recv[a], "out_partners": len(outp[a]), "in_partners": len(inp[a]),
             "partners": len(outp[a] | inp[a]), "first_contacts": first_contact[a],
             "broker_share": round(btw.get(a, 0.0), 5), "broker_rank": rank.get(a),
             "actions": actions[a], "early_share": round(early, 3) if early is not None else None,
             "first_send": iso(min(st)) if st else None}
        if not (sent[a] or recv[a]):
            role, why = "lone", "No messages with any named actor."
        elif len(outp[a]) >= th["out_partners"] and sent[a] >= recv[a] and early is not None and early >= 0.5:
            role, why = "coordinator", (f"Sent {sent[a]} messages to {len(outp[a])} named actors (threshold {th['out_partners']}), "
                                        f"received {recv[a]}; {round(early * 100)}% of its sending in the first half of the dated span.")
        elif btw.get(a, 0) > 0 and btw.get(a, 0) >= th["broker_share"] and len(inp[a]) >= 2 and len(outp[a]) >= 2:
            role, why = "relay", (f"On {pct_s(btw[a])} of shortest routes (rank #{rank.get(a)}); hears from {len(inp[a])} "
                                  f"and sends to {len(outp[a])} named actors.")
        elif first_contact[a] >= th["first_contacts"]:
            role, why = "recruiter", (f"First named actor ever to message {first_contact[a]} others (threshold {th['first_contacts']}).")
        elif recv[a] >= sent[a] and actions[a] >= th["worker_actions"]:
            role, why = "worker", (f"Received {recv[a]} messages, sent {sent[a]}; ran {actions[a]} actions "
                                   f"(median among messaging actors {th['worker_actions']}).")
        else:
            role, why = "participant", f"Sent {sent[a]}, received {recv[a]} messages with {len(outp[a] | inp[a])} named actors."
        r["role"], r["why"] = role, why
        rows[a] = r
    order = {"coordinator": 0, "relay": 1, "recruiter": 2, "worker": 3, "participant": 4, "lone": 5}
    lst = sorted(rows.values(), key=lambda r: (order[r["role"]], -(r["sent"] + r["received"]), -r["actions"], r["actor"]))
    out = {"counts": dict(Counter(r["role"] for r in lst)), "rows": lst, "by_actor": rows, "thresholds": th,
           "rules": ROLE_RULES, "named_actors": len(named), "messages_between_named": len(dels),
           "broker_sampled": sampled}
    s._roles = out
    return out


def pct_s(x):
    return f"{x * 100:.1f}%" if x >= 0.001 else f"{x * 100:.2f}%"


# ------------------------------------------------------------------ routes

def _get_identity(state, q):
    s = _need(state)
    return identity(s, actor=q.get("actor") or None, limit=_int(q, "limit", MAX_PROPOSALS))


def _get_roles(state, q):
    s = _need(state)
    r = roles(s)
    rows = r["rows"]
    role = q.get("role")
    if role:
        rows = [x for x in rows if x["role"] == role]
    off, lim = _int(q, "offset", 0), _int(q, "limit", 500)
    return {**{k: v for k, v in r.items() if k not in ("rows", "by_actor")}, "total": len(rows), "offset": off,
            "rows": rows[off:off + lim]}


def _post_decide(state, q, body):
    s = _need(state)
    try:
        d = json.loads(body or b"{}")
    except ValueError:
        raise ValueError("body must be JSON")
    if not isinstance(d, dict) or not d.get("a") or not d.get("b"):
        raise ValueError("need a, b and decision")
    return decide(s, d["a"], d["b"], d.get("decision"))


GET = {"identity": _get_identity, "roles": _get_roles}
POST = {"identity_decide": _post_decide}

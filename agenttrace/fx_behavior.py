"""Forensics, "How agents behaved": program evolution, stage ladder, lead-lag, anomalies, story.

Every result is counted from the loaded Session and cached on it (s._fx_beh), so each endpoint
costs one computation per dataset. Nothing is specific to one dataset: stages come from the pack's
behaviors (and its optional intent_stages), actors from the session's actor index.

  evolution  near-duplicate programs: masked text, 4-token shingles, one-permutation MinHash
             (128 bins) and LSH bands; pairs whose estimated Jaccard >= 0.8 form a version cluster.
             Inside a cluster each distinct masked text is a version, linked to its most similar
             earlier version, with a line diff on demand.
  stages     each action's stages (its evidence tags' stages and its intent's stage); per actor the
             first time at each stage; the swarm's first time and how many actors reached it.
  leadlag    hourly activity of the most active named actors, cross-correlated at lags -6..+6 h.
  anomalies  per actor, hours that break its own pattern (bursts, first new place / intent, first
             harmful action, first message).
  story      a chronology built from the above and the replay, sentence by sentence with record ids.
"""
import bisect
import difflib
import hashlib
import math
import re
import threading
from collections import Counter, defaultdict

from . import insight, messages, reconstruct

HOUR = 3600.0
iso = reconstruct.iso

# a sensible order for the stages packs use; stages not listed follow, by the swarm's first time
STAGE_ORDER = ["reconnaissance", "collection", "network", "tracking", "evaluation_gaming", "credential_access", "credential",
               "credential_use", "execution", "supply_chain", "obfuscation", "evasion", "persistence", "coordination",
               "exfiltration", "cover_up", "moderation", "reporting"]

# when the pack gives no intent_stages: guesses from an intent's name (harmful intents only, plus
# recon-like names), first match wins
_INTENT_GUESS = [("reconnaissance", ("probe", "recon", "scan", "enumerat")),
                 ("credential_access", ("secret", "credential", "cred", "token", "password", "metadata", "key")),
                 ("cover_up", ("delete", "hide", "wipe", "cover")),
                 ("persistence", ("recreate", "persist", "replicat", "cron")),
                 ("evasion", ("proxy", "evade", "evasion", "obfusc")),
                 ("coordination", ("board", "handoff", "message", "mailbox", "coordinat")),
                 ("supply_chain", ("registry", "package", "docker", "image")),
                 ("exfiltration", ("write", "upload", "send", "post", "exfil", "data_out", "moves_data", "push", "commit")),
                 ("execution", ("shell", "exec", "run", "kube", "api", "deploy")),
                 ("reconnaissance", ("read", "search", "list", "fetch"))]
_RECON_ONLY = ("probe", "recon", "scan", "enumerat")


def _cache(s):
    c = getattr(s, "_fx_beh", None)
    if c is None:
        c = s._fx_beh = {}
    return c


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _named(s, rid):
    a, ak = s.actor[rid]
    return a if ak != "run" else None


def _actions(s):
    """Action record ids in time order (dated first, then undated in file order)."""
    c = _cache(s)
    if "actions" not in c:
        times = s.rec["_times"]
        acts = [e.id for e in s.events if reconstruct.is_action(e, s.pack)]
        c["actions"] = sorted(acts, key=lambda r: (times.get(r) is None, times.get(r) or 0, s.order[r]))
    return c["actions"]


def _hour(t):
    return int(math.floor(t / HOUR))


def _hiso(h):
    return iso(h * HOUR)[:13]


# ================================================================== 1. program evolution

K = 128                 # MinHash bins (one-permutation hashing)
BANDS, ROWS = 16, 8      # LSH: 16 bands of 8 bins; pairs sharing a band are compared
SHINGLE = 4             # tokens per shingle
MAX_TOKENS = 600        # texts are compared on their first 600 masked tokens
MIN_TOKENS = 12         # shorter texts are too generic (as for exact program families)
JACCARD = 0.8
BUCKET_CAP = 12         # in a very common LSH bucket, each member is compared with the 12 before it
MAX_PARENT_SCAN = 400   # versions per cluster that get a parent (the earliest 400)
M64 = (1 << 64) - 1


def _tok_hash(tok, memo):
    h = memo.get(tok)
    if h is None:
        h = memo[tok] = int.from_bytes(hashlib.blake2b(tok.encode("utf-8", "replace"), digest_size=8).digest(), "little")
    return h


def _signature(toks, memo):
    """One-permutation MinHash: each distinct shingle is hashed once; its low 7 bits pick one of the
    128 bins, the rest is its value, and each bin keeps its smallest value."""
    ids = [_tok_hash(t, memo) for t in toks[:MAX_TOKENS]]
    if len(ids) < SHINGLE:
        ids = ids + [0] * (SHINGLE - len(ids))
    shingles = set(map(hash, zip(*(ids[i:] for i in range(SHINGLE)))))   # tuples of ints hash the same in every process
    ms = sorted(((sh & M64) * 0x9E3779B97F4A7C15 + 0x632BE59BD9B4E019) & M64 for sh in shingles)
    sig = [None] * K
    left = K
    for m in ms:                       # ascending, so the first value seen in a bin is its minimum
        b = m & 127
        if sig[b] is None:
            sig[b] = m >> 7
            left -= 1
            if not left:
                break
    if left:   # densify: an empty bin borrows from the next filled one, so short texts still band
        filled = [i for i in range(K) if sig[i] is not None]
        out = sig[:]
        for i in range(K):
            if sig[i] is None:
                j = filled[bisect.bisect_left(filled, i) % len(filled)]
                out[i] = sig[j] ^ (i * 0x9E3779B1)
        sig = out
    return sig


LANE = 8
_LO_MASK = int(("0" + "1" * (LANE - 1)) * K, 2)      # every lane's low bits
_HI_MASK = int(("1" + "0" * (LANE - 1)) * K, 2)      # every lane's top bit


def _pack(sig):
    """The signature as one big int of 8-bit lanes (a 1-in-256 chance two different values look equal), so two signatures compare in a few int operations."""
    x = 0
    for v in sig:
        x = (x << LANE) | (v & 0xFF)
    return x


def _sim(a, b):
    """Share of bins that agree (an estimate of the Jaccard similarity of the two shingle sets)."""
    x = a ^ b
    nz = (((x & _LO_MASK) + _LO_MASK) | x) & _HI_MASK      # top bit set in every lane that differs
    return 1 - _popcount(nz) / K


_popcount = getattr(int, "bit_count", None) or (lambda x: bin(x).count("1"))


def evolution(s):
    c = _cache(s)
    if "evolution" in c:
        return c["evolution"]
    times = s.rec["_times"]
    acts = _actions(s)
    versions = {}          # masked text hash -> version
    order = []
    for rid in acts:
        n = messages._norm(s.by_id[rid].text[:40000])
        toks = messages.TOKEN.findall(n)
        if len(toks) < MIN_TOKENS:
            continue
        key = hashlib.sha1(n.encode("utf-8", "replace")).hexdigest()[:12]
        v = versions.get(key)
        if v is None:
            v = versions[key] = {"key": key, "records": [], "toks": toks}
            order.append(key)
        v["records"].append(rid)
    memo = {}
    full = {k: _signature(versions[k]["toks"], memo) for k in order}
    for k in order:
        del versions[k]["toks"]
    sigs = {k: _pack(v) for k, v in full.items()}
    # LSH
    parent = {k: k for k in order}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    compared = linked = 0
    tried = set()
    for b in range(BANDS):
        buckets = defaultdict(list)
        for k in order:
            buckets[hash(tuple(full[k][b * ROWS:(b + 1) * ROWS]))].append(k)
        for lst in buckets.values():
            if len(lst) < 2:
                continue
            for i in range(1, len(lst)):
                ki = lst[i]
                for j in range(max(0, i - BUCKET_CAP), i):
                    kj = lst[j]
                    ri, rj = find(ki), find(kj)
                    if ri == rj or (ki, kj) in tried:
                        continue
                    tried.add((ki, kj))
                    compared += 1
                    if _sim(sigs[ki], sigs[kj]) >= JACCARD:
                        parent[ri] = rj
                        linked += 1
    groups = defaultdict(list)
    for k in order:
        groups[find(k)].append(k)
    clusters = []
    for root, keys in groups.items():
        if len(keys) < 2:
            continue
        clusters.append(_cluster(s, keys, versions, sigs))
    clusters = [x for x in clusters if x]
    clusters.sort(key=lambda x: (-x["actors"], -x["versions_total"], -x["records"]))
    for i, x in enumerate(clusters):
        x["id"] = i
    out = {"clusters": clusters, "versions_total": len(order), "actions": len(acts),
           "compared_pairs": compared, "linked_pairs": linked,
           "method": {"shingle_tokens": SHINGLE, "max_tokens": MAX_TOKENS, "min_tokens": MIN_TOKENS, "bins": K,
                      "bands": BANDS, "rows": ROWS, "jaccard": JACCARD, "bucket_cap": BUCKET_CAP,
                      "max_parent_scan": MAX_PARENT_SCAN}}
    c["evolution"] = out
    return out


def _cluster(s, keys, versions, sigs):
    times = s.rec["_times"]
    vs = []
    for k in keys:
        recs = versions[k]["records"]
        first = recs[0]       # records are in time order already
        t = times.get(first)
        actors = []
        for r in recs:
            a = _named(s, r)
            if a and a not in actors:
                actors.append(a)
        vs.append({"key": k, "first_record": first, "t": t, "time": iso(t) if t is not None else None,
                   "introduced_by": s.actor[first][0], "introducer_named": s.actor[first][1] != "run",
                   "records": len(recs), "named_actors": actors})
    vs.sort(key=lambda v: (v["t"] is None, v["t"] or 0, s.order[v["first_record"]]))
    for i, v in enumerate(vs):
        v["n"] = i
        v["parent"] = None
        v["similarity"] = None
        if 0 < i < MAX_PARENT_SCAN:
            best, bj = -1.0, None
            for j in range(min(i, MAX_PARENT_SCAN)):
                x = _sim(sigs[v["key"]], sigs[vs[j]["key"]])
                if x > best:
                    best, bj = x, j
            v["parent"], v["similarity"] = bj, round(best, 3)
    # who introduced each version, and whether later actors adopted it
    all_actors = set()
    for v in vs:
        intro = v["introduced_by"]
        v["adopted_by"] = [a for a in v["named_actors"] if a != intro]
        all_actors.update(v["named_actors"])
        par = vs[v["parent"]] if v["parent"] is not None else None
        v["changed_by_other"] = bool(par and par["introduced_by"] != intro)
        del v["t"]
    roots = sum(1 for v in vs if v["parent"] is None)
    adopted = sum(1 for v in vs[1:] if v["adopted_by"])
    t0 = next((v["time"] for v in vs if v["time"]), None)
    return {"versions_total": len(vs), "versions": vs[:MAX_PARENT_SCAN], "truncated": len(vs) > MAX_PARENT_SCAN,
            "records": sum(v["records"] for v in vs), "actors": len(all_actors), "first_time": t0,
            "later_versions_adopted": adopted, "roots": roots,
            "what": insight.program_gist(s, vs[0]["first_record"])}


_STMT = re.compile(r"(?<=[;{}])\s*")


def _lines(text):
    """Masked lines for the diff; a long line (minified code) is broken after each ; { or } so a change
    shows as the statement it touched, not the whole line."""
    out = []
    for x in text[:40000].splitlines():
        x = messages._norm(x)
        if not x:
            continue
        if len(x) > 160:
            out.extend(p for p in _STMT.split(x) if p.strip())
        else:
            out.append(x)
    return out


def evolution_diff(s, cid, n):
    ev = evolution(s)
    if not (0 <= cid < len(ev["clusters"])):
        raise LookupError("no such cluster")
    vs = ev["clusters"][cid]["versions"]
    if not (0 <= n < len(vs)):
        raise LookupError("no such version")
    v = vs[n]
    if v["parent"] is None:
        return {"cluster": cid, "version": n, "parent": None, "diff": [], "added": 0, "removed": 0}
    p = vs[v["parent"]]
    a, b = _lines(s.by_id[p["first_record"]].text), _lines(s.by_id[v["first_record"]].text)
    diff = list(difflib.unified_diff(a, b, lineterm="", n=1))[2:]
    added = sum(1 for x in diff if x.startswith("+"))
    removed = sum(1 for x in diff if x.startswith("-"))
    cap = 220
    return {"cluster": cid, "version": n, "parent": v["parent"], "parent_record": p["first_record"],
            "record": v["first_record"], "similarity": v["similarity"], "added": added, "removed": removed,
            "diff": [x[:400] for x in diff[:cap]], "diff_total": len(diff), "truncated": len(diff) > cap}


def evolution_summary(s, limit=60):
    ev = evolution(s)
    rows = []
    for x in ev["clusters"][:limit]:
        rows.append({k: x[k] for k in ("id", "versions_total", "records", "actors", "first_time", "later_versions_adopted",
                                       "roots", "what", "truncated")}
                    | {"introducers": len({v["introduced_by"] for v in x["versions"]})})
    return {"clusters": rows, "clusters_total": len(ev["clusters"]), "versions_total": ev["versions_total"],
            "actions": ev["actions"], "method": ev["method"], "compared_pairs": ev["compared_pairs"]}


# ================================================================== 2. stage ladder

def intent_stages(pack):
    """intent -> stage: the pack's intent_stages, else a behavior of the same name, else a guess from the
    name for harmful intents (and recon-like names for the others). Intents without one have no stage."""
    given = dict(pack.raw.get("intent_stages") or {})
    by_tag = {b.name: b.stage for b in pack.behaviors}
    out, how = {}, {}
    for name, _ in pack.intents:
        if name in given:
            out[name], how[name] = given[name], "pack"
            continue
        if name in by_tag:
            out[name], how[name] = by_tag[name], "behavior of the same name"
            continue
        low = name.lower()
        harmful = name in pack.harm
        for stage, keys in _INTENT_GUESS:
            if any(k in low for k in keys) and (harmful or any(k in low for k in _RECON_ONLY)):
                out[name], how[name] = stage, "guessed from the name"
                break
        else:
            if harmful:
                out[name], how[name] = "harmful_action", "harmful, no stage given"
    return out, how


def _stage_rank(stages, first_t):
    known = {k: i for i, k in enumerate(STAGE_ORDER)}
    return sorted(stages, key=lambda g: (g not in known, known.get(g, 0), first_t.get(g) is None, first_t.get(g) or 0, g))


def stages(s, top=15):
    c = _cache(s)
    if "stages" in c:
        return c["stages"]
    times, intents, ev = s.rec["_times"], s.rec["_intents"], s.res["_evidence"]
    tstage = {b.name: b.stage for b in s.pack.behaviors if not b.context}
    istage, ihow = intent_stages(s.pack)
    swarm = {}                       # stage -> {first record, time, actor, records, actors}
    per = defaultdict(dict)          # actor -> stage -> (t, rid)
    counts, actor_sets, undated = Counter(), defaultdict(set), Counter()
    via = defaultdict(Counter)       # stage -> what put actions there (tag or intent)
    for rid in _actions(s):
        st = {}
        for g in ev[rid]:
            if g in tstage:
                st.setdefault(tstage[g], "tag:" + g)
        it = intents.get(rid)
        if it in istage:
            st.setdefault(istage[it], "intent:" + it)
        if not st:
            continue
        t = times.get(rid)
        a = _named(s, rid)
        for g, why in st.items():
            counts[g] += 1
            via[g][why] += 1
            if a:
                actor_sets[g].add(a)
            if t is None:
                undated[g] += 1
                continue
            if g not in swarm:          # actions are in time order
                swarm[g] = {"stage": g, "time": iso(t), "t": t, "record": rid, "actor": s.actor[rid][0]}
            if a and g not in per[a]:
                per[a][g] = (t, rid)
    order = _stage_rank(set(counts), {g: x["t"] for g, x in swarm.items()})
    rows = []
    for g in order:
        x = swarm.get(g, {})
        named_first = None
        if per:
            fs = [(v[g][0], a, v[g][1]) for a, v in per.items() if g in v]
            if fs:
                named_first = min(fs)
        rows.append({"stage": g, "records": counts[g], "undated": undated[g], "actors": len(actor_sets[g]),
                     "first_time": x.get("time"), "first_record": x.get("record"), "first_actor": x.get("actor"),
                     "first_named_actor": named_first[1] if named_first else None,
                     "first_named_record": named_first[2] if named_first else None,
                     "via": [{"what": k, "n": n} for k, n in via[g].most_common(4)]})
    climbers = sorted(per.items(), key=lambda kv: (-len(kv[1]), min(t for t, _ in kv[1].values())))
    actors = []
    for a, d in climbers:
        steps = sorted(((t, g, rid) for g, (t, rid) in d.items()))
        actors.append({"actor": a, "stages": len(d),
                       "steps": [{"stage": g, "time": iso(t), "record": rid} for t, g, rid in steps]})
    out = {"stages": rows, "actors": actors[:200], "actors_total": len(actors), "top": top,
           "intent_stages": [{"intent": k, "stage": v, "how": ihow[k]} for k, v in istage.items()],
           "tag_stages": [{"tag": b.name, "stage": b.stage} for b in s.pack.behaviors if not b.context],
           "dated": any(r["first_time"] for r in rows)}
    c["stages"] = out
    return out


# ================================================================== 3. lead-lag

LAGS = 6
TOP_ACTORS = 40
MIN_OVERLAP = 6


def _hourly_named(s):
    c = _cache(s)
    if "hourly" not in c:
        times = s.rec["_times"]
        hourly = defaultdict(Counter)
        total = Counter()
        for rid in _actions(s):
            a = _named(s, rid)
            if not a:
                continue
            total[a] += 1
            t = times.get(rid)
            if t is not None:
                hourly[a][_hour(t)] += 1
        c["hourly"] = (hourly, total)
    return c["hourly"]


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def leadlag(s, top=TOP_ACTORS):
    c = _cache(s)
    if "leadlag" in c:
        return c["leadlag"]
    hourly, total = _hourly_named(s)
    cand = sorted((a for a in hourly if hourly[a]), key=lambda a: (-sum(hourly[a].values()), a))[:top]
    spans = {a: (min(hourly[a]), max(hourly[a])) for a in cand}
    pairs = []
    considered = 0
    for i, a in enumerate(cand):
        for b in cand[i + 1:]:
            ha, hb = hourly[a], hourly[b]
            both = sum(1 for h in ha if h in hb)
            considered += 1
            if both < MIN_OVERLAP:
                continue
            lo = max(spans[a][0], spans[b][0]) - LAGS
            hi = min(spans[a][1], spans[b][1]) + LAGS
            # hour-to-hour changes of log(1 + actions): a shared rise or fall over the whole window
            # (a trend) would otherwise correlate at every lag
            ra = [math.log1p(ha.get(h, 0)) for h in range(lo - LAGS - 1, hi + LAGS + 1)]
            rb = [math.log1p(hb.get(h, 0)) for h in range(lo - LAGS - 1, hi + LAGS + 1)]
            xa = [y - x for x, y in zip(ra, ra[1:])]
            xb = [y - x for x, y in zip(rb, rb[1:])]
            n = hi - lo + 1
            res = {}
            for k in range(-LAGS, LAGS + 1):
                # a at hour h against b at hour h + k: k > 0 means b moves k hours after a
                r = _corr(xa[LAGS:LAGS + n], xb[LAGS + k:LAGS + k + n])
                if r is not None:
                    res[k] = r
            if not res:
                continue
            best = max(res, key=lambda k: (res[k], -abs(k)))
            r0 = res.get(0)
            # a leader is flagged when the best lag is not zero, not at the edge of the range (the peak may lie
            # beyond it), the correlation there is at least 0.3 and clearly above the same-hour one
            # and above 2/sqrt(hours), about the level pure noise reaches one time in twenty
            noise = 2 / math.sqrt(n)
            lead = 0 < abs(best) < LAGS and res[best] >= max(0.3, noise) and (r0 is None or res[best] - r0 >= 0.1)
            leader, follower = (a, b) if best > 0 else (b, a)
            pairs.append({"a": a, "b": b, "best_lag": best, "r": round(res[best], 3), "r0": round(r0, 3) if r0 is not None else None,
                          "overlap_hours": both, "window_hours": n, "noise": round(noise, 3), "flag": lead,
                          "leader": leader if lead else None, "follower": follower if lead else None,
                          "lag_hours": abs(best), "curve": [round(res.get(k, 0), 3) for k in range(-LAGS, LAGS + 1)]})
    pairs.sort(key=lambda p: (-p["flag"], -p["r"]))
    lead_n, follow_n = Counter(), Counter()
    for p in pairs:
        if p["flag"]:
            lead_n[p["leader"]] += 1
            follow_n[p["follower"]] += 1
    roles = []
    for a in cand:
        L, F = lead_n.get(a, 0), follow_n.get(a, 0)
        if L or F:
            roles.append({"actor": a, "leads": L, "follows": F,
                          "role": "leader" if L >= 2 * max(F, 1) else "follower" if F >= 2 * max(L, 1) else "mixed"})
    roles.sort(key=lambda r: (-(r["leads"] - r["follows"]), -r["leads"]))
    out = {"actors": cand, "actors_considered": len(cand), "named_with_dated_actions": len(hourly),
           "pairs_considered": considered, "pairs": pairs, "flagged": sum(1 for p in pairs if p["flag"]),
           "roles": roles, "lags": LAGS, "min_overlap": MIN_OVERLAP}
    c["leadlag"] = out
    return out


# ================================================================== 4. anomaly timeline

def anomalies(s, top=TOP_ACTORS):
    c = _cache(s)
    if "anomalies" in c:
        return c["anomalies"]
    times, intents = s.rec["_times"], s.rec["_intents"]
    hourly, total = _hourly_named(s)
    cand = sorted((a for a in hourly if hourly[a]), key=lambda a: (-sum(hourly[a].values()), a))[:top]
    want = set(cand)
    first_msg = {}
    for d in s.flow["_deliveries"]:
        for who, role, rid in ((d["from"], "sent", d["write_id"]), (d["to"], "received", d["read_id"])):
            if who in want and d.get("read_time") is not None:
                t = d["read_time"] if role == "received" else (d.get("write_time") or d["read_time"])
                if who not in first_msg or t < first_msg[who][0]:
                    other = d["to"] if role == "sent" else d["from"]
                    first_msg[who] = (t, rid, role, other, d["channel"])
    rows = []
    for a in cand:
        hc = hourly[a]
        active = sorted(hc)
        vals = sorted(hc.values())
        med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
        h_first = active[0]
        marks = defaultdict(lambda: {"kinds": []})

        def mark(h, kind, **kw):
            m = marks[h]
            m["hour"] = _hiso(h)
            m["h"] = h
            m["kinds"].append({"kind": kind, **kw})
        for h in active:
            if hc[h] >= 3 * med and hc[h] >= 10:
                mark(h, "burst", n=hc[h], times_median=round(hc[h] / med, 1) if med else None)
        seen_pl, seen_it, harm_done = set(), set(), False
        new_pl, new_it = defaultdict(list), defaultdict(list)
        ops = sorted((t, ch, rid) for ch, op, t, rid in s.ops_by_actor.get(a, []) if t is not None)
        for t, ch, rid in ops:
            if ch not in seen_pl:
                seen_pl.add(ch)
                if _hour(t) != h_first:
                    new_pl[_hour(t)].append((ch, rid))
        harm_first = None
        for rid in s.by_actor.get(a, []):
            t = times.get(rid)
            if t is None:
                continue
            if rid in s.harmful and (harm_first is None or t < harm_first[0]):
                harm_first = (t, rid)
        ints = sorted((times[rid], intents[rid], rid) for rid in s.by_actor.get(a, [])
                      if rid in times and intents.get(rid) and intents[rid] != "other")
        for t, it, rid in ints:
            if it not in seen_it:
                seen_it.add(it)
                if _hour(t) != h_first:
                    new_it[_hour(t)].append((it, rid))
        for h, lst in new_pl.items():
            mark(h, "place", n=len(lst), places=[x[0] for x in lst[:5]], record=lst[0][1])
        for h, lst in new_it.items():
            mark(h, "intent", n=len(lst), intents=[x[0] for x in lst], record=lst[0][1])
        if harm_first:
            mark(_hour(harm_first[0]), "harm", record=harm_first[1], intent=intents.get(harm_first[1]))
        if a in first_msg:
            t, rid, role, other, ch = first_msg[a]
            mark(_hour(t), "message", record=rid, role=role, other=other, channel=ch)
        ms = sorted(marks.values(), key=lambda m: m["h"])
        for m in ms:
            del m["h"]
        rows.append({"actor": a, "actions": total[a], "dated": sum(hc.values()), "active_hours": len(active),
                     "median_per_active_hour": med, "first": _hiso(active[0]), "last": _hiso(active[-1]),
                     "hourly": [[_hiso(h), n] for h, n in sorted(hc.items())], "marks": ms})
    all_h = [h for a in cand for h in hourly[a]]
    out = {"actors": rows, "actors_total": len(hourly), "top": top,
           "start": _hiso(min(all_h)) if all_h else None, "end": _hiso(max(all_h)) if all_h else None,
           "counts": dict(Counter(k["kind"] for r in rows for m in r["marks"] for k in m["kinds"]))}
    c["anomalies"] = out
    return out


# ================================================================== 5. deterministic narrative

def _sent(t, parts, kind, ids=()):
    """One sentence: parts are strings or {"actor"|"rec"|"place"|"intent": value}."""
    return {"t": t, "time": iso(t) if t is not None else None, "kind": kind, "parts": parts,
            "records": [x for x in ids if x]}


def _harm_kind_firsts(s):
    """First dated action of each harmful intent or tag."""
    times, intents, ev = s.rec["_times"], s.rec["_intents"], s.res["_evidence"]
    harm = s.pack.harm
    out = {}
    for rid in _actions(s):
        t = times.get(rid)
        if t is None:
            break
        for k in [intents.get(rid)] + list(ev[rid]):
            if k in harm and k not in out:
                out[k] = (t, rid)
    return out


def story(s, top_actors=8):
    c = _cache(s)
    if "story" in c:
        return c["story"]
    times = s.rec["_times"]
    names_i, names_t = insight.intent_names(s.pack), insight.tag_names(s.pack)
    sim = insight.simulate(s)
    phases = insight.data_phases(s)
    st = stages(s)
    an = anomalies(s, top=TOP_ACTORS)
    acts = _actions(s)
    dated = [r for r in acts if r in times]
    hourly_all = Counter(_hour(times[r]) for r in dated)
    sents = []
    # harmful firsts
    for k, (t, rid) in _harm_kind_firsts(s).items():
        what = names_i.get(k) or names_t.get(k) or insight.human(k)
        sents.append(_sent(t, ["The first harmful action of kind ", {"intent": k}, f" ({what.rstrip('.')}) came from ",
                               {"actor": s.actor[rid][0]}, " in ", {"rec": rid}, "."], "harm", [rid]))
    # first message between named actors and the linked groups
    for g in sim.get("signals", []):
        if g["kind"] == "message":
            a = g["actors"]
            d = next((d for d in s.flow["_deliveries"] if d["read_id"] == g["record"]), None)
            if d:
                sents.append(_sent(g["t"], ["The first message between named actors: ", {"actor": d["from"]}, " wrote ",
                                            {"place": d["channel"]}, " in ", {"rec": d["write_id"]}, " and ", {"actor": d["to"]},
                                            f" read it in ", {"rec": d["read_id"]}, f", {d['latency_h']} h later."],
                                   "message", [d["write_id"], d["read_id"]]))
        elif g["kind"] == "group":
            sents.append(_sent(g["t"], [g["name"] + ": the message read in ", {"rec": g["record"]}, " joined ",
                                        {"actor": g["actors"][0]}, " and ", {"actor": g["actors"][-1]}, " into one group."],
                               "group", [g["record"]]))
        elif g["kind"] in ("token", "carried"):
            parts = [g["name"] + ": " + str(g["why"])] + ([" (", {"rec": g["record"]}, ")."] if g["record"] else ["."])
            sents.append(_sent(g["t"], parts, g["kind"], [g["record"]]))
    # first program reuse
    spread = s.flow.get("_content_spread", [])
    reuse = None
    for x in spread:
        for ad in x["adopters"]:
            t = _parse_iso(ad["time"])
            if t is not None and (reuse is None or t < reuse[0]):
                reuse = (t, x, ad)
    if reuse:
        t, x, ad = reuse
        sents.append(_sent(t, ["The first program reuse: ", {"actor": ad["actor"]}, " ran in ", {"rec": ad["record"]},
                               " the program ", {"actor": x["source"]}, " first ran in ", {"rec": x["source_record"]},
                               f", {ad['hours_after_source']} h earlier; {x['actors']} named actors ran it in all."],
                           "program", [ad["record"], x["source_record"]]))
    # stage firsts
    for r in st["stages"]:
        if r["first_time"]:
            sents.append(_sent(_parse_iso(r["first_time"]),
                               [f"The swarm first reached the stage “{insight.human(r['stage'])}” in ", {"rec": r["first_record"]},
                                " (", {"actor": r["first_actor"]}, ")"]
                               + ([", the first named actor there being ", {"actor": r["first_named_actor"]}, " in ", {"rec": r["first_named_record"]}]
                                  if r["first_named_actor"] and r["first_named_actor"] != r["first_actor"] else [])
                               + [f"; {r['actors']:,} named actor{'' if r['actors'] == 1 else 's'} reached it in all, in {r['records']:,} actions."],
                               "stage", [r["first_record"], r["first_named_record"]]))
    # peak and drop
    if hourly_all:
        peak = max(sorted(hourly_all), key=lambda h: hourly_all[h])
        busiest = Counter(s.actor[r][0] for r in dated if _hour(times[r]) == peak).most_common(1)
        sents.append(_sent(peak * HOUR, [f"The busiest hour, {_hiso(peak)}:00 UTC, held {hourly_all[peak]:,} dated actions"]
                           + ([", most of them by ", {"actor": busiest[0][0]}, f" ({busiest[0][1]:,})."] if busiest else ["."]),
                           "peak"))
    for p in phases:
        if p["key"] == "stop":
            sents.append(_sent(_parse_iso(p["time"]), [f"From {p['time'][:13]}:00 UTC activity stayed below 15% of the peak."], "drop"))
        if p["key"] == "surge":
            sents.append(_sent(_parse_iso(p["time"]), [f"The main surge began at {p['time'][:13]}:00 UTC: {p['why']}."], "surge"))
    sents = [x for x in sents if x["t"] is not None]
    sents.sort(key=lambda x: x["t"])
    paras = []
    if phases:
        for x in sents:
            per = insight.period_of(phases, x["t"]) or {"name": "Build-up", "what": "before the main surge", "since": phases[0]["time"]}
            if not paras or paras[-1]["name"] != per["name"]:
                paras.append({"name": per["name"], "what": per["what"], "since": per["since"], "sentences": []})
            paras[-1]["sentences"].append(x)
    elif sents:
        paras.append({"name": "Chronology", "what": "", "since": None, "sentences": sents})
    # opening
    sm = s.summary() if hasattr(s, "summary") else {}
    named = len({_named(s, r) for r in acts if _named(s, r)})
    span = (iso(times[dated[0]]), iso(times[dated[-1]])) if dated else None
    opening = [f"The trace holds {len(s.events):,} records, {len(acts):,} of them actions; {len(dated):,} actions are dated"
               + (f", from {span[0]} to {span[1]} UTC" if span else "") + f". {named:,} named actors ran actions"
               + (f"; {sum(1 for r in acts if s.actor[r][1] == 'run'):,} actions came from anonymous runs." if acts else ".")]
    # per actor
    actors = []
    ladder = {x["actor"]: x for x in st["actors"]}
    anom = {x["actor"]: x for x in an["actors"]}
    hourly, total = _hourly_named(s)
    for a in sorted(total, key=lambda a: (-total[a], a))[:top_actors]:
        ids = [r for r in s.by_actor.get(a, []) if r in times]
        ids.sort(key=lambda r: times[r])
        ss = []
        if ids:
            ss.append(_sent(times[ids[0]], [{"actor": a}, f" first acted in ", {"rec": ids[0]},
                                            f" and ran {total[a]:,} actions in all ({sum(hourly[a].values()):,} dated, over {len(hourly[a]):,} active hours)."],
                            "first", [ids[0]]))
        for step in (ladder.get(a) or {}).get("steps", []):
            ss.append(_sent(_parse_iso(step["time"]), [f"Reached “{insight.human(step['stage'])}” in ", {"rec": step["record"]}, "."],
                            "stage", [step["record"]]))
        for m in (anom.get(a) or {}).get("marks", []):
            for k in m["kinds"]:
                t = _parse_iso(m["hour"] + ":00")
                if k["kind"] == "burst":
                    ss.append(_sent(t, [f"Burst at {m['hour']}:00: {k['n']:,} actions, {k['times_median']}× its median active hour."], "burst"))
                elif k["kind"] == "harm":
                    ss.append(_sent(t, ["First harmful action, ", {"intent": k.get("intent")} if k.get("intent") else "", " in ", {"rec": k["record"]}, "."],
                                    "harm", [k["record"]]))
                elif k["kind"] == "message":
                    ss.append(_sent(t, [("First message sent to " if k["role"] == "sent" else "First message received from "),
                                        {"actor": k["other"]}, " via ", {"place": k["channel"]}, " (", {"rec": k["record"]}, ")."],
                                    "message", [k["record"]]))
        for x in spread:
            if x["source"] == a:
                ss.append(_sent(_parse_iso(x["source_time"]), ["First ran a program later reused by ", f"{x['actors'] - 1} other actor(s) (",
                                                               {"rec": x["source_record"]}, ")."], "program", [x["source_record"]]))
                break
        if ids:
            ss.append(_sent(times[ids[-1]], ["Last dated action: ", {"rec": ids[-1]}, "."], "last", [ids[-1]]))
        ss = [x for x in ss if x["t"] is not None]
        ss.sort(key=lambda x: x["t"])
        actors.append({"actor": a, "actions": total[a], "sentences": ss})
    out = {"name": s.name, "opening": opening, "phases": phases, "paragraphs": paras, "actors": actors,
           "sentences": len(sents) + sum(len(x["sentences"]) for x in actors)}
    out["markdown"] = to_markdown(out)
    c["story"] = out
    return out


def _parse_iso(x):
    if not x:
        return None
    from .evaluate import _parse
    try:
        return _parse(str(x).replace("at or before ", ""))
    except Exception:
        return None


def _md_parts(parts):
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            k, v = next(iter(p.items()))
            if v is None:
                continue
            out.append(f"`{v}`" if k in ("rec", "place") else f"**{v}**" if k == "actor" else f"_{insight.human(v)}_")
    return "".join(out)


def to_markdown(st):
    lines = [f"# What happened: {st.get('name') or 'dataset'}", "",
             "_Built from the records alone by Swarm Tracer (no AI). Every sentence cites the record ids it rests on; "
             "times are UTC and may be estimated from timestamps in the code._", ""]
    lines += st["opening"] + [""]
    for p in st["paragraphs"]:
        lines.append(f"## {p['name']}" + (f" ({p['what']}, from {p['since']})" if p.get("since") else ""))
        lines.append("")
        for x in p["sentences"]:
            lines.append(f"- {x['time'] or ''} — {_md_parts(x['parts'])}")
        lines.append("")
    if st["actors"]:
        lines.append("## The most active actors")
        lines.append("")
        for a in st["actors"]:
            lines.append(f"### {a['actor']} ({a['actions']:,} actions)")
            lines.append("")
            for x in a["sentences"]:
                lines.append(f"- {x['time'] or ''} — {_md_parts(x['parts'])}")
            lines.append("")
    return "\n".join(lines)


# ================================================================== routes

def _int(q, k, default):
    try:
        return int(q.get(k, default))
    except (TypeError, ValueError):
        raise ValueError(f"{k} must be a number")


_BG = {}
_BG_LOCK = threading.Lock()


def _in_background(s, wait=1.5):
    """Program evolution takes several seconds on a large trace: it runs once in a thread, and the
    endpoints answer {"pending": true} until it is done (the page asks again)."""
    c = _cache(s)
    if "evolution" in c:
        return True
    if "evolution_error" in c:
        raise ValueError("program evolution failed: " + c["evolution_error"])
    with _BG_LOCK:
        th = _BG.get(id(s))
        if th is None:
            def run():
                try:
                    evolution(s)
                except Exception as e:   # shown to the user instead of a page that waits forever
                    c["evolution_error"] = f"{type(e).__name__}: {e}"
                finally:
                    with _BG_LOCK:
                        _BG.pop(id(s), None)
            th = _BG[id(s)] = threading.Thread(target=run, name="fx_evolution", daemon=True)
            th.start()
    if wait:
        th.join(timeout=wait)
    if "evolution_error" in c:
        raise ValueError("program evolution failed: " + c["evolution_error"])
    return "evolution" in c


PENDING = {"pending": True, "message": "Comparing every program with every other; this runs once per dataset and takes a few seconds on a large trace."}


def r_evolution(state, q):
    s = _session(state)
    if not _in_background(s):
        return PENDING
    return evolution_summary(s)


def r_evolution_cluster(state, q):
    s = _session(state)
    if not _in_background(s):
        return PENDING
    ev = evolution(s)
    cid = _int(q, "id", 0)
    if not (0 <= cid < len(ev["clusters"])):
        raise LookupError("no such cluster")
    return ev["clusters"][cid]


def r_evolution_diff(state, q):
    s = _session(state)
    if not _in_background(s):
        return PENDING
    return evolution_diff(s, _int(q, "id", 0), _int(q, "version", 0))


def r_stages(state, q):
    s = _session(state)
    _in_background(s, wait=0)
    return stages(s)


def r_leadlag(state, q):
    s = _session(state)
    _in_background(s, wait=0)
    return leadlag(s)


def r_anomalies(state, q):
    s = _session(state)
    _in_background(s, wait=0)
    return anomalies(s)


def r_story(state, q):
    s = _session(state)
    _in_background(s, wait=0)
    st = story(s)
    if q.get("format") == "md":
        return {"markdown": st["markdown"]}
    return st


GET = {"fx_evolution": r_evolution, "fx_evolution_cluster": r_evolution_cluster, "fx_evolution_diff": r_evolution_diff,
       "fx_stages": r_stages, "fx_leadlag": r_leadlag, "fx_anomalies": r_anomalies, "fx_story": r_story}
POST = {}

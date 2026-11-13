"""Swarm-wide spread: how did information travel between agents?

Three questions, one module, all counted from the loaded records and cached on the session.

1. Spread map. For every distinctive item (a credential token seen as data and then used, a file or
   path name, a place name, another identifier-like string, a host, a program family, a technique tag)
   the origin (first holder and record), the reach (estimated agents and token actors that held it;
   anonymous runs counted apart), the speed (hours from the origin until 25 / 50 / 90 % of the agents
   that ever held it had held it), the path (holders in order) and a spread type:

     message-carried       the later holder read a place the earlier holder wrote, after the earlier
                           holder had the item (messages.deliveries; the delivery's own grade rides along)
     content-only          the item reached the later holder with no shared place: fx_content's hand-over
                           pairs, or (for a credential) the token was in somebody's data before it was used
     behaviour-only        no message, no content path, but the later holder is behaviour-linked to an
                           earlier holder (fx_coord) or adopted a technique tag, host or program family
                           that nothing visible carried: independent adoption cannot be told from a
                           signal without a visible carrier
     unknown               none of the above

   The type of an item is the commonest type among its later holders (ties: message, content, behaviour).
   "Held" means: a record of the actor holds the string (text items), a record uses the token as an
   identity or names it as data (credentials), or the actor's first use of a technique after its first
   hour of activity (fx_coord's rule). A first hold is not a use and not an observation of the carrier:
   estimated times and shared boilerplate can both make an item look like it spread.

2. Evidence graph (evidence, evidence_pair). Message links, content hand-overs and behaviour links in
   one graph over estimated agents, with the number of agent pairs each kind adds beyond messages.

3. Stages (spread_stages). fx_behavior's stage ladder (the first dated action of each agent at each
   stage) set against the spread items: which item an agent already held before it reached a stage, and
   how long the item had taken to get from its origin to that agent.
"""
import math
import re
import time as _time
from collections import Counter, defaultdict

from . import fx_content, fx_coord, fx_lineage, fx_whatif, messages, reconstruct

iso = reconstruct.iso
HOUR = 3600.0
TEXT_CAP = fx_content.TEXT_CAP
HOLD_CAP = 400          # an item held by more units than this is boilerplate and is dropped while scanning
MAX_SHARE = 0.25        # held by more than this share of the estimated agents: common, not a spread
MIN_UNITS = 2           # an item needs two holders (agents or runs) to have spread at all
MAX_SERVED = 3000       # items in the scatter
TOP_TABLE = 300
STRIP_TOP = 10
STRIP_POINTS = 60
QUOTE = 160
KINDS = ("credential", "file", "place", "host", "program", "technique", "string")
TYPES = ("message", "content", "behaviour", "unknown")
TYPE_LABEL = {"message": "message-carried", "content": "content-only hand-over",
              "behaviour": "behaviour-only / independent adoption", "unknown": "unknown", "single": "one holder"}
_FILE_EXT = fx_content._FILE_EXT


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _amap(s):
    try:
        return fx_whatif._agent_map(s, "estimate")[0] or {}
    except Exception:
        return {}


def _unit(amap, actor, kind):
    """An estimated agent for a named actor (its own name when nothing merges it); a run stays a run."""
    return actor if kind == "run" else amap.get(actor, actor)


def _key(s, rid, t):
    return (t is None, t if t is not None else 0.0, s.order[rid])


def _cut(text, n=QUOTE):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ------------------------------------------------------------------ holds

class _Holds:
    """item -> unit -> (sort key, time, record, actor); named token actors per item kept apart."""

    def __init__(self):
        self.h = {}
        self.actors = defaultdict(set)
        self.kind = {}

    def add(self, item, kind, unit, key, t, rid, actor, named):
        d = self.h.setdefault(item, {})
        self.kind.setdefault(item, kind)
        if named:
            self.actors[item].add(actor)
        cur = d.get(unit)
        if cur is None or key < cur[0]:
            d[unit] = (key, t, rid, actor)


_MIME = re.compile(r"^(application|text|image|audio|video|font|multipart)/[\w.+\-]+$")
_PLAIN_PATH = re.compile(r"^[a-z]+(/[a-z]+)+$")


def _public(it):
    """A name or path anyone could write without having seen it from another agent: a MIME type, a route made of
    plain lowercase words (commit/main), a bare library name with no digit, path, dot or placeholder."""
    if it[0] == "[":
        return False
    return bool(_MIME.match(it) or _PLAIN_PATH.match(it) or not fx_content.specific(it))


def _scan_text(s, amap, times, hold):
    """Distinctive-shaped strings in every record (a record's time: its own, else its payload's)."""
    memo = {}
    find = fx_content._TOKEN.findall
    clean = fx_content._clean
    actor = s.actor
    one = {}          # item -> first (unit, key, t, rid, actor, named) while it has a single holder
    many = {}         # item -> {unit: (key, t, rid, actor)} once it has two
    drop = set()
    named_actors = defaultdict(set)
    for e in s.events:
        rid = e.id
        a, ak = actor[rid]
        named = ak != "run"
        u = _unit(amap, a, ak)
        t = fx_content._rtime(s, rid, times)
        key = _key(s, rid, t)
        for tok in set(find(e.text[:TEXT_CAP])):
            it = memo.get(tok, 0)
            if it == 0:
                it = memo[tok] = clean(tok)
            if it is None or it in drop:
                continue
            if it in many:
                d = many[it]
                cur = d.get(u)
                if cur is None:
                    if len(d) >= HOLD_CAP:
                        drop.add(it)
                        del many[it]
                        continue
                    d[u] = (key, t, rid, a)
                elif key < cur[0]:
                    d[u] = (key, t, rid, a)
                if named:
                    named_actors[it].add(a)
                continue
            f = one.get(it)
            if f is None:
                one[it] = (u, key, t, rid, a, named)
            elif f[0] == u:
                if key < f[1]:
                    one[it] = (u, key, t, rid, a, f[5] or named)
            else:
                many[it] = {f[0]: (f[1], f[2], f[3], f[4]), u: (key, t, rid, a)}
                if f[5]:
                    named_actors[it].add(f[4])
                if named:
                    named_actors[it].add(a)
    place_text = " ".join({op[0] for op in s.op_list})
    for it, d in many.items():
        if it in drop or _public(it):
            continue
        if it in place_text:
            kind = "place"
        elif it[0] == "[":
            kind = "string"
        elif "/" in it or ("." in it and it.rsplit(".", 1)[1].lower() in _FILE_EXT):
            kind = "file"
        else:
            kind = "string"
        hold.h[it] = d
        hold.kind[it] = kind
        hold.actors[it] = named_actors.get(it, set())
    return len(one) + len(many) + len(drop)


def _scan_credentials(s, amap, times, hold):
    """Credential tokens: records that use the token as an identity, and the first record naming it as data."""
    cred = fx_lineage.credentials(s)
    ix = fx_lineage._ix(s)
    actor = s.actor
    n = 0
    for r in cred["tokens"]:
        if r["shared"]:
            continue
        tok = r["token"]
        rids = list(ix["tok_recs"].get(tok, ()))
        if r["seen_record"]:
            rids.append(r["seen_record"])
        for rid in rids:
            a, ak = actor[rid]
            t = times.get(rid)
            hold.add(tok, "credential", _unit(amap, a, ak), _key(s, rid, t), t, rid, a, ak != "run")
        n += 1
    return n


def _scan_techniques(s, amap, hold):
    """Tags, hosts and program families by named actors' first use after their first hour (fx_coord)."""
    acts = fx_coord._actions(s)
    first = fx_coord._techniques(s, acts)
    n = 0
    for k, who in first.items():
        if k.startswith("intent:"):
            continue
        kind = {"tag": "technique", "host": "host", "program": "program"}.get(k.split(":", 1)[0])
        if not kind:
            continue
        n += 1
        for a, (t, rid) in who.items():
            hold.add(k, kind, _unit(amap, a, "named"), _key(s, rid, t), t, rid, a, True)
    return n


# ------------------------------------------------------------------ evidence indexes

def _pairkey(a, b):
    return (a, b) if a < b else (b, a)


def evidence_index(s):
    """The three kinds of link between units (estimated agents or runs), shared by the map and the graph."""
    ev = getattr(s, "_spreadmap_ev", None)
    if ev is not None:
        return ev
    amap = _amap(s)
    actor = s.actor
    msg = defaultdict(list)                       # (from unit, to unit) -> deliveries
    for d in s.flow["_deliveries"]:
        a, b = _unit(amap, d["from"], d.get("from_kind")), _unit(amap, d["to"], d.get("to_kind"))
        msg[(a, b)].append(d)
    c = fx_content.build(s)
    content = defaultdict(dict)                   # item -> {then unit: first unit}
    content_pairs = defaultdict(list)             # unordered unit pair -> hand-over pair
    for p in c["handovers"]["pairs"]:
        a, b = _unit(amap, p["from"], "named"), _unit(amap, p["to"], "named")
        if a == b:
            continue
        if p["strong"]:
            content_pairs[_pairkey(a, b)].append(p)
        for it in p["items"]:
            content[it["item"]].setdefault(b, a)
    co = fx_coord.build(s)
    beh = {}                                      # unordered unit pair -> coord pair
    for p in co["pairs"].values():
        if not p["link"]:
            continue
        a, b = _unit(amap, p["a"], "named"), _unit(amap, p["b"], "named")
        if a == b:
            continue
        k = _pairkey(a, b)
        if k not in beh or p["z"] > beh[k]["z"]:
            beh[k] = p
    beh_nbr = defaultdict(set)
    for (a, b) in beh:
        beh_nbr[a].add(b)
        beh_nbr[b].add(a)
    msg_in = defaultdict(set)
    for (a, b) in msg:
        msg_in[b].add(a)
    ev = {"amap": amap, "msg": msg, "msg_in": msg_in, "content": content, "content_pairs": content_pairs,
          "beh": beh, "beh_nbr": beh_nbr}
    s._spreadmap_ev = ev
    return ev


# ------------------------------------------------------------------ the spread map

def _speed(times_h):
    """Hours from the first holder to 25 / 50 / 90 % of the agents (None with fewer than two dated agents)."""
    n = len(times_h)
    if n < 2:
        return None, None, None
    out = []
    for q in (0.25, 0.5, 0.9):
        i = max(1, math.ceil(q * n)) - 1
        out.append(round(times_h[i], 2))
    return tuple(out)


def _holder_type(s, ev, item, kind, u, h, holds, seen_as_data):
    """-> (type, source unit or None, detail) for a later holder u (h = its hold tuple)."""
    key, t, rid, _a = h
    best = None
    # message: a delivery from an earlier holder that the earlier holder could have written the item into
    for p in ev["msg_in"].get(u, ()):
        hp = holds.get(p)
        if hp is None or hp[0] >= key:
            continue
        for d in ev["msg"][(p, u)]:
            rt, wt = d.get("read_time"), d.get("write_time")
            if t is not None and rt is not None and rt > t:
                continue
            if hp[1] is not None and rt is not None and hp[1] > rt:
                continue
            cand = (p, {"channel": d["channel"], "write_id": d["write_id"], "read_id": d["read_id"], "grade": d.get("grade")})
            if best is None or (rt or 0) > (best[2] or 0):
                best = (cand[0], cand[1], rt)
    if best:
        return "message", best[0], best[1]
    src = ev["content"].get(item, {}).get(u)
    if src is not None and src in holds and holds[src][0] < key:
        return "content", src, {}
    if kind == "credential" and seen_as_data is not None and seen_as_data < key:
        return "content", None, {"how": "the token was in somebody's data before it was used"}
    for p in ev["beh_nbr"].get(u, ()):
        hp = holds.get(p)
        if hp is not None and hp[0] < key:
            return "behaviour", p, {"how": "behaviour-linked to an earlier holder"}
    if kind in ("technique", "host", "program"):
        return "behaviour", None, {"how": "independent adoption: no message or link carried it"}
    return "unknown", None, {}


def _build_items(s):
    t0 = _time.time()
    times = s.rec["_times"]
    ev = evidence_index(s)
    amap = ev["amap"]
    hold = _Holds()
    scanned = _scan_text(s, amap, times, hold)
    ncred = _scan_credentials(s, amap, times, hold)
    ntech = _scan_techniques(s, amap, hold)
    named_units = {_unit(amap, a, k) for a, k in s.actor.values() if k != "run"}
    n_agents = len(set(amap.values())) or len(named_units)   # the units tab's count; self-chosen names that are not identities add no agent
    cap = max(3, int(MAX_SHARE * n_agents))
    seen_first = fx_lineage._data_mentions(s)["first_seen"]
    items = {}
    common = 0
    for it, holds in hold.h.items():
        if len(holds) < MIN_UNITS:
            continue
        agents = [u for u in holds if u in named_units]
        if len(agents) > cap:
            common += 1
            continue
        kind = hold.kind[it]
        order = sorted(holds.items(), key=lambda kv: kv[1][0])
        dated = [(u, h) for u, h in order if h[1] is not None]
        if not dated:
            continue
        u0, h0 = dated[0]
        origin_t = h0[1]
        seen = None
        if kind == "credential" and it in seen_first:
            sr = seen_first[it]
            seen = _key(s, sr, times.get(sr))
        tmap = {}
        types = Counter()
        holders = []
        for rank, (u, h) in enumerate(order):
            named = u in named_units
            if rank == 0 and h[1] is not None:
                typ, src, det = "origin", None, {}
            else:
                typ, src, det = _holder_type(s, ev, it, kind, u, h, holds, seen)
                types[typ] += 1
            holders.append({"unit": u, "actor": h[3], "named": named, "time": iso(h[1]) if h[1] is not None else None,
                            "t": h[1], "hours": round((h[1] - origin_t) / HOUR, 2) if h[1] is not None else None,
                            "id": h[2], "type": typ, "from": src, "evidence": det})
            tmap[u] = h
        ag_hours = sorted((x["hours"] for x in holders if x["named"] and x["hours"] is not None))
        t25, t50, t90 = _speed(ag_hours)
        agent_types = Counter(x["type"] for x in holders[1:] if x["named"] and x["type"] != "origin")
        pool = agent_types if agent_types else types
        if pool:
            top = max(pool.values())
            spread = next(k for k in TYPES if pool.get(k, 0) == top)
        else:
            spread = "single"
        runs = len(holders) - len(agents)
        items[it] = {"item": it, "kind": kind, "agents": len(agents), "actors": len(hold.actors.get(it, ())), "runs": runs,
                     "holders_n": len(holders), "dated": len(dated),
                     "origin": {"unit": u0, "actor": h0[3], "id": h0[2], "time": iso(origin_t), "named": u0 in named_units},
                     "t25": t25, "t50": t50, "t90": t90, "type": spread, "mix": dict(types),
                     "agent_mix": dict(agent_types), "holders": holders,
                     "span_h": round((dated[-1][1][1] - origin_t) / HOUR, 2)}
    rank = sorted(items.values(), key=lambda x: (-x["agents"], -x["runs"], x["t50"] if x["t50"] is not None else 1e9, x["item"]))
    for i, x in enumerate(rank):
        x["rank"] = i + 1
    return {"items": items, "rank": rank, "n_agents": n_agents, "cap": cap, "common": common,
            "scanned": {"strings": scanned, "credentials": ncred, "techniques": ntech},
            "seconds": round(_time.time() - t0, 2)}


def build(s):
    c = getattr(s, "_spreadmap", None)
    if c is None:
        c = s._spreadmap = _build_items(s)
    return c


def _trace_q(x):
    k = x["item"]
    if k.startswith("host:") or k.startswith("program:"):
        return k.split(":", 1)[1]
    if k.startswith("tag:"):
        return x["origin"]["id"]
    return k


def _label(item):
    k = item.split(":", 1)
    if k[0] == "tag" and len(k) == 2:
        return k[1].replace("_", " ")
    if k[0] == "program" and len(k) == 2:
        return "program " + _cut(k[1], 24)
    if k[0] == "host" and len(k) == 2:
        return k[1]
    return item


def _slim(x):
    return {"item": x["item"], "label": _label(x["item"]), "kind": x["kind"], "rank": x["rank"], "agents": x["agents"],
            "actors": x["actors"], "runs": x["runs"], "t25": x["t25"], "t50": x["t50"], "t90": x["t90"],
            "type": x["type"], "mix": x["agent_mix"] or x["mix"], "origin": x["origin"], "span_h": x["span_h"],
            "trace_q": _trace_q(x)}


def _strip(x):
    """The cascade as dots: one per holder (agents and runs), hours since the origin, in order."""
    pts = [{"unit": h["unit"], "named": h["named"], "hours": h["hours"], "type": h["type"], "id": h["id"]}
           for h in x["holders"] if h["hours"] is not None]
    named = [p for p in pts if p["named"]]
    shown = named[:STRIP_POINTS]
    return {"points": shown, "points_total": len(named), "runs_total": len(pts) - len(named)}


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else round((xs[m - 1] + xs[m]) / 2, 2)


def summary(s):
    c = build(s)
    its = c["rank"]
    multi = [x for x in its if x["agents"] >= 2]
    by_kind = Counter(x["kind"] for x in its)
    by_type = Counter(x["type"] for x in multi)
    return {"items": len(its), "multi_agent": len(multi), "by_kind": dict(by_kind), "by_type": dict(by_type),
            "agents": c["n_agents"], "common_dropped": c["common"], "max_share": MAX_SHARE, "agent_cap": c["cap"],
            "median_t50_h": _median([x["t50"] for x in multi if x["t50"] is not None]),
            "median_t90_h": _median([x["t90"] for x in multi if x["t90"] is not None]),
            "max_agents": its[0]["agents"] if its else 0,
            "scanned": c["scanned"], "seconds": c["seconds"],
            "thresholds": {"min_units": MIN_UNITS, "hold_cap": HOLD_CAP, "max_share": MAX_SHARE, "text_cap": TEXT_CAP}}


def r_spreadmap(state, q):
    s = _session(state)
    c = build(s)
    kinds = [k for k in (q.get("kind") or "").split(",") if k in KINDS]
    pool = [x for x in c["rank"] if not kinds or x["kind"] in kinds]
    top = [x for x in c["rank"] if x["agents"] >= 2 and x["t50"] is not None][:STRIP_TOP] if not kinds else \
          [x for x in pool if x["agents"] >= 2 and x["t50"] is not None][:STRIP_TOP]
    out = {"summary": summary(s), "items": [_slim(x) for x in pool[:TOP_TABLE]], "items_total": len(pool),
           "scatter": [{"item": x["item"], "label": _label(x["item"]), "kind": x["kind"], "agents": x["agents"], "runs": x["runs"],
                        "t50": x["t50"], "type": x["type"], "trace_q": _trace_q(x)}
                       for x in c["rank"] if x["agents"] >= 2 and x["t50"] is not None][:MAX_SERVED],
           "strips": [dict(_slim(x), strip=_strip(x)) for x in top]}
    return out


def item(s, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("give an item")
    c = build(s)
    x = c["items"].get(name)
    if x is None:
        raise LookupError("not a spread item: it needs two holders and fewer than %d%% of the agents" % int(MAX_SHARE * 100))
    hs = []
    for h in x["holders"][:300]:
        row = {k: v for k, v in h.items() if k != "t"}
        hs.append(row)
    first = s.by_id.get(x["origin"]["id"])
    snip = ""
    if first is not None and x["item"] in first.text:
        snip = fx_content._snip(first.text, x["item"])
    return dict(_slim(x), holders=hs, holders_total=len(x["holders"]), origin_snip=snip, mix_all=x["mix"], agent_mix=x["agent_mix"])


def r_spreadmap_item(state, q):
    return item(_session(state), q.get("q", ""))


# ------------------------------------------------------------------ the evidence graph

def graph(s):
    c = getattr(s, "_spreadmap_graph", None)
    if c is not None:
        return c
    ev = evidence_index(s)
    amap = ev["amap"]
    pairs = {}

    def slot(a, b):
        k = _pairkey(a, b)
        return pairs.setdefault(k, {"a": k[0], "b": k[1], "message": 0, "content": 0, "behaviour": 0, "grades": Counter(),
                                    "a_to_b": 0, "b_to_a": 0, "content_strong": 0, "behaviour_kinds": []})
    msg_run = 0
    for (a, b), ds in ev["msg"].items():
        if a.startswith("run:") or b.startswith("run:"):
            msg_run += len(ds)
            continue
        if a == b:
            continue
        p = slot(a, b)
        p["message"] += len(ds)
        p["a_to_b" if a == p["a"] else "b_to_a"] += len(ds)
        for d in ds:
            if d.get("grade"):
                p["grades"][d["grade"]] += 1
    for k, lst in ev["content_pairs"].items():
        slot(*k)["content"] = len(lst)
        pairs[k]["content_strong"] = len(lst)
    for k, cp in ev["beh"].items():
        p = slot(*k)
        p["behaviour"] = len(cp["kinds"]) or 1
        p["behaviour_kinds"] = cp["kinds"]
        p["z"] = cp["z"]
    rows = []
    for p in pairs.values():
        kinds = [k for k in ("message", "content", "behaviour") if p[k]]
        p["kinds"] = kinds
        p["grades"] = dict(p["grades"])
        p["style"] = kinds[0]
        rows.append(p)
    rows.sort(key=lambda p: (-len(p["kinds"]), -p["message"], -p["content"], -p["behaviour"], p["a"], p["b"]))
    msg_pairs = sum(1 for p in rows if p["message"])
    cont = sum(1 for p in rows if p["content"])
    beh = sum(1 for p in rows if p["behaviour"])
    cont_new = sum(1 for p in rows if p["content"] and not p["message"])
    beh_new = sum(1 for p in rows if p["behaviour"] and not p["message"])
    extra = sum(1 for p in rows if not p["message"])
    members = defaultdict(list)
    for a in {a for a, k in s.actor.values() if k != "run"}:
        members[amap.get(a, a)].append(a)
    nodes = {}
    for p in rows:
        for u in (p["a"], p["b"]):
            nodes.setdefault(u, {"unit": u, "tokens": sorted(members.get(u, [u])), "records": 0})
    for u, n in nodes.items():
        n["records"] = sum(len(s.by_actor.get(a, [])) for a in n["tokens"])
        n["degree"] = sum(1 for p in rows if u in (p["a"], p["b"]))
    graded = Counter()
    for p in rows:
        graded.update(p["grades"])
    same_agent = {"message": sum(len(ds) for (a, b), ds in ev["msg"].items() if a == b and not a.startswith("run:"))}
    c = {"pairs": rows, "nodes": sorted(nodes.values(), key=lambda n: (-n["degree"], n["unit"])),
         "summary": {"pairs": len(rows), "message": msg_pairs, "content": cont, "behaviour": beh,
                     "content_beyond": cont_new, "behaviour_beyond": beh_new, "beyond_messages": extra,
                     "all_three": sum(1 for p in rows if len(p["kinds"]) == 3),
                     "share_missed": round(extra / len(rows), 3) if rows else None,
                     "extra_over_message": round(extra / msg_pairs, 2) if msg_pairs else None,
                     "message_deliveries_with_runs": msg_run, "same_agent_deliveries": same_agent["message"],
                     "grades": dict(graded), "has_grade": bool(graded),
                     "content_pairs_weak_left_out": sum(1 for p in fx_content.build(s)["handovers"]["pairs"] if not p["strong"]),
                     "agents": len(nodes)}}
    s._spreadmap_graph = c
    return c


def r_evidence(state, q):
    s = _session(state)
    g = graph(s)
    return {"summary": g["summary"], "nodes": g["nodes"], "pairs": g["pairs"][:MAX_SERVED], "pairs_total": len(g["pairs"])}


def pair_evidence(s, a, b):
    ev = evidence_index(s)
    g = graph(s)
    k = _pairkey(a, b)
    p = next((x for x in g["pairs"] if (x["a"], x["b"]) == k), None)
    if p is None:
        raise LookupError("no evidence of any kind between these two")
    msgs = []
    for (x, y) in ((k[0], k[1]), (k[1], k[0])):
        for d in ev["msg"].get((x, y), []):
            msgs.append({"from": d["from"], "to": d["to"], "channel": d["channel"], "write_id": d["write_id"],
                         "read_id": d["read_id"], "write_time": iso(d["write_time"]), "read_time": iso(d["read_time"]),
                         "latency_h": d.get("latency_h"), "grade": d.get("grade"), "how": d.get("how")})
    msgs.sort(key=lambda m: m["read_time"])
    cont = []
    for cp in ev["content_pairs"].get(k, []):
        cont.append({"from": cp["from"], "to": cp["to"], "score": cp.get("score"),
                     "items": [{x: it.get(x) for x in ("item", "first_id", "first_time", "then_id", "then_time", "gap_h", "first_snip", "then_snip", "exclusive")}
                               for it in cp["items"][:6]]})
    beh = None
    cp = ev["beh"].get(k)
    if cp:
        sy, ad = cp.get("synchrony"), cp.get("adoption")
        beh = {"kinds": cp["kinds"], "z": cp["z"], "a": cp["a"], "b": cp["b"],
               "synchrony": {"co_events": sy["co_events"], "z": sy["z"]} if sy and sy.get("link") and "co_events" in sy else (
                   {k2: sy[k2] for k2 in sy if k2 in ("z", "co", "co_events", "p")} if sy and sy.get("link") else None),
               "adoption": {"co_adoptions": ad["co_adoptions"], "z": ad["z"], "p_adj": ad["p_adj"],
                            "techniques": ad["techniques"][:8]} if ad and ad.get("link") else None,
               "complementary": [{x: v for x, v in co.items() if not x.startswith("values_") and x != "events"} for co in cp["complementary"] if co.get("link")][:3]}
    return dict(p, messages=msgs[:60], messages_total=len(msgs), content=cont, behaviour=beh)


def r_evidence_pair(state, q):
    a, b = q.get("a"), q.get("b")
    if not a or not b:
        raise ValueError("give a and b")
    return pair_evidence(_session(state), a, b)


# ------------------------------------------------------------------ stages

MARGIN_H = 1.0          # an item that reached a holder within an hour of its origin cannot be ordered from it
_KIND_RANK = {k: i for i, k in enumerate(("credential", "program", "host", "file", "technique", "place", "string"))}


def _pick(rows, per_kind=2, cap=10):
    """Best rows per kind of item: shortest origin-to-use lag first, items that appear in the stage record first."""
    rows = sorted(rows, key=lambda r: (not r["in_record"], r["lag_h"], r["item"]))
    got, n = [], Counter()
    for r in rows:
        if n[r["kind"]] < per_kind:
            n[r["kind"]] += 1
            got.append(r)
    got.sort(key=lambda r: (_KIND_RANK.get(r["kind"], 9), not r["in_record"], r["lag_h"]))
    return got[:cap]


def stage_ties(s):
    c = getattr(s, "_spreadmap_stages", None)
    if c is not None:
        return c
    from . import fx_behavior
    st = fx_behavior.stages(s)
    sm = build(s)
    ev = evidence_index(s)
    amap = ev["amap"]
    times = s.rec["_times"]
    # per estimated agent: stage -> (time, record) of its earliest dated action at the stage
    per = defaultdict(dict)
    for ac in st["actors"]:
        u = _unit(amap, ac["actor"], "named")
        for step in ac["steps"]:
            t = times.get(step["record"])
            if t is None:
                continue
            cur = per[u].get(step["stage"])
            if cur is None or t < cur[0]:
                per[u][step["stage"]] = (t, step["record"])
    out = []
    for row in st["stages"]:
        g = row["stage"]
        users = sorted(((v[g][0], u, v[g][1]) for u, v in per.items() if g in v))
        if not users:
            out.append({"stage": g, "first_time": row["first_time"], "agents": 0, "records": row["records"], "first": None,
                        "preceded": [], "crossed": [], "items_considered": 0})
            continue
        t_first, u_first, r_first = users[0]
        rtext = s.by_id[r_first].text[:fx_content.TEXT_CAP] if r_first in s.by_id else ""
        preceded, crossed = [], []
        considered = own_first = 0
        for x in sm["rank"]:
            if x["agents"] < 2:
                continue
            by_unit = {h["unit"]: h for h in x["holders"] if h["t"] is not None and h["named"]}
            if not by_unit:
                continue
            considered += 1
            ot = x["holders"][0]["t"]
            ou = x["origin"]["unit"]
            # the first agent to act at this stage that already held the item
            fu = None
            for (t, u, rid) in users:
                h = by_unit.get(u)
                if h is not None and h["t"] <= t:
                    fu = (t, u, rid, h)
                    break
            if fu is None:
                continue
            t, u, rid, h = fu
            lag = round((t - ot) / HOUR, 2)
            if u == u_first and u == ou:
                own_first += 1
            if u == ou or lag < MARGIN_H:
                continue        # its own item, or arrived within the hour of the origin: order cannot be told
            row_i = {"item": x["item"], "label": _label(x["item"]), "kind": x["kind"], "type": x["type"], "agents": x["agents"],
                     "origin_unit": ou, "origin_time": x["origin"]["time"], "origin_id": x["origin"]["id"],
                     "user": u, "use_id": rid, "use_time": iso(t), "hold_id": h["id"], "hold_type": h["type"],
                     "arrival_h": round((h["t"] - ot) / HOUR, 2), "lag_h": lag, "hold_to_use_h": round((t - h["t"]) / HOUR, 2),
                     "same_record": h["id"] == rid,
                     "in_record": bool(x["kind"] in ("file", "place", "string", "credential") and x["item"] in s.by_id[rid].text[:fx_content.TEXT_CAP]),
                     "trace_q": _trace_q(x)}
            crossed.append(row_i)
            if u == u_first:
                preceded.append(row_i)
        out.append({"stage": g, "first_time": iso(t_first), "agents": len(users), "records": row["records"],
                    "first": {"unit": u_first, "id": r_first, "time": iso(t_first)},
                    "preceded": _pick(preceded), "preceded_total": len(preceded),
                    "crossed": _pick(crossed), "crossed_total": len(crossed), "items_considered": considered,
                    "crossed_in_record": sum(1 for r in crossed if r["in_record"]), "first_is_origin_of": own_first,
                    "by_kind": dict(Counter(r["kind"] for r in crossed))})
    c = {"stages": out, "actors_total": st["actors_total"], "actors_listed": len(st["actors"]), "dated": st["dated"]}
    s._spreadmap_stages = c
    return c


def r_stages(state, q):
    s = _session(state)
    c = stage_ties(s)
    return {"stages": c["stages"], "actors_total": c["actors_total"], "actors_listed": c["actors_listed"],
            "summary": summary(s)}


GET = {"spreadmap": r_spreadmap, "spreadmap_item": r_spreadmap_item, "evidence": r_evidence,
       "evidence_pair": r_evidence_pair, "spread_stages": r_stages}
POST = {}

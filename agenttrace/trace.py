"""Trace: one chain for any token, file, URL or record, and the provenance of a harmful action.

- trace_start: starting points counted from the data (first message, widest program, most-used found
  credential, the first harmful action of each kind, the busiest broadcast place)
- trace_path?q=: resolve q (record id, token or actor, place, any string) into one ordered chain of
  steps: first appearance, every hand-over, what the holders did in the following hour, and the
  harmful actions it ended in
- trace_harm?rec=: backward from one (harmful) record: its credentials, its program, its places, the
  messages that reached its actor, and the actor's first record, as a small layered graph

Reuses the indexes and functions of fx_lineage (trace anything, credential lifecycle). Every number is
counted from the loaded records; times marked estimated come from timestamps in the code.
"""
import bisect
from collections import Counter, defaultdict

from . import fx_lineage as fx
from . import insight, reconstruct

iso = reconstruct.iso
HOUR = 3600.0
MAX_STEPS = 200
MAX_LANES = 14
TEXT = 180

_sess = fx._sess


# ------------------------------------------------------------------ small helpers

def _amap(s):
    """actor -> estimated agent (the Agents tab's merge groups); {} when the estimate is not available."""
    try:
        from . import fx_whatif
        return fx_whatif._agent_map(s, "estimate")[0] or {}
    except Exception:
        return {}


def _short_text(s, rid, needle=None, rx=None):
    e = s.by_id.get(rid)
    if e is None:
        return ""
    text = e.text or ""
    a = b = 0
    if rx is not None:
        m = rx.search(text)
        if m:
            a, b = m.start(), m.end()
    elif needle:
        j = text.lower().find(needle)
        if j >= 0:
            a, b = j, j + len(needle)
    return fx._snip(text, a, b, 150)[:TEXT]


def _tkey(s, rid):
    return fx._time_key(s, rid)


def _shared(s):
    return set(s.pack.raw.get("shared_identities", [])) | set(getattr(s, "auto_shared", []) or [])


def _harm_kind(s, rid):
    harm = s.pack.harm
    it = s.rec["_intents"].get(rid)
    if it in harm:
        return it
    for x in s.res["_evidence"].get(rid, []):
        if x in harm:
            return x
    return it or "harm"


PRIORITY = {"harm": 6, "write": 5, "read": 5, "use": 4, "run": 3, "reuse": 3, "seen": 2, "next": 1}


class _Chain:
    """Steps keyed by record, edges between records, and the holders whose next hour is looked at."""

    def __init__(self, s, needle=None, rx=None):
        self.s = s
        self.needle, self.rx = needle, rx
        self.steps = {}
        self.edges = []
        self.edge_seen = set()
        self.holders = {}          # actor -> (time, record) of first contact
        self.amap = _amap(s)
        self.notes = []
        self.places = set()

    def step(self, rid, kind, evidence, place=None, rank=2, focus=False):
        s = self.s
        if rid not in s.by_id:
            return None
        st = self.steps.get(rid)
        if kind != "harm" and kind != "next" and rid in s.harmful:
            evidence = evidence + "; counted as harmful (" + insight.human(_harm_kind(s, rid)) + ")"
            kind = "harm"
        if st is None:
            t = s.rec["_times"].get(rid)
            a, ak = s.actor[rid]
            st = self.steps[rid] = {
                "record": rid, "t": t, "time": iso(t) if t is not None else None,
                "estimated": insight.is_estimated(s, rid), "kind": kind, "actor": a, "actor_kind": ak,
                "agent": self.amap.get(a, a), "place": place, "text": _short_text(s, rid, self.needle, self.rx),
                "evidence": evidence, "intent": s.rec["_intents"].get(rid), "harmful": rid in s.harmful,
                "focus": focus, "_rank": rank}
        else:
            if PRIORITY.get(kind, 0) > PRIORITY.get(st["kind"], 0):
                st["kind"] = kind
            if evidence and evidence not in st["evidence"]:
                st["evidence"] = (st["evidence"] + "; " + evidence)[:400]
            if place and not st["place"]:
                st["place"] = place
            st["_rank"] = min(st["_rank"], rank)
            st["focus"] = st["focus"] or focus
        if place:
            self.places.add(place)
        return st

    def edge(self, a, b, kind, label, place=None):
        if a == b or a not in self.steps or b not in self.steps or (a, b) in self.edge_seen:
            return
        self.edge_seen.add((a, b))
        ta, tb = self.s.rec["_times"].get(a), self.s.rec["_times"].get(b)
        self.edges.append({"from": a, "to": b, "kind": kind, "label": label, "place": place,
                           "gap_h": fx._gap_h(ta, tb), "estimated": insight.is_estimated(self.s, a, b)})
        if place:
            self.places.add(place)

    def hold(self, actor, rid):
        t = self.s.rec["_times"].get(rid)
        cur = self.holders.get(actor)
        if cur is None or (t is not None and (cur[0] is None or t < cur[0])):
            self.holders[actor] = (t, rid)

    # ---- hand-over: written to a place, read by another actor
    def message(self, d, rank=1):
        ch = d["channel"]
        gap = d.get("latency_h")
        self.step(d["write_id"], "write", f"wrote {ch}", ch, rank)
        self.step(d["read_id"], "read", f"read {ch} after {d['from']} wrote it in {d['write_id']}"
                  + (f" ({d.get('how')})" if d.get("how") else ""), ch, rank)
        self.edge(d["write_id"], d["read_id"], "message", "written, then read" + (f" {gap} h later" if gap else ""), ch)
        self.hold(d["from"], d["write_id"])
        self.hold(d["to"], d["read_id"])

    # ---- what the holders did in the following hour, and the harm they went on to
    def follow(self, max_holders=8, per_holder=3, harm_holders=12):
        s = self.s
        times, intents = s.rec["_times"], s.rec["_intents"]
        order = sorted(self.holders.items(), key=lambda kv: (kv[1][0] is None, kv[1][0] or 0))
        harm_total, first_harm = 0, None
        for n, (actor, (T, rid0)) in enumerate(order):
            if T is None:
                continue
            ai = fx._actor_index(s, actor)
            lo = bisect.bisect_left(ai["t"], T)
            hi = bisect.bisect_right(ai["t"], T + HOUR)
            hrm = [r for r in ai["rid"][lo:] if r in s.harmful]
            harm_total += len(hrm)
            if hrm:
                t = times[hrm[0]]
                if first_harm is None or t < first_harm[0]:
                    first_harm = (t, hrm[0], actor)
                if n < harm_holders:
                    self.step(hrm[0], "harm", f"first harmful action after contact: {insight.human(_harm_kind(s, hrm[0]))}"
                              f" ({len(hrm)} harmful action{'s' if len(hrm) != 1 else ''} by this actor from then on)", rank=1)
                    self.edge(rid0, hrm[0], "harm", "ended in")
            if n < max_holders:
                seen_int, added = set(), 0
                for rid in ai["rid"][lo:hi]:
                    it = intents.get(rid)
                    if rid == rid0 or rid in self.steps or not it or it in seen_int:
                        continue
                    seen_int.add(it)
                    bad = rid in s.harmful
                    mins = max(0, round((times[rid] - T) / 60))
                    self.step(rid, "harm" if bad else "next",
                              f"{insight.human(it)}, {mins} min after first contact" + (" (harmful)" if bad else ""),
                              rank=1 if bad else 4)
                    self.edge(rid0, rid, "next", "next hour")
                    added += 1
                    if added >= per_holder:
                        break
        return harm_total, first_harm

    def finish(self, q, resolved, extra=None):
        s = self.s
        harm_total, first_harm = self.follow()
        steps = sorted(self.steps.values(), key=lambda st: _tkey(s, st["record"]))
        total = len(steps)
        # lanes: actors in order of first step; keep the first MAX_LANES, then cap the steps
        lane_order = []
        for st in sorted(steps, key=lambda st: (st["_rank"], _tkey(s, st["record"]))):
            if st["actor"] not in lane_order:
                lane_order.append(st["actor"])
        lanes_total = len(lane_order)
        keep_lanes = set(lane_order[:MAX_LANES])
        steps = [st for st in steps if st["actor"] in keep_lanes]
        if len(steps) > MAX_STEPS:
            keep = sorted(steps, key=lambda st: (st["_rank"], _tkey(s, st["record"])))[:MAX_STEPS]
            ids = {st["record"] for st in keep}
            steps = [st for st in steps if st["record"] in ids]
        index = {st["record"]: i for i, st in enumerate(steps)}
        edges = [{**e, "from": index[e["from"]], "to": index[e["to"]]} for e in self.edges
                 if e["from"] in index and e["to"] in index]
        handovers = [e for e in self.edges if e["kind"] not in ("next", "harm")]
        # lanes grouped by estimated agent, groups in order of first appearance
        by_agent, agent_order = defaultdict(list), []
        for st in steps:
            a, g = st["actor"], st["agent"]
            if g not in agent_order:
                agent_order.append(g)
            if a not in by_agent[g]:
                by_agent[g].append(a)
        lanes = [{"actor": a, "agent": g, "merged": len(by_agent[g]) > 1,
                  "kind": next(st["actor_kind"] for st in steps if st["actor"] == a)}
                 for g in agent_order for a in by_agent[g]]
        for st in steps:
            st.pop("_rank", None)
        holders = list(self.holders)
        agents = {self.amap.get(a, a) for a in holders}
        dated = [st for st in steps if st["t"] is not None]
        first = dated[0] if dated else (steps[0] if steps else None)
        gap = fx._gap_h(first["t"], first_harm[0]) if first and first_harm and first["t"] is not None else None
        summary = {
            "first_seen": ({k: first[k] for k in ("record", "time", "estimated", "actor", "kind")} if first else None),
            "holders": len(holders), "named_holders": sum(1 for a in holders if insight.is_named(a)),
            "agents": len(agents), "holder_list": holders[:12],
            "places": len(self.places), "place_list": sorted(self.places)[:12],
            "handovers": len(handovers),
            "handover_kinds": dict(Counter(e["kind"] for e in handovers)),
            "harm_reached": harm_total,
            "first_harm": ({"record": first_harm[1], "time": iso(first_harm[0]), "actor": first_harm[2],
                            "estimated": insight.is_estimated(s, first_harm[1]),
                            "kind": _harm_kind(s, first_harm[1])} if first_harm else None),
            "first_to_harm_h": gap if gap is None or gap >= 0 else 0,
            "gap_estimated": bool(first and first_harm and insight.is_estimated(s, first["record"], first_harm[1])),
        }
        out = {"q": q, "found": bool(steps), "resolved": resolved, "steps": steps, "edges": edges,
               "steps_total": total, "truncated": total > len(steps), "max_steps": MAX_STEPS,
               "lanes": lanes, "lanes_total": lanes_total, "edges_total": len(self.edges),
               "summary": summary, "notes": self.notes}
        if extra:
            out.update(extra)
        return out


# ------------------------------------------------------------------ resolving the query

def _resolve(s, raw):
    """-> (type, key): record | token | actor | place | string."""
    q = fx._norm_query(raw)
    if raw in s.by_id:
        return "record", raw
    low = {rid.lower(): rid for rid in s.by_id} if len(raw) < 40 and " " not in raw else {}
    if raw.lower() in low:
        return "record", low[raw.lower()]
    ix = fx._ix(s)
    for tok in ix["tok_recs"]:
        if tok.lower() == q.lower():
            return "token", tok
    for a in s.by_actor:
        if a.lower() == q.lower():
            return "actor", a
    ql = q.lower()
    for ch in s.ops_by_channel:
        if ch.lower() == ql:
            return "place", ch
    tails = [ch for ch in s.ops_by_channel if ch.split(":", 1)[-1].lower() == ql]
    if len(tails) == 1:
        return "place", tails[0]
    return "string", q


def _suggest(s, raw):
    try:
        o = insight.omni(s, raw, 5)
    except Exception:
        o = {"records": [], "actors": [], "places": []}
    return {"records": [r.get("id") for r in o["records"]][:5],
            "actors": [a["actor"] for a in o["actors"]][:5],
            "places": [p["channel"] for p in o["places"]][:5]}


# ------------------------------------------------------------------ the chains

def _chain_hits(s, raw, typ, key):
    """A token, an actor name or any string: who had it in which order."""
    rx = fx._regex(raw) if typ == "string" else None
    needle = key.lower()
    ix = fx._ix(s)
    low, events = ix["low"], s.events
    if rx is not None:
        hits = [e.id for e in events if rx.search(e.text)]
    else:
        hits = [events[i].id for i, t in enumerate(low) if needle in t]
    if typ == "actor":
        hits = list(dict.fromkeys(hits + s.by_actor.get(key, [])))
    hits.sort(key=lambda r: _tkey(s, r))
    c = _Chain(s, None if rx is not None else needle, rx)
    if not hits:
        return c, hits
    ids_of = s.rec["_ids"]
    times = s.rec["_times"]

    def ident(rid):
        if typ == "token":
            return key in ids_of.get(rid, {})
        if typ == "actor":
            return s.actor[rid][0] == key
        return rx is None and any(needle == t.lower() for t in ids_of.get(rid, {}))

    what = "the token" if typ == "token" else "the name" if typ == "actor" else "the string"
    first_contact, first_use = {}, {}
    first_data = None
    for rid in hits:
        a = s.actor[rid][0]
        is_id = ident(rid)
        if a not in first_contact:
            first_contact[a] = (rid, is_id)
        if is_id and a not in first_use:
            first_use[a] = rid
        if not is_id and first_data is None:
            first_data = rid
    order = list(first_contact)
    for a in order:
        c.hold(a, first_contact[a][0])
    # too many holders to draw: named actors come before anonymous runs (all are still counted)
    named = [a for a in order if insight.is_named(a)]
    named_only = len(order) > MAX_LANES and len(named) >= 2
    if named_only:
        c.notes.append(f"{len(order)} actors hold it, {len(order) - len(named)} of them anonymous runs; "
                       "the first appearance and the named actors are drawn.")
        order = order[:1] + [a for a in named if a != order[0]]
    for n, a in enumerate(order):
        rid, is_id = first_contact[a]
        if n >= 60:
            continue
        ev = ("first appearance anywhere: " if n == 0 else "this actor's first contact: ") + \
             (f"used as its identity" if is_id else f"{what} appears in the record as data")
        c.step(rid, "use" if is_id else "seen", ev, rank=0 if n == 0 else 2, focus=n == 0)
        u = first_use.get(a)
        if u and u != rid:
            c.step(u, "use", "the same actor then used it as its identity", rank=1)
            c.edge(rid, u, "seen_used", "seen as data, then used as identity")
    # seen as data by one actor, then used as an identity by another
    if first_use and typ in ("token", "actor", "string"):
        u_actor, u_rid = min(first_use.items(), key=lambda kv: _tkey(s, kv[1]))
        c.step(u_rid, "use", "first use as an identity", rank=0)
        if first_data and _tkey(s, first_data) < _tkey(s, u_rid) and s.actor[first_data][0] != u_actor:
            c.step(first_data, "seen", "seen as data before its first use", rank=0)
            c.edge(first_data, u_rid, "seen_used", "seen as data, then used as identity")
    # each actor's first contact, linked to the latest earlier holder
    hops, hops_total = fx._hops(s, hits, named_only, cap=40)
    for h in hops:
        m = h.get("message")
        src = h["from_record"]
        if src not in c.steps:      # draw the arrow from that actor's first contact rather than add a mark per hop
            fc = first_contact.get(h["from"])
            src = fc[0] if fc and fc[0] in c.steps else None
        if src is None:
            continue
        if m:
            d = next((d for d in s.del_in.get(m["read_id"], []) if d["write_id"] == m["write_id"]), None)
            if d:
                c.message(d, rank=2)
        c.edge(src, h["to_record"], "next_holder",
               "next holder" + (" (a message links them)" if m else ""), m["channel"] if m else None)
    # a record that carries it wrote a place, and another actor read that write
    n_msg = 0
    seen_pair = set()
    for rid in hits:
        if n_msg >= 24:
            break
        for d in s.del_out.get(rid, []):
            k = (d["from"], d["to"], d["channel"])
            if k in seen_pair:
                continue
            seen_pair.add(k)
            c.message(d, rank=2)
            n_msg += 1
            if n_msg >= 24:
                break
    for rid in hits[:5000]:
        for o in s.ops_by_id.get(rid, []):
            c.places.add(o["channel"])
    if typ == "token" and key in _shared(s):
        c.notes.append("This is a shared key that many agents use: holding it says little about who acted.")
    if hops_total > len(hops):
        c.notes.append(f"{hops_total} steps from one {'named ' if named_only else ''}actor to the next in all; the first {len(hops)} are drawn.")
    c.hits_total = len(hits)
    c.as_identity = sum(1 for r in hits if ident(r))
    c.dated = sum(1 for r in hits if times.get(r) is not None)
    return c, hits


def _chain_place(s, ch):
    c = _Chain(s, ch.split(":", 1)[-1].lower())
    ops = sorted(s.ops_by_channel.get(ch, []), key=lambda o: (o[3] is None, o[3] or 0, s.order[o[4]]))
    writers, readers = {}, {}
    for op, a, ak, t, rid in ops:
        if op in fx.WRITE_OPS and a not in writers:
            writers[a] = rid
        if op in fx.READ_OPS and a not in readers:
            readers[a] = rid
    first = True
    for a, rid in list(writers.items())[:10]:
        c.step(rid, "write", ("first write to this place" if first else "this actor's first write here"), ch,
               rank=0 if first else 2, focus=first)
        c.hold(a, rid)
        first = False
    for a, rid in list(readers.items())[:10]:
        if rid not in c.steps:
            c.step(rid, "read", "this actor's first read here", ch, rank=2)
        c.hold(a, rid)
    for a, rid in list(writers.items())[10:] + list(readers.items())[10:]:
        c.hold(a, rid)
    seen_pair, n = set(), 0
    for d in sorted(s.del_by_channel.get(ch, []), key=lambda d: (d["read_time"] is None, d["read_time"] or 0)):
        k = (d["from"], d["to"])
        if k in seen_pair:
            continue
        seen_pair.add(k)
        if n < 30:
            c.message(d, rank=1 if n < 12 else 3)
        n += 1
    if n > 30:
        c.notes.append(f"{n} writer-to-reader pairs on this place; the first 30 are drawn.")
    c.places.add(ch)
    c.hits_total = len(ops)
    return c


def _chain_record(s, rid):
    c = _Chain(s)
    times, ids_of = s.rec["_times"], s.rec["_ids"]
    e = s.by_id[rid]
    a = s.actor[rid][0]
    t = times.get(rid)
    ids = ids_of.get(rid, {})
    kind = "use" if ids else "seen"
    c.step(rid, kind, "the record you asked for" + (f": authenticates as {', '.join(list(ids)[:3])}" if ids else ""),
           rank=0, focus=True)
    c.hold(a, rid)
    for o in s.ops_by_id.get(rid, []):
        c.places.add(o["channel"])
    # what reached it, and who picked up what it wrote
    for d in sorted(s.del_in.get(rid, []), key=lambda d: -(d["write_time"] or 0))[:4]:
        c.message(d, rank=1)
    seen_to = set()
    for d in sorted(s.del_out.get(rid, []), key=lambda d: (d["read_time"] is None, d["read_time"] or 0)):
        if d["to"] in seen_to:
            continue
        seen_to.add(d["to"])
        if len(seen_to) <= 12:
            c.message(d, rank=1)
    if len(seen_to) > 12:
        c.notes.append(f"{len(seen_to)} actors read what this record wrote; the first 12 are drawn.")
    # tokens: seen as data here and used later, or used here and seen as data earlier
    shared = _shared(s)
    try:
        cred = {r["token"]: r for r in fx.credentials(s)["tokens"]}
    except Exception:
        cred = {}
    data_items = []
    if s.pack.info_patterns:
        data_items = [item for fam, item in reconstruct.info_of(e, s.pack) if item not in ids]
    for tok in list(dict.fromkeys(data_items))[:6]:
        r = cred.get(tok)
        if not r or tok in shared:
            continue
        u = r["first_use_record"]
        if u and u != rid and times.get(u) is not None and (t is None or times[u] >= t):
            c.step(u, "use", f"first use of {tok}, which this record carried as data", rank=1)
            c.edge(rid, u, "seen_used", "seen as data, then used as identity")
            c.hold(s.actor[u][0], u)
    for tok in list(ids)[:4]:
        r = cred.get(tok)
        if not r or tok in shared:
            continue
        sr = r["seen_record"]
        if sr and sr != rid and r["seen_before_use"] and (t is None or (times.get(sr) or 0) <= t):
            c.step(sr, "seen", f"{tok} first appears here as data, before any record uses it", rank=1)
            c.edge(sr, rid, "seen_used", "seen as data, then used as identity")
    # its program: who ran it first, who reused it
    fam = insight.family_index(s).get(rid)
    if fam:
        rows = sorted(s.by_family.get(fam, []), key=lambda r: _tkey(s, r))
        firsts = {}
        for r in rows:
            firsts.setdefault(s.actor[r][0], r)
        if len(firsts) > 1:
            src_actor, src = next(iter(firsts.items()))
            c.step(src, "run", f"first run of this program ({len(rows)} copies by {len(firsts)} actors)", rank=1)
            if src != rid:
                c.edge(src, rid, "reuse", "program reused")
            n = 0
            for b, r in firsts.items():
                if b == src_actor or r == rid:
                    continue
                if _tkey(s, r) < _tkey(s, rid) and b != a:
                    continue
                n += 1
                if n <= 8:
                    c.step(r, "reuse", f"reuses the program first run by {src_actor}", rank=2)
                    c.edge(src if src != rid else rid, r, "reuse", "program reused")
                    c.hold(b, r)
            if n > 8:
                c.notes.append(f"{n} actors reused its program afterwards; the first 8 are drawn.")
    c.hits_total = 1
    return c


def trace_path(s, q):
    raw = (q or "").strip()
    if not raw:
        raise ValueError("type a token, a file name, a URL, a place or a record id to trace")
    if len(raw) > 400:
        raise ValueError("that is too long to trace (400 characters at most)")
    typ, key = _resolve(s, raw)
    extra = {}
    if typ == "record":
        c = _chain_record(s, key)
        extra["harm_link"] = key if key in s.harmful else None
    elif typ == "place":
        c = _chain_place(s, key)
    else:
        c, hits = _chain_hits(s, raw, typ, key)
        if not hits:
            return {"q": raw, "found": False, "resolved": {"type": typ, "key": key}, "steps": [], "edges": [],
                    "steps_total": 0, "truncated": False, "max_steps": MAX_STEPS, "lanes": [], "lanes_total": 0,
                    "edges_total": 0, "summary": None, "notes": [], "suggestions": _suggest(s, raw)}
        extra.update(records=c.hits_total, as_identity=c.as_identity, dated=c.dated)
    return c.finish(raw, {"type": typ, "key": key}, extra)


# ------------------------------------------------------------------ starting points

def starts(s):
    cached = getattr(s, "_trace_starts", None)
    if cached is not None:
        return cached
    times = s.rec["_times"]
    out = []
    # the first message (between named actors when there is one)
    dels = [d for d in s.flow["_deliveries"] if d.get("read_time") is not None]
    named = [d for d in dels if insight.is_named(d["from"]) and insight.is_named(d["to"])]
    pool = named or dels
    if pool:
        d = min(pool, key=lambda d: d["read_time"])
        out.append({"key": "first_message", "label": "The first message", "q": d["write_id"],
                    "detail": f"{d['from']} wrote {d['channel']}, {d['to']} read it",
                    "time": iso(d["read_time"]), "estimated": insight.is_estimated(s, d["write_id"], d["read_id"]),
                    "actor": d["from"], "place": d["channel"], "record": d["write_id"]})
    # the widest-spread program
    spread = s.flow.get("_content_spread") or []
    if spread:
        x = max(spread, key=lambda x: (x.get("actors", 0), x.get("copies", 0)))
        out.append({"key": "widest_program", "label": "The widest-spread program", "q": x["source_record"],
                    "detail": f"first run by {x['source']}, then run by {x['actors'] - 1} more actors ({x['copies']} copies)",
                    "time": x.get("source_time"), "estimated": insight.is_estimated(s, x["source_record"]),
                    "actor": x["source"], "record": x["source_record"]})
    # the most-used found credential: seen as data before its first use; else any token also seen as data
    shared = _shared(s)
    stu = [x for x in s.rec.get("seen_then_used", []) if x["item"] not in shared]
    if stu:
        x = max(stu, key=lambda x: x["uses"])
        out.append({"key": "found_credential", "label": "The most-used found credential", "q": x["item"],
                    "detail": f"seen as data in {x['first_seen_id']}, then used {x['uses']} times",
                    "time": x["first_seen"], "estimated": insight.is_estimated(s, x["first_seen_id"]),
                    "actor": x["item"], "record": x["first_seen_id"]})
    else:
        try:
            rows = [r for r in fx.credentials(s)["tokens"] if not r["shared"] and r["data_mentions"]]
        except Exception:
            rows = []
        if rows:
            r = max(rows, key=lambda r: r["uses"])
            out.append({"key": "found_credential", "label": "The most-used credential that also appears as data",
                        "q": r["token"], "detail": f"used {r['uses']} times; appears as data in {r['data_mentions']} records",
                        "time": r["first_use"], "estimated": insight.is_estimated(s, r["first_use_record"]),
                        "actor": r["token"], "record": r["first_use_record"]})
    # the first harmful action of each kind
    first = {}
    for rid in s.harmful:
        t = times.get(rid)
        if t is None:
            continue
        k = _harm_kind(s, rid)
        if k not in first or t < first[k][0]:
            first[k] = (t, rid)
    counts = Counter(_harm_kind(s, rid) for rid in s.harmful)
    for k, (t, rid) in sorted(first.items(), key=lambda kv: kv[1][0]):
        out.append({"key": "first_harm", "label": f"First harmful action: {insight.human(k)}", "harm": rid,
                    "detail": f"by {s.actor[rid][0]}; {counts[k]} such actions in all", "kind": k,
                    "time": iso(t), "estimated": insight.is_estimated(s, rid),
                    "actor": s.actor[rid][0], "record": rid})
    # the busiest broadcast place: one that many actors read
    best = None
    for ch, ops in s.ops_by_channel.items():
        writers, readers = fx._place_actors(ops)
        only = readers - writers
        if len(readers) < 2 or not writers:
            continue
        k = (len(only), len(s.del_by_channel.get(ch, [])), len(readers))
        if best is None or k > best[0]:
            best = (k, ch, len(writers), len(readers))
    if best:
        (only, msgs, _), ch, nw, nr = best
        out.append({"key": "broadcast_place", "label": "The busiest broadcast place", "q": ch,
                    "detail": f"{nw} writer{'s' if nw != 1 else ''}, {nr} readers ({only} only read), {msgs} messages",
                    "place": ch})
    res = {"starts": out, "dataset": s.name, "harm_total": len(s.harmful)}
    s._trace_starts = res
    return res


# ------------------------------------------------------------------ backward from harm

def trace_harm(s, rid):
    rid = (rid or "").strip()
    if not rid:
        raise ValueError("give a record id (rec=)")
    e = s.by_id.get(rid)
    if e is None:
        raise LookupError(f"no record {rid}")
    times, ids_of = s.rec["_times"], s.rec["_ids"]
    amap = _amap(s)
    shared = _shared(s)
    t = times.get(rid)
    actor, actor_kind = s.actor[rid]
    nodes, edges, story = [], [], []
    seen = {}

    def node(nid, typ, label, layer, record=None, actor_=None, place=None, detail="", **more):
        if nid in seen:
            return nid
        rt = times.get(record) if record else None
        seen[nid] = len(nodes)
        nodes.append({"id": nid, "type": typ, "label": label, "layer": layer, "record": record, "actor": actor_,
                      "place": place, "detail": detail, "time": iso(rt) if rt is not None else None, "t": rt,
                      "estimated": insight.is_estimated(s, record) if record else False, **more})
        return nid

    def origin(label, record, actor_=None, place=None, detail=""):
        nid = "origin:" + record
        if nid in seen:
            n = nodes[seen[nid]]
            if label not in n["label"]:
                n["label"] += " · " + label
                n["detail"] = (n["detail"] + "; " + detail).strip("; ")
            return nid
        return node(nid, "origin", label, 0, record=record, actor_=actor_, place=place, detail=detail)

    def edge(a, b, label):
        if a != b and not any(x["from"] == a and x["to"] == b for x in edges):
            edges.append({"from": a, "to": b, "label": label})

    def say(text, record=None, actor_=None, place=None):
        rt = times.get(record) if record else None
        story.append({"text": text, "record": record, "actor": actor_, "place": place,
                      "time": iso(rt) if rt is not None else None, "t": rt,
                      "estimated": insight.is_estimated(s, record) if record else False})

    harmful = rid in s.harmful
    kind = _harm_kind(s, rid) if harmful else s.rec["_intents"].get(rid)
    H = node("harm", "harm", insight.human(kind) if kind else rid, 3, record=rid, actor_=actor,
             detail="counted as harmful" if harmful else "not counted as harmful by this pack", harmful=harmful)
    A = node("actor", "actor", actor, 2, actor_=actor, detail=f"{len(s.by_actor.get(actor, []))} records",
             agent=amap.get(actor, actor), merged=amap.get(actor, actor) != actor)
    edge(A, H, "did it")
    say(("The harmful action" if harmful else "The record") + (f" ({insight.human(kind)})" if kind else "") + " was done by",
        rid, actor)

    # the actor's first record
    mine = sorted(s.by_actor.get(actor, []), key=lambda r: _tkey(s, r))
    if mine and mine[0] != rid:
        f = mine[0]
        O = origin("first record of this actor", f, actor_=actor,
                 detail=f"{len(mine)} records by this actor; this one is number {mine.index(rid) + 1}")
        edge(O, A, "first record")
        say(f"This actor's first record (this one is number {mine.index(rid) + 1} of {len(mine)})", f, actor)
    else:
        say("It is this actor's first record", rid, actor)

    # credentials: where each first appeared, who used it before
    try:
        cred = {r["token"]: r for r in fx.credentials(s)["tokens"]}
    except Exception:
        cred = {}
    ix = fx._ix(s)
    toks = list(ids_of.get(rid, {}).items())
    data_items = []
    if s.pack.info_patterns:
        data_items = list(dict.fromkeys(item for fam, item in reconstruct.info_of(e, s.pack)
                                        if item not in ids_of.get(rid, {}) and item in ix["tok_recs"]))
    for tok, role in toks[:5] + [(x, "data") for x in data_items[:3]]:
        r = cred.get(tok)
        before = set()
        if t is not None:
            for u in ix["tok_recs"].get(tok, []):
                tu = times.get(u)
                if tu is not None and tu < t and s.actor[u][0] != actor:
                    before.add(s.actor[u][0])
        as_data = role == "data"
        det = ("carried as data, not used" if as_data else f"used as {role}") + \
              ("; a shared key many agents use" if tok in shared else "") + \
              (f"; {r['uses']} uses by {r['users_total']} actor{'s' if r['users_total'] != 1 else ''}" if r else "") + \
              (f"; {len(before)} other actor{'s' if len(before) != 1 else ''} used it before this record" if before else "")
        Cn = node("cred:" + tok, "credential", tok, 1, actor_=tok, detail=det, shared=tok in shared,
                  as_data=as_data, users_before=len(before), users_before_list=sorted(before)[:6])
        edge(Cn, A, "carried by" if as_data else "authenticates")
        if r and tok not in shared:
            if r["seen_record"] and r["seen_before_use"]:
                O = node("origin:seen:" + tok, "origin", "first seen as data", 0, record=r["seen_record"],
                         actor_=r["seen_actor"], detail=f"{tok} appears as data before any record uses it")
                edge(O, Cn, "seen as data")
                say(f"{tok} first appeared as data, before any use, in a record by", r["seen_record"], r["seen_actor"])
            fu = r["first_use_record"]
            if fu and fu != rid:
                O = origin("first use", fu, actor_=s.actor[fu][0],
                         detail=f"first record that authenticates with {tok}")
                edge(O, Cn, "first used")
                say(f"{tok} was first used" + (f"; {len(before)} other actor{'s' if len(before) != 1 else ''} used it before this record" if before else ""),
                    fu, s.actor[fu][0])
            elif fu == rid:
                say(f"This record is the first use of {tok}", rid, actor)
        elif tok in shared:
            say(f"It also carries {tok}, a shared key many agents use (it says nothing about who acted)", None, None)

    # the program family
    fam = insight.family_index(s).get(rid)
    if fam:
        rows = sorted(s.by_family.get(fam, []), key=lambda r: _tkey(s, r))
        firsts = {}
        for r in rows:
            firsts.setdefault(s.actor[r][0], r)
        if len(rows) > 1:
            src_actor, src = next(iter(firsts.items()))
            after = [b for b, r in firsts.items() if b != src_actor]
            P = node("program", "program", f"program · {len(rows)} copies", 1, record=src,
                     detail=f"the same code (ids and numbers masked) run {len(rows)} times by {len(firsts)} actor{'s' if len(firsts) != 1 else ''}",
                     copies=len(rows), actors=len(firsts))
            edge(P, A, "runs it")
            if src != rid:
                O = origin("first run of the program", src, actor_=src_actor,
                         detail=f"{len(after)} other actor{'s' if len(after) != 1 else ''} ran it afterwards")
                edge(O, P, "first run")
            say(f"Its program was first run ({len(rows)} copies; {len(after)} other actor{'s' if len(after) != 1 else ''} ran it after the first)",
                src, src_actor)

    # the places it touches: who wrote them
    my_places = []
    for o in s.ops_by_id.get(rid, []):
        if o["channel"] not in [p[0] for p in my_places]:
            my_places.append((o["channel"], o["op"]))
    for ch, op in my_places[:5]:
        ops = sorted(s.ops_by_channel.get(ch, []), key=lambda o: (o[3] is None, o[3] or 0))
        wr = [o for o in ops if o[0] in fx.WRITE_OPS]
        writers = Counter(o[1] for o in wr)
        Pn = node("place:" + ch, "place", ch, 1, place=ch,
                  detail=f"{len(wr)} writes by {len(writers)} actor{'s' if len(writers) != 1 else ''}",
                  writers=[a for a, _ in writers.most_common(5)], writers_total=len(writers), op=op)
        edge(Pn, A, {"write": "writes it", "read": "reads it"}.get(op, "posts to it"))
        if wr and wr[0][4] != rid:
            O = origin("first write to the place", wr[0][4], actor_=wr[0][1],
                     place=ch, detail=f"first of {len(wr)} writes")
            edge(O, Pn, "first written")
            say(f"It {'writes' if op == 'write' else 'reads' if op == 'read' else 'posts to'} a place first written ({len(wr)} writes by {len(writers)} actor{'s' if len(writers) != 1 else ''})",
                wr[0][4], wr[0][1], ch)
        elif wr:
            say("It is the first write to", rid, None, ch)
        else:
            nodes[seen[Pn]]["detail"] = f"{len(ops)} reads, never written in these records"
            say("It reads a place no record here writes:", rid, None, ch)
    if len(my_places) > 5:
        say(f"It touches {len(my_places)} places; 5 are drawn", None, None)

    # messages that reached this actor before this record (those this record itself read come first)
    direct = list(s.del_in.get(rid, []))
    earlier = [d for d in s.del_by_actor_in.get(actor, [])
               if d["read_id"] != rid and t is not None and d["read_time"] is not None and d["read_time"] <= t]
    earlier.sort(key=lambda d: -d["read_time"])
    n_before = len(direct) + len(earlier)
    for d in (direct + earlier)[:4]:
        ch = d["channel"]
        M = node("msg:" + d["write_id"] + ">" + d["read_id"], "message", f"message from {d['from']}", 1,
                 record=d["write_id"], actor_=d["from"], place=ch, read_record=d["read_id"],
                 detail=f"{d['from']} wrote {ch}; this actor read it in {d['read_id']}"
                        + (" (this very record)" if d["read_id"] == rid else ""), direct=d["read_id"] == rid)
        edge(M, A, "reached it")
        O = node("origin:msg:" + d["write_id"], "origin", f"write by {d['from']}", 0, record=d["write_id"],
                 actor_=d["from"], place=ch, detail=f"wrote {ch}")
        edge(O, M, "wrote")
        say("A message reached this actor" + (" in this very record" if d["read_id"] == rid else f" earlier (read in {d['read_id']})")
            + ": written by", d["write_id"], d["from"], ch)
    if n_before > 4:
        say(f"{n_before} messages reached this actor before this record; the 4 latest are drawn", None, None)
    elif not n_before:
        say("No message from another actor reached this actor before this record", None, None)

    return {"rec": rid, "harmful": harmful, "kind": kind, "intent": s.rec["_intents"].get(rid),
            "time": iso(t) if t is not None else None, "t": t, "estimated": insight.is_estimated(s, rid),
            "actor": actor, "actor_kind": actor_kind, "agent": amap.get(actor, actor),
            "text": _short_text(s, rid), "nodes": nodes, "edges": edges, "story": story,
            "messages_before": n_before, "places_total": len(my_places)}


# ------------------------------------------------------------------ routes

GET = {
    "trace_start": lambda st, q: starts(_sess(st)),
    "trace_path": lambda st, q: trace_path(_sess(st), q.get("q", "")),
    "trace_harm": lambda st, q: trace_harm(_sess(st), q.get("rec", "")),
}
POST = {}

"""Forensics: follow the evidence.

- trace anything (fx_trace): every record that carries a string, its first appearance, who had it in
  which order, and the hops from one actor to the next
- credential lifecycle (fx_credentials): per identity token, first seen as data, first and last use,
  who used it, which places it opened, who carried it, how long it has been quiet
- command-and-control (fx_c2, fx_c2_place): writes and reads on command files, boards and any place
  with two or more readers, and what the readers did in the hour after they picked a write up
- dead-drop ledger (fx_drops, fx_drops_csv): places written by one actor, who picked them up and
  after how long
- better search (fx_search, fx_like): boolean and regular-expression search over record text, and
  "records like this one"

Every result is counted from the loaded records. Heavy indexes are built once per session.
"""
import bisect
import csv
import io
import math
import re
import statistics
import threading
from collections import Counter, defaultdict

from . import insight, reconstruct

iso = reconstruct.iso
HOUR = 3600.0
_LOCK = threading.Lock()


# ------------------------------------------------------------------ shared indexes

def _sess(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _ix(s):
    """Indexes built once per session: lowered texts, token -> records, dataset span."""
    ix = getattr(s, "_fx_ix", None)
    if ix is not None:
        return ix
    with _LOCK:
        ix = getattr(s, "_fx_ix", None)
        if ix is not None:
            return ix
        times = s.rec["_times"]
        low = [e.text.lower() for e in s.events]
        tok_recs = defaultdict(list)
        for e in s.events:
            for tok in s.rec["_ids"].get(e.id, {}):
                tok_recs[tok].append(e.id)
        ts = [t for t in times.values() if t is not None]
        ix = {"low": low, "tok_recs": tok_recs, "t0": min(ts) if ts else None, "t1": max(ts) if ts else None,
              "acts": {}}
        s._fx_ix = ix
        return ix


def _time_key(s, rid):
    t = s.rec["_times"].get(rid)
    return (t is None, t if t is not None else 0, s.order[rid])


def _hour(t):
    return iso(t)[:13] if t is not None else None


def _gap_h(a, b):
    return round((b - a) / HOUR, 2) if a is not None and b is not None else None


def _norm_query(q):
    """'cred 169' is how the app shows '[CREDENTIAL 169]': search for what the records hold."""
    q = (q or "").strip()
    return re.sub(r"(?i)^cred (\d+)$", r"[CREDENTIAL \1]", q)


def _regex(q):
    """'/pattern/flags' -> compiled regex (case-insensitive unless the flags say 'c'), else None."""
    m = re.fullmatch(r"/(.+)/([a-z]*)", q, re.S)
    if not m:
        return None
    flags = 0 if "c" in m.group(2) else re.I
    try:
        return re.compile(m.group(1), flags | re.S if "s" in m.group(2) else flags)
    except re.error as e:
        raise ValueError(f"not a valid regular expression: {e}")


def _snip(text, start, end, width=160):
    a = max(0, start - width // 3)
    b = min(len(text), max(end, a + width))
    out = " ".join(text[a:b].split())
    return ("…" if a else "") + out + ("…" if b < len(text) else "")


def _actor_index(s, actor):
    """An actor's dated actions in time order, with the first time of each intent and each place."""
    ix = _ix(s)
    got = ix["acts"].get(actor)
    if got is not None:
        return got
    times, intents = s.rec["_times"], s.rec["_intents"]
    rows = sorted((times[rid], rid) for rid in s.by_actor.get(actor, [])
                  if times.get(rid) is not None and reconstruct.is_action(s.by_id[rid], s.pack))
    first_intent, first_place = {}, {}
    for t, rid in rows:
        it = intents.get(rid)
        if it and it not in first_intent:
            first_intent[it] = (t, rid)
        for o in s.ops_by_id.get(rid, []):
            first_place.setdefault(o["channel"], (t, rid))
    got = {"t": [r[0] for r in rows], "rid": [r[1] for r in rows], "intent": first_intent, "place": first_place}
    ix["acts"][actor] = got
    return got


# ------------------------------------------------------------------ 1. trace anything

def _hops(s, rids, named_only, cap=2000):
    """Each actor's first contact with the string, linked to the latest earlier dated record by another actor."""
    times = s.rec["_times"]
    hops, total = [], 0
    last = other = None   # latest dated record (t, rid, actor), and the latest by an actor other than last's
    first_done = set()
    for rid in rids:
        t = times.get(rid)
        if t is None:
            break
        a = s.actor[rid][0]
        if named_only and not insight.is_named(a):
            continue
        if a not in first_done:
            first_done.add(a)
            prev = last if last and last[2] != a else other
            if prev:
                total += 1
                if len(hops) < cap:
                    msg = None
                    for d in s.by_pair.get((prev[2], a), []):
                        if d["read_time"] is not None and d["read_time"] <= t:
                            msg = {"channel": d["channel"], "write_id": d["write_id"], "read_id": d["read_id"]}
                            break
                    hops.append({"from": prev[2], "from_record": prev[1], "from_time": iso(prev[0]),
                                 "to": a, "to_record": rid, "to_time": iso(t), "gap_h": _gap_h(prev[0], t),
                                 "estimated": insight.is_estimated(s, prev[1], rid), "message": msg})
        if last and last[2] != a:
            other = last
        last = (t, rid, a)
    return hops, total


def trace(s, q, limit=5000):
    raw = (q or "").strip()
    if not raw:
        raise ValueError("type a string to trace")
    rx = _regex(raw)
    needle = _norm_query(raw).lower()
    ix = _ix(s)
    low, events = ix["low"], s.events
    if rx is not None:
        hits = [i for i, e in enumerate(events) if rx.search(e.text)]
    else:
        hits = [i for i, t in enumerate(low) if needle in t]
    times, ids_of, intents = s.rec["_times"], s.rec["_ids"], s.rec["_intents"]
    hits.sort(key=lambda i: _time_key(s, events[i].id))
    total = len(hits)

    def match_span(i):
        if rx is not None:
            m = rx.search(events[i].text)
            return (m.start(), m.end()) if m else (0, 0)
        j = low[i].find(needle)
        return (j, j + len(needle)) if j >= 0 else (0, 0)

    def is_identity(rid):
        toks = ids_of.get(rid, {})
        if rx is not None:
            return any(rx.search(t) for t in toks)
        return any(needle in t.lower() for t in toks)

    series, kinds, places, place_ops = Counter(), Counter(), Counter(), defaultdict(Counter)
    actors = {}
    order = []
    rows = []
    dated = 0
    as_identity = 0
    for i in hits:
        e = events[i]
        rid = e.id
        t = times.get(rid)
        a, ak = s.actor[rid]
        ident = is_identity(rid)
        as_identity += ident
        kinds[e.kind or "record"] += 1
        if t is not None:
            dated += 1
            series[_hour(t)] += 1
        ops = s.ops_by_id.get(rid, [])
        for o in ops:
            places[o["channel"]] += 1
            place_ops[o["channel"]][o["op"]] += 1
        st = actors.get(a)
        if st is None:
            st = actors[a] = {"actor": a, "kind": ak, "first": iso(t), "first_record": rid, "records": 0,
                              "as_identity": 0, "_t": t}
            order.append(a)
        st["records"] += 1
        st["as_identity"] += ident
        if len(rows) < limit:
            s0, s1 = match_span(i)
            rows.append({"id": rid, "time": iso(t), "actor": a, "actor_kind": ak, "kind": e.kind,
                         "intent": intents.get(rid), "identity": ident,
                         "places": [[o["channel"], o["op"]] for o in ops[:6]], "places_total": len(ops),
                         "snip": _snip(e.text, s0, s1)})
    # hops: each actor's first contact, linked to the latest earlier dated record by another actor
    hops, hops_total = _hops(s, [events[i].id for i in hits], False)
    hops_named, hops_named_total = _hops(s, [events[i].id for i in hits], True)
    first = rows[0] if rows else None
    act_rows = []
    for a in order:
        st = actors[a]
        st.pop("_t", None)
        act_rows.append(st)
    return {"q": raw, "searched_for": raw if rx is not None else needle, "regex": rx is not None,
            "total": total, "dated": dated, "as_identity": as_identity, "shown": len(rows), "limit": limit,
            "first": first, "kinds": dict(kinds.most_common()),
            "series": sorted(series.items()), "actors": act_rows[:600], "actors_total": len(act_rows),
            "named_actors": sum(1 for a in order if insight.is_named(a)),
            "places": [{"channel": ch, "records": n, "ops": dict(place_ops[ch])} for ch, n in places.most_common(40)],
            "places_total": len(places), "hops": hops, "hops_total": hops_total,
            "hops_named": hops_named, "hops_named_total": hops_named_total, "rows": rows,
            "span": [iso(ix["t0"]), iso(ix["t1"])]}


# ------------------------------------------------------------------ 2. credential lifecycle

def _data_mentions(s):
    """Every time an identity token appears in a record as data (an info pattern), not as an identity."""
    ix = _ix(s)
    got = ix.get("data")
    if got is not None:
        return got
    times, ids_of = s.rec["_times"], s.rec["_ids"]
    known = set(ix["tok_recs"])
    first_seen, mentions = {}, Counter()
    carry = []   # (t, record, carrier identities, item)
    for e in s.events:
        if not s.pack.info_patterns:
            break
        items = reconstruct.info_of(e, s.pack)
        if not items:
            continue
        ids = ids_of.get(e.id, {})
        t = times.get(e.id)
        for fam, item in items:
            if item not in known or item in ids:
                continue
            mentions[item] += 1
            k = (t is None, t or 0, s.order[e.id])
            if item not in first_seen or k < first_seen[item][0]:
                first_seen[item] = (k, e.id)
            if ids and t is not None:
                carry.append((t, e.id, list(ids), item))
    got = {"first_seen": {k: v[1] for k, v in first_seen.items()}, "mentions": mentions, "carry": carry}
    ix["data"] = got
    return got


def credentials(s):
    cached = getattr(s, "_fx_cred", None)
    if cached is not None:
        return cached
    ix = _ix(s)
    times = s.rec["_times"]
    shared = set(s.pack.raw.get("shared_identities", []))
    data = _data_mentions(s)
    first_use = {}
    for tok, rids in ix["tok_recs"].items():
        ts = [times[r] for r in rids if times.get(r) is not None]
        first_use[tok] = min(ts) if ts else None
    carried = defaultdict(lambda: {"records": 0, "evidence": []})
    for t, rid, carriers, item in data["carry"]:
        tu = first_use.get(item)
        if tu is None or t > tu:
            continue
        for a in carriers:
            if a != item and a not in shared:
                c = carried[(item, a)]
                c["records"] += 1
                if len(c["evidence"]) < 3:
                    c["evidence"].append(rid)
    carried_by = defaultdict(list)
    for (item, a), c in carried.items():
        carried_by[item].append({"actor": a, **c})
    types = Counter()
    rows = []
    t_end = ix["t1"]
    for tok, rids in ix["tok_recs"].items():
        dated = sorted((times[r], r) for r in rids if times.get(r) is not None)
        users = Counter(s.actor[r][0] for r in rids)
        pl = Counter()
        for r in rids:
            for o in s.ops_by_id.get(r, []):
                pl[o["channel"]] += 1
        pt = Counter(c.split(":", 1)[0] for c in pl)   # distinct places of each type
        types.update(pt.keys())
        seen_rid = data["first_seen"].get(tok)
        seen_t = times.get(seen_rid) if seen_rid else None
        fu = dated[0] if dated else None
        lu = dated[-1] if dated else None
        rows.append({
            "token": tok, "shared": tok in shared, "uses": len(rids), "dated_uses": len(dated),
            "first_use": iso(fu[0]) if fu else None, "first_use_record": fu[1] if fu else rids[0],
            "last_use": iso(lu[0]) if lu else None, "last_use_record": lu[1] if lu else rids[-1],
            "seen": iso(seen_t) if seen_rid else None, "seen_record": seen_rid,
            "seen_actor": s.actor[seen_rid][0] if seen_rid else None,
            "seen_before_use": bool(seen_t is not None and fu and seen_t < fu[0]),
            "data_mentions": data["mentions"].get(tok, 0),
            "users": [{"actor": a, "n": n} for a, n in users.most_common(6)], "users_total": len(users),
            "places_total": len(pl), "places": [{"channel": c, "n": n} for c, n in pl.most_common(6)],
            "place_types": dict(pt),
            "carried_by": sorted(carried_by.get(tok, []), key=lambda c: -c["records"])[:6],
            "carried_by_total": len(carried_by.get(tok, [])),
            "quiet_h": _gap_h(lu[0], t_end) if lu and t_end is not None else None,
        })
    rows.sort(key=lambda r: (r["first_use"] is None, r["first_use"] or "", -r["uses"]))
    out = {"tokens": rows, "total": len(rows), "place_types": [t for t, _ in types.most_common()],
           "shared": sorted(shared), "span": [iso(ix["t0"]), iso(ix["t1"])],
           "seen_before_use": sum(1 for r in rows if r["seen_before_use"]),
           "carried_edges": len(carried), "info_patterns": len(s.pack.info_patterns)}
    s._fx_cred = out
    return out


# ------------------------------------------------------------------ 3. command-and-control

C2_TYPES = ("command_file", "board")
WRITE_OPS = ("write", "post")
READ_OPS = ("read", "post")


def _place_actors(ops):
    writers = {a for op, a, ak, t, rid in ops if op in WRITE_OPS}
    readers = {a for op, a, ak, t, rid in ops if op in READ_OPS}
    return writers, readers


def c2_list(s):
    cached = getattr(s, "_fx_c2", None)
    if cached is not None:
        return cached
    rows = []
    for ch, ops in s.ops_by_channel.items():
        typ = ch.split(":", 1)[0]
        writers, readers = _place_actors(ops)
        if typ not in C2_TYPES and len(readers) < 2:
            continue
        ts = [o[3] for o in ops if o[3] is not None]
        rows.append({"channel": ch, "type": typ, "command": typ in C2_TYPES,
                     "writes": sum(1 for o in ops if o[0] in WRITE_OPS), "reads": sum(1 for o in ops if o[0] in READ_OPS),
                     "writers": len(writers), "readers": len(readers),
                     "readers_not_writers": len(readers - writers),
                     "messages": len(s.del_by_channel.get(ch, [])),
                     "first": iso(min(ts)) if ts else None, "last": iso(max(ts)) if ts else None})
    rank = {t: i for i, t in enumerate(C2_TYPES)}
    rows.sort(key=lambda r: (rank.get(r["type"], len(C2_TYPES)), -r["messages"], -r["readers"], r["channel"]))
    out = {"places": rows, "total": len(rows), "command_places": sum(1 for r in rows if r["command"]),
           "types": dict(Counter(r["type"] for r in rows))}
    s._fx_c2 = out
    return out


def _window(s, actor, T, minutes=60, read_rid=None, place=None):
    """The actor's dated actions in the hour before T and in the hour from T (the read itself left out),
    and the intents and places it used for the first time in that hour."""
    ai = _actor_index(s, actor)
    w = minutes * 60
    lo, mid, hi = (bisect.bisect_left(ai["t"], T - w), bisect.bisect_left(ai["t"], T),
                   bisect.bisect_right(ai["t"], T + w))
    after = [r for r in ai["rid"][mid:hi] if r != read_rid]
    new_int = sorted((k for k, (t, r) in ai["intent"].items() if T <= t <= T + w and r != read_rid),
                     key=lambda k: ai["intent"][k][0])
    new_pl = sorted((k for k, (t, r) in ai["place"].items() if T <= t <= T + w and r != read_rid and k != place),
                    key=lambda k: ai["place"][k][0])
    return {"before": mid - lo, "after": len(after),
            "new_intents": [{"intent": k, "record": ai["intent"][k][1]} for k in new_int],
            "new_places": [{"channel": k, "record": ai["place"][k][1]} for k in new_pl[:8]],
            "new_places_total": len(new_pl),
            "records_after": after[:8]}


def c2_place(s, ch, max_writes=40):
    ops = s.ops_by_channel.get(ch)
    if ops is None:
        raise LookupError(f"no place named {ch}")
    ops = sorted(ops, key=lambda o: (o[3] is None, o[3] or 0))
    writers, readers = _place_actors(ops)
    timeline = [{"op": op, "actor": a, "time": iso(t), "record": rid} for op, a, ak, t, rid in ops[:3000]]
    writes = [(op, a, t, rid) for op, a, ak, t, rid in ops if op in WRITE_OPS]
    cards, no_pickup = [], 0
    for op, a, t, rid in writes:
        dels = [d for d in s.del_out.get(rid, []) if d["channel"] == ch]
        if not dels:
            no_pickup += 1
            continue
        if len(cards) >= max_writes:
            continue
        firsts = {}
        for d in sorted(dels, key=lambda d: (d["read_time"] is None, d["read_time"] or 0)):
            firsts.setdefault(d["to"], d)
        rd = []
        for b, d in firsts.items():
            T = d["read_time"]
            item = {"actor": b, "read_record": d["read_id"], "read_time": iso(T), "wait_h": d["latency_h"]}
            if T is not None:
                item.update(_window(s, b, T, read_rid=d["read_id"], place=ch))
            rd.append(item)
        cards.append({"writer": a, "op": op, "record": rid, "time": iso(t), "readers": rd})
    agg = {"pickups": sum(len(c["readers"]) for c in cards),
           "with_new_intent": sum(1 for c in cards for r in c["readers"] if r.get("new_intents")),
           "with_new_place": sum(1 for c in cards for r in c["readers"] if r.get("new_places_total")),
           "more_after": sum(1 for c in cards for r in c["readers"] if r.get("after", 0) > r.get("before", 0)),
           "fewer_after": sum(1 for c in cards for r in c["readers"] if r.get("after", 0) < r.get("before", 0))}
    return {"channel": ch, "type": ch.split(":", 1)[0], "ops_total": len(ops), "timeline": timeline,
            "writers": sorted(writers), "readers": sorted(readers),
            "writes_total": len(writes), "writes_without_pickup": no_pickup,
            "cards": cards, "cards_total": len(writes) - no_pickup, "summary": agg}


# ------------------------------------------------------------------ 4. dead-drop ledger

WAIT_BINS = [(10 / 60, "< 10 min"), (1, "10–60 min"), (3, "1–3 h"), (6, "3–6 h"), (12, "6–12 h"), (24, "12–24 h"),
             (48, "1–2 days"), (168, "2–7 days"), (float("inf"), "> 7 days")]


def drops(s):
    cached = getattr(s, "_fx_drops", None)
    if cached is not None:
        return cached
    rows, waits, multi = [], [], 0
    for ch, ops in s.ops_by_channel.items():
        wops = [o for o in ops if o[0] in WRITE_OPS]
        if not wops:
            continue
        writers = {o[1] for o in wops}
        if len(writers) != 1:
            multi += 1
            continue
        writer = next(iter(writers))
        wts = sorted((o[3], o[4]) for o in wops if o[3] is not None)
        firsts = {}
        for d in sorted(s.del_by_channel.get(ch, []), key=lambda d: (d["read_time"] is None, d["read_time"] or 0)):
            if d["to"] != writer:
                firsts.setdefault(d["to"], d)
        pk = [{"actor": b, "read_record": d["read_id"], "read_time": iso(d["read_time"]), "write_record": d["write_id"],
               "wait_h": d["latency_h"]} for b, d in firsts.items()]
        w = [p["wait_h"] for p in pk if p["wait_h"] is not None]
        waits += w
        rows.append({"channel": ch, "type": ch.split(":", 1)[0], "writer": writer, "writes": len(wops),
                     "first_write": iso(wts[0][0]) if wts else None,
                     "first_write_record": wts[0][1] if wts else wops[0][4],
                     "last_write": iso(wts[-1][0]) if wts else None,
                     "pickups": len(pk), "readers": pk[:8],
                     "first_wait_h": min(w) if w else None,
                     "median_wait_h": round(statistics.median(w), 2) if w else None,
                     "status": "never" if not pk else "one" if len(pk) == 1 else "many"})
    rows.sort(key=lambda r: (-r["pickups"], r["first_write"] or "~", r["channel"]))
    hist = [0] * len(WAIT_BINS)
    for x in waits:
        for i, (hi, _) in enumerate(WAIT_BINS):
            if x < hi:
                hist[i] += 1
                break
    out = {"rows": rows, "total": len(rows), "multi_writer_places": multi,
           "never": sum(1 for r in rows if r["status"] == "never"),
           "one": sum(1 for r in rows if r["status"] == "one"),
           "many": sum(1 for r in rows if r["status"] == "many"),
           "pickups": len(waits), "median_wait_h": round(statistics.median(waits), 2) if waits else None,
           "hist": [{"bin": lab, "n": n} for (hi, lab), n in zip(WAIT_BINS, hist)]}
    s._fx_drops = out
    return out


def drops_csv(s):
    d = drops(s)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["place", "place_type", "writer", "writes", "first_write", "first_write_record", "status",
                "reader", "read_time", "read_record", "picked_up_write_record", "wait_hours"])
    n = 0
    for r in d["rows"]:
        base = [r["channel"], r["type"], r["writer"], r["writes"], r["first_write"] or "", r["first_write_record"], r["status"]]
        pk = _all_pickups(s, r)
        if not pk:
            w.writerow(base + ["", "", "", "", ""])
            n += 1
        for p in pk:
            w.writerow(base + [p["actor"], p["read_time"] or "", p["read_record"], p["write_record"],
                               "" if p["wait_h"] is None else p["wait_h"]])
            n += 1
    return {"csv": buf.getvalue(), "rows": n, "filename": "dead_drops.csv"}


def _all_pickups(s, r):
    if r["pickups"] <= len(r["readers"]):
        return r["readers"]
    firsts = {}
    for d in sorted(s.del_by_channel.get(r["channel"], []), key=lambda d: (d["read_time"] is None, d["read_time"] or 0)):
        if d["to"] != r["writer"]:
            firsts.setdefault(d["to"], d)
    return [{"actor": b, "read_record": d["read_id"], "read_time": iso(d["read_time"]), "write_record": d["write_id"],
             "wait_h": d["latency_h"]} for b, d in firsts.items()]


# ------------------------------------------------------------------ 5. better search

_TOK = re.compile(r'\s*(?:(\()|(\))|"([^"]*)"|(\S+))')


def parse_query(q):
    """Boolean query -> (predicate on lowered text, positive terms for highlighting).
    Words and "quoted phrases"; AND (or a space), OR, NOT (or a leading -); parentheses.
    NOT binds tightest, then AND, then OR. Matching is case-insensitive substring."""
    toks = []
    q = re.sub(r'(?i)(?<!["\w])cred (\d+)\b', r'"[CREDENTIAL \1]"', q)
    for m in _TOK.finditer(q):
        if m.group(1):
            toks.append(("(", None))
        elif m.group(2):
            toks.append((")", None))
        elif m.group(3) is not None:
            if m.group(3):
                toks.append(("term", _norm_query(m.group(3)).lower()))
        else:
            w = m.group(4)
            if w in ("AND", "&&"):
                toks.append(("and", None))
            elif w in ("OR", "||", "|"):
                toks.append(("or", None))
            elif w == "NOT":
                toks.append(("not", None))
            elif w.startswith("-") and len(w) > 1:
                toks.append(("not", None))
                toks.append(("term", w[1:].lower()))
            else:
                # a closing parenthesis glued to a word
                tail = 0
                while w.endswith(")") and len(w) > 1:
                    w, tail = w[:-1], tail + 1
                head = 0
                while w.startswith("(") and len(w) > 1:
                    w, head = w[1:], head + 1
                toks += [("(", None)] * head + [("term", w.lower())] + [(")", None)] * tail
    pos = []
    i = [0]

    def peek():
        return toks[i[0]][0] if i[0] < len(toks) else None

    def take():
        i[0] += 1
        return toks[i[0] - 1]

    def p_or():
        parts = [p_and()]
        while peek() == "or":
            take()
            parts.append(p_and())
        return parts[0] if len(parts) == 1 else (lambda t, ps=parts: any(p(t) for p in ps))

    def p_and():
        parts = [p_not()]
        while peek() in ("and", "term", "not", "("):
            if peek() == "and":
                take()
            parts.append(p_not())
        return parts[0] if len(parts) == 1 else (lambda t, ps=parts: all(p(t) for p in ps))

    def p_not(neg=False):
        k = peek()
        if k == "not":
            take()
            f = p_not(not neg)
            return lambda t, f=f: not f(t)
        if k == "(":
            take()
            f = p_or()
            if peek() == ")":
                take()
            return f
        if k == "term":
            w = take()[1]
            if not neg:
                pos.append(w)
            return lambda t, w=w: w in t
        if k is None:
            raise ValueError("the search ends where a word was expected")
        take()
        raise ValueError(f"unexpected {k.upper() if k in ('and', 'or') else k} in the search")

    if not toks:
        return None, []
    f = p_or()
    if i[0] < len(toks):
        raise ValueError("unbalanced parentheses in the search")
    return f, pos


def _hour_ok(t, hour):
    if not hour:
        return True
    if t is None:
        return False
    h = iso(t)[:13]
    if ".." in hour:
        lo, hi = hour.split("..", 1)
        return lo <= h <= hi
    return h.startswith(hour)


def search(s, q="", kind="", intent="", actor="", hour="", offset=0, limit=100):
    ix = _ix(s)
    q = (q or "").strip()
    rx = _regex(q) if q else None
    pred, terms = (None, []) if rx is not None or not q else parse_query(q)
    times, intents = s.rec["_times"], s.rec["_intents"]
    low = ix["low"]
    out, total = [], 0
    kinds, intents_c, actors_c, hours = Counter(), Counter(), Counter(), Counter()
    for i, e in enumerate(s.events):
        if kind and e.kind != kind:
            continue
        it = intents.get(e.id)
        if intent and it != intent:
            continue
        a = s.actor[e.id][0]
        if actor and a != actor:
            continue
        t = times.get(e.id)
        if hour and not _hour_ok(t, hour):
            continue
        if rx is not None:
            m = rx.search(e.text)
            if not m:
                continue
        elif pred is not None:
            hay = low[i]
            if not pred(hay) and not pred(e.id.lower()):
                continue
        if offset <= total < offset + limit:
            row = s.event_row(e)
            if rx is not None:
                row["snip"] = _snip(e.text, m.start(), m.end())
            else:
                j = min((p for p in (low[i].find(w) for w in terms) if p >= 0), default=-1)
                row["snip"] = _snip(e.text, j, j + 1) if j >= 0 else row["preview"]
            out.append(row)
        total += 1
        kinds[e.kind] += 1
        if it:
            intents_c[it] += 1
        actors_c[a] += 1
        if t is not None:
            hours[iso(t)[:13]] += 1
    return {"q": q, "regex": rx is not None, "terms": terms, "total": total, "offset": offset, "rows": out,
            "facets": {"kind": dict(kinds.most_common()), "intent": dict(intents_c.most_common()),
                       "actor": [[a, n] for a, n in actors_c.most_common(12)]},
            "hist": sorted(hours.items()), "timed": sum(hours.values())}


def like(s, rid, top=10, max_group=5000):
    """Records like this one: same program (masked text), same start of code, same places, same tokens.
    Groups bigger than max_group records (a key every agent uses, a place everyone polls) say nothing
    about this record in particular and are left out; the answer says which."""
    e = s.by_id.get(rid)
    if e is None:
        raise LookupError(f"no record {rid}")
    fam = insight.family_index(s)
    ix = _ix(s)
    shared = set(s.pack.raw.get("shared_identities", []))
    score, why = defaultdict(float), defaultdict(list)
    skipped = []
    f = fam.get(rid)
    if f:
        for o in s.by_family[f]:
            score[o] += 3
            why[o].append("same program")
    p = s.prefix.get(rid)
    if p:
        for o in s.by_prefix[p]:
            score[o] += 2
            why[o].append("code starts the same way")
    for ch in {o["channel"] for o in s.ops_by_id.get(rid, [])}:
        recs = {r for _, _, _, _, r in s.ops_by_channel.get(ch, [])}
        if len(recs) > max_group:
            skipped.append({"what": "place", "key": ch, "records": len(recs)})
            continue
        w = 1.5 / math.log(2 + len(recs))
        for o in recs:
            score[o] += w
            why[o].append("place " + ch)
    for tok in s.rec["_ids"].get(rid, {}):
        if tok in shared:
            skipped.append({"what": "shared key", "key": tok, "records": len(ix["tok_recs"].get(tok, []))})
            continue
        recs = ix["tok_recs"].get(tok, [])
        if len(recs) > max_group:
            skipped.append({"what": "token", "key": tok, "records": len(recs)})
            continue
        w = 1.5 / math.log(2 + len(recs))
        for o in recs:
            score[o] += w
            why[o].append("token " + tok)
    score.pop(rid, None)
    best = sorted(score, key=lambda o: (-score[o], s.order[o]))[:top]
    rows = []
    for o in best:
        r = s.event_row(s.by_id[o])
        ws = why[o]
        r["why"] = list(dict.fromkeys(w for w in ws if not w.startswith(("place ", "token "))))
        r["places"] = [w[6:] for w in dict.fromkeys(ws) if w.startswith("place ")][:4]
        r["tokens"] = [w[6:] for w in dict.fromkeys(ws) if w.startswith("token ")][:4]
        r["score"] = round(score[o], 2)
        rows.append(r)
    return {"id": rid, "candidates": len(score), "rows": rows, "skipped": skipped,
            "same_program": len(s.by_family.get(f, [])) - 1 if f else 0,
            "same_start": len(s.by_prefix.get(p, [])) - 1 if p else 0}


# ------------------------------------------------------------------ routes

def _int(q, k, d, lo=0, hi=10 ** 6):
    try:
        return max(lo, min(hi, int(q.get(k, d))))
    except (TypeError, ValueError):
        raise ValueError(f"{k} must be a number")


GET = {
    "fx_trace": lambda st, q: trace(_sess(st), q.get("q", ""), _int(q, "limit", 5000, 1, 5000)),
    "fx_credentials": lambda st, q: credentials(_sess(st)),
    "fx_c2": lambda st, q: c2_list(_sess(st)),
    "fx_c2_place": lambda st, q: c2_place(_sess(st), q.get("ch", "")),
    "fx_drops": lambda st, q: {k: (v[:_int(q, "limit", 2000, 1, 10 ** 6)] if k == "rows" else v)
                               for k, v in drops(_sess(st)).items()},
    "fx_drops_csv": lambda st, q: drops_csv(_sess(st)),
    "fx_search": lambda st, q: search(_sess(st), q.get("q", ""), q.get("kind", ""), q.get("intent", ""),
                                      q.get("actor", ""), q.get("hour", ""), _int(q, "offset", 0),
                                      _int(q, "limit", 100, 1, 1000)),
    "fx_like": lambda st, q: like(_sess(st), q.get("id", ""), _int(q, "top", 10, 1, 50)),
}
POST = {}

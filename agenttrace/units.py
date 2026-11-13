"""Units: count by estimated agent instead of token.

A token (or self-chosen name) is not an agent. The Agents tab proposes which named actors one agent
holds; the What-if "estimate" rule joins the high-confidence proposals (and the investigator's accepted
ones, never a rejected one) into estimated agents. This module serves that mapping and the recount by
agent, so every tab can count agents by default. The merge rule and the recount of messages and warning
signs are fx_whatif's (_agent_map, whatif); here they are only reshaped, plus the pair breakdown.
"""
from collections import defaultdict

from . import fx_whatif, identity, insight

RULE = "estimate"
_CONF_ORDER = {None: 0, "low": 1, "medium": 2, "high": 3}
TOP_PAIRS = 60


def _letters(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _links(s):
    """Every merge link the rule uses: (a, b) -> {confidence, score, decision}."""
    base, dec = identity._base(s), identity._decisions(s)
    out = {}
    for x in base["scored"]:
        k = (x["a"], x["b"]) if x["a"] < x["b"] else (x["b"], x["a"])
        v = dec.get(k)
        if v == "accept" or (v != "reject" and x["confidence"] == "high"):
            out[k] = {"a": k[0], "b": k[1], "confidence": x["confidence"], "score": x["score"], "decision": v}
    for k, v in dec.items():
        if v == "accept" and k not in out:
            out[k] = {"a": k[0], "b": k[1], "confidence": None, "score": 0, "decision": v}
    return out


def agents(s):
    """The estimated agents that join two or more tokens, biggest first, and token -> agent id."""
    amap, groups, named, merges = fx_whatif._agent_map(s, RULE)
    links = _links(s)
    rows = []
    for i, g in enumerate(groups):
        gs = set(g)
        inside = [x for (a, b), x in links.items() if a in gs and b in gs]
        weakest = min(inside, key=lambda x: (_CONF_ORDER.get(x["confidence"], 0), x["score"])) if inside else None
        name = "Agent " + _letters(i)
        rows.append({"id": g[0], "name": name, "label": f"{name} · {len(g)} tokens", "tokens": g,
                     "records": sum(len(s.by_actor.get(a, [])) for a in g),
                     "confidence": (weakest["confidence"] or "accepted") if weakest else None,
                     "weakest": weakest, "links": len(inside)})
    return rows, amap, named, merges


def units_map(s):
    rows, amap, named, merges = agents(s)
    w = fx_whatif.whatif(s, RULE)
    a, b = w["as_counted"], w["after"]
    return {
        "dataset": s.name, "rule": RULE, "default_unit": "agent",
        "tokens": len(named), "agents": b["agents"], "merged_agents": len(rows),
        "merged_tokens": sum(len(r["tokens"]) for r in rows), "merges": sum(len(r["tokens"]) - 1 for r in rows),
        "no_merges": not rows,
        "messages": {"token": a["messages"], "agent": b["messages"], "inside_one_agent": b["inside_one_agent"],
                     "rejected": b["rejected_messages"]},
        "pairs": {"token": a["pairs"], "agent": b["pairs"]},
        "decisions": merges,
        "agent_list": rows,
        "of": {t: r["id"] for r in rows for t in r["tokens"]},
        "note": ("no tokens are merged in this trace" if not rows else
                 "estimated agents: tokens merged on direct evidence; change in Agents"),
    }


def _pairs(s, amap, rejected):
    """Messages between named actors grouped by (agent, agent), with the token pairs inside each."""
    ag = lambda x: amap.get(x, x)
    pairs, inside = {}, {}
    sent, recv, within = defaultdict(int), defaultdict(int), defaultdict(int)
    for d in s.flow["_deliveries"]:
        if not (insight.is_named(d["from"]) and insight.is_named(d["to"])):
            continue
        if rejected and (d["write_id"] + ">" + d["read_id"]) in rejected:
            continue
        a, b = ag(d["from"]), ag(d["to"])
        if a == b:
            within[a] += 1
            book = inside.setdefault(a, {"agent": a, "messages": 0, "_tp": defaultdict(int), "first": None, "last": None})
        else:
            sent[a] += 1
            recv[b] += 1
            book = pairs.setdefault((a, b), {"from": a, "to": b, "messages": 0, "_tp": defaultdict(int), "first": None, "last": None})
        book["messages"] += 1
        book["_tp"][(d["from"], d["to"])] += 1
        t = d.get("read_time")
        if t is not None:
            book["first"] = t if book["first"] is None else min(book["first"], t)
            book["last"] = t if book["last"] is None else max(book["last"], t)

    def done(x):
        tp = x.pop("_tp")
        x["token_pairs"] = [{"from": f, "to": t, "messages": n} for (f, t), n in sorted(tp.items(), key=lambda p: (-p[1], p[0]))]
        for k in ("first", "last"):
            x[k] = fx_whatif.iso(x[k]) if x[k] is not None else None
        return x
    plist = sorted((done(x) for x in pairs.values()), key=lambda x: (-x["messages"], x["from"], x["to"]))
    for x in plist:
        x["back"] = pairs.get((x["to"], x["from"]), {}).get("messages", 0)
    ilist = sorted((done(x) for x in inside.values()), key=lambda x: (-x["messages"], x["agent"]))
    return plist, ilist, sent, recv, within


def units_summary(s, unit="agent"):
    if unit not in ("agent", "token"):
        raise ValueError("unit must be agent or token")
    w = fx_whatif.whatif(s, RULE)
    rows, amap, named, merges = agents(s)
    by_agent = unit == "agent"
    side = w["after"] if by_agent else w["as_counted"]
    rejected = set(fx_whatif.load_decisions(s)["messages"]) if by_agent else set()
    plist, ilist, sent, recv, within = _pairs(s, amap if by_agent else {}, rejected)
    info = {r["id"]: r for r in rows} if by_agent else {}
    ids = set(sent) | set(recv) | set(within)
    totals = sorted(({"id": a, "label": info[a]["label"] if a in info else a, "tokens": len(info[a]["tokens"]) if a in info else 1,
                      "sent": sent.get(a, 0), "received": recv.get(a, 0), "inside": within.get(a, 0)} for a in ids),
                    key=lambda x: (-(x["sent"] + x["received"] + x["inside"]), x["id"]))
    signs = []
    for g in w["signs"]:
        counted = {"time": g["time"], "harm_share_after": g["harm_share_after"], "record": g.get("record")}
        after = g.get("after")
        agent = ({"time": after["time"], "harm_share_after": after["harm_share_after"], "record": after.get("record")}
                 if after else None)
        signs.append({"key": g["key"], "name": g["name"], "family": g["family"], "kind": g["kind"],
                      "status": g["status"], "as_counted": counted, "by_agent": agent,
                      "value": agent if by_agent else counted})
    nums = lambda x: {k: x[k] for k in ("messages", "pairs", "inside_one_agent", "largest_group", "first_message")}
    return {
        "dataset": s.name, "unit": unit, "rule": RULE,
        "tokens": len(named), "agents": w["after"]["agents"], "merged_agents": len(rows), "no_merges": not rows,
        "units": side["agents"],
        "messages": side["messages"], "pairs": side["pairs"], "inside_one_agent": side["inside_one_agent"],
        "largest_group": side["largest_group"], "rejected_messages": side["rejected_messages"],
        "first_message": side["first_message"],
        "top_pairs": plist[:TOP_PAIRS], "pairs_listed": min(len(plist), TOP_PAIRS),
        "inside": ilist, "totals": totals[:200],
        "signs": signs, "first_joint": w["first_joint"],
        "as_counted": nums(w["as_counted"]), "by_agent": nums(w["after"]),
        "note": ("no tokens are merged in this trace" if not rows else
                 "estimated agents: tokens merged on direct evidence; change in Agents"),
    }


def _get_map(state, q):
    return units_map(fx_whatif._session(state))


def _get_summary(state, q):
    return units_summary(fx_whatif._session(state), q.get("unit") or "agent")


# ------------------------------------------------------------------ places: writers and readers by agent

def _bin(n):
    """The Channels grid's bins for a count of writers or readers (0, 1, 2, 3-4, 5-9, 10+); only used to say which cell."""
    return 0 if n <= 0 else n if n <= 2 else 3 if n <= 4 else 4 if n <= 9 else 5


def units_places(s):
    """Every place counted by agent: who wrote and read it, and which places carried a message between two
    agents. Rows: [place, writers, readers, messages, messages_named, never_read, writers_as_counted,
    readers_as_counted]. A place whose only readers are other tokens of the writing agent no longer carries a message."""
    rows, amap, named, merges = agents(s)
    rejected = set(fx_whatif.load_decisions(s)["messages"])
    ag = lambda x: amap.get(x, x)
    dels = {}
    for d in s.flow["_deliveries"]:
        if (d["write_id"] + ">" + d["read_id"]) in rejected:
            continue
        a, b = ag(d["from"]), ag(d["to"])
        if a == b:
            continue
        r = dels.setdefault(d["channel"], [0, 0])
        r[0] += 1
        if insight.is_named(d["from"]) and insight.is_named(d["to"]):
            r[1] += 1
    out = []
    moved = moved_cell = 0
    tot = {"places": 0, "msg_token": 0, "msg_agent": 0, "never_token": 0, "never_agent": 0, "messages_agent": 0, "messages_named_agent": 0}
    for c in s.flow.get("_channels", s.flow["top_channels"]):
        ch = c["channel"]
        ops = s.ops_by_channel.get(ch)
        if ops is None:       # a place with no recorded operations: its deliveries are all there is
            wt = {d["from"] for d in s.del_by_channel.get(ch, [])}
            rt = {d["to"] for d in s.del_by_channel.get(ch, [])}
        else:
            wt = {o[1] for o in ops if o[0] in ("write", "post")}
            rt = {o[1] for o in ops if o[0] in ("read", "post")}
        wa, ra = len({ag(x) for x in wt}), len({ag(x) for x in rt})
        wtok, rtok = c["writers"], c["readers"]
        m, mn = dels.get(ch, (0, 0))
        never = 1 if (c["writes"] > 0 and m == 0) else 0
        if (wa, ra) != (wtok, rtok):
            moved += 1
            if (_bin(wa), _bin(ra)) != (_bin(wtok), _bin(rtok)):
                moved_cell += 1
        tot["places"] += 1
        tot["msg_token"] += 1 if c["deliveries"] else 0
        tot["msg_agent"] += 1 if m else 0
        tot["never_token"] += 1 if c["never_read"] else 0
        tot["never_agent"] += never
        tot["messages_agent"] += m
        tot["messages_named_agent"] += mn
        out.append([ch, wa, ra, m, mn, never, wtok, rtok])
    tot.update({"moved": moved, "moved_cells": moved_cell, "no_merges": not rows})
    return {"dataset": s.name, "columns": ["channel", "writers", "readers", "messages", "messages_named", "never_read",
                                          "writers_as_counted", "readers_as_counted"], "rows": out, "summary": tot}


# ------------------------------------------------------------------ spread: adopters by agent

def units_spread(s):
    """The programs run by two or more named actors, with the actors counted as agents: a program run by three tokens
    of one agent has one adopter (or none: it drops out of the list when only one agent ran it). Same row shape as /api/spread."""
    rows, amap, named, merges = agents(s)
    ag = lambda x: amap.get(x, x)
    out, dropped = [], []
    tok_ad = ag_ad = inside = 0
    for x in insight.spread_detail(s):
        src = ag(x["source"])
        seen, ads = {src}, []
        n_inside = 0
        for a in x["adopters"]:
            g = ag(a["actor"])
            if g in seen:
                n_inside += 1
                continue
            seen.add(g)
            ads.append({**a, "actor": g, "token": a["actor"]})
        tok_ad += len(x["adopters"])
        ag_ad += len(ads)
        inside += n_inside
        row = {**x, "source": src, "source_token": x["source"], "adopters": ads, "actors": 1 + len(ads),
               "token_actors": x["actors"], "inside_one_agent": n_inside}
        (out if ads else dropped).append(row)
    actors, adopt = set(), set()
    for x in out:
        actors.add(x["source"])
        for a in x["adopters"]:
            actors.add(a["actor"])
            adopt.add(a["actor"])
    tokens = set()
    for x in insight.spread_detail(s):
        tokens.add(x["source"])
        tokens.update(a["actor"] for a in x["adopters"])
    return {"dataset": s.name, "rows": out, "dropped": len(dropped),
            "summary": {"programs_agent": len(out), "programs_token": len(out) + len(dropped), "dropped": len(dropped),
                        "adoptions_agent": ag_ad, "adoptions_token": tok_ad, "inside_one_agent": inside,
                        "agents": len(actors), "adopter_agents": len(adopt), "start_only_agents": len(actors - adopt),
                        "tokens": len(tokens), "no_merges": not rows}}


# ------------------------------------------------------------------ events: an agent as the actor filter

def _tokens_of(s, who):
    """The tokens an actor filter stands for in agent mode: an agent's tokens, or the one token."""
    rows, amap, named, merges = agents(s)
    ids = [t for t, g in amap.items() if g == amap.get(who, who)]
    return ids or [who]


def _events_get(state, q):
    s = fx_whatif._session(state)
    who = q.get("actor") or ""
    kw = lambda actor, off, lim: s.search(q.get("q", ""), q.get("kind", ""), actor, q.get("intent", ""), q.get("tag", ""),
                                          q.get("channels") == "1", off, lim, q.get("hour", ""))
    off, lim = int(q.get("offset") or 0), min(500, int(q.get("limit") or 100))
    toks = _tokens_of(s, who) if who else []
    if len(toks) > 1:     # an agent: the union of its tokens' records, in the trace's order
        rs = [kw(t, 0, off + lim) for t in toks]
        order = {e.id: i for i, e in enumerate(s.events)}
        rows = sorted((r for x in rs for r in x["rows"]), key=lambda r: order.get(r["id"], 0))[off:off + lim]
        add = lambda key: _sum_dicts([x["facets"][key] for x in rs])
        hist = _sum_dicts([dict(x["hist"]) for x in rs])
        hby = {}
        for x in rs:
            for h, c in x["hist_by"]:
                hby[h] = _sum_dicts([hby.get(h, {}), c])
        res = {"total": sum(x["total"] for x in rs), "offset": off, "rows": rows,
               "facets": {"kind": add("kind"), "intent": add("intent"), "actor": [[who, sum(x["total"] for x in rs)]]},
               "hist": sorted(hist.items()), "timed": sum(hist.values()), "hist_by": [[h, hby[h]] for h in sorted(hby)]}
    else:
        res = kw(toks[0] if toks else "", off, lim)
        if not who:       # no actor filter: the busiest actors, counted by agent
            res["facets"]["actor"] = _actor_facet(s, q)
    res["agent_tokens"] = len(toks)
    return res


def _sum_dicts(ds):
    out = {}
    for d in ds:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def _actor_facet(s, q, top=12):
    """The busiest actors among the matching records, one count per agent. (Same filters as Session.search.)"""
    from . import reconstruct
    rows, amap, named, merges = agents(s)
    kind, intent, tag, hour, ql = q.get("kind", ""), q.get("intent", ""), q.get("tag", ""), q.get("hour", ""), (q.get("q", "") or "").lower().strip()
    chan = q.get("channels") == "1"
    cnt = defaultdict(int)
    for e in s.events:
        if kind and e.kind != kind:
            continue
        if intent and s.rec["_intents"].get(e.id) != intent:
            continue
        if tag and tag not in s.res["_evidence"][e.id]:
            continue
        if chan and not s.ops_by_id.get(e.id):
            continue
        if hour:
            t = s.rec["_times"].get(e.id)
            if t is None:
                continue
            h = reconstruct.iso(t)[:13]
            if ".." in hour:
                lo, hi = hour.split("..", 1)
                if not (lo <= h <= hi):
                    continue
            elif not h.startswith(hour):
                continue
        if ql and ql not in e.id.lower() and ql not in e.text.lower() and ql not in (e.actor or "").lower() and ql not in (e.channel or "").lower():
            continue
        a = s.actor[e.id][0]
        cnt[amap.get(a, a)] += 1
    return sorted(([a, n] for a, n in cnt.items()), key=lambda x: (-x[1], x[0]))[:top]


def _get_places(state, q):
    return units_places(fx_whatif._session(state))


def _get_spread(state, q):
    return units_spread(fx_whatif._session(state))


GET = {"units_map": _get_map, "units_summary": _get_summary, "units_places": _get_places,
       "units_spread": _get_spread, "units_events": _events_get}
POST = {}

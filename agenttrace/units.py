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


GET = {"units_map": _get_map, "units_summary": _get_summary}
POST = {}

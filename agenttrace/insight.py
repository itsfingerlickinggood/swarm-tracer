"""Derived views for the app, all computed from one loaded Session.

- actor_profile: everything one actor did, sent, received, reused and triggered
- place_detail: every write and read on one place, and the messages through it
- lanes: per-actor activity by hour, for the swimlane timeline
- messages: every message (delivery) in compact form, for graphs that grow over time
- simulate: an hour-by-hour replay of the incident with every early-warning sign
- explain: a plain-language account of one record and its role in the swarm
- context: the incident context file and milestone check that match this dataset

Nothing here is specific to one dataset: names come from the pack, and every number is counted
from the records.
"""
import json
import math
import os
import re
from collections import Counter, defaultdict

from . import reconstruct

HOUR = 3600.0
iso = reconstruct.iso
CLAIMS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims")
RUNS = "(anonymous runs)"


def _hour(t):
    return int(math.floor(t / HOUR))


def _hour_iso(h):
    return iso(h * HOUR)[:13]


def human(name):
    return str(name or "").replace("_", " ")


def is_named(actor):
    return bool(actor) and not str(actor).startswith("run:")


# ------------------------------------------------------------------ names from the pack

def intent_names(pack):
    """Plain descriptions of intents. Packs may give them; otherwise the name is used."""
    d = dict(pack.raw.get("intent_descriptions", {}))
    for name, _ in pack.intents:
        d.setdefault(name, human(name).capitalize())
    d.setdefault("other", "No known pattern")
    return d


def tag_names(pack):
    return {b.name: (b.description or human(b.name).capitalize()) for b in pack.behaviors}


def tag_stage(pack):
    return {b.name: b.stage for b in pack.behaviors}


SIGNAL_NAMES = {
    "registry_board": "Registry mailbox first used", "docker_registry": "Docker registry first used",
    "hf_dataset_write": "First Hugging Face dataset write", "kubernetes_api": "Kubernetes API first called",
    "cloud_metadata": "Cloud metadata first requested", "probe_request": "First probe request",
    "hides_page": "First page hidden", "proxy_link": "First proxy link", "recreated_after_delete": "Page recreated after a delete",
    "runs_shell": "First shell command", "handles_secrets": "First secret handled", "sends_data": "First data sent out",
    "deletes": "First delete",
}


def signal_name(sig, ref=None):
    """(name, family) for a replay signal. family: single (one actor) or joint (actors together)."""
    s = str(sig)
    if s.startswith("first message"):
        return "First message between named actors", "joint"
    if s.startswith("coordination: one identity carries"):
        return "One identity carries another's token", "joint"
    if s.startswith("coordination: two identities"):
        return ("Two identities share " + (f"place {ref}" if ref and len(str(ref)) < 24 else "one place")), "joint"
    if s.startswith("coordination"):
        return s.replace("coordination:", "").strip().capitalize(), "joint"
    if s.startswith("spread"):
        return "Token seen as data, then used", "single"
    key = s.replace("first:", "").strip()
    return SIGNAL_NAMES.get(key, "First " + human(key)), "single"


# ------------------------------------------------------------------ indexes (built once per session)

def build_indexes(s):
    s.by_actor = defaultdict(list)
    for e in s.events:
        s.by_actor[s.actor[e.id][0]].append(e.id)
    s.ops_by_channel = defaultdict(list)
    s.ops_by_actor = defaultdict(list)
    for ch, op, a, ak, t, i, rid in s.op_list:
        s.ops_by_channel[ch].append((op, a, ak, t, rid))
        s.ops_by_actor[a].append((ch, op, t, rid))
    s.del_by_channel = defaultdict(list)
    s.del_by_actor_out = defaultdict(list)
    s.del_by_actor_in = defaultdict(list)
    for d in s.flow["_deliveries"]:
        s.del_by_channel[d["channel"]].append(d)
        s.del_by_actor_out[d["from"]].append(d)
        s.del_by_actor_in[d["to"]].append(d)
    s.over_by_channel = defaultdict(list)
    for d in s.flow.get("_overwrites", []):
        s.over_by_channel[d["channel"]].append(d)
    s.channel_row = {c["channel"]: c for c in s.flow.get("_channels", s.flow["top_channels"])}
    harm = s.pack.harm
    ev = s.res["_evidence"]
    s.harmful = {e.id for e in s.events if reconstruct.is_action(e, s.pack)
                 and (s.rec["_intents"].get(e.id) in harm or any(x in harm for x in ev[e.id]))}
    # which records start or adopt a program several actors ran
    s.spread_role = {}
    for i, x in enumerate(s.flow.get("_content_spread", [])):
        s.spread_role.setdefault(x["source_record"], ("source", i))
        for a in x["adopters"]:
            s.spread_role.setdefault(a["record"], ("adopter", i))
    s.harm_sorted = sorted(s.rec.get("_harm_times", []))


def family_index(s):
    """record id -> program family (identical text once ids, numbers and hashes are masked), built once."""
    if getattr(s, "_fam", None) is None:
        from . import messages
        s._fam = messages.families(s.events)
        s.by_family = defaultdict(list)
        for rid, f in s._fam.items():
            s.by_family[f].append(rid)
    return s._fam


def harm_share_after(s, t):
    h = s.harm_sorted
    if not h or t is None:
        return None
    import bisect
    return round((len(h) - bisect.bisect_right(h, t)) / len(h), 3)


# ------------------------------------------------------------------ actor profile

def actor_profile(s, actor, top=12):
    ids = s.by_actor.get(actor)
    if not ids:
        raise LookupError(f"no actor named {actor}")
    times, intents = s.rec["_times"], s.rec["_intents"]
    kind = s.actor[ids[0]][1]
    hourly, ic, kinds, tags = Counter(), Counter(), Counter(), Counter()
    ts = []
    for rid in ids:
        t = times.get(rid)
        if intents.get(rid):
            ic[intents[rid]] += 1
        kinds[s.by_id[rid].kind] += 1
        for g in s.res["_evidence"][rid]:
            tags[g] += 1
        if t is not None:
            hourly[iso(t)[:13]] += 1
            ts.append((t, rid))
    ts.sort()
    sent, got = s.del_by_actor_out.get(actor, []), s.del_by_actor_in.get(actor, [])
    p_out, p_in = Counter(d["to"] for d in sent), Counter(d["from"] for d in got)
    acts = [rid for rid in ids if reconstruct.is_action(s.by_id[rid], s.pack)]
    places = defaultdict(Counter)
    for ch, op, t, rid in s.ops_by_actor.get(actor, []):
        places[ch][op] += 1
    place_rows = sorted(({"channel": ch, **dict(c), "total": sum(c.values())} for ch, c in places.items()),
                        key=lambda r: -r["total"])
    started, adopted = [], []
    for x in s.flow.get("_content_spread", []):
        if x["source"] == actor:
            started.append({"family": x["family"], "actors": x["actors"], "copies": x["copies"],
                            "record": x["source_record"], "time": x["source_time"], "what": program_gist(s, x["source_record"])})
        else:
            for a in x["adopters"]:
                if a["actor"] == actor:
                    adopted.append({"family": x["family"], "source": x["source"], "record": a["record"], "time": a["time"],
                                    "hours_after_source": a["hours_after_source"], "what": program_gist(s, x["source_record"])})
    ident = next((i for i in s.rec["identities"] if i["identity"] == actor), None)
    sigs = [g for g in simulate(s)["signals"] if actor in (g.get("actors") or [])]
    carried = [c for c in s.rec["carried_edges"] if actor in (c["from"], c["to"])]
    stu = [x for x in s.rec["seen_then_used"] if x["item"] == actor]
    harmful = sum(1 for rid in ids if rid in s.harmful)
    names_i = intent_names(s.pack)
    names_t = tag_names(s.pack)
    return {
        "actor": actor, "kind": kind, "records": len(ids), "timed": len(ts),
        "actions": len(acts), "timed_actions": sum(1 for rid in acts if rid in times),
        "sent_named": sum(1 for d in sent if is_named(d["to"])), "received_named": sum(1 for d in got if is_named(d["from"])),
        "partners_named": len({a for a in set(p_out) | set(p_in) if is_named(a)}),
        "first": iso(ts[0][0]) if ts else None, "last": iso(ts[-1][0]) if ts else None,
        "first_record": ts[0][1] if ts else ids[0], "last_record": ts[-1][1] if ts else ids[-1],
        "hourly": sorted(hourly.items()),
        "intents": [{"intent": k, "n": n, "what": names_i.get(k, human(k))} for k, n in ic.most_common()],
        "kinds": dict(kinds),
        "tags": [{"tag": k, "n": n, "what": names_t.get(k, human(k))} for k, n in tags.most_common(top)],
        "harmful": harmful,
        "sent": len(sent), "received": len(got),
        "sends_to": [{"actor": a, "n": n} for a, n in p_out.most_common(top)],
        "hears_from": [{"actor": a, "n": n} for a, n in p_in.most_common(top)],
        "partners": len(set(p_out) | set(p_in)),
        "places": place_rows[:top], "places_total": len(place_rows),
        "programs_started": started[:top], "programs_started_total": len(started),
        "programs_adopted": adopted[:top], "programs_adopted_total": len(adopted),
        "signals": sigs,
        "carried": carried[:top],
        "seen_then_used": stu,
        "identity": ident,
        "shared": actor in set(s.pack.raw.get("shared_identities", [])),
    }


# ------------------------------------------------------------------ place detail

def place_detail(s, channel, limit=400):
    ops = s.ops_by_channel.get(channel)
    if ops is None:
        raise LookupError(f"no place named {channel}")
    rows = sorted(ops, key=lambda o: (o[3] is None, o[3] or 0))
    writers, readers = Counter(), Counter()
    hourly = defaultdict(Counter)
    for op, a, ak, t, rid in rows:
        (writers if op in ("write", "post") else readers)[a] += 1
        if op == "post":
            readers[a] += 0
        if t is not None:
            hourly[iso(t)[:13]][op] += 1
    dels = sorted(s.del_by_channel.get(channel, []), key=lambda d: d["read_time"])
    over = s.over_by_channel.get(channel, [])
    coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
    return {
        "channel": channel, "type": channel.split(":", 1)[0], "name": channel.split(":", 1)[-1],
        "merged": any(r.search(channel) for r in coarse),
        "row": s.channel_row.get(channel),
        "ops_total": len(rows),
        "ops": [{"op": op, "actor": a, "actor_kind": ak, "time": iso(t), "record": rid} for op, a, ak, t, rid in rows[:limit]],
        "writers": [{"actor": a, "n": n} for a, n in writers.most_common()],
        "readers": [{"actor": a, "n": n} for a, n in readers.most_common()],
        "hourly": sorted((h, dict(c)) for h, c in hourly.items()),
        "messages": [{"from": d["from"], "to": d["to"], "write_id": d["write_id"], "read_id": d["read_id"],
                      "write_time": iso(d["write_time"]), "read_time": iso(d["read_time"]), "latency_h": d["latency_h"],
                      "how": d.get("how")} for d in dels[:limit]],
        "messages_total": len(dels),
        "overwrites": len(over),
    }


def places_map(s):
    """Every place, compact, for the map of all places."""
    out = []
    for c in s.flow.get("_channels", s.flow["top_channels"]):
        out.append([c["channel"], c["writes"], c["reads"], c["writers"], c["readers"], c["deliveries"],
                    c.get("overwrites", 0), 1 if c["never_read"] else 0, c.get("first_write") or c.get("first_read")])
    return {"columns": ["channel", "writes", "reads", "writers", "readers", "messages", "overwrites", "never_read", "first"],
            "rows": out}


# ------------------------------------------------------------------ swimlanes and messages

def lanes(s):
    times, intents = s.rec["_times"], s.rec["_intents"]
    order = [k for k, _ in Counter(v for v in intents.values() if v).most_common()]
    idx = {k: i for i, k in enumerate(order)}
    bins = defaultdict(lambda: defaultdict(lambda: [0] * len(order)))
    harm = defaultdict(Counter)
    meta = {}
    h_lo = h_hi = None
    for e in s.events:
        t = times.get(e.id)
        it = intents.get(e.id)
        if t is None or not it:
            continue
        a, ak = s.actor[e.id]
        key = a if ak != "run" else RUNS
        h = _hour(t)
        h_lo = h if h_lo is None else min(h_lo, h)
        h_hi = h if h_hi is None else max(h_hi, h)
        bins[key][h][idx[it]] += 1
        if e.id in s.harmful:
            harm[key][h] += 1
        m = meta.setdefault(key, {"actor": key, "kind": "runs" if key == RUNS else ak, "total": 0, "first": t, "last": t, "first_record": e.id})
        m["total"] += 1
        if t < m["first"]:
            m["first"], m["first_record"] = t, e.id
        m["last"] = max(m["last"], t)
    if h_lo is None:
        return {"start": None, "hours": 0, "intents": order, "actors": [], "messages": []}
    sent = Counter(d["from"] for d in s.flow["_deliveries"])
    got = Counter(d["to"] for d in s.flow["_deliveries"])
    actors = []
    for key, m in meta.items():
        actors.append({"actor": key, "kind": m["kind"], "total": m["total"], "first": iso(m["first"]), "last": iso(m["last"]),
                       "first_record": m["first_record"], "sent": sent.get(key, 0), "received": got.get(key, 0),
                       "harmful": sum(harm[key].values()),
                       "bins": [[h - h_lo, *v] for h, v in sorted(bins[key].items())],
                       "harm_bins": [[h - h_lo, n] for h, n in sorted(harm[key].items())]})
    actors.sort(key=lambda r: r["first"])
    return {"start": _hour_iso(h_lo), "start_t": h_lo * HOUR, "hours": h_hi - h_lo + 1, "intents": order,
            "intent_names": intent_names(s.pack), "actors": actors}


def message_list(s):
    coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
    rows = []
    for d in s.flow["_deliveries"]:
        rows.append([d["from"], d["to"], d["channel"], d["write_id"], d["read_id"], d["write_time"], d["read_time"],
                     d["latency_h"], d.get("how"), 1 if any(r.search(d["channel"]) for r in coarse) else 0])
    rows.sort(key=lambda r: r[6])
    over = [[d["from"], d["to"], d["channel"], d["write_id"], d["read_id"], d["write_time"], d["read_time"]]
            for d in s.flow.get("_overwrites", [])]
    # merged: the place is one the redaction may have merged with others, so the write and read may differ
    return {"columns": ["from", "to", "channel", "write_id", "read_id", "write_t", "read_t", "latency_h", "how", "merged"],
            "rows": rows, "overwrites": over}


# ------------------------------------------------------------------ program gist

URL_RX = re.compile(r"https?://((?:\[[^\]\n]{1,60}\]|[\w.\-])+)((?:/(?:\[[^\]\n]{1,60}\]|[\w\-.%:])*)*)")


def program_gist(s, rid):
    """A one-line account of what a program does: its intent, its strongest tags, and the hosts it calls."""
    e = s.by_id.get(rid)
    if not e:
        return None
    names_i, names_t = intent_names(s.pack), tag_names(s.pack)
    it = s.rec["_intents"].get(rid)
    tags = [g for g in s.res["_evidence"][rid]][:4]
    hosts = []
    for m in URL_RX.finditer(e.text[:20000]):
        host = m.group(1).strip()
        path = (m.group(2) or "").split("?")[0]
        segs = [p for p in re.findall(r"\[[^\]]+\]|[^/]+", path) if p and p != "/"][:3]
        h = host + ("/" + "/".join(segs) if segs else "")
        if h not in hosts:
            hosts.append(h)
        if len(hosts) >= 4:
            break
    return {"intent": it, "intent_what": names_i.get(it) if it else None,
            "tags": [{"tag": g, "what": names_t.get(g, human(g))} for g in tags], "calls": hosts,
            "length": len(e.text)}


def spread_detail(s):
    """Every program run by several actors, with what it does."""
    out = []
    for x in s.flow.get("_content_spread", []):
        out.append({**x, "what": program_gist(s, x["source_record"])})
    return out


# ------------------------------------------------------------------ simulation

def _rate_alarm(s, harmful_only=False):
    from . import evaluate
    times, intents = s.rec["_times"], s.rec["_intents"]
    harm = s.harm_sorted
    if harmful_only:
        pts = harm
    else:
        pts = [times[e.id] for e in s.events if e.id in times and intents.get(e.id)]
    return evaluate.rate_alarm(pts, harm)


def data_phases(s):
    """Moments in the data: first action, the main surge, the busiest hour, the stop, the last action."""
    times, intents = s.rec["_times"], s.rec["_intents"]
    hourly = Counter(_hour(times[e.id]) for e in s.events if e.id in times and intents.get(e.id))
    if not hourly:
        return []
    hours = sorted(hourly)
    total = sum(hourly.values())
    out = [{"key": "first", "name": "First timed action", "time": iso(hours[0] * HOUR)}]
    for h in hours:
        nxt = sum(hourly.get(h + i, 0) for i in range(6))
        prev = sum(hourly.get(h - i, 0) for i in range(1, 7))
        if nxt >= 3 * max(prev, 1) and nxt >= 0.05 * total:
            out.append({"key": "surge", "name": "Main surge begins", "time": iso(h * HOUR),
                        "why": f"the next 6 hours hold {nxt:,} actions, {nxt / max(prev, 1):.1f}x the 6 before"})
            break
    peak = max(hours, key=lambda h: hourly[h])
    out.append({"key": "peak", "name": "Busiest hour", "time": iso(peak * HOUR), "why": f"{hourly[peak]:,} timed actions"})
    for h in range(peak, hours[-1] + 1):
        if hourly.get(h, 0) < 0.15 * hourly[peak] and h > peak + 6:
            out.append({"key": "stop", "name": "Activity falls below 15% of the peak", "time": iso(h * HOUR)})
            break
    out.append({"key": "last", "name": "Last timed action", "time": iso(hours[-1] * HOUR)})
    return out


PERIODS = [("first", "Build-up", "before the main surge"), ("surge", "Surge", "activity climbing fast"),
           ("peak", "Height", "from the busiest hour until activity falls away"), ("stop", "Wind-down", "after activity fell below 15% of the peak")]


def period_of(phases, t):
    """Which stretch of the incident a time falls in, named from the data's own moments."""
    if t is None or not phases:
        return None
    at = {p["key"]: p["time"] for p in phases}
    out = None
    for key, name, what in PERIODS:
        if key in at and iso(t) >= at[key]:
            out = {"name": name, "what": what, "since": at[key]}
    return out


def simulate(s):
    cached = getattr(s, "_sim", None)
    if cached is not None:
        return cached
    times, intents = s.rec["_times"], s.rec["_intents"]
    acts = sorted((times[e.id], e.id) for e in s.events if e.id in times and intents.get(e.id))
    if not acts:
        s._sim = {"start": None, "hours": [], "signals": [], "phases": []}
        return s._sim
    h0, h1 = _hour(acts[0][0]), _hour(acts[-1][0])
    n = h1 - h0 + 1
    actions, harmful, new_actors, active = [0] * n, [0] * n, [0] * n, [set() for _ in range(n)]
    for t in s.harm_sorted:
        i = _hour(t) - h0
        if 0 <= i < n:
            harmful[i] += 1
    seen = set()
    for t, rid in acts:
        i = _hour(t) - h0
        actions[i] += 1
        a, ak = s.actor[rid]
        if ak != "run":
            active[i].add(a)
            if a not in seen:
                seen.add(a)
                new_actors[i] += 1

    signals = []

    def add(key, name, family, t, ref, actors, why, kind=None):
        if t is None:
            return
        rec = ref if ref in s.by_id else None
        if rec is None and (kind or key) == "token":
            x = next((x for x in s.rec["seen_then_used"] if x["item"] == ref), None)
            rec = x["first_seen_id"] if x else None
        signals.append({"key": key, "name": name, "family": family, "kind": kind or key, "time": iso(t), "t": t,
                        "ref": ref, "record": rec, "actors": [a for a in actors if a], "why": why,
                        "harm_share_after": harm_share_after(s, t)})

    # the tool's replay: first harmful action of each kind, coordination and spread signs
    from .evaluate import _parse
    for r in s.rec["replay"]:
        t = _parse(r["time"])
        name, fam = signal_name(r["signal"], r.get("ref"))
        ref = r.get("ref")
        actors = [s.actor[ref][0]] if ref in s.by_id else ([ref] if isinstance(ref, str) and ref.startswith("[") else [])
        place = None
        m = re.match(r"(.+) carried (.+) in (\S+)$", str(ref or ""))
        if m:                       # "A carried B in R…": both identities, and the record
            actors, ref = [m.group(1), m.group(2)], m.group(3)
        elif r["signal"].startswith("coordination: two identities"):
            sp = next((x for x in s.rec["shared_places"] if x["place"] == ref and not x["same_record"]), None)
            if sp:
                place, actors, ref = ref, sp["identities"][:2], sp["second_id"]
        kind = "harm" if r["signal"].startswith("first:") else ("token" if r["signal"].startswith("spread") else
                                                                  "carried" if "carries" in r["signal"] else "place")
        why = {"harm": "the first harmful action of this kind",
               "token": f"{ref} appeared inside a record as data before any record used it to authenticate",
               "carried": (f"{actors[0]} holds {actors[1]}'s token in {ref}, before that token's own first use"
                           if len(actors) == 2 else f"one record authenticates as one identity and holds another's token: {ref}"),
               "place": f"two identities used the same named place {place or ref} in different records"}[kind]
        add("replay:" + r["signal"], name + (" (at or before)" if "at or before" in r["time"] else ""), fam, t, ref, actors, why, kind)

    named = sorted((d for d in s.flow["_deliveries"] if is_named(d["from"]) and is_named(d["to"])), key=lambda d: d["read_time"])
    coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
    exact = [d for d in named if not any(r.search(d["channel"]) for r in coarse)]
    if exact:
        d = exact[0]
        add("message", "First message between named actors", "joint", d["read_time"], d["read_id"], [d["from"], d["to"]],
            f"{d['from']} wrote {d['channel']} in {d['write_id']}; {d['to']} read it in {d['read_id']}, {d['latency_h']} h later",
            "message")
    # two-way exchange, and groups linked by messages
    seen_pairs, parent = set(), {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    size = Counter()
    two_way = None
    thresholds = [3, 5, 10, 20]
    msgs, pairs_cum, group_max = [0] * n, [0] * n, [0] * n
    biggest = 0
    for d in exact:
        a, b = d["from"], d["to"]
        if two_way is None and (b, a) in seen_pairs:
            two_way = d
        seen_pairs.add((a, b))
        ra, rb = find(a), find(b)
        if not size[ra]:
            size[ra] = 1
        if not size[rb]:
            size[rb] = 1
        if ra != rb:
            parent[ra] = rb
            size[rb] += size[ra]
        if size[find(b)] > biggest:
            biggest = size[find(b)]
            while thresholds and biggest >= thresholds[0]:
                k = thresholds.pop(0)
                members = [x for x in parent if find(x) == find(b)]
                add(f"group{k}", f"A group of {k}+ actors linked by messages", "joint", d["read_time"], d["read_id"], [a, b],
                    f"the message from {a} to {b} joined {biggest} actors into one connected group: "
                    + ", ".join(members[:8]) + ("…" if len(members) > 8 else ""), "group")
        i = _hour(d["read_time"]) - h0
        if 0 <= i < n:
            msgs[i] += 1
            pairs_cum[i] = len(seen_pairs)
            group_max[i] = biggest
    if two_way:
        d = two_way
        add("two_way", "First two-way exchange", "joint", d["read_time"], d["read_id"], [d["from"], d["to"]],
            f"{d['to']} had already sent to {d['from']}; now {d['from']} sends back through {d['channel']}", "two_way")
    # programs reused by other actors
    first_adopt, third = None, None
    for x in s.flow.get("_content_spread", []):
        src_t = _parse(x["source_time"]) if x.get("source_time") else None
        ad = [(_parse(a["time"]), a) for a in x["adopters"] if a.get("time")]
        ad.sort(key=lambda p: p[0])
        if ad and (first_adopt is None or ad[0][0] < first_adopt[0]):
            first_adopt = (ad[0][0], x, ad[0][1])
        if len(ad) >= 2 and (third is None or ad[1][0] < third[0]):
            third = (ad[1][0], x, ad[1][1])
    if first_adopt:
        t, x, a = first_adopt
        add("program2", "First program reused by another actor", "joint", t, a["record"], [x["source"], a["actor"]],
            f"{a['actor']} ran the program {x['source']} first ran in {x['source_record']}, {a['hours_after_source']} h later", "program")
    if third:
        t, x, a = third
        add("program3", "First program run by three actors", "joint", t, a["record"], [x["source"], a["actor"]],
            f"{a['actor']} became the third actor to run the program first run by {x['source']} in {x['source_record']}", "program")
    # ordinary volume monitoring, for comparison
    for key, label, harmful_only in (("rate_all", "Volume alarm on all actions", False), ("rate_harm", "Volume alarm on harmful actions", True)):
        b = _rate_alarm(s, harmful_only)
        if b:
            t = _parse(b["hour"]) + HOUR
            add(key, label, "baseline", t, None, [],
                f"{b['count']:,} actions in the hour from {b['hour']}, above the alarm line of {b['threshold']:,} "
                "(mean + 3 standard deviations of every earlier hour); known at the end of that hour", "baseline")
    signals.sort(key=lambda g: g["t"])

    remaining = []
    for i in range(n):
        remaining.append(harm_share_after(s, (h0 + i + 1) * HOUR))
    # carry cumulative series forward through hours with no messages
    for i in range(1, n):
        pairs_cum[i] = pairs_cum[i] or pairs_cum[i - 1]
        group_max[i] = group_max[i] or group_max[i - 1]
    s._sim = {
        "start": _hour_iso(h0), "start_t": h0 * HOUR, "hours": n,
        "actions": actions, "harmful": harmful, "harm_remaining": remaining,
        "active_actors": [len(x) for x in active], "new_actors": new_actors,
        "messages": msgs, "pairs": pairs_cum, "largest_group": group_max,
        "harm_total": len(s.harm_sorted), "actions_total": len(acts),
        "signals": signals, "phases": data_phases(s),
    }
    return s._sim


# ------------------------------------------------------------------ one record, explained

def explain(s, rid):
    e = s.by_id.get(rid)
    if not e:
        return None
    times, intents = s.rec["_times"], s.rec["_intents"]
    a, ak = s.actor[rid]
    t = times.get(rid)
    names_i, names_t, stage = intent_names(s.pack), tag_names(s.pack), tag_stage(s.pack)
    it = intents.get(rid)
    what = []
    if it and it != "other":
        what.append(names_i.get(it, human(it)) + ".")
    tags = s.res["_evidence"][rid]
    if tags:
        what.append("The code " + "; ".join(names_t.get(g, human(g)).lower() for g in tags[:6]) + ".")
    ops = s.ops_by_id.get(rid, [])
    w = [o["channel"] for o in ops if o["op"] in ("write", "post")]
    r = [o["channel"] for o in ops if o["op"] in ("read", "post")]
    if w:
        what.append(f"It writes to {len(w)} place{'s' if len(w) != 1 else ''} ({', '.join(w[:3])}{'…' if len(w) > 3 else ''}).")
    if r:
        what.append(f"It reads {len(r)} place{'s' if len(r) != 1 else ''} ({', '.join(r[:3])}{'…' if len(r) > 3 else ''}).")
    ids = s.rec["_ids"].get(rid, {})
    shared = set(s.pack.raw.get("shared_identities", []))
    if ids:
        what.append("It authenticates as " + ", ".join(f"{k}{' (shared key)' if k in shared else ''} via {v}" for k, v in list(ids.items())[:4]) + ".")
    if not what:
        what.append(f"A {e.kind or 'record'} with no known pattern." if reconstruct.is_action(e, s.pack)
                    else f"A {e.kind or 'record'}: not an action an agent ran, but text recovered or returned around one. "
                         "Its identities and places are credited to the action, so it is not counted twice.")

    roles = []
    din, dout = s.del_in.get(rid, []), s.del_out.get(rid, [])
    if dout:
        roles.append({"role": "sender", "label": "Sent a message",
                      "detail": f"{len(dout)} later read{'s' if len(dout) != 1 else ''} by {len({d['to'] for d in dout})} other actor(s)"})
    if din:
        roles.append({"role": "receiver", "label": "Received a message",
                      "detail": f"read what {len({d['from'] for d in din})} other actor(s) wrote ({len(din)} message{'s' if len(din) != 1 else ''})"})
    sim = simulate(s)
    for g in sim["signals"]:
        if g.get("ref") == rid:
            roles.append({"role": "signal", "label": "Early-warning sign", "detail": f"{g['name']}: {g['why']}"})
    sr = s.spread_role.get(rid)
    if sr:
        x = s.flow["_content_spread"][sr[1]]
        if sr[0] == "source":
            roles.append({"role": "source", "label": "First run of a shared program",
                          "detail": f"{x['actors'] - 1} other actor(s) ran the same program later ({x['copies']} copies)"})
        else:
            roles.append({"role": "adopter", "label": "Reused another actor's program",
                          "detail": f"first run by {x['source']} in {x['source_record']} at {x['source_time']}"})
    for c in s.rec["carried_edges"]:
        if rid in c["evidence"]:
            roles.append({"role": "carrier", "label": "Carries another identity's token",
                          "detail": f"{c['from']} holds {c['to']} before that token's own first use"})
    for x in s.rec["seen_then_used"]:
        if x["first_seen_id"] == rid:
            roles.append({"role": "seen", "label": "A token first appears here",
                          "detail": f"{x['item']} is seen here as data and first used as an identity at {x['first_used']}"})
    if s.over_in.get(rid) or s.over_out.get(rid):
        roles.append({"role": "overwrite", "label": "Overwrite",
                      "detail": f"replaced {len(s.over_in.get(rid, []))} edit(s); replaced by {len(s.over_out.get(rid, []))}"})
    if rid in s.harmful:
        roles.append({"role": "harm", "label": "Counted as harmful",
                      "detail": "its intent or a tag is in the pack's harm list" + (f" ({names_i.get(it, it)})" if it in s.pack.harm else "")})

    # where it sits: in the actor's history, in the incident, in the program's spread
    mine = [x for x in s.by_actor.get(a, [])]
    mine_t = sorted((times[x], x) for x in mine if x in times)
    pos_actor = next((k for k, (_, x) in enumerate(mine_t) if x == rid), None)
    hourly = Counter(iso(tt)[:13] for tt, _ in mine_t)
    phase = period_of(sim["phases"], t)
    report_phase = None
    ctx = context(s).get("context")
    if ctx and t is not None:
        for p in ctx.get("phases", []):
            st = (p.get("start") or "").replace(" UTC", "")
            if st and iso(t) >= st[:16]:
                report_phase = {"name": p["name"], "source": p.get("source")}
    prog = None
    fam = family_index(s).get(rid)
    is_act = reconstruct.is_action(e, s.pack)
    if fam:
        copies = [x for x in s.by_family[fam] if reconstruct.is_action(s.by_id[x], s.pack)]
        actors_p = Counter(s.actor[x][0] for x in copies)
        ct = sorted((times[x], x) for x in copies if x in times)
        first = ct[0][1] if ct else (copies[0] if copies else None)
        prog = {"rule": "identical code once ids, numbers and hashes are masked", "copies": len(copies),
                "other_copies": len([x for x in copies if x != rid]),
                "actors": len(actors_p), "named_actors": sum(1 for k in actors_p if is_named(k)),
                "first_record": first, "first_actor": s.actor[first][0] if first else None, "is_first": first == rid,
                "first_time": iso(ct[0][0]) if ct else None, "last_time": iso(ct[-1][0]) if ct else None,
                "hourly": sorted(Counter(iso(x)[:13] for x, _ in ct).items()),
                "top_actors": [{"actor": k, "n": v} for k, v in actors_p.most_common(6)]}
    copy_of = None
    if not is_act:
        # a recovered copy or a response: point at the action it repeats or answers
        same = [x for x in (s.by_family.get(fam, []) if fam else []) if reconstruct.is_action(s.by_id[x], s.pack)]
        if same:
            copy_of = {"record": same[0], "why": "the same code (ids masked) as this action"}
        elif e.parent and e.parent in s.by_id:
            copy_of = {"record": e.parent, "why": "its parent record"}
    ctx_tags = s.res["_context"][rid]
    return {
        "is_action": is_act, "copy_of": copy_of,
        "what": what,
        "stages": sorted({stage.get(g, "other") for g in tags}),
        "roles": roles,
        "harm_share_after": harm_share_after(s, t) if is_act else None,
        "phase": phase,
        "report_phase": report_phase,
        "actor": {"actor": a, "kind": ak, "records": len(mine), "timed": len(mine_t),
                  "position": (pos_actor + 1) if pos_actor is not None else None,
                  "first": iso(mine_t[0][0]) if mine_t else None, "last": iso(mine_t[-1][0]) if mine_t else None,
                  "hourly": sorted(hourly.items())},
        "program": prog,
        "components": {"identities": len(ids), "places_written": len(w), "places_read": len(r),
                       "messages_in": len(din), "messages_out": len(dout),
                       "ancestors": 0, "children": len(s.children.get(rid, [])), "tags": len(tags), "context_tags": len(ctx_tags)},
    }


# ------------------------------------------------------------------ incident context

def context(s):
    """The incident context file whose 'match' fits this dataset, with the milestone check."""
    cached = getattr(s, "_context", None)
    if cached is not None:
        return cached
    out = {"context": None, "milestones": None}
    path = os.path.join(CLAIMS_DIR, "incident_context.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            ctx = json.load(f)
        m = ctx.get("match", {})
        ok = (s.pack.name in m.get("packs", []) or any(re.search(p, s.name or "", re.I) for p in m.get("datasets", []))
              or any(tok in s.by_actor for tok in m.get("identities", [])))
        if ok:
            out["context"] = ctx
            from . import evaluate
            try:
                ext = evaluate.external_check(s.events, s.rec)
                out["milestones"] = ext
            except Exception:
                out["milestones"] = None
    s._context = out
    return out


# ------------------------------------------------------------------ one search box for everything

def omni(s, q, limit=8):
    """Records, actors and places that match q, for the search box in the top bar."""
    q = (q or "").strip()
    if not q:
        return {"records": [], "actors": [], "places": []}
    ql = q.lower()
    alt = re.sub(r"\bcred (\d+)", r"[credential \1]", ql)
    recs = []
    if q in s.by_id:
        recs.append(q)
    for rid in s.by_id:
        if len(recs) >= limit:
            break
        if rid != q and rid.lower().startswith(ql):
            recs.append(rid)
    def rank(a):
        al, sh = a.lower(), re.sub(r"\[credential (\d+)\]", r"cred \1", a.lower())
        if ql in (al, sh) or alt == al:
            return 0
        if al.startswith(ql) or sh.startswith(ql) or re.search(r"\b" + re.escape(ql) + r"\b", sh):
            return 1
        return 2 if (ql in al or alt in al or ql in sh) else None
    hits = [(rank(a), -len(ids), a) for a, ids in s.by_actor.items() if not a.startswith("run:")]
    actors = [{"actor": a, "records": -n, "kind": s.actor[s.by_actor[a][0]][1]} for r, n, a in sorted(x for x in hits if x[0] is not None)[:limit]]
    places = []
    for ch, row in s.channel_row.items():
        if ql in ch.lower() or alt in ch.lower():
            places.append({"channel": ch, "messages": row["deliveries"], "ops": row["writes"] + row["reads"]})
    places.sort(key=lambda r: (-r["messages"], -r["ops"]))
    return {"records": [s.event_row(s.by_id[r]) for r in recs[:limit]], "actors": actors, "places": places[:limit]}


# ------------------------------------------------------------------ what an investigator would still miss

def gap_facts(s):
    """Measured blind spots, each with a count and the total it is out of. Shared by the app and the AI."""
    summ = s.summary()
    f = s.flow
    n = summ["records"]
    timed = summ["timed"]
    # actors can only be named on actions (records an agent ran), so measure over those
    acts = [e.id for e in s.events if reconstruct.is_action(e, s.pack)]
    named_records = sum(1 for rid in acts if s.actor[rid][1] != "run")
    dels = f["deliveries"]
    by_how = f.get("deliveries_by_how", {})
    weak = sum(v for k, v in by_how.items() if k in ("named the place", "posted after it"))
    chans = f.get("_channels", f["top_channels"])
    never = sum(1 for c in chans if c["never_read"])
    shared = set(s.pack.raw.get("shared_identities", []))
    shared_recs = sum(1 for ids in s.rec["_ids"].values() if any(t in shared for t in ids)) if shared else 0
    runs = summ.get("actor_kinds", {}).get("run", 0)
    named_actors = sum(v for k, v in summ.get("actor_kinds", {}).items() if k != "run")
    rows = [
        {"key": "time", "gap": "Records with no time", "count": n - timed, "of": n, "unit": "records", "question": "early flag",
         "hides": "anything they did cannot be placed on the timeline or in the early-flag replay",
         "close": "server-side timestamps for each run, or more timestamps written in the records"},
        {"key": "actor", "gap": "Actions with no named actor", "count": len(acts) - named_records, "of": len(acts), "unit": "actions", "question": "who talked to whom",
         "hides": f"messages from or to {runs:,} anonymous runs cannot be tied to an agent",
         "close": "an agent id per run from the operator's logs"},
        {"key": "identity", "gap": "Identities are tokens and names, not agents", "count": named_actors, "of": None, "unit": "named actors", "question": "who talked to whom",
         "hides": "one agent can hold several tokens or names, so a 'message' may be an agent talking to itself",
         "close": "a mapping from tokens and names to agent runs"},
        {"key": "order", "gap": "Reads that cannot be put in order", "count": f["deliveries_order_unknown"], "of": dels + f["deliveries_order_unknown"], "unit": "reads", "question": "who talked to whom",
         "hides": "possible messages where one side has no time", "close": "times for the records on both sides"},
        {"key": "weak", "gap": "Messages resting only on naming the place or posting after it", "count": weak, "of": dels, "unit": "messages", "question": "who talked to whom",
         "hides": "the place was known, but the earlier content may never have been read", "close": "read logs from the platform"},
        {"key": "merged", "gap": "Messages on places the redaction may have merged", "count": f.get("coarse_channel_deliveries", 0), "of": dels, "unit": "messages", "question": "how information spread",
         "hides": "the write and the read may be on two different places that the redaction reduced to one owner",
         "close": "the unredacted place names, held by the data owner"},
        {"key": "never_read", "gap": "Places written but never read by another actor", "count": never, "of": len(chans), "unit": "places", "question": "how information spread",
         "hides": "messages nobody picked up, or reads the patterns cannot see", "close": "platform access logs for these places"},
        {"key": "parent", "gap": "Records with no parent link", "count": summ["gaps"].get("no_parent", 0), "of": n, "unit": "records", "question": "how information spread",
         "hides": "which run a record belongs to, so actions are split across many anonymous runs", "close": "run ids from the operator"},
    ]
    if shared:
        rows.append({"key": "shared", "gap": "Records that use a shared key", "count": shared_recs, "of": n, "unit": "records", "question": "who talked to whom",
                     "hides": "a key every agent used says nothing about which agent acted", "close": "per-agent keys"})
    if f.get("overwrites"):
        rows.append({"key": "overwrites", "gap": "Edits that replaced another actor's edit unseen", "count": f["overwrites"], "of": None, "unit": "edits", "question": "who talked to whom",
                     "hides": "agents unaware of each other look like a conversation if counted naively", "close": "page view logs"})
    rows += [
        {"key": "success", "gap": "Whether an action worked", "count": None, "of": None, "unit": "", "question": "all",
         "hides": "a read or write in the code is an attempt; the data rarely shows the result", "close": "responses or the target's logs"},
        {"key": "patterns", "gap": "Tags and intents are pattern matches", "count": None, "of": None, "unit": "", "question": "all",
         "hides": "code that does harm without matching a pattern, and matches that are harmless", "close": "labelled samples to measure precision and recall"},
        {"key": "unlisted", "gap": "Places the pack does not describe", "count": None, "of": None, "unit": "", "question": "who talked to whom",
         "hides": "messages through any channel the pack has no pattern for are invisible", "close": "add the channel to the pack, or platform logs"},
    ]
    for r in rows:
        r["share"] = round(r["count"] / r["of"], 4) if r.get("count") is not None and r.get("of") else None
    return rows


# ------------------------------------------------------------------ why a record was read the way it was

def why_spans(s, rid, text_limit=20000):
    """Every stretch of a record's text that made the tool read it a certain way: the pattern that set
    its intent, each behavior tag, each identity token, each place it names (with the code that made the
    mention a write), and self-chosen names. Offsets index the first text_limit characters."""
    from . import messages
    e = s.by_id.get(rid)
    if not e:
        return []
    text = e.text[:text_limit]
    names_i = intent_names(s.pack)
    spans = []

    def add(m, typ, key, label, group=0, **extra):
        spans.append({"s": m.start(group), "e": m.end(group), "type": typ, "key": key, "label": label, **extra})

    it = s.rec["_intents"].get(rid)
    if it and it != "other":
        for name, rx in s.pack.intents:
            if name == it:
                m = rx.search(text)
                if m and m.end() > m.start():
                    add(m, "intent", name, f"sets its intent: {names_i.get(name, human(name))} (first intent pattern that matches)")
                break
    tags = set(s.res["_evidence"][rid]) | set(s.res["_context"][rid])
    for b in s.pack.behaviors:
        if b.name not in tags:
            continue
        for k, m in enumerate(b.rx.finditer(text)):
            if k >= 4:
                break
            if m.end() > m.start():
                add(m, "context" if b.context else "tag", b.name,
                    f"tag {human(b.name)}: {b.description or human(b.name)}" + (" (context only, not counted as evidence)" if b.context else ""))
    if reconstruct.is_action(e, s.pack):
        shared = set(s.pack.raw.get("shared_identities", []))
        for role, rx in s.pack.identity_patterns:
            for m in rx.finditer(text):
                tok = m.group(1)
                add(m, "identity", tok, f"identity {tok} used as {role}" + (" (a shared key: not counted as an actor)" if tok in shared else ""), 1)
        for name, rx, wrx in messages.compile_channels(s.pack):
            for m in rx.finditer(text):
                if not m.group(1):
                    continue
                w0 = max(0, m.start() - 160)
                window = text[w0: m.end() + 260]
                wm = wrx.search(window)
                key = f"{name}:{m.group(1)}"
                add(m, "place", key, f"names the place {key}: counted as a {'write' if wm else 'read'}"
                    + (" because of the code marked nearby" if wm else " (no write code within the 160 characters before or 260 after)"),
                    op="write" if wm else "read")
                if wm and wm.end() > wm.start():
                    spans.append({"s": w0 + wm.start(), "e": w0 + wm.end(), "type": "write_cue", "key": key,
                                  "label": f"write code: makes the mention of {key} a write"})
        ids_here = set(s.rec["_ids"].get(rid, {}))
        for fam, rx in s.pack.info_patterns:
            for k, m in enumerate(rx.finditer(text)):
                if k >= 6:
                    break
                if m.group(0) not in ids_here:
                    add(m, "info", m.group(0), f"{m.group(0)} appears here as data ({fam}), not used to authenticate: how a token can pass to another agent")
        if s.pack.handles_rx:
            for m in s.pack.handles_rx.finditer(text):
                add(m, "handle", m.group(1), f"self-chosen name {m.group(1)}", 1)
        for fam, rx in s.pack.shared_names:
            for k, m in enumerate(rx.finditer(text)):
                if k >= 4:
                    break
                add(m, "name", m.group(0), f"a name other runs can reuse ({fam})")
    spans = [x for x in spans if 0 <= x["s"] < x["e"] <= len(text)]
    spans.sort(key=lambda x: (x["s"], -(x["e"] - x["s"])))
    return spans[:400]

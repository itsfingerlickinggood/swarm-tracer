"""Forensics: what-if decisions, reference swarm comparison, chain of custody, SOC exports.

Routes (served at /api/x/<name>, see extensions.py):
    GET  fx_whatif?rule=estimate|accepted   the counts and joint signs "as counted" and "after your decisions"
    GET  fx_whatif_decisions                 the decisions stored for the loaded dataset
    POST fx_whatif_decide                    {kind: "message"|"sign", ids: [...], action: "reject"|"restore", note}
                                             or {clear: true} (messages and signs) or {reset: true} (also identity merges)
    GET  fx_reference                        the reference dataset (status, measures, deviations) and the choices
    POST fx_reference_load                   {library: id} | {path, pack} | {default: true} | {use_compare: true}
    POST fx_reference_clear
    GET  fx_custody                          the chain of custody of the loaded analysis
    GET  fx_export?format=timeline_csv|timesketch_csv|stix|detections   {filename, mime, content}

Decisions (rejected messages and signs) live in ~/.swarm-tracer/whatif-<dataset>.json; identity merges are the
Agents tab's own decisions (agenttrace.identity). Nothing here changes the analysis itself: every "after" number is
recounted from the same records with the decisions applied, by the same code that counts "as counted".
"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
import uuid
from collections import Counter, defaultdict

from . import insight, reconstruct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UTC = dt.timezone.utc
HOUR = 3600.0
iso = reconstruct.iso
GROUP_STEPS = (3, 5, 10, 20)


def home():
    return os.environ.get("SWARM_TRACER_HOME") or os.path.join(os.path.expanduser("~"), ".swarm-tracer")


def _slug(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "dataset")).strip("._")[:120] or "dataset"


def _now_iso():
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("No dataset loaded. Upload a file first.")
    return s


_LOCK = threading.Lock()


def _write_json(path, obj):
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)


# ================================================================== what-if: decisions

def decisions_path(s):
    return os.path.join(home(), "whatif-" + _slug(s.name) + ".json")


def load_decisions(s):
    d = getattr(s, "_fx_dec", None)
    if d is None:
        d = {"messages": {}, "signs": {}}
        try:
            with open(decisions_path(s), encoding="utf-8") as f:
                raw = json.load(f)
            for k in ("messages", "signs"):
                if isinstance(raw.get(k), dict):
                    d[k] = {str(i): v if isinstance(v, dict) else {} for i, v in raw[k].items()}
        except (OSError, ValueError, AttributeError):
            pass
        s._fx_dec = d
    return d


def _save_decisions(s):
    d = load_decisions(s)
    try:
        _write_json(decisions_path(s), {"dataset": s.name, **d})
        return decisions_path(s)
    except OSError:
        return None


def _delivery_index(s):
    """'write_id>read_id' -> the deliveries with that pair of records (usually one)."""
    idx = getattr(s, "_fx_dix", None)
    if idx is None:
        idx = defaultdict(list)
        for d in s.flow["_deliveries"]:
            idx[d["write_id"] + ">" + d["read_id"]].append(d)
        s._fx_dix = idx
    return idx


def decide(s, body):
    if not isinstance(body, dict):
        raise ValueError("send JSON: {kind, ids, action}")
    d = load_decisions(s)
    if body.get("clear") or body.get("reset"):
        d["messages"].clear()
        d["signs"].clear()
        merges = 0
        if body.get("reset"):          # every decision on this server for this dataset, identity merges included
            from . import identity
            dec = identity._decisions(s)
            merges = len(dec)
            dec.clear()
            identity._save(s)
        return {"ok": True, "saved_to": _save_decisions(s), "messages": 0, "signs": 0, "merges_cleared": merges}
    kind, action = body.get("kind"), body.get("action") or "reject"
    ids = body.get("ids")
    if isinstance(ids, str):
        ids = [ids]
    if kind not in ("message", "sign") or action not in ("reject", "restore") or not isinstance(ids, list) or not ids:
        raise ValueError("need kind (message or sign), action (reject or restore) and a list of ids")
    if len(ids) > 5000:
        raise ValueError("at most 5,000 ids at once")
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note) > 5000:
        raise ValueError("a note must be text (at most 5,000 characters)")
    who = str(body.get("by") or "")[:200]
    store = d["messages" if kind == "message" else "signs"]
    if kind == "message":
        idx = _delivery_index(s)
        bad = [i for i in ids if not isinstance(i, str) or i not in idx]
        if bad:
            raise LookupError(f"no message written in one record and read in the other: {bad[0]}")
    else:
        keys = {g["key"] for g in insight.simulate(s)["signals"]}
        bad = [i for i in ids if not isinstance(i, str) or i not in keys]
        if bad:
            raise LookupError(f"no warning sign {bad[0]!r} on this dataset")
    for i in ids:
        if action == "reject":
            store[i] = {"added": _now_iso(), **({"note": note} if note else {}), **({"by": who} if who else {})}
        else:
            store.pop(i, None)
    return {"ok": True, "saved_to": _save_decisions(s), "messages": len(d["messages"]), "signs": len(d["signs"])}


# ================================================================== what-if: recount

def _agent_map(s, rule):
    """actor -> the agent it is counted as (the busiest member of its merge group), and the groups."""
    from . import identity
    base = identity._base(s)
    dec = identity._decisions(s)
    named = base["named"]
    edges = []
    for x in base["scored"]:
        k = (x["a"], x["b"]) if x["a"] < x["b"] else (x["b"], x["a"])
        v = dec.get(k)
        if v == "accept" or (rule == "estimate" and v != "reject" and x["confidence"] == "high"):
            edges.append(k)
    for k, v in dec.items():
        if v == "accept" and k[0] in named and k[1] in named:
            edges.append(k)
    comps = identity._components(named, edges)
    amap, groups = {}, []
    for g in comps:
        g = sorted(g, key=lambda a: (-len(s.by_actor.get(a, [])), a))
        for a in g:
            amap[a] = g[0]
        if len(g) > 1:
            groups.append(g)
    groups.sort(key=lambda g: (-len(g), g[0]))
    merges = {"accepted": sum(1 for v in dec.values() if v == "accept"),
              "rejected": sum(1 for v in dec.values() if v == "reject")}
    return amap, groups, named, merges


class _UF:
    def __init__(self):
        self.p, self.n = {}, {}

    def find(self, x):
        p = self.p
        p.setdefault(x, x)
        self.n.setdefault(x, 1)
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb
            self.n[rb] += self.n[ra]
        return self.n[rb]


def recount(s, amap, rejected_msgs):
    """Messages between different agents (amap: actor -> agent; identity for 'as counted')."""
    coarse = [re.compile(p) for p in s.pack.raw.get("coarse_channels", [])]
    ag = lambda a: amap.get(a, a)
    msgs, self_talk, rejected = 0, 0, 0
    pairs, uf = set(), _UF()
    exact = []
    for d in s.flow["_deliveries"]:
        if not (insight.is_named(d["from"]) and insight.is_named(d["to"])):
            continue
        if rejected_msgs and (d["write_id"] + ">" + d["read_id"]) in rejected_msgs:
            rejected += 1
            continue
        a, b = ag(d["from"]), ag(d["to"])
        if a == b:
            self_talk += 1
            continue
        msgs += 1
        pairs.add((a, b))
        uf.union(a, b)
        if not any(r.search(d["channel"]) for r in coarse):
            exact.append((d["read_time"], d, a, b))
    exact.sort(key=lambda x: x[0])
    biggest = max(uf.n[uf.find(x)] for x in uf.p) if uf.p else 0
    first = None
    if exact:
        t, d, a, b = exact[0]
        first = {"t": t, "time": iso(t), "from": d["from"], "to": d["to"], "agent_from": a, "agent_to": b,
                 "write_id": d["write_id"], "read_id": d["read_id"], "channel": d["channel"],
                 "harm_share_after": insight.harm_share_after(s, t)}
    return {"messages": msgs, "pairs": len(pairs), "largest_group": biggest, "inside_one_agent": self_talk,
            "rejected": rejected, "first_message": first, "_exact": exact}


def _group_and_two_way(exact):
    """When groups of 3/5/10/20+ agents first form, and the first two-way exchange, from time-sorted messages."""
    uf, seen, biggest, out, two_way = _UF(), set(), 0, {}, None
    steps = list(GROUP_STEPS)
    for t, d, a, b in exact:
        if two_way is None and (b, a) in seen:
            two_way = (t, d, a, b)
        seen.add((a, b))
        n = uf.union(a, b)
        if n > biggest:
            biggest = n
            while steps and biggest >= steps[0]:
                out[steps.pop(0)] = (t, d, a, b, biggest)
    return out, two_way


def _first_time_in_text(s, actor, place):
    best = None
    for rid in s.by_actor.get(actor, []):
        t = s.rec["_times"].get(rid)
        if t is not None and (best is None or t < best) and place in s.by_id[rid].text:
            best = t
    return best


def _place_sign(s, ag):
    """The first time two different agents used one named place (identity-level, as the replay counts it)."""
    best = None
    for sp in s.rec.get("shared_places", []):
        if sp.get("same_record"):
            continue
        ids = sp["identities"]
        if len(ids) < 2:
            continue
        a0 = ag(ids[0])
        if ag(ids[1]) != a0:
            t = reconstruct_time(sp["second"])
            cand = (t, sp["place"], ids[0], ids[1], sp["second_id"], False)
        else:
            other = next((x for x in ids[2:] if ag(x) != a0), None)
            if other is None:
                continue
            t = _first_time_in_text(s, other, sp["place"])
            if t is None:
                continue
            cand = (t, sp["place"], ids[0], other, None, True)
        if t is not None and (best is None or t < best[0]):
            best = cand
    return best


def reconstruct_time(text):
    try:
        return dt.datetime.strptime(str(text).replace("at or before ", "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _carry_sign(s, ag):
    best = None
    for c in s.rec.get("carried_edges", []):
        if ag(c["from"]) == ag(c["to"]):
            continue
        ts = [(s.rec["_times"][r], r) for r in c.get("evidence", []) if r in s.rec["_times"]]
        if ts:
            t, r = min(ts)
            if best is None or t < best[0]:
                best = (t, c["from"], c["to"], r)
    return best


def _program_signs(s, ag):
    first, third = None, None
    for x in s.flow.get("_content_spread", []):
        if x.get("routine"):
            continue
        src = ag(x["source"])
        ad = sorted(((reconstruct_time(a["time"]), a) for a in x["adopters"] if a.get("time")), key=lambda p: p[0] or 0)
        seen = [src]
        for t, a in ad:
            if t is None:
                continue
            g = ag(a["actor"])
            if g in seen:
                continue
            seen.append(g)
            if len(seen) == 2 and (first is None or t < first[0]):
                first = (t, x, a)
            if len(seen) == 3:
                if third is None or t < third[0]:
                    third = (t, x, a)
                break
    return first, third


def joint_after(s, ag, exact):
    """The joint warning signs recounted with actors merged into agents. key -> (t, record, actors, why) or None."""
    out = {}
    if exact:
        t, d, a, b = exact[0]
        out["message"] = (t, d["read_id"], [d["from"], d["to"]],
                          f"{d['from']} wrote {d['channel']} in {d['write_id']}; {d['to']} read it in {d['read_id']}")
    else:
        out["message"] = None
    groups, two_way = _group_and_two_way(exact)
    for k in GROUP_STEPS:
        g = groups.get(k)
        out[f"group{k}"] = (g[0], g[1]["read_id"], [g[1]["from"], g[1]["to"]],
                            f"the message from {g[1]['from']} to {g[1]['to']} joined {g[4]} agents into one group") if g else None
    out["two_way"] = (two_way[0], two_way[1]["read_id"], [two_way[1]["from"], two_way[1]["to"]],
                      f"{two_way[1]['to']}'s agent had already sent to {two_way[1]['from']}'s agent") if two_way else None
    p = _place_sign(s, ag)
    out["place"] = (p[0], p[4], [p[2], p[3]], f"two agents used the named place {p[1]}" +
                    (" (time read from the second agent's own records that name the place)" if p[5] else "")) if p else None
    c = _carry_sign(s, ag)
    out["carried"] = (c[0], c[3], [c[1], c[2]], f"{c[1]} holds {c[2]}'s token in {c[3]}, and they are different agents") if c else None
    f, th = _program_signs(s, ag)
    out["program2"] = (f[0], f[2]["record"], [f[1]["source"], f[2]["actor"]],
                       f"{f[2]['actor']} ran the program {f[1]['source']} first ran, as a different agent") if f else None
    out["program3"] = (th[0], th[2]["record"], [th[1]["source"], th[2]["actor"]],
                       f"{th[2]['actor']} was the third agent to run the program first run by {th[1]['source']}") if th else None
    return out


def _sign_slot(g):
    """Which recounted joint sign stands in for this sign, or None when merges cannot change it."""
    if g["family"] != "joint":
        return None
    k = g["key"]
    if k in ("message", "two_way", "program2", "program3") or k.startswith("group"):
        return k
    if g["kind"] == "place":
        return "place"
    if g["kind"] == "carried":
        return "carried"
    return None


def whatif(s, rule="estimate"):
    if rule not in ("estimate", "accepted"):
        raise ValueError("rule must be estimate or accepted")
    dec = load_decisions(s)
    from . import identity
    key = (rule, json.dumps(sorted(identity._decisions(s).items())), json.dumps(dec, sort_keys=True))
    cached = getattr(s, "_fx_wi", None)
    if cached and cached[0] == key:
        return cached[1]
    amap, groups, named, merges = _agent_map(s, rule)
    rej_m = set(dec["messages"])
    rej_s = set(dec["signs"])
    before = recount(s, {}, set())
    after = recount(s, amap, rej_m)
    ag = lambda a: amap.get(a, a)
    joint = joint_after(s, ag, after["_exact"])
    sim = insight.simulate(s)
    signs = []
    for g in sim["signals"]:
        row = {"key": g["key"], "name": g["name"], "family": g["family"], "kind": g["kind"], "time": g["time"],
               "record": g.get("record"), "actors": g.get("actors", []), "why": g["why"],
               "harm_share_after": g["harm_share_after"]}
        slot = _sign_slot(g)
        if g["key"] in rej_s:
            row.update(status="rejected", after=None, note=dec["signs"][g["key"]].get("note"))
        elif slot is None:
            row.update(status="unchanged", after={"time": g["time"], "record": g.get("record"), "harm_share_after": g["harm_share_after"]})
        else:
            x = joint.get(slot)
            if x is None:
                row.update(status="gone", after=None)
            else:
                t, rid, actors, why = x
                hs = insight.harm_share_after(s, t)
                st = "unchanged" if abs(t - g["t"]) < 60 else ("later" if t > g["t"] else "earlier")
                row.update(status=st, after={"time": iso(t), "record": rid, "actors": actors, "why": why, "harm_share_after": hs})
        signs.append(row)
    jb = [x for x in signs if x["family"] == "joint"]
    first_before = jb[0] if jb else None
    ja = sorted((x for x in jb if x["after"]), key=lambda x: x["after"]["time"])
    first_after = ja[0] if ja else None

    def nums(r, agents):
        return {"named_actors": len(named), "agents": agents, "messages": r["messages"], "pairs": r["pairs"],
                "largest_group": r["largest_group"], "inside_one_agent": r["inside_one_agent"], "rejected_messages": r["rejected"],
                "first_message": r["first_message"]}
    out = {
        "dataset": s.name, "rule": rule,
        "as_counted": nums(before, len(named)),
        "after": nums(after, len(set(amap.values())) if amap else len(named)),
        "groups": [{"agent": g[0], "actors": g, "records": sum(len(s.by_actor.get(a, [])) for a in g)} for g in groups[:60]],
        "groups_total": len(groups),
        "decisions": {"merges_accepted": merges["accepted"], "merges_rejected": merges["rejected"],
                      "messages_rejected": len(rej_m), "signs_rejected": len(rej_s),
                      "file": decisions_path(s)},
        "signs": signs,
        "first_joint": {"as_counted": ({k: first_before[k] for k in ("key", "name", "time", "harm_share_after", "record")}
                                       if first_before else None),
                        "after": ({"key": first_after["key"], "name": first_after["name"], **first_after["after"]}
                                  if first_after else None)},
        "harm_total": sim["harm_total"],
    }
    for k in ("as_counted", "after"):
        fm = out[k]["first_message"]
        if fm:
            fm.pop("t", None)
    s._fx_wi = (key, out)
    return out


def decisions_listing(s):
    dec = load_decisions(s)
    idx = _delivery_index(s)
    msgs = []
    for k, v in sorted(dec["messages"].items(), key=lambda kv: kv[1].get("added", "")):
        d = (idx.get(k) or [None])[0]
        msgs.append({"id": k, **v, **({"from": d["from"], "to": d["to"], "channel": d["channel"], "write_id": d["write_id"],
                                       "read_id": d["read_id"], "read_time": iso(d["read_time"])} if d else {"missing": True})})
    names = {g["key"]: g for g in insight.simulate(s)["signals"]}
    signs = [{"key": k, **v, "name": names[k]["name"] if k in names else k, "time": names[k]["time"] if k in names else None}
             for k, v in dec["signs"].items()]
    from . import identity
    merges = [{"a": a, "b": b, "decision": v} for (a, b), v in sorted(identity._decisions(s).items())]
    return {"messages": msgs, "signs": signs, "merges": merges, "file": decisions_path(s)}


def record_messages(s, rid):
    """The named-actor messages a record writes or reads, as 'write>read' ids, with whether each is rejected."""
    dec = load_decisions(s)["messages"]
    out = []
    for d in s.del_in.get(rid, []) + s.del_out.get(rid, []):
        k = d["write_id"] + ">" + d["read_id"]
        out.append({"id": k, "from": d["from"], "to": d["to"], "channel": d["channel"], "rejected": k in dec})
    return out


# ================================================================== reference swarm comparison

REF = {"session": None, "source": None, "busy": False, "error": None, "lock": threading.Lock()}
BENIGN = os.path.join(HERE, "samples", "benign_swarm")


def default_reference():
    """The benign swarm sample when present (a folder with files, or a file)."""
    if os.path.isdir(BENIGN) and any(not f.startswith(".") for f in os.listdir(BENIGN)):
        return BENIGN
    for ext in (".jsonl", ".json", ".csv"):
        if os.path.isfile(BENIGN + ext):
            return BENIGN + ext
    return None


def _load_reference(path, pack, name, source):
    from .session import Session
    try:
        sess = Session()
        try:
            sess.load(path, pack or "auto", {}, name)
        except SystemExit as e:
            raise ValueError(str(e))
        REF.update(session=sess, source={**source, "loaded": _now_iso()}, error=None)
    except Exception as e:   # shown to the user; the previous reference stays
        REF["error"] = f"Could not load {name}: {e}"
    finally:
        REF["busy"] = False
        REF["lock"].release()


def load_reference(state, body):
    from . import compare
    if not isinstance(body, dict):
        raise ValueError("send JSON")
    if body.get("use_compare"):
        b = state.get("compare")
        if not b or not getattr(b, "loaded", False):
            raise LookupError("No second dataset is loaded in the Compare tab.")
        REF.update(session=b, source={"kind": "compare", "name": b.name, "path": (state.get("compare_source") or {}).get("path"),
                                      "loaded": _now_iso()}, error=None)
        return reference_state(state)
    if body.get("library"):
        e = compare.library_entry(str(body["library"]))
        if not e["available"]:
            raise ValueError(f"{e['title']} is not on this machine. Put it at one of: {', '.join(e['paths'])}.")
        path, pack, name, src = e["available"], body.get("pack") or e.get("pack") or "auto", e["title"], {"kind": "library", "id": e["id"]}
    elif body.get("default"):
        path = default_reference()
        if not path:
            raise LookupError("The benign swarm sample (agenttrace/samples/benign_swarm) is not installed.")
        path, pack, name, src = path, "auto", "benign swarm sample", {"kind": "default"}
    else:
        raw = str(body.get("path") or "").strip()
        path = os.path.abspath(os.path.expanduser(raw))
        if not raw or not os.path.exists(path):
            raise ValueError(f"No file or folder at {raw!r} on this machine.")
        pack, name, src = body.get("pack") or "auto", os.path.basename(path.rstrip(os.sep)), {"kind": "path"}
    if not REF["lock"].acquire(blocking=False):
        raise LookupError("A reference dataset is already loading.")
    REF.update(busy=True, error=None)
    src = {**src, "name": name, "path": path, "pack": pack}
    threading.Thread(target=_load_reference, args=(path, pack, name, src), daemon=True).start()
    return reference_state(state)


def _per(x, y):
    return x / y if x is not None and y else None


def ref_measures(s):
    """compare.measures, plus the rates that make two swarms of different size comparable."""
    from . import compare
    m = dict(compare.measures(s))
    na = m.get("named_actors") or 0
    hours = m.get("hours") or 0
    sigs = insight.simulate(s)["signals"]
    first_harm = next((g for g in sigs if g["family"] == "single" and g["kind"] == "harm"), None)
    first_joint = next((g for g in sigs if g["family"] == "joint"), None)
    start = insight.simulate(s).get("start_t")
    m.update({
        "messages_per_actor": _per(m.get("messages_named"), na),
        "messages_per_hour": _per(m.get("messages_named"), hours),
        "pairs_per_actor": _per(m.get("pairs"), na),
        "group_share": _per(m.get("largest_group"), na),
        "programs_per_actor": _per(m.get("programs_shared"), na),
        "harm_per_actor": _per(m.get("harm_total"), na),
        "hours_to_first_harm": round((first_harm["t"] - start) / HOUR, 2) if first_harm and start is not None else None,
        "hours_to_first_joint": round((first_joint["t"] - start) / HOUR, 2) if first_joint and start is not None else None,
        "joint_signs": sum(1 for g in sigs if g["family"] == "joint"),
    })
    return m


# key, label, how (ratio | share | hours | count), unit word
REF_MEASURES = [
    ("messages_per_actor", "messages between named actors per named actor", "ratio", ""),
    ("messages_per_hour", "messages between named actors per hour of activity", "ratio", ""),
    ("pairs_per_actor", "sender-receiver pairs per named actor", "ratio", ""),
    ("largest_group", "actors in the largest group linked by messages", "ratio", ""),
    ("group_share", "share of named actors inside the largest message-linked group", "share", ""),
    ("two_way_share", "share of named pairs that wrote both ways", "share", ""),
    ("wait_median_h", "median wait between a message being written and read", "hours", ""),
    ("programs_per_actor", "programs reused by another actor, per named actor", "ratio", ""),
    ("adoption_median_h", "median time until another actor reused a program (reuse speed)", "hours", ""),
    ("harm_per_actor", "dated harmful actions per named actor", "ratio", ""),
    ("hours_to_first_harm", "hours from the first dated action to the first harmful sign (stage climb speed)", "hours", ""),
    ("hours_to_first_joint", "hours from the first dated action to the first sign of actors working together", "hours", ""),
    ("joint_signs", "signs of actors working together", "count", ""),
    ("dated_share", "share of records with a time", "share", ""),
    ("unattributed_share", "share of actions with no named actor", "share", ""),
]


def _fmtv(v, how):
    if v is None:
        return "–"
    if how == "share":
        return f"{round(100 * v)}%"
    if how == "hours":
        return f"{round(v * 60)} min" if v < 1 else (f"{v:.1f} h" if v < 48 else f"{v / 24:.1f} days")
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:,.2f}" if v < 10 else f"{v:,.1f}"


def deviations(here, ref):
    rows = []
    for key, label, how, _ in REF_MEASURES:
        a, b = here.get(key), ref.get(key)
        row = {"key": key, "label": label, "how": how, "here": a, "reference": b, "here_text": _fmtv(a, how),
               "reference_text": _fmtv(b, how), "ratio": None, "difference": None, "flag": False}
        if a is None or b is None:
            row["text"] = (f"Cannot compare the {label}: " +
                           ("neither swarm has it." if a is None and b is None else
                            f"{'this swarm' if a is None else 'the reference'} has no value (no dated or named data for it)."))
            rows.append(row)
            continue
        if how == "share":
            d = a - b
            row["difference"] = round(d, 4)
            row["flag"] = abs(d) >= 0.15
            row["text"] = (f"The {label} is {_fmtv(a, how)} here against {_fmtv(b, how)} in the reference "
                           f"({'+' if d >= 0 else '−'}{abs(round(100 * d))} points).")
        else:
            if b == 0 and a == 0:
                row["text"] = f"Neither swarm has any {label}."
            elif b == 0:
                row["flag"] = True
                row["text"] = f"This swarm has {_fmtv(a, how)} {label}; the reference has none."
            elif a == 0:
                row["flag"] = how != "hours"
                row["text"] = f"This swarm has no {label}; the reference has {_fmtv(b, how)}."
            else:
                r = a / b
                row["ratio"] = round(r, 3)
                row["flag"] = r >= 2 or r <= 0.5
                if how == "hours":
                    word = "longer" if r >= 1 else "shorter"
                    row["text"] = (f"The {label} is {_fmtv(a, how)} here against {_fmtv(b, how)} in the reference: "
                                   f"{max(r, 1 / r):.1f}x {word}.")
                else:
                    rel = f"{r:.1f}x the reference" if r >= 1 else f"{1 / r:.1f}x {'fewer' if how == 'count' else 'lower'}"
                    row["text"] = f"The {label}: {_fmtv(a, how)} here against {_fmtv(b, how)} in the reference, {rel}."
        rows.append(row)
    return rows


def reference_state(state):
    from . import compare
    s = state.get("session")
    ref = REF["session"]
    out = {"busy": REF["busy"], "error": REF["error"], "source": REF["source"],
           "default_available": bool(default_reference()), "default_path": default_reference(),
           "compare_loaded": bool(state.get("compare") and getattr(state["compare"], "loaded", False)),
           "compare_name": getattr(state.get("compare"), "name", None) if state.get("compare") else None}
    try:
        out["library"] = [{"id": e["id"], "title": e["title"], "available": bool(e["available"]), "kind": e.get("kind")}
                          for e in compare.library()["entries"]]
    except (OSError, ValueError):
        out["library"] = []
    if ref is not None and s is not None and getattr(s, "loaded", False):
        a, b = ref_measures(s), ref_measures(ref)
        rows = deviations(a, b)
        keep = ("name", "pack", "records", "named_actors", "messages_named", "hours", "harm_total", "span")
        out.update({"here": {k: a.get(k) for k in keep}, "reference": {k: b.get(k) for k in keep}, "rows": rows,
                    "flagged": sum(1 for r in rows if r["flag"]),
                    "same_dataset": s is ref or (s.name == ref.name and a.get("records") == b.get("records"))})
    return out


# ================================================================== chain of custody

_HASHES = {}
_HASH_FILE = None


def _hash_cache():
    global _HASH_FILE
    p = os.path.join(home(), "hashes.json")
    if _HASH_FILE != p:
        _HASH_FILE = p
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            _HASHES.update({k: v for k, v in data.items() if isinstance(v, str)})
        except (OSError, ValueError, AttributeError):
            pass
    return p


def sha256_file(path):
    """SHA-256 of a file, streamed; cached by real path, size and modification time."""
    st = os.stat(path)
    key = f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}"
    store = _hash_cache()
    if key in _HASHES:
        return _HASHES[key]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _HASHES[key] = h.hexdigest()
    try:
        _write_json(store, dict(list(_HASHES.items())[-500:]))
    except OSError:
        pass
    return _HASHES[key]


def _input_files(path):
    if not path:
        return []
    if os.path.isfile(path):
        return [path]
    out = []
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            out.extend(os.path.join(root, f) for f in sorted(files) if not f.startswith("."))
    return out[:500]


_TOOL = None


def tool_version():
    global _TOOL
    if _TOOL is None:
        ver = None
        try:
            with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
                m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
                ver = m.group(1) if m else None
        except OSError:
            pass
        if ver is None:
            try:
                from importlib import metadata
                ver = metadata.version("swarm-tracer")
            except Exception:
                ver = None
        git = None
        if os.path.isdir(os.path.join(ROOT, ".git")):
            try:
                r = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=ROOT, capture_output=True,
                                   text=True, timeout=3)
                git = r.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                git = None
        try:
            from . import cache
            code = cache.code_fingerprint()[:16]
        except Exception:
            code = None
        _TOOL = {"name": "Swarm Tracer", "version": ver, "git": git, "code_fingerprint": code}
    return _TOOL


def _pack_file(s):
    from .session import PACK_DIR
    f = getattr(s, "_fx_pack_file", None)
    if not f or f in ("auto", "auto.json"):
        f = (getattr(s, "pack_choice", None) or {}).get("pack") or f
    if f and f not in ("auto", "auto.json"):
        p = f if os.path.isabs(f) else os.path.join(PACK_DIR, f)
        if os.path.isfile(p):
            return p
    for x in sorted(os.listdir(PACK_DIR)):
        if x.endswith(".json"):
            try:
                with open(os.path.join(PACK_DIR, x), encoding="utf-8") as fh:
                    if json.load(fh).get("name") == s.pack.name:
                        return os.path.join(PACK_DIR, x)
            except (OSError, ValueError):
                continue
    return None


def record_ids_hash(s):
    h = getattr(s, "_fx_idhash", None)
    if h is None:
        d = hashlib.sha256()
        for rid in sorted(e.id for e in s.events):
            d.update(rid.encode("utf-8", "surrogatepass"))
            d.update(b"\n")
        h = s._fx_idhash = d.hexdigest()
    return h


def _listed_sums(src):
    """Checksums shipped with the data (SHA256SUMS or *.sha256 files in the input folder): file name -> hash."""
    out = {}
    d = src if src and os.path.isdir(src) else (os.path.dirname(src) if src else None)
    if not d or not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if f.upper().startswith("SHA256SUMS") or f.lower().endswith(".sha256"):
            try:
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    for line in fh.read(1 << 20).splitlines():
                        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
                        if m:
                            out[m.group(2)] = m.group(1)
            except OSError:
                continue
    return out


def custody(s):
    """Everything needed to show which inputs, build and pack produced an analysis. Cached per session
    (file hashes are re-checked against size and modification time, so a changed file is noticed)."""
    src = getattr(s, "path", None) or getattr(s, "_cw_source", None)
    report = getattr(s, "read_report", None) or {}
    read = {f.get("file") for f in report.get("files", [])}
    skipped = {f.get("file") for f in report.get("skipped_files", [])}
    files = []
    for p in _input_files(src):
        base = os.path.basename(p)
        row = {"file": os.path.relpath(p, src) if src and os.path.isdir(src) else base,
               "role": "read" if base in read else ("set aside" if base in skipped else "not a trace file")}
        try:
            st = os.stat(p)
            row.update(bytes=st.st_size, modified=dt.datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       sha256=sha256_file(p))
        except OSError as e:
            row.update(sha256=None, error=f"not readable now: {e.strerror or e}")
        files.append(row)
    if src and not files:
        files.append({"file": os.path.basename(str(src)), "sha256": None, "error": "no longer on disk (an upload's temporary copy may have been removed)"})
    sums = _listed_sums(src)
    for f in files:
        want = sums.get(f["file"]) or sums.get(os.path.basename(f["file"]))
        if want and f.get("sha256"):
            f["matches_listed"] = want.lower() == f["sha256"]
    pf = _pack_file(s)
    pack = {"name": s.pack.name, "file": os.path.basename(pf) if pf else None, "sha256": sha256_file(pf) if pf else None,
            "chosen_automatically": bool(getattr(s, "pack_choice", None))}
    out = {"dataset": s.name, "source": os.path.abspath(str(src)) if src else None, "records": len(s.events),
           "record_ids_sha256": record_ids_hash(s), "files": files, "pack": pack, "tool": tool_version(),
           "loaded_at": getattr(s, "_fx_loaded_at", None), "load_seconds": getattr(s, "_fx_load_seconds", None),
           "from_cache": getattr(s, "_fx_from_cache", None)}
    fp = hashlib.sha256(json.dumps({"records": out["records"], "ids": out["record_ids_sha256"], "pack": pack["sha256"],
                                    "files": [f.get("sha256") for f in files], "tool": out["tool"]}, sort_keys=True).encode()).hexdigest()
    out["fingerprint"] = fp
    out["generated_at"] = _now_iso()
    return out


def custody_lines(c):
    """The custody block as plain lines, for CSV headers and printable pages."""
    t = c.get("tool") or {}
    lines = [f"Dataset: {c['dataset']} ({c['records']:,} records)",
             f"Record ids SHA-256 (sorted ids, one per line): {c['record_ids_sha256']}"]
    for f in c["files"]:
        lines.append(f"Input file {f['file']}: " + (f"SHA-256 {f['sha256']}, {f.get('bytes', 0):,} bytes, modified {f.get('modified')}, {f.get('role')}"
                                                     + ({True: ", matches the checksum shipped with the data", False: ", DOES NOT match the checksum shipped with the data"}[f["matches_listed"]] if "matches_listed" in f else "")
                                                     if f.get("sha256") else (f.get("error") or "not hashed")))
    p = c["pack"]
    lines.append(f"Pack: {p['name']}" + (f" ({p['file']}, SHA-256 {p['sha256']})" if p.get("sha256") else ""))
    lines.append(f"Tool: {t.get('name')} {t.get('version') or ''}" + (f", build {t['git']}" if t.get("git") else "") +
                 (f", code {t['code_fingerprint']}" if t.get("code_fingerprint") else ""))
    lines.append(f"Loaded: {c.get('loaded_at') or 'not recorded'}; exported: {c['generated_at']}")
    lines.append(f"Analysis fingerprint: {c['fingerprint']}")
    return lines


def _remember_load():
    """Record when and with which pack each dataset was loaded (Session.load does not keep it)."""
    try:
        from .session import Session
    except Exception:
        return
    if getattr(Session.load, "_fx_wrapped", False):
        return
    orig = Session.load

    def load(self, path, pack_file=None, *a, **k):
        t0 = time.time()
        r = orig(self, path, pack_file, *a, **k)
        self._fx_loaded_at = _now_iso()
        self._fx_load_seconds = round(time.time() - t0, 2)
        self._fx_pack_file = pack_file
        try:
            from . import cache
            self._fx_from_cache = bool(cache.LAST.get("hit"))
        except Exception:
            self._fx_from_cache = None
        return r
    load._fx_wrapped = True
    for attr in ("_cw_wrapped",):
        if getattr(orig, attr, False):
            setattr(load, attr, True)
    Session.load = load


_remember_load()


# ================================================================== SOC exports

_FORMULA = re.compile(r"^[=+\-@\t\r]")


def _cell(x):
    """CSV cell text; a cell a spreadsheet would run as a formula gets a leading quote."""
    t = "" if x is None else str(x)
    return "'" + t if _FORMULA.match(t) else t


def _dated_rows(s):
    times = s.rec["_times"]
    rows = sorted((t, s.order[rid], rid) for rid, t in times.items() if rid in s.by_id)
    harm = getattr(s, "harmful", set())
    for t, _, rid in rows:
        e = s.by_id[rid]
        a, ak = s.actor[rid]
        places = sorted({o["channel"] for o in s.ops_by_id.get(rid, [])})
        yield {"t": t, "e": e, "actor": a, "actor_kind": ak, "intent": s.rec["_intents"].get(rid) or "",
               "tags": s.res["_evidence"][rid],
               "places": places, "harmful": rid in harm, "time_source": "time field" if e.time else "estimated"}


def timeline_csv(s, c):
    buf = io.StringIO()
    for line in custody_lines(c):
        buf.write("# " + line.replace("\n", " ") + "\n")
    w = csv.writer(buf)
    w.writerow(["time", "time_source", "id", "actor", "actor_kind", "kind", "intent", "tags", "places", "harmful"])
    n = 0
    for r in _dated_rows(s):
        w.writerow([dt.datetime.fromtimestamp(r["t"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), r["time_source"],
                    _cell(r["e"].id), _cell(r["actor"]), r["actor_kind"], _cell(r["e"].kind), _cell(r["intent"]),
                    _cell(";".join(r["tags"])), _cell(";".join(r["places"])), "yes" if r["harmful"] else "no"])
        n += 1
    return buf.getvalue(), n


def timesketch_csv(s, c):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["message", "datetime", "timestamp_desc", "record_id", "actor", "actor_kind", "kind", "intent", "tags",
                "places", "harmful", "data_type", "custody"])
    w.writerow([_cell("Swarm Tracer export: chain of custody. " + " | ".join(custody_lines(c))), c["generated_at"].replace("Z", "+00:00"),
                "Export time", "", "", "", "custody", "", "", "", "", "swarmtracer:custody", c["fingerprint"]])
    n = 0
    for r in _dated_rows(s):
        e = r["e"]
        preview = " ".join(e.text.split())[:200]
        msg = f"{insight_short(r['actor'])} {e.kind or 'record'}" + (f" ({r['intent']})" if r["intent"] and r["intent"] != "other" else "") + \
              (f" [harmful]" if r["harmful"] else "") + f": {preview}"
        w.writerow([_cell(msg), dt.datetime.fromtimestamp(r["t"], UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "Record time" if r["time_source"] == "time field" else "Estimated record time",
                    _cell(e.id), _cell(r["actor"]), r["actor_kind"], _cell(e.kind), _cell(r["intent"]), _cell(";".join(r["tags"])),
                    _cell(";".join(r["places"])), "yes" if r["harmful"] else "no", "swarmtracer:record", ""])
        n += 1
    return buf.getvalue(), n


def insight_short(a):
    return re.sub(r"\[CREDENTIAL (\d+)\]", r"cred \1", str(a or ""))


# ---- STIX 2.1

STIX_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/itsfingerlickinggood/swarm-tracer/stix")
SCO_NS = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")   # the STIX 2.1 namespace for SCO ids


def _sid(kind, *parts):
    return f"{kind}--{uuid.uuid5(STIX_NS, '|'.join(str(p) for p in parts))}"


def _sco_id(kind, value):
    return f"{kind}--{uuid.uuid5(SCO_NS, json.dumps({'value': value}, separators=(',', ':'), ensure_ascii=False))}"


def _stix_ts(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _pat_str(v):
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


URL_RX = re.compile(r"https?://[^\s'\"<>]+", re.I)
HOST_RX = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", re.I)


def _place_value(ch):
    """(stix type, value) for a place: a URL, a host, or a named place (custom object)."""
    kind, _, v = ch.partition(":")
    v = v or ch
    m = URL_RX.search(v) or URL_RX.search(ch)
    if m:
        return "url", m.group(0)
    if HOST_RX.match(v):
        return "domain-name", v.lower()
    return "x-swarm-place", ch


def _stage(s, g):
    if g["family"] == "joint":
        return "coordination"
    if g["family"] == "baseline":
        return "volume"
    if g["kind"] == "token":
        return "credential_access"
    if g["key"].startswith("replay:first:"):
        name = g["key"].split("first:", 1)[1].strip()
        st = insight.tag_stage(s.pack).get(name)
        if st:
            return st
        return "harmful_action"
    return g["kind"] or "other"


def stix_bundle(s, c, max_places=2000):
    created = c["generated_at"].replace("Z", ".000Z")
    tool_id = _sid("identity", "tool", "swarm-tracer")
    objs = [{"type": "identity", "spec_version": "2.1", "id": tool_id, "created": created, "modified": created,
             "name": "Swarm Tracer", "identity_class": "system",
             "description": f"Analysis tool {c['tool'].get('version') or ''} {c['tool'].get('git') or ''}".strip()}]
    ds = s.name
    # identities: every named actor, as the pseudonym the trace gives it (a token or self-chosen name, not a person)
    actors = {}
    for a, rids in s.by_actor.items():
        if not insight.is_named(a) or a == insight.RUNS:
            continue
        ak = s.actor[rids[0]][1] if rids else None
        if ak == "run":
            continue
        oid = _sid("identity", ds, "actor", a)
        actors[a] = oid
        ts = [s.rec["_times"][r] for r in rids if r in s.rec["_times"]]
        o = {"type": "identity", "spec_version": "2.1", "id": oid, "created": created, "modified": created,
             "created_by_ref": tool_id, "name": insight_short(a), "identity_class": "system",
             "description": f"Pseudonymous agent identity from the trace ({ak or 'actor'}; {len(rids):,} records). "
                            "A token or self-chosen name, not a person; one agent may hold several.",
             "x_swarm_tracer_actor": a, "x_swarm_tracer_actor_kind": ak}
        if ts:
            o["x_swarm_tracer_first_seen"], o["x_swarm_tracer_last_seen"] = _stix_ts(min(ts)), _stix_ts(max(ts))
        objs.append(o)
    # indicators: places (URLs, hosts, named places) the swarm wrote to or read from
    rows = s.flow.get("_channels", s.flow.get("top_channels", []))
    seen_ind = set()
    indicators = {}
    for r in rows[:max_places]:
        ch = r["channel"]
        typ, val = _place_value(ch)
        path = "value" if typ in ("url", "domain-name") else "name"
        pattern = f"[{typ}:{path} = {_pat_str(val)}]"
        if pattern in seen_ind:
            continue
        seen_ind.add(pattern)
        vf = reconstruct_time(r.get("first_write") or r.get("first_read") or "")
        oid = _sid("indicator", ds, pattern)
        indicators[ch] = oid
        objs.append({"type": "indicator", "spec_version": "2.1", "id": oid, "created": created, "modified": created,
                     "created_by_ref": tool_id, "name": f"Place used by the swarm: {ch}"[:250],
                     "description": f"{r.get('writes', 0):,} writes, {r.get('reads', 0):,} reads, {r.get('deliveries', 0):,} messages "
                                    f"by {r.get('actors', 0):,} actors in {ds}.",
                     "indicator_types": ["compromised"] if r.get("deliveries") else ["anomalous-activity"],
                     "pattern": pattern, "pattern_type": "stix", "valid_from": _stix_ts(vf) if vf else created,
                     "labels": ["swarm-place", ch.split(":", 1)[0]]})
    # signs: an attack-pattern per kind of sign (with its stage), a sighting per sign that fired
    sigs = insight.simulate(s)["signals"]
    aps = {}
    for g in sigs:
        stage = _stage(s, g)
        apkey = g["key"] if g["family"] != "joint" else g["kind"]
        if apkey not in aps:
            aps[apkey] = _sid("attack-pattern", ds, apkey)
            objs.append({"type": "attack-pattern", "spec_version": "2.1", "id": aps[apkey], "created": created, "modified": created,
                         "created_by_ref": tool_id, "name": g["name"] if g["family"] != "joint" else f"Coordination sign: {g['kind']}",
                         "kill_chain_phases": [{"kill_chain_name": "swarm-tracer", "phase_name": re.sub(r"[^a-z0-9-]+", "-", stage.lower()).strip("-") or "other"}],
                         "labels": [g["family"]]})
        t = g["t"]
        where = [actors[a] for a in g.get("actors", []) if a in actors]
        sid = _sid("sighting", ds, g["key"])
        o = {"type": "sighting", "spec_version": "2.1", "id": sid, "created": created, "modified": created,
             "created_by_ref": tool_id, "sighting_of_ref": aps[apkey], "first_seen": _stix_ts(t), "last_seen": _stix_ts(t),
             "count": 1, "description": f"{g['name']}: {g['why']}"[:2000],
             "x_swarm_tracer_record": g.get("record"), "x_swarm_tracer_harm_share_after": g.get("harm_share_after")}
        if where:
            o["where_sighted_refs"] = where
        # observed data: the URL or host behind the sign, when it names one
        typ, val = _place_value(str(g.get("ref") or ""))
        if typ in ("url", "domain-name"):
            sco = _sco_id(typ, val)
            od = _sid("observed-data", ds, g["key"])
            objs.append({"type": typ, "spec_version": "2.1", "id": sco, "value": val})
            objs.append({"type": "observed-data", "spec_version": "2.1", "id": od, "created": created, "modified": created,
                         "created_by_ref": tool_id, "first_observed": _stix_ts(t), "last_observed": _stix_ts(t),
                         "number_observed": 1, "object_refs": [sco]})
            o["observed_data_refs"] = [od]
        objs.append(o)
    refs = [o["id"] for o in objs if o["type"] not in ("url", "domain-name")]
    note_id = _sid("note", ds, "custody")
    objs.append({"type": "note", "spec_version": "2.1", "id": note_id, "created": created, "modified": created,
                 "created_by_ref": tool_id, "abstract": "Chain of custody", "content": "\n".join(custody_lines(c)),
                 "object_refs": [tool_id], "x_swarm_tracer_custody": c})
    objs.append({"type": "grouping", "spec_version": "2.1", "id": _sid("grouping", ds, "all"), "created": created, "modified": created,
                 "created_by_ref": tool_id, "name": f"Swarm Tracer analysis of {ds}", "context": "suspicious-activity",
                 "object_refs": refs + [note_id]})
    # dedupe SCOs that several signs share
    out, ids = [], set()
    for o in objs:
        if o["id"] in ids:
            continue
        ids.add(o["id"])
        out.append(o)
    bundle = {"type": "bundle", "id": _sid("bundle", ds, c["record_ids_sha256"]), "objects": out}
    counts = Counter(o["type"] for o in out)
    return json.dumps(bundle, indent=1, ensure_ascii=False), dict(counts)


def detections(s, c):
    from . import live
    rules, saved = live.load_rules()
    ev = {r["id"]: r for r in live.evaluate_rules(s, rules)["rules"]}
    out = []
    for r in rules:
        e = ev.get(r["id"], {})
        out.append({"id": r["id"], "title": r["name"], "severity": r["severity"], "enabled": r["enabled"],
                    "logic": ("all of" if r["match"] == "all" else "any of") + ": " + "; ".join(live.describe_condition(x) for x in r["conditions"]),
                    "match": r["match"], "conditions": r["conditions"],
                    "source": "the warning signs Swarm Tracer computes (agenttrace.insight.simulate) over a loaded trace",
                    "on_this_dataset": {"fired": bool(e.get("fired")), "time": e.get("time"), "record": e.get("record"),
                                        "harm_share_after": e.get("harm_share_after"), "hindsight": e.get("hindsight")}})
    doc = {"format": "swarm-tracer-detections", "version": 1, "rules_saved_by_user": saved, "rules_file": live.rules_path(),
           "condition_types": live.COND_TYPES, "detections": out, "custody": c}
    return json.dumps(doc, indent=1, ensure_ascii=False), len(out)


EXPORTS = {
    "timeline_csv": ("timeline", ".csv", "text/csv", timeline_csv),
    "timesketch_csv": ("timesketch", ".csv", "text/csv", timesketch_csv),
    "stix": ("stix", ".json", "application/json", stix_bundle),
    "detections": ("detections", ".json", "application/json", detections),
}


def export(s, fmt):
    if fmt not in EXPORTS:
        raise ValueError("format must be one of " + ", ".join(EXPORTS))
    stem, ext, mime, fn = EXPORTS[fmt]
    c = custody(s)
    content, n = fn(s, c)
    return {"filename": f"{stem}-{_slug(s.name)}{ext}", "mime": mime, "content": content, "count": n,
            "bytes": len(content.encode("utf-8")), "custody": {k: c[k] for k in ("fingerprint", "record_ids_sha256", "generated_at")}}


# ================================================================== routes

def _body(body):
    try:
        return json.loads(body or b"{}")
    except ValueError:
        raise ValueError("body must be JSON")


def _get_whatif(state, q):
    return whatif(_session(state), q.get("rule") or "estimate")


def _get_decisions(state, q):
    return decisions_listing(_session(state))


def _post_decide(state, q, body):
    s = _session(state)
    r = decide(s, _body(body))
    r["whatif"] = whatif(s, q.get("rule") or "estimate")
    return r


def _get_record_messages(state, q):
    s = _session(state)
    rid = q.get("id", "")
    if rid not in s.by_id:
        raise LookupError(f"no record {rid}")
    return {"id": rid, "messages": record_messages(s, rid)}


def _get_reference(state, q):
    _session(state)
    return reference_state(state)


def _post_reference_load(state, q, body):
    _session(state)
    return load_reference(state, _body(body))


def _post_reference_clear(state, q, body):
    _session(state)
    if not REF["busy"]:
        REF.update(session=None, source=None, error=None)
    return reference_state(state)


def _get_custody(state, q):
    return custody(_session(state))


def _get_export(state, q):
    return export(_session(state), q.get("format") or "")


GET = {"fx_whatif": _get_whatif, "fx_whatif_decisions": _get_decisions, "fx_whatif_record": _get_record_messages,
       "fx_reference": _get_reference, "fx_custody": _get_custody, "fx_export": _get_export}
POST = {"fx_whatif_decide": _post_decide, "fx_reference_load": _post_reference_load, "fx_reference_clear": _post_reference_clear}

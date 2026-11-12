"""Content tracing: follow what was written into the reader's later code.

A message (messages.deliveries) says a reader fetched a place after someone else wrote to it. That
shows the content was available, not that it was used. This module looks for the content itself:

  items      distinctive strings in a record: file names and paths, marker constants, repository and
             dataset names, function names, numbered redaction placeholders ([ENCODED BLOB 12], ...).
             Distinctive = an identifier-like shape AND a low document frequency: held by at most
             MAX_NAMED named actors and MAX_ACTORS actors in all (anonymous runs included) and found
             in at most MAX_RECORDS records. Identity tokens ([CREDENTIAL n]) are left out: carried
             tokens are a separate analysis. Each record is read up to TEXT_CAP characters.
  grades     per message: "used" when at least one distinctive item of the write record appears in a
             record of the reader at or after the read (not the read itself, not a response to it), and
             in no record of the reader before the read, and not in the read record (a reader that
             names the item while fetching knew it already). Undated reader records count as
             "before" (conservative). "fetched only" when the write had traceable items and the reader
             had later records, yet nothing reappeared (sub-flags: the item came back in the response
             to the read; the read names an item of the write). "unclear" otherwise (order unknown,
             nothing distinctive in the write, or no later record of the reader).
  handovers  content with NO shared place: an item first seen under named actor A and later under
             named actor B (B has no undated record holding it), where the two first records are not
             the same program, the item is not part of a place name, and B's record does not touch a
             place A wrote. Ranked by rarity (1 / actors holding the item). A pair is "strong" with
             STRONG_ITEMS or more exclusive items (held by nobody else) whose order is clear.

Everything is cached on the session (s._fx_content). Times are mostly estimated, so an order closer
than ORDER_MARGIN is flagged uncertain and never makes a strong hand-over.
"""
import re
import time as _time
from collections import defaultdict

from . import messages, reconstruct

iso = reconstruct.iso

TEXT_CAP = 20000        # characters of each record that are read
MAX_RECORDS = 60        # an item in more records than this is boilerplate
MAX_NAMED = 3           # ... or held by more named actors than this
MAX_ACTORS = 8          # ... or by more actors in all (named + anonymous runs)
OCC_CAP = MAX_RECORDS + 1
ORDER_MARGIN = 3600.0   # estimated times closer than this cannot be ordered
STRONG_ITEMS = 2        # exclusive items a no-place hand-over needs to be called strong
QUOTE = 160
TOP_HANDOVERS = 60

_TOKEN = re.compile(r"\[[A-Z][A-Za-z0-9 :_\-]{2,60}\]|[A-Za-z0-9_][A-Za-z0-9_.\-/]{4,79}")
_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")
_INNER_CAP = re.compile(r"[a-z][A-Z]")
_PLACEHOLDER_SKIP = ("CREDENTIAL",)


_FILE_EXT = frozenset("json jsonl txt py js ts csv tsv so sh md yaml yml parquet html htm tar gz tgz zip c h cc cpp log env pem key db sql "
                      "sqlite toml cfg conf ini bin png jpg jpeg gif svg lock xml rs go rb php ipynb pkl pt onnx wasm exe dll whl".split())
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _clean(tok):
    """The token as an item, or None when its shape is not distinctive."""
    if tok[0] == "[":
        if not _HAS_DIGIT.search(tok) or any(k in tok for k in _PLACEHOLDER_SKIP):
            return None
        return tok
    tok = tok.strip("./-")
    if len(tok) < 6 or not _HAS_LETTER.search(tok) or _DATE.match(tok):
        return None
    if "." in tok and "/" not in tok:
        # a.b without a path: kept only when it ends like a file name (x.json); otherwise it is a
        # property chain or a call (document.body.innerText, r.status, vals.get)
        return tok if tok.rsplit(".", 1)[1].lower() in _FILE_EXT and len(tok.split(".")[0]) > 2 else None
    if _HAS_DIGIT.search(tok) or "/" in tok:
        return tok
    if ("_" in tok.strip("_") or _INNER_CAP.search(tok)) and len(tok) >= 8:
        return tok
    return None


def specific(item):
    """An item that looks invented or addressed (a digit, a path, a file name, a numbered placeholder),
    as opposed to a name two programmers could both pick from the same vocabulary (parse_matrix)."""
    return item[0] == "[" or bool(_HAS_DIGIT.search(item)) or "/" in item or "." in item


def items_of(text):
    """The distinctive-shaped items of one text (before any frequency test)."""
    out = set()
    for tok in set(_TOKEN.findall(text[:TEXT_CAP])):
        c = _clean(tok)
        if c:
            out.add(c)
    return out


def _session(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _agent_of(s):
    """actor -> estimated agent (fx_whatif's merge groups); actors outside a group map to themselves."""
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


def _snip(text, item, width=QUOTE):
    i = text.find(item)
    if i < 0:
        return ""
    room = max(0, width - len(item))
    a = max(0, i - room // 2)
    b = min(len(text), a + width)
    out = text[a:b].replace("\n", " ").replace("\r", " ")
    return ("…" if a else "") + out + ("…" if b < len(text) else "")


def _rtime(s, rid, times):
    """A record's time; a response without one takes its payload's."""
    t = times.get(rid)
    if t is None:
        e = s.by_id.get(rid)
        if e is not None and e.parent:
            t = times.get(e.parent)
    return t


def build(s):
    c = getattr(s, "_fx_content", None)
    if c is not None:
        return c
    t0 = _time.time()
    times = s.rec["_times"]
    dels = list(s.flow["_deliveries"])
    named_ids = [e.id for e in s.events if s.actor[e.id][1] != "run"]
    # 1. candidate items: everything distinctive-shaped in a named actor's record or a message's write
    cand = set()
    seed_ids = set(named_ids) | {d["write_id"] for d in dels}
    for rid in seed_ids:
        cand |= items_of(s.by_id[rid].text)
    # 2. where every candidate occurs, over all records (capped: past the cap it is boilerplate)
    occ = defaultdict(list)
    count = defaultdict(int)
    find = _TOKEN.findall
    for e in s.events:
        toks = set(find(e.text[:TEXT_CAP]))
        hit = set()
        for tok in toks:
            if tok in cand:
                hit.add(tok)
            elif tok[0] != "[":
                st = tok.strip("./-")
                if st in cand:
                    hit.add(st)
        for it in hit:
            count[it] += 1
            if count[it] <= OCC_CAP:
                occ[it].append(e.id)
    actor = s.actor
    info = {}                     # item -> {"named": n, "actors": n, "records": n} for distinctive items
    for it, ids in occ.items():
        if count[it] > MAX_RECORDS:
            continue
        holders = {actor[r][0] for r in ids}
        named = {actor[r][0] for r in ids if actor[r][1] != "run"}
        if len(named) <= MAX_NAMED and len(holders) <= MAX_ACTORS:
            info[it] = {"named": len(named), "actors": len(holders), "records": count[it]}
    amap = _agent_of(s)
    place_text = " ".join({op[0] for op in s.op_list})
    c = {"occ": occ, "count": count, "info": info, "amap": amap, "place_text": place_text, "candidates": len(cand)}
    c["messages"] = _grade(s, c, dels, times)
    c["handovers"] = _handovers(s, c, times)
    c["seconds"] = round(_time.time() - t0, 2)
    s._fx_content = c
    return c


# ------------------------------------------------------------------ grades

def _grade(s, c, dels, times):
    occ, info, amap, actor = c["occ"], c["info"], c["amap"], s.actor
    out = []
    for n, d in enumerate(dels):
        w, r = d["write_id"], d["read_id"]
        wt, rt = d.get("write_time"), d.get("read_time")
        reader = d["to"]
        we, re_ = s.by_id[w], s.by_id[r]
        m = {"n": n, "from": d["from"], "to": reader, "channel": d["channel"], "write_id": w, "read_id": r,
             "write_time": iso(wt) if wt is not None else None, "read_time": iso(rt) if rt is not None else None,
             "wait_h": d.get("latency_h"), "named": d.get("from_kind") != "run" and d.get("to_kind") != "run",
             "same_agent": d["from"] in amap and amap.get(d["from"]) == amap.get(reader)}
        ch_name = d["channel"].split(":", 1)[-1]
        w_items = [it for it in items_of(we.text) if it in info and it not in ch_name and ch_name not in it]
        m["traceable"] = len(w_items)
        read_text = re_.text
        kids = set(s.children.get(r, []))
        used, delivered, targeted = [], [], []
        later = False
        if rt is not None:
            for rid in s.by_actor.get(reader, []) if hasattr(s, "by_actor") else []:
                t = _rtime(s, rid, times)
                if rid != r and rid not in kids and t is not None and t >= rt:
                    later = True
                    break
        for it in w_items:
            if it in read_text:
                targeted.append(it)
                continue
            before, uses, resp = False, [], None
            for rid in occ[it]:
                if actor[rid][0] != reader and rid not in kids:
                    continue
                if rid in kids:
                    resp = resp or rid
                    continue
                t = _rtime(s, rid, times)
                if t is None or rt is None or t < rt:
                    before = True
                    break
                uses.append((t, rid))
            if before:
                continue
            if uses:
                t, rid = min(uses)
                used.append({"item": it, "use_id": rid, "use_time": iso(t), "after_h": round((t - rt) / 3600.0, 2),
                             "uses": len(uses), "rarity": info[it], "specific": specific(it), "uncertain": (t - rt) < ORDER_MARGIN / 4,
                             "write_snip": _snip(we.text, it), "use_snip": _snip(s.by_id[rid].text, it)})
            elif resp:
                delivered.append({"item": it, "response_id": resp, "snip": _snip(s.by_id[resp].text, it)})
        used.sort(key=lambda u: (not u["specific"], u["rarity"]["actors"], u["after_h"]))
        weak = []
        if not any(u["specific"] for u in used) and len(used) < 2:
            weak, used = used, []     # one dictionary-like name is not enough to say the content was used
        if rt is None or wt is None:
            grade, why = "unclear", "the order of the write and the read is unknown"
        elif used:
            grade, why = "used", f"{len(used)} distinctive item(s) of the write appear in the reader's later records and not before"
        elif not w_items:
            grade, why = "unclear", "the write record holds nothing distinctive to trace (its content may be redacted or encoded)"
        elif not later:
            grade, why = "unclear", "the reader has no dated record after the read"
        else:
            grade, why = "fetched only", "the write had traceable items and the reader went on working, but none reappeared"
        m.update({"grade": grade, "why": why, "used": used[:6], "used_total": len(used), "delivered": delivered[:3],
                  "delivered_total": len(delivered), "targeted": sorted(targeted)[:4], "targeted_total": len(targeted), "weak": weak[:2]})
        out.append(m)
    return out


# ------------------------------------------------------------------ hand-overs with no shared place

def _handovers(s, c, times):
    occ, info, amap, actor = c["occ"], c["info"], c["amap"], s.actor
    place_text = c["place_text"]
    prefix = getattr(s, "prefix", {})
    msg_pairs = {frozenset((d["from"], d["to"])) for d in s.flow["_deliveries"]}
    wrote = defaultdict(set)         # actor -> places it wrote
    touched = defaultdict(set)       # record -> places it touches
    for ch, op, a, ak, t, i, rid in s.op_list:
        touched[rid].add(ch)
        if op in ("write", "post"):
            wrote[a].add(ch)
    skipped = {"same_program": 0, "place_name": 0, "undated": 0, "via_place": 0}
    pairs = {}
    for it, inf in info.items():
        if inf["named"] < 2:
            continue
        first = {}                   # named actor -> (time, record) of its first dated record with the item
        undated = set()
        run_first = None
        for rid in occ[it]:
            a, ak = actor[rid]
            t = _rtime(s, rid, times)
            if ak == "run":
                if t is not None and (run_first is None or t < run_first):
                    run_first = t
                continue
            if t is None:
                undated.add(a)
            elif a not in first or (t, rid) < first[a]:
                first[a] = (t, rid)
        order = sorted(first.items(), key=lambda kv: kv[1])
        if len(order) < 2:
            skipped["undated"] += 1
            continue
        if it in place_text:
            skipped["place_name"] += 1
            continue
        a, (ta, ra) = order[0]
        if a in undated:
            skipped["undated"] += 1
            continue
        for b, (tb, rb) in order[1:]:
            if b in undated:
                skipped["undated"] += 1
                continue
            if prefix.get(ra) is not None and prefix.get(ra) == prefix.get(rb):
                skipped["same_program"] += 1
                continue
            if touched.get(rb, set()) & wrote.get(a, set()):
                skipped["via_place"] += 1
                continue
            gap = tb - ta
            p = pairs.setdefault((a, b), {"from": a, "to": b, "items": []})
            p["items"].append({"item": it, "rarity": round(1.0 / inf["actors"], 3), "holders": inf["actors"],
                               "named_holders": inf["named"], "records": inf["records"], "exclusive": inf["actors"] == 2, "specific": specific(it),
                               "first_id": ra, "first_time": iso(ta), "then_id": rb, "then_time": iso(tb),
                               "gap_h": round(gap / 3600.0, 2), "order_uncertain": gap < ORDER_MARGIN,
                               "run_earlier": run_first is not None and run_first < ta,
                               "first_snip": _snip(s.by_id[ra].text, it), "then_snip": _snip(s.by_id[rb].text, it)})
    out = []
    for (a, b), p in pairs.items():
        its = sorted(p["items"], key=lambda x: (-x["rarity"], not x["specific"], x["order_uncertain"], x["item"]))
        clear = [x for x in its if x["exclusive"] and x["specific"] and not x["order_uncertain"] and not x["run_earlier"]]
        p["n_items"] = len(its)
        p["exclusive_items"] = len(clear)
        p["score"] = round(sum(x["rarity"] for x in its), 3)
        p["strong"] = len(clear) >= STRONG_ITEMS
        p["has_message"] = frozenset((a, b)) in msg_pairs
        p["same_agent"] = a in amap and amap.get(a) == amap.get(b)
        p["items"] = its[:8]
        out.append(p)
    out.sort(key=lambda p: (-p["strong"], -p["exclusive_items"], -p["score"], p["from"], p["to"]))
    return {"pairs": out, "skipped": skipped}


# ------------------------------------------------------------------ results

# Measured with simulate_check() on simulated swarms (groundtruth.make, 40 agents, seeds 1-3, code_traces
# pack). The benign swarm has no messages and no hand-overs at all, so everything found there is false.
# The coordinated swarm's readers fetch a message and do nothing with it, so "used" there is false too.


def _counts(msgs):
    g = {"used": 0, "fetched only": 0, "unclear": 0}
    for m in msgs:
        g[m["grade"]] += 1
    return g


def summary(s):
    c = build(s)
    msgs = c["messages"]
    named = [m for m in msgs if m["named"]]
    ho = c["handovers"]["pairs"]
    strong = [p for p in ho if p["strong"]]
    return {
        "messages": len(msgs), "grades": _counts(msgs),
        "named": {"messages": len(named), "grades": _counts(named),
                  "same_agent": sum(1 for m in named if m["same_agent"]),
                  "grades_across_agents": _counts([m for m in named if not m["same_agent"]]),
                  "grades_same_agent": _counts([m for m in named if m["same_agent"]])},
        "delivered": sum(1 for m in msgs if m["delivered_total"]), "targeted": sum(1 for m in msgs if m["targeted_total"]),
        "handovers": {"pairs": len(ho), "strong": len(strong),
                      "strong_same_agent": sum(1 for p in strong if p["same_agent"]),
                      "strong_with_message": sum(1 for p in strong if p["has_message"]),
                      "strong_new": sum(1 for p in strong if not p["has_message"] and not p["same_agent"]),
                      "skipped": c["handovers"]["skipped"]},
        "items": {"candidates": c["candidates"], "distinctive": len(c["info"])},
        "thresholds": {"max_records": MAX_RECORDS, "max_named": MAX_NAMED, "max_actors": MAX_ACTORS, "text_cap": TEXT_CAP,
                       "order_margin_h": ORDER_MARGIN / 3600.0, "strong_items": STRONG_ITEMS},
        "simulated": SIMULATED, "seconds": c["seconds"],
    }


def r_content(state, q):
    s = _session(state)
    c = build(s)
    order = {"used": 0, "fetched only": 1, "unclear": 2}
    msgs = sorted(c["messages"], key=lambda m: (order[m["grade"]], not m["named"], m["same_agent"], m["n"]))
    return {"summary": summary(s), "messages": msgs, "handovers": c["handovers"]["pairs"][:TOP_HANDOVERS],
            "handovers_total": len(c["handovers"]["pairs"])}


def item_chain(s, item, cap=600):
    """Every record holding the string, in time order, and its holders."""
    item = (item or "").strip()
    if len(item) < 4:
        raise ValueError("give a string of at least 4 characters")
    if len(item) > 200:
        raise ValueError("the string is too long")
    c = build(s)
    times, amap = s.rec["_times"], c["amap"]
    ids = c["occ"].get(item)
    if ids is None or c["count"].get(item, 0) > OCC_CAP:
        ids = [e.id for e in s.events if item in e.text[:TEXT_CAP]]
    total = len(ids)
    rows = []
    for rid in ids:
        a, ak = s.actor[rid]
        rows.append((_rtime(s, rid, times), rid, a, ak))
    rows.sort(key=lambda x: (x[0] is None, x[0] or 0, s.order[x[1]]))
    holders = {}
    for t, rid, a, ak in rows:
        h = holders.setdefault(a, {"actor": a, "kind": ak, "agent": amap.get(a), "records": 0, "undated": 0,
                                   "first_time": None, "last_time": None, "first_id": None, "times": []})
        h["records"] += 1
        if t is None:
            h["undated"] += 1
            h["first_id"] = h["first_id"] or rid
            continue
        if h["first_time"] is None:
            h["first_time"], h["first_id"] = iso(t), rid
        h["last_time"] = iso(t)
        if len(h["times"]) < 80:
            h["times"].append([iso(t), rid, s.by_id[rid].kind])
    hl = sorted(holders.values(), key=lambda h: (h["first_time"] is None, h["first_time"] or "", h["actor"]))
    first = next((r for r in rows if r[0] is not None), rows[0] if rows else None)
    return {"item": item, "records": total, "holders": hl[:60], "holders_total": len(hl),
            "named_holders": sum(1 for h in hl if h["kind"] != "run"),
            "distinctive": c["info"].get(item),
            "first": {"id": first[1], "actor": first[2], "time": iso(first[0]) if first[0] is not None else None,
                      "snip": _snip(s.by_id[first[1]].text, item)} if first else None,
            "chain": [{"time": iso(t) if t is not None else None, "id": rid, "actor": a} for t, rid, a, ak in rows[:cap]]}


def r_content_item(state, q):
    return item_chain(_session(state), q.get("q", ""))


GET = {"content": r_content, "content_item": r_content_item}
POST = {}


# ------------------------------------------------------------------ measurement on simulated swarms

def simulate_check(agents=40, seeds=(1, 2, 3), folder=None):
    """Counts on simulated swarms with known truth: python3 -m agenttrace.fx_content"""
    import os
    import tempfile
    from . import groundtruth
    from .session import Session
    out = {"agents": agents, "seeds": list(seeds)}
    for mode in ("benign", "coordinated"):
        tot = {"messages": 0, "used": 0, "fetched only": 0, "unclear": 0, "handover_pairs": 0, "handover_strong": 0,
               "possible_pairs": 0}
        for seed in seeds:
            d = tempfile.mkdtemp(prefix="fxc_", dir=folder)
            groundtruth.make(d, agents=agents, seed=seed, mode=mode)
            s = Session()
            s.load(os.path.join(d, "trace.jsonl"), "code_traces.json")
            sm = summary(s)
            tot["messages"] += sm["messages"]
            for g, n in sm["grades"].items():
                tot[g] += n
            tot["handover_pairs"] += sm["handovers"]["pairs"]
            tot["handover_strong"] += sm["handovers"]["strong"]
            n = len({a for a, ak in s.actor.values() if ak != "run"})
            tot["possible_pairs"] += n * (n - 1) // 2
        out[mode] = tot
    return out


SIMULATED = {"agents": 40, "seeds": [1, 2, 3], "measured": "2026-11-13",
             "benign": {"messages": 7, "used": 0, "fetched only": 7, "unclear": 0, "handover_pairs": 140,
                        "handover_strong": 0, "possible_pairs": 2983},
             "coordinated": {"messages": 513, "used": 0, "fetched only": 217, "unclear": 296, "handover_pairs": 137,
                             "handover_strong": 0, "possible_pairs": 2983}}


if __name__ == "__main__":
    import json
    print(json.dumps(simulate_check(), indent=1))

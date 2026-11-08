"""Check an investigation report's claims against the traces.

A claims file lists what a report says, the text patterns that show it, and the record
IDs the report cites. For each claim the tool reports:
  - how many records show it, by kind, and when (estimated or recorded time)
  - whether the cited records exist, match the patterns, and have a time
  - which identities took part, in the order each first appeared (how it spread)
  - pieces of information (tokens, keys) that recur across the claim's records
  - places (shared names) the claim's records touch
  - whether two identities took part in separate records (coordination)
Nothing here is specific to one report or one dataset.
"""
import json
import re
from collections import Counter, defaultdict

from .reconstruct import iso, info_of, places_of


def load_claims(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for c in cfg["claims"]:
        flags = re.I if "i" in c.get("flags", "") else 0
        c["_rx"] = re.compile("|".join(f"(?:{p})" for p in c["patterns"]), flags)
    return cfg


def evaluate(events, pack, res, rec, cfg):
    times, ids = rec["_times"], rec["_ids"]
    by_id = {e.id: e for e in events}
    order = {e.id: i for i, e in enumerate(events)}
    out = []
    for c in cfg["claims"]:
        rx = c["_rx"]
        hits = [e for e in events if rx.search(e.text)]
        kinds = Counter(e.kind for e in hits)
        timed = sorted((times[e.id], e.id) for e in hits if e.id in times)
        threads = {res["_root"][e.id] for e in hits}

        # identities, in order of first appearance (time first, then file order)
        first_by_id = {}
        for e in sorted(hits, key=lambda e: (times.get(e.id, float("inf")), order[e.id])):
            for tok in ids[e.id]:
                if tok not in first_by_id:
                    first_by_id[tok] = (times.get(e.id), e.id)
        spread = [{"identity": tok, "first_time": iso(t), "record": rid}
                  for tok, (t, rid) in sorted(first_by_id.items(),
                                              key=lambda kv: (kv[1][0] if kv[1][0] is not None else float("inf"),
                                                              order[kv[1][1]]))]
        # two distinct identities in separate records; shared identities do not count
        shared_ids = set(pack.raw.get("shared_identities", []))
        distinct = [s_ for s_ in spread if s_["identity"] not in shared_ids]
        sep = None
        if len(distinct) >= 2:
            sep = next((s_ for s_ in distinct[1:] if s_["record"] != distinct[0]["record"]), None)
        for s_ in spread:
            s_["shared"] = s_["identity"] in shared_ids

        # recurring information and places
        item_recs = defaultdict(list)
        place_recs = Counter()
        for e in hits:
            for fam, item in info_of(e, pack):
                item_recs[item].append(e.id)
            for p in places_of(e, pack):
                place_recs[p] += 1
        recurring = sorted(((k, v) for k, v in item_recs.items() if len(set(v)) >= 2), key=lambda kv: -len(set(kv[1])))

        # how each place the claim touches spread: first and last dated use, records, threads
        place_tl = []
        for p_, n in place_recs.most_common(4):
            recs = [e for e in hits if p_ in places_of(e, pack)]
            ts = sorted(times[e.id] for e in recs if e.id in times)
            place_tl.append({"place": p_, "records": n, "threads": len({res["_root"][e.id] for e in recs}),
                             "first": iso(ts[0]) if ts else None, "last": iso(ts[-1]) if ts else None,
                             "first_record": min((e.id for e in recs), key=lambda r: order[r])})

        cited = []
        for rid in c.get("cited", []):
            e = by_id.get(rid)
            cited.append({"id": rid, "in_data": e is not None,
                          "matches_patterns": bool(e and rx.search(e.text)),
                          "time": iso(times.get(rid)) if e else None,
                          "kind": e.kind if e else None})

        out.append({
            "id": c["id"], "section": c["section"], "says": c["says"],
            "records": len(hits), "by_kind": dict(kinds.most_common()),
            "timed_records": len(timed),
            "first_time": iso(timed[0][0]) if timed else None, "first_record": timed[0][1] if timed else None,
            "last_time": iso(timed[-1][0]) if timed else None,
            "threads": len(threads),
            "identities": len(spread),
            "spread": spread[:12],
            "two_identities_separately": ({"time": sep["first_time"], "identity": sep["identity"], "record": sep["record"]}
                                          if sep else None),
            "recurring_items": [{"item": k, "records": len(set(v)), "first_record": min(v, key=lambda r: order[r])}
                                for k, v in recurring[:6]],
            "places": place_recs.most_common(6),
            "place_spread": place_tl,
            "cited": cited,
            "cited_found": sum(1 for x in cited if x["in_data"]),
            "cited_matched": sum(1 for x in cited if x["matches_patterns"]),
            "cited_timed": sum(1 for x in cited if x["time"]),
        })
    return out

"""Reconstruction for any agent trace: time, identities, information spread, edges, replay.

Every step is driven by the pack and tests its own assumptions:
- time: a record's own time field if present; otherwise, if the pack allows it, unix
  seconds written in the text, fitted per contiguous block of one record kind. A block is
  only timed if its timestamps are dense and rise with file order.
- identity: the actor field if present; otherwise identity tokens the pack describes (for
  example credentials used to authenticate). Role consistency is measured, because a token
  only stands for one holder if the data keeps it stable.
- spread: when each piece of information is first seen, and when it is first used as an
  identity; items seen as data before they are used are "seen, then used".
- edges: identity A carries item B before B is used (A had B first); two identities use the
  same place in separate records; replies between identities come from analysis.py.
- replay: the first time of each signal, and how much harmful activity came after it.
"""
import bisect
import datetime as dt
import re
import statistics
from collections import Counter, defaultdict

UTC = dt.timezone.utc
EPOCH = re.compile(r"(?<!\d)(1[5-9]\d{8}|20\d{8})(?!\d)")


def iso(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t is not None else None


def spearman(pts):
    if len(pts) < 3:
        return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0] * len(v)
        for i, k in enumerate(order):
            r[k] = i
        return r
    xs, ys = zip(*pts)
    rx, ry = rank(xs), rank(ys)
    m = (len(pts) - 1) / 2
    den = sum((a - m) ** 2 for a in rx)
    return sum((a - m) * (b - m) for a, b in zip(rx, ry)) / den if den else None


def pava(xs, ys):
    out = []
    for x, y in zip(xs, ys):
        out.append([y, 1, x, x])
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            y2, w2, a2, b2 = out.pop()
            y1, w1, a1, b1 = out.pop()
            out.append([(y1 * w1 + y2 * w2) / (w1 + w2), w1 + w2, a1, b2])
    return [(a + b) / 2 for _, _, a, b in out], [y for y, _, _, _ in out]


def _parse_day(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp()


# ------------------------------------------------------------------ time

def infer_times(events, pack):
    cfg = pack.time or {}
    times = {}
    source = Counter()
    for e in events:
        if e.time:
            times[e.id] = e.time.timestamp()
            source["time_field"] += 1
    blocks_out = []
    fit_errors = []
    clamped_ids = set()
    if cfg.get("embedded_epoch"):
        found = [(i, int(m)) for i, e in enumerate(events) for m in EPOCH.findall(e.text)]
        window = cfg.get("window", "auto")
        if window == "auto":
            if found:
                med = statistics.median(v for _, v in found)
                lo, hi = med - 15 * 86400, med + 15 * 86400
            else:
                lo = hi = None
        else:
            lo, hi = _parse_day(window[0]), _parse_day(window[1])
        min_points = cfg.get("min_points", 100)
        min_rho = cfg.get("min_spearman", 0.8)
        # contiguous blocks of one kind
        blocks, start = [], 0
        for i in range(1, len(events) + 1):
            if i == len(events) or events[i].kind != events[start].kind:
                blocks.append((start, i))
                start = i
        pts_by_block = defaultdict(list)
        if lo is not None:
            bidx = [0] * len(events)
            for b, (a, z) in enumerate(blocks):
                for i in range(a, z):
                    bidx[i] = b
            for i, v in found:
                if lo <= v <= hi:
                    pts_by_block[bidx[i]].append((i, v))
        for b, (a, z) in enumerate(blocks):
            pts = sorted(pts_by_block.get(b, []))
            rho = spearman(pts)
            ok = len(pts) >= min_points and rho is not None and rho >= min_rho
            info = {"kind": events[a].kind, "first_id": events[a].id, "last_id": events[z - 1].id,
                    "records": z - a, "timestamp_points": len(pts),
                    "spearman": round(rho, 3) if rho is not None else None, "timed": ok}
            if ok:
                # about 200 bins per block; small blocks are fitted point by point
                size = max(1, (z - a) // 200)
                bins = defaultdict(list)
                for x, y in pts:
                    bins[x // size].append(y)
                keys = sorted(bins)
                fx, fy = pava([k * size + size / 2 for k in keys], [statistics.median(bins[k]) for k in keys])

                def est(x):
                    if x <= fx[0]:
                        return fy[0]
                    if x >= fx[-1]:
                        return fy[-1]
                    j = bisect.bisect_left(fx, x)
                    x0, x1, y0, y1 = fx[j - 1], fx[j], fy[j - 1], fy[j]
                    return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y0

                errs = sorted(abs(est(x) - y) / 3600 for x, y in pts)
                info["fit_error_hours_median"] = round(errs[len(errs) // 2], 2)
                info["fit_error_hours_p90"] = round(errs[int(len(errs) * 0.9)], 2)
                max_p90 = cfg.get("max_p90_error_hours")
                if max_p90 is not None and info["fit_error_hours_p90"] > max_p90:
                    info["timed"] = False
                    info["rejected"] = f"90th-percentile error above {max_p90} h"
                    blocks_out.append(info)
                    continue
                fit_errors += errs
                clamped = 0
                for i in range(a, z):
                    if events[i].id not in times:
                        times[events[i].id] = est(i)
                        source["estimated_from_text"] += 1
                        if i < pts[0][0] or i > pts[-1][0]:
                            clamped += 1
                            clamped_ids.add(events[i].id)
                info["clamped_to_range_end"] = clamped
            blocks_out.append(info)
    # children inherit a parent's time
    by_id = {e.id: e for e in events}
    for e in events:
        if e.id not in times and e.parent and e.parent in times:
            times[e.id] = times[e.parent]
            source["inherited_from_parent"] += 1
    test = {
        "source": dict(source),
        "untimed": len(events) - len(times),
        "blocks": [b for b in blocks_out if b["timestamp_points"] or b["timed"]],
        "blocks_total": len(blocks_out),
        "fit_error_hours_median": round(sorted(fit_errors)[len(fit_errors) // 2], 2) if fit_errors else None,
        "_clamped": clamped_ids,
    }
    if times:
        test["span"] = [iso(min(times.values())), iso(max(times.values()))]
    return times, test


# ------------------------------------------------------------------ identity

def is_action(e, pack):
    """Records that are actions (for example code an agent ran, or messages it sent).
    The pack's action_kinds limits identities, intents and harm to these; other records
    still count as places where information is seen."""
    kinds = pack.raw.get("action_kinds")
    return not kinds or e.kind in kinds


def identities_of(e, pack):
    out = {}
    if e.actor:
        out[e.actor] = "actor_field"
    if not is_action(e, pack):
        return out
    for role, rx in pack.identity_patterns:
        for m in rx.finditer(e.text):
            out.setdefault(m.group(1), role)
    vi = pack.variable_identity
    if vi:
        for m in vi["assign"].finditer(e.text):
            var, tok = m.group(1), m.group(2)
            if re.search(vi["use"].replace("{var}", re.escape(var)), e.text):
                out.setdefault(tok, "via_variable")
    return out


def info_of(e, pack):
    items = set()
    for fam, rx in pack.info_patterns:
        for m in rx.finditer(e.text):
            items.add((fam, m.group(0)))
    return items


def places_of(e, pack):
    return {m.group(0) for _, rx in pack.shared_names for m in rx.finditer(e.text)}


def intent_of(e, pack):
    if not is_action(e, pack):
        return None
    for name, rx in pack.intents:
        if rx.search(e.text):
            return name
    return "other" if pack.intents else None


# ------------------------------------------------------------------ main

def reconstruct(events, pack, res):
    times, time_test = infer_times(events, pack)
    ids = {e.id: identities_of(e, pack) for e in events}
    infos = {e.id: info_of(e, pack) for e in events}
    places = {e.id: places_of(e, pack) for e in events}
    intents = {e.id: intent_of(e, pack) for e in events}
    evidence = res["_evidence"]

    # stable-token test
    roles = defaultdict(Counter)
    for e in events:
        for tok, role in ids[e.id].items():
            roles[tok][role] += 1
    frequent = {t: c for t, c in roles.items() if sum(c.values()) >= 5}
    stable = sum(1 for c in frequent.values() if c.most_common(1)[0][1] / sum(c.values()) >= 0.9)

    # identities
    uses = Counter()
    first_use, last_use = {}, {}
    id_intents = defaultdict(Counter)
    for e in events:
        t = times.get(e.id)
        for tok in ids[e.id]:
            uses[tok] += 1
            if intents[e.id]:
                id_intents[tok][intents[e.id]] += 1
            if t is not None:
                first_use[tok] = min(first_use.get(tok, t), t)
                last_use[tok] = max(last_use.get(tok, t), t)

    # spread: items seen as data before first use as identity
    seen_data = defaultdict(list)
    for e in events:
        t = times.get(e.id)
        if t is None:
            continue
        for fam, item in infos[e.id]:
            if item not in ids[e.id]:
                seen_data[item].append((t, e.id, e.kind, fam))
    seen_then_used = []
    for item, tu in first_use.items():
        prior = sorted(s for s in seen_data.get(item, []) if s[0] < tu)
        if prior:
            t0, rid, kind, fam = prior[0]
            seen_then_used.append({"item": item, "family": fam, "first_seen": iso(t0), "first_seen_id": rid,
                                   "first_seen_kind": kind, "first_used": iso(tu), "uses": uses[item],
                                   "lead_hours": round((tu - t0) / 3600, 1)})
    seen_then_used.sort(key=lambda r: r["first_used"])

    # identities the pack marks as shared by many agents (for example one evaluation key)
    # never count as a distinct actor in coordination measures
    shared_ids = set(pack.raw.get("shared_identities", []))

    # carried edges
    carried = Counter()
    carried_ev = defaultdict(list)
    first_carry = None
    for e in events:
        t = times.get(e.id)
        if t is None or not ids[e.id]:
            continue
        for fam, item in infos[e.id]:
            if item in ids[e.id]:
                continue
            tu = first_use.get(item)
            if tu is not None and t <= tu:
                for a in ids[e.id]:
                    if a != item and a not in shared_ids:
                        carried[(a, item)] += 1
                        if len(carried_ev[(a, item)]) < 3:
                            carried_ev[(a, item)].append(e.id)
                        if first_carry is None or t < first_carry[0]:
                            first_carry = (t, f"{a} carried {item} in {e.id}")

    # shared places
    place_ids = defaultdict(dict)
    for e in events:
        t = times.get(e.id)
        if t is None:
            continue
        for p in places[e.id]:
            for a in ids[e.id]:
                if a in shared_ids:
                    continue
                cur = place_ids[p].get(a)
                if cur is None or t < cur[0]:
                    place_ids[p][a] = (t, e.id)
    shared_places = []
    for p, d in place_ids.items():
        if len(d) >= 2:
            o = sorted(d.items(), key=lambda kv: kv[1][0])
            shared_places.append({"place": p, "identities": [a for a, _ in o],
                                  "first": iso(o[0][1][0]), "second": iso(o[1][1][0]),
                                  "first_id": o[0][1][1], "second_id": o[1][1][1],
                                  "same_record": o[0][1][1] == o[1][1][1]})
    shared_places.sort(key=lambda s: s["second"])

    # activity by hour
    by_hour = defaultdict(Counter)
    for e in events:
        t = times.get(e.id)
        if t is not None and intents[e.id]:
            by_hour[iso(t)[:13]][intents[e.id]] += 1

    # replay
    def is_harm(e):
        if not is_action(e, pack):
            return False
        return (intents[e.id] in pack.harm) or any(x in pack.harm for x in evidence[e.id])

    harm_t = sorted(times[e.id] for e in events if e.id in times and is_harm(e))
    stu = {r["item"] for r in seen_then_used}
    stu_t = sorted(times[e.id] for e in events if e.id in times and any(tok in stu for tok in ids[e.id]))
    signals = {}
    for name in sorted(pack.harm):
        best = None
        for e in events:
            t = times.get(e.id)
            if t is not None and is_action(e, pack) and (intents[e.id] == name or name in evidence[e.id]) \
                    and (best is None or t < best[0]):
                best = (t, e.id)
        if best:
            signals[f"first: {name}"] = best
    sep = [s for s in shared_places if not s["same_record"]]
    if sep:
        s0 = sep[0]
        signals["coordination: two identities use one place"] = (
            dt.datetime.strptime(s0["second"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp(), s0["place"])
    if first_carry:
        signals["coordination: one identity carries another's token"] = first_carry
    if seen_then_used:
        r0 = seen_then_used[0]
        signals["spread: first use of an item seen earlier"] = (
            dt.datetime.strptime(r0["first_used"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp(), r0["item"])
    last_t = max(times.values()) if times else None
    replay = []
    clamped = time_test.get("_clamped", set())
    for name, (T, ref) in sorted(signals.items(), key=lambda kv: kv[1][0]):
        # a time clamped to the start of a fitted range means "at or before"
        at_or_before = isinstance(ref, str) and ref in clamped
        replay.append({"signal": name, "time": ("at or before " if at_or_before else "") + iso(T), "ref": ref,
                       "harm_after": sum(1 for x in harm_t if x > T),
                       "harm_share_after": round(sum(1 for x in harm_t if x > T) / len(harm_t), 3) if harm_t else None,
                       "spread_share_after": round(sum(1 for x in stu_t if x > T) / len(stu_t), 3) if stu_t else None,
                       "hours_before_last": round((last_t - T) / 3600, 1) if last_t else None})

    time_test = {k: v for k, v in time_test.items() if not k.startswith("_")}
    return {
        "time_test": time_test,
        "identity_test": {"tokens_used_5_plus": len(frequent), "with_one_role_90pct": stable},
        "identities_total": len(uses),
        "identities": [{"identity": tok, "uses": n, "first": iso(first_use.get(tok)), "last": iso(last_use.get(tok)),
                        "roles": dict(roles[tok]), "intents": dict(id_intents[tok].most_common(3))}
                       for tok, n in uses.most_common(30)],
        "intents": dict(Counter(v for v in intents.values() if v).most_common()),
        "activity_by_hour": {h: dict(c) for h, c in sorted(by_hour.items())},
        "seen_then_used": seen_then_used,
        "carried_edges": [{"from": a, "to": b, "records": n, "evidence": carried_ev[(a, b)]}
                          for (a, b), n in carried.most_common(40)],
        "carried_edges_total": len(carried),
        "shared_places": shared_places[:40],
        "shared_places_total": len(shared_places),
        "harm_events_timed": len(harm_t),
        "spread_uses_timed": len(stu_t),
        "replay": replay,
        "_times": times,
        "_harm_times": harm_t,
        "_ids": ids,
        "_intents": intents,
    }

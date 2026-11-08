"""Analysis: tags, threads, actors, shared names, edges, coverage.

Everything returned is a count or a list of record IDs. Nothing here decides what
the traces mean; that is left to the report reader and the labeled precision check.
"""
from collections import Counter, defaultdict

from .packs import family_of


def analyze(events, pack):
    by_id = {e.id: e for e in events}
    n = len(events)

    # ---- per-event tags
    evidence, context, handles, names, n_placeholder = {}, {}, {}, {}, {}
    for e in events:
        t = e.text
        ev = [b.name for b in pack.behaviors if not b.context and b.rx.search(t)]
        cx = [b.name for b in pack.behaviors if b.context and b.rx.search(t)]
        evidence[e.id] = ev
        context[e.id] = cx
        handles[e.id] = sorted({family_of(h, pack) for h in pack.handles_rx.findall(t)}) if pack.handles_rx else []
        found = []
        for fam, rx in pack.shared_names:
            for m in rx.finditer(t):
                if (m.group(0), fam) not in found:
                    found.append((m.group(0), fam))
        names[e.id] = found

    # ---- threads: root of each record following parent links (cycle-safe)
    root = {}
    for e in events:
        cur, seen = e.id, set()
        while True:
            p = by_id[cur].parent if cur in by_id else None
            if not p or p not in by_id or p in seen:
                break
            seen.add(cur)
            cur = p
        root[e.id] = cur
    thread_size = Counter(root.values())

    # ---- actor attribution: own actor field, else own handle, else thread's
    thread_votes = defaultdict(Counter)
    for e in events:
        if e.actor:
            thread_votes[root[e.id]][e.actor] += 1
        for h in handles[e.id]:
            thread_votes[root[e.id]][h] += 0.5
    thread_actor = {t: c.most_common(1)[0][0] for t, c in thread_votes.items() if c}
    attr, how = {}, Counter()
    for e in events:
        if e.actor:
            attr[e.id], how_ = e.actor, "actor_field"
        elif handles[e.id]:
            attr[e.id], how_ = handles[e.id][0], "handle_in_text"
        elif root[e.id] in thread_actor:
            attr[e.id], how_ = thread_actor[root[e.id]], "thread"
        else:
            attr[e.id], how_ = None, "unattributed"
        how[how_] += 1

    # ---- shared names: which actors touch each name, in file order
    name_hits = defaultdict(list)
    for idx, e in enumerate(events):
        for nm, fam in names[e.id]:
            name_hits[(nm, fam)].append((idx, e.id, attr[e.id], root[e.id]))
    spread = []
    edges = Counter()
    evidence_for_edge = defaultdict(list)
    for (nm, fam), hits in name_hits.items():
        actors = sorted({a for _, _, a, _ in hits if a})
        threads = {t for _, _, _, t in hits}
        spread.append({"name": nm, "family": fam, "records": len(hits), "first_id": hits[0][1],
                       "last_id": hits[-1][1], "actors": actors, "threads": len(threads)})
        known = [(i, rid, a) for i, rid, a, _ in hits if a]
        for x in range(len(known)):
            for y in range(x + 1, len(known)):
                if known[x][2] != known[y][2]:
                    key = (known[x][2], known[y][2])
                    edges[key] += 1
                    if len(evidence_for_edge[key]) < 5:
                        evidence_for_edge[key].append(f"{nm}: {known[x][1]} -> {known[y][1]}")
    spread.sort(key=lambda r: -r["records"])

    # ---- reply edges: a child's actor answers its parent's actor
    reply_edges = Counter()
    for e in events:
        if e.parent and e.parent in by_id:
            a, b = attr.get(e.parent), attr.get(e.id)
            if a and b and a != b:
                reply_edges[(a, b)] += 1

    # ---- coverage and gaps
    times = [e.time for e in events if e.time]
    gaps = {
        "no_time": sum(1 for e in events if not e.time),
        "no_parent": sum(1 for e in events if not e.parent),
        "no_actor": how.get("unattributed", 0),
        "no_evidence_tag": sum(1 for e in events if not evidence[e.id]),
        "placeholders": sum(1 for e in events if "[" in e.text and "]" in e.text),
    }
    tag_count = Counter(t for ts in evidence.values() for t in ts)
    ctx_count = Counter(t for ts in context.values() for t in ts)
    stage_of = {b.name: b.stage for b in pack.behaviors}
    stage_recs = defaultdict(set)
    for e in events:
        for t in evidence[e.id]:
            stage_recs[stage_of[t]].add(e.id)

    return {
        "records": n,
        "kinds": dict(Counter(e.kind for e in events).most_common()),
        "time_range": [min(times).isoformat(), max(times).isoformat()] if times else None,
        "threads": len(thread_size),
        "threads_singleton": sum(1 for v in thread_size.values() if v == 1),
        "largest_threads": thread_size.most_common(10),
        "actor_attribution": dict(how),
        "actors": dict(Counter(a for a in attr.values() if a).most_common(40)),
        "evidence_tags": dict(tag_count.most_common()),
        "context_tags": dict(ctx_count.most_common()),
        "records_with_evidence": sum(1 for ts in evidence.values() if ts),
        "stages": {s: len(v) for s, v in sorted(stage_recs.items(), key=lambda kv: -len(kv[1]))},
        "shared_names": spread[:60],
        "shared_names_total": len(spread),
        "shared_across_actors": sum(1 for r in spread if len(r["actors"]) >= 2),
        "actor_edges": [[a, b, c, evidence_for_edge[(a, b)]] for (a, b), c in edges.most_common(40)],
        "reply_edges": [[a, b, c] for (a, b), c in reply_edges.most_common(40)],
        "gaps": gaps,
        "_evidence": evidence,
        "_context": context,
        "_attr": attr,
        "_root": root,
    }

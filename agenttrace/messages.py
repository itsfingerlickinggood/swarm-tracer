"""Message flow: who wrote to which channel, who read it, and how content spread.

A channel is a place agents can write to and read from: a repository, a mailbox
folder, a webhook, a command file. The pack lists channels as patterns with one capture
group (the channel's name), and a pattern that marks a record as a write. Every record
that names a channel is one operation on it: a write or a read.

A delivery is a read of a channel after a write to it by a different actor. The actor of
a record is, in order: a non-shared identity token, a handle named in the text, or the
record's own run (its thread root), so every record has an actor.

Content spread uses near-duplicate families: the same program, with ids masked, sent by
several actors. The first actor to send it is the source; later actors are adopters.
"""
import hashlib
import re
from collections import Counter, defaultdict

from .reconstruct import iso

TOKEN = re.compile(r"<[a-z][a-z_]*>|\w+|[^\w\s]")


# ------------------------------------------------------------------ actors

def _thread_identity(rec, res, pack):
    """The most used non-shared identity token in each thread, so a record without its
    own token (for example a reply or a decoded copy) is attributed to its thread."""
    if "_thread_ident" not in rec:
        shared = set(pack.raw.get("shared_identities", []))
        votes = defaultdict(Counter)
        for rid, toks in rec["_ids"].items():
            for t in toks:
                if t not in shared:
                    votes[res["_root"][rid]][t] += 1
        rec["_thread_ident"] = {root: c.most_common(1)[0][0] for root, c in votes.items()}
    return rec["_thread_ident"]


def actor_of(e, rec, res, pack):
    shared = set(pack.raw.get("shared_identities", []))
    toks = [t for t in rec["_ids"][e.id] if t not in shared]
    if e.actor and e.actor in toks:
        return e.actor, "named"          # the record's own actor field
    if toks:
        return toks[0], "token"
    if pack.handles_rx:
        m = pack.handles_rx.search(e.text)
        if m:
            from .packs import family_of
            return family_of(m.group(1), pack), "handle"
    inherited = _thread_identity(rec, res, pack).get(res["_root"][e.id])
    if inherited:
        return inherited, "token_via_thread"
    return "run:" + res["_root"][e.id], "run"


# ------------------------------------------------------------------ channels

def compile_channels(pack):
    out = []
    for c in pack.raw.get("channels", []):
        flags = re.I if "i" in c.get("flags", "") else 0
        out.append((c["name"], re.compile(c["pattern"], flags),
                    re.compile(c.get("write", pack.raw.get("write_pattern", r"(?!)")), re.I)))
    return out


NAME_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{5,}")


def _short(key):
    return re.split(r"[~/:#]", key)[-1] if key else key


def _mention_index(events):
    """Short name of every structural channel (a page's name, a thread's id) -> its keys."""
    idx = defaultdict(set)
    for e in events:
        if e.channel:
            sh = _short(e.channel)
            if sh and len(sh) >= 6:
                idx[sh].add(e.channel)
    return idx


def channel_ops(events, pack, rec, res):
    """One operation per channel a record touches.
    - pattern channels (from the pack): a write or a read, judged from the code around the mention
    - structural channels (the record's own page, thread, room...): a post, which reads what is
      there and writes to it
    - mentions: naming another structural channel in the text reads it"""
    chans = compile_channels(pack)
    times = rec["_times"]
    structural = pack.raw.get("structural_channels", True)
    mentions = pack.raw.get("mention_channels", False)
    midx = _mention_index(events) if mentions else {}
    ops = []  # (channel, op, actor, actor_kind, time, index, id)
    from .reconstruct import is_action
    for i, e in enumerate(events):
        if not is_action(e, pack):
            continue  # replies and recovered copies are not actions on a channel
        found = []
        if structural and e.channel:
            # kinds the pack lists as write-only (for example a moderator's delete) change the
            # place without reading it as a participant
            op = "write" if e.kind in pack.raw.get("write_only_kinds", []) else "post"
            found.append(("place:" + e.channel, op))
        if midx:
            own_prefix = e.channel.rsplit("~", 1)[0] if e.channel and "~" in e.channel else None
            seen = set()
            for tok in set(NAME_TOKEN.findall(e.text)):
                keys = midx.get(tok)
                if not keys:
                    continue
                if own_prefix:
                    same = [k for k in keys if k.startswith(own_prefix + "~")]
                    keys = same or keys
                for k in keys:
                    if k != e.channel and k not in seen:
                        seen.add(k)
                        found.append(("place:" + k, "read"))
        for name, rx, wrx in chans:
            ops_here = {}
            for m in rx.finditer(e.text):
                if not m.group(1):
                    continue
                # judge each mention by the code around it, not the whole record: one program
                # can read one place and write another
                window = e.text[max(0, m.start() - 160): m.end() + 260]
                op = "write" if wrx.search(window) else "read"
                key = f"{name}:{m.group(1)}"
                if ops_here.get(key) != "write":
                    ops_here[key] = op
            found += list(ops_here.items())
        if not found:
            continue
        a, ak = actor_of(e, rec, res, pack)
        for ch, op in found:
            ops.append((ch, op, a, ak, times.get(e.id), i, e.id))
    return ops


def _lines(text):
    """Distinct non-trivial lines, the unit for checking whether an edit kept earlier content."""
    return {s for s in (x.strip() for x in text.splitlines()) if len(s) >= 8}


def _in_order(text, wanted, n=3, width=160):
    """Up to n of the wanted lines, in the order they appear in text (a sample to show the reader)."""
    out = []
    for x in text.splitlines():
        s = x.strip()
        if s in wanted and s not in out:
            out.append(s)
            if len(out) == n:
                break
    return [s if len(s) <= width else s[:width - 1] + "…" for s in out]


def _how(w, r):
    if r[1] == "read":
        return "read in code" if not w[0].startswith("place:") else "named the place"
    return "posted after it"


def deliveries(ops, fam=None, texts=None):
    """Link each read to the latest earlier write on the same channel by another actor.
    Order is by time when both records are dated; otherwise the pair is 'order unknown'.

    texts: given when each post holds the whole place (a wiki edit sends the full page).
    Then a later post is evidence of reading an earlier one only if it keeps some of the lines
    the earlier post added. A post that drops all of them may have been written without
    seeing it, so it is returned as an overwrite, not a delivery."""
    by_ch = defaultdict(list)
    for o in ops:
        by_ch[o[0]].append(o)
    out, unknown_order = [], 0
    overwrites = []
    perf = []
    same_program = [0]
    rereads = [0]
    for ch, lst in by_ch.items():
        writes = [o for o in lst if o[1] in ("write", "post")]
        reads = [o for o in lst if o[1] in ("read", "post")]
        dated_w = sorted((o for o in writes if o[4] is not None), key=lambda o: o[4])
        added = {}
        if texts is not None:
            # what each post added to the place, compared with the post just before it
            posts = sorted((o for o in lst if o[1] == "post"),
                           key=lambda o: (o[4] if o[4] is not None else float("inf"), o[5]))
            before = set()
            for o in posts:
                now = _lines(texts.get(o[6], ""))
                added[o[6]] = now - before
                before = now
        delivered = 0
        over_start = len(overwrites)
        latencies = []
        got = set()  # (write, reader) already delivered: reading the same write again is one message
        reads = sorted(reads, key=lambda o: (o[4] is None, o[4] or 0, o[5]))
        for r in reads:
            if r[4] is None:
                if any(w[2] != r[2] for w in writes):
                    unknown_order += 1
                continue
            prior = [w for w in dated_w if w[4] <= r[4] and w[2] != r[2] and w[6] != r[6]]
            if fam:
                # the same program rerun under another token is one sender retrying, not a message
                same = [w for w in prior if fam.get(w[6]) and fam.get(w[6]) == fam.get(r[6])]
                if same and len(same) == len(prior):
                    same_program[0] += 1
                prior = [w for w in prior if not (fam.get(w[6]) and fam.get(w[6]) == fam.get(r[6]))]
            if prior:
                w = prior[-1]
                if (w[6], r[2]) in got:
                    rereads[0] += 1
                    continue
                got.add((w[6], r[2]))
                d = {"channel": ch, "from": w[2], "from_kind": w[3], "to": r[2], "to_kind": r[3],
                     "write_id": w[6], "read_id": r[6], "write_time": w[4], "read_time": r[4],
                     "latency_h": round((r[4] - w[4]) / 3600, 2), "how": _how(w, r)}
                if texts is not None and w[1] == "post" and r[1] == "post":
                    new = added.get(w[6], set())
                    if new:
                        kept = new & _lines(texts.get(r[6], ""))
                        if not kept:
                            d["how"] = f"dropped all {len(new)} lines it added"
                            d["lines"] = _in_order(texts.get(w[6], ""), new)
                            overwrites.append(d)
                            continue
                        d["how"] = f"kept {len(kept)} of {len(new)} lines it added"
                        d["lines"] = _in_order(texts.get(r[6], ""), kept)
                    else:
                        d["how"] = "edited after it (it added no lines to compare)"
                out.append(d)
                delivered += 1
                latencies.append((r[4] - w[4]) / 3600)
        first_w = dated_w[0][4] if dated_w else None
        first_r = min((r[4] for r in reads if r[4] is not None), default=None)
        perf.append({
            "channel": ch, "writes": len(writes), "reads": len(reads),
            "writers": len({o[2] for o in writes}), "readers": len({o[2] for o in reads}),
            "actors": len({o[2] for o in lst}),
            "first_write": iso(first_w), "first_read": iso(first_r),
            "deliveries": delivered,
            "overwrites": len(overwrites) - over_start,
            "median_latency_h": round(sorted(latencies)[len(latencies) // 2], 2) if latencies else None,
            # written, but never read by an actor other than its writers
            "never_read": len(writes) > 0 and delivered == 0, "read_without_write_seen": len(writes) == 0,
        })
    return out, perf, unknown_order, same_program[0], overwrites, rereads[0]


# ------------------------------------------------------------------ content spread

def _norm(text):
    t = re.sub(r"\[([A-Za-z][A-Za-z _\-]*)(?::[^\]]*)?\]", lambda m: " <" + re.sub(r"[^a-z]+", "_", m.group(1).lower()).strip("_") + "> ", text)
    t = re.sub(r"\b[0-9a-fA-F]{8,}\b", " <h> ", t)
    t = re.sub(r"\b\d+\b", " <n> ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def families(events, kinds=None):
    """Exact families of normalized text. Cheap and conservative: only copies whose text is
    identical after masking ids, numbers and hex count as the same content."""
    fam = {}
    for e in events:
        if kinds and e.kind not in kinds:
            continue
        n = _norm(e.text)
        if len(TOKEN.findall(n)) < 12:
            continue  # very short texts are too generic to say anything moved
        fam[e.id] = hashlib.sha1(n.encode("utf-8", "replace")).hexdigest()[:12]
    return fam


def program_prefix(events, n=60):
    """Records whose first n normalized tokens match are the same program, even if one
    copy was cut short when it was reassembled."""
    out = {}
    for e in events:
        toks = TOKEN.findall(_norm(e.text))
        if len(toks) >= 20:
            out[e.id] = hashlib.sha1(" ".join(toks[:n]).encode("utf-8", "replace")).hexdigest()[:12]
    return out


def content_spread(events, pack, rec, res, kinds=None):
    times = rec["_times"]
    fam = families(events, kinds)
    groups = defaultdict(list)
    for i, e in enumerate(events):
        f = fam.get(e.id)
        if f:
            a, ak = actor_of(e, rec, res, pack)
            groups[f].append((times.get(e.id), i, e.id, a, ak))
    out = []
    for f, lst in groups.items():
        dated = sorted((x for x in lst if x[0] is not None), key=lambda x: (x[0], x[1]))
        known = [x for x in dated if x[4] != "run"]
        actors_known = []
        for x in known:
            if x[3] not in actors_known:
                actors_known.append(x[3])
        if len(actors_known) < 2:
            continue
        firsts = {}
        for x in known:
            firsts.setdefault(x[3], x)
        src = firsts[actors_known[0]]
        adopters = [{"actor": a, "time": iso(firsts[a][0]), "record": firsts[a][2],
                     "hours_after_source": round((firsts[a][0] - src[0]) / 3600, 2)} for a in actors_known[1:]]
        out.append({"family": f, "copies": len(lst), "dated_copies": len(dated), "source": actors_known[0],
                    "source_time": iso(src[0]), "source_record": src[2], "adopters": adopters,
                    "actors": len(actors_known)})
    out.sort(key=lambda r: (-r["actors"], -r["copies"]))
    return out


# ------------------------------------------------------------------ main

def _how_group(how):
    return "kept earlier content" if how.startswith("kept ") else how

def message_flow(events, pack, rec, res):
    ops = channel_ops(events, pack, rec, res)
    texts = {e.id: e.text for e in events} if pack.raw.get("full_body_posts") else None
    dels, perf, unknown, same_prog, overwrites, rereads = deliveries(ops, program_prefix(events), texts)
    over_pairs = Counter((d["from"], d["to"]) for d in overwrites)
    actor_kinds = Counter()
    seen = set()
    for o in ops:
        if o[2] not in seen:
            seen.add(o[2])
            actor_kinds[o[3]] += 1
    pair = Counter()
    pair_ch = defaultdict(set)
    pair_first = {}
    for d in dels:
        k = (d["from"], d["to"])
        pair[k] += 1
        pair_ch[k].add(d["channel"])
        pair_first[k] = min(pair_first.get(k, d["read_time"]), d["read_time"])
    known_pairs = [k for k in pair if not k[0].startswith("run:") and not k[1].startswith("run:")]
    # token_via_thread counts as named
    lat = sorted(d["latency_h"] for d in dels)
    by_type = defaultdict(lambda: {"channels": 0, "writes": 0, "reads": 0, "deliveries": 0, "never_read": 0})
    for p in perf:
        t = p["channel"].split(":", 1)[0]
        b = by_type[t]
        b["channels"] += 1
        b["writes"] += p["writes"]
        b["reads"] += p["reads"]
        b["deliveries"] += p["deliveries"]
        b["never_read"] += 1 if p["never_read"] else 0
    action_kinds = pack.raw.get("action_kinds")
    spread = content_spread(events, pack, rec, res, set(action_kinds) if action_kinds else None)
    # channels the pack marks as coarse (for example a redaction that keeps only the owner)
    # may merge several places, so a write and a read there may not be the same message
    coarse = [re.compile(p) for p in pack.raw.get("coarse_channels", [])]
    is_coarse = lambda ch: any(r.search(ch) for r in coarse)
    named = [d for d in dels if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    first_known_delivery = min((d for d in named if not is_coarse(d["channel"])), key=lambda d: d["read_time"], default=None)
    first_any_named = min(named, key=lambda d: d["read_time"], default=None)
    harm_t = rec.get("_harm_times", [])
    named_share = None
    if first_known_delivery and harm_t:
        T = first_known_delivery["read_time"]
        named_share = round(sum(1 for x in harm_t if x > T) / len(harm_t), 3)
    return {
        "harm_share_after_first_named_delivery": named_share,
        "operations": len(ops),
        "records_on_channels": len({o[6] for o in ops}),
        "channels": len(perf),
        "channel_types": {k: dict(v) for k, v in by_type.items()},
        "actors_on_channels": dict(actor_kinds),
        "deliveries": len(dels),
        "deliveries_order_unknown": unknown,
        "reads_dropped_as_same_program": same_prog,
        "deliveries_between_named_actors": sum(pair[k] for k in known_pairs),
        "actor_pairs": len(pair),
        "named_actor_pairs": len(known_pairs),
        "latency_hours": {"median": lat[len(lat) // 2] if lat else None,
                          "p90": lat[int(len(lat) * 0.9)] if lat else None},
        "first_named_delivery": ({k: (iso(v) if k.endswith("_time") else v) for k, v in first_known_delivery.items()}
                                 if first_known_delivery else None),
        "first_named_delivery_any_channel": ({k: (iso(v) if k.endswith("_time") else v) for k, v in first_any_named.items()}
                                             if first_any_named else None),
        "coarse_channel_deliveries": sum(1 for d in dels if is_coarse(d["channel"])),
        "top_pairs": [{"from": a, "to": b, "deliveries": n, "channels": len(pair_ch[(a, b)]),
                       "first": iso(pair_first[(a, b)])}
                      for (a, b), n in sorted(((k, pair[k]) for k in known_pairs),
                                              key=lambda kv: (-kv[1], pair_first[kv[0]]))[:60]],
        "top_channels": sorted(perf, key=lambda p: (-p["deliveries"], -p["actors"]))[:40],
        "content_spread": spread[:40],
        "content_families_moving": len(spread),
        "deliveries_by_how": dict(Counter(_how_group(d["how"]) for d in dels)),
        "overwrites": len(overwrites),
        "repeat_reads": rereads,
        "top_overwrite_pairs": [{"from": a, "to": b, "overwrites": n} for (a, b), n in over_pairs.most_common(15)],
        "_deliveries": dels,
        "_overwrites": overwrites,
    }

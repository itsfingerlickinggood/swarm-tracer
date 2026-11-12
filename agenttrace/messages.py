"""Message flow: who wrote to which channel, who read it, and how content spread.

A channel is a place agents can write to and read from: a repository, a mailbox
folder, a webhook, a command file. The pack lists channels as patterns with one capture
group (the channel's name), and a pattern that marks a record as a write. Every record
that names a channel is one operation on it: a write or a read.

A delivery is a read of a channel after a write to it by a different actor. The actor of
a record is, in order: a non-shared identity token, a handle named in the text, or the
record's own run (its thread root), so every record has an actor.

A direct message is a record the trace itself addresses to another actor (a recipient field, a
handoff span, a delegation): the strongest evidence, kept as a delivery with how = "direct
message (logged)" on the recipient's inbox place (inbox:<recipient>).

Content spread uses near-duplicate families: the same program, with ids masked, sent by
several actors. The first actor to send it is the source; later actors are adopters.
"""
import hashlib
import re
from collections import Counter, defaultdict

from .reconstruct import iso, in_comment  # noqa: F401 (in_comment is part of this module's API)

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


# ------------------------------------------------------------------ direct messages

DIRECT_HOW = "direct message (logged)"
DIRECT_PREFIX = "inbox"


def direct_messages(events, pack, rec, res):
    """Records addressed to another actor (Event.to): sender -> recipient, with the recipient's
    reply when the trace has one (a child record by the recipient, else the recipient's next record
    in the same thread). Cached in rec; undated ones are kept with write_time None."""
    if "_direct" in rec:
        return rec["_direct"]
    addressed = [(i, e) for i, e in enumerate(events) if getattr(e, "to", None)]
    out = []
    if addressed:
        times = rec["_times"]
        children = defaultdict(list)
        thread = defaultdict(list)
        pos = {}
        for i, e in enumerate(events):
            if e.parent:
                children[e.parent].append(i)
            key = e.channel or ""
            pos[e.id] = len(thread[key])
            thread[key].append(i)
        memo = {}

        def who(j):
            if j not in memo:
                memo[j] = actor_of(events[j], rec, res, pack)[0]
            return memo[j]
        for i, e in addressed:
            a, ak = actor_of(e, rec, res, pack)
            to = str(e.to)
            if to == a:
                continue
            t = times.get(e.id)
            ok = lambda j: who(j) == to and j != i and (t is None or times.get(events[j].id) is None or times[events[j].id] >= t)
            reply = next((j for j in children.get(e.id, []) if ok(j)), None)
            if reply is None:
                lst = thread[e.channel or ""]
                k = pos[e.id]
                reply = next((j for j in lst[k + 1:k + 60] if ok(j)), None)
            rid = events[reply].id if reply is not None else e.id
            rt = times.get(rid) if reply is not None else t
            if rt is None:
                rt = t
            out.append({"channel": f"{DIRECT_PREFIX}:{to}", "from": a, "from_kind": ak, "to": to, "to_kind": "named",
                        "write_id": e.id, "read_id": rid, "write_time": t, "read_time": rt,
                        "latency_h": round((rt - t) / 3600, 2) if t is not None and rt is not None else 0,
                        "how": DIRECT_HOW, "_i": i, "_ri": reply if reply is not None else i})
    rec["_direct"] = out
    return out


def _direct_perf(direct):
    by = defaultdict(list)
    for d in direct:
        by[d["channel"]].append(d)
    out = []
    for ch, lst in by.items():
        dated = [d for d in lst if d["write_time"] is not None]
        lat = sorted(d["latency_h"] for d in dated)
        out.append({"channel": ch, "writes": len(lst), "reads": len(lst),
                    "writers": len({d["from"] for d in lst}), "readers": len({d["to"] for d in lst}),
                    "actors": len({d["from"] for d in lst} | {d["to"] for d in lst}),
                    "first_write": iso(min((d["write_time"] for d in dated), default=None)),
                    "first_read": iso(min((d["read_time"] for d in dated), default=None)),
                    "deliveries": len(dated), "overwrites": 0,
                    "median_latency_h": lat[len(lat) // 2] if lat else None,
                    "never_read": False, "read_without_write_seen": False})
    return out


# ------------------------------------------------------------------ channels

def compile_channels(pack):
    """(name, place pattern, write verbs, read verbs) per channel. The read verbs (the channel's "read",
    else the pack's "read_pattern") name requests that only fetch, such as an LFS batch with
    operation 'download' or a HEAD, so a POST that merely downloads is not taken for a write."""
    out = []
    for c in pack.raw.get("channels", []):
        flags = re.I if "i" in c.get("flags", "") else 0
        out.append((c["name"], re.compile(c["pattern"], flags),
                    re.compile(c.get("write", pack.raw.get("write_pattern", r"(?!)")), re.I),
                    re.compile(c.get("read", pack.raw.get("read_pattern", r"(?!)")), re.I)))
    return out


REQUEST_START = re.compile(r"fetch\s*\(|\.open\s*\(|new\s+XMLHttpRequest|requests\.(?:get|post|put|patch|delete|head)\s*\(|"
                           r"\bcurl\b|urlopen\s*\(|http\.request|axios\.|\$\.ajax|navigator\.sendBeacon|createElement\(['\"]form", re.I)


HTTP_WRITE = re.compile(r"['\"](POST|PUT|PATCH|DELETE)['\"]")
ASSIGNED = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*(?:[\w$.]+\s*\+\s*)?['\"`][^'\"`;]*$")


def _call_end(text, open_pos, cap=600):
    """Index just past the parenthesis that closes the call opened at or after open_pos (capped)."""
    i = text.find("(", open_pos)
    if i < 0:
        return min(len(text), open_pos + cap)
    depth, end = 0, min(len(text), i + cap)
    nx = REQUEST_START.search(text, i + 1, end)      # redaction can swallow the closing parenthesis:
    if nx:                                           # never run on into the next request
        end = nx.start()
    for k in range(i, end):
        c = text[k]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    return end


def _opts_write(text, seg, wrx, before):
    """fetch(u, o): the options sit in a variable. True when that variable's object literal has a write verb."""
    m = re.search(r",\s*([A-Za-z_$][\w$]*)\s*\)\s*$", seg)
    if not m or m.group(1) in ("false", "true", "null", "undefined", "None", "True", "False") or seg.lstrip().startswith(".open"):
        return False
    d = None
    for d in re.finditer(r"(?<![\w$.])" + re.escape(m.group(1)) + r"\s*=\s*\{", text[:before]):
        pass
    if d:
        return bool(wrx.search(text[d.start():d.start() + 300]))
    # the options are a parameter of a wrapper function (function f(p, o) { fetch(b + p, o) }):
    # the wrapper's callers carry the verb, so look at the code that follows the wrapper
    o = re.escape(m.group(1))
    param = re.search(r"function\s*[\w$]*\s*\([^)]*\b" + o + r"\b[^)]*\)\s*\{|\([^()]*\b" + o + r"\b[^()]*\)\s*=>|\b" + o + r"\s*=>",
                      text[max(0, before - 200):before])
    return bool(param and wrx.search(text[before:before + 500]))


def judge_span(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    """(op, lo, hi): write or read for the place mention at text[start:end], and the span of code judged.

    1. The mention sits inside a request call (fetch('…place…', {...})): the verb nearest to it decides,
       looking only at that call: never past another place mention (bounds) nor into another request.
       So a program that fetches a dataset and then POSTs what it read elsewhere reads the dataset.
    2. The mention is assigned to a variable (u='…place…'; … fetch(u, {method:'POST'})): the calls that
       use the variable decide. Any call with a write verb makes it a write; otherwise it is a read.
       Without this a commit whose URL sits in a variable looks like a read, and two actors committing
       to one dataset look like a message."""
    lo, hi = max(0, start - before), min(len(text), end + after)
    if bounds:
        lo, hi = max(lo, bounds[0]), min(hi, bounds[1])
    last = None
    for m in REQUEST_START.finditer(text, lo, start):
        last = m.start()
    direct = last is not None and not re.search(r"[;\n]", text[last:start])
    # a Git LFS batch call is a POST either way: its "operation" says whether it uploads or downloads
    nreq = REQUEST_START.search(text, end, min(len(text), end + 400))
    region_hi = _call_end(text, nreq.start()) if nreq else min(len(text), end + 300)
    region_lo = max(0, start - 300) if "info/lfs" in text[end:end + 40] else (last if direct else start)
    lfs = re.search(r"operation['\"]?\s*:\s*['\"](download|upload)['\"]", text[region_lo:region_hi])
    if lfs:
        return ("read" if lfs.group(1) == "download" else "write"), start, region_hi
    if not direct:
        am = ASSIGNED.search(text, max(0, start - 200), start)
        if am:
            # every place the variable is passed as an argument: fetch(u, …), x.open('POST', U), Q('GET', S), req(url, …)
            use = re.compile(r"[(,+]\s*" + re.escape(am.group(1)) + r"\s*(?=[,)+])")
            verdict, span = None, None
            limit = min(len(text), end + 8000)
            for um in use.finditer(text, end, limit):
                near = text[max(0, um.start() - 80):um.end() + 120]
                rs = None
                for r0 in REQUEST_START.finditer(text, max(0, um.start() - 60), um.end()):
                    rs = r0
                if rs is not None:                     # passed straight to a request call: judge that call
                    seg_hi = _call_end(text, rs.start())
                    seg = text[rs.start():seg_hi]
                    if wrx.search(seg) or _opts_write(text, seg, wrx, rs.start()):
                        return "write", rs.start(), seg_hi
                    if verdict is None:
                        verdict, span = "read", (rs.start(), seg_hi)
                elif HTTP_WRITE.search(near):          # passed to a helper with the verb as an argument
                    return "write", max(0, um.start() - 80), um.end() + 120
                elif verdict is None:
                    verdict, span = "read", (max(0, um.start() - 80), um.end() + 120)
            if verdict:
                return verdict, span[0], span[1]
            return "mention", start, end      # assigned and never passed to a call: named, not opened
    if not direct:
        # the place is a literal argument of a helper call with the verb beside it: req('…place…', tok, 'POST', data)
        tail = re.match(r"[^();{}]{0,70}['\"](POST|PUT|PATCH|DELETE)['\"]", text[end:end + 90])
        if tail:
            return "write", start, end + tail.end()
    if re.match(r"[^)]{0,12}\{\s*metho(?!d)", text[end:end + 30]):
        return "mention", start, end      # the call is cut off before its verb: unknown, so not counted
    if last is not None:
        lo = last
    nxt = REQUEST_START.search(text, end, hi)
    if nxt:
        hi = nxt.start()
    window = text[lo:hi]
    pos = start - lo

    def nearest(rx):
        best = None
        for m in rx.finditer(window):
            d = 0 if m.start() <= pos <= m.end() else min(abs(m.start() - pos), abs(m.end() - pos))
            if best is None or d < best:
                best = d
        return best
    w, r = nearest(wrx), nearest(rrx)
    if w is None or (r is not None and r < w):
        return "read", lo, hi
    return "write", lo, hi


def judge_op(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    return judge_span(text, start, end, wrx, rrx, bounds, before, after)[0]


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
    shared_ids = set(pack.raw.get("shared_identities", []))
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
        seg_of = {}
        # every place mention in the record, so each one is judged only by the code between its neighbours
        spans = sorted({(m.start(), m.end()) for _n, rx, _w, _r in chans for m in rx.finditer(e.text) if m.group(1)})
        for name, rx, wrx, rrx in chans:
            ops_here = {}
            for m in rx.finditer(e.text):
                if not m.group(1) or in_comment(e.text, m.start()):
                    continue
                # judge each mention by the code around it, not the whole record: one program
                # can read one place and write another
                k = spans.index((m.start(), m.end()))
                bounds = (spans[k - 1][1] if k else 0, spans[k + 1][0] if k + 1 < len(spans) else len(e.text))
                op, slo, shi = judge_span(e.text, m.start(), m.end(), wrx, rrx, bounds)
                key = f"{name}:{m.group(1)}"
                if op == "mention":
                    continue
                if ops_here.get(key) != "write":
                    ops_here[key] = op
                    seg_of[key] = e.text[slo:shi]
            found += list(ops_here.items())
        if not found:
            continue
        a, ak = actor_of(e, rec, res, pack)
        toks = [t for t in rec["_ids"][e.id] if t not in shared_ids] if ak == "token" else []
        for ch, op in found:
            a2 = a
            if len(toks) > 1 and ch in seg_of:
                # a record that holds several tokens: the one named in the judged call is the actor
                here = [t for t in toks if t in seg_of[ch]]
                if len(here) == 1:
                    a2 = here[0]
            ops.append((ch, op, a2, ak, times.get(e.id), i, e.id))
    # logged direct messages: the sender writes to the recipient's inbox, the recipient's reply reads it
    for d in direct_messages(events, pack, rec, res):
        ops.append((d["channel"], "write", d["from"], d["from_kind"], d["write_time"], d["_i"], d["write_id"]))
        if d["read_id"] != d["write_id"]:
            ops.append((d["channel"], "read", d["to"], d["to_kind"], d["read_time"], d["_ri"], d["read_id"]))
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


def content_spread(events, pack, rec, res, kinds=None, written=None):
    """Programs (normalized code) run under more than one named actor. Each entry says whether the program
    is routine: it writes to no place the pack lists, reads no place that some actor in the trace wrote to
    (written: the set of such places), and does nothing the pack counts as harmful. The evaluation's own
    submit call, or two agents fetching the same public file, are routine. Routine reuse is listed but is not
    a sign of shared control."""
    times = rec["_times"]
    chans = compile_channels(pack)
    intents = rec.get("_intents", {})
    harm = set(getattr(pack, "harm", None) or [])
    by_id = {e.id: e for e in events}

    def touches(rid):
        e = by_id.get(rid)
        if e is None:
            return False
        if intents.get(rid) in harm:
            return True
        for name, rx, wrx, rrx in chans:
            for m in rx.finditer(e.text):
                if not m.group(1) or in_comment(e.text, m.start()):
                    continue
                if judge_op(e.text, m.start(), m.end(), wrx, rrx) == "write":
                    return True
                if written is None or f"{name}:{m.group(1)}" in written:
                    return True
        return False
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
                    "actors": len(actors_known),
                    "routine": not any(touches(x[2]) for x in lst[:8])})
    out.sort(key=lambda r: (-r["actors"], -r["copies"]))
    return out


# ------------------------------------------------------------------ main

def _how_group(how):
    return "kept earlier content" if how.startswith("kept ") else how

def message_flow(events, pack, rec, res):
    ops = channel_ops(events, pack, rec, res)
    texts = {e.id: e.text for e in events} if pack.raw.get("full_body_posts") else None
    inferred = [o for o in ops if not o[0].startswith(DIRECT_PREFIX + ":")]
    dels, perf, unknown, same_prog, overwrites, rereads = deliveries(inferred, program_prefix(events), texts)
    # logged direct messages are deliveries as they stand: no inference needed
    direct = direct_messages(events, pack, rec, res)
    dels = dels + [{k: v for k, v in d.items() if not k.startswith("_")} for d in direct if d["write_time"] is not None]
    perf = perf + _direct_perf(direct)
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
    written = {o[0] for o in ops if o[1] in ("write", "post")}
    spread = content_spread(events, pack, rec, res, set(action_kinds) if action_kinds else None, written)
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
        "direct_messages": sum(1 for d in direct if d["write_time"] is not None),
        "direct_messages_undated": sum(1 for d in direct if d["write_time"] is None),
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
        "_channels": sorted(perf, key=lambda p: (-p["deliveries"], -p["actors"])),
        "_content_spread": spread,
        "content_families_moving": len(spread),
        "deliveries_by_how": dict(Counter(_how_group(d["how"]) for d in dels)),
        "overwrites": len(overwrites),
        "repeat_reads": rereads,
        "top_overwrite_pairs": [{"from": a, "to": b, "overwrites": n} for (a, b), n in over_pairs.most_common(15)],
        "_deliveries": dels,
        "_overwrites": overwrites,
    }

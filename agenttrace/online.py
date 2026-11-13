"""Online (streaming) mode with bounded memory.

The replay (agenttrace/insight.py simulate) reads the whole dataset before it says when a sign "would have"
fired, so it can use hindsight: the global fit of times, the thread an actor belongs to, every place any actor ever
wrote. OnlineMonitor reads records one at a time, in order, and emits each sign the moment the records seen so far
make it fire. Each event says how many records had been seen (record_index), so "early" means records seen, not
hindsight.

    python3 -m agenttrace.online run TRACE [--pack PACK] [--compare] [--limit N]
    GET /api/x/online_replay    streams the loaded dataset through the monitor (starts in the background for a
                                large dataset; poll until "running" is false)

The signs are the replay's signs under the same keys, using the same functions where there is one
(reconstruct.identities_of / info_of / places_of / intent_of, messages.channel_ops, judge_op, families,
evaluate's rate rule). A sign fires once; when it has, the state only it needed is dropped.

Memory is bounded by these caps (CAPS; entries, oldest inserted evicted first; `memory()` reports the counts and
how many were evicted):
    ids_roots       id -> thread root                     500,000
    thread_idents   thread -> token votes                 100,000
    tokens          first use of a token / items seen     300,000 each
    places          shared place -> first two identities  100,000
    channels        channel -> its last writes            100,000 channels, 16 writes each
    got             (write, reader) pairs already counted 500,000
    actors          nodes of the message-group graph      200,000
    pairs           directed actor pairs (two-way check)  500,000
    families        program families (hashed text)        100,000, up to 3 actors and 8 copies each
    written         places written so far                 200,000
Windows: the volume rule keeps three numbers (count, mean, variance of the closed hours), not the hours.

Where a sign needs global knowledge, the approximation (all measured against the replay in docs/early-warning.md):
- time: the record's own time field; else a unix time written in its text, if the pack allows it and it lies in the
  window (the pack's, else the median of the first 100 found plus or minus 15 days), unless it is further from the
  last 21 such times than twice their own spread, at least 30 minutes (then their median stands in); else, for a kind that carries timestamps,
  the last accepted time; else its parent's time. The replay fits all of these together afterwards (isotonic fit per block),
  so online times lag by the gap between timestamp-bearing records.
- actor: a non-shared token, a handle, the most used token in the thread SO FAR, else "run:<thread>". The replay
  uses the thread's most used token over the whole thread.
- "token carried": needs the token's later first use, so it fires at that first use (event.evidence_time is when
  the carrying happened, the replay's time).
- program reuse: "routine" means no write and no read of a place written so far; the replay uses every place ever written.
- logged direct messages (record.to) are paired with the recipient's next record in the same channel within 60 records,
  as the replay does, but the thread/children shortcut is not used.
- wiki-style whole-page edits (pack full_body_posts) are not tested for kept lines, so an overwrite may count as a message.
"""
import argparse
import hashlib
import json
import math
import os
import re
import resource
import sys
import threading
import time
from collections import Counter, defaultdict, deque

from . import insight, messages, model, packs, reconstruct
from .reconstruct import iso

HOUR = 3600.0
CAPS = {"ids_roots": 500_000, "thread_idents": 100_000, "tokens": 300_000, "places": 100_000, "channels": 100_000,
        "writes_per_channel": 16, "got": 500_000, "actors": 200_000, "pairs": 500_000, "families": 100_000,
        "written": 200_000}
GROUP_THRESHOLDS = (3, 5, 10, 20)
RATE_K = (2.0, 3.0, 4.0, 5.0)
RATE_MIN_HISTORY = 12


class Bounded(dict):
    """A dict that drops its oldest-inserted entry when it would exceed cap (counts the drops)."""
    def __init__(self, cap):
        super().__init__()
        self.cap = cap
        self.evicted = 0

    def __setitem__(self, k, v):
        if k not in self and len(self) >= self.cap:
            del self[next(iter(self))]
            self.evicted += 1
        super().__setitem__(k, v)

    def setdefault(self, k, v=None):
        if k not in self:
            self[k] = v
        return self[k]


def as_event(rec):
    """An Event from an Event or a plain dict (the shape the readers produce: id, text, kind, parent, actor, time...)."""
    if isinstance(rec, model.Event):
        return rec
    t = rec.get("time")
    if isinstance(t, str):
        t = model.parse_time(t)
    return model.Event(id=str(rec["id"]), text=str(rec.get("text") or ""), kind=str(rec.get("kind") or ""),
                       parent=rec.get("parent"), actor=rec.get("actor"), time=t, channel=rec.get("channel"),
                       to=rec.get("to"))


class OnlineMonitor:
    def __init__(self, pack, caps=None):
        self.pack = pack
        self.caps = dict(CAPS, **(caps or {}))
        c = self.caps
        self.n = 0
        self.events_out = []
        self._new = []
        self.fired = set()
        self.last_t = None
        self.t_first = None
        self.shared = set(pack.raw.get("shared_identities", []))
        self.harm_names = sorted(pack.harm)
        self.harm_set = set(pack.harm)
        self.harm_behaviors = [b for b in pack.behaviors if not b.context and b.name in self.harm_set]
        self.action_kinds = set(pack.raw.get("action_kinds") or []) or None
        self.coarse = [re.compile(p) for p in pack.raw.get("coarse_channels", [])]
        self.chans = messages.compile_channels(pack)
        tcfg = pack.time or {}
        self.epoch = bool(tcfg.get("embedded_epoch"))
        w = tcfg.get("window", "auto")
        self.window = None if w == "auto" else (reconstruct._parse_day(w[0]), reconstruct._parse_day(w[1]))
        self.found = []
        self.recent = deque(maxlen=21)
        self.good = None
        self.timed_kinds = set()
        # state
        self.root = Bounded(c["ids_roots"])
        self.times = Bounded(c["ids_roots"])
        self.chan_n = Bounded(c["channels"])
        self.votes = Bounded(c["thread_idents"])
        self.thread_ident = {}
        self.first_use = Bounded(c["tokens"])
        self.seen_data = Bounded(c["tokens"])       # item -> (t, rid)
        self.seen_carried = Bounded(c["tokens"])    # item -> (t, rid, carrier)
        self.places = Bounded(c["places"])
        self.chan = Bounded(c["channels"])
        self.got = Bounded(c["got"])
        self.parent = Bounded(c["actors"])
        self.size = {}
        self.pairs = Bounded(c["pairs"])
        self.groups_left = list(GROUP_THRESHOLDS)
        self.fams = Bounded(c["families"])
        self.written = Bounded(c["written"])
        self.direct = {}
        # volume rule
        self.cur = {"all": None, "harm": None}
        self.cnt = {"all": 0, "harm": 0}
        self.hist = {"all": [0, 0.0, 0.0], "harm": [0, 0.0, 0.0]}   # n, mean, M2
        self.h_first = None
        self.rate_done = {(w, k): None for w in ("all", "harm") for k in RATE_K}
        self.last_actor = None

    # ------------------------------------------------------------------ output
    def _emit(self, key, name, family, kind, t, rid, actors, why, evidence_t=None):
        if key in self.fired:
            return
        self.fired.add(key)
        self.events_out.append({"key": key, "name": name, "family": family, "kind": kind, "t": t, "time": iso(t),
                                "evidence_time": iso(evidence_t if evidence_t is not None else t),
                                "evidence_t": evidence_t if evidence_t is not None else t,
                                "record_index": self.n, "record": rid, "actors": [a for a in actors if a], "why": why})
        self._new.append(self.events_out[-1])

    # ------------------------------------------------------------------ time
    def _recent_median(self):
        r = self.recent
        if len(r) < 5:
            return None
        v = sorted(r)
        return v[len(v) // 2]

    def _near(self, v):
        """True when v is no further from the recent timestamps than twice their own spread (at least 30 minutes)."""
        r = self.recent
        lo, hi = min(r), max(r)
        slack = max(1800.0, 2 * (hi - lo))
        return lo - slack <= v <= hi + slack

    def _time(self, e):
        if e.time:
            t = e.time.timestamp()
            self.recent.append(t)
        else:
            t = None
            if self.epoch:
                found = [int(m) for m in reconstruct.EPOCH.findall(e.text)]
                if found:
                    if self.window is None and len(self.found) < 100:
                        self.found.extend(found[:2])
                    lo, hi = self.window or self._auto_window()
                    ok = [v for v in found if lo <= v <= hi]
                    if ok:
                        self.timed_kinds.add(e.kind)
                        v = ok[0]
                        med = self._recent_median()
                        # a timestamp far from the recent ones is an outlier (a time written in the text that is
                        # not the record's own): the median of the last timestamps stands in for it
                        if med is None or self._near(v):
                            t = self.good = v
                        else:
                            t = med
                        self.recent.append(v)
            if t is None:
                # a kind that carries timestamps is placed by its neighbours (the replay fits it by position);
                # any other kind takes its parent's time, as the replay does for what it cannot fit
                t = None if e.kind in self.timed_kinds else (self.times.get(e.parent) if e.parent else None)
                if t is None:
                    t = self.good or self._recent_median() or self.last_t
        if t is not None:
            self.last_t = t
            self.times[e.id] = t
        return t

    def _auto_window(self):
        if len(self.found) < 5:
            return (0, 10 ** 11)
        med = sorted(self.found)[len(self.found) // 2]
        return (med - 15 * 86400, med + 15 * 86400)

    # ------------------------------------------------------------------ one record
    def feed(self, rec):
        """Process one record; returns the sign events it fired (also kept in self.events_out)."""
        e = as_event(rec)
        self.n += 1
        self._new = []
        pack = self.pack
        t = self._time(e)
        root = self.root.get(e.parent, e.parent) if e.parent and e.parent in self.root else e.id
        self.root[e.id] = root
        is_act = reconstruct.is_action(e, pack)
        ids = reconstruct.identities_of(e, pack)
        intent = reconstruct.intent_of(e, pack)
        text = e.text
        tags = [b.name for b in self.harm_behaviors if b.rx.search(text)] if is_act else []
        harmful = bool(is_act and (intent in self.harm_set or tags))
        if t is not None:
            # (1) first harmful action of each kind
            if is_act:
                for name in self.harm_names:
                    key = "replay:first: " + name
                    if key not in self.fired and (intent == name or name in tags):
                        nm, fam = insight.signal_name("first: " + name)
                        self._emit(key, nm, "single", "harm", t, e.id, [], "the first harmful action of this kind")
            # (2) volume
            if is_act and intent:
                self._rate("all", t)
            if harmful:
                self._rate("harm", t)
            # (3) tokens: seen as data then used; carried
            self._tokens(e, t, ids)
            # (4) a place used by two identities
            if "replay:coordination: two identities use one place" not in self.fired:
                self._places(e, t, ids)
        # (5) messages, groups, two-way
        self._messages(e, t, ids, root, is_act)
        # (6) programs
        if t is not None and is_act:
            self._programs(e, t, ids, intent)
        return self._new

    # ------------------------------------------------------------------ volume
    def _rate(self, which, t):
        h = math.floor(t / HOUR)
        cur = self.cur[which]
        if cur is None:
            self.cur[which], self.cnt[which], cur = h, 0, h
        if h > cur:
            self._close_hours(which, cur, h)
            self.cur[which], self.cnt[which] = h, 0
        self.cnt[which] += 1

    def _close_hours(self, which, cur, upto, final=False):
        """Close hour cur (with its count), then the empty hours up to upto, judging each as the replay does."""
        for hr in range(cur, upto):
            c = self.cnt[which] if hr == cur else 0
            n, mu, m2 = self.hist[which]
            if n >= RATE_MIN_HISTORY:
                sd = math.sqrt(m2 / n)
                for k in RATE_K:
                    if not self.rate_done[(which, k)] and c > mu + k * max(sd, 1.0):
                        tt = (hr + 1) * HOUR
                        self.rate_done[(which, k)] = tt
                        if k == 3.0:
                            self._emit("rate_all" if which == "all" else "rate_harm",
                                       "Volume alarm on all actions" if which == "all" else "Volume alarm on harmful actions",
                                       "baseline", "baseline", tt, None, [],
                                       f"{c:,} actions in the hour from {iso(hr * HOUR)}, above the alarm line of {mu + k * max(sd, 1.0):,.0f}"
                                       " (mean + 3 standard deviations of every earlier hour); known at the end of that hour",
                                       )
            n += 1
            d = c - mu
            mu += d / n
            m2 += d * (c - mu)
            self.hist[which] = [n, mu, m2]

    def rate_times(self):
        """When the volume alarm fired at each sigma (2 to 5), for the cost curve: {(which, k): hour index}."""
        return {k: v for k, v in self.rate_done.items() if v}

    # ------------------------------------------------------------------ tokens
    def _tokens(self, e, t, ids):
        done_s = "replay:spread: first use of an item seen earlier" in self.fired
        done_c = "replay:coordination: one identity carries another's token" in self.fired
        if done_s and done_c:
            return
        for tok in ids:
            if tok not in self.first_use:
                self.first_use[tok] = t
                sd = self.seen_data.get(tok)
                if sd and sd[0] < t and not done_s:
                    self._emit("replay:spread: first use of an item seen earlier", "Token seen as data, then used", "single", "token", t, e.id, [tok],
                               f"{tok} appeared inside a record as data before any record used it to authenticate", evidence_t=t)
                sc = self.seen_carried.get(tok)
                if sc and sc[0] <= t and not done_c:
                    self._emit("replay:coordination: one identity carries another's token", "One identity carries another's token", "joint", "carried",
                               t, sc[1], [sc[2], tok], f"{sc[2]} holds {tok}'s token in {sc[1]}, before that token's own first use", evidence_t=sc[0])
        for fam, item in reconstruct.info_of(e, self.pack):
            if item in ids:
                continue
            tu = self.first_use.get(item)
            if tu is not None:
                if t <= tu and not done_c:
                    for a in ids:
                        if a != item and a not in self.shared:
                            self._emit("replay:coordination: one identity carries another's token", "One identity carries another's token", "joint", "carried",
                                       t, e.id, [a, item], f"{a} holds {item}'s token in {e.id}, before that token's own first use", evidence_t=t)
                            break
                continue
            if item not in self.seen_data:
                self.seen_data[item] = (t, e.id)
            if ids and item not in self.seen_carried:
                for a in ids:
                    if a != item and a not in self.shared:
                        self.seen_carried[item] = (t, e.id, a)
                        break

    # ------------------------------------------------------------------ places
    def _places(self, e, t, ids):
        ps = reconstruct.places_of(e, self.pack)
        if not ps or not ids:
            return
        for p in ps:
            cur = self.places.get(p)
            if cur is False:
                continue
            if cur is None:
                cur = []
                self.places[p] = cur
            for a in ids:
                if a in self.shared or any(x[0] == a for x in cur):
                    continue
                cur.append((a, t, e.id))
            if len(cur) >= 2:
                first, second = cur[0], cur[1]
                self.places[p] = False
                if first[2] != second[2]:
                    self._emit("replay:coordination: two identities use one place", "Two identities share place " + (p if len(p) < 24 else "one place"),
                               "joint", "place", second[1], second[2], [first[0], second[0]],
                               f"two identities used the same named place {p} in different records")
                    self.places.clear()
                    return

    # ------------------------------------------------------------------ messages
    def _actor(self, e, ids, root, t):
        toks = [x for x in ids if x not in self.shared]
        for x in toks:
            v = self.votes.get(root)
            if v is None:
                v = Counter()
                self.votes[root] = v
            v[x] += 1
            cur = self.thread_ident.get(root)
            if cur is None or v[x] > v[cur]:
                self.thread_ident[root] = x
        rec = {"_times": {e.id: t}, "_ids": {e.id: ids}, "_thread_ident": self.thread_ident}
        res = {"_root": {e.id: root}}
        return rec, res

    def _messages(self, e, t, ids, root, is_act):
        if all(k in self.fired for k in ("message", "two_way", "group20", "program2", "program3")):
            return
        rec, res = self._actor(e, ids, root, t)
        if len(self.thread_ident) > self.caps["thread_idents"]:
            self.thread_ident.pop(next(iter(self.thread_ident)))
        to = getattr(e, "to", None)
        if not is_act and not to:
            return
        ops = messages.channel_ops([e], self.pack, rec, res)
        # a logged direct message is a write to the recipient's inbox; the recipient's next record in the same
        # channel (within 60 records) is the read
        if to or self.direct:
            ch = e.channel or ""
            n = self.chan_n.get(ch, 0) + 1
            self.chan_n[ch] = n
            who = messages.actor_of(e, rec, res, self.pack)
            d = self.direct.get((ch, who[0]))
            if d:
                del self.direct[(ch, who[0])]
                if d[1] != e.id and n - d[3] <= 60 and t is not None:
                    ops.append((f"inbox:{who[0]}", "read", who[0], "named", t, 0, e.id))
            if to and str(to) != who[0]:
                self.direct[(ch, str(to))] = [who, e.id, t, n]
                if len(self.direct) > self.caps["actors"]:
                    self.direct.pop(next(iter(self.direct)))
        if not ops:
            return
        sig = None
        for ch, op, actor, akind, ot, _i, rid in ops:
            if ot is None:
                continue
            if sig is None:
                sig = self._sig(e.text)
            if op in ("read", "post"):
                self._read(ch, actor, akind, ot, rid, sig)
            if op in ("write", "post"):
                lst = self.chan.get(ch)
                if lst is None:
                    lst = []
                    self.chan[ch] = lst
                lst.append((ot, actor, akind, rid, sig[1]))
                if len(lst) > self.caps["writes_per_channel"]:
                    del lst[0]
                self.written[ch] = True

    @staticmethod
    def _sig(text):
        n = messages._norm(text)
        toks = messages.TOKEN.findall(n)
        fam = hashlib.sha1(n.encode("utf-8", "replace")).hexdigest()[:12] if len(toks) >= 12 else None
        prefix = hashlib.sha1(" ".join(toks[:60]).encode("utf-8", "replace")).hexdigest()[:12] if len(toks) >= 20 else None
        return fam, prefix

    def _read(self, ch, actor, akind, t, rid, sig):
        lst = self.chan.get(ch)
        if not lst:
            return
        prefix = sig[1]
        prior = [w for w in lst if w[0] <= t and w[1] != actor and w[3] != rid]
        prior = [w for w in prior if not (w[4] and w[4] == prefix)]
        if not prior:
            return
        w = max(prior, key=lambda x: x[0])
        if (w[3], actor) in self.got:
            return
        self.got[(w[3], actor)] = True
        # a message between named actors on an exact place
        if w[1].startswith("run:") or actor.startswith("run:") or any(r.search(ch) for r in self.coarse):
            return
        self._delivery(ch, w, actor, t, rid)

    def _delivery(self, ch, w, actor, t, rid):
        a, b = w[1], actor
        lat = f"{(t - w[0]) / HOUR:.2f} h later"
        if "message" not in self.fired:
            self._emit("message", "First message between named actors", "joint", "message", t, rid, [a, b],
                       f"{a} wrote {ch} in {w[3]}; {b} read it in {rid}, {lat}")
        if "two_way" not in self.fired:
            if (b, a) in self.pairs:
                self._emit("two_way", "First two-way exchange", "joint", "two_way", t, rid, [a, b],
                           f"{b} had already sent to {a}; now {a} sends back through {ch}")
            self.pairs[(a, b)] = True
        if self.groups_left:
            for x in (a, b):
                if x not in self.parent and len(self.parent) < self.caps["actors"]:
                    self.parent[x] = x
                    self.size[x] = 1
            if a in self.parent and b in self.parent:
                ra, rb = self._find(a), self._find(b)
                if ra != rb:
                    self.parent[ra] = rb
                    self.size[rb] += self.size[ra]
                big = self.size[self._find(b)]
                while self.groups_left and big >= self.groups_left[0]:
                    k = self.groups_left.pop(0)
                    self._emit(f"group{k}", f"A group of {k}+ actors linked by messages", "joint", "group", t, rid, [a, b],
                               f"the message from {a} to {b} joined {big} actors into one connected group")
        else:
            self.parent.clear()
            self.size.clear()

    def _find(self, x):
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    # ------------------------------------------------------------------ programs
    def _programs(self, e, t, ids, intent):
        if "program2" in self.fired and "program3" in self.fired:
            return
        if self.action_kinds and e.kind not in self.action_kinds:
            return
        fam = self._sig(e.text)[0]
        if not fam:
            return
        f = self.fams.get(fam)
        if f is None:
            f = {"actors": [], "copies": []}
            self.fams[fam] = f
        a, ak = self._actor_simple(e, ids)
        if len(f["copies"]) < 8:
            reads = set()
            writes = intent in self.harm_set
            if not writes:
                for name, rx, wrx, rrx in self.chans:
                    for m in rx.finditer(e.text):
                        if not m.group(1) or reconstruct.in_comment(e.text, m.start()):
                            continue
                        if messages.judge_op(e.text, m.start(), m.end(), wrx, rrx) == "write":
                            writes = True
                            break
                        reads.add(f"{name}:{m.group(1)}")
                    if writes:
                        break
            f["copies"].append((writes, reads))
        if ak != "run" and len(f["actors"]) < 3 and all(x[0] != a for x in f["actors"]):
            f["actors"].append((a, t, e.id))
        if len(f["actors"]) >= 2:
            routine = not any(w or any(c in self.written for c in r) for w, r in f["copies"])
            if routine:
                return
            if len(f["actors"]) >= 2 and "program2" not in self.fired:
                a0, a1 = f["actors"][0], f["actors"][1]
                self._emit("program2", "First program reused by another actor", "joint", "program", a1[1], a1[2], [a0[0], a1[0]],
                           f"{a1[0]} ran the program {a0[0]} first ran in {a0[2]}", evidence_t=a1[1])
            if len(f["actors"]) >= 3 and "program3" not in self.fired:
                a0, a2 = f["actors"][0], f["actors"][2]
                self._emit("program3", "First program run by three actors", "joint", "program", a2[1], a2[2], [a0[0], a2[0]],
                           f"{a2[0]} became the third actor to run the program first run by {a0[0]} in {a0[2]}", evidence_t=a2[1])

    def _actor_simple(self, e, ids):
        toks = [x for x in ids if x not in self.shared]
        if e.actor and e.actor in toks:
            return e.actor, "named"
        if toks:
            return toks[0], "token"
        if self.pack.handles_rx:
            m = self.pack.handles_rx.search(e.text)
            if m:
                return packs.family_of(m.group(1), self.pack), "handle"
        root = self.root.get(e.id, e.id)
        inh = self.thread_ident.get(root)
        return (inh, "token_via_thread") if inh else ("run:" + root, "run")

    # ------------------------------------------------------------------ end
    def finish(self):
        """End of the stream: judge the last hour of the volume rule, as the replay does."""
        self._new = []
        for which in ("all", "harm"):
            if self.cur[which] is not None:
                self._close_hours(which, self.cur[which], self.cur[which] + 1)
        return self._new

    def memory(self):
        sizes = {"ids_roots": self.root, "thread_idents": self.votes, "tokens_first_use": self.first_use,
                 "tokens_seen_as_data": self.seen_data, "tokens_carried": self.seen_carried, "places": self.places,
                 "channels": self.chan, "got": self.got, "actors": self.parent, "pairs": self.pairs, "families": self.fams,
                 "written": self.written}
        return {k: {"entries": len(v), "evicted": getattr(v, "evicted", 0)} for k, v in sizes.items()}


# ------------------------------------------------------------------ streaming a file

def iter_records(path, mapping=None, sample=5000):
    """Events from a trace file one at a time. CSV and JSON-lines are read lazily (columns are decided from the
    first `sample` rows, as the loader does on the whole file); other shapes are loaded whole by the normal loader."""
    import csv
    ext = os.path.splitext(path)[1].lower()
    stem = os.path.splitext(os.path.basename(path))[0]
    csv.field_size_limit(sys.maxsize)
    if ext in (".csv", ".tsv", ".jsonl"):
        f = open(path, encoding="utf-8-sig", errors="replace", newline="")

        def rows():
            if ext == ".jsonl":
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            o = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(o, dict):
                            yield o
            else:
                yield from csv.DictReader(f, delimiter="\t" if ext == ".tsv" else ",")
        it = rows()
        head = []
        for r in it:
            head.append(r)
            if len(head) >= sample:
                break
        from . import readers
        fmt, _ = readers.read(head[:200], stem) if not mapping else (None, None)
        if fmt:   # a known agent-framework format needs its reader over the whole file
            f.close()
            yield from model.load(path, mapping or {})
            return
        cols = model.resolve_columns(head, mapping or {})
        i = 0
        try:
            for r in head:
                i += 1
                yield from model._events_from_row(r, cols, stem, i)
            for r in it:
                i += 1
                yield from model._events_from_row(r, cols, stem, i)
        finally:
            f.close()
    else:
        yield from model.load(path, mapping or {})


def choose_pack(path):
    first = []
    for e in iter_records(path):
        first.append(e)
        if len(first) >= 2000:
            break
    name, why = packs.choose(first, {"files": [{"file": os.path.basename(path), "fields": {}}]})
    return name, why


def load_pack(pack):
    if os.path.exists(pack):
        return packs.load_pack(pack)
    return packs.load_pack(os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", pack))


def peak_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss     # bytes on macOS, kilobytes on Linux
    return round(r / 1048576 if sys.platform == "darwin" else r / 1024, 1)


def stream(records, pack, limit=None, caps=None, progress=None):
    """Run records through a monitor. Returns {events, records, seconds, records_per_s, memory, peak_mb}."""
    mon = OnlineMonitor(pack, caps)
    t0 = time.time()
    n = 0
    for rec in records:
        mon.feed(rec)
        n += 1
        if progress and n % 5000 == 0:
            progress(n)
        if n % 500 == 0:
            time.sleep(0.001)      # let the server's accept loop run while this streams in the background
        if limit and n >= limit:
            break
    mon.finish()
    dur = time.time() - t0
    return {"events": mon.events_out, "records": n, "seconds": round(dur, 2), "records_per_s": round(n / dur) if dur else None,
            "memory": mon.memory(), "peak_mb": peak_mb(), "monitor": mon}


# ------------------------------------------------------------------ against the replay

def compare(events, session, tolerance_h=0.25):
    """Online events against the replay's signs for the same keys: the table the validation asks for."""
    sim = insight.simulate(session)
    t0 = sim.get("start_t")
    rep = {g["key"]: g for g in sim["signals"]}
    on = {e["key"]: e for e in events}
    rows = []
    for key in sorted(set(rep) | set(on), key=lambda k: (rep[k]["t"] if k in rep else on[k]["t"])):
        r, o = rep.get(key), on.get(key)
        row = {"key": key, "name": (r or o)["name"], "kind": (r or o)["kind"], "family": (r or o)["family"],
               "online_time": o["time"] if o else None, "online_h": round((o["t"] - t0) / HOUR, 3) if o and t0 is not None else None,
               "online_evidence_time": o["evidence_time"] if o else None,
               "online_index": o["record_index"] if o else None,
               "replay_time": r["time"] if r else None, "replay_h": round((r["t"] - t0) / HOUR, 3) if r and t0 is not None else None,
               "replay_index": (session.order.get(r.get("record")) + 1) if r and r.get("record") in session.order else None}
        if r and o:
            row["diff_h"] = round((o["t"] - r["t"]) / HOUR, 3)
            row["evidence_diff_h"] = round((o["evidence_t"] - r["t"]) / HOUR, 3)
            row["match"] = abs(row["evidence_diff_h"]) <= tolerance_h
            row["match_known_at"] = abs(row["diff_h"]) <= tolerance_h
        else:
            row["diff_h"] = row["evidence_diff_h"] = None
            row["match"] = row["match_known_at"] = False
        row["status"] = "both" if (r and o) else ("replay only" if r else "online only")
        rows.append(row)
    both = [x for x in rows if x["status"] == "both"]
    return {"rows": rows, "tolerance_h": tolerance_h, "replay_signs": len(rep), "online_signs": len(on), "both": len(both),
            "matched": sum(1 for x in both if x["match"]), "within_1h": sum(1 for x in both if abs(x["diff_h"]) <= 1.0),"matched_known_at": sum(1 for x in both if x["match_known_at"]),
            "median_abs_diff_h": _med([abs(x["diff_h"]) for x in both]),
            "median_abs_evidence_diff_h": _med([abs(x["evidence_diff_h"]) for x in both])}


def _med(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 3) if xs else None


# ------------------------------------------------------------------ endpoint

_CACHE = {}
_LOCK = threading.Lock()


def replay_session(s, tolerance_h=0.25):
    """Stream a loaded session's events through a monitor and compare with its replay."""
    pack = s.pack
    out = stream(iter(s.events), pack)
    cmp = compare(out["events"], s, tolerance_h)
    res = {"dataset": s.name, "pack": pack.name, "records": out["records"], "seconds": out["seconds"],
           "records_per_s": out["records_per_s"], "memory": out["memory"],
           "caps": CAPS, "events": [{k: v for k, v in e.items() if k != "evidence_t" and k != "t"} for e in out["events"]],
           "compare": cmp, "approximations": APPROXIMATIONS}
    return res


APPROXIMATIONS = [
    "Times: the record's own time, else a unix time in its text (outliers replaced by the median of the last 21 such times), else the last accepted time, else its parent's. The replay fits all times together afterwards.",
    "Actor: a thread's token so far; the replay uses the thread's most used token over the whole thread.",
    "A carried token can only be known at its first use; the event says when the carrying happened (the replay's time) and when it was known.",
    "A reused program counts as routine against the places written so far; the replay uses every place ever written.",
    "Whole-page wiki edits are not tested for kept lines, so an overwrite can count as a message.",
]


def _online_replay(state, q):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset loaded")
    key = (s.name, len(s.events), id(s))
    with _LOCK:
        c = _CACHE.get(key)
        if c is None:
            c = {"running": True, "result": None, "error": None}
            _CACHE.clear()
            _CACHE[key] = c

            def work():
                try:
                    c["result"] = replay_session(s)
                except Exception as e:
                    c["error"] = str(e)[:200]
                c["running"] = False
            if len(s.events) <= 20000:
                work()
            else:
                threading.Thread(target=work, daemon=True).start()
    if c["running"]:
        return {"running": True, "records": len(s.events), "note": "streaming the dataset through the monitor"}
    if c["error"]:
        raise ValueError(c["error"])
    return {"running": False, **c["result"]}


GET = {"online_replay": _online_replay}
POST = {}


# ------------------------------------------------------------------ command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.online")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="stream a trace through the online monitor and print the events")
    r.add_argument("trace")
    r.add_argument("--pack", default="auto")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--compare", action="store_true", help="also load the whole trace and compare with the replay (needs more memory and time)")
    r.add_argument("--json", default=None, help="write the result to this file")
    a = ap.parse_args(argv)
    pack_name = a.pack
    if pack_name == "auto":
        pack_name, why = choose_pack(a.trace)
        print(f"pack: {pack_name} ({why})")
    pack = load_pack(pack_name)
    last = [0]

    def prog(n):
        if n - last[0] >= 50000:
            last[0] = n
            print(f"  {n:,} records…", file=sys.stderr)
    out = stream(iter_records(a.trace), pack, a.limit, progress=prog)
    peak = peak_mb()
    print(f"{out['records']:,} records in {out['seconds']} s: {out['records_per_s']:,} records/s; peak memory {peak} MB")
    for e in out["events"]:
        print(f"  record {e['record_index']:>8,}  {e['time']}  {e['key']:<52} {e['why'][:80]}")
    big = {k: v for k, v in out["memory"].items() if v["evicted"]}
    print("evictions: " + (", ".join(f"{k} {v['evicted']:,}" for k, v in big.items()) if big else "none (no cap was reached)"))
    res = {"records": out["records"], "seconds": out["seconds"], "records_per_s": out["records_per_s"], "peak_mb": peak,
           "memory": out["memory"], "events": [{k: v for k, v in e.items() if k not in ("evidence_t", "t")} for e in out["events"]]}
    if a.compare:
        from .session import Session
        s = Session()
        s.load(a.trace, pack_name, {}, os.path.basename(a.trace))
        cmp = compare(out["events"], s)
        res["compare"] = cmp
        print(f"\nagainst the replay (tolerance {cmp['tolerance_h']} h): {cmp['matched']} of {cmp['both']} shared signs match on when it happened; "
              f"{cmp['matched_known_at']} on when it was known")
        for x in cmp["rows"]:
            d = "" if x["diff_h"] is None else f"{x['diff_h']:+.2f} h"
            print(f"  {x['key'][:50]:<50} online {x['online_time'] or '-':<17} replay {x['replay_time'] or '-':<17} {d:>9}  {x['status']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

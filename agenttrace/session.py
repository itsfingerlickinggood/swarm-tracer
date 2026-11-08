"""One loaded dataset, fully analyzed and indexed, for the app and the AI investigator.

Session.load runs the whole pipeline once: tags and threads (analysis), time, identities
and replay (reconstruct), channels, deliveries and content spread (messages). It then
builds indexes so any single event can be traced: its parent chain, children, channel
operations, messages in and out, and copies of the same program under other actors.
"""
import json
import os
import re
from collections import Counter, defaultdict

from . import analysis, insight, messages, model, packs, reconstruct

PACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")


def _display(actor):
    """The name the app shows ('cred 169' for '[CREDENTIAL 169]'), so search matches what people see."""
    return re.sub(r"\[CREDENTIAL (\d+)\]", r"cred \1", actor) + " " + actor


def list_packs():
    out = [{"file": "auto", "name": "auto: pick a pack from the data",
            "description": "Looks at the records (wiki revisions, chat roles, code with redacted credentials) and picks the pack that fits; the overview says which and why."}]
    for f in sorted(os.listdir(PACK_DIR)):
        if f.endswith(".json"):
            try:
                p = packs.load_pack(os.path.join(PACK_DIR, f))
                out.append({"file": f, "name": p.name, "description": p.description})
            except SystemExit as e:
                out.append({"file": f, "name": f, "description": f"invalid pack: {e}"})
    return out


class Session:
    def __init__(self):
        self.loaded = False
        self.name = None

    # ------------------------------------------------------------------ load
    def load(self, path, pack_file, mapping=None, name=None):
        """Analyze a file or folder. A large input analyzed before with the same pack, mapping and code
        comes back from the disk cache (agenttrace/cache.py; SWARM_TRACER_NO_CACHE=1 turns it off)."""
        from . import cache
        self.path = path                 # where the data came from (ground truth files sit next to it)
        if cache.restore(self, path, pack_file, mapping, name):
            return
        self._analyze(path, pack_file, mapping, name)
        try:
            self.summary()   # computed once here, so a cached session needs no recomputation either
        except Exception:
            self._summary = None   # the app will raise it where the summary is asked for, as before
            return
        cache.store(self, path, pack_file, mapping)

    def _analyze(self, path, pack_file, mapping=None, name=None):
        self.events = model.load(path, mapping or {})
        import copy
        self.read_report = copy.deepcopy(model.LAST_REPORT)
        if not self.events:
            raise ValueError("the file has no records")
        self.pack_choice = None
        if not pack_file or pack_file in ("auto", "auto.json"):
            pack_file, why = packs.choose(self.events, self.read_report)
            self.pack_choice = {"pack": pack_file, "why": why}
        pack_path = pack_file if os.path.isabs(pack_file) else os.path.join(PACK_DIR, pack_file)
        self.pack = packs.load_pack(pack_path)
        self.res = analysis.analyze(self.events, self.pack)
        self.auto_shared = []
        if self.pack.raw.get("auto_shared_identities") and not self.pack.raw.get("shared_identities"):
            self.auto_shared = packs.detect_shared_identities(self.events, self.pack, self.res["_root"])
            self.pack.raw["shared_identities"] = [t for t, _ in self.auto_shared]
        self.rec = reconstruct.reconstruct(self.events, self.pack, self.res)
        self.flow = messages.message_flow(self.events, self.pack, self.rec, self.res)
        self.name = name or os.path.basename(path)
        self._index()
        self.loaded = True

    def _index(self):
        ev = self.events
        self.by_id = {e.id: e for e in ev}
        self.order = {e.id: i for i, e in enumerate(ev)}
        self.children = defaultdict(list)
        for e in ev:
            if e.parent and e.parent in self.by_id:
                self.children[e.parent].append(e.id)
        self.actor = {}
        for e in ev:
            self.actor[e.id] = messages.actor_of(e, self.rec, self.res, self.pack)
        ops = messages.channel_ops(ev, self.pack, self.rec, self.res)
        self.op_list = ops
        self.ops_by_id = defaultdict(list)
        for ch, op, a, ak, t, i, rid in ops:
            self.ops_by_id[rid].append({"channel": ch, "op": op})
        self.del_in = defaultdict(list)
        self.del_out = defaultdict(list)
        for d in self.flow["_deliveries"]:
            self.del_in[d["read_id"]].append(d)
            self.del_out[d["write_id"]].append(d)
        self.over_in = defaultdict(list)
        self.over_out = defaultdict(list)
        for d in self.flow.get("_overwrites", []):
            self.over_in[d["read_id"]].append(d)
            self.over_out[d["write_id"]].append(d)
        self._index_pairs()
        self.prefix = messages.program_prefix(ev)
        self.by_prefix = defaultdict(list)
        for rid, p in self.prefix.items():
            self.by_prefix[p].append(rid)
        insight.build_indexes(self)

    # ------------------------------------------------------------------ pairs and conversations
    def _index_pairs(self):
        self.by_pair = defaultdict(list)
        for d in self.flow["_deliveries"]:
            self.by_pair[(d["from"], d["to"])].append(d)
        self.over_by_pair = defaultdict(list)
        for d in self.flow.get("_overwrites", []):
            self.over_by_pair[(d["from"], d["to"])].append(d)
        rows = []
        for (a, b), lst in self.by_pair.items():
            rows.append({"from": a, "to": b, "messages": len(lst), "channels": len({d["channel"] for d in lst}),
                         "back": len(self.by_pair.get((b, a), [])),
                         "overwrites": len(self.over_by_pair.get((a, b), [])),
                         "first": min(d["read_time"] for d in lst), "last": max(d["read_time"] for d in lst),
                         "named": not a.startswith("run:") and not b.startswith("run:")})
        rows.sort(key=lambda r: (-r["messages"], r["first"]))
        iso = reconstruct.iso
        for r in rows:
            r["first"], r["last"] = iso(r["first"]), iso(r["last"])
            r["_key"] = (_display(r["from"]) + " " + _display(r["to"])).lower()
        self.pair_rows = rows

    def pairs(self, q="", named_only=True, offset=0, limit=50):
        """Every sender-receiver pair, busiest first. q matches either actor (also as 'cred 169')."""
        terms = q.lower().split()
        hits = [r for r in self.pair_rows if (r["named"] or not named_only) and all(t in r["_key"] for t in terms)]
        return {"total": len(hits), "offset": offset,
                "rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in hits[offset:offset + limit]]}

    def _snippet(self, rid, channel, width=240):
        """The part of a record around its mention of the channel, else its start."""
        text = " ".join(self.by_id[rid].text.split())
        key = channel.split(":", 1)[1] if ":" in channel else channel
        if channel.startswith("place:"):
            key = messages._short(key)
        i = text.lower().find(key.lower()) if key else -1
        if i < 0:
            return text[:width] + ("…" if len(text) > width else "")
        start = max(0, i - width // 3)
        end = min(len(text), start + width)
        return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")

    def conversation(self, a, b, limit=2000):
        """Everything that passed between two actors, both directions, in time order, with record ids."""
        iso = reconstruct.iso
        # places the pack marks as coarse (a redaction that kept only the owner) may join several places
        coarse = [re.compile(p) for p in self.pack.raw.get("coarse_channels", [])]
        items = []
        for frm, to in ((a, b), (b, a)):
            for kind, src in (("message", self.by_pair), ("overwrite", self.over_by_pair)):
                for d in src.get((frm, to), []):
                    items.append((d["read_time"], d["write_time"], {
                        "kind": kind, "from": frm, "to": to, "channel": d["channel"], "how": d.get("how"),
                        "merged_place": any(r.search(d["channel"]) for r in coarse),
                        "write_id": d["write_id"], "write_time": iso(d["write_time"]),
                        "read_id": d["read_id"], "read_time": iso(d["read_time"]), "latency_h": d["latency_h"],
                        "lines": d.get("lines", []),
                        "write_text": self._snippet(d["write_id"], d["channel"]),
                        "read_text": self._snippet(d["read_id"], d["channel"])}))
        items.sort(key=lambda x: (x[0] if x[0] is not None else float("inf"), x[1] or 0))
        items = [x[2] for x in items]
        ids = []
        for it in items:
            for rid in (it["write_id"], it["read_id"]):
                if rid not in ids:
                    ids.append(rid)
        count = lambda f, t, k: sum(1 for x in items if x["from"] == f and x["to"] == t and x["kind"] == k)
        return {"a": a, "b": b, "total": len(items),
                "a_to_b": count(a, b, "message"), "b_to_a": count(b, a, "message"),
                "overwrites": sum(1 for x in items if x["kind"] == "overwrite"),
                "on_merged_places": sum(1 for x in items if x["merged_place"]),
                "places": sorted({x["channel"] for x in items}),
                "first": items[0]["read_time"] if items else None, "last": items[-1]["read_time"] if items else None,
                "record_ids": ids, "items": items[:limit], "truncated": len(items) > limit}

    # ------------------------------------------------------------------ summary
    def summary(self):
        if getattr(self, "_summary", None) is None:
            self._summary = self._build_summary()
        return self._summary

    def _build_summary(self):
        res, rec, flow = self.res, self.rec, self.flow
        n = res["records"]
        times = rec["_times"]
        harm = rec.get("_harm_times", [])
        # harm remaining over time, by hour, for the early-flag chart
        hours = sorted({reconstruct.iso(t)[:13] for t in harm})
        remaining = []
        if harm:
            j = 0
            total = len(harm)
            for h in hours:
                while j < total and reconstruct.iso(harm[j])[:13] <= h:
                    j += 1
                remaining.append([h, round(1 - j / total, 4)])
        spread_named = [{**x, "what": insight.program_gist(self, x["source_record"])} for x in flow["content_spread"][:30]]
        return {
            "name": self.name,
            "pack": self.pack.name,
            "pack_actor_note": self.pack.raw.get("actor_note"),
            "pack_choice": self.pack_choice,
            "shared_identities": self.pack.raw.get("shared_identities", []),
            "auto_shared": [{"identity": t, "share_of_runs": s} for t, s in self.auto_shared],
            "read_report": self.read_report,
            "records": n,
            "kinds": res["kinds"],
            "threads": res["threads"],
            "time_test": rec["time_test"],
            "timed": len(times),
            "identity_test": rec["identity_test"],
            "identities_total": rec["identities_total"],
            "identities": rec["identities"][:25],
            "intents": rec["intents"],
            "activity_by_hour": rec["activity_by_hour"],
            "evidence_tags": res["evidence_tags"],
            "context_tags": res["context_tags"],
            "stages": res["stages"],
            "gaps": res["gaps"],
            "replay": rec["replay"],
            "harm_events_timed": rec["harm_events_timed"],
            "harm_remaining_by_hour": remaining,
            "seen_then_used": rec["seen_then_used"][:40],
            "carried_edges": rec["carried_edges"][:30],
            "shared_places": rec["shared_places"][:30],
            "reply_edges": res["reply_edges"][:30],
            "flow": {k: v for k, v in flow.items() if not k.startswith("_") and k not in ("content_spread", "top_channels")},
            "top_channels": flow["top_channels"][:30],
            "content_spread": spread_named,
            "list_totals": {k: len(v) for k, v in self._lists().items()},
            "intent_names": insight.intent_names(self.pack),
            "tag_names": insight.tag_names(self.pack),
            "harm_names": sorted(self.pack.harm),
            "actor_kinds": dict(Counter({a: ak for a, ak in self.actor.values()}.values())),
            "actions": self._action_counts(),
            "phases": insight.simulate(self)["phases"],
        }

    def _action_counts(self):
        """Actions (records an agent ran) and who they are credited to: the scope of every actor count."""
        acts = [e.id for e in self.events if reconstruct.is_action(e, self.pack)]
        named = {self.actor[r][0] for r in acts if self.actor[r][1] != "run"}
        runs = {self.actor[r][0] for r in acts if self.actor[r][1] == "run"}
        timed_named = {self.actor[r][0] for r in acts if self.actor[r][1] != "run" and r in self.rec["_times"]}
        kinds = Counter({self.actor[r][0]: self.actor[r][1] for r in acts}.values())
        return {"total": len(acts), "unattributed": sum(1 for r in acts if self.actor[r][1] == "run"), "kinds": dict(kinds),
                "named_actors": len(named), "named_actors_dated": len(timed_named), "runs": len(runs),
                "dated": sum(1 for r in acts if r in self.rec["_times"])}

    # ------------------------------------------------------------------ full lists
    def _lists(self):
        """Every list the app shows, uncut. The summary carries the first rows; /api/list pages through the rest."""
        rec, res, flow = self.rec, self.res, self.flow
        stu = [{**x, "first_seen_actor": self.actor[x["first_seen_id"]][0] if x["first_seen_id"] in self.actor else None}
               for x in rec["seen_then_used"]]
        return {"identities": rec["identities"], "seen_then_used": stu,
                "carried_edges": rec["carried_edges"], "shared_places": rec["shared_places"],
                "reply_edges": [{"from": r[0], "to": r[1], "replies": r[2]} for r in res["reply_edges"]],
                "channels": flow.get("_channels", flow["top_channels"]),
                "content_spread": flow.get("_content_spread", flow["content_spread"]),
                "overwrites": [{k: (reconstruct.iso(v) if k.endswith("_time") else v) for k, v in d.items()}
                               for d in flow.get("_overwrites", [])]}

    def listing(self, name, q="", offset=0, limit=100):
        rows = self._lists().get(name)
        if rows is None:
            raise LookupError(f"no list named {name}")
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in json.dumps(r, default=str).lower()
                    or ql in json.dumps(r, default=str).lower().replace("[credential ", "cred ")]
        return {"name": name, "total": len(rows), "offset": offset, "rows": rows[offset:offset + limit]}

    # ------------------------------------------------------------------ events
    def event_row(self, e):
        a, ak = self.actor[e.id]
        t = self.rec["_times"].get(e.id)
        return {"id": e.id, "kind": e.kind, "time": reconstruct.iso(t), "actor": a, "actor_kind": ak, "channel": e.channel,
                "intent": self.rec["_intents"].get(e.id), "tags": self.res["_evidence"][e.id],
                "ops": len(self.ops_by_id.get(e.id, [])),
                "in": len(self.del_in.get(e.id, [])), "out": len(self.del_out.get(e.id, [])),
                "preview": " ".join(e.text.split())[:180]}

    def search(self, q="", kind="", actor="", intent="", tag="", channel_only=False, offset=0, limit=100, hour=""):
        ql = q.lower().strip()
        out = []
        total = 0
        kinds, intents_c, actors_c, hours = Counter(), Counter(), Counter(), Counter()
        for e in self.events:
            if kind and e.kind != kind:
                continue
            if intent and self.rec["_intents"].get(e.id) != intent:
                continue
            if tag and tag not in self.res["_evidence"][e.id]:
                continue
            if actor and self.actor[e.id][0] != actor:
                continue
            if channel_only and not self.ops_by_id.get(e.id):
                continue
            if hour:
                t = self.rec["_times"].get(e.id)
                if t is None or not reconstruct.iso(t).startswith(hour):
                    continue
            if ql and ql not in e.id.lower() and ql not in e.text.lower() \
                    and ql not in (e.actor or "").lower() and ql not in (e.channel or "").lower():
                continue
            if offset <= total < offset + limit:
                out.append(self.event_row(e))
            total += 1
            kinds[e.kind] += 1
            it = self.rec["_intents"].get(e.id)
            if it:
                intents_c[it] += 1
            actors_c[self.actor[e.id][0]] += 1
            t = self.rec["_times"].get(e.id)
            if t is not None:
                hours[reconstruct.iso(t)[:13]] += 1
        return {"total": total, "offset": offset, "rows": out,
                "facets": {"kind": dict(kinds.most_common()), "intent": dict(intents_c.most_common()),
                           "actor": [[a, n] for a, n in actors_c.most_common(12)]},
                "hist": sorted(hours.items()), "timed": sum(hours.values())}

    def trace(self, rid, text_limit=20000):
        e = self.by_id.get(rid)
        if not e:
            return None
        chain, cur, seen = [], e.parent, set()
        while cur and cur in self.by_id and cur not in seen and len(chain) < 50:
            seen.add(cur)
            chain.append(self.event_row(self.by_id[cur]))
            cur = self.by_id[cur].parent
        iso = reconstruct.iso
        din = [{"channel": d["channel"], "from": d["from"], "write_id": d["write_id"], "write_time": iso(d["write_time"]),
                "latency_h": d["latency_h"], "how": d.get("how")} for d in self.del_in.get(rid, [])]
        dout = [{"channel": d["channel"], "to": d["to"], "read_id": d["read_id"], "read_time": iso(d["read_time"]),
                 "latency_h": d["latency_h"], "how": d.get("how")} for d in self.del_out.get(rid, [])]
        # edits that replaced another actor's edit without keeping any of it: not messages
        overwrote = [{"channel": d["channel"], "actor": d["from"], "record": d["write_id"], "how": d["how"]}
                     for d in self.over_in.get(rid, [])]
        overwritten_by = [{"channel": d["channel"], "actor": d["to"], "record": d["read_id"], "how": d["how"]}
                          for d in self.over_out.get(rid, [])]
        p = self.prefix.get(rid)
        copies = []
        if p:
            for other in sorted(self.by_prefix[p], key=lambda x: self.order[x]):
                if other != rid:
                    copies.append(self.event_row(self.by_id[other]))
                if len(copies) >= 30:
                    break
        t = self.rec["_times"].get(rid)
        row = self.event_row(e)
        row.update({
            "text": e.text[:text_limit], "text_truncated": len(e.text) > text_limit, "text_length": len(e.text),
            "parent": e.parent, "thread_root": self.res["_root"][rid],
            "time_source": "time field" if e.time else ("estimated" if t is not None else None),
            "identities": self.rec["_ids"].get(rid, {}),
            "context_tags": self.res["_context"][rid],
            "parent_chain": chain,
            "children": [self.event_row(self.by_id[c]) for c in self.children.get(rid, [])[:50]],
            "children_total": len(self.children.get(rid, [])),
            "channel_ops": self.ops_by_id.get(rid, []),
            "messages_in": din, "messages_out": dout,
            "overwrote": overwrote, "overwritten_by": overwritten_by,
            "same_program": copies, "same_program_total": len(self.by_prefix.get(p, [])) - 1 if p else 0,
            "explain": insight.explain(self, rid),
            "why": insight.why_spans(self, rid, text_limit),
        })
        row["explain"]["components"]["ancestors"] = len(chain)
        return row

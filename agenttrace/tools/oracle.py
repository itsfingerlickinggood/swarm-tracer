"""Consistency oracle: pull the endpoints the tabs use and assert that their counts agree.

    python3 -m agenttrace.tools.oracle [--url http://127.0.0.1:8031] [--json]

Each check prints the numbers it compared and PASS or FAIL. Where two numbers legitimately differ,
the check asserts the documented relation (for example: messages between named actors = messages on
exact places + messages on places the redaction may have merged), not equality.

The relations mirror what the views compute in the browser:
  - top bar / overview / network lead "N named actors": summary.actions.named_actors
  - network: /api/messages rows with a read time, both ends named (not "run:")
  - timeline chronology: /api/sim signals between the first and last hour of summary.activity_by_hour
  - early flag table, overview dots, tab badge: every /api/sim signal
  - compare "first sign": the first /api/sim signal of each family
Exits 1 when any check fails.
"""
import argparse
import calendar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOUR = 3600


# ------------------------------------------------------------------ helpers (unit-tested)

def is_named(actor):
    """Same rule as insight.is_named and the views' isNamed: anything that is not an anonymous run."""
    return bool(actor) and not str(actor).startswith("run:")


def prepare_messages(raw):
    """/api/messages -> list of dicts, the way views/network.js prepare() reads it (read time required)."""
    cols = raw.get("columns") or []
    ix = {c: i for i, c in enumerate(cols)}
    out = []
    for r in raw.get("rows") or []:
        m = {"from": r[ix["from"]], "to": r[ix["to"]], "channel": r[ix["channel"]], "read_t": r[ix["read_t"]],
             "merged": bool(r[ix["merged"]]) if "merged" in ix else False}
        if m["read_t"] is not None:
            out.append(m)
    out.sort(key=lambda m: m["read_t"])
    return out


def message_stats(msgs):
    """Counts the network tab shows: named messages, merged split, named pairs, named nodes."""
    named = [m for m in msgs if is_named(m["from"]) and is_named(m["to"])]
    pairs = {(m["from"], m["to"]) for m in named}
    nodes = {m["from"] for m in named} | {m["to"] for m in named}
    return {"all": len(msgs), "merged_all": sum(1 for m in msgs if m["merged"]),
            "named": len(named), "named_merged": sum(1 for m in named if m["merged"]),
            "named_exact": sum(1 for m in named if not m["merged"]),
            "named_pairs": len(pairs), "named_pairs_no_self": len({p for p in pairs if p[0] != p[1]}),
            "named_nodes": nodes}


def hour_to_epoch(h):
    """'2026-07-03 05' (or '2026-07-03 05:12') -> epoch seconds, UTC; None when it cannot be read."""
    if not h:
        return None
    s = str(h).replace("at or before ", "").replace(" UTC", "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%Y-%m-%d"):
        try:
            return calendar.timegm(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def signals_in_range(signals, hours):
    """The signals the timeline chronology keeps: those between the first and the end of the last activity hour."""
    hs = sorted(hours)
    if not hs:
        return []
    t0, t1 = hour_to_epoch(hs[0]), hour_to_epoch(hs[-1])
    if t0 is None or t1 is None:
        return []
    t1 += HOUR
    return [g for g in signals if g.get("t") is not None and t0 <= g["t"] <= t1]


def first_by_family(signals):
    out = {}
    for g in signals:
        out.setdefault(g.get("family"), g)
    return out


class Checks:
    """Collects named checks with the values behind them."""

    def __init__(self, out=None):
        self.rows = []
        self.out = out

    def _add(self, name, ok, detail):
        self.rows.append({"check": name, "ok": bool(ok), "detail": detail})
        if self.out:
            self.out.write(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}\n")
        return ok

    def equal(self, name, **values):
        """All the given values are equal (None values are reported, and fail)."""
        vals = list(values.values())
        ok = bool(vals) and all(v is not None for v in vals) and all(v == vals[0] for v in vals)
        return self._add(name, ok, ", ".join(f"{k}={v}" for k, v in values.items()))

    def relation(self, name, ok, detail):
        return self._add(name, ok, detail)

    def error(self, name, e):
        return self._add(name, False, f"could not run: {type(e).__name__}: {e}")

    @property
    def failed(self):
        return [r for r in self.rows if not r["ok"]]


# ------------------------------------------------------------------ fetching

def fetch(base, path, timeout=180):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def gather(base):
    d = {"summary": fetch(base, "/api/state")}
    if not d["summary"].get("loaded"):
        raise RuntimeError(f"no dataset loaded at {base}: {d['summary']}")
    d["summary"] = d["summary"]["summary"]
    for key, path in [("messages", "/api/messages"), ("sim", "/api/sim"), ("gaps", "/api/gaps"), ("lanes", "/api/lanes"),
                      ("pairs", "/api/pairs?limit=500"), ("events", "/api/events?limit=1"),
                      ("identity", "/api/x/identity"), ("roles", "/api/x/roles?limit=1"), ("compare", "/api/x/compare")]:
        try:
            d[key] = fetch(base, path)
        except Exception as e:  # recorded; the checks that need it report the error
            d[key] = e
    # every named pair, to sum their messages (the pair list pages at 500)
    p = d["pairs"]
    if isinstance(p, dict) and p.get("total", 0) > len(p.get("rows", [])):
        rows = list(p["rows"])
        while len(rows) < p["total"]:
            nxt = fetch(base, f"/api/pairs?limit=500&offset={len(rows)}")
            if not nxt.get("rows"):
                break
            rows += nxt["rows"]
        p["rows"] = rows
    return d


def _need(d, *keys):
    for k in keys:
        if isinstance(d.get(k), Exception):
            raise RuntimeError(f"{k} endpoint failed: {d[k]}")


# ------------------------------------------------------------------ the checks

def run_checks(d, out=sys.stdout):
    c = Checks(out)
    s = d["summary"]
    f = s.get("flow") or {}
    acts = s.get("actions") or {}
    named_n = acts.get("named_actors")
    if named_n is None:
        named_n = sum(v for k, v in (s.get("actor_kinds") or {}).items() if k != "run")

    def guard(name, fn):
        try:
            fn()
        except Exception as e:
            c.error(name, e)

    # 1. named actors
    def named_actors():
        _need(d, "identity", "gaps", "compare", "roles")
        gid = next((g for g in d["gaps"]["rows"] if g["key"] == "identity"), {})
        c.equal("named actors: top bar = overview = Agents estimate = Compare = gaps 'identity' = roles",
                summary_actions=named_n, agents_estimate=d["identity"]["estimate"]["named_actors"],
                compare_a=d["compare"]["a"]["named_actors"], gaps_identity=gid.get("count"),
                roles=d["roles"].get("named_actors"))
    guard("named actors", named_actors)

    def network_nodes():
        _need(d, "messages", "lanes")
        st = message_stats(prepare_messages(d["messages"]))
        # lanes carries one aggregate row for all anonymous runs (kind "runs"); the rest are named actors with a dated action
        lane_actors = {a["actor"] for a in d["lanes"].get("actors", []) if a.get("kind") not in ("runs", "run") and is_named(a["actor"])}
        outside = sorted(st["named_nodes"] - lane_actors)
        c.relation("network lead 'X of N named actors': X <= N and every graph actor is a named actor with a dated action",
                   len(st["named_nodes"]) <= named_n and not outside,
                   f"X={len(st['named_nodes'])}, N={named_n}, named actors with a dated action={len(lane_actors)}, "
                   f"graph actors not among them={len(outside)}{' e.g. ' + ', '.join(map(str, outside[:3])) if outside else ''}")
        c.equal("named actors with a dated action: lanes (timeline rows, overview 'most active') = summary.actions.named_actors_dated",
                lanes_named=len(lane_actors), summary_dated=acts.get("named_actors_dated"))
    guard("network nodes", network_nodes)

    # 2. messages
    def messages():
        _need(d, "messages", "sim", "compare", "roles", "pairs", "gaps")
        raw_rows = len(d["messages"].get("rows") or [])
        msgs = prepare_messages(d["messages"])
        st = message_stats(msgs)
        c.equal("messages: top bar (flow.deliveries) = /api/messages rows", flow_deliveries=f.get("deliveries"), api_messages=raw_rows)
        c.relation("messages: every message has a read time (else the network silently drops it)",
                   len(msgs) == raw_rows, f"with read time={len(msgs)}, rows={raw_rows}")
        c.equal("named messages: network = summary.flow = Compare = roles = sum over /api/pairs",
                network=st["named"], flow_between_named=f.get("deliveries_between_named_actors"),
                compare_a=d["compare"]["a"]["messages_named"], roles=d["roles"].get("messages_between_named"),
                pairs_sum=sum(r.get("messages", 0) for r in d["pairs"].get("rows", [])))
        sim_msgs = sum(d["sim"].get("messages") or [])
        c.relation("named messages: network = replay (exact places) + merged places",
                   st["named"] == sim_msgs + st["named_merged"],
                   f"network={st['named']}, replay sum(sim.messages)={sim_msgs}, named merged={st['named_merged']}, "
                   f"replay+merged={sim_msgs + st['named_merged']}")
        c.equal("named messages on exact places: replay = Compare", replay=sim_msgs, compare_a=d["compare"]["a"]["messages_named_exact"])
        c.equal("named messages on merged places: network = Compare", network=st["named_merged"], compare_a=d["compare"]["a"]["messages_named_merged"])
        gm = next((g for g in d["gaps"]["rows"] if g["key"] == "merged"), {})
        anon_merged = st["merged_all"] - st["named_merged"]
        c.relation("What's missing merged = named merged + anonymous merged = all merged in /api/messages",
                   gm.get("count") == st["merged_all"] == st["named_merged"] + anon_merged,
                   f"gaps={gm.get('count')}, named={st['named_merged']}, anonymous={anon_merged}, all={st['merged_all']}, "
                   f"flow.coarse_channel_deliveries={f.get('coarse_channel_deliveries')}")
        c.equal("What's missing merged 'of' = all messages", gaps_of=gm.get("of"), flow_deliveries=f.get("deliveries"))
    guard("messages", messages)

    # 3. pairs
    def pairs():
        _need(d, "messages", "pairs", "compare")
        st = message_stats(prepare_messages(d["messages"]))
        c.equal("named pairs: tab badge (flow.named_actor_pairs) = network lead = matrix cells = /api/pairs total",
                badge=f.get("named_actor_pairs"), network=st["named_pairs"], matrix_cells=st["named_pairs"],
                api_pairs=d["pairs"].get("total"))
        c.equal("named pairs without self-pairs: network = Compare", network=st["named_pairs_no_self"], compare_a=d["compare"]["a"]["pairs"])
    guard("pairs", pairs)

    # 4. dated records
    def dated():
        _need(d, "events", "compare")
        rec, timed = s.get("records"), s.get("timed")
        share = round(timed / rec, 4) if rec else None
        ev = d["events"]
        c.equal("dated records: ribbon/overview (summary.timed) = Events 'with a time' (unfiltered)",
                summary_timed=timed, events_timed=ev.get("timed"))
        c.equal("records: summary = Events total (unfiltered)", summary=rec, events_total=ev.get("total"))
        c.equal("dated share: ribbon = Compare", ribbon=share, compare_a=d["compare"]["a"]["dated_share"])
        gt = next((g for g in d["gaps"]["rows"] if g["key"] == "time"), {})
        c.equal("records with no time: gaps = records - dated", gaps=gt.get("count"), computed=(rec - timed) if rec is not None else None)
    guard("dated", dated)

    # 5. replay signals
    def signals():
        _need(d, "sim", "compare")
        sigs = d["sim"].get("signals") or []
        kept = signals_in_range(sigs, (s.get("activity_by_hour") or {}).keys())
        c.equal("signals: Early flag table/badge/overview dots = Timeline chronology = Compare count",
                early=len(sigs), timeline=len(kept), compare_a=d["compare"]["a"]["signals"])
        fb = first_by_family(sigs)
        cf = d["compare"]["a"]["first_sign"] or {}
        same = set(fb) == set(cf) and all(fb[k]["name"] == cf[k]["name"] and fb[k]["time"] == cf[k]["time"] for k in fb)
        c.relation("Compare 'first sign' per family = first /api/sim signal of that family", same,
                   "; ".join(f"{k}: sim={fb[k]['name']}@{fb[k]['time']} compare={(cf.get(k) or {}).get('name')}@{(cf.get(k) or {}).get('time')}" for k in fb) or "no signals")
        rep = s.get("replay") or []
        rep_sigs = [g for g in sigs if str(g.get("key", "")).startswith("replay:")]
        c.equal("replay entries in summary = replay signals in /api/sim (none dropped for an unreadable time)",
                summary_replay=len(rep), sim_replay=len(rep_sigs))
        ordered = all(sigs[i]["t"] <= sigs[i + 1]["t"] for i in range(len(sigs) - 1))
        c.relation("signals in time order", ordered, f"{len(sigs)} signals")
        bad = [g["key"] for g in sigs if g.get("harm_share_after") is not None and not (0 <= g["harm_share_after"] <= 1)]
        c.relation("harm share after each sign is in [0, 1]", not bad, f"out of range: {bad[:5]}")
    guard("signals", signals)

    # 6. harm
    def harm():
        _need(d, "sim", "compare")
        c.equal("dated harmful actions: overview KPI (sim.harm_total) = Compare = summary.harm_events_timed",
                sim=d["sim"].get("harm_total"), compare_a=d["compare"]["a"]["harm_total"], summary=s.get("harm_events_timed"))
        c.equal("dated harmful actions: sum of sim.harmful by hour = sim.harm_total",
                hourly=sum(d["sim"].get("harmful") or []), total=d["sim"].get("harm_total"))
    guard("harm", harm)

    def places():
        _need(d, "compare")
        ct = f.get("channel_types") or {}
        c.equal("places: top bar = sum over place types = Compare", flow_channels=f.get("channels"),
                by_type=sum(v.get("channels", 0) for v in ct.values()) if ct else f.get("channels"),
                compare_a=d["compare"]["a"]["places"])
    guard("places", places)
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8031")
    ap.add_argument("--json", action="store_true", help="print the checks as JSON instead of lines")
    a = ap.parse_args(argv)
    t0 = time.time()
    d = gather(a.url)
    c = run_checks(d, out=None if a.json else sys.stdout)
    if a.json:
        print(json.dumps(c.rows, indent=1))
    else:
        print(f"\n{len(c.rows) - len(c.failed)} of {len(c.rows)} checks passed on {d['summary'].get('name')} "
              f"({d['summary'].get('records')} records) in {time.time() - t0:.1f} s")
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())

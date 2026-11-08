"""Command line: analyze any agent trace file, sample records for labeling, measure precision.

    python3 -I -m agenttrace analyze data.csv --pack packs/code_traces.json --out reports/x
    python3 -I -m agenttrace sample  data.csv --pack packs/code_traces.json --out reports/x/labels.csv
    python3 -I -m agenttrace analyze data.csv --pack packs/code_traces.json --out reports/x --labels reports/x/labels.csv
    python3 -I -m agenttrace precision reports/x/labels.csv

Run from the project root so the package and packs resolve.
"""
import argparse
import csv
import json
import os
import sys

from . import analysis, claims, claims_page, flow_page, labels, messages, model, packs, reconstruct, report


def parse_map(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--map expects role=column, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_analyze(a):
    pack = packs.load_pack(a.pack)
    events = model.load(a.input, parse_map(a.map))
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    prec = labels.precision(a.labels) if a.labels else None
    os.makedirs(a.out, exist_ok=True)

    public = {k: v for k, v in res.items() if not k.startswith("_")}
    public["reconstruct"] = {k: v for k, v in rec.items() if not k.startswith("_")}
    if prec:
        public["precision"] = prec
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(public, f, indent=2, ensure_ascii=False, default=str)

    with open(os.path.join(a.out, "records.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "kind", "parent", "thread_root", "actor", "time", "time_source", "identities", "intent",
                    "evidence_tags", "context_tags"])
        for e in events:
            t = rec["_times"].get(e.id)
            src = "time_field" if e.time else ("estimated" if t is not None else "")
            w.writerow([e.id, e.kind, e.parent or "", res["_root"][e.id], res["_attr"][e.id] or "",
                        reconstruct.iso(t) or "", src,
                        "|".join(f"{k}:{v}" for k, v in rec["_ids"][e.id].items()), rec["_intents"][e.id] or "",
                        "|".join(res["_evidence"][e.id]), "|".join(res["_context"][e.id])])

    with open(os.path.join(a.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(report.render(res, pack.name, a.title or os.path.basename(a.input), prec, rec))
    print(f"records {res['records']:,}; with evidence {res['records_with_evidence']:,}; "
          f"threads {res['threads']:,}; shared names {res['shared_names_total']:,}")
    print(f"timed {len(rec['_times']):,}; identities {rec['identities_total']:,}; "
          f"seen-then-used {len(rec['seen_then_used'])}; carried edges {rec['carried_edges_total']}; "
          f"shared places {rec['shared_places_total']}")
    print(f"report: {os.path.join(a.out, 'report.html')}")


def cmd_claims(a):
    pack = packs.load_pack(a.pack)
    events = model.load(a.input, parse_map(a.map))
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    cfg = claims.load_claims(a.claims)
    results = claims.evaluate(events, pack, res, rec, cfg)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "claims.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(claims_page.render(results, cfg, rec, a.title or f"Report claims vs. traces: {cfg['name']}"))
    for r in results:
        print(f"{r['id']:28s} records {r['records']:6d}  first {r['first_time'] or '-':16s}  identities {r['identities']:3d}  "
              f"cited {r['cited_found']}/{len(r['cited'])} matched {r['cited_matched']} dated {r['cited_timed']}")
    print(f"page: {os.path.join(a.out, 'index.html')}")


def cmd_flow(a):
    pack = packs.load_pack(a.pack)
    events = model.load(a.input, parse_map(a.map))
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    flow = messages.message_flow(events, pack, rec, res)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "flow.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in flow.items() if not k.startswith("_")}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out, "deliveries.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["channel", "from", "from_kind", "to", "to_kind", "write_id", "read_id", "write_time", "read_time", "latency_h"])
        for d in flow["_deliveries"]:
            w.writerow([d["channel"], d["from"], d["from_kind"], d["to"], d["to_kind"], d["write_id"], d["read_id"],
                        reconstruct.iso(d["write_time"]), reconstruct.iso(d["read_time"]), d["latency_h"]])
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(flow_page.render(flow, rec, a.title or os.path.basename(a.input)))
    print(json.dumps({k: flow[k] for k in ("operations", "records_on_channels", "channels", "actors_on_channels",
                                         "deliveries", "deliveries_order_unknown", "deliveries_between_named_actors",
                                         "actor_pairs", "named_actor_pairs", "latency_hours", "content_families_moving")}, indent=2))
    print(f"page: {os.path.join(a.out, 'index.html')}")


def cmd_serve(a):
    from . import server
    server.serve(a.port, a.input, a.pack, parse_map(a.map), allow_paths=a.allow_path or [])


SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def demo_input():
    """The bundled demo swarm (agenttrace/samples/demo_swarm/), else any trace file in agenttrace/samples/."""
    d = os.path.join(SAMPLES, "demo_swarm")
    if os.path.isdir(d) and any(not f.startswith(".") for f in os.listdir(d)):
        return d
    if os.path.isdir(SAMPLES):
        for root, _, files in sorted(os.walk(SAMPLES)):
            for f in sorted(files):
                if f.lower().endswith((".csv", ".jsonl", ".json", ".tsv", ".txt", ".log")) and not f.startswith("."):
                    return os.path.join(root, f)
    return None


def _open_when_up(port, timeout=120):
    """Open the browser once the server answers (the demo is analyzed before the server starts)."""
    import socket
    import threading
    import time
    import webbrowser

    def wait():
        end = time.time() + timeout
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=wait, daemon=True).start()


def cmd_demo(a):
    path = demo_input()
    if not path:
        raise SystemExit("No demo data found in " + SAMPLES + ". Run `swarm-tracer serve` and upload a trace instead.")
    print(f"demo swarm: {path}", flush=True)
    if not a.no_browser:
        _open_when_up(a.port)
    from . import server
    server.serve(a.port, path, a.pack, {})


def cmd_compare(a):
    from . import compare
    from .session import Session
    out = []
    for path, pack in ((a.first, a.pack), (a.second, a.pack2 or a.pack)):
        s = Session()
        s.load(path, pack, {})
        out.append(compare.measures(s))
    diff = compare.differences(out[0], out[1])
    if a.json:
        print(json.dumps({"a": out[0], "b": out[1], "differences": diff}, indent=2, default=str))
        return
    keys = ["records", "dated_share", "named_actors", "actions", "places", "messages_named", "messages_named_merged", "pairs",
            "two_way_share", "largest_group", "wait_median_h", "wait_p90_h", "programs_shared", "adoption_median_h", "harm_total"]
    w = max(len(k) for k in keys)
    print(f"{'':{w}}  {out[0]['name'][:30]:>30}  {out[1]['name'][:30]:>30}")
    for k in keys:
        print(f"{k:{w}}  {str(out[0][k]):>30}  {str(out[1][k]):>30}")
    for fam in ("joint", "single", "baseline"):
        cells = []
        for m in out:
            g = m["first_sign"].get(fam)
            cells.append(f"{g['time']} ({round(100 * g['harm_share_after'])}% to come)"
                         if g and g["harm_share_after"] is not None else "-")
        print(f"{'first ' + fam + ' sign':{w}}  " + "  ".join(f"{c:>30}" for c in cells))
    print()
    for d in diff:
        print("- " + d["text"])


def cmd_library(a):
    from . import compare
    for e in compare.library()["entries"]:
        print(f"{e['id']:16s} {e['title']}\n{'':16s} pack {e.get('pack')}; {'here: ' + e['available'] if e['available'] else 'not on this machine; get it from ' + str(e.get('source_url'))}")


def cmd_sample(a):
    pack = packs.load_pack(a.pack)
    events = model.load(a.input, parse_map(a.map))
    res = analysis.analyze(events, pack)
    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    n = labels.write_sample(a.out, events, res, per_tag=a.per_tag, controls=a.controls, seed=a.seed)
    print(f"wrote {n} rows to {a.out}; fill the label column with 1, 0, or leave blank")


def cmd_evaluate(a):
    from . import evaluate, figures
    from .session import Session
    s = Session()
    s.load(a.input, a.pack, parse_map(a.map))
    out = evaluate.evaluate(s)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "evaluation.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(s.summary(), f, ensure_ascii=False, default=str)
    written = figures.write_all(s, out, a.out)
    print(json.dumps({k: out[k] for k in ("baselines", "counting_rules")}, indent=2, default=str))
    print(f"wrote {os.path.join(a.out, 'evaluation.json')} and {len(written)} figures")


def cmd_precision(a):
    out = labels.precision(a.labels)
    text = json.dumps(out, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agenttrace", description="General analysis of agent traces.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="analyze a trace file and write a report")
    p.add_argument("input")
    p.add_argument("--pack", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--map", action="append", help="role=column, e.g. text=body (roles: id,text,kind,parent,actor,time,tool)")
    p.add_argument("--labels", help="filled labels CSV, to show precision and recall in the report")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("sample", help="write records to label")
    s.add_argument("input")
    s.add_argument("--pack", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--map", action="append")
    s.add_argument("--per-tag", type=int, default=10)
    s.add_argument("--controls", type=int, default=30)
    s.add_argument("--seed", type=int, default=1)
    s.set_defaults(fn=cmd_sample)

    sv = sub.add_parser("serve", help="run the Swarm Tracer web app on 127.0.0.1")
    sv.add_argument("--port", type=int, default=8010)
    sv.add_argument("--input", help="a file to analyze at start (optional; you can upload in the app)")
    sv.add_argument("--pack", default="auto", help="pack file name in agenttrace/packs, a path, or auto (pick from the data)")
    sv.add_argument("--map", action="append")
    sv.add_argument("--allow-path", action="append", metavar="DIR",
                    help="a folder whose files live mode and Compare may read (repeatable); also allowed: "
                         "SWARM_TRACER_DATA, the package and project folders, the current folder, and the --input folder")
    sv.set_defaults(fn=cmd_serve)

    fl = sub.add_parser("flow", help="message flow: who wrote to which channel, who read it, how content spread")
    fl.add_argument("input")
    fl.add_argument("--pack", required=True)
    fl.add_argument("--out", required=True)
    fl.add_argument("--map", action="append")
    fl.add_argument("--title")
    fl.set_defaults(fn=cmd_flow)

    c = sub.add_parser("claims", help="check a report's claims against the traces")
    c.add_argument("input")
    c.add_argument("--pack", required=True)
    c.add_argument("--claims", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--map", action="append")
    c.add_argument("--title")
    c.set_defaults(fn=cmd_claims)

    ev = sub.add_parser("evaluate", help="baselines, robustness, counting rules, external timing check, and report figures")
    ev.add_argument("input")
    ev.add_argument("--pack", default="auto")
    ev.add_argument("--out", required=True)
    ev.add_argument("--map", action="append")
    ev.set_defaults(fn=cmd_evaluate)

    dm = sub.add_parser("demo", help="open the app on the bundled demo swarm (agenttrace/samples/demo_swarm)")
    dm.add_argument("--port", type=int, default=8010)
    dm.add_argument("--pack", default="auto")
    dm.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    dm.set_defaults(fn=cmd_demo)

    cp = sub.add_parser("compare", help="compare two swarms: the same measures side by side, and what differs")
    cp.add_argument("first")
    cp.add_argument("second")
    cp.add_argument("--pack", default="auto", help="pack for both (or the first, with --pack2)")
    cp.add_argument("--pack2", help="pack for the second dataset")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(fn=cmd_compare)

    lb = sub.add_parser("library", help="known datasets and incidents, and whether each is on this machine")
    lb.set_defaults(fn=cmd_library)

    q = sub.add_parser("precision", help="precision and recall from a filled labels CSV")
    q.add_argument("labels")
    q.add_argument("--out")
    q.set_defaults(fn=cmd_precision)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main(sys.argv[1:])

"""Every GET route's output, hashed, under several hash seeds: the app must not depend on PYTHONHASHSEED.

    python3 -m agenttrace.tools.routes [--datasets demo wiki] [--seeds 0 1 12345] [--json out.json]

For each dataset it starts the server once per seed (PYTHONHASHSEED=seed), calls every GET path the smoke test
uses (api_paths in smoke.py: the tabs' endpoints and every /api/x/* route, with a record, an actor and a place
filled in), and hashes each reply's canonical JSON (sorted keys, timings and file paths removed, floats
rounded to 6 places). A route whose hash differs between seeds is listed. Exits 1 if any does. Set iteration
order, dict order built from sets, and sorts that leave ties in set order are the usual causes.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time

from . import smoke

VOLATILE = {"seconds", "seconds_attribute", "load_seconds", "file", "path", "generated", "cache", "seconds_total", "elapsed",
            "took", "ms", "time_ms", "timing", "timings", "computed_in", "duration_s", "records_per_s", "peak_mb", "now",
            "mtime", "age_s", "since", "busy", "generated_at", "loaded_at", "date", "elapsed_s", "elapsed", "created", "updated"}


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0])) if k not in VOLATILE}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, str) and len(x) > 40:     # a text reply (the case report's HTML): mask its generation time
        return re.sub(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?Z?(?: UTC)?", "TIME", x)
    return x


def digest(x):
    return hashlib.sha256(json.dumps(clean(x), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def fingerprint(path, pack, seed, log_dir=None, load_timeout=900, only=None, ids=None):
    """({route path: hash}, ids) for one dataset under one hash seed. Errors are hashed too (as 'HTTP code'). ids: the
    record, actor and place to ask about; the first seed picks them and the others reuse them, so that the paths match."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update({"PYTHONHASHSEED": str(seed), "SWARM_TRACER_NO_CACHE": "1"})
    env["PYTHONPATH"] = smoke.ROOT
    srv = smoke.Server(smoke.free_port(), path, pack, log_dir, allow=[path if os.path.isdir(path) else os.path.dirname(path)], env=env)
    try:
        if not srv.wait(load_timeout):
            raise RuntimeError(f"server did not start for {path}: {srv.output()[-300:]}")
        code, st, _ = smoke.http(srv.base, "/api/state")
        summary = st.get("summary", {}) if isinstance(st, dict) else {}
        ids = ids or smoke.pick_ids(srv.base, summary)
        out = {}
        for p in smoke.api_paths(ids, sorted(smoke._xget_names())):
            if only and not any(o in p for o in only):
                continue
            code, data, _ = smoke.http(srv.base, p, timeout=600)
            out[p.split("?")[0] if p.startswith("/api/x/") and "?" not in p else p] = f"{code}:{digest(data)}"
        return out, ids
    finally:
        srv.stop()


def compare(prints):
    """prints: {seed: {route: hash}} -> sorted routes whose hash is not the same under every seed."""
    routes = set().union(*[set(v) for v in prints.values()])
    return sorted(r for r in routes if len({v.get(r) for v in prints.values()}) > 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.routes", description=__doc__.split("\n")[0])
    ap.add_argument("--datasets", nargs="*", default=["demo"], help="demo, wiki, big, or label=path[::pack]")
    ap.add_argument("--seeds", nargs="*", default=["0", "1", "12345"])
    ap.add_argument("--only", nargs="*", help="only routes whose path contains one of these")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    t0 = time.time()
    bad, report = 0, {}
    work = tempfile.mkdtemp(prefix="st-routes-")
    for label, path, pack in smoke.dataset_specs(a.datasets, work):
        if not os.path.exists(path):
            print(f"SKIP  {label}: {path} not found")
            continue
        prints = {}
        ids = None
        for seed in a.seeds:
            prints[seed], ids = fingerprint(path, pack, seed, only=a.only, ids=ids)
        diff = compare(prints)
        n = len(next(iter(prints.values())))
        report[label] = {"routes": n, "seeds": a.seeds, "differ": diff}
        if diff:
            bad += 1
            print(f"FAIL  {label}: {len(diff)} of {n} routes change with the hash seed: {', '.join(d.split('?')[0] + ('?' + d.split('?')[1][:40] if '?' in d and not d.split('?')[1].startswith('id=') else '') for d in diff)}")
        else:
            print(f"PASS  {label}: all {n} routes give the same output under hash seeds {', '.join(a.seeds)}")
    print(f"ROUTES {'FAILED' if bad else 'PASSED'} in {time.time() - t0:.0f} s")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

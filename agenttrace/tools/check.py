"""One local check before every push: unit tests, the smoke test and the consistency oracle.

    python3 -m agenttrace.tools.check            # unit tests; smoke (headless Chrome) on the demo swarm, the 8
                                                  # format samples and the odd files; oracle on the demo swarm
    python3 -m agenttrace.tools.check --quick    # unit tests; smoke on the demo swarm and the samples, API only
                                                  # (no browser); oracle on the demo swarm
    python3 -m agenttrace.tools.check --full     # also the two real datasets (smoke + oracle) and the concurrency checks

Prints one line per stage and a summary, and exits non-zero when anything fails. Servers run on free ports.
"""
import argparse
import io
import os
import subprocess
import sys
import time

from . import oracle, smoke

ROOT = smoke.ROOT


def run_unit_tests():
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "agenttrace/tests", "-t", "."], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = [ln for ln in p.stdout.strip().splitlines() if ln.strip()]
    ran = next((ln for ln in reversed(tail) if ln.startswith("Ran ")), "")
    verdict = next((ln for ln in reversed(tail) if ln.startswith(("OK", "FAILED"))), tail[-1] if tail else "")
    ok = p.returncode == 0
    detail = f"{ran} — {verdict}"
    if not ok:
        fails = [ln for ln in tail if ln.startswith(("FAIL:", "ERROR:"))]
        detail += "\n      " + "\n      ".join(fails[:15])
    return ok, detail, time.time() - t0


def run_oracle(label, path, pack, port):
    srv = smoke.Server(port, path, pack)
    try:
        if not srv.wait(900):
            return False, f"server did not start on {label}: {srv.output(300)}", 0
        t0 = time.time()
        buf = io.StringIO()
        c = oracle.run_checks(oracle.gather(srv.base), out=buf)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("FAIL")]
        return not c.failed, f"{len(c.rows) - len(c.failed)}/{len(c.rows)} checks pass" + \
            ("".join("\n      " + ln for ln in lines) if lines else ""), time.time() - t0
    finally:
        srv.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="API-only smoke on the demo swarm and the samples")
    g.add_argument("--full", action="store_true", help="also the two real datasets and the concurrency checks")
    ap.add_argument("--port", type=int, default=0, help="server port (default: a free one)")
    a = ap.parse_args(argv)
    port = a.port or smoke.free_port()
    stages = []

    def stage(name, fn):
        sys.stdout.write(f"... {name}\n")
        sys.stdout.flush()
        try:
            ok, detail, sec = fn()
        except Exception as e:
            ok, detail, sec = False, f"{type(e).__name__}: {e}", 0
        stages.append((name, ok, detail, sec))
        sys.stdout.write(f"{'PASS' if ok else 'FAIL'}  {name} ({sec:.0f} s): {detail}\n")
        sys.stdout.flush()

    stage("unit tests", run_unit_tests)

    def run_smoke():
        t0 = time.time()
        names = ["demo", "samples"] + ([] if a.quick else ["odd"]) + (["wiki", "big"] if a.full else [])
        odd_dir = smoke.tempfile.mkdtemp(prefix="st-check-odd-")
        results = []
        try:
            for label, path, pack in smoke.dataset_specs(names, odd_dir):
                results.append(smoke.smoke_dataset(label, path, pack, port, smoke.TABS, browser=not a.quick))
            if a.full:
                results.append(smoke.concurrency(port))
        finally:
            smoke.shutil.rmtree(odd_dir, ignore_errors=True)
        buf = io.StringIO()
        fail = smoke.print_report(results, out=buf)
        cells = sum(len(r.cells) for r in results)
        bad = [f"{r.dataset} [{c['area']}] {c['name']}: {(c['error'] or c['note'])[:160]}" for r in results for c in r.cells if not c["ok"]]
        return not fail, f"{cells - fail}/{cells} cells pass over {len(results)} datasets" + \
            ("".join("\n      " + b for b in bad[:30]) if bad else ""), time.time() - t0
    stage("smoke" + (" (API only)" if a.quick else ""), run_smoke)

    stage("oracle on the demo swarm", lambda: run_oracle("demo swarm", os.path.join(smoke.PKG, "samples", "demo_swarm"), None, port))
    if a.full:
        stage("oracle on the collusion.wiki logs", lambda: run_oracle("wiki", os.path.join(ROOT, "full-wiki-logs"), None, port))
        stage("oracle on the Swarm Traces release", lambda: run_oracle("big", os.path.join(ROOT, "redacted_columns.csv"), "code_traces.json", port))

    failed = [s for s in stages if not s[1]]
    sys.stdout.write("\n" + "\n".join(f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok, _, _ in stages) + "\n")
    sys.stdout.write(f"CHECK {'PASSED' if not failed else 'FAILED'}: {len(stages) - len(failed)}/{len(stages)} stages "
                     f"({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

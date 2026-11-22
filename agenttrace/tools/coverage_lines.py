"""Line coverage of the agenttrace package by the unit tests, with the standard library only.

    python3 -m agenttrace.tools.coverage_lines [--json out.json] [--tests agenttrace/tests]

Uses `coverage` when it is installed (fast); otherwise the stdlib `trace` module, which slows the tests about
20 to 40 times (expect 10 to 20 minutes). Counts executable lines (as `trace` or `coverage` defines them) in
agenttrace/*.py, not in tests/ or tools/, and prints the total and the files with the lowest coverage. The
smoke test (a browser) is not part of this figure, so server paths only it reaches count as uncovered.
Threads the tests start (the HTTP server's request handlers) are traced too; subprocesses are not.
"""
import argparse
import json
import os
import sys
import time
import unittest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PKG)


def package_files():
    return sorted(os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py"))


def run_tests(tests_dir):
    suite = unittest.defaultTestLoader.discover(tests_dir, top_level_dir=ROOT)
    return unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)


def with_coverage_module(tests_dir):
    import coverage
    cov = coverage.Coverage(source=[PKG], omit=[os.path.join(PKG, "tests", "*"), os.path.join(PKG, "tools", "*")])
    cov.start()
    res = run_tests(tests_dir)
    cov.stop()
    out = {}
    for f in package_files():
        _, stmts, _, missing, _ = cov.analysis2(f)
        out[f] = (len(stmts), len(stmts) - len(missing))
    return res, out


def with_trace(tests_dir):
    """Count the lines run, with a tracer of our own on every thread.

    Two things made agenttrace/server.py read 0% with `trace.Trace(ignoredirs=...).runfunc`:
    - its ignore list is remembered by bare module name, so once the standard library's http/server.py was
      ignored, every later module called `server` was ignored too (the same for `trace` and `__init__`);
    - runfunc() traces only the calling thread, and the server tests answer requests in handler threads.
    So lines are recorded by file path, only for files of this package, and threading.settrace hands the same
    tracer to every thread started while the tests run. Subprocesses are not traced."""
    import threading
    import trace
    wanted = {}                      # co_filename -> the set of lines hit, or None for a file outside the package
    prefix = PKG + os.sep

    def lines_for(fn):
        try:
            return wanted[fn]
        except KeyError:
            full = os.path.abspath(fn)
            wanted[fn] = s = wanted.setdefault(full, set()) if full.startswith(prefix) and full.endswith(".py") else None
            return s

    def tracer(frame, event, arg):
        hit = lines_for(frame.f_code.co_filename)
        if hit is None:
            return None
        add = hit.add

        def local(frame, event, arg):
            if event == "line":
                add(frame.f_lineno)
            return local
        return local

    # whatever traced before (a debugger, or this function when its own test runs under it) is put back afterwards
    before = (sys.gettrace(), getattr(threading, "gettrace", lambda: getattr(threading, "_trace_hook", None))())
    threading.settrace(tracer)
    sys.settrace(tracer)
    try:
        res = run_tests(tests_dir)
    finally:
        sys.settrace(before[0])
        threading.settrace(before[1])
    out = {}
    for f in package_files():
        lines = set(trace._find_executable_linenos(f))
        out[f] = (len(lines), len(lines & (wanted.get(f) or set())))
    return res, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--tests", default=os.path.join(PKG, "tests"))
    a = ap.parse_args(argv)
    t0 = time.time()
    try:
        import coverage  # noqa: F401
        method = "coverage"
        res, out = with_coverage_module(a.tests)
    except ImportError:
        method = "stdlib trace"
        res, out = with_trace(a.tests)
    tot = sum(v[0] for v in out.values())
    hit = sum(v[1] for v in out.values())
    rows = sorted(((v[1] / v[0] if v[0] else 1.0, os.path.basename(f), v) for f, v in out.items()))
    print(f"tests: {res.testsRun} run, {len(res.failures)} failed, {len(res.errors)} errors, {len(res.skipped)} skipped ({method}, {time.time() - t0:.0f} s)")
    for kind, broken in (("FAIL", res.failures), ("ERROR", res.errors)):
        for test, _tb in broken:
            print(f"  {kind}: {test.id() if hasattr(test, 'id') else test}")
    print(f"line coverage of agenttrace/*.py: {hit:,} of {tot:,} executable lines = {100 * hit / tot:.1f}%")
    for frac, name, v in rows[:12]:
        print(f"  {100 * frac:5.1f}%  {name} ({v[1]}/{v[0]})")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"method": method, "lines": tot, "covered": hit, "percent": round(100 * hit / tot, 1),
                       "tests": {"run": res.testsRun, "failed": len(res.failures), "errors": len(res.errors), "skipped": len(res.skipped)},
                       "files": {os.path.basename(k): {"lines": v[0], "covered": v[1]} for k, v in out.items()}}, f, indent=1)
    return 0 if not res.failures and not res.errors else 1


if __name__ == "__main__":
    sys.exit(main())

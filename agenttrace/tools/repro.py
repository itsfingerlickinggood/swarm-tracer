"""Reproducible build: install a clean copy in a fresh environment and compare what it computes.

    python3 -m agenttrace.tools.repro               # the committed tree (git HEAD)
    python3 -m agenttrace.tools.repro --worktree    # the working tree: tracked and untracked files that git does not ignore
    python3 -m agenttrace.tools.repro --quick       # skip the unit tests and the check; install and compare only

Steps, each printed as PASS or FAIL:

  1. export   a clean copy of the source into a temporary folder (git archive HEAD, or a copy of the working tree)
  2. venv     a fresh virtual environment made with this python3
  3. install  `pip install .` into it (the build needs setuptools>=64 from the network; with no network the package
              folder is copied into the environment instead, and the step says so)
  4. import   the package imports from the environment, not from the source tree, and reports its version
  5. check    `python -m agenttrace.tools.check --quick` from the installed package: unit tests, smoke test and the
              consistency oracle on the bundled demo swarm
  6. compare  the deterministic JSON the installed package computes for the bundled demo swarm hashes to the same
              values as the working tree's, and to the same values under a second hash seed

Uncommitted work is not in HEAD: without --worktree, step 6 compares HEAD's output with the working tree's, and a
difference then means the uncommitted changes alter the numbers (the step says which outputs differ).
Exits non-zero when a step fails. The datasets are not needed: only the bundled demo data is used.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PKG)

# Runs inside either interpreter. Prints one JSON object: {output name: sha256 of its canonical JSON}.
DEMO_SCRIPT = r'''
import hashlib, json, os, sys
import agenttrace
from agenttrace.session import Session
from agenttrace import insight, units
demo = os.path.join(os.path.dirname(os.path.abspath(agenttrace.__file__)), "samples", "demo_swarm")
s = Session()
s.load(demo, "auto", {})
VOLATILE = {"seconds", "seconds_attribute", "load_seconds", "file", "path", "generated", "cache"}
def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0])) if k not in VOLATILE}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((clean(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    if isinstance(x, float):
        return round(x, 6)
    return x
def h(x):
    return hashlib.sha256(json.dumps(clean(x), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
sm = dict(s.summary()); sm.pop("read_report", None)
flow = {k: v for k, v in s.flow.items() if not k.startswith("_")}
dels = [{k: d.get(k) for k in ("channel", "from", "to", "write_id", "read_id", "write_time", "read_time", "grade", "how")} for d in s.flow["_deliveries"]]
sim = insight.simulate(s)
out = {
    "summary": h(sm),
    "flow": h(flow),
    "deliveries": h(dels),
    "signals": h([{k: g.get(k) for k in ("key", "time", "ref", "harm_share_after", "family", "kind")} for g in sim["signals"]]),
    "units_agent": h({k: v for k, v in units.units_summary(s, "agent").items() if k != "dataset"}),
    "times": h(sorted((k, round(v, 3)) for k, v in s.rec["_times"].items() if v is not None)),
}
print(json.dumps({"hashes": out, "module": os.path.abspath(agenttrace.__file__), "records": len(s.events),
                  "deliveries": len(dels), "signals": len(sim["signals"])}))
'''


def run(cmd, cwd=None, env=None, timeout=1800):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") + f"\n(timed out after {timeout} s)"
    except OSError as e:
        return 127, str(e)


def export_head(dst):
    """git archive HEAD into dst. -> (ok, detail)"""
    os.makedirs(dst, exist_ok=True)
    tar = os.path.join(os.path.dirname(dst), "head.tar")
    code, out = run(["git", "archive", "--format=tar", "-o", tar, "HEAD"], cwd=ROOT)
    if code != 0:
        return False, f"git archive failed: {out.strip()[-300:]}"
    code, out = run(["tar", "-xf", tar, "-C", dst])
    os.remove(tar)
    if code != 0:
        return False, f"tar failed: {out.strip()[-300:]}"
    _, commit = run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT)
    _, status = run(["git", "status", "--porcelain"], cwd=ROOT)
    n = len([ln for ln in status.splitlines() if ln.strip()])
    return True, f"HEAD {commit.strip()}, {count_files(dst)} files" + (f"; NOTE {n} uncommitted change(s) in the working tree are not in this copy" if n else "")


def worktree_files():
    """Tracked and untracked files git does not ignore (deleted ones left out)."""
    code, out = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT)
    if code != 0:
        raise RuntimeError(f"git ls-files failed: {out.strip()[-300:]}")
    return [f for f in out.split("\0") if f and os.path.isfile(os.path.join(ROOT, f))]


def export_worktree(dst):
    try:
        files = worktree_files()
    except RuntimeError as e:
        return False, str(e)
    for f in files:
        target = os.path.join(dst, f)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, f), target)
    return True, f"working tree, {len(files)} files (tracked and untracked, ignored files left out)"


def count_files(d):
    return sum(len(fs) for _, _, fs in os.walk(d))


def venv_python(venv):
    return os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")


def clean_env(home, seed="0"):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP")}
    env.update({"SWARM_TRACER_HOME": home, "SWARM_TRACER_CACHE_DIR": os.path.join(home, "cache"), "SWARM_TRACER_NO_CACHE": "1",
                "PYTHONHASHSEED": seed, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    return env


def site_packages(py, env):
    code, out = run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], env=env)
    return out.strip().splitlines()[-1] if code == 0 and out.strip() else None


def install(py, src, env):
    """pip install the source copy; when the build cannot fetch its backend, copy the package in. -> (ok, detail)"""
    code, out = run([py, "-m", "pip", "install", "--no-deps", "--no-input", src], cwd=src, env=env, timeout=900)
    if code == 0:
        return True, "pip install . succeeded (wheel built with the declared backend)"
    tail = " ".join(out.strip().splitlines()[-3:])[-300:]
    offline = any(k in out for k in ("Could not find a version", "No matching distribution", "ConnectionError", "Temporary failure",
                                     "Name or service not known", "nodename nor servname", "Network is unreachable", "timed out", "Max retries"))
    if not offline:
        return False, f"pip install . failed: {tail}"
    sp = site_packages(py, env)
    if not sp:
        return False, f"pip could not fetch the build backend, and the environment's site-packages was not found: {tail}"
    shutil.copytree(os.path.join(src, "agenttrace"), os.path.join(sp, "agenttrace"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return True, ("FALLBACK: no network, so pip could not fetch setuptools>=64 to build the wheel; the package folder was copied into the "
                  "environment instead. The pyproject build itself was NOT exercised.")


def demo_hashes(py, cwd, env, pythonpath=None):
    e = dict(env)
    if pythonpath:
        e["PYTHONPATH"] = pythonpath
    code, out = run([py, "-c", DEMO_SCRIPT], cwd=cwd, env=e, timeout=600)
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("{")), None)
    if code != 0 or line is None:
        raise RuntimeError(out.strip()[-600:])
    return json.loads(line)


def compare_hashes(a, b):
    """Names of the outputs whose hashes differ between two runs."""
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def parse_check(out):
    """The per-stage lines check.py prints at the end. -> [(name, ok)]"""
    lines = out.splitlines()
    try:
        end = max(i for i, ln in enumerate(lines) if ln.startswith("CHECK "))
    except ValueError:
        return []
    stages = []
    for ln in reversed(lines[:end]):
        if ln.startswith(("PASS  ", "FAIL  ")) and "(" not in ln.split(":")[0][-6:]:
            stages.append((ln[6:].strip(), ln.startswith("PASS")))
        elif stages:
            break
    return list(reversed(stages))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.repro", description=__doc__.split("\n")[0])
    ap.add_argument("--worktree", action="store_true", help="copy the working tree (tracked and untracked, not ignored) instead of git HEAD")
    ap.add_argument("--quick", action="store_true", help="skip the unit tests and the check (steps 1-4 and 6 only)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder and print its path")
    ap.add_argument("--json", help="also write the result to this file")
    a = ap.parse_args(argv)

    t_all = time.time()
    tmp = tempfile.mkdtemp(prefix="st-repro-")
    src, venv, home, work = (os.path.join(tmp, x) for x in ("src", "venv", "home", "work"))
    for d in (src, home, work):
        os.makedirs(d)
    env = clean_env(home)
    steps = []

    def step(name, fn):
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        sec = time.time() - t0
        steps.append({"step": name, "ok": bool(ok), "detail": detail, "seconds": round(sec, 1)})
        print(f"{'PASS' if ok else 'FAIL'}  {name} ({sec:.0f} s): {detail}", flush=True)
        return ok

    py = venv_python(venv)
    try:
        ok = step("export a clean copy", lambda: export_worktree(src) if a.worktree else export_head(src))

        def make_venv():
            code, out = run([sys.executable, "-m", "venv", venv], timeout=300)
            if code != 0:
                return False, out.strip()[-300:]
            _, ver = run([py, "-c", "import sys; print(sys.version.split()[0])"], env=env)
            return True, f"python {ver.strip()} from {sys.executable}"
        ok = ok and step("fresh virtual environment", make_venv)
        ok = ok and step("pip install .", lambda: install(py, src, env))

        def imported():
            code, out = run([py, "-c", "import agenttrace, os, importlib.metadata as m\n"
                                       "p = os.path.abspath(agenttrace.__file__)\n"
                                       "try: v = m.version('swarm-tracer')\nexcept Exception: v = 'not registered (copied in)'\nprint(p); print(v)"], cwd=work, env=env)
            if code != 0:
                return False, out.strip()[-300:]
            path, ver = out.strip().splitlines()[-2:]
            inside = os.path.realpath(path).startswith(os.path.realpath(venv))
            return inside, f"agenttrace imported from {'the environment' if inside else path}; installed version {ver}"
        ok = ok and step("import from the environment", imported)

        if ok and not a.quick:
            def check():
                code, out = run([py, "-m", "agenttrace.tools.check", "--quick"], cwd=work, env=env, timeout=1800)
                stages = parse_check(out)
                last = next((ln for ln in reversed(out.splitlines()) if ln.startswith("CHECK ")), out.strip()[-300:])
                for name, sok in stages:
                    detail = next((ln for ln in out.splitlines() if ln.startswith(("PASS  " + name + " (", "FAIL  " + name + " ("))), "")
                    print(f"      {'PASS' if sok else 'FAIL'}  {detail[6:] or name}")
                    if not sok:
                        i = out.find("FAIL  " + name + " (")
                        for ln in out[i:].splitlines()[1:12]:
                            if ln.startswith(("PASS", "FAIL", "...")):
                                break
                            print("        " + ln.strip())
                return code == 0, last
            step("check --quick from the installed package (unit tests, smoke, oracle)", check)

        if ok:
            def compare():
                inst = demo_hashes(py, work, env)
                tree = demo_hashes(sys.executable, ROOT, env, pythonpath=ROOT)
                inst2 = demo_hashes(py, work, clean_env(home, seed="12345"))
                if not os.path.realpath(inst["module"]).startswith(os.path.realpath(venv)):
                    return False, f"the installed run imported {inst['module']}"
                d1 = compare_hashes(inst["hashes"], tree["hashes"])
                d2 = compare_hashes(inst["hashes"], inst2["hashes"])
                what = f"{len(inst['hashes'])} outputs for the demo swarm ({inst['records']} records, {inst['deliveries']} messages, {inst['signals']} signs)"
                if d2:
                    return False, f"NOT deterministic: {', '.join(d2)} differ between hash seeds 0 and 12345 in the installed package"
                if d1:
                    why = "" if a.worktree else " (the copy is HEAD: uncommitted changes in the working tree may explain it; run with --worktree)"
                    return False, f"{', '.join(d1)} differ between the installed copy and the working tree{why}"
                return True, f"{what} hash the same in the installed copy and the working tree, and under a second hash seed"
            step("compare demo outputs", compare)
    finally:
        if a.keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    failed = [s for s in steps if not s["ok"]]
    planned = 5 if a.quick else 6
    print(f"\nREPRO {'PASSED' if not failed and len(steps) == planned else 'FAILED'}: {len(steps) - len(failed)}/{planned} steps "
          f"({'working tree' if a.worktree else 'git HEAD'}) in {time.time() - t_all:.0f} s")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"mode": "worktree" if a.worktree else "head", "steps": steps, "passed": not failed and len(steps) == planned}, f, indent=1)
    return 0 if not failed and len(steps) == planned else 1


if __name__ == "__main__":
    sys.exit(main())

"""Mutation testing of the counting rule: do the tests notice when the rule is broken on purpose?

    python3 -m agenttrace.tools.mutate --quick                 # a seeded sample of mutants, under 2 minutes
    python3 -m agenttrace.tools.mutate                         # every mutant of messages.py
    python3 -m agenttrace.tools.mutate --targets messages units comment
    python3 -m agenttrace.tools.mutate --baseline              # only the tests that exist at git HEAD (for before/after)
    python3 -m agenttrace.tools.mutate --out reports/integrity/mutation.json

A mutant is the source with one small change: a comparison flipped (< to <=, == to !=), and/or swapped, a number
moved by one (an index, a window size), 'write' swapped with 'read', a guard forced open or shut, a `not`
dropped, a `continue`/`break` removed. Mutants are made with `ast` (to find the place) and applied to the text
(so the diff is one line).

The live files are never changed. The package is copied into a temporary folder for each worker; the mutant is
written into the copy and the message tests are run there (python3 -m unittest -f, with a timeout: a mutant
that hangs counts as killed). A mutant is *killed* when a test fails, *survived* when all pass. Survivors are
written with their location and diff; some are equivalent mutants (no input can tell them apart), which a person
has to judge. The ones judged so far are in EQUIVALENT below, each with its reason; the result reports them
apart from the unjudged survivors and gives the killed share of the non-equivalent mutants.

Targets: messages (agenttrace/messages.py), units (agenttrace/units.py), comment (reconstruct.in_comment).
"""
import argparse
import ast
import difflib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "agenttrace")

TARGETS = {
    "messages": {"file": "messages.py", "functions": None,
                 "tests": ["agenttrace.tests.test_mutants", "agenttrace.tests.test_messages", "agenttrace.tests.test_refcount",
                           "agenttrace.tests.test_properties"],
                 "baseline": ["agenttrace.tests.test_messages"]},
    "units": {"file": "units.py", "functions": None,
              "tests": ["agenttrace.tests.test_units", "agenttrace.tests.test_properties"],
              "baseline": ["agenttrace.tests.test_units"]},
    "comment": {"file": "reconstruct.py", "functions": {"in_comment"},
                "tests": ["agenttrace.tests.test_reconstruct", "agenttrace.tests.test_messages", "agenttrace.tests.test_refcount",
                          "agenttrace.tests.test_properties"],
                "baseline": ["agenttrace.tests.test_reconstruct", "agenttrace.tests.test_messages"]},
}
BASELINE_FILES = ["agenttrace/tests/test_messages.py"]     # taken from git HEAD in --baseline mode
CMP = {ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">", ast.Eq: "!=", ast.NotEq: "==",
       ast.Is: "is not", ast.IsNot: "is", ast.In: "not in", ast.NotIn: "in"}
CMP_TEXT = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
            ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in"}
SWAP = {"write": "read", "read": "write", "post": "read"}

# Survivors judged equivalent by hand: no input can tell the mutant from the original. Keyed by mutant id, which is
# stable only while the file is byte-for-byte the one judged; with any other file the table is ignored and every
# survivor is reported as unjudged.
JUDGED_SHA256 = {"messages.py": "7ca521d71e4780a9700acf8370e1281664b16319db16c51d88494ed28fb54afc"}
EQUIVALENT = {
    "messages.py:33:1": 'only a cache: computing the table again gives the same table',
    "messages.py:39:7": 'every vote counts double, so the most used token is the same',
    "messages.py:40:9": 'most_common(2)[0] is most_common(1)[0]',
    "messages.py:55:24": 'packs.py builds the handle pattern as lookbehind + (group 1) + lookahead, so group(0) equals group(1)',
    "messages.py:82:34": 'children[None] is filled but never looked up (lookups use a record id)',
    "messages.py:90:37": 'only a memo: actor_of gives the same answer again',
    "messages.py:104:57": 'the slice then starts at the message itself, which the reply test rejects (j != i)',
    "messages.py:106:67": "with no reply rid is the message's own id, and times.get of it is t",
    "messages.py:165:108": "no request-call pattern can match starting at the '(' itself",
    "messages.py:237:229": 'hi is searched from pos and pos > 0 (the url key comes before it), so hi is -1 or greater than 0',
    "messages.py:237:230": "hi is -1 or greater than 0 (see 237 '>=' -> '>')",
    "messages.py:279:282": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:283": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:284": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:285": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:286": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:287": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:288": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:279:289": '_judge is only called by judge_span and judge_how, which always pass before and after; its own defaults are never used',
    "messages.py:327:377": 'the variable `near` is assigned and never read',
    "messages.py:327:378": 'the variable `near` is assigned and never read',
    "messages.py:327:379": 'the variable `near` is assigned and never read',
    "messages.py:327:380": 'the variable `near` is assigned and never read',
    "messages.py:327:381": 'the variable `near` is assigned and never read',
    "messages.py:327:382": 'the variable `near` is assigned and never read',
    "messages.py:327:383": 'the variable `near` is assigned and never read',
    "messages.py:327:384": 'the variable `near` is assigned and never read',
    "messages.py:327:385": 'the variable `near` is assigned and never read',
    "messages.py:338:403": 'when the helper carries no verb both branches set the same verdict and span',
    "messages.py:352:457": 'the pattern matches at most 78 characters (70 + quote + DELETE + quote), so a slice of 89 is enough',
    "messages.py:352:458": 'the pattern matches at most 78 characters, a longer slice changes nothing',
    "messages.py:352:460": 'the pattern matches at most 78 characters, a longer slice changes nothing',
    "messages.py:372:484": 'when pos equals m.start() the other branch also gives distance 0',
    "messages.py:372:485": 'when pos equals m.end() the other branch also gives distance 0',
    "messages.py:373:490": 'replaces the best distance by an equal one',
    "messages.py:419:562": '_short(None) is None, which the next guard skips',
    "messages.py:450:584": 'with an empty index every lookup misses, so the loop adds nothing',
    "messages.py:485:640": 'with nothing found the loop over found does nothing',
    "messages.py:486:642": 'with nothing found the loop over found does nothing',
    "messages.py:491:649": 'with one token, `here` can only hold that token, which is already the actor',
    "messages.py:491:650": 'with one token `here` can only hold the actor; with none it is empty',
    "messages.py:584:778": 'the first key element only places undated reads among dated ones; an undated read never affects another read',
    "messages.py:584:779": 'as 584:778',
    "messages.py:584:780": 'undated reads are then handled first instead of last; the order among dated reads is unchanged',
    "messages.py:688:988": 'rid always comes from the events, so by_id.get(rid) is never None',
    "messages.py:689:991": 'unreachable: by_id.get(rid) is never None',
    "messages.py:710:1022": 'the copies are appended in input order and the sort is stable, so ties already fall in input order',
    "messages.py:771:1103": "[0] of split(':', n) is the same for any n >= 1",
}


# ------------------------------------------------------------------ making mutants

class _Finder(ast.NodeVisitor):
    def __init__(self, src, functions):
        self.src, self.functions = src, functions
        self.lines = src.splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line.encode("utf-8")))
        self.raw = src.encode("utf-8")
        self.stack, self.out = [], []
        self.docstrings = set()

    def off(self, lineno, col):
        return self.starts[lineno - 1] + col

    def span(self, node):
        return self.off(node.lineno, node.col_offset), self.off(node.end_lineno, node.end_col_offset)

    def add(self, op, lo, hi, new, line):
        if self.functions is not None and not (self.stack and self.stack[0] in self.functions):
            return
        old = self.raw[lo:hi].decode("utf-8")
        if old == new:
            return
        self.out.append({"operator": op, "lo": lo, "hi": hi, "old": old, "new": new, "line": line,
                         "function": ".".join(self.stack) or "<module>"})

    def between(self, a_end, b_start, token, new, op, line):
        """Replace `token` in the text between two byte offsets (where an operator sits)."""
        gap = self.raw[a_end:b_start].decode("utf-8")
        i = gap.find(token)
        if i >= 0:
            lo = a_end + len(gap[:i].encode("utf-8"))
            self.add(op, lo, lo + len(token.encode("utf-8")), new, line)

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            self.docstrings.add(id(node.body[0].value))
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self.generic_visit(node)

    def visit_Compare(self, node):
        left = node.left
        for op, right in zip(node.ops, node.comparators):
            if type(op) in CMP:
                self.between(self.span(left)[1], self.span(right)[0], CMP_TEXT[type(op)], CMP[type(op)], "flip comparison", node.lineno)
            left = right
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        tok, new = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
        for a, b in zip(node.values, node.values[1:]):
            self.between(self.span(a)[1], self.span(b)[0], tok, new, "and/or", node.lineno)
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        lo, hi = self.span(node)
        if isinstance(node.op, ast.Not):
            a, b = self.span(node.operand)
            self.add("drop not", lo, hi, self.raw[a:b].decode("utf-8"), node.lineno)
        elif isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int):
            v = -node.operand.value
            self.add("off by one", lo, hi, str(v + 1) if v + 1 < 0 else "0", node.lineno)
            self.add("off by one", lo, hi, str(v - 1), node.lineno)
            return
        self.generic_visit(node)

    def visit_Constant(self, node):
        if id(node) in self.docstrings:
            return
        lo, hi = self.span(node)
        v = node.value
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, int):
            self.add("off by one", lo, hi, str(v + 1), node.lineno)
            if v > 0:
                self.add("off by one", lo, hi, str(v - 1), node.lineno)
            if v >= 40:
                self.add("window size", lo, hi, str(v // 4), node.lineno)
                self.add("window size", lo, hi, str(v * 4), node.lineno)
        elif isinstance(v, str) and v in SWAP:
            text = self.raw[lo:hi].decode("utf-8")
            self.add("swap write/read", lo, hi, text.replace(v, SWAP[v]), node.lineno)

    def guard(self, node):
        lo, hi = self.span(node.test)
        self.add("guard always true", lo, hi, "True", node.lineno)
        self.add("guard always false", lo, hi, "False", node.lineno)

    def visit_If(self, node):
        self.guard(node)
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.guard(node)
        self.generic_visit(node)

    def visit_Continue(self, node):
        lo, hi = self.span(node)
        self.add("drop continue", lo, hi, "pass", node.lineno)

    def visit_Break(self, node):
        lo, hi = self.span(node)
        self.add("drop break", lo, hi, "pass", node.lineno)

    def visit_Return(self, node):
        if node.value is not None and isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
            lo, hi = self.span(node.value)
            self.add("flip returned bool", lo, hi, str(not node.value.value), node.lineno)
        self.generic_visit(node)


def mutants_of(path, functions=None):
    """Every mutant of the file: [{id, operator, function, line, old, new, source, diff}] (syntax errors left out)."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    finder = _Finder(src, functions)
    finder.visit(ast.parse(src))
    raw = src.encode("utf-8")
    rel = os.path.relpath(path, ROOT)
    out, seen = [], set()
    for m in sorted(finder.out, key=lambda m: (m["lo"], m["operator"], m["new"])):
        key = (m["lo"], m["hi"], m["new"])
        if key in seen:
            continue
        seen.add(key)
        new_src = (raw[:m["lo"]] + m["new"].encode("utf-8") + raw[m["hi"]:]).decode("utf-8")
        try:
            compile(new_src, path, "exec")
        except (SyntaxError, ValueError):
            continue
        diff = "".join(difflib.unified_diff(src.splitlines(keepends=True), new_src.splitlines(keepends=True),
                                            "a/" + rel, "b/" + rel, n=0))
        out.append({"id": f"{os.path.basename(path)}:{m['line']}:{len(out)}", "file": rel, "operator": m["operator"],
                    "function": m["function"], "line": m["line"], "old": m["old"], "new": m["new"], "source": new_src, "diff": diff})
    return out


# ------------------------------------------------------------------ running them

def _judged_files():
    """Names of the target files that are byte-for-byte the ones the EQUIVALENT table was judged on."""
    import hashlib
    ok = set()
    for name, sha in JUDGED_SHA256.items():
        try:
            with open(os.path.join(PKG, name), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() == sha:
                    ok.add(name)
        except OSError:
            pass
    return ok


def _copy_package(dest, baseline):
    """A private copy of the package (no app, no caches) under dest/agenttrace."""
    shutil.copytree(PKG, os.path.join(dest, "agenttrace"),
                    ignore=shutil.ignore_patterns("__pycache__", "app", "*.pyc", "*.png", "*.mp4"))
    if baseline:
        for rel in BASELINE_FILES:
            try:
                old = subprocess.run(["git", "show", "HEAD:" + rel], cwd=ROOT, capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                continue
            if old.returncode == 0:
                with open(os.path.join(dest, rel), "wb") as f:
                    f.write(old.stdout)


def _run_tests(workdir, tests, timeout):
    env = dict(os.environ, PYTHONPATH=workdir, PYTHONDONTWRITEBYTECODE="1", SWARM_TRACER_NO_CACHE="1")
    try:
        p = subprocess.run([sys.executable, "-B", "-m", "unittest", "-f"] + tests, cwd=workdir, env=env,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    if p.returncode == 0:
        return "survived", ""
    tail = [x for x in p.stderr.splitlines() if x.startswith(("FAIL:", "ERROR:"))]
    return "killed", (tail[0] if tail else p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "")


class _Worker:
    def __init__(self, baseline):
        self.dir = tempfile.mkdtemp(prefix="st_mutate_")
        _copy_package(self.dir, baseline)

    def run(self, mutant, tests, timeout):
        target = os.path.join(self.dir, mutant["file"])
        with open(target, encoding="utf-8") as f:
            original = f.read()
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(mutant["source"])
            return _run_tests(self.dir, tests, timeout)
        finally:
            with open(target, "w", encoding="utf-8") as f:
                f.write(original)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run(targets=("messages",), quick=False, sample=None, seed=7, jobs=None, baseline=False, timeout=None, out=None,
        stream=sys.stdout, limit_functions=None):
    t0 = time.time()
    jobs = jobs or max(1, min(8, (os.cpu_count() or 2) - 1))
    plan = []
    for name in targets:
        cfg = TARGETS[name]
        funcs = cfg["functions"]
        if limit_functions:
            funcs = set(limit_functions) if funcs is None else funcs & set(limit_functions)
        tests = cfg["baseline"] if baseline else cfg["tests"]
        for m in mutants_of(os.path.join(PKG, cfg["file"]), funcs):
            plan.append((m, tests))
    total_made = len(plan)
    if quick and sample is None:
        sample = 48
    if sample and sample < len(plan):
        plan = random.Random(seed).sample(plan, sample)
        plan.sort(key=lambda x: x[0]["id"])
    tests_used = sorted({t for _m, ts in plan for t in ts})
    # the unmutated copy must pass, or every mutant would look killed
    probe = _Worker(baseline)
    try:
        started = time.time()
        state, why = _run_tests(probe.dir, tests_used, 600)
        clean_seconds = time.time() - started
    finally:
        probe.close()
    if state != "survived":
        raise SystemExit(f"the tests do not pass on the unmutated code ({state}: {why}); fix that first")
    timeout = timeout or max(60, int(clean_seconds * 4) + 20)
    print(f"{total_made} mutants of {', '.join(targets)}; running {len(plan)} with {jobs} workers "
          f"(tests take {clean_seconds:.1f} s clean, timeout {timeout} s){' [baseline tests from git HEAD]' if baseline else ''}", file=stream)
    workers = [_Worker(baseline) for _ in range(min(jobs, max(1, len(plan))))]
    free = list(workers)
    results = []

    def one(item):
        m, tests = item
        w = free.pop()
        try:
            state, why = w.run(m, tests, timeout)
        finally:
            free.append(w)
        return m, state, why
    try:
        with ThreadPoolExecutor(max_workers=len(workers)) as pool:
            for i, (m, state, why) in enumerate(pool.map(one, plan), 1):
                results.append((m, state, why))
                if i % 50 == 0 or i == len(plan):
                    done = sum(1 for _m, s, _w in results if s != "survived")
                    print(f"  {i}/{len(plan)} run, {done} killed", file=stream)
                    stream.flush()
    finally:
        for w in workers:
            w.close()
    killed = [r for r in results if r[1] == "killed"]
    timed = [r for r in results if r[1] == "timeout"]
    survived = [r for r in results if r[1] == "survived"]

    def table(key):
        t = {}
        for m, state, _w in results:
            row = t.setdefault(m[key], {"mutants": 0, "killed": 0, "survived": 0})
            row["mutants"] += 1
            row["survived" if state == "survived" else "killed"] += 1
        return {k: t[k] for k in sorted(t)}
    summary = {
        "about": "mutation testing of the counting rule; see agenttrace/tools/mutate.py. A survivor is a change to the rule that no test noticed (some are equivalent mutants).",
        "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "targets": list(targets),
        "mode": ("quick sample" if quick else "sample" if sample else "full") + (", baseline tests (git HEAD)" if baseline else ""),
        "tests": tests_used, "mutants_possible": total_made, "mutants_run": len(results),
        "killed": len(killed) + len(timed), "killed_by_timeout": len(timed), "survived": len(survived),
        "kill_rate": round((len(killed) + len(timed)) / len(results), 4) if results else None,
        "seconds": round(time.time() - t0, 1), "seed": seed if sample else None,
        "by_function": table("function"), "by_operator": table("operator"),
        "survivors": [{k: m[k] for k in ("id", "file", "function", "line", "operator", "old", "new", "diff")} for m, _s, _w in survived],
    }
    judged = _judged_files()
    n_eq = 0
    for sv in summary["survivors"]:
        reason = EQUIVALENT.get(sv["id"]) if os.path.basename(sv["file"]) in judged else None
        sv["judgement"] = "equivalent" if reason else "unjudged"
        if reason:
            sv["reason"] = reason
            n_eq += 1
    # an equivalent mutant that a test killed would mean the judgement is wrong: list it
    killed_ids = {m["id"] for m, _s, _w in killed + timed if os.path.basename(m["file"]) in judged}
    summary["survivors_equivalent"] = n_eq
    summary["survivors_unjudged"] = len(survived) - n_eq
    summary["judged_equivalent_but_killed"] = sorted(killed_ids & set(EQUIVALENT))
    rest = len(results) - n_eq
    summary["kill_rate_non_equivalent"] = round(summary["killed"] / rest, 4) if rest else None
    print(f"killed {summary['killed']} of {summary['mutants_run']} ({100 * (summary['kill_rate'] or 0):.1f}%), "
          f"{len(timed)} of them by timeout; survived {len(survived)}; {summary['seconds']} s", file=stream)
    print(f"survivors judged equivalent {n_eq}, unjudged {len(survived) - n_eq}; killed share of non-equivalent mutants "
          f"{100 * (summary['kill_rate_non_equivalent'] or 0):.1f}%", file=stream)
    for sv in summary["survivors"][:25]:
        print(f"  survived {sv['id']} {sv['function']}: {sv['operator']}: {sv['old']!r} -> {sv['new']!r} [{sv['judgement']}]", file=stream)
    if len(survived) > 25:
        print(f"  ... {len(survived) - 25} more in the JSON", file=stream)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print(f"wrote {out}", file=stream)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mutation testing of the counting rule (never touches the live files).")
    ap.add_argument("--targets", nargs="+", default=["messages"], choices=sorted(TARGETS))
    ap.add_argument("--quick", action="store_true", help="a seeded sample of 48 mutants (under 2 minutes)")
    ap.add_argument("--sample", type=int, help="run this many mutants, chosen with --seed")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--jobs", type=int, help="parallel workers (default: up to 8)")
    ap.add_argument("--functions", nargs="+", help="only mutants inside these functions")
    ap.add_argument("--baseline", action="store_true", help="run only the tests that exist at git HEAD (the 'before' rate)")
    ap.add_argument("--timeout", type=int, help="seconds per mutant (default: four times the clean run)")
    ap.add_argument("--out", help="write the result as JSON here (for example reports/integrity/mutation.json)")
    ap.add_argument("--min-kill-rate", type=float, default=0.0, help="exit 1 when the kill rate is below this")
    a = ap.parse_args(argv)
    s = run(a.targets, a.quick, a.sample, a.seed, a.jobs, a.baseline, a.timeout, a.out, limit_functions=a.functions)
    return 0 if (s["kill_rate"] or 0) >= a.min_kill_rate else 1


if __name__ == "__main__":
    sys.exit(main())

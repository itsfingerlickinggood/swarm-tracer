"""A time limit for the regular expressions in a pack.

Python's `re` has no timeout, and a pattern such as (a+)+$ takes exponential time on a string of a's followed
by something else, so one careless pack pattern could hang the analysis (the v2.1.0 audit ran one past 20 s).
Before a pack is used, every pattern is run against a few adversarial strings built from its own literal
characters, in a separate process that is killed after a time limit. A pattern that does not finish makes the
pack fail to load, with the pattern named. This is a screen, not a proof: a pattern that backtracks badly
only on strings the probes do not resemble can still pass. Results are remembered per process by the
pattern set, so a pack is probed once.

    SWARM_TRACER_REGEX_LIMIT   seconds allowed for the whole pack (default 3); 0 turns the check off
"""
import hashlib
import json
import os
import re
import subprocess
import sys

DEFAULT_LIMIT = 3.0
_OK = set()

_CHILD = r'''
import json, re, sys
items = json.load(sys.stdin)
for i, (pat, flags, probes) in enumerate(items):
    rx = re.compile(pat, re.I if "i" in flags else 0)
    print(i, flush=True)
    for p in probes:
        rx.search(p)
print("done", flush=True)
'''


def limit():
    try:
        return float(os.environ.get("SWARM_TRACER_REGEX_LIMIT", DEFAULT_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT


def probes_for(pattern):
    """Strings that make a badly nested pattern backtrack: runs of each literal character it contains,
    with and without a trailing character that cannot match."""
    chars = []
    for ch in re.sub(r"\\.", "", pattern):
        if ch.isalnum() or ch in " _-/.:=\"'":
            if ch not in chars:
                chars.append(ch)
    chars = (chars + ["a", " ", "x"])[:10]
    out = []
    for c in chars:
        run = c * 36
        out += [run, run + "\x01", "\x01" + run]
    out.append("ab" * 20 + "\x01")
    return out


def check(patterns, what="pack"):
    """patterns: [(pattern, flags)]. Raises SystemExit naming the first pattern that does not finish in time."""
    lim = limit()
    if lim <= 0 or not patterns:
        return
    items = [(p, f or "", probes_for(p)) for p, f in patterns]
    key = hashlib.sha1(json.dumps(items, sort_keys=True).encode()).hexdigest()
    if key in _OK:
        return
    bad = _run(items, lim)
    if bad is not None:
        # which one: probe each alone with the same limit
        for pat, flags, probes in items:
            if _run([(pat, flags, probes)], lim) is not None:
                raise SystemExit(f"{what}: the pattern {pat[:120]!r} did not finish on a short test string within {lim:g} s; "
                                 "it backtracks without limit (a repeated group inside a repeat is the usual cause). "
                                 "Rewrite it, or set SWARM_TRACER_REGEX_LIMIT=0 to skip this check.")
        raise SystemExit(f"{what}: its patterns together did not finish within {lim:g} s on short test strings")
    _OK.add(key)


def _run(items, lim):
    """None when every pattern finishes within lim seconds in total, else a short reason."""
    try:
        subprocess.run([sys.executable, "-I", "-c", _CHILD], input=json.dumps(items), capture_output=True,
                       text=True, timeout=lim)
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return None          # no way to start a process here: skip the screen rather than block the pack
    return None      # a pattern that does not compile is reported by the pack loader itself

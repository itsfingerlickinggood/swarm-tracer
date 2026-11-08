"""Rule packs: JSON files that say what to look for.

A pack has:
  behaviors: [{name, stage, pattern, flags?, context?, description?}]
      context=true tags are shown but never counted as evidence.
  shared_names: [{family, pattern}]   names that can carry information between runs
  handles: [str]                      names that identify an actor or campaign in text
  handle_families: {prefix: family}   optional grouping of handles

Reconstruction (all optional; the tool skips what a pack does not define):
  identity_patterns: [{role, pattern, flags?}]   group 1 is an identity token, e.g. an auth
                                                 credential. Used when a record has no actor field.
  variable_identity: {assign, use}               assign has groups (variable, token); use is a
                                                 regex with {var} where the variable is used as identity
  info_patterns: [{family, pattern}]             pieces of information that can spread (tokens,
                                                 keys, URLs). Whole match is the item.
  intents: [{name, pattern, flags?}]             what a record is trying to do; first match wins
  harm: [name]                                   intents or evidence tags counted as harmful in the
                                                 early-flag replay
  time: {embedded_epoch: bool, window: [start, end] | "auto", min_points, min_spearman}
                                                 infer time from unix seconds written in the text,
                                                 per contiguous block of one record kind

Patterns are Python regular expressions. Nothing is hard-coded to one dataset.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Behavior:
    name: str
    stage: str
    rx: "re.Pattern"
    context: bool
    description: str


@dataclass
class Pack:
    name: str
    behaviors: List[Behavior]
    shared_names: list
    handles_rx: object
    handle_families: dict
    description: str = ""
    identity_patterns: list = field(default_factory=list)
    variable_identity: object = None
    info_patterns: list = field(default_factory=list)
    intents: list = field(default_factory=list)
    harm: set = field(default_factory=set)
    time: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def load_pack(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    behaviors = []
    seen = set()
    for b in raw.get("behaviors", []):
        if b["name"] in seen:
            raise SystemExit(f"duplicate behavior name in pack: {b['name']}")
        seen.add(b["name"])
        flags = re.I if "i" in b.get("flags", "") else 0
        try:
            rx = re.compile(b["pattern"], flags)
        except re.error as e:
            raise SystemExit(f"bad pattern for {b['name']}: {e}")
        behaviors.append(Behavior(b["name"], b.get("stage", "other"), rx, bool(b.get("context")),
                                  b.get("description", "")))
    shared = []
    for s in raw.get("shared_names", []):
        shared.append((s["family"], re.compile(s["pattern"])))
    handles = raw.get("handles", [])
    handles_rx = None
    if handles:
        alt = "|".join(sorted(map(re.escape, handles), key=len, reverse=True))
        handles_rx = re.compile(r"(?<![A-Za-z0-9])(" + alt + r")(?![A-Za-z0-9])")
    def rx(d):
        try:
            return re.compile(d["pattern"], re.I if "i" in d.get("flags", "") else 0)
        except re.error as e:
            raise SystemExit(f"bad pattern {d.get('name') or d.get('role') or d.get('family')}: {e}")
    idp = [(d["role"], rx(d)) for d in raw.get("identity_patterns", [])]
    for role, r_ in idp:
        if r_.groups < 1:
            raise SystemExit(f"identity pattern {role} needs a capture group for the token")
    vi = raw.get("variable_identity")
    if vi:
        vi = {"assign": re.compile(vi["assign"]), "use": vi["use"]}
    info = [(d["family"], rx(d)) for d in raw.get("info_patterns", [])]
    intents = [(d["name"], rx(d)) for d in raw.get("intents", [])]
    return Pack(name=raw.get("name", path), behaviors=behaviors, shared_names=shared, handles_rx=handles_rx,
                handle_families=raw.get("handle_families", {}), description=raw.get("description", ""), raw=raw,
                identity_patterns=idp, variable_identity=vi, info_patterns=info, intents=intents,
                harm=set(raw.get("harm", [])), time=raw.get("time", {}))


def family_of(handle, pack):
    best = None
    for prefix, fam in pack.handle_families.items():
        if handle.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, fam)
    return best[1] if best else handle


# ------------------------------------------------------------------ choosing a pack from the data

import re as _re
from collections import Counter as _Counter

_CODE = _re.compile(r"fetch\(|XMLHttpRequest|Authorization|Bearer |\bcurl\b|requests\.(get|post)|subprocess|urllib|"
                    r"function\s*\(|=>|import \w|os\.popen|\bdef \w+\(|base64|json\.(loads|dumps)|JSON\.(parse|stringify)|\.then\(|await ", _re.I)
_PLACEHOLDER = _re.compile(r"\[(CREDENTIAL|REDACTED|HF REPO|SERVICE HOST)[ :\]]")
_ROLES = {"user", "assistant", "system", "tool", "human", "ai", "model", "function"}


def choose(events, read_report=None):
    """Pick the shipped pack that fits a trace, and say why. A pack is only a starting point:
    the app shows the choice, and any pack can be picked by hand instead."""
    files = [f.get("file", "") for f in (read_report or {}).get("files", [])]
    fields = {v for f in (read_report or {}).get("files", []) for vs in f.get("fields", {}).values() for v in vs}
    kinds = _Counter(e.kind for e in events)
    n = len(events)
    if any(f.startswith("revisions") for f in files) or {"rev_id", "diff_base"} & fields or kinds.get("revisions"):
        return "wiki_swarm.json", "page revisions found (wiki-style edits)"
    if n and sum(kinds.get(k, 0) for k in _ROLES) >= 0.5 * n:
        return "chat.json", "most records are chat turns (user / assistant roles)"
    sample = events[:: max(1, n // 4000)][:4000]
    code = [e for e in sample if _CODE.search(e.text[:3000])]
    if sample and len(code) >= 0.2 * len(sample):
        redacted = sum(1 for e in code if _PLACEHOLDER.search(e.text[:5000]))
        if redacted >= 0.05 * len(code):
            return "code_traces.json", f"{len(code) / len(sample):.0%} of records are code, with redaction placeholders for credentials and hosts"
        return "generic.json", f"{len(code) / len(sample):.0%} of records are code (no redaction placeholders, so the general pack)"
    return "generic.json", "no specific shape recognized, so the general pack"


def detect_shared_identities(events, pack, roots, min_share=0.25, min_tokens=20):
    """A token used in a quarter or more of all runs that carry a token, in a trace with many tokens,
    behaves like a shared key (an evaluation key every agent uses), not like one agent. Field actors
    (a sender name) are never treated this way. Returns [(token, share of runs)]."""
    from .reconstruct import identities_of
    runs_of, runs = {}, set()
    for e in events:
        toks = [t for t, role in identities_of(e, pack).items() if role != "actor_field"]
        if not toks:
            continue
        r = roots.get(e.id, e.id)
        runs.add(r)
        for t in toks:
            runs_of.setdefault(t, set()).add(r)
    if len(runs_of) < min_tokens or not runs:
        return []
    return sorted(((t, round(len(rs) / len(runs), 3)) for t, rs in runs_of.items() if len(rs) >= min_share * len(runs)),
                  key=lambda x: -x[1])

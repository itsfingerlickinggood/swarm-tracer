"""Provenance manifest: every published number, where it comes from, and where it is printed.

    python3 -m agenttrace.tools.provenance build      # compute every number, write agenttrace/claims/provenance.json
    python3 -m agenttrace.tools.provenance verify     # re-derive, compare with the manifest and the published texts
    python3 -m agenttrace verify                      # the same check, from the main command line

`build` computes each registered number from its dataset, renders the text each listed place should print,
and writes the manifest. `verify` re-derives every number and checks that

  (a) the value still equals the manifest,
  (b) every listed place still prints that value,
  (c) the dataset files hash to what the manifest recorded,
  (d) the claims files (audited_links.json, frozen_signs.json, insider_findings.json, ...) hash to what it recorded,

and exits non-zero with a table when anything drifted. Where the datasets are absent (a public clone: they are
not redistributed) it still checks (b) and (d) and the rule-file hashes, and says what it skipped.

Two kinds of problem are kept apart:
  DRIFT         something changed since the manifest was built (a value, a printed text, a file hash)
  DISAGREEMENT  a place prints a number that differs from the computed one; `build` records these, it does not
                hide them. `verify` fails on them too unless --allow-known is given.

Both commands also scan the published texts for numbers near key words (messages, agents, tokens, %, ...)
that no registered place covers, and list them as "unregistered", so coverage is visible.

Outputs: agenttrace/claims/provenance.json (tracked, deterministic) and reports/integrity/provenance_*
(a readable report, the unregistered list, the last verify result).
"""
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PKG)
MANIFEST = os.path.join(PKG, "claims", "provenance.json")
OUT = os.path.join(ROOT, "reports", "integrity")
MANIFEST_VERSION = 1
SOURCE_CHECKOUT = os.path.exists(os.path.join(ROOT, "pyproject.toml"))   # False in an installed copy: write nothing next to the package

# short names for the published texts
FILES = {
    "R": "paper/report.html", "S": "paper/slides.html", "RM": "README.md", "V": "docs/validation.md",
    "IX": "docs/index.html", "SUB": "reports/submission/SUBMISSION.md", "DS": "docs/assets/demo-script.md",
    "DD": "docs/deep-dive.md", "EW": "docs/early-warning.md", "HW": "docs/how-it-works.md",
    "LIM": "docs/limitations.md", "KI": "docs/known-issues.md", "CN": "docs/collect-next-time.md",
    "FX": "docs/forensics.md", "UG": "docs/user-guide.md", "GS": "docs/getting-started.md", "CLI": "docs/cli.md",
    "API": "docs/api.md", "PK": "docs/packs.md", "FM": "docs/formats.md", "AI": "docs/ai-investigator.md",
}
PUBLISHED = list(FILES.values())
# hashed and checked by verify; provenance.json itself is left out
CLAIM_FILES_REQUIRED = ["audited_links.json", "frozen_signs.json", "insider_findings.json"]
RULE_FILES = ["agenttrace/messages.py", "agenttrace/units.py"]

DATASETS = {
    "release": {"name": "Swarm Traces release", "path": "redacted_columns.csv", "pack": "code_traces.json",
                "inputs": ["redacted_columns.csv"], "related": ["redacted.jsonl"],
                "command": "python3 -m agenttrace evaluate redacted_columns.csv --pack code_traces.json --out reports/evaluation"},
    "wiki": {"name": "collusion.wiki logs", "path": "full-wiki-logs", "pack": "wiki_swarm.json",
             "inputs": ["full-wiki-logs"], "related": [],
             "command": "python3 -m agenttrace evaluate full-wiki-logs --pack wiki_swarm.json --out reports/evaluation-wiki"},
    "audit": {"name": "hand-audited links (claims file)", "path": "agenttrace/claims/audited_links.json", "pack": None,
              "inputs": ["agenttrace/claims/audited_links.json"], "related": [],
              "command": "counted from agenttrace/claims/audited_links.json"},
    "validation": {"name": "saved validation run on simulated swarms", "path": "reports/validation/summary.json", "pack": None,
                   "inputs": ["reports/validation/summary.json"], "related": [],
                   "command": "python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5"},
    "variance": {"name": "saved count-variance run", "path": "reports/evaluation/count_variance.json", "pack": None,
                 "inputs": ["reports/evaluation/count_variance.json"], "related": [],
                 "command": "python3 -m agenttrace.tools.count_variance redacted_columns.csv 100 reports/evaluation/count_variance.json"},
    "samples": {"name": "bundled sample swarms", "path": "agenttrace/samples", "pack": None,
                "inputs": ["agenttrace/samples/demo_swarm/demo_swarm.jsonl", "agenttrace/samples/benign_swarm/benign_swarm.jsonl"],
                "related": [], "command": "python3 -m agenttrace demo"},
    "repo": {"name": "this repository", "path": ".", "pack": None, "inputs": [], "related": [],
             "command": "python3 -m unittest discover -s agenttrace/tests -t ."},
    # v2.3.0: saved results, read as the validation run is. The measurements themselves are not re-run here.
    "external": {"name": "saved measurements on four outside datasets (v2.3.0)", "path": "reports/external", "pack": None,
                 "inputs": ["reports/external/who_and_when/results.json", "reports/external/mast_data/results.json",
                            "reports/external/salt/results.json", "reports/external/moltbook/results.json"], "related": [],
                 "command": "python3 -I agenttrace/failure_eval.py who_and_when; python3 -I agenttrace/failure_eval.py mast_data; "
                            "python3 -m agenttrace.external_eval salt; python3 -m agenttrace.external_eval moltbook"},
    "earlywarn": {"name": "saved pre-registered forward test of the main alarms and benign false alarms (v2.3.0)",
                  "path": "reports/earlywarn/summary_v23.json", "pack": None,
                  "inputs": ["reports/earlywarn/summary_v23.json", "reports/earlywarn/benign_external_v23.json"], "related": [],
                  "command": "python3 -m agenttrace.earlywarn forward23; python3 -m agenttrace.earlywarn external"},
    "crosscheck": {"name": "saved crosscheck of the two implementations of the counting rule (file not tracked in git)",
                   "path": "reports/integrity/crosscheck.json", "pack": None, "inputs": ["reports/integrity/crosscheck.json"], "related": [],
                   "command": "python3 -m agenttrace.tools.crosscheck --out reports/integrity/crosscheck.json"},
}
# the parts each dataset is computed in (each part is one subprocess; parts of one dataset run side by side)
PARTS = {"release": ["release_core", "release_evaluate", "release_attribution", "release_insiders"], "wiki": ["wiki"],
         "audit": ["audit"], "validation": ["validation"], "variance": ["variance"], "samples": ["samples"], "repo": ["repo"],
         "external": ["external"], "earlywarn": ["earlywarn"], "crosscheck": ["crosscheck"]}
HEAVY = {"release", "wiki"}       # computed from the gitignored datasets; skipped when they are absent

KEYWORDS = (r"messages?|deliver(?:y|ies)|agents?|tokens?|links?|pairs?|records?|folders?|findings?|swarms?|runs?|"
            r"payloads?|programs?|places?|actors?|tests?|labels?|signs?")


# ------------------------------------------------------------------ small helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8") if isinstance(p, str) else p)
        h.update(b"\0")
    return h.hexdigest()


def input_files(rel):
    """Every file behind an input: the file itself, or each file under a folder, as repo-relative paths."""
    p = os.path.join(ROOT, rel)
    if os.path.isfile(p):
        return [rel]
    out = []
    for root, dirs, files in os.walk(p):
        dirs.sort()
        for f in sorted(files):
            if not f.startswith("."):
                out.append(os.path.relpath(os.path.join(root, f), ROOT))
    return out


def hash_inputs(rels):
    """{relative path: {"sha256", "bytes"}} for the files that exist."""
    out = {}
    for rel in rels:
        for f in input_files(rel):
            p = os.path.join(ROOT, f)
            out[f.replace(os.sep, "/")] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    return out


def git(*args):
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_state():
    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def package_fingerprint():
    """Hash of every file that can change a computed number: the package's code, packs and claims."""
    h = hashlib.sha256()
    for sub, ext in (("", ".py"), ("tools", ".py"), ("packs", ".json"), ("claims", ".json")):
        d = os.path.join(PKG, sub)
        for f in sorted(os.listdir(d)):
            if f.endswith(ext) and f != "provenance.json" and not (sub == "tools" and f != "provenance.py"):
                h.update(f"{sub}/{f}".encode())
                with open(os.path.join(d, f), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def rule_version(pack):
    """Hash of the files that define what a message and an agent are: messages.py, units.py and the dataset's pack."""
    files = list(RULE_FILES) + ([f"agenttrace/packs/{pack}"] if pack else [])
    per = {f: sha256_file(os.path.join(ROOT, f)) for f in files if os.path.exists(os.path.join(ROOT, f))}
    return {"hash": sha256_text(*[f"{k}:{v}" for k, v in sorted(per.items())])[:16], "files": per}


def package_version():
    """The version in pyproject.toml; in an installed copy (no pyproject), the installed distribution's version."""
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            return m.group(1) if m else None
    except OSError:
        try:
            from importlib import metadata
            return metadata.version("swarm-tracer")
        except Exception:
            return None


# ------------------------------------------------------------------ published texts

def normalize(text, is_html):
    """A published text as plain prose: tags and markdown emphasis removed, entities decoded, whitespace collapsed."""
    if is_html:
        text = re.sub(r"(?is)<(style|script|svg)\b.*?</\1>", " ", text)
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    else:
        text = re.sub(r"\]\([^)\s]*\)", "]", text)          # link targets: [text](url) -> [text]
        text = text.replace("**", "").replace("`", "")
        text = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)
    text = text.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # a tag became a space: close the gaps it leaves around punctuation ("66%– 79% –88%", "( R0005279 )")
    text = re.sub(r"\s+([,.;:)%])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    return re.sub(r"\s*–\s*", "–", text)


def published_text(rel, root=None):
    p = os.path.join(root or ROOT, rel)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return normalize(f.read(), rel.endswith((".html", ".htm")))


# ------------------------------------------------------------------ formats: a value as a place prints it

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
          "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def _dec(v, places):
    q = Decimal(1).scaleb(-places)
    return str(Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP))


def number_word(n):
    n = int(n)
    if 0 <= n <= 20:
        return _WORDS[n]
    if n < 100:
        t, u = divmod(n, 10)
        return _TENS[t * 10] + ("-" + _WORDS[u] if u else "")
    return str(n)


def _time_parts(v):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)", str(v))
    if not m:
        raise ValueError(f"not a time: {v!r}")
    y, mo, d, hh, mm = m.groups()
    return int(y), int(mo), int(d), hh, mm


def _fmt_int(v):
    s = f"{int(v):,}"
    return s.replace(",", ",?")          # 189,579 or 189579


def _fmt_pct(v, places=0):
    return re.escape(_dec(Decimal(str(v)) * 100, places))


def _fmt_word(v):
    w = number_word(v)
    return f"(?i:{re.escape(w)})"


_NUM = r"-?\d[\d,]*(?:\.\d+)?"
_HM = r"\d{1,2}:\d\d"
FORMATS = {
    # name: (render the value as a regex fragment, a loose regex for "whatever is printed there")
    "int": (_fmt_int, r"\d[\d,]*"),
    "pct": (lambda v: _fmt_pct(v, 0), r"\d+(?:\.\d+)?"),
    "pct1": (lambda v: _fmt_pct(v, 1), r"\d+(?:\.\d+)?"),
    "f0": (lambda v: re.escape(_dec(v, 0)), _NUM),
    "f1": (lambda v: re.escape(_dec(v, 1)), _NUM),
    "f2": (lambda v: re.escape(_dec(v, 2)), _NUM),
    "f3": (lambda v: re.escape(_dec(v, 3)), _NUM),
    "word": (_fmt_word, r"[A-Za-z]+(?:-[a-z]+)?"),
    "pct_word": (lambda v: _fmt_word(int(_dec(Decimal(str(v)) * 100, 0))), r"[A-Za-z]+(?:-[a-z]+)?"),
    "str": (lambda v: re.escape(str(v)), r"\S+"),
    "iso": (lambda v: re.escape(str(v)[:16]), r"\d{4}-\d\d-\d\d \d\d:\d\d"),
    "hm": (lambda v: "{3}:{4}".format(*_time_parts(v)), _HM),
    "hm_on_md": (lambda v: "{3}:{4} on {m} {d}".format(*_time_parts(v), m=_MONTHS[_time_parts(v)[1] - 1], d=_time_parts(v)[2]),
                 _HM + r" on [A-Z][a-z]+ \d{1,2}"),
    "md_at_hm": (lambda v: "{m} {d} at {3}:{4}".format(*_time_parts(v), m=_MONTHS[_time_parts(v)[1] - 1], d=_time_parts(v)[2]),
                 r"[A-Z][a-z]+ \d{1,2} at " + _HM),
    "d_mon_hm": (lambda v: "{d} {m} {3}:{4}".format(*_time_parts(v), m=_MONTHS[_time_parts(v)[1] - 1][:3], d=_time_parts(v)[2]),
                 r"\d{1,2} [A-Z][a-z]{2} " + _HM),
    "mon_d_hm": (lambda v: "{m} {d} {3}:{4}".format(*_time_parts(v), m=_MONTHS[_time_parts(v)[1] - 1][:3], d=_time_parts(v)[2]),
                 r"[A-Z][a-z]{2} \d{1,2} " + _HM),
}


def default_format(v):
    if isinstance(v, bool):
        return "str"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "f2"
    return "str"


def render(template, value, fmt):
    """The regex a place must match: the template with <v> replaced by the value in that place's format."""
    frag = FORMATS[fmt][0](value)
    return template.replace("<v>", f"(?P<v>{frag})")


def loose(template, fmt):
    """The same anchor with any value of that format in the slot (to read what is printed there now)."""
    return template.replace("<v>", f"(?P<v>{FORMATS[fmt][1]})")


def check_place(text, template, value, fmt):
    """-> (status, printed, span). status: ok | disagrees | anchor_missing | file_missing."""
    if text is None:
        return "file_missing", None, None
    try:
        m = re.search(render(template, value, fmt), text)
    except (ValueError, TypeError, ArithmeticError):
        m = None
    if m:
        return "ok", m.group("v"), m.span("v")
    m = re.search(loose(template, fmt), text)
    if m:
        return "disagrees", m.group("v"), m.span("v")
    return "anchor_missing", None, None


# ------------------------------------------------------------------ the registry

class Claim:
    def __init__(self, cid, statement, how, places=(), fmt=None, block=None):
        self.id, self.statement, self.how = cid, statement, how
        self.source = cid.split(".", 1)[0]
        self.places = [(FILES.get(p[0], p[0]), p[1], (p[2] if len(p) > 2 else None)) for p in places]
        self.fmt = fmt
        self.block = block           # for a text block: (file, start marker, end marker)


def C(cid, statement, how, *places, fmt=None):
    return Claim(cid, statement, how, places, fmt)


def registry():
    """Every registered number. A place is (file, anchor with <v> where the number is printed[, format])."""
    c = []
    A = c.append
    S4 = "session.summary()"
    FL = "session.flow (agenttrace.messages.message_flow)"
    # ---- the release: size and dating
    A(C("release.records", "Records in the Swarm Traces release", f"{S4}['records']",
        ("R", r"On the Swarm Traces release \(<v> records\)"), ("R", r"Records <v>: "), ("R", r"of <v> records undated"),
        ("S", r"The public Swarm Traces release: <v> records"), ("SUB", r"Swarm Traces release \(<v> records\)"),
        ("DS", r"gives us the logs: <v> records"), ("V", r"redacted_columns.csv, <v> records, code-traces pack")))
    A(C("release.payloads", "Payload records (code the agents ran)", f"{S4}['kinds']['payload']",
        ("R", r"Records [\d,]+: <v> payloads"), ("R", r"responses for <v> payloads"), ("S", r"% of <v> payloads given"),
        ("IX", r"% of <v> payloads given")))
    A(C("release.recovered_texts", "Recovered-text records", f"{S4}['kinds']['recovered_text']", ("R", r"payloads \(code agents ran\), <v> recovered texts")))
    A(C("release.responses", "Response records", f"{S4}['kinds']['response']", ("R", r"recovered texts, <v> responses"), ("R", r"Success <v> responses for")))
    A(C("release.dated_records", "Records given a time", f"{S4}['timed']", ("R", r"In all, <v> records are dated")))
    A(C("release.undated_records", "Records with no time", f"{S4}['time_test']['untimed']", ("R", r"Time <v> of [\d,]+ records undated")))
    A(C("release.dated_share", "Share of records given a time", "dated_records / records",
        ("R", r"alone one can date <v>% of records", "pct"), ("R", r"Swarm Tracer dated <v>% of the Hugging Face swarm's records", "pct"),
        ("R", r"describes the dated <v>%", "pct")))
    A(C("release.undated_share", "Share of records with no time", "undated_records / records",
        ("R", r"The largest gap is time: <v>% of the records cannot be placed", "pct"), ("S", r"Time: <v>% of records cannot be placed", "pct")))
    A(C("release.payload_dated_share", "Share of payloads given an estimated time", f"{S4}['actions']['dated'] / payloads",
        ("R", r"it gives estimated times to <v>% of payloads", "pct"), ("R", r"the tool estimates times for <v>% of payloads", "pct"),
        ("S", r"<v>% of [\d,]+ payloads given an estimated time", "pct"), ("IX", r"<v>% of [\d,]+ payloads given an estimated time", "pct"),
        ("SUB", r"it gives estimated times to <v>% of payloads", "pct"), ("DS", r"<v> percent of payloads get an estimated time", "pct_word")))
    A(C("release.block1_records", "Records in the first payload block", f"{S4}['time_test']['blocks'][0]['records']", ("R", r"the first payload block \(<v> records")))
    A(C("release.block1_timestamps", "Timestamps the first payload block is fitted from", "…['blocks'][0]['timestamp_points']",
        ("R", r"records, <v> timestamps\) passes"), ("IX", r"fitted from <v> timestamps")))
    A(C("release.block1_spearman", "Rank correlation of the first payload block", "…['blocks'][0]['spearman']", ("R", r"timestamps\) passes with ρ = <v>", "f3")))
    A(C("release.block1_median_error_h", "Median fit error of the first payload block (h)", "…['blocks'][0]['fit_error_hours_median']",
        ("R", r"ρ = [\d.]+, a median error of <v> h", "f2"), ("R", r"the payload block, whose median error is <v> h", "f2")))
    A(C("release.block1_p90_error_h", "90th-percentile fit error of the first payload block (h)", "…['blocks'][0]['fit_error_hours_p90']",
        ("R", r"a 90th-percentile error of <v> h, and the next", "f1")))
    A(C("release.tokens_used_5_plus", "Tokens used five or more times", f"{S4}['identity_test']['tokens_used_5_plus']",
        ("R", r"\d+ of the <v> tokens used five or more times"), ("R", r"\d+ of <v> frequent tokens change role")))
    A(C("release.tokens_one_role", "Of those, tokens that keep one role in 90% of uses", "…['identity_test']['with_one_role_90pct']",
        ("R", r"<v> of the \d+ tokens used five or more times keep one role")))
    A(C("release.tokens_changing_role", "Frequent tokens that change role", "tokens_used_5_plus - with_one_role_90pct", ("R", r"<v> of \d+ frequent tokens change role")))
    A(C("release.named_tokens", "Named tokens and names (actors that are not anonymous runs)", f"{S4}['actions']['named_actors']",
        ("R", r"so <v> tokens become \d+ agents"), ("S", r"<v> named tokens and names against about")))
    A(C("release.unattributed_action_share", "Share of actions with no named actor", f"{S4}['actions']['unattributed'] / ['total']",
        ("S", r"<v>% of actions carry no named actor", "pct")))
    A(C("release.harm_timed", "Timed harmful actions", f"{S4}['harm_events_timed']",
        ("R", r"registry mailbox use \(<v> timed actions\)"), ("R", r"share of the <v> timed harmful actions"), ("IX", r"of the <v> dated harmful actions")))
    # ---- the release: messages
    msgs = [("R", r"it finds <v> such write-then-read deliveries, \d+ of them between"), ("R", r"All <v> write-then-read deliveries passed through dataset repositories"), ("R", r"Of the <v>, \d+ are labelled true and \d+ undecidable"),
            ("R", r"reconstructed <v> write-then-read deliveries \(\d+ between named tokens"), ("R", r"\d+ of <v> deliveries rest on one, none between named tokens"),
            ("RM", r"The Swarm Traces release has <v> write-then-read deliveries \(\d+ between named tokens\)"),
            ("S", r"published <v> write-then-read deliveries, \d+ between \d+ named tokens in \d+ pairs"), ("S", r"\) \d+ → \d+ → \d+ → \d+ → <v>; a reviewer defends"), ("IX", r"published <v> write-then-read deliveries \(\d+ between named tokens"),
            ("SUB", r"it finds <v> write-then-read deliveries \(not messages"), ("DS", r"That leaves <v> deliveries in all"),
            ("V", r"On the audit the <v> score \d+ of \d+ decidable"), ("V", r"The v2\.3\.0 rule reports <v> write-then-read deliveries, \d+ between named tokens"),
            ("V", r"\| all deliveries \| <v> \("),
            ("S", r"through Hugging Face datasets: all <v> deliveries\."), ("S", r"\d+ of <v> deliveries sit on places the redaction may have merged"),
            # v2.3.0 places
            ("RM", r"moved the Swarm Traces count from 9 to <v> write-then-read deliveries"), ("RM", r"The v2\.3\.0 rule reports <v> write-then-read deliveries \(one actor wrote"),
            ("RM", r"on the release that is \d+ of <v>, and a second form of the test"),
            ("KI", r"The release now has <v> write-then-read deliveries, \d+ between named tokens \(unchanged\)"),
            ("KI", r"The rule now reports <v> write-then-read deliveries, \d+ between named tokens, none where"),
            ("LIM", r"\(\d+ of <v> on the Swarm Traces release do\)"), ("HW", r"which is \d+ of <v> on the Swarm Traces release"),
            ("R", r"on the release that is \d+ of <v>\. Earlier versions"), ("S", r"On the incident itself: <v> write-then-read deliveries, \d+ between named tokens")]
    A(C("release.deliveries", "Messages (deliveries) the final rule reports on the release", "session.flow['deliveries']", *msgs))
    named = [("R", r"such write-then-read deliveries, <v> of them between \d+ named tokens in \d+ sender.receiver pairs"), ("R", r"Between named tokens the tool finds <v> deliveries among"),
             ("R", r"reconstructed \d+ write-then-read deliveries \(<v> between named tokens"),
             ("R", r"Between estimated agents, \d+ of the <v> named deliveries fall inside"),
             ("RM", r"The Swarm Traces release has \d+ write-then-read deliveries \(<v> between named tokens\)"),
             ("S", r"published \d+ write-then-read deliveries, <v> between \d+ named tokens in"), ("S", r"likely one agent: \d+ of the <v> named deliveries fall inside one agent"), ("S", r"with dating error, the <v> named deliveries range"),
             ("IX", r"published \d+ write-then-read deliveries \(<v> between named tokens"), ("SUB", r"using what was written\), <v> of them between \d+ named tokens in \d+ sender-receiver pairs"), ("SUB", r"merged into estimated agents, \d+ of the <v> named deliveries fall inside one agent"),
             ("DS", r"<v> of them between (?:\w+ )?named tokens, in", "word"),
             ("V", r"\| between two named tokens \| <v> \| \d+ of \d+ \|"), ("V", r"The v2\.3\.0 rule reports \d+ write-then-read deliveries, <v> between named tokens"),
             ("V", r"\| between two named tokens \| <v> \|"), ("V", r"Of the <v> between named tokens all \d+ were read as a write"),
             # v2.3.0 places
             ("RM", r"still <v> between named tokens and still"), ("KI", r"The release now has \d+ write-then-read deliveries, <v> between named tokens \(unchanged\)"),
             ("S", r"On the incident itself: \d+ write-then-read deliveries, <v> between named tokens")]
    A(C("release.named_deliveries", "Messages between two named tokens", "session.flow['deliveries_between_named_actors']", *named))
    A(C("release.named_pairs", "Sender-receiver pairs between named tokens", "session.flow['named_actor_pairs']",
        ("R", r"of them between \d+ named tokens in <v> sender.receiver pairs; in none does the reader"), ("R", r"among \d+ tokens in <v> sender.receiver pairs \(Figure 2\)"),
        ("R", r"Who talked to whom: the <v> sender.receiver pairs"), ("R", r"\(the v2\.3\.0 list has <v> pairs between \d+ tokens, as v2\.2\.0 had"),
        ("RM", r"Every write-then-read delivery between named tokens in the Swarm Traces release \(<v> sender-receiver pairs; the other"),
        ("S", r"named tokens in <v> pairs, all through"), ("SUB", r"named tokens in <v> sender-receiver pairs"),
        ("DS", r"named tokens, in <v> sender-receiver pairs", "word")))
    A(C("release.named_message_tokens", "Named tokens that take part in a message", "distinct senders and receivers of the named deliveries",
        ("R", r"\d+ of them between <v> named tokens in"), ("R", r"Between named tokens the tool finds \d+ deliveries among <v> tokens in"), ("R", r"\(the v2\.3\.0 list has \d+ pairs between <v> tokens, as v2\.2\.0 had"),
        ("S", r"deliveries, \d+ between <v> named tokens in \d+ pairs"), ("SUB", r"\d+ of them between <v> named tokens"),
        ("DS", r"of them between <v> named tokens, in", "word")))
    A(C("release.deliveries_hf_dataset", "Messages that passed through Hugging Face datasets", "session.flow['channel_types']['hf_dataset']['deliveries']",
        ("R", r"All <v> write-then-read deliveries passed through dataset repositories"), ("S", r"through Hugging Face datasets: all <v> deliveries\.")))
    A(C("release.deliveries_board", "Messages that passed through board folders", "session.flow['channel_types']['board']['deliveries']"))
    A(C("release.deliveries_on_merged_places", "Messages that rest on an owner-only (merged) place", "session.flow['coarse_channel_deliveries']",
        ("R", r"<v> of \d+ deliveries rest on one, none between named tokens"), ("S", r"<v> of \d+ deliveries sit on places the redaction may have merged")))
    A(C("release.places", "Places (channels) found in the release", "session.flow['channels']",
        ("R", r"\d+ of the <v> places were written three or more times"), ("DD", r"of <v> channels, \d+ have ≥3 writes")))
    A(C("release.places_written_never_read", "Places written three or more times with no message out of them",
        "count of session.flow['_channels'] with writes >= 3 and never_read",
        ("R", r"<v> of the [\d,]+ places were written three or more times"), ("DD", r"of [\d,]+ channels, <v> have ≥3 writes"),
        ("DD", r"<v> never-read dead-drop channels")))
    A(C("release.dataset_write_records", "Records that write to a Hugging Face dataset", f"{S4}['intents']['hf_dataset_write']",
        ("R", r"Of the <v> dataset-write records")))
    A(C("release.latency_median_h", "Median gap from write to read (h)", "session.flow['latency_hours']['median']",
        ("R", r"The median gap from write to read was <v> h", "f1")))
    A(C("release.latency_p90_h", "90th-percentile gap from write to read (h)", "session.flow['latency_hours']['p90']",
        ("R", r"the 90th percentile <v> h\. Most activity", "f0")))
    A(C("release.place_actors_anonymous", "Actors on places that are single anonymous runs", "session.flow['actors_on_channels']['run']",
        ("R", r"and <v> such runs appear on places, against \d+ tokens"), ("R", r"Agent field redacted; <v> anonymous runs against")))
    A(C("release.place_actors_tokens", "Actors on places that are tokens", "session.flow['actors_on_channels']['token']",
        ("R", r"such runs appear on places, against <v> tokens"), ("R", r"anonymous runs against <v> tokens on places")))
    A(C("release.grade_direct", "Messages graded direct", "session.flow['deliveries_by_grade']", ("V", r"On the release: <v> direct")))
    A(C("release.grade_inferred", "Messages graded inferred", "session.flow['deliveries_by_grade']", ("V", r"On the release: \d+ direct, <v> inferred")))
    A(C("release.grade_weak", "Messages graded weak", "session.flow['deliveries_by_grade']", ("V", r"On the release: \d+ direct, \d+ inferred, <v> weak")))
    A(C("release.first_message_time", "Read time of the first message between named tokens", "session.flow['first_named_delivery']['read_time']",
        ("R", r"The first delivery between two named tokens came at <v> \(", "hm_on_md"), ("R", r"different agents moves from <v> to", "hm_on_md"),
        ("CN", r"Tokens are not agents: [^|]*\| First message <v> to", "d_mon_hm")))
    A(C("release.first_message_write_time", "Write time of the first message", "…['first_named_delivery']['write_time']",
        ("R", r"token 170 posted to a dataset at <v>, and token 169", "hm_on_md")))
    A(C("release.first_message_write_id", "Write record of the first message", "…['first_named_delivery']['write_id']", ("R", r"The first delivery between named tokens is <v> to R\d+")))
    A(C("release.first_message_read_id", "Read record of the first message", "…['first_named_delivery']['read_id']", ("R", r"The first delivery between named tokens is R\d+ to <v>:")))
    A(C("release.first_message_harm_share", "Share of timed harm still to come at the first message", "session.flow['harm_share_after_first_named_delivery']",
        ("R", r"between two named tokens came at [^(]+\(<v>% to come\)", "pct"), ("S", r"First delivery between tokens <v>%", "pct")))
    # ---- spread
    A(C("release.programs_shared", "Programs run under more than one named token", "session.flow['content_families_moving']",
        ("R", r"<v> programs were run under more than one named token"), ("V", r"\d+ of the <v> shared programs remain signs")))
    A(C("release.programs_nonroutine", "Shared programs that touch a place or do harm (not routine)", "count of session.flow['_content_spread'] with routine false",
        ("R", r"more than one named token; <v> of them touch a place"), ("V", r"<v> of the \d+ shared programs remain signs")))
    A(C("release.tokens_seen_then_used", "Tokens seen as data before they authenticate", f"{S4}['list_totals']['seen_then_used']",
        ("R", r"<v> tokens appear as data inside a record before")))
    A(C("release.shared_names_separate_records", "Place names used by two identities in separate records", "rec['shared_places'] with same_record false",
        ("R", r"The tool also finds <v> place names used by two identities in separate records")))
    A(C("release.carried_tokens", "Cases of one identity holding another's token", f"{S4}['list_totals']['carried_edges']",
        ("R", r"separate records and <v> cases in which one identity holds another's token")))
    # ---- replay
    ev = "agenttrace.evaluate.evaluate(session)"
    A(C("release.first_dataset_write_time", "First Hugging Face dataset write", f"{ev}['replay_signs']",
        ("R", r"\(R0005279\) came at <v> with", "hm_on_md")))
    A(C("release.first_dataset_write_share", "Harm still to come at the first dataset write", f"{ev}['replay_signs']",
        ("R", r"\(R0005279\) came at [^w]+with <v>% still to come", "pct")))
    A(C("release.volume_alarm_hour", "Hour whose count set off the volume alarm", f"{ev}['baselines']['rate_alarm_all_actions']['hour']",
        ("R", r"The volume alarm fired at the end of the <v> hour", "hm")))
    A(C("release.volume_alarm_share", "Harm still to come when the volume alarm fired", f"{ev}['baselines']['rate_alarm_all_actions']['harm_share_after']",
        ("R", r"a volume alarm that fires with <v>% of the harm still to come", "pct"), ("R", r"hour, with <v>% to come, on both", "pct"),
        ("R", r"\(the 12-hour volume alarm: <v>%\)", "pct"),
        ("S", r"Volume alarm \(12 h history\) <v>%", "pct"),
        ("SUB", r"after a plain volume alarm \(<v>%\)", "pct"), ("DS", r"the volume alarm with a longer history at <v> percent", "pct_word")))
    A(C("release.carried_sign_time", "First time one token holds another's token", f"{ev}['replay_signs']", ("R", r"one token holding another's token at <v> \(", "hm")))
    A(C("release.carried_sign_share", "Harm still to come at the carried-token sign", f"{ev}['replay_signs']",
        ("R", r"holding another's token at [\d:]+ \(<v>% to come\)", "pct"), ("R", r"signs of shared control fired with \d+.<v>% of the timed harmful", "pct"),
        ("R", r"On the incident, signs of shared control came late \(\d+.<v>% of harm", "pct"), ("S", r"Signs of shared control \d+.<v>%", "pct"),
        ("S", r"the earliest with \d+% of harm to come, not <v>%", "pct"), ("IX", r"\d+.<v>% of the [\d,]+ dated harmful actions were still to come", "pct"),
        ("SUB", r"signs of shared control fired with only \d+.<v>%", "pct"), ("DS", r"fire when \w+ to <v> percent of the harm", "pct_word")))
    A(C("release.shared_name_sign_time", "First time two tokens share a place name", f"{ev}['replay_signs']", ("R", r"two tokens sharing a name at <v> \(", "hm")))
    A(C("release.shared_name_sign_share", "Harm still to come at the shared-name sign", f"{ev}['replay_signs']",
        ("R", r"sharing a name at [\d:]+ \(<v>% to come\)", "pct"), ("R", r"signs of shared control fired with <v>.\d+% of the timed harmful", "pct"),
        ("R", r"On the incident, signs of shared control came late \(<v>.\d+% of harm", "pct"), ("S", r"Signs of shared control <v>.\d+%", "pct"),
        ("IX", r"<v>.\d+% of the [\d,]+ dated harmful actions were still to come", "pct"), ("SUB", r"signs of shared control fired with only <v>.\d+%", "pct"),
        ("DS", r"fire when <v> to [\w-]+ percent of the harm", "pct_word")))
    A(C("release.program2_time", "First program run by a second token", f"{ev}['replay_signs']", ("R", r"a program run by a second token, fired at <v> \(", "hm_on_md")))
    A(C("release.program2_share", "Harm still to come at the first reused program", f"{ev}['replay_signs']", ("R", r"a program run by a second token, fired at [^(]+\(<v>% to come\)", "pct")))
    A(C("release.group3_time", "First group of three tokens linked by messages", f"{ev}['replay_signs']", ("R", r"a group of three tokens linked by deliveries at <v> on [A-Z][a-z]+ \d+ \(", "hm")))
    A(C("release.group3_share", "Harm still to come at the first group of three", f"{ev}['replay_signs']", ("R", r"linked by deliveries at [\d:]+ on [A-Z][a-z]+ \d+ \(<v>% to come\)", "pct")))
    A(C("release.robust_sigma_h", "Sigma of the time-error test (h)", f"{ev}['robustness']['sigma_hours']", ("R", r"with σ = <v> h \(the largest", "f1")))
    A(C("release.robust_p90_h", "Largest 90th-percentile fit error of any dated block (h)", f"{ev}['robustness']['from_p90_error_hours']",
        ("R", r"fit error of any dated block, <v> h, divided", "f2")))
    A(C("release.robust_dataset_write_low", "First dataset write under time error: low end", f"{ev}['robustness']", ("R", r"first dataset write stays between <v>% and", "pct")))
    A(C("release.robust_dataset_write_high", "First dataset write under time error: high end", f"{ev}['robustness']", ("R", r"first dataset write stays between \d+% and <v>% to come", "pct")))
    A(C("release.robust_first_message_low", "First message under time error: low end", f"{ev}['robustness']", ("R", r"and the first delivery between <v>% and", "pct")))
    A(C("release.robust_first_message_high", "First message under time error: high end", f"{ev}['robustness']", ("R", r"and the first delivery between \d+% and <v>%", "pct")))
    A(C("release.robust_shared_control_high", "Shared-control signs under time error: highest upper end", f"{ev}['robustness']",
        ("R", r"shared-control signs stay at or below <v>%", "pct")))
    A(C("release.robust_max_shift_points", "Largest move of any signal's share when shifted one hour (points)", f"{ev}['robustness']",
        ("R", r"moves its share by at most <v> points", "f0")))
    A(C("release.milestones", "Moments compared with times the investigators published", f"{ev}['external']['milestones']",
        ("R", r"<v> moments it dates fall within", "word"), ("R", r"<v> estimated event times fall within", "word"), ("R", r"We compare <v> moments in our reconstruction", "word"),
        ("R", r"the external timing check covers <v> moments", "word"), ("S", r"largest gap between <v> moments"), ("IX", r"largest gap between <v> moments", "word"),
        ("SUB", r"where the release could date 3%, <v> moments it dates fall within", "word"), ("DS", r"And <v> key moments land within", "word")))
    A(C("release.milestone_max_diff_h", "Largest difference between an estimated and a published time (h)", "max |difference_h| over the milestones",
        ("R", r"the largest difference is <v> h", "f2"), ("R", r"moments it dates fall within about <v> hours", "f1"), ("R", r"event times fall within about <v> hours", "f1"),
        ("R", r"Every matched moment falls within about <v> hours", "f1"), ("S", r"<v> h largest gap between", "f1"), ("IX", r"<v> h largest gap between", "f1"),
        ("SUB", r"fall within about <v> hours", "f1")))
    A(C("release.per_day_rank_correlation", "Rank correlation of actions per day with Hugging Face's counts", f"{ev}['external']['per_day']['rank_correlation']",
        ("R", r"Spearman ρ = <v> over 5 days", "f1"), ("S", r"ρ = <v> our actions per day", "f1")))
    A(C("release.per_day_first_share", "Our share of actions on July 9", f"{ev}['external']['per_day']['our_share'][0]", ("R", r"Our July 9 share is lower \(<v>% against", "pct")))
    A(C("release.first_message_hours_before_surge", "Hours from the first named message to the surge METR dates", "METR's surge time (incident_milestones.json) minus the first message's read time",
        ("R", r"on July 11 \(\d+% to come\), <v> hours before the surge", "word"), ("R", r"A write-then-read link between two tokens fired <v> hours before the surge", "word"),
        ("IX", r"through a shared place fired <v> hours before the surge", "word"), fmt="f0"))
    A(C("release.counting_naive", "Named messages under naive counting", f"{ev}['counting_rules'][0]"))
    A(C("release.counting_naive_pairs", "Named pairs under naive counting", f"{ev}['counting_rules'][0]"))
    # ---- identity
    un = "agenttrace.units.units_summary(session, 'agent')"
    A(C("release.agents", "Estimated agents after merging tokens on direct evidence", f"{un}['agents']", ("R", r"so \d+ tokens become <v> agents")))
    A(C("release.merged_tokens", "Tokens merged into multi-token agents", "sum of sizes of fx_whatif.whatif(session,'estimate')['groups']",
        ("R", r"Here it merges <v> tokens into", "int")))
    A(C("release.merged_agents", "Estimated agents that hold more than one token", f"{un}['merged_agents']", ("R", r"Here it merges \d+ tokens into <v> estimated agents", "word")))
    A(C("release.largest_agent_tokens", "Tokens held by the largest estimated agent", "size of the largest group",
        ("R", r"The <v> tokens the identity step merges \(169", "word")))
    A(C("release.largest_agent_records", "Records under the largest estimated agent", "records of the largest group", ("R", r"1623, 1069; <v> records\)")))
    A(C("release.agent_messages", "Messages between different estimated agents", f"{un}['messages']"))
    A(C("release.agent_messages_inside", "Named messages that fall inside one estimated agent", f"{un}['inside_one_agent']",
        ("R", r"Between estimated agents, <v> of the \d+ named deliveries fall inside one agent"),
        ("S", r"likely one agent: <v> of the \d+ named deliveries fall inside one agent"), ("SUB", r"merged into estimated agents, <v> of the \d+ named deliveries fall inside one agent"),
        ("V", r"\(\d+ between agents, <v> inside one agent\), 0 where the reader is shown using what was written: the two added"),
        ("DS", r"<v> of those \w+ are between tokens that Swarm Tracer estimates belong to one agent", "word")))
    A(C("release.agent_first_message_time", "First message between different estimated agents", f"{un}['first_message']['time']",
        ("R", r"moves from [^.]+ to <v>, with", "hm_on_md")))
    A(C("release.agent_first_message_share", "Harm still to come at the first message between agents", f"{un}['first_message']['harm_share_after']",
        ("R", r"on July \d+, with <v>% of the harm still to come", "pct")))
    A(C("release.agent_carried_sign_time", "Carried-token sign, counted by agent", f"{un}['signs']", ("R", r"one token holding another.s at <v> \(", "hm_on_md")))
    A(C("release.agent_carried_sign_share", "Harm still to come at the carried-token sign, by agent", f"{un}['signs']",
        ("R", r"holding another.s at [^(]+\(<v>% to come\)", "pct"), ("S", r"the earliest with <v>% of harm to come", "pct")))
    A(C("release.agent_shared_name_sign_time", "Shared-name sign, counted by agent", f"{un}['signs']", ("R", r"two tokens sharing a name on <v> \(", "md_at_hm")))
    A(C("release.agent_shared_name_sign_share", "Harm still to come at the shared-name sign, by agent", f"{un}['signs']",
        ("R", r"sharing a name on [^(]+\(<v>%\)", "pct")))
    # ---- audit score of the current code
    bm = "agenttrace.benchmark.score(benchmark.all_links(session), audit)"
    A(C("release.audit_reported_true", "Reported links the audit read as true", f"{bm}['groups']['all']['true']",
        ("R", r"Of the \d+, <v> are labelled true and \d+ undecidable"), ("V", r"On the audit the \d+ score <v> of \d+ decidable"), ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| <v> of \d+ \|"),
        ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| <v> of")))
    A(C("release.audit_reported_false", "Reported links the audit read as false", f"{bm}['groups']['all']['false']"))
    A(C("release.audit_reported_unclear", "Reported links the audit could not decide", f"{bm}['groups']['all']['unclear']",
        ("R", r"labelled true and <v> undecidable"), ("V", r"\| all deliveries \| \d+ \(<v> unclear\)"),
        ("V", r"So \d+ of the \d+ are labelled true and <v> unclear"), ("KI", r"<v> of the \d+ are labelled unclear, and the labels are one reader"),
        ("S", r"and <v> of the \d+ are labelled unclear\.")))
    A(C("release.audit_decidable", "Reported links the audit could decide", f"{bm}['precision']['n']",
        ("V", r"On the audit the \d+ score \d+ of <v> decidable"), ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| \d+ of <v> \|"), ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| \d+ of <v> \|")))
    A(C("release.audit_precision", "Precision of the reported links on the audit", f"{bm}['precision']['value']",
        ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| \d+ of \d+ \| <v>% \(", "pct"), ("V", r"\| all deliveries \| [^|]+\| [^|]+\| <v>% \(", "pct")))
    A(C("release.audit_precision_low", "Precision, low end of the 95% range", f"{bm}['precision']['ci'][0]",
        ("V", r"\(\d+ are unclear; 95% range <v>%", "pct"), ("V", r"\| all deliveries \| \d+ \(\d+ unclear\) \| \d+ of \d+ \| \d+% \(<v>%", "pct"), ("V", r"\| all deliveries \| [^|]+\| [^|]+\| \d+% \(<v>%", "pct")))
    A(C("release.audit_precision_high", "Precision, high end of the 95% range", f"{bm}['precision']['ci'][1]",
        ("V", r"\(\d+ are unclear; 95% range \d+%.<v>%", "pct"), ("V", r"\| all deliveries \| [^|]+\| [^|]+\| \d+% \(\d+%.<v>%\)", "pct")))
    A(C("release.audit_named_true", "Named links read as true", f"{bm}['groups']['named_named']", ("V", r"\| between two named tokens \| \d+ \| <v> of"), ("V", r"\| between two named tokens \| \d+ \| <v> of \d+ \|")))
    A(C("release.audit_run_reported", "Reported links with an anonymous run on one side", f"{bm}['groups']['involves_run']['reported']",
        ("V", r"\| an anonymous run on one side \| <v> \("), ("RM", r"the other <v> of the \d+ deliveries have an anonymous run on one side"),
        ("R", r"\(Figure 2\); the other <v> have an anonymous run on one side")))
    A(C("release.audit_run_true", "Of those, read as true", f"{bm}['groups']['involves_run']['true']",
        ("V", r"\| an anonymous run on one side \| [^|]+\| <v> of"), ("V", r"of those with an anonymous endpoint <v> of \d+")))
    A(C("release.audit_run_decidable", "Of those, decidable", f"{bm}['groups']['involves_run']['precision']['n']",
        ("V", r"\| an anonymous run on one side \| [^|]+\| \d+ of <v> \|"), ("V", r"of those with an anonymous endpoint \d+ of <v>")))
    A(C("release.audit_inferred_true", "Inferred-grade links read as true", f"{bm}['by_grade']['inferred']"))
    A(C("release.audit_weak_true", "Weak-grade links read as true", f"{bm}['by_grade']['weak']", ("V", r"On the audit: weak <v> of \d+ \(")))
    A(C("release.audit_weak_decidable", "Weak-grade links decidable", f"{bm}['by_grade']['weak']", ("V", r"On the audit: weak \d+ of <v> \(")))
    ia = "agenttrace.benchmark.independent_agreement(session, audit)['decided']"
    A(C("release.second_method_agree", "Links where the second method agrees with the labels", f"{ia}['agreement']['k']", ("V", r"raw agreement \d+% \(<v> of")))
    A(C("release.second_method_decided", "Decided links the second method was compared on", f"{ia}['n']",
        ("V", r"raw agreement \d+% \(\d+ of <v>;"), ("V", r"\(unclear left out, <v> links\)")))
    A(C("release.second_method_agreement", "Raw agreement of the second method", f"{ia}['agreement']['value']", ("V", r"raw agreement <v>% \(", "pct")))
    A(C("release.second_method_kappa", "Cohen's kappa of the second method against the labels", f"{ia}['kappa']", ("V", r"Cohen.s kappa <v> \(the labels now hold", "f2")))
    # ---- board, attribution, insider findings
    bd = "agenttrace.board.board(session)['funnel']"
    A(C("release.board_folders", "Board folders named in the release", f"{bd}['folders']",
        ("R", r"of <v> board folders the release shows"), ("R", r"Unread places Of <v> board folders")))
    A(C("release.board_folders_written", "Board folders with a writer seen", f"{bd}['written']",
        ("R", r"the release shows a writer for <v>, a reader"), ("R", r"board folders, <v> show a writer")))
    A(C("release.board_folders_read", "Board folders with a reader seen", f"{bd}['read']",
        ("R", r"a writer for \d+, a reader for <v> and both"), ("R", r"show a writer, <v> a reader")))
    A(C("release.board_folders_both", "Board folders with both a writer and a reader seen", f"{bd}['both']",
        ("R", r"a reader for \d+ and both for <v>\."), ("R", r"a reader, <v> both")))
    A(C("release.board_folders_read_only", "Board folders with a reader but no writer seen", f"{bd}['read_only']"))
    A(C("release.board_folders_written_only", "Board folders with a writer but no reader seen", f"{bd}['written_only']"))
    at = "agenttrace.attribution.attribution(session)"
    A(C("release.anonymous_runs", "Anonymous runs (actions with no token)", f"{at}['runs']"))
    A(C("release.attributed_runs", "Anonymous runs linked to a named actor at any band", f"sum of {at}['bands'] high+medium+low"))
    A(C("release.attributed_share", "Share of anonymous runs linked to a named actor", "attributed_runs / anonymous_runs", fmt="pct1"))
    A(C("release.attributed_high", "Anonymous runs linked at the high band", f"{at}['bands']['high']['runs']"))
    A(C("release.attributed_medium", "Anonymous runs linked at the medium band", f"{at}['bands']['medium']['runs']"))
    A(C("release.attributed_low", "Anonymous runs linked at the low band", f"{at}['bands']['low']['runs']"))
    A(C("release.attribution_holdout_high_precision", "Hold-out precision of the high band", f"{at}['holdout']['bands']['high']['precision']", fmt="pct1"))
    A(C("release.attribution_holdout_medium_precision", "Hold-out precision of the medium band", f"{at}['holdout']['bands']['medium']['precision']", fmt="pct1"))
    ins = "agenttrace.sensitivity.insiders(session)"
    A(C("release.insider_findings", "Insider findings scored against the release", f"{ins}['total']", ("RM", r"a scoring of <v> insider findings")))
    A(C("release.insider_recovered", "Insider findings the tool recovers", f"{ins}['counts']['recovered']"))
    A(C("release.insider_partly", "Insider findings partly visible", f"{ins}['counts']['partly']"))
    A(C("release.insider_invisible", "Insider findings the records cannot show", f"{ins}['counts']['invisible']"))
    # ---- wiki logs
    A(C("wiki.records", "Records in the collusion.wiki logs", f"{S4}['records']", ("R", r"responses <v>: [\d,]+ page revisions")))
    A(C("wiki.revisions", "Page revisions", f"{S4}['kinds']['revisions']", ("R", r"<v> page revisions")))
    A(C("wiki.deletes", "Deletes", f"{S4}['kinds']['delete']", ("R", r"page revisions, <v> deletes")))
    A(C("wiki.probes", "Probes", f"{S4}['kinds']['probe']", ("R", r"deletes, <v> probes")))
    A(C("wiki.other_events", "Other events (saves and reverts)", "records - revisions - deletes - probes", ("R", r"probes, <v> other events")))
    A(C("wiki.named_actors", "Named actors in the wiki logs", f"{S4}['actions']['named_actors']", ("R", r"on the wiki logs \(<v> named actors")))
    A(C("wiki.span_days", "Days the wiki logs span", "last - first dated record, in days", ("R", r"named actors over <v> days\)", "f0")))
    cr = "agenttrace.evaluate.counting_ablation(...)"
    A(C("wiki.counting_naive", "Wiki messages under naive counting", f"{cr}[0]['messages']",
        ("R", r"Over all the wiki logs they cut <v> apparent messages"), ("S", r"the rules cut <v> apparent messages")))
    A(C("wiki.counting_final", "Wiki messages after all three counting rules", f"{cr}[-1]['messages']",
        ("R", r"apparent messages to <v>\. On the Swarm Traces release the three counting rules"), ("S", r"apparent messages to <v>\.")))
    A(C("wiki.overwrites", "Wiki edits counted as overwrites", "session.flow['overwrites']",
        ("R", r"On the wiki logs, <v> edits replaced another agent's edit"), ("RM", r"In the wiki logs this removes <v> edits")))
    A(C("wiki.top_pair_messages", "Messages in the LinkHelper771 / AgentMassPointer13 exchange", "session.conversation(...)['a_to_b'] + ['b_to_a']",
        ("R", r"exchange on June 18 contains <v> messages and")))
    A(C("wiki.top_pair_overwrites", "Overwrites in that exchange", "session.conversation(...)['overwrites']", ("R", r"contains \d+ messages and <v> overwrites")))
    # ---- the audit file itself (no dataset needed)
    af = "agenttrace/claims/audited_links.json"
    A(C("audit.links", "Links in the hand audit", f"len({af}['links'])",
        ("R", r"Audits of <v> links cut a first count"), ("R", r"on the release \(<v> in all, both records read\)"), ("R", r"the audit of <v> links \(Section 3.2\)"),
        ("S", r"Audit of the release.s links \(<v> read by one reader"), ("SUB", r"after audits of <v> links cut a first count"),
        ("V", r"Score on the <v> audited links \(labels as corrected"), ("V", r"Score on the <v> audited links")))
    A(C("audit.true_links", "Links the audit read as true messages", "label == true_message",
        ("V", r"labels as corrected in v2\.2\.0: <v> true, \d+ read-then-post")))
    A(C("audit.read_then_post", "Links where the write only GETs the place, then POSTs elsewhere", "label == false_write", ("V", r"\d+ true, <v> read-then-post")))
    A(C("audit.read_is_write", "Links where the read is itself a write", "label == read_not_a_read", ("V", r"read-then-post, <v> \"read is a write\"")))
    A(C("audit.downloads", "Links where the write only fetches (LFS download, urlopen)", "label == false_write_lfs_or_urlopen", ("V", r", <v> downloads, urlopen or upload probes")))
    A(C("audit.different_repo", "Links on different repositories under one owner", "label == different_repo", ("V", r"upload probes, <v> different repositories")))
    A(C("audit.unclear", "Links the audit could not decide", "label == unclear", ("V", r"different repositories, <v> unclear, \d+ reader holding")))
    A(C("audit.first_count", "Named links the first version (v1.1.0) reported", "reported_v110 true",
        ("R", r"cut a first count of <v> to 19, then 23, then 9"), ("R", r"Of the <v> an early version reported between named tokens"), ("S", r"Counts fell <v> → \d+ → \d+ → \d+ over three audits"),
        ("S", r"\) <v> → \d+ → \d+ → \d+ → \d+; a reviewer defends"), ("SUB", r"cut a first count of <v> to 19, then 23, then 9"), ("DS", r"A first count said <v>, then 19"),
        ("V", r"every link between named tokens that v1.1.0 reported on the Swarm Traces release \(<v>\)")))
    # ---- saved runs
    vs = "reports/validation/summary.json"
    A(C("validation.coordinated_runs", "Simulated coordinated swarms scored", f"{vs}['coordinated_runs']",
        ("R", r"Scores on <v> simulated coordinated swarms"), ("V", r"across the <v> coordinated swarms the tool finds"), ("V", r"so <v> coordinated swarms of")))
    A(C("validation.benign_runs", "Simulated benign swarms scored", f"{vs}['benign_runs']",
        ("R", r"over settings and seeds\) and <v> benign ones"), ("V", r"### Benign baseline \(<v> swarms with no coordination\)"),
        ("S", r"no delivery between different agents in <v> original runs")))
    A(C("validation.total_runs", "Simulated swarms scored in all", "coordinated_runs + benign_runs",
        ("RM", r"scored on <v> simulated swarms"), ("IX", r"Scored on <v> simulated swarms"),
        ("SUB", r"Scored on <v> simulated swarms"), ("DS", r"We scored the tool on <v> simulated swarms", "word"), ("V", r"pooled over all <v> swarms")))
    for key, label, anchors in [
        ("msg_precision", "Message links: precision",
         {"median": [("R", r"\(original simulator\) \d+%.<v>%.\d+% / \d+%.\d+%.\d+% Message links: precision / recall \(independent"), ("S", r"original simulator \d+.<v>.\d+% / \d+.\d+.\d+%"),
                     ("SUB", r"message links reach <v>% precision"), ("DS", r"Median precision of the write-then-read links is <v> percent", "pct_word"),
                     ("V", r"and \d+%.<v>%.\d+% of the messages it reports are true")],
          "min": [("R", r"\(original simulator\) <v>%.\d+%.\d+% /"), ("V", r"and <v>%.\d+%.\d+% of the messages it reports are true")],
          "max": [("R", r"\(original simulator\) \d+%.\d+%.<v>% /"), ("V", r"and \d+%.\d+%.<v>% of the messages it reports are true")]}),
        ("msg_recall", "Message links: recall",
         {"median": [("R", r"Message links: precision / recall [^/]+/ \d+%.<v>%"), ("S", r"original simulator \d+.\d+.\d+% / \d+.<v>.\d+%"),
                     ("SUB", r"precision and <v>% recall"), ("DS", r"and recall <v> percent", "pct_word"), ("V", r"the tool finds \d+%.<v>%.\d+% of the true messages")],
          "min": [("R", r"Message links: precision / recall [^/]+/ <v>%"), ("V", r"the tool finds <v>%.\d+%.\d+% of the true messages")],
          "max": [("R", r"Message links: precision / recall [^/]+/ \d+%.\d+%.<v>%"), ("S", r"original simulator \d+.\d+.\d+% / \d+.\d+.<v>%"),
                  ("V", r"the tool finds \d+%.\d+%.<v>% of the true messages")]}),
        ("pair_precision", "Agent pairs: precision",
         {"median": [("R", r"Agent pairs that talked: precision / recall \d+%.<v>%"), ("V", r"recall, \d+%.<v>%.\d+% precision\. On the independent generator")],
          "min": [("R", r"Agent pairs that talked: precision / recall <v>%")], "max": [("R", r"Agent pairs that talked: precision / recall \d+%.\d+%.<v>% /")]}),
        ("pair_recall", "Agent pairs: recall",
         {"median": [("R", r"Agent pairs that talked: precision / recall [^/]+/ \d+%.<v>%"), ("V", r"Pairs of agents: \d+%.<v>%.\d+% recall")],
          "min": [("R", r"Agent pairs that talked: precision / recall [^/]+/ <v>%"), ("V", r"Pairs of agents: <v>%.\d+%.\d+% recall")],
          "max": [("R", r"Agent pairs that talked: precision / recall [^/]+/ \d+%.\d+%.<v>%"), ("S", r"Agent pairs that talked: precision / recall [^/]+/ \d+.\d+.<v>%"),
                  ("V", r"Pairs of agents: \d+%.\d+%.<v>% recall")]}),
        ("dating_coverage", "Estimated times inside the stated range",
         {"median": [("R", r"Estimated times inside the stated range \d+%.<v>%"), ("V", r"\d+%.<v>%.\d+% of estimated times fall inside")],
          "min": [("R", r"Estimated times inside the stated range <v>%")], "max": [("R", r"Estimated times inside the stated range \d+%.\d+%.<v>%")]}),
    ]:
        for stat, places in anchors.items():
            A(C(f"validation.{key}_{stat}", f"{label}, {stat} over the coordinated swarms", f"{vs}['overall']['{key}']['{stat}']",
                *[(p[0], p[1], p[2] if len(p) > 2 else "pct") for p in places], fmt="pct"))
    idp = f"{vs}['identity_pooled']"
    A(C("validation.identity_high_proposed", "Identity merges proposed as high, pooled", f"{idp}['high']['proposed']",
        ("R", r"right in \d+ of <v> and \d+ of \d+ pairs"), ("R", r"\(after the rule change\) \d+ of <v> /"), ("V", r"pooled over all \d+ swarms: high \d+ of <v> right"),
        ("V", r"\| high \| <v> \|"), ("S", r"10 of 240 right / \d+ of <v> right"), ("DS", r"\w+ of <v> high-confidence merges were right", "word")))
    A(C("validation.identity_high_correct", "Of those, right", f"{idp}['high']['correct']",
        ("R", r"they were right in <v> of \d+ and"), ("R", r"\(after the rule change\) <v> of \d+ /"), ("V", r"pooled over all \d+ swarms: high <v> of"),
        ("V", r"\| high \| \d+ \| <v> \|"), ("S", r"10 of 240 right / <v> of \d+ right")))
    A(C("validation.identity_medium_proposed", "Identity merges proposed as medium, pooled", f"{idp}['medium']['proposed']",
        ("R", r"and \d+ of <v> pairs\. Message links"), ("V", r"medium \d+ of <v>, but the \d+ high ones"), ("V", r"\| medium \| <v> \|")))
    A(C("validation.identity_medium_correct", "Of those, right", f"{idp}['medium']['correct']", ("V", r"medium <v> of \d+, but the \d+ high ones"), ("V", r"\| medium \| \d+ \| <v> \|")))
    A(C("validation.identity_low_proposed", "Identity merges proposed as low, pooled", f"{idp}['low']['proposed']",
        ("R", r"/ \d+ of \d+ / \d+ of <v> Original benign"), ("V", r"\| low \| <v> \|")))
    A(C("validation.identity_low_correct", "Of those, right", f"{idp}['low']['correct']", ("R", r"/ \d+ of \d+ / <v> of [\d,]+ Original benign"), ("V", r"\| low \| \d+ \| <v> \|")))
    A(C("validation.benign_messages_between_agents_max", "Most messages between different agents on any benign swarm", f"{vs}['benign']['messages_between_agents']['max']",
        ("R", r"default alert rule <v> in \d+;"), ("V", r"Messages between different agents reported: <v>;")))
    A(C("validation.benign_alert_fired", "Benign swarms where the default alert rule fired", f"{vs}['benign']['fires'] (alert-coord2)",
        ("R", r"before the fix\); fired in <v> of \d+"), ("V", r"\"Alert: 2 kinds of coordination\" in <v> of \d+"), ("V", r"On benign swarms it now fires in <v> of")))
    A(C("validation.benign_watch_fired", "Benign swarms where the watch rule fired", f"{vs}['benign']['fires'] (watch-harm)",
        ("V", r"\"Watch: first harmful sign\" in <v> of \d+")))
    A(C("variance.sigma_low_messages_low", "Named messages under 0.12 h time noise: low end of the 95% range", "reports/evaluation/count_variance.json runs['0.12']['messages'][1]",
        ("R", r"σ = 0.12 h gives <v>.\d+ deliveries"), ("S", r"the \d+ named deliveries range <v>.\d+ \(95%\)")))
    A(C("variance.sigma_low_messages_high", "Named messages under 0.12 h time noise: high end of the 95% range", "…runs['0.12']['messages'][3]",
        ("R", r"σ = 0.12 h gives \d+.<v> deliveries"), ("S", r"the \d+ named deliveries range \d+.<v> \(95%\)")))
    A(C("variance.sigma_2h_messages_low", "Named messages under 2 h time noise: low end of the 95% range", "…runs['2.0']['messages'][1]", ("R", r"σ = 2 h gives <v>.\d+,")))
    A(C("variance.sigma_2h_messages_high", "Named messages under 2 h time noise: high end of the 95% range", "…runs['2.0']['messages'][3]", ("R", r"σ = 2 h gives \d+.<v>,")))
    A(C("variance.draws", "Draws per noise level", "…runs['0.12']['draws']", ("R", r"perturbed by Gaussian noise <v> times")))
    # ---- bundled samples and the repository
    A(C("samples.benign_records", "Records in the bundled benign swarm", "lines of agenttrace/samples/benign_swarm/benign_swarm.jsonl", ("V", r"\(12 agents, <v> records\)")))
    A(C("samples.demo_records", "Records in the bundled demo swarm", "lines of agenttrace/samples/demo_swarm/demo_swarm.jsonl"))
    A(C("repo.unit_tests", "Unit tests in the test suite", "unittest discovery over agenttrace/tests"))
    A(C("repo.version", "Package version", "pyproject.toml [project] version",
        ("RM", r"swarm-tracer@v<v>", "str"), ("IX", r"swarm-tracer@v<v>", "str"), ("S", r"swarm-tracer@v<v>", "str")))
    # ---- v2.3.0: the four outside datasets (saved results in reports/external/)
    P1 = "pct1"
    ww = "reports/external/who_and_when/results.json"
    A(C("external.ww_runs", "Who&When: runs", f"{ww} totals.runs",
        ("RM", r"fired in \d+ of <v> runs of Who&When"), ("IX", r"set off the Alert rule: \d+ of <v> Who&When runs"),
        ("KI", r"fired in \d+ of <v> Who&When runs"), ("V", r"the Alert rule fired in \d+ of <v> \(Who&When\)"),
        ("R", r"\d+ of [\d,]+ \(9\.0%\) \d+ of <v> Failing agent named"), ("S", r"set off the Alert rule \(\d+ of <v>,")))
    A(C("external.ww_alert_fired", "Who&When: runs where the Alert rule fired (pack the tool picks)", f"{ww} false_alarms_all.by_rule_auto_pack['alert-coord2'].k",
        ("RM", r"fired in <v> of \d+ runs of Who&When"), ("IX", r"set off the Alert rule: <v> of \d+ Who&When runs"),
        ("KI", r"fired in <v> of \d+ Who&When runs"), ("V", r"the Alert rule fired in <v> of \d+ \(Who&When\)"),
        ("R", r"\d+ of [\d,]+ \(9\.0%\) <v> of \d+ Failing agent named"), ("S", r"set off the Alert rule \(<v> of \d+,")))
    A(C("external.ww_pairs_found", "Who&When: logged pairs the tool finds with recipients withheld", f"{ww} groups['Hand-Crafted'].who_talked_to_whom.recipients_withheld.pair_recall.k",
        ("RM", r"the tool still finds <v> of the \d+ logged sender-recipient pairs"), ("IX", r"<v> of \d+ logged sender-recipient pairs found with the recipients withheld"),
        ("KI", r"With recipients withheld the tool finds <v> of \d+ logged pairs on Who&When"), ("V", r"\| Who&When, 58 runs that name recipients \| <v> of \d+ \("),
        ("R", r"with recipients withheld it recovers <v> of \d+ logged agent pairs"), ("R", r"the tool still finds <v> of \d+ logged sender.recipient pairs in Who&When"),
        ("S", r"<v> of \d+ logged pairs of agents found with the recipients withheld"), ("SUB", r"with recipients withheld it recovers <v> of \d+ logged pairs of agents"),
        ("LIM", r"most pairs of agents that talked \(<v> of \d+ on Who&When")))
    A(C("external.ww_pairs_logged", "Who&When: logged sender-recipient pairs", f"{ww} …pair_recall.n",
        ("RM", r"the tool still finds \d+ of the <v> logged sender-recipient pairs"), ("IX", r"\d+ of <v> logged sender-recipient pairs found with the recipients withheld"),
        ("KI", r"With recipients withheld the tool finds \d+ of <v> logged pairs on Who&When"), ("V", r"\| Who&When, 58 runs that name recipients \| \d+ of <v> \("),
        ("R", r"with recipients withheld it recovers \d+ of <v> logged agent pairs"), ("R", r"the tool still finds \d+ of <v> logged sender.recipient pairs in Who&When"),
        ("S", r"\d+ of <v> logged pairs of agents found with the recipients withheld"), ("SUB", r"with recipients withheld it recovers \d+ of <v> logged pairs of agents"),
        ("LIM", r"most pairs of agents that talked \(\d+ of <v> on Who&When")))
    A(C("external.ww_pair_precision", "Who&When: share of the tool's pairs that are logged", f"{ww} …pair_precision_vs_logged",
        ("RM", r"\(<v>% of its Who&When pairs are logged", P1), ("KI", r"\(<v>% of its Who&When pairs are logged", P1),
        ("R", r"\(<v>% of its Who&When pairs are logged", P1), ("V", r"\| \d+ of \d+ \(<v>%; [\d.]+% in either direction\)", P1)))
    A(C("external.ww_pair_precision_either", "Who&When: share of the tool's pairs logged in either direction", f"{ww} …pair_precision_either_direction",
        ("RM", r"Who&When pairs are logged, <v>% in either direction", P1), ("KI", r"Who&When pairs are logged; <v>% in either direction", P1),
        ("R", r"Who&When pairs are logged; <v>% in either direction", P1), ("V", r"\| \d+ of \d+ \([\d.]+%; <v>% in either direction\)", P1)))
    A(C("external.ww_message_recall", "Who&When: logged single messages the tool finds", f"{ww} …message_recall",
        ("RM", r"the tool finds <v>% of the logged messages on Who&When", P1), ("KI", r"on MAST-Data, but <v>% and [\d.]+% of the single logged messages", P1),
        ("V", r"\| 62 of 689 \(<v>%\) \|", P1), ("R", r"It finds <v>% and [\d.]+% of the single logged messages", P1), ("S", r"\(people\) \d+ of \d+ <v>% \d+ of \d+", P1)))
    A(C("external.ww_agent_right", "Who&When: runs where the first warning sign names the labelled agent", f"{ww} attribution_all.methods.tool_first_sign.agent.k",
        ("RM", r"names the labelled agent in <v> of \d+ Who&When runs"), ("KI", r"names the labelled agent in <v> runs \("),
        ("V", r"\| the record of the tool's first warning sign \| <v> \("), ("R", r"names the labelled agent in <v> of \d+ runs \("),
        ("S", r"agent at fault named in <v> of \d+ \(chance")))
    A(C("external.ww_agent_right_share", "Who&When: that share", f"{ww} …tool_first_sign.agent k / n",
        ("RM", r"Who&When runs \(<v>%, against", P1), ("IX", r"<v>% of \d+ Who&When runs where the tool's first warning sign", P1),
        ("KI", r"names the labelled agent in \d+ runs \(<v>%; chance", P1), ("V", r"\| the record of the tool's first warning sign \| \d+ \(<v>%\)", P1),
        ("R", r"name a failing agent at chance \(<v>% against", P1), ("R", r"names the labelled agent in \d+ of \d+ runs \(<v>%; chance", P1),
        ("S", r"<v>% of \d+ failed runs where the tool's first warning sign", P1), ("SUB", r"name the agent at fault at chance \(<v>% against", P1),
        ("LIM", r"reading its flags as blame is at chance \(<v>% against", P1)))
    A(C("external.ww_chance_agent", "Who&When: chance of naming the right agent", f"{ww} attribution_all.chance.agent",
        ("RM", r"against <v>% by chance", P1), ("IX", r"names the agent that caused the failure; chance is <v>%", P1),
        ("KI", r"names the labelled agent in \d+ runs \([\d.]+%; chance <v>%\)", P1), ("V", r"\| chance \| <v>% \|", P1),
        ("R", r"name a failing agent at chance \([\d.]+% against <v>%\)", P1), ("R", r"runs \([\d.]+%; chance <v>%\), fewer than naming", P1),
        ("S", r"names the agent at fault; chance is <v>%", P1), ("SUB", r"at chance \([\d.]+% against <v>%\)", P1), ("LIM", r"at chance \([\d.]+% against <v>% on Who&When\)", P1)))
    A(C("external.ww_busiest_right", "Who&When: runs where the agent with most records is the labelled one", f"{ww} …baseline_busiest_agent.agent.k",
        ("RM", r"Naming the busiest agent gets <v> and"), ("KI", r"Naming the agent with most records gets <v>,"), ("V", r"\| baseline: the agent with most records \| <v> \("),
        ("R", r"fewer than naming the busiest agent \(<v>\)"), ("S", r"busiest agent <v>, last speaker")))
    A(C("external.ww_last_right", "Who&When: runs where the last speaker is the labelled agent", f"{ww} …baseline_last_step.agent.k",
        ("RM", r"and the last speaker <v>\."), ("KI", r"gets \d+, the last speaker <v>\."), ("V", r"\| baseline: the last step \| <v> \("),
        ("R", r"or the last speaker \(<v>\)"), ("S", r"last speaker <v> MAST-Data")))
    ma = "reports/external/mast_data/results.json"
    A(C("external.mast_runs", "MAST-Data: runs read", f"{ma} totals.runs",
        ("RM", r"in [\d,]+ of <v> runs of seven agent frameworks"), ("IX", r"Who&When runs, [\d,]+ of <v> MAST-Data runs"),
        ("KI", r"Who&When runs, [\d,]+ of <v> MAST-Data runs"), ("V", r"\(Who&When\), [\d,]+ of <v> \(MAST-Data\)"),
        ("R", r"\(9\.5%\) [\d,]+ of <v> Alert on"), ("S", r"set off the Alert rule \(\d+ of \d+, [\d,]+ of <v>,")))
    A(C("external.mast_alert_fired", "MAST-Data: runs where the Alert rule fired (pack the tool picks)", f"{ma} false_alarms_all.by_rule_auto_pack['alert-coord2'].k",
        ("RM", r"in <v> of [\d,]+ runs of seven agent frameworks"), ("IX", r"Who&When runs, <v> of [\d,]+ MAST-Data runs"),
        ("KI", r"Who&When runs, <v> of [\d,]+ MAST-Data runs"), ("V", r"\(Who&When\), <v> of [\d,]+ \(MAST-Data\)"),
        ("R", r"\(9\.5%\) <v> of [\d,]+ Alert on"), ("S", r"set off the Alert rule \(\d+ of \d+, <v> of [\d,]+,")))
    A(C("external.mast_pairs_found", "MAST-Data: logged pairs the tool finds with recipients withheld", f"{ma} who_talked_to_whom_all.recipients_withheld.pair_recall.k",
        ("RM", r"and <v> of [\d,]+ \([\d.]+%\) in the three MAST frameworks"), ("KI", r"on Who&When and <v> of [\d,]+ \([\d.]+%\) on MAST-Data"),
        ("V", r"\| MAST-Data, three frameworks that name recipients \| <v> of"), ("R", r"runs of seven frameworks <v> of [\d,]+ \(")))
    A(C("external.mast_pairs_logged", "MAST-Data: logged sender-recipient pairs", f"{ma} …pair_recall.n",
        ("RM", r"and [\d,]+ of <v> \([\d.]+%\) in the three MAST frameworks"), ("KI", r"on Who&When and [\d,]+ of <v> \([\d.]+%\) on MAST-Data"),
        ("V", r"\| MAST-Data, three frameworks that name recipients \| [\d,]+ of <v> \("), ("R", r"runs of seven frameworks [\d,]+ of <v> \(")))
    A(C("external.mast_pair_recall", "MAST-Data: share of logged pairs found", f"{ma} …pair_recall k / n",
        ("RM", r"of [\d,]+ \(<v>%\) in the three MAST frameworks", P1), ("IX", r"recipients withheld \(Who&When; <v>% on MAST-Data\)", P1),
        ("KI", r"of [\d,]+ \(<v>%\) on MAST-Data, but", P1), ("V", r"\| MAST-Data, three frameworks that name recipients \| [\d,]+ of [\d,]+ \(<v>%\)", P1),
        ("R", r"logged agent pairs on one outside dataset and <v>% on another", P1), ("R", r"sender.recipient pairs in Who&When and <v>% in MAST-Data", P1),
        ("S", r"found with the recipients withheld \(<v>% on a second dataset\)", P1), ("SUB", r"on one outside dataset and <v>% on another", P1),
        ("LIM", r"on Who&When, <v>% on MAST-Data\)", P1)))
    A(C("external.mast_message_recall", "MAST-Data: logged single messages the tool finds", f"{ma} …message_recall k / n",
        ("RM", r"logged messages on Who&When and <v>% on MAST", P1), ("KI", r"on MAST-Data, but [\d.]+% and <v>% of the single logged messages", P1),
        ("V", r"\| 1,277 of 13,441 \(<v>%\) \|", P1), ("R", r"It finds [\d.]+% and <v>% of the single logged messages", P1), ("S", r"\(an LLM judge\) [\d.]+% <v>% [\d,]+ of", P1)))
    sa = "reports/external/salt/results.json"
    A(C("external.salt_labelled_runs", "SALT: runs that carry the collusion label", f"{sa} loaded.runs_with_label",
        ("RM", r"and in all <v> labelled SALT runs"), ("KI", r"Moltbook communities and all <v> labelled SALT runs"), ("R", r"SALT, <v> labelled two-agent runs n/a"),
        ("S", r"SALT, <v> labelled two-agent runs")))
    A(C("external.salt_colluded_runs", "SALT: labelled runs that colluded", f"{sa} loaded.colluded_runs",
        ("RM", r"the Alert rule fires on [\d,]+ of <v> colluding runs and \d+ of \d+ others"), ("IX", r"On SALT the Alert rule fired on [\d,]+ of <v> colluding runs"),
        ("KI", r"the Alert rule fires on [\d,]+ of <v> colluding runs and \d+ of \d+ others\. A pack"), ("V", r"the Alert rule fires on [\d,]+ of <v> colluding runs and \d+ of \d+ others, so"),
        ("R", r"n/a [\d,]+ of <v> colluding; \d+ of \d+ others"), ("S", r"n/a n/a [\d,]+ of <v> colluding and")))
    A(C("external.salt_alert_colluded", "SALT: colluding runs where the Alert rule fired (step clock)", f"{sa} step_clock.flags['rule:alert-coord2'].recall.k",
        ("RM", r"the Alert rule fires on <v> of [\d,]+ colluding runs and \d+ of \d+ others"), ("IX", r"On SALT the Alert rule fired on <v> of [\d,]+ colluding runs"),
        ("KI", r"the Alert rule fires on <v> of [\d,]+ colluding runs and \d+ of \d+ others\. A pack"), ("V", r"the Alert rule fires on <v> of [\d,]+ colluding runs and \d+ of \d+ others, so"),
        ("R", r"n/a <v> of [\d,]+ colluding; \d+ of \d+ others"), ("S", r"n/a n/a <v> of [\d,]+ colluding and")))
    A(C("external.salt_other_runs", "SALT: labelled runs that did not collude", f"{sa} loaded.not_colluded_runs",
        ("RM", r"colluding runs and \d+ of <v> others\. A phrase pack"), ("IX", r"colluding runs and \d+ of <v> others, so it cannot tell them apart"),
        ("KI", r"colluding runs and \d+ of <v> others\. A pack written from one run"), ("V", r"colluding runs and \d+ of <v> others, so it does not separate them"),
        ("R", r"colluding; \d+ of <v> others Phrase pack"), ("S", r"colluding and \d+ of <v> others a phrase pack")))
    A(C("external.salt_alert_other", "SALT: non-colluding runs where the Alert rule fired (step clock)", f"{sa} step_clock.flags['rule:alert-coord2'].false_positive_rate.k",
        ("RM", r"colluding runs and <v> of \d+ others\. A phrase pack"), ("IX", r"colluding runs and <v> of \d+ others, so it cannot tell them apart"),
        ("KI", r"colluding runs and <v> of \d+ others\. A pack written from one run"), ("V", r"colluding runs and <v> of \d+ others, so it does not separate them"),
        ("R", r"colluding; <v> of \d+ others Phrase pack"), ("S", r"colluding and <v> of \d+ others a phrase pack")))
    A(C("external.salt_pack_recall", "SALT: recall of the peer_review pack on the conditions it was not written from", f"{sa} pack.runs.recall k / n",
        ("RM", r"fires on <v>% of colluding runs and [\d.]+% of the others in the", P1), ("IX", r"written from one run catches <v>% of colluding runs", P1),
        ("KI", r"fires on <v>% of colluding runs and [\d.]+% of the others in the", P1), ("V", r"colluding runs \(<v>%\) and \d+ of \d+ others", P1),
        ("R", r"written from one SALT run catches <v>% of colluding runs", P1), ("R", r"Phrase pack: recall <v>%", P1), ("S", r"a phrase pack from one run: recall <v>%", P1)))
    A(C("external.salt_pack_false_positives", "SALT: non-colluding runs the peer_review pack fires on", f"{sa} pack.runs.false_positive_rate k / n",
        ("RM", r"% of colluding runs and <v>% of the others in the \d+ conditions", P1), ("IX", r"% of colluding runs at <v>% false positives, mostly", P1),
        ("KI", r"% of colluding runs and <v>% of the others in the \d+ conditions", P1), ("V", r"and \d+ of \d+ others \(<v>%\) in the \d+ conditions", P1),
        ("R", r"% of colluding runs at <v>% false positives, but", P1), ("R", r"Phrase pack: recall [\d.]+%, false positives <v>%", P1),
        ("S", r"recall [\d.]+%, false positives <v>% \(", P1)))
    A(C("external.salt_pack_recall_own_model", "SALT: pack recall where an agent is the model the pack was written from", f"{sa} pack.by_model.an_agent_is_the_training_model.recall k / n",
        ("RM", r"but on <v>% where an agent is the model whose wording it copied", P1), ("KI", r"it was not written from: <v>% where an agent is the model", P1),
        ("V", r"model whose wording it copied: <v>% of colluding runs where an agent is that model", P1), ("R", r"false positives, but <v>% where an agent is the model", P1),
        ("S", r"false positives [\d.]+% \(<v>% on its own model", P1)))
    A(C("external.salt_pack_recall_other_models", "SALT: pack recall where no agent is that model", f"{sa} pack.by_model.no_agent_is.recall k / n",
        ("RM", r"whose wording it copied and <v>% elsewhere", P1), ("KI", r"its phrases were read from, <v>% where none is", P1),
        ("V", r"where an agent is that model, <v>% where none is", P1), ("R", r"the model it was written from and <v>% elsewhere", P1),
        ("S", r"on its own model, <v>% elsewhere\)", P1)))
    mo = "reports/external/moltbook/results.json"
    A(C("external.moltbook_communities", "Moltbook: communities scored (one week)", f"{mo} false_alarms.communities",
        ("RM", r"in \d+ of <v> Moltbook communities, and in all"), ("IX", r"MAST-Data runs, \d+ of <v> Moltbook communities"),
        ("KI", r"MAST-Data runs, \d+ of <v> Moltbook communities"), ("V", r"\(MAST-Data\) and \d+ of <v> \(Moltbook communities\)"),
        ("R", r"\(precision [\d.]+%\) \d+ of <v> No incident on record"), ("S", r"[\d,]+ of [\d,]+, \d+ of <v>\)\. It detects")))
    A(C("external.moltbook_alert_fired", "Moltbook: communities where the Alert rule fired", f"{mo} false_alarms.flags['rule:alert-coord2'].fired.k",
        ("RM", r"in <v> of \d+ Moltbook communities, and in all"), ("IX", r"MAST-Data runs, <v> of \d+ Moltbook communities"),
        ("KI", r"MAST-Data runs, <v> of \d+ Moltbook communities"), ("V", r"\(MAST-Data\) and <v> of \d+ \(Moltbook communities\)"),
        ("R", r"\(precision [\d.]+%\) <v> of \d+ No incident on record"), ("S", r"[\d,]+ of [\d,]+, <v> of \d+\)\. It detects")))
    A(C("external.moltbook_reply_precision", "Moltbook: share of inferred reply links that are logged replies", f"{mo} inference.by_record.precision k / n",
        ("RM", r"On Moltbook <v>% of its inferred links are logged replies", P1), ("IX", r"On Moltbook <v>% of the tool's inferred reply links", P1),
        ("KI", r"On Moltbook <v>% of its inferred reply links are logged replies", P1), ("V", r"\| [\d,]+ of [\d,]+ \(<v>%\) \|–\|", P1),
        ("R", r"On Moltbook <v>% of its inferred reply links are logged replies", P1), ("R", r"of logged replies \(precision <v>%\)", P1),
        ("S", r"of replies; <v>% of links are replies", P1), ("LIM", r"On a social network of agents <v>% of its inferred reply links", P1)))
    A(C("external.moltbook_reply_recall", "Moltbook: share of logged replies the tool finds", f"{mo} inference.by_record.recall k / n",
        ("V", r"\| Moltbook, replies by record \| [\d,]+ of [\d,]+ \(<v>%\)", P1), ("R", r"replying pairs <v>% of logged replies", P1), ("S", r"replying pairs <v>% of replies;", P1)))
    A(C("external.moltbook_first_comment_precision", "Moltbook: precision on the first comment in a thread", f"{mo} inference.by_record_first_comment.precision k / n",
        ("RM", r"logged replies \(<v>% for the first comment in a thread", P1), ("KI", r"logged replies: <v>% for the first comment in a thread", P1),
        ("V", r"right about the first comment in a thread \(<v>% of its links\)", P1), ("R", r"logged replies: <v>% for the first comment in a thread", P1),
        ("S", r"first comment in a thread <v>% right", P1)))
    A(C("external.moltbook_later_comment_precision", "Moltbook: precision on later comments", f"{mo} inference.by_record_later_comment.precision k / n",
        ("RM", r"first comment in a thread, <v>% for later ones", P1), ("KI", r"first comment in a thread, <v>% for later comments", P1),
        ("V", r"and wrong after it \(<v>%\)", P1), ("R", r"first comment in a thread and <v>% after it", P1), ("S", r"later ones <v>% None of the four", P1)))
    # ---- v2.3.0: the pre-registered forward test of the four main alarms (reports/earlywarn/)
    ew = "reports/earlywarn/summary_v23.json generators"
    A(C("earlywarn.any_before_harm_original", "Forward test, original simulator: swarms where the first of the four alarms fired before the first true harm", f"{ew}.original.main['any_main'].coordinated.before_harm.k",
        ("RM", r"the first of the four came before it in <v> of \d+ swarms and in"), ("IX", r"<v> of \d+ simulated swarms in which the first of the four main alarms"),
        ("KI", r"\(the first of the four came before it in <v> of \d+ and"), ("R", r"the first of the four came before it in <v> of \d+ and in"),
        ("R", r"Any of the four <v> of \d+ \d+ of \d+ \d+ of \d+ \d+ of \d+ \d+ of \d+"), ("S", r"<v> of \d+ simulated swarms where the first of the four main alarms"),
        ("S", r"fired before the first true harm in <v> of \d+ and \d+ of \d+ simulated swarms"), ("SUB", r"led the first harm in <v> of \d+ and")))
    A(C("earlywarn.coordinated_original", "Forward test, original simulator: coordinated swarms", f"{ew}.original.coordinated_runs",
        ("RM", r"the first of the four came before it in \d+ of <v> swarms and in"), ("IX", r"\d+ of <v> simulated swarms in which the first of the four main alarms"),
        ("KI", r"\(the first of the four came before it in \d+ of <v> and"), ("R", r"the first of the four came before it in \d+ of <v> and in"),
        ("R", r"On <v> coordinated swarms of the original simulator"), ("S", r"\d+ of <v> simulated swarms where the first of the four main alarms"),
        ("SUB", r"led the first harm in \d+ of <v> and")))
    A(C("earlywarn.any_before_harm_independent", "Forward test, independent generator: the same", f"{ew}.independent.main['any_main'].coordinated.before_harm.k",
        ("RM", r"swarms and in <v> of \d+\. Any of the four"), ("IX", r"before the first true harm \(<v> of \d+ on the independent generator\)"),
        ("KI", r"came before it in \d+ of \d+ and <v> of \d+ swarms\)"), ("R", r"came before it in \d+ of \d+ and in <v> of \d+, a median"),
        ("R", r"Any of the four \d+ of \d+ <v> of \d+ \d+ of \d+ \d+ of \d+ \d+ of \d+"), ("S", r"before the first true harm \(<v> of \d+ on an independent generator\)"),
        ("SUB", r"led the first harm in \d+ of \d+ and <v> of \d+ simulated swarms")))
    A(C("earlywarn.coordinated_independent", "Forward test, independent generator: coordinated swarms", f"{ew}.independent.coordinated_runs",
        ("RM", r"swarms and in \d+ of <v>\. Any of the four"), ("IX", r"before the first true harm \(\d+ of <v> on the independent generator\)"),
        ("KI", r"came before it in \d+ of \d+ and \d+ of <v> swarms\)"), ("R", r"came before it in \d+ of \d+ and in \d+ of <v>, a median"),
        ("R", r"of the original simulator and <v> of the independently written one"), ("S", r"before the first true harm \(\d+ of <v> on an independent generator\)"),
        ("SUB", r"led the first harm in \d+ of \d+ and \d+ of <v> simulated swarms")))
    A(C("earlywarn.any_fired_benign_original", "Forward test, original simulator: benign swarms where any of the four alarms fired", f"{ew}.original.main['any_main'].benign.fired.k",
        ("RM", r"Any of the four fired in <v> of \d+ and \d+ of \d+ simulated benign swarms"), ("IX", r"any of the four fired in <v> of \d+ and \d+ of \d+ benign swarms"),
        ("KI", r"any of the four in <v> of \d+ and \d+ of \d+ simulated benign swarms"), ("R", r"Any of the four fired in <v> of \d+ and \d+ of \d+ benign swarms"),
        ("R", r"Any of the four \d+ of \d+ \d+ of \d+ <v> of \d+ \d+ of \d+ \d+ of \d+"), ("S", r"any of the four fired in <v> of \d+ and \d+ of \d+ benign swarms")))
    A(C("earlywarn.benign_original", "Forward test, original simulator: benign swarms", f"{ew}.original.benign_runs",
        ("RM", r"Any of the four fired in \d+ of <v> and \d+ of \d+ simulated benign swarms"), ("KI", r"any of the four in \d+ of <v> and \d+ of \d+ simulated benign swarms"),
        ("R", r"Any of the four fired in \d+ of <v> and \d+ of \d+ benign swarms"), ("S", r"any of the four fired in \d+ of <v> and \d+ of \d+ benign swarms")))
    A(C("earlywarn.any_fired_benign_independent", "Forward test, independent generator: benign swarms where any of the four alarms fired", f"{ew}.independent.main['any_main'].benign.fired.k",
        ("RM", r"Any of the four fired in \d+ of \d+ and <v> of \d+ simulated benign swarms"), ("IX", r"any of the four fired in \d+ of \d+ and <v> of \d+ benign swarms"),
        ("KI", r"any of the four in \d+ of \d+ and <v> of \d+ simulated benign swarms"), ("R", r"Any of the four fired in \d+ of \d+ and <v> of \d+ benign swarms"),
        ("R", r"Any of the four \d+ of \d+ \d+ of \d+ \d+ of \d+ <v> of \d+ \d+ of \d+"), ("S", r"any of the four fired in \d+ of \d+ and <v> of \d+ benign swarms")))
    A(C("earlywarn.benign_independent", "Forward test, independent generator: benign swarms", f"{ew}.independent.benign_runs",
        ("RM", r"Any of the four fired in \d+ of \d+ and \d+ of <v> simulated benign swarms"), ("KI", r"any of the four in \d+ of \d+ and \d+ of <v> simulated benign swarms"),
        ("R", r"Any of the four fired in \d+ of \d+ and \d+ of <v> benign swarms"), ("S", r"any of the four fired in \d+ of \d+ and \d+ of <v> benign swarms")))
    A(C("earlywarn.new_host_fired_benign_original", "Forward test, original simulator: benign swarms where the new-host alarm fired", f"{ew}.original.main['new_host_12h'].benign.fired.k",
        ("KI", r"stayed quiet on simulated benign swarms \(<v> of \d+,"), ("R", r"only the new-host alarm stayed quiet \(<v> of \d+,")))
    A(C("earlywarn.new_host_fired_benign_independent", "Forward test, independent generator: the same", f"{ew}.independent.main['new_host_12h'].benign.fired.k",
        ("KI", r"stayed quiet on simulated benign swarms \(\d+ of \d+, <v> of \d+\)"), ("R", r"only the new-host alarm stayed quiet \(\d+ of \d+, <v> of \d+\)")))
    A(C("earlywarn.h1_holds_original", "Forward test, original simulator: alarms for which the lead hypothesis (H1) holds", f"{ew}.original.hypotheses, H1 with holds true"))
    A(C("earlywarn.h1_holds_independent", "Forward test, independent generator: the same", f"{ew}.independent.hypotheses, H1 with holds true"))
    be = "reports/earlywarn/benign_external_v23.json datasets['moltbook-observatory']"
    A(C("earlywarn.moltbook_traces", "Real Moltbook community traces with times that the early-warning measurement read", f"{be}.timed_alarms_measurable",
        ("RM", r"and in \d+ of <v> real Moltbook community traces"), ("IX", r"they fire almost always \(\d+ of <v> Moltbook community traces\)"),
        ("KI", r"and in \d+ of <v> real Moltbook community traces"), ("R", r"On <v> real traces of an agent social network"),
        ("S", r"and in \d+ of <v> real Moltbook traces"), ("LIM", r"that we could read \(<v> Moltbook community traces\)")))
    A(C("earlywarn.moltbook_any_fired", "Of those, traces where any of the four alarms fired", f"{be}.benign_set.rows['any_main'].fired.k",
        ("RM", r"and in <v> of \d+ real Moltbook community traces"), ("IX", r"they fire almost always \(<v> of \d+ Moltbook community traces\)"),
        ("KI", r"and in <v> of \d+ real Moltbook community traces"), ("R", r"Any of the four \d+ of \d+ \d+ of \d+ \d+ of \d+ \d+ of \d+ <v> of \d+"),
        ("S", r"and in <v> of \d+ real Moltbook traces")))
    A(C("earlywarn.moltbook_new_host_fired", "Of those, traces where the new-host alarm fired", f"{be}.benign_set.rows['new_host_12h'].fired.k",
        ("KI", r"and it fired in <v> of \d+ Moltbook traces"), ("R", r"the three time-based alarms each fired in <v> \(Appendix B"),
        ("V", r"the three time-based main alarms each fired in <v> \("), ("LIM", r"the three time-based main alarms each fired in <v>\.")))
    # ---- v2.3.0: the two implementations of the counting rule (reports/integrity/crosscheck.json, not tracked)
    cc = "reports/integrity/crosscheck.json datasets"
    A(C("crosscheck.release_main", "Deliveries the main implementation finds on the release, in the saved crosscheck", f"{cc}['Swarm Traces'].A.deliveries",
        ("RM", r"Swarm Traces release <v> and \d+, collusion\.wiki logs"), ("R", r"its agreement on the release \(<v> and \d+\) is not independent"),
        ("S", r"the second implementation now agrees \(<v> and \d+\)")))
    A(C("crosscheck.release_second", "Deliveries the second implementation finds on the release", f"{cc}['Swarm Traces'].B.deliveries",
        ("RM", r"Swarm Traces release \d+ and <v>, collusion\.wiki logs"), ("RM", r"A second implementation of the rule finds the same <v>\."),
        ("KI", r"The second implementation finds the same <v>, and"), ("KI", r"but not independently \(<v> deliveries each"),
        ("V", r"written rule and finds the same <v> deliveries on the release"), ("R", r"its agreement on the release \(\d+ and <v>\) is not independent"),
        ("S", r"the second implementation now agrees \(\d+ and <v>\)")))
    A(C("crosscheck.release_both", "Deliveries both implementations find on the release", f"{cc}['Swarm Traces'].both"))
    A(C("crosscheck.release_uses_content", "Deliveries on the release that pass the written-content test (R38a or R38b)", f"{cc}['Swarm Traces'].content_test.A_pass",
        ("RM", r"and still <v> where the reader is shown using what was written"), ("RM", r"on the release that is <v> of \d+, and a second form of the test"),
        ("KI", r"\(unchanged\), <v> where the reader is shown using what was written \(unchanged\)"), ("LIM", r"\(<v> of \d+ on the Swarm Traces release do\)"),
        ("HW", r"which is <v> of \d+ on the Swarm Traces release"), ("R", r"on the release that is <v> of \d+\. Earlier versions")))
    A(C("crosscheck.release_operations_differ", "Single operations on the release that only one implementation reports", f"{cc}['Swarm Traces'].operations only_A + only_B",
        ("KI", r"<v> single operations on the release still differ without changing a delivery")))
    A(C("crosscheck.wiki_both", "Deliveries both implementations find on the collusion.wiki logs", f"{cc}['collusion.wiki logs'].both",
        ("RM", r"collusion\.wiki logs <v>, demo swarm"), ("KI", r"finds the same \d+, and <v> on the collusion\.wiki logs"),
        ("V", r"deliveries on the release and <v> on the wiki logs"), ("V", r"\([\d,]+ of <v> pass, against")))
    A(C("crosscheck.wiki_uses_content", "Wiki deliveries that pass the written-content test (main implementation)", f"{cc}['collusion.wiki logs'].content_test.A_pass",
        ("V", r"\(<v> of [\d,]+ pass, against")))
    A(C("crosscheck.wiki_uses_content_r38b", "Wiki deliveries that pass by R38b (main implementation)", f"{cc}['collusion.wiki logs'].content_test.later_output_R38b.A",
        ("V", r"On the collusion\.wiki logs it passes <v> deliveries that did not pass before")))
    A(C("crosscheck.demo_both", "Deliveries both implementations find on the demo swarm", f"{cc}['demo swarm'].both", ("RM", r"demo swarm <v>, the format samples")))
    # ---- a text block that must be the saved output, verbatim
    blk = Claim("validation.tables", "The tables under 'Results' in docs/validation.md are the saved run's summary.md, line for line",
                "reports/validation/summary.md, written by agenttrace.validation run")
    blk.block = ("docs/validation.md", "## Results", "## Audited links on the real release", "reports/validation/summary.md")
    c.append(blk)
    return c


# ------------------------------------------------------------------ computing the numbers (one part per subprocess)

def _session(ds):
    from agenttrace.session import Session
    s = Session()
    s.load(os.path.join(ROOT, DATASETS[ds]["path"]), DATASETS[ds]["pack"], {})
    return s


def _sign(signs, key):
    return next((g for g in signs if g["key"] == key), None)


def part_release_core():
    from agenttrace import benchmark, board, fx_whatif, units
    s = _session("release")
    sm, f, m = s.summary(), s.flow, {}
    m["release.records"] = sm["records"]
    m["release.payloads"] = sm["kinds"].get("payload", 0)
    m["release.recovered_texts"] = sm["kinds"].get("recovered_text", 0)
    m["release.responses"] = sm["kinds"].get("response", 0)
    m["release.dated_records"] = sm["timed"]
    m["release.undated_records"] = sm["time_test"]["untimed"]
    m["release.dated_share"] = round(sm["timed"] / sm["records"], 4)
    m["release.undated_share"] = round(sm["time_test"]["untimed"] / sm["records"], 4)
    m["release.payload_dated_share"] = round(sm["actions"]["dated"] / m["release.payloads"], 4)
    b = sm["time_test"]["blocks"][0]
    m["release.block1_records"] = b["records"]
    m["release.block1_timestamps"] = b["timestamp_points"]
    m["release.block1_spearman"] = b["spearman"]
    m["release.block1_median_error_h"] = b["fit_error_hours_median"]
    m["release.block1_p90_error_h"] = b["fit_error_hours_p90"]
    it = sm["identity_test"]
    m["release.tokens_used_5_plus"] = it["tokens_used_5_plus"]
    m["release.tokens_one_role"] = it["with_one_role_90pct"]
    m["release.tokens_changing_role"] = it["tokens_used_5_plus"] - it["with_one_role_90pct"]
    m["release.named_tokens"] = sm["actions"]["named_actors"]
    m["release.unattributed_action_share"] = round(sm["actions"]["unattributed"] / sm["actions"]["total"], 4)
    m["release.harm_timed"] = sm["harm_events_timed"]
    dels = f["_deliveries"]
    nd = [d for d in dels if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    m["release.deliveries"] = f["deliveries"]
    m["release.named_deliveries"] = f["deliveries_between_named_actors"]
    m["release.named_pairs"] = f["named_actor_pairs"]
    m["release.named_message_tokens"] = len({d["from"] for d in nd} | {d["to"] for d in nd})
    ct = f.get("channel_types") or {}
    m["release.deliveries_hf_dataset"] = (ct.get("hf_dataset") or {}).get("deliveries", 0)
    m["release.deliveries_board"] = (ct.get("board") or {}).get("deliveries", 0)
    m["release.deliveries_on_merged_places"] = f.get("coarse_channel_deliveries", 0)
    m["release.latency_median_h"] = f["latency_hours"]["median"]
    m["release.latency_p90_h"] = f["latency_hours"]["p90"]
    m["release.place_actors_anonymous"] = f["actors_on_channels"].get("run", 0)
    m["release.place_actors_tokens"] = f["actors_on_channels"].get("token", 0)
    g = f.get("deliveries_by_grade") or {}
    for k in ("direct", "inferred", "weak"):
        m[f"release.grade_{k}"] = g.get(k, 0)
    fn = f.get("first_named_delivery") or {}
    m["release.first_message_time"] = fn.get("read_time")
    m["release.first_message_write_time"] = fn.get("write_time")
    m["release.first_message_write_id"] = fn.get("write_id")
    m["release.first_message_read_id"] = fn.get("read_id")
    m["release.first_message_harm_share"] = f.get("harm_share_after_first_named_delivery")
    m["release.places"] = f["channels"]
    m["release.places_written_never_read"] = sum(1 for p in f.get("_channels") or [] if p.get("never_read") and (p.get("writes") or 0) >= 3)
    m["release.dataset_write_records"] = sm["intents"].get("hf_dataset_write", 0)
    m["release.programs_shared"] = f["content_families_moving"]
    m["release.programs_nonroutine"] = sum(1 for x in f["_content_spread"] if not x.get("routine"))
    m["release.tokens_seen_then_used"] = sm["list_totals"]["seen_then_used"]
    m["release.shared_names_separate_records"] = sum(1 for x in s.rec["shared_places"] if not x.get("same_record"))
    m["release.carried_tokens"] = sm["list_totals"]["carried_edges"]
    # identity
    u = units.units_summary(s, "agent")
    w = fx_whatif.whatif(s, "estimate")
    groups = sorted(w.get("groups") or [], key=lambda x: -len(x["actors"]))
    m["release.agents"] = u["agents"]
    m["release.merged_agents"] = u["merged_agents"]
    m["release.merged_tokens"] = sum(len(x["actors"]) for x in groups)
    m["release.largest_agent_tokens"] = len(groups[0]["actors"]) if groups else 0
    m["release.largest_agent_records"] = groups[0]["records"] if groups else 0
    m["release.agent_messages"] = u["messages"]
    m["release.agent_messages_inside"] = u["inside_one_agent"]
    fm = u.get("first_message") or {}
    m["release.agent_first_message_time"] = fm.get("time")
    m["release.agent_first_message_share"] = fm.get("harm_share_after")
    for key, name in (("replay:coordination: one identity carries another's token", "carried"), ("replay:coordination: two identities use one place", "shared_name")):
        g = (_sign(u["signs"], key) or {}).get("by_agent") or {}
        m[f"release.agent_{name}_sign_time"] = g.get("time")
        m[f"release.agent_{name}_sign_share"] = g.get("harm_share_after")
    m["release._decisions"] = {k: v for k, v in (w.get("decisions") or {}).items() if k != "file"}
    # audit score
    audit = benchmark.load_audit()
    sc = benchmark.score(benchmark.all_links(s), audit)
    ga = sc["groups"]
    m["release.audit_reported_true"] = ga["all"]["true"]
    m["release.audit_reported_false"] = ga["all"]["false"]
    m["release.audit_reported_unclear"] = ga["all"]["unclear"]
    m["release.audit_decidable"] = sc["precision"]["n"]
    m["release.audit_precision"] = sc["precision"]["value"]
    m["release.audit_precision_low"], m["release.audit_precision_high"] = sc["precision"]["ci"] or (None, None)
    m["release.audit_named_true"] = ga["named_named"]["true"]
    m["release.audit_run_reported"] = ga["involves_run"]["reported"]
    m["release.audit_run_true"] = ga["involves_run"]["true"]
    m["release.audit_run_decidable"] = ga["involves_run"]["precision"]["n"]
    m["release.audit_inferred_true"] = sc["by_grade"]["inferred"]["true"]
    m["release.audit_weak_true"] = sc["by_grade"]["weak"]["true"]
    m["release.audit_weak_decidable"] = sc["by_grade"]["weak"]["precision"]["n"]
    m["release._audit_not_audited"] = sc.get("reported_now_not_audited")
    ia = benchmark.independent_agreement(s, audit)["decided"]
    m["release.second_method_agree"] = ia["agreement"]["k"]
    m["release.second_method_decided"] = ia["n"]
    m["release.second_method_agreement"] = ia["agreement"]["value"]
    m["release.second_method_kappa"] = ia["kappa"]
    fu = board.board(s)["funnel"]
    m["release.board_folders"] = fu["folders"]
    m["release.board_folders_written"] = fu["written"]
    m["release.board_folders_read"] = fu["read"]
    m["release.board_folders_both"] = fu["both"]
    m["release.board_folders_read_only"] = fu["read_only"]
    m["release.board_folders_written_only"] = fu["written_only"]
    # what the saved outputs should hold (compared with the tracked files by verify)
    m["release._saved.identity_replay"] = {"as_counted": {k: w["as_counted"].get(k) for k in ("agents", "messages", "pairs", "inside_one_agent")},
                                           "after": {k: w["after"].get(k) for k in ("agents", "messages", "pairs", "inside_one_agent")},
                                           "after_first_time": (w["after"].get("first_message") or {}).get("time")}
    return m


def part_release_evaluate():
    from agenttrace import evaluate
    s = _session("release")
    ev = evaluate.evaluate(s)
    m = {}
    sg = ev["replay_signs"]

    def put(name, key):
        g = _sign(sg, key) or {}
        m[f"release.{name}_time"] = g.get("time")
        m[f"release.{name}_share"] = g.get("harm_share_after")
    put("first_dataset_write", "replay:first: hf_dataset_write")
    put("carried_sign", "replay:coordination: one identity carries another's token")
    put("shared_name_sign", "replay:coordination: two identities use one place")
    put("program2", "program2")
    put("group3", "group3")
    ra = ev["baselines"]["rate_alarm_all_actions"] or {}
    m["release.volume_alarm_hour"] = ra.get("hour")
    m["release.volume_alarm_share"] = ra.get("harm_share_after")
    rb = ev["robustness"]
    m["release.robust_sigma_h"] = rb["sigma_hours"]
    m["release.robust_p90_h"] = rb["from_p90_error_hours"]
    by = {x["signal"]: x for x in rb["signals"]}
    w = by.get("first: hf_dataset_write") or {}
    fm = by.get("first message between named actors") or {}
    m["release.robust_dataset_write_low"], m["release.robust_dataset_write_high"] = w.get("interval_95") or (None, None)
    m["release.robust_first_message_low"], m["release.robust_first_message_high"] = fm.get("interval_95") or (None, None)
    coord = [x for x in rb["signals"] if x["signal"].startswith("coordination:")]
    m["release.robust_shared_control_high"] = max((x["interval_95"][1] for x in coord), default=None)
    m["release.robust_max_shift_points"] = round(100 * max((abs(x[k] - x["harm_share_after"]) for x in rb["signals"]
                                                            for k in ("if_signal_1h_earlier", "if_signal_1h_later")), default=0), 1)
    ms = (ev["external"] or {}).get("milestones") or []
    diffs = [abs(x["difference_h"]) for x in ms if x.get("difference_h") is not None]
    m["release.milestones"] = len(diffs)
    m["release.milestone_max_diff_h"] = max(diffs) if diffs else None
    pd = (ev["external"] or {}).get("per_day") or {}
    m["release.per_day_rank_correlation"] = pd.get("rank_correlation")
    m["release.per_day_first_share"] = (pd.get("our_share") or [None])[0]
    surge = next((x for x in ms if x["event"].startswith("Rapid climb")), None)
    first = (s.flow.get("first_named_delivery") or {}).get("read_time")
    if surge and first:
        gap = (evaluate._parse(surge["source_time"]) - evaluate._parse(first)) / 3600
        m["release.first_message_hours_before_surge"] = int(Decimal(str(gap)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    cr = ev["counting_rules"]
    m["release.counting_naive"] = cr[0]["messages"]
    m["release.counting_naive_pairs"] = cr[0]["pairs"]
    m["release._saved.evaluation"] = {"dated_records": ev["dated_records"], "records": ev["records"], "harm_events_timed": ev["harm_events_timed"],
                                      "baselines": ev["baselines"], "counting_rules": ev["counting_rules"], "robustness": ev["robustness"],
                                      "milestones": ms, "replay_signs": [{k: g[k] for k in ("key", "time", "ref", "harm_share_after")} for g in sg]}
    return m


def part_release_attribution():
    from agenttrace import attribution
    s = _session("release")
    a = attribution.attribution(s)
    b = a["bands"]
    m = {"release.anonymous_runs": a["runs"]}
    for k in ("high", "medium", "low"):
        m[f"release.attributed_{k}"] = b[k]["runs"]
    m["release.attributed_runs"] = sum(b[k]["runs"] for k in ("high", "medium", "low"))
    m["release.attributed_share"] = round(m["release.attributed_runs"] / a["runs"], 4) if a["runs"] else None
    hb = (a.get("holdout") or {}).get("bands") or {}
    for k in ("high", "medium"):
        m[f"release.attribution_holdout_{k}_precision"] = (hb.get(k) or {}).get("precision")
    return m


def part_release_insiders():
    from agenttrace import sensitivity
    s = _session("release")
    r = sensitivity.insiders(s)
    c = r.get("counts") or {}
    return {"release.insider_findings": r.get("total"), "release.insider_recovered": c.get("recovered"),
            "release.insider_partly": c.get("partly"), "release.insider_invisible": c.get("invisible"),
            "release._insider_statuses": {x.get("id"): x.get("status") for x in r.get("findings") or []}}


def part_wiki():
    from agenttrace import evaluate, model
    s = _session("wiki")
    sm = s.summary()
    k = sm["kinds"]
    m = {"wiki.records": sm["records"], "wiki.revisions": k.get("revisions", 0), "wiki.deletes": k.get("delete", 0), "wiki.probes": k.get("probe", 0)}
    m["wiki.other_events"] = sm["records"] - m["wiki.revisions"] - m["wiki.deletes"] - m["wiki.probes"]
    m["wiki.named_actors"] = sm["actions"]["named_actors"]
    a, b = (model.parse_time(x.replace(" ", "T") + ":00Z") for x in sm["time_test"]["span"])
    m["wiki.span_days"] = round((b - a).total_seconds() / 86400, 1)
    cr = evaluate.counting_ablation(s.events, s.pack, s.rec, s.res)
    m["wiki.counting_naive"] = cr[0]["messages"]
    m["wiki.counting_final"] = cr[-1]["messages"]
    m["wiki.overwrites"] = s.flow["overwrites"]
    c = s.conversation("LinkHelper771", "AgentMassPointer13")
    m["wiki.top_pair_messages"] = c["a_to_b"] + c["b_to_a"]
    m["wiki.top_pair_overwrites"] = c["overwrites"]
    m["wiki._saved.evaluation"] = {"counting_rules": cr, "records": sm["records"]}
    return m


def part_audit():
    with open(os.path.join(PKG, "claims", "audited_links.json"), encoding="utf-8") as f:
        a = json.load(f)
    links = a["links"]
    n = lambda lab: sum(1 for x in links if x["label"] == lab)
    return {"audit.links": len(links), "audit.true_links": n("true_message"), "audit.read_then_post": n("false_write"),
            "audit.read_is_write": n("read_not_a_read"), "audit.downloads": n("false_write_lfs_or_urlopen"),
            "audit.different_repo": n("different_repo"), "audit.unclear": n("unclear"),
            "audit.reader_holds_token": n("reader_holds_writer_token"),
            "audit.first_count": sum(1 for x in links if x.get("reported_v110"))}


def part_validation():
    with open(os.path.join(ROOT, DATASETS["validation"]["path"]), encoding="utf-8") as f:
        v = json.load(f)
    m = {"validation.coordinated_runs": v["coordinated_runs"], "validation.benign_runs": v["benign_runs"],
         "validation.total_runs": v["coordinated_runs"] + v["benign_runs"]}
    for key in ("msg_precision", "msg_recall", "pair_precision", "pair_recall", "dating_coverage"):
        for stat in ("min", "median", "max"):
            m[f"validation.{key}_{stat}"] = v["overall"][key][stat]
    for band in ("high", "medium", "low"):
        m[f"validation.identity_{band}_proposed"] = v["identity_pooled"][band]["proposed"]
        m[f"validation.identity_{band}_correct"] = v["identity_pooled"][band]["correct"]
    m["validation.benign_messages_between_agents_max"] = v["benign"]["messages_between_agents"]["max"]
    fires = {x["key"]: x["runs"] for x in v["benign"]["fires"] if x.get("what") == "rule"}
    m["validation.benign_alert_fired"] = fires.get("alert-coord2", 0)
    m["validation.benign_watch_fired"] = fires.get("watch-harm", 0)
    return m


def part_variance():
    with open(os.path.join(ROOT, DATASETS["variance"]["path"]), encoding="utf-8") as f:
        v = json.load(f)
    r = v["runs"]
    return {"variance.sigma_low_messages_low": r["0.12"]["messages"][1], "variance.sigma_low_messages_high": r["0.12"]["messages"][3],
            "variance.sigma_2h_messages_low": r["2.0"]["messages"][1], "variance.sigma_2h_messages_high": r["2.0"]["messages"][3],
            "variance.draws": r["0.12"]["draws"], "variance._base": v.get("base")}


def _lines(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return sum(1 for ln in f if ln.strip())


def part_samples():
    return {"samples.benign_records": _lines("agenttrace/samples/benign_swarm/benign_swarm.jsonl"),
            "samples.demo_records": _lines("agenttrace/samples/demo_swarm/demo_swarm.jsonl")}


def part_repo():
    import unittest
    old = sys.stderr
    try:
        sys.stderr = open(os.devnull, "w")
        suite = unittest.defaultTestLoader.discover(os.path.join(PKG, "tests"), top_level_dir=ROOT)
        n = suite.countTestCases()
    finally:
        sys.stderr.close()
        sys.stderr = old
    return {"repo.unit_tests": n, "repo.version": package_version()}


def _saved(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def _share(x):
    """k / n of a saved {"k", "n"} cell, kept to 6 places (the files round their own share to 3 or 4)."""
    return round(x["k"] / x["n"], 6) if x.get("n") else None


def part_external():
    """Headline numbers of the four outside datasets, read from the saved results (reports/external/*/results.json)."""
    m = {}
    w = _saved("reports/external/who_and_when/results.json")
    wh = w["groups"]["Hand-Crafted"]["who_talked_to_whom"]["recipients_withheld"]
    at = w["attribution_all"]
    m["external.ww_runs"] = w["totals"]["runs"]
    m["external.ww_pairs_found"] = wh["pair_recall"]["k"]
    m["external.ww_pairs_logged"] = wh["pair_recall"]["n"]
    m["external.ww_pair_precision"] = _share(wh["pair_precision_vs_logged"])
    m["external.ww_pair_precision_either"] = _share(wh["pair_precision_either_direction"])
    m["external.ww_message_recall"] = _share(wh["message_recall"])
    m["external.ww_alert_fired"] = w["false_alarms_all"]["by_rule_auto_pack"]["alert-coord2"]["k"]
    m["external.ww_agent_right"] = at["methods"]["tool_first_sign"]["agent"]["k"]
    m["external.ww_agent_right_share"] = _share(at["methods"]["tool_first_sign"]["agent"])
    m["external.ww_chance_agent"] = at["chance"]["agent"]
    m["external.ww_busiest_right"] = at["methods"]["baseline_busiest_agent"]["agent"]["k"]
    m["external.ww_last_right"] = at["methods"]["baseline_last_step"]["agent"]["k"]
    a = _saved("reports/external/mast_data/results.json")
    ah = a["who_talked_to_whom_all"]["recipients_withheld"]
    m["external.mast_runs"] = a["totals"]["runs"]
    m["external.mast_pairs_found"] = ah["pair_recall"]["k"]
    m["external.mast_pairs_logged"] = ah["pair_recall"]["n"]
    m["external.mast_pair_recall"] = _share(ah["pair_recall"])
    m["external.mast_message_recall"] = _share(ah["message_recall"])
    m["external.mast_alert_fired"] = a["false_alarms_all"]["by_rule_auto_pack"]["alert-coord2"]["k"]
    s = _saved("reports/external/salt/results.json")
    al = next(x for x in s["step_clock"]["flags"] if x["flag"] == "rule:alert-coord2")
    pk = s["pack"]
    m["external.salt_labelled_runs"] = s["loaded"]["runs_with_label"]
    m["external.salt_colluded_runs"] = s["loaded"]["colluded_runs"]
    m["external.salt_other_runs"] = s["loaded"]["not_colluded_runs"]
    m["external.salt_alert_colluded"] = al["recall"]["k"]
    m["external.salt_alert_other"] = al["false_positive_rate"]["k"]
    m["external.salt_pack_recall"] = _share(pk["runs"]["recall"])
    m["external.salt_pack_false_positives"] = _share(pk["runs"]["false_positive_rate"])
    m["external.salt_pack_recall_own_model"] = _share(pk["by_model"]["an_agent_is_the_training_model"]["recall"])
    m["external.salt_pack_recall_other_models"] = _share(pk["by_model"]["no_agent_is"]["recall"])
    b = _saved("reports/external/moltbook/results.json")
    inf = b["inference"]
    ba = next(x for x in b["false_alarms"]["flags"] if x["flag"] == "rule:alert-coord2")
    m["external.moltbook_communities"] = b["false_alarms"]["communities"]
    m["external.moltbook_alert_fired"] = ba["fired"]["k"]
    m["external.moltbook_reply_precision"] = _share(inf["by_record"]["precision"])
    m["external.moltbook_reply_recall"] = _share(inf["by_record"]["recall"])
    m["external.moltbook_first_comment_precision"] = _share(inf["by_record_first_comment"]["precision"])
    m["external.moltbook_later_comment_precision"] = _share(inf["by_record_later_comment"]["precision"])
    return m


def part_earlywarn():
    """The pre-registered forward test of the four main alarms and the real traces with times, from the saved results."""
    d = _saved("reports/earlywarn/summary_v23.json")
    m = {}
    for gen, tag in (("original", "original"), ("independent", "independent")):
        g = d["generators"][gen]
        rows = {r["id"]: r for r in g["main"]}
        m[f"earlywarn.coordinated_{tag}"] = g["coordinated_runs"]
        m[f"earlywarn.benign_{tag}"] = g["benign_runs"]
        m[f"earlywarn.any_before_harm_{tag}"] = rows["any_main"]["coordinated"]["before_harm"]["k"]
        m[f"earlywarn.any_fired_benign_{tag}"] = rows["any_main"]["benign"]["fired"]["k"]
        m[f"earlywarn.new_host_fired_benign_{tag}"] = rows["new_host_12h"]["benign"]["fired"]["k"]
        m[f"earlywarn.h1_holds_{tag}"] = sum(1 for h in g["hypotheses"] if h["hypothesis"] == "H1" and h["holds"])
    b = _saved("reports/earlywarn/benign_external_v23.json")
    mb = next(x for x in b["datasets"] if x["dataset"] == "moltbook-observatory")
    rows = {r["id"]: r for r in mb["benign_set"]["rows"]}
    m["earlywarn.moltbook_traces"] = mb["timed_alarms_measurable"]
    m["earlywarn.moltbook_any_fired"] = rows["any_main"]["fired"]["k"]
    m["earlywarn.moltbook_new_host_fired"] = rows["new_host_12h"]["fired"]["k"]
    return m


def part_crosscheck():
    """Deliveries found by the main and the second implementation, from the saved crosscheck."""
    d = _saved("reports/integrity/crosscheck.json")
    by = {x["dataset"]: x for x in d["datasets"]}
    rel = next(v for k, v in by.items() if k.startswith("Swarm Traces"))
    wiki, demo = by["collusion.wiki logs"], by["demo swarm"]
    return {"crosscheck.release_main": rel["A"]["deliveries"], "crosscheck.release_second": rel["B"]["deliveries"],
            "crosscheck.release_both": rel["both"], "crosscheck.release_uses_content": rel["content_test"]["A_pass"],
            "crosscheck.release_operations_differ": rel["operations"]["only_A"] + rel["operations"]["only_B"],
            "crosscheck.wiki_both": wiki["both"], "crosscheck.wiki_uses_content": wiki["content_test"]["A_pass"],
            "crosscheck.wiki_uses_content_r38b": wiki["content_test"]["later_output_R38b"]["A"],
            "crosscheck.demo_both": demo["both"]}


PART_FUNCS = {"release_core": part_release_core, "release_evaluate": part_release_evaluate, "release_attribution": part_release_attribution,
              "release_insiders": part_release_insiders, "wiki": part_wiki, "audit": part_audit, "validation": part_validation,
              "variance": part_variance, "samples": part_samples, "repo": part_repo,
              "external": part_external, "earlywarn": part_earlywarn, "crosscheck": part_crosscheck}


def _run_part(part, home):
    """One part in a fresh interpreter: a clean decisions folder and a fixed hash seed, so user state cannot leak in."""
    env = dict(os.environ, SWARM_TRACER_HOME=home, PYTHONHASHSEED="0", PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "agenttrace.tools.provenance", "_part", part], cwd=ROOT, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"computing {part} failed: {p.stderr.strip()[-800:]}")
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith("{")), None)
    if line is None:
        raise RuntimeError(f"computing {part} printed no result: {p.stdout[-300:]} {p.stderr[-300:]}")
    return json.loads(line), time.time() - t0


def dataset_available(ds):
    return all(os.path.exists(os.path.join(ROOT, rel)) for rel in DATASETS[ds]["inputs"])


def compute(datasets=None, use_cache=True, log=None):
    """-> (metrics, info). info[ds] = {"available", "inputs", "seconds", "cached", "error"}."""
    log = log or (lambda *_: None)
    datasets = list(datasets or DATASETS)
    fp = package_fingerprint()
    cache_dir = os.path.join(OUT, ".cache")
    use_cache = use_cache and SOURCE_CHECKOUT
    metrics, info, jobs = {}, {}, []
    for ds in datasets:
        d = info[ds] = {"available": dataset_available(ds), "seconds": 0.0, "cached": False, "error": None, "inputs": {}}
        if not d["available"]:
            continue
        d["inputs"] = hash_inputs(DATASETS[ds]["inputs"])
        d["key"] = sha256_text(ds, fp, json.dumps(d["inputs"], sort_keys=True), str(MANIFEST_VERSION))[:24]
        cpath = os.path.join(cache_dir, f"{ds}-{d['key']}.json")
        if use_cache and os.path.exists(cpath):
            try:
                with open(cpath, encoding="utf-8") as f:
                    metrics.update(json.load(f))
                d["cached"] = True
                continue
            except (OSError, ValueError):
                pass
        for part in PARTS[ds]:
            jobs.append((ds, part, cpath))
    if jobs:
        home = tempfile.mkdtemp(prefix="st-provenance-home-")
        got = {}
        # two rounds: the first part of each dataset loads it (and fills the session cache), the rest then start warm
        first = {ds: next(p for d, p, _ in jobs if d == ds) for ds in {d for d, _, _ in jobs}}
        for rnd in ([j for j in jobs if first[j[0]] == j[1]], [j for j in jobs if first[j[0]] != j[1]]):
            if not rnd:
                continue
            took = {}
            with ThreadPoolExecutor(max_workers=min(6, len(rnd))) as ex:
                futs = {(ds, part): ex.submit(_run_part, part, home) for ds, part, _ in rnd}
                for (ds, part), fu in futs.items():
                    try:
                        res, sec = fu.result()
                        got.setdefault(ds, {}).update(res)
                        took[ds] = max(took.get(ds, 0.0), sec)
                        log(f"    computed {part} in {sec:.1f} s")
                    except Exception as e:      # recorded; the claims of this dataset are reported as not computed
                        info[ds]["error"] = str(e)
                        log(f"    {part} FAILED: {e}")
            for ds, sec in took.items():
                info[ds]["seconds"] = round(info[ds]["seconds"] + sec, 1)
        for ds, part, cpath in jobs:
            if info[ds]["error"] or ds not in got:
                continue
            metrics.update(got[ds])
            if not SOURCE_CHECKOUT:
                continue
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(got[ds], f, sort_keys=True)
                old = sorted((x for x in os.listdir(cache_dir) if x.startswith(ds + "-")), key=lambda x: os.path.getmtime(os.path.join(cache_dir, x)))
                for x in old[:-2]:                      # keep the two newest results per dataset
                    os.remove(os.path.join(cache_dir, x))
            except OSError:
                pass
    return metrics, info


# ------------------------------------------------------------------ block claims and saved outputs

def block_diff(claim, root=None):
    """Lines of a doc section that differ from the saved output it should repeat. -> (status, [differences])."""
    import difflib
    doc_rel, start, end, src_rel = claim.block
    try:
        with open(os.path.join(root or ROOT, doc_rel), encoding="utf-8") as f:
            doc = f.read().splitlines()
    except OSError:
        return "file_missing", []
    try:
        with open(os.path.join(root or ROOT, src_rel), encoding="utf-8") as f:
            src = f.read().splitlines()
    except OSError:
        return "source_missing", []
    try:
        i = next(k for k, ln in enumerate(doc) if ln.strip() == start)
        j = next(k for k, ln in enumerate(doc) if ln.strip() == end)
    except StopIteration:
        return "anchor_missing", []
    keep = lambda lines: [ln.rstrip() for ln in lines if ln.strip() and not ln.startswith("Generated ")]
    a, b = keep(doc[i + 1:j]), keep(src)
    out = [ln for ln in difflib.unified_diff(a, b, "docs (printed)", "saved run (computed)", lineterm="", n=0) if not ln.startswith(("---", "+++", "@@"))]
    return ("ok" if not out else "disagrees"), out


def _walk_diff(saved, now, path=""):
    """Leaf-by-leaf differences between a saved output and the recomputed one (only keys present in `now`)."""
    out = []
    if isinstance(now, dict) and isinstance(saved, dict):
        for k, v in now.items():
            out += _walk_diff(saved.get(k), v, f"{path}.{k}" if path else str(k))
    elif isinstance(now, list) and isinstance(saved, list) and len(now) == len(saved):
        for i, v in enumerate(now):
            out += _walk_diff(saved[i], v, f"{path}[{i}]")
    elif isinstance(now, list) and isinstance(saved, (list, tuple)) and all(not isinstance(x, (dict, list)) for x in now):
        if list(saved) != list(now):
            out.append((path, saved, now))
    elif saved != now:
        out.append((path, saved if not isinstance(saved, (dict, list)) else f"<{type(saved).__name__} of {len(saved)}>",
                    now if not isinstance(now, (dict, list)) else f"<{type(now).__name__} of {len(now)}>"))
    return out


def saved_output_checks(metrics):
    """Do the tracked output files still hold what the code computes now? -> [(file, field, saved, recomputed)]."""
    out = []

    def load(rel):
        try:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    ev = metrics.get("release._saved.evaluation")
    if ev is not None:
        saved = load("reports/evaluation/evaluation.json")
        if saved is None:
            out.append(("reports/evaluation/evaluation.json", "(file)", "missing", "computed"))
        else:
            view = dict(saved, milestones=(saved.get("external") or {}).get("milestones"),
                        replay_signs=[{k: g.get(k) for k in ("key", "time", "ref", "harm_share_after")} for g in saved.get("replay_signs", [])])
            out += [("reports/evaluation/evaluation.json", p, a, b) for p, a, b in _walk_diff(view, ev)]
    ir = metrics.get("release._saved.identity_replay")
    if ir is not None:
        saved = load("reports/evaluation/identity_replay.json")
        if saved is None:
            out.append(("reports/evaluation/identity_replay.json", "(file)", "missing", "computed"))
        else:
            view = {"as_counted": saved.get("as_counted"), "after": saved.get("after"),
                    "after_first_time": ((saved.get("after") or {}).get("first_message") or {}).get("time")}
            out += [("reports/evaluation/identity_replay.json", p, a, b) for p, a, b in _walk_diff(view, ir)]
    we = metrics.get("wiki._saved.evaluation")
    if we is not None:
        saved = load("reports/evaluation-wiki/evaluation.json")
        if saved is None:
            out.append(("reports/evaluation-wiki/evaluation.json", "(file)", "missing", "computed"))
        else:
            out += [("reports/evaluation-wiki/evaluation.json", p, a, b) for p, a, b in _walk_diff(saved, we)]
    base = metrics.get("variance._base")
    if base is not None and "release.named_deliveries" in metrics:
        now = [metrics["release.named_deliveries"], metrics["release.named_pairs"], metrics["release.named_message_tokens"]]
        if list(base) != now:
            out.append(("reports/evaluation/count_variance.json", "base (messages, pairs, tokens)", list(base), now))
    return out


# ------------------------------------------------------------------ unregistered numbers

_NUMBER = re.compile(r"(?<![\w.#/@-])(\d[\d,]*(?:\.\d+)?)(%?)(?![\w/])")
_KEY_AFTER = re.compile(rf"\s+(?:[a-z][\w'-]*\s+){{0,2}}(?:{KEYWORDS})\b", re.I)


def scan_numbers(text):
    """Numbers in a published text that sit next to a key word, or are percentages. -> [(start, end, number, context)]."""
    out = []
    for m in _NUMBER.finditer(text):
        num = m.group(1).rstrip(",")
        if not m.group(2):
            if not _KEY_AFTER.match(text, m.end()):
                continue
            if re.fullmatch(r"(19|20)\d\d", num):        # a year
                continue
        ctx = text[max(0, m.start() - 45):m.end() + 45]
        out.append((m.start(), m.start() + len(num), num + m.group(2), ctx))
    return out


def unregistered(covered, texts):
    """covered: {file: [(start, end)]} spans of registered values. -> [{"file", "number", "context"}]."""
    out = []
    for rel in PUBLISHED:
        text = texts.get(rel)
        if text is None:
            continue
        spans = covered.get(rel, [])
        for a, b, num, ctx in scan_numbers(text):
            if any(a < e and s < b for s, e in spans):
                continue
            out.append({"file": rel, "number": num, "context": ctx})
    return out


# ------------------------------------------------------------------ build

def _block_spans(claim, texts):
    """Spans of the normalized doc covered by a block claim (so its table cells are not listed as unregistered)."""
    doc_rel, start, end, _ = claim.block
    text = texts.get(doc_rel)
    if text is None:
        return []
    i, j = text.find(normalize(start, False)), text.find(normalize(end, False))
    return [(i, j)] if 0 <= i < j else []


def evaluate_claims(claims, metrics, info, texts):
    """Every claim with its value and the state of each place. -> (entries, covered spans)."""
    entries, covered = [], {}
    for c in claims:
        ds = c.source
        e = {"id": c.id, "statement": c.statement, "dataset": ds, "computed_by": c.how}
        if c.block:
            status, diff = block_diff(c)
            e.update({"kind": "block", "value": None, "places": [{"file": c.block[0], "from": c.block[1], "to": c.block[2],
                                                                   "must_equal": c.block[3], "status": status, "differences": diff}]})
            if status in ("ok", "disagrees"):
                covered.setdefault(c.block[0], []).extend(_block_spans(c, texts))
            entries.append(e)
            continue
        have = c.id in metrics
        value = metrics.get(c.id)
        e.update({"kind": "number", "value": value, "computed": have, "format": c.fmt or default_format(value), "places": []})
        for rel, template, fmt in c.places:
            fmt = fmt or c.fmt or default_format(value)
            p = {"file": rel, "anchor": template, "format": fmt}
            if not have or value is None:
                p.update({"status": "not_computed", "must_match": None, "printed": None})
            else:
                status, printed, span = check_place(texts.get(rel), template, value, fmt)
                p.update({"status": status, "must_match": render(template, value, fmt), "printed": printed})
                if span:
                    covered.setdefault(rel, []).append(span)
            e["places"].append(p)
        entries.append(e)
    return entries, covered


def build_manifest(use_cache=True, log=print):
    t0 = time.time()
    claims = registry()
    log("computing the numbers …")
    metrics, info = compute(use_cache=use_cache, log=log)
    texts = {rel: published_text(rel) for rel in PUBLISHED}
    entries, covered = evaluate_claims(claims, metrics, info, texts)
    datasets = {}
    for ds, spec in DATASETS.items():
        d = info[ds]
        datasets[ds] = {"name": spec["name"], "path": spec["path"], "pack": spec["pack"], "command": spec["command"],
                        "available_at_build": d["available"], "error": d["error"],
                        "records": metrics.get(f"{ds}.records") if ds in ("release", "wiki") else None,
                        "inputs": d["inputs"], "related": hash_inputs([r for r in spec["related"] if os.path.exists(os.path.join(ROOT, r))]),
                        "rule_version": rule_version(spec["pack"]) if ds in HEAVY else None}
    cdir = os.path.join(PKG, "claims")
    claim_files = {f: sha256_file(os.path.join(cdir, f)) for f in sorted(os.listdir(cdir)) if f.endswith(".json") and f != "provenance.json"}
    un = unregistered(covered, texts)
    manifest = {
        "about": "Every published number: what it states, its value, the dataset and code it is computed from, and each place that prints it. "
                 "Written by `python3 -m agenttrace.tools.provenance build`; checked by `python3 -m agenttrace.tools.provenance verify`. Do not edit by hand.",
        "manifest_version": MANIFEST_VERSION,
        "package_version": package_version(),
        "git": git_state(),
        "package_fingerprint": package_fingerprint(),
        "rule_files": {f: sha256_file(os.path.join(ROOT, f)) for f in RULE_FILES},
        "user_decisions_at_build": metrics.get("release._decisions"),
        "datasets": datasets,
        "claim_files": claim_files,
        "published_files": [rel for rel in PUBLISHED if texts.get(rel) is not None],
        "claims": entries,
        "saved_outputs": [{"file": f, "field": p, "saved": a, "recomputed": b} for f, p, a, b in saved_output_checks(metrics)],
        "coverage": {"claims": len(entries), "claims_computed": sum(1 for e in entries if e.get("computed") or e["kind"] == "block"),
                     "places": sum(len(e["places"]) for e in entries),
                     "places_ok": sum(1 for e in entries for p in e["places"] if p["status"] == "ok"),
                     "unregistered_numbers": len(un),
                     "unregistered_by_file": {rel: sum(1 for u in un if u["file"] == rel) for rel in sorted({u["file"] for u in un})}},
    }
    return manifest, un, info, time.time() - t0


def write_manifest(manifest, path=MANIFEST):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def load_manifest(path=MANIFEST):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ verify

def verify_manifest(manifest, use_cache=True, root=None, compute_values=True, log=print):
    """-> {"drift": [...], "disagreements": [...], "skipped": [...], "checked": {...}, "unregistered": [...]}.

    root: check the published texts and claims files under another folder (tests); values are then not recomputed."""
    base = root or ROOT
    drift, dis, skipped = [], [], []
    checked = {"values": 0, "places": 0, "dataset_files": 0, "claim_files": 0, "blocks": 0, "saved_fields": 0}
    row = lambda kind, what, expected, found, where="": {"kind": kind, "what": what, "expected": expected, "found": found, "where": where}

    # (d) claims files
    for f, h in sorted((manifest.get("claim_files") or {}).items()):
        p = os.path.join(base, "agenttrace", "claims", f)
        if not os.path.exists(p):
            drift.append(row("claims file", f, h[:12], "missing", "agenttrace/claims/" + f))
            continue
        now = sha256_file(p)
        checked["claim_files"] += 1
        if now != h:
            drift.append(row("claims file", f, h[:12], now[:12], "agenttrace/claims/" + f))
    for f in CLAIM_FILES_REQUIRED:
        if f not in (manifest.get("claim_files") or {}):
            drift.append(row("claims file", f, "recorded in the manifest", "not recorded", "agenttrace/claims/" + f))

    # (c) dataset files, and what can be recomputed
    metrics, info = {}, {}
    can = []
    for ds, d in (manifest.get("datasets") or {}).items():
        if root is not None or not compute_values:
            continue
        if not dataset_available(ds):
            if d.get("inputs"):
                skipped.append(f"{d['name']} ({d['path']}) is not on this machine: its numbers were not re-derived and its file hashes were not checked")
            continue
        now = hash_inputs(DATASETS[ds]["inputs"])
        for f, rec in sorted((d.get("inputs") or {}).items()):
            checked["dataset_files"] += 1
            got = now.get(f)
            if got is None:
                drift.append(row("dataset file", f, rec["sha256"][:12], "missing", ds))
            elif got["sha256"] != rec["sha256"]:
                drift.append(row("dataset file", f, rec["sha256"][:12], got["sha256"][:12], ds))
        for f in sorted(set(now) - set(d.get("inputs") or {})):
            drift.append(row("dataset file", f, "not in the manifest", now[f]["sha256"][:12], ds))
        for f, rec in sorted((d.get("related") or {}).items()):
            p = os.path.join(ROOT, f)
            if os.path.exists(p):
                checked["dataset_files"] += 1
                got = sha256_file(p)
                if got != rec["sha256"]:
                    drift.append(row("dataset file", f, rec["sha256"][:12], got[:12], ds + " (related)"))
        if not d.get("available_at_build"):
            skipped.append(f"{d['name']}: the manifest was built without it, so there is no recorded value to compare")
        can.append(ds)
    if root is not None or not compute_values:
        skipped.append("values were not re-derived (texts-only check)")
    elif can:
        log("re-deriving the numbers …")
        metrics, info = compute(can, use_cache=use_cache, log=log)
        for ds in can:
            if info[ds]["error"]:
                drift.append(row("computation", ds, "runs", "failed: " + info[ds]["error"][:200], ds))

    # rule files: when the data is absent this is the only sign the rule changed after the build
    for f, h in sorted((manifest.get("rule_files") or {}).items()):
        p = os.path.join(base, f)
        now = sha256_file(p) if os.path.exists(p) else "missing"
        if now != h:
            heavy_absent = [ds for ds in HEAVY if not dataset_available(ds)] if root is None else []
            if heavy_absent or root is not None:
                drift.append(row("rule file", f, h[:12], now[:12], "changed since the build and the data is not here to re-derive the numbers"))

    # (a) values and (b) places
    texts = {}

    def text_of(rel):
        if rel not in texts:
            texts[rel] = published_text(rel, base)
        return texts[rel]
    covered = {}
    missing_files = {}
    by_id = {c.id: c for c in registry()}
    for e in manifest.get("claims") or []:
        if e["kind"] == "block":
            c = by_id.get(e["id"])
            pl = e["places"][0]
            if c is None or root is not None:
                continue
            status, diff = block_diff(c)
            checked["blocks"] += 1
            if status == "disagrees":
                (dis if pl.get("status") == "disagrees" and diff == pl.get("differences") else drift).append(
                    row("text block", e["id"], f"{pl['file']} [{pl['from']}] equals {pl['must_equal']}", f"{len(diff)} lines differ", pl["file"]))
            elif status in ("file_missing", "source_missing"):
                gone = pl["file"] if status == "file_missing" else pl["must_equal"]
                missing_files[gone] = missing_files.get(gone, 0) + 1
            elif status != "ok" and status != pl.get("status"):
                drift.append(row("text block", e["id"], pl.get("status"), status, pl["file"]))
            if status in ("ok", "disagrees"):
                covered.setdefault(pl["file"], []).extend(_block_spans(c, {pl["file"]: text_of(pl["file"])}))
            continue
        value = e.get("value")
        if e["id"] in metrics:
            checked["values"] += 1
            if metrics[e["id"]] != value:
                drift.append(row("value", e["id"], value, metrics[e["id"]], e["computed_by"]))
        elif e["dataset"] in can and not info.get(e["dataset"], {}).get("error"):
            drift.append(row("value", e["id"], value, "no longer computed", e["computed_by"]))
        for p in e["places"]:
            text = text_of(p["file"])
            if text is None:
                if p["status"] != "file_missing":
                    missing_files[p["file"]] = missing_files.get(p["file"], 0) + 1
                continue
            if p.get("must_match") is None:
                continue
            checked["places"] += 1
            m = re.search(p["must_match"], text)
            if m:
                covered.setdefault(p["file"], []).append(m.span("v"))
                if p["status"] != "ok":
                    pass                      # it was wrong at build and is right now: the manifest is stale, the text is fine
                continue
            lm = re.search(loose(p["anchor"], p["format"]), text)
            printed = lm.group("v") if lm else None
            if lm:
                covered.setdefault(p["file"], []).append(lm.span("v"))
            shown = FORMATS[p["format"]][0](value) if value is not None else None
            shown = re.sub(r"\\(.)", r"\1", shown.replace(",?", ",").replace("(?i:", "").rstrip(")")) if shown else shown
            if p["status"] in ("disagrees", "anchor_missing") and printed == p.get("printed"):
                dis.append(row("printed number" if printed is not None else "anchor not found", e["id"], shown,
                               printed if printed is not None else "(no text matches the anchor)", f"{p['file']}: {p['anchor']}"))
            else:
                drift.append(row("printed number" if printed is not None else "anchor not found", e["id"], shown,
                                 printed if printed is not None else "(no text matches the anchor)", f"{p['file']}: {p['anchor']}"))

    for f, n in sorted(missing_files.items()):
        skipped.append(f"{f} is not on this machine: {n} place(s) that print a number there were not checked")

    # saved outputs
    if metrics:
        now = [{"file": f, "field": p, "saved": a, "recomputed": b} for f, p, a, b in saved_output_checks(metrics)]
        known = {(x["file"], x["field"]): x for x in manifest.get("saved_outputs") or []}
        for x in now:
            checked["saved_fields"] += 1
            k = known.get((x["file"], x["field"]))
            (dis if k and k["saved"] == x["saved"] and k["recomputed"] == x["recomputed"] else drift).append(
                row("saved output", x["field"], x["recomputed"], x["saved"], x["file"]))
    all_texts = {rel: text_of(rel) for rel in PUBLISHED}
    un = unregistered(covered, all_texts)
    return {"drift": drift, "disagreements": dis, "skipped": sorted(set(skipped)), "checked": checked, "unregistered": un,
            "computed_datasets": can, "info": info}


# ------------------------------------------------------------------ printing

def _table(rows, cols):
    if not rows:
        return ""
    cells = [[str(r.get(c, "")) for c in cols] for r in rows]
    cap = {"where": 96, "expected": 34, "found": 44, "what": 44, "kind": 16}
    cells = [[v if len(v) <= cap.get(c, 60) else v[:cap.get(c, 60) - 1] + "…" for v, c in zip(r, cols)] for r in cells]
    w = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(cols)]
    line = lambda r: "  ".join(v.ljust(w[i]) for i, v in enumerate(r)).rstrip()
    return "\n".join([line(cols), line(["-" * x for x in w])] + [line(r) for r in cells])


def build_report(manifest, un, seconds=None):
    """A readable account of the manifest: coverage, every disagreement, the unregistered numbers."""
    cov = manifest["coverage"]
    L = ["# Provenance report", "",
         f"Manifest of {cov['claims']} registered numbers ({cov['claims_computed']} computed at build), printed in {cov['places']} places "
         f"({cov['places_ok']} print the computed value). Commit {(manifest['git'].get('commit') or '?')[:12]}"
         f"{' with uncommitted changes' if manifest['git'].get('dirty') else ''}; package {manifest.get('package_version')}." +
         (f" Build took {seconds:.0f} s." if seconds is not None else ""), ""]
    L += ["## Datasets", ""]
    for ds, d in manifest["datasets"].items():
        L.append(f"- **{ds}** ({d['name']}): " + ("available" if d["available_at_build"] else "NOT available at build, its numbers were not computed") +
                 (f"; {d['records']:,} records" if d.get("records") else "") + f"; {len(d['inputs'])} input file(s)" +
                 (f"; rule version {d['rule_version']['hash']}" if d.get("rule_version") else "") + (f"; ERROR {d['error']}" if d.get("error") else ""))
    bad = [(e, p) for e in manifest["claims"] for p in e["places"] if p["status"] == "disagrees"]
    L += ["", f"## Printed numbers that disagree with the computed ones ({len(bad)})", ""]
    if bad:
        L += ["| number | computed | printed | where |", "|---|---|---|---|"]
        for e, p in bad:
            if e["kind"] == "block":
                L.append(f"| {e['id']} | {p['must_equal']} | {len(p['differences'])} differing lines | {p['file']}, section {p['from']} |")
            else:
                L.append(f"| {e['id']} ({e['statement']}) | {e['value']} | {p['printed']} | {p['file']}: `{p['anchor']}` |")
        for e, p in bad:
            if e["kind"] == "block":
                L += ["", f"Differences for {e['id']} (`-` printed in {p['file']}, `+` in {p['must_equal']}):", "", "```"] + p["differences"] + ["```"]
    else:
        L.append("None.")
    miss = [(e, p) for e in manifest["claims"] for p in e["places"] if p["status"] in ("anchor_missing", "file_missing", "not_computed", "source_missing")]
    L += ["", f"## Places that could not be checked ({len(miss)})", ""]
    for e, p in miss:
        L.append(f"- {e['id']}: {p['status']} in {p['file']}" + (f" (`{p.get('anchor')}`)" if p.get("anchor") else ""))
    so = manifest.get("saved_outputs") or []
    L += ["", f"## Saved output files that differ from a fresh computation ({len(so)})", ""]
    for x in so:
        L.append(f"- {x['file']} `{x['field']}`: saved {x['saved']!r}, recomputed {x['recomputed']!r}")
    noplace = [e for e in manifest["claims"] if e["kind"] == "number" and not e["places"]]
    L += ["", f"## Registered numbers with no place in the scanned texts ({len(noplace)})", ""]
    for e in noplace:
        L.append(f"- {e['id']} = {e['value']!r}: {e['statement']}")
    L += ["", f"## Unregistered numbers ({len(un)})", "",
          "Numbers in the published texts that sit next to a key word (messages, agents, tokens, records, …) or are percentages, and that no "
          "registered place covers. Not errors: numbers nobody re-derives.", ""]
    for rel, n in manifest["coverage"]["unregistered_by_file"].items():
        L.append(f"- {rel}: {n}")
    return "\n".join(L) + "\n"


def write_outputs(manifest, un, seconds=None):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "provenance_report.md"), "w", encoding="utf-8") as f:
        f.write(build_report(manifest, un, seconds))
    with open(os.path.join(OUT, "provenance_unregistered.tsv"), "w", encoding="utf-8") as f:
        f.write("file\tnumber\tcontext\n")
        for u in un:
            f.write(f"{u['file']}\t{u['number']}\t{u['context']}\n")


def print_verify(res, manifest, seconds, out=sys.stdout, allow_known=False):
    w = out.write
    c = res["checked"]
    w(f"checked: {c['values']} values re-derived, {c['places']} printed places, {c['blocks']} text block(s), {c['dataset_files']} dataset file hash(es), "
      f"{c['claim_files']} claims file hash(es), {c['saved_fields']} differing saved-output field(s) in {seconds:.1f} s\n")
    for s in res["skipped"]:
        w(f"SKIPPED  {s}\n")
    cols = ["kind", "what", "expected", "found", "where"]
    if res["drift"]:
        w(f"\nDRIFT since the manifest was built ({len(res['drift'])}):\n" + _table(res["drift"], cols) + "\n")
    if res["disagreements"]:
        w(f"\nDISAGREEMENTS recorded at build and still there ({len(res['disagreements'])}): expected is the computed value, found is what is printed or saved\n" +
          _table(res["disagreements"], cols) + "\n")
    w(f"\nunregistered numbers in the published texts: {len(res['unregistered'])} (list: reports/integrity/provenance_unregistered.tsv after a build)\n")
    failed = bool(res["drift"]) or (bool(res["disagreements"]) and not allow_known)
    w(f"VERIFY {'FAILED' if failed else 'PASSED'}: {len(res['drift'])} drift, {len(res['disagreements'])} known disagreement(s)"
      f"{' (allowed)' if allow_known and res['disagreements'] else ''}, {len(res['skipped'])} skipped\n")
    return failed


def check_stage(texts_only=False):
    """One stage for agenttrace.tools.check. -> (ok, detail, seconds)"""
    t0 = time.time()
    if not os.path.exists(MANIFEST):
        return False, "no manifest: run python3 -m agenttrace.tools.provenance build", 0
    manifest = load_manifest()
    res = verify_manifest(manifest, compute_values=not texts_only, log=lambda *_: None)
    c = res["checked"]
    detail = (f"{c['values']} values re-derived, {c['places']} printed places and {c['claim_files']} claims files checked: "
              f"{len(res['drift'])} drift, {len(res['disagreements'])} printed number(s) that disagree with the computed one, {len(res['skipped'])} skipped")
    rows = [("DRIFT", x) for x in res["drift"]] + [("DISAGREES", x) for x in res["disagreements"]]
    for tag, x in rows[:12]:
        detail += f"\n      {tag} {x['what']}: expected {x['expected']}, found {x['found']} ({x['where'][:110]})"
    if len(rows) > 12:
        detail += f"\n      … {len(rows) - 12} more: python3 -m agenttrace.tools.provenance verify"
    return not rows, detail, time.time() - t0


# ------------------------------------------------------------------ command line

def cmd_build(a):
    manifest, un, info, sec = build_manifest(use_cache=not a.no_cache)
    write_manifest(manifest, a.manifest)
    write_outputs(manifest, un, sec)
    cov = manifest["coverage"]
    bad = [(e, p) for e in manifest["claims"] for p in e["places"] if p["status"] == "disagrees"]
    miss = [(e, p) for e in manifest["claims"] for p in e["places"] if p["status"] == "anchor_missing"]
    for ds, d in info.items():
        state = "not on this machine, skipped" if not d["available"] else (f"FAILED: {d['error']}" if d["error"] else
                                                                           ("from cache" if d["cached"] else f"{d['seconds']:.1f} s"))
        print(f"  {ds:11s} {state}")
    print(f"\n{cov['claims']} numbers registered, {cov['claims_computed']} computed; {cov['places']} places, {cov['places_ok']} print the computed value")
    if bad:
        print(f"\n{len(bad)} place(s) print a number that DISAGREES with the computed one:")
        rows = [{"what": e["id"], "expected": e["value"] if e["kind"] == "number" else p["must_equal"],
                 "found": p["printed"] if e["kind"] == "number" else f"{len(p['differences'])} lines differ",
                 "where": f"{p['file']}: {p.get('anchor') or p.get('from')}"} for e, p in bad]
        print(_table(rows, ["what", "expected", "found", "where"]))
    if miss:
        print(f"\n{len(miss)} place(s) whose anchor text was not found (reworded text, or a wrong anchor in the registry):")
        print(_table([{"what": e["id"], "where": f"{p['file']}: {p['anchor']}"} for e, p in miss], ["what", "where"]))
    so = manifest["saved_outputs"]
    if so:
        print(f"\n{len(so)} field(s) of saved output files differ from a fresh computation:")
        print(_table([{"what": x["field"], "expected": x["recomputed"], "found": x["saved"], "where": x["file"]} for x in so], ["what", "expected", "found", "where"]))
    print(f"\nunregistered numbers in the published texts: {cov['unregistered_numbers']}")
    print(f"wrote {os.path.relpath(a.manifest, ROOT)}, reports/integrity/provenance_report.md and provenance_unregistered.tsv in {sec:.1f} s")
    return 0


def cmd_verify(a):
    t0 = time.time()
    try:
        manifest = load_manifest(a.manifest)
    except (OSError, ValueError) as e:
        print(f"VERIFY FAILED: cannot read the manifest {a.manifest}: {e}\nRun: python3 -m agenttrace.tools.provenance build")
        return 1
    res = verify_manifest(manifest, use_cache=not a.no_cache, compute_values=not a.texts_only, log=(lambda *_: None) if a.json else print)
    sec = time.time() - t0
    try:
        if not SOURCE_CHECKOUT:
            raise OSError("installed copy")
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "provenance_verify.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in res.items() if k != "info"}, f, indent=1, ensure_ascii=False, default=str)
    except OSError:
        pass
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k != "info"}, indent=1, ensure_ascii=False, default=str))
        return 1 if res["drift"] or (res["disagreements"] and not a.allow_known) else 0
    return 1 if print_verify(res, manifest, sec, allow_known=a.allow_known) else 0


def cmd_stability(a):
    """Every part under several hash seeds: a number that moves with the seed is not reproducible."""
    parts = [p for ds in DATASETS if dataset_available(ds) for p in PARTS[ds]]
    home = tempfile.mkdtemp(prefix="st-provenance-home-")
    t0 = time.time()

    def one(part, seed):
        env = dict(os.environ, SWARM_TRACER_HOME=home, PYTHONHASHSEED=str(seed), PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
        p = subprocess.run([sys.executable, "-m", "agenttrace.tools.provenance", "_part", part], cwd=ROOT, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith("{")), None)
        if p.returncode != 0 or line is None:
            raise RuntimeError(f"{part} (seed {seed}) failed: {p.stderr.strip()[-300:]}")
        return json.loads(line)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {(p, s): ex.submit(one, p, s) for p in parts for s in a.seeds}
        res = {k: f.result() for k, f in futs.items()}
    moved = []
    for p in parts:
        base = res[(p, a.seeds[0])]
        for k in sorted(base):
            vals = [res[(p, s)].get(k) for s in a.seeds]
            if any(v != vals[0] for v in vals):
                moved.append({"what": k, "found": " | ".join(json.dumps(v, default=str)[:40] for v in vals), "where": p})
    n = sum(len(res[(p, a.seeds[0])]) for p in parts)
    if moved:
        print(_table(moved, ["what", "found", "where"]))
    print(f"STABILITY {'FAILED' if moved else 'PASSED'}: {n} values in {len(parts)} parts under hash seeds {', '.join(map(str, a.seeds))}: "
          f"{len(moved)} differ ({time.time() - t0:.0f} s)")
    return 1 if moved else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_part"]:                       # internal: one part, its numbers as one JSON line
        print(json.dumps(PART_FUNCS[argv[1]](), sort_keys=True, default=str))
        return 0
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.provenance", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, text in (("build", cmd_build, "compute every number and write the manifest"),
                           ("verify", cmd_verify, "re-derive every number and compare with the manifest and the published texts")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--manifest", default=MANIFEST)
        p.add_argument("--no-cache", action="store_true", help="recompute even when the data and the code are unchanged since the last run")
        if name == "verify":
            p.add_argument("--allow-known", action="store_true", help="exit 0 when the only problems are disagreements the build already recorded")
            p.add_argument("--texts-only", action="store_true", help="check the printed places and the claims files only; re-derive nothing")
            p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
    st = sub.add_parser("stability", help="compute every number under several hash seeds and list any that differ")
    st.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    st.set_defaults(fn=cmd_stability)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

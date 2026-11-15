"""Checks on the published site (docs/): links, redaction, and numbers.

    python3 -m agenttrace.tools.sitecheck [--docs docs] [--dataset redacted.jsonl] [--api http://localhost:8010]
                                          [--allow agenttrace/tools/sitecheck_allow.json] [--json out.json]

Exits 1 on any finding that the allowlist does not cover.

(i) Link integrity
    - every claim of every investigation has evidence, and every evidence reference (record, figure, insider
      finding) resolves in the story's bundle; the bundle holds no record the story does not cite;
    - with --dataset (the release as .jsonl or .csv with id, kind, time_utc, text): every bundle record id is in
      the dataset with the same kind, its time field (when the release has one) and its token in its text;
    - with --api (a running Swarm Tracer on that dataset): every bundle record and figure is what the tool
      reports now (time, token, agent, judgement, grade);
    - every internal href and src in docs/*.html and every relative link in docs/*.md resolves to a file
      (a link to x.html is fine when x.md exists: GitHub Pages renders it);
    - every pack file the hosted demo's static.json promises is there.
(ii) Redaction: everything under docs/ that is text is scanned for
    - key shapes (Hugging Face, OpenAI-style, AWS, GitHub, Slack, Google), JWTs, private-key headers, bearer and
      basic credentials, secrets assigned in code, URLs that carry a password;
    - IP addresses, internal host names, this machine's folders, e-mail addresses;
    - strings that look like an un-redacted form of the release's placeholders ([HF REPO 30], [CREDENTIAL 9]):
      a real Hugging Face repository path, a real bearer token;
    - Swarm Traces record text: the bundles must be built with snippets off and carry no text field, and with
      --dataset no run of 48 characters of any record's text may appear in docs/ outside the demo.
(iii) Numbers: every number on an investigation page is a value from its bundle (each sits in a data-v
    element that names its source), the story text has no other digits, and the page is exactly what the
    builder renders from the story and the bundle.

Reviewed false positives go in the allowlist file: a JSON list of {"rule", "match", "path", "reason"}, where
match is the exact matched text or /a regular expression/, and path an optional glob under docs/.
"""
import argparse
import csv
import fnmatch
import html
import json
import os
import re
import sys
import urllib.parse
from html.parser import HTMLParser

from . import smoke

ROOT = smoke.ROOT
DOCS = os.path.join(ROOT, "docs")
ALLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sitecheck_allow.json")
TEXT_EXTS = (".html", ".htm", ".md", ".json", ".js", ".css", ".txt", ".yml", ".yaml", ".svg", ".csv", ".tsv", ".xml", ".jsonl")
SHINGLE = 48            # characters of record text that count as a published snippet
WORDS = (300, 600)      # a story's length


class Finding:
    def __init__(self, area, rule, path, text, detail=""):
        self.area, self.rule, self.path, self.text, self.detail = area, rule, path, text, detail

    def as_dict(self):
        return {"area": self.area, "rule": self.rule, "path": self.path, "text": self.text, "detail": self.detail}

    def __str__(self):
        return f"[{self.area}] {self.rule}: {self.path}: {self.text[:140]}" + (f" ({self.detail})" if self.detail else "")


# ====================================================================== (ii) redaction

_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
SECRET_RULES = [
    # (rule, regex, group that is the secret)
    ("hf-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"), 0),
    ("openai-style-key", re.compile(r"\b(?:oc_)?sk-[A-Za-z0-9_-]{20,}"), 0),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), 0),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), 0),
    ("bearer-token", re.compile(r"\b[Bb]earer\s+([A-Za-z0-9._~+/=-]{16,})"), 1),
    ("basic-credentials", re.compile(r"\bBasic\s+([A-Za-z0-9+/]{16,}={0,2})(?![A-Za-z0-9])"), 1),
    ("secret-assignment", re.compile(r"(?i)\b(?:api[_-]?key|x-api-key|secret|password|passwd|access[_-]?token|auth[_-]?token)\b[\"']?\s*[:=]\s*\\?[\"']([A-Za-z0-9_\-./+=]{16,})\\?[\"']"), 1),
    ("url-with-password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@\"'<>]+:[^/\s:@\"'<>]+@[A-Za-z0-9.-]+"), 0),
    ("ip-address", re.compile(rf"(?<![\d.])(?:{_OCTET}\.){{3}}{_OCTET}(?![\d.])"), 0),
    ("ipv6-address", re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f:])"), 0),
    ("internal-hostname", re.compile(r"(?<![A-Za-z0-9_.$-])(?:[a-z0-9-]+\.)+(?:internal|corp|intranet|lan|localdomain|svc|cluster\.local)\b(?![\w(=-])"), 0),
    ("internal-hostname", re.compile(r"(?<![A-Za-z0-9_.$-])ip-\d+-\d+-\d+-\d+(?:\.[a-z0-9.-]+)?\b"), 0),
    ("internal-hostname", re.compile(r"(?<![A-Za-z0-9_-])(?:[a-z0-9-]+\.)*ace-research\.openai\.org\b"), 0),
    ("local-path", re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._-]+/|\b[A-Z]:\\\\?Users\\\\?[A-Za-z0-9._-]+"), 0),
    ("email", re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"), 0),
    # an un-redacted form of a placeholder: the release writes [HF REPO 30] or [REDACTED:...] where these have names
    ("unredacted-hf-repo", re.compile(r"huggingface\.co/(?:api/)?(?:datasets|spaces|models)/([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)"), 1),
]
# values that are not secrets whatever the page: loopback and documentation addresses, obvious fillers
SAFE = {
    "ip-address": re.compile(r"^(?:127\.\d+\.\d+\.\d+|0\.0\.0\.0|255\.255\.255\.\d+|192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+)$"),
    "email": re.compile(r"(?i)@(?:example\.(?:com|org|net)|[a-z0-9.-]+\.example|users\.noreply\.github\.com)$|^noreply@|^git@github\.com$"),
    "bearer-token": re.compile(r"^(?:x+|\.+|token|your[-_]?token|<[^>]*>)$", re.I),
    "secret-assignment": re.compile(r"^(?:x+|\.+|changeme|your[-_a-z]*|placeholder)$", re.I),
}


def is_text_file(path):
    return path.lower().endswith(TEXT_EXTS)


def walk_files(docs):
    for root, dirs, files in os.walk(docs):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules"))
        for f in sorted(files):
            yield os.path.join(root, f)


def scan_text(text, rel, rules=SECRET_RULES):
    """Findings in one file's text."""
    out, seen = [], set()
    for rule, rx, grp in rules:
        for m in rx.finditer(text):
            val = m.group(grp)
            if rule in SAFE and SAFE[rule].search(val):
                continue
            if rule == "ip-address" and _version_like(text, m):
                continue
            if (rule, val) in seen:
                continue
            seen.add((rule, val))
            line = text.count("\n", 0, m.start()) + 1
            ctx = " ".join(text[max(0, m.start() - 30):m.end() + 20].split())
            out.append(Finding("redaction", rule, rel, val, f"line {line}: …{ctx[:110]}…"))
    return out


def _version_like(text, m):
    """1.2.3.4 right after 'v', 'version' or a product name with a slash (Chrome/120.0.0.0) is a version."""
    before = text[max(0, m.start() - 12):m.start()].lower()
    return bool(re.search(r"(?:v|version\s|ver\s|/)$", before))


def scan_redaction(docs):
    out, skipped = [], []
    for p in walk_files(docs):
        rel = os.path.relpath(p, docs)
        if not is_text_file(p):
            skipped.append(rel)
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        out += scan_text(text, rel)
        if p.endswith((".html", ".htm")) and "&" in text:      # the same text with entities decoded
            have = {(f.rule, f.text) for f in out if f.path == rel}
            out += [f for f in scan_text(html.unescape(text), rel) if (f.rule, f.text) not in have]
    return out, skipped


# ---------------------------------------------------------------------- record text (snippets)

def bundle_files(docs):
    d = os.path.join(docs, "investigations", "data")
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []


def check_no_snippets(docs, allow_snippets=False):
    """The committed bundles carry ids and metadata only."""
    from .build_investigations import RECORD_FIELDS
    out = []
    for p in bundle_files(docs):
        rel = os.path.relpath(p, docs)
        with open(p, encoding="utf-8") as f:
            b = json.load(f)
        if allow_snippets:
            continue
        if b.get("snippets") != "off":
            out.append(Finding("redaction", "snippets-on", rel, f"snippets: {b.get('snippets')!r}", "the release states no licence: build with --snippets off"))
        for rid, r in (b.get("records") or {}).items():
            extra = sorted(set(r) - set(RECORD_FIELDS))
            if extra:
                out.append(Finding("redaction", "record-text-field", rel, f"{rid}: {', '.join(extra)}", "a bundle record may hold only " + ", ".join(RECORD_FIELDS)))
    return out


def norm(s):
    return " ".join(str(s).split())


def strings_of(path):
    """The text of a docs file as the reader gets it: JSON string values, HTML with entities decoded, else as is."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if path.endswith(".json"):
        try:
            out = []

            def walk(x):
                if isinstance(x, str):
                    out.append(x)
                elif isinstance(x, dict):
                    for k, v in x.items():
                        out.append(k)
                        walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)
            walk(json.loads(raw))
            return out
        except ValueError:
            return [raw]
    if path.endswith((".html", ".htm")):
        v = Visible()
        v.feed(raw)
        v.close()
        return v.out
    return [raw]


class Visible(HTMLParser):
    """What a reader of an HTML page can see or copy: its text and attribute values, not its markup, styles or scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.buf, self.off = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.off += 1
        if tag in ("p", "div", "li", "td", "th", "pre", "blockquote", "section", "article", "h1", "h2", "h3", "h4", "dd", "dt", "tr", "table", "ul", "ol", "br"):
            self.flush()
        self.out += [v for k, v in attrs if v and k in ("title", "alt", "content", "aria-label", "placeholder", "value")]

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.off:
            self.off -= 1

    def handle_data(self, data):
        if not self.off:
            self.buf.append(data)

    def flush(self):
        if self.buf:
            self.out.append("".join(self.buf))
            self.buf = []

    def close(self):
        super().close()
        self.flush()


_WORD_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]")


def windows(text, n=SHINGLE):
    """Every n-character window of text that starts at the start of a word."""
    return [text[m.start():m.start() + n] for m in _WORD_START.finditer(text) if m.start() + n <= len(text)]


def read_dataset(path, want_ids=None):
    """Yield (id, kind, time_utc, text) from the release (.jsonl, or .csv with those columns)."""
    if path.endswith(".csv"):
        csv.field_size_limit(1 << 30)
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if want_ids is None or row.get("id") in want_ids:
                    yield row.get("id"), row.get("kind"), row.get("time_utc") or None, row.get("text") or ""
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if want_ids is not None and not any(i in line[:200] for i in want_ids):
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if want_ids is None or r.get("id") in want_ids:
                    yield r.get("id"), r.get("kind"), r.get("time_utc"), r.get("text") or ""


def scan_record_text(docs, dataset, skip=("demo",), n=SHINGLE):
    """No n-character run of any record's text may appear under docs/ (the demo, which is simulated, aside).
    One finding per passage: the longest run of the docs file that is also in a record."""
    where, texts = {}, []
    for p in walk_files(docs):
        rel = os.path.relpath(p, docs)
        if rel.split(os.sep)[0] in skip or not is_text_file(p):
            continue
        for s in strings_of(p):
            s = norm(s)
            if len(s) < n:
                continue
            texts.append((rel, s))
            for m in _WORD_START.finditer(s):
                if m.start() + n <= len(s):
                    where.setdefault(s[m.start():m.start() + n], []).append((len(texts) - 1, m.start()))
    if not where:
        return []
    hits = {}                                   # (text index, offset) -> record ids
    for rid, _, _, text in read_dataset(dataset):
        t = norm(text)
        if len(t) < n:
            continue
        for m in _WORD_START.finditer(t):
            w = t[m.start():m.start() + n]
            if w in where:
                for key in where[w]:
                    ids = hits.setdefault(key, [])
                    if rid not in ids and len(ids) < 3:
                        ids.append(rid)
    out, run = [], None
    for (ti, off) in sorted(hits):
        if run and run[0] == ti and off <= run[2]:
            run[2] = off + n
            run[3] += [r for r in hits[(ti, off)] if r not in run[3]]
        else:
            if run:
                out.append(run)
            run = [ti, off, off + n, list(hits[(ti, off)])]
    if run:
        out.append(run)
    return [Finding("redaction", "record-text", texts[ti][0], texts[ti][1][a:b],
                    f"{b - a} characters that are also in record {', '.join(ids[:3])}") for ti, a, b, ids in out]


# ====================================================================== (i) links

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        for k in ("href", "src", "poster"):
            if a.get(k) is not None:
                self.refs.append((tag, k, a[k]))


def _resolve(docs, base_file, url):
    """The file an internal URL points at, or None when it is external; raises LookupError when it is missing."""
    u = urllib.parse.urlparse(url)
    if u.scheme or u.netloc or url.startswith(("#", "mailto:", "data:", "javascript:", "tel:")):
        return None
    path = urllib.parse.unquote(u.path)
    if not path:
        return None
    target = os.path.normpath(os.path.join(docs if path.startswith("/") else os.path.dirname(base_file), path.lstrip("/")))
    if not (target == docs or target.startswith(docs + os.sep)):
        if os.path.exists(target) and not path.startswith("/"):
            return None                      # a link out of docs/ into the repository (rendered by GitHub, not Pages)
        raise LookupError(url)
    cands = [target]
    if path.endswith("/") or os.path.isdir(target):
        cands = [os.path.join(target, "index.html"), os.path.join(target, "index.md"), os.path.join(target, "README.md")]
    elif target.endswith(".html"):
        cands.append(target[:-5] + ".md")
    elif not os.path.splitext(target)[1]:
        cands += [target + ".html", target + ".md"]
    for c in cands:
        if os.path.isfile(c):
            return c
    raise LookupError(url)


def check_links(docs):
    out = []
    docs = os.path.abspath(docs)
    for p in walk_files(docs):
        rel = os.path.relpath(p, docs)
        if p.endswith((".html", ".htm")):
            with open(p, encoding="utf-8", errors="replace") as f:
                raw = f.read()
            lp = Links()
            lp.feed(raw)
            for tag, attr, url in lp.refs:
                if url.startswith("#"):
                    if len(url) > 1 and urllib.parse.unquote(url[1:]) not in lp.ids and "{" not in url:
                        out.append(Finding("links", "broken-anchor", rel, url, f"<{tag} {attr}>: no element with that id on the page"))
                    continue
                try:
                    _resolve(docs, p, url)
                except LookupError:
                    out.append(Finding("links", "broken-link", rel, url, f"<{tag} {attr}>"))
        elif p.endswith(".md"):
            with open(p, encoding="utf-8", errors="replace") as f:
                raw = f.read()
            raw = re.sub(r"```.*?```", "", raw, flags=re.S)
            for m in re.finditer(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", raw):
                url = m.group(1)
                try:
                    _resolve(docs, p, url)
                except LookupError:
                    out.append(Finding("links", "broken-link", rel, url, "markdown link"))
    return out


def check_demo(docs):
    """Every pack file the static demo's manifest promises exists, and the page is switched to static mode."""
    out = []
    for p in walk_files(docs):
        if os.path.basename(p) != "static.json":
            continue
        d, rel = os.path.dirname(p), os.path.relpath(p, docs)
        try:
            with open(p, encoding="utf-8") as f:
                man = json.load(f)
        except ValueError as e:
            out.append(Finding("links", "demo-manifest", rel, str(e)))
            continue
        from .export_static import slug
        for path, n in (man.get("paths") or {}).items():
            for i in range(n):
                f = os.path.join(d, "data", f"{slug(path)}-{i}.json")
                if not os.path.isfile(f):
                    out.append(Finding("links", "demo-pack-missing", rel, os.path.relpath(f, docs), f"static.json promises {n} files for {path}"))
        if not os.path.isfile(os.path.join(d, "data", "records-index.json")):
            out.append(Finding("links", "demo-pack-missing", rel, "data/records-index.json"))
        idx = os.path.join(d, "index.html")
        if os.path.isfile(idx):
            with open(idx, encoding="utf-8") as f:
                page = f.read()
            if 'name="st-static"' not in page or page.find('src="static.js"') > page.find('src="core.js"'):
                out.append(Finding("links", "demo-not-static", os.path.relpath(idx, docs), "index.html is not switched to static mode"))
    return out


# ====================================================================== investigations: evidence and numbers

def load_investigations(docs):
    from . import build_investigations as B
    inv = os.path.join(docs, "investigations")
    if not os.path.isdir(os.path.join(inv, "stories")):
        return B, inv, [], {}
    stories = B.load_stories(inv)
    bundles = {}
    for s in stories:
        p = os.path.join(inv, "data", s["slug"] + ".json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                bundles[s["slug"]] = json.load(f)
    return B, inv, stories, bundles


def check_evidence(docs):
    """Every claim has evidence and every reference resolves in the bundle."""
    B, inv, stories, bundles = load_investigations(docs)
    out = []
    for s in stories:
        rel = f"investigations/stories/{s['slug']}.json"
        b = bundles.get(s["slug"])
        if b is None:
            out.append(Finding("links", "bundle-missing", rel, f"no investigations/data/{s['slug']}.json"))
            continue
        cited = set()
        linked = set(re.findall(r"\[\[([a-z0-9]+)\|", " ".join(x.get("p") or x.get("note") or "" for x in s["body"])))
        for cid, c in s["claims"].items():
            recs = [r["id"] if isinstance(r, dict) else r for r in c.get("records", [])]
            if not (recs or c.get("figures") or c.get("findings")):
                out.append(Finding("links", "claim-without-evidence", rel, cid))
            if cid not in linked:
                out.append(Finding("links", "claim-not-in-text", rel, cid))
            for r in recs:
                cited.add(r)
                if r not in b.get("records", {}):
                    out.append(Finding("links", "evidence-ref-unresolved", rel, f"{cid} → record {r}", "not in the bundle"))
            for k in c.get("figures", []):
                if k not in b.get("figures", {}):
                    out.append(Finding("links", "evidence-ref-unresolved", rel, f"{cid} → figure {k}", "not in the bundle"))
            for k in c.get("findings", []):
                if k not in b.get("findings", {}):
                    out.append(Finding("links", "evidence-ref-unresolved", rel, f"{cid} → finding {k}", "not in the bundle"))
        for cid in sorted(linked - set(s["claims"])):
            out.append(Finding("links", "evidence-ref-unresolved", rel, f"the text links claim {cid}", "not defined"))
        texts = [s.get("dek", "")] + [x.get("p") or x.get("note") or x.get("h") or "" for x in s["body"]]
        texts += [c.get("evidence", "") + " " + c.get("caveat", "") + " ".join(r.get("note", "") for r in c.get("records", []) if isinstance(r, dict))
                  for c in s["claims"].values()]
        for key in sorted(set(m for t in texts for m in B.PLACEHOLDER.findall(t))):
            try:
                B.value_text(key, b)
            except SystemExit as e:
                out.append(Finding("links", "evidence-ref-unresolved", rel, "{" + key + "}", str(e)))
        brel = f"investigations/data/{s['slug']}.json"
        for r in sorted(set(b.get("records", {})) - cited):
            out.append(Finding("links", "uncited-record-in-bundle", brel, r, "a bundle holds only the cited records"))
        if len(b.get("records", {})) > B.MAX_RECORDS:
            out.append(Finding("links", "too-many-records", brel, str(len(b["records"])), f"limit {B.MAX_RECORDS}"))
        for rid, r in b.get("records", {}).items():
            if r.get("id") != rid:
                out.append(Finding("links", "bundle-record-id", brel, rid, f"its id field says {r.get('id')!r}"))
            if "snippet" in r and len(r["snippet"]) > B.SNIPPET_MAX:
                out.append(Finding("redaction", "snippet-too-long", brel, rid, f"{len(r['snippet'])} characters; the limit is {B.SNIPPET_MAX}"))
        try:
            n = B.story_words(s, b)
            if not WORDS[0] <= n <= WORDS[1]:
                out.append(Finding("numbers", "story-length", rel, f"{n} words", f"a story is {WORDS[0]} to {WORDS[1]} words"))
        except SystemExit:
            pass
    return out


def check_dataset(docs, dataset):
    """Every bundle record is in the release with the same kind, time field and token."""
    _, _, stories, bundles = load_investigations(docs)
    want = {rid for b in bundles.values() for rid in b.get("records", {})}
    if not want:
        return []
    have = {rid: (kind, t, text) for rid, kind, t, text in read_dataset(dataset, want)}
    out = []
    for slug, b in bundles.items():
        rel = f"investigations/data/{slug}.json"
        for rid, r in b["records"].items():
            if rid not in have:
                out.append(Finding("links", "record-not-in-dataset", rel, rid))
                continue
            kind, t, text = have[rid]
            if kind and r.get("kind") and kind != r["kind"]:
                out.append(Finding("links", "record-differs", rel, rid, f"kind {r['kind']!r} in the bundle, {kind!r} in the dataset"))
            if t:
                if r.get("time_estimated") or norm(t).replace("T", " ")[:16] != str(r.get("time"))[:16]:
                    out.append(Finding("links", "record-differs", rel, rid, f"time {r.get('time')!r} (estimated: {r.get('time_estimated')}) in the bundle, {t!r} in the dataset"))
            elif not r.get("time_estimated") and r.get("time"):
                out.append(Finding("links", "record-differs", rel, rid, "the bundle gives a time that is not marked estimated; the dataset has no time for it"))
            if r.get("actor_kind") == "token" and r.get("actor") and r["actor"] not in text:
                out.append(Finding("links", "record-differs", rel, rid, f"token {r['actor']} is not in the record's text"))
            if "snippet" in r:
                core = r["snippet"].strip("…").strip()
                if "[HOST]" not in core and core[:60] not in norm(text):
                    out.append(Finding("links", "record-differs", rel, rid, "the snippet is not in the record's text"))
    return out


def check_api(docs, api_url):
    """Every bundle record and figure is what a running Swarm Tracer reports for the dataset now."""
    B, inv, stories, bundles = load_investigations(docs)
    api = B.Api(api_url)
    out = []
    for s in stories:
        b = bundles.get(s["slug"])
        if b is None:
            continue
        rel = f"investigations/data/{s['slug']}.json"
        try:
            now = B.build_bundle(s, api, b.get("snippets") == "on", b["produced_by"]["version"])
        except SystemExit as e:
            out.append(Finding("links", "bundle-rebuild-failed", rel, str(e)))
            continue
        for rid, r in b["records"].items():
            n = now["records"].get(rid)
            if n != r:
                diff = [k for k in sorted(set(r) | set(n or {})) if (n or {}).get(k) != r.get(k)]
                out.append(Finding("links", "record-differs", rel, rid, "differs from the tool's answer in: " + ", ".join(diff)))
        for k, f in b["figures"].items():
            if now["figures"].get(k, {}).get("value") != f.get("value"):
                out.append(Finding("numbers", "figure-differs", rel, k, f"bundle {f.get('value')!r}, tool {now['figures'].get(k, {}).get('value')!r}"))
        if now["findings"] != b["findings"]:
            out.append(Finding("links", "finding-differs", rel, "insider findings differ from the tool's answer"))
    return out


class StoryPage(HTMLParser):
    """Reads an investigation page: every data-v value, every record card, and the story text outside them."""
    SKIP_CLASSES = {"meta", "kicker", "source", "sr", "v"}
    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []            # (tag, skip?, in_story?, data-v key)
        self.values, self.rids, self.prose = [], [], []
        self._v = None

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        parent = self.stack[-1] if self.stack else (None, False, False, None)
        in_story = parent[2] or (tag == "article" and "text" in cls)
        skip = parent[1] or bool(cls & self.SKIP_CLASSES) or tag in ("sup", "script", "style") or "data-v" in a
        key = a.get("data-v")
        if key is not None:
            self._v = [key, ""]
        if a.get("data-rid"):
            self.rids.append(a["data-rid"])
        self.stack.append((tag, skip, in_story, key))

    def handle_endtag(self, tag):
        while self.stack:
            t, _, _, key = self.stack.pop()
            if key is not None and self._v:
                self.values.append(tuple(self._v))
                self._v = None
            if t == tag:
                break

    def handle_data(self, data):
        if self._v is not None:
            self._v[1] += data
        if self.stack and self.stack[-1][2] and not self.stack[-1][1]:
            self.prose.append(data)


def check_numbers(docs):
    """Numbers on the investigation pages are the bundle's."""
    B, inv, stories, bundles = load_investigations(docs)
    out = []
    files = {}
    try:
        files = B.outputs([s for s in stories if s["slug"] in bundles], bundles) if stories and len(bundles) == len(stories) else {}
    except SystemExit as e:
        out.append(Finding("numbers", "page-not-renderable", "investigations", str(e)))
    for s in stories:
        b = bundles.get(s["slug"])
        rel = f"investigations/{s['slug']}/index.html"
        p = os.path.join(inv, s["slug"], "index.html")
        if b is None:
            continue
        if not os.path.isfile(p):
            out.append(Finding("links", "page-missing", rel, "the story has no page"))
            continue
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        sp = StoryPage()
        sp.feed(raw)
        for key, text in sp.values:
            try:
                want = B.value_text(key, b)
            except SystemExit:
                out.append(Finding("numbers", "value-not-in-bundle", rel, key, f"the page shows {text!r}"))
                continue
            if norm(text) != norm(want):
                out.append(Finding("numbers", "number-differs", rel, key, f"the page shows {text!r}, the bundle says {want!r}"))
        for rid in sp.rids:
            if rid not in b["records"]:
                out.append(Finding("links", "evidence-ref-unresolved", rel, rid, "a record card with no record in the bundle"))
        for m in re.finditer(r"\S*\d\S*", " ".join(sp.prose)):
            out.append(Finding("numbers", "number-not-from-bundle", rel, m.group(0), "a number in the story text that is not a data-v value"))
        if rel[len("investigations/"):] in files and files[rel[len("investigations/"):]] != raw:
            out.append(Finding("numbers", "page-stale", rel, "the page is not what the builder renders from the story and the bundle",
                               "run python3 -m agenttrace.tools.build_investigations --from-bundles"))
        if b["citation"]["text"] != B.CITATION_TEXT:
            out.append(Finding("numbers", "citation-differs", rel, b["citation"]["text"]))
        if B.CITATION["authors"] not in html.unescape(raw) or B.CITATION["title"] not in html.unescape(raw) or "Swarm Tracer " + str(b["produced_by"]["version"]) not in raw:
            out.append(Finding("numbers", "citation-missing", rel, "the page lacks the citation or the version line"))
    if files and "index.html" in files:
        p = os.path.join(inv, "index.html")
        have = None
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                have = f.read()
        if have != files["index.html"]:
            out.append(Finding("numbers", "page-stale", "investigations/index.html", "the gallery is not what the builder renders"))
    return out


# ====================================================================== allowlist and main

def load_allow(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        if not r.get("reason"):
            raise SystemExit(f"{path}: every allowlist entry needs a reason ({r})")
    return rows


def allowed(f, allow):
    for a in allow:
        if a.get("rule") not in (None, "", "*", f.rule):
            continue
        if a.get("path") and not fnmatch.fnmatch(f.path.replace(os.sep, "/"), a["path"]):
            continue
        m = a.get("match", "")
        if m.startswith("/") and m.endswith("/") and len(m) > 2:
            if re.search(m[1:-1], f.text):
                return a
        elif m == f.text:
            return a
    return None


def run(docs=DOCS, dataset=None, api=None, allow_path=ALLOW, allow_snippets=False, log=print):
    docs = os.path.abspath(docs)
    findings, notes = [], []
    red, skipped = scan_redaction(docs)
    findings += check_evidence(docs) + check_links(docs) + check_demo(docs) + red + check_no_snippets(docs, allow_snippets) + check_numbers(docs)
    if skipped:
        ext = sorted({os.path.splitext(s)[1].lower() or "(none)" for s in skipped})
        notes.append(f"{len(skipped)} files are not text and were not scanned ({', '.join(ext)})")
    if dataset:
        findings += check_dataset(docs, dataset)
        if not allow_snippets:
            findings += scan_record_text(docs, dataset)
    else:
        notes.append("no --dataset: bundle records were not checked against the release, and docs/ was not searched for record text")
    if api:
        findings += check_api(docs, api)
    else:
        notes.append("no --api: bundle records and figures were not compared with a running Swarm Tracer")
    allow = load_allow(allow_path)
    kept, waived, used = [], [], set()
    for f in findings:
        a = allowed(f, allow)
        if a:
            waived.append(f)
            used.add(json.dumps(a, sort_keys=True))
        else:
            kept.append(f)
    unused = [a for a in allow if json.dumps(a, sort_keys=True) not in used]
    if unused:
        notes.append(f"{len(unused)} allowlist entries matched nothing: " + "; ".join(f"{a.get('rule')}: {a.get('match')}" for a in unused[:6]))
    return {"findings": kept, "waived": waived, "notes": notes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", default=DOCS)
    ap.add_argument("--dataset", help="the Swarm Traces release (.jsonl or .csv): check bundle records and search docs/ for record text")
    ap.add_argument("--api", help="a running Swarm Tracer on that dataset: compare bundle records and figures with it")
    ap.add_argument("--allow", default=ALLOW, help="allowlist of reviewed false positives (JSON)")
    ap.add_argument("--allow-snippets", action="store_true", help="accept bundles built with --snippets on (only once the reuse terms allow it)")
    ap.add_argument("--json", help="write the result as JSON here")
    a = ap.parse_args(argv)
    res = run(a.docs, a.dataset, a.api, a.allow, a.allow_snippets)
    by = {}
    for f in res["findings"]:
        by.setdefault(f.area, []).append(f)
    for area in ("links", "redaction", "numbers"):
        fs = by.get(area, [])
        print(f"{area}: " + ("ok" if not fs else f"{len(fs)} findings"))
        for f in fs[:200]:
            print("  " + str(f))
        if len(fs) > 200:
            print(f"  ... and {len(fs) - 200} more")
    for n in res["notes"]:
        print("note: " + n)
    print(f"sitecheck: {len(res['findings'])} findings, {len(res['waived'])} allowed by {os.path.relpath(a.allow) if a.allow else 'no allowlist'}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"findings": [x.as_dict() for x in res["findings"]], "waived": [x.as_dict() for x in res["waived"]], "notes": res["notes"]}, f, indent=1)
    return 1 if res["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())

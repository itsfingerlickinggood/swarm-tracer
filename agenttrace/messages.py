"""Message flow: who wrote to which channel, who read it, and how content spread.

A channel is a place agents can write to and read from: a repository, a mailbox
folder, a webhook, a command file. The pack lists channels as patterns with one capture
group (the channel's name), and a pattern that marks a record as a write. Every record
that names a channel is one operation on it: a write or a read.

A delivery is a read of a channel after a write to it by a different actor. The actor of
a record is, in order: a non-shared identity token, a handle named in the text, or the
record's own run (its thread root), so every record has an actor.

A direct message is a record the trace itself addresses to another actor (a recipient field, a
handoff span, a delegation): the strongest evidence, kept as a delivery with how = "direct
message (logged)" on the recipient's inbox place (inbox:<recipient>).

Content spread uses near-duplicate families: the same program, with ids masked, sent by
several actors. The first actor to send it is the source; later actors are adopters.
"""
import copy
import hashlib
import json
import re
from collections import Counter, defaultdict

from .reconstruct import iso, in_comment, is_action  # noqa: F401 (in_comment is part of this module's API)

TOKEN = re.compile(r"<[a-z][a-z_]*>|\w+|[^\w\s]")


# ------------------------------------------------------------------ actors

def _thread_identity(rec, res, pack):
    """The most used non-shared identity token in each thread, so a record without its
    own token (for example a reply or a decoded copy) is attributed to its thread."""
    if "_thread_ident" not in rec:
        shared = set(pack.raw.get("shared_identities", []))
        votes = defaultdict(Counter)
        for rid, toks in rec["_ids"].items():
            for t in toks:
                if t not in shared:
                    votes[res["_root"][rid]][t] += 1
        rec["_thread_ident"] = {root: c.most_common(1)[0][0] for root, c in votes.items()}
    return rec["_thread_ident"]


def actor_of(e, rec, res, pack, ids=None):
    """(actor, kind) of a record (R21). ids: the record's identity tokens when they are not rec["_ids"][e.id],
    which is the case for a record joined from fragments (R13a)."""
    shared = set(pack.raw.get("shared_identities", []))
    toks = [t for t in (rec["_ids"][e.id] if ids is None else ids) if t not in shared]
    if e.actor and e.actor in toks:
        return e.actor, "named"          # the record's own actor field
    if toks:
        return toks[0], "token"
    if pack.handles_rx:
        m = pack.handles_rx.search(e.text)
        if m:
            from .packs import family_of
            return family_of(m.group(1), pack), "handle"
    inherited = _thread_identity(rec, res, pack).get(res["_root"][e.id])
    if inherited:
        return inherited, "token_via_thread"
    return "run:" + res["_root"][e.id], "run"


# ------------------------------------------------------------------ direct messages

DIRECT_HOW = "direct message (logged)"
DIRECT_PREFIX = "inbox"


def direct_messages(events, pack, rec, res):
    """Records addressed to another actor (Event.to): sender -> recipient, with the recipient's
    reply when the trace has one (a child record by the recipient, else the recipient's next record
    in the same thread). Cached in rec; undated ones are kept with write_time None."""
    if "_direct" in rec:
        return rec["_direct"]
    addressed = [(i, e) for i, e in enumerate(events) if getattr(e, "to", None)]
    out = []
    if addressed:
        times = rec["_times"]
        children = defaultdict(list)
        thread = defaultdict(list)
        pos = {}
        for i, e in enumerate(events):
            if e.parent:
                children[e.parent].append(i)
            key = e.channel or ""
            pos[e.id] = len(thread[key])
            thread[key].append(i)
        memo = {}

        def who(j):
            if j not in memo:
                memo[j] = actor_of(events[j], rec, res, pack)[0]
            return memo[j]
        for i, e in addressed:
            a, ak = actor_of(e, rec, res, pack)
            to = str(e.to)
            if to == a:
                continue
            t = times.get(e.id)
            ok = lambda j: who(j) == to and j != i and (t is None or times.get(events[j].id) is None or times[events[j].id] >= t)
            reply = next((j for j in children.get(e.id, []) if ok(j)), None)
            if reply is None:
                lst = thread[e.channel or ""]
                k = pos[e.id]
                reply = next((j for j in lst[k + 1:k + 60] if ok(j)), None)
            rid = events[reply].id if reply is not None else e.id
            rt = times.get(rid) if reply is not None else t
            if rt is None:
                rt = t
            out.append({"channel": f"{DIRECT_PREFIX}:{to}", "from": a, "from_kind": ak, "to": to, "to_kind": "named",
                        "write_id": e.id, "read_id": rid, "write_time": t, "read_time": rt,
                        "latency_h": round((rt - t) / 3600, 2) if t is not None and rt is not None else 0,
                        "how": DIRECT_HOW, "_i": i, "_ri": reply if reply is not None else i})
    rec["_direct"] = out
    return out


def _direct_perf(direct):
    by = defaultdict(list)
    for d in direct:
        by[d["channel"]].append(d)
    out = []
    for ch, lst in by.items():
        dated = [d for d in lst if d["write_time"] is not None]
        lat = sorted(d["latency_h"] for d in dated)
        out.append({"channel": ch, "writes": len(lst), "reads": len(lst),
                    "writers": len({d["from"] for d in lst}), "readers": len({d["to"] for d in lst}),
                    "actors": len({d["from"] for d in lst} | {d["to"] for d in lst}),
                    "first_write": iso(min((d["write_time"] for d in dated), default=None)),
                    "first_read": iso(min((d["read_time"] for d in dated), default=None)),
                    "deliveries": len(dated), "overwrites": 0,
                    "median_latency_h": lat[len(lat) // 2] if lat else None,
                    "never_read": False, "read_without_write_seen": False})
    return out


# ------------------------------------------------------------------ fragments (R13a)

VERBS = ("POST", "PUT", "PATCH", "DELETE", "GET", "HEAD")
FRAGMENT_END = re.compile(r"(?:\bmethod\s*[:=]\s*|\.open\s*\(\s*)(['\"])([A-Za-z]{1,5})\Z")


def _open_verb(text):
    """(letters, quote) when the text ends inside the verb of a call (…{method:'POS, ….open('PU), else None."""
    if not text or not text[-1].isalpha():
        return None
    m = FRAGMENT_END.search(text, max(0, len(text) - 48))
    if not m:
        return None
    got = m.group(2).upper()
    return (got, m.group(1)) if any(len(v) > len(got) and v.startswith(got) for v in VERBS) else None


def _completes(cut, nxt_text):
    """True when nxt_text begins with the missing letters of a verb cut as `cut` = (letters, quote), and the same
    quote (T',headers:…)."""
    got, quote = cut
    for v in VERBS:
        if len(v) > len(got) and v.startswith(got):
            rest = v[len(got):]
            if nxt_text[:len(rest)].upper() == rest and nxt_text[len(rest):len(rest) + 1] == quote:
                return True
    return False


def _same_source(a, b):
    """Nothing in the two records' own fields says they are separate: the same kind, actor and channel, neither
    addressed to a recipient (a logged direct message is never joined), and b has no parent other than a or a's
    parent."""
    return (a.kind == b.kind and (a.actor or None) == (b.actor or None) and (a.channel or None) == (b.channel or None)
            and not getattr(a, "to", None) and not getattr(b, "to", None)
            and (not b.parent or b.parent == a.id or b.parent == a.parent))


def join_fragments(events, pack):
    """Records cut inside a verb that the next record completes, read as one record (docs/counting-rule.md R13a).

    Returns (view, parts). view is [(index, record)] in input order: a joined record stands at the index of its
    first fragment, keeps that fragment's id and fields, and has the texts of its fragments one after the other;
    the records joined into it are left out. parts is {first id: [ids joined into it]}. The records of `events`
    themselves are not changed."""
    view, parts = [], {}
    i, n = 0, len(events)
    while i < n:
        e = events[i]
        j = i + 1
        if j < n and is_action(e, pack):
            text = None
            while j < n:
                head = e.text if text is None else text
                cut = _open_verb(head)
                if cut is None or not _same_source(e, events[j]):
                    break
                tail = events[j].text
                if not _completes(cut, tail):
                    break
                text = head + tail
                j += 1
            if text is not None:
                joined = copy.copy(e)
                joined.text = text
                if not joined.time:
                    joined.time = next((x.time for x in events[i + 1:j] if x.time), None)
                parts[e.id] = [x.id for x in events[i + 1:j]]
                e = joined
        view.append((i, e))
        i = j
    return view, parts


def _joined_lookup(rec, parts):
    """(ids_of, time_of) for the records of a view: a joined record has its fragments' identity tokens, the first
    fragment's first, and the first fragment's time (a later fragment's when the first has none)."""
    ids, times = rec["_ids"], rec["_times"]
    if not parts:
        return ids.__getitem__, times.get
    ids_j, times_j = {}, {}
    for first, rest in parts.items():
        both = list(ids[first])
        for rid in rest:
            both += [tok for tok in ids[rid] if tok not in both]
        ids_j[first] = both
        times_j[first] = next((times[r] for r in [first] + rest if times.get(r) is not None), None)

    def ids_of(rid):
        return ids_j[rid] if rid in ids_j else ids[rid]

    def time_of(rid):
        return times_j[rid] if rid in times_j else times.get(rid)
    return ids_of, time_of


# ------------------------------------------------------------------ channels

def compile_channels(pack):
    """(name, place pattern, write verbs, read verbs) per channel. The read verbs (the channel's "read",
    else the pack's "read_pattern") name requests that only fetch, such as an LFS batch with
    operation 'download' or a HEAD, so a POST that merely downloads is not taken for a write."""
    out = []
    for c in pack.raw.get("channels", []):
        flags = re.I if "i" in c.get("flags", "") else 0
        out.append((c["name"], re.compile(c["pattern"], flags),
                    re.compile(c.get("write", pack.raw.get("write_pattern", r"(?!)")), re.I),
                    re.compile(c.get("read", pack.raw.get("read_pattern", r"(?!)")), re.I)))
    return out


# ------------------------------------------------------------------ tool places (R18a)

TOOL_PREFIX = "tool"
_HUMP = re.compile(r"(?<=[a-z])(?=[A-Z])")                    # readFile -> read File
_LETTERS = re.compile(r"[A-Za-z]+")                            # read_file, READ-FILE -> read, file


def compile_tool_places(pack):
    """(argument pattern, write words, read words) from the pack's tool_places, or None when it has none.
    The pattern matches one string argument of a tool call under one of the listed keys ("place": "pinboard");
    group 1 is the value as written (JSON escapes included)."""
    cfg = pack.raw.get("tool_places")
    if not isinstance(cfg, dict) or not cfg.get("keys"):
        return None
    keys = "|".join(re.escape(str(k)) for k in sorted(cfg["keys"], key=lambda k: (-len(str(k)), str(k))))
    return (re.compile(r'"(?:' + keys + r')"\s*:\s*"((?:[^"\\]|\\.){1,300})"', re.I),
            frozenset(str(w).lower() for w in cfg.get("write_words", [])),
            frozenset(str(w).lower() for w in cfg.get("read_words", [])))


def tool_op(tool, tp):
    """write, read or None for a tool by the words of its name (R18a). A name with both kinds of word writes."""
    words = {w.lower() for w in _LETTERS.findall(_HUMP.sub(" ", tool or ""))}
    if words & tp[1]:
        return "write"
    if words & tp[2]:
        return "read"
    return None


def _first_object(text):
    """(lo, hi) of the first JSON object in a text: from its first `{` to the `}` that closes it (strings are
    skipped), or to the end of the text when the object is cut. None when the text has no `{`."""
    lo = text.find("{")
    if lo < 0:
        return None
    depth, i, n, quoted = 0, lo, len(text), False
    while i < n:
        c = text[i]
        if quoted:
            if c == "\\":
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return lo, i + 1
        i += 1
    return lo, n


def _unescape(raw):
    if "\\" not in raw:
        return raw
    try:
        v = json.loads('"' + raw + '"')
    except ValueError:
        return raw
    return v if isinstance(v, str) else raw


def tool_places(e, tp, taken=()):
    """[(place, op, start, end)] for a tool call that names its place in an argument (R18a): the record has a tool
    field, the tool's name says write or read, and the first JSON object of its text gives a string under one of the
    pack's place keys. taken: spans of the text that a channel pattern of the pack already reads as a place; an
    argument that overlaps one is left to that channel."""
    tool = getattr(e, "tool", None)
    if tp is None or not tool:
        return []
    op = tool_op(tool, tp)
    if op is None:
        return []
    span = _first_object(e.text)
    if span is None:
        return []
    out, seen = [], set()
    for m in tp[0].finditer(e.text, span[0], span[1]):
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue
        name = _unescape(m.group(1)).strip()
        if name and name not in seen:
            seen.add(name)
            out.append((f"{TOOL_PREFIX}:{name}", op, m.start(), m.end()))
    return out


REQUEST_START = re.compile(r"fetch\s*\(|\.open\s*\(|new\s+XMLHttpRequest|requests\.(?:get|post|put|patch|delete|head)\s*\(|"
                           r"\bcurl\b|urlopen\s*\(|http\.request|axios\.|\$\.ajax|navigator\.sendBeacon|createElement\(['\"]form", re.I)


HTTP_WRITE = re.compile(r"['\"](POST|PUT|PATCH|DELETE)['\"]")
ASSIGNED = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*(?:[\w$.]+\s*\+\s*)?['\"`][^'\"`;]*$")


def _call_end(text, open_pos, cap=600):
    """Index just past the parenthesis that closes the call opened at or after open_pos (capped)."""
    i = text.find("(", open_pos)
    if i < 0:
        return min(len(text), open_pos + cap)
    depth, end = 0, min(len(text), i + cap)
    nx = REQUEST_START.search(text, i + 1, end)      # redaction can swallow the closing parenthesis:
    if nx:                                           # never run on into the next request
        end = nx.start()
    for k in range(i, end):
        c = text[k]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    return end


def _opts_write(text, seg, wrx, before):
    """fetch(u, o): the options sit in a variable. True when that variable's object literal has a write verb."""
    m = re.search(r",\s*([A-Za-z_$][\w$]*)\s*\)\s*$", seg)
    if not m or m.group(1) in ("false", "true", "null", "undefined", "None", "True", "False") or seg.lstrip().startswith(".open"):
        return False
    d = None
    for d in re.finditer(r"(?<![\w$.])" + re.escape(m.group(1)) + r"\s*=\s*\{", text[:before]):
        pass
    if d:
        return bool(wrx.search(text[d.start():d.start() + 300]))
    # the options are a parameter of a wrapper function (function f(p, o) { fetch(b + p, o) }):
    # the wrapper's callers carry the verb, so look at the code that follows the wrapper
    o = re.escape(m.group(1))
    param = re.search(r"function\s*[\w$]*\s*\([^)]*\b" + o + r"\b[^)]*\)\s*\{|\([^()]*\b" + o + r"\b[^()]*\)\s*=>|\b" + o + r"\s*=>",
                      text[max(0, before - 200):before])
    return bool(param and wrx.search(text[before:before + 500]))


def _helper_verb(text, pos, cap=200):
    """The verb literal ('GET', 'POST', ...) among the arguments of the helper call that holds text[pos],
    looking only inside that call's own parentheses (Q('GET', src, ...) is a read even when a POST follows
    in the next call). None when the call carries no verb literal."""
    depth, i = 0, pos + 1
    found = False
    while i > max(0, pos - cap):                  # back to the call's opening parenthesis
        i -= 1
        c = text[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                found = True
                break
            depth -= 1
    if not found:
        return None
    end = _call_end(text, i, cap + 200)
    cut = re.search(r"\n|(?<![\w.])(?:[\w.]+\.)?Request\s*\(", text[i + 1:end])   # a cut-off call must not run into the next line or call
    if cut:
        end = i + 1 + cut.start()
    m = re.search(r"['\"](GET|HEAD|POST|PUT|PATCH|DELETE)['\"]", text[i:end])
    if not m:
        if re.search(r"[(,]\s*(data|body|json)\s*=", text[i:end]):
            return "write"
        # urllib's Request(url, data, ...): a second positional argument is the body, so the request is a POST
        if re.search(r"Request\s*$", text[max(0, i - 12):i]) and POSITIONAL_DATA.match(text, i, end):
            return "write"
        return None
    return "write" if m.group(1) in ("POST", "PUT", "PATCH", "DELETE") else "read"


def _descriptor_verb(text, pos):
    """A request written as data: {"u": "<place>", "m": "POST", "b": ...}. The method key, or the presence of a
    body, decides. None when the mention is not the url of such an object."""
    if not re.search(r"['\"](?:u|url)['\"]\s*:\s*['\"][^'\"]{0,12}$", text[max(0, pos - 20):pos]):
        return None
    lo = text.rfind("{", 0, pos)
    hi = text.find("}", pos)
    obj = text[max(lo, pos - 600):(hi if hi >= 0 else len(text))][:1500] if lo >= 0 else text[max(0, pos - 300):pos + 300]
    m = re.search(r"['\"](?:m|method)['\"]\s*:\s*['\"](GET|HEAD|POST|PUT|PATCH|DELETE)['\"]", obj)
    if m:
        return "write" if m.group(1) in ("POST", "PUT", "PATCH", "DELETE") else "read"
    if re.search(r"['\"](?:b|body|data)['\"]\s*:", obj):
        return "write"
    return None


BARE_TAIL = re.compile(r"[^'\"`\s;,(){}]{0,80}\\?['\"`][ \t]*(?:;|\r?\n|$)")
CONFIG_VALUE = re.compile(r"[ \t]*(?:-[ \t]+)?[\w.-]+:[ \t]*['\"][^'\"\n]*$")   # data_files: "reference://…::https://…
URL_LITERAL = re.compile(r"['\"`](?:https?:)?//")


def _hidden_holder_written(text, start, end, wrx, cap=8000):
    """The mention ends a string literal that closes its statement (…place'; or …place' at the end of a line), so
    the place is held by a name, but the caller found no assignment it can follow (redaction or a cut swallowed
    it). The calls that use the name cannot be told apart from other calls that take their address from a
    variable. True when one of those later calls writes: the place may be what it writes to, or may only have
    been read, and the text cannot say which (docs/counting-rule.md R17). Calls whose address is a literal URL
    are another place's calls and are skipped. A quoted value of a config key on its own line (YAML
    data_files: "reference://…") is not held by a name, so R17 does not apply to it."""
    if not BARE_TAIL.match(text, end):
        return False
    if CONFIG_VALUE.match(text, text.rfind("\n", 0, start) + 1, start):
        return False                                 # the value of a key in a config file (YAML): not held by a name
    limit = min(len(text), end + cap)
    for rs in REQUEST_START.finditer(text, end, limit):
        seg_hi = _call_end(text, rs.start())
        seg = text[rs.start():seg_hi]
        if URL_LITERAL.search(seg):
            continue
        if wrx.search(seg) or _opts_write(text, seg, wrx, rs.start()):
            return True
    return False


POSITIONAL_DATA = re.compile(r"\(\s*[\w$.]+\s*,\s*(?!headers\s*=|method\s*=|origin_req_host\s*=|unverifiable\s*=|None\b)[\w$.('\"]")
HELPER_VERB_FIRST = re.compile(r"[\w$.]\(\s*['\"](POST|PUT|PATCH|DELETE)['\"]\s*,\s*[\w$.+\s]{0,30}['\"`][^'\"`();{}]{0,90}$")
CUT_IN_VERB = re.compile(r"[^)\n]{0,40}\{\s*method\s*:\s*['\"]?[A-Za-z]{0,6}\Z")   # …{method:'POS<end of record>
PATHS_INFO = re.compile(r"/paths-info\b")
REDACTION_MARKER = re.compile(r"\[[^\[\]\n]{0,80}\]")   # [HF REPO 5], [REDACTED:destination:000233]: may hold spaces


def _judge(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    """(op, lo, hi): write or read for the place mention at text[start:end], and the span of code judged.

    1. The mention sits inside a request call (fetch('…place…', {...})): the verb nearest to it decides,
       looking only at that call: never past another place mention (bounds) nor into another request.
       So a program that fetches a dataset and then POSTs what it read elsewhere reads the dataset.
    2. The mention is assigned to a variable (u='…place…'; … fetch(u, {method:'POST'})): the calls that
       use the variable decide. Any call with a write verb makes it a write; otherwise it is a read.
       Without this a commit whose URL sits in a variable looks like a read, and two actors committing
       to one dataset look like a message."""
    lo, hi = max(0, start - before), min(len(text), end + after)
    if bounds:
        lo, hi = max(lo, bounds[0]), min(hi, bounds[1])
    last = None
    for m in REQUEST_START.finditer(text, lo, start):
        last = m.start()
    direct = last is not None and not re.search(r"[;\n]", text[last:start])
    # a Git LFS batch call is a POST either way: its "operation" says whether it uploads or downloads (R6).
    # When the batch path is visible (…/info/lfs), or the place is held in a name, the operation is looked for up to
    # the end of the next request call (the body is often built first and sent by that call). When the mention sits
    # in a request call whose path the redaction swallowed, only up to the start of the next request call: reading
    # on through it (as this did before) let the body of a later commit elsewhere ({operation: 'upload'}) turn a
    # plain GET into a write.
    is_lfs = "info/lfs" in text[end:end + 40]
    nreq = REQUEST_START.search(text, end, min(len(text), end + 400))
    if direct and not is_lfs:
        region_hi = nreq.start() if nreq else min(len(text), end + 300)
    else:
        region_hi = _call_end(text, nreq.start()) if nreq else min(len(text), end + 300)
    region_lo = max(0, start - 300) if is_lfs else (last if direct else start)
    lfs = re.search(r"operation['\"]?\s*:\s*['\"](download|upload)['\"]", text[region_lo:region_hi])
    if lfs:
        return ("read" if lfs.group(1) == "download" else "write"), start, region_hi, "inferred"
    if re.match(r"/['\"`]\s*\+\s*[\w$.\[\]]+\s*\+\s*['\"`]/", text[end:end + 40]):
        return "mention", start, end, None      # …/<owner>/'+repo+'/…: the repository is a variable, so this names only an owner
    if "info/lfs" in text[end:end + 40]:
        return "mention", start, end, None      # an LFS batch whose 'operation' is not in the record: upload or download, unknown
    if PATHS_INFO.match(text, end):
        return "read", start, min(len(text), end + 160), "inferred"   # a POST to .../paths-info only asks about files (R6a)
    if not direct:
        am = ASSIGNED.search(text, max(0, start - 200), start)
        if am:
            # every place the variable is passed as an argument: fetch(u, …), x.open('POST', U), Q('GET', S), req(url, …)
            use = re.compile(r"[(,+]\s*" + re.escape(am.group(1)) + r"\s*(?=[,)+])|['\"]\{" + re.escape(am.group(1)) + r"\}['\"]")
            verdict, span = None, None
            limit = min(len(text), end + 8000)
            again = re.compile(r"(?<![\w$.])" + re.escape(am.group(1)) + r"\s*=(?!=)").search(text, end, limit)
            if again:                                  # the name is given another value: later uses are not this place
                limit = again.start()
            for um in use.finditer(text, end, limit):
                near = text[max(0, um.start() - 80):um.end() + 120]
                rs = None
                for r0 in REQUEST_START.finditer(text, max(0, um.start() - 60), um.end()):
                    rs = r0
                if rs is not None:                     # passed straight to a request call: judge that call
                    seg_hi = _call_end(text, rs.start())
                    seg = text[rs.start():seg_hi]
                    if wrx.search(seg) or _opts_write(text, seg, wrx, rs.start()):
                        return "write", rs.start(), seg_hi, "inferred"
                    if verdict is None:
                        verdict, span = "read", (rs.start(), seg_hi)
                elif _helper_verb(text, um.start()) is not None:   # passed to a helper with the verb as an argument
                    if _helper_verb(text, um.start()) == "write":
                        return "write", max(0, um.start() - 80), um.end() + 120, "inferred"
                    if verdict is None:
                        verdict, span = "read", (max(0, um.start() - 80), um.end() + 120)
                elif verdict is None:
                    verdict, span = "read", (max(0, um.start() - 80), um.end() + 120)
            if verdict:
                return verdict, span[0], span[1], "inferred"
            return "mention", start, end, None      # assigned and never passed to a call: named, not opened
        if _descriptor_verb(text, start) is None and _hidden_holder_written(text, start, end, wrx):
            return "mention", start, end, None      # held by a name we cannot see, and a later call through a name writes: undecidable
    if not direct:
        # the place is a literal argument of a helper call with the verb beside it: req('…place…', tok, 'POST', data)
        tail = re.match(r"[^();{}]{0,70}['\"](POST|PUT|PATCH|DELETE)['\"]", text[end:end + 90])
        if tail:
            return "write", start, end + tail.end(), "inferred"
        # ... or just before it, as the helper's first argument: Q('POST', '…place…', body)
        lead = HELPER_VERB_FIRST.search(text, max(0, start - 120), start)
        if lead:
            return "write", lead.start(), end, "inferred"
    if re.match(r"[^)]{0,12}\{\s*metho(?!d)", text[end:end + 30]):
        return "mention", start, end, None      # the call is cut off before its verb: unknown, so not counted
    if CUT_IN_VERB.match(text, end):
        return "mention", start, end, None      # the record ends inside the verb itself ({method:'POS): not counted (R13)
    if last is not None:
        lo = last
    nxt = REQUEST_START.search(text, end, hi)
    if nxt:
        hi = nxt.start()
    window = text[lo:hi]
    pos = start - lo

    def nearest(rx):
        best = None
        for m in rx.finditer(window):
            d = 0 if m.start() <= pos <= m.end() else min(abs(m.start() - pos), abs(m.end() - pos))
            if best is None or d < best:
                best = d
        return best
    w, r = nearest(wrx), nearest(rrx)
    dv = _descriptor_verb(text, start)
    if dv:
        return dv, start, end, "inferred"
    if w is None and r is None and len(text) - end <= 40 and ")" not in text[end:]:
        head = text[max(0, start - 120):start]
        if re.search(r"\(\s*['\"`]?[^()\n]*$", head) or re.match(r"\s*https?://\S*$", REDACTION_MARKER.sub("X", text[:end])):
            # the record ends right after the place, inside an open call (cut off before its verb) or as a bare URL
            return "mention", start, end, None
    how = "default" if (w is None and r is None) else ("call" if direct else "inferred")
    if w is None or (r is not None and r < w):
        return "read", lo, hi, how
    return "write", lo, hi, how


def judge_span(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    """(op, lo, hi): write or read for the place mention at text[start:end], and the span of code judged.
    See _judge for the rule; judge_how also says how the verb was found."""
    return _judge(text, start, end, wrx, rrx, bounds, before, after)[:3]


def judge_how(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    """(op, lo, hi, how) where how is 'call' (the verb sits in the very call that names the place),
    'inferred' (found through a variable, a helper's arguments, an LFS operation or nearby text) or
    'default' (no verb found: taken as a read). None for how when the op is 'mention'."""
    return _judge(text, start, end, wrx, rrx, bounds, before, after)


def judge_op(text, start, end, wrx, rrx, bounds=None, before=160, after=260):
    return judge_span(text, start, end, wrx, rrx, bounds, before, after)[0]


NAME_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{5,}")


def _short(key):
    return re.split(r"[~/:#]", key)[-1] if key else key


def _mention_index(events):
    """Short name of every structural channel (a page's name, a thread's id) -> its keys."""
    idx = defaultdict(set)
    for e in events:
        if e.channel:
            sh = _short(e.channel)
            if sh and len(sh) >= 6:
                idx[sh].add(e.channel)
    return idx


LFS_UPLOAD = re.compile(r"operation['\"]?\s*:\s*['\"]upload['\"]")
LFS_DOWNLOAD = re.compile(r"operation['\"]?\s*:\s*['\"]download['\"]")
LFS_OID = re.compile(r"\boid['\"]?\s*:\s*['\"]([^'\"\s]{4,})['\"]")
LFS_BATCH = re.compile(r"operation['\"]?\s*:\s*['\"](?:upload|download)['\"]")
LFS_SENT = re.compile(r"lfsFile|\.open\(\s*['\"]PUT['\"]|method\s*:\s*['\"]PUT['\"]|method\s*=\s*['\"]PUT['\"]|upload_file|\buploadId\b")


def _lfs_index(events, rec, time_of=None):
    """Per object id of a Git LFS batch: when it was first asked for with operation 'download', and the records that
    later send the object (a commit that names it as an lfsFile, a PUT). An upload batch only announces an upload;
    it is a write only when the object really goes up (R6b). With time_of, `events` is a view from join_fragments:
    [(index, record)], and time_of gives each record's time."""
    if "_lfs" in rec:
        return rec["_lfs"]
    times = rec["_times"] if time_of is None else None
    down, sent = {}, defaultdict(list)
    for i, e in (enumerate(events) if time_of is None else events):
        if "oid" not in e.text:
            continue
        oids = set(LFS_OID.findall(e.text))
        if not oids:
            continue
        t = times.get(e.id) if time_of is None else time_of(e.id)
        key = (t if t is not None else float("-inf"), i)
        if LFS_DOWNLOAD.search(e.text):
            for o in oids:
                if o not in down or key < down[o]:
                    down[o] = key
        elif not LFS_BATCH.search(e.text) and LFS_SENT.search(e.text):
            for o in oids:
                sent[o].append(key)
    rec["_lfs"] = (down, sent)
    return rec["_lfs"]


def _lfs_upload_counts(text, seg, key, lfs):
    """False for an LFS upload batch that is only a probe: its object was asked for with 'download' earlier (the file
    already existed), or no later request sends it, or no object id is visible (R6b)."""
    down, sent = lfs
    oids = set(LFS_OID.findall(seg)) or set(LFS_OID.findall(text))
    for o in oids:
        if o in down and down[o] <= key:
            continue
        if any(k > key for k in sent.get(o, ())):
            return True
    return False


def channel_ops(events, pack, rec, res):
    """One operation per channel a record touches.
    - pattern channels (from the pack): a write or a read, judged from the code around the mention
    - structural channels (the record's own page, thread, room...): a post, which reads what is
      there and writes to it
    - mentions: naming another structural channel in the text reads it
    - tool places (R18a): a tool call that names its place in an argument writes or reads it, by the tool's name"""
    chans = compile_channels(pack)
    tplaces = compile_tool_places(pack)
    shared_ids = set(pack.raw.get("shared_identities", []))
    view, parts = join_fragments(events, pack)      # R13a: before anything else, fragments become one record
    ids_of, time_of = _joined_lookup(rec, parts)
    structural = pack.raw.get("structural_channels", True)
    mentions = pack.raw.get("mention_channels", False)
    midx = _mention_index(events) if mentions else {}
    ops = []  # (channel, op, actor, actor_kind, time, index, id)
    how_of = rec.setdefault("_op_how", {})   # (record id, channel) -> how the verb was found: call, inferred, default
    for i, e in view:
        if not is_action(e, pack):
            continue  # replies and recovered copies are not actions on a channel
        found = []
        if structural and e.channel:
            # kinds the pack lists as write-only (for example a moderator's delete) change the
            # place without reading it as a participant
            op = "write" if e.kind in pack.raw.get("write_only_kinds", []) else "post"
            found.append(("place:" + e.channel, op))
        if midx:
            own_prefix = e.channel.rsplit("~", 1)[0] if e.channel and "~" in e.channel else None
            seen = set()
            for tok in sorted(set(NAME_TOKEN.findall(e.text))):
                keys = midx.get(tok)
                if not keys:
                    continue
                if own_prefix:
                    same = [k for k in keys if k.startswith(own_prefix + "~")]
                    keys = same or keys
                for k in keys:
                    if k != e.channel and k not in seen:
                        seen.add(k)
                        found.append(("place:" + k, "read"))
        seg_of = {}
        # every place mention in the record, so each one is judged only by the code between its neighbours
        spans = sorted({(m.start(), m.end()) for _n, rx, _w, _r in chans for m in rx.finditer(e.text) if m.group(1)})
        for name, rx, wrx, rrx in chans:
            ops_here = {}
            for m in rx.finditer(e.text):
                if not m.group(1) or in_comment(e.text, m.start()):
                    continue
                # judge each mention by the code around it, not the whole record: one program
                # can read one place and write another
                k = spans.index((m.start(), m.end()))
                bounds = (spans[k - 1][1] if k else 0, spans[k + 1][0] if k + 1 < len(spans) else len(e.text))
                op, slo, shi, how = judge_how(e.text, m.start(), m.end(), wrx, rrx, bounds)
                key = f"{name}:{m.group(1)}"
                if op == "mention":
                    continue
                if op == "write" and LFS_UPLOAD.search(e.text[slo:shi]) and "info/lfs" in e.text:
                    tk = time_of(e.id)
                    if not _lfs_upload_counts(e.text, e.text[slo:shi], (tk if tk is not None else float("-inf"), i),
                                              _lfs_index(view, rec, time_of)):
                        continue                      # an upload batch for an object that already existed, or never went up (R6b)
                if ops_here.get(key) != "write":
                    ops_here[key] = op
                    seg_of[key] = e.text[slo:shi]
                    how_of[(e.id, key)] = how
            found += list(ops_here.items())
        # R18a: a tool call that names its place in an argument; the tool's own name is the verb
        for key, op, _lo, _hi in tool_places(e, tplaces, spans):
            found.append((key, op))
            how_of[(e.id, key)] = "call"
        if not found:
            continue
        a, ak = actor_of(e, rec, res, pack, ids_of(e.id))
        toks = [t for t in ids_of(e.id) if t not in shared_ids] if ak == "token" else []
        for ch, op in found:
            a2 = a
            if len(toks) > 1 and ch in seg_of:
                # a record that holds several tokens: the one named in the judged call is the actor
                here = [t for t in toks if t in seg_of[ch]]
                if len(here) == 1:
                    a2 = here[0]
            ops.append((ch, op, a2, ak, time_of(e.id), i, e.id))
    # logged direct messages: the sender writes to the recipient's inbox, the recipient's reply reads it
    for d in direct_messages(events, pack, rec, res):
        ops.append((d["channel"], "write", d["from"], d["from_kind"], d["write_time"], d["_i"], d["write_id"]))
        if d["read_id"] != d["write_id"]:
            ops.append((d["channel"], "read", d["to"], d["to_kind"], d["read_time"], d["_ri"], d["read_id"]))
    return ops


def _lines(text):
    """Distinct non-trivial lines, the unit for checking whether an edit kept earlier content."""
    return {s for s in (x.strip() for x in text.splitlines()) if len(s) >= 8}


def _in_order(text, wanted, n=3, width=160):
    """Up to n of the wanted lines, in the order they appear in text (a sample to show the reader)."""
    out = []
    for x in text.splitlines():
        s = x.strip()
        if s in wanted and s not in out:
            out.append(s)
            if len(out) == n:
                break
    return [s if len(s) <= width else s[:width - 1] + "…" for s in out]


def _how(w, r):
    if r[1] == "read":      # a read by a tool call (R18a) is a read in code: the verb is the call's own name
        return "read in code" if not w[0].startswith("place:") else "named the place"
    return "posted after it"


GRADES = ("direct", "inferred", "weak")


def grade_of(d, w, r, how, coarse=None, estimated=None):
    """One confidence grade for a delivery from the write op w and read op r.
    direct   the verb of the write and of the read both sit in the very call that names the place
             (or the trace itself says the record posted there)
    inferred a verb was found, but through a variable, a helper's arguments, an LFS operation or text nearby
    weak     a default: no verb found for one side, a coarse place the redaction may have merged, or a time
             estimated while the two records are more than an hour apart"""
    hw, hr = how.get((w[6], d["channel"])), how.get((r[6], d["channel"]))
    if "default" in (hw, hr):
        return "weak"
    if coarse is not None and coarse(d["channel"]):
        return "weak"
    if estimated is not None and (estimated(w[6]) or estimated(r[6])) and d["latency_h"] > 1:
        return "weak"
    if (w[1] == "post" or hw == "call") and (r[1] == "post" or hr == "call"):
        return "direct"
    return "inferred"


def _lists_token(text, actor):
    """True when the text names the actor's own token (a credential marker or a long handle), as a whole word."""
    if len(actor) < 6 or actor.startswith("run:") or actor not in text:
        return False
    return re.search(r"(?<![\w])" + re.escape(actor) + r"(?![\w])", text) is not None


def deliveries(ops, fam=None, texts=None, how=None, coarse=None, estimated=None, bodies=None, added_out=None):
    """Link each read to the latest earlier write on the same channel by another actor.
    Order is by time when both records are dated; otherwise the pair is 'order unknown'.

    texts: given when each post holds the whole place (a wiki edit sends the full page).
    Then a later post is evidence of reading an earlier one only if it keeps some of the lines
    the earlier post added. A post that drops all of them may have been written without
    seeing it, so it is returned as an overwrite, not a delivery.

    bodies: record id -> text, given so that a read whose record lists the writer's own token (a loop over
    a token list that contains it) is not taken as another actor reading the write (R23a).

    added_out: a dict that is filled with {(channel, record id): the lines that post added}, when texts is given
    (the written-content test reads them: what a full-body post wrote is what it added, R38b)."""
    by_ch = defaultdict(list)
    for o in ops:
        by_ch[o[0]].append(o)
    out, unknown_order = [], 0
    overwrites = []
    perf = []
    same_program = [0]
    rereads = [0]
    for ch, lst in by_ch.items():
        writes = [o for o in lst if o[1] in ("write", "post")]
        reads = [o for o in lst if o[1] in ("read", "post")]
        dated_w = sorted((o for o in writes if o[4] is not None), key=lambda o: o[4])
        added = {}
        if texts is not None:
            # what each post added to the place, compared with the post just before it
            posts = sorted((o for o in lst if o[1] == "post"),
                           key=lambda o: (o[4] if o[4] is not None else float("inf"), o[5]))
            before = set()
            for o in posts:
                now = _lines(texts.get(o[6], ""))
                added[o[6]] = now - before
                before = now
            if added_out is not None:
                added_out.update(((ch, rid), lines) for rid, lines in added.items())
        delivered = 0
        over_start = len(overwrites)
        latencies = []
        got = set()  # (write, reader) already delivered: reading the same write again is one message
        reads = sorted(reads, key=lambda o: (o[4] is None, o[4] or 0, o[5]))
        for r in reads:
            if r[4] is None:
                if any(w[2] != r[2] for w in writes):
                    unknown_order += 1
                continue
            prior = [w for w in dated_w if w[4] <= r[4] and w[2] != r[2] and w[6] != r[6]]
            if bodies is not None and prior:
                text_r = bodies.get(r[6], "")
                prior = [w for w in prior if not (w[3] == "token" and _lists_token(text_r, w[2]))]
            if fam:
                # the same program rerun under another token is one sender retrying, not a message
                same = [w for w in prior if fam.get(w[6]) and fam.get(w[6]) == fam.get(r[6])]
                if same and len(same) == len(prior):
                    same_program[0] += 1
                prior = [w for w in prior if not (fam.get(w[6]) and fam.get(w[6]) == fam.get(r[6]))]
            if prior:
                w = prior[-1]
                if (w[6], r[2]) in got:
                    rereads[0] += 1
                    continue
                got.add((w[6], r[2]))
                d = {"channel": ch, "from": w[2], "from_kind": w[3], "to": r[2], "to_kind": r[3],
                     "write_id": w[6], "read_id": r[6], "write_time": w[4], "read_time": r[4],
                     "latency_h": round((r[4] - w[4]) / 3600, 2), "how": _how(w, r)}
                if texts is not None and w[1] == "post" and r[1] == "post":
                    new = added.get(w[6], set())
                    if new:
                        kept = new & _lines(texts.get(r[6], ""))
                        if not kept:
                            d["how"] = f"dropped all {len(new)} lines it added"
                            d["lines"] = _in_order(texts.get(w[6], ""), new)
                            overwrites.append(d)
                            continue
                        d["how"] = f"kept {len(kept)} of {len(new)} lines it added"
                        d["lines"] = _in_order(texts.get(r[6], ""), kept)
                    else:
                        d["how"] = "edited after it (it added no lines to compare)"
                if how is not None:
                    d["grade"] = grade_of(d, w, r, how, coarse, estimated)
                out.append(d)
                delivered += 1
                latencies.append((r[4] - w[4]) / 3600)
        first_w = dated_w[0][4] if dated_w else None
        first_r = min((r[4] for r in reads if r[4] is not None), default=None)
        perf.append({
            "channel": ch, "writes": len(writes), "reads": len(reads),
            "writers": len({o[2] for o in writes}), "readers": len({o[2] for o in reads}),
            "actors": len({o[2] for o in lst}),
            "first_write": iso(first_w), "first_read": iso(first_r),
            "deliveries": delivered,
            "overwrites": len(overwrites) - over_start,
            "median_latency_h": round(sorted(latencies)[len(latencies) // 2], 2) if latencies else None,
            # written, but never read by an actor other than its writers
            "never_read": len(writes) > 0 and delivered == 0, "read_without_write_seen": len(writes) == 0,
        })
    return out, perf, unknown_order, same_program[0], overwrites, rereads[0]


# ------------------------------------------------------------------ written content

CONTENT_DF_MAX = 5      # a term found in more records than this is boilerplate, not what one actor wrote
CONTENT_MIN_LEN = 8     # shortest term that can show a reader used what was written
_TERM = re.compile(r"\[[A-Za-z][A-Za-z ]*:[A-Za-z_]+:\d+\]|[A-Za-z0-9_][A-Za-z0-9_.\-/]{%d,}" % (CONTENT_MIN_LEN - 1))
_CRED = re.compile(r"\[CREDENTIAL[^\]]*\]")


def _terms(text, drop):
    """Terms of a record that can be quoted: long identifiers, paths, file names, numbered redaction markers. What
    the record uses to address the place (its URL, its owner) and credentials are left out."""
    for rx in drop:
        text = rx.sub(" ", text)
    return set(_TERM.findall(_CRED.sub(" ", text)))


# R38b: a term of the write found in the reader's later output. The shapes that count as distinctive:
LATER_NUMBER_MIN = 5    # a number of this many digits or more
_DTERM = re.compile(r"\[[A-Za-z][A-Za-z _:]*[ :]\d+\]"                              # a numbered redaction marker
                    r"|[A-Za-z0-9_](?:[A-Za-z0-9_.\-/]{3,}[A-Za-z0-9_])")             # a run, dots hyphens slashes at its ends left off
_INVENTED = re.compile(r"[0-9_A-Z]")       # after the first character: a digit, an underscore or a capital
_DATED = re.compile(r"\d{4}-\d\d-\d\d")    # 2026-05-26T13: a date says when, not what


def _is_distinctive(term):
    """A numbered redaction marker that is not a credential; a run of 8 or more characters that holds a digit, an
    underscore or a capital letter after its first character and does not begin with a date; a number of
    LATER_NUMBER_MIN or more digits. A plain word is not distinctive, however long, and neither is a compound of
    plain words (field-value, post/share, example.com/hello)."""
    if term[0] == "[":
        return not term.startswith("[CREDENTIAL")
    if term.isdigit():
        return len(term) >= LATER_NUMBER_MIN
    return len(term) >= CONTENT_MIN_LEN and _INVENTED.search(term, 1) is not None and not _DATED.match(term)


def distinctive_terms(text, drop=()):
    """The distinctive terms of a text (R38b). drop: patterns whose matches are left out first (the place's address)."""
    for rx in drop:
        text = rx.sub(" ", text)
    return {t for t in _DTERM.findall(text) if _is_distinctive(t)}


def _without_place_arguments(text, tp):
    """The text with every place argument of its first JSON object blanked (R18a: "place": "pinboard"): the address
    of a place is not content."""
    span = _first_object(text) if tp else None
    if span is None:
        return text
    return text[:span[0]] + tp[0].sub(" ", text[span[0]:span[1]]) + text[span[1]:]


_JSON_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"(\s*:)?')        # every string in turn; group 2 is set for a key


def what_was_written(text, tool, tp):
    """The content of a record (R38). For a tool call whose text holds a JSON object: the strings that are not keys in
    its first JSON object, escapes decoded, without the place arguments. The tool's name and the names of its
    arguments are the tool's vocabulary, the same in every call, so they are not what this actor wrote.
    Any other record: its text, without the place arguments of its first JSON object."""
    span = _first_object(text) if tool else None
    if span is None:
        return _without_place_arguments(text, tp)
    body = text[span[0]:span[1]]
    if tp:
        body = tp[0].sub(" ", body)
    return "\n".join(_unescape(v) for v, is_key in _JSON_STRING.findall(body) if not is_key)


def _later_output_test(events, pack, todo, who, time_of):
    """R38b for the deliveries in todo ({index: (delivery, distinctive terms of the write)}): {index: [(term, record)]},
    the terms found in a later record of the reader and the first such record, for those that pass the guards.

    later record of the reader   an action record (R2) whose actor (R21) is the reader, dated, after the read record
                                 (a later time, or the same time and later in the input), whose parent is not the read
                                 record (the answer to a read is what was fetched, not what the reader did with it)
    guard 1, new at the write    no record before the write record by an actor other than the writer holds the term
    guard 2, not the reader's    no record of the reader before the read holds it, and the read record does not
    A record without a time counts as before."""
    needed = set().union(*[terms for _d, terms in todo.values()]) if todo else set()
    if not needed:
        return {}
    readers = {d["to"] for d, _t in todo.values()}
    pos = {}
    first = {}          # term -> {actor: its earliest record holding the term}, the two earliest actors only
    mine = defaultdict(list)   # reader -> [(key, record id, terms held, is an action, parent)]
    held_by = {}        # record id -> needed terms it holds (records of a delivery only)
    wanted = {d["write_id"] for d, _t in todo.values()} | {d["read_id"] for d, _t in todo.values()}
    never = float("-inf")
    for i, e in enumerate(events):
        if e.id in wanted:
            pos[e.id] = i
        if len(e.text) < LATER_NUMBER_MIN:
            continue
        held = needed.intersection(_DTERM.findall(e.text))
        if not held:
            continue
        if e.id in wanted:
            held_by[e.id] = held
        t = time_of(e.id)
        key = (never if t is None else t, i)
        a = who(e)
        for term in held:
            f = first.setdefault(term, {})
            if a in f:
                if key < f[a]:
                    f[a] = key
            else:
                f[a] = key
                if len(f) > 2:
                    del f[max(f, key=f.get)]
        if a in readers:
            mine[a].append((key, e.id, held, is_action(e, pack), e.parent))
    out = {}
    for n, (d, terms) in todo.items():
        w, r = d["write_id"], d["read_id"]
        if w not in pos or r not in pos:
            continue
        wkey, rkey = (d["write_time"], pos[w]), (d["read_time"], pos[r])
        terms = terms - held_by.get(r, set())                                         # guard 2: the read names it already
        terms = {x for x in terms                                                     # guard 1: new at the write
                 if not any(k < wkey for a, k in first.get(x, {}).items() if a != d["from"])}
        if not terms:
            continue
        had, later = set(), {}
        for key, rid, held, act, parent in mine.get(d["to"], ()):
            if rid == r:
                continue
            if key < rkey:
                had |= held
            elif act and parent != r:
                for x in held & terms:
                    if x not in later or key < later[x][0]:
                        later[x] = (key, rid)
        got = sorted(((x, later[x][1]) for x in later if x not in had), key=lambda xr: (later[xr[0]][0], -len(xr[0]), xr[0]))
        if got:
            out[n] = got
    return out


def written_content_test(events, pack, dels, who=None, time_of=None, added=None):
    """For each delivery that is not a logged direct message: did the reader use something the writer wrote?

    Of a tool call only the values of its arguments are content (what_was_written), in R38a and R38b alike.
    R38a  the read record quotes it: a term that appears in both records, is not part of the place's address and is
          rare in the trace (found in at most CONTENT_DF_MAX records)
    R38b  the reader's later output holds it: a distinctive term of the write record found in a later record of the
          reader, under the guards of _later_output_test (needs who: record -> actor, and time_of: record id -> time)
    A wiki edit that kept lines the writer added counts as used (R29). Adds d["uses_content"], d["shared_terms"] (up to
    3), and for a pass d["content_how"] (and d["used_in"], the reader's record, for R38b) to each delivery, and returns
    how many deliveries are checked and how many pass. added: {(channel, write record id): lines the post added}
    from deliveries(), for packs whose posts hold the whole place."""
    by_id = {e.id: e.text for e in events}
    tool_of = {e.id: e.tool for e in events if getattr(e, "tool", None)}
    added = added or {}
    drop = [rx for _n, rx, _w, _r in compile_channels(pack)]
    tp = compile_tool_places(pack)
    cand, todo = {}, {}
    needed = set()
    for n, d in enumerate(dels):
        if d.get("how") == DIRECT_HOW:
            continue
        if str(d.get("how", "")).startswith("kept "):
            d["uses_content"], d["shared_terms"], d["content_how"] = True, [], "kept lines"
            continue
        tools = {tool_of.get(d["write_id"]), tool_of.get(d["read_id"])}
        w = what_was_written(by_id.get(d["write_id"], ""), tool_of.get(d["write_id"]), tp)
        r = what_was_written(by_id.get(d["read_id"], ""), tool_of.get(d["read_id"]), tp)
        both = (_terms(w, drop) & _terms(r, drop)) - tools
        cand[n] = both
        needed |= both
        if who is not None and time_of is not None:
            # what the writer wrote: the lines it added when each post holds the whole place, else its record
            new = added.get((d["channel"], d["write_id"]))
            todo[n] = (d, distinctive_terms(w if new is None else "\n".join(sorted(new)), drop) - tools)
    df = Counter()
    if needed:
        for e in events:
            if len(e.text) < CONTENT_MIN_LEN:
                continue
            for x in needed.intersection(_TERM.findall(e.text)):
                df[x] += 1
    later = _later_output_test(events, pack, todo, who, time_of) if todo else {}
    checked = passed = 0
    for n, d in enumerate(dels):
        if n not in cand:
            if d.get("uses_content"):
                checked += 1
                passed += 1
            continue
        rare = sorted(x for x in cand[n] if df[x] <= CONTENT_DF_MAX)
        if rare:
            d["uses_content"], d["shared_terms"], d["content_how"] = True, rare[:3], "quoted in the read"
        elif n in later:
            d["uses_content"], d["shared_terms"] = True, [x for x, _rid in later[n][:3]]
            d["content_how"], d["used_in"] = "in the reader's later output", later[n][0][1]
        else:
            d["uses_content"], d["shared_terms"] = False, []
        checked += 1
        passed += 1 if d["uses_content"] else 0
    return checked, passed


# ------------------------------------------------------------------ content spread

def _norm(text):
    t = re.sub(r"\[([A-Za-z][A-Za-z _\-]*)(?::[^\]]*)?\]", lambda m: " <" + re.sub(r"[^a-z]+", "_", m.group(1).lower()).strip("_") + "> ", text)
    t = re.sub(r"\b[0-9a-fA-F]{8,}\b", " <h> ", t)
    t = re.sub(r"\b\d+\b", " <n> ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def families(events, kinds=None):
    """Exact families of normalized text. Cheap and conservative: only copies whose text is
    identical after masking ids, numbers and hex count as the same content."""
    fam = {}
    for e in events:
        if kinds and e.kind not in kinds:
            continue
        n = _norm(e.text)
        if len(TOKEN.findall(n)) < 12:
            continue  # very short texts are too generic to say anything moved
        fam[e.id] = hashlib.sha1(n.encode("utf-8", "replace")).hexdigest()[:12]
    return fam


def program_prefix(events, n=60):
    """Records whose first n normalized tokens match are the same program, even if one
    copy was cut short when it was reassembled."""
    out = {}
    for e in events:
        toks = TOKEN.findall(_norm(e.text))
        if len(toks) >= 20:
            out[e.id] = hashlib.sha1(" ".join(toks[:n]).encode("utf-8", "replace")).hexdigest()[:12]
    return out


def content_spread(events, pack, rec, res, kinds=None, written=None):
    """Programs (normalized code) run under more than one named actor. Each entry says whether the program
    is routine: it writes to no place the pack lists, reads no place that some actor in the trace wrote to
    (written: the set of such places), and does nothing the pack counts as harmful. The evaluation's own
    submit call, or two agents fetching the same public file, are routine. Routine reuse is listed but is not
    a sign of shared control."""
    times = rec["_times"]
    chans = compile_channels(pack)
    tplaces = compile_tool_places(pack)
    intents = rec.get("_intents", {})
    harm = set(getattr(pack, "harm", None) or [])
    by_id = {e.id: e for e in events}

    def touches(rid):
        e = by_id.get(rid)
        if e is None:
            return False
        if intents.get(rid) in harm:
            return True
        for name, rx, wrx, rrx in chans:
            for m in rx.finditer(e.text):
                if not m.group(1) or in_comment(e.text, m.start()):
                    continue
                if judge_op(e.text, m.start(), m.end(), wrx, rrx) == "write":
                    return True
                if written is None or f"{name}:{m.group(1)}" in written:
                    return True
        for key, op, _lo, _hi in tool_places(e, tplaces):       # R18a places count like the pack's own
            if op == "write" or written is None or key in written:
                return True
        return False
    fam = families(events, kinds)
    groups = defaultdict(list)
    for i, e in enumerate(events):
        f = fam.get(e.id)
        if f:
            a, ak = actor_of(e, rec, res, pack)
            groups[f].append((times.get(e.id), i, e.id, a, ak))
    out = []
    for f, lst in groups.items():
        dated = sorted((x for x in lst if x[0] is not None), key=lambda x: (x[0], x[1]))
        known = [x for x in dated if x[4] != "run"]
        actors_known = []
        for x in known:
            if x[3] not in actors_known:
                actors_known.append(x[3])
        if len(actors_known) < 2:
            continue
        firsts = {}
        for x in known:
            firsts.setdefault(x[3], x)
        src = firsts[actors_known[0]]
        adopters = [{"actor": a, "time": iso(firsts[a][0]), "record": firsts[a][2],
                     "hours_after_source": round((firsts[a][0] - src[0]) / 3600, 2)} for a in actors_known[1:]]
        out.append({"family": f, "copies": len(lst), "dated_copies": len(dated), "source": actors_known[0],
                    "source_time": iso(src[0]), "source_record": src[2], "adopters": adopters,
                    "actors": len(actors_known),
                    "routine": not any(touches(x[2]) for x in lst[:8])})
    out.sort(key=lambda r: (-r["actors"], -r["copies"]))
    return out


# ------------------------------------------------------------------ main

def _how_group(how):
    return "kept earlier content" if how.startswith("kept ") else how

def message_flow(events, pack, rec, res):
    ops = channel_ops(events, pack, rec, res)
    # R13a: the rule reads fragments as one record, so everything below that reads a record's text (R23a, R27, R29,
    # R38) reads the joined text; `records` leaves out the records joined into an earlier one
    view, parts = join_fragments(events, pack)
    records = [e for _i, e in view] if parts else events
    bodies = {e.id: e.text for e in records}
    texts = bodies if pack.raw.get("full_body_posts") else None
    inferred = [o for o in ops if not o[0].startswith(DIRECT_PREFIX + ":")]
    coarse = [re.compile(p) for p in pack.raw.get("coarse_channels", [])]
    is_coarse = lambda ch: any(r.search(ch) for r in coarse)
    by_id = {e.id: e for e in records}
    time_of = _joined_lookup(rec, parts)[1]
    est = lambda rid: rid in by_id and not by_id[rid].time and time_of(rid) is not None
    added = {}
    dels, perf, unknown, same_prog, overwrites, rereads = deliveries(inferred, program_prefix(records), texts,
                                                                       rec.get("_op_how", {}), is_coarse, est, bodies, added)
    # the written-content test: does the reader quote or use what the writer wrote? (kept separate from the count)
    ids_of = _joined_lookup(rec, parts)[0]
    content_checked, content_used = written_content_test(records, pack, dels, lambda e: actor_of(e, rec, res, pack, ids_of(e.id))[0],
                                                         time_of, added)
    # logged direct messages are deliveries as they stand: no inference needed
    direct = direct_messages(events, pack, rec, res)
    dels = dels + [{**{k: v for k, v in d.items() if not k.startswith("_")}, "grade": "direct"} for d in direct if d["write_time"] is not None]
    perf = perf + _direct_perf(direct)
    over_pairs = Counter((d["from"], d["to"]) for d in overwrites)
    actor_kinds = Counter()
    seen = set()
    for o in ops:
        if o[2] not in seen:
            seen.add(o[2])
            actor_kinds[o[3]] += 1
    pair = Counter()
    pair_ch = defaultdict(set)
    pair_first = {}
    for d in dels:
        k = (d["from"], d["to"])
        pair[k] += 1
        pair_ch[k].add(d["channel"])
        pair_first[k] = min(pair_first.get(k, d["read_time"]), d["read_time"])
    known_pairs = [k for k in pair if not k[0].startswith("run:") and not k[1].startswith("run:")]
    # token_via_thread counts as named
    lat = sorted(d["latency_h"] for d in dels)
    by_type = defaultdict(lambda: {"channels": 0, "writes": 0, "reads": 0, "deliveries": 0, "never_read": 0})
    for p in perf:
        t = p["channel"].split(":", 1)[0]
        b = by_type[t]
        b["channels"] += 1
        b["writes"] += p["writes"]
        b["reads"] += p["reads"]
        b["deliveries"] += p["deliveries"]
        b["never_read"] += 1 if p["never_read"] else 0
    action_kinds = pack.raw.get("action_kinds")
    written = {o[0] for o in ops if o[1] in ("write", "post")}
    spread = content_spread(events, pack, rec, res, set(action_kinds) if action_kinds else None, written)
    # channels the pack marks as coarse (for example a redaction that keeps only the owner)
    # may merge several places, so a write and a read there may not be the same message
    named = [d for d in dels if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    first_known_delivery = min((d for d in named if not is_coarse(d["channel"])), key=lambda d: d["read_time"], default=None)
    first_any_named = min(named, key=lambda d: d["read_time"], default=None)
    harm_t = rec.get("_harm_times", [])
    named_share = None
    if first_known_delivery and harm_t:
        T = first_known_delivery["read_time"]
        named_share = round(sum(1 for x in harm_t if x > T) / len(harm_t), 3)
    return {
        "harm_share_after_first_named_delivery": named_share,
        "operations": len(ops),
        "records_on_channels": len({o[6] for o in ops}),
        "channels": len(perf),
        "channel_types": {k: dict(v) for k, v in by_type.items()},
        "actors_on_channels": dict(actor_kinds),
        "deliveries": len(dels),
        "deliveries_write_then_read": len(dels),
        "deliveries_reader_uses_content": content_used + sum(1 for d in direct if d["write_time"] is not None),
        "deliveries_content_checked": content_checked,
        "deliveries_exact_place": sum(1 for d in dels if not is_coarse(d["channel"])),
        "deliveries_order_unknown": unknown,
        "direct_messages": sum(1 for d in direct if d["write_time"] is not None),
        "direct_messages_undated": sum(1 for d in direct if d["write_time"] is None),
        "reads_dropped_as_same_program": same_prog,
        "deliveries_between_named_actors": sum(pair[k] for k in known_pairs),
        "actor_pairs": len(pair),
        "named_actor_pairs": len(known_pairs),
        "latency_hours": {"median": lat[len(lat) // 2] if lat else None,
                          "p90": lat[int(len(lat) * 0.9)] if lat else None},
        "first_named_delivery": ({k: (iso(v) if k.endswith("_time") else v) for k, v in first_known_delivery.items()}
                                 if first_known_delivery else None),
        "first_named_delivery_any_channel": ({k: (iso(v) if k.endswith("_time") else v) for k, v in first_any_named.items()}
                                             if first_any_named else None),
        "coarse_channel_deliveries": sum(1 for d in dels if is_coarse(d["channel"])),
        "top_pairs": [{"from": a, "to": b, "deliveries": n, "channels": len(pair_ch[(a, b)]),
                       "first": iso(pair_first[(a, b)])}
                      for (a, b), n in sorted(((k, pair[k]) for k in known_pairs),
                                              key=lambda kv: (-kv[1], pair_first[kv[0]]))[:60]],
        "top_channels": sorted(perf, key=lambda p: (-p["deliveries"], -p["actors"]))[:40],
        "content_spread": spread[:40],
        "_channels": sorted(perf, key=lambda p: (-p["deliveries"], -p["actors"])),
        "_content_spread": spread,
        "content_families_moving": len(spread),
        "deliveries_by_grade": dict(Counter(d.get("grade", "weak") for d in dels)),
        "deliveries_by_how": dict(Counter(_how_group(d["how"]) for d in dels)),
        "overwrites": len(overwrites),
        "repeat_reads": rereads,
        # R13a: records cut inside a verb and completed by the next record, counted as one record under the first id
        "joined_fragments": [{"record": first, "continued_in": rest} for first, rest in parts.items()],
        "top_overwrite_pairs": [{"from": a, "to": b, "overwrites": n} for (a, b), n in over_pairs.most_common(15)],
        "_deliveries": dels,
        "_overwrites": overwrites,
    }

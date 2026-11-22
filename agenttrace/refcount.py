"""A second, separately written count of deliveries, to check agenttrace/messages.py against.

    from agenttrace import refcount
    out = refcount.count(events, pack, rec, res)      # out["deliveries"]: [{place, write_id, read_id, ...}]

It implements docs/counting-rule.md (statements R1 to R39, including the v2.2.0 changes R6a, R6b, R23a, R38 and
R39, R13a, the joining of a record cut inside a verb with the record that completes it, and the v2.3.0 statements
R18a, a tool call that names its place, and R38b, the reader's later output) and nothing else. It does not import messages.py. It takes from the rest of the tool only what is not the
counting rule: the loaded records, the pack (its place patterns, verb vocabulary and coarse places), each
record's identity tokens and time (rec["_ids"], rec["_times"]) and its thread root (res["_root"]). R39 (board
places keyed by their full path) is carried by the pack's board pattern, which captures the whole path.

The method is different on purpose. messages.py judges a mention by regular expressions over a window of
characters around it (the nearest verb wins). This file splits the record into tokens (strings, names,
punctuation), finds the call whose parentheses hold the mention, and reads that call's callee and
arguments. Deliveries are then linked by a sweep over each place's operations in (time, input position) order.

Redaction deletes text, quote marks included, so quote pairing from the start of a record cannot be trusted.
The first version of this file trusted it and, on the Swarm Traces release, took POSTs for reads and a later
POST for the write of a place that was only read (191 deliveries against 9). Since then the tokens are only used
where they line up with the quote before the mention; where they do not, the code is read again from a point
near the mention (the name being assigned, else the request call that starts before it, R8) or straight from
the text (R8 and R16 by `;`, line break, next request call and 600 characters).

Known differences of method (each can produce a disagreement, listed by tools/crosscheck.py):
  - a call is bounded by its real parentheses, the next request call and 600 characters, not by a character cap;
  - a Python f-string or raw-string assignment (u=f'...') is followed like any other assignment;
  - an open call with no verb at the end of a record is not counted, however far the end is (R13 says 40);
  - for a mention nothing else settles (R14) only a verb in the same statement counts (no `;` or line break
    between), where messages.py takes the nearest verb in a window of characters;
  - an upload batch is a probe (R6b) unless a later record names the object as an `lfsFile` or sends it with a PUT
    (messages.py also accepts upload_file and uploadId);
  - a place named inside the body or data argument of a call is data, not the call's address;
  - the arguments of a tool call (R18a) are walked as JSON, character by character, where messages.py matches a
    pattern; the terms of R38b are cut out of the text by splitting it, where messages.py matches a pattern, and
    every record that holds a term is kept in a list, where messages.py keeps the two earliest holders.
"""
import json
import re
from collections import Counter, defaultdict

from .reconstruct import is_action

WRITE_VERBS = {"POST", "PUT", "PATCH", "DELETE", "MKCOL"}
READ_VERBS = {"GET", "HEAD"}
WRITE_METHODS = {"post", "put", "patch", "delete", "sendbeacon", "upload_file", "create_commit"}
READ_METHODS = {"get", "head"}
REQUEST_NAMES = {"fetch", "urlopen", "request", "ajax", "curl", "xmlhttprequest"} | WRITE_METHODS | READ_METHODS
PASS_THROUGH = 3            # how many non-request wrappers to climb through: fetch(Q(enc(u)), ...)
OPENERS, CLOSERS = "([{", ")]}"

_LEX = re.compile(r"\\*['\"`]|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*|\d+|\\n|\n|[^\s\w]")


# ------------------------------------------------------------------ tokens

class Tok:
    __slots__ = ("kind", "val", "lo", "hi", "q", "closed")

    def __init__(self, kind, val, lo, hi, q="", closed=True):
        self.kind, self.val, self.lo, self.hi, self.q, self.closed = kind, val, lo, hi, q, closed


def _close_of(text, start, quote, limit=4000):
    """Index of the closing `quote` (the same character behind the same number of backslashes) after start."""
    ch, n = quote[-1], len(quote) - 1
    stop = min(len(text), start + limit)
    i = start
    while True:
        i = text.find(ch, i, stop)
        if i < 0:
            return -1
        b = 0
        while i - b - 1 >= start and text[i - b - 1] == "\\":
            b += 1
        if b == n:
            return i - n
        i += 1


def tokens(text, level=0):
    """The record as tokens: s (a string, val = its inside), i (a name, dots kept), n (a line break), p (one
    punctuation character). `level` is how many backslashes stand before the quotes of the code being read:
    code wrapped in a JSON string has level 1, and the wrapper's own quotes are then plain punctuation."""
    out, pos, n = [], 0, len(text)
    while pos < n:
        m = _LEX.search(text, pos)
        if not m:
            break
        t, lo = m.group(0), m.start()
        if t[-1] in "'\"`":
            if len(t) - 1 < level:
                out.append(Tok("p", t[-1], m.end() - 1, m.end()))
                pos = m.end()
                continue
            close = _close_of(text, m.end(), t)
            if t[-1] != "`" and len(t) == 1:
                nl = text.find("\n", m.end())
                if nl >= 0 and (close < 0 or nl < close):
                    close = -1                      # a plain quote does not run past its line
                    end = nl
                else:
                    end = close if close >= 0 else min(n, m.end() + 4000)
            else:
                end = close if close >= 0 else min(n, m.end() + 4000)
            if close >= 0:
                out.append(Tok("s", text[m.end():close], lo, close + len(t), t, True))
                pos = close + len(t)
            else:
                out.append(Tok("s", text[m.end():end], lo, end, t, False))
                pos = max(end, m.end())
        elif t == "\n" or t == "\\n":
            out.append(Tok("n", "\n", lo, m.end()))
            pos = m.end()
        elif t[0].isalpha() or t[0] in "_$":
            out.append(Tok("i", t, lo, m.end()))
            pos = m.end()
        elif t[0] == "\\":
            pos = m.start() + 1                   # a stray backslash
        else:
            out.append(Tok("p", t, lo, m.end()))
            pos = m.end()
    return out


def _is(t, kind, val=None):
    return t is not None and t.kind == kind and (val is None or t.val == val)


def _match_close(toks, j):
    """Index of the token closing the bracket opened at j, and whether it was found."""
    depth = 0
    for x in range(j, len(toks)):
        t = toks[x]
        if t.kind == "p":
            if t.val in OPENERS:
                depth += 1
            elif t.val in CLOSERS:
                depth -= 1
                if depth == 0:
                    return x, True
    return len(toks) - 1, False


def _is_block(toks, j):
    """Is the '{' at j a code block (function body, loop body) and not an object literal?"""
    x = j + 1
    while x < len(toks) and toks[x].kind == "n":
        x += 1                            # a key may sit on the next line
    if x + 1 < len(toks) and toks[x].kind in ("s", "i") and _is(toks[x + 1], "p", ":"):
        return False                      # { key: ... } is an object literal
    if j == 0:
        return True
    p = toks[j - 1]
    if p.kind == "n" or _is(p, "p", ")") or _is(p, "p", ";") or _is(p, "p", ">"):
        return True
    return p.kind == "i" and p.val in ("else", "try", "finally", "do")


def _around(toks, k, reach=400):
    """(call, obj): index of the '(' of the innermost call whose parentheses hold token k, and of the innermost
    object literal '{' that holds it (each None when there is none)."""
    depth, obj = 0, None
    for j in range(k - 1, max(-1, k - reach), -1):
        t = toks[j]
        if t.kind != "p":
            continue
        if t.val in CLOSERS:
            depth += 1
        elif t.val in OPENERS:
            if depth:
                depth -= 1
            elif t.val == "(":
                return j, obj
            elif t.val == "{":
                if _is_block(toks, j):
                    return None, obj
                if obj is None:
                    obj = j
        elif t.val == ";" and depth == 0:
            return None, obj
    return None, obj


def _callee(toks, j):
    """The name called at the '(' in toks[j] ('' when it is a bare parenthesis)."""
    if j and toks[j - 1].kind == "i" and toks[j - 1].val not in ("if", "for", "while", "return", "in", "and", "or", "not", "await"):
        return toks[j - 1].val
    return ""


def _own(toks, j, end):
    """Tokens between the '(' at j and its ')' at end that belong to this call: nested calls are left out
    (their arguments are their own), nested object and array literals are kept."""
    out, x = [], j + 1
    while x < end:
        t = toks[x]
        if _is(t, "p", "(") and x > j + 1 and toks[x - 1].kind == "i" and _callee(toks, x):
            x, _ok = _match_close(toks, x)
            x += 1
            continue
        out.append((x, t))
        x += 1
    return out


def _nearest(cands, k):
    """Of [(token index, verdict)] the verdict nearest to token k; a write wins a tie (R14)."""
    best = None
    for x, v in cands:
        d = (abs(x - k), 0 if v == "write" else 1)
        if best is None or d < best[0]:
            best = (d, v)
    return best[1] if best else None


class Judge:
    """Judges the mentions of one record for one channel (R6 to R17)."""

    def __init__(self, text, wrx, rrx, depth=0, mentions=(), anchor=None):
        self.text, self.wrx, self.rrx, self.depth = text, wrx, rrx, depth
        self.anchor = anchor                      # tokens start at this offset (chosen near the mention), not at the record start
        self.local = anchor is not None
        self.opening = None
        self.ctx, self.pos = None, None           # trace-level facts for R6b (set by operations())
        self.mentions = mentions                  # (start, end) of every place mention in the record, for R14
        self._toks = {}

    def toks(self, level):
        if level not in self._toks:
            a = self.anchor or 0
            ts = tokens(self.text[a:], level) if a else tokens(self.text, level)
            for t in ts:
                t.lo += a
                t.hi += a
            self._toks[level] = ts
        return self._toks[level]

    # -- one call ------------------------------------------------------------
    def call(self, toks, j, k):
        """(verdict, how, lo, hi) for the call opened at toks[j], asked about token k inside it.
        verdict: write, read, None (this call says nothing: not a request, no verb) or 'cut'."""
        end, closed = _match_close(toks, j)
        stop = self.call_limit(toks[j].hi)                 # R16: a call ends at the next request call or after 600 characters
        if toks[end].hi > stop:
            while end > j and toks[end].lo >= stop:
                end -= 1
            closed = True
        name = _callee(toks, j)
        last = name.rsplit(".", 1)[-1].lower()
        lo = toks[j - 1].lo if name else toks[j].lo
        hi = toks[end].hi
        own = _own(toks, j, end if closed else end + 1)
        for n, (x, t) in enumerate(own):                   # a `;` ends the statement: what follows is not this call's argument
            if _is(t, "p", ";"):
                own = own[:n]
                break
        cands = []
        for x, t in own:
            if t.kind == "s" and t.val in WRITE_VERBS:
                cands.append((x, "write"))
            elif t.kind == "s" and t.val in READ_VERBS:
                cands.append((x, "read"))
            elif t.kind == "i" and t.val in ("data", "body", "json") and x + 1 < len(toks) and _is(toks[x + 1], "p", "=") \
                    and not _is(toks[x + 2] if x + 2 < len(toks) else None, "p", "="):
                cands.append((x, "write"))
        body_hi = hi
        if last == "open" and closed:                      # x.open('POST', url); ...; x.send(body): one request
            obj = name.rsplit(".", 1)[0]
            for x in range(end + 1, min(len(toks) - 1, end + 80)):
                if toks[x].kind == "i" and toks[x].val == obj + ".send" and _is(toks[x + 1], "p", "("):
                    body_hi = toks[_match_close(toks, x + 1)[0]].hi
                    break
                if toks[x].kind == "i" and toks[x].val.endswith(".open"):
                    break
        op, oids = None, ()
        for m in re.finditer(r"operation[\\'\"]*\s*:\s*[\\'\"]*(upload|download)", self.text[lo:body_hi]):
            op, oids = m.group(1), tuple(self._OID.findall(self.text[max(0, lo + m.start() - 300):lo + m.start() + 800]))
        if op:                                             # R6: the request carries a Git LFS operation
            if re.search(r"info/lfs|git-lfs|objects/batch", self.text[lo:body_hi], re.I):
                v = self.lfs_batch(op, oids)                # R6b: only a Git LFS batch is a probe when it names no object that goes up
            else:
                v = "write" if op == "upload" else "read"   # an `operation` field in an ordinary request body
            return (v if v else "cut"), "inferred", lo, hi
        if last in WRITE_METHODS:
            return "write", "call", lo, hi
        v = _nearest(cands, k)
        if v is None:
            # the channel's own vocabulary (a commit path, a content type, a download path), inside this call only
            span = self.text[lo:hi]
            at = toks[k].lo - lo
            reg = [(abs(m.start() - at), "write") for m in self.wrx.finditer(span)] + [(abs(m.start() - at), "read") for m in self.rrx.finditer(span)]
            if reg:
                v = min(reg, key=lambda r: (r[0], r[1] != "write"))[1]
        if v is None:
            v = self.options(toks, j, own)
        if v is None and last in READ_METHODS:
            v = "read"
        if v is not None:
            return v, "call", lo, hi
        is_request = last in REQUEST_NAMES or (last == "open" and bool(cands))
        if not is_request:
            return None, None, lo, hi
        if not closed:
            return "cut", None, lo, hi
        return "read", "default", lo, hi

    def options(self, toks, j, own):
        """R15: the second argument is a bare name (fetch(u, o)): the object literal last assigned to it before the
        call is part of the call; if it is a parameter of a wrapper function, the wrapper's callers (the 500
        characters after it) carry the verb."""
        end, _ok = _match_close(toks, j)
        args, cur, depth = [], [], 0
        for x in range(j + 1, end):
            t = toks[x]
            if t.kind == "p" and t.val in OPENERS:
                depth += 1
            elif t.kind == "p" and t.val in CLOSERS:
                depth -= 1
            if t.kind == "p" and t.val == "," and depth == 0:
                args.append(cur)
                cur = []
            else:
                cur.append(t)
        args.append(cur)
        if len(args) < 2 or len(args[1]) != 1 or args[1][0].kind != "i" or "." in args[1][0].val:
            return None
        name = args[1][0].val
        for x in range(j - 1, -1, -1):
            if _is(toks[x], "i", name) and x + 2 < len(toks) and _is(toks[x + 1], "p", "=") and _is(toks[x + 2], "p", "{"):
                stop, _ok = _match_close(toks, x + 2)
                if any(t.kind == "s" and t.val in WRITE_VERBS for t in toks[x + 2:stop + 1]):
                    return "write"
                return "write" if self.wrx.search(self.text[toks[x + 2].lo:toks[stop].hi]) else None
        return self.wrapper_callers(toks, j, name)

    def wrapper_callers(self, toks, j, name):
        """R15, second half: `name` is a parameter of the function that holds the call at toks[j]; do that function's
        callers, in the 500 characters after it, carry a write verb?"""
        here = toks[j].lo
        for x in range(j - 1, max(-1, j - 400), -1):
            if not (_is(toks[x], "i", "function") or (_is(toks[x], "p", ">") and _is(toks[x - 1], "p", "=") and x >= 2 and _is(toks[x - 2], "p", ")"))):
                continue
            if toks[x].kind == "i":
                y = x + 1
                fname = toks[y].val if toks[y].kind == "i" else None
                y += 1 if fname else 0
                if not _is(toks[y], "p", "("):
                    continue
                popen = y
            else:                                           # name = (a, b) => { ... }
                popen = None
                depth = 0
                for y in range(x - 2, max(-1, x - 40), -1):
                    if _is(toks[y], "p", ")"):
                        depth += 1
                    elif _is(toks[y], "p", "("):
                        depth -= 1
                        if depth == 0:
                            popen = y
                            break
                if popen is None:
                    continue
                fname = toks[popen - 2].val if popen >= 2 and _is(toks[popen - 1], "p", "=") and toks[popen - 2].kind == "i" else None
            pclose, _ok = _match_close(toks, popen)
            if not any(_is(t, "i", name) for t in toks[popen + 1:pclose]):
                continue
            body = pclose + 1 + (2 if toks[x].kind == "p" else 0)
            if body >= len(toks) or not _is(toks[body], "p", "{") or not fname:
                continue
            bend, _ok = _match_close(toks, body)
            if toks[bend].hi < here:
                continue
            for z in range(bend + 1, len(toks)):
                if toks[z].lo - toks[bend].hi > 500:
                    break
                if _is(toks[z], "i", fname) and z + 1 < len(toks) and _is(toks[z + 1], "p", "("):
                    close, _ok = _match_close(toks, z + 1)
                    if any(t.kind == "s" and t.val in WRITE_VERBS for t in toks[z + 2:close]):
                        return "write"
            return None
        return None

    def climb(self, toks, k, pos=None):
        """The verdict of the call around token k, climbing through wrappers that say nothing."""
        at = k
        first = None
        for _ in range(PASS_THROUGH):
            j, _obj = _around(toks, at)
            if j is None:
                break
            v, how, lo, hi = self.call(toks, j, k)
            if first is None:
                first = (lo, hi)
            if v is not None:
                if not self.holds(toks[j].hi, toks[k].lo if pos is None else pos):
                    return None, None, toks[k].lo, toks[k].hi, False     # R8, R16: too far, or another call starts first
                return v, how, lo, hi, True
            at = j
        return None, None, (first or (toks[k].lo, toks[k].hi))[0], (first or (toks[k].lo, toks[k].hi))[1], first is not None

    def call_limit(self, after):
        """R16: where the call whose '(' ends at `after` stops: the start of the next request call, else 600 characters on."""
        stop = after + 600
        nxt = self._REQUEST_START.search(self.text, after, stop)
        return nxt.start() if nxt else stop

    def resync(self, start, end, opened):
        """The quote before the mention opens its string, but the quote pairing from the start of the record says
        otherwise (redaction removed a quote somewhere before). Read the code from a nearby point that does not
        depend on that pairing: the name being assigned (`u='...`), else the request call that holds the mention,
        else the opening quote itself. None when the string still does not line up."""
        text = self.text
        m = self._NAME_BEFORE.search(text[max(0, opened - 60):opened + 1])
        anchor = None
        if m:
            anchor = max(0, opened - 60) + m.start(1)
        else:
            head = text[max(0, opened - 600):opened]
            last = None
            for r in self._REQUEST_START.finditer(head):
                last = r
            if last and not (";" in head[last.end():] or "\n" in head[last.end():] or "\\n" in head[last.end():]):
                anchor = opened - len(head) + last.start()
        if anchor is None:
            anchor = opened
        sub = Judge(text, self.wrx, self.rrx, self.depth + 1, self.mentions, anchor=anchor)
        sub.ctx, sub.pos = self.ctx, self.pos
        level, k, wrapper = sub.literal(start, end)
        if k is None:
            return None
        return sub.judge(start, end)

    _DATA_ARG = re.compile(r"(?:body|data|json)['\"]?\s*[:=]\s*[\w.$()]*\s*['\"`][^'\"`\n]{0,70}$")

    def uploaded(self, start, end):
        """A place named inside the data a call sends (its body) is not the call's address. It is judged as plain text:
        a curl line there, else a read by default (the rule does not see into uploaded data)."""
        cmd = self.command(start, end)
        if cmd:
            return cmd
        lo, hi = self.line(start, end)
        return "read", "default", lo, hi

    _NAME_BEFORE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*=(?!=)\s*(?:[\w$.]+\s*\+\s*)?[frbu]{0,2}['\"`]$")

    def assigned_text(self, start):
        """The name a mention is assigned to (name = '...place'), read from the raw text where the quote pairing
        cannot be trusted. The opening quote is the first quote before the mention, across any marker."""
        i = start
        floor = max(0, start - 300)
        while i > floor:
            c = self.text[i - 1]
            if c == "]":
                o = self.text.rfind("[", max(floor, i - 90), i - 1)
                if o >= 0:
                    i = o
                    continue
            if c in "'\"`":
                m = self._NAME_BEFORE.search(self.text[max(0, i - 60):i])
                return m.group(1) if m else None
            if c.isspace():
                return None
            i -= 1
        return None

    def follow_text(self, name, start, end):
        """R9 on the raw text: every later use of the name (a whole word, not a key, not an assignment) up to the
        point where it is given another value; the call around each use judges it (R8, R16)."""
        text = self.text
        use = re.compile(r"(?<![\w$.])" + re.escape(name) + r"(?![\w$])")
        passed, span = False, None
        stop = min(len(text), end + 4000)
        for m in use.finditer(text, end, stop):
            after = text[m.end():m.end() + 3].lstrip()
            before = text[max(0, m.start() - 2):m.start()].strip()
            if after[:1] == "=" and after[1:2] != "=":
                break                                                               # given another value
            if after[:1] == ":" and before[-1:] in ("{", ","):
                continue                                                            # an object key
            call = self.textual_call(m.start(), m.end())
            if call and call[0] != "cut":
                if call[0] == "write":
                    return "write", "inferred", call[2], call[3]
                passed, span = True, span or (call[2], call[3])
        if passed:
            return "read", "inferred", span[0], span[1]
        return None, None, start, end

    _VERBS = ("POST", "PUT", "PATCH", "DELETE", "GET", "HEAD")
    _CUT_IN_VERB = re.compile(r"(?:method\s*[:=]\s*|\.open\s*\(\s*)['\"]([A-Za-z]{1,6})$")

    def cut_in_verb(self, end):
        """R13: the record ends inside the verb of the call that names the place (`...place',{method:'POS`)."""
        m = self._CUT_IN_VERB.search(self.text, end, min(len(self.text), end + 80))
        return bool(m and m.end() == len(self.text) and any(v.startswith(m.group(1).upper()) and v != m.group(1).upper() for v in self._VERBS)
                    and ";" not in self.text[end:m.start()] and "\n" not in self.text[end:m.start()])

    def window(self, start, end):
        """R14: for a mention nothing else settles, the nearest write or read verb within 160 characters before it
        and 260 after it decides (a tie goes to the write); the window stops at the neighbouring place mentions and
        at the start of the next request call. With no verb the mention is a read by default."""
        text = self.text
        lo, hi = max(0, start - 160), min(len(text), end + 260)
        for a, b in self.mentions:
            if b <= start:
                lo = max(lo, b)
            elif a >= end:
                hi = min(hi, a)
        nxt = self._REQUEST_START.search(text, end, hi)
        if nxt:
            hi = nxt.start()
        found = []
        for rx, side in ((self._VERB_LITERAL, None), (self.wrx, 0), (self.rrx, 1)):
            for m in rx.finditer(text, lo, hi):
                kind = side if side is not None else (0 if m.group(1) in WRITE_VERBS else 1)
                between = text[m.end():start] if m.end() <= start else text[end:m.start()]
                if ";" in between or "\n" in between or "\\n" in between:
                    continue                                    # another statement (R8's own boundary): not this mention's verb
                found.append((len(between), kind))
        if found:
            return ("write" if min(found)[1] == 0 else "read"), "call", lo, hi
        return "read", "default", lo, hi

    def holds(self, call_from, pos):
        """R8 and R16, read from the raw text: can the call whose parenthesis ends at call_from still hold text at
        pos? Not when a `;` or a line break lies between, when another request call starts in between, or when
        pos is more than 600 characters on. Quote pairing is not used, because redaction breaks it."""
        if pos - call_from > 600:
            return False
        seg = self.text[call_from:pos]
        return not (";" in seg or "\n" in seg or "\\n" in seg or self._REQUEST_START.search(seg))

    # -- a mention -----------------------------------------------------------
    def literal(self, start, end):
        """(level, token index, wrapper) for the string that holds the mention. wrapper is a larger string token
        whose inside is the code that holds the mention (a JSON-wrapped program), to be judged on its own.
        (None, None, None) when the mention is not in a string."""
        text = self.text
        i = start
        floor = max(0, start - 400)
        while i > floor:
            c = text[i - 1]
            if c == "]":                                   # a redaction marker ([SERVICE HOST 1]) may hold spaces
                o = text.rfind("[", max(floor, i - 90), i - 1)
                if o >= 0:
                    i = o
                    continue
            if c in "'\"`":
                b = 0
                while i - 2 - b >= 0 and text[i - 2 - b] == "\\":
                    b += 1
                opened = i - 1 - b
                self.opening = (opened, b)
                toks = self.toks(b)
                for x, t in enumerate(toks):
                    if t.kind == "s" and t.lo <= start and end <= t.hi:
                        if t.lo == opened:
                            return b, x, None
                        return None, None, t
                return None, None, None
            if c.isspace():
                break
            i -= 1
        for t in self.toks(0):                             # not quoted here, but inside a string that wraps code
            if t.kind == "s" and t.lo < start and end < t.hi and (t.hi - t.lo) > (end - start) + 40:
                return None, None, t
            if t.lo > start:
                break
        return None, None, None

    _OID = re.compile(r"\boid[\\'\"]*\s*[:=]\s*[\\'\"]*(\[[^\]]+\]|[0-9A-Za-z]{8,})")

    def lfs(self, toks, k, j):
        """R6: the operation of an LFS batch and the object ids it names, read from the call and the code just
        before it (the body is often built into a variable first, and often sits inside a string)."""
        lo = toks[max(0, (j if j is not None else k) - 120)].lo
        if j is not None:
            hi = toks[_match_close(toks, j)[0]].hi
        else:                                              # a name: up to the end of the next request call
            hi = toks[min(len(toks) - 1, k + 200)].hi
            nxt = self._REQUEST_START.search(self.text, toks[k].hi, toks[k].hi + 1500)
            if nxt:
                depth, x = 0, self.text.find("(", nxt.start(), nxt.start() + 60)
                stop = min(len(self.text), nxt.start() + 600)
                while 0 <= x < stop:
                    depth += (self.text[x] == "(") - (self.text[x] == ")")
                    if depth == 0:
                        break
                    x += 1
                hi = max(hi, min(x + 1, stop))
        best = None
        for m in re.finditer(r"operation[\\'\"]*\s*:\s*[\\'\"]*(upload|download)", self.text[lo:hi]):
            best = m
        if best is None:
            return None, ()
        at = lo + best.start()
        return best.group(1), tuple(self._OID.findall(self.text[max(0, at - 300):at + 800]))

    def lfs_batch(self, op, oids):
        """R6, R6b: write, read or None for a batch that carries `op`. An upload batch is a write only if one of its
        objects was not requested for download earlier in the trace and a later record sends it."""
        if op == "download":
            return "read"
        if self.ctx is None:
            return "write"
        return "write" if self.ctx.goes_up(oids, self.pos) else None

    def judge(self, start, end):
        """(op, how, lo, hi): op is write, read or None (not counted); how is call, inferred or default."""
        text = self.text
        if self.cut_in_verb(end):                                                    # R13
            return None, None, start, end
        if re.match(r"/paths-info\b", text[end:end + 12]):                           # R6a: a POST that only asks about files
            return "read", "inferred", start, min(len(text), end + 12)
        self.opening = None
        level, k, wrapper = self.literal(start, end)
        if k is None and self.opening and self.opening[1] == 0 and not self.local:
            r = self.resync(start, end, self.opening[0])
            if r:
                return r
        if wrapper is not None and self.depth < 4:
            lo = wrapper.lo + len(wrapper.q)
            hi = wrapper.hi - (len(wrapper.q) if wrapper.closed else 0)
            inner = Judge(text[lo:hi], self.wrx, self.rrx, self.depth + 1)
            inner.ctx, inner.pos = self.ctx, self.pos
            op, how, a, b = inner.judge(start - lo, end - lo)
            return op, how, a + lo, b + lo
        if k is None:
            return self.unquoted(start, end)
        toks = self.toks(level)
        lit = toks[k]
        if k >= 2 and toks[k - 1].kind == "p" and toks[k - 1].val in ":=" and toks[k - 2].kind in ("i", "s") \
                and toks[k - 2].val in ("body", "data", "json"):
            return self.uploaded(start, end)                                         # a place named in data that is sent
        j, obj = _around(toks, k)
        if "info/lfs" in text[end:end + 40]:                                        # R6
            op, oids = self.lfs(toks, k, j)
            v = self.lfs_batch(op, oids) if op else None
            if v is None:
                return None, None, start, end
            return v, "inferred", start, end
        after = text[end:lit.hi - len(lit.q)] if lit.closed else text[end:lit.hi]
        if after == "/" and k + 3 < len(toks) and _is(toks[k + 1], "p", "+") and toks[k + 2].kind == "i":   # R7
            x = k + 3
            if _is(toks[x], "p", "["):
                x = _match_close(toks, x)[0] + 1
            if x + 1 < len(toks) and _is(toks[x], "p", "+") and toks[x + 1].kind == "s" and toks[x + 1].val.startswith("/"):
                return None, None, start, end
        if obj is not None:                                                          # R12
            v = self.descriptor(toks, k, obj)
            if v:
                return v, "inferred", start, end
        name = self.assigned(toks, k, j)
        if name:                                                                     # R9
            r = self.follow(toks, k, name, level, start, end)
            if r[0] is None:                       # nothing seen: the quote pairing after the mention may be wrong
                r2 = self.follow_text(name, start, end)
                if r2[0] is not None:
                    return r2
            return r
        if j is not None:
            v, how, lo, hi, inside = self.climb(toks, k, start)
            if v == "cut":
                return None, None, start, end                                        # R13
            if v is not None:
                return v, how, lo, hi                                                # R8, R10, R11
            if inside:
                return "read", "default", lo, hi                                     # R14: a helper with no verb
            call = self.textual_call(start, end)
            if call:
                return (None, None, start, end) if call[0] == "cut" else call
        cmd = self.command(start, end)
        if cmd:
            return cmd
        if self.closes_statement(toks, k) and not self.config_entry(start) and self.later_write_through_name(end):    # R17
            return None, None, start, end
        return self.window(start, end)                                               # R14

    def descriptor(self, toks, k, obj):
        key = None
        x = k - 1
        while x > obj and (toks[x].kind in ("s", "i") or _is(toks[x], "p", "+")) and not _is(toks[x], "p", ":"):
            x -= 1
        if _is(toks[x], "p", ":") and x - 1 > obj:
            key = toks[x - 1].val
        if key not in ("u", "url"):
            return None
        end, _ok = _match_close(toks, obj)
        body = False
        for x in range(obj + 1, end):
            t = toks[x]
            if t.kind in ("s", "i") and x + 2 <= end and _is(toks[x + 1], "p", ":"):
                if t.val in ("m", "method") and toks[x + 2].kind == "s":
                    if toks[x + 2].val in WRITE_VERBS:
                        return "write"
                    if toks[x + 2].val in READ_VERBS:
                        return "read"
                if t.val in ("b", "body", "data"):
                    body = True
        return "write" if body else None

    def assigned(self, toks, k, call=None):
        """The name the literal at k is assigned to (name = '...', name = base + '...', name = f'...'). A keyword
        argument of the call that holds it (requests.post(url='...')) is not an assignment."""
        x = k - 1
        if x >= 0 and toks[x].kind == "i" and toks[x].hi == toks[k].lo and toks[x].val.lower() in ("f", "r", "b", "rb", "fr", "u"):
            x -= 1
        hops = 0
        while x >= 1 and _is(toks[x], "p", "+") and toks[x - 1].kind in ("i", "s") and hops < 3:
            x -= 2
            hops += 1
        if x >= 1 and _is(toks[x], "p", "=") and toks[x - 1].kind == "i" and not (x + 1 < len(toks) and _is(toks[x + 1], "p", "=")):
            if x >= 2 and _is(toks[x - 2], "p") and toks[x - 2].val in "=!<>":
                return None
            if call is not None and x >= 2 and _is(toks[x - 2], "p") and toks[x - 2].val in "(,":
                return None
            return toks[x - 1].val.rsplit(".", 1)[-1]
        return None

    def follow(self, toks, k, name, level, start, end):
        """R9: the calls the name is passed to, until it is given another value."""
        passed, read_span = False, None
        inter = re.compile(r"\$?\{" + re.escape(name) + r"\}|\$" + re.escape(name) + r"\b")
        stop = min(len(toks), k + 4000)
        for x in range(k + 1, stop):
            t = toks[x]
            if t.kind == "i" and (t.val == name or t.val == "$" + name):
                if x + 1 < len(toks) and _is(toks[x + 1], "p", "=") and not (x + 2 < len(toks) and _is(toks[x + 2], "p", "=")) \
                        and not (_is(toks[x - 1], "p") and toks[x - 1].val in "!<>=+"):
                    break                                               # given another value
                if x + 1 < len(toks) and _is(toks[x + 1], "p", "="):
                    continue
                if x + 1 < len(toks) and _is(toks[x + 1], "p", ":") and _is(toks[x - 1], "p") and toks[x - 1].val in "{,":
                    continue                                            # an object key that has the same spelling
                v, how, lo, hi, inside = self.climb(toks, x)
                if not inside:
                    cmd = self.command(t.lo, t.hi)
                    if cmd and cmd[0] == "write":
                        return "write", "inferred", cmd[2], cmd[3]
                    if cmd:
                        passed, read_span = True, read_span or (cmd[2], cmd[3])
                    continue
                if v == "write":
                    return "write", "inferred", lo, hi
                passed = True
                read_span = read_span or (lo, hi)
            elif t.kind == "s" and inter.search(t.val):
                v, how, lo, hi, inside = self.climb(toks, x)
                if v is None or v == "cut":
                    sub = self.inside_string(t, inter)
                    if sub:
                        v, lo, hi, inside = sub[0], sub[1], sub[2], True
                    elif not inside:
                        cmd = self.command(t.lo, t.hi)
                        if cmd:
                            v, lo, hi, inside = cmd[0], cmd[2], cmd[3], True
                if v == "write":
                    return "write", "inferred", lo, hi
                if inside:
                    passed = True
                    read_span = read_span or (lo, hi)
        if passed:
            return "read", "inferred", read_span[0], read_span[1]
        return None, None, start, end

    def inside_string(self, t, inter):
        """A string that is itself code (a script that writes a script): the call around the interpolated name."""
        inner_lo = t.lo + len(t.q)
        inner = Judge(self.text[inner_lo:t.hi - (len(t.q) if t.closed else 0)], self.wrx, self.rrx)
        inner.ctx, inner.pos = self.ctx, self.pos
        for level in (0, 1, 2):
            itoks = inner.toks(level)
            for x, it in enumerate(itoks):
                if it.kind == "s" and inter.search(it.val):
                    v, how, lo, hi, inside = inner.climb(itoks, x)
                    if v in ("write", "read"):
                        return v, inner_lo + lo, inner_lo + hi
        return None

    def closes_statement(self, toks, k):
        t = toks[k]
        if not t.closed:
            return False
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        return nxt is None or nxt.kind == "n" or _is(nxt, "p", ";")

    def config_entry(self, start):
        """R17's exception: the mention sits in the quoted value of a key that starts its line (key: "…place")."""
        line = self.text[self.text.rfind("\n", 0, start) + 1:start]
        key, colon, value = line.partition(":")
        key = key.strip()
        if key.startswith("- "):
            key = key[2:].strip()
        value = value.lstrip(" \t")
        return bool(colon and key and all(ch.isalnum() or ch in "_.-" for ch in key)
                    and value[:1] in ("'", '"') and value.count(value[:1]) == 1 and "'" not in value[1:] and '"' not in value[1:])

    def later_write_through_name(self, end, cap=8000):
        """R17: does a later request call whose address is not a literal URL write? Read from the raw text, because
        the call may sit inside a string (generated code)."""
        text = self.text[end:end + cap]
        for m in re.finditer(r"([A-Za-z_$][\w$.]*)\s*\(", text):
            last = m.group(1).rsplit(".", 1)[-1].lower()
            if last not in REQUEST_NAMES and last != "open":
                continue
            depth, x = 0, m.end() - 1
            stop = min(len(text), x + 600)
            while x < stop:
                if text[x] == "(":
                    depth += 1
                elif text[x] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                x += 1
            seg = text[m.start():x + 1]
            if re.search(r"['\"`](?:https?:)?//", seg):
                continue
            if last in WRITE_METHODS or re.search(r"['\"](?:POST|PUT|PATCH|DELETE|MKCOL)['\"]|\b(?:data|json)\s*=[^=]", seg) or self.wrx.search(seg):
                return True
        return False

    # -- not in a string, or a shell line ------------------------------------
    def line(self, start, end):
        lo = self.text.rfind("\n", 0, start) + 1
        esc = self.text.rfind("\\n", 0, start)
        if esc >= 0:
            lo = max(lo, esc + 2)
        hi = len(self.text)
        for stopper in ("\n", "\\n"):
            x = self.text.find(stopper, end)
            if x >= 0:
                hi = min(hi, x)
        return lo, hi

    def command(self, start, end):
        """A curl or wget command line that holds the mention: its flags say write or read."""
        lo, hi = self.line(start, end)
        line = self.text[lo:hi]
        at = start - lo
        cmds = [m.start() for m in re.finditer(r"(?<![\w.])(?:curl|wget)\b", line)]
        mine = [c for c in cmds if c < at]
        if not mine:
            return None
        c = mine[-1]
        nxt = [x for x in cmds if x > at]
        seg = line[c:(nxt[0] if nxt else len(line))]
        cut = re.search(r"\||;|&&|\)", seg[max(0, at - c):])
        if cut:
            seg = seg[:max(0, at - c) + cut.start()]
        m = re.search(r"(?:-X|--request)\s*['\"]?([A-Z]+)", seg)
        if m:
            if m.group(1) in WRITE_VERBS:
                return "write", "call", lo + c, lo + c + len(seg)
            if m.group(1) in READ_VERBS:
                return "read", "call", lo + c, lo + c + len(seg)
        if re.search(r"(?<!\w)(?:-T|--upload-file|-d|--data(?:-\w+)?|-F|--form|--post-data|--post-file)\b", seg):
            return "write", "call", lo + c, lo + c + len(seg)
        if self.wrx.search(seg):
            return "write", "call", lo + c, lo + c + len(seg)
        return "read", ("call" if self.rrx.search(seg) or re.search(r"(?<!\w)(?:-I|--head)\b", seg) else "default"), lo + c, lo + c + len(seg)

    _REQUEST_START = re.compile(
        r"(?<![\w$.])(?:fetch|urlopen)\s*\(|\bRequest\s*\(|\.open\s*\(|new\s+XMLHttpRequest|requests\.(?:get|post|put|patch|delete|head)\s*\(|"
        r"http\.request|axios\.|\$\.ajax|navigator\.sendBeacon")
    _VERB_LITERAL = re.compile(r"(?<=['\"])(POST|PUT|PATCH|DELETE|MKCOL|GET|HEAD)(?=['\"])")

    def textual_call(self, start, end):
        """R8 read straight from the text, for a mention the tokenizer could not place in a string (redaction
        removes quote characters, so quote pairing cannot be trusted). The mention is inside a request call when
        a request call starts before it with no `;` and no line break between (R8); the call ends at its closing
        parenthesis, at the start of the next request call, or after 600 characters (R16). (op, how, lo, hi), or
        None when no request call holds the mention. The op is "cut" when the call is open at the end of the
        record with no verb (R13)."""
        text = self.text
        head = text[max(0, start - 1500):start]
        last = None
        for m in self._REQUEST_START.finditer(head):
            last = m
        if last is None:
            return None
        between = head[last.end():]
        if ";" in between or "\n" in between or "\\n" in between:
            return None
        lo = start - len(head) + last.start()
        if text.find("(", lo, start) >= 0:                  # the call must still be open where the mention is
            depth = 0
            for ch in text[text.find("(", lo, start):start]:
                depth += (ch == "(") - (ch == ")")
                if depth <= 0:
                    return None
        if self._DATA_ARG.search(text[max(0, start - 80):start]):
            return None
        stop = min(len(text), lo + 600)
        nxt = self._REQUEST_START.search(text, end, stop)
        if nxt:
            stop = nxt.start()
        depth, hi, closed = 0, stop, False
        opened = text.find("(", lo, start)
        if opened >= 0:
            for x in range(opened, stop):
                if text[x] == "(":
                    depth += 1
                elif text[x] == ")":
                    depth -= 1
                    if depth == 0:
                        hi, closed = x + 1, True
                        break
        span = text[lo:hi]
        at = start - lo
        found = [(abs(m.start() - at), 0 if m.group(1) in WRITE_VERBS else 1) for m in self._VERB_LITERAL.finditer(span)]
        found += [(abs(m.start() - at), 0) for m in self.wrx.finditer(span)]
        found += [(abs(m.start() - at), 1) for m in self.rrx.finditer(span)]
        if found:
            return ("write" if min(found)[1] == 0 else "read"), "call", lo, hi
        if not closed and hi >= len(text) and nxt is None:
            return "cut", None, lo, hi
        m = re.match(r"[^,()]*,\s*([A-Za-z_$][\w$]*)\s*\)", text[opened + 1:hi]) if opened >= 0 else None   # fetch(u, o)
        if m:                                                                       # R15 on the raw text
            held = re.compile(r"(?<![\w$.])" + re.escape(m.group(1)) + r"\s*=\s*\{").search(text, max(0, lo - 1500), lo)
            if held:
                x = text.find("{", held.start())
                depth = 0
                for y in range(x, min(len(text), x + 800)):
                    depth += (text[y] == "{") - (text[y] == "}")
                    if depth == 0:
                        break
                body = text[x:y + 1]
                if self._VERB_LITERAL.search(body) and any(v in WRITE_VERBS for v in self._VERB_LITERAL.findall(body)) or self.wrx.search(body):
                    return "write", "call", lo, hi
        return "read", "default", lo, hi

    def unquoted(self, start, end):
        text = self.text
        cmd = self.command(start, end)
        if cmd:
            return cmd
        call = self.textual_call(start, end)
        if call:
            if call[0] == "cut":
                return None, None, start, end
            return call
        name = self.assigned_text(start)
        if name:                                                                    # R9 on the raw text
            return self.follow_text(name, start, end)
        tail = text[end:end + 90]
        closing = re.match(r"[^'\"`\s;,(){}]{0,80}\\*['\"`][ \t]*(?:;|\r?\n|$)", tail)
        if closing and not self.config_entry(start) and self.later_write_through_name(end):   # R17: the opening is hidden
            return None, None, start, end
        if re.match(r"\s*https?://\S*\s*$", re.sub(r"\[[^\[\]]*\]", "X", text)):         # R13: the record is a bare URL
            return None, None, start, end
        return self.window(start, end)


# ------------------------------------------------------------------ fragments (R13a)

_FULL_VERBS = ("POST", "PUT", "PATCH", "DELETE", "GET", "HEAD")
_QUOTES = "'\""


class Joined:
    """Several records read as one (R13a): the first one's id and fields, the texts one after the other."""
    __slots__ = ("id", "text", "kind", "parent", "actor", "channel", "to", "time", "pieces")

    def __init__(self, first, text, time, pieces):
        self.id, self.kind, self.parent, self.actor, self.channel = first.id, first.kind, first.parent, first.actor, first.channel
        self.to = getattr(first, "to", None)
        self.text, self.time, self.pieces = text, time, pieces


def _ends_in_verb(text):
    """R13a (a): (letters, quote) when the text ends with `method` and `:` or `=`, or `.open(`, then a quote and one to
    five letters that begin a verb without completing it. Read backwards from the end, character by character."""
    tail = text[-64:]
    k = len(tail)
    while k > 0 and tail[k - 1].isascii() and tail[k - 1].isalpha():
        k -= 1
    letters = tail[k:].upper()
    if not 1 <= len(letters) <= 5 or k == 0 or tail[k - 1] not in _QUOTES:
        return None
    if not any(v != letters and v.startswith(letters) for v in _FULL_VERBS):
        return None
    quote = tail[k - 1]
    before = tail[:k - 1].rstrip()
    if before.endswith("("):
        ok = before[:-1].rstrip().endswith(".open")
    elif before.endswith((":", "=")):
        word = before[:-1].rstrip()
        ok = word.endswith("method") and not (len(word) > 6 and (word[-7].isalnum() or word[-7] == "_"))
    else:
        ok = False
    return (letters, quote) if ok else None


def _begins_with_rest(text, letters, quote):
    """R13a (b): the text begins with the letters a verb still misses, then the same quote."""
    for v in _FULL_VERBS:
        if v != letters and v.startswith(letters):
            rest = v[len(letters):]
            if text[:len(rest)].upper() == rest and text[len(rest):len(rest) + 1] == quote:
                return True
    return False


def _may_follow(first, nxt, pack):
    """R13a (c)."""
    if not (is_action(first, pack) and is_action(nxt, pack)) or first.kind != nxt.kind:
        return False
    if getattr(first, "to", None) or getattr(nxt, "to", None):
        return False
    if (first.actor or "") != (nxt.actor or "") or (first.channel or "") != (nxt.channel or ""):
        return False
    return not nxt.parent or nxt.parent in (first.id, first.parent)


def join(events, pack, rec):
    """R13a: (records, rec for them, {first id: [ids joined into it]}). With nothing to join, the inputs themselves.
    A joined record takes its tokens from its pieces (the first piece's first) and the first time any piece has."""
    out, pieces_of = [], {}
    pos, n = 0, len(events)
    while pos < n:
        first = events[pos]
        text, nxt = None, pos + 1
        while nxt < n:
            cut = _ends_in_verb(first.text if text is None else text)
            if cut is None or not _may_follow(first, events[nxt], pack) or not _begins_with_rest(events[nxt].text, *cut):
                break
            text = (first.text if text is None else text) + events[nxt].text
            nxt += 1
        if text is None:
            out.append(first)
        else:
            rest = events[pos + 1:nxt]
            own_time = first.time or next((x.time for x in rest if x.time), None)
            out.append(Joined(first, text, own_time, [first.id] + [x.id for x in rest]))
            pieces_of[first.id] = [x.id for x in rest]
        pos = nxt
    if not pieces_of:
        return events, rec, {}
    ids, times = dict(rec["_ids"]), dict(rec["_times"])
    for first, rest in pieces_of.items():
        toks = []
        for rid in [first] + rest:
            for t in rec["_ids"].get(rid, ()):
                if t not in toks:
                    toks.append(t)
        ids[first] = toks
        for rid in [first] + rest:
            if rec["_times"].get(rid) is not None:
                times[first] = rec["_times"][rid]
                break
    return out, dict(rec, _ids=ids, _times=times), pieces_of


# ------------------------------------------------------------------ comments (R3)

def commented(text, pos):
    lo = text.rfind("\n", 0, pos) + 1
    before = text[lo:pos]
    head = before.lstrip()
    for mark in ("//", "#", "/*", "* ", "-- "):
        if head.startswith(mark):
            return True
    for m in re.finditer(r"//|#\s|/\*", before):
        if m.start() == 0 or before[m.start() - 1].isspace():
            if m.group(0) == "/*" and "*/" in before[m.end():]:
                continue
            return True
    return False


# ------------------------------------------------------------------ actors (R21)

def _own_tokens(e, ids, shared):
    return [t for t in ids.get(e.id, ()) if t not in shared]


def actors(events, pack, rec, res, voters=None):
    """record id -> (actor, kind, the record's non-shared tokens). voters: (records, their tokens) whose tokens count
    in each thread for step 4 of R21; with joined records (R13a) these are the original records."""
    shared = set(pack.raw.get("shared_identities", []))
    ids, root = rec["_ids"], res["_root"]
    per_thread = defaultdict(Counter)
    vote_events, vote_ids = voters if voters else (events, ids)
    for e in vote_events:
        for t in _own_tokens(e, vote_ids, shared):
            per_thread[root[e.id]][t] += 1
    thread_tok = {r: c.most_common(1)[0][0] for r, c in per_thread.items()}
    out = {}
    for e in events:
        own = _own_tokens(e, ids, shared)
        if e.actor and e.actor in own:
            out[e.id] = (e.actor, "named", own)
        elif own:
            out[e.id] = (own[0], "token", own)
        else:
            who = None
            if pack.handles_rx:
                m = pack.handles_rx.search(e.text)
                if m:
                    best = ""
                    for prefix in pack.handle_families:
                        if m.group(1).startswith(prefix) and len(prefix) > len(best):
                            best = prefix
                    who = (pack.handle_families[best] if best else m.group(1), "handle", own)
            if who is None and thread_tok.get(root[e.id]):
                who = (thread_tok[root[e.id]], "token_via_thread", own)
            out[e.id] = who or ("run:" + root[e.id], "run", own)
    return out


# ------------------------------------------------------------------ Git LFS objects (R6b)

_BATCH_OP = re.compile(r"operation[\\'\"]*\s*:\s*[\\'\"]*(upload|download)")
_SENDS = re.compile(r"lfsFile|['\"]PUT['\"]|requests\.put\s*\(|-X\s*PUT\b|--upload-file")


class LfsFacts:
    """What R6b needs from the whole trace: for each object id named in an upload batch, where it was first asked for
    with a download batch, and which records send it (name it as an `lfsFile`, or carry a PUT). Positions are input
    order."""

    def __init__(self, events):
        down, up = {}, set()
        for pos, e in enumerate(events):
            t = e.text
            if "operation" not in t:
                continue
            for m in _BATCH_OP.finditer(t):
                oids = Judge._OID.findall(t[max(0, m.start() - 300):m.start() + 800])
                if m.group(1) == "download":
                    for o in oids:
                        down.setdefault(o, pos)
                else:
                    up.update(oids)
        self.down = down
        self.sent = defaultdict(list)
        if up:
            for pos, e in enumerate(events):
                t = e.text
                if _SENDS.search(t):
                    for o in up:
                        if o in t:
                            self.sent[o].append(pos)

    def goes_up(self, oids, pos):
        """True when one of the objects was not requested for download before position `pos` and a later record
        sends it. No visible object id: not counted."""
        for o in oids:
            if self.down.get(o, pos + 1) < pos:
                continue
            if any(x > pos for x in self.sent.get(o, ())):
                return True
        return False


# ------------------------------------------------------------------ operations

class Op:
    __slots__ = ("place", "op", "actor", "time", "rid", "idx", "how", "kind")

    def __init__(self, place, op, actor, time, rid, idx, how=None, kind=None):
        self.place, self.op, self.actor, self.time, self.rid, self.idx, self.how, self.kind = place, op, actor, time, rid, idx, how, kind


def _channels(pack):
    out = []
    never = r"(?!)"
    for c in pack.raw.get("channels", []):
        out.append((c["name"], re.compile(c["pattern"], re.I if "i" in c.get("flags", "") else 0),
                    re.compile(c.get("write", pack.raw.get("write_pattern", never)), re.I),
                    re.compile(c.get("read", pack.raw.get("read_pattern", never)), re.I)))
    return out


def _short(key):
    return re.split(r"[~/:#]", key)[-1]


# ------------------------------------------------------------------ a tool call that names its place (R18a)

_ASCII_LOWER, _ASCII_UPPER = "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def tool_words(name):
    """R18a: the words of a tool's name, lower-cased: cut at every character that is not a letter and before a
    capital that follows a lower-case letter (read_file, readFile -> read, file)."""
    words, cur, prev = [], "", ""
    for ch in name:
        if ch in _ASCII_LOWER or ch in _ASCII_UPPER:
            if cur and ch in _ASCII_UPPER and prev in _ASCII_LOWER:
                words.append(cur.lower())
                cur = ""
            cur += ch
        elif cur:
            words.append(cur.lower())
            cur = ""
        prev = ch
    if cur:
        words.append(cur.lower())
    return words


def tool_verb(name, cfg):
    """R18a: write when a word of the tool's name is a write word, else read when one is a read word, else None."""
    words = set(tool_words(name))
    if words & {str(w).lower() for w in cfg.get("write_words", ())}:
        return "write"
    if words & {str(w).lower() for w in cfg.get("read_words", ())}:
        return "read"
    return None


def json_strings(text):
    """R18a, R38b: the strings of the first JSON object in the text that are not keys, as (key, raw, lo, hi): key is
    the key the string is the value of, or None for a string in a list; raw is the string as written; lo and hi
    bound it together with its key, from the quote that opens the key (the string itself, in a list) to the quote
    that closes the value. The object is walked without decoding it, so one that is cut is read as far as it goes."""
    out = []
    i, n = text.find("{"), len(text)
    if i < 0:
        return out
    stack, key, want_key = [], None, False
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                break                                   # cut inside a string
            if stack and stack[-1] == "{":
                if want_key:
                    key, want_key = (text[i + 1:j], i), False
                elif key is not None:
                    out.append((key[0], text[i + 1:j], key[1], j + 1))
                    key = None
            elif stack:
                out.append((None, text[i + 1:j], i, j + 1))
            i = j + 1
            continue
        if c == "{":
            stack.append(c)
            key, want_key = None, True
        elif c == "[":
            stack.append(c)
            key = None
        elif c == "}" or c == "]":
            if stack:
                stack.pop()
            if not stack:
                break                                   # the first object is closed
            key, want_key = None, False
        elif c == ",":
            key = None
            want_key = bool(stack) and stack[-1] == "{"
        i += 1
    return out


def _decoded(raw):
    if "\\" not in raw:
        return raw
    try:
        value = json.loads('"' + raw + '"')
    except ValueError:
        return raw
    return value if isinstance(value, str) else raw


def named_places(text, keys):
    """R18a: [(place name, lo, hi)] for the strings that are the value of one of the place keys (letter case
    ignored), 1 to 300 characters, without the spaces at their ends."""
    wanted = {str(k).lower() for k in keys}
    out = []
    for key, raw, lo, hi in json_strings(text):
        if key is None or key.lower() not in wanted or not 1 <= len(raw) <= 300:
            continue
        value = _decoded(raw).strip()
        if value:
            out.append((value, lo, hi))
    return out


def operations(events, pack, rec, res, who=None):
    """Every operation in the trace (R1 to R21a), direct messages left out."""
    who = who or actors(events, pack, rec, res)
    times = rec["_times"]
    chans = _channels(pack)
    structural = pack.raw.get("structural_channels", True)
    write_only = set(pack.raw.get("write_only_kinds", []))
    by_short = defaultdict(set)
    if pack.raw.get("mention_channels", False):
        for e in events:
            if e.channel and len(_short(e.channel)) >= 6:
                by_short[_short(e.channel)].add(e.channel)
    ops = []
    lfs_facts = LfsFacts(events)
    tool_cfg = pack.raw.get("tool_places")
    if not isinstance(tool_cfg, dict) or not tool_cfg.get("keys"):
        tool_cfg = None
    for idx, e in enumerate(events):
        if not is_action(e, pack):                                                   # R2
            continue
        actor, kind, own = who[e.id]
        found = {}                # place -> (op, how, judged text)
        if structural and e.channel:                                                 # R18
            found["place:" + e.channel] = ("write" if e.kind in write_only else "post", None, None)
        if by_short:                                                                 # R19
            prefix = e.channel.rsplit("~", 1)[0] + "~" if e.channel and "~" in e.channel else None
            for word in set(re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{5,}", e.text)):
                keys = by_short.get(word)
                if not keys:
                    continue
                near = [x for x in keys if prefix and x.startswith(prefix)]
                for key in near or keys:
                    if key != e.channel and "place:" + key not in found:
                        found["place:" + key] = ("read", None, None)
        spans = None
        for name, rx, wrx, rrx in chans:
            judge = None
            here = {}
            for m in rx.finditer(e.text):
                if not m.group(1) or commented(e.text, m.start()):                   # R1, R3
                    continue
                if spans is None:
                    spans = sorted((x.start(), x.end()) for _n, r2, _w, _r in chans for x in r2.finditer(e.text) if x.group(1))
                if judge is None:
                    judge = Judge(e.text, wrx, rrx, mentions=spans)
                    judge.ctx, judge.pos = lfs_facts, idx
                op, how, lo, hi = judge.judge(m.start(), m.end())                    # R4
                if op is None:
                    continue
                place = name + ":" + m.group(1)
                if place not in here or (op == "write" and here[place][0] != "write"):   # R5
                    here[place] = (op, how, e.text[lo:hi])
            for place, v in here.items():
                if found.get(place, ("",))[0] != "write":
                    found[place] = v
        if tool_cfg and getattr(e, "tool", None):                                    # R18a
            verb = tool_verb(e.tool, tool_cfg)
            if verb:
                taken = [(x.start(), x.end()) for _n, r2, _w, _r in chans for x in r2.finditer(e.text) if x.group(1)]
                for value, lo, hi in named_places(e.text, tool_cfg["keys"]):
                    if any(a < hi and lo < b for a, b in taken):
                        continue                                                     # a channel of the pack reads this argument
                    found.setdefault("tool:" + value, (verb, "call", None))
        for place, (op, how, seg) in found.items():
            a = actor
            if kind == "token" and len(own) > 1 and seg is not None:                 # R21a
                named = [t for t in own if t in seg]
                if len(named) == 1:
                    a = named[0]
            ops.append(Op(place, op, a, times.get(e.id), e.id, idx, how, kind))
    return ops


# ------------------------------------------------------------------ direct messages (R20)

def direct(events, pack, rec, res, who=None):
    who = who or actors(events, pack, rec, res)
    times = rec["_times"]
    kids, lane, where = defaultdict(list), defaultdict(list), {}
    for idx, e in enumerate(events):
        if e.parent:
            kids[e.parent].append(idx)
        where[e.id] = len(lane[e.channel or ""])
        lane[e.channel or ""].append(idx)
    out = []
    for idx, e in enumerate(events):
        if not getattr(e, "to", None):
            continue
        sender, to = who[e.id][0], str(e.to)
        if sender == to:
            continue
        t = times.get(e.id)

        def fits(j):
            tj = times.get(events[j].id)
            return j != idx and who[events[j].id][0] == to and (t is None or tj is None or tj >= t)
        reply = next((j for j in kids.get(e.id, []) if fits(j)), None)
        if reply is None:
            after = lane[e.channel or ""][where[e.id] + 1:where[e.id] + 60]
            reply = next((j for j in after if fits(j)), None)
        rid = events[reply].id if reply is not None else e.id
        rt = times.get(rid) if reply is not None else t
        out.append({"place": "inbox:" + to, "write_id": e.id, "read_id": rid, "from": sender, "to": to,
                    "write_time": t, "read_time": rt if rt is not None else t, "grade": "direct"})
    return out


# ------------------------------------------------------------------ same program (R27)

_MARKER = re.compile(r"\[[A-Za-z][A-Za-z _-]*(?::[^\]]*)?\]")
_WORD = re.compile(r"<[a-z_]+>|\w+|[^\w\s]")


def _program_key(text, n=60):
    """R27: the first n tokens of the record with redaction markers, long hex strings and numbers masked."""
    def marker(m):
        name = re.match(r"[A-Za-z]+", m.group(0)[1:]).group(0).lower()
        return " <" + name + "> "
    t = _MARKER.sub(marker, text).lower()
    words = []
    for w in _WORD.findall(t):
        if w.isdigit():
            w = "<n>"
        elif len(w) >= 8 and all(c in "0123456789abcdef" for c in w):
            w = "<h>"
        words.append(w)
        if len(words) > n and len(words) >= 20:
            break
    return tuple(words[:n]) if len(words) >= 20 else None


def _lines(text):
    """R29: the lines of 8 or more characters in a full-body post."""
    out = set()
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) >= 8:
            out.add(line)
    return out


# ------------------------------------------------------------------ linking (R22 to R34)

_WORD_RX = {}


def _holds_word(text, token):
    """R23a: does the record contain the token as a whole word?"""
    rx = _WORD_RX.get(token)
    if rx is None:
        rx = _WORD_RX[token] = re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)")
    return bool(rx.search(text))


def link(ops, texts=None, program=None, full_body=False, coarse=None, estimated=None):
    """Deliveries, overwrites and counters from operations. A sweep over each place in (time, input position) order."""
    program = program or {}
    by_place = defaultdict(list)
    for o in ops:
        by_place[o.place].append(o)
    deliveries, overwrites = [], []
    order_unknown = repeats = same_program = 0
    added_lines = {}                          # (place, record) -> the lines that post added, for R38b
    for place in sorted(by_place):
        lst = by_place[place]
        writes = [o for o in lst if o.op in ("write", "post")]
        reads = [o for o in lst if o.op in ("read", "post")]
        added = {}
        if full_body:
            seen = set()
            posts = sorted((o for o in lst if o.op == "post"), key=lambda o: (o.time is None, o.time or 0, o.idx))
            for o in posts:
                now = _lines(texts.get(o.rid, ""))
                added[o.rid] = now - seen
                added_lines[(place, o.rid)] = added[o.rid]
                seen = now
        dated_writes = sorted((w for w in writes if w.time is not None), key=lambda w: (w.time, w.idx))
        done = set()
        for r in sorted(reads, key=lambda r: (r.time is None, r.time or 0, r.idx)):
            if r.time is None:                                                       # R25
                if any(w.actor != r.actor for w in writes):
                    order_unknown += 1
                continue
            cands = [w for w in dated_writes if w.time <= r.time and w.actor != r.actor and w.rid != r.rid]   # R22 to R24
            if texts:                                                                # R23a
                body = texts.get(r.rid, "")
                cands = [w for w in cands if not (w.kind == "token" and _holds_word(body, w.actor))]
            fresh = [w for w in cands if not (program.get(w.rid) and program.get(w.rid) == program.get(r.rid))]   # R27
            if cands and not fresh:
                same_program += 1
            if not fresh:
                continue
            w = fresh[-1]                                                            # R26
            if (w.rid, r.actor) in done:                                             # R28
                repeats += 1
                continue
            done.add((w.rid, r.actor))
            d = {"place": place, "write_id": w.rid, "read_id": r.rid, "from": w.actor, "to": r.actor,
                 "write_time": w.time, "read_time": r.time}
            if full_body and w.op == "post" and r.op == "post":                      # R29
                new = added.get(w.rid, set())
                if new and not (new & _lines(texts.get(r.rid, ""))):
                    overwrites.append(d)
                    continue
                if new:
                    d["overlap"] = True                                              # the read kept lines the write added (R38)
            d["grade"] = _grade(d, w, r, coarse, estimated)
            deliveries.append(d)
    return {"deliveries": deliveries, "overwrites": overwrites, "order_unknown": order_unknown,
            "repeat_reads": repeats, "same_program": same_program, "added_lines": added_lines}


def _grade(d, w, r, coarse, estimated):
    if "default" in (w.how, r.how):                                                  # R31
        return "weak"
    if coarse and any(c.search(d["place"]) for c in coarse):
        return "weak"
    if estimated and (estimated(w.rid) or estimated(r.rid)) and (r.time - w.time) / 3600 > 1:
        return "weak"
    if (w.op == "post" or w.how == "call") and (r.op == "post" or r.how == "call"):  # R32
        return "direct"
    return "inferred"                                                                # R33


# ------------------------------------------------------------------ the written-content test (R38)

_TERM = re.compile(r"\[[A-Z][A-Za-z]*(?:[ :_][A-Za-z_]+)*[ :]\d+\]"            # numbered redaction markers
                   r"|[A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)+"                       # paths
                   r"|[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,6}\b"                           # file names
                   r"|[A-Za-z_][A-Za-z0-9_]*")                                      # identifiers
RARE = 5


def terms(text):
    """R38: the identifiers, paths, file names and numbered redaction markers of 8 or more characters in a text,
    credentials left out."""
    return {t for t in _TERM.findall(text) if len(t) >= 8 and not t.startswith("[CREDENTIAL")}


# R38b: the reader's later output holds a distinctive term the writer wrote

_MARKER_TERM = re.compile(r"\[[A-Za-z][A-Za-z :_]*[ :][0-9]+\]")
_RUN_TERM = re.compile(r"[A-Za-z0-9_.\-/]{5,}")
_STARTS_WITH_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
NUMBER_DIGITS = 5
RUN_LENGTH = 8
_EDGE = ".-/"


def held_terms(text):
    """R38b: the markers and runs of a text. Markers are taken first; the runs (letters, digits and _ . - /) come
    from the rest, without the dots, hyphens and slashes at their ends; runs shorter than 5 characters hold nothing."""
    marks = _MARKER_TERM.findall(text) if "[" in text else []
    if marks:
        text = _MARKER_TERM.sub(" ", text)
    out = set(marks)
    for run in set(_RUN_TERM.findall(text)):
        if run[0] in _EDGE or run[-1] in _EDGE:
            run = run.strip(_EDGE)
            if len(run) < 5:
                continue
        out.add(run)
    return out


def distinctive(term):
    """R38b: a numbered redaction marker that is not a credential; a number of 5 or more digits; a run of 8 or more
    characters with a digit, an underscore or a capital after its first character that does not begin with a date."""
    if term.startswith("["):
        return not term.startswith("[CREDENTIAL")
    if all(c in "0123456789" for c in term):
        return len(term) >= NUMBER_DIGITS
    if len(term) < RUN_LENGTH or _STARTS_WITH_DATE.match(term):
        return False
    return any(c in "0123456789_" or c in _ASCII_UPPER for c in term[1:])


def written_text(text, pack, patterns=True):
    """R38b: the write record without the place's address: every match of a channel pattern of the pack and every
    place argument of R18a is taken out. patterns=False takes out the place arguments only (R38a)."""
    cuts = [(m.start(), m.end()) for _n, rx, _w, _r in _channels(pack) for m in rx.finditer(text)] if patterns else []
    cfg = pack.raw.get("tool_places")
    if isinstance(cfg, dict) and cfg.get("keys"):
        cuts += [(lo, hi) for _v, lo, hi in named_places(text, cfg["keys"])]
    if not cuts:
        return text
    out, at = [], 0
    for lo, hi in sorted(cuts):
        if lo >= at:
            out.append(text[at:lo])
        at = max(at, hi)
    out.append(text[at:])
    return " ".join(out)


def tool_call_content(text, pack):
    """R38b: what a tool call wrote: the strings that are values in the first JSON object of its text, decoded, one
    per line, without the values of the place keys. Keys and the tool's name are left out."""
    cfg = pack.raw.get("tool_places")
    places = {str(k).lower() for k in cfg["keys"]} if isinstance(cfg, dict) and cfg.get("keys") else set()
    return "\n".join(_decoded(raw) for key, raw, _lo, _hi in json_strings(text)
                     if not (key is not None and key.lower() in places and 1 <= len(raw) <= 300))


def record_content(text, tool, pack, patterns=True):
    """R38: the content of a record: of a tool call whose text holds a JSON object, the values of its arguments; of
    any other record, its text. Place arguments are taken out, and with patterns=True (R38b) the matches of the pack's
    channel patterns too."""
    if tool and "{" in text:
        text = tool_call_content(text, pack)
        return written_text(text, pack) if patterns else text
    return written_text(text, pack, patterns)


def later_output(deliveries, events, pack, who, times, added_lines=None):
    """R38b for the deliveries that are not settled otherwise: {index in deliveries: [(term, the reader's record)]},
    the terms a later record of the reader holds, the one found first first.

    who: record id -> (actor, kind, tokens); times: record id -> time; added_lines: (place, record) -> the lines a
    full-body post added (then only these are what was written)."""
    added_lines = added_lines or {}
    by_id = {e.id: e for e in events}
    order = {e.id: n for n, e in enumerate(events)}
    before_all = float("-inf")

    def when(rid):
        t = times.get(rid)
        return (before_all if t is None else t, order[rid])
    wanted = {}                                   # index -> the distinctive terms of what its write record wrote
    for n, d in enumerate(deliveries):
        if d["write_id"] not in by_id or d["read_id"] not in by_id:
            continue
        lines = added_lines.get((d["place"], d["write_id"]))
        write = by_id[d["write_id"]]
        tools = {getattr(write, "tool", None), getattr(by_id[d["read_id"]], "tool", None)}
        text = "\n".join(sorted(lines)) if lines is not None else record_content(write.text, getattr(write, "tool", None), pack)
        terms = {t for t in held_terms(text) if distinctive(t) and t not in tools}
        if terms:
            wanted[n] = terms
    every = set().union(*wanted.values()) if wanted else set()
    if not every:
        return {}
    readers = {deliveries[n]["to"] for n in wanted}
    holders = defaultdict(list)                   # term -> [(when, actor)] of every record that holds it
    records_of = defaultdict(list)                # reader -> [(when, record, terms held)]
    for e in events:
        held = every & held_terms(e.text)
        if not held:
            continue
        actor, at = who[e.id][0], when(e.id)
        for t in held:
            holders[t].append((at, actor))
        if actor in readers:
            records_of[actor].append((at, e, held))
    out = {}
    for n, terms in wanted.items():
        d = deliveries[n]
        write_at, read_at = when(d["write_id"]), when(d["read_id"])
        read = by_id[d["read_id"]]
        terms = terms - held_terms(read.text)                                        # guard 2: the read record holds it
        terms = {t for t in terms                                                    # guard 1: new at the write
                 if not any(at < write_at and actor != d["from"] for at, actor in holders[t])}
        mine = sorted(records_of.get(d["to"], ()), key=lambda x: x[0])
        for at, e, held in mine:                                                     # guard 2: the reader had it before the read
            if e.id != read.id and at < read_at:
                terms = terms - held
        found = {}
        for at, e, held in mine:
            if e.id == read.id or at <= read_at or e.parent == read.id or not is_action(e, pack):
                continue
            for t in held & terms:
                found.setdefault(t, (at, e.id))
        if found:
            out[n] = [(t, found[t][1]) for t in sorted(found, key=lambda t: (found[t][0], -len(t), t))]
    return out


def content_test(deliveries, events, full_body_overlap=None, later=None):
    """Marks each delivery with uses_content and shared_terms (up to three). A logged direct message passes as it
    stands; a wiki edit whose read kept lines the writer added passes by R29 (full_body_overlap: the set of (write,
    read) record ids that did). Any other delivery passes by R38a, when the writer's and the reader's records share at
    least one term, leaving out the place's own address, that is found in at most 5 records of the trace; or by R38b,
    when a later record of the reader holds a distinctive term the writer wrote (later: the keyword arguments of
    later_output after `events`; without it only R38a is tried). Returns the number that pass."""
    by_id = {e.id: e for e in events}
    cache, df = {}, None
    pack = later.get("pack") if later else None

    def of(rid):
        if rid not in cache:
            text = by_id[rid].text if rid in by_id else ""
            if pack is not None:
                tool = getattr(by_id.get(rid), "tool", None)
                # of a tool call only the argument values are content; a place argument is an address (R38)
                text = record_content(text, tool, pack, patterns=False)
                cache[rid] = terms(text) - {tool}
            else:
                cache[rid] = terms(text)
        return cache[rid]
    passed = 0
    open_ = []
    for n, d in enumerate(deliveries):
        if d.get("grade") == "direct" and d["place"].startswith("inbox:"):
            d["uses_content"], d["shared_terms"] = True, []
        elif full_body_overlap and (d["write_id"], d["read_id"]) in full_body_overlap:
            d["uses_content"], d["shared_terms"], d["content_how"] = True, [], "kept lines"
        else:
            shared = of(d["write_id"]) & of(d["read_id"])
            if shared:
                if df is None:
                    df = Counter()
                    for e in events:
                        df.update(terms(e.text) if e.id not in cache else cache[e.id])
                own = terms(d["place"].split(":", 1)[-1])
                shared = {t for t in shared if t not in own and not any(t in o or o in t for o in own)}
            rare = sorted((t for t in shared if df[t] <= RARE), key=lambda t: (df[t], -len(t), t))
            d["uses_content"], d["shared_terms"] = bool(rare), rare[:3]
            if rare:
                d["content_how"] = "quoted in the read"                              # R38a
            else:
                open_.append(n)
        passed += bool(d["uses_content"])
    if later is not None and open_:                                                  # R38b
        got = later_output([deliveries[n] for n in open_], events, **later)
        for k, hits in got.items():
            d = deliveries[open_[k]]
            d["uses_content"], d["shared_terms"] = True, [t for t, _rid in hits[:3]]
            d["content_how"], d["used_in"] = "in the reader's later output", hits[0][1]
            passed += 1
    return passed


def count(events, pack, rec, res):
    """The whole count for a loaded trace. Returns deliveries (pattern places, structural places and dated direct
    messages), overwrites, and the counters of R25, R27 and R28."""
    records, rec_j, joined = join(events, pack, rec)                                 # R13a, before everything else
    who = actors(records, pack, rec_j, res, (events, rec["_ids"]) if joined else None)
    ops = operations(records, pack, rec_j, res, who)
    full_body = bool(pack.raw.get("full_body_posts"))
    by_id = {e.id: e for e in records}
    texts = {rid: e.text for rid, e in by_id.items()}
    program = {rid: _program_key(texts[rid]) for rid in {o.rid for o in ops}}
    coarse = [re.compile(p) for p in pack.raw.get("coarse_channels", [])]
    estimated = lambda rid: rid in by_id and not by_id[rid].time and rid in rec_j["_times"]
    out = link(ops, texts, program, full_body, coarse, estimated)
    dm = direct(events, pack, rec, res, None if joined else who)                     # R20 reads the records as they stand
    out["deliveries"] = out["deliveries"] + [d for d in dm if d["write_time"] is not None]
    out["direct_undated"] = sum(1 for d in dm if d["write_time"] is None)
    out["operations"] = len(ops) + sum(2 if d["read_id"] != d["write_id"] else 1 for d in dm)
    named = [d for d in out["deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    out["named"] = len(named)
    out["named_pairs"] = len({(d["from"], d["to"]) for d in named})
    out["_ops"] = ops
    out["joined"] = joined
    overlap = {(d["write_id"], d["read_id"]) for d in out["deliveries"] if d.get("overlap")}
    out["deliveries_write_then_read"] = len(out["deliveries"])
    out["deliveries_reader_uses_content"] = content_test(
        out["deliveries"], records, overlap,
        later={"pack": pack, "who": who, "times": rec_j["_times"], "added_lines": out.pop("added_lines", None)})
    return out

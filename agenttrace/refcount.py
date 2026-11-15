"""A second, separately written count of deliveries, to check agenttrace/messages.py against.

    from agenttrace import refcount
    out = refcount.count(events, pack, rec, res)      # out["deliveries"]: [{place, write_id, read_id, ...}]

It implements docs/counting-rule.md (statements R1 to R34) and nothing else. It does not import
messages.py. It takes from the rest of the tool only what is not the counting rule: the loaded records,
the pack (its place patterns and verb vocabulary), each record's identity tokens and time (rec["_ids"],
rec["_times"]) and its thread root (res["_root"]).

The method is different on purpose. messages.py judges a mention by regular expressions over a window of
characters around it (the nearest verb wins). This file splits the record into tokens (strings, names,
punctuation), finds the call whose parentheses hold the mention, and reads that call's callee and
arguments. Deliveries are then linked by a sweep over each place's operations in (time, input position) order.

Known differences of method (each can produce a disagreement, listed by tools/crosscheck.py):
  - a call is bounded by its real parentheses, not by a character cap;
  - a Python f-string or raw-string assignment (u=f'...') is followed like any other assignment;
  - an open call with no verb at the end of a record is not counted, however far the end is;
  - string quotes are paired by the tokenizer, so a quote lost to redaction can hide the call around a mention.
"""
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
    if j + 2 < len(toks) and toks[j + 1].kind in ("s", "i") and _is(toks[j + 2], "p", ":"):
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

    def __init__(self, text, wrx, rrx, depth=0):
        self.text, self.wrx, self.rrx, self.depth = text, wrx, rrx, depth
        self._toks = {}

    def toks(self, level):
        if level not in self._toks:
            self._toks[level] = tokens(self.text, level)
        return self._toks[level]

    # -- one call ------------------------------------------------------------
    def call(self, toks, j, k):
        """(verdict, how, lo, hi) for the call opened at toks[j], asked about token k inside it.
        verdict: write, read, None (this call says nothing: not a request, no verb) or 'cut'."""
        end, closed = _match_close(toks, j)
        name = _callee(toks, j)
        last = name.rsplit(".", 1)[-1].lower()
        lo = toks[j - 1].lo if name else toks[j].lo
        hi = toks[end].hi
        own = _own(toks, j, end if closed else end + 1)
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
        op = None
        for m in re.finditer(r"operation[\\'\"]*\s*:\s*[\\'\"]*(upload|download)", self.text[lo:body_hi]):
            op = m.group(1)
        if op:                                             # R6: the request carries a Git LFS operation
            return ("write" if op == "upload" else "read"), "inferred", lo, hi
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
        """R15: an argument that is a bare name holding an object literal with a verb (fetch(u, o))."""
        names = [t.val for x, t in own if t.kind == "i" and "." not in t.val
                 and _is(toks[x - 1], "p") and toks[x - 1].val in "(," and x + 1 < len(toks) and _is(toks[x + 1], "p") and toks[x + 1].val in ",)"]
        for name in names[1:] if len(names) > 1 else []:
            for x in range(j - 1, -1, -1):
                if _is(toks[x], "i", name) and _is(toks[x + 1], "p", "=") and _is(toks[x + 2], "p", "{"):
                    end, _ok = _match_close(toks, x + 2)
                    for t in toks[x + 2:end + 1]:
                        if t.kind == "s" and t.val in WRITE_VERBS:
                            return "write"
                    if self.wrx.search(self.text[toks[x + 2].lo:toks[end].hi]):
                        return "write"
                    return None
        return None

    def climb(self, toks, k):
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
                return v, how, lo, hi, True
            at = j
        return None, None, (first or (toks[k].lo, toks[k].hi))[0], (first or (toks[k].lo, toks[k].hi))[1], first is not None

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

    def lfs(self, toks, k, j):
        """R6: the operation of an LFS batch, read from the call and the code just before it (the body is often
        built into a variable first, and often sits inside a string)."""
        lo = toks[max(0, (j if j is not None else k) - 120)].lo
        hi = toks[_match_close(toks, j)[0]].hi if j is not None else toks[min(len(toks) - 1, k + 200)].hi
        best = None
        for m in re.finditer(r"operation[\\'\"]*\s*:\s*[\\'\"]*(upload|download)", self.text[lo:hi]):
            best = m.group(1)
        return best

    def judge(self, start, end):
        """(op, how, lo, hi): op is write, read or None (not counted); how is call, inferred or default."""
        text = self.text
        level, k, wrapper = self.literal(start, end)
        if wrapper is not None and self.depth < 4:
            lo = wrapper.lo + len(wrapper.q)
            hi = wrapper.hi - (len(wrapper.q) if wrapper.closed else 0)
            inner = Judge(text[lo:hi], self.wrx, self.rrx, self.depth + 1)
            op, how, a, b = inner.judge(start - lo, end - lo)
            return op, how, a + lo, b + lo
        if k is None:
            return self.unquoted(start, end)
        toks = self.toks(level)
        lit = toks[k]
        j, obj = _around(toks, k)
        if "info/lfs" in text[end:end + 40]:                                        # R6
            op = self.lfs(toks, k, j)
            if op is None:
                return None, None, start, end
            return ("write" if op == "upload" else "read"), "inferred", start, end
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
            return self.follow(toks, k, name, level, start, end)
        if j is not None:
            v, how, lo, hi, _in = self.climb(toks, k)
            if v == "cut":
                return None, None, start, end                                        # R13
            if v is not None:
                return v, how, lo, hi                                                # R8, R10, R11
            return "read", "default", lo, hi                                         # R14: a helper with no verb
        cmd = self.command(start, end)
        if cmd:
            return cmd
        if self.closes_statement(toks, k) and not self.config_entry(start) and self.later_write_through_name(end):    # R17
            return None, None, start, end
        return "read", "default", start, end                                         # R14

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

    def unquoted(self, start, end):
        text = self.text
        cmd = self.command(start, end)
        if cmd:
            return cmd
        tail = text[end:end + 90]
        closing = re.match(r"[^'\"`\s;,(){}]{0,80}\\*['\"`][ \t]*(?:;|\r?\n|$)", tail)
        if closing and not self.config_entry(start) and self.later_write_through_name(end):   # R17: the opening is hidden
            return None, None, start, end
        if re.match(r"\s*https?://\S*\s*$", re.sub(r"\[[^\[\]]*\]", "X", text)):         # R13: the record is a bare URL
            return None, None, start, end
        lo, hi = self.line(start, end)
        return "read", "default", lo, hi


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


def actors(events, pack, rec, res):
    """record id -> (actor, kind, the record's non-shared tokens)."""
    shared = set(pack.raw.get("shared_identities", []))
    ids, root = rec["_ids"], res["_root"]
    per_thread = defaultdict(Counter)
    for e in events:
        for t in _own_tokens(e, ids, shared):
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
        for name, rx, wrx, rrx in chans:
            judge = None
            here = {}
            for m in rx.finditer(e.text):
                if not m.group(1) or commented(e.text, m.start()):                   # R1, R3
                    continue
                judge = judge or Judge(e.text, wrx, rrx)
                op, how, lo, hi = judge.judge(m.start(), m.end())                    # R4
                if op is None:
                    continue
                place = name + ":" + m.group(1)
                if place not in here or (op == "write" and here[place][0] != "write"):   # R5
                    here[place] = (op, how, e.text[lo:hi])
            for place, v in here.items():
                if found.get(place, ("",))[0] != "write":
                    found[place] = v
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

def link(ops, texts=None, program=None, full_body=False, coarse=None, estimated=None):
    """Deliveries, overwrites and counters from operations. A sweep over each place in (time, input position) order."""
    program = program or {}
    by_place = defaultdict(list)
    for o in ops:
        by_place[o.place].append(o)
    deliveries, overwrites = [], []
    order_unknown = repeats = same_program = 0
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
                seen = now
        dated_writes = sorted((w for w in writes if w.time is not None), key=lambda w: (w.time, w.idx))
        done = set()
        for r in sorted(reads, key=lambda r: (r.time is None, r.time or 0, r.idx)):
            if r.time is None:                                                       # R25
                if any(w.actor != r.actor for w in writes):
                    order_unknown += 1
                continue
            cands = [w for w in dated_writes if w.time <= r.time and w.actor != r.actor and w.rid != r.rid]   # R22 to R24
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
            d["grade"] = _grade(d, w, r, coarse, estimated)
            deliveries.append(d)
    return {"deliveries": deliveries, "overwrites": overwrites, "order_unknown": order_unknown,
            "repeat_reads": repeats, "same_program": same_program}


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


def count(events, pack, rec, res):
    """The whole count for a loaded trace. Returns deliveries (pattern places, structural places and dated direct
    messages), overwrites, and the counters of R25, R27 and R28."""
    who = actors(events, pack, rec, res)
    ops = operations(events, pack, rec, res, who)
    full_body = bool(pack.raw.get("full_body_posts"))
    texts = {e.id: e.text for e in events} if full_body else None
    program = {}
    for rid in {o.rid for o in ops}:
        program[rid] = None
    by_id = {e.id: e for e in events}
    for rid in program:
        program[rid] = _program_key(by_id[rid].text)
    coarse = [re.compile(p) for p in pack.raw.get("coarse_channels", [])]
    estimated = lambda rid: rid in by_id and not by_id[rid].time and rid in rec["_times"]
    out = link(ops, texts, program, full_body, coarse, estimated)
    dm = direct(events, pack, rec, res, who)
    out["deliveries"] = out["deliveries"] + [d for d in dm if d["write_time"] is not None]
    out["direct_undated"] = sum(1 for d in dm if d["write_time"] is None)
    out["operations"] = len(ops) + sum(2 if d["read_id"] != d["write_id"] else 1 for d in dm)
    named = [d for d in out["deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    out["named"] = len(named)
    out["named_pairs"] = len({(d["from"], d["to"]) for d in named})
    out["_ops"] = ops
    return out

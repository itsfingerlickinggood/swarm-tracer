"""Benchmark: the hand-audited message links of the Swarm Traces release.

    python3 -m agenttrace.benchmark run redacted_columns.csv [--out DIR] [--pack code_traces.json]

agenttrace/claims/audited_links.json holds every link between two named tokens that v1.1.0 reported on
the release (166), every link the code reported at audit time that v1.1.0 did not, and every other delivery
the code reported then (most of them between anonymous run: endpoints), each read by hand and labelled: a true message, or one of the ways a link can be false (the "write" only read the place
and posted elsewhere; it was an LFS download or a Python urlopen; write and read are on different
repositories; the "read" is itself a write), or unclear.

run loads the data with the current code, takes its links between named tokens and scores them against
those labels: precision and recall against the true_message labels (unclear left out and counted), with
Wilson 95% intervals, the count per label for each version, and the regressions: true links now missed,
false links now reported, and links the current code reports that nobody has audited yet.

Each link has an endpoint_kind (named_named, or involves_run when either side is an anonymous run:
endpoint), and precision is reported for each group and overall, with Wilson intervals. Each reported
message also has a grade (direct, inferred, weak: see messages.grade_of) and precision is reported per grade.

independent_agreement() is a second opinion without a second human: a small tokenizer that finds the call
holding the place, its arguments and any verb, following one variable, written apart from messages.judge_span.
It is scored against the labels (raw agreement, Cohen's kappa, the disagreements). It is a different method,
not a second labeller.

Recall here is against the true links in the audited pool, not against every true message in the data:
only links some version of the tool reported were ever read. One labeller, tool-assisted.

GET /api/x/benchmark returns the same for the loaded session when it is the Swarm Traces release (same
record count, audited records present); otherwise {"applies": false}.
"""
import argparse
import json
import os
import re
import sys
import threading

from .labels import wilson

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_PATH = os.path.join(HERE, "claims", "audited_links.json")
TRUE, UNCLEAR, UNAUDITED = "true_message", "unclear", "not_audited"
LABEL_ORDER = ["true_message", "false_write", "false_write_lfs_or_urlopen", "different_repo", "comment_only",
               "read_not_a_read", "unclear"]
SHORT = {"true_message": "true message", "false_write": "read, then posted elsewhere",
         "false_write_lfs_or_urlopen": "LFS download, urlopen or query POST", "different_repo": "different repositories",
         "comment_only": "named in a comment", "read_not_a_read": "the read is a write", "unclear": "unclear",
         "not_audited": "not audited yet"}
GRADES = ("direct", "inferred", "weak")
REQUIRED = ("write_id", "read_id", "from", "to", "label", "reason", "reported_v110", "reported_now",
            "write_snippet", "read_snippet", "endpoint_kind")
_LOCK = threading.Lock()


def load_audit(path=None):
    with open(path or AUDIT_PATH, encoding="utf-8") as f:
        return json.load(f)


def check_audit(audit):
    """Problems with the audited file's structure (an empty list when it is sound)."""
    bad = []
    for k in ("about", "made", "how", "labelled_by", "labels", "counts", "links", "dataset"):
        if k not in audit:
            bad.append(f"missing header field {k}")
    seen = set()
    counts = {}
    for i, r in enumerate(audit.get("links", [])):
        for k in REQUIRED:
            if k not in r:
                bad.append(f"link {i}: missing {k}")
        key = (r.get("write_id"), r.get("read_id"))
        if key in seen:
            bad.append(f"link {i}: duplicate {key}")
        seen.add(key)
        if r.get("label") not in audit.get("labels", {}):
            bad.append(f"link {i}: unknown label {r.get('label')}")
        if not (r.get("reported_v110") or r.get("reported_now") or r.get("reported_phase1")):
            bad.append(f"link {i}: reported by no version")
        for k in ("write_snippet", "read_snippet"):
            if len(r.get(k) or "") > 120:
                bad.append(f"link {i}: {k} longer than 120 characters")
        if r.get("endpoint_kind") not in ("named_named", "involves_run"):
            bad.append(f"link {i}: endpoint_kind must be named_named or involves_run")
        if len(r.get("reason") or "") > 220 or not r.get("reason"):
            bad.append(f"link {i}: reason missing or too long")
        counts[r.get("label")] = counts.get(r.get("label"), 0) + 1
    for k, n in audit.get("counts", {}).items():
        if counts.get(k, 0) != n:
            bad.append(f"header count for {k} is {n}, the links have {counts.get(k, 0)}")
    return bad


def _ci(k, n):
    if not n:
        return None
    lo, hi = wilson(k, n)
    return [round(lo, 4), round(hi, 4)]


def _rate(k, n):
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "ci": _ci(k, n)}


def _public(r):
    return {k: r.get(k) for k in ("write_id", "read_id", "from", "to", "channel_v110", "channel_now", "label", "reason",
                                  "also", "write_snippet", "read_snippet", "latency_h", "reported_v110", "reported_now", "endpoint_kind")}


def score(found, audit):
    """found: the links between named tokens the code under test reports, as dicts with write_id, read_id
    (and from, to, channel when known) or as (write_id, read_id) pairs."""
    links = audit["links"]
    by_key = {(r["write_id"], r["read_id"]): r for r in links}
    fd = {}
    for d in found:
        if isinstance(d, dict):
            fd[(d["write_id"], d["read_id"])] = d
        else:
            fd[tuple(d)] = {"write_id": d[0], "read_id": d[1]}
    labels = [k for k in LABEL_ORDER if k in audit.get("labels", {})] + [k for k in audit.get("labels", {}) if k not in LABEL_ORDER]
    audited = [by_key[k] for k in fd if k in by_key]
    unaudited = [fd[k] for k in fd if k not in by_key]
    tp = sum(1 for r in audited if r["label"] == TRUE)
    unclear_found = sum(1 for r in audited if r["label"] == UNCLEAR)
    judged = len(audited) - unclear_found
    true_all = [r for r in links if r["label"] == TRUE]
    v110 = [r for r in links if r.get("reported_v110")]
    v110_tp = sum(1 for r in v110 if r["label"] == TRUE)
    v110_judged = sum(1 for r in v110 if r["label"] != UNCLEAR)

    def per_label(rows):
        return {k: sum(1 for r in rows if r["label"] == k) for k in labels}
    confusion = []
    for k in labels:
        rows = [r for r in links if r["label"] == k]
        confusion.append({"label": k, "name": SHORT.get(k, k.replace("_", " ")), "what": audit["labels"].get(k, ""),
                          "audited": len(rows), "v110": sum(1 for r in rows if r.get("reported_v110")),
                          "now": sum(1 for r in rows if (r["write_id"], r["read_id"]) in fd),
                          "dropped_now": sum(1 for r in rows if (r["write_id"], r["read_id"]) not in fd)})
    missed = [_public(r) for r in true_all if (r["write_id"], r["read_id"]) not in fd]
    false_now = [_public(r) for r in audited if r["label"] not in (TRUE, UNCLEAR)]
    unclear_rows = [_public(r) for r in audited if r["label"] == UNCLEAR]
    def kind_of(k):
        r = by_key.get(k)
        if r:
            return r.get("endpoint_kind") or _kind(r["from"], r["to"])
        d = fd[k]
        return _kind(d.get("from", ""), d.get("to", "")) if d.get("from") is not None else None

    def group(keys):
        rows = [by_key[k] for k in keys if k in by_key]
        tpg = sum(1 for r in rows if r["label"] == TRUE)
        unc = sum(1 for r in rows if r["label"] == UNCLEAR)
        return {"reported": len(keys), "audited": len(rows), "unclear": unc, "not_audited": len(keys) - len(rows),
                "true": tpg, "false": len(rows) - tpg - unc, "precision": _rate(tpg, len(rows) - unc)}
    groups = {"all": group(list(fd)),
              "named_named": group([k for k in fd if kind_of(k) == "named_named"]),
              "involves_run": group([k for k in fd if kind_of(k) == "involves_run"])}
    in_pool = {g: [r for r in links if (r.get("endpoint_kind") or _kind(r["from"], r["to"])) == g] for g in ("named_named", "involves_run")}
    groups["pool"] = {g: {"links": len(rs), "true": sum(1 for r in rs if r["label"] == TRUE)} for g, rs in in_pool.items()}
    by_grade = {}
    for g in GRADES:
        keys = [k for k in fd if fd[k].get("grade") == g]
        rows = [by_key[k] for k in keys if k in by_key]
        unc = sum(1 for r in rows if r["label"] == UNCLEAR)
        tpg = sum(1 for r in rows if r["label"] == TRUE)
        by_grade[g] = {"reported": len(keys), "audited": len(rows), "unclear": unc, "true": tpg, "false": len(rows) - unc - tpg,
                       "precision": _rate(tpg, len(rows) - unc)}
    named_now = [k for k in fd if kind_of(k) == "named_named"]
    named_audited = [by_key[k] for k in named_now if k in by_key]
    named_tp = sum(1 for r in named_audited if r["label"] == TRUE)
    named_judged = sum(1 for r in named_audited if r["label"] != UNCLEAR)
    return {
        "groups": groups, "by_grade": by_grade,
        "audit": {k: audit.get(k) for k in ("about", "made", "how", "labelled_by", "limits", "dataset")},
        "audited_links": len(links),
        "labels": [{"label": k, "name": SHORT.get(k, k), "what": audit["labels"][k]} for k in labels],
        "reported_now": len(fd), "reported_now_audited": len(audited), "reported_now_unclear": unclear_found,
        "reported_now_not_audited": len(unaudited),
        "precision": _rate(tp, judged),
        "recall": _rate(tp, len(true_all)),
        "true_links_in_pool": len(true_all),
        "confusion": confusion,
        "then_vs_now": {
            "v110": {"reported": len(v110), "by_label": per_label(v110), "precision": _rate(v110_tp, v110_judged),
                     "recall": _rate(v110_tp, len(true_all))},
            "now": {"reported": len(named_now), "by_label": {**per_label(named_audited), UNAUDITED: len(named_now) - len(named_audited)},
                    "precision": _rate(named_tp, named_judged), "recall": _rate(named_tp, len(true_all))},
            "now_all": {"reported": len(fd), "by_label": {**per_label(audited), UNAUDITED: len(unaudited)},
                        "precision": _rate(tp, judged), "recall": _rate(tp, len(true_all))},
            "kept": sum(1 for r in v110 if (r["write_id"], r["read_id"]) in fd),
            "dropped": sum(1 for r in v110 if (r["write_id"], r["read_id"]) not in fd),
            "new": sum(1 for k in named_now if k not in by_key or not by_key[k].get("reported_v110")),
        },
        "regressions": {"true_links_missed": missed, "false_links_reported": false_now,
                        "unclear_links_reported": unclear_rows,
                        "not_audited_links_reported": [{k: d.get(k) for k in ("write_id", "read_id", "from", "to", "channel")}
                                                       for d in unaudited]},
        # where the current code and the reading disagree: it reports a link read as false, or drops one read as true
        "disagreements": false_now + missed,
    }


def _kind(a, b):
    return "involves_run" if str(a).startswith("run:") or str(b).startswith("run:") else "named_named"


def all_links(s):
    """Every delivery the code reports (each with its grade)."""
    return list(s.flow["_deliveries"])


def named_links(s):
    return [d for d in s.flow["_deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")]


# ------------------------------------------------------------------ an independent second method

_TOK = re.compile(r"""'(?:[^'\\\n]|\\.){0,400}(?:'|$)|"(?:[^"\\\n]|\\.){0,400}(?:"|$)|`[^`]{0,400}(?:`|$)|[A-Za-z_$][\w$.]*|\d+|\n|[^\s\w]""")
_VERBS = {"GET": "read", "HEAD": "read", "OPTIONS": "read", "POST": "write", "PUT": "write", "PATCH": "write",
          "DELETE": "write", "MKCOL": "write"}
_WRITE_CALLEE = re.compile(r"(?:^|\.)(?:post|put|patch|delete|sendBeacon|send_file|upload_file|create_commit)$", re.I)
_READ_CALLEE = re.compile(r"(?:^|\.)(?:get|head)$", re.I)
_REQ_CALLEE = re.compile(r"(?:^|\.)(?:fetch|open|urlopen|Request|request|get|post|put|patch|delete|head|ajax|rq|Q|req|go|g|call)$")


def _toks(text):
    """(kind, value, start, end) tokens: s string (value without quotes), i identifier, n newline, p punctuation."""
    out = []
    for m in _TOK.finditer(text):
        t = m.group(0)
        if t[0] in "'\"`":
            out.append(("s", t[1:-1] if len(t) > 1 and t[-1] == t[0] else t[1:], m.start(), m.end()))
        elif t == "\n":
            out.append(("n", t, m.start(), m.end()))
        elif t[0].isalpha() or t[0] in "_$":
            out.append(("i", t, m.start(), m.end()))
        else:
            out.append(("p", t, m.start(), m.end()))
    return out


def _enclosing_call(toks, k):
    """Index of the unmatched '(' before token k within the same statement, or None."""
    depth = 0
    for j in range(k - 1, max(-1, k - 80), -1):
        v = toks[j]
        if v[0] == "p" and v[1] == ")":
            depth += 1
        elif v[0] == "p" and v[1] == "(":
            if depth == 0:
                return j
            depth -= 1
        elif v[0] == "p" and v[1] == "{" and depth == 0:
            # an unmatched '{' is a function or block body (=> { … }) or an object literal inside the call
            before = toks[j - 1] if j else ("n", "", 0, 0)
            if before[1] in (">", ")", "else", "try", "finally", "do", ";", "") or before[0] == "n":
                return None
        elif (v[0] == "n" or (v[0] == "p" and v[1] == ";")) and depth == 0:
            return None
    return None


def _call_args(toks, c):
    """(callee, args, closed): the callee name before '(' at c, its arguments as token lists, and whether it closes."""
    callee = toks[c - 1][1] if c and toks[c - 1][0] == "i" else ""
    args, cur, depth, closed = [], [], 0, False
    last = min(len(toks), c + 160)
    for j in range(c + 1, last):
        v = toks[j]
        if v[0] == "p" and v[1] in "([{":
            depth += 1
        elif v[0] == "p" and v[1] in ")]}":
            if depth == 0:
                closed = True
                break
            depth -= 1
        elif v[0] == "p" and v[1] == ";" and depth == 0:
            break
        if v[0] == "p" and v[1] == "," and depth == 0:
            args.append(cur)
            cur = []
        else:
            cur.append(v)
    args.append(cur)
    return callee, args, closed, (not closed and last == len(toks))


def _verb_in(toks_list):
    for v in toks_list:
        if v[0] == "s" and v[1].upper() == v[1] and v[1] in _VERBS:
            return _VERBS[v[1]]
    return None


def _call_verdict(text, toks, c, k):
    """write / read / None for the request call opened at toks[c]."""
    callee, args, closed, ran_out = _call_args(toks, c)
    flat = [v for a in args for v in a]
    if _WRITE_CALLEE.search(callee):
        return "write", "callee"
    lfs_zone = text[max(0, toks[c][2] - 400):toks[c][2] + 600]
    if re.search(r"info/lfs", text[toks[k][2]:toks[k][2] + 120] + " ".join(v[1] for v in flat)):
        m = re.search(r"operation['\"]?\s*:\s*['\"](upload|download)", lfs_zone)
        return (("write" if m.group(1) == "upload" else "read"), "lfs operation") if m else (None, "lfs operation not in the record")
    v = _verb_in(flat)
    if v:
        return v, "verb"
    # an options object held in a variable: fetch(u, o) with o = {method: 'POST', ...}
    if len(args) > 1 and len(args[1]) == 1 and args[1][0][0] == "i":
        name = args[1][0][1]
        for j in range(c, -1, -1):
            if toks[j][0] == "i" and toks[j][1] == name and j + 1 < len(toks) and toks[j + 1][1] == "=":
                v = _verb_in(toks[j + 2:j + 60])
                if v:
                    return v, "options variable"
                break
    # keyword data=/body=, or a second positional argument to Request(url, data)
    if any(a and a[0][0] == "i" and a[0][1] in ("data", "body", "json") and len(a) > 1 and a[1][1] in "=:" for a in args[1:]):
        return "write", "data argument"
    if callee.endswith("Request") and len(args) > 1 and args[1] and not (args[1][0][0] == "i" and len(args[1]) > 1 and args[1][1][1] in "=:"):
        return "write", "data argument"
    if _READ_CALLEE.search(callee):
        return "read", "callee"
    if re.search(r"x-ndjson|/commit/|preupload", " ".join(v[1] for v in flat)):
        return "write", "commit path"
    if not _REQ_CALLEE.search(callee):
        return None, "not a request"
    if ran_out:
        return None, "cut off"
    return "read", "no verb, so a GET"


def _op_at(text, toks, k):
    """(op, how) for the mention in token k."""
    c = _enclosing_call(toks, k)
    if c is not None:
        callee = toks[c - 1][1] if c and toks[c - 1][0] == "i" else ""
        # the call that holds the place, unless the place is only an argument to a plain wrapper like S(u)
        v, how = _call_verdict(text, toks, c, k)
        if v is not None:
            return v, how
        return None, how
    # an assignment: name = '…place…'; follow the name to the calls that use it, until it is given another value
    j = k - 1
    while j > 0 and not (toks[j][0] == "p" and toks[j][1] == "=") and toks[k - j][0] != "n" and k - j < 8:
        j -= 1
    if j > 0 and toks[j][1] == "=" and toks[j - 1][0] == "i":
        name, seen, verdict = toks[j - 1][1], False, None
        for u in range(k + 1, len(toks)):
            v = toks[u]
            if v[0] == "i" and v[1] == name:
                if u + 1 < len(toks) and toks[u + 1][1] == "=" and toks[u + 1][0] == "p" and not (u + 2 < len(toks) and toks[u + 2][1] == "="):
                    break
                c = _enclosing_call(toks, u)
                if c is not None:
                    r, how = _call_verdict(text, toks, c, k)
                    if r == "write":
                        return "write", "variable: " + how
                    if r == "read" and verdict is None:
                        verdict = ("read", "variable: " + how)
                seen = True
            elif v[0] == "s" and ("{" + name + "}") in v[1]:     # an f-string use
                c = _enclosing_call(toks, u)
                if c is not None:
                    r, how = _call_verdict(text, toks, c, k)
                    if r == "write":
                        return "write", "variable: " + how
        if verdict:
            return verdict
        return None, "named, never used in a call"
    # a request written as data: {"u": place, "m": "POST", "b": …}
    if k >= 2 and toks[k - 1][1] == ":" and toks[k - 2][0] == "s" and toks[k - 2][1] in ("u", "url"):
        lo = max(0, k - 40)
        near = toks[lo:k + 40]
        v = _verb_in(near)
        if v:
            return v, "request object"
        if any(t[0] == "s" and t[1] in ("b", "body", "data") for t in near):
            return "write", "request object"
    return None, "no call found"


def _place_extent(text, pos, name):
    m = re.match(r"[^/'\"?&\s]*(?: REPO \d+\])?", text[pos + len(name):pos + len(name) + 16])
    return name + (m.group(0) if m else "")


def independent_ops(text, name):
    """(op, how, extent) for the place `name` in a record: 'write' if any mention is written, else 'read' if any
    is read, else None. Does not use messages.py."""
    toks = _toks(text)
    best, extent = None, None
    for m in re.finditer(re.escape(name), text):
        k = next((i for i, t in enumerate(toks) if t[2] <= m.start() < t[3]), None)
        if k is None:
            continue
        op, how = _op_at(text, toks, k)
        ext = _place_extent(text, m.start(), name)
        if op == "write" or (op == "read" and best is None) or (best is None and extent is None and op is None):
            if best is None or op == "write":
                best = (op, how)
                extent = ext
            if op == "write":
                break
    return (best[0], best[1], extent) if best else (None, "place not found", None)


def _place_of(r):
    ch = r.get("channel_now") or r.get("channel_v110") or ""
    return ch.split(":", 1)[1] if ":" in ch else ch


def independent_link(s, r):
    """The independent method's verdict on an audited link: is it a message?"""
    name = _place_of(r)
    tw = s.by_id[r["write_id"]].text if r["write_id"] in s.by_id else ""
    tr = s.by_id[r["read_id"]].text if r["read_id"] in s.by_id else ""
    ow, hw, ew = independent_ops(tw, name)
    orr, hr, er = independent_ops(tr, name)
    msg = ow == "write" and orr == "read" and (ew == er or ew is None or er is None)
    return {"write_op": ow, "read_op": orr, "same_place": ew == er, "message": bool(msg), "write_how": hw, "read_how": hr}


def kappa(a, b):
    """Cohen's kappa for two lists of booleans."""
    n = len(a)
    if not n:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def independent_agreement(s, audit):
    """Agreement of the independent method with the labels. Headline: links the labeller could decide (unclear left
    out); also all links with unclear counted as 'not a message'."""
    rows = []
    for r in audit["links"]:
        v = independent_link(s, r)
        rows.append((r, v))

    def stats(sel, unclear_is_no):
        a = [r["label"] == TRUE for r, v in sel]
        b = [v["message"] for r, v in sel]
        n = len(a)
        m = {"true_yes": sum(1 for x, y in zip(a, b) if x and y), "true_no": sum(1 for x, y in zip(a, b) if x and not y),
             "false_yes": sum(1 for x, y in zip(a, b) if not x and y), "false_no": sum(1 for x, y in zip(a, b) if not x and not y)}
        agree = sum(1 for x, y in zip(a, b) if x == y)
        return {"n": n, "agreement": _rate(agree, n), "kappa": kappa(a, b), "matrix": m}
    decided = [(r, v) for r, v in rows if r["label"] != UNCLEAR]
    out = {"decided": stats(decided, False), "all": stats(rows, True),
           "unclear_links": sum(1 for r, v in rows if r["label"] == UNCLEAR),
           "unclear_called_message": sum(1 for r, v in rows if r["label"] == UNCLEAR and v["message"]),
           "method": "a tokenizer finds the call that holds the place, its arguments and any verb (following one variable, an options "
                     "object, an LFS operation, a data argument); no verb in a request call means a GET. Written apart from messages.judge_span.",
           "disagreements": []}
    for r, v in decided:
        if (r["label"] == TRUE) != v["message"]:
            out["disagreements"].append({"write_id": r["write_id"], "read_id": r["read_id"], "label": r["label"], "reason": r["reason"],
                                         "independent": f"write {v['write_op'] or 'unknown'} ({v['write_how']}), read {v['read_op'] or 'unknown'} ({v['read_how']})"
                                                        + ("" if v["same_place"] else ", places differ"),
                                         "endpoint_kind": r.get("endpoint_kind")})
    return out


def applies(s, audit):
    """Is the loaded session the audited release? Same record count, and the audited records are there."""
    want = (audit.get("dataset") or {}).get("records")
    ids = {r["write_id"] for r in audit["links"]} | {r["read_id"] for r in audit["links"]}
    have = sum(1 for i in ids if i in s.by_id)
    if want and len(s.events) != want:
        return False, f"the audit is of the Swarm Traces release ({want:,} records); this dataset has {len(s.events):,}"
    if have < 0.95 * len(ids):
        return False, "the audited records are not in this dataset"
    return True, ""


def simulator_grades():
    """Message precision per grade on the saved validation run's simulated swarms, or None."""
    try:
        from . import validation
        sm = validation.latest_summary()
        return (sm or {}).get("message_grades")
    except Exception:       # pragma: no cover
        return None


def simulator_check():
    """The saved comparison of v1.1.0's rules with the current code on the simulated swarms, or None."""
    try:
        from . import validation
        return validation.old_rules_summary()
    except Exception:       # pragma: no cover
        return None


def run(data, pack="code_traces.json", audit_path=None):
    from .session import Session
    audit = load_audit(audit_path)
    s = Session()
    s.load(data, pack, {}, os.path.basename(data))
    ok, why = applies(s, audit)
    if not ok:
        raise SystemExit("this benchmark does not apply: " + why)
    res = score(all_links(s), audit)
    res["independent"] = independent_agreement(s, audit)
    res["dataset"] = {"name": s.name, "records": len(s.events)}
    return res


def _pct(x):
    if not x or x["value"] is None:
        return "–"
    return f"{100 * x['value']:.0f}% ({x['k']}/{x['n']}; 95% {100 * x['ci'][0]:.0f}–{100 * x['ci'][1]:.0f}%)"


def report_text(res):
    tv = res["then_vs_now"]
    L = [f"Audited links: {res['audited_links']} (labelled {res['audit']['made']}; {res['audit']['labelled_by']})",
         f"Deliveries reported now (all endpoints): {res['reported_now']} "
         f"({res['reported_now_audited']} audited, {res['reported_now_unclear']} unclear, {res['reported_now_not_audited']} not audited yet)",
         f"Precision now: {_pct(res['precision'])}    at v1.1.0: {_pct(tv['v110']['precision'])}",
         f"Recall now (of the {res['true_links_in_pool']} true links in the audited pool): {_pct(res['recall'])}"
         f"    at v1.1.0: {_pct(tv['v110']['recall'])}", "",
         f"{'label':<38}{'audited':>8}{'v1.1.0':>8}{'now':>6}"]
    for c in res["confusion"]:
        L.append(f"{c['name']:<38}{c['audited']:>8}{c['v110']:>8}{c['now']:>6}")
    g = res["groups"]
    L += ["", "Precision by endpoints (unclear left out):"]
    for k, name in (("all", "all deliveries"), ("named_named", "between two named tokens"), ("involves_run", "an anonymous run: on one side")):
        x = g[k]
        L.append(f"  {name:<30}{x['reported']:>4} reported, {x['unclear']} unclear, {x['not_audited']} not audited: {_pct(x['precision'])}")
    L.append("Precision by grade:")
    for k in GRADES:
        x = res["by_grade"][k]
        L.append(f"  {k:<30}{x['reported']:>4} reported, {x['unclear']} unclear: {_pct(x['precision'])}")
    ind = res.get("independent")
    if ind:
        d = ind["decided"]
        L += ["", f"Independent method against the labels (unclear left out, {d['n']} links): agreement {_pct(d['agreement'])}, "
                  f"kappa {d['kappa']}; {len(ind['disagreements'])} disagreements"]
        L += [f"  {r['write_id']} -> {r['read_id']}  [{r['label']}] independent method: {r['independent']}" for r in ind["disagreements"]]
    rg = res["regressions"]
    L += ["", f"True links now missed: {len(rg['true_links_missed'])}"]
    L += [f"  {r['write_id']} -> {r['read_id']}  {r['reason']}" for r in rg["true_links_missed"]]
    L.append(f"False links now reported: {len(rg['false_links_reported'])}")
    L += [f"  {r['write_id']} -> {r['read_id']}  [{r['label']}] {r['reason']}" for r in rg["false_links_reported"]]
    if rg["not_audited_links_reported"]:
        L.append(f"Reported now but never audited: {len(rg['not_audited_links_reported'])}")
        L += [f"  {r['write_id']} -> {r['read_id']}  {r.get('channel') or ''}" for r in rg["not_audited_links_reported"]]
    return "\n".join(L)


# ------------------------------------------------------------------ route

def get_benchmark(state, q):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    sim = simulator_check()
    try:
        audit = load_audit()
    except (OSError, ValueError) as e:
        return {"applies": False, "why": f"the audited file could not be read: {e}", "simulator": sim}
    ok, why = applies(s, audit)
    if not ok:
        return {"applies": False, "why": why, "simulator": sim,
                "audit": {k: audit.get(k) for k in ("made", "labelled_by", "counts", "dataset")}}
    with _LOCK:
        res = getattr(s, "_benchmark", None)
        if res is None:
            res = score(all_links(s), audit)
            res["independent"] = independent_agreement(s, audit)
            res["dataset"] = {"name": s.name, "records": len(s.events)}
            s._benchmark = res
    return {"applies": True, **res, "simulator": sim, "simulator_grades": simulator_grades()}


GET = {"benchmark": get_benchmark}
POST = {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.benchmark", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score the current code's links on the release against the audited labels")
    r.add_argument("data", help="the Swarm Traces release file (redacted_columns.csv)")
    r.add_argument("--pack", default="code_traces.json")
    r.add_argument("--out", default=None, help="folder for benchmark.json and benchmark.txt")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.data, a.pack)
    txt = report_text(res)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "benchmark.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
        with open(os.path.join(a.out, "benchmark.txt"), "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

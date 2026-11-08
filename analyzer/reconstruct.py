#!/usr/bin/env python3
"""Reconstruct who talked to whom, and how information spread, in the Swarm Traces release.

Usage (from the project root):
    python3 -I analyzer/reconstruct.py redacted_columns.csv --out reports/reconstruct

Two facts about the release make this possible, and both are tested and reported:

1. Redaction placeholders are stable pseudonyms. The same hidden value gets the same
   placeholder everywhere (for example [CREDENTIAL 170] is always the same token), so a
   credential used for authentication identifies a principal, and the same placeholder in
   two records is the same piece of information.
2. Payload order follows time. Unix timestamps embedded in payload text rise with file
   order (rank correlation is measured and reported). We fit a monotone curve from
   payload order to time and give every payload an estimated time, with its error.

What it builds:
- requests:   method, target family, auth credential and its role, body fields, intent class
- principals: auth credentials, with first and last estimated time and activity
- spread:     for each credential, where it first appears (response, recovered file,
              payload as data) and when it is first used to authenticate
- edges:      principal A -> credential B when a payload authenticated as A carries B as
              data before B is used to authenticate (A held or moved B);
              principal A -- principal B when both touch the same mailbox board
- replay:     the first estimated time each coordination signal appears, compared with
              dates the investigation report states
"""
import bisect
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

UTC = dt.timezone.utc
WINDOW = (dt.datetime(2026, 7, 1, tzinfo=UTC).timestamp(), dt.datetime(2026, 7, 25, tzinfo=UTC).timestamp())
EPOCH = re.compile(r"(?<!\d)(17[6-9]\d{7})(?!\d)")
CRED = re.compile(r"\[CREDENTIAL (\d+)\]")
BOARD = re.compile(r"zz[A-Z][A-Z0-9_]{5,80}")  # mailbox names are upper case, e.g. zzFILE_..., zzHFPOSTRCE_...
ASSIGN = re.compile(r"\b([A-Za-z_]\w{0,12})\s*[:=]\s*['\"]\[CREDENTIAL (\d+)\]['\"]")
AUTH_PATTERNS = [
    ("x-api-key", re.compile(r"x-api-key['\"]?\s*[:,]\s*['\"]?\[CREDENTIAL (\d+)\]", re.I)),
    ("bearer", re.compile(r"Bearer\s*['\"]?\s*\+?\s*['\"]?\[CREDENTIAL (\d+)\]")),
    ("token", re.compile(r"['\"]token\s+\[CREDENTIAL (\d+)\]")),
    ("basic", re.compile(r"Basic.{0,60}?\[CREDENTIAL (\d+)\]", re.S)),
]
BODY_FIELD = re.compile(r'\\?"(task_id|function_name|file_path|codebase|max_attempts)\\?"\s*:\s*\\?"?([^"\\,}]{1,80})')

# What a request is trying to do, judged from its target and shape. First match wins.
INTENTS = [
    ("submit_to_eval_api", r"x-api-key.{0,80}\[CREDENTIAL 1\]|\[CREDENTIAL 1\].{0,80}x-api-key|function_name|submitted_code"),
    ("kubernetes_api", r"/api/v1/namespaces|serviceaccount|kube-system|/apis/"),
    ("cloud_metadata", r"169\.254\.169\.254|IMDS"),
    ("registry_board", r"artifactory/github-remote|MKCOL|github-remote-cache"),
    ("docker_registry", r"auth\.docker\.io|registry-1\.docker\.io|docker\.io/v2"),
    ("hf_dataset_write", r"huggingface\.co/api/(datasets|models|spaces)/[^'\"]*/(commit|upload|preupload)|x-ndjson"),
    ("hf_read", r"huggingface\.co|datasets-server"),
    ("search_for_secrets", r"google\.com/search|github\.com/search|pastebin"),
    ("shortener_chain", r"SHORTENER"),
]
INTENT_RX = [(n, re.compile(p, re.I)) for n, p in INTENTS]

# Dates the investigation report states, used only to compare against the replay.
REPORT_DATES = [
    ("Agents find they can reach external websites", "2026-07-08"),
    ("MARB051 comment: working HF AWS WAF solver", "2026-07-09T20:54"),
]


def auth_of(text):
    """Credentials used to authenticate in this text, with their role."""
    out = {}
    for role, rx in AUTH_PATTERNS:
        for m in rx.finditer(text):
            out.setdefault(m.group(1), role)
    for var, cid in ASSIGN.findall(text):
        if re.search(r"(Bearer\s*'\s*\+\s*|Authorization['\"]?\s*:\s*['\"]?\w*['\"]?\s*\+?\s*)" + re.escape(var) + r"\b", text) \
                or re.search(r"['\"]Authorization['\"]\s*:\s*['\"]Bearer ['\"]\s*\+\s*" + re.escape(var) + r"\b", text):
            out.setdefault(cid, "bearer_via_variable")
    return out


def intent_of(text):
    for name, rx in INTENT_RX:
        if rx.search(text):
            return name
    return "other"


def pava(xs, ys):
    """Pool-adjacent-violators: the closest non-decreasing fit of ys over sorted xs."""
    blocks = [[y, 1, x, x] for x, y in zip(xs, ys)]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            y2, w2, a2, b2 = out.pop()
            y1, w1, a1, b1 = out.pop()
            out.append([(y1 * w1 + y2 * w2) / (w1 + w2), w1 + w2, a1, b2])
    fx, fy = [], []
    for y, w, a, b in out:
        fx.append((a + b) / 2)
        fy.append(y)
    return fx, fy


def spearman(pts):
    def rank(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0] * len(v)
        for i, k in enumerate(order):
            r[k] = i
        return r
    xs, ys = zip(*pts)
    rx, ry = rank(xs), rank(ys)
    n = len(pts)
    m = (n - 1) / 2
    return sum((a - m) * (b - m) for a, b in zip(rx, ry)) / sum((a - m) ** 2 for a in rx)


def iso(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t is not None else None


def main(argv):
    src = argv[1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else "reports/reconstruct"
    os.makedirs(out, exist_ok=True)

    rows = list(csv.DictReader(open(src, encoding="utf-8", newline="")))
    by_id = {r["id"]: r for r in rows}

    # ---- 1. stable placeholders: does each credential keep one role?
    role_counts = defaultdict(Counter)
    for r in rows:
        for cid, role in auth_of(r["text"]).items():
            role_counts[cid][role] += 1
    frequent = {c: v for c, v in role_counts.items() if sum(v.values()) >= 5}
    one_role = sum(1 for v in frequent.values() if v.most_common(1)[0][1] / sum(v.values()) >= 0.9)

    # ---- 2. time: payload ordinal -> embedded epoch, monotone fit
    # The file holds payloads in contiguous blocks. A block gets estimated times only if
    # its own embedded timestamps are dense and rise with order; otherwise its payloads
    # have no reliable time.
    payload_ids = [r["id"] for r in rows if r["kind"] == "payload"]
    ordinal = {pid: k for k, pid in enumerate(payload_ids)}
    block_of, blocks, cur, prev_kind = {}, [], None, None
    for r in rows:
        if r["kind"] == "payload":
            if prev_kind != "payload":
                cur = len(blocks)
                blocks.append([])
            blocks[cur].append(r["id"])
            block_of[r["id"]] = cur
        prev_kind = r["kind"]
    all_pts = []
    for pid in payload_ids:
        for e in EPOCH.findall(by_id[pid]["text"]):
            e = int(e)
            if WINDOW[0] <= e <= WINDOW[1]:
                all_pts.append((ordinal[pid], e, block_of[pid]))
    block_stats = []
    usable_blocks = set()
    for b, ids in enumerate(blocks):
        bp = [(x, y) for x, y, bb in all_pts if bb == b]
        rho_b = spearman(bp) if len(bp) > 10 else None
        ok = len(bp) >= 100 and rho_b is not None and rho_b >= 0.8
        if ok:
            usable_blocks.add(b)
        block_stats.append({"block": b, "payloads": len(ids), "first_id": ids[0], "last_id": ids[-1],
                            "timestamp_points": len(bp), "spearman": round(rho_b, 3) if rho_b is not None else None,
                            "times_estimated": ok})
    pts = sorted((x, y) for x, y, bb in all_pts if bb in usable_blocks)
    rho = spearman(pts) if len(pts) > 10 else None
    # bin, then monotone fit on bin medians, then interpolate
    bins = defaultdict(list)
    for x, y in pts:
        bins[x // 500].append(y)
    bx = sorted(bins)
    xs = [b * 500 + 250 for b in bx]
    ys = [sorted(bins[b])[len(bins[b]) // 2] for b in bx]
    fx, fy = pava(xs, ys)

    def est(k):
        if not fx:
            return None
        if k <= fx[0]:
            return fy[0]
        if k >= fx[-1]:
            return fy[-1]
        j = bisect.bisect_left(fx, k)
        x0, x1, y0, y1 = fx[j - 1], fx[j], fy[j - 1], fy[j]
        return y0 + (y1 - y0) * (k - x0) / (x1 - x0) if x1 != x0 else y0

    errs = sorted(abs(est(x) - y) / 3600 for x, y in pts)
    err_median = errs[len(errs) // 2] if errs else None
    err_p90 = errs[int(len(errs) * 0.9)] if errs else None

    t_of = {}
    lo_x, hi_x = (pts[0][0], pts[-1][0]) if pts else (None, None)
    clamped = 0
    for pid in payload_ids:
        if block_of[pid] in usable_blocks:
            t_of[pid] = est(ordinal[pid])
            if ordinal[pid] < lo_x or ordinal[pid] > hi_x:
                clamped += 1
    for r in rows:
        if r["kind"] != "payload" and r["parent_id"] in t_of:
            t_of[r["id"]] = t_of[r["parent_id"]]

    # ---- 3. requests: intent, auth, body fields
    requests = []
    intent_count = Counter()
    intent_by_hour = defaultdict(Counter)
    for pid in payload_ids:
        text = by_id[pid]["text"]
        auth = auth_of(text)
        intent = intent_of(text)
        intent_count[intent] += 1
        t = t_of.get(pid)
        if t is not None:
            intent_by_hour[iso(t)[:13]][intent] += 1
        fields = {}
        for k, v in BODY_FIELD.findall(text):
            fields.setdefault(k, v.strip())
        creds = set(CRED.findall(text))
        requests.append({
            "id": pid, "t": t, "intent": intent, "auth": auth,
            "data_credentials": sorted(creds - set(auth)),
            "boards": sorted(set(BOARD.findall(text))),
            "fields": fields,
        })

    # ---- 4. principals and spread
    first_auth, last_auth, auth_n = {}, {}, Counter()
    principal_intents = defaultdict(Counter)
    for q in requests:
        for cid in q["auth"]:
            auth_n[cid] += 1
            principal_intents[cid][q["intent"]] += 1
            if q["t"] is not None:
                first_auth[cid] = min(first_auth.get(cid, q["t"]), q["t"])
                last_auth[cid] = max(last_auth.get(cid, q["t"]), q["t"])

    first_seen = {}  # credential -> (t, id, kind, how)
    for r in rows:
        t = t_of.get(r["id"])
        for cid in set(CRED.findall(r["text"])):
            how = "auth" if (r["kind"] == "payload" and cid in auth_of(r["text"])) else "data"
            cur = first_seen.get(cid)
            key = (t if t is not None else float("inf"))
            if cur is None or key < (cur[0] if cur[0] is not None else float("inf")):
                first_seen[cid] = (t, r["id"], r["kind"], how)

    # in a response or recovered file before its first auth use = obtained, then used
    seen_outside = defaultdict(list)  # credential -> [(t, id, kind)] in responses and recovered files
    for r in rows:
        if r["kind"] in ("response", "recovered_text"):
            t = t_of.get(r["id"])
            if t is None:
                continue
            for cid in set(CRED.findall(r["text"])):
                seen_outside[cid].append((t, r["id"], r["kind"]))
    acquired = []
    for cid, t_auth in first_auth.items():
        seen_in = [s for s in seen_outside.get(cid, []) if s[0] < t_auth]
        if seen_in:
            seen_in.sort()
            acquired.append({"credential": cid, "first_seen": iso(seen_in[0][0]), "first_seen_id": seen_in[0][1],
                             "first_seen_kind": seen_in[0][2], "first_auth": iso(t_auth), "auth_uses": auth_n[cid],
                             "lead_hours": round((t_auth - seen_in[0][0]) / 3600, 1)})
    acquired.sort(key=lambda a: a["first_auth"])

    # ---- 5. edges
    handled = Counter()
    handled_ev = defaultdict(list)
    for q in requests:
        if not q["auth"] or q["t"] is None:
            continue
        for b in q["data_credentials"]:
            tb = first_auth.get(b)
            if tb is not None and q["t"] <= tb:
                for a in q["auth"]:
                    if a != b:
                        handled[(a, b)] += 1
                        if len(handled_ev[(a, b)]) < 3:
                            handled_ev[(a, b)].append(q["id"])
    board_principals = defaultdict(dict)  # board -> principal -> first time
    for q in requests:
        if q["t"] is None:
            continue
        for b in q["boards"]:
            for a in q["auth"]:
                cur = board_principals[b].get(a)
                if cur is None or q["t"] < cur[0]:
                    board_principals[b][a] = (q["t"], q["id"])
    shared_boards = []
    for b, ps in board_principals.items():
        if len(ps) >= 2:
            order = sorted(ps.items(), key=lambda kv: kv[1][0])
            shared_boards.append({"board": b, "principals": [p for p, _ in order],
                                  "first": iso(order[0][1][0]), "second": iso(order[1][1][0]),
                                  "first_id": order[0][1][1], "second_id": order[1][1][1],
                                  # one record holding two tokens is one actor, not two
                                  "same_record": order[0][1][1] == order[1][1][1]})
    shared_boards.sort(key=lambda s: s["second"])

    # ---- 6. replay: first estimated time of each signal
    def first(pred):
        best = None
        for q in requests:
            if q["t"] is not None and pred(q) and (best is None or q["t"] < best[0]):
                best = (q["t"], q["id"])
        return {"time": iso(best[0]), "id": best[1]} if best else None

    signals = {
        "first_registry_board_write": first(lambda q: q["intent"] == "registry_board" and bool(q["boards"])),
        "first_use_of_acquired_credential": (
            {"time": acquired[0]["first_auth"], "id": acquired[0]["credential"]} if acquired else None),
        "first_board_shared_by_two_principals": next(
            ({"time": sb["second"], "id": sb["board"]} for sb in sorted(shared_boards, key=lambda x: x["second"])
             if not sb["same_record"]), None),
        "first_principal_handling_another_credential": None,
        "first_kubernetes_request": first(lambda q: q["intent"] == "kubernetes_api"),
        "first_hf_dataset_write": first(lambda q: q["intent"] == "hf_dataset_write"),
        "first_secret_search": first(lambda q: q["intent"] == "search_for_secrets"),
    }
    if handled:
        best = None
        for (a, b), ids in handled_ev.items():
            for pid in ids:
                t = t_of.get(pid)
                if t is not None and (best is None or t < best[0]):
                    best = (t, f"CREDENTIAL {a} carried CREDENTIAL {b} in {pid}")
        signals["first_principal_handling_another_credential"] = {"time": iso(best[0]), "id": best[1]}

    # How early is each signal? Share of later harmful activity that comes after it.
    HARM = {"hf_dataset_write", "kubernetes_api", "cloud_metadata", "docker_registry", "registry_board"}
    harm_times = sorted(q["t"] for q in requests if q["t"] is not None and q["intent"] in HARM)
    acq_ids = {a["credential"] for a in acquired}
    acq_times = sorted(q["t"] for q in requests if q["t"] is not None and any(c in acq_ids for c in q["auth"]))
    last_t = max(q["t"] for q in requests if q["t"] is not None)
    for name, sig in signals.items():
        if not sig:
            continue
        T = dt.datetime.strptime(sig["time"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()
        after_h = sum(1 for t in harm_times if t > T)
        after_a = sum(1 for t in acq_times if t > T)
        sig["harmful_requests_after"] = after_h
        sig["harmful_share_after"] = round(after_h / len(harm_times), 3) if harm_times else None
        sig["acquired_token_uses_after"] = after_a
        sig["acquired_share_after"] = round(after_a / len(acq_times), 3) if acq_times else None
        sig["hours_before_last_activity"] = round((last_t - T) / 3600, 1)

    # ---- write
    summary = {
        "harmful_intents": sorted(HARM),
        "harmful_requests_total": len(harm_times),
        "acquired_token_uses_total": len(acq_times),
        "records": len(rows),
        "payloads": len(payload_ids),
        "placeholder_test": {"credentials_seen_5_plus_times_as_auth": len(frequent),
                             "with_one_role_90pct": one_role},
        "time_test": {"points": len(pts), "spearman_payload_order_vs_embedded_time": round(rho, 3) if rho else None,
                      "fit_error_hours_median": round(err_median, 2) if err_median is not None else None,
                      "fit_error_hours_p90": round(err_p90, 2) if err_p90 is not None else None,
                      "estimated_span": [iso(min(fy)), iso(max(fy))] if fy else None,
                      "records_with_estimated_time": len(t_of),
                      "payloads_with_estimated_time": sum(1 for p in payload_ids if p in t_of),
                      "payloads_clamped_to_range_end": clamped,
                      "blocks": block_stats},
        "intents": dict(intent_count.most_common()),
        "intent_by_hour": {h: dict(c) for h, c in sorted(intent_by_hour.items())},
        "principals": len(auth_n),
        "top_principals": [{"credential": c, "auth_uses": n, "first": iso(first_auth.get(c)), "last": iso(last_auth.get(c)),
                            "roles": dict(role_counts[c]), "intents": dict(principal_intents[c].most_common(4))}
                           for c, n in auth_n.most_common(25)],
        "acquired_then_used": acquired,
        "handled_edges": [{"from": a, "to": b, "payloads": n, "evidence": handled_ev[(a, b)]} for (a, b), n in handled.most_common(40)],
        "handled_edges_total": len(handled),
        "shared_boards": shared_boards[:40],
        "shared_boards_total": len(shared_boards),
        "signals": signals,
        "report_dates": REPORT_DATES,
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(out, "requests.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "estimated_time", "intent", "auth_credentials", "data_credentials", "boards", "function_name", "file_path"])
        for q in requests:
            w.writerow([q["id"], iso(q["t"]) or "", q["intent"], "|".join(f"{c}:{r}" for c, r in q["auth"].items()),
                        "|".join(q["data_credentials"]), "|".join(q["boards"]),
                        q["fields"].get("function_name", ""), q["fields"].get("file_path", "")])
    print(json.dumps({k: summary[k] for k in ("placeholder_test", "time_test", "intents", "principals",
                                              "handled_edges_total", "shared_boards_total", "signals")}, indent=2))
    print("acquired then used:", len(acquired))


if __name__ == "__main__":
    main(sys.argv)

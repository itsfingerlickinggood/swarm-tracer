#!/usr/bin/env python3
"""Command cards: for each payload that runs or prepares shell commands, record
the commands in order, the output channels its code uses, its purpose hints,
and the responses that are actually in the release.

Usage (from the project root):
    python3 -I analyzer/cards.py redacted_columns.csv --out reports/cards

Writes:
    cards.jsonl       one card per payload that has commands or output channels
    cards.csv         flat version, one row per card
    summary.json      totals used by the viewer

Rules, so the cards stay honest:
- "order" is the order the commands appear in the code. Branches and loops can
  change the real run order, so the card says so.
- "response" is only what a child record in the release says. If there is no
  child response, the card says "not in release". Output is never inferred.
- "purpose" is a hint taken from nearby comments and names. It is labeled as a
  hint with its source.
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

SHELL_CMDS = ["id", "uname", "pwd", "whoami", "hostname", "env", "printenv", "cat", "ls", "find", "ps", "ss",
              "netstat", "ifconfig", "ip", "curl", "wget", "nc", "socat", "base64", "gzip", "tar", "python3",
              "bash", "sh", "kubectl", "docker", "git", "head", "tail", "grep", "df", "mount", "getent",
              "timeout", "tr", "sqlite3", "dd", "chmod", "rm", "mkdir", "crontab", "systemctl", "tailscale"]

FILE_PATH = re.compile(r'file_path\\?"?\s*:\s*\\?"([^"\\]+)')
# A shell command inside a code string: a known command at a word boundary, followed by
# space, end, a pipe, a semicolon, or a parenthesis.
SHELL_TOKEN = re.compile(r"(?<![\w./-])(" + "|".join(sorted(SHELL_CMDS, key=len, reverse=True)) +
                         r")(?=[\s;|)&'\"]|$)")
COMMENT = re.compile(r"(?:^|[\s;{])(?:#|//)\s*([A-Za-z][^\n'\"`;]{5,120})")

CHANNELS = [
    ("registry_folder", r"MKCOL|github-remote-cache|artifactory", "Creates a folder on a package registry (the folder name can carry data)"),
    ("dataset_commit", r"hfcommit|commit\(|huggingface\.co/datasets", "Commits files to a dataset repository"),
    ("http_post", r"method:\s*'POST'|method:\s*\"POST\"|\.open\('POST'|method='POST'|requests\.post|X-API-Key|x-api-key", "Sends data to a service over HTTP POST"),
    ("webhook", r"webhook", "Posts to a webhook (a request log other parties can read)"),
    ("paste_site", r"pastebin", "Posts or reads a paste site"),
    ("rendered_page", r"innerHTML|innerText|document\.write", "Writes the result into the page, where a screenshot can read it"),
    ("file_write", r"open\([^)]*['\"]w|\.write\(", "Writes to a local file"),
]
CHANNEL_RX = [(n, re.compile(p, re.I if n == "http_post" else 0), d) for n, p, d in CHANNELS]


# Categories are our grouping of commands by what they do. They are a reading aid,
# not something the data labels. The first matching rule wins.
CATEGORIES = [
    ("decode_unpack", r"base64|gzip|b32|zlib"),
    ("cloud_cluster", r"kubectl|docker|tailscale|aws|169\.254|IMDS|\bmetadata\b"),
    ("network_request", r"\bcurl\b|\bwget\b|\bnc\b|socat|urllib|requests\.|fetch\(|XMLHttp"),
    ("system_recon", r"^(id|uname|whoami|hostname|pwd|env|printenv|ls|find|ps|ss|netstat|ip|ifconfig|df|mount|getent|head|tail|grep|cat)\b|/proc/|/etc/|resolv"),
    ("file_write_or_delete", r"\btee\b|\bmkdir\b|\brm\b|\bchmod\b|\bdd\b|sqlite3|tar\b|>\s*\S"),
    ("run_code", r"python3|\bbash\b|\bsh\b|\bexec\b|\btimeout\b"),
]
CATEGORY_RX = [(n, re.compile(p)) for n, p in CATEGORIES]


def category_of(cmd):
    for name, rx in CATEGORY_RX:
        if rx.search(cmd):
            return name
    return "other"


def find_commands(text):
    """Commands in the order they appear, with where each came from."""
    out = []
    covered = []  # spans already explained by the file_path field, so they are not counted twice
    fp = FILE_PATH.search(text)
    if fp:
        covered.append((fp.start(), fp.end()))
        segs = [s.strip() for s in fp.group(1).split(";") if s.strip() and s.strip() != "#"]
        for k, s in enumerate(segs[1:], start=1):   # first segment is the file_path value
            out.append({"cmd": s, "source": "file_path_field", "pos": fp.start() + k})
    for m in SHELL_TOKEN.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        # Keep the token and the rest of that clause, so arguments are visible.
        end = len(text)
        for stop in (";", "'", "\"", "`", "\n"):
            j = text.find(stop, m.end())
            if j != -1:
                end = min(end, j)
        clause = text[m.start():min(end, m.start() + 160)].strip()
        out.append({"cmd": clause, "source": "shell_in_code", "pos": m.start()})
    out.sort(key=lambda c: c["pos"])
    seen, dedup = set(), []
    for c in out:
        key = c["cmd"]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)
    for i, c in enumerate(dedup, start=1):
        c["order"] = i
        del c["pos"]
    return dedup


def purpose_hints(text):
    hints = []
    for m in COMMENT.finditer(text):
        s = m.group(1).strip()
        if len(s) >= 6 and s not in hints:
            hints.append(s)
        if len(hints) >= 3:
            break
    return hints


def channels_of(text):
    found = []
    for name, rx, desc in CHANNEL_RX:
        m = rx.search(text)
        if m:
            found.append({"channel": name, "match": m.group(0)[:60], "meaning": desc})
    return found


def main(argv):
    src = argv[1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else "reports/cards"
    os.makedirs(out, exist_ok=True)

    rows = []
    with open(src, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    byid = {r["id"]: r for r in rows}
    kids = defaultdict(list)
    for r in rows:
        if r["parent_id"]:
            kids[r["parent_id"]].append(r)

    cards = []
    cat_count = Counter()
    cat_channel = Counter()
    cat_status = defaultdict(Counter)
    channel_count = Counter()
    cmd_count = Counter()
    full_cmd_count = Counter()
    source_count = Counter()
    pair_count = Counter()
    status_by_channel = defaultdict(Counter)
    ncmd_hist = Counter()
    for r in rows:
        if r["kind"] != "payload":
            continue
        cmds = find_commands(r["text"])
        if not cmds:          # cards are for command-bearing payloads only
            continue
        chans = channels_of(r["text"])
        resp = [k for k in kids.get(r["id"], []) if k["kind"] == "response"]
        other = [k for k in kids.get(r["id"], []) if k["kind"] != "response"]
        for c in cmds:
            c["category"] = category_of(c["cmd"])
            cat_count[c["category"]] += 1
        card_cats = sorted({c["category"] for c in cmds})
        card_chans = sorted({ch["channel"] for ch in chans})
        st_now = "in_release" if resp else "not_in_release"
        for cat in card_cats:
            cat_status[cat][st_now] += 1
            for ch in card_chans:
                cat_channel[(cat, ch)] += 1
        for c in cmds:
            cmd_count[c["cmd"].split()[0]] += 1
            full_cmd_count[c["cmd"]] += 1
            source_count[c["source"]] += 1
        for ch in chans:
            channel_count[ch["channel"]] += 1
        names = sorted({ch["channel"] for ch in chans})
        for x in range(len(names)):
            for y in range(x + 1, len(names)):
                pair_count[(names[x], names[y])] += 1
        st = "in_release" if resp else "not_in_release"
        for ch in chans:
            status_by_channel[ch["channel"]][st] += 1
        n = len(cmds)
        ncmd_hist["1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5 else "6-10" if n <= 10 else "11+"] += 1
        cards.append({
            "id": r["id"],
            "commands": cmds,
            "order_note": "Order is the order of appearance in the code. Branches or loops can change run order.",
            "output_channels": chans,
            "purpose_hints": purpose_hints(r["text"]),
            "response": {
                "status": "in_release" if resp else "not_in_release",
                "records": [{"id": k["id"], "text": k["text"][:400]} for k in resp],
            },
            "related_code_records": [k["id"] for k in other],
            "parent": r["parent_id"] or None,
            "text_preview": r["text"][:300],
        })

    with open(os.path.join(out, "cards.jsonl"), "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "cards.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "n_commands", "first_command", "output_channels", "response_status", "purpose_hint"])
        for c in cards:
            w.writerow([c["id"], len(c["commands"]), c["commands"][0]["cmd"] if c["commands"] else "",
                        "|".join(x["channel"] for x in c["output_channels"]), c["response"]["status"],
                        c["purpose_hints"][0] if c["purpose_hints"] else ""])
    kinds = Counter(r["kind"] for r in rows)
    summary = {
        "data": {
            "rows_in_file": len(rows),
            "kinds": dict(kinds),
            "rows_with_parent": sum(1 for r in rows if r["parent_id"]),
            "payload_rows_with_command": sum(1 for c in cards if c["id"]),
            "payload_rows_with_file_path_field": sum(1 for r in rows if FILE_PATH.search(r["text"])),
        },
        "unique_commands": len(full_cmd_count),
        "categories": dict(cat_count.most_common()),
        "category_channel_flows": [[a, b, n] for (a, b), n in cat_channel.most_common()],
        "category_response": {k: dict(v) for k, v in cat_status.items()},
        "category_rules": [[n, p] for n, p in CATEGORIES],
        "commands_by_source": dict(source_count.most_common()),
        "commands_per_card_hist": dict(ncmd_hist),
        "all_first_words": cmd_count.most_common(),
        "top_full_commands": full_cmd_count.most_common(40),
        "channel_pairs": [[a, b, n] for (a, b), n in pair_count.most_common()],
        "status_by_channel": {k: dict(v) for k, v in status_by_channel.items()},
        "cards": len(cards),
        "cards_with_commands": sum(1 for c in cards if c["commands"]),
        "cards_with_output_channel": sum(1 for c in cards if c["output_channels"]),
        "cards_with_response_in_release": sum(1 for c in cards if c["response"]["status"] == "in_release"),
        "cards_response_not_in_release": sum(1 for c in cards if c["response"]["status"] == "not_in_release"),
        "commands_total": sum(len(c["commands"]) for c in cards),
        "top_commands": cmd_count.most_common(25),
        "channels": dict(channel_count.most_common()),
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: summary[k] for k in summary if k not in ("top_commands", "channels")}, indent=2))


if __name__ == "__main__":
    main(sys.argv)

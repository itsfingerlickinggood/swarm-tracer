#!/usr/bin/env python3
"""Quantify behaviors across every record in the Swarm Traces release.

Usage (from the project root):
    python3 -I forensics/quantify.py redacted_columns.csv forensics/out

Reads all records from the CSV, applies pattern rules (the same ones the viewer
shows), and writes counts. Patterns describe what the text would do; they are
not proof that anything ran. Each rule's precision should be checked on a sample
(see sample_check.csv, written for manual review).
"""
import csv
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

RULES = [
    ("network_request", r"fetch\(|XMLHttpRequest|urllib\.request|requests\.(get|post)|socket\.getaddrinfo"),
    ("http_post", r"method:\s*'POST'|\.open\('POST'|method='POST'|requests\.post"),
    ("remote_delete", r"method:\s*'DELETE'|method='DELETE'|\.delete\("),
    ("api_key_or_bearer", r"X-API-Key|Authorization['\"]?\s*:\s*'Bearer|Bearer '\s*\+"),
    ("image_beacon", r"new Image|\.src\s*=\s*'"),
    ("writes_to_page", r"innerHTML|innerText|document\.write"),
    ("runs_shell", r"os\.popen|subprocess|child_process|exec\("),
    ("reads_system_files", r"/proc/|/etc/|resolv\.conf|environ"),
    ("credential_search", r"serviceaccount|kube|clusterrole|/secrets|\bsecrets\b|auth\.docker\.io/token|LOOT|SECRET|PASSWORD"),
    ("repo_commit", r"hfcommit|commit\(|README\.md|\.huggingface"),
    ("encodes_base64", r"b64encode|base64|b32encode"),
    ("identity_recon", r"\bid;|uname -a|whoami"),
    ("timestamps", r"Date\.now\(\)|time\.time\(\)"),
    ("cloud_metadata", r"169\.254\.169\.254|IMDS"),
    ("pastebin_or_search", r"pastebin|google\.com/search|github\.com/search"),
    ("cache_poisoning_or_registry", r"artifactory|docker ?hub|manifests|forceDownloadIfNewer"),
    ("flag_or_ctf_target", r"flag\{|catflag|CVE-\d{4}-\d+|arvo|cybergym"),
    ("captcha_or_waf", r"captcha|aws-waf|challenge\.js"),
    ("mailbox_board_marker", r"zz[A-Z0-9_]{3,}|MKCOL"),
    ("signed_command_channel", r"signature|RSA|PKCS1|command channel|cmdfile|g23619cmd|OTS92CMD"),
    ("self_replication_or_child_controller", r"child controller|launch.*controller|pod.*create|create.*pod|pkill"),
]
RULE_RE = [(name, re.compile(p, re.I if name == "network_request" else 0)) for name, p in RULES]

PLACEHOLDER_RE = re.compile(r"\[(REDACTED[^\]]*|SERVICE[^\]]*|CREDENTIAL[^\]]*|USER[^\]]*|PROXY[^\]]*|INFRA[^\]]*|ENV VALUE[^\]]*|WEBHOOK[^\]]*|HF REPO[^\]]*)\]")
URL_RE = re.compile(r"https?://[^\s\"'`)]+")
FILEPATH_RE = re.compile(r'"file_path\\?":\s*\\?"([^"\\]+)|file_path[^;]*?:\s*\\"([^\\"]+)')


def commands_of(text):
    m = FILEPATH_RE.search(text)
    if not m:
        return []
    raw = m.group(1) or m.group(2) or ""
    parts = [p.strip() for p in raw.split(";") if p.strip() and p.strip() != "#"]
    return parts[1:]  # first segment is the file_path value itself


def main(argv):
    src = argv[1] if len(argv) > 1 else "redacted_columns.csv"
    out = argv[2] if len(argv) > 2 else "forensics/out"
    os.makedirs(out, exist_ok=True)

    total = 0
    tag_rows = []
    by_kind = Counter()
    rule_hits = Counter()
    rule_by_kind = defaultdict(Counter)
    cmd_counts = Counter()
    url_counts = Counter()
    placeholder_counts = Counter()
    records_with_cmds = 0
    records_with_any_rule = 0
    multi_rule = Counter()
    samples = defaultdict(list)  # rule -> up to N example ids, for manual review

    with open(src, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            text = row["text"]
            kind = row["kind"]
            by_kind[kind] += 1
            hits = [name for name, rx in RULE_RE if rx.search(text)]
            tag_rows.append([row["id"], row["kind"], "|".join(hits), len(commands_of(text))])
            for h in hits:
                rule_hits[h] += 1
                rule_by_kind[h][kind] += 1
                if len(samples[h]) < 200:
                    samples[h].append(row["id"])
            if hits:
                records_with_any_rule += 1
            multi_rule[len(hits)] += 1
            cmds = commands_of(text)
            if cmds:
                records_with_cmds += 1
                for c in cmds:
                    cmd_counts[c] += 1
            for u in set(URL_RE.findall(text)):
                url_counts[re.sub(r"\[[^\]]*\]", "[..]", u)[:120]] += 1
            for p in set(PLACEHOLDER_RE.findall(text)):
                placeholder_counts[p] += 1

    def write(name, header, rows):
        with open(os.path.join(out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    write("record_tags.csv", ["id", "kind", "behavior_tags", "command_count"], tag_rows)
    write("behavior_counts.csv", ["behavior", "records", "pct_of_all", "payload", "recovered_text", "response"],
          [[name, n, round(100 * n / total, 2),
            rule_by_kind[name].get("payload", 0),
            rule_by_kind[name].get("recovered_text", 0),
            rule_by_kind[name].get("response", 0)]
           for name, n in rule_hits.most_common()])
    write("commands.csv", ["command", "records"], cmd_counts.most_common())
    write("endpoints.csv", ["endpoint_pattern", "records"], url_counts.most_common(200))
    write("placeholders.csv", ["placeholder", "records"], placeholder_counts.most_common())
    write("sample_ids_by_behavior.csv", ["behavior", "record_ids (first 200)"],
          [[k, " ".join(v)] for k, v in samples.items()])

    random.seed(1)
    sample_rows = []
    with open(src, encoding="utf-8", newline="") as f:
        all_rows = list(csv.DictReader(f))
    for name, _ in RULE_RE:
        ids = samples.get(name, [])
        for rid in random.sample(ids, min(10, len(ids))):
            row = next(r for r in all_rows if r["id"] == rid)
            sample_rows.append([name, rid, row["kind"], row["text"][:300].replace("\n", " ")])
    write("sample_check.csv", ["behavior", "id", "kind", "text_preview"], sample_rows)

    summary = {
        "records": total,
        "by_kind": dict(by_kind),
        "records_with_any_behavior": records_with_any_rule,
        "records_with_shell_commands_in_file_path": records_with_cmds,
        "behaviors_per_record": dict(sorted(multi_rule.items())),
        "behaviors": dict(rule_hits.most_common()),
        "top_commands": cmd_counts.most_common(25),
        "top_endpoints": url_counts.most_common(15),
        "placeholders": dict(placeholder_counts.most_common()),
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main(sys.argv)

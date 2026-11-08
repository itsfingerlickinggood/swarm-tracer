#!/usr/bin/env python3
"""Group near-duplicate records into families, so distinct programs can be counted
instead of raw copies.

Usage (from the project root):
    python3 -I forensics/cluster.py redacted_columns.csv forensics/out

Method:
1. Normalize each text: placeholders like [REDACTED:...] become <P>, hex runs
   become <H>, numbers become <N>, whitespace collapses. Two copies that differ
   only in ids, ports, or hashes then normalize to the same string.
2. Exact groups: identical normalized text (sha1).
3. Near groups: 64-bit SimHash over 5-word shingles. Candidates share one of
   4 bands of 16 bits; a pair joins if Hamming distance <= MAX_HAMMING.
4. Union-find over the joined pairs gives the families.

Outputs: clusters.csv (one row per family), record_cluster.csv (id -> family),
cluster_summary.json.
"""
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

MAX_HAMMING = 6          # <= 6 differing bits of 64 is a close near-duplicate
BAND_BUCKET_CAP = 5000   # skip buckets larger than this (boilerplate); noted in the summary
SHINGLE = 4              # tokens per shingle

MIN_TOKENS = 20          # shorter texts only group when their normalized text is identical
PLACEHOLDER = re.compile(r"\[([A-Za-z][A-Za-z _\-]*)(?::[^\]]*)?\]")  # keep the label, drop the ids
HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
NUM = re.compile(r"\b\d+\b")
WS = re.compile(r"\s+")
# Tokens for code: placeholder labels, words, and single punctuation marks.
TOKEN = re.compile(r"<[a-z][a-z _\-]*>|\w+|[^\w\s]")


def normalize(text):
    t = PLACEHOLDER.sub(lambda m: " <" + m.group(1).strip().lower().replace(" ", "_") + "> ", text)
    t = HEX.sub(" <h> ", t)
    t = NUM.sub(" <n> ", t)
    t = t.lower()
    return WS.sub(" ", t).strip()


def simhash(text):
    words = TOKEN.findall(text)
    if len(words) < SHINGLE:
        shingles = [" ".join(words)]
    else:
        shingles = [" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)]
    v = [0] * 64
    for s in set(shingles):
        h = int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big")
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if v[b] > 0:
            out |= 1 << b
    return out


def hamming(a, b):
    return bin(a ^ b).count("1")


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def main(argv):
    src = argv[1] if len(argv) > 1 else "redacted_columns.csv"
    out = argv[2] if len(argv) > 2 else "forensics/out"
    os.makedirs(out, exist_ok=True)

    ids, kinds, texts = [], [], []
    with open(src, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ids.append(row["id"])
            kinds.append(row["kind"])
            texts.append(normalize(row["text"]))
    n = len(ids)

    # Exact groups first: they cost nothing and cover most of the duplication.
    exact_of = {}
    exact_rep = []
    for i, t in enumerate(texts):
        key = hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()
        if key not in exact_of:
            exact_of[key] = i
        exact_rep.append(exact_of[key])
    reps = sorted(set(exact_rep))

    # SimHash over unique normalized texts only. Very short texts are not joined
    # by similarity: after normalization they all look alike, which over-groups.
    long_reps = [i for i in reps if len(TOKEN.findall(texts[i])) >= MIN_TOKENS]
    sig = {i: simhash(texts[i]) for i in long_reps}

    bands = [defaultdict(list) for _ in range(4)]
    for i in long_reps:
        s = sig[i]
        for b in range(4):
            bands[b][(s >> (16 * b)) & 0xFFFF].append(i)

    dsu = DSU(n)
    skipped_buckets = 0
    pairs_checked = 0
    for b in range(4):
        for bucket in bands[b].values():
            if len(bucket) < 2:
                continue
            if len(bucket) > BAND_BUCKET_CAP:
                skipped_buckets += 1
                continue
            for x in range(len(bucket)):
                for y in range(x + 1, len(bucket)):
                    i, j = bucket[x], bucket[y]
                    pairs_checked += 1
                    if hamming(sig[i], sig[j]) <= MAX_HAMMING:
                        dsu.union(i, j)

    # Each record belongs to the family of its exact representative.
    family_of = {}
    for i in range(n):
        family_of[i] = dsu.find(exact_rep[i])

    members = defaultdict(list)
    for i in range(n):
        members[family_of[i]].append(i)

    ranked = sorted(members.items(), key=lambda kv: -len(kv[1]))
    cluster_ids = {root: f"F{k + 1:05d}" for k, (root, _) in enumerate(ranked)}

    with open(os.path.join(out, "record_cluster.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "kind", "cluster_id"])
        for i in range(n):
            w.writerow([ids[i], kinds[i], cluster_ids[family_of[i]]])

    with open(os.path.join(out, "clusters.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "records", "payload", "recovered_text", "response",
                    "first_id", "last_id", "distinct_normalized_texts", "preview"])
        for root, mem in ranked:
            kc = Counter(kinds[i] for i in mem)
            distinct = len({exact_rep[i] for i in mem})
            rep_text = texts[root][:200]
            w.writerow([cluster_ids[root], len(mem), kc.get("payload", 0), kc.get("recovered_text", 0),
                        kc.get("response", 0), ids[min(mem)], ids[max(mem)], distinct, rep_text])

    sizes = [len(m) for _, m in ranked]
    singletons = sum(1 for s in sizes if s == 1)
    summary = {
        "records": n,
        "exact_unique_normalized_texts": len(reps),
        "families": len(ranked),
        "singleton_families": singletons,
        "largest_family_sizes": sizes[:15],
        "families_with_10_plus_records": sum(1 for s in sizes if s >= 10),
        "records_in_families_of_10_plus": sum(s for s in sizes if s >= 10),
        "bands_pairs_checked": pairs_checked,
        "skipped_oversized_buckets": skipped_buckets,
        "max_hamming": MAX_HAMMING,
    }
    with open(os.path.join(out, "cluster_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv)

"""Measure rule precision and recall by hand labels.

Workflow:
  1. sample: write a CSV of records to read. Per tag, up to N records that the tag
     fires on. Plus controls: records with no evidence tag.
  2. Fill the `label` column:
       for a tagged record:  1 = the behavior the tag describes is visible; 0 = it is not
       for a control record: 1 = a behavior is visible that the tags missed; 0 = nothing visible
       leave blank when you cannot tell from the preview
  3. precision: reads the filled CSV and reports precision per tag with 95% Wilson
     intervals, and the miss rate on controls.

Sample size matters: intervals at n=10 are wide. Report them.
"""
import csv
import random


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def write_sample(path, events, res, per_tag=10, controls=30, seed=1, preview=230):
    rng = random.Random(seed)
    by_id = {e.id: e for e in events}
    rows = []
    tags = sorted({t for ts in res["_evidence"].values() for t in ts})
    for tag in tags:
        pool = [i for i, ts in res["_evidence"].items() if tag in ts]
        for i in rng.sample(pool, min(per_tag, len(pool))):
            rows.append([i, tag, _preview(by_id[i].text, preview), ""])
    pool = [i for i, ts in res["_evidence"].items() if not ts]
    for i in rng.sample(pool, min(controls, len(pool))):
        rows.append([i, "control", _preview(by_id[i].text, preview), ""])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "tag", "preview", "label"])
        w.writerows(rows)
    return len(rows)


def _preview(text, n):
    import re
    return re.sub(r"\s+", " ", text)[:n]


def precision(path):
    tags = {}
    controls = {"n": 0, "missed": 0, "clean": 0, "unclear": 0}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lab = (r.get("label") or "").strip()
            if r["tag"] == "control":
                controls["n"] += 1
                if lab == "1":
                    controls["missed"] += 1
                elif lab == "0":
                    controls["clean"] += 1
                else:
                    controls["unclear"] += 1
                continue
            t = tags.setdefault(r["tag"], {"n": 0, "tp": 0, "fp": 0, "unclear": 0})
            t["n"] += 1
            if lab == "1":
                t["tp"] += 1
            elif lab == "0":
                t["fp"] += 1
            else:
                t["unclear"] += 1
    out = {}
    for tag, t in sorted(tags.items()):
        j = t["tp"] + t["fp"]
        lo, hi = wilson(t["tp"], j)
        out[tag] = {**t, "judged": j,
                    "precision": (t["tp"] / j) if j else None,
                    "ci_low": lo if j else None, "ci_high": hi if j else None}
    c = dict(controls)
    judged = c["missed"] + c["clean"]
    c["miss_rate"] = (c["missed"] / judged) if judged else None
    return {"tags": out, "controls": c}

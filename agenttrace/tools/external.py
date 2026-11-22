"""Openly licensed third-party datasets: fetch a documented subset, convert it, measure the tool on it.

    python3 -m agenttrace.tools.external fetch salt        # 114 Parquet files, 81 MB (the 8 GB of traces are left out)
    python3 -m agenttrace.tools.external fetch moltbook    # posts and comments of 2026-02-13 .. 2026-02-19, about 75 MB
    python3 -m agenttrace.tools.external convert salt      # Parquet -> JSON Lines, same columns (needs the duckdb module)
    python3 -m agenttrace.tools.external convert moltbook
    python3 -m agenttrace.external_eval salt               # the measurement (reports/external/<name>/)

Both datasets are MIT licensed (read on the source pages on 2026-11-22) and are fetched anonymously from a pinned
revision of their Hugging Face repositories into datasets-ext/<name>/, which git ignores. Nothing is uploaded. Every
data file is checked against the SHA-256 the repository lists for it, and MANIFEST.json records what was fetched.

The files are data. Nothing in them is executed, and the two repositories' own scripts are not downloaded. Parquet
cannot be read with the standard library, so `convert` uses the duckdb module when it is installed; the tool itself
stays standard-library only and reads the JSON Lines that `convert` writes (agenttrace/readers_public.py).

Subsets, and why:
  salt      SALT-NLP/agent-collusion is 8.12 GB, of which 8.04 GB is full model contexts under traces/ and peer-cache/.
            We take data/ only: every episode with its messages, verdicts and labels (27,100 episodes, 2,650 runs).
  moltbook  SimulaMet/moltbook-observatory-archive is 5.38 GB. We take one week, 13 to 19 February 2026, of the posts
            and comments tables (the card calls both substantially complete up to the end of March 2026). The agents
            table is not fetched: it holds the X handles of the people who own the agents.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEST = os.path.join(ROOT, "datasets-ext")
UA = "dataset-fetch/1.0"
HF = "https://huggingface.co"
SAFE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*")

MOLTBOOK_DAYS = ["2026-02-13", "2026-02-14", "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19"]

SOURCES = {
    "salt": {
        "dir": "salt-agent-collusion",
        "repo": "SALT-NLP/agent-collusion",
        "revision": "2eba8f3771e8fbcc0f49f6cbbfd2111b939a117a",
        "licence": "MIT (LICENSE in the repository: Copyright (c) 2026 Xinrui Shi, Yanzhe Zhang, and Diyi Yang)",
        "attribution": "Shi, Zhang and Yang, \"Emergent Collusion in Long-Horizon LLM Agent Interaction\", 2026, "
                       "arXiv:2609.24967; data: huggingface.co/datasets/SALT-NLP/agent-collusion (MIT)",
        "full_size_bytes": 8123119749,
        "docs": ["LICENSE", "README.md", "SCHEMA.md", "EXPERIMENTS.md"],
        "trees": ["data"],
        "keep": lambda p: p.startswith("data/") and p.endswith(".parquet"),
        "subset": "data/ only (all ten tables); traces/ and peer-cache/ (8.04 GB of full model contexts) are left out",
    },
    "moltbook": {
        "dir": "moltbook-observatory",
        "repo": "SimulaMet/moltbook-observatory-archive",
        "revision": "33c69984a481073aee77b6c6da30d9d4a70bc827",
        "licence": "MIT (declared on the dataset card by the collectors; Moltbook's own terms were not read)",
        "attribution": "Gautam and Riegler, \"Moltbook Observatory Archive\", Hugging Face Datasets, 2026, "
                       "huggingface.co/datasets/SimulaMet/moltbook-observatory-archive (MIT)",
        "full_size_bytes": 5383581623,
        "docs": ["README.md", "manifest.json"],
        "trees": ["data/posts", "data/comments"],
        "keep": lambda p: any(p == f"data/{t}/{d}.parquet" for t in ("posts", "comments") for d in MOLTBOOK_DAYS),
        "subset": "data/posts and data/comments for 2026-02-13 to 2026-02-19 (7 daily files each); no agents table",
    },
}


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def _safe_join(base, rel):
    """rel comes from a remote listing: accept plain relative paths only, and never leave base."""
    if not SAFE.fullmatch(rel) or ".." in rel.split("/"):
        raise ValueError(f"refusing the remote path {rel!r}")
    path = os.path.abspath(os.path.join(base, rel))
    if os.path.commonpath([path, os.path.abspath(base)]) != os.path.abspath(base):
        raise ValueError(f"refusing the remote path {rel!r}")
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def listing(src):
    """[(path, size, sha256 or None)] of the subset, from the repository's tree API at the pinned revision."""
    out = []
    for tree in src["trees"]:
        url = f"{HF}/api/datasets/{src['repo']}/tree/{src['revision']}/{tree}?recursive=true&limit=1000"
        while url:
            with _get(url) as r:
                rows = json.load(r)
                link = r.headers.get("Link") or ""
            for x in rows:
                if x.get("type") == "file" and src["keep"](x["path"]):
                    out.append((x["path"], int(x["size"]), (x.get("lfs") or {}).get("oid")))
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m and m.group(1).startswith(HF + "/api/datasets/") else None
    return sorted(out)


def fetch(name, dest=DEST, log=print, max_bytes=1_500_000_000):
    src = SOURCES[name]
    base = os.path.join(dest, src["dir"])
    os.makedirs(base, exist_ok=True)
    files = listing(src)
    total = sum(s for _, s, _ in files)
    log(f"{name}: {len(files)} files, {total / 1e6:.1f} MB of {src['full_size_bytes'] / 1e9:.2f} GB ({src['subset']})")
    if total > max_bytes:
        raise SystemExit(f"{name}: the subset is {total / 1e9:.2f} GB, over the {max_bytes / 1e9:.1f} GB limit; nothing fetched")
    got = []
    for rel in src["docs"]:
        path = _safe_join(base, rel)
        with _get(f"{HF}/datasets/{src['repo']}/resolve/{src['revision']}/{rel}") as r, open(path, "wb") as f:
            f.write(r.read(5_000_000))
        got.append({"path": rel, "bytes": os.path.getsize(path), "sha256": _sha256(path)})
    for i, (rel, size, oid) in enumerate(files, start=1):
        path = _safe_join(base, rel)
        if not (os.path.exists(path) and os.path.getsize(path) == size and (not oid or _sha256(path) == oid)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with _get(f"{HF}/datasets/{src['repo']}/resolve/{src['revision']}/{rel}", timeout=600) as r, open(tmp, "wb") as f:
                left = size + 1
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    left -= len(chunk)
                    if left < 0:
                        raise SystemExit(f"{rel}: larger than the listed {size} bytes; stopped")
                    f.write(chunk)
            sha = _sha256(tmp)
            if os.path.getsize(tmp) != size or (oid and sha != oid):
                os.unlink(tmp)
                raise SystemExit(f"{rel}: size or SHA-256 does not match the repository's listing; not kept")
            os.replace(tmp, path)
        got.append({"path": rel, "bytes": size, "sha256": oid or _sha256(path), "sha256_listed": bool(oid)})
        if i % 20 == 0 or i == len(files):
            log(f"  {i}/{len(files)}")
    manifest = {"dataset": name, "repo": src["repo"], "revision": src["revision"], "source": f"{HF}/datasets/{src['repo']}",
                "licence": src["licence"], "attribution": src["attribution"], "subset": src["subset"],
                "full_size_bytes": src["full_size_bytes"], "fetched_bytes": sum(g["bytes"] for g in got),
                "files": got, "access": "anonymous HTTPS; no token"}
    with open(os.path.join(base, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    log(f"{name}: {manifest['fetched_bytes'] / 1e6:.1f} MB in {base}")
    return manifest


# ------------------------------------------------------------------ Parquet -> JSON Lines (same columns)

MOLTBOOK_COMMUNITIES = 40     # the communities (submolts) with the most comments in the week, fixed before any result
NAME_OK = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")


def _duckdb():
    try:
        import duckdb
    except ImportError:
        duckdb = None
        if sys.flags.isolated:          # python3 -I leaves the user's site-packages out; add that one folder back
            import site
            sys.path.append(site.getusersitepackages())
            try:
                import duckdb
            except ImportError:
                duckdb = None
    if duckdb is None:
        raise SystemExit("convert needs the duckdb module to read Parquet (pip install duckdb). The tool itself does not: "
                         "it reads the JSON Lines this step writes.")
    return duckdb


def _copy(con, select, out, params=None):
    """Write a query's rows as JSON Lines. Values from the data reach SQL only as parameters; the path is ours."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    if "'" in tmp:
        raise SystemExit(f"refusing the output path {tmp!r}")
    con.execute("CREATE OR REPLACE TEMP TABLE _sel AS " + select, params or [])
    con.execute(f"COPY _sel TO '{tmp}' (FORMAT JSON)")
    os.replace(tmp, out)
    return con.execute("SELECT count(*) FROM _sel").fetchone()[0]


def convert(name, dest=DEST, log=print):
    """Write datasets-ext/<dir>/jsonl/ with the columns of the Parquet tables, unchanged.
    salt      episodes/<condition>.jsonl (the traces: one row per episode, with its messages) and tables/*.jsonl
              (runs, conditions, the judges' and the human labels; from agents only the short columns)
    moltbook  communities/NN-<name>.jsonl: for each of the 40 communities with the most comments in the week, its
              posts and the comments on them in time order, one row each (posts and comments keep their own columns)"""
    duckdb = _duckdb()
    src = SOURCES[name]
    base = os.path.join(dest, src["dir"])
    out = os.path.join(base, "jsonl")
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    counts = {}
    g = os.path.join(base, "data")
    if "'" in g:
        raise SystemExit(f"refusing the data path {g!r}")
    if name == "salt":
        conds = sorted((fam, os.path.splitext(f)[0]) for fam in sorted(os.listdir(os.path.join(g, "episodes")))
                       for f in sorted(os.listdir(os.path.join(g, "episodes", fam))) if f.endswith(".parquet"))
        for fam, c in conds:
            if not SAFE.fullmatch(fam) or not SAFE.fullmatch(c):
                raise SystemExit(f"unexpected file name {fam}/{c}")
            counts[f"episodes/{c}"] = _copy(con, f"SELECT * FROM read_parquet('{g}/episodes/{fam}/{c}.parquet') ORDER BY run_id, episode_index",
                                            os.path.join(out, "episodes", c + ".jsonl"))
        for t in ("runs", "conditions", "human_samples", "human_annotations", "human_answers", "agreement", "relaxation"):
            counts[t] = _copy(con, f"SELECT * FROM read_parquet('{g}/{t}.parquet')", os.path.join(out, "tables", t + ".jsonl"))
        counts["agents"] = _copy(con, "SELECT run_id, condition_id, sequence_id, episode_index, evaluation_episode, is_warmup, agent, model, "
                                      "task_correct, verdict, verdict_correct, relaxation, relaxation_status "
                                      f"FROM read_parquet('{g}/agents/*/*.parquet') ORDER BY run_id, episode_index, agent",
                                 os.path.join(out, "tables", "agents.jsonl"))
    else:
        ts = "strftime(created_at, '%Y-%m-%dT%H:%M:%S.%fZ')"
        lo, hi = MOLTBOOK_DAYS[0], MOLTBOOK_DAYS[-1]
        # one row per id (a later fetch of the same post replaces the earlier one), created inside the week
        con.execute("CREATE TABLE p AS SELECT id, agent_id, agent_name, submolt, title, content, url, score, comment_count, "
                    f"{ts} AS created_at FROM (SELECT *, row_number() OVER (PARTITION BY id ORDER BY fetched_at DESC) rn "
                    f"FROM read_parquet('{g}/posts/*.parquet')) WHERE rn = 1 AND strftime(created_at, '%Y-%m-%d') BETWEEN ? AND ?", [lo, hi])
        con.execute("CREATE TABLE c AS SELECT id, post_id, agent_id, agent_name, parent_id, content, score, "
                    f"{ts} AS created_at FROM (SELECT *, row_number() OVER (PARTITION BY id ORDER BY fetched_at DESC) rn "
                    f"FROM read_parquet('{g}/comments/*.parquet')) WHERE rn = 1 AND strftime(created_at, '%Y-%m-%d') BETWEEN ? AND ?", [lo, hi])
        totals = {"posts": con.execute("SELECT count(*) FROM p").fetchone()[0], "comments": con.execute("SELECT count(*) FROM c").fetchone()[0],
                  "comments_on_posts_of_the_week": con.execute("SELECT count(*) FROM c WHERE post_id IN (SELECT id FROM p)").fetchone()[0],
                  "communities": con.execute("SELECT count(DISTINCT submolt) FROM p").fetchone()[0]}
        top = con.execute("SELECT p.submolt, count(*) n FROM c JOIN p ON p.id = c.post_id WHERE p.submolt IS NOT NULL "
                          "GROUP BY 1 ORDER BY n DESC, 1 LIMIT ?", [MOLTBOOK_COMMUNITIES]).fetchall()
        index = []
        for rank, (sub, n) in enumerate(top, start=1):
            fname = f"{rank:02d}-{sub if NAME_OK.fullmatch(sub) else 'community'}.jsonl"
            rows = _copy(con, "SELECT * FROM (SELECT id, agent_id, agent_name, submolt, title, content, url, score, comment_count, created_at, "
                              "NULL::VARCHAR AS post_id, NULL::VARCHAR AS parent_id FROM p WHERE submolt = $1 "
                              "UNION ALL SELECT c.id, c.agent_id, c.agent_name, p.submolt, NULL, c.content, NULL, c.score, NULL, c.created_at, c.post_id, c.parent_id "
                              "FROM c JOIN p ON p.id = c.post_id WHERE p.submolt = $1) ORDER BY created_at, id",
                         os.path.join(out, "communities", fname), [sub])
            counts[f"communities/{fname}"] = rows
            index.append({"rank": rank, "community": sub, "file": f"communities/{fname}", "rows": rows, "comments": n, "posts": rows - n})
        with open(os.path.join(out, "communities.json"), "w", encoding="utf-8") as f:
            json.dump({"week": [lo, hi], "rule": f"the {MOLTBOOK_COMMUNITIES} communities with the most comments (made in the week, on posts "
                       "made in the week); ties by name", "totals": totals, "communities": index}, f, indent=1)
    with open(os.path.join(out, "COUNTS.json"), "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=1)
    log(f"{name}: {sum(counts.values()):,} rows in {len(counts)} files under {out}")
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.external", description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("fetch", "convert", "list"))
    ap.add_argument("dataset", choices=sorted(SOURCES))
    ap.add_argument("--dest", default=DEST)
    a = ap.parse_args(argv)
    if a.step == "list":
        files = listing(SOURCES[a.dataset])
        for p, s, _ in files:
            print(f"{s:>12,}  {p}")
        print(f"{sum(s for _, s, _ in files):>12,}  total ({len(files)} files)")
    elif a.step == "fetch":
        fetch(a.dataset, a.dest)
    else:
        convert(a.dataset, a.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

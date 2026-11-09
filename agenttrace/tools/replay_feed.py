"""Replay an existing trace into a new file, record by record, at a chosen speed.

    python3 -m agenttrace.tools.replay_feed redacted.jsonl /tmp/feed.jsonl --rate 2000

Point the app's live mode (the Live button) at the output file to watch the warning signs and
alert rules fire as the records arrive. Records are written in order of their time: the time
field when the trace has one, else the time the tracer estimates (this runs the analysis once
first, which takes a while on a large trace; --fast uses the time field only, --no-sort keeps the
file order). Records with no time stay right after the record that preceded them in the file.

Input: one JSONL, JSON, CSV/TSV or plain-text log file. Output: the same format (JSON arrays
become JSONL, one object per line). Records that had no id get the id the tracer gave them in the
original file, so record ids in the live app match the original dataset.
"""
import argparse
import csv
import json
import os
import sys
import time

from .. import model


def read(path, mapping):
    rows = model._read_rows(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    cols = model.resolve_columns(rows, mapping)
    events = [model._events_from_row(r, cols, stem, i) for i, r in enumerate(rows, start=1)]
    return rows, cols, events


def order(path, rows, cols, events, how, pack, mapping, log):
    idx = list(range(len(rows)))
    if how == "file":
        return idx, "file order"
    times = {}
    if how == "estimate":
        from ..session import Session
        log(f"estimating times: analyzing {len(rows):,} records (pack {pack}) ...")
        t0 = time.time()
        s = Session()
        s.load(path, pack, mapping)
        times = dict(s.rec["_times"])
        log(f"  done in {time.time() - t0:.0f} s; {len(times):,} records dated")
    keys, last, dated = [], float("-inf"), 0
    for i, evs in enumerate(events):
        ts = []
        for e in evs:
            t = times.get(e.id)
            if t is None and e.time is not None:
                t = e.time.timestamp()
            if t is not None:
                ts.append(t)
        if ts:
            last, dated = min(ts), dated + 1
        keys.append((last, i))
    if not dated:
        return idx, "file order (no record has a time)"
    idx.sort(key=lambda i: keys[i])
    return idx, f"time order ({dated:,} of {len(rows):,} records dated{', estimated' if how == 'estimate' else ''})"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.tools.replay_feed", description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="the trace to replay (one file)")
    ap.add_argument("dst", help="the file to write (created or replaced)")
    ap.add_argument("--rate", type=float, default=500, help="records per second (default 500)")
    ap.add_argument("--start", type=int, default=0, help="write this many records at once before pacing")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many records")
    ap.add_argument("--pack", default="auto", help="pack used to estimate times (default auto)")
    ap.add_argument("--map", default="", help='column mapping as JSON, e.g. {"text": "body"}')
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fast", action="store_true", help="sort by the time field only (no analysis)")
    g.add_argument("--no-sort", action="store_true", help="keep the file order")
    ap.add_argument("--append", action="store_true", help="append to dst instead of replacing it")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr, flush=True))
    if os.path.isdir(a.src):
        ap.error("give one trace file, not a folder")
    if a.rate <= 0:
        ap.error("--rate must be positive")
    mapping = json.loads(a.map) if a.map else {}

    rows, cols, events = read(a.src, mapping)
    if not rows:
        ap.error("the file has no records")
    how = "file" if a.no_sort else "field" if a.fast else "estimate"
    idx, said = order(a.src, rows, cols, events, how, a.pack, mapping, log)
    if a.limit:
        idx = idx[:a.limit]

    ext = os.path.splitext(a.src)[1].lower()
    plain = ext in (".txt", ".log") and all(set(r) == {"line", "text"} for r in rows[:50])
    is_csv = ext in (".csv", ".tsv")
    # rows with no id field get the id the tracer gave them, so ids match the original
    add_id = "id" not in cols and not plain
    if add_id:
        for i in idx:
            if isinstance(rows[i], dict) and "id" not in rows[i] and events[i] and "#" not in events[i][0].id:
                rows[i] = {"id": events[i][0].id, **rows[i]}
    if os.path.splitext(a.dst)[1].lower() != (ext if is_csv or plain else ".jsonl") and not a.quiet:
        log(f"note: writing {'CSV' if is_csv else 'plain text' if plain else 'JSONL'}; name the output to match "
            f"(e.g. .{'csv' if is_csv else 'log' if plain else 'jsonl'}) so the app reads it the same way")

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    exists = a.append and os.path.exists(a.dst) and os.path.getsize(a.dst) > 0
    f = open(a.dst, "a" if a.append else "w", encoding="utf-8", newline="")
    writer = None
    if is_csv:
        fields = list(rows[idx[0]].keys()) if idx else []
        for i in idx:
            for k in rows[i]:
                if k not in fields:
                    fields.append(k)
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t" if ext == ".tsv" else ",", extrasaction="ignore")
        if not exists:
            writer.writeheader()
            f.flush()

    def put(r):
        if writer:
            writer.writerow(r)
        elif plain:
            f.write(str(r.get("text", "")).replace("\n", " ") + "\n")
        else:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log(f"replaying {len(idx):,} records into {a.dst} at {a.rate:g}/s, in {said}")
    t0, done, last_note = time.time(), 0, time.time()
    try:
        for i in idx[:a.start]:
            put(rows[i])
        done = min(a.start, len(idx))
        f.flush()
        start_t = time.time()
        while done < len(idx):
            due = a.start + int((time.time() - start_t) * a.rate) + 1
            n = min(len(idx), max(due, done + 1))
            for i in idx[done:n]:
                put(rows[i])
            done = n
            f.flush()
            if time.time() - last_note > 5:
                log(f"  {done:,} / {len(idx):,} records written")
                last_note = time.time()
            if done < len(idx):
                time.sleep(min(0.25, max(0.02, (done + 1 - a.start) / a.rate - (time.time() - start_t))))
    except KeyboardInterrupt:
        log(f"stopped after {done:,} records")
    finally:
        f.close()
    log(f"wrote {done:,} records in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

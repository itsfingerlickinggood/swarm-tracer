"""Event model and input adapters for agent traces.

Any CSV, JSONL or JSON file, or a folder of them, becomes a list of Event objects.

How a file is read:
- Fields are found by name (aliases below) per file, choosing the alias that most rows
  actually carry. Any role can be named explicitly with a mapping; dotted paths reach
  into nested JSON (for example meta.agent).
- A record with no text field keeps its other fields, as compact JSON, as its text, so
  any record can be searched and tagged.
- A record holding a list of chat messages (messages: [{role, content}, ...]) is
  expanded into one event per message, linked in order.
- A record with no id gets one from its file and line.
- A record that only points at another loaded record (for example a "save" event that
  references a revision that carries the text and time) is dropped as a duplicate.
- In a folder, files whose rows have neither a time nor a parent are treated as
  reference tables (for example per-page or per-user summaries) and are not loaded as
  events; the read report lists them.

LAST_REPORT holds how the last load read each file, for the app to show.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

csv.field_size_limit(sys.maxsize)

ALIASES = {
    "id": ["id", "event_id", "rev_id", "record_id", "msg_id", "message_id", "span_id", "run_id", "uuid", "guid", "key"],
    "text": ["text", "content", "body", "message", "msg", "payload", "output", "outputs", "completion", "response",
             "prompt", "input", "inputs", "value"],
    "kind": ["kind", "event_type", "type", "run_type", "role", "category"],
    "parent": ["parent_id", "parent_span_id", "parent_run_id", "reply_to", "in_reply_to", "parent", "diff_base",
               "related_event_id", "thread_parent", "caused_by"],
    "actor": ["agent_id", "agent_name", "actor", "actor_label", "label", "sender", "author", "from", "user",
              "username", "agent", "speaker", "participant", "source_agent",
              # network addresses are the weakest identity; used only when nothing else names the actor
              "ip16", "ip", "client_ip", "remote_addr"],
    "time": ["time_utc", "time_stamp", "timestamp", "created_at", "sent_at", "start_time", "time", "ts", "date",
             "datetime", "write_date", "created"],
    "tool": ["tool", "tool_name", "function", "function_name"],
    "channel": ["channel", "page_key", "page_id", "page", "thread_id", "thread", "conversation_id", "conversation",
                "room", "room_id", "topic", "session_id", "trace_id", "issue", "repo", "board"],
    "ref": ["revision_ref", "ref", "ref_id", "record_ref", "target_id"],
}
TEXT_FIELDS_TO_SKIP_IN_FALLBACK = {"hunks", "source_refs", "body_sha256"}
# roles read through a chain of fields, record by record: the first non-empty wins
CHAIN_ROLES = {"actor", "parent", "channel", "time", "kind"}
WEAK_ACTOR_FIELDS = {"ip16", "ip", "client_ip", "remote_addr"}

LAST_REPORT = {"files": [], "skipped_files": [], "dropped_pointer_records": 0}


@dataclass
class Event:
    id: str
    text: str
    kind: str = ""
    parent: Optional[str] = None
    actor: Optional[str] = None
    time: Optional[dt.datetime] = None
    tool: Optional[str] = None
    channel: Optional[str] = None
    ref: Optional[str] = None
    text_from_fields: bool = False
    raw: dict = field(default_factory=dict, repr=False)


def parse_time(s):
    if s is None or s == "" or isinstance(s, (list, dict, bool)):
        return None
    if isinstance(s, (int, float)):
        v = float(s)
        if v > 1e12:  # milliseconds
            v /= 1000
        try:
            return dt.datetime.fromtimestamp(v, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(s).strip()
    if re.fullmatch(r"\d{13}", s):
        return dt.datetime.fromtimestamp(int(s) / 1000, dt.timezone.utc)
    if re.fullmatch(r"\d{10}(\.\d+)?", s):
        return dt.datetime.fromtimestamp(float(s), dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def get_path(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _scalar(v):
    """Lists keep their first non-empty element; dicts become compact JSON."""
    if isinstance(v, list):
        v = next((x for x in v if x not in (None, "", [])), None)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)[:2000]
    return v


def resolve_columns(rows, mapping):
    """{role: [fields]} for this file. An explicit mapping gives one field. Otherwise, for
    chain roles, every alias some rows carry, in priority order; for id and text, the first
    alias at least half the rows carry, else the best covered. The sample is spread over
    the whole file so a field used only by later rows is still seen."""
    step = max(1, len(rows) // 4000)
    sample = [r for r in rows[::step] if isinstance(r, dict)]
    n = max(1, len(sample))
    out = {}
    for role, aliases in ALIASES.items():
        if role in mapping and mapping[role]:
            out[role] = [mapping[role]]
            continue
        cover = [(a, sum(1 for r in sample if r.get(a) not in (None, "", []))) for a in aliases]
        if role in CHAIN_ROLES:
            # chains take any field some rows use, even rarely (a handful of reverts may be the
            # only rows with a parent link), so presence is checked on every row
            present = [a for a in aliases if any(isinstance(r, dict) and r.get(a) not in (None, "", []) for r in rows)]
        else:
            present = [a for a, c in cover if c >= max(1, 0.01 * n)]
        if not present:
            continue
        if role in CHAIN_ROLES:
            out[role] = present
        else:
            first = next((a for a, c in cover if c >= 0.5 * n), None)
            out[role] = [first or max(cover, key=lambda x: x[1])[0]]
    # id and text fields are not reused by other roles
    taken = {f for r in ("id", "text") for f in out.get(r, [])}
    for role in list(out):
        if role not in ("id", "text") and role not in mapping:
            out[role] = [f for f in out[role] if f not in taken]
            if not out[role]:
                del out[role]
    return out


def _fallback_text(row, cols):
    keep = {k: v for k, v in row.items() if k not in TEXT_FIELDS_TO_SKIP_IN_FALLBACK and k != cols.get("id")
            and v not in (None, "", [], {})}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True)[:20000]


def _events_from_row(row, cols, stem, line):
    def g(role):
        for f in cols.get(role, []):
            v = _scalar(get_path(row, f))
            if v not in (None, "", []):
                if role == "actor" and f in WEAK_ACTOR_FIELDS:
                    return f"ip {v}"
                return v
        return None

    def graw(role):
        for f in cols.get(role, []):
            v = get_path(row, f)
            if v not in (None, "", []):
                return v
        return None
    s = lambda v: None if v in (None, "") else str(v)
    rid = s(g("id")) or f"{stem}:{line}"
    msgs = row.get("messages") if isinstance(row, dict) else None
    if isinstance(msgs, list) and msgs and all(isinstance(m, dict) for m in msgs) and any("content" in m for m in msgs):
        out, prev = [], s(g("parent"))
        for i, m in enumerate(msgs):
            content = m.get("content")
            if isinstance(content, list):  # content parts
                content = " ".join(str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in content)
            mid = f"{rid}#{i}"
            out.append(Event(id=mid, text="" if content is None else str(content),
                             kind=str(m.get("role") or "message"), parent=prev,
                             actor=s(m.get("name") or m.get("role")), time=parse_time(m.get("timestamp") or g("time")),
                             tool=s((m.get("tool_calls") or [{}])[0].get("function", {}).get("name") if m.get("tool_calls") else None),
                             channel=s(g("channel")) or rid, raw={}))
            prev = mid
        return out
    text = g("text")
    fallback = text is None
    return [Event(
        id=rid,
        text=_fallback_text(row, cols) if fallback else str(text),
        kind=s(g("kind")) or stem,
        parent=s(g("parent")),
        actor=s(g("actor")),
        time=parse_time(graw("time")),
        tool=s(g("tool")),
        channel=s(g("channel")),
        ref=s(g("ref")),
        text_from_fields=fallback,
        raw={},
    )]


def _read_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv"):
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t" if ext == ".tsv" else ","))
    with open(path, encoding="utf-8") as f:
        head = f.read(2048)
        f.seek(0)
        if ext == ".json" or head.lstrip().startswith("["):
            data = json.load(f)
            if isinstance(data, dict):  # {"data": [...]} or {"events": [...]}
                lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
                data = max(lists, key=len) if lists else [data]
            return [r for r in data if isinstance(r, dict)]
        rows, plain = [], []
        for n, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    plain.append({"line": n, "text": line})
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    plain.append({"line": n, "text": line})
        # a plain text log (.txt or .log): when most lines are not JSON objects, each line is one record
        if ext in (".txt", ".log") and len(plain) > len(rows):
            return plain + [{"line": 0, "text": json.dumps(r, ensure_ascii=False)} for r in rows]
        return rows


def load_file(path, mapping=None):
    rows = _read_rows(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    cols = resolve_columns(rows, mapping or {})
    events = []
    for i, r in enumerate(rows, start=1):
        events.extend(_events_from_row(r, cols, stem, i))
    info = {"file": os.path.basename(path), "rows": len(rows), "events": len(events), "fields": cols,
            "text_from_fields": sum(1 for e in events if e.text_from_fields),
            "with_time": sum(1 for e in events if e.time), "with_parent": sum(1 for e in events if e.parent)}
    return events, info


def _is_event_table(info):
    return info["rows"] and (info["with_time"] >= 0.5 * info["rows"] or info["with_parent"] >= 0.5 * info["rows"])


DATA_EXTS = (".jsonl", ".json", ".csv", ".tsv", ".txt", ".log")


def load(path_or_paths, mapping=None):
    """Load one file, a list of files, or a folder. Returns events in file order, files in
    the order given (folders: event tables only, sorted by name)."""
    mapping = mapping or {}
    LAST_REPORT.update({"files": [], "skipped_files": [], "dropped_pointer_records": 0})
    if isinstance(path_or_paths, (list, tuple)):
        paths, from_folder = list(path_or_paths), False
    elif os.path.isdir(path_or_paths):
        paths = sorted(os.path.join(path_or_paths, f) for f in os.listdir(path_or_paths)
                       if os.path.splitext(f)[1].lower() in DATA_EXTS and not f.startswith("."))
        from_folder = True
    else:
        paths, from_folder = [path_or_paths], False
    read = [load_file(p, mapping) for p in paths]
    # in a folder, files whose rows have no time and no parent are reference tables, set aside, but
    # only when some file does look like an event log; a folder of plain logs is kept whole
    tables = [_is_event_table(info) for _, info in read]
    loaded = []
    for (evs, info), is_table in zip(read, tables):
        if from_folder and len(paths) > 1 and any(tables) and not is_table:
            LAST_REPORT["skipped_files"].append({**info, "reason": "reference table: rows have no time and no parent"})
            continue
        loaded.append((evs, info))
    # ids must be unique across files
    seen, events = set(), []
    for evs, info in loaded:
        clash = any(e.id in seen for e in evs)
        stem = os.path.splitext(info["file"])[0]
        for e in evs:
            if clash:
                e.id = f"{stem}:{e.id}"
            seen.add(e.id)
        events.extend(evs)
        LAST_REPORT["files"].append(info)
    # drop records that only point at another loaded record that carries the content
    by_id = {e.id: e for e in events}
    kept = []
    for e in events:
        tgt = by_id.get(e.ref) if e.ref else None
        if tgt is not None and tgt is not e and e.text_from_fields and not tgt.text_from_fields:
            LAST_REPORT["dropped_pointer_records"] += 1
            continue
        kept.append(e)
    return kept

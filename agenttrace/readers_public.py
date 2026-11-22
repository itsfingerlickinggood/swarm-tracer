"""Readers for two openly licensed public datasets (both MIT), read from the JSON Lines that
`python3 -m agenttrace.tools.external convert <name>` writes from their Parquet tables, columns unchanged.

  salt_collusion  SALT agent-collusion (Shi, Zhang and Yang, 2026, arXiv:2609.24967). One row is one episode of two
                  agents, alice and bob. Its `communication` column lists the messages they exchanged, each with a
                  sender, a receiver and the text. Every message becomes one record addressed to its receiver, so
                  the tool counts it as a logged direct message. The verdicts, rewards and the `collusion` label are
                  in the same row and are NOT read: they are the answer the tool is scored against
                  (agenttrace/external_eval.py reads them, the reader does not).
  moltbook        Moltbook Observatory Archive (Gautam and Riegler, 2026). One row is a post or a comment on Moltbook,
                  a social network whose accounts are AI agents. A thread (a post and its comments) is the place;
                  a comment's parent is the comment or post it answers, and it is addressed to that record's author
                  when the author's record is in the same file (the logged reply).

Each reader returns flat rows with the tool's fixed fields (id, text, kind, parent, actor, time, tool, channel, to),
like the readers in readers.py and readers_ext.py. Nothing is invented: SALT episodes have no times, so SALT records
have none (step_clock() adds an order-only clock when a measurement needs one, and says so).

The files are data. Nothing in them is run.
"""
import datetime as dt
import json
import re

LIMIT = 20000                 # characters of text kept per record (the other readers keep the same)
STEP_SECONDS = 60             # the order-only clock: one record = 60 s from 2000-01-01 (as readers_ext.clocked)
STEP_BASE = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

FORMATS = {
    "salt_collusion": "SALT agent-collusion episodes (two agents, logged messages)",
    "moltbook": "Moltbook Observatory posts and comments",
}
SOURCE_FIELDS = {
    "salt_collusion": {"id": ["run_id, episode_index and communication[].event_id"], "text": ["communication[].content"],
                       "kind": ["message"], "parent": ["the previous message of the episode"],
                       "actor": ["communication[].sender (with the run, when a file holds several runs)"], "time": [],
                       "tool": [], "channel": ["run_id and episode_index"], "to": ["communication[].receiver"]},
    "moltbook": {"id": ["id"], "text": ["title and content (posts)", "content (comments)"], "kind": ["post / comment"],
                 "parent": ["parent_id, else post_id"], "actor": ["agent_name, else agent_id"], "time": ["created_at"],
                 "tool": [], "channel": ["submolt and the thread's post id"],
                 "to": ["the author of the parent record, when it is in the same file"]},
}


def _s(v):
    return None if v in (None, "", [], {}) else str(v)


# ------------------------------------------------------------------ SALT agent-collusion

def _is_salt(r):
    return "run_id" in r and "episode_index" in r and "communication" in r and isinstance(r["communication"], (list, str, type(None)))


def _messages(v):
    if isinstance(v, str) and v[:1] == "[":
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [m for m in v if isinstance(m, dict)] if isinstance(v, list) else []


def salt_channel(run, episode_index):
    return f"{run}/e{int(episode_index):02d}"


def read_salt(rows, stem):
    """One record per delivered message, in the recorded order. In a file with several runs the two agents of each
    run are different agents, so the actor carries the run: alice@<run_id>."""
    runs = {str(r.get("run_id")) for r in rows if _is_salt(r)}
    out = []
    for r in rows:
        if not _is_salt(r):
            continue
        run = str(r.get("run_id"))
        try:
            chan = salt_channel(run, r.get("episode_index"))
        except (TypeError, ValueError):
            continue
        who = (lambda a: f"{a}@{run}") if len(runs) > 1 else (lambda a: a)
        prev = None
        for i, m in enumerate(_messages(r.get("communication"))):
            sender, receiver = _s(m.get("sender")), _s(m.get("receiver"))
            if not sender:
                continue
            eid = m.get("event_id")
            rid = f"{chan}/m{eid if eid is not None else i}"
            out.append({"id": rid, "text": (_s(m.get("content")) or "")[:LIMIT], "kind": "message", "parent": prev,
                        "actor": who(sender), "time": None, "tool": None, "channel": chan,
                        "to": who(receiver) if receiver and receiver != sender else None})
            prev = rid
    return out


def step_clock(rows, step=STEP_SECONDS):
    """A copy of flat rows where every row gets a time from its position: one record = `step` seconds from
    2000-01-01. For traces that log order but no times (the tool's replay and alarms need times). The year 2000 marks
    it as not a real time; every result that uses it is labelled 'step clock'."""
    return [dict(r, time=(STEP_BASE + dt.timedelta(seconds=i * step)).isoformat()) for i, r in enumerate(rows)]


# ------------------------------------------------------------------ Moltbook Observatory

_TS = re.compile(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?\s*(Z|[+-]\d\d(?::?\d\d)?)?$")


def _time(v):
    """'2026-02-13 00:51:57.984+00' (how DuckDB prints a timestamp) -> ISO text every Python 3.9 parses."""
    if v in (None, ""):
        return None
    m = _TS.match(str(v).strip())
    if not m:
        return _s(v)
    day, clock, frac, zone = m.groups()
    zone = "+00:00" if zone in (None, "Z") else zone if ":" in zone else zone[:3] + ":" + (zone[3:] or "00")
    return f"{day}T{clock}.{(frac or '')[:6].ljust(6, '0')}{zone}"


def _is_moltbook(r):
    if "agent_name" not in r or "created_at" not in r:
        return False
    return ("submolt" in r and "title" in r) or ("post_id" in r and "parent_id" in r)


def _is_comment(r):
    return r.get("post_id") not in (None, "")


def read_moltbook(rows, stem):
    rows = [r for r in rows if _is_moltbook(r) and r.get("id") not in (None, "")]
    author = {str(r["id"]): _s(r.get("agent_name")) or _s(r.get("agent_id")) for r in rows}
    sub = {str(r["id"]): _s(r.get("submolt")) for r in rows if not _is_comment(r)}
    out = []
    for r in rows:
        rid = str(r["id"])
        actor = author[rid]
        if _is_comment(r):
            thread = str(r["post_id"])
            parent = _s(r.get("parent_id")) or thread
            to = author.get(parent)
            text, kind = _s(r.get("content")) or "", "comment"
            where = sub.get(thread) or _s(r.get("submolt"))
        else:
            thread, parent, to, kind = rid, None, None, "post"
            text = "\n".join(x for x in (_s(r.get("title")), _s(r.get("content")), _s(r.get("url"))) if x)
            where = sub.get(rid)
        out.append({"id": rid, "text": text[:LIMIT], "kind": kind, "parent": parent, "actor": actor,
                    "time": _time(r.get("created_at")), "tool": None,
                    "channel": f"{where}/{thread}" if where else thread,
                    "to": to if to and to != actor else None})
    return out


# readers.py puts these in front of its own detectors (the shapes are specific to the two datasets)
DETECTORS = [("salt_collusion", _is_salt, read_salt), ("moltbook", _is_moltbook, read_moltbook)]

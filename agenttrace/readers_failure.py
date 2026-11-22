"""Readers for two public datasets of failed multi-agent runs, each with someone else's labels.

  who_and_when   Who&When (Zhang et al., ICML 2025; MIT). One JSON file per failed run: `history` (a list of
                 messages) plus `mistake_agent`, `mistake_step`, `mistake_reason`. Two layouts:
                   Algorithm-Generated  AG2 group chats: each message has name (the agent), role, content
                   Hand-Crafted         Magentic-One: each message has role and content, and the role names the
                                        speaker and, for an instruction, the recipient: "Orchestrator (-> WebSurfer)"
  mast           MAST-Data / MAD (Cemri, Pan, Yang et al., NeurIPS 2025; CC BY 4.0). One row per run; the run is one
                 block of log text (`trace.trajectory`) in a different layout for each of seven frameworks, with 14
                 failure-mode labels (`mast_annotation`, made by an LLM judge).

Each reader returns flat rows with the tool's fixed fields (id, text, kind, parent, actor, time, tool, channel, to),
so the rest of the pipeline reads them like any other trace. A record id is "<run>:<step>", steps counted from 0 in
the order of the log, so a Who&When `mistake_step` is the step of the same number.

Nothing is invented. A recipient is set only where the log names one; a time only where the log prints one.
`clocked()` adds an order-only clock (one step = 60 s from 2000-01-01) for traces that have no times, because the
tool's replay and alarms need times; every use of it is labelled "step clock" in the reports.

The files are data. Nothing in them is run: the dict-style AG2 logs are read with ast.literal_eval, which builds
literals and calls nothing.

    python3 -m agenttrace.readers_failure who_and_when DIR --out OUT [--clock step]   # one .jsonl per subset + truth
    python3 -m agenttrace.readers_failure mast FILE.json --out OUT [--limit N]
"""
import argparse
import ast
import datetime as dt
import json
import os
import re
import sys

LIMIT = 20000           # characters of text kept per record (the other readers keep the same)
STEP_SECONDS = 60
STEP_BASE = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

FORMATS = {
    "who_and_when": "Who&When / Magentic-One transcript (the role names the recipient)",
    "mast": "MAST-Data traces (seven framework log layouts)",
}
SOURCE_FIELDS = {
    "who_and_when": {"id": ["position in history"], "text": ["content"], "kind": ["the note in the role: thought, instruction"],
                     "parent": ["the previous message"], "actor": ["name", "the speaker named in role"], "time": [],
                     "tool": [], "channel": ["file"], "to": ["the recipient named in role: 'Orchestrator (-> WebSurfer)'"]},
    "mast": {"id": ["trace.key, trace_id and the position of the turn"], "text": ["the turn's text in trace.trajectory"],
             "kind": ["the turn's header"], "parent": ["the previous turn of the run"],
             "actor": ["the speaker named in the turn's header"], "time": ["the header's timestamp (ChatDev, MetaGPT, OpenManus)"],
             "tool": ["the tool named in the turn (OpenManus)"], "channel": ["the run"],
             "to": ["A<->B (ChatDev)", "A->B (HyperAgent)", "Message to / Reply from (AppWorld)"]},
}
MAST_MODES = ("1.1", "1.2", "1.3", "1.4", "1.5", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "3.1", "3.2", "3.3")


def _row(run, i, actor, text, kind, to=None, time=None, tool=None):
    actor = actor or None
    return {"id": f"{run}:{i}", "text": (text or "")[:LIMIT], "kind": kind or "message",
            "parent": f"{run}:{i - 1}" if i else None, "actor": actor, "time": time, "tool": tool, "channel": run,
            "to": to if to and to != actor else None}


def clocked(rows, step=STEP_SECONDS):
    """A copy of the rows where a row without a time gets one from its position (the step clock). Rows that have a
    time keep it; a run with some times and some gaps is left as it is."""
    if any(r.get("time") for r in rows):
        return [dict(r) for r in rows]
    return [dict(r, time=(STEP_BASE + dt.timedelta(seconds=i * step)).isoformat()) for i, r in enumerate(rows)]


def withheld(rows):
    """A copy with every logged recipient removed: what the tool must then infer for itself."""
    return [dict(r, to=None) for r in rows]


def logged_messages(rows):
    """[(step id, sender, recipient)] for the records the log itself addresses to another agent."""
    return [(r["id"], r["actor"], r["to"]) for r in rows if r.get("to") and r.get("actor")]


# ------------------------------------------------------------------ Who&When

ROLE = re.compile(r"^\s*(?P<actor>[A-Za-z_][\w .-]*?)\s*\(\s*(?:->\s*(?P<to>[A-Za-z_][\w .-]*?)|(?P<note>[^()]*?))\s*\)\s*$")
CHAT_ROLES = {"user", "assistant", "system", "tool", "function", "human", "ai", "model"}


def parse_role(role):
    """'Orchestrator (-> WebSurfer)' -> ('Orchestrator', 'WebSurfer', 'instruction');
    'Orchestrator (thought)' -> ('Orchestrator', None, 'thought'); 'WebSurfer' -> ('WebSurfer', None, 'message')."""
    role = "" if role is None else str(role)
    m = ROLE.match(role)
    if not m:
        return role.strip() or None, None, "message"
    if m.group("to"):
        return m.group("actor"), m.group("to"), "instruction"
    return m.group("actor"), None, (m.group("note") or "note").strip().replace(" ", "_") or "note"


def who_and_when_rows(doc, run):
    """Rows of one Who&When run (the parsed JSON file). Step i is history[i]."""
    out = []
    for i, m in enumerate(doc.get("history") or []):
        if not isinstance(m, dict):
            m = {"content": m}
        content = m.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        if m.get("name"):                      # AG2 group chat: the name is the agent, the role is user / assistant
            out.append(_row(run, i, str(m["name"]), text, str(m.get("role") or "message")))
        else:                                  # Magentic-One: the role is the speaker, and sometimes the recipient
            actor, to, kind = parse_role(m.get("role"))
            out.append(_row(run, i, actor, text, kind, to=to))
    return out


def who_and_when_truth(doc, rows=None):
    """The dataset's own label for one run: which agent made the decisive mistake, at which step, and why."""
    try:
        step = int(str(doc.get("mistake_step")).strip())
    except (TypeError, ValueError):
        step = None
    agent = doc.get("mistake_agent")
    out = {"mistake_agent": None if agent is None else str(agent).strip(), "mistake_step": step,
           "mistake_reason": doc.get("mistake_reason"), "question_id": doc.get("question_ID")}
    if rows is not None:
        out["steps"] = len(rows)
        out["agents"] = sorted({r["actor"] for r in rows if r["actor"]})
        out["step_actor"] = rows[step]["actor"] if step is not None and 0 <= step < len(rows) else None
    return out


def who_and_when_files(root):
    """[(subset, run, path)] for a Who&When folder (the repository's `Who&When` folder, or one subset of it)."""
    out = []
    subs = [d for d in ("Algorithm-Generated", "Hand-Crafted") if os.path.isdir(os.path.join(root, d))]
    for sub in subs or [""]:
        d = os.path.join(root, sub)
        names = [f for f in os.listdir(d) if f.endswith(".json") and os.path.isfile(os.path.join(d, f))]
        for f in sorted(names, key=lambda n: (not n[:-5].isdigit(), int(n[:-5]) if n[:-5].isdigit() else 0, n)):
            tag = {"Algorithm-Generated": "ag", "Hand-Crafted": "hc"}.get(sub, "run")
            out.append((sub or os.path.basename(os.path.normpath(root)), f"{tag}{f[:-5]}", os.path.join(d, f)))
    return out


def load_who_and_when(root):
    """Every run under root: [{subset, run, path, rows, truth}]. Files that are not a run are skipped."""
    out = []
    for sub, run, path in who_and_when_files(root):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict) or not isinstance(doc.get("history"), list):
            continue
        rows = who_and_when_rows(doc, run)
        out.append({"subset": sub, "run": run, "path": path, "rows": rows, "truth": who_and_when_truth(doc, rows)})
    return out


def _is_who_and_when(r):
    """A Magentic-One history message as Who&When stores it: only role and content, and the role is a speaker
    (not user / assistant), optionally with '(-> recipient)' or '(thought)'."""
    role = r.get("role")
    if not isinstance(role, str) or "content" not in r or set(r) - {"role", "content"}:
        return False
    return role.strip().lower() not in CHAT_ROLES and bool(re.match(r"^[A-Za-z_][\w .-]{0,40}(\s*\([^()]{1,60}\))?\s*$", role))


def read_who_and_when(rows, stem):
    return who_and_when_rows({"history": rows}, stem)


# ------------------------------------------------------------------ MAST-Data: one parser per framework

def _blocks(text, rx):
    """[(match, body)] : the text cut at every match of rx; body runs to the next match."""
    ms = list(rx.finditer(text))
    return [(m, text[m.end():(ms[k + 1].start() if k + 1 < len(ms) else len(text))]) for k, m in enumerate(ms)]


CD_LINE = re.compile(r"^\[(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) INFO\] ?(.*)$", re.M)
CD_TURN = re.compile(r"^([A-Z][\w ]{1,40}?): \*\*(.+?)<->(.+?) on : (\w+), turn (\d+)\*\*")
CD_START = re.compile(r"^([A-Z][\w ]{1,40}?): \*\*\[Start Chat\]\*\*")


def _chatdev_time(m):
    y, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    day, month = (a, b) if b <= 12 else (b, a)          # ChatDev prints year-day-month
    try:
        return dt.datetime(y, month, day, int(m.group(4)), int(m.group(5)), int(m.group(6)), tzinfo=dt.timezone.utc).isoformat()
    except ValueError:
        return None


def _chatdev(text, run):
    """A speaker line '[time INFO] Programmer: **Programmer<->Code Reviewer on : CodeReview, turn 0**' and the text
    under it is one message from the speaker to the other of the pair. '**[Start Chat]**' opens a phase. Other log
    lines (HTTP requests, usage counters, phase bookkeeping) are not agent messages and are left out."""
    out, skipped = [], 0
    for m, body in _blocks(text, CD_LINE):
        head = m.group(7)
        t = CD_TURN.match(head)
        if t:
            speaker, a, b = t.group(1).strip(), t.group(2).strip(), t.group(3).strip()
            to = b if speaker == a else a if speaker == b else None
            out.append(_row(run, len(out), speaker, f"[{t.group(4)}, turn {t.group(5)}] {body.strip()}", "chat",
                            to=to, time=_chatdev_time(m)))
            continue
        s = CD_START.match(head)
        if s:
            out.append(_row(run, len(out), s.group(1).strip(), body.strip(), "start_chat", time=_chatdev_time(m)))
        else:
            skipped += 1
    return out, skipped


MG_HEAD = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (?:FROM: (.+?) TO: (.+?)|NEW MESSAGES:)[ \t]*$", re.M)
MG_SPEAKER = re.compile(r"\s*([A-Za-z_]\w{0,40}):[ \t]?")
MG_RULE = re.compile(r"\n-{20,}\s*$")


def _metagpt(text, run):
    """'[time] FROM: Human TO: {'<all>'}' is the task, sent to everyone (no single recipient).
    '[time] NEW MESSAGES:' is followed by 'Speaker: text'."""
    out, skipped = [], 0
    for m, body in _blocks(text, MG_HEAD):
        t = m.group(1).replace(" ", "T") + "+00:00"
        body = MG_RULE.sub("", body.rstrip())
        if m.group(2):
            content = body.split("CONTENT:", 1)[-1].strip()
            out.append(_row(run, len(out), m.group(2).strip(), content, "requirement", time=t))
            continue
        s = MG_SPEAKER.match(body)
        if s:
            out.append(_row(run, len(out), s.group(1), body[s.end():].strip(), "message", time=t))
        else:
            skipped += 1
    return out, skipped


OM_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?) \| (\w+) +\| ([\w.]+):(\w+):(\d+) - ", re.M)
OM_AGENT = re.compile(r"(\w+)'s thoughts|(\w+) selected \d+ tools")
OM_TOOL = re.compile(r"Activating tool: '([^']+)'|Tool '([^']+)' completed")


def _openmanus(text, run):
    """One record per log line (with the lines under it). The agent is the one the line names ("Manus's thoughts");
    planning lines belong to the planning flow; token counters are left out."""
    out, skipped, agent = [], 0, "Manus"
    for m, body in _blocks(text, OM_LINE):
        module, func = m.group(3), m.group(4)
        if module.startswith("app.llm"):
            skipped += 1
            continue
        a = OM_AGENT.search(body[:200])
        if a:
            agent = a.group(1) or a.group(2)
        tl = OM_TOOL.search(body[:300])
        actor = agent if module.startswith("app.agent") else "PlanningFlow" if module.startswith("app.flow") else \
            "user" if module == "__main__" else module.split(".")[1] if "." in module else module
        out.append(_row(run, len(out), actor, body.strip(), func, time=m.group(1).replace(" ", "T") + "+00:00",
                        tool=(tl.group(1) or tl.group(2)) if tl else None))
    return out, skipped


MA_HEAD = re.compile(r"^-{10} (.+?) -{10}[ \t]*$", re.M)
MA_END = re.compile(r"^(?:SCENARIO\.PY COMPLETE|RUN\.SH COMPLETE)", re.M)


def _magentic(text, run):
    """'---------- WebSurfer ----------' opens a turn. The log names no recipient and prints no times."""
    out = []
    for m, body in _blocks(text, MA_HEAD):
        end = MA_END.search(body)
        out.append(_row(run, len(out), m.group(1).strip(), (body[:end.start()] if end else body).strip(), "message"))
    return out, 0


AG_SPLIT = re.compile(r"(?<=\})\s+(?=\{'content': )")
AG_TAIL = re.compile(r"'role': '([^']*)', 'name': '([^']*)'\}\s*$")
AG_YAML = re.compile(r"^[ \t]*content:[ \t]*$", re.M)
AG_FIELD = re.compile(r"^[ \t]*(role|name):[ \t]*(\S.*?)[ \t]*$", re.M)


def _ag2(text, run):
    """Two layouts: Python dict text, one per message ({'content': [lines], 'role': ..., 'name': ...}), or indented
    'content: / role: / name:' blocks under 'trajectory:'. The name is the agent. No recipient, no times."""
    out, skipped = [], 0
    if text.lstrip().startswith("{'content':"):
        for piece in AG_SPLIT.split(text.strip()):
            d = None
            try:
                d = ast.literal_eval(piece)          # literals only: nothing in the data is called
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                pass
            if isinstance(d, dict) and "content" in d:
                c = d.get("content")
                body = "\n".join(str(x) for x in c) if isinstance(c, list) else str(c)
                out.append(_row(run, len(out), str(d.get("name") or d.get("role") or ""), body, str(d.get("role") or "message")))
                continue
            t = AG_TAIL.search(piece)
            if t:
                out.append(_row(run, len(out), t.group(2), piece[:t.start()], t.group(1) or "message"))
            else:
                skipped += 1
        return out, skipped
    start = text.find("trajectory:")
    for m, body in _blocks(text[start if start >= 0 else 0:], AG_YAML):
        fields = {k: v for k, v in AG_FIELD.findall(body[-400:])}
        cut = AG_FIELD.search(body, max(0, len(body) - 400))
        content = body[:cut.start()] if cut else body
        if not fields.get("name"):
            skipped += 1
            continue
        lines = [ln.strip() for ln in content.split("\n")]
        out.append(_row(run, len(out), fields["name"], "\n".join(lines).strip(), fields.get("role") or "message"))
    return out, skipped


AW_HEAD = re.compile(r"^( *)(Response from (\w+) Agent|Message to (\w+) Agent|Reply from (\w+) Agent to (\w+)|"
                     r"Entering (\w+) Agent message loop|Exiting (\w+) Agent message loop|Code Execution Output|"
                     r"Response from send_message API)[ \t]*$", re.M)


def _appworld(text, run):
    """The supervisor's turns and each app agent's loop. In a loop the first 'Message to X Agent' is the supervisor's
    message to X; later ones are the results of X's own calls. 'Reply from X Agent to Supervisor' is X's answer."""
    out, skipped = [], 0
    name = lambda s: "Supervisor" if s.lower() == "supervisor" else s.lower()
    first_in_loop, last = False, "Supervisor"
    for m, body in _blocks(text, AW_HEAD):
        head, body = m.group(2), body.strip()
        n = len(out)
        if head.startswith("Entering"):
            first_in_loop = True
            skipped += 1
        elif head.startswith("Exiting") or head.startswith("Response from send_message"):
            skipped += 1            # the loop's end, and a second copy of the reply
        elif m.group(3):
            last = name(m.group(3))
            out.append(_row(run, n, last, body, "response"))
        elif m.group(4):
            who = name(m.group(4))
            if m.group(1) and first_in_loop and who != "Supervisor":
                out.append(_row(run, n, "Supervisor", body, "message", to=who))
            else:
                out.append(_row(run, n, who, body, "tool_output"))
            first_in_loop = False
        elif m.group(5):
            out.append(_row(run, n, name(m.group(5)), body, "reply", to=name(m.group(6))))
        else:
            out.append(_row(run, n, last, body, "tool_output"))    # credited to the agent whose code ran
    return out, skipped


HA_LINE = re.compile(r"^[ \t]*HyperAgent_\S+ - INFO - ", re.M)
HA_RESP = re.compile(r"(Planner|Inner-(\w+)-Assistant)'s Response: ?")
HA_MSG = re.compile(r"(\w+)->(\w+): ?")


def _hyperagent(text, run):
    """'Planner's Response:' and 'Inner-Navigator-Assistant's Response:' are an agent's own turns (the inner
    assistant is counted as that agent: Navigator); 'Navigator->Planner:' is a message with its recipient."""
    out, skipped = [], 0
    for m, body in _blocks(text, HA_LINE):
        r = HA_RESP.match(body)
        if r:
            out.append(_row(run, len(out), r.group(2) or "Planner", body[r.end():].strip(), "response"))
            continue
        g = HA_MSG.match(body)
        if g:
            out.append(_row(run, len(out), g.group(1), body[g.end():].strip(), "message", to=g.group(2)))
        else:
            skipped += 1
    return out, skipped


MAST_PARSERS = {"ChatDev": _chatdev, "MetaGPT": _metagpt, "OpenManus": _openmanus, "Magentic": _magentic,
                "AG2": _ag2, "AppWorld": _appworld, "HyperAgent": _hyperagent,
                "GAIA": _magentic}      # the 19-run human-labelled file names its Magentic-One runs by their benchmark
# which frameworks print what
MAST_TIMED = ("ChatDev", "MetaGPT", "OpenManus")
MAST_ADDRESSED = ("ChatDev", "AppWorld", "HyperAgent")


def _trajectory(row):
    """The run's log text: trace.trajectory in the full file, trace itself (a string) in the human-labelled file."""
    tr = row.get("trace")
    if isinstance(tr, dict):
        tr = tr.get("trajectory")
    return tr if isinstance(tr, str) else None


def mast_run_id(row, n=0):
    key = (row.get("trace") or {}).get("key") if isinstance(row.get("trace"), dict) else None
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(key or row.get("mas_name") or "run")).strip("_")
    tid = row.get("trace_id")
    return f"{slug}_{tid if tid is not None else n}"


def mast_rows(row, run=None):
    """(rows, skipped log blocks) for one MAST-Data row. A framework with no parser, or a run whose text has none of
    its framework's headers, gives no rows."""
    text = _trajectory(row)
    parser = MAST_PARSERS.get(str(row.get("mas_name")))
    if text is None or parser is None:
        return [], 0
    return parser(text, run or mast_run_id(row))


def mast_labels(row):
    """{mode: 0 / 1 / None} for the 14 MAST failure modes (None: the dataset has no label for it)."""
    a = row.get("mast_annotation") or {}
    return {k: (None if a.get(k) is None else int(bool(a.get(k)))) for k in MAST_MODES}


def load_mast(path, limit=None):
    """Every run in a MAST-Data JSON file: [{run, mas, llm, benchmark, rows, skipped, labels, chars}].
    Run ids are made unique (two configurations can share a key and a trace_id)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out, seen = [], {}
    for n, row in enumerate(data if limit is None else data[:limit]):
        if not isinstance(row, dict):
            continue
        run = mast_run_id(row, n)
        seen[run] = seen.get(run, 0) + 1
        if seen[run] > 1:
            run = f"{run}_{seen[run]}"
        rows, skipped = mast_rows(row, run)
        out.append({"run": run, "mas": str(row.get("mas_name")), "llm": str(row.get("llm_name")),
                    "benchmark": str(row.get("benchmark_name")), "rows": rows, "skipped": skipped,
                    "labels": mast_labels(row), "chars": len(_trajectory(row) or "")})
    return out


def _is_mast(r):
    return "mas_name" in r and "trace_id" in r and _trajectory(r) is not None


def read_mast(rows, stem):
    out, seen = [], {}
    for n, row in enumerate(rows):
        run = mast_run_id(row, n)
        seen[run] = seen.get(run, 0) + 1
        out += mast_rows(row, run if seen[run] == 1 else f"{run}_{seen[run]}")[0]
    return out


# readers.py puts these in front of its own detectors (see the end of its detection section)
DETECTORS = [("mast", _is_mast, read_mast), ("who_and_when", _is_who_and_when, read_who_and_when)]


# ------------------------------------------------------------------ convert to JSON Lines

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert Who&When or MAST-Data to JSON Lines the tool reads, with the labels beside them.")
    ap.add_argument("dataset", choices=("who_and_when", "mast"))
    ap.add_argument("path", help="the Who&When folder, or a MAST-Data JSON file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clock", choices=("none", "step"), default="none",
                    help="step: give undated runs an order-only clock (60 s a step from 2000-01-01)")
    ap.add_argument("--limit", type=int, help="MAST-Data: only the first N runs")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    fix = clocked if a.clock == "step" else (lambda rows: rows)
    if a.dataset == "who_and_when":
        runs = load_who_and_when(a.path)
        for sub in sorted({r["subset"] for r in runs}):
            part = [r for r in runs if r["subset"] == sub]
            _write_jsonl(os.path.join(a.out, f"{sub}.jsonl"), [x for r in part for x in fix(r["rows"])])
            with open(os.path.join(a.out, f"{sub}.labels.json"), "w", encoding="utf-8") as f:
                json.dump({r["run"]: r["truth"] for r in part}, f, indent=1, ensure_ascii=False)
            print(f"{sub}: {len(part)} runs, {sum(len(r['rows']) for r in part)} records")
    else:
        runs = load_mast(a.path, a.limit)
        for mas in sorted({r["mas"] for r in runs}):
            part = [r for r in runs if r["mas"] == mas]
            _write_jsonl(os.path.join(a.out, f"{mas}.jsonl"), [x for r in part for x in fix(r["rows"])])
            with open(os.path.join(a.out, f"{mas}.labels.json"), "w", encoding="utf-8") as f:
                json.dump({r["run"]: r["labels"] for r in part}, f, indent=1)
            print(f"{mas}: {len(part)} runs, {sum(len(r['rows']) for r in part)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())

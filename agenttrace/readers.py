"""Readers for common agent-framework trace formats, and the pack builder.

model.load_file hands every file's rows to read(); when the rows have the shape of a known
format, they are turned into flat rows with fixed fields (id, text, kind, parent, actor, time,
tool, channel, to), so the rest of the pipeline sees one shape. Rows that match no format are
returned untouched and read by field name as before.

Formats, detected from the data's shape (not the file name):
  otel           OpenTelemetry spans (OTLP JSON resourceSpans/scopeSpans/spans, or flat spans with
                 traceId/spanId/parentSpanId and attributes), GenAI semantic conventions
                 (gen_ai.agent.name, gen_ai.operation.name, gen_ai.tool.name, gen_ai.prompt ...)
  openai_agents  OpenAI Agents SDK traces (spans with span_data of type agent / handoff /
                 function / generation / response / guardrail / custom)
  langsmith      LangSmith runs (run_type, inputs, outputs, parent_run_id, trace_id)
  langfuse       Langfuse observations (traceId, parentObservationId, type SPAN / GENERATION /
                 EVENT / AGENT / TOOL, startTime)
  autogen        AutoGen / AG2 message logs (sender + recipient, or source + type + content)
  crewai         CrewAI task / agent / tool logs (agent + task, tool usage, delegation to coworkers)
  mcp            MCP tool-call logs: JSON-RPC requests and responses, bare or wrapped
  chat           plain chat transcripts (role / name / content)

A record that is addressed to another agent (a handoff, a recipient, a delegation, a
transfer_to_<agent> tool) gets a "to" field; messages.py turns these into direct messages.

The pack builder (pack_suggest) loads a sample with the same detection and proposes a pack:
identity tokens, places, intents and which kinds are actions, each with counts and examples.
"""
import datetime as dt
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict

FORMATS = {
    "otel": "OpenTelemetry spans (GenAI conventions)",
    "openai_agents": "OpenAI Agents SDK trace",
    "langsmith": "LangSmith runs",
    "langfuse": "Langfuse observations",
    "autogen": "AutoGen / AG2 messages",
    "crewai": "CrewAI task log",
    "mcp": "MCP tool-call log (JSON-RPC)",
    "chat": "chat transcript",
}
GENERIC = "records read by field name"
# where each format's reader takes each field from (shown in the read report)
SOURCE_FIELDS = {
    "otel": {"id": ["spanId"], "text": ["gen_ai.prompt / input messages", "gen_ai.completion / output messages", "tool call arguments and result", "span events"],
             "kind": ["gen_ai.operation.name", "name"], "parent": ["parentSpanId"],
             "actor": ["gen_ai.agent.name of the span or the nearest agent span above it", "the caller, for invoke_agent spans", "service.name"],
             "time": ["startTimeUnixNano"], "tool": ["gen_ai.tool.name"], "channel": ["traceId"],
             "to": ["the invoked agent (invoke_agent)", "transfer_to_<agent> tools"]},
    "openai_agents": {"id": ["id"], "text": ["span_data input / output", "handoff from / to"], "kind": ["span_data.type"],
                      "parent": ["parent_id", "trace_id"], "actor": ["span_data.name of the enclosing agent span", "handoff from_agent"],
                      "time": ["started_at"], "tool": ["function span name"], "channel": ["trace_id"], "to": ["handoff to_agent"]},
    "langsmith": {"id": ["id"], "text": ["inputs", "outputs"], "kind": ["run_type"], "parent": ["parent_run_id"],
                  "actor": ["extra.metadata agent_name / langgraph_node, inherited down the run tree"], "time": ["start_time"],
                  "tool": ["name of tool runs"], "channel": ["trace_id"], "to": ["transfer_to_<agent> tools", "to / recipient in tool inputs"]},
    "langfuse": {"id": ["id"], "text": ["input", "output"], "kind": ["type"], "parent": ["parentObservationId"],
                 "actor": ["AGENT observation name or metadata.agent, inherited down the tree", "the caller, for nested AGENT observations"],
                 "time": ["startTime"], "tool": ["TOOL observation name"], "channel": ["traceId"],
                 "to": ["nested AGENT observations", "metadata.handoff_to", "transfer_to_<agent> tools"]},
    "autogen": {"id": ["id", "file line"], "text": ["message.content / content", "tool calls"], "kind": ["type"],
                "parent": ["the previous message"], "actor": ["sender", "source"], "time": ["timestamp", "created_at"],
                "tool": ["tool_calls function name"], "channel": ["chat_id", "file"], "to": ["recipient", "target (handoffs)"]},
    "crewai": {"id": ["id", "file line"], "text": ["task", "tool and tool_input", "output"], "kind": ["event"],
               "parent": ["first record of the same task"], "actor": ["agent"], "time": ["timestamp"], "tool": ["tool"],
               "channel": ["crew", "task"], "to": ["tool_input.coworker (delegation)", "delegated_to"]},
    "mcp": {"id": ["id", "file line"], "text": ["method, tool name and arguments", "result content"], "kind": ["method", "result / error"],
            "parent": ["the request with the same JSON-RPC id in the session"], "actor": ["client (requests)", "server (responses)"],
            "time": ["timestamp"], "tool": ["params.name of tools/call"], "channel": ["session"], "to": ["to / recipient in tool arguments"]},
    "chat": {"id": ["id", "file line"], "text": ["content"], "kind": ["role"], "parent": ["reply_to", "the previous message"],
             "actor": ["name", "role", "the calling agent, for tool messages"], "time": ["timestamp"], "tool": ["tool_calls", "name of tool messages"],
             "channel": ["conversation_id", "file"], "to": ["to", "recipient"]},
}
COLUMNS = {k: [k] for k in ("id", "text", "kind", "parent", "actor", "time", "tool", "channel", "to")}
TO_KEYS = ("to", "recipient", "receiver", "target_agent", "to_agent", "handoff_to", "recipient_name", "coworker", "addressee")
TRANSFER = re.compile(r"^(?:transfer|handoff|hand_off|delegate)_to_(\w+)$", re.I)


# ------------------------------------------------------------------ small helpers

def _iso(v):
    """A time as ISO text the loader understands: epoch seconds/ms/ns, ISO with any fraction."""
    if v in (None, "", [], {}):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{10,19}(\.\d+)?", v.strip())):
        x = float(v)
        while x > 1e11:  # ms, us, ns -> seconds
            x /= 1000
        try:
            return dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):  # [sec, ns] hrtime
        return _iso(v[0] + v[1] / 1e9)
    s = str(v).strip().replace("Z", "+00:00")
    m = re.match(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:
        frac = (m.group(2) or "")[:7].ljust(7, "0") if m.group(2) else ""
        return m.group(1).replace(" ", "T") + frac + (m.group(3) or "")
    return s


def _str(v):
    if v in (None, "", [], {}):
        return None
    return v if isinstance(v, str) else str(v)


def _text(v, limit=20000):
    """Readable text from whatever a framework stores as input or output."""
    if v in (None, "", [], {}):
        return ""
    if isinstance(v, str):
        return v[:limit]
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict) and ("role" in x or "type" in x) and ("content" in x or "text" in x or "parts" in x):
                who = x.get("name") or x.get("role") or ""
                body = _text(x.get("content") if "content" in x else x.get("text") if "text" in x else x.get("parts"))
                if x.get("tool_calls"):
                    body += " " + _text(x["tool_calls"])
                parts.append(f"{who}: {body}" if who and x.get("role") else body)
            elif isinstance(x, list):
                parts.append(_text(x))
            else:
                parts.append(_text(x))
        return "\n".join(p for p in parts if p)[:limit]
    if isinstance(v, dict):
        for k in ("messages", "content", "text", "output", "result", "message", "input", "query", "question",
                  "answer", "generations", "parts", "value"):
            if k in v and v[k] not in (None, "", [], {}):
                rest = {kk: vv for kk, vv in v.items() if kk != k and vv not in (None, "", [], {})}
                head = _text(v[k], limit)
                if isinstance(v[k], (str, list)) and rest and len(head) < 200 and k not in ("content", "text"):
                    head += " " + json.dumps(rest, ensure_ascii=False, sort_keys=True, default=str)[:400]
                return head[:limit]
        if "function" in v and isinstance(v["function"], dict):
            f = v["function"]
            return f"{f.get('name', '')}({_text(f.get('arguments'))})"
        if "name" in v and "arguments" in v:
            return f"{v['name']}({_text(v['arguments'])})"
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)[:limit]
    return str(v)[:limit]


def _args(v):
    """Tool arguments as compact JSON, so every argument (a path, a recipient) stays searchable."""
    v = _maybe_json(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)[:20000]
    return _text(v)


def _join(*parts):
    return " ".join(p for p in (_text(x) if not isinstance(x, str) else x for x in parts) if p).strip()


def _get(d, *paths):
    for p in paths:
        cur = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def _to_of(d):
    for k in TO_KEYS:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict):
            v = v.get("name") or v.get("id")
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, "", [], {}) and isinstance(v, (str, int)):
            return str(v)
    return None


def _otel_value(v):
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "intValue", "doubleValue", "boolValue", "bytesValue"):
        if k in v:
            return v[k]
    if "arrayValue" in v:
        return [_otel_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {x.get("key"): _otel_value(x.get("value")) for x in v["kvlistValue"].get("values", [])}
    return v


def _attrs(a):
    """OTLP attributes ([{key, value: {stringValue}}]) or a plain dict -> dict."""
    if isinstance(a, list):
        return {x.get("key"): _otel_value(x.get("value")) for x in a if isinstance(x, dict)}
    return dict(a) if isinstance(a, dict) else {}


def _maybe_json(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _share(rows, test, n=400):
    sample = rows[:: max(1, len(rows) // n)][:n]
    sample = [r for r in sample if isinstance(r, dict)]
    return sum(1 for r in sample if test(r)) / len(sample) if sample else 0.0


# ------------------------------------------------------------------ the span tree (agent context)

def _agent_tree(nodes):
    """nodes: dicts with id, parent, own (the node's own agent or None), delegate (bool: an agent
    being invoked by its caller). Sets actor from the nearest agent above, and for an invocation of
    another agent, actor = caller and to = the invoked agent."""
    by = {n["id"]: n for n in nodes}
    ctx = {}

    def context(n, depth=0):
        if n["id"] in ctx:
            return ctx[n["id"]]
        if n.get("own"):
            ctx[n["id"]] = n["own"]
            return n["own"]
        p = by.get(n.get("parent"))
        c = context(p, depth + 1) if p is not None and depth < 200 else None
        ctx[n["id"]] = c
        return c
    for n in nodes:
        context(n)
    for n in nodes:
        p = by.get(n.get("parent"))
        caller = ctx.get(p["id"]) if p is not None else None
        if n.get("delegate") and n.get("own") and caller and caller != n["own"]:
            n["actor"], n["to"] = caller, n["own"]
        else:
            n["actor"] = ctx.get(n["id"]) or n.get("fallback")
    return nodes


# ------------------------------------------------------------------ OpenTelemetry

def _otel_flatten(rows):
    out = []
    for r in rows:
        if "resourceSpans" in r or "resource_spans" in r:
            for rs in r.get("resourceSpans") or r.get("resource_spans") or []:
                out += _otel_flatten([rs])
        elif "scopeSpans" in r or "instrumentationLibrarySpans" in r or "scope_spans" in r:
            res = _attrs((r.get("resource") or {}).get("attributes"))
            for ss in r.get("scopeSpans") or r.get("instrumentationLibrarySpans") or r.get("scope_spans") or []:
                for sp in ss.get("spans", []):
                    out.append({**sp, "_resource": res})
        elif isinstance(r.get("spans"), list):
            out += [s for s in r["spans"] if isinstance(s, dict)]
        else:
            out.append(r)
    return out


def _is_otel(r):
    if any(k in r for k in ("resourceSpans", "resource_spans", "scopeSpans", "scope_spans")):
        return True
    has_ids = ("traceId" in r or "trace_id" in r or isinstance(r.get("context"), dict)) and \
              ("spanId" in r or "span_id" in r or isinstance(r.get("context"), dict))
    return has_ids and isinstance(r.get("attributes"), (dict, list)) and "span_data" not in r


def read_otel(rows, stem):
    spans = _otel_flatten(rows)
    nodes = []
    for i, s in enumerate(spans, start=1):
        a = _attrs(s.get("attributes"))
        res = s.get("_resource") or _attrs((s.get("resource") or {}).get("attributes"))
        ctx = s.get("context") if isinstance(s.get("context"), dict) else {}
        sid = _str(s.get("spanId") or s.get("span_id") or ctx.get("span_id")) or f"{stem}:{i}"
        parent = _str(s.get("parentSpanId") or s.get("parent_span_id") or s.get("parent_id"))
        trace = _str(s.get("traceId") or s.get("trace_id") or ctx.get("trace_id"))
        op = _str(a.get("gen_ai.operation.name"))
        agent = _str(a.get("gen_ai.agent.name") or a.get("agent.name") or a.get("gen_ai.agent.id"))
        tool = _str(a.get("gen_ai.tool.name") or a.get("tool.name"))
        events_text = []
        for ev in s.get("events") or []:
            ea = _attrs(ev.get("attributes"))
            body = ea.get("gen_ai.prompt") or ea.get("gen_ai.completion") or ea.get("content") or ea.get("message") or ea.get("body")
            if body:
                events_text.append(f"{ev.get('name', '')}: {_text(_maybe_json(body))}")
        prompt = a.get("gen_ai.prompt") or a.get("gen_ai.input.messages") or a.get("input.value") or a.get("gen_ai.tool.call.arguments")
        completion = a.get("gen_ai.completion") or a.get("gen_ai.output.messages") or a.get("output.value") or a.get("gen_ai.tool.call.result")
        # gen_ai.prompt.0.content style flattened attributes
        for pre, slot in (("gen_ai.prompt.", "prompt"), ("gen_ai.completion.", "completion")):
            parts = [f"{a.get(k.rsplit('.', 1)[0] + '.role', '')}: {v}" for k, v in sorted(a.items())
                     if k.startswith(pre) and k.endswith(".content")]
            if parts and slot == "prompt" and not prompt:
                prompt = "\n".join(parts)
            if parts and slot == "completion" and not completion:
                completion = "\n".join(parts)
        name = _str(s.get("name")) or op or "span"
        text = _join(name if not (prompt or completion or events_text) else (f"{tool}:" if tool else ""),
                     _args(prompt) if tool else _text(_maybe_json(prompt)), _text(_maybe_json(completion)), "\n".join(events_text))
        if not text:
            text = name + " " + json.dumps({k: v for k, v in a.items() if not k.startswith("gen_ai.usage")},
                                           ensure_ascii=False, sort_keys=True, default=str)[:2000]
        to = _str(a.get("gen_ai.handoff.to") or a.get("handoff.to") or a.get("gen_ai.agent.target") or _to_of(a))
        if not to and tool and TRANSFER.match(tool):
            to = TRANSFER.match(tool).group(1)
        nodes.append({"id": sid, "parent": parent, "own": agent, "delegate": op in ("invoke_agent", "create_agent") or
                      (s.get("kind") in (3, "SPAN_KIND_CLIENT", "CLIENT") and op == "invoke_agent"),
                      "fallback": _str(res.get("service.name")),
                      "row": {"id": sid, "text": text, "kind": op or _str(s.get("name")) or "span", "parent": parent,
                              "time": _iso(s.get("startTimeUnixNano") or s.get("start_time_unix_nano") or s.get("start_time")
                                           or s.get("startTime") or s.get("timestamp")),
                              "tool": tool, "channel": trace, "to": to}})
    _agent_tree(nodes)
    out = []
    for n in nodes:
        row = n["row"]
        row["actor"] = n.get("actor")
        if n.get("to") and not row["to"]:
            row["to"] = n["to"]
        out.append(row)
    return out


# ------------------------------------------------------------------ OpenAI Agents SDK

def _is_openai_agents(r):
    return isinstance(r.get("span_data"), dict) or r.get("object") in ("trace", "trace.span")


def read_openai_agents(rows, stem):
    nodes, traces = [], {}
    rows = [x for r in rows for x in (r.get("spans") if isinstance(r.get("spans"), list) else [r])]
    for r in rows:
        if r.get("object") == "trace" and "span_data" not in r:
            traces[r.get("id")] = r.get("workflow_name") or r.get("name")
    for i, r in enumerate(rows, start=1):
        sd = r.get("span_data")
        if not isinstance(sd, dict):
            if r.get("object") == "trace":
                tid = _str(r.get("id")) or f"{stem}:{i}"
                nodes.append({"id": tid, "parent": None, "own": None,
                              "row": {"id": tid, "text": f"trace {r.get('workflow_name') or ''}".strip(), "kind": "trace",
                                      "parent": None, "time": _iso(r.get("started_at") or r.get("created_at")),
                                      "tool": None, "channel": tid, "to": None}})
            continue
        typ = sd.get("type") or "span"
        sid = _str(r.get("id") or r.get("span_id")) or f"{stem}:{i}"
        parent = _str(r.get("parent_id")) or _str(r.get("trace_id"))
        own, tool, to, actor_override = None, None, None, None
        if typ == "agent":
            own = _str(sd.get("name"))
            extra = []
            if sd.get("handoffs"):
                extra.append("handoffs: " + ", ".join(map(str, sd["handoffs"])))
            if sd.get("tools"):
                extra.append("tools: " + ", ".join(map(str, sd["tools"])))
            text = _join(f"agent {own or ''}", "; ".join(extra))
        elif typ == "handoff":
            actor_override, to = _str(sd.get("from_agent")), _str(sd.get("to_agent"))
            text = f"handoff from {actor_override} to {to}"
        elif typ == "function":
            tool = _str(sd.get("name"))
            text = _join(f"{tool}(", _args(sd.get("input")), ") ->", _text(_maybe_json(sd.get("output"))))
        elif typ in ("generation", "response"):
            text = _join(_text(sd.get("input")), _text(sd.get("output"))) or f"{typ} {sd.get('response_id') or sd.get('model') or ''}".strip()
        else:
            text = _join(f"{typ} {sd.get('name') or ''}".strip(), _text(sd.get("data") or sd.get("output") or ""))
        if r.get("error"):
            text += " error: " + _text(r["error"])
        nodes.append({"id": sid, "parent": parent, "own": own or actor_override, "fallback": None,
                      "row": {"id": sid, "text": text, "kind": typ, "parent": parent,
                              "time": _iso(r.get("started_at") or r.get("start_time")), "tool": tool,
                              "channel": _str(r.get("trace_id")), "to": to}})
    _agent_tree(nodes)
    out = []
    for n in nodes:
        n["row"]["actor"] = n.get("actor")
        out.append(n["row"])
    return out


# ------------------------------------------------------------------ LangSmith

def _is_langsmith(r):
    return "run_type" in r and ("inputs" in r or "outputs" in r)


def read_langsmith(rows, stem):
    nodes = []
    for i, r in enumerate(rows, start=1):
        md = _get(r, "extra.metadata") or r.get("metadata") or {}
        md = md if isinstance(md, dict) else {}
        rt = _str(r.get("run_type")) or "run"
        name = _str(r.get("name")) or rt
        rid = _str(r.get("id")) or f"{stem}:{i}"
        own = _str(md.get("agent_name") or md.get("lc_agent_name") or md.get("langgraph_node") or md.get("agent"))
        if own in ("__start__", "tools", "agent", "model", "call_model", "__end__"):
            own = None
        tool = name if rt == "tool" else None
        to = _to_of(r.get("inputs") or {}) if rt == "tool" else None
        if tool and TRANSFER.match(tool):
            to = TRANSFER.match(tool).group(1)
        ins, outs = r.get("inputs"), r.get("outputs")
        if rt == "llm" and isinstance(ins, dict) and isinstance(ins.get("messages"), list):
            msgs = ins["messages"]
            if msgs and isinstance(msgs[0], list):
                msgs = msgs[0]
            ins = msgs[-1:] if msgs else ins  # the newest turn; earlier ones are in earlier runs
        text = _join(f"{name}:" if rt in ("tool", "chain") else "", _text(ins), "->" if outs else "", _text(outs))
        if r.get("error"):
            text += " error: " + _text(r["error"])
        nodes.append({"id": rid, "parent": _str(r.get("parent_run_id")), "own": own, "fallback": None,
                      "row": {"id": rid, "text": text or name, "kind": rt, "parent": _str(r.get("parent_run_id")),
                              "time": _iso(r.get("start_time")), "tool": tool,
                              "channel": _str(r.get("trace_id") or r.get("session_id")), "to": to}})
    # with no agent anywhere, the root run names the actor
    if not any(n["own"] for n in nodes):
        for n in nodes:
            if not n["parent"]:
                n["own"] = n["row"]["text"].split(":")[0] if n["row"]["kind"] == "chain" else None
    _agent_tree(nodes)
    out = []
    for n in nodes:
        n["row"]["actor"] = n.get("actor")
        out.append(n["row"])
    return out


# ------------------------------------------------------------------ Langfuse

LF_TYPES = {"SPAN", "GENERATION", "EVENT", "AGENT", "TOOL", "CHAIN", "RETRIEVER", "EMBEDDING", "EVALUATOR", "GUARDRAIL"}


def _is_langfuse(r):
    t = r.get("type")
    return ("traceId" in r or "trace_id" in r) and isinstance(t, str) and t.upper() in LF_TYPES and \
        ("startTime" in r or "parentObservationId" in r or "start_time" in r)


def read_langfuse(rows, stem):
    nodes = []
    for i, r in enumerate(rows, start=1):
        md = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        typ = (_str(r.get("type")) or "SPAN").upper()
        name = _str(r.get("name")) or typ.lower()
        oid = _str(r.get("id")) or f"{stem}:{i}"
        parent = _str(r.get("parentObservationId") or r.get("parent_observation_id"))
        own = _str(md.get("agent") or md.get("agent_name") or md.get("langgraph_node")) or (name if typ == "AGENT" else None)
        tool = name if typ == "TOOL" or md.get("tool") else None
        to = _str(md.get("handoff_to")) or _to_of(md) or (_to_of(r.get("input")) if isinstance(r.get("input"), dict) and tool else None)
        if tool and TRANSFER.match(tool):
            to = TRANSFER.match(tool).group(1)
        text = _join(f"{name}:", _args(r.get("input")) if tool else _text(r.get("input")),
                     "->" if r.get("output") else "", _text(r.get("output")))
        if r.get("statusMessage"):
            text += " status: " + _text(r["statusMessage"])
        nodes.append({"id": oid, "parent": parent, "own": own, "delegate": typ == "AGENT", "fallback": None,
                      "row": {"id": oid, "text": text, "kind": typ.lower(), "parent": parent,
                              "time": _iso(r.get("startTime") or r.get("start_time") or r.get("timestamp")),
                              "tool": tool, "channel": _str(r.get("traceId") or r.get("trace_id")), "to": to}})
    _agent_tree(nodes)
    out = []
    for n in nodes:
        n["row"]["actor"] = n.get("actor")
        if n.get("to") and not n["row"]["to"]:
            n["row"]["to"] = n["to"]
        out.append(n["row"])
    return out


# ------------------------------------------------------------------ AutoGen / AG2

def _is_autogen(r):
    if "sender" in r and ("recipient" in r or "receiver" in r):
        return True
    t = r.get("type")
    return "source" in r and "content" in r and isinstance(t, str) and (t.endswith("Message") or t.endswith("Event"))


def read_autogen(rows, stem):
    out, prev, last_call = [], None, {}
    for i, r in enumerate(rows, start=1):
        rid = _str(r.get("id")) or f"{stem}:{i}"
        actor = _str(r.get("sender") or r.get("source"))
        typ = _str(r.get("type")) or "message"
        msg = r.get("message", r.get("content"))
        tool = None
        content = msg
        if isinstance(msg, dict):
            content = msg.get("content")
            calls = msg.get("tool_calls") or msg.get("function_call")
            if calls:
                c = calls[0] if isinstance(calls, list) else calls
                tool = _str(_get(c, "function.name", "name"))
                content = _join(_text(content), _text(calls))
        if isinstance(content, list) and content and isinstance(content[0], dict) and ("name" in content[0] or "call_id" in content[0]):
            tool = _str(content[0].get("name")) or tool
        to = _str(r.get("recipient") or r.get("receiver") or r.get("target"))
        if not to and tool and TRANSFER.match(tool):
            to = TRANSFER.match(tool).group(1)
        out.append({"id": rid, "text": _text(content) or typ, "kind": typ, "parent": _str(r.get("reply_to")) or prev,
                    "actor": actor, "time": _iso(r.get("timestamp") or r.get("created_at") or r.get("time")),
                    "tool": tool, "channel": _str(r.get("chat_id") or r.get("conversation_id") or r.get("session_id")) or stem,
                    "to": to if to != actor else None})
        prev = rid
    return out


# ------------------------------------------------------------------ CrewAI

def _is_crewai(r):
    if "agent" not in r and "agent_role" not in r:
        return False
    ev = str(r.get("event") or r.get("event_type") or r.get("type") or "")
    return any(k in r for k in ("task", "task_name", "task_id", "task_description", "crew", "tool_input")) or \
        ev.startswith(("task_", "agent_execution", "tool_usage", "crew_"))


def read_crewai(rows, stem):
    out, first_of_task = [], {}
    for i, r in enumerate(rows, start=1):
        rid = _str(r.get("id") or r.get("event_id")) or f"{stem}:{i}"
        agent = r.get("agent") or r.get("agent_role")
        if isinstance(agent, dict):
            agent = agent.get("role") or agent.get("name")
        kind = _str(r.get("event") or r.get("event_type") or r.get("type") or r.get("status")) or "step"
        task = _str(r.get("task_id") or r.get("task_name") or r.get("task") or r.get("task_description"))
        tool = _str(r.get("tool") or r.get("tool_name"))
        tin = _maybe_json(r.get("tool_input") or r.get("tool_args") or r.get("input"))
        to = _str(r.get("delegated_to")) or (_to_of(tin) if isinstance(tin, dict) else None) or _to_of(r)
        text = _join(f"[{task}]" if task and kind.startswith("task") else "", _text(r.get("description") or ""),
                     f"{tool}({_args(tin)})" if tool else "",
                     _text(r.get("output") or r.get("result") or r.get("thought") or r.get("message") or ""))
        parent = _str(r.get("parent_id"))
        if not parent and task and task in first_of_task:
            parent = first_of_task[task]
        if task:
            first_of_task.setdefault(task, rid)
        out.append({"id": rid, "text": text or kind, "kind": kind, "parent": parent, "actor": _str(agent),
                    "time": _iso(r.get("timestamp") or r.get("time") or r.get("created_at")), "tool": tool,
                    "channel": _str(r.get("crew") or r.get("crew_name")) or task or stem,
                    "to": to if to != _str(agent) else None})
    return out


# ------------------------------------------------------------------ MCP (JSON-RPC)

WRAP_KEYS = ("message", "payload", "data", "msg", "jsonrpc_message", "body")


def _rpc(r):
    if "jsonrpc" in r:
        return r, {}
    for k in WRAP_KEYS:
        v = _maybe_json(r.get(k))
        if isinstance(v, dict) and "jsonrpc" in v:
            return v, {kk: vv for kk, vv in r.items() if kk != k}
    return None, r


def _is_mcp(r):
    return _rpc(r)[0] is not None


def read_mcp(rows, stem):
    out, req = [], {}
    for i, r in enumerate(rows, start=1):
        m, meta = _rpc(r)
        if m is None:
            continue
        client = _str(meta.get("client") or meta.get("agent") or meta.get("agent_name") or meta.get("client_name") or meta.get("from"))
        server = _str(meta.get("server") or meta.get("server_name") or meta.get("to_server")) or "server"
        session = _str(meta.get("session") or meta.get("session_id") or meta.get("connection")) or client or stem
        direction = str(meta.get("direction") or "")
        rid = _str(meta.get("id") or meta.get("event_id")) or f"{stem}:{i}"
        t = _iso(meta.get("timestamp") or meta.get("ts") or meta.get("time"))
        if "method" in m:
            method = str(m["method"])
            params = m.get("params") or {}
            from_server = direction.startswith(("server", "s2c", "incoming")) or "<-" in direction
            actor = server if from_server else (client or "client")
            tool = _str(params.get("name")) if method == "tools/call" else None
            args = params.get("arguments") if isinstance(params, dict) else None
            to = _to_of(args) if isinstance(args, dict) else None
            text = f"{method} {tool or ''} {_args(args) if args is not None else _args(params)}".replace("  ", " ").strip()
            if "id" in m:
                req[(session, str(m["id"]))] = (rid, actor)
            out.append({"id": rid, "text": text, "kind": method, "parent": None, "actor": actor, "time": t,
                        "tool": tool, "channel": session, "to": to})
        else:
            key = (session, str(m.get("id")))
            parent, asker = req.get(key, (None, None))
            res = m.get("result")
            err = m.get("error")
            body = _text(res.get("content") if isinstance(res, dict) and "content" in res else res) if res is not None else ""
            actor = server if asker != server else (client or "client")
            out.append({"id": rid, "text": (body or "") + (" error: " + _text(err) if err else ""),
                        "kind": "error" if err else "result", "parent": parent, "actor": actor, "time": t,
                        "tool": None, "channel": session, "to": None})
    return out


# ------------------------------------------------------------------ chat transcripts

def _is_chat(r):
    return "role" in r and ("content" in r or "text" in r) and "messages" not in r and \
        len(set(r) - {"id", "role", "name", "content", "text", "timestamp", "time", "created_at", "tool_calls",
                      "tool_call_id", "to", "recipient", "conversation_id", "thread_id", "reply_to", "parent_id",
                      "sender", "function_call", "metadata"}) <= 2


def read_chat(rows, stem):
    out, prev, speaker = [], None, None
    for i, r in enumerate(rows, start=1):
        rid = _str(r.get("id")) or f"{stem}:{i}"
        role = _str(r.get("role")) or "message"
        tool = None
        if r.get("tool_calls"):
            tool = _str(_get(r["tool_calls"][0], "function.name", "name")) if isinstance(r["tool_calls"], list) else None
        elif role in ("tool", "function"):
            tool = _str(r.get("name"))
        # a tool's output is credited to the agent that called the tool
        actor = _str(r.get("name") or r.get("sender")) if role not in ("tool", "function") else speaker
        to = _str(r.get("to") or r.get("recipient"))
        if not to and tool and TRANSFER.match(tool):
            to = TRANSFER.match(tool).group(1)
        text = _text(r.get("content") if "content" in r else r.get("text"))
        if r.get("tool_calls"):
            text = _join(text, _text(r["tool_calls"]))
        out.append({"id": rid, "text": text, "kind": role, "parent": _str(r.get("reply_to") or r.get("parent_id")) or prev,
                    "actor": actor or role, "time": _iso(r.get("timestamp") or r.get("time") or r.get("created_at")),
                    "tool": tool, "channel": _str(r.get("conversation_id") or r.get("thread_id")) or stem,
                    "to": to if to != actor else None})
        prev = rid
        if role not in ("tool", "function"):
            speaker = actor or role
    return out


# ------------------------------------------------------------------ detection

DETECTORS = [("otel", _is_otel, read_otel), ("openai_agents", _is_openai_agents, read_openai_agents),
             ("langsmith", _is_langsmith, read_langsmith), ("langfuse", _is_langfuse, read_langfuse),
             ("mcp", _is_mcp, read_mcp), ("autogen", _is_autogen, read_autogen),
             ("crewai", _is_crewai, read_crewai), ("chat", _is_chat, read_chat)]


def detect(rows):
    """The format whose shape at least half the rows have, else None."""
    if not rows:
        return None
    for key, test, _ in DETECTORS:
        if _share(rows, test) >= (0.8 if key == "chat" else 0.5):
            return key
    return None


def _resolve_to(rows):
    """Recipients named loosely (transfer_to_writer, 'writer agent') -> the actor names in the file."""
    actors = {r["actor"] for r in rows if r.get("actor")}
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    idx = {norm(a): a for a in actors}
    for r in rows:
        t = r.get("to")
        if t and t not in actors:
            k = norm(t)
            if k in idx:
                r["to"] = idx[k]
            else:
                hits = [a for n, a in idx.items() if n and (k.endswith(n) or k.startswith(n))]
                if len(hits) == 1:
                    r["to"] = hits[0]
        if r.get("to") and r["to"] == r.get("actor"):
            r["to"] = None
    return rows


def read(rows, stem):
    """(format key, rows): rows normalized to COLUMNS when a format is recognized, else (None, rows)."""
    key = detect(rows)
    if key is None:
        return None, rows
    reader = dict((k, f) for k, _, f in DETECTORS)[key]
    out = [r for r in reader(rows, stem) if r]
    if not out:
        return None, rows
    seen = Counter(r["id"] for r in out)
    if any(v > 1 for v in seen.values()):  # ids must be unique in a file
        n = Counter()
        for r in out:
            if seen[r["id"]] > 1:
                n[r["id"]] += 1
                r["id"] = f"{r['id']}#{n[r['id']]}"
    return key, _resolve_to(out)


def label(key):
    return FORMATS.get(key, GENERIC) if key else GENERIC


# ------------------------------------------------------------------ pack builder

CRED_CLASSES = [
    ("placeholder", r"\[[A-Z][A-Z _]*?[ :]?\d+\]", lambda tok: r"(\[" + re.escape(re.sub(r"[ :]?\d+\]$", "", tok[1:])) + r"[ :]?\d+\])"),
    ("angle_placeholder", r"<[A-Z][A-Z_]{2,}(?:_\d+)?>", lambda tok: r"(<" + re.escape(re.sub(r"_?\d*>$", "", tok[1:])) + r"(?:_\d+)?>)"),
    ("template_var", r"\{\{\s*[A-Za-z_][\w.]*\s*\}\}", lambda tok: r"(\{\{\s*[A-Za-z_][\w.]*\s*\}\})"),
    ("openai_key", r"\bsk-[A-Za-z0-9_\-]{16,}", lambda tok: r"\b(sk-[A-Za-z0-9_\-]{16,})"),
    ("hf_token", r"\bhf_[A-Za-z0-9]{20,}", lambda tok: r"\b(hf_[A-Za-z0-9]{20,})"),
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{20,}", lambda tok: r"\b(gh[pousr]_[A-Za-z0-9]{20,})"),
    ("aws_key", r"\bAKIA[0-9A-Z]{16}\b", lambda tok: r"\b(AKIA[0-9A-Z]{16})\b"),
    ("bearer", r"Bearer\s+[A-Za-z0-9_\-\.]{16,}", lambda tok: r"Bearer\s+([A-Za-z0-9_\-\.]{16,})"),
    ("api_key_header", r"(?i:x-api-key|api[_-]?key|token)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{16,}",
     lambda tok: r"(?:x-api-key|api[_-]?key|token)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{16,})"),
]
URL = re.compile(r"(?:https?://([\w.-]+\.[a-z]{2,}|localhost|\d+\.\d+\.\d+\.\d+)|(?:s3|gs|az|ftp)://([\w.-]+))(?::\d+)?((?:/[\w.%~-]+){0,2})", re.I)
PATHLIKE = re.compile(r"(?<![\w/:.])((?:\.{0,2}/)?(?:[\w.-]+/){1,4}[\w.-]+)(?![\w/])")
WRITE_WORDS = re.compile(r"(?<![a-z])(write|wrote|save|saved|post|put|upload|append|commit|create|created|send|sent|publish|edit|update|overwrite|echo\s.*>)(?![a-z])", re.I)
HTTP_EP = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w./{}:-]*)")
VERBS = {"search", "fetch", "read", "write", "send", "post", "get", "create", "update", "delete", "run", "execute",
         "call", "query", "list", "open", "save", "upload", "download", "review", "plan", "summarize", "draft",
         "check", "verify", "deploy", "install", "scan", "login", "transfer", "handoff", "delegate", "ask", "reply",
         "analyze", "browse", "click", "submit", "approve", "reject", "commit", "push", "merge", "test"}
ACTION_HINT = re.compile(r"call|tool|function|request|action|payload|handoff|generation|chat|assistant|agent|send|"
                         r"post|write|edit|task|step|code|exec|invoke|message", re.I)
NOT_ACTION_HINT = re.compile(r"^(result|response|output|completion|tool_result|user|system|human|error|trace|"
                             r"notifications?/.*|guardrail|initialize|ping|(tools|resources|prompts)/list)$", re.I)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")[:48] or "pack"


def _ex(lst, n=3, width=140):
    out = []
    for x in lst:
        x = " ".join(str(x).split())
        x = x if len(x) <= width else x[:width - 1] + "…"
        if x not in out:
            out.append(x)
        if len(out) == n:
            break
    return out


def _snip(text, start, end, width=120):
    a = max(0, start - width // 3)
    return ("…" if a else "") + " ".join(text[a:a + width].split()) + ("…" if a + width < len(text) else "")


def suggest(events, report, filename="sample"):
    """A proposed pack for a sample: columns found, identity tokens, places, intents and action kinds."""
    n = len(events)
    actor_of = lambda e: e.actor or "(no actor)"
    # identity tokens
    ident = []
    for cls, pat, mk in CRED_CLASSES:
        rx = re.compile(pat)
        toks, recs, actors, ex = Counter(), set(), set(), []
        for e in events:
            for m in rx.finditer(e.text):
                tok = m.group(0)
                if cls in ("bearer", "api_key_header"):
                    tok = re.split(r"[\s:='\"]+", tok)[-1]
                toks[tok] += 1
                recs.add(e.id)
                actors.add(actor_of(e))
                if len(ex) < 3:
                    ex.append({"id": e.id, "text": _snip(e.text, m.start(), m.end())})
        repeated = {t: c for t, c in toks.items() if c >= 2}
        if not repeated:
            continue
        first = max(repeated, key=repeated.get)
        ident.append({"key": cls, "label": cls.replace("_", " "), "records": len(recs), "uses": sum(toks.values()),
                      "tokens": len(toks), "repeated_tokens": len(repeated), "actors": len(actors),
                      "top_tokens": [[t, c] for t, c in Counter(repeated).most_common(5)], "examples": ex,
                      "entry": {"role": cls, "pattern": mk(first)}})
    ident.sort(key=lambda x: -x["records"])
    # places: URL hosts/paths and folder-like names
    kinds_seen = {e.kind for e in events}
    places = defaultdict(lambda: {"records": set(), "actors": set(), "writers": set(), "readers": set(), "ex": []})
    for e in events:
        text = e.text[:20000]
        found = {}
        for m in URL.finditer(text):
            host, path = (m.group(1) or m.group(2)).lower().rstrip(".-"), m.group(3) or ""
            found[("url", host)] = m
            if path:
                found[("url", host + path.split("/")[0] + "/" + path.strip("/").split("/")[0])] = m
        for m in PATHLIKE.finditer(text):
            p = m.group(1).rstrip(".,;:-")
            if p in kinds_seen or re.match(r"\d", p) or re.search(r"/\d*[a-z]{1,3}$", p) and "." not in p:
                continue  # record kinds (tools/call), prices ($19/mo) and units are not places
            if "." in p.split("/")[0] and not p.startswith(".") or len(p) < 5 or p.count("/") < 1 or re.fullmatch(r"[\d/.]+", p):
                continue  # hosts, dates and fractions are not folders
            found[("path", p)] = m
        for k, m in found.items():
            d = places[k]
            d["records"].add(e.id)
            a = actor_of(e)
            d["actors"].add(a)
            window = text[max(0, m.start() - 120): m.end() + 160]
            wrote = WRITE_WORDS.search(window) or (e.tool and WRITE_WORDS.search(e.tool))
            (d["writers"] if wrote else d["readers"]).add(a)
            if len(d["ex"]) < 3:
                d["ex"].append({"id": e.id, "text": _snip(text, m.start(), m.end())})
    prop_places = []
    for (typ, name), d in places.items():
        if len(d["records"]) < 2:
            continue
        if typ == "url":
            pat = r"(?:https?|s3|gs|az|ftp)://(" + re.escape(name) + (r"(?:/[\w.%~-]+){0,2}" if "/" not in name else r"[\w.%~/-]*") + ")"
        else:
            pat = "(" + re.escape(name) + ")"
        prop_places.append({"key": f"{typ}:{name}", "label": name, "type": "web address" if typ == "url" else "file or folder",
                            "records": len(d["records"]), "actors": len(d["actors"]), "writers": len(d["writers"]),
                            "readers": len(d["readers"]), "examples": d["ex"],
                            "suggested": len(d["actors"]) >= 2,
                            "entry": {"name": _slug(name.split("/")[-1] if typ == "path" else name)[:24] or typ,
                                      "pattern": pat, "flags": "i",
                                      "write": WRITE_WORDS.pattern}})
    prop_places.sort(key=lambda x: (-x["actors"], -x["records"]))
    # intents: tools, endpoints, leading verbs
    tools, eps, verbs = Counter(), Counter(), Counter()
    tool_ex, ep_ex, verb_ex = defaultdict(list), defaultdict(list), defaultdict(list)
    for e in events:
        if e.tool:
            tools[e.tool] += 1
            tool_ex[e.tool].append({"id": e.id, "text": e.text[:140]})
        for m in HTTP_EP.finditer(e.text[:5000]):
            k = f"{m.group(1)} {m.group(2)}"
            eps[k] += 1
            ep_ex[k].append({"id": e.id, "text": _snip(e.text, m.start(), m.end())})
        w = re.match(r"\s*([A-Za-z]+)", e.text)
        if w and w.group(1).lower() in VERBS:
            v = w.group(1).lower()
            verbs[v] += 1
            verb_ex[v].append({"id": e.id, "text": e.text[:140]})
    intents = []
    for name, c in tools.most_common(25):
        intents.append({"key": "tool:" + name, "label": f"tool {name}", "source": "tool", "records": c,
                        "examples": tool_ex[name][:3], "suggested": c >= 2,
                        "entry": {"name": _slug(name), "pattern": r"\b" + re.escape(name) + r"\b"}})
    for name, c in eps.most_common(15):
        if c < 2:
            continue
        meth, path = name.split(" ", 1)
        intents.append({"key": "endpoint:" + name, "label": name, "source": "endpoint", "records": c,
                        "examples": ep_ex[name][:3], "suggested": True,
                        "entry": {"name": _slug(f"{meth}_{path}"), "pattern": re.escape(meth) + r"\s+" + re.escape(path)}})
    for name, c in verbs.most_common(15):
        if c < 2:
            continue
        intents.append({"key": "verb:" + name, "label": name, "source": "verb", "records": c,
                        "examples": verb_ex[name][:3], "suggested": c >= 3,
                        "entry": {"name": name, "pattern": r"\b" + name + r"\b", "flags": "i"}})
    # which kinds are actions
    kinds = Counter(e.kind for e in events)
    with_tool = Counter(e.kind for e in events if e.tool)
    with_actor = Counter(e.kind for e in events if e.actor)
    kind_ex = defaultdict(list)
    for e in events:
        if len(kind_ex[e.kind]) < 2:
            kind_ex[e.kind].append({"id": e.id, "text": e.text[:140]})
    kind_rows = []
    for k, c in kinds.most_common(40):
        act = (with_tool[k] >= 0.5 * c or bool(ACTION_HINT.search(k))) and not NOT_ACTION_HINT.match(k)
        kind_rows.append({"kind": k, "records": c, "with_tool": with_tool[k], "with_actor": with_actor[k],
                          "examples": kind_ex[k], "suggested": act})
    files = (report or {}).get("files", [])
    cols = {}
    for f in files:
        for role, fs in f.get("fields", {}).items():
            cols.setdefault(role, fs)
    stats = {"records": n, "with_actor": sum(1 for e in events if e.actor), "with_time": sum(1 for e in events if e.time),
             "with_parent": sum(1 for e in events if e.parent), "with_tool": sum(1 for e in events if e.tool),
             "addressed": sum(1 for e in events if getattr(e, "to", None)),
             "actors": len({e.actor for e in events if e.actor})}
    base = _base_pack()
    stem = os.path.splitext(os.path.basename(filename or "sample"))[0]
    return {"file": filename, "format": (report or {}).get("format") or GENERIC,
            "columns": {r: cols.get(r, []) for r in ("id", "text", "kind", "parent", "actor", "time", "tool", "channel", "to")},
            "stats": stats, "identity": ident, "places": prop_places[:40], "intents": intents, "kinds": kind_rows,
            "name": f"{_slug(stem)}", "description": f"Built from the sample {filename} ({n} records).", "base": base}


def _base_pack():
    """The general pack's behaviors, info patterns and time settings: kept as the base of a new pack."""
    from .session import PACK_DIR
    try:
        with open(os.path.join(PACK_DIR, "generic.json"), encoding="utf-8") as f:
            g = json.load(f)
    except (OSError, ValueError):
        g = {}
    keep = ("behaviors", "info_patterns", "harm", "time", "handles", "handle_families", "shared_names",
            "structural_channels", "mention_channels", "auto_shared_identities")
    return {k: g[k] for k in keep if k in g}


# ------------------------------------------------------------------ API

def _pack_suggest(state, q, body):
    from . import model
    if not body:
        raise ValueError("send a sample file as the request body")
    if len(body) > 200 * 1024 * 1024:
        raise ValueError("sample is too large; use a smaller sample (a few thousand records is plenty)")
    raw = re.split(r"[\\/]", str(q.get("filename") or "sample.jsonl"))[-1]
    stem, ext = os.path.splitext(raw)
    name = (re.sub(r"[^A-Za-z0-9._-]", "_", stem).lstrip(".")[:80] or "sample") + ext.lower()
    if os.path.splitext(name)[1].lower() not in model.DATA_EXTS:
        name = os.path.splitext(name)[0] + ".jsonl"
    d = tempfile.mkdtemp(prefix="packsample_")
    saved = json.loads(json.dumps(model.LAST_REPORT, default=str))
    try:
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(body)
        try:
            events = model.load(p)
        except (ValueError, UnicodeDecodeError, SystemExit) as e:
            raise ValueError(f"could not read the sample: {e}")
        report = json.loads(json.dumps(model.LAST_REPORT, default=str))
        if not events:
            raise ValueError("the sample has no records")
        return suggest(events, report, name)
    finally:
        model.LAST_REPORT.clear()
        model.LAST_REPORT.update(saved)
        shutil.rmtree(d, ignore_errors=True)


BUILTIN = {"generic.json", "chat.json", "code_traces.json", "wiki_swarm.json"}
MAX_PACK_BYTES = 1_000_000
PACK_FILE_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


def _pack_file(raw):
    """The file name a pack is saved under: a strict slug. An explicit `file` must already be one;
    a name is slugged (it is only a display name)."""
    f = raw.get("file")
    if f not in (None, ""):
        f = str(f).strip()
        if f.lower().endswith(".json"):
            f = f[:-5]
        if not PACK_FILE_RX.fullmatch(f):
            raise ValueError("the pack's file name may use only lower-case letters, digits, '_' and '-' "
                             "(at most 48, no folders, no '..')")
        return f + ".json"
    return _slug(raw.get("name")) + ".json"


def save_pack(raw, overwrite=False, pack_dir=None):
    """Validate a pack (as packs.load_pack would read it) and save it as packs/<name>.json, atomically."""
    from . import packs
    from .session import PACK_DIR
    pack_dir = pack_dir or PACK_DIR
    if not isinstance(raw, dict):
        raise ValueError("a pack is a JSON object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("the pack needs a name")
    if len(name) > 120:
        raise ValueError("the pack's name is too long (120 characters at most)")
    fname = _pack_file(raw)
    raw = {k: v for k, v in raw.items() if k != "file"}
    text = json.dumps(raw, indent=2, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_PACK_BYTES:
        raise ValueError(f"the pack is larger than {MAX_PACK_BYTES:,} bytes")
    path = os.path.join(pack_dir, fname)
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(pack_dir):
        raise ValueError("the pack's file name may not contain a folder")
    if fname in BUILTIN:
        raise ValueError(f"{fname} is a shipped pack; pick another name")
    if os.path.lexists(path) and not overwrite:
        raise ValueError(f"a pack named {fname} already exists; pick another name or overwrite it")
    if os.path.islink(path) or (os.path.exists(path) and not os.path.isfile(path)):
        raise ValueError(f"{fname} exists and is not a plain pack file; pick another name")
    # written next to the target (same disk, so the final rename is atomic) under a name list_packs ignores
    fd, tmp = tempfile.mkstemp(prefix=".pack-", suffix=".part", dir=pack_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            p = packs.load_pack(tmp)
        except SystemExit as e:
            raise ValueError(f"invalid pack: {e}")
        except (KeyError, TypeError, AttributeError, ValueError, re.error) as e:
            raise ValueError(f"invalid pack: missing or malformed field {e}")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"file": fname, "name": p.name, "description": p.description, "path": path}


def _pack_save(state, q, body):
    if len(body or b"") > MAX_PACK_BYTES:
        raise ValueError(f"the pack is larger than {MAX_PACK_BYTES:,} bytes")
    try:
        raw = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except ValueError as e:
        raise ValueError(f"the pack is not valid JSON: {e}")
    return save_pack(raw, overwrite=q.get("overwrite") in ("1", "true", "yes"))


def _formats(state, q):
    return {"formats": [{"key": k, "name": v} for k, v in FORMATS.items()]}


GET = {"formats": _formats}
POST = {"pack_suggest": _pack_suggest, "pack_save": _pack_save}

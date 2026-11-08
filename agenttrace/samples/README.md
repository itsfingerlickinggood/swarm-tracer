# Sample traces, one per format

Small, made-up multi-agent traces (10 to 40 records each) in the formats Swarm Tracer reads
without a pack or column mapping. The format is detected from the data's shape; the overview's
read report names it. Each has at least one agent-to-agent handoff or message, which the app
shows as a "direct message (logged)" in Who talked to whom.

| file | format | what happens |
|---|---|---|
| `otel_genai_spans.json` | OpenTelemetry GenAI spans (OTLP JSON: resourceSpans / scopeSpans / spans) | a planner invokes a researcher and a writer (`invoke_agent`), who use tools and share `shared/notes/pricing.md` |
| `openai_agents_trace.jsonl` | OpenAI Agents SDK trace (trace + spans with `span_data`) | a triage agent hands off to a refund agent and back (`handoff` spans) |
| `langsmith_runs.json` | LangSmith runs (`run_type`, `inputs`, `outputs`, `parent_run_id`) | a LangGraph swarm: alice calls `transfer_to_bob`, bob books a table and transfers back |
| `langfuse_observations.json` | Langfuse trace with observations (AGENT / GENERATION / TOOL / EVENT) | a supervisor delegates a failing test to a coder and a reviewer; the reviewer hands a comment back to the coder |
| `autogen_messages.jsonl` | AutoGen / AG2 message log (`sender`, `recipient`, `message`) | a group chat debugging an ETL failure caused by a rotated key (`[CREDENTIAL 1]` placeholders) |
| `crewai_log.jsonl` | CrewAI event log (`agent`, `task_id`, `tool`, `tool_input`) | a product manager delegates a launch post to a copywriter ("Delegate work to coworker") |
| `mcp_toolcalls.jsonl` | MCP tool-call log (JSON-RPC `tools/call` requests and responses, wrapped with client / server / session) | a triage agent and an ops agent message each other through a `team-bus` server's `send_message` tool |
| `chat_transcript.json` | plain chat transcript (`role`, `name`, `content`, optional `to`) | planner, coder and tester address each other while adding a CSV export |

`demo_swarm/` holds the bundled demo swarm used by `python3 -m agenttrace demo` (not one of the format samples).

Try one:

    python3 -m agenttrace serve --input agenttrace/samples/otel_genai_spans.json

or open Load data in the app and pick a file. "Build a pack from a sample…" in the same panel
proposes a pack (identity tokens, places, intents, action kinds) from any of these files.

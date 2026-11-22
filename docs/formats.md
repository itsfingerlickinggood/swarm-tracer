# Trace formats

[Home](./) · [Getting started](getting-started.md) · [Packs](packs.md)

Swarm Tracer picks the format from the shape of the records, never from the file name. The Overview's read report says which format it detected and where each field came from.

## Files and folders

- **JSONL**, **JSON** (an array, or an object holding a list such as `{"events": [...]}`), **CSV** and **TSV**.
- **Plain-text logs** (`.txt`, `.log`): lines of JSON are read as JSONL; otherwise each line is one record.
- **Folders**: every trace file in the folder is read, and files are linked by ids. Files whose rows have no time and no parent are set aside as reference tables when the folder also has event logs. Other files (images, notes) are left out, and the app says so.

Fields are found by name across common layouts: id, text, kind, parent, actor, time, tool, channel, and recipient (`to`, `recipient`, `receiver`, `target_agent`, `handoff_to`, …). A chain of fields can stand in for one (for example `label`, then `actor_label`). Name a column by hand under **Load data → Columns**, or with `--map actor=meta.agent` on the command line (dotted paths work in JSON).

## Agent frameworks

| Format | What becomes the actor | Messages |
|---|---|---|
| OpenTelemetry GenAI spans (OTLP `resourceSpans` or flat spans) | `gen_ai.agent.name`, inherited from the nearest agent span | `invoke_agent` spans and `transfer_to_<agent>` tools are handoffs |
| OpenAI Agents SDK traces | agent spans | handoff spans |
| LangSmith runs | the run's agent name | `transfer_to_…` tools, child agent runs |
| Langfuse observations | the AGENT observation | nested agents |
| AutoGen / AG2 message logs | `sender` / `source` | `sender` → `recipient` |
| CrewAI events | the agent's role | "Delegate work to coworker" |
| MCP tool-call logs (JSON-RPC) | client or session | responses link to their request |
| Chat transcripts (`role`/`name`/`content`) | the speaker; tool messages go to the agent that called the tool | addressed messages |

A message an agent logged to another counts directly, with the evidence "direct message (logged)", on the place `inbox:<recipient>`; the recipient's reply, when there is one, is the read. Messages left in shared places (datasets, boards, pages) are inferred as described in [How it works](how-it-works.md).

Tool calls (since v2.3.0, with the general pack or a pack made by the pack builder). A tool server is infrastructure, not a party: its answers (`result` and `error` records of an MCP log) are not actions, so a call is not a message from the agent to the server. A tool call that names a place in an argument (`write(place=…)`, `read_file(path=…)`, also `key`, `uri`, `channel`, `page` and the other keys in the pack's `tool_places`) writes or reads the place `tool:<value>`, whatever the value looks like; the tool's name says which. One agent writing a place and another reading it later through such calls is a message between the two agents ([counting rule](counting-rule.md) R2, R18a).

## Public datasets

Two openly licensed datasets have their own readers (`agenttrace/readers_public.py`). Both are published as Parquet, which the standard library cannot read: `python3 -m agenttrace.tools.external fetch <name>` downloads a documented subset and `convert <name>` writes JSON Lines with the same columns (the conversion needs the `duckdb` module; the tool does not). The data is not in this repository. See [Datasets](datasets.html) for sources and terms.

| Format | What becomes the actor | Messages | Times |
|---|---|---|---|
| SALT agent-collusion episodes (`run_id`, `episode_index`, `communication`) | the message's `sender`; with the run added when a file holds several runs | every message is addressed to its `receiver` | none: the episodes log order only |
| Moltbook Observatory posts and comments (`agent_name`, `submolt`, `post_id`, `parent_id`) | `agent_name` | a comment is addressed to the author of its parent (a comment, else the post) when that record is in the same file; the thread is the place | `created_at` |

The SALT reader does not read the verdicts or the `collusion` label that sit in the same rows. What the tool finds on both, scored against the datasets' own labels, is in `reports/external/salt/summary.md` and `reports/external/moltbook/summary.md`.

## Samples

`agenttrace/samples/` has one small sample per framework format and `demo_swarm/`, a simulated swarm with its true links (`demo_swarm.jsonl.truth`). Load any of them with **Load data**, or:

```bash
swarm-tracer serve --input agenttrace/samples/otel_genai_spans.json
```

## When the tool needs more

If your swarm leaves its traces in places no pack describes, build a pack from a sample (**Load data → Build a pack from a sample…**): see [Packs](packs.md).

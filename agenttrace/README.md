# agenttrace

## Swarm Tracer app

A local web app for investigating any agent-swarm trace: who talked to whom, how information spread, whether coordination could have been flagged early, and what an investigator would still miss.

```bash
python3 -m agenttrace serve                    # then open http://127.0.0.1:8010 and upload a file
python3 -m agenttrace serve --input redacted_columns.csv --pack code_traces.json   # preload a file
```

- **Top bar:** upload a CSV or JSONL trace, pick a pack, and optionally name the columns (id, text, kind, parent, actor, time). Columns are otherwise found by name.
- **Left pane (full height):** tabs for Overview, Who talked to whom (network graph and message pairs), Timeline (activity by hour with signal markers), Channels (how messages performed), Spread (program lanes and items seen then used), Early flag (harm still to come over time, with signals), Events (every record, searchable), and What's missing.
- **Right top:** the trace of the selected event. It shows a graph of its parent, children, messages in and out, then its identities, thread, channels touched, the same program elsewhere, and its full text. Click any record id, node or dot anywhere to trace it.
- **Right bottom:** the AI investigator ("AI Swarm Tracer"). Set the base URL, model and API key under Settings. The defaults are OpenCode Go (`https://opencode.ai/inference/go/openai/v1`, model `deepseek-v4.1-flash`); any OpenAI-compatible chat-completions endpoint works. Each question sends the system prompt (`ai_system_prompt.md`), an analysis brief, the selected event and any record ids named in the question. The key is used for that request only and is not written to disk. Keeping it for the browser session is optional.

### Any trace format

You can upload one file, several files, or a whole folder; the tool reads linked files together. Each file is read field by field:

- **Formats:** JSONL, a JSON array or `{"items": [...]}`-style JSON, CSV, and TSV.
- **Field names:** found automatically across common formats. These include flat event logs, wiki revisions and events, chat exports with a `messages` list (expanded into one event per message), OpenTelemetry-style spans (`span_id`, `parent_span_id`, `trace_id`), and LangSmith-style runs (`run_id`, `parent_run_id`).
- **Field chains:** actor, parent, channel and time are read through a chain of fields, record by record. For example, `label`, then `actor_label`, then the network address `ip16` as a last resort.
- **Missing text:** a record with no text field uses its other fields as its text.
- **Missing id:** a record with no id gets one from its file and line.
- **Duplicates:** records that only point at another loaded record (for example `save` events that reference a revision) are dropped.
- **Reference tables:** in a folder, files whose rows have no time and no parent (per-page or per-user summaries) are skipped.
- **Read report:** the Overview shows exactly how each file was read.

**Channels.** Each record's own page, thread, room or trace becomes a channel. Posting there reads what is already there and adds to it. Naming another page in the text counts as reading that page, which is how information spreads by reference. Pack patterns can add more channels, as the code-traces pack does for repositories and mailbox boards.

**Packs.** `generic.json` is a starting point for any trace. `code_traces.json` is for the Swarm Traces release. `wiki_swarm.json` is for wiki logs such as `full-wiki-logs/`. To analyze the wiki logs, upload the folder, or run:

```bash
python3 -m agenttrace serve --input full-wiki-logs --pack wiki_swarm.json
```

The server listens on 127.0.0.1 only. Uploaded files go to a private temporary folder and are removed when the server stops.

General analysis of agent traces: any CSV or JSONL file of records, with a rule pack that says what to look for. It produces one HTML report, a summary JSON, and a per-record CSV. It measures how accurate each rule is against hand labels.

Standard library only. Run from the project root.

## Commands

```bash
# 1. Analyze any trace file
python3 -m agenttrace analyze data.csv --pack agenttrace/packs/code_traces.json --out reports/data

# 2. Pick records to label (per tag, plus controls with no tag)
python3 -m agenttrace sample data.csv --pack agenttrace/packs/code_traces.json --out reports/data/labels.csv

# 3. Fill the label column: 1 = visible, 0 = not visible, blank = cannot tell
#    (for control rows: 1 = a behavior is visible that the tags missed)

# 4. Re-run with labels to get precision and recall in the report
python3 -m agenttrace analyze data.csv --pack agenttrace/packs/code_traces.json --out reports/data --labels reports/data/labels.csv

# Or only the numbers
python3 -m agenttrace precision reports/data/labels.csv
```

## Input

Any CSV or JSONL file. Columns are found by alias: `id`, `text` (also `content`, `body`, `message`), `kind` (`type`, `role`), `parent` (`parent_id`, `reply_to`), `actor` (`agent_id`, `sender`, `author`), `time` (`time_utc`, `timestamp`, `created_at`), `tool`. Name any column explicitly with `--map role=column`. In JSONL, a dotted path works: `--map actor=meta.agent`.

If there is no `id` or `text` column, the tool stops and says so.

## Packs

A pack is a JSON file. See `agenttrace/packs/`.

- `behaviors`: `{name, stage, pattern, flags?, context?, description?}`. A rule with `"context": true` is shown but never counted as evidence.
- `shared_names`: `{family, pattern}` for names that can carry information between runs.
- `handles` and `handle_families`: names that identify an actor or campaign in the text, and how to group them.

Two packs ship: `code_traces.json` (the swarm rules) and `chat.json` (a small example for chat logs).

### Reconstruction fields (all optional)

These drive who-talked-to-whom, spread, and the early-flag replay. A pack that leaves them out still gets replies between actors and the tag analysis.

- `action_kinds`: record kinds that are actions (for example `["payload"]` or `["assistant"]`). Identities, intents and harm only count in these. Other records still count as places where information is seen.
- `identity_patterns`: `{role, pattern}` with one capture group, the identity token (for example an auth credential). Used when there is no actor column.
- `variable_identity`: `{assign, use}` for tokens assigned to a variable and then used as identity. `assign` captures (variable, token); `use` is a regex with `{var}`.
- `info_patterns`: `{family, pattern}` for pieces of information that can spread, such as tokens or keys.
- `shared_names`: also used as places. Two identities using the same place in separate records is a coordination signal.
- `intents`: `{name, pattern}`, first match wins. This drives the hourly activity chart.
- `harm`: intents or evidence tags that count as harmful in the replay.
- `time`: `{embedded_epoch, window, min_points, min_spearman, max_p90_error_hours}`. When there is no time column, unix seconds in the text are fitted to file order within each block of one record kind. A block is timed only if it has enough timestamps, they rise with order, and the fit error stays under the limit. The report shows every block and whether it passed.

### What reconstruction reports

- Time and identity checks: what every other result depends on.
- Activity by hour, by intent.
- Identities by activity, with first and last time.
- Items seen as data and later used as an identity (spread), with the lead time.
- Carried-token links (one identity holds another's token before it is used), shared places, and replies.
- Early-flag replay: each signal's first time, and how much harmful activity and spread came after it.

## What the report shows

- Counts: records, threads, share with an evidence tag, share unattributed to an actor.
- Evidence tags, with precision and its 95% interval when labels are supplied.
- Context tags, separately.
- Stages.
- Recall on controls (records with no evidence tag): how many visibly contain behavior the tags missed.
- Actors, reply links between actors, and shared names that touch two or more actors, each with its evidence.
- Threads.
- What the data does not show.

## What it does not do

- It does not decide what the traces mean. The report states counts and measured accuracy; the reader draws conclusions.
- It does not detect behavior that the pack does not describe. The recall figure measures how much is missed.
- Precision is only as good as the labels. One labeler on small samples gives wide intervals.

## Tests

```bash
python3 -m unittest discover -s agenttrace/tests -t . -v
```

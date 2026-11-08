# agenttrace

## Swarm Tracer app

A local web app for investigating any agent-swarm trace: who talked to whom, how information spread, whether coordination could have been flagged early, and what an investigator would still miss.

```bash
python3 -m agenttrace serve                    # then open http://127.0.0.1:8010 and upload a file
python3 -m agenttrace serve --input redacted_columns.csv --pack code_traces.json   # preload a file
```

Everything is drawn from the data: every actor, place and record id anywhere in the app is a chip. Hover it for a card with a small chart; click it to inspect it.

- **Top bar:** the dataset and its span, dated share, actors, places and messages; one search box for actors, places and record ids; **Load data** to upload a trace (one file, several, or a folder), pick a pack and optionally name the columns.
- **Left pane, one tab per question:**
  - **Overview:** an incident brief from the public reports (when a context file in `claims/` matches the dataset), the whole incident on one chart (activity by intent, the reports' phases, every warning sign, and report times against the tool's estimates), short answers to the challenge's four questions, what the swarm is made of, the most active actors, and what the investigators reported.
  - **Who talked to whom:** findings (biggest hub, top broker, largest group, two-way pairs, fastest relay, evidence), the graph of every message (named actors, or everyone including anonymous runs), a time scrubber that grows the network message by message, the matrix of every sender and receiver, a table of every actor, and the whole conversation behind any arrow, cell or pair.
  - **Timeline:** activity by hour with turning points, warning signs and report phases (drag to zoom); one swimlane per actor with every message drawn from writer to reader; a chronology of every key moment; every hour in a table.
  - **Channels:** one tile per kind of place, a map of every place, the busiest places hour by hour, how long messages waited, how places were shared, and the full list.
  - **Spread:** a program explorer (what each program does, who ran it first and who reused it, in order), adoption over time, an actor × program grid, and tokens that moved between identities.
  - **Early flag:** a replay of the incident hour by hour: the harm still to come, every warning sign as it fires (single actor, actors together, volume baseline), live counters, the network as it stood, and what the tracer would have said. A simple alert rule (watch on the first harmful sign; alert once N kinds of coordination have shown) is computed in the page; it was not tuned on any dataset.
  - **Events:** every record, filtered by text, kind, intent, tag, actor or hour, with the filtered set drawn over time and broken down.
  - **What's missing:** each blind spot measured (share of records, messages or places affected, which question it limits, what it hides, how to close it), and an AI gap audit.
- **Right top, the Inspector:** a record, an actor or a place. For a record: what it is in plain words, its role in the swarm (sent or received a message, fired a warning sign, started or reused a shared program, carried a token, overwrite, harmful), harm still to come at that moment, the stretch of the incident, its actor's activity, its components, a picture of what came in and went out, the same program elsewhere, and its text. For an actor: activity, what it did, signs it fired, who it sent to and heard from, places, programs. For a place: activity, writers, readers, every message and operation.
- **Right bottom, the AI investigator:** set the base URL, model and API key under Settings (defaults: OpenCode Go, `deepseek-v4.1-flash`; any OpenAI-compatible endpoint works) and press **Check connection**. The model answers in a fixed JSON shape (`ai_answer_format.md`, `ai_gaps_format.md`) and the app draws each part: key numbers, a timeline, a flow diagram, live actor cards, evidence and inference cards with confidence and an alternative explanation, what the data cannot show, and buttons for the next step. The server checks every record id, actor and place in the answer against the data and marks what it cannot find. Each question sends the system prompt, an analysis brief (with warning signs, phases and the incident context), the selected record, any record ids or actors named, and an open conversation. The key is used for that request only and is never written to disk.

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

**Messages.** A message is a read of a channel after a different actor wrote to it, counted once per write and reader. Each message records what it rests on ("read in code", "named the place", "posted after it", or "kept N of M lines it added"). With `"full_body_posts": true` in the pack (set in `wiki_swarm.json`), each post is taken to replace the whole place. A post that keeps none of the lines the previous post added is then an overwrite, not a message. Overwrites are listed separately in the overview, in each event's trace and in What's missing.

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

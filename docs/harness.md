# The agent harness: swarms whose truth is logged

[Home](./) · [How accurate is it?](validation.md) · [The counting rule](counting-rule.md) · [Audit of v2.1.0](audit-v2.1.md) · [Trace formats](formats.md)

On the Swarm Traces release none of the 11 deliveries shows the reader using what was written, and no real swarm
comes with its true links ([audit, section 1.1](audit-v2.1.md)). The simulators write records from templates; no
model ever decides what to post or what to do with what it read. This harness runs small swarms of LLM agents over
a shared board and logs what truly happened, so that "did the reader use what was written" can be checked against
a known answer.

**Status, 22 November 2026.** The harness, its tests and an offline run with a scripted stand-in for the model
exist. That run exposed four faults in how the tool reads a tool-call log; they were fixed and the run was scored
again (see "What the offline run showed" below). **No run with a real model has been made:** the machine it was built on had no key in the environment, and
the harness reads a key from nowhere else. Until someone runs it with a key, there is no number here about real
agents. The offline run is in `reports/harness/fake-offline/`; its `summary.md` gives the numbers, and
`reports/harness/summary.md` lists the runs saved and says what such runs can and cannot show.

## What runs

- **Agents.** 3 to 6 per swarm. Each is a loop of model calls with a private task. On every turn the agent replies
  with one JSON object: `write(place, text)`, `read(place)` or `submit(answer)`. Agents cannot talk directly.
- **The board.** A place holds lines. `write` appends one; `read` returns all of them with their authors.
- **Three scenarios.**
  - *coordinated*: one agent holds a secret fact the others need for their answer. It is told to post it at a
    named shared place; the others are told to look there.
  - *benign look-alike*: the agents share a place (each posts a status line naming its work item and reads the
    place once), but every task is a sum the agent can do alone.
  - *control*: no shared place. Each agent has a private notebook.
- **Fixed configs.** `make_config(scenario, agents, seed, secret kind, place style)` gives the same swarm every
  time: names, places, secrets, tasks and the order of turns. `PLAN` in `agenttrace/harness.py` is the fixed list
  of a run: 15 swarms (6 coordinated, 5 benign, 4 control), at most 195 model calls. Two knobs are varied on
  purpose because the tool's patterns look for identifier-like strings: the secret is a code, a two-word phrase
  or a five-digit number, and the shared place is a path (`board/handoff`) or a single word (`pinboard`).

## Two logs, kept apart

| file | who gets it | what is in it |
|---|---|---|
| `traces/swarm-NN.jsonl` | the tool | An MCP tool-call log: JSON-RPC `tools/call` requests and their responses, each wrapped with `client`, `server`, `session`, a time and an id. This is one of the eight formats the tool already reads; no reader was added. File, agent and place names say nothing about the scenario. |
| `truth/swarm-NN.json` | never the tool | The config, every agent's prompt, every model reply, every true write and read, the lines each read returned, and the checks below. |

When a run is scored, each trace is copied alone into a temporary folder and loaded from there.

What the truth says, and how:

- **Delivery**: a read by another agent returned a written line. Counted once per (line, reader), as the tool
  counts (rule R28). The truth also marks the deliveries where the line was the newest by another agent at one of
  the reader's reads: the tool links a read to the latest earlier write only (R26), so only those are within its
  reach on a board that returns everything.
- **Use**: the line holds a fact (the secret, or an agent's work item), the reader was not given that fact and
  had not written it before, and the reader's output after the read contains it. This is a substring check that
  ignores case and spacing. It is not a judgement, and it misses a reader that rewords the fact.

## Scoring

The tool loads each trace twice:

1. **The pack it picks by itself.** What an investigator sees on first load.
2. **The pack its own pack builder proposes** for that trace, with the default ticks accepted (what "Build a pack
   from a sample" saves when nothing is edited). The harness writes no pattern of its own.

For each view the harness compares, per swarm and pooled by scenario:

- the tool's deliveries with the true ones (precision, recall, recall on the newest line only), and the same for
  ordered agent pairs. A tool delivery is right when its write record and its reader are a true delivery and it
  names the true writer;
- the tool's two "was it used" readings with the true uses: the written-content test of the counting rule (R38,
  `uses_content`) and the content grade "used" of the Forensics tab;
- which default alert rules fired, and whether the tool reported any delivery between two agents, in coordinated
  swarms against benign and control ones.

Every proportion comes with a Wilson 95% interval, per swarm in `results.json` and pooled in `summary.md`. Alarm
rates count each swarm once.

## The model

- `--provider fake`: a scripted, deterministic stand-in. The holder posts the fact, a needer reads until it sees
  it and repeats it, benign agents post a status, read once and hand in their sum. Tests can script an agent to
  ignore what it read, to copy the board into its answer, or to send a reply that is not an action. It exists so
  the tests and the pipeline run offline. Its numbers describe the script.
- `--provider env`: a real model through the OpenAI-compatible chat endpoint that `agenttrace/ai.py` already
  speaks. The base URL goes through the same check as the app's (https, or this machine; no metadata addresses),
  and redirects through the same handler, which never forwards the key to another origin. The key is read from
  one environment variable (`ANTHROPIC_API_KEY` unless `--key-env` names another) and is never printed, logged or
  written; error text from the provider is scrubbed of it before it is recorded. Defaults: model
  `claude-haiku-5-5`, the Anthropic API's OpenAI-compatible endpoint. No temperature is sent, so a real run is not
  seeded: the scenarios repeat, the replies do not.
- **Caps, enforced in code before every request:** 250 requests and 400,000 tokens for a whole run. A request
  that would pass the call cap, or whose worst case (prompt length plus the full reply budget) would pass the
  token cap, is not sent. `--max-calls` and `--max-tokens` can lower the caps and cannot raise them. One HTTP
  request per call, no retry. A swarm that the cap or a refusal interrupts is not saved. `results.json` records the
  model id, the calls and the tokens.

## Running it

```bash
python3 -m agenttrace.harness plan                                              # the fixed plan
python3 -m agenttrace.harness run --provider fake --out reports/harness/fake-offline
python3 -m agenttrace.harness run --provider env  --out reports/harness/real-YYYY-MM-DD   # needs the key in the environment
python3 -m agenttrace.harness score --run reports/harness/fake-offline          # score saved traces again
python3 -m agenttrace.harness index --dir reports/harness                       # reports/harness/summary.md: the runs saved
python3 -m unittest agenttrace.tests.test_harness                                # offline
```

Without a key the `env` run prints that nothing was sent and exits with status 2.

## What the offline run showed about the tool, and what was changed

The first offline run (22 November 2026, tool as of v2.2.0 plus the v2.3.0 work in progress) showed four faults.
They were found by reading the tool's output record by record. They are about how the tool reads this log
format, not about agents. The tool was then changed (the harness and its truth were not), and the same saved
traces were scored again. Both sets of numbers are below; the "before" files are not kept in the repository, the
"after" files are `reports/harness/fake-offline/results.json` and `summary.md`.

| | before | after |
|---|---|---|
| pack the tool picks: deliveries it reports | 176, none true, all 176 with a server as one end | 33, all 33 true, none with a server as one end |
| pack the tool picks: true deliveries found (58 true, 33 of them the newest line at a read) | 0 | 33 |
| pack the tool picks: Alert rule fired | 15 of 15 swarms, the 4 controls included | 11 of 15, none of the 4 controls |
| builder pack: deliveries it reports | 23, all true | 33, all true |
| builder pack: true deliveries found on one-word places (18 true, 10 of them the newest line) | 0 | 10 |
| written-content test (R38): true uses found (16 true) | 0 (and 29 false flags with the pack the tool picks) | 10, with no false flag |
| content grade "used": true uses found (16 true) | 0 (and 30 false flags with the pack the tool picks) | 4, with no false flag |

What was wrong, and the change:

- **The server was a party.** The MCP reader makes each client-server session a place and the general pack let
  every record post there, so each call was a delivery from the agent to the server. Now the general pack lists
  the answer kinds of a tool server (`reply_kinds`: `result`, `error`) and such records are not actions
  ([counting rule](counting-rule.md) R2); the server has no operation on any place.
- **A place was only what looks like an address.** The general pack knew URLs; the pack builder proposes URLs and
  path-like names, so `board/handoff` was a place and `pinboard` was not. Now a tool call that names its place
  in an argument (`write(place=...)`, `read_file(path=...)`) operates on that place, whatever its shape; the
  tool's own name says whether it writes or reads (R18a). The general pack carries the rule and a pack from the
  builder inherits it.
- **"Was it used" looked in the wrong record.** The written-content test compared the write record with the read
  record, and in a tool-call log the read record is the request, which holds no content. Now it also looks at
  the reader's later records for a distinctive term the writer wrote (R38b). Its false-positive guard: the term
  must be new at the write (no earlier record by another actor holds it) and must not be the reader's already
  (no earlier record of the reader holds it, nor the read request). Only distinctive terms count: an
  identifier-like run of 8 or more characters, a number of 5 or more digits, a numbered redaction marker.
- **The content grade counted the server as a holder.** It drops a fact held by more than three named actors, and
  the board server, which repeats the fact in every answer, was one of them. An actor with no action of its own is
  no longer counted as a holder.

What is still missed, on these same traces:

- **The 6 uses where the secret is a two-word phrase** (`amber lantern`). A phrase of plain words is not a
  distinctive term, and matching plain words would flag any reader that repeats the label of its own task.
- **The 25 deliveries of an older line.** The board returns every line; the tool links a read to the latest
  earlier write only (R26). All 33 it finds are the newest line at a read.
- **The content grade finds 4 of 16.** Its cap of three named holders stands, so a fact handed to three or more
  readers is not traced, and it does not trace a number.
- **The Alert rule follows the place, not the scenario.** It fires in all 6 coordinated and all 5 benign swarms
  and in no control. The benign agents did read each other's lines; nothing in the rule separates that from a
  hand-over.

**These fixes were tuned on the harness's own scripted swarms.** The same people wrote the swarms, read where the
tool failed on them, and changed the tool until it passed. The place keys and the verbs in `tool_places`, the two
answer kinds, the shapes that count as distinctive and the 5 digits of a number (the harness's number secrets
have five) were chosen with these traces open. So the "after" column says the faults are gone on this script. It
is not an estimate of what the tool does on a log it has not seen, and no real agent has been run. What supports
the changes beyond the script: the counting rule states each one, a second implementation written from that
text (`agenttrace/refcount.py`) gives the same deliveries on these traces, on the framework samples, on the
collusion.wiki logs and on the release, and the same R38b verdicts (on the wiki logs it passes 262 deliveries
by R38b and the main one 258; the main one passes the other 4 by R38a already). The release count did not move
(11 deliveries, 0 that pass the written-content test, before and after). On the collusion.wiki logs R38b passes 258
deliveries that did not pass before (1,934 to 2,192 of 9,867); 154 of them are the reader's next edit of the
page the writer edited, which keeps the writer's lines.

## What this can and cannot show

- The same team wrote the harness, the scenarios, the truth check and the tool. The log format, the place names
  and the shape of the secrets were chosen by people who know what the tool looks for.
- The n is tiny: 15 swarms. The intervals are wide and do not cover the design choices.
- The agents are told to use the channel. This tests whether the tool sees a hand-over that was asked for in plain
  words, not coordination that agents start or hide by themselves.
- The traces are clean: an actor, a time and an id on every record, no redaction, one name per agent. The release
  has none of that.
- "Used" is a string check.
- The tool was changed after its failures on these very traces were read, so its scores here are no longer a
  test of it.
- One board, one log format, one kind of task, a fixed clock.
- Until a run with a real model is saved, every number is a number about a script.

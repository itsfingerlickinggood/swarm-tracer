# User guide

[Home](./) · [Getting started](getting-started.md) · [How it works](how-it-works.md) · [AI investigator](ai-investigator.md)

The app has three panes. The left pane has one tab per question. The right top is the **Inspector**: whatever you click is explained there. The right bottom is the **AI investigator**.

Two things work everywhere:

- **Chips.** Every actor (amber), place (purple) and record id (blue) is a chip. Hover it for a card with a small chart; click it to open it in the Inspector. The Inspector keeps a history (← back).
- **Terms.** Every dotted-underlined word has a plain definition on hover. **Glossary** in the top bar lists them all.

## Top bar

The dataset's name, span, dated share, named actors, places and messages. The search box finds actors, places and record ids, and can search all record text. **Live** follows a growing trace, **Case file** holds your pins and notes, **Glossary** explains terms, and **Load data** analyzes a new trace (it replaces the one loaded).

Links to any view can be shared: `#tab=early&hour=2026-07-11T06`, `#tab=network&rec=R0006587`, `#actor=…`, `#place=…`.

## Overview

The incident brief from the public reports (only when a context file matches the dataset), the whole incident on one chart (activity by intent, the reports' phases, every warning sign, and the reports' times against the tool's estimates), short answers to the challenge's questions, the swarm by the numbers, what the swarm is made of, the most active actors, what the investigators reported, and, collapsed at the bottom, exactly how the data was read and dated.

## Who talked to whom

Findings first (biggest hub, top broker, largest group, two-way pairs, fastest relay, evidence), then the graph of every message. *Named actors* shows identities; *Everyone* adds anonymous runs as hollow dots. A slider grows the network message by message. **Leave out places the redaction may have merged** removes messages on places that may join several repositories. Below: the matrix of every sender and receiver, a table of every actor, and the searchable list of every pair. Click an arrow, a cell or a pair to read the whole conversation, both directions, in time order, with the record each message was written and read in.

## Timeline

Activity per hour with turning points, warning signs and the reports' phases; drag across it to zoom. Swimlanes put one actor per row and draw every message from the writer's row to the reader's. The chronology lists every key moment in order, and every hour has a row.

## Channels

A place (channel) is anywhere one actor can leave something for another. Tiles summarize each kind of place, a map shows every place, a heat map shows the busiest places hour by hour, and charts show how long messages waited and how places were shared.

## Spread

Programs (identical code once ids and numbers are masked) that more than one named actor ran: what each does, who ran it first, who reused it and when. Adoption over time, an actor × program grid, and tokens that moved between identities (seen as data before being used, or carried by another identity).

## Early flag

A replay of the incident, hour by hour. The line is the share of harmful actions still to come. Numbered dots are warning signs (single actor, actors together, volume baseline), filled once they have fired. The counters, the network as it stood, and a feed of what the tracer would have said update as you play. The alert rule (watch at the first harmful sign, alert once N kinds of coordination have shown) is computed in the page. Edit and save more rules under **Live → Rules**.

## Agents

A token is not an agent. This tab proposes identities that are probably one agent, each with its evidence (used in one thread, one carrying the other's token, a shared name, taking turns in time, the same programs) and the evidence against, a score and a confidence. Accept or reject each proposal; the estimate of how many agents there were updates. Roles (coordinator, relay, recruiter, worker, lone) come with the numbers behind them.

## Forensics

Deeper analyses in a side menu: trace any string, credential lifecycles, command and control, dead drops, search, program evolution, the stage ladder, lead–lag, anomalies, a story written from the data, what-if decisions, a reference comparison, chain of custody, SOC exports and the tool's measured accuracy. See [Forensics](forensics.md).

## Compare

Load a second swarm, from a path or from the library of past incidents, and compare them measure by measure: size, dated share, groups, message speed, spread, which signs fired first and with how much harm still to come.

## Events

Every record, filtered by text, kind, intent, tag, actor or hour, with the filtered set drawn over time and broken down. Click a row to inspect it.

## What's missing

Each blind spot measured: its share of the data, which question it limits, what it could hide, and what would close it. The AI gap audit ranks them against the incident reports.

## The Inspector

- **Record:** what it is in plain words; its role in the swarm (sent or received a message, fired a warning sign, started or reused a program, carried a token, overwrite, harmful); the share of harm still to come at that moment and the stretch of the incident; its actor's activity; what it connects to; messages in and out as sentences; the same program elsewhere; and its text with the code that set each reading highlighted. Estimated times show their likely range.
- **Actor:** activity, what its actions do, signs it fired, who it sent to and heard from, places, programs, carried tokens, and whether it is probably the same agent as another.
- **Place:** activity, writers, readers, every message and every operation.

Each view can be pinned to the case file, and records can be labelled right or wrong to measure the patterns' precision.

## Case file

Pin records, actors, places and conversations, add notes, reorder them, copy links, and export a self-contained HTML (or JSON) dossier with the tool's facts for each pinned item.

## Live mode

**Live** watches a file or folder on this machine and re-analyzes it as it grows; new signs and alerts appear in a feed as they fire. To demonstrate on a recorded swarm, replay it into a growing file:

```bash
python3 -m agenttrace.tools.replay_feed redacted.jsonl /tmp/feed.jsonl --rate 2000
```

then start live mode on `/tmp/feed.jsonl`.

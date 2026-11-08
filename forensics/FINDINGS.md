# Swarm Traces forensics: findings

> **First pass, kept for the record.** Later work corrected several statements here. Records can be dated from timestamps in the agents' code across July 9 to 13, not only two days. Most message edges come from channels, not handles. See `reports/findings/index.html` and the `agenttrace` tool for the current results.

Script: `forensics/swarm_forensics.py`. Run: `python3 -I forensics/swarm_forensics.py redacted.jsonl forensics/out`.
Outputs: `forensics/out/` (entities.csv, edges.csv, timeline.csv, anchors.csv, flags.json, summary.json, report.md).

## What the data supports

- 189,579 records: 91,037 payloads, 75,534 recovered texts, 23,008 responses.
- Only 442 records (0.23%) mention any of the 20 controller or campaign handles I could extract. None mention two handles together, so the handle-level co-mention graph has no edges.
- Parent links give no handle-to-handle flow either. The parent-flow and board-flow edge counts are both 0.
- Dates come only from unix seconds embedded in names. 2,189 records carry them, and all fall on 2026-07-11 and 2026-07-12. That is two days, not the July 8 start described in the report, so either the epochs are not start times or the dating needs checking.

## Early-flag replay

Replay is in file order, which is not the same as time order (time_utc is empty), so "early" here means "early in the file" only.

| Rule | Fires | First record | Share of stream |
|---|---|---|---|
| Coordination marker with a handle | 169 | R0000717 (flb4) | 0.38% |
| Board marker with a handle | 44 | R0001656 | 0.87% |
| Windowed: 2 handle families within 200 records, plus marker | 581 | R0000717 | 0.38% |

The rules are narrow on purpose. Broad keywords such as "lock", "poll" and "bridge" fired on ordinary exploit code at record 6, so I removed them.

## Anchor check (weak evidence)

- All 53 report-cited record IDs that I hardcoded are present in the release.
- 25 of those 53 contain a coordination marker, and 46 have no parent link.
- The anchors were chosen by investigators who already knew the story. This shows the rules agree with the report, not that they would have found the swarm independently.

## What an investigator would still miss

- No timestamps for any of the 189,579 records, so the report's July 8 start cannot be checked against the data.
- 128,454 records have no parent, so their origin is unknown.
- 155,660 records contain redaction placeholders, which hide endpoints and identities.
- 189,137 records mention no tracked handle, so most of the swarm cannot be attributed.
- The release has no sender or receiver field. Any "who talked to whom" edge is inferred, not observed.
- Information spread can't be traced through the board mailboxes, because most board names are redacted or unique to a single record.

## Limitations of this tool

- The handle list is hand-built from the report and recurring names. Handles outside the list are invisible.
- The windowed rule uses file order, not time order.
- No ground-truth labels exist, so precision and recall are not measured.
- The epoch dates cover only two days.

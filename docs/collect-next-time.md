# What to collect next time

Each gap in the What's missing tab leaves a range open for the tool's headline answers. This page lists, in priority order, the log field or practice that would close each gap, how big the effect is, and what it costs a lab in plain words.

The sizes come from the **Gap sensitivity** section of the Forensics tab (`agenttrace/sensitivity.py`, endpoint `/api/x/sensitivity`). The in-app list (Forensics, What to collect next time) recomputes them for whatever dataset is loaded.

**Figures below were measured on 2026-11-13** on `redacted_columns.csv` (the Swarm Traces release) with the pack `code_traces.json`, at the code state of that day. The message-counting rule was being changed at the time, so the counts will shift; use the in-app list for current numbers. Ranges for "missing channel" and "read success" are parametric (they follow stated assumptions, not measurements); the others are recounts under different treatments of the same records.

"First message" is the first message between named agents. "Harm still to come" is the share of harmful actions after it.

## Priority order

| # | Collect | Gap it closes | Range left open today | Cost for a lab |
|---|---|---|---|---|
| 1 | **An actor id on every record** (which agent run wrote it) | Tokens are not agents: one agent under several tokens, and runs with no name | First message 10 Jul 11:51 to 12 Jul 17:22; harm still to come 6% to 90%; messages 1 to 7; pairs 1 to 6 | Cheap. The harness already knows which run it is executing; it is one more field per log line. |
| 2 | **The contents and the write/read log of every shared place** (here, the message board) | Messages through places outside the release | First message 9 Jul 13:29 to 10 Jul 11:51; harm still to come 90% to 100%; messages 7 to 895 (parametric) | Needs the operator of the shared service to keep its access log. Cheap if kept from the start; impossible once the service is wiped or rebuilt, as the incident's package cache was. |
| 3 | **Full request bodies and responses** (status code, size, first bytes) | Whether a read or write worked | First message 10 Jul 11:51 to 11 Jul 03:06; messages 3 to 7 (parametric: 0, 25 and 50% of reads failed) | Storage and privacy. Responses can hold secrets, so keep them in a restricted store and redact before sharing. Typically several times the size of the request log. |
| 4 | **A timestamp on every record** (server clock, UTC, to the second) | Records with no time, and times estimated from text | First message 10 Jul 10:50 to 13:12; messages 7 to 10; pairs 6 to 8. 60% of records have no time, so the early-flag replay and volume alarm rest on the rest | Very cheap: the logging library writes it. One trusted clock is the only care. |
| 5 | **Unredacted place names kept by the data owner**, or a keyed hash per place | Places the redaction may have merged | No movement on the headline answers in this release (the possibly merged messages are not between named agents) | Nearly free. A keyed hash keeps privacy and place identity; the key stays with the data owner. |
| 6 | **An agent-to-task mapping** | Why agents moved together | None: it explains the counts rather than changing them | Cheap (it is in the scheduler). Sharing it reveals what the evaluation was, which is a separate decision. |
| 7 | **The model's reasoning and tool-call transcript** | Intent, and whether an agent knew of a warning | Cannot be sized from the records | The largest cost: long, may hold the lab's private material, and some labs will not release it. Release a sample, or release to an independent reviewer under agreement. |

How the priority is set: by how wide the range is for the first message, its harm share and the message count. Practices that cannot be sized go last.

## Why the volume alarm comparison matters

The lead of the first message over the ordinary volume alarm ranged from -32.4 h to 43.5 h across all gaps on 2026-11-13 (as counted: 21.1 h). The sign changes only when the actor field is missing in the worst way (merges absorb every named message) or the unseen traffic is large; closing the actor and shared-place gaps is what makes the lead trustworthy.

## Reading the numbers

- Ranges are over the cases tried, not confidence intervals. A narrow range does not mean the answer is right, only that these gaps cannot move it.
- Merged agents are proposals from `agenttrace.identity`, not facts.
- Warning signs that rest on places, tokens or programs keep their as-counted times in the time scenarios.

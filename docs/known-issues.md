# Known issues

[Home](./) · [Limits and dual use](limitations.md) · [How accurate is it?](validation.md)

Honest list of what is known to be wrong, weak or untested, kept up to date.

## Accuracy
- **Messages that only name a place.** A note that mentions a board or dataset without reading it can be counted as a read. On simulated swarms this is the main source of false messages (precision about 49% when such notes are common, 76% when they are not). See [validation](validation.md).
- **Coordination signs can fire early.** On simulated swarms the first-message and group signs usually fire before the first true message, because a false message comes first.
- **Program reuse fires on boilerplate.** Agents that share a template (for example the same submission code) trigger "program reused" even when they never coordinate. The benign swarms show this in 10 of 10 runs.
- **The harm list is broad.** In the code-traces pack every Hugging Face dataset commit counts as harm.
- **Identity merges at low confidence are rarely right** (about 1% on simulated swarms). Treat low as "worth a look". High and medium require direct evidence and were right in every simulated case.
- **Comments are matched like code.** An intent pattern can fire on a commented-out line.

## Untested
- **The AI investigator has not been run against a real model** in this project; every path is tested against stand-in providers.
- **Framework readers** (OpenTelemetry, LangSmith, Langfuse, AutoGen, CrewAI, OpenAI Agents SDK, MCP) are tested on samples written to match each format, not on real exports.

## Product
- **Large swarms draw slowly.** On thousands of actors the network graph is dense and some charts cap what they draw (they say so).
- **A pack can hold a slow regular expression.** A badly written pattern can tie up the server; there is no time limit on patterns yet.
- **Path refusals on macOS** mention "a link" for temporary folders under `/var`, which is confusing.

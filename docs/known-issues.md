# Known issues

[Home](./) · [Limits and dual use](limitations.md) · [How accurate is it?](validation.md)

Honest list of what is known to be wrong, weak or untested, kept up to date.

## Accuracy
- **Messages that only name a place.** Fixed for code comments: a place named only in a comment no longer counts as a read (simulated message precision 66% → 79%). A place named in a printed string or a variable that is never fetched can still count. See [validation](validation.md).
- **Coordination signs can fire early.** On simulated swarms the first message is now within an hour of the truth in 40 of 40 swarms; groups of 20+ still fire early in some, because a false message joins two groups.
- **Program reuse and boilerplate.** Fixed: reuse counts as a sign only when the program writes, reads a place another actor wrote, or does harm (benign swarms: 10 of 10 → 0 of 10). Two agents that run the same attack code without contact still fire it.
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

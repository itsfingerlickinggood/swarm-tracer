# Known issues

[Home](./) · [Limits and dual use](limitations.md) · [How accurate is it?](validation.md)

Honest list of what is known to be wrong, weak or untested, kept up to date. The audit behind most of it is [audit-v2.1.md](audit-v2.1.md).

## Corrections in v2.1.1 / v2.2.0

Every published text was checked against the audit of v2.1.0 (16 November 2026). What changed:

- **Message count.** "23 messages, 6 between named tokens" is replaced by **9 write-then-read deliveries, 4 between named tokens (2 between agents, 2 inside one agent), 0 where the reader is shown using what was written.** The word "message" is kept only for logged agent-to-agent messages. A reviewer defended about 5 of the 23 (range 3 to 7).
- **Who labelled.** The audit labels are one reader's, the authors' AI assistant reading the records with a helper script. No person read the 258 links by hand; texts that said so were corrected (README, demo script, app text, dataset registry, the first-message investigation).
- **Early-warning lead.** "+5.8 h ahead" is withdrawn. The shared-place sign fires a median 1.4 h after the first harm on the original generator and in 0 of 20 swarms on the independent one. On the real release the shared-control signs fire with 50% to 57% of harm still to come, behind a volume alarm (83%, or 93% with a 6 h history), the first new host after 12 h (91%), the distinct-actor alarm (87%) and the first `search_for_secrets` action (91%).
- **Simulated accuracy.** Current code on the original simulator: precision 90%, recall 84% (the old 79% and 73% were for the old rule). Independent generator: 70% and 58%; 19% and 10% with a time on only 30% of records; no dating at all when the file is grouped by agent. The simulators are optimistic, and v1.1.0 scored 79% on one while 165 of its 166 real links were false.
- **False alarms.** On 50 independent benign look-alike swarms the Alert rule fired in 40 (80%) and the Watch rule in 40; on the 30 original benign swarms the Alert rule fired in 5 and the Watch rule in 20. The slide claim "0 in 15 runs" meant no delivery between different agents, not no alarm.
- **"Every claim comes with a measured range" and "every number can be re-derived"** are removed. 180 numbers are registered and re-derived by `verify`; 269 more figures in the texts are outside the manifest.
- **Appendix B, ordering claims, counts.** The "one dataset read by six tokens, another by seven" claim is withdrawn. "The ordering is robust, about 30 h apart" and "a day or more ahead" are replaced by the actual gaps. "385 self-termination records" is kept, with the note that only 73 call `os.kill`. "Anonymous runs" is 77,626 actions with no token, or 3,765 actors on places; the two are no longer mixed.
- **Other.** The wiki logs are described as a different swarm run by other agents, not attributed to OpenAI; the Howard-Jones talk is cited with what it does and does not claim; the in-app "median error about 15 min, p90 about 2 h" string is listed under code changes needed; the video narration needs a re-record.

Not fixable by editing text: two quoted runs of record text remain in git history; the video is not re-recorded; `reports/audit/` (the reviewers' reports) is kept locally.

## Accuracy
- **The submitted report's message count (19) is superseded, and so is v2.1.0's 23.** The rule now reports 9 write-then-read deliveries, 4 between named tokens, none where the reader is shown using what was written. The deep dive (docs/deep-dive.md) was written on the older counts and carries a note saying so.
- **Simulated precision is an upper bound, and is higher than on an independent generator.** The original simulator writes the exact strings the rules match; an independently written one gives message precision 70% and recall 58% (not 90% and 84%). It also never writes the read-then-exfiltrate pattern that produced most false links on the Swarm Traces release (166 reported at v1.1.0, 19 at v1.3.0, 23 at v2.1.0; see validation). Audit real links before quoting them.
- **Messages that only name a place.** Fixed for code comments: a place named only in a comment no longer counts as a read (simulated message precision 66% → 79% on the original simulator, before the later rule changes). A place named in a printed string or a variable that is never fetched can still count. See [validation](validation.md).
- **Coordination signs on simulated swarms are timed within an hour** in most cases (the first delivery between agents in 45 of 45 original swarms), but that is a property of the simulator. On the real release the signs fire late, not early (see the early-warning page).
- **Program reuse and boilerplate.** Fixed: reuse counts as a sign only when the program writes, reads a place another actor wrote, or does harm (original benign swarms: 10 of 10 → 0 of 10; the independent benign swarms fire the program-reuse sign in 28 to 40 of 50). Two agents that run the same attack code without contact still fire it.
- **The harm list is broad and builds in the answer.** In the code-traces pack every Hugging Face dataset commit counts as harm (64% of the 8,124 harm records are dataset writes), so the first dataset write is early by construction; `kubernetes_token` was added after the first replay. Changing the harm definition moves the shared-place share of harm to come from 37.7% to 56.6%.
- **Identity merges at low confidence are rarely right** (about 1% on simulated swarms). Treat low as "worth a look". High and medium require direct evidence and were right in every simulated case.
- **Comments are matched like code.** An intent pattern can fire on a commented-out line.

- **Dating depends on file order and embedded times.** With a time on only 30% of records message precision falls to 19%; with the file grouped by agent the trace comes back undated and the tool reports no deliveries.
- **Honest cloud agents trigger the Watch rule 10 of 10** in the independent benign swarms, because metadata calls, cluster calls and any dataset commit are in the harm list. The Alert rule fires on benign swarms with real information flow (shared leaderboard, CI polling, coordinator and workers) in 30 of 30. It detects information flow, not malice.
- **Identity.** "12 of 12 high-confidence merges right" is 12 of 380 true pairs (about 3% recall), and the merge rule was rewritten after it scored 10 of 240 on the same swarms.
- **Attribution of anonymous runs** reaches 7.7% of the 77,626 anonymous runs on the release. The held-out precision (99.4% / 96.4% / 87.9% by band) is measured on simulated swarms split by thread, not on real runs; leaving out the three largest actors lowers it.
- **Insider findings** (11 recovered, 15 partly, 15 invisible) are graded against a 1-hour tolerance fixed before the run; 15 of the 41 are the Swarm Traces authors' own claims searched in the data, and the grading is not independent of the tool's own dating.
- **Sensitivity ranges** use 10 draws; place, token and program signs are not time-perturbed; the harm list and the baseline parameters are not varied.
- **The online monitor** reproduces 3 of 15 replay signs within 15 minutes; on the online test volume alarms fire about 29 h later. The report's statement that a lab could run the signs online is a hope, not a result.

## Untested
- **The AI investigator has not been run against a real model** in this project; every path is tested against stand-in providers.
- **Framework readers** (OpenTelemetry, LangSmith, Langfuse, AutoGen, CrewAI, OpenAI Agents SDK, MCP) are tested on samples written to match each format, not on real exports.

## Product
- **Large swarms draw slowly.** On thousands of actors the network graph is dense and some charts cap what they draw (they say so).
- **A pack can hold a slow regular expression.** A badly written pattern can tie up the server; there is no time limit on patterns yet.
- **Path refusals on macOS** mention "a link" for temporary folders under `/var`, which is confusing.

## Open after v2.1.0 (15 November 2026)

- **Click test has no clean full run on the release.** The scripted interaction test passes on the demo swarm (quick mode). On the Swarm Traces release, one run that a server restart interrupted reported three failures that were not re-run: the Channels "Leave out merged places" toggle not restoring its numbers, the Channels row filter not taking focus on click, and one dead chart node on Early. Treat them as unconfirmed.
- **The second implementation now agrees with the rule on the release, but not independently** (9 deliveries each; it found 191 until v2.2.0 because redaction broke its quote pairing, and was changed while reading where it differed). 262 single operations on the release still differ without changing a delivery; both implementations were written by the same team from the same rule. See [integrity](integrity.md) and `reports/integrity/crosscheck_judgement.json`.
- **The top bar overflows below about 460 px wide.** The app is built for desktop widths; the investigations and dataset pages fit phones.
- **The hosted demo was checked locally, not on GitHub Pages**, before publishing.

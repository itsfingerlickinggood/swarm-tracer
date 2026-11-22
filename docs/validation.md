# How accurate is the tool?

[Home](./) · [How it works](how-it-works.md) · [Limits](limitations.md) · [Command line](cli.md) · [API](api.md)

Swarm Tracer's hard claims (who messaged whom, when each warning sign appeared, when an undated record happened, which tokens are one agent) can only be checked against a swarm whose truth is known. No real swarm comes with that, so we simulate swarms, keep the truth, load each one with the tool exactly as the app loads a file, and compare. This page gives the results as **ranges over seeds** (min – **median** – max), not one number, and adds the project's first **benign baseline**: swarms that never coordinate, where everything the tool flags is a false positive.

**Read the simulated numbers as optimistic.** The generator was written by the same team as the tool and writes the exact strings the rules match. An independently written generator (section [Independent generator](#independent-generator-agenttraceindepgenpy), inside Results) gives message precision about 70% and recall about 58% where this page's original swarms give 90% and 84%, and v1.1.0 scored 79% on the original simulator while 165 of its 166 links on the real release were false. Not every number on this page comes with a range, and none of the simulated ones is accuracy on real data.

**Since v2.3.0 there are measurements on real data too**, against what four public datasets themselves record: [Measured on four outside datasets](#measured-on-four-outside-datasets-v230). In short: pairs of agents that talked are mostly recovered where the log has structure, single messages are not, the alarms fire on almost every run with no attack in it, and reading the tool's flags as blame for a failure is at chance. Read that section before the simulated tables.

Reproduce everything on this page (about 15 seconds, standard library only):

```
python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5
```

It writes `reports/validation/summary.json` (every run and every range), `summary.md` (the tables below) and the generated swarms. In the app, **Forensics → Test and export → How accurate is the tool?** draws the same tables as range bars, and can run a quick check (one seed, 20 agents) without a terminal. `GET /api/x/validation_summary` returns the latest saved summary.

## Method

**The simulated swarms** (`agenttrace.groundtruth make`) are code-like traces in the style of the Swarm Traces release. Each agent authenticates with its own identity token; some hold two. After a stretch of solo work, agents join the coordination one by one: they leave messages on shared registry folders and datasets and read one another's messages (each read fetches one named message, usually the newest), so every true message is a known (write record, read record) pair. Harmful actions (cloud metadata, cluster calls) come later. Three kinds of noise are built in: notes that name a place without reading it, reads whose address is assembled from pieces the patterns cannot see, and timestamps embedded in only some records (the rest must be estimated), unless every record has a time field.

**The settings** (each with seeds 1–5, so 45 coordinated swarms of 660–3,260 records each):

| setting | what changes |
|---|---|
| 40 agents, defaults | 12% of agents hold two tokens; 8% of reads hidden; a few place-naming notes per agent; times embedded in 60% of records |
| 20 agents / 80 agents | swarm size |
| 35% hold two tokens | many more agents with a second identity |
| 25% of reads hidden | more messages the patterns cannot see |
| many place-naming notes | notes that name a place without reading it, about 5 per agent |
| no hidden reads, no notes | the clean case |
| a time field on every record | nothing has to be estimated |
| real-world payload patterns | 60% of dataset reads and writes use the code shapes found when the real release's links were audited (below): a GET of a place followed by a POST of the result to a collector or a commit to a different dataset, LFS batch downloads (a POST that only fetches), Python `urlopen(url)` reads and `urlopen(Request(url, data))` writes, a URL kept in a variable and used by a later `fetch(u, {method:'POST'})`, several places in one record, proxy-prefixed URLs. It adds places whose path the redaction swallowed and several repositories under one owner. The truth stays exact. |

**The benign baseline** (`groundtruth make --mode benign`, 3 settings × 5 seeds): 40 agents work in parallel sessions on their own tasks over the same 36 hours. They submit work to an evaluation API (the same boilerplate program for everyone), read public reference datasets that nobody in the swarm writes, and, in the first benign setting, half of them save results to a dataset of their own and read them back. No agent ever reads what another wrote, no token is carried, and the truth has **no messages between agents and no harmful records**. The second benign setting is read-only (no agent writes anywhere). The third uses the real-world payload patterns with nothing coordinated behind them: an agent fetches a public reference and sends it on with its own submission, downloads through LFS, reads with Python, and saves to its own dataset. A small benign swarm with its truth file ships in `agenttrace/samples/benign_swarm/` (12 agents, 361 records).

**What is scored** for each swarm:

- **Message links**: precision and recall of the tool's (write record → read record) messages, and of the pairs of agents those messages join (the tool's actors mapped back to the true agents).
- **Early signs**: for every sign the replay names (first message, first two-way exchange, groups of 3/5/10/20 agents, first harmful action of each kind), the truth's time for the same sign; the tool's error in hours and whether it is within one hour.
- **Dating**: for records whose time the tool estimated, the error against the true time, and the share that falls inside the range the tool states for that block (its 90th-percentile fit error), i.e. whether the stated uncertainty is honest.
- **Identity merges**: every pair the Agents tab proposes (`agenttrace.identity`, saved accept/reject decisions ignored), checked against which tokens truly belong to one agent: precision per confidence band (high, medium, low) and recall. We also measure a what-if rule on the same proposals: keep a pair only when it rests on *direct* evidence (both tokens in one record, in one small thread, or one carrying the other's token).
- **Default alert rules** (`agenttrace.live`, the three built-in rules): on coordinated swarms, when they fire relative to the first true message and the first true harmful action; on benign swarms, whether they fire at all.

## Headline

- **On real data the first three counts were wrong, and audits fixed the rule.** We read every link between named tokens that v1.1.0 reported on the Swarm Traces release (166) and every one the code at v1.3.0 reported (19): 178 links, of which one was a message by our reading. The rule was changed and re-scored against those labels, which gave 23 (6 between named tokens) at v2.1.0. Four independent reviewers then read the 23 and would defend about 5 of them (range 3 to 7): 10 of the 23 rested on one LFS upload probe of a file whose download had been requested 34,000 s earlier, one reader looped over a token list that contained the writer's own token, and two were cut mid-verb. The v2.2.0 rule dropped those and counted 9. The v2.3.0 rule reports **11 write-then-read deliveries, 4 between named tokens (2 between agents, 2 inside one agent), 0 where the reader is shown using what was written**: the two added are one commit that the release cut into two records, counted again now that the two are read as one (R13a). The labels are **one reader's, the authors' AI assistant, reading the records with a helper script**; nobody double-labelled them, and no person read the 258 links by hand (earlier versions of this page said so; that was wrong). On the audit the 11 score 5 of 5 decidable (6 are unclear; 95% range 57%–100%), but the labels for 13 links were changed in the same commit as the v2.2.0 rule, so this is in-sample, and the two links added in v2.3.0 have not been judged as joined text. See [Audited links on the real release](#audited-links-on-the-real-release).
- **Messages, simulated (original simulator; the independent generator is lower)**: across the 45 coordinated swarms the tool finds 66%–**84%**–93% of the true messages, and 82%–**90%**–96% of the messages it reports are true. Pairs of agents: 73%–**90%**–96% recall, 89%–**95%**–99% precision. On the independent generator (file in time order, times on 60% of records) message precision is 70% and recall 58%; with a time on only 30% of records 19% and 10%; with the file grouped by agent nothing can be dated and no delivery is reported.
- **On the original simulator, harmful-action signs are exact**: first dataset write, first cluster call, first cloud-metadata call and first registry board are found in 45 of 45 swarms within an hour; the first delivery between agents is within an hour in 45 of 45, groups of 3/5/10 in 39–43 of 45, the first two-way exchange in 34 of 45. That is a property of the simulator, which writes the strings the signs look for. On the independent generator the Alert rule fires a median 4.7 h after the first true harm, the Watch rule 0.2 h before it, and the shared-place sign fires in none of 20 coordinated swarms.
- **Dating is good on the simulator when the file is in time order and timestamps are embedded**: median error about 1 minute (0.01–0.03 h), 90th percentile 3–7 minutes; 84%–**87%**–91% of estimated times fall inside the stated 90% range (slightly under the 90% it promises). That is a property of the simulator, not a measurement on the release. The estimate depends on file order and on how many records carry a time; see the independent generator below.
- **Identity merging, before and after a fix.** The first version labelled pairs **high** on coordination evidence alone (a shared place, handoffs, shared programs); pooled over the first swarms those were right **4% of the time (10 of 240)**. The rule was then rewritten, on the same swarms, to require direct evidence (the same record, a small shared thread, or a carried token) for high and medium. After the change, pooled over all 60 swarms: **high 12 of 12 right, medium 60 of 60**, but the 12 high ones are about 3% of the 380 true pairs (recall), and the rest stay low (about 1% right), so the low band should be read as "worth a look", not as a merge.
- **On the original benign swarms**: the tool reports **no** delivery between two different agents (0 in all 15, including the 5 with real-world payload patterns, where v1.1.0's rules report 282); that is a statement about the benign generator, which never produces boards, metadata calls or shared writers. The default rules fire: "Watch: first harmful sign" in 10 of 15 (every swarm whose agents save results: the code-traces pack counts any dataset commit as harmful), "Alert: 2 kinds of coordination" in 2 of 15, and the volume baseline in 6 of 15. On the 30 benign swarms of the earlier forward test the Alert rule fired in 5 and Watch in 20. **On 50 independent benign look-alike swarms the Alert rule fired in 39 to 40 (78% to 80%): in all 30 where agents share a leaderboard, poll a CI status dataset or hand tasks through a coordinator, and in 9 of 10 honest cloud-agent swarms.** It detects information flow, not malice. The slide figure "0 in 15 runs" meant no delivery between different agents, not no alarm. **On real runs with no recorded attack (v2.3.0) the Alert rule fired in 181 of 184 (Who&When), 1,567 of 1,640 (MAST-Data) and 40 of 40 (Moltbook communities).**

### The fixes this suite and a manual audit led to

1. **A place named only in a code comment is not a read.** Notes such as `// the crew says <dataset> has the plan; not fetching it yet` were counted as reads, and the harm patterns matched them too ("first registry board" fired a median 9 hours early). Mentions inside a comment (a line starting with `//`, `#`, `/*` or `*`, or a `//` / `# ` after whitespace) no longer count as reads, writes or actions. Message precision on the original simulator rose from 66% to 79% (median, before the later rule changes; it is 90% now) and the registry-board sign moved to within an hour of the truth in 40 of 40 swarms then (45 of 45 now). The "66% to 79%" comparison has no saved run behind it: the 66% run was not kept, so treat it as a recollection of the first run, not a result.
2. **The verb nearest the mention decides, and the window stops at the next place.** A reading of the earliest links on the Swarm Traces release found three artefacts the simulations do not have: a GET followed within 260 characters by a POST to a *different* dataset was charged as a write to the first; an LFS batch with `operation:'download'` (a POST) was taken for a write; and the redaction's `[REDACTED:username:N]] REPO K]` kept a repository number the place pattern dropped, so writes and reads of different repositories under one owner looked like one place. With the nearest request verb deciding, read verbs (GET, HEAD, LFS download) recognised, the code window clipped at the next place mention, and the repository number kept, the named messages on the release fell from 166 to 107. A second audit of those 107 found that most were two tokens fetching the same dataset and POSTing what they read to a collector: the POST, the nearest verb, made the read a write. Clipping the window at the start of the next request call (`fetch(`, `.open(`, `urlopen(`, `requests.post(` …) and recognising `urlopen`/`.read()` as reads leaves **19 messages in 12 pairs among 9 tokens** (a Python `urlopen(url)` with one argument is a read; `urlopen(Request(url, data))` is a write). The simulated scores did not move, which is itself a finding: the simulator lacked these artefacts. **Correction (2026-11-13):** an earlier version of this page said the 19 were each checked by hand. A full audit of all 178 links, with the two records of each read side by side, does not support them: see [Audited links on the real release](#audited-links-on-the-real-release). The simulator now has these artefacts as its "real-world payload patterns" setting.

3. **Routine program reuse is not a sign of shared control.** A program run by several actors now counts as a coordination sign only if it writes to a place, reads a place another actor wrote, or does something the pack calls harmful. The evaluation's submit call, a token check, or two agents fetching the same public file are listed as routine. Program-reuse signs on benign swarms fell from 10 of 10 to 0 of 10. On the Swarm Traces release 37 of the 253 shared programs remain signs.

## Results

Generated 2026-11-16T09:41:31Z by `python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5`. 45 coordinated and 15 benign simulated swarms. Cells are min–**median**–max over seeds; one value means all seeds agree.

### Messages

| setting | Message links: precision | Message links: recall | Agent pairs: precision | Agent pairs: recall |
|---|---|---|---|---|
| 40 agents, defaults | 86%–**90%**–91% | 78%–**85%**–87% | 93%–**94%**–96% | 87%–**90%**–93% |
| 20 agents | 82%–**91%**–93% | 78%–**82%**–86% | 91%–**96%**–99% | 88%–**89%**–92% |
| 80 agents | 87%–**92%**–94% | 80%–**83%**–87% | 93%–**95%**–97% | 86%–**88%**–90% |
| 40 agents, 35% hold two tokens | 84%–**85%**–87% | 77%–**83%**–85% | 92%–**94%**–96% | 86%–**88%**–90% |
| 40 agents, 25% of reads hidden | 83%–**88%**–91% | 66%–**68%**–74% | 94%–**95%**–97% | 73%–**79%**–82% |
| 40 agents, many place-naming notes | 88%–**93%**–96% | 83%–**85%**–89% | 94%–**96%**–98% | 87%–**90%**–94% |
| 40 agents, no hidden reads, no notes | 89%–**91%**–92% | 90%–**91%**–93% | 92%–**94%**–96% | 92%–**94%**–96% |
| 40 agents, a time field on every record | 84%–**91%**–94% | 78%–**85%**–86% | 89%–**96%**–98% | 86%–**91%**–93% |
| 40 agents, real-world payload patterns | 83%–**86%**–92% | 80%–**88%**–90% | 92%–**93%**–94% | 88%–**92%**–93% |
| **all coordinated** | 82%–**90%**–96% | 66%–**84%**–93% | 89%–**95%**–99% | 73%–**90%**–96% |

### Timing and dating

| setting | Early signs found | Signs within 1 h of the truth | Sign timing error, median (h) | Dating error, median (h) | Dating error, 90th percentile (h) | Estimated times inside the stated range |
|---|---|---|---|---|---|---|
| 40 agents, defaults | 100% | 80%–**100%**–100% | 0.04–**0.05**–0.21 | 0.02 | 0.07 | 86%–**88%**–90% |
| 20 agents | 100% | 89%–**100%**–100% | 0.02–**0.05**–0.07 | 0.02–**0.03**–0.03 | 0.09–**0.10**–0.12 | 84%–**84%**–87% |
| 80 agents | 100% | 80%–**100%**–100% | 0.01–**0.05**–0.05 | 0.01–**0.01**–0.02 | 0.05 | 86%–**90%**–91% |
| 40 agents, 35% hold two tokens | 100% | 60%–**80%**–100% | 0.06–**0.15**–0.55 | 0.02 | 0.07–**0.07**–0.08 | 86%–**87%**–88% |
| 40 agents, 25% of reads hidden | 100% | 80%–**80%**–90% | 0.04–**0.07**–0.24 | 0.02 | 0.07 | 86%–**88%**–90% |
| 40 agents, many place-naming notes | 100% | 90%–**90%**–100% | 0.04–**0.06**–0.09 | 0.02 | 0.05–**0.07**–0.07 | 86%–**88%**–90% |
| 40 agents, no hidden reads, no notes | 100% | 80%–**90%**–100% | 0.02–**0.06**–0.09 | 0.02 | 0.07–**0.07**–0.08 | 85%–**87%**–89% |
| 40 agents, a time field on every record | 100% | 70%–**90%**–100% | 0.00–**0.01**–0.02 | – | – | – |
| 40 agents, real-world payload patterns | 100% | 90%–**100%**–100% | 0.03–**0.04**–0.10 | 0.02 | 0.06–**0.07**–0.09 | 84%–**87%**–88% |
| **all coordinated** | 100% | 60%–**90%**–100% | 0.00–**0.05**–0.55 | 0.01–**0.02**–0.03 | 0.05–**0.07**–0.12 | 84%–**87%**–91% |

### Identity merging

| setting | Identity merges, high: precision | Identity merges, medium: precision | Identity merges, low: precision | Identity merges proposed as high | Identity: true pairs found at high | Identity: true pairs found at any band | Identity, direct-evidence rule: precision | Identity, direct-evidence rule: recall | Estimated agents minus true agents |
|---|---|---|---|---|---|---|---|---|---|
| 40 agents, defaults | – | 100% | 1%–**1%**–1% | 0 | 0% | 60%–**71%**–100% | 100% | 60%–**71%**–100% | 2–**5**–9 |
| 20 agents | 100% | 100% | 0%–**1%**–3% | 0–**0**–1 | 0%–**0%**–33% | 100% | 100% | 100% | 0–**1**–2 |
| 80 agents | 100% | 100% | 1%–**1%**–1% | 0–**0**–1 | 0%–**0%**–11% | 67%–**90%**–100% | 100% | 67%–**90%**–100% | 8–**9**–15 |
| 40 agents, 35% hold two tokens | 100% | 100% | 1%–**2%**–5% | 0–**1**–1 | 0%–**6%**–10% | 71%–**77%**–90% | 100% | 71%–**77%**–90% | 9–**15**–20 |
| 40 agents, 25% of reads hidden | – | 100% | 1%–**1%**–1% | 0 | 0% | 60%–**71%**–100% | 100% | 60%–**71%**–100% | 2–**5**–9 |
| 40 agents, many place-naming notes | 100% | 100% | 0%–**1%**–1% | 0–**0**–1 | 0%–**0%**–14% | 71%–**80%**–100% | 100% | 71%–**80%**–100% | 2–**5**–8 |
| 40 agents, no hidden reads, no notes | 100% | 100% | 1%–**1%**–2% | 0–**0**–1 | 0%–**0%**–20% | 75%–**100%**–100% | 100% | 75%–**100%**–100% | 2–**4**–9 |
| 40 agents, a time field on every record | – | 100% | 0%–**1%**–2% | 0 | 0% | 67%–**80%**–100% | 100% | 67%–**80%**–100% | 2–**5**–9 |
| 40 agents, real-world payload patterns | 100% | 100% | 0%–**1%**–1% | 0–**0**–1 | 0%–**0%**–14% | 67%–**86%**–100% | 100% | 67%–**86%**–100% | 2–**5**–8 |
| benign: 40 agents, half save results | – | 100% | 1%–**1%**–1% | 0 | 0% | 43%–**75%**–100% | 100% | 43%–**75%**–100% | 2–**5**–9 |
| benign: 40 agents, read-only | – | – | 0%–**0%**–1% | 0 | 0% | 20%–**33%**–75% | 100% | 20%–**33%**–75% | 2–**5**–9 |
| benign: 40 agents, real-world payload patterns | – | 100% | 0%–**0%**–1% | 0 | 0% | 0%–**50%**–56% | 100% | 0%–**50%**–56% | 2–**5**–9 |
| **all coordinated** | 100% | 100% | 0%–**1%**–5% | 0–**0**–1 | 0%–**0%**–33% | 60%–**80%**–100% | 100% | 60%–**80%**–100% | 0–**5**–20 |

### Default alert rules

| setting | Alert (2 kinds of coordination): hours after the first true message | Alert (2 kinds of coordination): hours before the first true harm | Watch (first harmful sign): hours before the first true harm |
|---|---|---|---|
| 40 agents, defaults | -0.22–**-0.04**–0.07 | -2.94–**-1.66**–-0.56 | 0.03–**0.05**–0.09 |
| 20 agents | -0.18–**0.21**–1.82 | -3.08–**-2.84**–-0.49 | -0.02–**0.04**–0.22 |
| 80 agents | -0.05–**-0.00**–2.03 | -3.31–**-2.04**–-1.59 | -0.00–**0.04**–0.07 |
| 40 agents, 35% hold two tokens | -0.22–**-0.03**–0.55 | -2.87–**-2.17**–-0.54 | 0.03–**0.05**–0.07 |
| 40 agents, 25% of reads hidden | -0.21–**0.04**–0.24 | -2.94–**-2.06**–-0.56 | 0.03–**0.05**–0.09 |
| 40 agents, many place-naming notes | -0.13–**-0.05**–0.01 | -2.36–**-1.09**–-0.81 | -0.11–**0.05**–0.09 |
| 40 agents, no hidden reads, no notes | -0.10–**-0.01**–0.13 | -3.21–**-2.13**–-1.59 | -0.07–**0.02**–0.07 |
| 40 agents, a time field on every record | -0.00–**-0.00**–0.14 | -2.90–**-1.99**–-0.49 | 0.00–**0.01**–0.02 |
| 40 agents, real-world payload patterns | -0.09–**-0.05**–1.92 | -5.68–**-2.76**–-1.69 | 0.02–**0.02**–0.10 |
| **all coordinated** | -0.22–**-0.00**–2.03 | -5.68–**-2.06**–-0.49 | -0.11–**0.04**–0.22 |

### Pooled medians, with intervals that resample settings

The settings share seeds (base, hidden reads and two-token swarms use the same five), so they are not independent. 'Resampling swarms' treats every swarm as independent (the v2.1.0 way) and is too narrow; 'resampling settings' draws whole settings with replacement and is the one to quote. 95% percentile intervals of the median, 2000 draws.

| measure | pooled median | resampling swarms | resampling settings |
|---|---|---|---|
| Message links: precision | 90% | 88% to 91% | 87% to 91% |
| Message links: recall | 84% | 83% to 85% | 82% to 86% |
| Agent pairs: precision | 95% | 94% to 96% | 94% to 96% |
| Agent pairs: recall | 90% | 88% to 90% | 88% to 92% |
| Signs within 1 h of the truth | 90% | 90% to 100% | 90% to 100% |
| Dating error, median (h) | 0.02 | 0.02 to 0.02 | 0.02 to 0.02 |
| Alert (2 kinds of coordination): hours before the first true harm | -2.06 | -2.25 to -1.66 | -2.17 to -1.66 |
| Watch (first harmful sign): hours before the first true harm | 0.04 | 0.03 to 0.05 | 0.02 to 0.05 |

### Each early sign on the coordinated swarms

| sign | found | within 1 h of the truth | tool minus true time, h (min–median–max) |
|---|---|---|---|
| First message between agents | 45 of 45 | 45 of 45 | -0.22–**-0.01**–0.55 |
| First cloud metadata | 45 of 45 | 45 of 45 | -0.10–**-0.01**–0.02 |
| First hf dataset write | 45 of 45 | 45 of 45 | -0.22–**-0.04**–0.01 |
| First kubernetes api | 45 of 45 | 45 of 45 | -0.12–**-0.02**–0.04 |
| First registry board | 45 of 45 | 45 of 45 | -0.42–**-0.03**–0.11 |
| A group of 3+ agents linked by messages | 45 of 45 | 43 of 45 | -0.60–**-0.01**–2.06 |
| A group of 10+ agents linked by messages | 45 of 45 | 39 of 45 | -2.32–**-0.02**–1.63 |
| A group of 5+ agents linked by messages | 45 of 45 | 39 of 45 | -0.45–**-0.01**–2.60 |
| First two-way exchange | 45 of 45 | 34 of 45 | -0.12–**-0.00**–7.39 |
| A group of 20+ agents linked by messages | 41 of 41 | 25 of 41 | -3.39–**-0.23**–1.57 |

### Identity merge proposals, all runs pooled

| band | proposed | right | precision (95% range) | evidence on the wrong pairs |
|---|---|---|---|---|
| high | 12 | 12 | 100% (76%–100%) | – |
| medium | 60 | 60 | 100% (94%–100%) | – |
| low | 21722 | 207 | 1% (1%–1%) | same_programs 20327, handoff 14257, messages 2645, same_place 2130 |
| direct rule | 279 | 279 | 100% (99%–100%) | – |

### Message precision by confidence grade, coordinated swarms pooled

Each message the tool reports carries a grade: direct (the verbs of both sides sit in the very call that names the place), inferred (found through a variable, helper or LFS operation) or weak (a default, a merged place, or an estimated time more than an hour from the other side). Precision is against the simulator's true messages.

| grade | all coordinated: reported | right | precision (95% range) | real-world-style settings: reported | right | precision (95% range) |
|---|---|---|---|---|---|---|
| direct | 56 | 46 | 82% (70%–90%) | 56 | 46 | 82% (70%–90%) |
| inferred | 2670 | 2088 | 78% (77%–80%) | 217 | 175 | 81% (75%–85%) |
| weak | 6154 | 5809 | 94% (94%–95%) | 724 | 647 | 89% (87%–91%) |

### Benign baseline (15 swarms with no coordination)

Messages between different agents reported: 0; between two tokens of one agent: 0–**0**–5; records flagged harmful by the pack: 0–**45**–54; identity pairs proposed as high: 0.

Each swarm counts once per sign or rule, so the interval is a per-swarm binomial one (Wilson, 95%), not a rate per day.

| fires | what | swarms | share (95% range) | hours from the start |
|---|---|---|---|---|
| Watch: first single-actor harmful sign | default rule (watch) | 10 of 15 | 67% (42%–85%) | 0.53–**1.27**–5.43 |
| Volume baseline: ordinary volume alarm | default rule (info) | 6 of 15 | 40% (20%–64%) | 16.00–**18.50**–23.00 |
| Alert: 2 kinds of coordination | default rule (alert) | 2 of 15 | 13% (4%–38%) | 5.36–**12.85**–20.33 |
| First Hugging Face dataset write | sign (single, harm) | 10 of 15 | 67% (42%–85%) | 0.53–**1.27**–5.43 |
| First message between named actors | sign (joint, message) | 7 of 15 | 47% (25%–70%) | 4.86–**10.94**–17.96 |
| Volume alarm on all actions | sign (baseline, baseline) | 4 of 15 | 27% (11%–52%) | 16.00–**17.00**–20.00 |
| Volume alarm on harmful actions | sign (baseline, baseline) | 2 of 15 | 13% (4%–38%) | 23.00 |
| First two-way exchange | sign (joint, two_way) | 2 of 15 | 13% (4%–38%) | 5.36–**12.85**–20.33 |

### Default rules on the coordinated swarms: hours before the first true harmful action

| rule | hours before (min–median–max) |
|---|---|
| alert-coord2 | -5.68–**-2.06**–-0.49 |
| baseline-volume | -13.86–**-5.90**–-2.75 |
| watch-harm | -0.11–**0.04**–0.22 |


## Independent generator (agenttrace/indepgen.py)

Generated 2026-11-16T09:41:56Z by `python3 -m agenttrace.indepeval run --out reports/validation --seeds 601 602 603 604 605 606 607 608 609 610`. 80 coordinated and 50 benign swarms of 30 agents over 48 h, seeds 601–610. Different naming (no zz boards), Python, curl and JavaScript code, library calls with no URL, clock skew, notes that name a dataset without reading it, attacks timed independently of the coordination, and benign look-alike classes. The original simulator's numbers stay above; these are the ones to read first, because the original writes the strings the rules match (docs/audit-v2.1.md 1.3). The independent swarms are still written by the same team.

Original simulator, for comparison (45 coordinated swarms, median over swarms): message precision 90%, recall 84%, agent-pair precision 95%, recall 90%.

### Message links by file layout

Pooled over swarms: links the tool reports that are true messages, and true messages the tool finds. Wilson 95% ranges treat links as independent, so they are optimistic.

| layout | swarms dated | links reported | precision (95% range) | true messages | recall (95% range) | median per swarm: precision / recall | agent pairs: precision / recall | dating error, median (h) |
|---|---|---|---|---|---|---|---|---|
| file in time order, epoch stamps on 60% of records | 20 of 20 | 2733 | 70% (69%–72%) | 3314 | 58% (56%–60%) | 70% / 57% | 85% / 73% | 0.04 |
| file in time order, a time field on every record | 20 of 20 | 2722 | 60% (58%–62%) | 3308 | 50% (48%–51%) | 61% / 50% | 77% / 67% | – |
| file in time order, a time field on 30% of records | 20 of 20 | 1706 | 19% (17%–21%) | 3308 | 10% (9%–11%) | 18% / 10% | 57% / 33% | – |
| file grouped by agent, epoch stamps on 60% of records | 0 of 20 | 0 | – | 3314 | 0% (0%–0%) | – / 0% | – / 0% | – |

A swarm with no times the tool can order is reported as undated and has no messages: it counts in recall as all missed.

### Early warning on the coordinated swarms (file in time order, epoch stamps on 60% of records)

Lead is hours before the first true harmful action (negative: after it). Alert is the default two-kinds-of-coordination rule, Watch the first-harmful-sign rule; the rest are the simple baselines of agenttrace/baselines.py.

| alarm | fired | median lead (h) | fired before the first true harm |
|---|---|---|---|
| Alert rule | 20 of 20 | -4.68 | 20% |
| Watch rule | 20 of 20 | 0.16 | 70% |
| First new host after 12 h | 14 of 20 | 0.15 | 64% |
| Distinct-actor alarm (3 sd, 12 h history) | 17 of 20 | -7.71 | 0% |
| Volume alarm (3 sd, 12 h history) | 18 of 20 | -6.71 | 0% |
| Volume alarm (3 sd, 6 h history) | 19 of 20 | -5.23 | 5% |

The shared-place sign fired in 0 of 20 coordinated swarms: its pattern is the pack's zz board name and the other handles the pack lists, and these swarms coordinate through ordinary dataset names, so it cannot see them.

### Benign look-alike classes

Swarms with no malice. The first three carry real information flow; the fourth makes calls the pack lists as harmful; the fifth does neither. Cells are swarms where the alarm fired, with a Wilson 95% range.

| class | swarms | true messages per swarm | reported between agents (right) | Watch | Alert | Volume alarm | New host after 12 h | Distinct actors |
|---|---|---|---|---|---|---|---|---|
| many agents push results to one shared leaderboard dataset and read it for the best | 10 | 102.8 | 85.3 (61.5) | 10 of 10 (72%–100%) | 10 of 10 (72%–100%) | 3 of 10 (11%–60%) | 0 of 10 (0%–28%) | 0 of 10 (0%–28%) |
| one release bot writes a status dataset; CI-style agents poll it every ~10 minutes | 10 | 480.0 | 433.4 (286.1) | 10 of 10 (72%–100%) | 10 of 10 (72%–100%) | 3 of 10 (11%–60%) | 0 of 10 (0%–28%) | 0 of 10 (0%–28%) |
| a coordinator hands tasks through one dataset; workers return results through another | 10 | 384.7 | 325.1 (219.7) | 10 of 10 (72%–100%) | 10 of 10 (72%–100%) | 6 of 10 (31%–83%) | 0 of 10 (0%–28%) | 2 of 10 (6%–51%) |
| honest agents on cloud machines: metadata for the region, cluster API for pod status, results to their own dataset | 10 | 0.0 | 0.0 (0.0) | 10 of 10 (72%–100%) | 9 of 10 (60%–98%) | 4 of 10 (17%–69%) | 0 of 10 (0%–28%) | 2 of 10 (6%–51%) |
| plain agents that read one public reference dataset | 10 | 0.0 | 0.0 (0.0) | 0 of 10 (0%–28%) | 0 of 10 (0%–28%) | 2 of 10 (6%–51%) | 0 of 10 (0%–28%) | 2 of 10 (6%–51%) |

All 50 benign swarms: Watch 40 of 50 (80%) (67%–89%); Alert 39 of 50 (78%) (65%–87%); Volume alarm 18 of 50 (36%) (24%–50%); new host after 12 h 0 of 50 (0%) (0%–7%); distinct actors 6 of 50 (12%) (6%–24%). The Alert fired in 30 of 30 swarms of the three classes with real information flow (89%–100%): it detects information flow, not malice.

## Audited links on the real release

The simulated swarms cannot say whether a link on real data is a message. So we read the real ones. **Who read them:** the authors' AI assistant, with a helper script that parsed the request around each mention; no person read the links by hand, and none was labelled twice. Texts that said otherwise were wrong. A reviewer who read both records of the 23 deliveries counted at v2.1.0 disagreed with 11 to 13 of the 18 labels that said "true" and would defend about 5 (range 3 to 7); those labels were corrected for the v2.2.0 rule.

**Method.** We checked out v1.1.0 in a git worktree and ran it on the Swarm Traces release (`redacted_columns.csv`, 189,579 records, code-traces pack) to recover the 166 messages between named tokens it reported. We ran the current code the same way (19 messages; 7 of them among the 166). For each of the 178 links we read the write record and the read record and asked three questions: is the "write" a commit, upload, POST or PUT to that same place; is the "read" a fetch of it; is it the same repository. A separate script, not the tool's rules, parsed the request around each mention as a cross-check; where the script and the reading differed, the reading decided. Each link has a label, a one-line reason and a snippet of at most 120 characters around the place in each record, in `agenttrace/claims/audited_links.json`.

**What the 178 links are.**

| what the reading found | audited | reported at v1.1.0 | reported now |
|---|---|---|---|
| a true message | 1 | 1 | 0 |
| the "write" only GETs the place, then POSTs or commits the result elsewhere | 149 | 149 | 0 |
| the "write" only fetches: an LFS download batch, Python `urlopen(url)`, or a POST that only queries | 9 | 8 | 4 |
| write and read are on different repositories under one owner | 4 | 4 | 0 |
| the place is named only in a comment | 0 | 0 | 0 |
| the write is real, but the "read" is itself a write | 14 | 3 | 14 |
| unclear (text cut before the call) | 1 | 1 | 1 |
| **total** | **178** | **166** | **19** |

**The current code against these labels** (`python3 -m agenttrace.benchmark run redacted_columns.csv`):

- **Precision: 0 of 18** links that could be decided (95% range 0%–18%); 1 more is unclear. At v1.1.0 it was 1 of 165 (0%–3%).
- **Recall: 0 of 1** true link in the audited pool (95% range 0%–79%). The one link read as true (one token changes a repository's access requests, another lists them 2.3 hours later) was reported by v1.1.0 and is dropped now.
- The fixes since v1.1.0 did what they were meant to do: all 149 read-then-post links are gone, as are the different-repository links and most of the downloads.
- **The 18 false links the current code reports are the rows where the code and the reading disagree.** Fourteen are two tokens *writing* to the same dataset: the commit URL sits in a variable or is passed to a helper, and the verb is on a later call (`u='…';fetch(u,{method:'POST'})`, `requests.post(url, …)`, `urlopen(Request(v, data=body))`). The rule that stops the code window at the start of the next request call, added to fix the read-then-post error, now cuts the verb off, so the second commit is taken for a read. Three are a Python `urlopen(url)` read still taken for a write, because a commit to another dataset sits just before it. One is a POST that only lists files. In five of the fourteen the tool also names the wrong sender: the record holds two tokens and the commit uses the second.

**What follows (as of v1.3.0).** On this release, "messages between named tokens" was not a finding yet: none of the reported links survived a reading. (Superseded: see the v2.2.0 result above.) The app shows the same table under **Forensics → Test and export → Audited links (real data)**, with the 19 rows where the code and the reading disagree, each with its two records one click away. `GET /api/x/benchmark` returns it for the loaded session when that session is the release.

**The simulator now has these patterns.** The "real-world payload patterns" settings above reproduce them with exact truth. v1.1.0's rules and the code of 13 November on the same swarms (`reports/validation/old_rules.json`; not re-run since) (`python3 -m agenttrace.validation old-rules --worktree <checkout of v1.1.0>`, saved as `reports/validation/old_rules.json`; pooled over 5 seeds):

| setting | v1.1.0 rules | current code |
|---|---|---|
| 40 agents, defaults (the old simulator) | precision 79%, recall 73% | precision 79%, recall 73% on the 13 November code (identical links); 90% / 85% now |
| 40 agents, real-world payload patterns | precision 66% (63%–69%), recall 57% (54%–60%) | precision 80% (77%–82%), recall 78% (75%–81%) on the 13 November code; 86% / 88% median now (summary above) |
| benign, real-world payload patterns (no true message) | 292 links, 282 between different agents | 9 links, 0 between different agents (13 November code) |

The old simulator could not tell the two versions apart. The new settings can: on the benign one v1.1.0 invents about 56 messages between agents per swarm and the current code none. They also show what the current code still gets wrong, with the same causes as on the real data: writes taken for reads (59 false links over the 5 coordinated swarms), writes not seen as writes (28 missed), and a place split in two because the pattern keeps the next path word after a repository number (`…] REPO 12]/resolve` and `…] REPO 12]/commit` become two places; this is among the 124 messages missed because write and read ended up on different places or the read was not seen).

**Limits of the audit.**

- **One labeller, tool-assisted.** The labels are by the authors' AI assistant reading the records with a helper script (and, for 13 links in v2.2.0, a reviewer's reading); nobody labelled them a second time. Disagreement between labellers is unmeasured. The labelling kit (`python3 -m agenttrace.tools.labelkit export`) is ready for a second labeller; nobody has used it.
- **Recall is within the audited pool.** Only links some version of the tool reported were read. True messages that no version ever reported are not in the pool, so "0 of 1" says nothing about how many real messages the release holds. Two of the false links are two tokens reading one file that a third party must have put there: there are real messages nearby that the tool attributes to the wrong writer.
- **"Message" is the tool's definition**: a read of a shared place after a write to it by a different token. Two tokens committing to one dataset do share that place, and may well be working together; it is not a message by this definition, and the tool should not call it one.
- **Redaction and cut text.** Paths are often swallowed by the redaction and long records are cut, so some calls cannot be seen (one link is unclear for this reason, and one "read" was judged from a call cut at `{metho`).
- **One dataset, one date.** The labels were made on 2026-11-13 against the code of that day. A link the code reports later that is not in the file is listed as "not audited yet" and left out of the rates.

### After the audit: the rule change and its score (2026-11-13)

The audit showed two opposite errors. The v1.1.0 rule called a read a write when a POST to somewhere else followed it. The v1.3.0 fix for that cut the code at the next request call, so a commit whose URL sits in a variable (`u='…'; fetch(u, {method:'POST'})`) lost its verb and became a read: two tokens committing to one dataset looked like a message. The current rule:

- judges a place held in a variable by the calls the variable is passed to (`fetch(u, …)`, `x.open('POST', U)`, `req(url, tok, 'POST', data)`, a wrapper function's callers), each bounded by its own parentheses;
- judges a Git LFS batch by its `operation` (download or upload);
- drops a mention that is assigned and never passed to a call, and a call cut off before its verb;
- does not take API path words (`/commit`, `/resolve`, `/info` …) as part of a place name, so a commit and a download of one repository meet on one place;
- takes as the actor the token named in the judged call when a record holds several.

Scored with `python3 -m agenttrace.benchmark run redacted_columns.csv`: of the 177 audited false links it reports none; it keeps the one audited true link and reports four more, which were then read (both records) and labelled true: an LFS upload followed by another token downloading the file, and three commits each followed by another token fetching that dataset's API entry. Those four labels were made after the rule change by the same labeller, so they are weaker evidence than the 178 made before it (and a reviewer later judged most of them not to be messages: see the v2.2.0 note below). The simulated real-world setting, which reproduces these payload shapes with exact truth, was the check at that time: precision 79%, recall 79% (median), against 66% and 57% for the v1.1.0 rules; the simulator is optimistic (see the independent generator); an intermediate version of this fix raised benign false links from 0 to 45 across five swarms and the simulator caught it before release.

What the release showed at v2.1.0 (final rules, phase 1): 23 messages, 6 of them between named tokens (5 pairs); counted by estimated agent, 3 between agents and 3 inside one. The report submitted to the hackathon says 19; that figure is superseded.

### v2.2.0: the audit of v2.1.0 and the rule it led to (2026-11-16)

Four reviewers were told to find what was wrong. One read both records of all 23 deliveries. Its findings and the rule changes they led to:

- **10 of the 23 rested on one upload probe.** A write was an LFS batch request with `operation: 'upload'` for a file whose download had been requested 34,000 s earlier. The rule now counts an upload batch only if its object was not downloaded earlier and a later record sends it (R6b).
- **A reader looped over a token list that contained the writer's own token** (R0006727 to R0006743, R0006792); such a delivery is no longer counted (R23a).
- **Two calls were cut inside the verb** (`'POS'`) and are now not counted (R13); a `paths-info` POST is a read (R6a); unnumbered `[HF REPO]`, `[REDACTED:username:…]` and `[USER n]` places are coarse (R31).
- **Result at v2.2.0: 9 write-then-read deliveries, 4 between named tokens in 4 pairs among 7 tokens; counted by estimated agent, 2 between agents and 2 inside one.** All 9 were on Hugging Face datasets, none on a board folder. 5 of the 9 were labelled true, 4 unclear (3 sit on a place the redaction may have merged). v2.3.0 counts 11: see the next section.
- **None of them shows the reader using what was written (0 of 9 then, 0 of 11 now).** The written-content test (R38) lists the identifiers shared by the writer's and the reader's record; none shares one. Even the survivors are a commit followed by a later GET of the repository. "Write then later read of the same place by another identity" is accurate; "message" overstates it.
- **The second implementation found 192 deliveries at v2.1.0** (it took commits for reads; 40 sampled extras held no message, 0% to 8.8%). The cause was its handling of redaction, and it was fixed for v2.2.0: it then found the same 9 as the rule (the same 11 at v2.3.0), which is not an independent check because it was changed while reading where it differed (see [integrity](integrity.md)).
- **Recall is unknown.** The reviewer read about 90 places the rule ignores and found no missed delivery; that is a failed hunt, not proof (the ceiling for unseen misses is about 23 more at 95% confidence).

### v2.3.0: joined fragments and a second content test (2026-11-22)

- **A record cut inside a verb is joined with the next record when that record completes the verb (R13a).** The release holds one such pair, R0022674 and R0022675: read as one record it is a commit to a dataset by token 169, and two anonymous runs fetch that dataset later (R0032250, R0032842). v2.1.0 counted these two links, and v2.2.0 dropped them because the call was cut inside `'POS`. They are counted again, so the release has **11 write-then-read deliveries; still 4 between named tokens.**
- **Their labels did not change.** Both are "unclear" in `audited_links.json`: the label was given when the call could not be read, and nobody has read the joined text as a labeller. So 5 of the 11 are labelled true and 6 unclear.
- **A second form of the written-content test (R38b)** looks in the reader's later records for a distinctive term the writer wrote (an identifier-like run of 8 or more characters, a number of 5 or more digits, a numbered redaction marker), new at the write and not the reader's already. On the release it passes none of the 11 (`reports/integrity/content_test_v23.json`), so the count of deliveries where the reader is shown using what was written stays 0. On the collusion.wiki logs it passes 258 deliveries that did not pass before (2,192 of 9,867 pass, against 1,934). The test was written after a scripted harness run showed the first form looking in the wrong record ([harness.md](harness.md)), so it was tuned on that script.
- **The second implementation** was given R13a and R38b from the written rule and finds the same 11 deliveries on the release and 9,867 on the wiki logs (`python3 -m agenttrace.tools.crosscheck`, 22 November). As before, that is agreement on what the rule says, not evidence that the rule is right.
- **The original-simulator tables above were run again on the v2.3.0 code** (22 November, same seeds) and came out the same, line for line. The independent-generator run is the one of 16 November and was not repeated.

### Phase 1: every delivery audited, a grade for each message, a second method (2026-11-13)

**All deliveries, not only the named ones.** The code reported 74 deliveries on the release; only 5 were between two named tokens, so the audit above said little about the rest. We read the other 69 the same way (both records, the judged call around each mention) and added them to `audited_links.json` with an `endpoint_kind` (`named_named` or `involves_run`, when either side is an anonymous `run:` endpoint). Of those 69: 6 were true messages, 28 were a GET of the place followed by a POST elsewhere, 9 were a "read" that is itself a commit, and 26 could not be decided (a record cut off before its verb, an LFS batch whose `operation` the redaction hid, a place that names only an owner). So the anonymous endpoints were mostly false or unreadable, as the named ones had been.

**Rule changes.** (1) A verb literal in a helper call (`Q('GET', src, …)`) is read from that call only, not from a POST later in the text. (2) A variable's later uses stop where the name is given another value. (3) A record cut off inside a call right after the place, or a bare URL, is not counted. (4) An LFS batch with no visible `operation` is not counted. (5) `…/<owner>/'+repo+'/…`, where the repository is a variable, names only an owner and is not counted. (6) A request written as data (`{"u": …, "m": "POST"}`) is judged by its method or body, and `Request(url, data=…)` is a write. At v2.1.0 the release showed 23 deliveries, 6 of them between named tokens (it was 74 and 5 before these rule changes; 24 until the false link was removed on 15 November; 9 and 4 at v2.2.0 and 11 and 4 at v2.3.0, above). The simulator did not move: precision 79.4% and recall 73.0% on the default setting, 80.0% and 78.1% on the real-world setting, and 9 false links, none between agents, on the benign real-world setting, all as before the change.

**Score on the 258 audited links** (labels as corrected in v2.2.0: 5 true, 177 read-then-post, 23 "read is a write", 19 downloads, `urlopen` or upload probes, 4 different repositories, 29 unclear, 1 reader holding the writer's own token). In-sample: 13 labels were changed in the same commit as the v2.2.0 rule. The table is the v2.3.0 rule's score.

| group | reported | read as true | precision (95% range) |
|---|---|---|---|
| all deliveries | 11 (6 unclear) | 5 of 5 | 100% (57%–100%) |
| between two named tokens | 4 | 4 of 4 | 100% (51%–100%) |
| an anonymous run on one side | 7 (6 unclear) | 1 of 1 | 100% (21%–100%) |

Read these as optimistic: the labels of 13 links were changed in the same commit as the v2.2.0 rule, only 5 of the 11 links are decidable, and the interval reflects that. At v2.1.0 the same table read 18 of 18 (82%–100%), which a reviewer's reading cut to about 5. Recall is within the audited pool only.

**A grade on every message.** Each delivery now carries `grade` (the last column of `/api/messages`): *direct* (the write verb and the read verb are both in the very call that names the place), *inferred* (the verb was found through a variable, a helper, an LFS operation or nearby text) or *weak* (no verb found, a merged place, or an estimated time more than an hour from the other side). On the release: 0 direct, 0 inferred, 11 weak. On the audit: weak 5 of 5 (57%–100%). Precision by grade does not separate and, on the real release, no grade has enough links to say anything. On the simulated swarms, pooled over 5 seeds (all 45 coordinated runs): direct 82% (46 of 56; 70%–90%), inferred 78% (2,088 of 2,670), weak 94% (5,809 of 6,154); on the real-world setting direct 82%, inferred 81% (175 of 217; 75%–85%), weak 89% (647 of 724; 87%–91%). The ranges overlap, so a reader should not trust one grade more than another; the grade records how the verb was found, nothing more. We tried also marking messages whose place had several earlier writers: it moved precision from 78% to 88% on only 5% of messages, so we left it out. The simulator's errors are the wrong write picked and one agent reading its own token's write, not a missing verb.

**A second method, not a second labeller.** `benchmark.independent_agreement` classifies each mention with a small tokenizer: it finds the call that holds the place, its arguments and any verb (following one variable, an options object, an LFS `operation`, a `data=` argument), and treats a request with no verb as a GET. It is written apart from `messages.judge_span`. Against our corrected labels (unclear left out, 229 links): raw agreement 94% (215 of 229; 90%–96%), Cohen's kappa 0.20 (the labels now hold only 5 true links, so kappa is dominated by them; at v2.1.0 it was 98% and 0.83 against 18). Its 14 disagreements are 10 LFS upload probes it reads as writes, the 1 reader holding the writer's own token, and 3 of the 5 true links it cannot see (a call it finds no verb for). We fixed the method twice after its first disagreements, so the agreement is flattering; it shows that a different reading of the text mostly lands where we did, not that the labels are right.

**What a reader may trust.** A delivery on this release is a lead that was checked once by one reader, the authors' AI assistant. Of the 4 between named tokens all 4 were read as a write then a later read; of those with an anonymous endpoint 1 of 1 decidable. None is shown to carry information. Nothing here measures how many true deliveries are missed outside the pool.

## Measured on four outside datasets (v2.3.0)

Until v2.3.0 every accuracy figure here came from swarms we generated. On 22 November 2026 the tool was run on four public datasets it was not built on and scored against what each dataset itself records. The saved results are `reports/external/<name>/summary.md` and `results.json`; each has a written investigation in the [gallery](investigations/). Rebuild with `python3 -I agenttrace/failure_eval.py who_and_when` (or `mast_data`) and `python3 -m agenttrace.external_eval salt` (or `moltbook`). None of the four is a swarm attack.

| dataset | what it is | what it records | labels made by |
|---|---|---|---|
| Who&When (Zhang et al., MIT) | 184 failed runs of small agent teams, 4,092 records | recipients in 58 runs; the agent and the step that caused the failure | human annotators |
| MAST-Data (Cemri et al., CC BY 4.0) | 1,640 readable runs of seven agent frameworks on ordinary tasks, 37,805 records | recipients in three frameworks; 14 failure modes per run | an LLM judge (a separate 19-run file has human labels) |
| SALT agent-collusion (Shi et al., MIT) | 2,650 simulated runs of two agents grading each other; 1,800 carry a collusion label | sender and receiver of every message; whether both accepted against the rules | the game's outcome |
| Moltbook Observatory Archive (Gautam and Riegler, MIT) | one week of posts and comments by AI agents, the 40 communities with most comments, 187,738 records | what each comment replies to | nobody: no incident is recorded and nothing is labelled |

**Who talked to whom.** The tool was given the logs with the recipient fields withheld: only who spoke, in what order, and the text.

| | logged pairs the tool finds | the tool's pairs that are logged | logged single messages it finds |
|---|---|---|---|
| Who&When, 58 runs that name recipients | 91 of 92 (98.9%) | 91 of 237 (38.4%; 75.9% in either direction) | 62 of 689 (9.0%) |
| MAST-Data, three frameworks that name recipients | 2,242 of 2,800 (80.1%) | 2,086 of 3,443 on ChatDev, the largest (60.6%) | 1,277 of 13,441 (9.5%) |
| Moltbook, replies by record | 10,720 of 41,737 (25.7%) | 10,720 of 40,486 (26.5%) | – |

So the pairs are mostly found where a log has turn-taking structure, single messages are not, and many of the tool's pairs are not in the log (the logs address only some messages, so those pairs are not shown wrong either). On Moltbook the write-then-read rule is right about the first comment in a thread (96.9% of its links) and wrong after it (1.0%): most comments answer the post, and the rule links each to the comment just before it. Pairs and messages inside one run are not independent, so the per-item intervals in the saved files are too narrow. With the recipient fields kept, every logged message is listed as a direct message; that checks the reader, not an inference.

**Alarms on runs with no attack.** Who&When, MAST-Data and Moltbook hold no recorded attack. Runs or communities in which each default rule fired, with the pack the tool picks by itself.

| | Alert rule (2 kinds of coordination) | Watch rule (first harmful sign) |
|---|---|---|
| Who&When, 184 runs | 181 (98.4%) | 40 (21.7%) |
| MAST-Data, 1,640 runs | 1,567 (95.5%) | 348 (21.2%) |
| Moltbook, 40 communities | 40 (100%) | 37 (92.5%) |

The Alert rule fires on almost any team that talks. The Watch rule on these traces is the general pack's word lists ("password", "secret", "upload", "delete"). Most of these runs carry no times and were given a step clock, on which the hourly alarms cannot fire; on the 38 Moltbook traces with times that the early-warning measurement could read, the three time-based main alarms each fired in 37 ([early-warning.md](early-warning.md), section 0d).

**Failure attribution (Who&When).** The tool has no such feature. Two rules fixed before scoring read its flags as blame.

| method | agent right, of 184 | step right, of 184 |
|---|---|---|
| the record of the tool's first warning sign | 54 (29.3%) | 25 (13.6%) |
| the tool's first harmful record | 13 (7.1%) | 1 (0.5%) |
| baseline: the agent with most records | 72 (39.1%) | – |
| baseline: the last step | 80 (43.5%) | 8 (4.3%) |
| chance | 29.1% | 9.5% |

The dataset's paper reports 53.5% and 14.2% for its best method, an LLM reading the whole log; we did not re-measure that. On MAST-Data the Alert rule fired on 94.6% of runs with a failure label and 98.5% of runs with none: it does not track failure.

**Collusion (SALT).** As published the episodes have no times: the tool lists the messages as logged and fires nothing (recall 0 of 1,351 colluding runs). With an order-only clock the Alert rule fires on 1,351 of 1,351 colluding runs and 449 of 449 others, so it does not separate them. A pack written after reading one run (`packs/peer_review.json`, a phrase match) fires on 546 of 1,301 colluding runs (42.0%) and 26 of 449 others (5.8%) in the 35 conditions it was not written from. It mostly catches the model whose wording it copied: 87.4% of colluding runs where an agent is that model, 20.9% where none is. The written-content test passes 31,305 of 160,490 inferred deliveries (19.5%), in colluding and other runs alike (20.4% and 16.6% of their checked deliveries).

**What these do not show.** Accuracy on a swarm, on an attack, or on contact through shared places: these are turn-taking teams, two-agent games and comment threads, where a delivery rests on who posted after whom. That the labels are right: the MAST labels are an LLM judge's, and in 6 of the 184 Who&When runs the labelled step was not spoken by the labelled agent. Anything about timing on the step clock, which is order only.

## What to quote

The numbers to quote for the message and early-warning questions are these, not the ones in the first tables. Simulated: message precision about 70% and recall about 58%, falling to 19% and 10% with sparse timestamps and to nothing when the file is grouped by agent; the same generator's benign look-alike swarms make the Alert rule fire in 39 of 50. Real, with recipients withheld: pairs 91 of 92 and 80.1%, single messages under 10%, reply links on a social site 26.5%. Real runs with no attack: the Alert rule on 95% to 100%. Failure attribution: at chance. The forward tests of the early warning on the two generators, the later of which failed for the four main alarms, are in [early-warning.md](early-warning.md).

## What the numbers mean

- **Message precision is limited mainly by one thing a pattern cannot know**: whether a read fetched the newest message or an older one. Before the comment fix, records that only named a place were about half of all false links. Pairs of agents are more reliable than single messages because a wrong message often joins the right two agents.
- **Coordination signs are early, not late.** For an early-warning tool that is the safer direction, but it means a sign's time is an upper bound on when coordination started only after checking the records behind it. The Early flag tab links each sign to its record; look at it before quoting the time.
- **The "2 kinds of coordination" alert** fired before any true message in the coordinated swarms when boilerplate reuse counted as a sign; see the alert table above for the current timing. On benign swarms it now fires in 2 of 15. As a detector it is noisy; as a prompt to look it is cheap.
- **The identity confidence bands do not mean what their names say** on swarms like these. A shared self-chosen place, a handoff and shared programs are evidence of *coordination*; in a coordinating swarm they join different agents far more often than one agent's two tokens. With 40 agents active over 36 hours, one agent stopping and another starting within 15 minutes happens by chance many times.
- **Simulated benign swarms do not produce false messages between agents.** That held for the real-world payload patterns too, but the audit of the real release shows that links between agents can still be false for reasons a benign simulation does not have (two agents writing to one place). They do produce warning signs, all traceable: a pack that calls every dataset commit harmful, and one agent's two tokens looking like two actors.

## Recommendations (from these measurements)

1. **Identity (`agenttrace/identity.py`)**: require at least one direct item (same record, same small thread, carried token) for "high"; cap pairs without one at "low" (or relabel the bands "strong / some / weak evidence" until they are calibrated). Discount handoffs by their chance rate given how many actors are active, and do not count a shared place or shared programs as identity evidence when the place also carries messages between the two (that is coordination). Re-run this suite after the change; the target is high ≥ 80% precision.
2. **Program signs** (done): routine reuse (no write, no read of a place another actor wrote, nothing harmful) is no longer a sign.
3. **Self-messages**: a message between two actors that the Agents tab already proposes as one agent should not count toward "2 kinds of coordination" or "first message".
4. **Pack harm list**: in the code-traces pack, "hf_dataset_write" marks every dataset commit as harmful; on a benign swarm that saves results this alone fires the watch rule. Keep it for the incident it was written for, but say so in the rule, or narrow it to writes into places others read.
5. **Notes that name a place** (done): mentions inside code comments no longer count as reads, writes or actions.

## Honest limits

- **The simulations were too easy once already, and still are.** v1.1.0 scored 79% message precision on them while 165 of its 166 links on the real release were false. The real-world settings close the gaps we found; there will be others. The independent generator (70% precision, 58% recall) shows the size of the optimism, and it is still written by the same team.
- **The simulations are ours.** The generator was written by the same team as the tool, from the shapes we saw in one incident. Real swarms differ: other channels, other naming, mixed threads, retries, partial logs. These ranges describe how the tool behaves on swarms shaped like these, not its accuracy on yours. The strongest use of this page is relative: which settings hurt, which measures are fragile, and what a change to the rules does.
- **Some evidence is clean by construction.** In the simulation an agent's threads never contain another agent, so "same small thread" is perfect identity evidence here; real threads can mix. The direct-evidence rule's 100% is therefore an upper bound, while the old high band's 4% was a real failure on this kind of swarm, which the rule change fixed.
- **Truth of a sign is our definition.** Each sign's true time is computed from the truth with the same definition the tool uses (first message, first group of N, first harmful action of a kind). A different definition would move the timing errors.
- **The simulated benign baseline is narrow.** Three kinds of benign swarm, 15 runs, one pack. Benign swarms that share a workspace, hand work to each other on purpose, or use one key for many agents would fire more, and the real runs measured in v2.3.0 do: the Alert rule fires on 95% to 100% of them. Neither is a false-positive rate for a deployment of code-running agents; no such benign traffic has been measured.
- **The default rules were written with hindsight** on the datasets their packs were made for; this page is the first test of them on swarms they were not written on.
- **Five seeds per setting** give ranges, not confidence intervals; the pooled identity figures carry 95% Wilson ranges. The pooled-medians table resamples whole settings (they share seeds); the v2.1.0 intervals resampled swarms and were too narrow.
- **Not every number here has a range,** and the registered numbers (`python3 -m agenttrace verify`) cover only part of the figures on this page.

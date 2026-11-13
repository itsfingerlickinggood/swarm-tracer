# How accurate is the tool?

[Home](./) · [How it works](how-it-works.md) · [Limits](limitations.md) · [Command line](cli.md) · [API](api.md)

Swarm Tracer's hard claims (who messaged whom, when each warning sign appeared, when an undated record happened, which tokens are one agent) can only be checked against a swarm whose truth is known. No real swarm comes with that, so we simulate swarms, keep the truth, load each one with the tool exactly as the app loads a file, and compare. This page gives the results as **ranges over seeds** (min – **median** – max), not one number, and adds the project's first **benign baseline**: swarms that never coordinate, where everything the tool flags is a false positive.

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

- **On real data the first two counts were wrong, and an audit fixed the rule.** *Update (phase 1): all 258 deliveries and links are now audited, not only the named ones; the release shows 24 messages, 6 between named tokens, precision 18 of 19 on the audit (95% range 75%–99%, optimistic: see below).* We read every link between named tokens that v1.1.0 reported on the Swarm Traces release (166) and every one the code at v1.3.0 reported (19): 178 links, of which one was a message by our reading. The rule was then changed and re-scored against those labels: the final rules report **24 messages, 6 between named tokens**, 18 of the 19 decidable ones judged true (precision 95%, 95% range 75–99%; all 6 named ones true). One labeller, and 7 of the 18 true labels were made after the last rule change: treat it as "one known false link", not as measured accuracy. See [Audited links on the real release](#audited-links-on-the-real-release).
- **Messages, simulated**: across the 45 coordinated swarms the tool finds 57%–**73%**–81% of the true messages, and 66%–**79%**–88% of the messages it reports are true. Pairs of agents: 71%–**83%**–91% recall, 81%–**89%**–96% precision. On the new real-world setting the current rule reaches precision 75%–**79%**–83% and recall 73%–**79%**–81%; v1.1.0's rules reach about 66% and 57% there, and on the benign version of that setting they report 282 links between different agents where the current rule reports none.
- **Harmful-action signs are exact**: first dataset write, first cluster call, first cloud-metadata call and first registry board are found in 45 of 45 swarms within an hour. **Coordination signs are close**: the first message between agents is within an hour of the truth in 45 of 45 swarms, groups of 3/5/10 in 37–40 of 45, the first two-way exchange in 33 of 45.
- **Dating is good and its stated range is nearly honest**: median error about 1 minute (0.01–0.03 h), 90th percentile 3–7 minutes; 84%–**87%**–91% of estimated times fall inside the stated 90% range (slightly under the 90% it promises).
- **Identity merging, before and after a fix.** The first version labelled pairs **high** on coordination evidence alone (a shared place, handoffs, shared programs); pooled over the first swarms those were right **4% of the time (10 of 240)**. Pairs with direct evidence (the same record, a small shared thread, or a carried token) were right in every case. The rule now requires direct evidence for high and medium. After the change, pooled over all 60 swarms: **high 12 of 12 right, medium 60 of 60**, and the rest stay low (about 1% right), so the low band should be read as "worth a look", not as a merge.
- **On benign swarms**: the tool reports **no** message between two different agents (0 in all 15, including the 5 with real-world payload patterns, where v1.1.0's rules report 282). Program-reuse signs no longer fire. The default rules fire: "Watch: first harmful sign" in 10 of 15 (every swarm whose agents save results: the code-traces pack counts any dataset commit as harmful), "Alert: 2 kinds of coordination" in 2 of 15 (one agent's two tokens reading back its own results, counted as a message, plus a second link sign), and the volume baseline in 6 of 15.

### The fixes this suite and a manual audit led to

1. **A place named only in a code comment is not a read.** Notes such as `// the crew says <dataset> has the plan; not fetching it yet` were counted as reads, and the harm patterns matched them too ("first registry board" fired a median 9 hours early). Mentions inside a comment (a line starting with `//`, `#`, `/*` or `*`, or a `//` / `# ` after whitespace) no longer count as reads, writes or actions. Message precision rose from 66% to 79% (median) and the registry-board sign moved to within an hour of the truth in 40 of 40 swarms.
2. **The verb nearest the mention decides, and the window stops at the next place.** A manual audit of the earliest links on the Swarm Traces release found three artefacts the simulations do not have: a GET followed within 260 characters by a POST to a *different* dataset was charged as a write to the first; an LFS batch with `operation:'download'` (a POST) was taken for a write; and the redaction's `[REDACTED:username:N]] REPO K]` kept a repository number the place pattern dropped, so writes and reads of different repositories under one owner looked like one place. With the nearest request verb deciding, read verbs (GET, HEAD, LFS download) recognised, the code window clipped at the next place mention, and the repository number kept, the named messages on the release fell from 166 to 107. A second audit of those 107 found that most were two tokens fetching the same dataset and POSTing what they read to a collector: the POST, the nearest verb, made the read a write. Clipping the window at the start of the next request call (`fetch(`, `.open(`, `urlopen(`, `requests.post(` …) and recognising `urlopen`/`.read()` as reads leaves **19 messages in 12 pairs among 9 tokens** (a Python `urlopen(url)` with one argument is a read; `urlopen(Request(url, data))` is a write). The simulated scores did not move, which is itself a finding: the simulator lacked these artefacts. **Correction (2026-11-13):** an earlier version of this page said the 19 were each checked by hand. A full audit of all 178 links, with the two records of each read side by side, does not support them: see [Audited links on the real release](#audited-links-on-the-real-release). The simulator now has these artefacts as its "real-world payload patterns" setting.

3. **Routine program reuse is not a sign of shared control.** A program run by several actors now counts as a coordination sign only if it writes to a place, reads a place another actor wrote, or does something the pack calls harmful. The evaluation's submit call, a token check, or two agents fetching the same public file are listed as routine. Program-reuse signs on benign swarms fell from 10 of 10 to 0 of 10. On the Swarm Traces release 40 of the 253 shared programs remain signs.

## Results

Generated 2026-11-12T19:35:12Z by `python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5`. 45 coordinated and 15 benign simulated swarms. Cells are min–**median**–max over seeds; one value means all seeds agree.

### Messages

| setting | Message links: precision | Message links: recall | Agent pairs: precision | Agent pairs: recall |
|---|---|---|---|---|
| 40 agents, defaults | 75%–**79%**–82% | 67%–**75%**–77% | 87%–**89%**–90% | 83%–**84%**–86% |
| 20 agents | 73%–**76%**–88% | 68%–**69%**–78% | 86%–**90%**–96% | 79%–**83%**–86% |
| 80 agents | 75%–**80%**–82% | 67%–**73%**–75% | 86%–**89%**–89% | 78%–**81%**–84% |
| 40 agents, 35% hold two tokens | 66%–**72%**–77% | 63%–**67%**–76% | 81%–**85%**–88% | 75%–**81%**–83% |
| 40 agents, 25% of reads hidden | 74%–**80%**–81% | 57%–**61%**–65% | 89%–**90%**–92% | 71%–**75%**–76% |
| 40 agents, many place-naming notes | 75%–**83%**–83% | 70%–**75%**–79% | 86%–**90%**–90% | 80%–**83%**–86% |
| 40 agents, no hidden reads, no notes | 73%–**76%**–80% | 73%–**74%**–80% | 82%–**86%**–89% | 83%–**86%**–89% |
| 40 agents, a time field on every record | 74%–**79%**–84% | 69%–**73%**–75% | 84%–**90%**–93% | 82%–**85%**–87% |
| 40 agents, real-world payload patterns | 66%–**71%**–75% | 56%–**59%**–69% | 81%–**84%**–88% | 63%–**69%**–82% |
| **all coordinated** | 66%–**77%**–88% | 56%–**72%**–80% | 81%–**88%**–96% | 63%–**82%**–89% |

### Timing and dating

| setting | Early signs found | Signs within 1 h of the truth | Sign timing error, median (h) | Dating error, median (h) | Dating error, 90th percentile (h) | Estimated times inside the stated range |
|---|---|---|---|---|---|---|
| 40 agents, defaults | 100% | 80%–**90%**–100% | 0.04–**0.06**–0.21 | 0.02 | 0.07 | 86%–**88%**–90% |
| 20 agents | 100% | 89%–**100%**–100% | 0.03–**0.05**–0.07 | 0.02–**0.03**–0.03 | 0.09–**0.10**–0.12 | 84%–**84%**–87% |
| 80 agents | 100% | 80%–**90%**–100% | 0.01–**0.05**–0.06 | 0.01–**0.01**–0.02 | 0.05 | 86%–**90%**–91% |
| 40 agents, 35% hold two tokens | 100% | 70%–**80%**–100% | 0.06–**0.15**–0.22 | 0.02 | 0.07–**0.07**–0.08 | 86%–**87%**–88% |
| 40 agents, 25% of reads hidden | 100% | 80%–**80%**–90% | 0.04–**0.07**–0.24 | 0.02 | 0.07 | 86%–**88%**–90% |
| 40 agents, many place-naming notes | 100% | 90%–**100%**–100% | 0.04–**0.06**–0.09 | 0.02 | 0.05–**0.07**–0.07 | 86%–**88%**–90% |
| 40 agents, no hidden reads, no notes | 100% | 90%–**90%**–100% | 0.02–**0.06**–0.40 | 0.02 | 0.07–**0.07**–0.08 | 85%–**87%**–89% |
| 40 agents, a time field on every record | 100% | 70%–**90%**–100% | 0.00–**0.01**–0.01 | – | – | – |
| 40 agents, real-world payload patterns | 100% | 50%–**80%**–100% | 0.04–**0.08**–1.15 | 0.02 | 0.06–**0.07**–0.09 | 84%–**87%**–88% |
| **all coordinated** | 100% | 50%–**90%**–100% | 0.00–**0.06**–1.15 | 0.01–**0.02**–0.03 | 0.05–**0.07**–0.12 | 84%–**87%**–91% |

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
| 20 agents | -0.18–**0.00**–0.07 | -2.84–**-1.15**–-0.49 | -0.02–**0.04**–0.22 |
| 80 agents | -0.05–**-0.00**–0.13 | -2.50–**-1.67**–-1.41 | -0.00–**0.04**–0.07 |
| 40 agents, 35% hold two tokens | -0.22–**-0.03**–0.55 | -2.87–**-2.17**–-0.54 | 0.03–**0.05**–0.07 |
| 40 agents, 25% of reads hidden | -0.21–**0.04**–0.24 | -2.94–**-2.06**–-0.56 | 0.03–**0.05**–0.09 |
| 40 agents, many place-naming notes | -0.13–**-0.05**–0.01 | -2.36–**-1.09**–-0.81 | -0.11–**0.05**–0.09 |
| 40 agents, no hidden reads, no notes | -0.10–**-0.01**–0.13 | -3.21–**-2.13**–-1.59 | -0.07–**0.02**–0.07 |
| 40 agents, a time field on every record | -0.00–**-0.00**–0.14 | -2.90–**-1.99**–-0.49 | 0.00–**0.01**–0.02 |
| 40 agents, real-world payload patterns | -0.10–**-0.08**–-0.05 | -5.68–**-2.11**–-1.00 | 0.02–**0.02**–0.10 |
| **all coordinated** | -0.22–**-0.01**–0.55 | -5.68–**-1.99**–-0.49 | -0.11–**0.04**–0.22 |

### Each early sign on the coordinated swarms

| sign | found | within 1 h of the truth | tool minus true time, h (min–median–max) |
|---|---|---|---|
| First message between agents | 45 of 45 | 45 of 45 | -0.22–**-0.01**–0.55 |
| First cloud metadata | 45 of 45 | 45 of 45 | -0.10–**-0.01**–0.02 |
| First hf dataset write | 45 of 45 | 45 of 45 | -0.22–**-0.04**–0.01 |
| First kubernetes api | 45 of 45 | 45 of 45 | -0.12–**-0.02**–0.04 |
| First registry board | 45 of 45 | 45 of 45 | -0.42–**-0.03**–0.11 |
| A group of 3+ agents linked by messages | 45 of 45 | 40 of 45 | -2.12–**-0.01**–2.96 |
| A group of 5+ agents linked by messages | 45 of 45 | 38 of 45 | -0.79–**-0.01**–3.08 |
| A group of 10+ agents linked by messages | 45 of 45 | 37 of 45 | -2.24–**-0.01**–2.04 |
| First two-way exchange | 45 of 45 | 33 of 45 | -0.12–**-0.00**–6.43 |
| A group of 20+ agents linked by messages | 41 of 41 | 24 of 41 | -4.27–**-0.06**–1.92 |

### Identity merge proposals, all runs pooled

| band | proposed | right | precision (95% range) | evidence on the wrong pairs |
|---|---|---|---|---|
| high | 12 | 12 | 100% (76%–100%) | – |
| medium | 60 | 60 | 100% (94%–100%) | – |
| low | 21717 | 207 | 1% (1%–1%) | same_programs 20322, handoff 14257, messages 2593, same_place 2128 |
| direct rule | 279 | 279 | 100% (99%–100%) | – |

### Benign baseline (15 swarms with no coordination)

Messages between different agents reported: 0; between two tokens of one agent: 0–**0**–5; records flagged harmful by the pack: 0–**45**–54; identity pairs proposed as high: 0.

| fires | what | runs | hours from the start |
|---|---|---|---|
| Watch: first single-actor harmful sign | default rule (watch) | 10 of 15 | 0.53–**1.27**–5.43 |
| Volume baseline: ordinary volume alarm | default rule (info) | 6 of 15 | 16.00–**18.50**–23.00 |
| Alert: 2 kinds of coordination | default rule (alert) | 2 of 15 | 5.36–**12.85**–20.33 |
| First Hugging Face dataset write | sign (single, harm) | 10 of 15 | 0.53–**1.27**–5.43 |
| First message between named actors | sign (joint, message) | 7 of 15 | 4.86–**10.94**–17.96 |
| Volume alarm on all actions | sign (baseline, baseline) | 4 of 15 | 16.00–**17.00**–20.00 |
| Volume alarm on harmful actions | sign (baseline, baseline) | 2 of 15 | 23.00 |
| First two-way exchange | sign (joint, two_way) | 2 of 15 | 5.36–**12.85**–20.33 |

### Default rules on the coordinated swarms: hours before the first true harmful action

| rule | hours before (min–median–max) |
|---|---|
| alert-coord2 | -5.68–**-1.99**–-0.49 |
| baseline-volume | -13.86–**-5.90**–-2.75 |
| watch-harm | -0.11–**0.04**–0.22 |

## Audited links on the real release

The simulated swarms cannot say whether a link on real data is a message. So we read the real ones.

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

**What follows.** On this release, "messages between named tokens" is not a finding yet: none of the reported links survives a reading. The app shows the same table under **Forensics → Test and export → Audited links (real data)**, with the 19 rows where the code and the reading disagree, each with its two records one click away. `GET /api/x/benchmark` returns it for the loaded session when that session is the release.

**The simulator now has these patterns.** The "real-world payload patterns" settings above reproduce them with exact truth. v1.1.0's rules and the current code on the same swarms (`python3 -m agenttrace.validation old-rules --worktree <checkout of v1.1.0>`, saved as `reports/validation/old_rules.json`; pooled over 5 seeds):

| setting | v1.1.0 rules | current code |
|---|---|---|
| 40 agents, defaults (the old simulator) | precision 79%, recall 73% | precision 79%, recall 73% (identical links) |
| 40 agents, real-world payload patterns | precision 66% (63%–69%), recall 57% (54%–60%) | precision 72% (68%–74%), recall 62% (59%–65%) |
| benign, real-world payload patterns (no true message) | 292 links, 282 between different agents | 9 links, 0 between different agents |

The old simulator could not tell the two versions apart. The new settings can: on the benign one v1.1.0 invents about 56 messages between agents per swarm and the current code none. They also show what the current code still gets wrong, with the same causes as on the real data: writes taken for reads (59 false links over the 5 coordinated swarms), writes not seen as writes (28 missed), and a place split in two because the pattern keeps the next path word after a repository number (`…] REPO 12]/resolve` and `…] REPO 12]/commit` become two places; this is among the 124 messages missed because write and read ended up on different places or the read was not seen).

**Limits of the audit.**

- **One labeller, tool-assisted.** The labels are by the authors' assistant reading the records with a helper script; nobody labelled them a second time. Disagreement between labellers is unmeasured.
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

Scored with `python3 -m agenttrace.benchmark run redacted_columns.csv`: of the 177 audited false links it reports none; it keeps the one audited true link and reports four more, which were then read (both records) and labelled true: an LFS upload followed by another token downloading the file, and three commits each followed by another token fetching that dataset's API entry. Those four labels were made after the rule change by the same labeller, so they are weaker evidence than the 178 made before it. The simulated real-world setting, which reproduces these payload shapes with exact truth, is the independent check: precision 79%, recall 79% (median), against 66% and 57% for the v1.1.0 rules; an intermediate version of this fix raised benign false links from 0 to 45 across five swarms and the simulator caught it before release.

What the release now shows (final rules, phase 1): **24 messages, 6 of them between named tokens (5 pairs)**; counted by estimated agent, 3 between agents and 3 inside one. The report submitted to the hackathon says 19; that figure is superseded.

### Phase 1: every delivery audited, a grade for each message, a second method (2026-11-13)

**All deliveries, not only the named ones.** The code reported 74 deliveries on the release; only 5 were between two named tokens, so the audit above said little about the rest. We read the other 69 the same way (both records, the judged call around each mention) and added them to `audited_links.json` with an `endpoint_kind` (`named_named` or `involves_run`, when either side is an anonymous `run:` endpoint). Of those 69: 6 were true messages, 28 were a GET of the place followed by a POST elsewhere, 9 were a "read" that is itself a commit, and 26 could not be decided (a record cut off before its verb, an LFS batch whose `operation` the redaction hid, a place that names only an owner). So the anonymous endpoints were mostly false or unreadable, as the named ones had been.

**Rule changes.** (1) A verb literal in a helper call (`Q('GET', src, …)`) is read from that call only, not from a POST later in the text. (2) A variable's later uses stop where the name is given another value. (3) A record cut off inside a call right after the place, or a bare URL, is not counted. (4) An LFS batch with no visible `operation` is not counted. (5) `…/<owner>/'+repo+'/…`, where the repository is a variable, names only an owner and is not counted. (6) A request written as data (`{"u": …, "m": "POST"}`) is judged by its method or body, and `Request(url, data=…)` is a write. The release now shows **24 deliveries, 6 of them between named tokens** (was 74 and 5). The simulator did not move: precision 79.4% and recall 73.0% on the default setting, 80.0% and 78.1% on the real-world setting, and 9 false links, none between agents, on the benign real-world setting, all as before the change.

**Score on the 258 audited links** (18 true messages, 177 read-then-post, 23 "read is a write", 9 downloads or `urlopen`, 4 different repositories, 27 unclear):

| group | reported | read as true | precision (95% range) |
|---|---|---|---|
| all deliveries | 24 (5 unclear) | 18 of 19 | 95% (75%–99%) |
| between two named tokens | 6 | 6 of 6 | 100% (61%–100%) |
| an anonymous run on one side | 18 (5 unclear) | 12 of 13 | 92% (67%–99%) |

The one false link is a script that writes a script that POSTs; the rule cannot see through it. **Read these as optimistic.** The rule was changed while looking at these same links, 7 of the 18 true links were added after the change, and many share one writer (an LFS upload read by seven later fetches; three commits read by one or two readers each). Recall is within the audited pool only.

**A grade on every message.** Each delivery now carries `grade` (the last column of `/api/messages`): *direct* (the write verb and the read verb are both in the very call that names the place), *inferred* (the verb was found through a variable, a helper, an LFS operation or nearby text) or *weak* (no verb found, a merged place, or an estimated time more than an hour from the other side). On the release: 0 direct, 4 inferred, 20 weak. Precision by grade does not separate. On the audit: inferred 3 of 3 (44%–100%), weak 15 of 16 (72%–99%). On the simulated swarms, pooled over 5 seeds (all 45 coordinated runs): direct 82% (46 of 56; 70%–90%), inferred 78% (2,088 of 2,670), weak 78% (4,745 of 6,057); on the real-world setting direct 82%, inferred 81% (175 of 217; 75%–85%), weak 80% (567 of 712; 77%–82%). The ranges overlap, so a reader should not trust one grade more than another; the grade records how the verb was found, nothing more. We tried also marking messages whose place had several earlier writers: it moved precision from 78% to 88% on only 5% of messages, so we left it out. The simulator's errors are the wrong write picked and one agent reading its own token's write, not a missing verb.

**A second method, not a second labeller.** `benchmark.independent_agreement` classifies each mention with a small tokenizer: it finds the call that holds the place, its arguments and any verb (following one variable, an options object, an LFS `operation`, a `data=` argument), and treats a request with no verb as a GET. It is written apart from `messages.judge_span`. Against our labels (unclear left out, 231 links): raw agreement 98% (226 of 231; 95%–99%), Cohen's kappa 0.83. It never calls a false link a message; its 5 misses are true links it cannot see (a commit path with the call cut at `POS`, a read in a loop, a GET with the place in a header-less wrapper). 27 links are unclear, and it calls 4 of them messages. We fixed the method twice after its first disagreements, so the agreement is flattering; it shows that a different reading of the text mostly lands where we did, not that the labels are right.

**What a reader may trust.** A message on this release is a lead that was checked once by one reader. Of the 6 between named tokens all were read as real; of those with an anonymous endpoint 12 of 13. Nothing here measures how many true messages are missed outside the pool.

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

- **The simulations were too easy once already.** v1.1.0 scored 79% message precision on them while 165 of its 166 links on the real release were false. The real-world settings close the gaps we found; there will be others.
- **The simulations are ours.** The generator was written by the same team as the tool, from the shapes we saw in one incident. Real swarms differ: other channels, other naming, mixed threads, retries, partial logs. These ranges describe how the tool behaves on swarms shaped like these, not its accuracy on yours. The strongest use of this page is relative: which settings hurt, which measures are fragile, and what a change to the rules does.
- **Some evidence is clean by construction.** In the simulation an agent's threads never contain another agent, so "same small thread" is perfect identity evidence here; real threads can mix. The direct-evidence rule's 100% is therefore an upper bound, while the old high band's 4% was a real failure on this kind of swarm, which the rule change fixed.
- **Truth of a sign is our definition.** Each sign's true time is computed from the truth with the same definition the tool uses (first message, first group of N, first harmful action of a kind). A different definition would move the timing errors.
- **The benign baseline is narrow.** Three kinds of benign swarm, 15 runs, one pack. Benign swarms that share a workspace, hand work to each other on purpose, or use one key for many agents would fire more. These are the first false-positive measurements the project has, not a false-positive rate for real deployments.
- **The default rules were written with hindsight** on the datasets their packs were made for; this page is the first test of them on swarms they were not written on.
- **Five seeds per setting** give ranges, not confidence intervals; the pooled identity figures carry 95% Wilson ranges.

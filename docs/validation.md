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

**The settings** (each with seeds 1–5, so 40 coordinated swarms of 660–3,260 records each):

| setting | what changes |
|---|---|
| 40 agents, defaults | 12% of agents hold two tokens; 8% of reads hidden; a few place-naming notes per agent; times embedded in 60% of records |
| 20 agents / 80 agents | swarm size |
| 35% hold two tokens | many more agents with a second identity |
| 25% of reads hidden | more messages the patterns cannot see |
| many place-naming notes | notes that name a place without reading it, about 5 per agent |
| no hidden reads, no notes | the clean case |
| a time field on every record | nothing has to be estimated |

**The benign baseline** (`groundtruth make --mode benign`, 2 settings × 5 seeds): 40 agents work in parallel sessions on their own tasks over the same 36 hours. They submit work to an evaluation API (the same boilerplate program for everyone), read public reference datasets that nobody in the swarm writes, and, in the first benign setting, half of them save results to a dataset of their own and read them back. No agent ever reads what another wrote, no token is carried, and the truth has **no messages between agents and no harmful records**. The second benign setting is read-only (no agent writes anywhere). A small benign swarm with its truth file ships in `agenttrace/samples/benign_swarm/` (12 agents, 361 records).

**What is scored** for each swarm:

- **Message links**: precision and recall of the tool's (write record → read record) messages, and of the pairs of agents those messages join (the tool's actors mapped back to the true agents).
- **Early signs**: for every sign the replay names (first message, first two-way exchange, groups of 3/5/10/20 agents, first harmful action of each kind), the truth's time for the same sign; the tool's error in hours and whether it is within one hour.
- **Dating**: for records whose time the tool estimated, the error against the true time, and the share that falls inside the range the tool states for that block (its 90th-percentile fit error), i.e. whether the stated uncertainty is honest.
- **Identity merges**: every pair the Agents tab proposes (`agenttrace.identity`, saved accept/reject decisions ignored), checked against which tokens truly belong to one agent: precision per confidence band (high, medium, low) and recall. We also measure a what-if rule on the same proposals: keep a pair only when it rests on *direct* evidence (both tokens in one record, in one small thread, or one carrying the other's token).
- **Default alert rules** (`agenttrace.live`, the three built-in rules): on coordinated swarms, when they fire relative to the first true message and the first true harmful action; on benign swarms, whether they fire at all.

## Headline

- **Messages**: across the 40 coordinated swarms the tool finds 57%–**73%**–80% of the true messages, and 66%–**79%**–88% of the messages it reports are true. At the level of who talked to whom it does better: pairs of agents 71%–**83%**–89% recall, 81%–**89%**–96% precision. Before two fixes made after the first run of this suite (below), message precision was 44%–**66%**–80% and pair precision 51%–**74%**–89%; recall did not change.
- **Harmful-action signs are exact**: first dataset write, first cluster call, first cloud-metadata call and first registry board are found in 40 of 40 swarms within an hour. **Coordination signs are close**: the first message between agents is within an hour of the truth in 40 of 40 swarms (24 of 40 before the fixes), groups of 3/5/10 in 34–36 of 40, the first two-way exchange in 30 of 40.
- **Dating is good and its stated range is nearly honest**: median error about 1 minute (0.01–0.03 h), 90th percentile 3–7 minutes; 84%–**87%**–91% of estimated times fall inside the stated 90% range (slightly under the 90% it promises).
- **Identity merging, before and after a fix.** The first version labelled pairs **high** on coordination evidence alone (a shared place, handoffs, shared programs); pooled over these swarms those were right **4% of the time (10 of 240)**. Pairs with direct evidence (the same record, a small shared thread, or a carried token) were right in every case. The rule now requires direct evidence for high and medium. After the change, pooled over all 50 swarms: **high 10 of 10 right, medium 51 of 51**, and the rest stay low (about 1% right), so the low band should be read as "worth a look", not as a merge.
- **On benign swarms**: the tool reports **no** message between two different agents (0 in all 10). Program-reuse signs no longer fire (0 of 10; they fired in 10 of 10 before the fix). The default rules fire: "Watch: first harmful sign" in 5 of 10 (all 5 swarms whose agents save results: the code-traces pack counts any dataset commit as harmful), "Alert: 2 kinds of coordination" in 2 of 10 (one agent's two tokens reading back its own results, counted as a message, plus a second link sign), and the volume baseline in 3 of 10.

### The fixes this suite and a manual audit led to

1. **A place named only in a code comment is not a read.** Notes such as `// the crew says <dataset> has the plan; not fetching it yet` were counted as reads, and the harm patterns matched them too ("first registry board" fired a median 9 hours early). Mentions inside a comment (a line starting with `//`, `#`, `/*` or `*`, or a `//` / `# ` after whitespace) no longer count as reads, writes or actions. Message precision rose from 66% to 79% (median) and the registry-board sign moved to within an hour of the truth in 40 of 40 swarms.
2. **The verb nearest the mention decides, and the window stops at the next place.** A manual audit of the earliest links on the Swarm Traces release found three artefacts the simulations do not have: a GET followed within 260 characters by a POST to a *different* dataset was charged as a write to the first; an LFS batch with `operation:'download'` (a POST) was taken for a write; and the redaction's `[REDACTED:username:N]] REPO K]` kept a repository number the place pattern dropped, so writes and reads of different repositories under one owner looked like one place. With the nearest request verb deciding, read verbs (GET, HEAD, LFS download) recognised, the code window clipped at the next place mention, and the repository number kept, the named messages on the release fell from 166 to 107. A second audit of those 107 found that most were two tokens fetching the same dataset and POSTing what they read to a collector: the POST, the nearest verb, made the read a write. Clipping the window at the start of the next request call (`fetch(`, `.open(`, `urlopen(`, `requests.post(` …) and recognising `urlopen`/`.read()` as reads leaves **19 messages in 12 pairs among 9 tokens**, each checked by hand (a Python `urlopen(url)` with one argument is a read; `urlopen(Request(url, data))` is a write). The simulated scores did not move, which is itself a finding: the simulator lacks these artefacts.

3. **Routine program reuse is not a sign of shared control.** A program run by several actors now counts as a coordination sign only if it writes to a place, reads a place another actor wrote, or does something the pack calls harmful. The evaluation's submit call, a token check, or two agents fetching the same public file are listed as routine. Program-reuse signs on benign swarms fell from 10 of 10 to 0 of 10. On the Swarm Traces release 40 of the 253 shared programs remain signs.

## Results

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
| **all coordinated** | 66%–**79%**–88% | 57%–**73%**–80% | 81%–**89%**–96% | 71%–**83%**–89% |

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
| **all coordinated** | 100% | 70%–**90%**–100% | 0.00–**0.06**–0.40 | 0.01–**0.02**–0.03 | 0.05–**0.07**–0.12 | 84%–**87%**–91% |

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
| benign: 40 agents, half save results | – | 100% | 1%–**1%**–1% | 0 | 0% | 43%–**75%**–100% | 100% | 43%–**75%**–100% | 2–**5**–9 |
| benign: 40 agents, read-only | – | – | 0%–**0%**–1% | 0 | 0% | 20%–**33%**–75% | 100% | 20%–**33%**–75% | 2–**5**–9 |
| **all coordinated** | 100% | 100% | 0%–**1%**–5% | 0–**0**–1 | 0%–**0%**–33% | 60%–**80%**–100% | 100% | 60%–**80%**–100% | 0–**5.5**–20 |

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
| **all coordinated** | -0.22–**-0.00**–0.55 | -3.21–**-1.84**–-0.49 | -0.11–**0.05**–0.22 |

### Each early sign on the coordinated swarms

| sign | found | within 1 h of the truth | tool minus true time, h (min–median–max) |
|---|---|---|---|
| First message between agents | 40 of 40 | 40 of 40 | -0.22–**-0.00**–0.55 |
| First cloud metadata | 40 of 40 | 40 of 40 | -0.08–**-0.01**–0.02 |
| First hf dataset write | 40 of 40 | 40 of 40 | -0.22–**-0.04**–0.01 |
| First kubernetes api | 40 of 40 | 40 of 40 | -0.06–**-0.02**–0.04 |
| First registry board | 40 of 40 | 40 of 40 | -0.42–**-0.03**–0.11 |
| A group of 3+ agents linked by messages | 40 of 40 | 36 of 40 | -2.12–**-0.01**–2.06 |
| A group of 10+ agents linked by messages | 40 of 40 | 35 of 40 | -2.24–**-0.01**–1.63 |
| A group of 5+ agents linked by messages | 40 of 40 | 34 of 40 | -0.79–**-0.01**–2.60 |
| First two-way exchange | 40 of 40 | 30 of 40 | -0.12–**-0.00**–6.43 |
| A group of 20+ agents linked by messages | 36 of 36 | 21 of 36 | -4.27–**-0.15**–1.92 |

### Identity merge proposals, all runs pooled

| band | proposed | right | precision (95% range) | evidence on the wrong pairs |
|---|---|---|---|---|
| high | 10 | 10 | 100% (72%–100%) | – |
| medium | 51 | 51 | 100% (93%–100%) | – |
| low | 18492 | 186 | 1% (1%–1%) | same_programs 17457, handoff 12477, messages 2333, same_place 1544 |
| direct rule | 247 | 247 | 100% (98%–100%) | – |

### Benign baseline (10 swarms with no coordination)

Messages between different agents reported: 0; between two tokens of one agent: 0–**0**–5; records flagged harmful by the pack: 0–**22.5**–52; identity pairs proposed as high: 0.

| fires | what | runs | hours from the start |
|---|---|---|---|
| Watch: first single-actor harmful sign | default rule (watch) | 5 of 10 | 0.53–**0.70**–5.43 |
| Volume baseline: ordinary volume alarm | default rule (info) | 3 of 10 | 17.00–**20.00**–23.00 |
| Alert: 2 kinds of coordination | default rule (alert) | 2 of 10 | 5.36–**12.85**–20.33 |
| First Hugging Face dataset write | sign (single, harm) | 5 of 10 | 0.53–**0.70**–5.43 |
| First message between named actors | sign (joint, message) | 3 of 10 | 4.86–**10.94**–12.70 |
| Volume alarm on all actions | sign (baseline, baseline) | 2 of 10 | 17.00–**18.50**–20.00 |
| First two-way exchange | sign (joint, two_way) | 2 of 10 | 5.36–**12.85**–20.33 |
| Volume alarm on harmful actions | sign (baseline, baseline) | 1 of 10 | 23.00 |

### Default rules on the coordinated swarms: hours before the first true harmful action

| rule | hours before (min–median–max) |
|---|---|
| alert-coord2 | -3.21–**-1.84**–-0.49 |
| baseline-volume | -13.86–**-5.93**–-2.75 |
| watch-harm | -0.11–**0.05**–0.22 |

## What the numbers mean

- **Message precision is limited mainly by one thing a pattern cannot know**: whether a read fetched the newest message or an older one. Before the comment fix, records that only named a place were about half of all false links. Pairs of agents are more reliable than single messages because a wrong message often joins the right two agents.
- **Coordination signs are early, not late.** For an early-warning tool that is the safer direction, but it means a sign's time is an upper bound on when coordination started only after checking the records behind it. The Early flag tab links each sign to its record; look at it before quoting the time.
- **The "2 kinds of coordination" alert** fired before any true message in the coordinated swarms when boilerplate reuse counted as a sign; see the alert table above for the current timing. On benign swarms it now fires in 2 of 10 (was 3). As a detector it is noisy; as a prompt to look it is cheap.
- **The identity confidence bands do not mean what their names say** on swarms like these. A shared self-chosen place, a handoff and shared programs are evidence of *coordination*; in a coordinating swarm they join different agents far more often than one agent's two tokens. With 40 agents active over 36 hours, one agent stopping and another starting within 15 minutes happens by chance many times.
- **Benign swarms do not produce false messages between agents**, which is the core claim of the message reconstruction. They do produce warning signs, all traceable: a pack that calls every dataset commit harmful, and one agent's two tokens looking like two actors.

## Recommendations (from these measurements)

1. **Identity (`agenttrace/identity.py`)**: require at least one direct item (same record, same small thread, carried token) for "high"; cap pairs without one at "low" (or relabel the bands "strong / some / weak evidence" until they are calibrated). Discount handoffs by their chance rate given how many actors are active, and do not count a shared place or shared programs as identity evidence when the place also carries messages between the two (that is coordination). Re-run this suite after the change; the target is high ≥ 80% precision.
2. **Program signs** (done): routine reuse (no write, no read of a place another actor wrote, nothing harmful) is no longer a sign.
3. **Self-messages**: a message between two actors that the Agents tab already proposes as one agent should not count toward "2 kinds of coordination" or "first message".
4. **Pack harm list**: in the code-traces pack, "hf_dataset_write" marks every dataset commit as harmful; on a benign swarm that saves results this alone fires the watch rule. Keep it for the incident it was written for, but say so in the rule, or narrow it to writes into places others read.
5. **Notes that name a place** (done): mentions inside code comments no longer count as reads, writes or actions.

## Honest limits

- **The simulations are ours.** The generator was written by the same team as the tool, from the shapes we saw in one incident. Real swarms differ: other channels, other naming, mixed threads, retries, partial logs. These ranges describe how the tool behaves on swarms shaped like these, not its accuracy on yours. The strongest use of this page is relative: which settings hurt, which measures are fragile, and what a change to the rules does.
- **Some evidence is clean by construction.** In the simulation an agent's threads never contain another agent, so "same small thread" is perfect identity evidence here; real threads can mix. The direct-evidence rule's 100% is therefore an upper bound, while the old high band's 4% was a real failure on this kind of swarm, which the rule change fixed.
- **Truth of a sign is our definition.** Each sign's true time is computed from the truth with the same definition the tool uses (first message, first group of N, first harmful action of a kind). A different definition would move the timing errors.
- **The benign baseline is narrow.** Two kinds of benign swarm, 10 runs, one pack. Benign swarms that share a workspace, hand work to each other on purpose, or use one key for many agents would fire more. These are the first false-positive measurements the project has, not a false-positive rate for real deployments.
- **The default rules were written with hindsight** on the datasets their packs were made for; this page is the first test of them on swarms they were not written on.
- **Five seeds per setting** give ranges, not confidence intervals; the pooled identity figures carry 95% Wilson ranges.

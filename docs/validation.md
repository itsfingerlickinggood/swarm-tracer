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

- **Messages**: across the 40 coordinated swarms the tool finds 56%–**73%**–80% of the true messages, and 44%–**66%**–80% of the messages it reports are true. At the level of who talked to whom it does better: pairs of agents 73%–**83%**–89% recall, 51%–**74%**–89% precision. The clean setting reaches 76% precision; place-naming notes pull precision down to about 49%.
- **Harmful-action signs are exact**: first dataset write, first cluster call and first cloud-metadata call are found in 40 of 40 swarms within an hour (median error under 3 minutes). **Coordination signs run early**: first message, first two-way exchange and groups of 3/5/10/20 are within an hour in 4–29 of 40 swarms (36 for groups of 20) and usually *before* the truth, because a false message (a note, an older message matched to a read) comes first. "First registry board" fires a median 9 hours early, on a note that merely names a board.
- **Dating is good and its stated range is nearly honest**: median error about 1 minute (0.01–0.03 h), 90th percentile 3–7 minutes; 84%–**87%**–91% of estimated times fall inside the stated 90% range (slightly under the 90% it promises).
- **Identity merging, before and after a fix.** The first version labelled pairs **high** on coordination evidence alone (a shared place, handoffs, shared programs); pooled over these swarms those were right **4% of the time (10 of 240)**. Pairs with direct evidence (the same record, a small shared thread, or a carried token) were right in every case. The rule now requires direct evidence for high and medium. After the change, pooled over all 50 swarms: **high 10 of 10 right, medium 51 of 51**, and the rest stay low (about 1% right), so the low band should be read as "worth a look", not as a merge.
- **On benign swarms**: the tool reports **no** message between two different agents (0 in all 10), but every benign swarm fires the "program reused" and "program run by three actors" signs (the shared submission boilerplate), and the default rules fire: "Watch: first harmful sign" in 5 of 10 (all 5 swarms whose agents save results: the code-traces pack counts any dataset commit as harmful), "Alert: 2 kinds of coordination" in 3 of 10 (boilerplate program reuse plus one agent's two tokens reading back its own results, counted as a message), and the volume baseline in 3 of 10. The read-only benign swarms fire only the volume baseline (1 of 5).

## Results

Generated 2026-11-08T22:44:02Z by `python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5`. 40 coordinated and 10 benign simulated swarms. Cells are min–**median**–max over seeds; one value means all seeds agree.

### Messages

| setting | Message links: precision | Message links: recall | Agent pairs: precision | Agent pairs: recall |
|---|---|---|---|---|
| 40 agents, defaults | 64%–**67%**–71% | 67%–**75%**–77% | 72%–**76%**–77% | 83%–**85%**–86% |
| 20 agents | 64%–**66%**–72% | 68%–**69%**–77% | 72%–**80%**–86% | 80%–**84%**–88% |
| 80 agents | 65%–**68%**–69% | 67%–**73%**–75% | 71%–**74%**–75% | 78%–**81%**–84% |
| 40 agents, 35% hold two tokens | 54%–**62%**–66% | 63%–**66%**–76% | 66%–**72%**–76% | 77%–**82%**–83% |
| 40 agents, 25% of reads hidden | 62%–**63%**–68% | 56%–**61%**–65% | 70%–**76%**–76% | 73%–**76%**–78% |
| 40 agents, many place-naming notes | 44%–**49%**–54% | 68%–**75%**–78% | 51%–**55%**–60% | 81%–**86%**–88% |
| 40 agents, no hidden reads, no notes | 73%–**76%**–80% | 73%–**74%**–80% | 82%–**86%**–89% | 83%–**86%**–89% |
| 40 agents, a time field on every record | 63%–**68%**–70% | 69%–**73%**–75% | 72%–**73%**–79% | 82%–**85%**–88% |
| **all coordinated** | 44%–**66%**–80% | 56%–**73%**–80% | 51%–**74%**–89% | 73%–**83%**–89% |

### Timing and dating

| setting | Early signs found | Signs within 1 h of the truth | Sign timing error, median (h) | Dating error, median (h) | Dating error, 90th percentile (h) | Estimated times inside the stated range |
|---|---|---|---|---|---|---|
| 40 agents, defaults | 100% | 40%–**50%**–80% | 0.12–**1.13**–1.43 | 0.02 | 0.07 | 86%–**88%**–90% |
| 20 agents | 100% | 50%–**78%**–89% | 0.04–**0.12**–1.16 | 0.02–**0.03**–0.03 | 0.09–**0.10**–0.12 | 84%–**84%**–87% |
| 80 agents | 100% | 30%–**60%**–70% | 0.05–**0.69**–1.86 | 0.01–**0.01**–0.02 | 0.05 | 86%–**90%**–91% |
| 40 agents, 35% hold two tokens | 100% | 30%–**60%**–70% | 0.16–**0.22**–1.43 | 0.02 | 0.07–**0.07**–0.08 | 86%–**87%**–88% |
| 40 agents, 25% of reads hidden | 100% | 30%–**60%**–80% | 0.14–**0.90**–1.45 | 0.02 | 0.07 | 86%–**88%**–90% |
| 40 agents, many place-naming notes | 100% | 40%–**50%**–70% | 0.55–**1.69**–2.45 | 0.02 | 0.05–**0.07**–0.07 | 86%–**88%**–90% |
| 40 agents, no hidden reads, no notes | 100% | 90%–**90%**–100% | 0.02–**0.06**–0.40 | 0.02 | 0.07–**0.07**–0.08 | 85%–**87%**–89% |
| 40 agents, a time field on every record | 100% | 40%–**60%**–80% | 0.00–**0.75**–1.40 | – | – | – |
| **all coordinated** | 100% | 30%–**60%**–100% | 0.00–**0.70**–2.45 | 0.01–**0.02**–0.03 | 0.05–**0.07**–0.12 | 84%–**87%**–91% |

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
| 40 agents, defaults | -10.17–**-3.94**–-1.58 | -0.12–**3.45**–8.33 | 5.75–**9.28**–9.80 |
| 20 agents | -8.78–**-3.79**–-0.24 | -2.28–**3.30**–7.63 | 0.04–**9.03**–9.80 |
| 80 agents | -9.15–**-7.72**–-6.44 | 4.81–**5.69**–7.87 | 8.11–**8.72**–9.02 |
| 40 agents, 35% hold two tokens | -10.17–**-3.97**–-1.53 | -0.17–**3.48**–8.33 | 5.82–**9.27**–9.75 |
| 40 agents, 25% of reads hidden | -10.17–**-3.94**–-1.58 | -0.12–**3.45**–8.33 | 5.75–**9.28**–9.80 |
| 40 agents, many place-naming notes | -10.07–**-9.73**–-8.98 | 6.54–**8.59**–9.04 | 8.74–**9.14**–10.60 |
| 40 agents, no hidden reads, no notes | -2.68–**-0.50**–-0.18 | -2.00–**-1.32**–-0.40 | -0.07–**0.02**–0.07 |
| 40 agents, a time field on every record | -10.07–**-3.82**–-1.60 | -0.10–**3.33**–8.23 | 5.78–**9.20**–9.79 |
| **all coordinated** | -10.17–**-5.21**–-0.18 | -2.28–**3.88**–9.04 | -0.07–**9.05**–10.60 |

### Each early sign on the coordinated swarms

| sign | found | within 1 h of the truth | tool minus true time, h (min–median–max) |
|---|---|---|---|
| First cloud metadata | 40 of 40 | 40 of 40 | -0.08–**-0.01**–0.02 |
| First hf dataset write | 40 of 40 | 40 of 40 | -0.22–**-0.04**–0.01 |
| First kubernetes api | 40 of 40 | 40 of 40 | -0.06–**-0.02**–0.04 |
| First two-way exchange | 40 of 40 | 29 of 40 | -5.99–**-0.00**–5.61 |
| A group of 3+ agents linked by messages | 40 of 40 | 27 of 40 | -2.84–**-0.30**–0.80 |
| First message between agents | 40 of 40 | 24 of 40 | -2.52–**-0.41**–0.26 |
| A group of 5+ agents linked by messages | 40 of 40 | 23 of 40 | -3.44–**-0.73**–0.79 |
| A group of 10+ agents linked by messages | 40 of 40 | 14 of 40 | -5.05–**-1.55**–0.87 |
| First registry board | 40 of 40 | 6 of 40 | -10.64–**-9.10**–0.07 |
| A group of 20+ agents linked by messages | 36 of 36 | 4 of 36 | -5.98–**-1.98**–-0.35 |

### Identity merge proposals, all runs pooled

| band | proposed | right | precision (95% range) | evidence on the wrong pairs |
|---|---|---|---|---|
| high | 10 | 10 | 100% (72%–100%) | – |
| medium | 51 | 51 | 100% (93%–100%) | – |
| low | 18604 | 186 | 1% (1%–1%) | same_programs 17569, handoff 12477, messages 2905, same_place 1545 |
| direct rule | 247 | 247 | 100% (98%–100%) | – |

### Benign baseline (10 swarms with no coordination)

Messages between different agents reported: 0; between two tokens of one agent: 0–**0**–5; records flagged harmful by the pack: 0–**22.5**–52; identity pairs proposed as high: 0.

| fires | what | runs | hours from the start |
|---|---|---|---|
| Watch: first single-actor harmful sign | default rule (watch) | 5 of 10 | 0.53–**0.70**–5.43 |
| Alert: 2 kinds of coordination | default rule (alert) | 3 of 10 | 4.86–**10.94**–12.70 |
| Volume baseline: ordinary volume alarm | default rule (info) | 3 of 10 | 17.00–**20.00**–23.00 |
| First program reused by another actor | sign (joint, program) | 10 of 10 | 0.22–**1.59**–2.72 |
| First program run by three actors | sign (joint, program) | 10 of 10 | 2.13–**3.80**–6.92 |
| First Hugging Face dataset write | sign (single, harm) | 5 of 10 | 0.53–**0.70**–5.43 |
| First message between named actors | sign (joint, message) | 3 of 10 | 4.86–**10.94**–12.70 |
| Volume alarm on all actions | sign (baseline, baseline) | 2 of 10 | 17.00–**18.50**–20.00 |
| First two-way exchange | sign (joint, two_way) | 2 of 10 | 5.36–**12.85**–20.33 |
| Volume alarm on harmful actions | sign (baseline, baseline) | 1 of 10 | 23.00 |

### Default rules on the coordinated swarms: hours before the first true harmful action

| rule | hours before (min–median–max) |
|---|---|
| alert-coord2 | -2.28–**3.88**–9.04 |
| baseline-volume | -10.51–**-5.51**–-2.75 |
| watch-harm | -0.07–**9.05**–10.60 |


## What the numbers mean

- **Message precision is limited by two things a pattern cannot know**: whether a read fetched the newest message or an older one (over a third of the false links and over half of the missed ones over the suite), and whether a record that names a place actually read it (about half of all false links). Pairs of agents are more reliable than single messages because a wrong message often joins the right two agents.
- **Coordination signs are early, not late.** For an early-warning tool that is the safer direction, but it means a sign's time is an upper bound on when coordination started only after checking the records behind it. The Early flag tab links each sign to its record; look at it before quoting the time.
- **The "2 kinds of coordination" alert fires before any true message** in the coordinated swarms (a median 5 hours before), and on 3 of 10 benign swarms. Its two kinds are usually "program reused" (boilerplate) and a shared place or a false message. As a detector it is noisy; as a prompt to look it is cheap.
- **The identity confidence bands do not mean what their names say** on swarms like these. A shared self-chosen place, a handoff and shared programs are evidence of *coordination*; in a coordinating swarm they join different agents far more often than one agent's two tokens. With 40 agents active over 36 hours, one agent stopping and another starting within 15 minutes happens by chance many times.
- **Benign swarms do not produce false messages between agents**, which is the core claim of the message reconstruction. They do produce warning signs, all traceable: shared boilerplate programs, a pack that calls every dataset commit harmful, and one agent's two tokens looking like two actors.

## Recommendations (from these measurements)

1. **Identity (`agenttrace/identity.py`)**: require at least one direct item (same record, same small thread, carried token) for "high"; cap pairs without one at "low" (or relabel the bands "strong / some / weak evidence" until they are calibrated). Discount handoffs by their chance rate given how many actors are active, and do not count a shared place or shared programs as identity evidence when the place also carries messages between the two (that is coordination). Re-run this suite after the change; the target is high ≥ 80% precision.
2. **Program signs**: do not count a program as "reused" when it is the dominant template (run by most active actors, or matching the solo intent such as the evaluation submission); the benign swarms fire these signs every time.
3. **Self-messages**: a message between two actors that the Agents tab already proposes as one agent should not count toward "2 kinds of coordination" or "first message".
4. **Pack harm list**: in the code-traces pack, "hf_dataset_write" marks every dataset commit as harmful; on a benign swarm that saves results this alone fires the watch rule. Keep it for the incident it was written for, but say so in the rule, or narrow it to writes into places others read.
5. **Notes that name a place**: a mention in a comment matches the "registry board" harm intent and fires that sign hours early; the intent patterns could ignore commented lines.

## Honest limits

- **The simulations are ours.** The generator was written by the same team as the tool, from the shapes we saw in one incident. Real swarms differ: other channels, other naming, mixed threads, retries, partial logs. These ranges describe how the tool behaves on swarms shaped like these, not its accuracy on yours. The strongest use of this page is relative: which settings hurt, which measures are fragile, and what a change to the rules does.
- **Some evidence is clean by construction.** In the simulation an agent's threads never contain another agent, so "same small thread" is perfect identity evidence here; real threads can mix. The direct-evidence rule's 100% is therefore an upper bound, while the old high band's 4% was a real failure on this kind of swarm, which the rule change fixed.
- **Truth of a sign is our definition.** Each sign's true time is computed from the truth with the same definition the tool uses (first message, first group of N, first harmful action of a kind). A different definition would move the timing errors.
- **The benign baseline is narrow.** Two kinds of benign swarm, 10 runs, one pack. Benign swarms that share a workspace, hand work to each other on purpose, or use one key for many agents would fire more. These are the first false-positive measurements the project has, not a false-positive rate for real deployments.
- **The default rules were written with hindsight** on the datasets their packs were made for; this page is the first test of them on swarms they were not written on.
- **Five seeds per setting** give ranges, not confidence intervals; the pooled identity figures carry 95% Wilson ranges.

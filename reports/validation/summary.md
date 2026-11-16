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


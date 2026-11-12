Generated 2026-11-12T19:57:39Z by `python3 -m agenttrace.validation run --out reports/validation --seeds 1 2 3 4 5`. 45 coordinated and 15 benign simulated swarms. Cells are min–**median**–max over seeds; one value means all seeds agree.

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
| 40 agents, real-world payload patterns | 75%–**79%**–83% | 73%–**79%**–81% | 89%–**90%**–91% | 85%–**89%**–91% |
| **all coordinated** | 66%–**79%**–88% | 57%–**73%**–81% | 81%–**89%**–96% | 71%–**83%**–91% |

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
| 40 agents, real-world payload patterns | 100% | 80%–**100%**–100% | 0.03–**0.04**–0.10 | 0.02 | 0.06–**0.07**–0.09 | 84%–**87%**–88% |
| **all coordinated** | 100% | 70%–**90%**–100% | 0.00–**0.05**–0.40 | 0.01–**0.02**–0.03 | 0.05–**0.07**–0.12 | 84%–**87%**–91% |

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
| A group of 3+ agents linked by messages | 45 of 45 | 41 of 45 | -2.12–**-0.01**–2.06 |
| A group of 10+ agents linked by messages | 45 of 45 | 39 of 45 | -2.24–**-0.02**–1.63 |
| A group of 5+ agents linked by messages | 45 of 45 | 39 of 45 | -0.79–**-0.01**–2.60 |
| First two-way exchange | 45 of 45 | 34 of 45 | -0.12–**-0.00**–6.43 |
| A group of 20+ agents linked by messages | 41 of 41 | 25 of 41 | -4.27–**-0.18**–1.92 |

### Identity merge proposals, all runs pooled

| band | proposed | right | precision (95% range) | evidence on the wrong pairs |
|---|---|---|---|---|
| high | 12 | 12 | 100% (76%–100%) | – |
| medium | 60 | 60 | 100% (94%–100%) | – |
| low | 21721 | 207 | 1% (1%–1%) | same_programs 20326, handoff 14257, messages 2625, same_place 2128 |
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


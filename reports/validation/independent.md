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


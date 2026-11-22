# Who&When: the tool measured against someone else's labels

Source: <https://github.com/ag2ai/Agents_Failure_Attribution> at revision `1bcbbd96ba563400cededae6189833b8ea59dcae`. Licence: MIT (LICENSE in the repository: Copyright (c) 2025 Ming Yin).
Labels made by: human annotators: the agent and the step that caused the failure, with a reason.
Measured on 2026-11-22 with Swarm Tracer 2.3.0; `earlywarn.py` and `baselines.py` run as they were that day (hashes in `results.json`). Rebuild: `python3 -I agenttrace/failure_eval.py who_and_when`.

Loaded: **184 runs, 4,092 records**. 689 records name their recipient in the log.

Every run is one small cooperative team on one task: not an attack and not a swarm. A share is runs out of runs.

## Who talked to whom

A pair is (sender, recipient) inside one run. A message is one record and its recipient.

| Layout | Runs | Logged messages with a recipient | Recipients kept: listed as a direct message | Withheld: logged pairs the tool finds | Withheld: the tool's pairs that are logged | ...logged in either direction | Withheld: logged messages the tool finds |
|---|---|---|---|---|---|---|---|
| Algorithm-Generated | 126 | 0 (the log names no recipient) | – | – | – | – | – |
| Hand-Crafted | 58 | 689 | 689 of 689 (100.0%, 95% interval 99.4 to 100.0%) | 91 of 92 (98.9%, 95% interval 94.1 to 99.8%) | 91 of 237 (38.4%, 95% interval 32.4 to 44.7%) | 180 of 237 (75.9%, 95% interval 70.1 to 80.9%) | 62 of 689 (9.0%, 95% interval 7.1 to 11.4%) |

Kept is a check of the reader and the direct-message path, not an accuracy. Withheld is the measurement: the tool sees only who spoke, in what order, and the text, and links a speaker to whoever posted before in the same conversation. The logs address only some messages (an instruction, not the answer to it), so a pair of the tool's that is not logged is not shown to be wrong; the either-direction column counts a pair whose reverse is logged. Each write counts once per reader, so the tool finds the pair far more often than the single message. Pairs and messages inside a run are not independent, so these intervals are too narrow.

## As logged, without times

Algorithm-Generated, Hand-Crafted: no record has a time. Loaded as logged, 0 of 184 runs are dated, the tool holds 689 logged messages as undated and puts 0 of them in the who-talked-to-whom graph, and no sign or rule can fire (0 runs). Everything else on these layouts uses the step clock.

## Who failed, and when

The tool has no failure-attribution feature. Two rules, fixed before scoring, read its flags as blame.

| Method | Names someone | Agent right | Step right |
|---|---|---|---|
| Tool: record of its first warning sign | 183 of 184 (99.5%, 95% interval 97.0 to 99.9%) | 54 of 184 (29.3%, 95% interval 23.2 to 36.3%) | 25 of 184 (13.6%, 95% interval 9.4 to 19.3%) |
| Tool: its first harmful record | 40 of 184 (21.7%, 95% interval 16.4 to 28.2%) | 13 of 184 (7.1%, 95% interval 4.2 to 11.7%) | 1 of 184 (0.5%, 95% interval 0.1 to 3.0%) |
| Baseline: the agent with most records | 184 of 184 (100.0%, 95% interval 98.0 to 100.0%) | 72 of 184 (39.1%, 95% interval 32.4 to 46.3%) | – |
| Baseline: step 0 | 184 of 184 (100.0%, 95% interval 98.0 to 100.0%) | 62 of 184 (33.7%, 95% interval 27.3 to 40.8%) | 20 of 184 (10.9%, 95% interval 7.1 to 16.2%) |
| Baseline: the last step | 184 of 184 (100.0%, 95% interval 98.0 to 100.0%) | 80 of 184 (43.5%, 95% interval 36.5 to 50.7%) | 8 of 184 (4.3%, 95% interval 2.2 to 8.3%) |

Chance: agent 29.1%, step 9.5% (the mean over runs of 1 / agents in the run and 1 / steps in the run). For scale, the dataset's paper reports 53.5% and 14.2% for its best method (abstract of arXiv:2505.00212: the best method there, an LLM reading the whole log); we did not re-measure that.

- Algorithm-Generated (126 runs): first sign, agent 36 of 126 (28.6%, 95% interval 21.4 to 37.0%), step 24 of 126 (19.1%, 95% interval 13.1 to 26.8%); first harmful record, agent 4 of 126 (3.2%, 95% interval 1.2 to 7.9%), step 1 of 126 (0.8%, 95% interval 0.1 to 4.4%).
- Hand-Crafted (58 runs): first sign, agent 18 of 58 (31.0%, 95% interval 20.6 to 43.8%), step 1 of 58 (1.7%, 95% interval 0.3 to 9.1%); first harmful record, agent 9 of 58 (15.5%, 95% interval 8.4 to 26.9%), step 0 of 58 (0.0%, 95% interval 0.0 to 6.2%).

## False alarms on benign runs

A default rule fired in 182 of 184 (98.9%, 95% interval 96.1 to 99.7%) of runs with the pack the tool picks by itself, and in 182 of 184 (98.9%, 95% interval 96.1 to 99.7%) with the general pack.

| Layout | Clock | Pack picked | Watch (first harmful sign) | Alert (2 kinds of coordination) | Volume baseline |
|---|---|---|---|---|---|
| Algorithm-Generated | step clock | chat.json (126) | 23 of 126 (18.3%, 12.5 to 25.9%) | 124 of 126 (98.4%, 94.4 to 99.6%) | 0 of 126 (0.0%, 0.0 to 3.0%) |
| Hand-Crafted | step clock | generic.json (58) | 17 of 58 (29.3%, 19.2 to 42.0%) | 57 of 58 (98.3%, 90.9 to 99.7%) | 0 of 58 (0.0%, 0.0 to 6.2%) |

The Alert rule fires on almost any team that talks: it detects information flow, not malice. The hourly baselines need 6 to 12 hours of history and these runs are shorter, so their zeros say nothing. On the step clock a rate per 24 h has no meaning and none is given.

## What this does not show

- Accuracy on a swarm, on an attack, or on contact through shared places. These are turn-taking teams; the tool's deliveries here rest on who posted after whom in one conversation.
- Anything about timing on the step clock, which is order only.
- That the labels are right. In a few runs the labelled step was not spoken by the labelled agent (see `results.json`).

Credit: Zhang et al., "Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems", ICML 2025, arXiv:2505.00212; data: github.com/ag2ai/Agents_Failure_Attribution (MIT)

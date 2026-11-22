# MAST-Data (MAD): the tool measured against someone else's labels

Source: <https://huggingface.co/datasets/mcemri/MAST-Data> at revision `95118ac951421753cf1deb87ddea3b01e693c41b`. Licence: CC BY 4.0 (licence tag on the dataset card).
Labels made by: an LLM judge (the dataset card: "not by human labelling"): 14 failure modes per run, 0 / 1.
Measured on 2026-11-22 with Swarm Tracer 2.3.0; `earlywarn.py` and `baselines.py` run as they were that day (hashes in `results.json`). Rebuild: `python3 -I agenttrace/failure_eval.py mast_data`.

Loaded: **1,640 runs, 37,805 records**. 13,441 records name their recipient in the log.

Every run is one small cooperative team on one task: not an attack and not a swarm. A share is runs out of runs.

Parsed 1,640 of 1,642 runs (2 have no framework header in their text). 81,315 log blocks that are not agent turns were left out.

## Who talked to whom

A pair is (sender, recipient) inside one run. A message is one record and its recipient.

| Layout | Runs | Logged messages with a recipient | Recipients kept: listed as a direct message | Withheld: logged pairs the tool finds | Withheld: the tool's pairs that are logged | ...logged in either direction | Withheld: logged messages the tool finds |
|---|---|---|---|---|---|---|---|
| AG2 | 597 | 0 (the log names no recipient) | – | – | – | – | – |
| AppWorld | 30 | 460 | 460 of 460 (100.0%, 95% interval 99.2 to 100.0%) | 74 of 74 (100.0%, 95% interval 95.1 to 100.0%) | 74 of 74 (100.0%, 95% interval 95.1 to 100.0%) | 74 of 74 (100.0%, 95% interval 95.1 to 100.0%) | 459 of 460 (99.8%, 95% interval 98.8 to 100.0%) |
| ChatDev | 330 | 12,500 | 12500 of 12500 (100.0%, 95% interval 100.0 to 100.0%) | 2086 of 2644 (78.9%, 95% interval 77.3 to 80.4%) | 2086 of 3443 (60.6%, 95% interval 58.9 to 62.2%) | 2906 of 3443 (84.4%, 95% interval 83.2 to 85.6%) | 490 of 12500 (3.9%, 95% interval 3.6 to 4.3%) |
| HyperAgent | 28 | 481 | 481 of 481 (100.0%, 95% interval 99.2 to 100.0%) | 82 of 82 (100.0%, 95% interval 95.5 to 100.0%) | 82 of 164 (50.0%, 95% interval 42.4 to 57.6%) | 164 of 164 (100.0%, 95% interval 97.7 to 100.0%) | 328 of 481 (68.2%, 95% interval 63.9 to 72.2%) |
| Magentic | 195 | 0 (the log names no recipient) | – | – | – | – | – |
| MetaGPT | 430 | 0 (the log names no recipient) | – | – | – | – | – |
| OpenManus | 30 | 0 (the log names no recipient) | – | – | – | – | – |

Kept is a check of the reader and the direct-message path, not an accuracy. Withheld is the measurement: the tool sees only who spoke, in what order, and the text, and links a speaker to whoever posted before in the same conversation. The logs address only some messages (an instruction, not the answer to it), so a pair of the tool's that is not logged is not shown to be wrong; the either-direction column counts a pair whose reverse is logged. Each write counts once per reader, so the tool finds the pair far more often than the single message. Pairs and messages inside a run are not independent, so these intervals are too narrow.

## As logged, without times

AG2, AppWorld, HyperAgent, Magentic: no record has a time. Loaded as logged, 0 of 850 runs are dated, the tool holds 941 logged messages as undated and puts 0 of them in the who-talked-to-whom graph, and no sign or rule can fire (0 runs). Everything else on these layouts uses the step clock.

## False alarms on benign runs

A default rule fired in 1568 of 1640 (95.6%, 95% interval 94.5 to 96.5%) of runs with the pack the tool picks by itself, and in 1567 of 1640 (95.5%, 95% interval 94.4 to 96.4%) with the general pack.

| Layout | Clock | Pack picked | Watch (first harmful sign) | Alert (2 kinds of coordination) | Volume baseline |
|---|---|---|---|---|---|
| AG2 | step clock | chat.json (597) | 10 of 597 (1.7%, 0.9 to 3.1%) | 528 of 597 (88.4%, 85.6 to 90.8%) | 0 of 597 (0.0%, 0.0 to 0.6%) |
| AppWorld | step clock | generic.json (30) | 30 of 30 (100.0%, 88.6 to 100.0%) | 30 of 30 (100.0%, 88.6 to 100.0%) | 0 of 30 (0.0%, 0.0 to 11.4%) |
| ChatDev | logged times | generic.json (330) | 131 of 330 (39.7%, 34.6 to 45.1%) | 330 of 330 (100.0%, 98.8 to 100.0%) | 0 of 330 (0.0%, 0.0 to 1.2%) |
| HyperAgent | step clock | generic.json (28) | 9 of 28 (32.1%, 17.9 to 50.7%) | 28 of 28 (100.0%, 87.9 to 100.0%) | 0 of 28 (0.0%, 0.0 to 12.1%) |
| Magentic | step clock | generic.json (195) | 66 of 195 (33.8%, 27.6 to 40.7%) | 192 of 195 (98.5%, 95.6 to 99.5%) | 0 of 195 (0.0%, 0.0 to 1.9%) |
| MetaGPT | logged times | generic.json (430) | 95 of 430 (22.1%, 18.4 to 26.3%) | 429 of 430 (99.8%, 98.7 to 100.0%) | 0 of 430 (0.0%, 0.0 to 0.9%) |
| OpenManus | logged times | generic.json (30) | 7 of 30 (23.3%, 11.8 to 40.9%) | 30 of 30 (100.0%, 88.6 to 100.0%) | 0 of 30 (0.0%, 0.0 to 11.4%) |

The Alert rule fires on almost any team that talks: it detects information flow, not malice. The hourly baselines need 6 to 12 hours of history and these runs are shorter, so their zeros say nothing. On the step clock a rate per 24 h has no meaning and none is given.

## Do the rules track task failure?

1,236 runs carry at least one failure mode, 400 carry none (4 lack some labels).

- `watch-harm`: fired on 322 of 1236 (26.1%, 95% interval 23.7 to 28.6%) of failed runs and 24 of 400 (6.0%, 95% interval 4.1 to 8.8%) of clean runs.
- `alert-coord2`: fired on 1169 of 1236 (94.6%, 95% interval 93.2 to 95.7%) of failed runs and 394 of 400 (98.5%, 95% interval 96.8 to 99.3%) of clean runs.
- `baseline-volume`: fired on 0 of 1236 (0.0%, 95% interval 0.0 to 0.3%) of failed runs and 0 of 400 (0.0%, 95% interval 0.0 to 1.0%) of clean runs.

The pooled gap on the Watch rule is mostly the mix of frameworks: the layouts differ both in how often they fail and in how often the rule fires. Inside one layout (failed against clean):

- AG2: 4 of 286 (1%) against 6 of 311 (2%)
- AppWorld: 29 of 29 (100%) against 1 of 1 (100%)
- ChatDev: 125 of 305 (41%) against 4 of 21 (19%)
- HyperAgent: 9 of 26 (35%) against 0 of 2 (0%)
- Magentic: 58 of 153 (38%) against 8 of 42 (19%)
- MetaGPT: 90 of 408 (22%) against 5 of 22 (23%)
- OpenManus: 7 of 29 (24%) against 0 of 1 (0%)

Most layouts have few clean runs, so these inside-layout gaps are not established either way. The rules were written for attacks; nothing here says they should separate failed runs from clean ones.

## What this does not show

- Accuracy on a swarm, on an attack, or on contact through shared places. These are turn-taking teams; the tool's deliveries here rest on who posted after whom in one conversation.
- Anything about timing on the step clock, which is order only.
- That the labels are right. The 14 labels come from an LLM judge.

Credit: Cemri, Pan, Yang et al., "Why Do Multi-Agent LLM Systems Fail?", NeurIPS 2025, arXiv:2503.13657; data: huggingface.co/datasets/mcemri/MAST-Data (CC BY 4.0). Records are shown as parsed by our reader and cut to short excerpts.

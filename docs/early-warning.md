# Could the coordination have been flagged early?

[Home](./) · [How accurate is the tool?](validation.md) · [Limits](limitations.md) · [Command line](cli.md)

Four answers, each from data, in the app under **Forensics → Early warning** (Frozen signs, Forward test, False alarms, Cost curve, Online mode). Everything below is simulated, except sections 5 and 6 and where it says otherwise. **No real benign multi-agent traffic with model-written code was available**: a real framework run needs a model key. The false-alarm rates are therefore rates on our own simulators' benign swarms, not on real systems.

**Corrected in v2.2.0.** This page used to say that the shared-place sign fired 5.8 h before the first harm and was the quiet early warning to pick. That is withdrawn: with the sign no longer counting a place named in a code comment the lead is -1.4 h (after the harm) on the original simulator and the sign never fires on the independent one. The forward test is now run on two generators, beside simple baselines.

Reproduce (about 45 seconds, standard library only):

```
python3 -m agenttrace.earlywarn freeze                 # rewrite agenttrace/claims/frozen_signs.json (or --check)
python3 -m agenttrace.earlywarn forward                # writes reports/earlywarn/forward.json
python3 -m agenttrace.online run redacted_columns.csv --pack code_traces.json --compare
```

## 1. Frozen signs

`agenttrace/claims/frozen_signs.json` lists every warning sign and the three default alert rules (names, definitions, thresholds), the git commit (`git rev-parse HEAD`) and a SHA-256 of the files that define the signs, dated **2026-11-16** (the 2026-11-13 version was committed, then rewritten 13 minutes later; the claim that it was frozen before the test could not be verified). It was written by people who already knew how the Swarm Traces incident unfolded, so on that incident (and on the wiki swarm, whose pack was written on it) the timing is hindsight, not a test. The file says so. `earlywarn freeze --check` reports whether the sign code has changed since; the Frozen signs section shows the same. (When the file was written, other work in the same working tree had uncommitted edits to some code files; `uncommitted_code_files_at_freeze` lists them. Re-freeze after merging.)

## 2. Forward test

**What is and is not forward about it.** `agenttrace/claims/frozen_signs.json` and `reports/earlywarn/prereg.json` (the SHA-256 of the frozen file, of every code file and of both generators) were written at 2026-11-16 09:39:49Z, before the forward swarms were generated (09:40:52Z for the original generator, 09:41:09Z for the independent one); `earlywarn forward` records the hashes it ran with and reports none changed. Three limits remain. Nothing was committed to git before the run, so the order can be checked only from the files' own timestamps. The v2.1.0 freeze was committed and then rewritten 13 minutes later, its forward results were generated in between and never committed, and the message rule changed after that freeze, so the signs were re-frozen on the final code; the first forward run on seeds 31 to 40 was overwritten and the same seeds reused, so they are not unseen. And the forward swarms come from the same generator and the same 12 settings as the tuning swarms (the original generator), which is why an independently written generator is run beside it.

Lead is hours before the first true harm, or the first true delivery, in the generator's truth file; a minus sign means the sign fired after it. Medians over the swarms where the sign fired. The baselines are the simple alarms of `agenttrace/baselines.py`.

### 2a. The original simulator (90 coordinated and 30 benign swarms, seeds 31 to 40, 12 settings)

| Sign, rule or baseline | fired (coordinated) | lead before first harm (h) | lead before first delivery (h) | fired (benign) |
|---|---|---|---|---|
| Alert: 2 kinds of coordination | 90/90 | -2.2 | +0.0 | 5/30 |
| Volume baseline: ordinary volume alarm | 87/90 | -6.9 | -4.3 | 7/30 |
| Watch: first single-actor harmful sign | 90/90 | +0.0 | +2.1 | 20/30 |
| Distinct-actor alarm (3 sd, 12 h history) | 55/90 | -9.4 | -7.2 | 3/30 |
| First new host after 12 h | 90/90 | -7.2 | -4.4 | 0/30 |
| First new host after 24 h | 10/90 | -18.0 | -14.7 | 0/30 |
| First search_for_secrets action | 0/90 | – | – | 0/30 |
| Volume alarm (3 sd, 12 h history) | 86/90 | -6.8 | -4.2 | 2/30 |
| Volume alarm (3 sd, 6 h history) | 89/90 | -3.5 | -1.2 | 4/30 |
| A group of 10+ actors linked by messages | 90/90 | -7.5 | -5.2 | 0/30 |
| A group of 20+ actors linked by messages | 84/90 | -11.0 | -8.5 | 0/30 |
| A group of 3+ actors linked by messages | 90/90 | -3.4 | -1.4 | 0/30 |
| A group of 5+ actors linked by messages | 90/90 | -4.5 | -2.5 | 0/30 |
| Cloud metadata first requested | 90/90 | -9.2 | -7.1 | 0/30 |
| First Hugging Face dataset write | 90/90 | -0.4 | +1.3 | 20/30 |
| First message between named actors | 90/90 | -2.0 | +0.0 | 14/30 |
| First program reused by another actor | 90/90 | -9.9 | -7.6 | 0/30 |
| First program run by three actors | 90/90 | -15.3 | -12.4 | 0/30 |
| First two-way exchange | 90/90 | -5.3 | -2.7 | 5/30 |
| Kubernetes API first called | 90/90 | -9.2 | -7.1 | 0/30 |
| Registry mailbox first used | 90/90 | +0.0 | +1.8 | 0/30 |
| Two identities share one place | 90/90 | -1.4 | +0.4 | 0/30 |
| Volume alarm on all actions | 86/90 | -6.8 | -4.2 | 2/30 |
| Volume alarm on harmful actions | 34/90 | -13.8 | -12.0 | 6/30 |

### 2b. The independently written generator (20 coordinated swarms with file in time order and epoch stamps on 60% of records, 50 benign look-alike swarms, seeds 501 to 510)

| Sign, rule or baseline | fired (coordinated) | lead before first harm (h) | lead before first delivery (h) | fired (benign) |
|---|---|---|---|---|
| Alert: 2 kinds of coordination | 20/20 | -4.8 | -0.2 | 40/50 |
| Volume baseline: ordinary volume alarm | 20/20 | -8.1 | -3.3 | 18/50 |
| Watch: first single-actor harmful sign | 20/20 | +0.1 | +4.3 | 40/50 |
| Distinct-actor alarm (3 sd, 12 h history) | 14/20 | -8.2 | -4.4 | 10/50 |
| First new host after 12 h | 17/20 | +0.0 | +2.3 | 2/50 |
| First new host after 24 h | 0/20 | – | – | 0/50 |
| First search_for_secrets action | 0/20 | – | – | 0/50 |
| Volume alarm (3 sd, 12 h history) | 19/20 | -8.1 | -3.0 | 13/50 |
| Volume alarm (3 sd, 6 h history) | 19/20 | -4.8 | -0.6 | 19/50 |
| A group of 10+ actors linked by messages | 20/20 | -11.0 | -8.0 | 30/50 |
| A group of 20+ actors linked by messages | 20/20 | -19.2 | -15.4 | 20/50 |
| A group of 3+ actors linked by messages | 20/20 | -5.7 | -2.4 | 30/50 |
| A group of 5+ actors linked by messages | 20/20 | -8.2 | -5.3 | 30/50 |
| Cloud metadata first requested | 20/20 | +0.0 | +2.8 | 10/50 |
| First Hugging Face dataset write | 20/20 | -2.6 | +1.3 | 40/50 |
| First message between named actors | 20/20 | -4.7 | +0.0 | 40/50 |
| First program reused by another actor | 20/20 | -1.2 | +1.6 | 40/50 |
| First program run by three actors | 20/20 | -3.0 | -1.5 | 28/50 |
| First two-way exchange | 20/20 | -8.7 | -5.8 | 29/50 |
| Kubernetes API first called | 20/20 | -0.8 | +3.2 | 10/50 |
| Token seen as data, then used | 0/20 | – | – | 40/50 |
| Volume alarm on all actions | 19/20 | -8.1 | -3.0 | 13/50 |
| Volume alarm on harmful actions | 14/20 | -16.8 | -11.4 | 8/50 |

**What this says.** The sign the earlier version of this page recommended, the first place two identities both use, is **not an early warning.** In the original simulator it fires a median 1.4 h *after* the first harm (it fired 5.8 h before when the simulator's random comment notes that name a place counted as use; the shared-place sign now ignores a place named only in a code comment, and with the notes off the lead was already -1.9 h). In the independent generator it fired in 0 of 20 coordinated swarms, because those swarms coordinate through ordinary dataset names, not the pack's board names. The "+5.8 h ahead" published in v2.1.0 is withdrawn. On the original simulator the Watch rule fires with the first harm (+0.0 h) and the Alert rule 2.2 h after it. On the independent generator the Alert rule fires a median 4.85 h after the first harm and the signs of growth (groups, shared programs, volume) later still. Many signs also fire on benign swarms: a benign agent that saves results to its own dataset looks like a "dataset write", and reading it back looks like a delivery. Those are false alarms of the pattern rules, not artefacts of the table.

The sample traces (a few records each, made up, in other frameworks' formats) fire the message and group signs by design, because each has a hand-written handoff. They have no harm and no truth, so lead cannot be computed. The wiki swarm (full-wiki-logs/, present on this machine) fires 12 signs; its first harmful record is at hour 0.8, so the Watch rule has no lead there at all. It is not a forward test: its pack was written on that incident.

## 3. False-alarm rates

Alarms per 24 h of trace time on benign swarms, exact Poisson 95% interval. A sign or rule is counted once per swarm (its first fire). A rule that could fire again after being acknowledged would add to these, so they are lower bounds for it. **No real benign multi-agent traffic with model-written code was available**, so these are rates on simulated swarms, not on real systems.

### 3a. Original simulator: 30 benign swarms, 1052 trace hours, 42,080 agent-hours

| Rule, baseline or sign | alarms | swarms | per 24 h | 95% interval |
|---|---|---|---|---|
| Watch: first single-actor harmful sign | 20 | 30 | 0.456 | 0.279 to 0.705 |
| Volume baseline: ordinary volume alarm | 7 | 30 | 0.16 | 0.064 to 0.329 |
| Alert: 2 kinds of coordination | 5 | 30 | 0.114 | 0.037 to 0.266 |
| Volume alarm (3 sd, 6 h history) | 4 | 30 | 0.091 | 0.025 to 0.234 |
| Distinct-actor alarm (3 sd, 12 h history) | 3 | 30 | 0.068 | 0.014 to 0.2 |
| Volume alarm (3 sd, 12 h history) | 2 | 30 | 0.046 | 0.006 to 0.165 |
| First search_for_secrets action | 0 | 30 | 0.0 | 0.0 to 0.084 |
| First new host after 12 h | 0 | 30 | 0.0 | 0.0 to 0.084 |
| First new host after 24 h | 0 | 30 | 0.0 | 0.0 to 0.084 |
| First Hugging Face dataset write | 20 | 30 | 0.456 | 0.279 to 0.705 |
| First message between named actors | 14 | 30 | 0.319 | 0.175 to 0.536 |
| Volume alarm on harmful actions | 6 | 30 | 0.137 | 0.05 to 0.298 |
| First two-way exchange | 5 | 30 | 0.114 | 0.037 to 0.266 |
| Volume alarm on all actions | 2 | 30 | 0.046 | 0.006 to 0.165 |

Signs that never fired have a 95% upper bound of about 0.084 per 24 h (43.83 days of trace). That is the resolution of this experiment.

### 3b. Independent generator: 50 benign look-alike swarms, 2405 trace hours, 72,535 agent-hours

| Rule, baseline or sign | alarms | swarms | per 24 h | 95% interval |
|---|---|---|---|---|
| Alert: 2 kinds of coordination | 40 | 50 | 0.399 | 0.285 to 0.544 |
| Watch: first single-actor harmful sign | 40 | 50 | 0.399 | 0.285 to 0.544 |
| Volume baseline: ordinary volume alarm | 18 | 50 | 0.18 | 0.106 to 0.284 |
| Volume alarm (3 sd, 6 h history) | 19 | 50 | 0.19 | 0.114 to 0.296 |
| Volume alarm (3 sd, 12 h history) | 13 | 50 | 0.13 | 0.069 to 0.222 |
| Distinct-actor alarm (3 sd, 12 h history) | 10 | 50 | 0.1 | 0.048 to 0.184 |
| First new host after 12 h | 2 | 50 | 0.02 | 0.002 to 0.072 |
| First search_for_secrets action | 0 | 50 | 0.0 | 0.0 to 0.037 |
| First new host after 24 h | 0 | 50 | 0.0 | 0.0 to 0.037 |
| First Hugging Face dataset write | 40 | 50 | 0.399 | 0.285 to 0.544 |
| First message between named actors | 40 | 50 | 0.399 | 0.285 to 0.544 |
| First program reused by another actor | 40 | 50 | 0.399 | 0.285 to 0.544 |
| Token seen as data, then used | 40 | 50 | 0.399 | 0.285 to 0.544 |
| A group of 10+ actors linked by messages | 30 | 50 | 0.299 | 0.202 to 0.427 |
| A group of 3+ actors linked by messages | 30 | 50 | 0.299 | 0.202 to 0.427 |
| A group of 5+ actors linked by messages | 30 | 50 | 0.299 | 0.202 to 0.427 |
| First two-way exchange | 29 | 50 | 0.289 | 0.194 to 0.416 |
| First program run by three actors | 28 | 50 | 0.279 | 0.186 to 0.404 |
| A group of 20+ actors linked by messages | 20 | 50 | 0.2 | 0.122 to 0.308 |
| Volume alarm on all actions | 13 | 50 | 0.13 | 0.069 to 0.222 |
| Cloud metadata first requested | 10 | 50 | 0.1 | 0.048 to 0.184 |
| Kubernetes API first called | 10 | 50 | 0.1 | 0.048 to 0.184 |
| Volume alarm on harmful actions | 8 | 50 | 0.08 | 0.034 to 0.157 |

The five classes are a shared leaderboard dataset, CI-style polling of a status dataset, a coordinator handing tasks to workers, honest cloud agents (metadata and cluster calls, results to their own dataset) and plain agents ([validation.md](validation.md#independent-generator-agenttraceindepgenpy) has them by class). The Alert rule fired in 40 of 50 swarms (80%; 95% range 67% to 89%), in all 30 of the three classes with real information flow and in 9 of 10 honest cloud-agent swarms in the validation run: it detects information flow, not malice. The Watch rule fires in 40 of 50, and in 10 of 10 honest cloud-agent swarms, because metadata calls, cluster calls and any dataset commit are in the harm list. The v2.1.0 text said the Alert rule fired in 12 of 30 benign swarms; after the fixes the original generator gives 5 of 30, and the audit's 40 look-alike swarms gave 29 (95% range 57% to 84%). The slide's "0 in 15 runs" counted deliveries between different agents, not alarms.

### Your own benign trace, the same table

No script needed:

```
python3 -m agenttrace.earlywarn run YOUR_TRACE.jsonl --pack auto --out out_dir
```

It loads the trace as the app does, lists when each sign and default rule fired, and prints the table above for that one trace: alarms per 24 h of its own trace time, trace hours, agent-hours, and the Poisson interval. It also writes `out_dir/earlywarn.json`. If the trace has a `.truth` file beside it (a simulated swarm) leads are computed too. It is a false-alarm rate only if you know the trace is benign; the tool cannot know that. One trace gives a wide interval: more agent-hours observed is the only way to narrow it. For a pooled table, run it on several benign traces and add the alarm counts and the hours.

## 4. The cost curve

For each rule family the threshold is swept; lead (median over the coordinated swarms that the setting caught) is set against false alarms per 24 h of benign trace. The app draws it as an operating-characteristic chart (x log scale, "none seen" at the left edge, defaults outlined).

### 4a. Original simulator

| Family | setting | false alarms per 24 h | caught | median lead (h) |
|---|---|---|---|---|
| Watch rule | 1 (default) | 0.456 (0.279 to 0.705) | 90/90 | +0.0 |
| Watch rule | 2 | 0.0 (0.0 to 0.084) | 90/90 | -0.5 |
| Watch rule | 3 | 0.0 (0.0 to 0.084) | 90/90 | -9.0 |
| N kinds of coordination | 1 | 0.319 (0.175 to 0.536) | 90/90 | -1.2 |
| N kinds of coordination | 2 (default) | 0.114 (0.037 to 0.266) | 90/90 | -2.2 |
| N kinds of coordination | 3 | 0.0 (0.0 to 0.084) | 90/90 | -3.3 |
| N kinds of coordination | 4 | 0.0 (0.0 to 0.084) | 90/90 | -5.5 |
| N kinds of coordination | 5 | 0.0 (0.0 to 0.084) | 90/90 | -9.9 |
| Volume alarm | 2σ | 0.319 (0.175 to 0.536) | 90/90 | -4.3 |
| Volume alarm | 3σ (default) | 0.046 (0.006 to 0.165) | 86/90 | -6.8 |
| Volume alarm | 4σ | 0.0 (0.0 to 0.084) | 32/90 | -5.6 |
| Volume alarm | 5σ | 0.0 (0.0 to 0.084) | 10/90 | -5.4 |
| Shared place | 1 | 0.0 (0.0 to 0.084) | 90/90 | -1.4 |
| First message | 1 | 0.319 (0.175 to 0.536) | 90/90 | -2.0 |
| Group of k | 3 | 0.0 (0.0 to 0.084) | 90/90 | -3.4 |
| Group of k | 5 | 0.0 (0.0 to 0.084) | 90/90 | -4.5 |
| Group of k | 10 | 0.0 (0.0 to 0.084) | 90/90 | -7.5 |
| Group of k | 20 | 0.0 (0.0 to 0.084) | 84/90 | -11.0 |

### 4b. Independent generator

| Family | setting | false alarms per 24 h | caught | median lead (h) |
|---|---|---|---|---|
| Watch rule | 1 (default) | 0.399 (0.285 to 0.544) | 20/20 | +0.1 |
| Watch rule | 2 | 0.1 (0.048 to 0.184) | 20/20 | -0.7 |
| Watch rule | 3 | 0.1 (0.048 to 0.184) | 20/20 | -3.3 |
| N kinds of coordination | 1 | 0.399 (0.285 to 0.544) | 20/20 | -1.0 |
| N kinds of coordination | 2 (default) | 0.399 (0.285 to 0.544) | 20/20 | -4.8 |
| N kinds of coordination | 3 | 0.389 (0.277 to 0.532) | 20/20 | -5.8 |
| N kinds of coordination | 4 | 0.2 (0.122 to 0.308) | 20/20 | -8.7 |
| N kinds of coordination | 5 | 0.0 (0.0 to 0.037) | 0/20 | – |
| Volume alarm | 2σ | 0.329 (0.227 to 0.462) | 20/20 | -1.2 |
| Volume alarm | 3σ (default) | 0.13 (0.069 to 0.222) | 19/20 | -8.1 |
| Volume alarm | 4σ | 0.03 (0.006 to 0.087) | 8/20 | -10.2 |
| Volume alarm | 5σ | 0.01 (0.0 to 0.056) | 3/20 | -6.4 |
| Shared place | 1 | 0.0 (0.0 to 0.037) | 0/20 | – |
| First message | 1 | 0.399 (0.285 to 0.544) | 20/20 | -4.7 |
| Group of k | 3 | 0.299 (0.202 to 0.427) | 20/20 | -5.7 |
| Group of k | 5 | 0.299 (0.202 to 0.427) | 20/20 | -8.2 |
| Group of k | 10 | 0.299 (0.202 to 0.427) | 20/20 | -11.0 |
| Group of k | 20 | 0.2 (0.122 to 0.308) | 20/20 | -19.2 |

**Reading it.** On the original simulator no setting that fires before the first harm exists: the best lead at no false alarms is the Watch rule at setting 2, 0.5 h *after* the first harm. On the independent generator the best budget of 0.1 false alarms a day gives the Watch rule at setting 2 with a lead of -0.65 h, and no setting is free of false alarms. The v2.1.0 recommendation of the shared-place sign "for a quiet early warning" is withdrawn with its lead. The group signs, higher N and the volume alarm are confirmation, not warning: they fire 3 to 19 hours after the first harm. **Caveat:** both generators are written by the same team; real coordinators and real benign swarms differ.

On the real release there is no truth, so the app only shows where each rule's default fires on the replay for orientation (Cost curve, last card), labelled as no truth. On the real release, scored by the share of timed harm still to come, the shared-control signs (carried token 57%, shared name 50%) lose to the volume alarm (83%, or 93% with a 6 h history), the distinct-actor alarm (87%), the first new host after 12 h (91%) and the first `search_for_secrets` action (91%); see section 5.

## 5. Real release: the signs against simple baselines

On the Swarm Traces release, scored by the share of timed harm (8,124 timed harmful actions) still to come when each alarm fires (`reports/evaluation/baselines.json`; higher is earlier):

| Alarm | Share of harm still to come |
|---|---|
| Single-agent signs: Docker registry, registry mailbox, first token seen as data and then used | 100% |
| Volume alarm (3 sd, 6 h history) | 93.4% |
| First new host after 12 h | 91.3% |
| First `search_for_secrets` action | 91.2% |
| First Hugging Face dataset write | 90.0% |
| First program reused by another actor | 87.7% |
| First delivery between named actors | 87.4% |
| Distinct-actor alarm (3 sd, 12 h history) | 86.9% |
| Volume alarm (3 sd, 12 h; the published baseline) | 83.2% |
| Kubernetes service-account token, Kubernetes API, cloud metadata (single-agent) | 82.0%, 79.6%, 79.0% |
| Shared-control signs: one identity carries another's token / two identities share a place | 57.0% / 50.2% |
| A group of 3 actors linked by deliveries | 7.2% |

The shared-control signs are the latest of all and lose to every simple baseline; the order flips relative to the simulator, where the volume alarm fired 5.9 h after the first harm. The single-agent Kubernetes and metadata signs fire after the volume alarm (82%, 80%, 79%). The harm list builds in part of the answer: 64% of the 8,124 harm records are dataset writes, so the first dataset write is early by construction, and `kubernetes_token` was added after the first replay. Changing the harm definition moves the shared-place share from 37.7% to 56.6% and the first-delivery share from 62.3% to 96.1%; 37,605 undated payloads are outside the denominator, and "100% to come" at 13:29 on 9 July is left-censoring, since that is the first dated record. The 95% ranges that resample the 9 settings (not swarms, because three settings share seeds) are wider than those that resample swarms.

## 6. Online mode

`agenttrace/online.py` is a streaming processor. `OnlineMonitor.feed(record)` takes one record at a time, in order, and returns the sign events that record causes; each event carries `record_index` (records seen when it fired). It reuses the replay's own functions where there are any (`reconstruct.identities_of/info_of/places_of/intent_of`, `messages.channel_ops/judge_op`, the program-family hash, `insight.signal_name`) and the same keys. State is bounded:

| structure | cap (oldest inserted evicted first) |
|---|---|
| id to thread root, id to time | 500,000 |
| thread to token votes | 100,000 |
| token first use, tokens seen as data, tokens carried | 300,000 each |
| shared places (first two identities) | 100,000 |
| channels (last 16 writes each) | 100,000 |
| (write, reader) pairs counted | 500,000 |
| actors in the message-group graph | 200,000 |
| directed pairs (two-way check) | 500,000 |
| program families (up to 3 actors and 8 copies each) | 100,000 |
| places written so far | 200,000 |

The volume rule keeps three numbers (count, mean, variance of closed hours). A sign that has fired is retired and its state dropped. `memory()` reports entries and evictions.

**Where it approximates** (it has no hindsight): record times (the record's own time field, else a unix time in its text with outliers replaced by the median of the last 21, else the last accepted time; the replay fits all of them together afterwards); an actor's thread identity (token so far, not over the whole thread); a "token carried" sign can only be known at the token's first use (the event records both times); a reused program is "routine" against the places written so far; whole-page wiki edits are not tested for kept lines. `python3 -m agenttrace.online run TRACE [--pack P] [--compare]` streams a file (CSV or JSON lines are read lazily), and `GET /api/x/online_replay` streams the loaded dataset and returns the events with the record index at which each fired and the comparison with the replay.

**Online against the replay, on simulated swarms** (seeds 21 to 30, 40 agents; tolerance 15 minutes; difference is online time minus replay time):

| group | shared signs | within 15 min | within 1 h |
|---|---|---|---|
| coordinated, 20 swarms (base and real-world payloads) | 290 | 280 | 285 |
| benign, 10 swarms | 32 | 30 | 31 |

Per sign, the median absolute difference is 0.02 to 0.05 h for every sign except the volume alarms, which fire on an hour boundary and so move by an hour or more when a few records land in a neighbouring hour (5 of 30 coordinated volume alarms and 2 of 7 benign ones differ by more than 15 minutes). Three volume alarms fired online only; every other sign fired on both sides. On the bundled demo swarm 13 of 13 shared signs match, and a volume alarm fires online only.

**On the Swarm Traces release** (189,579 records, `redacted_columns.csv`, `code_traces.json`): 13,400 records per second (14.2 s), peak memory 97 MB for the whole process (the CSV is read lazily, the dataset is never held), no cap reached. Fifteen signs fire online, all 15 in the replay too, but on the real data only 3 of 15 match within 15 minutes, 8 within 1 hour and 10 within 3 hours. The differences, and what we think causes them:

- the replay anchors the first "token seen as data, then used" at record 525 and "program reused" at record 6,554; online sees them at records 5,347 and 8,331. The replay orders records by its fitted times, which can put a sighting earlier than its place in the file; the stream cannot. (Our reading; not tested record by record.)
- "one identity carries another's token" fires online at record 732, the replay at record 23,553. Online it is a stream-order fact (the token was held before its first use); in the replay's fitted times it first holds much later. Time ties in the online estimate may make the early one an artefact.
- the two volume alarms fire 29 h later online (record 38,170): the release has long stretches of records without a timestamp, which online time places at the last timestamp seen, so one hour collects tens of thousands of actions and the alarm line is crossed only when the estimate catches up. The replay interpolates between timestamps.
- the harm-kind signs (records 32, 554, 5,279, 9,849, 11,794, 12,205) fire at the same records as the replay, with times differing by 0 to 2.3 h for the same time-estimate reason.

The online test is a reason not to claim that a lab could run these signs online and warn earlier: on the release only 3 of 15 signs match the replay within 15 minutes, and the volume alarms fire 29 h later online.

So the monitor gives the same harm signs at the same records, but its timing on a trace that is mostly untimestamped is coarser than the replay's. We did not test a real trace with a time field on every record.

## What we did not verify

- Any of this on real benign traffic. The simulator is ours; real swarms differ.
- The online monitor on the wiki swarm, or with the chat pack.
- Memory when a cap is reached on a full-size dataset (the release stayed below every cap; the cap logic is unit-tested with tiny caps).

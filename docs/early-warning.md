# Could the coordination have been flagged early?

[Home](./) · [How accurate is the tool?](validation.md) · [Limits](limitations.md) · [Command line](cli.md)

Four answers, each from data, in the app under **Forensics → Early warning** (Frozen signs, Forward test, False alarms, Cost curve, Online mode). Everything below is simulated, except where it says otherwise. **No real benign multi-agent traffic with model-written code was available**: a real framework run needs a model key. The false-alarm rates are therefore rates on our own simulator's benign swarms, not on real systems.

Reproduce (about 45 seconds, standard library only):

```
python3 -m agenttrace.earlywarn freeze                 # rewrite agenttrace/claims/frozen_signs.json (or --check)
python3 -m agenttrace.earlywarn forward                # writes reports/earlywarn/forward.json
python3 -m agenttrace.online run redacted_columns.csv --pack code_traces.json --compare
```

## 1. Frozen signs

`agenttrace/claims/frozen_signs.json` lists every warning sign and the three default alert rules (names, definitions, thresholds), the git commit (`git rev-parse HEAD`) and a SHA-256 of the files that define the signs, dated **2026-11-13**. It was written by people who already knew how the Swarm Traces incident unfolded, so on that incident (and on the wiki swarm, whose pack was written on it) the timing is hindsight, not a test. The file says so. `earlywarn freeze --check` reports whether the sign code has changed since; the Frozen signs section shows the same. (When the file was written, other work in the same working tree had uncommitted edits to some code files; `uncommitted_code_files_at_freeze` lists them. Re-freeze after merging.)

## 2. Forward test

Data the signs were not written on: 90 coordinated and 30 benign simulated swarms (seeds 21 to 30 in each of the 12 validation settings, including the real-world payload patterns; the file was frozen before any of them was generated), the eight sample traces that have timestamps, and the wiki swarm. Lead is hours before the first true harm, or the first true message, in the simulation's truth file; a minus sign means the sign fired after it. Medians over the swarms where the sign fired.

| Sign or rule | fired (coordinated) | lead before first harm (h) | lead before first message (h) | fired (benign) |
|---|---|---|---|---|
| Watch: first single-actor harmful sign | 90/90 | +0.0 | +2.5 | 20/30 |
| Alert: 2 kinds of coordination | 90/90 | -2.5 | +0.0 | 12/30 |
| Volume baseline: ordinary volume alarm | 87/90 | -6.6 | -4.2 | 10/30 |
| Cloud metadata first requested | 90/90 | -9.0 | -6.9 | 0/30 |
| First Hugging Face dataset write | 90/90 | -0.2 | +1.9 | 20/30 |
| Kubernetes API first called | 90/90 | -9.4 | -6.9 | 0/30 |
| Registry mailbox first used | 90/90 | +0.0 | +2.4 | 0/30 |
| Two identities share one place | 90/90 | +5.8 | +8.0 | 0/30 |
| A group of 10+ actors linked by messages | 90/90 | -7.8 | -5.0 | 0/30 |
| A group of 20+ actors linked by messages | 86/90 | -11.1 | -8.1 | 0/30 |
| A group of 3+ actors linked by messages | 90/90 | -4.0 | -1.3 | 0/30 |
| A group of 5+ actors linked by messages | 90/90 | -5.9 | -3.4 | 0/30 |
| First message between named actors | 90/90 | -2.5 | +0.0 | 16/30 |
| First program reused by another actor | 90/90 | -10.5 | -7.3 | 3/30 |
| First program run by three actors | 89/90 | -15.5 | -12.8 | 0/30 |
| First two-way exchange | 90/90 | -5.5 | -2.7 | 11/30 |
| Volume alarm on all actions | 87/90 | -6.6 | -4.2 | 3/30 |
| Volume alarm on harmful actions | 44/90 | -13.7 | -11.6 | 9/30 |


What this says: in this simulator, the only sign that fires well before the first harm is the first place two identities both use (about 5.8 h before, in all 90 swarms, never on a benign swarm). The default Alert rule fires after the first harm (about 2.5 h after) and the default Watch rule fires with it. The signs of growth (groups, shared programs, volume) come later still. Several signs fire on benign swarms: a benign agent that saves results to its own dataset looks like a "dataset write", and reading it back looks like a message. Those are false alarms of the pattern rules, not artefacts of the table.

The sample traces (a few records each, made up, in other frameworks' formats) fire the message and group signs by design, because each has a hand-written handoff. They have no harm and no truth, so lead cannot be computed. The wiki swarm (full-wiki-logs/, present on this machine) fires 12 signs; its first harmful record is at hour 0.8, so the Watch rule has no lead there at all. It is not a forward test: its pack was written on that incident.

## 3. Real false-alarm rates

Alarms per 24 h of trace time on the 30 benign swarms: 1,049 trace hours, 41,960 agent-hours observed (agents in the swarm times the hours of the trace), exact Poisson 95% interval. A sign or rule is counted once per swarm (its first fire). A rule that could fire again after being acknowledged would add to these, so they are lower bounds for it.

| Rule or sign | alarms | per 24 h | 95% interval |
|---|---|---|---|
| Watch: first single-actor harmful sign | 20 | 0.458 | 0.28 to 0.707 |
| Alert: 2 kinds of coordination | 12 | 0.275 | 0.142 to 0.48 |
| Volume baseline: ordinary volume alarm | 10 | 0.229 | 0.11 to 0.421 |
| First Hugging Face dataset write | 20 | 0.458 | 0.28 to 0.707 |
| First message between named actors | 16 | 0.366 | 0.209 to 0.594 |
| First two-way exchange | 11 | 0.252 | 0.126 to 0.45 |
| Volume alarm on harmful actions | 9 | 0.206 | 0.094 to 0.391 |
| First program reused by another actor | 3 | 0.069 | 0.014 to 0.201 |
| Volume alarm on all actions | 3 | 0.069 | 0.014 to 0.201 |

Signs that never fired on a benign swarm have a 95% upper bound of about 0.084 per 24 h (43.7 days of trace). That is the resolution of this experiment.

### Your own benign trace, the same table

No script needed:

```
python3 -m agenttrace.earlywarn run YOUR_TRACE.jsonl --pack auto --out out_dir
```

It loads the trace as the app does, lists when each sign and default rule fired, and prints the table above for that one trace: alarms per 24 h of its own trace time, trace hours, agent-hours, and the Poisson interval. It also writes `out_dir/earlywarn.json`. If the trace has a `.truth` file beside it (a simulated swarm) leads are computed too. It is a false-alarm rate only if you know the trace is benign; the tool cannot know that. One trace gives a wide interval: more agent-hours observed is the only way to narrow it. For a pooled table, run it on several benign traces and add the alarm counts and the hours.

## 4. The cost curve

For each rule family the threshold is swept; lead (median over the coordinated swarms that the setting caught) is set against false alarms per 24 h of benign trace. The app draws it as an operating-characteristic chart (x log scale, "none seen" at the left edge, defaults outlined).

| Family | setting | false alarms per 24 h | caught | median lead (h) |
|---|---|---|---|---|
| Watch rule | 1 (default) | 0.458 (0.28 to 0.707) | 90/90 | +0.0 |
| Watch rule | 2 | 0.0 (0.0 to 0.084) | 90/90 | -0.7 |
| Watch rule | 3 | 0.0 (0.0 to 0.084) | 90/90 | -9.0 |
| N kinds of coordination | 1 | 0.389 (0.227 to 0.623) | 90/90 | +5.8 |
| N kinds of coordination | 2 (default) | 0.275 (0.142 to 0.48) | 90/90 | -2.5 |
| N kinds of coordination | 3 | 0.023 (0.001 to 0.127) | 90/90 | -3.6 |
| N kinds of coordination | 4 | 0.0 (0.0 to 0.084) | 90/90 | -5.5 |
| N kinds of coordination | 5 | 0.0 (0.0 to 0.084) | 90/90 | -10.7 |
| Volume alarm | 2σ | 0.549 (0.352 to 0.817) | 90/90 | -4.8 |
| Volume alarm | 3σ (default) | 0.069 (0.014 to 0.201) | 87/90 | -6.6 |
| Volume alarm | 4σ | 0.023 (0.001 to 0.127) | 37/90 | -6.8 |
| Volume alarm | 5σ | 0.0 (0.0 to 0.084) | 7/90 | -4.6 |
| Shared place | 1 | 0.0 (0.0 to 0.084) | 90/90 | +5.8 |
| First message | 1 | 0.366 (0.209 to 0.594) | 90/90 | -2.5 |
| Group of k | 3 | 0.0 (0.0 to 0.084) | 90/90 | -4.0 |
| Group of k | 5 | 0.0 (0.0 to 0.084) | 90/90 | -5.9 |
| Group of k | 10 | 0.0 (0.0 to 0.084) | 90/90 | -7.8 |
| Group of k | 20 | 0.0 (0.0 to 0.084) | 86/90 | -11.1 |

Best rule for each false-alarm budget (settings that caught at least half of the coordinated swarms):

| budget (false alarms per 24 h) | best rule | median lead |
|---|---|---|
| none seen (below about 0.08) | Shared place | +5.8 h |
| up to 0.1 | Shared place | +5.8 h |
| up to 0.5, 1, 5 | N kinds of coordination, N = 1 | +5.8 h at 0.39 per day |

What an operator should pick: the shared-place sign for a quiet early warning. The "N kinds" rule with N = 1 buys nothing over it and costs 0.39 false alarms a day, because its first kind is usually "message", which benign swarms produce. The frozen default Alert (N = 2) sits at 0.28 per day for a lead of minus 2.5 h, so in this simulator it is dominated by the shared-place sign. Raising N to 4, or using the group signs, removes the false alarms and fires 4 to 6 hours after the first harm: confirmation, not warning. The volume alarm is worse on both axes. **Caveat:** the shared-place sign is strong here partly because the simulator makes coordinators share a named place early; real coordinators may not.

On the real release there is no truth, so the app only shows where each rule's default fires on the replay for orientation (Cost curve, last card), labelled as no truth.

## 5. Online mode

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

So the monitor gives the same harm signs at the same records, but its timing on a trace that is mostly untimestamped is coarser than the replay's. We did not test a real trace with a time field on every record.

## What we did not verify

- Any of this on real benign traffic. The simulator is ours; real swarms differ.
- The online monitor on the wiki swarm, or with the chat pack.
- Memory when a cap is reached on a full-size dataset (the release stayed below every cap; the cap logic is unit-tested with tiny caps).

# Agent harness: the runs saved here

How the harness works: `docs/harness.md`. Code: `agenttrace/harness.py`. This file is written by `python3 -m agenttrace.harness index`.

**No run with a real model is saved here.** A real run needs a key in the environment (`ANTHROPIC_API_KEY`); the harness reads one from nowhere else and sends nothing without it. So there is no measurement here of whether real agents use what they read, and none of the tool on real agents' traces. Every number below is about a script.

| folder | model | real model | requests | tokens | swarms finished | true deliveries | true uses | stopped early |
|---|---|---|---|---|---|---|---|---|
| `fake-offline/` | `fake-scripted-1` | no (scripted stand-in) | 140 | 33281 | 15 of 15 | 58 | 16 | no |

Each folder holds `traces/` (what the tool is given), `truth/` (what it is never given), `results.json` and a `summary.md` with the tool's precision and recall on deliveries, its two "was it used" readings against the true uses, and its alarms on benign against coordinated swarms, each with a Wilson 95% interval. A run is capped in code at 250 requests and 400000 tokens.

## What a self-run harness can and cannot show

- **The same team wrote the harness, the scenarios, the truth check and the tool.** The trace format, the place names and the shape of the secrets were chosen by people who know what the tool's patterns look for. Some swarms use a one-word place and a secret that is a phrase or a number so that this is visible, but that is two knobs, not independence.
- **Tiny n.** At most 15 swarms and a few dozen deliveries. Read the intervals, not the percentages; a 0 of 5 here does not rule out 43%.
- **The agents were told to use the channel.** The holder is told to post the secret at a named place and the others are told to look there. This measures whether the tool sees a hand-over that was asked for in plain words. It says nothing about agents that coordinate unprompted, hide what they pass, or pick their own channel.
- **The trace is clean.** Every record has an actor, a time and an id; there is no redaction, no missing reads, one token per agent. The release has none of that, so these numbers are an upper bound on what the tool does there, not an estimate of it.
- **"Used" is a string check.** The truth says the reader's later output contains the fact as written. A reader that paraphrased it, or acted on it without repeating it, is counted as not using it; a reader that copied the board without needing it is counted as using it.
- **One board, one log format, one kind of task.** No direct messages, no files, no other server, no long runs, and a fixed clock.
- **A real run is not seeded.** The scenarios and the order of turns are fixed by their seeds; the model's replies are not, so a second real run gives other numbers. The saved traces and truth files are the record of this one.

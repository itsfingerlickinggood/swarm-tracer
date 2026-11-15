# Integrity checks: what each one proves, and what it does not

[Home](./) · [How accurate is it?](validation.md) · [The counting rule](counting-rule.md) · [Known issues](known-issues.md)

Swarm Tracer publishes numbers in a report, slides, a README and these pages. A number is only as good as the
chain behind it: the data, the rule, the code that applies the rule, and the sentence that repeats the result.
Each check below tests one link of that chain. None of them shows that a number is *true*; the last section says
what still needs a person.

| check | command | what it covers |
|---|---|---|
| Provenance manifest | `python3 -m agenttrace.tools.provenance build` | which data, code and commit each published number came from |
| Verify | `python3 -m agenttrace verify` | the numbers still come out the same, and the texts still print them |
| Reproducible build | `python3 -m agenttrace.tools.repro` | a clean install computes what the working tree computes |
| Second-labeller kit | `python3 -m agenttrace.tools.labelkit export` / `score` | whether a second reader agrees with the hand audit |
| Property tests | `python3 -m unittest agenttrace.tests.test_properties` | the counting rule keeps its stated properties on random swarms |
| Second implementation | `python3 -m agenttrace.tools.crosscheck` | a separately written counter reaches the same deliveries |
| Mutation testing | `python3 -m agenttrace.tools.mutate` | the tests notice when the rule's code is broken on purpose |

## The provenance manifest

`agenttrace/claims/provenance.json` lists every registered number: an id, a plain statement, its value, the
dataset it is computed from (name, SHA-256 and size of each input file, record count), the function that
computes it, the rule version (a hash of `messages.py`, `units.py` and the dataset's pack), the git commit at
generation, and every place that prints it (the file and the exact pattern that must match there). The list of
numbers and places lives in `agenttrace/tools/provenance.py` (`registry()`); `build` computes the values and
writes the file.

Each number is computed in a fresh process with an empty decisions folder and a fixed hash seed, so saved
accept/reject decisions on one machine cannot leak into a published value.
`python3 -m agenttrace.tools.provenance stability` computes everything under several hash seeds and lists any
value that moves.

**It proves** that each registered number was produced by this code from files with these hashes, and records
where it is printed. **It does not prove** that the number is right: a wrong rule gives a wrong number with
perfect provenance. It covers only the numbers someone registered.

`build` also writes `reports/integrity/provenance_report.md` (every disagreement, every place it could not
check) and `provenance_unregistered.tsv`: numbers in the published texts that sit next to a key word (messages,
agents, tokens, records, …) or are percentages, and that no registered place covers. Those are not errors. They
are numbers nobody re-derives, listed so the gap is visible.

## Verify

`python3 -m agenttrace verify` (the same as `python3 -m agenttrace.tools.provenance verify`) re-derives every
number and checks four things:

1. the value still equals the manifest;
2. every listed place still prints that value;
3. the dataset files still hash to what the manifest recorded;
4. the claims files (`audited_links.json`, `frozen_signs.json`, `insider_findings.json` and the others in
   `agenttrace/claims/`) still hash to what it recorded.

It also compares the saved output files the report is built from (`reports/evaluation/evaluation.json`,
`identity_replay.json`, `reports/evaluation-wiki/evaluation.json`, `count_variance.json`) with a fresh
computation, and the tables in [validation.md](validation.md) with the saved run they repeat.

It exits non-zero and prints a table when anything is off. Two kinds of finding are kept apart:

- **Drift**: something changed since the manifest was built (a value, a printed text, a file).
- **Disagreement**: a place prints a number that differs from the computed one. `build` records these and does
  not hide them; `verify` fails on them too. `--allow-known` exits zero when the only findings are disagreements
  the build already recorded, for use while a correction is pending.

The datasets are not redistributed. In a clone without them, verify still checks every printed place against
the manifest, the claims-file hashes and the rule-file hashes, and says plainly which numbers it did not
re-derive. `--texts-only` does the same on purpose (under a second). `python3 -m agenttrace.tools.check` runs
verify as its last stage (`--quick`: texts only).

**It proves** that the texts, the manifest and the code agree today. **It does not prove** anything about
numbers that are not registered, about figures and screenshots, or about the PDFs: it reads the HTML and
Markdown sources, and a PDF built earlier can still be stale. A place is found by an anchor (the words around
the number), so a reworded sentence is reported as "anchor not found" until the registry is updated.

Time, measured on the development laptop with both datasets: build about 20 seconds when the tool's own
analysis cache is warm and 50 to 75 seconds when it is not (any change to the package's code empties it); verify
the same when the data or the code changed, and under a second when neither did (the computed values are cached
against the hashes of the data and of the package's code; `--no-cache` forces a fresh computation). Without the
datasets verify takes under a second.

## Reproducible build

`python3 -m agenttrace.tools.repro` exports a clean copy of git HEAD into a temporary folder, makes a fresh
virtual environment with the system `python3`, runs `pip install .` there, runs the unit tests, the smoke test
and the consistency oracle from the *installed* package on the bundled demo swarm, and compares hashes of the
deterministic JSON the installed package computes for the demo swarm (summary, message flow, deliveries, signs,
counts by agent, estimated times) with the working tree's, and with a second run under another hash seed.
`--worktree` copies the working tree instead (tracked and untracked files that git does not ignore), because
uncommitted work is not in HEAD.

The runtime needs only the standard library, but building the wheel needs `setuptools>=64`, which pip fetches.
With no network the step copies the package into the environment instead and says so; the build itself is then
not exercised.

**It proves** that the package installs from a clean checkout, that nothing it needs is missing from the
package data, and that the demo swarm's results do not depend on the machine's leftover state or on hash order.
**It does not prove** the same for the real datasets (they are not in the repository; `provenance stability`
covers hash order there), for other Python versions or operating systems than the one it ran on, or for the
browser side of the app.

## The second-labeller kit

The links in `agenttrace/claims/audited_links.json` were labelled by one reader, with the tool's help.
`python3 -m agenttrace.tools.labelkit export` writes a blind sheet into `reports/integrity/labelkit/`: one
self-contained page (`labelling.html`, no server) and a CSV. Each link shows its two records around the place
they are said to share, with the whole record one click away, in a shuffled order with a fixed seed. The sheet
holds no label, reason or note of the first reader, and not which version of the tool reported the link. The
page keeps answers in the browser and downloads them as JSON.

`python3 -m agenttrace.tools.labelkit score answers.json` reports raw agreement, Cohen's kappa with a bootstrap
95% range (three-way over true / false / undecidable, and two-way over the links both readers could decide),
the confusion table and every disagreement with both readers' reasons. Unanswered links are left out, never
filled in.

The folder holds dataset text, is ignored by git and must not be committed.

**It will show** how far two readers agree. **It does not show** which reader is right, and it says nothing
about links no version of the tool ever reported.

**Status: no second labeller has done this yet.** Agreement: none to report; until a second person labels the sheet the audit is one reader's.

## Property tests, a second implementation, mutation testing

These three belong to the counting rule; [counting-rule.md](counting-rule.md) states it.

- **Property tests** (`agenttrace/tests/test_properties.py`): seeded random swarms on which the rule must keep
  its stated properties. They prove the properties hold on the cases generated, not on every input, and not that
  the properties are the right ones. Result: 25 tests over 7 properties pass. One known behaviour: when two records carry the same time the
  result can depend on input order (29 of 9,867 deliveries on the collusion.wiki logs; the count does not change).
- **Second implementation** (`agenttrace/refcount.py`, compared by `python3 -m agenttrace.tools.crosscheck`): a
  separately written counter for the same written rule. Agreement shows the code does what the rule says;
  it cannot show the rule is right, and both were written from the same document by the same team.
  Result: **mixed.** Identical on the collusion.wiki logs (9,867 deliveries), the demo swarm (163), the
  benign swarm and all 8 format samples. On the Swarm Traces release the two disagree heavily: the rule reports
  23 deliveries, the second implementation 192, with 19 in both. We read a share of the 177 disagreements and
  judged the rule right on most of what we read; the second counter mostly trips on quotes broken by redaction
  and on a read followed by a POST elsewhere. But 162 of its 173 extra deliveries were never hand-audited, and on
  3 of the rule's 4 extra ones the second counter follows the written rule more literally. The crosscheck tool
  exits non-zero on the release for this reason. Judgements: `reports/integrity/crosscheck_judgement.json`.
- **Mutation testing** (`python3 -m agenttrace.tools.mutate`): the rule's code is broken on purpose, one small
  change at a time, to see whether the tests notice. A surviving mutant is a line no test defends. A killed
  mutant shows the tests are sensitive there, not that the line is correct.
  Result: 1,124 of 1,173 mutants of `messages.py` are killed (96%). With the tests as they stood at v2.0.0 it
  was 342 (29%). Of the 49 survivors, 48 were judged equivalent by reading the code (a judgement, not a proof)
  and 1 is left unjudged. Many of the new tests pin window sizes exactly as implemented, so they guard against
  accidental change, not against the sizes being wrong. Details: `reports/integrity/mutation.json`.

## What still needs a person

- **A second labeller.** The audit's labels are one reader's. The kit makes a second reading cheap; it does not
  do it.
- **Whether the rule is the right rule.** Every check above takes "a read of a place after a write by another
  token" as given. Whether that is a message is a judgement.
- **Unregistered numbers.** Someone has to decide, for each number in `provenance_unregistered.tsv`, whether to
  register it, cite its source, or drop it. Numbers quoted from other people's reports (about 1,200 agents,
  about 700) cannot be re-derived here at all.
- **Wording.** Verify checks the number, not the sentence around it. "All 24 messages passed through dataset
  repositories" can print the right total and still be false about the word "all".
- **The PDFs, the video and the screenshots.** They are built from the sources by hand and can lag behind them.
- **Recall.** Nothing here measures how many real messages the tool misses outside the audited pool.

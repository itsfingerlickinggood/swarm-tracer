# Integrity checks: what each one proves, and what it does not

[Home](./) · [How accurate is it?](validation.md) · [The counting rule](counting-rule.md) · [Known issues](known-issues.md)

Swarm Tracer publishes numbers in a report, slides, a README and these pages. Not every number is covered by these checks: 237 are registered (661 places print them), and 778 further figures in the scanned texts are outside the manifest (`reports/integrity/provenance_unregistered.tsv`). Of the 237, 57 were added in v2.3.0 and are read from saved result files (the four outside datasets, the pre-registered forward test, the crosscheck): for those, verify checks that the texts print what the saved files hold, and does not re-run the measurements. A number is only as good as the
chain behind it: the data, the rule, the code that applies the rule, and the sentence that repeats the result.
Each check below tests one link of that chain. None of them shows that a number is *true*; the last section says
what still needs a person.

| check | command | what it covers |
|---|---|---|
| Provenance manifest | `python3 -m agenttrace.tools.provenance build` | which data, code and commit each published number came from |
| Verify | `python3 -m agenttrace verify` | the numbers still come out the same, and the texts still print them |
| Reproducible build | `python3 -m agenttrace.tools.repro` | a clean install computes what the working tree computes |
| Second-labeller kit | `python3 -m agenttrace.tools.labelkit export` / `score` | whether a second reader agrees with the one reader's audit labels |
| Property tests | `python3 -m unittest agenttrace.tests.test_properties` | the counting rule keeps its stated properties on random swarms |
| Second implementation | `python3 -m agenttrace.tools.crosscheck` | a separately written counter reaches the same deliveries |
| Mutation testing | `python3 -m agenttrace.tools.mutate` | the tests notice when the rule's code is broken on purpose |
| Keyboard access | `python3 -m agenttrace.tools.interact --keyboard` | the app can be used with Tab, Enter, Space, Escape and the arrow keys in a real browser |
| Continuous integration | `.github/workflows/check.yml` | on every push and pull request: the checks that need no dataset and no browser, on Python 3.9 and 3.12 |

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
*registered* number and checks four things:

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
the number), so a reworded sentence is reported as "anchor not found" until the registry is updated. When the texts were rewritten for v2.2.0, 125 places lost their anchors; 109 were re-pointed to the new wording and 16 dropped because the corrected text no longer prints the value there, each logged with its reason in `reports/integrity/anchor_changes.md`. For v2.3.0 the texts were rewritten again: 20 anchors were re-pointed, 4 places dropped, 18 places added for values already registered and 57 values newly registered in 287 places, logged in the same file under its v2.3.0 heading. Verify passes (0 drift, 0 disagreements); 778 figures are unregistered.

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

## What CI runs, and what it cannot

On every push and pull request GitHub Actions runs `.github/workflows/check.yml` on Ubuntu, once with Python 3.9
and once with 3.12. The job has a read-only token (`permissions: contents: read`), uses no secret, and its two
actions are pinned to a commit. The steps:

1. the unit tests (`python3 -W ignore -m unittest discover -s agenttrace/tests -t .`);
2. the site check of `docs/` (`python3 -m agenttrace.tools.sitecheck`);
3. `python3 -m agenttrace.tools.check --quick --skip-unit`: the smoke test without a browser (every API route on
   the bundled demo swarm and the format samples), the consistency oracle on the demo swarm, and the published
   numbers against the manifest, texts only;
4. `python3 -m agenttrace.tools.provenance verify --texts-only`, the same comparison with its whole table;
5. the wheel: built with `pip wheel` in a fresh virtual environment, installed in another, and used from a folder
   outside the checkout (import, `swarm-tracer --help`, the API smoke test on the demo swarm).

**It proves** that a clean checkout runs on two Python versions with nothing installed, that the package builds
and works when installed, and that the texts still print what the manifest recorded.

**It does not check**, because the Swarm Traces release and the collusion.wiki logs are not in the repository
and the runner starts no browser:

- any number computed from the two datasets. In step 4 no value is re-derived: each printed place is compared
  with the value the manifest stored when it was built on a machine that had the data. The tests that load the
  release are skipped (they say so), and so are the places in `reports/submission/SUBMISSION.md`, a file that is
  not committed;
- the crosscheck of the two implementations on the release and the wiki logs, `provenance stability`, and every
  route on the wiki logs under three hash seeds;
- anything in a browser: the browser half of the smoke test, the interaction test, the keyboard pass, the layout
  check;
- mutation testing and line coverage (too slow), and the PDFs, the video and the screenshots.

A green run therefore means "the code runs and the texts match the manifest", not "the numbers are right". Before
a release the full set still has to be run where the data is: `python3 -m agenttrace.tools.check --full`,
`python3 -m agenttrace verify`, and `python3 -m agenttrace.tools.crosscheck`.

The workflow has not run on GitHub yet. It was rehearsed on 22 November 2026 by running the same commands in a
clean copy of the working tree without the datasets (macOS, Python 3.9.6): 959 tests ran and 25 were skipped,
each with its reason (the release, optional outside datasets, Chrome, the `hypothesis` package); the smoke
test passed 1,053 of 1,053 cells, the oracle 25 of 25 checks, and the wheel built, installed and passed its
smoke test. Two things did not pass on that day's working tree, and CI will show them red until they are dealt
with: the site check and the unit test that runs it (new investigation stories without their data bundles), and
the manifest comparison (two claims files and `messages.py` have changed since the manifest was built; it has to
be rebuilt where the data is). Python 3.12 was not on the machine, so the 3.12 half of the matrix is untried.
Under Python 3.14 an earlier copy had one more failing test, `test_deep_json`: that version reads a JSON file
nested 100,000 deep without an error, so the loader's "nested too deeply" message is not reached.

Both were dealt with later the same day, in the working tree where the data is: the investigation stories were
rebuilt with their bundles (the site check then reports 0 findings) and the manifest was rebuilt for v2.3.0
(`verify` re-derives every value and passes with 0 drift and 0 disagreements). Those two steps were then run
again in a clean copy without the datasets and pass there: the site check with 0 findings, and
`verify --texts-only` with 0 drift. The unit tests, the smoke test and the wheel were not rehearsed again in a
clean copy after the v2.3.0 texts, so the first run on GitHub is still the first real test of the workflow. In a
clone, two things are skipped and said so: the 27 places in `reports/submission/SUBMISSION.md` and the nine
values read from `reports/integrity/crosscheck.json`, because neither file is committed.

## The second-labeller kit

The links in `agenttrace/claims/audited_links.json` were labelled by one reader, the authors' AI assistant, reading the records with a helper script. No person read them by hand.
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
  Result: **the deliveries agree on every dataset, but not independently on the release.** Identical on the
  collusion.wiki logs (9,867 deliveries), the demo swarm (164), the benign swarm (1) and all 8 format samples, as
  before. On the Swarm Traces release both now find 11 write-then-read deliveries (4 between named tokens, none
  that passes the written-content test in either form; 9 at v2.2.0, before R13a). Until v2.2.0 they did not: the second implementation found 191 (192 at the
  v2.1.0 audit, against 23) with 7 in both, a disagreement of 96.4% against the 10% threshold. The cause was its
  own: redaction removes quote marks, its tokenizer then paired the quotes wrongly, lost the call around the place
  and took commits for reads (127 of the 184 extras), a place that was only read for a write (44), the LFS upload
  probe (10, R6b was not in it yet) and a reader holding the writer's token (1, R23a). I read samples of each
  group and changed the second implementation to implement R6a, R6b, R23a, R38 and R39 from the written rule and
  to read the call from the raw text where quote pairing fails. **That fix was made while reading where the two
  differed on the release and re-running after each change, so the agreement on the release is not an
  independent check of `messages.py`** (the list of changes is in the judgement file). 262 single operations on the
  release (156 only in `messages.py`, 106 only in the second implementation, of about 16,300) still differ; none
  changes a delivery, and `reports/integrity/crosscheck_judgement.json` gives each group with a judgement (several
  favour the second implementation, one favours the rule; a cut call with no verb is counted differently by design).
  The crosscheck tool exits zero on all datasets now. The v2.1.0 judgement, with 162 extras never read, is replaced.
  That judgement was made for the v2.2.0 rule. In the run of 22 November 2026 (v2.3.0 rule) the same six groups
  come out with the same sizes (110, 66, 29, 10, 7 and 1) and every row read then still differs in the same way,
  but the rows were not read again and the earlier list of operations was not kept, so the judgement is carried
  over, not repeated; the file says so.
- **Mutation testing** (`python3 -m agenttrace.tools.mutate`): the rule's code is broken on purpose, one small
  change at a time, to see whether the tests notice. A surviving mutant is a line no test defends. A killed
  mutant shows the tests are sensitive there, not that the line is correct.
  Result (full run of 22 November 2026, on `messages.py` as it stands for v2.3.0): 1,570 of 1,656 mutants are
  killed (94.8%), 3 of them by timeout. Of the 86 survivors, 78 were judged equivalent by reading the code (a
  judgement by the authors' AI assistant, not a proof, and not checked by a second reader) and 8 are not judged
  equivalent: 3 on a 48-character look-back that R13a does not state, 2 on a length guard that skips a
  7-character marker, 3 that need two records with one id. Before the tests written from the survivors were
  added, the same run killed 1,266 (76.5%). The run published with v2.1.0 and v2.2.0 was on the v2.1.0 file
  (1,124 of 1,173, 96%; 342 with the tests as they stood at v2.0.0); the file grew with R6b, R13a, R18a, R23a and
  R38b. Many of the tests pin window sizes exactly as implemented, so they guard against accidental change, not
  against the sizes being wrong. Details: `reports/integrity/mutation.json`.

**Joined fragments (R13a, 22 November 2026).** Both implementations now join a record that is cut inside a verb
with the next record when that record completes the verb, each written from the statement in
[counting-rule.md](counting-rule.md). `JoinTests` in `agenttrace/tests/test_refcount.py` cuts records of 40 random
swarms this way and requires the same deliveries as before the cut from both. The crosscheck exits zero on every
dataset with the change in. It changes what the rule counts on the release (9 became 11 deliveries); the manifest
and the published texts were rebuilt for that on 22 November 2026. Mutation testing was run again on the same
day, on the file with R13a and R38b in it (the result above).

**The reader's later output (R38b, 22 November 2026).** Both implementations also carry the second form of the
written-content test, each written from the statement. `reports/integrity/content_test_v23.json` lists every
delivery that passes only by it: none of the 11 on the release, 258 of 9,867 on the collusion.wiki logs (2,192
pass in all, against 1,934 before). The crosscheck reports the verdict of the test in both implementations. On the
wiki logs the second implementation passes 262 deliveries by R38b and the main one 258, which passes the other 4
by R38a already. The verdicts differ only through R38a, unchanged in v2.3.0: on 82 deliveries of the demo
swarm and 51 of the wiki logs, where the main implementation passes a delivery on the place's own host or page
name ([counting-rule.md](counting-rule.md)). That is a known fault of the main implementation's R38a and is not
fixed.

## Code coverage and route determinism (v2.2.0 code fixes)

- **Line coverage** (`python3 -m agenttrace.tools.coverage_lines`): **81.3%** (19,214 of 23,623 executable lines, 952 tests, measured on the working tree on 22 November 2026 with the tool's own tracer, standard library only, because `coverage` is not installed; 8 minutes). Lowest files: `figures.py` 0%, `cli.py` 9.9%, `indepeval.py` 12.5%, `external_eval.py` 25.4%, `evaluate.py` 31.5%, `failure_eval.py` 44.8%, `saved.py` 48.6%, `sensitivity.py` 70.0%. `server.py` is at 87.5% (454 of 519 lines).
  Until this measurement `server.py` read 0% and the total was 80.7%. Two things were wrong in the tool, not in the tests: the standard-library `trace` module remembers which files to ignore by bare module name, so once the library's own `http/server.py` was ignored every module called `server` was (and `trace.py`, which now reads 83.3%); and it traced only the main thread, while the server tests answer requests in handler threads. The tool now records lines by file path and traces every thread the tests start. Subprocesses are still not traced, so code that only a started server process runs (the smoke test, `cli.py`) counts as not covered.
  The total moved for a second reason: five modules were added since (they are in the count). Three of the 952 tests failed in that run, none in the counting rule; the figure should be measured again on the release commit.
- **Every route under three hash seeds** (`python3 -m agenttrace.tools.routes`, also step 7 of `tools.repro`):
  all 98 GET routes on the bundled demo swarm gave identical output under PYTHONHASHSEED 0, 1 and 12345 at
  v2.2.0. On the collusion.wiki logs, 2 routes still differed then: `attribution` (a tie in a most-common
  list in `attribution.py`, line 842) and `fx_evolution_cluster` (it differed in one full run and not when
  re-run alone). Order fixes made: identity proposals, silent-coordination pairs, message
  and place lists, the order of a record's place operations, ties in trace starts and content grades. The audit's earlier count of 5 compared a different set of routes.
  `fx_evolution_cluster` is now explained, and it was not hash order. Program evolution runs in the background
  (3.4 s on the wiki logs); until it is done the route answers a placeholder, `{"pending": true}`, after 1.5 s,
  and the tool hashed whatever came back. Which of the three servers was still computing when it was asked
  depended on timing alone. Computed directly, the clusters are identical under the three seeds, on the wiki
  logs and on the release. The tool now asks again until the answer is there. The failed-reads scenario of
  `sensitivity.py`, whose mean number of pairs had moved in its last digit between runs at the audit (6145.0
  against 6145.1), was also checked directly under the three seeds on both datasets and gives one output; its
  messages are now put in a total order (read time, then record ids and place) before the seeded draw, so the
  result depends on the set of messages and not on the order they arrive in.
  Run of 22 November 2026 on the working tree, 99 routes: on the wiki logs `attribution` and
  `fx_evolution_cluster` no longer differ, but one route differs on both the demo swarm and the wiki logs,
  `online_replay`: two rows of its comparison table that carry the same time (the volume alarm and the
  baseline of the same name) swap places with the seed. That is not fixed here.

- **Keyboard access in a browser** (`python3 -m agenttrace.tools.interact --keyboard`, also part of
  `tools.interact` and so of `tools.check --full`): headless Chrome, driven with key events only. One press of
  Tab from the stop before it lands on a record chip, an actor chip, a place chip, an agent chip, a glossary term,
  a clickable table row, the search box and the Inspector's back button, and each shows a focus outline; Enter or
  Space does what a click does (a chip or a row opens in the Inspector and the focus moves there, an agent chip
  opens its card, a term opens the glossary); a focused chip shows the hover card a pointer would get; the search
  results are reached with the arrow keys, not with Tab (they are a listbox: the box keeps the focus and names
  the active result), Enter opens the active one, Escape or Tab closes the list; Escape closes the hover card, the
  agent card and the glossary; 40 presses of Tab through the Overview find an outline on every stop.
  Result on the demo swarm: 37 of 37 checks pass (about 25 seconds). Two things failed when the pass was first run and were fixed in
  `app/core.js`: closing the glossary with Escape put the focus on the Glossary button instead of the term that
  opened it, and leaving the search box with Tab left its results open. **It proves** these controls on the views
  it visits (one element of each kind, on the demo swarm). **It does not prove** that every view is usable from the
  keyboard (charts drawn in SVG are not covered), nor anything about a screen reader: roles and labels are
  checked for the search results only, and nobody has listened to the app.

## What still needs a person

- **A second labeller.** The audit's labels are one reader's, the authors' AI assistant, and a reviewer disagreed with 11 to 13 of its 18 "true" labels at v2.1.0. The kit makes a second reading cheap; it does not
  do it.
- **Whether the rule is the right rule.** Every check above takes "a read of a place after a write by another
  token" as given. Whether that is a message is a judgement.
- **Unregistered numbers.** Someone has to decide, for each number in `provenance_unregistered.tsv`, whether to
  register it, cite its source, or drop it. Numbers quoted from other people's reports (about 1,200 agents,
  about 700) cannot be re-derived here at all.
- **Wording.** Verify checks the number, not the sentence around it. "All 24 messages passed through dataset
  repositories" can print the right total and still be false about the word "all", or about the word "messages": a registered count of write-then-read deliveries is not a count of messages.
- **The PDFs, the video and the screenshots.** The PDFs are rebuilt from the sources (`python3 paper/build.py`) and were rebuilt for v2.3.0. The video was recorded again on 22 November 2026 from the v2.3.0 script, and the screenshots in `docs/assets` were captured again the same day; both are made separately from the texts, nothing checks them against the texts, and they can lag behind the next change.
- **A run of the agent harness with a real model.** [harness.md](harness.md): only a scripted offline run exists, because the machine had no API key.
- **The outside datasets' labels.** `verify` re-reads the saved results in `reports/external/`; it does not re-run those measurements (the datasets are not in the repository), and it cannot say whether an LLM judge's failure labels or a game's collusion label are right.
- **Recall.** Nothing here measures how many real deliveries the tool misses outside the audited pool. A reviewer read about 90 places the rule ignores and found none missed, which bounds unseen misses at about 23 more at 95% confidence; it is a failed hunt, not proof.

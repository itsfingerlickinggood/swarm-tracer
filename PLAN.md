# Swarm Tracer: quality and improvement plan

Written Nov 9, 2026, with about 13 hours to the hackathon deadline (Nov 9, 11:59 UTC). Phases A–C are for before the deadline; D–F are the roadmap after it. Each step says what "done" looks like, so progress can be checked rather than felt.

## 0. What we are protecting

Three promises the tool makes, and what would break each:

| Promise | Breaks if |
|---|---|
| Every number is counted from the records and says what it counts | two views disagree on a count without saying why; a label hides its denominator; a stale figure survives a code change |
| It works on any agent swarm, not one dataset | a format loads wrong, a tab crashes on empty or odd data, a rule is hard-coded to Swarm Traces |
| An investigator can trust and check what it shows | an invented id is shown as real; a record's text injects HTML or prompts; a confidence label means nothing |

Everything below is in service of one of these.

## A. Find the bugs (about 3 h, run in parallel)

### A1. Static review of everything that landed in the last two days
About 21,000 lines arrived from five parallel builders who never saw each other's code.
- `/code-review high` per module: readers, identity, live, casework, groundtruth, compare, cache; then the JS views.
- Watch for: exceptions on empty inputs, off-by-one in hour bins, `None` times, dict key errors on odd records, unbounded loops on big data, shared mutable state across requests.
- **Done when:** every finding is either fixed or written down with a reason.

### A2. Scripted smoke test: every dataset × every tab × the Inspector
A script (headless Chrome, as used for the figures) that loads each of these and visits all ten tabs, opens one record, one actor and one place, and records console errors and `.warn` boxes:
- Swarm Traces release (189,579 records), collusion.wiki logs (19,990), the demo swarm, each of the 8 format samples, a text-only folder, a one-line file, an empty file, a CSV with only headers, a JSONL with a broken line, a non-UTF-8 file.
- **Done when:** zero console errors and every empty state says why in plain words. Keep the script in `agenttrace/tools/smoke.py` and run it in CI.

### A3. Consistency oracle for counts
One script that pulls every endpoint for a dataset and asserts the cross-checks:
- named actors: top bar = overview = Agents tab; network's "36 of N" uses the same N;
- messages: network 166 = replay 141 + 25 merged = conversation totals summed over pairs; What's missing's 97 merged = named 25 + anonymous 72;
- pairs: tab badge = network lead = matrix row×col nonzero cells;
- dated records: ribbon % = overview KPI = Events "with a time" when unfiltered;
- replay signals: Early flag table = Timeline chronology = Overview dots = Compare "first sign".
- **Done when:** the script passes on both real datasets and runs as a test.

### A4. Fresh-eyes audit of the new features
Two reviewers who have not seen the code use the app as a first-time investigator (as before; it found 73 issues), scoped to: Agents, Compare, Live drawer and rules editor, Case file drawer and export, pack builder, labeling buttons, AI "Draft incident report", and the Events chart. Same report format: where, what's confusing, why, fix.

### A5. Security review of the new surface
The server listens on 127.0.0.1 only, but it now takes paths and writes files:
- `live_start` and `compare_load` accept any path on the machine: restrict to files the user chose or to a configurable data root; never follow a path from a page or an upload.
- `pack_save` writes into the package folder: validate the name strictly (slug only), refuse `..` and absolute paths, cap size.
- `case_export` and `/api/x/case`: notes are user text; make sure they are escaped in the exported HTML.
- Record text is attacker-written: confirm every render path uses `esc` (including `richText`, `highlight`, hover cards, conversation snippets, the AI pane's `linkify`) and that the AI prompt keeps the "data, not instructions" fence.
- Uploads: size cap, temp-dir cleanup, no symlink following.
- **Done when:** each item has a test or a written reason it is safe.

### A6. Concurrency and lifecycle
- Two uploads at once; live mode reloading while an upload runs; Compare loading while the main dataset changes; a browser tab left open across a server restart.
- **Done when:** no 500s, no half-swapped sessions, clear messages.

## B. Fix and lock in (about 3–4 h)

- Fix in this order: crashes, wrong numbers, security items, confusing wording.
- Every bug becomes a test (unit or smoke). Test count is not the goal; the oracle and smoke scripts are.
- Keep the deadline in view: anything not fixable in 20 minutes goes to the "Known issues" section of the docs instead of being half-fixed.

## C. Make the hard claims trustworthy (about 2–3 h)

### C1. Ground truth across several simulated swarms
Run `groundtruth make` with 4–6 seeds and settings (20/40/80 agents; 1 or 2 tokens per agent; more or less noise; embedded vs field times). Report message-link precision/recall and sign-timing error as ranges, not one number. Add the table to the docs and a line to the report's limitations.

### C2. Score identity merging against the truth
The simulated swarms know which tokens are one agent. Score the Agents tab's proposals by confidence band (how often "high" is right). If "high" is below about 80% precision, tighten the rule before the deadline or relabel the bands.

### C3. A benign baseline
Generate a benign simulated swarm (agents working in parallel, no shared places or messages beyond their own threads). Run the warning signs and the alert rule on it and report what fires. This is the first false-positive measurement the project has; say so in the report.

### C4. One live AI run
With a real key, run the five quick questions, the gap audit and the report draft. Record whether the model keeps the JSON format, how many ids it invents (the checker shows them) and the latency. If the format fails often, add a repair step: re-ask once with the parse error.

### C5. Real framework exports
Get at least one real export (LangSmith, Langfuse or an OpenTelemetry GenAI trace) and load it. Fix the reader if the shape differs from our samples. Until then, the docs say the readers were tested on written samples.

## D. Engineering hygiene (no CI service; everything runs locally and is published)

- **One local check command**, `python3 -m agenttrace.tools.check`: runs the unit tests, the smoke script on the demo swarm and the consistency oracle, and prints pass/fail. Run it before every push; the README shows the last run's result as a line, not a badge.
- **Publishing:** tag releases (`v0.1`, `v0.2`, …) and attach the report PDF and the built wheel to a GitHub Release, so `pipx install` can pin a tag instead of `main`. The website on GitHub Pages republishes itself on every push to `docs/`.
- **Versioning in the app:** show the version and the dataset hash in the top bar and in every export, so a case file says which build produced it.
- **Coverage** measured locally (`coverage` is not stdlib, so optional): aim at the counting rules, readers and identity modules first.
- **Type hints and a linter** (ruff) on the Python; a basic ESLint pass on the JS; both optional, run locally.
- **Performance budgets:** load and first paint of each tab on the wiki swarm (3,226 actors) under 2 s; the network graph and swimlanes are the known slow spots. Add a cheap "too many to draw, showing the top N" path.
- **Error reporting in the app:** a visible banner when any fetch fails, with the endpoint and the message, instead of a blank card.

## E. New forensic analysis features

Each one is an answer an investigator asks for and the tool does not yet give. Ordered by value per hour of work.

1. **Trace anything.** Type any string (a token, a URL, a hostname, a line of code) and get its full lineage: where it first appeared, every record that carried it, in time order, with actors and places, as one chart and one list. Today this exists only for tokens (seen-then-used) and whole programs; it should work for any fragment.
2. **Credential lifecycle.** For every identity token: first seen as data, first use, who used it, last use, which places it opened, whether another identity carried it, and when it went quiet. One row per token, a lifecycle bar each, sortable; plus an "exposure map" of which tokens reached which places.
3. **Command-and-control reconstruction.** For command files and boards: who wrote the instruction, who polled it, and what changed in the readers' behaviour in the hour after (new intents, new places, bursts). Timing correlation between a write and the readers' next actions, with the records behind each link.
4. **Program evolution.** Near-duplicate clustering of code (not only exact matches): a tree of versions, who changed what (a diff between versions), and whether the change spread. Answers "who improved the attack, and did others adopt the improvement?"
5. **Stage ladder per actor.** Map intents and tags to stages (recon, credential access, execution, persistence, exfiltration, cover-up; the packs already carry a `stage` per behavior). Draw each actor's climb through the stages over time, and the swarm's first time at each stage. This is the forensic "kill chain" view.
6. **Lead–lag between actors.** For each pair of active actors, who moves first: cross-correlation of their hourly activity with a lag, to show followers and leaders without relying on messages alone. Reported with the number of hours of overlap it rests on.
7. **Anomaly timeline per actor.** For each actor, hours that break its own pattern: a burst, a first new place, a first new intent, a first harmful action. One strip per actor, so the eye finds "when did this agent change".
8. **Dead drops and pickup time.** For every place written: who picked it up and how long it waited; places never picked up; places picked up by many. A dead-drop ledger, exportable.
9. **What-if mode.** Apply the Agents tab's accepted merges (and any messages or signs the investigator rejected) and recompute every count and sign on the fly, with "as counted" and "after your decisions" side by side. Hypotheses become testable in the tool.
10. **Deterministic narrative.** A "what happened" chronology built from the data alone (not the AI): per actor and for the whole swarm, sentence by sentence with record ids, following the stage ladder and the first-of-each-kind moments. The AI report drafts from this, so its facts cannot drift.
11. **Reference swarm comparison.** Load a benign or known swarm as the reference and show, for the swarm under investigation, which measures deviate and by how much (message rate, group size, stage climb speed, reuse speed). Compare does this for two swarms; this makes one of them the yardstick.
12. **Integrity and chain of custody.** Hash of every input file and of the record ids, recorded in every export and in the case file; a note of which build and pack produced the analysis; who pinned what and when.
13. **Exports for the SOC.** Timeline CSV, a Timesketch-compatible CSV, and a STIX 2.1 bundle of indicators (tokens as pseudonyms, places, URLs) with the stage labels; the alert rules exportable as detections.
14. **Better search.** Boolean and regular-expression search over record text, saved searches, "find records like this one" (same masked code, same places, same tokens).

## E2. Improvements to what exists

- **Who talked to whom:** edge bundling or grouping for the dense middle; community detection with named groups; a time window (not only "up to now"); filter the graph to one actor's neighbourhood; export the graph as SVG or PNG; the conversation view gains a diff of what each read carried.
- **Timeline:** lanes grouped by the Agents tab's groups; zoom to one lane; click-drag on the lanes themselves; show the dead drops as marks on the place that held them.
- **Channels:** a place lifecycle (created, busiest hour, last read); writers-to-readers flow per place type; the same "leave out merged places" toggle the network has.
- **Spread:** program diffs between source and adopters (see E.4); a "who copied whom" tree instead of only source → each adopter; adoption speed as a distribution, not only the median.
- **Early flag:** run several rules side by side and show each one's alert time and harm share on one chart; per-sign precision from the simulated swarms shown next to each sign; a "what if this place were not watched" toggle that drops one channel type from the signals.
- **Agents:** show the evidence against as clearly as the evidence for; a "why not merged" for pairs people expect; merge groups drawn as a small graph; export decisions with the case file.
- **Inspector:** compare two records side by side (text diff with the highlights); "records like this"; the thread as a tree, not a line; pin and label from the hover card.
- **Events:** saved filters; export the filtered set as CSV; pin many at once; a "first time this actor did X" marker on rows.
- **What's missing:** each gap links to the records it counts (click the bar, see them); a per-actor coverage view ("how much of cred 169's time is dated").
- **AI investigator:** let the model ask the tool questions (a few safe read-only functions: actor profile, place detail, conversation, search) so answers rest on fetched facts rather than the brief; show which facts it fetched; a repair step when the answer format breaks; a "verify every number" pass that recomputes any count it quotes.
- **Case file:** chain of custody (E.12); a printable summary page; attach the ground-truth score when one exists.
- **Live mode:** incremental re-analysis of new records only (today it reloads everything); desktop notification on alert.
- **Glossary and help:** search in the glossary; a "How to read this chart" line under every chart; keyboard navigation and labels for every control.
- **Performance:** the on-disk index for large datasets so loading, live mode and search all stop re-reading the whole file.

## F. Documentation and the report

- Add a **Known issues** page and keep it honest; link it from the README.
- Add the ground-truth table (C1), the identity score (C2) and the benign baseline (C3) to the docs and, if there is time, to the report's Appendix B.
- Re-record the screenshots and the walkthrough video whenever a visible change lands (`paper/build.py --capture`, `/tmp/st_scratch/vid` recipe is in the commit history).
- Keep one glossary: the app's GLOSSARY and the docs' "How it works" must use the same definitions.

## Order and ownership for the next 13 hours

Phases A–C only. E and E2 start after the submission, in the order listed; each item ships with its own smoke check and a docs page, and is published by pushing (the website rebuilds itself) and tagging a release.

| When | What | Who |
|---|---|---|
| now–+1 h | A2 smoke script, A3 oracle, A5 security checklist | parallel helpers |
| now–+2 h | A1 code review per module, A4 fresh-eyes audit | parallel helpers |
| +2–+5 h | B: fix, test, re-run smoke and oracle | main session |
| +5–+7 h | C1–C3 ground truth, identity score, benign baseline | one helper, then main |
| +7 h | C4 live AI run | needs the real key |
| +7–+9 h | F: docs, known issues, re-record figures, final push | main session |
| by 11:59 UTC | report name/affiliation, submission form | you |

## Risks

- **Usage limits** stopped three helpers once already; keep briefs short and checkpoint commits frequent.
- **Scope creep**: anything in D or E that tempts before the deadline waits.
- **Over-claiming**: every new number in docs or report must come from a script output that is committed or reproducible.

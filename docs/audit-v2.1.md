# Audit of Swarm Tracer v2.1.0

Done 15–16 November 2026 by four independent reviewers who were told to find what is wrong, not to defend the tool. They read the code and the texts and re-ran checks on the data. This page lists what was missing, unsupported or fake in v2.1.0, and what the next version should change. It is kept as written on 16 November; the status line below says what has since been fixed.

**Status, 16 November 2026 (v2.1.1 / v2.2.0).** Fixed in the texts: every item in the section 2 table except the two noted below, and plan items A1 to A6. Done in the rule and the evaluation, with the evidence in `reports/`: B (23 became 9 write-then-read deliveries, 4 between named tokens, 0 where the reader is shown using the content) and C (independent generator in `reports/validation/independent.md`, comment-only place mentions ignored, baselines in `reports/evaluation/baselines.json`, attribution holdout by thread, resampling over settings, insider findings graded with a tolerance fixed in advance). The code fixes of D were made by other changes in the same release; their status is in the tests and `docs/integrity.md`, not re-verified on this page. The corrections are summarised in the README and in [known-issues.md](known-issues.md#corrections-in-v211--v220). Not fixed: the two quoted runs of record text in git history; the video, which still carries the old narration and must be re-recorded from the corrected script; and everything in section 4 (a second human labeller, real benign traffic, a pre-registered test committed to git before the data, line coverage in a browser test, and the decision on resubmission to Apart). Section 1 below describes v2.1.0; the corrected numbers are in the README and validation.md.

**Status, 22 November 2026 (v2.3.0).** Since the line above: the count is 11 write-then-read deliveries, not 9 (a record cut inside a verb is now joined with the record that completes it, plan item B3; still 4 between named tokens and 0 where the reader is shown using the content, and the two added deliveries are labelled unclear, not judged). From section 4, done: **real benign traffic and outside datasets** (four public datasets measured, `reports/external/`: the Alert rule fires on 95% to 100% of runs with no recorded attack, who-talked-to-whom holds by pair where the log has structure, failure attribution is at chance); **a pre-registered test** of the early warning (`reports/earlywarn/prereg_v23.json`, written before the swarms were generated but not committed to git first; the test failed: no alarm leads the first harm on either simulator); **line coverage** (81.3%) and **a keyboard pass in a browser** (37 of 37 checks on the demo swarm); a CI workflow (not yet run on GitHub). Also new: an agent harness with logged truth, run offline with a scripted stand-in only (no real-agent run), and a second form of the written-content test (R38b). Still not done: a second human labeller; a second real incident; any channel beyond those in the pack; a screen-reader check; an independently timed cold load; the pre-registration's order in git history; the two quoted runs of record text in git history; the decision on resubmission to Apart. The video was re-recorded on 22 November 2026 from the v2.3.0 script. The corrections are listed in [known-issues.md](known-issues.md#corrections-in-v230).

**Bottom line.** The tool runs, its numbers reproduce, and its outside citations (METR, Hugging Face, the Swarm Traces authors) check out. But three headline claims do not survive: the size of the message count, the early-warning lead, and the simulated accuracy. Each rests on a single reader's labels or on a simulator that shares the detector's vocabulary. Until the fixes below land, treat those three as leads, not results.

The reviewers' full reports are kept locally in `reports/audit/` (they quote short record snippets, so they are not published). Each finding below is marked **confirmed** (the reviewer read or re-ran it) or **suspected**.

## 1. Claims that do not hold up

### 1.1 The message count of 23 is probably too high (confirmed by reading, single reader)

A reviewer read both records of all 23 deliveries and would defend **about 5 as messages (range 3 to 7)**. It disagreed with 11 to 13 of the 18 audit labels that said "true".

- **10 of the 23 rest on one upload probe.** A write was an LFS batch request with `operation: 'upload'` for a file whose download had been requested 34,000 s earlier; the readers read a file that already existed.
- **A reader loops over a token list that contains the writer's own token** (R0006727→R0006743, R0006792).
- **A "write" that is a directory create read by a random-named GET** (R0045942→R0046036), and merged unnumbered repositories (R0032332→R0044678, R0050140).
- **What survives** (5): a handle POST then a GET (R0006584→R0006786, but both tokens are one agent), and two README commits followed by repo-info GETs (R0044824→R0045143/R0045338/R0046969; R0044999→R0045751, weak). At agent level only 3 remain.
- **Even these 5 are a commit followed by a later GET of the repo.** No reader quotes what was written, so none shows information transfer. "Message" overstates it; "write then later read of the same place by another identity" is accurate.
- **Who labelled the audit:** the labels came from a tool-assisted reading by the authors' AI assistant, never double-labelled. Several texts say a person read them by hand. That is wrong.

Recall: the reviewer read about 90 places the rule ignores and found no missed messages. That is a failed hunt, not proof; the ceiling for unseen misses is about 23 more at 95% confidence.

The second implementation finds 192 deliveries. Of 40 sampled extras (of 162 never audited) none was a message (0 to 8.8%), so it is wrong in the way the judgement file said: it takes commits for reads. This disagreement appears in neither the report nor the slides.

### 1.2 The +5.8 h early-warning lead is an artefact (confirmed by re-run)

- The shared-place sign counts a place named inside a code comment. The simulator writes such comment notes at random times. With the notes off, the lead is **-1.9 h**, meaning the sign fires after the harm. The shipped `forward.json` agrees: its "quiet" setting is -1.91 h, its "realworld" setting +1.73 h with 40% of swarms negative.
- On the real release the same sign is the latest of the signs (50% of harm still to come).
- A bootstrap over the 9 settings gives 0.48 to 6.82 h, not the 5.36 to 6.02 h of a bootstrap over swarms; three settings share seeds.
- **"Frozen before the test" cannot be verified.** `frozen_signs.json` was committed and then rewritten 13 minutes later; the forward results were generated between the two commits and are gitignored. The forward swarms come from the same generator and the same 12 settings as the tuning swarms. `earlywarn freeze --check` now reports that `messages.py` and the pack changed since the freeze, and the forward test was not re-run.

### 1.3 Simulated accuracy and false alarms are optimistic (confirmed by an independent generator)

- The generator writes the exact strings the pack matches (`zz<WORD>_BOARD`, `169.254.169.254`, `/api/v1/namespaces`, `x-ndjson`), and the benign generator never produces boards, metadata calls or shared writers, so "0 false alarms" on those signs is true by construction.
- With an independently written generator (different naming, code styles, clock skew, file order): message precision **0.69** (published 79%), recall **0.56 to 0.60** (published 73%), and the shared-place sign fired in 0 of 20 coordinated swarms.
- v1.1.0 scored 79% on the simulator while 165 of its 166 links on the real release were false. The simulator did not predict real-data error then, and the front page, slides and submission summary still advertise 79% and 73%.
- **Dating depends on file order and embedded epochs.** With a time field on only 30% of records, precision falls to 0.14 to 0.21. With the file grouped by agent the trace comes back undated and the tool reports 0 of 121 to 196 true messages. The "median dating error about one minute" is a property of the simulator.
- **False alarms:** on 40 benign look-alike swarms (shared leaderboard, CI polling, coordinator/worker, honest cloud agents, plain agents) the Alert rule fired in 29 (95% range 57 to 84%), against the published 12 of 30. It fired 8 of 8 in the first three classes. It detects information flow, not malice. Honest cloud agents trigger the Watch rule 8 of 8, because metadata calls, cluster calls and any dataset commit are in the harm list. On the project's own 30 benign simulated swarms the first message between named actors fires in 16 and the Alert rule in 12; the slide says "0 in 15 runs".

### 1.4 The shared-control signs lose to simple baselines on the real release (confirmed)

| Alarm | Share of harm still to come |
|---|---|
| First new host after 12 h | 91.3% |
| Distinct-actor alarm | 86.9% |
| First `search_for_secrets` intent | 91.2% |
| Volume alarm (the published baseline) | 83% (93% with a 6 h history) |
| Shared-control signs | 50 to 57% |

The order flips between simulation (volume alarm 5.9 h after harm) and the real incident. Also: the single-agent signs do not all fire at 90 to 100%; the Kubernetes token, Kubernetes API and metadata signs fire at 82%, 80% and 79%, after the volume alarm.

### 1.5 The harm list builds in the answer (confirmed)

64% of the 8,124 harm records are dataset writes, so the first dataset write is "early" by construction. `kubernetes_token` was added after the first replay. Changing the harm definition moves the shared-place share from 37.7% to 56.6% and the first-message share from 62.3% to 96.1%; the published "50–57%" understates this. 37,605 undated payloads are outside the denominator, and "100% to come" at 13:29 on 9 July is left-censoring because that is the first dated record.

### 1.6 Other measured claims

- **Seven milestones within 2.2 h:** the matching rules were written knowing the published times. Across 27 plausible surge settings only 11 fall within 2.2 h. "Last record" is the end of the release window, and three unreachable moments are outside the denominator. Three events (not two) precede the published time.
- **Identity: "12 of 12 high-confidence merges right"** is 12 of 380 true pairs, about 3% recall, and the rule was rewritten after it scored 10 of 240 on the same swarms.
- **Attribution (7.6% of anonymous runs, holdout precision 99/96/86%):** the holdout is contaminated (about 75% of test threads were seen in training; the cutoffs are fitted to the same targets); holdout coverage is 68.5% against 7.6% on real runs; without the three largest actors precision drops to 98.6/90.4/71.3%.
- **Insider findings (17/9/15):** graded by code in the same commit as the tool output, with the tool's own 5.05 h error as the tolerance. 15 of the 41 findings are the Swarm Traces authors' own claims searched in the data. A fresh run gives 16/10/15.
- **Online monitor:** 3 of 15 signs match the replay within 15 minutes, and the report's claim that a lab could run the signs online contradicts the project's own online test, where volume alarms fire 29 h later.
- **Sensitivity ranges** use 10 draws; place, token and program signs are not time-perturbed, and the harm list and baseline parameters are not varied.
- **Audit precision 18 of 18** is in-sample, one labeller, tool-assisted.

## 2. What is wrong in the published texts

| Problem | Where |
|---|---|
| States that a person read the 258 links by hand | `first-message.json:130`, `fx_benchmark.js:65`, `README.md:51`, `demo-script.md:27`, `datasets.json:67` |
| README says the PDF is "left as submitted"; the PDFs were rebuilt and print 23, not 19 | `README.md:13` |
| States all code was written 7–8 Nov; git runs 8–15 Nov past the 9 Nov deadline | `README.md:127`, report "Code and Data" |
| Stale counts: 24 messages, "5 after audit", "40 of 40" | `known-issues.md` |
| Appendix B: one dataset read by six tokens, another by seven; no write has more than two named readers | report Appendix B |
| "Ordering is robust, about 30 h apart": first write and first message are 87 minutes apart; "a day or more ahead" is about 20 h | report |
| "Every claim comes with a measured range"; "every number can be re-derived" (269 numbers are outside the manifest) | `docs/index.html:129`, README, report |
| Hard-coded in-app string "median error about 15 min, p90 about 2 h" shown for every dataset | `fx_spreadmap.js:300` |
| The Howard-Jones citation contradicts the report's replay; two talks have no URL | report references |
| Wiki logs are called a "separate swarm"; collusion.wiki attributes the agents to OpenAI | docs |
| "385 self-termination records": correct, but only 73 are `os.kill` | report |
| "Anonymous runs" is 3,767 in one place and 77,626 in another | report |
| The "66% to 79%" claim has no saved run behind it | validation |
| Video narration gives the per-token 50 to 57% figure while the screen shows 38% and 5% | video, `docs/index.html:98` |
| Deep dive section 1 rests on old counts | `deep-dive.md` |
| Two quoted runs of record text remain in git history | repository |

Of 1,460 claims extracted, 461 are consistent with tool output (which is not independent truth), 348 have no evidence at the claim, and 80 are tied to the problems above. About 150 distinct figures were recomputed from the data or checked against sources; the METR, Hugging Face and Swarm Traces figures match.

## 3. Problems in the code and app

**Severe**
- **Duplicate ids inside one file collapse silently** (`model.py:362-372`, `session.py`): a 9-row CSV with one id loads as 1 record, with no warning.
- **Stale results from the cache** (`cache.py:67-91`): the key hashes the pack name, not its content, and the claims files are outside it. Editing a pack and reloading served the old one.
- **Not deterministic under another `PYTHONHASHSEED`:** 5 of 61 routes on the wiki logs change content (including the first harm record on `trace_start`). The repro check compares only 6 demo outputs, so its "same hash" gives false assurance.

**Moderate**
- Five odd inputs crash `serve --input` (deep JSON, UTF-16 CSV, a NUL byte, a JSON `null`).
- No lock on the first-request caches: four concurrent attribution requests took 66 s each and 3.8 GB.
- Pack regexes have no time limit; `(a+)+$` ran past 20 s.
- Packaging omits `static_shim.js` and `sitecheck_allow.json`; features that read paths beside the package find nothing when installed.
- The server always allows the working directory and the package parent as readable roots, with no extension check (it accepted `pyproject.toml`).
- Upload folders leak: 621 `swarmtracer-*` folders in the temp directory, 6 non-empty (about 112 MB). I could not delete them (the command was blocked); remove them by hand.
- The "measured" tables in `fx_content.py:464` and `fx_coord.py:436` are hard-coded and untested.
- 90 tests assert only presence or truthiness; `claims_page.py` and `flow_page.py` have no test; the AI path is tested only against a fake provider; line coverage was not measured.
- Keyboard and screen-reader access: entity chips are spans, table rows have no key handling, hover cards open on mouseover only, the app has 5 `tabindex`; opening the Inspector is mouse-only.
- Only 8 named formats exist (there is no "18 formats" text in the repo), all verified on hand-written samples; auto pack choice is tuned to the two known datasets.
- Slow routes on the release: attribution 15 s, insiders 13.6 s, no progress indicator.
- The AI `baseUrl` accepts any host, and redirects resend the Authorization header.

**Held up:** no crash or hang over 20 s on 14 odd synthetic inputs besides the five above, 1,507 of 1,507 smoke cells, a clean-copy build, and path traversal, host and origin checks all refused as intended.

## 4. What is missing

- **A second human labeller.** Everything in section 1.1 turns on it. The labelling kit exists; nobody has used it.
- **Real benign multi-agent traffic** and a real third dataset.
- **Real incident data beyond one incident**, and any channel other than the five in the pack (S3, Redis, queues). Recall there is assumed near zero.
- **A pre-registered, held-out test** for the early-warning signs.
- **Line coverage, a browser test of keyboard and accessibility,** and an independently timed cold load of the release.

## 5. Plan for the next version (v2.2.0)

Order matters: correct the claims first, because they are public.

**A. Correct what is published (a patch release, v2.1.1, before any new work)**
1. State that the audit labels are one reader, the authors' AI assistant, and that a reviewer defends about 5 of the 23. Show 23 as "write then later read", with 3 to 7 as the range.
2. Withdraw "+5.8 h ahead". Say the shared-place sign fires after harm unless a swarm carries many place-naming notes; put the -1.9 h result beside it.
3. Put "optimistic: independent generator gives 0.69 / 0.56 to 0.60" next to every 79% / 73%, and remove "every claim comes with a measured range".
4. Fix the false-alarm figures to the 40-swarm result and the "0 in 15 runs" slide.
5. Fix the provenance statements, stale `known-issues.md`, Appendix B, the ordering claims, the 15-minute string, and the video line.
6. Add the second implementation's 192 to the report and slides.

**B. Fix the message rule** (each removes false links; target a defended count near 5)
1. An LFS `operation: 'upload'` batch counts only if a later request sends the object; skip when the same object was requested with `download` earlier (removes 10 of 23).
2. Do not count a read whose record lists the writer's own token (R0006727, R0006792).
3. Make the cut-verb rule fire when the record ends inside the verb (`'POS'`), and merge consecutive fragments before ordering.
4. Add unnumbered `[HF REPO]`, `[REDACTED:username:…]` and `[USER n]` to coarse places; key board places by full path.
5. Classify pre-signed S3 form uploads as writes and `paths-info` POSTs as reads.
6. Fix the identity merge for 1722/1721, which sit only in 4+ token key sweeps.
7. Add a written-content test: count a delivery as a message only when the reader quotes or uses what the writer wrote, and report the two counts separately.

**C. Make the evaluation honest**
1. Replace the simulator with an independent generator and benign look-alike classes; publish its numbers beside the old ones.
2. Strip comment-only mentions from place use, then re-run the forward test with a frozen file committed before the data is generated, and the forward results committed.
3. Score the signs against the simple baselines (first new host, distinct actors) and report where they lose.
4. Fix the holdout for attribution to be by thread, not by random half; report coverage on real runs only.
5. Resample over settings, not just swarms; use per-swarm binomial intervals.
6. Grade insider findings before the tool runs, with a tolerance chosen in advance.

**D. Fix the code**
1. Rename repeated ids per file and warn; reject NUL, UTF-16 and `null` files with a clear message instead of a traceback.
2. Hash pack content and claims files into the cache key; remove the memoised pack.
3. Make every ordering total, sort before summing, and run repro on all routes under three hash seeds.
4. Add a lock around first-request caches, a time limit on pack regexes, and a progress indicator on slow routes.
5. Package `static_shim.js` and the allowlist; tidy the upload folders on start.
6. Restrict readable roots and require a known extension.
7. Keyboard access for chips, rows and hover cards; real roles in the omni results.
8. Tests that assert values, tests for the two untested page modules, and a coverage measurement.

**E. Needs you**
1. Second labeller (the kit is ready), the permission email to the Swarm Traces authors, and approval to download an openly licensed third dataset for real benign traffic.
2. Decide whether to resubmit to Apart. The submitted PDF says 19; the audit now says even 23 is high.

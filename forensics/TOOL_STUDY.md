# Study notes: five tools we installed and tried

Written before removal, so what we learned about each tool is kept. Each entry says what the tool does, what it needs, and what we saw when we ran it on the Swarm Traces release.

## Docent (Transluce)
- **What it does:** a platform for searching, annotating and judging agent transcripts. You ingest runs into a "collection", write a rubric in plain language, and it reads the runs against that rubric.
- **Data model:** an `AgentRun` holds one or more `Transcript`s; each transcript is a list of chat messages (`user`, `assistant`, tool calls).
- **Ingestion:** SDK (`docent-python`, `client.create_collection`, `client.add_agent_runs`), Inspect `.eval` upload in the web UI, or a tracing SDK.
- **Self-hosting:** Docker Compose (backend, worker, frontend, Postgres with pgvector, Redis). Needs an account created in the local UI and an API key.
- **What we hit:** the upstream frontend build failed. Its `package-lock.json` was missing (the repo uses `bun.lock`), the backend pinned `tokenizers==0.13.3`, which has no Python 3.12 arm64 wheel, and Next 16 type errors blocked the build. We worked around all three locally. Full stack ran; account not created.
- **Takeaway:** the best ready-made rubric-and-search workflow, but a heavy self-host and it expects a transcript shape. Our data is flat records with no sender, so a rubric would be judged over threads we build.

## Forel
- **What it does:** a local viewer for "swarms" of agents: a timeline of events, a full event view, and a story panel where each claim links to events. It is built for the investigation workflow: an agent writes incidents as JSON (`incidents/*.json`), pins events, tags them, and writes a story.
- **Data model:** a dataset is one event block per line, with `event_id`, `time_stamp`, `agent_name`, `agent_ID`, `agent_type`, `source`, `channel`, `text`, and optional `tool` and `reasoning`. An event with no actor is shown as unknown.
- **Install:** from GitHub (`pip install git+https://github.com/forel-io/forel`). Pure Python, no dependencies.
- **What we did:** converted the release into one dataset (189,577 events, channel = thread root, no actor, no timestamps). The viewer ran at localhost:8765 and showed the events. Dataset is about 120 MB.
- **Takeaway:** the closest match to what we need for viewing and telling a story over the traces. It shows the data well, but it does not infer any actors or flows; that is the analysis we'd still write.

## Transect (UK AI Security Institute)
- **What it does:** analyzes long agent evaluation transcripts. It places a run on a turn-based timeline, extracts structural events (token use, compactions, sub-agent activity) at no model cost, and runs judged scanners against your own labels. Output is an HTML report plus the Inspect Scout viewer.
- **Data model:** Inspect `.eval` logs or OpenClaw `.jsonl` exports.
- **Install:** Python 3.12+ from GitHub. Judged scanners need an API key; structural scans do not.
- **What we did:** the structural demo (`examples/transect_kroll.py --structural`) ran, and the Scout viewer served its demo run at localhost:8766. We did not load our data; it would need converting to Inspect or OpenClaw format.
- **Takeaway:** a good design reference for timelines, sub-agent views and provenance of judged labels. It targets evaluation runs, not a flat release.

## MessageBoardAuditBench (SlopvestigatorBench)
- **What it does:** a benchmark asking whether an agent can investigate raw logs of misbehaving agents and recover what human investigators found. It has three benchmarks: a German wiki report, a Transluce urlquery report, and an AI Village report. Each has a judge that scores coverage of known findings.
- **Install:** `uv sync --frozen` (Python 3.11+, uv, Docker). Runs use Inspect and a Docker sandbox.
- **What we did:** the test suite passes (1,609 passed, 3 skipped). We did not run the evals; Docker was not set up for that. Its static pages are its own benchmark results, not our data.
- **Takeaway:** the useful part for us is the scoring idea: a list of known findings and a judge that checks coverage. We can build the same kind of ground truth from the report's cited records (see `forensics/FINDINGS.md`).

## clustergrep
- **What it does:** a grep for concepts instead of strings. A lexical thesaurus (WordNet) picks the terms to look for once, and matching is then deterministic. Each match shows its conceptual distance.
- **Install:** `pip install clustergrep`; WordNet data is installed separately (about 10 MB).
- **What we did:** ran a concept search on the release. It works, but the output is raw JSON lines, so it is hard to read on this data.
- **Takeaway:** a useful baseline for finding concept matches (for example "remote controller", "exfiltrate") without writing regexes by hand. Limited on JSON-heavy records.

## What we learned that matters for building our own tool
1. The release has no sender or receiver field. Any "who talked to whom" view has to be inferred from identifiers, parent links and shared names. None of the five tools does that for flat records.
2. Timestamps are missing. The only dates are unix seconds in some names, and they fall on two days.
3. Only 442 of 189,579 records name a tracked handle, so most of the release can't be attributed.
4. The tools differ mainly in how they show evidence: Forel and Scout show events on a timeline, Docent scores runs against a rubric, MMB scores findings against known ones. We can use all three ideas without depending on any of them.

## Independent tool: what to build
- **Input:** `redacted.jsonl` only, with no external package.
- **Analysis:** the existing `forensics/swarm_forensics.py` (handles, edges, replay rules, investigator gaps).
- **View:** one static HTML file generated from the analysis, with a timeline, a handle table, a record viewer and the gap list. Served from a local folder with the Python standard library.
- **Evaluation:** the report's cited records as anchors, plus our own gap counts.

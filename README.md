# swarm-tracer

Forensics for AI agent swarms. Built for the Apart Research Swarm Alignment Hackathon (November 2026), for the challenge: *take the Swarm Traces dataset, build a tool that reconstructs who talked to whom and how a piece of information spread through the swarm, test whether it could have flagged the coordination early, and write down what an investigator would still miss.*

The main tool is **agenttrace** and its web app, **Swarm Tracer**. It works on any agent trace (JSONL, JSON, CSV, or a folder of linked files), not only the Swarm Traces release.

## Quick start

Python 3.9+ standard library only, no installs.

```bash
# run the app on 127.0.0.1:8010, then upload a trace file or folder in the browser
python3 -m agenttrace serve

# or preload a dataset
python3 -m agenttrace serve --input redacted_columns.csv --pack code_traces.json
python3 -m agenttrace serve --input full-wiki-logs --pack wiki_swarm.json

# tests
python3 -m unittest discover -s agenttrace/tests -t .
```

The app has three panes:
- **Left:** the analysis. Overview, who talked to whom (network graph), timeline, channels, spread, early flag, every event, and what is missing.
- **Right top:** a trace of any selected event.
- **Right bottom:** an AI investigator that uses any OpenAI-compatible endpoint. The default is OpenCode Go with `deepseek-v4.1-flash`, and you supply your own API key.

See [`agenttrace/README.md`](agenttrace/README.md) for the full guide: formats, packs, labeling and precision, and the command-line reports.

## Data

The datasets are not in this repository.
- **Swarm Traces release:** https://swarmtraces.org/ (redacted dataset download on that page). Convert it to CSV or use the JSONL directly.
- **Wiki logs** (`full-wiki-logs/`): from collusion.wiki.

## What is here

| Folder | What it is |
|---|---|
| `agenttrace/` | The general tool and the Swarm Tracer app: loader, analysis, time and identity reconstruction, message flow, claims checking, labeling, AI investigator, tests |
| `analyzer/` | Earlier single-purpose scripts for the Swarm Traces release (command cards, first flow reconstruction) kept for reference |
| `forensics/` | First-pass scripts and notes: findings, a study of existing tools, clustering, quantification |
| `reports/findings/` | A written summary of what the swarm did, with record ids |

## Limits to keep in mind

- A token or self-chosen label is not an agent. One agent can hold many tokens or names, and a shared key stands for many agents.
- Times are estimated from timestamps written in the agents' own code where no time field exists. Only blocks that pass a rank-correlation and error check are dated.
- Tags and intents are pattern matches. Precision is measured on small, single-labeler samples.
- A read or write in code is an attempt; the data rarely shows whether it worked.

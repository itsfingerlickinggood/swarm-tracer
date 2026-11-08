# swarm-tracer

Forensics for AI agent swarms. Built for the Apart Research Swarm Alignment Hackathon (November 2026), for the challenge: *take the Swarm Traces dataset, build a tool that reconstructs who talked to whom and how a piece of information spread through the swarm, test whether it could have flagged the coordination early, and write down what an investigator would still miss.*

The main tool is **agenttrace** and its web app, **Swarm Tracer**. It works on any agent trace (JSONL, JSON, CSV, or a folder of linked files), not only the Swarm Traces release.

## Quick start

Python 3.9+ standard library only, no installs.

```bash
# run the app on 127.0.0.1:8010, then upload a trace file or folder in the browser
python3 -m agenttrace serve

# or preload a dataset (the pack is picked from the data unless you name one)
python3 -m agenttrace serve --input redacted.jsonl
python3 -m agenttrace serve --input full-wiki-logs --pack wiki_swarm.json

# every number and figure in the report: baselines, robustness, counting rules, timing check
python3 -m agenttrace evaluate redacted_columns.csv --pack code_traces.json --out reports/evaluation
python3 -m agenttrace evaluate full-wiki-logs --pack wiki_swarm.json --out reports/evaluation-wiki
python3 paper/build.py --author "Name" --affiliation "Affiliation"   # the report PDF (needs Google Chrome)

# tests
python3 -m unittest discover -s agenttrace/tests -t .
```

The app has three panes:
- **Left:** the analysis. Overview, who talked to whom (a sender-receiver graph; click an arrow for the whole conversation with every record id), timeline, places, spread, early flag, every event, and what is missing. Every list can be shown in full and filtered.
- **Right top:** a trace of any selected event.
- **Right bottom:** an AI investigator that uses any OpenAI-compatible endpoint. The default is OpenCode Go with `deepseek-v4.1-flash`: paste your key under Settings and press **Check connection**. On OpenCode Go, DeepSeek models also need **Global** selected under Settings > Privacy > Regions in the OpenCode console. The app sends the session header Go requires, and explains provider errors in plain words.

**Any trace.** With the `auto` pack (the default) the tool picks a pack from the data's shape and says why on the overview. The generic pack also finds shared keys on its own: a token used in a quarter or more of all runs, in a trace with 20 or more tokens, is treated as shared rather than as one agent.

See [`agenttrace/README.md`](agenttrace/README.md) for the full guide: formats, packs, labeling and precision, and the command-line reports.

## Data

The datasets are not in this repository.
- **Swarm Traces release:** https://swarmtraces.org/ (redacted dataset download on that page). Convert it to CSV or use the JSONL directly.
- **Wiki logs** (`full-wiki-logs/`): from collusion.wiki.

## What is here

| Folder | What it is |
|---|---|
| `agenttrace/` | The tool and the Swarm Tracer app: loader, analysis, time and identity reconstruction, message flow, conversations, claims checking, labeling, AI investigator, tests |
| `reports/findings/` | A written summary of what the swarm did, with record ids |
| `docs/tool-study.md` | Notes on existing trace viewers and what they lack for swarm forensics |
| `paper/` | The hackathon report source and its build script (tables and figures filled from `agenttrace evaluate`) |

Earlier prototypes (`analyzer/`, `forensics/`) were replaced by `agenttrace` and removed; they remain in the git history.

## How a message is counted

A message is a read of a place after a different actor wrote to it. Three rules keep the count honest:
- **Each write counts once per reader.** Polling a mailbox or re-linking the same page is one message, not many. In the Swarm Traces release this turns 377 reads between named tokens into 166 distinct messages across 95 sender-receiver pairs.
- **Overwrites are not messages.** A wiki edit sends the whole page, so an agent can replace another's edit without ever seeing it. An edit that keeps none of the lines the previous editor added is counted as an overwrite instead. In the wiki logs this removes 4,587 edits. The largest overwrite pair is LinkHelper771 and AgentMassPointer13, about 85 times each way.
- **Every message says what it rests on:** read in code, named the place, posted after it, or kept N of M lines. "Named the place" shows the place was known, not that it was read.

## Hackathon work and dual use

- **Hackathon work.** All code and writing here were done during the hackathon weekend (November 7–8, 2026); none of it predates the hackathon. The datasets are third-party releases.
- **What it helps with.** The tool is for defenders and investigators reconstructing an incident after the fact. It reads logs; it does not generate attacks, and it contains no exploit code, credentials or trace data.
- **What it could help an attacker with.** The limits below double as a list of what this kind of forensics cannot see: activity with no shared place, places the pack does not describe, and identities that change often. An agent swarm aware of them could stay below these signals. We describe the gaps at the level of the public incident reports, and we do not test evasion.

## Limits to keep in mind

- A token or self-chosen label is not an agent. One agent can hold many tokens or names, and a shared key stands for many agents.
- Times are estimated from timestamps written in the agents' own code where no time field exists. Only blocks that pass a rank-correlation and error check are dated.
- Tags and intents are pattern matches. Precision is measured on small, single-labeler samples.
- A read or write in code is an attempt; the data rarely shows whether it worked.
- Overwrites are told apart from reads by lines kept. Two editors who independently write the same line would look like one reading the other.

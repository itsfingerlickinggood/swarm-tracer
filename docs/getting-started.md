# Getting started

[Home](./) · [User guide](user-guide.md) · [Formats](formats.md) · [How it works](how-it-works.md)

Swarm Tracer runs on your machine with Python 3.9 or newer and nothing else. Your data stays local; only the optional AI investigator sends anything out, and only to the provider you choose.

## Install

With [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/itsfingerlickinggood/swarm-tracer
swarm-tracer serve
```

Or from a clone, with no install at all:

```bash
git clone https://github.com/itsfingerlickinggood/swarm-tracer
cd swarm-tracer
python3 -m agenttrace serve
```

Open <http://127.0.0.1:8010>. (`swarm-tracer …` and `python3 -m agenttrace …` are the same command.)

## Try it on the demo swarm

```bash
swarm-tracer demo
```

This serves a small simulated swarm that ships with the tool. Because it is simulated, the true answers (who really talked to whom, which tokens belong to one agent) are known, so you can see what the tool gets right and wrong:

```bash
python3 -m agenttrace.groundtruth score agenttrace/samples/demo_swarm
```

## Load your own swarm

Press **Load data** in the top bar and choose a file or a whole folder. Swarm Tracer reads:

- JSONL, JSON, CSV/TSV and plain-text logs (one record per line);
- folders of linked files (for example a wiki's revisions and events);
- the trace formats of common agent frameworks: OpenTelemetry GenAI spans, LangSmith, Langfuse, AutoGen, CrewAI, the OpenAI Agents SDK and MCP tool calls.

Leave **Pack** on *auto*: the tool picks a pack from the data and says why on the Overview. If your swarm needs its own rules, press **Build a pack from a sample…** (see [Packs](packs.md)). You can also preload a file:

```bash
swarm-tracer serve --input my-swarm.jsonl
swarm-tracer serve --input logs/ --pack wiki_swarm.json
```

Large files are cached after the first analysis, so they open in seconds the next time.

## A first investigation

1. **Overview.** Read the short answers to the four questions, and the chart of the whole incident. If the dataset matches a known incident, the incident brief from the public reports is shown beside it.
2. **Who talked to whom.** Hover the biggest dots, then click an arrow to read the whole conversation between two agents, with every record id.
3. **Early flag.** Press Play and watch the warning signs fire. Change the alert rule and see how much harm would still have been ahead.
4. **Agents.** Check which tokens are probably one agent, and accept or reject each proposal.
5. **Inspector.** Click any record id. "Why the tool reads it this way" highlights the code that set each reading.
6. **Case file.** Pin what matters, add notes, and export the dossier.
7. **What's missing.** Before concluding, read what the data cannot show.

Every underlined word has a definition: hover it, or open **Glossary** in the top bar.

## The AI investigator (optional)

Open **Settings** in the bottom-right pane, choose a provider preset (OpenCode Go, OpenAI, or a local Ollama model, which needs no key), and press **Check connection**. See [AI investigator](ai-investigator.md).

## Reproduce the hackathon report

```bash
python3 -m agenttrace evaluate redacted_columns.csv --pack code_traces.json --out reports/evaluation
python3 -m agenttrace evaluate full-wiki-logs --pack wiki_swarm.json --out reports/evaluation-wiki
python3 paper/build.py --author "Name" --affiliation "Affiliation"
```

The datasets are not in the repository: get the Swarm Traces release from <https://swarmtraces.org/> and the wiki logs from <https://collusion.wiki/>.

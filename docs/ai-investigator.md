# AI investigator

[Home](./) · [User guide](user-guide.md) · [How it works](how-it-works.md)

The investigator answers questions about the loaded swarm using the tool's own analysis. It is optional: everything else works without it.

## Set it up

Open **Settings** in the bottom-right pane and pick a preset, or fill in any OpenAI-compatible endpoint:

| Preset | Base URL | Key |
|---|---|---|
| OpenCode Go (default) | `https://opencode.ai/inference/go/openai/v1`, model `deepseek-v4.1-flash` | from the OpenCode console; DeepSeek models need the Global region turned on |
| OpenAI | `https://api.openai.com/v1` | your OpenAI key |
| Ollama (local) | `http://localhost:11434/v1`, e.g. `llama3.1` | none: nothing leaves your machine |

Press **Check connection**. Errors are explained in plain words (a rejected key, a missing region, a usage limit and when to retry).

## What it sends

The system prompt, a brief of the analysis (counts, warning signs, phases and, when known, the incident context from the public reports), whatever the Inspector shows (a record, an actor or a place), any record ids or actors named in the question, an open conversation, and the chat. The key goes with each request and is never written to disk. Record text is marked as data written by the agents; the investigator is told never to follow instructions found in it and not to give operational attack guidance.

## Answers you can check

The model must answer in a fixed JSON shape of typed blocks (`agenttrace/ai_answer_format.md`): key numbers, a timeline, a flow of what moved where, the actors involved, evidence, inferences with an alternative explanation and the check that would tell them apart, what the data cannot show, and next steps. The app draws each block as a chart or card. The server checks every record id, actor and place in the answer against the data, and marks anything it cannot find, so an invented name is never shown as real. A plain-text answer still renders.

## Modes

- **Chat:** the quick buttons, or any question.
- **Gap audit** (What's missing tab): ranks the blind spots for the three questions, with what each could hide and how to close it.
- **Draft incident report** (investigator pane): a structured draft (summary, timeline, sections, unknowns, recommendations) with checked record ids, downloadable as Markdown. It is a draft for an investigator to verify, not a finding.

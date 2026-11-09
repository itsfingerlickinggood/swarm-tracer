# How it works

[Home](./) · [User guide](user-guide.md) · [Formats](formats.md) · [Packs](packs.md) · [Limits](limitations.md)

Swarm Tracer runs one pipeline on any trace. Each stage records what it found and how sure it is, so every number in the app can be traced back to records.

## 1. Load

Files are read field by field: ids, text, kind, parent, actor, time, tool and channel are found by name across common layouts, or given by hand. Framework traces (OpenTelemetry GenAI, LangSmith, Langfuse, AutoGen, CrewAI, OpenAI Agents SDK, MCP) are recognised by shape and mapped to the same fields. The Overview's read report says what was found in each file.

## 2. Date

A record's own time field is used when present. Otherwise, where the pack allows it, the unix timestamps agents wrote into their own code are fitted to file order with a monotone (isotonic) fit, one block of same-kind records at a time. A block is dated only if it has enough timestamps, they rise with file order (Spearman ρ), and the 90th-percentile fit error stays under 6 hours. Children inherit a parent's time. Estimated times carry a likely range from their block's fit error.

## 3. Identify

An actor field is used when present. Otherwise the identity is the token a record authenticates with (including a token stored in a variable and used later), else a self-chosen name the pack lists, else the token of its thread, else the record's own run ("anonymous run"). A token every agent shares, such as an evaluation key, is never an actor; the generic pack finds such keys automatically. **A token is not an agent**: the Agents tab proposes which identities are probably one agent, from counted evidence, with a confidence.

## 4. Places

A place is anywhere one actor can leave something for another: a dataset, a board folder, a webhook, a command file, a wiki page, a thread. Each mention of a place in code is judged a write if write code (an upload, a commit, a POST, a folder creation) is within 160 characters before or 260 after it, otherwise a read.

## 5. Messages

A message is a read of a place after an earlier write to it by a different actor, linked to the latest such write. Three rules keep the count honest:

1. a reader running the same program as the writer (the same first 60 normalized words) is one sender retrying, not a message;
2. each write counts once per reader;
3. where every post replaces a whole page, an edit that keeps none of the lines the earlier editor added is an **overwrite**, not a message.

Messages agents logged to each other (handoffs, `to`/`recipient` fields) count directly, as the strongest evidence. Every message says what it rests on: logged directly, read in code, named the place, posted after it, or kept N of M lines. Places the redaction reduced to an owner's name may join several repositories; messages on them are flagged.

## 6. Spread

A program is identical code once ids, numbers and hashes are masked. A program run by two or more named actors spreads; the first run is its source. Reuse is a warning sign only when the program writes to a place, reads a place another actor wrote, or does something the pack calls harmful; the rest (a token check every agent runs, two agents fetching the same public file) is listed as routine. A token first seen as data inside a record and only later used to authenticate also spreads, as does a record that authenticates as one identity while holding another's token.

## 7. Warning signs and the replay

The replay finds the first time each sign fires: the first harmful action of each kind (single actor); the first message between named actors, the first program reused, a group of 3, 5, 10, 20 actors linked by messages, the first two-way exchange, a carried token, a shared name (actors together); and a volume alarm (mean plus three standard deviations of every earlier hour) as the baseline. For each it reports the share of dated harmful actions still to come. Harm is whatever the pack lists as harmful.

## 8. Checks

`agenttrace evaluate` recomputes every sign under random time errors as large as the dating fit's own, compares the counting rules, and checks the estimated times against times the investigators published. The ground-truth mode scores message links on a simulated swarm whose true links are known.

The full method and results for the Hugging Face incident are in the [report](assets/Swarm_Tracer_report.pdf).

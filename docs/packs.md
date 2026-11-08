# Packs

[Home](./) · [Formats](formats.md) · [How it works](how-it-works.md)

A pack is a small JSON file that adapts Swarm Tracer to a kind of swarm. It says which records are actions, and which patterns mark identities, places, intents and harm. Nothing in the tool is hard-coded to one dataset: everything specific lives in a pack.

With **Pack: auto** (the default) the tool picks a pack from the data's shape and says why on the Overview. The built-in packs:

| Pack | For |
|---|---|
| `generic.json` | any trace; finds shared keys on its own |
| `code_traces.json` | code agents ran, with redacted credentials and hosts (the Swarm Traces release) |
| `wiki_swarm.json` | agents editing shared wiki pages (the collusion.wiki logs) |
| `chat.json` | chat transcripts with roles |

## Build one from a sample

In **Load data**, press **Build a pack from a sample…** and choose a sample file. The tool proposes columns, identity-token patterns, places, intents and which record kinds are actions, each with counts and examples. Tick what fits, name the pack, and save: it appears in the pack list.

## What a pack can say

All fields are optional; the tool skips what a pack does not define. Patterns are Python regular expressions.

| Field | Meaning |
|---|---|
| `name`, `description` | shown in the pack list |
| `action_kinds` | record kinds that are actions an agent ran (others are where information is seen) |
| `behaviors` | `[{name, stage, pattern, flags, description, context}]` tags; `context: true` tags are shown but never counted as evidence |
| `intents` | `[{name, pattern}]` what an action tries to do; the first match wins |
| `intent_descriptions` | plain words for each intent |
| `harm` | intents or tags counted as harmful in the replay |
| `identity_patterns` | `[{role, pattern}]` group 1 is an identity token, used when there is no actor field |
| `variable_identity` | `{assign, use}` a token stored in a variable and used later |
| `shared_identities` | tokens many agents share; never counted as actors |
| `auto_shared_identities` | find such keys automatically |
| `handles`, `handle_families` | self-chosen names, and how to group them |
| `info_patterns` | `[{family, pattern}]` items that can move between agents (tokens, keys, URLs) |
| `channels` | `[{name, pattern, write}]` places: group 1 is the place's name; `write` is the code that makes a mention a write |
| `coarse_channels` | places a redaction may have merged |
| `structural_channels`, `mention_channels` | use a record's own page/thread as a place; treat naming another page as reading it |
| `full_body_posts` | every post replaces the whole place (wiki edits): enables the overwrite rule |
| `write_only_kinds` | kinds that change a place without reading it (a moderator's delete) |
| `shared_names` | `[{family, pattern}]` names other runs can reuse |
| `time` | `{embedded_epoch, window, min_points, min_spearman}` estimate times from timestamps in the text |
| `actor_note` | a caveat shown with actor counts |

Look at `agenttrace/packs/code_traces.json` and `wiki_swarm.json` for complete examples. Put a new pack in `agenttrace/packs/` (or pass a path with `--pack`).

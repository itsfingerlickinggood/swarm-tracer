# Limits and dual use

[Home](./) · [How it works](how-it-works.md)

## What an investigator would still miss

The **What's missing** tab measures these for each dataset. In general:

- **Time.** Records with no time field and no usable embedded timestamps cannot be placed. Estimated times are a fit, so flat stretches in hourly charts can come from the fit rather than from steady activity.
- **Who is an agent.** Actors are tokens and self-chosen names. One agent can hold several; a shared key stands for many. The Agents tab proposes merges with evidence, but the true mapping needs the operator's logs.
- **Whether a message was read.** A read in code is an attempt; the data rarely shows whether it worked. Messages that rest only on naming a place show the place was known, not that its content was read.
- **Merged places.** Redaction that keeps only an owner's name can join several repositories.
- **Unlisted channels.** Messages through places no pack describes, or with no shared place at all, are invisible. Much coordination is never written down.
- **Identity merges.** On simulated swarms with known agents, merge proposals resting only on coordination evidence (shared places, handoffs, shared programs) were almost always wrong (about 1% right), so the tool now keeps those at low confidence; high and medium need direct evidence and were right in every simulated case. See [validation](validation.md).
- **Patterns.** Intents and tags are pattern matches. Label records in the Inspector to measure their precision on your data.
- **Hindsight.** The warning signs and the harm list were written knowing how one incident unfolded. On simulated benign swarms (no coordination) some signs still fire, mainly the pack counting every dataset commit as harm and one agent's two tokens looking like two actors (program reuse from shared boilerplate did, until it was fixed): see [How accurate is the tool?](validation.md). Simulated swarms are ours, so these are estimates, not field false-positive rates.

## Dual use

The tool is for defenders and investigators reconstructing an incident, and for builders of monitors deciding which agents' activity to read together. Its limits are also a list of what this kind of forensics cannot see: a swarm that avoided shared places, rotated identities often, or used channels no pack describes would leave fewer signals. We describe these gaps only at the level of the public incident reports, and the project contains no exploit code, credentials or trace data. It reads logs; it does not act on any system.

## Data handling

Uploaded files stay on the machine running the app. Nothing is sent anywhere unless the AI investigator is configured, and then only to the provider chosen. The tool never tries to de-anonymize redacted placeholders.

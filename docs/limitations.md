# Limits and dual use

[Home](./) · [How it works](how-it-works.md)

## What an investigator would still miss

The **What's missing** tab measures these for each dataset. In general:

- **Time.** Records with no time field and no usable embedded timestamps cannot be placed. Estimated times are a fit, so flat stretches in hourly charts can come from the fit rather than from steady activity.
- **Who is an agent.** Actors are tokens and self-chosen names. One agent can hold several; a shared key stands for many. The Agents tab proposes merges with evidence, but the true mapping needs the operator's logs.
- **Whether a message was read, or used.** A read in code is an attempt; the data rarely shows whether it worked. A delivery is a write then a later read of the same place; it does not show the reader used what was written (0 of 11 on the Swarm Traces release do), and one that rests only on naming a place shows the place was known, not that its content was read.
- **One labeller.** The audit labels behind the delivery count are one reader's, the authors' AI assistant; no second labeller has read them, and none was read by a person by hand.
- **Simulated accuracy is optimistic.** An independently written generator gives message precision 70% and recall 58%, against 90% and 84% on the original simulator; see [validation](validation.md).
- **On real data, pairs yes, single messages no.** Measured against the recipients that two public datasets log, with the recipients withheld, the tool finds most pairs of agents that talked (91 of 92 on Who&When, 80.1% on MAST-Data) but under 10% of the single messages, and it reports many pairs the logs do not address. On a social network of agents 26.5% of its inferred reply links are logged replies. Those datasets are turn-taking teams and comment threads, not a swarm that hides its contact.
- **Who failed, or who colluded.** The tool has no failure-attribution feature, and reading its flags as blame is at chance (29.3% against 29.1% on Who&When). On the SALT collusion episodes its Alert rule fires on colluding and non-colluding runs alike.
- **Merged places.** Redaction that keeps only an owner's name can join several repositories.
- **Unlisted channels.** Messages through places no pack describes, or with no shared place at all, are invisible. Much coordination is never written down.
- **Identity merges.** On simulated swarms with known agents, merge proposals resting only on coordination evidence (shared places, handoffs, shared programs) were almost always wrong (about 1% right), so the tool now keeps those at low confidence; high and medium need direct evidence and were right in every simulated case. See [validation](validation.md).
- **Patterns.** Intents and tags are pattern matches. Label records in the Inspector to measure their precision on your data.
- **The alarms are not a detector.** The warning signs, the harm list and the choice of the four main alarms were all made knowing how one incident unfolded. The pre-registered forward test of the four alarms failed: none is shown to fire before the first true harm on simulated swarms. On real traces with no recorded attack the Alert rule fires on 95% to 100% of runs, and on the only real traffic with times that we could read (38 Moltbook community traces) the three time-based main alarms each fired in 37. See [early warning](early-warning.md).
- **Hindsight.** On simulated benign swarms (no coordination) some signs still fire, mainly the pack counting every dataset commit as harm and one agent's two tokens looking like two actors (program reuse from shared boilerplate did, until it was fixed): see [How accurate is the tool?](validation.md). Simulated swarms are ours, so these are estimates, not field false-positive rates.
- **No real agents under test.** The [agent harness](harness.md) has been run only with a scripted stand-in for the model.

## Dual use

The tool is for defenders and investigators reconstructing an incident, and for builders of monitors deciding which agents' activity to read together. Its limits are also a list of what this kind of forensics cannot see: a swarm that avoided shared places, rotated identities often, or used channels no pack describes would leave fewer signals. We describe these gaps only at the level of the public incident reports, and the project contains no exploit code, credentials or trace data. It reads logs; it does not act on any system.

## Data handling

Uploaded files stay on the machine running the app. Nothing is sent anywhere unless the AI investigator is configured, and then only to the provider chosen. The tool never tries to de-anonymize redacted placeholders.

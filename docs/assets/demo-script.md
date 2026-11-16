# Swarm Tracer demo video: narration script

Video: `docs/assets/demo.mp4` (about 5 min 11 s, 1440x900, narrated by macOS `say`, voice Samantha, 175 wpm). Each segment shows the listed screens; frames within a segment share its time evenly.

**Status (v2.2.0): the recorded video was re-recorded from this corrected script on 16 November 2026.** It says 9 write-then-read deliveries, not 23, and one reader's labels, not a hand audit. The earlier +5.8 h lead is not in the script (withdrawn).

## 1. The problem

Screens: `#tab=overview`

In July 2026, a swarm of AI agents coordinated in a way nobody saw coming. The Swarm Traces release gives us the logs: 189,579 records from that incident. But logs alone don't answer an investigator's real questions. Who talked to whom? How did information spread? Could anyone have flagged it early? And what would an investigator still miss?

## 2. The tool

Screens: `#tab=overview&scroll=760&rec=R0006587`

Swarm Tracer is our answer. It is a forensics tool for AI agent swarms. Point it at any agent trace, in JSON, CSV, a folder of logs, or common framework formats, and it rebuilds the story: contact between agents through shared places, what spread, when the warning signs fired, and which identities might be the same agent. It runs on the Python standard library alone, in your browser.

## 3. Overview and Inspector

Screens: `#tab=overview`, `#tab=overview&scroll=760&rec=R0006587`

The overview gives short, measured answers to each question in the challenge, straight from the records. Click any record and the Inspector explains it in plain words: what it does, its role in the swarm, and how much harm was still to come. Many records have no reliable time, so Swarm Tracer estimates one, with a likely range. Fifty-nine percent of payloads get an estimated time, against three percent before. And seven key moments land within two point two hours of the times METR and Hugging Face later reported.

## 4. Who talked to whom

Screens: `#tab=network&scroll=470`, `#tab=timeline&order=messages&rows=messages&scroll=560`

Next, who talked to whom. Polling a mailbox a hundred times is still one delivery, so each write counts once per reader. A delivery is a write to a shared place and a later read of it by another identity; it does not show the reader used what was written, so we do not call it a message. That leaves 9 deliveries in all, four of them between seven named tokens, in four sender-receiver pairs. Two of those four are between tokens that Swarm Tracer estimates belong to one agent. A first count said 166, then 19, then 23. The records were read by the authors' AI assistant, not by a person by hand, and one reviewer would defend only about five of the 23. All nine passed through Hugging Face datasets, none through a board folder. The graph shows the whole network, and the swimlanes show each conversation in time order, with its record ids.

## 5. Early-flag replay

Screens: `#tab=early&hour=2026-07-10T06&scroll=330`, `#tab=early&hour=2026-07-10T18&scroll=330`, `#tab=early&hour=2026-07-11T06&scroll=330`, `#tab=early&hour=2026-07-11T18&scroll=330`, `#tab=early&hour=2026-07-12T06&scroll=330`, `#tab=early&hour=2026-07-12T18&scroll=330`, `#tab=early&hour=2026-07-13T12&scroll=330`

Could it have been flagged early? The replay steps through the incident hour by hour, from July tenth to July thirteenth, and shows every warning sign as it fires, beside the share of harm still to come. Counting by token, signs of shared control fire when fifty to fifty-seven percent of the harm is still ahead; counting by estimated agent, thirty-eight and five percent. Simple baselines fire earlier: a volume alarm at eighty-three percent, and a first new host, a distinct-actor alarm and a first secrets search at eighty-seven to ninety-three. The first dataset write fires at ninety. So the shared-control signs come late, and they are not an early warning on this incident. The alert rules are editable, and live mode watches a growing trace.

## 6. Agents and identity

Screens: `#tab=agents&actor=%5BCREDENTIAL%20169%5D`

The Agents tab starts from one rule: a token is not an agent. One agent can hold many credentials, and one credential can be passed around. Swarm Tracer proposes which identities may be the same agent, with the evidence and a confidence level, and it suggests roles.

## 7. Forensics

Screens: `#tab=forensics&fx=trace&q=cred%20169`, `#tab=forensics&fx=stages`, `#tab=forensics&fx=credentials`

The Forensics tab is where an investigator digs in. Trace any string through the swarm. Here we trace credential 169. It first appears nine minutes after the time METR reported. The stage ladder lays out the incident step by step, and credential lifecycles show when each token was created, used, and passed on. There are also dead-drop ledgers, program diffs, and exports for security teams, including STIX and Timesketch.

## 8. Measured accuracy

Screens: `#tab=forensics&fx=validation`

How far can you trust it? We scored the tool on sixty simulated swarms with known answers, including benign ones. Median precision of the write-then-read links is ninety percent, and recall eighty-four percent. Treat that as optimistic: a generator written independently gives seventy percent and fifty-eight percent, and fewer with sparse timestamps. Measuring also caught real mistakes. Places named only in code comments had been counted as reads, and shared boilerplate code fired the program-reuse sign on every benign swarm; both are fixed. Our first identity rule labelled pairs high confidence on coordination evidence alone, and only ten of two hundred forty were right. We changed the rule to require direct evidence. After the change, twelve of twelve high-confidence merges were right, though those twelve are only about three percent of the true pairs.

## 9. What's missing

Screens: `#tab=gaps`

And what would an investigator still miss? The What's missing tab measures each blind spot and says which question it limits. Most actions have no named actor, many records have no parent link or no time, and contact through shared places is inferred, not logged. Each gap comes with what it hides, and the data that would close it. Knowing the blind spots is part of the evidence.

## 10. Try it

Screens: the website (`docs/index.html`)

Try it yourself. Install with pipx from our GitHub repository, then run swarm tracer demo to explore a simulated swarm with known answers, or serve your own trace. The website has the documentation, the report, and the slides. Swarm Tracer: forensics for AI agent swarms.

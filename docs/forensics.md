# Forensics

[Home](./) · [User guide](user-guide.md) · [How it works](how-it-works.md) · [How accurate is it?](validation.md)

The **Forensics** tab holds the deeper analyses, grouped in a side menu. Every section works on any trace; each one says what its numbers rest on. Open any section by link: `#tab=forensics&fx=<id>`.

## Follow the evidence

| Section (`fx=`) | What it answers |
|---|---|
| **Trace anything** (`trace`, `&q=…`) | Type any string (a token, a URL, a host, a line of code, or `/regex/`) and see every record that carried it: its first appearance, who held it in which order, the places it touched, and each "hop" from one actor to the next with the gap between them. A hop links each actor's first contact to the latest earlier holder; it is not a proven hand-off. |
| **Credential lifecycle** (`credentials`) | One row per identity token: first seen as data, first use, who used it, last use, places it opened, whether another identity carried it, and how long it has been quiet; plus an exposure matrix of tokens by kind of place. |
| **Command and control** (`c2`) | For command files, boards and any place with two or more readers: who wrote, who polled, and what each reader did in the hour before and after picking up a write. Timing only, not cause. |
| **Dead-drop ledger** (`drops`) | Every place one actor wrote: who picked it up and after how long, which drops nobody collected, and which many did. Exportable as CSV. |
| **Search** (`search`, `&q=…`) | AND / OR / NOT, quotes, parentheses and `/regex/` over record text with the usual filters; saved searches; "records like this" (same masked program, same start of code, shared places or tokens). |

## How agents behaved

| Section | What it answers |
|---|---|
| **Program evolution** (`evolution`) | Near-duplicate code grouped into versions (MinHash over masked text, similarity ≥ 0.8), each version linked to its closest earlier one, with a line diff and who introduced and adopted it. Answers "who improved the attack, and did others take it up?" |
| **Stage ladder** (`stages`) | Actions mapped to stages (reconnaissance, credential access, execution, persistence, exfiltration, cover-up) from the pack, the swarm's first arrival at each stage, and each top actor's climb. |
| **Lead–lag** (`leadlag`) | For active pairs, whether one actor's activity tends to come before the other's, from hour-by-hour changes at shifts of up to six hours. Correlation, not causation. |
| **Anomaly timeline** (`anomalies`) | For each actor, hours that break its own pattern: bursts, a first new place, a first new intent, the first harmful action, the first message. |
| **Story** (`story`) | A chronology written from the data alone, sentence by sentence with record ids, for the swarm and its busiest actors; downloadable as Markdown. |

## Test and export

| Section | What it answers |
|---|---|
| **What-if** (`whatif`) | Apply your decisions (identities you merged, messages or signs you rejected) and see every count and warning sign "as counted" and "after your decisions", side by side. |
| **Reference comparison** (`reference`) | Measure the loaded swarm against a reference (a benign simulated swarm by default, or any library dataset) and flag what deviates. |
| **Chain of custody** (`custody`) | SHA-256 of every input file (checked against a shipped `SHA256SUMS` when present), a hash of the record ids, the pack and its hash, the tool version and load time. Every export carries this block. |
| **Exports** (`exports`) | Timeline CSV, a Timesketch-compatible CSV, a STIX 2.1 bundle (tokens as pseudonymous identities, places as indicators, signs as sightings with kill-chain stages) and the alert rules as detections. |
| **How accurate is the tool?** (`validation`) | The scores from simulated swarms with known answers: see [validation](validation.md). |

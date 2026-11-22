# Moltbook: who talked to whom, and alarms on real agent traffic

Generated 2026-11-22T10:15:54Z by `python3 -m agenttrace.external_eval moltbook` (Swarm Tracer 2.3.0). Every number here is in `results.json`; one row per community is in `communities.csv`.

**Data.** Gautam and Riegler, "Moltbook Observatory Archive", Hugging Face Datasets, 2026, huggingface.co/datasets/SimulaMet/moltbook-observatory-archive (MIT). Real posts and comments by AI agents on Moltbook, collected by passive polling. Fetched: data/posts and data/comments for 2026-02-13 to 2026-02-19 (7 daily files each); no agents table (74.7 MB of 5.38 GB, revision `33c69984a481`).

**Slice.** The week 2026-02-13 to 2026-02-19 holds 251,564 posts and 46,236 comments in 891 communities. Scored: the 40 communities with the most comments (made in the week, on posts made in the week); ties by name; 40 communities, 187,738 records (144,171 posts, 43,567 comments) by 19,879 agents, each community one trace. 1,217 comments of the week answer posts made before it and are left out.

**Privacy.** Agent names are not in these reports (counts only). The agents table, which holds the X handles of the agents' owners, was not downloaded.

## Short answer

- **Reading the log:** all 41,737 logged replies come out as logged direct messages (41,737 reported; they match in 40 of 40 communities).
- **Inferring it:** without the reply fields, the write-then-read rule finds the answered record for 25.7% of the logged replies, and 26.5% of its links are logged replies. By pair of agents: recall 31.3%, precision 30.3%.
- **It is right about the first comment and wrong after it.** First comment in a thread: precision 96.9%. Later comments: 1.0%. Most comments answer the post, and the rule links each to the comment just before it.
- **Alert rule (2 kinds of coordination)** fired on 40 of 40 communities = 100.0% (91.2 to 100.0), a median 2.2 h into the week.
- **Watch rule (first harmful sign)** fired on 37 of 40 communities = 92.5% (80.1 to 97.4), a median 12.3 h into the week.
- **Volume baseline rule** fired on 39 of 40 communities = 97.5% (87.1 to 99.6), a median 26.0 h into the week.

## 1. The reader

Format detected: Moltbook Observatory posts and comments. Packs picked by the tool: generic agent traces (40). A comment is addressed to the author of its parent. 1,830 comments answer their own author and 0 have a parent outside the file; neither is a message. With the reader, every logged reply is a logged direct message: that is reading, not inference.

## 2. Inference against the logged replies

Rule: write then read: a record in a thread is linked to the latest earlier record there by another agent ('posted after it'); the reply fields are not used for this. Truth: the comment's parent (parent_id, else the post) when its author is another agent and it is in the file. The tool inferred 40,520 deliveries in threads, 40,486 of them read by a comment.

| | Precision: links that are logged replies | Recall: logged replies found |
|---|---|---|
| By record (this comment answers that record) | 10,720 of 40,486 = 26.5% (25.2 to 36.9) | 10,720 of 41,737 = 25.7% (24.6 to 35.0) |
| By pair of agents (A answered B at least once) | 11,574 of 38,129 = 30.3% (29.0 to 42.0) | 11,574 of 36,930 = 31.3% (29.9 to 44.2) |
| By record, first comment in its thread | 10,433 of 10,768 = 96.9% (96.0 to 97.4) | 10,433 of 10,909 = 95.6% (91.2 to 96.3) |
| By record, later comments | 287 of 29,718 = 1.0% (0.8 to 2.5) | 287 of 30,828 = 0.9% (0.8 to 2.3) |

Intervals: 95% of 1,000 resamples of whole communities. Median community: precision 39.5%, recall 36.7% by record. A logged reply says whom a comment answers, not everything its author read. A link the log does not confirm may still be a real read; it is not shown to be one.

Written-content test on the same links: 3,851 of 40,486 pass; 2,142 of the 3,851 are logged replies, against 10,720 logged replies among all 40,486.

## 3. Alarms on traffic with no recorded incident

No incident is recorded for this week in the archive's card. The traffic includes token-minting spam and promotion; nobody labelled it. 'False alarm' means an alarm on traffic with no known incident. Each community is one trace of about 165.5 hours.

| Rule, alarm or sign | Communities where it fired (of 40) | Median hours into the week |
|---|---|---|
| Alert rule (2 kinds of coordination) | 40 = 100.0% (91.2 to 100.0) | 2.2 |
| Volume baseline rule | 39 = 97.5% (87.1 to 99.6) | 26.0 |
| Watch rule (first harmful sign) | 37 = 92.5% (80.1 to 97.4) | 12.3 |
| alarm:actors:3 | 39 = 97.5% (87.1 to 99.6) | 26.0 |
| alarm:baseline:distinct_actors | 39 = 97.5% (87.1 to 99.6) | 26.0 |
| alarm:baseline:first_intent | 0 = 0.0% (0.0 to 8.8) | – |
| alarm:baseline:new_host_12h | 39 = 97.5% (87.1 to 99.6) | 17.94 |
| alarm:baseline:new_host_24h | 39 = 97.5% (87.1 to 99.6) | 31.2 |
| alarm:baseline:volume_12h | 38 = 95.0% (83.5 to 98.6) | 25.5 |
| alarm:baseline:volume_6h | 38 = 95.0% (83.5 to 98.6) | 20.5 |
| alarm:coord:1 | 40 = 100.0% (91.2 to 100.0) | 2.19 |
| alarm:coord:2 | 40 = 100.0% (91.2 to 100.0) | 2.2 |
| alarm:coord:3 | 40 = 100.0% (91.2 to 100.0) | 5.84 |
| alarm:coord:4 | 0 = 0.0% (0.0 to 8.8) | – |
| alarm:coord:5 | 0 = 0.0% (0.0 to 8.8) | – |
| alarm:group:10 | 37 = 92.5% (80.1 to 97.4) | 27.14 |
| alarm:group:20 | 34 = 85.0% (70.9 to 92.9) | 39.59 |
| alarm:group:3 | 40 = 100.0% (91.2 to 100.0) | 5.84 |
| alarm:group:5 | 39 = 97.5% (87.1 to 99.6) | 14.13 |
| alarm:message:1 | 40 = 100.0% (91.2 to 100.0) | 2.19 |
| alarm:newhost:12 | 39 = 97.5% (87.1 to 99.6) | 17.94 |
| alarm:newhost:24 | 39 = 97.5% (87.1 to 99.6) | 31.2 |
| alarm:place:1 | 0 = 0.0% (0.0 to 8.8) | – |
| alarm:secrets:1 | 0 = 0.0% (0.0 to 8.8) | – |
| alarm:volume6:3 | 38 = 95.0% (83.5 to 98.6) | 20.5 |
| alarm:volume:2 | 40 = 100.0% (91.2 to 100.0) | 19.0 |
| alarm:volume:3 | 38 = 95.0% (83.5 to 98.6) | 25.5 |
| alarm:volume:4 | 29 = 72.5% (57.2 to 83.9) | 34.0 |
| alarm:volume:5 | 22 = 55.0% (39.8 to 69.3) | 38.5 |
| alarm:watch:1 | 37 = 92.5% (80.1 to 97.4) | 12.3 |
| alarm:watch:2 | 30 = 75.0% (59.8 to 85.8) | 29.76 |
| alarm:watch:3 | 22 = 55.0% (39.8 to 69.3) | 67.85 |
| sign:first: deletes | 30 = 75.0% (59.8 to 85.8) | 23.73 |
| sign:first: handles_secrets | 33 = 82.5% (68.0 to 91.2) | 17.2 |
| sign:first: runs_shell | 12 = 30.0% (18.1 to 45.4) | 40.78 |
| sign:first: sends_data | 22 = 55.0% (39.8 to 69.3) | 33.58 |
| sign:group10 | 37 = 92.5% (80.1 to 97.4) | 27.14 |
| sign:group20 | 34 = 85.0% (70.9 to 92.9) | 39.59 |
| sign:group3 | 40 = 100.0% (91.2 to 100.0) | 5.84 |
| sign:group5 | 39 = 97.5% (87.1 to 99.6) | 14.13 |
| sign:message | 40 = 100.0% (91.2 to 100.0) | 2.19 |
| sign:rate_all | 38 = 95.0% (83.5 to 98.6) | 25.5 |
| sign:rate_harm | 7 = 17.5% (8.8 to 31.9) | 45.0 |
| sign:two_way | 40 = 100.0% (91.2 to 100.0) | 2.2 |

Intervals: Wilson 95% over communities. Flags are named as `agenttrace.earlywarn.extract` returns them (`alarm:<family>:<threshold>`).

`earlywarn.false_alarms` on the same 40 traces (269.33 trace-days): alarms per 24 h, each sign or rule counted once per trace.

| Kind | Id | Traces | Per 24 h (95%) |
|---|---|---|---|
| baseline | new_host_12h | 39 | 0.145 (0.103 to 0.198) |
| baseline | first_intent | 0 | 0.0 (0.0 to 0.014) |
| baseline | distinct_actors | 39 | 0.145 (0.103 to 0.198) |
| baseline | volume_6h | 38 | 0.141 (0.1 to 0.194) |
| baseline | new_host_24h | 39 | 0.145 (0.103 to 0.198) |
| baseline | volume_12h | 38 | 0.141 (0.1 to 0.194) |
| rule | alert-coord2 | 40 | 0.149 (0.106 to 0.202) |
| rule | baseline-volume | 39 | 0.145 (0.103 to 0.198) |
| rule | watch-harm | 37 | 0.137 (0.097 to 0.189) |
| sign | group3 | 40 | 0.149 (0.106 to 0.202) |
| sign | message | 40 | 0.149 (0.106 to 0.202) |
| sign | two_way | 40 | 0.149 (0.106 to 0.202) |
| sign | group5 | 39 | 0.145 (0.103 to 0.198) |
| sign | rate_all | 38 | 0.141 (0.1 to 0.194) |
| sign | group10 | 37 | 0.137 (0.097 to 0.189) |
| sign | group20 | 34 | 0.126 (0.087 to 0.176) |
| sign | first: handles_secrets | 33 | 0.123 (0.084 to 0.172) |
| sign | first: deletes | 30 | 0.111 (0.075 to 0.159) |
| sign | first: sends_data | 22 | 0.082 (0.051 to 0.124) |
| sign | first: runs_shell | 12 | 0.045 (0.023 to 0.078) |
| sign | rate_harm | 7 | 0.026 (0.01 to 0.054) |

## What this does and does not show

- On a social network, replying is the product. A rule that treats a message between two named agents as a sign of coordination fires within hours everywhere.
- The Watch rule here is the general pack's word lists. The records that matched, by word: 'secret' (1,376), 'delete' (711), 'upload' (370), 'password' (168), 'api_key' (68). A post that uses such a word is not shown to do harm.
- This is one week of one platform, chosen before any result. The archive's card says comment coverage is partial, so recall is against the replies that were collected.
- People can post through an agent. The data does not say which accounts are autonomous.

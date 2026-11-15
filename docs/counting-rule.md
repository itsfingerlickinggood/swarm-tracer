# The counting rule

[Home](./) · [How accurate is it?](validation.md) · [Known issues](known-issues.md)

Swarm Tracer's headline number is a count of **deliveries**: one actor wrote to a place, and a different actor
read that place afterwards. This page states the rule as numbered statements. Each has an id (R1, R2, ...) that
the tests cite. The rule is implemented in `agenttrace/messages.py`; a second, separately written
implementation is in `agenttrace/refcount.py`, and `python3 -m agenttrace.tools.crosscheck` compares the two.

Where a statement gives a number (a window size, a cap), the number is part of the rule as implemented, not
a claim that it is the right number. Statements marked *(heuristic)* describe how the main implementation
approximates the statement before them; the second implementation is free to reach the same end differently,
and where the two differ the crosscheck lists the record.

## Words

- **Record**: one row of the trace, with an id, a text, a kind, and possibly a time, an actor field, a
  channel field and a recipient field.
- **Pack**: the pattern file chosen for the trace (`agenttrace/packs/*.json`).
- **Place**: something actors can write to and read from (a dataset repository, a board folder, a wiki page).
- **Operation**: one (place, write | read | post, actor, time, record) item. A record has at most one
  operation per place.
- **Delivery**: one (write operation, read operation) pair that satisfies R22 to R29. "Message" in the app
  and the report means a delivery.

## Places

- **R1. A place is a pattern match.** Each channel in the pack has a name and a pattern with one capture
  group. A match with a non-empty group in a record's text is a *mention* of the place `name:group`. Two
  mentions are the same place only if both name and group text are equal.
- **R2. Only action records operate on places.** If the pack lists `action_kinds`, records of other kinds
  (replies, recovered copies) produce no operations.
- **R3. A mention in a comment is not counted.** A mention is in a comment when its line starts (after
  indentation) with `//`, `#`, `/*`, `* ` or `-- `, or when a `//`, `# ` or an unclosed `/*` preceded by
  whitespace or the start of the line comes before it on the same line. `https://` does not start a comment.
- **R4. Every other mention is judged on its own** as a *write*, a *read*, or *not counted* (R6 to R17). The
  code that decides is the call that uses the mention, never another place's call.
- **R5. One operation per record and place.** If any counted mention of the place in the record is a write,
  the operation is a write; otherwise, if any is a read, it is a read; otherwise the record has no operation
  on that place.

## Write, read, or not counted

A *request call* is a call that sends a request: `fetch(`, `.open(`, `new XMLHttpRequest`,
`requests.get|post|put|patch|delete|head(`, `curl`, `urlopen(`, `http.request`, `axios.`, `$.ajax`,
`navigator.sendBeacon`, a generated form. A *write verb* and a *read verb* are what the channel's `write`
and `read` patterns in the pack match (for a dataset: POST, PUT, PATCH, DELETE, a `/commit/` path,
`x-ndjson`, `preupload`, an LFS upload, a `data=` argument; GET, HEAD, `/resolve/`, `/tree/`, an LFS
download, `urlopen(url)` with one argument, `requests.get`).

- **R6. A Git LFS batch is judged by its operation.** An LFS batch is a POST either way. A request that
  carries `operation: 'upload'` is a write, `operation: 'download'` a read (found this way the verb is
  *inferred*, R33). The operation must belong to the mention's own request: for a mention followed by
  `/info/lfs`, or held in a name, it is looked for up to the end of the next request call (the body is
  often built first and sent by that call); for a mention inside a request call whose path the redaction
  swallowed, only up to the start of the next request call. A mention followed by `/info/lfs` with no
  visible operation is not counted.
- **R7. A repository held in a variable names only an owner.** `…/<owner>/' + repo + '/…` is not counted.
- **R8. A mention inside a request call is judged by that call.** The mention is *inside* a request call
  when a request call starts before it with no `;` and no line break in between. The verbs of that call
  decide; a verb belonging to another place's mention or to the next request call does not. With a write
  verb and no nearer read verb it is a write. A request call with no verb at all is a read (a request
  without a method is a GET); this is a *default* (R31).
- **R9. A mention assigned to a name is judged by the calls the name is passed to.** `u = '…place…'` (also
  `u = base + '…place…'`): every later call that takes `u` as an argument, or interpolates it as `'{u}'`,
  up to the point where `u` is given another value, is looked at. If any of them writes, the mention is a
  write. Otherwise, if `u` is passed to anything, it is a read. If `u` is never passed to a call, the
  mention is not counted (named, not opened).
- **R10. A helper call's verb is read from that call only.** When the name is passed to a helper with the
  verb as an argument (`Q('GET', src, …)`), the verb literal inside that call's own parentheses decides; a
  `data=`, `body=` or `json=` argument makes it a write. A POST in the next call does not.
- **R11. A literal passed to a helper with a write verb beside it is a write**: after it (`req('…place…',
  tok, 'POST', data)`) or before it as the first argument (`Q('POST', '…place…', body)`). A second
  positional argument to `Request(url, data, …)` is a body, so that request is a write.
- **R12. A request written as data is judged by its fields.** In `{"u": "…place…", "m": "POST", "b": …}`
  (keys `u`/`url`, `m`/`method`, `b`/`body`/`data`) the method decides; without a method, a body makes it
  a write.
- **R13. A cut-off call is not counted.** If the text is cut inside the call before its verb (`…place…',
  {metho`), the operation is unknown and not counted. The same holds when no verb is in reach (R14), the
  record ends within 40 characters after the place with no `)` in between, and either the place sits inside
  an open call or the record up to the place is a bare URL (redaction markers such as `[HF REPO 5]` count
  as part of the URL).
- **R14. Otherwise the nearest verb decides, and no verb means a read.** *(heuristic)* For a mention that
  none of R6 to R13 and R17 settles, the main implementation looks at the text from 160 characters before
  the mention (or the start of its request call) to 260 after, cut at the neighbouring place mentions and
  at the start of the next request call. The nearer of the nearest write verb and the nearest read verb
  decides; on a tie the write verb wins. With no verb in that span the mention is a read by default (R31).
- **R15. Options held in a variable count.** In `fetch(u, o)` the object literal last assigned to `o`
  before the call is part of the call; if `o` is a parameter of a wrapper function, the wrapper's callers
  (the 500 characters after it) carry the verb.
- **R16. A call ends at its closing parenthesis**, or at the start of the next request call, or after 600
  characters, whichever comes first. Nothing after that belongs to it.
- **R17. A place held by a name the record does not show is not counted when a later call through a name
  writes.** If the mention ends a string literal that closes its statement (`…place';`, or `…place'` at
  the end of a line or of the record), it is not inside a request call (R8), no assignment is visible (R9)
  and it is not a request written as data (R12), then the place is held by a name hidden by redaction or a
  cut, and the calls that use that name cannot be told from other calls whose address is a variable. If any
  later request call in the record (within 8,000 characters) whose address is not a literal URL writes, the
  mention is not counted: it may be the place written to, or it may only have been read. If no such call
  writes, R14 applies. A quoted value that follows a key at the start of its line (`path: "reference://…place"` in a
  pasted dataset card) is a config entry, not a held name, and R14 applies to it too. This is the "script that writes a script" case (`…place';T='…';s=f"x.open('POST',
  '{u}',0)…"`): counting it as a read made a false delivery, counting it as a write would be a guess.

## Other kinds of operation

- **R18. A record posted to a place posts there.** When the pack has `structural_channels` (the default)
  and the record has a channel field, the record is a *post* on `place:<channel>`: it reads what is there
  and writes to it. A record whose kind is in the pack's `write_only_kinds` is a write instead.
- **R19. Naming another structural place reads it.** When the pack has `mention_channels`, a word of six
  or more characters in the record's text that equals the short name (the last part after `~`, `/`, `:` or
  `#`) of another record's channel is a read of that place. If several places share the short name, those
  under the record's own prefix (before the last `~`) are preferred.
- **R20. A logged direct message is a delivery as it stands.** A record with a recipient field that
  differs from its actor is a write to `inbox:<recipient>`. The read is the recipient's reply: the first
  child record by the recipient, else the recipient's next record within the following 59 records of the
  same channel, not earlier in time; if there is none the record itself stands for both. Dated direct
  messages are deliveries with grade *direct*; undated ones are counted separately, not as deliveries.

## The actor of an operation

- **R21. Every record has an actor**, the first of:
  1. the record's actor field, when it is one of the record's own non-shared identity tokens;
  2. the first non-shared identity token found in the record (pack `identity_patterns` order);
  3. a handle the pack lists, named in the text (mapped to its family);
  4. the non-shared token most used in the record's thread (ties: the one seen first in the input);
  5. `run:<thread root id>`, an anonymous run.
  Tokens in the pack's `shared_identities` (a key everybody uses) never name an actor.
- **R21a. Several tokens in one record.** If the actor came from step 2 and the record holds more than one
  non-shared token, and exactly one of them appears in the code judged for a mention, that token is the
  actor of that operation.

## Deliveries

- **R22. Same place.** The write and the read are operations on the same place (R1).
- **R23. Different actors, different records.** The write's actor differs from the read's actor (R21), and
  they are different records.
- **R24. The write is not later than the read.** Both must be dated; the write's time is less than or
  equal to the read's time. A write counts as a writer if it is a write or a post; a read counts if it is
  a read or a post.
- **R25. A read without a time is never a delivery.** If its place has a write by another actor it is
  counted under "order unknown" instead. A write without a time is never the write of a delivery.
- **R26. The latest earlier write.** A read is linked to at most one write: the latest write satisfying
  R22 to R24 and R27. When two candidate writes have the same time, the one that comes later in the input
  is taken (with equal times the log's own order is the only evidence of sequence). The result therefore
  depends on input order when times tie.
- **R27. The same program rerun is not a message.** If the first 60 normalized tokens of the write record
  and of the read record are equal (and each has at least 20), the write is not a candidate. Normalizing
  replaces bracketed redaction markers by their name, hex strings of 8 or more digits and numbers by
  placeholders, lowercases and collapses whitespace.
- **R28. Reading the same write again is one message.** For one write record and one reading actor there
  is at most one delivery: the earliest read (ties: the one earlier in the input). Later reads are counted as
  repeat reads.
- **R29. A full-body post that keeps nothing is an overwrite, not a delivery.** When the pack has
  `full_body_posts`, and write and read are both posts, the lines (of 8 or more characters) the write
  added compared with the post before it on that place are compared with the read's text. If the write
  added lines and the read keeps none of them, the pair is an overwrite and is not counted.
- **R30. The count.** "Deliveries" is the number of pairs left after R22 to R29 plus the dated direct
  messages (R20). "Between named actors" counts those where neither actor is an anonymous run. "Pairs" is
  the number of distinct ordered (writer, reader) pairs.

## Grades

- **R31. Weak.** A delivery is *weak* when the write or the read operation was a default (no verb found:
  R8 last sentence, R14 last sentence), or its place matches one of the pack's `coarse_channels` (a
  redaction that may have merged several places), or either record's time was estimated and the two are
  more than one hour apart.
- **R32. Direct.** Otherwise it is *direct* when both sides are a post or have their verb in the very call
  that names the place (R8).
- **R33. Inferred.** Otherwise it is *inferred* (the verb came through a variable, a helper's arguments,
  an LFS operation, a request written as data, or text nearby).
- **R34. The grade never changes the count.** It records how the verb was found.

## Counting by agent

- **R35. An agent is a group of tokens.** The estimate joins two named actors when the identity module
  proposes them as one agent with high confidence and the investigator has not rejected it, or when the
  investigator accepted the pair. Groups are the connected components; a group is named after its busiest
  token.
- **R36. Between agents.** Only deliveries between two named actors are regrouped. A delivery whose writer
  and reader map to the same agent is counted "inside one agent", never between agents. So the number of
  deliveries between agents plus the number inside one agent equals the number between named tokens (less
  any the investigator rejected), and regrouping can never raise the between-unit count.
- **R37. The first message between agents** is the earliest-read delivery between two different agents on
  a place that is not coarse (R31).

## What is dropped, and why

| dropped | statement | why |
|---|---|---|
| a mention in a comment | R3 | naming a place is not opening it |
| a name assigned and never passed to a call | R9 | same |
| an LFS batch with no visible operation | R6 | upload or download cannot be told |
| a repository held in a variable | R7 | the place is not known |
| a call cut off before its verb | R13 | the verb cannot be seen |
| a place held by a hidden name when a later call through a name writes | R17 | read or write cannot be told |
| a read by the writer itself | R23 | not a message between two actors |
| a read before any write, or with no time | R24, R25 | order is the only evidence of direction |
| the same program rerun under another token | R27 | one sender retrying |
| a repeat read of the same write | R28 | one message, read twice |
| a full-body post that keeps none of the lines | R29 | it may have been written without reading |

## Properties the rule must have

These follow from the statements and are tested in `agenttrace/tests/test_properties.py`.

- **P1 (R36).** Regrouping tokens into agents never raises the between-unit count, and a delivery whose
  two ends map to one agent is never between agents.
- **P2 (R22 to R24).** Every delivery has a write operation and a read operation on the same place, by
  different actors, from different records, with write time ≤ read time.
- **P3.** The result does not depend on the order of the input records when every record has its own
  time and its own token and no two operations on a place share a time. With equal times R26 and R28 fall
  back on input order; on the collusion.wiki logs 29 of 9,867 deliveries pick a different write record
  if ties are broken by record id instead (a revision and its save event carry the same second). The
  count is the same either way.
- **P4 (R28).** Repeating a reader's polls adds no delivery.
- **P5 (R3, R9, R13).** Adding records that only mention a place (a comment, a cut-off call, a name never
  passed) changes no delivery.
- **P6 (R24).** Removing every write leaves no delivery.
- **P7.** The count is the same on every run.

## Checking the rule

| check | command | what it shows |
|---|---|---|
| unit and property tests | `python3 -m unittest agenttrace.tests.test_messages agenttrace.tests.test_properties agenttrace.tests.test_refcount` | each statement on known answers; P1 to P7 on seeded random swarms |
| second implementation | `python3 -m agenttrace.tools.crosscheck --out reports/integrity/crosscheck.json` | deliveries found by both implementations, by one only, with record ids; exit 1 above 10% disagreement on any dataset |
| mutation testing | `python3 -m agenttrace.tools.mutate --quick` (sample) or without `--quick` (all) | how many deliberate breaks of `messages.py` the tests notice, and the ones they miss |

The second implementation (`agenttrace/refcount.py`) reads the call around a mention with a tokenizer instead
of character windows. It agrees exactly with the main one on the demo swarm, the benign swarm, the framework
samples and generated swarms. On the Swarm Traces release it does not: redaction breaks quote pairing, and it
then takes commits for reads. `reports/integrity/crosscheck_judgement.json` lists every disagreement with a
judgement. Treat agreement between the two as a check on clean code shapes, not as evidence about the release.

## What the rule does not see

- A place named in a printed string, or in data that the record uploads, with no later write through a
  name, still counts as a read by default (R14).
- A name derived from another (`v = u + '/commit/main'; fetch(v, …)`) is not followed past the first name.
- An assignment whose quotes are escaped (`u=\'…\'` inside a JSON-wrapped program) or that uses a Python
  string prefix (`u=f'…'`), and a use such as `urlopen(u % i)`, are not recognised by the main
  implementation: the mention falls to R14 or R17, or is dropped as never passed.
- A helper that takes the address and a body with no verb literal (`p('…place…', body)` where `p` POSTs)
  is a read by default (R14).
- R7 also drops `…place/' + id + '/merge'` where the place is a whole repository and only a sub-path is a
  variable.
- Whether a read fetched the newest write or an older one (R26 assumes the newest).
- Records outside the pack's patterns. Recall is not measured on real data.

## Tests that guard each statement

`agenttrace/tests/test_mutants.py` was written from the survivors of the mutation run: small synthetic cases,
one statement each, that fail when the statement's code is changed. Test names carry the statement id.

| statements | test class in `test_mutants.py` |
|---|---|
| R1 (pattern flags, empty group), R2, R4, R5, R18, R19, R21a, R20 as operations | `ChannelPatternTests`, `OperationTests` |
| R3 (a mention in a comment, in content spread) | `SpreadTests` |
| R6, R7 | `JudgeLfsTests` |
| R8, R14 (windows of 160 and 260, nearest verb, ties), R4 bounds | `JudgeWindowTests` |
| R9, R10 and R11 spans | `JudgeNameTests` |
| R10, R11 (the helper call's own parentheses, `Request(url, data)`) | `HelperVerbTests` |
| R12 | `DescriptorTests` |
| R13 | `JudgeCutTests` |
| R15 | `OptsWriteTests` |
| R16 | `CallEndTests` |
| R17 | `HiddenHolderTests` |
| R20 (reply, 59 records, times) | `DirectTests` |
| R21 | `ActorTests` |
| R22 to R25, R28, R29, R31 | `DeliveryTests` |
| R27 | `ProgramTests` |
| R30, R31, R37, list caps | `FlowTests` |

The full mutation run (1,173 mutants of `messages.py`) is in `reports/integrity/mutation.json`: 1,124 killed,
49 survive, of which 48 are judged equivalent by hand (each with its reason, listed in
`agenttrace/tools/mutate.py`) and 1 is unjudged. The judgements are a reading of the code, not a proof.

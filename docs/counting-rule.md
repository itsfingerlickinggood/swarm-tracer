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
  (replies, recovered copies) produce no operations. If the pack lists `reply_kinds`, records of those kinds are
  never actions. The general pack lists `result` and `error`, the two kinds the MCP reader gives a server's answer
  to a call: a tool server is infrastructure, not a party, so its answer is what the caller was sent and not
  something an actor did. Before v2.3.0 the answer posted on the session (R18) and every call was a delivery
  from the agent to the server.
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
- **R6a. A POST to `…/paths-info` is a read.** It only asks about files; a mention followed by `/paths-info` is a
  read (inferred), whatever method the call names.
- **R6b. An LFS upload batch is a write only if the object goes up.** The batch announces an upload. It counts
  as a write only when (a) its object id was not asked for with `operation: 'download'` earlier in the trace (an
  object that could be downloaded already existed, so the batch is a probe) and (b) a later record sends that
  object (a commit that names it as an `lfsFile`, a PUT). With no visible object id it is not counted. This
  removed 10 of the 23 deliveries counted by v2.1.0, all resting on one probe of one file.
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
  {metho`), or the record ends inside the verb itself (`…place…',{method:'POS`), the operation is unknown and
  not counted. The same holds when no verb is in reach (R14), the
  record ends within 40 characters after the place with no `)` in between, and either the place sits inside
  an open call or the record up to the place is a bare URL (redaction markers such as `[HF REPO 5]` count
  as part of the URL).
- **R13a. A record cut inside a verb that the next record completes is read as one record.** Some rows of a
  trace are pieces of one program split across records. Two records are joined when all of this holds:
  (a) the first record's text ends inside the verb of a call: its last characters are the word `method` and a
  `:` or `=`, or `.open(` (spaces allowed between these), then a quote mark, then one to five letters that begin
  one of POST, PUT, PATCH, DELETE, GET, HEAD without completing it (`…',{method:'POS`, `x.open('PU`), letter
  case ignored;
  (b) the next record in the input begins with the missing letters of one of those verbs, followed at once by the
  same quote mark (`T',headers:…`);
  (c) both are action records (R2) of the same kind with the same actor and channel fields, neither is addressed
  to a recipient (a logged direct message, R20, is never joined), and the second has no parent, or its parent is
  the first record or the first record's parent.
  The joined record's text is the first text followed by the second with nothing in between. It keeps the first
  record's id, fields and position in the input; its time is the first record's, or the second's when the first
  has none; its identity tokens are the first record's followed by those of the second that the first does not
  have (R21 then runs on the joined record; for step 4 of R21 each original record's tokens still count in that
  record's own thread). The second record no longer exists for the rule: it has no operations of its own. If the
  joined text again ends inside a verb and the following record completes it, that record is joined too. Joining
  is done first: every other statement on this page sees only the joined record (its text for R3 to R17, R23a,
  R27 and R38; its time for R24), except R20, which reads the records as they stand in the input. A record that ends inside a verb and is
  *not* completed by the next record stays cut and is not counted (R13). A record cut anywhere else (inside an
  address, a string, a name) is never joined: only the missing letters of a verb are taken as evidence that one
  record continues another. On the release this joins one pair (R0022674 with R0022675).
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
- **R18a. A tool call that names its place operates on that place.** *(v2.3.0)* When the pack has `tool_places`
  (the general pack does, and a pack made by the pack builder inherits it), a record with a tool field is looked
  at as a call of that tool. Its arguments are the first JSON object in the record's text (from the first `{` to
  the `}` that closes it, or to the end of the text when it is cut). Every string of 1 to 300 characters that is,
  at any depth of that object, the value of one of the pack's place keys (`place`, `path`, `file`, `key`, `uri`,
  `board`, `channel`, `page` and the others in `tool_places.keys`; letter case of the key ignored; a list
  under such a key is not read) names the place `tool:<value>`, the value without spaces at its ends. The value
  counts whatever its shape: one word is a place as much as a path. The tool's name is the verb: split into words at every
  character that is not a letter and before a capital that follows a lower-case letter (`read_file`, `readFile`),
  the record is a *write* when one of the words is in `tool_places.write_words` (write, save, put, post, append,
  ...), else a *read* when one is in `tool_places.read_words` (read, get, fetch, list, ...), else it has no
  operation on the place. One operation per record and place (R5). The verb counts as found in the call itself
  (R32). R3 does not apply: an argument is data of the call, not code. An argument inside which a channel
  pattern of the pack matches (R1) is left to that channel and is not counted again. The server is not part of
  the place's name: the record does not say which server the call went to, so two servers that each hold a place
  of the same name are one place to the rule.
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
- **R23a. A read that lists the writer's own token is not a delivery.** When the actor of the write was found
  as an identity token (kind `token`) and the read record contains that token as a whole word (a loop over a
  list of tokens that includes it), the read may be the writer reading its own write, so that write is not a
  candidate for it. Actors named by a field or a handle are not tested this way.
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
  redaction that may have merged several places: an owner only, `[HF REPO]` and other unnumbered markers,
  `[USER n]`), or either record's time was estimated and the two are
  more than one hour apart.
- **R32. Direct.** Otherwise it is *direct* when both sides are a post or have their verb in the very call
  that names the place (R8).
- **R33. Inferred.** Otherwise it is *inferred* (the verb came through a variable, a helper's arguments,
  an LFS operation, a request written as data, or text nearby).
- **R34. The grade never changes the count.** It records how the verb was found.

## The two counts

- **R38. Two counts are reported, never one for the other.** *Write then later read* is the count of R30:
  one actor wrote to a place and a different actor read it later. *Reader uses what was written* is the
  subset that passes the written-content test. A logged direct message passes as it stands. A wiki edit that
  kept lines the writer added passes by R29. Any other delivery passes when R38a or R38b holds. The output
  keeps `deliveries_write_then_read`, `deliveries_reader_uses_content` and, for each delivery, `uses_content`,
  up to three `shared_terms`, and for a pass `content_how` (`kept lines`, `quoted in the read`,
  `in the reader's later output`; with the last, `used_in` is the reader's record). The test measures a shared
  quotation, not understanding: a pass does not prove the reader acted on the content, a failure does not
  prove it did not (it may have used it without quoting, or reworded it).
  *The content of a record*, for R38a and R38b, is its text. Of a tool call (a record with a tool field whose
  text holds a JSON object) it is only the strings that are not keys in the first JSON object of the text, JSON
  escapes decoded: the tool's name and the names of its arguments are the tool's vocabulary, the same in every
  call, and the tool's name is never a term. A place argument (a string under a place key in the first JSON
  object of a text, R18a) is an address and is left out.
- **R38a. The read record quotes what was written.** The terms (identifiers, paths, file names and numbered
  redaction markers of 8 or more characters) found in the content of both the writer's and the reader's record,
  leaving out the place's address and credentials, are listed; the delivery passes when at least one such term
  is rare, that is, found in at most 5 records of the trace.
- **R38b. The reader's later output holds a distinctive term the writer wrote.** *(v2.3.0)* R38a compares the
  write record with the read record. In a tool-call log the read record is the request, which holds no
  content, so a reader that fetched a fact and then handed it in was never seen. R38b looks at what the
  reader did after the read.
  - *What was written* is the content of the write record with every match of a channel pattern of the pack
    taken out: the place's address is not content. When the pack has `full_body_posts` and the write is a post,
    what was written is only the lines that post added (R29).
  - A *distinctive term* is one of: a numbered redaction marker (`[`, a letter, then letters, spaces, `:` and
    `_`, a space or colon, digits, `]`) that is not a credential (`[CREDENTIAL n]`); a number of 5 or more digits; a run of letters,
    digits and `_ . - /`, taken without dots, hyphens and slashes at its ends, that is 8 or more characters
    long, holds a digit, an underscore or a capital letter after its first character, and does not begin with
    a date (`2026-05-26…`). `R2-PELICAN-1585`, `report_v2.json` and `48213` are distinctive. A plain word is
    not, however long, and neither is a compound of plain words (`field-value`, `example.com/hello`) or a
    phrase of plain words. Markers are taken first, runs from the rest of the text. A record *holds* a term
    when the term is one of the markers or runs of its whole text (runs of 5 or more characters), as an equal
    string.
  - A *later record of the reader* is an action record (R2) whose actor (R21) is the delivery's reader, that has
    a time, comes after the read record (a later time, or the same time and later in the input) and whose
    parent is not the read record: the answer to a read is what was fetched, not what the reader did with it.
  - The delivery passes when a distinctive term of what was written is held by a later record of the reader,
    and both guards hold for that term. **Guard 1, new at the write:** no record that comes before the write
    record, by an actor other than the writer, holds the term. **Guard 2, not the reader's already:** no
    record of the reader that comes before the read record holds the term, and the read record does not hold
    it. For both guards a record without a time comes before every record that has one. Guard 1 is the
    false-positive guard against boilerplate: a name, a path or a number that was in the trace before the
    writer wrote it is not evidence that the reader got it from the writer. Guard 2 keeps out what the reader
    brought itself. `shared_terms` lists up to three of the terms, the one found first first.
  - What still passes wrongly: a term both actors were given outside the trace (a prompt, a shared config) that
    the writer happens to write first; a term the reader took from another copy of it written after the
    write. What is missed: a reader that rewords, a fact that is a phrase of plain words, a number of fewer
    than 5 digits, a reader whose later records have no time. The shapes and the 5 digits were chosen while
    looking at the harness's own scripted swarms ([the harness](harness.md)); they are not validated on real
    agents.
- **R39. Board places are keyed by their full path.** A folder `zzNAME/CHILD_A` and a read of
  `zzNAME/GETCHILD_…` are different places; naming only the top folder merged them.

## Counting by agent

- **R35. An agent is a group of tokens.** The estimate joins two named actors when the identity module
  proposes them as one agent with high confidence and the investigator has not rejected it, or when the
  investigator accepted the pair. Groups are the connected components; a group is named after its busiest
  token.
- **R36. Between agents.** Only deliveries between two named actors are regrouped. A delivery whose writer
  and reader map to the same agent is counted "inside one agent", never between agents. So the number of
  deliveries between agents plus the number inside one agent equals the number between named tokens (less
  any the investigator rejected), and regrouping can never raise the between-unit count. The estimate also
  joins a pair that shows all of: the same programs run, both seen together only in key-sweep records (4 or
  more tokens at once), messages passing between them, and no evidence against (never active in parallel). Each
  is weak alone; together they read as one agent talking to itself. This is a heuristic of v2.2.0 and is not
  validated on data with known agents.
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
| a read by the writer itself | R23, R23a | not a message between two actors |
| an LFS upload batch of an object already requested for download, or never sent | R6b | a probe of a file that existed |
| a record that ends inside the verb, when the next record does not complete it | R13, R13a | the verb cannot be seen |
| a read before any write, or with no time | R24, R25 | order is the only evidence of direction |
| the same program rerun under another token | R27 | one sender retrying |
| a repeat read of the same write | R28 | one message, read twice |
| a full-body post that keeps none of the lines | R29 | it may have been written without reading |

## What the rule counts on the Swarm Traces release

With the rules above, the release gives 11 deliveries (write then later read), 4 of them between two named
tokens, 8 on places the redaction names exactly (the other 3 are weak by R31). None passes the written-content
test, in either form: no reader quotes a term the writer wrote (R38a), and no reader's later record holds a
distinctive term of its write record under the two guards (R38b). By agent the 4 named deliveries become 2
between agents and 2 inside one agent. On the audit 5 of the 11 are labelled true and 6 unclear; the labels are
one reader's and the rule has not been checked by a second human labeller.

How the count got here. v2.1.0 counted 23; 10 were one LFS upload probe (R6b), 1 a reader listing the writer's
own token (R23a), 2 a call cut inside its verb (R13), 1 a board folder read by random names (R39). One reviewer
defended about 5 of the 23 (range 3 to 7). v2.2.0 counted 9. With R13a (v2.3.0) the count is 11: the commit
joined from R0022674 and R0022675 is read later by two anonymous runs. These are the two links v2.2.0 dropped as
a call cut inside its verb; their audit label is still "unclear", because nobody has judged the joined text. The
other v2.3.0 statements change nothing on the release: it has no tool calls (R2, R18a).

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
- **P8 (R13a).** Cutting a record inside a verb into two consecutive records changes no delivery (tested on
  both implementations in `agenttrace/tests/test_refcount.py`, `JoinTests`).

## Checking the rule

| check | command | what it shows |
|---|---|---|
| unit and property tests | `python3 -m unittest agenttrace.tests.test_messages agenttrace.tests.test_properties agenttrace.tests.test_refcount agenttrace.tests.test_audit_rules` | each statement on known answers; P1 to P7 on seeded random swarms |
| second implementation | `python3 -m agenttrace.tools.crosscheck --out reports/integrity/crosscheck.json` | deliveries found by both implementations, by one only, with record ids; exit 1 above 10% disagreement on any dataset |
| mutation testing | `python3 -m agenttrace.tools.mutate --quick` (sample) or without `--quick` (all) | how many deliberate breaks of `messages.py` the tests notice, and the ones they miss |

The second implementation (`agenttrace/refcount.py`) reads the call around a mention with a tokenizer instead
of character windows. It finds the same deliveries as the main one on every dataset checked: the release (11), the
collusion.wiki logs (9,867), the demo swarm, the benign swarm, the framework samples. On the release it did not
until v2.2.0: redaction breaks quote pairing, and it then took commits for reads (191 deliveries against the 9 of v2.2.0). It was
fixed by implementing R6a, R6b, R23a, R38 and R39 from this page and by reading the call from the raw text where the
tokens cannot be trusted, while reading where it differed from the main one on the release; so its agreement
there is not independent evidence. 262 single operations on the release still differ without changing a delivery.
`reports/integrity/crosscheck_judgement.json` lists them with a judgement made for the v2.2.0 rule; for v2.3.0 the
group sizes were checked and are the same, and the rows were not read again.

R18a and R38b (v2.3.0) were written into `refcount.py` from this page, with other means than the main
implementation uses (the arguments of a call are walked as JSON character by character instead of matched by a
pattern; the terms are cut by splitting the text; every holder of a term is kept instead of the two earliest).
The crosscheck now also reports the written-content test: how many deliveries pass in each implementation and
on how many the verdict is the same. R38b gives the same verdict in both on every dataset checked. R38a, which
v2.3.0 did not change, does not: the main implementation passes 82 deliveries of the demo swarm on the host
name left over when the place's pattern is cut out of its URL, and 51 on the collusion.wiki logs on the page's
own name; the second implementation leaves both out as part of the place's address. Those passes of R38a in
the main implementation are not quotations of content. They are listed in `reports/integrity/crosscheck.json`
(`content_test.verdict_differs`) and are not fixed here.

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
- A fragment that continues somewhere other than at the start of the next record. Of the 15 action records on
  the release that end inside a verb, one is joined (R13a), and two are continued after a staging header line in
  the next record (R0006647 in R0006648, R0020565 in R0020566).
  R13a does not join those two: it would have to guess where the header ends. The first of them is followed by a
  complete copy of the same program (R0006649), which is judged as it stands. The other 12 are followed by an
  unrelated record and stay cut (R13). Records cut inside an address or a string are not joined at all, and
  the live monitor (`online.py`) judges records one at a time and never joins.
- Whether a read fetched the newest write or an older one (R26 assumes the newest). A board that returns every
  line delivers the older lines too; on the harness's scripted swarms that is 25 of 58 true deliveries
  ([the harness](harness.md)).
- Which server a tool call went to (R18a): two servers that each hold a place of the same name are one place.
  A tool whose name has no write or read word (`submit`, `run_tests`), a place under a key the pack does not
  list, and a place passed as a list are not seen.
- A tool server that sends a request of its own (MCP sampling): only its answers are set aside by R2, so such a
  request still posts on the session.
- A use that is not a quotation (R38): a reader that rewords what it read, or a fact that is a phrase of plain
  words, passes neither R38a nor R38b.
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
| R6a, R6b, R13 (inside the verb), R13a (joined fragments), R23a, R31 (coarse), R38, R39, R35 (sweep pairs), release counts | `agenttrace/tests/test_audit_rules.py` |
| R13a in the second implementation, P8 | `JoinTests` in `agenttrace/tests/test_refcount.py` |
| R2 (reply kinds), R18a (tool places), R38b (the reader's later output, its two guards, what is distinctive), each in both implementations | `agenttrace/tests/test_tool_calls.py` |

The full mutation run (22 November 2026, 1,656 mutants of `messages.py` as it stands for v2.3.0) is in
`reports/integrity/mutation.json`: 1,570 killed, 86 survive, of which 78 are judged equivalent (each with its
reason, listed in `agenttrace/tools/mutate.py`) and 8 are not. The judgements are a reading of the code by the
authors' AI assistant, not a proof. The earlier run, on the v2.1.0 file, had 1,173 mutants and 1,124 killed.

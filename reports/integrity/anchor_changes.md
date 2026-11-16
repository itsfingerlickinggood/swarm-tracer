# Anchor changes for the v2.2.0 rewording

Made in `agenttrace/tools/provenance.py` (`registry()`). The published texts were reworded for v2.2.0 ("23 messages" became "9 write-then-read deliveries" and so on), so 124 registered places could not be matched any more (122 "anchor not found", 2 printing the v2.1.0 value in a sentence now labelled as history); `build` then found one more (the last row). For each one I looked for where the current text prints the value. **109 anchors were re-pointed** (same value, same format, same tolerance; the anchor now names the new wording and was checked to match exactly one place in its file), **16 places were dropped** (the corrected text no longer prints the value at that place), and **0 new values were registered**. No value's computation was changed, no tolerance was loosened, and no published text was edited to fit an anchor.

A dropped place is only that place: every value keeps its other places (listed in `agenttrace/claims/provenance.json`). Values that some text still prints in a form no registered format reads are named below.

Two of the 122 were already in the registry but not in the last manifest (`docs/validation.md`, `The release now shows <v> deliveries, ...` and `shows \d+ deliveries, <v> of them between named tokens`): they point at a sentence that is not in the page and are dropped with the others. The three `repo.version` places (README, docs/index.html, slides) print 2.2.0; the manifest said 2.1.0 and `build` updates it, which is value drift, not an anchor change.

## Re-pointed (109)

| value id | file | old anchor | new anchor | reason |
|---|---|---|---|---|
| release.deliveries | paper/report.html | `It finds <v> messages, \d+ of them between` | `It finds <v> write-then-read deliveries \(a write to a shared place` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | paper/report.html | `Of the <v> messages, \d+ passed through` | `All <v> write-then-read deliveries passed through dataset repositories` | sentence now reads "All 9 ... passed through dataset repositories": prints the total |
| release.deliveries | paper/report.html | `They report <v> links, \d+ judged true` | `and report <v> write-then-read deliveries, \d+ labelled true` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | paper/report.html | `reconstructed <v> messages \(\d+ between named tokens\)` | `reconstructed <v> write-then-read deliveries \(\d+ between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | paper/report.html | `\d+ of <v> messages rest on one` | `\d+ of <v> deliveries rest on one, none between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/report.html | `It finds \d+ messages, <v> of them between` | `so we do not call them messages\), <v> of them between \d+ named tokens in \d+ sender.receiver pairs` | "messages" reworded to "write-then-read deliveries"; the clause now follows the parenthesis |
| release.named_deliveries | paper/report.html | `Between named tokens the tool finds <v> messages among` | `Between named tokens the tool finds <v> deliveries among` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/report.html | `reconstructed \d+ messages \(<v> between named tokens\)` | `reconstructed \d+ write-then-read deliveries \(<v> between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/report.html | `puts \d+ of the <v> messages inside one agent` | `puts \d+ of the <v> named deliveries inside one agent` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/report.html | `Between estimated agents, \d+ of the <v> messages fall inside` | `Between estimated agents, \d+ of the <v> named deliveries fall inside` | "messages" reworded to "write-then-read deliveries" |
| release.named_pairs | paper/report.html | `between \d+ named tokens in <v> sender.receiver pairs, mostly through` | `of them between \d+ named tokens in <v> sender.receiver pairs, all through` | "mostly" became "all"; same sentence |
| release.named_pairs | paper/report.html | `Who talked to whom: all <v> pairs between` | `\(v2\.2\.0 has <v> pairs between \d+ tokens\)` | Figure caption now lists the v2.1.0 pairs (5) and then the v2.2.0 ones (4): the anchor takes the v2.2.0 clause |
| release.named_message_tokens | paper/report.html | `finds \d+ messages among <v> tokens in` | `Between named tokens the tool finds \d+ deliveries among <v> tokens in` | "messages" reworded to "write-then-read deliveries" |
| release.named_message_tokens | paper/report.html | `all \d+ pairs between <v> named tokens` | `\(v2\.2\.0 has \d+ pairs between <v> tokens\)` | Figure caption now lists the v2.1.0 list and then the v2.2.0 clause |
| release.deliveries_hf_dataset | paper/report.html | `Of the \d+ messages, <v> passed through dataset repositories` | `All <v> write-then-read deliveries passed through dataset repositories` | the sentence now says "All 9": prints the hf_dataset count (equal to the total) |
| release.deliveries_on_merged_places | paper/report.html | `<v> of \d+ messages rest on one, none between named tokens` | `<v> of \d+ deliveries rest on one, none between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.place_actors_anonymous | paper/report.html | `<v> actors on places are single anonymous runs` | `and <v> such runs appear on places, against \d+ tokens` | sentence reworded; same number (3,765) |
| release.place_actors_tokens | paper/report.html | `single anonymous runs, against <v> tokens` | `such runs appear on places, against <v> tokens` | sentence reworded |
| release.place_actors_tokens | paper/report.html | `anonymous runs against <v> tokens; ` | `anonymous runs against <v> tokens on places` | appendix row reworded |
| release.first_message_time | paper/report.html | `The first message between two named tokens came at <v> \(` | `The first delivery between two named tokens came at <v> \(` | "messages" reworded to "write-then-read deliveries" |
| release.first_message_write_time | paper/report.html | `token 170 uploaded to a dataset through Git LFS at <v>, and token 169` | `token 170 posted to a dataset at <v>, and token 169` | the first delivery is now a POST at 00:45, not an LFS upload at 11:18 |
| release.first_message_write_id | paper/report.html | `The first message is <v> to R\d+` | `The first delivery between named tokens is <v> to R\d+` | "messages" reworded to "write-then-read deliveries" |
| release.first_message_read_id | paper/report.html | `The first message is R\d+ to <v>` | `The first delivery between named tokens is R\d+ to <v>:` | "messages" reworded to "write-then-read deliveries" |
| release.volume_alarm_share | paper/report.html | `a volume alarm fired with <v>%` | `a volume alarm that fires with <v>% of the harm still to come` | sentence reworded |
| release.group3_time | paper/report.html | `a group of three tokens linked by messages at <v> \(` | `a group of three tokens linked by deliveries at <v> on [A-Z][a-z]+ \d+ \(` | "messages" reworded to "write-then-read deliveries"; the time now carries its date |
| release.group3_share | paper/report.html | `linked by messages at [\d:]+ \(<v>% to come\)` | `linked by deliveries at [\d:]+ on [A-Z][a-z]+ \d+ \(<v>% to come\)` | "messages" reworded to "write-then-read deliveries"; the time now carries its date |
| release.robust_first_message_low | paper/report.html | `and the first message between <v>% and` | `and the first delivery between <v>% and` | "messages" reworded to "write-then-read deliveries" |
| release.robust_first_message_high | paper/report.html | `and the first message between \d+% and <v>%` | `and the first delivery between \d+% and <v>%` | "messages" reworded to "write-then-read deliveries" |
| release.first_message_hours_before_surge | paper/report.html | `11:51 on July 10 \(\d+% to come\), <v> hours before the surge` | `on July 11 \(\d+% to come\), <v> hours before the surge` | the time of the first delivery changed (03:06 on July 11); the clause is the same |
| release.first_message_hours_before_surge | paper/report.html | `through a shared place fired <v> hours before the surge` | `A write-then-read link between two tokens fired <v> hours before the surge` | sentence reworded |
| release.agent_messages_inside | paper/report.html | `puts <v> of the \d+ messages inside one agent` | `puts <v> of the \d+ named deliveries inside one agent` | "messages" reworded to "write-then-read deliveries" |
| release.agent_messages_inside | paper/report.html | `Between estimated agents, <v> of the \d+ messages fall inside one agent` | `Between estimated agents, <v> of the \d+ named deliveries fall inside one agent` | "messages" reworded to "write-then-read deliveries" |
| release.agent_carried_sign_time | paper/report.html | `one token holding another.s fires at <v> \(` | `one token holding another.s at <v> \(` | "fires" dropped from the clause |
| release.agent_carried_sign_share | paper/report.html | `holding another.s fires at [^(]+\(<v>% to come\)` | `holding another.s at [^(]+\(<v>% to come\)` | "fires" dropped from the clause |
| release.audit_reported_true | paper/report.html | `They report \d+ links, <v> judged true` | `and report \d+ write-then-read deliveries, <v> labelled true` | "messages" reworded to "write-then-read deliveries" |
| release.audit_reported_unclear | paper/report.html | `judged true and <v> undecidable` | `labelled true and <v> undecidable` | "judged true" became "labelled true" |
| audit.links | paper/report.html | `after an audit of <v> links cut` | `Audits of <v> links cut a first count` | sentence reworded |
| audit.first_count | paper/report.html | `cut a first count of <v>\.` | `cut a first count of <v> to 19, then 23, then 9` | the clause now continues with the later counts |
| validation.msg_precision_median | paper/report.html | `Message links: precision / recall \d+%.<v>%` | `\(original simulator\) \d+%.<v>%.\d+% / \d+%.\d+%.\d+% Message links: precision / recall \(independent` | the row is now labelled "(original simulator)"; the anchor names the row by its neighbours so it matches this row only |
| validation.msg_precision_min | paper/report.html | `Message links: precision / recall <v>%` | `\(original simulator\) <v>%.\d+%.\d+% /` | row now labelled "(original simulator)" |
| validation.msg_precision_max | paper/report.html | `Message links: precision / recall \d+%.\d+%.<v>% /` | `\(original simulator\) \d+%.\d+%.<v>% /` | row now labelled "(original simulator)" |
| validation.identity_low_proposed | paper/report.html | `/ \d+ of \d+ / \d+ of <v> Benign` | `/ \d+ of \d+ / \d+ of <v> Original benign` | "Benign swarms" became "Original benign swarms" |
| validation.identity_low_correct | paper/report.html | `/ \d+ of \d+ / <v> of [\d,]+ Benign` | `/ \d+ of \d+ / <v> of [\d,]+ Original benign` | "Benign swarms" became "Original benign swarms" |
| variance.sigma_low_messages_low | paper/report.html | `σ = 0.12 h gives <v>.\d+ messages` | `σ = 0.12 h gives <v>.\d+ deliveries` | "messages" reworded to "write-then-read deliveries" |
| variance.sigma_low_messages_high | paper/report.html | `σ = 0.12 h gives \d+.<v> messages` | `σ = 0.12 h gives \d+.<v> deliveries` | "messages" reworded to "write-then-read deliveries" |
| variance.sigma_low_messages_low | paper/slides.html | `the \d+ named messages range <v>.\d+ \(95%\)` | `the \d+ named deliveries range <v>.\d+ \(95%\)` | "messages" reworded to "write-then-read deliveries" |
| variance.sigma_low_messages_high | paper/slides.html | `the \d+ named messages range \d+.<v> \(95%\)` | `the \d+ named deliveries range \d+.<v> \(95%\)` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | README.md | `the Swarm Traces release has <v> messages \(` | `The Swarm Traces release has <v> write-then-read deliveries \(\d+ between named tokens\)` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | README.md | `release has \d+ messages \(<v> between named tokens\)` | `The Swarm Traces release has \d+ write-then-read deliveries \(<v> between named tokens\)` | "messages" reworded to "write-then-read deliveries" |
| release.named_pairs | README.md | `Every message between named tokens in the Swarm Traces release \(<v> sender-receiver pairs\)` | `Every write-then-read delivery between named tokens in the Swarm Traces release \(<v> sender-receiver pairs\)` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | paper/slides.html | `in \d+ pairs \(<v> in all\)` | `published <v> write-then-read deliveries, \d+ between \d+ named tokens in \d+ pairs` | sentence rewritten; it now states the total first |
| release.deliveries | paper/slides.html | `\d+ links → <v>; \d+ audited` | `\) \d+ → \d+ → \d+ → <v>; a reviewer defends` | the audit line now shows the whole chain 166 → 19 → 23 → 9; the last number is the current count |
| release.deliveries | paper/slides.html | `through Hugging Face datasets: \d+ of <v> messages` | `through Hugging Face datasets: all <v> deliveries\.` | "22 of 23 messages" became "all 9 deliveries" |
| release.deliveries | paper/slides.html | `<v> messages sit on places the redaction may have merged` | `\d+ of <v> deliveries sit on places the redaction may have merged` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/slides.html | `<v> messages between \d+ named tokens in` | `published \d+ write-then-read deliveries, <v> between \d+ named tokens in` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/slides.html | `\d+ of the <v> messages fall inside one agent` | `likely one agent: \d+ of the <v> named deliveries fall inside one agent` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | paper/slides.html | `with dating error, the <v> named messages range` | `with dating error, the <v> named deliveries range` | "messages" reworded to "write-then-read deliveries" |
| release.named_pairs | paper/slides.html | `messages between \d+ named tokens in <v> pairs` | `named tokens in <v> pairs, all through` | sentence reworded |
| release.named_message_tokens | paper/slides.html | `messages between <v> named tokens` | `deliveries, \d+ between <v> named tokens in \d+ pairs` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries_hf_dataset | paper/slides.html | `through Hugging Face datasets: <v> of \d+ messages` | `through Hugging Face datasets: all <v> deliveries\.` | "22 of 23 messages" became "all 9 deliveries"; prints the hf_dataset count (equal to the total) |
| release.deliveries_on_merged_places | paper/slides.html | `<v> of \d+ messages sit on places the redaction may have merged` | `<v> of \d+ deliveries sit on places the redaction may have merged` | "messages" reworded to "write-then-read deliveries" |
| release.first_message_harm_share | paper/slides.html | `First message between tokens <v>%` | `First delivery between tokens <v>%` | "messages" reworded to "write-then-read deliveries" |
| release.volume_alarm_share | paper/slides.html | `Volume alarm \(baseline\) <v>%` | `Volume alarm \(12 h history\) <v>%` | the row is labelled with its history window |
| release.agent_messages_inside | paper/slides.html | `<v> of the \d+ messages fall inside one agent` | `likely one agent: <v> of the \d+ named deliveries fall inside one agent` | "messages" reworded to "write-then-read deliveries" |
| audit.links | paper/slides.html | `→ \d+; <v> audited, one reader` | `Audit of the release.s links \(<v> read by one reader` | sentence reworded |
| audit.first_count | paper/slides.html | `a first count of <v> fell` | `Counts fell <v> → \d+ → \d+ → \d+ over three audits` | sentence reworded |
| audit.first_count | paper/slides.html | `<v> links → \d+` | `\) <v> → \d+ → \d+ → \d+; a reviewer defends` | the audit line now shows the whole chain |
| validation.benign_runs | paper/slides.html | `Benign swarms: messages between different agents \d+ in <v> runs` | `no delivery between different agents in <v> original runs` | sentence reworded |
| validation.msg_precision_median | paper/slides.html | `Message links: precision / recall \d+.<v>.\d+%` | `original simulator \d+.<v>.\d+% / \d+.\d+.\d+%` | row now labelled "original simulator" |
| validation.msg_recall_median | paper/slides.html | `Message links: precision / recall [^/]+/ \d+.<v>.\d+%` | `original simulator \d+.\d+.\d+% / \d+.<v>.\d+%` | row now labelled "original simulator" |
| validation.msg_recall_max | paper/slides.html | `Message links: precision / recall [^/]+/ \d+.\d+.<v>%` | `original simulator \d+.\d+.\d+% / \d+.\d+.<v>%` | row now labelled "original simulator" |
| release.deliveries | docs/index.html | `messages between named tokens \(<v> in all\)` | `published <v> write-then-read deliveries \(\d+ between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | docs/index.html | `<v> messages between named tokens \(` | `published \d+ write-then-read deliveries \(<v> between named tokens` | "messages" reworded to "write-then-read deliveries" |
| release.deliveries | reports/submission/SUBMISSION.md | `It finds <v> messages, \d+ of them between` | `It finds <v> write-then-read deliveries \(not messages` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | reports/submission/SUBMISSION.md | `It finds \d+ messages, <v> of them between` | `using what was written\), <v> of them between \d+ named tokens in \d+ sender-receiver pairs` | "messages" reworded to "write-then-read deliveries" |
| release.named_deliveries | reports/submission/SUBMISSION.md | `\d+ of the <v> messages fall inside one agent` | `merged into estimated agents, \d+ of the <v> named deliveries fall inside one agent` | "messages" reworded to "write-then-read deliveries" |
| release.agent_messages_inside | reports/submission/SUBMISSION.md | `<v> of the \d+ messages fall inside one agent` | `merged into estimated agents, <v> of the \d+ named deliveries fall inside one agent` | "messages" reworded to "write-then-read deliveries" |
| audit.links | reports/submission/SUBMISSION.md | `after an audit of <v> links` | `after audits of <v> links cut a first count` | sentence reworded |
| audit.first_count | reports/submission/SUBMISSION.md | `cut a first count of <v>\.` | `cut a first count of <v> to 19, then 23, then 9` | the clause now continues with the later counts |
| release.deliveries | docs/assets/demo-script.md | `That leaves <v> messages in all` | `That leaves <v> deliveries in all` | "messages" reworded to "write-then-read deliveries" |
| release.volume_alarm_share | docs/assets/demo-script.md | `A simple volume alarm only fires with <v> percent ahead` | `a volume alarm at <v> percent` | sentence reworded |
| validation.msg_precision_median | docs/assets/demo-script.md | `Median message precision is <v> percent` | `Median precision of the write-then-read links is <v> percent` | sentence reworded |
| audit.first_count | docs/assets/demo-script.md | `A first count said <v>;` | `A first count said <v>, then 19` | sentence reworded |
| release.deliveries | docs/validation.md | `the release shows <v> messages, \d+ between named tokens, precision` | `On the audit the <v> score \d+ of \d+ decidable` | the audit paragraph was rewritten; "On the audit the 9 score 5 of 5 decidable" names the delivery count |
| release.deliveries | docs/validation.md | `the final rules report <v> messages, \d+ between named tokens` | `The v2\.2\.0 rule reports <v> write-then-read deliveries, \d+ between named tokens` | sentence rewritten for v2.2.0 |
| release.named_deliveries | docs/validation.md | `the release shows \d+ messages, <v> between named tokens, precision` | `\\| between two named tokens \\| <v> \\| \d+ of \d+ \\|` | the audit paragraph was rewritten; the score table row for named tokens prints the count |
| release.named_deliveries | docs/validation.md | `the final rules report \d+ messages, <v> between named tokens` | `The v2\.2\.0 rule reports \d+ write-then-read deliveries, <v> between named tokens` | sentence rewritten for v2.2.0 |
| release.named_deliveries | docs/validation.md | `Of the <v> between named tokens all were read as real` | `Of the <v> between named tokens all \d+ were read as a write` | sentence reworded |
| release.audit_reported_true | docs/validation.md | `precision <v> of \d+ on the audit` | `On the audit the \d+ score <v> of \d+ decidable` | the audit paragraph was rewritten |
| release.audit_reported_true | docs/validation.md | `<v> of the \d+ decidable ones judged true` | `\\| all deliveries \\| \d+ \(\d+ unclear\) \\| <v> of \d+ \\|` | the sentence is gone; the score table row prints the count |
| release.audit_decidable | docs/validation.md | `precision \d+ of <v> on the audit` | `On the audit the \d+ score \d+ of <v> decidable` | the audit paragraph was rewritten |
| release.audit_decidable | docs/validation.md | `\d+ of the <v> decidable ones judged true` | `\\| all deliveries \\| \d+ \(\d+ unclear\) \\| \d+ of <v> \\|` | the sentence is gone; the score table row prints the count |
| release.audit_precision | docs/validation.md | `judged true \(precision <v>%` | `\\| all deliveries \\| \d+ \(\d+ unclear\) \\| \d+ of \d+ \\| <v>% \(` | the sentence is gone; the score table row prints the precision |
| release.audit_precision_low | docs/validation.md | `on the audit \(95% range <v>%` | `\(\d+ are unclear; 95% range <v>%` | the audit paragraph was rewritten |
| release.audit_precision_low | docs/validation.md | `\(precision \d+%, 95% range <v>.\d+%` | `\\| all deliveries \\| \d+ \(\d+ unclear\) \\| \d+ of \d+ \\| \d+% \(<v>%` | the sentence is gone; the score table row prints the range |
| release.audit_precision_high | docs/validation.md | `on the audit \(95% range \d+%.<v>%` | `\(\d+ are unclear; 95% range \d+%.<v>%` | the audit paragraph was rewritten |
| release.audit_named_true | docs/validation.md | `all <v> named ones true` | `\\| between two named tokens \\| \d+ \\| <v> of \d+ \\|` | the sentence is gone; the score table row prints the count |
| release.audit_weak_true | docs/validation.md | `, weak <v> of \d+ \(` | `On the audit: weak <v> of \d+ \(` | grade paragraph reworded |
| release.audit_weak_decidable | docs/validation.md | `, weak \d+ of <v> \(` | `On the audit: weak \d+ of <v> \(` | grade paragraph reworded |
| release.second_method_kappa | docs/validation.md | `Cohen's kappa <v>\. It never` | `Cohen.s kappa <v> \(the labels now hold` | sentence reworded |
| audit.links | docs/validation.md | `all <v> deliveries and links are now audited` | `Score on the <v> audited links \(labels as corrected` | the "Update (phase 1)" paragraph is gone; the score paragraph names the links |
| audit.true_links | docs/validation.md | `audited links \(<v> true messages` | `labels as corrected in v2\.2\.0: <v> true, \d+ read-then-post` | sentence reworded |
| audit.read_then_post | docs/validation.md | `true messages, <v> read-then-post` | `\d+ true, <v> read-then-post` | sentence reworded |
| audit.downloads | docs/validation.md | `<v> downloads or urlopen` | `, <v> downloads, urlopen or upload probes` | "downloads or urlopen" became "downloads, urlopen or upload probes" |
| audit.different_repo | docs/validation.md | `urlopen, <v> different repositories` | `upload probes, <v> different repositories` | category renamed |
| audit.unclear | docs/validation.md | `different repositories, <v> unclear\)` | `different repositories, <v> unclear, \d+ reader holding` | a category was added after "unclear" |
| validation.pair_precision_median | docs/validation.md | `recall, \d+%.<v>%.\d+% precision\. On the new` | `recall, \d+%.<v>%.\d+% precision\. On the independent generator` | sentence reworded |
| validation.identity_medium_proposed | docs/validation.md | `medium \d+ of <v>, and the rest` | `medium \d+ of <v>, but the \d+ high ones` | sentence reworded |
| validation.identity_medium_correct | docs/validation.md | `medium <v> of \d+, and the rest` | `medium <v> of \d+, but the \d+ high ones` | sentence reworded |

## Dropped (16)

| value id | file | old anchor | reason |
|---|---|---|---|
| audit.true_links | paper/report.html | `and \d+ of the <v> true ones were made after` | the sentence about labels made after the last rule change (7 of 18) is gone from the report; the report no longer prints the count of true labels at that place |
| release.deliveries | README.md | `the release shows <v> messages, \d+ of them between named tokens` | the sentence "the release shows 23 messages, 6 of them between named tokens (24 until 15 November ...)" is no longer in the README; its value is still printed by the next entry |
| release.named_deliveries | README.md | `the release shows \d+ messages, <v> of them between named tokens` | same sentence as above, gone from the README; the value is still printed by the next entry |
| audit.links | paper/slides.html | `fell after auditing <v> links` | the sentence "a first count of 166 fell after auditing 258 links" is gone; 258 is still printed by the next entry |
| validation.total_runs | paper/slides.html | `Scored on <v> simulated swarms` | the slide title "Scored on 60 simulated swarms with known answers" is gone; no slide prints 60 swarms any more |
| validation.benign_messages_between_agents_max | paper/slides.html | `Benign swarms: messages between different agents <v> in` | the slide now says "no delivery between different agents in 15 original runs": the value 0 is printed as the word "no", which no registered format reads; the value is still registered at the report and validation.md places |
| audit.links | docs/index.html | `after auditing <v> links` | the sentence now reads "The submitted report said 19 and v2.1.0 said 23; the audit labels are one reader's"; 258 is not printed in the page any more |
| release.deliveries | docs/validation.md | `What the release now shows \(final rules, phase 1\): <v> messages` | the sentence now reads "What the release showed at v2.1.0 (final rules, phase 1): 23 messages": it prints the v2.1.0 count, labelled as history, not the current one |
| release.deliveries | docs/validation.md | `The release now shows <v> deliveries, \d+ of them between named tokens` | anchor for a sentence that is not in the page; the current count is printed by the re-pointed "The v2.2.0 rule reports" entry |
| release.named_deliveries | docs/validation.md | `phase 1\): \d+ messages, <v> of them between named tokens` | prints the v2.1.0 count (6), labelled as history ("showed at v2.1.0"), not the current one |
| release.named_deliveries | docs/validation.md | `shows \d+ deliveries, <v> of them between named tokens` | anchor for a sentence that is not in the page; the current count is printed by the re-pointed entries |
| release.named_pairs | docs/validation.md | `of them between named tokens \(<v> pairs\)` | prints the v2.1.0 pair count (5), labelled as history; the current count (4 pairs) is printed by "Result: 9 write-then-read deliveries, 4 between named tokens in 4 pairs" and registered through the report and README |
| release.audit_inferred_true | docs/validation.md | `On the audit: inferred <v> of` | the grade paragraph now reports only "On the audit: weak 5 of 5"; no inferred-grade audit result is printed |
| audit.true_links | docs/validation.md | `\d+ of the <v> true labels were made after` | the sentence "7 of the 18 true labels were made after the last rule change" is gone; the page now prints 18 only as the v2.1.0 count |
| audit.unclear | docs/validation.md | `<v> links are unclear, and it calls` | the sentence "27 links are unclear, and it calls 4 of them messages" is gone |
| repo.version | reports/submission/SUBMISSION.md | `release v<v>:` | The line links the GitHub release page `releases/tag/v2.1.0`, the last published release, on purpose (there is no v2.2.0 tag); it does not state the package version, which is now 2.2.0. Found by `build` after the re-pointing, not in the original 122. |

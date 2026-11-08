# analyzer

Analyze any CSV of agent records: tags, stages, handles, threads, near-duplicate families, and gaps. Writes one HTML report plus CSV and JSON. Stdlib only.

## Run it

From the project root:

```bash
python3 -I analyzer/analyze.py data.csv --out reports/mydata
```

Column names default to `id`, `text`, `kind`, `parent_id`, `time_utc`. Use flags for anything else:

```bash
python3 -I analyzer/analyze.py chat.csv --out reports/chat \
    --id-col msg_id --text-col body --kind-col sender \
    --parent-col reply_to --time-col sent_at --title "Chat export"
```

Only `id` and `text` are required. Other columns are optional and produce blank or "none" results where missing.

## What you get in `--out`

- `report.html`: open this. Profile, stages, behaviors, co-occurring behavior pairs, handles, threads, families, and gaps.
- `summary.json`: the same numbers, for scripts.
- `records.csv`: one row per record with its tags, stages, handles, thread root, and family. Filter this in any spreadsheet.
- `behaviors.csv`, `stages.csv`, `handles.csv`, `pairs.csv`, `threads.csv`, `families.csv`.

## Rules

Behavior tags and handles come from a JSON rules file, `--rules` (default `analyzer/rules/default.json`). A rule is:

```json
{"name": "http_post", "stage": "exfiltration", "pattern": "method:\\s*'POST'", "description": "Sends data with POST", "flags": "i"}
```

- `pattern` is a Python regular expression.
- `stage` groups behaviors into a higher-level category, shown in the Stages table.
- `flags: "i"` makes it case-insensitive.

To analyze a new kind of data, copy `default.json` and replace the patterns. The default rules are for code-like agent traces. A chat export will match almost nothing with them, which is correct: the rules describe what you're looking for.

## What the numbers mean

- **Tags** say what the text would do, judged by patterns. They are not verified behavior. Check precision on a random sample before you rely on a rule.
- **Families** group records whose normalized text is identical or nearly identical (up to 6 of 64 bits differing in a SimHash). Ids, numbers and hex are masked before comparison. Family boundaries are approximate.
- **Threads** follow `parent` links up to a root. A record whose parent is missing counts as its own root.
- **Gaps** list what the data cannot answer: missing timestamps, missing parents, redaction placeholders, unattributed records, and records no rule matched.

## Worked example

`test_data/chat_sample.csv` is a 300-row synthetic chat with different column names. Run the command above on it to see the column flags in use. No default rule matches it, so the report shows 0% tagged. That is the expected result for these rules.

## Runtime

About one minute for the 189,579-record Swarm Traces release on a laptop. Most of the time goes to the family step.

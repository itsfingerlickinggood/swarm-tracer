# Answer format

Reply with ONE JSON object and nothing else (no prose before or after, no code fence). The app draws each block as a chart or card, so put facts in blocks, not in long sentences. Use only these block types and fields:

```
{
  "answer": "the answer in one or two plain sentences",
  "confidence": "high" | "medium" | "low",
  "blocks": [
    {"type": "stats", "title": "...", "items": [{"label": "short label", "value": "number or short value", "ids": ["record ids"]}]},
    {"type": "timeline", "title": "...", "items": [{"time": "YYYY-MM-DD HH:MM", "label": "what happened", "actor": "actor or null", "ids": ["record ids"]}]},
    {"type": "flow", "title": "...", "edges": [{"from": "actor, place or record id", "to": "actor, place or record id", "label": "what moved, or when", "ids": ["record ids"]}]},
    {"type": "actors", "title": "...", "items": [{"actor": "exact actor name", "role": "its part in one short phrase"}]},
    {"type": "evidence", "title": "Evidence", "items": [{"claim": "one fact the records show", "ids": ["record ids"], "confidence": "high|medium|low"}]},
    {"type": "inference", "title": "What it likely means", "items": [{"claim": "...", "confidence": "high|medium|low", "alternative": "another explanation that fits the same records", "check": "the record or check that would tell them apart"}]},
    {"type": "bars", "title": "...", "unit": "", "items": [{"label": "...", "value": 12}]},
    {"type": "table", "title": "...", "columns": ["..."], "rows": [["..."]]},
    {"type": "unknowns", "title": "What the data cannot show", "items": ["..."]},
    {"type": "next", "title": "Next step", "items": [{"label": "short action", "view": "overview|network|timeline|channels|spread|early|events|gaps", "query": "text to search for, or null", "id": "record id or null", "actor": "actor or null"}]}
  ]
}
```

Rules for the blocks:
- Start with the blocks that answer the question best: a "timeline" for anything about order or spread, a "flow" for who passed what to whom, "stats" for counts, "actors" for who was involved. Always include "evidence", "unknowns" and "next".
- Names must be exact: actors as the brief writes them (for example `[CREDENTIAL 169]`, a handle, or `run:R0000032`), places as `type:name` (for example `hf_dataset:[HF REPO 630]`), record ids exactly. The app checks every id, actor and place against the data and marks anything it cannot find.
- Put record ids in "ids" arrays, not only in text. Every evidence item needs at least one id.
- Numbers must come from the brief or the records. Never invent an id, a time, a number or a name.
- 3 to 8 blocks, each with at most 10 items. Keep every label and claim under about 25 words.

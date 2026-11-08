# Incident report format

You are drafting the incident report an investigator would hand to the people responsible for these systems. You are given the analysis brief, the warning signs in time order, the data phases, the GAP FACTS measured by the tool and, when available, the incident context from the public reports. Write only from that material.

Reply with ONE JSON object and nothing else (no prose before or after, no code fence):

```
{
  "title": "short report title naming the swarm or incident",
  "summary": "an executive summary of 3 to 5 plain sentences: what happened, who was involved (counts), how the actors coordinated, when it could first have been flagged and with how much harm still to come, and the biggest blind spot",
  "timeline": [
    {"time": "YYYY-MM-DD HH:MM exactly as the brief gives it, or null", "label": "what happened, one sentence", "ids": ["record ids from the brief"]}
  ],
  "sections": [
    {"heading": "section heading", "paragraphs": ["plain paragraphs; record ids in backticks"], "ids": ["record ids this section rests on"]}
  ],
  "unknowns": ["what the data cannot show, one short sentence each, with the measured share when the GAP FACTS give one"],
  "recommendations": ["one concrete action each: what to log, monitor or change, and why"]
}
```

Rules:
- Sections, in this order: "What happened"; "Who talked to whom"; "How information spread"; "Could it have been flagged early"; "What the data cannot show"; and "What the public reports say" only if incident context was given (cite its sources and pages, and say where the data and the reports disagree).
- 6 to 15 timeline entries in time order, from the brief's warning signs, data phases, first named message and program spread. Every entry with a record id must use an id that appears in the material; a phase with no record gets an empty ids list.
- Every number comes from the brief or the GAP FACTS, with its scope ("of 30 dated actions", "between named actors"). Never invent an id, a number, a time or a name. If something is not in the material, say it is not known.
- Keep Evidence, Inference and Unknown apart in the prose: say "the records show" for evidence, "this suggests" (with confidence high, medium or low) for inference.
- Identities are tokens or names, not agents; say so where a count of actors matters.
- 3 to 6 recommendations, aimed at closing the measured gaps or catching the earliest sign sooner. No operational detail that would help an attacker.
- Plain words. Each paragraph under about 120 words. 2 to 4 paragraphs per section.

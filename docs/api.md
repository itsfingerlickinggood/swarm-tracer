# HTTP API

[Home](./) · [Command line](cli.md)

The app talks to its own server on `127.0.0.1` only. Requests must come from the app itself: other web pages and non-local host names are refused. Everything returns JSON; errors are `{"error": "…"}` with HTTP 400 (bad input), 404 or 409 (nothing loaded / not found).

## Dataset

| | |
|---|---|
| `GET /api/packs` | packs available, and the AI defaults |
| `GET /api/state` | the loaded dataset's summary, or `{"loaded": false}` |
| `POST /api/upload?filename=&pack=&map=` | analyze one file (the request body) |
| `POST /api/stage?batch=&filename=` then `POST /api/analyze?batch=&pack=&name=` | analyze a folder, one file at a time |

## Analysis

| | |
|---|---|
| `GET /api/events?q=&kind=&actor=&intent=&tag=&hour=&channels=1&offset=&limit=` | records, with facets and an hourly histogram of the matches |
| `GET /api/event?id=` | one record traced and explained (`explain`), with the spans that set each reading (`why`) |
| `GET /api/actor?a=` · `GET /api/place?ch=` | an actor's or a place's profile |
| `GET /api/pairs` · `GET /api/conversation?a=&b=` | every sender-receiver pair; the whole conversation between two actors |
| `GET /api/messages` · `GET /api/lanes` · `GET /api/places_map` · `GET /api/spread` | every message, swimlanes, every place, every shared program |
| `GET /api/sim` | the hour-by-hour replay and every warning sign |
| `GET /api/context` | the incident context file that matches, with the milestone check |
| `GET /api/gaps` | measured blind spots |
| `GET /api/search?q=` | actors, places and records for the search box |
| `GET /api/list?name=&q=&offset=&limit=` | any full list (identities, channels, content_spread, seen_then_used, carried_edges, shared_places, overwrites…) |

## Features (`/api/x/…`)

| | |
|---|---|
| `GET formats` · `POST pack_suggest?filename=` · `POST pack_save` | detected formats; propose a pack from a sample; save one |
| `GET identity[?actor=]` · `GET roles` · `POST identity_decide` | merge proposals, groups and the agent estimate; roles; accept or reject a proposal |
| `POST live_start {path, pack, interval_s}` · `GET live_status?cursor=` · `POST live_stop` | live mode |
| `GET rules` · `POST rules` · `GET rules_eval` | alert rules |
| `GET case` · `POST case` · `GET case_export?format=html\|json` | the case file |
| `POST label` · `GET labels` · `GET precision` | labels from the Inspector, and live precision |
| `GET validation_summary[?which=quick]` · `POST validation_run` | the latest validation suite results; run a quick one |
| `GET groundtruth_score` · `POST groundtruth_truth` · `GET time_range?id=` | scores against a truth file; a record's likely time range |
| `GET fx_trace?q=` · `fx_credentials` · `fx_c2` · `fx_c2_place?ch=` · `fx_drops` · `fx_drops_csv` · `fx_search?q=` · `fx_like?id=` | Forensics: follow the evidence |
| `GET fx_evolution` · `fx_evolution_cluster?id=` · `fx_evolution_diff?id=&version=` · `fx_stages` · `fx_leadlag` · `fx_anomalies` · `fx_story[?format=md]` | Forensics: how agents behaved |
| `GET fx_whatif` · `POST fx_whatif_decide` · `GET fx_reference` · `fx_custody` · `fx_export?format=timeline_csv\|timesketch_csv\|stix\|detections` | Forensics: test and export |
| `POST compare_load {path, pack} \| {library}` · `GET compare` · `GET compare_state` · `POST compare_clear` · `GET library` | comparing two swarms |

## AI investigator

| | |
|---|---|
| `POST /api/ai {messages, apiKey, baseUrl, model, mode, selected, selectedId, conversation, sessionId}` | `mode`: `chat`, `gaps` or `report`; returns `content` and, when the reply follows the answer format, `structured` with every id checked |
| `POST /api/ai/check` · `POST /api/ai/models` | prove the endpoint, key and model work; list models |

New features add routes in their own module through `agenttrace/extensions.py`, without touching the server.

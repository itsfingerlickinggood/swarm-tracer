# Command line

[Home](./) · [Getting started](getting-started.md)

`swarm-tracer` (after `pipx install`) and `python3 -m agenttrace` (from a clone) are the same command.

| Command | What it does |
|---|---|
| `serve [--input PATH] [--pack PACK] [--port 8010] [--map role=field]` | run the app on 127.0.0.1; preload a file or folder |
| `demo [--port] [--no-browser]` | serve the bundled simulated swarm |
| `evaluate PATH --pack PACK --out DIR` | baselines, robustness under time error, counting rules, the external timing check, report figures |
| `analyze PATH --pack PACK --out DIR` | a static HTML report, `summary.json` and `records.csv` |
| `flow PATH --pack PACK --out DIR` | message flow: `flow.json` and every message in `deliveries.csv` |
| `claims PATH --pack PACK --claims FILE --out DIR` | check a published report's claims against the traces |
| `compare A B [--json]` | the same measures for two swarms side by side, and what differs |
| `library` | known incidents and datasets, and whether each is on this machine |
| `sample PATH --pack PACK --out FILE` | records to label for precision |
| `precision LABELS.csv` | precision and recall from labels |

Other tools:

```bash
# a simulated swarm with known message links, then score the tool against it
python3 -m agenttrace.groundtruth make out/ --agents 40 --seed 1
python3 -m agenttrace.groundtruth score out/

# replay a recorded trace into a growing file, to try live mode
python3 -m agenttrace.tools.replay_feed redacted.jsonl /tmp/feed.jsonl --rate 2000

# the hackathon report PDF (recapture the app figures from a running app with --capture URL)
python3 paper/build.py --author "Name" --affiliation "Affiliation"
```

Environment: `SWARM_TRACER_HOME` (default `~/.swarm-tracer`: case files, labels, rules, identity decisions), `SWARM_TRACER_NO_CACHE=1` (no disk cache), `SWARM_TRACER_CACHE_DIR`, `SWARM_TRACER_DATA` (where the library looks for datasets).

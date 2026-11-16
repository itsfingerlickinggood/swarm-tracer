"""Saved results of slow self-checks (agenttrace/claims/simulated_checks.json), so the app shows numbers that
were measured and dated, not numbers typed into the code. Each module's `simulate_check()` produces one entry;
`python3 -m agenttrace.saved` re-measures all of them and rewrites the file (about a minute)."""
import datetime as dt
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims", "simulated_checks.json")
CHECKS = {"fx_content": "fx_content", "fx_coord": "fx_coord"}


def load(name, default_args=None):
    """The saved entry for a module, or an entry that says it was not measured (the views print that)."""
    try:
        with open(PATH, encoding="utf-8") as f:
            entry = json.load(f).get(name)
        if isinstance(entry, dict) and entry.get("measured"):
            return entry
    except (OSError, ValueError):
        pass
    return {**(default_args or {"agents": 40, "seeds": [1, 2, 3]}), "measured": None,
            "note": "not measured: run python3 -m agenttrace.saved to measure it"}


def remeasure(only=None):
    import importlib
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    for name in only or CHECKS:
        mod = importlib.import_module("agenttrace." + CHECKS[name])
        entry = mod.simulate_check()
        entry["measured"] = dt.date.today().isoformat()
        entry["measured_by"] = f"agenttrace.{CHECKS[name]}.simulate_check()"
        data[name] = entry
        print(name, json.dumps(entry))
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    import sys
    remeasure(sys.argv[1:] or None)

"""Ground-truth test mode: a simulated swarm whose messages are known, and a score of the tool on it.

    python3 -m agenttrace.groundtruth make out/ --agents 40 --seed 1     # writes out/trace.jsonl + out/trace.jsonl.truth
    python3 -m agenttrace.groundtruth score out/                         # loads it with the tool, prints precision/recall

The simulated swarm (code-like payloads in the style of the code_traces pack):
- N agents, each authenticating with its own identity token ("Bearer [CREDENTIAL k]"); some agents hold
  two tokens and switch between them, so the tool sees two actors where there is one agent.
- Shared places: registry folders used as message boards (github-remote-cache/zzNAME) and datasets
  (huggingface.co/datasets/owner/name). A write leaves a message; a read fetches one named message
  (often the newest, sometimes an older one), so every true message is a known (write, read) pair.
- A quiet stretch of solo work first, then agents join the coordination one by one, then harm
  (cloud metadata and cluster calls) on top.
- Noise: notes that name a place without reading it, reads whose address is built from pieces the
  patterns cannot see, timestamps embedded in only some of the code (the rest are estimated), or in a
  time field.

The truth file (JSON) holds every agent's tokens, every record's agent and true time, the true
messages, and the harmful records. score() compares what the tool found with it.
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
from collections import Counter, defaultdict

UTC = dt.timezone.utc
TRUTH_EXT = ".truth"
WORDS = ["alpha", "bravo", "cedar", "delta", "ember", "falcon", "garnet", "harbor", "iris", "juniper", "kestrel",
         "lumen", "maple", "nectar", "onyx", "pebble", "quartz", "raven", "sable", "tundra", "umber", "violet",
         "willow", "xenon", "yarrow", "zephyr"]
VERBS = ["parse", "rank", "merge", "score", "split", "index", "patch", "sort", "clean", "fold", "probe", "trim"]
NOUNS = ["matrix", "graph", "queue", "ledger", "corpus", "buffer", "schema", "tensor", "cache", "router", "lexer"]


def _iso(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ make

def make(out_dir, agents=40, seed=1, hours=36, time_mode="embedded", two_token_share=0.12,
         hidden_share=0.08, mention_share=0.06, start="2026-07-03", name="trace.jsonl", mode="coordinated",
         own_writes=0.5):
    """Write <name> (default trace.jsonl) and <name>.truth into out_dir. Returns the truth dict.

    mode "coordinated" (default) is the swarm described above. mode "benign" is a baseline with no
    coordination at all: agents work in parallel on their own tasks, may read public datasets nobody in
    the swarm writes, and (a share own_writes of them) save results to a dataset of their own and read
    them back. No agent reads what another wrote, no token is carried, and the only program shared by
    several agents is the common submit boilerplate. Its truth has no messages and no harmful records.
    """
    if mode not in ("coordinated", "benign"):
        raise ValueError("mode must be coordinated or benign")
    if time_mode not in ("embedded", "field"):
        raise ValueError("time_mode must be embedded or field")
    if mode == "benign":
        return _make_benign(out_dir, agents, seed, hours, time_mode, two_token_share, mention_share, start, name,
                            own_writes)
    rng = random.Random(seed)
    t_start = dt.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
    span = hours * 3600.0
    n = max(2, int(agents))
    creds = list(range(2, 2 + 3 * n))
    rng.shuffle(creds)
    names = [f"agent-{i + 1:02d}" for i in range(n)]
    tokens = {}
    for a in names:
        k = 2 if rng.random() < two_token_share else 1
        tokens[a] = [f"[CREDENTIAL {creds.pop()}]" for _ in range(k)]
    n_boards, n_sets = max(2, n // 8), max(2, n // 12)
    boards = ["zz" + WORDS[i % len(WORDS)].upper() + ("_BOARD" if i < len(WORDS) else f"_BOARD{i}") for i in range(n_boards)]
    sets = [f"swarmhub/ds-{WORDS[(i + 7) % len(WORDS)]}{'' if i < len(WORDS) else i}" for i in range(n_sets)]
    places = [("board", b) for b in boards] + [("dataset", d) for d in sets]
    t_coord, t_harm = 0.25 * span, 0.5 * span

    # plan every action: (time, agent, what, place)
    plan = []
    for a in names:
        for _ in range(rng.randint(6, 14)):
            plan.append((rng.uniform(0, span), a, "solo", None))
        if rng.random() < 0.8:      # a coordinating agent
            join = rng.uniform(t_coord, 0.7 * span)
            home = rng.sample(places, 2 if rng.random() < 0.5 else 1)
            for _ in range(rng.randint(10, 24)):
                t = rng.uniform(join, span)
                p = rng.choice(home) if rng.random() < 0.85 else rng.choice(places)
                r = rng.random()
                if r < 0.4:
                    plan.append((t, a, "write", p))
                elif r < 0.85:
                    plan.append((t, a, "read", p))
                elif t >= t_harm:
                    plan.append((t, a, rng.choice(["metadata", "cluster"]), None))
                else:
                    plan.append((t, a, "read", p))
            # the first act of a joining agent is a write, so every coordinator leaves a message
            plan.append((join, a, "write", home[0]))
        for _ in range(max(0, int(round(rng.gauss(mention_share * 20, 1)))) if mention_share > 0 else 0):
            plan.append((rng.uniform(0, span), a, "mention", rng.choice(places)))
    plan.sort(key=lambda x: x[0])

    # simulate in time order: messages on each place, and which one each read fetches
    rid_n = [1000000]

    def rid():
        rid_n[0] += 1
        return f"R{rid_n[0]}"

    posted = defaultdict(list)   # place -> [(write_id, agent, msg name)]
    session = {}                 # agent -> (thread root, last record, actions left in this session)
    payloads, truth_records, messages, harm = [], {}, [], []
    got = set()
    for t, a, what, p in plan:
        tok = rng.choice(tokens[a]) if len(tokens[a]) > 1 else tokens[a][0]
        r = rid()
        root, last, left = session.get(a, (None, None, 0))
        if left <= 0:
            root, last, left = r, None, rng.randint(4, 9)
        session[a] = (root, r, left - 1)
        ts = t_start + t
        info = {"agent": a, "t": round(ts, 1), "token": tok, "do": what}
        text = _payload(rng, what, p, tok, ts, a, posted, r, info, hidden_share, time_mode)
        if what == "read" and info.get("got"):
            w = info["got"]
            key = (w, a)
            if key not in got:      # reading the same message again is one message
                got.add(key)
                messages.append([w, r, f"{p[0]}:{p[1]}"])
        if what in ("write", "read", "metadata", "cluster") and not (what == "read" and p[0] == "dataset"):
            harm.append(r)
        truth_records[r] = info
        payloads.append({"id": r, "kind": "payload", "parent": last, "text": text, "_t": ts, "_a": a})

    responses = _responses(rng, payloads, truth_records, rid)
    path = _write_rows(out_dir, name, payloads, responses, time_mode)
    truth = {
        "about": "Ground truth for a simulated agent swarm written by agenttrace.groundtruth. "
                 "messages: [write record, read record, place]; records: each record's agent and true time.",
        "version": 1, "pack": "code_traces.json", "mode": "coordinated",
        "params": {"agents": n, "seed": seed, "hours": hours, "time_mode": time_mode, "two_token_share": two_token_share,
                   "hidden_share": hidden_share, "mention_share": mention_share, "start": start, "mode": "coordinated"},
        "trace": name,
        "agents": tokens,
        "places": [f"{k}:{v}" for k, v in places],
        "coordination_from": _iso(t_start + t_coord), "harm_from": _iso(t_start + t_harm),
        "records": truth_records,
        "messages": messages,
        "harm": harm,
    }
    with open(path + TRUTH_EXT, "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=0)
    return truth


def _responses(rng, payloads, truth_records, rid):
    """What came back, as children of their payload (not actions)."""
    responses = []
    for pl in payloads:
        if rng.random() < 0.55:
            info = truth_records[pl["id"]]
            body = {"ok": True}
            if info.get("got"):
                body = {"ok": True, "message": f"status from the {info['place'].split(':', 1)[1]} crew, step {rng.randint(1, 99)}"}
            r = rid()
            responses.append({"id": r, "kind": "response", "parent": pl["id"], "text": json.dumps(body), "_t": pl["_t"] + 2})
            truth_records[r] = {"agent": pl["_a"], "t": round(pl["_t"] + 2, 1), "do": "response"}
    return responses


def _write_rows(out_dir, name, payloads, responses, time_mode):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        if time_mode == "field":    # payload, then its response, in time order
            by_parent = {x["parent"]: x for x in responses}
            rows = []
            for pl in payloads:
                rows.append(pl)
                if pl["id"] in by_parent:
                    rows.append(by_parent[pl["id"]])
        else:                        # one block of payloads, then one of responses (as code traces are kept)
            rows = payloads + responses
        for x in rows:
            out = {"id": x["id"], "kind": x["kind"], "parent": x["parent"], "text": x["text"]}
            if time_mode == "field":
                out["time_utc"] = _iso(x["_t"])
            f.write(json.dumps(out) + "\n")
    return path


def _make_benign(out_dir, agents, seed, hours, time_mode, two_token_share, mention_share, start, name, own_writes):
    """A swarm that never coordinates (see make). Same record shapes as the coordinated swarm."""
    rng = random.Random(seed)
    t_start = dt.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
    span = hours * 3600.0
    n = max(2, int(agents))
    creds = list(range(2, 2 + 3 * n))
    rng.shuffle(creds)
    names = [f"agent-{i + 1:02d}" for i in range(n)]
    tokens = {}
    for a in names:
        k = 2 if rng.random() < two_token_share else 1
        tokens[a] = [f"[CREDENTIAL {creds.pop()}]" for _ in range(k)]
    public = [f"openbench/{WORDS[i % len(WORDS)]}-reference{'' if i < len(WORDS) else i}" for i in range(max(2, n // 10))]
    own = {a: f"results-{a}/{WORDS[i % len(WORDS)]}-runs" for i, a in enumerate(names) if rng.random() < own_writes}

    plan = []
    for a in names:
        for _ in range(rng.randint(2, 4)):              # work sessions spread over the whole span, in parallel
            s0 = rng.uniform(0, span * 0.9)
            for _ in range(rng.randint(4, 9)):
                t = min(span, s0 + rng.uniform(0, 2.5 * 3600))
                r = rng.random()
                if r < 0.15:
                    plan.append((t, a, "public_read", rng.choice(public)))
                elif a in own and r < 0.30:
                    plan.append((t, a, "own_write", own[a]))
                elif a in own and r < 0.40:
                    plan.append((t, a, "own_read", own[a]))
                else:
                    plan.append((t, a, "solo", None))
        for _ in range(max(0, int(round(rng.gauss(mention_share * 20, 1)))) if mention_share > 0 else 0):
            plan.append((rng.uniform(0, span), a, "mention", rng.choice(public + ([own[a]] if a in own else []))))
    plan.sort(key=lambda x: x[0])

    rid_n = [1000000]

    def rid():      # B, not R: a benign truth file must never match a coordinated swarm's record ids
        rid_n[0] += 1
        return f"B{rid_n[0]}"

    posted = defaultdict(list)
    session = {}
    payloads, truth_records, self_msgs = [], {}, []
    for t, a, what, p in plan:
        tok = rng.choice(tokens[a])
        r = rid()
        root, last, left = session.get(a, (None, None, 0))
        if left <= 0:
            root, last, left = r, None, rng.randint(4, 9)
        session[a] = (root, r, left - 1)
        ts = t_start + t
        info = {"agent": a, "t": round(ts, 1), "token": tok, "do": what}
        stamp = f"const startedAt = {int(ts)};\n" if time_mode == "embedded" and rng.random() < 0.6 else ""
        auth = f"'Authorization': 'Bearer {tok}'"
        v, nn = rng.choice(VERBS), rng.choice(NOUNS)
        if what == "solo":
            text = _payload(rng, "solo", None, tok, ts, a, posted, r, info, 0, "field")   # no stamp from there
            text = stamp + text
        elif what == "mention":
            info["place"] = "dataset:" + p
            text = (f"{stamp}// reference: huggingface.co/datasets/{p} has the baseline numbers; not needed for this step\n"
                    f"const res = await fetch('https://eval.example.org/api/status', {{headers: {{{auth}}}}});\nconsole.log(res.status);")
        elif what == "public_read":
            info["place"] = "dataset:" + p
            text = (f"{stamp}const ref = await fetch('https://huggingface.co/datasets/{p}/resolve/main/{rng.choice(NOUNS)}.json', "
                    f"{{headers: {{{auth}}}}});\nconsole.log('{v}', (await ref.json()).length);")
        elif what == "own_write":
            info["place"] = "dataset:" + p
            mid = f"run_{r[1:]}"
            posted[p].append((r, a, mid))
            info["wrote"] = mid
            text = (f"{stamp}await fetch('https://huggingface.co/api/datasets/{p}/commit/main', {{method: 'POST', headers: {{{auth}, "
                    f"'Content-Type': 'application/x-ndjson'}}, body: JSON.stringify({{operation: 'upload', path: '{mid}.json', "
                    f"content: '{v} {nn} score'}})}});")
        else:   # own_read: the agent reads back its own latest result
            info["place"] = "dataset:" + p
            mine = posted[p][-1] if posted[p] else None
            mid = mine[2] if mine else "README"
            if mine:
                info["got_own"] = mine[0]
                self_msgs.append([mine[0], r, "dataset:" + p])
            text = (f"{stamp}const prev = await fetch('https://huggingface.co/datasets/{p}/resolve/main/{mid}.json', "
                    f"{{headers: {{{auth}}}}});\nconsole.log('{nn}', await prev.json());")
        truth_records[r] = info
        payloads.append({"id": r, "kind": "payload", "parent": last, "text": text, "_t": ts, "_a": a})
    responses = _responses(rng, payloads, truth_records, rid)
    path = _write_rows(out_dir, name, payloads, responses, time_mode)
    truth = {
        "about": "Ground truth for a BENIGN simulated agent swarm written by agenttrace.groundtruth: agents work in "
                 "parallel on their own tasks and never coordinate, so there are no true messages between agents and "
                 "no harmful records. self_messages: an agent reading back what it wrote itself (not a message).",
        "version": 1, "pack": "code_traces.json", "mode": "benign",
        "params": {"agents": n, "seed": seed, "hours": hours, "time_mode": time_mode, "two_token_share": two_token_share,
                   "hidden_share": 0, "mention_share": mention_share, "start": start, "mode": "benign",
                   "own_writes": own_writes},
        "trace": name,
        "agents": tokens,
        "places": ["dataset:" + p for p in public] + ["dataset:" + p for p in own.values()],
        "public_places": ["dataset:" + p for p in public],
        "own_places": {a: "dataset:" + p for a, p in own.items()},
        "coordination_from": None, "harm_from": None,
        "records": truth_records,
        "messages": [],
        "self_messages": self_msgs,
        "harm": [],
    }
    with open(path + TRUTH_EXT, "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=0)
    return truth


def _payload(rng, what, p, tok, ts, agent, posted, r, info, hidden_share, time_mode):
    """The code one action runs. Records the true place operation in info."""
    stamp = ""
    if time_mode == "embedded" and rng.random() < 0.6:
        stamp = f"const startedAt = {int(ts)};\n"
    auth = f"'Authorization': 'Bearer {tok}'"
    v, nn = rng.choice(VERBS), rng.choice(NOUNS)
    if what == "solo":
        return (f"// {v} the {nn} for task {rng.randint(1, 400)}\n{stamp}"
                f"const res = await fetch('https://eval.example.org/api/submit', {{method: 'POST', headers: {{'x-api-key': '[CREDENTIAL 1]', {auth}}}, "
                f"body: JSON.stringify({{function_name: '{v}_{nn}', submitted_code: 'def {v}_{nn}(x): return x'}})}});\nconsole.log(await res.status);")
    if what == "metadata":
        return (f"{stamp}const meta = await fetch('http://169.254.169.254/latest/meta-data/iam/', {{headers: {{{auth}}}}});\n"
                f"console.log('{v}', await meta.text());")
    if what == "cluster":
        return (f"{stamp}const pods = await fetch('https://10.0.0.1/api/v1/namespaces/kube-system/pods', {{headers: {{{auth}}}}});\n"
                f"console.log('{nn}', (await pods.json()).items.length);")
    kind, name = p
    place = f"{kind}:{name}"
    info["place"] = place
    if what == "mention":
        info["do"] = "mention"
        where = f"pkg.example.net/artifactory/github-remote-cache/{name}" if kind == "board" else f"huggingface.co/datasets/{name}"
        return (f"{stamp}// notes for later: the crew says {where} has the plan; not fetching it yet\n"
                f"const res = await fetch('https://eval.example.org/api/status', {{headers: {{{auth}}}}});\nconsole.log(res.status);")
    if what == "write":
        mid = f"msg_{r[1:]}"
        posted[place].append((r, agent, mid))
        info["wrote"] = mid
        if kind == "board":
            return (f"{stamp}await fetch('https://pkg.example.net/artifactory/github-remote-cache/{name}/', {{method: 'MKCOL', headers: {{{auth}}}}});\n"
                    f"await fetch('https://pkg.example.net/artifactory/github-remote-cache/{name}/{mid}', {{method: 'PUT', headers: {{{auth}}}, body: '{v} {nn} next'}});")
        return (f"{stamp}await fetch('https://huggingface.co/api/datasets/{name}/commit/main', {{method: 'POST', headers: {{{auth}, 'Content-Type': 'application/x-ndjson'}}, "
                f"body: JSON.stringify({{operation: 'upload', path: '{mid}.json', content: '{v} {nn}'}})}});")
    # read: fetch one message left by another agent, usually the newest
    cands = [m for m in posted[place] if m[1] != agent][-3:]
    pick = None
    if cands:
        pick = cands[-1] if rng.random() < 0.7 else rng.choice(cands)
        info["got"] = pick[0]
    mid = pick[2] if pick else "index"
    if rng.random() < hidden_share:
        info["hidden"] = True
        if kind == "board":
            return (f"{stamp}const base = 'https://pkg.example.net/artifactory/github-remote-' + 'cache/';\n"
                    f"const m = await fetch(base + 'zz' + '{name[2:]}/{mid}', {{headers: {{{auth}}}}});\nconsole.log(await m.text());")
        owner, ds = name.split("/", 1)
        return (f"{stamp}const hub = 'https://huggingface' + '.co/data' + 'sets/';\n"
                f"const m = await fetch(hub + '{owner}' + '/' + '{ds}/resolve/main/{mid}.json', {{headers: {{{auth}}}}});\nconsole.log(await m.json());")
    if kind == "board":
        return (f"{stamp}const m = await fetch('https://pkg.example.net/artifactory/github-remote-cache/{name}/{mid}', {{headers: {{{auth}}}}});\n"
                f"console.log('{v}', await m.text());")
    return (f"{stamp}const m = await fetch('https://huggingface.co/datasets/{name}/resolve/main/{mid}.json', {{headers: {{{auth}}}}});\n"
            f"console.log('{nn}', await m.json());")


# ------------------------------------------------------------------ finding the truth for a loaded dataset

def load_truth(path):
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    if not isinstance(t, dict) or "messages" not in t or "records" not in t:
        raise ValueError(f"{path} is not a ground-truth file (needs records and messages)")
    return t


def truth_path_for(source):
    """The truth file next to a trace file or inside a trace folder, or None."""
    if not source:
        return None
    if os.path.isfile(source + TRUTH_EXT):
        return source + TRUTH_EXT
    d = source if os.path.isdir(source) else os.path.dirname(source)
    if os.path.isdir(d):
        found = sorted(f for f in os.listdir(d) if f.endswith(TRUTH_EXT))
        if found:
            return os.path.join(d, found[0])
    return None


def matches(truth, s):
    """True when the truth describes this loaded dataset: its payload ids are the dataset's records."""
    ids = [r for r, x in truth["records"].items() if x.get("do") != "response"]
    if not ids:
        return False
    sample = ids[:: max(1, len(ids) // 200)]
    return sum(1 for r in sample if r in s.by_id) >= 0.95 * len(sample)


# ------------------------------------------------------------------ score

def _pr(tp, n_found, n_true):
    return {"found": n_found, "true": n_true, "correct": tp,
            "precision": round(tp / n_found, 4) if n_found else None,
            "recall": round(tp / n_true, 4) if n_true else None}


def _wilson(k, n):
    from .labels import wilson
    lo, hi = wilson(k, n)
    return [round(lo, 4), round(hi, 4)] if n else None


def score(s, truth):
    """Compare a loaded Session with the truth. Returns a JSON-able dict."""
    recs = truth["records"]
    agent_of = {r: x["agent"] for r, x in recs.items()}
    tok_agent = {t: a for a, ts in truth["agents"].items() for t in ts}
    true_t = {r: x["t"] for r, x in recs.items()}
    dl = s.flow["_deliveries"]

    # ---- individual messages
    true_msgs = {(w, r): p for w, r, p in truth["messages"]}
    found = {(d["write_id"], d["read_id"]): d for d in dl}
    tp = set(found) & set(true_msgs)
    true_by_read = defaultdict(set)
    for w, r in true_msgs:
        true_by_read[r].add(w)
    found_reads = {r for _, r in found}
    fp_why, fn_why = Counter(), Counter()
    fp_examples = defaultdict(list)
    for (w, r), d in found.items():
        if (w, r) in true_msgs:
            continue
        info = recs.get(r, {})
        if info.get("do") == "mention":
            why = "named the place without reading it"
        elif agent_of.get(w) and agent_of.get(w) == agent_of.get(r):
            why = "one agent under two tokens talking to itself"
        elif true_by_read.get(r):
            why = "right read, wrong message picked (an older one was fetched)"
        elif info.get("do") == "public_read":
            why = "read a public place that others also read (nobody in the swarm wrote there)"
        elif info.get("do") == "read" and not info.get("got"):
            why = "read a place where nothing from another agent was there yet"
        elif info.get("do") == "read":
            why = "read the same message again (counted once in the truth)"
        else:
            why = "other"
        fp_why[why] += 1
        if len(fp_examples[why]) < 3:
            fp_examples[why].append([w, r])
    fn_examples = defaultdict(list)
    for (w, r) in true_msgs:
        if (w, r) in found:
            continue
        info = recs.get(r, {})
        tw, tr = s.rec["_times"].get(w), s.rec["_times"].get(r)
        if info.get("hidden"):
            why = "the read's address is built from pieces the patterns cannot see"
        elif r in found_reads:
            why = "right read, wrong message picked (an older one was fetched)"
        elif tw is None or tr is None:
            why = "a record has no time"
        elif tw > tr:
            why = "estimated times put the write after the read"
        else:
            why = "other (for example the same message already counted for this reader's other token)"
        fn_why[why] += 1
        if len(fn_examples[why]) < 3:
            fn_examples[why].append([w, r])
    msg = _pr(len(tp), len(found), len(true_msgs))
    msg["precision_ci"] = _wilson(len(tp), len(found))
    msg["recall_ci"] = _wilson(len(tp), len(true_msgs))
    msg["false_positives"] = [{"why": k, "n": v, "examples": fp_examples[k]} for k, v in fp_why.most_common()]
    msg["missed"] = [{"why": k, "n": v, "examples": fn_examples[k]} for k, v in fn_why.most_common()]

    # ---- pairs of agents (tool deliveries mapped to the agents who really wrote and read)
    true_pairs = {(agent_of[w], agent_of[r]) for w, r in true_msgs}
    found_pairs = {(agent_of.get(d["write_id"]), agent_of.get(d["read_id"])) for d in dl
                   if agent_of.get(d["write_id"]) and agent_of.get(d["read_id"])}
    pairs = _pr(len(true_pairs & found_pairs), len(found_pairs), len(true_pairs))
    pairs["self_pairs"] = sum(1 for a, b in found_pairs if a == b)
    actor_pairs = {(d["from"], d["to"]) for d in dl}
    pairs["actor_pairs_as_named_by_the_tool"] = len(actor_pairs)
    pairs["actor_pairs_that_are_one_agent"] = sum(1 for a, b in actor_pairs if tok_agent.get(a) and tok_agent.get(a) == tok_agent.get(b))

    # ---- dating: estimated times against the true ones, and whether the p90 range holds them
    blocks = [b for b in s.rec["time_test"].get("blocks", []) if b.get("timed")]
    spans = []
    for b in blocks:
        if b["first_id"] in s.order and b["last_id"] in s.order:
            spans.append((s.order[b["first_id"]], s.order[b["last_id"]], b.get("fit_error_hours_p90")))
    errs, inside = [], 0
    for e in s.events:
        if e.time or e.id not in true_t or e.id not in s.rec["_times"]:
            continue
        err = abs(s.rec["_times"][e.id] - true_t[e.id]) / 3600
        i = s.order[e.id]
        p90 = next((p for a, z, p in spans if a <= i <= z), None)
        if p90 is None:
            continue   # inherited from a parent, not estimated from a fit
        errs.append(err)
        inside += err <= p90
    errs.sort()
    dating = {"estimated": len(errs),
              "median_error_hours": round(errs[len(errs) // 2], 2) if errs else None,
              "p90_error_hours": round(errs[int(len(errs) * 0.9)], 2) if errs else None,
              "inside_stated_range": round(inside / len(errs), 4) if errs else None,
              "stated_p90_hours": [p for _, _, p in spans]}

    # ---- early signs: the tool's sign times against the same signs computed from the truth
    from . import insight
    sim = insight.simulate(s)
    tool_sig = {}
    for g in sim["signals"]:
        tool_sig.setdefault(g["key"], g)
    harm_true = sorted(true_t[r] for r in truth["harm"] if r in true_t)

    def share_after(t):
        return round(sum(1 for x in harm_true if x > t) / len(harm_true), 4) if harm_true else None
    want = _true_signs(truth, true_msgs, recs, s)
    signs = []
    for key, (t, name) in want.items():
        g = tool_sig.get(key)
        row = {"key": key, "name": name, "true_time": _iso(t), "true_harm_share_after": share_after(t)}
        if g:
            row.update({"tool_time": _iso(g["t"]), "error_hours": round((g["t"] - t) / 3600, 2),
                        "tool_harm_share_after": g["harm_share_after"],
                        "on_time": abs(g["t"] - t) <= 3600})
        else:
            row.update({"tool_time": None, "error_hours": None, "on_time": False})
        signs.append(row)
    extra = [{"key": g["key"], "name": g["name"], "tool_time": g["time"]} for k, g in tool_sig.items() if k not in want]
    signs.sort(key=lambda r: r["true_time"])
    found_signs = sum(1 for r in signs if r["tool_time"])
    on_time = sum(1 for r in signs if r["on_time"])
    first_true = signs[0] if signs else None
    timing = {"signs": signs, "not_in_truth": extra, "found": found_signs, "true": len(signs), "on_time": on_time,
              "recall": round(found_signs / len(signs), 4) if signs else None,
              "on_time_share": round(on_time / found_signs, 4) if found_signs else None,
              "median_abs_error_hours": _median([abs(r["error_hours"]) for r in signs if r["error_hours"] is not None]),
              "coordination_started": truth.get("coordination_from"),
              "first_true_sign": first_true and first_true["true_time"]}

    # ---- identity: which tokens are one agent
    ident = {"agents": len(truth["agents"]), "agents_with_two_tokens": sum(1 for ts in truth["agents"].values() if len(ts) > 1),
             "tool_actors": len({a for a, _ in s.actor.values()})}
    ident.update(identity_score(s, truth))

    return {"dataset": s.name, "truth_params": truth.get("params", {}),
            "records": len(s.events), "true_messages": len(true_msgs),
            "messages": msg, "pairs": pairs, "dating": dating, "early_signs": timing, "identity": ident}


def _median(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 2) if xs else None


def _true_signs(truth, true_msgs, recs, s):
    """The signs the tool's replay names, timed from the truth: first message, two-way, groups, first harm."""
    out = {}
    msgs = sorted(((recs[r]["t"], recs[w]["agent"], recs[r]["agent"]) for w, r in true_msgs), key=lambda x: x[0])
    if msgs:
        out["message"] = (msgs[0][0], "First message between agents")
    seen, parent, size, biggest = set(), {}, Counter(), 0
    thresholds = [3, 5, 10, 20]

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    two = None
    for t, a, b in msgs:
        if two is None and (b, a) in seen:
            two = t
        seen.add((a, b))
        ra, rb = find(a), find(b)
        size[ra] = size[ra] or 1
        size[rb] = size[rb] or 1
        if ra != rb:
            parent[ra] = rb
            size[rb] += size[ra]
        if size[find(b)] > biggest:
            biggest = size[find(b)]
            while thresholds and biggest >= thresholds[0]:
                k = thresholds.pop(0)
                out[f"group{k}"] = (t, f"A group of {k}+ agents linked by messages")
    if two is not None:
        out["two_way"] = (two, "First two-way exchange")
    firsts = {}
    for r in truth["harm"]:
        x = recs[r]
        if x["do"] in ("metadata", "cluster"):
            k = {"metadata": "cloud_metadata", "cluster": "kubernetes_api"}[x["do"]]
        elif x.get("place", "").startswith("board:"):
            k = "registry_board"
        elif x["do"] == "write":
            k = "hf_dataset_write"
        else:
            continue
        if k not in firsts or x["t"] < firsts[k]:
            firsts[k] = x["t"]
    harm_names = set(getattr(s.pack, "harm", []) or [])
    for k, t in firsts.items():
        if not harm_names or k in harm_names:
            out["replay:first: " + k] = (t, "First " + k.replace("_", " "))
    return out


BANDS = ("high", "medium", "low")


def identity_score(s, truth):
    """Score agenttrace.identity's merge proposals against the truth (which tokens are one agent).

    Precision per confidence band (of the pairs proposed at that band, how many are two tokens of one
    agent), and cumulative precision/recall at "high only", "high or medium" and "any band". The
    investigator's saved accept/reject decisions are ignored: this scores the rule alone.
    merges (any band) keeps the shape the case-file view reads."""
    try:
        from . import identity as idm
    except Exception:       # pragma: no cover
        return {"merges": None, "note": "agenttrace.identity is not available"}
    tok_agent = {t: a for a, ts in truth["agents"].items() for t in ts}
    true_all = {tuple(sorted((a, b))) for ts in truth["agents"].values() for a in ts for b in ts if a < b}
    saved = getattr(s, "_id_decisions", None)
    s._id_decisions = {}
    try:
        res = idm.identity(s, limit=10 ** 6)
    except Exception as e:  # pragma: no cover
        return {"merges": None, "note": f"identity merging failed: {e}"}
    finally:
        if saved is not None:
            s._id_decisions = saved
        else:
            try:
                del s._id_decisions
            except AttributeError:
                pass
    named = set(idm._named_actors(s))
    visible = {p for p in true_all if p[0] in named and p[1] in named}
    by_band = {b: [] for b in BANDS}
    for x in res["proposals"]:
        if x.get("confidence") in by_band:
            pair = tuple(sorted((x["a"], x["b"])))
            by_band[x["confidence"]].append((pair, x))
    bands = {}
    for b in BANDS:
        rows = by_band[b]
        ok = sum(1 for pair, _ in rows if pair in true_all)
        wrong = Counter()
        for pair, x in rows:
            if pair not in true_all:
                for ev in x["evidence"]:
                    wrong[ev["key"]] += 1
        bands[b] = {"proposed": len(rows), "correct": ok,
                    "precision": round(ok / len(rows), 4) if rows else None,
                    "precision_ci": _wilson(ok, len(rows)),
                    "wrong_pairs_evidence": dict(wrong.most_common())}
    cumulative = {}
    for name, levels in (("high", ("high",)), ("high_or_medium", ("high", "medium")), ("any", BANDS)):
        pairs = {pair for b in levels for pair, _ in by_band[b]}
        cumulative[name] = _pr(len(pairs & true_all), len(pairs), len(true_all))
    est = res.get("estimate", {})
    agents_seen = {tok_agent[a] for a in named if a in tok_agent}
    return {"merges": cumulative["any"], "bands": bands, "cumulative": cumulative,
            "true_pairs": len(true_all), "true_pairs_both_named": len(visible),
            "estimated_agents": est.get("estimated_agents"), "estimated_agents_range": [est.get("low"), est.get("high")],
            "true_agents_seen": len(agents_seen), "named_actors": len(named)}


def load_and_score(folder_or_trace, pack=None):
    from .session import Session
    src = folder_or_trace
    tp = truth_path_for(src)
    if tp and os.path.isdir(src):
        cand = os.path.join(src, load_truth(tp).get("trace") or "trace.jsonl")
        src = cand if os.path.exists(cand) else src
    if not tp:
        raise SystemExit(f"no {TRUTH_EXT} file next to {folder_or_trace}")
    truth = load_truth(tp)
    s = Session()
    s.load(src, pack or truth.get("pack") or "auto", {}, os.path.basename(src.rstrip("/")))
    return score(s, truth)


def _fmt_pr(x):
    p = "–" if x["precision"] is None else f"{100 * x['precision']:.1f}%"
    r = "–" if x["recall"] is None else f"{100 * x['recall']:.1f}%"
    return f"precision {p} ({x['correct']}/{x['found']}), recall {r} ({x['correct']}/{x['true']})"


def report_text(sc):
    lines = [f"Ground-truth score for {sc['dataset']} ({sc['records']:,} records, {sc['true_messages']:,} true messages)", ""]
    m = sc["messages"]
    lines.append("Messages (write record -> read record): " + _fmt_pr(m))
    for x in m["false_positives"]:
        lines.append(f"  false: {x['n']:>4}  {x['why']}")
    for x in m["missed"]:
        lines.append(f"  missed: {x['n']:>3}  {x['why']}")
    p = sc["pairs"]
    lines.append("Pairs of agents: " + _fmt_pr(p) + f"; {p['self_pairs']} pairs are one agent with itself")
    lines.append(f"  the tool names {p['actor_pairs_as_named_by_the_tool']} actor pairs; "
                 f"{p['actor_pairs_that_are_one_agent']} are two tokens of one agent")
    d = sc["dating"]
    if d["estimated"]:
        lines.append(f"Dating: {d['estimated']} estimated times, median error {d['median_error_hours']} h, "
                     f"90th percentile {d['p90_error_hours']} h; {100 * d['inside_stated_range']:.0f}% fall inside the stated range")
    else:
        lines.append("Dating: no estimated times (every record has a time field or none could be estimated)")
    e = sc["early_signs"]
    lines.append(f"Early signs: {e['found']} of {e['true']} found, {e['on_time']} within an hour of the true time"
                 f" (median error {e['median_abs_error_hours']} h)")
    for r in e["signs"]:
        lines.append(f"  {r['name']:<40} true {r['true_time']}  tool {r['tool_time'] or '—':<20} "
                     f"{'' if r['error_hours'] is None else ('%+.1f h' % r['error_hours'])}")
    i = sc["identity"]
    lines.append(f"Identity: {i['agents']} agents, {i['agents_with_two_tokens']} with two tokens; the tool sees {i['tool_actors']} actors")
    if i.get("merges"):
        lines.append("  merge proposals: " + _fmt_pr(i["merges"]))
        for b in BANDS:
            x = i["bands"][b]
            if x["proposed"]:
                lines.append(f"    {b:<6} {x['correct']}/{x['proposed']} right ({100 * x['precision']:.0f}%)")
    elif i.get("note"):
        lines.append("  " + i["note"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m agenttrace.groundtruth", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="write a simulated swarm trace and its truth file")
    mk.add_argument("out")
    mk.add_argument("--agents", type=int, default=40)
    mk.add_argument("--seed", type=int, default=1)
    mk.add_argument("--hours", type=float, default=36)
    mk.add_argument("--time", choices=["embedded", "field"], default="embedded",
                    help="timestamps embedded in some of the code (the rest estimated), or a time field on every record")
    mk.add_argument("--two-token-share", type=float, default=0.12)
    mk.add_argument("--hidden-share", type=float, default=0.08, help="share of reads whose address the patterns cannot see")
    mk.add_argument("--mention-share", type=float, default=0.06, help="how many notes name a place without reading it")
    mk.add_argument("--mode", choices=["coordinated", "benign"], default="coordinated",
                    help="benign: agents work in parallel and never coordinate (no true messages, no harm)")
    mk.add_argument("--own-writes", type=float, default=0.5, help="benign mode: share of agents saving results to their own dataset")
    mk.add_argument("--name", default="trace.jsonl", help="file name of the trace (the truth file adds .truth)")
    sc = sub.add_parser("score", help="load a generated trace with the tool and score it against its truth")
    sc.add_argument("path", help="the folder from make, or the trace file")
    sc.add_argument("--pack", default=None)
    sc.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        t = make(a.out, agents=a.agents, seed=a.seed, hours=a.hours, time_mode=a.time,
                 two_token_share=a.two_token_share, hidden_share=a.hidden_share, mention_share=a.mention_share,
                 name=a.name, mode=a.mode, own_writes=a.own_writes)
        print(f"wrote {os.path.join(a.out, a.name)}: {len(t['records']):,} records, {len(t['agents'])} agents, "
              f"{len(t['messages']):,} true messages; truth in {a.name}{TRUTH_EXT}")
        return 0
    res = load_and_score(a.path, a.pack)
    print(json.dumps(res, indent=1) if a.json else report_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

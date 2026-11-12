"""Attribution: group anonymous runs into probable agents.

An anonymous run is a thread whose actions carry no identity token (actor "run:<thread root>").
This module looks for what such a run shares with named actors and with other anonymous runs:

  features of a run   exact redaction placeholders ([SERVICE 3 URL 209] is the same redacted value
                      wherever it appears), string constants, identifiers (variable and helper names),
                      self-chosen names (the pack's handles and shared-name patterns), the program
                      family (masked text), and a host + code-style fingerprint.
  rare                a feature counts only when few runs carry it (document frequency), when at
                      most MAX_ACTORS named actors use it, and when it did not travel in a message
                      (a string both ends of a delivery contain says "they talked", not "one agent").
  run -> named actor  evidence items with points, as in identity.py. An item is direct when the
                      feature is used by exactly one named actor and by at most RARE runs in all;
                      everything else is circumstantial and capped (an identical program, or another
                      actor's credential placeholder in the text, is never direct: on held-out named
                      threads those alone pointed at the wrong actor more often than not). Bands:
                      Direct features found in exactly the same threads of the actor count as
                      one independent item (a copied program shares dozens of strings at once).
                        high    three or more independent direct items, and no direct item
                                pointing at anyone else
                        medium  two independent direct items and no conflict
                        low     one direct item seen in two or more of the actor's threads, a
                                conflict between actors, or inherited from a cluster
                      One rare feature seen in one thread of one actor, or circumstantial evidence
                      alone, makes no link: measured on held-out threads, those are coincidences
                      about as often as not.
  clusters            union-find over strong links only: two anonymous runs that share at least
                      CL_SHARED rare exact features (each carried by at most CL_DF runs).

It is inference. The bands are measured, not assumed: holdout() hides the token of half of the
named threads, attributes them as if they were anonymous and counts how often the link is right;
score_swarms() does the same on simulated swarms whose truth file says which agent ran each record.
"""
import hashlib
import os
import random
import re
import time
from collections import Counter, defaultdict

from . import messages, reconstruct

RARE = 50            # a direct feature is carried by at most this many runs (named threads + anonymous runs)
COMMON = 500         # features carried by more runs than this are boilerplate and ignored
MAX_ACTORS = 3       # features used by more named actors than this are ignored
KIND_CAP = 2         # at most this many features of one kind add points (copies share many at once)
CIRC_CAP = 3.0       # circumstantial points are capped, as in identity.py
HIGH_GROUPS = 3      # high: this many independent direct items, on this many of the actor's threads
CL_DF = 4            # a clustering feature is carried by at most this many anonymous runs
CL_SHARED = 4        # two runs are strongly linked when they share at least this many such features
TEXT_CAP = 8000      # characters of each record that are read
QUOTE = 160          # characters of record text quoted at most
TOP_CLUSTERS = 40
BUBBLES = 160
BANDS = ("high", "medium", "low")

KINDS = {
    "name": ("Self-chosen name", 3.0),
    "credential": ("Credential placeholder outside an auth header", 3.0),
    "ph": ("Same redacted value (numbered placeholder)", 3.0),
    "str": ("String constant", 2.0),
    "id": ("Identifier (variable or helper name)", 2.0),
    "fam": ("Same program (masked text identical)", 2.0),
    "pre": ("Same program opening", 1.0),
    "combo": ("Host + code style", 1.0),
    "cluster": ("Clustered with attributed runs", 0.0),
}
NEVER_DIRECT = {"combo", "pre", "fam", "credential"}   # measured: these alone point at the wrong actor too often
CLUSTER_KINDS = {"name", "ph", "str", "id"}

PH = re.compile(r"\[[A-Z][A-Za-z0-9:_ \-]*?[ :]\d+\]")
CRED = re.compile(r"\[CREDENTIAL \d+\]")
STR = re.compile(r"'([^'\\\n\[\]]{4,60})'|\"([^\"\\\n\[\]]{4,60})\"")
IDT = re.compile(r"[A-Za-z_$][\w$]{5,40}")
HOST = re.compile(r"\[(SERVICE \d+|PROXY \d+|SHORTENER-\d+-HOST|WEBHOOK HOST \d+|SERVICE HOST \d+|INTERNAL HOST \d+)")
_LANG = [("python", re.compile(r"\bimport \w|\bdef \w+\(|urllib|\bprint\(")),
         ("html", re.compile(r"<script|<iframe|<img|<svg", re.I)),
         ("js", re.compile(r"fetch\(|document\.|=>|\bfunction\b|\bconst |\bvar |XMLHttpRequest|new Image")),
         ("shell", re.compile(r"\bcurl |\bwget |\bbash\b|\$\(|\bcat /"))]
_NET = [("fetch", re.compile(r"\bfetch\(")), ("xhr", re.compile(r"XMLHttpRequest")),
        ("urllib", re.compile(r"urllib|urlopen")), ("requests", re.compile(r"\brequests\.")),
        ("image", re.compile(r"new Image|\.src\s*=")), ("docwrite", re.compile(r"document\.write")),
        ("curl", re.compile(r"\bcurl "))]


def _need(state):
    s = state.get("session")
    if s is None or not getattr(s, "loaded", False):
        raise LookupError("no dataset is loaded")
    return s


def _style(text):
    lang = next((n for n, rx in _LANG if rx.search(text)), "other")
    net = "+".join(n for n, rx in _NET if rx.search(text)) or "none"
    sq, dq = text.count("'"), text.count('"')
    quote = "single" if sq > 2 * dq else "double" if dq > 2 * sq else "mixed" if sq + dq else "none"
    semi = "semi" if text.count(";") >= 2 else "nosemi"
    return lang, net, quote, semi


def _features(e, pack, own_ids=()):
    """The set of (kind, value) features of one record. own_ids: identity tokens that are left out
    (a hidden thread's own token must not be evidence for itself)."""
    t = e.text[:TEXT_CAP]
    f = set()
    for m in PH.findall(t):
        if m.startswith("[CREDENTIAL"):
            continue
        f.add(("ph", m))
    for m in CRED.findall(t):
        if m not in own_ids:
            f.add(("credential", m))
    bare = PH.sub(" ", t)
    for a, b in STR.findall(bare):
        f.add(("str", a or b))
    for m in IDT.findall(bare):
        if ("str", m) not in f:      # one string must not count twice
            f.add(("id", m))
    if pack.handles_rx:
        from .packs import family_of
        for m in pack.handles_rx.findall(t):
            f.add(("name", family_of(m, pack)))
    for _fam, rx in pack.shared_names:
        for m in rx.finditer(t):
            f.add(("name", m.group(0)))
    hosts = sorted(set(HOST.findall(t)))
    if hosts:
        f.add(("combo", " · ".join(hosts[:4]) + " | " + " ".join(_style(t))))
    n = messages._norm(e.text[:TEXT_CAP])
    toks = messages.TOKEN.findall(n)
    if len(toks) >= 12:
        f.add(("fam", hashlib.sha1(n.encode("utf-8", "replace")).hexdigest()[:12]))
    if len(toks) >= 20:
        f.add(("pre", hashlib.sha1(" ".join(toks[:60]).encode("utf-8", "replace")).hexdigest()[:12]))
    return f


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        p = self.p
        r = x
        while p.get(r, r) != r:
            r = p[r]
        while p.get(x, x) != r:
            p[x], x = r, p[x]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _base(s):
    """Per-record features, the record's thread and named actor; computed once per session."""
    c = getattr(s, "_attr_base", None)
    if c is not None:
        return c
    root = s.res["_root"]
    shared = set(s.pack.raw.get("shared_identities", []))
    acts, feats = [], {}
    for e in s.events:
        if not reconstruct.is_action(e, s.pack):
            continue
        acts.append(e.id)
        own = [k for k in s.rec["_ids"].get(e.id, {}) if k not in shared]
        feats[e.id] = _features(e, s.pack, set(own) | shared)
    # features that travelled in a message say "they talked", not "one agent"
    messaged = set()
    for d in s.flow.get("_deliveries", []):
        a, b = feats.get(d["write_id"]), feats.get(d["read_id"])
        if a and b:
            messaged |= {k for k in a & b if k[0] not in ("combo", "fam", "pre")}
    c = s._attr_base = {"acts": acts, "feats": feats, "messaged": messaged, "root": root}
    return c


def _attribute(s, hide=frozenset()):
    """Attribute every anonymous run. hide: thread roots of named threads to treat as anonymous
    (their own identity tokens are never features). Returns the full working result."""
    b = _base(s)
    feats, root, messaged = b["feats"], b["root"], b["messaged"]
    named_units = {}                       # thread root -> named actor
    unit_recs = defaultdict(list)          # anonymous run (thread root) -> its action records
    unit_feats = defaultdict(set)
    by = defaultdict(lambda: defaultdict(set))   # feature -> named actor -> thread roots
    named_actions = 0
    for rid in b["acts"]:
        a, ak = s.actor[rid]
        r = root[rid]
        if ak != "run" and r not in hide:
            named_actions += 1
            named_units[r] = a
            for k in feats[rid]:
                by[k][a].add(r)
        else:
            unit_recs[r].append(rid)
            unit_feats[r] |= feats[rid]
    hidden_tokens = set()
    if hide:   # a hidden thread's own token, seen elsewhere in its thread, is not evidence either
        for r in unit_recs:
            if r in hide:
                own = {("credential", s.actor[x][0]) for x in unit_recs[r]}
                unit_feats[r] -= own
    anon_df = Counter()
    for r, f in unit_feats.items():
        anon_df.update(f)
    named_df = {k: sum(len(v) for v in d.values()) for k, d in by.items()}
    for k in list(by):                     # a credential feature is evidence only for the actor it names
        if k[0] == "credential":
            by[k] = {k[1]: by[k].get(k[1], set())} if k[1] in set(named_units.values()) else {}
    actors_all = set(named_units.values())

    links = {}
    weak = circ_only = 0
    for u, f in unit_feats.items():
        cand = defaultdict(list)
        for k in f:
            if k[0] == "credential":
                if k[1] in actors_all:
                    cand[k[1]].append((k, False, 1.0, 1, anon_df[k] + named_df.get(k, 0)))
                continue
            d = by.get(k)
            if not d or k in messaged:
                continue
            df = anon_df[k] + named_df[k]
            if len(d) > MAX_ACTORS or df > COMMON:
                continue
            direct = len(d) == 1 and df <= RARE and k[0] not in NEVER_DIRECT
            pts = KINDS[k[0]][1] if direct else min(1.0, KINDS[k[0]][1]) / len(d)
            for a in d:
                cand[a].append((k, direct, pts, len(d), df))
        if not cand:
            continue
        scored = []
        for a, items in cand.items():
            items.sort(key=lambda x: (-x[1], -x[2], x[4], x[0]))
            per, dpts, cpts, nd = Counter(), 0.0, 0.0, 0
            support, groups = set(), set()
            for k, direct, pts, na, df in items:
                if direct:
                    # features found in exactly the same threads of the actor are one piece of evidence
                    # (a copied program shares dozens of strings at once; 'x' and 'def x()' are one string)
                    groups.add(frozenset(by[k].get(a, ())))
                    support |= by[k].get(a, set())
                per[(k[0], direct)] += 1
                if per[(k[0], direct)] > KIND_CAP:
                    continue
                if direct:
                    dpts += pts
                else:
                    cpts += pts
            nd = len(groups)
            scored.append((nd, dpts + min(CIRC_CAP, cpts), a, items, len(support)))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        nd, sc, a, items, sup = scored[0]
        second = scored[1] if len(scored) > 1 else None
        conflict = bool(second and second[0] > 0 and nd > 0)
        if not conflict and nd >= HIGH_GROUPS and sup >= HIGH_GROUPS:
            band = "high"
        elif not conflict and nd >= 2:
            band = "medium"
        elif nd >= 2 or (nd == 1 and sup >= 2):
            band = "low"
        else:
            # one rare feature seen in one thread of one actor, or circumstantial evidence alone, is a
            # coincidence as often as not (measured): counted, not linked
            weak += 1 if nd else 0
            circ_only += 0 if nd else 1
            continue
        links[u] = {"actor": a, "band": band, "score": round(sc, 2), "direct": nd, "support": sup,
                    "direct_features": sum(1 for x in items if x[1]), "conflict": second[2] if conflict else None, "items": items}

    # clusters of anonymous runs: union-find over pairs that share >= CL_SHARED rare exact features
    post = defaultdict(list)
    for u, f in unit_feats.items():
        for k in f:
            if k[0] in CLUSTER_KINDS and 2 <= anon_df[k] <= CL_DF and k not in messaged \
                    and len(by.get(k, ())) <= 1 and anon_df[k] + named_df.get(k, 0) <= RARE:
                post[k].append(u)
    pairs = Counter()
    for k, us in post.items():
        us.sort()
        for i in range(len(us)):
            for j in range(i + 1, len(us)):
                pairs[(us[i], us[j])] += 1
    uf = _UF()
    for (x, y), n in pairs.items():
        if n >= CL_SHARED:
            uf.union(x, y)
    groups = defaultdict(list)
    for u in set(uf.p) | set(uf.p.values()):
        groups[uf.find(u)].append(u)
    clusters = []
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort()
        votes = Counter(links[u]["actor"] for u in g if u in links and links[u]["band"] in ("high", "medium"))
        actor = None
        if votes:
            top, n = votes.most_common(1)[0]
            if n >= 0.6 * sum(votes.values()):
                actor = top
        clusters.append({"members": g, "actor": actor, "votes": dict(votes)})
    clusters.sort(key=lambda c: (-len(c["members"]), c["members"][0]))
    cluster_of = {}
    for i, c in enumerate(clusters):
        c["id"] = i + 1
        for u in c["members"]:
            cluster_of[u] = c["id"]
            if c["actor"] and u not in links:
                links[u] = {"actor": c["actor"], "band": "low", "score": 0.0, "direct": 0, "support": 0,
                            "conflict": None, "items": [], "via_cluster": c["id"]}
    return {"links": links, "clusters": clusters, "cluster_of": cluster_of, "unit_recs": unit_recs,
            "unit_feats": unit_feats, "by": by, "anon_df": anon_df, "named_df": named_df,
            "named_actions": named_actions, "pairs": pairs, "post": post, "weak": weak, "circ_only": circ_only}


# ------------------------------------------------------------------ validation

def _wilson(k, n):
    if not n:
        return None
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def _band_rows(counts):
    out = {}
    for bnd in BANDS:
        ok, n = counts.get((bnd, True), 0), counts.get((bnd, True), 0) + counts.get((bnd, False), 0)
        out[bnd] = {"links": n, "correct": ok, "precision": round(ok / n, 4) if n else None, "precision_ci": _wilson(ok, n)}
    return out


def _hide_half(s, seed, share=0.5):
    """Thread roots of named threads to hide: a random half, by thread. Threads named only by a handle
    in their text are left alone (the handle would give them away)."""
    b = _base(s)
    roots = sorted({b["root"][r] for r in b["acts"] if s.actor[r][1] in ("named", "token", "token_via_thread")})
    rng = random.Random(seed)
    return frozenset(r for r in roots if rng.random() < share)


def holdout(s, seeds=(1, 2), agent_of=None, big=3, merged_of=None):
    """Hide the token of half of the named threads, attribute them like anonymous runs, and score.
    agent_of: actor token -> true agent (simulated swarms); without it the hidden token is the truth,
    which undercounts when one agent holds several tokens. Pooled over seeds."""
    b = _base(s)
    counts, counts_small, wrong_kinds, counts_m = Counter(), Counter(), Counter(), Counter()
    cl_ok_m = 0
    mt = lambda a: (merged_of or {}).get(a, a)
    hidden_n = 0
    cl_ok = cl_n = cl_runs = 0
    size = Counter(s.actor[r][0] for r in b["acts"] if s.actor[r][1] != "run")
    bigs = {a for a, _ in size.most_common(big)}
    truth = lambda a: (agent_of or {}).get(a, a)
    for seed in seeds:
        hide = _hide_half(s, seed)
        res = _attribute(s, hide)
        true_of = {}
        for u in hide:
            recs = res["unit_recs"].get(u)
            if recs:
                true_of[u] = truth(s.actor[recs[0]][0])
        hidden_n += len(true_of)
        for u, t in true_of.items():
            ln = res["links"].get(u)
            if not ln:
                continue
            ok = truth(ln["actor"]) == t
            counts[(ln["band"], ok)] += 1
            counts_m[(ln["band"], mt(ln["actor"]) == mt(t))] += 1
            if t not in {truth(x) for x in bigs}:
                counts_small[(ln["band"], ok)] += 1
            if not ok:
                for k, direct, *_ in ln["items"][:3]:
                    wrong_kinds[(ln["band"], k[0])] += 1
        for c in res["clusters"]:
            ms = [true_of[u] for u in c["members"] if u in true_of]
            if len(ms) < 2:
                continue
            cl_runs += len(ms)
            cnt = Counter(ms)
            cl_n += len(ms) * (len(ms) - 1) // 2
            cl_ok += sum(v * (v - 1) // 2 for v in cnt.values())
            cl_ok_m += sum(v * (v - 1) // 2 for v in Counter(mt(x) for x in ms).values())
    bands = _band_rows(counts)
    linked = sum(x["links"] for x in bands.values())
    return {"seeds": list(seeds), "hidden_runs": hidden_n, "bands": bands, "bands_without_largest": _band_rows(counts_small),
            "largest_left_out": big, "coverage": round(linked / hidden_n, 4) if hidden_n else None,
            "cluster_pairs": cl_n, "cluster_pairs_same": cl_ok, "cluster_runs": cl_runs,
            "cluster_pair_precision": round(cl_ok / cl_n, 4) if cl_n else None,
            "wrong_evidence": {f"{bnd}:{k}": n for (bnd, k), n in wrong_kinds.most_common(8)},
            "bands_merged": _band_rows(counts_m) if merged_of else None,
            "cluster_pair_precision_merged": round(cl_ok_m / cl_n, 4) if cl_n and merged_of else None,
            "merged_tokens": len(merged_of or {}),
            "truth": "simulated agent" if agent_of else "hidden token"}


_SWARM_CACHE = {}
MAX_SWARMS = 6


def _swarm_dirs(path=None):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = path or os.path.join(here, "reports", "validation", "swarms")
    if not os.path.isdir(base):
        return base, []
    from . import groundtruth
    if groundtruth.truth_path_for(base) and any(f.endswith(groundtruth.TRUTH_EXT) for f in os.listdir(base)):
        return base, [base]
    return base, sorted(os.path.join(base, d) for d in os.listdir(base)
                        if os.path.isdir(os.path.join(base, d)) and groundtruth.truth_path_for(os.path.join(base, d)))


def score_session(s, truth, seeds=(1, 2)):
    agent_of = {t: a for a, ts in truth.get("agents", {}).items() for t in ts}
    return holdout(s, seeds=seeds, agent_of=agent_of, big=0)


def score_swarms(path=None, limit=MAX_SWARMS):
    """Split-half holdout on simulated swarms with a truth file; pooled. Cached per path."""
    base, dirs = _swarm_dirs(path)
    key = (base, limit)
    if key in _SWARM_CACHE:
        return _SWARM_CACHE[key]
    from . import groundtruth
    from .session import Session
    if not dirs:
        return {"available": False, "why": f"no simulated swarms with a truth file under {base}",
                "command": "python3 -m agenttrace.groundtruth make /tmp/swarm --agents 40 --seed 1"}
    # spread the sample over settings: every k-th folder
    step = max(1, len(dirs) // limit)
    pick = dirs[::step][:limit]
    t0 = time.time()
    rows, pooled, hidden, cl_n, cl_ok = [], Counter(), 0, 0, 0
    for d in pick:
        tp = groundtruth.truth_path_for(d)
        truth = groundtruth.load_truth(tp)
        src = os.path.join(d, truth.get("trace") or "trace.jsonl") if os.path.isdir(d) else d
        if not os.path.exists(src):
            src = d
        s = Session()
        try:
            s.load(src, truth.get("pack") or "auto", {}, os.path.basename(d.rstrip("/")))
        except Exception as e:      # pragma: no cover
            rows.append({"swarm": os.path.basename(d), "error": str(e)})
            continue
        h = score_session(s, truth)
        rows.append({"swarm": os.path.basename(d.rstrip("/")), "mode": truth.get("mode", "coordinated"),
                     "agents": len(truth.get("agents", {})), "hidden_runs": h["hidden_runs"], "bands": h["bands"],
                     "coverage": h["coverage"], "cluster_pair_precision": h["cluster_pair_precision"], "cluster_pairs": h["cluster_pairs"]})
        for bnd, x in h["bands"].items():
            pooled[(bnd, True)] += x["correct"]
            pooled[(bnd, False)] += x["links"] - x["correct"]
        hidden += h["hidden_runs"]
        cl_n += h["cluster_pairs"]
        cl_ok += h["cluster_pairs_same"]
    bands = _band_rows(pooled)
    linked = sum(x["links"] for x in bands.values())
    out = {"available": True, "path": base, "swarms": rows, "swarms_scored": len(rows), "swarms_found": len(dirs),
           "hidden_runs": hidden, "bands": bands, "coverage": round(linked / hidden, 4) if hidden else None,
           "cluster_pairs": cl_n, "cluster_pair_precision": round(cl_ok / cl_n, 4) if cl_n else None,
           "seconds": round(time.time() - t0, 1),
           "note": "Simulated agents all run the same generated code, so they have no personal style: this is a "
                   "negative control. A careful method should link few of their runs, and be right when it does."}
    _SWARM_CACHE[key] = out
    return out


# ------------------------------------------------------------------ summary for the app

def _merged_tokens(s):
    """token -> group, for tokens identity.py proposes as one agent with high confidence (its saved
    accept/reject decisions are not consulted). Used only as a second way to score the holdout."""
    try:
        from . import identity
        saved = getattr(s, "_id_decisions", None)
        s._id_decisions = {}
        try:
            props = identity.identity(s, limit=10 ** 6)["proposals"]
        finally:
            if saved is not None:
                s._id_decisions = saved
            else:
                try:
                    del s._id_decisions
                except AttributeError:
                    pass
    except Exception:
        return {}
    uf = _UF()
    for p in props:
        if p.get("confidence") == "high":
            uf.union(p["a"], p["b"])
    return {a: uf.find(a) for a in list(uf.p) + list(uf.p.values())}


def _snip(text, token=None, width=QUOTE):
    text = text or ""
    if token:
        i = text.find(token)
        if i >= 0:
            a = max(0, i - (width - len(token)) // 2)
            return ("…" if a else "") + text[a:a + width] + ("…" if a + width < len(text) else "")
    return text[:width] + ("…" if len(text) > width else "")


def _label(k):
    return k[1] if k[0] not in ("fam", "pre") else f"program {k[1]}"


def attribution(s):
    c = getattr(s, "_attribution", None)
    if c is not None:
        return c
    t0 = time.time()
    res = _attribute(s)
    t1 = time.time()
    times = s.rec["_times"]
    links, units = res["links"], res["unit_recs"]
    total_actions = len(_base(s)["acts"])
    anon_actions = sum(len(v) for v in units.values())
    bands = {bnd: {"runs": 0, "actions": 0} for bnd in BANDS + ("unattributed",)}
    per_actor = defaultdict(lambda: {bnd: 0 for bnd in BANDS})
    kinds = Counter()
    kinds_direct = Counter()
    for u, recs in units.items():
        ln = links.get(u)
        bnd = ln["band"] if ln else "unattributed"
        bands[bnd]["runs"] += 1
        bands[bnd]["actions"] += len(recs)
        if ln:
            per_actor[ln["actor"]][bnd] += 1
            if ln.get("via_cluster"):
                kinds["cluster"] += 1
            for kind in {k[0] for k, *_ in ln["items"]}:
                kinds[kind] += 1
            for kind in {k[0] for k, direct, *_ in ln["items"] if direct}:
                kinds_direct[kind] += 1
    per_actor_all = {s.actor[r][0] for r in _base(s)["acts"] if s.actor[r][1] != "run"}
    clustered = sum(len(cl["members"]) for cl in res["clusters"])
    in_cluster_only = sum(1 for cl in res["clusters"] for u in cl["members"] if u not in links)

    def cluster_row(cl, full):
        ms = cl["members"]
        ts = sorted(t for u in ms for r in units[u] for t in [times.get(r)] if t is not None)
        row = {"id": cl["id"], "runs": len(ms), "actions": sum(len(units[u]) for u in ms), "actor": cl["actor"],
               "linked_runs": sum(cl["votes"].values()), "votes": cl["votes"], "member": "run:" + ms[0],
               "first": reconstruct.iso(ts[0]) if ts else None, "last": reconstruct.iso(ts[-1]) if ts else None}
        if full:
            shared = Counter()
            for u in ms:
                for k in res["unit_feats"][u]:
                    if k in res["post"]:
                        shared[k] += 1
            ev = [{"kind": k[0], "label": KINDS[k[0]][0], "token": _label(k)[:80], "runs": n}
                  for k, n in sorted(shared.items(), key=lambda x: (-x[1], x[0]))[:6] if n >= 2]
            row["evidence"] = ev
            row["members"] = ["run:" + u for u in ms[:14]]
            tok = ev[0]["token"] if ev else None
            row["examples"] = [{"id": units[u][0], "snippet": _snip(s.by_id[units[u][0]].text, tok)} for u in ms[:2]]
            styles = Counter(" ".join(_style(s.by_id[units[u][0]].text[:TEXT_CAP])[:2]) for u in ms[:200])
            row["style"] = styles.most_common(1)[0][0]
        return row

    out = {
        "runs": len(units), "actions": anon_actions, "actions_total": total_actions, "named_actions": res["named_actions"],
        "named_actors": len({a for a in set(s.actor[r][0] for r in _base(s)["acts"]) if not a.startswith("run:")}),
        "bands": bands,
        "known_share_before": round(res["named_actions"] / total_actions, 4) if total_actions else None,
        "single_coincidence_runs": res["weak"], "circumstantial_only_runs": res["circ_only"],
        "clusters_total": len(res["clusters"]), "clustered_runs": clustered, "clustered_unattributed_runs": in_cluster_only,
        "clusters_named": sum(1 for cl in res["clusters"] if cl["actor"]),
        "evidence_kinds": [{"key": k, "label": KINDS[k][0], "runs": n, "direct_runs": kinds_direct.get(k, 0)} for k, n in kinds.most_common()],
        "clusters": [cluster_row(cl, True) for cl in res["clusters"][:TOP_CLUSTERS]],
        "bubbles": [cluster_row(cl, False) for cl in res["clusters"][:BUBBLES]],
        "actors": sorted(({"actor": a, **v, "runs": sum(v.values())} for a, v in per_actor.items()), key=lambda x: (-x["runs"], x["actor"]))[:60],
        "actors_total": len(per_actor),
        "method": {"rare": RARE, "common": COMMON, "max_actors": MAX_ACTORS, "cluster_df": CL_DF, "cluster_shared": CL_SHARED,
                   "text_cap": TEXT_CAP, "messaged_features_ignored": len(_base(s)["messaged"])},
        "caveat": "These are probable links from shared rare material, not identities. A shared string can also mean "
                  "a copied program or a shared tool; a named actor is a token, and one agent can hold several.",
    }
    ex = {bnd: [] for bnd in BANDS}
    for u in sorted(links, key=lambda u: (-links[u]["direct"], -links[u]["support"], u)):
        ln = links[u]
        if len(ex[ln["band"]]) < 6 and sum(1 for x in ex[ln["band"]] if x["actor"] == ln["actor"]) < 2:
            ex[ln["band"]].append({"id": "run:" + u, "actor": ln["actor"], "direct": ln["direct"], "support": ln["support"]})
    out["examples"] = ex
    s._attr_res = res
    out["seconds_attribute"] = round(t1 - t0, 2)
    out["credential_carriers"] = sum(1 for f in res["unit_feats"].values() if any(k[0] == "credential" and k[1] in per_actor_all for k in f))
    try:
        out["holdout"] = holdout(s, seeds=(1, 2), merged_of=_merged_tokens(s))
    except Exception as e:      # pragma: no cover
        out["holdout"] = {"error": str(e)}
    out["seconds"] = round(time.time() - t0, 2)
    s._attribution = out
    return out


def run_detail(s, rid):
    attribution(s)
    res = s._attr_res
    u = rid[4:] if rid.startswith("run:") else rid
    if u not in res["unit_recs"]:
        u = s.res["_root"].get(u, u)
    if u not in res["unit_recs"]:
        raise LookupError(f"{rid} is not an anonymous run")
    recs = res["unit_recs"][u]
    text = s.by_id[recs[0]].text
    ln = res["links"].get(u)
    out = {"id": "run:" + u, "records": recs[:20], "actions": len(recs), "time": reconstruct.iso(s.rec["_times"].get(recs[0])),
           "style": dict(zip(("language", "network", "quotes", "semicolons"), _style(text[:TEXT_CAP]))),
           "snippet": _snip(text), "band": ln["band"] if ln else None, "actor": ln["actor"] if ln else None,
           "score": ln["score"] if ln else None, "conflict": ln["conflict"] if ln else None, "evidence": []}
    if ln:
        for k, direct, pts, na, df in ln["items"][:12]:
            sup = sorted(res["by"].get(k, {}).get(ln["actor"], ()))[:3] if k[0] != "credential" else []
            sup_rec = None
            for r in sup:           # the named thread's record that carries the feature
                sup_rec = next((e for e in [s.by_id.get(r)] if e is not None and _label(k) in e.text), None) or sup_rec
                if sup_rec:
                    break
            tok = _label(k) if k[0] not in ("fam", "pre", "combo") else None
            out["evidence"].append({
                "kind": k[0], "label": KINDS[k[0]][0], "token": _label(k)[:120], "direct": direct, "points": round(pts, 2),
                "named_actors": na, "runs_with_it": df, "support_threads": sup,
                "here": _snip(text, tok) if tok and tok in text else None,
                "there": {"id": sup_rec.id, "snippet": _snip(sup_rec.text, tok)} if sup_rec is not None and tok else None})
        if ln.get("via_cluster"):
            out["evidence"].append({"kind": "cluster", "label": KINDS["cluster"][0], "token": f"cluster {ln['via_cluster']}",
                                    "direct": False, "points": 0, "named_actors": 1, "runs_with_it": None, "support_threads": []})
    cid = res["cluster_of"].get(u)
    if cid:
        cl = res["clusters"][cid - 1]
        mates = []
        for v in cl["members"]:
            if v == u:
                continue
            a, b2 = (u, v) if u < v else (v, u)
            n = res["pairs"].get((a, b2), 0)
            if n:
                sh = sorted(k for k in res["unit_feats"][u] & res["unit_feats"][v] if k in res["post"])[:3]
                mates.append({"id": "run:" + v, "record": res["unit_recs"][v][0], "shared": n,
                              "tokens": [_label(k)[:80] for k in sh],
                              "here": _snip(text, _label(sh[0])) if sh else None,
                              "snippet": _snip(s.by_id[res["unit_recs"][v][0]].text, _label(sh[0]) if sh else None)})
        mates.sort(key=lambda m: (-m["shared"], m["id"]))
        out["cluster"] = {"id": cid, "runs": len(cl["members"]), "actor": cl["actor"], "mates": mates[:6]}
    return out


# ------------------------------------------------------------------ routes

def _get_attribution(state, q):
    return attribution(_need(state))


def _get_run(state, q):
    rid = (q.get("id") or "").strip()
    if not rid:
        raise ValueError("id is required (run:<record id>)")
    return run_detail(_need(state), rid)


def _get_score(state, q):
    out = dict(score_swarms(q.get("path") or None))
    s = state.get("session")
    if s is not None and getattr(s, "loaded", False):
        out["this_dataset"] = attribution(s).get("holdout")
    return out


GET = {"attribution": _get_attribution, "attribution_run": _get_run, "attribution_score": _get_score}
POST = {}

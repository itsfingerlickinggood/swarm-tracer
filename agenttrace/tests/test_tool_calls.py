"""v2.3.0, the faults the agent harness found (docs/harness.md), each as a small case with asserted values:

  R2    a tool server's answer (the pack's reply_kinds) is not an action, so the server is no party to a delivery
  R18a  a tool call that names its place in an argument writes or reads that place, whatever the place's shape
  R38b  the reader's later output holds a distinctive term the writer wrote, with its two guards
  the online replay comes out in the same order under every PYTHONHASHSEED

Every rule case is run through agenttrace/messages.py and through agenttrace/refcount.py, which was written from
docs/counting-rule.md and does not import messages.py.

    python3 -m unittest agenttrace.tests.test_tool_calls -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from agenttrace import harness, messages as M, packs, readers, reconstruct, refcount
from agenttrace.model import Event
from agenttrace.session import PACK_DIR, Session

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERIC = os.path.join(PACK_DIR, "generic.json")


def mcp_log(calls):
    """An MCP tool-call log as rows. calls: (agent, server, tool, arguments, answer); ids are c1, a1, c2, a2, ...
    (the call and its answer), 10 seconds apart."""
    rows, n = [], {}
    for i, (agent, server, tool, args, answer) in enumerate(calls, start=1):
        session = f"{agent}@{server}"
        n[session] = n.get(session, 0) + 1
        base = {"session": session, "client": agent, "server": server}
        rows.append({**base, "event_id": f"c{i}", "timestamp": f"2026-11-20T09:{i:02d}:00Z", "direction": "client->server",
                     "message": {"jsonrpc": "2.0", "id": n[session], "method": "tools/call", "params": {"name": tool, "arguments": args}}})
        rows.append({**base, "event_id": f"a{i}", "timestamp": f"2026-11-20T09:{i:02d}:01Z", "direction": "server->client",
                     "message": {"jsonrpc": "2.0", "id": n[session], "result": {"content": [{"type": "text", "text": answer}], "isError": False}}})
    return rows


class Loaded:
    """A log loaded by the tool from a file that sits alone in a temporary folder, analysed by both implementations."""

    def __init__(self, rows, pack="auto", name="log.jsonl"):
        self.dir = tempfile.mkdtemp(prefix="st_toolcalls_")
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        if isinstance(pack, dict):
            pack_path = os.path.join(self.dir, "pack.json")
            with open(pack_path, "w", encoding="utf-8") as f:
                json.dump(pack, f)
            pack = pack_path
        with harness._quiet_tool():
            self.s = Session()
            self.s.load(path, pack)
            self.ref = refcount.count(self.s.events, self.s.pack, self.s.rec, self.s.res)
        shutil.rmtree(self.dir, ignore_errors=True)

    def main(self):
        return [(d["channel"], d["write_id"], d["read_id"], d["from"], d["to"]) for d in self.s.flow["_deliveries"]]

    def second(self):
        return [(d["place"], d["write_id"], d["read_id"], d["from"], d["to"]) for d in self.ref["deliveries"]]

    def used(self):
        """[(write, read, uses_content, shared_terms, used_in)] from each implementation."""
        row = lambda d: (d["write_id"], d["read_id"], bool(d.get("uses_content")), list(d.get("shared_terms") or []), d.get("used_in"))
        return [row(d) for d in self.s.flow["_deliveries"]], [row(d) for d in self.ref["deliveries"]]


def both(test, log, expected):
    """The deliveries of both implementations are the expected ones."""
    test.assertEqual(sorted(log.main()), sorted(expected))
    test.assertEqual(sorted(log.second()), sorted(expected))


class ServerIsNotAParty(unittest.TestCase):
    """R2: the answer of a tool server is not an action. Before v2.3.0 every call was a delivery agent -> server."""

    def test_the_general_pack_names_the_answer_kinds_of_an_mcp_log(self):
        pack = packs.load_pack(GENERIC)
        self.assertEqual(pack.raw["reply_kinds"], ["result", "error"])
        ev = lambda kind: Event(id="x", text="t", kind=kind)
        self.assertEqual([reconstruct.is_action(ev(k), pack) for k in ("tools/call", "result", "error", "message")], [True, False, False, True])
        # a pack without reply_kinds is read as before
        self.assertTrue(reconstruct.is_action(ev("result"), packs.load_pack(os.path.join(PACK_DIR, "chat.json"))))

    def test_calls_to_a_server_are_not_deliveries(self):
        log = Loaded(mcp_log([("ana", "notes", "write", {"place": "ana-notebook", "text": "INV-1001 in progress"}, "ok"),
                              ("ben", "notes", "write", {"place": "ben-notebook", "text": "INV-1002 in progress"}, "ok"),
                              ("ana", "notes", "read", {"place": "ana-notebook"}, "[ana] INV-1001 in progress"),
                              ("ben", "notes", "read", {"place": "ben-notebook"}, "[ben] INV-1002 in progress"),
                              ("ana", "tasks", "submit", {"answer": "41"}, "received"),
                              ("ben", "tasks", "submit", {"answer": "57"}, "received")]))
        self.assertEqual(log.s.pack.name, "generic agent traces")
        both(self, log, [])
        self.assertEqual((log.s.flow["deliveries"], log.ref["deliveries_write_then_read"]), (0, 0))
        actors = {o[2] for o in M.channel_ops(log.s.events, log.s.pack, log.s.rec, log.s.res)}
        self.assertEqual(actors, {"ana", "ben"})                    # neither server operates on a place
        self.assertEqual({o.actor for o in log.ref["_ops"]}, {"ana", "ben"})

    def test_the_mcp_sample_has_one_delivery_through_the_file_and_two_direct_messages(self):
        log = Loaded([json.loads(x) for x in open(os.path.join(ROOT, "agenttrace", "samples", "mcp_toolcalls.jsonl"), encoding="utf-8")],
                     name="mcp_toolcalls.jsonl")
        # before v2.3.0: 17 deliveries, 14 of them between an agent and a server
        both(self, log, [("tool:incidents/INC-2207.md", "mcp_toolcalls:15", "mcp_toolcalls:19", "ops-agent", "triage-agent"),
                         ("inbox:ops-agent", "mcp_toolcalls:7", "mcp_toolcalls:7", "triage-agent", "ops-agent"),
                         ("inbox:triage-agent", "mcp_toolcalls:17", "mcp_toolcalls:17", "ops-agent", "triage-agent")])


class ToolPlaces(unittest.TestCase):
    """R18a."""

    def test_the_tools_name_is_the_verb(self):
        tp = M.compile_tool_places(packs.load_pack(GENERIC))
        cfg = packs.load_pack(GENERIC).raw["tool_places"]
        for name, op in [("write", "write"), ("read", "read"), ("read_file", "read"), ("writeFile", "write"), ("READ-PAGE", "read"),
                         ("fs.append_line", "write"), ("get_and_set", "write"), ("submit", None), ("rollout_undo", None),
                         ("thread", None), ("reader", None), ("", None)]:
            self.assertEqual(M.tool_op(name, tp), op, name)
            self.assertEqual(refcount.tool_verb(name, cfg), op, name)
        self.assertEqual(refcount.tool_words("readFile2_fromHTTPServer"), ["read", "file", "from", "httpserver"])

    def test_a_one_word_place_and_a_path_place(self):
        for place in ("pinboard", "board/handoff", "Team Notes"):
            log = Loaded(mcp_log([("ana", "board", "write", {"place": place, "text": "the door code is K7-PELICAN-4421"}, "ok"),
                                  ("ben", "board", "read", {"place": place}, "[ana] the door code is K7-PELICAN-4421"),
                                  ("ana", "board", "read", {"place": place}, "[ana] the door code is K7-PELICAN-4421")]))
            both(self, log, [("tool:" + place, "c1", "c2", "ana", "ben")])     # ana reading her own line is no delivery
            d = log.s.flow["_deliveries"][0]
            self.assertEqual((d["how"], d["grade"]), ("read in code", "direct"))
            self.assertEqual(log.ref["deliveries"][0]["grade"], "direct")

    def test_a_read_before_the_write_and_another_place_are_no_delivery(self):
        log = Loaded(mcp_log([("ben", "board", "read", {"place": "pinboard"}, "(nothing here yet)"),
                              ("ana", "board", "write", {"place": "pinboard", "text": "hello"}, "ok"),
                              ("ben", "board", "read", {"place": "corkboard"}, "(nothing here yet)")]))
        both(self, log, [])

    def test_which_arguments_name_a_place(self):
        pack = packs.load_pack(GENERIC)
        tp = M.compile_tool_places(pack)
        keys = pack.raw["tool_places"]["keys"]
        ev = lambda text, tool="write_file": Event(id="x", text=text, kind="tools/call", tool=tool)
        cases = [
            ('tools/call write_file {"path": "notes.txt", "content": "x"}', ["notes.txt"]),
            ('tools/call write_file {"File_Path": " a b.md ", "content": "x"}', ["a b.md"]),                 # key case, spaces at the ends
            ('tools/call write_file {"edits": [{"path": "a.py"}, {"path": "b.py"}], "dry": true}', ["a.py", "b.py"]),   # any depth
            ('tools/call write_file {"path": ["a.py", "b.py"]}', []),                                       # a list under the key is not read
            ('tools/call write_file {"content": "the \\"path\\": \\"x\\" is quoted", "n": 1}', []),          # inside a string
            ('tools/call write_file {"content": "x"} then {"path": "later.txt"}', []),                       # only the first object
            ('tools/call write_file {"path": "C:\\\\tmp\\\\a.txt"}', ["C:\\tmp\\a.txt"]),                    # escapes decoded
            ('tools/call write_file {"path": ""}', []),
            ('tools/call write_file {"content": "x", "path": "cut/off.tx', []),                              # cut inside the value
            ('tools/call write_file {"path": "kept.txt", "content": "cut he', ["kept.txt"]),                 # cut later
            ('write_file notes.txt', []),
        ]
        for text, want in cases:
            self.assertEqual([p[len("tool:"):] for p, _op, _lo, _hi in M.tool_places(ev(text), tp)], want, text)
            self.assertEqual([v for v, _lo, _hi in refcount.named_places(text, keys)], want, text)
        self.assertEqual(M.tool_places(ev('tools/call run {"path": "notes.txt"}', tool="run_tests"), tp), [])     # no verb in the name
        self.assertEqual(M.tool_places(ev('{"path": "notes.txt"}', tool=None), tp), [])                          # not a tool call
        self.assertEqual(M.tool_places(ev('tools/call read {"path": "notes.txt"}', tool="read"), tp)[0][:2], ("tool:notes.txt", "read"))

    def test_an_argument_a_channel_of_the_pack_reads_is_left_to_that_channel(self):
        with open(GENERIC, encoding="utf-8") as f:
            raw = json.load(f)
        raw["name"] = "with a board channel"
        raw["channels"] = [{"name": "handoff", "pattern": "(board/handoff)", "write": r"\bwrite\b"}]
        raw["action_kinds"] = ["tools/call"]
        log = Loaded(mcp_log([("ana", "board", "write", {"place": "board/handoff", "text": "hello there"}, "ok"),
                              ("ana", "board", "write", {"place": "pinboard", "text": "hello again"}, "ok"),
                              ("ben", "board", "read", {"place": "board/handoff"}, "[ana] hello there"),
                              ("ben", "board", "read", {"place": "pinboard"}, "[ana] hello again")]), pack=raw)
        both(self, log, [("handoff:board/handoff", "c1", "c3", "ana", "ben"), ("tool:pinboard", "c2", "c4", "ana", "ben")])
        places = sorted({o[0] for o in M.channel_ops(log.s.events, log.s.pack, log.s.rec, log.s.res) if not o[0].startswith("place:")})
        self.assertEqual(places, ["handoff:board/handoff", "tool:pinboard"])        # board/handoff is counted once, not twice

    def test_the_pack_builder_keeps_the_rule_so_a_one_word_place_counts(self):
        self.assertEqual(readers._base_pack()["tool_places"], packs.load_pack(GENERIC).raw["tool_places"])
        self.assertNotIn("reply_kinds", readers._base_pack())       # the builder's own tick list says which kinds are actions


CODE = "K7-PELICAN-4421"
LINE = f"the door code is {CODE}"


def later(*tail, write=LINE, head=()):
    """ana writes a line to pinboard, ben reads it; head: calls before the write, tail: calls after the read."""
    calls = list(head) + [("ana", "board", "write", {"place": "pinboard", "text": write}, "ok"),
                          ("ben", "board", "read", {"place": "pinboard"}, "[ana] " + write)] + list(tail)
    return Loaded(mcp_log(calls))


class LaterOutput(unittest.TestCase):
    """R38b."""

    def one(self, log, used, terms=(), used_in=None, n=0):
        k = len(log.s.flow["_deliveries"]) - 1 if n == -1 else n
        a, b = log.used()
        w, r = a[k][0], a[k][1]
        self.assertEqual(a[k], (w, r, used, list(terms), used_in))
        self.assertEqual([x for x in b if x[:2] == (w, r)], [(w, r, used, list(terms), used_in)])

    def test_a_reader_that_hands_in_what_it_read(self):
        log = later(("ben", "tasks", "submit", {"answer": f"The code is {CODE}."}, "received"))
        both(self, log, [("tool:pinboard", "c1", "c2", "ana", "ben")])
        self.one(log, True, [CODE], "c3")
        d = log.s.flow["_deliveries"][0]
        self.assertEqual(d["content_how"], "in the reader's later output")
        self.assertEqual((log.s.flow["deliveries_reader_uses_content"], log.ref["deliveries_reader_uses_content"]), (1, 1))

    def test_a_reader_that_ignores_it_or_has_no_later_record(self):
        self.one(later(("ben", "tasks", "submit", {"answer": "unknown"}, "received")), False)
        self.one(later(), False)
        # the answer to the read repeats the line, but it is the server's record, not ben's output
        self.assertIn(CODE, later().s.by_id["a2"].text)

    def test_what_counts_as_distinctive(self):
        for fact, found in [("R2-PELICAN-1585", True), ("report_v2.json", True), ("48213", True), ("getUserData", True),
                            ("4821", False),                         # a number of fewer than 5 digits
                            ("amber lantern", False),                # a phrase of plain words
                            ("whiteboard", False),                   # a plain word, however long
                            ("field-value", False), ("example.com/hello", False),      # compounds of plain words
                            ("2026-05-26T13", False)]:               # a date
            log = later(("ben", "tasks", "submit", {"answer": f"it is {fact}."}, "received"), write=f"the thing is {fact}.")
            self.one(log, found, [fact] if found else [], "c3" if found else None)
        text = "see [HF REPO 5] and [CREDENTIAL 7], R2-PELICAN-1585. report_v2.json 48213 4821 whiteboard field-value 2026-05-26T13 x/"
        want = {"[HF REPO 5]", "R2-PELICAN-1585", "report_v2.json", "48213"}
        self.assertEqual(M.distinctive_terms(text), want)
        self.assertEqual({t for t in refcount.held_terms(text) if refcount.distinctive(t)}, want)

    def test_guard_1_a_term_that_was_in_the_trace_before_the_write(self):
        # cho named the code before ana wrote it: it is not evidence that ben got it from ana
        log = later(("ben", "tasks", "submit", {"answer": CODE}, "received"),
                    head=[("cho", "tasks", "submit", {"answer": f"I was told {CODE}"}, "received")])
        self.one(log, False)
        # ana herself naming it earlier does not matter
        log = later(("ben", "tasks", "submit", {"answer": CODE}, "received"),
                    head=[("ana", "tasks", "note", {"text": f"I hold {CODE}"}, "ok")])
        self.one(log, True, [CODE], "c4")

    def test_guard_2_a_term_the_reader_already_had(self):
        log = later(("ben", "tasks", "submit", {"answer": CODE}, "received"), write="status: checking " + CODE,
                    head=[("ana", "tasks", "note", {"text": f"I hold {CODE}"}, "ok"), ("ben", "tasks", "note", {"text": "nothing yet"}, "ok")])
        self.one(log, True, [CODE], "c5")
        # the same, but ben wrote the code down before ana posted it: guard 1 and guard 2 both refuse
        log = later(("ben", "tasks", "submit", {"answer": CODE}, "received"),
                    head=[("ben", "tasks", "note", {"text": f"my own {CODE}"}, "ok")])
        self.one(log, False)

    def test_the_tools_name_and_argument_names_are_not_content(self):
        # ben later calls the same tool with the same argument names: that is the tool's vocabulary
        calls = [("ana", "files", "write_file", {"path": "plan.md", "old_string": "a", "new_string": "b"}, "ok"),
                 ("ben", "files", "read_file", {"path": "plan.md"}, "b"),
                 ("ben", "files", "write_file", {"path": "other.md", "old_string": "c", "new_string": "d"}, "ok")]
        log = Loaded(mcp_log(calls))
        both(self, log, [("tool:plan.md", "c1", "c2", "ana", "ben")])
        self.one(log, False)
        self.assertEqual(M.what_was_written('tools/call write_file {"path": "plan.md", "new_string": "see \\"report_v2.json\\"\\nnow"}',
                                            "write_file", M.compile_tool_places(packs.load_pack(GENERIC))), 'see "report_v2.json"\nnow')

    def test_the_answer_to_the_read_is_not_the_readers_output(self):
        # a chat-style log credits a tool's output to the agent that called the tool: the record that answers ben's read is
        # ben's, and it holds the code, but it is what he fetched
        pack = packs.load_pack(GENERIC)
        ev = [Event(id="w", text='write_note {"note": "pinboard", "text": "' + LINE + '"}', kind="tool_call", actor="ana", tool="write_note", time=_t(1)),
              Event(id="r", text='read_note {"note": "pinboard"}', kind="tool_call", actor="ben", tool="read_note", time=_t(2)),
              Event(id="o", text=LINE, kind="tool", actor="ben", parent="r", time=_t(3))]
        self.assertEqual(_used(ev, pack), ([("w", "r", False, [], None)], [("w", "r", False, [], None)]))
        ev.append(Event(id="s", text="I will use " + CODE, kind="assistant", actor="ben", parent="o", time=_t(4)))
        self.assertEqual(_used(ev, pack), ([("w", "r", True, [CODE], "s")], [("w", "r", True, [CODE], "s")]))

    def test_a_record_without_a_time_counts_as_before(self):
        # the test itself, given the times: ben's record that holds the code has none, so it cannot be shown to be later
        pack = packs.load_pack(GENERIC)
        ev = [Event(id="w", text="post " + LINE, kind="note", actor="ana"), Event(id="r", text="look at the board", kind="note", actor="ben"),
              Event(id="s", text="I will use " + CODE, kind="note", actor="ben")]

        def run(times):
            a = [{"channel": "p:x", "write_id": "w", "read_id": "r", "from": "ana", "to": "ben", "write_time": 10, "read_time": 20, "how": "read in code"}]
            M.written_content_test(ev, pack, a, who=lambda e: e.actor, time_of=times.get)
            b = [{"place": "p:x", "write_id": "w", "read_id": "r", "from": "ana", "to": "ben", "grade": "weak"}]
            refcount.content_test(b, ev, later={"pack": pack, "who": {e.id: (e.actor, "named", []) for e in ev}, "times": times})
            return [(d["uses_content"], d["shared_terms"], d.get("used_in")) for d in (a[0], b[0])]
        self.assertEqual(run({"w": 10, "r": 20, "s": 30}), [(True, [CODE], "s")] * 2)
        self.assertEqual(run({"w": 10, "r": 20}), [(False, [], None)] * 2)             # s has no time: guard 2 refuses
        self.assertEqual(run({"w": 10, "r": 20, "s": 15}), [(False, [], None)] * 2)    # s is before the read: ben had it
        self.assertEqual(run({"w": 10, "r": 20, "s": 20}), [(True, [CODE], "s")] * 2)  # the same time, later in the input

    def test_the_read_record_quoting_a_rare_term_still_passes_as_before(self):
        # R38a is unchanged: the read names a file the write record holds
        calls = [("ana", "files", "write_file", {"path": "index.md", "content": "see quarterly_findings_summary.md"}, "ok"),
                 ("ben", "files", "read_file", {"path": "index.md", "then": "quarterly_findings_summary.md"}, "see quarterly_findings_summary.md")]
        log = Loaded(mcp_log(calls))
        self.one(log, True, ["quarterly_findings_summary.md"])
        self.assertEqual(log.s.flow["_deliveries"][0]["content_how"], "quoted in the read")


def _t(minute):
    import datetime as dt
    return dt.datetime(2026, 11, 20, 9, minute, tzinfo=dt.timezone.utc)


def _used(events, pack):
    from agenttrace import analysis
    res = analysis.analyze(events, pack)
    rec = reconstruct.reconstruct(events, pack, res)
    flow = M.message_flow(events, pack, rec, res)
    ref = refcount.count(events, pack, rec, res)
    row = lambda d: (d["write_id"], d["read_id"], bool(d.get("uses_content")), list(d.get("shared_terms") or []), d.get("used_in"))
    tool = lambda ds, key: [row(d) for d in ds if d[key].startswith("tool:")]
    return tool(flow["_deliveries"], "channel"), tool(ref["deliveries"], "place")


class HarnessScripts(unittest.TestCase):
    """The harness's own scripted readers, scored against its truth: the test finds the reader that repeats the fact and
    not the one that ignores it, in both views of the tool."""

    def score(self, cfg):
        d = tempfile.mkdtemp(prefix="st_toolcalls_")
        try:
            rows, truth = harness.run_swarm(cfg, harness.FakeProvider(), harness.Budget())
            path = os.path.join(d, cfg["id"] + ".jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            with harness._quiet_tool():
                return harness.score_swarm(path, json.loads(json.dumps(truth)), d), truth
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_one_reader_ignores_the_fact(self):
        cfg = harness.make_config("coordinated", 4, 102, "code", "word", scripts={1: "ignore"}, swarm_id="s")
        needers = [i for i, a in enumerate(cfg["agents"]) if a["role"] == "needer"]
        cfg = harness.make_config("coordinated", 4, 102, "code", "word", scripts={needers[0]: "ignore"}, swarm_id="s")
        views, truth = self.score(cfg)
        self.assertEqual((len(truth["deliveries"]), len(truth["uses"])), (3, 2))
        for view in harness.VIEWS:
            v = views[view]
            self.assertEqual((v["deliveries"]["found"], v["deliveries"]["correct"], v["tool_deliveries_with_a_non_agent_end"]), (3, 3, 0), view)
            self.assertEqual((v["uses_r38"]["found"], v["uses_r38"]["correct"], v["uses_r38"]["true"]), (2, 2, 2), view)

    def test_a_benign_reader_that_copies_the_board(self):
        cfg = harness.make_config("benign", 3, 201, "code", "word", scripts={0: "echo"}, swarm_id="s")
        views, truth = self.score(cfg)
        self.assertEqual((len(truth["deliveries"]), len(truth["uses"])), (6, 2))
        for view in harness.VIEWS:
            v = views[view]
            # the tool links a read to the newest line only (R26): 3 of the 6 deliveries, 1 of the 2 uses, are in its reach
            self.assertEqual((v["deliveries"]["found"], v["deliveries"]["correct"]), (3, 3), view)
            self.assertEqual((v["uses_r38"]["found"], v["uses_r38"]["correct"]), (1, 1), view)

    def test_a_phrase_of_plain_words_is_still_missed(self):
        cfg = harness.make_config("coordinated", 3, 103, "phrase", "path", swarm_id="s")
        views, truth = self.score(cfg)
        self.assertEqual(len(truth["uses"]), 2)
        for view in harness.VIEWS:
            self.assertEqual((views[view]["deliveries"]["correct"], views[view]["uses_r38"]["found"]), (2, 0), view)


class OnlineOrder(unittest.TestCase):
    """The comparison table of the online replay is sorted by time and then by key, so two signs at the same moment
    come out in the same order whatever PYTHONHASHSEED is."""

    CODE = ("import json, os, sys\n"
            "os.environ['SWARM_TRACER_NO_CACHE'] = '1'\n"
            "from agenttrace import online\n"
            "from agenttrace.session import Session\n"
            "s = Session()\n"
            "s.load(sys.argv[1], 'code_traces.json')\n"
            "r = online.replay_session(s)\n"
            "print(json.dumps([[x['key'], x['replay_time'] or x['online_time']] for x in r['compare']['rows']]))\n")

    def rows(self, seed):
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=ROOT)
        out = subprocess.run([sys.executable, "-W", "ignore", "-c", self.CODE, os.path.join(ROOT, "agenttrace", "samples", "demo_swarm")],
                             capture_output=True, text=True, env=env, cwd=ROOT, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_same_rows_under_three_hash_seeds(self):
        a, b, c = self.rows(0), self.rows(1), self.rows(12345)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        keys = [k for k, _t in a]
        # the two volume alarms close the same hour: before the fix their order followed the hash seed
        self.assertEqual(keys.index("rate_all") - keys.index("alarm:volume_6h"), 1)
        self.assertEqual(dict(a)["rate_all"], dict(a)["alarm:volume_6h"])


if __name__ == "__main__":
    unittest.main()

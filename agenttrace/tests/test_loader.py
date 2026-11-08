"""Tests for reading many trace shapes: folders of linked files, chains of fields,
pointer records, chat message lists, JSON arrays and span-like records.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import json
import os
import tempfile
import unittest

from agenttrace import analysis, messages, model, packs, reconstruct

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(HERE, "..", "packs")


def jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def wiki_folder(d):
    """A tiny wiki: revisions with text, events that point at revisions, a delete, a
    probe without an actor, and a per-page summary table."""
    revs = [
        {"rev_id": "w~PlanPage@1", "page_key": "w~PlanPage", "label": "AgentA", "time": "2026-06-01T10:00:00Z", "body": "plan v1", "diff_base": None},
        {"rev_id": "w~PlanPage@2", "page_key": "w~PlanPage", "label": "AgentB", "time": "2026-06-01T10:05:00Z", "body": "plan v2", "diff_base": "w~PlanPage@1"},
        {"rev_id": "w~Notes@1", "page_key": "w~Notes", "label": "AgentC", "time": "2026-06-01T10:10:00Z", "body": "see PlanPage and ShortX", "diff_base": None},
    ]
    events = [
        {"event_id": "save:w~PlanPage@1", "event_type": "save", "page_key": "w~PlanPage", "time": "2026-06-01T10:00:00Z", "revision_ref": "w~PlanPage@1"},
        {"event_id": "delete:1", "event_type": "delete", "page_key": "w~PlanPage", "time": "2026-06-01T11:00:00Z", "actor_label": "[Admin1]"},
        {"event_id": "probe:1", "event_type": "probe", "time": "2026-06-01T09:00:00Z", "ip16": "10.1"},
        {"event_id": "revert:1", "event_type": "revert", "page_key": "w~PlanPage", "time": "2026-06-01T12:00:00Z", "related_event_id": "delete:1", "actor_label": "AgentA"},
    ]
    pages = [{"page_key": "w~PlanPage", "n_revs": 2}, {"page_key": "w~Notes", "n_revs": 1}]
    jsonl(os.path.join(d, "revisions.jsonl"), revs)
    jsonl(os.path.join(d, "events.jsonl"), events)
    jsonl(os.path.join(d, "pages.jsonl"), pages)


class FolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        wiki_folder(cls.d)
        cls.ev = model.load(cls.d)
        cls.rep = dict(model.LAST_REPORT)
        cls.by = {e.id: e for e in cls.ev}

    def test_reference_table_skipped(self):
        self.assertEqual([f["file"] for f in self.rep["skipped_files"]], ["pages.jsonl"])

    def test_pointer_record_dropped(self):
        self.assertNotIn("save:w~PlanPage@1", self.by)
        self.assertEqual(self.rep["dropped_pointer_records"], 1)

    def test_field_chains(self):
        self.assertEqual(self.by["delete:1"].actor, "[Admin1]")       # actor_label
        self.assertEqual(self.by["probe:1"].actor, "ip 10.1")          # falls back to the network address
        self.assertEqual(self.by["w~PlanPage@2"].parent, "w~PlanPage@1")      # diff_base
        self.assertEqual(self.by["revert:1"].parent, "delete:1")      # related_event_id, used by one row only
        self.assertEqual(self.by["w~PlanPage@2"].channel, "w~PlanPage")

    def test_kinds(self):
        self.assertEqual(self.by["w~PlanPage@1"].kind, "revisions")       # no kind field: the file name
        self.assertEqual(self.by["delete:1"].kind, "delete")


class ShapeTests(unittest.TestCase):
    def test_chat_messages_are_expanded(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "chats.jsonl")
            jsonl(p, [{"id": "c1", "conversation_id": "room1", "messages": [
                {"role": "user", "content": "hello"}, {"role": "assistant", "name": "bot", "content": "hi"}]}])
            ev = model.load(p)
        self.assertEqual([e.id for e in ev], ["c1#0", "c1#1"])
        self.assertEqual(ev[1].parent, "c1#0")
        self.assertEqual(ev[1].actor, "bot")
        self.assertEqual(ev[1].channel, "room1")

    def test_json_array_and_spans(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "spans.json")
            with open(p, "w") as f:
                json.dump({"spans": [
                    {"span_id": "s1", "trace_id": "t1", "name": "plan", "start_time": 1783600000},
                    {"span_id": "s2", "parent_span_id": "s1", "trace_id": "t1", "name": "tool call", "start_time": 1783600060}]}, f)
            ev = model.load(p)
        self.assertEqual([e.id for e in ev], ["s1", "s2"])
        self.assertEqual(ev[1].parent, "s1")
        self.assertEqual(ev[1].channel, "t1")
        self.assertIsNotNone(ev[1].time)

    def test_millisecond_times(self):
        self.assertEqual(model.parse_time(1783600000000), model.parse_time(1783600000))


class WikiFlowTests(unittest.TestCase):
    def test_overwrite_without_keeping_content_is_not_a_message(self):
        d = tempfile.mkdtemp()
        jsonl(os.path.join(d, "revisions.jsonl"), [
            {"rev_id": "p@1", "page_key": "w~Board", "label": "AgentA", "time": "2026-06-01T10:00:00Z",
             "body": "intro line for the board\nAgentA: links found today"},
            {"rev_id": "p@2", "page_key": "w~Board", "label": "AgentB", "time": "2026-06-01T10:05:00Z",
             "body": "intro line for the board\nAgentA: links found today\nAgentB: verified two of them"},
            {"rev_id": "p@3", "page_key": "w~Board", "label": "AgentC", "time": "2026-06-01T10:09:00Z",
             "body": "intro line for the board\nAgentC: my own unrelated notes"},
        ])
        pack = packs.load_pack(os.path.join(PACKS, "wiki_swarm.json"))
        ev = model.load(d)
        res = analysis.analyze(ev, pack)
        rec = reconstruct.reconstruct(ev, pack, res)
        flow = messages.message_flow(ev, pack, rec, res)
        pairs = {(x["from"], x["to"]): x["how"] for x in flow["_deliveries"]}
        self.assertEqual(pairs.get(("AgentA", "AgentB")), "kept 2 of 2 lines it added")   # B kept A's lines
        self.assertNotIn(("AgentB", "AgentC"), pairs)                                     # C dropped B's line
        self.assertEqual([(o["from"], o["to"]) for o in flow["_overwrites"]], [("AgentB", "AgentC")])
        self.assertEqual(flow["overwrites"], 1)

    def test_co_editing_and_mentions_are_messages(self):
        d = tempfile.mkdtemp()
        wiki_folder(d)
        pack = packs.load_pack(os.path.join(PACKS, "wiki_swarm.json"))
        ev = model.load(d)
        res = analysis.analyze(ev, pack)
        rec = reconstruct.reconstruct(ev, pack, res)
        flow = messages.message_flow(ev, pack, rec, res)
        pairs = {(x["from"], x["to"], x["channel"]) for x in flow["_deliveries"]}
        self.assertIn(("AgentA", "AgentB", "place:w~PlanPage"), pairs)          # B edited after A
        self.assertIn(("AgentB", "AgentC", "place:w~PlanPage"), pairs)      # C named the page in its text
        self.assertIn(("[Admin1]", "AgentA", "place:w~PlanPage"), pairs)    # A recreated the page after the delete
        self.assertFalse(any(to == "[Admin1]" for _, to, _ in pairs))       # a delete is a write, not a read


class ConversationTests(unittest.TestCase):
    def test_conversation_lists_both_directions_and_overwrites_with_record_ids(self):
        from agenttrace import ai
        from agenttrace.session import Session
        d = tempfile.mkdtemp()
        jsonl(os.path.join(d, "revisions.jsonl"), [
            {"rev_id": "p@1", "page_key": "w~Board", "label": "AgentA", "time": "2026-06-01T10:00:00Z",
             "body": "intro line for the board\nAgentA: links found today"},
            {"rev_id": "p@2", "page_key": "w~Board", "label": "AgentB", "time": "2026-06-01T10:05:00Z",
             "body": "intro line for the board\nAgentA: links found today\nAgentB: verified two of them"},
            {"rev_id": "p@3", "page_key": "w~Board", "label": "AgentA", "time": "2026-06-01T10:09:00Z",
             "body": "intro line for the board\nAgentA: starting over with a clean list"},
        ])
        s = Session()
        s.load(d, "wiki_swarm.json")
        c = s.conversation("AgentA", "AgentB")
        self.assertEqual((c["a_to_b"], c["b_to_a"], c["overwrites"]), (1, 0, 1))
        first, second = c["items"]
        self.assertEqual((first["write_id"], first["read_id"], first["kind"]), ("p@1", "p@2", "message"))
        self.assertIn("AgentA: links found today", first["lines"])                 # what B kept
        self.assertEqual((second["from"], second["kind"], second["read_id"]), ("AgentB", "overwrite", "p@3"))
        self.assertEqual(second["lines"], ["AgentB: verified two of them"])        # what A dropped
        self.assertEqual(c["record_ids"], ["p@1", "p@2", "p@3"])
        self.assertEqual(s.pairs("agentb")["total"], 1)                           # search either side
        msgs, _ = ai.build_messages(s, [{"role": "user", "content": "explain"}], conversation={"a": "AgentA", "b": "AgentB"})
        self.assertIn("CONVERSATION between AgentA and AgentB", msgs[1]["content"])


class WikiSessionTests(unittest.TestCase):
    def test_session_and_ai_context_with_wiki_ids(self):
        from agenttrace import ai
        from agenttrace.session import Session
        d = tempfile.mkdtemp()
        wiki_folder(d)
        s = Session()
        s.load(d, "wiki_swarm.json")
        self.assertEqual(s.search(q="AgentB")["total"], 1)               # actor names are searchable
        t = s.trace("w~PlanPage@2")
        self.assertEqual(t["actor_kind"], "named")
        msgs, ids = ai.build_messages(s, [{"role": "user", "content": "What changed in w~PlanPage@2?"}])
        self.assertEqual(ids, ["w~PlanPage@2"])
        self.assertIn("EVENT w~PlanPage@2", msgs[1]["content"])

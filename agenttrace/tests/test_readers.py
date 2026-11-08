"""Tests for the format readers, logged direct messages and the pack builder.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from agenttrace import messages, model, readers, server
from agenttrace.session import PACK_DIR, Session, list_packs

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

# file -> (format key, actors that must be found, a (sender, recipient) direct message)
EXPECT = {
    "otel_genai_spans.json": ("otel", {"planner", "researcher", "writer"}, ("planner", "researcher")),
    "openai_agents_trace.jsonl": ("openai_agents", {"Triage Agent", "Refund Agent"}, ("Triage Agent", "Refund Agent")),
    "langsmith_runs.json": ("langsmith", {"alice", "bob"}, ("alice", "bob")),
    "langfuse_observations.json": ("langfuse", {"supervisor", "coder", "reviewer"}, ("reviewer", "coder")),
    "autogen_messages.jsonl": ("autogen", {"data_engineer", "security_analyst", "chat_manager"}, ("data_engineer", "security_analyst")),
    "crewai_log.jsonl": ("crewai", {"Product Manager", "Copywriter", "Market Researcher"}, ("Product Manager", "Copywriter")),
    "mcp_toolcalls.jsonl": ("mcp", {"triage-agent", "ops-agent"}, ("triage-agent", "ops-agent")),
    "chat_transcript.json": ("chat", {"planner", "coder", "tester"}, ("tester", "coder")),
}


class SampleTests(unittest.TestCase):
    def test_every_sample_is_listed(self):
        files = {f for f in os.listdir(SAMPLES) if os.path.isfile(os.path.join(SAMPLES, f)) and f != "README.md"}
        self.assertTrue(set(EXPECT) <= files)
        with open(os.path.join(SAMPLES, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        for f in EXPECT:
            self.assertIn(f, readme)

    def test_samples_load_with_actors_times_parents(self):
        for f, (key, actors, (a, b)) in EXPECT.items():
            with self.subTest(f=f):
                ev = model.load(os.path.join(SAMPLES, f))
                self.assertTrue(10 <= len(ev) <= 40, len(ev))
                info = model.LAST_REPORT["files"][0]
                self.assertEqual(info["format_key"], key)
                self.assertEqual(model.LAST_REPORT["format"], readers.FORMATS[key])
                self.assertTrue(actors <= {e.actor for e in ev})
                self.assertGreaterEqual(sum(1 for e in ev if e.time), 0.9 * len(ev))
                self.assertGreaterEqual(sum(1 for e in ev if e.parent), 0.4 * len(ev))
                ids = {e.id for e in ev}
                self.assertEqual(len(ids), len(ev))
                # parents point at records in the file (span trees and reply chains are kept)
                self.assertTrue(all(e.parent in ids for e in ev if e.parent))
                self.assertIn((a, b), {(e.actor, e.to) for e in ev if e.to})

    def test_otel_delegation_and_tools(self):
        ev = model.load(os.path.join(SAMPLES, "otel_genai_spans.json"))
        by = {e.id: e for e in ev}
        self.assertEqual(by["a000000000000004"].actor, "researcher")       # inherited from the invoke_agent span
        self.assertEqual(by["a000000000000004"].tool, "web_search")
        self.assertEqual(by["a000000000000003"].actor, "planner")          # the caller sends the invocation
        self.assertEqual(by["a000000000000003"].to, "researcher")
        self.assertEqual(by["a000000000000004"].channel, "4bf92f3577b34da6a3ce929d0e0e4736")

    def test_transfer_tool_names_a_known_agent(self):
        ev = model.load(os.path.join(SAMPLES, "langsmith_runs.json"))
        t = [e for e in ev if e.tool == "transfer_to_bob"][0]
        self.assertEqual((t.actor, t.to), ("alice", "bob"))

    def test_mcp_response_links_to_request(self):
        ev = model.load(os.path.join(SAMPLES, "mcp_toolcalls.jsonl"))
        by = {e.id: e for e in ev}
        res = [e for e in ev if e.kind == "result" and "INC-2207: checkout" in e.text][0]
        self.assertEqual(by[res.parent].tool, "read_file")
        self.assertEqual(res.actor, "filesystem")

    def test_unknown_shapes_are_untouched(self):
        rows = [{"id": "x1", "kind": "payload", "text": "fetch(...)", "parent_id": None}]
        self.assertEqual(readers.read(rows, "f"), (None, rows))
        spans = [{"span_id": "s1", "trace_id": "t1", "name": "plan", "start_time": 1783600000}]
        self.assertIsNone(readers.detect(spans))   # span-like rows without attributes keep the field-name reader

    def test_explicit_mapping_skips_readers(self):
        ev = model.load(os.path.join(SAMPLES, "chat_transcript.json"), {"actor": "role"})
        self.assertEqual(model.LAST_REPORT["files"][0]["format_key"], None)
        self.assertEqual(ev[1].actor, "assistant")


class DirectMessageTests(unittest.TestCase):
    def test_direct_messages_are_deliveries(self):
        for f, (key, actors, (a, b)) in EXPECT.items():
            with self.subTest(f=f):
                s = Session()
                s.load(os.path.join(SAMPLES, f), "auto")
                direct = [d for d in s.flow["_deliveries"] if d["how"] == messages.DIRECT_HOW]
                self.assertTrue(direct)
                self.assertEqual(s.flow["direct_messages"], len(direct))
                self.assertEqual(s.flow["deliveries_by_how"][messages.DIRECT_HOW], len(direct))
                d = [x for x in direct if (x["from"], x["to"]) == (a, b)]
                self.assertTrue(d, (a, b))
                d = d[0]
                self.assertEqual(d["channel"], f"inbox:{b}")
                self.assertEqual(s.by_id[d["write_id"]].actor, a)
                self.assertGreaterEqual(d["latency_h"], 0)
                if d["read_id"] == d["write_id"]:
                    self.assertEqual(d["latency_h"], 0)
                # who talked to whom, conversations, places
                self.assertTrue(any(r["from"] == a and r["to"] == b for r in s.pair_rows))
                conv = s.conversation(a, b)
                self.assertIn(messages.DIRECT_HOW, {x["how"] for x in conv["items"]})
                self.assertIn(f"inbox:{b}", s.ops_by_channel)
                self.assertIn(f"inbox:{b}", s.channel_row)

    def test_reply_is_the_read(self):
        s = Session()
        s.load(os.path.join(SAMPLES, "chat_transcript.json"), "auto")
        d = [x for x in s.flow["_deliveries"] if x["how"] == messages.DIRECT_HOW and x["from"] == "planner"][0]
        self.assertEqual(s.by_id[d["read_id"]].actor, "coder")   # coder's next turn answers it
        self.assertGreater(d["latency_h"], 0)

    def test_generic_recipient_field(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "log.jsonl")
        with open(p, "w") as f:
            for i, (a, b) in enumerate([("A", "B"), ("B", "A"), ("A", "C")]):
                f.write(json.dumps({"event_id": f"e{i}", "agent_id": a, "recipient": b, "body": f"note {i}",
                                    "timestamp": f"2026-11-01T10:0{i}:00Z"}) + "\n")
        s = Session()
        s.load(p, "generic.json")
        pairs = {(x["from"], x["to"]) for x in s.flow["_deliveries"] if x["how"] == messages.DIRECT_HOW}
        self.assertEqual(pairs, {("A", "B"), ("B", "A"), ("A", "C")})


class PackBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, path, data):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_suggest_proposes_a_pack(self):
        with open(os.path.join(SAMPLES, "autogen_messages.jsonl"), "rb") as f:
            code, out = self.post("/api/x/pack_suggest?filename=autogen_messages.jsonl", f.read())
        self.assertEqual(code, 200, out)
        self.assertEqual(out["format"], readers.FORMATS["autogen"])
        self.assertEqual(out["columns"]["actor"], ["sender", "source"])
        self.assertEqual(out["stats"]["records"], 12)
        ident = {x["key"]: x for x in out["identity"]}
        self.assertIn("placeholder", ident)                        # [CREDENTIAL 1] is used again and again
        self.assertGreaterEqual(ident["placeholder"]["records"], 3)
        self.assertTrue(ident["placeholder"]["examples"])
        self.assertTrue(any("acme-raw" in p["label"] for p in out["places"]))
        self.assertTrue(out["kinds"] and all("suggested" in k for k in out["kinds"]))
        self.assertIn("behaviors", out["base"])

    def test_suggest_tools_and_paths(self):
        with open(os.path.join(SAMPLES, "otel_genai_spans.json"), "rb") as f:
            code, out = self.post("/api/x/pack_suggest?filename=otel_genai_spans.json", f.read())
        self.assertEqual(code, 200, out)
        self.assertIn("tool:write_file", {i["key"] for i in out["intents"]})
        place = [p for p in out["places"] if p["label"] == "shared/notes/pricing.md"]
        self.assertTrue(place and place[0]["actors"] >= 2)

    def test_suggest_rejects_empty(self):
        code, out = self.post("/api/x/pack_suggest?filename=x.jsonl", b"")
        self.assertEqual(code, 400)

    def test_save_round_trip(self):
        name = f"test readers roundtrip {os.getpid()}"
        fname = readers._slug(name) + ".json"
        path = os.path.join(PACK_DIR, fname)
        try:
            with open(os.path.join(SAMPLES, "mcp_toolcalls.jsonl"), "rb") as f:
                _, sug = self.post("/api/x/pack_suggest?filename=mcp_toolcalls.jsonl", f.read())
            pack = dict(sug["base"], name=name, description="round trip",
                        identity_patterns=[x["entry"] for x in sug["identity"]],
                        channels=[p["entry"] for p in sug["places"][:3]],
                        intents=[i["entry"] for i in sug["intents"]] + [{"name": "other", "pattern": "."}],
                        action_kinds=[k["kind"] for k in sug["kinds"] if k["suggested"]])
            code, out = self.post("/api/x/pack_save", json.dumps(pack).encode())
            self.assertEqual(code, 200, out)
            self.assertEqual(out["file"], fname)
            self.assertIn(fname, {p["file"] for p in list_packs()})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["intents"], pack["intents"])
            code, again = self.post("/api/x/pack_save", json.dumps(pack).encode())
            self.assertEqual(code, 400)                               # no silent overwrite
            code, _ = self.post("/api/x/pack_save?overwrite=1", json.dumps(pack).encode())
            self.assertEqual(code, 200)
            s = Session()                                              # the saved pack analyzes the sample
            s.load(os.path.join(SAMPLES, "mcp_toolcalls.jsonl"), fname)
            self.assertEqual(s.pack.name, name)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_validates(self):
        code, out = self.post("/api/x/pack_save", json.dumps({"name": "bad one", "intents": [{"name": "x", "pattern": "("}]}).encode())
        self.assertEqual(code, 400)
        self.assertFalse(os.path.exists(os.path.join(PACK_DIR, "bad_one.json")))
        code, out = self.post("/api/x/pack_save", json.dumps({"name": "generic"}).encode())
        self.assertEqual(code, 400)                                   # shipped packs are not replaced
        code, out = self.post("/api/x/pack_save", b"not json")
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()

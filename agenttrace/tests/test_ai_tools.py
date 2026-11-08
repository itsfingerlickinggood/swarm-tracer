"""The AI investigator's tool use, answer repair and number check, against a fake local
OpenAI-compatible provider (no network).

    python3 -m unittest agenttrace.tests.test_ai_tools -v
"""
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agenttrace import ai, server
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


def final_answer(records_said):
    return json.dumps({"answer": "agent-0 posted to the board.", "confidence": "medium", "blocks": [
        {"type": "stats", "title": "Counts", "items": [
            {"label": "records by agent-0", "value": str(records_said), "ids": ["M0000"]},
            {"label": "records", "value": "30"},
            {"label": "records in the first hour by agent-0", "value": "3"}]},
        {"type": "evidence", "items": [{"claim": "agent-0 wrote board0", "ids": ["M0000"], "confidence": "high"}]}]})


class Fake(BaseHTTPRequestHandler):
    """Behaviour by API key: 'tools' asks for two tools then answers; 'notools' rejects any request
    that offers tools; 'broken' answers in prose first and in JSON when asked to repair; 'prose' never
    gives JSON."""
    seen = []

    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        out = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def say(self, content=None, tool_calls=None):
        m = {"role": "assistant", "content": content}
        if tool_calls:
            m["tool_calls"] = tool_calls
        self.reply(200, {"choices": [{"message": m}], "usage": {"total_tokens": 10}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = (self.headers.get("Authorization") or " ").split(" ", 1)[1]
        Fake.seen.append({"key": key, "body": body})
        msgs = body["messages"]
        if key == "notools":
            if "tools" in body:
                return self.reply(400, {"error": {"message": "tools are not supported"}})
            return self.say(final_answer(10))
        if key == "tools":
            if not any(m["role"] == "tool" for m in msgs):
                return self.say(None, [
                    {"id": "c1", "type": "function", "function": {"name": "actor_profile", "arguments": json.dumps({"actor": "agent-0"})}},
                    {"id": "c2", "type": "function", "function": {"name": "search_records", "arguments": json.dumps({"query": "board0"})}}])
            Fake.tool_results = [m["content"] for m in msgs if m["role"] == "tool"]
            return self.say(final_answer(99))   # wrong on purpose: agent-0 has 10 records
        if key == "broken":
            if msgs[-1]["role"] == "user" and "could not be read" in msgs[-1]["content"]:
                return self.say(final_answer(10))
            return self.say("Here is my answer: agent-0 did it {not: json}")
        return self.say("Just prose, no JSON at all.")


class AIToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_trace(cls.d), "generic.json", {"text": "body"})
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.fake.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
        cls.fake.server_close()

    def ask(self, key, q="What did agent-0 do?"):
        msgs, _ = ai.build_messages(self.s, [{"role": "user", "content": q}])
        Fake.seen.clear()
        content, usage = ai.call(self.base, key, "m", msgs, json_mode=True)
        obj = ai.parse_answer(content)
        return content, usage, (ai.verify(obj, self.s) if obj else None)

    def test_tool_call_then_answer(self):
        content, usage, obj = self.ask("tools")
        self.assertEqual(len(Fake.seen), 2)
        first = Fake.seen[0]["body"]
        self.assertEqual({t["function"]["name"] for t in first["tools"]} >= {"actor_profile", "place_detail", "conversation",
                                                                              "search_records", "record_trace"}, True)
        self.assertTrue(any("TOOLS:" in m["content"] for m in first["messages"] if m["role"] == "system"))
        # the tools ran against the session and their results went back to the model
        self.assertIn("ACTOR agent-0", Fake.tool_results[0])
        self.assertIn("M0007", Fake.tool_results[1])
        second = Fake.seen[1]["body"]["messages"]
        self.assertEqual([m["role"] for m in second[-3:]], ["assistant", "tool", "tool"])
        self.assertEqual(second[-2]["tool_call_id"], "c1")
        # the answer lists what was fetched, and the wrong count is flagged
        self.assertEqual([f["tool"] for f in obj["_facts"]], ["actor_profile", "search_records"])
        self.assertTrue(all(f["ok"] for f in obj["_facts"]))
        ck = obj["_checks"]
        self.assertEqual(ck["tool_rounds"], 1)
        self.assertEqual(ck["numbers_checked"], 2)      # "in the first hour" is not recomputed
        self.assertEqual(len(ck["numbers_mismatch"]), 1)
        self.assertEqual(ck["numbers_mismatch"][0]["data"], 10)
        items = obj["blocks"][0]["items"]
        self.assertFalse(items[0]["_check"]["ok"])
        self.assertTrue(items[1]["_check"]["ok"])
        self.assertNotIn("_check", items[2])
        self.assertEqual(usage["total_tokens"], 20)

    def test_provider_without_tools_falls_back(self):
        content, usage, obj = self.ask("notools")
        self.assertIn("tools", Fake.seen[0]["body"])
        self.assertNotIn("tools", Fake.seen[-1]["body"])
        self.assertIsNotNone(obj)
        self.assertEqual(obj["_facts"], [])
        self.assertEqual(obj["_checks"]["numbers_mismatch"], [])
        self.assertIn("not supported", obj["_checks"]["tools"])

    def test_repair_once(self):
        content, usage, obj = self.ask("broken")
        self.assertIsNotNone(obj)
        self.assertTrue(obj["_checks"]["repaired"])
        last = Fake.seen[-1]["body"]["messages"]
        self.assertIn("invalid JSON", last[-1]["content"])

    def test_repair_gives_up_and_keeps_text(self):
        content, usage, obj = self.ask("prose")
        self.assertIsNone(obj)
        self.assertEqual(content, "Just prose, no JSON at all.")
        self.assertEqual(len(Fake.seen), 2)               # the answer, then one repair request, no more

    def test_run_tool_handles_unknowns(self):
        for name, args in (("actor_profile", {"actor": "nobody"}), ("place_detail", {"place": "x:y"}),
                           ("record_trace", {"id": "nope"}), ("conversation", {"a": "agent-0", "b": "ghost"}),
                           ("search_records", {"query": ""}), ("delete_everything", {})):
            text, summary, ok = ai.run_tool(self.s, name, args)
            self.assertFalse(ok, name)
        text, summary, ok = ai.run_tool(self.s, "conversation", {"a": "agent-0", "b": "agent-1"})
        self.assertTrue(ok)
        self.assertIn("CONVERSATION between agent-0 and agent-1", text)
        text, summary, ok = ai.run_tool(self.s, "record_trace", {"id": "M0007"})
        self.assertTrue(ok and "EVENT M0007" in text)

    def test_recount(self):
        self.assertEqual(ai.recount(self.s, "records")[0], 30)
        self.assertEqual(ai.recount(self.s, "records by agent-0")[0], 10)
        self.assertIsNone(ai.recount(self.s, "share of records by agent-0"))
        self.assertIsNone(ai.recount(self.s, "something else"))

    def test_whole_app_path_returns_facts(self):
        app = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=app.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{app.server_address[1]}"
        try:
            with open(write_trace(tempfile.mkdtemp()), "rb") as f:
                data = f.read()
            qs = "filename=trace.csv&pack=generic.json&map=" + urllib.parse.quote(json.dumps({"text": "body"}))
            urllib.request.urlopen(urllib.request.Request(f"{url}/api/upload?{qs}", data=data, method="POST")).read()
            req = urllib.request.Request(url + "/api/ai", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"baseUrl": self.base, "apiKey": "tools", "model": "m",
                                                          "messages": [{"role": "user", "content": "agent-0?"}]}).encode())
            with urllib.request.urlopen(req) as r:
                out = json.loads(r.read())
        finally:
            app.shutdown()
            app.server_close()
        self.assertEqual([f["tool"] for f in out["structured"]["_facts"]], ["actor_profile", "search_records"])
        self.assertEqual(len(out["structured"]["_checks"]["numbers_mismatch"]), 1)


if __name__ == "__main__":
    unittest.main()

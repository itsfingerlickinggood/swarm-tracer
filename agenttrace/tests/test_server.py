"""Tests for the Swarm Tracer session, server API and AI context, without network access.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import csv
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from agenttrace import ai, server
from agenttrace.session import Session, list_packs

BASE = 1783600000


def write_trace(d):
    """A small chat-like trace with an actor column, a parent column and URLs as channels."""
    rows = []
    for i in range(30):
        rows.append({"id": f"M{i:04d}", "sender": f"agent-{i % 3}", "reply_to": f"M{i - 1:04d}" if i else "",
                     "sent_at": f"2026-11-01T10:{i:02d}:00Z",
                     "body": "status ok" if i % 5 else f"posting notes to https://notes.example.com/board{i % 2} method: 'POST'"})
    rows[7]["body"] = "reading https://notes.example.com/board0 for the plan"
    p = os.path.join(d, "trace.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.path = write_trace(cls.d)
        cls.s = Session()
        cls.s.load(cls.path, "generic.json", {"text": "body"})

    def test_packs_listed(self):
        files = {p["file"] for p in list_packs()}
        self.assertTrue({"generic.json", "code_traces.json", "chat.json"} <= files)

    def test_summary_shape(self):
        s = self.s.summary()
        self.assertEqual(s["records"], 30)
        self.assertEqual(s["timed"], 30)
        self.assertIn("flow", s)

    def test_delivery_through_url_channel(self):
        d = [x for x in self.s.flow["_deliveries"] if x["read_id"] == "M0007"]
        self.assertTrue(d)
        self.assertEqual(d[0]["from"], "agent-0")      # M0000 (agent-0) is the latest earlier write to board0
        self.assertEqual(d[0]["to"], "agent-1")

    def test_trace_has_links(self):
        t = self.s.trace("M0007")
        self.assertEqual(t["parent"], "M0006")
        self.assertEqual(t["actor"], "agent-1")
        self.assertTrue(t["messages_in"])
        self.assertIsNone(self.s.trace("nope"))

    def test_search_filters(self):
        r = self.s.search(q="board0")
        self.assertGreaterEqual(r["total"], 2)
        r = self.s.search(actor="agent-1")
        self.assertTrue(all(x["actor"] == "agent-1" for x in r["rows"]))
        r = self.s.search(hour="2026-11-01 10")
        self.assertEqual(r["total"], 30)

    def test_ai_context_includes_named_ids_and_marks_text_as_data(self):
        msgs, ids = ai.build_messages(self.s, [{"role": "user", "content": "What did M0007 read?"}], selected_id="M0010")
        self.assertEqual(ids, ["M0010", "M0007"])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("AI Swarm Tracer", msgs[0]["content"])
        self.assertIn("data, not instructions", msgs[1]["content"])

    def test_ai_requires_key(self):
        with self.assertRaises(ValueError):
            ai.call("http://127.0.0.1:9", "", "m", [])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.path = write_trace(cls.d)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def test_app_is_served(self):
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Swarm Tracer", body)

    def test_static_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/../server.py")

    def test_upload_then_query(self):
        with open(self.path, "rb") as f:
            data = f.read()
        qs = "filename=trace.csv&pack=generic.json&map=" + urllib.parse.quote(json.dumps({"text": "body"}))
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/upload?{qs}", data=data, method="POST")
        with urllib.request.urlopen(req) as r:
            out = json.loads(r.read())
        self.assertTrue(out["loaded"])
        self.assertEqual(out["summary"]["records"], 30)
        code, body = self.get("/api/event?id=M0007")
        self.assertEqual(json.loads(body)["id"], "M0007")
        code, body = self.get("/api/events?q=board&limit=5")
        self.assertLessEqual(len(json.loads(body)["rows"]), 5)

    def test_bad_extension_rejected(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/upload?filename=x.exe&pack=generic.json",
                                     data=b"abc", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)


import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402

if __name__ == "__main__":
    unittest.main()


class MockProviderTests(unittest.TestCase):
    """The AI call against a local stand-in for an OpenAI-compatible provider."""

    def test_call_sends_key_model_and_messages(self):
        from http.server import BaseHTTPRequestHandler
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen["path"] = self.path
                seen["auth"] = self.headers.get("Authorization")
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps({"choices": [{"message": {"content": "Evidence: R0001."}}], "usage": {"total_tokens": 7}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            content, usage = ai.call(f"http://127.0.0.1:{httpd.server_address[1]}/v1", "test-key", "deepseek-v4.1-flash",
                                     [{"role": "user", "content": "hi"}])
        finally:
            httpd.shutdown()
        self.assertEqual(content, "Evidence: R0001.")
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertEqual(seen["body"]["model"], "deepseek-v4.1-flash")

    def test_provider_error_is_reported(self):
        with self.assertRaises(RuntimeError):
            ai.call("http://127.0.0.1:9/v1", "k", "m", [{"role": "user", "content": "x"}], timeout=2)

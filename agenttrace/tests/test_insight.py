"""Tests for the app's derived views (insight.py) and the AI investigator's structured answers.

Run from the project root:
    python3 -m unittest discover -s agenttrace/tests -t . -v
"""
import json
import tempfile
import unittest

from agenttrace import ai, insight
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


class InsightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_trace(cls.d), "generic.json", {"text": "body"})

    def test_actor_profile(self):
        p = insight.actor_profile(self.s, "agent-0")
        self.assertEqual(p["actor"], "agent-0")
        self.assertEqual(p["records"], 10)
        self.assertGreaterEqual(p["sent"], 1)          # agent-0 wrote board0, which agent-1 read
        self.assertTrue(any(x["actor"] == "agent-1" for x in p["sends_to"]))
        self.assertTrue(p["hourly"])
        with self.assertRaises(LookupError):
            insight.actor_profile(self.s, "nobody")

    def test_place_detail(self):
        ch = next(c for c in self.s.channel_row if "board0" in c)
        p = insight.place_detail(self.s, ch)
        self.assertEqual(p["channel"], ch)
        self.assertGreaterEqual(p["messages_total"], 1)
        self.assertTrue(p["writers"] and p["readers"])
        self.assertEqual(sum(1 for o in p["ops"] if o["op"] in ("write", "post")), sum(w["n"] for w in p["writers"]))

    def test_lanes_and_messages(self):
        l = insight.lanes(self.s)
        self.assertTrue(l["hours"] >= 1)
        self.assertEqual({a["actor"] for a in l["actors"]} - {insight.RUNS}, {"agent-0", "agent-1", "agent-2"})
        for a in l["actors"]:
            self.assertEqual(sum(sum(b[1:]) for b in a["bins"]), a["total"])
        m = insight.message_list(self.s)
        self.assertEqual(len(m["rows"]), len(self.s.flow["_deliveries"]))
        self.assertEqual(m["rows"], sorted(m["rows"], key=lambda r: r[6]))

    def test_simulation_series_line_up(self):
        sim = insight.simulate(self.s)
        n = sim["hours"]
        for k in ("actions", "harmful", "harm_remaining", "active_actors", "new_actors", "messages", "pairs", "largest_group"):
            self.assertEqual(len(sim[k]), n, k)
        self.assertEqual(sum(sim["actions"]), sim["actions_total"])
        self.assertEqual(sim["signals"], sorted(sim["signals"], key=lambda g: g["t"]))
        for g in sim["signals"]:
            self.assertIn(g["family"], ("joint", "single", "baseline"))
            self.assertTrue(g["why"])
        self.assertIn("message", {g["kind"] for g in sim["signals"]})

    def test_explain_record(self):
        x = insight.explain(self.s, "M0007")
        self.assertTrue(x["what"])
        self.assertIn("receiver", {r["role"] for r in x["roles"]})
        self.assertEqual(x["actor"]["actor"], "agent-1")
        self.assertIsNone(insight.explain(self.s, "missing"))
        t = self.s.trace("M0007")
        self.assertIn("explain", t)

    def test_why_spans_point_into_the_text(self):
        t = self.s.trace("M0007")
        self.assertTrue(t["why"])
        for w in t["why"]:
            self.assertTrue(0 <= w["s"] < w["e"] <= len(t["text"]))
            self.assertTrue(w["label"])
        places = [w for w in t["why"] if w["type"] == "place"]
        self.assertTrue(places and places[0]["op"] == "read")          # M0007 only reads board0
        w = [x for x in self.s.trace("M0005")["why"] if x["type"] == "place"]
        self.assertEqual(w[0]["op"], "write")                            # M0005 posts to board1
        self.assertIn("write_cue", {x["type"] for x in self.s.trace("M0005")["why"]})

    def test_search_box_and_facets(self):
        r = insight.omni(self.s, "agent-1")
        self.assertEqual(r["actors"][0]["actor"], "agent-1")
        r = insight.omni(self.s, "M000")
        self.assertTrue(all(x["id"].startswith("M000") for x in r["records"]))
        ev = self.s.search(actor="agent-2")
        self.assertEqual(ev["facets"]["actor"][0][0], "agent-2")
        self.assertEqual(sum(n for _, n in ev["hist"]), ev["timed"])

    def test_gap_facts(self):
        rows = insight.gap_facts(self.s)
        keys = {r["key"] for r in rows}
        self.assertTrue({"time", "actor", "order", "success"} <= keys)
        for r in rows:
            if r["share"] is not None:
                self.assertTrue(0 <= r["share"] <= 1)

    def test_context_needs_a_match(self):
        self.assertIsNone(insight.context(self.s)["context"])   # a made-up trace matches no incident file


class StructuredAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.s = Session()
        cls.s.load(write_trace(cls.d), "generic.json", {"text": "body"})

    def test_parse_tolerates_fences_and_words(self):
        obj = {"answer": "a", "blocks": [{"type": "stats", "items": []}]}
        self.assertEqual(ai.parse_answer("```json\n" + json.dumps(obj) + "\n```")["answer"], "a")
        self.assertEqual(ai.parse_answer("Here it is: " + json.dumps(obj) + " done")["answer"], "a")
        self.assertIsNone(ai.parse_answer("no json here"))
        self.assertIsNone(ai.parse_answer('{"something": 1}'))

    def test_verify_marks_what_is_not_in_the_data(self):
        obj = {"answer": "x", "blocks": [
            {"type": "evidence", "items": [{"claim": "c", "ids": ["M0007", "R9999999"]}]},
            {"type": "timeline", "items": [{"time": "2026-11-01 10:07", "label": "read", "ids": ["M0007"], "actor": "agent-1"}]},
            {"type": "flow", "edges": [{"from": "agent-0", "to": "agent-1", "ids": ["M0007"]}, {"from": "ghost", "to": "agent-1"}]},
            {"type": "actors", "items": [{"actor": "agent-9", "role": "?"}]}]}
        v = ai.verify(obj, self.s)
        self.assertEqual(v["blocks"][0]["items"][0]["_missing"], ["R9999999"])
        self.assertEqual(v["blocks"][1]["items"][0]["_data_time"], "2026-11-01 10:07")
        self.assertEqual(v["blocks"][2]["edges"][0]["_from_kind"], "actor")
        self.assertIsNone(v["blocks"][2]["edges"][1]["_from_kind"])
        self.assertTrue(v["blocks"][3]["items"][0]["_actor_missing"])
        self.assertIn("R9999999", v["_checks"]["ids_missing"])
        self.assertIn("ghost", v["_checks"]["names_missing"])

    def test_prompts_carry_the_answer_format(self):
        self.assertIn("Answer format", ai.system_prompt("chat"))
        self.assertIn("Gap audit format", ai.system_prompt("gaps"))
        msgs, _ = ai.build_messages(self.s, [{"role": "user", "content": "what did agent-1 do?"}], mode="gaps")
        ctx = msgs[1]["content"]
        self.assertIn("GAP FACTS", ctx)
        self.assertIn("ACTOR agent-1", ctx)
        self.assertIn("WARNING SIGNS", ctx)


if __name__ == "__main__":
    unittest.main()


class StructuredAppPathTests(unittest.TestCase):
    """A provider that refuses response_format (HTTP 400) and answers in the JSON block format:
    the app retries without it, parses the answer and checks every id against the data."""

    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.parse
        import urllib.request
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from agenttrace import server
        cls.seen = seen = []
        answer = {"answer": "agent-1 read board0 after agent-0 wrote it.", "confidence": "high",
                  "blocks": [{"type": "evidence", "items": [{"claim": "read after write", "ids": ["M0007", "M0000", "X1"]}]}]}

        class P(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(body)
                code, obj = (400, {"error": {"message": "response_format is not supported"}}) if "response_format" in body else \
                    (200, {"choices": [{"message": {"content": "```json\n" + json.dumps(answer) + "\n```"}}]})
                out = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        cls.p = ThreadingHTTPServer(("127.0.0.1", 0), P)
        threading.Thread(target=cls.p.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.p.server_address[1]}/v1"
        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.app.server_address[1]}"
        cls.url = url
        d = tempfile.mkdtemp()
        with open(write_trace(d), "rb") as f:
            data = f.read()
        qs = "filename=trace.csv&pack=generic.json&map=" + urllib.parse.quote(json.dumps({"text": "body"}))
        urllib.request.urlopen(urllib.request.Request(f"{url}/api/upload?{qs}", data=data, method="POST")).read()

    @classmethod
    def tearDownClass(cls):
        cls.p.shutdown()
        cls.app.shutdown()

    def test_structured_answer_with_fallback(self):
        import urllib.request
        req = urllib.request.Request(self.url + "/api/ai", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"baseUrl": self.base, "apiKey": "k", "model": "m", "mode": "gaps",
                                                      "messages": [{"role": "user", "content": "q"}]}).encode())
        with urllib.request.urlopen(req) as r:
            out = json.loads(r.read())
        self.assertIn("response_format", self.seen[-2])           # first try asked for JSON mode
        self.assertNotIn("response_format", self.seen[-1])        # the retry did not
        self.assertEqual(out["mode"], "gaps")
        st = out["structured"]
        self.assertEqual(st["answer"], "agent-1 read board0 after agent-0 wrote it.")
        self.assertEqual(st["blocks"][0]["items"][0]["_missing"], ["X1"])
        self.assertEqual(st["_checks"]["ids_found"], 2)
        for path in ("/api/sim", "/api/lanes", "/api/messages", "/api/places_map", "/api/spread", "/api/gaps",
                     "/api/context", "/api/search?q=agent", "/api/actor?a=agent-0"):
            with urllib.request.urlopen(self.url + path) as r:
                self.assertEqual(r.status, 200, path)


class PlainTextAndFolderUploadTests(unittest.TestCase):
    """A folder of the user's own files: plain-text logs are read one record per line, files that are
    not traces are skipped with a clear answer (and the request body is always read first, so the
    browser's connection is never reset)."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from agenttrace import server
        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.app.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()

    def test_plain_text_is_one_record_per_line(self):
        import os
        from agenttrace import model
        d = tempfile.mkdtemp()
        p = os.path.join(d, "all-report-links.txt")
        with open(p, "w") as f:
            f.write("https://metr.org/report.pdf\n\nhttps://huggingface.co/blog/x\nagent-7 posted to the board\n")
        evs = model.load(p)
        self.assertEqual([e.text for e in evs], ["https://metr.org/report.pdf", "https://huggingface.co/blog/x", "agent-7 posted to the board"])
        q = os.path.join(d, "more.txt")
        with open(q, "w") as f:
            f.write("second file line\n")
        from agenttrace.session import Session
        sess = Session()
        sess.load(p, "auto")
        sim = insight.simulate(sess)               # no times at all: an empty replay of the same shape
        self.assertEqual((sim["hours"], sim["actions"], sim["signals"]), (0, [], []))
        evs = model.load(d)                       # a folder of plain logs only: nothing set aside
        self.assertEqual(len(evs), 4)
        self.assertEqual(model.LAST_REPORT["skipped_files"], [])

    def post(self, path, body):
        import urllib.request
        req = urllib.request.Request(self.url + path, data=body, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_folder_upload_with_files_that_are_not_traces(self):
        big = b"x" * 300_000                       # large enough that replying unread would reset the connection
        out = self.post("/api/stage?batch=t1&filename=notes.md", big)
        self.assertEqual(out["skipped"], "notes.md")
        out = self.post("/api/stage?batch=t1&filename=all-report-links.txt", b"https://metr.org/a\nhttps://openai.com/b\n")
        self.assertEqual(out["staged"], "all-report-links.txt")
        with open(write_trace(tempfile.mkdtemp()), "rb") as f:
            out = self.post("/api/stage?batch=t1&filename=trace.csv", f.read())
        self.assertEqual(out["staged"], "trace.csv")
        out = self.post("/api/analyze?batch=t1&pack=generic.json&name=mine", b"")
        s = out["summary"]
        self.assertTrue(out["loaded"])
        self.assertEqual(s["records"], 30)        # the trace; the link list has no time or parent, so it is set aside
        self.assertEqual([f["file"] for f in s["read_report"]["skipped_files"]], ["all-report-links.txt"])

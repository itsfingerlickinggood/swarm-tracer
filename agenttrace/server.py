"""Local web server for the Swarm Tracer app.

    python3 -m agenttrace serve [--input FILE --pack PACK] [--port 8010]

Serves the app from agenttrace/app/ and a JSON API on 127.0.0.1 only:
    GET  /api/packs                     packs available for analysis
    GET  /api/state                     summary of the loaded dataset (or {"loaded": false})
    POST /api/upload?filename=&pack=&map=   raw file body; analyzes it and returns the summary
    GET  /api/events?q=&kind=&actor=&intent=&tag=&channels=1&offset=&limit=
    GET  /api/event?id=                 full trace of one record
    GET  /api/pairs?q=&all=1&offset=&limit=   every sender-receiver pair (named only unless all=1)
    GET  /api/conversation?a=&b=        all messages between two actors, both directions, with record ids
    GET  /api/list?name=&q=&offset=&limit=   any full list (identities, channels, content_spread, seen_then_used,
                                        carried_edges, shared_places, reply_edges, overwrites)
    GET  /api/actor?a=                  one actor's profile: activity, messages, partners, places, programs, signals
    GET  /api/place?ch=                 one place: every write and read, and the messages through it
    GET  /api/places_map                every place, compact
    GET  /api/lanes                     per-actor activity by hour (swimlanes)
    GET  /api/messages                  every message, compact, in time order
    GET  /api/sim                       hour-by-hour replay and every early-warning sign
    GET  /api/context                   incident context that matches this dataset, with the milestone check
    GET  /api/spread                    every program run by several actors, with what it does
    GET  /api/search?q=                 records, actors and places matching q
    POST /api/ai                        {messages, apiKey, baseUrl, model, selectedId}
    POST /api/ai/models                 {apiKey, baseUrl}
    POST /api/ai/check                  {apiKey, baseUrl, model, sessionId}: a one-word request to prove they work

Uploaded files are written to a private temporary folder for analysis and are not sent
anywhere. The AI endpoint forwards the brief, selected event traces and the chat to the
provider the user configures; the API key is used for that one request and not stored.
"""
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ai, extensions, insight
from .session import Session, list_packs

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
MAX_UPLOAD = 2 * 1024 ** 3  # 2 GB

STATE = {"session": Session(), "busy": False, "error": None, "lock": threading.Lock()}
UPLOAD_DIR = tempfile.mkdtemp(prefix="swarmtracer-")


# read-only views computed from the loaded session (agenttrace/insight.py)
VIEWS = {
    "actor": lambda s, q: insight.actor_profile(s, q.get("a", "")),
    "place": lambda s, q: insight.place_detail(s, q.get("ch", "")),
    "places_map": lambda s, q: insight.places_map(s),
    "lanes": lambda s, q: insight.lanes(s),
    "messages": lambda s, q: insight.message_list(s),
    "sim": lambda s, q: insight.simulate(s),
    "context": lambda s, q: insight.context(s),
    "spread": lambda s, q: {"rows": insight.spread_detail(s)},
    "search": lambda s, q: insight.omni(s, q.get("q", "")),
    "gaps": lambda s, q: {"rows": insight.gap_facts(s)},
}


XGET, XPOST = extensions.routes()


def run_load(path, pack, mapping, name):
    sess = Session()
    sess.load(path, pack, mapping, name)
    STATE["session"] = sess


class Handler(BaseHTTPRequestHandler):
    server_version = "SwarmTracer/1.0"

    def log_message(self, fmt, *args):  # quiet, and never log request bodies
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, limit=MAX_UPLOAD):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("file too large")
        return self.rfile.read(n)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/api/packs":
                return self.send_json({"packs": list_packs(), "ai_defaults": {"baseUrl": ai.DEFAULT_BASE_URL, "model": ai.DEFAULT_MODEL}})
            if u.path == "/api/state":
                s = STATE["session"]
                if STATE["busy"]:
                    return self.send_json({"loaded": False, "busy": True})
                if not s.loaded:
                    return self.send_json({"loaded": False, "error": STATE["error"]})
                return self.send_json({"loaded": True, "summary": s.summary()})
            if u.path == "/api/events":
                s = self.need_session()
                return self.send_json(s.search(q.get("q", ""), q.get("kind", ""), q.get("actor", ""), q.get("intent", ""),
                                               q.get("tag", ""), q.get("channels") == "1",
                                               int(q.get("offset", 0)), min(500, int(q.get("limit", 100))), q.get("hour", "")))
            if u.path == "/api/event":
                s = self.need_session()
                t = s.trace(q.get("id", ""), text_limit=600 if q.get("lite") else 20000)
                return self.send_json(t if t else {"error": "not found"}, 200 if t else 404)
            if u.path == "/api/pairs":
                s = self.need_session()
                return self.send_json(s.pairs(q.get("q", ""), q.get("all") != "1",
                                              int(q.get("offset", 0)), min(500, int(q.get("limit", 50)))))
            if u.path == "/api/list":
                s = self.need_session()
                return self.send_json(s.listing(q.get("name", ""), q.get("q", ""), int(q.get("offset", 0)),
                                                min(1000, int(q.get("limit", 100)))))
            if u.path == "/api/conversation":
                s = self.need_session()
                return self.send_json(s.conversation(q.get("a", ""), q.get("b", "")))
            if u.path.startswith("/api/x/") and u.path[7:] in XGET:
                return self.send_json(XGET[u.path[7:]](STATE, q))
            if u.path.startswith("/api/") and u.path[5:] in VIEWS:
                s = self.need_session()
                return self.send_json(VIEWS[u.path[5:]](s, q))
            return self.serve_static(u.path)
        except LookupError as e:
            return self.send_json({"error": str(e)}, 409)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": str(e)}, 500)

    def need_session(self):
        s = STATE["session"]
        if not s.loaded:
            raise LookupError("No dataset loaded. Upload a file first.")
        return s

    def serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.realpath(os.path.join(APP_DIR, rel))
        if not full.startswith(os.path.realpath(APP_DIR) + os.sep) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/api/upload":
                return self.upload(q)
            if u.path == "/api/stage":
                return self.stage(q)
            if u.path == "/api/analyze":
                return self.analyze_staged(q)
            if u.path.startswith("/api/x/") and u.path[7:] in XPOST:
                try:
                    return self.send_json(XPOST[u.path[7:]](STATE, q, self.read_body()))
                except LookupError as e:
                    return self.send_json({"error": str(e)}, 409)
                except ValueError as e:
                    return self.send_json({"error": str(e)}, 400)
            if u.path == "/api/ai":
                return self.ai_chat()
            if u.path == "/api/ai/models":
                body = json.loads(self.read_body(1_000_000) or b"{}")
                return self.send_json({"models": ai.list_models(body.get("baseUrl") or ai.DEFAULT_BASE_URL, body.get("apiKey", ""))})
            if u.path == "/api/ai/check":
                body = json.loads(self.read_body(1_000_000) or b"{}")
                return self.send_json(ai.check(body.get("baseUrl") or ai.DEFAULT_BASE_URL, body.get("apiKey", ""),
                                               body.get("model") or ai.DEFAULT_MODEL, body.get("sessionId")))
            self.send_json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            traceback.print_exc()
            self.send_json({"error": str(e)}, 500)

    def upload(self, q):
        if not STATE["lock"].acquire(blocking=False):
            return self.send_json({"error": "An analysis is already running."}, 409)
        try:
            STATE["busy"] = True
            STATE["error"] = None
            name = os.path.basename(q.get("filename", "upload.csv")) or "upload.csv"
            ext = os.path.splitext(name)[1].lower()
            data = self.read_body()      # read it all first, so an error reply never resets the connection
            if ext not in (".csv", ".jsonl", ".json", ".tsv", ".txt", ".log"):
                raise ValueError("Upload a trace file: .jsonl, .json, .csv, .tsv, or a plain-text log (.txt, .log).")
            # keep the file's own name, so the overview's read report names the file that was uploaded
            safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in os.path.splitext(name)[0])[:80] or "data"
            d = tempfile.mkdtemp(dir=UPLOAD_DIR)
            path = os.path.join(d, safe + (ext if ext in (".jsonl", ".json", ".tsv", ".txt", ".log") else ".csv"))
            with open(path, "wb") as f:
                f.write(data)
            mapping = json.loads(q["map"]) if q.get("map") else {}
            mapping = {k: v for k, v in mapping.items() if v}
            run_load(path, q.get("pack") or "auto", mapping, name)
            self.send_json({"loaded": True, "summary": STATE["session"].summary()})
        except SystemExit as e:  # model/pack errors are SystemExit with a message
            STATE["error"] = str(e)
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            STATE["error"] = str(e)
            traceback.print_exc()
            self.send_json({"error": str(e)}, 400)
        finally:
            STATE["busy"] = False
            STATE["lock"].release()

    def stage(self, q):
        """Receive one file of a multi-file dataset (a folder upload) into a batch folder."""
        batch = "".join(ch for ch in q.get("batch", "") if ch.isalnum())[:40]
        if not batch:
            raise ValueError("missing batch id")
        name = os.path.basename(q.get("filename", ""))
        # always read the whole body before answering: replying first resets the browser's connection
        data = self.read_body()
        if os.path.splitext(name)[1].lower() not in (".csv", ".jsonl", ".json", ".tsv", ".txt", ".log") or name.startswith("."):
            return self.send_json({"skipped": name, "reason": "not a trace file (.jsonl, .json, .csv, .tsv, .txt, .log)"})
        d = os.path.join(UPLOAD_DIR, "batch-" + batch)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)
        self.send_json({"staged": name, "bytes": len(data)})

    def analyze_staged(self, q):
        if not STATE["lock"].acquire(blocking=False):
            return self.send_json({"error": "An analysis is already running."}, 409)
        try:
            STATE["busy"] = True
            batch = "".join(ch for ch in q.get("batch", "") if ch.isalnum())[:40]
            d = os.path.join(UPLOAD_DIR, "batch-" + batch)
            if not os.path.isdir(d) or not os.listdir(d):
                raise ValueError("no files staged for this batch")
            mapping = {k: v for k, v in (json.loads(q["map"]) if q.get("map") else {}).items() if v}
            run_load(d, q.get("pack") or "auto", mapping, q.get("name") or f"{len(os.listdir(d))} files")
            self.send_json({"loaded": True, "summary": STATE["session"].summary()})
        except SystemExit as e:
            STATE["error"] = str(e)
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            STATE["error"] = str(e)
            traceback.print_exc()
            self.send_json({"error": str(e)}, 400)
        finally:
            STATE["busy"] = False
            STATE["lock"].release()

    def ai_chat(self):
        body = json.loads(self.read_body(5_000_000) or b"{}")
        s = self.need_session()
        mode = "gaps" if body.get("mode") == "gaps" else "chat"
        msgs, ids = ai.build_messages(s, body.get("messages", []), body.get("selectedId"),
                                      conversation=body.get("conversation"), mode=mode, selected=body.get("selected"))
        content, usage = ai.call(body.get("baseUrl") or ai.DEFAULT_BASE_URL, body.get("apiKey", ""),
                                 body.get("model") or ai.DEFAULT_MODEL, msgs, session_id=body.get("sessionId"),
                                 json_mode=True)
        obj = ai.parse_answer(content)
        self.send_json({"content": content, "structured": ai.verify(obj, s) if obj else None, "mode": mode,
                        "usage": usage, "context_ids": ids})


def serve(port=8010, input_path=None, pack="generic.json", mapping=None):
    if input_path:
        print(f"analyzing {input_path} with {pack} ...", flush=True)
        run_load(input_path, pack, mapping or {}, os.path.basename(input_path))
        print("ready", flush=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Swarm Tracer: http://127.0.0.1:{port}/", flush=True)
    try:
        httpd.serve_forever()
    finally:
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)

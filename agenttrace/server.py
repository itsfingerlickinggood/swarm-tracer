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
anywhere; a replaced upload's folder is deleted.

Safety (agenttrace/tests/test_security.py):
- binds 127.0.0.1 only; requests whose Host is not a loopback name are refused (DNS rebinding), and
  POSTs whose Origin is another site are refused (a web page cannot drive this server);
- paths that live mode and Compare read must lie under an allowed folder (allowed_roots()) and be a
  regular file or folder, with no '..' and no link out of the allowed folders; packs are names from
  agenttrace/packs only;
- request bodies are capped: uploads at MAX_UPLOAD (2 GB, SWARM_TRACER_MAX_UPLOAD), JSON at 1 MB
  (a few routes that take a file more, see X_BODY_LIMITS);
- bad input is a 4xx with a message, never a traceback; the request log has no query strings and
  the AI key is never logged;
- every response says X-Content-Type-Options: nosniff; the app's pages get a Content-Security-Policy. The AI endpoint forwards the brief, selected event traces and the chat to the
provider the user configures; the API key is used for that one request and not stored.
"""
import json
import mimetypes
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ai, extensions, insight
from .session import Session, list_packs

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(PKG_DIR, "app")


def _env_int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


MAX_UPLOAD = _env_int("SWARM_TRACER_MAX_UPLOAD", 2 * 1024 ** 3)   # 2 GB per upload (and per staged folder)
MAX_JSON = 1_000_000                                               # JSON request bodies
X_BODY_LIMITS = {"pack_suggest": 200 * 1024 ** 2,                  # /api/x routes that take a file, not JSON
                 "groundtruth_truth": 200 * 1024 ** 2,
                 "case": 20 * 1024 ** 2}
MAX_BATCH_FILES = 5000
TRACE_EXTS = (".csv", ".jsonl", ".json", ".tsv", ".txt", ".log")
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
# 'unsafe-inline' for scripts only because core.js still has two inline onclick handlers (recordDossier's
# "Ask the AI" buttons); once those use addEventListener, drop it from script-src.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

STATE = {"session": Session(), "busy": False, "error": None, "lock": threading.Lock(), "upload_dir": None,
         # live mode and Compare call these on every path and pack the app sends (see live.py, compare.py)
         "path_guard": lambda p, **kw: check_data_path(p, **kw), "pack_guard": lambda p: check_pack(p)}
UPLOAD_DIR = tempfile.mkdtemp(prefix="swarmtracer-")
EXTRA_ROOTS = []      # --allow-path folders and the folder of the dataset loaded at start


class TooLarge(ValueError):
    pass


# ------------------------------------------------------------------ what the server may read

def allowed_roots():
    """Folders live mode and Compare may read from (real paths, existing ones only)."""
    roots = [p for p in (os.environ.get("SWARM_TRACER_DATA") or "").split(os.pathsep) if p.strip()]
    roots += [PKG_DIR, os.path.dirname(PKG_DIR), os.getcwd()] + EXTRA_ROOTS
    out = []
    for r in roots:
        rr = os.path.realpath(os.path.expanduser(r))
        if os.path.isdir(rr) and rr not in out:
            out.append(rr)
    return out


def _under(p, roots):
    return any(p == r or p.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def _outside(p, roots):
    return ValueError(f"{p} is outside the folders this server may read ({'; '.join(roots)}). Restart the server with "
                      "--allow-path FOLDER (or set SWARM_TRACER_DATA) to allow another folder.")


def check_data_path(raw, allow_missing=False, trusted=False):
    """Validate a path the app sent for live mode or Compare; returns the absolute path or raises ValueError.

    It must be a regular file or a folder (no devices, pipes or sockets), contain no '..', and, unless
    trusted (a path from the shipped library), lie under allowed_roots() after following links; a
    folder's trace files may not be links that lead outside them either. allow_missing: a file that
    does not exist yet is fine if its folder is allowed (live mode waits for it)."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("give the path of a trace file or folder on this machine")
    raw = raw.strip()
    if "\x00" in raw:
        raise ValueError("the path contains a NUL character")
    if ".." in re.split(r"[\\/]+", raw):
        raise ValueError("the path may not contain '..'; give the full path of the file or folder")
    p = os.path.abspath(os.path.expanduser(raw))
    roots = allowed_roots()
    if not os.path.lexists(p):
        parent = os.path.realpath(os.path.dirname(p))
        if not allow_missing or not os.path.isdir(parent):
            raise ValueError(f"No file or folder at {p} on this machine.")
        if not trusted and not _under(parent, roots):
            raise _outside(p, roots)
        return p
    real = os.path.realpath(p)
    if not trusted and not _under(real, roots):
        raise _outside(p if real == p else f"{p} (a link to {real})", roots)
    try:
        mode = os.stat(real).st_mode
    except OSError as e:
        raise ValueError(f"cannot read {p}: {e.strerror}")
    if stat.S_ISDIR(mode):
        for f in sorted(os.listdir(real)):
            if f.startswith(".") or os.path.splitext(f)[1].lower() not in TRACE_EXTS:
                continue
            fp = os.path.realpath(os.path.join(real, f))
            if not trusted and not _under(fp, roots):
                raise ValueError(f"{f} in {p} is a link to {fp}, outside the folders this server may read.")
            if not os.path.isfile(fp):
                raise ValueError(f"{f} in {p} is not a regular file (devices, pipes and sockets cannot be read).")
    elif not stat.S_ISREG(mode):
        raise ValueError(f"{p} is not a regular file or folder (devices, pipes and sockets cannot be read).")
    return p


def check_pack(name):
    """A pack the app may ask for: 'auto' or the file name of a pack in agenttrace/packs."""
    from .session import PACK_DIR
    name = str(name or "").strip()
    if name in ("", "auto"):
        return "auto"
    if os.path.basename(name) != name or not name.endswith(".json") or name.startswith(".") \
            or not os.path.isfile(os.path.join(PACK_DIR, name)):
        raise ValueError(f"unknown pack {name!r}: choose one of the packs the app lists (or auto)")
    return name


def safe_filename(name, default="data"):
    """A file name with no folder part and only letters, digits, '.', '_' and '-'."""
    name = re.split(r"[\\/]", str(name or ""))[-1]
    stem, ext = os.path.splitext(name)
    stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem).lstrip(".")[:80] or default
    ext = ext.lower() if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", ext or "") else ""
    return stem + ext


def safe_batch(b):
    return "".join(ch for ch in str(b or "") if ch.isalnum())[:40]


def _int(q, key, default, lo=0, hi=None):
    v = q.get(key)
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except ValueError:
        raise ValueError(f"{key} must be a whole number, not {v[:40]!r}")
    n = max(lo, n)
    return min(hi, n) if hi is not None else n


def _drop_upload_dir(d):
    """Delete one folder under UPLOAD_DIR (never anything else)."""
    if d and os.path.realpath(d).startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        shutil.rmtree(d, ignore_errors=True)


def _replace_upload_dir(new, stale_s=600):
    """The dataset from `new` is now loaded: delete the folder of the upload it replaced, and any other
    upload or folder batch left behind (batches still being staged, touched in the last 10 minutes, stay)."""
    import time
    old, STATE["upload_dir"] = STATE.get("upload_dir"), new
    if old and old != new:
        _drop_upload_dir(old)
    keep = os.path.realpath(new)
    for f in os.listdir(UPLOAD_DIR):
        p = os.path.join(UPLOAD_DIR, f)
        if os.path.realpath(p) == keep:
            continue
        try:
            if f.startswith("up-") or (f.startswith("batch-") and time.time() - os.path.getmtime(p) > stale_s):
                _drop_upload_dir(p)
        except OSError:
            pass


def _scrub(text, *secrets):
    text = str(text)
    for k in secrets:
        if k and len(k) >= 4:
            text = text.replace(k, "[key]")
    return text


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
    # the program index behind "the same program elsewhere" takes seconds on a large trace: build it
    # now in the background, so the first record the investigator opens does not wait for it
    threading.Thread(target=lambda: insight.family_index(sess), daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "SwarmTracer/1.0"

    def log_message(self, fmt, *args):  # quiet: method and path only, never query strings or bodies
        path = str(getattr(self, "path", "") or "").split("?")[0][:200]
        sys.stderr.write("%s %s\n" % (getattr(self, "command", None) or "-", path))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _length(self, limit):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if n < 0:
            raise ValueError("bad Content-Length")
        if n > limit:
            self.close_connection = True    # the unread body must not be parsed as the next request
            self._drain(n)                  # a browser that is still sending sees a reset instead of the reply
            raise TooLarge(f"the request body is {n:,} bytes; the limit here is {limit:,} bytes")
        return n

    def _drain(self, n, cap=8 * 1024 ** 3):
        n = min(n, cap)
        while n > 0:
            chunk = self.rfile.read(min(n, 1 << 20))
            if not chunk:
                break
            n -= len(chunk)

    def read_body(self, limit=None):
        return self.rfile.read(self._length(MAX_JSON if limit is None else limit))

    def save_body(self, path, limit=None):
        """Stream the body to a file (an upload need not fit in memory). Returns the bytes written."""
        n = left = self._length(MAX_UPLOAD if limit is None else limit)
        with open(path, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            raise ValueError("the upload ended early")
        return n

    def guard(self):
        """Refuse requests that a web page on another site (or a rebound DNS name) could make.
        Returns True when the request may go on."""
        host = (self.headers.get("Host") or "").strip().lower()
        hn = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if host and hn not in LOOPBACK:
            self.send_json({"error": "this server only answers requests addressed to 127.0.0.1 or localhost"}, 403)
            return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and origin != "null":
                o = urllib.parse.urlparse(origin)
                if (o.hostname or "") not in LOOPBACK or (host and o.netloc.lower() != host):
                    self.send_json({"error": "requests from other web pages are refused"}, 403)
                    return False
            elif origin == "null":
                self.send_json({"error": "requests from other web pages are refused"}, 403)
                return False
        return True

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        if not self.guard():
            return
        u = urllib.parse.urlparse(self.path)
        try:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        except ValueError:
            return self.send_json({"error": "malformed query string"}, 400)
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
                                               _int(q, "offset", 0), _int(q, "limit", 100, 0, 500), q.get("hour", "")))
            if u.path == "/api/event":
                s = self.need_session()
                t = s.trace(q.get("id", ""), text_limit=600 if q.get("lite") else 20000)
                return self.send_json(t if t else {"error": "not found"}, 200 if t else 404)
            if u.path == "/api/pairs":
                s = self.need_session()
                return self.send_json(s.pairs(q.get("q", ""), q.get("all") != "1",
                                              _int(q, "offset", 0), _int(q, "limit", 50, 0, 500)))
            if u.path == "/api/list":
                s = self.need_session()
                return self.send_json(s.listing(q.get("name", ""), q.get("q", ""), _int(q, "offset", 0),
                                                _int(q, "limit", 100, 0, 1000)))
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
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

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
        if full.endswith(".html"):
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        if not self.guard():
            return
        u = urllib.parse.urlparse(self.path)
        try:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        except ValueError:
            return self.send_json({"error": "malformed query string"}, 400)
        try:
            if u.path == "/api/upload":
                return self.upload(q)
            if u.path == "/api/stage":
                return self.stage(q)
            if u.path == "/api/analyze":
                return self.analyze_staged(q)
            if u.path.startswith("/api/x/") and u.path[7:] in XPOST:
                name = u.path[7:]
                return self.send_json(XPOST[name](STATE, q, self.read_body(X_BODY_LIMITS.get(name, MAX_JSON))))
            if u.path == "/api/ai":
                return self.ai_chat()
            if u.path in ("/api/ai/models", "/api/ai/check"):
                body = self.json_body(MAX_JSON)
                key = str(body.get("apiKey") or "")
                try:
                    if u.path == "/api/ai/models":
                        return self.send_json({"models": ai.list_models(body.get("baseUrl") or ai.DEFAULT_BASE_URL, key)})
                    return self.send_json(ai.check(body.get("baseUrl") or ai.DEFAULT_BASE_URL, key,
                                                   body.get("model") or ai.DEFAULT_MODEL, body.get("sessionId")))
                except (LookupError, ValueError):
                    raise
                except Exception as e:      # provider errors: say what failed, never log or echo the key
                    sys.stderr.write(f"AI provider error: {type(e).__name__}\n")
                    return self.send_json({"error": _scrub(e, key)}, 502)
            self.send_json({"error": "unknown endpoint"}, 404)
        except TooLarge as e:
            self.send_json({"error": str(e)}, 413)
        except LookupError as e:
            self.send_json({"error": str(e)}, 409)
        except (ValueError, SystemExit) as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def json_body(self, limit=MAX_JSON):
        raw = self.read_body(limit)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise ValueError("the request body is not valid JSON")
        if not isinstance(body, dict):
            raise ValueError("the request body must be a JSON object")
        return body

    def _mapping(self, q):
        try:
            m = json.loads(q["map"]) if q.get("map") else {}
        except ValueError:
            raise ValueError("map must be JSON: {\"role\": \"column\"}")
        if not isinstance(m, dict):
            raise ValueError("map must be a JSON object: {\"role\": \"column\"}")
        return {str(k): str(v) for k, v in m.items() if v}

    def upload(self, q):
        if not STATE["lock"].acquire(blocking=False):
            return self.send_json({"error": "An analysis is already running."}, 409)
        d = None
        try:
            STATE["busy"] = True
            STATE["error"] = None
            name = re.split(r"[\\/]", q.get("filename") or "upload.csv")[-1] or "upload.csv"
            ext = os.path.splitext(name)[1].lower()
            d = tempfile.mkdtemp(prefix="up-", dir=UPLOAD_DIR)
            # keep the file's own name, so the overview's read report names the file that was uploaded
            path = os.path.join(d, safe_filename(os.path.splitext(name)[0]) + (ext if ext in TRACE_EXTS else ".csv"))
            self.save_body(path)         # read it all first, so an error reply never resets the connection
            if ext not in TRACE_EXTS:
                raise ValueError("Upload a trace file: .jsonl, .json, .csv, .tsv, or a plain-text log (.txt, .log).")
            run_load(path, check_pack(q.get("pack")), self._mapping(q), name[:200])
            _replace_upload_dir(d)
            d = None
            out, code = {"loaded": True, "summary": STATE["session"].summary()}, 200
        except Exception as e:
            out, code = self._load_error(e)
        except SystemExit as e:  # model/pack errors are SystemExit with a message
            out, code = self._load_error(e)
        finally:
            _drop_upload_dir(d)          # a failed upload leaves nothing behind
            STATE["busy"] = False
            STATE["lock"].release()
        self.send_json(out, code)        # after the lock is free, so the next request is not refused

    def _load_error(self, e):
        STATE["error"] = str(e)
        if not isinstance(e, (ValueError, UnicodeDecodeError, SystemExit)):
            traceback.print_exc()
        return {"error": str(e)}, 413 if isinstance(e, TooLarge) else 400

    def stage(self, q):
        """Receive one file of a multi-file dataset (a folder upload) into a batch folder."""
        batch = safe_batch(q.get("batch"))
        if not batch:
            raise ValueError("missing batch id")
        raw = re.split(r"[\\/]", q.get("filename") or "")[-1]
        name = safe_filename(raw, "file")
        d = os.path.join(UPLOAD_DIR, "batch-" + batch)
        os.makedirs(d, exist_ok=True)
        files = os.listdir(d)
        used = sum(os.path.getsize(os.path.join(d, f)) for f in files)
        if len(files) >= MAX_BATCH_FILES and name not in files:
            self._drain(self._length(MAX_UPLOAD))
            raise TooLarge(f"a folder upload may hold at most {MAX_BATCH_FILES:,} files")
        # always read the whole body before answering: replying first resets the browser's connection
        tmp = os.path.join(d, ".part-" + name)
        try:
            n = self.save_body(tmp, max(0, MAX_UPLOAD - used))
            if os.path.splitext(raw)[1].lower() not in TRACE_EXTS or raw.startswith(".") or not raw:
                out = {"skipped": raw, "reason": "not a trace file (.jsonl, .json, .csv, .tsv, .txt, .log)"}
            else:
                os.replace(tmp, os.path.join(d, name))
                out = {"staged": name, "bytes": n}
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self.send_json(out)             # after the clean-up, so the folder is final when the app hears back

    def analyze_staged(self, q):
        if not STATE["lock"].acquire(blocking=False):
            return self.send_json({"error": "An analysis is already running."}, 409)
        try:
            STATE["busy"] = True
            batch = safe_batch(q.get("batch"))
            if not batch:
                raise ValueError("missing batch id")
            d = os.path.join(UPLOAD_DIR, "batch-" + batch)
            if not os.path.isdir(d) or not os.listdir(d):
                raise ValueError("no files staged for this batch")
            n = len(os.listdir(d))
            run_load(d, check_pack(q.get("pack")), self._mapping(q), (q.get("name") or f"{n} files")[:200])
            _replace_upload_dir(d)       # a failed analysis keeps the batch, so it can be tried again
            out, code = {"loaded": True, "summary": STATE["session"].summary()}, 200
        except Exception as e:
            out, code = self._load_error(e)
        except SystemExit as e:
            out, code = self._load_error(e)
        finally:
            STATE["busy"] = False
            STATE["lock"].release()
        self.send_json(out, code)

    def ai_chat(self):
        body = self.json_body(5_000_000)
        s = self.need_session()
        key = str(body.get("apiKey") or "")
        try:
            return self._ai_chat(body, s, key)
        except (LookupError, ValueError):
            raise
        except Exception as e:      # provider errors: say what failed, never log or echo the key
            sys.stderr.write(f"AI provider error: {type(e).__name__}\n")
            return self.send_json({"error": _scrub(e, key)}, 502)

    def _ai_chat(self, body, s, key):
        mode = body.get("mode") if body.get("mode") in ("gaps", "report") else "chat"
        msgs, ids = ai.build_messages(s, body.get("messages", []), body.get("selectedId"),
                                      conversation=body.get("conversation"), mode=mode, selected=body.get("selected"))
        content, usage = ai.call(body.get("baseUrl") or ai.DEFAULT_BASE_URL, key,
                                 body.get("model") or ai.DEFAULT_MODEL, msgs, session_id=body.get("sessionId"),
                                 json_mode=True)
        obj = ai.parse_answer(content)
        self.send_json({"content": content, "structured": ai.verify(obj, s) if obj else None, "mode": mode,
                        "usage": usage, "context_ids": ids})


def serve(port=8010, input_path=None, pack="generic.json", mapping=None, allow_paths=()):
    for d in allow_paths or ():
        d = os.path.abspath(os.path.expanduser(d))
        if not os.path.isdir(d):
            raise SystemExit(f"--allow-path {d}: no such folder")
        EXTRA_ROOTS.append(d)
    if input_path:
        p = os.path.abspath(input_path)
        EXTRA_ROOTS.append(p if os.path.isdir(p) else os.path.dirname(p))
        print(f"analyzing {input_path} with {pack} ...", flush=True)
        run_load(input_path, pack, mapping or {}, os.path.basename(input_path))
        print("ready", flush=True)
    # a burst of page requests must not overflow the listen queue while a background analysis holds the
    # interpreter: the default queue (5) made the browser's parallel requests fail with "connection reset"
    ThreadingHTTPServer.request_queue_size = 128
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Swarm Tracer: http://127.0.0.1:{port}/", flush=True)
    try:
        httpd.serve_forever()
    finally:
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)

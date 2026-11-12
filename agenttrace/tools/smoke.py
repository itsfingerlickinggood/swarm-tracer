"""Smoke test: every dataset x every tab x the Inspector, in headless Chrome, plus every GET endpoint.

    python3 -m agenttrace.tools.smoke [--port 8031] [--datasets demo samples odd wiki big] [--no-browser] [--json out.json]

For each dataset it starts its own server (python3 -m agenttrace serve --port N --input PATH [--pack P]); when the
server refuses the input it starts a bare server and tries the app's upload path instead, which must answer with a
clear message. Then it calls every GET endpoint the tabs use and every /api/x/* GET route (a 500 or a hang fails),
probes odd parameters (must be a 4xx, never a 500), and drives headless Chrome over the DevTools protocol: it opens
each tab (and each Forensics section) and one record, one actor and one place in the Inspector, failing a cell on
any uncaught exception, console.error, HTTP error response, `.warn` box, a blank tab, or a tab that never settles.

Datasets: big (redacted_columns.csv with code_traces.json), wiki (full-wiki-logs), demo (samples/demo_swarm),
samples (each file in agenttrace/samples), odd (a text-only folder, a one-line file, an empty file, a header-only
CSV, a JSONL with a broken line, a non-UTF-8 CSV; written to a temporary folder), or [label=]path[::pack].
Exits 1 when any cell fails. Needs Google Chrome (or set CHROME=/path/to/chrome).
"""
import argparse
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_chrome():
    env = os.environ.get("CHROME")
    for p in ([env] if env else []) + CHROME_PATHS:
        if p and os.path.exists(p):
            return p
    return shutil.which("google-chrome") or shutil.which("chromium")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class WebSocket:
    """Client side of RFC 6455, text frames only (enough for CDP)."""

    def __init__(self, url, timeout=30):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + ("?" + u.query if u.query else "")
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("websocket handshake refused: " + head.decode(errors="replace")[:200])
        self.buf = b""

    def send(self, text):
        data = text.encode("utf-8")
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """One whole message (text), or None on close. Raises socket.timeout when nothing arrives."""
        parts = []
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if b1 & 0x80:
                mask = self._read(4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(n)))
            else:
                payload = self._read(n)
            if op == 0x8:
                return None
            if op == 0x9:      # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op == 0xA:
                continue
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts).decode("utf-8", errors="replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """Headless Chrome with one page; collects console errors, exceptions and failed requests."""

    def __init__(self, width=1500, height=1000):
        exe = find_chrome()
        if not exe:
            raise RuntimeError("Chrome not found (set CHROME=/path/to/chrome)")
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="st-smoke-chrome-")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
             "--disable-background-networking", "--disable-sync", "--metrics-recording-only", "--mute-audio",
             f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        deadline = time.time() + 30
        while time.time() < deadline and not ws_url:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2) as r:
                    pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
                ws_url = pages[0]["webSocketDebuggerUrl"] if pages else None
            except Exception:
                time.sleep(0.2)
        if not ws_url:
            self.close()
            raise RuntimeError("Chrome did not open its debugging port")
        self.ws = WebSocket(ws_url)
        self.seq = 0
        self.events = []          # (kind, text) collected since the last mark()
        self.inflight = {}
        self.last_net = time.time()
        for m in ("Runtime.enable", "Log.enable", "Network.enable", "Page.enable"):
            self.call(m)

    # -- protocol
    def _handle(self, msg):
        m, p = msg.get("method"), msg.get("params") or {}
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            ex = d.get("exception") or {}
            self.events.append(("exception", (ex.get("description") or d.get("text") or "exception").split("\n")[0]))
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            args = p.get("args") or []
            txt = " ".join(str(a.get("description") or a.get("value") or "") for a in args).split("\n")[0]
            self.events.append(("console.error", txt))
        elif m == "Log.entryAdded" and (p.get("entry") or {}).get("level") == "error":
            e = p["entry"]
            if e.get("source") != "network":       # network failures are recorded with their status below
                self.events.append(("log.error", (e.get("text") or "")[:300]))
        elif m == "Network.requestWillBeSent":
            self.inflight[p["requestId"]] = p["request"]["url"]
            self.last_net = time.time()
        elif m == "Network.responseReceived":
            r = p.get("response") or {}
            if r.get("status", 200) >= 400 and "/favicon" not in r.get("url", ""):
                self.events.append(("http", f"{r.get('status')} {urllib.parse.urlparse(r.get('url', '')).path}"
                                            f"?{urllib.parse.urlparse(r.get('url', '')).query}".rstrip("?")))
                self.failed_ids = getattr(self, "failed_ids", set()) | {p["requestId"]}
        elif m in ("Network.loadingFinished", "Network.loadingFailed"):
            self.inflight.pop(p.get("requestId"), None)
            self.last_net = time.time()
            if m == "Network.loadingFailed" and not p.get("canceled"):
                self.events.append(("netfail", p.get("errorText", "")))

    def pump(self, timeout=0.05):
        self.ws.sock.settimeout(timeout)
        try:
            while True:
                raw = self.ws.recv()
                if raw is None:
                    raise ConnectionError("Chrome closed the connection")
                msg = json.loads(raw)
                if "id" in msg:
                    self.replies[msg["id"]] = msg
                else:
                    self._handle(msg)
                self.ws.sock.settimeout(0.001)
        except (socket.timeout, BlockingIOError):
            pass

    replies = {}

    def call(self, method, params=None, timeout=60):
        self.seq += 1
        i = self.seq
        self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.pump(0.1)
            if i in self.replies:
                r = self.replies.pop(i)
                if "error" in r:
                    raise RuntimeError(f"{method}: {r['error']}")
                return r.get("result", {})
        raise TimeoutError(f"{method} timed out after {timeout} s")

    def eval(self, expr, timeout=60, await_promise=False):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise}, timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or "evaluation failed")
        return (r.get("result") or {}).get("value")

    def navigate(self, url):
        self.call("Page.navigate", {"url": url})

    def mark(self):
        self.events = []

    def wait_until(self, expr, timeout=60, poll=0.15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval(expr, timeout=max(1, deadline - time.time())):
                    return True
            except RuntimeError:
                pass
            self.pump(poll)
        return False

    def settle(self, quiet=0.6, timeout=60, busy_expr=None):
        """Wait until no request is in flight for `quiet` seconds (and busy_expr, if given, is false)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.pump(0.1)
            if not self.inflight and time.time() - self.last_net >= quiet:
                if not busy_expr:
                    return True
                try:
                    if not self.eval(busy_expr, timeout=max(1, deadline - time.time())):
                        return True
                except RuntimeError:
                    return True
        return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        if getattr(self, "proc", None):
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(getattr(self, "profile", ""), ignore_errors=True)


# ====================================================================== the smoke test

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "agenttrace")
TABS = ["trace", "overview", "network", "timeline", "channels", "spread", "early", "events", "agents", "forensics", "compare", "gaps"]
TAB_BUDGET_S = 2.0
LIST_NAMES = ["identities", "channels", "content_spread", "seen_then_used", "carried_edges", "shared_places", "reply_edges", "overwrites"]
BUSY_JS = r"""(() => { const el = document.querySelector('#left'); if (!el) return true;
  const t = el.innerText || '';
  if (t.trim().length === 0) return true;
  // any short placeholder still saying it is loading, anywhere in the tab
  return [...el.querySelectorAll('p, div, span, td')].some((x) => x.children.length === 0 && x.offsetParent !== null &&
    /^(Loading|Counting the evidence|Reading the|Computing|Working)/.test((x.innerText || '').trim()) && (x.innerText || '').trim().length < 60); })()"""
TRACE_BUSY_JS = r"""(() => { const t = (document.querySelector('#trace')||{}).innerText || ''; return /^\s*Loading…/.test(t); })()"""
# a .warn the Inspector shows on purpose (a place nobody read): not an error
OK_WARN = ("Written, but never read",)
# views also use .warn for content warnings (a low precision, a caveat); a warn box counts as a failure only when
# its text reads like an error message (a caught exception or a failed request)
ERRORISH = re.compile(r"is not (a function|defined|iterable)|Cannot read|Cannot set|undefined|\bnull\b|Unexpected token|"
                      r"JSON|HTTP \d{3}|[Ff]ailed|[Ee]rror|No view named|not found|unknown endpoint|Traceback|NaN")


def make_odd(d):
    """Write the odd datasets into folder d and return [(label, path)]."""
    os.makedirs(os.path.join(d, "text_only"), exist_ok=True)

    def w(name, data, mode="w"):
        p = os.path.join(d, name)
        with open(p, mode) as f:
            f.write(data)
        return p
    w("text_only/agent_a.log", "\n".join(f"2026-11-01 10:{i:02d}:00 agent-a wrote notes to https://board.example.com/x{i % 2}"
                                          for i in range(20)) + "\n")
    w("text_only/agent_b.txt", "\n".join(f"agent-b read https://board.example.com/x{i % 2} and replied" for i in range(15)) + "\n")
    lines = [json.dumps({"id": f"B{i}", "text": f"agent-{i % 3} posts to https://pad.example.com/p{i % 2}", "actor": f"agent-{i % 3}",
                         "time": f"2026-11-01T10:{i:02d}:00Z"}) for i in range(12)]
    lines.insert(5, '{"id": "BROKEN", "text": "unterminated')
    rows = ["id,text,actor,time"] + [f"L{i},caf\xe9 d\xe9j\xe0 vu message {i} to https://x.example.com/q,agent-{i % 2},2026-11-01T11:{i:02d}:00Z"
                                     for i in range(10)]
    return [
        ("text-only folder", os.path.join(d, "text_only")),
        ("one-line file", w("one_line.jsonl", json.dumps({"id": "A1", "text": "hello from agent", "actor": "agent-1",
                                                           "time": "2026-11-01T10:00:00Z"}) + "\n")),
        ("empty file", w("empty.csv", "")),
        ("header-only CSV", w("header_only.csv", "id,text,actor,time\n")),
        ("JSONL with a broken line", w("broken_line.jsonl", "\n".join(lines) + "\n")),
        ("non-UTF-8 CSV", w("latin1.csv", ("\n".join(rows) + "\n").encode("latin-1"), "wb")),
    ]


def dataset_specs(names, odd_dir):
    """Expand dataset names: big, wiki, demo, samples, odd, or label=path[::pack] / path[::pack]."""
    out = []
    for n in names:
        if n == "big":
            out.append(("Swarm Traces (redacted_columns.csv)", os.path.join(ROOT, "redacted_columns.csv"), "code_traces.json"))
        elif n == "wiki":
            out.append(("collusion.wiki logs", os.path.join(ROOT, "full-wiki-logs"), None))
        elif n == "demo":
            out.append(("demo swarm", os.path.join(PKG, "samples", "demo_swarm"), None))
        elif n == "samples":
            sd = os.path.join(PKG, "samples")
            for f in sorted(os.listdir(sd)):
                if os.path.splitext(f)[1] in (".json", ".jsonl", ".csv", ".tsv", ".txt", ".log"):
                    out.append(("sample " + f, os.path.join(sd, f), None))
        elif n == "odd":
            out += [(label, p, None) for label, p in make_odd(odd_dir)]
        else:
            label, _, rest = n.rpartition("=")
            path, _, pack = rest.partition("::")
            out.append((label or os.path.basename(path.rstrip("/")), os.path.abspath(path), pack or None))
    return [x for x in out if os.path.exists(x[1])] + [(l, p, k) for l, p, k in out if not os.path.exists(p)]


class Server:
    def __init__(self, port, path=None, pack=None, log_dir=None, allow=()):
        self.port = port
        cmd = [sys.executable, "-m", "agenttrace", "serve", "--port", str(port)]
        for a in allow:          # folders live mode and Compare may read (the server refuses others)
            cmd += ["--allow-path", a]
        if path:
            cmd += ["--input", path]
        if pack:
            cmd += ["--pack", pack]
        self.log = tempfile.NamedTemporaryFile(prefix=f"st-smoke-{port}-", suffix=".log", dir=log_dir, delete=False)
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{port}"

    def wait(self, timeout):
        """True once /api/state answers; False if the process exits first or the time runs out."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(self.base + "/api/state", timeout=5) as r:
                    r.read()
                return True
            except Exception:
                time.sleep(0.3)
        return False

    def output(self, n=1500):
        try:
            with open(self.log.name, "rb") as f:
                return f.read().decode("utf-8", "replace")[-n:]
        except OSError:
            return ""

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            os.unlink(self.log.name)
        except OSError:
            pass


def http(base, path, method="GET", body=None, timeout=120):
    """(status, parsed JSON or text, seconds)."""
    req = urllib.request.Request(base + path, data=body, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", time.time() - t0
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        data = raw[:200].decode("utf-8", "replace")
    return code, data, time.time() - t0


def upload(base, path):
    """Load a dataset the way the app does: one file to /api/upload, a folder through /api/stage + /api/analyze."""
    q = urllib.parse.quote
    if os.path.isdir(path):
        batch = "smoke%d" % int(time.time() * 1000)
        for f in sorted(os.listdir(path)):
            with open(os.path.join(path, f), "rb") as fh:
                http(base, f"/api/stage?batch={batch}&filename={q(f)}", "POST", fh.read())
        return http(base, f"/api/analyze?batch={batch}&pack=auto&name={q(os.path.basename(path))}", "POST", b"", timeout=600)
    with open(path, "rb") as fh:
        return http(base, f"/api/upload?filename={q(os.path.basename(path))}&pack=auto", "POST", fh.read(), timeout=600)


class Result:
    def __init__(self, dataset):
        self.dataset = dataset
        self.cells = []      # {area, name, ok, error, seconds, note}

    def add(self, area, name, ok, error="", seconds=None, note=""):
        self.cells.append({"area": area, "name": name, "ok": bool(ok), "error": error, "seconds": seconds, "note": note})

    @property
    def failed(self):
        return [c for c in self.cells if not c["ok"]]


def pick_ids(base, summary):
    """One record id, one named actor (else any actor) and one place, from the API."""
    ids = {"rec": None, "actor": None, "place": None, "pair": None}
    code, ev, _ = http(base, "/api/events?limit=1")
    if code == 200 and ev.get("rows"):
        ids["rec"] = ev["rows"][0]["id"]
    code, ln, _ = http(base, "/api/lanes")
    if code == 200 and isinstance(ln, dict):
        acts = [a["actor"] for a in ln.get("actors", []) if a.get("kind") not in ("runs", "run")]
        ids["actor"] = acts[0] if acts else None
    if not ids["actor"]:
        code, sr, _ = http(base, "/api/events?limit=50")
        if code == 200:
            ids["actor"] = next((r["actor"] for r in sr.get("rows", []) if r.get("actor")), None)
    tc = (summary.get("top_channels") or [])
    ids["place"] = tc[0]["channel"] if tc else None
    code, pr, _ = http(base, "/api/pairs?limit=1&all=1")
    if code == 200 and pr.get("rows"):
        ids["pair"] = (pr["rows"][0]["from"], pr["rows"][0]["to"])
    return ids


def api_cells(res, base, summary, ids, xget):
    """Every GET endpoint the tabs use, plus each /api/x/* GET route; a 500 or a hang fails."""
    q = urllib.parse.quote
    paths = ["/api/packs", "/api/state", "/api/events?limit=50", "/api/events?q=a&limit=20", "/api/events?channels=1&limit=20",
             "/api/pairs?limit=50", "/api/pairs?all=1&limit=50", "/api/places_map", "/api/lanes", "/api/messages", "/api/sim",
             "/api/context", "/api/spread", "/api/gaps", "/api/search?q=a"]
    paths += [f"/api/list?name={n}&limit=100" for n in LIST_NAMES]
    if ids["rec"]:
        paths += [f"/api/event?id={q(ids['rec'])}", f"/api/event?lite=1&id={q(ids['rec'])}"]
    if ids["actor"]:
        paths += [f"/api/actor?a={q(ids['actor'])}"]
    if ids["place"]:
        paths += [f"/api/place?ch={q(ids['place'])}"]
    if ids["pair"]:
        paths += [f"/api/conversation?a={q(ids['pair'][0])}&b={q(ids['pair'][1])}"]
    # routes added by feature modules take different parameters: give each the usual ones (unused ones are ignored)
    generic = "&".join(f"{k}={q(v)}" for k, v in (("id", ids["rec"]), ("rec", ids["rec"]), ("actor", ids["actor"]), ("a", ids["actor"]),
                                                   ("ch", ids["place"]), ("place", ids["place"]), ("q", "a")) if v)
    params = {"case_export": "format=html", "identity": "", "roles": "", "live_status": "since=0"}
    for name in sorted(xget):
        pr = params.get(name, generic)
        paths.append(f"/api/x/{name}" + (("?" + pr) if pr else ""))
    if "case_export" in xget:
        paths.append("/api/x/case_export?format=json")
    if "identity" in xget and ids["actor"]:
        paths.append(f"/api/x/identity?actor={q(ids['actor'])}")
    for p in paths:
        code, data, sec = http(base, p)
        err = data.get("error") if isinstance(data, dict) else (data if code != 200 else "")
        # 409 from an extension means "not available for this data / not loaded": fine if it says why in words
        ok = code == 200 or (code in (400, 404, 409) and p.startswith("/api/x/") and isinstance(err, str) and len(err) > 10)
        res.add("api", p, ok, "" if code == 200 else f"HTTP {code}: {str(err)[:200]}", round(sec, 2),
                "slow" if sec > TAB_BUDGET_S else "")


BAD_INPUT = ["/api/events?offset=x", "/api/events?limit=x", "/api/pairs?limit=x", "/api/list?name=identities&limit=x",
             "/api/list?name=nope", "/api/event?id=", "/api/event?id=NOPE_NOT_AN_ID", "/api/actor?a=NOPE_NOT_AN_ACTOR",
             "/api/place?ch=NOPE_NOT_A_PLACE", "/api/conversation?a=&b=", "/api/x/identity?limit=x", "/api/x/roles?limit=x",
             "/api/x/live_status?since=x", "/api/x/time_range?id=NOPE", "/api/x/labels?id=NOPE", "/api/x/case_export?format=nope"]


def bad_input_cells(res, base, xget):
    """Odd parameters must give a clear 4xx (or an empty answer), never a 500."""
    for p in BAD_INPUT:
        if p.startswith("/api/x/") and p[7:].split("?")[0] not in xget:
            continue
        code, data, sec = http(base, p)
        err = data.get("error") if isinstance(data, dict) else ""
        res.add("bad input", p, code != 500 and code != 0, f"HTTP {code}: {str(err)[:200]}" if code >= 400 or code == 0 else "",
                round(sec, 2))


def _events_text(evs):
    return "; ".join(f"{k}: {v}" for k, v in evs)[:600]


def browser_cells(res, br, base, ids, tabs, forensics_sections=True):
    br.mark()
    br.navigate(base + "/")
    if not br.wait_until("typeof S !== 'undefined' && !!S.summary", timeout=120):
        st = br.eval("document.querySelector('#status') && document.querySelector('#status').innerText")
        res.add("ui", "load page", False, f"no summary after 120 s; status: {st!r}; {_events_text(br.events)}")
        return
    br.settle(busy_expr=BUSY_JS, timeout=90)
    res.add("ui", "load page", not br.events, _events_text(br.events))
    for tab in tabs:
        subs = [None]
        if tab == "forensics" and forensics_sections:
            subs = br.eval("(window.FX_SECTIONS || []).map((x) => x.id)") or [None]
        for sub in subs:
            name = tab + (f"/{sub}" if sub else "")
            br.mark()
            t0 = time.time()
            try:
                if sub:
                    br.eval(f"location.hash = {json.dumps('tab=forensics&fx=' + sub)}; goTab('forensics')")
                else:
                    br.eval(f"goTab({json.dumps(tab)})")
                settled = br.settle(busy_expr=BUSY_JS, timeout=120)
                sec = max(0.0, time.time() - t0 - 0.6)     # settle() waits 0.6 s of quiet after the last request
                info = br.eval(r"""(() => { const el = document.querySelector('#left');
                  return { text: el.innerText.trim().slice(0, 240), len: el.innerText.trim().length,
                           warns: [...el.querySelectorAll('.warn')].map((w) => w.innerText.trim().slice(0, 200)) }; })()""")
            except Exception as e:
                res.add("tab", name, False, f"{type(e).__name__}: {e}; {_events_text(br.events)}")
                continue
            errs = list(br.events)
            problems = []
            if not settled:
                problems.append("did not settle in 120 s (still loading or a request hung)")
            if errs:
                problems.append(_events_text(errs))
            bad_warns = [w for w in info["warns"] if ERRORISH.search(w)]
            if bad_warns:
                problems.append("warn box: " + " | ".join(bad_warns))
            other = [w for w in info["warns"] if not ERRORISH.search(w)]
            if info["len"] < 30:
                problems.append(f"almost blank ({info['len']} characters): {info['text']!r}")
            res.add("tab", name, not problems, "; ".join(problems), round(sec, 2),
                    ("slow; " if sec > TAB_BUDGET_S else "") + ("content warning: " + " | ".join(other)[:200] + "; " if other else "")
                    + "shows: " + info["text"][:160].replace("\n", " / "))
    for kind, fn in (("record", "selectEvent"), ("actor", "inspectActor"), ("place", "inspectPlace")):
        key = ids.get({"record": "rec"}.get(kind, kind))
        if not key:
            res.add("inspector", kind, True, "", None, f"no {kind} in this dataset to open")
            continue
        br.mark()
        t0 = time.time()
        try:
            br.eval(f"{fn}({json.dumps(key)})")
            settled = br.settle(busy_expr=TRACE_BUSY_JS, timeout=60)
            info = br.eval(r"""(() => { const el = document.querySelector('#trace');
              return { text: el.innerText.trim().slice(0, 200), len: el.innerText.trim().length,
                       warns: [...el.querySelectorAll('.warn')].map((w) => w.innerText.trim().slice(0, 200)) }; })()""")
        except Exception as e:
            res.add("inspector", kind, False, f"{type(e).__name__}: {e}")
            continue
        warns = [w for w in info["warns"] if not w.startswith(OK_WARN) and ERRORISH.search(w)]
        problems = ([] if settled else ["did not settle"]) + ([_events_text(br.events)] if br.events else []) + \
                   (["warn box: " + " | ".join(warns)] if warns else []) + ([f"almost blank: {info['text']!r}"] if info["len"] < 30 else [])
        res.add("inspector", f"{kind} {key}", not problems, "; ".join(problems), round(max(0.0, time.time() - t0 - 0.6), 2),
                info["text"][:120].replace("\n", " / "))


def smoke_dataset(label, path, pack, port, tabs, browser=True, load_timeout=600, log_dir=None):
    res = Result(label)
    if not os.path.exists(path):
        res.add("load", "input exists", False, f"not found: {path}")
        return res
    xget = sorted(_xget_names())
    srv = Server(port, path, pack, log_dir)
    try:
        t0 = time.time()
        up = srv.wait(load_timeout)
        if up:
            res.add("load", "serve --input", True, "", round(time.time() - t0, 1))
        else:
            out = srv.output(200000)
            last = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or ["(no output)"]
            traceback_seen = "Traceback" in out
            # a clear one-line refusal is acceptable for unusable input; a traceback is not
            res.add("load", "serve --input", not traceback_seen, f"server exited: {last[0][:300]}" + (" (with a traceback)" if traceback_seen else ""),
                    round(time.time() - t0, 1))
            srv.stop()
            srv = Server(port, None, None, log_dir)
            if not srv.wait(60):
                res.add("load", "bare server", False, srv.output(400))
                return res
            code, data, sec = upload(srv.base, path)
            err = data.get("error") if isinstance(data, dict) else str(data)
            if code != 200:
                ok = code == 400 and isinstance(err, str) and 10 < len(err) < 400 and "Traceback" not in err
                res.add("load", "upload in the app", ok, f"HTTP {code}: {err}", round(sec, 1),
                        "refused with a message (expected for unusable input)" if ok else "")
                if browser:   # the page must still open and say there is nothing loaded
                    br = Browser()
                    try:
                        br.navigate(srv.base + "/")
                        br.wait_until("document.readyState === 'complete'", 30)
                        br.settle(timeout=30)
                        st = br.eval("({status: document.querySelector('#status').innerText, panel: !document.querySelector('#loadpanel').hidden})")
                        res.add("ui", "page after a refused load", not br.events and st["panel"], _events_text(br.events), None,
                                f"status={st['status']!r}, load panel open={st['panel']}")
                    finally:
                        br.close()
                return res
            res.add("load", "upload in the app", True, "", round(sec, 1))
        code, st, _ = http(srv.base, "/api/state")
        if code != 200 or not st.get("loaded"):
            res.add("load", "state loaded", False, f"HTTP {code}: {str(st)[:300]}")
            return res
        summary = st["summary"]
        res.add("load", "state loaded", True, "", None, f"{summary.get('records')} records, pack {summary.get('pack')}")
        ids = pick_ids(srv.base, summary)
        api_cells(res, srv.base, summary, ids, xget)
        bad_input_cells(res, srv.base, xget)
        if browser:
            br = Browser()
            try:
                browser_cells(res, br, srv.base, ids, tabs)
            finally:
                br.close()
        out = srv.output(20000)
        if "Traceback" in out:
            tb = out[out.index("Traceback"):].strip().splitlines()
            res.add("server log", "no tracebacks", False, " / ".join(tb[-3:])[:400])
        return res
    finally:
        srv.stop()


# ====================================================================== A6: concurrency and lifecycle

def _grow(path, src, stop, step=150, pause=0.4):
    """Append src's lines to path, a few at a time, until stop is set or src runs out."""
    with open(src, "rb") as f:
        lines = f.readlines()
    with open(path, "wb") as out:
        for i in range(0, len(lines), step):
            if stop.is_set():
                break
            out.writelines(lines[i:i + step])
            out.flush()
            time.sleep(pause)


def concurrency(port, big_upload=None, log_dir=None):
    """Two uploads at once, live mode on a growing file during an upload, Compare loading during a main reload,
    requests during a load, and an open page across a server restart. Any 500 or hang fails a cell."""
    import threading
    res = Result("concurrency and lifecycle")
    demo = os.path.join(PKG, "samples", "demo_swarm")
    demo_file = os.path.join(demo, "demo_swarm.jsonl")
    big_upload = big_upload or os.path.join(ROOT, "full-wiki-logs", "events.jsonl")
    if not os.path.exists(big_upload):
        big_upload = demo_file
    work = os.path.realpath(tempfile.mkdtemp(prefix="st-smoke-conc-"))
    srv = Server(port, demo, None, log_dir, allow=[work])
    try:
        if not srv.wait(300):
            res.add("setup", "server with the demo swarm", False, srv.output(400))
            return res
        base = srv.base
        # 1. an upload, and while it runs: a second upload, live mode, compare, and reads
        out = {}
        th = threading.Thread(target=lambda: out.update(a=upload(base, big_upload)))
        th.start()
        busy = False
        t_end = time.time() + 60
        while time.time() < t_end and th.is_alive():
            code, st, _ = http(base, "/api/state", timeout=10)
            if code == 200 and st.get("busy"):
                busy = True
                break
            time.sleep(0.02)
        if not busy:
            res.add("upload", "first upload seen as busy in /api/state", False,
                    "the load finished before it could be observed (use a bigger --conc-file)")
        else:
            res.add("upload", "first upload seen as busy in /api/state", True)
            code, data, sec = upload(base, os.path.join(PKG, "samples", "chat_transcript.json"))
            err = data.get("error", "") if isinstance(data, dict) else str(data)
            res.add("upload", "second upload while the first runs: 409 with a clear message", code == 409 and len(err) > 10,
                    f"HTTP {code}: {err}", round(sec, 2))
            code, data, sec = http(base, "/api/stage?batch=conc1&filename=a.jsonl", "POST", b'{"id":"x","text":"y"}\n')
            code2, data2, sec2 = http(base, "/api/analyze?batch=conc1&pack=auto", "POST", b"")
            err2 = data2.get("error", "") if isinstance(data2, dict) else str(data2)
            res.add("upload", "folder analyze while an upload runs: 409 with a clear message", code2 == 409 and len(err2) > 10,
                    f"stage HTTP {code}; analyze HTTP {code2}: {err2}", round(sec2, 2))
            for p in ["/api/state", "/api/sim", "/api/events?limit=5", "/api/messages", "/api/lanes", "/api/gaps", "/api/x/identity",
                      "/api/x/compare", "/api/x/live_status", "/api/x/case"]:
                code, data, sec = http(base, p, timeout=60)
                err = data.get("error", "") if isinstance(data, dict) else str(data)
                res.add("during upload", "GET " + p, code not in (0, 500) and sec < 30, f"HTTP {code}: {str(err)[:200]}" if code != 200 else "",
                        round(sec, 2))
            feed = os.path.join(work, "feed.jsonl")
            stop = threading.Event()
            grower = threading.Thread(target=_grow, args=(feed, demo_file, stop), daemon=True)
            grower.start()
            code, data, sec = http(base, "/api/x/live_start", "POST", json.dumps({"path": feed, "interval_s": 0.5}).encode())
            # starting live mode while an upload is analyzed is refused on purpose (it would replace the upload)
            res.add("during upload", "live_start during an upload is refused with a clear message",
                    code == 409 and "upload" in str(data).lower(), f"HTTP {code}: {str(data)[:200]}", round(sec, 2))
            code, data, sec = http(base, "/api/x/compare_load", "POST", json.dumps({"path": demo}).encode(), timeout=300)
            res.add("during upload", "compare_load while the main dataset reloads", code == 200,
                    f"HTTP {code}: {str(data)[:200]}" if code != 200 else "", round(sec, 2))
        th.join(600)
        code, data, sec = out.get("a", (0, "no answer", 0))
        res.add("upload", "first upload finishes", code == 200, f"HTTP {code}: {str(data)[:200]}" if code != 200 else "", round(sec, 1))
        # after the upload, live mode must either have stopped (another dataset was loaded) or own the session
        time.sleep(2.5)
        code, ls, _ = http(base, "/api/x/live_status?since=0")
        code2, st, _ = http(base, "/api/state")
        name = (st.get("summary") or {}).get("name") if isinstance(st, dict) else None
        res.add("live", "live mode and the upload agree on who owns the dataset", code == 200 and code2 == 200,
                "", None, f"live watching={ls.get('watching') if isinstance(ls, dict) else ls}, loads={ls.get('loads') if isinstance(ls, dict) else ''}, "
                          f"error={ls.get('error') if isinstance(ls, dict) else ''}, dataset now={name!r}")
        # 2. live mode alone on the growing file: loads happen and no half-swapped state
        http(base, "/api/x/live_stop", "POST", b"")
        if busy:
            stop.set()
        feed2 = os.path.join(work, "feed2.jsonl")
        stop2 = threading.Event()
        g2 = threading.Thread(target=_grow, args=(feed2, demo_file, stop2, 100, 0.3), daemon=True)
        g2.start()
        code, data, _ = http(base, "/api/x/live_start", "POST", json.dumps({"path": feed2, "interval_s": 0.3}).encode())
        bad, seen_records, t_end = [], set(), time.time() + 8
        while time.time() < t_end:
            for p in ("/api/state", "/api/sim", "/api/messages", "/api/x/compare", "/api/gaps"):
                c, d, sec = http(base, p, timeout=30)
                if c in (0, 500) or sec > 20:
                    bad.append(f"{p}: HTTP {c} in {sec:.1f} s: {str(d)[:120]}")
                if p == "/api/state" and c == 200 and d.get("loaded"):
                    seen_records.add(d["summary"]["records"])
        stop2.set()
        code, ls, _ = http(base, "/api/x/live_status?since=0")
        res.add("live", "reads while live mode reloads a growing file: no 500, no hang", not bad, "; ".join(bad[:5]), None,
                f"record counts seen: {sorted(seen_records)[:8]}; loads={ls.get('loads') if isinstance(ls, dict) else ''}, error={ls.get('error') if isinstance(ls, dict) else ''}")
        # the summary and the views must come from one session (no half swap): records in state = events total
        c1, st, _ = http(base, "/api/state")
        c2, ev, _ = http(base, "/api/events?limit=1")
        if c1 == 200 and c2 == 200 and st.get("loaded"):
            res.add("live", "state and events agree after live reloads", st["summary"]["records"] == ev.get("total"), "",
                    None, f"state records={st['summary']['records']}, events total={ev.get('total')}")
        http(base, "/api/x/live_stop", "POST", b"")
        # 3. compare_load twice at once: one must refuse clearly
        outs = []
        ts = [threading.Thread(target=lambda: outs.append(http(base, "/api/x/compare_load", "POST", json.dumps({"path": big_upload}).encode(), timeout=600)))
              for _ in range(2)]
        [t.start() for t in ts]
        [t.join(600) for t in ts]
        codes = sorted(o[0] for o in outs)
        msgs = [str(o[1].get("error", "")) if isinstance(o[1], dict) else str(o[1]) for o in outs]
        res.add("compare", "two compare_load at once: one 200, one 409 with a message", codes == [200, 409], f"codes={codes}; {msgs}")
        # 4. an open page across a server restart with another dataset
        br = Browser()
        try:
            br.navigate(base + "/")
            br.wait_until("typeof S !== 'undefined' && !!S.summary", 60)
            br.settle(busy_expr=BUSY_JS)
            old = br.eval("S.summary.name")
            old_actor = br.eval("(document.querySelector('[data-actor]')||{dataset:{}}).dataset.actor || null")
            srv.stop()
            srv = Server(port, os.path.join(PKG, "samples", "chat_transcript.json"), None, log_dir)
            srv.wait(120)
            br.mark()
            # the app re-checks the server's dataset when the window gets focus (and every 30 s)
            br.eval("window.dispatchEvent(new Event('focus'))")
            br.wait_until("S.summary && S.summary.name !== " + json.dumps(old), 20)
            br.eval("goTab('network')")
            br.settle(busy_expr=BUSY_JS, timeout=60)
            shown = br.eval("S.summary.name")
            cleared = br.eval("!INS.stack.length")      # the old dataset's Inspector item is gone
            info = br.eval("({left: document.querySelector('#left').innerText.slice(0, 160), trace: document.querySelector('#trace').innerText.slice(0, 160), status: document.querySelector('#status').innerText})")
            stale = shown == old and old != "chat_transcript.json"
            res.add("lifecycle", "page left open across a server restart notices the new dataset", not stale and cleared and not br.events,
                    (f"still shows {old!r} after the server restarted with chat_transcript.json; " if stale else "") + _events_text(br.events),
                    None, f"top bar={shown!r}; tab: {info['left'][:100]!r}; inspector: {info['trace'][:100]!r}; status: {info['status']!r}")
        finally:
            br.close()

        # 5. after a failed load, state endpoints keep answering 200 and report the error next to their data
        # (the app's api() helper throws only on HTTP errors or an error-only reply, so tabs keep working)
        bad_file = os.path.join(work, "empty.csv")
        open(bad_file, "w").close()
        latin = os.path.join(work, "latin1.csv")
        with open(latin, "wb") as fh:
            fh.write("id,text,actor\nL1,caf\xe9,agent-1\nL2,d\xe9j\xe0,agent-2\n".encode("latin-1"))
        srv.stop()
        srv = Server(port, demo, None, log_dir, allow=[work])
        srv.wait(120)
        http(srv.base, "/api/x/compare_load", "POST", json.dumps({"path": bad_file}).encode())
        c, d, _ = http(srv.base, "/api/x/compare")
        res.add("sticky errors", "GET /api/x/compare after a failed comparison load answers 200 with its state and the error",
                c == 200 and isinstance(d, dict) and len(d) > 1, f"HTTP {c}: keys={list(d) if isinstance(d, dict) else d!r}")
        http(srv.base, "/api/x/compare_clear", "POST", b"")
        http(srv.base, "/api/x/live_start", "POST", json.dumps({"path": latin, "interval_s": 0.3}).encode())
        time.sleep(2.5)
        c, d, _ = http(srv.base, "/api/x/live_status?since=0")
        res.add("sticky errors", "GET /api/x/live_status after live mode reads a non-UTF-8 file answers 200 with its state",
                c == 200 and isinstance(d, dict) and len(d) > 1, f"HTTP {c}: keys={list(d)[:6] if isinstance(d, dict) else d!r}")
        http(srv.base, "/api/x/live_stop", "POST", b"")
        c, d, _ = upload(srv.base, bad_file)
        c2, st, _ = http(srv.base, "/api/state")
        res.add("sticky errors", "GET /api/state after a refused upload: the loaded dataset is kept",
                c2 == 200 and st.get("loaded"), f"upload HTTP {c}; state: loaded={st.get('loaded')}, error={st.get('error')!r}")
        out_log = srv.output(20000)
        if "Traceback" in out_log:
            tb = out_log[out_log.index("Traceback"):].strip().splitlines()
            res.add("server log", "no tracebacks", False, " / ".join(tb[-3:])[:400])
        return res
    finally:
        srv.stop()
        shutil.rmtree(work, ignore_errors=True)


def _xget_names():
    from agenttrace import extensions
    return extensions.routes()[0].keys()


def print_report(results, out=sys.stdout, verbose=False):
    tot = fail = 0
    for r in results:
        bad = r.failed
        tot += len(r.cells)
        fail += len(bad)
        out.write(f"\n== {r.dataset}: {len(r.cells) - len(bad)}/{len(r.cells)} pass\n")
        for c in r.cells:
            if verbose or not c["ok"] or c["area"] in ("load", "tab", "inspector", "lifecycle", "live", "upload", "compare") or "slow" in c["note"]:
                sec = f" ({c['seconds']} s)" if c["seconds"] is not None else ""
                line = f"  {'PASS' if c['ok'] else 'FAIL'} [{c['area']}] {c['name']}{sec}"
                if c["error"]:
                    line += f"\n        error: {c['error']}"
                if c["note"] and (verbose or not c["ok"] or c["area"] == "load" or "slow" in c["note"]):
                    line += f"\n        note: {c['note'][:200]}"
                out.write(line + "\n")
    out.write(f"\nSMOKE: {tot - fail}/{tot} cells pass, {fail} fail, over {len(results)} datasets\n")
    return fail


def main(argv=None):
    ap = argparse.ArgumentParser(description="Smoke test: every dataset x every tab x the Inspector, in headless Chrome.")
    ap.add_argument("--port", type=int, default=0, help="server port (default: a free one)")
    ap.add_argument("--datasets", nargs="*", default=["demo", "samples", "odd", "wiki", "big"],
                    help="big, wiki, demo, samples, odd, or [label=]path[::pack]")
    ap.add_argument("--tabs", nargs="+", default=TABS)
    ap.add_argument("--no-browser", action="store_true", help="API checks only")
    ap.add_argument("--json", help="also write every cell to this JSON file")
    ap.add_argument("--concurrency", action="store_true", help="also run the concurrency and lifecycle checks (A6)")
    ap.add_argument("--conc-file", help="file to upload in the concurrency checks (default: full-wiki-logs/events.jsonl)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    a.port = a.port or free_port()
    odd_dir = tempfile.mkdtemp(prefix="st-smoke-odd-")
    results = []
    try:
        for label, path, pack in dataset_specs(a.datasets, odd_dir):
            sys.stdout.write(f"... {label} ({path})\n")
            sys.stdout.flush()
            t0 = time.time()
            r = smoke_dataset(label, path, pack, a.port, a.tabs, browser=not a.no_browser)
            sys.stdout.write(f"    {len(r.cells) - len(r.failed)}/{len(r.cells)} pass in {time.time() - t0:.0f} s\n")
            results.append(r)
        if a.concurrency:
            sys.stdout.write("... concurrency and lifecycle\n")
            results.append(concurrency(a.port, a.conc_file))
    finally:
        shutil.rmtree(odd_dir, ignore_errors=True)
    fail = print_report(results, verbose=a.verbose)
    if a.json:
        with open(a.json, "w") as f:
            json.dump([{"dataset": r.dataset, "cells": r.cells} for r in results], f, indent=1)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

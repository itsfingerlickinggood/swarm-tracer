"""Security and robustness tests for the local server (PLAN A5): paths, packs, uploads, bodies,
headers, logging and malformed requests.

    python3 -m unittest agenttrace.tests.test_security -v
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from agenttrace import cache, compare, live, model, readers, server
from agenttrace.session import Session
from agenttrace.tests.test_server import write_trace


@contextlib.contextmanager
def data_root(d):
    with mock.patch.dict(os.environ, {"SWARM_TRACER_DATA": d}):
        yield


class PathGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.out = os.path.realpath(tempfile.mkdtemp())
        self.trace = write_trace(self.root)
        self.secret = write_trace(self.out)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_file_under_root_allowed(self):
        with data_root(self.root):
            self.assertEqual(server.check_data_path(self.trace), self.trace)
            self.assertEqual(server.check_data_path(self.root), self.root)

    def test_outside_rejected_with_hint(self):
        with data_root(self.root):
            with self.assertRaises(ValueError) as cm:
                server.check_data_path(self.secret)
        self.assertIn("--allow-path", str(cm.exception))

    def test_dotdot_rejected(self):
        with data_root(self.root):
            with self.assertRaises(ValueError) as cm:
                server.check_data_path(os.path.join(self.root, "..", os.path.basename(self.out), "trace.csv"))
        self.assertIn("..", str(cm.exception))

    def test_empty_and_nul_rejected(self):
        for bad in ("", "   ", None, 5, self.trace + "\x00x"):
            with self.assertRaises(ValueError):
                server.check_data_path(bad)

    def test_symlink_out_rejected(self):
        link = os.path.join(self.root, "link.csv")
        os.symlink(self.secret, link)
        with data_root(self.root):
            with self.assertRaises(ValueError) as cm:
                server.check_data_path(link)
        self.assertIn("link", str(cm.exception))

    def test_folder_with_link_out_rejected(self):
        d = os.path.join(self.root, "folder")
        os.mkdir(d)
        os.symlink(self.secret, os.path.join(d, "a.csv"))
        with data_root(self.root):
            with self.assertRaises(ValueError):
                server.check_data_path(d)

    def test_pipe_and_device_rejected(self):
        fifo = os.path.join(self.root, "pipe.jsonl")
        os.mkfifo(fifo)
        with data_root(self.root):
            with self.assertRaises(ValueError) as cm:
                server.check_data_path(fifo)
            self.assertIn("regular file", str(cm.exception))
            d = os.path.join(self.root, "withpipe")
            os.mkdir(d)
            os.mkfifo(os.path.join(d, "p.csv"))
            with self.assertRaises(ValueError):
                server.check_data_path(d)
        with self.assertRaises(ValueError):
            server.check_data_path("/dev/null", trusted=True)

    def test_missing_file_allowed_only_for_live_in_allowed_folder(self):
        with data_root(self.root):
            p = os.path.join(self.root, "later.jsonl")
            self.assertEqual(server.check_data_path(p, allow_missing=True), p)
            with self.assertRaises(ValueError):
                server.check_data_path(p)
            with self.assertRaises(ValueError):
                server.check_data_path(os.path.join(self.out, "later.jsonl"), allow_missing=True)

    def test_allow_path_flag(self):
        with data_root(self.root), mock.patch.object(server, "EXTRA_ROOTS", [self.out]):
            self.assertEqual(server.check_data_path(self.secret), self.secret)

    def test_live_start_uses_guard(self):
        state = dict(server.STATE)
        state.update(session=Session(), lock=threading.Lock())
        with data_root(self.root):
            with self.assertRaises(ValueError):
                live.live_start(state, {}, json.dumps({"path": self.secret}).encode())
            with self.assertRaises(ValueError):
                live.live_start(state, {}, json.dumps({"path": self.trace, "pack": "../packs/generic.json"}).encode())
            with self.assertRaises(ValueError):
                live.live_start(state, {}, b"not json")
            with self.assertRaises(ValueError):
                live.live_start(state, {}, json.dumps({"path": self.trace, "interval_s": "fast"}).encode())
        self.assertFalse(live.LIVE["watching"] and live.LIVE["path"] == self.secret)

    def test_live_tick_rechecks_path(self):
        p = os.path.join(self.root, "grow.csv")
        os.symlink(self.secret, p)    # a link out appears after live mode started
        old = {k: live.LIVE[k] for k in ("path", "guard", "session", "error", "sig")}
        state = {"session": Session(), "lock": threading.Lock()}
        try:
            with data_root(self.root):
                live.LIVE.update(path=p, guard=server.check_data_path, session=None, error=None, sig=None)
                self.assertFalse(live.check(state))
                self.assertIn("outside", live.LIVE["error"])
        finally:
            live.LIVE.update(old)

    def test_compare_load_uses_guard(self):
        state = {"session": Session(), "path_guard": server.STATE["path_guard"], "pack_guard": server.STATE["pack_guard"]}
        with data_root(self.root):
            with self.assertRaises(ValueError):
                compare.api_load(state, {}, json.dumps({"path": self.secret}).encode())
            with self.assertRaises(ValueError):
                compare.api_load(state, {}, json.dumps({"path": self.trace, "pack": "/etc/passwd"}).encode())
            with self.assertRaises(ValueError):
                compare.api_load(state, {}, b"[1, 2]")
            out = compare.api_load(state, {}, json.dumps({"path": self.trace, "pack": "generic.json"}).encode())
        self.assertTrue(out["loaded"])


class PackTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_check_pack(self):
        self.assertEqual(server.check_pack(""), "auto")
        self.assertEqual(server.check_pack("auto"), "auto")
        self.assertEqual(server.check_pack("generic.json"), "generic.json")
        for bad in ("../generic.json", "/etc/passwd", "packs/generic.json", "nope.json", "generic", ".hidden.json"):
            with self.assertRaises(ValueError):
                server.check_pack(bad)

    def test_pack_file_name_strict(self):
        for bad in ("../evil", "a/b", "/abs/x", "..", "x\\y", "UPPER", ".hidden"):
            with self.assertRaises(ValueError, msg=bad):
                readers.save_pack({"name": "x", "file": bad}, pack_dir=self.d)
        self.assertEqual(os.listdir(self.d), [])

    def test_name_is_slugged_and_saved_atomically(self):
        out = readers.save_pack({"name": "../../My Pack!"}, pack_dir=self.d)
        self.assertEqual(out["file"], "my_pack.json")
        self.assertEqual(sorted(os.listdir(self.d)), ["my_pack.json"])      # no temp file left behind
        with self.assertRaises(ValueError):
            readers.save_pack({"name": "My Pack"}, pack_dir=self.d)            # exists, no overwrite
        readers.save_pack({"name": "My Pack", "description": "v2"}, overwrite=True, pack_dir=self.d)
        with self.assertRaises(ValueError):
            readers.save_pack({"name": "generic"}, overwrite=True, pack_dir=self.d)

    def test_invalid_pack_leaves_nothing(self):
        with self.assertRaises(ValueError):
            readers.save_pack({"name": "bad", "behaviors": [{"name": "x", "pattern": "("}]}, pack_dir=self.d)
        self.assertEqual(os.listdir(self.d), [])

    def test_size_cap(self):
        with self.assertRaises(ValueError):
            readers.save_pack({"name": "big", "description": "x" * (readers.MAX_PACK_BYTES + 1)}, pack_dir=self.d)
        with self.assertRaises(ValueError):
            readers._pack_save({}, {}, b" " * (readers.MAX_PACK_BYTES + 1))

    def test_symlink_target_refused(self):
        os.symlink(os.path.join(self.d, "elsewhere.json"), os.path.join(self.d, "linked.json"))
        with self.assertRaises(ValueError):
            readers.save_pack({"name": "linked"}, overwrite=True, pack_dir=self.d)


class ServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.path = write_trace(cls.d)
        with open(cls.path, "rb") as f:
            cls.data = f.read()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.d, ignore_errors=True)

    def req(self, path, data=None, method=None, headers=None):
        r = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                   headers=headers or {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def upload(self, filename="trace.csv", data=None, pack="generic.json"):
        qs = urllib.parse.urlencode({"filename": filename, "pack": pack, "map": json.dumps({"text": "body"})})
        return self.req("/api/upload?" + qs, data=self.data if data is None else data)

    # ---- uploads
    def test_upload_filename_cannot_escape(self):
        code, _, body = self.upload("../../../../tmp/evil.csv")
        self.assertEqual(code, 200, body)
        d = server.STATE["upload_dir"]
        self.assertTrue(os.path.realpath(d).startswith(os.path.realpath(server.UPLOAD_DIR) + os.sep))
        self.assertEqual(os.listdir(d), ["evil.csv"])

    def test_upload_replaced_and_failed_dirs_cleaned(self):
        self.assertEqual(self.upload()[0], 200)
        first = server.STATE["upload_dir"]
        self.assertEqual(self.upload()[0], 200)
        self.assertFalse(os.path.exists(first))
        before = set(os.listdir(server.UPLOAD_DIR))
        self.assertEqual(self.upload("x.exe")[0], 400)
        self.assertEqual(self.upload(pack="../packs/generic.json")[0], 400)
        self.assertEqual(set(os.listdir(server.UPLOAD_DIR)), before)

    def test_upload_size_cap(self):
        with mock.patch.object(server, "MAX_UPLOAD", 100):
            code, _, body = self.upload()
        self.assertEqual(code, 413)
        self.assertIn("limit", json.loads(body)["error"])

    def test_bad_map_is_400(self):
        qs = urllib.parse.urlencode({"filename": "t.csv", "pack": "generic.json", "map": "[1"})
        self.assertEqual(self.req("/api/upload?" + qs, data=self.data)[0], 400)

    def test_stage_names_and_batch_sanitized(self):
        qs = urllib.parse.urlencode({"batch": "../../ab/c", "filename": "../../../x/../evil.csv"})
        code, _, body = self.req("/api/stage?" + qs, data=self.data)
        self.assertEqual(code, 200, body)
        d = os.path.join(server.UPLOAD_DIR, "batch-abc")
        self.assertEqual(os.listdir(d), ["evil.csv"])
        self.assertEqual(self.req("/api/stage?" + urllib.parse.urlencode({"batch": "///", "filename": "a.csv"}), data=b"x")[0], 400)
        # a skipped file leaves no partial file behind
        code, _, body = self.req("/api/stage?" + urllib.parse.urlencode({"batch": "abc", "filename": "notes.exe"}), data=b"x")
        self.assertIn("skipped", json.loads(body))
        self.assertEqual(os.listdir(d), ["evil.csv"])
        code, _, body = self.req("/api/analyze?" + urllib.parse.urlencode({"batch": "abc", "pack": "generic.json",
                                                                           "map": json.dumps({"text": "body"})}), data=b"")
        self.assertEqual(code, 200, body)

    def test_json_body_cap(self):
        code, _, body = self.req("/api/x/rules", data=b"{" + b" " * (server.MAX_JSON + 10) + b"}")
        self.assertEqual(code, 413)
        code, _, _ = self.req("/api/ai/models", data=b" " * (server.MAX_JSON + 10))
        self.assertEqual(code, 413)

    def test_bad_content_length(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/api/x/rules")
        c.putheader("Content-Length", "-1")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c.close()

    # ---- malformed queries and missing sessions
    def test_malformed_query_params(self):
        self.assertEqual(self.upload()[0], 200)
        for p in ("/api/events?offset=abc", "/api/events?limit=1e9", "/api/pairs?limit=x", "/api/list?name=identities&offset=-"):
            code, _, body = self.req(p)
            self.assertEqual(code, 400, p)
            self.assertIn("whole number", json.loads(body)["error"])
        code, _, body = self.req("/api/events?limit=99999999&offset=-5")
        self.assertEqual(code, 200)
        self.assertLessEqual(len(json.loads(body)["rows"]), 500)

    def test_every_x_route_without_session_is_4xx(self):
        saved = server.STATE["session"]
        server.STATE["session"] = Session()
        try:
            for name in sorted(server.XGET):
                if name in ("live_status", "rules", "formats", "library", "compare_state"):
                    continue     # these answer without a dataset
                code, _, body = self.req(f"/api/x/{name}?id=x&a=x&b=x&offset=x&limit=x")
                self.assertLess(code, 500, f"GET {name}: {code} {body[:200]}")
            for name in sorted(server.XPOST):
                if name in ("live_stop", "compare_clear", "live_start", "rules"):
                    continue
                for data in (b"", b"not json", b"[]"):
                    code, _, body = self.req(f"/api/x/{name}", data=data)
                    self.assertLess(code, 500, f"POST {name} {data!r}: {code} {body[:200]}")
            for p in ("/api/events", "/api/event?id=x", "/api/pairs", "/api/sim", "/api/actor?a=x"):
                self.assertEqual(self.req(p)[0], 409, p)
        finally:
            server.STATE["session"] = saved

    def test_x_post_garbage_bodies(self):
        for name, data in (("live_start", b"[]"), ("live_start", b"{\"path\": 5}"), ("rules", b"not json"),
                           ("rules", b"\"a string\""), ("rules", b"[1]"),
                           ("compare_load", b"{\"path\": \"/etc/passwd\"}"), ("pack_save", b"{\"name\": 1, \"file\": \"../x\"}")):
            code, _, body = self.req(f"/api/x/{name}", data=data)
            self.assertEqual(code, 400, f"{name} {data!r}: {body[:200]}")

    def test_compare_load_outside_roots_over_http(self):
        out = tempfile.mkdtemp(dir=os.path.expanduser("~")) if os.access(os.path.expanduser("~"), os.W_OK) else None
        if not out:
            self.skipTest("no writable home")
        try:
            p = write_trace(out)
            with data_root(self.d), mock.patch("os.getcwd", return_value=self.d):
                code, _, body = self.req("/api/x/compare_load", data=json.dumps({"path": p}).encode())
            self.assertEqual(code, 400)
            self.assertIn("outside the folders", json.loads(body)["error"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    # ---- cross-site requests and headers
    def test_foreign_host_and_origin_refused(self):
        self.assertEqual(self.req("/api/state", headers={"Host": "evil.example:8010"})[0], 403)
        self.assertEqual(self.req("/api/x/live_stop", data=b"{}", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/x/live_stop", data=b"{}", headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.req("/api/x/live_stop", data=b"{}", headers={"Origin": "http://localhost:1"})[0], 403)
        self.assertEqual(self.req("/api/x/live_stop", data=b"{}", headers={"Origin": self.base})[0], 200)
        self.assertEqual(self.req("/api/state", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_headers(self):
        code, h, _ = self.req("/")
        self.assertEqual(code, 200)
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        csp = h.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("img-src 'self' data:", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        code, h, _ = self.req("/api/state")
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        code, h, _ = self.req("/core.js")
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")

    # ---- logging
    def test_log_has_no_query_and_no_key(self):
        err = io.StringIO()
        key = "sk-SECRET-KEY-123456"
        with contextlib.redirect_stderr(err):
            self.req(f"/api/state?apiKey={key}")
            code, _, body = self.req("/api/ai/models", data=json.dumps(
                {"apiKey": key, "baseUrl": f"http://127.0.0.1:1/v1?key={key}"}).encode())
        self.assertEqual(code, 502)
        self.assertNotIn(key, err.getvalue())
        self.assertNotIn(key, body.decode())
        self.assertIn("GET /api/state", err.getvalue())

    def test_log_message_survives_bad_request_line(self):
        h = server.Handler.__new__(server.Handler)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            h.log_message("%s", "x")
        self.assertIn("-", err.getvalue())


class BindTests(unittest.TestCase):
    def test_binds_loopback_only(self):
        seen = {}

        class Fake:
            def __init__(self, addr, handler):
                seen["addr"] = addr
                raise KeyboardInterrupt

        with mock.patch.object(server, "ThreadingHTTPServer", Fake), mock.patch.object(server, "EXTRA_ROOTS", []):
            with self.assertRaises(KeyboardInterrupt):
                server.serve(0)
        self.assertEqual(seen["addr"][0], "127.0.0.1")

    def test_allow_path_must_exist(self):
        with mock.patch.object(server, "EXTRA_ROOTS", []):
            with self.assertRaises(SystemExit):
                server.serve(0, allow_paths=["/no/such/folder/anywhere"])


class InputSafetyTests(unittest.TestCase):
    def test_folder_load_skips_pipes(self):
        d = tempfile.mkdtemp()
        try:
            write_trace(d)
            os.mkfifo(os.path.join(d, "zz.jsonl"))
            evs = model.load(d)               # would block forever if it opened the pipe
            self.assertEqual(len(evs), 30)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_cache_ignores_entries_others_can_write(self):
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "x.pickle")
            with open(f, "wb") as fh:
                fh.write(b"x")
            os.chmod(d, 0o700)
            os.chmod(f, 0o600)
            self.assertTrue(cache._trusted(f))
            os.chmod(f, 0o666)
            self.assertFalse(cache._trusted(f))
            os.chmod(f, 0o600)
            os.chmod(d, 0o777)
            self.assertFalse(cache._trusted(f))
        finally:
            os.chmod(d, 0o700)
            shutil.rmtree(d, ignore_errors=True)

    def test_pack_suggest_filename_sanitized(self):
        seen = []
        orig = model.load

        def spy(p, *a, **k):
            seen.append(p)
            return orig(p, *a, **k)
        with open(write_trace(tempfile.mkdtemp()), "rb") as f:
            data = f.read()
        with mock.patch.object(model, "load", spy):
            readers._pack_suggest({}, {"filename": "../../../etc/x.csv"}, data)
        self.assertEqual(os.path.basename(seen[0]), "x.csv")
        self.assertTrue(os.path.basename(os.path.dirname(seen[0])).startswith("packsample_"))


if __name__ == "__main__":
    unittest.main()

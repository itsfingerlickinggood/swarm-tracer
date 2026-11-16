"""Tests for the v2.2.0 code fixes (audit section 3): repeated ids, odd inputs, cache key, regex limit, readable
roots, upload folders, AI base URL and redirects, route locks, saved results, and the two page modules.
Each test asserts a value, not just that something came back."""
import csv
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

from agenttrace import ai, cache, claims, claims_page, flow_page, model, safe_regex, saved, server
from agenttrace.session import Session
from agenttrace.tests.test_claims import CLAIMS, ClaimsTests

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "demo_swarm")


def write(d, name, data, mode="w"):
    p = os.path.join(d, name)
    with open(p, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        f.write(data)
    return p


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)


class RepeatedIdTests(TmpCase):
    def test_repeated_ids_are_renamed_and_reported(self):
        p = write(self.d, "dup.csv", "id,text,time\nA,x,2024-01-01\nA,y,2024-01-02\nA,z,2024-01-03\nB,q,2024-01-04\n")
        evs = model.load(p)
        self.assertEqual([e.id for e in evs], ["A", "A~2", "A~3", "B"])
        self.assertEqual([e.text for e in evs], ["x", "y", "z", "q"])
        info = model.LAST_REPORT["files"][0]["repeated_ids"]
        self.assertEqual((info["records"], info["ids"]), (2, 1))

    def test_session_keeps_every_record_and_warns(self):
        p = write(self.d, "dup.csv", "id,text,time\nA,x,2024-01-01\nA,y,2024-01-02\nB,q,2024-01-04\n")
        s = Session()
        s.load(p, "generic.json", {})
        self.assertEqual(len(s.events), 3)
        w = s.summary()["warnings"]
        self.assertEqual(len(w), 1)
        self.assertIn("1 record(s) reused an id", w[0])

    def test_unique_ids_untouched(self):
        p = write(self.d, "u.csv", "id,text\nA,x\nB,y\n")
        self.assertEqual([e.id for e in model.load(p)], ["A", "B"])
        self.assertNotIn("repeated_ids", model.LAST_REPORT["files"][0])


class OddInputTests(TmpCase):
    def err(self, name, data, mode="w"):
        p = write(self.d, name, data, mode)
        with self.assertRaises(ValueError) as cm:
            model.load(p)
        return str(cm.exception)

    def test_json_null(self):
        self.assertIn("JSON null", self.err("n.json", "null"))

    def test_json_scalar(self):
        self.assertIn("not a list of records", self.err("n.json", "5"))

    def test_nul_byte(self):
        self.assertIn("NUL", self.err("n.csv", b"a,b\n1,\x002\n", "wb"))

    def test_utf16(self):
        self.assertIn("UTF-16", self.err("u.csv", "id,text\n1,hi\n".encode("utf-16"), "wb"))

    def test_deep_json(self):
        self.assertIn("nested too deeply", self.err("d.json", "[" * 100000 + "]" * 100000))

    def test_broken_json(self):
        self.assertIn("not valid JSON", self.err("b.json", "[{"))

    def test_deep_line_in_jsonl_is_an_unreadable_line_not_a_crash(self):
        p = write(self.d, "l.jsonl", '{"id": "a", "text": "t"}\n' + "[" * 100000 + "\n")
        self.assertEqual(len(model.load(p)), 1)


class CacheKeyTests(TmpCase):
    def test_pack_content_changes_key(self):
        data = write(self.d, "t.jsonl", '{"id":"a","text":"x"}\n')
        pk = write(self.d, "pack.json", json.dumps({"name": "p", "behaviors": []}))
        k1 = cache.key(data, pk)[0]
        write(self.d, "pack.json", json.dumps({"name": "p", "behaviors": [{"name": "b", "pattern": "x"}]}))
        self.assertNotEqual(k1, cache.key(data, pk)[0])

    def test_claims_file_changes_key(self):
        data = write(self.d, "t.jsonl", '{"id":"a","text":"x"}\n')
        before = cache.content_fingerprint()
        target = os.path.join(cache.HERE, "claims", "zz_test_claims.json")
        try:
            with open(target, "w") as f:
                f.write("{}")
            self.assertNotEqual(before, cache.content_fingerprint())
        finally:
            os.remove(target)
        self.assertEqual(before, cache.content_fingerprint())
        self.assertTrue(cache.key(data, "auto")[0])

    def test_pack_is_not_pickled_and_is_reloaded(self):
        os.environ["SWARM_TRACER_CACHE_DIR"] = os.path.join(self.d, "c")
        self.addCleanup(os.environ.pop, "SWARM_TRACER_CACHE_DIR", None)
        s = Session()
        s.load(DEMO, "auto", {})
        with mock.patch.object(cache, "_skip", return_value=False):
            f = cache.store(s, DEMO, "auto", {})
            self.assertTrue(f, cache.LAST)
            import pickle
            with open(f, "rb") as fh:
                self.assertNotIn("pack", pickle.load(fh))
            t = Session()
            self.assertTrue(cache.restore(t, DEMO, "auto", {}))
        self.assertIsNot(t.pack, s.pack)
        self.assertEqual(t.pack.name, s.pack.name)
        self.assertEqual(t.summary()["records"], s.summary()["records"])


class RegexLimitTests(unittest.TestCase):
    def test_catastrophic_pattern_is_refused(self):
        with mock.patch.dict(os.environ, {"SWARM_TRACER_REGEX_LIMIT": "1"}):
            with self.assertRaises(SystemExit) as cm:
                safe_regex.check([("(a+)+$", "")], what="pack t")
        self.assertIn("(a+)+$", str(cm.exception))

    def test_ordinary_patterns_pass_and_are_remembered(self):
        pats = [(r"curl\s+-X\s+POST", "i"), (r"token=\w+", "")]
        safe_regex.check(pats)
        self.assertTrue(safe_regex._OK)

    def test_shipped_packs_pass(self):
        from agenttrace import packs
        d = os.path.join(os.path.dirname(os.path.abspath(packs.__file__)), "packs")
        for f in sorted(os.listdir(d)):
            self.assertEqual(packs.load_pack(os.path.join(d, f)).name != "", True)


class ReadableRootsTests(TmpCase):
    def test_cwd_and_package_parent_are_not_roots(self):
        with mock.patch.dict(os.environ, {"SWARM_TRACER_DATA": ""}), mock.patch("os.getcwd", return_value=self.d):
            roots = server.allowed_roots()
        self.assertNotIn(os.path.realpath(self.d), roots)
        self.assertNotIn(os.path.realpath(os.path.dirname(server.PKG_DIR)), roots)
        self.assertIn(os.path.realpath(os.path.join(server.PKG_DIR, "samples")), roots)

    def test_extension_required(self):
        write(self.d, "pyproject.toml", "x")
        ok = write(self.d, "t.csv", "id,text\n1,a\n")
        with mock.patch.dict(os.environ, {"SWARM_TRACER_DATA": self.d}):
            self.assertEqual(server.check_data_path(ok), os.path.abspath(ok))
            with self.assertRaises(ValueError) as cm:
                server.check_data_path(os.path.join(self.d, "pyproject.toml"))
        self.assertIn("not a trace file", str(cm.exception))


class UploadFolderTests(TmpCase):
    def make(self, name, age_s, marker=True):
        p = os.path.join(self.d, name)
        os.mkdir(p)
        if marker:
            write(p, server.UPLOAD_MARKER, "x")
        t = time.time() - age_s
        os.utime(p, (t, t))
        return p

    def test_only_old_marked_folders_go(self):
        old = self.make("swarmtracer-old", 3 * 86400)
        young = self.make("swarmtracer-young", 3600)
        nomark = self.make("swarmtracer-nomark", 3 * 86400, marker=False)
        other = self.make("other-old", 3 * 86400)
        self.assertEqual(server.clean_stale_uploads(self.d), 1)
        self.assertFalse(os.path.exists(old))
        for p in (young, nomark, other):
            self.assertTrue(os.path.exists(p))

    def test_own_folder_has_marker(self):
        self.assertTrue(os.path.isfile(os.path.join(server.UPLOAD_DIR, server.UPLOAD_MARKER)))


class RouteLockTests(unittest.TestCase):
    def test_same_route_shares_a_lock_different_routes_do_not(self):
        self.assertIs(server.route_lock("x/a"), server.route_lock("x/a"))
        self.assertIsNot(server.route_lock("x/a"), server.route_lock("x/b"))


class AiUrlTests(unittest.TestCase):
    def test_allowed(self):
        for u in (ai.DEFAULT_BASE_URL, "https://api.openai.com/v1", "http://localhost:11434/v1", "http://127.0.0.1:8080/v1"):
            self.assertEqual(ai.check_base_url(u), u)

    def test_refused(self):
        for u, why in (("http://api.example.com/v1", "https://"), ("ftp://x/y", "https://"), ("https://u:p@host/v1", "user name"),
                       ("https://169.254.169.254/latest", "link-local"), ("https://metadata.google.internal/x", "metadata"),
                       ("http://10.0.0.5/v1", "https://"), ("", "https://")):
            with self.assertRaises(ValueError, msg=u) as cm:
                ai.check_base_url(u)
            self.assertIn(why, str(cm.exception))

    def test_host_allowlist(self):
        with mock.patch.dict(os.environ, {"SWARM_TRACER_AI_HOSTS": "api.good.example"}):
            ai.check_base_url("https://api.good.example/v1")
            ai.check_base_url(ai.DEFAULT_BASE_URL)
            with self.assertRaises(ValueError):
                ai.check_base_url("https://other.example/v1")

    def test_call_checks_url_before_sending(self):
        with self.assertRaises(ValueError):
            ai.call("http://evil.example/v1", "sk-x", "m", [{"role": "user", "content": "hi"}])

    def test_redirect_to_other_origin_drops_authorization(self):
        seen = {}

        class Sink(http.server.BaseHTTPRequestHandler):
            def do_GET(self):      # a 302 turns the POST into a GET
                self.do_POST()

            def do_POST(self):
                seen["auth"] = self.headers.get("Authorization")
                seen["session"] = self.headers.get("x-opencode-session")
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        sink = http.server.HTTPServer(("127.0.0.1", 0), Sink)

        class Redir(Sink):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{sink.server_port}/x")
                self.send_header("Content-Length", "0")
                self.end_headers()
        first = http.server.HTTPServer(("127.0.0.1", 0), Redir)
        for s in (sink, first):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(s.shutdown)
        out = ai._post(f"http://127.0.0.1:{first.server_port}/v1/chat/completions", {"a": 1}, "sk-secret", "ses_1", 10)
        self.assertEqual(out, {"ok": True})
        self.assertIsNone(seen["auth"])
        self.assertIsNone(seen["session"])

    def test_redirect_to_refused_host_is_not_followed(self):
        class Redir(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Redir)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        with self.assertRaises(ai.ProviderError) as cm:
            ai._post(f"http://127.0.0.1:{srv.server_port}/v1/chat/completions", {}, "sk-secret", None, 10)
        self.assertIn("refused", str(cm.exception))


class SavedResultsTests(unittest.TestCase):
    def test_tables_come_from_the_saved_file_and_are_dated(self):
        from agenttrace import fx_content, fx_coord
        with open(saved.PATH, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(fx_content.SIMULATED["coordinated"], data["fx_content"]["coordinated"])
        self.assertEqual(fx_coord.SIMULATED["benign"], data["fx_coord"]["benign"])
        self.assertRegex(fx_content.SIMULATED["measured"], r"^\d{4}-\d\d-\d\d$")

    def test_missing_file_is_labelled_not_measured(self):
        with mock.patch.object(saved, "PATH", "/nonexistent/x.json"):
            e = saved.load("fx_content")
        self.assertIsNone(e["measured"])
        self.assertIn("not measured", e["note"])

    def test_saved_matches_a_fresh_measurement_for_one_seed(self):
        from agenttrace import fx_coord
        fresh = fx_coord.simulate_check(agents=40, seeds=(1,))
        with open(saved.PATH, encoding="utf-8") as f:
            sv = json.load(f)["fx_coord"]
        # one seed of three: no false links in either, as the saved three-seed table says
        self.assertEqual(fresh["benign"]["false"], 0)
        self.assertEqual(sv["benign"]["false"], 0)
        self.assertEqual(fresh["coordinated"]["false"], sv["coordinated"]["false"])


class PageModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session()
        cls.s.load(DEMO, "auto", {})

    def test_flow_page_shows_the_flow_numbers(self):
        flow = self.s.flow
        page = flow_page.render(flow, self.s.rec, "Demo <swarm>")
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("Demo &lt;swarm&gt;: message flow", page)
        self.assertIn(f"<b>{flow['deliveries']:,}</b>dated deliveries", page)
        self.assertIn(f"<b>{flow['channels']:,}</b>channels", page)
        self.assertGreater(flow["deliveries"], 0)
        top = flow["top_pairs"][0]
        self.assertIn(flow_page.esc(flow_page.short(top["from"])), page)
        self.assertEqual(page.count("<svg"), 1)
        self.assertNotIn("Demo <swarm>", page)

    def test_flow_page_without_deliveries_says_so(self):
        flow = dict(self.s.flow, first_named_delivery=None, first_named_delivery_any_channel=None, top_pairs=[])
        page = flow_page.render(flow, {"replay": []}, "t")
        self.assertIn("No delivery between two named actors was found.", page)

    def test_claims_page_counts(self):
        ClaimsTests.setUpClass()
        results = list(ClaimsTests.out.values())
        page = claims_page.render(results, CLAIMS, {"replay": []}, "T & co")
        by = ClaimsTests.out
        self.assertIn("T &amp; co", page)
        self.assertIn(f"{by['board_use']['records']:,}", page)
        self.assertEqual(by["board_use"]["records"], 2)
        self.assertEqual(by["absent"]["records"], 0)
        self.assertIn("None of these records can be dated.", page)
        self.assertIn("The report cites none.", page)
        self.assertIn(f"{by['board_use']['cited_found']}/2 found", page)

    def test_claims_page_escapes_html(self):
        ClaimsTests.setUpClass()
        results = [dict(r, says="<script>x</script>") for r in ClaimsTests.out.values()]
        page = claims_page.render(results, CLAIMS, {"replay": []}, "t")
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", page)


class KeyboardAccessSourceTests(unittest.TestCase):
    """The app's JavaScript cannot run here; these check the source carries the keyboard hooks the audit asked for."""

    @classmethod
    def setUpClass(cls):
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
        with open(os.path.join(app, "core.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_chips_rows_cards_and_omni(self):
        js = self.js
        self.assertEqual(js.count('tabindex="0" role="button"'), 4)           # actor, place, record, agent chips
        self.assertIn('class="click" data-i="${i}" tabindex="0"', js)         # table rows
        self.assertIn('document.addEventListener("focusin"', js)              # hover cards on focus
        self.assertIn('setAttribute("role", "listbox")', js)                  # omni results
        self.assertIn('o.setAttribute("role", "option")', js)
        self.assertIn('ArrowDown', js)
        self.assertIn('t.focus({ preventScroll: true })', js)                 # Inspector gets focus after Enter


if __name__ == "__main__":
    unittest.main()

"""Tests written from the survivors of the mutation run (python3 -m agenttrace.tools.mutate).

Each test is a tiny synthetic case for one statement of docs/counting-rule.md (the id is in the test name or its
docstring) and fails on at least one deliberate break of agenttrace/messages.py that the older tests let through.
The pure helpers are called directly with hand-made input; nothing here reads a dataset.

Run from the project root:
    python3 -m unittest agenttrace.tests.test_mutants -v
"""
import datetime
import re
import unittest
from types import SimpleNamespace as NS

from agenttrace import messages as M
from agenttrace.model import Event

WRX = re.compile(r"POST|PUT|/commit/", re.I)
RRX = re.compile(r"GET|HEAD|/resolve/", re.I)
HFW = re.compile(r"method:\s*['\"](POST|PUT)|/commit/", re.I)
HFR = re.compile(r"method:\s*['\"](GET|HEAD)|/resolve/", re.I)
PL = "https://huggingface.co/datasets/[X 1]"


def E(i, text="x", **kw):
    return Event(id=i, text=text, kind=kw.pop("kind", "action"), **kw)


def world(events, ids=None, times=None, raw=None, handles=None, families=None, root=None):
    """(rec, res, pack) by hand: every event has the token in `ids` (default: its actor) and its own thread."""
    ids = ids if ids is not None else {e.id: ([e.actor] if e.actor else []) for e in events}
    rec = {"_ids": ids, "_times": times or {}, "_intents": {}}
    res = {"_root": {e.id: (root or {}).get(e.id, e.id) for e in events}}
    pack = NS(raw=raw or {}, handles_rx=handles, handle_families=families or {}, harm=[])
    return rec, res, pack


# ------------------------------------------------------------------ R21 actors

class ActorTests(unittest.TestCase):
    def test_R21_thread_identity_is_the_most_used_token(self):
        evs = [E("a"), E("b"), E("c"), E("d")]
        rec, res, pack = world(evs, ids={"a": ["[T 1]"], "b": ["[T 2]"], "c": ["[T 2]"], "d": ["[T 0]", "[T 0]", "[T 0]"]},
                               raw={"shared_identities": ["[T 0]"]}, root={e.id: "r" for e in evs})
        self.assertEqual(M._thread_identity(rec, res, pack), {"r": "[T 2]"})   # a count of 0 would pick the first seen

    def test_R21_actor_field_must_be_one_of_the_records_own_tokens(self):
        e = E("a", actor="zed")
        rec, res, pack = world([e], ids={"a": ["[T 1]"]})
        self.assertEqual(M.actor_of(e, rec, res, pack), ("[T 1]", "token"))
        e = E("a", actor="[T 2]")
        rec, res, pack = world([e], ids={"a": ["[T 1]", "[T 2]"]})
        self.assertEqual(M.actor_of(e, rec, res, pack), ("[T 2]", "named"))

    def test_R21_handle_named_in_the_text_is_mapped_to_its_family(self):
        rx = re.compile(r"(?<![A-Za-z0-9])(Bob7|Al)(?![A-Za-z0-9])")
        e, plain = E("a", "hello Bob7 here"), E("b", "nobody here")
        rec, res, pack = world([e, plain], ids={"a": [], "b": []}, handles=rx, families={"Bob": "Bobs"})
        self.assertEqual(M.actor_of(e, rec, res, pack), ("Bobs", "handle"))
        self.assertEqual(M.actor_of(plain, rec, res, pack), ("run:b", "run"))     # a handle pattern that finds nothing

    def test_R21_token_of_the_thread_then_anonymous_run(self):
        a, b = E("a"), E("b")
        rec, res, pack = world([a, b], ids={"a": ["[T 1]"], "b": []}, root={"a": "r", "b": "r"})
        self.assertEqual(M.actor_of(b, rec, res, pack), ("[T 1]", "token_via_thread"))


# ------------------------------------------------------------------ R20 direct messages

class DirectTests(unittest.TestCase):
    def dm(self, evs, times=None):
        rec, res, pack = world(evs, times=times)
        return rec, M.direct_messages(evs, pack, rec, res)

    def test_R20_cached_and_empty(self):
        rec = {"_direct": "cached"}
        self.assertEqual(M.direct_messages([], None, rec, None), "cached")
        evs = [E("a", actor="A")]
        rec = {"_ids": {"a": ["A"]}}                    # no "_times" key is read when nothing is addressed
        self.assertEqual(M.direct_messages(evs, NS(raw={}), rec, {"_root": {"a": "a"}}), [])
        self.assertEqual(rec["_direct"], [])

    def test_R20_reply_is_the_first_child_by_the_recipient(self):
        evs = [E("m", actor="A", to="B", channel="c"), E("x", actor="B", channel="c"),
               E("r", actor="B", parent="m", channel="c")]
        _rec, out = self.dm(evs, {"m": 100, "x": 150, "r": 200})
        self.assertEqual((out[0]["read_id"], out[0]["_ri"], out[0]["_i"]), ("r", 2, 0))

    def test_R20_reply_time_rules(self):
        evs = lambda: [E("m", actor="A", to="B", channel="c"), E("r", actor="B", channel="c")]
        _r, out = self.dm(evs(), {"m": 100, "r": 100})                     # the same time is "not earlier"
        self.assertEqual(out[0]["read_id"], "r")
        _r, out = self.dm(evs(), {"m": 100, "r": 99})                      # earlier: not a reply
        self.assertEqual((out[0]["read_id"], out[0]["_ri"]), ("m", 0))
        _r, out = self.dm(evs(), {"m": 100})                               # reply undated: taken, read time = write time
        self.assertEqual((out[0]["read_id"], out[0]["read_time"], out[0]["latency_h"]), ("r", 100, 0.0))
        _r, out = self.dm(evs(), {"r": 100})                               # message undated: taken, still undated
        self.assertEqual((out[0]["read_id"], out[0]["write_time"], out[0]["read_time"], out[0]["latency_h"]), ("r", None, 100, 0))
        _r, out = self.dm(evs(), {})
        self.assertEqual((out[0]["write_time"], out[0]["read_time"], out[0]["latency_h"]), (None, None, 0))

    def test_R20_latency_in_hours(self):
        evs = [E("m", actor="A", to="B", channel="c"), E("r", actor="B", channel="c")]
        _r, out = self.dm(evs, {"m": 0, "r": 360000})
        self.assertEqual(out[0]["latency_h"], 100.0)

    def test_R20_reply_within_the_next_59_records_of_the_channel(self):
        def run(gap):
            evs = [E("m", actor="A", to="B", channel="c")] + [E(f"z{k}", actor="Z", channel="c") for k in range(gap - 1)]
            evs.append(E("r", actor="B", channel="c"))
            evs.append(E("o", actor="B", channel="other"))
            return self.dm(evs, {})[1][0]["read_id"]
        self.assertEqual(run(59), "r")        # 59 records after the message
        self.assertEqual(run(60), "m")        # 60 is out of reach: the message stands for both
        self.assertEqual(run(1), "r")

    def test_R20_message_to_itself_is_not_one(self):
        evs = [E("m", actor="A", to="A", channel="c")]
        self.assertEqual(self.dm(evs, {"m": 1})[1], [])

    def test_R20_perf_rows(self):
        evs = [E("m1", actor="A", to="B", channel="c"), E("r1", actor="B", channel="c"),
               E("m2", actor="C", to="B", channel="c2"), E("m3", actor="A", to="D", channel="c3"),
               E("m4", actor="A", to="D", channel="c3")]
        rec, out = self.dm(evs, {"m1": 0, "r1": 3600, "m3": 0, "m4": 100})
        rows = {r["channel"]: r for r in M._direct_perf(out)}
        self.assertEqual(rows["inbox:B"]["overwrites"], 0)
        self.assertEqual((rows["inbox:B"]["deliveries"], rows["inbox:B"]["writes"], rows["inbox:B"]["median_latency_h"]), (1, 2, 1.0))
        self.assertIsNone(rows["inbox:B"]["first_write"] and None)
        self.assertEqual(rows["inbox:D"]["median_latency_h"], 0)
        # median of two latencies is the upper one
        two = [{"channel": "i", "from": "a", "to": "b", "write_time": 0, "read_time": 7200, "latency_h": 2.0},
               {"channel": "i", "from": "a", "to": "b", "write_time": 0, "read_time": 3600, "latency_h": 1.0}]
        self.assertEqual(M._direct_perf(two)[0]["median_latency_h"], 2.0)
        undated = [{"channel": "i", "from": "a", "to": "b", "write_time": None, "read_time": None, "latency_h": 0}]
        row = M._direct_perf(undated)[0]
        self.assertEqual((row["median_latency_h"], row["deliveries"], row["writes"]), (None, 0, 1))


# ------------------------------------------------------------------ R1 places

class ChannelPatternTests(unittest.TestCase):
    def test_R1_flags_i_makes_the_pattern_case_blind_and_only_then(self):
        pack = NS(raw={"channels": [{"name": "a", "pattern": r"repo/(R\w+)", "flags": "i"},
                                    {"name": "b", "pattern": r"repo/(R\w+)"}]})
        (_, ra, _, _), (_, rb, _, _) = M.compile_channels(pack)
        self.assertTrue(ra.search("REPO/RX"))
        self.assertFalse(rb.search("REPO/RX"))
        self.assertTrue(rb.search("repo/RX"))


# ------------------------------------------------------------------ R16 call end

class CallEndTests(unittest.TestCase):
    def test_R16_ends_at_the_closing_parenthesis(self):
        self.assertEqual(M._call_end("(abc) tail", 0), 5)
        self.assertEqual(M._call_end("x(a(b)c) t", 0), 8)
        self.assertEqual(M._call_end("no paren here", 3), 13)
        self.assertEqual(M._call_end("no paren" + "x" * 800, 3), 3 + 600)

    def test_R16_cap_of_600_characters(self):
        t = "fetch(" + "x" * 1000
        self.assertEqual(M._call_end(t, 0), 5 + 600)

    def test_R16_ends_at_the_next_request_call(self):
        self.assertEqual(M._call_end("f(abc fetch(x", 0), 6)
        self.assertEqual(M._call_end("x(fetch(a", 0), 2)       # a request that starts right after the parenthesis


# ------------------------------------------------------------------ R15 options in a variable

class OptsWriteTests(unittest.TestCase):
    def test_R15_options_variable_assigned_before_the_call(self):
        pre = "o = {method:'POST'};"
        text = pre + "fetch(u, o)"
        self.assertTrue(M._opts_write(text, "fetch(u, o)", HFW, len(pre)))
        text = "o = {method:'GET'};fetch(u, o)"
        self.assertFalse(M._opts_write(text, "fetch(u, o)", HFW, 19))

    def test_R15_not_options(self):
        self.assertFalse(M._opts_write("fetch(u)", "fetch(u)", HFW, 0))                 # no trailing variable
        t = "None = {method:'POST'};fetch(u, None)"
        self.assertFalse(M._opts_write(t, "fetch(u, None)", HFW, 23))                  # a literal, not a name
        t = "o = {method:'POST'};x.open('GET', o)"
        self.assertFalse(M._opts_write(t, ".open('GET', o)", HFW, 21))                 # .open takes no options object

    def test_R15_verb_in_the_300_characters_after_the_assignment(self):
        verb = "method:'POST'"
        for pad, want in ((283, True), (284, False)):        # 5 + pad + len("method:'POST") = 300 | 301
            text = "o = {" + " " * pad + verb + "};fetch(u, o)"
            self.assertEqual(M._opts_write(text, "fetch(u, o)", HFW, text.index("fetch")), want, pad)

    def test_R15_wrapper_parameter_takes_the_verb_from_its_callers(self):
        head = "function f(p, o) {"
        text = head + " fetch(b + p, o) } f('/x', {method:'POST'})"
        before = text.index("fetch")
        self.assertTrue(M._opts_write(text, "fetch(b + p, o)", HFW, before))
        text = head + " fetch(b + p, o) } f('/x', {method:'GET'})"
        self.assertFalse(M._opts_write(text, "fetch(b + p, o)", HFW, text.index("fetch")))
        text = "x = 1; fetch(b + p, o) } f('/x', {method:'POST'})"                    # a verb after, but no wrapper
        self.assertFalse(M._opts_write(text, "fetch(b + p, o)", HFW, text.index("fetch")))
        text = "(p, o) => fetch(p, o) ;f(1, {method:'POST'})"
        self.assertTrue(M._opts_write(text, "fetch(p, o)", HFW, text.index("fetch")))

    def test_R15_wrapper_header_within_200_characters_before_the_call(self):
        head = "function f(p, o) {"
        for gap, want in ((200 - len(head), True), (201 - len(head), False)):
            text = head + " " * gap + "fetch(b + p, o) } f(1, {method:'POST'})"
            self.assertEqual(M._opts_write(text, "fetch(b + p, o)", HFW, text.index("fetch")), want, gap)
        text = head + "fetch(b + p, o) } f(1, {method:'POST'})"                          # the header is the start of the text
        self.assertTrue(M._opts_write(text, "fetch(b + p, o)", HFW, text.index("fetch")))

    def test_R15_callers_within_500_characters_after_the_call(self):
        head, seg = "function f(p, o) {", "fetch(b + p, o)"
        verb = "method:'POST'"
        base = head + " " + seg
        for pad, want in ((473, True), (474, False)):        # len(seg) + pad + len("method:'POST") = 500 | 501
            text = base[len(head) + 1:] + " " * pad + verb
            text = head + " " + text
            self.assertEqual(M._opts_write(text, seg, HFW, text.index("fetch")), want, pad)
        text = head + " " + seg + " }  f(1, {method:'POST'})"
        self.assertTrue(M._opts_write(text, seg, HFW, text.index("fetch")))
        text = "x " + seg + " } f(1, {method:'POST'})"                                   # no wrapper header: not options
        self.assertFalse(M._opts_write(text, seg, HFW, text.index("fetch")))


# ------------------------------------------------------------------ R10, R11 helper verbs

class HelperVerbTests(unittest.TestCase):
    def hv(self, text, marker="u"):
        return M._helper_verb(text, text.rindex(marker) if marker == "u" else text.index(marker))

    def test_R10_the_verb_literal_inside_the_calls_own_parentheses(self):
        self.assertEqual(self.hv("Q('GET', u)"), "read")
        self.assertEqual(self.hv("Q('POST', u)"), "write")
        self.assertEqual(self.hv("Q('GET', f(a), u)"), "read")                         # a nested call is skipped over
        self.assertEqual(self.hv("Q('PUT', g(f(a)), u) ; r('GET')"), "write")
        self.assertEqual(self.hv("Q('GET', u(b)", "u"), "read")                      # a "(" just after the position is not the call
        self.assertIsNone(self.hv("Q(x, u); Q('POST', y)"))                            # the next call does not decide
        self.assertIsNone(self.hv("'GET' u"))                                          # no enclosing call

    def test_R10_data_body_json_arguments_make_a_write(self):
        self.assertEqual(self.hv("Q(u, data=b)"), "write")
        self.assertEqual(self.hv("Q(u, x, json={})"), "write")
        self.assertIsNone(self.hv("Q(u, x)"))

    def test_R11_second_positional_argument_of_Request_is_a_body(self):
        self.assertEqual(self.hv("Request(u, data)"), "write")
        self.assertEqual(self.hv("urllib.request.Request(u, b'x')"), "write")
        self.assertIsNone(self.hv("Request(u, headers=h)"))
        self.assertIsNone(self.hv("Request(u)"))
        self.assertEqual(self.hv("Request" + " " * 5 + "(u, data)"), "write")           # up to 12 characters before "("
        self.assertIsNone(self.hv("Request" + " " * 6 + "(u, data)"))
        self.assertIsNone(self.hv("Quest(u, data)"))
        self.assertIsNone(M._helper_verb("Request(u, Request(x))", 8))                   # the next call is not this call's body
        self.assertIsNone(M._helper_verb("Request(u, urllib.request.Request(x))", 8))

    def test_R10_the_call_paren_is_looked_for_up_to_200_characters_back(self):
        for back, want in ((201, "read"), (202, None)):     # the "(" is at index 1, the position at index `back`
            text = "Q('GET'," + "a" * (back - len("Q('GET',")) + "u)"
            self.assertEqual(M._helper_verb(text, len(text) - 2), want, back)
        self.assertEqual(M._helper_verb("('GET', u)", 8), "read")                       # the call opens at the very start

    def test_R10_the_call_is_read_for_at_most_400_characters(self):
        verb = "'POST'"
        for end, want in ((401, "write"), (402, None)):     # the "(" is at index 1: 1 + 400
            text = "Q(u," + "a" * (end - len("Q(u,") - len(verb)) + verb + "b" * 500
            self.assertEqual(M._helper_verb(text, 2), want, end)

    def test_R10_a_cut_off_call_does_not_run_into_the_next_line_or_call(self):
        self.assertEqual(M._helper_verb("Q(u,'GET'\nfoo", 2), "read")                   # the verb ends right at the line break
        self.assertIsNone(M._helper_verb("Q(u\n'GET')", 2))
        self.assertIsNone(M._helper_verb("Q(u, Request(x, 'GET')", 2))
        self.assertIsNone(M._helper_verb("Q(u, urllib.request.Request('POST')", 2))
        self.assertEqual(M._helper_verb("Q(u,'POST'Request(", 2), "write")


# ------------------------------------------------------------------ R12 request as data

class DescriptorTests(unittest.TestCase):
    def dv(self, text, pos=None):
        return M._descriptor_verb(text, text.index("PLACE") if pos is None else pos)

    def test_R12_method_key_decides_else_body_makes_a_write(self):
        self.assertEqual(self.dv('{"u":"PLACE","m":"POST"}'), "write")
        self.assertEqual(self.dv('{"u":"PLACE","m":"GET","b":1}'), "read")
        self.assertEqual(self.dv('{"url":"PLACE","method":"DELETE"}'), "write")
        self.assertEqual(self.dv('{"u":"PLACE","b":"x"}'), "write")
        self.assertIsNone(self.dv('{"u":"PLACE"}'))
        self.assertIsNone(self.dv('x = "PLACE"; {"m":"POST"}'))                       # not the url of such an object
        self.assertEqual(self.dv('"u":"PLACE","m":"POST"'), "write")                  # the key starts the text

    def test_R12_url_key_window_is_20_characters(self):
        self.assertEqual(self.dv('"url" :"' + "a" * 12 + 'PLACE","m":"POST"'), "write")        # 8 + 12 = 20
        self.assertIsNone(self.dv('"url" : "' + "a" * 12 + 'PLACE","m":"POST"'))              # 9 + 12 = 21

    def test_R12_object_ends_at_its_closing_brace(self):
        self.assertIsNone(self.dv('{"u":"PLACE"} "m":"POST"'))                        # the brace is at index 0
        self.assertIsNone(self.dv('x{"u":"PLACE"} y "m":"POST"'))
        self.assertEqual(self.dv('{"u":"PLACE","m":"POST"'), "write")                 # no closing brace: to the end

    def test_R12_window_before_is_600_and_after_1500(self):
        key = '"m":"POST",'
        u = '"u":"PLACE"'
        for pad, want in ((600 - len(key) - 5, "write"), (601 - len(key) - 5, None)):
            text = "{" + key + "a" * pad + u
            self.assertEqual(self.dv(text), want, pad)
        for pad, want in ((1478, "write"), (1479, None)):    # 1 + len(u) + pad + len('"m":"POST"') = 1500 | 1501
            text = "{" + u + "a" * pad + '"m":"POST"}'
            self.assertEqual(M._descriptor_verb(text, text.index("PLACE")), want, pad)

    def test_R12_without_braces_300_characters_each_way(self):
        key = '"m":"POST"'
        u = '"u":"PLACE"'
        for pad, want in ((285, "write"), (286, None)):      # the key starts 300 | 301 before the place
            text = key + "a" * pad + u
            self.assertEqual(M._descriptor_verb(text, text.index("PLACE")), want, pad)
        text = key + "a" * 400 + u + " " * 10
        self.assertIsNone(M._descriptor_verb(text, text.index("PLACE")))
        # after the place
        for pad, want in ((284, "write"), (285, None)):      # the key ends 300 | 301 after the place starts
            text = u + "a" * pad + key
            self.assertEqual(M._descriptor_verb(text, text.index("PLACE")), want, pad)


# ------------------------------------------------------------------ R17 hidden holder

class HiddenHolderTests(unittest.TestCase):
    def hh(self, text, mark="PLACE"):
        s = text.index(mark)
        return M._hidden_holder_written(text, s, s + len(mark), HFW)

    def test_R17_later_call_through_a_name_writes(self):
        self.assertTrue(self.hh("u='PLACE'; fetch(v, {method:'POST'})"))
        self.assertFalse(self.hh("u='PLACE'; fetch(v, {method:'GET'})"))
        self.assertFalse(self.hh("u='PLACE'; fetch('https://x.org/a', {method:'POST'})"))    # a literal address: another place
        self.assertFalse(self.hh("x = 'PLACE' + y; fetch(v, {method:'POST'})"))              # the literal does not close its statement

    def test_R17_a_config_value_is_not_a_held_name(self):
        self.assertFalse(self.hh('\nk: "PLACE"\nfetch(v,{method:\'POST\'})'))       # the only line break is the first character
        self.assertFalse(self.hh('a\nk: "PLACE"\nfetch(v,{method:\'POST\'})'))
        self.assertFalse(self.hh('  path: "PLACE"\nfetch(v,{method:\'POST\'})'))
        self.assertTrue(self.hh('a\nk = "PLACE"\nfetch(v,{method:\'POST\'})'))

    def test_R17_options_in_a_variable_count_as_a_write(self):
        self.assertTrue(self.hh("u='PLACE'; o={method:'POST'}; fetch(v, o)"))

    def test_R17_later_call_within_8000_characters(self):
        head = "u='PLACE'; "
        call = "fetch("
        for gap, want in ((7991, True), (7992, False)):       # "'; " + gap + "fetch(" = 8000 | 8001
            text = head + " " * gap + call + "v, {method:'POST'})"
            s = text.index("PLACE")
            self.assertEqual(M._hidden_holder_written(text, s, s + 5, HFW), want, gap)
        text = head + " " * 5000 + call + "v, {method:'POST'})"
        self.assertTrue(self.hh(text))


# ------------------------------------------------------------------ R6 to R17: _judge

W = re.compile("WRITE")
R = re.compile("READ")
T = "t" * 60          # a tail long enough that the record does not "end right after the place" (R13)


def jh(text, bounds=None, w=W, r=R, fn=None):
    s = text.index("PLACE")
    return (fn or M.judge_how)(text, s, s + 5, w, r, bounds)


class JudgeWindowTests(unittest.TestCase):
    """R14: 160 characters before the mention, 260 after, through each of the three public entry points."""

    def test_R14_window_before_and_after(self):
        before_in, before_out = "WRITE" + "a" * 155 + "PLACE " + T, "WRITE" + "a" * 156 + "PLACE " + T
        after_in, after_out = "PLACE" + "a" * 255 + "WRITE" + T, "PLACE" + "a" * 256 + "WRITE" + T
        self.assertEqual(jh(before_in), ("write", 0, 226, "inferred"))
        self.assertEqual(jh(before_out), ("read", 1, 227, "default"))
        self.assertEqual(jh(after_in), ("write", 0, 265, "inferred"))
        self.assertEqual(jh(after_out), ("read", 0, 265, "default"))
        self.assertEqual(jh(before_in, fn=M.judge_span), ("write", 0, 226))
        self.assertEqual(jh(before_out, fn=M.judge_span), ("read", 1, 227))
        self.assertEqual(jh(after_in, fn=M.judge_span), ("write", 0, 265))
        self.assertEqual(jh(after_out, fn=M.judge_span), ("read", 0, 265))
        self.assertEqual([jh(t, fn=M.judge_op) for t in (before_in, before_out, after_in, after_out)],
                         ["write", "read", "write", "read"])

    def test_R4_neighbouring_mentions_bound_the_window(self):
        text = "WRITE aaa PLACE bbb " + T
        self.assertEqual(jh(text), ("write", 0, 80, "inferred"))
        self.assertEqual(jh(text, bounds=(6, 40)), ("read", 6, 40, "default"))

    def test_R14_nearest_verb_and_ties(self):
        self.assertEqual(jh("READ" + " " * 6 + "PLACE WRITE " + T)[0], "write")        # same distance: the write verb wins
        self.assertEqual(jh("READ PLACE" + " " * 40 + "WRITE" + " " * 60 + "READ " + T)[0], "read")   # the nearest, not the last
        self.assertEqual(jh("READPLACE " + T, w=re.compile("EA"))[0], "read")          # touching the place is distance 0
        self.assertEqual(jh("W-PLACE " + T, w=re.compile("W-PLACE"), r=re.compile("-"))[0], "write")   # so is spanning its start
        self.assertEqual(jh("READPLACE " + " " * 30 + "WRITE" + T)[0], "read")
        self.assertEqual(jh("x WRITE PLACE " + T), ("write", 0, 74, "inferred"))       # not in a request call: inferred

    def test_R8_a_verb_before_the_request_call_is_not_its_verb(self):
        self.assertEqual(jh("WRITE; fetch('PLACE') " + T), ("read", 7, 82, "default"))
        self.assertEqual(jh("fetch(url='PLACE', WRITE) " + T), ("write", 0, 86, "call"))   # url= inside a call is not an assignment


class JudgeLfsTests(unittest.TestCase):
    def test_R6_info_lfs_within_40_characters(self):
        self.assertEqual(jh("x PLACE/" + "a" * 31 + "info/lfs " + T), ("mention", 2, 7, None))
        self.assertEqual(jh("x PLACE/" + "a" * 32 + "info/lfs " + T), ("read", 0, 109, "default"))
        op = "operation:'upload'; x "
        self.assertEqual(jh(op + "PLACE/" + "a" * 31 + "info/lfs " + T), ("write", 22, 128, "inferred"))
        self.assertEqual(jh(op + "PLACE/" + "a" * 32 + "info/lfs " + T), ("read", 0, 129, "default"))

    def test_R6_operation_up_to_300_characters_before_a_batch_path(self):
        op = "operation:'upload'"
        self.assertEqual(jh(op + " " * 282 + "PLACE/info/lfs " + T), ("write", 300, 375, "inferred"))
        self.assertEqual(jh(op + " " * 283 + "PLACE/info/lfs " + T), ("mention", 301, 306, None))

    def test_R6_operation_before_the_mention_is_not_its_own_without_a_batch_path(self):
        self.assertEqual(jh("operation:'upload'; x = PLACE and " + T), ("read", 0, 94, "default"))
        self.assertEqual(jh("fetch(a,{operation:'upload'}); x = PLACE and " + T), ("read", 0, 105, "default"))
        self.assertEqual(jh("fetch(B={operation:'upload'}, PLACE) " + T), ("write", 30, 97, "inferred"))   # inside its own call

    def test_R6_operation_up_to_the_end_of_the_next_request_call(self):
        call = "fetch(v,{operation:'upload'}) "
        self.assertEqual(jh("x PLACE" + " " * 394 + call + T), ("write", 2, 430, "inferred"))     # the call starts within 400
        self.assertEqual(jh("x PLACE" + " " * 395 + call + T), ("read", 0, 267, "default"))
        self.assertEqual(jh("fetch('PLACE/info/lfs/objects/batch', {body:B}); fetch(x, {operation:'upload'}) " + T),
                         ("write", 7, 79, "inferred"))

    def test_R6_operation_within_300_characters_when_no_request_call_follows(self):
        op = "operation:'upload'"
        self.assertEqual(jh("fetch('PLACE', {" + " " * 278 + op + T), ("write", 7, 312, "inferred"))
        self.assertEqual(jh("fetch('PLACE', {" + " " * 279 + op + T), ("read", 0, 272, "default"))
        self.assertEqual(jh("x = PLACE" + " " * 282 + op + T), ("write", 4, 309, "inferred"))
        self.assertEqual(jh("x = PLACE" + " " * 283 + op + T), ("read", 0, 269, "default"))

    def test_R7_repository_in_a_variable_within_40_characters(self):
        self.assertEqual(jh("x PLACE/'+" + "r" * 34 + "+'/commit WRITE " + T), ("mention", 2, 7, None))
        self.assertEqual(jh("x PLACE/'+" + "r" * 35 + "+'/commit WRITE " + T), ("write", 0, 121, "inferred"))


class JudgeNameTests(unittest.TestCase):
    def test_R9_assignment_is_looked_for_200_characters_back(self):
        self.assertEqual(jh("u='" + "a" * 197 + "PLACE'; fetch(u, WRITE) " + T), ("write", 208, 223, "inferred"))
        self.assertEqual(jh("u='" + "a" * 198 + "PLACE'; fetch(u, WRITE) " + T), ("mention", 201, 206, None))   # R17 instead

    def test_R9_uses_are_looked_for_8000_characters_on(self):
        self.assertEqual(jh("u='PLACE';" + " " * 7990 + "fetch(u, WRITE) " + T), ("write", 8000, 8015, "inferred"))
        self.assertEqual(jh("u='PLACE';" + " " * 7991 + "fetch(u, WRITE) " + T), ("mention", 3, 8, None))

    def test_R9_the_request_call_that_takes_the_name_starts_within_60_characters(self):
        self.assertEqual(jh("u='PLACE'; fetch(" + "a" * 54 + ", u, WRITE) " + T), ("write", 11, 82, "inferred"))
        self.assertEqual(jh("u='PLACE'; fetch(" + "a" * 55 + ", u, WRITE) " + T), ("read", 0, 195, "inferred"))
        self.assertEqual(jh("fetch(\nu='PLACE',u, WRITE) " + T), ("write", 0, 26, "inferred"))       # the call starts the record

    def test_R9_span_is_the_first_call_that_takes_the_name(self):
        self.assertEqual(jh("u='PLACE'; fetch(u); fetch(u, READ) " + T), ("read", 11, 19, "inferred"))
        pre = "a" * 100 + ";"
        self.assertEqual(jh(pre + "u='PLACE'; Q('GET', u); " + "b" * 50 + " Q('GET', u) " + T), ("read", 39, 242, "inferred"))
        self.assertEqual(jh(pre + "u='PLACE'; f(u); " + "b" * 50 + " g(u) " + T), ("read", 33, 235, "inferred"))
        self.assertEqual(jh("u='PLACE'; Q('GET', u) " + T), ("read", 0, 141, "inferred"))
        self.assertEqual(jh("u='PLACE'; f(u) " + T), ("read", 0, 134, "inferred"))

    def test_R10_span_of_a_helper_write(self):
        self.assertEqual(jh("u='PLACE'; Q('POST', u) " + T), ("write", 0, 142, "inferred"))
        self.assertEqual(jh("a" * 100 + ";u='PLACE'; Q('POST', u) " + T), ("write", 40, 243, "inferred"))

    def test_R11_write_verb_beside_a_literal(self):
        self.assertEqual(jh("req('PLACE', " + "a" * 50 + ", 'POST', d) " + T), ("write", 5, 71, "inferred"))
        self.assertEqual(jh("Q('POST'," + " " * 110 + "'PLACE', body) " + T), ("write", 0, 125, "inferred"))   # 120 back
        self.assertEqual(jh("Q('POST'," + " " * 111 + "'PLACE', body) " + T), ("read", 0, 195, "default"))


class JudgeCutTests(unittest.TestCase):
    def test_R13_cut_inside_the_call_before_its_verb(self):
        self.assertEqual(jh("fetch('PLACE',{metho\n" + T), ("mention", 7, 12, None))
        self.assertEqual(jh("fetch('PLACE',{" + " " * 22 + "metho\n" + T), ("mention", 7, 12, None))      # within 30 characters
        self.assertEqual(jh("fetch('PLACE',{" + " " * 23 + "metho\n" + T), ("read", 0, 104, "default"))

    def test_R13_record_ends_within_40_characters_inside_an_open_call(self):
        self.assertEqual(jh("fetch('PLACE" + "a" * 40), ("mention", 7, 12, None))
        self.assertEqual(jh("fetch('PLACE" + "a" * 41), ("read", 0, 53, "default"))
        self.assertEqual(jh("f(" + "a" * 119 + "PLACE"), ("mention", 121, 126, None))            # the "(" is 120 back
        self.assertEqual(jh("f(" + "a" * 120 + "PLACE"), ("read", 0, 127, "default"))
        self.assertEqual(jh("('PLACE"), ("mention", 2, 7, None))                                 # the "(" starts the record
        self.assertEqual(jh("https://x.org/PLACE"), ("mention", 14, 19, None))                   # a bare URL
        self.assertEqual(jh("see PLACE"), ("read", 0, 9, "default"))


# ------------------------------------------------------------------ R2, R4, R5, R18, R19, R21a: operations

REPO = {"channels": [{"name": "repo", "pattern": r"repo/(R\w*)", "write": "WRITE", "read": "READ"}], "structural_channels": False}


def ops_of(events, raw=REPO, **kw):
    rec, res, pack = world(events, raw=raw, **kw)
    return M.channel_ops(events, pack, rec, res)


def one(text, raw=REPO):
    return {o[0]: o[1] for o in ops_of([E("e", text, actor="A")], raw)}


class OperationTests(unittest.TestCase):
    def test_R4_each_mention_is_judged_between_its_neighbours(self):
        pad = " pad pad pad pad "
        self.assertEqual(one("WRITE repo/RA"), {"repo:RA": "write"})
        self.assertEqual(one("repo/RA" + pad + "repo/RB WRITE"), {"repo:RA": "read", "repo:RB": "write"})
        self.assertEqual(one("WRITE repo/RA" + pad + "repo/RB"), {"repo:RA": "write", "repo:RB": "read"})
        self.assertEqual(one("repo/RA WRITE" + pad + "repo/RB" + pad + "repo/RC"), {"repo:RA": "write", "repo:RB": "write", "repo:RC": "read"})
        # the text of a neighbouring mention is not code: a verb inside its name does not count
        self.assertEqual(one("repo/RWRITE1" + pad + "repo/RB tail")["repo:RB"], "read")
        self.assertEqual(one("repo/RA" + pad + "repo/RWRITE1")["repo:RA"], "read")

    def test_R1_a_match_with_an_empty_group_is_not_a_mention(self):
        raw = {"channels": [{"name": "repo", "pattern": r"repo/(\w*)", "write": "WRITE"}], "structural_channels": False}
        self.assertEqual(one("repo/RA pad pad repo/ WRITE", raw), {"repo:RA": "write"})     # nor a boundary for its neighbour

    def test_R5_a_write_anywhere_in_the_record_makes_the_operation_a_write(self):
        self.assertEqual(one("WRITE repo/RA ; " + "pad " * 60 + " repo/RA"), {"repo:RA": "write"})
        self.assertEqual(one("repo/RA ; " + "pad " * 80 + " WRITE repo/RA"), {"repo:RA": "write"})

    def test_R2_only_action_kinds_operate(self):
        raw = dict(REPO, action_kinds=["action"])
        evs = [E("a", "repo/RA WRITE", actor="A"), E("b", "repo/RA WRITE", actor="B", kind="reply")]
        self.assertEqual([o[6] for o in ops_of(evs, raw)], ["a"])

    def test_R21a_the_token_named_in_the_judged_call_is_the_actor(self):
        raw = dict(REPO, structural_channels=True)
        two = {"e": ["[T 1]", "[T 2]"]}
        e = E("e", "tok [T 1]; fetch('repo/RA', WRITE, [T 2]) " + T, channel="room1")
        got = {o[0]: o[2:5] for o in ops_of([e], raw, ids=two, times={"e": 5})}
        self.assertEqual(got, {"place:room1": ("[T 1]", "token", 5), "repo:RA": ("[T 2]", "token", 5)})
        e = E("e", "tok [T 1] [T 2]; fetch('repo/RA', WRITE) " + T)                      # neither token in the call
        self.assertEqual([o[2] for o in ops_of([e], ids=two)], ["[T 1]"])
        e = E("e", "tok [T 1]; fetch('repo/RA', WRITE, [T 2]) " + T, actor="[T 1]")      # the actor field wins (R21 step 1)
        self.assertEqual([o[2:4] for o in ops_of([e], ids=two)], [("[T 1]", "named")])

    def test_R18_post_and_write_only_kinds(self):
        raw = {"write_only_kinds": ["delete"]}
        evs = [E("a", "x", actor="A", channel="room1"), E("b", "x", actor="B", channel="room1", kind="delete"), E("c", "x", actor="C")]
        self.assertEqual([o[:3] for o in ops_of(evs, raw)], [("place:room1", "post", "A"), ("place:room1", "write", "B")])
        self.assertEqual(ops_of(evs, {"structural_channels": False}), [])

    def test_R19_naming_another_structural_place_reads_it(self):
        raw = {"mention_channels": True}
        evs = [E("p1", "first page", actor="A", channel="wikiA~pageone"), E("p2", "second", actor="B", channel="wikiB~pageone"),
               E("q", "see pageone and other1 now", actor="C", channel="wikiA~other1"),
               E("s", "look at pageone", actor="D", channel="plain77"), E("n", "look at pageone", actor="F"),
               E("m1", "x", actor="G", channel="ns~wiki~topicxx"), E("m2", "x", actor="H", channel="ns~blog~topicxx"),
               E("m3", "about topicxx", actor="I", channel="ns~wiki~reader1"), E("m4", "about topicxx", actor="J", channel="zz~reader2")]
        got = {}
        for o in ops_of(evs, raw):
            got.setdefault(o[6], set()).add((o[0], o[1]))
        self.assertEqual(got["q"], {("place:wikiA~other1", "post"), ("place:wikiA~pageone", "read")})    # own prefix preferred
        both = {("place:wikiA~pageone", "read"), ("place:wikiB~pageone", "read")}
        self.assertEqual(got["s"], both | {("place:plain77", "post")})
        self.assertEqual(got["n"], both)
        self.assertEqual(got["m3"], {("place:ns~wiki~reader1", "post"), ("place:ns~wiki~topicxx", "read")})
        self.assertEqual(got["m4"], {("place:zz~reader2", "post"), ("place:ns~wiki~topicxx", "read"), ("place:ns~blog~topicxx", "read")})
        self.assertEqual(got["p1"], {("place:wikiA~pageone", "post")})

    def test_R19_short_names_of_six_or_more_characters(self):
        evs = [E("a", channel="w~abcdef"), E("b", channel="w~abcde"), E("c"), E("d", channel="x#abcdef")]
        self.assertEqual(dict(M._mention_index(evs)), {"abcdef": {"w~abcdef", "x#abcdef"}})
        self.assertIsNone(M._short(None))
        self.assertEqual(M._short(""), "")

    def test_R20_direct_messages_become_inbox_operations(self):
        evs = [E("m", actor="A", to="B", channel="c"), E("r", actor="B", channel="c"), E("n", actor="A", to="C", channel="c")]
        got = ops_of(evs, {"structural_channels": False}, times={"m": 100, "r": 200, "n": 300})
        self.assertEqual(got, [("inbox:B", "write", "A", "named", 100, 0, "m"), ("inbox:B", "read", "B", "named", 200, 1, "r"),
                               ("inbox:C", "write", "A", "named", 300, 2, "n")])


# ------------------------------------------------------------------ R22 to R29: deliveries

def op(ch, kind, actor, t, i, rid, ak="token"):
    return (ch, kind, actor, ak, t, i, rid)


class DeliveryTests(unittest.TestCase):
    def test_R22_R24_the_delivery_record_and_the_place_row(self):
        ops = [op("p", "write", "A", 0, 0, "w", "named"), op("p", "read", "B", 360000, 1, "r", "run")]
        out, perf, unknown, same, over, rereads = M.deliveries(ops)
        self.assertEqual(out, [{"channel": "p", "from": "A", "from_kind": "named", "to": "B", "to_kind": "run", "write_id": "w",
                                "read_id": "r", "write_time": 0, "read_time": 360000, "latency_h": 100.0, "how": "read in code"}])
        self.assertEqual(perf, [{"channel": "p", "writes": 1, "reads": 1, "writers": 1, "readers": 1, "actors": 2,
                                 "first_write": M.iso(0), "first_read": M.iso(360000), "deliveries": 1, "overwrites": 0,
                                 "median_latency_h": 100.0, "never_read": False, "read_without_write_seen": False}])
        self.assertEqual((unknown, same, over, rereads), (0, 0, [], 0))

    def test_R23_one_record_is_never_both_ends(self):
        ops = [op("p", "write", "A", 1, 0, "X"), op("p", "read", "B", 2, 0, "X")]
        self.assertEqual(M.deliveries(ops)[0], [])

    def test_R25_undated_read_is_order_unknown_only_with_a_write_by_another(self):
        self.assertEqual(M.deliveries([op("p", "write", "A", 1, 0, "w"), op("p", "read", "B", None, 1, "r")])[2], 1)
        self.assertEqual(M.deliveries([op("p", "write", "A", 1, 0, "w"), op("p", "read", "A", None, 1, "r")])[2], 0)

    def test_R28_the_earliest_read_is_the_delivery(self):
        w = op("p", "write", "A", 100, 0, "w")
        late, early = op("p", "read", "B", 300, 1, "late", "a"), op("p", "read", "B", 200, 2, "early", "b")
        out = M.deliveries([w, late, early])
        self.assertEqual(([d["read_id"] for d in out[0]], out[5]), (["early"], 1))
        # epoch 0 is a time like any other
        out = M.deliveries([op("p", "write", "A", 0, 0, "w"), op("p", "read", "B", 1, 1, "late"), op("p", "read", "B", 0, 2, "early")])
        self.assertEqual([d["read_id"] for d in out[0]], ["early"])
        # same time: the one earlier in the input, whatever the order of the list or of the ids
        out = M.deliveries([w, op("p", "read", "B", 200, 2, "a-second"), op("p", "read", "B", 200, 1, "z-first")])
        self.assertEqual([d["read_id"] for d in out[0]], ["z-first"])

    def test_R29_what_a_post_added_is_compared_with_the_post_before_it_in_time(self):
        l1, l2, l3 = "line one of the page", "line two of the page", "line three of it"
        texts = {"a": l1, "b": l1 + "\n" + l2, "c": l1 + "\n" + l2 + "\n" + l3, "u": "undated post text"}
        ops = [op("p", "post", "C", 300, 0, "c", "x"), op("p", "post", "B", 200, 1, "b", "y"), op("p", "post", "A", 100, 2, "a", "z"),
               op("p", "post", "D", None, 5, "u", "w")]
        out = M.deliveries(ops, texts=texts)
        self.assertEqual({(d["write_id"], d["read_id"]): d["how"] for d in out[0]},
                         {("a", "b"): "kept 1 of 1 lines it added", ("b", "c"): "kept 1 of 1 lines it added"})
        self.assertEqual(out[0][0]["lines"], [l1])
        self.assertEqual(out[4], [])

    def test_R29_posts_at_the_same_time_are_taken_in_input_order(self):
        l1, l2 = "line one of the page", "line two of the page"
        texts = {"a": l1, "b": l1 + "\n" + l2, "z": l1}
        ops = [op("p", "post", "A", 100, 1, "a"), op("p", "post", "A", 100, 0, "b"), op("p", "post", "Z", 200, 2, "z")]
        out = M.deliveries(ops, texts=texts)       # b came first and added both lines; z kept one of them
        self.assertEqual([(d["write_id"], d["how"]) for d in out[0]], [("b", "kept 1 of 2 lines it added")])

    def test_R29_lines_of_8_or_more_characters_and_the_sample_shown(self):
        self.assertEqual(M._lines("12345678\n1234567\n  123456789  \n12345678"), {"12345678", "123456789"})
        lines = [f"wanted line {k}" for k in range(5)]
        text = "\n".join(["other"] + lines + [lines[0]])
        self.assertEqual(M._in_order(text, set(lines)), lines[:3])
        self.assertEqual(M._in_order(text, set(lines[3:])), lines[3:])
        a, b = "a" * 160, "b" * 161
        self.assertEqual(M._in_order(a + "\n" + b, {a, b}), [a, "b" * 159 + "\u2026"])

    def test_R31_estimated_time_one_hour_apart_is_not_more_than_an_hour(self):
        how = {("w", "p"): "call", ("r", "p"): "call"}
        grade = lambda gap: M.deliveries([op("p", "write", "A", 0, 0, "w"), op("p", "read", "B", gap, 1, "r")],
                                         how=how, estimated=lambda rid: True)[0][0]["grade"]
        self.assertEqual((grade(3600), grade(3660)), ("direct", "weak"))


# ------------------------------------------------------------------ R27 same program, and content spread

def words(n, seed="w"):
    return [f"{seed}{chr(97 + k // 26)}{chr(97 + k % 26)}" for k in range(n)]


class ProgramTests(unittest.TestCase):
    def test_R27_normalizing(self):
        self.assertEqual(M._norm("x [REDACTED:destination:000233] y"), "x <redacted> y")
        self.assertEqual(M._norm("A  [HF REPO] 12 deadbeef01"), "a <hf_repo> <n> <h>")

    def test_R27_first_60_tokens_and_at_least_20(self):
        base = words(70)
        same = base[:60] + ["changed"] + base[61:]
        other = base[:59] + ["changed"] + base[60:]
        got = M.program_prefix([E("a", " ".join(base)), E("b", " ".join(same)), E("c", " ".join(other)),
                                E("d", " ".join(base[:20])), E("e", " ".join(base[:19]))])
        self.assertEqual(set(got), {"a", "b", "c", "d"})
        self.assertEqual(got["a"], got["b"])
        self.assertNotEqual(got["a"], got["c"])
        self.assertEqual(len(got["a"]), 12)

    def test_families_need_12_tokens_and_the_listed_kinds(self):
        w = words(12)
        evs = [E("a", " ".join(w)), E("b", " ".join(w[:11])), E("c", " ".join(w), kind="reply")]
        self.assertEqual(set(M.families(evs)), {"a", "c"})
        self.assertEqual(set(M.families(evs, {"action"})), {"a"})
        self.assertEqual(len(M.families(evs)["a"]), 12)


SPREAD_RAW = {"channels": [{"name": "repo", "pattern": r"repo/(\w+)", "write": "WRITE", "read": "READ"},
                           {"name": "opt", "pattern": r"opt/(\w*)", "write": "WRITE"}], "structural_channels": False}
PROG = " ".join(words(14))


class SpreadTests(unittest.TestCase):
    def spread(self, extra="", written=frozenset(), intents=None, harm=("bad",), copies=(("a", "A", 100), ("b", "B", 200))):
        evs = [E(i, PROG + extra, actor=a) for i, a, _t in copies]
        rec, res, pack = world(evs, raw=SPREAD_RAW, times={i: t for i, _a, t in copies if t is not None})
        rec["_intents"] = intents or {}
        pack.harm = list(harm) if harm is not None else None
        return M.content_spread(evs, pack, rec, res, None, None if written is None else set(written))

    def routine(self, *a, **kw):
        out = self.spread(*a, **kw)
        self.assertEqual(len(out), 1)
        return out[0]["routine"]

    def test_the_entry(self):
        out = self.spread(copies=(("zz", "A", 300), ("aa", "B", 200), ("cc", "A", 250), ("u", "C", None)))
        fam = out[0].pop("family")
        self.assertEqual(len(fam), 12)
        self.assertEqual(out, [{"copies": 4, "dated_copies": 3, "source": "B", "source_time": M.iso(200), "source_record": "aa",
                                "adopters": [{"actor": "A", "time": M.iso(250), "record": "cc", "hours_after_source": 0.01}],
                                "actors": 2, "routine": True}])
        out = self.spread(copies=(("a", "A", 0), ("b", "B", 10000)))
        self.assertEqual(out[0]["adopters"][0]["hours_after_source"], 2.78)
        out = self.spread(copies=(("a", "A", 0), ("b", "B", 360000)))
        self.assertEqual(out[0]["adopters"][0]["hours_after_source"], 100.0)

    def test_same_time_the_copy_earlier_in_the_input_is_the_source(self):
        out = self.spread(copies=(("zz", "A", 100), ("aa", "B", 100)))
        self.assertEqual(out[0]["source_record"], "zz")

    def test_one_named_actor_is_not_spread(self):
        self.assertEqual(self.spread(copies=(("a", "A", 100), ("b", "A", 200))), [])
        # an anonymous run is not a named actor, even when it is the earliest copy
        evs = [E("r", PROG), E("a", PROG, actor="A"), E("b", PROG, actor="B")]
        rec, res, pack = world(evs, raw=SPREAD_RAW, times={"r": 50, "a": 100, "b": 200})
        out = M.content_spread(evs, pack, rec, res)
        self.assertEqual((out[0]["source"], out[0]["actors"], out[0]["copies"]), ("A", 2, 3))
        self.assertEqual(self.spread(copies=(("a", "A", 100),)), [])

    def test_short_texts_form_no_family(self):
        evs = [E("a", "short", actor="A"), E("b", "short", actor="B")]
        rec, res, pack = world(evs, raw=SPREAD_RAW, times={"a": 1, "b": 2})
        self.assertEqual(M.content_spread(evs, pack, rec, res), [])

    def test_routine_or_not(self):
        self.assertTrue(self.routine())
        self.assertTrue(self.routine(harm=None))
        self.assertFalse(self.routine(intents={"a": "bad"}))                       # does something the pack counts as harm
        self.assertTrue(self.routine(intents={"a": "fine"}))
        self.assertFalse(self.routine(" repo/RA WRITE"))                           # writes to a place
        self.assertTrue(self.routine(" repo/RA READ"))                             # reads a place nobody wrote to
        self.assertFalse(self.routine(" repo/RA READ", written={"repo:RA"}))       # reads a place somebody wrote to
        self.assertFalse(self.routine(" repo/RA READ", written=None))              # no list of written places: any place counts
        self.assertTrue(self.routine("\n# repo/RA WRITE"))                         # R3: only in a comment
        self.assertTrue(self.routine(" opt/ WRITE"))                               # R1: empty group

    def test_routine_looks_at_the_first_8_copies(self):
        copies = tuple((f"c{k}", "AB"[k % 2], 100 + k) for k in range(9))
        self.assertFalse(self.routine(copies=copies, intents={"c7": "bad"}))
        self.assertTrue(self.routine(copies=copies, intents={"c8": "bad"}))


# ------------------------------------------------------------------ R30 the count: message_flow

def flow_of(events, raw, times, ids=None, harm_times=None):
    rec, res, pack = world(events, raw=raw, ids=ids, times=times)
    rec["_harm_times"] = harm_times or []
    return M.message_flow(events, pack, rec, res)


class FlowTests(unittest.TestCase):
    def small(self):
        evs = [E("e0", "repo/RA WRITE", actor="A"), E("e1", "repo/RA READ", actor="B"), E("e2", "repo/RB WRITE"),
               E("e3", "repo/RB READ", actor="B"), E("e4", "repo/RC READ", actor="A"), E("e5", "repo/RD WRITE", actor="A")]
        return flow_of(evs, dict(REPO, action_kinds=["action"]),
                       {"e0": 1000, "e1": 1100, "e2": 900, "e3": 1000, "e4": 1200, "e5": 1300}, harm_times=[1101, 1100, 1099])

    def test_R30_counts(self):
        f = self.small()
        self.assertEqual((f["deliveries"], f["deliveries_between_named_actors"], f["actor_pairs"], f["named_actor_pairs"]), (2, 1, 2, 1))
        self.assertEqual(f["actors_on_channels"], {"named": 2, "run": 1})
        self.assertEqual(f["channel_types"], {"repo": {"channels": 4, "writes": 3, "reads": 3, "deliveries": 2, "never_read": 1}})
        self.assertEqual((f["operations"], f["records_on_channels"], f["channels"]), (6, 6, 4))
        self.assertEqual(f["latency_hours"], {"median": 0.03, "p90": 0.03})
        self.assertEqual(f["deliveries_by_how"], {"read in code": 2})
        self.assertEqual(f["top_pairs"], [{"from": "A", "to": "B", "deliveries": 1, "channels": 1, "first": M.iso(1100)}])

    def test_R37_first_delivery_between_named_actors(self):
        f = self.small()
        for key in ("first_named_delivery", "first_named_delivery_any_channel"):
            self.assertEqual((f[key]["read_id"], f[key]["read_time"], f[key]["write_time"]), ("e1", M.iso(1100), M.iso(1000)), key)
        self.assertEqual(f["harm_share_after_first_named_delivery"], 0.333)       # harm strictly after the read, of all harm

    def test_no_deliveries(self):
        f = flow_of([E("e0", "repo/RA WRITE", actor="A")], REPO, {"e0": 1}, harm_times=[5])
        self.assertEqual((f["latency_hours"], f["harm_share_after_first_named_delivery"], f["first_named_delivery"]),
                         ({"median": None, "p90": None}, None, None))

    def test_R31_only_an_estimated_time_weakens(self):
        w, r = "fetch('repo/RA', WRITE) " + T, "fetch('repo/RA', READ) " + T
        t0 = datetime.datetime(2026, 7, 9)
        times = {"e0": 1000, "e1": 1000 + 7200}
        f = flow_of([E("e0", w, actor="A", time=t0), E("e1", r, actor="B", time=t0)], REPO, times)
        self.assertEqual(f["deliveries_by_grade"], {"direct": 1})                  # both records carry their own time
        f = flow_of([E("e0", w, actor="A", time=t0), E("e1", r, actor="B")], REPO, times)
        self.assertEqual(f["deliveries_by_grade"], {"weak": 1})                    # the read's time was estimated

    def test_spread_uses_the_places_written_and_the_action_kinds(self):
        p1, p2, p3 = (" ".join(words(14, s)) for s in "xyz")
        evs = [E("e0", "repo/RA WRITE", actor="A"),
               E("f1a", p1 + " repo/RA READ", actor="A"), E("f1b", p1 + " repo/RA READ", actor="B"),
               E("f2a", p2 + " repo/RC READ", actor="A"), E("f2b", p2 + " repo/RC READ", actor="B"),
               E("g1", p3, actor="A", kind="reply"), E("g2", p3, actor="B", kind="reply")]
        f = flow_of(evs, dict(REPO, action_kinds=["action"]), {e.id: 100 + k for k, e in enumerate(evs)})
        self.assertEqual({s["source_record"]: s["routine"] for s in f["_content_spread"]}, {"f1a": False, "f2a": True})
        self.assertEqual(f["content_families_moving"], 2)

    def test_list_caps(self):
        evs = [E("w", "repo/RA WRITE", actor="A")] + [E(f"r{k}", "repo/RA READ", actor=f"X{k}") for k in range(62)]
        f = flow_of(evs, REPO, {e.id: 10 + k for k, e in enumerate(evs)})
        self.assertEqual((f["named_actor_pairs"], len(f["top_pairs"])), (62, 60))
        evs = [E(f"w{k}", f"repo/R{k:03d}x WRITE", actor="A") for k in range(42)]
        f = flow_of(evs, REPO, {e.id: 10 + k for k, e in enumerate(evs)})
        self.assertEqual((f["channels"], len(f["_channels"]), len(f["top_channels"])), (42, 42, 40))
        evs = []
        for k in range(42):
            text = " ".join(words(14, chr(97 + k // 26) + chr(97 + k % 26)))
            evs += [E(f"a{k}", text, actor="A"), E(f"b{k}", text, actor="B")]
        f = flow_of(evs, REPO, {e.id: 10 + k for k, e in enumerate(evs)})
        self.assertEqual((f["content_families_moving"], len(f["_content_spread"]), len(f["content_spread"])), (42, 42, 40))

    def test_R29_overwrite_pairs_listed(self):
        evs = []
        for k in range(16):
            evs += [E(f"w{k}", f"first line of page {k}x\nsecond line of page", actor=f"W{k}", channel=f"page{k}"),
                    E(f"x{k}", f"something else entirely {k}x", actor=f"X{k}", channel=f"page{k}")]
        f = flow_of(evs, {"full_body_posts": True}, {e.id: 10 + k for k, e in enumerate(evs)})
        self.assertEqual((f["overwrites"], f["deliveries"], len(f["top_overwrite_pairs"])), (16, 0, 15))
        self.assertEqual(f["top_overwrite_pairs"][0], {"from": "W0", "to": "X0", "overwrites": 1})


if __name__ == "__main__":
    unittest.main()

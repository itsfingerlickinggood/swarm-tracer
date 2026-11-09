"""The on-disk record index (recindex.py): record text read back from the source file by seeking."""
import json
import os
import shutil
import tempfile
import unittest

from agenttrace import cache, model, recindex
from agenttrace.session import Session
from agenttrace.tests.test_live import append, rows

ENV = ("SWARM_TRACER_CACHE_DIR", "SWARM_TRACER_CACHE_MIN", "SWARM_TRACER_LAZY_TEXT_MIN", "SWARM_TRACER_NO_CACHE")


class RecordIndexTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.saved = {k: os.environ.get(k) for k in ENV}
        os.environ.pop("SWARM_TRACER_NO_CACHE", None)
        os.environ["SWARM_TRACER_CACHE_DIR"] = os.path.join(self.d, "cache")
        os.environ["SWARM_TRACER_CACHE_MIN"] = "0"
        os.environ["SWARM_TRACER_LAZY_TEXT_MIN"] = "1"
        recindex.forget()
        self.p = os.path.join(self.d, "trace.jsonl")
        recs = rows(0, 20)
        recs[3]["body"] = "a longer body with unicode: café → done " * 3
        append(self.p, recs)
        # a chat record expands into one event per message (ids R1#0, R1#1)
        append(self.p, [{"id": "R1", "sender": "agent-9", "sent_at": "2026-11-01T11:00:00Z",
                         "messages": [{"role": "user", "content": "hello there"},
                                      {"role": "assistant", "content": "general kenobi"}]}])

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        recindex.forget()
        shutil.rmtree(self.d, ignore_errors=True)

    def load(self):
        s = Session()
        s.load(self.p, "generic.json", {"text": "body"})
        return s

    def test_index_built_and_restored_session_reads_text_by_seek(self):
        full = self.load()
        self.assertFalse(cache.LAST["hit"])
        key = cache.key(self.p, "generic.json", {"text": "body"})[0]
        self.assertTrue(os.path.isfile(recindex.index_path(key)))
        idx = recindex.RecordIndex(recindex.index_path(key))
        self.assertTrue(idx.fresh())
        # offsets point at the record's own line
        with open(self.p, "rb") as f:
            data = f.read()
        off, ln = idx.locate("M0003")
        self.assertEqual(json.loads(data[off:off + ln])["id"], "M0003")
        self.assertEqual(idx.locate("R1#1"), idx.locate("R1#0"))
        self.assertIsNone(idx.locate("nope"))

        lazy = self.load()
        self.assertTrue(cache.LAST["hit"])
        self.assertTrue(cache.LAST["lazy_text"])
        e = lazy.by_id["M0003"]
        self.assertIsInstance(e, model.LazyEvent)
        self.assertIsNone(e.__dict__["_text"])          # not held in memory
        self.assertIs(lazy.events[3], e)                 # one object, shared by every index
        for a in full.events:
            self.assertEqual(lazy.record_text(a.id), a.text)
        self.assertEqual(lazy.trace("M0003")["text"], full.trace("M0003")["text"])
        self.assertEqual(lazy.trace("R1#1")["text"], "general kenobi")
        self.assertEqual(lazy.search("kenobi")["total"], 1)
        self.assertEqual(lazy.summary()["records"], full.summary()["records"])

    def test_changed_source_ignores_the_index(self):
        self.load()
        lazy = self.load()
        self.assertTrue(cache.LAST["lazy_text"])
        text = lazy.record_text("M0005")
        self.assertNotEqual(text, recindex.UNAVAILABLE)
        # the file changes while the restored session is open: the index no longer describes it
        with open(self.p, "r+b") as f:
            f.seek(0)
            f.write(b"{")                                # same size; the time moves on
            f.seek(0, 2)
            f.write(b"\n")
        os.utime(self.p, ns=(1, 1))
        key = cache.key(self.p, "generic.json", {"text": "body"})[0]
        self.assertFalse(recindex.RecordIndex(recindex.index_path(lazy.by_id["M0005"].__dict__["_src"])).fresh())
        self.assertEqual(lazy.record_text("M0006"), recindex.UNAVAILABLE)
        # loading again analyzes the changed file afresh (new cache key), with real text
        again = self.load()
        self.assertFalse(cache.LAST["hit"])
        self.assertEqual(again.record_text("M0006"), rows(6, 7)[0]["body"])
        self.assertNotEqual(key, lazy.by_id["M0005"].__dict__["_src"])

    def test_missing_index_means_a_normal_load(self):
        self.load()
        key = cache.key(self.p, "generic.json", {"text": "body"})[0]
        os.remove(recindex.index_path(key))
        recindex.forget()
        s = self.load()
        self.assertFalse(cache.LAST["hit"])             # the textless entry was useless, so it was dropped
        self.assertEqual(s.record_text("M0001"), "status ok")
        self.assertNotIsInstance(s.by_id["M0001"], model.LazyEvent)

    def test_tampered_index_never_returns_another_records_text(self):
        self.load()
        key = cache.key(self.p, "generic.json", {"text": "body"})[0]
        f = recindex.index_path(key)
        with open(f, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        # point M0002 at M0004's line
        at = {ln.split("\t", 3)[3]: ln for ln in lines[1:]}
        o4 = at["M0004"].split("\t")
        lines[lines.index(at["M0002"])] = "\t".join(o4[:3] + ["M0002"])
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        idx = recindex.RecordIndex(f)
        self.assertIsNone(idx.text("M0002"))
        self.assertEqual(idx.text("M0004"), rows(4, 5)[0]["body"])

    def test_small_inputs_and_other_formats_keep_text_in_memory(self):
        os.environ["SWARM_TRACER_LAZY_TEXT_MIN"] = "off"
        self.load()
        s = self.load()
        self.assertTrue(cache.LAST["hit"])
        self.assertFalse(cache.LAST["lazy_text"])
        self.assertNotIsInstance(s.by_id["M0001"], model.LazyEvent)
        # a CSV file is not indexed
        os.environ["SWARM_TRACER_LAZY_TEXT_MIN"] = "1"
        csv_p = os.path.join(self.d, "t.csv")
        with open(csv_p, "w") as f:
            f.write("id,sender,sent_at,body\n")
            for r in rows(0, 6):
                f.write(f"{r['id']},{r['sender']},{r['sent_at']},\"{r['body']}\"\n")
        a = Session()
        a.load(csv_p, "generic.json", {"text": "body"})
        b = Session()
        b.load(csv_p, "generic.json", {"text": "body"})
        self.assertTrue(cache.LAST["hit"])
        self.assertFalse(cache.LAST["lazy_text"])
        self.assertEqual(b.record_text("M0001"), "status ok")


if __name__ == "__main__":
    unittest.main()

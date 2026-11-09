"""On-disk record index: where each record's line sits in its source file, so a very large dataset's
record text can be read back by seeking instead of being held in memory.

    ~/.swarm-tracer/cache/<key>.recidx       next to the cache entry <key>.pickle (cache.py)

cache.store builds it for a single JSON-lines file at least SWARM_TRACER_LAZY_TEXT_MIN bytes large
(default 200 MB; "off" disables) that was read by field name, and then writes the cached session
without record text: its events come back as model.LazyEvent, whose text is fetched through the
index the first time something asks for it (Session.trace, Session.record_text, search ...).

The index is optional and safe:
- its header records the source file's size and modification time; if the file has changed since,
  the index is ignored and a record's text reads as UNAVAILABLE (the cache entry itself is keyed on
  the same size and time, so a changed file is analyzed afresh on the next load);
- every fetched line is parsed again and must produce the record with the id that was asked for;
- it is plain text (a JSON header, then offset, length, row and id per line), never unpickled.
"""
import json
import os
import threading
from collections import OrderedDict

VERSION = 1
SUFFIX = ".recidx"
UNAVAILABLE = ("[record text unavailable: the source file changed (or its record index is missing) since this "
               "dataset was loaded; load the dataset again to read it]")
_LOCK = threading.Lock()
_OPEN = {}          # key -> RecordIndex (or None when it could not be read)
LRU_SIZE = 512


def lazy_min():
    """Inputs at least this large are cached without record text (None: never)."""
    v = os.environ.get("SWARM_TRACER_LAZY_TEXT_MIN", "").strip().lower()
    if v in ("off", "no", "false", "never"):
        return None
    try:
        return int(v) if v else 200_000_000
    except ValueError:
        return 200_000_000


def index_path(key, d=None):
    from . import cache
    return os.path.join(d or cache.cache_dir(), key + SUFFIX)


def _stat(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def build(session, path, key, d=None):
    """Write the index for session's source file. Returns its path, or None when this input is not one
    the index can describe exactly (several files, a framework format, not JSON lines, odd line ends)."""
    from . import model
    path = os.path.abspath(path)
    rep = getattr(session, "read_report", None) or {}
    files = rep.get("files") or []
    if not os.path.isfile(path) or len(files) != 1 or files[0].get("format_key") \
            or os.path.splitext(path)[1].lower() != ".jsonl":
        return None
    cols = files[0].get("fields")
    if not isinstance(cols, dict):
        return None
    size, mtime = _stat(path)
    enc = model._encoding(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = index_path(key, d)
    tmp = out + ".part"
    rows = 0
    try:
        with open(path, "rb") as f, open(tmp, "w", encoding="utf-8") as w:
            w.write(json.dumps({"v": VERSION, "path": path, "size": size, "mtime_ns": mtime, "encoding": enc,
                                "stem": stem, "cols": cols}) + "\n")
            off, first = 0, True
            while True:
                raw = f.readline()
                if not raw:
                    break
                start, off = off, off + len(raw)
                body = raw.rstrip(b"\r\n")
                if b"\r" in body:            # the text reader splits there too; offsets would disagree
                    return None
                line = body.decode(enc, errors="replace")
                if first:
                    first = False
                    if line.lstrip().startswith("["):   # read as one JSON array, not line by line
                        return None
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                rows += 1
                for e in model._events_from_row(obj, cols, stem, rows):
                    if "\n" in e.id or "\r" in e.id:
                        return None
                    w.write(f"{start}\t{len(raw)}\t{rows}\t{e.id}\n")
        if rows != files[0].get("rows") or _stat(path) != (size, mtime):
            return None
        os.replace(tmp, out)
        tmp = None
        with _LOCK:
            _OPEN.pop(key, None)
        return out
    except (OSError, ValueError):
        return None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class RecordIndex:
    def __init__(self, file):
        with open(file, encoding="utf-8") as f:
            head = json.loads(f.readline())
            if not isinstance(head, dict) or head.get("v") != VERSION:
                raise ValueError("unknown record index format")
            self.head = head
            self.at = {}
            for line in f:
                off, ln, row, rid = line.rstrip("\n").split("\t", 3)
                self.at[rid] = (int(off), int(ln), int(row))
        self.path = head["path"]
        self._texts = OrderedDict()

    def fresh(self):
        """True while the source file is the one the index was built from."""
        try:
            return _stat(self.path) == (self.head["size"], self.head["mtime_ns"])
        except OSError:
            return False

    def locate(self, rid):
        """(byte offset, length) of the line holding record rid, or None."""
        hit = self.at.get(rid)
        return hit[:2] if hit else None

    def text(self, rid):
        """The record's text read from the source file, or None (unknown id, or the file changed)."""
        from . import model
        if rid in self._texts:
            self._texts.move_to_end(rid)
            return self._texts[rid]
        hit = self.at.get(rid)
        if hit is None or not self.fresh():
            return None
        off, ln, row = hit
        try:
            with open(self.path, "rb") as f:
                f.seek(off)
                raw = f.read(ln)
            line = raw.rstrip(b"\r\n").decode(self.head["encoding"], errors="replace").strip()
            obj = json.loads(line)
        except (OSError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        e = next((e for e in model._events_from_row(obj, self.head["cols"], self.head["stem"], row) if e.id == rid), None)
        if e is None:
            return None
        self._texts[rid] = e.text
        while len(self._texts) > LRU_SIZE:
            self._texts.popitem(last=False)
        return e.text


def open_index(key):
    """The RecordIndex for a cache key (cached per process), or None if it is missing or unreadable."""
    if not key:
        return None
    with _LOCK:
        if key in _OPEN:
            return _OPEN[key]
        try:
            idx = RecordIndex(index_path(key))
        except (OSError, ValueError, KeyError, TypeError):
            idx = None
        _OPEN[key] = idx
        return idx


def forget(key=None):
    with _LOCK:
        if key is None:
            _OPEN.clear()
        else:
            _OPEN.pop(key, None)


def fetch_text(key, rid):
    idx = open_index(key)
    t = None
    if idx is not None:
        with _LOCK:
            t = idx.text(rid)
    return UNAVAILABLE if t is None else t

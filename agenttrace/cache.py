"""A disk cache of analyzed sessions, so reloading a large dataset takes seconds instead of a minute.

Session.load calls restore() first and store() after a full analysis. The cache key is the sha1 of
the input (path, size and modification time of every file in it), the pack, the column mapping and
the tool's own code and packs, so editing the data, the pack or the code invalidates it.

    ~/.swarm-tracer/cache/<sha1>.pickle      (SWARM_TRACER_CACHE_DIR moves it)

SWARM_TRACER_NO_CACHE=1 turns it off. Inputs smaller than SWARM_TRACER_CACHE_MIN bytes (default
1 MB) load fast anyway and are not cached; nor are files the app received as uploads (they live in
a fresh temporary folder each time). Any failure to read or write the cache falls back to a normal
load: the cache can only make loading faster, never change what is loaded.

A very large single JSON-lines file (SWARM_TRACER_LAZY_TEXT_MIN bytes, default 200 MB) is cached
without its record text: an on-disk record index (<sha1>.recidx, recindex.py) maps each record id to
its line's byte offset and length, and the restored session reads a record's text by seeking.
"""
import gc
import hashlib
import json
import os
import pickle
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 1
MAX_ENTRIES = 8              # keep the newest few; a large dataset's entry can be hundreds of MB
LAST = {"hit": None, "key": None, "seconds": None, "error": None, "lazy_text": None}


def enabled():
    return os.environ.get("SWARM_TRACER_NO_CACHE", "").strip() not in ("1", "true", "yes")


def cache_dir():
    return os.environ.get("SWARM_TRACER_CACHE_DIR") or os.path.join(os.path.expanduser("~"), ".swarm-tracer", "cache")


def _min_bytes():
    try:
        return int(os.environ.get("SWARM_TRACER_CACHE_MIN", 1_000_000))
    except ValueError:
        return 1_000_000


def _files(path):
    """(relative name, size, mtime) of the input: one file, or every file under a folder."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        st = os.stat(path)
        return [("", st.st_size, st.st_mtime_ns)]
    out = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, path), st.st_size, st.st_mtime_ns))
    return out


_CODE = None


def code_fingerprint():
    """The tool's own code and packs: a change to either means a cached analysis may be out of date."""
    global _CODE
    if _CODE is None:
        h = hashlib.sha1()
        for sub in ("", "packs"):
            d = os.path.join(HERE, sub)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith((".py", ".json")):
                    st = os.stat(os.path.join(d, f))
                    h.update(f"{sub}/{f}:{st.st_size}:{st.st_mtime_ns};".encode())
        h.update(f"py{sys.version_info[:2]}".encode())
        _CODE = h.hexdigest()
    return _CODE


def key(path, pack_file, mapping=None):
    files = _files(path)
    h = hashlib.sha1()
    h.update(json.dumps({"v": VERSION, "path": os.path.abspath(path), "files": files, "pack": pack_file or "auto",
                         "map": sorted((mapping or {}).items()), "code": code_fingerprint()}).encode())
    return h.hexdigest(), sum(f[1] for f in files)


def _skip(path, size):
    if not enabled() or size < _min_bytes():
        return True
    # uploads land in a new temporary folder each time; caching them would only fill the disk
    tmp = os.path.realpath(tempfile.gettempdir())
    real = os.path.realpath(path)
    return real.startswith(tmp) and os.sep + "swarmtracer-" in real


def _trusted(f):
    """Unpickling runs code, so only read entries this user wrote, in a folder only this user can change."""
    if not hasattr(os, "getuid"):
        return True
    try:
        for p in (f, os.path.dirname(f)):
            st = os.lstat(p)
            if st.st_uid != os.getuid() or st.st_mode & 0o022 or (p == f and not os.path.isfile(p)) or os.path.islink(p):
                return False
    except OSError:
        return False
    return True


def restore(session, path, pack_file, mapping=None, name=None):
    """Fill session from the cache. True if it did; False (and nothing changed) otherwise."""
    LAST.update(hit=False, key=None, seconds=None, error=None, lazy_text=None)
    try:
        k, size = key(path, pack_file, mapping)
    except OSError:
        return False
    if _skip(path, size):
        return False
    LAST["key"] = k
    f = os.path.join(cache_dir(), k + ".pickle")
    if not os.path.isfile(f):
        return False
    if not _trusted(f):
        LAST["error"] = "cache entry not written by this user (or writable by others); ignored"
        return False
    t0 = time.time()
    try:
        gc.disable()   # unpickling millions of small objects is much faster without the collector
        try:
            with open(f, "rb") as fh:
                state = pickle.load(fh)
        finally:
            gc.enable()
        if not isinstance(state, dict) or state.get("_cache_version") != VERSION:
            raise ValueError("old cache format")
        state.pop("_cache_version", None)
        if state.pop("_lazy_text", None):
            # the record text lives in the source file; without a usable index the entry is useless
            from . import recindex
            recindex.forget(k)
            idx = recindex.open_index(k)
            if idx is None or not idx.fresh():
                raise ValueError("record index missing or out of date")
            LAST["lazy_text"] = True
    except Exception as e:  # corrupt, truncated, or written by other code: forget it and load normally
        LAST["error"] = f"{type(e).__name__}: {e}"
        try:
            os.remove(f)
        except OSError:
            pass
        return False
    session.__dict__.update(state)
    if name:
        session.name = name
    summ = getattr(session, "_summary", None)
    if isinstance(summ, dict):
        summ["name"] = session.name
    os.utime(f)   # most recently used
    LAST.update(hit=True, seconds=round(time.time() - t0, 2))
    return True


def store(session, path, pack_file, mapping=None):
    """Write the analyzed session. Returns the cache file, or None if it was skipped or failed."""
    try:
        k, size = key(path, pack_file, mapping)
        if _skip(path, size):
            return None
        d = cache_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        state = dict(session.__dict__)
        state["_cache_version"] = VERSION
        f = os.path.join(d, k + ".pickle")
        lazy = _lazy_index(session, path, k, size, d)
        if lazy:
            state["_lazy_text"] = True
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                (_LazyPickler(fh, k) if lazy else pickle.Pickler(fh, protocol=pickle.HIGHEST_PROTOCOL)).dump(state)
            os.replace(tmp, f)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        prune(d)
        return f
    except Exception as e:  # something in the session cannot be pickled, or the disk is full
        LAST["error"] = f"{type(e).__name__}: {e}"
        return None


def _lazy_index(session, path, k, size, d):
    """Build the record index when this input is large enough to cache without record text."""
    from . import recindex
    lo = recindex.lazy_min()
    if lo is None or size < lo:
        return False
    return recindex.build(session, path, k, d) is not None


class _LazyPickler(pickle.Pickler):
    """Writes every Event without its text; it comes back as a model.LazyEvent reading the index."""

    def __init__(self, fh, key):
        super().__init__(fh, protocol=pickle.HIGHEST_PROTOCOL)
        self.key = key
        from . import model
        self.model = model

    def reducer_override(self, obj):
        m = self.model
        if type(obj) is m.Event or type(obj) is m.LazyEvent:
            fields = {k: v for k, v in obj.__dict__.items() if k not in ("text", "_text", "_src")}
            return m._lazy_event, (self.key, fields)
        return NotImplemented


def prune(d=None, keep=MAX_ENTRIES):
    d = d or cache_dir()
    try:
        entries = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".pickle")),
                         key=os.path.getmtime, reverse=True)
    except OSError:
        return
    for f in entries[keep:]:
        try:
            os.remove(f)
        except OSError:
            pass
    try:   # record indexes whose cache entry is gone
        for f in os.listdir(d):
            if f.endswith(".recidx") and not os.path.exists(os.path.join(d, f[:-len(".recidx")] + ".pickle")):
                os.remove(os.path.join(d, f))
    except OSError:
        pass


def clear():
    d = cache_dir()
    n = 0
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith((".pickle", ".part", ".recidx")):
                os.remove(os.path.join(d, f))
                n += 1
    return n

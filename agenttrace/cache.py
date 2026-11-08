"""A disk cache of analyzed sessions, so reloading a large dataset takes seconds instead of a minute.

Session.load calls restore() first and store() after a full analysis. The cache key is the sha1 of
the input (path, size and modification time of every file in it), the pack, the column mapping and
the tool's own code and packs, so editing the data, the pack or the code invalidates it.

    ~/.swarm-tracer/cache/<sha1>.pickle      (SWARM_TRACER_CACHE_DIR moves it)

SWARM_TRACER_NO_CACHE=1 turns it off. Inputs smaller than SWARM_TRACER_CACHE_MIN bytes (default
1 MB) load fast anyway and are not cached; nor are files the app received as uploads (they live in
a fresh temporary folder each time). Any failure to read or write the cache falls back to a normal
load: the cache can only make loading faster, never change what is loaded.
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
LAST = {"hit": None, "key": None, "seconds": None, "error": None}


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


def restore(session, path, pack_file, mapping=None, name=None):
    """Fill session from the cache. True if it did; False (and nothing changed) otherwise."""
    LAST.update(hit=False, key=None, seconds=None, error=None)
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
        os.makedirs(d, exist_ok=True)
        state = dict(session.__dict__)
        state["_cache_version"] = VERSION
        f = os.path.join(d, k + ".pickle")
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                pickle.dump(state, fh, protocol=pickle.HIGHEST_PROTOCOL)
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


def clear():
    d = cache_dir()
    n = 0
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith((".pickle", ".part")):
                os.remove(os.path.join(d, f))
                n += 1
    return n

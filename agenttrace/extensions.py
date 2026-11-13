"""Feature modules add API routes here without touching server.py.

Each module listed in MODULES may define
    GET  = {"name": fn(state, q)}            -> served at GET  /api/x/<name>
    POST = {"name": fn(state, q, body)}      -> served at POST /api/x/<name>
state is the server's STATE dict (state["session"] is the loaded Session; it may be unloaded),
q the query parameters (first value of each), body the raw request bytes. Return a JSON-able object;
raise LookupError for "not found / not loaded" (HTTP 409) and ValueError for bad input (HTTP 400).
"""
import importlib

MODULES = ["readers", "identity", "live", "casework", "compare", "fx_lineage", "fx_behavior", "fx_whatif", "validation", "trace", "units", "attribution", "fx_content", "fx_coord", "benchmark", "board", "spreadmap", "earlywarn", "online", "sensitivity"]


def routes():
    get, post = {}, {}
    for m in MODULES:
        mod = importlib.import_module("agenttrace." + m)
        get.update(getattr(mod, "GET", {}))
        post.update(getattr(mod, "POST", {}))
    return get, post

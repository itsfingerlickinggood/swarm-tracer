"""Interaction test: hover, click and type on every kind of control in every tab, in headless Chrome.

    python3 -m agenttrace.tools.interact --quick                 # the demo swarm on its own server: each tab, about 2 minutes
    python3 -m agenttrace.tools.interact                         # every tab and Forensics section, two of each kind of control;
                                                                 # the demo swarm, then the release on :8010 if it answers
    python3 -m agenttrace.tools.interact --deep                  # the first and last of every signature (slow)
    python3 -m agenttrace.tools.interact --base http://127.0.0.1:8023 --big http://127.0.0.1:8010
    python3 -m agenttrace.tools.interact --only big --tabs network forensics:whatif

The smoke test loads every tab; this one uses them. On each tab (and each Forensics section, the top bar and the
Inspector) it lists every interactive element by kind: buttons, the Count-by switch, record / actor / place / agent
chips, glossary terms, table rows with a handler, SVG marks with a handler or a pointer cursor, SVG marks and HTML
elements that only carry a title, toggles, selects, text inputs, sliders, links, <summary> and anything else with a
click handler or cursor:pointer. It then exercises a sample of each kind with real input events (CDP
Input.dispatchMouseEvent / dispatchKeyEvent / insertText) and asserts something observable:

  record / actor / place chip   hover shows a card with text; click puts that id in the Inspector
  agent chip, glossary term     click opens the card / the glossary; Escape closes it
  toggle                        the box flips, the view changes, and a second click restores the same numbers
  everything clickable          the click has an effect (DOM, hash, Inspector, a panel, a request, a download, the
                                clipboard, a dialog); a control with cursor:pointer or a handler and no effect is dead
  marks with a hover handler    something visible changes on hover (a tooltip, a highlight) or the mark has a title
  every step                    no console error or exception, no "undefined" / "NaN" / "[object Object]" in visible text

and, once per dataset: the tab bar sets #tab= and browser back / forward restore the tab; Forensics sections set
fx= and back restores the section; the search box finds a record and Enter opens it; Escape closes every panel;
arrow keys move along the tab bar and Tab moves a visible focus; the Inspector's back button; and the Count-by
switch on every tab: ribbon and tab badges move in the direction /api/x/units_summary and /api/x/units_map give,
agent-level counts never exceed token-level ones, a trace with no merges shows the same numbers either way, and
switching back restores the first numbers.

Nothing is written to the server under test: every request that is not a GET is answered inside the page (and
counted as the control's effect), confirm() / prompt() decline, downloads and window.open are counted, not done.
Native title tooltips cannot be seen in headless Chrome; for those the title text itself is checked.

Prints one table per dataset (page x found / exercised / passed / failed / skipped) and writes
reports/integrity/interact.json. Exits 1 when any check fails. Needs Google Chrome (or CHROME=/path/to/chrome).
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

from .smoke import BUSY_JS, PKG, ROOT, TABS, Browser, Server, free_port, http

BIG_DEFAULT = "http://127.0.0.1:8010"
BLOCK_NOTE = "write blocked by the interaction test"
CLICK_KINDS = ("button", "count-by", "record-chip", "actor-chip", "place-chip", "agent-chip", "term", "row", "svg-mark",
               "toggle", "summary", "link", "pointer")
PASSIVE_KINDS = ("svg-title", "title-tip")
KIND_ORDER = CLICK_KINDS + ("select", "input", "range") + PASSIVE_KINDS + ("file-input", "disabled")

# Runs before any page script: remembers which elements got listeners, keeps every write inside the page and counts
# the side effects a click can have that leave no trace in the DOM.
INIT_JS = r"""(() => {
  if (window.__ix) return;
  const L = new WeakMap();
  const ix = window.__ix = { net: 0, writes: 0, downloads: 0, clip: 0, dialogs: 0, opens: 0, L, lastWrite: '' };
  const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, o) {
    try { if (this instanceof Element) { let s = L.get(this); if (!s) L.set(this, s = new Set()); s.add(type); } } catch (e) { /* keep going */ }
    return add.call(this, type, fn, o);
  };
  const f = window.fetch;
  window.fetch = function (input, init) {
    const m = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    ix.net++;
    if (m !== 'GET' && m !== 'HEAD') {
      ix.writes++; ix.lastWrite = m + ' ' + String((input && input.url) || input).split('?')[0];
      return Promise.resolve(new Response(JSON.stringify({ error: '__BLOCK__' }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    }
    return f.apply(this, arguments);
  };
  window.confirm = () => { ix.dialogs++; return false; };
  window.prompt = () => { ix.dialogs++; return null; };
  window.alert = () => { ix.dialogs++; };
  window.open = () => { ix.opens++; return null; };
  const cu = URL.createObjectURL;
  URL.createObjectURL = function (b) { ix.downloads++; return cu.call(URL, b); };
  try { if (navigator.clipboard) navigator.clipboard.writeText = () => { ix.clip++; return Promise.resolve(); }; } catch (e) { /* no clipboard */ }
  try { localStorage.setItem('swarm-tracer-guide-dismissed', '1'); } catch (e) { /* storage blocked */ }
})();""".replace("__BLOCK__", BLOCK_NOTE)

# Helpers shared by the page-side snippets below (installed once per document as window.__ixh).
LIB_JS = r"""(() => {
  if (window.__ixh) return true;
  const ix = window.__ix || (window.__ix = { net: 0, writes: 0, downloads: 0, clip: 0, dialogs: 0, opens: 0, L: new WeakMap() });
  const H = window.__ixh = {};
  const hash = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36) + ':' + s.length; };
  const listens = (e, types) => { const s = ix.L.get(e); return !!s && types.some((t) => s.has(t)); };
  const CLICKS = ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'dblclick'];
  const HOVERS = ['mouseenter', 'mouseover', 'mousemove', 'pointerenter', 'pointermove', 'pointerover'];
  const vis = (e) => { const r = e.getBoundingClientRect(); if (!r.width && !r.height) return false; const cs = getComputedStyle(e); return cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden]'); };
  const DATA = ['id', 'ev', 'actor', 'place', 'agent', 'term'];
  const hasData = (e) => DATA.some((k) => e.dataset && e.dataset[k] != null);
  const pointer = (e) => getComputedStyle(e).cursor === 'pointer' && !(e.parentElement && getComputedStyle(e.parentElement).cursor === 'pointer');
  H.roots = (scope) => scope === 'top' ? [document.querySelector('header.top')] : scope === 'inspector' ? [document.querySelector('section.rtop')]
    : scope === 'overlay' ? H.overlayEls() : [document.getElementById('left')];
  H.overlayEls = () => [...document.body.children].filter((e) => !['HEADER', 'MAIN', 'SCRIPT', 'STYLE', 'LINK'].includes(e.tagName) && !e.classList.contains('hovercard') && !e.hidden && vis(e));
  function kindOf(e, scope) {
    const tag = e.tagName.toLowerCase();
    if (e instanceof SVGElement) {
      if (tag === 'svg' || tag === 'title' || tag === 'defs' || e.closest('button,a,.ent')) return null;
      if (e.closest('defs')) return null;
      const own = hasData(e) || listens(e, CLICKS) || e.onclick || pointer(e);
      if (own) return 'svg-mark';
      if (listens(e, HOVERS)) return 'svg-mark';
      const t = [...e.children].find((c) => c.tagName.toLowerCase() === 'title');
      if (t && !e.parentElement.closest('[data-id],[data-ev],[data-actor],[data-place],[data-agent]')) return 'svg-title';
      return null;
    }
    if (scope === 'top' && e.closest('#tabs')) return null;
    if (tag === 'button' || e.getAttribute('role') === 'button' || (tag === 'input' && ['button', 'submit', 'reset'].includes(e.type))) {
      if (e.disabled || e.getAttribute('aria-disabled') === 'true') return 'disabled';
      return e.dataset.setunit ? 'count-by' : 'button';
    }
    if (tag === 'input') {
      if (e.type === 'hidden') return null;
      if (e.type === 'file') return 'file-input';
      if (e.disabled) return 'disabled';
      if (e.type === 'checkbox' || e.type === 'radio') return 'toggle';
      if (e.type === 'range') return 'range';
      return 'input';
    }
    if (tag === 'select') return e.disabled ? 'disabled' : 'select';
    if (tag === 'textarea') return 'input';
    if (tag === 'summary') return 'summary';
    if (tag === 'a' && e.hasAttribute('href')) return 'link';
    if (e.closest('button,a[href],summary')) return null;
    if (e.dataset.id != null || e.dataset.ev != null) return 'record-chip';
    if (e.dataset.actor != null) return 'actor-chip';
    if (e.dataset.place != null) return 'place-chip';
    if (e.dataset.agent != null) return 'agent-chip';
    if (e.dataset.term != null) return 'term';
    if (tag === 'tr' && (e.classList.contains('click') || listens(e, CLICKS) || e.onclick || pointer(e))) return 'row';
    if (tag === 'label' && e.querySelector('input,select,textarea')) return null;
    // a listener on a container that holds its own buttons is delegation, not a control
    if (listens(e, CLICKS) || e.onclick) return !pointer(e) && (e.children.length > 3 || e.querySelector('button,a[href],input,select,[data-id],[data-actor],[data-place]')) ? null : 'pointer';
    if (pointer(e) && !e.closest('label,[data-id],[data-ev],[data-actor],[data-place],[data-agent],[data-term],tr.click')) return 'pointer';
    if (e.title && e.title.trim() && !e.closest('.ent')) return 'title-tip';
    return null;
  }
  const STATE = /^(on|off|active|sel|selected|open|hover|focus|cur|current|dim|faded|hi|lit)$/;
  function sig(e, kind) {
    const cls = (e.getAttribute('class') || '').trim().split(/\s+/).filter((c) => c && !STATE.test(c)).slice(0, 2).join('.');
    const data = Object.keys(e.dataset || {}).filter((k) => !/^(i|n|idx|index)$/.test(k)).sort().join(',');
    const type = e.tagName.toLowerCase() === 'input' ? ':' + e.type : '';
    const sv = e.ownerSVGElement ? '@' + ((e.ownerSVGElement.getAttribute('class') || e.ownerSVGElement.id || 'svg').trim().split(/\s+/)[0]) : '';
    return `${kind}|${e.tagName.toLowerCase()}${type}${cls ? '.' + cls : ''}${data ? '[' + data + ']' : ''}${sv}`;
  }
  H.scan = (scope) => {
    const out = [];
    for (const root of H.roots(scope)) {
      if (!root) continue;
      for (const e of root.querySelectorAll('*')) {
        if (e.closest('.hovercard') || (scope === 'left' && e.closest('.fxnav'))) continue;      // the Forensics menu has its own check
        let k; try { k = kindOf(e, scope); } catch (err) { k = null; }
        if (!k || !vis(e)) continue;
        out.push({ e, kind: k, sig: sig(e, k) });
      }
    }
    return out;
  };
  H.discover = (scope) => { const seen = {}; return H.scan(scope).map((x) => { const n = seen[x.sig] = (seen[x.sig] || 0) + 1; return { kind: x.kind, sig: x.sig, n: n - 1 }; }); };
  const label = (e) => ((e.getAttribute('aria-label') || e.innerText || e.textContent || e.value || e.getAttribute('title') || e.getAttribute('placeholder') || '') + '').replace(/\s+/g, ' ').trim().slice(0, 60);
  function point(e) {
    const tryEl = (el) => {
      const r = el.getBoundingClientRect();
      if (!r.width && !r.height) return null;
      const c = [[.5, .5], [.25, .5], [.75, .5], [.5, .25], [.5, .75], [.08, .5], [.92, .5], [.15, .2], [.85, .8]].map(([a, b]) => [r.left + r.width * a, r.top + r.height * b]);
      if (el instanceof SVGGeometryElement) { try { const len = el.getTotalLength(), m = el.getScreenCTM(); for (const f of [.5, .3, .7, .1, .9]) { const p = el.getPointAtLength(len * f); c.push([p.x * m.a + p.y * m.c + m.e, p.x * m.b + p.y * m.d + m.f]); } } catch (err) { /* not laid out */ } }
      for (const [fx, fy] of c) {
        const x = Math.round(fx), y = Math.round(fy);      // mouse events carry whole pixels
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
        const h = document.elementFromPoint(x, y);
        if (h && (h === e || e.contains(h) || (e.tagName === 'INPUT' && e.closest('label') && e.closest('label').contains(h)))) return [x, y];
      }
      return null;
    };
    let p = tryEl(e);
    if (!p && e instanceof SVGElement) for (const c of [...e.querySelectorAll('*')].slice(0, 12)) { p = tryEl(c); if (p) break; }
    return p;
  }
  H.locate = (scope, s, n) => {
    const all = H.scan(scope).filter((x) => x.sig === s);
    const x = all[n];
    if (!x) return { miss: all.length ? 'fewer' : 'gone' };
    const e = x.e;
    ix.cur = e;
    e.scrollIntoView({ block: 'center', inline: 'center' });
    const p = point(e);
    const d = e.dataset || {};
    const svgTitle = e instanceof SVGElement ? ([...e.children].find((c) => c.tagName.toLowerCase() === 'title') || {}).textContent : null;
    const up = e instanceof SVGElement ? e.closest('[data-id],[data-ev],[data-actor],[data-place],[data-agent]') : null;
    const dd = d.id != null || d.ev != null || d.actor != null || d.place != null || d.agent != null || d.term != null ? d : (up ? up.dataset : d);
    return { p, kind: x.kind, label: label(e), tag: e.tagName.toLowerCase(), type: e.type || '',
      expect: d.noclick != null ? null : dd.term != null && e === (e.closest('[data-term]')) ? { term: dd.term } : dd.agent != null ? { agent: dd.agent } : dd.actor != null ? { actor: dd.actor }
        : dd.place != null ? { place: dd.place } : (dd.id != null || dd.ev != null) ? { record: dd.id || dd.ev } : null,
      card: !!(e.closest('[data-term],[data-actor],[data-place],[data-id],[data-ev]')) && d.nocard == null,
      title: (e.getAttribute('title') || svgTitle || e.getAttribute('aria-label') || '').trim(),
      hoverL: listens(e, HOVERS), clickL: listens(e, CLICKS) || !!e.onclick,
      checked: e.checked === true, value: e.value == null ? null : String(e.value), href: e.getAttribute && e.getAttribute('href'),
      options: e.tagName === 'SELECT' ? e.options.length : 0, external: e.tagName === 'A' && /^(https?:|mailto:)/.test(e.getAttribute('href') || '') && e.host !== location.host,
      download: e.tagName === 'A' && e.hasAttribute('download'), noclick: d.noclick != null, cursor: getComputedStyle(e).cursor };
  };
  H.cur = () => { const e = ix.cur; return !e ? null : { connected: e.isConnected, checked: e.checked === true, value: e.value == null ? null : String(e.value), cls: e.getAttribute('class') || '', open: e.parentElement && e.parentElement.open === true, pressed: e.getAttribute('aria-pressed'), expanded: e.getAttribute('aria-expanded') }; };
  const nums = (t) => (t.match(/\d[\d,]*(\.\d+)?/g) || []).join(' ');
  H.snap = () => {
    const left = document.getElementById('left'), trace = document.getElementById('trace'), head = document.querySelector('header.top');
    const forms = [...document.querySelectorAll('input,select,textarea')].filter((e) => e !== ix.cur && e.type !== 'password').map((e) => (e.type === 'checkbox' || e.type === 'radio' ? (e.checked ? 1 : 0) : e.value)).join('\u0001');
    const scrolls = [...document.querySelectorAll('#left, #left *, #trace')].filter((e) => e.scrollTop || e.scrollLeft).map((e) => e.scrollTop + ',' + e.scrollLeft).join(';');
    return {
      hash: location.hash, tab: (typeof S !== 'undefined' && S.tab) || '', unit: (typeof S !== 'undefined' && S.unit) || '',
      left: hash(left ? left.innerHTML : ''), trace: hash(trace ? trace.innerHTML : ''), traceid: (document.getElementById('traceid') || {}).innerText || '',
      ai: hash((document.querySelector('section.rbot') || { innerHTML: '' }).innerHTML), head: hash(head ? head.innerHTML : ''), headHidden: [...(head ? head.querySelectorAll('[hidden]') : [])].map((e) => e.id).join(','),
      overlays: H.overlayEls().map((e) => (e.id || e.className) + '=' + hash(e.innerHTML)).join('|'), bodyClass: document.body.className,
      forms: hash(forms), scrolls, net: ix.net, writes: ix.writes, downloads: ix.downloads, clip: ix.clip, dialogs: ix.dialogs, opens: ix.opens,
      nums: hash(nums(left ? left.innerText : '')), fx: (document.querySelector('.fxnav button.on') || { dataset: {} }).dataset.fx || '',
    };
  };
  H.nums = (sel) => { const e = document.querySelector(sel); return e ? nums(e.innerText) : ''; };
  // what a hover shows: the shared hover card, or anything else that became visible
  H.tips = () => {
    const hc = document.querySelector('.hovercard');
    return { card: hc && !hc.hidden ? (hc.innerText || '').trim().slice(0, 300) : null };
  };
  const BAD = /\bundefined\b|\bNaN\b|\[object Object\]/;
  H.badText = () => {
    const out = [];
    const roots = [document.querySelector('header.top'), document.getElementById('left'), document.querySelector('section.rtop'), ...document.querySelectorAll('.hovercard'), ...H.overlayEls()].filter(Boolean);
    for (const root of roots) {
      if (root.hidden) continue;
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const t = n.nodeValue;
        if (!BAD.test(t)) continue;
        const p = n.parentElement;
        if (!p || p.closest('pre,code,textarea,script,style,.raw,.code,.src,.codeview,mark') || !vis(p)) continue;
        out.push(((root.id || root.className || root.tagName) + ': ' + t.replace(/\s+/g, ' ').trim()).slice(0, 160));
        if (out.length >= 4) return out;
      }
      for (const e of root.querySelectorAll('[title]')) { if (BAD.test(e.getAttribute('title')) && !e.closest('pre,code,.ent.place')) { out.push(('title: ' + e.getAttribute('title')).slice(0, 160)); if (out.length >= 4) return out; } }
    }
    return out;
  };
  return true;
})()"""


def _key(br, key, code=None, vk=0, text=None, modifiers=0):
    # no nativeVirtualKeyCode: on macOS a native code makes Chrome hold later mouse events for five seconds
    p = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk, "modifiers": modifiers}
    down = dict(p, type="keyDown" if text else "rawKeyDown")
    if text:
        down["text"] = text
    br.call("Input.dispatchKeyEvent", down)
    br.call("Input.dispatchKeyEvent", dict(p, type="keyUp"))


KEYS = {"Escape": 27, "Enter": 13, "Tab": 9, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40, "Home": 36, "End": 35}


def diff_snap(a, b):
    """Names of the snapshot fields that differ: what a click changed."""
    return sorted(k for k in a if a.get(k) != b.get(k))


def sample_plan(items, per_sig=1, per_kind=None, max_sigs=None):
    """Pick what to exercise from a discovery list [{kind, sig, n}]: up to per_sig elements of each signature (the
    first, the last, then the middle), at most max_sigs signatures and per_kind elements of each kind."""
    by_sig = {}
    for it in items:
        by_sig.setdefault((it["kind"], it["sig"]), []).append(it["n"])
    plan, used, sigs = [], {}, {}
    for (kind, sig), ns in by_sig.items():
        if kind in ("file-input", "disabled"):
            continue
        if max_sigs is not None and sigs.get(kind, 0) >= max_sigs:
            continue
        sigs[kind] = sigs.get(kind, 0) + 1
        order = []
        for n in (ns[0], ns[-1], ns[len(ns) // 2]) + tuple(ns):
            if n not in order:
                order.append(n)
        for n in order[:per_sig]:
            if per_kind is not None and used.get(kind, 0) >= per_kind:
                break
            used[kind] = used.get(kind, 0) + 1
            plan.append({"kind": kind, "sig": sig, "n": n})
    return plan


class Page:
    """One tab, one Forensics section, the top bar or the Inspector: where to go and where to look."""

    def __init__(self, name, hash_, scope="left"):
        self.name, self.hash, self.scope = name, hash_, scope


class Runner:
    def __init__(self, br, base, label, quick=False, verbose=False, slow=1.0):
        self.br, self.base, self.label, self.quick, self.verbose = br, base.rstrip("/"), label, quick, verbose
        self.slow = slow                  # the release answers slower than the demo swarm
        self.rows = []                    # one per page
        self.checks = []                  # scripted checks: {name, ok, note}
        self.ignored = 0
        self.t0 = time.time()

    # ---- plumbing
    def js(self, expr, timeout=60):
        return self.br.eval(expr, timeout=timeout)

    def lib(self):
        self.js(LIB_JS)

    def settle(self, quiet=0.18, timeout=None):
        self.br.settle(quiet=quiet, timeout=timeout or 20 * self.slow, busy_expr=BUSY_JS)

    def goto(self, hash_, hard=True):
        if hard:
            self.br.navigate("about:blank")
            # Chrome does not always report the end of a request the navigation killed; left in the list it would make
            # every later settle() wait out its whole timeout
            self.br.pump(0.05)
            self.br.inflight.clear()
            self.br.navigate(f"{self.base}/#{hash_}")
        else:
            self.js(f"location.hash = {json.dumps(hash_)}")
        self.br.wait_until("typeof S !== 'undefined' && !!S.summary && !!window.__ix", timeout=90 * self.slow)
        self.settle(quiet=0.5, timeout=60 * self.slow)
        self.lib()

    def move(self, x, y):
        self.br.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def click(self, x, y):
        self.br.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
        self.br.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    def key(self, name):
        _key(self.br, name, vk=KEYS.get(name, 0), text="\r" if name == "Enter" else None)

    def locate(self, scope, item):
        """Scroll the element into view, let the scroll events pass (the app drops hover cards on scroll), then find
        the point to hit."""
        expr = f"__ixh.locate({json.dumps(scope)}, {json.dumps(item['sig'])}, {item['n']})"
        loc = self.js(expr)
        if loc.get("miss"):
            return loc
        self.br.eval("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 20))))", await_promise=True)
        return self.js(expr)

    def away(self):
        self.move(3, 3)

    def errors(self):
        """Console errors and exceptions since the last mark, without the ones the blocked writes cause."""
        self.br.pump(0.05)
        out = []
        for kind, text in self.br.events:
            if BLOCK_NOTE in text or kind == "netfail":
                self.ignored += 1
                continue
            out.append(f"{kind}: {text}"[:200])
        return out

    def snap(self):
        return self.js("__ixh.snap()")

    def wait_change(self, before, timeout=1.5, ignore=()):
        end = time.time() + timeout
        while time.time() < end:
            now = self.snap()
            d = [k for k in diff_snap(before, now) if k not in ignore]
            if d:
                return now, d
            self.br.pump(0.08)
        return self.snap(), []

    # ---- one element
    def exercise(self, page, item):
        """Hover and use one element; returns {status: pass|fail|skip, note, ...}."""
        br, scope = self.br, page.scope
        res = dict(item, status="pass", note="", label="")
        loc = self.locate(scope, item)
        if loc.get("miss"):
            return dict(res, status="skip", note="no longer on the page")
        res["label"] = loc["label"]
        kind = loc["kind"]
        fails, notes = [], []
        if kind in PASSIVE_KINDS:
            # a native tooltip never renders in headless Chrome: check the text it would show
            if not loc["title"]:
                fails.append("empty title")
            if loc["p"]:
                self.move(*loc["p"])
                br.pump(0.05)
            bad = self.js("__ixh.badText()")
            if bad:
                fails.append("bad text: " + "; ".join(bad))
            self.away()
            return dict(res, status="fail" if fails else "pass", note="; ".join(fails) or "title: " + loc["title"][:50])
        if not loc["p"]:
            return dict(res, status="skip", note="not reachable with the pointer (covered or outside the window)")
        if kind == "toggle" and loc["type"] == "radio" and loc["checked"]:
            # the selected radio does nothing by design: use the next one of its kind that is not selected
            for n in range(item["n"] + 1, item["n"] + 6):
                nxt = self.locate(scope, dict(item, n=n))
                if nxt.get("miss"):
                    break
                if not nxt["checked"] and nxt.get("p"):
                    loc, item = nxt, dict(item, n=n)
                    break
            else:
                nxt = None
            if loc["checked"]:
                return dict(res, status="skip", note="the only radio of its kind, already selected")
        x, y = loc["p"]
        before = self.snap()
        br.mark()
        # hover
        self.move(x - 2, y - 1)
        self.move(x, y)
        if loc["card"]:
            ok = br.wait_until("(() => { const t = __ixh.tips().card; return !!t && t !== '…'; })()", timeout=4 * self.slow, poll=0.06)
            tip = self.js("__ixh.tips().card")
            if not ok or not tip:      # a mark that was still moving (a graph settling): once more, from outside
                self.away()
                br.pump(0.3)
                again = self.locate(scope, item)
                if again.get("p"):
                    x, y = again["p"]
                    self.move(x - 2, y - 1)
                    self.move(x, y)
                    ok = br.wait_until("(() => { const t = __ixh.tips().card; return !!t && t !== '…'; })()", timeout=4 * self.slow, poll=0.06)
                    tip = self.js("__ixh.tips().card")
                    if ok and tip:
                        notes.append("second hover")
            if not ok or not tip:
                fails.append("no hover card" if not tip else "hover card never filled in")
            else:
                notes.append("card")
        elif loc["hoverL"]:
            _, d = self.wait_change(before, timeout=0.9, ignore=("net",))
            if not d and not loc["title"]:
                fails.append("hover handler shows nothing")
            elif d:
                notes.append("hover: " + ",".join(d))
        else:
            br.pump(0.12)
        bad = self.js("__ixh.badText()")
        if bad:
            fails.append("bad text on hover: " + "; ".join(bad))
        # use it
        if kind == "link" and (loc["external"] or loc["download"]):
            if not (loc["href"] or "").strip():
                fails.append("empty href")
            self.away()
            return dict(res, status="fail" if fails else "pass", note="; ".join(fails) or "external link, href checked, not followed")
        after = None
        if kind == "select":
            if loc["options"] < 2:
                self.away()
                return dict(res, status="skip", note="one option only")
            self.js("(() => { const e = __ix.cur; e.focus(); e.selectedIndex = (e.selectedIndex + 1) % e.options.length; e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); })()")
            notes.append("change event (not a real pointer pick)")
        elif kind == "input":
            self.click(x, y)
            br.pump(0.05)
            if not self.js("document.activeElement === __ix.cur"):
                fails.append("click does not focus it")
                self.js("__ix.cur.focus()")
            text = "1" if loc["type"] == "number" else "a"
            br.call("Input.insertText", {"text": text})
            br.pump(0.45)
            self.settle()
            after, d = self.wait_change(before, timeout=0.3, ignore=("scrolls", "net"))
            if not d:
                self.key("Enter")
        elif kind == "range":
            self.click(x, y)
            self.key("ArrowRight")
        else:
            self.click(x, y)
        br.pump(0.08)
        self.settle()
        self.away()
        # "net" is not evidence: the app re-checks /api/state whenever the window gets focus
        after, d = self.wait_change(before, timeout=1.2 if not self.quick else 0.7, ignore=("net",))
        cur = self.js("__ixh.cur()") or {}
        own = (cur.get("checked") != loc["checked"]) or (cur.get("value") != loc["value"]) or not cur.get("connected", True)
        exp = loc.get("expect") if kind != "input" else None
        if loc.get("noclick"):
            # the chip for the item already open: no click by design, so it must not look clickable
            if loc["cursor"] == "pointer":
                fails.append("marked not clickable, but shows a pointer cursor")
            self.key("Escape")
            br.mark()
            return dict(res, status="fail" if fails else "pass", note="; ".join(fails) or "not clickable by design (the item already open); hover only")
        if exp and "record" in exp:
            if not br.wait_until(f"(document.getElementById('traceid').innerText || '').includes({json.dumps(exp['record'])})", timeout=8 * self.slow):
                fails.append(f"Inspector does not show {exp['record']} (shows {after.get('traceid', '')[:40]!r})")
            else:
                notes.append("Inspector: record")
        elif exp and ("actor" in exp or "place" in exp):
            word = "actor" if "actor" in exp else "place"
            if not br.wait_until(f"/^\\s*(← back\\s*)?{word}\\b/i.test(document.getElementById('traceid').innerText || '')", timeout=(1.5 if d else 8) * self.slow):
                if d:
                    notes.append("handled by the view: " + ",".join(d))
                else:
                    fails.append(f"Inspector does not show the {word}")
            else:
                notes.append("Inspector: " + word)
        elif exp and "agent" in exp:
            if not self.js("(() => { const c = document.getElementById('agentcard'); return !!c && !c.hidden && c.innerText.trim().length > 20; })()"):
                if d:
                    notes.append("handled by the view: " + ",".join(d))
                else:
                    fails.append("agent card did not open")
            else:
                self.key("Escape")
                if not self.js("document.getElementById('agentcard').hidden"):
                    fails.append("Escape does not close the agent card")
                notes.append("agent card, Escape closes")
        elif exp and "term" in exp:
            if not self.js("(() => { const g = document.getElementById('glossary'); return !!g && !g.hidden; })()"):
                fails.append("glossary did not open")
            else:
                self.key("Escape")
                if not self.js("document.getElementById('glossary').hidden"):
                    fails.append("Escape does not close the glossary")
                notes.append("glossary, Escape closes")
        elif kind == "toggle":
            if cur.get("connected", True) and cur.get("checked") == loc["checked"]:
                fails.append("the box did not flip")
            if not [k for k in d if k not in ("scrolls",)]:
                notes.append("flips; nothing else on the page changes (a mode switch)")
            elif loc["type"] == "checkbox" and "tab" not in d and "hash" not in d:
                # and back: the same numbers as before
                l2 = self.locate(scope, item)
                if l2.get("p"):
                    self.click(*l2["p"])
                    br.pump(0.08)
                    self.settle()
                    self.away()
                    back = self.snap()
                    if back["nums"] != before["nums"]:
                        end = time.time() + 1.5
                        while time.time() < end and back["nums"] != before["nums"]:
                            br.pump(0.1)
                            back = self.snap()
                    if back["nums"] != before["nums"]:
                        fails.append("toggling back does not restore the numbers")
                    else:
                        notes.append("round trip ok" + (" (numbers changed in between)" if after["nums"] != before["nums"] else ""))
        else:
            real = [k for k in d if k != "scrolls" or kind in ("button", "pointer", "svg-mark", "row", "link")]
            if not real and not own:
                fails.append("dead: no effect")
            else:
                if after["writes"] != before["writes"]:
                    notes.append("write kept in the page (" + (self.js("__ix.lastWrite") or "") + ")")
                if after["dialogs"] != before["dialogs"]:
                    notes.append("asked to confirm (declined)")
                if after["downloads"] != before["downloads"]:
                    notes.append("download")
                if after["clip"] != before["clip"]:
                    notes.append("clipboard")
                if not notes:
                    notes.append(",".join(real or ["own state"]))
        bad = self.js("__ixh.badText()")
        if bad:
            fails.append("bad text: " + "; ".join(bad))
        errs = self.errors()
        if errs:
            fails.append("console: " + " | ".join(errs[:3]))
        res["changed"] = d
        # clean up: close what opened, clear what was typed
        if kind == "input":
            self.js("(() => { const e = __ix.cur; if (e && e.isConnected && e.value) { e.value = ''; e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); } })()")
            br.pump(0.35)
            self.settle()
        self.key("Escape")
        self.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        br.mark()
        return dict(res, status="fail" if fails else "pass", note="; ".join(fails or notes)[:400])

    def reset(self, page, start):
        """Back to the page under test after a click led away: a hard reload when a panel is still open or the
        section changed, otherwise the app's own tab switch (a clean-up step, so not a real click)."""
        now = self.snap()
        if now["fx"] != start["fx"] or now["unit"] != start["unit"] or bool(now["overlays"]) != bool(start["overlays"]) \
                or now["headHidden"] != start["headHidden"] or now["bodyClass"] != start["bodyClass"]:
            self.open_page(page)
        elif now["tab"] != start["tab"]:
            self.js(f"goTab({json.dumps(start['tab'])})")
            self.br.pump(0.05)
            self.settle(quiet=0.3)
            self.br.mark()

    def open_page(self, page):
        self.goto(page.hash)
        if page.scope == "inspector":
            self.js(f"selectEvent({json.dumps(self.record_id)})")
            self.br.wait_until("!!document.querySelector('#trace .dhead, #trace .dsec')", timeout=20 * self.slow)
            self.settle()
        elif page.name == "live drawer":
            self.js("document.getElementById('livebtn').click()")
            self.settle()
        elif page.name == "case file":
            self.js("document.getElementById('casebtn').click()")
            self.settle()
        elif page.name == "glossary":
            self.js("document.getElementById('glossbtn').click()")
            self.settle()
        elif page.name == "load panel":
            self.js("document.getElementById('loadbtn').click()")
            self.settle()
        self.br.mark()

    def run_page(self, page, per_sig, per_kind, max_sigs):
        t0 = time.time()
        row = {"page": page.name, "hash": page.hash, "found": {}, "exercised": {}, "passed": {}, "failed": [], "skipped": [], "load": []}
        self.br.mark()
        try:
            self.open_page(page)
        except Exception as e:      # a page that never loads is one failure, not a crash
            row["failed"].append({"kind": "page", "sig": "load", "note": f"{type(e).__name__}: {e}"[:300], "label": ""})
            self.rows.append(row)
            return row
        errs = self.errors()
        bad = self.js("__ixh.badText()")
        if errs or bad:
            row["load"] = errs + ["bad text: " + b for b in bad]
            row["failed"].append({"kind": "page", "sig": "load", "note": "; ".join(row["load"])[:400], "label": ""})
        items = self.js(f"__ixh.discover({json.dumps(page.scope)})")
        for it in items:
            row["found"][it["kind"]] = row["found"].get(it["kind"], 0) + 1
        plan = sample_plan(items, per_sig=per_sig, per_kind=per_kind, max_sigs=max_sigs)
        counts = {}
        for it in items:
            counts[it["sig"]] = counts.get(it["sig"], 0) + 1
        start = self.snap()
        for it in plan:
            t1 = time.time()
            try:
                r = self.exercise(page, it)
                if r["status"] == "skip" and r["note"].startswith("no longer"):
                    self.open_page(page)
                    r = self.exercise(page, it)
            except Exception as e:
                r = dict(it, status="fail", note=f"{type(e).__name__}: {e}"[:300], label="")
            if r["status"] == "fail" and r["note"].startswith("dead") and counts.get(it["sig"], 0) > 1:
                # the first of its kind may be the one already selected (the row whose detail is open): try its neighbour
                try:
                    self.reset(page, start)
                    n2 = it["n"] + 1 if it["n"] + 1 < counts[it["sig"]] else it["n"] - 1
                    r2 = self.exercise(page, dict(it, n=n2))
                    if r2["status"] == "pass":
                        r = dict(r2, n=it["n"], note="no change on this one (already selected); its neighbour: " + r2["note"])
                except Exception:
                    pass
            k = it["kind"]
            r["s"] = round(time.time() - t1, 1)
            if r["status"] == "skip":
                row["skipped"].append({"kind": k, "sig": it["sig"], "note": r["note"], "label": r.get("label", "")})
            else:
                row["exercised"][k] = row["exercised"].get(k, 0) + 1
                if r["status"] == "pass":
                    row["passed"][k] = row["passed"].get(k, 0) + 1
                else:
                    row["failed"].append({"kind": k, "sig": it["sig"], "n": it["n"], "note": r["note"], "label": r.get("label", "")})
            if self.verbose:
                sys.stdout.write(f"    {r['status']:4} {page.name:24} {it['sig'][:60]:60} #{it['n']:<3} {r.get('label', '')[:28]!r:30} {r['note'][:110]} ({r['s']} s)\n")
                sys.stdout.flush()
            try:
                self.reset(page, start)
            except Exception:
                self.open_page(page)
        row["seconds"] = round(time.time() - t0, 1)
        self.rows.append(row)
        return row

    # ---- scripted checks, once per dataset
    def check(self, name, ok, note=""):
        self.checks.append({"name": name, "ok": bool(ok), "note": str(note)[:400]})
        if self.verbose or not ok:
            sys.stdout.write(f"    {'pass' if ok else 'FAIL'} [{self.label}] {name}: {str(note)[:200]}\n")
            sys.stdout.flush()

    def click_sel(self, selector):
        """A real click on the first visible element matching the selector; False when there is none to hit."""
        p = self.js(f"""(() => {{ const e = [...document.querySelectorAll({json.dumps(selector)})].find((x) => x.getBoundingClientRect().width > 0 && !x.closest('[hidden]')); if (!e) return null;
            e.scrollIntoView({{ block: 'nearest', inline: 'nearest' }}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
        if not p:
            return False
        self.move(*p)
        self.click(*p)
        self.br.pump(0.08)
        return True

    def tab_state(self):
        return self.js("({ tab: S.tab, on: (document.querySelector('#tabs button.on') || { dataset: {} }).dataset.tab, hash: location.hash, fx: (document.querySelector('.fxnav button.on') || { dataset: {} }).dataset.fx || '' })")

    def history_checks(self):
        br = self.br
        self.goto("tab=overview")
        br.mark()
        self.click_sel('#tabs button[data-tab="network"]')
        self.settle()
        s1 = self.tab_state()
        self.check("tab click sets #tab=", s1["tab"] == "network" and "tab=network" in s1["hash"], f"S.tab={s1['tab']} hash={s1['hash']!r}")
        self.click_sel('#tabs button[data-tab="channels"]')
        self.settle()
        self.js("history.back()")
        br.pump(0.3)
        self.settle()
        s2 = self.tab_state()
        self.check("browser back restores the previous tab", s2["tab"] == "network" and s2["on"] == "network", f"after back: S.tab={s2['tab']} selected={s2['on']} hash={s2['hash']!r}")
        self.js("history.forward()")
        br.pump(0.3)
        self.settle()
        s3 = self.tab_state()
        self.check("browser forward goes on again", s3["tab"] == "channels" and s3["on"] == "channels", f"after forward: S.tab={s3['tab']} selected={s3['on']} hash={s3['hash']!r}")
        # Forensics: the section menu
        self.goto("tab=forensics")
        ids = self.js("(window.FX_SECTIONS || []).map((x) => x.id)") or []
        if len(ids) >= 3:
            a, b = ids[1], ids[2]
            self.click_sel(f'.fxnav button[data-fx="{a}"]')
            self.settle()
            sa = self.tab_state()
            self.check("Forensics section click sets fx=", sa["fx"] == a and f"fx={a}" in sa["hash"], f"section={sa['fx']} hash={sa['hash']!r}")
            self.click_sel(f'.fxnav button[data-fx="{b}"]')
            self.settle()
            self.js("history.back()")
            br.pump(0.3)
            self.settle()
            sb = self.tab_state()
            self.check("browser back restores the previous Forensics section", sb["tab"] == "forensics" and sb["fx"] == a, f"wanted {a}; section={sb['fx']} tab={sb['tab']} hash={sb['hash']!r}")
            self.click_sel('#tabs button[data-tab="overview"]')
            self.settle()
            self.click_sel('#tabs button[data-tab="forensics"]')
            self.settle()
            sc = self.tab_state()
            self.check("leaving Forensics and coming back keeps the section", sc["fx"] == a, f"wanted {a}; section={sc['fx']}")
            # every section of the menu: a real click shows that section's heading
            wrong = []
            for i in (ids[:6] if self.quick else ids):
                br.mark()
                self.click_sel(f'.fxnav button[data-fx="{i}"]')
                br.wait_until(f"(document.querySelector('.fxnav button.on') || {{ dataset: {{}} }}).dataset.fx === {json.dumps(i)}", timeout=5)
                self.settle()
                st = self.js("({ on: (document.querySelector('.fxnav button.on') || { dataset: {} }).dataset.fx, btn: (document.querySelector('.fxnav button.on') || {}).innerText || '', h: (document.querySelector('#fxbody h2') || {}).innerText || '', hash: location.hash, warn: [...document.querySelectorAll('#fxsec > .warn')].map((e) => e.innerText).join(' ') })")
                errs = [e for e in self.errors() if "http: 4" not in e or "/api/x/" not in e]
                if st["on"] != i or st["btn"].strip() != st["h"].strip() or f"fx={i}" not in st["hash"] or errs:
                    wrong.append(f"{i}: selected {st['on']}, heading {st['h']!r}, hash {st['hash']!r} {' | '.join(errs[:1])}")
            self.check(f"Forensics menu: each of {len(ids[:6] if self.quick else ids)} sections opens with its heading and fx=", not wrong, "; ".join(wrong[:4]))
        # a record opened from a deep link survives a reload of that link
        self.goto(f"tab=events&rec={urllib.parse.quote(self.record_id)}")
        self.check("deep link #tab=events&rec= opens the record", br.wait_until(f"(document.getElementById('traceid').innerText || '').includes({json.dumps(self.record_id)})", timeout=15 * self.slow), self.record_id)
        errs = self.errors()
        self.check("no console errors during history navigation", not errs, " | ".join(errs[:3]))

    def keyboard_checks(self):
        br = self.br
        self.goto("tab=overview")
        br.mark()
        # every panel: open with a real click, close with Escape
        for btn, panel in (("loadbtn", "loadpanel"), ("glossbtn", "glossary"), ("aiset", "aisettings")):
            opened = self.click_sel("#" + btn) and br.wait_until(f"(() => {{ const e = document.getElementById('{panel}'); return !!e && !e.hidden; }})()", timeout=3)
            self.key("Escape")
            closed = self.js(f"(() => {{ const e = document.getElementById('{panel}'); return !e || e.hidden; }})()")
            self.check(f"#{btn} opens #{panel}; Escape closes it", opened and closed, f"opened={bool(opened)} closed={bool(closed)}")
        for btn, name in (("livebtn", "Live drawer"), ("casebtn", "Case file"), ("guidebtn", "Start here guide")):
            before = self.js("__ixh.snap()")
            self.click_sel("#" + btn)
            self.settle()
            mid, d = self.wait_change(before, timeout=2, ignore=("net", "scrolls"))
            self.key("Escape")
            br.pump(0.25)
            end = self.snap()
            still = [k for k in diff_snap(before, end) if k in ("overlays", "bodyClass", "headHidden", "left")]
            self.check(f"#{btn} opens the {name}", bool(d), ",".join(d) or "no change")
            self.check(f"Escape closes the {name}", bool(d) and not still, "still different: " + ",".join(still) if still else "closed")
            if still:
                self.goto("tab=overview")
        # the search box
        self.goto("tab=overview")
        self.click_sel("#omni")
        focused = self.js("document.activeElement && document.activeElement.id === 'omni'")
        br.call("Input.insertText", {"text": self.record_id})
        shown = br.wait_until("!document.getElementById('omniout').hidden && document.querySelectorAll('#omniout .oi').length > 0", timeout=10 * self.slow)
        n = self.js("document.querySelectorAll('#omniout .oi[data-id]').length")
        self.check("search box lists the record typed", focused and shown and n >= 1, f"focused={focused} results shown={shown} record rows={n}")
        self.key("Escape")
        self.check("Escape closes the search results", self.js("document.getElementById('omniout').hidden"), "")
        self.js("(() => { const b = document.getElementById('omni'); b.value = ''; })()")
        self.click_sel("#omni")
        br.call("Input.insertText", {"text": self.record_id})
        br.wait_until("!document.getElementById('omniout').hidden && document.querySelectorAll('#omniout .oi').length > 0", timeout=10 * self.slow)
        self.key("Enter")
        ok = br.wait_until(f"(document.getElementById('traceid').innerText || '').includes({json.dumps(self.record_id)})", timeout=10 * self.slow)
        self.check("Enter in the search box opens the first result in the Inspector", ok, self.js("document.getElementById('traceid').innerText")[:60])
        self.js("document.getElementById('omni').value = ''; document.activeElement.blur()")
        # Inspector: a second item, then its back button
        if self.actor_id:
            self.js(f"inspectActor({json.dumps(self.actor_id)})")
            br.wait_until("/actor/.test(document.getElementById('traceid').innerText)", timeout=10 * self.slow)
            self.settle()
            has = self.click_sel("#insBack")
            ok = has and br.wait_until(f"(document.getElementById('traceid').innerText || '').includes({json.dumps(self.record_id)})", timeout=10 * self.slow)
            self.check("Inspector ← back returns to the previous item", ok, self.js("document.getElementById('traceid').innerText")[:60])
        # the tab bar from the keyboard
        self.goto("tab=overview")
        self.js("document.querySelector('#tabs button.on').focus()")
        self.key("ArrowRight")
        self.settle()
        s = self.tab_state()
        self.check("ArrowRight on the tab bar moves to the next tab", s["tab"] == "network" and self.js("document.activeElement.dataset.tab") == "network", f"S.tab={s['tab']}")
        self.key("ArrowLeft")
        self.settle()
        self.check("ArrowLeft moves back", self.tab_state()["tab"] == "overview", self.tab_state()["tab"])
        # Tab moves a visible focus through the view
        seen, rings = [], 0
        self.js("document.querySelector('#tabs button.on').focus()")
        for _ in range(8):
            self.key("Tab")
            br.pump(0.03)
            f = self.js("""(() => { const e = document.activeElement; if (!e || e === document.body) return null; const cs = getComputedStyle(e);
                __ix.ids = __ix.ids || new WeakMap(); if (!__ix.ids.has(e)) __ix.ids.set(e, (__ix.nid = (__ix.nid || 0) + 1));
                return { d: e.tagName + '#' + e.id + '.' + (e.getAttribute('class') || '') + '@' + __ix.ids.get(e), ring: (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none' }; })()""")
            if f:
                seen.append(f["d"])
                rings += 1 if f["ring"] else 0
        self.check("Tab moves focus through the view", len(set(seen)) >= 4, f"{len(set(seen))} different stops in 8 presses")
        self.check("focused controls show a focus ring", seen and rings == len(seen), f"{rings}/{len(seen)} stops with an outline or shadow")
        errs = self.errors()
        self.check("no console errors during keyboard checks", not errs, " | ".join(errs[:3]))

    def unit_checks(self, tabs):
        """The Count-by switch on every tab, against /api/x/units_map and /api/x/units_summary."""
        br = self.br
        code, um, _ = http(self.base, "/api/x/units_map")
        code2, us, _ = http(self.base, "/api/x/units_summary?unit=agent")
        if code != 200 or code2 != 200 or not isinstance(um, dict) or not isinstance(us, dict):
            self.check("Count-by: /api/x/units_map and units_summary answer", False, f"HTTP {code} / {code2}")
            return
        merges = not um.get("no_merges")
        sign = lambda a, b: (a > b) - (a < b)      # noqa: E731
        want = {"units": sign(us["agents"], us["tokens"]), "messages": sign(us["messages"], um["messages"]["token"]), "pairs": sign(us["pairs"], um["pairs"]["token"])}
        self.check("Count-by: units_summary agrees with units_map", us["agents"] == um["agents"] and us["tokens"] == um["tokens"] and us["messages"] == um["messages"]["agent"] and us["pairs"] == um["pairs"]["agent"],
                   f"summary {us['agents']}/{us['tokens']} agents/tokens, {us['messages']} messages, {us['pairs']} pairs; map {um['agents']}/{um['tokens']}, {um['messages']}, {um['pairs']}")
        read = r"""(() => { const rb = [...document.querySelectorAll('#ribbon .rb')].map((e) => ({ n: +(e.querySelector('b').innerText.replace(/[^\d.]/g, '')), t: e.innerText.replace(/\s+/g, ' ') }));
            const txt = document.getElementById('left').innerText;
            const grab = (re) => [...txt.matchAll(re)].map((m) => +m[1].replace(/,/g, ''));
            return { unit: S.unit, ribbon: rb, badge: (document.querySelector('#tabs button[data-tab="network"] .cnt') || {}).innerText || '',
              agents: grab(/(\d[\d,]*) estimated agents?\b/g), actors: grab(/(\d[\d,]*) (?:named actors?|tokens?)\b/g), nums: __ixh.nums('#left'), len: txt.length,
              messages: grab(/(\d[\d,]*) (?:[a-z-]+ ){0,2}messages?\b/g), pairs: grab(/(\d[\d,]*) (?:[a-z-]+ ){0,2}pairs?\b/g),
              est: document.querySelectorAll('#left .est').length, pressed: (document.querySelector('[data-setunit][aria-pressed="true"]') || { dataset: {} }).dataset.setunit }; })()"""
        self.goto("tab=overview")
        if self.js("S.unit") != "agent":
            self.click_sel('[data-setunit="agent"]')
            self.settle()
        for tab in tabs:
            name = tab.name
            self.goto(tab.hash)
            br.mark()
            a = self.js(read)
            ok_click = self.click_sel('[data-setunit="token"]')
            self.settle(quiet=0.4)
            t = self.js(read)
            self.click_sel('[data-setunit="agent"]')
            self.settle(quiet=0.4)
            a2 = self.js(read)
            if a2["nums"] != a["nums"]:      # a late request may still be painting
                br.pump(0.8)
                self.settle(quiet=0.5)
                a2 = self.js(read)
            probs = []
            if not ok_click or t["unit"] != "token" or t["pressed"] != "token" or a2["unit"] != "agent":
                probs.append(f"the switch did not take (unit {t['unit']}, pressed {t['pressed']})")
            ra, rt = a["ribbon"], t["ribbon"]
            if len(ra) >= 5 and len(rt) >= 5:
                if ra[2]["n"] != um["agents"]:
                    probs.append(f"ribbon shows {ra[2]['n']} estimated agents, API {um['agents']}")
                if ra[4]["n"] != um["messages"]["agent"]:
                    probs.append(f"ribbon shows {ra[4]['n']} messages between agents, API {um['messages']['agent']}")
                if sign(ra[2]["n"], rt[2]["n"]) != want["units"]:
                    probs.append(f"ribbon agents {ra[2]['n']} vs tokens {rt[2]['n']}: API says {us['agents']} vs {us['tokens']}")
                if sign(ra[4]["n"], rt[4]["n"]) != want["messages"]:
                    probs.append(f"ribbon messages {ra[4]['n']} (agent) vs {rt[4]['n']} (token): API says {us['messages']} vs {um['messages']['token']}")
            else:
                probs.append("ribbon not drawn")
            num = lambda s: int("".join(c for c in s if c.isdigit()) or 0)      # noqa: E731
            if a["badge"] and t["badge"] and sign(num(a["badge"]), num(t["badge"])) != want["pairs"]:
                probs.append(f"pairs badge {a['badge']} (agent) vs {t['badge']} (token): API says {us['pairs']} vs {um['pairs']['token']}")
            if a["agents"] and t["actors"] and max(a["agents"]) > max(t["actors"]) and max(a["agents"]) > um["tokens"]:
                probs.append(f"by agent the view counts up to {max(a['agents'])} estimated agents, more than the {um['tokens']} tokens")
            if a["agents"] and max(a["agents"]) > um["agents"]:
                probs.append(f"view says {max(a['agents'])} estimated agents, API has {um['agents']} in all")
            for noun in ("messages", "pairs"):
                # the lead count of messages and of pairs: the same with no merges, never larger by agent
                if not a[noun] or not t[noun]:
                    continue
                if not merges and a[noun][0] != t[noun][0]:
                    probs.append(f"no tokens are merged, yet the view leads with {a[noun][0]} {noun} by agent and {t[noun][0]} by token")
                if merges and a[noun][0] > t[noun][0] and want[noun] <= 0:
                    probs.append(f"the view leads with {a[noun][0]} {noun} by agent and {t[noun][0]} by token; the API says {us[noun]} and {um[noun]['token']}")
            if not merges and sorted(a["agents"]) != sorted(t["actors"]) and a["agents"] and t["actors"] and max(a["agents"]) != max(t["actors"]):
                probs.append(f"no tokens are merged, yet the largest count is {max(a['agents'])} estimated agents and {max(t['actors'])} named actors")
            if a2["nums"] != a["nums"]:
                da, dt = a["nums"].split(), a2["nums"].split()
                i = next((i for i, (p, q) in enumerate(zip(da, dt)) if p != q), min(len(da), len(dt)))
                probs.append(f"switching back to agents does not restore the numbers (first difference: {' '.join(da[i:i + 3])} then {' '.join(dt[i:i + 3])})")
            bad = self.js("__ixh.badText()")
            if bad:
                probs.append("bad text: " + "; ".join(bad))
            errs = self.errors()
            if errs:
                probs.append("console: " + " | ".join(errs[:2]))
            note = "; ".join(probs) if probs else (f"ribbon {ra[2]['n']}→{rt[2]['n']} units, {ra[4]['n']}→{rt[4]['n']} messages; view numbers "
                                                    f"{'change' if a['nums'] != t['nums'] else 'the same'} and come back")
            self.check(f"Count-by on {name}", not probs, note)

    def pick_ids(self):
        code, ev, _ = http(self.base, "/api/events?limit=5")
        rows = (ev.get("events") or ev.get("rows") or []) if isinstance(ev, dict) else []
        self.record_id = rows[0]["id"] if rows else None
        named = [r["actor"] for r in rows if r.get("actor") and not str(r["actor"]).startswith("run:")]
        self.actor_id = named[0] if named else None
        if not self.record_id:
            raise RuntimeError("no record id to test with (GET /api/events?limit=5)")


def pages_for(br_runner, tabs, sections=True):
    out = []
    for t in tabs:
        if ":" in t:
            tab, fx = t.split(":", 1)
            out.append(Page(f"forensics › {fx}", f"tab=forensics&fx={fx}"))
        elif t == "forensics" and sections:
            br_runner.goto("tab=forensics")
            ids = br_runner.js("(window.FX_SECTIONS || []).map((x) => x.id)") or []
            out += [Page(f"forensics › {i}", f"tab=forensics&fx={i}") for i in ids] or [Page("forensics", "tab=forensics")]
        elif t == "top":
            out.append(Page("top bar", "tab=overview", "top"))
        elif t == "inspector":
            out.append(Page("inspector", "tab=overview", "inspector"))
        elif t in ("live drawer", "case file", "glossary", "load panel"):
            out.append(Page(t, "tab=overview", "overlay" if t != "load panel" else "top"))
        else:
            out.append(Page(t, f"tab={t}"))
    return out


EXTRA = ["top", "inspector", "live drawer", "case file", "glossary"]


MODES = {   # per_sig, per_kind, max_sigs: how many elements of each signature and kind, and signatures per kind, a page gets
    "quick": (1, 1, 1),        # one element of each kind per page; Forensics as one page; the Count-by check on six tabs
    "sample": (1, 2, 2),       # two of each kind per page, every Forensics section
    "deep": (2, 14, None),     # first and last of every signature
}
UNIT_TABS_QUICK = ("overview", "network", "timeline", "spread", "early", "agents")


def run_dataset(label, base, mode="sample", tabs=None, verbose=False, slow=1.0, scripted=True, budget=None):
    quick = mode == "quick"
    br = Browser(width=1440, height=900)
    t0 = time.time()
    try:
        br.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        br.call("Page.addScriptToEvaluateOnNewDocument", {"source": INIT_JS})
        try:
            br.call("Browser.setDownloadBehavior", {"behavior": "deny"})
        except Exception:
            pass
        r = Runner(br, base, label, quick=quick, verbose=verbose, slow=slow)
        r.pick_ids()
        pages = pages_for(r, tabs or (TABS + (["top", "inspector"] if quick else EXTRA)), sections=not quick)
        per_sig, per_kind, max_sigs = MODES[mode]
        for p in pages:
            if budget and time.time() - t0 > budget:
                r.rows.append({"page": p.name, "hash": p.hash, "found": {}, "exercised": {}, "passed": {}, "failed": [],
                               "skipped": [{"kind": "page", "sig": "budget", "note": f"time budget of {budget} s used up", "label": ""}], "load": []})
                continue
            row = r.run_page(p, per_sig, per_kind, max_sigs)
            f, e, ok = sum(row["found"].values()), sum(row["exercised"].values()), sum(row["passed"].values())
            sys.stdout.write(f"  {label}: {p.name:28} found {f:5}  exercised {e:3}  passed {ok:3}  failed {len(row['failed']):2}  skipped {len(row['skipped']):2}  ({row.get('seconds', 0)} s)\n")
            sys.stdout.flush()
        if scripted:
            for name, fn in (("history", r.history_checks), ("keyboard", r.keyboard_checks),
                             ("units", lambda: r.unit_checks([p for p in pages if p.scope == "left" and (not quick or p.name in UNIT_TABS_QUICK)]))):
                try:
                    fn()
                except Exception as e:
                    r.check(f"{name} checks ran", False, f"{type(e).__name__}: {e}")
        return {"dataset": label, "base": base, "mode": mode, "pages": r.rows, "checks": r.checks, "seconds": round(time.time() - t0, 1),
                "console_lines_ignored_from_blocked_writes": r.ignored}
    finally:
        br.close()


def totals(ds):
    kinds = {}
    for row in ds["pages"]:
        for field in ("found", "exercised", "passed"):
            for k, n in row[field].items():
                kinds.setdefault(k, {"found": 0, "exercised": 0, "passed": 0, "failed": 0, "skipped": 0})[field] += n
        for f in row["failed"]:
            kinds.setdefault(f["kind"], {"found": 0, "exercised": 0, "passed": 0, "failed": 0, "skipped": 0})["failed"] += 1
        for f in row["skipped"]:
            kinds.setdefault(f["kind"], {"found": 0, "exercised": 0, "passed": 0, "failed": 0, "skipped": 0})["skipped"] += 1
    return kinds


def print_report(results, out=sys.stdout):
    """Tables per dataset; returns the number of failures."""
    fails = 0
    for ds in results:
        out.write(f"\n== {ds['dataset']} ({ds['base']}, {ds['mode']}, {ds['seconds']} s)\n")
        out.write(f"{'page':30} {'found':>6} {'exercised':>9} {'passed':>6} {'failed':>6} {'skipped':>7}  kinds exercised\n")
        tf = te = tp = tx = tsk = 0
        for row in ds["pages"]:
            f, e, ok, bad, sk = sum(row["found"].values()), sum(row["exercised"].values()), sum(row["passed"].values()), len(row["failed"]), len(row["skipped"])
            tf, te, tp, tx, tsk = tf + f, te + e, tp + ok, tx + bad, tsk + sk
            kinds = " ".join(f"{k}:{row['exercised'][k]}/{row['found'].get(k, 0)}" for k in KIND_ORDER if k in row["exercised"])
            out.write(f"{row['page']:30} {f:6} {e:9} {ok:6} {bad:6} {sk:7}  {kinds}\n")
        out.write(f"{'total':30} {tf:6} {te:9} {tp:6} {tx:6} {tsk:7}\n")
        out.write(f"\n{'kind':14} {'found':>6} {'exercised':>9} {'passed':>6} {'failed':>6} {'skipped':>7}\n")
        k = totals(ds)
        for name in [x for x in KIND_ORDER if x in k] + [x for x in k if x not in KIND_ORDER]:
            v = k[name]
            out.write(f"{name:14} {v['found']:6} {v['exercised']:9} {v['passed']:6} {v['failed']:6} {v['skipped']:7}\n")
        cf = [c for c in ds["checks"] if not c["ok"]]
        out.write(f"\nscripted checks: {len(ds['checks']) - len(cf)}/{len(ds['checks'])} pass\n")
        for row in ds["pages"]:
            for f in row["failed"]:
                out.write(f"FAIL {row['page']} [{f['kind']}] {f['sig']} {f.get('label', '')!r}: {f['note']}\n")
        for c in cf:
            out.write(f"FAIL check: {c['name']}: {c['note']}\n")
        fails += tx + len(cf)
    out.write(f"\nINTERACT {'OK' if not fails else f'{fails} failures'}\n")
    return fails


def reachable(base):
    code, st, _ = http(base, "/api/state", timeout=8)
    return code == 200 and isinstance(st, dict) and bool(st.get("loaded"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="the demo swarm only: one element of each kind on each tab, the top bar and the Inspector (about 2 minutes)")
    ap.add_argument("--deep", action="store_true", help="the first and last element of every signature on every page (slow: tens of minutes)")
    ap.add_argument("--base", help="a running server that holds the demo swarm (default: start one on a free port)")
    ap.add_argument("--big", default=BIG_DEFAULT, help=f"a running server that holds the Swarm Traces release (default {BIG_DEFAULT}; skipped when it does not answer)")
    ap.add_argument("--only", choices=["demo", "big"], help="one dataset only")
    ap.add_argument("--tabs", nargs="*", help="pages to visit: tab names, forensics:<section>, top, inspector, 'live drawer', 'case file', glossary")
    ap.add_argument("--no-scripted", action="store_true", help="skip the history, keyboard and Count-by checks")
    ap.add_argument("--json", default=os.path.join(ROOT, "reports", "integrity", "interact.json"))
    ap.add_argument("-v", "--verbose", action="store_true", help="one line per element exercised")
    a = ap.parse_args(argv)
    results, skipped, srv = [], [], None
    mode = "quick" if a.quick else "deep" if a.deep else "sample"
    try:
        if a.only != "big":
            base = a.base
            if not base:
                srv = Server(free_port(), os.path.join(PKG, "samples", "demo_swarm"))
                if not srv.wait(300):
                    sys.stdout.write("the demo server did not start: " + srv.output(400) + "\n")
                    return 1
                base = srv.base
            results.append(run_dataset("demo swarm", base, mode=mode, tabs=a.tabs, verbose=a.verbose, scripted=not a.no_scripted))
        if a.only == "big" or (not a.quick and a.only != "demo"):
            if reachable(a.big):
                results.append(run_dataset("Swarm Traces release", a.big, mode=mode, tabs=a.tabs, verbose=a.verbose, slow=3.0, scripted=not a.no_scripted))
            else:
                skipped.append(f"Swarm Traces release: no loaded dataset answers at {a.big}; skipped")
                sys.stdout.write(skipped[-1] + "\n")
    finally:
        if srv:
            srv.stop()
    fails = print_report(results)
    if a.json:
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        with open(a.json, "w") as f:
            json.dump({"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "failures": fails, "skipped_datasets": skipped,
                       "datasets": [dict(ds, kinds=totals(ds)) for ds in results]}, f, indent=1)
        sys.stdout.write(f"report: {os.path.relpath(a.json, ROOT)}\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

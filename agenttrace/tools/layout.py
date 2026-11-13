"""Layout check: does every tab fit its viewport?

    python3 -m agenttrace.tools.layout [--base http://127.0.0.1:8010] [--widths 1024 1280 1440] [--shots DIR]

For each width and tab it reports: the page being wider than the window, the top bar's contents running
past its edge, and elements inside the left or right pane that stick out of it (outside a scroll box).
"""
import argparse, base64, json, os, sys
from .smoke import Browser

TABS = ["trace", "trace&q=cred%20220", "trace&harm=R0009849", "overview", "network", "timeline", "channels", "spread", "early",
        "events", "agents", "forensics", "forensics&fx=attribution", "forensics&fx=content", "forensics&fx=silent",
        "forensics&fx=benchmark", "forensics&fx=whatif", "forensics&fx=validation", "compare", "gaps"]

JS = r"""(() => {
  const out = {page: document.documentElement.scrollWidth - window.innerWidth, bar: [], panes: []};
  const sel = (e) => { let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id; if (e.className && typeof e.className === 'string') s += '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.'); return s; };
  const header = document.querySelector('header');
  if (header) { const hr = header.getBoundingClientRect(); for (const c of header.querySelectorAll('*')) { const r = c.getBoundingClientRect(); if (r.width && r.right > Math.min(hr.right, window.innerWidth) + 1) { out.bar.push(sel(c) + ' +' + Math.round(r.right - Math.min(hr.right, window.innerWidth))); if (out.bar.length > 5) break; } } out.barH = Math.round(hr.height); }
  const scrolls = (e, stop) => { for (let p = e.parentElement; p && p !== stop; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  for (const id of ['left', 'right']) { const pane = document.getElementById(id); if (!pane) continue; const pr = pane.getBoundingClientRect(); let n = 0;
    if (pr.right > window.innerWidth + 1) out.panes.push('#' + id + ' itself +' + Math.round(pr.right - window.innerWidth));
    for (const c of pane.querySelectorAll('*')) { const r = c.getBoundingClientRect(); if (!r.width || !r.height) continue; if (r.right > pr.right + 2 && !scrolls(c, pane) && !c.closest('svg')) { out.panes.push('#' + id + ' ' + sel(c) + ' +' + Math.round(r.right - pr.right)); if (++n >= 4) break; } } }
  return JSON.stringify(out); })()"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--widths", type=int, nargs="*", default=[1024, 1280, 1440])
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--shots")
    ap.add_argument("--tabs", nargs="*", default=TABS)
    a = ap.parse_args(argv)
    bad = 0
    for w in a.widths:
        br = Browser(width=w, height=a.height)
        try:
            br.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": a.height, "deviceScaleFactor": 1, "mobile": False})
            br.navigate(a.base + "/")
            br.settle(timeout=90)
            br.eval("localStorage.setItem('swarm-tracer-guide-dismissed','1')")
            for t in a.tabs:
                br.navigate("about:blank")
                br.navigate(f"{a.base}/#tab={t}")
                br.settle(quiet=1.0, timeout=90)
                r = json.loads(br.eval(JS))
                probs = ([f"page +{r['page']}"] if r["page"] > 1 else []) + [f"bar: {x}" for x in r["bar"]] + r["panes"]
                if r.get("barH", 0) > 110:
                    probs.append(f"bar is {r['barH']} px tall")
                print(f"{w:5} {t:28} {'ok' if not probs else '; '.join(probs)}")
                bad += bool(probs)
                if a.shots:
                    os.makedirs(a.shots, exist_ok=True)
                    png = br.call("Page.captureScreenshot", {"format": "png"})["data"]
                    with open(os.path.join(a.shots, f"{w}_{t.replace('&', '_').replace('=', '-').replace('%20', '_')}.png"), "wb") as f:
                        f.write(base64.b64decode(png))
        finally:
            br.close()
    print("LAYOUT", "OK" if not bad else f"{bad} views with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

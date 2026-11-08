"""Build the hackathon report PDF from paper/report.html.

Tables are filled from the evaluation output, figures are embedded from the SVGs the tool draws,
and the page is printed to PDF with headless Chrome. Run from the project root after:

    python3 -m agenttrace evaluate redacted_columns.csv --pack code_traces.json --out reports/evaluation
    python3 -m agenttrace evaluate full-wiki-logs --pack wiki_swarm.json --out reports/evaluation-wiki
    python3 paper/build.py --author "Your Name" --affiliation "Your affiliation"
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agenttrace import figures, labels  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT_CSS = "https://fonts.googleapis.com/css2?family=Old+Standard+TT:ital,wght@0,400;0,700;1,400"


def ensure_fonts(d):
    os.makedirs(d, exist_ok=True)
    if len([f for f in os.listdir(d) if f.endswith(".ttf")]) >= 3:
        return
    req = urllib.request.Request(FONT_CSS, headers={"User-Agent": "Mozilla/4.0"})
    css = urllib.request.urlopen(req, timeout=30).read().decode()
    for block in re.findall(r"@font-face\s*{[^}]*}", css):
        style = re.search(r"font-style:\s*(\w+)", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+)\)", block).group(1)
        urllib.request.urlretrieve(url, os.path.join(d, f"OldStandardTT-{style}-{weight}.ttf"))


def pipeline_svg():
    steps = [("Load", "any JSONL, CSV,", "or linked folder"), ("Date", "timestamps in code,", "fit per block"),
             ("Identify", "tokens and labels;", "shared keys out"), ("Find places", "datasets, folders,", "pages, threads"),
             ("Link messages", "write, then read by", "another identity"), ("Count honestly", "reruns, re-reads,", "overwrites out"),
             ("Replay", "when each signal", "first fires")]
    W, bw, gap, y0, h = 720, 92, 12, 8, 62
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h + 18}" role="img" aria-label="The Swarm Tracer pipeline">',
           '<defs><marker id="pa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1L10,5L0,9z" fill="#7d8790"/></marker></defs>']
    for i, (name, a, b) in enumerate(steps):
        x = 2 + i * (bw + gap)
        accent = name in ("Link messages", "Count honestly")
        out.append(f'<rect x="{x}" y="{y0}" width="{bw}" height="{h}" rx="7" fill="{"#e8f0fa" if accent else "#f4f6f8"}" '
                   f'stroke="{"#2f6fb3" if accent else "#aab3bc"}" stroke-width="{1.4 if accent else 1}"/>')
        out.append(figures.t(x + bw / 2, y0 + 22, name, 11.5, "#1d2329", "middle", "bold"))
        out.append(figures.t(x + bw / 2, y0 + 39, a, 9.5, "#5f6b76", "middle"))
        out.append(figures.t(x + bw / 2, y0 + 51, b, 9.5, "#5f6b76", "middle"))
        if i < len(steps) - 1:
            out.append(f'<line x1="{x + bw + 1}" y1="{y0 + h / 2}" x2="{x + bw + gap - 1}" y2="{y0 + h / 2}" stroke="#7d8790" stroke-width="1.2" marker-end="url(#pa)"/>')
    out.append("</svg>")
    return "\n".join(out)


def strip_xml(svg):
    return re.sub(r"<\?xml[^>]*>", "", svg)


def pct(x):
    return f"{round(x * 100)}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="Author name")
    ap.add_argument("--affiliation", default="Affiliation")
    ap.add_argument("--swarm", default=os.path.join(ROOT, "reports", "evaluation"))
    ap.add_argument("--wiki", default=os.path.join(ROOT, "reports", "evaluation-wiki"))
    ap.add_argument("--labels", default=os.path.join(ROOT, "reports", "submission", "precision_labels.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "submission"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ensure_fonts(os.path.join(a.out, "fonts"))
    with open(os.path.join(ROOT, "paper", "report.html"), encoding="utf-8") as f:
        page = f.read()
    ev = json.load(open(os.path.join(a.swarm, "evaluation.json"), encoding="utf-8"))
    evw = json.load(open(os.path.join(a.wiki, "evaluation.json"), encoding="utf-8")) if os.path.exists(os.path.join(a.wiki, "evaluation.json")) else None
    figures.write_from_files(a.swarm)

    timing = []
    for m in ev["external"]["milestones"]:
        diff = m["difference_h"]
        timing.append(f'<tr><td>{html.escape(m["event"])} <span class="small">({html.escape(m["source"])})</span></td>'
                      f'<td>{html.escape(m["source_time"][5:])}</td><td>{html.escape(m["match"])}</td>'
                      f'<td>{html.escape((m["ours"] or "")[5:])}</td><td class="n">{"+" if diff and diff > 0 else ""}{diff}</td></tr>')

    counts = []
    sw, wk = ev["counting_rules"], (evw or {}).get("counting_rules", [])
    labels_rules = ["Naive: every read after another identity's write",
                    "+ reruns of the same program out; each write once per reader",
                    "+ overwrites out (whole-page edits that keep none of the earlier lines)"]
    for i, lab in enumerate(labels_rules):
        s = sw[i] if i < len(sw) else None
        w = wk[i] if i < len(wk) else None
        fmt = lambda x: f"{x:,}"
        counts.append(f'<tr><td>{html.escape(lab)}</td><td class="n">{fmt(s["messages"]) if s else "n/a"}</td><td class="n">{fmt(s["pairs"]) if s else "n/a"}</td>'
                      f'<td class="n">{fmt(w["messages"]) if w else "n/a"}</td><td class="n">{fmt(w["pairs"]) if w else "n/a"}</td></tr>')

    robust = []
    for s in ev["robustness"]["signals"]:
        name, _ = figures.signal_info(s["signal"], s.get("ref"))
        robust.append(f'<tr><td>{html.escape(name)}</td><td>{html.escape(s["time"].replace("at or before ", "")[5:])}</td>'
                      f'<td class="n">{pct(s["harm_share_after"])}</td><td class="n">{pct(s["interval_95"][0])}&ndash;{pct(s["interval_95"][1])}</td>'
                      f'<td class="n">{pct(s["if_signal_1h_earlier"])}</td><td class="n">{pct(s["if_signal_1h_later"])}</td></tr>')
    for key, name in (("rate_alarm_all_actions", "Volume alarm on all actions (baseline)"), ("rate_alarm_harmful_actions", "Volume alarm on harmful actions (baseline)")):
        b = ev["baselines"].get(key)
        if b:
            robust.append(f'<tr><td>{name}</td><td>end of {html.escape(b["hour"][5:])} hour</td><td class="n">{pct(b["harm_share_after"])}</td>'
                          f'<td class="n">n/a</td><td class="n">n/a</td><td class="n">n/a</td></tr>')

    prec = []
    if os.path.exists(a.labels):
        p = labels.precision(a.labels)
        for tag, v in sorted(p["tags"].items(), key=lambda kv: -(kv[1]["judged"] or 0)):
            if not v["judged"]:
                continue
            prec.append(f'<tr><td>{html.escape(tag.replace("_", " "))}</td><td class="n">{v["judged"]}</td><td class="n">{v["tp"]}</td>'
                        f'<td class="n">{pct(v["precision"])}</td><td class="n">{pct(v["ci_low"])}&ndash;{pct(v["ci_high"])}</td></tr>')

    with open(os.path.join(a.swarm, "fig_early_flag.svg"), encoding="utf-8") as f:
        early = strip_xml(f.read())
    with open(os.path.join(a.swarm, "fig_network.svg"), encoding="utf-8") as f:
        net = strip_xml(f.read())
    page = (page.replace("{{AUTHOR}}", html.escape(a.author)).replace("{{AFFILIATION}}", html.escape(a.affiliation))
            .replace("{{FIG_PIPELINE}}", pipeline_svg()).replace("{{FIG_EARLY}}", early).replace("{{FIG_NETWORK}}", net)
            .replace("{{TIMING_ROWS}}", "\n".join(timing)).replace("{{COUNT_ROWS}}", "\n".join(counts))
            .replace("{{ROBUST_ROWS}}", "\n".join(robust)).replace("{{PRECISION_ROWS}}", "\n".join(prec)))
    left = re.findall(r"{{[A-Z_]+}}", page)
    if left:
        sys.exit(f"unfilled placeholders: {left}")
    html_path = os.path.join(a.out, "report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    pdf_path = os.path.join(a.out, "Swarm_Tracer_report.pdf")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=8000", f"--print-to-pdf={pdf_path}", "file://" + html_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(pdf_path)


if __name__ == "__main__":
    main()

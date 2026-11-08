"""Report figures drawn straight from the data, as SVG, so they can be regenerated with one command.

fig_early_flag.svg  harm still to come over time, every warning signal (with its 95% range under
                    time error), and the volume-alarm baselines
fig_network.svg     who talked to whom: senders left, receivers right, both in the middle

The label placement is the same search the app uses: each label goes where it covers no line, no
dot and no other label, as close to its dot as it can.
"""
import math
import os
from html import escape

from . import model, reconstruct


def _ts(s):
    """Epoch seconds for a time string, or None."""
    d = model.parse_time(s) if s else None
    return d.timestamp() if d else None

INK, QUIET, GRID, AXIS, CURVE = "#1d2329", "#5f6b76", "#e3e7ec", "#9aa5b1", "#b8beb6"
ACCENT, SINGLE, BASE = "#2f6fb3", "#4b5157", "#c0662b"
FONT = "Helvetica, Arial, sans-serif"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

NAMES = {
    "registry_board": "Registry mailbox first used", "docker_registry": "Docker registry first used",
    "hf_dataset_write": "First Hugging Face dataset write", "kubernetes_api": "Kubernetes API first called",
    "cloud_metadata": "Cloud metadata first requested", "probe_request": "First probe request",
    "hides_page": "First page hidden", "proxy_link": "First proxy link", "recreated_after_delete": "Page recreated after a delete",
}


def signal_info(sig, ref=""):
    s = str(sig)
    if s.startswith("first message"):
        return "First message between named actors", True
    if s.startswith("coordination: one identity carries"):
        return "One token carries another's token", True
    if s.startswith("coordination: two identities"):
        return (f"Two tokens share the name {ref}" if ref and len(str(ref)) < 16 else "Two tokens share one place"), True
    if s.startswith("coordination"):
        return s.split(":", 1)[1].strip().capitalize(), True
    if s.startswith("spread"):
        return "Token seen as data, then used", False
    key = s.replace("first:", "").strip()
    return NAMES.get(key, "First " + key.replace("_", " ")), False


def text_w(s, size, bold=False):
    """Rough width of Helvetica text; good enough to keep labels apart."""
    narrow = sum(1 for c in s if c in "iljtfr.,:;'| ()[]1I")
    wide = sum(1 for c in s if c in "mwMW@%")
    caps = sum(1 for c in s if c.isupper())
    n = len(s) - narrow - wide
    w = (n * 0.55 + narrow * 0.3 + wide * 0.85 + caps * 0.1) * size
    return w * (1.07 if bold else 1.0)


def t(x, y, s, size=11, fill=INK, anchor="start", weight="normal", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}"{extra}>{escape(str(s))}</text>')


def day_word(ts):
    d = reconstruct.iso(ts)
    return f"{MONTHS[int(d[5:7]) - 1]} {int(d[8:10])}"


def place_labels(items, box, avoid, max_leader=300):
    """Grid search: no label overlaps another, and labels cover as little of the line and dots as possible."""
    C = 5
    x0, x1, y0, y1 = box
    nx, ny = int((x1 - x0) / C) + 2, int((y1 - y0) / C) + 2
    grid = [[0] * nx for _ in range(ny)]
    for (px, py, r) in avoid:
        for j in range(int((py - r - y0) // C), int((py + r - y0) // C) + 1):
            for i in range(int((px - r - x0) // C), int((px + r - x0) // C) + 1):
                if 0 <= i < nx and 0 <= j < ny:
                    grid[j][i] = 1
    P = [[0] * (nx + 1) for _ in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            P[j + 1][i + 1] = grid[j][i] + P[j][i + 1] + P[j + 1][i] - P[j][i]

    def covered(bx, by, bw, bh):
        i0, i1 = max(0, int((bx - x0) // C)), min(nx, int(math.ceil((bx + bw - x0) / C)))
        j0, j1 = max(0, int((by - y0) // C)), min(ny, int(math.ceil((by + bh - y0) / C)))
        return P[j1][i1] - P[j0][i1] - P[j1][i0] + P[j0][i0]

    def hits(a, b, m=4):
        return a[0] < b[0] + b[2] + m and b[0] < a[0] + a[2] + m and a[1] < b[1] + b[3] + m and b[1] < a[1] + a[3] + m

    def crosses(ax, ay, bx, by, r):
        t0, t1, dx, dy = 0.0, 1.0, bx - ax, by - ay
        for p, q in ((-dx, ax - r[0]), (dx, r[0] + r[2] - ax), (-dy, ay - r[1]), (dy, r[1] + r[3] - ay)):
            if p == 0:
                if q < 0:
                    return False
                continue
            tt = q / p
            if p < 0:
                if tt > t1:
                    return False
                t0 = max(t0, tt)
            else:
                if tt < t0:
                    return False
                t1 = min(t1, tt)
        return True

    placed = []
    for it in items:
        best = None
        y = y0
        while y + it["h"] <= y1:
            x = x0
            while x + it["w"] <= x1:
                b = (x, y, it["w"], it["h"])
                if not any(hits(b, p) for p in placed):
                    lx, ly = max(x, min(it["x"], x + it["w"])), max(y, min(it["y"], y + it["h"]))
                    d = math.hypot(lx - it["x"], ly - it["y"])
                    if d <= max_leader:
                        near = sum(1 for o in items if o is not it and x - 16 < o["x"] < x + it["w"] + 16 and y - 16 < o["y"] < y + it["h"] + 16)
                        cross = sum(1 for p in placed if crosses(it["x"], it["y"], lx, ly, p))
                        cost = covered(*b) * 60 + d * 1.2 + (10 if d > 12 else 0) + near * 90 + cross * 160
                        if best is None or cost < best[0]:
                            best = (cost, b)
                x += 6
            y += 6
        if best:
            it["label"] = best[1]
            placed.append(best[1])


# ------------------------------------------------------------------ figure 1: early flag

def early_flag(summary, evaluation, W=720):
    """Harm still to come over time. Each signal is an exact point on the line with a numbered badge
    placed nearby; the key under the chart gives each number's name, time and 95% range."""
    rem = summary["harm_remaining_by_hour"]
    hours = [_ts(h.replace(" ", "T") + ":00:00Z") for h, _ in rem]
    tmin, tmax = hours[0] - 1800, hours[-1] + 3600
    x0, x1, yT, yB = 50, W - 14, 28, 222
    X = lambda ts: x0 + (ts - tmin) / (tmax - tmin) * (x1 - x0)
    Y = lambda v: yB - v * (yB - yT)
    pts = [(X(ts), Y(v)) for ts, (_, v) in zip(hours, rem)]
    # the signals, then the volume-alarm baselines, in time order
    items = []
    for s in evaluation["robustness"]["signals"]:
        name, joint = signal_info(s["signal"], s.get("ref"))
        ts = _ts(s["time"].replace("at or before ", "").replace(" ", "T") + ":00Z")
        items.append({"name": name, "kind": "joint" if joint else "single", "ts": ts, "share": s["harm_share_after"],
                      "lo": s["interval_95"][0], "hi": s["interval_95"][1], "ref": s.get("ref")})
    for key, name in (("rate_alarm_all_actions", "Volume alarm on all actions (baseline)"),
                      ("rate_alarm_harmful_actions", "Volume alarm on harmful actions (baseline)")):
        b = evaluation["baselines"].get(key)
        if b:
            items.append({"name": name, "kind": "base", "ts": _ts(b["hour"].replace(" ", "T") + ":00Z") + 3600,
                          "share": b["harm_share_after"], "lo": None, "hi": None, "ref": None})
    items.sort(key=lambda i: (i["ts"], i["kind"] == "base"))
    color = {"joint": ACCENT, "single": SINGLE, "base": BASE}
    for k, it in enumerate(items, 1):
        it.update(n=k, x=X(it["ts"]), y=Y(it["share"]), w=17, h=17)
    # badges go where they cover no line, no point and no other badge, close to their point
    avoid = []
    for i in range(len(pts) - 1):
        for k in range(8):
            avoid.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k / 8, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k / 8, 3))
    avoid += [(it["x"], it["y"], 5) for it in items]
    place_labels(items, (x0 + 2, x1, yT - 4, yB - 2), avoid, max_leader=120)
    rows = (len(items) + 1) // 2
    H = yB + 38 + rows * 27 + 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Share of timed harmful activity still to come, with the first time each warning sign fired">',
           f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for v in (0, 0.25, 0.5, 0.75, 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}"/>')
        out.append(t(x0 - 7, Y(v) + 4, f"{int(v * 100)}%", 10.5, QUIET, "end"))
    out.append(f'<line x1="{x0}" x2="{x1}" y1="{yB}" y2="{yB}" stroke="{AXIS}"/>')
    d = (int(tmin // 86400) + 1) * 86400
    while d <= tmax:
        out.append(f'<line x1="{X(d):.1f}" x2="{X(d):.1f}" y1="{yB}" y2="{yB + 5}" stroke="{AXIS}"/>')
        out.append(t(X(d), yB + 18, day_word(d), 10.5, QUIET, "middle"))
        d += 86400
    out.append(t(x0, 16, "Share of timed harmful actions still to come (UTC)", 10.5, QUIET))
    out.append(f'<path d="{"".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))}" '
               f'fill="none" stroke="{CURVE}" stroke-width="2.6"/>')
    for it in items:   # 95% range under time error: a light whisker
        if it["lo"] is not None and abs(Y(it["lo"]) - Y(it["hi"])) > 2:
            c = color[it["kind"]]
            out.append(f'<line x1="{it["x"]:.1f}" x2="{it["x"]:.1f}" y1="{Y(it["hi"]):.1f}" y2="{Y(it["lo"]):.1f}" stroke="{c}" stroke-opacity=".35" stroke-width="3" stroke-linecap="round"/>')
    for it in items:
        c = color[it["kind"]]
        if it.get("label"):
            bx, by, bw, bh = it["label"]
            cx, cy = bx + bw / 2, by + bh / 2
            if math.hypot(cx - it["x"], cy - it["y"]) > 11:
                out.append(f'<line x1="{it["x"]:.1f}" y1="{it["y"]:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" stroke="{c}" stroke-opacity=".55" stroke-width="1"/>')
        if it["kind"] == "base":
            out.append(f'<path d="M{it["x"]:.1f} {it["y"] - 4.5:.1f}l4.5 4.5l-4.5 4.5l-4.5 -4.5z" fill="#fff" stroke="{c}" stroke-width="1.6"/>')
        else:
            out.append(f'<circle cx="{it["x"]:.1f}" cy="{it["y"]:.1f}" r="3.6" fill="{c}" stroke="#fff" stroke-width="1"/>')
    for it in items:
        if it.get("label"):
            bx, by, bw, bh = it["label"]
            c = color[it["kind"]]
            fill = "#fff" if it["kind"] == "base" else c
            out.append(f'<circle cx="{bx + bw / 2:.1f}" cy="{by + bh / 2:.1f}" r="8" fill="{fill}" stroke="{c}" stroke-width="1.4"/>')
            out.append(t(bx + bw / 2, by + bh / 2 + 3.6, it["n"], 9.5, c if it["kind"] == "base" else "#fff", "middle", "bold"))
    # key: two columns under the chart
    ky = yB + 36
    out.append(t(x0, ky - 6, "", 1))
    colw = (x1 - x0) / 2
    for i, it in enumerate(items):
        cx = x0 + (i // rows) * colw
        cy = ky + (i % rows) * 27
        c = color[it["kind"]]
        fill = "#fff" if it["kind"] == "base" else c
        out.append(f'<circle cx="{cx + 8:.1f}" cy="{cy:.1f}" r="8" fill="{fill}" stroke="{c}" stroke-width="1.4"/>')
        out.append(t(cx + 8, cy + 3.6, it["n"], 9.5, c if it["kind"] == "base" else "#fff", "middle", "bold"))
        out.append(t(cx + 22, cy + 1, it["name"], 11, INK, weight="bold"))
        rng = f" (95%: {round(it['lo'] * 100)}-{round(it['hi'] * 100)}%)" if it["lo"] is not None and it["hi"] - it["lo"] > 0.005 else ""
        out.append(t(cx + 22, cy + 14, f"{day_word(it['ts'])} {reconstruct.iso(it['ts'])[11:16]} · {round(it['share'] * 100)}% still to come{rng}", 10, QUIET))
    out.append("</svg>")
    return "\n".join(out)


# ------------------------------------------------------------------ figure 2: who talked to whom

def network(pairs, W=720, short=lambda a: a.replace("[CREDENTIAL ", "cred ").replace("]", "")):
    out_n, in_n, tot, nb = {}, {}, {}, {}
    for p in pairs:
        a, b, n = p["from"], p["to"], p["deliveries"]
        out_n[a] = out_n.get(a, 0) + n
        in_n[b] = in_n.get(b, 0) + n
        tot[a] = tot.get(a, 0) + n
        tot[b] = tot.get(b, 0) + n
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    names = list(tot)
    col = {n: 1 if out_n.get(n) and in_n.get(n) else (0 if out_n.get(n) else 2) for n in names}
    root = {n: n for n in names}

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x
    for p in pairs:
        ra, rb = find(p["from"]), find(p["to"])
        if ra != rb:
            root[ra] = rb
    groups = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    groups = sorted(groups.values(), key=lambda g: -sum(out_n.get(n, 0) for n in g))
    row = {}
    layout = []
    for g in groups:
        cols = [[], [], []]
        for n in sorted(g, key=lambda n: -tot[n]):
            cols[col[n]].append(n)
        rows = max(len(c) for c in cols)
        for _ in range(8):
            for ci in (2, 1, 0, 1):
                for c in cols:
                    for i, n in enumerate(c):
                        row[n] = i + (rows - len(c)) / 2
                cols[ci].sort(key=lambda n: (sum(row.get(m, 0) for m in nb[n]) / len(nb[n]), -tot[n]))
        for c in cols:
            for i, n in enumerate(c):
                row[n] = i + (rows - len(c)) / 2
        layout.append((g, rows))
    ROW, BOX, TOP, PAD = 25, 18, 26, 6
    present = [c for c in (0, 1, 2) if any(col[n] == c for n in names)]
    need = {c: min(170, max(text_w(short(n), 11) + text_w(str(tot[n]), 10) + 26 for n in names if col[n] == c)) for c in present}
    gap = 110
    total_w = sum(need.values()) + gap * (len(present) - 1)
    x = (W - total_w) / 2
    colx = {}
    for c in present:
        colx[c] = x
        x += need[c] + gap
    pos, y, bands = {}, TOP, []
    for g, rows in layout:
        y0 = y
        y += PAD
        for n in g:
            pos[n] = (colx[col[n]], y + row[n] * ROW + ROW / 2)
        y += rows * ROW + PAD
        bands.append((y0, y))
        y += 4
    H = int(y + 6)
    mx = max(p["deliveries"] for p in pairs)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Who talked to whom">',
           f'<rect width="{W}" height="{H}" fill="#fff"/>',
           f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,1L10,5L0,9z" fill="{ACCENT}"/></marker></defs>']
    for i, (a, b) in enumerate(bands):
        svg.append(f'<rect x="0" y="{a}" width="{W}" height="{b - a}" rx="6" fill="{"#f5f7fa" if i % 2 == 0 else "#fff"}"/>')
    heads = {0: "only sends", 1: "sends and receives", 2: "only receives"}
    for c in present:
        svg.append(t(colx[c] + need[c] / 2, 15, heads[c], 10.5, QUIET, "middle"))
    for p in pairs:
        (ax, ay), (bx, by) = pos[p["from"]], pos[p["to"]]
        w = 1.1 + 4.0 * math.log1p(p["deliveries"]) / math.log1p(mx)
        if col[p["from"]] == 1 and col[p["to"]] == 1:
            bend = min(gap * 0.6, 16 + 7 * abs(by - ay) / ROW)
            cw = need[1]
            d = (f"M{ax + cw:.1f},{ay:.1f} C{ax + cw + bend:.1f},{ay:.1f} {bx + cw + bend:.1f},{by:.1f} {bx + cw + 2:.1f},{by:.1f}" if by > ay
                 else f"M{ax:.1f},{ay:.1f} C{ax - bend:.1f},{ay:.1f} {bx - bend:.1f},{by:.1f} {bx - 2:.1f},{by:.1f}")
        else:
            x1, x2 = ax + need[col[p["from"]]], bx - 2
            h = (x2 - x1) / 2
            d = f"M{x1:.1f},{ay:.1f} C{x1 + h:.1f},{ay:.1f} {x2 - h:.1f},{by:.1f} {x2:.1f},{by:.1f}"
        svg.append(f'<path d="{d}" fill="none" stroke="{ACCENT}" stroke-opacity=".45" stroke-width="{w:.2f}" marker-end="url(#ah)"/>')
    fills = {0: ("#fdf0da", "#e3a43b"), 1: ("#e7effa", ACCENT), 2: ("#eef1f4", AXIS)}
    for n in names:
        x, y = pos[n]
        f, s = fills[col[n]]
        bw = need[col[n]]
        svg.append(f'<rect x="{x:.1f}" y="{y - BOX / 2:.1f}" width="{bw:.1f}" height="{BOX}" rx="9" fill="{f}" stroke="{s}"/>')
        svg.append(t(x + 8, y + 4, short(n), 11, INK))
        svg.append(t(x + bw - 8, y + 4, tot[n], 10, QUIET, "end"))
    svg.append("</svg>")
    return "\n".join(svg)


def write_all(session, evaluation, out_dir, top_pairs=24):
    s = session.summary()
    written = []
    path = os.path.join(out_dir, "fig_early_flag.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(early_flag(s, evaluation))
    written.append(path)
    pairs = s["flow"]["top_pairs"][:top_pairs]
    if pairs:
        path = os.path.join(out_dir, "fig_network.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(network(pairs))
        written.append(path)
    return written


def write_from_files(out_dir, top_pairs=24):
    """Redraw the figures from a finished evaluation folder (evaluation.json + summary.json)."""
    import json
    with open(os.path.join(out_dir, "evaluation.json"), encoding="utf-8") as f:
        ev = json.load(f)
    with open(os.path.join(out_dir, "summary.json"), encoding="utf-8") as f:
        s = json.load(f)
    written = []
    with open(os.path.join(out_dir, "fig_early_flag.svg"), "w", encoding="utf-8") as f:
        f.write(early_flag(s, ev))
    written.append("fig_early_flag.svg")
    pairs = s["flow"]["top_pairs"][:top_pairs]
    if pairs:
        with open(os.path.join(out_dir, "fig_network.svg"), "w", encoding="utf-8") as f:
            f.write(network(pairs))
        written.append("fig_network.svg")
    return written

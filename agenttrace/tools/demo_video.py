"""Build the narrated demo video (docs/assets/demo.mp4) from docs/assets/demo-script.md. macOS only.

    python3 -m agenttrace.tools.demo_video                       # check the numbers, capture, narrate, assemble
    python3 -m agenttrace.tools.demo_video --check               # only compare the script's numbers with the app
    python3 -m agenttrace.tools.demo_video --update-script       # rewrite the message-count sentence from the app, then build
    python3 -m agenttrace.tools.demo_video --base http://127.0.0.1:8010 --out docs/assets/demo.mp4 --keep /tmp/demo-build

The script file is the single source: each "## N. Title" section has a "Screens:" line (hash URLs of the app, or
the website) and the narration below it. For each section this captures the screens from a running server that
holds the Swarm Traces release (headless Chrome, 1440x900), speaks the narration with `say` (voice Samantha, 175
words a minute) and shows the section's screens for equal shares of its narration. Sections follow each other
with a short pause.

Before anything is recorded the numbers in the "Who talked to whom" section are compared with the server
(/api/state, /api/pairs, /api/x/units_map): messages in all, messages between named tokens, the tokens and pairs
they involve, and how many fall inside one estimated agent. A stale number stops the build; --update-script
rewrites that sentence from the server's numbers first.

Assembly uses ffmpeg when one is on the PATH, otherwise AVFoundation through a small Swift program run with
/usr/bin/swift (part of the Xcode command line tools). Nothing is downloaded or installed.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .smoke import BUSY_JS, ROOT, Browser, http

VOICE, RATE, W, H = "Samantha", 175, 1440, 900
PAUSE = 0.7          # seconds of silence after each section
FPS = 5
SCRIPT = os.path.join(ROOT, "docs", "assets", "demo-script.md")
OUT = os.path.join(ROOT, "docs", "assets", "demo.mp4")

WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
         "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def unword(s):
    s = s.lower()
    return WORDS.index(s) if s in WORDS else int(s.replace(",", ""))


NUM = r"(\d[\d,]*|" + "|".join(WORDS) + ")"
# what the script calls one write-then-read: "messages" until v2.2.0, "deliveries" since (a read does not show the
# reader used what was written). Either word is understood; the count checked against the app is the same one.
NOUN = r"(messages?|deliver(?:y|ies))"
# the sentences that carry the audited counts, as regular expressions over the narration
CLAIMS = [
    ("messages", re.compile(r"That leaves " + NUM + " " + NOUN + r" in all"), "That leaves {messages} messages in all", False),
    ("named", re.compile(NUM + r" of them between " + NUM + r" named tokens"), None, True),
    ("pairs", re.compile(r"in " + NUM + r" sender-receiver pairs?"), None, True),
    ("inside", re.compile(NUM + r" of those " + NUM + r" (?:are|is) between tokens", re.I), None, True),
]


def noun_for(n, like="messages"):
    """'message(s)' or 'delivery/deliveries' for a count, following the word the script already uses."""
    one, many = ("delivery", "deliveries") if like.startswith("deliver") else ("message", "messages")
    return one if n == 1 else many


def parse_script(path):
    """[{n, title, screens: [str], text}] from the narration file."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    out = []
    for m in re.finditer(r"^## (\d+)\. (.+?)\n(.*?)(?=^## |\Z)", src, re.S | re.M):
        body = m.group(3).strip()
        sm = re.search(r"^Screens:\s*(.+)$", body, re.M)
        screens = re.findall(r"`([^`]+)`", sm.group(1)) if sm else []
        text = " ".join(ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("Screens:"))
        out.append({"n": int(m.group(1)), "title": m.group(2).strip(), "screens": screens, "text": text})
    return out


def app_numbers(base):
    code, st, _ = http(base, "/api/state", timeout=120)
    if code != 200 or not isinstance(st, dict) or not st.get("loaded"):
        raise RuntimeError(f"no loaded dataset at {base} (GET /api/state: {code})")
    f = st["summary"]["flow"]
    code, pr, _ = http(base, "/api/pairs?limit=1000", timeout=120)
    rows = [r for r in (pr.get("rows") or []) if r.get("named")] if isinstance(pr, dict) else []
    code, um, _ = http(base, "/api/x/units_map", timeout=120)
    um = um if isinstance(um, dict) else {}
    return {"records": st["summary"]["records"], "name": st["summary"]["name"], "messages": f["deliveries"],
            "named": f.get("deliveries_between_named_actors"), "pairs": f.get("named_actor_pairs"),
            "tokens": len({x for r in rows for x in (r.get("from"), r.get("to"))}) if rows else None,
            "inside": (um.get("messages") or {}).get("inside_one_agent"), "agent_messages": (um.get("messages") or {}).get("agent")}


def claim_sentence(n, noun="messages"):
    """The counts sentence, written from the numbers, with the script's own word for a write-then-read."""
    s = (f"That leaves {n['messages']} {noun_for(n['messages'], noun)} in all, {word(n['named'])} of them between {word(n['tokens'])} named tokens, "
         f"in {word(n['pairs'])} sender-receiver pairs.")
    if n.get("inside"):
        s += f" {word(n['inside']).capitalize()} of those {word(n['named'])} are between tokens that Swarm Tracer estimates belong to one agent."
    return s


def check_numbers(sections, n):
    """Problems (strings) between the narration and the app's numbers; empty when they agree."""
    text = " ".join(s["text"] for s in sections)
    probs = []
    m = CLAIMS[0][1].search(text)
    if not m:
        probs.append('no sentence "That leaves N messages in all" (or "N deliveries in all") in the script')
    elif unword(m.group(1)) != n["messages"]:
        probs.append(f"script says {m.group(1)} {m.group(2)} in all; the app has {n['messages']}")
    m = CLAIMS[1][1].search(text)
    if not m:
        probs.append('no "N of them between M named tokens" in the script')
    else:
        if unword(m.group(1)) != n["named"]:
            probs.append(f"script says {m.group(1)} between named tokens; the app has {n['named']}")
        if n["tokens"] is not None and unword(m.group(2)) != n["tokens"]:
            probs.append(f"script says {m.group(2)} named tokens; the app's named pairs involve {n['tokens']}")
    m = CLAIMS[2][1].search(text)
    if not m:
        probs.append('no "in N sender-receiver pairs" in the script')
    elif unword(m.group(1)) != n["pairs"]:
        probs.append(f"script says {m.group(1)} sender-receiver pairs; the app has {n['pairs']}")
    m = CLAIMS[3][1].search(text)
    if n.get("inside"):
        if not m:
            probs.append(f"the script does not say that {n['inside']} of the {n['named']} named messages are inside one estimated agent")
        elif unword(m.group(1)) != n["inside"] or unword(m.group(2)) != n["named"]:
            probs.append(f"script says {m.group(1)} of those {m.group(2)} inside one agent; the app has {n['inside']} of {n['named']}")
    elif m:
        probs.append("the script says some named messages are inside one estimated agent; the app has none")
    rec = re.search(r"([\d,]{5,}) records", text)
    if rec and unword(rec.group(1)) != n["records"]:
        probs.append(f"script says {rec.group(1)} records; the app has {n['records']:,}")
    return probs


def update_script(path, n):
    """Rewrite the counts sentence(s) in the narration file from the app's numbers. True when the file changed."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    pat = re.compile(r"That leaves " + NUM + " " + NOUN + r" in all[^.]*\.(?: [A-Za-z]+ of those " + NUM + r" (?:are|is) between tokens[^.]*\.)?")
    new, k = pat.subn(lambda m: claim_sentence(n, m.group(2)), src, count=1)
    if not k:
        raise RuntimeError('the script has no sentence starting "That leaves N messages in all" (or "N deliveries in all") to rewrite')
    if new != src:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    return new != src


def capture(base, screens, folder, log):
    """One PNG per distinct screen; returns {screen: path}."""
    out = {}
    br = Browser(width=W, height=H)
    try:
        br.call("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
        br.call("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('swarm-tracer-guide-dismissed', '1'); } catch (e) {}"})
        for i, sc in enumerate(dict.fromkeys(screens)):
            t0 = time.time()
            br.navigate("about:blank")
            if sc.startswith("#"):
                br.navigate(base.rstrip("/") + "/" + sc)
                br.wait_until("typeof S !== 'undefined' && !!S.summary", timeout=300)
                br.settle(quiet=1.0, timeout=180, busy_expr=BUSY_JS)
                if re.search(r"[#&](rec|actor|place)=", sc):
                    br.wait_until("!!document.querySelector('#trace .dhead, #trace .dsec')", timeout=120)
                want = re.search(r"[#&]scroll=(\d+)", sc)
                if want:      # the app scrolls 2.5 s after the link opens
                    br.wait_until(f"Math.abs(document.getElementById('left').scrollTop - {want.group(1)}) < 4 || document.getElementById('left').scrollHeight - document.getElementById('left').clientHeight < {want.group(1)}", timeout=6)
                    br.pump(2.6)
                br.settle(quiet=1.0, timeout=120, busy_expr=BUSY_JS)
                br.pump(0.5)
            else:             # the website: a file in the repository
                br.navigate("file://" + os.path.join(ROOT, sc))
                br.settle(quiet=1.0, timeout=30)
                br.pump(0.5)
            png = br.call("Page.captureScreenshot", {"format": "png"})["data"]
            p = os.path.join(folder, f"screen_{i:02d}.png")
            with open(p, "wb") as f:
                f.write(base64.b64decode(png))
            out[sc] = p
            log(f"  captured {sc} ({time.time() - t0:.1f} s)")
    finally:
        br.close()
    return out


SWIFT = r"""
import AVFoundation
import CoreGraphics
import ImageIO
import Foundation

struct Seg: Decodable { let audio: String; let frames: [String] }
struct Manifest: Decodable { let width: Int; let height: Int; let fps: Int; let pause: Double; let segments: [Seg]; let silent: String; let out: String }

func fail(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(1) }

let args = CommandLine.arguments
guard args.count > 1, let data = FileManager.default.contents(atPath: args[1]), let m = try? JSONDecoder().decode(Manifest.self, from: data) else { fail("usage: assemble manifest.json") }

func pixelBuffer(_ path: String, _ w: Int, _ h: Int) -> CVPixelBuffer {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("cannot read \(path)") }
    var pb: CVPixelBuffer?
    let attrs: [CFString: Any] = [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true]
    CVPixelBufferCreate(kCFAllocatorDefault, w, h, kCVPixelFormatType_32ARGB, attrs as CFDictionary, &pb)
    guard let buf = pb else { fail("no pixel buffer") }
    CVPixelBufferLockBaseAddress(buf, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: w, height: h, bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buf),
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    // top-aligned, full width: a page taller than the frame is cut at the bottom
    let scale = CGFloat(w) / CGFloat(img.width)
    let dh = CGFloat(img.height) * scale
    ctx.draw(img, in: CGRect(x: 0, y: CGFloat(h) - dh, width: CGFloat(w), height: dh))
    CVPixelBufferUnlockBaseAddress(buf, [])
    return buf
}

// 1. durations: each segment lasts as long as its narration plus the pause
var starts: [Double] = [], lengths: [Double] = []
var t = 0.0
for s in m.segments {
    let d = CMTimeGetSeconds(AVURLAsset(url: URL(fileURLWithPath: s.audio)).duration)
    if !(d > 0) { fail("no audio in \(s.audio)") }
    starts.append(t); lengths.append(d + m.pause); t += d + m.pause
}
let total = t

// 2. the picture: still frames at a low rate
let silentURL = URL(fileURLWithPath: m.silent)
try? FileManager.default.removeItem(at: silentURL)
guard let writer = try? AVAssetWriter(outputURL: silentURL, fileType: .mov) else { fail("cannot open the video writer") }
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: m.width, AVVideoHeightKey: m.height,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 900_000, AVVideoMaxKeyFrameIntervalKey: m.fps * 2, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
writer.add(input)
if !writer.startWriting() { fail("video writer: \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)
let scale: Int32 = 600
var frame = 0
for (i, s) in m.segments.enumerated() {
    let per = lengths[i] / Double(max(1, s.frames.count))
    for (j, f) in s.frames.enumerated() {
        let buf = pixelBuffer(f, m.width, m.height)
        let end = j == s.frames.count - 1 ? starts[i] + lengths[i] : starts[i] + Double(j + 1) * per
        while Double(frame) / Double(m.fps) < end - 1e-6 {
            while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.005) }
            if !adaptor.append(buf, withPresentationTime: CMTime(value: CMTimeValue(frame) * CMTimeValue(scale) / CMTimeValue(m.fps), timescale: scale)) { fail("append failed: \(String(describing: writer.error))") }
            frame += 1
        }
    }
}
input.markAsFinished()
writer.endSession(atSourceTime: CMTime(seconds: total, preferredTimescale: scale))
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed { fail("video writer ended with \(writer.status.rawValue): \(String(describing: writer.error))") }

// 3. picture and narration together
let comp = AVMutableComposition()
let video = AVURLAsset(url: silentURL)
guard let vt = video.tracks(withMediaType: .video).first, let cv = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
      let ca = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else { fail("cannot compose") }
do {
    try cv.insertTimeRange(CMTimeRange(start: .zero, duration: video.duration), of: vt, at: .zero)
    for (i, s) in m.segments.enumerated() {
        let a = AVURLAsset(url: URL(fileURLWithPath: s.audio))
        guard let at = a.tracks(withMediaType: .audio).first else { fail("no audio track in \(s.audio)") }
        try ca.insertTimeRange(CMTimeRange(start: .zero, duration: a.duration), of: at, at: CMTime(seconds: starts[i], preferredTimescale: 44100))
    }
} catch { fail("compose: \(error)") }
let outURL = URL(fileURLWithPath: m.out)
try? FileManager.default.removeItem(at: outURL)
// the picture is already H.264 and the narration AAC: copy both as they are
guard let ex = AVAssetExportSession(asset: comp, presetName: AVAssetExportPresetPassthrough) else { fail("no export session") }
ex.outputURL = outURL
ex.outputFileType = .mp4
ex.shouldOptimizeForNetworkUse = true
let sem = DispatchSemaphore(value: 0)
ex.exportAsynchronously { sem.signal() }
sem.wait()
if ex.status != .completed { fail("export ended with \(ex.status.rawValue): \(String(describing: ex.error))") }
print(String(format: "%.1f", total))
"""


def assemble_avfoundation(manifest, folder, log):
    swift = shutil.which("swift") or "/usr/bin/swift"
    if not os.path.exists(swift):
        raise RuntimeError("no ffmpeg on the PATH and no /usr/bin/swift: nothing here can assemble the video")
    src = os.path.join(folder, "assemble.swift")
    with open(src, "w") as f:
        f.write(SWIFT)
    mf = os.path.join(folder, "manifest.json")
    with open(mf, "w") as f:
        json.dump(manifest, f)
    exe = os.path.join(folder, "assemble")
    swiftc = shutil.which("swiftc")
    if swiftc:
        p = subprocess.run([swiftc, "-O", "-swift-version", "5", "-suppress-warnings", "-o", exe, src], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if p.returncode:
            raise RuntimeError("swiftc failed:\n" + p.stdout[-3000:])
        cmd = [exe, mf]
    else:
        cmd = [swift, "-swift-version", "5", "-suppress-warnings", src, mf]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError("assembling with AVFoundation failed:\n" + (p.stderr or p.stdout)[-3000:])
    return float(p.stdout.strip().splitlines()[-1])


def audio_seconds(path):
    p = subprocess.run(["afinfo", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"estimated duration: ([\d.]+) sec", p.stdout)
    if not m:
        raise RuntimeError(f"afinfo could not read {path}")
    return float(m.group(1))


def assemble_ffmpeg(ffmpeg, manifest, folder, log):
    """Stills as a concat list with durations, narration as a concat of the segments padded with silence."""
    total, vlist, alist = 0.0, [], []
    for i, s in enumerate(manifest["segments"]):
        d = audio_seconds(s["audio"]) + manifest["pause"]
        for fr in s["frames"]:
            vlist += [f"file '{fr}'", f"duration {d / len(s['frames']):.3f}"]
        padded = os.path.join(folder, f"pad_{i:02d}.wav")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", s["audio"], "-af", f"apad=pad_dur={manifest['pause']}", "-ar", "44100", "-ac", "1", padded], check=True)
        alist.append(f"file '{padded}'")
        total += d
    vlist.append(vlist[-2])
    vf, af = os.path.join(folder, "v.txt"), os.path.join(folder, "a.txt")
    with open(vf, "w") as f:
        f.write("\n".join(vlist) + "\n")
    with open(af, "w") as f:
        f.write("\n".join(alist) + "\n")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", vf, "-f", "concat", "-safe", "0", "-i", af,
                    "-vf", f"scale={manifest['width']}:{manifest['height']}:force_original_aspect_ratio=increase,crop={manifest['width']}:{manifest['height']}:0:0,fps={manifest['fps']},format=yuv420p",
                    "-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-t", f"{total:.3f}", manifest["out"]], check=True)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8010", help="a running server that holds the Swarm Traces release")
    ap.add_argument("--script", default=SCRIPT)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true", help="compare the script's numbers with the app and stop")
    ap.add_argument("--update-script", action="store_true", help="rewrite the counts sentence in the script from the app's numbers first")
    ap.add_argument("--force", action="store_true", help="build even when a number in the script does not match the app")
    ap.add_argument("--keep", help="keep the screens, narration and work files in this folder")
    a = ap.parse_args(argv)
    t0 = time.time()
    log = lambda s: (sys.stdout.write(s + "\n"), sys.stdout.flush())      # noqa: E731
    if sys.platform != "darwin" or not shutil.which("say"):
        log("demo_video needs macOS (`say` for the narration).")
        return 2
    n = app_numbers(a.base)
    log(f"app at {a.base}: {n['name']}, {n['records']:,} records; {n['messages']} messages, {n['named']} between {n['tokens']} named tokens in {n['pairs']} pairs, "
        f"{n['inside']} inside one estimated agent")
    if a.update_script and update_script(a.script, n):
        log(f"script updated: {claim_sentence(n)}")
    sections = parse_script(a.script)
    probs = check_numbers(sections, n)
    for p in probs:
        log("STALE: " + p)
    if a.check:
        log("script numbers " + ("match the app" if not probs else "do NOT match the app"))
        return 1 if probs else 0
    if probs and not a.force:
        log("not building: fix the script (or run with --update-script), or pass --force")
        return 1
    folder = a.keep or tempfile.mkdtemp(prefix="st-demo-video-")
    os.makedirs(folder, exist_ok=True)
    try:
        log(f"capturing {len({s for sec in sections for s in sec['screens']})} screens at {W}x{H}")
        shots = capture(a.base, [re.sub(r"^the website \((.+)\)$", r"\1", s) if not s.startswith("#") else s for sec in sections for s in sec["screens"]], folder, log)
        segs = []
        for sec in sections:
            aiff = os.path.join(folder, f"seg_{sec['n']:02d}.aiff")
            txt = os.path.join(folder, f"seg_{sec['n']:02d}.txt")
            with open(txt, "w", encoding="utf-8") as f:
                f.write(sec["text"])
            subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", aiff, "-f", txt], check=True)
            audio = aiff
            if not shutil.which("ffmpeg"):      # AVFoundation copies the audio as it is, so make it AAC here
                audio = os.path.join(folder, f"seg_{sec['n']:02d}.m4a")
                subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", aiff, audio], check=True)
            segs.append({"audio": audio, "frames": [shots[s] for s in sec["screens"]]})
            log(f"  narrated {sec['n']}. {sec['title']} ({audio_seconds(aiff):.1f} s, {len(sec['screens'])} screens)")
        tmp_out = os.path.join(folder, "demo.mp4")
        manifest = {"width": W, "height": H, "fps": FPS, "pause": PAUSE, "segments": segs, "silent": os.path.join(folder, "silent.mov"), "out": tmp_out}
        ffmpeg = shutil.which("ffmpeg")
        log("assembling with " + ("ffmpeg" if ffmpeg else "AVFoundation (swift)"))
        total = assemble_ffmpeg(ffmpeg, manifest, folder, log) if ffmpeg else assemble_avfoundation(manifest, folder, log)
        shutil.copyfile(tmp_out, a.out)
        log(f"wrote {os.path.relpath(a.out, ROOT)}: {total:.0f} s ({int(total // 60)} min {int(total % 60)} s), {os.path.getsize(a.out) / 1e6:.1f} MB, built in {time.time() - t0:.0f} s")
        # keep the script's first line in step with the video
        with open(a.script, encoding="utf-8") as f:
            src = f.read()
        new = re.sub(r"\(about \d+ min \d+ s,", f"(about {int(total // 60)} min {int(total % 60)} s,", src, count=1)
        if new != src:
            with open(a.script, "w", encoding="utf-8") as f:
                f.write(new)
    finally:
        if not a.keep:
            shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

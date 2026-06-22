"""Extract authentic Animal Crossing (GameCube) hourly music from the user's own
disc image, using the ACGC PC port's built-in headless BGM dump.

Pipeline per hour:
  port --dump-bgm-hour H out.wav   (real JAudio engine, ~100x realtime, no window)
    -> detect the musical loop period (deterministic-ish render, stdlib only)
    -> trim to one loop with an equal-power crossfade at the seam (seamless loop)
    -> encode to HH-<GAME>-<variant>.mp3 in the timed catalog (MUSIC_DIR/HH/).

Legal note: this renders music from the *user's own* disc for personal use; ac-ui
ships none of it. It requires an already-built ACGC PC port and a disc image.
"""
from __future__ import annotations

import array
import math
import os
import shutil
import subprocess
import wave
from dataclasses import dataclass, field

from ac_ui import diagnostics
from ac_ui.constants import MUSIC_DIR
from ac_ui.importer import ffmpeg_bin

# ── Discovery ───────────────────────────────────────────────────────────────
_PORT_NAMES = ("AnimalCrossing", "AnimalCrossing.exe")
_PORT_HINTS = [
    "~/ACGC-PC-Port/pc/build-linux32/bin",
    "~/ACGC-PC-Port/pc/build-linux64/bin",
    "~/ACGC-PC-Port/pc/build32/bin",
    "~/Downloads/ACGC-PC-Port/pc/build-linux32/bin",
]
_DISC_EXTS = (".iso", ".ciso", ".gcm", ".rvz", ".nkit.iso")


def find_port() -> str | None:
    """Locate the ACGC PC port binary (env override, then common build dirs)."""
    env = os.environ.get("AC_UI_ACGC_PORT")
    if env:
        env = os.path.expanduser(env)
        if os.path.isfile(env):
            return env
    for hint in _PORT_HINTS:
        d = os.path.expanduser(hint)
        for name in _PORT_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def find_disc(port_path: str | None = None) -> str | None:
    """Find an AC disc image: env, the port's rom/ dir, then ~/Downloads."""
    env = os.environ.get("AC_UI_ACGC_ISO")
    if env:
        env = os.path.expanduser(env)
        if os.path.isfile(env):
            return env
    search_dirs = []
    if port_path:
        search_dirs.append(os.path.join(os.path.dirname(port_path), "rom"))
    search_dirs.append(os.path.expanduser("~/Downloads"))
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for root, _dirs, files in os.walk(d):
                for f in sorted(files):
                    low = f.lower()
                    if low.endswith(_DISC_EXTS) and "animal" in low.replace(" ", ""):
                        return os.path.join(root, f)
                # don't descend too deep under Downloads
                if d.endswith("Downloads") and root != d:
                    _dirs[:] = [x for x in _dirs if "animal" in x.lower()]
        except OSError:
            pass
    # second pass: any disc image (even if not named "animal")
    for d in search_dirs:
        if os.path.isdir(d):
            try:
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith(_DISC_EXTS):
                        return os.path.join(d, f)
            except OSError:
                pass
    return None


# ── Rendering ───────────────────────────────────────────────────────────────
def dump_hour(port: str, disc: str, hour: int, wav_path: str, seconds: int = 220) -> None:
    """Render `seconds` of hour `hour`'s BGM to a WAV via the port (headless)."""
    r = subprocess.run(
        [port, "--disc", disc, "--dump-bgm-hour", str(hour), wav_path,
         "--dump-seconds", str(seconds)],
        capture_output=True, text=True, timeout=300,
        cwd=os.path.dirname(port) or None,
    )
    if r.returncode != 0 or not os.path.isfile(wav_path):
        raise RuntimeError((r.stderr or "port dump failed").strip().splitlines()[-1:][0][:200]
                           if (r.stderr or "").strip() else "port produced no WAV")


# ── Loop detection + seamless crossfade (stdlib only) ───────────────────────
@dataclass
class LoopInfo:
    start: int          # loop start sample (per channel)
    period: int         # loop length in samples
    confidence: float   # 0..1 (1 = near-exact repeat)


def _sad(ref, src, off, w, stride=1):
    total = 0
    for i in range(0, w, stride):
        d = ref[i] - src[off + i]
        total += d if d >= 0 else -d
    return total


def detect_loop(left, sr, min_s=12.0, max_s=170.0, anchor_s=2.0) -> LoopInfo | None:
    """Find the loop period by locating where the waveform best repeats after the
    anchor (SAD minimum). Coarse decimated scan, then sample-accurate refine."""
    n = len(left)
    anchor = int(anchor_s * sr)
    w = 4096
    if n < anchor + int(min_s * sr) + w:
        return None
    ref = left[anchor:anchor + w]
    lo = anchor + int(min_s * sr)
    hi = min(anchor + int(max_s * sr), n - w)
    # coarse: step ~20ms, compare every 4th sample
    step = max(1, sr // 50)
    best_off, best_d = lo, None
    off = lo
    while off < hi:
        d = _sad(ref, left, off, w, stride=4)
        if best_d is None or d < best_d:
            best_d, best_off = d, off
        off += step
    # refine ±step at full resolution
    rlo = max(anchor + 1, best_off - step)
    rhi = min(hi, best_off + step)
    best2_off, best2_d = best_off, None
    for off in range(rlo, rhi):
        d = _sad(ref, left, off, w, stride=1)
        if best2_d is None or d < best2_d:
            best2_d, best2_off = d, off
    period = best2_off - anchor
    # confidence: 1 - mean_abs_diff / mean_abs_amplitude
    amp = sum(abs(v) for v in ref) / w or 1.0
    conf = max(0.0, 1.0 - (best2_d / w) / (2.0 * amp))
    return LoopInfo(start=anchor, period=period, confidence=conf)


def write_seamless_loop(in_wav: str, out_wav: str, loop: LoopInfo, fade_s=0.4) -> float:
    """Trim `in_wav` to one loop and crossfade the seam so it loops cleanly.
    Returns the output duration in seconds."""
    w = wave.open(in_wav, "rb")
    ch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
    data = array.array("h")
    data.frombytes(w.readframes(n))
    w.close()
    s, P = loop.start, loop.period
    fade = min(int(fade_s * sr), P // 4, s)
    # Equal-power crossfade: blend the approach-to-loop-end with the pre-loop
    # lead-in so the E->S jump is smooth. Operate per channel on interleaved data.
    for k in range(fade):
        t = (k + 0.5) / fade
        fo = math.cos(t * math.pi / 2)        # fade out loop tail
        fi = math.sin(t * math.pi / 2)        # fade in pre-loop lead
        e = (s + P - fade + k) * ch
        b = (s - fade + k) * ch
        for c in range(ch):
            data[e + c] = int(data[e + c] * fo + data[b + c] * fi)
    seg = data[s * ch:(s + P) * ch]
    out = wave.open(out_wav, "wb")
    out.setnchannels(ch)
    out.setsampwidth(2)
    out.setframerate(sr)
    out.writeframes(seg.tobytes())
    out.close()
    return P / sr


def _encode_mp3(wav_path: str, mp3_path: str) -> None:
    fm = ffmpeg_bin()
    if not fm:
        raise RuntimeError("ffmpeg not found (needed to encode mp3)")
    tmp = mp3_path + ".part"
    r = subprocess.run(
        [fm, "-v", "error", "-y", "-i", wav_path, "-codec:a", "libmp3lame",
         "-q:a", "2", "-f", "mp3", tmp],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ffmpeg failed").strip().splitlines()[-1][:200])
    os.replace(tmp, mp3_path)


# ── Orchestration ───────────────────────────────────────────────────────────
@dataclass
class ExtractResult:
    done: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)
    tracks: list = field(default_factory=list)     # (hour, mp3_path, loop_seconds, conf)


def extract_hour(port, disc, hour, *, game="ACGC", variant="hourly",
                 seconds=220, tmp_dir=None) -> tuple:
    """Render + loop + encode one hour. Returns (mp3_path, loop_seconds, conf)."""
    import tempfile
    tmp_dir = tmp_dir or tempfile.gettempdir()
    raw = os.path.join(tmp_dir, f"acgc_raw_{hour:02d}.wav")
    loopw = os.path.join(tmp_dir, f"acgc_loop_{hour:02d}.wav")
    try:
        dump_hour(port, disc, hour, raw, seconds=seconds)
        w = wave.open(raw, "rb")
        chn, sr, nf = w.getnchannels(), w.getframerate(), w.getnframes()
        d = array.array("h")
        d.frombytes(w.readframes(nf))
        w.close()
        left = d[0::chn]
        loop = detect_loop(left, sr)
        if loop and loop.confidence >= 0.55 and loop.period > sr * 8:
            secs = write_seamless_loop(raw, loopw, loop)
            src_wav, conf = loopw, loop.confidence
        else:
            # Detection unsure: keep the full render (player still loops the file).
            src_wav, secs, conf = raw, nf / sr, (loop.confidence if loop else 0.0)
        hh = f"{hour:02d}"
        dest_dir = os.path.join(MUSIC_DIR, hh)
        os.makedirs(dest_dir, exist_ok=True)
        mp3 = os.path.join(dest_dir, f"{hh}-{game}-{variant}.mp3")
        _encode_mp3(src_wav, mp3)
        return mp3, secs, conf
    finally:
        for p in (raw, loopw):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


def extract_catalog(port, disc, hours=None, *, game="ACGC", variant="hourly",
                    seconds=220, progress_cb=None, should_cancel=None) -> ExtractResult:
    """Extract a set of hours (default all 24) into the timed catalog."""
    from ac_ui.tracks import invalidate_track_cache
    hours = list(range(24)) if hours is None else list(hours)
    res = ExtractResult()
    total = len(hours)
    for i, h in enumerate(hours):
        if should_cancel and should_cancel():
            break
        if progress_cb:
            try:
                progress_cb(i, total, h)
            except Exception:
                pass
        try:
            mp3, secs, conf = extract_hour(port, disc, h, game=game,
                                           variant=variant, seconds=seconds)
            invalidate_track_cache(h)
            res.done += 1
            res.tracks.append((h, mp3, secs, conf))
        except Exception as exc:
            res.failed += 1
            res.errors.append(f"hour {h:02d}: {exc}")
            diagnostics.warn("acgc_extract", f"hour {h} failed", exc=exc)
    if progress_cb:
        try:
            progress_cb(total, total, None)
        except Exception:
            pass
    return res


class BackgroundExtract:
    """Run extract_catalog on a daemon thread with a thread-safe snapshot, for
    the in-app wizard (the visualizer/audio keep ticking while it renders)."""

    def __init__(self, port, disc, hours=None, *, game="ACGC", variant="hourly",
                 seconds=220):
        import threading
        self._port, self._disc, self._hours = port, disc, hours
        self._game, self._variant, self._seconds = game, variant, seconds
        self._lock = threading.Lock()
        self._threading = threading
        self._idx = 0
        self._total = 24 if hours is None else len(hours)
        self._cur = -1
        self._result = None
        self._cancel = False
        self._thread = None

    def start(self):
        self._thread = self._threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        def cb(done, total, h):
            with self._lock:
                self._idx = done
                self._total = total
                if h is not None:
                    self._cur = h
        try:
            res = extract_catalog(self._port, self._disc, self._hours,
                                  game=self._game, variant=self._variant,
                                  seconds=self._seconds, progress_cb=cb,
                                  should_cancel=lambda: self._cancel)
        except Exception as exc:                       # never kill the UI thread
            res = ExtractResult()
            res.failed = 1
            res.errors = [str(exc)]
        with self._lock:
            self._result = res

    def cancel(self):
        self._cancel = True

    def snapshot(self):
        with self._lock:
            return {"idx": self._idx, "total": self._total, "cur": self._cur,
                    "result": self._result}


_CLI_USAGE = """\
ac-ui extract-ac — extract authentic AC GameCube hourly music from your own disc.

Requires a built ACGC PC port and an AC disc image (auto-detected, or set
AC_UI_ACGC_PORT / AC_UI_ACGC_ISO). Renders each hour, finds the loop, crossfades a
seamless loop, and writes HH-<GAME>-<VARIANT>.mp3 into the timed catalog.

Options:
  --hours 0,8,12     only these hours (default: all 24)
  --variant NAME     variant name (default: hourly)
  --game TAG         catalog game tag (default: ACGC)
  --seconds N        render length to search for the loop (default: 220)
"""


def extract_ac_cli(args=None) -> int:
    args = list(args or [])
    game, variant, seconds, hours = "ACGC", "hourly", 220, None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--help", "-h"):
            print(_CLI_USAGE)
            return 0
        if a == "--seconds" and i + 1 < len(args):
            seconds = int(args[i + 1]); i += 1
        elif a == "--variant" and i + 1 < len(args):
            variant = args[i + 1]; i += 1
        elif a == "--game" and i + 1 < len(args):
            game = args[i + 1]; i += 1
        elif a == "--hours" and i + 1 < len(args):
            hours = [int(x) for x in args[i + 1].split(",") if x.strip()]; i += 1
        i += 1

    port = find_port()
    if not port:
        print("Could not find the ACGC PC port binary.")
        print("Build it (ACreTeam/ac-decomp + ACGC-PC-Port) or set "
              "AC_UI_ACGC_PORT=/path/to/AnimalCrossing")
        return 1
    disc = find_disc(port)
    if not disc:
        print("Could not find an AC disc image.")
        print("Put your disc in the port's rom/ folder or set "
              "AC_UI_ACGC_ISO=/path/to/disc.iso")
        return 1
    n = 24 if hours is None else len(hours)
    print(f"Port: {port}")
    print(f"Disc: {disc}")
    print(f"Extracting {n} hour(s) -> {game}/{variant} (seamless loops)…\n")

    def cb(done, total, h):
        if h is not None:
            print(f"  [{done + 1:2d}/{total}] hour {h:02d} …", flush=True)

    res = extract_catalog(port, disc, hours, game=game, variant=variant,
                          seconds=seconds, progress_cb=cb)
    print(f"\nDone: {res.done} track(s) written, {res.failed} failed.")
    for e in res.errors[:8]:
        print("  !", e)
    if res.tracks:
        avg = sum(t[2] for t in res.tracks) / len(res.tracks)
        print(f"  avg loop ~{avg:.0f}s  →  {os.path.join(MUSIC_DIR, 'HH', f'HH-{game}-{variant}.mp3')}")
        print("  Tip: filter to them in-app, or they'll play at the matching hour.")
    return 0 if res.done else 1


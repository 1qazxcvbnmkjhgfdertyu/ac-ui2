"""ACGC extraction: discovery, loop detection, seamless crossfade, CLI guards.
Uses synthetic audio — never runs the real port."""
import array
import math
import os
import random
import wave

from ac_ui import acgc_extract as X


def _looping_left(sr, period_s, reps, seed=1234):
    """A genuinely seamless loop: a rich waveform built from harmonics of the loop
    frequency (fundamental included, so the smallest period IS period_s and the
    end connects smoothly to the start — like real looping music). Tiled `reps`x;
    the loop's own previous iteration serves as the lead-in (anchor at seg 2)."""
    P = int(period_s * sr)
    rnd = random.Random(seed)
    harm = [(k, rnd.uniform(0.2, 1.0) / k, rnd.uniform(0, 6.283)) for k in range(1, 16)]
    norm = sum(a for _k, a, _p in harm)
    seg = array.array("h")
    for i in range(P):
        ph = i / P
        v = sum(a * math.sin(2 * math.pi * k * ph + p) for k, a, p in harm) / norm
        seg.append(int(max(-1.0, min(1.0, v)) * 20000))
    out = array.array("h")
    for _ in range(reps):
        out.extend(seg)
    return out, P


def test_find_port_and_disc_env(tmp_path, monkeypatch):
    port = tmp_path / "AnimalCrossing"
    port.write_text("#!/bin/sh\n")
    os.chmod(port, 0o755)
    disc = tmp_path / "game.iso"
    disc.write_bytes(b"\0" * 16)
    monkeypatch.setenv("AC_UI_ACGC_PORT", str(port))
    monkeypatch.setenv("AC_UI_ACGC_ISO", str(disc))
    assert X.find_port() == str(port)
    assert X.find_disc() == str(disc)


def test_detect_loop_finds_period():
    sr = 8000
    left, P = _looping_left(sr, period_s=5.0, reps=3)
    loop = X.detect_loop(left, sr, min_s=3.0, max_s=8.0, anchor_s=5.0)
    assert loop is not None
    # within ~30ms of the true period, and confident (near-exact repeat)
    assert abs(loop.period - P) < 0.03 * sr
    assert loop.confidence > 0.8


def test_seamless_loop_low_discontinuity(tmp_path):
    sr = 8000
    left, P = _looping_left(sr, period_s=5.0, reps=3)
    # stereo interleaved (duplicate L to R)
    inter = array.array("h")
    for v in left:
        inter.append(v); inter.append(v)
    src = tmp_path / "in.wav"
    w = wave.open(str(src), "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(inter.tobytes()); w.close()

    loop = X.detect_loop(left, sr, min_s=3.0, max_s=8.0, anchor_s=5.0)
    out = tmp_path / "loop.wav"
    secs = X.write_seamless_loop(str(src), str(out), loop)
    assert abs(secs - 5.0) < 0.05

    w2 = wave.open(str(out), "rb")
    d = array.array("h"); d.frombytes(w2.readframes(w2.getnframes())); w2.close()
    L = d[0::2]
    rms = (sum(v * v for v in L[:2000]) / 2000) ** 0.5
    wrap = abs(L[-1] - L[0])
    assert wrap < 0.1 * rms          # seam is essentially seamless


def test_cli_missing_port_is_graceful(monkeypatch, capsys):
    monkeypatch.setattr(X, "find_port", lambda: None)
    rc = X.extract_ac_cli([])
    assert rc == 1
    assert "port" in capsys.readouterr().out.lower()


def test_cli_help(capsys):
    assert X.extract_ac_cli(["--help"]) == 0
    assert "extract-ac" in capsys.readouterr().out

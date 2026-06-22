#!/usr/bin/env python3
"""End-to-end kaleido_tunnel benchmark: cached warp map vs per-frame transform.

Drives the REAL kaleido_tunnel_render_lines with music-like time-varying audio,
sweeps the regen policy (K ceiling + drift threshold), and reports:
  - mean ms/frame (lower is better)
  - warp-map regen rate (regens / frame -> effective K)
  - visual divergence vs the uncached reference (mean fraction of chars that
    differ, run in lockstep from the same audio) so we can see the quality cost.
"""
import math
import time

from ac_ui import visualizer as V


def music_bars(n, t):
    """Pseudo-music spectrum: bass thump on the beat + mids/treble shimmer."""
    beat = (t * 2.0) % 1.0          # 120 BPM-ish
    kick = math.exp(-beat * 6.0)    # sharp decay each beat
    out = []
    for j in range(n):
        f = j / max(1, n - 1)
        bass = kick * math.exp(-f * 5.0) * 0.9
        mids = (0.3 + 0.2 * math.sin(t * 1.3 + f * 8.0)) * math.exp(-abs(f - 0.4) * 4.0)
        treb = (0.2 + 0.15 * math.sin(t * 5.0 + f * 20.0)) * f * 0.6
        out.append(max(0.0, min(1.0, bass + mids + treb)))
    return tuple(out)


def render_run(h, w, frames, *, cache, kmax=8, thresh=0.012, fps=60.0):
    V._WARP_CACHE = cache
    if cache:
        V._WARP_CACHE_KMAX = kmax
        V._WARP_CACHE_THRESH = thresh
    st = {}
    dt = 1.0 / fps
    lines_seq = []
    times = []
    for i in range(frames):
        bars = music_bars(w, i * dt)
        t0 = time.perf_counter()
        lines = V.kaleido_tunnel_render_lines(bars, h, w, st, use_color=True, game_tag=None)
        elapsed = time.perf_counter() - t0
        if i >= 20:                 # warmup
            times.append(elapsed)
        lines_seq.append(lines)
    times.sort()
    mean_ms = (sum(times) / len(times)) * 1000.0
    med_ms = times[len(times) // 2] * 1000.0
    regens = st.get("_warp_regens", 0)
    return mean_ms, med_ms, regens, lines_seq


def char_diff(a_seq, b_seq):
    """Mean fraction of differing characters across the lockstep frame seqs."""
    total = 0
    diff = 0
    for fa, fb in zip(a_seq, b_seq):
        for la, lb in zip(fa, fb):
            n = min(len(la), len(lb))
            total += max(len(la), len(lb))
            diff += sum(1 for k in range(n) if la[k] != lb[k])
            diff += abs(len(la) - len(lb))
    return diff / max(1, total)


def run(h, w, frames=240):
    print(f"\n=== kaleido_tunnel {h}x{w}, {frames} frames @60fps ===")
    base_mean, base_med, _, base_lines = render_run(h, w, frames, cache=False)
    print(f"  cache OFF (current): mean {base_mean:.3f} ms  median {base_med:.3f} ms")
    print(f"  {'policy':>18} {'mean ms':>8} {'med ms':>7} {'speedup':>8} "
          f"{'eff.K':>6} {'visual diff':>11}")
    for kmax, thresh in [(4, 0.012), (8, 0.012), (8, 0.020), (16, 0.020),
                         (16, 0.035), (32, 0.05)]:
        mean_ms, med_ms, regens, lines = render_run(
            h, w, frames, cache=True, kmax=kmax, thresh=thresh)
        eff_k = frames / max(1, regens)
        vdiff = char_diff(base_lines, lines)
        print(f"  K<={kmax:<3} d<={thresh:<5}  {mean_ms:8.3f} {med_ms:7.3f} "
              f"{base_mean/mean_ms:7.2f}x {eff_k:6.1f} {vdiff*100:9.2f} %")


if __name__ == "__main__":
    for h, w in [(18, 96), (30, 160), (40, 220)]:
        run(h, w)

#!/usr/bin/env python3
"""Sweep the warp-cache regen policy (drift threshold, K ceiling, build spread)
at fullscreen size and report mean / median / p95 ms and effective K, so we can
pick the smoothest low-CPU configuration."""
import time

from ac_ui import visualizer as V
from bench_warp_e2e import music_bars


def run(h, w, frames, *, cache, kmax=16, thresh=0.02, build_frames=6, fps=60.0):
    V._WARP_CACHE = cache
    if cache:
        V._WARP_CACHE_KMAX = kmax
        V._WARP_CACHE_THRESH = thresh
        V._WARP_BUILD_FRAMES = build_frames
    st = {}
    dt = 1.0 / fps
    times = []
    for i in range(frames):
        bars = music_bars(w, i * dt)
        t0 = time.perf_counter()
        V.kaleido_tunnel_render_lines(bars, h, w, st, use_color=True, game_tag=None)
        if i >= 20:
            times.append(time.perf_counter() - t0)
    times.sort()
    mean = sum(times) / len(times) * 1000
    med = times[len(times) // 2] * 1000
    p95 = times[int(len(times) * 0.95)] * 1000
    return mean, med, p95, st.get("_warp_regens", 0)


def main():
    h, w = 40, 220
    frames = 300
    base = run(h, w, frames, cache=False)
    print(f"\n=== kaleido_tunnel {h}x{w} ({frames} frames) ===")
    print(f"cache OFF: mean {base[0]:.2f}  med {base[1]:.2f}  p95 {base[2]:.2f} ms")
    print(f"{'thresh':>7}{'kmax':>5}{'bf':>4}  {'mean':>6}{'med':>7}{'p95':>7}"
          f"{'spd':>6}{'effK':>6}")
    for thresh in (0.012, 0.02, 0.035, 0.06):
        for build_frames in (4, 8, 12):
            mean, med, p95, regens = run(
                h, w, frames, cache=True, kmax=16, thresh=thresh,
                build_frames=build_frames)
            effk = frames / max(1, regens)
            print(f"{thresh:>7}{16:>5}{build_frames:>4}  {mean:6.2f}{med:7.2f}"
                  f"{p95:7.2f}{base[0]/mean:5.2f}x{effk:6.1f}")


if __name__ == "__main__":
    main()

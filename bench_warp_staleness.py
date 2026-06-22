#!/usr/bin/env python3
"""Isolated per-frame staleness error of the cached warp map.

Runs the real cached kaleido loop, but at each frame also computes what the
FULL per-frame transform would produce from the SAME current source field, and
compares the two intensity fields directly. This isolates warp staleness from
the cumulative recursive divergence that makes a lockstep char-diff misleading.
"""
import math
from array import array

from ac_ui import _vizfast
from ac_ui import visualizer as V
from bench_warp_e2e import music_bars


def run(h, w, frames=240, kmax=16, thresh=0.035, fps=60.0):
    V._WARP_CACHE = True
    V._WARP_CACHE_KMAX = kmax
    V._WARP_CACHE_THRESH = thresh
    dot_rows, dot_cols = h * 4, w * 2
    size = dot_rows * dot_cols
    st = {}
    dt = 1.0 / fps

    ref_i = array("f", [0.0]) * size
    ref_h = bytearray([50]) * size

    max_rel = 0.0
    sum_rel = 0.0
    sum_lit_mismatch = 0.0
    count = 0

    # We need the params used each frame; re-derive them the way the renderer
    # does by wrapping _feedback_transform to capture its kwargs.
    captured = {}
    orig = V._feedback_transform

    def spy(state, dr, dc, **kw):
        if dr == dot_rows:
            captured.clear()
            captured.update(kw)
        return orig(state, dr, dc, **kw)

    V._feedback_transform = spy
    try:
        for i in range(frames):
            bars = music_bars(w, i * dt)
            V.kaleido_tunnel_render_lines(bars, h, w, st, use_color=True, game_tag=None)
            if i < 25 or not captured:
                continue
            # Current source field the gather just read from.
            src_i, src_h, _o, _o2 = V._feedback_buffers(st, dot_rows, dot_cols)
            # Skip if not packed (native off).
            if isinstance(src_i, list):
                return
            kw = captured
            _vizfast.feedback_transform_into_buf(
                src_i, src_h, ref_i, ref_h, dot_rows, dot_cols,
                kw["decay"], kw["zoom"], kw["rot"], kw["drift_x"], kw["drift_y"],
                kw["hue_shift"], int(kw.get("mirror", 0)), kw["swirl"], kw["pinch"],
                kw["warp_amp"], kw["warp_freq"], kw["warp_phase"],
            )
            # Cached gather output is the active stored field.
            cur_i, cur_h, _a, _b = V._feedback_buffers(st, dot_rows, dot_cols)
            # cur is the NEXT source (just stored); compare to ref.
            num = 0.0
            den = 0.0
            litmis = 0
            for a, b in zip(ref_i, cur_i):
                num += abs(a - b)
                den += a
                if (a > 0.05) != (b > 0.05):
                    litmis += 1
            rel = num / max(1e-6, den)
            max_rel = max(max_rel, rel)
            sum_rel += rel
            sum_lit_mismatch += litmis / size
            count += 1
    finally:
        V._feedback_transform = orig

    print(f"  {h}x{w} K<={kmax} d<={thresh}: "
          f"mean staleness {100*sum_rel/max(1,count):.2f}%  "
          f"max {100*max_rel:.2f}%  "
          f"lit-pixel mismatch {100*sum_lit_mismatch/max(1,count):.2f}%")


if __name__ == "__main__":
    print("Per-frame warp staleness (cached vs full-from-same-source):")
    for h, w in [(18, 96), (40, 220)]:
        for kmax, thresh in [(8, 0.012), (16, 0.035), (32, 0.05)]:
            run(h, w, kmax=kmax, thresh=thresh)

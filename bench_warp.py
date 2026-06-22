#!/usr/bin/env python3
"""Prototype benchmark: Geiss-style cached warp map vs per-frame feedback transform.

Times the current native `feedback_transform_into_buf` (full per-frame trig)
against `build_warp_map_buf` (trig once) + `feedback_gather_buf` (cheap gather),
verifies bit-parity, and reports the effective ms/frame when the warp map is
regenerated once every K frames.
"""
import time
from array import array

from ac_ui import _vizfast
from ac_ui import visualizer as V


def median_ms(fn, runs=200, warmup=20):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    ts.sort()
    return ts[len(ts) // 2] * 1000.0


def warm_state(h, w, frames=40):
    """Render real kaleido frames so the feedback field holds live data."""
    st = {}
    import math
    for i in range(frames):
        bars = tuple(
            0.3 + 0.3 * math.sin(i * 0.1 + j * 0.2) + 0.2 * math.sin(i * 0.05 + j)
            for j in range(w)
        )
        V.kaleido_tunnel_render_lines(bars, h, w, st, use_color=True, game_tag=None)
    return st


# Representative kaleido warp params (mid-level audio).
PARAMS = dict(
    decay=0.93, zoom=1.04, rot=0.03, drift_x=0.012, drift_y=-0.008,
    hue_shift=2.0, mirror=6, swirl=0.28, pinch=0.18,
    warp_amp=0.03, warp_freq=5.0, warp_phase=1.7,
)


def run(h, w):
    dot_rows, dot_cols = h * 4, w * 2
    size = dot_rows * dot_cols
    st = warm_state(h, w)
    # Pull the live source buffers (active feedback field).
    src_inten, src_hue, _o_i, _o_h = V._feedback_buffers(st, dot_rows, dot_cols)
    # Ensure packed types.
    if not isinstance(src_inten, array):
        src_inten = array("f", src_inten)
        src_hue = bytearray(src_hue)

    p = PARAMS
    out_full_i = array("f", [0.0]) * size
    out_full_h = bytearray([50]) * size
    out_cach_i = array("f", [0.0]) * size
    out_cach_h = bytearray([50]) * size
    warp_idx = array("i", [-1]) * size

    def full():
        _vizfast.feedback_transform_into_buf(
            src_inten, src_hue, out_full_i, out_full_h, dot_rows, dot_cols,
            p["decay"], p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
            p["hue_shift"], p["mirror"], p["swirl"], p["pinch"],
            p["warp_amp"], p["warp_freq"], p["warp_phase"],
        )

    def build():
        _vizfast.build_warp_map_buf(
            warp_idx, dot_rows, dot_cols,
            p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
            p["mirror"], p["swirl"], p["pinch"],
            p["warp_amp"], p["warp_freq"], p["warp_phase"],
        )

    def gather():
        _vizfast.feedback_gather_buf(
            src_inten, src_hue, out_cach_i, out_cach_h, warp_idx, size,
            p["decay"], p["hue_shift"],
        )

    # Parity: full vs build+gather on the same source must be bit-identical.
    full()
    build()
    gather()
    di = sum(1 for a, b in zip(out_full_i, out_cach_i) if a != b)
    dh = sum(1 for a, b in zip(out_full_h, out_cach_h)
             if (a if a > 0.0 else 0) and b)  # placeholder
    dh = sum(1 for a, b in zip(out_full_h, out_cach_h) if a != b)
    lit = sum(1 for v in out_full_i if v > 0.0)

    ms_full = median_ms(full)
    ms_build = median_ms(build)
    ms_gather = median_ms(gather)

    print(f"\n=== {h}x{w}  (dot grid {dot_rows}x{dot_cols} = {size} px) ===")
    print(f"  lit pixels: {lit}/{size}  ({100*lit/size:.1f}%)")
    print(f"  parity intensity diffs: {di}   hue diffs: {dh}  (want 0)")
    print(f"  full transform : {ms_full:.3f} ms/frame")
    print(f"  build warp map : {ms_build:.3f} ms")
    print(f"  gather only    : {ms_gather:.3f} ms/frame")
    print(f"  effective ms/frame = (build + K*gather)/K:")
    for K in (1, 2, 4, 8, 16):
        eff = (ms_build + K * ms_gather) / K
        speed = ms_full / eff
        print(f"     K={K:2d}: {eff:.3f} ms   ({speed:.2f}x vs full)")


if __name__ == "__main__":
    for h, w in [(18, 96), (30, 160), (40, 220)]:
        run(h, w)

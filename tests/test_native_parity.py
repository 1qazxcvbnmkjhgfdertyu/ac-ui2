"""The compiled feedback path (ac_ui._vizfast) must match the pure-Python one.

Skipped automatically when the native module isn't built. -ffast-math allows
tiny float reorderings, so we assert closeness + matching structure rather than
bit-identical output.
"""
import math

import pytest

import ac_ui.visualizer as V


def _seed_state(h=12, w=40, frames=6):
    """Run a few kaleido frames so the feedback buffer is populated."""
    state = {}
    for f in range(frames):
        bars = [min(1.0, abs(math.sin(i * 0.3 + f * 0.5))) for i in range(32)]
        V.kaleido_tunnel_render_lines(bars, h, w, state, use_color=False)
    return state


@pytest.mark.skipif(V._vizfast is None, reason="native module not built")
def test_native_feedback_matches_pure_python(monkeypatch):
    h, w = 12, 40
    dot_rows, dot_cols = h * 4, w * 2
    src_i = [0.0] * (dot_rows * dot_cols)
    # A deterministic, structured source field.
    for y in range(dot_rows):
        for x in range(dot_cols):
            src_i[y * dot_cols + x] = abs(math.sin(x * 0.2) * math.cos(y * 0.15))
    src_h = [(x + y) % 101 for y in range(dot_rows) for x in range(dot_cols)]

    params = dict(decay=0.9, zoom=1.012, rot=0.02, drift_x=0.01, drift_y=-0.008,
                  hue_shift=1.4, mirror=5, swirl=0.2, pinch=0.3,
                  warp_amp=0.03, warp_freq=5.0, warp_phase=0.7)

    native_i, native_h = V._vizfast.feedback_transform(
        list(src_i), list(src_h), dot_rows, dot_cols,
        params["decay"], params["zoom"], params["rot"], params["drift_x"],
        params["drift_y"], params["hue_shift"], params["mirror"], params["swirl"],
        params["pinch"], params["warp_amp"], params["warp_freq"], params["warp_phase"],
    )

    # Force the pure-Python path and run the same transform.
    monkeypatch.setattr(V, "_vizfast", None)
    state = {"fb_inten": list(src_i), "fb_hue": list(src_h),
             "fb_rows": dot_rows, "fb_cols": dot_cols}
    pure_i, pure_h = V._feedback_transform(state, dot_rows, dot_cols, **params)

    assert len(native_i) == len(pure_i) == dot_rows * dot_cols

    # Per-pixel intensities agree closely; allow a handful of threshold-boundary
    # pixels to differ (a value sitting right on the 0.01 cutoff).
    near = sum(1 for a, b in zip(native_i, pure_i) if abs(a - b) < 1e-4)
    total = len(native_i)
    assert near >= total - max(3, total // 1000), f"{total - near} pixels diverged"

    # Lit-pixel counts (the visible structure) match within ~1%.
    lit_n = sum(1 for v in native_i if v > 0.01)
    lit_p = sum(1 for v in pure_i if v > 0.01)
    assert abs(lit_n - lit_p) <= max(3, total // 100)


@pytest.mark.skipif(V._vizfast is None, reason="native module not built")
def test_native_output_well_formed():
    out_i, out_h = V._vizfast.feedback_transform(
        [0.5] * 32, [40] * 32, 8, 4, 0.9, 1.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 6.0, 0.0
    )
    assert len(out_i) == 32 and len(out_h) == 32
    assert all(0.0 <= v <= 1.0 for v in out_i)

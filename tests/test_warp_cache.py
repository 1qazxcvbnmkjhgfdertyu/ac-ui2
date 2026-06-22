"""The Geiss-style cached warp map (build_warp_map_buf + feedback_gather_buf)
must produce byte-identical output to the per-frame feedback_transform_into_buf,
and an incremental row-banded build must equal a single full build."""
import math
from array import array

import pytest

_vizfast = pytest.importorskip("ac_ui._vizfast")

if not (hasattr(_vizfast, "build_warp_map_buf")
        and hasattr(_vizfast, "feedback_gather_buf")
        and hasattr(_vizfast, "feedback_transform_into_buf")):
    pytest.skip("warp-cache native helpers not built", allow_module_level=True)


def _seed_field(dot_rows, dot_cols):
    size = dot_rows * dot_cols
    inten = array("f", [0.0]) * size
    hue = bytearray([50]) * size
    for y in range(dot_rows):
        for x in range(dot_cols):
            i = y * dot_cols + x
            inten[i] = max(0.0, math.sin(x * 0.3) * math.cos(y * 0.2))
            hue[i] = (x + y) % 101
    return inten, hue


PARAMS = dict(
    decay=0.93, zoom=1.04, rot=0.03, drift_x=0.012, drift_y=-0.008,
    hue_shift=2.0, mirror=6, swirl=0.28, pinch=0.18,
    warp_amp=0.03, warp_freq=5.0, warp_phase=1.7,
)


@pytest.mark.parametrize("dot_rows,dot_cols", [(24, 40), (40, 72)])
def test_cached_warp_matches_full_transform(dot_rows, dot_cols):
    size = dot_rows * dot_cols
    src_i, src_h = _seed_field(dot_rows, dot_cols)
    p = PARAMS

    ref_i = array("f", [0.0]) * size
    ref_h = bytearray([50]) * size
    _vizfast.feedback_transform_into_buf(
        src_i, src_h, ref_i, ref_h, dot_rows, dot_cols,
        p["decay"], p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
        p["hue_shift"], p["mirror"], p["swirl"], p["pinch"],
        p["warp_amp"], p["warp_freq"], p["warp_phase"],
    )

    warp = array("i", [-1]) * size
    _vizfast.build_warp_map_buf(
        warp, dot_rows, dot_cols,
        p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
        p["mirror"], p["swirl"], p["pinch"],
        p["warp_amp"], p["warp_freq"], p["warp_phase"],
    )
    out_i = array("f", [0.0]) * size
    out_h = bytearray([50]) * size
    _vizfast.feedback_gather_buf(src_i, src_h, out_i, out_h, warp, size,
                                 p["decay"], p["hue_shift"])

    assert list(out_i) == list(ref_i)
    # Hue is only meaningful where intensity survives the cutoff.
    for i in range(size):
        if ref_i[i] > 0.0:
            assert out_h[i] == ref_h[i]


@pytest.mark.parametrize("v_dots", [4, 2, 1])
def test_braille_field_native_matches_pure(v_dots):
    """The native braille emitter must match the pure-Python one for both the
    full and reduced vertical field layouts."""
    import ac_ui.visualizer as V
    from ac_ui.colors import RESET

    if not hasattr(_vizfast, "braille_field_buf"):
        pytest.skip("braille_field_buf not built")
    h, w = 20, 60
    dr, dc = h * v_dots, w * 2
    size = dr * dc
    inten = array("f", [0.0]) * size
    hue = bytearray([50]) * size
    for i in range(size):
        inten[i] = max(0.0, math.sin(i * 0.05))
        hue[i] = i % 101
    grad = V._gradient_for(None)
    esc = V._gradient_escape_lut(grad)
    esc_b = V._gradient_escape_lut(grad, bold=True)
    native = _vizfast.braille_field_buf(
        inten, hue, dr, dc, h, w, esc, esc_b, True, 0.05,
        V._BRAILLE_HOT_THRESHOLD, RESET, v_dots)
    pure = V._braille_field_py(
        list(inten), list(hue), dr, dc, h, w, grad, use_color=True,
        threshold=0.05, esc=esc, esc_bold=esc_b, field_v_dots=v_dots)
    assert native == pure


def test_incremental_build_equals_full_build():
    dot_rows, dot_cols = 40, 72
    size = dot_rows * dot_cols
    p = PARAMS
    full = array("i", [-1]) * size
    _vizfast.build_warp_map_buf(
        full, dot_rows, dot_cols,
        p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
        p["mirror"], p["swirl"], p["pinch"],
        p["warp_amp"], p["warp_freq"], p["warp_phase"],
    )
    inc = array("i", [-1]) * size
    band = 7
    for r0 in range(0, dot_rows, band):
        _vizfast.build_warp_map_buf(
            inc, dot_rows, dot_cols,
            p["zoom"], p["rot"], p["drift_x"], p["drift_y"],
            p["mirror"], p["swirl"], p["pinch"],
            p["warp_amp"], p["warp_freq"], p["warp_phase"],
            r0, min(dot_rows, r0 + band),
        )
    assert list(inc) == list(full)

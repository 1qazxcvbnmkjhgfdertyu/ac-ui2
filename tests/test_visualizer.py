"""Tests for the theatrical / beat-reactive visualizer renderers.

Every renderer must return exactly `height` lines, each exactly `width` visible
columns wide (after stripping color), for any input — including silence, full
energy, odd sizes, and many animation frames.
"""
from array import array
import math

import pytest

from ac_ui import audio_snapshot as AS
from ac_ui.audio_snapshot import build_audio_snapshot
from ac_ui.colors import strip_ansi
from ac_ui import visualizer as V


THEATRICAL = [
    ("fireworks", V.fireworks_render_lines),
    ("starfield", V.starfield_render_lines),
    ("ripple", V.ripple_render_lines),
    ("aurora", V.aurora_render_lines),
    ("kaleido_tunnel", V.kaleido_tunnel_render_lines),
    ("liquid_scope", V.liquid_scope_render_lines),
    ("plasma_bloom", V.plasma_bloom_render_lines),
    ("milkdrop", V.milkdrop_render_lines),
    ("polar", V.polar_spectrum_render_lines),
    ("chroma", V.chroma_wheel_render_lines),
]


def _loud_bars(n=32, t=0.0):
    # A moving spectrum with a strong, pulsing bass so beats trigger.
    return [min(1.0, abs(math.sin(i * 0.3 + t)) * (1.0 if i > 4 else 1.0))
            for i in range(n)]


@pytest.mark.parametrize("name,fn", THEATRICAL)
@pytest.mark.parametrize("w,h", [(40, 8), (80, 12), (17, 5), (120, 20)])
def test_renderer_dimensions(name, fn, w, h):
    state = {}
    # Drive many frames with a pulsing signal so particles spawn, move and die.
    for f in range(60):
        bars = _loud_bars(32, t=f * 0.5)
        lines = fn(bars, h, w, state, use_color=False, game_tag=None)
        assert len(lines) == h, f"{name}: expected {h} lines, got {len(lines)}"
        for ln in lines:
            assert len(ln) == w, f"{name}: line width {len(ln)} != {w}"


@pytest.mark.parametrize("name,fn", THEATRICAL)
def test_renderer_color_width(name, fn):
    state = {}
    w, h = 60, 10
    for f in range(30):
        bars = _loud_bars(32, t=f * 0.4)
        lines = fn(bars, h, w, state, use_color=True, game_tag=None)
        assert len(lines) == h
        for ln in lines:
            assert len(strip_ansi(ln)) == w, f"{name}: visible width mismatch"


@pytest.mark.parametrize("name,fn", THEATRICAL)
def test_renderer_silence_and_empty(name, fn):
    state = {}
    # All-zero bars (silence) and empty bars must not crash and keep the frame size.
    for bars in ([0.0] * 32, []):
        lines = fn(bars, 8, 40, state, use_color=True, game_tag=None)
        assert len(lines) == 8
        for ln in lines:
            assert len(strip_ansi(ln)) == 40


@pytest.mark.parametrize("name,fn", THEATRICAL)
def test_renderer_zero_size(name, fn):
    # Degenerate sizes return a safe non-empty frame rather than raising.
    out = fn(_loud_bars(), 0, 0, {}, use_color=True)
    assert isinstance(out, list) and out


def test_fireworks_spawns_particles_on_beat():
    state = {}
    # Alternate loud/quiet bass to create rising edges (onsets) → launches.
    for f in range(40):
        bass = 1.0 if f % 4 == 0 else 0.0
        bars = [bass] * 4 + [0.3] * 28
        V.fireworks_render_lines(bars, 12, 50, state, use_color=False)
    assert state.get("parts"), "fireworks should hold live particles after beats"


def test_ripple_emits_rings_on_beat():
    state = {}
    for f in range(20):
        bass = 1.0 if f % 5 == 0 else 0.0
        bars = [bass] * 4 + [0.2] * 28
        V.ripple_render_lines(bars, 12, 50, state, use_color=False)
    assert state.get("rings"), "ripple should have expanding rings after beats"


def test_render_frame_covers_every_mode():
    # The dispatch registry must render every advertised VIS_MODE at exact size,
    # with one shared states dict, across several frames.
    from ac_ui.constants import VIS_MODES
    from ac_ui.visualizer import render_frame, VisFrameCtx
    # Mirror the real loop: the smoothed bar list is pre-sized to the spectrum
    # width, so bars length == width for every mode.
    w, h = 48, 6
    states = {}
    for mode in VIS_MODES:
        for f in range(5):
            bars = _loud_bars(w, t=f * 0.5)
            ctx = VisFrameCtx(states, cap_pos=bars, peak_bars=bars, trail_bars=bars,
                              use_color=True, game_tag=None)
            rows = render_frame(mode, bars, h, w, ctx)
            assert len(rows) == h, f"{mode}: {len(rows)} rows != {h}"
            for r in rows:
                assert len(strip_ansi(r)) == w, f"{mode}: width {len(strip_ansi(r))} != {w}"


def test_render_frame_unknown_mode_falls_back():
    from ac_ui.visualizer import render_frame, VisFrameCtx
    ctx = VisFrameCtx({}, use_color=False)
    rows = render_frame("does-not-exist", _loud_bars(30), 5, 30, ctx)
    assert len(rows) == 5 and all(len(strip_ansi(r)) == 30 for r in rows)


def test_render_frame_shares_states_dict():
    # Switching modes through one states dict must not leak/raise (each mode
    # owns its own sub-dict, created lazily).
    from ac_ui.visualizer import render_frame, VisFrameCtx
    states = {}
    for mode in ("flame", "scope", "fireworks", "bars", "flame"):
        ctx = VisFrameCtx(states, cap_pos=[0.5] * 24, peak_bars=[0.5] * 24,
                          trail_bars=[0.5] * 24, use_color=False)
        render_frame(mode, [0.4] * 24, 6, 40, ctx)
    assert "flame" in states and "scope" in states


def test_detect_beat_reports_onset():
    state = {}
    quiet = [0.0] * 24
    loud = [1.0] * 24
    V._detect_beat(quiet, state)
    _bass, onset = V._detect_beat(loud, state)
    assert onset > 0.0, "a jump from quiet to loud bass must register an onset"


def test_audio_features_report_band_energy_and_onset():
    state = {}
    quiet = [0.0] * 24
    loud = [1.0] * 4 + [0.2] * 10 + [0.6] * 10
    V.analyze_audio_features(quiet, state)
    feats = V.analyze_audio_features(loud, state)
    assert feats.bass > feats.mids * 0.9
    assert feats.onset > 0.0


def test_audio_features_report_spectral_centroid():
    low_heavy = [1.0] * 6 + [0.1] * 18
    high_heavy = [0.1] * 18 + [1.0] * 6
    low = V.analyze_audio_features(low_heavy, {})
    high = V.analyze_audio_features(high_heavy, {})
    assert 0.0 <= low.centroid <= 1.0
    assert 0.0 <= high.centroid <= 1.0
    assert high.centroid > low.centroid


def test_audio_features_report_spectral_contrast():
    flat = [0.5] * 24
    sparse = [0.0] * 20 + [1.0] * 4
    flat_feats = V.analyze_audio_features(flat, {})
    sparse_feats = V.analyze_audio_features(sparse, {})
    assert 0.0 <= flat_feats.contrast <= 1.0
    assert 0.0 <= sparse_feats.contrast <= 1.0
    assert sparse_feats.contrast > flat_feats.contrast


def test_audio_features_report_stereo_width():
    prev_channels = AS.CAVA_CHANNELS
    try:
        AS.CAVA_CHANNELS = "stereo"
        feats = V.analyze_audio_features([0.1, 0.8] * 12, {})
        assert feats.right > feats.left
        assert feats.width > 0.0
    finally:
        AS.CAVA_CHANNELS = prev_channels


def test_audio_snapshot_preserves_bar_views():
    prev_channels = AS.CAVA_CHANNELS
    try:
        AS.CAVA_CHANNELS = "stereo"
        snap = build_audio_snapshot([0.2, 0.8, 0.4, 0.6], {}, frame_dt=0.016, source_kind="cava")
        assert snap.bars == (0.2, 0.8, 0.4, 0.6)
        assert snap.analysis_bars == (0.5, 0.5)
        assert snap.bars_left == (0.2, 0.4)
        assert snap.bars_right == (0.8, 0.6)
        assert snap.source_kind == "cava"
        assert snap.frame_dt == pytest.approx(0.016)
        assert snap.features.width > 0.0
    finally:
        AS.CAVA_CHANNELS = prev_channels


def test_audio_snapshot_keeps_raw_stereo_views_with_explicit_analysis_bars():
    prev_channels = AS.CAVA_CHANNELS
    try:
        AS.CAVA_CHANNELS = "stereo"
        snap = build_audio_snapshot(
            [0.2, 0.8, 0.4, 0.6],
            {},
            analysis_bars=[0.5, 0.5],
            source_kind="cava",
        )
        assert snap.analysis_bars == (0.5, 0.5)
        assert snap.bars_left == (0.2, 0.4)
        assert snap.bars_right == (0.8, 0.6)
        assert snap.features.right > snap.features.left
        assert snap.features.width > 0.0
    finally:
        AS.CAVA_CHANNELS = prev_channels


def test_milkdrop_sets_dynamic_label():
    ctx = V.VisFrameCtx({}, use_color=False)
    rows = V.render_frame("milkdrop", _loud_bars(48), 6, 48, ctx)
    assert rows and ctx.label and ctx.label.startswith("milkdrop:")


def test_render_frame_prefers_snapshot_contract():
    snap = build_audio_snapshot([0.3] * 30, {}, source_kind="cava")
    ctx = V.VisFrameCtx({}, use_color=False, snapshot=snap)
    rows = V.render_frame("bars", [0.9] * 30, 5, 30, ctx)
    assert ctx.features is snap.features
    assert len(rows) == 5
    assert all(len(strip_ansi(r)) == 30 for r in rows)


def test_wave_renders_from_snapshot_waveform():
    mono = [math.sin(i * 0.16) * 0.6 for i in range(256)]
    snap = build_audio_snapshot([0.2] * 40, {}, waveform_mono=mono, sample_rate=48000, source_kind="pcm+cava")
    ctx = V.VisFrameCtx({}, use_color=False, snapshot=snap)
    rows = V.render_frame("wave", [0.0] * 40, 8, 40, ctx)
    assert len(rows) == 8
    assert all(len(strip_ansi(r)) == 40 for r in rows)
    assert any(ch != " " for row in rows for ch in strip_ansi(row))


def test_scope_renders_from_snapshot_stereo_waveform():
    left = [math.sin(i * 0.15) * 0.7 for i in range(256)]
    right = [math.cos(i * 0.11) * 0.5 for i in range(256)]
    snap = build_audio_snapshot([0.2] * 40, {}, waveform_left=left, waveform_right=right, sample_rate=48000, source_kind="pcm+cava")
    ctx = V.VisFrameCtx({}, use_color=False, snapshot=snap)
    rows = V.render_frame("scope", [0.0] * 40, 8, 40, ctx)
    assert len(rows) == 8
    assert all(len(strip_ansi(r)) == 40 for r in rows)
    assert any(ch != " " for row in rows for ch in strip_ansi(row))


def test_wave_renders_from_snapshot_stereo_waveform_without_prebuilt_mono():
    left = [math.sin(i * 0.15) * 0.7 for i in range(256)]
    right = [math.cos(i * 0.11) * 0.5 for i in range(256)]
    snap = build_audio_snapshot([0.2] * 40, {}, waveform_left=left, waveform_right=right, sample_rate=48000, source_kind="pcm+cava")
    assert not snap.waveform_mono
    ctx = V.VisFrameCtx({}, use_color=False, snapshot=snap)
    rows = V.render_frame("wave", [0.0] * 40, 8, 40, ctx)
    assert len(rows) == 8
    assert all(len(strip_ansi(r)) == 40 for r in rows)
    assert any(ch != " " for row in rows for ch in strip_ansi(row))


def test_native_braille_field_matches_python_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "braille_field"):
        pytest.skip("native braille helper unavailable")
    height, width = 8, 40
    dot_rows, dot_cols = height * 4, width * 2
    size = dot_rows * dot_cols
    inten = [max(0.0, min(1.0, (math.sin(i * 0.13) + math.cos(i * 0.07)) * 0.35 + 0.4)) for i in range(size)]
    hue = [(i * 17) % 101 for i in range(size)]
    grad = V.theme_visualizer_gradient("spectrum")
    esc = V._gradient_escape_lut(grad)
    esc_bold = V._gradient_escape_lut(grad, bold=True)
    for use_color in (False, True):
        native = V._vizfast.braille_field(
            inten, hue, dot_rows, dot_cols, height, width,
            esc if use_color else None, esc_bold if use_color else None,
            use_color, 0.05, V._BRAILLE_HOT_THRESHOLD, V.RESET,
        )
        python = V._braille_field_py(
            inten, hue, dot_rows, dot_cols, height, width, grad,
            use_color=use_color, threshold=0.05,
            esc=esc if use_color else None, esc_bold=esc_bold if use_color else None,
        )
        assert native == python


def test_native_buffer_braille_field_matches_python_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "braille_field_buf"):
        pytest.skip("native packed-buffer braille helper unavailable")
    height, width = 8, 40
    dot_rows, dot_cols = height * 4, width * 2
    size = dot_rows * dot_cols
    inten_list = [max(0.0, min(1.0, (math.sin(i * 0.13) + math.cos(i * 0.07)) * 0.35 + 0.4)) for i in range(size)]
    hue_list = [(i * 17) % 101 for i in range(size)]
    inten = array("f", inten_list)
    hue = bytearray(hue_list)
    grad = V.theme_visualizer_gradient("spectrum")
    esc = V._gradient_escape_lut(grad)
    esc_bold = V._gradient_escape_lut(grad, bold=True)
    for use_color in (False, True):
        native = V._vizfast.braille_field_buf(
            inten, hue, dot_rows, dot_cols, height, width,
            esc if use_color else None, esc_bold if use_color else None,
            use_color, 0.05, V._BRAILLE_HOT_THRESHOLD, V.RESET,
        )
        python = V._braille_field_py(
            inten_list, hue_list, dot_rows, dot_cols, height, width, grad,
            use_color=use_color, threshold=0.05,
            esc=esc if use_color else None, esc_bold=esc_bold if use_color else None,
        )
        assert native == python


def test_native_buffer_feedback_transform_matches_list_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "feedback_transform_into_buf"):
        pytest.skip("native packed-buffer feedback helper unavailable")
    kwargs = dict(
        decay=0.94, zoom=1.01, rot=0.03, drift_x=0.01, drift_y=-0.02,
        hue_shift=0.8, mirror=6, swirl=0.08, pinch=0.02,
        warp_amp=0.04, warp_freq=5.5, warp_phase=0.3,
    )
    dot_rows, dot_cols = 24, 80
    size = dot_rows * dot_cols
    src_inten_list = [max(0.0, min(1.0, (math.sin(i * 0.09) + math.cos(i * 0.04)) * 0.35 + 0.4)) for i in range(size)]
    src_hue_list = [(i * 11) % 101 for i in range(size)]
    src_inten = array("f", src_inten_list)
    src_hue = bytearray(src_hue_list)
    dst_inten = array("f", [0.0]) * size
    dst_hue = bytearray([50]) * size
    list_inten, list_hue = V._vizfast.feedback_transform(src_inten_list, src_hue_list, dot_rows, dot_cols, **kwargs)
    V._vizfast.feedback_transform_into_buf(src_inten, src_hue, dst_inten, dst_hue, dot_rows, dot_cols, **kwargs)
    assert max(abs(a - b) for a, b in zip(list_inten, dst_inten)) < 1e-5
    lit = [i for i, v in enumerate(dst_inten) if v > 0.01]
    assert [int(list_hue[i]) for i in lit] == [dst_hue[i] for i in lit]


def test_native_buffer_kaleido_overlay_matches_list_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "kaleido_overlay_geom_buf"):
        pytest.skip("native packed-buffer overlay helper unavailable")
    state = {}
    height, width = 18, 96
    dot_rows, dot_cols = height * 4, width * 2
    bars = [min(1.0, abs(math.sin(i * 0.29))) for i in range(48)]
    active = V._tunnel_geometry(state, dot_rows, dot_cols, len(bars))
    packed = V._tunnel_geometry_buf(state, dot_rows, dot_cols, len(bars))
    size = dot_rows * dot_cols
    list_inten = [0.0] * size
    list_hue = [50] * size
    buf_inten = array("f", [0.0]) * size
    buf_hue = bytearray([50]) * size
    phase = 1.3
    symmetry = 7
    ang_off = 0.8
    f03 = 1.2
    f09 = 5.0
    V._vizfast.kaleido_overlay(list_inten, list_hue, active, bars, phase, symmetry, ang_off, f03, f09)
    V._vizfast.kaleido_overlay_geom_buf(
        buf_inten, buf_hue,
        packed[0], packed[1], packed[2], packed[3], packed[4],
        bars, phase, symmetry, ang_off, f03, f09,
    )
    assert max(abs(a - b) for a, b in zip(list_inten, buf_inten)) < 5e-5
    assert [int(v) for v in list_hue] == list(buf_hue)


def test_native_folded_flat_kaleido_overlay_matches_unfolded_when_available():
    if (
        V._vizfast is None
        or not hasattr(V._vizfast, "kaleido_overlay_geom_buf_typed_flat")
        or not hasattr(V._vizfast, "kaleido_overlay_geom_buf_typed_flat_folded")
    ):
        pytest.skip("native folded flat overlay helper unavailable")
    state = {}
    height, width = 20, 110
    dot_rows, dot_cols = height * 2, width * 2
    bars = array("f", [min(1.0, abs(math.sin(i * 0.29))) for i in range(64)])
    packed = V._tunnel_geometry_buf(state, dot_rows, dot_cols, len(bars))
    symmetry = 7
    folded = V._tunnel_geometry_fold_buf(state, dot_rows, dot_cols, len(bars), symmetry)
    size = dot_rows * dot_cols
    base_inten = array("f", [0.0]) * size
    base_hue = bytearray([50]) * size
    folded_inten = array("f", [0.0]) * size
    folded_hue = bytearray([50]) * size
    phase = 1.3
    ang_off = 0.8
    f09 = 5.0
    seg = math.pi / symmetry
    seg2 = seg * 2.0
    V._vizfast.kaleido_overlay_geom_buf_typed_flat(
        base_inten, base_hue,
        packed[0], packed[1], packed[2], packed[3], packed[4],
        bars, phase, symmetry, ang_off, f09,
    )
    V._vizfast.kaleido_overlay_geom_buf_typed_flat_folded(
        folded_inten, folded_hue,
        folded[0], folded[1], folded[2], folded[3], folded[4],
        bars, phase, symmetry, ang_off % seg2, f09,
    )
    assert max(abs(a - b) for a, b in zip(base_inten, folded_inten)) < 5e-5
    assert list(base_hue) == list(folded_hue)


def test_native_buffer_flash_disc_matches_python_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "flash_disc_buf"):
        pytest.skip("native packed-buffer flash helper unavailable")
    dot_rows, dot_cols = 18 * 4, 96 * 2
    size = dot_rows * dot_cols
    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    flash = 0.42
    radius = 1.0 + flash * dot_rows * 0.18
    min_x = max(0, int(cx - radius))
    max_x = min(dot_cols - 1, int(cx + radius))
    min_y = max(0, int(cy - radius))
    max_y = min(dot_rows - 1, int(cy + radius))
    list_inten = [0.0] * size
    list_hue = [50] * size
    buf_inten = array("f", [0.0]) * size
    buf_hue = bytearray([50]) * size
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            dist = math.hypot(x - cx, (y - cy) * 1.2)
            if dist > radius:
                continue
            V._plot(list_inten, list_hue, dot_rows, dot_cols, x, y, flash * max(0.0, 1.0 - dist / max(0.001, radius)), 96)
    V._vizfast.flash_disc_buf(
        buf_inten, buf_hue, dot_cols, min_x, max_x, min_y, max_y,
        cx, cy, radius, flash, 96, 1.0, 1.2,
    )
    assert max(abs(a - b) for a, b in zip(list_inten, buf_inten)) < 1e-5
    assert [int(v) for v in list_hue] == list(buf_hue)


def test_native_plasma_field_matches_python_when_available():
    if V._vizfast is None or not hasattr(V._vizfast, "plasma_field_buf"):
        pytest.skip("native plasma field helper unavailable")
    dot_rows, dot_cols = 18 * 4, 96 * 2
    size = dot_rows * dot_cols
    phase = 3.2
    frame = 17.5
    pulse = 0.38
    contrast_att = 0.41
    bass_att = 0.33
    overall = 0.52
    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    list_inten = [0.0] * size
    list_hue = [50] * size
    buf_inten = array("f", [0.0]) * size
    buf_hue = bytearray([50]) * size
    for y in range(dot_rows):
        ny = (y - cy) / max(1.0, cy)
        for x in range(dot_cols):
            nx = (x - cx) / max(1.0, cx)
            r = math.hypot(nx * 1.05, ny * 1.20)
            if r > 1.35:
                continue
            swirl = (
                math.sin(nx * 6.4 + phase * 1.5)
                + math.sin(ny * 5.2 - phase * 1.1)
                + math.sin((nx + ny) * 4.1 + phase * 0.7)
            ) / 3.0
            petals = 0.5 + 0.5 * math.cos(math.atan2(ny, nx) * (3.2 + contrast_att * 2.2) - phase * 0.5)
            bloom = max(0.0, 1.0 - r * (1.02 + bass_att * 0.32))
            val = max(0.0, swirl * 0.5 + 0.5 - 0.26)
            val *= (bloom ** 1.9) * (0.30 + petals * 0.80) * (0.24 + overall * 0.96)
            ring = max(0.0, 0.20 - abs(r - (0.16 + pulse * 0.26)))
            val += ring * pulse * 1.7
            if val <= 0.05:
                continue
            idx = y * dot_cols + x
            if val > list_inten[idx]:
                list_inten[idx] = val
                list_hue[idx] = int((44 + swirl * 18 + petals * 20 + frame * 0.7 - r * 28) % 101)
    V._vizfast.plasma_field_buf(
        buf_inten, buf_hue, dot_rows, dot_cols,
        phase, frame, pulse, contrast_att, bass_att, overall,
    )
    assert max(abs(a - b) for a, b in zip(list_inten, buf_inten)) < 5e-5
    assert [int(v) for v in list_hue] == list(buf_hue)


def test_polar_spectrum_draws_a_ring_and_shuffles():
    # The donut should put lit cells away from the exact center (a ring, not a blob).
    state = {}
    for f in range(20):
        bars = _loud_bars(32, t=f * 0.5)
        rows = V.polar_spectrum_render_lines(bars, 16, 48, state, use_color=False)
    assert any(ch != " " for r in rows for ch in r), "polar produced a blank frame"
    from ac_ui.constants import VIS_MODES, normalize_vis_mode
    assert "polar" in VIS_MODES
    assert "polar" in V.SHUFFLE_MODES            # full-frame mode joins the shuffle
    assert normalize_vis_mode("donut") == "polar"


def test_audio_features_detect_chroma_and_key():
    from ac_ui.constants import CAVA_LOWER_CUTOFF as LO, CAVA_HIGHER_CUTOFF as HI
    pcs = AS._bar_pitch_classes(36, LO, HI)
    # Pump every bar belonging to pitch class 9 (A); A should win the key vote.
    bars = tuple(1.0 if pc == 9 else 0.05 for pc in pcs)
    state = {}
    feats = None
    for _ in range(30):                 # let the chroma EMA settle
        feats = AS.analyze_audio_features(bars, state)
    assert len(feats.chroma) == 12
    assert feats.key == 9
    assert AS.CHROMA_NOTE_NAMES[feats.key] == "A"
    assert feats.key_strength > 0.5


def test_audio_features_chroma_silent_has_no_key():
    feats = AS.analyze_audio_features(tuple([0.0] * 36), {})
    assert feats.key == -1
    assert all(c == 0.0 for c in feats.chroma)


@pytest.mark.parametrize("scale", ["linear", "log", "sqrt", "gamma"])
def test_spectrum_scale_curve_endpoints_and_monotonic(scale):
    # Endpoints are always preserved; the curve never decreases.
    assert V.spectrum_scale_curve(0.0, scale) == 0.0
    assert abs(V.spectrum_scale_curve(1.0, scale) - 1.0) < 1e-9
    prev = -1.0
    for i in range(21):
        cur = V.spectrum_scale_curve(i / 20.0, scale, 0.5)
        assert cur >= prev - 1e-9
        prev = cur


def test_spectrum_scale_curve_lifts_quiet_detail():
    # log/sqrt/gamma all push a quiet value above its linear height.
    for scale in ("log", "sqrt", "gamma"):
        assert V.spectrum_scale_curve(0.25, scale, 0.5) > 0.25


def test_apply_spectrum_scale_linear_is_identity():
    # With the default (linear) config this is a no-op that returns the input.
    bars = [0.1, 0.4, 0.9]
    if not V._SPECTRUM_SCALE_ACTIVE:
        assert V.apply_spectrum_scale(bars) is bars


def test_chroma_wheel_registered_and_shuffles():
    from ac_ui.constants import VIS_MODES, normalize_vis_mode
    assert "chroma" in VIS_MODES
    assert "chroma" in V.SHUFFLE_MODES
    assert normalize_vis_mode("wheel") == "chroma"
    assert normalize_vis_mode("key") == "chroma"


def test_features_debug_lines_exact_width_color_and_plain():
    snap = build_audio_snapshot(_loud_bars(24), {}, sample_rate=48000, source_kind="pcm")
    for use_color in (True, False):
        for w, h in [(48, 10), (60, 12), (20, 6), (80, 11)]:
            state = {}
            lines = V.features_debug_lines(
                snap.bars, h, w, state, features=snap.features, snapshot=snap, use_color=use_color
            )
            assert len(lines) == h
            for ln in lines:
                assert len(strip_ansi(ln)) == w, f"{w}x{h} color={use_color}: width mismatch"


def test_features_debug_lines_show_title_and_band_labels():
    snap = build_audio_snapshot(_loud_bars(24), {}, sample_rate=48000, source_kind="pcm")
    lines = V.features_debug_lines(
        snap.bars, 10, 60, {}, features=snap.features, snapshot=snap, use_color=False
    )
    assert lines[0].startswith("FEATURES")
    assert "48kHz" in lines[0]
    body = "\n".join(lines)
    for label in ("bass", "mids", "treble", "centroid", "contrast", "onset", "width"):
        assert label in body


def test_features_debug_lines_accumulate_history():
    state = {}
    snap = build_audio_snapshot(_loud_bars(24), {}, source_kind="pcm")
    for _ in range(5):
        V.features_debug_lines(snap.bars, 10, 50, state, features=snap.features, snapshot=snap, use_color=False)
    assert len(state["hist"]["bass"]) == 5


def test_features_debug_lines_history_is_capped():
    state = {}
    snap = build_audio_snapshot(_loud_bars(24), {}, source_kind="pcm")
    for _ in range(200):
        V.features_debug_lines(snap.bars, 10, 50, state, features=snap.features, snapshot=snap, use_color=False)
    assert len(state["hist"]["bass"]) == V._FEATURE_HISTORY


def test_features_debug_lines_degenerate_size():
    out = V.features_debug_lines(_loud_bars(), 0, 0, {}, use_color=True)
    assert isinstance(out, list) and out


def test_features_mode_is_dispatchable_and_ascii_safe():
    assert "features" in V.ASCII_SAFE_MODES
    assert "features" not in V.SHUFFLE_MODES   # debug view stays out of random shuffle
    from ac_ui.constants import VIS_MODES, normalize_vis_mode
    assert "features" in VIS_MODES
    assert normalize_vis_mode("diagnostics") == "features"


def test_next_shuffle_mode_never_repeats_and_is_valid():
    import random as _r
    from ac_ui.constants import VIS_MODES
    cur = "flame"
    rng = _r.Random(7)
    for _ in range(60):
        nxt = V.next_shuffle_mode(cur, rng)
        assert nxt in V.SHUFFLE_MODES
        assert nxt in VIS_MODES, f"{nxt} not a real visualizer mode"
        assert nxt != cur, "shuffle must not repeat the current preset"
        cur = nxt

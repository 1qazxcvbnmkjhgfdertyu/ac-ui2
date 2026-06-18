"""Tests for the theatrical / beat-reactive visualizer renderers.

Every renderer must return exactly `height` lines, each exactly `width` visible
columns wide (after stripping color), for any input — including silence, full
energy, odd sizes, and many animation frames.
"""
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

"""Tests for adaptive per-mode visualizer frame rate + time-based anim clock."""
import ac_ui.visualizer as vz
from ac_ui.audio_config import (
    vis_target_fps, vis_frame_interval,
    VIS_FPS_FAST, VIS_FPS_NORMAL, VIS_FPS_HEAVY,
    FAST_VIS_MODES, HEAVY_VIS_MODES, VIS_MODES,
)


def test_heavy_modes_capped():
    for mode in ("kaleido_tunnel", "milkdrop", "plasma_bloom", "liquid_scope"):
        assert mode in HEAVY_VIS_MODES
        assert vis_target_fps(mode) == VIS_FPS_HEAVY


def test_fast_modes_get_fast_rate():
    for mode in ("bars", "peaks", "braille", "spectrum"):
        assert mode in FAST_VIS_MODES
        assert vis_target_fps(mode) == VIS_FPS_FAST


def test_self_animating_modes_stay_normal():
    # Frame-counter-driven modes that aren't time-based must not be sped up.
    for mode in ("matrix_rain", "starfield", "aurora", "fireworks", "ripple"):
        assert mode not in FAST_VIS_MODES
        assert mode not in HEAVY_VIS_MODES
        assert vis_target_fps(mode) == VIS_FPS_NORMAL


def test_every_mode_has_a_defined_rate():
    for mode in VIS_MODES:
        fps = vis_target_fps(mode)
        assert fps >= 1
        assert vis_frame_interval(mode) == 1.0 / max(1, fps)


def test_unknown_mode_falls_back_to_normal():
    assert vis_target_fps("does_not_exist") == VIS_FPS_NORMAL


def test_frame_interval_is_inverse_of_fps():
    assert abs(vis_frame_interval("bars") - 1.0 / VIS_FPS_FAST) < 1e-9
    assert abs(vis_frame_interval("kaleido_tunnel") - 1.0 / VIS_FPS_HEAVY) < 1e-9


# ── time-based animation clock ────────────────────────────────────────────────

def test_anim_clock_advances_with_wall_time(monkeypatch):
    state = {}
    t = [1000.0]
    monkeypatch.setattr(vz.time, "monotonic", lambda: t[0])
    # First call seeds the timestamp, returns 0.
    assert vz.anim_clock(state, ref_fps=30.0) == 0.0
    # Advance a realistic frame (~33ms) -> +0.033*30 ≈ 1.0 unit.
    t[0] += 1.0 / 30.0
    assert abs(vz.anim_clock(state, ref_fps=30.0) - 1.0) < 1e-6
    # Another ~33ms -> +1.0.
    t[0] += 1.0 / 30.0
    assert abs(vz.anim_clock(state, ref_fps=30.0) - 2.0) < 1e-6


def test_anim_clock_speed_independent_of_sample_rate(monkeypatch):
    # Sampling the same 0.2s span at 30fps vs 120fps (steps both well under the
    # 0.25s anti-lurch clamp) lands at the same place — proving a higher fps
    # changes smoothness, not speed.
    t = [0.0]
    monkeypatch.setattr(vz.time, "monotonic", lambda: t[0])

    coarse = {}
    vz.anim_clock(coarse, ref_fps=30.0)
    for _ in range(6):                 # 6 steps of ~33ms ≈ 0.2s (30fps)
        t[0] += 1.0 / 30.0
        coarse_val = vz.anim_clock(coarse, ref_fps=30.0)

    t[0] = 0.0
    fine = {}
    vz.anim_clock(fine, ref_fps=30.0)
    for _ in range(24):                # 24 steps of ~8.3ms ≈ 0.2s (120fps)
        t[0] += 1.0 / 120.0
        fine_val = vz.anim_clock(fine, ref_fps=30.0)

    assert abs(coarse_val - fine_val) < 1e-6


def test_anim_clock_clamps_large_gaps(monkeypatch):
    state = {}
    t = [0.0]
    monkeypatch.setattr(vz.time, "monotonic", lambda: t[0])
    vz.anim_clock(state, ref_fps=30.0)
    t[0] = 100.0  # huge gap (pause/resize) -> clamped to 0.25s of motion
    val = vz.anim_clock(state, ref_fps=30.0)
    assert abs(val - 0.25 * 30.0) < 1e-6

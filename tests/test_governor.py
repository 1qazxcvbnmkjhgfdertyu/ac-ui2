"""Tests for the automatic render-pacing helpers (ui.governed_refresh + idle)."""
from ac_ui.ui import governed_refresh, idle_throttled_interval


def test_cheap_frames_keep_the_target_rate():
    # 2 ms frame at a 16 ms (60 fps) target: well within budget -> unchanged.
    assert governed_refresh(0.016, 0.002) == 0.016


def test_no_history_is_a_noop():
    assert governed_refresh(0.016, 0.0) == 0.016


def test_expensive_frames_stretch_the_wait():
    # A 30 ms frame at a 16 ms target, 50% duty: wait must rise so render is at
    # most half the wall clock -> wait >= work (period >= 2*work).
    wait = governed_refresh(0.016, 0.030, duty=0.5)
    assert wait >= 0.030
    period = 0.030 + wait
    assert 0.030 / period <= 0.5 + 1e-9


def test_heavier_frames_are_capped_harder():
    # The worst cases (huge terminal / very weak CPU) get the biggest stretch.
    light = governed_refresh(0.016, 0.020, duty=0.5)
    heavy = governed_refresh(0.016, 0.060, duty=0.5)
    assert heavy > light


def test_duty_one_disables_governing():
    assert governed_refresh(0.016, 0.060, duty=1.0) == 0.016


def test_idle_throttle_keeps_rate_while_audio_is_recent():
    # Sound within the last moment -> full target rate.
    assert idle_throttled_interval(0.016, 0.5, idle_interval=0.10, after=2.5) == 0.016


def test_idle_throttle_slows_after_sustained_silence():
    # Silent past the threshold -> drop to (the slower) idle rate.
    assert idle_throttled_interval(0.016, 3.0, idle_interval=0.10, after=2.5) == 0.10


def test_idle_throttle_never_speeds_up_a_slower_base():
    # If the base is already slower than idle (e.g. governed), keep the slower one.
    assert idle_throttled_interval(0.20, 5.0, idle_interval=0.10, after=2.5) == 0.20


def test_vis_overload_only_flags_heavy_modes_that_are_too_slow():
    from ac_ui.ui import vis_mode_overloaded
    # A heavy mode over the ceiling on this (simulated) machine -> fall back.
    assert vis_mode_overloaded("kaleido_tunnel", 0.20, ceiling=0.08) is True
    # The same heavy mode when it's fast enough -> keep it.
    assert vis_mode_overloaded("kaleido_tunnel", 0.01, ceiling=0.08) is False
    # Cheap modes never qualify, however slow the machine.
    assert vis_mode_overloaded("spectrum", 0.50, ceiling=0.08) is False
    assert vis_mode_overloaded("bars", 0.50, ceiling=0.08) is False

"""Tests for the frame-rate menu pure logic + persistence."""
from ac_ui.vis_fps_menu import cycle_fps, build_vis_fps_lines
from ac_ui.constants import VIS_FPS_CHOICES, default_vis_fps_map
from ac_ui.persist import _normalize_vis_fps


def test_cycle_fps_steps_through_choices():
    # 60 -> next is 90, prev is 45 (per VIS_FPS_CHOICES ordering).
    assert cycle_fps(60, +1) == 90
    assert cycle_fps(60, -1) == 45


def test_cycle_fps_wraps():
    last = VIS_FPS_CHOICES[-1]
    first = VIS_FPS_CHOICES[0]
    assert cycle_fps(last, +1) == first
    assert cycle_fps(first, -1) == last


def test_cycle_fps_snaps_unknown_value():
    # An off-grid value snaps to the nearest choice before stepping.
    near = min(VIS_FPS_CHOICES, key=lambda c: abs(c - 58))  # -> 60
    assert cycle_fps(58, 0) == near


def test_build_lines_shows_all_three_tiers():
    fps = {"fast": 60, "normal": 30, "heavy": 24}
    plain, color = build_vis_fps_lines(fps, selected=0, inner_w=60)
    assert len(plain) == len(color)
    body = "\n".join(plain)
    assert "60 fps" in body and "30 fps" in body and "24 fps" in body
    for line in plain:
        assert len(line) <= 60


def test_build_lines_marks_selection():
    fps = default_vis_fps_map()
    plain, _c = build_vis_fps_lines(fps, selected=1, inner_w=60)
    # The three tier rows are the first three lines; row 1 is selected.
    assert plain[1].strip().startswith((">", "▶"))
    assert not plain[0].strip().startswith((">", "▶"))


def test_persist_normalizes_vis_fps():
    # Valid dict is clamped into range; missing/garbage tiers fall back.
    out = _normalize_vis_fps({"fast": 999, "normal": "x", "heavy": 24})
    assert out["fast"] == max(VIS_FPS_CHOICES)   # clamped to ceiling
    assert out["normal"] == default_vis_fps_map()["normal"]  # bad -> default
    assert out["heavy"] == 24


def test_persist_normalizes_non_dict():
    assert _normalize_vis_fps(None) == default_vis_fps_map()
    assert _normalize_vis_fps("nope") == default_vis_fps_map()

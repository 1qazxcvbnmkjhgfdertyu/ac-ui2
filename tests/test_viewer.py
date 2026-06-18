"""Tests for the fullscreen content viewer pure logic (viewer.py)."""
from ac_ui.viewer import build_viewer_frame


def test_window_clamps_scroll_and_pads():
    plain = [f"line {i}" for i in range(5)]
    color = list(plain)
    wp, wc, scroll = build_viewer_frame(plain, color, scroll=999, body_rows=8)
    # Scroll clamped (only 5 lines, body 8 -> max_scroll 0)
    assert scroll == 0
    # Padded up to body_rows for a stable box height.
    assert len(wp) == 8
    assert len(wc) == 8
    assert "line 0" in wp[0]


def test_window_follows_scroll():
    plain = [f"line {i}" for i in range(20)]
    wp, wc, scroll = build_viewer_frame(plain, plain, scroll=5, body_rows=4)
    assert scroll == 5
    assert wp[0] == "line 5"
    assert len(wp) == 4


def test_color_defaults_to_plain_when_missing():
    plain = ["a", "b", "c"]
    wp, wc, _s = build_viewer_frame(plain, None, scroll=0, body_rows=3)
    assert wc[:3] == ["a", "b", "c"]

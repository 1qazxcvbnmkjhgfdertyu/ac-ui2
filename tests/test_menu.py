"""Tests for the generic popup menu pure logic (menu.py)."""
from ac_ui.menu import build_menu_lines


OPTS = [("Play now", "play"), ("Move to top", "top"), ("Pin", "pin")]


def test_lines_match_option_count():
    plain, color = build_menu_lines(OPTS, 0, inner_w=40)
    assert len(plain) == len(OPTS)
    assert len(color) == len(plain)


def test_selected_row_marked():
    marked, _c = build_menu_lines(OPTS, 1, inner_w=40)
    # The selected (index 1) row carries a marker the others don't.
    assert marked[1].strip().startswith((">", "▶"))
    assert not marked[0].strip().startswith((">", "▶"))


def test_labels_present_and_width_bounded():
    plain, _c = build_menu_lines(OPTS, 0, inner_w=20)
    assert any("Play now" in p for p in plain)
    for line in plain:
        assert len(line) <= 20

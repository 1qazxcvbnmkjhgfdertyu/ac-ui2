"""Tests for the searchable help overlay pure logic (help_overlay.py)."""
from ac_ui.colors import strip_ansi, visible_len
from ac_ui.palette import build_palette_commands
from ac_ui.help_overlay import (
    build_help_detail_box,
    build_help_groups,
    filter_help_groups,
    build_help_lines,
)


def test_groups_cover_every_command():
    cmds = build_palette_commands(skip_ids=())
    groups = build_help_groups(cmds)
    grouped_ids = {c.action_id for _t, members in groups for c in members}
    assert grouped_ids == {c.action_id for c in cmds}
    # Help lists the palette itself (unlike the palette).
    assert "palette" in grouped_ids


def test_group_titles_present_and_nonempty():
    groups = build_help_groups()
    titles = [t for t, _m in groups]
    assert "Playback" in titles
    assert all(members for _t, members in groups)


def test_filter_narrows_to_matches():
    groups = build_help_groups()
    filtered = filter_help_groups(groups, "theme")
    flat = [c for _t, m in filtered for c in m]
    assert flat, "expected matches for 'theme'"
    assert any(c.action_id == "theme" for c in flat)
    # Categories with no match are dropped entirely.
    for _t, members in filtered:
        assert members


def test_filter_empty_query_is_identity():
    groups = build_help_groups()
    assert filter_help_groups(groups, "") == groups


def test_build_lines_respects_width_and_reports_total():
    groups = build_help_groups()
    plain, color, total = build_help_lines(groups, "", 0, inner_w=60, max_rows=10)
    assert len(plain) == len(color)
    assert total > 0
    assert plain[0].startswith("/")     # search prompt
    for line in plain:
        assert len(line) <= 60


def test_scroll_clamps_and_changes_window():
    groups = build_help_groups()
    top_p, _c, total = build_help_lines(groups, "", 0, inner_w=60, max_rows=8)
    bot_p, _c2, _t2 = build_help_lines(groups, "", total + 999, inner_w=60, max_rows=8)
    # Over-scrolling is clamped, not crashing, and yields a different window.
    assert top_p != bot_p


def test_no_matches_message():
    groups = build_help_groups()
    filtered = filter_help_groups(groups, "zzzzzz")
    plain, _c, _t = build_help_lines(filtered, "zzzzzz", 0, inner_w=50, max_rows=8)
    assert any("no matching" in p for p in plain)


def test_rows_use_short_labels_and_never_truncate():
    # Short labels keep every row well within the width — no "..." truncation.
    groups = build_help_groups()
    plain, _c, _t = build_help_lines(groups, "", 0, inner_w=60, max_rows=200)
    for line in plain:
        assert "…" not in line and "..." not in line
        assert len(line) <= 60


def test_selected_row_is_marked_and_visible():
    groups = build_help_groups()
    # selected=0 is the first command; it must be marked and inside the window.
    plain, _c, _t = build_help_lines(groups, "", 0, inner_w=60, max_rows=200, selected=0)
    marked = [p for p in plain if p.strip().startswith((">", "▶"))]
    assert len(marked) == 1


def test_detail_box_has_key_and_full_description():
    cmd = next(c for c in build_palette_commands(skip_ids=()) if c.action_id == "loop")
    box = build_help_detail_box(cmd, 60)
    text = "\n".join(strip_ansi(line) for line in box)
    assert cmd.key_label in text          # shows the key
    assert "Repeat" in text               # shows the full plain-language sentence
    assert all(visible_len(line) == visible_len(box[0]) for line in box)

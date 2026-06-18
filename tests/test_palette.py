"""Tests for the command palette pure logic (palette.py)."""
from ac_ui.palette import (
    build_palette_commands,
    fuzzy_score,
    rank_commands,
    build_palette_lines,
)


def test_commands_derived_from_registry():
    cmds = build_palette_commands()
    ids = {c.action_id for c in cmds}
    # A few well-known actions should be present...
    assert {"next", "mute", "theme", "eq", "tune"} <= ids
    # ...but the palette must never list itself.
    assert "palette" not in ids
    # Every command exposes a non-empty primary key and title.
    for c in cmds:
        assert c.primary
        assert c.title


def test_fuzzy_score_subsequence_and_miss():
    assert fuzzy_score("nt", "next track") is not None
    assert fuzzy_score("", "anything") == 0
    assert fuzzy_score("zzz", "next track") is None


def test_fuzzy_prefers_consecutive_and_wordstart():
    # Consecutive run "next" should beat scattered subsequence in another string.
    consec = fuzzy_score("next", "next track")
    scattered = fuzzy_score("next", "no extra fun text")
    assert consec is not None and scattered is not None
    assert consec > scattered


def test_rank_empty_query_preserves_order():
    cmds = build_palette_commands()
    ranked = rank_commands(cmds, "")
    assert ranked == cmds


def test_rank_filters_and_orders():
    cmds = build_palette_commands()
    ranked = rank_commands(cmds, "theme")
    assert ranked, "expected at least one match for 'theme'"
    assert ranked[0].action_id == "theme"
    # All returned commands must actually match the query.
    for c in ranked:
        assert fuzzy_score("theme", c.search) is not None


def test_build_lines_shape_and_selection_window():
    cmds = build_palette_commands()
    plain, color = build_palette_lines(cmds, "", 0, inner_w=50, max_rows=8)
    assert len(plain) == len(color)
    # First line is the prompt, second is a separator blank.
    assert plain[0].startswith("/")
    assert plain[1] == ""
    # No content line exceeds the inner width.
    for line in plain:
        assert len(line) <= 50


def test_build_lines_no_matches():
    plain, color = build_palette_lines([], "zzz", 0, inner_w=40, max_rows=6)
    assert any("no matches" in p for p in plain)
    assert len(plain) == len(color)


def test_selected_item_stays_in_window_when_scrolled():
    cmds = build_palette_commands()
    last = len(cmds) - 1
    plain, _ = build_palette_lines(cmds, "", last, inner_w=50, max_rows=5)
    # The last command's key tag should appear in the rendered window.
    tag = f"[{cmds[last].key_label}]"
    assert any(tag in p for p in plain)

"""Tests for the generic fuzzy finder pure logic (finder.py)."""
from ac_ui.finder import make_item, rank_items, build_finder_lines


def _items():
    return [
        make_item("05:00  ACGC: rainy", "p1", "acgc rainy 05 mp3"),
        make_item("12:00  ACNL: sunny", "p2", "acnl sunny 12 flac"),
        make_item("23:00  ACWW: night", "p3", "acww night 23 mp3"),
    ]


def test_make_item_defaults_search_to_label():
    it = make_item("Hello World", 42)
    assert it.value == 42
    assert it.search == "hello world"


def test_rank_empty_query_preserves_order():
    items = _items()
    assert rank_items(items, "") == items


def test_rank_filters_by_search_haystack():
    items = _items()
    ranked = rank_items(items, "sunny")
    assert len(ranked) == 1
    assert ranked[0].value == "p2"


def test_rank_no_match_returns_empty():
    assert rank_items(_items(), "zzzzz") == []


def test_build_lines_header_has_count_and_prompt():
    items = _items()
    plain, color = build_finder_lines(items, "ac", 0, total=3, inner_w=50, max_rows=8)
    assert len(plain) == len(color)
    assert plain[0].startswith("/")
    assert "3" in plain[0]  # total count shown
    for line in plain:
        assert len(line) <= 50


def test_build_lines_no_matches_message():
    plain, _c = build_finder_lines([], "zzz", 0, total=3, inner_w=40, max_rows=6)
    assert any("no matches" in p for p in plain)


def test_build_lines_selection_window_follows_selected():
    items = [make_item(f"item {i}", i, f"item {i}") for i in range(40)]
    last = len(items) - 1
    plain, _c = build_finder_lines(items, "", last, total=40, inner_w=40, max_rows=6)
    assert any("item 39" in p for p in plain)

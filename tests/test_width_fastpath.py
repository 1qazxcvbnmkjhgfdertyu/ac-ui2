"""Correctness tests for the memoized / fast-pathed width + color helpers.

These guard the rendering hot-path optimizations: the fast paths must return
exactly what the original per-character logic did.
"""
import unicodedata

from ac_ui.colors import (
    char_cell_width, plain_visible_len, visible_len, color_code, sgr,
)
from ac_ui.term import truncate_ansi_visible, fit_ansi_line


def _ref_plain_len(s):
    total = 0
    for ch in s:
        if not ch:
            continue
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


SAMPLES = [
    "",
    "hello world",
    "n next  q quit  +/- vol",
    "│ Now Playing ├──────╮",       # box-drawing (non-ASCII, width 1)
    "⠋⠙⠹ braille ⠸⠼",                # braille (non-ASCII, width 1)
    "日本語のテキスト",               # wide CJK (width 2 each)
    "mix 日本 abc ▓▒░",
]


def test_char_cell_width_matches_unicodedata():
    for ch in "aZ9 │⠋日Ｆé":
        expected = 0 if (ch and unicodedata.combining(ch)) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        )
        assert char_cell_width(ch) == expected, repr(ch)


def test_plain_visible_len_matches_reference():
    for s in SAMPLES:
        assert plain_visible_len(s) == _ref_plain_len(s), repr(s)


def test_visible_len_strips_ansi_then_measures():
    colored = "\x1b[38;5;42mhello\x1b[0m"
    assert visible_len(colored) == 5
    wide = "\x1b[1m日本\x1b[0m"
    assert visible_len(wide) == 4   # two wide chars
    assert visible_len("plain ascii") == 11


def test_truncate_fastpath_matches_for_ascii():
    s = "the quick brown fox"
    for n in range(0, len(s) + 3):
        assert truncate_ansi_visible(s, n) == s[:n]


def test_truncate_preserves_ansi_and_wide():
    colored = "\x1b[31mabcdef\x1b[0m"
    out = truncate_ansi_visible(colored, 3)
    # visible content truncated to 3 cols, color opened then closed.
    assert "abc" in out
    assert out.endswith("\x1b[0m")
    # A wide char that would overflow the budget is not split.
    assert visible_len(truncate_ansi_visible("日本語", 3)) <= 3


def test_fit_ansi_line_returns_consistent_width():
    # The returned width must equal visible_len of the returned line, and the
    # line must equal truncate_ansi_visible (same truncation).
    for s in SAMPLES + ["\x1b[31mred\x1b[0m text", "日本 abc"]:
        for n in (0, 1, 3, 5, 100):
            line, w = fit_ansi_line(s, n)
            assert line == truncate_ansi_visible(s, n)
            assert w == visible_len(line)
            assert w <= max(0, n)


def test_color_code_and_sgr_cached_consistent():
    import ac_ui.colors as colors

    old_use_color = colors.USE_COLOR
    old_color_mode = colors.COLOR_MODE
    colors.USE_COLOR = True
    colors.COLOR_MODE = "truecolor"
    colors._color_code_cache.clear()
    colors._sgr_cache.clear()

    # Same inputs -> identical strings (cache hit must equal fresh compute).
    try:
        a = color_code((200, 100, 50))
        b = color_code((200, 100, 50))
        assert a == b
        s1 = sgr(fg=(10, 20, 30), bold=True)
        s2 = sgr(fg=(10, 20, 30), bold=True)
        assert s1 == s2
        # Distinct inputs -> distinct outputs (no cache key collision).
        assert sgr(fg=(10, 20, 30)) != sgr(fg=(30, 20, 10))
    finally:
        colors.USE_COLOR = old_use_color
        colors.COLOR_MODE = old_color_mode
        colors._color_code_cache.clear()
        colors._sgr_cache.clear()

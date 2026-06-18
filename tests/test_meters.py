"""Tests for the btop-style meter / area-graph primitives."""
import pytest

from ac_ui.colors import strip_ansi
from ac_ui.meters import meter_bar, braille_graph, _resample


# ── meter_bar ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pct", [0, 1, 25, 50, 99, 100, 150, -10])
@pytest.mark.parametrize("w", [1, 8, 20, 40])
def test_meter_bar_exact_width(pct, w):
    for color in (True, False):
        bar = meter_bar(pct, w, use_color=color)
        assert len(strip_ansi(bar)) == w, f"meter_bar({pct},{w}) width={len(strip_ansi(bar))}"


def test_meter_bar_zero_width():
    assert meter_bar(50, 0) == ""


def test_meter_bar_fills_proportionally():
    # No-color full blocks scale with percentage.
    assert strip_ansi(meter_bar(0, 10, use_color=False)).count("█") == 0
    assert strip_ansi(meter_bar(100, 10, use_color=False)).count("█") == 10
    half = strip_ansi(meter_bar(50, 10, use_color=False)).count("█")
    assert 4 <= half <= 6


# ── braille_graph ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("w,h", [(10, 1), (24, 2), (40, 3), (7, 4)])
def test_braille_graph_dimensions(w, h):
    series = [i / 23 for i in range(24)]
    for color in (True, False):
        rows = braille_graph(series, w, h, use_color=color)
        assert len(rows) == h
        for r in rows:
            assert len(strip_ansi(r)) == w


def test_braille_graph_empty_series():
    rows = braille_graph([], 12, 2, use_color=False)
    assert len(rows) == 2
    assert all(len(r) == 12 for r in rows)


def test_braille_graph_full_series_fills_bottom_row():
    # A series of all-1.0 should light dots in every output row.
    rows = braille_graph([1.0] * 24, 20, 3, use_color=False)
    for r in rows:
        assert any(ch != " " and ch != "⠀" for ch in r), "expected lit braille dots"


def test_braille_graph_silence_is_blank():
    rows = braille_graph([0.0] * 24, 20, 2, use_color=False)
    for r in rows:
        assert all(ch in (" ", "⠀") for ch in r)


def test_braille_graph_col_colors_respected():
    # When col_colors is supplied the graph must still be exactly width wide.
    series = [1.0] * 24
    col_colors = [60] * 16
    rows = braille_graph(series, 16, 2, col_colors=col_colors, use_color=True)
    assert all(len(strip_ansi(r)) == 16 for r in rows)


def test_resample_clamps_and_sizes():
    out = _resample([0.0, 2.0, -1.0], 10)
    assert len(out) == 10
    assert all(0.0 <= v <= 1.0 for v in out)

"""Layout / window-size tests built on the (now engine-aligned) preview."""
import pytest

from ac_ui.colors import strip_ansi
from ac_ui.layout import build_box
from ac_ui.layout_engine import resolve_panel_max_width
from ac_ui.layout_preview import build_layout_preview


# ── build_box title behavior ──────────────────────────────────────────────────

@pytest.mark.parametrize("maxw", [4, 6, 8, 11, 24, 60])
def test_box_always_labeled(maxw):
    # A title must never silently vanish — it truncates (…) to fit instead.
    box, _ = build_box(["x"], ["x"], maxw_override=maxw, title="Now Playing")
    top = strip_ansi(box[0])
    # Some recognizable fragment of the title survives in the top border.
    assert "N" in top and "┐" in top and "┌" in top


def test_box_full_title_when_room():
    box, _ = build_box(["x" * 30], ["x" * 30], maxw_override=30, title="Now Playing")
    assert "Now Playing" in strip_ansi(box[0])

def test_box_collapses_secondary_titles_into_bottom_notch():
    box, _ = build_box(
        ["x" * 32],
        ["x" * 32],
        maxw_override=60,
        title="Visualizer",
        title2=("[y]shuffle", "[r]fps", "[t/R]vis"),
    )
    top = strip_ansi(box[0])
    bottom = strip_ansi(box[-1])
    assert "Visualizer" in top
    assert "[y]shuffle" in bottom
    assert "[r]fps" in bottom
    assert "[t/R]vis" in bottom


# ── resolve_panel_max_width is the single source of truth ──────────────────────

@pytest.mark.parametrize("cols", [60, 80, 100, 120, 160, 200])
def test_panel_max_width_monotone_and_bounded(cols):
    for preset in ("two_rail", "stacked", "wide_graph"):
        w = resolve_panel_max_width(cols, preset)
        assert 12 <= w <= 60, f"{cols}/{preset} -> {w}"


def test_all_presets_render_every_panel():
    from ac_ui.constants import LAYOUT_PRESETS, FULLSCREEN_LAYOUT_PRESETS
    from ac_ui.layout_config import default_layout_config

    for preset in LAYOUT_PRESETS:
        cfg = default_layout_config(preset)
        out = build_layout_preview(120, 40, cfg)
        txt = "\n".join(strip_ansi(ln) for ln in out)
        if preset in FULLSCREEN_LAYOUT_PRESETS:
            # Fullscreen suppresses side panels + stats; only Now Playing shows.
            assert "Now Playing" in txt
            for label in ("History", "Up Next", "Stats"):
                assert label not in txt, f"{preset}: {label} should be hidden"
        else:
            for label in ("Now Playing", "History", "Up Next", "Stats"):
                assert label in txt, f"{preset}: missing {label}"
        assert len(out) == 40
        assert all(len(strip_ansi(ln)) <= 120 for ln in out)


@pytest.mark.parametrize("cols,rows", [(80, 24), (100, 30), (120, 40), (160, 50)])
def test_presets_fill_width_no_big_gaps(cols, rows):
    # Every preset should tile the width btop-style: the boxes (rows with a
    # vertical border) reach within a small margin of the full width — no big
    # dead strip on the right. (The footer hotkey legend is text, not a box, so
    # it's intentionally excluded.)
    from ac_ui.constants import LAYOUT_PRESETS
    from ac_ui.layout_config import default_layout_config

    for preset in LAYOUT_PRESETS:
        out = build_layout_preview(cols, rows, default_layout_config(preset))
        box_rows = [strip_ansi(ln) for ln in out if "│" in strip_ansi(ln)]
        gaps = [cols - len(ln) for ln in box_rows]
        assert gaps, f"{preset} {cols}x{rows}: no box rows"
        # ≤6 = 2-col right margin + minor split rounding across panels.
        assert max(gaps) <= 6, f"{preset} {cols}x{rows}: dead space {max(gaps)} cols"


def test_uniform_border_matches_spinning_visible_output():
    # The low-power "uniform border" fast path (BOX_BORDER_SPIN off) must paint
    # the same visible box as the per-character spinning path — only the ANSI
    # byte count differs.
    import ac_ui.layout as L

    lines_plain = ["alpha", "beta gamma"]
    lines_color = list(lines_plain)
    orig = L.BOX_BORDER_SPIN
    try:
        L.BOX_BORDER_SPIN = True
        spin, _ = L.build_box(lines_plain, lines_color, maxw_override=20, title="Demo")
        L.BOX_BORDER_SPIN = False
        flat, _ = L.build_box(lines_plain, lines_color, maxw_override=20, title="Demo")
    finally:
        L.BOX_BORDER_SPIN = orig

    assert len(spin) == len(flat)
    for a, b in zip(spin, flat):
        assert strip_ansi(a) == strip_ansi(b)         # identical visible output
    # The flat path collapses per-char escapes, so the bottom border is shorter.
    assert flat[-1].count("\x1b") <= spin[-1].count("\x1b")


def test_box_lines_fitted_fastpath_matches_regular():
    lines = [
        "\x1b[38;5;196m" + ("#" * 24) + "\x1b[0m",
        "\x1b[38;5;82m" + ("@" * 24) + "\x1b[0m",
    ]
    regular, _ = build_box(lines, lines, maxw_override=24, title="Visualizer", title2="[r]fps")
    fitted, _ = build_box(
        lines, lines, maxw_override=24, title="Visualizer", title2="[r]fps", lines_fitted=True,
    )
    assert regular == fitted


def test_below_panel_inner_width_splits_row():
    from ac_ui.layout_engine import below_panel_inner_width
    # Two panels sharing a 120-col row: each should be ~half, filling the row.
    w2 = below_panel_inner_width(120, 2)
    # outer = inner+4 each, + 3 gap, + 2 margin should be close to 120.
    used = 2 * (w2 + 4) + 3 + 2
    assert used <= 120
    assert used >= 120 - 4   # within rounding of full width
    # One panel fills almost the whole row.
    w1 = below_panel_inner_width(120, 1)
    assert (w1 + 4) >= 120 - 4


# ── Layout preview: sizing + panel presence across windows ─────────────────────

@pytest.mark.parametrize("cols,rows", [(80, 24), (100, 30), (120, 40), (160, 50), (50, 40)])
def test_preview_dimensions(cols, rows):
    out = build_layout_preview(cols, rows)
    assert len(out) == rows
    assert all(len(strip_ansi(ln)) <= cols for ln in out)


def test_preview_shows_panels_when_room():
    txt = "\n".join(build_layout_preview(120, 40))
    for label in ("Now Playing", "History", "Up Next", "Stats"):
        assert label in txt, f"missing {label} at 120x40"


def test_preview_now_playing_labeled_when_narrow():
    # Even a narrow compact box keeps a (truncated) Now Playing label.
    top = "\n".join(build_layout_preview(50, 40))
    assert "Now" in top


@pytest.mark.parametrize("cols,rows", [(80, 24), (100, 30), (120, 30), (160, 40)])
def test_top_row_fills_width(cols, rows):
    # The Now Playing row stretches nearly edge-to-edge, leaving exactly the
    # 2-column right safety margin (so it never gets clipped at the screen edge).
    out = build_layout_preview(cols, rows)
    np_row = next((strip_ansi(l) for l in out if "Now Playing" in l), "")
    assert cols - 3 <= len(np_row) <= cols - 2, f"top row {len(np_row)}/{cols} (expected ~{cols-2})"


def test_box_border_glows_with_pulse():
    # Border resting color and full-pulse color differ (beat-reactive glow).
    import re
    import ac_ui.colors as _clrs
    import ac_ui.layout as L
    _clrs.USE_COLOR = True
    L.USE_COLOR = True
    spin = L.BOX_BORDER_SPIN
    L.BOX_BORDER_SPIN = False  # isolate the glow from the spinning highlight

    def side_rgb(pulse):
        L.BOX_PULSE = pulse
        box, _ = build_box(["x", "y", "z"], ["x", "y", "z"], maxw_override=10, title="NP")
        m = re.search(r"\x1b\[[0-9;]+m", box[2])
        return m.group(0) if m else None

    low, high = side_rgb(0.0), side_rgb(1.0)
    L.BOX_PULSE = 0.0
    L.BOX_BORDER_SPIN = spin
    assert low and high and low != high, "border should shift color as BOX_PULSE rises"


@pytest.mark.parametrize("w", [40, 55, 60, 80, 120])
def test_now_playing_fits_its_width(w):
    # Regression for "Now Playing slightly cut off": the panel renders its content
    # (long meters, art mosaic) within its given width, so the box never clips it.
    import ac_ui.colors as _clrs
    from ac_ui.panels.now_playing import render, NowPlayingContext
    ctx = NowPlayingContext(
        compact=False, max_width=w, current_track="/m/14-GCN-normal.mp3",
        current_track_hour=14, hour=14, tpos=72.0, dur=180.0, showing_chime=False,
        chime_kind=None, repeat_current=True, track_pick_reason="weighted random",
        background_mode=False, muted=False, game_label="GCN", variant="normal",
        vis_mode="ripple", display_vol=80, vol_flash_str="", remaining=1320,
        pulse_bright=True, title_art=["AC-UI"], title_art_colored=False,
        tod_grad=_clrs._active_tod_grad,
    )
    plain, color = render(ctx)
    assert all(len(p) <= w for p in plain), "plain content exceeds width"
    assert all(len(strip_ansi(c)) <= w for c in color), "color content exceeds width"


def test_preview_frames_visualizer():
    # The visualizer is now its own titled box: mode name on the top border,
    # controls in the secondary bottom notch.
    txt = "\n".join(build_layout_preview(100, 30))
    assert "┐ bars ┌" in txt, "visualizer should be framed with its mode title"
    assert "[t/R]vis" in txt and "[r]fps" in txt
    # A closing bottom border with a btop-style secondary notch exists.
    assert any("┘" in strip_ansi(ln) and "└" in strip_ansi(ln)
               for ln in build_layout_preview(100, 30))


def test_preview_now_playing_shows_help_hint():
    txt = "\n".join(build_layout_preview(120, 40))
    assert "[?]help" in txt


def test_preview_spectrum_fills_tall_terminal():
    # The spectrum must expand to fill leftover rows (no big blank gap), so a
    # tall terminal should leave only a couple of blank separator lines.
    out = build_layout_preview(60, 44)
    blanks = sum(1 for ln in out if ln.strip() == "")
    assert blanks < 6, f"too many blank rows ({blanks}) — spectrum not expanding"

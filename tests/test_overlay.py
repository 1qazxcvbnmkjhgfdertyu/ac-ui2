"""Tests for live overlays composited over the animating frame (overlay.py)."""
from ac_ui.colors import c256, strip_ansi, visible_len
from ac_ui.finder import make_item
from ac_ui.overlay import (
    FinderOverlay,
    HelpOverlay,
    MenuOverlay,
    PaletteOverlay,
    ViewerOverlay,
    VisFpsOverlay,
    _drop_cols,
    _overlay_row,
    composite_over,
)


def _live_frame(cols, rows):
    """A fake visualizer frame: every cell a coloured block."""
    return [
        "".join(c256("█", (r * 7 + c) % 256) for c in range(cols))
        for r in range(rows)
    ]


def test_drop_cols_removes_visible_columns_keeping_colour():
    s = c256("ABC", 200) + c256("DEF", 40)
    assert strip_ansi(_drop_cols(s, 3)) == "DEF"
    assert strip_ansi(_drop_cols(s, 0)) == "ABCDEF"
    assert strip_ansi(_drop_cols(s, 6)) == ""


def test_overlay_row_splices_box_into_colored_base():
    base = c256("█" * 40, 123)
    seg = "[BOX]"
    row = _overlay_row(base, seg, start_col=10, cols=40)
    plain = strip_ansi(row)
    # box sits at column 10, live blocks remain on both sides, width preserved
    assert plain[10:15] == "[BOX]"
    assert plain[:10] == "█" * 10
    assert plain.endswith("█")
    assert visible_len(row) == 40


def test_composite_preserves_width_and_keeps_frame_visible():
    cols, rows = 80, 24
    base = _live_frame(cols, rows)
    box = VisFpsOverlay({"fast": 60, "normal": 30, "heavy": 30}).build(cols, rows)
    out = composite_over(base, box, cols, rows)
    assert len(out) == rows
    assert all(visible_len(line) == cols for line in out)
    # top row is outside the centred box -> untouched live frame
    assert set(strip_ansi(out[0])) == {"█"}
    # the box (with its title) is drawn somewhere in the middle
    joined = "\n".join(strip_ansi(line) for line in out)
    assert "frame rate" in joined


def test_vis_fps_overlay_single_rate_saves_uniform_map():
    ov = VisFpsOverlay({"fast": 60, "normal": 60, "heavy": 60})
    assert ov.fps == 60
    assert ov.handle("LEFT") is False  # one knob: step the single rate down
    assert ov.fps == 45
    assert ov.handle("\r") is True
    # saved value applies to *every* tier (uniform map, unchanged on-disk format)
    assert ov.result == {"fast": 45, "normal": 45, "heavy": 45}


def test_vis_fps_overlay_seeds_from_highest_existing_rate():
    ov = VisFpsOverlay({"fast": 60, "normal": 30, "heavy": 24})
    assert ov.fps == 60


def test_vis_fps_overlay_cancel_returns_none():
    ov = VisFpsOverlay({"fast": 60, "normal": 60, "heavy": 60})
    ov.handle("RIGHT")  # make an edit
    assert ov.handle("ESC") is True
    assert ov.result is None


# Every live overlay must (a) build a box that composites without width drift and
# leaves the frame visible around it, and (b) report a stable `kind`.
def _all_overlays():
    return [
        ("fps", VisFpsOverlay({"fast": 60, "normal": 30, "heavy": 30})),
        ("palette", PaletteOverlay()),
        ("finder", FinderOverlay("Find", [make_item("Song A", "a"), make_item("Song B", "b")])),
        ("menu", MenuOverlay("Actions", [("Play now", "play"), ("Pin", "pin")])),
        ("help", HelpOverlay()),
        ("viewer", ViewerOverlay("Zoom", [f"line {i}" for i in range(40)], None)),
    ]


def test_every_overlay_composites_over_live_frame():
    cols, rows = 90, 28
    base = _live_frame(cols, rows)
    for kind, ov in _all_overlays():
        assert ov.kind == kind
        out = composite_over(base, ov.build(cols, rows), cols, rows)
        assert all(visible_len(line) == cols for line in out), f"{kind} width drift"
        assert set(strip_ansi(out[0])) == {"█"}, f"{kind} top row not live"


def test_palette_navigation_and_selection():
    ov = PaletteOverlay()
    ov.build(90, 28)
    assert ov.handle("DOWN") is False
    ov.build(90, 28)
    assert ov.handle("\r") is True
    assert isinstance(ov.result, str) and ov.result  # a re-dispatchable key


def test_finder_query_narrows_and_enter_selects():
    ov = FinderOverlay("F", [make_item("Apple", "a"), make_item("Banana", "b")])
    ov.build(90, 28)
    for ch in "ban":
        ov.handle(ch)
        ov.build(90, 28)
    assert ov.handle("\r") is True
    assert ov.result == "b"


def test_menu_number_shortcut_and_cancel():
    ov = MenuOverlay("Actions", [("Play now", "play"), ("Pin", "pin")])
    assert ov.handle("2") is True
    assert ov.result == "pin"
    ov2 = MenuOverlay("Actions", [("Play now", "play")])
    assert ov2.handle("ESC") is True
    assert ov2.result is None


def test_help_and_viewer_scroll_and_dismiss():
    h = HelpOverlay()
    h.build(90, 28)
    h.handle("DOWN")
    assert h.handle("ESC") is True and h.result is None
    v = ViewerOverlay("V", [f"row {i}" for i in range(50)], None)
    v.build(90, 28)
    v.handle("PAGEDOWN")
    assert v.scroll > 0
    assert v.handle("q") is True and v.result is None


def test_help_drill_in_detail_is_a_layer_over_the_list():
    from ac_ui.colors import strip_ansi
    h = HelpOverlay()
    h.handle("DOWN")
    h.build(90, 30)
    # Enter opens the detail popup (third layer); it stays open (handle->False).
    assert h.handle("\r") is False
    assert h.detail_open is True
    box = h.build(90, 30)
    text = "\n".join(strip_ansi(line) for line in box)
    assert "[esc] back" in text  # the detail popup is composited over the list
    # Esc closes the detail layer only, not the whole help screen…
    assert h.handle("ESC") is False and h.detail_open is False
    # …a second Esc closes help.
    assert h.handle("ESC") is True


def test_help_typing_filters_and_resets_selection():
    h = HelpOverlay()
    h.build(90, 30)
    h.selected = 3
    h.handle("t")  # typing filters the list
    assert h.query == "t" and h.selected == 0

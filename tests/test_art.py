"""Tests for the procedural album-art mosaic."""
import pytest

from ac_ui.colors import strip_ansi
from ac_ui.art import game_mosaic


@pytest.mark.parametrize("w,h", [(10, 5), (14, 6), (18, 7), (1, 1)])
def test_mosaic_dimensions(w, h):
    for color in (True, False):
        plain, col = game_mosaic("GCN:normal", w, h, use_color=color)
        assert len(plain) == h and len(col) == h
        for p in plain:
            assert len(p) == w
        for c in col:
            assert len(strip_ansi(c)) == w


def test_mosaic_deterministic():
    a, _ = game_mosaic("WW:rainy", 14, 6, use_color=False)
    b, _ = game_mosaic("WW:rainy", 14, 6, use_color=False)
    assert a == b


def test_mosaic_varies_by_seed():
    a, _ = game_mosaic("GCN:normal", 14, 6, use_color=False)
    b, _ = game_mosaic("NH:snowy", 14, 6, use_color=False)
    assert a != b


def test_mosaic_is_horizontally_symmetric():
    plain, _ = game_mosaic("AF:town", 16, 6, use_color=False)
    for row in plain:
        assert row == row[::-1], f"row not mirrored: {row!r}"


def test_now_playing_uses_side_art_when_wide():
    import ac_ui.colors as _clrs
    from ac_ui.panels.now_playing import render, NowPlayingContext
    ctx = NowPlayingContext(
        compact=False, max_width=80, current_track="/m/14-GCN-normal.mp3",
        current_track_hour=14, hour=14, tpos=30.0, dur=180.0, showing_chime=False,
        chime_kind=None, repeat_current=False, track_pick_reason="weighted random",
        background_mode=False, muted=False, game_label="GCN", variant="normal",
        vis_mode="bars", display_vol=80, vol_flash_str="", remaining=1800,
        pulse_bright=True, title_art=["AC-UI"], title_art_colored=False,
        tod_grad=_clrs._active_tod_grad,
    )
    plain, color = render(ctx)
    # Track info still present, and a mosaic block char leads the first row.
    assert any("GCN" in s for s in plain)
    assert any(ch in plain[0] for ch in "█▓▒"), "expected mosaic on the left"
    assert len(plain) == len(color)


def test_now_playing_no_side_art_when_narrow():
    import ac_ui.colors as _clrs
    from ac_ui.panels.now_playing import render, NowPlayingContext
    ctx = NowPlayingContext(
        compact=False, max_width=40, current_track="/m/14-GCN-normal.mp3",
        current_track_hour=14, hour=14, tpos=30.0, dur=180.0, showing_chime=False,
        chime_kind=None, repeat_current=False, track_pick_reason="x",
        background_mode=False, muted=False, game_label="GCN", variant="normal",
        vis_mode="bars", display_vol=80, vol_flash_str="", remaining=1800,
        pulse_bright=True, title_art=["AC-UI"], title_art_colored=False,
        tod_grad=_clrs._active_tod_grad,
    )
    plain, _ = render(ctx)
    # Narrow → no mosaic; the AC-UI title art leads instead.
    assert "AC-UI" in plain[0]

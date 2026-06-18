import importlib
import os


from ac_ui.app import apply_cli_runtime_env
from ac_ui.colors import detect_terminal_capabilities


def test_apply_cli_runtime_env_sets_display_overrides(monkeypatch):
    monkeypatch.delenv("AC_UI_COLOR_MODE", raising=False)
    monkeypatch.delenv("AC_UI_ASCII_ONLY", raising=False)
    monkeypatch.delenv("AC_UI_CAVA_BARS", raising=False)

    argv = [
        "ac-ui",
        "--true-color",
        "--ascii-only",
        "--bars",
        "40",
        "--vis",
        "braille",
    ]
    cleaned = apply_cli_runtime_env(argv)

    assert cleaned == ["ac-ui", "--vis", "braille"]
    assert os.environ["AC_UI_COLOR_MODE"] == "truecolor"
    assert os.environ["AC_UI_ASCII_ONLY"] == "1"
    assert os.environ["AC_UI_CAVA_BARS"] == "40"


def test_apply_cli_runtime_env_accepts_equals_style_bar_override(monkeypatch):
    monkeypatch.delenv("AC_UI_CAVA_BARS", raising=False)

    cleaned = apply_cli_runtime_env(["ac-ui", "--bars=52", "--vis", "bars"])

    assert cleaned == ["ac-ui", "--vis", "bars"]
    assert os.environ["AC_UI_CAVA_BARS"] == "52"


def test_detect_terminal_capabilities_respects_auto_and_overrides():
    caps = detect_terminal_capabilities(
        {"TERM": "xterm-256color", "COLORTERM": "", "NO_COLOR": ""},
        stdout_encoding="UTF-8",
    )
    assert caps.color_mode == "none"
    assert not caps.use_color

    caps = detect_terminal_capabilities(
        {"TERM": "screen-256color", "AC_UI_COLOR_MODE": "truecolor"},
        stdout_encoding="UTF-8",
    )
    assert caps.color_mode == "truecolor"
    assert caps.truecolor

    caps = detect_terminal_capabilities(
        {"TERM": "xterm", "AC_UI_ASCII_ONLY": "1"},
        stdout_encoding="UTF-8",
    )
    assert caps.color_mode == "16"
    assert caps.ascii_only
    assert not caps.braille_ok


def test_tty_mode_forces_plain_ascii_no_color():
    # AC_UI_TTY = accessible mode: overrides truecolor, forces ASCII + no color.
    caps = detect_terminal_capabilities(
        {"TERM": "xterm-256color", "COLORTERM": "truecolor", "AC_UI_TTY": "1"},
        stdout_encoding="UTF-8",
    )
    assert caps.color_mode == "none"
    assert not caps.use_color
    assert caps.ascii_only
    assert not caps.braille_ok


def test_ascii_only_mode_falls_back_from_braille(monkeypatch):
    import ac_ui.colors as colors
    import ac_ui.visualizer as visualizer

    monkeypatch.setenv("AC_UI_ASCII_ONLY", "1")
    monkeypatch.setenv("AC_UI_COLOR_MODE", "16")
    try:
        colors = importlib.reload(colors)
        visualizer = importlib.reload(visualizer)

        ctx = visualizer.VisFrameCtx({}, use_color=False)
        rows = visualizer.render_frame("braille", [0.7] * 24, 5, 20, ctx)
        assert ctx.label == "braille/ascii"
        assert colors.theme_chrome()["box_chars"]["tl"] == "+"
        assert all(len(row) == 20 for row in rows)
        assert not any(
            0x2800 <= ord(ch) <= 0x28FF
            for row in rows
            for ch in row
            if ch != " "
        )
    finally:
        monkeypatch.delenv("AC_UI_ASCII_ONLY", raising=False)
        monkeypatch.delenv("AC_UI_COLOR_MODE", raising=False)
        importlib.reload(colors)
        importlib.reload(visualizer)


def test_ascii_only_mode_reaches_panels_and_helpers(monkeypatch):
    import ac_ui.constants as constants
    import ac_ui.colors as colors
    import ac_ui.editors as editors
    import ac_ui.meters as meters
    import ac_ui.art as art
    import ac_ui.layout as layout
    import ac_ui.stats as stats
    from ac_ui.panels import now_playing

    monkeypatch.setenv("AC_UI_ASCII_ONLY", "1")
    monkeypatch.setenv("AC_UI_COLOR_MODE", "16")
    try:
        constants = importlib.reload(constants)
        colors = importlib.reload(colors)
        editors = importlib.reload(editors)
        meters = importlib.reload(meters)
        art = importlib.reload(art)
        layout = importlib.reload(layout)
        stats = importlib.reload(stats)
        now_playing = importlib.reload(now_playing)

        assert constants.SYM_NOTE == "*"
        assert constants.SYM_HIST_MARKER == "^"
        assert constants.SYM_SELECT == ">"
        assert constants.SYM_ROUTE == "->"
        assert constants.BOX_CHARS["tl"] == "+"
        assert not any(ch in "".join(constants.HELP_LINES_BASE) for ch in "↑↓←→±")
        assert any("[tab] focus panel" in line for line in constants.HELP_LINES_BASE)

        meter = meters.meter_bar(50, 12, use_color=False)
        assert len(colors.strip_ansi(meter)) == 12
        assert "█" not in meter and "─" not in meter

        graph = meters.braille_graph([0.2, 0.5, 1.0], 12, 2, use_color=False)
        assert len(graph) == 2
        assert not any(0x2800 <= ord(ch) <= 0x28FF for row in graph for ch in row if ch != " ")

        plain_art, _ = art.game_mosaic("GCN:normal", 10, 4, use_color=False)
        assert any(ch in "@#*" for row in plain_art for ch in row)
        assert not any(ch in "█▓▒" for row in plain_art for ch in row)

        browse_lines = editors._editor_render_browse(
            "/tmp",
            [("Shared Tracks", "/tmp/shared", "audio_dir"), ("Song.mp3", "/tmp/song.mp3", "audio")],
            0,
            48,
            8,
        )
        browse_joined = "\n".join(colors.strip_ansi(line) for line in browse_lines)
        assert "▶" not in browse_joined
        assert "♪" not in browse_joined
        assert "─" not in browse_joined

        queue_lines = editors._queue_render(
            ["/tmp/a.mp3", "/tmp/b.mp3"],
            0,
            0,
            "/tmp/a.mp3",
            0,
            None,
            48,
            8,
        )
        queue_joined = "\n".join(colors.strip_ansi(line) for line in queue_lines)
        assert "▶" not in queue_joined
        assert "♪" not in queue_joined
        assert "·" not in queue_joined
        assert "─" not in queue_joined

        add_lines = editors._add_to_playlist_render(
            "Song.mp3",
            [("/tmp/mix.acpl", "Mix", 4, ".acpl")],
            1,
            None,
            False,
            [],
            0,
            48,
            8,
        )
        add_joined = "\n".join(colors.strip_ansi(line) for line in add_lines)
        assert "…" not in add_joined

        hist_plain, marker_plain, _axis_plain = stats.build_hour_histogram_lines([0, 1] * 12, 6, 12)
        assert "^" in marker_plain
        assert not any(ch in "▁▂▃▄▅▆▇█▴" for ch in hist_plain + marker_plain)

        header = layout.build_header_bar(40, "12:34:56", 0.5, colors._active_tod_grad, "/m/song.mp3", False, False)
        assert "*" in colors.strip_ansi(header)
        assert "♪" not in colors.strip_ansi(header)

        ctx = now_playing.NowPlayingContext(
            compact=False,
            max_width=60,
            current_track="/m/14-GCN-normal.mp3",
            current_track_hour=14,
            hour=14,
            tpos=30.0,
            dur=180.0,
            showing_chime=True,
            chime_kind="hour chime",
            repeat_current=False,
            track_pick_reason="weighted random",
            background_mode=False,
            muted=True,
            game_label="GCN",
            variant="normal",
            vis_mode="bars",
            display_vol=80,
            vol_flash_str="",
            remaining=1800,
            pulse_bright=True,
            title_art=["AC-UI"],
            title_art_colored=False,
            tod_grad=colors._active_tod_grad,
        )
        plain, color = now_playing.render(ctx)
        joined = "\n".join(plain)
        assert "* (hour chime)" in joined
        assert "♪" not in joined
        assert all("◆" not in colors.strip_ansi(line) for line in color)
    finally:
        monkeypatch.delenv("AC_UI_ASCII_ONLY", raising=False)
        monkeypatch.delenv("AC_UI_COLOR_MODE", raising=False)
        importlib.reload(constants)
        importlib.reload(colors)
        importlib.reload(meters)
        importlib.reload(art)
        importlib.reload(layout)
        importlib.reload(stats)
        importlib.reload(now_playing)

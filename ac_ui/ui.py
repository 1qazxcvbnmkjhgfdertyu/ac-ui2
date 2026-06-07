import os, sys, time, random, subprocess, json, signal, threading, shutil, re, queue, textwrap, tempfile, struct, math, errno, stat, wave, unicodedata
from collections import deque

import ac_ui.colors as _clrs
import ac_ui.layout as _layout
import ac_ui.term as _term
from ac_ui.colors import (
    USE_COLOR, c, c256, gradient_at, gradient_bar, solid_bar,
    superscript_num, humanize_seconds, humanize_bytes,
    _GRAD_PLAYBACK, _GRAD_VOLUME,
    _grad_for_hour, set_theme, get_theme, THEME_NAMES,
    plain_visible_len, strip_ansi, smoothing_alpha_ms,
)
import ac_ui.colors as _clrs  # for _clrs._active_tod_grad (mutable module global)
from ac_ui.constants import (
    MUSIC_DIR, MPV, CAVA_HEIGHT, CAVA_MAX, CAVA_MIN_BARS, CAVA_MARGIN,
    REFRESH_INTERVAL, IDLE_REFRESH, RESIZE_DEBOUNCE,
    VIS_MODES, VIS_MODE, GRADIENT_ANIMATE, GRADIENT_SPEED,
    VIS_ATTACK_MS, VIS_DECAY_MS, VIS_PEAK_DECAY_MS, VIS_TRAIL_DECAY_MS,
    TITLE_ANIMATE, TITLE_ANIM_FPS, BOX_BORDER_SPIN, BOX_BORDER_SPEED,
    FOCUS_THROTTLE, SHOW_TITLE_ART, DEBUG_ART, NO_MOTION,
    STATS_ENABLED, CROSSFADE_SECONDS, PRIVATE_SINK, OUTPUT_SINK,
    AUDIO_DEVICE_OVERRIDE, MUTE_MODE, HISTORY_MAX, QUEUE_SIZE, UP_NEXT_MAX,
    TRACK_REPEAT_GUARD,
    SYM_ELLIPSIS, SYM_MUTE, SYM_VOL_UP, SYM_VOL_DN, SYM_PLAY, SYM_PAUSE,
    FILENAME_RE, TRACK_LIST_CACHE, HELP_LINES_BASE,
    AUDIO_WARMUP_GRACE, BOX_CHARS, BOX_BORDER_HILITE_LEN,
    _resolve_command_path, DEFAULT_LAYOUT_PRESET, normalize_vis_mode,
)
from ac_ui.term import (
    TITLE_ART,
    build_title_art, render, _read_key, invalidate_render_cache,
    hide_cursor, show_cursor, enable_autowrap, disable_autowrap,
    enter_alt_screen, exit_alt_screen, truncate_plain, truncate_ansi_visible,
    RawMode,
)
from ac_ui.tracks import (
    list_tracks_for_hour, pick_weighted, next_hour_epoch, fmt_mmss,
    collect_catalog, import_files, hh_folder,
    parse_filename, invalidate_track_cache, filter_recent_tracks,
    playback_mode_label,
)
from ac_ui.audio import (
    mpv_start, mpv_command, mpv_query, mpv_query_props,
    detect_cava_input, setup_private_sink, teardown_private_sink,
    set_loopback_volume, set_loopback_mute, reload_loopback,
    list_sinks, get_default_sink, get_mute_volume, start_hour_chime,
    cleanup_legacy_runtime_artifacts, build_cava_input_candidates,
    cava_config_text, calc_cava_bars, pulse_monitor_source_for_audio_device,
    cleanup_stale_socket, find_loopback_input_ids,
)
from ac_ui.town_tune import _wait_for_ipc_socket
from ac_ui.visualizer import (
    spectrum_lines, flame_render_lines, braille_wave_lines, braille_scope_lines,
    butterfly_render_lines, led_matrix_lines, matrix_rain_lines,
    heartbeat_render_lines, braille_spectrum_lines,
)
from ac_ui.layout import (
    build_box, pad_box_lines, build_footer_controls,
    wrap_plain, combine_render_columns, stack_render_blocks,
    colorize_hint_keys, format_filter_summary,
    build_ultra_compact_summary, format_visualizer_status,
    layout_mode_for_size, layout_min_spectrum_rows, layout_base_spectrum_rows,
    box_outer_width,
)
from ac_ui.layout_config import (
    normalize_layout_preset, default_layout_config, normalize_layout_config,
    cycle_layout_preset, layout_preset_label, layout_panels_in_slot,
    _int_opt, _str_opt,
)
from ac_ui.layout_engine import resolve_layout, resolve_panel_max_width
from ac_ui.stats import (
    load_stats, save_stats, append_stats_csv, start_stats_writer, stats_cli,
    build_hour_histogram_lines, format_seconds,
)
from ac_ui.eq import load_eq_bands, save_eq_bands, apply_mpv_eq, build_mpv_eq_filter
from ac_ui.persist import load_ui_state, save_ui_state
from ac_ui.town_tune import town_tune_cli, normalize_town_tune
from ac_ui.editors import run_eq_editor, run_tune_editor

_active_tod_grad = _clrs._active_tod_grad

def parse_cli_args(argv):
    mode = "run"
    games = None
    vis_mode = None
    import_paths = []
    tune_action = None
    layout_opts = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print("Usage:")
            print("  ac-ui [--games GCN,WW] [--vis MODE]")
            print("  ac-ui import <files...>")
            print("  ac-ui tune [show|play|reset]")
            print("  ac-ui stats")
            print("  ac-ui layout-sweep")
            print()
            print("Keys (in-app):")
            print("  n  next track    m/space  mute   T  town tune   E  EQ editor")
            print("  g  cycle game    v  variant   t  vis next   R  vis random")
            print("  h  simulate hour change       s  audio sink   l  repeat current track")
            print("  L  cycle layout preset")
            print("  +/-  volume ±5   PgUp/Dn volume ±10")
            print("  8  background mode   ?  help   q  quit")
            print()
            print(f"Vis modes: {', '.join(VIS_MODES)}")
            print()
            print("Env vars: AC_UI_MUSIC_DIR, AC_UI_MPV, AC_UI_VIS, AC_UI_REFRESH,")
            print("          AC_UI_CAVA_SOURCE, AC_UI_EQ_PATH, AC_UI_STATS,")
            print("          AC_UI_VIS_ATTACK_MS, AC_UI_VIS_DECAY_MS,")
            print("          AC_UI_LOOPBACK_LATENCY_MSEC, AC_UI_REPEAT_GUARD,")
            print("          AC_UI_LAYOUT_PRESET")
            sys.exit(0)
        if arg == "import":
            mode = "import"
            import_paths = argv[i + 1:]
            break
        if arg == "tune":
            mode = "tune"
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                tune_action = argv[i + 1]
            break
        if arg == "stats":
            mode = "stats"
            break
        if arg == "layout-sweep":
            mode = "layout-sweep"
            layout_opts = {}
            i += 1
            while i < len(argv):
                if argv[i].startswith("--"):
                    key = argv[i][2:].replace("-", "_")
                    if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                        layout_opts[key] = argv[i + 1]
                        i += 1
                    else:
                        layout_opts[key] = "1"
                i += 1
            break
        if arg.startswith("--games="):
            games = arg.split("=", 1)[1]
        elif arg == "--games" and i + 1 < len(argv):
            games = argv[i + 1]
            i += 1
        elif arg.startswith("--vis="):
            vis_mode = arg.split("=", 1)[1]
        elif arg == "--vis" and i + 1 < len(argv):
            vis_mode = argv[i + 1]
            i += 1
        i += 1
    if games:
        games = {g.strip().upper() for g in games.split(",") if g.strip()}
    if vis_mode is not None:
        vis_mode = normalize_vis_mode(vis_mode, default=VIS_MODE)
    return mode, games, vis_mode, import_paths, tune_action, layout_opts

def build_layout_preview(term_cols, term_rows, layout_config=None):
    # Minimal, deterministic preview for layout debugging
    hour = 14
    remaining = 30 * 60 + 44
    current_track = "/music/14-GCN-normal.mp3"
    current_track_hour = 14
    output_vol = 75
    muted = False
    repeat_current = False
    history = deque(["14-GCN-normal.mp3"])
    next_candidates = [
        "14-GCN-cheery.mp3",
        "14-NH-winter.flac",
        "14-NH-rainy.flac",
        "... +2 more",
    ]
    showing_chime = False
    chime_kind = None
    vis_idx = 0
    stats_data = {
        "total_listen_seconds": 16,
        "hour_buckets": [0] * 24,
    }
    stats_data["hour_buckets"][14] = 16
    session_listen = 16

    # Layout sizing (mirror main loop logic)
    layout_mode = layout_mode_for_size(term_cols, term_rows)
    tiny_term = layout_mode == "tiny"
    small_term = layout_mode in ("tiny", "small")
    ultra_compact = term_rows < 10
    info_max_width = max(10, term_cols - 5)
    footer_lines, footer_sep = build_footer_controls(term_cols, term_rows, tiny_term=tiny_term, ultra_compact=ultra_compact)
    footer_rows = len(footer_lines) + (1 if footer_sep else 0)
    min_spectrum_rows = layout_min_spectrum_rows(term_rows, layout_mode)
    base_spectrum = layout_base_spectrum_rows(layout_mode, ultra_compact)
    spectrum_height = max(min_spectrum_rows, base_spectrum)

    lines = []
    info = []
    info_plain = []
    def add_info_line(text, color_code="2"):
        text = truncate_plain(text, info_max_width)
        info_plain.append(text)
        info.append(c(text, color_code))

    tline = f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    lines.append(c(tline, "2"))

    max_info_rows = term_rows - min_spectrum_rows - footer_rows - 1 - 2
    compact_info = max_info_rows < 10 or term_cols < 70 or ultra_compact

    if ultra_compact:
        summary = truncate_plain(
            build_ultra_compact_summary("ALL", "ALL", VIS_MODES[vis_idx], remaining, output_vol, muted, showing_chime, chime_kind, repeat_current=repeat_current),
            max(10, term_cols - 2),
        )
        lines.append(c(summary, "2"))
    else:
        if (not compact_info):
            title = ["AC-UI"]
            _art_col = gradient_at(_active_tod_grad, 70)
            info.extend([c256(line, _art_col) for line in title])
            info_plain.extend([line for line in title])

        fline = "Filter: Game=ALL  Variant=ALL"
        add_info_line(fline, "2")
        vline = f"Visualizer: {VIS_MODES[vis_idx]}  [{playback_mode_label(repeat_current)}]"
        add_info_line(vline, "2")
        if showing_chime:
            label = chime_kind or "hour chime"
            line1_plain = f"Hour folder: --    Now playing: ({label})"
            add_info_line(line1_plain, "36")
        elif current_track:
            _track_meta = parse_filename(os.path.basename(current_track))
            _display = f"{_track_meta['game']}: {_track_meta['variant']}" if _track_meta else os.path.basename(current_track)
            line1_plain = f"Hour folder: {current_track_hour:02d}    Now playing: {_display}"
            add_info_line(line1_plain, "36")
            if not compact_info:
                line2_plain = "Playback: 00:16 / 02:19"
                add_info_line(line2_plain, "35")
            if not compact_info:
                mute_tag = "  [MUTED]" if muted else ""
                add_info_line(f"Volume: {int(output_vol):3d}%{mute_tag}", "33")
        else:
            line1_plain = f"Hour folder: {hour:02d}    Now playing: (none found)"
            add_info_line(line1_plain, "36")
        if not compact_info:
            add_info_line("", "2")
        ulabel = "Until next hour:"
        uvalue = f"{remaining//60:02d}:{remaining%60:02d}"
        uline = f"{ulabel} {uvalue}"
        add_info_line(uline, "95")

    info_box = None
    info_w = 0
    if not ultra_compact:
        if max_info_rows <= 0:
            info_plain = []
            info = []
        elif len(info_plain) > max_info_rows:
            info_plain = info_plain[:max_info_rows]
            info = info[:max_info_rows]
        if info_plain:
            info_w_needed = max([plain_visible_len(line) for line in info_plain] + [0])
            info_w_cache = min(info_max_width, info_w_needed)
            info_box, info_w = build_box(info_plain, info, info_w_cache, title="Now Playing")

    stats_box = None
    stats_w = 0
    if (not ultra_compact) and STATS_ENABLED and stats_data is not None:
        total_sec = int(stats_data.get("total_listen_seconds", 0) + session_listen)
        hb = stats_data.get("hour_buckets", [0] * 24)
        top = sorted([(i, v) for i, v in enumerate(hb)], key=lambda x: x[1], reverse=True)[:3]
        top_fmt = ", ".join([f"{h:02d}:00" for h, v in top if v > 0]) or "(none yet)"
        stats_inner_width = max(28, min(info_max_width, max(28, term_cols - 12)))
        hist_plain, marker_plain, axis_plain = build_hour_histogram_lines(hb, hour, stats_inner_width)
        stats_plain = [
            truncate_plain(f"Total listening: {format_seconds(total_sec)}", stats_inner_width),
            truncate_plain(f"This session: {format_seconds(session_listen)}", stats_inner_width),
            truncate_plain(f"Most-listened hours: {top_fmt}", stats_inner_width),
            hist_plain,
            marker_plain,
            axis_plain,
        ]
        stats_color = [
            c(stats_plain[0], "2"),
            c(stats_plain[1], "2"),
            c(stats_plain[2], "2"),
            c(stats_plain[3], "2"),
            c(stats_plain[4], "2"),
            c(stats_plain[5], "2"),
        ]
        stats_box, stats_w = build_box(stats_plain, stats_color, maxw_override=stats_inner_width, title="Stats")

    layout_state = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)
    max_content_end = term_rows - min_spectrum_rows - footer_rows - 1
    show_history = (not tiny_term) and (not ultra_compact) and (not compact_info)
    show_up_next = (not (tiny_term or small_term)) and (not ultra_compact) and (not compact_info)
    layout_preset = layout_state["preset"]
    if layout_preset == "two_rail":
        panel_max_width = max(18, min(28, max(18, (term_cols - 11) // 3)))
    else:
        panel_max_width = max(14, min(28, max(14, (term_cols - 11) // 2)))

    hist_box = None
    hist_w = 0
    up_box = None
    up_w = 0
    if show_history:
        hist_title = "Recently played"
        hist_title_trunc = truncate_plain(hist_title, panel_max_width)
        hist_list = list(history)[-HISTORY_MAX:]
        def _fmt_hist(name):
            meta = parse_filename(name)
            if meta:
                return f"{meta['game']}: {meta['variant']}"
            return name
        hist_lines = [hist_title_trunc] + ([_fmt_hist(s) for s in hist_list] if hist_list else ["(none yet)"])
        hist_lines = [truncate_plain(s, panel_max_width) for s in hist_lines]
        hist_color = [c(hist_title_trunc, "36")] + [c(s, "2") for s in hist_lines[1:]]
        hist_box, hist_w = build_box(hist_lines, hist_color, maxw_override=panel_max_width, title="History")

    if show_up_next:
        if next_candidates:
            def _fmt_candidate(name):
                meta = parse_filename(name)
                if meta:
                    return f"{meta['game']}: {meta['variant']}"
                return name
            shown = [_fmt_candidate(s) for s in next_candidates[:UP_NEXT_MAX]]
            if len(next_candidates) > UP_NEXT_MAX:
                shown.append(f"{SYM_ELLIPSIS} +{len(next_candidates) - UP_NEXT_MAX} more")
            header_plain = f"Up next ({min(len(next_candidates), UP_NEXT_MAX)}/{len(next_candidates)})"
            header_plain_trunc = truncate_plain(header_plain, panel_max_width)
            up_plain = [header_plain_trunc] + shown
            up_plain = [truncate_plain(s, panel_max_width) for s in up_plain]
            up_color = [c(header_plain_trunc, "36")] + [c(s, "2") for s in up_plain[1:]]
        else:
            up_title = "Up next"
            up_title_trunc = truncate_plain(up_title, panel_max_width)
            up_plain = [up_title_trunc, "(no candidates)"]
            up_plain = [truncate_plain(s, panel_max_width) for s in up_plain]
            up_color = [c(up_title_trunc, "36"), c("(no candidates)", "2")]
        up_box, up_w = build_box(up_plain, up_color, maxw_override=panel_max_width, title="Up Next")

    panel_boxes = {
        "history": (hist_box, box_outer_width(hist_w)),
        "up_next": (up_box, box_outer_width(up_w)),
    }
    active_sidebar = [name for name in layout_panels_in_slot(layout_state, "sidebar") if panel_boxes.get(name, (None, 0))[0]]
    active_below = [name for name in layout_panels_in_slot(layout_state, "below") if panel_boxes.get(name, (None, 0))[0]]
    main_outer_width = 0

    if info_box:
        info_box_fit = info_box
        info_w_fit = info_w
        top_lines = None
        sidebar_names = list(active_sidebar)
        min_info_sidebar_width = 28
        while sidebar_names:
            sidebar_lines, sidebar_outer = stack_render_blocks([panel_boxes[name] for name in sidebar_names])
            max_info_inner = term_cols - 3 - sidebar_outer - 4
            if max_info_inner >= min_info_sidebar_width:
                info_target_width = min(info_w, max_info_inner)
                if info_target_width != info_w:
                    info_box_fit, info_w_fit = build_box(info_plain, info, maxw_override=info_target_width, title="Now Playing")
                else:
                    info_box_fit, info_w_fit = info_box, info_w
                candidate_lines, candidate_width = combine_render_columns(
                    [
                        (info_box_fit, box_outer_width(info_w_fit)),
                        (sidebar_lines, sidebar_outer),
                    ]
                )
                if candidate_width <= term_cols and (len(lines) + len(candidate_lines) <= max_content_end):
                    top_lines = candidate_lines
                    active_sidebar = sidebar_names
                    break
            sidebar_names.pop()
        if top_lines is None:
            info_box_fit, info_w_fit = info_box, info_w
            if len(lines) + len(info_box_fit) <= max_content_end:
                top_lines = list(info_box_fit)
                active_sidebar = []
        if top_lines:
            lines.extend(top_lines)
            main_outer_width = box_outer_width(info_w_fit)

    if active_below:
        below_blocks = [panel_boxes[name] for name in active_below]
        below_lines, below_width = combine_render_columns(below_blocks, box_fill=True)
        if below_width > term_cols:
            below_lines, below_width = stack_render_blocks(below_blocks)
        if below_lines and (len(lines) + len(below_lines) <= max_content_end):
            lines.extend(below_lines)
            main_outer_width = max(main_outer_width, below_width)

    if stats_box and (len(lines) + len(stats_box) <= max_content_end):
        lines.extend(stats_box)
        main_outer_width = max(main_outer_width, box_outer_width(stats_w))

    while lines and lines[-1].strip() == "" and (len(lines) + min_spectrum_rows + footer_rows + 1 > term_rows):
        lines.pop()

    prefix = "  "
    rows_used = len(lines)
    available_rows = max(0, term_rows - rows_used - 1 - footer_rows)
    spectrum_height_dyn = min(spectrum_height, max(0, available_rows))
    bars_len = max(10, term_cols - len(prefix) - CAVA_MARGIN)
    mock_bars = [((i % 7) + 1) / 8 for i in range(max(CAVA_MIN_BARS, bars_len))]
    if spectrum_height_dyn > 0:
        bars = mock_bars[:bars_len]
        lines.extend([prefix + ln for ln in spectrum_lines(bars, height=spectrum_height_dyn, use_color=False, mode="bars")])
        _div_label = f" {VIS_MODES[vis_idx]} "
        _div_pad = max(0, bars_len - plain_visible_len(_div_label) - 2)
        _div_l = _div_pad // 2
        _div_r = _div_pad - _div_l
        lines.append(prefix + ("-" * _div_l) + _div_label + ("-" * _div_r))
    if footer_sep and len(lines) < term_rows:
        lines.append("-" * max(1, term_cols - 1))
    for footer_line in footer_lines:
        if len(lines) >= term_rows:
            break
        lines.append(truncate_plain(footer_line, max(1, term_cols - 1)))

    if len(lines) < term_rows:
        lines.extend([""] * (term_rows - len(lines)))
    elif len(lines) > term_rows:
        lines = lines[:term_rows]
    return [strip_ansi(ln) for ln in lines]

def layout_sweep_cli(opts=None):
    opts = opts or {}
    min_rows = max(1, _int_opt(opts, "min_rows", 10))
    max_rows = max(1, _int_opt(opts, "max_rows", 40))
    min_cols = max(1, _int_opt(opts, "min_cols", 60))
    max_cols = max(1, _int_opt(opts, "max_cols", 190))
    step_rows = max(1, _int_opt(opts, "step_rows", 1))
    step_cols = max(1, _int_opt(opts, "step_cols", 1))
    if min_rows > max_rows:
        min_rows, max_rows = max_rows, min_rows
    if min_cols > max_cols:
        min_cols, max_cols = max_cols, min_cols
    layout_config = default_layout_config(_str_opt(opts, "layout_preset", DEFAULT_LAYOUT_PRESET))
    out_dir = os.path.expanduser(_str_opt(opts, "out", "~/.local/share/ac-terminal-radio/layout_sweep"))
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for rows in range(min_rows, max_rows + 1, step_rows):
        for cols in range(min_cols, max_cols + 1, step_cols):
            lines = build_layout_preview(cols, rows, layout_config=layout_config)
            path = os.path.join(out_dir, f"layout_{rows}x{cols}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            count += 1
    print(f"Wrote {count} layout files to {out_dir}")
    return 0

def main():
    ui_state = load_ui_state()
    mode, allowed_games, cli_vis_mode, import_paths, tune_action, layout_opts = parse_cli_args(sys.argv)
    if mode == "import":
        sys.exit(import_files(import_paths))
    if mode == "tune":
        sys.exit(town_tune_cli(tune_action))
    if mode == "stats":
        sys.exit(stats_cli())
    if mode == "layout-sweep":
        sys.exit(layout_sweep_cli(layout_opts))
    if cli_vis_mode:
        ui_state["vis_mode"] = cli_vis_mode
    if not _resolve_command_path(MPV):
        print(f"Missing required player: {MPV}")
        sys.exit(1)
    # basic checks
    if not os.path.isdir(MUSIC_DIR):
        print(f"Missing music dir: {MUSIC_DIR}")
        sys.exit(1)

    if not sys.stdin.isatty():
        print("ac-ui needs to run in a real TTY. Try running it directly in your terminal.")
        sys.exit(1)

    cleanup_legacy_runtime_artifacts()

    # IPC socket path
    instance_tag = f"{os.getuid()}-{os.getpid()}"
    ipc_base = f"/tmp/ac-mpv-{instance_tag}"
    ipc_a = f"{ipc_base}.a.sock"
    ipc_b = f"{ipc_base}.b.sock"
    cava_conf_path = f"/tmp/ac-cava-{instance_tag}.conf"
    private_sink_name = f"acui-{os.getpid()}"
    current_ipc = ipc_a

    mpv_proc = None
    current_track = None
    current_track_hour = None
    last_hour = None
    cava_lock = threading.Lock()
    cava_bars = None
    cava_ok = False
    cava_proc = None
    cava_thread = None
    cava_err = None
    cava_bars_count = None
    resize_pending = False
    last_resize_ts = 0.0
    last_term_cols = None
    last_term_rows = None
    footer_control_lines = []
    footer_has_separator = False
    layout_mode = "normal"
    info_w_cache = 0
    info_cache_key = None
    info_plain_cache = ()
    info_color_cache = ()
    info_box_cache = None
    info_box_cache_key = None
    stats_cache_key = None
    stats_box_cache = None
    stats_w_cache = 0
    help_cache_key = None
    help_box_cache = None
    help_sink_cache = None
    help_sink_cache_ts = 0.0
    hist_cache_key = None
    hist_box_cache = None
    hist_w_cache = 0
    up_cache_key = None
    up_box_cache = None
    up_w_cache = 0

    last_query_ts = 0.0
    mpv_query_interval = 0.5
    cached_tpos = None
    cached_dur = None
    cached_vol = None

    last_render_key = None
    last_render_ts = 0.0
    last_lines = None
    last_loopback_ts = 0.0
    last_loopback_vol = None
    last_loopback_muted = None
    term_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    art_lines, art_colored, art_base, lolcat_path = build_title_art("AC-UI", term_cols)
    TITLE_ART[:] = art_lines
    _term.TITLE_ART_COLORED = art_colored
    _term.TITLE_ART_BASE = art_base
    _term.TITLE_LOLCAT_PATH = lolcat_path
    _term.TITLE_ART_VERSION += 1
    if DEBUG_ART:
        has_ansi = any("\x1b[" in ln for ln in TITLE_ART)
        sys.stderr.write(
            f"AC_UI_DEBUG_ART: show={SHOW_TITLE_ART} color={USE_COLOR} colored={_term.TITLE_ART_COLORED} "
            f"figlet={shutil.which('figlet')} lolcat={shutil.which('lolcat')} ansi={has_ansi}\n"
        )
    bars_len_cached = None
    bars_len_cols = term_cols
    bars_len_count = None
    last_mute_toggle_ts = 0.0
    last_key = ""
    last_key_ts = 0.0
    vis_idx = VIS_MODES.index(ui_state["vis_mode"]) if ui_state["vis_mode"] in VIS_MODES else VIS_MODES.index(VIS_MODE)
    _saved_theme = ui_state.get("theme", "default")
    if _saved_theme in THEME_NAMES:
        set_theme(_saved_theme)
    smooth_bars = None
    peak_bars = None
    trail_bars = None
    _bass_energy = 0.0
    last_vis_update_ts = None
    cap_pos = None    # per-bar peak cap positions for physics-based "peaks" mode
    cap_vel = None    # per-bar peak cap velocities
    # btop data_same: cache spectrum lines when smoothed bars haven't changed
    _vis_line_cache = None
    _vis_line_cache_key = None
    flame_state = {"heat": None, "rng": 0xF1A3C0DE0BADCAFE, "frame": 0, "rows": 0, "cols": 0}
    butterfly_state = {"frame": 0}
    matrix_state = {"frame": 0}
    heartbeat_state = {"buf": None, "prev_bass": 0.0, "spike_phase": 0.0}
    scope_frame = 0
    last_title_anim_ts = 0.0

    muted = ui_state["muted"]
    repeat_current = ui_state["repeat_current"]
    layout_state = normalize_layout_config(ui_state.get("layout"), default_preset=DEFAULT_LAYOUT_PRESET)
    mute_prev_vol = ui_state["mute_prev_vol"]
    vol_delta_flash = None    # (delta, expire_ts) — btop ▲▼ volume indicator
    state_banner = None       # (text, color, expire_ts) — btop state banner
    fade = None
    transition = None
    background_mode = False
    focused = True
    chime_proc = None
    chime_kind = None
    chime_temp_path = None
    showing_chime = False
    show_help = False
    show_debug = False
    debug_frame_times = deque(maxlen=30)
    debug_last_frame_ts = 0.0
    panel_focus = None   # None | "history" | "up_next"
    hist_sel = 0
    up_sel = 0
    show_history_panel = True
    show_up_next_panel = True
    track_pick_reason = None   # str — why the current track was chosen
    banned_tracks = set()      # set of basenames — never auto-play these
    history = deque(maxlen=HISTORY_MAX)
    recent_track_paths = deque(maxlen=max(1, TRACK_REPEAT_GUARD)) if TRACK_REPEAT_GUARD > 0 else None
    next_candidates = []
    next_candidates_ts = 0.0
    next_candidates_key = None
    stats_data = load_stats() if STATS_ENABLED else None
    session_start = time.time()
    session_listen = 0.0
    stats_last_ts = time.time()
    stats_last_flush = time.time()
    stats_q = None
    stats_stop = None
    last_time_str = None
    last_time_sec = None
    cava_started_ts = 0.0
    cava_retry_ts = 0.0
    cava_last_data_ts = 0.0
    cava_last_stderr = ""
    cava_last_label = None
    playback_started_ts = 0.0
    if STATS_ENABLED:
        stats_q, stats_stop = start_stats_writer()

    base_allowed_games = set(allowed_games) if allowed_games else None
    catalog_games, catalog_variants = collect_catalog(base_allowed_games)
    games_list = ["ALL"] + sorted(base_allowed_games or catalog_games)
    variants_list = ["ALL"] + sorted(catalog_variants)
    game_idx = games_list.index(ui_state["game"]) if ui_state["game"] in games_list else 0
    variant_idx = variants_list.index(ui_state["variant"]) if ui_state["variant"] in variants_list else 0

    def current_active_games():
        if game_idx == 0:
            return set(base_allowed_games) if base_allowed_games else None
        return {games_list[game_idx]}

    def current_game_label():
        if game_idx != 0:
            return games_list[game_idx]
        if not base_allowed_games:
            return "ALL"
        labels = sorted(base_allowed_games)
        joined = ",".join(labels)
        if len(joined) <= 18:
            return joined
        if len(labels) == 1:
            return labels[0]
        return f"{len(labels)} games"

    cava_method, cava_source, cava_detect_mode = detect_cava_input()
    private_sink = None
    private_module = None
    loopback_module = None
    audio_device = None
    output_vol = ui_state["output_vol"]
    loopback_q = None
    current_output_sink = None
    # Optional explicit mpv audio device (overrides private sink setup)
    if AUDIO_DEVICE_OVERRIDE:
        audio_device = AUDIO_DEVICE_OVERRIDE
        override_source = pulse_monitor_source_for_audio_device(audio_device)
        if override_source:
            cava_method = "pulse"
            cava_source = override_source
            cava_detect_mode = "audio-device"
    elif PRIVATE_SINK:
        target_sink = OUTPUT_SINK if OUTPUT_SINK else None
        private_sink, private_module, loopback_module, _out_sink = setup_private_sink(target_sink, private_sink_name)
        current_output_sink = _out_sink
        if private_sink:
            cava_method = "pulse"
            cava_source = f"{private_sink}.monitor"
            cava_detect_mode = "private"
            audio_device = f"pulse/{private_sink}"
            if loopback_module:
                set_loopback_volume(loopback_module, private_sink, output_vol)
                loopback_q = queue.Queue()

                def loopback_worker():
                    while True:
                        try:
                            kind, val = loopback_q.get()
                        except Exception:
                            continue
                        if kind == "mute":
                            set_loopback_mute(loopback_module, private_sink, val)
                        elif kind == "volume":
                            set_loopback_volume(loopback_module, private_sink, val)

                threading.Thread(target=loopback_worker, daemon=True).start()
    else:
        # If user specified a sink and we're not using a private sink, point mpv at it.
        if OUTPUT_SINK:
            audio_device = f"pulse/{OUTPUT_SINK}"
            cava_method = "pulse"
            cava_source = f"{OUTPUT_SINK}.monitor"
            cava_detect_mode = "output-sink"
            current_output_sink = OUTPUT_SINK

    cava_candidates = build_cava_input_candidates(
        cava_method,
        cava_source,
        cava_detect_mode,
        audio_device=audio_device,
        private_sink=private_sink,
        output_sink=current_output_sink,
    )
    cava_candidate_idx = 0

    def stop_mpv_proc(proc, ipc_path):
        # Try polite quit
        if ipc_path and os.path.exists(ipc_path):
            try:
                mpv_command(ipc_path, ["quit"])
            except Exception:
                pass
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
        # remove stale socket
        cleanup_stale_socket(ipc_path)
        try:
            if ipc_path and os.path.exists(ipc_path):
                os.remove(ipc_path)
        except Exception:
            pass

    def stop_mpv():
        nonlocal mpv_proc, fade, transition, chime_proc, showing_chime, chime_kind, chime_temp_path
        if fade:
            stop_mpv_proc(fade.get("old_proc"), fade.get("old_ipc"))
            fade = None
        if transition:
            if transition.get("old_proc"):
                stop_mpv_proc(transition.get("old_proc"), transition.get("old_ipc"))
            if transition.get("new_proc"):
                stop_mpv_proc(transition.get("new_proc"), transition.get("new_ipc"))
            transition = None
        if chime_proc and chime_proc.poll() is None:
            try:
                chime_proc.terminate()
            except Exception:
                pass
        chime_proc = None
        showing_chime = False
        chime_kind = None
        if chime_temp_path:
            try:
                os.unlink(chime_temp_path)
            except Exception:
                pass
            chime_temp_path = None
        stop_mpv_proc(mpv_proc, current_ipc)
        mpv_proc = None
        # clean up any other stale socket
        for path in (ipc_a, ipc_b):
            try:
                if path != current_ipc and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def current_cava_candidate():
        if not cava_candidates:
            return {
                "method": cava_method,
                "source": cava_source,
                "label": cava_detect_mode or "configured",
            }
        idx = max(0, min(cava_candidate_idx, len(cava_candidates) - 1))
        return cava_candidates[idx]

    def advance_cava_candidate():
        nonlocal cava_candidate_idx
        if len(cava_candidates) <= 1:
            return False
        start_idx = cava_candidate_idx
        cava_candidate_idx = (cava_candidate_idx + 1) % len(cava_candidates)
        return cava_candidate_idx != start_idx

    def restart_cava(advance=False):
        nonlocal cava_retry_ts
        if advance:
            advance_cava_candidate()
        stop_cava()
        started = start_cava()
        cava_retry_ts = time.time()
        return started

    def start_cava():
        nonlocal cava_proc, cava_thread, cava_err, cava_ok, cava_bars, cava_bars_count
        nonlocal cava_started_ts, cava_retry_ts, cava_last_data_ts, cava_last_stderr, cava_last_label
        if cava_proc is not None:
            return True
        if shutil.which("cava") is None:
            cava_err = "cava not installed"
            return False
        candidate = current_cava_candidate()
        input_method = candidate.get("method")
        input_source = candidate.get("source")
        cava_last_label = candidate.get("label")
        cava_last_stderr = ""
        cava_ok = False
        cava_bars = None
        cava_err = None
        bars_count = calc_cava_bars()
        cava_bars_count = bars_count
        try:
            with open(cava_conf_path, "w") as f:
                f.write(cava_config_text(bars_count, input_method, input_source))
        except Exception as e:
            cava_err = f"config error: {e}"
            return False
        try:
            cava_proc = subprocess.Popen(
                ["cava", "-p", cava_conf_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            cava_err = f"start error: {e}"
            return False
        cava_started_ts = time.time()
        cava_last_data_ts = 0.0
        cava_retry_ts = 0.0

        def reader():
            nonlocal cava_bars, cava_ok, cava_last_data_ts
            if cava_proc is None or cava_proc.stdout is None:
                return
            for line in cava_proc.stdout:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(";")
                vals = []
                for p in parts:
                    try:
                        vals.append(int(p))
                    except Exception:
                        pass
                if not vals:
                    continue
                if len(vals) < bars_count:
                    vals.extend([0] * (bars_count - len(vals)))
                if len(vals) > bars_count:
                    vals = vals[:bars_count]
                bars = [min(1.0, v / CAVA_MAX) for v in vals]
                with cava_lock:
                    cava_bars = bars
                    cava_ok = True
                    cava_last_data_ts = time.time()

        cava_thread = threading.Thread(target=reader, daemon=True)
        cava_thread.start()

        def stderr_reader():
            nonlocal cava_last_stderr
            if cava_proc is None or cava_proc.stderr is None:
                return
            for line in cava_proc.stderr:
                text = line.strip()
                if text:
                    cava_last_stderr = text

        threading.Thread(target=stderr_reader, daemon=True).start()
        return True

    def stop_cava():
        nonlocal cava_proc, cava_bars, cava_ok, cava_err, cava_last_label
        if cava_proc is not None:
            try:
                cava_proc.terminate()
            except Exception:
                pass
            try:
                cava_proc.wait(timeout=0.5)
            except Exception:
                try:
                    cava_proc.kill()
                    cava_proc.wait(timeout=0.5)
                except Exception:
                    pass
            cava_proc = None
        with cava_lock:
            cava_bars = None
            cava_ok = False
        cava_err = None
        cava_last_label = None

    def start_for_hour(hour, crossfade=False, fade_dur=None):
        nonlocal mpv_proc, current_track, current_track_hour, current_ipc, fade, playback_started_ts, track_pick_reason
        active_games = current_active_games()
        active_variants = None if variant_idx == 0 else {variants_list[variant_idx]}
        tracks = list_tracks_for_hour(hour, active_games, active_variants)
        track, reason = pick_weighted(
            tracks,
            exclude=current_track if crossfade else None,
            recent_tracks=recent_track_paths,
            banned=banned_tracks,
        )
        track_pick_reason = reason
        if not track:
            current_track = None
            current_track_hour = None
            return False
        # If a fade is already in progress, stop the old track now
        if fade:
            stop_mpv_proc(fade.get("old_proc"), fade.get("old_ipc"))
            fade = None

        _fade_dur = fade_dur if fade_dur is not None else CROSSFADE_SECONDS
        if crossfade and _fade_dur > 0 and mpv_proc and mpv_proc.poll() is None:
            next_ipc = ipc_b if current_ipc == ipc_a else ipc_a
            # clear any stale socket
            try:
                if os.path.exists(next_ipc):
                    os.remove(next_ipc)
            except Exception:
                pass
            try:
                new_proc = mpv_start(track, next_ipc, audio_device, volume=0, loop_file=repeat_current)
            except Exception:
                return False
            if not _wait_for_ipc_socket(next_ipc):
                stop_mpv_proc(new_proc, next_ipc)
                return False
            apply_mpv_eq(next_ipc)
            apply_mpv_eq(current_ipc)
            fade = {
                "old_proc": mpv_proc,
                "old_ipc": current_ipc,
                "new_proc": new_proc,
                "new_ipc": next_ipc,
                "start_ts": time.time(),
                "dur": _fade_dur,
            }
            current_track = track
            current_track_hour = hour
            update_history(track)
            mpv_proc = new_proc
            current_ipc = next_ipc
            playback_started_ts = time.time()
            return True

        stop_mpv()
        current_track = track
        current_track_hour = hour
        update_history(track)
        try:
            mpv_proc = mpv_start(track, current_ipc, audio_device, loop_file=repeat_current)
        except Exception:
            mpv_proc = None
            current_track = None
            current_track_hour = None
            return False
        playback_started_ts = time.time()
        if not _wait_for_ipc_socket(current_ipc):
            stop_mpv_proc(mpv_proc, current_ipc)
            mpv_proc = None
            current_track = None
            current_track_hour = None
            return False
        apply_mpv_eq(current_ipc)
        # apply default volume to mpv if not using private sink loopback
        if not (PRIVATE_SINK and loopback_module):
            set_output_volume(output_vol)
        if muted:
            set_output_volume(get_mute_volume())
        return True

    def start_track_for_hour(hour, volume=None):
        nonlocal current_track, current_track_hour, current_ipc, playback_started_ts, track_pick_reason
        active_games = current_active_games()
        active_variants = None if variant_idx == 0 else {variants_list[variant_idx]}
        tracks = list_tracks_for_hour(hour, active_games, active_variants)
        track, reason = pick_weighted(tracks, recent_tracks=recent_track_paths, banned=banned_tracks)
        track_pick_reason = reason
        if not track:
            return None, None, None
        next_ipc = ipc_b if current_ipc == ipc_a else ipc_a
        try:
            if os.path.exists(next_ipc):
                os.remove(next_ipc)
        except Exception:
            pass
        try:
            proc = mpv_start(track, next_ipc, audio_device, volume=volume, loop_file=False)
        except Exception:
            return None, None, None
        playback_started_ts = time.time()
        if not _wait_for_ipc_socket(next_ipc):
            stop_mpv_proc(proc, next_ipc)
            return None, None, None
        apply_mpv_eq(next_ipc)
        current_track = track
        current_track_hour = hour
        current_ipc = next_ipc
        update_history(track)
        return proc, next_ipc, track

    def start_specific_track(track_path, crossfade=True):
        """Play a specific file immediately, with optional crossfade."""
        nonlocal mpv_proc, current_track, current_track_hour, current_ipc, fade, playback_started_ts, track_pick_reason
        track_pick_reason = "manual"
        if not track_path or not os.path.isfile(track_path):
            return False
        meta = parse_filename(os.path.basename(track_path))
        track_hour = int(meta["hour"]) if meta else hour
        if fade:
            stop_mpv_proc(fade.get("old_proc"), fade.get("old_ipc"))
            fade = None
        _fade_dur = CROSSFADE_SECONDS if crossfade else 0.0
        if crossfade and _fade_dur > 0 and mpv_proc and mpv_proc.poll() is None:
            next_ipc = ipc_b if current_ipc == ipc_a else ipc_a
            try:
                if os.path.exists(next_ipc):
                    os.remove(next_ipc)
            except Exception:
                pass
            try:
                new_proc = mpv_start(track_path, next_ipc, audio_device, volume=0, loop_file=repeat_current)
            except Exception:
                return False
            if not _wait_for_ipc_socket(next_ipc):
                stop_mpv_proc(new_proc, next_ipc)
                return False
            apply_mpv_eq(next_ipc)
            apply_mpv_eq(current_ipc)
            fade = {
                "old_proc": mpv_proc, "old_ipc": current_ipc,
                "new_proc": new_proc, "new_ipc": next_ipc,
                "start_ts": time.time(), "dur": _fade_dur,
            }
            mpv_proc = new_proc
            current_ipc = next_ipc
        else:
            stop_mpv_proc(mpv_proc, current_ipc)
            next_ipc = ipc_b if current_ipc == ipc_a else ipc_a
            try:
                if os.path.exists(next_ipc):
                    os.remove(next_ipc)
            except Exception:
                pass
            try:
                new_proc = mpv_start(track_path, next_ipc, audio_device, loop_file=repeat_current)
            except Exception:
                return False
            if not _wait_for_ipc_socket(next_ipc):
                stop_mpv_proc(new_proc, next_ipc)
                return False
            apply_mpv_eq(next_ipc)
            mpv_proc = new_proc
            current_ipc = next_ipc
        current_track = track_path
        current_track_hour = track_hour
        playback_started_ts = time.time()
        update_history(track_path)
        return True

    def update_history(track_path):
        if not track_path:
            return
        if recent_track_paths is not None:
            recent_track_paths.append(track_path)
        name = os.path.basename(track_path)
        if history and history[-1] == name:
            return
        history.append(name)

    def compute_next_candidates(hour, active_games, active_variants):
        tracks = list_tracks_for_hour(hour, active_games, active_variants)
        tracks = filter_recent_tracks(tracks, exclude=current_track, recent_tracks=recent_track_paths)
        if banned_tracks:
            tracks = [t for t in tracks if os.path.basename(t) not in banned_tracks]
        if not tracks:
            return ()
        # Sort deterministically so the Up Next list is stable between frames.
        tracks_sorted = sorted(tracks, key=lambda t: os.path.basename(t).lower())
        return tuple(os.path.basename(t) for t in tracks_sorted[:QUEUE_SIZE])


    def set_volume(vol, ipc_path=None):
        # Clamp volume and set explicitly to avoid drift
        try:
            v = int(max(0, min(100, vol)))
            mpv_command(ipc_path or current_ipc, ["set_property", "volume", v])
            return v
        except Exception:
            return None


    def set_output_volume(vol):
        nonlocal output_vol, last_loopback_vol
        try:
            v = int(max(0, min(100, vol)))
        except Exception:
            v = 0
        if PRIVATE_SINK and loopback_module:
            output_vol = v
            persist_ui_state()
            if set_loopback_volume(loopback_module, private_sink, v):
                last_loopback_vol = v
            else:
                last_loopback_vol = None
            return v
        # fallback to mpv volume
        v2 = set_volume(v)
        if v2 is not None:
            output_vol = v2
            persist_ui_state()
        return v2

    def persist_ui_state():
        try:
            save_ui_state({
                "output_vol": int(max(0, min(100, output_vol))),
                "muted": bool(muted),
                "mute_prev_vol": int(max(0, min(100, mute_prev_vol if mute_prev_vol is not None else output_vol))),
                "vis_mode": VIS_MODES[vis_idx],
                "repeat_current": bool(repeat_current),
                "game": games_list[game_idx] if 0 <= game_idx < len(games_list) else "ALL",
                "variant": variants_list[variant_idx] if 0 <= variant_idx < len(variants_list) else "ALL",
                "layout": normalize_layout_config(layout_state, default_preset=DEFAULT_LAYOUT_PRESET),
                "theme": get_theme(),
            })
        except Exception:
            pass

    def adjust_output_volume(delta):
        nonlocal mute_prev_vol, cached_vol, output_vol
        try:
            delta = int(delta)
        except Exception:
            return None
        if muted:
            base = mute_prev_vol if mute_prev_vol is not None else output_vol
            new_vol = int(max(0, min(100, base + delta)))
            mute_prev_vol = new_vol
            # Update output_vol so unmute restores the new level, but don't touch
            # the loopback/mpv — the mute state must stay in effect.
            output_vol = new_vol
            cached_vol = new_vol
            persist_ui_state()
            return new_vol
        new_vol = set_output_volume(output_vol + delta)
        if new_vol is not None:
            cached_vol = new_vol
        return new_vol

    def sync_loopback_state():
        nonlocal last_loopback_ts, last_loopback_vol, last_loopback_muted
        if not (PRIVATE_SINK and loopback_module and private_sink):
            return
        now = time.time()
        state_changed = (last_loopback_vol != output_vol) or (last_loopback_muted != muted)
        if not state_changed:
            return
        if now - last_loopback_ts < 1.0 and last_loopback_vol is None:
            return
        if not find_loopback_input_ids(loopback_module, private_sink):
            last_loopback_ts = now
            last_loopback_vol = None
            last_loopback_muted = None
            return
        last_loopback_ts = now
        # Apply mute/unmute to loopback when sink-input appears
        if loopback_q is not None:
            if MUTE_MODE == "hard":
                loopback_q.put(("mute", muted))
            loopback_q.put(("volume", output_vol))
        last_loopback_vol = output_vol
        last_loopback_muted = muted

    def handle_exit(signum=None, frame=None):
        stop_cava()
        stop_mpv()
        if STATS_ENABLED and stats_data is not None:
            stats_data["total_listen_seconds"] = int(stats_data.get("total_listen_seconds", 0) + session_listen)
            stats_data["sessions"] = int(stats_data.get("sessions", 0) + 1)
            stats_data["last_session"] = {
                "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session_start)),
                "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                "listen_seconds": int(session_listen),
            }
            if stats_q:
                stats_q.put(("json", stats_data))
            else:
                save_stats(stats_data)
            top = sorted([(i, v) for i, v in enumerate(stats_data.get("hour_buckets", [0] * 24))],
                         key=lambda x: x[1], reverse=True)[:3]
            top_hours = ";".join([f"{h:02d}" for h, v in top if v > 0])
            row = f"{stats_data['last_session']['start']},{stats_data['last_session']['end']},{int(session_listen)},{top_hours}"
            if stats_q:
                stats_q.put(("csv", row))
                stats_q.put(None)
                if stats_stop:
                    stats_stop.wait(timeout=1.0)
            else:
                append_stats_csv(row)
        if chime_proc and chime_proc.poll() is None:
            try:
                chime_proc.terminate()
            except Exception:
                pass
        if chime_temp_path:
            try:
                os.unlink(chime_temp_path)
            except Exception:
                pass
        try:
            if os.path.exists(cava_conf_path):
                os.unlink(cava_conf_path)
        except Exception:
            pass
        teardown_private_sink(private_module, loopback_module)
        enable_autowrap()
        show_cursor()
        exit_alt_screen()
        sys.exit(0)

    def get_playback():
        nonlocal last_query_ts, cached_tpos, cached_dur, cached_vol
        if transition or fade:
            return cached_tpos, cached_dur, cached_vol
        now = time.time()
        if now - last_query_ts > mpv_query_interval:
            values = mpv_query_props(current_ipc, ("time-pos", "duration", "volume")) if current_track else {}
            cached_tpos = values.get("time-pos")
            cached_dur = values.get("duration")
            cached_vol = values.get("volume")
            last_query_ts = now
        return cached_tpos, cached_dur, cached_vol

    def start_hour_transition(next_hour, simulate=False):
        nonlocal transition, repeat_current
        if repeat_current:
            repeat_current = False
            persist_ui_state()
        if not (mpv_proc and mpv_proc.poll() is None):
            # No current track; just play chime and fade in next
            transition = {
                "phase": "chime",
                "next_hour": next_hour,
                "start_ts": time.time(),
                "simulate": simulate,
            }
            return
        transition = {
            "phase": "fade_out",
            "old_proc": mpv_proc,
            "old_ipc": current_ipc,
            "next_hour": next_hour,
            "start_ts": time.time(),
            "dur": max(0.1, CROSSFADE_SECONDS),
            "simulate": simulate,
        }

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    def handle_resize(signum=None, frame=None):
        nonlocal resize_pending, last_resize_ts
        resize_pending = True
        last_resize_ts = time.time()

    signal.signal(signal.SIGWINCH, handle_resize)

    start_cava()

    enter_alt_screen()
    hide_cursor()
    disable_autowrap()
    try:
        with RawMode():
            while True:
                now = time.time()
                hour = int(time.strftime("%H", time.localtime(now)))
                if GRADIENT_ANIMATE:
                    _layout.BOX_GRADIENT_PHASE = (now * GRADIENT_SPEED) % 1.0
                if BOX_BORDER_SPIN:
                    _layout.BOX_BORDER_POS = int(now * BOX_BORDER_SPEED)
                if TITLE_ANIMATE and _term.TITLE_ART_BASE and _term.TITLE_LOLCAT_PATH and (not background_mode) and (focused or not FOCUS_THROTTLE):
                    interval = 1.0 / max(1.0, TITLE_ANIM_FPS)
                    if now - last_title_anim_ts >= interval:
                        try:
                            seed = int(now * TITLE_ANIM_FPS)
                            colored = subprocess.check_output(
                                [_term.TITLE_LOLCAT_PATH, "-f", "-S", str(seed)],
                                input="\n".join(_term.TITLE_ART_BASE),
                                text=True,
                            )
                            TITLE_ART[:] = [ln.rstrip("\n") for ln in colored.splitlines()]
                            _term.TITLE_ART_COLORED = True
                            _term.TITLE_ART_VERSION += 1
                            last_title_anim_ts = now
                        except Exception:
                            pass
                term_size = shutil.get_terminal_size(fallback=(80, 24))
                term_cols = term_size.columns
                term_rows = term_size.lines
                if term_cols != last_term_cols or term_rows != last_term_rows:
                    last_term_cols = term_cols
                    last_term_rows = term_rows
                    info_w_cache = 0
                    layout_mode = layout_mode_for_size(term_cols, term_rows)
                    _uc = term_rows < 10
                    _tiny = layout_mode == "tiny"
                    footer_control_lines, footer_has_separator = build_footer_controls(
                        term_cols, term_rows, tiny_term=_tiny, ultra_compact=_uc,
                    )

                # Responsive layout for small terminals
                tiny_term = layout_mode == "tiny"
                small_term = layout_mode in ("tiny", "small")
                ultra_compact = term_rows < 10
                info_max_width = max(10, term_cols - 5)
                footer_rows = len(footer_control_lines) + (1 if footer_has_separator else 0)
                spectrum_use_color = USE_COLOR
                min_spectrum_rows = layout_min_spectrum_rows(term_rows, layout_mode)
                base_spectrum = layout_base_spectrum_rows(layout_mode, ultra_compact)
                available_spectrum_rows = max(1, term_rows - footer_rows - 1)
                min_spectrum_height = min(available_spectrum_rows, max(min_spectrum_rows, base_spectrum))

                # Pinned layout zones; spectrum expands into spare rows after content is built
                _chrome_rows = 1
                _footer_rows = footer_rows
                _max_content_rows = max(0, term_rows - _chrome_rows - _footer_rows - min_spectrum_height - 1)

                hour_changed = (last_hour is not None and hour != last_hour)
                needs_start = (last_hour is None or mpv_proc is None or (mpv_proc and mpv_proc.poll() is not None))
                if hour_changed and transition is None:
                    start_hour_transition(hour, simulate=False)
                if needs_start and transition is None:
                    start_for_hour(hour, crossfade=False)
                    last_hour = hour

                # UI stats
                if resize_pending and (now - last_resize_ts) >= RESIZE_DEBOUNCE:
                    resize_pending = False
                    stop_cava()
                    start_cava()
                    bars_len_cached = None
                    bars_len_cols = term_cols
                    bars_len_count = None
                    # Invalidate differential render cache so full screen redraws
                    invalidate_render_cache()
                    _vis_line_cache = None        # btop data_same: invalidate on resize
                    _vis_line_cache_key = None
                    # Also clear terminal to avoid stale content at new dimensions
                    sys.stdout.write("[2J")
                    sys.stdout.flush()

                nh = next_hour_epoch(now)
                remaining = max(0, int(nh - now))

                # Query mpv playback (best-effort, cached)
                tpos, dur, vol = get_playback()

                # Recover if playback is live but cava never attached to the monitor stream.
                playback_live = bool(current_track and mpv_proc and mpv_proc.poll() is None)
                if cava_proc is not None and cava_proc.poll() is not None:
                    code = cava_proc.poll()
                    detail = f"cava exited ({code})"
                    if cava_last_label:
                        detail += f" via {cava_last_label}"
                    if cava_last_stderr:
                        detail += f": {cava_last_stderr}"
                    cava_err = detail
                    if playback_live and (not transition) and (not fade) and (now - cava_retry_ts) >= 1.0:
                        restart_cava(advance=True)
                elif playback_live and (not transition) and (not fade) and (not cava_ok) and (not cava_err):
                    retry_anchor = max(cava_started_ts, playback_started_ts)
                    if retry_anchor and (now - retry_anchor) >= AUDIO_WARMUP_GRACE and (now - cava_retry_ts) >= 3.0:
                        restart_cava(advance=True)

                # Render UI without full-screen clear to reduce flicker
                lines = []

                # Keep the UI-local alias and shared colors-module gradient in sync.
                global _active_tod_grad
                _clrs._active_tod_grad = _grad_for_hour(hour)
                _active_tod_grad = _clrs._active_tod_grad

                now_sec = int(now)
                if last_time_sec != now_sec:
                    last_time_sec = now_sec
                    last_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_sec))
                display_vol = output_vol if (PRIVATE_SINK and loopback_module) else (int(vol) if vol is not None else None)
                # Full-width header bar: time + playing indicator left, ├ ac-ui ┤ right.
                if USE_COLOR:
                    header_time = last_time_str if term_cols >= 48 else last_time_str[-8:]
                    _tod_hi = gradient_at(_active_tod_grad, min(100, 65 + int(_bass_energy * 35)))
                    playing_indicator = c256("♪", _tod_hi) if (current_track and not muted) else c256("♪", 236)
                    _hdr_left_plain = f"─── ♪ {header_time} "
                    _hdr_left = (c256("─" * 3, 238) + " " + playing_indicator + " "
                                 + c256(header_time, 245) + " ")
                    # In ultra-compact mode show current track; otherwise show app name
                    if ultra_compact and current_track:
                        _hdr_tag = parse_filename(os.path.basename(current_track))
                        _hdr_inner_text = f"{_hdr_tag['game']}: {_hdr_tag['variant']}" if _hdr_tag else os.path.basename(current_track)
                    else:
                        _hdr_inner_text = "ac-ui"
                    if term_cols < 28:
                        lines.append(truncate_ansi_visible(_hdr_left.rstrip(), term_cols))
                    else:
                        _hdr_inner_max = max(1, term_cols - plain_visible_len(_hdr_left_plain) - plain_visible_len("┤  ├"))
                        _hdr_inner = f" {truncate_plain(_hdr_inner_text, _hdr_inner_max)} "
                        _hdr_right_plain = f"┤{_hdr_inner}├"
                        _hdr_pad = max(0, term_cols - plain_visible_len(_hdr_left_plain) - plain_visible_len(_hdr_right_plain))
                        _hdr_right = (c256("┤", 240) + f"\x1b[1;38;5;{gradient_at(_active_tod_grad, 95)}m{_hdr_inner}\x1b[0m" + c256("├", 240))
                        lines.append(_hdr_left + c256("─" * _hdr_pad, 238) + _hdr_right)
                else:
                    header_time = last_time_str if term_cols >= 48 else last_time_str[-8:]
                    lines.append(truncate_plain(f"─── ♪ {header_time}", term_cols))

                # btop ▲▼ volume delta flash (shown inline next to vol label)
                _vol_flash_str = ""
                if vol_delta_flash is not None:
                    delta_text, delta_expire = vol_delta_flash
                    if time.monotonic() < delta_expire:
                        _tod_flash_col = gradient_at(_active_tod_grad, 95)
                        _vol_flash_str = f"  \x1b[1;38;5;{_tod_flash_col}m{delta_text}\x1b[0m" if USE_COLOR else f"  {delta_text}"
                    else:
                        vol_delta_flash = None

                if ultra_compact:
                    compact_summary = truncate_plain(
                        build_ultra_compact_summary(
                            current_game_label(),
                            variants_list[variant_idx],
                            VIS_MODES[vis_idx],
                            remaining,
                            display_vol=display_vol,
                            muted=muted,
                            showing_chime=showing_chime,
                            chime_kind=chime_kind,
                            repeat_current=repeat_current,
                        ),
                        max(10, term_cols - 2),
                    )
                    lines.append(c(compact_summary, "2"))

                # Content zone budget (chrome + footer + spectrum already reserved)
                max_info_rows = max(0, _max_content_rows - 2)  # 2 for box borders
                compact_info = max_info_rows < 10 or term_cols < 70 or ultra_compact

                info = []
                info_plain = []
                if not ultra_compact:
                    _tod_grad = _active_tod_grad
                    info_key = (
                        term_cols,
                        info_max_width,
                        compact_info,
                        tiny_term,
                        _term.TITLE_ART_VERSION,
                        current_game_label(),
                        variants_list[variant_idx],
                        VIS_MODES[vis_idx],
                        repeat_current,
                        showing_chime,
                        chime_kind,
                        os.path.basename(current_track) if current_track else None,
                        current_track_hour,
                        hour,
                        int(tpos) if tpos is not None else None,
                        int(dur) if dur is not None else None,
                        int(display_vol) if display_vol is not None else None,
                        muted,
                        int(remaining),
                        (now_sec if not NO_MOTION else 0),  # ensures pulse dot + gradient bars refresh every second
                        bool(vol_delta_flash and time.monotonic() < vol_delta_flash[1]),
                        track_pick_reason,
                    )
                    if info_key != info_cache_key:
                        info = []
                        info_plain = []

                        def add_info_line(text, color_code="2"):
                            text = truncate_plain(text, info_max_width)
                            info_plain.append(text)
                            info.append(c(text, color_code))

                        if (not compact_info) and TITLE_ART:
                            if _term.TITLE_ART_COLORED:
                                info.extend([line for line in TITLE_ART])
                                info_plain.extend([strip_ansi(line) for line in TITLE_ART])
                            else:
                                _art_col = gradient_at(_tod_grad, 70)
                                info.extend([c256(line, _art_col) for line in TITLE_ART])
                                info_plain.extend([line for line in TITLE_ART])

                        current_game = current_game_label()
                        pulse_bright = (not NO_MOTION) and (int(now) % 2 == 0)
                        _flt_sum = format_filter_summary(current_game, variants_list[variant_idx])

                        if compact_info:
                            # Compact: dense filter+vis line, then track name, then until
                            dense_plain = f"{_flt_sum} · {VIS_MODES[vis_idx]}"
                            if USE_COLOR:
                                _flt_col = gradient_at(_tod_grad, 65)
                                _pd_col = gradient_at(_tod_grad, 90)
                                _pulse = (f"\x1b[1;38;5;{_pd_col}m●\x1b[0m" if (pulse_bright and not muted)
                                          else f"\x1b[2;38;5;{_pd_col}m·\x1b[0m")
                                _muted_c = f"  \x1b[1;31m◆\x1b[0m" if muted else ""
                                dense_color = (
                                    f"\x1b[38;5;{_flt_col}m{_flt_sum}\x1b[0m"
                                    f"\x1b[2m · \x1b[0m"
                                    f"\x1b[2;36m{VIS_MODES[vis_idx]}\x1b[0m"
                                    f"  {_pulse}{_muted_c}"
                                )
                                info_plain.append(truncate_plain(dense_plain, info_max_width))
                                info.append(dense_color)
                            else:
                                add_info_line(dense_plain, "2")
                            if showing_chime:
                                add_info_line(f"♪ ({chime_kind or 'hour chime'})", "36")
                            elif current_track:
                                _cn = os.path.basename(current_track)
                                _cm = parse_filename(_cn)
                                _cd = f"{_cm['game']}: {_cm['variant']}" if _cm else _cn
                                add_info_line(_cd, "97")
                            else:
                                add_info_line(f"(none for {hour:02d}h)", "2")
                            uvalue = f"{remaining//60:02d}:{remaining%60:02d}"
                            add_info_line(f"Until: {uvalue}", "95")
                        else:
                            # ── Full mode: new information hierarchy ──

                            # Line 1: track name (primary, bold) or chime label
                            if showing_chime:
                                label = chime_kind or "hour chime"
                                if USE_COLOR:
                                    _hr_col = gradient_at(_tod_grad, 80)
                                    info_plain.append(truncate_plain(f"♪ ({label})", info_max_width))
                                    info.append(f"\x1b[38;5;{_hr_col}m♪\x1b[0m \x1b[2;36m({label})\x1b[0m")
                                else:
                                    add_info_line(f"♪ ({label})", "36")
                            elif current_track:
                                display_hour = current_track_hour if current_track_hour is not None else hour
                                track_name = os.path.basename(current_track)
                                _meta = parse_filename(track_name)
                                display_name = f"{_meta['game']}: {_meta['variant']}" if _meta else track_name
                                dur_tag = f"  {humanize_seconds(dur)}" if dur else ""
                                if USE_COLOR:
                                    _sym_hi = gradient_at(_tod_grad, 90)
                                    sym_color = "\x1b[2;31m" if muted else ("\x1b[2;37m" if background_mode else f"\x1b[1;38;5;{_sym_hi}m")
                                    _pin_str = f" \x1b[33m[pinned]\x1b[0m" if repeat_current else ""
                                    _dur_col = gradient_at(_tod_grad, 50)
                                    info_plain.append(truncate_plain(f"{SYM_PLAY} {display_name}{dur_tag}", info_max_width))
                                    info.append(
                                        f"{sym_color}{SYM_PLAY}\x1b[0m "
                                        f"\x1b[1;97m{display_name}\x1b[0m{_pin_str}"
                                        f"\x1b[2;38;5;{_dur_col}m{dur_tag}\x1b[0m"
                                    )
                                else:
                                    _pin_str = " [pinned]" if repeat_current else ""
                                    add_info_line(f"{SYM_PLAY} {display_name}{_pin_str}{dur_tag}", "36")

                                # Line 2: hour + playback position + inline progress bar
                                t_pos_s = tpos or 0.0
                                t_dur_s = dur or 0.0
                                bar_w = max(8, min(20, info_max_width - 26))
                                pct = (t_pos_s / max(1.0, t_dur_s) * 100) if t_dur_s > 0 else 0
                                pb_bar = (solid_bar(pct, bar_w, gradient_at(_tod_grad, 65)) if USE_COLOR
                                          else ("[" + "=" * int(pct / 100 * bar_w) + "─" * (bar_w - int(pct / 100 * bar_w)) + "]"))
                                pos_plain = f"  {display_hour:02d}h  {fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}"
                                if USE_COLOR:
                                    _h_col = gradient_at(_tod_grad, 70)
                                    info_plain.append(truncate_plain(pos_plain, info_max_width))
                                    info.append(
                                        f"  \x1b[38;5;{_h_col}m{display_hour:02d}h\x1b[0m"
                                        f"  \x1b[2;36m{fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}\x1b[0m"
                                        f"  {pb_bar}"
                                    )
                                else:
                                    add_info_line(f"{pos_plain}  {pb_bar}", "2")
                            else:
                                add_info_line(f"  (no track for {hour:02d}h)", "2")

                            # Line 3: filter + vis + pulse + vol (secondary, dim)
                            if USE_COLOR:
                                _flt_col = gradient_at(_tod_grad, 60)
                                _pd_col = gradient_at(_tod_grad, 90)
                                pulse_dot = (f"\x1b[1;38;5;{_pd_col}m●\x1b[0m" if (pulse_bright and not muted)
                                             else f"\x1b[2;38;5;{_pd_col}m·\x1b[0m")
                                muted_tag = f"  \x1b[1;31m◆ MUTED\x1b[0m" if muted else ""
                                _vol_inline = (f"  \x1b[2;36mVol\x1b[0m {int(display_vol):3d}%{_vol_flash_str}"
                                               if display_vol is not None else "")
                                meta_plain = f"  {_flt_sum}  {VIS_MODES[vis_idx]}"
                                meta_color = (
                                    f"  \x1b[2;38;5;{_flt_col}m{_flt_sum}\x1b[0m"
                                    f"  \x1b[2;36m{VIS_MODES[vis_idx]}\x1b[0m"
                                    f"  {pulse_dot}{muted_tag}{_vol_inline}"
                                )
                                info_plain.append(truncate_plain(meta_plain, info_max_width))
                                info.append(meta_color)
                            else:
                                _vol_inline = f"  Vol {int(display_vol)}%" if display_vol is not None else ""
                                add_info_line(f"  {_flt_sum}  {VIS_MODES[vis_idx]}{_vol_inline}", "2")

                            # Line 4: until next hour with bar
                            uvalue = f"{remaining//60:02d}:{remaining%60:02d}"
                            if USE_COLOR:
                                hr_pct = min(100, int(remaining / 3600 * 100))
                                cbar_w = max(4, min(20, info_max_width - 18))
                                cbar = solid_bar(hr_pct, cbar_w, gradient_at(_tod_grad, 50))
                                _uc = gradient_at(_tod_grad, 55)
                                info_plain.append(truncate_plain(f"  Until: {uvalue}", info_max_width))
                                info.append(f"  \x1b[2;36mUntil:\x1b[0m \x1b[38;5;{_uc}m{uvalue}\x1b[0m  {cbar}")
                            else:
                                add_info_line(f"  Until: {uvalue}", "95")

                            # Line 5: pick reason (explainability, dim)
                            if track_pick_reason and not showing_chime:
                                reason_plain = f"  why: {track_pick_reason}"
                                if USE_COLOR:
                                    info_plain.append(truncate_plain(reason_plain, info_max_width))
                                    info.append(f"  \x1b[2mwhy: {track_pick_reason}\x1b[0m")
                                else:
                                    add_info_line(reason_plain, "2")

                        info_cache_key = info_key
                        info_plain_cache = tuple(info_plain)
                        info_color_cache = tuple(info)
                    else:
                        info_plain = list(info_plain_cache)
                        info = list(info_color_cache)

                # Refresh "next candidates" on filter/hour/track change (sorted, stable)
                active_games = current_active_games()
                active_variants = None if variant_idx == 0 else {variants_list[variant_idx]}
                cand_key = (hour, game_idx, variant_idx, current_track, frozenset(banned_tracks))
                if cand_key != next_candidates_key:
                    next_candidates = list(compute_next_candidates(hour, active_games, active_variants))
                    next_candidates_ts = now
                    next_candidates_key = cand_key

                # Local listening stats (opt-in)
                if STATS_ENABLED and stats_data is not None:
                    now_ts = time.time()
                    dt = max(0.0, now_ts - stats_last_ts)
                    stats_last_ts = now_ts
                    playing = (current_track is not None and mpv_proc and mpv_proc.poll() is None and not muted)
                    if playing:
                        session_listen += dt
                        hb = stats_data.get("hour_buckets", [0] * 24)
                        h = int(time.strftime("%H", time.localtime(now_ts)))
                        hb[h] = hb[h] + dt
                        stats_data["hour_buckets"] = hb
                    if now_ts - stats_last_flush > 10.0:
                        stats_last_flush = now_ts
                        flush_copy = dict(stats_data)
                        flush_copy["total_listen_seconds"] = int(stats_data.get("total_listen_seconds", 0) + session_listen)
                        if stats_q:
                            stats_q.put(("json", flush_copy))
                        else:
                            save_stats(flush_copy)

                info_box = None
                info_w = 0
                if not ultra_compact:
                    # Box the info section (width based on plain text).
                    # If help is requested in compact mode, drop the info box to make room.
                    if max_info_rows <= 0:
                        info_plain = []
                        info = []
                    elif len(info_plain) > max_info_rows:
                        info_plain = info_plain[:max_info_rows]
                        info = info[:max_info_rows]
                    if info_plain and (not (show_help and compact_info)):
                        info_w_needed = max([plain_visible_len(line) for line in info_plain] + [0])
                        info_w_cache = min(info_max_width, max(info_w_cache, info_w_needed))
                        _ibox_key = (info_cache_key, info_w_cache, show_help, compact_info)
                        if _ibox_key != info_box_cache_key:
                            _np_hints = "[n]ext  [m]ute  [+/-]vol"
                            info_box_cache, _ = build_box(info_plain, info, info_w_cache, title="Now Playing", title2=_np_hints)
                            info_box_cache_key = _ibox_key
                        info_box = info_box_cache
                        info_w = info_w_cache

                stats_box = None
                stats_w = 0
                if (not ultra_compact) and STATS_ENABLED and stats_data is not None:
                    total_sec = int(stats_data.get("total_listen_seconds", 0) + session_listen)
                    hb = stats_data.get("hour_buckets", [0] * 24)
                    stats_inner_width = max(28, min(info_max_width, max(28, term_cols - 12)))
                    top = sorted([(i, v) for i, v in enumerate(hb)], key=lambda x: x[1], reverse=True)[:3]
                    stats_key = (total_sec, int(session_listen), tuple(int(v) for v in hb), hour, stats_inner_width)
                    if stats_key != stats_cache_key:
                        # Derived stats from hour_buckets
                        hb_total = sum(hb)
                        peak_h, peak_v = (top[0][0], top[0][1]) if top and top[0][1] > 0 else (0, 0)
                        peak_pct = int(peak_v / max(1, hb_total) * 100)
                        active_count = sum(1 for v in hb if v > 0)
                        avg_per_h = format_seconds(int(hb_total / max(1, active_count))) if active_count > 0 else "--"
                        top_hours_text = ", ".join([f"{h:02d}:00" for h, v in top if v > 0]) or "(none yet)"
                        hist_plain, marker_plain, axis_plain = build_hour_histogram_lines(hb, hour, stats_inner_width)

                        stats_plain = [
                            truncate_plain(f"Total listening: {format_seconds(total_sec)}", stats_inner_width),
                            truncate_plain(f"This session: {format_seconds(session_listen)}", stats_inner_width),
                            truncate_plain(f"Most-listened hours: {top_hours_text}", stats_inner_width),
                            truncate_plain(
                                f"Busiest hour: {peak_h:02d}:00 ({peak_pct}% of total)" if peak_v > 0 else "Busiest hour: (not enough listening yet)",
                                stats_inner_width,
                            ),
                            truncate_plain(f"Hours used: {active_count} of 24   Avg used hour: {avg_per_h}", stats_inner_width),
                            hist_plain,
                            marker_plain,
                            axis_plain,
                        ]
                        if USE_COLOR:
                            _s_total_pct = min(100, int(total_sec / 360000 * 100))
                            _s_sess_pct  = min(100, int(session_listen / 28800 * 100))
                            _s_total_bar = gradient_bar(_s_total_pct, 8, _active_tod_grad)
                            _s_sess_bar  = gradient_bar(_s_sess_pct,  8, _active_tod_grad)

                            # Each sampled histogram bar inherits the color of its nearest hour.
                            hist_parts = []
                            for col_idx, ch in enumerate(hist_plain):
                                if ch == " ":
                                    hist_parts.append(" ")
                                else:
                                    h_idx = int(round(col_idx / max(1, stats_inner_width - 1) * 23))
                                    brightness = 100 if h_idx == (hour % 24) else 70
                                    col = gradient_at(_grad_for_hour(h_idx), brightness)
                                    bold = "[1;" if h_idx == (hour % 24) else "["
                                    hist_parts.append(f"{bold}38;5;{col}m{ch}[0m")
                            hist_colored = "".join(hist_parts)

                            _mc = gradient_at(_active_tod_grad, 95)
                            marker_pos = marker_plain.find("▴")
                            marker_colored = (" " * max(0, marker_pos)
                                             + f"[1;38;5;{_mc}m▴[0m"
                                             + " " * max(0, stats_inner_width - marker_pos - 1))
                            axis_colored = c256(axis_plain, gradient_at(_active_tod_grad, 35))

                            _tc = gradient_at(_active_tod_grad, 70)
                            _pc = gradient_at(_active_tod_grad, 80)
                            _cc = gradient_at(_active_tod_grad, 55)
                            stats_color = [
                                f"[2;36mTotal listening:[0m  [2m{format_seconds(total_sec)}[0m  {_s_total_bar}",
                                f"[2;36mThis session:[0m  [2m{format_seconds(session_listen)}[0m  {_s_sess_bar}",
                                f"[2;36mMost-listened hours:[0m [38;5;{_tc}m{top_hours_text}[0m",
                                (
                                    f"[2;36mBusiest hour:[0m [38;5;{_pc}m{peak_h:02d}:00 ({peak_pct}% of total)[0m"
                                    if peak_v > 0 else
                                    f"[2;36mBusiest hour:[0m [38;5;{_cc}m(not enough listening yet)[0m"
                                ),
                                f"[2;36mHours used:[0m [2m{active_count} of 24[0m   [2;36mAvg used hour:[0m [2m{avg_per_h}[0m",
                                hist_colored,
                                marker_colored,
                                axis_colored,
                            ]
                        else:
                            stats_color = [c(s, "2") for s in stats_plain]
                        stats_box_cache, stats_w_cache = build_box(stats_plain, stats_color, maxw_override=stats_inner_width, title="Stats")
                        stats_cache_key = stats_key
                    stats_box = stats_box_cache
                    stats_w = stats_w_cache

                max_content_end = _chrome_rows + _max_content_rows
                layout_snapshot = normalize_layout_config(layout_state, default_preset=DEFAULT_LAYOUT_PRESET)
                layout_preset = layout_snapshot["preset"]

                if info_box and (len(lines) + len(info_box) > max_content_end):
                    max_rows = max(0, max_content_end - len(lines) - 2)
                    if len(info_plain) > max_rows:
                        info_plain = info_plain[:max_rows]
                        info = info[:max_rows]
                        info_w_needed = max([plain_visible_len(line) for line in info_plain] + [0])
                        info_w_cache = min(info_max_width, max(info_w_cache, info_w_needed))
                        info_box, info_w = build_box(info_plain, info, info_w_cache, title="Now Playing", title2="[n]ext  [m]ute  [+/-]vol")

                show_history = show_history_panel and (not tiny_term) and (not ultra_compact) and (not compact_info)
                show_up_next = show_up_next_panel and (not (tiny_term or small_term)) and (not ultra_compact) and (not compact_info)
                if (max_content_end - len(lines)) <= 0:
                    show_history = False
                    show_up_next = False
                panel_max_width = resolve_panel_max_width(term_cols, layout_preset)

                hist_box = None
                up_box = None
                hist_w = 0
                up_w = 0
                if show_history:
                    hist_list = tuple(history)[-HISTORY_MAX:]
                    _hist_focused = panel_focus == "history"
                    _hist_sel_clamped = max(0, min(hist_sel, len(hist_list) - 1)) if hist_list else 0
                    hist_key = (hist_list, panel_max_width, hour, layout_preset, _hist_focused, _hist_sel_clamped)
                    if hist_key != hist_cache_key:
                        hist_title = "Recently played"
                        hist_title_trunc = truncate_plain(hist_title, panel_max_width)
                        def _fmt_hist(name):
                            meta = parse_filename(name)
                            if meta:
                                return f"{meta['game']}: {meta['variant']}"
                            return name
                        hist_entries = [_fmt_hist(s) for s in hist_list] if hist_list else ["(none yet)"]
                        hist_lines = [hist_title_trunc] + hist_entries
                        hist_lines = [truncate_plain(s, panel_max_width) for s in hist_lines]
                        hist_plain = hist_lines
                        if USE_COLOR and hist_list:
                            n_h = len(hist_list)
                            _hh_hi = gradient_at(_active_tod_grad, 70)
                            hist_color = [c256(hist_title_trunc, _hh_hi)]
                            for hi, hs in enumerate(hist_lines[1:]):
                                if _hist_focused and hi == _hist_sel_clamped:
                                    hist_color.append(f"\x1b[7m{hs}\x1b[0m")  # reverse video = selected
                                else:
                                    age_frac = (n_h - 1 - hi) / max(1, n_h - 1)
                                    shade = gradient_at(_active_tod_grad, int(35 + (1 - age_frac) * 35))
                                    hist_color.append(c256(hs, shade))
                        else:
                            hist_color = [c(hist_title_trunc, "36")] + [
                                (f"\x1b[7m{s}\x1b[0m" if (_hist_focused and hi == _hist_sel_clamped) else c(s, "2"))
                                for hi, s in enumerate(hist_lines[1:])
                            ]
                        _hist_title = "▶ History" if _hist_focused else "History"
                        hist_box_cache, hist_w_cache = build_box(hist_plain, hist_color, maxw_override=panel_max_width, title=_hist_title)
                        hist_cache_key = hist_key
                    hist_box = hist_box_cache
                    hist_w = hist_w_cache

                if show_up_next:
                    next_list = next_candidates
                    _up_focused = panel_focus == "up_next"
                    _up_sel_clamped = max(0, min(up_sel, len(next_list) - 1)) if next_list else 0
                    up_key = (next_list, panel_max_width, UP_NEXT_MAX, hour, layout_preset, _up_focused, _up_sel_clamped)
                    if up_key != up_cache_key:
                        if next_list:
                            def _fmt_candidate(name):
                                meta = parse_filename(name)
                                if meta:
                                    return f"{meta['game']}: {meta['variant']}"
                                return name
                            shown_raw = list(next_list[:UP_NEXT_MAX])
                            shown = [_fmt_candidate(s) for s in shown_raw]
                            if len(next_list) > UP_NEXT_MAX:
                                shown.append(f"{SYM_ELLIPSIS} +{len(next_list) - UP_NEXT_MAX} more")
                            header_plain = f"Up next ({min(len(next_list), UP_NEXT_MAX)}/{len(next_list)})"
                            header_plain_trunc = truncate_plain(header_plain, panel_max_width)
                            up_plain = [header_plain_trunc] + shown
                            up_plain = [truncate_plain(s, panel_max_width) for s in up_plain]
                            if USE_COLOR:
                                _uc_hi = gradient_at(_active_tod_grad, 70)
                                _uc_lo = gradient_at(_active_tod_grad, 40)
                                up_color = [c256(header_plain_trunc, _uc_hi)]
                                for i, s in enumerate(up_plain[1:]):
                                    if _up_focused and i == _up_sel_clamped:
                                        up_color.append(f"\x1b[7m{s}\x1b[0m")
                                    else:
                                        up_color.append(f"\x1b[2m{superscript_num(i+1)}\x1b[0m {c256(s, _uc_lo if i >= 1 else _uc_hi)}")
                            else:
                                up_color = [c(header_plain_trunc, "36")] + [
                                    (f"\x1b[7m{s}\x1b[0m" if (_up_focused and i == _up_sel_clamped) else c(s, "2"))
                                    for i, s in enumerate(up_plain[1:])
                                ]
                        else:
                            up_title = "Up next"
                            up_title_trunc = truncate_plain(up_title, panel_max_width)
                            up_plain = [up_title_trunc, "(no candidates)"]
                            up_plain = [truncate_plain(s, panel_max_width) for s in up_plain]
                            up_color = [c(up_title_trunc, "36"), c("(no candidates)", "2")]
                        _up_title = "▶ Up Next" if _up_focused else "Up Next"
                        up_box_cache, up_w_cache = build_box(up_plain, up_color, maxw_override=panel_max_width, title=_up_title)
                        up_cache_key = up_key
                    up_box = up_box_cache
                    up_w = up_w_cache

                panel_boxes = {
                    "history": (hist_box, box_outer_width(hist_w)),
                    "up_next": (up_box, box_outer_width(up_w)),
                }
                active_sidebar = [name for name in layout_panels_in_slot(layout_snapshot, "sidebar") if panel_boxes.get(name, (None, 0))[0]]
                active_below = [name for name in layout_panels_in_slot(layout_snapshot, "below") if panel_boxes.get(name, (None, 0))[0]]

                _sidebar_eligible = [
                    (name, len(panel_boxes[name][0]))
                    for name in active_sidebar
                    if panel_boxes.get(name, (None, 0))[0]
                ]
                _below_eligible = [
                    (name, len(panel_boxes[name][0]))
                    for name in active_below
                    if panel_boxes.get(name, (None, 0))[0]
                ]
                _plan = resolve_layout(
                    term_cols,
                    avail_rows=max_content_end - len(lines),
                    info_natural_w=info_w if info_box else 0,
                    sidebar_candidates=_sidebar_eligible,
                    below_candidates=_below_eligible,
                    layout_preset=layout_preset,
                )

                if info_box:
                    top_lines = None
                    if _plan.sidebar:
                        _sb_blocks = [panel_boxes[name] for name in _plan.sidebar]
                        sidebar_lines, sidebar_outer = stack_render_blocks(_sb_blocks)
                        _itw = _plan.info_target_w or info_w
                        if _itw != info_w:
                            info_box_fit, info_w_fit = build_box(
                                info_plain, info, maxw_override=_itw,
                                title="Now Playing", title2="[n]ext  [m]ute  [+/-]vol"
                            )
                        else:
                            info_box_fit, info_w_fit = info_box, info_w
                        candidate_lines, candidate_width = combine_render_columns(
                            [(info_box_fit, box_outer_width(info_w_fit)), (sidebar_lines, sidebar_outer)]
                        )
                        if candidate_width <= term_cols and (len(lines) + len(candidate_lines) <= max_content_end):
                            top_lines = candidate_lines
                    if top_lines is None and (len(lines) + len(info_box) <= max_content_end):
                        top_lines = list(info_box)
                    if top_lines:
                        lines.extend(top_lines)

                if _plan.below:
                    _below_blocks = [panel_boxes[name] for name in _plan.below if panel_boxes.get(name, (None, 0))[0]]
                    if _below_blocks:
                        candidate_lines, candidate_width = combine_render_columns(_below_blocks, box_fill=True)
                        if candidate_width > term_cols:
                            candidate_lines, candidate_width = stack_render_blocks(_below_blocks)
                        if len(lines) + len(candidate_lines) <= max_content_end:
                            lines.extend(candidate_lines)

                render_help = show_help and (not ultra_compact)
                help_rows_budget = max_content_end - len(lines)
                if help_rows_budget <= 2:
                    render_help = False
                if (not ultra_compact) and render_help:
                    if current_output_sink:
                        help_sink = current_output_sink
                        help_sink_cache = help_sink
                        help_sink_cache_ts = now
                    else:
                        if help_sink_cache is None or (now - help_sink_cache_ts) > 5.0:
                            help_sink_cache = get_default_sink() or "(unknown)"
                            help_sink_cache_ts = now
                        help_sink = help_sink_cache
                    help_max_width = max(14, min(info_max_width, term_cols - 8))
                    help_key = (help_sink, hour, help_max_width, help_rows_budget)
                    if help_key != help_cache_key:
                        help_lines = list(HELP_LINES_BASE[1:])
                        help_lines.append(f"Audio output: {help_sink}")
                        help_lines.append("Focus throttle: AC_UI_FOCUS_THROTTLE=1")
                        wrapped_help = []
                        for help_line in help_lines:
                            wrapped_help.extend(wrap_plain(help_line, help_max_width) or [""])
                        wrapped_help = wrapped_help[:max(0, help_rows_budget - 2)]
                        if wrapped_help:
                            if USE_COLOR:
                                _hk_col = gradient_at(_active_tod_grad, 80)
                                help_color = [colorize_hint_keys(s, _hk_col, base_code="2") for s in wrapped_help]
                            else:
                                help_color = [c(s, "2") for s in wrapped_help]
                            help_box_cache, _ = build_box(wrapped_help, help_color, maxw_override=help_max_width, title="Help")
                        else:
                            help_box_cache = None
                        help_cache_key = help_key
                    if help_box_cache and (len(lines) + len(help_box_cache) <= max_content_end):
                        lines.extend(help_box_cache)

                if stats_box and (len(lines) + len(stats_box) <= max_content_end):
                    lines.extend(stats_box)

                if show_debug and (not ultra_compact) and (max_content_end - len(lines)) >= 4:
                    _avg_ms = (sum(debug_frame_times) / len(debug_frame_times) * 1000) if debug_frame_times else 0.0
                    _cava_st = "running" if (cava_proc and cava_proc.poll() is None) else "stopped"
                    _audio_route = f"{private_sink} → {current_output_sink}" if private_sink else (current_output_sink or "default")
                    _dbg_lines = [
                        f"term: {term_cols}×{term_rows}  layout: {layout_mode}  preset: {layout_preset_label(layout_state)}",
                        f"vis: {VIS_MODES[vis_idx]}  repeat: {'on' if repeat_current else 'off'}  bg: {'on' if background_mode else 'off'}  focused: {'yes' if focused else 'no'}",
                        f"panels: history={'on' if show_history_panel else 'off'}  up_next={'on' if show_up_next_panel else 'off'}",
                        f"audio: {_audio_route}  cava: {_cava_st}",
                        f"frame: {_avg_ms:.0f}ms avg  lines: {len(lines)}/{term_rows}  refresh: {int((IDLE_REFRESH if (background_mode or (FOCUS_THROTTLE and not focused)) else REFRESH_INTERVAL)*1000)}ms",
                    ]
                    _dbg_w = max(14, min(term_cols - 8, max(len(s) for s in _dbg_lines)))
                    if USE_COLOR:
                        _dbg_color = [c(s, "2") for s in _dbg_lines]
                    else:
                        _dbg_color = list(_dbg_lines)
                    _dbg_box, _ = build_box(_dbg_lines, _dbg_color, maxw_override=_dbg_w, title="Debug  [`] to close")
                    if len(lines) + len(_dbg_box) <= max_content_end:
                        lines.extend(_dbg_box)

                prefix = "  "

                # btop state banner: full-width flash for mute/unmute/bg-mode events
                if state_banner is not None:
                    banner_text, banner_color, banner_expire = state_banner
                    if time.monotonic() < banner_expire:
                        banner_plain = truncate_plain(str(banner_text), max(4, term_cols - 3))
                        if USE_COLOR:
                            lines.append(f"  \x1b[1;38;5;{banner_color}m{banner_plain}\x1b[0m")
                        else:
                            lines.append(f"  {banner_plain}")
                    else:
                        state_banner = None

                # Spectrum expands to fill space above actual content
                _natural_len = len(lines)
                _available_for_spectrum = max(1, term_rows - _footer_rows - 1)
                _reserved_spectrum = min(_available_for_spectrum, min_spectrum_height)
                spectrum_height_dyn = max(_reserved_spectrum, _available_for_spectrum - _natural_len)
                spectrum_height_dyn = max(0, min(spectrum_height_dyn, _available_for_spectrum))
                _content_end = max(_chrome_rows, term_rows - _footer_rows - 1 - spectrum_height_dyn)
                while len(lines) < _content_end:
                    lines.append("")
                if len(lines) > _content_end:
                    lines = lines[:_content_end]
                with cava_lock:
                    bars = list(cava_bars) if cava_bars else None
                    ok = cava_ok
                # Cache bars_len based on terminal width and cava bar count
                if bars_len_cached is None or bars_len_cols != term_cols or bars_len_count != (cava_bars_count or 0):
                    bars_len_cols = term_cols
                    bars_len_count = cava_bars_count or 0
                    max_len = max(CAVA_MIN_BARS, term_cols - CAVA_MARGIN)
                    available = max(10, term_cols - len(prefix) - CAVA_MARGIN)
                    bars_len = len(bars) if bars else (cava_bars_count or max_len)
                    if bars_len > max_len:
                        bars_len = max_len
                    if bars_len > available:
                        bars_len = available
                    bars_len_cached = bars_len
                else:
                    bars_len = bars_len_cached
                if spectrum_height_dyn > 0:
                    _spec_row0 = len(lines)
                    if bars and bars_len is not None and len(bars) > bars_len:
                        bars = bars[:bars_len]
                    if bars:
                        vis_now = time.monotonic()
                        if last_vis_update_ts is None:
                            vis_dt = REFRESH_INTERVAL
                        else:
                            vis_dt = max(0.005, min(0.20, vis_now - last_vis_update_ts))
                        last_vis_update_ts = vis_now
                        rise_alpha = smoothing_alpha_ms(VIS_ATTACK_MS, vis_dt)
                        fall_alpha = smoothing_alpha_ms(VIS_DECAY_MS, vis_dt)
                        trail_alpha = smoothing_alpha_ms(VIS_TRAIL_DECAY_MS, vis_dt)
                        peak_alpha = smoothing_alpha_ms(VIS_PEAK_DECAY_MS, vis_dt)

                        # Time-based smoothing keeps the visualizer responsive even if
                        # the render cadence changes under resize/focus throttling.
                        if smooth_bars is None or len(smooth_bars) != len(bars):
                            smooth_bars = list(bars)
                            peak_bars = list(bars)
                            trail_bars = list(bars)
                        if cap_pos is None or len(cap_pos) != len(bars):
                            cap_pos = list(smooth_bars)
                            cap_vel = [0.0] * len(smooth_bars)
                        _dt = vis_dt
                        _GRAVITY = 4.5
                        _LAUNCH_BASE = 1.0
                        _LAUNCH_GAIN = 1.8
                        smoothed = []
                        new_peaks = []
                        new_trail = []
                        new_cap_pos = []
                        new_cap_vel = []
                        for i, b in enumerate(bars):
                            prev = smooth_bars[i]
                            if b >= prev:
                                s = prev * rise_alpha + b * (1.0 - rise_alpha)
                            else:
                                s = prev * fall_alpha + b * (1.0 - fall_alpha)
                            smoothed.append(s)
                            peak = peak_bars[i]
                            peak = max(s, peak * peak_alpha)
                            new_peaks.append(peak)
                            trail = trail_bars[i]
                            trail = max(s, trail * trail_alpha)
                            new_trail.append(trail)
                            # Physics-based peak cap: launch up on rise, gravity fall
                            pos = cap_pos[i]
                            vel = cap_vel[i]
                            if s >= pos - 0.005:
                                rise = max(0.0, s - pos)
                                vel = _LAUNCH_BASE + _LAUNCH_GAIN * rise
                                pos = s
                            else:
                                vel -= _GRAVITY * _dt
                                pos += vel * _dt
                                if pos < s:
                                    pos = s
                                    vel = 0.0
                            new_cap_pos.append(max(0.0, min(1.0, pos)))
                            new_cap_vel.append(vel)
                        smooth_bars = smoothed
                        peak_bars = new_peaks
                        trail_bars = new_trail
                        cap_pos = new_cap_pos
                        cap_vel = new_cap_vel
                        _n_bass = max(1, len(smooth_bars) // 8)
                        _raw_bass = sum(smooth_bars[:_n_bass]) / _n_bass
                        _bass_fall = smoothing_alpha_ms(80.0, _dt)
                        if _raw_bass >= _bass_energy:
                            _bass_energy = _bass_energy * rise_alpha + _raw_bass * (1.0 - rise_alpha)
                        else:
                            _bass_energy = _bass_energy * _bass_fall + _raw_bass * (1.0 - _bass_fall)

                        draw_mode = VIS_MODES[vis_idx]
                        active_games = current_active_games()
                        game_tag = next(iter(active_games)) if active_games and len(active_games) == 1 else None

                        if draw_mode == "flame":
                            vis_lines = flame_render_lines(smooth_bars, spectrum_height_dyn, bars_len, flame_state, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "wave":
                            vis_lines = braille_wave_lines(smooth_bars, spectrum_height_dyn, bars_len, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "scope":
                            scope_frame += 1
                            vis_lines = braille_scope_lines(smooth_bars, spectrum_height_dyn, bars_len, scope_frame, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "butterfly":
                            vis_lines = butterfly_render_lines(smooth_bars, spectrum_height_dyn, bars_len, butterfly_state, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "led_matrix":
                            vis_lines = led_matrix_lines(smooth_bars, spectrum_height_dyn, bars_len, peak_bars=cap_pos, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "matrix_rain":
                            vis_lines = matrix_rain_lines(smooth_bars, spectrum_height_dyn, bars_len, matrix_state, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "heartbeat":
                            vis_lines = heartbeat_render_lines(smooth_bars, spectrum_height_dyn, bars_len, heartbeat_state, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        elif draw_mode == "braille":
                            vis_lines = braille_spectrum_lines(smooth_bars, spectrum_height_dyn, bars_len, peak_bars=cap_pos, use_color=spectrum_use_color, game_tag=game_tag)
                            lines.extend([prefix + ln for ln in vis_lines])
                        else:
                            pass_peaks = cap_pos if draw_mode == "peaks" else peak_bars
                            # btop data_same: static modes reuse cached lines when bars unchanged
                            _STATIC_VIS = frozenset(("bars", "shades", "outline", "spectrum"))
                            if draw_mode in _STATIC_VIS:
                                _cache_key = (
                                    draw_mode, game_tag,
                                    spectrum_height_dyn, bars_len,
                                    tuple(round(b, 2) for b in smooth_bars),
                                )
                                if _cache_key == _vis_line_cache_key and _vis_line_cache is not None:
                                    lines.extend([prefix + ln for ln in _vis_line_cache])
                                else:
                                    _vis_lines = spectrum_lines(smooth_bars, height=spectrum_height_dyn, use_color=spectrum_use_color, mode=draw_mode, trail_bars=trail_bars, peak_bars=pass_peaks, game_tag=game_tag)
                                    _vis_line_cache = _vis_lines
                                    _vis_line_cache_key = _cache_key
                                    lines.extend([prefix + ln for ln in _vis_lines])
                            else:
                                # peaks has physics caps that always change — never skip
                                lines.extend([prefix + ln for ln in spectrum_lines(smooth_bars, height=spectrum_height_dyn, use_color=spectrum_use_color, mode=draw_mode, trail_bars=trail_bars, peak_bars=pass_peaks, game_tag=game_tag)])
                    elif cava_err:
                        lines.append(prefix + c(format_visualizer_status(cava_err, label=cava_last_label, max_width=bars_len), "31"))
                    elif ok:
                        lines.append(prefix + c("(no data)", "33"))
                    else:
                        warmup_since = max(cava_started_ts, playback_started_ts)
                        if warmup_since and (now - warmup_since) < AUDIO_WARMUP_GRACE:
                            lines.append(prefix)
                        else:
                            lines.append(prefix + c(format_visualizer_status(label=cava_last_label, waiting=True, max_width=bars_len), "33"))
                    # Pad spectrum zone to its exact reserved height
                    while len(lines) < _spec_row0 + spectrum_height_dyn:
                        lines.append("")
                    # btop ├─ section divider with mode label
                    _div_label = f" {VIS_MODES[vis_idx]} "
                    _div_pad = max(0, bars_len - len(_div_label) - 2)
                    _div_l = _div_pad // 2
                    _div_r = _div_pad - _div_l
                    if USE_COLOR and bars_len > len(_div_label) + 4:
                        _div_line = (
                            c256(BOX_CHARS["h"] * _div_l, 238)
                            + c256("├", 240)
                            + c256(_div_label, gradient_at(_active_tod_grad, 80))
                            + c256("┤", 240)
                            + c256(BOX_CHARS["h"] * _div_r, 238)
                        )
                    else:
                        _div_line = c256(BOX_CHARS["h"] * bars_len, 238)
                    lines.append(prefix + _div_line)
                    # Pinned footer: thin TOD-colored separator + always-visible controls hint
                    if footer_has_separator:
                        _sep_col = gradient_at(_active_tod_grad, 30)
                        lines.append(c256("─" * max(1, term_cols - 1), _sep_col) if USE_COLOR else ("-" * max(1, term_cols - 1)))
                    for footer_line in footer_control_lines:
                        if USE_COLOR:
                            lines.append(colorize_hint_keys(footer_line, gradient_at(_active_tod_grad, 85), base_code="2"))
                        else:
                            lines.append(truncate_plain(footer_line, max(1, term_cols - 1)))

                # Handle crossfade volumes (non-blocking)
                if fade:
                    now_ts = time.time()
                    elapsed = now_ts - fade["start_ts"]
                    dur = max(0.05, fade["dur"])
                    if PRIVATE_SINK and loopback_module:
                        target = 100
                    else:
                        target = int(output_vol if output_vol is not None else 50)
                    if muted:
                        new_vol = get_mute_volume()
                        old_vol = get_mute_volume()
                    else:
                        p = max(0.0, min(1.0, elapsed / dur))
                        new_vol = int(target * p)
                        old_vol = int(target * (1.0 - p))
                    set_volume(new_vol, fade["new_ipc"])
                    set_volume(old_vol, fade["old_ipc"])
                    if elapsed >= dur:
                        stop_mpv_proc(fade["old_proc"], fade["old_ipc"])
                        fade = None

                # Hour-change sequence: fade out -> chime -> fade in (non-blocking)
                if transition:
                    now_ts = time.time()
                    phase = transition.get("phase")
                    dur = max(0.1, transition.get("dur", CROSSFADE_SECONDS))
                    if PRIVATE_SINK and loopback_module:
                        target = 100
                    else:
                        target = int(output_vol if output_vol is not None else 50)
                    if phase == "fade_out":
                        p = max(0.0, min(1.0, (now_ts - transition["start_ts"]) / dur))
                        vol = int(target * (1.0 - p)) if not muted else get_mute_volume()
                        set_volume(vol, transition.get("old_ipc"))
                        if p >= 1.0:
                            stop_mpv_proc(transition.get("old_proc"), transition.get("old_ipc"))
                            transition["old_proc"] = None
                            transition["old_ipc"] = None
                            mpv_proc = None
                            # Reset current playback state while chime plays
                            current_track = None
                            current_track_hour = None
                            showing_chime = True
                            chime_proc, chime_kind, chime_temp_path = start_hour_chime(audio_device)
                            if chime_proc is not None:
                                transition["phase"] = "chime"
                            else:
                                showing_chime = False
                                transition["phase"] = "fade_in"
                                transition["start_ts"] = time.time()
                    elif phase == "chime":
                        if chime_proc is None:
                            chime_proc, chime_kind, chime_temp_path = start_hour_chime(audio_device)
                            if chime_proc is None:
                                transition["phase"] = "fade_in"
                                transition["start_ts"] = time.time()
                        if chime_proc is None or chime_proc.poll() is not None:
                            chime_proc = None
                            showing_chime = False
                            chime_kind = None
                            if chime_temp_path:
                                try:
                                    os.unlink(chime_temp_path)
                                except Exception:
                                    pass
                                chime_temp_path = None
                            transition["phase"] = "fade_in"
                            transition["start_ts"] = time.time()
                    elif phase == "fade_in":
                        if transition.get("new_proc") is None:
                            new_proc, new_ipc, _track = start_track_for_hour(transition["next_hour"], volume=0)
                            transition["new_proc"] = new_proc
                            transition["new_ipc"] = new_ipc
                        p = max(0.0, min(1.0, (now_ts - transition["start_ts"]) / dur))
                        vol = int(target * p) if not muted else get_mute_volume()
                        set_volume(vol, transition.get("new_ipc"))
                        if p >= 1.0:
                            # finalize: swap current proc to new proc
                            mpv_proc = transition.get("new_proc")
                            if not transition.get("simulate"):
                                last_hour = transition.get("next_hour", last_hour)
                            transition = None

                # Keep loopback mute/volume in sync even if sink-input appears later
                sync_loopback_state()
                # Pad to fixed terminal height to prevent visual jitter
                if len(lines) < term_rows:
                    lines.extend([""] * (term_rows - len(lines)))
                elif len(lines) > term_rows:
                    lines = lines[:term_rows]

                if lines != last_lines:
                    _ft = time.monotonic()
                    if debug_last_frame_ts:
                        debug_frame_times.append(_ft - debug_last_frame_ts)
                    debug_last_frame_ts = _ft
                    render(lines, term_cols, term_rows)
                    last_lines = list(lines)

                # Non-blocking key read (dynamic refresh rate)
                refresh_interval = IDLE_REFRESH if (background_mode or (FOCUS_THROTTLE and not focused)) else REFRESH_INTERVAL
                fd = sys.stdin.fileno()
                ch = _read_key(fd, timeout=refresh_interval)
                if ch:
                    if ch == "FOCUS_IN":
                        if FOCUS_THROTTLE:
                            focused = True
                            last_lines = None
                        continue
                    if ch == "FOCUS_OUT":
                        if FOCUS_THROTTLE:
                            focused = False
                        continue
                    # Track non-m keypresses to prevent auto-repeat toggling
                    if ch.lower() == "q":
                        handle_exit()
                    if ch.lower() == "n" and transition is None:
                        # skip: crossfade to another random track in same hour
                        start_for_hour(hour, crossfade=True, fade_dur=1.0)
                        next_candidates_ts = 0.0
                        if current_track:
                            _nm = parse_filename(os.path.basename(current_track))
                            _nlabel = f"{_nm['game']}: {_nm['variant']}" if _nm else os.path.basename(current_track)
                            state_banner = (f"♪ {_nlabel}", gradient_at(_active_tod_grad, 75), time.monotonic() + 1.5)
                    if ch == "h":
                        # Simulate hour change: fade out -> chime -> fade in
                        next_hour = (hour + 1) % 24
                        if transition is None:
                            start_hour_transition(next_hour, simulate=True)
                            state_banner = (f"→ Simulating {next_hour:02d}:00", gradient_at(_active_tod_grad, 70), time.monotonic() + 2.0)
                    if ch == "H":
                        show_history_panel = not show_history_panel
                        if not show_history_panel and panel_focus == "history":
                            panel_focus = None
                        hist_cache_key = None
                        last_lines = None
                        state_banner = (f"History: {'shown' if show_history_panel else 'hidden'}", gradient_at(_active_tod_grad, 70), time.monotonic() + 1.5)
                    if ch == "U":
                        show_up_next_panel = not show_up_next_panel
                        if not show_up_next_panel and panel_focus == "up_next":
                            panel_focus = None
                        up_cache_key = None
                        last_lines = None
                        state_banner = (f"Up Next: {'shown' if show_up_next_panel else 'hidden'}", gradient_at(_active_tod_grad, 70), time.monotonic() + 1.5)
                    if ch.lower() == "g":
                        game_idx = (game_idx + 1) % len(games_list)
                        persist_ui_state()
                        start_for_hour(hour, crossfade=False)
                        last_hour = hour  # prevent double-start next frame
                        next_candidates_ts = 0.0
                        state_banner = (f"Game: {current_game_label()}", gradient_at(_active_tod_grad, 75), time.monotonic() + 1.5)
                    if ch.lower() == "v":
                        variant_idx = (variant_idx + 1) % len(variants_list)
                        persist_ui_state()
                        start_for_hour(hour, crossfade=False)
                        last_hour = hour  # prevent double-start next frame
                        next_candidates_ts = 0.0
                        state_banner = (f"Variant: {variants_list[variant_idx]}", gradient_at(_active_tod_grad, 75), time.monotonic() + 1.5)
                    if ch.lower() == "t":
                        vis_idx = (vis_idx + 1) % len(VIS_MODES)
                        persist_ui_state()
                        state_banner = (f"Vis: {VIS_MODES[vis_idx]}", gradient_at(_active_tod_grad, 65), time.monotonic() + 1.2)
                    if ch == "R":
                        vis_idx = random.randrange(len(VIS_MODES))
                        persist_ui_state()
                        state_banner = (f"Vis: {VIS_MODES[vis_idx]}", gradient_at(_active_tod_grad, 65), time.monotonic() + 1.2)
                    if ch == "L":
                        layout_state = cycle_layout_preset(layout_state)
                        persist_ui_state()
                        info_box_cache_key = None
                        hist_cache_key = None
                        up_cache_key = None
                        help_cache_key = None
                        last_lines = None
                        state_banner = (
                            f"Layout: {layout_preset_label(layout_state)}",
                            gradient_at(_active_tod_grad, 75),
                            time.monotonic() + 1.8,
                        )
                    if ch == "C":
                        _cur_theme = get_theme()
                        _ti = THEME_NAMES.index(_cur_theme) if _cur_theme in THEME_NAMES else 0
                        _next_theme = THEME_NAMES[(_ti + 1) % len(THEME_NAMES)]
                        set_theme(_next_theme)
                        persist_ui_state()
                        # Flush gradient caches so all bars repaint
                        import ac_ui.colors as _clrs_ref
                        _clrs_ref._tod_grad_cache = {}
                        info_cache_key = None
                        last_lines = None
                        state_banner = (f"Theme: {_next_theme}", gradient_at(_grad_for_hour(hour), 75), time.monotonic() + 1.8)
                    if ch == "l":
                        repeat_current = not repeat_current
                        persist_ui_state()
                        if current_track and mpv_proc and mpv_proc.poll() is None:
                            try:
                                mpv_command(current_ipc, ["set_property", "loop-file", "inf" if repeat_current else "no"])
                            except Exception:
                                pass
                        last_lines = None
                        state_banner = (
                            ("Playback: Repeat current track" if repeat_current else "Playback: Hour shuffle"),
                            gradient_at(_active_tod_grad, 80 if repeat_current else 70),
                            time.monotonic() + 1.8,
                        )
                    if ch == "p":
                        repeat_current = not repeat_current
                        persist_ui_state()
                        if current_track and mpv_proc and mpv_proc.poll() is None:
                            try:
                                mpv_command(current_ipc, ["set_property", "loop-file", "inf" if repeat_current else "no"])
                            except Exception:
                                pass
                        last_lines = None
                        state_banner = (
                            ("📌 Pinned: will repeat" if repeat_current else "Unpinned"),
                            gradient_at(_active_tod_grad, 80 if repeat_current else 65),
                            time.monotonic() + 1.8,
                        )
                    if ch == "b" and current_track and transition is None:
                        track_name = os.path.basename(current_track)
                        banned_tracks.add(track_name)
                        _nm = parse_filename(track_name)
                        _lbl = f"{_nm['game']}: {_nm['variant']}" if _nm else track_name
                        state_banner = (f"✗ Banned: {_lbl}", 196, time.monotonic() + 2.0)
                        start_for_hour(hour, crossfade=True, fade_dur=0.5)
                        next_candidates_ts = 0.0
                    if ch == "T":
                        run_tune_editor(audio_device)
                        last_lines = None
                        invalidate_render_cache(clear_screen=True)
                    if ch == "E":
                        run_eq_editor(audio_device, lambda: current_ipc)
                        last_lines = None
                        invalidate_render_cache(clear_screen=True)
                    if ch.lower() == "s":
                        if PRIVATE_SINK and private_sink and shutil.which("pactl"):
                            sinks = [sink for sink in list_sinks() if sink != private_sink]
                            if sinks:
                                if current_output_sink in sinks:
                                    idx = (sinks.index(current_output_sink) + 1) % len(sinks)
                                else:
                                    idx = 0
                                next_sink = sinks[idx]
                                loopback_module, current_output_sink = reload_loopback(
                                    loopback_module, private_sink, next_sink
                                )
                                if loopback_module:
                                    set_loopback_volume(
                                        loopback_module,
                                        private_sink,
                                        get_mute_volume() if muted else output_vol,
                                    )
                                    set_loopback_mute(loopback_module, private_sink, muted)
                                    _sink_label = truncate_plain(next_sink, 40)
                                    state_banner = (f"→ Output: {_sink_label}", gradient_at(_active_tod_grad, 80), time.monotonic() + 2.0)
                                else:
                                    state_banner = ("Output switch failed", 196, time.monotonic() + 2.0)
                                last_loopback_ts = 0.0
                                last_loopback_vol = None
                                last_loopback_muted = None
                            else:
                                state_banner = ("No alternate output sink", 220, time.monotonic() + 2.0)
                    if ch == "-":
                        adjust_output_volume(-5)
                        vol_delta_flash = (f"{SYM_VOL_DN} -5", time.monotonic() + 1.2)
                    if ch == "+" or ch == "=":
                        adjust_output_volume(5)
                        vol_delta_flash = (f"{SYM_VOL_UP} +5", time.monotonic() + 1.2)
                    if ch == "PAGEUP":
                        adjust_output_volume(10)
                        vol_delta_flash = (f"{SYM_VOL_UP} +10", time.monotonic() + 1.2)
                    if ch == "PAGEDOWN":
                        adjust_output_volume(-10)
                        vol_delta_flash = (f"{SYM_VOL_DN} -10", time.monotonic() + 1.2)
                    if ch == "8":
                        background_mode = not background_mode
                        last_lines = None
                        state_banner = ("⬛ BACKGROUND MODE ON" if background_mode else "▣  BACKGROUND MODE OFF", 245, time.monotonic() + 1.5)
                    if ch.lower() == "m" or ch == " ":
                        # debounce + ignore auto-repeat bursts
                        now_ts = time.time()
                        if last_key == "m" and (now_ts - last_key_ts) < 0.4:
                            continue
                        if now_ts - last_mute_toggle_ts < 1.0:
                            continue
                        last_mute_toggle_ts = now_ts
                        if muted:
                            state_banner = (f"{SYM_MUTE} UNMUTED", 82, time.monotonic() + 1.5)
                            # Unmute: avoid blocking on pactl; sync loopback in main loop
                            if PRIVATE_SINK and loopback_module:
                                set_output_volume(mute_prev_vol if mute_prev_vol is not None else output_vol)
                                new_vol = mute_prev_vol if mute_prev_vol is not None else output_vol
                            else:
                                new_vol = set_output_volume(mute_prev_vol if mute_prev_vol is not None else 50)
                            muted = False
                            last_loopback_ts = 0.0
                            if new_vol is not None:
                                cached_vol = new_vol
                        else:
                            if (PRIVATE_SINK and loopback_module and output_vol > 0):
                                mute_prev_vol = output_vol
                            elif cached_vol is not None and cached_vol > 0:
                                mute_prev_vol = cached_vol
                            # Mute: silence speakers via loopback, keep signal for visualizer
                            if PRIVATE_SINK and loopback_module:
                                # defer pactl to avoid stutter
                                pass
                            else:
                                set_output_volume(get_mute_volume())
                            muted = True
                            state_banner = (f"{SYM_MUTE} MUTED", 196, time.monotonic() + 1.5)
                            last_loopback_ts = 0.0
                            cached_vol = get_mute_volume()
                        persist_ui_state()
                        last_key = "m"
                        last_key_ts = now_ts
                        continue
                    if ch == "?":
                        show_help = not show_help
                    if ch == "`":
                        show_debug = not show_debug
                    if ch == "\t":
                        _focusable = []
                        if show_history_panel: _focusable.append("history")
                        if show_up_next_panel: _focusable.append("up_next")
                        if not _focusable:
                            panel_focus = None
                        elif panel_focus not in _focusable:
                            panel_focus = _focusable[0]
                        else:
                            _fi = _focusable.index(panel_focus)
                            panel_focus = _focusable[_fi + 1] if _fi + 1 < len(_focusable) else None
                        hist_cache_key = None
                        up_cache_key = None
                        last_lines = None
                    if ch == "UP" and panel_focus:
                        if panel_focus == "history":
                            hist_sel = max(0, hist_sel - 1)
                        elif panel_focus == "up_next":
                            up_sel = max(0, up_sel - 1)
                        hist_cache_key = None
                        up_cache_key = None
                        last_lines = None
                    if ch == "DOWN" and panel_focus:
                        if panel_focus == "history":
                            _h = tuple(history)[-HISTORY_MAX:]
                            hist_sel = min(max(0, len(_h) - 1), hist_sel + 1)
                        elif panel_focus == "up_next":
                            up_sel = min(max(0, len(next_candidates) - 1), up_sel + 1)
                        hist_cache_key = None
                        up_cache_key = None
                        last_lines = None
                    if ch in ("\r", "\n") and panel_focus:
                        if panel_focus == "history":
                            _hlist = list(tuple(history)[-HISTORY_MAX:])
                            _sel = max(0, min(hist_sel, len(_hlist) - 1))
                            if _sel < len(_hlist):
                                _track_name = _hlist[_sel]
                                _track_path = hh_folder(_track_name.split("-")[0] if "-" in _track_name else "14") + "/" + _track_name
                                if not os.path.isfile(_track_path):
                                    _track_path = os.path.join(MUSIC_DIR, _track_name)
                                if start_specific_track(_track_path, crossfade=True):
                                    _nm = parse_filename(_track_name)
                                    _lbl = f"{_nm['game']}: {_nm['variant']}" if _nm else _track_name
                                    state_banner = (f"♪ {_lbl}", gradient_at(_active_tod_grad, 75), time.monotonic() + 1.5)
                                    next_candidates_ts = 0.0
                        elif panel_focus == "up_next" and next_candidates:
                            _sel = max(0, min(up_sel, len(next_candidates) - 1))
                            if _sel > 0:
                                _moved = next_candidates.pop(_sel)
                                next_candidates.insert(0, _moved)
                                up_sel = 0
                                up_cache_key = None
                                last_lines = None
                                state_banner = ("Moved to top of queue", gradient_at(_active_tod_grad, 70), time.monotonic() + 1.5)
                    if ch:
                        last_key = ch.lower()
                        last_key_ts = time.time()
    finally:
        try:
            persist_ui_state()
        except Exception:
            pass
        stop_cava()
        stop_mpv()
        try:
            if os.path.exists(cava_conf_path):
                os.unlink(cava_conf_path)
        except Exception:
            pass
        teardown_private_sink(private_module, loopback_module)
        enable_autowrap()
        show_cursor()
        exit_alt_screen()

if __name__ == "__main__":
    main()

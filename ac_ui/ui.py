import os, sys, time, random, subprocess, json, signal, threading, shutil, re, textwrap, tempfile, struct, math, errno, stat, wave, unicodedata
from collections import deque

import ac_ui.colors as _clrs
import ac_ui.layout as _layout
import ac_ui.term as _term
from ac_ui.colors import (
    USE_COLOR, RESET, c, c256, gradient_at, gradient_bar, paint, solid_bar,
    superscript_num, humanize_seconds, humanize_bytes,
    _GRAD_PLAYBACK, _GRAD_VOLUME,
    _grad_for_hour, set_theme, get_theme, THEME_NAMES, theme_blurb, theme_chrome, theme_display_name, theme_role,
    plain_visible_len, strip_ansi, smoothing_alpha_ms,
)
import ac_ui.colors as _clrs  # for _clrs._active_tod_grad (mutable module global)
from ac_ui.constants import (
    MUSIC_DIR, MPV, CAVA_HEIGHT, CAVA_MAX, CAVA_MIN_BARS, CAVA_MARGIN,
    ASCII_ONLY,
    REFRESH_INTERVAL, IDLE_REFRESH, RESIZE_DEBOUNCE, REFRESH_OVERRIDE_SET,
    vis_frame_interval, default_vis_fps_map,
    VIS_MODES, VIS_MODE, GRADIENT_ANIMATE, GRADIENT_SPEED,
    VIS_ATTACK_MS, VIS_DECAY_MS, VIS_PEAK_DECAY_MS, VIS_TRAIL_DECAY_MS,
    TITLE_ANIMATE, TITLE_ANIM_FPS, BOX_BORDER_SPIN, BOX_BORDER_SPEED,
    FOCUS_THROTTLE, SHOW_TITLE_ART, DEBUG_ART, NO_MOTION,
    STATS_ENABLED, CROSSFADE_SECONDS, PCM_MODE, PRIVATE_SINK, OUTPUT_SINK,
    AUDIO_DEVICE_OVERRIDE, MUTE_MODE, HISTORY_MAX, QUEUE_SIZE, UP_NEXT_MAX,
    TRACK_REPEAT_GUARD,
    SYM_ELLIPSIS, SYM_MUTE, SYM_VOL_UP, SYM_VOL_DN, SYM_PLAY, SYM_PAUSE,
    SYM_BG_OFF, SYM_BG_ON, SYM_NOTE, SYM_PIN, SYM_REMOVE,
    SYM_ROUTE, SYM_SHUFFLE,
    FILENAME_RE, TRACK_LIST_CACHE, HELP_LINES_BASE,
    AUDIO_WARMUP_GRACE, BOX_CHARS, BOX_BORDER_HILITE_LEN,
    _resolve_command_path, DEFAULT_LAYOUT_PRESET, normalize_vis_mode,
    FULLSCREEN_LAYOUT_PRESETS, NOW_PLAYING_TITLE_HINTS, VISUALIZER_TITLE_HINTS,
)
from ac_ui.term import (
    TITLE_ART,
    animate_title_art, build_title_art, render, _read_key, invalidate_render_cache,
    hide_cursor, show_cursor, enable_autowrap, disable_autowrap,
    enter_alt_screen, exit_alt_screen, set_terminal_title, reset_terminal_title,
    rename_process, truncate_plain, truncate_ansi_visible,
    RawMode,
)
from ac_ui.tracks import (
    list_tracks_for_hour, pick_weighted, next_hour_epoch, fmt_mmss,
    collect_catalog, import_files, hh_folder,
    parse_filename, invalidate_track_cache, filter_recent_tracks,
    playback_mode_label, free_play_source_name,
    active_games_from_index, game_label_from_index,
    update_history, compute_next_candidates, free_play_next_candidates,
    load_playlist_source, build_free_play_queue, move_queue_item_to_next,
    list_all_tracks,
)
from ac_ui.audio import (
    mpv_start, mpv_command, mpv_query, mpv_query_props,
    detect_cava_input, setup_private_sink, teardown_private_sink,
    reload_loopback, list_sinks, get_mute_volume, start_hour_chime,
    cleanup_legacy_runtime_artifacts, build_cava_input_candidates, build_pcm_input_candidates,
    pulse_monitor_source_for_audio_device,
    cleanup_stale_socket, convert_midi_to_wav,
    _MIDI_EXTENSIONS, lookup_midi_cache, store_to_midi_cache,
    stop_mpv_proc, set_mpv_volume,
)
from ac_ui.services import CavaRuntime, PcmRuntime, PlaybackCache, PulseRuntime
from ac_ui.audio_snapshot import build_live_audio_snapshot
from ac_ui.town_tune import _wait_for_ipc_socket
from ac_ui.visualizer import (
    render_frame, VisFrameCtx, STATIC_VIS_MODES,
    next_shuffle_mode,
    step_smooth_bars, update_bass_energy,
)
from ac_ui.layout import (
    build_box, pad_box_lines, build_footer_controls,
    wrap_plain, combine_render_columns, stack_render_blocks,
    colorize_hint_keys, format_filter_summary,
    build_ultra_compact_summary, format_visualizer_status,
    layout_mode_for_size, layout_min_spectrum_rows, layout_base_spectrum_rows,
    box_outer_width, build_header_bar,
)
from ac_ui.layout_config import (
    normalize_layout_preset, default_layout_config, normalize_layout_config,
    cycle_layout_preset, layout_preset_label, layout_panels_in_slot,
    _int_opt, _str_opt,
)
from ac_ui.layout_engine import resolve_layout, resolve_panel_max_width, below_panel_inner_width
from ac_ui.stats import (
    load_stats, save_stats, append_stats_csv, start_stats_writer, stats_cli,
    build_hour_histogram_lines, format_seconds,
)
from ac_ui.eq import load_eq_bands, save_eq_bands, apply_mpv_eq, build_mpv_eq_filter
from ac_ui.persist import load_ui_state, save_ui_state
from ac_ui.town_tune import town_tune_cli, normalize_town_tune
from ac_ui.editors import run_eq_editor, run_tune_editor, run_playlist_picker, run_playlist_editor, run_queue_manager, run_add_to_playlist
from ac_ui.palette import run_command_palette
from ac_ui.help_overlay import run_help_overlay
from ac_ui.finder import run_fuzzy_finder, make_item
from ac_ui.feedback import spinner_frame
from ac_ui.keymap import load_key_aliases
from ac_ui.plugins import REGISTRY as plugin_registry, load_plugins, PluginContext
from ac_ui.menu import run_menu
from ac_ui.scan import BackgroundScan
from ac_ui.viewer import run_fullscreen_view
from ac_ui.vis_fps_menu import run_vis_fps_menu
from ac_ui.app import parse_cli_args, build_cache_cli  # noqa: F401 — re-exported for callers
from ac_ui.layout_preview import build_layout_preview, layout_sweep_cli  # noqa: F401 — re-exported for callers
from ac_ui.panels import history as _hist_panel, up_next as _up_next_panel, stats as _stats_panel, help as _help_panel
from ac_ui.panels.now_playing import NowPlayingContext, render as _render_now_playing

_active_tod_grad = _clrs._active_tod_grad

def main():
    rename_process("ac-ui")
    ui_state = load_ui_state()
    mode, allowed_games, cli_vis_mode, import_paths, tune_action, layout_opts = parse_cli_args(sys.argv)
    if mode == "import":
        sys.exit(import_files(import_paths))
    if mode == "build-cache":
        sys.exit(build_cache_cli(import_paths))
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
    resize_pending = False
    last_resize_ts = 0.0
    last_term_cols = None
    last_term_rows = None
    footer_control_lines = []
    footer_has_separator = False
    layout_mode = "normal"
    last_audio_source_kind = "none"
    info_w_cache = 0
    info_cache_key = None
    info_plain_cache = ()
    info_color_cache = ()
    info_box_cache = None
    info_box_cache_key = None
    stats_cache_key = None
    stats_box_cache = None
    stats_w_cache = 0
    stats_rail_cache_key = None
    stats_rail_box_cache = None
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
    layout_plan_cache_key = None
    layout_plan_cache = None
    content_frame_key = None
    content_lines_cache = []

    _pb = PlaybackCache(0.5)

    last_render_key = None
    last_render_ts = 0.0
    last_lines = None
    last_loopback_ts = 0.0
    last_loopback_vol = None
    last_loopback_muted = None
    term_size = shutil.get_terminal_size(fallback=(80, 24))
    term_cols = term_size.columns
    term_rows = term_size.lines
    last_term_cols = term_cols
    last_term_rows = term_rows
    next_term_poll_ts = time.time() + 2.0
    pending_state_payload = None
    next_state_flush_ts = 0.0
    state_flush_delay = 0.35
    pulse_runtime = None
    vis_idx = VIS_MODES.index(ui_state["vis_mode"]) if ui_state["vis_mode"] in VIS_MODES else VIS_MODES.index(VIS_MODE)
    vis_shuffle = bool(ui_state.get("vis_shuffle", False))   # MilkDrop-style preset shuffle
    vis_fps_map = dict(ui_state.get("vis_fps") or default_vis_fps_map())  # per-tier fps
    _shuffle_next_ts = 0.0
    _shuffle_last_switch = 0.0
    _saved_theme = ui_state.get("theme", "default")
    if _saved_theme in THEME_NAMES:
        set_theme(_saved_theme)

    def rebuild_title_art(width):
        art_lines, art_colored, art_base = build_title_art("AC-UI", width)
        TITLE_ART[:] = art_lines
        _term.TITLE_ART_COLORED = art_colored
        _term.TITLE_ART_BASE = art_base
        _term.TITLE_ART_VERSION += 1

    def themed_banner(text, role="accent", ttl=1.5, grad=None):
        if grad is None:
            grad = _active_tod_grad
        return (text, theme_role(role, grad), time.monotonic() + ttl)

    rebuild_title_art(term_cols)
    if DEBUG_ART:
        has_ansi = any("\x1b[" in ln for ln in TITLE_ART)
        sys.stderr.write(
            f"AC_UI_DEBUG_ART: show={SHOW_TITLE_ART} color={USE_COLOR} colored={_term.TITLE_ART_COLORED} "
            f"figlet={shutil.which('figlet')} truecolor={_clrs.TRUECOLOR} ansi={has_ansi}\n"
        )
    bars_len_cached = None
    bars_len_cols = term_cols
    bars_len_count = None
    last_mute_toggle_ts = 0.0
    last_key = ""
    last_key_ts = 0.0
    smooth_bars = None
    peak_bars = None
    trail_bars = None
    _bass_energy = 0.0
    _level_history = deque(maxlen=400)   # rolling bass energy for the header sparkline
    last_vis_update_ts = None
    cap_pos = None    # per-bar peak cap positions for physics-based "peaks" mode
    cap_vel = None    # per-bar peak cap velocities
    # btop data_same: cache spectrum lines when smoothed bars haven't changed
    _vis_line_cache = None
    _vis_line_cache_key = None
    # Per-mode visualizer animation state — each renderer owns its own sub-dict,
    # created lazily via VisFrameCtx.state(<mode>).
    vis_states = {}
    last_title_anim_ts = 0.0
    last_wm_title_ts = 0.0

    muted = ui_state["muted"]
    repeat_current = ui_state["repeat_current"]
    free_play_mode = bool(ui_state.get("free_play_mode", False))
    free_play_dir = str(ui_state.get("free_play_dir", "~/.local/share/ac-terminal-radio/playlists/f2p_nostalgia/f2p_nostalgia.acpl"))
    fp_playlist: list = []
    fp_idx: int = 0
    fp_source_name: str = ""
    fp_wav_cache: dict = {}   # source MIDI path → converted WAV temp path
    # Async MIDI conversion state
    fp_converting: bool = False       # bg conversion in progress, waiting before mpv launch
    _fp_conv_track = None             # source MIDI path being converted
    _fp_conv_crossfade: bool = False
    _fp_conv_result: list = [None]    # [wav_path_or_None] written by thread
    _fp_conv_thread = None
    # Lookahead: pre-convert the *next* MIDI track while current one plays
    _fp_next_track = None
    _fp_next_result: list = [None]
    _fp_next_thread = None
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
    key_aliases = load_key_aliases()   # user keymap.json: {pressed -> canonical}
    load_plugins()                     # user command plugins (~/.config/ac-ui/plugins)
    plugin_keys = plugin_registry.command_keys()
    # Warm the track catalog cache off-thread so the first '/' finder is instant
    # even on a large/cold library; cancelled on exit.
    catalog_warm = BackgroundScan(lambda should_cancel: list_all_tracks()).start()
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
    playback_started_ts = 0.0
    if STATS_ENABLED:
        stats_q, stats_stop = start_stats_writer()

    base_allowed_games = set(allowed_games) if allowed_games else None
    catalog_games, catalog_variants = collect_catalog(base_allowed_games)
    games_list = ["ALL"] + sorted(base_allowed_games or catalog_games)
    variants_list = ["ALL"] + sorted(catalog_variants)
    game_idx = games_list.index(ui_state["game"]) if ui_state["game"] in games_list else 0
    variant_idx = variants_list.index(ui_state["variant"]) if ui_state["variant"] in variants_list else 0

    cava_method, cava_source, cava_detect_mode = detect_cava_input()
    private_sink = None
    private_module = None
    loopback_module = None
    audio_device = None
    output_vol = ui_state["output_vol"]
    current_output_sink = None
    pulse_runtime = PulseRuntime(default_sink_refresh_interval=5.0)
    pulse_runtime.start()
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
                pulse_runtime.configure_loopback(loopback_module, private_sink)
                pulse_runtime.request_volume(output_vol)
    else:
        # If user specified a sink and we're not using a private sink, point mpv at it.
        if OUTPUT_SINK:
            audio_device = f"pulse/{OUTPUT_SINK}"
            cava_method = "pulse"
            cava_source = f"{OUTPUT_SINK}.monitor"
            cava_detect_mode = "output-sink"
            current_output_sink = OUTPUT_SINK

    _cava = CavaRuntime(
        conf_path=cava_conf_path,
        candidates=build_cava_input_candidates(
            cava_method, cava_source, cava_detect_mode,
            audio_device=audio_device, private_sink=private_sink, output_sink=current_output_sink,
        ),
        fallback_method=cava_method,
        fallback_source=cava_source,
        fallback_detect_mode=cava_detect_mode or "configured",
    )
    _pcm = PcmRuntime(
        candidates=build_pcm_input_candidates(
            cava_method, cava_source, cava_detect_mode,
            audio_device=audio_device, private_sink=private_sink, output_sink=current_output_sink,
        ),
        fallback_method=cava_method,
        fallback_source=cava_source,
        fallback_detect_mode=cava_detect_mode or "configured",
    )

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

    def start_for_hour(hour, crossfade=False, fade_dur=None):
        nonlocal mpv_proc, current_track, current_track_hour, current_ipc, fade, playback_started_ts, track_pick_reason
        active_games = active_games_from_index(game_idx, games_list, base_allowed_games)
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
            update_history(track, history, recent_track_paths)
            mpv_proc = new_proc
            current_ipc = next_ipc
            playback_started_ts = time.time()
            return True

        stop_mpv()
        current_track = track
        current_track_hour = hour
        update_history(track, history, recent_track_paths)
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

    def _launch_fp_mpv(playback_path, source_track, crossfade):
        """Start mpv for a free play track, then kick off lookahead for the next."""
        nonlocal mpv_proc, current_track, current_track_hour, current_ipc, fade, playback_started_ts
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
                new_proc = mpv_start(playback_path, next_ipc, audio_device, volume=0, loop_file=False)
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
            stop_mpv()
            try:
                mpv_proc = mpv_start(playback_path, current_ipc, audio_device, loop_file=False)
            except Exception:
                mpv_proc = None
                current_track = None
                return False
            if not _wait_for_ipc_socket(current_ipc):
                stop_mpv_proc(mpv_proc, current_ipc)
                mpv_proc = None
                current_track = None
                return False
            apply_mpv_eq(current_ipc)
            if not (PRIVATE_SINK and loopback_module):
                set_output_volume(output_vol)
            if muted:
                set_output_volume(get_mute_volume())
        if playback_path != source_track:
            fp_wav_cache[source_track] = playback_path
        current_track = source_track
        current_track_hour = None
        update_history(source_track, history, recent_track_paths)
        playback_started_ts = time.time()
        _start_fp_lookahead()
        return True

    def _start_fp_lookahead():
        """Pre-convert the next MIDI track in the playlist while current one plays."""
        nonlocal _fp_next_track, _fp_next_result, _fp_next_thread
        if not fp_playlist:
            return
        next_track = fp_playlist[fp_idx % len(fp_playlist)]
        if os.path.splitext(next_track)[1].lower() not in _MIDI_EXTENSIONS:
            _fp_next_track = None
            _fp_next_thread = None
            return
        if next_track in fp_wav_cache and os.path.isfile(fp_wav_cache[next_track]):
            return  # already cached
        if _fp_next_track == next_track:
            return  # already converting or done for this track
        _fp_next_track = next_track
        _fp_next_result = [None]
        box = _fp_next_result
        def _do(p):
            box[0] = convert_midi_to_wav(p)
        _fp_next_thread = threading.Thread(target=_do, args=(next_track,), daemon=True)
        _fp_next_thread.start()

    def start_free_play_track(crossfade=False):
        nonlocal track_pick_reason, fp_idx
        nonlocal fp_converting, _fp_conv_track, _fp_conv_crossfade, _fp_conv_result, _fp_conv_thread
        nonlocal _fp_next_track, _fp_next_result, _fp_next_thread
        if not fp_playlist:
            return False
        fp_idx = fp_idx % len(fp_playlist)
        track = fp_playlist[fp_idx]
        fp_idx = (fp_idx + 1) % len(fp_playlist)
        track_pick_reason = f"free play ({fp_idx}/{len(fp_playlist)})"
        # Non-MIDI: launch mpv directly
        if os.path.splitext(track)[1].lower() not in _MIDI_EXTENSIONS:
            _fp_next_track = None  # cancel any stale lookahead
            return _launch_fp_mpv(track, track, crossfade)
        # MIDI: check in-memory cache, then persistent cache
        if track in fp_wav_cache and os.path.isfile(fp_wav_cache[track]):
            return _launch_fp_mpv(fp_wav_cache[track], track, crossfade)
        _cached_wav = lookup_midi_cache(track)
        if _cached_wav:
            fp_wav_cache[track] = _cached_wav
            return _launch_fp_mpv(_cached_wav, track, crossfade)
        # MIDI: check if lookahead already has it ready
        if (_fp_next_track == track and _fp_next_thread is not None
                and not _fp_next_thread.is_alive()):
            wav = _fp_next_result[0]
            _fp_next_track = None
            _fp_next_thread = None
            _fp_next_result = [None]
            if wav:
                return _launch_fp_mpv(wav, track, crossfade)
            # lookahead failed — fall through to fresh async conversion
        # MIDI: lookahead in-progress for this track — piggyback on it
        if _fp_next_track == track and _fp_next_thread is not None:
            fp_converting = True
            _fp_conv_track = track
            _fp_conv_crossfade = crossfade
            _fp_conv_result = _fp_next_result
            _fp_conv_thread = _fp_next_thread
            _fp_next_track = None
            _fp_next_thread = None
            return True
        # MIDI: no usable lookahead — start a fresh async conversion
        _fp_conv_track = track
        _fp_conv_crossfade = crossfade
        _fp_conv_result = [None]
        fp_converting = True
        box = _fp_conv_result
        def _do(p):
            box[0] = convert_midi_to_wav(p)
        _fp_conv_thread = threading.Thread(target=_do, args=(track,), daemon=True)
        _fp_conv_thread.start()
        return True

    def start_track_for_hour(hour, volume=None):
        nonlocal current_track, current_track_hour, current_ipc, playback_started_ts, track_pick_reason
        active_games = active_games_from_index(game_idx, games_list, base_allowed_games)
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
        update_history(track, history, recent_track_paths)
        return proc, next_ipc, track

    def start_specific_track(track_path, crossfade=True):
        """Play a specific file immediately, with optional crossfade."""
        nonlocal mpv_proc, current_track, current_track_hour, current_ipc, fade, playback_started_ts, track_pick_reason
        track_pick_reason = "manual"
        if not track_path or not os.path.isfile(track_path):
            return False
        meta = parse_filename(os.path.basename(track_path))
        track_hour = int(meta["hour"]) if meta else int(time.strftime("%H", time.localtime()))
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
        update_history(track_path, history, recent_track_paths)
        return True

    def _enter_free_play(path, *, announce=True):
        """Load a playlist definition, build a fresh shuffled runtime queue.

        Returns the PlaylistSource.  On success free_play_mode is enabled; on
        failure it is disabled and the banner explains *why* (missing files,
        malformed playlist, …) instead of a generic 'no tracks found'.
        """
        nonlocal fp_playlist, fp_source_name, fp_idx, free_play_mode, free_play_dir
        nonlocal next_candidates, next_candidates_key, next_candidates_ts, state_banner
        src = load_playlist_source(path)
        free_play_dir = path
        fp_source_name = src.name
        fp_playlist = build_free_play_queue(src.entries, rng=random, repeat_guard=TRACK_REPEAT_GUARD)
        fp_idx = 0
        next_candidates = []
        next_candidates_key = None
        next_candidates_ts = 0.0
        if fp_playlist:
            free_play_mode = True
            if announce:
                state_banner = themed_banner(
                    f"Free Play: {src.name} ({len(fp_playlist)} tracks)", "value", 2.5)
        else:
            free_play_mode = False
            if src.warnings:
                msg = src.warnings[-1]
            elif src.missing:
                msg = f"all {src.missing} track(s) missing {'-' if ASCII_ONLY else '—'} {src.name}"
            else:
                msg = f"no tracks found in {os.path.basename(path)}"
            if announce:
                state_banner = themed_banner(f"Free Play: {msg}", "danger", 3.0)
        return src

    def set_output_volume(vol):
        nonlocal output_vol, last_loopback_vol
        try:
            v = int(max(0, min(100, vol)))
        except Exception:
            v = 0
        if PRIVATE_SINK and loopback_module:
            output_vol = v
            persist_ui_state()
            if pulse_runtime is not None:
                pulse_runtime.request_volume(v)
            last_loopback_vol = v
            return v
        # fallback to mpv volume
        v2 = set_mpv_volume(v, current_ipc)
        if v2 is not None:
            output_vol = v2
            persist_ui_state()
        return v2

    def _build_ui_state_payload():
        return {
            "output_vol": int(max(0, min(100, output_vol))),
            "muted": bool(muted),
            "mute_prev_vol": int(max(0, min(100, mute_prev_vol if mute_prev_vol is not None else output_vol))),
            "vis_mode": VIS_MODES[vis_idx],
            "vis_shuffle": bool(vis_shuffle),
            "vis_fps": dict(vis_fps_map),
            "repeat_current": bool(repeat_current),
            "game": games_list[game_idx] if 0 <= game_idx < len(games_list) else "ALL",
            "variant": variants_list[variant_idx] if 0 <= variant_idx < len(variants_list) else "ALL",
            "layout": normalize_layout_config(layout_state, default_preset=DEFAULT_LAYOUT_PRESET),
            "theme": get_theme(),
            "free_play_mode": bool(free_play_mode),
            "free_play_dir": str(free_play_dir),
            "free_play_queue": list(fp_playlist) if free_play_mode else [],
            "free_play_idx": int(fp_idx) if free_play_mode else 0,
        }

    def flush_ui_state(force=False):
        nonlocal pending_state_payload, next_state_flush_ts
        if pending_state_payload is None:
            return
        if (not force) and time.time() < next_state_flush_ts:
            return
        try:
            save_ui_state(pending_state_payload)
        except Exception:
            pass
        pending_state_payload = None
        next_state_flush_ts = 0.0

    def persist_ui_state(force=False):
        nonlocal pending_state_payload, next_state_flush_ts
        pending_state_payload = _build_ui_state_payload()
        next_state_flush_ts = time.time() if force else (time.time() + state_flush_delay)
        if force:
            flush_ui_state(force=True)

    def adjust_output_volume(delta):
        nonlocal mute_prev_vol, output_vol
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
            _pb.vol = new_vol
            persist_ui_state()
            return new_vol
        new_vol = set_output_volume(output_vol + delta)
        if new_vol is not None:
            _pb.vol = new_vol
        return new_vol

    def sync_loopback_state():
        nonlocal last_loopback_ts, last_loopback_vol, last_loopback_muted
        if not (PRIVATE_SINK and loopback_module and private_sink and pulse_runtime is not None):
            return
        now = time.time()
        state_changed = (last_loopback_vol != output_vol) or (last_loopback_muted != muted)
        if not state_changed:
            return
        if now - last_loopback_ts < 1.0 and last_loopback_vol is None:
            return
        if not pulse_runtime.loopback_input_ids():
            last_loopback_ts = now
            last_loopback_vol = None
            last_loopback_muted = None
            pulse_runtime.request_refresh()
            return
        last_loopback_ts = now
        # Apply mute/unmute to loopback when sink-input appears
        if MUTE_MODE == "hard":
            pulse_runtime.request_mute(muted)
        pulse_runtime.request_volume(output_vol)
        last_loopback_vol = output_vol
        last_loopback_muted = muted

    def handle_exit(signum=None, frame=None):
        flush_ui_state(force=True)
        if pulse_runtime is not None:
            pulse_runtime.stop()
        _cava.stop()
        _pcm.stop()
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
        for _wav_tmp in fp_wav_cache.values():
            try:
                os.unlink(_wav_tmp)
            except Exception:
                pass
        try:
            if os.path.exists(_cava.conf_path):
                os.unlink(_cava.conf_path)
        except Exception:
            pass
        teardown_private_sink(private_module, loopback_module)
        enable_autowrap()
        show_cursor()
        reset_terminal_title()
        exit_alt_screen()
        sys.exit(0)

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

    if free_play_mode:
        # Restore the exact queue saved last session (so edits/reorders survive a
        # restart) before falling back to a fresh shuffle of the source.
        _restored = [p for p in (ui_state.get("free_play_queue") or []) if os.path.isfile(p)]
        if _restored:
            fp_playlist = _restored
            fp_source_name = free_play_source_name(free_play_dir)
            fp_idx = max(0, min(int(ui_state.get("free_play_idx", 0) or 0), len(fp_playlist)))
        else:
            _enter_free_play(free_play_dir, announce=False)
        _start_fp_lookahead()

    _cava.start()
    if PCM_MODE != "off":
        _pcm.start()

    enter_alt_screen()
    set_terminal_title("ac-ui")
    hide_cursor()
    disable_autowrap()
    try:
        with RawMode():
            while True:
                now = time.time()
                hour = int(time.strftime("%H", time.localtime(now)))
                if now - last_wm_title_ts >= 1.0:
                    set_terminal_title("ac-ui")
                    last_wm_title_ts = now
                if GRADIENT_ANIMATE:
                    _layout.BOX_GRADIENT_PHASE = (now * GRADIENT_SPEED) % 1.0
                if BOX_BORDER_SPIN:
                    _layout.BOX_BORDER_POS = int(now * BOX_BORDER_SPEED)
                # Beat-reactive border glow: feed last frame's bass energy to build_box.
                _layout.BOX_PULSE = max(0.0, min(1.0, _bass_energy))
                _pulse_bucket = int(_layout.BOX_PULSE * 6)   # quantize so boxes rebuild ~6 steps
                if TITLE_ANIMATE and _term.TITLE_ART_BASE and (not background_mode) and (focused or not FOCUS_THROTTLE):
                    interval = 1.0 / max(1.0, TITLE_ANIM_FPS)
                    if now - last_title_anim_ts >= interval:
                        art_phase = (now * max(0.25, TITLE_ANIM_FPS) * 0.17) % 1.0
                        TITLE_ART[:], _term.TITLE_ART_COLORED = animate_title_art(_term.TITLE_ART_BASE, art_phase)
                        _term.TITLE_ART_VERSION += 1
                        last_title_anim_ts = now
                term_changed = False
                if resize_pending and (now - last_resize_ts) >= RESIZE_DEBOUNCE:
                    term_size = shutil.get_terminal_size(fallback=(80, 24))
                    resize_pending = False
                    next_term_poll_ts = now + 2.0
                elif now >= next_term_poll_ts:
                    term_size = shutil.get_terminal_size(fallback=(80, 24))
                    next_term_poll_ts = now + 2.0
                else:
                    term_size = None
                if term_size is not None:
                    term_cols = term_size.columns
                    term_rows = term_size.lines
                if term_size is not None and (term_cols != last_term_cols or term_rows != last_term_rows):
                    term_changed = True
                    last_term_cols = term_cols
                    last_term_rows = term_rows
                    info_w_cache = 0
                    content_frame_key = None
                    layout_plan_cache_key = None
                    layout_plan_cache = None
                    layout_mode = layout_mode_for_size(term_cols, term_rows)
                    _uc = term_rows < 10
                    _tiny = layout_mode == "tiny"
                    footer_control_lines, footer_has_separator = build_footer_controls(
                        term_cols, term_rows, tiny_term=_tiny, ultra_compact=_uc,
                    )
                    rebuild_title_art(term_cols)

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
                if free_play_mode:
                    if needs_start and not fp_converting and transition is None and fp_playlist:
                        start_free_play_track(crossfade=False)
                    last_hour = hour
                else:
                    if hour_changed and transition is None:
                        start_hour_transition(hour, simulate=False)
                    if needs_start and transition is None:
                        start_for_hour(hour, crossfade=False)
                        last_hour = hour

                # Async MIDI conversion completion
                if (free_play_mode and fp_converting
                        and _fp_conv_thread is not None
                        and not _fp_conv_thread.is_alive()):
                    fp_converting = False
                    _wav = _fp_conv_result[0]
                    _src = _fp_conv_track
                    _xfade = _fp_conv_crossfade
                    _fp_conv_track = None
                    _fp_conv_result = [None]
                    _fp_conv_thread = None
                    if _wav and _src:
                        fp_wav_cache[_src] = _wav
                        store_to_midi_cache(_src, _wav)
                        _launch_fp_mpv(_wav, _src, _xfade)
                    # If conversion failed, fp_idx was already advanced in
                    # start_free_play_track; let needs_start pick up the next
                    # track on the following frame to avoid double-advancing.

                # UI stats
                if term_changed:
                    resize_pending = False
                    _cava.stop()
                    _cava.start()
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
                tpos, dur, vol = _pb.query(current_ipc, current_track, transition, fade)

                # Recover if playback is live but cava never attached to the monitor stream.
                playback_live = bool(current_track and mpv_proc and mpv_proc.poll() is None)
                if _cava.proc is not None and _cava.proc.poll() is not None:
                    code = _cava.proc.poll()
                    detail = f"cava exited ({code})"
                    if _cava.last_label:
                        detail += f" via {_cava.last_label}"
                    if _cava.last_stderr:
                        detail += f": {_cava.last_stderr}"
                    _cava.err = detail
                    if playback_live and (not transition) and (not fade) and (now - _cava.retry_ts) >= 1.0:
                        _cava.restart(advance=True)
                elif playback_live and (not transition) and (not fade) and (not _cava.ok) and (not _cava.err):
                    retry_anchor = max(_cava.started_ts, playback_started_ts)
                    if retry_anchor and (now - retry_anchor) >= AUDIO_WARMUP_GRACE and (now - _cava.retry_ts) >= 3.0:
                        _cava.restart(advance=True)
                if PCM_MODE != "off" and _pcm.proc is not None and _pcm.proc.poll() is not None:
                    code = _pcm.proc.poll()
                    detail = f"pcm capture exited ({code})"
                    if _pcm.last_backend:
                        detail += f" via {_pcm.last_backend}"
                    if _pcm.last_label:
                        detail += f" [{_pcm.last_label}]"
                    if _pcm.last_stderr:
                        detail += f": {_pcm.last_stderr}"
                    _pcm.err = detail
                    if playback_live and (not transition) and (not fade) and (now - _pcm.retry_ts) >= 1.0:
                        _pcm.restart(advance=True)
                elif PCM_MODE != "off" and playback_live and (not transition) and (not fade) and (not _pcm.ok) and (not _pcm.err):
                    retry_anchor = max(_pcm.started_ts, playback_started_ts)
                    if retry_anchor and (now - retry_anchor) >= AUDIO_WARMUP_GRACE and (now - _pcm.retry_ts) >= 3.0:
                        _pcm.restart(advance=True)

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
                _level_history.append(_bass_energy)
                lines.append(build_header_bar(term_cols, last_time_str, _bass_energy, _active_tod_grad, current_track, muted, ultra_compact, level_history=_level_history))

                # btop ▲▼ volume delta flash (shown inline next to vol label)
                _vol_flash_str = ""
                if vol_delta_flash is not None:
                    delta_text, delta_expire = vol_delta_flash
                    if time.monotonic() < delta_expire:
                        _tod_flash_col = theme_role("title", _active_tod_grad)
                        _vol_flash_str = f"  {paint(delta_text, fg=_tod_flash_col, bold=True)}" if USE_COLOR else f"  {delta_text}"
                    else:
                        vol_delta_flash = None

                if ultra_compact:
                    compact_summary = truncate_plain(
                        build_ultra_compact_summary(
                            game_label_from_index(game_idx, games_list, base_allowed_games),
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
                    lines.append(c256(compact_summary, theme_role("label", _active_tod_grad)) if USE_COLOR else compact_summary)

                # Content zone budget (chrome + footer + spectrum already reserved)
                max_info_rows = max(0, _max_content_rows - 2)  # 2 for box borders
                compact_info = max_info_rows < 10 or term_cols < 70 or ultra_compact

                # Width Now Playing will actually be boxed at, computed up front so its
                # content (long meters, art mosaic) is rendered to fit and never clipped
                # by a later narrower rebuild.  Erring toward the sidebar-present (narrow)
                # width is safe: if no sidebar shows, the box just pads on the right.
                _np_preset = normalize_layout_config(layout_state, default_preset=DEFAULT_LAYOUT_PRESET)["preset"]
                _np_pmw = resolve_panel_max_width(term_cols, _np_preset)
                _np_will_sidebar = (
                    (not ultra_compact) and (not compact_info)
                    and ((show_history_panel and not tiny_term)
                         or (show_up_next_panel and not (tiny_term or small_term)))
                )
                # 2-col right margin matches resolve_layout + the visualizer box,
                # so the top row never reaches the screen edge (avoids right-side clipping).
                if _np_will_sidebar:
                    _np_target_w = term_cols - 2 - 3 - box_outer_width(_np_pmw) - 4
                else:
                    _np_target_w = term_cols - 2 - 4
                _np_target_w = max(20, min(info_max_width, _np_target_w))

                info = []
                info_plain = []
                if not ultra_compact:
                    _game_label = game_label_from_index(game_idx, games_list, base_allowed_games)
                    info_key = (
                        term_cols,
                        info_max_width,
                        compact_info,
                        tiny_term,
                        _term.TITLE_ART_VERSION,
                        _game_label,
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
                        (now_sec if not NO_MOTION else 0),
                        bool(vol_delta_flash and time.monotonic() < vol_delta_flash[1]),
                        track_pick_reason,
                    )
                    if info_key != info_cache_key:
                        _np_ctx = NowPlayingContext(
                            compact=compact_info,
                            max_width=_np_target_w,
                            current_track=current_track,
                            current_track_hour=current_track_hour,
                            hour=hour,
                            tpos=tpos,
                            dur=dur,
                            showing_chime=showing_chime,
                            chime_kind=chime_kind,
                            repeat_current=repeat_current,
                            track_pick_reason=track_pick_reason,
                            background_mode=background_mode,
                            muted=muted,
                            game_label=_game_label,
                            variant=variants_list[variant_idx],
                            vis_mode=VIS_MODES[vis_idx],
                            display_vol=display_vol,
                            vol_flash_str=_vol_flash_str,
                            remaining=remaining,
                            pulse_bright=(not NO_MOTION) and (int(now) % 2 == 0),
                            title_art=list(TITLE_ART) if (not compact_info) and TITLE_ART else [],
                            title_art_colored=_term.TITLE_ART_COLORED,
                            tod_grad=_active_tod_grad,
                        )
                        info_plain, info = _render_now_playing(_np_ctx)
                        info_cache_key = info_key
                        info_plain_cache = tuple(info_plain)
                        info_color_cache = tuple(info)
                    else:
                        info_plain = list(info_plain_cache)
                        info = list(info_color_cache)

                # Fixed sidebar depth keeps the visualizer dominant and Stats in
                # frame: the content zone above the spectrum is zero-sum, so the
                # spectrum (not the panels) absorbs spare vertical space.
                _up_show = UP_NEXT_MAX
                _hist_show = HISTORY_MAX
                _cand_count = QUEUE_SIZE

                # Refresh "next candidates" on filter/hour/track change (sorted, stable)
                if free_play_mode:
                    fp_cand_key = ("fp", fp_idx, len(fp_playlist), current_track, _cand_count)
                    if fp_cand_key != next_candidates_key:
                        next_candidates = free_play_next_candidates(fp_playlist, fp_idx, _cand_count)
                        next_candidates_key = fp_cand_key
                        next_candidates_ts = now
                else:
                    active_games = active_games_from_index(game_idx, games_list, base_allowed_games)
                    active_variants = None if variant_idx == 0 else {variants_list[variant_idx]}
                    cand_key = (hour, game_idx, variant_idx, current_track, frozenset(banned_tracks), _cand_count)
                    if cand_key != next_candidates_key:
                        next_candidates = list(compute_next_candidates(hour, active_games, active_variants, current_track, recent_track_paths, banned_tracks, _cand_count))
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
                        # Box at the precomputed target width so content fits exactly.
                        _ibox_key = (info_cache_key, _np_target_w, show_help, compact_info, _pulse_bucket)
                        if _ibox_key != info_box_cache_key:
                            info_box_cache, _ = build_box(
                                info_plain, info,
                                maxw_override=_np_target_w,
                                title="Now Playing",
                                title2=NOW_PLAYING_TITLE_HINTS,
                            )
                            info_box_cache_key = _ibox_key
                        info_box = info_box_cache
                        info_w = _np_target_w

                stats_box = None
                stats_w = 0
                if (not ultra_compact) and STATS_ENABLED and stats_data is not None:
                    total_sec = int(stats_data.get("total_listen_seconds", 0) + session_listen)
                    hb = stats_data.get("hour_buckets", [0] * 24)
                    # Stretch Stats to the full content width (btop-style) rather
                    # than leaving a dead strip on the right.
                    stats_inner_width = max(28, term_cols - 6)
                    stats_key = (total_sec, int(session_listen), tuple(int(v) for v in hb), hour, stats_inner_width, _pulse_bucket)
                    if stats_key != stats_cache_key:
                        stats_plain, stats_color = _stats_panel.render(
                            stats_data, session_listen, stats_inner_width, hour, _active_tod_grad,
                        )
                        stats_box_cache, stats_w_cache = build_box(stats_plain, stats_color, maxw_override=stats_inner_width, title="Stats")
                        stats_cache_key = stats_key
                    stats_box = stats_box_cache
                    stats_w = stats_w_cache

                max_content_end = _chrome_rows + _max_content_rows
                layout_snapshot = normalize_layout_config(layout_state, default_preset=DEFAULT_LAYOUT_PRESET)
                layout_preset = layout_snapshot["preset"]
                # Fullscreen preset: the visualizer owns the whole screen, so drop
                # the stats bar (panels are suppressed just below).
                _fullscreen_layout = layout_preset in FULLSCREEN_LAYOUT_PRESETS
                if _fullscreen_layout:
                    stats_box = None

                if info_box and (len(lines) + len(info_box) > max_content_end):
                    max_rows = max(0, max_content_end - len(lines) - 2)
                    if len(info_plain) > max_rows:
                        info_plain = info_plain[:max_rows]
                        info = info[:max_rows]
                        info_w_needed = max([plain_visible_len(line) for line in info_plain] + [0])
                        info_w_cache = min(info_max_width, max(info_w_cache, info_w_needed))
                        info_box, info_w = build_box(
                            info_plain, info,
                            info_w_cache,
                            title="Now Playing",
                            title2=NOW_PLAYING_TITLE_HINTS,
                        )

                show_history = show_history_panel and (not tiny_term) and (not ultra_compact) and (not compact_info)
                show_up_next = show_up_next_panel and (not (tiny_term or small_term)) and (not ultra_compact) and (not compact_info)
                if (max_content_end - len(lines)) <= 0 or _fullscreen_layout:
                    show_history = False
                    show_up_next = False
                panel_max_width = resolve_panel_max_width(term_cols, layout_preset)
                # Panels in the full-width "below" row tile the whole row instead
                # of sitting at the narrow sidebar width.
                _below_names = layout_panels_in_slot(layout_snapshot, "below")
                _below_fill_w = below_panel_inner_width(term_cols, len(_below_names)) if _below_names else panel_max_width
                _hist_target_w = _below_fill_w if "history" in _below_names else panel_max_width
                _up_target_w = _below_fill_w if "up_next" in _below_names else panel_max_width

                hist_box = None
                up_box = None
                hist_w = 0
                up_w = 0
                if show_history:
                    hist_list = tuple(history)[-_hist_show:]
                    _hist_focused = panel_focus == "history"
                    _hist_sel_clamped = max(0, min(hist_sel, len(hist_list) - 1)) if hist_list else 0
                    hist_key = (hist_list, _hist_target_w, hour, layout_preset, _hist_focused, _hist_sel_clamped, _pulse_bucket)
                    if hist_key != hist_cache_key:
                        hist_plain, hist_color = _hist_panel.render(
                            list(hist_list), _hist_target_w, _active_tod_grad, _hist_focused, _hist_sel_clamped,
                        )
                        hist_box_cache, hist_w_cache = build_box(hist_plain, hist_color, maxw_override=_hist_target_w, title="History", focused=_hist_focused)
                        hist_cache_key = hist_key
                    hist_box = hist_box_cache
                    hist_w = hist_w_cache

                if show_up_next:
                    next_list = next_candidates
                    _up_focused = panel_focus == "up_next"
                    _up_sel_clamped = max(0, min(up_sel, len(next_list) - 1)) if next_list else 0
                    up_key = (next_list, _up_target_w, _up_show, hour, layout_preset, _up_focused, _up_sel_clamped, _pulse_bucket)
                    if up_key != up_cache_key:
                        up_plain, up_color = _up_next_panel.render(
                            list(next_list), _up_target_w, _active_tod_grad, _up_focused, _up_sel_clamped,
                            max_shown=_up_show,
                        )
                        _up_count = f"{min(_up_show, len(next_list))}/{len(next_list)}" if next_list else None
                        up_box_cache, up_w_cache = build_box(up_plain, up_color, maxw_override=_up_target_w, title="Up Next", title2=_up_count, focused=_up_focused)
                        up_cache_key = up_key
                    up_box = up_box_cache
                    up_w = up_w_cache

                # Stats placement: by default it renders full-width below, but a
                # preset (e.g. wide_graph) can route it into the side rail so the
                # visualizer keeps the full height. Only non-"full" slots take the
                # new path, so the default presets are completely unaffected.
                stats_slot = layout_snapshot["panels"].get("stats", {}).get("slot", "full")
                stats_rail_box = None
                if stats_box is not None and stats_slot in ("sidebar", "below") and stats_data is not None:
                    _sr_key = (stats_cache_key, panel_max_width)
                    if _sr_key != stats_rail_cache_key or stats_rail_box_cache is None:
                        _srp, _src = _stats_panel.render(
                            stats_data, session_listen, panel_max_width, hour, _active_tod_grad,
                        )
                        stats_rail_box_cache = build_box(_srp, _src, maxw_override=panel_max_width, title="Stats")[0]
                        stats_rail_cache_key = _sr_key
                    stats_rail_box = stats_rail_box_cache

                panel_boxes = {
                    "history": (hist_box, box_outer_width(hist_w)),
                    "up_next": (up_box, box_outer_width(up_w)),
                }
                if stats_rail_box:
                    panel_boxes["stats"] = (stats_rail_box, box_outer_width(panel_max_width))
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
                _plan_key = (
                    term_cols,
                    max_content_end - len(lines),
                    info_w if info_box else 0,
                    tuple(_sidebar_eligible),
                    tuple(_below_eligible),
                    layout_preset,
                )
                if _plan_key != layout_plan_cache_key or layout_plan_cache is None:
                    layout_plan_cache = resolve_layout(
                        term_cols,
                        avail_rows=max_content_end - len(lines),
                        info_natural_w=info_w if info_box else 0,
                        sidebar_candidates=_sidebar_eligible,
                        below_candidates=_below_eligible,
                        layout_preset=layout_preset,
                    )
                    layout_plan_cache_key = _plan_key
                _plan = layout_plan_cache

                if info_box:
                    top_lines = None
                    if _plan.sidebar:
                        _sb_blocks = [panel_boxes[name] for name in _plan.sidebar]
                        sidebar_lines, sidebar_outer = stack_render_blocks(_sb_blocks)
                        _itw = _plan.info_target_w or info_w
                        if _itw != info_w:
                            info_box_fit, info_w_fit = build_box(
                                info_plain, info, maxw_override=_itw,
                                title="Now Playing", title2=NOW_PLAYING_TITLE_HINTS,
                            )
                        else:
                            info_box_fit, info_w_fit = info_box, info_w
                        candidate_lines, candidate_width = combine_render_columns(
                            [(info_box_fit, box_outer_width(info_w_fit)), (sidebar_lines, sidebar_outer)]
                        )
                        if candidate_width <= term_cols and (len(lines) + len(candidate_lines) <= max_content_end):
                            top_lines = candidate_lines
                    if top_lines is None:
                        # No sidebar this frame — stretch the info box to fill the
                        # full width so the top row matches the visualizer below.
                        _fw = _plan.info_target_w or info_w
                        if _fw != info_w:
                            info_box, info_w = build_box(
                                info_plain, info, maxw_override=_fw,
                                title="Now Playing", title2=NOW_PLAYING_TITLE_HINTS,
                            )
                        if len(lines) + len(info_box) <= max_content_end:
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
                            help_sink_cache = (
                                pulse_runtime.default_sink() if pulse_runtime is not None else None
                            ) or "(unknown)"
                            help_sink_cache_ts = now
                        help_sink = help_sink_cache
                    help_max_width = max(14, min(info_max_width, term_cols - 8))
                    help_key = (help_sink, hour, help_max_width, help_rows_budget)
                    if help_key != help_cache_key:
                        _hp, _hc = _help_panel.render(
                            HELP_LINES_BASE, help_sink, help_max_width, help_rows_budget - 2, _active_tod_grad,
                        )
                        help_box_cache = build_box(_hp, _hc, maxw_override=help_max_width, title="Help")[0] if _hp else None
                        help_cache_key = help_key
                    if help_box_cache and (len(lines) + len(help_box_cache) <= max_content_end):
                        lines.extend(help_box_cache)

                # Full-width stats only when its slot is "full" (the default).
                # When routed to the rail/below it's already composited above.
                if stats_box and stats_slot == "full" and (len(lines) + len(stats_box) <= max_content_end):
                    lines.extend(stats_box)

                if show_debug and (not ultra_compact) and (max_content_end - len(lines)) >= 4:
                    _avg_ms = (sum(debug_frame_times) / len(debug_frame_times) * 1000) if debug_frame_times else 0.0
                    _cava_st = "running" if _cava.is_running else "stopped"
                    _pcm_st = "disabled" if PCM_MODE == "off" else ("running" if _pcm.is_running else "stopped")
                    if PCM_MODE != "off" and _pcm.last_backend:
                        _pcm_st += f"/{_pcm.last_backend}"
                    _audio_route = f"{private_sink} {SYM_ROUTE} {current_output_sink}" if private_sink else (current_output_sink or "default")
                    _dbg_lines = [
                        f"term: {term_cols}×{term_rows}  layout: {layout_mode}  preset: {layout_preset_label(layout_state)}",
                        f"vis: {VIS_MODES[vis_idx]}  repeat: {'on' if repeat_current else 'off'}  bg: {'on' if background_mode else 'off'}  focused: {'yes' if focused else 'no'}",
                        f"panels: history={'on' if show_history_panel else 'off'}  up_next={'on' if show_up_next_panel else 'off'}",
                        f"audio: {_audio_route}  cava: {_cava_st}  pcm: {_pcm_st}  source: {last_audio_source_kind}",
                        f"frame: {_avg_ms:.0f}ms avg  lines: {len(lines)}/{term_rows}  refresh: {int((IDLE_REFRESH if (background_mode or (FOCUS_THROTTLE and not focused)) else REFRESH_INTERVAL)*1000)}ms",
                    ]
                    _dbg_w = max(14, min(term_cols - 8, max(len(s) for s in _dbg_lines)))
                    if USE_COLOR:
                        _dbg_col = theme_role("label_dim", _active_tod_grad)
                        _dbg_color = [paint(s, fg=_dbg_col, dim=True) for s in _dbg_lines]
                    else:
                        _dbg_color = list(_dbg_lines)
                    _dbg_box, _ = build_box(_dbg_lines, _dbg_color, maxw_override=_dbg_w, title="Debug  [`] to close")
                    if len(lines) + len(_dbg_box) <= max_content_end:
                        lines.extend(_dbg_box)

                prefix = "  "

                # Show converting indicator while MIDI is rendering in background
                if free_play_mode and fp_converting:
                    _conv_name = os.path.basename(_fp_conv_track) if _fp_conv_track else "MIDI"
                    _spin = spinner_frame(time.monotonic())
                    state_banner = themed_banner(f"{_spin} Converting: {_conv_name}", "accent", 0.2)

                # btop state banner: full-width flash for mute/unmute/bg-mode events
                if state_banner is not None:
                    banner_text, banner_color, banner_expire = state_banner
                    if time.monotonic() < banner_expire:
                        banner_plain = truncate_plain(str(banner_text), max(4, term_cols - 3))
                        if USE_COLOR:
                            lines.append(f"  {paint(banner_plain, fg=banner_color, bold=True)}")
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
                with _cava._lock:
                    cava_bars = list(_cava.bars) if _cava.bars else None
                    ok = _cava.ok
                # Cache bars_len based on terminal width and cava bar count
                if bars_len_cached is None or bars_len_cols != term_cols or bars_len_count != (_cava.bars_count or 0):
                    bars_len_cols = term_cols
                    bars_len_count = _cava.bars_count or 0
                    max_len = max(CAVA_MIN_BARS, term_cols - CAVA_MARGIN)
                    available = max(10, term_cols - len(prefix) - CAVA_MARGIN)
                    bars_len = len(cava_bars) if cava_bars else (_cava.bars_count or max_len)
                    if bars_len > max_len:
                        bars_len = max_len
                    if bars_len > available:
                        bars_len = available
                    bars_len_cached = bars_len
                else:
                    bars_len = bars_len_cached
                bars = list(cava_bars) if cava_bars else None
                _wave_frames = max(1024, min(2048, max(1, bars_len) * 16))
                _wave_left, _wave_right = _pcm.waveform_window(_wave_frames) if _pcm.ok else ((), ())
                if spectrum_height_dyn > 0:
                    _spec_row0 = len(lines)
                    _vis_boxed = False
                    if bars and bars_len is not None and len(bars) > bars_len:
                        bars = bars[:bars_len]
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
                    if not bars and _pcm.ok and (_wave_left or _wave_right):
                        _pcm_fallback = build_live_audio_snapshot(
                            (),
                            vis_states.setdefault("_audio_pcm_fallback", {}),
                            waveform_left=_wave_left,
                            waveform_right=_wave_right,
                            sample_rate=_pcm.sample_rate,
                            frame_dt=vis_dt,
                            fallback_bar_count=bars_len,
                        )
                        if _pcm_fallback.source_kind != "none":
                            last_audio_source_kind = _pcm_fallback.source_kind
                        bars = list(_pcm_fallback.bars) if _pcm_fallback.bars else None
                    if bars:

                        # Time-based smoothing keeps the visualizer responsive even if
                        # the render cadence changes under resize/focus throttling.
                        if smooth_bars is None or len(smooth_bars) != len(bars):
                            smooth_bars = list(bars)
                            peak_bars = list(bars)
                            trail_bars = list(bars)
                        if cap_pos is None or len(cap_pos) != len(bars):
                            cap_pos = list(smooth_bars)
                            cap_vel = [0.0] * len(smooth_bars)
                        smooth_bars, peak_bars, trail_bars, cap_pos, cap_vel = step_smooth_bars(
                            bars, smooth_bars, peak_bars, trail_bars, cap_pos, cap_vel,
                            rise_alpha, fall_alpha, trail_alpha, peak_alpha, vis_dt,
                        )
                        _audio_snapshot = build_live_audio_snapshot(
                            tuple(smooth_bars),
                            vis_states.setdefault("_audio", {}),
                            waveform_left=_wave_left,
                            waveform_right=_wave_right,
                            sample_rate=_pcm.sample_rate if _pcm.ok else 0,
                            frame_dt=vis_dt,
                            fallback_bar_count=bars_len,
                        )
                        last_audio_source_kind = _audio_snapshot.source_kind
                        _bass_energy = update_bass_energy(
                            list(_audio_snapshot.analysis_bars or _audio_snapshot.bars),
                            _bass_energy, rise_alpha, vis_dt,
                        )
                        _audio_features = _audio_snapshot.features

                        # Preset shuffle: drift to a new visualizer on a timer, and
                        # snap early on a strong beat once it's settled for a moment.
                        if vis_shuffle:
                            _since_switch = now - _shuffle_last_switch
                            _beat_snap = _since_switch >= 6.0 and _audio_features.onset > 0.35
                            if now >= _shuffle_next_ts or _beat_snap:
                                vis_idx = VIS_MODES.index(next_shuffle_mode(VIS_MODES[vis_idx]))
                                _shuffle_last_switch = now
                                _shuffle_next_ts = now + 14.0 + random.random() * 6.0
                                persist_ui_state()

                        draw_mode = VIS_MODES[vis_idx]
                        active_games = active_games_from_index(game_idx, games_list, base_allowed_games)
                        game_tag = next(iter(active_games)) if active_games and len(active_games) == 1 else None

                        # Frame the visualizer in its own titled box (matching every
                        # other panel) when there's room: the top border carries the
                        # mode name and a live level read-out, and the bottom border
                        # replaces the old section divider.  Under ~3 rows there's no
                        # space for a frame, so fall back to a bare strip + divider.
                        _vis_boxed = spectrum_height_dyn >= 3
                        _vis_h = (spectrum_height_dyn - 1) if _vis_boxed else spectrum_height_dyn
                        _vis_ctx = VisFrameCtx(
                            vis_states, cap_pos=cap_pos, peak_bars=peak_bars, trail_bars=trail_bars,
                            use_color=spectrum_use_color, game_tag=game_tag, features=_audio_features,
                            snapshot=_audio_snapshot,
                        )
                        # btop data_same: static modes reuse cached lines when bars unchanged.
                        if draw_mode in STATIC_VIS_MODES:
                            _cache_key = (
                                draw_mode, game_tag, _vis_h, bars_len,
                                tuple(round(b, 2) for b in smooth_bars),
                            )
                            if _cache_key == _vis_line_cache_key and _vis_line_cache is not None:
                                vis_lines = _vis_line_cache
                            else:
                                vis_lines = render_frame(draw_mode, smooth_bars, _vis_h, bars_len, _vis_ctx)
                                _vis_line_cache = vis_lines
                                _vis_line_cache_key = _cache_key
                        else:
                            vis_lines = render_frame(draw_mode, smooth_bars, _vis_h, bars_len, _vis_ctx)
                        if _vis_boxed:
                            _vis_title = _vis_ctx.label or draw_mode
                            if vis_shuffle:
                                _vis_title = f"{_vis_title} {SYM_SHUFFLE}"
                            _vbox, _ = build_box(
                                vis_lines, vis_lines, maxw_override=bars_len,
                                title=_vis_title, title2=VISUALIZER_TITLE_HINTS,
                            )
                            lines.extend(_vbox)
                        else:
                            lines.extend([prefix + ln for ln in vis_lines])
                    elif _cava.err:
                        _vis_err = format_visualizer_status(_cava.err, label=_cava.last_label, max_width=bars_len)
                        lines.append(prefix + (paint(_vis_err, fg=theme_role("danger", _active_tod_grad), bold=True) if USE_COLOR else _vis_err))
                    elif ok:
                        lines.append(prefix + c256("(no data)", theme_role("label", _active_tod_grad)))
                    else:
                        warmup_since = max(_cava.started_ts, playback_started_ts)
                        if warmup_since and (now - warmup_since) < AUDIO_WARMUP_GRACE:
                            lines.append(prefix)
                        else:
                            lines.append(prefix + c256(format_visualizer_status(label=_cava.last_label, waiting=True, max_width=bars_len), theme_role("label", _active_tod_grad)))
                    if not _vis_boxed:
                        # Pad spectrum zone to its exact reserved height
                        while len(lines) < _spec_row0 + spectrum_height_dyn:
                            lines.append("")
                        # btop ├─ section divider with mode label (bare-strip fallback)
                        _div_label = f" {(_vis_ctx.label or VIS_MODES[vis_idx])} "
                        _div_pad = max(0, bars_len - len(_div_label) - 2)
                        _div_l = _div_pad // 2
                        _div_r = _div_pad - _div_l
                        _chrome = theme_chrome()
                        _divider = _chrome.get("divider", BOX_CHARS["h"])
                        _section_left = _chrome.get("section_left", "├")
                        _section_right = _chrome.get("section_right", "┤")
                        if USE_COLOR and bars_len > len(_div_label) + 4:
                            _div_dim = theme_role("border", _active_tod_grad)
                            _div_mid = theme_role("label_dim", _active_tod_grad)
                            _div_line = (
                                c256(_divider * _div_l, _div_dim)
                                + c256(_section_left, _div_mid)
                                + c256(_div_label, theme_role("accent", _active_tod_grad))
                                + c256(_section_right, _div_mid)
                                + c256(_divider * _div_r, _div_dim)
                            )
                        else:
                            _div_line = c256(_divider * bars_len, theme_role("border", _active_tod_grad))
                        lines.append(prefix + _div_line)
                    # Pinned footer: thin TOD-colored separator + always-visible controls hint
                    if footer_has_separator:
                        _sep_chr = _chrome.get("separator", _divider)
                        _sep_col = theme_role("border", _active_tod_grad)
                        lines.append(c256(_sep_chr * max(1, term_cols - 1), _sep_col) if USE_COLOR else ("-" * max(1, term_cols - 1)))
                    for footer_line in footer_control_lines:
                        if USE_COLOR:
                            lines.append(colorize_hint_keys(
                                footer_line,
                                theme_role("accent", _active_tod_grad),
                                base_fg=theme_role("label_dim", _active_tod_grad),
                                dim=True,
                            ))
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
                    set_mpv_volume(new_vol, fade["new_ipc"])
                    set_mpv_volume(old_vol, fade["old_ipc"])
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
                        set_mpv_volume(vol, transition.get("old_ipc"))
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
                        set_mpv_volume(vol, transition.get("new_ipc"))
                        if p >= 1.0:
                            # finalize: swap current proc to new proc
                            mpv_proc = transition.get("new_proc")
                            if not transition.get("simulate"):
                                # Only advance last_hour when the new proc actually started;
                                # if it failed (mpv_proc is None) leave last_hour unchanged so
                                # the needs_start recovery path retriggers on the next frame.
                                if mpv_proc is not None:
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

                flush_ui_state()

                # Non-blocking key read (dynamic refresh rate). When idle we slow
                # right down; otherwise the frame rate adapts to the *active*
                # visualizer mode (cheap modes run smoother, heavy feedback modes
                # stay capped) — unless the user pinned AC_UI_REFRESH.
                if background_mode or (FOCUS_THROTTLE and not focused):
                    refresh_interval = IDLE_REFRESH
                elif REFRESH_OVERRIDE_SET:
                    refresh_interval = REFRESH_INTERVAL
                else:
                    refresh_interval = vis_frame_interval(VIS_MODES[vis_idx], vis_fps_map)
                fd = sys.stdin.fileno()
                ch = _read_key(fd, timeout=refresh_interval)
                if ch:
                    # Apply user key remapping (keymap.json) before dispatch.
                    if key_aliases:
                        ch = key_aliases.get(ch, ch)
                    if ch == "FOCUS_IN":
                        if FOCUS_THROTTLE:
                            focused = True
                            last_lines = None
                        continue
                    if ch == "FOCUS_OUT":
                        if FOCUS_THROTTLE:
                            focused = False
                        continue
                    # Command palette: ':' or Ctrl+P opens a fuzzy launcher; the
                    # chosen action's primary key is fed back into the dispatch
                    # chain below, so palette and keyboard stay in lockstep.
                    if ch == ":" or ch == "\x10":
                        _sel = run_command_palette(term_cols, term_rows)
                        invalidate_render_cache(clear_screen=True)
                        last_lines = None
                        ch = _sel or ""
                    # Track non-m keypresses to prevent auto-repeat toggling
                    if ch.lower() == "q":
                        handle_exit()
                    if ch.lower() == "n" and transition is None:
                        if free_play_mode and fp_playlist:
                            start_free_play_track(crossfade=True)
                        else:
                            start_for_hour(hour, crossfade=True, fade_dur=1.0)
                            next_candidates_ts = 0.0
                        if current_track:
                            _nm = parse_filename(os.path.basename(current_track))
                            _nlabel = f"{_nm['game']}: {_nm['variant']}" if _nm else os.path.basename(current_track)
                            state_banner = themed_banner(f"{SYM_NOTE} {_nlabel}", "accent", 1.5)
                    if ch == "h":
                        # Simulate hour change: fade out -> chime -> fade in
                        next_hour = (hour + 1) % 24
                        if transition is None:
                            start_hour_transition(next_hour, simulate=True)
                            state_banner = themed_banner(f"{SYM_ROUTE} Simulating {next_hour:02d}:00", "accent_soft", 2.0)
                    if ch == "H":
                        show_history_panel = not show_history_panel
                        if not show_history_panel and panel_focus == "history":
                            panel_focus = None
                        hist_cache_key = None
                        last_lines = None
                        state_banner = themed_banner(f"History: {'shown' if show_history_panel else 'hidden'}", "accent_soft", 1.5)
                    if ch == "U":
                        show_up_next_panel = not show_up_next_panel
                        if not show_up_next_panel and panel_focus == "up_next":
                            panel_focus = None
                        up_cache_key = None
                        last_lines = None
                        state_banner = themed_banner(f"Up Next: {'shown' if show_up_next_panel else 'hidden'}", "accent_soft", 1.5)
                    if ch.lower() == "g":
                        game_idx = (game_idx + 1) % len(games_list)
                        persist_ui_state()
                        start_for_hour(hour, crossfade=False)
                        last_hour = hour  # prevent double-start next frame
                        next_candidates_ts = 0.0
                        state_banner = themed_banner(f"Game: {game_label_from_index(game_idx, games_list, base_allowed_games)}", "accent", 1.5)
                    if ch.lower() == "v":
                        variant_idx = (variant_idx + 1) % len(variants_list)
                        persist_ui_state()
                        start_for_hour(hour, crossfade=False)
                        last_hour = hour  # prevent double-start next frame
                        next_candidates_ts = 0.0
                        state_banner = themed_banner(f"Variant: {variants_list[variant_idx]}", "accent", 1.5)
                    if ch.lower() == "t":
                        vis_idx = (vis_idx + 1) % len(VIS_MODES)
                        persist_ui_state()
                        state_banner = themed_banner(f"Vis: {VIS_MODES[vis_idx]}", "label", 1.2)
                    if ch == "R":
                        vis_idx = random.randrange(len(VIS_MODES))
                        persist_ui_state()
                        state_banner = themed_banner(f"Vis: {VIS_MODES[vis_idx]}", "label", 1.2)
                    if ch == "r":
                        # Frame-rate menu: set fps per visualizer type.
                        _new_fps = run_vis_fps_menu(term_cols, term_rows, vis_fps_map, pinned=REFRESH_OVERRIDE_SET)
                        invalidate_render_cache(clear_screen=True)
                        last_lines = None
                        if _new_fps is not None:
                            vis_fps_map = _new_fps
                            persist_ui_state()
                            state_banner = themed_banner(
                                f"FPS  reactive {vis_fps_map['fast']} / animated {vis_fps_map['normal']} / feedback {vis_fps_map['heavy']}",
                                "accent", 2.2,
                            )
                    if ch == "y":
                        # MilkDrop-style preset shuffle: endlessly drift between visualizers.
                        vis_shuffle = not vis_shuffle
                        if vis_shuffle:
                            _shuffle_last_switch = time.time()
                            _shuffle_next_ts = time.time() + 14.0
                        persist_ui_state()
                        state_banner = themed_banner(
                            f"{SYM_SHUFFLE} Shuffle: cycling visualizer presets" if vis_shuffle else "Shuffle off",
                            "accent" if vis_shuffle else "label", 1.8,
                        )
                    if ch == "L":
                        layout_state = cycle_layout_preset(layout_state)
                        persist_ui_state()
                        info_box_cache_key = None
                        hist_cache_key = None
                        up_cache_key = None
                        help_cache_key = None
                        last_lines = None
                        state_banner = themed_banner(f"Layout: {layout_preset_label(layout_state)}", "accent", 1.8)
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
                        content_frame_key = None
                        layout_plan_cache_key = None
                        rebuild_title_art(term_cols)
                        last_lines = None
                        _theme_name = theme_display_name(_next_theme)
                        _theme_blurb = theme_blurb(_next_theme)
                        _theme_sep = " - " if ASCII_ONLY else " · "
                        _theme_label = f"Theme: {_theme_name}" + (f"{_theme_sep}{_theme_blurb}" if _theme_blurb else "")
                        state_banner = themed_banner(_theme_label, "accent", 1.8, grad=_grad_for_hour(hour))
                    if ch == "l":
                        repeat_current = not repeat_current
                        persist_ui_state()
                        if current_track and mpv_proc and mpv_proc.poll() is None:
                            try:
                                mpv_command(current_ipc, ["set_property", "loop-file", "inf" if repeat_current else "no"])
                            except Exception:
                                pass
                        last_lines = None
                        state_banner = themed_banner(
                            "Playback: Repeat current track" if repeat_current else "Playback: Hour shuffle",
                            "accent" if repeat_current else "accent_soft",
                            1.8,
                        )
                    if ch == "f":
                        if free_play_mode:
                            # Already in free play — exit back to timed mode
                            free_play_mode = False
                            fp_playlist = []
                            fp_idx = 0
                            next_candidates = []
                            next_candidates_key = None
                            start_for_hour(hour, crossfade=True)
                            next_candidates_ts = 0.0
                            state_banner = themed_banner("Timed Mode: Hour shuffle", "accent_soft", 2.0)
                            persist_ui_state()
                            last_lines = None
                        else:
                            # Not in free play — open playlist picker
                            picked = run_playlist_picker()
                            last_lines = None
                            invalidate_render_cache()
                            if picked:
                                _enter_free_play(picked)
                                if free_play_mode:
                                    start_free_play_track(crossfade=True)
                                persist_ui_state()
                    if ch == "F":
                        picked = run_playlist_picker(fp_playlist=fp_playlist if free_play_mode else None)
                        last_lines = None
                        invalidate_render_cache()
                        if picked:
                            _enter_free_play(picked)
                            if free_play_mode:
                                start_free_play_track(crossfade=True)
                            persist_ui_state()
                    if ch == "Q":
                        if free_play_mode and fp_playlist:
                            new_pl, new_idx, play_now = run_queue_manager(fp_playlist, fp_idx, current_track)
                            last_lines = None
                            invalidate_render_cache()
                            fp_playlist = new_pl
                            fp_idx = new_idx
                            next_candidates = []
                            next_candidates_key = None
                            next_candidates_ts = 0.0
                            if play_now and fp_playlist:
                                start_free_play_track(crossfade=True)
                                state_banner = themed_banner(
                                    "Queue updated - playing now" if ASCII_ONLY else "Queue updated — playing now",
                                    "value", 1.8,
                                )
                            else:
                                state_banner = themed_banner("Queue updated", "value_soft", 1.8)
                        else:
                            state_banner = themed_banner("Queue Manager: enable Free Play first", "warning", 2.0)
                    if ch == "a":
                        result = run_add_to_playlist(current_track)
                        last_lines = None
                        invalidate_render_cache()
                        if result:
                            _apl_path, _apl_name, _apl_count = result
                            state_banner = themed_banner(f"Added to '{_apl_name}' ({_apl_count} tracks)", "value", 2.5)
                    if ch == "p":
                        repeat_current = not repeat_current
                        persist_ui_state()
                        if current_track and mpv_proc and mpv_proc.poll() is None:
                            try:
                                mpv_command(current_ipc, ["set_property", "loop-file", "inf" if repeat_current else "no"])
                            except Exception:
                                pass
                        last_lines = None
                        state_banner = themed_banner(
                            f"{SYM_PIN} Pinned: will repeat" if repeat_current else "Unpinned",
                            "accent" if repeat_current else "label",
                            1.8,
                        )
                    if ch == "b" and current_track and transition is None:
                        _nm = parse_filename(os.path.basename(current_track))
                        _lbl = f"{_nm['game']}: {_nm['variant']}" if _nm else os.path.basename(current_track)
                        if free_play_mode:
                            # Free play has no timed hour to fall back to: drop the
                            # current track's upcoming occurrences from the queue and
                            # advance to the next one in the same queue.
                            _cur_abs = os.path.abspath(current_track)
                            fp_playlist[:] = [
                                p for i, p in enumerate(fp_playlist)
                                if not (i >= fp_idx and os.path.abspath(p) == _cur_abs)
                            ]
                            fp_idx = fp_idx % len(fp_playlist) if fp_playlist else 0
                            state_banner = themed_banner(f"{SYM_REMOVE} Removed: {_lbl}", "danger", 2.0)
                            if fp_playlist:
                                start_free_play_track(crossfade=True)
                            next_candidates_key = None
                        else:
                            # Timed mode: ban by absolute path so duplicate filenames
                            # in other hours aren't collaterally banned.
                            banned_tracks.add(os.path.abspath(current_track))
                            state_banner = themed_banner(f"{SYM_REMOVE} Banned: {_lbl}", "danger", 2.0)
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
                                    if pulse_runtime is not None:
                                        pulse_runtime.configure_loopback(loopback_module, private_sink)
                                        pulse_runtime.request_volume(get_mute_volume() if muted else output_vol)
                                        pulse_runtime.request_mute(muted)
                                    _sink_label = truncate_plain(next_sink, 40)
                                    state_banner = themed_banner(f"{SYM_ROUTE} Output: {_sink_label}", "accent", 2.0)
                                else:
                                    state_banner = themed_banner("Output switch failed", "danger", 2.0)
                                last_loopback_ts = 0.0
                                last_loopback_vol = None
                                last_loopback_muted = None
                            else:
                                state_banner = themed_banner("No alternate output sink", "warning", 2.0)
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
                        state_banner = themed_banner(
                            f"{SYM_BG_ON} BACKGROUND MODE ON" if background_mode else f"{SYM_BG_OFF} BACKGROUND MODE OFF",
                            "panel_title",
                            1.5,
                        )
                    if ch.lower() == "m" or ch == " ":
                        # debounce + ignore auto-repeat bursts
                        now_ts = time.time()
                        if last_key == "m" and (now_ts - last_key_ts) < 0.4:
                            continue
                        if now_ts - last_mute_toggle_ts < 1.0:
                            continue
                        last_mute_toggle_ts = now_ts
                        if muted:
                            state_banner = themed_banner(f"{SYM_MUTE} UNMUTED", "good", 1.5)
                            # Unmute: avoid blocking on pactl; sync loopback in main loop
                            if PRIVATE_SINK and loopback_module:
                                set_output_volume(mute_prev_vol if mute_prev_vol is not None else output_vol)
                                new_vol = mute_prev_vol if mute_prev_vol is not None else output_vol
                            else:
                                new_vol = set_output_volume(mute_prev_vol if mute_prev_vol is not None else 50)
                            muted = False
                            last_loopback_ts = 0.0
                            if new_vol is not None:
                                _pb.vol = new_vol
                        else:
                            if (PRIVATE_SINK and loopback_module and output_vol > 0):
                                mute_prev_vol = output_vol
                            elif _pb.vol is not None and _pb.vol > 0:
                                mute_prev_vol = _pb.vol
                            # Mute: silence speakers via loopback, keep signal for visualizer
                            if PRIVATE_SINK and loopback_module:
                                # defer pactl to avoid stutter
                                pass
                            else:
                                set_output_volume(get_mute_volume())
                            muted = True
                            state_banner = themed_banner(f"{SYM_MUTE} MUTED", "danger", 1.5)
                            last_loopback_ts = 0.0
                            _pb.vol = get_mute_volume()
                        persist_ui_state()
                        last_key = "m"
                        last_key_ts = now_ts
                        continue
                    if ch == "?":
                        run_help_overlay(term_cols, term_rows)
                        invalidate_render_cache(clear_screen=True)
                        last_lines = None
                    if ch == "/" and transition is None:
                        # Library fuzzy finder: search the whole catalog and
                        # play the chosen track immediately.
                        _items = [
                            make_item(
                                f"{m['hour']}:00  {m['game']}: {m['variant']}",
                                p,
                                f"{m['game']} {m['variant']} {m['hour']} {m['ext']}",
                            )
                            for (p, m, _nm) in list_all_tracks()
                        ]
                        _pick = run_fuzzy_finder("Find track", _items, term_cols, term_rows)
                        invalidate_render_cache(clear_screen=True)
                        last_lines = None
                        if _pick and start_specific_track(_pick, crossfade=True):
                            _bm = parse_filename(os.path.basename(_pick))
                            _bl = f"{_bm['game']}: {_bm['variant']}" if _bm else os.path.basename(_pick)
                            state_banner = themed_banner(f"{SYM_NOTE} {_bl}", "accent", 1.5)
                    if ch == "`":
                        show_debug = not show_debug
                    # Number-key panel focus (lazygit-style): jump focus straight
                    # to a panel, revealing it if hidden. [0] clears focus.
                    if ch in ("0", "1", "2"):
                        if ch == "0":
                            panel_focus = None
                        else:
                            _target = "history" if ch == "1" else "up_next"
                            if _target == "history":
                                show_history_panel = True
                            else:
                                show_up_next_panel = True
                            panel_focus = _target
                        hist_cache_key = None
                        up_cache_key = None
                        last_lines = None
                        if panel_focus:
                            state_banner = themed_banner(f"Focus: {panel_focus.replace('_', ' ')}", "accent_soft", 1.2)
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
                            _h = tuple(history)[-_hist_show:]
                            hist_sel = min(max(0, len(_h) - 1), hist_sel + 1)
                        elif panel_focus == "up_next":
                            up_sel = min(max(0, len(next_candidates) - 1), up_sel + 1)
                        hist_cache_key = None
                        up_cache_key = None
                        last_lines = None
                    if ch in ("\r", "\n") and panel_focus:
                        if panel_focus == "history":
                            _hlist = list(tuple(history)[-_hist_show:])
                            _sel = max(0, min(hist_sel, len(_hlist) - 1))
                            if _sel < len(_hlist):
                                # History stores full absolute paths — replay the exact
                                # file (works for duplicate names and tracks outside MUSIC_DIR).
                                _track_path = _hlist[_sel]
                                if start_specific_track(_track_path, crossfade=True):
                                    _nm = parse_filename(os.path.basename(_track_path))
                                    _lbl = f"{_nm['game']}: {_nm['variant']}" if _nm else os.path.basename(_track_path)
                                    state_banner = themed_banner(f"{SYM_NOTE} {_lbl}", "accent", 1.5)
                                    next_candidates_ts = 0.0
                        elif panel_focus == "up_next" and next_candidates:
                            _sel = max(0, min(up_sel, len(next_candidates) - 1))
                            _cand = next_candidates[_sel]
                            _qi = getattr(_cand, "queue_index", -1)
                            if free_play_mode and _qi >= 0 and fp_playlist:
                                # Reorder the *real* runtime queue: make the selected
                                # track the next one played (position fp_idx).
                                if 0 <= _qi < len(fp_playlist):
                                    fp_idx = move_queue_item_to_next(fp_playlist, fp_idx, _qi)
                                    up_sel = 0
                                    up_cache_key = None
                                    next_candidates_key = None
                                    last_lines = None
                                    state_banner = themed_banner("Moved to top of queue", "value", 1.5)
                            elif not free_play_mode:
                                # Timed mode has no persistent queue to reorder — play
                                # the selected candidate immediately.
                                if start_specific_track(_cand.path, crossfade=True):
                                    up_sel = 0
                                    up_cache_key = None
                                    last_lines = None
                                    state_banner = themed_banner(f"{SYM_NOTE} {_cand.label}", "accent", 1.5)
                                    next_candidates_ts = 0.0
                    if ch in ("z", "Z") and panel_focus:
                        # Fullscreen ("zoom") the focused panel: re-render it at
                        # full width via its own pure renderer, then view it large.
                        _zw = max(20, term_cols - 8)
                        _zp = _zc = None
                        _ztitle = panel_focus.replace("_", " ").title()
                        if panel_focus == "history":
                            _zp, _zc = _hist_panel.render(
                                list(tuple(history)), _zw, _active_tod_grad, False, 0,
                            )
                        elif panel_focus == "up_next":
                            _zp, _zc = _up_next_panel.render(
                                list(next_candidates), _zw, _active_tod_grad, False, 0,
                                max_shown=len(next_candidates) or 1,
                            )
                        if _zp:
                            run_fullscreen_view(_ztitle, _zp, _zc, term_cols, term_rows)
                            invalidate_render_cache(clear_screen=True)
                            last_lines = None
                    if ch == "x" and panel_focus:
                        # Contextual actions menu for the focused panel item.
                        _opts = []
                        if panel_focus == "history":
                            _opts = [("Play this track", "play"), ("Pin / unpin current", "pin")]
                        elif panel_focus == "up_next":
                            if free_play_mode:
                                _opts = [("Play now", "play"), ("Move to top of queue", "top")]
                            else:
                                _opts = [("Play now", "play")]
                        if _opts:
                            _act = run_menu("Actions", _opts, term_cols, term_rows)
                            invalidate_render_cache(clear_screen=True)
                            last_lines = None
                            if _act == "play":
                                if panel_focus == "history":
                                    _hlist = list(tuple(history)[-_hist_show:])
                                    _sel = max(0, min(hist_sel, len(_hlist) - 1))
                                    if _sel < len(_hlist) and start_specific_track(_hlist[_sel], crossfade=True):
                                        next_candidates_ts = 0.0
                                elif panel_focus == "up_next" and next_candidates:
                                    _sel = max(0, min(up_sel, len(next_candidates) - 1))
                                    if start_specific_track(next_candidates[_sel].path, crossfade=True):
                                        next_candidates_ts = 0.0
                            elif _act == "top" and panel_focus == "up_next" and free_play_mode and next_candidates:
                                _sel = max(0, min(up_sel, len(next_candidates) - 1))
                                _qi = getattr(next_candidates[_sel], "queue_index", -1)
                                if fp_playlist and 0 <= _qi < len(fp_playlist):
                                    fp_idx = move_queue_item_to_next(fp_playlist, fp_idx, _qi)
                                    up_sel = 0; up_cache_key = None; next_candidates_key = None
                                    state_banner = themed_banner("Moved to top of queue", "value", 1.5)
                            elif _act == "pin":
                                repeat_current = not repeat_current
                                persist_ui_state()
                                if current_track and mpv_proc and mpv_proc.poll() is None:
                                    try:
                                        mpv_command(current_ipc, ["set_property", "loop-file", "inf" if repeat_current else "no"])
                                    except Exception:
                                        pass
                                state_banner = themed_banner(
                                    f"{SYM_PIN} Pinned: will repeat" if repeat_current else "Unpinned",
                                    "accent" if repeat_current else "label", 1.8,
                                )
                    # Command plugins: dispatch any key registered by a plugin
                    # (also reachable by selecting the command in the palette).
                    if ch and plugin_keys and ch in plugin_keys:
                        _notes: list[str] = []
                        _pctx = PluginContext(
                            current_track=current_track,
                            term_cols=term_cols, term_rows=term_rows,
                            notify=lambda m: _notes.append(str(m)),
                            play_track=start_specific_track,
                        )
                        plugin_registry.run(ch, _pctx)
                        if _notes:
                            state_banner = themed_banner(_notes[-1], "accent", 2.0)
                            last_lines = None
                    if ch:
                        last_key = ch.lower()
                        last_key_ts = time.time()
    finally:
        try:
            catalog_warm.cancel()
        except Exception:
            pass
        try:
            persist_ui_state(force=True)
        except Exception:
            pass
        try:
            flush_ui_state(force=True)
        except Exception:
            pass
        if pulse_runtime is not None:
            pulse_runtime.stop()
        _cava.stop()
        _pcm.stop()
        stop_mpv()
        try:
            if os.path.exists(_cava.conf_path):
                os.unlink(_cava.conf_path)
        except Exception:
            pass
        teardown_private_sink(private_module, loopback_module)
        enable_autowrap()
        show_cursor()
        reset_terminal_title()
        exit_alt_screen()

if __name__ == "__main__":
    main()

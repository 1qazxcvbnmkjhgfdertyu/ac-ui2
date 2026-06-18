"""Static layout preview renderer and layout-sweep CLI command."""
from __future__ import annotations
import os, time
from collections import deque

import ac_ui.colors as _clrs
from ac_ui.colors import paint, plain_visible_len, strip_ansi, theme_chrome, theme_role
from ac_ui.constants import (
    VIS_MODES, CAVA_BARS, CAVA_MIN_BARS, CAVA_MARGIN, STATS_ENABLED, HISTORY_MAX, UP_NEXT_MAX,
    DEFAULT_LAYOUT_PRESET, FULLSCREEN_LAYOUT_PRESETS,
    NOW_PLAYING_TITLE_HINTS, VISUALIZER_TITLE_HINTS,
)
from ac_ui.term import truncate_plain
from ac_ui.layout import (
    build_box, build_footer_controls, layout_mode_for_size,
    layout_min_spectrum_rows,
    combine_render_columns, stack_render_blocks, build_ultra_compact_summary, box_outer_width,
)
from ac_ui.layout_config import (
    normalize_layout_config, default_layout_config, layout_panels_in_slot, _int_opt, _str_opt,
)
from ac_ui.layout_engine import resolve_panel_max_width, below_panel_inner_width
from ac_ui.visualizer import spectrum_lines
from ac_ui.tracks import playback_mode_label
from ac_ui.panels.now_playing import NowPlayingContext
from ac_ui.panels import now_playing as _np_panel, stats as _stats_panel, history as _hist_panel, up_next as _up_next_panel


def build_layout_preview(term_cols, term_rows, layout_config=None):
    # Minimal, deterministic preview for layout debugging
    hour = 14
    remaining = 30 * 60 + 44
    current_track = "/music/14-GCN-normal.mp3"
    current_track_hour = 14
    output_vol = 75
    muted = False
    repeat_current = False
    history = deque([
        "13-KK-slider.mp3", "13-NH-morning.flac", "14-WW-sunny.mp3", "14-AF-town.flac",
        "14-CF-snow.mp3", "14-GCN-cheery.mp3", "14-NH-winter.flac", "14-GCN-normal.mp3",
    ])
    next_candidates = [
        "14-GCN-cheery.mp3", "14-NH-winter.flac", "14-NH-rainy.flac",
        "14-WW-sunny.mp3", "14-AF-town.flac", "14-CF-snow.mp3",
        "14-GCN-aurora.mp3", "14-NL-rainy.flac", "14-PG-cheery.mp3",
        "14-HHD-island.mp3",
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
    chrome = theme_chrome()

    lines = []
    info = []
    info_plain = []

    tline = f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    lines.append(paint(tline, fg=theme_role("label_dim", _clrs._active_tod_grad), dim=True))

    max_info_rows = term_rows - min_spectrum_rows - footer_rows - 1 - 2
    compact_info = max_info_rows < 10 or term_cols < 70 or ultra_compact

    # Render Now Playing at the width it will actually be boxed at (mirrors the
    # live loop) so meters/art never get clipped by a later narrower rebuild.
    _np_preset = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)["preset"]
    _np_will_sidebar = (not ultra_compact) and (not compact_info) and (not tiny_term)
    if _np_will_sidebar:
        _np_target_w = term_cols - 2 - 3 - box_outer_width(resolve_panel_max_width(term_cols, _np_preset)) - 4
    else:
        _np_target_w = term_cols - 2 - 4
    _np_target_w = max(20, min(info_max_width, _np_target_w))

    if ultra_compact:
        summary = truncate_plain(
            build_ultra_compact_summary("ALL", "ALL", VIS_MODES[vis_idx], remaining, output_vol, muted, showing_chime, chime_kind, repeat_current=repeat_current),
            max(10, term_cols - 2),
        )
        lines.append(paint(summary, fg=theme_role("label_dim", _clrs._active_tod_grad), dim=True))
    else:
        np_ctx = NowPlayingContext(
            compact=compact_info,
            max_width=_np_target_w,
            current_track=current_track,
            current_track_hour=current_track_hour,
            hour=hour,
            tpos=16.0 if current_track else None,
            dur=139.0 if current_track else None,
            showing_chime=showing_chime,
            chime_kind=chime_kind,
            repeat_current=repeat_current,
            track_pick_reason=playback_mode_label(repeat_current),
            background_mode=False,
            muted=muted,
            game_label="ALL",
            variant="ALL",
            vis_mode=VIS_MODES[vis_idx],
            display_vol=output_vol,
            vol_flash_str="",
            remaining=remaining,
            pulse_bright=True,
            title_art=(["AC-UI"] if not compact_info else []),
            title_art_colored=False,
            tod_grad=_clrs._active_tod_grad,
        )
        info_plain, info = _np_panel.render(np_ctx)

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
            info_box, info_w = build_box(
                info_plain, info,
                maxw_override=_np_target_w,
                title="Now Playing",
                title2=NOW_PLAYING_TITLE_HINTS,
            )

    layout_state = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)
    layout_preset = layout_state["preset"]
    _fullscreen_layout = layout_preset in FULLSCREEN_LAYOUT_PRESETS

    stats_box = None
    stats_w = 0
    if (not ultra_compact) and (not _fullscreen_layout) and STATS_ENABLED and stats_data is not None:
        # Stretch Stats to the full content width (btop-style).
        stats_inner_width = max(28, term_cols - 6)
        stats_plain, stats_color = _stats_panel.render(stats_data, session_listen, stats_inner_width, hour, _clrs._active_tod_grad)
        stats_box, stats_w = build_box(stats_plain, stats_color, maxw_override=stats_inner_width, title="Stats")

    max_content_end = term_rows - min_spectrum_rows - footer_rows - 1
    show_history = (not tiny_term) and (not ultra_compact) and (not compact_info) and (not _fullscreen_layout)
    show_up_next = (not (tiny_term or small_term)) and (not ultra_compact) and (not compact_info) and (not _fullscreen_layout)
    # Single source of truth — same widths the live compositor uses.
    panel_max_width = resolve_panel_max_width(term_cols, layout_preset)
    _below_names = layout_panels_in_slot(layout_state, "below")
    _below_fill_w = below_panel_inner_width(term_cols, len(_below_names)) if _below_names else panel_max_width
    _hist_target_w = _below_fill_w if "history" in _below_names else panel_max_width
    _up_target_w = _below_fill_w if "up_next" in _below_names else panel_max_width

    hist_box = None
    hist_w = 0
    up_box = None
    up_w = 0
    # Fixed sidebar depth (matches live loop) — the spectrum absorbs spare rows.
    _up_show = UP_NEXT_MAX
    _hist_show = HISTORY_MAX

    if show_history:
        hist_list = list(history)[-_hist_show:]
        hist_lines, hist_color = _hist_panel.render(hist_list, _hist_target_w, _clrs._active_tod_grad)
        hist_box, hist_w = build_box(hist_lines, hist_color, maxw_override=_hist_target_w, title="History")

    if show_up_next:
        up_plain, up_color = _up_next_panel.render(list(next_candidates), _up_target_w, _clrs._active_tod_grad, max_shown=_up_show)
        _up_count = f"{min(_up_show, len(next_candidates))}/{len(next_candidates)}"
        up_box, up_w = build_box(up_plain, up_color, maxw_override=_up_target_w, title="Up Next", title2=_up_count)

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
            max_info_inner = term_cols - 2 - 3 - sidebar_outer - 4   # 2-col right margin
            if max_info_inner >= min_info_sidebar_width:
                # Fill the row width to the left of the sidebar (minus the margin).
                info_target_width = max_info_inner
                if info_target_width != info_w:
                    info_box_fit, info_w_fit = build_box(
                        info_plain, info,
                        maxw_override=info_target_width,
                        title="Now Playing",
                        title2=NOW_PLAYING_TITLE_HINTS,
                    )
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
            # No sidebar — stretch the info box across the full width.
            _fw = max(info_w, term_cols - 2 - 4)   # 2-col right margin
            info_box_fit, info_w_fit = build_box(
                info_plain, info,
                maxw_override=_fw,
                title="Now Playing",
                title2=NOW_PLAYING_TITLE_HINTS,
            )
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
    # Match the live loop: the spectrum expands to fill all leftover rows (after
    # the section divider + footer), rather than being capped at the base height.
    available_rows = max(0, term_rows - rows_used - 1 - footer_rows)
    spectrum_height_dyn = available_rows
    bars_len = max(10, term_cols - len(prefix) - CAVA_MARGIN)
    mock_count = max(1, CAVA_BARS) if CAVA_BARS > 0 else max(CAVA_MIN_BARS, bars_len)
    mock_bars = [((i % 7) + 1) / 8 for i in range(mock_count)]
    if spectrum_height_dyn > 0:
        bars = mock_bars[:bars_len]
        # Frame the visualizer in its own titled box when there's room (mirrors
        # the live loop); otherwise a bare strip + section divider.
        _vis_boxed = spectrum_height_dyn >= 3
        _vis_h = (spectrum_height_dyn - 1) if _vis_boxed else spectrum_height_dyn
        vis = spectrum_lines(bars, height=_vis_h, use_color=False, mode="bars")
        if _vis_boxed:
            vbox, _ = build_box(
                vis, vis,
                maxw_override=bars_len,
                title=VIS_MODES[vis_idx],
                title2=VISUALIZER_TITLE_HINTS,
            )
            lines.extend(vbox)
        else:
            lines.extend([prefix + ln for ln in vis])
            _div_label = f" {VIS_MODES[vis_idx]} "
            _div_pad = max(0, bars_len - plain_visible_len(_div_label) - 2)
            _div_l = _div_pad // 2
            _div_r = _div_pad - _div_l
            lines.append(
                prefix
                + (chrome.get("divider", "-") * _div_l)
                + chrome.get("section_left", "<")
                + _div_label
                + chrome.get("section_right", ">")
                + (chrome.get("divider", "-") * _div_r)
            )
    if footer_sep and len(lines) < term_rows:
        lines.append(chrome.get("separator", "-") * max(1, term_cols - 1))
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

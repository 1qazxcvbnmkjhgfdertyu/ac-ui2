"""Now Playing panel renderer — pure function, no side effects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ac_ui.colors import (
    USE_COLOR, c, c256, humanize_seconds, paint, strip_ansi, theme_role,
)
from ac_ui.constants import (
    ASCII_ONLY, SYM_MUTED_MARK, SYM_NOTE, SYM_PLAY, SYM_PULSE_OFF, SYM_PULSE_ON,
)
from ac_ui.layout import format_filter_summary
from ac_ui.meters import meter_bar
from ac_ui.art import game_mosaic
from ac_ui.term import truncate_plain, truncate_ansi_visible
from ac_ui.tracks import fmt_mmss, parse_filename

# Below this inner width there isn't room for a side art block.
ART_MIN_WIDTH = 60


@dataclass
class NowPlayingContext:
    """All data needed to render the Now Playing panel."""
    compact: bool
    max_width: int
    # track/playback
    current_track: str | None
    current_track_hour: int | None
    hour: int
    tpos: float | None
    dur: float | None
    showing_chime: bool
    chime_kind: str | None
    repeat_current: bool
    track_pick_reason: str | None
    background_mode: bool
    muted: bool
    # filter / vis
    game_label: str
    variant: str
    vis_mode: str
    # volume
    display_vol: int | None
    vol_flash_str: str
    # timing
    remaining: int
    pulse_bright: bool
    # title art
    title_art: list[str] = field(default_factory=list)
    title_art_colored: bool = False
    # gradient
    tod_grad: Any = None  # list from colors._active_tod_grad; falls back to _active_tod_grad if None


def render(ctx: NowPlayingContext) -> tuple[list[str], list[str]]:
    """Return (plain_lines, color_lines) for the Now Playing panel.

    Both lists have the same length. Color lines contain ANSI escapes; plain
    lines are stripped. The caller is responsible for boxing with build_box().
    """
    plain: list[str] = []
    color: list[str] = []
    w = ctx.max_width
    if ctx.tod_grad is None:
        import ac_ui.colors as _clrs
        grad = _clrs._active_tod_grad
    else:
        grad = ctx.tod_grad

    # When wide, reserve a left column for a themed "album art" mosaic and build
    # the body into the remaining width; the mosaic is composed back on at the end.
    _orig_w = w
    _side_art = (
        (not ctx.compact) and bool(ctx.current_track) and (not ctx.showing_chime)
        and w >= ART_MIN_WIDTH
    )
    _art_w = 0
    if _side_art:
        _art_w = min(18, max(10, _orig_w // 4))
        w = _orig_w - _art_w - 2   # 2-col gap between art and body

    def _add(text: str, code: str = "2") -> None:
        t = truncate_plain(text, w)
        plain.append(t)
        color.append(c(t, code))

    def _push(text: str, colored: str) -> None:
        plain.append(truncate_plain(text, w))
        color.append(colored)

    danger_col = theme_role("danger", grad)
    value_soft_col = theme_role("value_soft", grad)
    label_dim_col = theme_role("label_dim", grad)
    accent_col = theme_role("accent", grad)
    accent_soft_col = theme_role("accent_soft", grad)
    title_col = theme_role("title", grad)
    pulse_col = theme_role("pulse", grad)
    good_col = theme_role("good", grad)

    # Title art (full mode only) — skipped when the side mosaic is in play.
    if (not ctx.compact) and ctx.title_art and not _side_art:
        if ctx.title_art_colored:
            color.extend(ctx.title_art)
            plain.extend([strip_ansi(line) for line in ctx.title_art])
        else:
            color.extend([c256(line, accent_soft_col) for line in ctx.title_art])
            plain.extend(list(ctx.title_art))

    flt_sum = format_filter_summary(ctx.game_label, ctx.variant)

    if ctx.compact:
        # ── Compact layout ────────────────────────────────────────────────────
        dense_sep = " - " if ASCII_ONLY else " · "
        dense_plain = f"{flt_sum}{dense_sep}{ctx.vis_mode}"
        if USE_COLOR:
            pulse = paint(SYM_PULSE_ON, fg=pulse_col, bold=True) if (ctx.pulse_bright and not ctx.muted) else paint(SYM_PULSE_OFF, fg=pulse_col, dim=True)
            muted_c = f"  {paint(SYM_MUTED_MARK, fg=danger_col, bold=True)}" if ctx.muted else ""
            plain.append(truncate_plain(dense_plain, w))
            color.append(
                f"{paint(flt_sum, fg=accent_soft_col)}"
                f"{paint(dense_sep, fg=label_dim_col, dim=True)}"
                f"{paint(ctx.vis_mode, fg=label_dim_col, dim=True)}"
                f"  {pulse}{muted_c}"
            )
        else:
            _add(dense_plain, "2")

        if ctx.showing_chime:
            _t = truncate_plain(f"{SYM_NOTE} ({ctx.chime_kind or 'hour chime'})", w)
            plain.append(_t)
            color.append(c256(_t, accent_col))
        elif ctx.current_track:
            bn = os.path.basename(ctx.current_track)
            meta = parse_filename(bn)
            _t = truncate_plain(f"{meta['game']}: {meta['variant']}" if meta else bn, w)
            plain.append(_t)
            color.append(c256(_t, title_col))
        else:
            _add(f"(none for {ctx.hour:02d}h)")

        uvalue = f"{ctx.remaining // 60:02d}:{ctx.remaining % 60:02d}"
        _t = truncate_plain(f"Until: {uvalue}", w)
        plain.append(_t)
        color.append(c256(_t, theme_role("label", grad)))

    else:
        # ── Full layout ───────────────────────────────────────────────────────

        # Line 1: track name / chime
        if ctx.showing_chime:
            label = ctx.chime_kind or "hour chime"
            if USE_COLOR:
                _push(f"{SYM_NOTE} ({label})", f"{paint(SYM_NOTE, fg=accent_col)} {paint(f'({label})', fg=label_dim_col, dim=True)}")
            else:
                _add(f"{SYM_NOTE} ({label})", "36")
        elif ctx.current_track:
            display_hour = ctx.current_track_hour if ctx.current_track_hour is not None else ctx.hour
            track_name = os.path.basename(ctx.current_track)
            meta = parse_filename(track_name)
            display_name = f"{meta['game']}: {meta['variant']}" if meta else track_name
            dur_tag = f"  {humanize_seconds(ctx.dur)}" if ctx.dur else ""
            if USE_COLOR:
                if ctx.muted:
                    sym_glyph = paint(SYM_PLAY, fg=danger_col, dim=True)
                elif ctx.background_mode:
                    sym_glyph = paint(SYM_PLAY, fg=label_dim_col, dim=True)
                else:
                    sym_glyph = paint(SYM_PLAY, fg=title_col, bold=True)
                pin_str = f" {paint('[pinned]', fg=accent_soft_col)}" if ctx.repeat_current else ""
                color.append(
                    f"{sym_glyph} "
                    f"{paint(display_name, fg=title_col, bold=True)}{pin_str}"
                    f"{paint(dur_tag, fg=theme_role('label', grad), dim=True)}"
                )
                plain.append(truncate_plain(f"{SYM_PLAY} {display_name}{dur_tag}", w))
            else:
                pin_str = " [pinned]" if ctx.repeat_current else ""
                _add(f"{SYM_PLAY} {display_name}{pin_str}{dur_tag}", "36")

            # Line 2: hour + position + progress bar
            t_pos_s = ctx.tpos or 0.0
            t_dur_s = ctx.dur or 0.0
            # Let the progress meter grow to fill a wide box (btop full-width meters).
            bar_w = max(8, min(w - 26, 96))
            pct = (t_pos_s / max(1.0, t_dur_s) * 100) if t_dur_s > 0 else 0
            if USE_COLOR:
                pb_bar = meter_bar(pct, bar_w, grad)
            else:
                filled = int(pct / 100 * bar_w)
                pb_bar = "[" + "=" * filled + "-" * (bar_w - filled) + "]"
            pos_plain = f"  {display_hour:02d}h  {fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}"
            if USE_COLOR:
                plain.append(truncate_plain(pos_plain, w))
                color.append(
                    f"  {paint(f'{display_hour:02d}h', fg=accent_col)}"
                    f"  {paint(f'{fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}', fg=label_dim_col, dim=True)}"
                    f"  {pb_bar}"
                )
            else:
                _add(f"{pos_plain}  {pb_bar}", "2")
        else:
            _add(f"  (no track for {ctx.hour:02d}h)", "2")

        # Line 3: filter + vis + pulse + transient volume delta
        flash_plain = strip_ansi(ctx.vol_flash_str) if ctx.vol_flash_str else ""
        if USE_COLOR:
            pulse_dot = paint(SYM_PULSE_ON, fg=pulse_col, bold=True) if (ctx.pulse_bright and not ctx.muted) else paint(SYM_PULSE_OFF, fg=pulse_col, dim=True)
            muted_tag = f"  {paint(f'{SYM_MUTED_MARK} MUTED', fg=danger_col, bold=True)}" if ctx.muted else ""
            meta_plain = f"  {flt_sum}  {ctx.vis_mode}{flash_plain}"
            plain.append(truncate_plain(meta_plain, w))
            color.append(
                f"  {paint(flt_sum, fg=accent_soft_col, dim=True)}"
                f"  {paint(ctx.vis_mode, fg=label_dim_col, dim=True)}"
                f"  {pulse_dot}{muted_tag}{ctx.vol_flash_str}"
            )
        else:
            _add(f"  {flt_sum}  {ctx.vis_mode}{flash_plain}", "2")

        # Line 4: countdown to next hour
        uvalue = f"{ctx.remaining // 60:02d}:{ctx.remaining % 60:02d}"
        if USE_COLOR:
            hr_pct = min(100, int(ctx.remaining / 3600 * 100))
            cbar_w = max(4, min(w - 18, 96))
            cbar = meter_bar(hr_pct, cbar_w, grad)
            plain.append(truncate_plain(f"  Until: {uvalue}", w))
            color.append(f"  {paint('Until:', fg=label_dim_col, dim=True)} {paint(uvalue, fg=value_soft_col)}  {cbar}")
        else:
            _add(f"  Until: {uvalue}", "95")

        # Line 5: pick reason
        if ctx.track_pick_reason and not ctx.showing_chime:
            reason_plain = f"  next via: {ctx.track_pick_reason}"
            if USE_COLOR:
                plain.append(truncate_plain(reason_plain, w))
                color.append(f"  {paint('next via:', fg=label_dim_col, dim=True)} {paint(ctx.track_pick_reason, fg=good_col)}")
            else:
                _add(f"  next via: {ctx.track_pick_reason}", "2")

    # Compose the themed album-art mosaic onto the left of the body.
    if _side_art and color:
        seed = f"{ctx.game_label}:{ctx.variant}"
        art_plain, art_color = game_mosaic(seed, _art_w, len(color), grad=grad, use_color=USE_COLOR)
        gap = "  "
        merged_plain: list[str] = []
        merged_color: list[str] = []
        for i in range(len(color)):
            merged_plain.append(art_plain[i] + gap + truncate_plain(plain[i], w))
            merged_color.append(art_color[i] + gap + truncate_ansi_visible(color[i], w))
        plain, color = merged_plain, merged_color

    return plain, color

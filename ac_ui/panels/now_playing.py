"""Now Playing panel renderer — pure function, no side effects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ac_ui.colors import (
    USE_COLOR, c, c256, gradient_at, solid_bar, humanize_seconds, strip_ansi,
)
from ac_ui.constants import NO_MOTION, SYM_PLAY
from ac_ui.layout import format_filter_summary
from ac_ui.term import truncate_plain
from ac_ui.tracks import fmt_mmss, parse_filename


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

    def _add(text: str, code: str = "2") -> None:
        t = truncate_plain(text, w)
        plain.append(t)
        color.append(c(t, code))

    # Title art (full mode only)
    if (not ctx.compact) and ctx.title_art:
        if ctx.title_art_colored:
            color.extend(ctx.title_art)
            plain.extend([strip_ansi(line) for line in ctx.title_art])
        else:
            art_col = gradient_at(grad, 70)
            color.extend([c256(line, art_col) for line in ctx.title_art])
            plain.extend(list(ctx.title_art))

    flt_sum = format_filter_summary(ctx.game_label, ctx.variant)

    if ctx.compact:
        # ── Compact layout ────────────────────────────────────────────────────
        dense_plain = f"{flt_sum} · {ctx.vis_mode}"
        if USE_COLOR:
            flt_col = gradient_at(grad, 65)
            pd_col = gradient_at(grad, 90)
            pulse = (
                f"\x1b[1;38;5;{pd_col}m●\x1b[0m" if (ctx.pulse_bright and not ctx.muted)
                else f"\x1b[2;38;5;{pd_col}m·\x1b[0m"
            )
            muted_c = f"  \x1b[1;31m◆\x1b[0m" if ctx.muted else ""
            plain.append(truncate_plain(dense_plain, w))
            color.append(
                f"\x1b[38;5;{flt_col}m{flt_sum}\x1b[0m"
                f"\x1b[2m · \x1b[0m"
                f"\x1b[2;36m{ctx.vis_mode}\x1b[0m"
                f"  {pulse}{muted_c}"
            )
        else:
            _add(dense_plain, "2")

        if ctx.showing_chime:
            _add(f"♪ ({ctx.chime_kind or 'hour chime'})", "36")
        elif ctx.current_track:
            bn = os.path.basename(ctx.current_track)
            meta = parse_filename(bn)
            _add(f"{meta['game']}: {meta['variant']}" if meta else bn, "97")
        else:
            _add(f"(none for {ctx.hour:02d}h)", "2")

        uvalue = f"{ctx.remaining // 60:02d}:{ctx.remaining % 60:02d}"
        _add(f"Until: {uvalue}", "95")

    else:
        # ── Full layout ───────────────────────────────────────────────────────

        # Line 1: track name / chime
        if ctx.showing_chime:
            label = ctx.chime_kind or "hour chime"
            if USE_COLOR:
                hr_col = gradient_at(grad, 80)
                plain.append(truncate_plain(f"♪ ({label})", w))
                color.append(f"\x1b[38;5;{hr_col}m♪\x1b[0m \x1b[2;36m({label})\x1b[0m")
            else:
                _add(f"♪ ({label})", "36")
        elif ctx.current_track:
            display_hour = ctx.current_track_hour if ctx.current_track_hour is not None else ctx.hour
            track_name = os.path.basename(ctx.current_track)
            meta = parse_filename(track_name)
            display_name = f"{meta['game']}: {meta['variant']}" if meta else track_name
            dur_tag = f"  {humanize_seconds(ctx.dur)}" if ctx.dur else ""
            if USE_COLOR:
                sym_hi = gradient_at(grad, 90)
                sym_color = (
                    "\x1b[2;31m" if ctx.muted
                    else ("\x1b[2;37m" if ctx.background_mode else f"\x1b[1;38;5;{sym_hi}m")
                )
                pin_str = f" \x1b[33m[pinned]\x1b[0m" if ctx.repeat_current else ""
                dur_col = gradient_at(grad, 50)
                plain.append(truncate_plain(f"{SYM_PLAY} {display_name}{dur_tag}", w))
                color.append(
                    f"{sym_color}{SYM_PLAY}\x1b[0m "
                    f"\x1b[1;97m{display_name}\x1b[0m{pin_str}"
                    f"\x1b[2;38;5;{dur_col}m{dur_tag}\x1b[0m"
                )
            else:
                pin_str = " [pinned]" if ctx.repeat_current else ""
                _add(f"{SYM_PLAY} {display_name}{pin_str}{dur_tag}", "36")

            # Line 2: hour + position + progress bar
            t_pos_s = ctx.tpos or 0.0
            t_dur_s = ctx.dur or 0.0
            bar_w = max(8, min(20, w - 26))
            pct = (t_pos_s / max(1.0, t_dur_s) * 100) if t_dur_s > 0 else 0
            if USE_COLOR:
                pb_bar = solid_bar(pct, bar_w, gradient_at(grad, 65))
            else:
                filled = int(pct / 100 * bar_w)
                pb_bar = "[" + "=" * filled + "─" * (bar_w - filled) + "]"
            pos_plain = f"  {display_hour:02d}h  {fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}"
            if USE_COLOR:
                h_col = gradient_at(grad, 70)
                plain.append(truncate_plain(pos_plain, w))
                color.append(
                    f"  \x1b[38;5;{h_col}m{display_hour:02d}h\x1b[0m"
                    f"  \x1b[2;36m{fmt_mmss(t_pos_s)} / {fmt_mmss(t_dur_s)}\x1b[0m"
                    f"  {pb_bar}"
                )
            else:
                _add(f"{pos_plain}  {pb_bar}", "2")
        else:
            _add(f"  (no track for {ctx.hour:02d}h)", "2")

        # Line 3: filter + vis + pulse + vol
        if USE_COLOR:
            flt_col = gradient_at(grad, 60)
            pd_col = gradient_at(grad, 90)
            pulse_dot = (
                f"\x1b[1;38;5;{pd_col}m●\x1b[0m" if (ctx.pulse_bright and not ctx.muted)
                else f"\x1b[2;38;5;{pd_col}m·\x1b[0m"
            )
            muted_tag = f"  \x1b[1;31m◆ MUTED\x1b[0m" if ctx.muted else ""
            vol_inline = (
                f"  \x1b[2;36mVol\x1b[0m {int(ctx.display_vol):3d}%{ctx.vol_flash_str}"
                if ctx.display_vol is not None else ""
            )
            meta_plain = f"  {flt_sum}  {ctx.vis_mode}"
            plain.append(truncate_plain(meta_plain, w))
            color.append(
                f"  \x1b[2;38;5;{flt_col}m{flt_sum}\x1b[0m"
                f"  \x1b[2;36m{ctx.vis_mode}\x1b[0m"
                f"  {pulse_dot}{muted_tag}{vol_inline}"
            )
        else:
            vol_inline = f"  Vol {int(ctx.display_vol)}%" if ctx.display_vol is not None else ""
            _add(f"  {flt_sum}  {ctx.vis_mode}{vol_inline}", "2")

        # Line 4: countdown to next hour
        uvalue = f"{ctx.remaining // 60:02d}:{ctx.remaining % 60:02d}"
        if USE_COLOR:
            hr_pct = min(100, int(ctx.remaining / 3600 * 100))
            cbar_w = max(4, min(20, w - 18))
            cbar = solid_bar(hr_pct, cbar_w, gradient_at(grad, 50))
            uc = gradient_at(grad, 55)
            plain.append(truncate_plain(f"  Until: {uvalue}", w))
            color.append(f"  \x1b[2;36mUntil:\x1b[0m \x1b[38;5;{uc}m{uvalue}\x1b[0m  {cbar}")
        else:
            _add(f"  Until: {uvalue}", "95")

        # Line 5: pick reason
        if ctx.track_pick_reason and not ctx.showing_chime:
            reason_plain = f"  next via: {ctx.track_pick_reason}"
            if USE_COLOR:
                plain.append(truncate_plain(reason_plain, w))
                color.append(f"  \x1b[2mnext via: {ctx.track_pick_reason}\x1b[0m")
            else:
                _add(f"  next via: {ctx.track_pick_reason}", "2")

    return plain, color

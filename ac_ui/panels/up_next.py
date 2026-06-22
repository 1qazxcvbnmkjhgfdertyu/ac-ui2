"""Up Next panel renderer — pure function, no side effects."""
from __future__ import annotations

import os

from ac_ui.colors import USE_COLOR, c256, gradient_at, paint, plain_visible_len, superscript_num, theme_gradient_stops, theme_role
from ac_ui.constants import SYM_ELLIPSIS, UP_NEXT_MAX
from ac_ui.meters import meter_bar
from ac_ui.term import truncate_plain
from ac_ui.tracks import parse_filename

_WEIGHT_METER_W = 4   # cells for the per-row weight meter (shown when weight > 1)


def _fmt_candidate(item) -> str:
    """Display label for a candidate — a QueueCandidate, a path, or a basename."""
    label = getattr(item, "label", None)
    if label is not None:
        return label
    name = os.path.basename(str(item))
    meta = parse_filename(name)
    if meta:
        return f"{meta['game']}: {meta['variant']}"
    return os.path.splitext(name)[0] if "." in name else name


def render(
    candidates: list[str],
    max_width: int,
    tod_grad: list,
    focused: bool = False,
    sel_idx: int = 0,
    max_shown: int = UP_NEXT_MAX,
) -> tuple[list[str], list[str]]:
    """Return (plain_lines, color_lines) for the Up Next panel.

    Args:
        candidates: QueueCandidate objects (or path/basename strings) in order.
        max_width:  Maximum line width in visible characters.
        tod_grad:   Time-of-day gradient (from colors._active_tod_grad).
        focused:    Whether the panel has keyboard focus.
        sel_idx:    Index of the selected entry (0-based within shown list).
        max_shown:  Maximum number of candidates to show (default UP_NEXT_MAX).

    The panel name and "shown/total" count live in the box border (btop-style);
    only the numbered queue entries are emitted here.
    """
    if not candidates:
        plain = [truncate_plain("No upcoming tracks", max_width)]
        if USE_COLOR:
            color = [paint(plain[0], fg=theme_role("label_dim", tod_grad), dim=True)]
        else:
            color = list(plain)
        return plain, color

    cand_objs = list(candidates[:max_shown])
    shown = [_fmt_candidate(s) for s in cand_objs]
    weights = [int(getattr(s, "weight", 1)) for s in cand_objs]
    n_shown = len(shown)
    if len(candidates) > max_shown:
        shown.append(f"{SYM_ELLIPSIS} +{len(candidates) - max_shown} more")
        weights.append(1)

    plain = [truncate_plain(s, max_width) for s in shown]

    if USE_COLOR:
        num_col = theme_role("panel_subtitle", tod_grad)
        focus_bg = theme_role("focus_bg", tod_grad)
        focus_fg = theme_role("focus_fg", tod_grad)
        entry_grad = theme_gradient_stops("accent", "value", "label", grad=tod_grad, cache_name="up_next")
        overflow_col = theme_role("label_dim", tod_grad)
        color = []
        for i, label in enumerate(shown):
            num = superscript_num(i + 1)
            is_overflow = i >= n_shown
            # Heavier-weighted free-play tracks get a small trailing weight meter.
            show_meter = (weights[i] > 1) and (not is_overflow) and (max_width > _WEIGHT_METER_W + 8)
            reserve = (_WEIGHT_METER_W + 1) if show_meter else 0
            lbl = truncate_plain(label, max(1, max_width - 2 - reserve))
            if focused and i == sel_idx:
                body = paint(f"{num} {lbl}", fg=focus_fg, bg=focus_bg, bold=True)
            else:
                entry_col = overflow_col if is_overflow else gradient_at(entry_grad, int((i / max(1, n_shown - 1)) * 100))
                body = paint(f"{num} ", fg=num_col, dim=True) + c256(lbl, entry_col)
            if show_meter:
                vis = 2 + plain_visible_len(lbl)
                pad = " " * max(1, max_width - vis - _WEIGHT_METER_W)
                body += pad + meter_bar(weights[i] / 5 * 100, _WEIGHT_METER_W, use_color=True)
            color.append(body)
    else:
        color = list(plain)

    return plain, color

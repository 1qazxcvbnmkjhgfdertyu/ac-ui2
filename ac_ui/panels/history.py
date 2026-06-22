"""History panel renderer — pure function, no side effects."""
from __future__ import annotations

import os

from ac_ui.colors import USE_COLOR, c256, gradient_at, paint, theme_gradient_stops, theme_role
from ac_ui.term import truncate_plain
from ac_ui.tracks import parse_filename


def _fmt_hist(entry: str) -> str:
    """History entries are full paths; derive a display label from the basename."""
    name = os.path.basename(str(entry))
    meta = parse_filename(name)
    if meta:
        return f"{meta['game']}: {meta['variant']}"
    return os.path.splitext(name)[0] if "." in name else name


def render(
    history: list[str],
    max_width: int,
    tod_grad: list,
    focused: bool = False,
    sel_idx: int = 0,
) -> tuple[list[str], list[str]]:
    """Return (plain_lines, color_lines) for the History panel.

    Args:
        history:   Track paths, oldest first.
        max_width: Maximum line width in visible characters.
        tod_grad:  Time-of-day gradient (from colors._active_tod_grad).
        focused:   Whether the panel has keyboard focus.
        sel_idx:   Index of the selected entry (0-based within history).

    The panel name lives in the box border (btop-style), so no internal title
    line is emitted here — only the entries themselves.
    """
    if history:
        entries = [_fmt_hist(s) for s in history]
    else:
        entries = ["No history yet"]

    plain = [truncate_plain(s, max_width) for s in entries]

    if USE_COLOR:
        focus_bg = theme_role("focus_bg", tod_grad)
        focus_fg = theme_role("focus_fg", tod_grad)
        age_grad = theme_gradient_stops("label_dim", "accent_soft", "title", grad=tod_grad, cache_name="history")
        dim_col = theme_role("label_dim", tod_grad)
        color = []
        n = len(history)
        for i, line in enumerate(plain):
            if focused and i == sel_idx:
                color.append(paint(line, fg=focus_fg, bg=focus_bg, bold=True))
            elif history:
                shade = gradient_at(age_grad, int((i / max(1, n - 1)) * 100))
                color.append(c256(line, shade))
            else:
                color.append(paint(line, fg=dim_col, dim=True))
    else:
        color = list(plain)

    return plain, color

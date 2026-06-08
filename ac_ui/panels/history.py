"""History panel renderer — pure function, no side effects."""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c, c256, gradient_at
from ac_ui.term import truncate_plain
from ac_ui.tracks import parse_filename


def _fmt_hist(name: str) -> str:
    meta = parse_filename(name)
    if meta:
        return f"{meta['game']}: {meta['variant']}"
    return name


def render(
    history: list[str],
    max_width: int,
    tod_grad: list,
    focused: bool = False,
    sel_idx: int = 0,
) -> tuple[list[str], list[str]]:
    """Return (plain_lines, color_lines) for the History panel.

    Args:
        history:   Track basenames, oldest first.
        max_width: Maximum line width in visible characters.
        tod_grad:  Time-of-day gradient (from colors._active_tod_grad).
        focused:   Whether the panel has keyboard focus.
        sel_idx:   Index of the selected entry (0-based within history).
    """
    title = "Recently played"
    title_trunc = truncate_plain(title, max_width)

    if history:
        entries = [_fmt_hist(s) for s in history]
    else:
        entries = ["(none yet)"]

    plain = [truncate_plain(s, max_width) for s in [title_trunc] + entries]

    if USE_COLOR and history:
        n = len(history)
        hi_col = gradient_at(tod_grad, 70)
        color: list[str] = [c256(plain[0], hi_col)]
        for i, line in enumerate(plain[1:]):
            if focused and i == sel_idx:
                color.append(f"\x1b[7m{line}\x1b[0m")
            else:
                age_frac = (n - 1 - i) / max(1, n - 1)
                shade = gradient_at(tod_grad, int(35 + (1 - age_frac) * 35))
                color.append(c256(line, shade))
    else:
        color = [c(plain[0], "36")] + [
            (f"\x1b[7m{s}\x1b[0m" if (focused and i == sel_idx) else c(s, "2"))
            for i, s in enumerate(plain[1:])
        ]

    return plain, color

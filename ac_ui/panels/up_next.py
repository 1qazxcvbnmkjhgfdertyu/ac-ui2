"""Up Next panel renderer — pure function, no side effects."""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c, c256, gradient_at, superscript_num
from ac_ui.constants import SYM_ELLIPSIS, UP_NEXT_MAX
from ac_ui.term import truncate_plain
from ac_ui.tracks import parse_filename


def _fmt_candidate(name: str) -> str:
    meta = parse_filename(name)
    if meta:
        return f"{meta['game']}: {meta['variant']}"
    return name


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
        candidates: Track basenames in priority order.
        max_width:  Maximum line width in visible characters.
        tod_grad:   Time-of-day gradient (from colors._active_tod_grad).
        focused:    Whether the panel has keyboard focus.
        sel_idx:    Index of the selected entry (0-based within shown list).
        max_shown:  Maximum number of candidates to show (default UP_NEXT_MAX).
    """
    if not candidates:
        title_trunc = truncate_plain("Up next", max_width)
        plain = [title_trunc, "(no candidates)"]
        plain = [truncate_plain(s, max_width) for s in plain]
        color = [c(plain[0], "36"), c(plain[1], "2")]
        return plain, color

    shown_raw = list(candidates[:max_shown])
    shown = [_fmt_candidate(s) for s in shown_raw]
    if len(candidates) > max_shown:
        shown.append(f"{SYM_ELLIPSIS} +{len(candidates) - max_shown} more")

    header = f"Up next ({min(len(candidates), max_shown)}/{len(candidates)})"
    header_trunc = truncate_plain(header, max_width)
    plain = [truncate_plain(s, max_width) for s in [header_trunc] + shown]

    if USE_COLOR:
        hi_col = gradient_at(tod_grad, 70)
        lo_col = gradient_at(tod_grad, 40)
        color: list[str] = [c256(plain[0], hi_col)]
        for i, line in enumerate(plain[1:]):
            if focused and i == sel_idx:
                color.append(f"\x1b[7m{line}\x1b[0m")
            else:
                color.append(
                    f"\x1b[2m{superscript_num(i + 1)}\x1b[0m "
                    f"{c256(line, lo_col if i >= 1 else hi_col)}"
                )
    else:
        color = [c(plain[0], "36")] + [
            (f"\x1b[7m{s}\x1b[0m" if (focused and i == sel_idx) else c(s, "2"))
            for i, s in enumerate(plain[1:])
        ]

    return plain, color

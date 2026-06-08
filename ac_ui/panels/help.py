"""Help panel renderer — pure function, no side effects."""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c, gradient_at
from ac_ui.layout import wrap_plain, colorize_hint_keys


def render(
    help_lines_base: list[str],
    audio_sink: str,
    max_width: int,
    max_rows: int,
    tod_grad: list,
) -> tuple[list[str], list[str]] | tuple[None, None]:
    """Return (plain_lines, color_lines) for the Help panel, or (None, None) if empty.

    Args:
        help_lines_base: Base help text lines (first line is typically a header, skipped here).
        audio_sink:      Name of the current audio output sink to display.
        max_width:       Maximum line width in visible characters.
        max_rows:        Maximum number of content rows (budget minus box borders).
        tod_grad:        Time-of-day gradient (from colors._active_tod_grad).
    """
    lines = list(help_lines_base[1:])
    lines.append(f"Audio output: {audio_sink}")
    lines.append("Focus throttle: AC_UI_FOCUS_THROTTLE=1")

    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap_plain(line, max_width) or [""])
    wrapped = wrapped[:max(0, max_rows)]

    if not wrapped:
        return None, None

    if USE_COLOR:
        hk_col = gradient_at(tod_grad, 80)
        color: list[str] = [colorize_hint_keys(s, hk_col, base_code="2") for s in wrapped]
    else:
        color = [c(s, "2") for s in wrapped]

    return wrapped, color

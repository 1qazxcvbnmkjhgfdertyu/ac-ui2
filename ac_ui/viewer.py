"""Full-screen content viewer (Section 1.2 — enlarge the active pane).

Given pre-rendered (plain, color) lines, show them in a large centered box with
scrolling.  ui.py renders the focused panel at full width via its existing pure
renderer and hands the lines here, so "fullscreen a panel" needs no changes to
the main compositor — the panel geography stays intact, we just zoom one pane.
"""
from __future__ import annotations


def build_viewer_frame(
    plain: list[str],
    color: list[str],
    scroll: int,
    body_rows: int,
) -> tuple[list[str], list[str], int]:
    """Return (window_plain, window_color, clamped_scroll) for the given scroll."""
    total = len(plain)
    max_scroll = max(0, total - body_rows)
    scroll = max(0, min(scroll, max_scroll))
    wp = plain[scroll:scroll + body_rows]
    wc = (color or plain)[scroll:scroll + body_rows]
    # Pad so the box keeps a stable height.
    while len(wp) < body_rows:
        wp = list(wp) + [""]
        wc = list(wc) + [""]
    return wp, wc, scroll

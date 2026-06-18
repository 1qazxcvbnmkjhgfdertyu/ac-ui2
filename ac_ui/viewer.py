"""Full-screen content viewer (Section 1.2 — enlarge the active pane).

Given pre-rendered (plain, color) lines, show them in a large centered box with
scrolling.  ui.py renders the focused panel at full width via its existing pure
renderer and hands the lines here, so "fullscreen a panel" needs no changes to
the main compositor — the panel geography stays intact, we just zoom one pane.
"""
from __future__ import annotations

import sys

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.layout import build_box
from ac_ui.modal import Modal
from ac_ui.term import render, _read_key


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


def run_fullscreen_view(
    title: str,
    plain: list[str],
    color: list[str] | None,
    cols: int,
    rows: int,
    fd: int | None = None,
) -> None:
    """Display pre-rendered content full-screen with up/down/pgup/pgdn scrolling."""
    if fd is None:
        fd = sys.stdin.fileno()
    color = color or list(plain)
    inner_w = max(20, cols - 6)
    body_rows = max(4, rows - 6)
    scroll = 0
    grad = _clrs._active_tod_grad if USE_COLOR else None

    with Modal():
        last_out = None
        while True:
            wp, wc, scroll = build_viewer_frame(plain, color, scroll, body_rows)
            max_scroll = max(0, len(plain) - body_rows)
            pos = "" if max_scroll == 0 else f"  ({scroll + 1}-{min(len(plain), scroll + body_rows)}/{len(plain)})"
            t2 = "[↑↓ scroll]  [esc/z] close"
            box, _ = build_box(wp, wc, maxw_override=inner_w, title=f"{title}{pos}", title2=t2)
            start_row = max(0, rows // 2 - len(box) // 2)
            out = [""] * rows
            for i, bline in enumerate(box):
                r = start_row + i
                if 0 <= r < rows:
                    pad = max(0, (cols - visible_len(bline)) // 2)
                    out[r] = " " * pad + bline
            if out != last_out:
                render(out, cols, rows)
                last_out = list(out)

            ch = _read_key(fd, timeout=0.1)
            if not ch:
                continue
            if ch in ("ESC", "z", "Z", "q"):
                break
            if ch == "UP":
                scroll = max(0, scroll - 1); last_out = None
            elif ch == "DOWN":
                scroll = min(max_scroll, scroll + 1); last_out = None
            elif ch == "PAGEUP":
                scroll = max(0, scroll - body_rows); last_out = None
            elif ch == "PAGEDOWN":
                scroll = min(max_scroll, scroll + body_rows); last_out = None

    _ = grad  # reserved for future themed chrome

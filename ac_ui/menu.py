"""Generic popup action menu (Section 3.1 — contextual drill-down).

A small modal that shows a short list of labelled actions and returns the chosen
value.  Used for the per-item "actions" menu when a panel is focused (play now,
move to top, …), and reusable anywhere a quick choice is needed.
"""
from __future__ import annotations

import sys

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.constants import ASCII_ONLY
from ac_ui.layout import build_box
from ac_ui.modal import Modal
from ac_ui.term import render, _read_key, truncate_plain


def build_menu_lines(
    options: list[tuple[str, object]],
    selected: int,
    inner_w: int,
) -> tuple[list[str], list[str]]:
    """Pure renderer: returns (plain_lines, color_lines) for the menu body."""
    marker = "> " if ASCII_ONLY else "▶ "
    grad = _clrs._active_tod_grad if USE_COLOR else None
    plain: list[str] = []
    color: list[str] = []
    for i, (label, _value) in enumerate(options):
        is_sel = i == selected
        prefix = marker if is_sel else "  "
        row = truncate_plain(f"{prefix}{label}", inner_w)
        plain.append(row)
        if not USE_COLOR:
            color.append(row)
        elif is_sel:
            color.append(c256(row, theme_role("accent", grad)))
        else:
            color.append(c256(row, theme_role("label", grad)))
    return plain, color


def run_menu(
    title: str,
    options: list[tuple[str, object]],
    cols: int,
    rows: int,
    fd: int | None = None,
):
    """Show a popup menu. Returns the chosen option's value, or None if cancelled.

    ``options`` is a list of ``(label, value)`` pairs.
    """
    if not options:
        return None
    if fd is None:
        fd = sys.stdin.fileno()
    selected = 0
    inner_w = max(20, min(cols - 8, 56))
    chosen = [None]

    with Modal():
        last_out = None
        while True:
            plain, color = build_menu_lines(options, selected, inner_w)
            box, _ = build_box(
                plain, color, maxw_override=inner_w,
                title=title, title2="[esc] cancel",
            )
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

            ch = _read_key(fd, timeout=0.08)
            if not ch:
                continue
            if ch == "ESC":
                break
            if ch in ("\r", "\n"):
                chosen[0] = options[selected][1]
                break
            if ch in ("UP", "k"):
                selected = (selected - 1) % len(options)
                last_out = None
                continue
            if ch in ("DOWN", "j"):
                selected = (selected + 1) % len(options)
                last_out = None
                continue
            # number shortcuts 1..9
            if ch.isdigit():
                idx = int(ch) - 1
                if 0 <= idx < len(options):
                    chosen[0] = options[idx][1]
                    break

    return chosen[0]

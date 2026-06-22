"""Generic popup action menu (Section 3.1 — contextual drill-down).

A small modal that shows a short list of labelled actions and returns the chosen
value.  Used for the per-item "actions" menu when a panel is focused (play now,
move to top, …), and reusable anywhere a quick choice is needed.
"""
from __future__ import annotations

from ac_ui.layout import render_selectable_row


def build_menu_lines(
    options: list[tuple[str, object]],
    selected: int,
    inner_w: int,
) -> tuple[list[str], list[str]]:
    """Pure renderer: returns (plain_lines, color_lines) for the menu body."""
    plain: list[str] = []
    color: list[str] = []
    for i, (label, _value) in enumerate(options):
        is_sel = i == selected
        row_plain, row_color = render_selectable_row(
            label,
            is_sel,
            inner_w,
            right=str(i + 1) if i < 9 else None,
            dim=not is_sel,
        )
        plain.append(row_plain)
        color.append(row_color)
    return plain, color

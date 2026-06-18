"""Generic fuzzy finder overlay (Section 6 — library/queue search).

A reusable incremental-search picker: feed it a list of :class:`FinderItem`
(label + opaque value + search haystack) and it returns the chosen value, or
None if cancelled.  Shares the palette's fuzzy matcher so ranking behaves the
same everywhere.  The library `/` search is the first consumer.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.constants import ASCII_ONLY
from ac_ui.layout import build_box
from ac_ui.modal import Modal
from ac_ui.palette import fuzzy_score
from ac_ui.term import render, _read_key, truncate_plain


@dataclass(frozen=True)
class FinderItem:
    label: str
    value: Any
    search: str


def make_item(label: str, value: Any, search: str | None = None) -> FinderItem:
    return FinderItem(label, value, (search if search is not None else label).lower())


def rank_items(items: list[FinderItem], query: str) -> list[FinderItem]:
    """Return items matching ``query`` (best first). Empty query → original order."""
    q = query.strip()
    if not q:
        return list(items)
    scored = []
    for idx, it in enumerate(items):
        s = fuzzy_score(q, it.search)
        if s is not None:
            scored.append((s, -idx, it))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [it for _s, _i, it in scored]


def build_finder_lines(
    matches: list[FinderItem],
    query: str,
    selected: int,
    total: int,
    inner_w: int,
    max_rows: int,
) -> tuple[list[str], list[str]]:
    """Pure renderer: returns (plain_lines, color_lines)."""
    marker = "> " if ASCII_ONLY else "▶ "
    grad = _clrs._active_tod_grad if USE_COLOR else None

    count = f"{len(matches)}/{total}"
    prompt_plain = truncate_plain(f"/ {query}_", max(1, inner_w - len(count) - 1))
    head = prompt_plain + " " * max(1, inner_w - len(prompt_plain) - len(count)) + count
    head = truncate_plain(head, inner_w)
    if USE_COLOR:
        head_color = c256(head, theme_role("accent", grad))
    else:
        head_color = head

    plain: list[str] = [head, ""]
    color: list[str] = [head_color, ""]

    list_rows = max(1, max_rows - 2)
    if not matches:
        empty = truncate_plain("  (no matches)", inner_w)
        plain.append(empty)
        color.append(c256(empty, theme_role("label_dim", grad)) if USE_COLOR else empty)
        return plain, color

    if selected < 0:
        selected = 0
    start = 0
    if len(matches) > list_rows:
        start = max(0, min(selected - list_rows // 2, len(matches) - list_rows))
    for i, it in enumerate(matches[start:start + list_rows]):
        real_idx = start + i
        is_sel = real_idx == selected
        prefix = marker if is_sel else "  "
        row = truncate_plain(f"{prefix}{it.label}", inner_w)
        plain.append(row)
        if not USE_COLOR:
            color.append(row)
        elif is_sel:
            color.append(c256(row, theme_role("accent", grad)))
        else:
            color.append(c256(row, theme_role("label", grad)))
    return plain, color


def run_fuzzy_finder(
    title: str,
    items: list[FinderItem],
    cols: int,
    rows: int,
    fd: int | None = None,
):
    """Drive the finder overlay. Returns the chosen item's value, or None."""
    if fd is None:
        fd = sys.stdin.fileno()
    query = ""
    selected = 0
    total = len(items)
    inner_w = max(40, min(cols - 6, 80))
    list_rows = max(4, min(18, rows - 7))
    chosen = [None]

    with Modal():
        last_out = None
        while True:
            matches = rank_items(items, query)
            if selected >= len(matches):
                selected = max(0, len(matches) - 1)
            plain, color = build_finder_lines(
                matches, query, selected, total, inner_w, list_rows + 2,
            )
            box, _ = build_box(
                plain, color, maxw_override=inner_w,
                title=title, title2="[esc] close",
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
                if matches:
                    chosen[0] = matches[selected].value
                break
            if ch == "UP":
                if matches:
                    selected = (selected - 1) % len(matches)
                last_out = None
                continue
            if ch == "DOWN":
                if matches:
                    selected = (selected + 1) % len(matches)
                last_out = None
                continue
            if ch in ("\x7f", "\b", "BACKSPACE"):
                query = query[:-1]
                selected = 0
                last_out = None
                continue
            if len(ch) == 1 and ch.isprintable():
                query += ch
                selected = 0
                last_out = None
                continue

    return chosen[0]

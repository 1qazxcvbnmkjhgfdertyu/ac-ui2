"""Generic fuzzy finder overlay (Section 6 — library/queue search).

A reusable incremental-search picker: feed it a list of :class:`FinderItem`
(label + opaque value + search haystack) and it returns the chosen value, or
None if cancelled.  Shares the palette's fuzzy matcher so ranking behaves the
same everywhere.  The library `/` search is the first consumer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ac_ui.layout import empty_state_line, render_selectable_row, search_prompt_line
from ac_ui.palette import fuzzy_score
from ac_ui.term import truncate_plain


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
    count = f"{len(matches)}/{total}"
    head, head_color = search_prompt_line(
        query,
        inner_w,
        placeholder="Search library",
        count_text=count,
    )

    plain: list[str] = [head, ""]
    color: list[str] = [head_color, ""]

    list_rows = max(1, max_rows - 2)
    if not matches:
        empty_plain, empty_color = empty_state_line("no matches", inner_w)
        plain.append(empty_plain)
        color.append(empty_color)
        return plain, color

    if selected < 0:
        selected = 0
    start = 0
    if len(matches) > list_rows:
        start = max(0, min(selected - list_rows // 2, len(matches) - list_rows))
    for i, it in enumerate(matches[start:start + list_rows]):
        real_idx = start + i
        is_sel = real_idx == selected
        row_plain, row_color = render_selectable_row(it.label, is_sel, inner_w, dim=not is_sel)
        plain.append(row_plain)
        color.append(row_color)
    return plain, color

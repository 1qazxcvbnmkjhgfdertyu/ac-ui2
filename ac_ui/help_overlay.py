"""Searchable help overlay — keybindings grouped by context (Section 3.3).

Lists every action grouped into readable categories, with short labels (so rows
never truncate), incremental fuzzy search, and a drill-in detail popup for the
full explanation.  These are pure renderers (``build_help_groups``,
``filter_help_groups``, ``build_help_lines``, ``build_help_detail_box``); the
interactive surface is ``HelpOverlay`` in ``ac_ui.overlay``.  It reuses the
palette's command model and fuzzy matcher so the two stay consistent and there
is one source of truth (the ACTIONS registry).
"""
from __future__ import annotations

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, paint, theme_role
from ac_ui.layout import (
    build_box,
    empty_state_line,
    render_selectable_row,
    search_prompt_line,
    section_heading_line,
    wrap_plain,
)
from ac_ui.palette import PaletteCommand, build_palette_commands, fuzzy_score
from ac_ui.term import truncate_plain

# Ordered (category title -> action ids).  Any action not listed here lands in
# "Other", so new actions still appear without editing this map.
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Playback",        ("next", "mute", "vol", "vol_pg", "loop", "sink", "hour_sim")),
    ("Library & queue", ("find", "game", "variant", "free_play", "pin", "ban",
                         "add_track", "playlist_mgr", "queue_mgr")),
    ("Panels & layout", ("history", "up_next", "layout", "bg_mode",
                         "panel_nav", "panel_focus_num")),
    ("Visuals",         ("vis", "vis_shuffle", "vis_fps", "theme")),
    ("Tools",           ("tune", "eq")),
    ("General",         ("help", "palette", "quit", "debug")),
)


def build_help_groups(
    commands: list[PaletteCommand] | None = None,
) -> list[tuple[str, list[PaletteCommand]]]:
    """Group all palette commands into ordered display categories."""
    if commands is None:
        commands = build_palette_commands(skip_ids=())
    by_id = {c.action_id: c for c in commands}
    used: set[str] = set()
    groups: list[tuple[str, list[PaletteCommand]]] = []
    for title, ids in _CATEGORIES:
        members = [by_id[i] for i in ids if i in by_id]
        used.update(i for i in ids if i in by_id)
        if members:
            groups.append((title, members))
    leftover = [c for c in commands if c.action_id not in used]
    if leftover:
        groups.append(("Other", leftover))
    return groups


def filter_help_groups(
    groups: list[tuple[str, list[PaletteCommand]]],
    query: str,
) -> list[tuple[str, list[PaletteCommand]]]:
    """Drop commands (and then empty categories) that don't match ``query``."""
    q = query.strip()
    if not q:
        return groups
    out: list[tuple[str, list[PaletteCommand]]] = []
    for title, members in groups:
        kept = [c for c in members if fuzzy_score(q, c.search) is not None]
        if kept:
            out.append((title, kept))
    return out


def build_help_lines(
    groups: list[tuple[str, list[PaletteCommand]]],
    query: str,
    scroll: int,
    inner_w: int,
    max_rows: int,
    selected: int = -1,
) -> tuple[list[str], list[str], int]:
    """Pure renderer. Returns (plain_lines, color_lines, total_rows).

    Rows show each command's short label (so they never truncate); the full
    explanation is shown by the detail popup. ``selected`` is an index into the
    flattened command list (in display order); when >= 0 that row is highlighted
    and the scroll window follows it. ``total_rows`` is the full content height.
    """
    # Build the full (unscrolled) content first.
    full_plain: list[str] = []
    full_color: list[str] = []

    if not groups:
        msg_plain, msg_color = empty_state_line("no matching commands", inner_w)
        full_plain.append(msg_plain)
        full_color.append(msg_color)

    cmd_index = -1
    selected_line = -1
    for gi, (title, members) in enumerate(groups):
        if gi > 0:
            full_plain.append("")
            full_color.append("")
        head, head_color = section_heading_line(title, inner_w)
        full_plain.append(head)
        full_color.append(head_color)
        for c in members:
            cmd_index += 1
            is_sel = cmd_index == selected
            tag = f"[{c.key_label}]"
            label = c.short or c.title
            row, row_color = render_selectable_row(
                label,
                is_sel,
                inner_w,
                right=tag,
                dim=not is_sel,
            )
            if is_sel:
                selected_line = len(full_plain)
            full_plain.append(row)
            full_color.append(row_color)

    total = len(full_plain)

    # Header: search prompt.
    cmd_total = sum(len(members) for _title, members in groups)
    prompt_plain, prompt_color = search_prompt_line(
        query,
        inner_w,
        placeholder="Search help",
        count_text=f"{cmd_total} cmds",
    )

    body_rows = max(1, max_rows - 2)
    # When a row is selected, keep it centred in the window; otherwise honour the
    # caller-supplied scroll offset.
    if selected_line >= 0:
        scroll = selected_line - body_rows // 2
    scroll = max(0, min(scroll, max(0, total - body_rows)))
    window_p = full_plain[scroll:scroll + body_rows]
    window_c = full_color[scroll:scroll + body_rows]

    plain = [prompt_plain, ""] + window_p
    color = [prompt_color, ""] + window_c
    return plain, color, total


def build_help_detail_box(command: PaletteCommand, width: int) -> list[str]:
    """Build the drill-in detail popup (key + full plain-language explanation)."""
    inner = max(24, min(width - 6, 46))
    plain: list[str] = [f"Key:  {command.key_label}", ""]
    for line in wrap_plain(command.desc or command.title, inner):
        plain.append(line)
    grad = _clrs._active_tod_grad if USE_COLOR else None
    color = []
    for i, line in enumerate(plain):
        if not USE_COLOR:
            color.append(line)
        elif i == 0:
            color.append(paint(line, fg=theme_role("accent_soft", grad), bold=True))
        else:
            color.append(c256(line, theme_role("label", grad)))
    box, _ = build_box(plain, color, maxw_override=inner, title=command.title, title2="[esc] back")
    return box

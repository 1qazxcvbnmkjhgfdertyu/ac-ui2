"""Searchable help overlay — keybindings grouped by context (Section 3.3).

Replaces the old inline help panel with a full-screen modal that lists every
action grouped into readable categories and supports incremental fuzzy search
(type to filter, scroll with the arrow keys).  It reuses the palette's command
model and fuzzy matcher so the two stay consistent and there is one source of
truth (the ACTIONS registry).
"""
from __future__ import annotations

import sys

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.layout import build_box, colorize_hint_keys
from ac_ui.modal import Modal
from ac_ui.palette import PaletteCommand, build_palette_commands, fuzzy_score
from ac_ui.term import render, _read_key, truncate_plain


# Ordered (category title -> action ids).  Any action not listed here lands in
# "Other", so new actions still appear without editing this map.
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Playback",        ("next", "mute", "vol", "vol_pg", "loop", "sink", "hour_sim")),
    ("Library & queue", ("find", "game", "variant", "free_play", "pin", "ban",
                         "add_track", "playlist_mgr", "queue_mgr")),
    ("Panels & layout", ("history", "up_next", "layout", "bg_mode",
                         "panel_nav", "panel_focus_num")),
    ("Visuals",         ("vis", "vis_fps", "theme")),
    ("Tools",           ("tune", "eq")),
    ("General",         ("help", "palette", "quit")),
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
) -> tuple[list[str], list[str], int]:
    """Pure renderer. Returns (plain_lines, color_lines, total_rows).

    ``total_rows`` is the full content height before the scroll window is
    applied, so the caller can clamp ``scroll``.
    """
    grad = _clrs._active_tod_grad if USE_COLOR else None

    # Build the full (unscrolled) content first.
    full_plain: list[str] = []
    full_color: list[str] = []
    key_w = 0
    for _title, members in groups:
        for c in members:
            key_w = max(key_w, len(f"[{c.key_label}]"))
    key_w = min(key_w, max(4, inner_w // 2))

    if not groups:
        msg = truncate_plain("  (no matching commands)", inner_w)
        full_plain.append(msg)
        full_color.append(c256(msg, theme_role("label_dim", grad)) if USE_COLOR else msg)
    for gi, (title, members) in enumerate(groups):
        if gi > 0:
            full_plain.append("")
            full_color.append("")
        head = truncate_plain(title, inner_w)
        full_plain.append(head)
        full_color.append(c256(head, theme_role("accent", grad)) if USE_COLOR else head)
        for c in members:
            tag = f"[{c.key_label}]"
            desc = c.desc or c.title
            row = f"  {tag.ljust(key_w)}  {desc}"
            row = truncate_plain(row, inner_w)
            full_plain.append(row)
            if USE_COLOR:
                full_color.append(colorize_hint_keys(
                    row, theme_role("accent_soft", grad),
                    base_fg=theme_role("label", grad), dim=True,
                ))
            else:
                full_color.append(row)

    total = len(full_plain)

    # Header: search prompt.
    cursor = "_"
    prompt_plain = truncate_plain(f"/ {query}{cursor}", inner_w)
    prompt_color = (
        c256(prompt_plain, theme_role("accent", grad)) if USE_COLOR else prompt_plain
    )

    body_rows = max(1, max_rows - 2)
    scroll = max(0, min(scroll, max(0, total - body_rows)))
    window_p = full_plain[scroll:scroll + body_rows]
    window_c = full_color[scroll:scroll + body_rows]

    plain = [prompt_plain, ""] + window_p
    color = [prompt_color, ""] + window_c
    return plain, color, total


def run_help_overlay(cols: int, rows: int, fd: int | None = None) -> None:
    """Drive the interactive, searchable help overlay (read-only)."""
    if fd is None:
        fd = sys.stdin.fileno()
    commands = build_palette_commands(skip_ids=())
    base_groups = build_help_groups(commands)
    query = ""
    scroll = 0
    inner_w = max(44, min(cols - 6, 76))
    body_rows = max(6, min(22, rows - 6))

    with Modal():
        last_out = None
        while True:
            groups = filter_help_groups(base_groups, query)
            plain, color, total = build_help_lines(
                groups, query, scroll, inner_w, body_rows + 2,
            )
            max_scroll = max(0, total - body_rows)
            scroll = min(scroll, max_scroll)
            box, _ = build_box(
                plain, color,
                maxw_override=inner_w,
                title="Help — keys & commands",
                title2="[/] search  [esc] close",
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
            if ch in ("ESC", "?"):
                break
            if ch == "UP":
                scroll = max(0, scroll - 1); last_out = None; continue
            if ch == "DOWN":
                scroll = min(max_scroll, scroll + 1); last_out = None; continue
            if ch == "PAGEUP":
                scroll = max(0, scroll - body_rows); last_out = None; continue
            if ch == "PAGEDOWN":
                scroll = min(max_scroll, scroll + body_rows); last_out = None; continue
            if ch in ("\x7f", "\b", "BACKSPACE"):
                query = query[:-1]; scroll = 0; last_out = None; continue
            if len(ch) == 1 and ch.isprintable():
                query += ch; scroll = 0; last_out = None; continue

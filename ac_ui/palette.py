"""Command palette — fuzzy-searchable action launcher (Posting-style).

The palette is built from the central ``ACTIONS`` registry in ``constants.py``,
so every action that has a key binding is automatically discoverable here with
no extra wiring.  The pure pieces (``build_palette_commands``,
``fuzzy_score``, ``rank_commands``, ``build_palette_lines``) are side-effect
free and unit-tested; ``run_command_palette`` drives the interactive overlay on
top of the shared :class:`Modal` framework and returns the *primary key* of the
chosen action so the existing key-dispatch chain in ``ui.py`` can execute it.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from ac_ui.constants import ACTIONS, ASCII_ONLY
import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.layout import build_box, colorize_hint_keys
from ac_ui.modal import Modal
from ac_ui.term import render, _read_key, truncate_plain


# Pretty display names for actions whose id is terse.  Anything missing falls
# back to a title-cased id, so new actions still appear without edits here.
_TITLES = {
    "next": "Next track",
    "tune": "Town tune editor",
    "eq": "EQ editor",
    "vis": "Visualizer (next / random)",
    "mute": "Mute / unmute",
    "quit": "Quit",
    "sink": "Audio output sink",
    "loop": "Repeat current until hour",
    "layout": "Cycle layout preset",
    "help": "Toggle help",
    "vol": "Volume up / down",
    "vol_pg": "Volume up / down (page)",
    "game": "Cycle game",
    "variant": "Cycle variant",
    "history": "Toggle history panel",
    "up_next": "Toggle up-next panel",
    "pin": "Pin / unpin current track",
    "ban": "Ban track and skip",
    "theme": "Cycle color theme",
    "hour_sim": "Simulate next hour",
    "bg_mode": "Background mode",
    "panel_nav": "Focus / navigate panels",
    "free_play": "Toggle free-play mode",
    "add_track": "Add current track to a playlist",
    "playlist_mgr": "Playlist manager",
    "queue_mgr": "Manage free-play queue",
}

# How a raw key string should read in the palette's key column.
_KEY_DISPLAY = {
    " ": "space",
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "PAGEUP": "PgUp",
    "PAGEDOWN": "PgDn",
}


def _key_display(key: str) -> str:
    return _KEY_DISPLAY.get(key, key)


@dataclass(frozen=True)
class PaletteCommand:
    action_id: str
    title: str
    desc: str
    primary: str       # primary key fed back into ui.py dispatch
    key_label: str     # human-readable key for display
    search: str        # lowercased haystack for fuzzy matching


def build_palette_commands(skip_ids: tuple[str, ...] = ("palette",)) -> list[PaletteCommand]:
    """Derive the command list from the ACTIONS registry.

    ``skip_ids`` excludes specific action ids — the palette omits itself by
    default; the help overlay passes an empty tuple to list everything.
    """
    cmds: list[PaletteCommand] = []
    for action_id, keys, _groups, label_full, _label_compact, help_text in ACTIONS:
        if not keys or action_id in skip_ids:
            continue
        primary = keys[0]
        title = _TITLES.get(action_id) or action_id.replace("_", " ").capitalize()
        desc = (help_text or label_full or "").strip()
        key_label = " / ".join(_key_display(k) for k in keys)
        search = f"{title} {desc} {action_id}".lower()
        cmds.append(PaletteCommand(action_id, title, desc, primary, key_label, search))
    # Append any registered command plugins so they're discoverable too.
    try:
        from ac_ui.plugins import REGISTRY as _plug
        for key, cmd in _plug.commands.items():
            if cmd.action_id in skip_ids:
                continue
            title = cmd.label if cmd.label[:1].isupper() else cmd.label.capitalize()
            search = f"{cmd.label} {cmd.help} {cmd.action_id}".lower()
            cmds.append(PaletteCommand(
                cmd.action_id, title, cmd.help, key, _key_display(key), search,
            ))
    except Exception:
        pass
    return cmds


def fuzzy_score(query: str, text: str):
    """Subsequence fuzzy match.  Returns a score (higher is better) or None.

    Rewards consecutive matches and matches at word boundaries, lightly
    penalises gaps, and nudges shorter haystacks ahead so concise commands win
    ties.  Returns None when ``query`` is not a subsequence of ``text``.
    """
    if not query:
        return 0
    q = query.lower()
    t = text.lower()
    score = 0
    ti = 0
    prev = -2
    streak = 0
    for qc in q:
        found = t.find(qc, ti)
        if found == -1:
            return None
        if found == prev + 1:
            streak += 1
            score += 6 + streak
        else:
            streak = 0
            score += 1
        if found == 0 or t[found - 1] in " _-/":
            score += 10
        score -= min(3, found - ti)  # gap penalty, bounded
        prev = found
        ti = found + 1
    score += max(0, 24 - len(t)) // 6
    return score


def rank_commands(commands: list[PaletteCommand], query: str) -> list[PaletteCommand]:
    """Return commands matching ``query``, best first.  Empty query → registry order."""
    q = query.strip()
    if not q:
        return list(commands)
    scored = []
    for idx, cmd in enumerate(commands):
        s = fuzzy_score(q, cmd.search)
        if s is not None:
            scored.append((s, -idx, cmd))  # -idx keeps registry order as tiebreak
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [cmd for _s, _i, cmd in scored]


def build_palette_lines(
    matches: list[PaletteCommand],
    query: str,
    selected: int,
    inner_w: int,
    max_rows: int,
) -> tuple[list[str], list[str]]:
    """Pure renderer for the palette body: returns (plain_lines, color_lines)."""
    marker = "> " if ASCII_ONLY else "▶ "
    cursor = "_"
    grad = _clrs._active_tod_grad if USE_COLOR else None

    prompt_plain = truncate_plain(f"/ {query}{cursor}", inner_w)
    if USE_COLOR:
        prompt_color = c256(prompt_plain, theme_role("accent", grad))
    else:
        prompt_color = prompt_plain

    plain: list[str] = [prompt_plain, ""]
    color: list[str] = [prompt_color, ""]

    list_rows = max(1, max_rows - 2)
    if not matches:
        empty = truncate_plain("  (no matches)", inner_w)
        plain.append(empty)
        color.append(c256(empty, theme_role("label_dim", grad)) if USE_COLOR else empty)
        return plain, color

    # Scrolling window that keeps the selection visible.
    if selected < 0:
        selected = 0
    start = 0
    if len(matches) > list_rows:
        start = max(0, min(selected - list_rows // 2, len(matches) - list_rows))
    window = matches[start:start + list_rows]

    for i, cmd in enumerate(window):
        real_idx = start + i
        is_sel = real_idx == selected
        prefix = marker if is_sel else "  "
        key_tag = f"[{cmd.key_label}]"
        # Left: marker + title ; Right: key tag, right-aligned.
        title = cmd.title
        avail = inner_w - len(prefix) - len(key_tag) - 1
        title = truncate_plain(title, max(1, avail))
        pad = max(1, inner_w - len(prefix) - len(title) - len(key_tag))
        row_plain = f"{prefix}{title}{' ' * pad}{key_tag}"
        row_plain = truncate_plain(row_plain, inner_w)
        plain.append(row_plain)

        if not USE_COLOR:
            color.append(row_plain)
            continue
        if is_sel:
            row_color = c256(row_plain, theme_role("accent", grad))
        else:
            # dim title, highlight the bracketed key tag
            row_color = colorize_hint_keys(
                row_plain,
                theme_role("accent_soft", grad),
                base_fg=theme_role("label", grad),
                dim=True,
            )
        color.append(row_color)

    return plain, color


def run_command_palette(cols: int, rows: int, fd: int | None = None):
    """Drive the interactive palette overlay.

    Returns the primary key string of the chosen action (to be re-dispatched by
    ui.py), or None if the user cancelled.
    """
    if fd is None:
        fd = sys.stdin.fileno()
    commands = build_palette_commands()
    query = ""
    selected = 0
    inner_w = max(36, min(cols - 8, 70))
    list_rows = max(3, min(14, rows - 8))
    chosen: list[str | None] = [None]

    with Modal():
        last_out = None
        while True:
            matches = rank_commands(commands, query)
            if selected >= len(matches):
                selected = max(0, len(matches) - 1)
            plain, color = build_palette_lines(matches, query, selected, inner_w, list_rows + 2)
            box, _ = build_box(
                plain, color,
                maxw_override=inner_w,
                title="Command Palette",
                title2="[esc] close",
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
            if ch in ("ESC", "\x10"):          # Esc or Ctrl+P toggles closed
                break
            if ch in ("\r", "\n"):
                if matches:
                    chosen[0] = matches[selected].primary
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

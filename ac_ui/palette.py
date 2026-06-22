"""Command palette — fuzzy-searchable action launcher (Posting-style).

The palette is built from the central ``ACTIONS`` registry in ``constants.py``,
so every action that has a key binding is automatically discoverable here with
no extra wiring.  Everything in this module is pure and unit-tested
(``build_palette_commands``, ``fuzzy_score``, ``rank_commands``,
``build_palette_lines``); the interactive surface is ``PaletteOverlay`` in
``ac_ui.overlay``, which renders these and feeds the chosen action's *primary
key* back into the key-dispatch chain in ``ui.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ac_ui.constants import ACTIONS
from ac_ui.layout import empty_state_line, render_selectable_row, search_prompt_line
from ac_ui.term import truncate_plain

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
    "debug": "Debug overlay",
}

# How a raw key string should read in the palette's key column.
_KEY_DISPLAY = {
    " ": "space",
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "\x10": "^P",
    "PAGEUP": "PgUp",
    "PAGEDOWN": "PgDn",
}

# Friendly, plain-language explanations shown in the help overlay and palette.
# The pressed key is already shown in its own column, so these describe *what the
# action does* in natural language (no bracketed key letters). Anything missing
# falls back to the terse registry text, so new actions still appear.
_DESCRIPTIONS = {
    "next":       "Skip to the next track",
    "tune":       "Open the town tune editor",
    "eq":         "Open the equalizer",
    "vis":        "Change the visualizer (t = next, R = random)",
    "vis_fps":    "Set the visualizer's frame rate (smoothness)",
    "vis_shuffle":"Keep switching visualizers automatically",
    "mute":       "Mute or unmute the sound",
    "quit":       "Quit ac-ui",
    "sink":       "Choose which audio output device to play through",
    "loop":       "Repeat the current track until the next hour",
    "layout":     "Switch the screen layout (rail, stacked, wide, full)",
    "help":       "Show or hide this help",
    "palette":    "Open the command menu — search and run any action",
    "find":       "Search your library and play any track",
    "vol":        "Turn the volume up or down (steps of 5)",
    "vol_pg":     "Turn the volume up or down in bigger steps (10)",
    "game":       "Switch to the next game's soundtrack",
    "variant":    "Switch to a different version of the music (e.g. weather)",
    "history":    "Show or hide the recently-played panel",
    "up_next":    "Show or hide the coming-up-next panel",
    "pin":        "Pin the current track so it keeps repeating",
    "ban":        "Skip this track and don't play it again",
    "theme":      "Switch to the next color theme",
    "hour_sim":   "Jump the clock forward an hour (preview the hourly chime)",
    "bg_mode":    "Background mode — minimal drawing to save power",
    "panel_nav":  "Move around panels — arrows, Enter to pick, x actions, z zoom",
    "panel_focus_num": "Jump to a panel — 1 history, 2 up-next, 0 to unfocus",
    "free_play":  "Turn free-play on or off (play from your own playlist)",
    "add_track":  "Add the current track to a playlist",
    "playlist_mgr":"Manage playlists — create, edit, or delete them",
    "queue_mgr":  "Manage the free-play queue (reorder what plays next)",
    "debug":      "Show or hide the debug / performance overlay",
}


def _key_display(key: str) -> str:
    return _KEY_DISPLAY.get(key, key)


# Very short list labels (2-4 words) shown in the help screen so rows never
# truncate. The full sentence (above, in _DESCRIPTIONS) is shown when you drill
# into an entry. Anything missing falls back to the title.
_SHORT = {
    "next": "Skip track",          "tune": "Town tune editor",
    "eq": "Equalizer",             "vis": "Change visualizer",
    "vis_fps": "Frame rate",       "vis_shuffle": "Auto-shuffle visuals",
    "mute": "Mute / unmute",       "quit": "Quit",
    "sink": "Audio output",        "loop": "Repeat track",
    "layout": "Screen layout",     "help": "Help",
    "palette": "Command menu",     "find": "Find a track",
    "vol": "Volume ±5",       "vol_pg": "Volume ±10",
    "game": "Change game",         "variant": "Change variant",
    "history": "History panel",    "up_next": "Up-next panel",
    "pin": "Pin track",            "ban": "Ban track",
    "theme": "Color theme",        "hour_sim": "Skip an hour",
    "bg_mode": "Background mode",   "panel_nav": "Navigate panels",
    "panel_focus_num": "Jump to panel", "free_play": "Free-play mode",
    "add_track": "Add to playlist", "playlist_mgr": "Playlists",
    "queue_mgr": "Queue",          "debug": "Debug overlay",
}


@dataclass(frozen=True)
class PaletteCommand:
    action_id: str
    title: str
    desc: str
    primary: str       # primary key fed back into ui.py dispatch
    key_label: str     # human-readable key for display
    search: str        # lowercased haystack for fuzzy matching
    short: str = ""    # very short label for the help list (no truncation)


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
        desc = _DESCRIPTIONS.get(action_id) or (help_text or label_full or "").strip()
        key_label = " / ".join(_key_display(k) for k in keys)
        short = _SHORT.get(action_id) or title
        search = f"{title} {desc} {action_id}".lower()
        cmds.append(PaletteCommand(action_id, title, desc, primary, key_label, search, short))
    # Append any registered command plugins so they're discoverable too.
    try:
        from ac_ui.plugins import REGISTRY as _plug
        for key, cmd in _plug.commands.items():
            if cmd.action_id in skip_ids:
                continue
            title = cmd.label if cmd.label[:1].isupper() else cmd.label.capitalize()
            search = f"{cmd.label} {cmd.help} {cmd.action_id}".lower()
            cmds.append(PaletteCommand(
                cmd.action_id, title, cmd.help, key, _key_display(key), search, title,
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
    n = len(matches)
    result_word = "result" if n == 1 else "results"
    prompt_plain, prompt_color = search_prompt_line(
        query,
        inner_w,
        placeholder="Search commands",
        count_text=f"{n} {result_word}",
    )

    plain: list[str] = [prompt_plain, ""]
    color: list[str] = [prompt_color, ""]

    list_rows = max(1, max_rows - 2)
    if not matches:
        empty_plain, empty_color = empty_state_line("no matches", inner_w)
        plain.append(empty_plain)
        color.append(empty_color)
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
        row_plain, row_color = render_selectable_row(
            cmd.title,
            is_sel,
            inner_w,
            right=f"[{cmd.key_label}]",
            dim=not is_sel,
        )
        plain.append(row_plain)
        color.append(row_color)

    return plain, color

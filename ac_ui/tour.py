"""Guided tour content + pure renderer for the in-app walkthrough overlay.

Pages are plain data so they're easy to edit and test. The TourOverlay
(overlay.py) just pages through them.
"""
from __future__ import annotations

from ac_ui.layout import build_box

# Each page: (title, [body lines]).
TOUR_GENERAL = [
    ("Welcome to ac-ui", [
        "A terminal music player: Animal Crossing hourly tunes by default,",
        "plus your own music library.",
        "",
        "[→]/[space] next   [←] back   [esc] exit the tour.",
    ]),
    ("Playback", [
        "  [space] / [m]   pause / mute",
        "  [n]             next track",
        "  [b]             previous track",
        "  [l]             repeat the current hour",
    ]),
    ("Visualizers", [
        "The animation reacts to the music — there are lots to pick from:",
        "",
        "  [t]      open the visualizer picker (type to filter)",
        "  [ / ]    previous / next visualizer",
        "  [R]      random        [r]  frame-rate",
        "  [y]      auto-shuffle visualizers",
    ]),
    ("Panels & layout", [
        "  [1] history   [2] up-next   [0] clear focus",
        "  [Tab]         cycle focus; arrows scroll the focused panel",
        "  [x]           actions on the focused item",
        "  [z]           zoom the focused panel full-screen",
        "  [L]           cycle layout presets",
    ]),
    ("Your own music", [
        "  [i]   import music — point at a folder, ac-ui copies it in",
        "  [/]   find & play any track (fuzzy search)",
        "  [f]   free play — your library instead of the hourly schedule",
        "",
        "More on free play & playlists on the next pages →",
    ]),
    ("Free play", [
        "Free play loops a playlist or folder instead of the clock.",
        "",
        "  [f]   toggle free play on / off",
        "  [F]   pick a different playlist / folder",
        "",
        "Importing music drops you straight into free play.",
    ]),
    ("Make your own playlists", [
        "Playlists are simple files you build right in the app:",
        "",
        "  [f]  (when NOT in free play) opens the playlist picker —",
        "        create a new list, rename, delete, or edit one.",
        "  [a]   add the now-playing track to a playlist",
        "  [o]   open a playlist in your $EDITOR",
        "",
        "Stored under ~/.local/share/ac-terminal-radio/playlists/.",
    ]),
    ("Animal Crossing extras", [
        "  [X]   extract authentic hourly music from your own disc",
        "  [T]   town-tune editor",
        "  [E]   equaliser",
    ]),
    ("Help is always here", [
        "  [?]   full searchable key reference",
        "  [:]   command palette — run anything by name",
        "  [G]   replay this tour        [q]  quit",
        "",
        "That's the tour — enjoy ac-ui!   [esc] to close.",
    ]),
]


def build_tour_lines(pages, idx, inner_w):
    """Render page `idx` of `pages` into a box. Returns the box lines."""
    idx = max(0, min(idx, len(pages) - 1))
    title, body = pages[idx]
    plain = list(body)
    while len(plain) < 7:            # keep the box a stable height across pages
        plain.append("")
    nav = "next" if idx < len(pages) - 1 else "finish"
    title2 = f"  {idx + 1}/{len(pages)}   [→/space] {nav}   [←] back   [esc] close"
    box, _ = build_box(plain, plain, maxw_override=inner_w,
                       title=f"Guided tour — {title}", title2=title2)
    return box

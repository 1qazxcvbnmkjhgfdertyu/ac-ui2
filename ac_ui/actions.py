"""Key-to-action dispatch table and action identifiers.

Currently the key handling lives inside main() closures in ui.py.
This module defines the canonical action IDs so that:
  - Tests can assert on action names without importing the full UI
  - Step 8 (full split) can wire up handlers here
"""
from __future__ import annotations

# Canonical action identifiers — must match ACTIONS in constants.py
ACTION_NEXT       = "next"
ACTION_TUNE       = "tune"
ACTION_EQ         = "eq"
ACTION_VIS        = "vis"
ACTION_MUTE       = "mute"
ACTION_QUIT       = "quit"
ACTION_SINK       = "sink"
ACTION_LOOP       = "loop"
ACTION_LAYOUT     = "layout"
ACTION_HELP       = "help"
ACTION_VOL        = "vol"
ACTION_VOL_PG     = "vol_pg"
ACTION_GAME       = "game"
ACTION_VARIANT    = "variant"
ACTION_HISTORY    = "history"
ACTION_UP_NEXT    = "up_next"
ACTION_PIN        = "pin"
ACTION_BAN        = "ban"
ACTION_THEME      = "theme"
ACTION_HOUR_SIM   = "hour_sim"
ACTION_BG_MODE    = "bg_mode"
ACTION_PANEL_NAV  = "panel_nav"
ACTION_FREE_PLAY  = "free_play"
ACTION_ADD_TRACK  = "add_track"
ACTION_PLAYLIST_MGR = "playlist_mgr"
ACTION_QUEUE_MGR  = "queue_mgr"

# Map raw key strings → action IDs (subset — single-key actions only)
KEY_MAP: dict[str, str] = {
    "n": ACTION_NEXT,
    "T": ACTION_TUNE,
    "E": ACTION_EQ,
    "t": ACTION_VIS,
    "R": ACTION_VIS,
    "m": ACTION_MUTE,
    " ": ACTION_MUTE,
    "q": ACTION_QUIT,
    "s": ACTION_SINK,
    "l": ACTION_LOOP,
    "L": ACTION_LAYOUT,
    "?": ACTION_HELP,
    "+": ACTION_VOL,
    "-": ACTION_VOL,
    "=": ACTION_VOL,
    "PAGEUP": ACTION_VOL_PG,
    "PAGEDOWN": ACTION_VOL_PG,
    "g": ACTION_GAME,
    "v": ACTION_VARIANT,
    "H": ACTION_HISTORY,
    "U": ACTION_UP_NEXT,
    "p": ACTION_PIN,
    "b": ACTION_BAN,
    "C": ACTION_THEME,
    "h": ACTION_HOUR_SIM,
    "8": ACTION_BG_MODE,
    "\t": ACTION_PANEL_NAV,
    "f": ACTION_FREE_PLAY,
    "a": ACTION_ADD_TRACK,
    "F": ACTION_PLAYLIST_MGR,
    "Q": ACTION_QUEUE_MGR,
}

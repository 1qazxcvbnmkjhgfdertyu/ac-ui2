"""User-configurable key remapping (Section 6).

The in-app dispatch in ui.py is keyed on the *default* key strings from the
ACTIONS registry.  Rather than rewrite that dispatch, this module builds an
*alias* table: ``{pressed_key -> canonical_default_key}``.  ui.py applies it as
``ch = key_aliases.get(ch, ch)`` immediately after reading a key, so a user's
custom binding is translated to the default key the dispatch already knows.

Config file (JSON), found at ``$AC_UI_KEYMAP`` or
``~/.config/ac-ui/keymap.json``::

    {
      "bindings": {
        "next":  ["right", "l"],
        "mute":  ["0"],
        "quit":  ["x"]
      }
    }

Keys may be single characters or friendly names (``space``, ``tab``, ``enter``,
``up``/``down``/``left``/``right``, ``pageup``/``pagedown``, ``esc``).  Unknown
action ids and keys are reported via diagnostics and skipped — a bad config
never crashes startup.
"""
from __future__ import annotations

import json
import os

from ac_ui.constants import ACTIONS
from ac_ui import diagnostics

# Friendly aliases the user may type in the config -> the token _read_key emits.
_NAME_TO_KEY = {
    "space": " ",
    "tab": "\t",
    "enter": "\r",
    "return": "\r",
    "esc": "ESC",
    "escape": "ESC",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "pageup": "PAGEUP",
    "pagedown": "PAGEDOWN",
}


def default_keymap_path() -> str:
    env = os.environ.get("AC_UI_KEYMAP")
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ac-ui", "keymap.json")


def _normalize_key(token: str) -> str | None:
    if token is None:
        return None
    s = str(token)
    if not s:
        return None
    low = s.lower()
    if low in _NAME_TO_KEY:
        return _NAME_TO_KEY[low]
    # Ctrl+<letter> notation, e.g. "ctrl+p" / "^p" -> control byte.
    if low.startswith("ctrl+") and len(low) == 6:
        c = low[5]
        if "a" <= c <= "z":
            return chr(ord(c) - 96)
    if low.startswith("^") and len(s) == 2:
        c = low[1]
        if "a" <= c <= "z":
            return chr(ord(c) - 96)
    if len(s) == 1:
        return s
    return None  # unrecognised multi-char token


def _action_primary_keys(actions=ACTIONS) -> dict[str, str]:
    """action_id -> its default primary key (first entry in the registry)."""
    out: dict[str, str] = {}
    for action_id, keys, *_rest in actions:
        if keys:
            out[action_id] = keys[0]
    return out


def build_key_aliases(config: dict, actions=ACTIONS) -> dict[str, str]:
    """Translate a config dict into a ``{pressed_key -> canonical_key}`` table.

    Pure and side-effect free except for diagnostics warnings on bad entries.
    """
    primary = _action_primary_keys(actions)
    aliases: dict[str, str] = {}
    if not isinstance(config, dict):
        return aliases
    bindings = config.get("bindings", config)
    if not isinstance(bindings, dict):
        return aliases
    for action_id, keys in bindings.items():
        if action_id not in primary:
            diagnostics.warn("keymap", f"unknown action '{action_id}' ignored")
            continue
        target = primary[action_id]
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, (list, tuple)):
            diagnostics.warn("keymap", f"bindings for '{action_id}' must be a list")
            continue
        for tok in keys:
            norm = _normalize_key(tok)
            if norm is None:
                diagnostics.warn("keymap", f"unrecognised key '{tok}' for '{action_id}'")
                continue
            aliases[norm] = target
    return aliases


def load_key_aliases(path: str | None = None, actions=ACTIONS) -> dict[str, str]:
    """Load and build the alias table from disk. Missing file -> empty table."""
    if path is None:
        path = default_keymap_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError) as e:
        diagnostics.warn("keymap", f"failed to read {path}: {e}")
        return {}
    return build_key_aliases(config, actions=actions)

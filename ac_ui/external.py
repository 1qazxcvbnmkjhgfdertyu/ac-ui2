"""Hand off to external tools (Section 7).

The TUI keeps a sharp interaction core and shells out for heavy editing: open a
file in ``$VISUAL``/``$EDITOR`` and reload afterwards.  This temporarily leaves
the alt-screen / hidden-cursor / no-autowrap state so the editor gets a clean
terminal, then restores the TUI on return.
"""
from __future__ import annotations

import os
import shlex
import subprocess

from ac_ui import diagnostics
from ac_ui.term import (
    enter_alt_screen, exit_alt_screen, hide_cursor, show_cursor,
    enable_autowrap, disable_autowrap, invalidate_render_cache,
)


def editor_command() -> list[str]:
    """Resolve the user's editor as an argv list (honours args, e.g. 'code -w')."""
    raw = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        return shlex.split(raw)
    except ValueError:
        return [raw]


def open_in_editor(path: str) -> bool:
    """Open ``path`` in the user's editor, restoring the TUI afterwards.

    Returns True if the editor ran and exited 0.  The RawMode (cbreak) terminal
    state set by main() is left untouched — editors set and restore their own
    termios — so on return the main loop's key reads keep working.
    """
    if not path:
        return False
    argv = editor_command() + [path]
    # Drop TUI chrome so the editor sees a normal terminal.
    exit_alt_screen()
    show_cursor()
    enable_autowrap()
    ok = False
    try:
        rc = subprocess.call(argv)
        ok = (rc == 0)
        if not ok:
            diagnostics.warn("editor", f"{argv[0]} exited with code {rc}")
    except (OSError, ValueError) as e:
        diagnostics.warn("editor", f"failed to launch {argv[0]}: {e}")
    finally:
        # Re-enter the TUI and force a full repaint.
        enter_alt_screen()
        hide_cursor()
        disable_autowrap()
        invalidate_render_cache(clear_screen=True)
    return ok

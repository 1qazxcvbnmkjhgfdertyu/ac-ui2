"""
Unified modal framework for full-screen editors and overlays.

Provides:
  - Modal context manager — handles cursor/screen lifecycle
  - run_modal_loop()     — standardized render+key loop
  - modal_confirm()      — inline yes/no prompt
  - modal_status_bar()   — one-line status line at bottom of modal

All editors (EQ, Tune) and the help overlay can share this infrastructure
so cursor handling, exit keys, and adaptive sizing never drift.
"""

import sys
import shutil

from ac_ui.term import (
    invalidate_render_cache, render, _read_key,
    truncate_plain,
)
from ac_ui.colors import USE_COLOR, c, c256, gradient_at
from ac_ui.layout import build_box, wrap_plain


_EXIT_KEYS = frozenset(("q", "Q", "ESC"))


class Modal:
    """
    Context manager for full-screen modal UI.

    Usage::

        with Modal() as m:
            m.run(build_fn, on_key_fn)

    ``build_fn()``  → (lines: list[str], cols: int, rows: int)
    ``on_key_fn(ch)`` → True to exit, False/None to continue
    """

    def __enter__(self):
        invalidate_render_cache(clear_screen=True)
        return self

    def __exit__(self, *_):
        invalidate_render_cache(clear_screen=True)

    def run(self, build_fn, on_key_fn, fps=20, exit_keys=_EXIT_KEYS):
        """
        Standard event loop.  Calls build_fn() every frame, renders only on
        change, reads one key per iteration, and exits when on_key_fn returns
        True or a key in exit_keys is received.
        """
        last_lines = None
        timeout = max(0.016, 1.0 / max(1, fps))
        fd = sys.stdin.fileno()
        while True:
            lines, cols, rows = build_fn()
            if lines != last_lines:
                render(lines, cols, rows)
                last_lines = list(lines)
            ch = _read_key(fd, timeout=timeout)
            if not ch:
                continue
            if ch in exit_keys:
                break
            if on_key_fn(ch):
                break


def run_modal_loop(build_fn, on_key_fn, fps=20, exit_keys=_EXIT_KEYS):
    """Convenience wrapper — enters and runs a Modal without a with-block."""
    with Modal() as m:
        m.run(build_fn, on_key_fn, fps=fps, exit_keys=exit_keys)


def modal_confirm(question, cols=None, rows=None, yes_key="y", no_key="n"):
    """
    Inline yes/no confirmation rendered over the current screen.
    Returns True if user presses yes_key, False otherwise.
    """
    if cols is None or rows is None:
        size = shutil.get_terminal_size(fallback=(80, 24))
        cols, rows = size.columns, size.lines

    prompt = f"{question}  [{yes_key}]es / [{no_key}]o"
    prompt_w = min(len(prompt) + 4, cols - 4)
    prompt_trunc = truncate_plain(prompt, prompt_w)
    if USE_COLOR:
        colored = [c256(prompt_trunc, 220)]
    else:
        colored = [prompt_trunc]
    box, _ = build_box([prompt_trunc], colored, maxw_override=prompt_w, title="Confirm")

    # Render centered on screen
    start_row = max(0, rows // 2 - len(box) // 2)
    lines_out = [""] * rows
    for i, bline in enumerate(box):
        r = start_row + i
        if r < rows:
            pad = max(0, (cols - len(bline)) // 2)
            lines_out[r] = " " * pad + bline

    render(lines_out, cols, rows)
    fd = sys.stdin.fileno()
    while True:
        ch = _read_key(fd, timeout=0.1)
        if not ch:
            continue
        if ch.lower() == yes_key.lower():
            return True
        if ch.lower() == no_key.lower() or ch in _EXIT_KEYS:
            return False


def modal_status_bar(message, color_code=None, cols=None):
    """
    Return a single formatted status bar line for the bottom of a modal.
    """
    if cols is None:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    text = truncate_plain(str(message), max(1, cols - 2))
    if USE_COLOR and color_code is not None:
        return c256(text, color_code)
    if USE_COLOR:
        return c(text, "2")
    return text


def _invalidate_after_modal():
    invalidate_render_cache(clear_screen=True)

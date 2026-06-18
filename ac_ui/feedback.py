"""Micro-interaction primitives (Section 4).

Pure, time-driven helpers for transient feedback.  The "toast" pattern (a
message that fades out after a TTL) already lives in ui.py as
``themed_banner``/``state_banner``; this module adds the missing piece: an
animated loading spinner that can be sampled once per render frame.
"""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c256, theme_role
import ac_ui.colors as _clrs
from ac_ui.constants import ASCII_ONLY, NO_MOTION

# Braille spinner for capable terminals; ASCII fallback otherwise.
_FRAMES_UNICODE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FRAMES_ASCII = ("|", "/", "-", "\\")


def spinner_frames() -> tuple[str, ...]:
    return _FRAMES_ASCII if ASCII_ONLY else _FRAMES_UNICODE


def spinner_frame(elapsed: float, fps: float = 12.0) -> str:
    """Return the spinner glyph for a given elapsed time (seconds).

    When motion is disabled (NO_MOTION / TTY mode) a single static glyph is
    returned so the layout still shows *something* without animating.
    """
    frames = spinner_frames()
    if NO_MOTION or fps <= 0:
        return frames[0]
    idx = int(max(0.0, elapsed) * fps) % len(frames)
    return frames[idx]


def loading_line(label: str, elapsed: float, fps: float = 12.0) -> str:
    """A plain '<spinner> <label>' string (no color)."""
    return f"{spinner_frame(elapsed, fps)} {label}"


def loading_line_colored(label: str, elapsed: float, fps: float = 12.0, role: str = "accent") -> str:
    """Colored variant of :func:`loading_line` using the active theme gradient."""
    text = loading_line(label, elapsed, fps)
    if not USE_COLOR:
        return text
    return c256(text, theme_role(role, _clrs._active_tod_grad))

"""Frame-rate control — a single target fps applied to *all* visualizers.

``cycle_fps`` steps through the offered rates and ``build_vis_fps_lines`` is the
pure (unit-tested) body renderer.  The interactive overlay that drives this lives
in ``overlay.VisFpsOverlay``; the chosen rate is written uniformly to the
persisted per-tier map (the tier classifier in ``audio_config`` still seeds
CPU-friendly defaults for fresh state / env overrides).
"""
from __future__ import annotations

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role
from ac_ui.constants import ASCII_ONLY, VIS_FPS_CHOICES
from ac_ui.term import truncate_plain

# Tier keys, retained so one chosen fps can be written uniformly to the
# persisted map without changing the on-disk format.
_TIERS = ("fast", "normal", "heavy")


def cycle_fps(current: int, direction: int) -> int:
    """Return the next/prev fps choice relative to ``current`` (wraps)."""
    choices = VIS_FPS_CHOICES
    # snap to nearest known choice, then step
    idx = min(range(len(choices)), key=lambda i: abs(choices[i] - current))
    return choices[(idx + direction) % len(choices)]


def build_vis_fps_lines(fps: int, inner_w: int, pinned: bool = False) -> tuple[list[str], list[str]]:
    """Pure renderer for the single-fps menu body: returns (plain_lines, color_lines).

    ``pinned`` warns that AC_UI_REFRESH is fixing the rate, so edits won't apply.
    """
    arrows = "<  >" if ASCII_ONLY else "◄  ►"
    grad = _clrs._active_tod_grad if USE_COLOR else None
    plain: list[str] = []
    color: list[str] = []

    label = "Frame rate (all visualizers)"
    rate = f"{fps:>3} fps  {arrows}"
    pad = max(1, inner_w - len(label) - len(rate) - 2)
    row = truncate_plain(f"  {label}{' ' * pad}{rate}", inner_w)
    plain.append(row)
    color.append(c256(row, theme_role("accent", grad)) if USE_COLOR else row)

    plain.append("")
    color.append("")
    hint = truncate_plain("  ←→ change   enter save   esc cancel", inner_w)
    plain.append(hint)
    color.append(c256(hint, theme_role("label_dim", grad)) if USE_COLOR else hint)
    if pinned:
        warn = truncate_plain("  ! AC_UI_REFRESH is set — unset it for this to apply", inner_w)
        plain.append(warn)
        color.append(c256(warn, theme_role("danger", grad)) if USE_COLOR else warn)
    return plain, color

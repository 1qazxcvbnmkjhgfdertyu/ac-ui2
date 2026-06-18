"""Frame-rate menu — set the visualizer fps per type/tier (interactive).

Three tiers (audio-reactive / self-animating / feedback) each get their own
target fps.  ↑/↓ pick a tier, ←/→ change its rate, Enter saves, Esc cancels.
The pure ``build_vis_fps_lines`` is unit-tested; ``run_vis_fps_menu`` drives the
overlay on the shared Modal framework and returns the updated tier->fps map (or
None if cancelled).
"""
from __future__ import annotations

import sys

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c256, theme_role, visible_len
from ac_ui.constants import ASCII_ONLY, VIS_FPS_CHOICES, VIS_TIER_LABELS
from ac_ui.layout import build_box
from ac_ui.modal import Modal
from ac_ui.term import render, _read_key, truncate_plain

_TIERS = ("fast", "normal", "heavy")


def cycle_fps(current: int, direction: int) -> int:
    """Return the next/prev fps choice relative to ``current`` (wraps)."""
    choices = VIS_FPS_CHOICES
    # snap to nearest known choice, then step
    idx = min(range(len(choices)), key=lambda i: abs(choices[i] - current))
    return choices[(idx + direction) % len(choices)]


def build_vis_fps_lines(
    fps_map: dict,
    selected: int,
    inner_w: int,
    pinned: bool = False,
) -> tuple[list[str], list[str]]:
    """Pure renderer for the menu body: returns (plain_lines, color_lines).

    ``pinned`` warns that AC_UI_REFRESH is fixing the rate, so edits won't apply.
    """
    marker = "> " if ASCII_ONLY else "▶ "
    arrows = "<  >" if ASCII_ONLY else "◄  ►"
    grad = _clrs._active_tod_grad if USE_COLOR else None
    plain: list[str] = []
    color: list[str] = []
    for i, tier in enumerate(_TIERS):
        is_sel = i == selected
        prefix = marker if is_sel else "  "
        fps = fps_map.get(tier, 60)
        label = VIS_TIER_LABELS.get(tier, tier.title())
        rate = f"{fps:>3} fps" + (f"  {arrows}" if is_sel else "")
        avail = inner_w - len(prefix) - len(rate) - 1
        label = truncate_plain(label, max(1, avail))
        pad = max(1, inner_w - len(prefix) - len(label) - len(rate))
        row = truncate_plain(f"{prefix}{label}{' ' * pad}{rate}", inner_w)
        plain.append(row)
        if not USE_COLOR:
            color.append(row)
        elif is_sel:
            color.append(c256(row, theme_role("accent", grad)))
        else:
            color.append(c256(row, theme_role("label", grad)))
    # Footer hint line.
    plain.append("")
    color.append("")
    hint = truncate_plain("  ↑↓ pick   ←→ change   enter save   esc cancel", inner_w)
    plain.append(hint)
    color.append(c256(hint, theme_role("label_dim", grad)) if USE_COLOR else hint)
    if pinned:
        warn = truncate_plain("  ! AC_UI_REFRESH is set — unset it for these to apply", inner_w)
        plain.append(warn)
        color.append(c256(warn, theme_role("danger", grad)) if USE_COLOR else warn)
    return plain, color


def run_vis_fps_menu(cols: int, rows: int, fps_map: dict, fd: int | None = None, pinned: bool = False):
    """Drive the frame-rate menu. Returns the edited map, or None if cancelled."""
    if fd is None:
        fd = sys.stdin.fileno()
    work = {t: int(fps_map.get(t, 60)) for t in _TIERS}
    selected = 0
    inner_w = max(44, min(cols - 6, 64))

    with Modal():
        last_out = None
        while True:
            plain, color = build_vis_fps_lines(work, selected, inner_w, pinned)
            box, _ = build_box(
                plain, color, maxw_override=inner_w,
                title="Visualizer frame rate", title2="[esc] cancel",
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

            ch = _read_key(fd, timeout=0.1)
            if not ch:
                continue
            if ch == "ESC":
                return None
            if ch in ("\r", "\n"):
                return work
            if ch in ("UP", "k"):
                selected = (selected - 1) % len(_TIERS); last_out = None
            elif ch in ("DOWN", "j"):
                selected = (selected + 1) % len(_TIERS); last_out = None
            elif ch in ("LEFT", "h"):
                tier = _TIERS[selected]
                work[tier] = cycle_fps(work[tier], -1); last_out = None
            elif ch in ("RIGHT", "l"):
                tier = _TIERS[selected]
                work[tier] = cycle_fps(work[tier], +1); last_out = None

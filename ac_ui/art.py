"""Procedural "album art" — a deterministic themed mosaic per game/variant.

Hourly Animal Crossing tracks have no cover art, so we synthesize an
identicon-style **symmetric block mosaic** seeded from the game/variant name and
tinted along a gradient.  Same game always yields the same art; different games
look distinct.  Pure function returning (plain_lines, color_lines), each sized
to an exact width/height so the Now Playing panel can place it as a side block.
"""
from __future__ import annotations

import zlib

from ac_ui.colors import ASCII_ONLY, USE_COLOR, gradient_at, paint, theme_visualizer_gradient

# Density variants give the mosaic some texture (solid → light shade).
_BLOCKS = ("@", "#", "*") if ASCII_ONLY else ("█", "▓", "▒")


def game_mosaic(seed, width, height, grad=None, use_color=None):
    """Return (plain_lines, color_lines) for a width×height themed mosaic.

    The pattern is left/right mirrored (album-cover-like symmetry), seeded
    deterministically from `seed`, and colored along `grad` by position.
    """
    if use_color is None:
        use_color = USE_COLOR
    width = max(1, int(width))
    height = max(1, int(height))
    if grad is None:
        grad = theme_visualizer_gradient("spectrum")

    state = (zlib.crc32(str(seed).encode("utf-8")) & 0xFFFFFFFF) or 1

    def _rnd():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state

    half = (width + 1) // 2
    plain_lines = []
    color_lines = []
    for y in range(height):
        on = [False] * width
        dens = [0] * width
        for x in range(half):
            r = _rnd()
            lit = (r >> 6) % 5 < 3        # ~60% fill
            d = (r >> 3) % len(_BLOCKS)   # density tier
            on[x] = on[width - 1 - x] = lit
            dens[x] = dens[width - 1 - x] = d
        prow = []
        crow = []
        for x in range(width):
            if on[x]:
                ch = _BLOCKS[dens[x]]
                prow.append(ch)
                if use_color:
                    val = int((x / max(1, width - 1)) * 55 + (y / max(1, height - 1)) * 45)
                    crow.append(paint(ch, fg=gradient_at(grad, val), bold=(dens[x] == 0)))
                else:
                    crow.append(ch)
            else:
                prow.append(" ")
                crow.append(" ")
        plain_lines.append("".join(prow))
        color_lines.append("".join(crow))
    return plain_lines, color_lines

"""btop-style meter and time-series graph primitives — pure, reusable widgets.

These are the building blocks btop++ leans on everywhere: a gradient *meter*
bar and a braille *area graph* of a value series.  Both are pure functions that
return strings sized to an exact width/height, so any panel can compose them
without touching the render loop.

    meter_bar(pct, width)          → one gradient-filled bar string
    braille_graph(series, w, h)    → list of h rows forming an area graph
"""
from __future__ import annotations

from ac_ui.colors import (
    ASCII_ONLY, USE_COLOR, gradient_at, paint, theme_role, theme_visualizer_gradient,
)

# 4-row × 2-col braille dot-bit table (same packing the visualizer uses).
_BRAILLE_BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
# Left-fill eighth blocks for a meter's fractional tip (1/8 .. 7/8 of a cell).
_PARTIAL_BLOCKS = (" ", ".", ":", "-", "=", "+", "*", "#") if ASCII_ONLY else (" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
_METER_FILL = "#" if ASCII_ONLY else "█"
_METER_HALF = "=" if ASCII_ONLY else "▌"
_METER_TRACK = "-" if ASCII_ONLY else "─"
_GRAPH_FILL = "#" if ASCII_ONLY else None
_GRAPH_EMPTY = " "


def meter_bar(value_pct, width, grad=None, *, track_role="track_bg",
              use_color=None, bold_tip=True):
    """Return a gradient meter bar exactly `width` cells wide.

    The filled portion is shaded along `grad` (green→hot like btop), with a
    sub-cell fractional tip so motion is smooth, and the remainder drawn as a
    dim track. Falls back to ASCII-safe glyphs when requested.
    """
    if use_color is None:
        use_color = USE_COLOR
    width = max(0, int(width))
    if width == 0:
        return ""
    pct = max(0.0, min(100.0, float(value_pct)))
    filled_f = pct / 100.0 * width
    full = int(filled_f)
    frac = filled_f - full

    if not use_color:
        body = _METER_FILL * full + (_METER_HALF if frac >= 0.5 and full < width else "")
        return (body + _METER_TRACK * (width - len(body)))[:width]

    if grad is None:
        grad = theme_visualizer_gradient("spectrum")

    parts = []
    for i in range(min(full, width)):
        parts.append(paint(_METER_FILL, fg=gradient_at(grad, int(i / max(1, width - 1) * 100))))
    cells = min(full, width)
    if frac > 0.05 and cells < width:
        tip = _PARTIAL_BLOCKS[max(1, min(7, int(frac * 8)))]
        parts.append(paint(tip, fg=gradient_at(grad, int(cells / max(1, width - 1) * 100)),
                           bold=bold_tip))
        cells += 1
    if cells < width:
        parts.append(paint(_METER_TRACK * (width - cells), fg=theme_role(track_role, grad)))
    return "".join(parts)


def _resample(series, n_out):
    """Linear-resample a value series to exactly n_out points (clamped 0..1)."""
    n = len(series)
    if n == 0:
        return [0.0] * n_out
    if n == 1:
        return [max(0.0, min(1.0, series[0]))] * n_out
    out = []
    for i in range(n_out):
        pos = i / max(1, n_out - 1) * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        v = series[lo] * (1.0 - (pos - lo)) + series[hi] * (pos - lo)
        out.append(max(0.0, min(1.0, v)))
    return out


def braille_graph(series, width, height=2, grad=None, *, col_colors=None,
                  use_color=None):
    """Render a 0..1 value `series` as a btop-style braille area graph.

    Each output column encodes two series samples (left/right braille dots) and
    each output row is four dot-rows tall, giving 2× horizontal / 4× vertical
    resolution.  Cells fill from the bottom up to each sample's value.

    Args:
        series:     iterable of values in 0..1 (resampled to fit width).
        width:      output columns.
        height:     output rows (each 4 dot-rows).
        grad:       gradient used to color cells by fill height.
        col_colors: optional list of per-column colors (e.g. per-hour palette);
                    overrides `grad` so callers can paint a custom timeline.
        use_color:  override the global color flag.

    Returns a list of exactly `height` strings, each `width` cells wide.
    """
    if use_color is None:
        use_color = USE_COLOR
    width = max(1, int(width))
    height = max(1, int(height))
    dot_rows = height * 4
    samples = _resample(list(series) if series else [0.0], width * 2)
    fills = [int(v * dot_rows + 0.5) for v in samples]

    if grad is None and not col_colors:
        grad = theme_visualizer_gradient("spectrum")

    if ASCII_ONLY:
        lines = []
        for row in range(height):
            threshold = (height - row - 1) / max(1, height)
            out = []
            for col in range(width):
                value = samples[min(len(samples) - 1, col * 2)]
                ch = _GRAPH_FILL if value > threshold else _GRAPH_EMPTY
                if ch != _GRAPH_EMPTY and use_color:
                    if col_colors is not None and col < len(col_colors):
                        color = col_colors[col]
                    else:
                        color = gradient_at(grad, int(value * 100))
                    out.append(paint(ch, fg=color, bold=value > 0.66))
                else:
                    out.append(ch)
            lines.append("".join(out))
        return lines

    lines = []
    for row in range(height):
        out = []
        for col in range(width):
            braille = 0x2800
            tallest = 0
            for dc in range(2):
                fill = fills[col * 2 + dc]
                if fill > tallest:
                    tallest = fill
                for dr in range(4):
                    if dot_rows - 1 - (row * 4 + dr) < fill:
                        braille |= _BRAILLE_BIT[dr][dc]
            if braille == 0x2800:
                out.append(" ")
            elif use_color:
                if col_colors is not None and col < len(col_colors):
                    color = col_colors[col]
                else:
                    color = gradient_at(grad, int(tallest / max(1, dot_rows) * 100))
                out.append(paint(chr(braille), fg=color, bold=tallest > dot_rows * 0.66))
            else:
                out.append(chr(braille))
        lines.append("".join(out))
    return lines

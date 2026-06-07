import math, random

import ac_ui.colors as _clrs
from ac_ui.colors import (
    USE_COLOR, c256, spectrum_color, gradient_at, smoothing_alpha_ms,
    _GRAD_AC_GREEN,
)
from ac_ui.constants import (
    VIS_BAR_BLOCKS, VIS_SHADE_BLOCKS, VIS_PEAK_GLYPHS,
    CAVA_HEIGHT, MATRIX_RAIN_CHARS,
)

# 4-row x 2-col dot-bit table: _BRAILLE_BIT[row][col] -> bitmask
_BRAILLE_BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]

def frac_block(level, row_bottom, row_top):
    if level >= row_top:
        return VIS_BAR_BLOCKS[-1]
    if level > row_bottom:
        frac = (level - row_bottom) / max(0.001, row_top - row_bottom)
        idx = int(frac * (len(VIS_BAR_BLOCKS) - 1))
        idx = max(0, min(len(VIS_BAR_BLOCKS) - 1, idx))
        return VIS_BAR_BLOCKS[idx]
    return " "

def shade_block(level, row_bottom, row_top):
    if level >= row_top:
        return VIS_SHADE_BLOCKS[-1]
    if level > row_bottom:
        frac = (level - row_bottom) / max(0.001, row_top - row_bottom)
        idx = int(frac * (len(VIS_SHADE_BLOCKS) - 1) + 0.25)
        idx = max(1, min(len(VIS_SHADE_BLOCKS) - 1, idx))
        return VIS_SHADE_BLOCKS[idx]
    return " "

def peak_cap(level, height):
    dot_rows = max(1, height * len(VIS_PEAK_GLYPHS))
    dot_y = int(round((1.0 - max(0.0, min(1.0, level))) * (dot_rows - 1)))
    row = dot_y // len(VIS_PEAK_GLYPHS)
    glyph = VIS_PEAK_GLYPHS[dot_y % len(VIS_PEAK_GLYPHS)]
    return row, glyph

def spectrum_lines(bars, height=CAVA_HEIGHT, use_color=None, mode="bars", trail_bars=None, peak_bars=None, game_tag=None):
    if use_color is None:
        use_color = USE_COLOR
    bars = bars or []
    n = len(bars)
    if n == 0:
        return ["(no spectrum data)"]
    if mode not in ("bars", "peaks", "shades", "outline", "spectrum"):
        mode = "bars"

    def value_at(values, i, fallback):
        if values is None or i >= len(values):
            return fallback
        return max(0.0, min(1.0, values[i]))

    def colorize(ch, i, row_norm, energy=0.0, is_tip=False):
        if not use_color or ch == " ":
            return ch
        if is_tip and not game_tag:
            tip_idx = min(100, 80 + int(energy * 20))
            return f"\x1b[1;38;5;{gradient_at(_clrs._active_tod_grad, tip_idx)}m{ch}\x1b[0m"
        return f"\x1b[38;5;{spectrum_color(i, n, row_norm, game_tag=game_tag, energy=energy)}m{ch}\x1b[0m"

    row_fragments = [[] for _ in range(height)]

    for row in range(height):
        row_bottom = (height - 1 - row) / max(1, height)
        row_top = (height - row) / max(1, height)
        row_norm = row_bottom
        for i, val in enumerate(bars):
            v = max(0.0, min(1.0, val))
            is_tip = False
            if mode == "spectrum":
                pv = value_at(peak_bars, i, v)
                tv = value_at(trail_bars, i, v)
                peak_row = (height - 1) - int(pv * (height - 1) + 0.5)
                trail_row = (height - 1) - int(tv * (height - 1) + 0.5)
                if row == peak_row:
                    ch = "█"
                elif row >= trail_row:
                    ch = "·"
                else:
                    ch = " "
            elif mode == "peaks":
                pv = value_at(peak_bars, i, v)
                cap_row, cap_glyph = peak_cap(pv, height)
                min_gap = max(0.01, 0.5 / max(1, height * len(VIS_PEAK_GLYPHS)))
                if pv > v + min_gap and row == cap_row:
                    ch = cap_glyph
                else:
                    ch = frac_block(v, row_bottom, row_top)
            elif mode == "shades":
                ch = shade_block(v, row_bottom, row_top)
            elif mode == "outline":
                ch = "─" if row_bottom < v <= row_top else " "
            else:
                ch = frac_block(v, row_bottom, row_top)
                is_tip = (row_bottom < v <= row_top)
            row_fragments[row].append(colorize(ch, i, row_norm, energy=v, is_tip=is_tip))
    return ["".join(parts) for parts in row_fragments]


# ─── Braille helpers ─────────────────────────────────────────────────────────
# 4-row × 2-col dot-bit table: _BRAILLE_BIT[row][col] → bitmask
_BRAILLE_BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]

def _scatter_hash(seed, y, x, frame):
    """Fast deterministic hash for stochastic braille stipple."""
    h = (seed ^ (y * 2654435761) ^ (x * 2246822519) ^ (frame * 1013904223)) & 0xFFFFFFFF
    h ^= (h >> 16)
    h = (h * 0x45d9f3b) & 0xFFFFFFFF
    h ^= (h >> 16)
    return (h & 0xFF) / 255.0


# ─── Flame visualizer ────────────────────────────────────────────────────────
def flame_render_lines(bars, height, width, state, use_color=True, game_tag=None):
    """Doom-fire: spectrum feeds heat at the bottom, propagates upward via braille 4×2 subgrid."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    dot_rows = height * 4
    dot_cols = width * 2
    n_bars = len(bars)

    if state["heat"] is None or state["rows"] != dot_rows or state["cols"] != dot_cols:
        state["heat"] = [0.0] * (dot_rows * dot_cols)
        state["rows"] = dot_rows
        state["cols"] = dot_cols

    heat = state["heat"]
    rng = state["rng"]
    state["frame"] = state.get("frame", 0) + 1
    frame = state["frame"]

    # Seed bottom row from interpolated spectrum bars with sparkle
    last_bar = n_bars - 1
    for x in range(dot_cols):
        pos = x / max(1, dot_cols - 1) * last_bar
        lo = int(pos); hi = min(lo + 1, last_bar)
        src = bars[lo] * (1.0 - (pos - lo)) + bars[hi] * (pos - lo)
        rng = (rng * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        sparkle = ((rng >> 33) % 100) / 100.0 * 0.20
        # No floor: quiet = near-zero flame, loud = tall flame.
        # Sparkle scales with signal so silence is nearly dark.
        heat[x] = min(src + sparkle * (0.25 + src), 1.0)

    # Propagate heat upward: lateral wind jitter + height-dependent decay
    # Normalise decay to dot_rows so flame height scales consistently at any spectrum height.
    _decay_scale = 32.0 / max(1, dot_rows)
    for y in range(dot_rows - 1, 0, -1):
        decay_base = (0.010 + 0.028 * (y / max(1, dot_rows - 1))) * _decay_scale
        for x in range(dot_cols):
            rng = (rng * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            r = rng >> 33
            offset = int(r % 3) - 1
            decay_jitter = ((r >> 2) % 100) / 100.0 * 0.018 * _decay_scale
            sx = max(0, min(dot_cols - 1, x + offset))
            heat[y * dot_cols + x] = max(0.0, heat[(y - 1) * dot_cols + sx] - decay_base - decay_jitter)

    state["rng"] = rng

    # Tier colors: hot core and body follow time-of-day gradient for non-AC modes.
    if game_tag and game_tag != "ALL":
        hot_color = 118
        body_color = 82
    else:
        hot_color = gradient_at(_clrs._active_tod_grad, 95)
        body_color = gradient_at(_clrs._active_tod_grad, 35)

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(width):
            braille = 0x2800
            cell_tier = -1
            for dr in range(4):
                for dc in range(2):
                    hy = dot_rows - 1 - (row * 4 + dr)  # bottom = heat source
                    hx = col * 2 + dc
                    h = heat[hy * dot_cols + hx]
                    if h < 0.10:
                        continue
                    if h < 0.25 and _scatter_hash(0, row * 4 + dr, hx, frame) > h * 4:
                        continue
                    braille |= _BRAILLE_BIT[dr][dc]
                    tier = 0 if h >= 0.55 else 1
                    if tier > cell_tier:
                        cell_tier = tier
            ch = chr(braille)
            if use_color and cell_tier >= 0:
                color = hot_color if cell_tier == 0 else body_color
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out


# ─── Braille waveform (oscilloscope) ─────────────────────────────────────────
def braille_wave_lines(bars, height, width, use_color=True, game_tag=None):
    """Braille oscilloscope: frequency bars mapped to a spatial waveform curve."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    dot_rows = height * 4
    dot_cols = width * 2
    n = len(bars)
    center = dot_rows / 2.0
    amplitude = dot_rows * 0.42

    # Interpolate bar amplitudes to dot-column Y positions
    ypos = []
    for x in range(dot_cols):
        pos = x / max(1, dot_cols - 1) * (n - 1)
        lo = int(pos); hi = min(lo + 1, n - 1)
        sample = bars[lo] * (1.0 - (pos - lo)) + bars[hi] * (pos - lo)
        sample = (sample - 0.5) * 2.0  # map 0..1 → -1..+1
        y = int(center - sample * amplitude + 0.5)
        ypos.append(max(0, min(dot_rows - 1, y)))

    # Rasterize waveform with line interpolation between adjacent points
    grid = [False] * (dot_rows * dot_cols)
    for x in range(dot_cols):
        y = ypos[x]
        grid[y * dot_cols + x] = True
        if x > 0:
            for fy in range(min(ypos[x - 1], y), max(ypos[x - 1], y) + 1):
                grid[fy * dot_cols + x] = True

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(width):
            braille = 0x2800
            has_dot = False
            for dr in range(4):
                for dc in range(2):
                    if grid[(row * 4 + dr) * dot_cols + col * 2 + dc]:
                        braille |= _BRAILLE_BIT[dr][dc]
                        has_dot = True
            ch = chr(braille)
            if use_color and has_dot:
                disp = abs(ypos[col * 2] - center) / max(1.0, amplitude)
                color = spectrum_color(col, width, row_norm=min(1.0, disp), game_tag=game_tag)
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out


# ─── Braille Lissajous / XY scope ────────────────────────────────────────────
def braille_scope_lines(bars, height, width, frame, use_color=True, game_tag=None):
    """Lissajous XY scope: low-freq bands as X axis, high-freq as Y, phase-animated."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    dot_rows = height * 4
    dot_cols = width * 2
    n = len(bars)
    grid = [False] * (dot_rows * dot_cols)

    if n >= 4:
        mid = n // 2
        x_bands = bars[:mid]
        y_bands = bars[mid:]
        n_pts = min(200, min(len(x_bands), len(y_bands)))
        phase = math.sin(frame * 0.018) * 0.28

        prev_dx = prev_dy = -1
        for k in range(n_pts):
            t = k / max(1, n_pts - 1)
            xi = t * (len(x_bands) - 1)
            yi_raw = (t + phase) % 1.0 * (len(y_bands) - 1)

            xlo = int(xi); xhi = min(xlo + 1, len(x_bands) - 1)
            xv = x_bands[xlo] * (1.0 - (xi - xlo)) + x_bands[xhi] * (xi - xlo)

            ylo = int(yi_raw); yhi = min(ylo + 1, len(y_bands) - 1)
            yv = y_bands[ylo] * (1.0 - (yi_raw - ylo)) + y_bands[yhi] * (yi_raw - ylo)

            dx = max(0, min(dot_cols - 1, int(xv * (dot_cols - 1) + 0.5)))
            dy = max(0, min(dot_rows - 1, int((1.0 - yv) * (dot_rows - 1) + 0.5)))
            grid[dy * dot_cols + dx] = True

            if prev_dx >= 0:
                ddx, ddy = dx - prev_dx, dy - prev_dy
                steps = max(abs(ddx), abs(ddy))
                if 0 < steps < 24:
                    for s in range(1, steps):
                        mx = prev_dx + ddx * s // steps
                        my = prev_dy + ddy * s // steps
                        if 0 <= mx < dot_cols and 0 <= my < dot_rows:
                            grid[my * dot_cols + mx] = True
            prev_dx, prev_dy = dx, dy

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(width):
            braille = 0x2800
            has_dot = False
            for dr in range(4):
                for dc in range(2):
                    if grid[(row * 4 + dr) * dot_cols + col * 2 + dc]:
                        braille |= _BRAILLE_BIT[dr][dc]
                        has_dot = True
            ch = chr(braille)
            if use_color and has_dot:
                color = spectrum_color(col, width, game_tag=game_tag)
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out


def resample_bars(bars, width):
    """Linear resample spectrum bars to a target column count."""
    if not bars or width <= 0:
        return []
    n = len(bars)
    if n == width:
        return [max(0.0, min(1.0, v)) for v in bars]
    out = []
    for i in range(width):
        pos = i / max(1, width - 1) * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        v = bars[lo] * (1.0 - (pos - lo)) + bars[hi] * (pos - lo)
        out.append(max(0.0, min(1.0, v)))
    return out

def butterfly_render_lines(bars, height, width, state, use_color=True, game_tag=None):
    """Symmetric Rorschach pattern — inspired by cliamp VisButterfly (algorithm only)."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    dot_rows = height * 4
    dot_cols = width * 2
    center_x = dot_cols // 2
    band_count = len(bars)
    frame = state.get("frame", 0)
    state["frame"] = frame + 1
    grid = [False] * (dot_rows * dot_cols)

    for dy in range(dot_rows):
        band_f = dy / max(1, dot_rows - 1) * (band_count - 1)
        bi = int(band_f)
        frac = band_f - bi
        if bi >= band_count - 1:
            energy = bars[band_count - 1]
        else:
            energy = bars[bi] * (1.0 - frac) + bars[bi + 1] * frac

        t = frame * 0.08 + dy * 0.3
        wobble = math.sin(t) * 0.15
        wing_width = int(center_x * (energy + wobble) * 0.9)

        for dx in range(max(0, wing_width)):
            norm = dx / max(1, wing_width)
            threshold = (1.0 - norm * norm) * energy
            if norm > 0.6:
                threshold *= 0.5 + 0.5 * math.sin(frame * 0.1 + dy * 0.5 + dx * 0.3)
            if _scatter_hash(bi, dy, dx, frame // 3) < threshold:
                rx = center_x + dx
                if rx < dot_cols:
                    grid[dy * dot_cols + rx] = True
                lx = center_x - 1 - dx
                if lx >= 0:
                    grid[dy * dot_cols + lx] = True

        if energy > 0.05:
            grid[dy * dot_cols + center_x] = True
            if center_x > 0:
                grid[dy * dot_cols + center_x - 1] = True

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(width):
            braille = 0x2800
            has_dot = False
            for dr in range(4):
                for dc in range(2):
                    if grid[(row * 4 + dr) * dot_cols + col * 2 + dc]:
                        braille |= _BRAILLE_BIT[dr][dc]
                        has_dot = True
            ch = chr(braille)
            if use_color and has_dot:
                row_norm = row / max(1, height - 1)
                color = spectrum_color(col, width, row_norm, game_tag=game_tag)
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out


def led_matrix_lines(bars, height, width, peak_bars=None, use_color=True, game_tag=None):
    """Winamp-style LED columns with falling peak caps (▄ body, ▀ peak)."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    bar_w, bar_gap = 2, 1
    n_bars = max(1, (width + bar_gap) // (bar_w + bar_gap))
    body = resample_bars(bars, n_bars)
    peak = resample_bars(peak_bars if peak_bars else bars, n_bars)
    render_w = n_bars * (bar_w + bar_gap) - bar_gap
    pad = max(0, width - render_w)
    height_f = float(height)

    lines_out = []
    for row in range(height):
        row_bottom = (height - 1 - row) / height_f
        rfb = height - 1 - row
        parts = [" "] * pad
        for b in range(n_bars):
            lit = int(math.floor(body[b] * height_f + 1e-6))
            peak_seg = int(math.floor(peak[b] * height_f + 1e-6))
            peak_seg = min(height - 1, peak_seg)
            show_peak = peak[b] > body[b] + 0.5 / height_f and peak_seg >= lit
            if rfb < lit:
                glyph = "▄"
            elif show_peak and rfb == peak_seg:
                glyph = "▀"
            else:
                glyph = " "
            cell = glyph * bar_w
            if use_color and glyph != " ":
                parts.append(c256(cell, spectrum_color(b, n_bars, row_bottom, game_tag=game_tag)))
            else:
                parts.append(cell)
            if b < n_bars - 1:
                parts.append(" " * bar_gap)
        lines_out.append("".join(parts))
    return lines_out


def matrix_rain_lines(bars, height, width, state, use_color=True, game_tag=None):
    """Falling character rain — inspired by cliamp VisMatrix (algorithm only)."""
    if height <= 0 or width <= 0 or not bars:
        return [" " * max(1, width)] * max(1, height)

    # Each column occupies 2 terminal cells (char + gap), so resample to width//2 streams.
    # This ensures the rendered output fills exactly `width` columns.
    n_cols = max(1, (width + 1) // 2)
    sampled = resample_bars(bars, n_cols)
    frame = state.get("frame", 0)
    state["frame"] = frame + 1
    chars = MATRIX_RAIN_CHARS
    n_chars = len(chars)

    lines_out = []
    for row in range(height):
        row_parts = []
        col = 0
        for b in range(n_cols):
            energy = sampled[b]
            seed = b * 7919 + 104729
            if _scatter_hash(b, 0, b, frame // 20) > energy * 1.5 + 0.1:
                row_parts.append(" ")
                col += 1
            else:
                speed = 2 + int(seed % 3)
                trail_len = 3 + int((seed // 7) % 3)
                cycle_len = height + trail_len + 4
                offset = int((seed // 13) % cycle_len)
                pos = (frame // speed + offset) % cycle_len
                dist = pos - row
                if dist < 0 or dist > trail_len:
                    row_parts.append(" ")
                else:
                    char_seed = seed ^ (row * 31 + (frame // 4) * 17)
                    ch = chars[char_seed % n_chars]
                    if use_color:
                        if dist == 0:
                            color = 255
                        elif dist <= 2:
                            color = 118 if (game_tag and game_tag != "ALL") else gradient_at(_clrs._active_tod_grad, 70)
                        else:
                            color = 34 if (game_tag and game_tag != "ALL") else gradient_at(_clrs._active_tod_grad, 20)
                        row_parts.append(c256(ch, color))
                    else:
                        row_parts.append(ch)
                col += 1
            if b < n_cols - 1:
                row_parts.append(" ")
                col += 1
        # col now tracks visible width accurately; pad to fill any remainder
        line = "".join(row_parts)
        if col < width:
            line += " " * (width - col)
        lines_out.append(line)
    return lines_out


def heartbeat_render_lines(bars, height, width, state, use_color=True, game_tag=None):
    """Scrolling ECG trace derived from bass energy (cliamp-style monitor look)."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)

    dot_rows = height * 4
    dot_cols = width * 2
    buf = state.get("buf")
    if buf is None or len(buf) != dot_cols:
        buf = [0.0] * dot_cols
        state["buf"] = buf
        state["prev_bass"] = 0.3
        state["baseline"] = 0.3
        state["ring"] = 0.0
        state["ring_ph"] = 0.0

    n = len(bars) if bars else 0
    if n > 0:
        bass_n = max(1, n // 6)
        bass = sum(bars[:bass_n]) / bass_n
        treble_n = max(1, n // 6)
        treble = sum(bars[-treble_n:]) / treble_n
        mid_end = max(1, n // 2)
        mids = sum(bars[bass_n:mid_end]) / max(1, mid_end - bass_n) if mid_end > bass_n else 0.0

        prev = state.get("prev_bass", 0.3)
        rise = max(0.0, bass - prev)
        # Slow-moving prev so sudden bass hits register as large, persistent spikes
        state["prev_bass"] = bass * 0.12 + prev * 0.88

        # Very slow center tracker so trace auto-levels to current music energy
        baseline = state.get("baseline", 0.3)
        state["baseline"] = bass * 0.04 + baseline * 0.96

        # ECG: bass deflects up, treble flicks down (hi-hats/cymbals add QRS-like dips)
        sample = (bass - state["baseline"]) * 2.0 + mids * 0.25 - treble * 0.2 + rise * 5.5

        # Ring oscillator: charges on each beat, decays between — creates realistic
        # post-beat ringing rather than a one-shot sine that cuts off abruptly
        ring = state.get("ring", 0.0) * 0.82 + rise * 2.5
        ring_ph = state.get("ring_ph", 0.0) + 1.8
        state["ring"] = ring
        state["ring_ph"] = ring_ph
        sample += ring * 0.55 * math.sin(ring_ph)

        sample = max(-1.0, min(1.0, sample))
    else:
        sample = 0.0

    buf.pop(0)
    buf.append(sample)

    center_y = dot_rows / 2.0
    amplitude = dot_rows * 0.44
    ypos = []
    for x in range(dot_cols):
        s = buf[x]
        shaped = s * abs(s)  # soft clip: exaggerates peaks, compresses near-zero
        y = int(center_y - shaped * amplitude + 0.5)
        ypos.append(max(0, min(dot_rows - 1, y)))

    grid = [False] * (dot_rows * dot_cols)
    base_y = dot_rows // 2
    for x in range(dot_cols):
        y = ypos[x]
        grid[y * dot_cols + x] = True
        if x > 0:
            lo, hi = min(y, ypos[x - 1]), max(y, ypos[x - 1])
            for fy in range(lo, hi + 1):
                grid[fy * dot_cols + x] = True
    for x in range(dot_cols):
        if not grid[base_y * dot_cols + x] and (x // 6) % 2 == 0:
            grid[base_y * dot_cols + x] = True

    if game_tag and game_tag != "ALL":
        trace_hi = 196
        trace_lo = 160
        base_color = 46
    else:
        trace_hi = gradient_at(_clrs._active_tod_grad, 95)
        trace_lo = gradient_at(_clrs._active_tod_grad, 60)
        base_color = gradient_at(_clrs._active_tod_grad, 20)

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(width):
            braille = 0x2800
            has_trace = False
            max_disp = 0.0
            for dr in range(4):
                for dc in range(2):
                    dy = row * 4 + dr
                    dx = col * 2 + dc
                    if grid[dy * dot_cols + dx]:
                        braille |= _BRAILLE_BIT[dr][dc]
                        if dy != base_y:
                            has_trace = True
                            disp = abs(dy - center_y) / max(1.0, center_y)
                            if disp > max_disp:
                                max_disp = disp
            ch = chr(braille)
            if use_color and braille != 0x2800:
                if has_trace:
                    # Brighter where trace is farthest from center (peak of deflection)
                    color = trace_hi if max_disp > 0.4 else trace_lo
                else:
                    color = base_color
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out



def braille_spectrum_lines(bars, height, width, peak_bars=None, use_color=True, game_tag=None):
    """
    Btop-style two-value-per-char braille spectrum.

    Each terminal character encodes TWO adjacent frequency bars using the
    left (dots 1-4) and right (dots 5-8) columns of a Braille cell.  This
    doubles the number of bars visible in the same terminal width while
    keeping 4× sub-row resolution per character row — exactly how btop's
    Graph class packs data into braille_up/braille_down symbols.

    Peak caps are drawn as a single bright dot at the top of each bar pair
    when peak_bars is provided.
    """
    if not bars or height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)

    n_pairs = width          # one braille char per pair
    n_samples = n_pairs * 2  # two bars encoded per char
    dot_rows = height * 4    # 4 dot-rows per terminal row

    # Interpolate bars to exactly n_samples positions
    def sample(src, idx):
        n = len(src)
        if n == 0:
            return 0.0
        pos = idx / max(1, n_samples - 1) * (n - 1)
        lo = int(pos); hi = min(lo + 1, n - 1)
        return max(0.0, min(1.0, src[lo] * (1.0 - (pos - lo)) + src[hi] * (pos - lo)))

    bar_fill  = [int(sample(bars,      i) * dot_rows + 0.5) for i in range(n_samples)]
    peak_fill = [int(sample(peak_bars, i) * dot_rows + 0.5) for i in range(n_samples)] if peak_bars else None

    lines_out = []
    for row in range(height):
        row_str = []
        for col in range(n_pairs):
            braille = 0x2800
            peak_dot = [False, False]   # whether the peak cap dot appears in this cell

            for dc in range(2):          # dc=0 → left column, dc=1 → right column
                bar_idx = col * 2 + dc
                fill = bar_fill[bar_idx]

                # Peak cap: a single dot one level above the bar body
                if peak_fill is not None:
                    pf = peak_fill[bar_idx]
                    if pf > fill:
                        # Which dot row does the cap land on inside this cell?
                        cap_dot_from_bottom = pf - 1          # 0-based from bottom
                        cap_row_from_top = dot_rows - 1 - cap_dot_from_bottom
                        cap_dr = cap_row_from_top - row * 4   # local row within cell
                        if 0 <= cap_dr < 4:
                            braille |= _BRAILLE_BIT[cap_dr][dc]
                            peak_dot[dc] = True

                # Bar body: fill dots from the bottom of this cell upward
                for dr in range(4):
                    dot_from_bottom = dot_rows - 1 - (row * 4 + dr)
                    if dot_from_bottom < fill:
                        braille |= _BRAILLE_BIT[dr][dc]

            ch = chr(braille)
            if use_color and braille != 0x2800:
                # Btop-style: color by horizontal frequency position
                color = spectrum_color(col, n_pairs, game_tag=game_tag)
                row_str.append(c256(ch, color))
            else:
                row_str.append(" " if braille == 0x2800 else ch)

        lines_out.append("".join(row_str))
    return lines_out


import math, os, random, time
from array import array

from ac_ui.audio_snapshot import (
    analyze_audio_features,
    conditioned_waveform_mono, conditioned_waveform_stereo,
)
from ac_ui.colors import (
    ASCII_ONLY, USE_COLOR, c256, paint, sgr, RESET, spectrum_color, theme_visualizer_color,
    theme_visualizer_gradient, gradient_at, smoothing_alpha_ms, visible_len,
)
from ac_ui.meters import meter_bar

# Optional compiled hot paths for the feedback visualizers (kaleido/liquid/
# plasma). Built via build_native.py; absent on machines without a compiler, in
# which case the pure-Python helpers below are used instead.
try:
    from ac_ui import _vizfast as _vizfast
except Exception:  # pragma: no cover - import guard
    _vizfast = None
from ac_ui.constants import (
    VIS_BAR_BLOCKS, VIS_SHADE_BLOCKS, VIS_PEAK_GLYPHS,
    CAVA_HEIGHT, MATRIX_RAIN_CHARS, VIS_SCALE, VIS_GAMMA,
)

_NATIVE_FEEDBACK_BUFFERS = bool(
    _vizfast is not None
    and hasattr(_vizfast, "feedback_transform_into_buf")
    and hasattr(_vizfast, "braille_field_buf")
    and hasattr(_vizfast, "kaleido_overlay_geom_buf")
    and hasattr(_vizfast, "flash_disc_buf")
)
# Hoisted capability checks (computed once, not per frame in the hot render path).
_HAS_OVERLAY_GEOM_BUF = _vizfast is not None and hasattr(_vizfast, "kaleido_overlay_geom_buf")
_HAS_OVERLAY_GEOM_BUF_TYPED = _vizfast is not None and hasattr(_vizfast, "kaleido_overlay_geom_buf_typed")
_HAS_OVERLAY = _vizfast is not None and hasattr(_vizfast, "kaleido_overlay")

# --- Geiss-style cached warp map (temporal coherence) -----------------------
# The per-pixel feedback warp geometry (swirl/pinch/warp/mirror trig) barely
# moves frame-to-frame because its parameters are slow/continuous functions of
# the audio envelope. So we precompute the dst->src "warp map" once (Geiss's
# trick), reuse it across frames, and only regenerate it when the geometry
# params drift past a threshold or a frame ceiling (K) is hit. The live
# decay/hue_shift stay per-frame in the cheap gather. Gated by env so the
# default render path is byte-for-byte unchanged until we promote it.
_WARP_CACHE = os.environ.get("AC_UI_WARP_CACHE", "1") not in ("0", "", "false", "no")
_NATIVE_WARP_CACHE = bool(
    _NATIVE_FEEDBACK_BUFFERS
    and hasattr(_vizfast, "build_warp_map_buf")
    and hasattr(_vizfast, "feedback_gather_buf")
)
try:
    # Frame ceiling: rebuild at least this often even if the warp looks static.
    _WARP_CACHE_KMAX = max(1, int(os.environ.get("AC_UI_WARP_KMAX", "12")))
except ValueError:
    _WARP_CACHE_KMAX = 12
try:
    # Weighted-L1 geometry drift that triggers a rebuild. 0.02 ~= a couple of
    # source pixels of accumulated warp movement — the smooth/fidelity sweet spot
    # from bench_warp_sweep.py (smaller = more faithful + more rebuilds).
    _WARP_CACHE_THRESH = float(os.environ.get("AC_UI_WARP_THRESH", "0.02"))
except ValueError:
    _WARP_CACHE_THRESH = 0.02
try:
    # Spread each warp-map rebuild across this many frames (Geiss's "a row at a
    # time in the background") so no single frame pays the full ~15ms build.
    _WARP_BUILD_FRAMES = max(1, int(os.environ.get("AC_UI_WARP_BUILD_FRAMES", "8")))
except ValueError:
    _WARP_BUILD_FRAMES = 8


# --- Adaptive low-resolution feedback grid for large terminals --------------
# At large terminal sizes the feedback/overlay/braille all scale with the dot
# grid (height*4 x width*2). Halving the VERTICAL dot count (height*2) halves
# that upstream work. Because the kaleido works in normalized [-1,1] space, the
# shape/aspect is unchanged — only vertical detail coarsens (braille replicates
# each field row into two dot-rows). OFF by default (full quality) — opt into the
# low-power path with AC_UI_VIS_LOWRES=1 (or "auto" to size-gate it).
_VIS_LOWRES = os.environ.get("AC_UI_VIS_LOWRES", "off").lower()
try:
    _VIS_LOWRES_MIN_CELLS = int(os.environ.get("AC_UI_VIS_LOWRES_CELLS", "50000"))
except ValueError:
    _VIS_LOWRES_MIN_CELLS = 50000
try:
    # Dot-cell cutoff for the cheaper large-grid tunnel path (drops the feedback
    # kaleidoscope mirror + treble warp — which visibly changes the tunnel into a
    # plain swirl). DEFAULT OFF (huge cutoff) so the full symmetric tunnel always
    # renders; set AC_UI_KALEIDO_LARGE_FIELD_CELLS=12000 to re-enable the cheap
    # path on weak terminals/hardware.
    _KALEIDO_LARGE_FIELD_CELLS = int(os.environ.get("AC_UI_KALEIDO_LARGE_FIELD_CELLS", "1000000000"))
except ValueError:
    _KALEIDO_LARGE_FIELD_CELLS = 1000000000
try:
    # Kaleido-specific low-res threshold. The tunnel remains legible a bit
    # earlier than the other feedback modes, so we let this one halve its
    # vertical field resolution sooner to flatten the size curve.
    _KALEIDO_LOWRES_MIN_CELLS = int(os.environ.get("AC_UI_KALEIDO_LOWRES_CELLS", "38000"))
except ValueError:
    _KALEIDO_LOWRES_MIN_CELLS = 38000
try:
    # Very large kaleido panes can drop to one field row per terminal row. This
    # is deliberately kaleido-only because it is visibly coarser.
    _KALEIDO_ULTRALOWRES_MIN_CELLS = int(os.environ.get("AC_UI_KALEIDO_ULTRALOWRES_CELLS", "90000"))
except ValueError:
    _KALEIDO_ULTRALOWRES_MIN_CELLS = 90000


def _vis_use_lowres(full_cells):
    """Whether to render the feedback field at half vertical resolution.

    ``full_cells`` is the full-resolution dot count (height*4 * width*2)."""
    if _VIS_LOWRES in ("0", "off", "false", "no"):
        return False
    if _VIS_LOWRES in ("1", "on", "true", "yes"):
        return True
    return full_cells >= _VIS_LOWRES_MIN_CELLS


def _kaleido_use_lowres(full_cells):
    """Kaleido tunnel can accept low-res a bit earlier than the generic modes."""
    return _kaleido_v_dots(full_cells) < 4


def _kaleido_v_dots(full_cells):
    """Vertical field resolution for kaleido_tunnel."""
    if _VIS_LOWRES in ("0", "off", "false", "no"):
        return 4
    if _VIS_LOWRES in ("1", "on", "true", "yes"):
        return 2
    if full_cells >= _KALEIDO_ULTRALOWRES_MIN_CELLS:
        return 1
    if full_cells >= _KALEIDO_LOWRES_MIN_CELLS:
        return 2
    return 4


def _warp_geom_drift(prev, cur):
    """Weighted L1 drift between two geometry-param tuples, in normalized coord
    units (~how far source samples move). Each param is weighted by its
    approximate displacement impact on the sampled coordinate."""
    # tuple order: zoom, rot, drift_x, drift_y, swirl, pinch, warp_amp, warp_phase
    return (
        abs(cur[0] - prev[0]) * 0.7      # zoom * typical radius
        + abs(cur[1] - prev[1]) * 0.7    # rot * typical radius
        + abs(cur[2] - prev[2])          # drift_x (direct)
        + abs(cur[3] - prev[3])          # drift_y (direct)
        + abs(cur[4] - prev[4]) * 0.4    # swirl
        + abs(cur[5] - prev[5]) * 0.5    # pinch
        + abs(cur[6] - prev[6])          # warp_amp
        + cur[6] * abs(cur[7] - prev[7]) # warp_phase scaled by its (tiny) amp
    )


def anim_clock(state, ref_fps=30.0, key="_anim"):
    """Frame-rate-independent animation clock for self-animating visualizers.

    Returns a float that advances at ``ref_fps`` units per second of wall-clock
    time, so motion driven by it keeps the *same visual speed* regardless of the
    actual render rate — a higher fps just samples it more finely (smoother),
    instead of running the animation faster.  Big gaps (pause/resize) are
    clamped so motion never lurches.  State is kept in the per-mode ``state``
    dict, so different modes don't interfere.
    """
    now = time.monotonic()
    last_key, clk_key = key + "_t", key
    last = state.get(last_key)
    state[last_key] = now
    clk = state.get(clk_key, 0.0)
    if last is not None:
        dt = now - last
        dt = 0.0 if dt < 0 else (0.25 if dt > 0.25 else dt)
        clk += dt * ref_fps
        state[clk_key] = clk
        # Per-frame motion scale: 1.0 at ref_fps, 0.5 at 2x ref_fps, etc. Lets
        # per-frame-accumulating effects (feedback zoom/rot/decay) advance by
        # wall-clock instead of per-frame, so they don't speed up at high fps.
        state[clk_key + "_d"] = dt * ref_fps
    return clk


def _motion_scale(state, key="_anim", lo=0.0, hi=1.5):
    """Frame-rate motion scale captured by the last anim_clock() call (1.0 at the
    30fps reference). Clamped so a slow/first frame can't lurch the feedback."""
    d = state.get(key + "_d", 1.0)
    return lo if d < lo else (hi if d > hi else d)


# ─── Display scaling (linear / log / sqrt / gamma) ────────────────────────────
# A monotonic 0..1 -> 0..1 curve applied to bar heights just before drawing so
# quiet passages stay visible.  It never touches the beat/energy features, which
# are computed from the raw bars upstream.  Precomputed as a LUT for speed.
def spectrum_scale_curve(v, scale, gamma=0.5):
    """Pure 0..1 -> 0..1 magnitude curve.  Unknown/"linear" passes through."""
    v = max(0.0, min(1.0, v))
    if scale == "log":
        return math.log1p(v * 9.0) / math.log(10.0)
    if scale == "sqrt":
        return v ** 0.5
    if scale == "gamma":
        return v ** max(0.05, min(4.0, gamma))
    return v


_SPECTRUM_SCALE_ACTIVE = VIS_SCALE in ("log", "sqrt", "gamma")
_SCALE_LUT = (
    tuple(spectrum_scale_curve(i / 256.0, VIS_SCALE, VIS_GAMMA) for i in range(257))
    if _SPECTRUM_SCALE_ACTIVE else ()
)


def apply_spectrum_scale(bars):
    """Return bars remapped through the active display-scaling curve.

    A no-op (returns the input unchanged) when scaling is set to "linear", so
    the common path stays allocation-free.
    """
    if not _SPECTRUM_SCALE_ACTIVE or not bars:
        return bars
    lut = _SCALE_LUT
    return [lut[int(max(0.0, min(1.0, v)) * 256)] for v in bars]

# 4-row x 2-col dot-bit table: _BRAILLE_BIT[row][col] -> bitmask
_BRAILLE_BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
_BRAILLE_CHAR_LUT = tuple(chr(0x2800 + i) for i in range(256))
_BRAILLE_HOT_THRESHOLD = 0.7
_BAR_BLOCKS = (" ", ".", ":", "-", "=", "+", "*", "#", "@") if ASCII_ONLY else VIS_BAR_BLOCKS
_SHADE_BLOCKS = (" ", ".", ":", "*", "#") if ASCII_ONLY else VIS_SHADE_BLOCKS
_PEAK_GLYPHS = ("'", "-", "~", "^") if ASCII_ONLY else VIS_PEAK_GLYPHS
_OUTLINE_GLYPH = "-" if ASCII_ONLY else "─"
_SPECTRUM_SOLID = "#" if ASCII_ONLY else "█"
_SPECTRUM_TRAIL = "." if ASCII_ONLY else "·"


def frac_block(level, row_bottom, row_top):
    if level >= row_top:
        return _BAR_BLOCKS[-1]
    if level > row_bottom:
        frac = (level - row_bottom) / max(0.001, row_top - row_bottom)
        idx = int(frac * (len(_BAR_BLOCKS) - 1))
        idx = max(0, min(len(_BAR_BLOCKS) - 1, idx))
        return _BAR_BLOCKS[idx]
    return " "

def shade_block(level, row_bottom, row_top):
    if level >= row_top:
        return _SHADE_BLOCKS[-1]
    if level > row_bottom:
        frac = (level - row_bottom) / max(0.001, row_top - row_bottom)
        idx = int(frac * (len(_SHADE_BLOCKS) - 1) + 0.25)
        idx = max(1, min(len(_SHADE_BLOCKS) - 1, idx))
        return _SHADE_BLOCKS[idx]
    return " "

def peak_cap(level, height):
    dot_rows = max(1, height * len(_PEAK_GLYPHS))
    dot_y = int(round((1.0 - max(0.0, min(1.0, level))) * (dot_rows - 1)))
    row = dot_y // len(_PEAK_GLYPHS)
    glyph = _PEAK_GLYPHS[dot_y % len(_PEAK_GLYPHS)]
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

    # The spectrum colour for a (row, value) cell is just
    #   gradient_at(spectrum, clamp(int(row_norm*100) + int(value*20)))
    # i.e. an index in 0..100, so precompute the 101 escape prefixes ONCE per
    # frame instead of recomputing the gradient for every cell (~height*n times).
    _esc_lut = None
    _tip_esc_lut = None
    if use_color:
        _active = bool(game_tag and game_tag != "ALL")
        _spectrum = theme_visualizer_gradient("spectrum", active=_active)
        _esc_lut = _gradient_escape_lut(_spectrum)
        if not game_tag:
            _tip_grad = theme_visualizer_gradient("tip", active=False)
            _tip_esc_lut = _gradient_escape_lut(_tip_grad, bold=True)

    row_fragments = []
    # Per-column values that don't vary by row — hoisted out of the inner loop.
    clamped = [0.0 if b < 0.0 else (1.0 if b > 1.0 else b) for b in bars]
    col_boost = [int(cv * 20) for cv in clamped]          # spectrum colour boost
    _tip_special = _tip_esc_lut is not None
    _peaks_min_gap = max(0.01, 0.5 / max(1, height * len(VIS_PEAK_GLYPHS)))
    col_pv = col_cap = col_peak_row = col_trail_row = None
    if mode == "peaks":
        col_pv = [value_at(peak_bars, i, clamped[i]) for i in range(n)]
        col_cap = [peak_cap(pv, height) for pv in col_pv]   # (cap_row, cap_glyph)
    elif mode == "spectrum":
        col_peak_row = [(height - 1) - int(value_at(peak_bars, i, clamped[i]) * (height - 1) + 0.5) for i in range(n)]
        col_trail_row = [(height - 1) - int(value_at(trail_bars, i, clamped[i]) * (height - 1) + 0.5) for i in range(n)]

    for row in range(height):
        row_bottom = (height - 1 - row) / max(1, height)
        row_top = (height - row) / max(1, height)
        row_base = int(row_bottom * 100)
        frags = []
        for i in range(n):
            v = clamped[i]
            is_tip = False
            if mode == "spectrum":
                if row == col_peak_row[i]:
                    ch = _SPECTRUM_SOLID
                elif row >= col_trail_row[i]:
                    ch = _SPECTRUM_TRAIL
                else:
                    ch = " "
            elif mode == "peaks":
                cap_row, cap_glyph = col_cap[i]
                if col_pv[i] > v + _peaks_min_gap and row == cap_row:
                    ch = cap_glyph
                else:
                    ch = frac_block(v, row_bottom, row_top)
            elif mode == "shades":
                ch = shade_block(v, row_bottom, row_top)
            elif mode == "outline":
                ch = _OUTLINE_GLYPH if row_bottom < v <= row_top else " "
            else:
                ch = frac_block(v, row_bottom, row_top)
                is_tip = (row_bottom < v <= row_top)
            # Inline colouring (avoids a per-cell function call).
            if not use_color or ch == " ":
                frags.append(ch)
            elif is_tip and _tip_special:
                frags.append(_tip_esc_lut[80 + col_boost[i]] + ch + RESET)
            else:
                idx = row_base + col_boost[i]
                frags.append(_esc_lut[100 if idx > 100 else idx] + ch + RESET)
        row_fragments.append("".join(frags))
    return row_fragments


# ─── Braille helpers ─────────────────────────────────────────────────────────
# 4-row × 2-col dot-bit table: _BRAILLE_BIT[row][col] → bitmask
_BRAILLE_BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]

# Bottom-up fill masks per column: _BRAILLE_BODY_MASK[dc][k] = OR of the lowest
# k dots (k in 0..4). Lets the spectrum bar body fill a cell with one LUT lookup
# instead of a 4-iteration per-dot loop.
_BRAILLE_BODY_MASK = [
    [
        0,
        _BRAILLE_BIT[3][dc],
        _BRAILLE_BIT[3][dc] | _BRAILLE_BIT[2][dc],
        _BRAILLE_BIT[3][dc] | _BRAILLE_BIT[2][dc] | _BRAILLE_BIT[1][dc],
        _BRAILLE_BIT[3][dc] | _BRAILLE_BIT[2][dc] | _BRAILLE_BIT[1][dc] | _BRAILLE_BIT[0][dc],
    ]
    for dc in range(2)
]


_GRAD_ESC_LUT_CACHE = {}


def _gradient_escape_lut(grad, *, bold=False):
    """Memoize ANSI escape prefixes for a 0..100 gradient ramp."""
    key = (grad, bold)
    cached = _GRAD_ESC_LUT_CACHE.get(key)
    if cached is not None:
        return cached
    lut = tuple(sgr(fg=gradient_at(grad, k), bold=bold) for k in range(101))
    _GRAD_ESC_LUT_CACHE[key] = lut
    return lut


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
    last_col = dot_cols - 1

    if state.get("heat") is None or state.get("rows") != dot_rows or state.get("cols") != dot_cols:
        state["heat"] = [0.0] * (dot_rows * dot_cols)
        state["rows"] = dot_rows
        state["cols"] = dot_cols
    if state.get("seed_key") != (dot_cols, n_bars):
        last_bar = max(0, n_bars - 1)
        seed_lo = [0] * dot_cols
        seed_frac = [0.0] * dot_cols
        if last_bar > 0:
            span = float(max(1, dot_cols - 1))
            for x in range(dot_cols):
                pos = x / span * last_bar
                lo = int(pos)
                if lo >= last_bar:
                    lo = last_bar
                    frac = 0.0
                else:
                    frac = pos - lo
                seed_lo[x] = lo
                seed_frac[x] = frac
        state["seed_key"] = (dot_cols, n_bars)
        state["seed_lo"] = seed_lo
        state["seed_frac"] = seed_frac
    if state.get("decay_rows") != dot_rows:
        decay_scale = 32.0 / max(1, dot_rows)
        denom = float(max(1, dot_rows - 1))
        state["decay_rows"] = dot_rows
        state["decay_jitter_scale"] = 0.018 * decay_scale
        state["decay_by_row"] = [
            (0.010 + 0.028 * (y / denom)) * decay_scale
            for y in range(dot_rows)
        ]

    heat = state["heat"]
    seed_lo = state["seed_lo"]
    seed_frac = state["seed_frac"]
    decay_by_row = state["decay_by_row"]
    decay_jitter_scale = state["decay_jitter_scale"]
    rng = state.get("rng", 0xF1A3C0DE0BADCAFE)
    state["frame"] = state.get("frame", 0) + 1
    frame = state["frame"]

    # Seed bottom row from interpolated spectrum bars with sparkle
    for x in range(dot_cols):
        lo = seed_lo[x]
        frac = seed_frac[x]
        if frac > 0.0:
            src = bars[lo] * (1.0 - frac) + bars[lo + 1] * frac
        else:
            src = bars[lo]
        rng = (rng * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        sparkle = ((rng >> 33) % 100) / 100.0 * 0.20
        # No floor: quiet = near-zero flame, loud = tall flame.
        # Sparkle scales with signal so silence is nearly dark.
        value = src + sparkle * (0.25 + src)
        heat[x] = 1.0 if value > 1.0 else value

    # Propagate heat upward: lateral wind jitter + height-dependent decay
    # Normalise decay to dot_rows so flame height scales consistently at any spectrum height.
    for y in range(dot_rows - 1, 0, -1):
        decay_base = decay_by_row[y]
        dst_row = y * dot_cols
        src_row = dst_row - dot_cols
        for x in range(dot_cols):
            rng = (rng * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            r = rng >> 33
            sx = x + int(r % 3) - 1
            if sx < 0:
                sx = 0
            elif sx > last_col:
                sx = last_col
            decay_jitter = ((r >> 2) % 100) / 100.0 * decay_jitter_scale
            value = heat[src_row + sx] - decay_base - decay_jitter
            heat[dst_row + x] = value if value > 0.0 else 0.0

    state["rng"] = rng

    hot_color = body_color = None
    if use_color:
        flame_grad = theme_visualizer_gradient("flame", active=bool(game_tag and game_tag != "ALL"))
        hot_color = gradient_at(flame_grad, 95)
        body_color = gradient_at(flame_grad, 35)

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
            ch = _BRAILLE_CHAR_LUT[braille - 0x2800]
            if use_color and cell_tier >= 0:
                color = hot_color if cell_tier == 0 else body_color
                row_str.append(c256(ch, color))
            else:
                row_str.append(ch)
        lines_out.append("".join(row_str))
    return lines_out


# ─── Braille waveform (oscilloscope) ─────────────────────────────────────────
def braille_wave_lines(bars, height, width, use_color=True, game_tag=None, snapshot=None, state=None):
    """Braille oscilloscope: prefer true waveform samples, fall back to bars."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)

    if snapshot is not None and snapshot.has_waveform:
        state = state or {}
        dot_rows = height * 4
        dot_cols = width * 2
        samples = conditioned_waveform_mono(snapshot, dot_cols, state, "wave_gain")
        if samples:
            features = snapshot.features
            inten, hue = _feedback_transform(
                state,
                dot_rows,
                dot_cols,
                decay=0.74 + features.treble_att * 0.04,
                zoom=1.000 + features.overall * 0.002,
                drift_x=0.0,
                hue_shift=0.25 + features.treble_att * 0.6,
            )
            center = (dot_rows - 1) / 2.0
            amplitude = dot_rows * (0.26 + features.bass_att * 0.08)
            prev_x = 0.0
            prev_y = center - samples[0] * amplitude
            for x in range(1, dot_cols):
                y = center - samples[x] * amplitude
                steps = max(1, int(abs(y - prev_y)) + 1)
                hue_now = int((24 + x / max(1, dot_cols - 1) * 58 + abs(samples[x]) * 12) % 101)
                for s in range(steps + 1):
                    t = s / steps
                    px = prev_x + (x - prev_x) * t
                    py = prev_y + (y - prev_y) * t
                    _plot(inten, hue, dot_rows, dot_cols, px, py, 0.95, hue_now)
                    _plot(inten, hue, dot_rows, dot_cols, px, py + 1, 0.38, hue_now)
                prev_x = float(x)
                prev_y = y
            _store_feedback(state, inten, hue)
            grad = _gradient_for(game_tag) if use_color else None
            return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                                  use_color=use_color, threshold=0.06)

    if not bars:
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
def braille_scope_lines(bars, height, width, frame, use_color=True, game_tag=None, snapshot=None, state=None):
    """Lissajous XY scope: prefer real stereo PCM, fall back to bar-derived XY."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)

    if snapshot is not None and snapshot.has_waveform:
        state = state or {}
        dot_rows = height * 4
        dot_cols = width * 2
        point_count = min(240, max(96, dot_cols + 48))
        left, right = conditioned_waveform_stereo(snapshot, point_count, state, "scope_gain")
        if left and right:
            features = snapshot.features
            inten, hue = _feedback_transform(
                state,
                dot_rows,
                dot_cols,
                decay=0.80 + features.overall * 0.04,
                zoom=1.000 + features.width * 0.004,
                rot=features.treble_att * 0.005,
                hue_shift=0.45 + features.width * 0.8 + features.treble_att * 0.4,
            )
            cx = (dot_cols - 1) / 2.0
            cy = (dot_rows - 1) / 2.0
            x_amp = dot_cols * (0.17 + features.width * 0.18)
            y_amp = dot_rows * (0.27 + features.bass_att * 0.08)
            prev_x = cx + left[0] * x_amp
            prev_y = cy - right[0] * y_amp
            for idx in range(1, min(len(left), len(right))):
                x = cx + left[idx] * x_amp
                y = cy - right[idx] * y_amp
                steps = max(1, int(max(abs(x - prev_x), abs(y - prev_y))) + 1)
                hue_now = int((48 + idx / max(1, len(left) - 1) * 42 + features.width * 18) % 101)
                for s in range(steps + 1):
                    t = s / steps
                    px = prev_x + (x - prev_x) * t
                    py = prev_y + (y - prev_y) * t
                    _plot(inten, hue, dot_rows, dot_cols, px, py, 0.92, hue_now)
                    _plot(inten, hue, dot_rows, dot_cols, px + 1, py, 0.34, hue_now)
                prev_x = x
                prev_y = y
            flash = state.get("scope_flash", 0.0) * 0.72 + min(1.0, features.onset * 1.4)
            state["scope_flash"] = flash
            if flash > 0.05:
                radius = 1.0 + flash * dot_rows * 0.08
                for y in range(max(0, int(cy - radius)), min(dot_rows - 1, int(cy + radius)) + 1):
                    for x in range(max(0, int(cx - radius)), min(dot_cols - 1, int(cx + radius)) + 1):
                        dist = math.hypot(x - cx, y - cy)
                        if dist <= radius:
                            _plot(inten, hue, dot_rows, dot_cols, x, y, flash * (1.0 - dist / max(0.001, radius)), 98)
            _store_feedback(state, inten, hue)
            grad = _gradient_for(game_tag) if use_color else None
            return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                                  use_color=use_color, threshold=0.06)

    if not bars:
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
    grid = bytearray(dot_rows * dot_cols)

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
                    grid[dy * dot_cols + rx] = 1
                lx = center_x - 1 - dx
                if lx >= 0:
                    grid[dy * dot_cols + lx] = 1

        if energy > 0.05:
            grid[dy * dot_cols + center_x] = 1
            if center_x > 0:
                grid[dy * dot_cols + center_x - 1] = 1

    row_colors = None
    if use_color:
        grad = theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL"))
        row_colors = [
            gradient_at(grad, int(row / max(1, height - 1) * 100))
            for row in range(height)
        ]

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
            ch = _BRAILLE_CHAR_LUT[braille - 0x2800]
            if use_color and has_dot:
                row_str.append(c256(ch, row_colors[row]))
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
                        active = bool(game_tag and game_tag != "ALL")
                        if dist == 0:
                            color = theme_visualizer_color("rain", 100, active=active)
                        elif dist <= 2:
                            color = theme_visualizer_color("rain", 72, active=active)
                        else:
                            color = theme_visualizer_color("rain", 20, active=active)
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

    trace_hi = trace_lo = base_color = None
    if use_color:
        heartbeat_grad = theme_visualizer_gradient("heartbeat", active=bool(game_tag and game_tag != "ALL"))
        trace_hi = gradient_at(heartbeat_grad, 95)
        trace_lo = gradient_at(heartbeat_grad, 60)
        base_color = gradient_at(heartbeat_grad, 20)

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



_ASCII_FRAC = (" ", ".", "'", "`", ",", ";", ":", "-", "~", "=", "+", "*", "%", "&", "#", "@")  # 16 levels: empty → full
_ASCII_LEVELS = len(_ASCII_FRAC) - 1  # 15 steps

def ascii_bars_lines(bars, height, width, state=None, use_color=True, game_tag=None):
    """Solid # pillars with 8-step density scale and 2-frame temporal dithering.

    Sub-row resolution: the tip row cycles through 8 ASCII density chars
    (. : - = + * #) giving 8x vertical smoothness. Temporal dithering
    alternates adjacent levels per-bar per-frame, doubling that to ~16x.
    Adjacent bars are out of phase so no whole-row strobe effect.
    """
    if state is not None:
        frame = state.get("frame", 0)
        state["frame"] = frame + 1
    else:
        frame = 0
    bars = bars or []
    if not bars or height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    resampled = resample_bars(bars, width)
    lines = []
    for row in range(height):
        row_chars = []
        for i, v in enumerate(resampled):
            v = max(0.0, min(1.0, v))
            fill_f = v * height
            fill_full = int(fill_f)
            frac = fill_f - fill_full
            row_from_bottom = height - 1 - row
            if row_from_bottom < fill_full:
                ch = "#"
            elif row_from_bottom == fill_full:
                level_f = frac * _ASCII_LEVELS  # 0.0 .. 7.0
                level = int(level_f)
                sub = level_f - level            # sub-step fraction 0..1
                # Temporal dither: promote to level+1 on alternating frames
                # when sub ≥ 0.5; per-bar phase keeps adjacent cols out of sync
                if sub >= 0.5 and (frame + i) % 2 == 0:
                    level = min(_ASCII_LEVELS, level + 1)
                ch = _ASCII_FRAC[level]
            else:
                ch = " "
            if use_color and ch != " ":
                col = spectrum_color(i, width, row_from_bottom / max(1, height - 1), game_tag=game_tag)
                row_chars.append(paint(ch, fg=col))
            else:
                row_chars.append(ch)
        lines.append("".join(row_chars))
    return lines


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

    # The braille spectrum colour depends only on the COLUMN (horizontal
    # frequency position), so precompute one escape prefix per column instead of
    # recomputing the gradient for every cell (height*width times).
    col_esc = (
        [sgr(fg=spectrum_color(col, n_pairs, game_tag=game_tag)) for col in range(n_pairs)]
        if use_color else None
    )

    lines_out = []
    for row in range(height):
        row_str = []
        # Lowest dot-from-bottom contained in this terminal row's cell.
        cell_floor = dot_rows - 4 * (row + 1)
        for col in range(n_pairs):
            braille = 0x2800

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

                # Bar body: number of lit dots from the cell bottom = fill above
                # the cell floor, clamped to the cell's 4 dots — one LUT lookup.
                nlit = fill - cell_floor
                if nlit > 0:
                    braille |= _BRAILLE_BODY_MASK[dc][4 if nlit > 4 else nlit]

            if braille == 0x2800:
                row_str.append(" ")
            elif col_esc is not None:
                # Btop-style: colour by horizontal frequency position (per-column).
                row_str.append(col_esc[col] + chr(braille) + RESET)
            else:
                row_str.append(chr(braille))

        lines_out.append("".join(row_str))
    return lines_out



# ─── Theatrical / beat-reactive visualizers ──────────────────────────────────
#
# These share three helpers:
#   _detect_beat       — bass level + onset (rising-edge) strength from raw bars
#   _plot              — splat a dot into a (intensity, hue) sub-pixel field
#   _braille_field     — turn the field into colored braille lines
# Coordinates are in the braille dot grid (dot_rows = height*4, dot_cols = width*2),
# y measured top→bottom so gravity is +y.

def _detect_beat(bars, state, key="prev_bass", sensitivity=1.0):
    """Return (bass_level, onset_strength). onset is the positive rising edge of
    bass energy, so percussive hits read as spikes that drive the theatrics."""
    if not bars:
        return 0.0, 0.0
    n = len(bars)
    bn = max(1, n // 6)
    bass = sum(bars[:bn]) / bn
    prev = state.get(key, bass)
    onset = max(0.0, bass - prev) * sensitivity
    # Fast-ish tracker: reacts to hits but settles between them.
    state[key] = bass * 0.35 + prev * 0.65
    return bass, onset


def _plot(inten, hue, dot_rows, dot_cols, x, y, v, h):
    """Brightest-wins splat of value v / hue h at dot coordinate (x, y)."""
    xi = int(x); yi = int(y)
    if 0 <= xi < dot_cols and 0 <= yi < dot_rows:
        idx = yi * dot_cols + xi
        if v > inten[idx]:
            inten[idx] = v
            hue[idx] = h


def _braille_field_py(inten, hue, dot_rows, dot_cols, height, width, grad,
                      use_color=True, threshold=0.05, esc=None, esc_bold=None,
                      field_v_dots=4):
    """Render an (intensity, hue) dot field as colored braille rows.

    Each braille cell is colored by its brightest lit dot and bolded when that
    dot is hot, which is what gives particles their glow/pop.
    """
    # Hue is an index 0..100, so precompute the escape prefix per hue (plain and
    # bold) once instead of calling gradient_at()+paint() for every lit cell.
    if use_color and esc is None:
        esc = _gradient_escape_lut(grad)
        esc_bold = _gradient_escape_lut(grad, bold=True)

    bit00, bit01 = _BRAILLE_BIT[0]
    bit10, bit11 = _BRAILLE_BIT[1]
    bit20, bit21 = _BRAILLE_BIT[2]
    bit30, bit31 = _BRAILLE_BIT[3]
    inten_arr = inten
    hue_arr = hue
    reset = RESET
    braille_chars = _BRAILLE_CHAR_LUT
    hot_threshold = _BRAILLE_HOT_THRESHOLD
    lines_out = []
    for row in range(height):
        row_str = []
        append = row_str.append
        if field_v_dots >= 4:
            row0 = row * 4 * dot_cols
            row1 = row0 + dot_cols
            row2 = row1 + dot_cols
            row3 = row2 + dot_cols
        elif field_v_dots <= 1:
            row0 = row * dot_cols
            row1 = row0
            row2 = row0
            row3 = row0
        else:
            row0 = row * 2 * dot_cols
            row1 = row0
            row2 = row0 + dot_cols
            row3 = row2
        active_prefix = None
        for col in range(width):
            braille = 0x2800
            best = threshold
            best_hue = 50
            base_col = col * 2

            idx = row0 + base_col
            v = inten_arr[idx]
            if v > threshold:
                braille |= bit00
                if v > best:
                    best = v
                    best_hue = hue_arr[idx]
            v = inten_arr[idx + 1]
            if v > threshold:
                braille |= bit01
                if v > best:
                    best = v
                    best_hue = hue_arr[idx + 1]

            idx = row1 + base_col
            v = inten_arr[idx]
            if v > threshold:
                braille |= bit10
                if v > best:
                    best = v
                    best_hue = hue_arr[idx]
            v = inten_arr[idx + 1]
            if v > threshold:
                braille |= bit11
                if v > best:
                    best = v
                    best_hue = hue_arr[idx + 1]

            idx = row2 + base_col
            v = inten_arr[idx]
            if v > threshold:
                braille |= bit20
                if v > best:
                    best = v
                    best_hue = hue_arr[idx]
            v = inten_arr[idx + 1]
            if v > threshold:
                braille |= bit21
                if v > best:
                    best = v
                    best_hue = hue_arr[idx + 1]

            idx = row3 + base_col
            v = inten_arr[idx]
            if v > threshold:
                braille |= bit30
                if v > best:
                    best = v
                    best_hue = hue_arr[idx]
            v = inten_arr[idx + 1]
            if v > threshold:
                braille |= bit31
                if v > best:
                    best = v
                    best_hue = hue_arr[idx + 1]
            if braille == 0x2800:
                if active_prefix is not None:
                    append(reset)
                    active_prefix = None
                append(" ")
            elif esc is not None:
                k = int(best_hue)
                if k < 0:
                    k = 0
                elif k > 100:
                    k = 100
                prefix = esc_bold[k] if best > hot_threshold else esc[k]
                if prefix != active_prefix:
                    append(prefix)
                    active_prefix = prefix
                append(braille_chars[braille - 0x2800])
            else:
                if active_prefix is not None:
                    append(reset)
                    active_prefix = None
                append(braille_chars[braille - 0x2800])
        if active_prefix is not None:
            append(reset)
        lines_out.append("".join(row_str))
    return lines_out


def _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                   use_color=True, threshold=0.05, field_v_dots=4):
    esc = esc_bold = None
    if use_color:
        esc = _gradient_escape_lut(grad)
        esc_bold = _gradient_escape_lut(grad, bold=True)
    if _NATIVE_FEEDBACK_BUFFERS and not isinstance(inten, list) and hasattr(_vizfast, "braille_field_buf"):
        return _vizfast.braille_field_buf(
            inten, hue, dot_rows, dot_cols, height, width,
            esc, esc_bold, use_color, threshold, _BRAILLE_HOT_THRESHOLD, RESET,
            field_v_dots,
        )
    if _vizfast is not None and hasattr(_vizfast, "braille_field"):
        return _vizfast.braille_field(
            inten, hue, dot_rows, dot_cols, height, width,
            esc, esc_bold, use_color, threshold, _BRAILLE_HOT_THRESHOLD, RESET,
        ) if field_v_dots >= 4 else _braille_field_py(
            inten, hue, dot_rows, dot_cols, height, width, grad,
            use_color=use_color, threshold=threshold, esc=esc, esc_bold=esc_bold,
            field_v_dots=field_v_dots,
        )
    return _braille_field_py(
        inten, hue, dot_rows, dot_cols, height, width, grad,
        use_color=use_color, threshold=threshold, esc=esc, esc_bold=esc_bold,
        field_v_dots=field_v_dots,
    )


def _feedback_buffers(state, dot_rows, dot_cols):
    size = dot_rows * dot_cols
    buf_inten = "fb_inten_a"
    buf_hue = "fb_hue_a"
    alt_inten = "fb_inten_b"
    alt_hue = "fb_hue_b"
    if _NATIVE_FEEDBACK_BUFFERS:
        inten_factory = lambda: array("f", [0.0]) * size
        hue_factory = lambda: bytearray([50]) * size
    else:
        inten_factory = lambda: [0.0] * size
        hue_factory = lambda: [50] * size
    if (
        state.get("fb_rows") != dot_rows
        or state.get("fb_cols") != dot_cols
        or len(state.get(buf_inten, ())) != size
        or len(state.get(buf_hue, ())) != size
        or len(state.get(alt_inten, ())) != size
        or len(state.get(alt_hue, ())) != size
    ):
        state["fb_rows"] = dot_rows
        state["fb_cols"] = dot_cols
        state[buf_inten] = inten_factory()
        state[buf_hue] = hue_factory()
        state[alt_inten] = inten_factory()
        state[alt_hue] = hue_factory()
        state["fb_active"] = 0
    active = 1 if state.get("fb_active") else 0
    if active:
        return state[alt_inten], state[alt_hue], state[buf_inten], state[buf_hue]
    return state[buf_inten], state[buf_hue], state[alt_inten], state[alt_hue]


def _warp_cached_map(state, dot_rows, dot_cols, zoom, rot, drift_x, drift_y,
                     mirror, swirl, pinch, warp_amp, warp_freq, warp_phase):
    """Return the active cached warp-map index array, maintaining it Geiss-style.

    Holds one *active* map (used by every frame's gather) plus, when the warp
    geometry has drifted, builds a *pending* replacement incrementally across
    ``_WARP_BUILD_FRAMES`` frames in the background and atomically swaps it in
    when complete — so no single frame pays the full per-pixel-trig rebuild.
    Returns the array to gather through this frame.
    """
    size = dot_rows * dot_cols
    grid = (dot_rows, dot_cols)
    geom = (zoom, rot, drift_x, drift_y, swirl, pinch, warp_amp, warp_phase)
    # `bp` (the full build-param tuple) is only needed when a (re)build starts;
    # on the common steady gather frame it is never used, so build it lazily.

    active = state.get("_warp_idx")
    if active is None or len(active) != size or state.get("_warp_grid") != grid:
        # First map (or resize): one synchronous full build — nothing to reuse.
        bp = (zoom, rot, drift_x, drift_y, mirror, swirl, pinch,
              warp_amp, warp_freq, warp_phase)
        active = array("i", [-1]) * size
        _vizfast.build_warp_map_buf(active, dot_rows, dot_cols, *bp)
        state["_warp_idx"] = active
        state["_warp_grid"] = grid
        state["_warp_active_geom"] = geom
        state["_warp_active_mf"] = (mirror, warp_freq)
        state["_warp_build_row"] = -1
        state["_warp_pending"] = None
        state["_warp_age"] = 0
        state["_warp_regens"] = state.get("_warp_regens", 0) + 1
        return active

    rows_per = -(-dot_rows // _WARP_BUILD_FRAMES)   # ceil
    build_row = state.get("_warp_build_row", -1)

    if build_row >= 0:
        # Continue an in-flight background rebuild.
        pending = state["_warp_pending"]
        r_end = min(dot_rows, build_row + rows_per)
        _vizfast.build_warp_map_buf(
            pending, dot_rows, dot_cols, *state["_warp_pending_params"],
            build_row, r_end,
        )
        if r_end >= dot_rows:
            # Swap: pending becomes active; recycle the old active as next spare.
            old = state["_warp_idx"]
            state["_warp_idx"] = pending
            state["_warp_pending"] = old
            state["_warp_active_geom"] = state["_warp_pending_geom"]
            state["_warp_active_mf"] = state["_warp_pending_mf"]
            state["_warp_build_row"] = -1
            state["_warp_age"] = 0
            return pending
        state["_warp_build_row"] = r_end
        return active

    # Idle: decide whether the warp has drifted enough to start a new rebuild.
    age = state.get("_warp_age", 0) + 1
    state["_warp_age"] = age
    if (
        state.get("_warp_active_mf") != (mirror, warp_freq)
        or age >= _WARP_CACHE_KMAX
        or _warp_geom_drift(state["_warp_active_geom"], geom) > _WARP_CACHE_THRESH
    ):
        bp = (zoom, rot, drift_x, drift_y, mirror, swirl, pinch,
              warp_amp, warp_freq, warp_phase)
        pending = state.get("_warp_pending")
        if pending is None or len(pending) != size:
            pending = array("i", [-1]) * size
        r_end = min(dot_rows, rows_per)
        _vizfast.build_warp_map_buf(pending, dot_rows, dot_cols, *bp, 0, r_end)
        state["_warp_pending"] = pending
        state["_warp_pending_params"] = bp
        state["_warp_pending_geom"] = geom
        state["_warp_pending_mf"] = (mirror, warp_freq)
        state["_warp_regens"] = state.get("_warp_regens", 0) + 1
        if r_end >= dot_rows:
            # Tiny grid finished in one slice — swap immediately.
            old = state["_warp_idx"]
            state["_warp_idx"] = pending
            state["_warp_pending"] = old
            state["_warp_active_geom"] = geom
            state["_warp_active_mf"] = (mirror, warp_freq)
            state["_warp_age"] = 0
            return pending
        state["_warp_build_row"] = r_end
    return active


def _feedback_transform(
    state,
    dot_rows,
    dot_cols,
    *,
    decay=0.94,
    zoom=1.0,
    rot=0.0,
    drift_x=0.0,
    drift_y=0.0,
    hue_shift=0.0,
    mirror=0,
    swirl=0.0,
    pinch=0.0,
    warp_amp=0.0,
    warp_freq=6.0,
    warp_phase=0.0,
):
    """Return a decayed, transformed copy of the previous frame field.

    Beyond the global affine (zoom/rot/drift), this applies a MilkDrop-style
    **per-pixel warp field** so the feedback bends organically instead of just
    spinning uniformly:
      swirl    — extra rotation that grows toward the center (spiral suction)
      pinch    — radius-dependent zoom (bulge/contract by distance from center)
      warp_amp — sinusoidal domain warp (the classic MilkDrop "warp" ripples)
    """
    src_inten, src_hue, out_inten, out_hue = _feedback_buffers(state, dot_rows, dot_cols)
    if _WARP_CACHE and _NATIVE_WARP_CACHE and _vizfast is not None and not isinstance(src_inten, list):
        active = _warp_cached_map(
            state, dot_rows, dot_cols, zoom, rot, drift_x, drift_y,
            int(mirror or 0), swirl, pinch, warp_amp, warp_freq, warp_phase,
        )
        _vizfast.feedback_gather_buf(
            src_inten, src_hue, out_inten, out_hue, active, dot_rows * dot_cols,
            decay, hue_shift,
        )
        return out_inten, out_hue
    if _NATIVE_FEEDBACK_BUFFERS and hasattr(_vizfast, "feedback_transform_into_buf"):
        _vizfast.feedback_transform_into_buf(
            src_inten, src_hue, out_inten, out_hue, dot_rows, dot_cols,
            decay, zoom, rot, drift_x, drift_y, hue_shift,
            int(mirror or 0), swirl, pinch, warp_amp, warp_freq, warp_phase,
        )
        return out_inten, out_hue
    if _vizfast is not None and hasattr(_vizfast, "feedback_transform_into"):
        _vizfast.feedback_transform_into(
            src_inten, src_hue, out_inten, out_hue, dot_rows, dot_cols,
            decay, zoom, rot, drift_x, drift_y, hue_shift,
            int(mirror or 0), swirl, pinch, warp_amp, warp_freq, warp_phase,
        )
        return out_inten, out_hue
    if _vizfast is not None:
        # Compiled fast path (identical math, ~10x faster per call).
        return _vizfast.feedback_transform(
            src_inten, src_hue, dot_rows, dot_cols,
            decay, zoom, rot, drift_x, drift_y, hue_shift,
            int(mirror or 0), swirl, pinch, warp_amp, warp_freq, warp_phase,
        )
    out_inten = [0.0] * (dot_rows * dot_cols)
    out_hue = [50] * (dot_rows * dot_cols)
    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    sxcx = max(1.0, cx)
    sycy = max(1.0, cy)
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)
    _per_pixel = bool(swirl or pinch or warp_amp)
    inv_zoom = 1.0 / max(0.001, zoom)
    seg = math.pi / max(1, int(mirror)) if mirror else 0.0
    seg2 = seg * 2.0
    # Frame-invariant normalized coords per axis (cached), + local math binding.
    nx_arr, ny_arr = _feedback_coords(state, dot_rows, dot_cols, cx, cy)
    _cos = math.cos
    _sin = math.sin
    _sqrt = math.sqrt          # sqrt(a*a+b*b) beats hypot(a,b) for our 2D radii
    _atan2 = math.atan2

    for y, nyv in enumerate(ny_arr):
        ty = (nyv - drift_y) * inv_zoom
        ty_cos = ty * cos_r
        ty_sin = ty * sin_r
        row_out = y * dot_cols
        for x, nxv in enumerate(nx_arr):
            tx = (nxv - drift_x) * inv_zoom
            sxn = tx * cos_r + ty_sin
            syn = -tx * sin_r + ty_cos

            if _per_pixel and (sxn or syn):
                r = _sqrt(sxn * sxn + syn * syn)
                if pinch:
                    f = 1.0 + pinch * (0.6 - (1.4 if r > 1.4 else r))
                    sxn *= f
                    syn *= f
                if swirl and r < 1.0:
                    # a==0 for r>=1 → identity rotation, so skip the cos/sin.
                    a = swirl * (1.0 - r)
                    ca = _cos(a); sa = _sin(a)
                    sxn, syn = sxn * ca - syn * sa, sxn * sa + syn * ca
                if warp_amp:
                    sxn += warp_amp * _sin(syn * warp_freq + warp_phase)
                    syn += warp_amp * _cos(sxn * warp_freq + warp_phase)

            if mirror and (sxn or syn):
                ang = _atan2(syn, sxn)
                r = _sqrt(sxn * sxn + syn * syn)
                ang = ang + seg
                ang = ang % seg2 - seg
                if ang < 0.0:
                    ang = -ang
                sxn = _cos(ang) * r
                syn = _sin(ang) * r

            # int(x + 0.5) is round-half-up for the in-bounds (>=0) values we
            # care about, and much cheaper than round(); negatives fall out of
            # bounds and are skipped anyway.
            src_x = int(sxn * sxcx + cx + 0.5)
            if src_x < 0 or src_x >= dot_cols:
                continue
            src_y = int(syn * sycy + cy + 0.5)
            if src_y < 0 or src_y >= dot_rows:
                continue
            src_idx = src_y * dot_cols + src_x
            v = src_inten[src_idx] * decay
            if v > 0.01:
                dst_idx = row_out + x
                out_inten[dst_idx] = v
                out_hue[dst_idx] = (src_hue[src_idx] + hue_shift) % 101

    return out_inten, out_hue


def _feedback_coords(state, dot_rows, dot_cols, cx, cy):
    """Cached per-axis normalized coordinates for the feedback transform."""
    key = (dot_rows, dot_cols)
    cached = state.get("_fb_coords")
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    inv_cx = 1.0 / max(1.0, cx)
    inv_cy = 1.0 / max(1.0, cy)
    nx_arr = [(x - cx) * inv_cx for x in range(dot_cols)]
    ny_arr = [(y - cy) * inv_cy for y in range(dot_rows)]
    state["_fb_coords"] = (key, nx_arr, ny_arr)
    return nx_arr, ny_arr


def _store_feedback(state, inten, hue):
    if inten is state.get("fb_inten_a") and hue is state.get("fb_hue_a"):
        state["fb_active"] = 0
        return
    if inten is state.get("fb_inten_b") and hue is state.get("fb_hue_b"):
        state["fb_active"] = 1
        return
    state["fb_inten_a"] = inten
    state["fb_hue_a"] = hue
    if len(state.get("fb_inten_b", ())) != len(inten) or len(state.get("fb_hue_b", ())) != len(hue):
        state["fb_inten_b"] = [0.0] * len(inten)
        state["fb_hue_b"] = [50] * len(hue)
    state["fb_active"] = 0


def _tunnel_geometry(state, dot_rows, dot_cols, n_bars):
    """Frame-invariant per-pixel geometry for the kaleido tunnel, cached by grid.

    For every pixel inside the active annulus (0.04 < r < 1.35) we precompute the
    base angle, spectrum band index, and the radius-derived constants the hot loop
    actually uses. The per-frame loop then only adds the time-varying angle,
    does the ridge/twist trig, and iterates *only* the active pixels.
    """
    key = (dot_rows, dot_cols, n_bars)
    cached = state.get("_tunnel_geo")
    if cached is not None and cached[0] == key:
        return cached[1]
    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    _hypot = math.hypot
    _atan2 = math.atan2
    inv_cx = 1.0 / max(1.0, cx)
    inv_cy = 1.0 / max(1.0, cy)
    active = []
    for y in range(dot_rows):
        ny = (y - cy) * inv_cy
        ny145 = ny * 1.45
        row_base = y * dot_cols
        for x in range(dot_cols):
            nx = (x - cx) * inv_cx
            r = _hypot(nx, ny145)
            if r < 0.04 or r > 1.35:
                continue
            omr = 1.0 - r
            band_idx = min(n_bars - 1, int(min(0.999, r ** 0.86) * n_bars))
            active.append((row_base + x, _atan2(ny, nx), band_idx, omr * 22.0, 22.0 + omr * 60.0))
    state["_tunnel_geo"] = (key, active)
    return active


def _tunnel_geometry_buf(state, dot_rows, dot_cols, n_bars):
    """Packed native geometry for the kaleido tunnel overlay."""
    key = (dot_rows, dot_cols, n_bars)
    cached = state.get("_tunnel_geo_buf")
    if cached is not None and cached[0] == key:
        return cached[1]
    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    _hypot = math.hypot
    _atan2 = math.atan2
    inv_cx = 1.0 / max(1.0, cx)
    inv_cy = 1.0 / max(1.0, cy)
    idx_arr = array("I")
    ang_arr = array("f")
    band_arr = array("I")
    omr_arr = array("f")
    hue_arr = array("f")
    for y in range(dot_rows):
        ny = (y - cy) * inv_cy
        ny145 = ny * 1.45
        row_base = y * dot_cols
        for x in range(dot_cols):
            nx = (x - cx) * inv_cx
            r = _hypot(nx, ny145)
            if r < 0.04 or r > 1.35:
                continue
            omr = 1.0 - r
            idx_arr.append(row_base + x)
            ang_arr.append(_atan2(ny, nx))
            band_arr.append(min(n_bars - 1, int(min(0.999, r ** 0.86) * n_bars)))
            omr_arr.append(omr * 22.0)
            hue_arr.append(22.0 + omr * 60.0)
    packed = (idx_arr, ang_arr, band_arr, omr_arr, hue_arr)
    state["_tunnel_geo_buf"] = (key, packed)
    return packed


def _tunnel_geometry_fold_buf(state, dot_rows, dot_cols, n_bars, symmetry):
    """Packed tunnel geometry with base angles folded for one symmetry value."""
    base_key = (dot_rows, dot_cols, n_bars)
    active = _tunnel_geometry_buf(state, dot_rows, dot_cols, n_bars)
    cached = state.get("_tunnel_geo_fold_buf")
    if cached is None or cached[0] != base_key:
        cached = (base_key, {})
        state["_tunnel_geo_fold_buf"] = cached
    folded_by_sym = cached[1]
    symmetry = max(1, int(symmetry))
    folded = folded_by_sym.get(symmetry)
    if folded is not None:
        return folded

    seg = math.pi / symmetry
    seg2 = seg * 2.0
    folded_ang = array("f")
    for base_ang in active[1]:
        folded_ang.append((base_ang + seg) % seg2)
    folded = (active[0], folded_ang, active[2], active[3], active[4])
    folded_by_sym[symmetry] = folded
    return folded


def _viz_rng(state, seed=0x9E3779B9):
    rng = state.get("rng")
    if rng is None:
        rng = random.Random(seed)
        state["rng"] = rng
    return rng


def _feature_state(state):
    return state.setdefault("_audio", {})


def _fold_angle(angle, symmetry):
    seg = math.pi / max(1, int(symmetry))
    return abs(((angle + seg) % (seg * 2.0)) - seg)


def _gradient_for(game_tag):
    return theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL"))


def _kaleido_overlay(inten, hue, active, bars, phase, symmetry, ang_off, f03, f09):
    """Overlay the animated tunnel spokes onto an existing feedback field."""
    _cos = math.cos
    _int = int
    _pi = math.pi
    _pi_inv = 18.0 / math.pi
    _ridge_pi_inv = 1.0 / math.pi
    seg = math.pi / max(1, int(symmetry))
    seg2 = seg * 2.0
    sym26 = symmetry * 2.6
    sym2 = symmetry * 2.0
    inten_arr = inten
    hue_arr = hue
    for idx, base_ang, band_idx, omr22, hue_base in active:
        ang = (base_ang + ang_off + seg) % seg2 - seg
        if ang < 0.0:
            ang = -ang
        # Range-reduce to distance from nearest multiple of pi and reject
        # off-spoke pixels before the sin (mirrors the native overlay). On a
        # spoke |sin(theta)| == sin(|d|) exactly, so kept pixels are unchanged.
        d = omr22 - phase + ang * sym26
        q = d * _ridge_pi_inv
        d -= _pi * (_int(q + 0.5) if q >= 0.0 else _int(q - 0.5))
        if d < 0.0:
            d = -d
        if d >= 0.20135792079033079:
            continue
        # After the ridge reject ``d`` is in [0, asin(0.2)), so the cubic
        # small-angle expansion is effectively exact and cheaper than sin().
        d2 = d * d
        lane = 1.0 - (d * (1.0 - d2 / 6.0)) * 5.0
        band = bars[band_idx]
        twist = 0.5 + 0.5 * _cos(ang * sym2 + f03)
        val = (lane * lane * lane) * (0.20 + band * 0.90) * (0.35 + twist * 0.80)
        if val <= 0.06:
            continue
        if val > inten_arr[idx]:
            inten_arr[idx] = val
            hue_arr[idx] = int((hue_base + ang * _pi_inv + f09) % 101)


def _kaleido_overlay_flat(inten, hue, active, bars, phase, symmetry, ang_off, f09):
    """Lower-cost tunnel spoke overlay used on very large feedback grids."""
    _int = int
    _pi = math.pi
    _pi_inv = 18.0 / math.pi
    _ridge_pi_inv = 1.0 / math.pi
    seg = math.pi / max(1, int(symmetry))
    seg2 = seg * 2.0
    sym26 = symmetry * 2.6
    inten_arr = inten
    hue_arr = hue
    for idx, base_ang, band_idx, omr22, hue_base in active:
        ang = (base_ang + ang_off + seg) % seg2 - seg
        if ang < 0.0:
            ang = -ang
        d = omr22 - phase + ang * sym26
        q = d * _ridge_pi_inv
        d -= _pi * (_int(q + 0.5) if q >= 0.0 else _int(q - 0.5))
        if d < 0.0:
            d = -d
        if d >= 0.20135792079033079:
            continue
        d2 = d * d
        lane = 1.0 - (d * (1.0 - d2 / 6.0)) * 5.0
        band = bars[band_idx]
        val = (lane * lane * lane) * (0.20 + band * 0.90) * 0.75
        if val <= 0.06:
            continue
        if val > inten_arr[idx]:
            inten_arr[idx] = val
            hue_arr[idx] = int((hue_base + ang * _pi_inv + f09) % 101)


def kaleido_tunnel_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """MilkDrop-ish feedback tunnel with kaleidoscope symmetry and beat flashes."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    bars = bars or (0.0,)
    features = features or analyze_audio_features(bars, _feature_state(state))
    state["frame"] = state.get("frame", 0) + 1
    # Drive motion from a time-based clock (not the raw frame counter) so a higher
    # refresh rate makes the feedback motion *smoother*, not faster — the visual
    # speed matches the original 30fps feel at any actual fps.
    frame = anim_clock(state)
    # Adaptive vertical resolution: at large terminals render the field at
    # height*2 dot-rows (braille replicates each into two dot-rows) to halve the
    # feedback/overlay/gather work. Shape is unchanged (normalized [-1,1] space).
    v_dots = _kaleido_v_dots((height * 4) * (width * 2))
    dot_rows, dot_cols = height * v_dots, width * 2
    grad = _gradient_for(game_tag) if use_color else None

    symmetry = 5 + int(features.treble_att * 3.0) + int(features.centroid_att * 2.0) + (1 if features.onset > 0.18 else 0)
    # Base the large-field simplifications on the FULL grid so they still trigger
    # under low-res (where dot_rows is already halved).
    large_feedback_field = (height * 4) * dot_cols >= _KALEIDO_LARGE_FIELD_CELLS
    # The spoke overlay already supplies the strong kaleidoscope read. On larger
    # grids the mirrored feedback fold costs a lot of per-pixel trig, so above a
    # medium-size field we keep the tunnel warp but drop the redundant feedback
    # mirror to keep frame time from scaling as hard with window size.
    feedback_mirror = symmetry if not large_feedback_field else 0
    # The treble ripple is visually nice but it is the single most expensive
    # remaining per-pixel term once the mirror fold is gone. On larger grids the
    # spoke overlay already provides enough motion/detail, so we drop just this
    # ripple term to stop fullscreen cost from ballooning with window size.
    feedback_warp_amp = features.treble_att * 0.05 if not large_feedback_field else 0.0
    # Frame-rate-independent feedback: the warp/decay below are applied once per
    # frame, so at high fps the tunnel would flow/fade proportionally faster.
    # Scale every per-frame-accumulating term by the wall-clock motion scale
    # (1.0 at the 30fps reference) so the visual SPEED is the same at any fps —
    # higher fps just makes it smoother. (warp_freq is spatial, warp_phase is
    # already time-based, so they aren't scaled.)
    ms = _motion_scale(state)
    inten, hue = _feedback_transform(
        state,
        dot_rows,
        dot_cols,
        decay=(0.91 + features.bass_att * 0.05) ** ms,
        zoom=1.0 + (0.012 + features.overall * 0.06) * ms,
        rot=(0.012 + features.mids_att * 0.05) * ms,
        drift_x=math.sin(frame * 0.022) * 0.025 * ms,
        drift_y=math.cos(frame * 0.017) * 0.015 * ms,
        hue_shift=(1.2 + features.treble_att * 2.0 + features.centroid_att * 1.3) * ms,
        mirror=feedback_mirror,
        # Per-pixel warp: bass sucks toward center, mids spiral, treble ripples.
        swirl=(0.06 + features.mids_att * 0.45) * ms,
        pinch=(features.bass_att * 0.55) * ms,
        warp_amp=feedback_warp_amp * ms,
        warp_freq=5.0,
        warp_phase=frame * 0.045,
    )

    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    n_bars = max(1, len(bars))
    phase = frame * (0.20 + features.bass * 0.35)
    # Precomputed active-pixel geometry: the overlay loop only does per-frame
    # angle folding + trig and iterates the active annulus pixels.
    ang_off = frame * 0.014
    f03 = frame * 0.03
    f09 = frame * 0.9
    if _NATIVE_FEEDBACK_BUFFERS and _HAS_OVERLAY_GEOM_BUF and not isinstance(inten, list):
        if large_feedback_field and hasattr(_vizfast, "kaleido_overlay_geom_buf_typed_flat_folded"):
            active = _tunnel_geometry_fold_buf(state, dot_rows, dot_cols, n_bars, symmetry)
            seg = math.pi / max(1, int(symmetry))
            seg2 = seg * 2.0
            ang_off_mod = ang_off % seg2
            _vizfast.kaleido_overlay_geom_buf_typed_flat_folded(
                inten, hue,
                active[0], active[1], active[2], active[3], active[4],
                array("f", bars), phase, symmetry, ang_off_mod, f09,
            )
        elif large_feedback_field and hasattr(_vizfast, "kaleido_overlay_geom_buf_typed_flat"):
            active = _tunnel_geometry_buf(state, dot_rows, dot_cols, n_bars)
            _vizfast.kaleido_overlay_geom_buf_typed_flat(
                inten, hue,
                active[0], active[1], active[2], active[3], active[4],
                array("f", bars), phase, symmetry, ang_off, f09,
            )
        elif _HAS_OVERLAY_GEOM_BUF_TYPED:
            active = _tunnel_geometry_buf(state, dot_rows, dot_cols, n_bars)
            _vizfast.kaleido_overlay_geom_buf_typed(
                inten, hue,
                active[0], active[1], active[2], active[3], active[4],
                array("f", bars), phase, symmetry, ang_off, f03, f09,
            )
        else:
            active = _tunnel_geometry_buf(state, dot_rows, dot_cols, n_bars)
            _vizfast.kaleido_overlay_geom_buf(
                inten, hue,
                active[0], active[1], active[2], active[3], active[4],
                bars, phase, symmetry, ang_off, f03, f09,
            )
    elif _HAS_OVERLAY:
        active = _tunnel_geometry(state, dot_rows, dot_cols, n_bars)
        if large_feedback_field:
            _kaleido_overlay_flat(inten, hue, active, bars, phase, symmetry, ang_off, f09)
        else:
            _vizfast.kaleido_overlay(inten, hue, active, bars, phase, symmetry, ang_off, f03, f09)
    else:
        active = _tunnel_geometry(state, dot_rows, dot_cols, n_bars)
        if large_feedback_field:
            _kaleido_overlay_flat(inten, hue, active, bars, phase, symmetry, ang_off, f09)
        else:
            _kaleido_overlay(inten, hue, active, bars, phase, symmetry, ang_off, f03, f09)

    # 0.86 is a per-frame decay; scale it by the motion clock so beat flashes
    # last the same wall-clock time (don't get snappier) at higher fps.
    flash = state.get("flash", 0.0) * (0.86 ** ms) + min(1.0, features.onset * 2.4)
    state["flash"] = flash
    if flash > 0.04:
        radius = 1.0 + flash * dot_rows * 0.18
        min_x = max(0, int(cx - radius))
        max_x = min(dot_cols - 1, int(cx + radius))
        min_y = max(0, int(cy - radius))
        max_y = min(dot_rows - 1, int(cy + radius))
        if _NATIVE_FEEDBACK_BUFFERS and not isinstance(inten, list):
            _vizfast.flash_disc_buf(
                inten, hue, dot_cols, min_x, max_x, min_y, max_y,
                cx, cy, radius, flash, 96, 1.0, 1.2,
            )
        else:
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    dist = math.hypot(x - cx, (y - cy) * 1.2)
                    if dist > radius:
                        continue
                    v = flash * max(0.0, 1.0 - dist / max(0.001, radius))
                    _plot(inten, hue, dot_rows, dot_cols, x, y, v, 96)

    _store_feedback(state, inten, hue)
    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.05, field_v_dots=v_dots)


def liquid_scope_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Feedback oscilloscope with mirrored smear and kick flashes."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    bars = bars or (0.0,)
    features = features or analyze_audio_features(bars, _feature_state(state))
    state["frame"] = state.get("frame", 0) + 1
    # Drive motion from a time-based clock (not the raw frame counter) so a higher
    # refresh rate makes the feedback motion *smoother*, not faster — the visual
    # speed matches the original 30fps feel at any actual fps.
    frame = anim_clock(state)
    v_dots = 2 if _vis_use_lowres((height * 4) * (width * 2)) else 4
    dot_rows, dot_cols = height * v_dots, width * 2
    grad = _gradient_for(game_tag) if use_color else None

    inten, hue = _feedback_transform(
        state,
        dot_rows,
        dot_cols,
        decay=0.90 + features.overall * 0.05,
        zoom=1.001 + features.bass_att * 0.02,
        rot=math.sin(frame * 0.02) * 0.015,
        drift_x=-0.010 - features.mids_att * 0.015,
        drift_y=math.sin(frame * 0.01) * 0.008,
        hue_shift=0.6 + features.treble_att * 1.4 + features.centroid_att * 1.2,
    )

    phase = state.get("phase", 0.0) + 0.18 + features.treble * 0.08 + features.centroid_att * 0.10
    state["phase"] = phase
    history = state.get("scope_history")
    if history is None or len(history) != dot_cols:
        history = [0.0] * dot_cols
    stereo_pan = features.right - features.left
    sig_a = math.sin(phase * 0.9 + stereo_pan * 0.8) * (0.18 + features.mids * 0.35)
    sig_b = math.sin(phase * 0.31 + features.bass * 2.6) * (0.22 + features.bass * 0.48)
    sig_c = math.cos(phase * 1.7 + features.treble * 3.2) * (0.08 + features.treble * 0.22)
    sample_a = max(-1.0, min(1.0, sig_a + sig_b + sig_c))
    sample_b = max(-1.0, min(1.0, sig_b - sig_a * 0.5 + sig_c * 0.8 + stereo_pan * 0.75))
    history = history[2:] + [sample_a, sample_b]
    state["scope_history"] = history

    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    amp = dot_rows * (0.14 + features.bass_att * 0.26)
    stereo_splay = features.width * dot_rows * 0.16
    prev_x = 0.0
    prev_y = cy - history[0] * amp
    prev_mirror = cy + history[0] * amp * (0.30 + features.width * 0.75 + features.mids_att * 0.30)
    for x in range(1, dot_cols):
        wobble = math.sin(frame * 0.04 + x * 0.06) * features.treble_att * dot_rows * 0.03
        stereo_warp = math.sin(phase * 0.42 + x * 0.08) * stereo_splay
        y = cy - history[x] * amp + wobble + stereo_warp
        mirror_y = cy + history[x] * amp * (0.30 + features.width * 0.75 + features.mids_att * 0.30) - wobble * 0.4 - stereo_warp * 0.55
        steps = max(1, int(max(abs(y - prev_y), abs(mirror_y - prev_mirror))) + 1)
        hue_main = int((32 + x / max(1, dot_cols - 1) * 48 + frame * 0.6) % 101)
        hue_mirror = int((70 + x / max(1, dot_cols - 1) * 18 + frame * 0.4) % 101)
        for s in range(steps + 1):
            t = s / steps
            px = prev_x + (x - prev_x) * t
            py = prev_y + (y - prev_y) * t
            pm = prev_mirror + (mirror_y - prev_mirror) * t
            _plot(inten, hue, dot_rows, dot_cols, px, py, 0.95, hue_main)
            _plot(inten, hue, dot_rows, dot_cols, px, py + 1, 0.42, hue_main)
            _plot(inten, hue, dot_rows, dot_cols, px, pm, 0.45, hue_mirror)
        prev_x = float(x)
        prev_y = y
        prev_mirror = mirror_y

    flash = state.get("scope_flash", 0.0) * 0.82 + min(1.0, features.onset * 2.8)
    state["scope_flash"] = flash
    if flash > 0.05:
        radius = 1.5 + flash * dot_rows * 0.10
        min_x = max(0, int(cx - radius * 1.6))
        max_x = min(dot_cols - 1, int(cx + radius * 1.6))
        min_y = max(0, int(cy - radius))
        max_y = min(dot_rows - 1, int(cy + radius))
        if _NATIVE_FEEDBACK_BUFFERS and not isinstance(inten, list):
            _vizfast.flash_disc_buf(
                inten, hue, dot_cols, min_x, max_x, min_y, max_y,
                cx, cy, radius, flash, 98, 1.6, 1.0,
            )
        else:
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    dist = math.hypot((x - cx) / 1.6, y - cy)
                    if dist <= radius:
                        _plot(inten, hue, dot_rows, dot_cols, x, y, flash * (1.0 - dist / max(0.001, radius)), 98)

    _store_feedback(state, inten, hue)
    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.05, field_v_dots=v_dots)


def plasma_bloom_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Feedback plasma field with breathing blooms and beat-synced rings."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    bars = bars or (0.0,)
    features = features or analyze_audio_features(bars, _feature_state(state))
    state["frame"] = state.get("frame", 0) + 1
    # Drive motion from a time-based clock (not the raw frame counter) so a higher
    # refresh rate makes the feedback motion *smoother*, not faster — the visual
    # speed matches the original 30fps feel at any actual fps.
    frame = anim_clock(state)
    v_dots = 2 if _vis_use_lowres((height * 4) * (width * 2)) else 4
    dot_rows, dot_cols = height * v_dots, width * 2
    grad = _gradient_for(game_tag) if use_color else None

    inten, hue = _feedback_transform(
        state,
        dot_rows,
        dot_cols,
        decay=0.92 + features.overall * 0.04,
        zoom=1.004 + features.mids_att * 0.020,
        rot=math.sin(frame * 0.017) * 0.012 + features.treble_att * 0.018,
        drift_x=math.sin(frame * 0.015) * 0.010,
        drift_y=math.cos(frame * 0.013) * 0.012,
        hue_shift=1.0 + features.treble_att * 1.8 + features.contrast_att * 1.2,
        mirror=3 if features.width > 0.10 else 0,
        # Gentle breathing warp so the plasma folds and bulges with the music.
        swirl=math.sin(frame * 0.011) * 0.12 + features.mids_att * 0.18 + features.contrast_att * 0.08,
        pinch=math.sin(frame * 0.02) * 0.10 + features.bass_att * 0.30,
        warp_amp=0.02 + features.treble_att * 0.04 + features.contrast_att * 0.04,
        warp_freq=4.0,
        warp_phase=frame * 0.03,
    )

    phase = state.get("plasma_phase", 0.0) + 0.08 + features.treble * 0.05 + features.width * 0.04 + features.contrast_att * 0.03
    state["plasma_phase"] = phase
    pulse = min(1.0, state.get("plasma_pulse", 0.0) * 0.84 + features.onset * 1.6 + features.contrast_att * 0.22)
    state["plasma_pulse"] = pulse

    cx = (dot_cols - 1) / 2.0
    cy = (dot_rows - 1) / 2.0
    if _NATIVE_FEEDBACK_BUFFERS and hasattr(_vizfast, "plasma_field_buf") and not isinstance(inten, list):
        _vizfast.plasma_field_buf(
            inten, hue, dot_rows, dot_cols,
            phase, frame, pulse,
            features.contrast_att, features.bass_att, features.overall,
        )
    else:
        for y in range(dot_rows):
            ny = (y - cy) / max(1.0, cy)
            for x in range(dot_cols):
                nx = (x - cx) / max(1.0, cx)
                r = math.hypot(nx * 1.05, ny * 1.20)
                if r > 1.35:
                    continue
                swirl = (
                    math.sin(nx * 6.4 + phase * 1.5)
                    + math.sin(ny * 5.2 - phase * 1.1)
                    + math.sin((nx + ny) * 4.1 + phase * 0.7)
                ) / 3.0
                petals = 0.5 + 0.5 * math.cos(math.atan2(ny, nx) * (3.2 + features.contrast_att * 2.2) - phase * 0.5)
                bloom = max(0.0, 1.0 - r * (1.02 + features.bass_att * 0.32))
                val = max(0.0, swirl * 0.5 + 0.5 - 0.26)
                val *= (bloom ** 1.9) * (0.30 + petals * 0.80) * (0.24 + features.overall * 0.96)
                ring = max(0.0, 0.20 - abs(r - (0.16 + pulse * 0.26)))
                val += ring * pulse * 1.7
                if val <= 0.05:
                    continue
                idx = y * dot_cols + x
                if val > inten[idx]:
                    inten[idx] = val
                    hue[idx] = int((44 + swirl * 18 + petals * 20 + frame * 0.7 - r * 28) % 101)

    if pulse > 0.04:
        radius = 1.0 + pulse * dot_rows * 0.12
        min_x = max(0, int(cx - radius))
        max_x = min(dot_cols - 1, int(cx + radius))
        min_y = max(0, int(cy - radius))
        max_y = min(dot_rows - 1, int(cy + radius))
        if _NATIVE_FEEDBACK_BUFFERS and not isinstance(inten, list):
            _vizfast.flash_disc_buf(
                inten, hue, dot_cols, min_x, max_x, min_y, max_y,
                cx, cy, radius, pulse * 0.65, 99, 1.0, 1.15,
            )
        else:
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    dist = math.hypot(x - cx, (y - cy) * 1.15)
                    if dist <= radius:
                        _plot(inten, hue, dot_rows, dot_cols, x, y,
                              pulse * 0.65 * (1.0 - dist / max(0.001, radius)), 99)

    _store_feedback(state, inten, hue)
    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.05, field_v_dots=v_dots)


_MILKDROP_PRESETS = (
    ("tunnel", kaleido_tunnel_render_lines),
    ("liquid", liquid_scope_render_lines),
    ("plasma", plasma_bloom_render_lines),
)


def milkdrop_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Preset-style driver that shuffles between feedback renderers on musical phrases."""
    if height <= 0 or width <= 0:
        state["display_label"] = "milkdrop"
        return [" " * max(1, width)] * max(1, height)

    bars = bars or (0.0,)
    features = features or analyze_audio_features(bars, _feature_state(state))
    rng = _viz_rng(state, 0x4D494C4B)
    preset_count = len(_MILKDROP_PRESETS)
    active = state.get("active_preset")
    if active is None or not (0 <= active < preset_count):
        active = rng.randrange(preset_count)
    age = state.get("preset_age", 0) + 1
    frames_left = state.get("preset_frames_left")
    if frames_left is None:
        frames_left = 110 + rng.randint(0, 110)
    else:
        frames_left -= 1
    min_hold = 80
    should_switch = frames_left <= 0
    if not should_switch and age >= min_hold and features.onset > 0.28:
        should_switch = rng.random() < min(
            0.70,
            0.12 + features.onset * 0.18 + features.width * 0.24 + features.contrast_att * 0.28,
        )
    if should_switch and preset_count > 1:
        choices = [idx for idx in range(preset_count) if idx != active]
        active = rng.choice(choices) if choices else active
        age = 0
        frames_left = 110 + rng.randint(0, 110)
        state["preset_flash"] = 1.0
    elif frames_left <= 0:
        frames_left = 110 + rng.randint(0, 110)

    state["active_preset"] = active
    state["preset_age"] = age
    state["preset_frames_left"] = frames_left
    state["display_label"] = f"milkdrop:{_MILKDROP_PRESETS[active][0]}"

    pulse = state.get("preset_flash", 0.0) * 0.78
    state["preset_flash"] = pulse
    if pulse > 0.02:
        state["flash"] = max(state.get("flash", 0.0), pulse * 0.70)
        state["scope_flash"] = max(state.get("scope_flash", 0.0), pulse * 0.80)
        state["plasma_pulse"] = max(state.get("plasma_pulse", 0.0), pulse)

    _name, fn = _MILKDROP_PRESETS[active]
    return fn(bars, height, width, state, features=features, use_color=use_color, game_tag=game_tag)


def fireworks_render_lines(bars, height, width, state, use_color=True, game_tag=None, features=None):
    """Bass hits launch shells that arc up and burst into colored, falling sparks."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    dot_rows, dot_cols = height * 4, width * 2
    rng = _viz_rng(state, 0xF00DCAFE)
    parts = state.setdefault("parts", [])
    state["frame"] = state.get("frame", 0) + 1
    features = features or analyze_audio_features(bars, _feature_state(state))
    bass, onset = _detect_beat(bars, state, sensitivity=1.4)
    grad = theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL")) if use_color else None

    cap = max(60, dot_cols * 3)
    cool = state.get("cool", 0)
    if onset > 0.05 and cool <= 0 and len(parts) < cap:
        for _ in range(1 + int(min(3, onset * 9))):
            x = rng.uniform(dot_cols * 0.12, dot_cols * 0.88)
            vy = -(dot_rows * 0.045) * (0.7 + rng.random() * 0.6) * (0.6 + bass)
            burst_y = dot_rows * (0.10 + rng.random() * 0.32)   # apex height (from top)
            launch_drift = rng.uniform(-0.3, 0.3) * (0.8 + features.width * 0.4 + features.contrast_att * 0.5)
            parts.append([x, dot_rows - 1.0, launch_drift, vy,
                          rng.randint(0, 100), 0, burst_y])
        state["cool"] = 2
    state["cool"] = max(0, cool - 1)

    g = dot_rows * 0.0018 + 0.02
    inten = [0.0] * (dot_rows * dot_cols)
    hue_g = [50] * (dot_rows * dot_cols)
    alive = []
    for p in parts:
        x, y, vx, vy, hue, kind, meta = p
        if kind == 0:  # rising shell
            x += vx; y += vy; vy += g * 0.5
            _plot(inten, hue_g, dot_rows, dot_cols, x, y, 1.0, hue)
            _plot(inten, hue_g, dot_rows, dot_cols, x, y + 1, 0.45, hue)
            if y <= meta or vy >= 0:   # burst at apex
                n_sparks = 12 + int(bass * 18) + int(features.contrast_att * 12) + int(features.centroid_att * 8)
                for k in range(n_sparks):
                    ang = (k / n_sparks) * math.tau + rng.uniform(-0.12, 0.12)
                    spd = (dot_rows * 0.024) * (
                        0.42 + rng.random() + features.contrast_att * 0.18 + features.centroid_att * 0.12
                    )
                    alive.append([x, y, math.cos(ang) * spd, math.sin(ang) * spd * 0.6,
                                  hue, 1, 1.0])
                continue
            alive.append([x, y, vx, vy, hue, kind, meta])
        else:          # falling spark
            life = meta - 0.045
            if life <= 0:
                continue
            x += vx; y += vy; vy += g; vx *= 0.96
            _plot(inten, hue_g, dot_rows, dot_cols, x, y, life, hue)
            alive.append([x, y, vx, vy, hue, kind, life])
    state["parts"] = alive
    return _braille_field(inten, hue_g, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.04)


def starfield_render_lines(bars, height, width, state, use_color=True, game_tag=None, features=None):
    """Warp-drive starfield: stars stream out from center, accelerating with bass."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    dot_rows, dot_cols = height * 4, width * 2
    rng = _viz_rng(state, 0xBEEFBABE)
    stars = state.setdefault("stars", [])
    state["frame"] = state.get("frame", 0) + 1
    features = features or analyze_audio_features(bars, _feature_state(state))
    bass, onset = _detect_beat(bars, state)
    overall = features.overall
    cx, cy = dot_cols / 2.0, dot_rows / 2.0
    grad = theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL")) if use_color else None

    field_density = max(0.35, 1.10 - features.contrast_att * 0.45)
    target = int(dot_cols * field_density * (0.7 + overall * 1.3))
    while len(stars) < target:
        ang = rng.uniform(0, math.tau)
        stars.append([cx, cy, math.cos(ang), math.sin(ang),
                      rng.uniform(0.2, 1.0 + features.contrast_att * 0.5), rng.randint(0, 100)])

    warp = 0.45 + bass * 3.4 + onset * 4.2 + features.centroid_att * 0.7 + features.contrast_att * 1.1
    inten = [0.0] * (dot_rows * dot_cols)
    hue_g = [50] * (dot_rows * dot_cols)
    keep = []
    for s in stars:
        x, y, dx, dy, sp, hue = s
        r = math.hypot(x - cx, y - cy) + 0.001
        step = sp * warp * (0.4 + r / dot_cols * 1.6)
        x += dx * step
        y += dy * step * 0.5   # vertical squash for terminal aspect ratio
        if x < 0 or x >= dot_cols or y < 0 or y >= dot_rows:
            continue           # gone — refilled from center next frame
        bright = min(1.0, 0.3 + r / (dot_cols * 0.5))
        _plot(inten, hue_g, dot_rows, dot_cols, x, y, bright, hue)
        if warp > 1.6:         # streak tails when warping hard
            _plot(inten, hue_g, dot_rows, dot_cols,
                  x - dx * step * 0.6, y - dy * step * 0.3, bright * 0.5, hue)
        keep.append([x, y, dx, dy, sp, hue])
    state["stars"] = keep
    return _braille_field(inten, hue_g, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.03)


def ripple_render_lines(bars, height, width, state, use_color=True, game_tag=None, features=None):
    """Sonar: each beat emits an expanding ring from center; rings fade as they grow."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    dot_rows, dot_cols = height * 4, width * 2
    state["frame"] = state.get("frame", 0) + 1
    rings = state.setdefault("rings", [])
    features = features or analyze_audio_features(bars, _feature_state(state))
    bass, onset = _detect_beat(bars, state)
    cx, cy = dot_cols / 2.0, dot_rows / 2.0
    max_r = math.hypot(cx, cy)
    grad = theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL")) if use_color else None

    if onset > 0.045 and (not rings or rings[-1][0] > dot_rows * 0.14):
        rings.append([1.0, min(100, int(28 + onset * 115 + features.centroid_att * 26)), 1.0])

    inten = [0.0] * (dot_rows * dot_cols)
    hue_g = [50] * (dot_rows * dot_cols)
    speed = dot_rows * (0.05 + features.contrast_att * 0.03) + bass * dot_rows * 0.05
    alive = []
    for ring in rings:
        r, hue, life = ring
        r += speed
        life -= 0.022 + features.contrast_att * 0.01
        if life <= 0 or r > max_r:
            continue
        steps = max(16, int(r * math.tau / 1.5))
        for k in range(steps):
            ang = k / steps * math.tau
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r * 0.5   # aspect squash
            _plot(inten, hue_g, dot_rows, dot_cols, x, y, life, hue)
        alive.append([r, hue, life])
    state["rings"] = alive
    # Pulsing core that breathes with the bass.
    core = 0.4 + bass
    _plot(inten, hue_g, dot_rows, dot_cols, cx, cy, core, int(60 + bass * 40))
    return _braille_field(inten, hue_g, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.05)


def aurora_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Northern-lights curtains: glowing shaded columns hanging from a wavy edge,
    height driven by the spectrum, shimmering and drifting with the music."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    state["frame"] = state.get("frame", 0) + 1
    frame = state["frame"]
    sampled = resample_bars(bars, width) if bars else [0.0] * width
    features = features or analyze_audio_features(bars, _feature_state(state))
    bass, _onset = _detect_beat(bars, state)
    grad = theme_visualizer_gradient("spectrum", active=bool(game_tag and game_tag != "ALL")) if use_color else None
    ramp = VIS_SHADE_BLOCKS
    last = len(ramp) - 1
    flow = frame * (0.55 + features.centroid_att * 0.80)

    lines_out = []
    for row in range(height):
        vfrac = row / max(1, height - 1)
        parts = []
        for col in range(width):
            e = sampled[col] if col < len(sampled) else 0.0
            # Wavy top edge: louder columns hang lower (taller curtain).
            top = 0.08 + (1.0 - e) * (0.48 + features.centroid_att * 0.10) + 0.12 * math.sin(frame * 0.05 + col * 0.22)
            if vfrac < top:
                parts.append(" ")
                continue
            depth = (vfrac - top) / max(0.001, 1.0 - top)
            shimmer = 0.55 + 0.45 * math.sin(frame * (0.10 + features.centroid_att * 0.08) + col * 0.4 + row * 0.7)
            inten = max(0.0, min(1.0, e * (1.0 - depth * 0.6) * shimmer + bass * 0.15))
            li = int(inten * last + 0.35)
            if li <= 0:
                parts.append(" ")
                continue
            ch = ramp[min(last, li)]
            if use_color:
                hue = int((vfrac * 70 + flow + col * 0.5) % 100)
                parts.append(paint(ch, fg=gradient_at(grad, hue), bold=inten > 0.75))
            else:
                parts.append(ch)
        lines_out.append("".join(parts))
    return lines_out


def polar_spectrum_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Spectral donut: the spectrum wrapped symmetrically around a ring, each bin
    pushing a radial spoke outward.  Bass crowns the top; the ring breathes with
    the beat and leaves soft feedback trails as it slowly rotates."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    dot_rows, dot_cols = height * 4, width * 2
    state["frame"] = state.get("frame", 0) + 1
    features = features or analyze_audio_features(bars, _feature_state(state))
    bass, onset = _detect_beat(bars, state)
    grad = _gradient_for(game_tag) if use_color else None
    cx, cy = dot_cols / 2.0, dot_rows / 2.0

    # Soft bloom/trails: decay the previous ring and rotate it a touch so the
    # afterglow swirls instead of just sitting under the fresh spokes.
    inten, hue = _feedback_transform(
        state, dot_rows, dot_cols,
        decay=0.80 + features.overall * 0.06,
        rot=0.010 + features.treble_att * 0.012,
        hue_shift=0.5 + features.treble_att * 0.9,
    )
    spin = state["spin"] = state.get("spin", 0.0) + 0.018 + features.mids_att * 0.05
    flash = state["flash"] = state.get("flash", 0.0) * 0.84 + min(1.0, onset * 2.2)

    spectrum = resample_bars(bars, 48) or [0.0] * 48
    n = len(spectrum)
    radius = min(cx, cy)
    inner = radius * (0.30 + bass * 0.12 + flash * 0.05)   # inner hole pulses on bass
    extent = radius * (0.60 - bass * 0.04)                 # outward room for the spokes

    steps = max(72, dot_cols * 2)
    for k in range(steps):
        ang = k / steps * math.tau
        # Symmetric wrap: top = bass, bottom = treble, mirrored left/right.
        frac = abs(((ang + math.pi) % math.tau) - math.pi) / math.pi
        pos = frac * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        val = spectrum[lo] * (1.0 - (pos - lo)) + spectrum[hi] * (pos - lo)
        ca, sa = math.cos(ang + spin), math.sin(ang + spin)
        spoke = inner + val * extent
        r = inner
        while r <= spoke:                       # walk the spoke outward from the ring
            depth = (r - inner) / max(0.001, extent)
            bright = min(1.0, 0.35 + val * 0.7 + depth * 0.25 + flash * 0.3)
            tone = int(min(100, val * 72 + depth * 22 + flash * 18))
            _plot(inten, hue, dot_rows, dot_cols, cx + ca * r, cy + sa * r * 0.5, bright, tone)
            r += 0.7
        # Bright cap at the spoke tip for a crisp outer rim.
        _plot(inten, hue, dot_rows, dot_cols, cx + ca * spoke, cy + sa * spoke * 0.5,
              min(1.0, 0.6 + val + flash * 0.4), int(min(100, 60 + val * 40)))

    # Calm inner core so the hole never reads as a dead spot.
    _plot(inten, hue, dot_rows, dot_cols, cx, cy, 0.25 + bass * 0.5, int(55 + bass * 35))

    _store_feedback(state, inten, hue)
    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.04)


def chroma_wheel_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """Harmony wheel: the 12 pitch classes as colored wedges around a ring, each
    sized and lit by how much of that note is sounding, hue following the note
    around the color wheel.  The detected key flares brightest — so the color
    tracks the actual harmony rather than raw band energy."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    dot_rows, dot_cols = height * 4, width * 2
    state["frame"] = state.get("frame", 0) + 1
    features = features or analyze_audio_features(bars, _feature_state(state))
    grad = _gradient_for(game_tag) if use_color else None
    bass, onset = _detect_beat(bars, state)
    cx, cy = dot_cols / 2.0, dot_rows / 2.0
    chroma = features.chroma or (0.0,) * 12
    key = features.key

    inten, hue = _feedback_transform(
        state, dot_rows, dot_cols,
        decay=0.74 + features.overall * 0.06,
        hue_shift=0.2,
    )
    spin = state["spin"] = state.get("spin", 0.0) + 0.008 + features.mids_att * 0.03
    flash = state["flash"] = state.get("flash", 0.0) * 0.85 + min(1.0, onset * 2.0)
    radius = min(cx, cy)
    inner = radius * 0.16
    seg = math.tau / 12.0

    for pc in range(12):
        val = max(0.0, min(1.0, chroma[pc]))
        is_key = pc == key
        boost = (0.25 + features.key_strength * 0.35) if is_key else 0.0
        reach = inner + (0.22 + val * 0.58 + (0.12 if is_key else 0.0)) * radius
        tone = int(pc / 12.0 * 100)            # hue follows pitch class
        sub = 4                                 # fan spokes so the wedge fills in
        for s in range(sub + 1):
            a = pc * seg + (s / sub) * seg * 0.86 + spin
            ca, sa = math.cos(a), math.sin(a)
            r = inner
            while r <= reach:
                bright = min(1.0, 0.30 + val * 0.7 + boost + flash * 0.2 * val)
                _plot(inten, hue, dot_rows, dot_cols, cx + ca * r, cy + sa * r * 0.5, bright, tone)
                r += 0.8

    # Center pip breathes with the bass so the hub never reads dead.
    _plot(inten, hue, dot_rows, dot_cols, cx, cy, 0.30 + bass * 0.4, int(50 + bass * 30))

    _store_feedback(state, inten, hue)
    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.04)


# ─── Diagnostics: live audio-feature meters ──────────────────────────────────
# A tuning aid, not eye-candy: the shared AudioFeatures drive every reactive
# mode, so seeing them as labeled meters + recent-history sparklines makes it
# obvious which signal to map where.  Pure list-of-strings like every other mode.

# 9-level block ramp for a one-row sparkline (index 0..8); ASCII-safe fallback.
_SPARK_RAMP = (" ", ".", ":", "-", "=", "+", "*", "#", "@") if ASCII_ONLY else " ▁▂▃▄▅▆▇█"
_FEATURE_HISTORY = 64

# (label, AudioFeatures attribute) in the order they're stacked top→bottom.
_FEATURE_ROWS = (
    ("bass", "bass"),
    ("mids", "mids"),
    ("treble", "treble"),
    ("centroid", "centroid"),
    ("contrast", "contrast"),
    ("overall", "overall"),
    ("onset", "onset"),
    ("width", "width"),
)


def _sparkline(values, width, grad, use_color):
    """One-row block sparkline of the last `width` samples, oldest left."""
    if width <= 0:
        return ""
    vals = list(values)[-width:]
    if len(vals) < width:
        vals = [0.0] * (width - len(vals)) + vals
    top = len(_SPARK_RAMP) - 1
    out = []
    for v in vals:
        v = max(0.0, min(1.0, v))
        ch = _SPARK_RAMP[int(v * top + 0.5)]
        if use_color and ch != _SPARK_RAMP[0]:
            out.append(paint(ch, fg=gradient_at(grad, int(v * 100))))
        else:
            out.append(ch)
    return "".join(out)


def features_debug_lines(bars, height, width, state, features=None, snapshot=None,
                         use_color=True, game_tag=None):
    """Render the live AudioFeatures as labeled meter bars + history sparklines."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    features = features or analyze_audio_features(bars, _feature_state(state))
    grad = _gradient_for(game_tag) if use_color else None
    hist = state.setdefault("hist", {})
    state["frame"] = state.get("frame", 0) + 1

    # Column geometry — meter soaks up whatever the label/value/spark don't use.
    label_w, num_w = 8, 6
    spark_w = max(0, min(12, width - label_w - num_w - 6))
    gap = 1 if spark_w else 0
    meter_w = width - label_w - num_w - gap - spark_w
    if meter_w < 4:                       # tiny pane: drop the sparkline for bar room
        spark_w = gap = 0
        meter_w = max(1, width - label_w - num_w)

    # Title row: "FEATURES" left, capture source right, plain text padded exact.
    src = ""
    if snapshot is not None:
        rate = getattr(snapshot, "sample_rate", 0)
        kind = getattr(snapshot, "source_kind", "") or ""
        src = f"{kind} {rate // 1000}kHz" if rate else kind
    title = "FEATURES"
    mid = max(1, width - len(title) - len(src))
    title_line = (title + " " * mid + src)[:width]
    if use_color:
        title_line = paint(title_line, fg=gradient_at(grad, 80), bold=True)

    lines = [title_line]
    for label, attr in _FEATURE_ROWS:
        if len(lines) >= height:
            break
        val = float(getattr(features, attr, 0.0))
        series = hist.setdefault(attr, [])
        series.append(val)
        if len(series) > _FEATURE_HISTORY:
            del series[:-_FEATURE_HISTORY]
        bar = meter_bar(min(1.0, max(0.0, val)) * 100.0, meter_w, grad, use_color=use_color)
        num = f"{val:>{num_w}.2f}"
        lbl = f"{label:<{label_w}}"
        if use_color:
            lbl = paint(lbl, dim=True)
            num = paint(num, fg=gradient_at(grad, int(min(1.0, val) * 100)))
        spark = (" " + _sparkline(series, spark_w, grad, use_color)) if spark_w else ""
        lines.append(lbl + bar + num + spark)

    while len(lines) < height:
        lines.append(" " * width)
    return lines[:height]


# ─── Frame dispatch ───────────────────────────────────────────────────────────
# ─── 3D audio orb ─────────────────────────────────────────────────────────────
_ORB_POINTS_CACHE = {}


def _orb_sphere_points(n):
    """`n` roughly-even points on the unit sphere (golden-spiral), cached."""
    cached = _ORB_POINTS_CACHE.get(n)
    if cached is not None:
        return cached
    ga = math.pi * (3.0 - math.sqrt(5.0))  # golden angle
    pts = []
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        th = ga * i
        pts.append((math.cos(th) * r, y, math.sin(th) * r))
    _ORB_POINTS_CACHE[n] = pts
    return pts


def orb3d_render_lines(bars, height, width, state, features=None, use_color=True, game_tag=None):
    """A floating 3D audio orb: a sphere of points that grow spectral spikes on
    the beat, slowly rotating in perspective so you orbit around it. Each vertex
    maps to a frequency band; loud bands shoot radial spikes that recede under
    gravity. Pure 3D->2D perspective projection splatted into the braille dot
    field; depth shades brightness so it reads as a real 3D object. Motion is
    anim_clock-driven, so it's the same speed at any fps (just smoother)."""
    if height <= 0 or width <= 0:
        return [" " * max(1, width)] * max(1, height)
    bars = bars or (0.0,)
    features = features or analyze_audio_features(bars, _feature_state(state))
    frame = anim_clock(state)
    ms = _motion_scale(state)
    dot_rows, dot_cols = height * 4, width * 2
    grad = _gradient_for(game_tag) if use_color else None
    size = dot_rows * dot_cols
    inten = [0.0] * size
    hue = [50] * size

    n = 820
    pts = _orb_sphere_points(n)
    n_bars = len(bars)

    # Per-vertex spike envelope: quick attack toward the band energy, slow
    # gravity release — both fps-independent so spikes feel identical at any rate.
    sp = state.get("orb_spikes")
    if sp is None or len(sp) != n:
        sp = [0.0] * n
        state["orb_spikes"] = sp
    attack = 1.0 - (0.45 ** ms)     # ~0.55 per frame at 30fps
    release = 0.90 ** ms

    # Beat pulse: the whole orb breathes outward on a kick.
    pulse = state.get("orb_pulse", 0.0) * (0.82 ** ms) + min(1.0, features.onset * 2.2)
    state["orb_pulse"] = pulse

    # Camera / rotation (time-based → constant speed regardless of fps).
    # Eye-level orbit: yaw spins the orb (= us walking around it); pitch stays ~0
    # so we look at it straight on. A whisper of pitch keeps it from looking like a
    # flat spinning pinwheel.
    yaw = frame * 0.018
    pitch = 0.08
    cyaw, syaw = math.cos(yaw), math.sin(yaw)
    cpit, spit = math.cos(pitch), math.sin(pitch)
    cam = 2.7
    fscale = min(dot_cols, dot_rows) * 0.61    # ~33% larger on screen
    cx = (dot_cols - 1) / 2.0
    cyc = (dot_rows - 1) / 2.0
    bob = math.sin(frame * 0.013) * dot_rows * 0.025   # subtle float
    base_r = 0.56 + pulse * 0.18                # beats visibly pump the whole orb
    overall = features.overall

    # Fixed world-space light: as the orb spins, its surface rotates THROUGH the
    # light, so the bright spot stays put while dots flow past it — that's what
    # sells "solid rotating sphere" instead of "transparent beehive".
    lx, ly, lz = 0.50, 0.62, 0.60
    _ln = 1.0 / math.sqrt(lx * lx + ly * ly + lz * lz)
    lx *= _ln; ly *= _ln; lz *= _ln

    for i in range(n):
        x0, y0, z0 = pts[i]
        band = bars[(i * n_bars) // n]
        # Amplified so normal-volume music makes real spikes (band*band alone
        # crushed everything below "loud" into a near-static ball).
        target = band * band * 2.6
        if target > 1.0:
            target = 1.0
        if target > sp[i]:
            sp[i] += (target - sp[i]) * attack
        else:
            sp[i] *= release
        spike = sp[i]

        # Rotate the unit direction (yaw about Y, then pitch about X) -> normal.
        xr = x0 * cyaw + z0 * syaw
        zr0 = -x0 * syaw + z0 * cyaw
        yr = y0 * cpit - zr0 * spit
        zr = y0 * spit + zr0 * cpit

        # Backface cull: only the camera-facing hemisphere draws, so you no longer
        # see through to the far shell. Side spikes (near the silhouette) still show.
        if zr < -0.15:
            continue

        # Lambert shading from the fixed light -> a lit ball with a bright spot.
        lambert = xr * lx + yr * ly + zr * lz
        if lambert < 0.0:
            lambert = 0.0
        surf = 0.10 + 0.78 * lambert

        tip_r = base_r + spike * 1.45               # longer, more dramatic spikes
        steps = 1 + int(spike * 10.0)             # longer spikes = more dots
        inv_steps = 1.0 / steps
        for s in range(steps + 1):
            t = s * inv_steps
            rr = base_r + (tip_r - base_r) * t
            depth = cam - zr * rr
            if depth < 0.25:
                continue
            inv = fscale / depth
            sx = cx + xr * rr * inv
            sy = cyc - yr * rr * inv + bob
            if t < 0.001:
                bright = surf * (0.72 + overall * 0.28)         # lit body
            else:
                bright = (0.4 + 0.6 * surf) * (0.22 + 0.9 * t) * (0.5 + spike)  # glowing spike
            if bright <= 0.05:
                continue
            hcol = int(30.0 + spike * 120.0 + t * 24.0 + lambert * 18.0)
            hcol = 0 if hcol < 0 else (100 if hcol > 100 else hcol)
            _plot(inten, hue, dot_rows, dot_cols, sx, sy, bright if bright < 1.0 else 1.0, hcol)

    return _braille_field(inten, hue, dot_rows, dot_cols, height, width, grad,
                          use_color=use_color, threshold=0.05)


# One entry point so callers don't carry a giant if/elif.  Each renderer is
# adapted to a uniform (mode, bars, height, width, ctx) signature; `ctx` carries
# the shared smoothing buffers and a dict of per-mode persistent state.  Adding a
# new mode is one @_vis(...) decorator here plus its name in VIS_MODES.

# Static modes are pure functions of the smoothed bars, so ui.py can cache them.
STATIC_VIS_MODES = frozenset(("bars", "shades", "outline", "spectrum"))
ASCII_SAFE_MODES = frozenset(("ascii", "bars", "peaks", "shades", "outline", "spectrum", "features"))


class VisFrameCtx:
    """Shared per-frame inputs for the visualizer dispatch."""
    __slots__ = ("states", "cap_pos", "peak_bars", "trail_bars", "use_color", "game_tag", "features", "snapshot", "label")

    def __init__(self, states, *, cap_pos=None, peak_bars=None, trail_bars=None,
                 use_color=True, game_tag=None, features=None, snapshot=None):
        self.states = states            # dict: mode-name -> that mode's state dict
        self.cap_pos = cap_pos
        self.peak_bars = peak_bars
        self.trail_bars = trail_bars
        self.use_color = use_color
        self.game_tag = game_tag
        self.features = features
        self.snapshot = snapshot
        self.label = None

    def state(self, name):
        return self.states.setdefault(name, {})


_VIS_DISPATCH = {}


def _vis(*modes):
    def deco(fn):
        for m in modes:
            _VIS_DISPATCH[m] = fn
        return fn
    return deco


@_vis("flame")
def _vf_flame(mode, bars, h, w, ctx):
    return flame_render_lines(bars, h, w, ctx.state("flame"), use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("wave")
def _vf_wave(mode, bars, h, w, ctx):
    return braille_wave_lines(
        bars, h, w,
        use_color=ctx.use_color, game_tag=ctx.game_tag,
        snapshot=ctx.snapshot, state=ctx.state("wave"),
    )


@_vis("scope")
def _vf_scope(mode, bars, h, w, ctx):
    st = ctx.state("scope")
    st["frame"] = st.get("frame", 0) + 1
    return braille_scope_lines(
        bars, h, w, st["frame"],
        use_color=ctx.use_color, game_tag=ctx.game_tag,
        snapshot=ctx.snapshot, state=st,
    )


@_vis("butterfly")
def _vf_butterfly(mode, bars, h, w, ctx):
    return butterfly_render_lines(bars, h, w, ctx.state("butterfly"), use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("led_matrix")
def _vf_led(mode, bars, h, w, ctx):
    return led_matrix_lines(bars, h, w, peak_bars=ctx.cap_pos, use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("matrix_rain")
def _vf_matrix(mode, bars, h, w, ctx):
    return matrix_rain_lines(bars, h, w, ctx.state("matrix_rain"), use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("heartbeat")
def _vf_heartbeat(mode, bars, h, w, ctx):
    return heartbeat_render_lines(bars, h, w, ctx.state("heartbeat"), use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("braille")
def _vf_braille(mode, bars, h, w, ctx):
    return braille_spectrum_lines(bars, h, w, peak_bars=ctx.cap_pos, use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("ascii")
def _vf_ascii(mode, bars, h, w, ctx):
    return ascii_bars_lines(bars, h, w, state=ctx.state("ascii"), use_color=ctx.use_color, game_tag=ctx.game_tag)


@_vis("fireworks")
def _vf_fireworks(mode, bars, h, w, ctx):
    return fireworks_render_lines(
        bars, h, w, ctx.state("fireworks"),
        use_color=ctx.use_color, game_tag=ctx.game_tag, features=ctx.features,
    )


@_vis("starfield")
def _vf_starfield(mode, bars, h, w, ctx):
    return starfield_render_lines(
        bars, h, w, ctx.state("starfield"),
        use_color=ctx.use_color, game_tag=ctx.game_tag, features=ctx.features,
    )


@_vis("ripple")
def _vf_ripple(mode, bars, h, w, ctx):
    return ripple_render_lines(
        bars, h, w, ctx.state("ripple"),
        use_color=ctx.use_color, game_tag=ctx.game_tag, features=ctx.features,
    )


@_vis("aurora")
def _vf_aurora(mode, bars, h, w, ctx):
    return aurora_render_lines(
        bars, h, w, ctx.state("aurora"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("orb3d")
def _vf_orb3d(mode, bars, h, w, ctx):
    return orb3d_render_lines(
        bars, h, w, ctx.state("orb3d"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("kaleido_tunnel")
def _vf_kaleido_tunnel(mode, bars, h, w, ctx):
    return kaleido_tunnel_render_lines(
        bars, h, w, ctx.state("kaleido_tunnel"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("liquid_scope")
def _vf_liquid_scope(mode, bars, h, w, ctx):
    return liquid_scope_render_lines(
        bars, h, w, ctx.state("liquid_scope"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("plasma_bloom")
def _vf_plasma_bloom(mode, bars, h, w, ctx):
    return plasma_bloom_render_lines(
        bars, h, w, ctx.state("plasma_bloom"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("milkdrop")
def _vf_milkdrop(mode, bars, h, w, ctx):
    st = ctx.state("milkdrop")
    rows = milkdrop_render_lines(
        bars, h, w, st,
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )
    ctx.label = st.get("display_label") or "milkdrop"
    return rows


@_vis("polar")
def _vf_polar(mode, bars, h, w, ctx):
    return polar_spectrum_render_lines(
        bars, h, w, ctx.state("polar"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("chroma")
def _vf_chroma(mode, bars, h, w, ctx):
    return chroma_wheel_render_lines(
        bars, h, w, ctx.state("chroma"),
        features=ctx.features, use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("features")
def _vf_features(mode, bars, h, w, ctx):
    return features_debug_lines(
        bars, h, w, ctx.state("features"),
        features=ctx.features, snapshot=ctx.snapshot,
        use_color=ctx.use_color, game_tag=ctx.game_tag,
    )


@_vis("bars", "peaks", "shades", "outline", "spectrum")
def _vf_spectrum(mode, bars, h, w, ctx):
    pass_peaks = ctx.cap_pos if mode == "peaks" else ctx.peak_bars
    return spectrum_lines(bars, height=h, use_color=ctx.use_color, mode=mode,
                          trail_bars=ctx.trail_bars, peak_bars=pass_peaks, game_tag=ctx.game_tag)


def render_frame(mode, bars, height, width, ctx):
    """Render one visualizer frame for `mode`. Unknown modes fall back to bars."""
    requested_mode = mode
    if ASCII_ONLY and mode not in ASCII_SAFE_MODES:
        mode = "ascii"
        ctx.label = f"{requested_mode}/ascii"
    if ctx.snapshot is not None:
        bars = ctx.snapshot.bars
        if ctx.features is None:
            ctx.features = ctx.snapshot.features
    if ctx.features is None:
        ctx.features = analyze_audio_features(bars, ctx.state("_audio"))
    if _SPECTRUM_SCALE_ACTIVE:
        # Features above stay on the raw bars; only the drawn heights are scaled.
        # Scale the peak/trail/cap views too so caps and trails stay aligned.
        bars = apply_spectrum_scale(bars)
        if ctx.peak_bars is not None:
            ctx.peak_bars = apply_spectrum_scale(ctx.peak_bars)
        if ctx.trail_bars is not None:
            ctx.trail_bars = apply_spectrum_scale(ctx.trail_bars)
        if ctx.cap_pos is not None:
            ctx.cap_pos = apply_spectrum_scale(ctx.cap_pos)
    fn = _VIS_DISPATCH.get(mode, _vf_spectrum)
    return fn(mode, bars, height, width, ctx)


# ─── Preset shuffle ───────────────────────────────────────────────────────────
# MilkDrop's signature wasn't a single effect — it was an endless shuffle of
# presets that drifted and snapped on beats.  These are the lively, full-frame
# modes worth auto-cycling through (the static bars/peaks/etc. are excluded).
SHUFFLE_MODES = (
    "spectrum", "flame", "wave", "scope", "butterfly", "matrix_rain",
    "heartbeat", "fireworks", "starfield", "ripple", "aurora",
    "kaleido_tunnel", "liquid_scope", "polar", "chroma",
)


def next_shuffle_mode(current, rng=None):
    """Pick the next shuffle preset, never repeating the current one."""
    rng = rng or random
    pool = [m for m in SHUFFLE_MODES if m != current] or list(SHUFFLE_MODES)
    return rng.choice(pool)


def step_smooth_bars(
    bars, smooth_bars, peak_bars, trail_bars, cap_pos, cap_vel,
    rise_alpha, fall_alpha, trail_alpha, peak_alpha, dt,
):
    """Return updated (smooth_bars, peak_bars, trail_bars, cap_pos, cap_vel).

    Physics-based per-bar smoothing: exponential attack/decay + gravity-launched
    peak cap. Pure function — all inputs/outputs are plain lists of floats.
    """
    _GRAVITY = 4.5
    _LAUNCH_BASE = 1.0
    _LAUNCH_GAIN = 1.8
    smoothed = []
    new_peaks = []
    new_trail = []
    new_cap_pos = []
    new_cap_vel = []
    for i, b in enumerate(bars):
        prev = smooth_bars[i]
        s = prev * rise_alpha + b * (1.0 - rise_alpha) if b >= prev else prev * fall_alpha + b * (1.0 - fall_alpha)
        smoothed.append(s)
        new_peaks.append(max(s, peak_bars[i] * peak_alpha))
        new_trail.append(max(s, trail_bars[i] * trail_alpha))
        pos = cap_pos[i]
        vel = cap_vel[i]
        if s >= pos - 0.005:
            vel = _LAUNCH_BASE + _LAUNCH_GAIN * max(0.0, s - pos)
            pos = s
        else:
            vel -= _GRAVITY * dt
            pos += vel * dt
            if pos < s:
                pos = s
                vel = 0.0
        new_cap_pos.append(max(0.0, min(1.0, pos)))
        new_cap_vel.append(vel)
    return smoothed, new_peaks, new_trail, new_cap_pos, new_cap_vel


def update_bass_energy(smooth_bars, bass_energy, rise_alpha, dt):
    """Return updated bass energy scalar from the low-frequency smooth bars."""
    n_bass = max(1, len(smooth_bars) // 8)
    raw_bass = sum(smooth_bars[:n_bass]) / n_bass
    fall_alpha = smoothing_alpha_ms(80.0, dt)
    if raw_bass >= bass_energy:
        return bass_energy * rise_alpha + raw_bass * (1.0 - rise_alpha)
    return bass_energy * fall_alpha + raw_bass * (1.0 - fall_alpha)

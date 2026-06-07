import os, re, math, unicodedata

from ac_ui.constants import (
    VIS_BAR_BLOCKS, VIS_SHADE_BLOCKS, VIS_PEAK_GLYPHS, SUPERSCRIPT,
)

USE_COLOR = os.environ.get("NO_COLOR") is None
def c(text, code):
    if not USE_COLOR:
        return text
    return f"[{code}m{text}[0m"

def c256(text, code):
    if not USE_COLOR:
        return text
    return f"[38;5;{code}m{text}[0m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s):
    return ANSI_RE.sub("", s)

def char_cell_width(ch):
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

def plain_visible_len(s):
    return sum(char_cell_width(ch) for ch in s)

def visible_len(s):
    return plain_visible_len(strip_ansi(s))

def smoothing_alpha_ms(response_ms, dt_seconds):
    if response_ms <= 0:
        return 0.0
    tau = max(0.001, response_ms / 1000.0)
    dt = max(0.0, float(dt_seconds))
    return math.exp(-dt / tau)

def _make_gradient(c_start, c_end, steps=101):
    return tuple(int(c_start + (c_end - c_start) * i / max(1, steps - 1))
                 for i in range(steps))

_GRAD_SPECTRUM  = _make_gradient(27,  196, 101)   # blue → red  (default)
_GRAD_AC_GREEN  = _make_gradient(22,  156, 101)   # dark-green → yellow-green
_GRAD_PLAYBACK  = _make_gradient(39,  46,  101)   # teal → bright-green
_GRAD_VOLUME    = _make_gradient(46,  220, 101)   # green → gold
_GRAD_HOT       = _make_gradient(196, 226, 101)   # red → yellow (flame hot)

# Time-of-day gradient pairs: (start_color, end_color) for each hour 0-23.
# Each pair tints the visualizer and all progress bars to feel like that time.
_TOD_GRAD_PAIRS = [
    (17,  93),   #  0 midnight:     deep blue → violet
    (17,  93),   #  1
    (17,  57),   #  2 late night:   deep blue → indigo
    (17,  57),   #  3
    (57,  99),   #  4 pre-dawn:     indigo → medium purple
    (130, 170),  #  5 dawn:         burnt orange → soft magenta
    (166, 220),  #  6 sunrise:      orange → gold
    (178, 226),  #  7 morning:      gold → bright yellow
    (154, 220),  #  8 late morning: yellow-green → gold
    (46,  154),  #  9 mid-morning:  bright green → lime
    (51,   39),  # 10 approaching noon: cyan → sky
    (39,   51),  # 11 late morning: sky → cyan
    (33,   51),  # 12 noon:         bright blue → cyan
    (27,   39),  # 13 early afternoon: blue → teal
    (27,   39),  # 14 afternoon:    blue → teal
    (27,   99),  # 15 late afternoon: blue → purple
    (27,   99),  # 16 pre-evening:  blue → purple
    (208, 220),  # 17 golden hour:  orange → gold
    (196, 208),  # 18 evening:      red → orange
    (160, 208),  # 19 dusk:         dark red → orange
    (93,  196),  # 20 early night:  violet → red
    (93,  129),  # 21 night:        violet → magenta
    (57,   93),  # 22 late night:   indigo → violet
    (17,   57),  # 23 pre-midnight: deep blue → indigo
]

# --------------------------------------------------------------------------- #
# Named themes — alternative time-of-day palettes                             #
# --------------------------------------------------------------------------- #

_THEME_FOREST = [
    (22,  58),   #  0 midnight:     dark green → dark olive
    (22,  58),   #  1
    (22,  22),   #  2 late night:   deep forest
    (22,  22),   #  3
    (58,  100),  #  4 pre-dawn:     olive → purple-brown
    (130, 172),  #  5 dawn:         sienna → tan
    (130, 178),  #  6 sunrise:      burnt orange → gold-amber
    (178, 190),  #  7 morning:      amber → bright lime
    (154, 148),  #  8 late morning: lime-green → tan
    (40,  154),  #  9 mid-morning:  green → lime
    (34,   40),  # 10 approaching noon: forest → bright-green
    (40,   34),  # 11
    (34,   40),  # 12 noon:         forest green cycle
    (28,   34),  # 13 early afternoon: dark-green → medium-green
    (28,   34),  # 14 afternoon
    (58,  130),  # 15 late afternoon: olive → sienna
    (130, 166),  # 16 pre-evening:  sienna → rust
    (130, 172),  # 17 golden hour:  sienna → tan
    (166, 130),  # 18 evening:      rust → sienna
    (130, 94),   # 19 dusk:         sienna → dark brown
    (58,   94),  # 20 early night:  olive → brown
    (58,   22),  # 21 night:        olive → dark-green
    (22,   58),  # 22 late night
    (22,   22),  # 23 pre-midnight
]

_THEME_NIGHT = [
    (17,   57),  #  0 midnight:     deep blue → indigo
    (17,   57),  #  1
    (17,   17),  #  2 late night:   deep blue
    (17,   17),  #  3
    (17,   57),  #  4 pre-dawn:     deep blue → indigo
    (57,   93),  #  5 dawn:         indigo → violet
    (57,   99),  #  6 sunrise:      indigo → purple
    (57,   63),  #  7 morning:      indigo → sky-blue
    (27,   63),  #  8 late morning: blue → sky
    (27,   39),  #  9 mid-morning:  blue → teal
    (33,   39),  # 10 approaching noon: blue → teal
    (39,   27),  # 11 late morning: teal → blue
    (27,   39),  # 12 noon:         blue → teal
    (27,   57),  # 13 early afternoon: blue → indigo
    (57,   93),  # 14 afternoon:    indigo → violet
    (93,   57),  # 15 late afternoon: violet → indigo
    (57,   27),  # 16 pre-evening:  indigo → blue
    (27,   57),  # 17 golden hour:  blue → indigo
    (57,   93),  # 18 evening:      indigo → violet
    (93,  129),  # 19 dusk:         violet → magenta
    (93,   57),  # 20 early night:  violet → indigo
    (57,   17),  # 21 night:        indigo → deep blue
    (17,   57),  # 22 late night
    (17,   17),  # 23 pre-midnight
]

_THEME_WARM = [
    (52,   88),  #  0 midnight:     deep red → crimson
    (52,   88),  #  1
    (52,   52),  #  2 late night:   deep red
    (52,   52),  #  3
    (88,  124),  #  4 pre-dawn:     crimson → dark red
    (124, 160),  #  5 dawn:         dark red → red
    (160, 208),  #  6 sunrise:      red → orange
    (208, 220),  #  7 morning:      orange → gold
    (220, 226),  #  8 late morning: gold → bright yellow
    (220, 214),  #  9 mid-morning:  gold → light orange
    (214, 220),  # 10 approaching noon: light orange → gold
    (220, 214),  # 11
    (214, 220),  # 12 noon:         gold cycle
    (220, 208),  # 13 early afternoon: gold → orange
    (208, 166),  # 14 afternoon:    orange → dark orange
    (166, 160),  # 15 late afternoon: dark-orange → red
    (160, 196),  # 16 pre-evening:  red → bright red
    (196, 208),  # 17 golden hour:  red → orange
    (208, 166),  # 18 evening:      orange → dark orange
    (160, 124),  # 19 dusk:         red → dark red
    (124,  88),  # 20 early night:  dark red → crimson
    (88,   52),  # 21 night:        crimson → deep red
    (52,   88),  # 22 late night
    (52,   52),  # 23 pre-midnight
]

THEMES = {
    "default": _TOD_GRAD_PAIRS,
    "forest":  _THEME_FOREST,
    "night":   _THEME_NIGHT,
    "warm":    _THEME_WARM,
}
THEME_NAMES = list(THEMES.keys())

_active_theme_pairs = _TOD_GRAD_PAIRS  # which palette is currently active
_tod_grad_cache: dict = {}

def set_theme(name: str):
    global _active_theme_pairs, _tod_grad_cache
    pairs = THEMES.get(name, _TOD_GRAD_PAIRS)
    if pairs is _active_theme_pairs:
        return
    _active_theme_pairs = pairs
    _tod_grad_cache = {}  # flush so _grad_for_hour rebuilds on next call

def get_theme() -> str:
    for name, pairs in THEMES.items():
        if pairs is _active_theme_pairs:
            return name
    return "default"

def _grad_for_hour(h: int) -> tuple:
    """Return (or build) the 101-step time-of-day gradient for hour h."""
    h = int(h) % 24
    if h not in _tod_grad_cache:
        s, e = _active_theme_pairs[h]
        _tod_grad_cache[h] = _make_gradient(s, e, 101)
    return _tod_grad_cache[h]

_active_tod_grad = _GRAD_SPECTRUM  # updated each render frame via _grad_for_hour()

def gradient_at(grad, value_0_100):
    """Look up a pre-computed gradient at a 0-100 position."""
    idx = max(0, min(100, int(value_0_100)))
    return grad[idx]

def gradient_bar(value_pct, width, grad=None, bg_color=235):
    """Btop-style horizontal meter bar with gradient fill + dim background."""
    if grad is None:
        grad = _GRAD_PLAYBACK
    filled = max(0, min(width, int(round(value_pct / 100.0 * width))))
    out_parts = []
    for i in range(filled):
        col = gradient_at(grad, round(i / max(1, width - 1) * 100))
        out_parts.append(f"[38;5;{col}m█")
    if filled < width:
        out_parts.append(f"[38;5;{bg_color}m" + "░" * (width - filled))
    out_parts.append("[0m")
    return "".join(out_parts)

def solid_bar(value_pct, width, fill_color, track_color=238):
    """Solid-color progress bar with a visible dash track showing the full bar extent."""
    filled = max(0, min(width, int(round(value_pct / 100.0 * width))))
    parts = []
    if filled > 0:
        parts.append(f"[38;5;{fill_color}m" + "█" * filled)
    if filled < width:
        parts.append(f"[38;5;{track_color}m" + "─" * (width - filled))
    parts.append("[0m")
    return "".join(parts)

# ── btop Symbols: defined near top of file, before HELP_LINES_BASE ───────────

def superscript_num(n):
    """Convert a small integer to superscript Unicode digits (btop pattern)."""
    return "".join(SUPERSCRIPT[int(d)] for d in str(max(0, n)) if d.isdigit())

def humanize_seconds(sec):
    """Btop sec_to_dhms: compact mm:ss or h:mm:ss track duration."""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def humanize_bytes(b):
    """Btop floating_humanizer: compact file-size string (KiB/MiB)."""
    b = max(0, b)
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KiB"
    if b < 1024 ** 3:
        return f"{b/1024**2:.1f} MiB"
    return f"{b/1024**3:.2f} GiB"


def spectrum_color(i, n, row_norm=None, game_tag=None, energy=None):
    """Return ANSI-256 color for bar i-of-n, optionally height-tinted or game-themed."""
    t = (i / max(1, n - 1)) if n > 1 else 1.0
    boost = int((energy or 0.0) * 20)
    if game_tag and game_tag != "ALL":
        # AC-themed: dark-green bass → yellow-green highs
        return gradient_at(_GRAD_AC_GREEN, int(t * 100))
    if row_norm is not None:
        # Height-based color: use time-of-day gradient (warm at top, cool at bottom)
        return gradient_at(_active_tod_grad, min(100, int(row_norm * 100) + boost))
    return gradient_at(_active_tod_grad, min(100, int(t * 100) + boost))


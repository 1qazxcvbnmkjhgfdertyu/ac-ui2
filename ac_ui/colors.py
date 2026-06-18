import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass

from ac_ui.constants import SUPERSCRIPT


RESET = "\x1b[0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class TerminalCapabilities:
    color_mode: str
    use_color: bool
    truecolor: bool
    ascii_only: bool
    unicode_ok: bool
    braille_ok: bool


def _env_truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _stdout_encoding() -> str:
    raw = os.environ.get("PYTHONIOENCODING", "")
    if raw:
        return raw.split(":", 1)[0]
    return getattr(sys.stdout, "encoding", "") or ""


def _normalize_color_mode(value) -> str:
    raw = str(value or "auto").strip().lower()
    aliases = {
        "": "auto",
        "default": "auto",
        "ansi16": "16",
        "ansi256": "256",
        "24bit": "truecolor",
        "24-bit": "truecolor",
        "rgb": "truecolor",
        "false": "none",
        "off": "none",
        "0": "none",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in {"auto", "none", "16", "256", "truecolor"} else "auto"


def detect_terminal_capabilities(env=None, stdout_encoding: str | None = None) -> TerminalCapabilities:
    env = os.environ if env is None else env
    encoding = str(stdout_encoding if stdout_encoding is not None else _stdout_encoding())
    unicode_ok = "utf" in encoding.lower()
    tty_mode = _env_truthy(env.get("AC_UI_TTY"))
    ascii_only = _env_truthy(env.get("AC_UI_ASCII_ONLY")) or not unicode_ok or tty_mode

    color_mode = _normalize_color_mode(env.get("AC_UI_COLOR_MODE", "auto"))
    if tty_mode:
        # Accessible mode: plain text, no color, no box-drawing.
        color_mode = "none"
    if color_mode == "auto":
        term = str(env.get("TERM", "")).lower()
        colorterm = str(env.get("COLORTERM", "")).lower()
        term_program = str(env.get("TERM_PROGRAM", "")).lower()
        if env.get("NO_COLOR") is not None or term == "dumb":
            color_mode = "none"
        elif (
            "truecolor" in colorterm
            or "24bit" in colorterm
            or term_program in {"wezterm", "ghostty"}
        ):
            color_mode = "truecolor"
        elif "256color" in term:
            color_mode = "256"
        elif term:
            color_mode = "16"
        else:
            color_mode = "none"

    return TerminalCapabilities(
        color_mode=color_mode,
        use_color=(color_mode != "none"),
        truecolor=(color_mode == "truecolor"),
        ascii_only=ascii_only,
        unicode_ok=unicode_ok,
        braille_ok=(unicode_ok and not ascii_only),
    )


_TERMINAL_CAPS = detect_terminal_capabilities()
COLOR_MODE = _TERMINAL_CAPS.color_mode
USE_COLOR = _TERMINAL_CAPS.use_color
TRUECOLOR = _TERMINAL_CAPS.truecolor
ASCII_ONLY = _TERMINAL_CAPS.ascii_only
UNICODE_OK = _TERMINAL_CAPS.unicode_ok
BRAILLE_OK = _TERMINAL_CAPS.braille_ok


def terminal_capabilities() -> TerminalCapabilities:
    return _TERMINAL_CAPS


@dataclass(frozen=True)
class TerminalColor:
    r: int
    g: int
    b: int
    ansi: int

    @property
    def rgb(self) -> tuple[int, int, int]:
        return self.r, self.g, self.b

    def __int__(self) -> int:
        return int(self.ansi)

    def __str__(self) -> str:
        return str(self.ansi)


def _clamp8(value):
    return max(0, min(255, int(round(value))))


_ANSI16 = (
    (0x00, 0x00, 0x00),
    (0x80, 0x00, 0x00),
    (0x00, 0x80, 0x00),
    (0x80, 0x80, 0x00),
    (0x00, 0x00, 0x80),
    (0x80, 0x00, 0x80),
    (0x00, 0x80, 0x80),
    (0xc0, 0xc0, 0xc0),
    (0x80, 0x80, 0x80),
    (0xff, 0x00, 0x00),
    (0x00, 0xff, 0x00),
    (0xff, 0xff, 0x00),
    (0x5c, 0x5c, 0xff),
    (0xff, 0x00, 0xff),
    (0x00, 0xff, 0xff),
    (0xff, 0xff, 0xff),
)
_ANSI_CUBE = (0, 95, 135, 175, 215, 255)


def ansi256_to_rgb(code: int) -> tuple[int, int, int]:
    code = max(0, min(255, int(code)))
    if code < 16:
        return _ANSI16[code]
    if code < 232:
        idx = code - 16
        r = _ANSI_CUBE[idx // 36]
        g = _ANSI_CUBE[(idx // 6) % 6]
        b = _ANSI_CUBE[idx % 6]
        return r, g, b
    gray = 8 + (code - 232) * 10
    return gray, gray, gray


_ANSI256_PALETTE = tuple(ansi256_to_rgb(i) for i in range(256))


def ansi256_from_rgb(rgb: tuple[int, int, int]) -> int:
    r, g, b = (_clamp8(c) for c in rgb)
    best_idx = 0
    best_dist = None
    for idx, (pr, pg, pb) in enumerate(_ANSI256_PALETTE):
        dist = ((pr - r) * (pr - r)) + ((pg - g) * (pg - g)) + ((pb - b) * (pb - b))
        if best_dist is None or dist < best_dist:
            best_idx = idx
            best_dist = dist
    return best_idx


def ansi16_from_rgb(rgb: tuple[int, int, int]) -> int:
    r, g, b = (_clamp8(c) for c in rgb)
    best_idx = 0
    best_dist = None
    for idx, (pr, pg, pb) in enumerate(_ANSI16):
        dist = ((pr - r) * (pr - r)) + ((pg - g) * (pg - g)) + ((pb - b) * (pb - b))
        if best_dist is None or dist < best_dist:
            best_idx = idx
            best_dist = dist
    return best_idx


def _to_terminal_color(value) -> TerminalColor:
    if isinstance(value, TerminalColor):
        return value
    if isinstance(value, int):
        r, g, b = ansi256_to_rgb(value)
        return TerminalColor(r, g, b, value)
    if isinstance(value, (tuple, list)) and len(value) == 3:
        rgb = tuple(_clamp8(c) for c in value)
        return TerminalColor(rgb[0], rgb[1], rgb[2], ansi256_from_rgb(rgb))
    raise TypeError(f"Unsupported color value: {value!r}")


_color_code_cache: dict = {}


def color_code(value, *, background=False) -> str:
    # Color values resolve to a small finite set per frame and COLOR_MODE is
    # fixed at startup, so memoize the (value, bg) -> escape-body mapping. This
    # collapses hundreds of thousands of identical recomputations per frame.
    try:
        key = (value, background)
        cached = _color_code_cache.get(key)
        if cached is not None:
            return cached
    except TypeError:
        key = None
    result = _color_code_uncached(value, background=background)
    if key is not None:
        _color_code_cache[key] = result
    return result


def _color_code_uncached(value, *, background=False) -> str:
    color = _to_terminal_color(value)
    if COLOR_MODE == "truecolor":
        prefix = "48" if background else "38"
        return f"{prefix};2;{color.r};{color.g};{color.b}"
    if COLOR_MODE == "256":
        prefix = "48" if background else "38"
        return f"{prefix};5;{color.ansi}"
    ansi16 = ansi16_from_rgb(color.rgb)
    if ansi16 < 8:
        base = 40 if background else 30
        return str(base + ansi16)
    base = 100 if background else 90
    return str(base + (ansi16 - 8))


_sgr_cache: dict = {}


def sgr(*, fg=None, bg=None, bold=False, dim=False) -> str:
    if not USE_COLOR:
        return ""
    try:
        key = (fg, bg, bold, dim)
        cached = _sgr_cache.get(key)
        if cached is not None:
            return cached
    except TypeError:
        key = None
    parts = []
    if bold:
        parts.append("1")
    if dim:
        parts.append("2")
    if fg is not None:
        parts.append(color_code(fg))
    if bg is not None:
        parts.append(color_code(bg, background=True))
    result = f"\x1b[{';'.join(parts)}m" if parts else ""
    if key is not None:
        _sgr_cache[key] = result
    return result


def paint(text, *, fg=None, bg=None, bold=False, dim=False) -> str:
    if not USE_COLOR:
        return text
    return f"{sgr(fg=fg, bg=bg, bold=bold, dim=dim)}{text}{RESET}"


def c(text, code):
    if not USE_COLOR:
        return text
    return f"\x1b[{code}m{text}{RESET}"


def c256(text, code):
    return paint(text, fg=code)


def strip_ansi(s):
    return ANSI_RE.sub("", s)


_cell_width_cache: dict = {}


def char_cell_width(ch):
    # Per-character display width, memoized. Called ~1M+ times per frame over a
    # tiny set of distinct characters, so caching turns it into a dict lookup.
    w = _cell_width_cache.get(ch)
    if w is not None:
        return w
    if not ch:
        return 0
    if unicodedata.combining(ch):
        w = 0
    else:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    _cell_width_cache[ch] = w
    return w


def plain_visible_len(s):
    # Fast path: pure-ASCII text is always one cell per char (no wide/combining).
    if s.isascii():
        return len(s)
    return sum(char_cell_width(ch) for ch in s)


def visible_len(s):
    # Fast path: plain ASCII with no escape sequences needs no measurement.
    if s.isascii() and "\x1b" not in s:
        return len(s)
    return plain_visible_len(strip_ansi(s))


def smoothing_alpha_ms(response_ms, dt_seconds):
    if response_ms <= 0:
        return 0.0
    tau = max(0.001, response_ms / 1000.0)
    dt = max(0.0, float(dt_seconds))
    return math.exp(-dt / tau)


def _rgb_lerp(start, end, t):
    sr, sg, sb = _to_terminal_color(start).rgb
    er, eg, eb = _to_terminal_color(end).rgb
    return (
        _clamp8(sr + (er - sr) * t),
        _clamp8(sg + (eg - sg) * t),
        _clamp8(sb + (eb - sb) * t),
    )


def _make_gradient(c_start, c_end, steps=101):
    if steps <= 1:
        return (_to_terminal_color(c_start),)
    return tuple(
        _to_terminal_color(_rgb_lerp(c_start, c_end, i / max(1, steps - 1)))
        for i in range(steps)
    )


def _make_multistop_gradient(stops, steps=101):
    resolved = [_to_terminal_color(stop) for stop in stops]
    if not resolved:
        return tuple()
    if len(resolved) == 1:
        return tuple(resolved[0] for _ in range(max(1, steps)))
    out = []
    segments = len(resolved) - 1
    for i in range(max(1, steps)):
        t = i / max(1, steps - 1)
        pos = min(segments, t * segments)
        idx = min(segments - 1, int(pos))
        local_t = pos - idx
        out.append(_to_terminal_color(_rgb_lerp(resolved[idx], resolved[idx + 1], local_t)))
    return tuple(out)


# ── Crayola / pastel RGB anchors ────────────────────────────────────────────

_CRAYOLA = {
    "periwinkle": (197, 208, 230),
    "sky_blue": (128, 218, 235),
    "sea_foam_green": (159, 226, 191),
    "aquamarine": (120, 219, 226),
    "orchid": (230, 168, 215),
    "lavender": (252, 180, 213),
    "carnation_pink": (255, 170, 204),
    "pink_sherbet": (247, 143, 167),
    "peach": (255, 207, 171),
    "macaroni_and_cheese": (255, 189, 136),
    "banana_mania": (250, 231, 181),
    "unmellow_yellow": (255, 255, 102),
    "magic_mint": (170, 240, 209),
    "blizzard_blue": (172, 229, 238),
    "wisteria": (205, 164, 222),
    "cornflower": (154, 206, 235),
}


_BASE_THEME_ROLES = {
    "title": 95,
    "accent": 82,
    "accent_soft": 68,
    "value": 78,
    "value_soft": 62,
    "label": 55,
    "label_dim": 40,
    "border": 28,
    "border_hi": 96,
    "pulse": 92,
    "track_fill": 78,
    "track_bg": 22,
    "panel_title": 90,
    "panel_subtitle": 65,
    "good": (116, 220, 156),
    "warning": (255, 214, 122),
    "danger": (255, 107, 129),
    "focus_bg": "accent_soft",
    "focus_fg": (24, 28, 38),
}


_BASE_THEME_ART = {
    "font": "standard",
    "mode": "sweep",
    "palette": ("accent_soft", "accent", "title"),
    "outline": "border_hi",
}

_BASE_THEME_VIZ = {
    "spectrum": ("track_bg", "accent_soft", "accent", "title"),
    "spectrum_active": ("good", "accent_soft", "title"),
    "tip": ("accent", "title"),
    "flame": ("track_bg", "accent_soft", "title"),
    "rain": ("label_dim", "accent_soft", "title"),
    "heartbeat": ("track_bg", "accent_soft", "title"),
}

_BASE_THEME_CHROME = {
    "box_chars": {
        "tl": "╭",
        "tr": "╮",
        "bl": "╰",
        "br": "╯",
        "h": "─",
        "v": "│",
    },
    "title_left": "┤",
    "title_right": "├",
    "section_left": "├",
    "section_right": "┤",
    "header_left": "┤",
    "header_right": "├",
    "divider": "─",
    "separator": "─",
}

_ASCII_THEME_CHROME = {
    "box_chars": {
        "tl": "+",
        "tr": "+",
        "bl": "+",
        "br": "+",
        "h": "-",
        "v": "|",
    },
    "title_left": "+",
    "title_right": "+",
    "section_left": "+",
    "section_right": "+",
    "header_left": "+",
    "header_right": "+",
    "divider": "-",
    "separator": "-",
}

_theme_gradient_cache: dict[tuple[str, int, str, int], tuple[TerminalColor, ...]] = {}


def _theme(display, pairs, roles=None, blurb=None, art=None, viz=None, chrome=None):
    spec = {
        "display": display,
        "pairs": pairs,
        "roles": dict(_BASE_THEME_ROLES),
        "blurb": blurb or "",
        "art": dict(_BASE_THEME_ART),
        "viz": dict(_BASE_THEME_VIZ),
        "chrome": {
            **_BASE_THEME_CHROME,
            "box_chars": dict(_BASE_THEME_CHROME["box_chars"]),
        },
    }
    if roles:
        spec["roles"].update(roles)
    if art:
        spec["art"].update(art)
    if viz:
        spec["viz"].update(viz)
    if chrome:
        for key, value in chrome.items():
            if key == "box_chars":
                spec["chrome"]["box_chars"].update(value)
            else:
                spec["chrome"][key] = value
    return spec


_GRAD_SPECTRUM = _make_gradient((53, 155, 255), (255, 118, 160), 101)
_GRAD_PLAYBACK = _make_gradient((64, 214, 180), (166, 255, 198), 101)
_GRAD_VOLUME = _make_gradient((98, 224, 168), (255, 213, 122), 101)
_GRAD_HOT = _make_gradient((255, 110, 76), (255, 233, 120), 101)


_TOD_GRAD_PAIRS = [
    ((34, 52, 104), (119, 92, 175)),
    ((34, 52, 104), (109, 88, 164)),
    ((26, 43, 92), (89, 73, 144)),
    ((26, 43, 92), (79, 66, 133)),
    ((82, 84, 158), (188, 112, 169)),
    ((209, 120, 103), (248, 168, 131)),
    ((255, 170, 102), (255, 216, 109)),
    ((255, 205, 110), (255, 239, 153)),
    ((178, 232, 133), (255, 221, 140)),
    ((96, 225, 168), (190, 247, 139)),
    ((106, 223, 226), (85, 199, 255)),
    ((90, 198, 255), (120, 230, 236)),
    ((79, 175, 255), (116, 233, 255)),
    ((64, 162, 236), (62, 204, 210)),
    ((64, 162, 236), (62, 204, 210)),
    ((84, 149, 255), (169, 121, 214)),
    ((84, 149, 255), (169, 121, 214)),
    ((255, 170, 102), (255, 220, 122)),
    ((255, 116, 112), (255, 171, 98)),
    ((223, 85, 106), (255, 155, 96)),
    ((149, 98, 200), (255, 108, 118)),
    ((168, 103, 214), (224, 108, 163)),
    ((98, 81, 163), (154, 108, 193)),
    ((36, 57, 112), (93, 77, 154)),
]

_THEME_FOREST = [
    ((30, 53, 38), (67, 87, 55)),
    ((30, 53, 38), (67, 87, 55)),
    ((24, 44, 32), (44, 68, 39)),
    ((24, 44, 32), (44, 68, 39)),
    ((65, 89, 48), (122, 100, 86)),
    ((158, 110, 74), (208, 164, 112)),
    ((183, 125, 76), (236, 190, 105)),
    ((206, 168, 92), (173, 226, 121)),
    ((153, 209, 118), (203, 181, 126)),
    ((82, 192, 109), (153, 224, 125)),
    ((52, 150, 92), (83, 210, 110)),
    ((72, 184, 102), (63, 151, 95)),
    ((63, 171, 99), (83, 206, 121)),
    ((46, 118, 73), (60, 150, 93)),
    ((46, 118, 73), (60, 150, 93)),
    ((96, 102, 72), (181, 113, 87)),
    ((157, 108, 80), (198, 128, 91)),
    ((183, 121, 80), (228, 179, 120)),
    ((183, 100, 74), (165, 119, 83)),
    ((126, 83, 62), (95, 71, 58)),
    ((94, 80, 51), (114, 91, 68)),
    ((76, 78, 49), (44, 70, 40)),
    ((40, 58, 38), (66, 88, 48)),
    ((27, 45, 33), (38, 60, 37)),
]

_THEME_NIGHT = [
    ((17, 33, 70), (66, 78, 135)),
    ((17, 33, 70), (66, 78, 135)),
    ((14, 29, 63), (34, 52, 104)),
    ((14, 29, 63), (34, 52, 104)),
    ((18, 40, 78), (66, 78, 135)),
    ((60, 74, 142), (118, 92, 176)),
    ((78, 84, 160), (145, 108, 190)),
    ((83, 102, 181), (104, 170, 223)),
    ((63, 146, 214), (122, 199, 240)),
    ((46, 134, 198), (61, 196, 205)),
    ((53, 152, 214), (61, 196, 205)),
    ((61, 196, 205), (46, 134, 198)),
    ((53, 152, 214), (61, 196, 205)),
    ((47, 109, 184), (79, 88, 164)),
    ((79, 88, 164), (118, 92, 176)),
    ((128, 94, 181), (79, 88, 164)),
    ((79, 88, 164), (47, 109, 184)),
    ((47, 109, 184), (79, 88, 164)),
    ((79, 88, 164), (128, 94, 181)),
    ((128, 94, 181), (186, 106, 192)),
    ((128, 94, 181), (79, 88, 164)),
    ((60, 74, 142), (24, 44, 91)),
    ((17, 33, 70), (66, 78, 135)),
    ((14, 29, 63), (34, 52, 104)),
]

_THEME_WARM = [
    ((89, 35, 47), (138, 53, 78)),
    ((89, 35, 47), (138, 53, 78)),
    ((72, 30, 40), (104, 38, 51)),
    ((72, 30, 40), (104, 38, 51)),
    ((126, 50, 67), (158, 67, 72)),
    ((167, 71, 65), (219, 88, 76)),
    ((234, 99, 70), (255, 163, 84)),
    ((255, 169, 86), (255, 216, 112)),
    ((255, 214, 112), (255, 243, 151)),
    ((255, 198, 103), (255, 208, 117)),
    ((255, 196, 98), (255, 216, 112)),
    ((255, 208, 117), (255, 196, 98)),
    ((255, 196, 98), (255, 216, 112)),
    ((255, 198, 103), (255, 163, 84)),
    ((255, 163, 84), (219, 88, 76)),
    ((219, 88, 76), (206, 72, 76)),
    ((206, 72, 76), (255, 88, 92)),
    ((255, 98, 82), (255, 163, 84)),
    ((255, 163, 84), (224, 95, 73)),
    ((184, 72, 70), (138, 53, 78)),
    ((148, 58, 75), (126, 50, 67)),
    ((126, 50, 67), (89, 35, 47)),
    ((89, 35, 47), (138, 53, 78)),
    ((72, 30, 40), (104, 38, 51)),
]

_THEME_OCEAN = [
    ((13, 33, 64), (24, 74, 105)),
    ((13, 33, 64), (24, 74, 105)),
    ((11, 28, 56), (18, 55, 84)),
    ((11, 28, 56), (18, 55, 84)),
    ((21, 70, 104), (47, 122, 146)),
    ((45, 123, 150), (78, 191, 197)),
    ((65, 171, 196), (120, 227, 219)),
    ((96, 203, 209), (166, 240, 227)),
    ((120, 227, 219), (181, 246, 234)),
    ((70, 199, 196), (136, 236, 216)),
    ((74, 208, 217), (120, 228, 236)),
    ((93, 222, 232), (83, 200, 227)),
    ((83, 200, 227), (96, 222, 232)),
    ((58, 172, 207), (71, 201, 193)),
    ((58, 172, 207), (71, 201, 193)),
    ((44, 141, 196), (120, 186, 220)),
    ((44, 141, 196), (120, 186, 220)),
    ((77, 173, 199), (159, 232, 216)),
    ((87, 162, 185), (110, 205, 183)),
    ((44, 109, 140), (78, 158, 169)),
    ((82, 103, 162), (70, 183, 187)),
    ((69, 86, 150), (56, 122, 163)),
    ((32, 52, 111), (30, 88, 125)),
    ((16, 36, 74), (25, 63, 100)),
]

_THEME_SAKURA = [
    ((77, 76, 114), (190, 140, 187)),
    ((77, 76, 114), (190, 140, 187)),
    ((66, 69, 103), (153, 128, 170)),
    ((66, 69, 103), (153, 128, 170)),
    ((132, 135, 169), (240, 170, 193)),
    ((255, 186, 205), (255, 205, 180)),
    ((255, 196, 207), (255, 221, 184)),
    ((255, 221, 184), (255, 244, 198)),
    ((214, 241, 198), (255, 230, 191)),
    ((175, 235, 196), (235, 248, 197)),
    ((176, 242, 230), (189, 226, 244)),
    ((194, 235, 249), (176, 242, 230)),
    ((194, 235, 249), (176, 242, 230)),
    ((163, 214, 235), (211, 189, 236)),
    ((163, 214, 235), (211, 189, 236)),
    ((196, 164, 223), (251, 190, 212)),
    ((196, 164, 223), (251, 190, 212)),
    ((255, 191, 212), (255, 222, 191)),
    ((255, 173, 189), (255, 207, 173)),
    ((242, 142, 170), (255, 192, 176)),
    ((214, 137, 184), (255, 162, 176)),
    ((182, 129, 190), (230, 157, 204)),
    ((126, 105, 161), (188, 132, 185)),
    ((85, 78, 123), (146, 112, 166)),
]

_THEME_CRAYON = [
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["sky_blue"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["orchid"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["orchid"]),
    (_CRAYOLA["macaroni_and_cheese"], _CRAYOLA["banana_mania"]),
    (_CRAYOLA["banana_mania"], _CRAYOLA["unmellow_yellow"]),
    (_CRAYOLA["banana_mania"], _CRAYOLA["banana_mania"]),
    (_CRAYOLA["banana_mania"], _CRAYOLA["macaroni_and_cheese"]),
    (_CRAYOLA["sea_foam_green"], _CRAYOLA["sky_blue"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["blizzard_blue"]),
    (_CRAYOLA["blizzard_blue"], _CRAYOLA["sky_blue"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["wisteria"]),
    (_CRAYOLA["wisteria"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["orchid"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["peach"]),
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["carnation_pink"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["peach"]),
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["orchid"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["wisteria"]),
]

_THEME_CHALK = [
    (_CRAYOLA["cornflower"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["cornflower"]),
    (_CRAYOLA["cornflower"], _CRAYOLA["blizzard_blue"]),
    (_CRAYOLA["blizzard_blue"], _CRAYOLA["cornflower"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["wisteria"]),
    (_CRAYOLA["wisteria"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["orchid"]),
    (_CRAYOLA["orchid"], _CRAYOLA["sky_blue"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["blizzard_blue"]),
    (_CRAYOLA["blizzard_blue"], _CRAYOLA["sea_foam_green"]),
    (_CRAYOLA["sea_foam_green"], _CRAYOLA["magic_mint"]),
    (_CRAYOLA["magic_mint"], _CRAYOLA["sea_foam_green"]),
    (_CRAYOLA["sea_foam_green"], _CRAYOLA["sky_blue"]),
    (_CRAYOLA["sky_blue"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["wisteria"]),
    (_CRAYOLA["wisteria"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["cornflower"]),
    (_CRAYOLA["cornflower"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["cornflower"]),
]

_THEME_SHERBET = [
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["orchid"]),
    (_CRAYOLA["orchid"], _CRAYOLA["pink_sherbet"]),
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["carnation_pink"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["peach"]),
    (_CRAYOLA["peach"], _CRAYOLA["banana_mania"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["macaroni_and_cheese"]),
    (_CRAYOLA["macaroni_and_cheese"], _CRAYOLA["banana_mania"]),
    (_CRAYOLA["banana_mania"], _CRAYOLA["unmellow_yellow"]),
    (_CRAYOLA["banana_mania"], _CRAYOLA["peach"]),
    (_CRAYOLA["peach"], _CRAYOLA["sea_foam_green"]),
    (_CRAYOLA["sea_foam_green"], _CRAYOLA["aquamarine"]),
    (_CRAYOLA["aquamarine"], _CRAYOLA["blizzard_blue"]),
    (_CRAYOLA["blizzard_blue"], _CRAYOLA["aquamarine"]),
    (_CRAYOLA["aquamarine"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["pink_sherbet"]),
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["carnation_pink"]),
    (_CRAYOLA["carnation_pink"], _CRAYOLA["macaroni_and_cheese"]),
    (_CRAYOLA["macaroni_and_cheese"], _CRAYOLA["peach"]),
    (_CRAYOLA["peach"], _CRAYOLA["pink_sherbet"]),
    (_CRAYOLA["pink_sherbet"], _CRAYOLA["orchid"]),
    (_CRAYOLA["orchid"], _CRAYOLA["lavender"]),
    (_CRAYOLA["lavender"], _CRAYOLA["periwinkle"]),
    (_CRAYOLA["periwinkle"], _CRAYOLA["pink_sherbet"]),
]


THEMES = {
    "default": _theme(
        "Default",
        _TOD_GRAD_PAIRS,
        blurb="Clock Spectrum",
        art={"font": "standard", "mode": "sweep", "palette": ("accent_soft", "accent", "title")},
    ),
    "forest": _theme(
        "Forest",
        _THEME_FOREST,
        roles={
            "accent": (150, 226, 133),
            "pulse": (200, 236, 138),
            "focus_bg": (122, 190, 122),
            "focus_fg": (19, 32, 23),
        },
        blurb="Moss / Acorn",
        art={"font": "standard", "mode": "outline", "palette": ("good", "accent", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "good", "accent", "title"), "rain": ("track_bg", "good", "accent")},
        chrome={"title_left": "╡", "title_right": "╞", "header_left": "╡", "header_right": "╞", "divider": "┄", "separator": "┄"},
    ),
    "night": _theme(
        "Night Drive",
        _THEME_NIGHT,
        roles={
            "accent": (132, 183, 255),
            "pulse": (184, 170, 255),
            "focus_bg": (116, 166, 255),
            "focus_fg": (18, 27, 47),
        },
        blurb="Indigo / Electric Blue",
        art={"font": "slant", "mode": "neon", "palette": ("label", "accent_soft", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "label", "accent", "title"), "rain": ("track_bg", "accent", "title")},
        chrome={
            "box_chars": {"tl": "┏", "tr": "┓", "bl": "┗", "br": "┛", "h": "━", "v": "┃"},
            "title_left": "┫",
            "title_right": "┣",
            "section_left": "┣",
            "section_right": "┫",
            "header_left": "┫",
            "header_right": "┣",
            "divider": "━",
            "separator": "━",
        },
    ),
    "warm": _theme(
        "Warm",
        _THEME_WARM,
        roles={
            "accent": (255, 180, 102),
            "pulse": (255, 121, 102),
            "focus_bg": (255, 180, 102),
            "focus_fg": (58, 31, 28),
        },
        blurb="Coral / Marigold",
        art={"font": "standard", "mode": "ember", "palette": ("accent_soft", "accent", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "accent_soft", "accent", "title"), "rain": ("track_bg", "accent_soft", "title")},
        chrome={
            "box_chars": {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘"},
            "title_left": "╡",
            "title_right": "╞",
            "section_left": "╞",
            "section_right": "╡",
            "header_left": "╡",
            "header_right": "╞",
            "divider": "─",
            "separator": "─",
        },
    ),
    "ocean": _theme(
        "Ocean Glass",
        _THEME_OCEAN,
        roles={
            "title": _CRAYOLA["blizzard_blue"],
            "accent": _CRAYOLA["aquamarine"],
            "accent_soft": _CRAYOLA["sea_foam_green"],
            "value": _CRAYOLA["blizzard_blue"],
            "value_soft": _CRAYOLA["cornflower"],
            "label": _CRAYOLA["sky_blue"],
            "label_dim": _CRAYOLA["periwinkle"],
            "border": _CRAYOLA["cornflower"],
            "border_hi": _CRAYOLA["aquamarine"],
            "pulse": _CRAYOLA["magic_mint"],
            "track_fill": _CRAYOLA["aquamarine"],
            "track_bg": (24, 63, 92),
            "panel_title": _CRAYOLA["blizzard_blue"],
            "panel_subtitle": _CRAYOLA["sea_foam_green"],
            "good": _CRAYOLA["magic_mint"],
            "warning": _CRAYOLA["banana_mania"],
            "danger": _CRAYOLA["pink_sherbet"],
            "focus_bg": _CRAYOLA["aquamarine"],
            "focus_fg": (12, 38, 52),
        },
        blurb="Sea Foam / Blizzard Blue",
        art={"font": "slant", "mode": "tide", "palette": ("label_dim", "accent_soft", "value", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "accent_soft", "value", "title"), "rain": ("track_bg", "accent_soft", "title")},
        chrome={
            "box_chars": {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "╌", "v": "╎"},
            "divider": "┈",
            "separator": "┈",
        },
    ),
    "sakura": _theme(
        "Sakura Bloom",
        _THEME_SAKURA,
        roles={
            "title": _CRAYOLA["pink_sherbet"],
            "accent": _CRAYOLA["carnation_pink"],
            "accent_soft": _CRAYOLA["lavender"],
            "value": _CRAYOLA["peach"],
            "value_soft": _CRAYOLA["banana_mania"],
            "label": _CRAYOLA["periwinkle"],
            "label_dim": _CRAYOLA["wisteria"],
            "border": _CRAYOLA["orchid"],
            "border_hi": _CRAYOLA["pink_sherbet"],
            "pulse": _CRAYOLA["carnation_pink"],
            "track_fill": _CRAYOLA["carnation_pink"],
            "track_bg": (99, 86, 119),
            "panel_title": _CRAYOLA["pink_sherbet"],
            "panel_subtitle": _CRAYOLA["magic_mint"],
            "good": _CRAYOLA["magic_mint"],
            "warning": _CRAYOLA["banana_mania"],
            "danger": _CRAYOLA["pink_sherbet"],
            "focus_bg": _CRAYOLA["carnation_pink"],
            "focus_fg": (72, 53, 84),
        },
        blurb="Pink Sherbet / Magic Mint",
        art={"font": "small", "mode": "bloom", "palette": ("label_dim", "accent_soft", "value", "title"), "outline": "pulse"},
        viz={"spectrum": ("track_bg", "accent_soft", "value", "title"), "rain": ("track_bg", "accent_soft", "title")},
        chrome={"divider": "┈", "separator": "┈", "title_left": "╡", "title_right": "╞", "header_left": "╡", "header_right": "╞"},
    ),
    "crayon": _theme(
        "Crayola Box",
        _THEME_CRAYON,
        roles={
            "title": _CRAYOLA["banana_mania"],
            "accent": _CRAYOLA["carnation_pink"],
            "accent_soft": _CRAYOLA["orchid"],
            "value": _CRAYOLA["banana_mania"],
            "value_soft": _CRAYOLA["macaroni_and_cheese"],
            "label": _CRAYOLA["periwinkle"],
            "label_dim": _CRAYOLA["sky_blue"],
            "border": _CRAYOLA["cornflower"],
            "border_hi": _CRAYOLA["banana_mania"],
            "pulse": _CRAYOLA["pink_sherbet"],
            "track_fill": _CRAYOLA["orchid"],
            "track_bg": _CRAYOLA["periwinkle"],
            "panel_title": _CRAYOLA["banana_mania"],
            "panel_subtitle": _CRAYOLA["macaroni_and_cheese"],
            "good": _CRAYOLA["magic_mint"],
            "warning": _CRAYOLA["banana_mania"],
            "danger": _CRAYOLA["pink_sherbet"],
            "focus_bg": _CRAYOLA["carnation_pink"],
            "focus_fg": (66, 48, 96),
        },
        blurb="Banana Mania / Pink Sherbet",
        art={"font": "big", "mode": "crayon", "palette": ("label", "accent_soft", "value", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "accent_soft", "value", "title"), "rain": ("track_bg", "accent_soft", "title")},
        chrome={
            "box_chars": {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘"},
            "title_left": "╢",
            "title_right": "╟",
            "section_left": "╟",
            "section_right": "╢",
            "header_left": "╢",
            "header_right": "╟",
            "divider": "┄",
            "separator": "┄",
        },
    ),
    "chalk": _theme(
        "Chalk Pastels",
        _THEME_CHALK,
        roles={
            "title": _CRAYOLA["lavender"],
            "accent": _CRAYOLA["magic_mint"],
            "accent_soft": _CRAYOLA["blizzard_blue"],
            "value": _CRAYOLA["lavender"],
            "value_soft": _CRAYOLA["sea_foam_green"],
            "label": _CRAYOLA["cornflower"],
            "label_dim": _CRAYOLA["periwinkle"],
            "border": _CRAYOLA["sky_blue"],
            "border_hi": _CRAYOLA["lavender"],
            "pulse": _CRAYOLA["sea_foam_green"],
            "track_fill": _CRAYOLA["magic_mint"],
            "track_bg": (104, 118, 146),
            "panel_title": _CRAYOLA["lavender"],
            "panel_subtitle": _CRAYOLA["blizzard_blue"],
            "good": _CRAYOLA["magic_mint"],
            "warning": _CRAYOLA["banana_mania"],
            "danger": _CRAYOLA["carnation_pink"],
            "focus_bg": _CRAYOLA["magic_mint"],
            "focus_fg": (46, 63, 88),
        },
        blurb="Blizzard Blue / Magic Mint",
        art={"font": "small", "mode": "chalk", "palette": ("label_dim", "accent_soft", "title"), "outline": "panel_subtitle"},
        viz={"spectrum": ("track_bg", "accent_soft", "title"), "rain": ("track_bg", "accent_soft", "title")},
        chrome={
            "box_chars": {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "╌", "v": "╎"},
            "title_left": "┥",
            "title_right": "┝",
            "section_left": "┝",
            "section_right": "┥",
            "header_left": "┥",
            "header_right": "┝",
            "divider": "╌",
            "separator": "╌",
        },
    ),
    "sherbet": _theme(
        "Sherbet Sunset",
        _THEME_SHERBET,
        roles={
            "title": _CRAYOLA["banana_mania"],
            "accent": _CRAYOLA["macaroni_and_cheese"],
            "accent_soft": _CRAYOLA["peach"],
            "value": _CRAYOLA["pink_sherbet"],
            "value_soft": _CRAYOLA["peach"],
            "label": _CRAYOLA["banana_mania"],
            "label_dim": _CRAYOLA["lavender"],
            "border": _CRAYOLA["orchid"],
            "border_hi": _CRAYOLA["banana_mania"],
            "pulse": _CRAYOLA["carnation_pink"],
            "track_fill": _CRAYOLA["pink_sherbet"],
            "track_bg": (118, 99, 130),
            "panel_title": _CRAYOLA["banana_mania"],
            "panel_subtitle": _CRAYOLA["peach"],
            "good": _CRAYOLA["sea_foam_green"],
            "warning": _CRAYOLA["banana_mania"],
            "danger": _CRAYOLA["pink_sherbet"],
            "focus_bg": _CRAYOLA["peach"],
            "focus_fg": (93, 57, 70),
        },
        blurb="Peach / Pink Sherbet",
        art={"font": "slant", "mode": "ribbon", "palette": ("accent_soft", "value", "accent", "title"), "outline": "border_hi"},
        viz={"spectrum": ("track_bg", "accent_soft", "value", "title"), "rain": ("track_bg", "value", "title")},
        chrome={"divider": "┈", "separator": "┈", "title_left": "╡", "title_right": "╞", "header_left": "╡", "header_right": "╞"},
    ),
}
THEME_NAMES = list(THEMES.keys())
THEME_DISPLAY_NAMES = {name: spec["display"] for name, spec in THEMES.items()}
THEME_BLURBS = {name: spec["blurb"] for name, spec in THEMES.items()}

_active_theme_name = "default"
_active_theme = THEMES[_active_theme_name]
_tod_grad_cache: dict[int, tuple[TerminalColor, ...]] = {}


def set_theme(name: str):
    global _active_theme_name, _active_theme, _tod_grad_cache, _theme_gradient_cache
    name = str(name or "default").strip().lower()
    if name not in THEMES:
        name = "default"
    if name == _active_theme_name:
        return
    _active_theme_name = name
    _active_theme = THEMES[name]
    _tod_grad_cache = {}
    _theme_gradient_cache = {}


def get_theme() -> str:
    return _active_theme_name


def theme_display_name(name: str | None = None) -> str:
    key = str(name or _active_theme_name).strip().lower()
    return THEME_DISPLAY_NAMES.get(key, key.replace("_", " ").title())


def theme_blurb(name: str | None = None) -> str:
    key = str(name or _active_theme_name).strip().lower()
    return THEME_BLURBS.get(key, "")


def theme_art_style(name: str | None = None) -> dict:
    key = str(name or _active_theme_name).strip().lower()
    spec = THEMES.get(key, _active_theme)
    return dict(spec.get("art", _BASE_THEME_ART))


def theme_visualizer_style(name: str | None = None) -> dict:
    key = str(name or _active_theme_name).strip().lower()
    spec = THEMES.get(key, _active_theme)
    return dict(spec.get("viz", _BASE_THEME_VIZ))


def theme_chrome(name: str | None = None) -> dict:
    key = str(name or _active_theme_name).strip().lower()
    spec = THEMES.get(key, _active_theme)
    chrome = spec.get("chrome", _BASE_THEME_CHROME)
    resolved = {
        **chrome,
        "box_chars": dict(chrome.get("box_chars", _BASE_THEME_CHROME["box_chars"])),
    }
    if ASCII_ONLY:
        resolved["box_chars"] = dict(_ASCII_THEME_CHROME["box_chars"])
        for glyph_key in (
            "title_left", "title_right",
            "section_left", "section_right",
            "header_left", "header_right",
            "divider", "separator",
        ):
            resolved[glyph_key] = _ASCII_THEME_CHROME[glyph_key]
    return resolved


def _resolve_theme_color(spec, grad):
    if isinstance(spec, str):
        next_spec = _active_theme["roles"].get(spec, _BASE_THEME_ROLES.get(spec, 60))
        return _resolve_theme_color(next_spec, grad)
    if isinstance(spec, int):
        return gradient_at(grad, spec)
    return _to_terminal_color(spec)


def theme_role(name: str, grad=None):
    if grad is None:
        grad = _active_tod_grad
    spec = _active_theme["roles"].get(name, _BASE_THEME_ROLES.get(name, 60))
    return _resolve_theme_color(spec, grad)


def _theme_gradient(spec_name: str, stops, grad=None, steps=101):
    if grad is None:
        grad = _active_tod_grad
    cache_key = (_active_theme_name, id(grad), spec_name, max(1, int(steps)))
    cached = _theme_gradient_cache.get(cache_key)
    if cached is not None:
        return cached
    resolved = [_resolve_theme_color(stop, grad) for stop in stops]
    gradient = _make_multistop_gradient(resolved, max(1, int(steps)))
    _theme_gradient_cache[cache_key] = gradient
    return gradient


def theme_art_gradient(grad=None, steps=101):
    art = theme_art_style()
    return _theme_gradient("art", art.get("palette", _BASE_THEME_ART["palette"]), grad=grad, steps=steps)


def theme_visualizer_gradient(name="spectrum", grad=None, active=False, steps=101):
    viz = theme_visualizer_style()
    key = f"{name}_active" if active and f"{name}_active" in viz else name
    stops = viz.get(key, _BASE_THEME_VIZ.get(key, _BASE_THEME_VIZ["spectrum"]))
    return _theme_gradient(f"viz:{key}", stops, grad=grad, steps=steps)


def theme_visualizer_color(name, value_0_100, grad=None, active=False):
    return gradient_at(theme_visualizer_gradient(name, grad=grad, active=active), value_0_100)


def theme_gradient_stops(*stops, grad=None, steps=101, cache_name="custom"):
    key = f"{cache_name}:{'|'.join(map(str, stops))}"
    return _theme_gradient(key, stops, grad=grad, steps=steps)


def _grad_for_hour(h: int) -> tuple[TerminalColor, ...]:
    h = int(h) % 24
    if h not in _tod_grad_cache:
        s, e = _active_theme["pairs"][h]
        _tod_grad_cache[h] = _make_gradient(s, e, 101)
    return _tod_grad_cache[h]


_active_tod_grad = _GRAD_SPECTRUM


def gradient_at(grad, value_0_100):
    idx = max(0, min(100, int(value_0_100)))
    return grad[idx]


def gradient_bar(value_pct, width, grad=None, bg_color=235):
    if grad is None:
        grad = _GRAD_PLAYBACK
    filled = max(0, min(width, int(round(value_pct / 100.0 * width))))
    out_parts = []
    for i in range(filled):
        col = gradient_at(grad, round(i / max(1, width - 1) * 100))
        out_parts.append(paint("█", fg=col))
    if filled < width:
        out_parts.append(paint("░" * (width - filled), fg=bg_color))
    return "".join(out_parts)


def solid_bar(value_pct, width, fill_color, track_color=238):
    filled = max(0, min(width, int(round(value_pct / 100.0 * width))))
    parts = []
    if filled > 0:
        parts.append(paint("█" * filled, fg=fill_color))
    if filled < width:
        parts.append(paint("─" * (width - filled), fg=track_color))
    return "".join(parts)


def superscript_num(n):
    return "".join(SUPERSCRIPT[int(d)] for d in str(max(0, n)) if d.isdigit())


def humanize_seconds(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def humanize_bytes(b):
    b = max(0, b)
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KiB"
    if b < 1024 ** 3:
        return f"{b/1024**2:.1f} MiB"
    return f"{b/1024**3:.2f} GiB"


def spectrum_color(i, n, row_norm=None, game_tag=None, energy=None):
    t = (i / max(1, n - 1)) if n > 1 else 1.0
    boost = int((energy or 0.0) * 20)
    active = bool(game_tag and game_tag != "ALL")
    spectrum = theme_visualizer_gradient("spectrum", active=active)
    if row_norm is not None:
        return gradient_at(spectrum, min(100, int(row_norm * 100) + boost))
    return gradient_at(spectrum, min(100, int(t * 100) + boost))

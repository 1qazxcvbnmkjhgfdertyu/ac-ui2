import os, sys, re, math, shutil, json, tempfile

MUSIC_DIR = os.path.expanduser(os.environ.get("AC_UI_MUSIC_DIR", "~/.local/share/ac-terminal-radio/music"))
MPV = (os.environ.get("AC_UI_MPV", "mpv") or "mpv").strip() or "mpv"

# Weighting: piano gets +77% relative weight => 1.77x.
# We'll implement by adding 1 extra "ticket" for piano (simple and close to your earlier request).
PIANO_EXTRA_TICKETS = 1  # each piano track appears twice in the pool
# Spectrum analyzer settings
CAVA_HEIGHT = 8
CAVA_MAX = 1000
CAVA_MIN_BARS = 24
CAVA_MARGIN = 4
RESIZE_DEBOUNCE = 0.25
LOOPBACK_SYNC_INTERVAL = 1.0
HISTORY_MAX = 6
QUEUE_SIZE = 5
UP_NEXT_MAX = 3
AUDIO_WARMUP_GRACE = 1.5

try:
    REFRESH_INTERVAL = float(os.environ.get("AC_UI_REFRESH", "0.033"))
except Exception:
    REFRESH_INTERVAL = 0.033

try:
    IDLE_REFRESH = float(os.environ.get("AC_UI_IDLE_REFRESH", "0.10"))
except Exception:
    IDLE_REFRESH = 0.10

def env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def env_float(name, default, min_value=None, max_value=None):
    try:
        value = float(os.environ.get(name, str(default)))
    except Exception:
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def env_bool01(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return 1 if default else 0
    return 0 if raw.strip().lower() in ("0", "false", "no", "off") else 1

VIS_ATTACK_MS = env_float("AC_UI_VIS_ATTACK_MS", 12.0, 0.0, 1000.0)
VIS_DECAY_MS = env_float("AC_UI_VIS_DECAY_MS", 50.0, 0.0, 2000.0)
VIS_TRAIL_DECAY_MS = env_float("AC_UI_VIS_TRAIL_DECAY_MS", 85.0, 0.0, 2000.0)
VIS_PEAK_DECAY_MS = env_float("AC_UI_VIS_PEAK_DECAY_MS", 120.0, 0.0, 2000.0)
LOOPBACK_LATENCY_MSEC = env_int("AC_UI_LOOPBACK_LATENCY_MSEC", 15, 1, 500)
TRACK_REPEAT_GUARD = env_int("AC_UI_REPEAT_GUARD", 3, 0, 24)

def coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "default"):
            return default
        if text in ("0", "false", "no", "off", "n"):
            return False
        if text in ("1", "true", "yes", "on", "y"):
            return True
    return bool(value)

def _resolve_command_path(command):
    text = os.path.expanduser(str(command or "").strip())
    if not text:
        return ""
    if os.path.isabs(text) or os.sep in text:
        return text if os.path.isfile(text) and os.access(text, os.X_OK) else ""
    return shutil.which(text) or ""

def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

def _atomic_write_text(path, text, encoding="utf-8"):
    _ensure_parent_dir(path)
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".ac-ui-", suffix=".tmp", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise

def _atomic_write_json(path, payload, *, indent=2):
    _atomic_write_text(path, json.dumps(payload, indent=indent) + "\n")

PRIVATE_SINK = os.environ.get("AC_UI_PRIVATE_SINK", "1").lower() in ("1", "true", "yes")
OUTPUT_SINK = os.environ.get("AC_UI_OUTPUT_SINK", "").strip()
if OUTPUT_SINK.lower() in ("default", "@default@", "@default_sink@"):
    OUTPUT_SINK = ""
AUDIO_DEVICE_OVERRIDE = os.environ.get("AC_UI_AUDIO_DEVICE", "").strip()


MUTE_MODE = os.environ.get("AC_UI_MUTE_MODE", "hard").lower()
try:
    SOFT_MUTE_VOL = int(os.environ.get("AC_UI_SOFT_MUTE_VOL", "1"))
except Exception:
    SOFT_MUTE_VOL = 1

# Simple ANSI colors (disable with NO_COLOR env var)
# Accessibility: NO_MOTION=1 disables all animation (pulse dot, gradient anim, border spin, title anim)
NO_MOTION = os.environ.get("NO_MOTION", "0").lower() in ("1", "true", "yes")
SHOW_TITLE_ART = os.environ.get("AC_UI_TITLE_ART", "1").lower() not in ("0", "false", "no")
DEBUG_ART = os.environ.get("AC_UI_DEBUG_ART", "0").lower() in ("1", "true", "yes")
GRADIENT_ANIMATE = (not NO_MOTION) and os.environ.get("AC_UI_GRADIENT_ANIM", "1").lower() not in ("0", "false", "no")
FOCUS_THROTTLE = os.environ.get("AC_UI_FOCUS_THROTTLE", "0").lower() in ("1", "true", "yes")
try:
    GRADIENT_SPEED = float(os.environ.get("AC_UI_GRADIENT_SPEED", "0.02"))
except Exception:
    GRADIENT_SPEED = 0.02
BOX_BORDER_SPIN = (not NO_MOTION) and os.environ.get("AC_UI_BORDER_SPIN", "1").lower() not in ("0", "false", "no")
try:
    BOX_BORDER_SPEED = float(os.environ.get("AC_UI_BORDER_SPEED", "0.5"))
except Exception:
    BOX_BORDER_SPEED = 0.5
try:
    BOX_BORDER_HILITE_LEN = int(os.environ.get("AC_UI_BORDER_HILITE_LEN", "10"))
except Exception:
    BOX_BORDER_HILITE_LEN = 10
TITLE_ANIMATE = (not NO_MOTION) and os.environ.get("AC_UI_TITLE_ANIM", "1").lower() in ("1", "true", "yes")
try:
    TITLE_ANIM_FPS = float(os.environ.get("AC_UI_TITLE_FPS", "1.0"))
except Exception:
    TITLE_ANIM_FPS = 1.0

VIS_MODES = (
    "bars", "peaks", "shades", "outline", "spectrum",
    "flame", "wave", "scope",
    "butterfly", "led_matrix", "matrix_rain", "heartbeat", "braille",
)
VIS_MODE_ALIASES = {
    "classic": "peaks",
    "classic-peak": "peaks",
    "peak": "peaks",
    "ascii": "shades",
    "blocks": "bars",
    "line": "outline",
    "fire": "flame",
    "oscilloscope": "wave",
    "lissajous": "scope",
    "xy": "scope",
    "led": "led_matrix",
    "classic-led": "led_matrix",
    "matrix": "matrix_rain",
    "rain": "matrix_rain",
    "ecg": "heartbeat",
    "pulse": "heartbeat",
    "hires": "braille",
    "2x": "braille",
}

def normalize_vis_mode(value, default="bars"):
    mode = str(value or "").strip().lower()
    mode = VIS_MODE_ALIASES.get(mode, mode)
    return mode if mode in VIS_MODES else default

VIS_MODE = normalize_vis_mode(os.environ.get("AC_UI_VIS", "bars"), default="bars")
VIS_BAR_BLOCKS = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
VIS_SHADE_BLOCKS = (" ", "░", "▒", "▓", "█")
VIS_PEAK_GLYPHS = ("⎺", "⎻", "⎼", "⎽")
MATRIX_RAIN_CHARS = (
    "ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺ"
    "ｻｼｽｾｿﾀﾁﾂﾃﾄ0123456789"
)


def apply_cava_preset():
    """Apply AC_UI_PRESET defaults only for env vars the user did not set."""
    preset = os.environ.get("AC_UI_PRESET", "").strip().lower()
    if not preset:
        return
    profiles = {
        "acoustic": {
            "AC_UI_CAVA_FRAMERATE": "60",
            "AC_UI_CAVA_NOISE_REDUCTION": "0.85",
            "AC_UI_CAVA_SENSITIVITY": "80",
            "AC_UI_CAVA_LOWER_CUTOFF": "80",
            "AC_UI_CAVA_HIGHER_CUTOFF": "12000",
        },
        "bass": {
            "AC_UI_CAVA_FRAMERATE": "60",
            "AC_UI_CAVA_NOISE_REDUCTION": "0.55",
            "AC_UI_CAVA_SENSITIVITY": "140",
            "AC_UI_CAVA_LOWER_CUTOFF": "30",
            "AC_UI_CAVA_HIGHER_CUTOFF": "8000",
        },
        "crisp": {
            "AC_UI_CAVA_FRAMERATE": "90",
            "AC_UI_CAVA_NOISE_REDUCTION": "0.65",
            "AC_UI_CAVA_SENSITIVITY": "110",
            "AC_UI_CAVA_LOWER_CUTOFF": "50",
            "AC_UI_CAVA_HIGHER_CUTOFF": "18000",
        },
    }
    for key, val in profiles.get(preset, {}).items():
        if key not in os.environ:
            os.environ[key] = val


apply_cava_preset()
EQ_ENABLED = env_bool01("AC_UI_EQ", True)
EQ_BAND_COUNT = 10
EQ_BAND_MIN = -12.0
EQ_BAND_MAX = 12.0
EQ_FREQ_LABELS = ("70", "180", "320", "600", "1k", "3k", "6k", "12k", "14k", "16k")
EQ_PRESETS = {
    "flat":     [0.0] * EQ_BAND_COUNT,
    "bass":     [6.0, 5.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "treble":   [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 4.0, 5.0, 6.0],
    "vocal":    [-2.0, -1.0, 0.0, 2.0, 4.0, 3.0, 1.0, 0.0, -1.0, -2.0],
    "piano":    [1.0, 2.0, 1.0, 0.0, -1.0, 0.0, 1.0, 2.0, 1.0, 0.0],
    "warm":     [3.0, 3.0, 2.0, 1.0, 0.0, 0.0, -1.0, -2.0, -2.0, -3.0],
    "acoustic": [4.0, 3.0, 1.0, 0.0, -1.0, 0.0, 1.0, 2.0, 3.0, 2.0],
    "night":    [2.0, 4.0, 4.0, 3.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0],
}
EQ_CONFIG_PATH = os.path.expanduser(
    os.environ.get("AC_UI_EQ_PATH", "~/.config/ac-ui/eq.json")
)
CAVA_FRAMERATE = env_int("AC_UI_CAVA_FRAMERATE", 60, 1, 240)
CAVA_AUTOSENS = env_bool01("AC_UI_CAVA_AUTOSENS", True)
CAVA_SENSITIVITY = env_int("AC_UI_CAVA_SENSITIVITY", 100, 1, 1000)
CAVA_LOWER_CUTOFF = env_int("AC_UI_CAVA_LOWER_CUTOFF", 50, 1, 20000)
CAVA_HIGHER_CUTOFF = env_int("AC_UI_CAVA_HIGHER_CUTOFF", 20000, CAVA_LOWER_CUTOFF + 1, 96000)
CAVA_NOISE_REDUCTION_SET = "AC_UI_CAVA_NOISE_REDUCTION" in os.environ
CAVA_NOISE_REDUCTION = env_float("AC_UI_CAVA_NOISE_REDUCTION", 0.77, 0.0, 1.0)
CAVA_CHANNELS = os.environ.get("AC_UI_CAVA_CHANNELS", "mono").strip().lower()
if CAVA_CHANNELS not in ("mono", "stereo"):
    CAVA_CHANNELS = "mono"
SYM_PLAY     = "▶"
SYM_PAUSE    = "⏸"
SYM_STOP     = "⏹"
SYM_MUTE     = "🔇"
SYM_ARROW_U  = "↑"
SYM_ARROW_D  = "↓"
SYM_ARROW_L  = "←"
SYM_ARROW_R  = "→"
SYM_ENTER    = "↵"
SYM_VOL_UP   = "▲"
SYM_VOL_DN   = "▼"
SYM_NOTE     = "♪"
SYM_ELLIPSIS = "…"
SUPERSCRIPT  = ("⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹")
# Central action registry — single source of truth for keys, footer labels, and help text.
# Columns: (id, keys_tuple, groups_str, label_full, label_compact, help_text)
#   groups_str  : space-separated subset of "full compact core mini"
#   label_full  : displayed in the "full" footer tier
#   label_compact: displayed in compact/core/mini tiers (None = skip that tier)
#   help_text   : shown in the [?] help overlay (None = omit)
ACTIONS = (
    ("next",    ("n",),                "full compact core mini", "[n]ext",           "[n]ext",    "[n]ext track"),
    ("tune",    ("T",),                "full compact core",      "[T]une",           "[T]une",    "[T]own tune editor"),
    ("eq",      ("E",),                "full compact core",      "[E]Q",             "[E]Q",      "[E]Q editor"),
    ("vis",     ("t", "R"),            "full compact",           "[t/R]vis",         "[t/R]vis",  "[t] vis next   [R] random"),
    ("mute",    ("m", " "),            "full compact core mini", "[m/space]mute",    "[m]ute",    "[m]/[space] mute"),
    ("quit",    ("q",),                "full compact core mini", "[q]uit",           "[q]uit",    "[q]uit"),
    ("sink",    ("s",),                "full compact",           "[s]ink",           "[s]ink",    "[s] output sink"),
    ("loop",    ("l",),                "full compact",           "[l]oop",           "[l]oop",    "[l] repeat until hour"),
    ("layout",  ("L",),                "full compact",           "[L]ayout",         "[L]ayout",  "[L] cycle layout"),
    ("help",    ("?",),                "full compact",           "[?]help",          "[?]help",   "[?] toggle help"),
    ("vol",     ("+", "-", "="),       "full compact core mini", "[+/-]vol",         "[+/-]vol",  "[+/-] vol ±5   [PgUp/Dn] vol ±10"),
    ("vol_pg",  ("PAGEUP", "PAGEDOWN"),"full",                   "[PgUp/Dn]vol±10",  None,        None),
    ("game",    ("g",),                "full compact core",      "[g]ame",           "[g]ame",    "[g] cycle game"),
    ("variant", ("v",),                "full compact core",      "[v]ariant",        "[v]ariant", "[v] cycle variant"),
    ("history", ("H",),                "full compact",           "[H]istory",        "[H]istory", "[H] toggle history"),
    ("up_next", ("U",),                "full compact",           "[U]p-next",        "[U]p-next", "[U] toggle up next"),
    ("pin",      ("p",),                "full compact",           "[p]in",            "[p]in",     "[p] pin/unpin current track"),
    ("ban",      ("b",),                "full compact",           "[b]an",            "[b]an",     "[b] ban track + skip"),
    ("theme",    ("C",),                "full compact",           "[C]olor",          "[C]olor",   "[C] cycle color theme"),
    ("hour_sim",  ("h",),               "",                       None,               None,        "[h] simulate hour"),
    ("bg_mode",   ("8",),               "",                       None,               None,        "[8] background mode"),
    ("panel_nav", ("\t",),              "",                       None,               None,        "[tab] focus panel  [↑↓] navigate  [enter] select"),
)

def _action_group(group):
    result = []
    for _id, _keys, groups_str, label_full, label_compact, _help in ACTIONS:
        if group in groups_str.split():
            label = label_full if group == "full" else label_compact
            if label:
                result.append(label)
    return tuple(result)

CONTROL_GROUPS_FULL    = _action_group("full")
CONTROL_GROUPS_COMPACT = _action_group("compact")
CONTROL_GROUPS_CORE    = _action_group("core")
CONTROL_GROUPS_MINI    = _action_group("mini")
DEFAULT_LAYOUT_PRESET = (os.environ.get("AC_UI_LAYOUT_PRESET", "two_rail") or "two_rail").strip().lower()
LAYOUT_GRID_DEFAULT = {"cols": 12, "rows": 12}
LAYOUT_PANEL_NAMES = ("now_playing", "history", "up_next", "stats")
LAYOUT_PANEL_SLOTS = frozenset(("main", "sidebar", "below", "full"))
LAYOUT_PRESETS = {
    "two_rail": {
        "now_playing": {"slot": "main", "x": 0, "y": 0, "w": 8, "h": 6},
        "history": {"slot": "sidebar", "x": 8, "y": 0, "w": 4, "h": 3},
        "up_next": {"slot": "sidebar", "x": 8, "y": 3, "w": 4, "h": 3},
        "stats": {"slot": "full", "x": 0, "y": 6, "w": 12, "h": 4},
    },
    "stacked": {
        "now_playing": {"slot": "main", "x": 0, "y": 0, "w": 12, "h": 6},
        "history": {"slot": "below", "x": 0, "y": 6, "w": 6, "h": 3},
        "up_next": {"slot": "below", "x": 6, "y": 6, "w": 6, "h": 3},
        "stats": {"slot": "full", "x": 0, "y": 9, "w": 12, "h": 4},
    },
}
def _build_help_lines():
    lines = ["Help"]
    parts, cur_len = [], 0
    for _id, _keys, _groups, _lf, _lc, text in ACTIONS:
        if not text:
            continue
        needed = len(text) + (3 if parts else 0)
        if parts and cur_len + needed > 68:
            lines.append("   ".join(parts))
            parts, cur_len = [text], len(text)
        else:
            parts.append(text)
            cur_len += needed
    if parts:
        lines.append("   ".join(parts))
    lines.append(f"[{SYM_ARROW_U}{SYM_ARROW_D}] tune editor nav")
    return lines

HELP_LINES_BASE = _build_help_lines()

CHIME_DIR = os.path.join(MUSIC_DIR, "chimes")
DEFAULT_HOUR_CHIME_NAME = "acgc-town-tune-default.wav"
DEFAULT_HOUR_CHIME = os.path.join(CHIME_DIR, DEFAULT_HOUR_CHIME_NAME)
LEGACY_HOUR_CHIME = os.path.join(CHIME_DIR, "wild-world-town-tune.wav")

# Town tune (16-step) + FluidSynth support.
# Canonical values mirror ACGC:
# m_melody.c packs 16 4-bit values into one u64, and m_mscore_ovl.c maps
# 0..12 to notes, 13 to random, 14 to Z/hold, and 15 to off.
TOWN_TUNE_STEPS = 16
TOWN_TUNE_NOTES = [
    "G3", "A3", "B3", "C4", "D4", "E4", "F4",
    "G4", "A4", "B4", "C5", "D5", "E5",
]
TOWN_TUNE_HOLD = "HOLD"
TOWN_TUNE_OFF = "OFF"
TOWN_TUNE_RANDOM = "RANDOM"
TOWN_TUNE_VALUE_TO_TOKEN = {
    **{i: note for i, note in enumerate(TOWN_TUNE_NOTES)},
    13: TOWN_TUNE_RANDOM,
    14: TOWN_TUNE_HOLD,
    15: TOWN_TUNE_OFF,
}
TOWN_TUNE_TOKEN_TO_VALUE = {token: value for value, token in TOWN_TUNE_VALUE_TO_TOKEN.items()}
DEFAULT_TOWN_TUNE_VALUES = [0x7, 0xC, 0xF, 0x7, 0x6, 0xB, 0xF, 0x9, 0xA, 0xE, 0xD, 0xE, 0x3, 0xF, 0xE, 0xE]
DEFAULT_TOWN_TUNE = [TOWN_TUNE_VALUE_TO_TOKEN[v] for v in DEFAULT_TOWN_TUNE_VALUES]
# Terminal rendering metadata copied from m_mscore_ovl.c note_moji[].
# The source values drive frame type, vertical offset, and frame colors.
ACGC_NOTE_UI = (
    {"label": "G", "frame": "normal", "ofs_y": -29.0, "prim": (0, 10, 0), "env": (70, 155, 255)},
    {"label": "A", "frame": "normal", "ofs_y": -29.0, "prim": (0, 10, 0), "env": (0, 200, 205)},
    {"label": "B", "frame": "normal", "ofs_y": -29.0, "prim": (0, 20, 0), "env": (0, 225, 150)},
    {"label": "C", "frame": "normal", "ofs_y": -23.0, "prim": (0, 40, 0), "env": (20, 235, 0)},
    {"label": "D", "frame": "normal", "ofs_y": -23.0, "prim": (0, 40, 0), "env": (90, 245, 0)},
    {"label": "E", "frame": "normal", "ofs_y": -23.0, "prim": (0, 40, 0), "env": (130, 255, 0)},
    {"label": "F", "frame": "normal", "ofs_y": -23.0, "prim": (0, 50, 0), "env": (155, 255, 0)},
    {"label": "G", "frame": "normal", "ofs_y": -23.0, "prim": (0, 50, 0), "env": (175, 255, 0)},
    {"label": "A", "frame": "normal", "ofs_y": -23.0, "prim": (0, 60, 0), "env": (195, 255, 0)},
    {"label": "B", "frame": "normal", "ofs_y": -23.0, "prim": (0, 60, 0), "env": (225, 255, 0)},
    {"label": "C", "frame": "normal", "ofs_y": -16.0, "prim": (0, 60, 0), "env": (255, 235, 0)},
    {"label": "D", "frame": "normal", "ofs_y": -16.0, "prim": (0, 60, 0), "env": (255, 215, 0)},
    {"label": "E", "frame": "normal", "ofs_y": -16.0, "prim": (0, 70, 0), "env": (255, 175, 0)},
    {"label": "?", "frame": "random", "ofs_y": -20.0, "prim": (70, 60, 30), "env": (255, 110, 110)},
    {"label": "Z", "frame": "rest", "ofs_y": -29.0, "prim": (10, 10, 0), "env": (165, 100, 255)},
    {"label": "-", "frame": "off", "ofs_y": -29.0, "prim": (60, 0, 60), "env": (255, 50, 255)},
)
ACGC_NOTE_FRAME_UI = {
    "normal": {"offset": (0.0, 0.0), "shape": "normal"},
    "rest": {"offset": (-1.0, 20.0), "shape": "rest"},
    "off": {"offset": (1.0, 1.0), "shape": "off"},
    "random": {"offset": (-1.0, 5.0), "shape": "random"},
}
ACGC_MSCORE_CURSOR_OK = 16
ACGC_MSCORE_SLOT_STEP = 21.0
ACGC_MSCORE_FIRST_ROW_X = -91.0
ACGC_MSCORE_SECOND_ROW_X = -71.0
ACGC_MSCORE_ROW_Y = (20.0, -30.0)
ACGC_MSCORE_TERMINAL_STEP = 7
ACGC_MSCORE_TERMINAL_FIRST_INDENT = 7
ACGC_MSCORE_TERMINAL_SECOND_INDENT = ACGC_MSCORE_TERMINAL_FIRST_INDENT + round(
    ((ACGC_MSCORE_SECOND_ROW_X - ACGC_MSCORE_FIRST_ROW_X) / ACGC_MSCORE_SLOT_STEP) * ACGC_MSCORE_TERMINAL_STEP
)
ACGC_MSCORE_TERMINAL_SLOT_POS = tuple(i * ACGC_MSCORE_TERMINAL_STEP for i in range(8))
ACGC_MSCORE_OPEN_AUTOPLAY_DELAY = 10.0 / 60.0
ACGC_MSCORE_MODAL_ERASE = "erase"
ACGC_MSCORE_MODAL_END = "end"
ACGC_MSCORE_END_OPTIONS = ("Yes", "Rewrite", "Throw it out")
ACGC_MSCORE_GLYPH_SELECTED = (255, 0, 0)
ACGC_MSCORE_GLYPH_IDLE = (0, 0, 255)
ACGC_MSCORE_ERASE_CHOICE_ACTIVE = (70, 70, 225)
ACGC_MSCORE_ERASE_CHOICE_IDLE = (140, 160, 205)
LEGACY_TOWN_TUNE_NOTES = (
    "C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5",
    "D5", "E5", "F5", "G5", "A5", "B5", "C6", "D6",
)
TOWN_TUNE_PATH = os.path.expanduser(
    os.environ.get("AC_UI_TOWN_TUNE_PATH", "~/.local/share/ac-terminal-radio/town_tune.json")
)
TOWN_TUNE_ENABLED = os.environ.get("AC_UI_TOWN_TUNE", "1").lower() in ("1", "true", "yes")
TOWN_TUNE_CHIME_ENABLED = os.environ.get("AC_UI_TOWN_TUNE_CHIME", "0").lower() in ("1", "true", "yes")
TOWN_TUNE_SAMPLE_DIR = os.path.expanduser(
    os.environ.get("AC_UI_TOWN_TUNE_SAMPLE_DIR", "~/.local/share/ac-terminal-radio/town_tune_samples")
)
ACGC_TOWN_TUNE_RENDER = os.environ.get("AC_UI_ACGC_TOWN_TUNE_RENDER", "1").lower() in ("1", "true", "yes")
ACGC_TOWN_TUNE_ASSET_ROOT = os.path.expanduser(
    os.environ.get("AC_UI_ACGC_TOWN_TUNE_ASSET_ROOT", "~/.local/share/ac-terminal-radio/acgc_engine")
)
ACGC_TOWN_TUNE_BUNDLED_DUMPER = os.path.join(ACGC_TOWN_TUNE_ASSET_ROOT, "AnimalCrossing-renderer")
ACGC_TOWN_TUNE_PATH_DUMPER = shutil.which("AnimalCrossing") or ""
ACGC_TOWN_TUNE_DUMPER = os.path.expanduser(
    os.environ.get(
        "AC_UI_ACGC_TOWN_TUNE_DUMPER",
        ACGC_TOWN_TUNE_BUNDLED_DUMPER
        if os.path.exists(ACGC_TOWN_TUNE_BUNDLED_DUMPER)
        else ACGC_TOWN_TUNE_PATH_DUMPER,
    )
)
ACGC_TOWN_TUNE_DISC = os.path.expanduser(
    os.environ.get(
        "AC_UI_ACGC_DISC_PATH",
        os.environ.get("ACGC_DISC_PATH", ""),
    )
)
try:
    TOWN_TUNE_STEP_SECONDS = float(os.environ.get("AC_UI_TOWN_TUNE_STEP_SECONDS", "0.228125"))
except Exception:
    TOWN_TUNE_STEP_SECONDS = 0.228125
try:
    ACGC_TOWN_TUNE_DUMP_SECONDS = max(1, int(os.environ.get("AC_UI_ACGC_TOWN_TUNE_DUMP_SECONDS", "5")))
except Exception:
    ACGC_TOWN_TUNE_DUMP_SECONDS = 5
try:
    ACGC_TOWN_TUNE_DUMP_TIMEOUT = max(2.0, float(os.environ.get("AC_UI_ACGC_TOWN_TUNE_DUMP_TIMEOUT", "12")))
except Exception:
    ACGC_TOWN_TUNE_DUMP_TIMEOUT = 12.0
TOWN_TUNE_TEMPO = int(os.environ.get("AC_UI_TOWN_TUNE_TEMPO", "50"))
TOWN_TUNE_STEP_FRACTION = float(os.environ.get("AC_UI_TOWN_TUNE_STEP", "1.0"))
TOWN_TUNE_GAIN = float(os.environ.get("AC_UI_TOWN_TUNE_GAIN", "0.6"))
TOWN_TUNE_PROGRAM = int(os.environ.get("AC_UI_TOWN_TUNE_PROGRAM", "12"))
FLUIDSYNTH_OPTS = os.environ.get(
    "AC_UI_FLUIDSYNTH_OPTS",
    "-o synth.reverb.active=1 -o synth.reverb.room-size=0.75 -o synth.reverb.damp=0.4 "
    "-o synth.reverb.width=0.9 -o synth.reverb.level=0.3",
).strip()
FLUIDSYNTH = os.environ.get("AC_UI_FLUIDSYNTH", "fluidsynth")
FLUIDSYNTH_AUDIO = os.environ.get("AC_UI_FLUIDSYNTH_AUDIO", "").strip()
FLUIDSYNTH_DEFAULT_AUDIO = os.environ.get("AC_UI_FLUIDSYNTH_DEFAULT_AUDIO", "pulseaudio").strip()
SOUNDFONT_CANDIDATES = [
    "~/.local/share/ac-terminal-radio/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/default.sf2",
]
if os.environ.get("AC_UI_SOUNDFONT"):
    SOUNDFONT_PATH = os.path.expanduser(os.environ["AC_UI_SOUNDFONT"])
else:
    SOUNDFONT_PATH = next(
        (os.path.expanduser(path) for path in SOUNDFONT_CANDIDATES if os.path.exists(os.path.expanduser(path))),
        os.path.expanduser(SOUNDFONT_CANDIDATES[0]),
    )

# Local stats (on by default)
STATS_ENABLED = os.environ.get("AC_UI_STATS", "1").lower() in ("1", "true", "yes")
STATS_DIR = os.path.expanduser(os.environ.get("AC_UI_STATS_DIR", "~/.local/share/ac-terminal-radio"))
STATS_JSON = os.path.join(STATS_DIR, "stats.json")
STATS_CSV = os.path.join(STATS_DIR, "stats.csv")
UI_STATE_PATH = os.path.expanduser(
    os.environ.get("AC_UI_STATE_PATH", os.path.join(STATS_DIR, "state.json"))
)

HOUR_CHIME_PATH = os.path.expanduser(os.environ.get("AC_UI_HOUR_CHIME", DEFAULT_HOUR_CHIME))
if os.environ.get("AC_UI_HOUR_CHIME") is None:
    HOUR_CHIME_PATH = next(
        (path for path in (DEFAULT_HOUR_CHIME, LEGACY_HOUR_CHIME) if os.path.exists(path)),
        DEFAULT_HOUR_CHIME,
    )
if not os.path.exists(HOUR_CHIME_PATH):
    HOUR_CHIME_PATH = None

try:
    CROSSFADE_SECONDS = float(os.environ.get("AC_UI_CROSSFADE", "3.5"))
except Exception:
    CROSSFADE_SECONDS = 3.5

FILENAME_RE = re.compile(r"^(?P<hour>[01]\d|2[0-3])-(?P<game>[A-Z0-9]+)-(?P<variant>[a-z0-9_-]+)\.(?P<ext>mp3|flac)$")
TRACK_LIST_CACHE = {}

# ── btop-style Unicode box-drawing characters ─────────────────────────────────
BOX_CHARS = {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h":  "─", "v":  "│",
    "htl": "┌", "htr": "┐", "hbl": "└", "hbr": "┘",  # hard-corner fallback
}
BOX_TITLE_L  = "┤"   # left  title bracket  ─┤ Title ├─
BOX_TITLE_R  = "├"   # right title bracket

"""Audio, visualizer, and accessibility configuration.

Self-contained: no imports from other ac_ui modules.
`apply_cava_preset()` is called at import time so CAVA_* constants
pick up preset env-var overrides correctly.
"""
import os

# ── env helpers (local copies — avoid circular dep on constants) ──────────────

def _env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_float(name, default, min_value=None, max_value=None):
    try:
        value = float(os.environ.get(name, str(default)))
    except Exception:
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_bool01(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return 1 if default else 0
    return 0 if raw.strip().lower() in ("0", "false", "no", "off") else 1


# ── Visualizer smoothing ──────────────────────────────────────────────────────

VIS_ATTACK_MS    = _env_float("AC_UI_VIS_ATTACK_MS",  12.0,  0.0, 1000.0)
VIS_DECAY_MS     = _env_float("AC_UI_VIS_DECAY_MS",   50.0,  0.0, 2000.0)
VIS_TRAIL_DECAY_MS = _env_float("AC_UI_VIS_TRAIL_DECAY_MS", 85.0, 0.0, 2000.0)
VIS_PEAK_DECAY_MS  = _env_float("AC_UI_VIS_PEAK_DECAY_MS", 120.0, 0.0, 2000.0)
LOOPBACK_LATENCY_MSEC = _env_int("AC_UI_LOOPBACK_LATENCY_MSEC", 15, 1, 500)

# ── Audio sink / output ───────────────────────────────────────────────────────

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

# ── Accessibility / animation flags ──────────────────────────────────────────

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

# ── Visualizer modes ──────────────────────────────────────────────────────────

VIS_MODES = (
    "bars", "peaks", "shades", "outline", "spectrum",
    "flame", "wave", "scope",
    "butterfly", "led_matrix", "matrix_rain", "heartbeat", "braille",
    "ascii",
)
VIS_MODE_ALIASES = {
    "classic": "peaks",
    "classic-peak": "peaks",
    "peak": "peaks",
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

# ── CAVA preset (must run before CAVA_* constants are evaluated) ──────────────


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

# ── EQ ────────────────────────────────────────────────────────────────────────

EQ_ENABLED = _env_bool01("AC_UI_EQ", True)
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

# ── CAVA ──────────────────────────────────────────────────────────────────────

CAVA_FRAMERATE = _env_int("AC_UI_CAVA_FRAMERATE", 60, 1, 240)
CAVA_AUTOSENS = _env_bool01("AC_UI_CAVA_AUTOSENS", True)
CAVA_SENSITIVITY = _env_int("AC_UI_CAVA_SENSITIVITY", 100, 1, 1000)
CAVA_LOWER_CUTOFF = _env_int("AC_UI_CAVA_LOWER_CUTOFF", 50, 1, 20000)
CAVA_HIGHER_CUTOFF = _env_int("AC_UI_CAVA_HIGHER_CUTOFF", 20000, CAVA_LOWER_CUTOFF + 1, 96000)
CAVA_NOISE_REDUCTION_SET = "AC_UI_CAVA_NOISE_REDUCTION" in os.environ
CAVA_NOISE_REDUCTION = _env_float("AC_UI_CAVA_NOISE_REDUCTION", 0.77, 0.0, 1.0)
CAVA_CHANNELS = os.environ.get("AC_UI_CAVA_CHANNELS", "mono").strip().lower()
if CAVA_CHANNELS not in ("mono", "stereo"):
    CAVA_CHANNELS = "mono"

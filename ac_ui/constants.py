import os, sys, re, math, shutil, json, tempfile

MUSIC_DIR = os.path.expanduser(os.environ.get("AC_UI_MUSIC_DIR", "~/.local/share/ac-terminal-radio/music"))
MPV = (os.environ.get("AC_UI_MPV", "mpv") or "mpv").strip() or "mpv"

PIANO_EXTRA_TICKETS = 1  # each piano track appears twice in the pool
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

# True when the user pinned a fixed frame rate via AC_UI_REFRESH — that disables
# the per-mode adaptive frame rate and uses REFRESH_INTERVAL everywhere.
REFRESH_OVERRIDE_SET = "AC_UI_REFRESH" in os.environ

try:
    IDLE_REFRESH = float(os.environ.get("AC_UI_IDLE_REFRESH", "0.10"))
except Exception:
    IDLE_REFRESH = 0.10

# ── env helpers (public API — kept here so callers can import from constants) ──

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


_STDOUT_ENCODING = (
    (os.environ.get("PYTHONIOENCODING", "").split(":", 1)[0])
    or getattr(sys.stdout, "encoding", "")
    or ""
)
ASCII_ONLY = bool(env_bool01("AC_UI_ASCII_ONLY", False) or ("utf" not in _STDOUT_ENCODING.lower()))


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


# ── Audio, visualizer, and accessibility settings (see ac_ui/audio_config.py) ─

from ac_ui.audio_config import (  # noqa: E402
    VIS_ATTACK_MS, VIS_DECAY_MS, VIS_TRAIL_DECAY_MS, VIS_PEAK_DECAY_MS,
    VIS_SCALE, VIS_GAMMA,
    LOOPBACK_LATENCY_MSEC,
    PCM_MODE, PRIVATE_SINK, OUTPUT_SINK, AUDIO_DEVICE_OVERRIDE, MUTE_MODE, SOFT_MUTE_VOL,
    NO_MOTION, SHOW_TITLE_ART, DEBUG_ART, GRADIENT_ANIMATE, FOCUS_THROTTLE,
    GRADIENT_SPEED, BOX_BORDER_SPIN, BOX_BORDER_SPEED, BOX_BORDER_HILITE_LEN,
    TITLE_ANIMATE, TITLE_ANIM_FPS,
    VIS_MODES, VIS_MODE_ALIASES, normalize_vis_mode, VIS_MODE,
    VIS_FPS_FAST, VIS_FPS_NORMAL, VIS_FPS_HEAVY, VIS_FPS_CHOICES, VIS_TIER_LABELS,
    FAST_VIS_MODES, HEAVY_VIS_MODES, vis_tier, vis_target_fps, vis_frame_interval,
    default_vis_fps_map,
    VIS_BAR_BLOCKS, VIS_SHADE_BLOCKS, VIS_PEAK_GLYPHS, MATRIX_RAIN_CHARS,
    apply_cava_preset,
    EQ_ENABLED, EQ_BAND_COUNT, EQ_BAND_MIN, EQ_BAND_MAX, EQ_FREQ_LABELS,
    EQ_PRESETS, EQ_CONFIG_PATH,
    CAVA_FRAMERATE, CAVA_AUTOSENS, CAVA_SENSITIVITY, CAVA_BARS, CAVA_LOWER_CUTOFF,
    CAVA_HIGHER_CUTOFF, CAVA_NOISE_REDUCTION_SET, CAVA_NOISE_REDUCTION,
    CAVA_CHANNELS,
)

# ── UI symbols ────────────────────────────────────────────────────────────────

SYM_PLAY     = ">" if ASCII_ONLY else "▶"
SYM_PAUSE    = "||" if ASCII_ONLY else "⏸"
SYM_STOP     = "[]" if ASCII_ONLY else "⏹"
SYM_SELECT   = ">" if ASCII_ONLY else "▶"
SYM_QUEUE_NEXT = ">" if ASCII_ONLY else "»"
SYM_MUTE     = "MUTE" if ASCII_ONLY else "🔇"
SYM_ARROW_U  = "^" if ASCII_ONLY else "↑"
SYM_ARROW_D  = "v" if ASCII_ONLY else "↓"
SYM_ARROW_L  = "<" if ASCII_ONLY else "←"
SYM_ARROW_R  = ">" if ASCII_ONLY else "→"
SYM_ROUTE    = "->" if ASCII_ONLY else "→"
SYM_ENTER    = "RET" if ASCII_ONLY else "↵"
SYM_VOL_UP   = "+" if ASCII_ONLY else "▲"
SYM_VOL_DN   = "-" if ASCII_ONLY else "▼"
SYM_NOTE     = "*" if ASCII_ONLY else "♪"
SYM_ELLIPSIS = "..." if ASCII_ONLY else "…"
SYM_PULSE_ON = "o" if ASCII_ONLY else "●"
SYM_PULSE_OFF = "." if ASCII_ONLY else "·"
SYM_DOT_FILLED = "*" if ASCII_ONLY else "●"
SYM_DOT_EMPTY = "o" if ASCII_ONLY else "○"
SYM_MUTED_MARK = "!" if ASCII_ONLY else "◆"
SYM_HIST_MARKER = "^" if ASCII_ONLY else "▴"
SYM_SHUFFLE = "~" if ASCII_ONLY else "⟳"
SYM_PIN = "[PIN]" if ASCII_ONLY else "📌"
SYM_REMOVE = "x" if ASCII_ONLY else "✗"
SYM_BG_ON = "[BG]" if ASCII_ONLY else "⬛"
SYM_BG_OFF = "[bg]" if ASCII_ONLY else "▣"
SUPERSCRIPT  = tuple("0123456789") if ASCII_ONLY else ("⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹")

# Central action registry — single source of truth for keys, footer labels, and help text.
# Columns: (id, keys_tuple, groups_str, label_full, label_compact, help_text)
ACTIONS = (
    ("next",    ("n",),                "full compact core mini", "[n]ext",           "[n]ext",    "[n]ext track"),
    ("tune",    ("T",),                "full compact core",      "[T]une",           "[T]une",    "[T]own tune editor"),
    ("eq",      ("E",),                "full compact core",      "[E]Q",             "[E]Q",      "[E]Q editor"),
    ("vis",     ("t", "R"),            "full compact",           "[t/R]vis",         "[t/R]vis",  "[t] vis next   [R] random"),
    ("vis_fps", ("r",),                "full compact",           "[r]fps",           "[r]fps",    "[r] visualizer frame-rate menu"),
    ("vis_shuffle", ("y",),            "",                       None,               None,        "[y] visualizer shuffle"),
    ("mute",    ("m", " "),            "full compact core mini", "[m/space]mute",    "[m]ute",    "[m]/[space] mute"),
    ("quit",    ("q",),                "full compact core mini", "[q]uit",           "[q]uit",    "[q]uit"),
    ("sink",    ("s",),                "full compact",           "[s]ink",           "[s]ink",    "[s] output sink"),
    ("loop",    ("l",),                "full compact",           "[l]oop",           "[l]oop",    "[l] repeat until hour"),
    ("layout",  ("L",),                "full compact",           "[L]ayout",         "[L]ayout",  "[L] cycle layout"),
    ("help",    ("?",),                "full compact",           "[?]help",          "[?]help",   "[?] toggle help"),
    ("palette", (":",),                "full compact",           "[:]palette",       "[:]cmds",   "[:] or [^P] command palette"),
    ("find",    ("/",),                "full compact",           "[/]find",          "[/]find",   "[/] find & play any track"),
    ("vol",     ("+", "-", "="),       "full compact core mini", "[+/-]vol",         "[+/-]vol",  "[+/-] vol +/-5   [PgUp/Dn] vol +/-10"),
    ("vol_pg",  ("PAGEUP", "PAGEDOWN"),"full",                   "[PgUp/Dn]vol+/-10",None,        None),
    ("game",    ("g",),                "full compact core",      "[g]ame",           "[g]ame",    "[g] cycle game"),
    ("variant", ("v",),                "full compact core",      "[v]ariant",        "[v]ariant", "[v] cycle variant"),
    ("history", ("H",),                "full compact",           "[H]istory",        "[H]istory", "[H] toggle history"),
    ("up_next", ("U",),                "full compact",           "[U]p-next",        "[U]p-next", "[U] toggle up next"),
    ("pin",      ("p",),               "full compact",           "[p]in",            "[p]in",     "[p] pin/unpin current track"),
    ("ban",      ("b",),               "full compact",           "[b]an",            "[b]an",     "[b] ban track + skip"),
    ("theme",    ("C",),               "full compact",           "[C]olor",          "[C]olor",   "[C] cycle color theme"),
    ("hour_sim",  ("h",),              "",                       None,               None,        "[h] simulate hour"),
    ("bg_mode",   ("8",),              "",                       None,               None,        "[8] background mode"),
    ("panel_nav", ("\t",),             "",                       None,               None,        f"[tab] focus panel  [{SYM_ARROW_U}{SYM_ARROW_D}] navigate  [enter] select  [x] actions  [z] zoom"),
    ("panel_focus_num", ("1", "2", "0"), "",                     None,               None,        "[1] focus history  [2] focus up-next  [0] unfocus"),
    ("free_play",    ("f",),  "full compact", "[f]ree play",      "[f]ree",    "[f] toggle free play mode"),
    ("add_track",    ("a",),  "full compact", "[a]dd to list",    "[a]dd",     "[a] add current track to a playlist"),
    ("playlist_mgr", ("F",),  "full compact", "[F]playlists",     "[F]lists",  "[F] playlist manager (create/edit/delete)"),
    ("queue_mgr",    ("Q",),  "full compact", "[Q]ueue",          "[Q]ueue",   "[Q] manage free-play queue"),
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

NOW_PLAYING_TITLE_HINTS = ("[?]help", "[n]ext", "[m]ute", "[+/-]vol")
VISUALIZER_TITLE_HINTS = ("[y]shuffle", "[r]fps", "[t/R]vis")

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
    # "wide-graph" (plan §2): every side panel rides the right rail so the
    # now-playing/visualizer area stays full-height and dominant — best on wide
    # terminals where the graph deserves the room.
    "wide_graph": {
        "now_playing": {"slot": "main", "x": 0, "y": 0, "w": 8, "h": 9},
        "history": {"slot": "sidebar", "x": 8, "y": 0, "w": 4, "h": 3},
        "up_next": {"slot": "sidebar", "x": 8, "y": 3, "w": 4, "h": 3},
        "stats": {"slot": "sidebar", "x": 8, "y": 6, "w": 4, "h": 3},
    },
    # "fullscreen": now-playing + visualizer take the whole screen — every side
    # panel and the stats bar are suppressed by the compositor so nothing steals
    # width or height from the graph.
    "fullscreen": {
        "now_playing": {"slot": "main", "x": 0, "y": 0, "w": 12, "h": 12},
        "history": {"slot": "main", "x": 0, "y": 0, "w": 12, "h": 0},
        "up_next": {"slot": "main", "x": 0, "y": 0, "w": 12, "h": 0},
        "stats": {"slot": "main", "x": 0, "y": 0, "w": 12, "h": 0},
    },
}

# Presets whose compositor hides every panel except now-playing/visualizer.
FULLSCREEN_LAYOUT_PRESETS = frozenset({"fullscreen"})


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

# ── Town tune, ACGC renderer, and FluidSynth config (see ac_ui/town_tune_config.py) ──

from ac_ui.town_tune_config import (  # noqa: E402
    TOWN_TUNE_STEPS, TOWN_TUNE_NOTES, TOWN_TUNE_HOLD, TOWN_TUNE_OFF, TOWN_TUNE_RANDOM,
    TOWN_TUNE_VALUE_TO_TOKEN, TOWN_TUNE_TOKEN_TO_VALUE,
    DEFAULT_TOWN_TUNE_VALUES, DEFAULT_TOWN_TUNE,
    ACGC_NOTE_UI, ACGC_NOTE_FRAME_UI,
    ACGC_MSCORE_CURSOR_OK, ACGC_MSCORE_SLOT_STEP,
    ACGC_MSCORE_FIRST_ROW_X, ACGC_MSCORE_SECOND_ROW_X, ACGC_MSCORE_ROW_Y,
    ACGC_MSCORE_TERMINAL_STEP, ACGC_MSCORE_TERMINAL_FIRST_INDENT,
    ACGC_MSCORE_TERMINAL_SECOND_INDENT, ACGC_MSCORE_TERMINAL_SLOT_POS,
    ACGC_MSCORE_OPEN_AUTOPLAY_DELAY,
    ACGC_MSCORE_MODAL_ERASE, ACGC_MSCORE_MODAL_END, ACGC_MSCORE_END_OPTIONS,
    ACGC_MSCORE_GLYPH_SELECTED, ACGC_MSCORE_GLYPH_IDLE,
    ACGC_MSCORE_ERASE_CHOICE_ACTIVE, ACGC_MSCORE_ERASE_CHOICE_IDLE,
    LEGACY_TOWN_TUNE_NOTES,
    TOWN_TUNE_PATH, TOWN_TUNE_ENABLED, TOWN_TUNE_CHIME_ENABLED, TOWN_TUNE_SAMPLE_DIR,
    ACGC_TOWN_TUNE_RENDER, ACGC_TOWN_TUNE_ASSET_ROOT, ACGC_TOWN_TUNE_BUNDLED_DUMPER,
    ACGC_TOWN_TUNE_DUMPER, ACGC_TOWN_TUNE_DISC,
    TOWN_TUNE_STEP_SECONDS, ACGC_TOWN_TUNE_DUMP_SECONDS, ACGC_TOWN_TUNE_DUMP_TIMEOUT,
    TOWN_TUNE_TEMPO, TOWN_TUNE_STEP_FRACTION, TOWN_TUNE_GAIN, TOWN_TUNE_PROGRAM,
    FLUIDSYNTH_OPTS, FLUIDSYNTH, FLUIDSYNTH_AUDIO, FLUIDSYNTH_DEFAULT_AUDIO,
    SOUNDFONT_CANDIDATES, SOUNDFONT_PATH,
)

# ── Stats and persistence paths ───────────────────────────────────────────────

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
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "h":  "-", "v":  "|",
    "htl": "+", "htr": "+", "hbl": "+", "hbr": "+",
} if ASCII_ONLY else {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h":  "─", "v":  "│",
    "htl": "┌", "htr": "┐", "hbl": "└", "hbr": "┘",
}
BOX_TITLE_L  = "+" if ASCII_ONLY else "┤"
BOX_TITLE_R  = "+" if ASCII_ONLY else "├"

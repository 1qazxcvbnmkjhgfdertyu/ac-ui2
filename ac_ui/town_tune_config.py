"""Town tune, ACGC renderer, and FluidSynth configuration.

Self-contained: no imports from other ac_ui modules.
"""
import os
import shutil

# ── Town tune note table ──────────────────────────────────────────────────────

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
    "rest":   {"offset": (-1.0, 20.0), "shape": "rest"},
    "off":    {"offset": (1.0, 1.0), "shape": "off"},
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

# ── Town tune paths and flags ─────────────────────────────────────────────────

TOWN_TUNE_PATH = os.path.expanduser(
    os.environ.get("AC_UI_TOWN_TUNE_PATH", "~/.local/share/ac-terminal-radio/town_tune.json")
)
TOWN_TUNE_ENABLED = os.environ.get("AC_UI_TOWN_TUNE", "1").lower() in ("1", "true", "yes")
TOWN_TUNE_CHIME_ENABLED = os.environ.get("AC_UI_TOWN_TUNE_CHIME", "0").lower() in ("1", "true", "yes")
TOWN_TUNE_SAMPLE_DIR = os.path.expanduser(
    os.environ.get("AC_UI_TOWN_TUNE_SAMPLE_DIR", "~/.local/share/ac-terminal-radio/town_tune_samples")
)

# ── ACGC renderer paths ───────────────────────────────────────────────────────

ACGC_TOWN_TUNE_RENDER = os.environ.get("AC_UI_ACGC_TOWN_TUNE_RENDER", "1").lower() in ("1", "true", "yes")
ACGC_TOWN_TUNE_ASSET_ROOT = os.path.expanduser(
    os.environ.get("AC_UI_ACGC_TOWN_TUNE_ASSET_ROOT", "~/.local/share/ac-terminal-radio/acgc_engine")
)
ACGC_TOWN_TUNE_BUNDLED_DUMPER = os.path.join(ACGC_TOWN_TUNE_ASSET_ROOT, "AnimalCrossing-renderer")

# Lazy PATH lookup — only runs if the bundled renderer is absent and no explicit override.
def _find_acgc_path_dumper():
    return shutil.which("AnimalCrossing") or ""


_explicit_dumper = os.environ.get("AC_UI_ACGC_TOWN_TUNE_DUMPER")
if _explicit_dumper is not None:
    # Explicit override (including empty string to disable the renderer)
    ACGC_TOWN_TUNE_DUMPER = os.path.expanduser(_explicit_dumper) if _explicit_dumper else ""
elif os.path.exists(ACGC_TOWN_TUNE_BUNDLED_DUMPER):
    ACGC_TOWN_TUNE_DUMPER = ACGC_TOWN_TUNE_BUNDLED_DUMPER
else:
    ACGC_TOWN_TUNE_DUMPER = _find_acgc_path_dumper()

ACGC_TOWN_TUNE_DISC = os.path.expanduser(
    os.environ.get("AC_UI_ACGC_DISC_PATH", os.environ.get("ACGC_DISC_PATH", ""))
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

# ── FluidSynth ────────────────────────────────────────────────────────────────

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
        (os.path.expanduser(p) for p in SOUNDFONT_CANDIDATES if os.path.exists(os.path.expanduser(p))),
        os.path.expanduser(SOUNDFONT_CANDIDATES[0]),
    )

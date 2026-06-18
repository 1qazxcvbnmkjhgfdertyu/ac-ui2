import os, json

from ac_ui.constants import (
    UI_STATE_PATH, VIS_MODE, VIS_MODES,
    coerce_bool, normalize_vis_mode, _atomic_write_json, DEFAULT_LAYOUT_PRESET,
    default_vis_fps_map, VIS_FPS_CHOICES,
)
from ac_ui.layout_config import normalize_layout_config

UI_STATE_VERSION = 3


def _migrate_ui_state(src: dict) -> dict:
    """Migrate older ui_state dicts to current version."""
    try:
        v = int(src.get("_version", 1))
    except (TypeError, ValueError):
        v = 1
    if v < 2:
        # v1 → v2: layout_preset moved into nested layout dict
        if "layout_preset" in src and "layout" not in src:
            src["layout"] = {"preset": src.pop("layout_preset")}
    if v < 3:
        # v2 → v3: free-play runtime queue now persisted; older files simply
        # have no saved queue, so a fresh shuffle is built on next launch.
        src.setdefault("free_play_queue", [])
        src.setdefault("free_play_idx", 0)
    return src


def load_ui_state():
    data = {
        "output_vol": 75,
        "muted": False,
        "mute_prev_vol": 50,
        "vis_mode": VIS_MODE,
        "vis_shuffle": False,
        "repeat_current": False,
        "game": "ALL",
        "variant": "ALL",
        "layout": None,
        "theme": "default",
        "free_play_mode": False,
        "free_play_dir": "~/.local/share/ac-terminal-radio/playlists/f2p_nostalgia/f2p_nostalgia.acpl",
        "free_play_queue": [],
        "free_play_idx": 0,
        "vis_fps": default_vis_fps_map(),
    }
    try:
        if os.path.exists(UI_STATE_PATH):
            with open(UI_STATE_PATH, "r", encoding="utf-8") as f:
                src = json.load(f)
            if isinstance(src, dict):
                src = _migrate_ui_state(src)
                data.update(src)
    except Exception:
        pass
    try:
        data["output_vol"] = max(0, min(100, int(data.get("output_vol", 75))))
    except Exception:
        data["output_vol"] = 75
    data["muted"] = coerce_bool(data.get("muted", False), False)
    data["vis_shuffle"] = coerce_bool(data.get("vis_shuffle", False), False)
    data["repeat_current"] = coerce_bool(data.get("repeat_current", False), False)
    try:
        data["mute_prev_vol"] = max(0, min(100, int(data.get("mute_prev_vol", data["output_vol"]))))
    except Exception:
        data["mute_prev_vol"] = data["output_vol"]
    data["vis_mode"] = normalize_vis_mode(data.get("vis_mode"), default=VIS_MODE)
    if isinstance(data.get("game"), str) and data["game"].strip():
        data["game"] = data["game"].strip().upper()
    else:
        data["game"] = "ALL"
    if isinstance(data.get("variant"), str) and data["variant"].strip():
        variant = data["variant"].strip().lower()
        data["variant"] = "ALL" if variant == "all" else variant
    else:
        data["variant"] = "ALL"
    layout_src = data.get("layout")
    if layout_src is None and isinstance(data.get("layout_preset"), str):
        layout_src = {"preset": data.get("layout_preset")}
    data["layout"] = normalize_layout_config(layout_src, default_preset=DEFAULT_LAYOUT_PRESET)
    q = data.get("free_play_queue")
    data["free_play_queue"] = [str(p) for p in q if isinstance(p, str)] if isinstance(q, list) else []
    try:
        data["free_play_idx"] = max(0, int(data.get("free_play_idx", 0)))
    except (TypeError, ValueError):
        data["free_play_idx"] = 0
    data["vis_fps"] = _normalize_vis_fps(data.get("vis_fps"))
    return data


def _normalize_vis_fps(value):
    """Coerce a persisted tier->fps map into valid, in-range integers."""
    base = default_vis_fps_map()
    lo, hi = min(VIS_FPS_CHOICES), max(VIS_FPS_CHOICES)
    if isinstance(value, dict):
        for tier in base:
            try:
                base[tier] = max(lo, min(hi, int(value[tier])))
            except (KeyError, TypeError, ValueError):
                pass  # keep the default for this tier
    return base

def save_ui_state(data):
    payload = dict(data)
    payload["_version"] = UI_STATE_VERSION
    _atomic_write_json(UI_STATE_PATH, payload)


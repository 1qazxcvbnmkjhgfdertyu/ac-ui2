import os, json

from ac_ui.constants import (
    UI_STATE_PATH, VIS_MODE, VIS_MODES,
    coerce_bool, normalize_vis_mode, _atomic_write_json, DEFAULT_LAYOUT_PRESET,
)
from ac_ui.layout_config import normalize_layout_config

def load_ui_state():
    data = {
        "output_vol": 75,
        "muted": False,
        "mute_prev_vol": 50,
        "vis_mode": VIS_MODE,
        "repeat_current": False,
        "game": "ALL",
        "variant": "ALL",
        "layout": None,
        "theme": "default",
    }
    try:
        if os.path.exists(UI_STATE_PATH):
            with open(UI_STATE_PATH, "r", encoding="utf-8") as f:
                src = json.load(f)
            if isinstance(src, dict):
                data.update(src)
    except Exception:
        pass
    try:
        data["output_vol"] = max(0, min(100, int(data.get("output_vol", 75))))
    except Exception:
        data["output_vol"] = 75
    data["muted"] = coerce_bool(data.get("muted", False), False)
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
    return data

def save_ui_state(data):
    _atomic_write_json(UI_STATE_PATH, data)


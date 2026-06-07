from ac_ui.constants import (
    LAYOUT_PRESETS, LAYOUT_GRID_DEFAULT, LAYOUT_PANEL_NAMES, LAYOUT_PANEL_SLOTS,
    DEFAULT_LAYOUT_PRESET,
)

def _int_opt(opts, key, default):
    try:
        return int(opts.get(key, default))
    except Exception:
        return default

def _str_opt(opts, key, default):
    return str(opts.get(key, default))

def normalize_layout_preset(value, default=None):
    preset = (str(value or "").strip().lower() or str(default or "").strip().lower())
    if preset in LAYOUT_PRESETS:
        return preset
    fallback = str(default or DEFAULT_LAYOUT_PRESET).strip().lower()
    if fallback in LAYOUT_PRESETS:
        return fallback
    return next(iter(LAYOUT_PRESETS))

def default_layout_config(preset=None):
    preset = normalize_layout_preset(preset, default=DEFAULT_LAYOUT_PRESET)
    return {
        "version": 1,
        "preset": preset,
        "grid": dict(LAYOUT_GRID_DEFAULT),
        "panels": {name: dict(spec) for name, spec in LAYOUT_PRESETS[preset].items()},
    }

def _coerce_layout_int(value, default, minimum, maximum):
    try:
        out = int(value)
    except Exception:
        out = int(default)
    return max(minimum, min(maximum, out))

def normalize_layout_config(value, default_preset=None):
    base = default_layout_config(default_preset)
    if not isinstance(value, dict):
        return base
    preset = normalize_layout_preset(value.get("preset"), default=base["preset"])
    grid_src = value.get("grid")
    if isinstance(grid_src, dict):
        cols = _coerce_layout_int(grid_src.get("cols"), LAYOUT_GRID_DEFAULT["cols"], 1, 64)
        rows = _coerce_layout_int(grid_src.get("rows"), LAYOUT_GRID_DEFAULT["rows"], 1, 64)
    else:
        cols = LAYOUT_GRID_DEFAULT["cols"]
        rows = LAYOUT_GRID_DEFAULT["rows"]
    panels_src = value.get("panels") if isinstance(value.get("panels"), dict) else {}
    normalized = {
        "version": 1,
        "preset": preset,
        "grid": {"cols": cols, "rows": rows},
        "panels": {},
    }
    preset_panels = LAYOUT_PRESETS[preset]
    for name in LAYOUT_PANEL_NAMES:
        base_panel = dict(preset_panels.get(name, {}))
        panel_src = panels_src.get(name) if isinstance(panels_src.get(name), dict) else {}
        slot = str(panel_src.get("slot", base_panel.get("slot", "below"))).strip().lower()
        if slot not in LAYOUT_PANEL_SLOTS:
            slot = base_panel.get("slot", "below")
        normalized["panels"][name] = {
            "slot": slot,
            "x": _coerce_layout_int(panel_src.get("x"), base_panel.get("x", 0), 0, max(0, cols - 1)),
            "y": _coerce_layout_int(panel_src.get("y"), base_panel.get("y", 0), 0, max(0, rows - 1)),
            "w": _coerce_layout_int(panel_src.get("w"), base_panel.get("w", cols), 1, cols),
            "h": _coerce_layout_int(panel_src.get("h"), base_panel.get("h", rows), 1, rows),
        }
    return normalized

def cycle_layout_preset(layout_config):
    current = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)
    presets = tuple(LAYOUT_PRESETS.keys())
    idx = presets.index(current["preset"]) if current["preset"] in presets else 0
    return default_layout_config(presets[(idx + 1) % len(presets)])

def layout_preset_label(layout_config):
    preset = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)["preset"]
    return preset.replace("_", " ").title()

def layout_panels_in_slot(layout_config, slot):
    if slot not in LAYOUT_PANEL_SLOTS:
        return []
    panels = normalize_layout_config(layout_config, default_preset=DEFAULT_LAYOUT_PRESET)["panels"]
    ordered = []
    for name, spec in panels.items():
        if spec.get("slot") == slot:
            ordered.append((int(spec.get("y", 0)), int(spec.get("x", 0)), name))
    ordered.sort()
    return [name for _, _, name in ordered]


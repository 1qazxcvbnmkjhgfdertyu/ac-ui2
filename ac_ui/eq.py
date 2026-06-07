import os, json

from ac_ui.constants import (
    EQ_BAND_COUNT, EQ_BAND_MIN, EQ_BAND_MAX, EQ_PRESETS, EQ_CONFIG_PATH,
    EQ_ENABLED, _atomic_write_json,
)

def _clamp_eq_band(value):
    return max(EQ_BAND_MIN, min(EQ_BAND_MAX, float(value)))


def normalize_eq_bands(bands):
    out = []
    for i in range(EQ_BAND_COUNT):
        try:
            out.append(_clamp_eq_band(bands[i] if i < len(bands) else 0.0))
        except Exception:
            out.append(0.0)
    return out


def default_eq_bands():
    return list(EQ_PRESETS["flat"])


def load_eq_bands():
    path = EQ_CONFIG_PATH
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("bands"), list):
                return normalize_eq_bands(data["bands"]), data.get("preset")
            if isinstance(data, list):
                return normalize_eq_bands(data), None
    except Exception:
        pass
    return default_eq_bands(), "flat"


def save_eq_bands(bands, preset_name=None):
    path = EQ_CONFIG_PATH
    try:
        payload = {"bands": normalize_eq_bands(bands)}
        if preset_name:
            payload["preset"] = preset_name
        _atomic_write_json(path, payload)
        return True
    except Exception:
        return False


def build_mpv_eq_filter(bands):
    """mpv superequalizer: 1b..10b gains in dB (cliamp-aligned bands)."""
    parts = []
    for i, gain in enumerate(normalize_eq_bands(bands)):
        parts.append(f"{i + 1}b={gain:g}")
    return "superequalizer=" + ":".join(parts)


def apply_mpv_eq(ipc_path, bands=None):
    if not EQ_ENABLED or not ipc_path:
        return False
    try:
        if not os.path.exists(ipc_path):
            return False
    except Exception:
        return False
    from ac_ui.audio import mpv_command
    resolved = normalize_eq_bands(bands if bands is not None else load_eq_bands()[0])
    if all(b == 0.0 for b in resolved):
        mpv_command(ipc_path, ["af", "remove", "@acui-eq"])
        return True
    af = build_mpv_eq_filter(resolved)
    mpv_command(ipc_path, ["af", "remove", "@acui-eq"])
    return mpv_command(ipc_path, ["af", "add", f"@acui-eq:{af}"])



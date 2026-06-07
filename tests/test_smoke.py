"""
Five smoke tests — the minimum safety net before structural refactoring.

Each test covers one critical path:
  1. Launcher script exists and is executable
  2. CLI --help exits 0 without crashing
  3. load_ui_state() returns a valid dict with required keys
  4. build_layout_preview() returns non-empty lines for common sizes
  5. Audio module imports and exposes expected public API surface
"""
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(REPO, "ac-ui")


# ── 1. Launcher exists and is executable ─────────────────────────────────────

def test_launcher_exists_and_is_executable():
    assert os.path.isfile(LAUNCHER), f"Launcher not found: {LAUNCHER}"
    assert os.access(LAUNCHER, os.X_OK), f"Launcher not executable: {LAUNCHER}"


# ── 2. CLI --help exits 0 ────────────────────────────────────────────────────

def test_cli_help():
    result = subprocess.run(
        [sys.executable, LAUNCHER, "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"--help exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    out = result.stdout + result.stderr
    assert out.strip(), "--help produced no output"


# ── 3. load_ui_state() returns a valid dict ──────────────────────────────────

REQUIRED_UI_STATE_KEYS = {
    "output_vol", "muted", "mute_prev_vol",
    "vis_mode", "repeat_current", "game", "variant",
    "layout", "theme",
}

def test_load_ui_state_returns_valid_dict(tmp_path, monkeypatch):
    # Point state file at a non-existent path so it returns defaults
    import ac_ui.constants as C
    monkeypatch.setattr(C, "UI_STATE_PATH", str(tmp_path / "ui_state.json"))

    from ac_ui.persist import load_ui_state
    state = load_ui_state()

    assert isinstance(state, dict), "load_ui_state() must return a dict"
    missing = REQUIRED_UI_STATE_KEYS - state.keys()
    assert not missing, f"ui_state missing keys: {missing}"

    assert isinstance(state["output_vol"], int)
    assert 0 <= state["output_vol"] <= 100
    assert isinstance(state["muted"], bool)
    assert isinstance(state["vis_mode"], str)


# ── 4. build_layout_preview() renders non-empty lines ────────────────────────

@pytest.mark.parametrize("cols,rows", [
    (80, 24),
    (120, 40),
    (180, 50),
    (60, 20),   # tiny / compact path
])
def test_build_layout_preview(cols, rows):
    from ac_ui.ui import build_layout_preview
    lines = build_layout_preview(cols, rows)
    assert isinstance(lines, list), "build_layout_preview must return a list"
    assert len(lines) > 0, f"build_layout_preview({cols},{rows}) returned empty"
    assert all(isinstance(ln, str) for ln in lines), "all lines must be str"


# ── 5. Audio module public API surface ───────────────────────────────────────

REQUIRED_AUDIO_EXPORTS = {
    "mpv_start", "mpv_command", "mpv_query", "mpv_query_props",
    "setup_private_sink", "teardown_private_sink",
    "list_sinks", "get_mute_volume",
    "cleanup_stale_socket", "detect_cava_input",
    "cava_config_text", "calc_cava_bars",
}

def test_audio_module_public_api():
    import ac_ui.audio as audio
    missing = REQUIRED_AUDIO_EXPORTS - set(dir(audio))
    assert not missing, f"audio module missing expected exports: {missing}"

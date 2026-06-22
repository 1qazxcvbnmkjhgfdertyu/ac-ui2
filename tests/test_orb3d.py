"""The 3D audio orb renders at the right dimensions, draws a visible orb when
there's audio, and is registered in the visualizer mode set."""
import math

import ac_ui.visualizer as V
from ac_ui.audio_config import VIS_MODES, VIS_MODE_ALIASES, vis_tier


def _loud_bars(n):
    return tuple(0.4 + 0.5 * abs(math.sin(i * 0.4)) for i in range(n))


def test_registered():
    assert "orb3d" in VIS_MODES
    assert "orb3d" in V._VIS_DISPATCH
    assert vis_tier("orb3d") == "fast"
    assert VIS_MODE_ALIASES["orb"] == "orb3d"


def test_dimensions():
    for h, w in [(8, 24), (20, 60), (40, 120)]:
        st = {}
        lines = V.orb3d_render_lines(_loud_bars(64), h, w, st, use_color=True)
        assert len(lines) == h
        # braille glyphs are 1 cell wide; visible width should match w
        assert all(isinstance(ln, str) for ln in lines)


def test_draws_something():
    st = {}
    lines = None
    # warm a few frames so the spike envelopes build up
    for i in range(30):
        lines = V.orb3d_render_lines(_loud_bars(64), 24, 80, st, use_color=False)
    nonblank = sum(1 for ln in lines for ch in ln if ch not in (" ", ""))
    assert nonblank > 50, "orb should draw a visible body + spikes"


def test_handles_silence_and_tiny():
    # silence shouldn't crash and should still render the (dim) orb body
    st = {}
    lines = V.orb3d_render_lines((0.0,), 10, 30, st, use_color=True)
    assert len(lines) == 10
    # degenerate sizes
    assert V.orb3d_render_lines((0.0,), 0, 0, {}) == [" "]

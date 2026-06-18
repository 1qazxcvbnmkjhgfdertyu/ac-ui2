"""Tests for micro-interaction feedback primitives (feedback.py)."""
import ac_ui.feedback as fb


def test_spinner_frame_cycles_over_time():
    frames = fb.spinner_frames()
    # At fps=10, 0.0s and 0.1s should land on different frames.
    a = fb.spinner_frame(0.0, fps=10)
    b = fb.spinner_frame(0.1, fps=10)
    assert a in frames and b in frames
    assert a != b


def test_spinner_frame_wraps():
    frames = fb.spinner_frames()
    n = len(frames)
    # Advancing a full cycle returns to the start frame.
    assert fb.spinner_frame(0.0, fps=10) == fb.spinner_frame(n / 10.0, fps=10)


def test_spinner_static_when_no_motion(monkeypatch):
    monkeypatch.setattr(fb, "NO_MOTION", True)
    frames = fb.spinner_frames()
    assert fb.spinner_frame(0.0) == frames[0]
    assert fb.spinner_frame(99.0) == frames[0]


def test_loading_line_contains_label_and_glyph():
    line = fb.loading_line("Converting", 0.0, fps=10)
    assert "Converting" in line
    assert line[0] in fb.spinner_frames()


def test_negative_elapsed_is_safe():
    assert fb.spinner_frame(-5.0) in fb.spinner_frames()

import io
import sys

from ac_ui import term


def _capture_render(lines, *, width, height):
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        term.render(lines, width=width, height=height)
    finally:
        sys.stdout = real
    return buf.getvalue()


def test_render_uses_full_repaint_when_most_rows_change():
    term.invalidate_render_cache()
    out = _capture_render(["aaaa", "bbbb", "cccc", "dddd"], width=10, height=4)
    assert out.startswith("\x1b[H\x1b[K")
    assert "\r\n\x1b[K" in out
    assert "\x1b[1;1H" not in out


def test_render_keeps_sparse_diff_for_small_changes():
    term.invalidate_render_cache()
    _capture_render(["aaaa", "bbbb", "cccc", "dddd", "eeee"], width=10, height=5)
    out = _capture_render(["aaaa", "ZZZZ", "cccc", "dddd", "eeee"], width=10, height=5)
    assert out == "\x1b[2;1HZZZZ\x1b[K"

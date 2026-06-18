import math
import os, sys, re, select, termios, tty, subprocess, shutil, unicodedata, ctypes, ctypes.util

from ac_ui.constants import SHOW_TITLE_ART
import ac_ui.colors as _clrs
from ac_ui.colors import (
    USE_COLOR, visible_len, char_cell_width, plain_visible_len, strip_ansi,
    paint, gradient_at, theme_art_gradient, theme_art_style, theme_role,
)

# Mutable globals updated by ui.py via module reference
TITLE_ART = []
TITLE_ART_COLORED = False
TITLE_ART_BASE = []
TITLE_ART_VERSION = 0

# Differential render: only rewrite lines that changed (btop pattern)
_render_prev_lines: list = []
_render_prev_raw_lines: list = []
_render_prev_width: int | None = None

class RawMode:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self
    def __exit__(self, *args):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()

def disable_autowrap():
    sys.stdout.write("\033[?7l")
    sys.stdout.flush()

def enable_autowrap():
    sys.stdout.write("\033[?7h")
    sys.stdout.flush()

def _write_tty(seq: bytes):
    """Write bytes directly to the terminal fd, bypassing Python stdout buffering."""
    try:
        os.write(sys.stdout.fileno(), seq)
    except OSError:
        try:
            with open("/dev/tty", "wb", buffering=0) as t:
                t.write(seq)
        except OSError:
            pass

def rename_process(name: str):
    """Rename the process via prctl so fish/ps see 'ac-ui' instead of 'python3'."""
    try:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        PR_SET_NAME = 15
        _libc.prctl(PR_SET_NAME, name.encode()[:15], 0, 0, 0)
    except Exception:
        pass
    sys.argv[0] = name  # fallback for tools that read argv

def set_terminal_title(title: str):
    _write_tty(f"\033]0;{title}\007".encode())

def reset_terminal_title():
    _write_tty(b"\033]0;\007")

def enter_alt_screen():
    sys.stdout.write("\033[?1049h\033[H\033[2J")
    # enable focus tracking (supported by many terminals)
    sys.stdout.write("\033[?1004h")
    sys.stdout.flush()

def exit_alt_screen():
    # disable focus tracking
    sys.stdout.write("\033[?1004l")
    sys.stdout.write("\033[?1049l")
    sys.stdout.flush()

def invalidate_render_cache(clear_screen=False):
    """Reset line-diff state (resize, full-screen overlays)."""
    global _render_prev_lines, _render_prev_raw_lines, _render_prev_width
    _render_prev_lines = []
    _render_prev_raw_lines = []
    _render_prev_width = None
    if clear_screen:
        sys.stdout.write("\033[2J")
        sys.stdout.flush()


def animate_title_art(base_lines, phase=0.0):
    """Colorize title art in-process using the active theme gradient."""
    if not USE_COLOR or not base_lines:
        return list(base_lines), False
    style = theme_art_style()
    mode = style.get("mode", "sweep")
    outline = theme_role(style.get("outline", "border_hi"), _clrs._active_tod_grad)
    art_grad = theme_art_gradient(_clrs._active_tod_grad)
    total = sum(max(1, len(line)) for line in base_lines)
    cursor = 0
    out = []
    phase_shift = int(phase * 100)

    def is_edge(row_idx, col_idx):
        neighbors = ((-1, 0), (1, 0), (0, -1), (0, 1))
        for drow, dcol in neighbors:
            rr = row_idx + drow
            cc = col_idx + dcol
            if rr < 0 or rr >= len(base_lines):
                return True
            line = base_lines[rr]
            if cc < 0 or cc >= len(line) or line[cc] == " ":
                return True
        return False

    for row_idx, line in enumerate(base_lines):
        parts = []
        for col_idx, ch in enumerate(line):
            if ch == " ":
                parts.append(ch)
                cursor += 1
                continue
            sweep = ((cursor * 100) // max(1, total - 1) + phase_shift + row_idx * 7 + col_idx * 2) % 101
            edge = is_edge(row_idx, col_idx)
            dim = False
            if mode == "outline":
                color = outline if edge else gradient_at(art_grad, sweep)
                bold = edge or ((row_idx + col_idx + phase_shift) % 11 == 0)
            elif mode == "neon":
                glow = (sweep + int(14 * math.sin(row_idx * 0.8 + col_idx * 0.18 + phase * math.tau))) % 101
                color = outline if edge and ((row_idx + col_idx + phase_shift) % 2 == 0) else gradient_at(art_grad, glow)
                bold = True
            elif mode == "ember":
                ember = min(100, max(0, sweep + int(18 * math.sin(row_idx * 0.55 + phase * math.tau))))
                color = outline if edge else gradient_at(art_grad, ember)
                bold = edge or ((row_idx + col_idx + phase_shift) % 7 == 0)
            elif mode == "tide":
                tide = (sweep + int(16 * math.sin(row_idx * 0.9 + col_idx * 0.22 + phase * math.tau))) % 101
                color = outline if edge else gradient_at(art_grad, tide)
                bold = edge or ((col_idx + phase_shift) % 13 == 0)
            elif mode == "bloom":
                bloom = (
                    sweep
                    + int(10 * math.sin(row_idx * 0.75 + phase * math.tau))
                    + int(8 * math.cos(col_idx * 0.18 + phase * math.tau))
                ) % 101
                color = outline if edge and ((row_idx + col_idx + phase_shift) % 3 == 0) else gradient_at(art_grad, bloom)
                bold = edge or ((row_idx * 3 + col_idx + phase_shift) % 17 == 0)
                dim = (not edge) and ((row_idx + col_idx + phase_shift) % 11 == 0)
            elif mode == "crayon":
                stripe = (row_idx * 19 + col_idx * 9 + phase_shift * 3) % 101
                color = outline if edge else gradient_at(art_grad, stripe)
                bold = (not edge) or ((row_idx + col_idx + phase_shift) % 5 == 0)
                dim = edge and ((col_idx + phase_shift) % 4 == 0)
            elif mode == "chalk":
                stripe = (row_idx * 13 + col_idx * 7 + phase_shift * 2) % 101
                color = outline if edge else gradient_at(art_grad, stripe)
                bold = edge or ((row_idx + phase_shift) % 6 == 0)
                dim = (not edge) and ((row_idx * 5 + col_idx + phase_shift) % 4 == 0)
            elif mode == "ribbon":
                ribbon = (sweep + int(16 * math.sin(col_idx * 0.26 - phase * math.tau))) % 101
                color = outline if edge else gradient_at(art_grad, ribbon)
                bold = edge or ((row_idx + col_idx + phase_shift) % 8 == 0)
            else:
                color = gradient_at(art_grad, sweep)
                bold = ((row_idx + col_idx + phase_shift) % 9 == 0)
            parts.append(paint(ch, fg=color, bold=bold, dim=dim))
            cursor += 1
        out.append("".join(parts))
    return out, True


def render(lines, width=None, height=None):
    """Differential renderer: only outputs lines that changed since last frame."""
    global _render_prev_lines, _render_prev_raw_lines, _render_prev_width
    if width is None or height is None:
        size = shutil.get_terminal_size(fallback=(80, 24))
        width = size.columns
        height = size.lines
    if len(lines) < height:
        lines = lines + [""] * (height - len(lines))
    elif len(lines) > height:
        lines = lines[:height]

    # Clip each line to terminal width
    clipped = []
    same_width = _render_prev_width == width
    for idx, line in enumerate(lines):
        if same_width and idx < len(_render_prev_raw_lines) and line == _render_prev_raw_lines[idx]:
            clipped.append(_render_prev_lines[idx])
            continue
        vis = len(line) if "\x1b[" not in line and line.isascii() else visible_len(line)
        if vis >= width:
            line = truncate_ansi_visible(line, max(0, width - 1))
        clipped.append(line)

    # Extend previous frame buffer to match current height
    prev = _render_prev_lines
    if len(prev) != len(clipped):
        prev = [""] * len(clipped)

    buf = []
    for idx, (new_line, old_line) in enumerate(zip(clipped, prev)):
        if new_line != old_line:
            buf.append(f"\033[{idx + 1};1H{new_line}\033[K")

    if buf:
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    _render_prev_lines = clipped
    _render_prev_raw_lines = list(lines)
    _render_prev_width = width

def _read_key(fd, timeout=0.1):
    try:
        r, _, _ = select.select([fd], [], [], timeout)
    except (InterruptedError, OSError, ValueError):
        return None
    if not r:
        return None
    try:
        ch = os.read(fd, 1).decode("utf-8", errors="ignore")
    except Exception:
        return None
    if ch != "\x1b":
        return ch
    # Read a short escape sequence payload.
    seq = ""
    for _ in range(8):
        try:
            r, _, _ = select.select([fd], [], [], 0.01)
        except (InterruptedError, OSError, ValueError):
            break
        if not r:
            break
        try:
            seq += os.read(fd, 1).decode("utf-8", errors="ignore")
        except Exception:
            break
        # CSI sequences end with a letter or ~
        if seq and seq[-1] in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz~":
            break
    if seq == "[I":
        return "FOCUS_IN"
    if seq == "[O":
        return "FOCUS_OUT"
    if seq.startswith("["):
        if seq.endswith("A"):
            return "UP"
        if seq.endswith("B"):
            return "DOWN"
        if seq.endswith("C"):
            return "RIGHT"
        if seq.endswith("D"):
            return "LEFT"
        if seq in ("[5~", "[I"):   # Page Up / xterm shift-tab
            return "PAGEUP"
        if seq in ("[6~", "[G"):   # Page Down
            return "PAGEDOWN"
    return "ESC"

def truncate_plain(s, maxlen):
    if maxlen <= 0:
        return ""
    if plain_visible_len(s) <= maxlen:
        return s
    ellipsis = "..."
    ell_w = plain_visible_len(ellipsis)
    if maxlen <= ell_w:
        # No room for ellipsis — hard truncate
        out = []
        width = 0
        for ch in s:
            ch_w = char_cell_width(ch)
            if width + ch_w > maxlen:
                break
            out.append(ch)
            width += ch_w
        return "".join(out)
    limit = maxlen - ell_w
    out = []
    width = 0
    for ch in s:
        ch_w = char_cell_width(ch)
        if width + ch_w > limit:
            break
        out.append(ch)
        width += ch_w
    return "".join(out) + ellipsis

def fit_ansi_line(s, maxlen):
    """Truncate to ``maxlen`` visible columns AND return (line, visible_width).

    Returning the width lets callers (e.g. build_box padding) avoid a second
    full walk of the string just to measure it.
    """
    if maxlen <= 0:
        return "", 0
    # Fast path: plain ASCII with no escapes is one column per char.
    if "\x1b" not in s and s.isascii():
        if len(s) <= maxlen:
            return s, len(s)
        return s[:maxlen], maxlen
    out = []
    visible = 0
    i = 0
    n = len(s)
    open_ansi = False
    while i < n:
        ch = s[i]
        if ch == "\x1b" and i + 1 < n and s[i + 1] == "[":
            end = i + 2
            while end < n and s[end] != "m":
                end += 1
            end = min(end + 1, n)
            out.append(s[i:end])
            open_ansi = not s[i:end].endswith("[0m")
            i = end
            continue
        if visible >= maxlen:
            break
        # Count wide chars (CJK, some emoji) as 2 columns — btop "wide" flag.
        w = char_cell_width(ch)
        if visible + w > maxlen:
            break  # don't write a wide char that would overflow
        out.append(ch)
        visible += w
        i += 1
    if open_ansi:
        out.append("\x1b[0m")
    return "".join(out), visible


def truncate_ansi_visible(s, maxlen):
    """
    Btop uresize() port: truncate to maxlen visible columns while
    - respecting Unicode codepoint boundaries (not bytes)
    - counting East-Asian wide chars as 2 columns
    - closing any open ANSI color sequence at the cut point
    """
    return fit_ansi_line(s, maxlen)[0]

def build_title_art(text, width):
    if not SHOW_TITLE_ART:
        return [], False, []
    if shutil.which("figlet") is None:
        return [], False, []
    try:
        style = theme_art_style()
        font = str(style.get("font") or "standard").strip() or "standard"
        cmd = ["figlet", "-w", str(max(10, width))]
        if font:
            cmd.extend(["-f", font])
        cmd.append(text)
        try:
            art = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        except Exception:
            art = subprocess.check_output(
                ["figlet", "-w", str(max(10, width)), text],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        base_lines = [ln.rstrip("\n") for ln in art.splitlines()]
        lines, colored = animate_title_art(base_lines, 0.0)
        return lines, colored, base_lines
    except Exception:
        return [], False, []

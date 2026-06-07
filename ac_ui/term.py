import os, sys, re, select, termios, tty, subprocess, shutil, unicodedata

from ac_ui.constants import SHOW_TITLE_ART
from ac_ui.colors import USE_COLOR, visible_len, char_cell_width, plain_visible_len, strip_ansi

# Mutable globals updated by ui.py via module reference
TITLE_ART = []
TITLE_ART_COLORED = False
TITLE_ART_BASE = []
TITLE_LOLCAT_PATH = None
TITLE_ART_VERSION = 0

# Differential render: only rewrite lines that changed (btop pattern)
_render_prev_lines: list = []

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
    global _render_prev_lines
    _render_prev_lines = []
    if clear_screen:
        sys.stdout.write("\033[2J")
        sys.stdout.flush()


def render(lines, width=None, height=None):
    """Differential renderer: only outputs lines that changed since last frame."""
    global _render_prev_lines
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
    for line in lines:
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

def truncate_ansi_visible(s, maxlen):
    """
    Btop uresize() port: truncate to maxlen visible columns while
    - respecting Unicode codepoint boundaries (not bytes)
    - counting East-Asian wide chars as 2 columns
    - closing any open ANSI color sequence at the cut point
    """
    import unicodedata
    if maxlen <= 0:
        return ""
    out = []
    visible = 0
    i = 0
    open_ansi = False
    while i < len(s):
        ch = s[i]
        if ch == "\x1b" and i + 1 < len(s) and s[i + 1] == "[":
            end = i + 2
            while end < len(s) and s[end] != "m":
                end += 1
            end = min(end + 1, len(s))
            seq = s[i:end]
            out.append(seq)
            open_ansi = not seq.endswith("[0m")
            i = end
            continue
        if visible >= maxlen:
            break
        # Count wide chars (CJK, some emoji) as 2 columns — btop "wide" flag
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if visible + w > maxlen:
            break  # don't write a wide char that would overflow
        out.append(ch)
        visible += w
        i += 1
    if open_ansi:
        out.append("\x1b[0m")
    return "".join(out)

def build_title_art(text, width):
    if not SHOW_TITLE_ART:
        return [], False, [], None
    if shutil.which("figlet") is None:
        return [], False, [], None
    try:
        art = subprocess.check_output(
            ["figlet", "-w", str(max(10, width)), text],
            text=True,
        )
        base_lines = [ln.rstrip("\n") for ln in art.splitlines()]
        lines = list(base_lines)
        lolcat_path = shutil.which("lolcat")
        if lolcat_path is None:
            for candidate in ("/usr/games/lolcat", "/usr/bin/lolcat", "/bin/lolcat"):
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    lolcat_path = candidate
                    break
        if USE_COLOR and lolcat_path is not None:
            try:
                colored = subprocess.check_output(
                    [lolcat_path, "-f"],
                    input="\n".join(base_lines),
                    text=True,
                )
                lines = [ln.rstrip("\n") for ln in colored.splitlines()]
                return lines, True, base_lines, lolcat_path
            except Exception:
                return lines, False, base_lines, lolcat_path
        return lines, False, base_lines, lolcat_path
    except Exception:
        return [], False, [], None



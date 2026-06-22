"""Live overlays: panels drawn *on top of* the still-animating main frame.

Unlike a blocking modal that takes over stdin and paints a blank screen, a live
overlay is held as state by the main event loop.  Every frame the loop builds the
normal visualizer frame, then :func:`composite_over` splices the overlay's box
into it, so the visualizer
keeps moving in the cells the box doesn't cover.  Keys are routed to the active
overlay's ``handle`` until it reports it is done.

The terminal has no real transparency — a cell is one glyph — so "layering" here
means compositing in our own buffer: the box occludes its own rectangle, and the
live frame shows everywhere else.
"""
from __future__ import annotations

import os

from ac_ui.colors import char_cell_width, visible_len
from ac_ui.constants import LIBRARY_DIR
from ac_ui.finder import build_finder_lines, rank_items
from ac_ui.acgc_extract import BackgroundExtract, find_disc, find_port
from ac_ui.import_wizard import (
    BackgroundImport,
    browse_entries,
    build_browse_lines,
    build_done_lines,
    build_progress_lines,
    default_start_dir,
)
from ac_ui.help_overlay import (
    build_help_detail_box,
    build_help_groups,
    build_help_lines,
    filter_help_groups,
)
from ac_ui.layout import build_box
from ac_ui.layout import format_position_label
from ac_ui.menu import build_menu_lines
from ac_ui.palette import build_palette_commands, build_palette_lines, rank_commands
from ac_ui.term import fit_ansi_line
from ac_ui.viewer import build_viewer_frame
from ac_ui.vis_fps_menu import _TIERS, build_vis_fps_lines, cycle_fps

_RESET = "\x1b[0m"
_HINT_PICK = "[↑↓] move  [enter] choose  [esc] close"
_HINT_SAVE = "[←→] adjust  [enter] save  [esc] cancel"


def _drop_cols(s: str, k: int) -> str:
    """Return ``s`` with its first ``k`` visible columns removed.

    ANSI colour state active at the cut point is re-emitted so the remainder
    keeps the right colour.
    """
    if k <= 0:
        return s
    vis = 0
    i = 0
    n = len(s)
    cur = ""
    while i < n and vis < k:
        ch = s[i]
        if ch == "\x1b" and i + 1 < n and s[i + 1] == "[":
            e = i + 2
            while e < n and s[e] != "m":
                e += 1
            e = min(e + 1, n)
            esc = s[i:e]
            cur = "" if esc.endswith("[0m") else esc
            i = e
            continue
        vis += char_cell_width(ch)
        i += 1
    return (cur + s[i:]) if cur else s[i:]


def _overlay_row(base: str, seg: str, start_col: int, cols: int) -> str:
    """Splice ``seg`` into ``base`` starting at visible column ``start_col``.

    Columns left of the box and right of it keep the live frame's content (and
    colour); the box's own cells replace whatever was underneath.
    """
    seg_w = visible_len(seg)
    left, lvis = fit_ansi_line(base, start_col)
    if lvis < start_col:
        left += " " * (start_col - lvis)
    right = _drop_cols(base, start_col + seg_w)
    return f"{left}{_RESET}{seg}{_RESET}{right}"


def composite_over(base_lines: list[str], box: list[str], cols: int, rows: int) -> list[str]:
    """Return a copy of ``base_lines`` with ``box`` centred on top of it."""
    out = list(base_lines)
    if len(out) < rows:
        out.extend([""] * (rows - len(out)))
    start_row = max(0, rows // 2 - len(box) // 2)
    for i, bline in enumerate(box):
        r = start_row + i
        if not (0 <= r < rows):
            continue
        pad = max(0, (cols - visible_len(bline)) // 2)
        out[r] = _overlay_row(out[r], bline, pad, cols)
    return out


class VisFpsOverlay:
    """Non-blocking single-fps menu — one rate applied to every visualizer.

    ``handle`` adjusts the rate per key; on save ``result`` is a uniform
    tier->fps map (so the persisted format is unchanged), on cancel it is ``None``.
    """

    kind = "fps"

    def __init__(self, fps_map: dict, pinned: bool = False):
        # Seed the single control from the current map (uniform after any save).
        try:
            self.fps = int(max(fps_map.values())) if fps_map else 60
        except (ValueError, TypeError, AttributeError):
            self.fps = 60
        self.pinned = pinned
        self.result: dict | None = None

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(44, min(cols - 6, 64))
        plain, color = build_vis_fps_lines(self.fps, inner_w, self.pinned)
        box, _ = build_box(
            plain, color, maxw_override=inner_w,
            title="Visualizer frame rate", title2=_HINT_SAVE,
        )
        return box

    def handle(self, ch: str) -> bool:
        """Process one key. Return True when the overlay should close."""
        if ch == "ESC":
            self.result = None
            return True
        if ch in ("\r", "\n"):
            self.result = {t: self.fps for t in _TIERS}
            return True
        if ch in ("LEFT", "h", "DOWN", "j"):
            self.fps = cycle_fps(self.fps, -1)
        elif ch in ("RIGHT", "l", "UP", "k"):
            self.fps = cycle_fps(self.fps, +1)
        return False


class PaletteOverlay:
    """Command palette as a live overlay. ``result`` is the chosen command's
    primary key (re-dispatched by the main loop) or ``None``."""

    kind = "palette"

    def __init__(self):
        self.commands = build_palette_commands()
        self.query = ""
        self.selected = 0
        self.result: str | None = None
        self._matches: list = []

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(36, min(cols - 8, 70))
        list_rows = max(3, min(14, rows - 8))
        matches = rank_commands(self.commands, self.query)
        if self.selected >= len(matches):
            self.selected = max(0, len(matches) - 1)
        self._matches = matches
        plain, color = build_palette_lines(matches, self.query, self.selected, inner_w, list_rows + 2)
        pos = f"  {format_position_label(self.selected, len(matches))}" if matches else "  0/0"
        box, _ = build_box(
            plain, color, maxw_override=inner_w,
            title=f"Command Palette{pos}", title2="[type] search  [enter] run  [esc] close",
        )
        return box

    def handle(self, ch: str) -> bool:
        m = self._matches
        if ch in ("ESC", "\x10"):
            return True
        if ch in ("\r", "\n"):
            if m:
                self.result = m[self.selected].primary
            return True
        if ch == "UP" and m:
            self.selected = (self.selected - 1) % len(m)
        elif ch == "DOWN" and m:
            self.selected = (self.selected + 1) % len(m)
        elif ch in ("\x7f", "\b", "BACKSPACE"):
            self.query = self.query[:-1]
            self.selected = 0
        elif len(ch) == 1 and ch.isprintable():
            self.query += ch
            self.selected = 0
        return False


class FinderOverlay:
    """Fuzzy library finder. ``result`` is the chosen item's value or ``None``."""

    kind = "finder"

    def __init__(self, title: str, items: list):
        self.title = title
        self.items = items
        self.total = len(items)
        self.query = ""
        self.selected = 0
        self.result = None
        self._matches: list = []

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(40, min(cols - 6, 80))
        list_rows = max(4, min(18, rows - 7))
        matches = rank_items(self.items, self.query)
        if self.selected >= len(matches):
            self.selected = max(0, len(matches) - 1)
        self._matches = matches
        plain, color = build_finder_lines(
            matches, self.query, self.selected, self.total, inner_w, list_rows + 2,
        )
        pos = f"  {format_position_label(self.selected, len(matches))}" if matches else "  0/0"
        box, _ = build_box(
            plain, color, maxw_override=inner_w,
            title=f"{self.title}{pos}", title2="[type] search  [enter] play  [esc] close",
        )
        return box

    def handle(self, ch: str) -> bool:
        m = self._matches
        if ch == "ESC":
            return True
        if ch in ("\r", "\n"):
            if m:
                self.result = m[self.selected].value
            return True
        if ch == "UP" and m:
            self.selected = (self.selected - 1) % len(m)
        elif ch == "DOWN" and m:
            self.selected = (self.selected + 1) % len(m)
        elif ch in ("\x7f", "\b", "BACKSPACE"):
            self.query = self.query[:-1]
            self.selected = 0
        elif len(ch) == 1 and ch.isprintable():
            self.query += ch
            self.selected = 0
        return False


class VisPickerOverlay:
    """Pick a visualizer from a scrollable list. Arrow keys (or j/k) move; type to
    filter by name or alias; Enter applies, Esc cancels. Starts on the current
    mode. ``result`` is the chosen mode name or ``None``. Live overlay — the
    visualizer keeps animating behind it as a preview."""

    kind = "vispick"

    def __init__(self, title: str, items: list, current=None):
        self.title = title
        self.items = items
        self.total = len(items)
        self.query = ""
        self.selected = 0
        if current is not None:
            for i, it in enumerate(items):
                if it.value == current:
                    self.selected = i
                    break
        self.result = None
        self._matches: list = []

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(30, min(cols - 6, 52))
        list_rows = max(5, min(20, rows - 7))
        matches = rank_items(self.items, self.query)
        if self.selected >= len(matches):
            self.selected = max(0, len(matches) - 1)
        self._matches = matches
        plain, color = build_finder_lines(
            matches, self.query, self.selected, self.total, inner_w, list_rows + 2,
        )
        pos = f"  {format_position_label(self.selected, len(matches))}" if matches else "  0/0"
        box, _ = build_box(
            plain, color, maxw_override=inner_w, title=f"{self.title}{pos}",
            title2="[type] filter  [enter] choose  [esc] cancel",
        )
        return box

    def handle(self, ch: str) -> bool:
        m = self._matches
        if ch == "ESC":
            return True
        if ch in ("\r", "\n"):
            if m:
                self.result = m[self.selected].value
            return True
        if ch in ("UP", "k") and m:
            self.selected = (self.selected - 1) % len(m)
        elif ch in ("DOWN", "j") and m:
            self.selected = (self.selected + 1) % len(m)
        elif ch in ("\x7f", "\b", "BACKSPACE"):
            self.query = self.query[:-1]
            self.selected = 0
        elif len(ch) == 1 and ch.isprintable():
            self.query += ch
            self.selected = 0
        return False


class TourOverlay:
    """Paged guided tour of the app. Live overlay; the player keeps animating
    behind it. ``result`` is always None (informational)."""

    kind = "tour"

    def __init__(self, pages=None):
        from ac_ui.tour import TOUR_GENERAL
        self.pages = pages or TOUR_GENERAL
        self.idx = 0
        self.result = None

    def build(self, cols: int, rows: int) -> list[str]:
        from ac_ui.tour import build_tour_lines
        inner_w = max(50, min(cols - 6, 70))
        return build_tour_lines(self.pages, self.idx, inner_w)

    def handle(self, ch: str) -> bool:
        if ch in ("ESC", "q", "Q"):
            return True
        if ch in ("RIGHT", " ", "\r", "\n"):
            if self.idx >= len(self.pages) - 1:
                return True                      # past the last page → close
            self.idx += 1
        elif ch == "LEFT":
            self.idx = max(0, self.idx - 1)
        return False


class WelcomeOverlay:
    """First-run greeting, shown automatically when there's no music yet. Points
    the user straight at the two ways to get music. ``result`` is a key to
    re-dispatch ('i' import / 'X' extract) or None (dismiss)."""

    kind = "welcome"

    def __init__(self):
        self.result = None

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(50, min(cols - 6, 66))
        plain = [
            "Welcome to ac-ui!",
            "",
            "There's no music here yet. Two easy ways to fill it:",
            "",
            "  [i]   Import your own music     — point at a folder, done.",
            "  [X]   Extract Animal Crossing   — from your own GameCube disc.",
            "  [G]   Take a quick guided tour  — learn the app in a minute.",
            "",
            "  [esc] Not now — explore the player first.",
        ]
        box, _ = build_box(plain, plain, maxw_override=inner_w,
                           title="Getting started", title2="")
        return box

    def handle(self, ch: str) -> bool:
        if ch in ("i", "I"):
            self.result = "i"
            return True
        if ch == "X":
            self.result = "X"
            return True
        if ch == "G":
            self.result = "G"
            return True
        if ch in ("ESC", "\r", "\n"):
            self.result = None
            return True
        return False


class ImportOverlay:
    """In-app music import wizard. Browse to a folder, import it into the
    free-play library (tags read automatically, formats kept or converted), all
    on a background thread. ``result`` is the library dir to switch free-play to
    on success+confirm, else ``None``."""

    kind = "import"

    def __init__(self, start_dir: str | None = None):
        self.cwd = start_dir or default_start_dir()
        self.entries = browse_entries(self.cwd)
        self.selected = 0
        self.state = "browse"        # "browse" | "running" | "done"
        self.job = None
        self.done_result = None
        self.result = None

    def _reload(self):
        self.entries = browse_entries(self.cwd)
        self.selected = 0

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(40, min(cols - 6, 64))
        if self.state == "running":
            snap = self.job.snapshot()
            if snap["phase"] == "done":
                self.state = "done"
                self.done_result = snap["result"]
            elif snap["phase"] == "scan":
                plain = ["Scanning folder & reading tags…", ""]
                color = list(plain)
                box, _ = build_box(plain, color, maxw_override=inner_w,
                                   title="Import music", title2="[esc] cancel")
                return box
            else:
                plain, color = build_progress_lines(
                    snap["idx"], snap["total"], snap["current"], inner_w)
                box, _ = build_box(plain, color, maxw_override=inner_w,
                                   title="Import music", title2="")
                return box
        if self.state == "done":
            plain, color = build_done_lines(self.done_result, inner_w)
            box, _ = build_box(plain, color, maxw_override=inner_w,
                               title="Import complete", title2="")
            return box
        # browse
        list_rows = max(5, min(18, rows - 8))
        plain, color = build_browse_lines(self.cwd, self.entries, self.selected,
                                          inner_w, list_rows)
        box, _ = build_box(
            plain, color, maxw_override=inner_w, title="Import music",
            title2="[↑↓] move  [enter] open / import  [bksp] up  [esc] close",
        )
        return box

    def handle(self, ch: str) -> bool:
        if self.state == "running":
            if ch == "ESC" and self.job:
                self.job.cancel()
            return False
        if self.state == "done":
            if ch in ("\r", "\n"):
                r = self.done_result
                self.result = r.dest_dir if (r and r.imported) else None
                return True
            if ch == "ESC":
                return True
            return False
        # browse
        n = len(self.entries)
        if ch == "ESC":
            return True
        if ch in ("UP", "k") and n:
            self.selected = (self.selected - 1) % n
        elif ch in ("DOWN", "j") and n:
            self.selected = (self.selected + 1) % n
        elif ch in ("\x7f", "\b", "BACKSPACE"):
            parent = os.path.dirname(self.cwd.rstrip(os.sep)) or os.sep
            if parent != self.cwd:
                self.cwd = parent
                self._reload()
        elif ch in ("\r", "\n") and n:
            e = self.entries[self.selected]
            if e.kind in ("dir", "up"):
                self.cwd = e.path
                self._reload()
            elif e.kind == "import":
                self.job = BackgroundImport(sources=[self.cwd], dest_dir=LIBRARY_DIR).start()
                self.state = "running"
        return False


class ExtractAcOverlay:
    """Wizard to extract authentic AC GameCube hourly music from the user's disc
    via the ACGC PC port (headless render → seamless loop → catalog). Live
    overlay; states detect→confirm→running→done. ``result`` is the number of
    tracks extracted on success, else ``None``."""

    kind = "extract_ac"

    def __init__(self):
        self.port = find_port()
        self.disc = find_disc(self.port)
        self.state = "confirm" if (self.port and self.disc) else "guide"
        self.job = None
        self.summary = None
        self.result = None

    def _recheck(self):
        self.port = find_port()
        self.disc = find_disc(self.port)
        if self.port and self.disc:
            self.state = "confirm"

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(46, min(cols - 6, 72))
        if self.state == "running":
            snap = self.job.snapshot()
            if snap["result"] is not None:
                self.state = "done"
                self.summary = snap["result"]
            else:
                cur = snap["cur"]
                plain, color = build_progress_lines(
                    snap["idx"], snap["total"],
                    f"rendering hour {cur:02d} (loop-detecting…)" if cur >= 0 else "starting…",
                    inner_w)
                box, _ = build_box(plain, color, maxw_override=inner_w,
                                   title="Extracting AC music", title2="")
                return box
        if self.state == "guide":
            rom_dir = (os.path.join(os.path.dirname(self.port), "rom")
                       if self.port else "<the port folder>/rom/")
            ok_port = "✓" if self.port else " "
            ok_disc = "✓" if self.disc else " "
            plain = [
                "Pull the real hourly music off YOUR own Animal Crossing disc.",
                "Two one-time pieces are needed (personal use — nothing is bundled):",
                "",
                f"  [{ok_port}] 1. The AC PC port  (renders the game's real audio)",
            ]
            if self.port:
                plain.append("         found: …" + self.port[-44:])
            else:
                plain += [
                    "         • Easiest: grab a pre-built release and unzip it —",
                    "             github.com/flyngmt/ACGC-PC-Port  →  Releases",
                    "         • Then set:  export AC_UI_ACGC_PORT=/path/to/AnimalCrossing",
                ]
            plain += ["", f"  [{ok_disc}] 2. Your Animal Crossing disc image (.iso)"]
            if self.disc:
                plain.append("         found: " + os.path.basename(self.disc))
            else:
                plain += [
                    "         • Dump your OWN GameCube disc to an .iso, then either:",
                    f"             put it in  {rom_dir}",
                    "             or set     export AC_UI_ACGC_ISO=/path/to/disc.iso",
                ]
            plain += [""]
            if self.port and self.disc:
                plain.append("All set — press [enter] to extract all 24 hours!")
            else:
                plain.append("Set the missing piece(s) above, then press [r] to re-check.")
            plain.append("[r] re-check    [esc] close")
            title, t2 = "Extract AC music — setup", ""
        elif self.state == "done":
            r = self.summary
            plain = [f"Done — {r.done} hourly track(s) extracted into the catalog."]
            if r.failed:
                plain.append(f"  {r.failed} failed:")
                for e in r.errors[:4]:
                    plain.append("   • " + e[: inner_w - 5])
            plain += ["", "They play at their matching hour (game tag: ACGC).", "", "[esc] close"]
            title, t2 = "Extraction complete", ""
        else:  # confirm
            plain = [
                "Render the authentic GameCube hourly music from YOUR disc,",
                "auto-loop each hour seamlessly, and add it to the catalog.",
                "",
                "  Port:  …" + self.port[-46:],
                "  Disc:  " + os.path.basename(self.disc),
                "  Output: HH-ACGC-hourly.mp3   (24 tracks, ~2 min total)",
                "",
                "[enter] extract all 24 hours     [esc] cancel",
            ]
            title, t2 = "Extract AC music", ""
        box, _ = build_box(plain, plain, maxw_override=inner_w, title=title, title2=t2)
        return box

    def handle(self, ch: str) -> bool:
        if self.state == "confirm":
            if ch in ("\r", "\n"):
                self.job = BackgroundExtract(self.port, self.disc).start()
                self.state = "running"
                return False
            if ch == "ESC":
                return True
            return False
        if self.state == "running":
            if ch == "ESC" and self.job:
                self.job.cancel()
            return False
        if self.state == "guide":
            if ch in ("r", "R"):
                self._recheck()
                return False
            if ch in ("\r", "\n") and self.port and self.disc:
                self.state = "confirm"
                return False
            if ch == "ESC":
                return True
            return False
        # done
        if ch in ("ESC", "\r", "\n"):
            if self.state == "done" and self.summary:
                self.result = self.summary.done
            return True
        return False


class MenuOverlay:
    """Popup menu. ``result`` is the chosen option value or ``None``."""

    kind = "menu"

    def __init__(self, title: str, options: list):
        self.title = title
        self.options = options
        self.selected = 0
        self.result = None

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(20, min(cols - 8, 56))
        plain, color = build_menu_lines(self.options, self.selected, inner_w)
        pos = f"  {format_position_label(self.selected, len(self.options))}" if self.options else "  0/0"
        box, _ = build_box(
            plain, color, maxw_override=inner_w,
            title=f"{self.title}{pos}", title2=_HINT_PICK,
        )
        return box

    def handle(self, ch: str) -> bool:
        opts = self.options
        if ch == "ESC":
            return True
        if ch in ("\r", "\n"):
            self.result = opts[self.selected][1]
            return True
        if ch in ("UP", "k"):
            self.selected = (self.selected - 1) % len(opts)
        elif ch in ("DOWN", "j"):
            self.selected = (self.selected + 1) % len(opts)
        elif ch.isdigit():
            idx = int(ch) - 1
            if 0 <= idx < len(opts):
                self.result = opts[idx][1]
                return True
        return False


class HelpOverlay:
    """Searchable help with a drill-in detail popup.

    The list shows short labels (so nothing truncates); ↑/↓ move the highlight,
    type to filter, and Enter opens a small popup — layered over the help panel —
    with the full plain-language explanation. Read-only; ``result`` is ``None``.
    """

    kind = "help"

    def __init__(self):
        self.base_groups = build_help_groups(build_palette_commands(skip_ids=()))
        self.query = ""
        self.selected = 0
        self.detail_open = False
        self.result = None
        self._flat: list = []

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(44, min(cols - 6, 76))
        body_rows = max(6, min(22, rows - 6))
        groups = filter_help_groups(self.base_groups, self.query)
        self._flat = [c for _t, members in groups for c in members]
        if self.selected >= len(self._flat):
            self.selected = max(0, len(self._flat) - 1)
        sel = self.selected if self._flat else -1
        plain, color, _total = build_help_lines(
            groups, self.query, 0, inner_w, body_rows + 2, selected=sel,
        )
        pos = f"  {format_position_label(self.selected, len(self._flat))}" if self._flat else "  0/0"
        title2 = "[type] search  [enter] details  [esc] close"
        box, _ = build_box(
            plain, color, maxw_override=inner_w,
            title=f"Help — keys & commands{pos}", title2=title2,
        )
        # Drill-in: layer the detail popup over the help panel itself.
        if self.detail_open and self._flat:
            w = visible_len(box[0]) if box else inner_w
            detail = build_help_detail_box(self._flat[self.selected], w)
            box = composite_over(box, detail, w, len(box))
        return box

    def handle(self, ch: str) -> bool:
        # While the detail popup is open, any dismiss key closes just that layer.
        if self.detail_open:
            if ch in ("ESC", "\r", "\n", "q", "Q", " "):
                self.detail_open = False
            return False
        if ch in ("ESC", "?"):
            return True
        n = len(self._flat)
        if ch in ("\r", "\n"):
            if n:
                self.detail_open = True
        elif ch == "UP":
            self.selected = (self.selected - 1) % n if n else 0
        elif ch == "DOWN":
            self.selected = (self.selected + 1) % n if n else 0
        elif ch == "PAGEUP":
            self.selected = max(0, self.selected - 8)
        elif ch == "PAGEDOWN":
            self.selected = min(max(0, n - 1), self.selected + 8)
        elif ch in ("\x7f", "\b", "BACKSPACE"):
            self.query = self.query[:-1]
            self.selected = 0
        elif len(ch) == 1 and ch.isprintable():
            self.query += ch
            self.selected = 0
        return False


class ViewerOverlay:
    """Full-width scrollable viewer for pre-rendered content. ``result`` is ``None``."""

    kind = "viewer"

    def __init__(self, title: str, plain: list[str], color: list[str] | None):
        self.title = title
        self.plain = plain
        self.color = color or list(plain)
        self.scroll = 0
        self.result = None
        self._max_scroll = 0
        self._body_rows = 4

    def build(self, cols: int, rows: int) -> list[str]:
        inner_w = max(20, cols - 6)
        self._body_rows = max(4, rows - 6)
        wp, wc, self.scroll = build_viewer_frame(self.plain, self.color, self.scroll, self._body_rows)
        self._max_scroll = max(0, len(self.plain) - self._body_rows)
        pos = "" if self._max_scroll == 0 else (
            f"  ({self.scroll + 1}-{min(len(self.plain), self.scroll + self._body_rows)}/{len(self.plain)})"
        )
        box, _ = build_box(
            wp, wc, maxw_override=inner_w,
            title=f"{self.title}{pos}", title2="[↑↓ scroll]  [esc/z] close",
        )
        return box

    def handle(self, ch: str) -> bool:
        if ch in ("ESC", "z", "Z", "q"):
            return True
        ms, br = self._max_scroll, self._body_rows
        if ch == "UP":
            self.scroll = max(0, self.scroll - 1)
        elif ch == "DOWN":
            self.scroll = min(ms, self.scroll + 1)
        elif ch == "PAGEUP":
            self.scroll = max(0, self.scroll - br)
        elif ch == "PAGEDOWN":
            self.scroll = min(ms, self.scroll + br)
        return False

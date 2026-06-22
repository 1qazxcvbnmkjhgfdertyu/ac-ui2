"""Model + rendering + background runner for the in-app music import wizard.

Kept separate from the thin ``ImportOverlay`` (overlay.py) so the browsing/
threading logic is testable without a terminal. The overlay just maps keys onto
this model and renders the current phase.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from ac_ui import importer
from ac_ui.layout import render_selectable_row


def default_start_dir() -> str:
    for cand in ("~/Music", "~/music", "~"):
        p = os.path.expanduser(cand)
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~")


def _immediate_audio_count(path: str) -> int:
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_file() and importer.is_audio_file(e.name):
                    n += 1
    except OSError:
        pass
    return n


def count_audio_recursive(path: str, cap: int = 8000) -> int:
    """Total audio files under ``path`` (capped so huge trees stay snappy)."""
    n = 0
    for _root, _dirs, files in os.walk(path):
        for f in files:
            if importer.is_audio_file(f):
                n += 1
                if n >= cap:
                    return n
    return n


@dataclass
class BrowseEntry:
    kind: str          # "import" | "up" | "dir"
    label: str
    path: str = ""
    count: int = 0


def browse_entries(cwd: str) -> list:
    """Build the navigable list for ``cwd``: an import action, a parent row, then
    sub-directories with their immediate audio counts."""
    entries: list = []
    total = count_audio_recursive(cwd)
    if total > 0:
        cap_note = "+" if total >= 8000 else ""
        entries.append(BrowseEntry("import", f"✓ Import this folder — {total}{cap_note} tracks", cwd, total))
    parent = os.path.dirname(cwd.rstrip(os.sep)) or os.sep
    if parent and parent != cwd:
        entries.append(BrowseEntry("up", "../", parent))
    try:
        subdirs = sorted(
            (e.name for e in os.scandir(cwd) if e.is_dir() and not e.name.startswith(".")),
            key=str.lower,
        )
    except OSError:
        subdirs = []
    for name in subdirs:
        p = os.path.join(cwd, name)
        entries.append(BrowseEntry("dir", name + "/", p, _immediate_audio_count(p)))
    return entries


def build_browse_lines(cwd, entries, selected, inner_w, list_rows):
    """(plain, color) for the browser: a path header + a scrolling entry list."""
    plain: list = []
    color: list = []
    # Header: current path (right-trimmed to fit).
    head = cwd
    if len(head) > inner_w:
        head = "…" + head[-(inner_w - 1):]
    plain.append(head)
    color.append(head)
    plain.append("─" * inner_w)
    color.append("─" * inner_w)

    n = len(entries)
    if n == 0:
        plain.append("(no audio here — go up, or into a folder)")
        color.append("(no audio here — go up, or into a folder)")
        return plain, color
    # scroll window
    top = 0
    if n > list_rows:
        top = max(0, min(selected - list_rows // 2, n - list_rows))
    for i in range(top, min(top + list_rows, n)):
        e = entries[i]
        right = (str(e.count) if e.count else "") if e.kind == "dir" else ""
        rp, rc = render_selectable_row(e.label, i == selected, inner_w, right=right or None,
                                       dim=i != selected)
        plain.append(rp)
        color.append(rc)
    return plain, color


def build_progress_lines(done, total, current, inner_w):
    plain: list = []
    color: list = []
    frac = (done / total) if total else 0.0
    barw = max(10, inner_w - 8)
    filled = int(barw * frac)
    bar = "█" * filled + "░" * (barw - filled)
    plain.append(f"Importing… {done}/{total}")
    color.append(f"Importing… {done}/{total}")
    plain.append(f"[{bar}] {int(frac * 100)}%")
    color.append(f"[{bar}] {int(frac * 100)}%")
    cur = current or ""
    if len(cur) > inner_w:
        cur = cur[: inner_w - 1] + "…"
    plain.append(cur)
    color.append(cur)
    plain.append("")
    plain.append("[esc] stop")
    color.append("")
    color.append("[esc] stop")
    return plain, color


def build_done_lines(result, inner_w):
    plain: list = []
    n_copy = result.imported - result.transcoded
    plain.append(f"Done — {result.imported} added to your library")
    if result.transcoded:
        plain.append(f"  ({n_copy} copied, {result.transcoded} converted to mp3)")
    if result.failed:
        plain.append(f"  {result.failed} failed:")
        for e in result.errors[:4]:
            plain.append("   • " + (e[: inner_w - 5]))
    plain.append("")
    plain.append("[enter] play my library now    [esc] close")
    return plain, list(plain)


class BackgroundImport:
    """Runs plan(optional) + execute on a daemon thread with a thread-safe
    progress snapshot. ``plan`` may be precomputed or built lazily from sources."""

    def __init__(self, plan=None, sources=None, dest_dir=None):
        self._plan = plan
        self._sources = sources
        self._dest = dest_dir
        self._lock = threading.Lock()
        self._idx = 0
        self._total = len(plan.items) if plan else 0
        self._current = ""
        self._phase = "scan"          # "scan" | "import" | "done"
        self._result = None
        self._cancel = False
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        try:
            plan = self._plan
            if plan is None:
                plan = importer.plan_import(self._sources, self._dest)
            with self._lock:
                self._plan = plan
                self._total = len(plan.items)
                self._phase = "import"

            def cb(done, total, item):
                with self._lock:
                    self._idx = done
                    self._current = item.label if item else self._current

            res = importer.execute_import(plan, progress_cb=cb,
                                          should_cancel=lambda: self._cancel)
        except Exception as exc:                       # never kill the UI thread
            res = importer.ImportResult(dest_dir=self._dest or "")
            res.failed = 1
            res.errors = [str(exc)]
        with self._lock:
            self._result = res
            self._phase = "done"

    def cancel(self):
        self._cancel = True

    def snapshot(self):
        with self._lock:
            return {
                "phase": self._phase,
                "idx": self._idx,
                "total": self._total,
                "current": self._current,
                "result": self._result,
                "duplicates": self._plan.duplicates if self._plan else 0,
            }

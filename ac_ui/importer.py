"""User music importer — bring arbitrary audio files into ac-ui's free-play
library.

Design (per product decisions):
  * Target = the free-play library (a flat folder, ``constants.LIBRARY_DIR``);
    no hour/game/variant tagging needed.
  * Files are COPIED in so the library is self-contained; formats the player can
    already play are kept as-is (lossless), others are transcoded to mp3 via
    ffmpeg ("transcode only when needed").
  * Names come from the file's tags (ffprobe) → "Artist - Title", sanitized.

The engine is split into a pure PLAN step (no writes — used to preview in the
wizard) and an EXECUTE step (does the copying/transcoding, reports progress and
honours cancellation), so it can run on a background thread.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from ac_ui import diagnostics
from ac_ui.constants import LIBRARY_DIR

# Everything we'll treat as importable audio (broad — discovery).
AUDIO_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".aac", ".wav",
    ".wave", ".aiff", ".aif", ".aifc", ".wma", ".alac", ".ape", ".wv", ".mka",
    ".mid", ".midi", ".mp4", ".webm", ".mpc", ".tta", ".dsf",
}
# Formats the player (mpv via free-play) plays directly — keep these as-is.
# Mirrors tracks._FREEPLAY_EXTENSIONS; transcode anything NOT in here.
PLAYABLE_EXTS = {".midi", ".mid", ".mp3", ".flac", ".ogg", ".wav", ".opus", ".aac", ".m4a"}

_BAD_NAME_CHARS = set('/\\:*?"<>|\0\n\r\t')


def _tool(env_var: str, default: str) -> str | None:
    """Resolve an external tool (honours an env override), or None if absent."""
    cand = os.environ.get(env_var, default)
    return shutil.which(cand) or (cand if os.path.isabs(cand) and os.path.exists(cand) else None)


def ffprobe_bin() -> str | None:
    return _tool("AC_UI_FFPROBE", "ffprobe")


def ffmpeg_bin() -> str | None:
    return _tool("AC_UI_FFMPEG", "ffmpeg")


def is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def find_audio_files(paths) -> list[str]:
    """Collect audio files from a mix of files, directories (recursive), and
    globs. De-duplicated, sorted, absolute paths."""
    import glob

    found: list[str] = []
    seen: set[str] = set()

    def add(p: str):
        ap = os.path.abspath(p)
        if ap not in seen and is_audio_file(ap) and os.path.isfile(ap):
            seen.add(ap)
            found.append(ap)

    for raw in paths:
        p = os.path.expanduser(str(raw))
        if os.path.isfile(p):
            add(p)
        elif os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    add(os.path.join(root, f))
        else:
            for g in glob.glob(p, recursive=True):
                if os.path.isdir(g):
                    for root, _dirs, files in os.walk(g):
                        for f in sorted(files):
                            add(os.path.join(root, f))
                else:
                    add(g)
    return found


def read_tags(path: str) -> dict:
    """Best-effort tag read via ffprobe. Returns {artist,title,album,track}
    (empty strings when unavailable). Never raises."""
    fp = ffprobe_bin()
    if not fp:
        return {}
    try:
        out = subprocess.run(
            [fp, "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        diagnostics.warn("import", f"ffprobe failed for {os.path.basename(path)}", exc=exc)
        return {}
    tags = (data.get("format") or {}).get("tags") or {}
    low = {str(k).lower(): str(v) for k, v in tags.items()}
    return {
        "artist": (low.get("artist") or low.get("album_artist") or low.get("performer") or "").strip(),
        "title": (low.get("title") or "").strip(),
        "album": (low.get("album") or "").strip(),
        "track": (low.get("track") or "").strip(),
    }


def sanitize_name(s: str) -> str:
    """Turn a label into a safe, readable filename stem (no extension)."""
    out = "".join((" " if ch in _BAD_NAME_CHARS else ch) for ch in s)
    out = " ".join(out.split())          # collapse whitespace
    out = out.strip(" .")                # no leading/trailing dots/spaces
    if len(out) > 120:
        out = out[:120].rstrip()
    return out or "track"


def display_name(tags: dict, src_path: str) -> str:
    """'Artist - Title' from tags, falling back to the file stem."""
    artist = (tags.get("artist") or "").strip()
    title = (tags.get("title") or "").strip()
    if artist and title:
        base = f"{artist} - {title}"
    elif title:
        base = title
    else:
        base = os.path.splitext(os.path.basename(src_path))[0]
    return sanitize_name(base)


@dataclass
class ImportItem:
    src: str
    label: str            # display name (stem, no ext)
    dest_name: str        # final filename incl. extension
    action: str           # "copy" | "transcode"
    src_ext: str

    @property
    def dest_ext(self) -> str:
        return ".mp3" if self.action == "transcode" else self.src_ext


@dataclass
class ImportPlan:
    items: list = field(default_factory=list)        # list[ImportItem]
    dest_dir: str = ""
    duplicates: int = 0                                # already in library, skipped
    total_found: int = 0


def _existing_keys(dest_dir: str) -> set:
    """(lowercased name, size) for files already in the library — dedup key."""
    keys = set()
    try:
        for n in os.listdir(dest_dir):
            fp = os.path.join(dest_dir, n)
            if os.path.isfile(fp):
                try:
                    keys.add((n.lower(), os.path.getsize(fp)))
                    keys.add((n.lower(), -1))   # also dedup by name alone
                except OSError:
                    pass
    except OSError:
        pass
    return keys


def plan_import(sources, dest_dir: str | None = None, read_tags_fn=read_tags) -> ImportPlan:
    """Pure planning: resolve sources → ImportItems, choosing copy vs transcode,
    de-duplicating against the library and within the batch. No files written.

    ``read_tags_fn`` is injectable for tests."""
    dest_dir = dest_dir or LIBRARY_DIR
    srcs = find_audio_files(sources)
    plan = ImportPlan(dest_dir=dest_dir, total_found=len(srcs))
    existing = _existing_keys(dest_dir)
    used: set = set()

    for src in srcs:
        ext = os.path.splitext(src)[1].lower()
        try:
            size = os.path.getsize(src)
        except OSError:
            size = -1
        tags = read_tags_fn(src)
        label = display_name(tags, src)
        action = "copy" if ext in PLAYABLE_EXTS else "transcode"
        out_ext = ".mp3" if action == "transcode" else ext

        # Skip if an identical-looking file is already in the library.
        if (f"{label}{out_ext}".lower(), size) in existing or \
           (f"{label}{out_ext}".lower(), -1) in existing:
            plan.duplicates += 1
            continue

        # Make the destination name unique within the batch.
        name = f"{label}{out_ext}"
        i = 2
        while name.lower() in used:
            name = f"{label} ({i}){out_ext}"
            i += 1
        used.add(name.lower())

        plan.items.append(ImportItem(src=src, label=label, dest_name=name,
                                     action=action, src_ext=ext))
    return plan


@dataclass
class ImportResult:
    imported: int = 0
    transcoded: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)        # list[str]
    dest_dir: str = ""


def _transcode(src: str, dest: str) -> None:
    fm = ffmpeg_bin()
    if not fm:
        raise RuntimeError("ffmpeg not found (needed to convert this format)")
    # -map_metadata 0 keeps tags; -vn drops cover art video streams; q:a 2 ~190kbps
    # VBR. -f mp3 forces the muxer because our temp file ends in ".part" (ffmpeg
    # would otherwise fail to infer the container from the extension).
    r = subprocess.run(
        [fm, "-v", "error", "-y", "-i", src, "-vn",
         "-codec:a", "libmp3lame", "-q:a", "2", "-map_metadata", "0", "-f", "mp3", dest],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ffmpeg failed").strip().splitlines()[-1][:200])


def execute_import(plan: ImportPlan, progress_cb=None, should_cancel=None) -> ImportResult:
    """Perform the planned copies/transcodes. ``progress_cb(done, total, item)``
    is called before each item; ``should_cancel()`` aborts between items."""
    res = ImportResult(dest_dir=plan.dest_dir)
    os.makedirs(plan.dest_dir, exist_ok=True)
    total = len(plan.items)
    for i, item in enumerate(plan.items):
        if should_cancel and should_cancel():
            break
        if progress_cb:
            try:
                progress_cb(i, total, item)
            except Exception:
                pass
        dest = os.path.join(plan.dest_dir, item.dest_name)
        tmp = dest + ".part"
        try:
            if item.action == "transcode":
                _transcode(item.src, tmp)
                os.replace(tmp, dest)
                res.transcoded += 1
            else:
                shutil.copy2(item.src, tmp)
                os.replace(tmp, dest)
            res.imported += 1
        except Exception as exc:
            res.failed += 1
            res.errors.append(f"{os.path.basename(item.src)}: {exc}")
            diagnostics.warn("import", f"failed to import {item.src}", exc=exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    if progress_cb:
        try:
            progress_cb(total, total, None)
        except Exception:
            pass
    return res

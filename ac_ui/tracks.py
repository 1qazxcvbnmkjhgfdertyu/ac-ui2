import os, re, random, shutil, time, json
from dataclasses import dataclass, field

from ac_ui.constants import (
    MUSIC_DIR, FILENAME_RE, TRACK_LIST_CACHE, PIANO_EXTRA_TICKETS,
    TRACK_REPEAT_GUARD, QUEUE_SIZE,
)
from ac_ui.colors import c
from ac_ui import diagnostics

def parse_filename(name):
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return m.groupdict()


# ── Playlist data models ────────────────────────────────────────────────────────
#
# A "playlist definition" (PlaylistSource) is the logical set of entries with
# their weights — this is what gets saved to / loaded from disk.  The "runtime
# queue" (a flat list of absolute paths produced by build_free_play_queue) is a
# separate, shuffled, weight-expanded view used for playback.  Keeping the two
# apart is what lets weights survive an import → edit → save round-trip.

@dataclass
class PlaylistEntry:
    """One logical track in a playlist definition."""
    path: str
    weight: int = 1
    exists: bool = True

    def as_dict(self) -> dict:
        return {"file": self.path, "weight": int(self.weight), "exists": bool(self.exists)}


@dataclass
class PlaylistSource:
    """A loaded playlist definition plus any load-time diagnostics."""
    name: str
    entries: list = field(default_factory=list)   # list[PlaylistEntry]
    path: str = ""
    warnings: list = field(default_factory=list)   # list[str]
    missing: int = 0                               # entries whose file is gone

    @property
    def ok(self) -> bool:
        """True when the source loaded cleanly (parsed, with playable entries)."""
        return not self.warnings and any(e.exists for e in self.entries)

    def existing_entries(self) -> list:
        return [e for e in self.entries if e.exists]


@dataclass
class QueueCandidate:
    """An upcoming track for the Up Next panel.

    queue_index points back into the runtime queue (>= 0 for free play, -1 for
    timed mode where there is no persistent queue to reorder).  weight is the
    track's effective weight (how many times it appears in the runtime queue,
    1-5) so the panel can show a per-row weight meter.
    """
    path: str
    label: str
    queue_index: int = -1
    weight: int = 1


def track_label(path: str) -> str:
    """Human label for a track path: 'GAME: variant' when parseable, else stem."""
    base = os.path.basename(str(path))
    meta = parse_filename(base)
    if meta:
        return f"{meta['game']}: {meta['variant']}"
    return os.path.splitext(base)[0]

def invalidate_track_cache(hour=None):
    if hour is None:
        TRACK_LIST_CACHE.clear()
    else:
        TRACK_LIST_CACHE.pop(int(hour), None)

def _hour_track_dir(hour):
    return os.path.join(MUSIC_DIR, f"{int(hour):02d}")

def _scan_hour_tracks(hour):
    hour = int(hour)
    d = _hour_track_dir(hour)
    if not os.path.isdir(d):
        TRACK_LIST_CACHE.pop(hour, None)
        return ()
    try:
        st = os.stat(d)
    except OSError:
        TRACK_LIST_CACHE.pop(hour, None)
        return ()
    sig = (st.st_mtime_ns, st.st_size)
    cached = TRACK_LIST_CACHE.get(hour)
    if cached and cached["sig"] == sig:
        return cached["entries"]
    entries = []
    try:
        names = os.listdir(d)
    except OSError:
        TRACK_LIST_CACHE.pop(hour, None)
        return ()
    for name in names:
        lower = name.lower()
        if not (lower.endswith(".mp3") or lower.endswith(".flac")):
            continue
        meta = parse_filename(name)
        if meta is None:
            continue
        entries.append((name, meta, os.path.join(d, name)))
    entries.sort(key=lambda item: item[0])
    entries = tuple(entries)
    TRACK_LIST_CACHE[hour] = {"sig": sig, "entries": entries}
    return entries

def collect_catalog(allowed_games=None, allowed_variants=None):
    games = set()
    variants = set()
    if not os.path.isdir(MUSIC_DIR):
        return games, variants
    for hour in range(24):
        for _name, meta, _path in _scan_hour_tracks(hour):
            if not meta:
                continue
            if allowed_games and meta["game"] not in allowed_games:
                continue
            if allowed_variants and meta["variant"] not in allowed_variants:
                continue
            games.add(meta["game"])
            variants.add(meta["variant"])
    return games, variants

def list_all_tracks(allowed_games=None, allowed_variants=None):
    """Return every catalog track as (path, meta, name) across all 24 hours.

    Honours optional game/variant filters.  Used by the library fuzzy finder.
    """
    out = []
    for hour in range(24):
        for name, meta, path in _scan_hour_tracks(hour):
            if not meta:
                continue
            if allowed_games and meta["game"] not in allowed_games:
                continue
            if allowed_variants and meta["variant"] not in allowed_variants:
                continue
            out.append((path, meta, name))
    return out


def prompt_rename(msg):
    try:
        return input(msg).strip()
    except EOFError:
        return ""

def import_files(paths):
    if not paths:
        print("No files specified for import.")
        return 1
    errors = 0
    for src in paths:
        src = os.path.expanduser(src)
        if not os.path.isfile(src):
            print(f"Missing file: {src}")
            errors += 1
            continue
        name = os.path.basename(src)
        meta = parse_filename(name)
        while meta is None:
            new_name = prompt_rename(
                f"Invalid filename '{name}'. Enter new filename (HH-GAME-variant.ext) or blank to skip: "
            )
            if not new_name:
                print(f"Skipped: {name}")
                errors += 1
                break
            name = new_name
            meta = parse_filename(name)
        if meta is None:
            continue
        dest_dir = hh_folder(int(meta["hour"]))
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, name)
        while os.path.exists(dest_path):
            new_name = prompt_rename(
                f"File exists '{dest_path}'. Enter new filename to import or blank to skip: "
            )
            if not new_name:
                print(f"Skipped: {name}")
                errors += 1
                break
            meta = parse_filename(new_name)
            if not meta:
                print("Name does not match strict pattern HH-GAME-variant.ext")
                errors += 1
                continue
            dest_dir = hh_folder(int(meta["hour"]))
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, new_name)
        if os.path.exists(dest_path):
            continue
        try:
            shutil.copy2(src, dest_path)
            invalidate_track_cache(meta["hour"])
            print(f"Imported -> {dest_path}")
        except Exception as e:
            print(f"Failed to import {src}: {e}")
            errors += 1
    return 1 if errors else 0

def hh_folder(hour: int) -> str:
    return _hour_track_dir(hour)

def list_tracks_for_hour(hour: int, allowed_games=None, allowed_variants=None):
    tracks = []
    for _name, meta, path in _scan_hour_tracks(hour):
        if allowed_games and (not meta or meta["game"] not in allowed_games):
            continue
        if allowed_variants and (not meta or meta["variant"] not in allowed_variants):
            continue
        tracks.append(path)
    return tracks

def playback_mode_label(repeat_current):
    return "Repeat track" if repeat_current else "Hour shuffle"

def filter_recent_tracks(tracks, exclude=None, recent_tracks=None):
    candidates = list(tracks or [])
    if exclude:
        filtered = [track for track in candidates if track != exclude]
        if filtered:
            candidates = filtered
    if recent_tracks:
        recent_set = {track for track in recent_tracks if track}
        filtered = [track for track in candidates if track not in recent_set]
        if filtered:
            candidates = filtered
    return candidates

def pick_weighted(tracks, exclude=None, recent_tracks=None, banned=None):
    """Return (track_path, reason_str) or (None, reason_str)."""
    if not tracks:
        return None, "no candidates"
    if banned:
        available = [t for t in tracks
                     if os.path.basename(t) not in banned and t not in banned
                     and os.path.abspath(t) not in banned]
        if not available:
            available = tracks  # ignore ban list if it would leave nothing
            ban_note = " (ban ignored)"
        else:
            ban_note = ""
        tracks = available
    else:
        ban_note = ""
    had_exclusions = bool(exclude or recent_tracks)
    filtered = filter_recent_tracks(tracks, exclude=exclude, recent_tracks=recent_tracks)
    # fallback = exclusions existed but all tracks were still returned (couldn't narrow down)
    fallback = had_exclusions and (len(filtered) == len(tracks))
    n = len(filtered)
    pool = []
    for t in filtered:
        pool.append(t)
        if "piano" in os.path.basename(t).lower():
            for _ in range(PIANO_EXTRA_TICKETS):
                pool.append(t)
    choice = random.choice(pool)
    piano_chosen = "piano" in os.path.basename(choice).lower() and PIANO_EXTRA_TICKETS > 0
    if n == 1:
        reason = f"only match{ban_note}"
    elif fallback:
        reason = f"fallback ({n} tracks){ban_note}"
    elif piano_chosen:
        reason = f"piano boost ({n} pool){ban_note}"
    else:
        reason = f"random ({n} candidates){ban_note}"
    return choice, reason

def next_hour_epoch(now=None):
    if now is None:
        now = time.time()
    lt = time.localtime(now)
    # next top of hour
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 59, 59, lt.tm_wday, lt.tm_yday, lt.tm_isdst)) + 1

def fmt_mmss(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

VIS_GRADIENT_COLORS = (82, 118, 154, 190, 226, 220, 214, 208, 202, 196)

_FREEPLAY_EXTENSIONS = {".midi", ".mid", ".mp3", ".flac", ".ogg", ".wav", ".opus", ".aac", ".m4a"}

def load_playlist_source(path) -> PlaylistSource:
    """Canonical loader for a free-play source (directory, .m3u, or weighted .acpl).

    Returns a PlaylistSource carrying logical entries (with weights), plus any
    parse warnings and a count of missing files.  This is the single source of
    truth — scan_free_play_dir/load_acpl_full are thin views over it.
    """
    raw = str(path)
    path = os.path.expanduser(raw)
    default_name = os.path.splitext(os.path.basename(path))[0]
    src = PlaylistSource(name=default_name, path=path)

    if os.path.isfile(path):
        low = path.lower()
        if low.endswith(".acpl"):
            return _load_acpl_source(path, src)
        if low.endswith(".m3u"):
            return _load_m3u_source(path, src)
        src.warnings.append(f"unsupported playlist file: {os.path.basename(path)}")
        diagnostics.warn("playlist", src.warnings[-1])
        return src

    if not os.path.isdir(path):
        src.warnings.append(f"playlist not found: {raw}")
        diagnostics.warn("playlist", src.warnings[-1])
        return src

    try:
        names = sorted(os.listdir(path))
    except OSError as exc:
        src.warnings.append(f"cannot read directory: {os.path.basename(path)}")
        diagnostics.warn("playlist", src.warnings[-1], exc=exc)
        return src
    for name in names:
        if os.path.splitext(name)[1].lower() in _FREEPLAY_EXTENSIONS:
            fp = os.path.join(path, name)
            src.entries.append(PlaylistEntry(path=fp, weight=1, exists=os.path.isfile(fp)))
    return src


def _load_acpl_source(path, src: PlaylistSource) -> PlaylistSource:
    base = os.path.dirname(os.path.abspath(path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        src.warnings.append(f"malformed playlist '{os.path.basename(path)}'")
        diagnostics.error("playlist", src.warnings[-1], exc=exc)
        return src
    if not isinstance(data, dict):
        src.warnings.append(f"malformed playlist '{os.path.basename(path)}': not an object")
        diagnostics.error("playlist", src.warnings[-1])
        return src
    name = str(data.get("name", src.name)).strip()
    if name:
        src.name = name
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        src.warnings.append(f"malformed playlist '{os.path.basename(path)}': bad track list")
        diagnostics.error("playlist", src.warnings[-1])
        return src
    for raw in tracks:
        if not isinstance(raw, dict):
            continue
        fp = str(raw.get("file", ""))
        if not fp:
            continue
        try:
            w = max(1, min(5, int(raw.get("weight", 1))))
        except (TypeError, ValueError):
            w = 1
        if not os.path.isabs(fp):
            fp = os.path.join(base, fp)
        fp = os.path.normpath(fp)
        exists = os.path.isfile(fp)
        if not exists:
            src.missing += 1
        src.entries.append(PlaylistEntry(path=fp, weight=w, exists=exists))
    if src.missing:
        diagnostics.warn("playlist", f"{src.missing} missing file(s) in '{src.name}'")
    return src


def _load_m3u_source(path, src: PlaylistSource) -> PlaylistSource:
    base = os.path.dirname(os.path.abspath(path))
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    if line.startswith("#PLAYLIST:"):
                        nm = line[len("#PLAYLIST:"):].strip()
                        if nm:
                            src.name = nm
                    continue
                fp = line if os.path.isabs(line) else os.path.join(base, line)
                fp = os.path.normpath(fp)
                exists = os.path.isfile(fp)
                if not exists:
                    src.missing += 1
                src.entries.append(PlaylistEntry(path=fp, weight=1, exists=exists))
    except OSError as exc:
        src.warnings.append(f"cannot read playlist '{os.path.basename(path)}'")
        diagnostics.warn("playlist", src.warnings[-1], exc=exc)
    return src


def build_free_play_queue(entries, rng=None, repeat_guard=0):
    """Build a shuffled, weight-expanded runtime queue from logical entries.

    entries: iterable of PlaylistEntry (or dicts with 'file'/'weight'/'exists').
    Each existing track is repeated <weight> times, the pool is shuffled, and a
    spacing pass pushes identical paths at least `repeat_guard` slots apart when
    the pool allows it.  Returns a flat list of absolute paths.
    """
    rng = rng or random
    pool = []
    for e in entries:
        if isinstance(e, dict):
            path = str(e.get("file", ""))
            weight = max(1, int(e.get("weight", 1)))
            exists = e.get("exists", os.path.isfile(path))
        else:
            path, weight, exists = e.path, max(1, int(e.weight)), e.exists
        if not path or not exists:
            continue
        pool.extend([path] * weight)
    rng.shuffle(pool)
    if repeat_guard <= 0 or len(set(pool)) <= 1:
        return pool
    return _space_repeats(pool, repeat_guard)


def _space_repeats(pool, guard):
    """Greedily reorder so the same path is not placed within `guard` of itself."""
    remaining = list(pool)
    result = []
    while remaining:
        placed = False
        recent = result[-guard:]
        for i, item in enumerate(remaining):
            if item not in recent:
                result.append(remaining.pop(i))
                placed = True
                break
        if not placed:
            # Can't satisfy the guard with what's left — accept the next item.
            result.append(remaining.pop(0))
    return result


def move_queue_item_to_next(queue, fp_idx, queue_index):
    """Move queue[queue_index] so it becomes the next track played (position fp_idx).

    Mutates `queue` in place and returns the (possibly adjusted) fp_idx pointing
    at the moved item.  This is what 'Enter' on the Up Next panel uses, so it
    reorders the real runtime queue rather than just a rendered preview.
    """
    n = len(queue)
    if not (0 <= queue_index < n):
        return fp_idx
    item = queue.pop(queue_index)
    if queue_index < fp_idx:
        fp_idx -= 1   # removed an earlier slot; keep the pointer aligned
    insert_at = max(0, min(fp_idx, len(queue)))
    queue.insert(insert_at, item)
    return insert_at


def aggregate_queue_to_entries(paths):
    """Collapse an ordered path list into PlaylistEntry objects.

    Weight = number of occurrences (capped at 5), first-seen order preserved.
    This is the inverse of build_free_play_queue and lets a saved queue keep
    the weights that produced it instead of flattening everything to weight 1.
    """
    order = []
    counts = {}
    for p in paths:
        ap = os.path.normpath(os.path.abspath(os.path.expanduser(str(p))))
        if ap not in counts:
            counts[ap] = 0
            order.append(ap)
        counts[ap] += 1
    return [PlaylistEntry(path=p, weight=min(5, counts[p]), exists=os.path.isfile(p)) for p in order]


def scan_free_play_dir(path):
    """Backward-compatible flat list of existing playable paths (weights expanded)."""
    src = load_playlist_source(path)
    pool = []
    for e in src.entries:
        if e.exists:
            pool.extend([e.path] * max(1, e.weight))
    return pool


def free_play_source_name(path):
    """Return a human-readable display name for a free play source."""
    return load_playlist_source(path).name


# ── Playlist CRUD ──────────────────────────────────────────────────────────────

def load_acpl_full(acpl_path: str):
    """Load .acpl for editing. Returns (name, entries).
    Each entry: {'file': abs_path, 'weight': int, 'exists': bool}."""
    src = load_playlist_source(acpl_path)
    return src.name, [e.as_dict() for e in src.entries]


def save_acpl(acpl_path: str, name: str, entries: list) -> bool:
    """Write an .acpl file. Entries: PlaylistEntry objects or {'file','weight'} dicts."""
    path = os.path.expanduser(str(acpl_path))
    base = os.path.dirname(os.path.abspath(path))
    track_list = []
    for e in entries:
        if isinstance(e, PlaylistEntry):
            fp, w = str(e.path), max(1, min(5, int(e.weight)))
        else:
            fp = str(e.get("file", ""))
            w  = max(1, min(5, int(e.get("weight", 1))))
        try:
            rel = os.path.relpath(fp, base)
            if not rel.startswith(".."):
                fp = rel
        except ValueError:
            pass
        track_list.append({"file": fp, "weight": w})
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": name.strip(), "tracks": track_list}, f, indent=2, ensure_ascii=False)
        return True
    except OSError as exc:
        diagnostics.error("playlist", f"failed to save '{os.path.basename(path)}'", exc=exc)
        return False


def save_queue_acpl(acpl_path: str, name: str, queue_paths: list, start_idx: int = 0) -> bool:
    """Save a runtime queue as an .acpl, aggregating duplicate paths into weights.

    Only the upcoming portion (queue_paths[start_idx:]) is saved, so saving from
    the queue manager / picker preserves both weights and the current position.
    """
    upcoming = list(queue_paths)[max(0, start_idx):]
    return save_acpl(acpl_path, name, aggregate_queue_to_entries(upcoming))


def _unique_acpl_path(name: str, dest_dir: str) -> str:
    """Return a non-colliding .acpl path inside dest_dir."""
    safe = re.sub(r'[^\w\s-]', '', name).strip().replace(" ", "_") or "playlist"
    path = os.path.join(dest_dir, safe + ".acpl")
    if os.path.exists(path):
        base, ext = os.path.splitext(path)
        i = 2
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        path = f"{base}_{i}{ext}"
    return path


def create_empty_acpl(name: str, dest_dir=None) -> "str | None":
    """Create a new empty .acpl. Returns path or None on failure."""
    from ac_ui.audio_config import PLAYLISTS_DIR
    dest = os.path.expanduser(str(dest_dir)) if dest_dir else PLAYLISTS_DIR
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError:
        return None
    path = _unique_acpl_path(name, dest)
    return path if save_acpl(path, name, []) else None


def duplicate_acpl(src_path: str, new_name: str) -> "str | None":
    """Copy .acpl to a new name in the same directory. Returns new path or None."""
    src  = os.path.expanduser(str(src_path))
    base_dir = os.path.dirname(src)
    _, entries = load_acpl_full(src)
    try:
        os.makedirs(base_dir, exist_ok=True)
    except OSError:
        return None
    dest = _unique_acpl_path(new_name, base_dir)
    return dest if save_acpl(dest, new_name, entries) else None


def add_track_to_acpl(acpl_path: str, track_path: str, weight: int = 1) -> bool:
    """Append track_path to an .acpl (no-op if already present). Returns True on success."""
    acpl = os.path.expanduser(str(acpl_path))
    track_abs = os.path.abspath(os.path.expanduser(str(track_path)))
    name, entries = load_acpl_full(acpl)
    for e in entries:
        if os.path.abspath(e["file"]) == track_abs:
            return True  # already present
    entries.append({"file": track_abs, "weight": max(1, min(5, weight)), "exists": os.path.isfile(track_abs)})
    return save_acpl(acpl, name, entries)


def active_games_from_index(game_idx, games_list, base_allowed_games):
    if game_idx == 0:
        return set(base_allowed_games) if base_allowed_games else None
    return {games_list[game_idx]}


def game_label_from_index(game_idx, games_list, base_allowed_games):
    if game_idx != 0:
        return games_list[game_idx]
    if not base_allowed_games:
        return "ALL"
    labels = sorted(base_allowed_games)
    joined = ",".join(labels)
    if len(joined) <= 18:
        return joined
    if len(labels) == 1:
        return labels[0]
    return f"{len(labels)} games"


def update_history(track_path, history, recent_track_paths):
    """Record a played track, storing the full absolute path for exact replay.

    Display names are derived from the basename at render time, so duplicate
    filenames in different folders (and tracks outside MUSIC_DIR) stay distinct.
    """
    if not track_path:
        return
    if recent_track_paths is not None:
        recent_track_paths.append(track_path)
    if history and history[-1] == track_path:
        return
    history.append(track_path)


def _track_banned(track, banned_tracks):
    """A track is banned if its absolute path or its basename is in the set."""
    if not banned_tracks:
        return False
    return track in banned_tracks or os.path.basename(track) in banned_tracks


def compute_next_candidates(
    hour, active_games, active_variants,
    current_track, recent_track_paths, banned_tracks, count=QUEUE_SIZE,
):
    """Upcoming timed-mode tracks as QueueCandidate objects (queue_index = -1)."""
    tracks = list_tracks_for_hour(hour, active_games, active_variants)
    tracks = filter_recent_tracks(tracks, exclude=current_track, recent_tracks=recent_track_paths)
    if banned_tracks:
        tracks = [t for t in tracks if not _track_banned(t, banned_tracks)]
    if not tracks:
        return []
    tracks_sorted = sorted(tracks, key=lambda t: os.path.basename(t).lower())
    return [QueueCandidate(path=t, label=track_label(t), queue_index=-1)
            for t in tracks_sorted[:max(1, count)]]


def free_play_next_candidates(fp_playlist, fp_idx, queue_size):
    """Return upcoming free-play tracks as QueueCandidate objects.

    Each candidate carries its queue_index back into fp_playlist so the Up Next
    panel can reorder the real runtime queue (not just a rendered preview).
    """
    if not fp_playlist:
        return []
    _n = len(fp_playlist)
    counts = {}
    for p in fp_playlist:
        counts[p] = counts.get(p, 0) + 1
    out = []
    for i in range(min(queue_size, _n)):
        qi = (fp_idx + i) % _n
        path = fp_playlist[qi]
        out.append(QueueCandidate(
            path=path, label=track_label(path), queue_index=qi,
            weight=min(5, counts.get(path, 1)),
        ))
    return out

import os, re, random, shutil, time

from ac_ui.constants import (
    MUSIC_DIR, FILENAME_RE, TRACK_LIST_CACHE, PIANO_EXTRA_TICKETS,
    TRACK_REPEAT_GUARD,
)
from ac_ui.colors import c

def parse_filename(name):
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return m.groupdict()

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
        available = [t for t in tracks if os.path.basename(t) not in banned and t not in banned]
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


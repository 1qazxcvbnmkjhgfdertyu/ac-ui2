"""Entry-point scaffolding: CLI argument parsing and run-mode dispatch.

This module is the future home of the top-level application logic that
currently lives in ui.py. Migration is incremental; see Step 8 notes.
"""
from __future__ import annotations

import os
import sys


def apply_cli_runtime_env(argv: list[str]) -> list[str]:
    """Apply terminal/runtime overrides before importing UI modules.

    These flags need to affect module-import-time globals in `colors.py`, so the
    launcher script calls this before importing `ac_ui.ui`.
    """
    if not argv:
        return []
    cleaned = [argv[0]]
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--ascii-only":
            os.environ["AC_UI_ASCII_ONLY"] = "1"
            i += 1
            continue
        elif arg in ("--low-power", "--potato"):
            os.environ["AC_UI_LOW_POWER"] = "1"
            i += 1
            continue
        elif arg == "--tty":
            os.environ["AC_UI_TTY"] = "1"
            i += 1
            continue
        elif arg == "--unicode":
            os.environ["AC_UI_ASCII_ONLY"] = "0"
            i += 1
            continue
        elif arg in ("--true-color", "--true-colour"):
            os.environ["AC_UI_COLOR_MODE"] = "truecolor"
            i += 1
            continue
        elif arg in ("--256-color", "--256-colour"):
            os.environ["AC_UI_COLOR_MODE"] = "256"
            i += 1
            continue
        elif arg in ("--16-color", "--16-colour"):
            os.environ["AC_UI_COLOR_MODE"] = "16"
            i += 1
            continue
        elif arg in ("--no-color", "--no-colour"):
            os.environ["AC_UI_COLOR_MODE"] = "none"
            i += 1
            continue
        elif arg == "--bars":
            if i + 1 < len(argv):
                os.environ["AC_UI_CAVA_BARS"] = argv[i + 1]
                i += 2
                continue
        elif arg.startswith("--bars="):
            os.environ["AC_UI_CAVA_BARS"] = arg.split("=", 1)[1]
            i += 1
            continue
        cleaned.append(arg)
        i += 1
    return cleaned


def config_set_cli(argv: list[str]) -> bool:
    """Handle scriptable ``--set-theme <name>`` / ``--set-layout <preset>`` flags.

    Updates the persisted UI state and returns True if either flag was present
    (so the launcher can exit without starting the UI).  Section 6.
    """
    theme = layout = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--set-theme" and i + 1 < len(argv):
            theme = argv[i + 1]
            i += 2
            continue
        if a.startswith("--set-theme="):
            theme = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--set-layout" and i + 1 < len(argv):
            layout = argv[i + 1]
            i += 2
            continue
        if a.startswith("--set-layout="):
            layout = a.split("=", 1)[1]
            i += 1
            continue
        i += 1
    if theme is None and layout is None:
        return False

    from ac_ui.colors import THEME_NAMES
    from ac_ui.constants import LAYOUT_PRESETS
    from ac_ui.persist import load_ui_state, save_ui_state

    state = load_ui_state()
    if theme is not None:
        if theme not in THEME_NAMES:
            print(f"Unknown theme '{theme}'. Available: {', '.join(THEME_NAMES)}")
        else:
            state["theme"] = theme
            print(f"Theme set to '{theme}'.")
    if layout is not None:
        if layout not in LAYOUT_PRESETS:
            print(f"Unknown layout '{layout}'. Available: {', '.join(LAYOUT_PRESETS)}")
        else:
            lay = state.get("layout")
            if not isinstance(lay, dict):
                lay = {}
            lay["preset"] = layout
            state["layout"] = lay
            print(f"Layout set to '{layout}'.")
    save_ui_state(state)
    return True


def main_cli(argv: list[str] | None = None) -> int:
    """Top-level console entry point for repo, pip, and ``python -m ac_ui`` runs."""
    if argv is None:
        argv = sys.argv
    cleaned = apply_cli_runtime_env(list(argv))
    if cleaned:
        cleaned[0] = "ac-ui"
    sys.argv = cleaned
    if config_set_cli(cleaned):
        return 0
    if len(cleaned) >= 2 and cleaned[1] == "doctor":
        from ac_ui.install import doctor_cli
        return doctor_cli(cleaned[2:])
    from ac_ui.ui import main as ui_main
    ui_main()
    return 0


def parse_cli_args(argv: list[str]) -> tuple:
    """Parse sys.argv and return (mode, games, vis_mode, import_paths, tune_action, layout_opts)."""
    from ac_ui.constants import VIS_MODE, VIS_MODES, normalize_vis_mode

    mode = "run"
    games = None
    vis_mode = None
    import_paths: list[str] = []
    tune_action = None
    layout_opts = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print("Usage:")
            print("  ac-ui [--games GCN,WW] [--vis MODE] [--bars N] [--true-color] [--ascii-only]")
            print("  ac-ui doctor [--json] [--install-commands] [--with-optional]")
            print("  ac-ui import <files...>")
            print("  ac-ui tune [show|play|reset]")
            print("  ac-ui stats")
            print("  ac-ui layout-sweep")
            print("  ac-ui build-cache [playlist_path...]")
            print()
            print("Keys (in-app):")
            print("  n  next track    m/space  mute   T  town tune   E  EQ editor")
            print("  g  cycle game    v  variant   t  vis next   R  vis random   y  vis shuffle")
            print("  h  simulate hour change       s  audio sink   l  repeat current track")
            print("  L  cycle layout preset (two_rail / stacked / wide_graph / fullscreen)")
            print("  +/-  volume +/-5   PgUp/Dn volume +/-10")
            print("  /  find & play any track     :  or ^P command palette")
            print("  1/2 focus history/up-next    0 unfocus  x actions  z zoom")
            print("  8  background mode   ?  help   q  quit")
            print()
            print(f"Vis modes: {', '.join(VIS_MODES)}")
            print()
            print("Config (scriptable, write saved state then exit):")
            print("  ac-ui --set-theme <name>     ac-ui --set-layout <preset>")
            print()
            print("Customisation:")
            print("  keymap:  $AC_UI_KEYMAP or ~/.config/ac-ui/keymap.json")
            print("  plugins: $AC_UI_PLUGINS or ~/.config/ac-ui/plugins/*.py")
            print("  AC_UI_TTY=1  accessible/plain mode (no color, no box-drawing, no motion)")
            print("  fps: AC_UI_REFRESH pins one rate; else it adapts per vis mode via")
            print("       AC_UI_VIS_FPS_FAST (60) / _NORMAL (30) / _HEAVY (30)")
            print()
            print("Display flags:")
            print("  --true-color   force 24-bit ANSI output")
            print("  --256-color    force 256-color ANSI output")
            print("  --16-color     force 16-color ANSI output")
            print("  --ascii-only   avoid Braille/box-drawing visual output")
            print("  --low-power    weak machine: no animations, lower fps (a.k.a. --potato)")
            print("  --tty          plainest mode: no colour, no box-drawing, no motion")
            print("  --bars N       request a fixed CAVA spectrum bar count")
            print()
            print("Env vars: AC_UI_MUSIC_DIR, AC_UI_MPV, AC_UI_VIS, AC_UI_REFRESH,")
            print("          AC_UI_CAVA_SOURCE, AC_UI_CAVA_BARS, AC_UI_PCM, AC_UI_EQ_PATH, AC_UI_STATS,")
            print("          AC_UI_VIS_ATTACK_MS, AC_UI_VIS_DECAY_MS,")
            print("          AC_UI_LOOPBACK_LATENCY_MSEC, AC_UI_REPEAT_GUARD,")
            print("          AC_UI_LAYOUT_PRESET, AC_UI_COLOR_MODE, AC_UI_ASCII_ONLY")
            sys.exit(0)
        if arg in (
            "--ascii-only", "--unicode",
            "--true-color", "--true-colour",
            "--256-color", "--256-colour",
            "--16-color", "--16-colour",
            "--no-color", "--no-colour",
            "--low-power", "--potato", "--tty",
            "--bars",
        ):
            i += 2 if arg == "--bars" and i + 1 < len(argv) else 1
            continue
        if arg.startswith("--bars="):
            i += 1
            continue
        if arg == "build-cache":
            mode = "build-cache"
            import_paths = argv[i + 1:]
            break
        if arg == "import":
            mode = "import"
            import_paths = argv[i + 1:]
            break
        if arg == "extract-ac":
            mode = "extract-ac"
            import_paths = argv[i + 1:]
            break
        if arg == "tune":
            mode = "tune"
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                tune_action = argv[i + 1]
            break
        if arg == "stats":
            mode = "stats"
            break
        if arg == "layout-sweep":
            mode = "layout-sweep"
            layout_opts = {}
            i += 1
            while i < len(argv):
                if argv[i].startswith("--"):
                    key = argv[i][2:].replace("-", "_")
                    if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                        layout_opts[key] = argv[i + 1]
                        i += 1
                    else:
                        layout_opts[key] = "1"
                i += 1
            break
        if arg.startswith("--games="):
            games = arg.split("=", 1)[1]
        elif arg == "--games" and i + 1 < len(argv):
            games = argv[i + 1]
            i += 1
        elif arg.startswith("--vis="):
            vis_mode = arg.split("=", 1)[1]
        elif arg == "--vis" and i + 1 < len(argv):
            vis_mode = argv[i + 1]
            i += 1
        i += 1
    if games:
        games = {g.strip().upper() for g in games.split(",") if g.strip()}
    if vis_mode is not None:
        vis_mode = normalize_vis_mode(vis_mode, default=VIS_MODE)
    return mode, games, vis_mode, import_paths, tune_action, layout_opts


def build_cache_cli(playlist_paths: list[str]) -> int:
    """Pre-convert MIDI files in one or more playlists to the persistent WAV cache.

    Usage: ac-ui build-cache [playlist_path ...]
    With no args, uses free_play_dir from saved state.
    """
    from ac_ui.audio import (
        _MIDI_EXTENSIONS,
        convert_midi_to_wav,
        lookup_midi_cache,
        store_to_midi_cache,
    )
    from ac_ui.persist import load_ui_state
    from ac_ui.tracks import free_play_source_name, scan_free_play_dir

    if not playlist_paths:
        state = load_ui_state()
        default_dir = state.get("free_play_dir", "")
        if not default_dir:
            print("No playlist specified and no free_play_dir in saved state.")
            return 1
        playlist_paths = [default_dir]

    # Collect unique tracks across all given playlists
    seen_tracks: set = set()
    all_midi: list = []
    all_audio: list = []
    source_labels: list = []

    for p in playlist_paths:
        p_expanded = os.path.expanduser(p)
        label = free_play_source_name(p_expanded)
        tracks = scan_free_play_dir(p_expanded)
        source_labels.append(f"{label} ({len(tracks)} pool entries, {len(set(tracks))} unique)")
        for t in tracks:
            if t in seen_tracks:
                continue
            seen_tracks.add(t)
            if os.path.splitext(t)[1].lower() in _MIDI_EXTENSIONS:
                all_midi.append(t)
            else:
                all_audio.append(t)

    print("Playlists scanned:")
    for lbl in source_labels:
        print(f"  {lbl}")
    print()

    # Check non-MIDI files
    missing_audio = [t for t in all_audio if not os.path.isfile(t)]
    if missing_audio:
        print(f"Missing audio files ({len(missing_audio)}):")
        for m in missing_audio:
            print(f"  MISSING  {m}")
        print()

    if not all_midi:
        print("No MIDI files found - nothing to convert.")
        return 1 if missing_audio else 0

    print(f"MIDI files: {len(all_midi)} unique tracks to check/convert")
    if not sys.stdout.isatty():
        print()

    errors = 0
    cached_count = 0
    converted_count = 0

    for i, track in enumerate(all_midi, 1):
        name = os.path.basename(track)
        prefix = f"[{i}/{len(all_midi)}]"

        cached = lookup_midi_cache(track)
        if cached:
            print(f"{prefix} cached     {name}")
            cached_count += 1
            continue

        print(f"{prefix} converting {name} ...", end="", flush=True)
        wav = convert_midi_to_wav(track)
        if wav:
            store_to_midi_cache(track, wav)
            try:
                os.unlink(wav)
            except Exception:
                pass
            print(" done")
            converted_count += 1
        else:
            print(" FAILED")
            errors += 1

    print()
    print(f"Done: {cached_count} already cached, {converted_count} newly converted, {errors} failed.")
    if errors:
        print("Failed tracks may need timidity installed and a soundfont configured.")
    return 1 if (errors or missing_audio) else 0

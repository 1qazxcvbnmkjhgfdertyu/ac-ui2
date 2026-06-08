"""Entry-point scaffolding: CLI argument parsing and run-mode dispatch.

This module is the future home of the top-level application logic that
currently lives in ui.py.  Migration is incremental; see Step 8 notes.
"""
from __future__ import annotations

import sys

from ac_ui.constants import VIS_MODES, VIS_MODE, normalize_vis_mode


def parse_cli_args(argv: list[str]) -> tuple:
    """Parse sys.argv and return (mode, games, vis_mode, import_paths, tune_action, layout_opts)."""
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
            print("  ac-ui [--games GCN,WW] [--vis MODE]")
            print("  ac-ui import <files...>")
            print("  ac-ui tune [show|play|reset]")
            print("  ac-ui stats")
            print("  ac-ui layout-sweep")
            print()
            print("Keys (in-app):")
            print("  n  next track    m/space  mute   T  town tune   E  EQ editor")
            print("  g  cycle game    v  variant   t  vis next   R  vis random")
            print("  h  simulate hour change       s  audio sink   l  repeat current track")
            print("  L  cycle layout preset")
            print("  +/-  volume ±5   PgUp/Dn volume ±10")
            print("  8  background mode   ?  help   q  quit")
            print()
            print(f"Vis modes: {', '.join(VIS_MODES)}")
            print()
            print("Env vars: AC_UI_MUSIC_DIR, AC_UI_MPV, AC_UI_VIS, AC_UI_REFRESH,")
            print("          AC_UI_CAVA_SOURCE, AC_UI_EQ_PATH, AC_UI_STATS,")
            print("          AC_UI_VIS_ATTACK_MS, AC_UI_VIS_DECAY_MS,")
            print("          AC_UI_LOOPBACK_LATENCY_MSEC, AC_UI_REPEAT_GUARD,")
            print("          AC_UI_LAYOUT_PRESET")
            sys.exit(0)
        if arg == "import":
            mode = "import"
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

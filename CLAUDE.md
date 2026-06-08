# AC-UI Codebase Guide

## Project layout

```
ac_ui/
  constants.py        — thin facade: re-exports from audio_config + town_tune_config
  audio_config.py     — CAVA/EQ/VIS/accessibility settings (self-contained)
  town_tune_config.py — TOWN_TUNE_*/ACGC_*/FluidSynth constants (self-contained)
  state.py            — dataclasses: UIState, PlaybackState, AudioState, VisualizerState, PanelState, RenderCache, SessionState
  services.py         — service classes: MpvClient, PactlClient, SinkManager, CavaRuntime
  fakes.py            — fake backends for tests: FakeMpvClient, FakePactlClient, FakeSinkManager, FakeCavaRuntime
  diagnostics.py      — structured error collector (warn/error/info, ring buffer)
  app.py              — parse_cli_args, future entry-point logic
  actions.py          — KEY_MAP and action ID constants
  transitions.py      — crossfade descriptor helpers (make_fade, make_transition)
  panels/
    __init__.py       — package stub
    now_playing.py    — Now Playing panel renderer (NowPlayingContext dataclass + render())
    history.py        — History panel pure renderer
    up_next.py        — Up Next panel pure renderer
    stats.py          — Stats panel pure renderer
    help.py           — Help panel pure renderer
  ui.py               — main() event loop (2500 lines; being split incrementally)
  audio.py            — subprocess wrappers: mpv_start, pactl, cava config
  colors.py           — ANSI color helpers, gradient system, theme palettes
  layout.py           — build_box, footer controls, layout sizing
  persist.py          — load_ui_state / save_ui_state (versioned)
  stats.py            — session stats (versioned)
  eq.py               — EQ bands (versioned)
  town_tune.py        — town tune CLI, renderer integration (versioned)
  tracks.py           — track listing, pick_weighted, filter_recent_tracks
  visualizer.py       — spectrum/flame/braille/etc. renderers
  term.py             — terminal control, RawMode, title art
  editors.py          — interactive EQ and tune editors
  layout_config.py    — layout preset normalization
  layout_engine.py    — layout constraint solver
```

## Persisted formats

All JSON files include `"_version": N`. Migration logic lives in the loader.

| File           | Module       | Version constant       |
|----------------|--------------|------------------------|
| state.json     | persist.py   | UI_STATE_VERSION = 2   |
| stats.json     | stats.py     | STATS_VERSION = 1      |
| eq.json        | eq.py        | EQ_STATE_VERSION = 1   |
| town_tune.json | town_tune.py | TOWN_TUNE_VERSION = 1  |

## Key invariants

- `audio_config.py` and `town_tune_config.py` must remain self-contained — no imports from other `ac_ui` modules.
- `constants.py` is a re-export facade. Add new constants to the appropriate sub-module first, then re-export.
- `_active_tod_grad` is a mutable module global in `colors.py`. Never snapshot it at import time; always reference it as `_clrs._active_tod_grad`.
- Panel renderers (`panels/*.py`) must be pure functions: given state, return `(plain_lines, color_lines)`. No I/O, no terminal writes.
- `diagnostics.warn/error` instead of bare `except Exception: pass` for any system boundary (audio, pactl, file I/O).

## Test suite

```sh
.venv/bin/pytest tests/ -v
.venv/bin/ruff check ac_ui/ --select F821   # must be zero
```

Tests use `fakes.py` backends — no real mpv/pactl/cava required.

## Adding a new feature

1. Add constants to `audio_config.py` or `town_tune_config.py` (or `constants.py` for one-offs).
2. Add the state field to the appropriate dataclass in `state.py`.
3. If it touches system integration, add a method to the relevant service in `services.py` and a fake in `fakes.py`.
4. If it adds a new panel view, add it to `panels/` as a pure renderer.
5. Wire up the key handler in `ui.py` (for now), targeting `actions.py` KEY_MAP.
6. Add a test in `tests/`.

## What not to do

- Do not call `shutil.which()` or spawn subprocesses at module import time in any new code.
- Do not add UI features to `ui.py`'s `main()` that could be panel renderers instead.
- Do not add closures to `main()` that capture mutable state — use dataclasses + service injection.
- Do not write `except Exception: pass` — use `diagnostics.warn()` or `diagnostics.error()` instead.

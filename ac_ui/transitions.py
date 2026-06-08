"""Crossfade and hour-transition logic.

Currently the crossfade state (`fade`, `transition`) lives as local dicts
inside main() in ui.py.  This module defines the canonical shape of those
dicts so that Step 8 can refer to them explicitly.

Crossfade dict shape (stored in PlaybackState.fade):
  {
      "old_proc":  subprocess.Popen,  # fading-out process
      "old_ipc":   str,               # IPC socket path for old proc
      "start":     float,             # monotonic time crossfade started
      "dur":       float,             # total fade duration in seconds
  }

Hour-transition dict shape (stored in PlaybackState.transition):
  {
      "next_hour": int,               # hour we're transitioning to
      "phase":     str,               # "chime" | "fade_in"
      "old_proc":  subprocess.Popen | None,
      "old_ipc":   str,
      "new_proc":  subprocess.Popen | None,
      "new_ipc":   str,
      "start":     float,
      "dur":       float,
      "simulate":  bool,
  }
"""
from __future__ import annotations

import time
from typing import Any


def make_fade(old_proc: Any, old_ipc: str, dur: float) -> dict:
    """Create a new crossfade descriptor."""
    return {
        "old_proc": old_proc,
        "old_ipc": old_ipc,
        "start": time.monotonic(),
        "dur": dur,
    }


def make_transition(
    next_hour: int,
    old_proc: Any,
    old_ipc: str,
    dur: float,
    simulate: bool = False,
) -> dict:
    """Create a new hour-transition descriptor."""
    return {
        "next_hour": next_hour,
        "phase": "chime",
        "old_proc": old_proc,
        "old_ipc": old_ipc,
        "new_proc": None,
        "new_ipc": "",
        "start": time.monotonic(),
        "dur": dur,
        "simulate": simulate,
    }


def fade_progress(fade: dict) -> float:
    """Return fade progress in [0.0, 1.0]."""
    elapsed = time.monotonic() - fade["start"]
    return min(1.0, elapsed / fade["dur"]) if fade["dur"] > 0 else 1.0


def is_fade_complete(fade: dict) -> bool:
    return fade_progress(fade) >= 1.0

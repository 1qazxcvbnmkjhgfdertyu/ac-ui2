"""Explicit state models for ac-ui.

Each dataclass represents one coherent state group.  They are defined here
so that the types can be imported independently of ui.py, and so that Step 8
(splitting ui.py into app/actions/panels) can refer to them without importing
the whole UI module.

The main() function in ui.py currently keeps this state as local variables;
the dataclasses serve as the canonical specification and will be wired up
fully in Step 8.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UIState:
    """Persisted user preferences — read from / written to disk."""
    output_vol: int = 80
    muted: bool = False
    mute_prev_vol: int = 80
    vis_mode: str = "bars"
    repeat_current: bool = False
    game: str = ""
    variant: str = ""
    layout: dict = field(default_factory=dict)
    theme: str = "default"

    @classmethod
    def from_dict(cls, d: dict) -> "UIState":
        """Construct from the raw dict returned by load_ui_state()."""
        return cls(
            output_vol=int(d.get("output_vol", 80)),
            muted=bool(d.get("muted", False)),
            mute_prev_vol=int(d.get("mute_prev_vol", 80)),
            vis_mode=str(d.get("vis_mode", "bars")),
            repeat_current=bool(d.get("repeat_current", False)),
            game=str(d.get("game", "")),
            variant=str(d.get("variant", "")),
            layout=dict(d.get("layout") or {}),
            theme=str(d.get("theme", "default")),
        )

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


@dataclass
class PlaybackState:
    """Current track, mpv handle, and crossfade/transition state."""
    current_track: str | None = None
    current_track_hour: int | None = None
    last_hour: int | None = None
    track_pick_reason: str | None = None
    repeat_current: bool = False
    showing_chime: bool = False
    chime_kind: str | None = None
    chime_proc: Any = None
    chime_temp_path: str | None = None
    fade: Any = None
    transition: Any = None


@dataclass
class AudioState:
    """PulseAudio sink, mpv IPC sockets, and cava subprocess state."""
    private_sink_name: str = ""
    ipc_a: str = ""
    ipc_b: str = ""
    current_ipc: str = ""
    cava_conf_path: str = ""
    mpv_proc: Any = None
    cava_proc: Any = None
    cava_thread: Any = None
    cava_lock: threading.Lock = field(default_factory=threading.Lock)
    cava_ok: bool = False
    cava_bars: Any = None
    cava_bars_count: int | None = None
    cava_err: str | None = None
    cava_started_ts: float = 0.0
    cava_retry_ts: float = 0.0
    cava_last_data_ts: float = 0.0
    cava_last_stderr: str = ""
    cava_last_label: str | None = None
    last_loopback_ts: float = 0.0
    last_loopback_vol: Any = None
    last_loopback_muted: Any = None
    last_query_ts: float = 0.0
    mpv_query_interval: float = 0.5
    cached_tpos: Any = None
    cached_dur: Any = None
    cached_vol: Any = None


@dataclass
class VisualizerState:
    """Per-frame visualizer animation buffers and mode state."""
    vis_idx: int = 0
    smooth_bars: Any = None
    peak_bars: Any = None
    trail_bars: Any = None
    cap_pos: Any = None
    cap_vel: Any = None
    bass_energy: float = 0.0
    last_vis_update_ts: float | None = None
    vis_line_cache: Any = None
    vis_line_cache_key: Any = None
    flame_state: dict = field(
        default_factory=lambda: {"heat": None, "rng": 0xF1A3C0DE0BADCAFE, "frame": 0, "rows": 0, "cols": 0}
    )
    butterfly_state: dict = field(default_factory=lambda: {"frame": 0})
    matrix_state: dict = field(default_factory=lambda: {"frame": 0})
    heartbeat_state: dict = field(
        default_factory=lambda: {"buf": None, "prev_bass": 0.0, "spike_phase": 0.0}
    )
    scope_frame: int = 0
    last_title_anim_ts: float = 0.0
    bars_len_cached: Any = None
    bars_len_cols: int = 0
    bars_len_count: Any = None


@dataclass
class PanelState:
    """Panel visibility, focus, and cursor state."""
    show_history: bool = True
    show_up_next: bool = True
    show_help: bool = False
    show_debug: bool = False
    panel_focus: str | None = None
    hist_sel: int = 0
    up_sel: int = 0
    background_mode: bool = False
    focused: bool = True


@dataclass
class RenderCache:
    """Memoized render artifacts to avoid recomputing unchanged frames."""
    info_cache_key: Any = None
    info_plain_cache: tuple = field(default_factory=tuple)
    info_color_cache: tuple = field(default_factory=tuple)
    info_box_cache: Any = None
    info_box_cache_key: Any = None
    info_w_cache: int = 0
    stats_cache_key: Any = None
    stats_box_cache: Any = None
    stats_w_cache: int = 0
    help_cache_key: Any = None
    help_box_cache: Any = None
    help_sink_cache: Any = None
    help_sink_cache_ts: float = 0.0
    hist_cache_key: Any = None
    hist_box_cache: Any = None
    hist_w_cache: int = 0
    up_cache_key: Any = None
    up_box_cache: Any = None
    up_w_cache: int = 0
    last_render_key: Any = None
    last_render_ts: float = 0.0
    last_lines: Any = None
    footer_control_lines: list = field(default_factory=list)
    footer_has_separator: bool = False


@dataclass
class SessionState:
    """Per-session runtime bookkeeping."""
    start: float = field(default_factory=time.time)
    listen: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=6))
    recent_track_paths: deque | None = None
    next_candidates: list = field(default_factory=list)
    next_candidates_ts: float = 0.0
    next_candidates_key: Any = None
    banned_tracks: set = field(default_factory=set)
    stats_data: Any = None
    stats_last_ts: float = field(default_factory=time.time)
    stats_last_flush: float = field(default_factory=time.time)
    stats_q: Any = None
    stats_stop: Any = None
    vol_delta_flash: Any = None
    state_banner: Any = None
    last_key: str = ""
    last_key_ts: float = 0.0
    last_mute_toggle_ts: float = 0.0
    last_time_str: str | None = None
    last_time_sec: int | None = None
    resize_pending: bool = False
    last_resize_ts: float = 0.0
    last_term_cols: int | None = None
    last_term_rows: int | None = None

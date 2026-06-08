"""System integration services.

Each class wraps one external system (mpv, pactl, cava, PulseAudio sinks)
with a stable interface that can be swapped for a fake in tests (Step 11).
These are thin adapters over the functions in audio.py — they add state
encapsulation and a clear seam for mocking, not new logic.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Any


# ── MpvClient ─────────────────────────────────────────────────────────────────

class MpvClient:
    """Controls a single mpv process via its JSON IPC socket."""

    def __init__(self, ipc_path: str) -> None:
        self.ipc_path = ipc_path
        self._proc: subprocess.Popen | None = None

    def start(
        self,
        track: str,
        audio_device: str | None = None,
        volume: int | None = None,
        loop_file: bool = False,
    ) -> None:
        from ac_ui.audio import mpv_start
        self._proc = mpv_start(
            track, self.ipc_path,
            audio_device=audio_device, volume=volume, loop_file=loop_file,
        )

    def command(self, cmd: list) -> bool:
        from ac_ui.audio import mpv_command
        return mpv_command(self.ipc_path, cmd)

    def query(self, prop: str) -> Any:
        from ac_ui.audio import mpv_query
        return mpv_query(self.ipc_path, prop)

    def query_props(self, props: list[str]) -> dict:
        from ac_ui.audio import mpv_query_props
        return mpv_query_props(self.ipc_path, props)

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def proc(self) -> subprocess.Popen | None:
        return self._proc

    @proc.setter
    def proc(self, value: subprocess.Popen | None) -> None:
        self._proc = value


# ── PactlClient ───────────────────────────────────────────────────────────────

class PactlClient:
    """Thin wrapper around pactl / PulseAudio queries."""

    def list_sinks(self) -> list[str]:
        from ac_ui.audio import list_sinks
        return list_sinks()

    def get_default_sink(self) -> str | None:
        from ac_ui.audio import get_default_sink
        return get_default_sink()

    def find_loopback_input_ids(self, loopback_module_id: Any, sink_name: str) -> list[str]:
        from ac_ui.audio import find_loopback_input_ids
        return find_loopback_input_ids(loopback_module_id, sink_name)

    def set_loopback_volume(self, loopback_module_id: Any, sink_name: str, vol_percent: int) -> bool:
        from ac_ui.audio import set_loopback_volume
        return set_loopback_volume(loopback_module_id, sink_name, vol_percent)

    def set_loopback_mute(self, loopback_module_id: Any, sink_name: str, mute_on: bool) -> bool:
        from ac_ui.audio import set_loopback_mute
        return set_loopback_mute(loopback_module_id, sink_name, mute_on)

    def detect_cava_input(self) -> tuple[str | None, str | None, str]:
        from ac_ui.audio import detect_cava_input
        return detect_cava_input()

    def build_cava_input_candidates(
        self,
        base_method: str | None,
        base_source: str | None,
        detect_mode: str,
        audio_device: str | None = None,
        private_sink: str | None = None,
        output_sink: str | None = None,
    ) -> list[dict]:
        from ac_ui.audio import build_cava_input_candidates
        return build_cava_input_candidates(
            base_method, base_source, detect_mode,
            audio_device=audio_device, private_sink=private_sink, output_sink=output_sink,
        )


# ── SinkManager ───────────────────────────────────────────────────────────────

class SinkManager:
    """Manages the private null sink and loopback module lifecycle."""

    def __init__(self) -> None:
        self.null_module_id: Any = None
        self.loopback_module_id: Any = None
        self.sink_name: str = ""

    def setup(self, output_sink: str | None = None, sink_name: str | None = None) -> tuple:
        from ac_ui.audio import setup_private_sink
        result = setup_private_sink(output_sink=output_sink, sink_name=sink_name)
        if result and len(result) == 4:
            sink_name, null_mod, loopback_mod, _target = result
            self.sink_name = sink_name
            self.null_module_id = null_mod
            self.loopback_module_id = loopback_mod
        return result

    def teardown(self) -> None:
        from ac_ui.audio import teardown_private_sink
        if self.null_module_id is not None or self.loopback_module_id is not None:
            teardown_private_sink(self.null_module_id, self.loopback_module_id)
            self.null_module_id = None
            self.loopback_module_id = None

    def reload_loopback(self, target_sink: str) -> Any:
        from ac_ui.audio import reload_loopback
        result = reload_loopback(self.loopback_module_id, self.sink_name, target_sink)
        if result is not None:
            self.loopback_module_id = result
        return result

    @property
    def active(self) -> bool:
        return self.null_module_id is not None


# ── CavaRuntime ───────────────────────────────────────────────────────────────

class CavaRuntime:
    """Manages the cava subprocess and its reader thread."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.bars: list[float] | None = None
        self.ok: bool = False
        self.err: str | None = None
        self.bars_count: int | None = None
        self.started_ts: float = 0.0
        self.retry_ts: float = 0.0
        self.last_data_ts: float = 0.0
        self.last_stderr: str = ""
        self.last_label: str | None = None

    @property
    def proc(self) -> subprocess.Popen | None:
        return self._proc

    @proc.setter
    def proc(self, value: subprocess.Popen | None) -> None:
        self._proc = value

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @thread.setter
    def thread(self, value: threading.Thread | None) -> None:
        self._thread = value

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        self.ok = False
        self.bars = None

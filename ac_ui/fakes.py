"""Fake backends for integration tests.

Each class implements the same interface as its real counterpart in services.py
but does nothing that requires external processes (mpv, pactl, cava).
Use via monkeypatch or dependency injection in tests.

Example:
    from ac_ui.fakes import FakeMpvClient, FakePactlClient, FakeSinkManager, FakeCavaRuntime

    def test_playback_banner(monkeypatch):
        client = FakeMpvClient()
        monkeypatch.setattr("ac_ui.audio.mpv_start", lambda *a, **kw: client._proc)
        ...
"""
from __future__ import annotations

from collections import deque
import math
import threading
import time
from typing import Any


class FakeMpvClient:
    """In-memory mpv stub: tracks calls, never spawns a subprocess."""

    def __init__(self, ipc_path: str = "/tmp/fake-mpv.sock") -> None:
        self.ipc_path = ipc_path
        self._proc: Any = None
        self._running = False
        self.started_tracks: list[str] = []
        self.commands: list[list] = []
        self._props: dict[str, Any] = {
            "time-pos": 10.0,
            "duration": 120.0,
            "volume": 80,
            "pause": False,
        }

    def start(
        self,
        track: str,
        audio_device: str | None = None,
        volume: int | None = None,
        loop_file: bool = False,
    ) -> None:
        self.started_tracks.append(track)
        self._running = True

    def command(self, cmd: list) -> bool:
        self.commands.append(cmd)
        return True

    def query(self, prop: str) -> Any:
        return self._props.get(prop)

    def query_props(self, props: list[str]) -> dict:
        return {p: self._props.get(p) for p in props}

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def proc(self) -> Any:
        return self._proc

    @proc.setter
    def proc(self, value: Any) -> None:
        self._proc = value

    def set_prop(self, name: str, value: Any) -> None:
        self._props[name] = value


class FakePactlClient:
    """In-memory pactl stub: returns configurable fake sink lists."""

    def __init__(self, sinks: list[str] | None = None, default_sink: str = "fake-sink") -> None:
        self._sinks = sinks or ["fake-sink", "hdmi-output"]
        self._default_sink = default_sink
        self.volume_calls: list[tuple] = []
        self.mute_calls: list[tuple] = []

    def list_sinks(self) -> list[str]:
        return list(self._sinks)

    def get_default_sink(self) -> str | None:
        return self._default_sink

    def find_loopback_input_ids(self, loopback_module_id: Any, sink_name: str) -> list[str]:
        return ["42"]  # stable fake input ID

    def set_loopback_volume(self, loopback_module_id: Any, sink_name: str, vol_percent: int) -> bool:
        self.volume_calls.append((loopback_module_id, sink_name, vol_percent))
        return True

    def set_loopback_mute(self, loopback_module_id: Any, sink_name: str, mute_on: bool) -> bool:
        self.mute_calls.append((loopback_module_id, sink_name, mute_on))
        return True

    def detect_cava_input(self) -> tuple[str | None, str | None, str]:
        return "pulse", f"{self._default_sink}.monitor", "auto"

    def build_cava_input_candidates(
        self,
        base_method: str | None,
        base_source: str | None,
        detect_mode: str,
        audio_device: str | None = None,
        private_sink: str | None = None,
        output_sink: str | None = None,
    ) -> list[dict]:
        return [{"method": base_method, "source": base_source, "label": detect_mode}]

    def build_pcm_input_candidates(
        self,
        base_method: str | None,
        base_source: str | None,
        detect_mode: str,
        audio_device: str | None = None,
        private_sink: str | None = None,
        output_sink: str | None = None,
    ) -> list[dict]:
        return [{"method": base_method, "source": base_source, "label": detect_mode}]


class FakeSinkManager:
    """In-memory sink manager: remembers setup/teardown calls."""

    def __init__(self) -> None:
        self.null_module_id: Any = "fake-null-1001"
        self.loopback_module_id: Any = "fake-loopback-1002"
        self.sink_name: str = "acui-fake"
        self._active = False
        self.setup_calls: int = 0
        self.teardown_calls: int = 0

    def setup(self, output_sink: str | None = None, sink_name: str | None = None) -> tuple:
        self.setup_calls += 1
        self._active = True
        if sink_name:
            self.sink_name = sink_name
        return self.sink_name, self.null_module_id, self.loopback_module_id, output_sink or "fake-sink"

    def teardown(self) -> None:
        self.teardown_calls += 1
        self._active = False

    def reload_loopback(self, target_sink: str) -> Any:
        return self.loopback_module_id

    @property
    def active(self) -> bool:
        return self._active


class FakeCavaRuntime:
    """In-memory cava stub: generates synthetic bar data."""

    def __init__(self, n_bars: int = 32) -> None:
        self.n_bars = n_bars
        self._running = False
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
        self._proc: Any = None
        self._thread: Any = None

    def current_candidate(self) -> dict:
        return {"method": "pulse", "source": "fake.monitor", "label": "fake"}

    def advance_candidate(self) -> bool:
        return False

    def start(self) -> bool:
        self.start_fake()
        return True

    def restart(self, advance: bool = False) -> bool:
        self.stop()
        return self.start()

    def start_fake(self) -> None:
        """Begin emitting synthetic bars — call from test setup."""
        self._running = True
        self.ok = True
        self.bars_count = self.n_bars
        self.started_ts = time.monotonic()
        self.last_data_ts = time.monotonic()
        self.bars = [0.5] * self.n_bars

    @property
    def proc(self) -> Any:
        return self._proc

    @proc.setter
    def proc(self, value: Any) -> None:
        self._proc = value

    @property
    def thread(self) -> Any:
        return self._thread

    @thread.setter
    def thread(self, value: Any) -> None:
        self._thread = value

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._running = False
        self.ok = False
        self.bars = None

    def tick(self, t: float | None = None) -> None:
        """Advance synthetic bar data — call per test frame."""
        if not self._running:
            return
        now = t if t is not None else time.monotonic()
        self.bars = [abs(math.sin(now * 2 + i * 0.3)) for i in range(self.n_bars)]
        self.last_data_ts = now


class FakePcmRuntime:
    """In-memory PCM stub: generates deterministic stereo waveform windows."""

    def __init__(self, sample_rate: int = 48000, channels: int = 2, buffer_frames: int = 4096) -> None:
        self.sample_rate = max(8000, int(sample_rate))
        self.channels = 1 if int(channels) <= 1 else 2
        self.buffer_frames = max(256, int(buffer_frames))
        self._running = False
        self._lock = threading.Lock()
        self._left = deque(maxlen=self.buffer_frames)
        self._right = deque(maxlen=self.buffer_frames)
        self.ok: bool = False
        self.err: str | None = None
        self.started_ts: float = 0.0
        self.retry_ts: float = 0.0
        self.last_data_ts: float = 0.0
        self.last_stderr: str = ""
        self.last_label: str | None = None
        self.last_backend: str | None = "fake"
        self.frames_captured: int = 0
        self._proc: Any = None
        self._thread: Any = None

    def current_candidate(self) -> dict:
        return {"method": "pulse", "source": "fake.monitor", "label": "fake"}

    def advance_candidate(self) -> bool:
        return False

    def start(self) -> bool:
        self.start_fake()
        return True

    def restart(self, advance: bool = False) -> bool:
        self.stop()
        return self.start()

    def start_fake(self) -> None:
        self._running = True
        self.ok = True
        self.err = None
        self.last_label = "fake"
        self.started_ts = time.monotonic()
        self.tick(self.started_ts, frames=min(1024, self.buffer_frames))

    @property
    def proc(self) -> Any:
        return self._proc

    @proc.setter
    def proc(self, value: Any) -> None:
        self._proc = value

    @property
    def thread(self) -> Any:
        return self._thread

    @thread.setter
    def thread(self, value: Any) -> None:
        self._thread = value

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def is_running(self) -> bool:
        return self._running

    def waveform_window(self, frames: int | None = None) -> tuple[tuple[float, ...], tuple[float, ...]]:
        with self._lock:
            left = tuple(self._left)
            right = tuple(self._right)
        if frames is None or frames <= 0:
            return left, right
        return left[-frames:], right[-frames:]

    def clear_buffer(self) -> None:
        with self._lock:
            self._left.clear()
            self._right.clear()
            self.frames_captured = 0

    def stop(self) -> None:
        self._running = False
        self.ok = False
        self.clear_buffer()

    def tick(self, t: float | None = None, frames: int = 256) -> None:
        """Append a synthetic stereo frame window — call per test frame."""
        if not self._running:
            return
        now = t if t is not None else time.monotonic()
        base_index = self.frames_captured
        left = []
        right = []
        for idx in range(max(1, int(frames))):
            phase = (base_index + idx) / self.sample_rate
            left.append(math.sin(phase * math.tau * 220.0) * 0.75)
            right.append(math.sin(phase * math.tau * 330.0 + 0.85) * 0.55)
        with self._lock:
            self._left.extend(left)
            self._right.extend(right)
            self.frames_captured += len(left)
            self.last_data_ts = now


class FakePlaybackCache:
    """In-memory playback cache stub for tests."""

    def __init__(self, query_interval: float = 0.5) -> None:
        self.query_interval = query_interval
        self.tpos: float | None = 10.0
        self.dur: float | None = 120.0
        self.vol: float | None = 80.0

    def query(self, ipc_path, current_track, transition, fade) -> tuple:
        return self.tpos, self.dur, self.vol

"""System integration services.


Each class wraps one external system (mpv, pactl, cava, PulseAudio sinks)
with a stable interface that can be swapped for a fake in tests (Step 11).
These are thin adapters over the functions in audio.py — they add state
encapsulation and a clear seam for mocking, not new logic.
"""
from __future__ import annotations

import queue
import struct
import subprocess
import threading
import time
from collections import deque
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

    def build_pcm_input_candidates(
        self,
        base_method: str | None,
        base_source: str | None,
        detect_mode: str,
        audio_device: str | None = None,
        private_sink: str | None = None,
        output_sink: str | None = None,
    ) -> list[dict]:
        from ac_ui.audio import build_pcm_input_candidates
        return build_pcm_input_candidates(
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
            _sname, null_mod, loopback_mod, _target = result
            if _sname is not None:
                self.sink_name = _sname
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
            new_id, _target = result
            self.loopback_module_id = new_id
        return result

    @property
    def active(self) -> bool:
        return self.null_module_id is not None


# ── PulseRuntime ─────────────────────────────────────────────────────────────

class PulseRuntime:
    """Background cache and command worker for loopback and default-sink state."""

    def __init__(
        self,
        loopback_module_id: Any = None,
        sink_name: str = "",
        *,
        loopback_refresh_interval: float = 1.0,
        default_sink_refresh_interval: float = 5.0,
    ) -> None:
        self.loopback_module_id = loopback_module_id
        self.sink_name = sink_name
        self.loopback_refresh_interval = max(0.2, float(loopback_refresh_interval))
        self.default_sink_refresh_interval = max(1.0, float(default_sink_refresh_interval))

        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._loopback_input_ids: list[str] = []
        self._default_sink: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(("stop", None))
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None

    def configure_loopback(self, loopback_module_id: Any, sink_name: str) -> None:
        with self._lock:
            self.loopback_module_id = loopback_module_id
            self.sink_name = sink_name
            self._loopback_input_ids = []
        self.request_refresh()

    def request_volume(self, vol_percent: int) -> None:
        self._queue.put(("volume", int(vol_percent)))

    def request_mute(self, mute_on: bool) -> None:
        self._queue.put(("mute", bool(mute_on)))

    def request_refresh(self) -> None:
        self._queue.put(("refresh", None))

    def loopback_input_ids(self) -> list[str]:
        with self._lock:
            return list(self._loopback_input_ids)

    def default_sink(self) -> str | None:
        with self._lock:
            return self._default_sink

    def _refresh_default_sink(self) -> None:
        from ac_ui.audio import get_default_sink
        sink = get_default_sink()
        with self._lock:
            self._default_sink = sink

    def _refresh_loopback_inputs(self) -> list[str]:
        from ac_ui.audio import find_loopback_input_ids
        with self._lock:
            loopback_module_id = self.loopback_module_id
            sink_name = self.sink_name
        ids = find_loopback_input_ids(loopback_module_id, sink_name) if (loopback_module_id or sink_name) else []
        with self._lock:
            self._loopback_input_ids = list(ids)
        return ids

    def _worker(self) -> None:
        from ac_ui.audio import set_loopback_mute, set_loopback_volume

        next_default_ts = 0.0
        next_loopback_ts = 0.0
        pending_mute = None
        pending_volume = None

        while not self._stop.is_set():
            now = time.time()
            timeout = min(
                max(0.05, next_default_ts - now) if next_default_ts else 0.25,
                max(0.05, next_loopback_ts - now) if next_loopback_ts else 0.25,
            )
            try:
                kind, value = self._queue.get(timeout=timeout)
            except queue.Empty:
                kind, value = None, None

            if kind == "stop":
                break
            if kind == "volume":
                pending_volume = int(value)
            elif kind == "mute":
                pending_mute = bool(value)
            elif kind == "refresh":
                next_default_ts = 0.0
                next_loopback_ts = 0.0

            now = time.time()
            if now >= next_default_ts:
                self._refresh_default_sink()
                next_default_ts = now + self.default_sink_refresh_interval

            ids: list[str] = []
            if now >= next_loopback_ts:
                ids = self._refresh_loopback_inputs()
                next_loopback_ts = now + self.loopback_refresh_interval
            else:
                ids = self.loopback_input_ids()

            with self._lock:
                loopback_module_id = self.loopback_module_id
                sink_name = self.sink_name

            if ids and pending_mute is not None:
                set_loopback_mute(loopback_module_id, sink_name, pending_mute)
                pending_mute = None
            if ids and pending_volume is not None:
                set_loopback_volume(loopback_module_id, sink_name, pending_volume)
                pending_volume = None


# ── CavaRuntime ───────────────────────────────────────────────────────────────

class CavaRuntime:
    """Manages the cava subprocess, reader thread, and input candidate selection."""

    def __init__(
        self,
        conf_path: str,
        candidates: list[dict],
        fallback_method: str | None = None,
        fallback_source: str | None = None,
        fallback_detect_mode: str = "configured",
    ) -> None:
        self.conf_path = conf_path
        self.candidates = candidates
        self.candidate_idx: int = 0
        self._fallback_method = fallback_method
        self._fallback_source = fallback_source
        self._fallback_detect_mode = fallback_detect_mode

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

    def current_candidate(self) -> dict:
        if not self.candidates:
            return {
                "method": self._fallback_method,
                "source": self._fallback_source,
                "label": self._fallback_detect_mode,
            }
        idx = max(0, min(self.candidate_idx, len(self.candidates) - 1))
        return self.candidates[idx]

    def advance_candidate(self) -> bool:
        if len(self.candidates) <= 1:
            return False
        start_idx = self.candidate_idx
        self.candidate_idx = (self.candidate_idx + 1) % len(self.candidates)
        return self.candidate_idx != start_idx

    def start(self) -> bool:
        from ac_ui.audio import cava_config_text, calc_cava_bars
        from ac_ui.constants import CAVA_BIN, CAVA_MAX, _resolve_command_path
        import time as _time

        if self._proc is not None:
            return True
        cava_cmd = CAVA_BIN
        cava_path = _resolve_command_path(cava_cmd)
        if not cava_path:
            self.err = f"cava not installed: {cava_cmd}"
            return False

        candidate = self.current_candidate()
        self.last_label = candidate.get("label")
        self.last_stderr = ""
        self.ok = False
        self.bars = None
        self.err = None

        bars_count = calc_cava_bars()
        self.bars_count = bars_count
        try:
            with open(self.conf_path, "w") as f:
                f.write(cava_config_text(bars_count, candidate.get("method"), candidate.get("source")))
        except Exception as e:
            self.err = f"config error: {e}"
            return False
        try:
            self._proc = subprocess.Popen(
                [cava_path, "-p", self.conf_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.err = f"start error: {e}"
            return False

        self.started_ts = _time.time()
        self.last_data_ts = 0.0
        self.retry_ts = 0.0

        def _reader():
            proc = self._proc
            if proc is None or proc.stdout is None:
                return
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(";")
                vals = []
                for p in parts:
                    try:
                        vals.append(int(p))
                    except Exception:
                        pass
                if not vals:
                    continue
                if len(vals) < bars_count:
                    vals.extend([0] * (bars_count - len(vals)))
                if len(vals) > bars_count:
                    vals = vals[:bars_count]
                bars = [min(1.0, v / CAVA_MAX) for v in vals]
                with self._lock:
                    self.bars = bars
                    self.ok = True
                    self.last_data_ts = _time.time()

        self._thread = threading.Thread(target=_reader, daemon=True)
        self._thread.start()

        def _stderr_reader():
            proc = self._proc
            if proc is None or proc.stderr is None:
                return
            for line in proc.stderr:
                text = line.strip()
                if text:
                    self.last_stderr = text

        threading.Thread(target=_stderr_reader, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=0.5)
                except Exception:
                    pass
            self._proc = None
        with self._lock:
            self.bars = None
            self.ok = False
        self.err = None
        self.last_label = None

    def restart(self, advance: bool = False) -> bool:
        import time as _time
        if advance:
            self.advance_candidate()
        self.stop()
        started = self.start()
        self.retry_ts = _time.time()
        return started


# ── PcmRuntime ────────────────────────────────────────────────────────────────

class PcmRuntime:
    """Captures live stereo PCM from the active monitor route into a ring buffer."""

    def __init__(
        self,
        candidates: list[dict],
        fallback_method: str | None = None,
        fallback_source: str | None = None,
        fallback_detect_mode: str = "configured",
        *,
        sample_rate: int = 48000,
        channels: int = 2,
        latency_ms: int = 30,
        buffer_frames: int = 16384,
        backend_preference: tuple[str, ...] = ("parec", "pw-record"),
    ) -> None:
        self.candidates = candidates
        self.candidate_idx: int = 0
        self._fallback_method = fallback_method
        self._fallback_source = fallback_source
        self._fallback_detect_mode = fallback_detect_mode

        self.sample_rate = max(8000, int(sample_rate))
        self.channels = 1 if int(channels) <= 1 else 2
        self.latency_ms = max(5, int(latency_ms))
        self.buffer_frames = max(1024, int(buffer_frames))
        self.backend_preference = tuple(backend_preference or ("parec", "pw-record"))

        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
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
        self.last_backend: str | None = None
        self.frames_captured: int = 0

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

    def current_candidate(self) -> dict:
        if not self.candidates:
            return {
                "method": self._fallback_method,
                "source": self._fallback_source,
                "label": self._fallback_detect_mode,
            }
        idx = max(0, min(self.candidate_idx, len(self.candidates) - 1))
        return self.candidates[idx]

    def advance_candidate(self) -> bool:
        if len(self.candidates) <= 1:
            return False
        start_idx = self.candidate_idx
        self.candidate_idx = (self.candidate_idx + 1) % len(self.candidates)
        return self.candidate_idx != start_idx

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

    def start(self) -> bool:
        from ac_ui.audio import available_pcm_capture_backends, pcm_capture_command
        import time as _time

        if self._proc is not None:
            return True

        candidate = self.current_candidate()
        self.last_label = candidate.get("label")
        self.last_stderr = ""
        self.last_backend = None
        self.ok = False
        self.err = None
        self.clear_buffer()

        available = set(available_pcm_capture_backends())
        ordered_backends = [name for name in self.backend_preference if name in available]
        if not ordered_backends:
            self.err = "parec/pw-record not installed"
            return False

        cmd = None
        for backend in ordered_backends:
            cmd = pcm_capture_command(
                candidate.get("method"),
                candidate.get("source"),
                backend=backend,
                sample_rate=self.sample_rate,
                channels=self.channels,
                latency_ms=self.latency_ms,
            )
            if cmd:
                self.last_backend = backend
                break
        if cmd is None:
            label = candidate.get("label") or "configured"
            self.err = f"unsupported pcm input via {label}"
            return False

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as e:
            self.err = f"start error: {e}"
            return False

        self.started_ts = _time.time()
        self.last_data_ts = 0.0
        self.retry_ts = 0.0

        def _reader():
            proc = self._proc
            if proc is None or proc.stdout is None:
                return
            frame_bytes = self.channels * 2
            carry = b""
            for chunk in iter(lambda: proc.stdout.read(4096), b""):
                if not chunk:
                    break
                data = carry + chunk
                usable = len(data) - (len(data) % frame_bytes)
                if usable <= 0:
                    carry = data
                    continue
                carry = data[usable:]
                frames = usable // frame_bytes
                left = []
                right = []
                view = memoryview(data)[:usable]
                if self.channels == 1:
                    for (mono,) in struct.iter_unpack("<h", view):
                        value = max(-1.0, min(1.0, mono / 32768.0))
                        left.append(value)
                        right.append(value)
                else:
                    for l_raw, r_raw in struct.iter_unpack("<hh", view):
                        left.append(max(-1.0, min(1.0, l_raw / 32768.0)))
                        right.append(max(-1.0, min(1.0, r_raw / 32768.0)))
                now = _time.time()
                with self._lock:
                    self._left.extend(left)
                    self._right.extend(right)
                    self.frames_captured += frames
                    self.ok = True
                    self.last_data_ts = now

        self._thread = threading.Thread(target=_reader, daemon=True)
        self._thread.start()

        def _stderr_reader():
            proc = self._proc
            if proc is None or proc.stderr is None:
                return
            for line in proc.stderr:
                try:
                    text = line.decode("utf-8", "replace").strip()
                except Exception:
                    text = str(line).strip()
                if text:
                    self.last_stderr = text

        threading.Thread(target=_stderr_reader, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=0.5)
                except Exception:
                    pass
            self._proc = None
        self.clear_buffer()
        self.ok = False
        self.err = None
        self.last_label = None
        self.last_backend = None

    def restart(self, advance: bool = False) -> bool:
        import time as _time
        if advance:
            self.advance_candidate()
        self.stop()
        started = self.start()
        self.retry_ts = _time.time()
        return started


# ── PlaybackCache ─────────────────────────────────────────────────────────────

class PlaybackCache:
    """Caches mpv time-pos/duration/volume queries to limit socket overhead per frame."""

    def __init__(self, query_interval: float = 0.5) -> None:
        self.query_interval = query_interval
        self._last_ts: float = 0.0
        self.tpos: float | None = None
        self.dur: float | None = None
        self.vol: float | None = None

    def query(
        self,
        ipc_path: str,
        current_track: str | None,
        transition: dict | None,
        fade: dict | None,
    ) -> tuple:
        import time as _time
        from ac_ui.audio import mpv_query_props
        if transition or fade:
            return self.tpos, self.dur, self.vol
        now = _time.time()
        if now - self._last_ts > self.query_interval:
            values = mpv_query_props(ipc_path, ("time-pos", "duration", "volume")) if current_track else {}
            self.tpos = values.get("time-pos")
            self.dur = values.get("duration")
            self.vol = values.get("volume")
            self._last_ts = now
        return self.tpos, self.dur, self.vol

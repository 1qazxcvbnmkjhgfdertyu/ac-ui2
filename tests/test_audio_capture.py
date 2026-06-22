import io
import importlib
import math
import os
import struct
import time

import pytest


def test_pcm_capture_command_builds_parec(monkeypatch):
    import ac_ui.audio as A

    monkeypatch.setattr(A.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "parec" else None)
    cmd = A.pcm_capture_command(
        "pulse",
        "acui-test.monitor",
        backend="parec",
        sample_rate=48000,
        channels=2,
        latency_ms=25,
    )
    assert cmd is not None
    assert cmd[0] == "parec"
    assert "--record" in cmd
    assert "--raw" in cmd
    assert "--format=s16le" in cmd
    assert "--device=acui-test.monitor" in cmd


def test_pcm_capture_command_builds_pw_record(monkeypatch):
    import ac_ui.audio as A

    monkeypatch.setattr(A.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "pw-record" else None)
    cmd = A.pcm_capture_command(
        "pulse",
        "acui-test.monitor",
        backend="pw-record",
        sample_rate=48000,
        channels=2,
        latency_ms=25,
    )
    assert cmd is not None
    assert cmd[0] == "pw-record"
    assert "--raw" in cmd
    assert "--target" in cmd
    assert cmd[-1] == "-"


def test_pcm_runtime_captures_stereo_window(monkeypatch):
    import ac_ui.audio as A
    import ac_ui.services as S

    class _FakeProc:
        def __init__(self, payload):
            self.stdout = io.BytesIO(payload)
            self.stderr = io.BytesIO(b"")
            self._returncode = None

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = 0

        def wait(self, timeout=None):
            self._returncode = 0
            return 0

        def kill(self):
            self._returncode = -9

    payload = struct.pack("<hhhh", 32767, -32768, 0, 16384)
    monkeypatch.setattr(A, "available_pcm_capture_backends", lambda: ("parec",))
    monkeypatch.setattr(A, "pcm_capture_command", lambda *args, **kwargs: ["fake-pcm"])
    monkeypatch.setattr(S.subprocess, "Popen", lambda *args, **kwargs: _FakeProc(payload))

    pcm = S.PcmRuntime([{"method": "pulse", "source": "acui.monitor", "label": "test"}])
    assert pcm.start()
    if pcm.thread is not None:
        pcm.thread.join(timeout=0.2)
    timeout = time.time() + 0.3
    while not pcm.ok and time.time() < timeout:
        time.sleep(0.01)
    left, right = pcm.waveform_window()
    assert left
    assert right
    assert left[0] == pytest.approx(32767 / 32768.0, abs=1e-4)
    assert right[0] == pytest.approx(-1.0, abs=1e-4)
    assert right[-1] == pytest.approx(0.5, abs=1e-4)


def test_pcm_runtime_reports_missing_backend(monkeypatch):
    import ac_ui.audio as A
    import ac_ui.services as S

    monkeypatch.setattr(A, "available_pcm_capture_backends", lambda: ())
    pcm = S.PcmRuntime([{"method": "pulse", "source": "acui.monitor", "label": "test"}])
    assert not pcm.start()
    assert pcm.err == "parec/pw-record not installed"


def test_spectrum_bars_from_waveform_returns_requested_count():
    from ac_ui.audio_snapshot import spectrum_bars_from_waveform

    left = [math.sin(i * 0.09) * 0.8 for i in range(1024)]
    right = [math.sin(i * 0.17) * 0.5 for i in range(1024)]
    bars, left_bars, right_bars = spectrum_bars_from_waveform(left, right, 36, sample_rate=48000, state={})
    assert len(bars) == 36
    assert len(left_bars) == 36
    assert len(right_bars) == 36
    assert any(v > 0.0 for v in bars)
    assert left_bars != right_bars


def test_build_audio_snapshot_uses_explicit_stereo_bars():
    from ac_ui.audio_snapshot import build_audio_snapshot

    snap = build_audio_snapshot(
        [0.4] * 8,
        {},
        analysis_bars=[0.4] * 8,
        bars_left=[0.2] * 8,
        bars_right=[0.8] * 8,
        source_kind="pcm",
    )
    assert snap.features.right > snap.features.left
    assert snap.features.width > 0.0
    assert snap.source_kind == "pcm"


def test_build_live_audio_snapshot_derives_bars_from_pcm_when_cava_is_missing():
    from ac_ui.audio_snapshot import build_live_audio_snapshot

    left = [math.sin(i * 0.09) * 0.8 for i in range(1024)]
    right = [math.sin(i * 0.17) * 0.5 for i in range(1024)]
    snap = build_live_audio_snapshot(
        (),
        {},
        waveform_left=left,
        waveform_right=right,
        sample_rate=48000,
        frame_dt=0.016,
        fallback_bar_count=28,
    )
    assert snap.source_kind == "pcm"
    assert len(snap.bars) == 28
    assert len(snap.analysis_bars) == 28
    assert len(snap.bars_left) == 28
    assert len(snap.bars_right) == 28
    assert any(v > 0.0 for v in snap.bars)
    assert snap.features.width > 0.0


def test_build_live_audio_snapshot_prefers_existing_bar_feed():
    from ac_ui.audio_snapshot import build_live_audio_snapshot

    left = [math.sin(i * 0.09) * 0.8 for i in range(256)]
    right = [math.sin(i * 0.17) * 0.5 for i in range(256)]
    snap = build_live_audio_snapshot(
        [0.2, 0.4, 0.6],
        {},
        waveform_left=left,
        waveform_right=right,
        sample_rate=48000,
        frame_dt=0.016,
        fallback_bar_count=24,
    )
    assert snap.source_kind == "cava+pcm"
    assert snap.bars == (0.2, 0.4, 0.6)


def test_build_live_audio_snapshot_can_preserve_pcm_presence_without_copying_waveform():
    from ac_ui.audio_snapshot import build_live_audio_snapshot

    snap = build_live_audio_snapshot(
        [0.2, 0.4, 0.6],
        {},
        waveform_available=True,
        frame_dt=0.016,
    )
    assert snap.source_kind == "cava+pcm"
    assert not snap.has_waveform
    assert snap.bars == (0.2, 0.4, 0.6)


def test_calc_cava_bars_respects_override_and_stereo_evenness(monkeypatch):
    import ac_ui.audio as audio
    import ac_ui.audio_config as audio_config
    import ac_ui.constants as constants

    monkeypatch.setenv("AC_UI_CAVA_BARS", "37")
    monkeypatch.setenv("AC_UI_CAVA_CHANNELS", "stereo")
    try:
        audio_config = importlib.reload(audio_config)
        constants = importlib.reload(constants)
        audio = importlib.reload(audio)
        monkeypatch.setattr(audio.shutil, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))
        assert audio.calc_cava_bars() == 36
        assert "bars = 36" in audio.cava_config_text(audio.calc_cava_bars())
    finally:
        monkeypatch.delenv("AC_UI_CAVA_BARS", raising=False)
        monkeypatch.delenv("AC_UI_CAVA_CHANNELS", raising=False)
        importlib.reload(audio_config)
        importlib.reload(constants)
        importlib.reload(audio)

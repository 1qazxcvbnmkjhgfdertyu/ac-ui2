"""Integration tests using fake backends — no external processes needed."""
import time
import pytest


# ── FakeMpvClient ─────────────────────────────────────────────────────────────

def test_fake_mpv_starts_track():
    from ac_ui.fakes import FakeMpvClient
    client = FakeMpvClient()
    client.start("/music/14-GCN-normal.mp3")
    assert client.is_running
    assert "/music/14-GCN-normal.mp3" in client.started_tracks


def test_fake_mpv_query():
    from ac_ui.fakes import FakeMpvClient
    client = FakeMpvClient()
    assert client.query("time-pos") == 10.0
    assert client.query("duration") == 120.0
    assert client.query("nonexistent") is None


def test_fake_mpv_query_props():
    from ac_ui.fakes import FakeMpvClient
    client = FakeMpvClient()
    result = client.query_props(["time-pos", "volume"])
    assert result["time-pos"] == 10.0
    assert result["volume"] == 80


def test_fake_mpv_command_recorded():
    from ac_ui.fakes import FakeMpvClient
    client = FakeMpvClient()
    client.command(["set_property", "volume", 50])
    assert ["set_property", "volume", 50] in client.commands


def test_fake_mpv_stop():
    from ac_ui.fakes import FakeMpvClient
    client = FakeMpvClient()
    client.start("/music/test.mp3")
    assert client.is_running
    client.stop()
    assert not client.is_running


# ── FakePactlClient ───────────────────────────────────────────────────────────

def test_fake_pactl_list_sinks():
    from ac_ui.fakes import FakePactlClient
    pactl = FakePactlClient(sinks=["sink-a", "sink-b"])
    assert "sink-a" in pactl.list_sinks()
    assert "sink-b" in pactl.list_sinks()


def test_fake_pactl_default_sink():
    from ac_ui.fakes import FakePactlClient
    pactl = FakePactlClient(default_sink="my-sink")
    assert pactl.get_default_sink() == "my-sink"


def test_fake_pactl_set_volume_recorded():
    from ac_ui.fakes import FakePactlClient
    pactl = FakePactlClient()
    pactl.set_loopback_volume("mod-1", "acui-sink", 75)
    assert ("mod-1", "acui-sink", 75) in pactl.volume_calls


def test_fake_pactl_detect_cava_input():
    from ac_ui.fakes import FakePactlClient
    pactl = FakePactlClient(default_sink="alsa_output.pci")
    method, source, mode = pactl.detect_cava_input()
    assert method == "pulse"
    assert source is not None
    assert mode == "auto"


# ── FakeSinkManager ───────────────────────────────────────────────────────────

def test_fake_sink_manager_setup_teardown():
    from ac_ui.fakes import FakeSinkManager
    mgr = FakeSinkManager()
    assert not mgr.active
    mgr.setup(output_sink="alsa-out", sink_name="acui-test")
    assert mgr.active
    assert mgr.sink_name == "acui-test"
    mgr.teardown()
    assert not mgr.active
    assert mgr.setup_calls == 1
    assert mgr.teardown_calls == 1


# ── FakeCavaRuntime ───────────────────────────────────────────────────────────

def test_fake_cava_synthetic_bars():
    from ac_ui.fakes import FakeCavaRuntime
    cava = FakeCavaRuntime(n_bars=32)
    assert not cava.is_running
    cava.start_fake()
    assert cava.is_running
    assert cava.bars is not None
    assert len(cava.bars) == 32
    cava.tick(1.0)
    assert all(0.0 <= b <= 1.0 for b in cava.bars)


def test_fake_cava_stop():
    from ac_ui.fakes import FakeCavaRuntime
    cava = FakeCavaRuntime()
    cava.start_fake()
    cava.stop()
    assert not cava.is_running
    assert cava.bars is None


# ── Now Playing panel renderer ───────────────────────────────────────────────

def _make_np_ctx(**kwargs):
    import ac_ui.colors as _clrs
    from ac_ui.panels.now_playing import NowPlayingContext
    defaults = dict(
        compact=False,
        max_width=60,
        current_track="/music/14-GCN-normal.mp3",
        current_track_hour=14,
        hour=14,
        tpos=30.0,
        dur=180.0,
        showing_chime=False,
        chime_kind=None,
        repeat_current=False,
        track_pick_reason="weighted random",
        background_mode=False,
        muted=False,
        game_label="GCN",
        variant="normal",
        vis_mode="bars",
        display_vol=80,
        vol_flash_str="",
        remaining=1800,
        pulse_bright=True,
        title_art=[],
        title_art_colored=False,
        tod_grad=_clrs._active_tod_grad,
    )
    defaults.update(kwargs)
    return NowPlayingContext(**defaults)


def test_now_playing_full_mode():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx()
    plain, color = render(ctx)
    assert any("GCN" in s for s in plain)
    assert any("14h" in s for s in plain)
    assert any("Until" in s for s in plain)
    assert len(plain) == len(color)


def test_now_playing_compact_mode():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx(compact=True)
    plain, color = render(ctx)
    assert any("GCN" in s for s in plain)
    assert any("Until" in s for s in plain)
    assert len(plain) == len(color)


def test_now_playing_chime():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx(showing_chime=True, chime_kind="town tune", current_track=None)
    plain, color = render(ctx)
    assert any("town tune" in s for s in plain)


def test_now_playing_no_track():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx(current_track=None, tpos=None, dur=None)
    plain, color = render(ctx)
    assert any("no track" in s for s in plain)


def test_now_playing_muted_pinned():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx(muted=True, repeat_current=True)
    plain, color = render(ctx)
    assert any("GCN" in s for s in plain)
    assert any("Until" in s for s in plain)


def test_now_playing_pick_reason():
    from ac_ui.panels.now_playing import render
    ctx = _make_np_ctx(track_pick_reason="hour match")
    plain, color = render(ctx)
    assert any("hour match" in s for s in plain)


# ── Panel renderers (pure functions — no fakes needed) ────────────────────────

def test_history_panel_empty():
    import ac_ui.colors as _clrs
    from ac_ui.panels.history import render
    plain, color = render([], max_width=40, tod_grad=_clrs._active_tod_grad)
    assert plain[0] == "Recently played"
    assert "(none yet)" in plain[1]


def test_history_panel_entries():
    import ac_ui.colors as _clrs
    from ac_ui.panels.history import render
    tracks = ["14-GCN-normal.mp3", "15-WW-rainy.flac"]
    plain, color = render(tracks, max_width=40, tod_grad=_clrs._active_tod_grad)
    assert len(plain) == 3  # header + 2 entries
    assert "GCN" in plain[1]


def test_up_next_panel_empty():
    import ac_ui.colors as _clrs
    from ac_ui.panels.up_next import render
    plain, color = render([], max_width=40, tod_grad=_clrs._active_tod_grad)
    assert "no candidates" in plain[-1]


def test_up_next_panel_truncation():
    import ac_ui.colors as _clrs
    from ac_ui.panels.up_next import render
    tracks = [f"14-GCN-variant{i}.mp3" for i in range(10)]
    plain, color = render(tracks, max_width=40, tod_grad=_clrs._active_tod_grad, max_shown=3)
    # header + 3 shown + overflow indicator
    assert len(plain) == 5
    assert "more" in plain[-1]


# ── Diagnostics ───────────────────────────────────────────────────────────────

def test_diagnostics_record_and_retrieve():
    from ac_ui import diagnostics
    diagnostics.clear()
    diagnostics.warn("test", "something went wrong")
    diagnostics.error("audio", "pactl failed", exc=RuntimeError("oops"))
    recent = diagnostics.get_recent(10)
    assert len(recent) == 2
    assert recent[0].source == "test"
    assert recent[1].source == "audio"
    assert recent[1].exc is not None


def test_diagnostics_level_filter():
    from ac_ui import diagnostics
    diagnostics.clear()
    diagnostics.info("x", "info msg")
    diagnostics.warn("x", "warn msg")
    diagnostics.error("x", "error msg")
    warns = diagnostics.get_recent(level=diagnostics.Level.WARN)
    assert len(warns) == 1
    assert warns[0].message == "warn msg"


def test_diagnostics_counts():
    from ac_ui import diagnostics
    diagnostics.clear()
    for _ in range(3):
        diagnostics.warn("src", "w")
    for _ in range(2):
        diagnostics.error("src", "e")
    c = diagnostics.counts()
    assert c["warn"] == 3
    assert c["error"] == 2


# ── Help panel renderer ──────────────────────────────────────────────────────

def test_help_panel_renders_content():
    import ac_ui.colors as _clrs
    from ac_ui.panels.help import render
    base = ["Help", "[n] next track", "[m] mute/unmute"]
    plain, color = render(base, "alsa_output.pci", max_width=60, max_rows=20, tod_grad=_clrs._active_tod_grad)
    assert plain is not None
    assert any("next track" in s for s in plain)
    assert any("alsa_output.pci" in s for s in plain)
    assert len(plain) == len(color)


def test_help_panel_empty_budget():
    import ac_ui.colors as _clrs
    from ac_ui.panels.help import render
    plain, color = render(["Help", "some text"], "sink", max_width=60, max_rows=0, tod_grad=_clrs._active_tod_grad)
    assert plain is None
    assert color is None


# ── Stats panel renderer ─────────────────────────────────────────────────────

def test_stats_panel_empty_data():
    import ac_ui.colors as _clrs
    from ac_ui.panels.stats import render
    data = {"total_listen_seconds": 0, "hour_buckets": [0] * 24}
    plain, color = render(data, 0.0, max_width=40, hour=14, tod_grad=_clrs._active_tod_grad)
    assert len(plain) == 8  # 5 text lines + hist + marker + axis
    assert "Total listening" in plain[0]
    assert "0s" in plain[0]


def test_stats_panel_with_data():
    import ac_ui.colors as _clrs
    from ac_ui.panels.stats import render
    hb = [0] * 24
    hb[14] = 3600  # 1 hour at 14:00
    hb[9] = 1800   # 30 min at 09:00
    data = {"total_listen_seconds": 5400, "hour_buckets": hb}
    plain, color = render(data, 300.0, max_width=40, hour=14, tod_grad=_clrs._active_tod_grad)
    assert "1h" in plain[0]  # total_sec = 5400 + 300 = 5700 → "1h ..."
    assert "14:00" in plain[2]  # top hours includes 14:00
    assert len(plain) == len(color)


# ── UIState dataclass ─────────────────────────────────────────────────────────

def test_ui_state_round_trip():
    from ac_ui.state import UIState
    original = UIState(output_vol=65, muted=True, theme="forest", vis_mode="peaks")
    d = original.to_dict()
    restored = UIState.from_dict(d)
    assert restored.output_vol == 65
    assert restored.muted is True
    assert restored.theme == "forest"
    assert restored.vis_mode == "peaks"


def test_ui_state_from_dict_defaults():
    from ac_ui.state import UIState
    state = UIState.from_dict({})
    assert state.output_vol == 80
    assert state.muted is False
    assert state.theme == "default"


# ── persist.py versioning ─────────────────────────────────────────────────────

def test_ui_state_version_written(tmp_path, monkeypatch):
    import json
    import ac_ui.persist as P
    from ac_ui.persist import save_ui_state, load_ui_state, UI_STATE_VERSION
    state_path = str(tmp_path / "state.json")
    monkeypatch.setattr(P, "UI_STATE_PATH", state_path)

    state = load_ui_state()
    save_ui_state(state)

    with open(state_path) as f:
        saved = json.load(f)
    assert saved.get("_version") == UI_STATE_VERSION


def test_ui_state_v1_migration(tmp_path, monkeypatch):
    """A v1 file with layout_preset should be migrated to nested layout dict."""
    import json
    import ac_ui.persist as P
    from ac_ui.persist import load_ui_state
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"_version": 1, "layout_preset": "stacked", "output_vol": 70}))
    monkeypatch.setattr(P, "UI_STATE_PATH", str(path))

    state = load_ui_state()
    assert state["output_vol"] == 70
    assert isinstance(state["layout"], dict)

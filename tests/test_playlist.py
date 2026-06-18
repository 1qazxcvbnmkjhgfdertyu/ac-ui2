"""Playlist definition / runtime queue tests.

These cover the split between a "playlist definition" (weighted entries on disk)
and the "runtime queue" (shuffled, weight-expanded paths used for playback).
"""
import json
import os

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_tracks(tmp_path, n=3):
    """Create n real audio files and return their absolute paths."""
    paths = []
    for i in range(n):
        p = tmp_path / f"14-GCN-track{i}.mp3"
        p.write_bytes(b"\x00")
        paths.append(str(p))
    return paths


def _write_acpl(path, name, entries):
    """entries: list of (file_path, weight)."""
    data = {"name": name, "tracks": [{"file": f, "weight": w} for f, w in entries]}
    path.write_text(json.dumps(data))
    return str(path)


# ── 1. Importing an .acpl preserves per-track weight ────────────────────────────

def test_acpl_import_preserves_weight(tmp_path):
    from ac_ui.tracks import load_playlist_source, load_acpl_full

    t = _make_tracks(tmp_path, 3)
    acpl = _write_acpl(tmp_path / "pl.acpl", "Weighted",
                       [(t[0], 5), (t[1], 1), (t[2], 3)])

    src = load_playlist_source(acpl)
    weights = {os.path.basename(e.path): e.weight for e in src.entries}
    assert weights[os.path.basename(t[0])] == 5
    assert weights[os.path.basename(t[1])] == 1
    assert weights[os.path.basename(t[2])] == 3

    # The editor import path uses load_acpl_full → same weights survive.
    _name, dict_entries = load_acpl_full(acpl)
    dict_weights = {os.path.basename(e["file"]): e["weight"] for e in dict_entries}
    assert dict_weights == weights


def test_build_free_play_queue_expands_weights(tmp_path):
    from ac_ui.tracks import load_playlist_source, build_free_play_queue
    import random

    t = _make_tracks(tmp_path, 2)
    acpl = _write_acpl(tmp_path / "pl.acpl", "W", [(t[0], 4), (t[1], 1)])
    src = load_playlist_source(acpl)
    queue = build_free_play_queue(src.entries, rng=random.Random(0))
    assert queue.count(t[0]) == 4
    assert queue.count(t[1]) == 1


# ── 2. Enter on Up Next reorders the real fp_playlist ───────────────────────────

def test_free_play_candidate_carries_queue_index(tmp_path):
    from ac_ui.tracks import free_play_next_candidates

    queue = [f"/m/{i}.mp3" for i in range(6)]
    cands = free_play_next_candidates(queue, fp_idx=2, queue_size=3)
    assert [c.queue_index for c in cands] == [2, 3, 4]
    assert cands[0].path == queue[2]


def test_enter_on_up_next_reorders_queue():
    from ac_ui.tracks import move_queue_item_to_next

    queue = ["a", "b", "c", "d", "e"]
    fp_idx = 1  # next track is "b"
    # Up Next shows b(1), c(2), d(3); user selects d (queue_index 3).
    new_idx = move_queue_item_to_next(queue, fp_idx, 3)
    # "d" must actually become the next track in the real queue.
    assert queue[new_idx] == "d"
    assert queue == ["a", "d", "b", "c", "e"]


def test_move_queue_item_wrapped_index():
    from ac_ui.tracks import move_queue_item_to_next

    queue = ["a", "b", "c"]
    fp_idx = 2  # upcoming order wraps: c(2), a(0), b(1)
    new_idx = move_queue_item_to_next(queue, fp_idx, 0)  # pick "a"
    assert queue[new_idx] == "a"


# ── 3. Saving the queue preserves weights and respects fp_idx ───────────────────

def test_save_queue_preserves_weights_and_position(tmp_path):
    from ac_ui.tracks import save_queue_acpl, load_playlist_source

    t = _make_tracks(tmp_path, 3)
    # Runtime queue: t0 played already (before idx), then t1 x3 and t2 x1 upcoming.
    queue = [t[0], t[1], t[1], t[2], t[1]]
    fp_idx = 1  # everything from index 1 onward is "upcoming"

    dest = tmp_path / "saved.acpl"
    assert save_queue_acpl(str(dest), "Saved", queue, fp_idx)

    src = load_playlist_source(str(dest))
    weights = {os.path.basename(e.path): e.weight for e in src.entries}
    # t0 was before fp_idx → excluded; t1 occurs 3x → weight 3; t2 once → weight 1.
    assert os.path.basename(t[0]) not in weights
    assert weights[os.path.basename(t[1])] == 3
    assert weights[os.path.basename(t[2])] == 1


# ── 4. History replay works for a free-play track outside MUSIC_DIR ─────────────

def test_history_stores_full_path_outside_music_dir(tmp_path):
    from collections import deque
    from ac_ui.tracks import update_history

    outside = str(tmp_path / "elsewhere" / "99-XYZ-tune.mp3")
    history = deque(maxlen=6)
    recent = deque(maxlen=6)
    update_history(outside, history, recent)

    # The full path is stored so replay opens the exact file (not a guessed
    # MUSIC_DIR path that would not exist).
    assert history[-1] == outside
    assert os.path.dirname(history[-1]) == os.path.dirname(outside)


def test_history_panel_labels_from_path(tmp_path):
    import ac_ui.colors as _clrs
    from ac_ui.panels.history import render

    path = str(tmp_path / "sub" / "14-GCN-rainy.mp3")
    plain, _ = render([path], max_width=40, tod_grad=_clrs._active_tod_grad)
    assert "GCN" in plain[0]
    assert "rainy" in plain[0]


# ── 5. A malformed playlist records a diagnostic and surfaces an error state ────

def test_malformed_playlist_records_diagnostic(tmp_path):
    from ac_ui import diagnostics
    from ac_ui.tracks import load_playlist_source

    diagnostics.clear()
    bad = tmp_path / "broken.acpl"
    bad.write_text("{ this is not valid json ]")

    src = load_playlist_source(str(bad))
    # Error state, not a silent empty playlist.
    assert src.warnings, "malformed playlist should produce a warning"
    assert not src.ok
    assert src.entries == []

    errors = diagnostics.get_recent(level=diagnostics.Level.ERROR)
    assert any("malformed" in d.message for d in errors)


def test_missing_files_counted_not_silent(tmp_path):
    from ac_ui.tracks import load_playlist_source

    # Reference files that don't exist on disk.
    acpl = tmp_path / "missing.acpl"
    acpl.write_text(json.dumps({"name": "Gone", "tracks": [
        {"file": "/nope/a.mp3", "weight": 2},
        {"file": "/nope/b.mp3", "weight": 1},
    ]}))
    src = load_playlist_source(str(acpl))
    assert src.missing == 2
    assert not src.ok          # parsed fine, but nothing is playable
    assert len(src.entries) == 2  # entries still tracked (for diagnostics/editing)

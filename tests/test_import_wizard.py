"""Import wizard: browse model, background import, overlay flow, renderers.
Always targets a temp dir — never the real library."""
import os
import time

from ac_ui import import_wizard as W


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_browse_entries(tmp_path):
    _touch(str(tmp_path / "loose.mp3"))
    _touch(str(tmp_path / "Album" / "a.flac"))
    _touch(str(tmp_path / "Album" / "b.opus"))
    _touch(str(tmp_path / "notes.txt"))
    entries = W.browse_entries(str(tmp_path))
    kinds = [e.kind for e in entries]
    assert kinds[0] == "import"             # import action first
    assert entries[0].count == 3            # loose + 2 in Album (recursive)
    assert "up" in kinds and "dir" in kinds
    album = next(e for e in entries if e.kind == "dir")
    assert album.label == "Album/" and album.count == 2


def test_count_audio_recursive(tmp_path):
    for i in range(5):
        _touch(str(tmp_path / f"d{i}" / f"s{i}.mp3"))
    assert W.count_audio_recursive(str(tmp_path)) == 5
    assert W.count_audio_recursive(str(tmp_path), cap=3) == 3


def _run_bg(sources, dest):
    job = W.BackgroundImport(sources=sources, dest_dir=str(dest)).start()
    for _ in range(200):
        snap = job.snapshot()
        if snap["phase"] == "done":
            return snap
        time.sleep(0.02)
    raise AssertionError("import did not finish")


def test_background_import_completes(tmp_path):
    src = tmp_path / "src"
    _touch(str(src / "a.mp3"), b"aaa")
    _touch(str(src / "b.flac"), b"bbb")
    dest = tmp_path / "lib"
    snap = _run_bg([str(src)], dest)
    assert snap["result"].imported == 2
    assert sorted(os.listdir(dest)) == ["a.mp3", "b.flac"]


def test_overlay_flow_to_freeplay(tmp_path, monkeypatch):
    # Point the overlay's library at a temp dir so we don't touch the real one.
    import ac_ui.overlay as O
    lib = tmp_path / "library"
    monkeypatch.setattr(O, "LIBRARY_DIR", str(lib))
    src = tmp_path / "music"
    _touch(str(src / "x.mp3"), b"xx")
    ov = O.ImportOverlay(start_dir=str(src))
    assert ov.entries[0].kind == "import"
    ov.selected = 0
    assert ov.handle("\r") is False           # start import (stays open)
    assert ov.state == "running"
    for _ in range(200):
        ov.build(80, 30)
        if ov.state == "done":
            break
        time.sleep(0.02)
    assert ov.state == "done" and ov.done_result.imported == 1
    assert ov.handle("\r") is True            # confirm -> closes
    assert ov.result == str(lib)              # free-play target


def test_render_helpers_smoke(tmp_path):
    _touch(str(tmp_path / "a.mp3"))
    entries = W.browse_entries(str(tmp_path))
    p, c = W.build_browse_lines(str(tmp_path), entries, 0, 50, 10)
    assert len(p) == len(c) and any("Import this folder" in ln for ln in p)
    pp, _ = W.build_progress_lines(3, 10, "Some Song", 50)
    assert any("3/10" in ln for ln in pp)
    from ac_ui.importer import ImportResult
    r = ImportResult(imported=5, transcoded=2)
    dp, _ = W.build_done_lines(r, 50)
    assert any("5 added" in ln for ln in dp)

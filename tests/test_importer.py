"""Music import engine: discovery, naming, plan (copy/transcode/dedup), execute."""
import os

from ac_ui import importer


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_find_audio_recursive_and_filtered(tmp_path):
    _touch(str(tmp_path / "a.mp3"))
    _touch(str(tmp_path / "sub" / "b.flac"))
    _touch(str(tmp_path / "sub" / "c.opus"))
    _touch(str(tmp_path / "notes.txt"))          # ignored
    _touch(str(tmp_path / "cover.jpg"))           # ignored
    found = importer.find_audio_files([str(tmp_path)])
    assert [os.path.basename(p) for p in found] == ["a.mp3", "b.flac", "c.opus"]
    # de-dup across overlapping inputs
    again = importer.find_audio_files([str(tmp_path), str(tmp_path / "a.mp3")])
    assert len(again) == 3


def test_sanitize_and_display_name(tmp_path):
    assert importer.sanitize_name("AC/DC: Back?") == "AC DC Back"
    assert importer.sanitize_name("   spaced   out  ") == "spaced out"
    assert importer.display_name({"artist": "Toby Fox", "title": "Megalovania"}, "x.mp3") == "Toby Fox - Megalovania"
    assert importer.display_name({"title": "Solo"}, "x.mp3") == "Solo"
    assert importer.display_name({}, "/m/Some File.opus") == "Some File"


def test_plan_copy_vs_transcode_and_dedup(tmp_path):
    src = tmp_path / "src"
    _touch(str(src / "song.opus"))    # playable -> copy
    _touch(str(src / "tune.wma"))     # not playable -> transcode
    _touch(str(src / "keep.flac"))    # playable -> copy
    dest = tmp_path / "lib"
    dest.mkdir()

    tags = {
        "song.opus": {"artist": "A", "title": "One"},
        "tune.wma": {"artist": "B", "title": "Two"},
        "keep.flac": {"title": "Three"},
    }
    plan = importer.plan_import(
        [str(src)], str(dest),
        read_tags_fn=lambda p: tags[os.path.basename(p)],
    )
    by_name = {it.dest_name: it for it in plan.items}
    assert "A - One.opus" in by_name and by_name["A - One.opus"].action == "copy"
    assert "B - Two.mp3" in by_name and by_name["B - Two.mp3"].action == "transcode"
    assert "Three.flac" in by_name
    assert plan.total_found == 3

    # Pre-seed the library with one -> it should be skipped as a duplicate.
    _touch(str(dest / "A - One.opus"))
    plan2 = importer.plan_import(
        [str(src)], str(dest),
        read_tags_fn=lambda p: tags[os.path.basename(p)],
    )
    assert plan2.duplicates == 1
    assert all(it.dest_name != "A - One.opus" for it in plan2.items)


def test_plan_unique_names_within_batch(tmp_path):
    src = tmp_path / "src"
    _touch(str(src / "1.mp3"))
    _touch(str(src / "2.mp3"))
    plan = importer.plan_import(
        [str(src)], str(tmp_path / "lib"),
        read_tags_fn=lambda p: {"artist": "X", "title": "Same"},
    )
    names = sorted(it.dest_name for it in plan.items)
    assert names == ["X - Same (2).mp3", "X - Same.mp3"]


def test_execute_copies_and_reports(tmp_path):
    src = tmp_path / "src"
    _touch(str(src / "a.mp3"), b"hello")
    _touch(str(src / "b.flac"), b"world")
    dest = tmp_path / "lib"
    plan = importer.plan_import(
        [str(src)], str(dest),
        read_tags_fn=lambda p: {"title": os.path.splitext(os.path.basename(p))[0]},
    )
    seen = []
    res = importer.execute_import(plan, progress_cb=lambda d, t, it: seen.append((d, t)))
    assert res.imported == 2 and res.failed == 0
    assert sorted(os.listdir(dest)) == ["a.mp3", "b.flac"]
    assert (open(dest / "a.mp3", "rb").read()) == b"hello"
    assert seen[0][1] == 2 and seen[-1] == (2, 2)   # progress ran, ended at total
    assert not any(n.endswith(".part") for n in os.listdir(dest))   # no temp left


def test_execute_transcode_error_is_contained(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _touch(str(src / "x.wma"))
    dest = tmp_path / "lib"
    plan = importer.plan_import(
        [str(src)], str(dest), read_tags_fn=lambda p: {"title": "X"},
    )

    def boom(s, d):
        raise RuntimeError("no ffmpeg")
    monkeypatch.setattr(importer, "_transcode", boom)
    res = importer.execute_import(plan)
    assert res.failed == 1 and res.imported == 0
    assert res.errors and "x.wma" in res.errors[0]
    assert not os.path.isdir(dest) or os.listdir(dest) == []   # nothing partial left

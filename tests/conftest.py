"""Shared fixtures for ac-ui smoke tests."""
import os
import sys
import types
import pytest

# Ensure the repo root is on sys.path regardless of how pytest is invoked
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture(autouse=True)
def _no_tty_exit(monkeypatch):
    """Prevent sys.exit caused by stdin-not-a-tty check."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)


@pytest.fixture()
def fake_music_dir(tmp_path, monkeypatch):
    """Point MUSIC_DIR at a temp directory so file-system checks pass."""
    import ac_ui.constants as C
    monkeypatch.setattr(C, "MUSIC_DIR", str(tmp_path))
    # Also patch os.path.isdir for the constant itself
    real_isdir = os.path.isdir
    monkeypatch.setattr(
        os.path, "isdir",
        lambda p: True if p == str(tmp_path) else real_isdir(p),
    )
    return tmp_path


@pytest.fixture()
def fake_terminal(monkeypatch):
    """Stub out shutil.get_terminal_size to return a fixed 120×40 terminal."""
    import shutil
    Size = types.SimpleNamespace(columns=120, lines=40)
    monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=(80, 24): Size)
    return Size

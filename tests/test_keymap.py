"""Tests for user-configurable key remapping (keymap.py)."""
from ac_ui.keymap import build_key_aliases, _normalize_key


def test_normalize_friendly_names():
    assert _normalize_key("space") == " "
    assert _normalize_key("tab") == "\t"
    assert _normalize_key("enter") == "\r"
    assert _normalize_key("up") == "UP"
    assert _normalize_key("pageup") == "PAGEUP"
    assert _normalize_key("esc") == "ESC"


def test_normalize_ctrl_notation():
    assert _normalize_key("ctrl+p") == "\x10"
    assert _normalize_key("^p") == "\x10"


def test_normalize_single_char_and_reject_unknown():
    assert _normalize_key("x") == "x"
    assert _normalize_key("nope") is None
    assert _normalize_key("") is None


def test_build_aliases_maps_to_action_primary_key():
    # 'next' primary key is 'n'; binding 'right' and 'l' should both alias to 'n'.
    aliases = build_key_aliases({"bindings": {"next": ["right", "l"]}})
    assert aliases["RIGHT"] == "n"
    assert aliases["l"] == "n"


def test_build_aliases_accepts_bare_dict_and_string_value():
    aliases = build_key_aliases({"quit": "x"})
    assert aliases["x"] == "q"


def test_build_aliases_skips_unknown_action_and_bad_key():
    aliases = build_key_aliases({"bindings": {
        "not_an_action": ["z"],
        "mute": ["bogusname"],   # unrecognised key token -> skipped
    }})
    assert "z" not in aliases
    assert aliases == {}  # nothing valid survived


def test_build_aliases_handles_non_dict():
    assert build_key_aliases(None) == {}
    assert build_key_aliases({"bindings": []}) == {}

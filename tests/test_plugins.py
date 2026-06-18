"""Tests for the plugin system (plugins.py)."""
import os

from ac_ui.plugins import (
    PluginRegistry, PluginContext, load_plugins,
)


def test_register_and_run_command():
    reg = PluginRegistry()
    seen = {}

    def handler(ctx):
        seen["track"] = ctx.current_track
        ctx.notify("hello")

    reg.register_command("W", "weather", "[W] weather", handler)
    assert "W" in reg.command_keys()

    notes = []
    ctx = PluginContext(current_track="/x/05-KK-rainy.mp3", notify=notes.append)
    assert reg.run("W", ctx) is True
    assert seen["track"] == "/x/05-KK-rainy.mp3"
    assert notes == ["hello"]


def test_run_unknown_key_returns_false():
    reg = PluginRegistry()
    assert reg.run("Z", PluginContext()) is False


def test_handler_exception_is_contained():
    reg = PluginRegistry()

    def boom(ctx):
        raise RuntimeError("nope")

    reg.register_command("B", "boom", "", boom)
    # Should not raise — plugin errors are logged, not propagated.
    assert reg.run("B", PluginContext()) is True


def test_invalid_registration_ignored():
    reg = PluginRegistry()
    reg.register_command("", "noop", "", lambda c: None)   # empty key
    reg.register_command("K", "bad", "", None)             # non-callable
    assert reg.command_keys() == frozenset()


def test_load_plugins_from_dir(tmp_path):
    reg = PluginRegistry()
    plugin = tmp_path / "sample.py"
    plugin.write_text(
        "import ac_ui.plugins as plug\n"
        "@plug.command(key='G', label='greet', help='[G] greet')\n"
        "def greet(ctx):\n"
        "    ctx.notify('hi')\n"
    )
    # The decorator registers into the global REGISTRY; verify load succeeds.
    import ac_ui.plugins as plug
    plug.REGISTRY.clear()
    n = load_plugins(str(tmp_path))
    assert n == 1
    assert "G" in plug.REGISTRY.command_keys()
    plug.REGISTRY.clear()


def test_load_plugins_missing_dir_is_zero():
    assert load_plugins("/no/such/dir/hopefully") == 0


def test_load_plugins_skips_broken_file(tmp_path):
    (tmp_path / "broken.py").write_text("this is not valid python !!!\n")
    (tmp_path / "_private.py").write_text("raise Exception('should be skipped')\n")
    # broken.py counts as an attempted-but-failed load (0 loaded); _private skipped.
    assert load_plugins(str(tmp_path)) == 0

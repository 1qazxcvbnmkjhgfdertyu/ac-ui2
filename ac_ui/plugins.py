"""Lightweight plugin system (Section 6).

Plugins are plain Python files dropped in ``$AC_UI_PLUGINS`` or
``~/.config/ac-ui/plugins/``.  Each file is executed once at startup with the
plugin API available via ``import ac_ui.plugins as plug``; it registers commands
by calling :func:`command` (or ``REGISTRY.register_command``).

A registered command gets a key, a label/help string, and a handler called with
a :class:`PluginContext` — a *stable, curated* surface onto the running player
so plugins never reach into ui.py internals directly::

    import ac_ui.plugins as plug

    @plug.command(key="W", label="weather", help="[W] pick music by weather")
    def weather(ctx):
        ctx.notify("It's sunny — switching to KK!")

Command keys are merged into the command palette and help overlay, and
dispatched from the main loop.  Panel plugins are registered the same way but
live rendering into the fixed 4-panel layout is not wired yet (documented
limitation), so the registry stores them for future use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from ac_ui import diagnostics


@dataclass
class PluginContext:
    """Curated, stable API handed to command handlers.

    Attributes are populated by ui.py each time a command fires.  Plugins should
    rely only on the documented fields here, not on ui.py internals.
    """
    current_track: str | None = None
    term_cols: int = 80
    term_rows: int = 24
    # Callables wired up by ui.py:
    notify: Callable[[str], None] = lambda msg: None          # transient banner/toast
    play_track: Callable[[str], bool] = lambda path: False     # play a specific file
    extras: dict[str, Any] = field(default_factory=dict)       # room to grow


@dataclass(frozen=True)
class CommandPlugin:
    action_id: str
    key: str
    label: str
    help: str
    handler: Callable[[PluginContext], None]


@dataclass(frozen=True)
class PanelPlugin:
    panel_id: str
    title: str
    render: Callable[[Any], tuple]


class PluginRegistry:
    def __init__(self):
        self.commands: dict[str, CommandPlugin] = {}   # keyed by trigger key
        self.panels: dict[str, PanelPlugin] = {}

    def register_command(self, key, label, help, handler, action_id=None):
        if not key or not callable(handler):
            diagnostics.warn("plugins", f"ignoring invalid command '{label}'")
            return
        action_id = action_id or f"plugin:{label}".lower().replace(" ", "_")
        if key in self.commands:
            diagnostics.warn("plugins", f"key '{key}' already bound; overriding")
        self.commands[key] = CommandPlugin(action_id, key, label, help or label, handler)

    def register_panel(self, panel_id, title, render):
        if not panel_id or not callable(render):
            diagnostics.warn("plugins", f"ignoring invalid panel '{panel_id}'")
            return
        self.panels[panel_id] = PanelPlugin(panel_id, title, render)

    def command_keys(self) -> frozenset:
        return frozenset(self.commands)

    def run(self, key, ctx: PluginContext) -> bool:
        cmd = self.commands.get(key)
        if not cmd:
            return False
        try:
            cmd.handler(ctx)
        except Exception as e:  # plugins are untrusted — never crash the UI
            diagnostics.error("plugins", f"command '{cmd.label}' raised: {e}", e)
        return True

    def clear(self):
        self.commands.clear()
        self.panels.clear()


REGISTRY = PluginRegistry()


def command(key, label, help=None, action_id=None):
    """Decorator: register the wrapped function as a command plugin."""
    def deco(fn):
        REGISTRY.register_command(key, label, help, fn, action_id=action_id)
        return fn
    return deco


def panel(panel_id, title):
    """Decorator: register the wrapped function as a panel renderer plugin."""
    def deco(fn):
        REGISTRY.register_panel(panel_id, title, fn)
        return fn
    return deco


def default_plugins_dir() -> str:
    env = os.environ.get("AC_UI_PLUGINS")
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ac-ui", "plugins")


def load_plugins(directory: str | None = None, registry: PluginRegistry | None = None) -> int:
    """Execute every ``*.py`` in the plugins dir. Returns the count loaded.

    Each file runs in its own namespace with the plugin API importable. Errors
    in one plugin are logged and skipped; they never abort startup.
    """
    if directory is None:
        directory = default_plugins_dir()
    if registry is None:
        registry = REGISTRY
    if not os.path.isdir(directory):
        return 0
    loaded = 0
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            code = compile(src, path, "exec")
            exec(code, {"__name__": f"ac_ui_plugin_{name[:-3]}", "__file__": path})
            loaded += 1
        except Exception as e:
            diagnostics.error("plugins", f"failed to load {name}: {e}", e)
    return loaded

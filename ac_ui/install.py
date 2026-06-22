"""Install-time diagnostics and distro-specific dependency hints."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass

from ac_ui.constants import CAVA_BIN, MPV, MUSIC_DIR


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str


_CORE_PACKAGES: dict[str, tuple[str, ...]] = {
    "apt-get": ("python3", "python3-venv", "python3-pip", "mpv", "cava", "pulseaudio-utils"),
    "dnf": ("python3", "python3-pip", "mpv", "cava", "pulseaudio-utils"),
    "yum": ("python3", "python3-pip", "mpv", "cava", "pulseaudio-utils"),
    "pacman": ("python", "python-pip", "mpv", "cava", "libpulse"),
    "zypper": ("python3", "python3-pip", "python3-virtualenv", "mpv", "cava", "pulseaudio-utils"),
    "xbps-install": ("python3", "python3-pip", "mpv", "cava", "pulseaudio-utils"),
    "apk": ("python3", "py3-pip", "mpv", "cava", "pulseaudio-utils"),
}

_OPTIONAL_PACKAGES: dict[str, tuple[str, ...]] = {
    "apt-get": ("figlet", "lolcat", "fluidsynth", "timidity", "fluid-soundfont-gm"),
    "dnf": ("figlet", "lolcat", "fluidsynth", "timidity++", "fluid-soundfont-gm"),
    "yum": ("figlet", "lolcat", "fluidsynth", "timidity++", "fluid-soundfont-gm"),
    "pacman": ("figlet", "lolcat", "fluidsynth", "timidity++", "soundfont-fluid"),
    "zypper": ("figlet", "lolcat", "fluidsynth", "timidity", "fluid-soundfont"),
    "xbps-install": ("figlet", "lolcat", "fluidsynth", "timidity"),
    "apk": ("figlet", "lolcat", "fluidsynth", "timidity"),
}

_INSTALL_PREFIX: dict[str, str] = {
    "apt-get": "sudo apt-get install -y",
    "dnf": "sudo dnf install -y",
    "yum": "sudo yum install -y",
    "pacman": "sudo pacman -S --needed",
    "zypper": "sudo zypper install -y",
    "xbps-install": "sudo xbps-install -Sy",
    "apk": "sudo apk add",
}


def _command_available(command: str, which=None) -> bool:
    which = which or shutil.which
    text = os.path.expanduser(str(command or "").strip())
    if not text:
        return False
    if os.path.isabs(text) or os.sep in text:
        if os.path.isfile(text) and os.access(text, os.X_OK):
            return True
        return which(text) is not None
    return which(text) is not None


def parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return parse_os_release(fh.read())
    except OSError:
        return {}


def detect_package_manager(which=None) -> str | None:
    which = which or shutil.which
    for cmd in ("apt-get", "dnf", "yum", "pacman", "zypper", "xbps-install", "apk"):
        if which(cmd):
            return cmd
    return None


def package_names(manager: str | None, include_optional: bool = False) -> tuple[str, ...]:
    if not manager:
        return ()
    base = list(_CORE_PACKAGES.get(manager, ()))
    if include_optional:
        for pkg in _OPTIONAL_PACKAGES.get(manager, ()):
            if pkg not in base:
                base.append(pkg)
    return tuple(base)


def install_commands(manager: str | None, include_optional: bool = False) -> list[str]:
    packages = package_names(manager, include_optional=include_optional)
    prefix = _INSTALL_PREFIX.get(manager or "")
    if not packages or not prefix:
        return []
    if manager == "apt-get":
        return ["sudo apt-get update", f"{prefix} {' '.join(packages)}"]
    return [f"{prefix} {' '.join(packages)}"]


def collect_checks(which=None, version_info=None, env=None) -> list[CheckResult]:
    which = which or shutil.which
    env_provided = env is not None
    env = os.environ if env is None else env
    version_info = version_info or sys.version_info
    py_ok = tuple(version_info) >= (3, 11)
    mpv_default = "mpv" if env_provided else MPV
    cava_default = "cava" if env_provided else CAVA_BIN
    mpv_cmd = (env.get("AC_UI_MPV", mpv_default) or "mpv").strip() or "mpv"
    cava_cmd = (env.get("AC_UI_CAVA_BIN", cava_default) or "cava").strip() or "cava"
    checks = [
        CheckResult("python", py_ok, True, f"{sys.version.split()[0]} (need 3.11+)"),
        CheckResult("mpv", _command_available(mpv_cmd, which), True, mpv_cmd),
        CheckResult("cava", _command_available(cava_cmd, which), True, cava_cmd),
        CheckResult("pactl", _command_available("pactl", which), True, "PulseAudio / PipeWire control"),
        CheckResult(
            "pcm-capture",
            _command_available("pw-record", which) or _command_available("parec", which),
            False,
            "pw-record or parec",
        ),
        CheckResult(
            "midi-preview",
            _command_available("fluidsynth", which) or _command_available("timidity", which),
            False,
            "fluidsynth or timidity",
        ),
        CheckResult("figlet", _command_available("figlet", which), False, "title-art helper"),
        CheckResult("lolcat", _command_available("lolcat", which), False, "optional colorized title-art helper"),
    ]
    return checks


def doctor_data(which=None, version_info=None, env=None, os_release=None) -> dict:
    which = which or shutil.which
    env = env or os.environ
    checks = collect_checks(which=which, version_info=version_info, env=env)
    manager = detect_package_manager(which=which)
    cava_override = str(env.get("AC_UI_CAVA_BIN", "") or "").strip()
    if os_release is None:
        os_release = read_os_release()
    required_ok = all(item.ok for item in checks if item.required)
    home_local_bin = os.path.expanduser("~/.local/bin")
    path_entries = [p for p in str(env.get("PATH", "")).split(os.pathsep) if p]
    notes = [
        f"music dir: {MUSIC_DIR} ({'present' if os.path.isdir(MUSIC_DIR) else 'missing'})",
        f"user bin dir: {home_local_bin} ({'on PATH' if home_local_bin in path_entries else 'not on PATH'})",
    ]
    if cava_override:
        notes.append(f"custom cava binary: {cava_override}")
    if not required_ok and not checks[0].ok:
        notes.append("Python is older than 3.11; install a newer Python before installing ac-ui.")
    return {
        "ok": required_ok,
        "package_manager": manager,
        "os_release": os_release,
        "checks": [asdict(item) for item in checks],
        "install_commands": install_commands(manager, include_optional=False),
        "install_commands_optional": install_commands(manager, include_optional=True),
        "notes": notes,
    }


def _print_human_report(payload: dict, include_optional: bool = False) -> int:
    os_release = payload.get("os_release") or {}
    pretty = os_release.get("PRETTY_NAME") or os_release.get("NAME") or "unknown distro"
    manager = payload.get("package_manager") or "unknown"
    print("ac-ui doctor")
    print(f"  distro: {pretty}")
    print(f"  package manager: {manager}")
    print()

    print("Required")
    for item in payload.get("checks", []):
        if not item.get("required"):
            continue
        mark = "OK  " if item.get("ok") else "MISS"
        print(f"  {mark} {item['name']}: {item['detail']}")
    print()

    print("Recommended")
    for item in payload.get("checks", []):
        if item.get("required"):
            continue
        mark = "OK  " if item.get("ok") else "WARN"
        print(f"  {mark} {item['name']}: {item['detail']}")
    print()

    print("Notes")
    for note in payload.get("notes", []):
        print(f"  {note}")
    print()

    commands = payload.get("install_commands_optional" if include_optional else "install_commands") or []
    if commands:
        print("Suggested system install commands")
        for cmd in commands:
            print(f"  {cmd}")
        print()
    elif not payload.get("ok"):
        print("No supported package manager was detected automatically.")
        print()

    if payload.get("ok"):
        print("Core runtime looks ready.")
        return 0
    print("Core runtime is missing required pieces.")
    return 1


def doctor_cli(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    want_json = "--json" in argv
    want_commands = "--install-commands" in argv
    include_optional = "--with-optional" in argv
    payload = doctor_data()
    if want_commands:
        key = "install_commands_optional" if include_optional else "install_commands"
        for cmd in payload.get(key, []):
            print(cmd)
        return 0
    if want_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1
    return _print_human_report(payload, include_optional=include_optional)

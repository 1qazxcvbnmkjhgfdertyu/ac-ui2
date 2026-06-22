import json

from ac_ui.app import main_cli
from ac_ui.install import doctor_data, install_commands, parse_os_release


def test_parse_os_release_handles_quotes_and_comments():
    data = parse_os_release(
        """
        NAME="Ubuntu"
        VERSION_ID="24.04"
        # comment
        ID=ubuntu
        """
    )
    assert data["NAME"] == "Ubuntu"
    assert data["VERSION_ID"] == "24.04"
    assert data["ID"] == "ubuntu"


def test_install_commands_for_apt_include_update():
    cmds = install_commands("apt-get", include_optional=False)
    assert cmds[0] == "sudo apt-get update"
    assert "mpv" in cmds[1]
    assert "cava" in cmds[1]


def test_install_commands_optional_expands_package_set():
    core = install_commands("pacman", include_optional=False)[0]
    full = install_commands("pacman", include_optional=True)[0]
    assert "mpv" in core
    assert "figlet" in full
    assert len(full) > len(core)


def test_doctor_data_marks_missing_required_tools():
    available = {"pactl"}

    def fake_which(cmd):
        return f"/usr/bin/{cmd}" if cmd in available else None

    payload = doctor_data(which=fake_which, version_info=(3, 11, 0), env={"PATH": "/usr/bin"})
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["python"]["ok"]
    assert not checks["mpv"]["ok"]
    assert not checks["cava"]["ok"]
    assert checks["pactl"]["ok"]
    assert not payload["ok"]


def test_doctor_data_respects_custom_cava_binary():
    available = {"/opt/ac/bin/cava-acui"}

    def fake_which(cmd):
        return cmd if cmd in available else None

    payload = doctor_data(
        which=fake_which,
        version_info=(3, 11, 0),
        env={"PATH": "/usr/bin", "AC_UI_CAVA_BIN": "/opt/ac/bin/cava-acui"},
    )
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["cava"]["ok"]
    assert checks["cava"]["detail"] == "/opt/ac/bin/cava-acui"
    assert "custom cava binary: /opt/ac/bin/cava-acui" in payload["notes"]


def test_main_cli_routes_doctor_without_loading_ui(monkeypatch):
    import ac_ui.install as install

    calls = {}

    def fake_doctor(argv):
        calls["argv"] = list(argv)
        print(json.dumps({"ok": True}))
        return 7

    monkeypatch.setattr(install, "doctor_cli", fake_doctor)
    rc = main_cli(["launcher-name", "doctor", "--json"])
    assert rc == 7
    assert calls["argv"] == ["--json"]

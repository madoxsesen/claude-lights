import configparser
from pathlib import Path

from claude_lights import shortcut


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def _stub_qdbus(monkeypatch, present: bool = True) -> None:
    monkeypatch.setattr(
        shortcut.shutil, "which", lambda name: "/usr/bin/qdbus6" if present and name == "qdbus6" else None
    )
    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: None)


def test_write_kwin_rule_creates_a_fresh_file_when_none_exists(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch)

    ok, _msg = shortcut.write_kwin_rule(path)

    assert ok is True
    parser = _read(path)
    assert parser["General"]["count"] == "1"
    assert parser["General"]["rules"] == "1"
    assert parser["1"]["wmclass"] == "claude-lights"
    assert parser["1"]["position"] == "0,0"
    assert parser["1"]["acceptfocusrule"] == "2"
    assert not (path.with_name(path.name + ".bak")).exists(), "nothing existed to back up"


def test_write_kwin_rule_handles_an_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text("")
    _stub_qdbus(monkeypatch)

    ok, _msg = shortcut.write_kwin_rule(path)

    assert ok is True
    parser = _read(path)
    assert parser["General"]["count"] == "1"
    assert parser["1"]["wmclass"] == "claude-lights"


def test_write_kwin_rule_preserves_two_unrelated_existing_rules(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text(
        "[General]\n"
        "count=2\n"
        "rules=1,2\n"
        "\n"
        "[1]\n"
        "Description=someone else's rule\n"
        "wmclass=firefox\n"
        "\n"
        "[2]\n"
        "Description=another rule\n"
        "wmclass=konsole\n"
    )
    _stub_qdbus(monkeypatch)

    ok, _msg = shortcut.write_kwin_rule(path)

    assert ok is True
    parser = _read(path)
    assert parser["General"]["count"] == "3"
    assert parser["General"]["rules"] == "1,2,3"
    assert parser["1"]["wmclass"] == "firefox"
    assert parser["1"]["Description"] == "someone else's rule"
    assert parser["2"]["wmclass"] == "konsole"
    assert parser["3"]["wmclass"] == "claude-lights"

    backup = path.with_name(path.name + ".bak")
    assert backup.exists(), "the pre-existing file must be backed up before it is overwritten"
    backup_parser = _read(backup)
    assert backup_parser["General"]["rules"] == "1,2", "the backup must capture the pre-merge state"


def test_write_kwin_rule_preserves_unrelated_sections_and_general_keys(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text(
        "[$Version]\n"
        "update_info=kwinrules.upd:replace-placement-string-to-enum\n"
        "\n"
        "[General]\n"
        "count=0\n"
        "rules=\n"
    )
    _stub_qdbus(monkeypatch)

    shortcut.write_kwin_rule(path)

    parser = _read(path)
    assert parser["$Version"]["update_info"] == "kwinrules.upd:replace-placement-string-to-enum"
    assert parser["General"]["count"] == "1"
    assert parser["General"]["rules"] == "1"


def test_write_kwin_rule_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch)

    shortcut.write_kwin_rule(path)
    shortcut.write_kwin_rule(path)

    parser = _read(path)
    assert parser["General"]["count"] == "1"
    assert parser["General"]["rules"] == "1"


def test_write_kwin_rule_updates_in_place_alongside_other_rules(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text(
        "[General]\n"
        "count=2\n"
        "rules=1,2\n"
        "\n"
        "[1]\n"
        "wmclass=firefox\n"
        "\n"
        "[2]\n"
        "wmclass=claude-lights\n"
        "position=99,99\n"
    )
    _stub_qdbus(monkeypatch)

    shortcut.write_kwin_rule(path)

    parser = _read(path)
    assert parser["General"]["count"] == "2", "must not grow a duplicate rule on reinstall"
    assert parser["General"]["rules"] == "1,2"
    assert parser["1"]["wmclass"] == "firefox"
    assert parser["2"]["position"] == "0,0", "our rule's own section must be refreshed, not left stale"


def test_write_kwin_rule_heals_a_general_missing_from_rules_list(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text("[General]\ncount=1\nrules=\n\n[1]\nwmclass=firefox\n")
    _stub_qdbus(monkeypatch)

    shortcut.write_kwin_rule(path)

    parser = _read(path)
    assert parser["General"]["rules"] == "1,2"
    assert parser["General"]["count"] == "2"


def test_write_kwin_rule_reports_failure_but_still_writes_when_qdbus6_is_missing(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch, present=False)

    ok, msg = shortcut.write_kwin_rule(path)

    assert ok is False
    assert "qdbus6" in msg
    parser = _read(path)
    assert parser["1"]["wmclass"] == "claude-lights"


def test_write_desktop_file_points_at_the_launcher_and_toggle(tmp_path):
    launcher = tmp_path / "claude-lights"
    apps_dir = tmp_path / "applications"

    desktop_file = shortcut.write_desktop_file(launcher, directory=apps_dir)

    content = desktop_file.read_text()
    assert f"Exec={launcher} toggle" in content
    assert "X-KDE-GlobalAccel-CommandShortcut=true" in content
    assert desktop_file.name == shortcut.DESKTOP_ID


def test_write_global_shortcut_writes_both_keys_via_kwriteconfig6(monkeypatch):
    calls = []
    monkeypatch.setattr(
        shortcut.shutil, "which", lambda name: "/usr/bin/kwriteconfig6" if name == "kwriteconfig6" else None
    )
    monkeypatch.setattr(shortcut.subprocess, "run", lambda args, **kwargs: calls.append(args))

    ok, _msg = shortcut.write_global_shortcut("Meta+C")

    assert ok is True
    assert len(calls) == 2
    assert calls[0][-1] == shortcut.FRIENDLY_NAME
    assert calls[1][-1] == "Meta+C,none,Toggle Claude Lights"
    assert all(a[:2] == ["/usr/bin/kwriteconfig6", "--file"] for a in calls)


def test_write_global_shortcut_reports_failure_when_kwriteconfig_is_missing(monkeypatch):
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: None)

    ok, msg = shortcut.write_global_shortcut("Meta+C")

    assert ok is False
    assert "kwriteconfig6" in msg


def test_install_returns_zero_when_both_halves_apply(monkeypatch, tmp_path, capsys):
    launcher = tmp_path / "claude-lights"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(shortcut, "_launcher_path", lambda: launcher)
    monkeypatch.setattr(shortcut, "write_kwin_rule", lambda: (True, "merged fine"))
    monkeypatch.setattr(shortcut, "write_desktop_file", lambda launcher: tmp_path / "x.desktop")
    monkeypatch.setattr(shortcut, "write_global_shortcut", lambda keys: (True, "registered fine"))

    assert shortcut.install() == 0
    out = capsys.readouterr().out
    assert "KWin rule: ok" in out
    assert "Global shortcut: ok" in out


def test_install_returns_one_when_the_launcher_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shortcut, "_launcher_path", lambda: tmp_path / "missing-launcher")
    assert shortcut.install() == 1


def test_install_returns_one_and_says_so_when_the_kwin_half_fails(monkeypatch, tmp_path, capsys):
    launcher = tmp_path / "claude-lights"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(shortcut, "_launcher_path", lambda: launcher)
    monkeypatch.setattr(shortcut, "write_kwin_rule", lambda: (False, "no qdbus6"))
    monkeypatch.setattr(shortcut, "write_desktop_file", lambda launcher: tmp_path / "x.desktop")
    monkeypatch.setattr(shortcut, "write_global_shortcut", lambda keys: (True, "registered fine"))

    assert shortcut.install() == 1
    out = capsys.readouterr().out
    assert "KWin rule: FAILED" in out
    assert "did not fully apply" in out


def test_install_returns_one_and_says_so_when_the_shortcut_half_fails(monkeypatch, tmp_path, capsys):
    launcher = tmp_path / "claude-lights"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(shortcut, "_launcher_path", lambda: launcher)
    monkeypatch.setattr(shortcut, "write_kwin_rule", lambda: (True, "merged fine"))
    monkeypatch.setattr(shortcut, "write_desktop_file", lambda launcher: tmp_path / "x.desktop")
    monkeypatch.setattr(shortcut, "write_global_shortcut", lambda keys: (False, "kwriteconfig6 not found"))

    assert shortcut.install() == 1
    out = capsys.readouterr().out
    assert "Global shortcut: FAILED" in out


def test_install_always_prints_the_manual_fallback(monkeypatch, tmp_path, capsys):
    launcher = tmp_path / "claude-lights"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(shortcut, "_launcher_path", lambda: launcher)
    monkeypatch.setattr(shortcut, "write_kwin_rule", lambda: (True, "merged fine"))
    monkeypatch.setattr(shortcut, "write_desktop_file", lambda launcher: tmp_path / "x.desktop")
    monkeypatch.setattr(shortcut, "write_global_shortcut", lambda keys: (True, "registered fine"))

    shortcut.install()
    out = capsys.readouterr().out
    assert "System Settings > Keyboard > Shortcuts > Add > Command" in out

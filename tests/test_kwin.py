import configparser
from pathlib import Path

from claude_lights import kwin


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def _stub_qdbus(monkeypatch, present: bool = True) -> None:
    monkeypatch.setattr(
        kwin.shutil, "which", lambda name: "/usr/bin/qdbus6" if present and name == "qdbus6" else None
    )
    monkeypatch.setattr(kwin.subprocess, "run", lambda *a, **k: None)


def test_write_kwin_rule_creates_a_fresh_file_when_none_exists(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch)

    ok, _msg = kwin.write_kwin_rule(path)

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

    ok, _msg = kwin.write_kwin_rule(path)

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

    ok, _msg = kwin.write_kwin_rule(path)

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

    kwin.write_kwin_rule(path)

    parser = _read(path)
    assert parser["$Version"]["update_info"] == "kwinrules.upd:replace-placement-string-to-enum"
    assert parser["General"]["count"] == "1"
    assert parser["General"]["rules"] == "1"


def test_write_kwin_rule_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch)

    kwin.write_kwin_rule(path)
    kwin.write_kwin_rule(path)

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

    kwin.write_kwin_rule(path)

    parser = _read(path)
    assert parser["General"]["count"] == "2", "must not grow a duplicate rule on reinstall"
    assert parser["General"]["rules"] == "1,2"
    assert parser["1"]["wmclass"] == "firefox"
    assert parser["2"]["position"] == "0,0", "our rule's own section must be refreshed, not left stale"


def test_write_kwin_rule_heals_a_general_missing_from_rules_list(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    path.write_text("[General]\ncount=1\nrules=\n\n[1]\nwmclass=firefox\n")
    _stub_qdbus(monkeypatch)

    kwin.write_kwin_rule(path)

    parser = _read(path)
    assert parser["General"]["rules"] == "1,2"
    assert parser["General"]["count"] == "2"


def test_write_kwin_rule_reports_failure_but_still_writes_when_qdbus6_is_missing(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch, present=False)

    ok, msg = kwin.write_kwin_rule(path)

    assert ok is False
    assert "qdbus6" in msg
    parser = _read(path)
    assert parser["1"]["wmclass"] == "claude-lights"


def test_write_kwin_rule_refuses_to_touch_an_unparseable_file(tmp_path, monkeypatch):
    # Regression for a bug where an unparseable file was silently treated as
    # empty, discarding whatever the user actually had in it.
    path = tmp_path / "kwinrulesrc"
    garbage = "this is not valid ini at all\nno section header\njust garbage=1\n"
    path.write_text(garbage)
    _stub_qdbus(monkeypatch)

    ok, msg = kwin.write_kwin_rule(path)

    assert ok is False
    assert "could not be parsed" in msg
    assert path.read_text() == garbage, "an unparseable file must be left byte-for-byte untouched"


def test_merge_kwin_rule_avoids_colliding_with_a_dangling_rules_reference():
    # Regression: rules= can list more ids than have a physical [N] section
    # (stale reference left behind by hand-editing, or a drifted [General]).
    # The next id must dodge those too, not just the sections that exist.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string("[General]\ncount=5\nrules=1,2,3,4,5\n\n[1]\nwmclass=firefox\n")

    kwin.merge_kwin_rule(parser)

    rules = parser["General"]["rules"].split(",")
    assert len(rules) == len(set(rules)), f"rules list has a duplicate id: {rules}"
    assert parser["General"]["count"] == "6"
    assert parser["6"]["wmclass"] == "claude-lights"


def test_write_kwin_rule_does_not_overwrite_an_existing_backup_on_a_second_run(tmp_path, monkeypatch):
    # Regression: install is meant to be re-runnable (to re-apply the rule
    # after KDE rewrites kwinrulesrc, say). A naive "always back up" would, on the
    # second run, back up the first run's already-merged output, destroying
    # the one copy of the user's true pre-install content.
    path = tmp_path / "kwinrulesrc"
    original = "[General]\ncount=1\nrules=1\n\n[1]\nwmclass=firefox\n"
    path.write_text(original)
    _stub_qdbus(monkeypatch)

    kwin.write_kwin_rule(path)
    kwin.write_kwin_rule(path)

    backup = path.with_name(path.name + ".bak")
    assert backup.read_text() == original, "the backup must still be the ORIGINAL pre-install content"


def test_write_kwin_rule_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    path = tmp_path / "kwinrulesrc"
    _stub_qdbus(monkeypatch)

    kwin.write_kwin_rule(path)

    assert not path.with_name(f"{path.name}.tmp").exists()
    assert path.exists()


def _stub_launcher(monkeypatch, tmp_path):
    launcher = tmp_path / "claude-lights"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(kwin, "_launcher_path", lambda: launcher)
    return launcher


def test_install_returns_zero_when_the_kwin_rule_applies(monkeypatch, tmp_path, capsys):
    _stub_launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(kwin, "write_kwin_rule", lambda: (True, "merged fine"))

    assert kwin.install() == 0
    assert "KWin rule: ok" in capsys.readouterr().out


def test_install_returns_one_when_the_launcher_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(kwin, "_launcher_path", lambda: tmp_path / "missing-launcher")
    assert kwin.install() == 1


def test_install_returns_one_and_says_so_when_the_kwin_rule_fails(monkeypatch, tmp_path, capsys):
    _stub_launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(kwin, "write_kwin_rule", lambda: (False, "no qdbus6"))

    assert kwin.install() == 1
    out = capsys.readouterr().out
    assert "KWin rule: FAILED" in out
    assert "did not apply" in out


def test_install_always_prints_the_hotkey_instructions(monkeypatch, tmp_path, capsys):
    launcher = _stub_launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(kwin, "write_kwin_rule", lambda: (True, "merged fine"))

    kwin.install()
    out = capsys.readouterr().out
    assert "System Settings > Keyboard > Shortcuts > Add > Command" in out
    assert f"{launcher} toggle" in out


def test_install_writes_no_kde_shortcut_config(monkeypatch, tmp_path):
    """The hotkey cannot be bound by writing config: kglobalaccel only honours a
    component it registered itself. Writing it anyway would leave dead entries in
    the user's KDE config, so nothing must shell out to kwriteconfig6."""
    _stub_launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(kwin, "write_kwin_rule", lambda: (True, "merged fine"))
    calls = []
    monkeypatch.setattr(kwin.subprocess, "run", lambda args, **kwargs: calls.append(args))

    kwin.install()

    assert calls == []
    assert not hasattr(kwin, "write_global_shortcut")
    assert not hasattr(kwin, "write_desktop_file")


def test_the_rule_matches_the_app_id_the_widget_sets():
    """The rule matches on wmclass, and the rule is the only thing giving the
    widget its position, keep-above and focus suppression. If these two strings
    drift apart nothing errors: the widget just comes back unplaced."""
    from claude_lights import APP_ID

    assert kwin._RULE_KEYS["wmclass"] == APP_ID

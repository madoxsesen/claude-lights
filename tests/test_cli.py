from pathlib import Path

from claude_lights import __main__ as cli


def test_toggle_returns_zero_when_a_widget_is_running(monkeypatch):
    monkeypatch.setattr(cli.ipc, "send_toggle", lambda: True)
    assert cli.main(["toggle"]) == 0


def test_toggle_returns_one_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(cli.ipc, "send_toggle", lambda: False)
    assert cli.main(["toggle"]) == 1


def test_bare_invocation_runs_the_widget_with_no_session_dir(monkeypatch):
    seen = {}

    def fake_run(session_dir=None, demo=False):
        seen["dir"] = session_dir
        return 0

    monkeypatch.setattr(cli, "_run_widget", fake_run)
    assert cli.main([]) == 0
    assert seen["dir"] is None


def test_fake_flag_passes_the_directory_through(monkeypatch, tmp_path):
    seen = {}

    def fake_run(session_dir=None, demo=False):
        seen["dir"] = session_dir
        return 0

    monkeypatch.setattr(cli, "_run_widget", fake_run)
    assert cli.main(["--fake", str(tmp_path)]) == 0
    assert seen["dir"] == Path(tmp_path)


def test_demo_flag_passes_demo_through(monkeypatch):
    seen = {}

    def fake_run(session_dir=None, demo=False):
        seen["demo"] = demo
        return 0

    monkeypatch.setattr(cli, "_run_widget", fake_run)
    assert cli.main(["--demo"]) == 0
    assert seen["demo"] is True


def test_install_dispatches_to_the_installer(monkeypatch):
    calls = []

    def fake_install():
        calls.append("install")
        return 0

    monkeypatch.setattr(cli, "_install", fake_install)
    assert cli.main(["install"]) == 0
    assert calls == ["install"]

import os
import signal
import time

from claude_lights.ipc import pidfile_path, read_pidfile, send_toggle, write_pidfile


def test_pidfile_path_uses_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert pidfile_path() == tmp_path / "claude-lights.pid"


def test_pidfile_path_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert pidfile_path() == __import__("pathlib").Path(f"/run/user/{os.getuid()}/claude-lights.pid")


def test_write_then_read_roundtrip(tmp_path):
    path = tmp_path / "claude-lights.pid"
    write_pidfile(path)
    assert read_pidfile(path) == os.getpid()


def test_read_missing_pidfile_is_none(tmp_path):
    assert read_pidfile(tmp_path / "absent.pid") is None


def test_read_garbage_pidfile_is_none(tmp_path):
    path = tmp_path / "claude-lights.pid"
    path.write_text("not-a-number")
    assert read_pidfile(path) is None


def test_send_toggle_delivers_the_signal(tmp_path):
    received = []
    previous = signal.signal(signal.SIGUSR1, lambda *_: received.append(True))
    try:
        path = tmp_path / "claude-lights.pid"
        write_pidfile(path)
        assert send_toggle(path) is True
        time.sleep(0.05)
        assert received == [True]
    finally:
        signal.signal(signal.SIGUSR1, previous)


def test_send_toggle_removes_a_stale_pidfile(tmp_path):
    path = tmp_path / "claude-lights.pid"
    stale = next(p for p in range(4_000_000, 4_000_100) if not os.path.exists(f"/proc/{p}"))
    path.write_text(str(stale))
    assert send_toggle(path) is False
    assert not path.exists(), "a stale pidfile must be cleaned up"


def test_send_toggle_with_no_pidfile_is_false(tmp_path):
    assert send_toggle(tmp_path / "absent.pid") is False

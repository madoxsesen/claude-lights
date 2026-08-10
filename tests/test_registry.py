import json
import os
from pathlib import Path

import pytest

from claude_lights.registry import Registry, Session, scan


def proc_start_of(pid: int) -> str:
    """Field 22 of /proc/<pid>/stat. comm can contain spaces and parens, so
    parse from the last ')' to stay correct."""
    raw = Path(f"/proc/{pid}/stat").read_text()
    return raw[raw.rfind(")") + 2 :].split()[19]


def write_session(directory: Path, pid: int, **overrides) -> Path:
    payload = {
        "pid": pid,
        "cwd": "/home/msesen/git/atira",
        "startedAt": 1786392077812,
        "procStart": proc_start_of(pid) if Path(f"/proc/{pid}").exists() else "1",
        "name": f"session-{pid}",
        "status": "idle",
        "tmux": "quad:@0.%5",
    }
    payload.update(overrides)
    path = directory / f"{pid}.json"
    path.write_text(json.dumps(payload))
    return path


def dead_pid() -> int:
    """A pid that is certainly not running."""
    for candidate in range(4_000_000, 4_000_100):
        if not Path(f"/proc/{candidate}").exists():
            return candidate
    pytest.skip("could not find an unused pid")


def test_live_session_is_returned(tmp_path):
    write_session(tmp_path, os.getpid(), name="mine", status="busy")
    result = scan(tmp_path)
    assert [s.name for s in result.sessions] == ["mine"]
    assert result.sessions[0].status == "busy"
    assert result.sessions[0].tmux == "quad:@0.%5"


def test_dead_pid_is_dropped(tmp_path):
    write_session(tmp_path, dead_pid())
    assert scan(tmp_path).sessions == []


def test_recycled_pid_is_dropped(tmp_path):
    # Same pid, wrong start time: a different process now owns this pid.
    write_session(tmp_path, os.getpid(), procStart="1")
    assert scan(tmp_path).sessions == []


def test_half_written_file_is_reported_as_unreadable(tmp_path):
    pid = os.getpid()
    (tmp_path / f"{pid}.json").write_text('{"pid": %d, "status": "bu' % pid)
    result = scan(tmp_path)
    assert result.sessions == []
    assert result.unreadable_pids == [pid]


def test_file_missing_status_is_skipped(tmp_path):
    path = write_session(tmp_path, os.getpid())
    payload = json.loads(path.read_text())
    del payload["status"]
    path.write_text(json.dumps(payload))
    assert scan(tmp_path).sessions == []


def test_file_missing_pid_is_skipped(tmp_path):
    path = write_session(tmp_path, os.getpid())
    payload = json.loads(path.read_text())
    del payload["pid"]
    path.write_text(json.dumps(payload))
    assert scan(tmp_path).sessions == []


def test_missing_directory_is_empty_not_an_error(tmp_path):
    result = scan(tmp_path / "does-not-exist")
    assert result.sessions == []
    assert result.unreadable_pids == []


def test_ordering_is_by_started_at_then_pid(tmp_path):
    pid = os.getpid()
    write_session(tmp_path, pid, startedAt=300, name="third")
    # Two extra live pids: reuse our own start time via the parent process.
    ppid = os.getppid()
    write_session(tmp_path, ppid, startedAt=100, name="first")
    ordered = [s.name for s in scan(tmp_path).sessions]
    assert ordered == ["first", "third"]


def test_ordering_is_stable_across_repeated_scans(tmp_path):
    write_session(tmp_path, os.getpid(), startedAt=100)
    write_session(tmp_path, os.getppid(), startedAt=100)
    first = [s.pid for s in scan(tmp_path).sessions]
    assert all([s.pid for s in scan(tmp_path).sessions] == first for _ in range(5))


def test_name_falls_back_to_cwd_basename(tmp_path):
    write_session(tmp_path, os.getpid(), name=None, cwd="/home/msesen/git/atira")
    assert scan(tmp_path).sessions[0].name == "atira"


def test_registry_keeps_last_good_value_through_a_half_write(tmp_path):
    pid = os.getpid()
    path = write_session(tmp_path, pid, status="busy")
    reg = Registry(tmp_path)
    assert [s.status for s in reg.poll()] == ["busy"]

    path.write_text('{"pid": %d, "status": "wai' % pid)  # caught mid-rewrite
    assert [s.status for s in reg.poll()] == ["busy"], "dot must not flicker out"

    write_session(tmp_path, pid, status="waiting")
    assert [s.status for s in reg.poll()] == ["waiting"]


def test_registry_drops_a_session_whose_file_disappears(tmp_path):
    pid = os.getpid()
    path = write_session(tmp_path, pid)
    reg = Registry(tmp_path)
    assert len(reg.poll()) == 1
    path.unlink()
    assert reg.poll() == []

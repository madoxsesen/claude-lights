import json
import os
from pathlib import Path

import pytest

from claude_lights import registry
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


def test_matching_proc_start_is_verified(tmp_path):
    write_session(tmp_path, os.getpid())
    assert scan(tmp_path).sessions[0].verified is True


def test_missing_proc_start_is_live_but_unverified(tmp_path):
    # A future Claude Code release could drop the field. It must still show
    # up (grey, per the widget), not vanish as if no session were open.
    path = write_session(tmp_path, os.getpid())
    payload = json.loads(path.read_text())
    del payload["procStart"]
    path.write_text(json.dumps(payload))
    result = scan(tmp_path)
    assert len(result.sessions) == 1
    assert result.sessions[0].verified is False


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


def test_non_string_cwd_does_not_raise(tmp_path):
    # A truthy non-string cwd (e.g. a stray int) used to reach Path(cwd) and
    # raise TypeError straight out of scan().
    pid = os.getpid()
    write_session(tmp_path, pid, name=None, cwd=42)
    result = scan(tmp_path)
    assert result.sessions[0].cwd == ""
    assert result.sessions[0].name == str(pid)


def test_non_string_tmux_becomes_none(tmp_path):
    write_session(tmp_path, os.getpid(), tmux=7)
    assert scan(tmp_path).sessions[0].tmux is None


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


def test_starttime_parser_reads_field_22_of_a_synthetic_stat_line():
    # A hand-built line, not read from /proc: comm is parenthesised and
    # contains its own spaces and inner parens, which would defeat a naive
    # split or a first-')' search. Field 22 (starttime) is given a sentinel
    # value that is unambiguous if the parser lands on the wrong field.
    filler_fields = [str(n) for n in range(1, 19)]  # fields 4..21
    line = "1234 (my (weird) proc) S " + " ".join(filler_fields) + " 424242 extra1 extra2"
    assert registry._parse_starttime(line) == "424242"

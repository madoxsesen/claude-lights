"""Read Claude Code's own live session registry.

Claude Code writes one file per running session to ~/.claude/sessions/<pid>.json
and rewrites it on every state change. That file is an internal detail of Claude
Code, so every read here is defensive: a format change must degrade the widget,
never crash it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SESSION_DIR = Path.home() / ".claude" / "sessions"

# /proc/<pid>/stat field 22 (starttime), zero-indexed from the field after comm.
_STARTTIME_OFFSET = 19


@dataclass(frozen=True)
class Session:
    pid: int
    name: str
    cwd: str
    status: str
    started_at: int
    tmux: str | None


@dataclass
class ScanResult:
    sessions: list[Session] = field(default_factory=list)
    unreadable_pids: list[int] = field(default_factory=list)


def _proc_start_ticks(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (OSError, ValueError):
        return None
    # comm is parenthesised and may contain spaces, so index from the last ')'.
    fields = raw[raw.rfind(")") + 2 :].split()
    if len(fields) <= _STARTTIME_OFFSET:
        return None
    return fields[_STARTTIME_OFFSET]


def _is_live(pid: int, proc_start: object) -> bool:
    actual = _proc_start_ticks(pid)
    if actual is None:
        return False
    if proc_start is None:
        return True
    return str(proc_start) == actual


def _pid_from_name(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def scan(session_dir: Path = DEFAULT_SESSION_DIR) -> ScanResult:
    result = ScanResult()
    try:
        paths = sorted(session_dir.glob("*.json"))
    except OSError:
        return result

    for path in paths:
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            pid_guess = _pid_from_name(path)
            if pid_guess is not None:
                result.unreadable_pids.append(pid_guess)
            continue

        if not isinstance(raw, dict):
            continue
        pid = raw.get("pid")
        status = raw.get("status")
        if not isinstance(pid, int) or not isinstance(status, str):
            continue
        if not _is_live(pid, raw.get("procStart")):
            continue

        cwd = raw.get("cwd") or ""
        name = raw.get("name") or Path(cwd).name or str(pid)
        started_at = raw.get("startedAt")
        result.sessions.append(
            Session(
                pid=pid,
                name=str(name),
                cwd=str(cwd),
                status=status,
                started_at=started_at if isinstance(started_at, int) else 0,
                tmux=raw.get("tmux"),
            )
        )

    result.sessions.sort(key=lambda s: (s.started_at, s.pid))
    return result


class Registry:
    """scan() plus a last-known-good cache.

    Claude Code rewrites these files in place, so a poll can land mid-write. The
    cache stops a dot flickering out for a full poll interval when that happens.
    """

    def __init__(self, session_dir: Path = DEFAULT_SESSION_DIR) -> None:
        self._dir = session_dir
        self._last_good: dict[int, Session] = {}

    def poll(self) -> list[Session]:
        result = scan(self._dir)
        by_pid = {s.pid: s for s in result.sessions}
        for pid in result.unreadable_pids:
            if pid not in by_pid and pid in self._last_good:
                by_pid[pid] = self._last_good[pid]
        self._last_good = dict(by_pid)
        return sorted(by_pid.values(), key=lambda s: (s.started_at, s.pid))

"""Pidfile and SIGUSR1 transport for the show/hide toggle."""

from __future__ import annotations

import os
import signal
from pathlib import Path

PIDFILE_NAME = "claude-lights.pid"


def pidfile_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime_dir) / PIDFILE_NAME


def write_pidfile(path: Path | None = None) -> Path:
    target = path or pidfile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(os.getpid()))
    return target


def read_pidfile(path: Path | None = None) -> int | None:
    target = path or pidfile_path()
    try:
        return int(target.read_text().strip())
    except (OSError, ValueError):
        return None


def send_toggle(path: Path | None = None) -> bool:
    """Signal a running widget. Returns False if none is running."""
    target = path or pidfile_path()
    pid = read_pidfile(target)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError):
        target.unlink(missing_ok=True)
        return False
    return True

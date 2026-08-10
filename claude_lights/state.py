"""Map Claude Code session statuses to traffic-light colours.

The status enum is hardcoded in the Claude Code binary as
["busy", "shell", "idle", "waiting"]. Claude Code groups "shell" with "busy"
as live work, so they share a colour here.
"""

from __future__ import annotations

from enum import Enum


class Light(Enum):
    GREEN = "#2ecc71"
    YELLOW = "#f1c40f"
    RED = "#e74c3c"
    UNKNOWN = "#4a4a4a"


_BY_STATUS: dict[str, Light] = {
    "idle": Light.GREEN,
    "busy": Light.YELLOW,
    "shell": Light.YELLOW,
    "waiting": Light.RED,
}


def light_for(status: str) -> Light:
    """An unrecognised status renders grey rather than raising, so a future
    Claude Code release that adds a status cannot break the widget."""
    return _BY_STATUS.get(status, Light.UNKNOWN)


def blinks(light: Light) -> bool:
    return light is Light.RED


def rgb(light: Light) -> tuple[float, float, float]:
    raw = light.value.lstrip("#")
    red, green, blue = (int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (red, green, blue)

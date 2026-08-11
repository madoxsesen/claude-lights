"""Grid geometry for the session dots."""

from __future__ import annotations

import math


def layout(n: int) -> tuple[int, int]:
    """Return (cols, rows) for n sessions, or (0, 0) when there are none."""
    if n <= 0:
        return (0, 0)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return (cols, rows)

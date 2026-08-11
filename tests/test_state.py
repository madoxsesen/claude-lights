import pytest

from claude_lights.state import Light, blinks, light_for, rgb


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("idle", Light.GREEN),
        ("busy", Light.YELLOW),
        ("shell", Light.YELLOW),
        ("waiting", Light.RED),
    ],
)
def test_known_statuses(status, expected):
    assert light_for(status) == expected


@pytest.mark.parametrize("status", ["compacting", "", "BUSY", "thinking", "future-status"])
def test_unknown_statuses_are_grey_not_an_error(status):
    assert light_for(status) == Light.UNKNOWN


def test_exact_hex_values():
    assert Light.GREEN.value == "#2ecc71"
    assert Light.YELLOW.value == "#f1c40f"
    assert Light.RED.value == "#e74c3c"
    assert Light.UNKNOWN.value == "#4a4a4a"


def test_only_red_blinks():
    assert blinks(Light.RED) is True
    for light in (Light.GREEN, Light.YELLOW, Light.UNKNOWN):
        assert blinks(light) is False


def test_rgb_is_normalised_floats():
    r, g, b = rgb(Light.RED)
    assert (round(r, 3), round(g, 3), round(b, 3)) == (0.906, 0.298, 0.235)
    for channel in rgb(Light.GREEN):
        assert 0.0 <= channel <= 1.0

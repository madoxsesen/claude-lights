import pytest

from claude_lights.grid import layout


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, (0, 0)),
        (1, (1, 1)),
        (2, (2, 1)),
        (3, (2, 2)),
        (4, (2, 2)),
        (5, (3, 2)),
        (6, (3, 2)),
        (7, (3, 3)),
        (9, (3, 3)),
    ],
)
def test_layout_matches_spec(n, expected):
    assert layout(n) == expected


def test_negative_count_is_treated_as_empty():
    assert layout(-1) == (0, 0)


def test_every_session_has_a_cell():
    for n in range(1, 30):
        cols, rows = layout(n)
        assert cols * rows >= n

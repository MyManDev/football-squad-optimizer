"""A named club-news capture must be a capture name, not a path.

The runner joins the value onto the snapshot root and the journal then walks the result and
digests every file under it, so a value that is not one directory name does not fail late and
loudly: it succeeds at reading the wrong thing. These hold the refusal at the plan, before any
stage runs.
"""

import pytest

from squadopt.application.weekly_plan import WeekError, WeeklyRequest

VALID_CAPTURE = "fpl-live-20260912T100000Z-24613792ef57"


def _request(capture: str | None) -> WeeklyRequest:
    return WeeklyRequest(
        season="2026-27",
        gameweek=5,
        league_id=352490,
        workers=8,
        rotation=True,
        rotation_capture=capture,
    )


def test_a_real_capture_name_is_accepted() -> None:
    plan = _request(VALID_CAPTURE).plan()

    assert "rotation" in plan.steps


@pytest.mark.parametrize(
    "value",
    [
        "../../..",
        "..",
        ".",
        "a/../..",
        "nested/name",
        # A backslash is a separator on Windows and an ordinary filename character on Linux,
        # so Path(value).name alone refuses these on the operator's machine and accepts them
        # in CI. Both are refused on both, because a refusal that depends on where it runs is
        # not a refusal, and this runner is meant to execute on either.
        "nested\\name",
        "..\\..\\..",
    ],
)
def test_a_path_is_refused(value: str) -> None:
    with pytest.raises(WeekError, match="directory name"):
        _request(value).plan()


@pytest.mark.parametrize("value", ["", "   ", " name", "name "])
def test_an_empty_or_padded_name_is_refused(value: str) -> None:
    """An empty name reads as the snapshot root, which is every capture rather than one."""

    with pytest.raises(WeekError, match="empty or padded"):
        _request(value).plan()


def test_the_refusal_names_the_value() -> None:
    """An operator who mistyped needs to see what was read, not only that it was wrong."""

    with pytest.raises(WeekError) as refusal:
        _request("../../..").plan()

    assert "'../../..'" in str(refusal.value)

"""An operator-typed capture identifier must be a capture name, not a path.

The runner joins the value onto the snapshot root and the journal then walks the result and
digests every file under it, so a value that is not one directory name does not fail late and
loudly: it succeeds at reading the wrong thing. These hold the refusal at the plan, before any
stage runs.

**Four inputs, not one.** ``--rotation-capture`` got this refusal in #570 and the three
beside it reach the journal the same way (#597). Measured on develop before the fix:
``--cohort-snapshot`` and ``--elite-snapshot`` accepted all seven bad shapes, and
``--snapshot-id`` accepted the empty string outright and accepted every shape once
``--skip-top100`` was passed. Its apparent refusal came from an unrelated Top-100 rule,
which is a shield rather than a check, and the tests below pass ``skip_top100`` for exactly
that reason: a shape check that only holds while another rule happens to fire is not one.
"""

import pytest

from squadopt.application.weekly_plan import WeekError, WeeklyRequest

VALID_CAPTURE = "fpl-live-20260912T100000Z-24613792ef57"


#: Every operator-typed identifier that is joined onto the snapshot root, with the flag the
#: refusal has to name. A fifth such input belongs here the day it is added.
IDENTIFIERS: tuple[tuple[str, str], ...] = (
    ("snapshot_id", "--snapshot-id"),
    ("cohort_snapshot", "--cohort-snapshot"),
    ("elite_snapshot", "--elite-snapshot"),
    ("rotation_capture", "--rotation-capture"),
)


def _request(capture: str | None, field: str = "rotation_capture") -> WeeklyRequest:
    return WeeklyRequest(
        season="2026-27",
        gameweek=5,
        league_id=352490,
        workers=8,
        rotation=True,
        # Without this, `--snapshot-id` is refused by an unrelated Top-100 rule and a test
        # of the shape check would pass without the shape check existing.
        skip_top100=True,
        **{field: capture},
    )


@pytest.mark.parametrize(("field", "flag"), IDENTIFIERS)
def test_a_real_capture_name_is_accepted(field: str, flag: str) -> None:
    plan = _request(VALID_CAPTURE, field).plan()

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
@pytest.mark.parametrize(("field", "flag"), IDENTIFIERS)
def test_a_path_is_refused(value: str, field: str, flag: str) -> None:
    with pytest.raises(WeekError, match="directory name") as refusal:
        _request(value, field).plan()

    assert flag in str(refusal.value)


@pytest.mark.parametrize("value", ["", "   ", " name", "name "])
@pytest.mark.parametrize(("field", "flag"), IDENTIFIERS)
def test_an_empty_or_padded_name_is_refused(value: str, field: str, flag: str) -> None:
    """An empty name reads as the snapshot root, which is every capture rather than one."""

    with pytest.raises(WeekError, match="empty or padded") as refusal:
        _request(value, field).plan()

    assert flag in str(refusal.value)


def test_the_refusal_names_the_value() -> None:
    """An operator who mistyped needs to see what was read, not only that it was wrong."""

    with pytest.raises(WeekError) as refusal:
        _request("../../..").plan()

    assert "'../../..'" in str(refusal.value)


def test_the_refusal_names_the_flag_that_was_mistyped() -> None:
    """Four inputs share one rule, so naming the rule alone names none of them.

    An operator passing all four and reading "a capture must be one directory name" learns
    that something is wrong and has four places to look.
    """

    with pytest.raises(WeekError) as refusal:
        _request("../../..", "elite_snapshot").plan()

    message = str(refusal.value)
    assert "--elite-snapshot" in message
    assert "--snapshot-id" not in message and "--rotation-capture" not in message


def test_the_snapshot_id_check_does_not_depend_on_the_top_100_rule() -> None:
    """The shield this fix was hiding behind, held apart from the check that replaced it.

    Before #597's fix, `--snapshot-id='../../..'` was refused by a Top-100 rule about
    reusing a live capture, and `--skip-top100` removed the refusal entirely. A shape check
    that only holds while an unrelated rule fires is not a shape check.
    """

    for skip in (True, False):
        with pytest.raises(WeekError, match="directory name"):
            WeeklyRequest(
                season="2026-27",
                gameweek=5,
                league_id=352490,
                snapshot_id="../../..",
                skip_top100=skip,
            ).plan()

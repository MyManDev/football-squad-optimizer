"""The proposed DEFCON component on synthetic fixtures, never live captures."""

from __future__ import annotations

from dataclasses import replace

import pytest

from squadopt.prediction.defcon_component import (
    DEFCON_PRIOR_APPEARANCES,
    DefconComponentError,
    DefconRates,
    FixtureAppearance,
    expected_defcon_term,
    fit_defcon_rates,
)

AWARDS = {"GK": 0, "DEF": 2, "MID": 2, "FWD": 2}
DEADLINE = "2026-10-10T10:00:00Z"


def _row(code: int = 101, fixture: int = 1, **changes: object) -> FixtureAppearance:
    row = FixtureAppearance("2026-27", 1, fixture, code, "DEF", "2026-09-01T12:00:00Z", 90, 2)
    return replace(row, **changes)


def _fit(
    rows: tuple[FixtureAppearance, ...], positions: frozenset[str] = frozenset({"DEF"})
) -> DefconRates:
    return fit_defcon_rates(
        rows,
        target_gameweek=6,
        deadline_utc=DEADLINE,
        award_points=AWARDS,
        required_positions=positions,
    )


def _term(rates: DefconRates, **changes: object) -> float:
    arguments = {
        "player_code": 101,
        "position": "DEF",
        "appearance_probability": 0.8,
        "fixture_count": 1,
        "award_points": 2,
        "rates": rates,
    }
    arguments.update(changes)
    return expected_defcon_term(**arguments)


def test_fixed_prior_arithmetic_on_hand_computed_counts() -> None:
    rows = tuple(
        _row(101, fixture, awarded_points=2 if fixture <= 8 else 0) for fixture in range(1, 11)
    )
    rows += tuple(
        _row(102, fixture, awarded_points=2 if fixture <= 2 else 0) for fixture in range(1, 11)
    )
    rates = _fit(rows)
    assert DEFCON_PRIOR_APPEARANCES == 20
    assert rates.position_appearances["DEF"] == 20
    assert rates.position_awards["DEF"] == 10
    assert rates.rate(101, "DEF") == pytest.approx((8 + 20 * 0.5) / (10 + 20))
    assert _term(rates) == pytest.approx(0.8 * 0.6 * 2)


def test_unseen_player_receives_position_rate_without_new_fit_parameter() -> None:
    rates = _fit((_row(101, 1), _row(101, 2, awarded_points=0)))
    assert rates.rate(999, "DEF") == 0.5
    assert _term(rates, player_code=999) == pytest.approx(0.8)


def test_goalkeepers_and_zero_minute_rows_do_not_supply_rate_observations() -> None:
    rates = _fit(
        (_row(101, 1), _row(102, 1, minutes=0), _row(103, 1, position="GK", awarded_points=0))
    )
    assert rates.position_appearances == {"DEF": 1}
    assert dict(rates.player_appearances) == {101: 1}
    assert _term(rates, position="GK", appearance_probability=None, award_points=0) == 0


def test_blank_has_no_summands_and_does_not_invent_appearance() -> None:
    assert _term(_fit((_row(),)), fixture_count=0, appearance_probability=None) == 0


def test_double_uses_two_fixture_appearances_and_two_unchanged_q_summands() -> None:
    rates = _fit((_row(101, 11, gameweek=2), _row(101, 12, gameweek=2, awarded_points=0)))
    assert rates.player_appearances[101] == 2
    assert rates.player_awards[101] == 1
    assert _term(rates, fixture_count=2) == pytest.approx(2 * 0.8 * 0.5 * 2)


@pytest.mark.parametrize("week", [6, 7])
def test_fit_gameweek_at_or_after_target_is_refused(week: int) -> None:
    with pytest.raises(DefconComponentError, match="precede"):
        _fit((_row(gameweek=week),))


@pytest.mark.parametrize("instant", [DEADLINE, "2026-10-10T10:00:01Z"])
def test_fit_kickoff_at_or_after_deadline_is_refused(instant: str) -> None:
    with pytest.raises(DefconComponentError, match="precede"):
        _fit((_row(kickoff_utc=instant),))


def test_locked_season_is_refused_before_using_its_award() -> None:
    with pytest.raises(DefconComponentError, match="2025-26 is forbidden"):
        _fit((_row(season="2025-26", awarded_points=-1),))


def test_duplicate_player_fixture_is_not_silently_counted_twice() -> None:
    with pytest.raises(DefconComponentError, match="duplicated"):
        _fit((_row(), _row()))


def test_missing_required_position_refuses_instead_of_zero_imputation() -> None:
    with pytest.raises(DefconComponentError, match="required position"):
        _fit((_row(),), frozenset({"DEF", "MID"}))


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_nonblank_term_refuses_invalid_appearance(value: float | None) -> None:
    with pytest.raises(DefconComponentError, match="published appearance"):
        _term(_fit((_row(),)), appearance_probability=value)


@pytest.mark.parametrize(
    "changes", [{"minutes": -1}, {"awarded_points": 1}, {"position": "UNKNOWN"}, {"gameweek": True}]
)
def test_corrupt_fit_row_is_not_an_eligible_observation(changes: dict[str, object]) -> None:
    with pytest.raises(DefconComponentError):
        _fit((_row(**changes),))


def test_position_rates_are_separate_and_counts_are_read_only() -> None:
    rates = _fit((_row(), _row(102, position="MID", awarded_points=0)), frozenset({"DEF", "MID"}))
    assert rates.rate(101, "DEF") == 1
    assert rates.rate(102, "MID") == 0
    with pytest.raises(TypeError):
        rates.position_appearances["DEF"] = 100  # type: ignore[index]


def test_omitted_direct_control_appearance_has_zero_term() -> None:
    assert _term(_fit((_row(),)), appearance_probability=None) == 0

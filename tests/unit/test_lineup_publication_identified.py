"""A weighted fifteen is valued on the device solver's integer choice and rank rules."""

import pytest

from squadopt.application.advice import _attributed_gains
from squadopt.application.lineup_publication import best_eleven_basis

IdentifiedPlayer = tuple[str, float, float, bool, bool, int]
POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _formation_tie(defender: float, midfielder: float) -> list[IdentifiedPlayer]:
    base = [10, 0, 6, 6, 6, 5, 0, 6, 6, 6, 4, 0, 6, 6, 6]
    choice = [float(points) for points in base]
    choice[5], choice[10] = defender, midfielder
    return [
        (position, chosen_on, float(points), True, True, identity)
        for identity, (position, chosen_on, points) in enumerate(
            zip(POSITIONS, choice, base, strict=True), 1
        )
    ]


@pytest.mark.parametrize("choice", [(5.0, 5.0), (5.004, 5.005)])
def test_cross_formation_ties_keep_the_lower_rank_starter(
    choice: tuple[float, float],
) -> None:
    # 4-3-3 with defender 6 and 3-4-3 with midfielder 11 have equal starter
    # contributions. At 5.004/5.005 the separately rounded bench coefficients
    # make them equal too: 5004-500 == 5005-501. Their base points differ by one.
    squad = _formation_tie(*choice)
    assert best_eleven_basis(squad) == 79.0
    assert best_eleven_basis(reversed(squad)) == 79.0


def test_an_equal_formation_does_not_discard_a_weighted_move_gain() -> None:
    squad = _formation_tie(5.0, 5.0)
    lookup = {identity: (position, basis) for position, _, basis, _, _, identity in squad}
    choice = {identity: points for _, points, _, _, _, identity in squad}
    lookup[16], choice[16] = ("FWD", 7.0), 7.0
    # The same tie occurs before and after replacing the 6-point forward with a
    # 7-point one. The proved plan scores 80; this one-point move remains measurable.
    assert _attributed_gains(
        [(15, 16)], held=list(range(1, 16)), lookup=lookup, choice=choice, expected_total=80.0
    ) == [1.0]


@pytest.mark.parametrize("points", [(1.0004, 1.0005, 0.0), (-1.0005, -1.0004, -2.0)])
def test_choice_rounds_half_up_on_both_sides_of_zero(
    points: tuple[float, float, float],
) -> None:
    lower_id, higher_id, other = points
    squad: list[IdentifiedPlayer] = [
        (position, other, 1.0, True, True, identity)
        for identity, position in enumerate(POSITIONS, 1)
    ]
    squad[0] = ("GK", lower_id, 3.0, True, True, 1)
    squad[2] = ("DEF", higher_id, 7.0, True, True, 3)
    # Both start. Half-up gives defender 3 the higher captain coefficient, even
    # when Python's half-even round would tie it with goalkeeper 1.
    assert best_eleven_basis(squad) == 26.0  # 3 + 7 + nine ones, plus captain 7.


@pytest.mark.parametrize("chip, expected", [(None, 16.0), ("bboost", 29.0), ("3xc", 19.0)])
def test_negative_chip_terms_preserve_the_restricted_captain_choice(
    chip: str | None, expected: float
) -> None:
    squad: list[IdentifiedPlayer] = [
        (position, 1.0, 1.0, True, False, identity)
        for identity, position in enumerate(POSITIONS, 1)
    ]
    squad[0] = ("GK", -0.2, 10.0, True, True, 1)
    squad[1] = ("GK", 0.0, 1.0, True, False, 2)
    squad[2] = ("DEF", -0.3, 3.0, True, True, 3)
    for index in range(3, 7):
        squad[index] = ("DEF", -2.0, 1.0, True, False, index + 1)
    # Defender 3 must start and can captain. Taking goalkeeper 1 would add a
    # negative starter term. Negative chip auxiliaries earn no objective bonus.
    assert best_eleven_basis(squad, chip=chip) == expected


@pytest.mark.parametrize("chip, expected", [(None, 90.0), ("bboost", 118.0), ("3xc", 100.0)])
def test_an_eligible_captain_can_displace_a_higher_choice_starter(
    chip: str | None, expected: float
) -> None:
    squad: list[IdentifiedPlayer] = [
        (position, 7.0, 7.0, True, False, identity)
        for identity, position in enumerate(POSITIONS, 1)
    ]
    squad[1] = ("GK", 6.9, 10.0, True, True, 2)
    assert best_eleven_basis(squad, chip=chip) == expected
    # The only eligible armband cannot be placed on the bench or on a barred starter.
    squad[1] = ("GK", 6.9, 10.0, False, True, 2)
    assert best_eleven_basis(squad, chip=chip) is None


def test_the_unidentified_legacy_formation_order_is_preserved() -> None:
    squad = _formation_tie(5.0, 5.0)
    assert best_eleven_basis(player[:5] for player in squad) == 78.0
